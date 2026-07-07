import json
from pathlib import Path

from services.agent_runtime import codex_333_legacy_freeze_manifest as module

from xinao_seedlab.cli.__main__ import main as cli_main


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_repo(repo: Path) -> None:
    _write_text(
        repo / "AGENTS.md",
        "\n".join(
            [
                r"D:\XINAO_CLEAN_RUNTIME is legacy/reference-only.",
                "old `current_task_owner` is legacy/reference-only.",
            ]
        ),
    )
    _write_text(
        repo / "CODEX_S_L0.md",
        "\n".join(
            [
                "legacy_managed_hook_freeze",
                r"D:\XINAO_CLEAN_RUNTIME is not S source of truth.",
                "Never use old B hooks, old `current_task_owner`, old completion gate.",
            ]
        ),
    )
    _write_json(
        repo / "contracts" / "codex-s-workspace-boundary.v1.json",
        {
            "legacy_physical_git_root_path_ref": "reference_only_not_default",
            "archive_mother_repository_ref": "reference_only_not_default",
            "legacy_global_managed_hook_freeze": {
                "state": r"D:\XINAO_RESEARCH_RUNTIME\state\legacy_managed_hook_freeze\latest.json"
            },
            "current_task_owner_read_model_role": "derived_reference_only_unless_bound_to_seed_cortex_task",
            "old_current_task_owner_role": "legacy_reference_only_unless_bound_to_seed_cortex_task",
        },
    )
    _write_text(
        repo / "src" / "xinao_seedlab" / "cli" / "__main__.py",
        "333-legacy-freeze-manifest\n",
    )


def _seed_runtime(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "legacy_managed_hook_freeze" / "latest.json",
        {
            "schema_version": "xinao.codex_s.legacy_managed_hook_freeze.v1",
            "status": "legacy_managed_hook_frozen_fail_open",
        },
    )
    _write_json(
        runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json",
        {
            "status": "s_tool_registry_ready",
            "provider_ids": [module.TOOL_PROVIDER_ID],
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json",
        {"next_required_artifact": "legacy_freeze_manifest.v1"},
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
                    "legacy_freeze_manifest.v1",
                    "legacy_reference_only_runtime_guard.v1",
                    r"D:\XINAO_CLEAN_RUNTIME",
                    "current_task_owner",
                ]
            ),
        )
        files.append(path)
    return files


def test_legacy_freeze_manifest_writes_reference_only_guard(tmp_path: Path) -> None:
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
    assert payload["status"] == "legacy_freeze_manifest_ready"
    assert payload["reference_only_runtime_guard"]["old_completion_gate_allowed"] is False
    assert payload["reference_only_runtime_guard"]["old_current_task_owner_ambient_promotion_allowed"] is False
    assert all(item["reference_only"] is True for item in payload["legacy_entries"])
    assert all(item["default_hot_path_authority_allowed"] is False for item in payload["legacy_entries"])
    assert all(item["completion_authority_allowed"] is False for item in payload["legacy_entries"])
    assert payload["boundary_refs"]["tool_registry"]["provider_visible"] is True
    assert Path(payload["output_paths"]["latest"]).is_file()
    assert Path(payload["output_paths"]["readback"]).is_file()


def test_cli_invokes_legacy_freeze_manifest(tmp_path: Path, capsys) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _seed_runtime(runtime)
    source_files = _source_files(tmp_path / "source")

    argv = [
        "333-legacy-freeze-manifest",
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
    assert output["accepted_for"] == [
        "P0.legacy_freeze_manifest",
        "P0.legacy_reference_only_runtime_guard",
    ]
