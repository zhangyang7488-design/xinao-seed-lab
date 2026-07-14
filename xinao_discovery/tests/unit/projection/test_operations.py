from __future__ import annotations

import json
from pathlib import Path

from xinao.projection.operations import (
    _canonical_hash,
    _readonly_environment,
    build_workflow_projection,
    render_tui,
    verify_evidence_report,
)


def _report(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    snapshot = {"operation_id": "op-1", "complete": True}
    snapshot_hash = _canonical_hash(snapshot)
    artifact = runtime / "proof" / f"{snapshot_hash}.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        json.dumps(
            {
                "workflow_id": "wf-1",
                "snapshot_hash": snapshot_hash,
                "snapshot": snapshot,
            }
        ),
        encoding="utf-8",
    )
    value = {
        "status": "verified",
        "checks": {"one": True},
        "prepared": {"workflow_id": "wf-1", "run_id": "run-1"},
        "mainline_result": {
            "operation_id": "op-1",
            "complete": True,
            "paused": False,
            "stop_requested": False,
            "fact_count": 2,
            "duplicate_signals": 2,
            "last_evidence_ref": f"/evidence/proof/{snapshot_hash}.json",
            "control_audit": [{"action": "PAUSE"}, {"action": "RESUME"}],
        },
        "history": {
            "mainline": {"replay_failure": None},
            "campaign": {"replay_failure": None},
        },
        "report_hash": "",
    }
    value["report_hash"] = _canonical_hash(value)
    report = tmp_path / "report.json"
    report.write_text(json.dumps(value), encoding="utf-8")
    return report, runtime


def test_readonly_environment_drops_domain_credentials() -> None:
    result = _readonly_environment(
        {
            "PATH": "safe",
            "SYSTEMROOT": "safe",
            "TEMP": "safe-temp",
            "DATABASE_URL": "secret",
            "PGPASSWORD": "secret",
            "XINAO_API_TOKEN": "secret",
        }
    )
    assert result == {
        "PATH": "safe",
        "SYSTEMROOT": "safe",
        "TEMP": "safe-temp",
        "NO_COLOR": "1",
        "APPDATA": "safe-temp",
    }


def test_report_verification_and_projection_show_pause_resume(tmp_path: Path) -> None:
    report, runtime = _report(tmp_path)
    verification = verify_evidence_report(report, runtime_root=runtime)
    assert verification["ok"] is True
    projection = build_workflow_projection(
        report,
        runtime_root=runtime,
        temporal_description={
            "workflowExecutionInfo": {
                "execution": {"workflowId": "wf-1", "runId": "run-1"},
                "type": {"name": "XinaoMainlineCanaryWorkflow"},
                "taskQueue": "queue-1",
                "status": "WORKFLOW_EXECUTION_STATUS_COMPLETED",
                "historyLength": "48",
            },
            "result": json.loads(report.read_text(encoding="utf-8"))["mainline_result"],
        },
    )
    assert projection["domain_write_credentials"] is False
    assert projection["pause_visible"] is True
    assert projection["resume_visible"] is True
    tui = render_tui(projection)
    assert "[READ ONLY]" in tui
    assert "PAUSE -> RESUME" in tui


def test_tampered_report_fails_closed(tmp_path: Path) -> None:
    report, runtime = _report(tmp_path)
    value = json.loads(report.read_text(encoding="utf-8"))
    value["checks"]["one"] = False
    report.write_text(json.dumps(value), encoding="utf-8")
    result = verify_evidence_report(report, runtime_root=runtime)
    assert result["ok"] is False
    assert result["checks"]["report_hash_matches"] is False
    assert result["checks"]["all_report_checks_pass"] is False
