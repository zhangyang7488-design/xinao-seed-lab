from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from services.agent_runtime.system_awareness_consumer import (
    evaluate_completion_card,
    evaluate_promotion_evidence,
    evaluate_recovery_truth,
    evaluate_temporary_object,
    evaluate_trajectory_sample,
    evaluate_wakeable_wait,
    preflight_supervisor_root,
    project_episode_outcome,
    reconcile_identity,
    reconcile_problem_lifecycle,
    reconcile_temporal_identity,
    scan_task_run,
    validate_strict_json_result,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        "events_count": 1,
    }
    _write_json(run_dir / "task.json", task)
    _write_json(run_dir / "state.json", state)
    (run_dir / "events.jsonl").write_text(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    report = scan_task_run(run_dir)
    assert report["episode_outcome"]["tokens"]["by_outcome"] == {
        "accepted": 30,
        "failed": 70,
        "cancelled": 0,
        "incomplete": 0,
    }


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
    ok = preflight_supervisor_root(root, phase="EXPLORE", json_schema_path=schema_path)
    assert ok["ok"] is True
    assert ok["model_tokens"] == 0
    invalid_phase = preflight_supervisor_root(root, phase="IMPLEMENT", json_schema_path=schema_path)
    assert invalid_phase["ok"] is False
    assert invalid_phase["reason_codes"] == ["SUPERVISOR_PHASE_INVALID"]
    assert invalid_phase["model_call_allowed"] is False

    missing_schema = preflight_supervisor_root(root, phase="EXPLORE", require_json_object=True)
    assert missing_schema["reason_codes"] == ["RESULT_SCHEMA_BOUND_OR_PREMODEL_REJECT"]
    assert missing_schema["model_call_allowed"] is False

    selector.unlink()
    assert preflight_supervisor_root(root, phase="EXPLORE")["reason_codes"] == [
        "SUPERVISOR_SELECTOR_MISSING"
    ]
    selector.write_text(
        "def resolve_supervisor_worker_decision():\n    return {}\n", encoding="utf-8"
    )
    preparer.unlink()
    assert preflight_supervisor_root(root, phase="EXPLORE")["reason_codes"] == [
        "COMMON_CONTRACT_PREPARER_MISSING"
    ]
    preparer.write_text("# preparer\n", encoding="utf-8")
    python_exe.unlink()
    assert preflight_supervisor_root(root, phase="EXPLORE")["reason_codes"] == [
        "SUPERVISOR_RUNTIME_MISSING"
    ]


def test_temporal_recovery_temporary_object_and_promotion_truth() -> None:
    temporal = reconcile_temporal_identity(
        {"deployment_name": "xinao", "build_id": "repo-build"},
        {
            "deployment_name": "xinao",
            "current_build_id": "live-build",
            "task_queue": "queue",
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
    verified_recovery = evaluate_recovery_truth(
        {
            "declared": {},
            "live": {},
            "isolated_restore": {"authorized": True, "passed": True, "data_identity_match": True},
            "downstream_canary": {"passed": True, "real_consumer": True},
        }
    )
    assert verified_recovery["status"] == "verified"

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
