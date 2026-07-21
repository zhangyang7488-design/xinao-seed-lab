from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import services.agent_runtime.system_awareness_consumer as awareness_module
from services.agent_runtime.system_awareness_consumer import (
    evaluate_completion_card,
    evaluate_promotion_evidence,
    evaluate_recovery_truth,
    evaluate_temporary_object,
    evaluate_trajectory_sample,
    evaluate_wakeable_wait,
    preflight_supervisor_root,
    project_episode_outcome,
    publish_worktree_lifecycle_record,
    reconcile_global_frontier,
    reconcile_identity,
    reconcile_problem_lifecycle,
    reconcile_temporal_identity,
    scan_task_run,
    scan_worktree_lifecycle,
    validate_strict_json_result,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_scan_run(root: Path, run_id: str, events: list[dict[str, object]]) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "task.json",
        {"schema_version": "codex.verified-task-run.v1", "run_id": run_id},
    )
    _write_json(
        run_dir / "state.json",
        {
            "schema_version": "codex.verified-task-run.v1",
            "run_id": run_id,
            "status": "in_progress",
            "current_phase": events[-1]["phase"] if events else "initialized",
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


def test_completion_card_keeps_boundary_parent_and_internal_child_distinct() -> None:
    binder = evaluate_completion_card(
        {
            "work_key": "wk:g1:binder",
            "authority_scope": "parent_owner",
            "boundary_predicates": {"LAND": True, "V": True, "LEDGER_MOVE": True},
            "parent_predicates": {"PUBLIC_MATERIALS": False},
        }
    )
    assert binder["status"] == "boundary_verified_parent_open"
    assert binder["parent_state"] == "open"
    assert binder["parent_completion_claim_allowed"] is False

    non_owner = evaluate_completion_card(
        {
            "work_key": "wk:consumer",
            "authority_scope": "non_parent_owner",
            "boundary_predicates": {"INPUTS": True, "MANIFEST": True, "V": True},
        }
    )
    assert non_owner["status"] == "verified_within_boundary_non_parent_owner"
    assert non_owner["reason_codes"] == ["BOUNDARY_VERIFIED_NO_PARENT_AUTHORITY"]

    incomplete = evaluate_completion_card(
        {
            "work_key": "wk:land-only",
            "authority_scope": "parent_owner",
            "boundary_predicates": {"LAND": True, "V": True, "LEDGER_MOVE": False},
        }
    )
    assert incomplete["status"] == "partial"
    assert "LEDGER_MOVE_MISSING" in incomplete["reason_codes"]

    child = evaluate_completion_card(
        {
            "work_key": "wk:worker-child",
            "role": "internal_execution_child",
            "boundary_predicates": {"PARENT_POOL_CONTRACT": True},
        }
    )
    assert child["gap_discovery_eligible"] is False
    assert child["reason_codes"] == ["INTERNAL_CHILD_NOT_INDEPENDENT_CONSUMER"]


def test_token_projection_conserves_failed_cancelled_and_separate_recovery() -> None:
    report = project_episode_outcome(
        {
            "episode_id": "episode-1",
            "native_total_tokens": 600,
            "high_burn_threshold": 500,
            "attempts": [
                {
                    "attempt_id": "a",
                    "status": "accepted",
                    "usage": {"total_tokens": 100},
                    "outcome_links": [],
                },
                {
                    "attempt_id": "b",
                    "status": "rejected",
                    "usage": {"total_tokens": 300},
                    "outcome_links": [],
                },
                {
                    "attempt_id": "c",
                    "status": "cancelled",
                    "usage": {"total_tokens": 200},
                    "outcome_links": [],
                },
            ],
        }
    )
    assert report["tokens"]["conservation"] == "balanced"
    assert report["tokens"]["by_outcome"] == {
        "accepted": 100,
        "failed": 300,
        "cancelled": 200,
        "incomplete": 0,
    }
    assert "HIGH_BURN_NO_CONVERSION" in report["reason_codes"]

    recovered = project_episode_outcome(
        {
            "episode_id": "episode-2",
            "attempts": [
                {
                    "attempt_id": "rejected-worker",
                    "status": "rejected",
                    "usage": {"total_tokens": 50},
                    "outcome_links": [{"kind": "owner_recovered_artifact", "receipt": "owner-v"}],
                }
            ],
        }
    )
    assert recovered["attempts"][0]["declared_status"] == "rejected"
    assert recovered["attempts"][0]["cost_bucket"] == "failed"
    assert "REJECTED_ATTEMPT_COST_RETAINED" in recovered["reason_codes"]
    assert "ARTIFACT_OWNER_RECOVERED_SEPARATELY" in recovered["reason_codes"]


def test_task_run_scan_accounts_promptfoo_pass_and_failure_tokens(tmp_path: Path) -> None:
    run_id = "promptfoo-cost"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    promptfoo = tmp_path / "promptfoo.result.json"
    _write_json(
        promptfoo,
        {
            "results": {
                "results": [
                    {
                        "success": True,
                        "vars": {"case_id": "pass-case"},
                        "response": {"tokenUsage": {"total": 30}},
                    },
                    {
                        "success": False,
                        "vars": {"case_id": "failed-case"},
                        "response": {"tokenUsage": {"total": 70}},
                    },
                ]
            }
        },
    )
    task = {"schema_version": "codex.verified-task-run.v1", "run_id": run_id}
    event = {
        "schema_version": "codex.verified-task-run.v1",
        "event_id": "promptfoo-event",
        "run_id": run_id,
        "phase": "behavior_regression_partial",
        "kind": "result",
        "exit_code": 1,
        "retry_class": "deterministic",
        "summary": "one case passed and one failed",
        "evidence_refs": [str(promptfoo)],
        "target": "wk:eval",
        "actor": "promptfoo",
    }
    state = {
        "schema_version": "codex.verified-task-run.v1",
        "run_id": run_id,
        "status": "in_progress",
        "current_phase": event["phase"],
        "events_count": 1,
    }
    _write_json(run_dir / "task.json", task)
    _write_json(run_dir / "state.json", state)
    (run_dir / "events.jsonl").write_text(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    report = scan_task_run(run_dir)
    assert report["episode_outcome"]["tokens"]["by_outcome"] == {
        "accepted": 100,
        "failed": 0,
        "cancelled": 0,
        "incomplete": 0,
    }
    verdicts = {row["evaluation_verdict"] for row in report["episode_outcome"]["attempts"]}
    assert verdicts == {"passed", "failed"}


def test_task_run_scan_lazily_consumes_dispatch_outcome_v2_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.agent_runtime.dispatch_economics as dispatch_economics

    outcome = tmp_path / "worker-terminal-event.json"
    _write_json(outcome, {"schema_version": "xinao.dispatch_outcome_event.v2"})
    outcome_ref = f"{outcome}#sha256={hashlib.sha256(outcome.read_bytes()).hexdigest()}"
    run_id = "dispatch-v2-awareness"
    run_dir = _write_scan_run(
        tmp_path,
        run_id,
        [
            {
                "schema_version": "codex.verified-task-run.v1",
                "event_id": "worker-terminal-1",
                "run_id": run_id,
                "phase": "worker_terminal",
                "kind": "result",
                "exit_code": 0,
                "retry_class": "none",
                "summary": "typed worker terminal",
                "evidence_refs": [outcome_ref],
                "target": "wk-1",
                "actor": "grok-worker-pool",
                "side_effect_id": "se:worker-terminal:op-1:attempt-1",
            }
        ],
    )
    expected = {
        "schema_version": "xinao.dispatch_outcome_projection.v1",
        "event_count": 1,
        "summary": {
            "provider_terminal": 1,
            "provider_accepted": 1,
            "owner_adopted": 0,
            "authority_applied": 0,
            "effect_verified": 0,
        },
        "metrics": {
            "total_tokens": 90,
            "failed_tokens": 20,
            "cost_per_verified_work_key": None,
        },
        "work_keys": [
            {
                "work_key": "wk-1",
                "non_conversion_reason": "owner_verdict_missing",
                "effect_verified": False,
            }
        ],
        "outcome_chain_closed": False,
        "authority": False,
        "completion_claim_allowed": False,
    }
    calls: list[Path] = []

    def fake_project(path: Path) -> dict[str, object]:
        calls.append(Path(path))
        return expected

    monkeypatch.setattr(dispatch_economics, "project_dispatch_outcomes", fake_project)
    report = scan_task_run(run_dir)

    assert calls == [run_dir.resolve()]
    assert report["dispatch_outcome_projection"] == expected
    assert report["dispatch_outcome_projection"]["metrics"]["total_tokens"] == 90
    assert (
        report["dispatch_outcome_projection"]["work_keys"][0]["non_conversion_reason"]
        == "owner_verdict_missing"
    )
    assert report["dispatch_outcome_projection"]["summary"] == {
        "provider_terminal": 1,
        "provider_accepted": 1,
        "owner_adopted": 0,
        "authority_applied": 0,
        "effect_verified": 0,
    }
    assert report["dispatch_outcome_projection"]["completion_claim_allowed"] is False
    assert "DISPATCH_OUTCOME_V2_PROJECTED" in report["reason_codes"]


@pytest.mark.parametrize("phase", ["owner_adopted", "authority_applied"])
def test_task_run_scan_recognizes_explicit_authority_axis_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    import services.agent_runtime.dispatch_economics as dispatch_economics

    outcome = tmp_path / f"{phase}.json"
    _write_json(outcome, {"schema_version": "xinao.dispatch_outcome_event.v2"})
    outcome_ref = f"{outcome}#sha256={hashlib.sha256(outcome.read_bytes()).hexdigest()}"
    run_id = f"dispatch-axis-{phase}"
    run_dir = _write_scan_run(
        tmp_path,
        run_id,
        [
            {
                "schema_version": "codex.verified-task-run.v1",
                "event_id": f"event-{phase}",
                "run_id": run_id,
                "phase": phase,
                "kind": "result",
                "exit_code": 0,
                "retry_class": "none",
                "summary": phase,
                "evidence_refs": [outcome_ref],
                "target": "wk-1",
                "actor": "codex-owner",
                "side_effect_id": f"se:{phase}:wk-1",
            }
        ],
    )
    expected = {
        "schema_version": "xinao.dispatch_outcome_projection.v1",
        "event_count": 1,
        "authority": False,
        "completion_claim_allowed": False,
    }
    calls: list[Path] = []

    def fake_project(path: Path) -> dict[str, object]:
        calls.append(Path(path))
        return expected

    monkeypatch.setattr(dispatch_economics, "project_dispatch_outcomes", fake_project)
    report = scan_task_run(run_dir)

    assert calls == [run_dir.resolve()]
    assert report["dispatch_outcome_projection"] == expected
    assert "parent_complete" not in report["dispatch_outcome_projection"]


def test_task_run_without_dispatch_events_remains_projection_compatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.agent_runtime.dispatch_economics as dispatch_economics

    run_dir = _write_scan_run(tmp_path, "legacy-no-dispatch", [])

    def forbidden_project(_path: Path) -> dict[str, object]:
        raise AssertionError("dispatch projection must stay lazy for old runs")

    monkeypatch.setattr(dispatch_economics, "project_dispatch_outcomes", forbidden_project)
    report = scan_task_run(run_dir)

    assert "dispatch_outcome_projection" not in report
    assert report["reason_codes"] == ["SYSTEM_AWARENESS_SCAN_COMPLETED"]
    assert report["episode_outcome"]["tokens"]["known_total"] == 0


def test_malformed_dispatch_v2_event_fails_closed_at_awareness_seam(tmp_path: Path) -> None:
    outcome = tmp_path / "malformed-worker-terminal-event.json"
    _write_json(outcome, {"schema_version": "xinao.dispatch_outcome_event.v2"})
    outcome_ref = f"{outcome}#sha256={hashlib.sha256(outcome.read_bytes()).hexdigest()}"
    run_id = "dispatch-v2-malformed"
    run_dir = _write_scan_run(
        tmp_path,
        run_id,
        [
            {
                "schema_version": "codex.verified-task-run.v1",
                "event_id": "worker-terminal-invalid",
                "run_id": run_id,
                "phase": "worker_terminal",
                "kind": "result",
                "exit_code": 0,
                "retry_class": "none",
                "summary": "malformed typed worker terminal",
                "evidence_refs": [outcome_ref],
                "target": "wk-invalid",
                "actor": "grok-worker-pool",
                "side_effect_id": "se:worker-terminal:invalid",
            }
        ],
    )

    with pytest.raises(awareness_module.SystemAwarenessError) as raised:
        scan_task_run(run_dir)
    assert raised.value.reason_code == "DISPATCH_OUTCOME_PROJECTION_INVALID"


def test_work_unit_projection_preserves_non_prefixed_execution_work_keys(
    tmp_path: Path,
) -> None:
    run_id = "non-prefixed-work-keys"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    hex_key = "a" * 64
    events = [
        {
            "schema_version": "codex.verified-task-run.v1",
            "event_id": "plain-key-planned",
            "run_id": run_id,
            "phase": "work_unit_planned",
            "kind": "result",
            "exit_code": 0,
            "retry_class": "none",
            "summary": "plain execution-contract key planned",
            "evidence_refs": [],
            "target": "work-1",
            "actor": "codex_owner",
            "side_effect_id": "se:plain:planned",
        },
        {
            "schema_version": "codex.verified-task-run.v1",
            "event_id": "plain-key-active",
            "run_id": run_id,
            "phase": "work_unit_active",
            "kind": "result",
            "exit_code": 0,
            "retry_class": "none",
            "summary": "plain execution-contract key active",
            "evidence_refs": [],
            "target": "work-1",
            "actor": "codex_owner",
            "side_effect_id": "se:plain:active",
        },
        {
            "schema_version": "codex.verified-task-run.v1",
            "event_id": "hex-key-planned",
            "run_id": run_id,
            "phase": "work_unit_planned",
            "kind": "result",
            "exit_code": 0,
            "retry_class": "none",
            "summary": "foundation key planned",
            "evidence_refs": [],
            "target": hex_key,
            "actor": "codex_owner",
            "side_effect_id": "se:hex:planned",
        },
        {
            "schema_version": "codex.verified-task-run.v1",
            "event_id": "hex-key-active",
            "run_id": run_id,
            "phase": "work_unit_active",
            "kind": "result",
            "exit_code": 0,
            "retry_class": "none",
            "summary": "foundation key active",
            "evidence_refs": [],
            "target": hex_key,
            "actor": "codex_owner",
            "side_effect_id": "se:hex:active",
        },
        {
            "schema_version": "codex.verified-task-run.v1",
            "event_id": "hex-key-paused",
            "run_id": run_id,
            "phase": "work_unit_paused",
            "kind": "result",
            "exit_code": 0,
            "retry_class": "none",
            "summary": "foundation key paused",
            "evidence_refs": [],
            "target": hex_key,
            "actor": "codex_owner",
            "side_effect_id": "se:hex:paused",
        },
        {
            "schema_version": "codex.verified-task-run.v1",
            "event_id": "ordinary-target-is-not-work-unit",
            "run_id": run_id,
            "phase": "git_remote_readback",
            "kind": "result",
            "exit_code": 0,
            "retry_class": "none",
            "summary": "ordinary task-run target",
            "evidence_refs": [],
            "target": "origin/main",
            "actor": "codex_owner",
            "side_effect_id": "se:git-readback",
        },
    ]
    _write_json(
        run_dir / "task.json",
        {"schema_version": "codex.verified-task-run.v1", "run_id": run_id},
    )
    _write_json(
        run_dir / "state.json",
        {
            "schema_version": "codex.verified-task-run.v1",
            "run_id": run_id,
            "status": "in_progress",
            "current_phase": events[-1]["phase"],
            "events_count": len(events),
        },
    )
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )

    units = scan_task_run(run_dir)["work_unit_lifecycle"]["work_units"]
    by_key = {row["work_key"]: row for row in units}
    assert set(by_key) == {"work-1", hex_key}
    assert by_key["work-1"]["state"] == "active"
    assert by_key[hex_key]["state"] == "paused"
    assert by_key[hex_key]["resume_requires_live_fact_reconciliation"] is True


def test_problem_projection_merges_splits_requires_effectiveness_and_reopens() -> None:
    merged = reconcile_problem_lifecycle(
        {
            "events": [
                {
                    "event_id": "e1",
                    "family_signature": "selector-drift",
                    "governing_cause": "root-resolution",
                    "work_key": "a",
                },
                {
                    "event_id": "e2",
                    "family_signature": "selector-drift",
                    "governing_cause": "root-resolution",
                    "work_key": "b",
                },
            ],
            "close_requested": True,
            "effectiveness_evidence": [{"kind": "behavior_regression", "passed": True}],
        }
    )
    problem = merged["problems"][0]
    assert problem["problem_class"] == "systemic_capability_gap"
    assert problem["status"] == "monitoring"
    assert "PROBLEM_FAMILY_MERGED" in problem["reason_codes"]
    assert "EFFECTIVENESS_EVIDENCE_MISSING" in problem["reason_codes"]

    same_row_is_not_a_window = reconcile_problem_lifecycle(
        {
            "events": [
                {
                    "event_id": "e1",
                    "family_signature": "consumer-only",
                    "governing_cause": "effect-window-missing",
                }
            ],
            "close_requested": True,
            "effectiveness_evidence": [
                {"kind": "real_consumer", "passed": True, "window_completed": True}
            ],
        }
    )["problems"][0]
    assert same_row_is_not_a_window["status"] == "monitoring"
    assert "EFFECTIVENESS_EVIDENCE_MISSING" in same_row_is_not_a_window["reason_codes"]

    split = reconcile_problem_lifecycle(
        {
            "events": [
                {
                    "event_id": "e1",
                    "family_signature": "json-invalid",
                    "governing_cause": "narration-prefix",
                },
                {
                    "event_id": "e2",
                    "family_signature": "json-invalid",
                    "governing_cause": "schema-missing",
                },
            ]
        }
    )
    assert len(split["problems"]) == 2
    assert all("PROBLEM_FAMILY_SPLIT" in row["reason_codes"] for row in split["problems"])

    effective = reconcile_problem_lifecycle(
        {
            "events": [
                {
                    "event_id": "e1",
                    "family_signature": "resume-stale",
                    "governing_cause": "missing-consumer",
                }
            ],
            "close_requested": True,
            "effectiveness_evidence": [
                {"kind": "real_consumer", "passed": True},
                {"kind": "monitoring_window", "passed": True, "window_completed": True},
            ],
        }
    )["problems"][0]
    assert effective["status"] == "effective"
    retained_effective = reconcile_problem_lifecycle(
        {
            "previous": effective,
            "events": [
                {
                    "event_id": "e1",
                    "family_signature": "resume-stale",
                    "governing_cause": "missing-consumer",
                }
            ],
        }
    )["problems"][0]
    assert retained_effective["status"] == "effective"
    assert retained_effective["recurrence_state"] == "effective"
    assert retained_effective["effectiveness_evidence"] == effective["effectiveness_evidence"]
    assert "PROBLEM_STATE_RETAINED_NO_NEW_EVENT" in retained_effective["reason_codes"]
    recurred = reconcile_problem_lifecycle(
        {
            "previous": effective,
            "events": [
                {
                    "event_id": "e1",
                    "family_signature": "resume-stale",
                    "governing_cause": "missing-consumer",
                },
                {
                    "event_id": "e2",
                    "family_signature": "resume-stale",
                    "governing_cause": "missing-consumer",
                },
            ],
        }
    )["problems"][0]
    assert recurred["status"] == "open"
    assert recurred["recurrence_state"] == "recurred"
    assert recurred["repair_level"] == "structural_chain_repair"
    assert recurred["repair_decision"] == "structural_repair"

    retained = reconcile_problem_lifecycle({"previous": recurred, "events": []})["problems"][0]
    assert retained["problem_ref"] == recurred["problem_ref"]
    assert retained["status"] == "open"

    no_build = reconcile_problem_lifecycle(
        {
            "events": [
                {
                    "event_id": "irrelevant-1",
                    "family_signature": "adjacent-feature",
                    "governing_cause": "not-parent-relevant",
                    "relevant_to_parent": False,
                    "expected_net_benefit_positive": False,
                }
            ]
        }
    )["problems"][0]
    assert no_build["repair_decision"] == "no_build"
    assert no_build["status"] == "retired"
    assert "NO_BUILD_SELECTED" in no_build["reason_codes"]


def test_global_frontier_reconciliation_keeps_local_wait_scoped_and_requires_full_proof() -> None:
    local = reconcile_global_frontier(
        {
            "parent_mainline_id": "mainline-1",
            "event_head": "event-12",
            "scan_generation": "scan-3",
            "frontier_disposition": "local_wait",
            "transactions": [
                {
                    "transaction_id": "package-a",
                    "scope": "package",
                    "work_key": "package-a",
                    "batch_id": "batch-a",
                    "package_id": "a",
                    "state": "blocked",
                    "affected_cone": "package-a",
                    "consumer": "consumer-a",
                }
            ],
            "covered_transaction_ids": ["package-a"],
        }
    )
    assert local["status"] == "valid"
    assert local["parent_state"] == "open"
    assert local["parent_wait_claim_allowed"] is False
    assert local["global_frontier_reconciled"] is False
    assert "LOCAL_WAIT_SCOPE_PRESERVED" in local["reason_codes"]

    incomplete = reconcile_global_frontier(
        {
            "parent_mainline_id": "mainline-1",
            "event_head": "event-13",
            "scan_generation": "scan-4",
            "frontier_disposition": "no_positive_global_candidate",
            "transactions": [
                {"transaction_id": "package-a", "scope": "package"},
                {"transaction_id": "package-b", "scope": "package"},
            ],
            "covered_transaction_ids": ["package-a"],
        }
    )
    assert incomplete["status"] == "invalid"
    assert incomplete["parent_wait_claim_allowed"] is False
    assert "GLOBAL_COVERAGE_INCOMPLETE" in incomplete["reason_codes"]

    collision = reconcile_global_frontier(
        {
            "parent_mainline_id": "mainline-1",
            "event_head": "event-14",
            "scan_generation": "scan-5",
            "frontier_disposition": "durable_wait",
            "transactions": [
                {
                    "transaction_id": "mainline-1",
                    "scope": "package",
                    "work_key": "mainline-1",
                }
            ],
            "covered_transaction_ids": ["mainline-1"],
        }
    )
    assert collision["status"] == "invalid"
    assert "PACKAGE_PARENT_SCOPE_COLLISION" in collision["scope_violations"]


def test_scan_task_run_projects_invalid_parent_wait_receipt_fail_closed(tmp_path: Path) -> None:
    run_dir = _write_scan_run(
        tmp_path,
        "frontier-scope",
        [
            {
                "run_id": "frontier-scope",
                "schema_version": "codex.verified-task-run.v1",
                "event_id": "frontier-1",
                "phase": "global_frontier_reconciliation",
                "exit_code": 0,
                "global_frontier_reconciliation": {
                    "parent_mainline_id": "mainline-1",
                    "event_head": "event-9",
                    "scan_generation": "scan-1",
                    "frontier_disposition": "durable_wait",
                    "transactions": [
                        {
                            "transaction_id": "mainline-1",
                            "scope": "package",
                            "work_key": "mainline-1",
                        }
                    ],
                    "covered_transaction_ids": ["mainline-1"],
                },
            }
        ],
    )
    report = scan_task_run(run_dir)
    receipt = report["global_frontier_reconciliation"]
    assert receipt["status"] == "invalid"
    assert receipt["parent_wait_claim_allowed"] is False
    assert "GLOBAL_FRONTIER_RECONCILIATION_PROJECTED" in report["reason_codes"]


def test_identity_json_and_preflight_are_fail_closed_before_model(tmp_path: Path) -> None:
    missing = reconcile_identity({"declared": "grok-4.5", "selected": "grok-4.5", "observed": ""})
    assert missing["status"] == "unverified"
    assert missing["reason_codes"] == ["OBSERVED_IDENTITY_MISSING"]
    mismatch = reconcile_identity(
        {
            "declared": "grok-4.5",
            "selected": "grok-4.5",
            "observed": "other",
            "allowed_observed": ["grok-4.5-build"],
        }
    )
    assert mismatch["reason_codes"] == ["MODEL_IDENTITY_MISMATCH"]

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["lane"],
        "properties": {"lane": {"type": "string"}},
    }
    prefixed = validate_strict_json_result('narration\n{"lane":"x"}', schema)
    assert prefixed == {
        "ok": False,
        "reason_code": "RESULT_JSON_PREFIX_INVALID",
        "attempt_status": "rejected",
    }
    assert validate_strict_json_result('{"lane":"x"}', schema)["attempt_status"] == "accepted"
    assert (
        validate_strict_json_result('{"lane":1}', schema)["reason_code"]
        == "RESULT_JSON_SCHEMA_MISMATCH"
    )

    root = tmp_path / "root"
    selector = root / "services" / "agent_runtime" / "routing_policy_reader.py"
    selector.parent.mkdir(parents=True)
    selector.write_text(
        "def resolve_supervisor_worker_decision():\n    return {}\n", encoding="utf-8"
    )
    preparer = root / "scripts" / "prepare_direct_worker_pool_common_contract.py"
    preparer.parent.mkdir(parents=True)
    preparer.write_text("# preparer\n", encoding="utf-8")
    python_exe = root / ".venv" / "Scripts" / "python.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.write_bytes(b"runtime")
    schema_path = tmp_path / "result.schema.json"
    _write_json(schema_path, schema)
    fake = preflight_supervisor_root(root, phase="EXPLORE", json_schema_path=schema_path)
    assert fake["ok"] is False
    assert "SUPERVISOR_SELECTOR_PROBE_FAILED" in fake["reason_codes"]
    assert "COMMON_CONTRACT_PREPARER_PROBE_FAILED" in fake["reason_codes"]
    assert fake["model_tokens"] == 0

    ok = preflight_supervisor_root(REPO_ROOT, phase="EXPLORE", json_schema_path=schema_path)
    assert ok["ok"] is True
    assert ok["selector_probe"]["executed"] is True
    assert ok["preparer_probe"]["help_contract"] is True
    invalid_phase = preflight_supervisor_root(
        REPO_ROOT, phase="IMPLEMENT", json_schema_path=schema_path
    )
    assert invalid_phase["ok"] is False
    assert invalid_phase["reason_codes"] == ["SUPERVISOR_PHASE_INVALID"]
    assert invalid_phase["model_call_allowed"] is False

    missing_schema = preflight_supervisor_root(REPO_ROOT, phase="EXPLORE", require_json_object=True)
    assert missing_schema["reason_codes"] == ["RESULT_SCHEMA_BOUND_OR_PREMODEL_REJECT"]
    assert missing_schema["model_call_allowed"] is False

    selector.unlink()
    selector_missing = preflight_supervisor_root(root, phase="EXPLORE")["reason_codes"]
    assert "SUPERVISOR_SELECTOR_MISSING" in selector_missing
    assert "COMMON_CONTRACT_PREPARER_PROBE_FAILED" in selector_missing
    selector.write_text(
        "def resolve_supervisor_worker_decision():\n    return {}\n", encoding="utf-8"
    )
    preparer.unlink()
    preparer_missing = preflight_supervisor_root(root, phase="EXPLORE")["reason_codes"]
    assert "SUPERVISOR_SELECTOR_PROBE_FAILED" in preparer_missing
    assert "COMMON_CONTRACT_PREPARER_MISSING" in preparer_missing
    preparer.write_text("# preparer\n", encoding="utf-8")
    python_exe.unlink()
    assert preflight_supervisor_root(root, phase="EXPLORE")["reason_codes"] == [
        "SUPERVISOR_RUNTIME_MISSING"
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX virtualenv layout regression")
def test_preflight_accepts_posix_virtualenv_runtime(tmp_path: Path) -> None:
    root = tmp_path / "root"
    selector = root / "services" / "agent_runtime" / "routing_policy_reader.py"
    selector.parent.mkdir(parents=True)
    selector.write_text(
        "def resolve_supervisor_worker_decision(request, runtime_root=None):\n"
        "    if request is None:\n"
        "        raise TypeError('request must be an object')\n"
        "    return {}\n",
        encoding="utf-8",
    )
    preparer = root / "scripts" / "prepare_direct_worker_pool_common_contract.py"
    preparer.parent.mkdir(parents=True)
    preparer.write_text(
        "import argparse\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--selection-receipt')\n"
        "parser.add_argument('--work-key')\n"
        "parser.add_argument('--output')\n"
        "parser.parse_args()\n",
        encoding="utf-8",
    )
    runtime = root / ".venv" / "bin" / "python"
    runtime.parent.mkdir(parents=True)
    runtime.symlink_to(Path(sys.executable))

    report = preflight_supervisor_root(root, phase="EXPLORE")

    assert report["ok"] is True
    assert report["python_executable"] == str(runtime)
    assert report["selector_probe"]["executed"] is True
    assert report["preparer_probe"]["help_contract"] is True


def test_temporal_recovery_temporary_object_and_promotion_truth(tmp_path: Path) -> None:
    temporal = reconcile_temporal_identity(
        {
            "deployment_name": "xinao",
            "build_id": "repo-build",
            "task_queue": "queue",
            "work_key": "work-temporal",
            "workflow_id": "workflow-temporal",
        },
        {
            "deployment_name": "xinao",
            "current_build_id": "live-build",
            "task_queue": "queue",
            "work_key": "work-temporal",
            "workflow_id": "workflow-temporal",
            "run_id": "run-temporal-1",
            "workflow_versioning": "UNVERSIONED",
            "activity_versioning": "UNVERSIONED",
            "pollers": None,
        },
    )
    assert temporal["status"] == "partial"
    assert "TEMPORAL_BUILD_PIN_DRIFT" in temporal["reason_codes"]
    assert "TEMPORAL_QUEUE_UNVERSIONED" in temporal["reason_codes"]
    assert temporal["mutation_performed"] is False

    partial_recovery = evaluate_recovery_truth(
        {
            "declared": {"archive_mode": "on", "backup_dirs": ["wal"]},
            "live": {"container": "running"},
        }
    )
    assert partial_recovery["status"] == "partial"
    assert partial_recovery["reason_codes"] == ["RESTORE_CANARY_MISSING"]
    manifest_ref = _artifact_ref(tmp_path, "restore-manifest.json", '{"manifest":true}\n')
    receipt_ref = _artifact_ref(tmp_path, "restore-receipt.json", '{"restored":true}\n')
    authorization_ref = _artifact_ref(
        tmp_path, "restore-authorization.json", '{"authorized_scope":"isolated"}\n'
    )
    canary_ref = _artifact_ref(tmp_path, "restore-canary.json", '{"consumer":"passed"}\n')
    verified_recovery = evaluate_recovery_truth(
        {
            "declared": {},
            "live": {},
            "isolated_restore": {
                "passed": True,
                "data_identity_match": True,
                "source_identity": "source:backup-1",
                "target_identity": "isolated:restore-1",
                "manifest_ref": manifest_ref,
                "receipt_ref": receipt_ref,
                "authorization_ref": authorization_ref,
            },
            "downstream_canary": {
                "passed": True,
                "real_consumer": True,
                "source_event_id": "restore-canary-event",
                "evidence_ref": canary_ref,
            },
        }
    )
    assert verified_recovery["status"] == "verified"
    assert verified_recovery["recovery_boundary_verified"] is True
    assert verified_recovery["completion_claim_allowed"] is False

    unclassified = evaluate_temporary_object({"object_id": "candidate"})
    assert unclassified["decision"] == "quarantine_unclassified"
    assert unclassified["delete_performed"] is False
    expired = evaluate_temporary_object(
        {
            "object_id": "candidate",
            "owner": "codex",
            "expiry": "2026-07-19T00:00:00Z",
            "next_consumer": "test",
            "pin": "old",
            "current_pin": "new",
        },
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    assert expired["decision"] == "revalidation_required"
    assert expired["reason_codes"] == ["TEMP_OBJECT_REVALIDATION_REQUIRED"]
    reusable = evaluate_temporary_object(
        {
            "object_id": "candidate",
            "owner": "codex",
            "expiry": "2026-07-21T00:00:00Z",
            "next_consumer": "test",
            "pin": "current",
            "current_pin": "current",
            "manifest_ok": True,
            "canary_ok": True,
        },
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    assert reusable["decision"] == "reuse_admitted"
    assert reusable["reason_codes"] == ["TEMP_OBJECT_REUSE_ADMITTED"]
    assert evaluate_promotion_evidence({"eval_passed": True, "live_consumer_verified": False}) == {
        "schema_version": "xinao.system_awareness.promotion_evidence.v1",
        "status": "partial",
        "promotion_allowed": False,
        "reason_codes": ["LIVE_CONSUMER_NOT_VERIFIED"],
    }


def test_trajectory_sampling_is_deterministic_and_checks_parent_authority() -> None:
    rows = [
        {
            "trajectory_id": "a",
            "event_id": "a",
            "envelope": True,
            "pin": True,
            "manifest": True,
            "authority": "non_parent_owner",
            "result_contract": True,
            "parent_complete_claim": True,
        },
        {
            "trajectory_id": "b",
            "event_id": "b",
            "envelope": True,
            "pin": True,
            "manifest": True,
            "authority": "parent_owner",
            "result_contract": True,
        },
    ]
    first = evaluate_trajectory_sample(rows, sample_size=2, seed="fixed")
    second = evaluate_trajectory_sample(rows, sample_size=2, seed="fixed")
    assert first == second
    report_a = next(row for row in first["reports"] if row["trajectory_id"] == "a")
    assert report_a["defect_codes"] == ["UNAUTHORIZED_PARENT_COMPLETION_CLAIM"]
    assert report_a["source_event_ref"] == "a"


def test_wakeable_wait_requires_complete_reconciliation_and_verified_wake_surface() -> None:
    wait = evaluate_wakeable_wait(
        {
            "frontier_reconciled": True,
            "alternative_paths_checked": True,
            "prerequisites_checked": True,
            "positive_actions": [],
            "wake_conditions": ["new task-run event", "external dependency changes"],
            "durable_surface_verified": True,
        }
    )
    assert wait["status"] == "wakeable_wait"
    assert wait["reason_codes"] == ["WAKEABLE_WAIT_NO_POSITIVE_ACTION"]
    assert wait["completion_claim_allowed"] is False
    assert wait["blocked_claim_allowed"] is False

    active = evaluate_wakeable_wait(
        {
            "frontier_reconciled": True,
            "alternative_paths_checked": True,
            "prerequisites_checked": True,
            "positive_actions": ["run consumer canary"],
            "wake_conditions": [],
            "durable_surface_verified": False,
        }
    )
    assert active["wait_allowed"] is False
    assert "POSITIVE_ACTION_AVAILABLE" in active["reason_codes"]


def test_fresh_process_scans_utf8_task_run_and_failed_worker_cost(tmp_path: Path) -> None:
    run_id = "横向问题扫描"
    run_dir = tmp_path / run_id
    pool = tmp_path / "工人证据" / "pool_summary.json"
    _write_json(
        pool,
        {
            "schema_version": "xinao.grok_worker_pool.v2",
            "pool_id": "pool-1",
            "results": [{"status": "rejected", "usage": {"total_tokens": 120}, "lane": 0}],
        },
    )
    task = {
        "schema_version": "codex.verified-task-run.v1",
        "run_id": run_id,
        "mode": "bounded_task",
        "objective": "自动发现横向问题",
    }
    event = {
        "schema_version": "codex.verified-task-run.v1",
        "event_id": "事件-1",
        "run_id": run_id,
        "timestamp": "2026-07-20T00:00:00Z",
        "actor": "工人总线",
        "kind": "result",
        "phase": "worker_candidate_rejected",
        "summary": "中文摘要：结构化结果未生成",
        "evidence_refs": [str(pool)],
        "target": "wk:横向",
        "exit_code": 1,
        "duration_ms": None,
        "retry_class": "transient",
        "side_effect_id": None,
    }
    state = {
        "schema_version": "codex.verified-task-run.v1",
        "run_id": run_id,
        "status": "in_progress",
        "current_phase": event["phase"],
        "events_count": 1,
    }
    _write_json(run_dir / "task.json", task)
    _write_json(run_dir / "state.json", state)
    (run_dir / "events.jsonl").write_text(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "扫描结果.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_system_awareness_consumer.py"),
            "scan-task-run",
            "--task-run-dir",
            str(run_dir),
            "--high-burn-threshold",
            "100",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["utf8"]["roundtrip_ok"] is True
    assert report["utf8"]["reason_codes"] == [
        "UTF8_PATH_ROUNDTRIP_OK",
        "UTF8_EVENT_SEARCHABLE",
    ]
    assert report["episode_outcome"]["tokens"]["by_outcome"]["failed"] == 120
    assert "HIGH_BURN_NO_CONVERSION" in report["episode_outcome"]["reason_codes"]
    assert report["problem_projection"]["problem_count"] == 1


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _worktree_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    worktree = tmp_path / "side worktree 中文"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "codex@example.invalid")
    _git(repo, "config", "user.name", "Codex Test")
    (repo / ".gitignore").write_text("*.secret\n", encoding="utf-8")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "base.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "worktree", "add", "-b", "feature/lifecycle", str(worktree), "main")
    return repo, worktree


def _artifact_ref(root: Path, name: str, body: str) -> str:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return f"{path}#sha256={hashlib.sha256(path.read_bytes()).hexdigest()}"


def _work_unit_evidence_ref(
    root: Path,
    name: str,
    *,
    kind: str,
    work_key: str,
    subject: str,
    observed_value: str,
) -> str:
    path = root / name
    _write_json(
        path,
        {
            "schema_version": "xinao.work_unit_finalizer_evidence.v1",
            "kind": kind,
            "work_key": work_key,
            "subject": subject,
            "observed_value": observed_value,
            "readback_verified": True,
            "authority": False,
            "completion_claim_allowed": False,
        },
    )
    return f"{path}#sha256={hashlib.sha256(path.read_bytes()).hexdigest()}"


def _lifecycle_event(
    run_id: str,
    event_id: str,
    ordinal: int,
    phase: str,
    work_key: str,
    side_effect_id: str,
    evidence_refs: list[str],
    *,
    actor: str = "codex_owner",
) -> dict[str, object]:
    return {
        "schema_version": "codex.verified-task-run.v1",
        "event_id": event_id,
        "run_id": run_id,
        "timestamp": f"2026-07-20T00:{ordinal:02d}:00Z",
        "actor": actor,
        "kind": "result",
        "phase": phase,
        "summary": phase,
        "evidence_refs": evidence_refs,
        "target": work_key,
        "exit_code": 0,
        "duration_ms": 1,
        "retry_class": "none",
        "side_effect_id": side_effect_id,
    }


def _write_lifecycle_run(run_dir: Path, events: list[dict[str, object]]) -> bytes:
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_dir.name
    _write_json(
        run_dir / "task.json",
        {
            "schema_version": "codex.verified-task-run.v1",
            "run_id": run_id,
            "mode": "bounded_task",
            "objective": "work-unit lifecycle test",
        },
    )
    _write_json(
        run_dir / "state.json",
        {
            "schema_version": "codex.verified-task-run.v1",
            "run_id": run_id,
            "status": "in_progress",
            "current_phase": events[-1]["phase"],
            "events_count": len(events),
        },
    )
    raw = b"".join(
        (
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        for event in events
    )
    (run_dir / "events.jsonl").write_bytes(raw)
    return raw


def _retire_candidate_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, object], list[dict[str, object]]]:
    repo, worktree = _worktree_repo(tmp_path)
    initial = scan_worktree_lifecycle(repo, base_ref="main")
    observed_report = next(
        row for row in initial["worktrees"] if Path(row["worktree_path"]) == worktree.resolve()
    )
    observed = observed_report["observed"]
    work_key = "wk:test:work-unit"
    carrier_id = "carrier:test:1"
    run_dir = tmp_path / "task-runs" / "work-unit-run"
    event_path = run_dir / "events.jsonl"
    boundary_ref = _work_unit_evidence_ref(
        tmp_path,
        "boundary.json",
        kind="boundary_verification",
        work_key=work_key,
        subject="bounded-test-suite",
        observed_value="passed",
    )
    land_ref = _work_unit_evidence_ref(
        tmp_path,
        "land.json",
        kind="git_remote_ref",
        work_key=work_key,
        subject="origin/main",
        observed_value="abc",
    )
    no_effect_ref = _work_unit_evidence_ref(
        tmp_path,
        "effect-not-required.json",
        kind="effect_not_required",
        work_key=work_key,
        subject="documentation-only-carrier",
        observed_value="explicitly-not-required",
    )
    events = [
        _lifecycle_event(
            run_dir.name,
            "planned",
            1,
            "work_unit_planned",
            work_key,
            "se:planned",
            [],
        ),
        _lifecycle_event(
            run_dir.name,
            "active",
            2,
            "work_unit_active",
            work_key,
            "se:active",
            [],
        ),
        _lifecycle_event(
            run_dir.name,
            "verifying",
            3,
            "work_unit_verifying",
            work_key,
            "se:verifying",
            [],
        ),
        _lifecycle_event(
            run_dir.name,
            "boundary",
            4,
            "work_unit_boundary_verified",
            work_key,
            "se:boundary",
            [boundary_ref],
            actor="pytest",
        ),
        _lifecycle_event(
            run_dir.name,
            "land-requested",
            5,
            "work_unit_land_requested",
            work_key,
            "se:land-requested",
            [],
        ),
        _lifecycle_event(
            run_dir.name,
            "land",
            6,
            "work_unit_land_verified",
            work_key,
            "se:land",
            [land_ref],
            actor="pytest",
        ),
        _lifecycle_event(
            run_dir.name,
            "no-effect",
            7,
            "work_unit_effect_not_required",
            work_key,
            "se:no-effect",
            [no_effect_ref],
            actor="pytest",
        ),
        _lifecycle_event(
            run_dir.name,
            "retire-request",
            8,
            "worktree_lifecycle_retire_requested",
            work_key,
            "se:retire-request",
            [
                f"xinao-worktree-carrier:{carrier_id}:1",
                f"xinao-worktree-observation-sha256:{observed['observation_sha256']}",
            ],
        ),
    ]
    raw = _write_lifecycle_run(run_dir, events)
    record = dict(observed_report["record_template"])
    record.update(
        {
            "carrier_id": carrier_id,
            "carrier_generation": 1,
            "purpose": "bounded lifecycle test",
            "owner": "codex_owner",
            "declared_state": "retire_requested",
            "recorded_at": "2026-07-20T00:00:00Z",
            "expires_at": "2026-07-20T23:59:59Z",
            "work_key": work_key,
            "side_effect_id": "se:retire-request",
            "task_run_event_ref": f"{event_path}#retire-request",
            "event_head": {
                "event_count": 8,
                "event_id": "retire-request",
                "prefix_sha256": hashlib.sha256(raw).hexdigest(),
            },
            "finalizer_event_refs": {
                "boundary_verified": f"{event_path}#boundary",
                "land_verified": f"{event_path}#land",
                "effect_not_required": f"{event_path}#no-effect",
            },
        }
    )
    return repo, worktree, run_dir, record, events


def test_worktree_candidate_binds_logical_identity_finalizers_and_fresh_process(
    tmp_path: Path,
) -> None:
    repo, worktree, run_dir, record, events = _retire_candidate_fixture(tmp_path)
    records_path = tmp_path / "lifecycle-records.json"
    records = {
        "schema_version": "xinao.worktree_lifecycle_records.v1",
        "authority": False,
        "delete_authority": False,
        "records": [record],
    }
    _write_json(records_path, records)
    records_ref = f"{records_path}#sha256={hashlib.sha256(records_path.read_bytes()).hexdigest()}"
    events.append(
        _lifecycle_event(
            run_dir.name,
            "records-published",
            9,
            "worktree_lifecycle_records_published",
            "wk:test:work-unit",
            "se:records-published",
            [records_ref],
        )
    )
    _write_lifecycle_run(run_dir, events)

    report = scan_worktree_lifecycle(
        repo,
        base_ref="main",
        records=records,
        now=datetime(2026, 7, 20, 0, 10, tzinfo=timezone.utc),
    )
    side = next(row for row in report["worktrees"] if Path(row["worktree_path"]) == worktree)
    assert side["decision"] == "retire_candidate"
    assert side["retire_ready"] is True
    assert side["retire_ready_scope"] == "carrier_removal_candidate_only"
    assert side["work_key"] == "wk:test:work-unit"
    assert side["carrier_id"] == "carrier:test:1"
    assert side["authority"] is False
    assert side["delete_authority"] is False
    assert side["delete_performed"] is False
    assert side["automatic_delete_allowed"] is False
    assert side["completion_claim_allowed"] is False

    task_report = scan_task_run(run_dir)
    unit = next(
        row
        for row in task_report["work_unit_lifecycle"]["work_units"]
        if row["work_key"] == "wk:test:work-unit"
    )
    assert unit["state"] == "effect_not_required"
    assert unit["finalizers"]["all_parent_predicates_observed"] is True
    assert unit["carrier_records_binding"]["sha256"] == records_ref.rsplit("=", 1)[1]
    assert unit["completion_claim_allowed"] is False

    output = tmp_path / "fresh-worktree-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_system_awareness_consumer.py"),
            "scan-worktrees",
            "--repo-root",
            str(repo),
            "--base-ref",
            "main",
            "--task-run-dir",
            str(run_dir),
            "--now",
            "2026-07-20T00:10:00Z",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    fresh = json.loads(output.read_text(encoding="utf-8"))
    assert fresh["summary"]["retire_ready_count"] == 1
    assert fresh["delete_performed"] is False


def test_failed_or_untyped_effect_event_cannot_complete_work_unit(tmp_path: Path) -> None:
    _, _, run_dir, _, events = _retire_candidate_fixture(tmp_path)
    no_effect = next(event for event in events if event["event_id"] == "no-effect")
    no_effect["kind"] = "observation"
    no_effect["exit_code"] = 1
    _write_lifecycle_run(run_dir, events)

    unit = next(
        row
        for row in scan_task_run(run_dir)["work_unit_lifecycle"]["work_units"]
        if row["work_key"] == "wk:test:work-unit"
    )
    assert unit["state"] == "landed"
    assert unit["finalizers"]["effect_not_required"]["status"] == "pending"
    assert unit["finalizers"]["all_parent_predicates_observed"] is False
    assert unit["invalid_transitions"][-1]["event_id"] == "no-effect"


def test_record_producer_publishes_real_observation_and_rejects_generation_reuse(
    tmp_path: Path,
) -> None:
    repo, worktree = _worktree_repo(tmp_path)
    observed_report = next(
        row
        for row in scan_worktree_lifecycle(repo, base_ref="main")["worktrees"]
        if Path(row["worktree_path"]) == worktree.resolve()
    )
    observed = observed_report["observed"]
    run_dir = tmp_path / "task-runs" / "record-producer-run"
    event = _lifecycle_event(
        run_dir.name,
        "carrier-active",
        1,
        "worktree_lifecycle_active",
        "work-producer",
        "se:carrier-active",
        [
            "xinao-worktree-carrier:carrier:producer:1",
            f"xinao-worktree-observation-sha256:{observed['observation_sha256']}",
        ],
    )
    _write_lifecycle_run(run_dir, [event])
    records_path = tmp_path / "state" / "worktree-records.json"
    report = publish_worktree_lifecycle_record(
        repo,
        records_path,
        worktree_path=worktree,
        task_run_event_ref=f"{run_dir / 'events.jsonl'}#carrier-active",
        carrier_id="carrier:producer",
        carrier_generation=1,
        purpose="real producer canary",
        owner="codex_owner",
        declared_state="active",
        work_key="work-producer",
        side_effect_id="se:carrier-active",
        base_ref="main",
    )
    assert report["status"] == "record_published"
    assert report["git_mutation_performed"] is False
    records = json.loads(records_path.read_text(encoding="utf-8"))
    assert records["generation_floors"] == {"carrier:producer": 1}
    rescanned = scan_worktree_lifecycle(
        repo,
        base_ref="main",
        records=records,
        now=datetime(2026, 7, 20, 0, 30, tzinfo=timezone.utc),
    )
    side = next(row for row in rescanned["worktrees"] if Path(row["worktree_path"]) == worktree)
    assert side["decision"] == "active"

    other_worktree = tmp_path / "second carrier"
    _git(repo, "worktree", "add", "-b", "feature/second", str(other_worktree), "main")
    with pytest.raises(awareness_module.SystemAwarenessError) as reused:
        publish_worktree_lifecycle_record(
            repo,
            records_path,
            worktree_path=other_worktree,
            task_run_event_ref=f"{run_dir / 'events.jsonl'}#carrier-active",
            carrier_id="carrier:producer",
            carrier_generation=1,
            purpose="different incarnation must not reuse generation",
            owner="codex_owner",
            declared_state="active",
            work_key="work-producer",
            side_effect_id="se:carrier-active",
            base_ref="main",
        )
    assert reused.value.reason_code == "WORKTREE_CARRIER_GENERATION_REUSED"


def test_ignored_material_tree_equivalence_and_polluted_git_env_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, worktree = _worktree_repo(tmp_path / "ignored")
    (worktree / "local.secret").write_text("unique\n", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "wrong-git-dir"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "wrong-work-tree"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "wrong-index"))
    ignored = scan_worktree_lifecycle(repo, base_ref="main")
    side = next(row for row in ignored["worktrees"] if Path(row["worktree_path"]) == worktree)
    assert side["observed"]["ignored_material_present"] is True
    assert side["observed"]["ignored"] >= 1
    assert side["retire_ready"] is False
    assert ignored["source"]["inherited_git_environment_sanitized"] is True

    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    monkeypatch.delenv("GIT_INDEX_FILE")

    repo2, worktree2 = _worktree_repo(tmp_path / "tree-equivalence")
    (worktree2 / "temporary.txt").write_text("temporary\n", encoding="utf-8")
    _git(worktree2, "add", "temporary.txt")
    _git(worktree2, "commit", "-m", "temporary")
    _git(worktree2, "revert", "--no-edit", "HEAD")
    tree_report = scan_worktree_lifecycle(repo2, base_ref="main")
    reverted = next(
        row for row in tree_report["worktrees"] if Path(row["worktree_path"]) == worktree2
    )
    assert reverted["observed"]["head_tree_reachable_from_base"] is True
    assert reverted["observed"]["head_is_ancestor_of_base"] is False
    assert reverted["observed"]["commits_absorbed"] is False
    assert reverted["retire_ready"] is False


