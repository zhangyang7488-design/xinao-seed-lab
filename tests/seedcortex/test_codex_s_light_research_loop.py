import importlib.util
import json
from pathlib import Path
from typing import Any

from xinao_seedlab.application.seed_cortex import build_default_service

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "codex_s_light_research_loop.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_s_light_research_loop", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_scan(repo: Path, roots: list[str], query: str, max_results: int) -> list[dict[str, Any]]:
    return [
        {
            "path": str(repo / "services" / "agent_runtime" / "codex_s_direct_worker_lane.py"),
            "repo_relative_path": "services/agent_runtime/codex_s_direct_worker_lane.py",
            "line": 12,
            "snippet": "Direct worker lane invokes Qwen or DP staging providers.",
            "query": query,
        }
    ][:max_results]


def _runner(
    *,
    provider_id: str,
    selected_carrier_provider_id: str,
    mode: str,
    invocation_id: str,
    runtime_root: str | Path,
    model: str = "",
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    result_path = runtime / "fake_light_research" / f"{invocation_id}.{mode}.json"
    record_path = runtime / "fake_light_research" / f"{invocation_id}.record.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "status": "model_ready",
                "provider_id": provider_id,
                "selected_carrier_provider_id": selected_carrier_provider_id,
                "mode": mode,
                "completion_claim_allowed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "provider_payload": {
            "mode_invocation_status": "draft_ready" if mode == "draft" else "model_ready",
            "provider_invocation_performed": True,
            "model_invocation_performed": True,
            "tool_invocation_performed": False,
            "provider_id": provider_id,
            "selected_carrier_provider_id": selected_carrier_provider_id,
            "selected_model": model,
            "mode": mode,
            "result_path": str(result_path),
            "provider_invocation_ref": str(record_path),
            "named_blocker": "",
        }
    }


def _fake_local_invoker(**kwargs: Any) -> dict[str, Any]:
    selected_pool = str(kwargs.get("selected_pool_provider_id") or "local_ollama_qwen3")
    return _runner(
        provider_id=selected_pool,
        selected_carrier_provider_id="local_ollama_qwen",
        mode=str(kwargs["mode"]),
        invocation_id=str(kwargs["invocation_id"]),
        runtime_root=kwargs["runtime_root"],
        model=str(kwargs.get("selected_model") or ""),
    )


def _fake_qwen_invoker(**kwargs: Any) -> dict[str, Any]:
    return _runner(
        provider_id="qwen_prepaid_cheap_worker",
        selected_carrier_provider_id="qwen_prepaid_cheap_worker",
        mode=str(kwargs["mode"]),
        invocation_id=str(kwargs["invocation_id"]),
        runtime_root=kwargs["runtime_root"],
        model="qwen3.6-flash",
    )


def _fake_dp_invoker(**kwargs: Any) -> dict[str, Any]:
    provider = "legacy.deepseek_dp_sidecar"
    if kwargs["mode"] == "search":
        provider = "seed_cortex.local_source_ledger_search"
    return {
        "provider_payload": {
            "mode_invocation_status": "search_ready" if kwargs["mode"] == "search" else "model_ready",
            "provider_invocation_performed": True,
            "model_invocation_performed": kwargs["mode"] != "search",
            "tool_invocation_performed": kwargs["mode"] == "search",
            "provider_id": provider,
            "selected_carrier_provider_id": provider,
            "selected_model": "deepseek-v4-pro" if kwargs["mode"] == "audit" else "",
            "mode": str(kwargs["mode"]),
            "result_path": str(Path(kwargs["runtime_root"]) / "fake_light_research" / f"{kwargs['invocation_id']}.json"),
            "provider_invocation_ref": str(Path(kwargs["runtime_root"]) / "fake_light_research" / f"{kwargs['invocation_id']}.record.json"),
            "named_blocker": "",
        }
    }


def test_light_research_loop_fans_in_local_external_qwen_and_dp(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        mode="architecture_audit",
        wave_id="unit-light-research-architecture",
        objective="Audit light search delegation loop",
        local_query="direct_worker_lane|SourceLedger",
        source_urls=["https://docs.litellm.ai/docs/routing"],
        external_note="LiteLLM Router is a mature provider routing candidate.",
        worker_policy="cloud_allowed",
        rg_runner=_fake_scan,
        local_invoker=_fake_local_invoker,
        qwen_invoker=_fake_qwen_invoker,
        dp_invoker=_fake_dp_invoker,
        write=True,
    )

    assert payload["status"] == "light_research_loop_ready"
    assert payload["validation"]["passed"] is True
    assert payload["not_333_mainline"] is True
    assert payload["completion_claim_allowed"] is False
    assert payload["source_ledger"]["entry_count"] == 2
    assert payload["claim_cards"]["claim_card_count"] == 2
    assert payload["artifact_acceptance_queue"]["claim_card_requires_source_ledger"] is True
    provider_ids = {lane["actual_provider_id"] for lane in payload["worker_lanes"]}
    assert "local_ollama_qwen3" in provider_ids
    assert "local_ollama_deepseek_r1" in provider_ids
    assert "qwen_prepaid_cheap_worker" in provider_ids
    assert "legacy.deepseek_dp_sidecar" in provider_ids
    assert Path(payload["output_paths"]["latest"]).is_file()
    assert Path(payload["output_paths"]["manifest"]).is_file()


def test_light_research_loop_blocks_external_mode_without_external_source(tmp_path: Path) -> None:
    module = _load_module()
    payload = module.build(
        runtime_root=tmp_path / "runtime",
        repo_root=REPO_ROOT,
        mode="external_light",
        wave_id="unit-light-research-missing-external",
        objective="Missing external source should remain blocked",
        local_query="SourceLedger",
        worker_policy="skip",
        rg_runner=_fake_scan,
        write=True,
    )

    assert payload["status"] == "light_research_loop_blocked"
    assert payload["validation"]["checks"]["external_sources_bound_when_required"] is False
    assert payload["completion_claim_allowed"] is False


def test_light_research_loop_scans_absolute_local_root(tmp_path: Path) -> None:
    module = _load_module()
    external_root = tmp_path / "legacy_runtime"
    source = external_root / "action_contract.txt"
    source.parent.mkdir(parents=True)
    source.write_text(
        "result_wait keeps the user from manually polling the control plane.\n",
        encoding="utf-8",
    )

    payload = module.build(
        runtime_root=tmp_path / "runtime",
        repo_root=REPO_ROOT,
        mode="local_only",
        wave_id="unit-light-research-absolute-root",
        objective="Scan an old runtime path without copying it into the repo",
        local_query="result_wait",
        local_roots=[str(external_root)],
        worker_policy="skip",
        write=True,
    )

    assert payload["status"] == "light_research_loop_ready"
    assert payload["validation"]["passed"] is True
    assert payload["source_ledger"]["entry_count"] == 1
    entry = payload["source_ledger"]["entries"][0]
    assert entry["source_url"].startswith(f"file:{source}")
    assert entry["repo_relative_path"] == str(source.resolve())
    assert entry["accepted_for"] == "light_research_loop_local_scan"


def test_capability_gateway_exposes_light_research_loop(tmp_path: Path) -> None:
    service = build_default_service(tmp_path / "runtime", repo_root=REPO_ROOT)
    payload = service.capability_gateway_snapshot(write_runtime=True)

    assert "codex_s.light_research_loop" in payload["provider_ids"]
    provider = next(item for item in payload["providers"] if item["provider_id"] == "codex_s.light_research_loop")
    assert provider["not_333_mainline"] is True
    assert provider["completion_claim_allowed"] is False
