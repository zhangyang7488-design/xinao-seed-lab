import json
from pathlib import Path

from services.agent_runtime import codex_333_task_transaction_control as module
from xinao_seedlab.cli.__main__ import main as cli_main


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_current_index(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "schema_version": "unit.current_333_run_index.v1",
            "status": "current_333_run_index_ready",
            "workflow_id": "unit-333-workflow",
            "workflow_run_id": "unit-run",
            "temporal": {
                "address": "127.0.0.1:7233",
                "port_open": True,
                "workflow_id": "unit-333-workflow",
                "workflow_run_id": "unit-run",
                "status": "Running",
                "task_queue": "xinao-codex-task-default",
                "pending_activity_count": 1,
            },
        },
    )


def test_insert_front_transaction_writes_backend_control_evidence(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _seed_current_index(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        routing_verb="插队",
        assignment_dag_node_id="urgent-node",
        wave_id="urgent-wave",
        priority=100,
        control_id="unit-insert-front",
        write=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["routing_verb"] == "insert_front"
    assert payload["signal_payload"]["insert_front"] is True
    assert payload["signal_payload"]["continue_same_task_signal"]["assignment_dag_node_id"] == (
        "urgent-node"
    )
    assert payload["live_signal"]["status"] == "temporal_task_control_signal_not_sent_dry_run"
    assert payload["workflow_ref"]["workflow_id"] == "unit-333-workflow"
    assert Path(payload["output_paths"]["latest"]).is_file()
    assert Path(payload["output_paths"]["readback"]).is_file()


def test_pause_cancel_and_resume_are_supported_transactions(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _seed_current_index(runtime)

    pause = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        routing_verb="pause",
        control_id="unit-pause",
        write=False,
    )
    cancel = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        routing_verb="cancel",
        control_id="unit-cancel",
        write=False,
    )
    resume = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        routing_verb="resume",
        control_id="unit-resume",
        write=False,
    )

    assert pause["validation"]["passed"] is True
    assert pause["signal_payload"]["pause_requested"] is True
    assert cancel["validation"]["passed"] is True
    assert cancel["signal_payload"]["cancel_requested"] is True
    assert resume["validation"]["passed"] is True
    assert resume["signal_payload"]["resume_requested"] is True


def test_cli_invokes_333_task_transaction_control(tmp_path: Path, capsys) -> None:
    runtime = tmp_path / "runtime"
    _seed_current_index(runtime)

    exit_code = cli_main(
        [
            "333-task-transaction-control",
            "--runtime-root",
            str(runtime),
            "--repo-root",
            str(tmp_path / "repo"),
            "--routing-verb",
            "return_to_main_tree",
            "--assignment-dag-node-id",
            "mainline-next",
            "--control-id",
            "unit-return-mainline",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["routing_verb"] == "return_to_mainline"
    assert output["signal_payload"]["continue_same_task_signal"]["assignment_dag_node_id"] == (
        "mainline-next"
    )
    assert output["validation"]["passed"] is True
