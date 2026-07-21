from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import services.agent_runtime.system_awareness_consumer as awareness_module
from services.agent_runtime.execution_contract import artifact_json_bytes
from services.agent_runtime.system_awareness_consumer import (
    PROBLEM_TRANSITION_VERSION,
    SystemAwarenessError,
    build_problem_transition,
    reconcile_typed_problem_lifecycle,
    scan_task_run,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_RUN_CLI = Path(r"C:\Users\xx363\.codex\skills\verified-agent-loop\scripts\task_run.py")


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(artifact_json_bytes(value))


def _proof(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_text('{"passed":true}\n', encoding="utf-8")
    return f"{path}#sha256={hashlib.sha256(path.read_bytes()).hexdigest()}"


def _row(value: dict[str, object], ordinal: int) -> dict[str, object]:
    return {
        **value,
        "source_event_id": value["task_run_event_id"],
        "source_event_ordinal": ordinal,
        "transition_evidence_ref": f"transition-{ordinal}",
    }


def _transition(
    *,
    ordinal: int,
    transition_type: str,
    problem_ref: str = "",
    problem_generation: int = 1,
    repair_generation: int = 0,
    governing_cause: str = "selector-root-drift",
    evidence_refs: list[str] | None = None,
    repair_decision: str = "",
    repair_level: str = "",
    consumer_id: str = "",
    window_id: str = "",
    window_completed: bool = False,
    passed: bool = False,
) -> dict[str, object]:
    event_id = f"evt-{ordinal}"
    return _row(
        build_problem_transition(
            transition_type=transition_type,
            task_run_id="run-problem",
            task_run_event_id=event_id,
            side_effect_id=f"se:{ordinal}",
            family_signature="selector-drift",
            governing_cause=governing_cause,
            work_key="wk:selector",
            component_id="selector-consumer",
            problem_generation=problem_generation,
            repair_generation=repair_generation,
            problem_ref=problem_ref,
            repair_decision=repair_decision,
            repair_level=repair_level,
            consumer_id=consumer_id,
            window_id=window_id,
            window_completed=window_completed,
            passed=passed,
            evidence_refs=evidence_refs or [],
        ),
        ordinal,
    )


def _scan_run(
    root: Path,
    run_id: str,
    events: list[dict[str, object]],
    *,
    status: str = "in_progress",
) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    _json(
        run_dir / "task.json",
        {"schema_version": "codex.verified-task-run.v1", "run_id": run_id},
    )
    _json(
        run_dir / "state.json",
        {
            "schema_version": "codex.verified-task-run.v1",
            "run_id": run_id,
            "status": status,
            "current_phase": events[-1]["phase"],
            "events_count": len(events),
        },
    )
    (run_dir / "events.jsonl").write_text(
        "".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )
    return run_dir


def test_typed_problem_identity_survives_cause_revision_effect_and_recurrence(
    tmp_path: Path,
) -> None:
    proof = _proof(tmp_path, "effect.json")
    first = _transition(ordinal=1, transition_type="problem_observed")
    problem_ref = str(first["problem_ref"])
    revised = _transition(
        ordinal=2,
        transition_type="problem_observed",
        problem_ref=problem_ref,
        governing_cause="selector-root-and-contract-drift",
    )
    repair = _transition(
        ordinal=3,
        transition_type="repair_adopted",
        problem_ref=problem_ref,
        repair_generation=1,
        governing_cause="selector-root-and-contract-drift",
        repair_decision="small_repair",
        repair_level="local_patch",
        evidence_refs=[proof],
    )
    consumer = _transition(
        ordinal=4,
        transition_type="consumer_effect_verified",
        problem_ref=problem_ref,
        repair_generation=1,
        governing_cause="selector-root-and-contract-drift",
        consumer_id="real-selector-entry",
        passed=True,
        evidence_refs=[proof],
    )
    window = _transition(
        ordinal=5,
        transition_type="effect_window_completed",
        problem_ref=problem_ref,
        repair_generation=1,
        governing_cause="selector-root-and-contract-drift",
        window_id="fresh-window-1",
        window_completed=True,
        passed=True,
        evidence_refs=[proof],
    )
    close = _transition(
        ordinal=6,
        transition_type="problem_close_requested",
        problem_ref=problem_ref,
        repair_generation=1,
        governing_cause="selector-root-and-contract-drift",
    )

    effective = reconcile_typed_problem_lifecycle([first, revised, repair, consumer, window, close])
    assert effective["problem_count"] == 1
    row = effective["problems"][0]
    assert row["problem_ref"] == problem_ref
    assert row["governing_cause_history"] == [
        "selector-root-drift",
        "selector-root-and-contract-drift",
    ]
    assert row["status"] == "effective"
    assert row["problem_effectiveness_boundary_verified"] is True

    recurrence = _transition(
        ordinal=7,
        transition_type="problem_observed",
        problem_ref=problem_ref,
        problem_generation=2,
        governing_cause="selector-root-and-contract-drift",
    )
    recurred = reconcile_typed_problem_lifecycle(
        [first, revised, repair, consumer, window, close, recurrence]
    )["problems"][0]
    assert recurred["problem_ref"] == problem_ref
    assert recurred["problem_generation"] == 2
    assert recurred["recurrence_state"] == "recurred"
    assert recurred["repair_level"] == "structural_chain_repair"
    assert "RECURRENCE_AFTER_EFFECTIVE_GENERATION" in recurred["classification_basis"]


def test_wrong_repair_generation_cannot_supply_effect_or_close(tmp_path: Path) -> None:
    proof = _proof(tmp_path, "proof.json")
    observed = _transition(ordinal=1, transition_type="problem_observed")
    problem_ref = str(observed["problem_ref"])
    repair = _transition(
        ordinal=2,
        transition_type="repair_adopted",
        problem_ref=problem_ref,
        repair_generation=1,
        repair_decision="small_repair",
        repair_level="local_patch",
        evidence_refs=[proof],
    )
    wrong_consumer = _transition(
        ordinal=3,
        transition_type="consumer_effect_verified",
        problem_ref=problem_ref,
        repair_generation=2,
        consumer_id="wrong-generation-consumer",
        passed=True,
        evidence_refs=[proof],
    )
    with pytest.raises(SystemAwarenessError) as caught:
        reconcile_typed_problem_lifecycle([observed, repair, wrong_consumer])
    assert caught.value.reason_code == "PROBLEM_TRANSITION_ORPHANED"


def test_task_run_scanner_requires_hash_and_exact_event_binding(tmp_path: Path) -> None:
    run_id = "typed-transition-run"
    event_id = "evt-problem-1"
    transition = build_problem_transition(
        transition_type="problem_observed",
        task_run_id=run_id,
        task_run_event_id=event_id,
        side_effect_id="se:problem-1",
        family_signature="runtime-contract-gap",
        governing_cause="producer-consumer-schema-drift",
        work_key="wk:runtime-contract",
        component_id="contract-consumer",
        problem_generation=1,
        systemic_signals={"cross_entrypoint": True},
    )
    carrier = tmp_path / "transition.json"
    _json(carrier, transition)
    carrier_sha = hashlib.sha256(carrier.read_bytes()).hexdigest()
    event = {
        "schema_version": "codex.verified-task-run.v1",
        "event_id": event_id,
        "run_id": run_id,
        "actor": "codex-owner",
        "kind": "failure",
        "phase": "problem_transition_recorded",
        "summary": "typed problem",
        "evidence_refs": [f"{carrier}#sha256={carrier_sha}"],
        "target": "wk:runtime-contract",
        "exit_code": 1,
        "retry_class": "deterministic",
        "side_effect_id": "se:problem-1",
    }
    run_dir = _scan_run(tmp_path / "runs", run_id, [event])

    projection = scan_task_run(run_dir)["problem_projection"]
    assert projection["truth_sources"] == "typed_hash_bound_task_run_problem_transitions"
    assert projection["problem_count"] == 1
    assert projection["problems"][0]["problem_class"] == "systemic_capability_gap"

    carrier.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(SystemAwarenessError) as caught:
        scan_task_run(run_dir)
    assert caught.value.reason_code == "PROBLEM_TRANSITION_EVIDENCE_INVALID"


def test_legacy_free_text_does_not_manufacture_systemic_identity_and_terminal_is_visible(
    tmp_path: Path,
) -> None:
    legacy_run = "legacy-free-text"
    failure = {
        "schema_version": "codex.verified-task-run.v1",
        "event_id": "evt-legacy",
        "run_id": legacy_run,
        "actor": "different-looking-actor",
        "kind": "failure",
        "phase": "worker_failed",
        "summary": "failed",
        "evidence_refs": [],
        "target": r"D:\free\text\carrier",
        "exit_code": 1,
        "retry_class": "deterministic",
        "side_effect_id": None,
    }
    legacy_dir = _scan_run(tmp_path / "runs-a", legacy_run, [failure])
    legacy_problem = scan_task_run(legacy_dir)["problem_projection"]["problems"][0]
    assert legacy_problem["problem_class"] == "local_defect"
    assert legacy_problem["work_keys"] == []
    assert legacy_problem["components"] == []

    terminal_run = "terminal-partial"
    finished = {
        "schema_version": "codex.verified-task-run.v1",
        "event_id": "evt-finished",
        "run_id": terminal_run,
        "actor": "coordinator",
        "kind": "result",
        "phase": "finished",
        "summary": "partial result",
        "evidence_refs": [],
        "target": None,
        "exit_code": None,
        "retry_class": "none",
        "side_effect_id": None,
        "terminal_status": "partial",
    }
    terminal_dir = _scan_run(tmp_path / "runs-b", terminal_run, [finished], status="partial")
    terminal_problem = scan_task_run(terminal_dir)["problem_projection"]["problems"][0]
    assert terminal_problem["family_signature"] == "task-run-terminal-partial"
    assert terminal_problem["source_event_refs"] == ["evt-finished"]


def test_external_problem_state_is_rejected_and_malformed_frontier_is_reported(
    tmp_path: Path,
) -> None:
    run_id = "strict-problem-input"
    initialized = {
        "schema_version": "codex.verified-task-run.v1",
        "event_id": "evt-init",
        "run_id": run_id,
        "actor": "coordinator",
        "kind": "checkpoint",
        "phase": "initialized",
        "summary": "initialized",
        "evidence_refs": [],
        "target": None,
        "exit_code": None,
        "retry_class": "none",
        "side_effect_id": None,
    }
    run_dir = _scan_run(tmp_path / "runs", run_id, [initialized])
    with pytest.raises(SystemAwarenessError) as caught:
        scan_task_run(run_dir, effectiveness_evidence=[])
    assert caught.value.reason_code == "EXTERNAL_PROBLEM_FACTS_NOT_AUTHORIZED"

    frontier = awareness_module._frontier_reconciliation_from_events(  # noqa: SLF001
        [{"kind": "global_frontier_reconciliation"}]
    )
    assert frontier is not None
    assert frontier["status"] == "invalid"
    assert frontier["reason_codes"] == ["INPUT_INVALID", "GLOBAL_FRONTIER_RECEIPT_INVALID"]


def test_untyped_effect_and_global_close_cannot_advance_problem_lifecycle(
    tmp_path: Path,
) -> None:
    run_id = "untyped-close-refused"
    effect = tmp_path / "untyped-effect.json"
    _json(
        effect,
        {
            "kind": "real_consumer",
            "passed": True,
            "window_completed": True,
        },
    )
    effect_ref = f"{effect}#sha256={hashlib.sha256(effect.read_bytes()).hexdigest()}"
    events = [
        {
            "schema_version": "codex.verified-task-run.v1",
            "event_id": "evt-failure",
            "run_id": run_id,
            "actor": "legacy-producer",
            "kind": "failure",
            "phase": "consumer_failed",
            "summary": "consumer failed",
            "evidence_refs": [],
            "target": "wk:legacy",
            "exit_code": 1,
            "retry_class": "deterministic",
            "side_effect_id": None,
        },
        {
            "schema_version": "codex.verified-task-run.v1",
            "event_id": "evt-effect",
            "run_id": run_id,
            "actor": "legacy-producer",
            "kind": "result",
            "phase": "problem_effectiveness_observed",
            "summary": "untyped effect",
            "evidence_refs": [effect_ref],
            "target": "wk:legacy",
            "exit_code": 0,
            "retry_class": "none",
            "side_effect_id": "se:legacy-effect",
        },
        {
            "schema_version": "codex.verified-task-run.v1",
            "event_id": "evt-close",
            "run_id": run_id,
            "actor": "legacy-producer",
            "kind": "result",
            "phase": "problem_close_requested",
            "summary": "unscoped close",
            "evidence_refs": [],
            "target": "wk:legacy",
            "exit_code": 0,
            "retry_class": "none",
            "side_effect_id": "se:legacy-close",
        },
    ]
    run_dir = _scan_run(tmp_path / "runs", run_id, events)
    problem = scan_task_run(run_dir)["problem_projection"]["problems"][0]
    assert problem["status"] == "open"
    assert problem["problem_effectiveness_boundary_verified"] is False
    assert "TYPED_PROBLEM_TRANSITION_REQUIRED_FOR_LIFECYCLE_ADVANCE" in problem["reason_codes"]


@pytest.mark.skipif(not TASK_RUN_CLI.is_file(), reason="canonical task-run CLI unavailable")
def test_fresh_process_finish_adapter_records_partial_problem_before_close(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "task-runs"
    run_id = "problem-adapter-canary"
    initialized = subprocess.run(
        [
            sys.executable,
            str(TASK_RUN_CLI),
            "--root",
            str(run_root),
            "init",
            "--run-id",
            run_id,
            "--mode",
            "bounded_task",
            "--objective",
            "verify typed terminal problem adapter",
            "--risk",
            "reversible_local",
            "--completion",
            "consumer effect is verified",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert initialized.returncode == 0, initialized.stderr

    adapter = REPO_ROOT / "scripts" / "record_problem_transition.py"
    command = [
        sys.executable,
        str(adapter),
        "finish",
        "--task-run-cli",
        str(TASK_RUN_CLI),
        "--task-run-root",
        str(run_root),
        "--task-run-id",
        run_id,
        "--status",
        "partial",
        "--summary",
        "consumer effect remains unverified",
    ]
    finished = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode == 0, finished.stderr
    finish_result = json.loads(finished.stdout)
    assert finish_result["problem_transitions"][0]["transition_type"] == "problem_observed"

    output = tmp_path / "fresh-scan.json"
    scanned = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_system_awareness_consumer.py"),
            "scan-task-run",
            "--task-run-dir",
            str(run_root / run_id),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert scanned.returncode == 0, scanned.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["source"]["status"] == "partial"
    assert report["problem_projection"]["truth_sources"] == (
        "typed_hash_bound_task_run_problem_transitions"
    )
    assert report["problem_projection"]["problem_count"] == 1
    assert report["problem_projection"]["problems"][0]["status"] == "open"

    replay = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["replayed"] is True


@pytest.mark.skipif(not TASK_RUN_CLI.is_file(), reason="canonical task-run CLI unavailable")
def test_fresh_process_record_adapter_closes_exact_repair_generation(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "task-runs"
    run_id = "problem-lifecycle-canary"
    initialized = subprocess.run(
        [
            sys.executable,
            str(TASK_RUN_CLI),
            "--root",
            str(run_root),
            "init",
            "--run-id",
            run_id,
            "--mode",
            "bounded_task",
            "--objective",
            "verify full typed problem lifecycle",
            "--risk",
            "reversible_local",
            "--completion",
            "problem repair effect is verified",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert initialized.returncode == 0, initialized.stderr
    proof_ref = _proof(tmp_path, "live-effect.json")
    adapter = REPO_ROOT / "scripts" / "record_problem_transition.py"
    common = [
        sys.executable,
        str(adapter),
        "record",
        "--task-run-cli",
        str(TASK_RUN_CLI),
        "--task-run-root",
        str(run_root),
        "--task-run-id",
        run_id,
        "--family-signature",
        "runtime-contract-gap",
        "--governing-cause",
        "producer-consumer-contract-drift",
        "--work-key",
        "wk:runtime-contract",
        "--component-id",
        "runtime-contract-consumer",
    ]

    def record(*arguments: str) -> dict[str, object]:
        completed = subprocess.run(
            [*common, *arguments],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    observed = record(
        "--transition-type",
        "problem_observed",
        "--systemic-signal",
        "cross_entrypoint",
    )
    problem_ref = str(observed["problem_ref"])
    repair_args = (
        "--transition-type",
        "repair_adopted",
        "--problem-ref",
        problem_ref,
        "--repair-decision",
        "structural_repair",
        "--repair-level",
        "structural_chain_repair",
        "--evidence-ref",
        proof_ref,
    )
    repair = record(*repair_args)
    assert repair["repair_generation"] == 1
    assert record(*repair_args)["replayed"] is True
    record(
        "--transition-type",
        "consumer_effect_verified",
        "--problem-ref",
        problem_ref,
        "--consumer-id",
        "fresh-runtime-consumer",
        "--passed",
        "--evidence-ref",
        proof_ref,
    )
    record(
        "--transition-type",
        "effect_window_completed",
        "--problem-ref",
        problem_ref,
        "--window-id",
        "fresh-process-window",
        "--window-completed",
        "--passed",
        "--evidence-ref",
        proof_ref,
    )
    close_args = (
        "--transition-type",
        "problem_close_requested",
        "--problem-ref",
        problem_ref,
    )
    record(*close_args)
    assert record(*close_args)["replayed"] is True

    report = scan_task_run(run_root / run_id)
    problem = report["problem_projection"]["problems"][0]
    assert problem["problem_ref"] == problem_ref
    assert problem["repair_generation"] == 1
    assert problem["status"] == "effective"
    assert problem["next_consumer"] is None
