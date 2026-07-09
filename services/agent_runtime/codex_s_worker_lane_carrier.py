"""Thin worker lane carrier — mature seams only (not phase1 handroll)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import (
    DEFAULT_REPO,
    DEFAULT_RUNTIME,
    now_iso,
    write_json,
)
from services.agent_runtime.pro_review_after_draft import invoke_pro_review_via_gateway
from services.agent_runtime.routing_policy_reader import PRO_REVIEW_ROUTE_ROLE, pro_review_model
from services.agent_runtime.thin_provider_client import (
    DEFAULT_BASE_URL,
    chat_completion,
    probe_gateway,
)

SCHEMA_VERSION = "xinao.codex_s.worker_lane_carrier.thin.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_WORKER_LANE_CARRIER_THIN_V1"
TASK_ID = "codex_s_worker_lane_carrier_20260708"

MODE_ORDER = (
    "draft",
    "eval",
    "contradiction",
    "audit",
    "extraction",
    "citation_verify",
    "search",
    "provider_probe",
)
SUCCESS_STATUSES = {"draft_ready", "model_ready", "search_ready", "provider_probe_ready"}

QWEN_CHEAP_WORKER_PROVIDER_ID = "qwen_prepaid_cheap_worker"
DEEPSEEK_DP_PROVIDER_ID = "legacy.deepseek_dp_sidecar"
DEEPSEEK_DP_ROUTE_ID = "deepseek_dp"
CODEX_EXEC_PROVIDER_ID = "codex_exec"
CHEAP_QWEN_FIRST_MODES = {"draft", "extraction", "eval"}
QWEN_FIRST_APPLIES_ONLY_TO = "cheap_worker_lane"
QWEN_FIRST_MUST_NOT_OVERRIDE_LANES = [
    "quality_escalation_lane",
    "hard_reasoning_lane",
    "engineering_executor_lane",
    "final_merge_lane",
]
QWEN_FALLBACK_ALLOWED_REASONS = {
    "LOCAL_OLLAMA_QWEN_NOT_READY",
    "LOCAL_OLLAMA_QWEN_INVOKE_FAILED",
    "LOCAL_OLLAMA_QWEN_TIMEOUT",
    "TASK_NOT_SUITABLE_FOR_LOCAL_OLLAMA",
    "QWEN_RATE_LIMIT",
    "QWEN_AUTH_FAILED",
    "QWEN_QUALITY_BLOCKER",
    "TASK_NOT_SUITABLE_FOR_QWEN",
    "QWEN_NOT_READY",
    "QWEN_TRANSIENT_OR_ENDPOINT_FAILED",
    "QWEN_WORKER_POOL_INVOKER_NOT_ROUTED",
    "QWEN_WORKER_POOL_WRONG_PYTHON_CARRIER",
    "PROVIDER_GATEWAY_UNREACHABLE",
    "PROVIDER_GATEWAY_AUTH_OR_UPSTREAM",
}
DP_FALLBACK_ALLOWED_REASONS = {
    "DEEPSEEK_AUTH_FAILED",
    "DEEPSEEK_RATE_LIMIT",
    "DEEPSEEK_TIMEOUT",
    "DEEPSEEK_ENDPOINT_UNAVAILABLE",
    "DEEPSEEK_ENDPOINT_TRANSIENT_HTTP_ERROR",
    "DEEPSEEK_PROVIDER_NOT_CONFIGURED",
    "DEEPSEEK_MODEL_INVOCATION_FAILED",
    "DEEPSEEK_EMPTY_MODEL_RESPONSE",
    "DP_WORKER_POOL_INVOKE_FAILED",
}
EXTERNAL_DRAFT_PROVIDER_IDS = {DEEPSEEK_DP_PROVIDER_ID, QWEN_CHEAP_WORKER_PROVIDER_ID}
LOCAL_STUB_PROVIDER_PREFIXES = ("seed_cortex.local_",)
PROVIDER_SCHEDULER_TASK_ID = "codex_native_provider_scheduler_phase4_20260704"

DpInvoker = Callable[..., dict[str, Any]]
QwenInvoker = Callable[..., dict[str, Any]]


def safe_stem(value: str, *, limit: int = 96) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-_.")
    cleaned = cleaned or "default"
    if len(cleaned) <= limit:
        return cleaned
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{cleaned[: limit - 13].strip('-_.') or 'default'}-{digest}"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def s_venv_python(repo: Path = DEFAULT_REPO) -> Path:
    return repo / ".venv" / "Scripts" / "python.exe"


def python_carrier_status(repo: Path = DEFAULT_REPO) -> dict[str, Any]:
    expected = s_venv_python(repo)
    current = Path(sys.executable)

    def norm(path: Path) -> str:
        return os.path.normcase(os.path.abspath(str(path)))

    expected_exists = expected.is_file()
    using_expected = expected_exists and norm(current) == norm(expected)
    return {
        "schema_version": "xinao.codex_s.python_carrier.v1",
        "status": "s_venv_carrier_ready" if using_expected else "s_venv_carrier_not_used",
        "expected_python": str(expected),
        "current_python": str(current),
        "expected_python_exists": expected_exists,
        "using_expected_python": using_expected,
        "system_python_environment_blocker_only": expected_exists and not using_expected,
        "provider_readiness_fact_allowed": using_expected or not expected_exists,
    }


def wave_digest_stem(wave_id: str) -> str:
    return f"mdwp-{hashlib.sha256(wave_id.encode('utf-8')).hexdigest()[:16]}"


def provider_scheduler_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / PROVIDER_SCHEDULER_TASK_ID
    return {
        "state": state,
        "latest": state / "latest.json",
        "qwen_prepaid_policy": state / "qwen_prepaid_policy" / "latest.json",
        "qwen_invocation": state / "qwen_invocation" / "latest.json",
    }


def load_provider_route_context(runtime: Path) -> dict[str, Any]:
    paths = provider_scheduler_paths(runtime)
    thin_latest = read_json(runtime / "state" / "thin_glue_provider" / "latest.json")
    latest = read_json(paths["latest"]) or thin_latest
    qwen_policy = read_json(paths["qwen_prepaid_policy"])
    qwen_invocation = read_json(paths["qwen_invocation"])
    gateway_url = os.environ.get("XINAO_PROVIDER_BASE_URL", DEFAULT_BASE_URL)
    probe = probe_gateway(base_url=gateway_url)
    gateway_ok = probe.get("ok") is True
    qwen_ready = gateway_ok or (
        qwen_policy.get("status") == "qwen_prepaid_policy_ready"
        and (
            qwen_invocation.get("status") == "qwen_dashscope_canary_ready"
            or qwen_invocation.get("succeeded") is True
        )
    )
    cheap_models = (
        qwen_policy.get("models", {}).get("cheap_default_candidates")
        if isinstance(qwen_policy.get("models"), dict)
        else []
    )
    selected_model = str(
        qwen_invocation.get("selected_model")
        or (cheap_models[0] if isinstance(cheap_models, list) and cheap_models else "")
        or "qwen3.6-flash"
    )
    return {
        "runtime_root": str(runtime),
        "provider_scheduler_task_id": PROVIDER_SCHEDULER_TASK_ID,
        "provider_scheduler_latest_ref": str(paths["latest"]),
        "qwen_prepaid_policy_ref": str(paths["qwen_prepaid_policy"]),
        "qwen_invocation_ref": str(paths["qwen_invocation"]),
        "qwen_prepaid_policy_status": str(qwen_policy.get("status") or ""),
        "qwen_invocation_status": str(qwen_invocation.get("status") or ""),
        "qwen_prepaid_cheap_worker_ready": qwen_ready,
        "qwen_prepaid_cheap_worker_default_first": gateway_ok or qwen_ready,
        "qwen_selected_model": selected_model,
        "qwen_api_key_source_label": str(
            qwen_policy.get("secret_status", {}).get("api_key_source_label")
            if isinstance(qwen_policy.get("secret_status"), dict)
            else ("thin_glue_gateway" if gateway_ok else "")
        ),
        "gateway_probe": probe,
        "gateway_base_url": gateway_url,
        "routing_contract": qwen_policy.get("routing_contract", {}),
        "fallback_allowed_reasons": sorted(QWEN_FALLBACK_ALLOWED_REASONS),
        "outputs_to_staging_only": True,
        "direct_repo_write_allowed": False,
        "refs": {key: str(path) for key, path in paths.items()},
        "not_completion_boundary": True,
        "thin_carrier": True,
    }


def provider_route_for_mode(mode: str, context: dict[str, Any]) -> dict[str, Any]:
    qwen_ready = context.get("qwen_prepaid_cheap_worker_ready") is True
    cheap_mode = mode in CHEAP_QWEN_FIRST_MODES
    if cheap_mode and qwen_ready:
        return {
            "route_class": "cheap_draft_extract_eval",
            "lane_kind": "provider_gateway_cheap_worker",
            "provider_role": "CheapWorkerProvider",
            "preferred_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
            "preferred_provider_label": "Qwen prepaid cheap worker",
            "preferred_model": context.get("qwen_selected_model") or "qwen3.6-flash",
            "fallback_provider_ids": [DEEPSEEK_DP_PROVIDER_ID, CODEX_EXEC_PROVIDER_ID],
            "qwen_prepaid_first_required": True,
            "qwen_prepaid_first_reason": "thin_carrier: gateway/qwen cheap first for draft/extract/eval",
            "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
            "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
            "fallback_allowed_reasons": sorted(QWEN_FALLBACK_ALLOWED_REASONS),
            "outputs_to_staging_only": True,
            "direct_repo_write_allowed": False,
        }
    if cheap_mode:
        return {
            "route_class": "cheap_draft_extract_eval",
            "lane_kind": "dp_sidecar_execution",
            "provider_role": "CheapWorkerProvider",
            "preferred_provider_id": DEEPSEEK_DP_PROVIDER_ID,
            "preferred_provider_label": "DeepSeek/DP sidecar",
            "fallback_provider_ids": [CODEX_EXEC_PROVIDER_ID],
            "qwen_prepaid_first_required": False,
            "qwen_prepaid_first_reason": "QWEN_NOT_READY",
            "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
            "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
            "fallback_allowed_reasons": sorted(QWEN_FALLBACK_ALLOWED_REASONS),
            "outputs_to_staging_only": True,
            "direct_repo_write_allowed": False,
        }
    if mode in {"contradiction", "audit"}:
        route_class = "pro_review_after_draft"
        fallback = [CODEX_EXEC_PROVIDER_ID]
    elif mode == "citation_verify":
        route_class = "citation_verify_support"
        fallback = [QWEN_CHEAP_WORKER_PROVIDER_ID, CODEX_EXEC_PROVIDER_ID]
    else:
        route_class = "support_worker"
        fallback = [CODEX_EXEC_PROVIDER_ID]
    preferred_model = ""
    if route_class == "pro_review_after_draft":
        preferred_model = pro_review_model(runtime_root=context.get("runtime_root") or DEFAULT_RUNTIME)
    return {
        "route_class": route_class,
        "lane_kind": "dp_sidecar_execution",
        "provider_role": "ProReviewProvider" if route_class == "pro_review_after_draft" else "CheapWorkerProvider",
        "route_role": PRO_REVIEW_ROUTE_ROLE if route_class == "pro_review_after_draft" else "",
        "preferred_provider_id": DEEPSEEK_DP_PROVIDER_ID,
        "preferred_provider_label": "DeepSeek V4 Pro review" if route_class == "pro_review_after_draft" else "DeepSeek/DP sidecar",
        "preferred_model": preferred_model,
        "fallback_provider_ids": fallback,
        "qwen_prepaid_first_required": False,
        "qwen_prepaid_first_reason": "mode_not_qwen_cheap_first",
        "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
        "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
        "fallback_allowed_reasons": sorted(
            DP_FALLBACK_ALLOWED_REASONS if route_class == "pro_review_after_draft" else QWEN_FALLBACK_ALLOWED_REASONS
        ),
        "outputs_to_staging_only": True,
        "direct_repo_write_allowed": False,
    }


def classify_qwen_blocker(value: Any) -> str:
    text = str(value or "")
    upper = text.upper()
    if not text:
        return "QWEN_WORKER_POOL_INVOKE_FAILED"
    if "429" in upper or "RATE" in upper or "LIMIT" in upper:
        return "QWEN_RATE_LIMIT"
    if "401" in upper or "403" in upper or "AUTH" in upper or "API_KEY" in upper:
        return "QWEN_AUTH_FAILED"
    if any(
        token in upper
        for token in (
            "TIMEOUT",
            "ENDPOINT",
            "UNAVAILABLE",
            "GATEWAY",
            "UNREACHABLE",
            "REFUSED",
            "10061",
            "502",
            "503",
            "504",
        )
    ):
        return "QWEN_TRANSIENT_OR_ENDPOINT_FAILED"
    if "NOT_SUITABLE" in upper:
        return "TASK_NOT_SUITABLE_FOR_QWEN"
    if "NOT_READY" in upper or "UNREACHABLE" in upper:
        return "QWEN_NOT_READY"
    return text if upper.startswith("QWEN_") or upper.startswith("PROVIDER_") else "QWEN_WORKER_POOL_INVOKE_FAILED"


def classify_dp_blocker(value: Any) -> str:
    text = str(value or "")
    upper = text.upper()
    if not text:
        return "DP_WORKER_POOL_INVOKE_FAILED"
    if "429" in upper or "RATE" in upper:
        return "DEEPSEEK_RATE_LIMIT"
    if "401" in upper or "403" in upper or "AUTH" in upper or "NOT_CONFIGURED" in upper:
        return "DEEPSEEK_PROVIDER_NOT_CONFIGURED"
    if "TIMEOUT" in upper:
        return "DEEPSEEK_TIMEOUT"
    if any(token in upper for token in ("ENDPOINT", "UNAVAILABLE", "502", "503", "504")):
        return "DEEPSEEK_ENDPOINT_UNAVAILABLE"
    return text if upper.startswith("DEEPSEEK_") or upper.startswith("DP_") else "DP_WORKER_POOL_INVOKE_FAILED"


def qwen_mode_status(mode: str) -> str:
    return "draft_ready" if mode == "draft" else "model_ready"


def provider_payload_succeeded(payload: dict[str, Any]) -> bool:
    status = str(payload.get("mode_invocation_status") or "")
    if status in SUCCESS_STATUSES and payload.get("provider_invocation_performed") is True:
        return True
    if status == "provider_probe_ready" and not payload.get("named_blocker"):
        return True
    return False


def _qwen_state_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "codex_s_direct_worker_lane" / "qwen_worker_invocation"
    return {
        "state": state,
        "records": state / "records",
        "latest": state / "latest.json",
        "artifacts": state / "artifacts",
        "raw": state / "raw",
    }


def invoke_qwen_cheap_worker_lane(
    *,
    runtime_root: str | Path,
    task_id: str,
    request_id: str,
    invocation_id: str,
    episode_id: str,
    mode: str,
    objective: str,
    input_text: str,
    max_results: int = 5,
    write: bool = True,
) -> dict[str, Any]:
    del episode_id, max_results
    runtime = Path(runtime_root)
    paths = _qwen_state_paths(runtime)
    record_path = paths["records"] / f"{safe_stem(invocation_id)}.json"
    latest_path = paths["latest"]
    artifact_path = paths["artifacts"] / f"{safe_stem(invocation_id)}.{mode}.json"
    raw_response_path = paths["raw"] / f"{safe_stem(invocation_id)}.raw.json"
    route_context = load_provider_route_context(runtime)
    selected_model = str(route_context.get("qwen_selected_model") or "qwen3.6-flash")
    gateway_url = str(route_context.get("gateway_base_url") or DEFAULT_BASE_URL)
    base_payload: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.qwen_cheap_worker_lane.v1",
        "provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
        "task_id": task_id,
        "request_id": request_id,
        "invocation_id": invocation_id,
        "mode": mode,
        "objective": objective,
        "qwen_prepaid_first_attempted": True,
        "qwen_prepaid_first_required": mode in CHEAP_QWEN_FIRST_MODES,
        "selected_model": selected_model,
        "gateway_base_url": gateway_url,
        "thin_carrier": True,
        "outputs_to_staging_only": True,
        "direct_repo_write_allowed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if mode not in CHEAP_QWEN_FIRST_MODES:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "named_blocker": "TASK_NOT_SUITABLE_FOR_QWEN",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner

    carrier = python_carrier_status(DEFAULT_REPO)
    if carrier.get("provider_readiness_fact_allowed") is not True:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
            "named_blocker": "QWEN_WORKER_POOL_WRONG_PYTHON_CARRIER",
            "python_carrier": carrier,
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner

    system_prompt = (
        "You are Qwen cheap worker for Codex S direct lane. Produce bounded "
        "draft/extraction/eval support only. No completion claims."
    )
    user_prompt = "\n".join(
        [
            f"mode={mode}",
            f"objective={objective}",
            "Return concise Markdown with actionable bullets.",
            "",
            input_text[:12000],
        ]
    )
    completion = chat_completion(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=selected_model,
        base_url=gateway_url,
        timeout_s=90.0,
    )
    if completion.get("ok") is not True:
        blocker = classify_qwen_blocker(
            completion.get("named_blocker") or completion.get("error") or "QWEN_NOT_READY"
        )
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "named_blocker": blocker,
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner

    response_body = completion.get("response") if isinstance(completion.get("response"), dict) else {}
    choices = response_body.get("choices") if isinstance(response_body.get("choices"), list) else []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    content = str(message.get("content") or "") if isinstance(message, dict) else ""
    usage = response_body.get("usage") if isinstance(response_body.get("usage"), dict) else {}
    if write:
        write_json(raw_response_path, {"response": response_body, "usage": usage})
    if not content.strip():
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
            "provider_invocation_performed": True,
            "model_invocation_performed": False,
            "named_blocker": "QWEN_EMPTY_MODEL_RESPONSE",
            "raw_response_ref": str(raw_response_path),
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner

    artifact = {
        "schema_version": f"{SCHEMA_VERSION}.qwen_cheap_worker_artifact.v1",
        "provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
        "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
        "model": selected_model,
        "mode": mode,
        "objective": objective,
        "content": content,
        "thin_carrier": True,
        "completion_claim_allowed": False,
        "generated_at": now_iso(),
    }
    if write:
        write_json(artifact_path, artifact)
    provider_payload = {
        **base_payload,
        "mode_invocation_status": qwen_mode_status(mode),
        "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
        "provider_invocation_performed": True,
        "model_invocation_performed": True,
        "tool_invocation_performed": False,
        "result_path": str(artifact_path),
        "raw_response_ref": str(raw_response_path),
        "provider_invocation_ref": str(record_path),
        "evidence_refs": {
            "latest": str(latest_path),
            "record_path": str(record_path),
            "result_path": str(artifact_path),
        },
        "named_blocker": "",
        "usage": usage,
    }
    runner = {
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "result_path": str(artifact_path),
            "provider_invocation_ref": str(record_path),
        },
    }
    if write:
        write_json(record_path, runner)
        write_json(latest_path, runner)
    return runner


def default_dp_invoker() -> DpInvoker:
    from services.agent_runtime.dp_sidecar_execution_port import invoke_dp_sidecar_execution_port

    return invoke_dp_sidecar_execution_port


def default_qwen_invoker() -> QwenInvoker:
    return invoke_qwen_cheap_worker_lane


def _normalize_dp_runner(runner: dict[str, Any]) -> dict[str, Any]:
    provider_payload = runner.get("provider_payload")
    if isinstance(provider_payload, dict) and provider_payload:
        return runner
    nested = runner.get("provider_payload", {}).get("provider_payload")
    if isinstance(nested, dict):
        return {"provider_payload": nested, "actual_dispatch_refs": runner.get("actual_dispatch_refs", {})}
    service_payload = runner.get("provider_payload")
    if isinstance(service_payload, dict):
        return {"provider_payload": service_payload, "actual_dispatch_refs": runner.get("actual_dispatch_refs", {})}
    return {"provider_payload": {}, "actual_dispatch_refs": {}}


def invoke_lane_with_provider_route(
    *,
    runtime: Path,
    wave_id: str,
    brief: dict[str, Any],
    dp_invoker: DpInvoker,
    qwen_invoker: QwenInvoker,
    write: bool,
) -> dict[str, Any]:
    mode = str(brief["mode"])
    lane_id = str(brief["lane_id"])
    wave_stem = wave_digest_stem(wave_id)
    invocation_id = safe_stem(lane_id)
    route = brief.get("provider_route") if isinstance(brief.get("provider_route"), dict) else {}
    if route.get("route_class") == "pro_review_after_draft" and mode in {"audit", "contradiction"}:
        return invoke_pro_review_via_gateway(
            runtime_root=runtime,
            invocation_id=invocation_id,
            mode=mode,
            objective=str(brief["objective"]),
            input_text=str(brief["input_text"]),
            write=write,
            trigger_installed=True,
        )
    qwen_required = route.get("qwen_prepaid_first_required") is True
    common = {
        "runtime_root": runtime,
        "task_id": TASK_ID,
        "request_id": f"{wave_stem}-{mode}-request",
        "invocation_id": invocation_id,
        "episode_id": f"{TASK_ID}:{wave_stem}",
        "mode": mode,
        "objective": str(brief["objective"]),
        "input_text": str(brief["input_text"]),
        "max_results": 5,
        "write": write,
    }
    if qwen_required:
        qwen_runner = qwen_invoker(**common)
        qwen_payload = (
            qwen_runner.get("provider_payload")
            if isinstance(qwen_runner.get("provider_payload"), dict)
            else {}
        )
        qwen_status = str(qwen_payload.get("mode_invocation_status") or "")
        qwen_selected = str(qwen_payload.get("selected_carrier_provider_id") or "")
        if (
            qwen_status in SUCCESS_STATUSES
            and qwen_selected == QWEN_CHEAP_WORKER_PROVIDER_ID
            and qwen_payload.get("model_invocation_performed") is True
        ):
            return qwen_runner
        fallback_reason = classify_qwen_blocker(qwen_payload.get("named_blocker"))
        if fallback_reason in QWEN_FALLBACK_ALLOWED_REASONS:
            dp_runner = _normalize_dp_runner(dp_invoker(**common))
            provider_payload = (
                dp_runner.get("provider_payload")
                if isinstance(dp_runner.get("provider_payload"), dict)
                else {}
            )
            provider_payload.update(
                {
                    "qwen_prepaid_first_required": True,
                    "qwen_prepaid_first_attempted": True,
                    "qwen_prepaid_first_succeeded": False,
                    "fallback_from_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
                    "fallback_reason": fallback_reason,
                    "fallback_allowed": True,
                    "qwen_attempt_ref": str(qwen_payload.get("provider_invocation_ref") or ""),
                }
            )
            dp_runner["provider_payload"] = provider_payload
            dp_runner["qwen_prepaid_attempt"] = qwen_payload
            return dp_runner
        qwen_payload.update(
            {
                "fallback_allowed": False,
                "fallback_reason": fallback_reason,
                "qwen_prepaid_first_required": True,
                "qwen_prepaid_first_attempted": True,
                "qwen_prepaid_first_succeeded": False,
            }
        )
        qwen_runner["provider_payload"] = qwen_payload
        return qwen_runner
    return _normalize_dp_runner(dp_invoker(**common))


def run_lane(
    *,
    runtime: Path,
    wave_id: str,
    brief: dict[str, Any],
    dp_invoker: DpInvoker,
    qwen_invoker: QwenInvoker,
    write: bool,
    qwen_quality_invoker: QwenInvoker | None = None,
    codex_invoker: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    del qwen_quality_invoker, codex_invoker
    mode = str(brief["mode"])
    lane_id = str(brief["lane_id"])
    started_at = now_iso()
    started_perf = time.perf_counter()
    runner_payload = invoke_lane_with_provider_route(
        runtime=runtime,
        wave_id=wave_id,
        brief=brief,
        dp_invoker=dp_invoker,
        qwen_invoker=qwen_invoker,
        write=write,
    )
    latency_ms = int((time.perf_counter() - started_perf) * 1000)
    completed_at = now_iso()
    provider_payload = (
        runner_payload.get("provider_payload")
        if isinstance(runner_payload.get("provider_payload"), dict)
        else {}
    )
    dispatch_refs = (
        runner_payload.get("actual_dispatch_refs")
        if isinstance(runner_payload.get("actual_dispatch_refs"), dict)
        else {}
    )
    status = str(provider_payload.get("mode_invocation_status") or "")
    raw_response_ref = str(provider_payload.get("raw_response_ref") or "")
    raw_response_missing = bool(raw_response_ref) and not Path(raw_response_ref).is_file()
    artifact_ref = str(
        dispatch_refs.get("result_path")
        or provider_payload.get("result_path")
        or ""
    )
    selected_provider = str(
        provider_payload.get("selected_carrier_provider_id")
        or provider_payload.get("provider_id")
        or ""
    )
    named_blocker = str(provider_payload.get("named_blocker") or "")
    provider_performed = provider_payload.get("provider_invocation_performed") is True
    model_invocation_performed = provider_payload.get("model_invocation_performed") is True
    tool_invocation_performed = provider_payload.get("tool_invocation_performed") is True
    completed = status in SUCCESS_STATUSES and (provider_performed or mode == "provider_probe")
    artifact_exists = bool(artifact_ref) and Path(artifact_ref).is_file()
    observed_usage = provider_payload.get("usage") if isinstance(provider_payload.get("usage"), dict) else {}
    qwen_invocation = (
        selected_provider == QWEN_CHEAP_WORKER_PROVIDER_ID and model_invocation_performed
    )
    deepseek_dp_invocation = (
        selected_provider in {DEEPSEEK_DP_PROVIDER_ID, DEEPSEEK_DP_ROUTE_ID}
        and model_invocation_performed
    )
    external_draft_invocation = (
        mode == "draft"
        and selected_provider in EXTERNAL_DRAFT_PROVIDER_IDS
        and model_invocation_performed
    )
    local_stub = selected_provider.startswith(LOCAL_STUB_PROVIDER_PREFIXES)
    provider_route = (
        brief.get("provider_route") if isinstance(brief.get("provider_route"), dict) else {}
    )
    return {
        "lane_id": lane_id,
        "mode": mode,
        "objective": brief["objective"],
        "status": "succeeded" if completed else "blocked",
        "started_at": started_at,
        "completed_at": completed_at,
        "latency_ms": latency_ms,
        "mode_invocation_status": status,
        "selected_carrier_provider_id": selected_provider,
        "provider": selected_provider,
        "provider_invocation_performed": provider_performed,
        "model_invocation_performed": model_invocation_performed,
        "tool_invocation_performed": tool_invocation_performed,
        "qwen_prepaid_invocation": qwen_invocation,
        "deepseek_dp_invocation": deepseek_dp_invocation,
        "qwen_prepaid_first_required": provider_route.get("qwen_prepaid_first_required") is True,
        "qwen_prepaid_first_attempted": provider_payload.get("qwen_prepaid_first_attempted") is True,
        "qwen_prepaid_first_succeeded": qwen_invocation,
        "fallback_allowed": provider_payload.get("fallback_allowed") is True,
        "provider_route": provider_route,
        "external_draft_invocation": external_draft_invocation,
        "local_stub": local_stub,
        "artifact_ref": artifact_ref,
        "draft_ref": artifact_ref if mode == "draft" else "",
        "artifact_exists": artifact_exists,
        "provider_invocation_ref": str(provider_payload.get("provider_invocation_ref") or ""),
        "provider_latest_ref": str(
            provider_payload.get("evidence_refs", {}).get("latest")
            if isinstance(provider_payload.get("evidence_refs"), dict)
            else ""
        ),
        "raw_response_ref": raw_response_ref,
        "raw_response_missing": raw_response_missing,
        "usage": observed_usage,
        "named_blocker": named_blocker,
        "runner_payload_digest_sha256": sha256_json(runner_payload),
        "thin_carrier": True,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def _read_artifact_content(artifact_ref: str) -> str:
    if not artifact_ref:
        return ""
    path = Path(artifact_ref)
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    if isinstance(payload, dict):
        return str(payload.get("content") or "")
    return ""


def run_worker_lane_bus_activity(
    *,
    runtime_root: str | Path,
    workflow_id: str = "",
    mode: str = "draft",
    objective: str = "",
    input_text: str = "",
    provider: str = "auto",
    write: bool = True,
    integrated_bus_bound: bool = True,
) -> dict[str, Any]:
    """Integrated bus Temporal activity entry — thin carrier, not direct foreground lane."""
    if mode not in MODE_ORDER:
        raise ValueError(f"Unsupported integrated_bus worker lane mode: {mode}")
    runtime = Path(runtime_root)
    wave_id = workflow_id or f"integrated-bus-worker-lane-{now_iso()}"
    lane_id = f"{wave_id}-{mode}-bus"
    route_context = load_provider_route_context(runtime)
    provider_route = provider_route_for_mode(mode, route_context)
    if provider == "qwen" and mode in CHEAP_QWEN_FIRST_MODES:
        provider_route = {
            **provider_route,
            "route_class": "cheap_draft_extract_eval",
            "preferred_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
            "qwen_prepaid_first_required": True,
            "qwen_prepaid_first_reason": "integrated_bus_activity: qwen default_draft_worker_first",
        }
    brief = {
        "lane_id": lane_id,
        "mode": mode,
        "objective": objective or f"integrated_bus worker lane {mode}",
        "input_text": input_text,
        "provider_route": provider_route,
        "integrated_bus_bound": integrated_bus_bound,
        "not_333_mainline": not integrated_bus_bound,
        "completion_claim_allowed": False,
        "outputs_to_staging_only": True,
    }
    lane_result = run_lane(
        runtime=runtime,
        wave_id=wave_id,
        brief=brief,
        dp_invoker=default_dp_invoker(),
        qwen_invoker=default_qwen_invoker(),
        write=write,
    )
    artifact_ref = str(lane_result.get("artifact_ref") or "")
    draft_content = _read_artifact_content(artifact_ref)
    bus_state_dir = runtime / "state" / "integrated_bus_worker_lane"
    bus_state_dir.mkdir(parents=True, exist_ok=True)
    record_path = bus_state_dir / "records" / f"{safe_stem(lane_id)}.json"
    latest_path = bus_state_dir / "latest.json"
    bus_payload: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.integrated_bus_activity.v1",
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "integrated_bus_worker_lane_ready"
        if lane_result.get("status") == "succeeded"
        else "integrated_bus_worker_lane_blocked",
        "generated_at": now_iso(),
        "workflow_id": wave_id,
        "lane_id": lane_id,
        "mode": mode,
        "provider": provider,
        "integrated_bus_bound": integrated_bus_bound,
        "not_333_mainline": not integrated_bus_bound,
        "not_333_mainline_reason": (
            ""
            if integrated_bus_bound
            else "Worker lane invoked outside integrated_bus Temporal activity graph."
        ),
        "route_role": str(provider_route.get("route_role") or ""),
        "route_class": str(provider_route.get("route_class") or ""),
        "preferred_provider_id": str(provider_route.get("preferred_provider_id") or ""),
        "preferred_model": str(provider_route.get("preferred_model") or lane_result.get("selected_carrier_provider_id") or ""),
        "worker_lane_result": lane_result,
        "artifact_ref": artifact_ref,
        "draft_content_chars": len(draft_content),
        "model_invocation_performed": lane_result.get("model_invocation_performed") is True,
        "provider_invocation_performed": lane_result.get("provider_invocation_performed") is True,
        "named_blocker": str(lane_result.get("named_blocker") or ""),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "thin_carrier": True,
        "evidence_refs": {
            "record_path": str(record_path),
            "latest": str(latest_path),
            "artifact_ref": artifact_ref,
        },
    }
    if write:
        write_json(record_path, bus_payload)
        write_json(latest_path, bus_payload)
        if integrated_bus_bound:
            direct_latest = runtime / "state" / "codex_s_direct_worker_lane" / "latest.json"
            direct_latest.parent.mkdir(parents=True, exist_ok=True)
            write_json(
                direct_latest,
                {
                    "schema_version": "xinao.codex_s.direct_worker_lane.v1",
                    "sentinel": "SENTINEL:XINAO_CODEX_S_DIRECT_WORKER_LANE",
                    "status": bus_payload["status"],
                    "generated_at": bus_payload["generated_at"],
                    "mode": mode,
                    "wave_id": wave_id,
                    "lane_id": lane_id,
                    "integrated_bus_bound": True,
                    "integrated_bus_temporal_activity": True,
                    "not_333_mainline": False,
                    "not_mainline_reason": (
                        "Worker lane invoked from integrated_bus Temporal LangGraphPlugin "
                        "activity node (qwen draft + pro review chain)."
                    ),
                    "worker_lane_result": lane_result,
                    "model_invocation_performed": lane_result.get("model_invocation_performed"),
                    "provider_invocation_performed": lane_result.get("provider_invocation_performed"),
                    "artifact_ref": artifact_ref,
                    "named_blocker": bus_payload["named_blocker"],
                    "evidence_refs": bus_payload["evidence_refs"],
                },
            )
    return {
        "worker_lane_ok": lane_result.get("status") == "succeeded"
        and lane_result.get("model_invocation_performed") is True,
        "worker_lane_status": str(lane_result.get("status") or ""),
        "worker_lane_mode": mode,
        "worker_lane_provider": str(
            lane_result.get("selected_carrier_provider_id")
            or provider_route.get("preferred_provider_id")
            or ""
        ),
        "worker_lane_model": str(provider_route.get("preferred_model") or ""),
        "worker_lane_artifact_ref": artifact_ref,
        "worker_lane_draft_content": draft_content,
        "worker_lane_named_blocker": str(lane_result.get("named_blocker") or ""),
        "worker_lane_evidence_ref": str(latest_path),
        "worker_lane_runtime_enforced": integrated_bus_bound
        and lane_result.get("model_invocation_performed") is True,
        "worker_lane_integrated_bus_bound": integrated_bus_bound,
        "adapter": "codex_s_worker_lane_carrier_integrated_bus_activity",
    }