def test_retired_tombstone_is_distinct_from_unexplained_missing_carrier(tmp_path: Path) -> None:
    repo, worktree, run_dir, record, events = _retire_candidate_fixture(tmp_path)
    _git(repo, "worktree", "remove", str(worktree))
    removal_ref = _artifact_ref(tmp_path, "removal-readback.json", '{"absent":true}\n')
    events.append(
        _lifecycle_event(
            run_dir.name,
            "retired",
            9,
            "worktree_lifecycle_retired",
            "wk:test:work-unit",
            "se:remove",
            [
                "xinao-worktree-carrier:carrier:test:1:1",
                f"xinao-worktree-absence-path-id:{record['path_id']}",
                removal_ref,
            ],
        )
    )
    raw = _write_lifecycle_run(run_dir, events)
    tombstone = {
        **record,
        "declared_state": "retired",
        "side_effect_id": "se:remove",
        "task_run_event_ref": f"{run_dir / 'events.jsonl'}#retired",
        "event_head": {
            "event_count": 9,
            "event_id": "retired",
            "prefix_sha256": hashlib.sha256(raw).hexdigest(),
        },
    }
    records = {
        "schema_version": "xinao.worktree_lifecycle_records.v1",
        "authority": False,
        "delete_authority": False,
        "records": [tombstone],
    }
    retired = scan_worktree_lifecycle(repo, base_ref="main", records=records)
    assert retired["summary"]["retired_count"] == 1
    assert retired["orphan_records"] == []
    assert retired["retired_carriers"][0]["reason_code"] == ("WORKTREE_RETIRED_TOMBSTONE_VERIFIED")

    worktree.mkdir()
    residual = scan_worktree_lifecycle(repo, base_ref="main", records=records)
    assert residual["summary"]["retired_count"] == 0
    assert residual["orphan_records"][0]["reason_code"] == ("WORKTREE_RETIRED_PATH_STILL_PRESENT")
    worktree.rmdir()

    unexplained = {
        **tombstone,
        "declared_state": "active",
    }
    orphaned = scan_worktree_lifecycle(
        repo,
        base_ref="main",
        records={**records, "records": [unexplained]},
    )
    assert orphaned["summary"]["retired_count"] == 0
    assert len(orphaned["orphan_records"]) == 1


