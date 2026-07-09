"""DeepSeek V4 Pro review node — gateway invoke after worker draft terminal (thin bind)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from services.agent_runtime.routing_policy_reader import (
    PRO_REVIEW_ROUTE_ROLE,
    load_routing_policy,
    pro_review_model,
)
from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, now_iso, write_json
from services.agent_runtime.thin_provider_client import DEFAULT_BASE_URL, chat_completion, probe_gateway

SCHEMA_VERSION = "xinao.pro_review_after_draft.v1"
SENTINEL = "SENTINEL:XINAO_PRO_REVIEW_AFTER_DRAFT_V1"
STATE_NAME = "pro_review_after_draft"
TASK_ID = "pro_review_after_draft_20260709"
PROVIDER_ID = "legacy.deepseek_dp_sidecar"
PRO_REVIEW_MODES = {"audit", "contradiction"}


def _state_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / STATE_NAME
    return {
        "state": state,
        "latest": state / "latest.json",
        "records": state / "records",
        "artifacts": state / "artifacts",
        "raw": state / "raw",
    }


def _safe_stem(value: str, *, limit: int = 96) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in str(value).strip())
    cleaned = cleaned.strip("-_.") or "default"
    if len(cleaned) <= limit:
        return cleaned
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{cleaned[: limit - 13].strip('-_.') or 'default'}-{digest}"


def _classify_blocker(value: Any) -> str:
    text = str(value or "")
    upper = text.upper()
    if not text:
        return "DEEPSEEK_PRO_REVIEW_INVOKE_FAILED"
    if "429" in upper or "RATE" in upper:
        return "DEEPSEEK_RATE_LIMIT"
    if "401" in upper or "403" in upper or "AUTH" in upper:
        return "DEEPSEEK_AUTH_FAILED"
    if any(token in upper for token in ("TIMEOUT", "UNREACHABLE", "UNAVAILABLE", "502", "503", "504")):
        return "DEEPSEEK_ENDPOINT_UNAVAILABLE"
    return text if upper.startswith("DEEPSEEK_") else "DEEPSEEK_PRO_REVIEW_INVOKE_FAILED"


def _sync_dp_sidecar_provider_evidence(
    *,
    runtime: Path,
    invocation_id: str,
    mode: str,
    objective: str,
    input_text: str,
    model: str,
    gateway_url: str,
    gateway_ok: bool,
    model_invocation_performed: bool,
    named_blocker: str,
    artifact_path: Path | None,
    raw_response_path: Path | None,
    usage: dict[str, Any],
    trigger_installed: bool,
) -> str:
    """Mirror pro-review progress into dp_sidecar_execution_provider/latest.json (honest partial)."""
    provider_state = runtime / "state" / "dp_sidecar_execution_provider"
    provider_state.mkdir(parents=True, exist_ok=True)
    latest_path = provider_state / "latest.json"
    record_path = provider_state / "records" / f"{invocation_id}.json"
    input_hash = hashlib.sha256(input_text.encode("utf-8", errors="replace")).hexdigest()
    runtime_enforced = trigger_installed and model_invocation_performed and gateway_ok
    payload: dict[str, Any] = {
        "schema_version": "xinao.seedcortex.dp_sidecar_execution_provider.v1",
        "status": "dp_sidecar_execution_provider_ready"
        if model_invocation_performed
        else "dp_sidecar_execution_provider_blocked",
        "provider_registration_status": "provider_registered",
        "mode_invocation_status": "model_ready" if model_invocation_performed else "blocked",
        "provider_id": PROVIDER_ID,
        "selected_carrier_provider_id": PROVIDER_ID if model_invocation_performed else "",
        "selected_model": model if model_invocation_performed else "",
        "port_id": "dp_sidecar_execution_port",
        "task_id": TASK_ID,
        "request_id": f"{invocation_id}-pro-review-request",
        "invocation_id": invocation_id,
        "episode_id": f"{TASK_ID}:{invocation_id}",
        "mode": mode,
        "objective": objective,
        "input_text_sha256": input_hash,
        "max_results": 5,
        "mode_dispatch_attempted": True,
        "provider_invocation_performed": model_invocation_performed or gateway_ok,
        "model_invocation_performed": model_invocation_performed,
        "tool_invocation_performed": False,
        "named_blocker": named_blocker,
        "raw_response_ref": str(raw_response_path or ""),
        "result_path": str(artifact_path or ""),
        "provider_invocation_ref": str(record_path),
        "evidence_refs": {
            "record_path": str(record_path),
            "latest": str(latest_path),
            "pro_review_latest": str(runtime / "state" / STATE_NAME / "latest.json"),
            "routing_policy": str(runtime / "agent_runtime" / "routing_policy.json"),
        },
        "fan_in_refs": {
            "artifact_acceptance_queue_required": True,
            "provider_probe_only": False,
            "provider_dispatch_artifact_required": True,
        },
        "route_role": PRO_REVIEW_ROUTE_ROLE,
        "gateway_base_url": gateway_url,
        "gateway_probe_ok": gateway_ok,
        "trigger_installed": trigger_installed,
        "runtime_enforced": runtime_enforced,
        "runtime_enforced_scope": (
            "integrated_bus_pro_review_node_gateway_invoke"
            if runtime_enforced
            else "pro_review_thin_bind_partial_not_temporal_main_loop"
        ),
        "adoption_state": (
            "runtime_enforced_for_integrated_bus_pro_review_node_partial"
            if runtime_enforced
            else "api_cli_verifier_ready_trigger_installed_partial"
        ),
        "sidecar_repo_mutation_performed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {"passed": model_invocation_performed},
        "usage": usage,
        "generated_at": now_iso(),
    }
    write_json(record_path, payload)
    write_json(latest_path, payload)
    return str(latest_path)


def invoke_pro_review_via_gateway(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    invocation_id: str = "",
    mode: str = "audit",
    objective: str = "",
    input_text: str = "",
    draft_artifact_ref: str = "",
    gateway_base_url: str | None = None,
    write: bool = True,
    trigger_installed: bool = True,
) -> dict[str, Any]:
    if mode not in PRO_REVIEW_MODES:
        raise ValueError(f"pro_review gateway supports modes {sorted(PRO_REVIEW_MODES)}; got {mode}")
    runtime = Path(runtime_root)
    paths = _state_paths(runtime)
    policy = load_routing_policy(runtime_root=runtime)
    model = pro_review_model(runtime_root=runtime)
    gateway_url = gateway_base_url or os.environ.get("XINAO_PROVIDER_BASE_URL", DEFAULT_BASE_URL)
    resolved_invocation = invocation_id or f"pro-review-{_safe_stem(objective or mode)}"
    record_path = paths["records"] / f"{_safe_stem(resolved_invocation)}.json"
    artifact_path = paths["artifacts"] / f"{_safe_stem(resolved_invocation)}.{mode}.json"
    raw_response_path = paths["raw"] / f"{_safe_stem(resolved_invocation)}.raw.json"

    probe = probe_gateway(base_url=gateway_url)
    gateway_ok = probe.get("ok") is True
    base_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "invocation_id": resolved_invocation,
        "mode": mode,
        "route_role": PRO_REVIEW_ROUTE_ROLE,
        "objective": objective,
        "provider_id": PROVIDER_ID,
        "selected_carrier_provider_id": PROVIDER_ID,
        "selected_model": model,
        "gateway_base_url": gateway_url,
        "routing_policy_ref": policy.get("policy_path"),
        "routing_policy_present": policy.get("policy_present") is True,
        "draft_artifact_ref": draft_artifact_ref,
        "trigger_installed": trigger_installed,
        "runtime_enforced": False,
        "runtime_enforced_scope": "pro_review_thin_bind_partial_not_temporal_main_loop",
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "outputs_to_staging_only": True,
        "generated_at": now_iso(),
    }

    if not gateway_ok:
        blocker = str(probe.get("named_blocker") or "PROVIDER_GATEWAY_UNREACHABLE")
        payload = {
            **base_payload,
            "status": "pro_review_blocked",
            "mode_invocation_status": "blocked",
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "named_blocker": blocker,
            "gateway_probe": probe,
            "evidence_refs": {"latest": str(paths["latest"]), "record_path": str(record_path)},
        }
        runner = {"provider_payload": payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(paths["latest"], runner)
            _sync_dp_sidecar_provider_evidence(
                runtime=runtime,
                invocation_id=resolved_invocation,
                mode=mode,
                objective=objective,
                input_text=input_text,
                model=model,
                gateway_url=gateway_url,
                gateway_ok=False,
                model_invocation_performed=False,
                named_blocker=blocker,
                artifact_path=None,
                raw_response_path=None,
                usage={},
                trigger_installed=trigger_installed,
            )
        return runner

    system_prompt = (
        "You are DeepSeek V4 Pro on the XINAO 333 mature control plane pro-review node. "
        "Audit worker draft artifacts after draft terminal. Return bounded acceptance review: "
        "findings, risks, weld recommendations, fan-in hints. No completion claims."
    )
    user_prompt = "\n".join(
        [
            f"mode={mode}",
            f"route_role={PRO_REVIEW_ROUTE_ROLE}",
            f"objective={objective}",
            f"draft_artifact_ref={draft_artifact_ref or 'inline'}",
            "required_output=concise Markdown audit with pass/partial/block recommendation",
            "",
            input_text[:24000],
        ]
    )
    completion = chat_completion(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=model,
        base_url=gateway_url,
        timeout_s=120.0,
    )
    if completion.get("ok") is not True:
        blocker = _classify_blocker(completion.get("named_blocker") or completion.get("error"))
        payload = {
            **base_payload,
            "status": "pro_review_blocked",
            "mode_invocation_status": "blocked",
            "provider_invocation_performed": True,
            "model_invocation_performed": False,
            "named_blocker": blocker,
            "gateway_probe": probe,
            "evidence_refs": {"latest": str(paths["latest"]), "record_path": str(record_path)},
        }
        runner = {"provider_payload": payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(paths["latest"], runner)
            _sync_dp_sidecar_provider_evidence(
                runtime=runtime,
                invocation_id=resolved_invocation,
                mode=mode,
                objective=objective,
                input_text=input_text,
                model=model,
                gateway_url=gateway_url,
                gateway_ok=True,
                model_invocation_performed=False,
                named_blocker=blocker,
                artifact_path=None,
                raw_response_path=None,
                usage={},
                trigger_installed=trigger_installed,
            )
        return runner

    response_body = completion.get("response") if isinstance(completion.get("response"), dict) else {}
    choices = response_body.get("choices") if isinstance(response_body.get("choices"), list) else []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    content = str(message.get("content") or "") if isinstance(message, dict) else ""
    usage = response_body.get("usage") if isinstance(response_body.get("usage"), dict) else {}
    if write:
        write_json(raw_response_path, {"response": response_body, "usage": usage})

    if not content.strip():
        blocker = "DEEPSEEK_EMPTY_MODEL_RESPONSE"
        payload = {
            **base_payload,
            "status": "pro_review_blocked",
            "mode_invocation_status": "blocked",
            "provider_invocation_performed": True,
            "model_invocation_performed": False,
            "named_blocker": blocker,
            "raw_response_ref": str(raw_response_path),
            "evidence_refs": {"latest": str(paths["latest"]), "record_path": str(record_path)},
        }
        runner = {"provider_payload": payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(paths["latest"], runner)
            _sync_dp_sidecar_provider_evidence(
                runtime=runtime,
                invocation_id=resolved_invocation,
                mode=mode,
                objective=objective,
                input_text=input_text,
                model=model,
                gateway_url=gateway_url,
                gateway_ok=True,
                model_invocation_performed=False,
                named_blocker=blocker,
                artifact_path=None,
                raw_response_path=raw_response_path,
                usage=usage,
                trigger_installed=trigger_installed,
            )
        return runner

    artifact = {
        "schema_version": f"{SCHEMA_VERSION}.artifact.v1",
        "provider_id": PROVIDER_ID,
        "selected_carrier_provider_id": PROVIDER_ID,
        "selected_model": model,
        "mode": mode,
        "route_role": PRO_REVIEW_ROUTE_ROLE,
        "objective": objective,
        "content": content,
        "completion_claim_allowed": False,
        "generated_at": now_iso(),
    }
    if write:
        write_json(artifact_path, artifact)

    runtime_enforced = trigger_installed and gateway_ok
    payload = {
        **base_payload,
        "status": "pro_review_ready",
        "mode_invocation_status": "model_ready",
        "provider_invocation_performed": True,
        "model_invocation_performed": True,
        "named_blocker": "",
        "result_path": str(artifact_path),
        "raw_response_ref": str(raw_response_path),
        "runtime_enforced": runtime_enforced,
        "runtime_enforced_scope": (
            "integrated_bus_pro_review_node_gateway_invoke"
            if runtime_enforced
            else "pro_review_thin_bind_partial_not_temporal_main_loop"
        ),
        "adoption_state": (
            "runtime_enforced_for_integrated_bus_pro_review_node_partial"
            if runtime_enforced
            else "api_cli_verifier_ready_trigger_installed_partial"
        ),
        "usage": usage,
        "evidence_refs": {
            "latest": str(paths["latest"]),
            "record_path": str(record_path),
            "result_path": str(artifact_path),
            "raw_response_ref": str(raw_response_path),
        },
    }
    runner = {
        "provider_payload": payload,
        "actual_dispatch_refs": {
            "result_path": str(artifact_path),
            "provider_invocation_ref": str(record_path),
        },
    }
    if write:
        write_json(record_path, runner)
        write_json(paths["latest"], runner)
        dp_latest = _sync_dp_sidecar_provider_evidence(
            runtime=runtime,
            invocation_id=resolved_invocation,
            mode=mode,
            objective=objective,
            input_text=input_text,
            model=model,
            gateway_url=gateway_url,
            gateway_ok=True,
            model_invocation_performed=True,
            named_blocker="",
            artifact_path=artifact_path,
            raw_response_path=raw_response_path,
            usage=usage,
            trigger_installed=trigger_installed,
        )
        payload["dp_sidecar_provider_latest_ref"] = dp_latest
        write_json(paths["latest"], runner)
    return runner


def run_pro_review_bus(
    *,
    runtime_root: Path,
    content_md: str,
    workflow_id: str = "",
    gateway_base_url: str | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Integrated bus node — pro review after sandbox/draft terminal."""
    del workflow_id
    objective = "333 integrated_bus pro_review_after_draft"
    runner = invoke_pro_review_via_gateway(
        runtime_root=runtime_root,
        mode="audit",
        objective=objective,
        input_text=content_md,
        draft_artifact_ref="integrated_bus:sandbox_stdout",
        gateway_base_url=gateway_base_url,
        write=write,
        trigger_installed=True,
    )
    payload = runner.get("provider_payload") if isinstance(runner.get("provider_payload"), dict) else {}
    return {
        "pro_review_ok": payload.get("model_invocation_performed") is True,
        "pro_review_status": str(payload.get("status") or ""),
        "pro_review_model": str(payload.get("selected_model") or ""),
        "pro_review_named_blocker": str(payload.get("named_blocker") or ""),
        "pro_review_evidence_ref": str(
            payload.get("evidence_refs", {}).get("latest")
            if isinstance(payload.get("evidence_refs"), dict)
            else ""
        ),
        "pro_review_runtime_enforced": payload.get("runtime_enforced") is True,
        "pro_review_trigger_installed": payload.get("trigger_installed") is True,
        "adapter": "routing_policy_gateway_deepseek_v4_pro",
    }