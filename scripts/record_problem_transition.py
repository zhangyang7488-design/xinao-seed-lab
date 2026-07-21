#!/usr/bin/env python3
"""Append typed problem facts through the canonical task-run event chain.

This is a thin adapter, not another ledger.  It writes one immutable,
hash-bound transition artifact and asks the existing ``task_run.py event``
command to append the authoritative reference.  The ``finish`` wrapper records
non-verified completion criteria before delegating to ``task_run.py finish``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.execution_contract import artifact_json_bytes  # noqa: E402
from services.agent_runtime.system_awareness_consumer import (  # noqa: E402
    PROBLEM_TRANSITION_VERSION,
    SystemAwarenessError,
    build_problem_transition,
    scan_task_run_problem_append_snapshot,
    validate_problem_transition_append,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRANSITIONS = (
    "problem_observed",
    "repair_adopted",
    "consumer_effect_verified",
    "effect_window_completed",
    "problem_close_requested",
)
_TERMINAL_STATUSES = ("verified", "partial", "blocked", "unverified")
_PROBLEM_TERMINALS = frozenset({"partial", "blocked", "unverified"})


class ProblemTransitionAdapterError(RuntimeError):
    """The adapter cannot make the requested task-run mutation safely."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "PROBLEM_TRANSITION_ADAPTER_FAILED",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _load_object(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProblemTransitionAdapterError(f"cannot read {field}: {path}") from exc
    if not isinstance(value, dict):
        raise ProblemTransitionAdapterError(f"{field} must be a JSON object")
    return value


def _atomic_exact_json(path: Path, value: Mapping[str, object]) -> str:
    raw = artifact_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        observed = path.read_bytes()
        if observed != raw:
            raise ProblemTransitionAdapterError(
                f"problem transition carrier already contains different bytes: {path}"
            )
        return hashlib.sha256(observed).hexdigest()
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Link the fully fsynced temporary inode into its deterministic
            # final name without replacing an identical concurrent writer.
            # This keeps readers from ever observing partial JSON and avoids
            # Windows os.replace races on the same destination.
            os.link(temporary_path, path)
        except FileExistsError:
            observed = path.read_bytes()
            if observed != raw:
                raise ProblemTransitionAdapterError(
                    f"problem transition carrier already contains different bytes: {path}"
                )
    finally:
        temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


def _hash_bound_ref(reference: str, field: str) -> str:
    if "#sha256=" not in reference:
        raise ProblemTransitionAdapterError(f"{field} must be hash-bound")
    path_text, expected = reference.rsplit("#sha256=", 1)
    if not _SHA256_RE.fullmatch(expected):
        raise ProblemTransitionAdapterError(f"{field} has an invalid sha256")
    try:
        observed = hashlib.sha256(Path(path_text).read_bytes()).hexdigest()
    except OSError as exc:
        raise ProblemTransitionAdapterError(f"{field} cannot be read") from exc
    if observed != expected:
        raise ProblemTransitionAdapterError(f"{field} sha256 drifted")
    return reference


def _verified_refs(values: Sequence[str]) -> list[str]:
    return [_hash_bound_ref(value, f"evidence_refs[{index}]") for index, value in enumerate(values)]


