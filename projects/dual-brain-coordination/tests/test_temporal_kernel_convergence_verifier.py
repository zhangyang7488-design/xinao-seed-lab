from __future__ import annotations

from scripts.verify_temporal_kernel_convergence import evaluate_convergence


def _snapshot() -> dict[str, object]:
    sha = "a" * 64
    snapshot: dict[str, object] = {
        "workflow_status": "WorkflowExecutionStatus.COMPLETED",
        "workflow_result": {
            "ok": True,
            "terminal_status": "completed",
            "finalize": {"kernel": {"ok": True, "required": True, "state": "completed"}},
            "langgraph_children": [{"passed": True, "failed_checks": []}],
            "step_evidence": [
                {
                    "artifact": {
                        "artifact_path": "D:/evidence/step.json",
                        "sha256": sha,
                        "size_bytes": 12,
                        "sqlite_hook": {"ok": True},
                    }
                }
            ],
        },
        "task_view": {
            "task": {
                "state": "completed",
                "completed_at_ms": 1,
                "lease_owner": None,
                "lease_token": None,
                "metadata": {
                    "temporal_mode": "live",
                    "temporal_started_by": "codex",
                    "temporal_workflow_id": "workflow-1",
                    "temporal_run_id": "run-1",
                    "temporal_kernel_lease_token": "lease-1",
                },
            },
            "attempts": [{"state": "completed"}],
            "artifacts": [{"artifact_id": "art_1", "sha256": sha, "size_bytes": 12}],
        },
        "events": [
            {"event_type": "TaskDispatched"},
            {"event_type": "TemporalWorkflowStarted", "actor": "codex"},
            {"event_type": "ArtifactRegistered"},
            {"event_type": "TaskCompleted"},
        ],
        "artifact_probe": {
            "path": "D:/evidence/step.json",
            "exists": True,
            "sha256": sha,
            "size_bytes": 12,
        },
    }
    snapshot["workflow_result"]["finalize"]["workflow_id"] = "workflow-1"  # type: ignore[index]
    return snapshot


def test_four_way_terminal_and_artifact_equality_passes() -> None:
    result = evaluate_convergence(**_snapshot())
    assert result["ok"] is True
    assert result["failed_checks"] == []


def test_missing_required_kernel_hook_cannot_green() -> None:
    snapshot = _snapshot()
    snapshot["workflow_result"]["finalize"]["kernel"] = {  # type: ignore[index]
        "ok": True,
        "required": False,
        "state": "completed",
    }
    result = evaluate_convergence(**snapshot)
    assert result["ok"] is False
    assert result["failed_checks"] == ["kernel_hook_required"]


def test_duplicate_task_completed_event_cannot_green() -> None:
    snapshot = _snapshot()
    snapshot["events"].append({"event_type": "TaskCompleted"})  # type: ignore[union-attr]
    result = evaluate_convergence(**snapshot)
    assert result["ok"] is False
    assert "one_task_completed_event" in result["failed_checks"]
