import json
from pathlib import Path

from services.agent_runtime import codex_333_host_dialogue_gate_trace as module
from xinao_seedlab.cli.__main__ import main as cli_main


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_repo(repo: Path) -> Path:
    hook_script = repo / "scripts" / "hardmode" / "Invoke-CodexSUserPromptSubmitHook.ps1"
    _write_text(
        hook_script,
        "\n".join(
            [
                "human_dialogue",
                "diagnosis",
                "execution",
                "watch",
                "Invoke-CodexSMetaMinutePreflight.ps1",
            ]
        ),
    )
    _write_text(
        repo / "src" / "xinao_seedlab" / "cli" / "__main__.py",
        "333-host-dialogue-gate-trace\n",
    )
    hooks_json = repo / "hooks.json"
    _write_json(
        hooks_json,
        {
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": (
                                    "powershell -File "
                                    f'"{hook_script}"'
                                ),
                            }
                        ]
                    }
                ]
            }
        },
    )
    return hooks_json


def _seed_runtime(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "clean_dialogue_gate" / "latest.json",
        {"validation": {"passed": True}},
    )
    _write_json(
        runtime / "state" / "codex_s_user_prompt_submit_hook" / "latest.json",
        {"status": "user_prompt_submit_hook_ready"},
    )
    _write_json(
        runtime / "state" / "codex_s_token_budget_gate" / "latest.json",
        {"status": "token_budget_gate_ready"},
    )
    _write_json(
        runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json",
        {"next_required_artifact": "host_dialogue_gate_trace.v1"},
    )
    _write_json(
        runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json",
        {"provider_ids": [module.TOOL_PROVIDER_ID]},
    )


def test_host_dialogue_gate_trace_writes_samples_and_refs(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    hooks_json = _seed_repo(repo)
    _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        hooks_json=hooks_json,
        write=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["status"] == "host_dialogue_gate_trace_ready"
    assert payload["validation"]["checks"]["sample_classes_match"] is True
    assert payload["validation"]["checks"]["human_dialogue_no_hot_path_policy"] is True
    assert payload["validation"]["checks"]["cli_entrypoint_registered"] is True
    assert payload["tool_registry"]["provider_visible"] is True
    classes = {item["sample_id"]: item["message_class"] for item in payload["sample_traces"]}
    assert classes == {
        "human_dialogue": "human_dialogue",
        "execution": "execution",
        "watch": "watch",
    }
    assert Path(payload["output_paths"]["latest"]).is_file()
    assert Path(payload["output_paths"]["readback"]).is_file()


def test_cli_invokes_host_dialogue_gate_trace(tmp_path: Path, capsys) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    hooks_json = _seed_repo(repo)
    _seed_runtime(runtime)

    exit_code = cli_main(
        [
            "333-host-dialogue-gate-trace",
            "--runtime-root",
            str(runtime),
            "--repo-root",
            str(repo),
            "--hooks-json",
            str(hooks_json),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["validation"]["passed"] is True
    assert output["cli"]["registered"] is True
