from __future__ import annotations

import json
from pathlib import Path

from xinao_seedlab.application.seed_cortex import build_default_service


def test_dp_sidecar_provider_dispatches_nonprobe_artifacts(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    service = build_default_service(runtime)

    search = service.invoke_dp_sidecar_execution_provider(
        task_id="dp-sidecar-provider-test",
        request_id="request-search",
        invocation_id="invoke-search",
        episode_id="episode-dp-sidecar-provider-test",
        mode="search",
        objective="search local source ledger for DP evidence",
        input_text="source_ledger AAQ worker ledger",
        write_runtime=True,
    )
    assert search["mode_invocation_status"] == "search_ready"
    assert search["mode_dispatch_attempted"] is True
    assert search["provider_invocation_performed"] is True
    assert search["tool_invocation_performed"] is True
    assert search["model_invocation_performed"] is False
    assert search["selected_carrier_provider_id"] == "seed_cortex.local_source_ledger_search"
    assert search["source_provider_invocation"]["result_count"] >= 1
    assert search["source_provider_invocation"]["query_normalization"]["normalized"] is True
    assert Path(search["result_path"]).is_file()
    assert search["completion_claim_allowed"] is False

    draft = service.invoke_dp_sidecar_execution_provider(
        task_id="dp-sidecar-provider-test",
        request_id="request-draft",
        invocation_id="invoke-draft",
        episode_id="episode-dp-sidecar-provider-test",
        mode="draft",
        objective="produce local bounded draft evidence",
        input_text="write_targets=src/xinao_seedlab/application/seed_cortex.py",
        write_runtime=True,
    )
    assert draft["mode_invocation_status"] == "draft_ready"
    assert draft["mode_dispatch_attempted"] is True
    assert draft["provider_invocation_performed"] is True
    assert draft["selected_carrier_provider_id"] in {
        "legacy.deepseek_dp_sidecar",
        "seed_cortex.local_draft_artifact_provider",
    }
    assert Path(draft["result_path"]).is_file()
    assert draft["named_blocker"] == ""
    assert draft["completion_claim_allowed"] is False

    eval_payload = service.invoke_dp_sidecar_execution_provider(
        task_id="dp-sidecar-provider-test",
        request_id="request-eval",
        invocation_id="invoke-eval",
        episode_id="episode-dp-sidecar-provider-test",
        mode="eval",
        objective="evaluate DP dispatch artifact readiness",
        input_text="DP sidecar non-probe lanes must not use provider_probe as progress.",
        write_runtime=True,
    )
    assert eval_payload["mode_invocation_status"] == "model_ready"
    assert eval_payload["mode_dispatch_attempted"] is True
    assert eval_payload["provider_invocation_performed"] is True
    assert eval_payload["tool_invocation_performed"] is True
    assert eval_payload["model_invocation_performed"] is False
    assert (
        eval_payload["selected_carrier_provider_id"] == "seed_cortex.local_eval_artifact_provider"
    )
    assert Path(eval_payload["result_path"]).is_file()
    assert eval_payload["named_blocker"] == "DEEPSEEK_PROVIDER_NOT_CONFIGURED"
    assert eval_payload["completion_claim_allowed"] is False


def test_dp_sidecar_eval_uses_real_deepseek_model_when_available(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = tmp_path / "runtime"
    service = build_default_service(runtime)

    def fake_deepseek_model(**kwargs):
        result_path = Path(kwargs["result_path"])
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_payload = {
            "status": "model_ready",
            "provider_id": "legacy.deepseek_dp_sidecar",
            "selected_model": "deepseek-chat",
            "mode": kwargs["mode"],
            "content": "DeepSeek eval artifact",
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            "completion_claim_allowed": False,
        }
        result_path.write_text(json.dumps(result_payload), encoding="utf-8")
        return {
            "ok": True,
            "status": "model_ready",
            "provider_id": "legacy.deepseek_dp_sidecar",
            "selected_model": "deepseek-chat",
            "usage": result_payload["usage"],
            "response": result_payload,
            "result_path": str(result_path),
            "api_key_source_label": "test",
            "named_blocker": "",
            "model_invocation_performed": True,
        }

    monkeypatch.setattr(service, "_invoke_deepseek_model", fake_deepseek_model)

    payload = service.invoke_dp_sidecar_execution_provider(
        task_id="dp-sidecar-provider-test",
        request_id="request-eval",
        invocation_id="invoke-eval-real",
        episode_id="episode-dp-sidecar-provider-test",
        mode="eval",
        objective="evaluate with real DP carrier",
        input_text="DP sidecar eval must be a model invocation when DeepSeek is available.",
        write_runtime=True,
    )

    assert payload["mode_invocation_status"] == "model_ready"
    assert payload["provider_invocation_performed"] is True
    assert payload["model_invocation_performed"] is True
    assert payload["tool_invocation_performed"] is False
    assert payload["selected_carrier_provider_id"] == "legacy.deepseek_dp_sidecar"
    assert payload["selected_model"] == "deepseek-chat"
    assert payload["named_blocker"] == ""
    assert payload["source_provider_invocation"]["model"] == "deepseek-chat"
    assert Path(payload["result_path"]).is_file()


def test_dp_sidecar_provider_probe_does_not_count_as_bulk_progress(tmp_path: Path) -> None:
    service = build_default_service(tmp_path / "runtime")

    payload = service.invoke_dp_sidecar_execution_provider(
        task_id="dp-sidecar-provider-test",
        request_id="request-probe",
        invocation_id="invoke-probe",
        episode_id="episode-dp-sidecar-provider-test",
        mode="provider_probe",
        objective="probe only",
        input_text="probe",
        write_runtime=True,
    )

    assert payload["mode_invocation_status"] == "provider_probe_ready"
    assert payload["mode_dispatch_attempted"] is False
    assert payload["provider_invocation_performed"] is False
    assert Path(payload["result_path"]).is_file()
    assert payload["completion_claim_allowed"] is False
