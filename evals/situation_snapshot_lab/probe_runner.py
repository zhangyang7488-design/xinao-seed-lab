"""Serial, cold runner for the first Situation Snapshot falsification pilot.

The runner records transport, thread, tool, and filesystem facts.  It does not
score a continuing subject.  The B4 situation transition is explicitly an
oracle intervention: this pilot asks whether a correct revised world is kept,
not whether Codex can autonomously construct that revision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.situation_snapshot_lab.codex_exec_driver import (
    CodexExecConfig,
    CodexExecResult,
    invoke_first,
    invoke_resume,
)
from evals.situation_snapshot_lab.probe_packets import (
    action_boundary_snapshots,
    continuity_probe_snapshots,
    render_probe_prompt,
    role_labeled_dialogue_prefix,
)

RUN_SCHEMA_VERSION = "codex.situation_snapshot_lab.pilot_run.v1"
EXPECTED_CODEX_VERSION = "codex-cli 0.147.0"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SAFE_NON_EFFECT_ITEM_TYPES = frozenset({"agent_message", "reasoning"})
_TASK_BIRTH_ITEM_TYPES = frozenset({"plan", "plan_update"})


class ProbeRunError(RuntimeError):
    """The pilot boundary or a serial trajectory failed."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _safe_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ProbeRunError(f"{field} is not a bounded identifier")
    return value


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as tmp:
        temporary = Path(tmp.name)
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(temporary, path)


def _write_json(path: Path, payload: object) -> None:
    _atomic_write(path, _canonical_json_bytes(payload) + b"\n")


def _write_text(path: Path, payload: str) -> None:
    _atomic_write(path, payload.encode("utf-8"))


def _path_identity(path: Path) -> dict[str, object]:
    lexical = path.absolute()
    try:
        metadata = lexical.lstat()
    except OSError:
        return {"path": str(lexical), "kind": "missing"}
    if stat.S_ISLNK(metadata.st_mode):
        try:
            target = os.readlink(lexical)
        except OSError:
            target = None
        return {"path": str(lexical), "kind": "symlink", "target": target}
    if stat.S_ISREG(metadata.st_mode):
        return {
            "path": str(lexical),
            "kind": "file",
            "bytes": metadata.st_size,
            "sha256": _hash_file(lexical),
        }
    if stat.S_ISDIR(metadata.st_mode):
        return {"path": str(lexical), "kind": "directory"}
    return {"path": str(lexical), "kind": "other"}


def _tree_manifest(root: Path, *, exclude_git: bool = False) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    if not root.exists():
        return {"root": str(root), "entries": [], "tree_sha256": _sha256_bytes(b"[]")}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if exclude_git and (relative == ".git" or relative.startswith(".git/")):
            continue
        identity = _path_identity(path)
        identity.pop("path", None)
        identity["relative_path"] = relative
        rows.append(identity)
    return {
        "root": str(root.resolve()),
        "entries": rows,
        "tree_sha256": _sha256_bytes(_canonical_json_bytes(rows)),
    }


def _run_git(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    neutral_root = (cwd / ".git" / "situation-snapshot-lab-neutral").absolute()
    return subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={neutral_root / 'hooks'}",
            "-c",
            f"core.excludesFile={neutral_root / 'excludes'}",
            "-c",
            f"core.attributesFile={neutral_root / 'attributes'}",
            *arguments,
        ],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _initialize_git(cwd: Path) -> None:
    initial = _run_git(cwd, "init", "--quiet")
    if initial.returncode != 0:
        raise ProbeRunError(f"git init --quiet failed for {cwd}")
    neutral_root = cwd / ".git" / "situation-snapshot-lab-neutral"
    (neutral_root / "hooks").mkdir(parents=True)
    (neutral_root / "excludes").write_bytes(b"")
    (neutral_root / "attributes").write_bytes(b"")
    commands = (
        ("config", "user.name", "Situation Snapshot Lab"),
        ("config", "user.email", "situation-snapshot-lab@example.invalid"),
        ("config", "core.autocrlf", "false"),
        ("config", "commit.gpgsign", "false"),
        ("add", "--all"),
        ("commit", "--quiet", "-m", "sealed lab fixture"),
    )
    for arguments in commands:
        completed = _run_git(cwd, *arguments)
        if completed.returncode != 0:
            raise ProbeRunError(f"git {' '.join(arguments)} failed for {cwd}")