def _run_cli(task_run_cli: Path, task_run_root: Path, arguments: Sequence[str]) -> dict[str, Any]:
    command = [
        sys.executable,
        str(task_run_cli.resolve(strict=True)),
        "--root",
        str(task_run_root.resolve(strict=False)),
        *arguments,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        reason_code = "PROBLEM_TRANSITION_ADAPTER_FAILED"
        if "event head changed" in detail:
            reason_code = "TASK_RUN_EVENT_HEAD_CHANGED"
        elif "unrecognized arguments:" in detail and (
            "--expected-events-count" in detail or "--expected-events-sha256" in detail
        ):
            reason_code = "TASK_RUN_EVENT_HEAD_CAS_UNAVAILABLE"
        raise ProblemTransitionAdapterError(
            f"task-run command failed exit={completed.returncode}: {detail}",
            reason_code=reason_code,
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProblemTransitionAdapterError("task-run command returned non-JSON output") from exc
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise ProblemTransitionAdapterError("task-run command did not return ok=true")
    return value


def _run_dir(task_run_root: Path, task_run_id: str) -> Path:
    root = task_run_root.resolve(strict=False)
    candidate = (root / task_run_id).resolve(strict=False)
    if candidate.parent != root:
        raise ProblemTransitionAdapterError("task_run_id escaped task_run_root")
    return candidate


def _problem_rows(snapshot: Mapping[str, object]) -> list[dict[str, Any]]:
    projection = snapshot.get("problem_projection")
    rows = projection.get("problems") if isinstance(projection, Mapping) else None
    if not isinstance(rows, list):
        raise ProblemTransitionAdapterError("problem projection has no problems[]")
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _draft_problem_ref(config: Mapping[str, object]) -> str:
    draft = build_problem_transition(
        transition_type="problem_observed",
        task_run_id=str(config["task_run_id"]),
        task_run_event_id="evt-problem-ref-draft",
        side_effect_id="se:problem-ref-draft",
        family_signature=str(config["family_signature"]),
        governing_cause=str(config["governing_cause"]),
        work_key=str(config["work_key"]),
        component_id=str(config["component_id"]),
        problem_generation=1,
        owner_id=str(config["owner_id"]),
        systemic_signals=config.get("systemic_signals"),  # type: ignore[arg-type]
    )
    return str(draft["problem_ref"])


def _derive_generations(
    *,
    transition_type: str,
    current: Mapping[str, object] | None,
    explicit_problem_generation: int | None,
    explicit_repair_generation: int | None,
) -> tuple[int, int]:
    if explicit_problem_generation is not None:
        problem_generation = explicit_problem_generation
    elif transition_type == "problem_observed":
        if current is None:
            problem_generation = 1
        elif current.get("status") in {"effective", "retired"}:
            problem_generation = int(current.get("problem_generation") or 0) + 1
        else:
            problem_generation = int(current.get("problem_generation") or 1)
    else:
        if current is None:
            raise ProblemTransitionAdapterError(
                f"{transition_type} requires an existing problem_ref"
            )
        if current.get("status") in {"effective", "retired"}:
            raise ProblemTransitionAdapterError(
                f"{transition_type} cannot mutate a closed problem generation"
            )
        problem_generation = int(current.get("problem_generation") or 0)

    current_repair = int(current.get("repair_generation") or 0) if current else 0
    if transition_type == "problem_observed":
        repair_generation = 0
    elif explicit_repair_generation is not None:
        repair_generation = explicit_repair_generation
    elif transition_type == "repair_adopted":
        repair_generation = current_repair + 1
    else:
        repair_generation = current_repair
    return problem_generation, repair_generation


def _existing_transition(
    events: Sequence[Mapping[str, object]],
    config: Mapping[str, object],
    *,
    problem_ref: str,
    evidence_refs: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    for raw_event in reversed(events):
        event = dict(raw_event)
        if event.get("phase") != "problem_transition_recorded":
            continue
        refs = event.get("evidence_refs")
        if not isinstance(refs, list):
            continue
        for reference in refs:
            reference_text = str(reference)
            try:
                _hash_bound_ref(reference_text, "existing problem transition")
                payload = _load_object(
                    Path(reference_text.rsplit("#sha256=", 1)[0]),
                    "existing problem transition",
                )
            except ProblemTransitionAdapterError:
                continue
            if (
                payload.get("schema_version") != PROBLEM_TRANSITION_VERSION
                or payload.get("transition_type") != config["transition_type"]
                or payload.get("problem_ref") != problem_ref
            ):
                continue
            explicit_problem_generation = config.get("problem_generation")
            explicit_repair_generation = config.get("repair_generation")
            if (
                explicit_problem_generation is not None
                and payload.get("problem_generation") != explicit_problem_generation
            ) or (
                explicit_repair_generation is not None
                and payload.get("repair_generation") != explicit_repair_generation
            ):
                continue
            requested_side_effect = str(config.get("side_effect_id") or "")
            if requested_side_effect and payload.get("side_effect_id") != requested_side_effect:
                continue
            try:
                expected = build_problem_transition(
                    transition_type=str(config["transition_type"]),
                    task_run_id=str(config["task_run_id"]),
                    task_run_event_id=str(payload.get("task_run_event_id") or ""),
                    side_effect_id=str(payload.get("side_effect_id") or ""),
                    problem_ref=problem_ref,
                    problem_generation=payload.get("problem_generation"),  # type: ignore[arg-type]
                    repair_generation=payload.get("repair_generation"),  # type: ignore[arg-type]
                    family_signature=str(config["family_signature"]),
                    governing_cause=str(config["governing_cause"]),
                    work_key=str(config["work_key"]),
                    component_id=str(config["component_id"]),
                    owner_id=str(config["owner_id"]),
                    systemic_signals=config.get("systemic_signals"),  # type: ignore[arg-type]
                    repair_decision=str(config.get("repair_decision") or ""),
                    repair_level=str(config.get("repair_level") or ""),
                    terminal_status=str(config.get("terminal_status") or ""),
                    consumer_id=str(config.get("consumer_id") or ""),
                    window_id=str(config.get("window_id") or ""),
                    window_completed=config.get("window_completed") is True,
                    passed=config.get("passed") is True,
                    relevant_to_parent=config.get("relevant_to_parent"),  # type: ignore[arg-type]
                    expected_net_benefit_positive=config.get("expected_net_benefit_positive"),  # type: ignore[arg-type]
                    evidence_refs=evidence_refs,
                )
            except SystemAwarenessError:
                continue
            if expected == payload:
                observed = payload.get("transition_type") == "problem_observed"
                if (
                    payload.get("task_run_id") != event.get("run_id")
                    or payload.get("task_run_event_id") != event.get("event_id")
                    or payload.get("side_effect_id") != event.get("side_effect_id")
                    or payload.get("work_key") != event.get("target")
                    or event.get("kind") != ("failure" if observed else "result")
                    or event.get("exit_code") != (1 if observed else 0)
                ):
                    raise ProblemTransitionAdapterError(
                        "existing problem transition disagrees with its task-run event"
                    )
                return payload, event, reference_text
    return None


def _replay_existing_event(
    *,
    task_run_cli: Path,
    task_run_root: Path,
    event: Mapping[str, object],
) -> dict[str, Any]:
    arguments = [
        "event",
        "--run-id",
        str(event["run_id"]),
        "--event-id",
        str(event["event_id"]),
        "--actor",
        str(event["actor"]),
        "--kind",
        str(event["kind"]),
        "--phase",
        str(event["phase"]),
        "--summary",
        str(event["summary"]),
    ]
    for reference in event.get("evidence_refs") or []:  # type: ignore[union-attr]
        arguments.extend(["--evidence-ref", str(reference)])
    for option, field in (
        ("--target", "target"),
        ("--exit-code", "exit_code"),
        ("--duration-ms", "duration_ms"),
        ("--retry-class", "retry_class"),
        ("--side-effect-id", "side_effect_id"),
    ):
        if event.get(field) is not None:
            arguments.extend([option, str(event[field])])
    return _run_cli(task_run_cli, task_run_root, arguments)


def _record_transition(config: Mapping[str, object]) -> dict[str, Any]:
    transition_type = str(config["transition_type"])
    task_run_root = Path(str(config["task_run_root"]))
    task_run_id = str(config["task_run_id"])
    run_dir = _run_dir(task_run_root, task_run_id)
    if not run_dir.is_dir():
        raise ProblemTransitionAdapterError(f"task run does not exist: {run_dir}")
    problem_ref = str(config.get("problem_ref") or "").upper()
    if not problem_ref:
        if transition_type != "problem_observed":
            raise ProblemTransitionAdapterError(f"{transition_type} requires --problem-ref")
        problem_ref = _draft_problem_ref(config)

    evidence_refs = _verified_refs(list(config.get("evidence_refs") or []))
    snapshot = scan_task_run_problem_append_snapshot(run_dir)
    snapshot_events = snapshot.get("events")
    if not isinstance(snapshot_events, list) or not all(
        isinstance(event, Mapping) for event in snapshot_events
    ):
        raise ProblemTransitionAdapterError("problem append snapshot has no valid events[]")
    existing = _existing_transition(
        snapshot_events,
        config,
        problem_ref=problem_ref,
        evidence_refs=evidence_refs,
    )
    if existing is not None:
        transition, event, transition_ref = existing
        task_result = _replay_existing_event(
            task_run_cli=Path(str(config["task_run_cli"])),
            task_run_root=task_run_root,
            event=event,
        )
        return {
            "ok": True,
            "task_run_id": task_run_id,
            "event_id": transition["task_run_event_id"],
            "replayed": task_result.get("replayed") is True,
            "transition_type": transition_type,
            "transition_id": transition["transition_id"],
            "problem_ref": problem_ref,
            "problem_generation": transition["problem_generation"],
            "repair_generation": transition["repair_generation"],
            "transition_ref": transition_ref,
            "authority": False,
            "completion_claim_allowed": False,
        }

    current = next(
        (row for row in _problem_rows(snapshot) if row.get("problem_ref") == problem_ref),
        None,
    )
    problem_generation, repair_generation = _derive_generations(
        transition_type=transition_type,
        current=current,
        explicit_problem_generation=config.get("problem_generation"),  # type: ignore[arg-type]
        explicit_repair_generation=config.get("repair_generation"),  # type: ignore[arg-type]
    )
    identity_seed = {
        "transition_type": transition_type,
        "task_run_id": task_run_id,
        "problem_ref": problem_ref,
        "problem_generation": problem_generation,
        "repair_generation": repair_generation,
        "family_signature": config["family_signature"],
        "governing_cause": config["governing_cause"],
        "work_key": config["work_key"],
        "component_id": config["component_id"],
        "owner_id": config["owner_id"],
        "systemic_signals": config.get("systemic_signals") or {},
        "repair_decision": config.get("repair_decision") or "",
        "repair_level": config.get("repair_level") or "",
        "terminal_status": config.get("terminal_status") or "",
        "consumer_id": config.get("consumer_id") or "",
        "window_id": config.get("window_id") or "",
        "window_completed": config.get("window_completed") is True,
        "passed": config.get("passed") is True,
        "relevant_to_parent": config.get("relevant_to_parent"),
        "expected_net_benefit_positive": config.get("expected_net_benefit_positive"),
        "evidence_refs": evidence_refs,
        "requested_side_effect_id": config.get("side_effect_id") or "",
    }
    identity_sha = hashlib.sha256(artifact_json_bytes(identity_seed)).hexdigest()
    event_id = f"evt-problem-{identity_sha[:32]}"
    side_effect_id = str(config.get("side_effect_id") or "") or (
        f"se:problem:{transition_type}:{problem_ref}:g{problem_generation}:"
        f"r{repair_generation}:{identity_sha[:16]}"
    )
    transition = build_problem_transition(
        transition_type=transition_type,
        task_run_id=task_run_id,
        task_run_event_id=event_id,
        side_effect_id=side_effect_id,
        problem_ref=problem_ref,
        problem_generation=problem_generation,
        repair_generation=repair_generation,
        family_signature=str(config["family_signature"]),
        governing_cause=str(config["governing_cause"]),
        work_key=str(config["work_key"]),
        component_id=str(config["component_id"]),
        owner_id=str(config["owner_id"]),
        systemic_signals=config.get("systemic_signals"),  # type: ignore[arg-type]
        repair_decision=str(config.get("repair_decision") or ""),
        repair_level=str(config.get("repair_level") or ""),
        terminal_status=str(config.get("terminal_status") or ""),
        consumer_id=str(config.get("consumer_id") or ""),
        window_id=str(config.get("window_id") or ""),
        window_completed=config.get("window_completed") is True,
        passed=config.get("passed") is True,
        relevant_to_parent=config.get("relevant_to_parent"),  # type: ignore[arg-type]
        expected_net_benefit_positive=config.get("expected_net_benefit_positive"),  # type: ignore[arg-type]
        evidence_refs=evidence_refs,
    )
    preappend = validate_problem_transition_append(
        run_dir,
        transition,
        expected_events_count=int(snapshot["expected_events_count"]),
        expected_events_sha256=str(snapshot["events_sha256"]),
    )
    output_dir = Path(str(config.get("output_dir") or (run_dir / "problem_transitions")))
    output = output_dir.resolve(strict=False) / f"{event_id}.json"
    transition_sha = _atomic_exact_json(output, transition)
    transition_ref = f"{output.resolve(strict=True)}#sha256={transition_sha}"
    observed = transition_type == "problem_observed"
    task_result = _run_cli(
        Path(str(config["task_run_cli"])),
        task_run_root,
        [
            "event",
            "--run-id",
            task_run_id,
            "--event-id",
            event_id,
            "--actor",
            str(config["actor"]),
            "--kind",
            "failure" if observed else "result",
            "--phase",
            "problem_transition_recorded",
            "--summary",
            f"problem transition {transition_type} {problem_ref} "
            f"g{problem_generation} r{repair_generation}",
            "--evidence-ref",
            transition_ref,
            "--target",
            str(config["work_key"]),
            "--exit-code",
            "1" if observed else "0",
            "--retry-class",
            "deterministic" if observed else "none",
            "--side-effect-id",
            side_effect_id,
            "--expected-events-count",
            str(preappend["expected_events_count"]),
            "--expected-events-sha256",
            str(preappend["events_sha256"]),
        ],
    )
    return {
        "ok": True,
        "task_run_id": task_run_id,
        "event_id": event_id,
        "replayed": task_result.get("replayed") is True,
        "transition_type": transition_type,
        "transition_id": transition["transition_id"],
        "problem_ref": problem_ref,
        "problem_generation": problem_generation,
        "repair_generation": repair_generation,
        "transition_ref": transition_ref,
        "authority": False,
        "completion_claim_allowed": False,
    }


def _tri_state(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _signals(values: Sequence[str]) -> dict[str, bool]:
    return {value: True for value in values}


def _record_config(args: argparse.Namespace) -> dict[str, object]:
    return {
        "task_run_cli": args.task_run_cli,
        "task_run_root": args.task_run_root,
        "task_run_id": args.task_run_id,
        "output_dir": args.output_dir,
        "actor": args.actor,
        "owner_id": args.owner_id,
        "transition_type": args.transition_type,
        "family_signature": args.family_signature,
        "governing_cause": args.governing_cause,
        "work_key": args.work_key,
        "component_id": args.component_id,
        "problem_ref": args.problem_ref,
        "problem_generation": args.problem_generation,
        "repair_generation": args.repair_generation,
        "systemic_signals": _signals(args.systemic_signal),
        "repair_decision": args.repair_decision,
        "repair_level": args.repair_level,
        "terminal_status": args.terminal_status,
        "consumer_id": args.consumer_id,
        "window_id": args.window_id,
        "window_completed": args.window_completed,
        "passed": args.passed,
        "relevant_to_parent": _tri_state(args.relevant_to_parent),
        "expected_net_benefit_positive": _tri_state(args.expected_net_benefit_positive),
        "evidence_refs": args.evidence_ref,
        "side_effect_id": args.side_effect_id,
    }


def _valid_hash_refs(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    accepted: list[str] = []
    for value in values:
        try:
            accepted.append(_hash_bound_ref(str(value), "criterion evidence"))
        except ProblemTransitionAdapterError:
            continue
    return accepted


def _has_terminal_transition(run_dir: Path, status: str) -> bool:
    try:
        text = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("phase") != "problem_transition_recorded":
            continue
        refs = event.get("evidence_refs")
        if not isinstance(refs, list):
            continue
        for reference in refs:
            try:
                reference_text = _hash_bound_ref(str(reference), "terminal problem transition")
                path_text = reference_text.rsplit("#sha256=", 1)[0]
                payload = _load_object(Path(path_text), "problem transition")
            except ProblemTransitionAdapterError:
                continue
            if (
                payload.get("schema_version") == PROBLEM_TRANSITION_VERSION
                and payload.get("transition_type") == "problem_observed"
                and payload.get("terminal_status") == status
                and payload.get("task_run_id") == event.get("run_id")
                and payload.get("task_run_event_id") == event.get("event_id")
                and payload.get("side_effect_id") == event.get("side_effect_id")
                and payload.get("work_key") == event.get("target")
                and event.get("kind") == "failure"
                and event.get("exit_code") == 1
            ):
                return True
    return False


def _finish(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = _run_dir(args.task_run_root, args.task_run_id)
    state = _load_object(run_dir / "state.json", "state")
    current_status = str(state.get("status") or "")
    if current_status != "in_progress":
        if current_status != args.status:
            raise ProblemTransitionAdapterError(
                f"run already closed with a different status: {current_status}"
            )
        if args.status in _PROBLEM_TERMINALS and not _has_terminal_transition(run_dir, args.status):
            raise ProblemTransitionAdapterError(
                "closed non-verified run lacks a typed terminal problem transition"
            )
        return {
            "ok": True,
            "task_run_id": args.task_run_id,
            "status": args.status,
            "replayed": True,
            "problem_transitions": [],
        }

    recorded: list[dict[str, Any]] = []
    if args.status in _PROBLEM_TERMINALS:
        evidence = _load_object(run_dir / "evidence.json", "evidence")
        raw_criteria = evidence.get("criteria")
        criteria = raw_criteria if isinstance(raw_criteria, list) else []
        unmet = [
            dict(row)
            for row in criteria
            if isinstance(row, Mapping) and row.get("verdict") != "pass"
        ]
        if not unmet:
            unmet = [
                {
                    "index": 0,
                    "criterion": "task run ended without a verified terminal outcome",
                    "observations": [],
                }
            ]
        work_key = args.work_key or f"wk:task-run:{args.task_run_id}"
        for criterion in unmet:
            index = int(criterion.get("index") or 0)
            criterion_text = str(criterion.get("criterion") or "unknown completion criterion")
            criterion_sha = hashlib.sha256(criterion_text.encode("utf-8")).hexdigest()[:12]
            observations = criterion.get("observations")
            last = observations[-1] if isinstance(observations, list) and observations else {}
            proof_refs = (
                _valid_hash_refs(last.get("evidence_refs")) if isinstance(last, Mapping) else []
            )
            recorded.append(
                _record_transition(
                    {
                        "task_run_cli": args.task_run_cli,
                        "task_run_root": args.task_run_root,
                        "task_run_id": args.task_run_id,
                        "output_dir": args.output_dir,
                        "actor": args.actor,
                        "owner_id": args.owner_id,
                        "transition_type": "problem_observed",
                        "family_signature": "task-run-completion-criterion",
                        "governing_cause": f"completion-criterion-{index}-{criterion_sha}",
                        "work_key": work_key,
                        "component_id": args.component_id,
                        "problem_ref": "",
                        "problem_generation": None,
                        "repair_generation": None,
                        "systemic_signals": {},
                        "repair_decision": "",
                        "repair_level": "",
                        "terminal_status": args.status,
                        "consumer_id": "",
                        "window_id": "",
                        "window_completed": False,
                        "passed": False,
                        "relevant_to_parent": True,
                        "expected_net_benefit_positive": None,
                        "evidence_refs": proof_refs,
                        "side_effect_id": "",
                    }
                )
            )

    finish_arguments = [
        "finish",
        "--run-id",
        args.task_run_id,
        "--status",
        args.status,
        "--summary",
        args.summary,
        "--actor",
        args.actor,
    ]
    for reference in args.evidence_ref:
        finish_arguments.extend(["--evidence-ref", reference])
    result = _run_cli(args.task_run_cli, args.task_run_root, finish_arguments)
    return {
        "ok": True,
        "task_run_id": args.task_run_id,
        "status": args.status,
        "replayed": False,
        "problem_transitions": recorded,
        "task_run_result": result,
    }


def _common_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--task-run-cli", type=Path, required=True)
    common.add_argument("--task-run-root", type=Path, required=True)
    common.add_argument("--task-run-id", required=True)
    common.add_argument("--output-dir", type=Path)
    common.add_argument("--actor", default="codex-owner")
    common.add_argument("--owner-id", default="codex-owner")
    return common


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    common = _common_parser()

    record = sub.add_parser("record", parents=[common])
    record.add_argument("--transition-type", choices=_TRANSITIONS, required=True)
    record.add_argument("--family-signature", required=True)
    record.add_argument("--governing-cause", required=True)
    record.add_argument("--work-key", required=True)
    record.add_argument("--component-id", required=True)
    record.add_argument("--problem-ref")
    record.add_argument("--problem-generation", type=int)
    record.add_argument("--repair-generation", type=int)
    record.add_argument(
        "--systemic-signal",
        action="append",
        choices=(
            "capability_gap",
            "missing_consumer",
            "governing_assumption",
            "cross_entrypoint",
            "control_boundary",
        ),
        default=[],
    )
    record.add_argument(
        "--repair-decision", choices=("small_repair", "structural_repair", "no_build")
    )
    record.add_argument(
        "--repair-level",
        choices=(
            "local_patch",
            "structural_chain_repair",
            "governing_boundary_repair",
            "no_build",
        ),
    )
    record.add_argument("--terminal-status", choices=sorted(_PROBLEM_TERMINALS))
    record.add_argument("--consumer-id")
    record.add_argument("--window-id")
    record.add_argument("--window-completed", action="store_true")
    record.add_argument("--passed", action="store_true")
    record.add_argument(
        "--relevant-to-parent", choices=("true", "false", "unknown"), default="unknown"
    )
    record.add_argument(
        "--expected-net-benefit-positive",
        choices=("true", "false", "unknown"),
        default="unknown",
    )
    record.add_argument("--evidence-ref", action="append", default=[])
    record.add_argument("--side-effect-id")

    finish = sub.add_parser("finish", parents=[common])
    finish.add_argument("--status", choices=_TERMINAL_STATUSES, required=True)
    finish.add_argument("--summary", required=True)
    finish.add_argument("--evidence-ref", action="append", default=[])
    finish.add_argument("--work-key")
    finish.add_argument("--component-id", default="canonical-task-run-finish")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        value = (
            _record_transition(_record_config(args)) if args.command == "record" else _finish(args)
        )
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        SystemAwarenessError,
        ProblemTransitionAdapterError,
    ) as exc:
        reason_code = getattr(exc, "reason_code", "PROBLEM_TRANSITION_ADAPTER_FAILED")
        print(
            json.dumps(
                {"ok": False, "reason_code": reason_code, "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
