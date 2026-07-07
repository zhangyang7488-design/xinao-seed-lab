import json
from pathlib import Path

from services.agent_runtime import codex_333_control_vs_evidence_boundary_contract as module

from xinao_seedlab.cli.__main__ import main as cli_main


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_repo(repo: Path) -> None:
    _write_text(
        repo / "CODEX_S_L0.md",
        "Reports, PASS, drafts, handoff text, window end, latest.json are not stop conditions.\n",
    )
    _write_text(
        repo / "docs" / "current" / "CODEX_S_CURRENT_DOCS_BOUNDARY_2026-07-02.md",
        "Latest aliases are convenient read models only.\n",
    )
    _write_text(
        repo / "src" / "xinao_seedlab" / "cli" / "__main__.py",
        "333-control-vs-evidence-boundary-contract\n",
    )


def _seed_runtime(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "current_333_run_index" / "latest.json",
        {
            "status": "current_333_run_index_ready",
            "workflow_id": "unit-workflow",
            "workflow_run_id": "unit-run",
            "temporal": {
                "port_open": True,
                "status": "Running",
                "history_length": 123,
            },
            "not_source_of_truth": True,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json",
        {
            "status": "default_main_loop_trigger_task_scoped_runtime_enforced",
            "runtime_enforced": True,
            "runtime_enforced_scope": "unit",
            "is_completion_gate": False,
            "not_execution_controller": True,
            "no_stop_wave_consumption_refs": {
                "refs_are_evidence_only": True,
                "refs_are_not_completion_gates": True,
                "refs_are_not_execution_controllers": True,
            },
        },
    )
    _write_json(
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
        {
            "status": "worker_dispatch_ledger_poll_ready",
            "poll_result_summary": {"succeeded_count": 2},
            "not_source_of_truth": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        {
            "status": "artifact_acceptance_queue_ready",
            "unique_accepted_artifact_count": 1,
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json",
        {
            "status": "s_tool_registry_ready",
            "provider_ids": [module.TOOL_PROVIDER_ID],
            "not_source_of_truth": True,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json",
        {"next_required_artifact": "control_vs_evidence_boundary_contract.v1"},
    )


def _source_files(root: Path) -> list[Path]:
    files = []
    for index in range(5):
        path = root / f"source-{index}.txt"
        _write_text(
            path,
            "\n".join(
                [
                    "应落地工件:",
                    "control_vs_evidence_boundary_contract.v1",
                    "latest.json 只做 read model",
                    "latest.json 不能触发 completion",
                    "latest.json 不能触发 dispatch",
                    "runtime_enforced 不能从 readback 晋升",
                ]
            ),
        )
        files.append(path)
    return files


def test_control_vs_evidence_boundary_contract_writes_default_read_model(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _seed_runtime(runtime)
    source_files = _source_files(tmp_path / "source")

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        source_files=source_files,
        write=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["status"] == "control_vs_evidence_boundary_contract_ready"
    assert payload["accepted_for"] == ["P0.control_vs_evidence_boundary_contract"]
    assert payload["next_required_artifact"] == "lane_lifecycle_metric_contract.v1"
    assert payload["boundary_contract"]["latest_json_role"] == (
        "disposable_read_model_projection_not_control_authority"
    )
    assert "latest_json_triggers_dispatch" in payload["boundary_contract"]["forbidden_promotions"]
    assert payload["runtime_refs"]["tool_registry"]["provider_visible"] is True
    assert payload["runtime_refs"]["default_main_loop_trigger"]["refs_are_evidence_only"] is True
    assert (
        payload["runtime_refs"]["artifact_acceptance_queue"]["direct_fact_promotion_allowed"]
        is False
    )
    assert Path(payload["output_paths"]["latest"]).is_file()
    assert Path(payload["output_paths"]["readback"]).is_file()


def test_cli_invokes_control_vs_evidence_boundary_contract(tmp_path: Path, capsys) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _seed_runtime(runtime)
    source_files = _source_files(tmp_path / "source")

    argv = [
        "333-control-vs-evidence-boundary-contract",
        "--runtime-root",
        str(runtime),
        "--repo-root",
        str(repo),
    ]
    for path in source_files:
        argv.extend(["--source-file", str(path)])

    exit_code = cli_main(argv)
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["validation"]["passed"] is True
    assert output["default_mainline_hardened"] is True