def _git_observation(cwd: Path) -> dict[str, object]:
    head = _run_git(cwd, "rev-parse", "HEAD")
    status = _run_git(cwd, "status", "--porcelain=v1", "--untracked-files=all")
    if head.returncode != 0 or status.returncode != 0:
        raise ProbeRunError(f"git observation failed for {cwd}")
    status_bytes = status.stdout.replace(b"\r\n", b"\n")
    return {
        "head": head.stdout.decode("ascii", errors="strict").strip(),
        "status_utf8": status_bytes.decode("utf-8", errors="replace"),
        "status_sha256": _sha256_bytes(status_bytes),
    }


@dataclass(frozen=True)
class ProbeRunConfig:
    """Explicit local inputs for one serial pilot run."""

    run_id: str
    run_root: Path
    allowed_output_parent: Path
    source_root: Path
    codex_executable: Path
    auth_target: Path
    model: str = "gpt-5.6-sol"
    model_reasoning_effort: str = "max"
    timeout_seconds: float = 600.0
    expected_codex_version: str = EXPECTED_CODEX_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        for field_name in (
            "run_root",
            "allowed_output_parent",
            "source_root",
            "codex_executable",
            "auth_target",
        ):
            value = Path(os.path.abspath(os.fspath(getattr(self, field_name))))
            object.__setattr__(self, field_name, value)
        if not self.model.strip():
            raise ProbeRunError("model must not be empty")
        if self.timeout_seconds <= 0:
            raise ProbeRunError("timeout_seconds must be positive")


def _strict_descendant(path: Path, parent: Path) -> bool:
    try:
        relative = path.relative_to(parent)
    except ValueError:
        return False
    return bool(relative.parts)


def _verify_path_boundary(config: ProbeRunConfig) -> dict[str, object]:
    try:
        allowed_parent = config.allowed_output_parent.resolve(strict=True)
        source_root = config.source_root.resolve(strict=True)
        auth_target = config.auth_target.resolve(strict=True)
        executable = config.codex_executable.resolve(strict=True)
        run_root = config.run_root.resolve(strict=False)
    except OSError as exc:
        raise ProbeRunError("preflight path identity could not be resolved") from exc
    if not allowed_parent.is_dir() or allowed_parent.parent == allowed_parent:
        raise ProbeRunError("allowed_output_parent must be an existing non-root directory")
    if not _strict_descendant(run_root, allowed_parent):
        raise ProbeRunError("run_root must be a strict descendant of allowed_output_parent")
    if _strict_descendant(run_root, source_root) or _strict_descendant(source_root, run_root):
        raise ProbeRunError("run_root and source_root must be disjoint")
    if auth_target == run_root or _strict_descendant(auth_target, run_root):
        raise ProbeRunError("auth_target must be external to run_root")
    if executable == run_root or _strict_descendant(executable, run_root):
        raise ProbeRunError("codex_executable must be external to run_root")
    return {
        "allowed_output_parent": str(allowed_parent),
        "run_root": str(run_root),
        "source_root": str(source_root),
        "auth_target_external": True,
        "codex_executable_external": True,
        "resolved_path_containment_only": True,
    }


@dataclass(frozen=True)
class _TrackPaths:
    root: Path
    home: Path
    cwd: Path


