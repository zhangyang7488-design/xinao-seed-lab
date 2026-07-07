import importlib.util
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "codex_s_direct_worker_lane.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_s_direct_worker_lane", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_qwen_ready_state(runtime: Path) -> None:
    state = runtime / "state" / "codex_native_provider_scheduler_phase4_20260704"
    (state / "qwen_prepaid_policy").mkdir(parents=True, exist_ok=True)
    (state / "qwen_invocation").mkdir(parents=True, exist_ok=True)
    (state / "latest.json").write_text(
        json.dumps(
            {
                "status": "codex_native_provider_scheduler_ready",
                "qwen_prepaid_cheap_worker_default_first": True,
                "codex_native_default_primary": False,
                "codex_brain_only_default": True,
                "codex_bulk_worker_default_paused": True,
                "default_token_saving_worker_route": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (state / "qwen_prepaid_policy" / "latest.json").write_text(
        json.dumps(
            {
                "status": "qwen_prepaid_policy_ready",
                "models": {"cheap_default_candidates": ["qwen3.6-flash"]},
                "secret_status": {"api_key_source_label": "test:redacted"},
                "outputs_to_staging_only": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (state / "qwen_invocation" / "latest.json").write_text(
        json.dumps(
            {
                "status": "qwen_dashscope_canary_ready",
                "succeeded": True,
                "selected_model": "qwen3.6-flash",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _fake_qwen_invoker(**kwargs: Any) -> dict[str, Any]:
    runtime = Path(kwargs["runtime_root"])
    mode = str(kwargs["mode"])
    invocation_id = str(kwargs["invocation_id"])
    result_path = runtime / "fake_qwen_results" / f"{invocation_id}.{mode}.json"
    raw_path = runtime / "fake_qwen_results" / f"{invocation_id}.{mode}.raw.json"
    provider_path = runtime / "fake_qwen_results" / f"{invocation_id}.provider.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "status": "draft_ready" if mode == "draft" else "model_ready",
                "mode": mode,
                "provider_id": "qwen_prepaid_cheap_worker",
                "completion_claim_allowed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    raw_path.write_text(
        json.dumps({"usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}}),
        encoding="utf-8",
    )
    provider_payload = {
        "mode_invocation_status": "draft_ready" if mode == "draft" else "model_ready",
        "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
        "provider_invocation_performed": True,
        "model_invocation_performed": True,
        "tool_invocation_performed": False,
        "qwen_prepaid_first_required": True,
        "qwen_prepaid_first_attempted": True,
        "result_path": str(result_path),
        "raw_response_ref": str(raw_path),
        "provider_invocation_ref": str(provider_path),
        "selected_model": "qwen3.6-flash",
        "evidence_refs": {"latest": str(runtime / "fake_qwen_results" / "latest.json")},
        "named_blocker": "",
    }
    return {
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "result_path": str(result_path),
            "provider_invocation_ref": str(provider_path),
            "provider_latest_ref": provider_payload["evidence_refs"]["latest"],
        },
    }


def _fake_dp_invoker(**kwargs: Any) -> dict[str, Any]:
    runtime = Path(kwargs["runtime_root"])
    mode = str(kwargs["mode"])
    invocation_id = str(kwargs["invocation_id"])
    result_path = runtime / "fake_dp_results" / f"{invocation_id}.{mode}.json"
    raw_path = runtime / "fake_dp_results" / f"{invocation_id}.{mode}.raw.json"
    provider_path = runtime / "fake_dp_results" / f"{invocation_id}.provider.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "status": "draft_ready" if mode == "draft" else "model_ready",
                "mode": mode,
                "provider_id": "legacy.deepseek_dp_sidecar",
                "completion_claim_allowed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    raw_path.write_text(
        json.dumps({"usage": {"prompt_tokens": 8, "completion_tokens": 11, "total_tokens": 19}}),
        encoding="utf-8",
    )
    provider_payload = {
        "mode_invocation_status": "draft_ready" if mode == "draft" else "model_ready",
        "selected_carrier_provider_id": "legacy.deepseek_dp_sidecar",
        "provider_invocation_performed": True,
        "model_invocation_performed": True,
        "tool_invocation_performed": False,
        "result_path": str(result_path),
        "raw_response_ref": str(raw_path),
        "provider_invocation_ref": str(provider_path),
        "evidence_refs": {"latest": str(runtime / "fake_dp_results" / "latest.json")},
        "named_blocker": "",
    }
    return {
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "result_path": str(result_path),
            "provider_invocation_ref": str(provider_path),
            "provider_latest_ref": provider_payload["evidence_refs"]["latest"],
        },
    }


def test_qwen_direct_lane_reinvokes_s_venv_when_started_from_wrong_python() -> None:
    module = _load_module()

    assert module.should_reinvoke_s_venv_for_qwen(
        provider="qwen",
        mode="extraction",
        repo=REPO_ROOT,
        qwen_invoker_provided=False,
        carrier={
            "expected_python_exists": True,
            "using_expected_python": False,
            "expected_python": str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
        },
    ) is True
    assert module.should_reinvoke_s_venv_for_qwen(
        provider="qwen",
        mode="audit",
        repo=REPO_ROOT,
        qwen_invoker_provided=False,
        carrier={"expected_python_exists": True, "using_expected_python": False},
    ) is False
    assert module.should_reinvoke_s_venv_for_qwen(
        provider="qwen",
        mode="draft",
        repo=REPO_ROOT,
        qwen_invoker_provided=True,
        carrier={"expected_python_exists": True, "using_expected_python": False},
    ) is False


def test_direct_worker_lane_auto_uses_qwen_first_and_marks_not_mainline(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _write_qwen_ready_state(runtime)

    payload = module.invoke_direct_worker_lane(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="direct-lane-qwen-test-wave",
        lane_id="direct-lane-qwen-test-wave-draft-01",
        mode="draft",
        provider="auto",
        objective="draft with cheap worker",
        input_text="test input",
        write=True,
        dp_invoker=_fake_dp_invoker,
        qwen_invoker=_fake_qwen_invoker,
    )

    assert payload["validation"]["passed"] is True
    assert payload["status"] == "direct_worker_lane_ready"
    assert payload["direct_worker_lane"] is True
    assert payload["not_333_mainline"] is True
    assert payload["completion_claim_allowed"] is False
    assert payload["worker_lane_result"]["selected_carrier_provider_id"] == (
        "qwen_prepaid_cheap_worker"
    )
    assert payload["worker_lane_result"]["qwen_prepaid_first_required"] is True
    assert Path(payload["evidence_refs"]["latest"]).is_file()


def test_direct_worker_lane_dp_override_uses_dp_and_keeps_completion_blocked(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    payload = module.invoke_direct_worker_lane(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="direct-lane-dp-test-wave",
        lane_id="direct-lane-dp-test-wave-audit-01",
        mode="audit",
        provider="dp",
        objective="audit with dp lane",
        input_text="test input",
        write=True,
        dp_invoker=_fake_dp_invoker,
        qwen_invoker=_fake_qwen_invoker,
    )

    assert payload["validation"]["passed"] is True
    assert payload["worker_lane_result"]["selected_carrier_provider_id"] == (
        "legacy.deepseek_dp_sidecar"
    )
    assert payload["provider_route"]["qwen_prepaid_first_required"] is False
    assert payload["not_execution_controller"] is True
    assert payload["requires_aaq_for_fact_or_next_frontier"] is True


def test_direct_qwen_override_blocks_non_cheap_mode_without_dp_fallback(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _write_qwen_ready_state(runtime)

    payload = module.invoke_direct_worker_lane(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="direct-lane-qwen-audit-test-wave",
        lane_id="direct-lane-qwen-audit-test-wave-audit-01",
        mode="audit",
        provider="qwen",
        objective="audit should not be forced onto qwen cheap worker",
        input_text="test input",
        write=True,
        dp_invoker=_fake_dp_invoker,
        qwen_invoker=_fake_qwen_invoker,
    )

    assert payload["validation"]["passed"] is False
    assert payload["status"] == "direct_worker_lane_blocked"
    assert payload["named_blocker"] == "TASK_NOT_SUITABLE_FOR_QWEN"
    assert payload["worker_lane_result"]["qwen_prepaid_first_attempted"] is False
    assert payload["worker_lane_result"]["deepseek_dp_invocation"] is False