def test_old_observation_replay_unbounded_ttl_and_self_declared_archive_fail_closed(
    tmp_path: Path,
) -> None:
    repo, worktree, run_dir, record, events = _retire_candidate_fixture(tmp_path)
    records = {
        "schema_version": "xinao.worktree_lifecycle_records.v1",
        "authority": False,
        "delete_authority": False,
        "records": [record],
    }
    (worktree / "base.txt").write_text("drifted\n", encoding="utf-8")
    replayed = scan_worktree_lifecycle(
        repo,
        base_ref="main",
        records=records,
        now=datetime(2026, 7, 20, 0, 10, tzinfo=timezone.utc),
    )
    side = next(row for row in replayed["worktrees"] if Path(row["worktree_path"]) == worktree)
    assert side["decision"] == "record_stale"
    assert "WORKTREE_LIFECYCLE_FACT_DRIFT" in side["reason_codes"]
    assert side["retire_ready"] is False

    (worktree / "base.txt").write_text("base\n", encoding="utf-8")
    unbounded = {**record, "expires_at": "2026-07-22T00:00:00Z"}
    ttl = scan_worktree_lifecycle(
        repo,
        base_ref="main",
        records={**records, "records": [unbounded]},
        now=datetime(2026, 7, 20, 0, 10, tzinfo=timezone.utc),
    )
    ttl_side = next(row for row in ttl["worktrees"] if Path(row["worktree_path"]) == worktree)
    assert ttl_side["decision"] == "record_stale"
    assert "WORKTREE_LIFECYCLE_RECORD_EXPIRED" in ttl_side["reason_codes"]

    (worktree / "unique.txt").write_text("unique\n", encoding="utf-8")
    observed_scan = scan_worktree_lifecycle(repo, base_ref="main")
    observed_report = next(
        row for row in observed_scan["worktrees"] if Path(row["worktree_path"]) == worktree
    )
    observed = observed_report["observed"]
    events.append(
        _lifecycle_event(
            run_dir.name,
            "archive-request",
            9,
            "worktree_lifecycle_archive_required",
            "wk:test:work-unit",
            "se:archive-request",
            [
                "xinao-worktree-carrier:carrier:test:1:1",
                f"xinao-worktree-observation-sha256:{observed['observation_sha256']}",
            ],
        )
    )
    raw = _write_lifecycle_run(run_dir, events)
    artifact_ref = _artifact_ref(tmp_path, "archive-payload.bin", "not a restore\n")
    artifact_path, artifact_sha = artifact_ref.rsplit("#sha256=", 1)
    fake_manifest_path = tmp_path / "fake-archive-manifest.json"
    fake_manifest = {
        "schema_version": "xinao.worktree_archive_manifest.v1",
        "authority": False,
        "coverage_complete": True,
        "source": {
            "path_id": observed["path_id"],
            "worktree_path": observed["worktree_path"],
            "head": observed["head"],
            "observation_sha256": observed["observation_sha256"],
            "dirty_fingerprint": observed["dirty_fingerprint"],
            "ignored_fingerprint": observed["ignored_fingerprint"],
        },
        "artifacts": [{"path": artifact_path, "sha256": artifact_sha}],
    }
    _write_json(fake_manifest_path, fake_manifest)
    archive_record = dict(observed_report["record_template"])
    archive_record.update(
        {
            "carrier_id": "carrier:test:1",
            "carrier_generation": 1,
            "purpose": "archive negative",
            "owner": "codex_owner",
            "declared_state": "archive_required",
            "recorded_at": "2026-07-20T00:00:00Z",
            "expires_at": "2026-07-20T23:59:59Z",
            "work_key": "wk:test:work-unit",
            "side_effect_id": "se:archive-request",
            "task_run_event_ref": f"{run_dir / 'events.jsonl'}#archive-request",
            "event_head": {
                "event_count": 9,
                "event_id": "archive-request",
                "prefix_sha256": hashlib.sha256(raw).hexdigest(),
            },
            "archive": {
                "manifest_path": str(fake_manifest_path),
                "manifest_sha256": hashlib.sha256(fake_manifest_path.read_bytes()).hexdigest(),
            },
        }
    )
    archive = scan_worktree_lifecycle(
        repo,
        base_ref="main",
        records={**records, "records": [archive_record]},
        now=datetime(2026, 7, 20, 0, 10, tzinfo=timezone.utc),
    )
    archive_side = next(
        row for row in archive["worktrees"] if Path(row["worktree_path"]) == worktree
    )
    assert archive_side["decision"] == "archive_required"
    assert archive_side["archive"]["reason_code"] == ("WORKTREE_ARCHIVE_VERIFICATION_MISSING")
    assert archive_side["retire_ready"] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows path identity regression")
def test_windows_path_containment_and_slash_base_ref_are_exact(tmp_path: Path) -> None:
    parent = tmp_path / "MixedCaseParent"
    child = parent / "Child"
    child.mkdir(parents=True)
    assert awareness_module._path_within(Path(str(child).upper()), Path(str(parent).lower()))
    assert awareness_module._protected_base_branch_ref("origin/release/1.0") == (
        "refs/heads/release/1.0"
    )