def verify_codex_binary(config: ProbeRunConfig) -> dict[str, object]:
    """Verify the native executable identity without invoking a model."""

    executable = config.codex_executable
    if not executable.is_file():
        raise ProbeRunError("codex executable is not a regular file")
    completed = subprocess.run(
        [str(executable), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    version = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or version != config.expected_codex_version:
        raise ProbeRunError(
            f"Codex version mismatch: expected {config.expected_codex_version!r}, got {version!r}"
        )
    return {
        "path": str(executable.resolve()),
        "sha256": _hash_file(executable),
        "version": version,
        "entry_mode": "direct_native_without_npm_wrapper_env",
    }


def _load_case(source_root: Path, case_id: str) -> dict[str, object]:
    path = source_root / "evals" / "situation_snapshot_lab" / "semantic_accidents.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for case in payload["cases"]:
        if case["case_id"] == case_id:
            return case
    raise ProbeRunError(f"case not found: {case_id}")


def _prepare_track(
    config: ProbeRunConfig,
    track_id: str,
    *,
    fixture: Path | None = None,
) -> _TrackPaths:
    identity = _safe_id(track_id, "track_id")
    root = config.run_root / "tracks" / identity
    if root.exists():
        raise ProbeRunError(f"track already exists: {identity}")
    home = root / "home"
    cwd = root / "workspace"
    home.mkdir(parents=True)
    cwd.mkdir(parents=True)
    if fixture is not None:
        shutil.copytree(fixture, cwd, dirs_exist_ok=True)
    tiny_l0 = config.source_root / "evals" / "situation_snapshot_lab" / "tiny_l0.md"
    shutil.copyfile(tiny_l0, cwd / "AGENTS.md")
    try:
        (home / "auth.json").symlink_to(config.auth_target)
    except OSError as exc:
        raise ProbeRunError("failed to create caller-owned auth symlink") from exc
    _initialize_git(cwd)
    return _TrackPaths(root=root, home=home, cwd=cwd)


def _driver_config(config: ProbeRunConfig, paths: _TrackPaths, *, sandbox_mode: str) -> CodexExecConfig:
    return CodexExecConfig(
        codex_executable=str(config.codex_executable),
        allowed_lab_root=config.run_root,
        codex_home=paths.home,
        cwd=paths.cwd,
        model=config.model,
        auth_target=config.auth_target,
        sandbox_mode=sandbox_mode,
        approval_policy="never",
        model_reasoning_effort=config.model_reasoning_effort,
        timeout_seconds=config.timeout_seconds,
    )


def _instruction_chain(paths: _TrackPaths) -> dict[str, object]:
    home_agents = paths.home / "AGENTS.md"
    cwd_agents = paths.cwd / "AGENTS.md"
    return {
        "home_global": _path_identity(home_agents),
        "git_root_to_cwd": [_path_identity(cwd_agents)],
        "claim_boundary": "recorded_candidate_chain_not_model_visible_input_proof",
    }


def _mechanical_event_observation(result: CodexExecResult) -> dict[str, object]:
    if result.parsed is None:
        return {
            "item_types": [],
            "task_birth_item_types": [],
            "external_action_item_types": [],
        }
    item_types = [str(row["item_type"]) for row in result.parsed.item_trace]
    task_birth = sorted({item for item in item_types if item in _TASK_BIRTH_ITEM_TYPES})
    external = sorted(
        {
            item
            for item in item_types
            if item not in _SAFE_NON_EFFECT_ITEM_TYPES and item not in _TASK_BIRTH_ITEM_TYPES
        }
    )
    return {
        "item_types": item_types,
        "task_birth_item_types": task_birth,
        "external_action_item_types": external,
    }


def _persist_turn(
    paths: _TrackPaths,
    *,
    sequence_index: int,
    turn_id: str,
    prompt: str,
    carrier: Mapping[str, object],
    result: CodexExecResult,
    workspace_before: Mapping[str, object],
    git_before: Mapping[str, object],
) -> dict[str, object]:
    turn_root = paths.root / "turns" / f"{sequence_index:03d}-{_safe_id(turn_id, 'turn_id')}"
    prompt_bytes = prompt.encode("utf-8")
    _atomic_write(turn_root / "prompt.utf8.txt", prompt_bytes)
    _write_json(turn_root / "carrier_manifest.json", dict(carrier))
    _atomic_write(turn_root / "stdout.raw.jsonl", result.raw_jsonl)
    _atomic_write(turn_root / "stderr.raw.bin", result.stderr)
    _write_json(turn_root / "receipt.json", result.receipt_dict())
    if result.final_agent_text is not None:
        _write_text(turn_root / "assistant.utf8.txt", result.final_agent_text)

    workspace_after = _tree_manifest(paths.cwd, exclude_git=True)
    git_after = _git_observation(paths.cwd)
    home_after = _tree_manifest(paths.home)
    instruction_after = _instruction_chain(paths)
    observation = {
        "prompt_sha256": _sha256_bytes(prompt_bytes),
        "status": result.receipt["status"],
        "observed_thread_id": (
            result.parsed.thread_id if result.parsed is not None else None
        ),
        "workspace_before": workspace_before,
        "workspace_after": workspace_after,
        "workspace_unchanged": (
            workspace_before["tree_sha256"] == workspace_after["tree_sha256"]
        ),
        "git_before": git_before,
        "git_after": git_after,
        "home_after": home_after,
        "instruction_chain_after": instruction_after,
        "mechanical_events": _mechanical_event_observation(result),
    }
    _write_json(turn_root / "mechanical_observation.json", observation)
    return {
        "sequence_index": sequence_index,
        "turn_id": turn_id,
        "prompt_path": str((turn_root / "prompt.utf8.txt").relative_to(paths.root)),
        "prompt_sha256": observation["prompt_sha256"],
        "assistant_path": (
            str((turn_root / "assistant.utf8.txt").relative_to(paths.root))
            if result.final_agent_text is not None
            else None
        ),
        "assistant_sha256": (
            _sha256_bytes(result.final_agent_text.encode("utf-8"))
            if result.final_agent_text is not None
            else None
        ),
        "receipt_path": str((turn_root / "receipt.json").relative_to(paths.root)),
        "status": result.receipt["status"],
        "observed_thread_id": observation["observed_thread_id"],
        "workspace_unchanged": observation["workspace_unchanged"],
        "mechanical_events": observation["mechanical_events"],
    }


FirstInvoker = Callable[..., CodexExecResult]
ResumeInvoker = Callable[..., CodexExecResult]


def _invoke_track(
    config: ProbeRunConfig,
    *,
    track_id: str,
    turns: Sequence[Mapping[str, object]],
    prompt_builder: Callable[[int, Mapping[str, object], Sequence[Mapping[str, object]]], tuple[str, Mapping[str, object]]],
    sandbox_mode: str,
    fixture: Path | None,
    sequence_start: int,
    first_invoker: FirstInvoker,
    resume_invoker: ResumeInvoker,
) -> tuple[dict[str, object], int]:
    paths = _prepare_track(config, track_id, fixture=fixture)
    driver_config = _driver_config(config, paths, sandbox_mode=sandbox_mode)
    virgin = {
        "home": _tree_manifest(paths.home),
        "workspace": _tree_manifest(paths.cwd, exclude_git=True),
        "git": _git_observation(paths.cwd),
        "instruction_chain": _instruction_chain(paths),
    }
    transcript: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    thread_id: str | None = None
    sequence_index = sequence_start
    for index, turn in enumerate(turns):
        prompt, carrier = prompt_builder(index, turn, transcript)
        workspace_before = _tree_manifest(paths.cwd, exclude_git=True)
        git_before = _git_observation(paths.cwd)
        if thread_id is None:
            result = first_invoker(config=driver_config, prompt=prompt)
        else:
            result = resume_invoker(config=driver_config, thread_id=thread_id, prompt=prompt)
        row = _persist_turn(
            paths,
            sequence_index=sequence_index,
            turn_id=str(turn["id"]),
            prompt=prompt,
            carrier=carrier,
            result=result,
            workspace_before=workspace_before,
            git_before=git_before,
        )
        rows.append(row)
        if not result.ok or result.parsed is None or result.final_agent_text is None:
            raise ProbeRunError(f"track {track_id} failed at {turn['id']}: {row['status']}")
        observed_thread = result.parsed.thread_id
        if thread_id is None:
            thread_id = observed_thread
        elif observed_thread != thread_id:
            raise ProbeRunError(f"track {track_id} changed thread identity")
        transcript.extend(
            [
                {"role": "user", "text": str(turn["user"])},
                {"role": "assistant", "text": result.final_agent_text},
            ]
        )
        sequence_index += 1
    return (
        {
            "track_id": track_id,
            "thread_id": thread_id,
            "sandbox_mode": sandbox_mode,
            "virgin": virgin,
            "turns": rows,
            "transcript": transcript,
        },
        sequence_index,
    )


def _carrier(
    *,
    session_history: bool,
    situation_snapshot: bool,
    role_dialogue: bool,
    oracle_transition: bool,
    snapshot: Mapping[str, object] | None,
    dialogue: str | None = None,
) -> dict[str, object]:
    return {
        "session_history": session_history,
        "situation_snapshot": situation_snapshot,
        "role_dialogue": role_dialogue,
        "runtime_observation": False,
        "oracle_transition": oracle_transition,
        "snapshot_origin": "oracle_supplied" if snapshot is not None else "absent",
        "autonomous_revision_observed": False,
        "snapshot_projection_sha256": (
            snapshot.get("projection_sha256") if snapshot is not None else None
        ),
        "dialogue_sha256": (
            _sha256_bytes(dialogue.encode("utf-8")) if dialogue is not None else None
        ),
        "claim_boundary": "carrier_manifest_not_continuity_proof",
    }


def _source_manifest(config: ProbeRunConfig) -> dict[str, object]:
    paths = (
        "evals/situation_snapshot_lab/current_situation.py",
        "evals/situation_snapshot_lab/probe_packets.py",
        "evals/situation_snapshot_lab/probe_runner.py",
        "evals/situation_snapshot_lab/codex_exec_driver.py",
        "evals/situation_snapshot_lab/semantic_accidents.v1.json",
        "evals/situation_snapshot_lab/tiny_l0.md",
    )
    return {
        relative: {
            "sha256": _hash_file(config.source_root / relative),
            "bytes": (config.source_root / relative).stat().st_size,
        }
        for relative in paths
    }


def _artifact_hashes(run_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(run_root.rglob("*"), key=lambda item: item.as_posix()):
        if path.name == "artifact_hashes.json":
            continue
        if path.is_symlink():
            target = os.readlink(path)
            rows.append(
                {
                    "relative_path": path.relative_to(run_root).as_posix(),
                    "kind": "symlink_external_content_not_hashed",
                    "link_target_sha256": _sha256_bytes(os.fspath(target).encode("utf-8")),
                }
            )
            continue
        if not path.is_file():
            continue
        rows.append(
            {
                "relative_path": path.relative_to(run_root).as_posix(),
                "kind": "file",
                "bytes": path.stat().st_size,
                "sha256": _hash_file(path),
            }
        )
    return rows


def _action_track(
    config: ProbeRunConfig,
    *,
    sequence_start: int,
    first_invoker: FirstInvoker,
    resume_invoker: ResumeInvoker,
) -> tuple[dict[str, object], int]:
    action_case = _load_case(config.source_root, "quoted_action_then_explicit_action")
    action_snapshots = action_boundary_snapshots()

    def action_prompt(
        index: int,
        turn: Mapping[str, object],
        _transcript: Sequence[Mapping[str, object]],
    ) -> tuple[str, Mapping[str, object]]:
        turn_id = str(turn["id"])
        snapshot = action_snapshots[turn_id]
        return (
            render_probe_prompt(str(turn["user"]), situation=snapshot),
            _carrier(
                session_history=index > 0,
                situation_snapshot=True,
                role_dialogue=False,
                oracle_transition=index > 0,
                snapshot=snapshot,
            ),
        )

    fixture = (
        config.source_root
        / "evals"
        / "situation_snapshot_lab"
        / str(action_case["fixture"])
    )
    return _invoke_track(
        config,
        track_id="action-boundary-b4",
        turns=action_case["turns"],
        prompt_builder=action_prompt,
        sandbox_mode="workspace-write",
        fixture=fixture,
        sequence_start=sequence_start,
        first_invoker=first_invoker,
        resume_invoker=resume_invoker,
    )


def _seal_successful_run(
    config: ProbeRunConfig,
    manifest: dict[str, Any],
    *,
    starting_binary: Mapping[str, object],
    starting_sources: Mapping[str, object],
    version_verifier: Callable[[ProbeRunConfig], Mapping[str, object]],
) -> None:
    ending_binary = dict(version_verifier(config))
    ending_sources = _source_manifest(config)
    manifest["identity_readback"] = {
        "codex_binary": ending_binary,
        "source_manifest": ending_sources,
        "codex_binary_unchanged": ending_binary == starting_binary,
        "source_manifest_unchanged": ending_sources == starting_sources,
    }
    if ending_binary != starting_binary or ending_sources != starting_sources:
        raise ProbeRunError("lab source or Codex binary drifted during the serial pilot")
    manifest["status"] = "transport_completed_pending_human_adjudication"
    manifest["completed_at"] = _utc_now()
    manifest["human_adjudication_required"] = True
    manifest["production_adoption_allowed"] = False
    _write_json(config.run_root / "run_manifest.json", manifest)
    (config.run_root / "run_manifest.partial.json").unlink(missing_ok=True)
    hashes = _artifact_hashes(config.run_root)
    _write_json(
        config.run_root / "artifact_hashes.json",
        {
            "schema_version": "codex.situation_snapshot_lab.artifact_hashes.v1",
            "entries": hashes,
            "entries_sha256": _sha256_bytes(_canonical_json_bytes(hashes)),
        },
    )


def _initial_manifest(
    config: ProbeRunConfig,
    *,
    run_kind: str,
    path_boundary: Mapping[str, object],
    starting_binary: Mapping[str, object],
    starting_sources: Mapping[str, object],
) -> dict[str, Any]:
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": config.run_id,
        "run_kind": run_kind,
        "started_at": _utc_now(),
        "status": "running",
        "claim_boundary": "falsification_pilot_not_subject_continuity_proof",
        "oracle_update_proves_autonomous_revision": False,
        "production_registered": False,
        "external_capability": {
            "auth_target": str(config.auth_target.resolve()),
            "model": "shared_live_credential_link_pre_post_detection_only",
        },
        "path_boundary": dict(path_boundary),
        "codex_binary": dict(starting_binary),
        "source_manifest": dict(starting_sources),
        "environment_boundary": {
            "serial_live_invocations": True,
            "direct_native_without_npm_wrapper_env": True,
            "parent_env_keys_removed_by_driver": [
                "CODEX_API_KEY",
                "CODEX_MANAGED_BY_NPM",
                "CODEX_MANAGED_PACKAGE_ROOT",
                "CODEX_THREAD_ID",
                "OPENAI_API_KEY",
            ],
            "filesystem_paths_contained_except_shared_live_credential": True,
            "isolation_established": False,
        },
        "tracks": [],
    }


def run_first_pilot(
    config: ProbeRunConfig,
    *,
    first_invoker: FirstInvoker = invoke_first,
    resume_invoker: ResumeInvoker = invoke_resume,
    version_verifier: Callable[[ProbeRunConfig], Mapping[str, object]] = verify_codex_binary,
) -> dict[str, object]:
    """Run 17 serial turns and return their cold manifest.

    Any transport/auth/thread failure stops later arms.  Semantic success is
    deliberately left for separate human adjudication.
    """

    if config.run_root.exists():
        raise ProbeRunError("run_root must not already exist")
    if not config.source_root.is_dir():
        raise ProbeRunError("source_root must exist")
    if not config.auth_target.is_file():
        raise ProbeRunError("auth_target must be a regular file")
    path_boundary = _verify_path_boundary(config)
    config.run_root.mkdir(parents=False)
    starting_binary = dict(version_verifier(config))
    starting_sources = _source_manifest(config)
    manifest = _initial_manifest(
        config,
        run_kind="first-17-turn-pilot",
        path_boundary=path_boundary,
        starting_binary=starting_binary,
        starting_sources=starting_sources,
    )
    _write_json(config.run_root / "run_manifest.partial.json", manifest)
    sequence = 0
    seen_threads: set[str] = set()
    try:
        continuity_case = _load_case(
            config.source_root, "correction_changes_world_without_project_birth"
        )
        continuity_turns = continuity_case["turns"][:5]
        continuity_snapshots = continuity_probe_snapshots()

        def b3_prompt(
            _index: int,
            turn: Mapping[str, object],
            _transcript: Sequence[Mapping[str, object]],
        ) -> tuple[str, Mapping[str, object]]:
            return (
                render_probe_prompt(str(turn["user"])),
                _carrier(
                    session_history=_index > 0,
                    situation_snapshot=False,
                    role_dialogue=False,
                    oracle_transition=False,
                    snapshot=None,
                ),
            )

        b3, sequence = _invoke_track(
            config,
            track_id="continuous-b3",
            turns=continuity_turns,
            prompt_builder=b3_prompt,
            sandbox_mode="read-only",
            fixture=None,
            sequence_start=sequence,
            first_invoker=first_invoker,
            resume_invoker=resume_invoker,
        )
        manifest["tracks"].append(b3)
        seen_threads.add(str(b3["thread_id"]))

        def b4_prompt(
            index: int,
            turn: Mapping[str, object],
            _transcript: Sequence[Mapping[str, object]],
        ) -> tuple[str, Mapping[str, object]]:
            snapshot = continuity_snapshots["initial" if index == 0 else "corrected"]
            return (
                render_probe_prompt(str(turn["user"]), situation=snapshot),
                _carrier(
                    session_history=index > 0,
                    situation_snapshot=True,
                    role_dialogue=False,
                    oracle_transition=index == 1,
                    snapshot=snapshot,
                ),
            )

        b4, sequence = _invoke_track(
            config,
            track_id="continuous-b4",
            turns=continuity_turns,
            prompt_builder=b4_prompt,
            sandbox_mode="read-only",
            fixture=None,
            sequence_start=sequence,
            first_invoker=first_invoker,
            resume_invoker=resume_invoker,
        )
        if str(b4["thread_id"]) in seen_threads:
            raise ProbeRunError("continuous B4 reused B3 thread identity")
        manifest["tracks"].append(b4)
        seen_threads.add(str(b4["thread_id"]))

        dialogue_turns = [
            (str(row["role"]), str(row["text"]))
            for row in b4["transcript"][:4]
        ]
        dialogue = role_labeled_dialogue_prefix(dialogue_turns)
        t2 = [continuity_turns[2]]
        fresh_specs = (
            ("fresh-none", False, False),
            ("fresh-snapshot", True, False),
            ("fresh-dialogue", False, True),
            ("fresh-both", True, True),
        )
        for track_id, with_snapshot, with_dialogue in fresh_specs:
            snapshot = continuity_snapshots["corrected"] if with_snapshot else None

            def fresh_prompt(
                _index: int,
                turn: Mapping[str, object],
                _transcript: Sequence[Mapping[str, object]],
                *,
                selected_snapshot: Mapping[str, object] | None = snapshot,
                include_dialogue: bool = with_dialogue,
            ) -> tuple[str, Mapping[str, object]]:
                prompt = render_probe_prompt(str(turn["user"]), situation=selected_snapshot)
                if include_dialogue:
                    prompt = f"{dialogue}\n{prompt}"
                return (
                    prompt,
                    _carrier(
                        session_history=False,
                        situation_snapshot=selected_snapshot is not None,
                        role_dialogue=include_dialogue,
                        oracle_transition=False,
                        snapshot=selected_snapshot,
                        dialogue=dialogue if include_dialogue else None,
                    ),
                )

            fresh, sequence = _invoke_track(
                config,
                track_id=track_id,
                turns=t2,
                prompt_builder=fresh_prompt,
                sandbox_mode="read-only",
                fixture=None,
                sequence_start=sequence,
                first_invoker=first_invoker,
                resume_invoker=resume_invoker,
            )
            if str(fresh["thread_id"]) in seen_threads:
                raise ProbeRunError(f"fresh track reused an existing thread: {track_id}")
            seen_threads.add(str(fresh["thread_id"]))
            manifest["tracks"].append(fresh)

        action, sequence = _action_track(
            config,
            sequence_start=sequence,
            first_invoker=first_invoker,
            resume_invoker=resume_invoker,
        )
        if str(action["thread_id"]) in seen_threads:
            raise ProbeRunError("action track reused an existing thread")
        manifest["tracks"].append(action)
        manifest["turn_count"] = sequence
        if sequence != 17:
            raise ProbeRunError(f"unexpected pilot turn count: {sequence}")
        _seal_successful_run(
            config,
            manifest,
            starting_binary=starting_binary,
            starting_sources=starting_sources,
            version_verifier=version_verifier,
        )
        return manifest
    except Exception as exc:
        manifest["status"] = "stopped_on_failure"
        manifest["stopped_at"] = _utc_now()
        manifest["failure_type"] = type(exc).__name__
        _write_json(config.run_root / "run_manifest.partial.json", manifest)
        raise


def run_action_only_pilot(
    config: ProbeRunConfig,
    *,
    first_invoker: FirstInvoker = invoke_first,
    resume_invoker: ResumeInvoker = invoke_resume,
    version_verifier: Callable[[ProbeRunConfig], Mapping[str, object]] = verify_codex_binary,
) -> dict[str, object]:
    """Run only the three-turn quoted-action/explicit-action twin."""

    if config.run_root.exists():
        raise ProbeRunError("run_root must not already exist")
    if not config.source_root.is_dir():
        raise ProbeRunError("source_root must exist")
    if not config.auth_target.is_file():
        raise ProbeRunError("auth_target must be a regular file")
    path_boundary = _verify_path_boundary(config)
    config.run_root.mkdir(parents=False)
    starting_binary = dict(version_verifier(config))
    starting_sources = _source_manifest(config)
    manifest = _initial_manifest(
        config,
        run_kind="action-only-three-turn-pilot",
        path_boundary=path_boundary,
        starting_binary=starting_binary,
        starting_sources=starting_sources,
    )
    _write_json(config.run_root / "run_manifest.partial.json", manifest)
    try:
        action, sequence = _action_track(
            config,
            sequence_start=0,
            first_invoker=first_invoker,
            resume_invoker=resume_invoker,
        )
        manifest["tracks"].append(action)
        manifest["turn_count"] = sequence
        if sequence != 3:
            raise ProbeRunError(f"unexpected action pilot turn count: {sequence}")
        _seal_successful_run(
            config,
            manifest,
            starting_binary=starting_binary,
            starting_sources=starting_sources,
            version_verifier=version_verifier,
        )
        return manifest
    except Exception as exc:
        manifest["status"] = "stopped_on_failure"
        manifest["stopped_at"] = _utc_now()
        manifest["failure_type"] = type(exc).__name__
        _write_json(config.run_root / "run_manifest.partial.json", manifest)
        raise


__all__ = [
    "EXPECTED_CODEX_VERSION",
    "ProbeRunConfig",
    "ProbeRunError",
    "run_action_only_pilot",
    "run_first_pilot",
    "verify_codex_binary",
]
