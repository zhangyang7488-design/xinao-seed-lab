import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT
    / "services"
    / "agent_runtime"
    / "codex_native_provider_scheduler_phase4.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("phase4", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_scheduler_registers_codex_native_default_and_dp_aux(tmp_path, monkeypatch) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    phase3_latest = runtime / "state" / module.PHASE3_TASK_ID / "latest.json"
    phase3_latest.parent.mkdir(parents=True, exist_ok=True)
    phase3_latest.write_text(
        json.dumps(
            {
                "phase1_payload_summary": {
                    "draft_count": 5,
                    "staged_count": 5,
                    "merged_count": 1,
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "codex_version",
        lambda runtime_root, cwd: {
            "installed": True,
            "path": "codex",
            "version": "codex-cli 0.142.3",
        },
    )
    monkeypatch.setattr(
        module,
        "module_available",
        lambda name: name in {"openai_codex", "agents", "litellm", "temporalio", "openai"},
    )
    monkeypatch.setattr(
        module,
        "qwen_secret_status",
        lambda runtime_root: {
            "api_key_available": True,
            "api_key_source_label": "runtime_private_config:qwen_key_txt_path",
            "named_blocker": "",
            "env_vars": ["DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"],
        },
    )

    payload = module.run_provider_scheduler(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase4-test-wave-001",
        invoke_codex_exec=False,
        invoke_qwen=False,
        write=True,
    )

    providers = {
        item["provider_id"]: item for item in payload["provider_registry"]["providers"]
    }
    assert payload["validation"]["passed"] is True
    assert payload["codex_native_default_primary"] is True
    assert providers["codex_exec"]["default"] == "on"
    assert providers["codex_exec"]["status"] == "ready"
    assert providers["codex_sdk"]["status"] == "ready"
    assert providers["codex_mcp_agents"]["status"] == "ready"
    assert providers["qwen_dashscope"]["status"] == "ready"
    assert providers["qwen_prepaid_cheap_worker"]["default"] == "on_first_for_cheap_work"
    assert providers["qwen_prepaid_cheap_worker"]["outputs_to_staging_only"] is True
    assert providers["deepseek_dp"]["not_primary_code_executor"] is True
    assert payload["scheduler_decision"]["active_primary_executor_pool"] == [
        "codex_exec",
        "codex_sdk",
    ]
    assert payload["scheduler_decision"]["active_prepaid_cheap_pool"] == ["qwen_prepaid_cheap_worker"]
    assert payload["scheduler_decision"]["active_aux_draft_pool"] == [
        "qwen_prepaid_cheap_worker",
        "deepseek_dp",
    ]
    assert payload["scheduler_decision"]["route_policy"]["draft_extraction_classify_eval"][0] == "qwen_prepaid_cheap_worker"
    assert payload["model_gateway"]["status"] == "model_gateway_ready"
    assert payload["draft_staging"]["staged_count"] >= 5
    assert payload["merge_consumer"]["merged_count"] == 1

    latest = runtime / "state" / module.TASK_ID / "latest.json"
    manifest = runtime / "capabilities" / "codex_s.provider_scheduler" / "manifest.json"
    readback = runtime / "readback" / "zh" / f"{module.TASK_ID}.md"
    assert latest.is_file()
    assert manifest.is_file()
    assert "现在能 invoke 什么" in readback.read_text(encoding="utf-8")


def test_missing_dp_remains_named_blocker_not_fake_success(tmp_path, monkeypatch) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    monkeypatch.setattr(
        module,
        "codex_version",
        lambda runtime_root, cwd: {
            "installed": True,
            "path": "codex",
            "version": "codex-cli 0.142.3",
        },
    )
    monkeypatch.setattr(
        module,
        "module_available",
        lambda name: name in {"openai_codex", "agents", "litellm", "temporalio", "openai"},
    )
    monkeypatch.setattr(
        module,
        "qwen_secret_status",
        lambda runtime_root: {
            "api_key_available": True,
            "api_key_source_label": "runtime_private_config:qwen_key_txt_path",
            "named_blocker": "",
            "env_vars": ["DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"],
        },
    )

    payload = module.run_provider_scheduler(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase4-dp-blocked-wave-001",
        invoke_codex_exec=False,
        invoke_qwen=False,
        write=True,
    )

    providers = {
        item["provider_id"]: item for item in payload["provider_registry"]["providers"]
    }
    assert providers["deepseek_dp"]["status"] == "blocked"
    assert providers["deepseek_dp"]["named_blocker"] == "DP_DRAFT_POOL_NOT_RUNNING"
    assert "DP_DRAFT_POOL_NOT_RUNNING" in payload["named_blockers"]
    assert payload["validation"]["checks"]["dp_aux_not_primary"] is True
    assert payload["validation"]["checks"]["qwen_prepaid_default_first_for_cheap_work"] is True
    assert payload["status"] == "codex_native_provider_scheduler_ready_with_named_blockers"
