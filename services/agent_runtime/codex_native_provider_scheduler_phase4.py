from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import progress_self_evolution
from services.agent_runtime.provider_price_catalog import price_catalog_payload


SCHEMA_VERSION = "xinao.codex_s.codex_native_provider_scheduler_phase4.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_CODEX_NATIVE_PROVIDER_SCHEDULER_PHASE4"
TASK_ID = "codex_native_provider_scheduler_phase4_20260704"
PHASE3_TASK_ID = "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(
    os.environ.get("XINAO_REPO")
    or os.environ.get("XINAO_CODEX_WORKSPACE")
    or os.environ.get("XINAO_CODEX_WORKDIR")
    or Path(__file__).absolute().parents[2]
)
DESKTOP_MEMO_REF = Path(
    r"C:\Users\xx363\Desktop\新系统\备用历史\Codex_DeepSeek_高并行草稿主脑合并模式_20260704.txt"
)
QWEN_MEMO_REF = DESKTOP_MEMO_REF
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or r"C:\Users\xx363\.codex-seed-cortex")
DEFAULT_TASK_QUEUE = "xinao-codex-task-default"
QWEN_SECRET_REFS_RELATIVE = Path("private_config") / "provider_secrets" / "qwen_dashscope.secret_refs.json"
QWEN_CHEAP_MODEL_CANDIDATES = ["qwen3.6-flash", "qwen3.5-flash", "qwen-flash"]
QWEN_QUALITY_MODELS = ["qwen3.7-plus", "qwen3.7-max"]
QWEN_CODE_DIVERSITY_MODELS = ["qwen3-coder-flash", "qwen3-coder-plus"]
LOCAL_OLLAMA_PROVIDER_ID = "local_ollama_qwen"
LOCAL_OLLAMA_QWEN3_PROVIDER_ID = "local_ollama_qwen3"
LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID = "local_ollama_qwen25_coder"
LOCAL_OLLAMA_DEEPSEEK_R1_PROVIDER_ID = "local_ollama_deepseek_r1"
LOCAL_OLLAMA_MODEL_ENV = "XINAO_LOCAL_OLLAMA_CHEAP_MODEL"
LOCAL_OLLAMA_DEFAULT_MODEL = os.environ.get(LOCAL_OLLAMA_MODEL_ENV, "qwen3:8b")
LOCAL_OLLAMA_MODEL_POOL = (
    {
        "provider_id": LOCAL_OLLAMA_QWEN3_PROVIDER_ID,
        "model": "qwen3:8b",
        "role": "local_general_extract_draft_claimcard_worker",
        "route_roles": ["cheap_extract", "summary", "claimcard", "general_draft"],
        "modes": ["draft", "extraction", "eval"],
    },
    {
        "provider_id": LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID,
        "model": "qwen2.5-coder:7b",
        "role": "local_code_candidate_test_draft_worker",
        "route_roles": ["code_draft", "single_file_patch_proposal", "test_draft"],
        "modes": ["draft", "eval"],
    },
    {
        "provider_id": LOCAL_OLLAMA_DEEPSEEK_R1_PROVIDER_ID,
        "model": "deepseek-r1:8b",
        "role": "local_contradiction_sanity_audit_worker",
        "route_roles": ["contradiction", "sanity_audit", "local_reasoning"],
        "modes": ["audit", "contradiction", "eval"],
    },
)
LOCAL_OLLAMA_POOL_PROVIDER_IDS = tuple(str(item["provider_id"]) for item in LOCAL_OLLAMA_MODEL_POOL)
DEFAULT_COST_PER_ACCEPTED_ARTIFACT_LIMIT = 0.25
PROVIDER_ROUTING_MODE_ENV = "XINAO_CODEX_S_PROVIDER_ROUTING_MODE"
CODEX_CREDIT_PRESSURE_ENV = "XINAO_CODEX_CREDIT_PRESSURE"
DEFAULT_PROVIDER_ROUTING_MODE = "codex_brain_only"
PROVIDER_ROUTING_MODES = {"codex_primary", "qwen_dp_first", "codex_brain_only", "auto_low_credit"}
CODEX_BRAIN_ONLY_MODES = {"qwen_dp_first", "codex_brain_only"}
CODEX_ONLY_ACCEPTANCE_ROUTE_KEYS = frozenset(
    {
        "final_merge_artifact_acceptance",
    }
)
CODEX_BRAIN_ONLY_DEFAULT_WORKER_PROVIDER = "deepseek_v4_pro"
LITELLM_ROUTER_PROVIDER_ID = "litellm_router"
LITELLM_ROUTED_BY = "litellm"
P0_004_LITELLM_BINDING_ID = "p0_004_litellm_default_binding"
P0_004_REPLACE_TARGET = "ProviderScheduler hand-rolled gateway"
P0_004_REPLACEMENT = "LiteLLM Router"
P0_004_BINDING_MAX_ATTEMPTS = 3
P0_004_BINDING_MAX_RECURSIVE_REPAIRS = 2
P0_004_BINDING_RETRY_EXHAUSTED_BLOCKER = "LITELLM_BINDING_RETRY_BUDGET_EXHAUSTED"


def p0_004_binding_retry_policy() -> dict[str, Any]:
    return {
        "policy_id": "bounded_delivery_retry",
        "scope": "same_deliverable_binding_only",
        "max_attempts": P0_004_BINDING_MAX_ATTEMPTS,
        "max_recursive_repairs": P0_004_BINDING_MAX_RECURSIVE_REPAIRS,
        "backoff": "short_exponential_with_jitter",
        "retry_same_deliverable_on_failure": True,
        "continue_to_next_task_only_after": "accepted_for_binding",
        "failure_terminal_blocker": P0_004_BINDING_RETRY_EXHAUSTED_BLOCKER,
        "next_frontier_on_failure": False,
        "empty_retry_forbidden": True,
        "mature_pattern_refs": [
            "Temporal RetryPolicy.maximum_attempts",
            "LangGraph recursion_limit",
            "OpenAI Agents max_turns",
            "CrewAI max_iter/max_retry_limit",
        ],
    }


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def safe_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
    return cleaned.strip("-")[:140] or "artifact"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_provider_routing_mode(value: Any) -> str:
    mode = str(value or "").strip().lower().replace("-", "_")
    return mode if mode in PROVIDER_ROUTING_MODES else DEFAULT_PROVIDER_ROUTING_MODE


def detect_codex_credit_pressure(runtime: Path) -> dict[str, Any]:
    sources = [
        runtime / "state" / "default_auto_dispatch" / "latest.json",
        runtime / "state" / "temporal_codex_task_workflow" / "auto_dispatch_latest.json",
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
    ]
    env_pressure = str(os.environ.get(CODEX_CREDIT_PRESSURE_ENV) or "").strip().lower()
    pressure = env_pressure in {"1", "true", "yes", "on"}
    refs: list[str] = []
    blockers: list[str] = []
    retry_after = ""
    for path in sources:
        payload = read_json(path)
        if not payload:
            continue
        text = json.dumps(payload, ensure_ascii=False)
        if "CODEX_USAGE_LIMIT_RETRY_AFTER" in text or "usage limit" in text.lower():
            pressure = True
            refs.append(str(path))
        for key in ("named_blocker", "upstream_named_blocker", "retry_after_text"):
            value = str(payload.get(key) or "")
            if value:
                if key == "retry_after_text" and not retry_after:
                    retry_after = value
                elif "CODEX" in value or "LIMIT" in value.upper():
                    blockers.append(value)
    return {
        "active": pressure,
        "env_var": CODEX_CREDIT_PRESSURE_ENV,
        "env_active": env_pressure in {"1", "true", "yes", "on"},
        "evidence_refs": refs,
        "named_blockers": sorted(set(blockers)),
        "retry_after_text": retry_after,
    }


def load_provider_cost_routing_policy(runtime: Path) -> dict[str, Any]:
    paths = output_paths(runtime)
    configured = read_json(paths["provider_cost_routing_policy_latest"])
    env_mode = os.environ.get(PROVIDER_ROUTING_MODE_ENV)
    raw_configured_mode = configured.get("mode") or configured.get("configured_mode")
    configured_mode = normalize_provider_routing_mode(
        env_mode or raw_configured_mode
    )
    legacy_mode_alias_migrated = (
        not env_mode
        and configured_mode == "qwen_dp_first"
        and DEFAULT_PROVIDER_ROUTING_MODE == "codex_brain_only"
    )
    if legacy_mode_alias_migrated:
        configured_mode = "codex_brain_only"
    credit_pressure = detect_codex_credit_pressure(runtime)
    effective_mode = configured_mode
    if configured_mode == "auto_low_credit":
        effective_mode = "codex_brain_only" if credit_pressure.get("active") else "codex_primary"
    return {
        "schema_version": f"{SCHEMA_VERSION}.provider_cost_routing_policy.v1",
        "status": "provider_cost_routing_policy_ready",
        "mode": configured_mode,
        "configured_mode_source": "env" if env_mode else "runtime_policy_or_default",
        "legacy_mode_alias_migrated": legacy_mode_alias_migrated,
        "legacy_mode_alias": "qwen_dp_first" if legacy_mode_alias_migrated else "",
        "effective_mode": effective_mode,
        "default_mode": DEFAULT_PROVIDER_ROUTING_MODE,
        "switch_env": PROVIDER_ROUTING_MODE_ENV,
        "runtime_policy_ref": str(paths["provider_cost_routing_policy_latest"]),
        "codex_credit_pressure": credit_pressure,
        "qwen_dp_first_global_default": DEFAULT_PROVIDER_ROUTING_MODE in CODEX_BRAIN_ONLY_MODES,
        "codex_brain_only_global_default": DEFAULT_PROVIDER_ROUTING_MODE == "codex_brain_only",
        "codex_primary_switch_available": True,
        "allowed_modes": sorted(PROVIDER_ROUTING_MODES),
        "semantics": {
            "qwen_dp_first": "Qwen/DP handle extraction, draft, eval, audit, contradiction, and bulk worker output; Codex stays final patch, merge, AAQ, and high-risk owner.",
            "codex_brain_only": "Qwen/prepaid quota handles suitable cheap extraction/classification/compression first, DeepSeek handles heavier staging and quality escalation, and Codex is capped to routing decisions, high-risk judgment, final merge, and AAQ.",
            "codex_primary": "Codex can take primary worker execution while Qwen/DP remain cheap auxiliary lanes.",
            "auto_low_credit": "Use codex_primary until Codex credit pressure is observed, then switch to codex_brain_only.",
        },
        "not_completion_boundary": True,
    }


def as_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def as_int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def scrub_secret_text(value: Any, *, api_key: str = "") -> str:
    text = str(value)
    secret_values = [
        api_key,
        os.environ.get("DASHSCOPE_API_KEY", ""),
        os.environ.get("DEEPSEEK_API_KEY", ""),
        os.environ.get("OPENAI_API_KEY", ""),
    ]
    for secret in secret_values:
        if secret:
            text = text.replace(secret, "[REDACTED_SECRET]")
    return text[-1200:]


def qwen_secret_refs(runtime: Path) -> dict[str, Any]:
    payload = read_json(output_paths(runtime)["qwen_secret_refs"])
    return payload if isinstance(payload, dict) else {}


def _read_text_secret(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            candidate = line.strip().strip('"').strip("'")
            if candidate and len(candidate) >= 8:
                return candidate
    except Exception:
        return ""
    return ""


def _read_csv_secret(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            rows = list(csv.reader(handle))
    except Exception:
        return ""
    for row in rows:
        for cell in row:
            candidate = str(cell).strip().strip('"').strip("'")
            lowered = candidate.lower()
            if (
                len(candidate) >= 20
                and not candidate.isdigit()
                and lowered not in {"id", "apikey", "api_key", "secret", "token"}
            ):
                return candidate
    return ""


def qwen_api_key_candidates(runtime: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    env_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if env_key:
        candidates.append({"api_key": env_key, "source_label": "env:DASHSCOPE_API_KEY"})
        seen.add(env_key)

    refs = qwen_secret_refs(runtime)
    file_candidates = [
        ("runtime_private_config:qwen_key_csv_path", refs.get("qwen_key_csv_path"), _read_csv_secret),
        ("runtime_private_config:qwen_key_txt_path", refs.get("qwen_key_txt_path"), _read_text_secret),
    ]
    for label, raw_path, reader in file_candidates:
        if not raw_path:
            continue
        path = Path(str(raw_path))
        if not path.is_file():
            continue
        api_key = reader(path).strip()
        if api_key and api_key not in seen:
            candidates.append({"api_key": api_key, "source_label": label})
            seen.add(api_key)
    return candidates


def load_qwen_api_key(runtime: Path) -> dict[str, Any]:
    candidates = qwen_api_key_candidates(runtime)
    if candidates:
        first = candidates[0]
        return {
            "api_key": first.get("api_key") or "",
            "source_label": first.get("source_label") or "",
            "available": True,
            "candidate_count": len(candidates),
            "named_blocker": "",
        }
    return {
        "api_key": "",
        "source_label": "",
        "available": False,
        "candidate_count": 0,
        "named_blocker": "DASHSCOPE_API_KEY_NOT_CONFIGURED",
    }


def qwen_base_url_candidates(runtime: Path) -> list[dict[str, str]]:
    refs = qwen_secret_refs(runtime)
    candidates: list[dict[str, str]] = []
    env_base_url = os.environ.get("DASHSCOPE_BASE_URL", "").strip()
    if env_base_url:
        candidates.append({"label": "env:DASHSCOPE_BASE_URL", "base_url": env_base_url})
    runtime_base_url = str(refs.get("base_url") or "").strip()
    if runtime_base_url:
        candidates.append({"label": "runtime_private_config:base_url", "base_url": runtime_base_url})
    workspace_id = str(refs.get("workspace_id") or "").strip()
    if workspace_id:
        candidates.append(
            {
                "label": "runtime_private_config:workspace_beijing_base_url",
                "base_url": f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            }
        )
    candidates.append(
        {
            "label": "dashscope_generic_openai_compatible",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        }
    )
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        base_url = candidate["base_url"].rstrip("/")
        if base_url in seen:
            continue
        seen.add(base_url)
        deduped.append({"label": candidate["label"], "base_url": base_url})
    return deduped


def qwen_secret_status(runtime: Path) -> dict[str, Any]:
    refs_path = output_paths(runtime)["qwen_secret_refs"]
    refs = qwen_secret_refs(runtime)
    key = load_qwen_api_key(runtime)
    candidates = qwen_api_key_candidates(runtime)
    return {
        "secret_policy": "runtime private config/env only; secret values are never written to repo or evidence",
        "api_key_available": key.get("available") is True,
        "api_key_source_label": key.get("source_label") or "",
        "api_key_candidate_count": len(candidates),
        "api_key_source_labels_available": [str(item.get("source_label") or "") for item in candidates],
        "runtime_secret_refs_present": refs_path.is_file(),
        "txt_ref_present": bool(refs.get("qwen_key_txt_path")),
        "csv_ref_present": bool(refs.get("qwen_key_csv_path")),
        "workspace_configured": bool(refs.get("workspace_id")),
        "base_url_configured": bool(os.environ.get("DASHSCOPE_BASE_URL") or refs.get("base_url") or refs.get("workspace_id")),
        "env_vars": ["DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"],
        "named_blocker": "" if key.get("available") else str(key.get("named_blocker") or "DASHSCOPE_API_KEY_NOT_CONFIGURED"),
    }


def local_ollama_status(timeout_seconds: int = 5, selected_model: str | None = None) -> dict[str, Any]:
    executable = shutil.which("ollama")
    selected_model = selected_model or os.environ.get(LOCAL_OLLAMA_MODEL_ENV, LOCAL_OLLAMA_DEFAULT_MODEL)
    payload: dict[str, Any] = {
        "provider_id": LOCAL_OLLAMA_PROVIDER_ID,
        "selected_model": selected_model,
        "model_env": LOCAL_OLLAMA_MODEL_ENV,
        "ollama_models_env": os.environ.get("OLLAMA_MODELS", ""),
        "executable": executable or "",
        "models": [],
        "ready": False,
        "status": "local_ollama_qwen_blocked",
        "named_blocker": "",
    }
    models_root = Path(str(payload["ollama_models_env"])) if payload["ollama_models_env"] else None
    payload["models_root_exists"] = bool(models_root and models_root.exists())
    if not executable:
        payload["named_blocker"] = "OLLAMA_CLI_NOT_INSTALLED"
        return payload
    try:
        completed = subprocess.run(
            [executable, "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired:
        payload["named_blocker"] = "OLLAMA_LIST_TIMEOUT"
        return payload
    except Exception as exc:
        payload["named_blocker"] = f"OLLAMA_LIST_FAILED:{exc.__class__.__name__}"
        return payload
    payload["ollama_list_returncode"] = completed.returncode
    if completed.returncode != 0:
        payload["stderr_tail"] = scrub_secret_text(completed.stderr)[-500:]
        payload["named_blocker"] = "OLLAMA_LIST_FAILED"
        return payload
    models: list[str] = []
    for line in (completed.stdout or "").splitlines()[1:]:
        fields = line.split()
        if fields:
            models.append(fields[0])
    payload["models"] = models
    if selected_model in models:
        payload["ready"] = True
        payload["status"] = "local_ollama_qwen_ready"
        return payload
    payload["named_blocker"] = "OLLAMA_QWEN_MODEL_NOT_AVAILABLE"
    return payload


def local_ollama_pool_status(timeout_seconds: int = 5) -> dict[str, Any]:
    model_statuses = []
    ready_provider_ids: list[str] = []
    ready_models: list[str] = []
    for spec in LOCAL_OLLAMA_MODEL_POOL:
        model = str(spec["model"])
        try:
            status = local_ollama_status(timeout_seconds=timeout_seconds, selected_model=model)
        except TypeError:
            status = local_ollama_status(timeout_seconds=timeout_seconds)
            models = status.get("models") if isinstance(status.get("models"), list) else []
            if model != status.get("selected_model") and model not in models:
                status = {
                    **status,
                    "ready": False,
                    "status": "local_ollama_model_optional_blocked",
                    "selected_model": model,
                    "named_blocker": "OLLAMA_MODEL_NOT_AVAILABLE",
                }
        ready = status.get("ready") is True
        if ready:
            ready_provider_ids.append(str(spec["provider_id"]))
            ready_models.append(model)
        model_statuses.append(
            {
                **spec,
                "ready": ready,
                "status": "ready" if ready else "optional_blocked",
                "health": status,
                "selected_by_env": model == os.environ.get(LOCAL_OLLAMA_MODEL_ENV, LOCAL_OLLAMA_DEFAULT_MODEL),
                "outputs_to_staging_only": True,
                "direct_repo_write_allowed": False,
                "can_search_directly": False,
                "local_only": True,
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}.local_ollama_pool_status.v1",
        "provider_id": "local_ollama_pool",
        "carrier_provider_id": LOCAL_OLLAMA_PROVIDER_ID,
        "status": "local_ollama_pool_ready" if ready_provider_ids else "local_ollama_pool_optional_blocked",
        "ready": bool(ready_provider_ids),
        "ready_provider_ids": ready_provider_ids,
        "ready_models": ready_models,
        "model_statuses": model_statuses,
        "resource_limiter": {
            "ollama_models_env": os.environ.get("OLLAMA_MODELS", ""),
            "max_loaded_models_env": "OLLAMA_MAX_LOADED_MODELS",
            "max_loaded_models": os.environ.get("OLLAMA_MAX_LOADED_MODELS", ""),
            "num_parallel_env": "OLLAMA_NUM_PARALLEL",
            "num_parallel": os.environ.get("OLLAMA_NUM_PARALLEL", ""),
            "concurrency_scope": "resource_limiter_only_not_route_policy",
        },
        "local_is_candidate_not_mandatory_first": True,
        "not_search_provider": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def local_pool_candidates_for_route(route_key: str, pool_status: dict[str, Any]) -> list[str]:
    if not pool_status.get("ready"):
        return []
    route = route_key.lower()
    candidates: list[str] = []
    for item in pool_status.get("model_statuses", []):
        if not isinstance(item, dict) or item.get("ready") is not True:
            continue
        provider_id = str(item.get("provider_id") or "")
        route_roles = " ".join(str(role) for role in item.get("route_roles", []))
        if "code" in route and provider_id == LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID:
            candidates.append(provider_id)
        elif any(token in route for token in ["audit", "contradiction", "sanity"]) and provider_id == LOCAL_OLLAMA_DEEPSEEK_R1_PROVIDER_ID:
            candidates.append(provider_id)
        elif provider_id == LOCAL_OLLAMA_QWEN3_PROVIDER_ID and any(
            token in f"{route} {route_roles}"
            for token in ["draft", "extract", "summary", "claimcard", "cheap", "eval"]
        ):
            candidates.append(provider_id)
    return candidates


def worker_turn_provider_decision(input_payload: dict[str, Any]) -> dict[str, Any]:
    route_key = str(
        input_payload.get("provider_route_key")
        or input_payload.get("route_key")
        or input_payload.get("route_class")
        or ""
    ).strip()
    worker_kind = str(input_payload.get("worker_kind") or "").strip()
    phase_scope = str(input_payload.get("phase_scope") or "")
    prompt = str(input_payload.get("codex_worker_prompt") or "")
    haystack = f"{route_key} {worker_kind} {phase_scope} {prompt}".lower()
    pool_status = local_ollama_pool_status(timeout_seconds=2)
    prompt_size = len(prompt.encode("utf-8", errors="replace"))
    local_queue_depth = as_int(os.environ.get("XINAO_LOCAL_OLLAMA_QUEUE_DEPTH"))
    local_reasonable = (
        pool_status.get("ready") is True
        and local_queue_depth <= 0
        and prompt_size <= as_int(os.environ.get("XINAO_LOCAL_OLLAMA_MAX_PROMPT_BYTES") or 12000)
    )
    signals = {
        "semantic_route_key": route_key,
        "worker_kind": worker_kind,
        "phase_scope": phase_scope,
        "prompt_size_bytes": prompt_size,
        "local_queue_depth": local_queue_depth,
        "local_reasonable": local_reasonable,
        "local_pool_ready_provider_ids": pool_status.get("ready_provider_ids", []),
        "routing_inputs": [
            "semantic_route_key",
            "worker_kind",
            "phase_scope",
            "prompt_size_bytes",
            "local_queue_depth",
            "local_model_loaded_or_available",
            "provider_health",
            "budget_gate",
            "quality_risk",
            "repo_mutation_risk",
        ],
    }
    if route_key == "final_merge_artifact_acceptance" or input_payload.get("final_acceptance_only") is True:
        provider_id, mode, reason, model = "codex_exec", "", "final_acceptance_codex_short_signoff", ""
    elif route_key == "high_risk_patch_or_repo_mutation" or input_payload.get("aaq_final_signoff") is True:
        provider_id, mode, reason, model = "codex_exec", "", "high_risk_repo_mutation_codex_owned", ""
    elif route_key == "structural_blocker_repair" or input_payload.get("structural_blocker_repair") is True:
        provider_id, mode, reason, model = "deepseek_v4_pro", "audit", "structural_blocker_repair_v4pro", ""
    elif any(token in haystack for token in ["merge", "conflict", "architecture", "supervisor", "frontier", "synthesis", "plan_review"]):
        provider_id, mode, reason, model = "deepseek_v4_pro", "audit", "complex_brain_or_architecture_v4pro", ""
    elif any(token in haystack for token in ["contradiction", "sanity", "反驳", "矛盾"]):
        local_candidates = local_pool_candidates_for_route("contradiction_sanity_audit", pool_status)
        if local_reasonable and LOCAL_OLLAMA_DEEPSEEK_R1_PROVIDER_ID in local_candidates:
            provider_id, mode, reason, model = (
                LOCAL_OLLAMA_DEEPSEEK_R1_PROVIDER_ID,
                "audit",
                "dynamic_router_local_deepseek_r1_sanity_audit",
                "deepseek-r1:8b",
            )
        else:
            provider_id, mode, reason, model = "deepseek_v4_pro", "audit", "sanity_audit_cloud_v4pro_or_dp", ""
    elif "code" in haystack or "patch" in haystack or "test" in haystack or worker_kind == "implementation_worker":
        local_candidates = local_pool_candidates_for_route("code_draft", pool_status)
        if local_reasonable and LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID in local_candidates:
            provider_id, mode, reason, model = (
                LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID,
                "draft",
                "dynamic_router_local_qwen25_coder_code_draft",
                "qwen2.5-coder:7b",
            )
        else:
            provider_id, mode, reason, model = "qwen_prepaid_cheap_worker", "draft", "dynamic_router_qwen_cloud_code_or_draft", ""
    else:
        local_candidates = local_pool_candidates_for_route("cheap_draft_extract_eval", pool_status)
        if local_reasonable and LOCAL_OLLAMA_QWEN3_PROVIDER_ID in local_candidates:
            provider_id, mode, reason, model = (
                LOCAL_OLLAMA_QWEN3_PROVIDER_ID,
                "draft",
                "dynamic_router_local_qwen3_cheap_draft",
                "qwen3:8b",
            )
        else:
            provider_id, mode, reason, model = "qwen_prepaid_cheap_worker", "draft", "dynamic_router_qwen_cloud_cheap_pool", ""
    return {
        "schema_version": f"{SCHEMA_VERSION}.worker_turn_provider_decision.v1",
        "provider_id": provider_id,
        "mode": mode,
        "route_reason": reason,
        "selected_local_model": model,
        "selected_carrier_provider_id": LOCAL_OLLAMA_PROVIDER_ID if provider_id in LOCAL_OLLAMA_POOL_PROVIDER_IDS else provider_id,
        "signals": signals,
        "local_ollama_pool_status": pool_status,
        "mature_router_alignment": {
            "litellm_router_installed": module_available("litellm"),
            "semantic_router_installed": module_available("semantic_router"),
            "routellm_installed": module_available("routellm"),
            "static_order_is_fallback_only": True,
            "local_first_mandatory": False,
            "route_llm_style_cost_quality_thresholds": True,
            "semantic_router_style_intent_classification": True,
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def invoke_qwen_canary(runtime: Path, *, timeout_seconds: int) -> dict[str, Any]:
    key = load_qwen_api_key(runtime)
    key_candidates = qwen_api_key_candidates(runtime)
    result: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.qwen_invocation.v1",
        "provider_id": "qwen_dashscope",
        "role": "prepaid_priority_cheap_worker_canary",
        "invoke_performed": True,
        "api_key_present": key.get("available") is True,
        "api_key_source_label": key.get("source_label") or "",
        "api_key_candidate_count": len(key_candidates),
        "api_key_source_labels_attempted": [],
        "models_attempted": [],
        "attempts": [],
        "succeeded": False,
        "status": "qwen_dashscope_canary_blocked",
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }
    if not key.get("available"):
        result["named_blocker"] = key.get("named_blocker") or "DASHSCOPE_API_KEY_NOT_CONFIGURED"
        return result
    if not module_available("openai"):
        result["named_blocker"] = "OPENAI_PYTHON_SDK_NOT_INSTALLED_FOR_DASHSCOPE"
        return result

    from openai import OpenAI
    try:
        import httpx
    except Exception:
        httpx = None  # type: ignore[assignment]

    prompt = (
        "Return a compact JSON object with provider_id='qwen_dashscope', "
        "status='ready', role='prepaid_priority_cheap_worker'. No markdown."
    )
    deadline = time.time() + max(5, timeout_seconds)
    for key_candidate in key_candidates:
        api_key = str(key_candidate.get("api_key") or "")
        source_label = str(key_candidate.get("source_label") or "")
        result["api_key_source_labels_attempted"].append(source_label)
        for base in qwen_base_url_candidates(runtime):
            for model in QWEN_CHEAP_MODEL_CANDIDATES:
                remaining = deadline - time.time()
                if remaining <= 1:
                    result["named_blocker"] = "QWEN_DASHSCOPE_CANARY_TIMEOUT"
                    return result
                result["models_attempted"].append(model)
                attempt = {
                    "api_key_source_label": source_label,
                    "base_url_label": base["label"],
                    "model": model,
                    "request_shape": "openai.chat.completions.create",
                    "trust_env_proxy": False,
                }
                http_client = None
                try:
                    client_timeout = max(3, min(10, remaining))
                    client_kwargs: dict[str, Any] = {
                        "api_key": api_key,
                        "base_url": base["base_url"],
                        "timeout": client_timeout,
                        "max_retries": 0,
                    }
                    if httpx is not None:
                        http_client = httpx.Client(timeout=client_timeout, trust_env=False)
                        client_kwargs["http_client"] = http_client
                    client = OpenAI(
                        **client_kwargs,
                    )
                    completion = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "You are a provider canary. Return only JSON."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0,
                        max_tokens=120,
                        extra_body={"enable_thinking": False},
                    )
                    content = completion.choices[0].message.content if completion.choices else ""
                    attempt["status"] = "succeeded"
                    result["attempts"].append(attempt)
                    result.update(
                        {
                            "succeeded": bool(content),
                            "status": "qwen_dashscope_canary_ready" if content else "qwen_dashscope_canary_blocked",
                            "selected_model": model,
                            "selected_base_url_label": base["label"],
                            "selected_api_key_source_label": source_label,
                            "response_excerpt": str(content or "")[:500],
                        }
                    )
                    if result["succeeded"]:
                        return result
                except Exception as exc:
                    attempt.update(
                        {
                            "status": "failed",
                            "error_type": exc.__class__.__name__,
                            "error_tail": scrub_secret_text(exc, api_key=api_key),
                        }
                    )
                    result["attempts"].append(attempt)
                finally:
                    if http_client is not None:
                        http_client.close()
    result["named_blocker"] = "QWEN_DASHSCOPE_OPENAI_COMPATIBLE_INVOKE_FAILED"
    return result


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / TASK_ID
    return {
        "state": state,
        "latest": state / "latest.json",
        "records": state / "records",
        "claim_cards_latest": state / "claim_cards" / "latest.json",
        "provider_registry_latest": state / "provider_registry" / "latest.json",
        "executor_adapter_latest": state / "executor_adapter" / "latest.json",
        "model_gateway_latest": state / "model_gateway" / "latest.json",
        "model_gateway_config": state / "model_gateway" / "litellm_router.codex_native.yaml",
        "provider_price_catalog_latest": runtime / "state" / "provider_price_catalog" / "latest.json",
        "provider_cost_routing_policy_latest": runtime / "state" / "provider_cost_routing_policy" / "latest.json",
        "scheduler_decision_latest": state / "scheduler_decision" / "latest.json",
        "provider_invocation_latest": state / "provider_invocation" / "latest.json",
        "qwen_invocation_latest": state / "qwen_invocation" / "latest.json",
        "qwen_prepaid_policy_latest": state / "qwen_prepaid_policy" / "latest.json",
        "draft_staging_latest": state / "draft_staging" / "latest.json",
        "merge_consumer_latest": state / "merge_consumer" / "latest.json",
        "temporal_activity_latest": state / "temporal_activity" / "latest.json",
        "schemas": state / "schemas",
        "logs": state / "logs",
        "readback": runtime / "readback" / "zh" / f"{TASK_ID}.md",
        "capability_manifest": runtime / "capabilities" / "codex_s.provider_scheduler" / "manifest.json",
        "loop_runtime_state_latest": runtime / "state" / "loop_runtime_state" / "latest.json",
        "phase3_latest": runtime / "state" / PHASE3_TASK_ID / "latest.json",
        "qwen_secret_refs": runtime / QWEN_SECRET_REFS_RELATIVE,
    }


def hidden_subprocess_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def codex_command(args: list[str]) -> tuple[list[str], str]:
    codex_path = (
        shutil.which("codex.ps1")
        or shutil.which("codex.cmd")
        or shutil.which("codex.exe")
        or shutil.which("codex")
    )
    if not codex_path:
        return [], ""
    suffix = Path(codex_path).suffix.lower()
    if os.name == "nt" and suffix == ".ps1":
        powershell = shutil.which("powershell.exe") or shutil.which("powershell") or "powershell.exe"
        return [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            codex_path,
            *args,
        ], codex_path
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        comspec = os.environ.get("ComSpec") or "cmd.exe"
        return [comspec, "/d", "/s", "/c", codex_path, *args], codex_path
    return [codex_path, *args], codex_path


def run_hidden_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, Any]:
    started = time.time()
    env = dict(os.environ)
    env["CODEX_HOME"] = str(CODEX_HOME)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            **hidden_subprocess_kwargs(),
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8", errors="replace")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8", errors="replace")
        return {
            "command": command,
            "returncode": completed.returncode,
            "timed_out": False,
            "latency_ms": int((time.time() - started) * 1000),
            "stdout_ref": str(stdout_path),
            "stderr_ref": str(stderr_path),
            "stdout_digest_sha256": hashlib.sha256((completed.stdout or "").encode("utf-8", errors="replace")).hexdigest(),
            "stderr_tail": (completed.stderr or "")[-1200:],
            "hidden_no_window": os.name == "nt",
        }
    except OSError as exc:
        stdout_path.write_text("", encoding="utf-8", errors="replace")
        stderr_path.write_text(str(exc), encoding="utf-8", errors="replace")
        return {
            "command": command,
            "returncode": -1,
            "timed_out": False,
            "latency_ms": int((time.time() - started) * 1000),
            "stdout_ref": str(stdout_path),
            "stderr_ref": str(stderr_path),
            "stdout_digest_sha256": hashlib.sha256(b"").hexdigest(),
            "stderr_tail": str(exc)[-1200:],
            "hidden_no_window": os.name == "nt",
            "named_blocker": "COMMAND_NOT_FOUND_OR_UNEXECUTABLE",
        }
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8", errors="replace")
        stderr_path.write_text(exc.stderr or "", encoding="utf-8", errors="replace")
        return {
            "command": command,
            "returncode": -1,
            "timed_out": True,
            "latency_ms": int((time.time() - started) * 1000),
            "stdout_ref": str(stdout_path),
            "stderr_ref": str(stderr_path),
            "stdout_digest_sha256": hashlib.sha256((exc.stdout or "").encode("utf-8", errors="replace")).hexdigest(),
            "stderr_tail": str(exc)[-1200:],
            "hidden_no_window": os.name == "nt",
            "named_blocker": "CODEX_EXEC_CANARY_TIMEOUT",
        }


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def codex_version(runtime: Path, cwd: Path) -> dict[str, Any]:
    command, codex = codex_command(["--version"])
    if not command:
        return {"installed": False, "named_blocker": "CODEX_CLI_NOT_INSTALLED"}
    probe = run_hidden_command(
        command,
        cwd=cwd,
        timeout_seconds=20,
        stdout_path=runtime / "state" / TASK_ID / "logs" / "codex_version.stdout.txt",
        stderr_path=runtime / "state" / TASK_ID / "logs" / "codex_version.stderr.txt",
    )
    version = ""
    try:
        version = Path(probe["stdout_ref"]).read_text(encoding="utf-8").strip()
    except Exception:
        version = ""
    return {"installed": probe.get("returncode") == 0, "path": codex, "version": version, "probe": probe}


def write_codex_exec_output_schema(path: Path) -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["provider_id", "status", "capability", "no_file_edits"],
        "properties": {
            "provider_id": {"type": "string"},
            "status": {"type": "string"},
            "capability": {"type": "string"},
            "no_file_edits": {"type": "boolean"},
        },
    }
    write_json(path, schema)


def invoke_codex_exec_canary(runtime: Path, repo: Path, *, timeout_seconds: int) -> dict[str, Any]:
    paths = output_paths(runtime)
    schema_path = paths["schemas"] / "codex_exec_canary.schema.json"
    last_message = paths["logs"] / "codex_exec_canary.last_message.json"
    stdout = paths["logs"] / "codex_exec_canary.stdout.jsonl"
    stderr = paths["logs"] / "codex_exec_canary.stderr.txt"
    write_codex_exec_output_schema(schema_path)
    prompt = (
        "You are a bounded Codex exec canary for Seed Cortex S. "
        "Do not edit files and do not run shell commands. "
        "Return a JSON object with provider_id='codex_exec', status='ready', "
        "capability='non_interactive_engineering_worker', no_file_edits=true."
    )
    command, codex_path = codex_command(
        [
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--cd",
            str(repo),
            "--ephemeral",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(last_message),
            prompt,
        ]
    )
    if not command:
        result = {
            "command": ["codex", "exec"],
            "returncode": -1,
            "timed_out": False,
            "latency_ms": 0,
            "stdout_ref": str(stdout),
            "stderr_ref": str(stderr),
            "stdout_digest_sha256": hashlib.sha256(b"").hexdigest(),
            "stderr_tail": "codex command not found",
            "hidden_no_window": os.name == "nt",
            "named_blocker": "CODEX_CLI_NOT_INSTALLED",
        }
    else:
        result = run_hidden_command(
            command,
            cwd=repo,
            timeout_seconds=timeout_seconds,
            stdout_path=stdout,
            stderr_path=stderr,
        )
        result["codex_path"] = codex_path
    last_payload: dict[str, Any] = {}
    if last_message.is_file():
        try:
            last_payload = json.loads(last_message.read_text(encoding="utf-8-sig"))
        except Exception:
            last_payload = {"raw": last_message.read_text(encoding="utf-8", errors="replace")[:2000]}
    result.update(
        {
            "provider_id": "codex_exec",
            "invoke_performed": True,
            "last_message_ref": str(last_message),
            "last_message_payload": last_payload,
            "succeeded": result.get("returncode") == 0
            and (last_payload.get("provider_id") == "codex_exec" or bool(last_payload)),
            "status": "codex_exec_canary_ready"
            if result.get("returncode") == 0
            and (last_payload.get("provider_id") == "codex_exec" or bool(last_payload))
            else "codex_exec_canary_blocked",
            "not_completion_boundary": True,
        }
    )
    if not result["succeeded"]:
        result["named_blocker"] = result.get("named_blocker") or "CODEX_EXEC_CANARY_FAILED_OR_AUTH_BLOCKED"
    return result


def read_codex_exec_cached_canary(runtime: Path) -> dict[str, Any]:
    paths = output_paths(runtime)
    last_message = paths["logs"] / "codex_exec_canary.last_message.json"
    stdout = paths["logs"] / "codex_exec_canary.stdout.jsonl"
    stderr = paths["logs"] / "codex_exec_canary.stderr.txt"
    version_stdout = paths["logs"] / "codex_version.stdout.txt"
    last_payload: dict[str, Any] = {}
    if last_message.is_file():
        try:
            last_payload = json.loads(last_message.read_text(encoding="utf-8-sig"))
        except Exception:
            last_payload = {
                "raw": last_message.read_text(encoding="utf-8", errors="replace")[:2000]
            }
    version = ""
    if version_stdout.is_file():
        version = version_stdout.read_text(encoding="utf-8", errors="replace").strip()
    ready = last_payload.get("provider_id") == "codex_exec" or bool(last_payload)
    payload = {
        "provider_id": "codex_exec",
        "invoke_performed": False,
        "cached_readiness_observed": ready,
        "succeeded": ready,
        "status": "codex_exec_cached_canary_ready"
        if ready
        else "codex_exec_cached_canary_missing",
        "last_message_ref": str(last_message),
        "last_message_payload": last_payload,
        "stdout_ref": str(stdout),
        "stderr_ref": str(stderr),
        "version": version,
        "not_completion_boundary": True,
    }
    if not ready:
        payload["named_blocker"] = "CODEX_EXEC_CACHED_CANARY_MISSING"
    return payload


def external_research_claim_cards() -> dict[str, Any]:
    cards = [
        {
            "source_family": "official_openai_codex",
            "url": "https://developers.openai.com/codex/noninteractive",
            "claim": "codex exec is the documented non-interactive surface for scripts and CI without opening the TUI.",
            "accepted_for": "codex_exec_primary_code_executor_adapter",
        },
        {
            "source_family": "official_openai_codex",
            "url": "https://developers.openai.com/codex/sdk",
            "claim": "Codex SDK is the documented programmatic control surface for internal tools, CI/CD, workflows, and complex engineering tasks.",
            "accepted_for": "codex_sdk_long_running_code_worker_adapter",
        },
        {
            "source_family": "official_openai_agents",
            "url": "https://developers.openai.com/codex/guides/agents-sdk",
            "claim": "Codex CLI can be exposed as an MCP server to the Agents SDK via codex and codex-reply tools.",
            "accepted_for": "codex_mcp_agents_adapter",
        },
        {
            "source_family": "official_litellm",
            "url": "https://docs.litellm.ai/docs/routing",
            "claim": "LiteLLM Router provides load balancing, queueing, cooldowns, fallbacks, timeouts, and retries.",
            "accepted_for": "model_gateway_router",
        },
        {
            "source_family": "official_litellm",
            "url": "https://docs.litellm.ai/docs/providers/ollama",
            "claim": "LiteLLM can route to Ollama local models, so local models can be gateway candidates without becoming a separate controller.",
            "accepted_for": "local_ollama_model_gateway_candidate_pool",
        },
        {
            "source_family": "upstream_routellm",
            "url": "https://github.com/lm-sys/RouteLLM",
            "claim": "RouteLLM-style routing treats cheap and strong models as a cost-quality threshold decision, not a fixed local-first chain.",
            "accepted_for": "cost_quality_router_policy_boundary",
        },
        {
            "source_family": "upstream_semantic_router",
            "url": "https://github.com/aurelio-labs/semantic-router",
            "claim": "Semantic routing should classify intent before model choice, reducing slow or keyword-only model selection.",
            "accepted_for": "semantic_route_class_before_provider_choice",
        },
        {
            "source_family": "upstream_vllm_semantic_router",
            "url": "https://github.com/vllm-project/semantic-router",
            "claim": "vLLM Semantic Router frames routing across local, private, and frontier models by capability, cost, privacy, and safety signals.",
            "accepted_for": "local_private_frontier_provider_pool_boundary",
        },
        {
            "source_family": "official_openrouter",
            "url": "https://openrouter.ai/docs/guides/routing/provider-selection",
            "claim": "Provider routing can use price, throughput, latency, and fallback signals, so static provider order is only a fallback hint.",
            "accepted_for": "provider_health_price_latency_fallback_inputs",
        },
        {
            "source_family": "official_ollama",
            "url": "https://docs.ollama.com/faq",
            "claim": "OLLAMA_MAX_LOADED_MODELS and OLLAMA_NUM_PARALLEL are resource limits, not task routing policy.",
            "accepted_for": "local_ollama_resource_limiter_not_router_policy",
        },
        {
            "source_family": "official_aliyun_dashscope",
            "url": "https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope/",
            "claim": "DashScope exposes OpenAI-compatible API access using API keys, model names, and compatible-mode base URLs.",
            "accepted_for": "qwen_dashscope_openai_compatible_adapter",
        },
        {
            "source_family": "official_aliyun_qwen_models",
            "url": "https://www.alibabacloud.com/help/en/model-studio/text-generation/",
            "claim": "Qwen text-generation model families include low-cost flash workers and stronger plus/max models for higher quality lanes.",
            "accepted_for": "qwen_prepaid_cheap_worker_and_quality_escalation",
        },
        {
            "source_family": "official_aliyun_dashscope_rate_limit",
            "url": "https://help.aliyun.com/zh/model-studio/rate-limit/",
            "claim": "DashScope account/API-key quotas are shared and different models have independent rate-limit dimensions.",
            "accepted_for": "qwen_dynamic_width_scheduler_rate_limit_inputs",
        },
        {
            "source_family": "official_temporal",
            "url": "https://docs.temporal.io/task-queue",
            "claim": "Temporal task queues persist work for polling workers and are the right durable owner for background activity execution.",
            "accepted_for": "hidden_temporal_activity_owner",
        },
        {
            "source_family": "python_stdlib",
            "url": "https://docs.python.org/3/library/subprocess.html",
            "claim": "subprocess.CREATE_NO_WINDOW is the Windows mechanism for child processes without visible console windows.",
            "accepted_for": "windows_no_window_executor_adapter",
        },
        {
            "source_family": "local_mature_open_source",
            "url": r"E:\XINAO_EXTERNAL_MATURE\codex_20260627\awesome_extracted\ben-vargas__ai-sdk-provider-codex-cli",
            "claim": "Local mature adapter reference exists for treating Codex CLI as a provider boundary.",
            "accepted_for": "provider_adapter_reference_only",
        },
        {
            "source_family": "local_mature_open_source",
            "url": r"E:\XINAO_EXTERNAL_MATURE\codex_20260627\awesome_extracted\leonardsellem__codex-subagents-mcp",
            "claim": "Local mature MCP reference exists for subagent delegation through codex exec, but it is not the S runtime owner.",
            "accepted_for": "mcp_subagent_reference_only",
        },
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}.claim_cards.v1",
        "task_id": TASK_ID,
        "status": "external_research_fan_in_ready",
        "cards": cards,
        "source_family_count": len({card["source_family"] for card in cards}),
        "generated_at": now_iso(),
    }


def build_provider_registry(runtime: Path, repo: Path, codex_probe: dict[str, Any]) -> dict[str, Any]:
    phase3 = read_json(output_paths(runtime)["phase3_latest"])
    dp_summary = phase3.get("phase1_payload_summary") if isinstance(phase3.get("phase1_payload_summary"), dict) else {}
    codex_exec_ready = bool(codex_probe.get("installed"))
    codex_sdk_ready = module_available("openai_codex")
    agents_ready = module_available("agents")
    litellm_ready = module_available("litellm")
    temporal_ready = module_available("temporalio")
    qwen_status = qwen_secret_status(runtime)
    local_status = local_ollama_status()
    local_pool_status = local_ollama_pool_status()
    local_ready = local_status.get("ready") is True
    qwen_sdk_ready = module_available("openai")
    qwen_ready = bool(qwen_status.get("api_key_available")) and qwen_sdk_ready
    qwen_blocker = ""
    if not qwen_status.get("api_key_available"):
        qwen_blocker = str(qwen_status.get("named_blocker") or "DASHSCOPE_API_KEY_NOT_CONFIGURED")
    elif not qwen_sdk_ready:
        qwen_blocker = "OPENAI_PYTHON_SDK_NOT_INSTALLED_FOR_DASHSCOPE"
    local_pool_providers = [
        {
            "provider_id": str(item.get("provider_id") or ""),
            "carrier_provider_id": LOCAL_OLLAMA_PROVIDER_ID,
            "role": str(item.get("role") or ""),
            "default": "candidate_when_dynamic_router_scores_local_positive",
            "switchable": True,
            "status": "ready" if item.get("ready") is True else "optional_blocked",
            "installed": bool(item.get("health", {}).get("executable")) if isinstance(item.get("health"), dict) else False,
            "transport": "ollama_local_cli",
            "models": [str(item.get("model") or "")],
            "selected_model": str(item.get("model") or ""),
            "route_roles": item.get("route_roles") or [],
            "modes": item.get("modes") or [],
            "local_only": True,
            "not_search_provider": True,
            "not_primary_code_executor": True,
            "local_first_mandatory": False,
            "dynamic_router_candidate": True,
            "direct_repo_write_allowed": False,
            "outputs_to_staging_only": True,
            "fallback_to": ["qwen_prepaid_cheap_worker", "deepseek_dp", "deepseek_v4_pro"],
            "health": item.get("health") if isinstance(item.get("health"), dict) else {},
            "named_blocker": "",
            "optional_named_blocker": ""
            if item.get("ready") is True
            else str(item.get("health", {}).get("named_blocker") or "LOCAL_OLLAMA_MODEL_NOT_READY")
            if isinstance(item.get("health"), dict)
            else "LOCAL_OLLAMA_MODEL_NOT_READY",
        }
        for item in local_pool_status.get("model_statuses", [])
        if isinstance(item, dict)
    ]
    providers = [
        {
            "provider_id": "codex_exec",
            "role": "brain_route_high_risk_final_acceptance_executor",
            "default": "on_for_brain_acceptance",
            "switchable": True,
            "status": "ready" if codex_exec_ready else "blocked",
            "installed": codex_exec_ready,
            "command": "codex exec --json --sandbox read-only --output-schema <schema> --output-last-message <artifact>",
            "no_window_supported": os.name == "nt",
            "fallback_to": ["codex_sdk", "deepseek_dp"],
            "named_blocker": "" if codex_exec_ready else "CODEX_CLI_NOT_INSTALLED",
        },
        {
            "provider_id": "codex_sdk",
            "role": "long_running_brain_acceptance_worker",
            "default": "on_for_brain_acceptance_when_available",
            "switchable": True,
            "status": "ready" if codex_sdk_ready else "blocked",
            "installed": codex_sdk_ready,
            "python_import": "openai_codex",
            "reuses_codex_auth": True,
            "fallback_to": ["codex_exec", "deepseek_dp"],
            "named_blocker": "" if codex_sdk_ready else "OPENAI_CODEX_SDK_NOT_INSTALLED",
        },
        {
            "provider_id": "codex_mcp_agents",
            "role": "codex_as_tool_or_specialist",
            "default": "on_when_explicit_brain_tool_needed",
            "switchable": True,
            "status": "ready" if agents_ready else "blocked",
            "installed": agents_ready,
            "python_import": "agents",
            "mcp_bridge": "Agents SDK MCPServerStdio + Codex MCP server",
            "fallback_to": ["codex_exec"],
            "named_blocker": "" if agents_ready else "OPENAI_AGENTS_SDK_NOT_INSTALLED",
        },
        {
            "provider_id": "deepseek_dp",
            "role": "deepseek_flash_bulk_staging_worker",
            "default": "on_first_for_bulk_worker_when_token_saving",
            "switchable": True,
            "status": "ready" if int(dp_summary.get("draft_count") or 0) > 0 else "blocked",
            "models": ["deepseek-v4-flash"],
            "draft_count_latest": int(dp_summary.get("draft_count") or 0),
            "staged_count_latest": int(dp_summary.get("staged_count") or 0),
            "merged_count_latest": int(dp_summary.get("merged_count") or 0),
            "primary_bulk_staging_worker": True,
            "direct_repo_write_allowed": False,
            "outputs_to_staging_only": True,
            "fallback_to": ["codex_exec"],
            "named_blocker": "" if int(dp_summary.get("draft_count") or 0) > 0 else "DP_DRAFT_POOL_NOT_RUNNING",
        },
        {
            "provider_id": "deepseek_v4_pro",
            "role": "deepseek_v4_pro_hard_execution_staging_worker",
            "default": "on_first_for_hard_audit_multifile_execution_when_token_saving",
            "switchable": True,
            "status": "ready" if int(dp_summary.get("draft_count") or 0) > 0 else "blocked",
            "models": ["deepseek-v4-pro"],
            "primary_hard_staging_worker": True,
            "deepseek_v4_pro_main_worker_eligible": True,
            "direct_repo_write_allowed": False,
            "outputs_to_staging_only": True,
            "fallback_to": ["deepseek_dp", "qwen_quality_aux_worker", "codex_exec"],
            "named_blocker": "" if int(dp_summary.get("draft_count") or 0) > 0 else "DP_DRAFT_POOL_NOT_RUNNING",
        },
        {
            "provider_id": "qwen_dashscope",
            "role": "prepaid_account_openai_compatible_gateway",
            "default": "on_when_configured",
            "switchable": True,
            "status": "ready" if qwen_ready else "blocked",
            "installed": qwen_sdk_ready,
            "secret_status": qwen_status,
            "transport": "OpenAI-compatible DashScope chat.completions",
            "fallback_to": ["deepseek_dp", "codex_exec"],
            "named_blocker": "" if qwen_ready else qwen_blocker,
        },
        {
            "provider_id": LOCAL_OLLAMA_PROVIDER_ID,
            "role": "legacy_local_ollama_worker_carrier_for_model_pool",
            "default": "candidate_carrier_for_local_pool_not_mandatory_first",
            "switchable": True,
            "status": "ready" if local_ready else "optional_blocked",
            "installed": bool(local_status.get("executable")),
            "transport": "ollama_local_cli",
            "models": [local_status.get("selected_model") or LOCAL_OLLAMA_DEFAULT_MODEL],
            "selected_model": local_status.get("selected_model") or LOCAL_OLLAMA_DEFAULT_MODEL,
            "model_pool_provider_ids": list(LOCAL_OLLAMA_POOL_PROVIDER_IDS),
            "local_pool_status": local_pool_status,
            "local_only": True,
            "not_search_provider": True,
            "not_primary_code_executor": True,
            "local_first_mandatory": False,
            "dynamic_router_candidate": True,
            "direct_repo_write_allowed": False,
            "outputs_to_staging_only": True,
            "fallback_to": ["qwen_prepaid_cheap_worker", "deepseek_dp", "codex_exec"],
            "health": local_status,
            "named_blocker": "",
            "optional_named_blocker": "" if local_ready else str(local_status.get("named_blocker") or "LOCAL_OLLAMA_QWEN_NOT_READY"),
        },
        *local_pool_providers,
        {
            "provider_id": "qwen_prepaid_cheap_worker",
            "role": "prepaid_priority_cheap_draft_extraction_classify_eval_pool",
            "default": "on_first_for_cheap_work",
            "switchable": True,
            "status": "ready" if qwen_ready else "blocked",
            "models": QWEN_CHEAP_MODEL_CANDIDATES,
            "prepaid_priority": True,
            "monthly_burn_target_input": "runtime_private_config_or_env_only",
            "not_primary_code_executor": True,
            "outputs_to_staging_only": True,
            "fallback_to": ["deepseek_dp", "codex_exec"],
            "named_blocker": "" if qwen_ready else qwen_blocker,
        },
        {
            "provider_id": "qwen_code_diversity_worker",
            "role": "code_candidate_diversity_draft_only",
            "default": "on_for_candidate_diversity",
            "switchable": True,
            "status": "ready" if qwen_ready else "blocked",
            "models": QWEN_CODE_DIVERSITY_MODELS,
            "not_primary_code_executor": True,
            "direct_repo_write_allowed": False,
            "outputs_to_staging_only": True,
            "fallback_to": ["codex_exec", "codex_sdk"],
            "named_blocker": "" if qwen_ready else qwen_blocker,
        },
        {
            "provider_id": "qwen_quality_aux_worker",
            "role": "quality_escalation_auxiliary_reasoning",
            "default": "on_for_small_width_escalation",
            "switchable": True,
            "status": "ready" if qwen_ready else "blocked",
            "models": QWEN_QUALITY_MODELS,
            "not_primary_code_executor": True,
            "outputs_to_staging_only": True,
            "fallback_to": ["deepseek_dp", "codex_exec"],
            "named_blocker": "" if qwen_ready else qwen_blocker,
        },
        {
            "provider_id": "search",
            "role": "source_family_research_sourceledger_claimcards",
            "default": "on_for_open_research",
            "switchable": True,
            "status": "foreground_tool_ready",
            "search_provider_order": [
                "exa_api_first_when_configured",
                "serper_api_second_when_configured",
                "free_local_search_sourceledger_searxng_ddgs",
            ],
            "background_note": "search/exa is a source retrieval lane only; models consume SourceLedger/ClaimCards and do not become the search provider",
            "model_consumers": [
                LOCAL_OLLAMA_PROVIDER_ID,
                *LOCAL_OLLAMA_POOL_PROVIDER_IDS,
                "qwen_prepaid_cheap_worker",
                "deepseek_dp",
                "deepseek_v4_pro",
                "codex_exec",
            ],
            "fallback_to": ["free_local_search", "codex_exec"],
            "not_model_worker": True,
            "named_blocker": "",
        },
        {
            "provider_id": LITELLM_ROUTER_PROVIDER_ID,
            "role": "model_gateway",
            "default": "on_for_default_model_gateway",
            "switchable": True,
            "status": "ready" if litellm_ready else "blocked",
            "installed": litellm_ready,
            "routed_by": LITELLM_ROUTED_BY if litellm_ready else "",
            "default_hot_path": litellm_ready,
            "binding_id": P0_004_LITELLM_BINDING_ID,
            "replace_target": P0_004_REPLACE_TARGET,
            "replacement": P0_004_REPLACEMENT,
            "retry_policy": p0_004_binding_retry_policy(),
            "hand_rolled_gateway_default": False,
            "supports": ["load_balance", "queue", "fallback", "cooldown", "timeout", "retry"],
            "named_blocker": "" if litellm_ready else "LITELLM_NOT_INSTALLED",
        },
        {
            "provider_id": "temporal_activity",
            "role": "hidden_background_owner",
            "default": "on",
            "switchable": False,
            "status": "ready" if temporal_ready else "blocked",
            "installed": temporal_ready,
            "task_queue": DEFAULT_TASK_QUEUE,
            "named_blocker": "" if temporal_ready else "TEMPORALIO_NOT_INSTALLED",
        },
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}.provider_registry.v1",
        "task_id": TASK_ID,
        "status": "provider_registry_ready"
        if all(provider["status"] != "blocked" for provider in providers if provider["provider_id"] in {"codex_exec", "codex_sdk", "codex_mcp_agents", "deepseek_dp", "qwen_dashscope", "qwen_prepaid_cheap_worker", "litellm_router", "temporal_activity"})
        else "provider_registry_ready_with_named_blockers",
        "providers": providers,
        "scheduler_controls": [
            "open",
            "close",
            "pause",
            "resume",
            "route",
            "fallback",
            "cooldown",
            "replace",
            "escalate_to_strong_worker",
            "downgrade_to_cheap_draft",
        ],
        "codex_native_execution_default_primary": False,
        "codex_brain_only_default": True,
        "codex_bulk_worker_default_paused": True,
        "dp_is_auxiliary_draft_augmentation": True,
        "dp_is_auxiliary_draft_augmentation_legacy_compat_only": True,
        "deepseek_bulk_staging_default": True,
        "deepseek_v4_pro_hard_execution_default": True,
        "fixed_deepseek_share_target_used": False,
        "deepseek_worker_share_strategy": "dynamic_escalation_after_qwen_when_suitable",
        "codex_supervisor_share_target_max": 0.20,
        "qwen_quota_priority_default": True,
        "local_ollama_pool_status": local_pool_status,
        "local_model_candidate_when_scored": True,
        "local_model_default_first_when_configured": False,
        "local_model_default_scope": "cheap_draft_summary_classify_compress_sanity_audit_staging_only_when_dynamic_router_selects_it",
        "local_first_mandatory": False,
        "search_provider_boundary": "search/exa produces SourceLedger/ClaimCards; local/Qwen/DeepSeek consume search artifacts but do not own search",
        "qwen_prepaid_cheap_worker_default_first": True,
        "qwen_prepaid_cheap_worker_default_first_scope": "cheap_extract_classify_compress_only",
        "completion_claim_allowed": False,
        "generated_at": now_iso(),
    }


def build_executor_adapter(registry: dict[str, Any]) -> dict[str, Any]:
    providers = {item["provider_id"]: item for item in registry.get("providers", []) if isinstance(item, dict)}
    local_stage_pool = [
        provider_id
        for provider_id in LOCAL_OLLAMA_POOL_PROVIDER_IDS
        if providers.get(provider_id, {}).get("status") == "ready"
    ]
    legacy_local_carrier = [LOCAL_OLLAMA_PROVIDER_ID] if providers.get(LOCAL_OLLAMA_PROVIDER_ID, {}).get("status") == "ready" else []
    adapters = {
        "codex_exec": {
            "adapter_role": "brain_route_high_risk_final_acceptance_task",
            "transport": "hidden_subprocess",
            "command_template": "codex exec --json --sandbox <mode> --cd <repo> --output-schema <schema> --output-last-message <artifact> <prompt>",
            "stdout_jsonl": True,
            "stderr_log_artifact": True,
            "windows_no_window": True,
            "enabled": providers.get("codex_exec", {}).get("status") == "ready",
        },
        "codex_sdk": {
            "adapter_role": "long_running_brain_acceptance_worker",
            "transport": "openai_codex_python_sdk",
            "thread_resume_supported": True,
            "enabled": providers.get("codex_sdk", {}).get("status") == "ready",
        },
        "codex_mcp_agents": {
            "adapter_role": "codex_as_mcp_tool_for_agents",
            "transport": "agents.mcp.MCPServerStdio",
            "manager_control_returns_to_supervisor_brain": True,
            "enabled": providers.get("codex_mcp_agents", {}).get("status") == "ready",
        },
        "deepseek_dp": {
            "adapter_role": "deepseek_flash_bulk_staging_execution_pool",
            "transport": "existing_dp_sidecar_execution_provider",
            "models": ["deepseek-v4-flash"],
            "direct_repo_write_allowed": False,
            "outputs_to_staging_only": True,
            "enabled": providers.get("deepseek_dp", {}).get("status") == "ready",
        },
        "deepseek_v4_pro": {
            "adapter_role": "deepseek_v4_pro_hard_multifile_execution_staging_pool",
            "transport": "existing_dp_sidecar_execution_provider",
            "models": ["deepseek-v4-pro"],
            "direct_repo_write_allowed": False,
            "outputs_to_staging_only": True,
            "enabled": providers.get("deepseek_v4_pro", {}).get("status") == "ready",
        },
        LOCAL_OLLAMA_PROVIDER_ID: {
            "adapter_role": "legacy_local_ollama_worker_carrier_for_model_pool",
            "transport": "ollama_local_cli",
            "models": providers.get(LOCAL_OLLAMA_PROVIDER_ID, {}).get("models") or [LOCAL_OLLAMA_DEFAULT_MODEL],
            "outputs_to_staging_only": True,
            "direct_repo_write_allowed": False,
            "can_search_directly": False,
            "local_only": True,
            "local_first_mandatory": False,
            "model_pool_provider_ids": list(LOCAL_OLLAMA_POOL_PROVIDER_IDS),
            "windows_no_window": True,
            "enabled": providers.get(LOCAL_OLLAMA_PROVIDER_ID, {}).get("status") == "ready",
        },
        **{
            provider_id: {
                "adapter_role": providers.get(provider_id, {}).get("role") or "local_ollama_model_pool_candidate",
                "transport": "ollama_local_cli",
                "carrier_provider_id": LOCAL_OLLAMA_PROVIDER_ID,
                "models": providers.get(provider_id, {}).get("models") or [],
                "route_roles": providers.get(provider_id, {}).get("route_roles") or [],
                "outputs_to_staging_only": True,
                "direct_repo_write_allowed": False,
                "can_search_directly": False,
                "local_only": True,
                "local_first_mandatory": False,
                "dynamic_router_candidate": True,
                "windows_no_window": True,
                "enabled": providers.get(provider_id, {}).get("status") == "ready",
            }
            for provider_id in LOCAL_OLLAMA_POOL_PROVIDER_IDS
        },
        "qwen_prepaid_cheap_worker": {
            "adapter_role": "prepaid_priority_draft_extraction_classify_eval_pool",
            "transport": "openai_compatible_dashscope",
            "models": QWEN_CHEAP_MODEL_CANDIDATES,
            "outputs_to_staging_only": True,
            "direct_repo_write_allowed": False,
            "windows_no_window": True,
            "enabled": providers.get("qwen_prepaid_cheap_worker", {}).get("status") == "ready",
        },
        "qwen_code_diversity_worker": {
            "adapter_role": "code_candidate_diversity_staging_only",
            "transport": "openai_compatible_dashscope",
            "models": QWEN_CODE_DIVERSITY_MODELS,
            "outputs_to_staging_only": True,
            "direct_repo_write_allowed": False,
            "enabled": providers.get("qwen_code_diversity_worker", {}).get("status") == "ready",
        },
        "qwen_quality_aux_worker": {
            "adapter_role": "small_width_quality_escalation_auxiliary",
            "transport": "openai_compatible_dashscope",
            "models": QWEN_QUALITY_MODELS,
            "outputs_to_staging_only": True,
            "direct_repo_write_allowed": False,
            "enabled": providers.get("qwen_quality_aux_worker", {}).get("status") == "ready",
        },
    }
    return {
        "schema_version": f"{SCHEMA_VERSION}.executor_adapter.v1",
        "task_id": TASK_ID,
        "status": "executor_adapter_ready",
        "adapters": adapters,
        "default_primary_executor_pool": [],
        "codex_brain_pool": ["codex_exec", "codex_sdk"],
        "default_staging_executor_pool": local_stage_pool + [
            "qwen_prepaid_cheap_worker",
            "deepseek_dp",
            "deepseek_v4_pro",
        ],
        "local_model_worker_pool": local_stage_pool,
        "legacy_local_ollama_carrier_pool": legacy_local_carrier,
        "local_model_candidate_not_mandatory_first": True,
        "deepseek_bulk_worker_pool": ["deepseek_dp"],
        "deepseek_hard_worker_pool": ["deepseek_v4_pro"],
        "aux_draft_worker_pool": local_stage_pool + ["qwen_prepaid_cheap_worker", "deepseek_dp"],
        "code_diversity_worker_pool": ["qwen_code_diversity_worker"],
        "quality_aux_worker_pool": ["deepseek_dp", "deepseek_v4_pro", "qwen_quality_aux_worker"],
        "optional_specialist_tool_pool": ["codex_mcp_agents"],
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }


def build_model_gateway(runtime: Path, registry: dict[str, Any]) -> dict[str, Any]:
    paths = output_paths(runtime)
    config = "\n".join(
        [
            "model_list:",
            "  - model_name: codex-brain-acceptance",
            "    litellm_params:",
            "      model: openai/${XINAO_CODEX_PRIMARY_MODEL:-gpt-5-codex}",
            "      api_key: os.environ/OPENAI_API_KEY",
            "  - model_name: deepseek-draft-augmentation",
            "    litellm_params:",
            "      model: deepseek/${XINAO_DEEPSEEK_DRAFT_MODEL:-deepseek-v4-flash}",
            "      api_key: os.environ/DEEPSEEK_API_KEY",
            "  - model_name: deepseek-quality-escalation",
            "    litellm_params:",
            "      model: deepseek/${XINAO_DEEPSEEK_QUALITY_MODEL:-deepseek-v4-pro}",
            "      api_key: os.environ/DEEPSEEK_API_KEY",
            "  - model_name: local-ollama-qwen3",
            "    litellm_params:",
            "      model: ollama/qwen3:8b",
            "      api_base: os.environ/OLLAMA_BASE_URL",
            "  - model_name: local-ollama-qwen25-coder",
            "    litellm_params:",
            "      model: ollama/qwen2.5-coder:7b",
            "      api_base: os.environ/OLLAMA_BASE_URL",
            "  - model_name: local-ollama-deepseek-r1",
            "    litellm_params:",
            "      model: ollama/deepseek-r1:8b",
            "      api_base: os.environ/OLLAMA_BASE_URL",
            "  - model_name: qwen-prepaid-cheap-worker",
            "    litellm_params:",
            "      model: openai/${XINAO_QWEN_CHEAP_MODEL:-qwen3.6-flash}",
            "      api_base: os.environ/DASHSCOPE_BASE_URL",
            "      api_key: os.environ/DASHSCOPE_API_KEY",
            "  - model_name: qwen-code-diversity-worker",
            "    litellm_params:",
            "      model: openai/${XINAO_QWEN_CODE_DIVERSITY_MODEL:-qwen3-coder-flash}",
            "      api_base: os.environ/DASHSCOPE_BASE_URL",
            "      api_key: os.environ/DASHSCOPE_API_KEY",
            "  - model_name: qwen-quality-aux-worker",
            "    litellm_params:",
            "      model: openai/${XINAO_QWEN_QUALITY_MODEL:-qwen3.7-plus}",
            "      api_base: os.environ/DASHSCOPE_BASE_URL",
            "      api_key: os.environ/DASHSCOPE_API_KEY",
            "router_settings:",
            "  routing_strategy: usage-based-routing-v2",
            "  fallbacks:",
            "    - local-ollama-qwen3: [qwen-prepaid-cheap-worker, deepseek-draft-augmentation]",
            "    - local-ollama-qwen25-coder: [qwen-prepaid-cheap-worker, deepseek-quality-escalation]",
            "    - local-ollama-deepseek-r1: [deepseek-quality-escalation, deepseek-draft-augmentation]",
            "    - qwen-prepaid-cheap-worker: [deepseek-draft-augmentation, deepseek-quality-escalation]",
            "    - qwen-code-diversity-worker: [deepseek-quality-escalation, deepseek-draft-augmentation]",
            "    - qwen-quality-aux-worker: [deepseek-quality-escalation, deepseek-draft-augmentation]",
            "    - deepseek-quality-escalation: [deepseek-draft-augmentation, qwen-quality-aux-worker]",
            "    - codex-brain-acceptance: [deepseek-quality-escalation]",
            "    - deepseek-draft-augmentation: [qwen-prepaid-cheap-worker, deepseek-quality-escalation]",
            "  cooldown_time: 60",
            "  timeout: 120",
            "  num_retries: 2",
            "",
        ]
    )
    write_text(paths["model_gateway_config"], config)
    litellm_ready = any(
        item.get("provider_id") == LITELLM_ROUTER_PROVIDER_ID and item.get("status") == "ready"
        for item in registry.get("providers", [])
        if isinstance(item, dict)
    )
    default_binding = {
        "binding_id": P0_004_LITELLM_BINDING_ID,
        "status": "default_route_bound" if litellm_ready else "default_route_blocked",
        "routed_by": LITELLM_ROUTED_BY if litellm_ready else "",
        "router_provider_id": LITELLM_ROUTER_PROVIDER_ID,
        "replace_target": P0_004_REPLACE_TARGET,
        "replacement": P0_004_REPLACEMENT,
        "default_hot_path": litellm_ready,
        "hand_rolled_gateway_default": False,
        "success_field": "routed_by=litellm",
        "retry_policy": p0_004_binding_retry_policy(),
        "failure_blocker": "" if litellm_ready else "LITELLM_NOT_ON_DEFAULT_PATH",
    }
    route_common = {
        "routed_by": LITELLM_ROUTED_BY if litellm_ready else "",
        "router_provider_id": LITELLM_ROUTER_PROVIDER_ID,
    }
    return {
        "schema_version": f"{SCHEMA_VERSION}.model_gateway.v1",
        "task_id": TASK_ID,
        "gateway": "LiteLLM Router",
        "status": "model_gateway_ready" if litellm_ready else "model_gateway_blocked",
        "binding_id": P0_004_LITELLM_BINDING_ID,
        "routed_by": LITELLM_ROUTED_BY if litellm_ready else "",
        "router_provider_id": LITELLM_ROUTER_PROVIDER_ID,
        "default_route_binding": default_binding,
        "default_hot_path": litellm_ready,
        "hand_rolled_gateway_default": False,
        "replace_target": P0_004_REPLACE_TARGET,
        "replacement": P0_004_REPLACEMENT,
        "config_ref": str(paths["model_gateway_config"]),
        "secret_policy": "repo/runtime evidence stores env var names only, never secret values",
        "routes": [
            {
                **route_common,
                "route_id": "codex-brain-acceptance",
                "providers": ["codex_exec", "codex_sdk"],
                "role": "brain_route_high_risk_final_acceptance_aaq",
            },
            {
                **route_common,
                "route_id": "cheap-draft-augmentation",
                "providers": ["qwen_prepaid_cheap_worker", LOCAL_OLLAMA_QWEN3_PROVIDER_ID, "deepseek_dp"],
                "role": "dynamic_local_or_qwen_cheap_draft_with_deepseek_flash_escalation",
                "local_first_mandatory": False,
            },
            {
                **route_common,
                "route_id": "bulk-staging-execution",
                "providers": [
                    "qwen_prepaid_cheap_worker",
                    LOCAL_OLLAMA_QWEN3_PROVIDER_ID,
                    LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID,
                    "deepseek_dp",
                    "deepseek_v4_pro",
                ],
                "role": "dynamic_local_or_qwen_when_suitable_deepseek_staging_before_codex_acceptance",
                "local_first_mandatory": False,
            },
            {
                **route_common,
                "route_id": "code-candidate-diversity",
                "providers": [LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID, "qwen_code_diversity_worker", "deepseek_v4_pro", "deepseek_dp"],
                "role": "draft_only_code_candidate_diversity",
                "local_first_mandatory": False,
            },
            {
                **route_common,
                "route_id": "quality-aux-escalation",
                "providers": [LOCAL_OLLAMA_DEEPSEEK_R1_PROVIDER_ID, "deepseek_v4_pro", "deepseek_dp", "qwen_quality_aux_worker"],
                "role": "small_width_quality_audit_and_reasoning",
                "local_first_mandatory": False,
            },
            {
                **route_common,
                "route_id": "source-family-research",
                "providers": ["search", LOCAL_OLLAMA_QWEN3_PROVIDER_ID, "qwen_prepaid_cheap_worker", "deepseek_dp"],
                "role": "search_exa_or_sourceledger_then_local_or_qwen_claimcard_draft",
                "local_first_mandatory": False,
            },
        ],
        "router_controls": ["load_balance", "queue", "fallback", "cooldown", "timeout", "retry"],
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }


def reorder_route(route: list[str], preferred: list[Any]) -> list[str]:
    preferred_text = [str(item) for item in preferred if str(item)]
    reordered = [provider for provider in preferred_text if provider in route]
    reordered.extend(provider for provider in route if provider not in reordered)
    return reordered or route


def build_budget_gate(
    runtime: Path,
    strategy_mutation_consumption: dict[str, Any],
    *,
    provider_cost_routing_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spend = read_json(runtime / "state" / "modular_dynamic_worker_pool_phase1" / "spend_ledger" / "latest.json")
    pool = read_json(output_paths(runtime)["phase3_latest"])
    phase1_summary = pool.get("phase1_payload_summary") if isinstance(pool.get("phase1_payload_summary"), dict) else {}
    token_cost_spend = spend.get("token_cost_spend") if isinstance(spend.get("token_cost_spend"), dict) else {}
    if not token_cost_spend:
        token_cost_spend = pool.get("token_cost_spend") if isinstance(pool.get("token_cost_spend"), dict) else {}
    total_tokens = max(
        as_int(token_cost_spend.get("total_tokens")),
        as_int(spend.get("total_tokens")),
        as_int(pool.get("total_tokens")),
    )
    cost_actual = max(
        as_float(spend.get("cost_actual")),
        as_float(spend.get("cost_usd")),
        as_float(token_cost_spend.get("cost_usd")),
        as_float(token_cost_spend.get("estimated_cost_usd")),
        as_float(pool.get("cost_actual")),
    )
    accepted_count = max(
        as_int(spend.get("accepted_artifact_count")),
        as_int(spend.get("AAQ_accepted_delta")),
        as_int(pool.get("accepted_artifact_count")),
        as_int(phase1_summary.get("merged_count")),
    )
    cost_per_accepted = cost_actual / max(1, accepted_count) if cost_actual else 0.0
    mutation_budget = strategy_mutation_consumption.get("budget_gate")
    if not isinstance(mutation_budget, dict):
        mutation_budget = {}
    routing_policy = provider_cost_routing_policy or {}
    effective_mode = str(routing_policy.get("effective_mode") or DEFAULT_PROVIDER_ROUTING_MODE)
    credit_pressure = (
        routing_policy.get("codex_credit_pressure")
        if isinstance(routing_policy.get("codex_credit_pressure"), dict)
        else {}
    )
    token_cost_missing = total_tokens > 0 and cost_actual <= 0.0
    pressure_active = (
        mutation_budget.get("active") is True
        or credit_pressure.get("active") is True
        or token_cost_missing
        or (cost_actual > 0 and accepted_count == 0)
        or cost_per_accepted > DEFAULT_COST_PER_ACCEPTED_ARTIFACT_LIMIT
    )
    brain_only_mode = effective_mode in CODEX_BRAIN_ONLY_MODES
    if brain_only_mode and pressure_active:
        scheduler_action = "limit_codex_only_keep_qwen_dp_dynamic_width"
    elif pressure_active:
        scheduler_action = "reduce_width_pause_low_yield_or_drain"
    elif brain_only_mode:
        scheduler_action = "route_qwen_dp_first_codex_final_only"
    else:
        scheduler_action = "continue_codex_primary_with_cost_metering"
    return {
        "schema_version": f"{SCHEMA_VERSION}.budget_gate.v1",
        "status": "budget_gate_active",
        "active": True,
        "pressure_active": pressure_active,
        "default_enabled": True,
        "provider_cost_routing_mode": effective_mode,
        "default_token_saving_mode": brain_only_mode,
        "codex_brain_only_default": effective_mode == "codex_brain_only",
        "codex_credit_pressure": credit_pressure,
        "total_tokens": total_tokens,
        "cost_actual": cost_actual,
        "cost_catalog_required": True,
        "token_cost_missing": token_cost_missing,
        "token_with_zero_cost_forbidden": True,
        "accepted_artifact_count": accepted_count,
        "cost_per_accepted_artifact": cost_per_accepted,
        "limit": DEFAULT_COST_PER_ACCEPTED_ARTIFACT_LIMIT,
        "scheduler_action": scheduler_action,
        "width_cap_scope": "codex_only"
        if brain_only_mode
        else "global"
        if pressure_active
        else "",
        "qwen_dp_dynamic_width_unlimited": brain_only_mode,
        "pause_lane_class": (
            ["codex_bulk_draft", "codex_long_report", "codex_background_subagent"]
            if brain_only_mode
            else ["cheap_draft", "audit_only", "readback_only"]
            if pressure_active
            else []
        ),
        "max_codex_width_cap": 1 if brain_only_mode or pressure_active else 0,
        "max_qwen_dp_width_cap": 0,
        "max_width_cap": 0 if brain_only_mode else 3 if pressure_active else 0,
        "preferred_worker_order": (
            ["qwen_prepaid_cheap_worker", "deepseek_v4_pro", "deepseek_dp", "codex_exec"]
            if brain_only_mode
            else ["codex_exec", "codex_sdk", "qwen_prepaid_cheap_worker", "deepseek_dp"]
        ),
        "source_refs": [
            str(runtime / "state" / "modular_dynamic_worker_pool_phase1" / "spend_ledger" / "latest.json"),
            str(output_paths(runtime)["phase3_latest"]),
            str(output_paths(runtime)["provider_cost_routing_policy_latest"]),
            str(output_paths(runtime)["provider_price_catalog_latest"]),
        ],
        "not_completion_boundary": True,
    }


def build_scheduler_decision(
    registry: dict[str, Any],
    *,
    strategy_mutation_consumption: dict[str, Any] | None = None,
    budget_gate: dict[str, Any] | None = None,
    provider_cost_routing_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    providers = {item["provider_id"]: item for item in registry.get("providers", []) if isinstance(item, dict)}
    local_candidate_pool = [
        provider_id
        for provider_id in LOCAL_OLLAMA_POOL_PROVIDER_IDS
        if providers.get(provider_id, {}).get("status") == "ready"
    ]
    local_general_pool = [provider_id for provider_id in local_candidate_pool if provider_id == LOCAL_OLLAMA_QWEN3_PROVIDER_ID]
    local_code_pool = [provider_id for provider_id in local_candidate_pool if provider_id == LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID]
    local_audit_pool = [provider_id for provider_id in local_candidate_pool if provider_id == LOCAL_OLLAMA_DEEPSEEK_R1_PROVIDER_ID]
    mutation = strategy_mutation_consumption or {}
    routing_policy = provider_cost_routing_policy or {}
    routing_mode = str(routing_policy.get("effective_mode") or DEFAULT_PROVIDER_ROUTING_MODE)
    brain_only_mode = routing_mode in CODEX_BRAIN_ONLY_MODES
    route_hints = mutation.get("provider_route_hints") if isinstance(mutation.get("provider_route_hints"), dict) else {}
    preferred_order = mutation.get("preferred_provider_order") if isinstance(mutation.get("preferred_provider_order"), list) else []
    litellm_ready = providers.get(LITELLM_ROUTER_PROVIDER_ID, {}).get("status") == "ready"
    model_gateway_binding = {
        "binding_id": P0_004_LITELLM_BINDING_ID,
        "status": "default_route_bound" if litellm_ready else "default_route_blocked",
        "routed_by": LITELLM_ROUTED_BY if litellm_ready else "",
        "router_provider_id": LITELLM_ROUTER_PROVIDER_ID,
        "replace_target": P0_004_REPLACE_TARGET,
        "replacement": P0_004_REPLACEMENT,
        "default_hot_path": litellm_ready,
        "hand_rolled_gateway_default": False,
        "success_decision": "accepted_for_binding",
        "retry_policy": p0_004_binding_retry_policy(),
        "failure_blocker": "" if litellm_ready else "LITELLM_NOT_ON_DEFAULT_PATH",
    }
    if brain_only_mode:
        default_route = [
            "qwen_prepaid_cheap_worker",
            *local_general_pool,
            *local_code_pool,
            *local_audit_pool,
            "deepseek_v4_pro",
            "deepseek_dp",
            "qwen_quality_aux_worker",
            "codex_exec",
            "codex_sdk",
            "codex_mcp_agents",
            "search",
        ]
        route_policy = {
            "engineering_patch_or_test": [
                "qwen_code_diversity_worker",
                "deepseek_v4_pro",
                "deepseek_dp",
            ],
            "final_merge_artifact_acceptance": ["codex_exec", "codex_sdk"],
            "long_running_thread": ["qwen_prepaid_cheap_worker", *local_general_pool, "deepseek_dp", "deepseek_v4_pro"],
            "specialist_tool_delegate": ["qwen_prepaid_cheap_worker", *local_general_pool, "deepseek_dp", "search"],
            "draft_extraction_classify_eval": ["qwen_prepaid_cheap_worker", *local_general_pool, "deepseek_dp", "deepseek_v4_pro"],
            "cheap_parallel_draft": ["qwen_prepaid_cheap_worker", *local_general_pool, "deepseek_dp", "deepseek_v4_pro"],
            "code_candidate_diversity": [
                *local_code_pool,
                "qwen_code_diversity_worker",
                "deepseek_v4_pro",
                "deepseek_dp",
                "qwen_prepaid_cheap_worker",
            ],
            "complex_audit_contradiction_key_plan_review": [
                "deepseek_v4_pro",
                *local_audit_pool,
                "deepseek_dp",
                "qwen_quality_aux_worker",
                "qwen_prepaid_cheap_worker",
            ],
            "source_family_research": ["search", *local_general_pool, "qwen_prepaid_cheap_worker", "deepseek_dp"],
            "codex_brain_decision": ["codex_exec", "codex_sdk"],
            "high_risk_patch_or_repo_mutation": ["codex_exec", "codex_sdk", "deepseek_v4_pro"],
        }
    else:
        default_route = [
            "codex_exec",
            "codex_sdk",
            "codex_mcp_agents",
            "qwen_prepaid_cheap_worker",
            "deepseek_dp",
            "search",
        ]
        route_policy = {
            "engineering_patch_or_test": ["codex_exec", "codex_sdk"],
            "final_merge_artifact_acceptance": ["codex_exec", "codex_sdk"],
            "long_running_thread": ["codex_sdk", "codex_exec"],
            "specialist_tool_delegate": ["codex_mcp_agents", "codex_exec"],
            "draft_extraction_classify_eval": [*local_general_pool, "qwen_prepaid_cheap_worker", "deepseek_dp", "codex_exec"],
            "cheap_parallel_draft": [*local_general_pool, "qwen_prepaid_cheap_worker", "deepseek_dp"],
            "code_candidate_diversity": ["qwen_code_diversity_worker", "codex_exec", "codex_sdk"],
            "complex_audit_contradiction_key_plan_review": [
                "deepseek_dp",
                "qwen_quality_aux_worker",
                "codex_exec",
                "codex_sdk",
            ],
            "source_family_research": ["search", *local_general_pool, "qwen_prepaid_cheap_worker", "deepseek_dp"],
        }
    if mutation.get("strategy_mutation_consumed") is True:
        default_route = reorder_route(default_route, preferred_order)
        for route_key, route in list(route_policy.items()):
            hint = route_hints.get(route_key)
            if isinstance(hint, list) and hint:
                route_policy[route_key] = reorder_route(route, hint)
    if brain_only_mode:
        cheap_extract_first = [
            "qwen_prepaid_cheap_worker",
            *local_general_pool,
            "deepseek_dp",
            "deepseek_v4_pro",
            "qwen_quality_aux_worker",
        ]
        bulk_first = [
            "qwen_prepaid_cheap_worker",
            *local_general_pool,
            *local_code_pool,
            "deepseek_dp",
            "deepseek_v4_pro",
            "qwen_quality_aux_worker",
        ]
        hard_first = [
            "deepseek_v4_pro",
            "deepseek_dp",
            *local_audit_pool,
            "qwen_prepaid_cheap_worker",
            "qwen_quality_aux_worker",
        ]
        code_candidate_first = [
            *local_code_pool,
            "qwen_code_diversity_worker",
            "deepseek_v4_pro",
            "deepseek_dp",
            "qwen_prepaid_cheap_worker",
        ]
        source_research_first = ["search", *local_general_pool, "qwen_prepaid_cheap_worker", "deepseek_dp", "deepseek_v4_pro"]
        default_route = reorder_route(default_route, bulk_first)
        for route_key, route in list(route_policy.items()):
            if route_key in {
                "final_merge_artifact_acceptance",
                "codex_brain_decision",
                "high_risk_patch_or_repo_mutation",
            }:
                continue
            preferred = (
                hard_first
                if route_key == "complex_audit_contradiction_key_plan_review"
                else code_candidate_first
                if route_key in {"engineering_patch_or_test", "code_candidate_diversity"}
                else cheap_extract_first
                if route_key == "draft_extraction_classify_eval"
                else source_research_first
                if route_key == "source_family_research"
                else bulk_first
            )
            route_policy[route_key] = reorder_route(route, preferred)
    budget = budget_gate or {}
    decision: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.scheduler_decision.v1",
        "task_id": TASK_ID,
        "status": "scheduler_decision_ready",
        "default_route": default_route,
        "default_route_binding": model_gateway_binding,
        "model_gateway_binding": model_gateway_binding,
        "routed_by": LITELLM_ROUTED_BY if litellm_ready else "",
        "model_gateway_provider_id": LITELLM_ROUTER_PROVIDER_ID,
        "default_model_gateway": P0_004_REPLACEMENT,
        "hand_rolled_gateway_default": False,
        "p0_004_litellm_default_binding": litellm_ready,
        "route_policy": route_policy,
        "fallback_policy": {
            "codex_exec_failed": ["codex_sdk", "deepseek_dp"],
            "codex_sdk_unavailable": ["codex_exec"],
            "agents_mcp_unavailable": ["codex_exec"],
            "local_ollama_unavailable": ["qwen_prepaid_cheap_worker", "deepseek_dp"],
                "qwen_rate_limited_or_auth_blocked": [*local_general_pool, "deepseek_dp", "codex_exec"],
            "dp_rate_limited": ["qwen_prepaid_cheap_worker", "codex_exec", "search"],
        },
        "active_primary_executor_pool": [
            pid
            for pid in ["codex_exec", "codex_sdk"]
            if not brain_only_mode and providers.get(pid, {}).get("status") == "ready"
        ],
        "active_codex_brain_pool": [
            pid
            for pid in ["codex_exec", "codex_sdk"]
            if providers.get(pid, {}).get("status") == "ready"
        ],
        "active_aux_draft_pool": [
            pid
            for pid in [*LOCAL_OLLAMA_POOL_PROVIDER_IDS, "qwen_prepaid_cheap_worker", "deepseek_dp"]
            if providers.get(pid, {}).get("status") == "ready"
        ],
        "active_local_model_pool": [
            pid for pid in LOCAL_OLLAMA_POOL_PROVIDER_IDS if providers.get(pid, {}).get("status") == "ready"
        ],
        "active_deepseek_bulk_worker_pool": [
            pid for pid in ["deepseek_dp"] if providers.get(pid, {}).get("status") == "ready"
        ],
        "active_deepseek_hard_worker_pool": [
            pid for pid in ["deepseek_v4_pro"] if providers.get(pid, {}).get("status") == "ready"
        ],
        "active_prepaid_cheap_pool": [
            pid for pid in ["qwen_prepaid_cheap_worker"] if providers.get(pid, {}).get("status") == "ready"
        ],
        "active_code_diversity_pool": [
            pid for pid in ["qwen_code_diversity_worker"] if providers.get(pid, {}).get("status") == "ready"
        ],
        "active_quality_aux_pool": [
            pid
            for pid in ["deepseek_dp", "deepseek_v4_pro", "qwen_quality_aux_worker"]
            if providers.get(pid, {}).get("status") == "ready"
        ],
        "active_optional_tool_pool": [
            pid for pid in ["codex_mcp_agents"] if providers.get(pid, {}).get("status") == "ready"
        ],
        "dynamic_width_policy": {
            "target_width_inputs": [
                "independent_task_count",
                "provider_headroom",
                "queue_capacity",
                "fan_in_capacity",
                "budget_remaining",
                "rate_limit",
                "retry_after",
                "qwen_prepaid_remaining",
                "qwen_monthly_burn_target",
            "local_ollama_model_ready",
            "local_ollama_queue_depth",
            "local_ollama_model_switch_cost",
            "semantic_route_class",
            "cost_quality_threshold",
            ],
            "local_model_weight": "candidate_when_score_allows_staging_only_not_mandatory_first",
            "qwen_prepaid_weight": "quota_priority_for_suitable_extract_classify_compress_draft",
            "deepseek_weight": "dynamic_escalation_for_bulk_or_qwen_gap_not_fixed_share",
            "deepseek_v4_pro_weight": "hard_multifile_audit_execution_first_before_codex_acceptance",
            "codex_weight": "brain_only_router_high_risk_judgment_final_merge_aaq",
            "cost_threshold_routing": "RouteLLM_style_cost_quality_thresholds_without_new_control_plane",
            "no_fixed_target_width": True,
            "fixed_deepseek_share_target_used": False,
        },
        "codex_brain_only_budget": {
            "enabled": brain_only_mode,
            "target_codex_share_min": 0.10,
            "target_codex_share_max": 0.20,
            "default_codex_bulk_worker_allowed": False,
            "fixed_deepseek_share_target_used": False,
            "deepseek_worker_share_strategy": "dynamic_escalation_after_qwen_when_suitable",
            "deepseek_default_staging_executor": "deepseek_dp",
            "deepseek_hard_execution_provider": "deepseek_v4_pro",
            "cheap_local_provider": local_general_pool[0] if local_general_pool else "",
            "local_model_candidate_pool": local_candidate_pool,
            "local_model_default_scope": "cheap_draft_summary_classify_compress_sanity_audit_staging_only_when_dynamic_router_selects_it",
            "qwen_default_scope": "cheap_extract_classify_compress_only",
            "codex_allowed_route_keys": [
                "codex_brain_decision",
                "high_risk_patch_or_repo_mutation",
                "final_merge_artifact_acceptance",
            ],
            "cheap_extract_provider": "qwen_prepaid_cheap_worker",
            "bulk_default_provider": "dynamic_qwen_or_local_then_deepseek_dp",
            "quality_escalation_provider": "deepseek_v4_pro",
        },
        "strategy_mutation_consumption": mutation,
        "provider_cost_routing_policy": routing_policy,
        "provider_routing_mode": routing_mode,
        "default_token_saving_worker_route": brain_only_mode,
        "budget_gate": budget,
        "budget_gate_consumed": budget.get("active") is True,
        "provider_route_hints_consumed": mutation.get("strategy_mutation_consumed") is True
        and bool(route_hints),
        "qwen_prepaid_cheap_worker_default_first": True,
        "local_model_candidate_when_scored": True,
        "local_model_default_first_when_configured": False,
        "local_first_mandatory": False,
        "local_model_default_scope": "cheap_draft_summary_classify_compress_sanity_audit_staging_only_when_dynamic_router_selects_it",
        "search_provider_boundary": "search/exa remains retrieval only; local/Qwen/DeepSeek consume search artifacts for draft/audit",
        "qwen_prepaid_cheap_worker_default_first_scope": "cheap_extract_classify_compress_only",
        "deepseek_bulk_staging_default": brain_only_mode,
        "deepseek_v4_pro_hard_execution_default": brain_only_mode,
        "fixed_deepseek_share_target_used": False,
        "deepseek_worker_share_strategy": (
            "dynamic_escalation_after_qwen_when_suitable" if brain_only_mode else ""
        ),
        "codex_supervisor_share_target_max": 0.20 if brain_only_mode else 1.0,
        "dp_not_unique_default_primary": True,
        "codex_native_execution_default_primary": not brain_only_mode,
        "codex_brain_only_default": brain_only_mode,
        "codex_primary_for_final_patch_acceptance": True,
        "codex_bulk_worker_default_paused": brain_only_mode,
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }
    return decision


def build_qwen_prepaid_policy(runtime: Path, scheduler_decision: dict[str, Any]) -> dict[str, Any]:
    secret_status = qwen_secret_status(runtime)
    return {
        "schema_version": f"{SCHEMA_VERSION}.qwen_prepaid_policy.v1",
        "task_id": TASK_ID,
        "status": "qwen_prepaid_policy_ready"
        if secret_status.get("api_key_available")
        else "qwen_prepaid_policy_blocked",
        "memo_ref": str(QWEN_MEMO_REF),
        "secret_status": secret_status,
        "routing_contract": {
            "engineering_patch_test_env_provider_default": [
                "deepseek_v4_pro",
                "deepseek_dp",
                "qwen_code_diversity_worker",
            ],
            "default_worker_route_when_token_saving": [
                "qwen_prepaid_cheap_worker",
                *LOCAL_OLLAMA_POOL_PROVIDER_IDS,
                "deepseek_dp",
                "deepseek_v4_pro",
            ],
            "draft_extraction_classify_eval_default_first": [
                "qwen_prepaid_cheap_worker",
                LOCAL_OLLAMA_QWEN3_PROVIDER_ID,
                "deepseek_dp",
                "deepseek_v4_pro",
            ],
            "code_candidate_diversity": [
                LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID,
                "deepseek_v4_pro",
                "deepseek_dp",
                "qwen_code_diversity_worker",
            ],
            "quality_escalation_small_width": [
                LOCAL_OLLAMA_DEEPSEEK_R1_PROVIDER_ID,
                "deepseek_v4_pro",
                "deepseek_dp",
                "qwen_quality_aux_worker",
            ],
            "codex_brain_only_routes": [
                "codex_brain_decision",
                "high_risk_patch_or_repo_mutation",
                "final_merge_artifact_acceptance",
            ],
            "repo_mutation_acceptance": ["codex_exec", "codex_sdk"],
            "source_research_extract_claimcard": ["search", LOCAL_OLLAMA_QWEN3_PROVIDER_ID, "qwen_prepaid_cheap_worker", "deepseek_dp"],
        },
        "provider_cost_routing_policy": scheduler_decision.get("provider_cost_routing_policy", {}),
        "codex_final_patch_acceptance_only_when_token_saving": (
            scheduler_decision.get("default_token_saving_worker_route") is True
        ),
        "models": {
            "cheap_default_candidates": QWEN_CHEAP_MODEL_CANDIDATES,
            "quality_aux": QWEN_QUALITY_MODELS,
            "code_diversity": QWEN_CODE_DIVERSITY_MODELS,
        },
        "scheduler_inputs": scheduler_decision.get("dynamic_width_policy", {}).get("target_width_inputs", []),
        "outputs_to_staging_only": True,
        "direct_repo_write_allowed": False,
        "not_primary_code_executor": True,
        "local_model_scope": "candidate_when_dynamic_router_scores_local_positive; never mandatory first hop",
        "local_first_mandatory": False,
        "qwen_scope": "cheap_extract_classify_compress_only",
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }


def build_draft_staging(
    *,
    runtime: Path,
    registry: dict[str, Any],
    executor_adapter: dict[str, Any],
    model_gateway: dict[str, Any],
    qwen_prepaid_policy: dict[str, Any],
    invocation: dict[str, Any],
) -> dict[str, Any]:
    items = [
        {
            "artifact_id": "provider_registry",
            "artifact_ref": str(output_paths(runtime)["provider_registry_latest"]),
            "accepted_for": "provider_scheduler_fan_in",
        },
        {
            "artifact_id": "executor_adapter",
            "artifact_ref": str(output_paths(runtime)["executor_adapter_latest"]),
            "accepted_for": "provider_scheduler_fan_in",
        },
        {
            "artifact_id": "model_gateway",
            "artifact_ref": str(output_paths(runtime)["model_gateway_latest"]),
            "accepted_for": "accepted_for_binding",
            "binding_id": P0_004_LITELLM_BINDING_ID,
            "success_decision": "accepted_for_binding",
            "replace_target": P0_004_REPLACE_TARGET,
            "replacement": P0_004_REPLACEMENT,
            "retry_policy": p0_004_binding_retry_policy(),
        },
        {
            "artifact_id": "qwen_prepaid_policy",
            "artifact_ref": str(output_paths(runtime)["qwen_prepaid_policy_latest"]),
            "accepted_for": "prepaid_cheap_worker_scheduler_fan_in",
        },
    ]
    if invocation:
        items.append(
            {
                "artifact_id": "provider_invocation",
                "artifact_ref": str(output_paths(runtime)["provider_invocation_latest"]),
                "accepted_for": "provider_scheduler_fan_in",
            }
        )
    if isinstance(invocation.get("qwen_dashscope"), dict) and invocation.get("qwen_dashscope"):
        items.append(
            {
                "artifact_id": "qwen_invocation",
                "artifact_ref": str(output_paths(runtime)["qwen_invocation_latest"]),
                "accepted_for": "qwen_prepaid_worker_canary_fan_in",
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}.draft_staging.v1",
        "task_id": TASK_ID,
        "status": "draft_staging_ready",
        "staged_count": len(items),
        "items": items,
        "provider_registry_status": registry.get("status"),
        "executor_adapter_status": executor_adapter.get("status"),
        "model_gateway_status": model_gateway.get("status"),
        "qwen_prepaid_policy_status": qwen_prepaid_policy.get("status"),
        "codex_exec_invocation_status": invocation.get("status") if invocation else "not_requested",
        "qwen_invocation_status": invocation.get("qwen_dashscope", {}).get("status")
        if isinstance(invocation.get("qwen_dashscope"), dict)
        else "not_requested",
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }


def render_merge_artifact(payload: dict[str, Any]) -> str:
    registry = payload.get("provider_registry", {})
    gateway = payload.get("model_gateway", {})
    decision = payload.get("scheduler_decision", {})
    invocation = payload.get("provider_invocation", {})
    blockers = payload.get("named_blockers", [])
    routing = payload.get("provider_cost_routing_policy", {})
    qwen_invocation = invocation.get("qwen_dashscope") if isinstance(invocation.get("qwen_dashscope"), dict) else {}
    lines = [
        "# Codex Native ProviderScheduler merge",
        "",
        SENTINEL,
        "",
        f"- task_id: `{TASK_ID}`",
        f"- status: `{payload.get('status')}`",
        f"- primary_executor_pool: `{', '.join(decision.get('active_primary_executor_pool') or [])}`",
        f"- codex_brain_pool: `{', '.join(decision.get('active_codex_brain_pool') or [])}`",
        f"- provider_routing_mode: `{routing.get('effective_mode') or decision.get('provider_routing_mode')}`",
        f"- default_token_saving_worker_route: {payload.get('default_token_saving_worker_route')}",
        f"- model_gateway_binding: `{gateway.get('binding_id')}` routed_by=`{gateway.get('routed_by')}` decision=`{payload.get('artifact_acceptance_decision')}`",
        f"- deepseek_bulk_worker_pool: `{', '.join(decision.get('active_deepseek_bulk_worker_pool') or [])}`",
        f"- deepseek_hard_worker_pool: `{', '.join(decision.get('active_deepseek_hard_worker_pool') or [])}`",
        f"- aux_draft_pool: `{', '.join(decision.get('active_aux_draft_pool') or [])}`",
        f"- local_model_pool: `{', '.join(decision.get('active_local_model_pool') or [])}`",
        f"- prepaid_cheap_pool: `{', '.join(decision.get('active_prepaid_cheap_pool') or [])}`",
        f"- optional_tool_pool: `{', '.join(decision.get('active_optional_tool_pool') or [])}`",
        f"- codex_exec_canary: `{invocation.get('codex_exec', {}).get('status') if isinstance(invocation.get('codex_exec'), dict) else invocation.get('status')}`",
        f"- qwen_dashscope_canary: `{qwen_invocation.get('status') or 'not_requested'}`",
        f"- named_blockers: `{', '.join(blockers)}`",
        "",
        "## Adopted",
        "",
        "- Codex exec / SDK are registered as the brain pool for route decisions, high-risk judgment, final merge, and AAQ.",
        "- Agents SDK / Codex MCP is registered as optional specialist-as-tool lane.",
        "- Local Ollama/Qwen is registered as a cheap draft/summary/classify/compress worker when configured; it is staging-only and not a search provider.",
        "- Qwen/DashScope is registered as the prepaid-priority cheap extraction/classify/compress worker.",
        "- Qwen code lanes provide candidate diversity as staging-only worker output.",
        "- DP/DeepSeek V4 Flash is the default bulk staging worker; DeepSeek V4 Pro is first for hard multifile/audit execution before Codex acceptance.",
        "- LiteLLM Router is the accepted default ModelGateway binding for fallback/cooldown/queueing; P0-004 exits as accepted_for_binding, not next_frontier.",
        "- Failure handling is bounded_delivery_retry: retry the same binding a finite number of times, then write a named blocker instead of opening frontier.",
        "- Temporal hidden activity remains the background owner.",
        "",
        "## Provider Registry",
        "",
    ]
    for provider in registry.get("providers", []) if isinstance(registry.get("providers"), list) else []:
        if isinstance(provider, dict):
            lines.append(
                f"- {provider.get('provider_id')}: status={provider.get('status')} role={provider.get('role')} default={provider.get('default')}"
            )
    lines.extend(["", SENTINEL, ""])
    return "\n".join(lines)


def build_capability_manifest(runtime: Path, payload: dict[str, Any]) -> dict[str, Any]:
    paths = output_paths(runtime)
    return {
        "schema_version": "xinao.capability.manifest.v1",
        "provider_id": "codex_s.provider_scheduler",
        "task_id": TASK_ID,
        "status": "registered",
        "capability_kinds": [
            "provider_scheduler",
            "codex_brain_only_default_router",
            "codex_exec",
            "codex_sdk",
            "codex_mcp_agents",
            "qwen_dashscope_openai_compatible",
            "local_ollama_qwen",
            "qwen_prepaid_cheap_worker",
            "qwen_code_diversity_worker",
            "qwen_quality_aux_worker",
            "deepseek_dp_augmentation",
            "deepseek_v4_pro_quality_escalation",
            "provider_price_catalog",
            "provider_cost_routing_policy",
            "token_saving_worker_route_switch",
            "model_gateway",
            "executor_adapter",
            "temporal_hidden_activity",
        ],
        "invoke": {
            "cli": (
                r".\.venv\Scripts\xinao-seedlab.exe --repo-root "
                r"E:\XINAO_RESEARCH_WORKSPACES\S codex-native-provider-scheduler-phase4"
            ),
            "direct_module": (
                r".\.venv\Scripts\python.exe -m "
                r"services.agent_runtime.codex_native_provider_scheduler_phase4"
            ),
            "temporal_workflow": (
                r".\.venv\Scripts\python.exe -m services.agent_runtime.temporal_codex_task_workflow "
                f"--live-temporal --task-id {TASK_ID} --runtime-root D:/XINAO_RESEARCH_RUNTIME"
            ),
        },
        "latest_ref": str(paths["latest"]),
        "readback_ref": str(paths["readback"]),
        "completion_claim_allowed": False,
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }


def render_readback(payload: dict[str, Any]) -> str:
    decision = payload.get("scheduler_decision", {})
    invocation = payload.get("provider_invocation", {})
    blockers = payload.get("named_blockers", [])
    qwen_invocation = invocation.get("qwen_dashscope") if isinstance(invocation.get("qwen_dashscope"), dict) else {}
    qwen_policy = payload.get("qwen_prepaid_policy", {})
    gateway = payload.get("model_gateway", {}) if isinstance(payload.get("model_gateway"), dict) else {}
    binding_acceptance = (
        payload.get("binding_acceptance")
        if isinstance(payload.get("binding_acceptance"), dict)
        else {}
    )
    mutation = payload.get("strategy_mutation_consumption") if isinstance(payload.get("strategy_mutation_consumption"), dict) else {}
    budget_gate = payload.get("budget_gate") if isinstance(payload.get("budget_gate"), dict) else {}
    routing = payload.get("provider_cost_routing_policy") if isinstance(payload.get("provider_cost_routing_policy"), dict) else {}
    return "\n".join(
        [
            "# Codex native ProviderScheduler phase4 回读",
            "",
            SENTINEL,
            "",
            f"- status: `{payload.get('status')}`",
            f"- codex_native_default_primary: {payload.get('codex_native_default_primary')}",
            f"- codex_brain_only_default: {payload.get('codex_brain_only_default')}",
            f"- codex_bulk_worker_default_paused: {payload.get('codex_bulk_worker_default_paused')}",
            f"- provider_routing_mode: `{routing.get('effective_mode')}`",
            f"- default_token_saving_worker_route: {payload.get('default_token_saving_worker_route')}",
            f"- model_gateway_binding: `{gateway.get('binding_id')}`",
            f"- routed_by: `{gateway.get('routed_by')}`",
            f"- artifact_acceptance_decision: `{binding_acceptance.get('artifact_acceptance_decision') or payload.get('artifact_acceptance_decision')}`",
            f"- next_frontier_default_exit: {payload.get('next_frontier_default_exit')}",
            f"- routing_switch_env: `{routing.get('switch_env')}`",
            f"- primary_executor_pool: `{', '.join(decision.get('active_primary_executor_pool') or [])}`",
            f"- codex_brain_pool: `{', '.join(decision.get('active_codex_brain_pool') or [])}`",
            f"- aux_draft_pool: `{', '.join(decision.get('active_aux_draft_pool') or [])}`",
            f"- local_model_pool: `{', '.join(decision.get('active_local_model_pool') or [])}`",
            f"- qwen_prepaid_cheap_pool: `{', '.join(decision.get('active_prepaid_cheap_pool') or [])}`",
            f"- optional_tool_pool: `{', '.join(decision.get('active_optional_tool_pool') or [])}`",
            f"- codex_exec_canary: `{invocation.get('codex_exec', {}).get('status') if isinstance(invocation.get('codex_exec'), dict) else invocation.get('status')}`",
            f"- qwen_dashscope_canary: `{qwen_invocation.get('status') or 'not_requested'}`",
            f"- qwen_key_source: `{qwen_policy.get('secret_status', {}).get('api_key_source_label') or 'not_configured'}`",
            f"- strategy_mutation_consumed: {mutation.get('strategy_mutation_consumed') is True}",
            f"- budget_gate: `{budget_gate.get('status', 'budget_gate_unknown')}`",
            f"- budget_scheduler_action: `{budget_gate.get('scheduler_action', '')}`",
            f"- named_blockers: `{', '.join(blockers)}`",
            f"- provider_registry: `{payload.get('evidence_refs', {}).get('provider_registry')}`",
            f"- executor_adapter: `{payload.get('evidence_refs', {}).get('executor_adapter')}`",
            f"- model_gateway: `{payload.get('evidence_refs', {}).get('model_gateway')}`",
            f"- temporal_activity: `{payload.get('evidence_refs', {}).get('temporal_activity')}`",
            f"- merge_artifact: `{payload.get('merge_artifact')}`",
            "",
            "## 现在能 invoke 什么",
            "",
            "- `.\\.venv\\Scripts\\xinao-seedlab.exe --repo-root E:\\XINAO_RESEARCH_WORKSPACES\\S codex-native-provider-scheduler-phase4`",
            f"- `.\\.venv\\Scripts\\python.exe -m services.agent_runtime.temporal_codex_task_workflow --live-temporal --task-id {TASK_ID} --runtime-root D:/XINAO_RESEARCH_RUNTIME`",
            "- `codex exec --json --sandbox read-only ...` 只作为脑层决策/高风险判断/最终 AAQ 验收入口",
            "- `openai_codex` Python SDK 只作为长任务脑层/验收 worker",
            "- `agents` + MCPServerStdio 作为 Codex-as-tool lane",
            "- `local_ollama_qwen3` / `qwen3:8b` 作为本地便宜草稿、摘要、分类、压缩候选 worker；不直接搜索、不写 repo，只进 staging/fan-in",
            "- `local_ollama_qwen25_coder` / `qwen2.5-coder:7b` 作为本地代码候选 worker；`local_ollama_deepseek_r1` / `deepseek-r1:8b` 作为本地反驳/小审计候选 worker",
            "- `Qwen/DashScope OpenAI-compatible` 作为预付费优先 cheap draft/extraction/classify/eval 工人池",
            "- 默认省 token worker 路由：Qwen 先跑 bulk/draft/extract/classify/cheap eval，本地模型按 router score/resource state 做候选补充，DeepSeek V4 Pro 处理复杂审计/多文件计划/关键矛盾，Codex 保留 10-20% 脑层决策/高风险合并/AAQ。",
            "- P0-004 默认 ModelGateway 绑定验收：`accepted_for_binding`；默认出口不是 `next_frontier`。",
            "",
            "## 边界",
            "",
            "- 这不是完成声明；它是 ProviderScheduler 能力注册、真实/阻塞调用证据和 fan-in merge。",
            "- Qwen/千问只负责低成本草稿、抽取、分类、低风险评估和候选多样性；输出必须进 staging/fan-in。",
            "- search/Exa 只负责检索 SourceLedger/ClaimCard；本地模型、Qwen、DeepSeek 只是消费搜索结果，不把搜索冒充执行进展。",
            "- Codex 默认不做 bulk worker；需要 repo mutation 时先走候选/审计 staging，再由 Codex 做最终接受。",
            "- DP/DeepSeek 是质量升级层，不是唯一默认主控。",
            "- 所有后台执行必须走 hidden/no-window/Temporal activity 形态。",
            "",
            SENTINEL,
            "",
        ]
    )


def run_provider_scheduler(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "codex-native-provider-scheduler-phase4-wave-001",
    invoke_codex_exec: bool = True,
    codex_exec_timeout_seconds: int = 180,
    invoke_qwen: bool = True,
    qwen_timeout_seconds: int = 60,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    claim_cards = external_research_claim_cards()
    codex_probe = codex_version(runtime, repo)
    registry = build_provider_registry(runtime, repo, codex_probe)
    executor_adapter = build_executor_adapter(registry)
    model_gateway = build_model_gateway(runtime, registry)
    strategy_mutation = progress_self_evolution.load_active_strategy_mutation(runtime)
    strategy_mutation_consumption = progress_self_evolution.scheduler_consumption_from_mutation(strategy_mutation)
    provider_cost_routing_policy = load_provider_cost_routing_policy(runtime)
    provider_price_catalog = price_catalog_payload()
    budget_gate = build_budget_gate(
        runtime,
        strategy_mutation_consumption,
        provider_cost_routing_policy=provider_cost_routing_policy,
    )
    scheduler_decision = build_scheduler_decision(
        registry,
        strategy_mutation_consumption=strategy_mutation_consumption,
        budget_gate=budget_gate,
        provider_cost_routing_policy=provider_cost_routing_policy,
    )
    qwen_prepaid_policy = build_qwen_prepaid_policy(runtime, scheduler_decision)
    invocation: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.provider_invocation.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "provider_invocation_not_requested",
        "codex_exec": {},
        "qwen_dashscope": {},
        "generated_at": now_iso(),
        "not_completion_boundary": True,
    }
    if invoke_codex_exec:
        codex_exec = invoke_codex_exec_canary(
            runtime,
            repo,
            timeout_seconds=codex_exec_timeout_seconds,
        )
        invocation["codex_exec"] = codex_exec
        invocation["status"] = "provider_invocation_ready" if codex_exec.get("succeeded") else "provider_invocation_blocked"
    else:
        invocation["codex_exec"] = read_codex_exec_cached_canary(runtime)
    if invoke_qwen:
        qwen_invocation = invoke_qwen_canary(runtime, timeout_seconds=qwen_timeout_seconds)
        invocation["qwen_dashscope"] = qwen_invocation
        if qwen_invocation.get("succeeded"):
            invocation["status"] = "provider_invocation_ready"
        else:
            invocation["status"] = "provider_invocation_blocked"
    if invoke_codex_exec and invoke_qwen:
        codex_ok = invocation.get("codex_exec", {}).get("succeeded") is True
        qwen_ok = invocation.get("qwen_dashscope", {}).get("succeeded") is True
        invocation["status"] = "provider_invocation_ready" if codex_ok and qwen_ok else "provider_invocation_blocked"
    draft_staging = build_draft_staging(
        runtime=runtime,
        registry=registry,
        executor_adapter=executor_adapter,
        model_gateway=model_gateway,
        qwen_prepaid_policy=qwen_prepaid_policy,
        invocation=invocation,
    )
    blockers = [
        provider.get("named_blocker")
        for provider in registry.get("providers", [])
        if isinstance(provider, dict) and provider.get("named_blocker")
    ]
    codex_exec_invocation = invocation.get("codex_exec") if isinstance(invocation.get("codex_exec"), dict) else {}
    qwen_invocation = invocation.get("qwen_dashscope") if isinstance(invocation.get("qwen_dashscope"), dict) else {}
    if invoke_codex_exec and codex_exec_invocation and not codex_exec_invocation.get("succeeded"):
        blockers.append(str(codex_exec_invocation.get("named_blocker") or "CODEX_EXEC_CANARY_FAILED_OR_AUTH_BLOCKED"))
    if invoke_qwen and qwen_invocation and not qwen_invocation.get("succeeded"):
        blockers.append(str(qwen_invocation.get("named_blocker") or "QWEN_DASHSCOPE_OPENAI_COMPATIBLE_INVOKE_FAILED"))
    route_policy = (
        scheduler_decision.get("route_policy")
        if isinstance(scheduler_decision.get("route_policy"), dict)
        else {}
    )
    ready_local_model_ids = [
        str(provider.get("provider_id") or "")
        for provider in registry.get("providers", [])
        if isinstance(provider, dict)
        and str(provider.get("provider_id") or "") in LOCAL_OLLAMA_POOL_PROVIDER_IDS
        and provider.get("status") == "ready"
    ]
    local_model_ready = bool(ready_local_model_ids)
    local_general_ready = any(
        provider.get("provider_id") == LOCAL_OLLAMA_QWEN3_PROVIDER_ID and provider.get("status") == "ready"
        for provider in registry.get("providers", [])
        if isinstance(provider, dict)
    )
    qwen_then_local_cheap_prefix = ["qwen_prepaid_cheap_worker"] + (
        [LOCAL_OLLAMA_QWEN3_PROVIDER_ID] if local_general_ready else []
    )
    draft_route = route_policy.get("draft_extraction_classify_eval", [])
    cheap_route = route_policy.get("cheap_parallel_draft", [])
    source_route = route_policy.get("source_family_research", [])
    brain_budget = (
        scheduler_decision.get("codex_brain_only_budget")
        if isinstance(scheduler_decision.get("codex_brain_only_budget"), dict)
        else {}
    )
    codex_brain_only_default = provider_cost_routing_policy.get("effective_mode") in CODEX_BRAIN_ONLY_MODES
    codex_allowed_route_keys = set(brain_budget.get("codex_allowed_route_keys") or [])
    codex_provider_ids = {"codex_exec", "codex_sdk", "codex_mcp_agents"}
    codex_on_disallowed_routes = [
        route_key
        for route_key, route in route_policy.items()
        if route_key not in codex_allowed_route_keys
        and isinstance(route, list)
        and any(str(provider_id) in codex_provider_ids for provider_id in route)
    ]
    model_gateway_routes = (
        model_gateway.get("routes")
        if isinstance(model_gateway.get("routes"), list)
        else []
    )
    codex_on_disallowed_gateway_routes = [
        str(route.get("route_id") or "")
        for route in model_gateway_routes
        if isinstance(route, dict)
        and route.get("route_id") != "codex-brain-acceptance"
        and any(str(provider_id) in codex_provider_ids for provider_id in route.get("providers", []))
    ]
    model_gateway_binding = (
        model_gateway.get("default_route_binding")
        if isinstance(model_gateway.get("default_route_binding"), dict)
        else {}
    )
    litellm_default_bound = (
        model_gateway.get("status") == "model_gateway_ready"
        and model_gateway.get("binding_id") == P0_004_LITELLM_BINDING_ID
        and model_gateway.get("routed_by") == LITELLM_ROUTED_BY
        and model_gateway.get("router_provider_id") == LITELLM_ROUTER_PROVIDER_ID
        and model_gateway.get("default_hot_path") is True
        and model_gateway.get("hand_rolled_gateway_default") is False
        and model_gateway_binding.get("status") == "default_route_bound"
        and model_gateway_binding.get("routed_by") == LITELLM_ROUTED_BY
        and model_gateway_binding.get("success_field") == "routed_by=litellm"
        and scheduler_decision.get("model_gateway_binding", {}).get("success_decision")
        == "accepted_for_binding"
        and scheduler_decision.get("p0_004_litellm_default_binding") is True
    )
    retry_policy = (
        model_gateway_binding.get("retry_policy")
        if isinstance(model_gateway_binding.get("retry_policy"), dict)
        else {}
    )
    bounded_retry_policy_ready = (
        retry_policy.get("policy_id") == "bounded_delivery_retry"
        and retry_policy.get("scope") == "same_deliverable_binding_only"
        and retry_policy.get("max_attempts") == P0_004_BINDING_MAX_ATTEMPTS
        and retry_policy.get("max_recursive_repairs") == P0_004_BINDING_MAX_RECURSIVE_REPAIRS
        and retry_policy.get("retry_same_deliverable_on_failure") is True
        and retry_policy.get("continue_to_next_task_only_after") == "accepted_for_binding"
        and retry_policy.get("failure_terminal_blocker")
        == P0_004_BINDING_RETRY_EXHAUSTED_BLOCKER
        and retry_policy.get("next_frontier_on_failure") is False
        and retry_policy.get("empty_retry_forbidden") is True
    )
    checks = {
        "claim_cards_multiple_source_families": int(claim_cards.get("source_family_count") or 0) >= 4,
        "codex_exec_registered_brain_ready": any(
            provider.get("provider_id") == "codex_exec"
            and provider.get("default") == "on_for_brain_acceptance"
            and provider.get("status") == "ready"
            for provider in registry.get("providers", [])
            if isinstance(provider, dict)
        ),
        "codex_sdk_registered": any(
            provider.get("provider_id") == "codex_sdk" and provider.get("status") == "ready"
            for provider in registry.get("providers", [])
            if isinstance(provider, dict)
        ),
        "agents_sdk_registered": any(
            provider.get("provider_id") == "codex_mcp_agents" and provider.get("status") == "ready"
            for provider in registry.get("providers", [])
            if isinstance(provider, dict)
        ),
        "qwen_prepaid_cheap_worker_registered_ready": any(
            provider.get("provider_id") == "qwen_prepaid_cheap_worker" and provider.get("status") == "ready"
            for provider in registry.get("providers", [])
            if isinstance(provider, dict)
        ),
        "local_ollama_pool_optional_or_registered": (
            not local_model_ready
            or all(
                provider.get("status") == "ready"
                and provider.get("outputs_to_staging_only") is True
                and provider.get("direct_repo_write_allowed") is False
                and provider.get("not_search_provider") is True
                and provider.get("local_first_mandatory") is False
                for provider in registry.get("providers", [])
                if isinstance(provider, dict)
                and str(provider.get("provider_id") or "") in ready_local_model_ids
            )
        ),
        "qwen_prepaid_first_for_cheap_extract_scope": (
            draft_route[: len(qwen_then_local_cheap_prefix)] == qwen_then_local_cheap_prefix
            and scheduler_decision.get("qwen_prepaid_cheap_worker_default_first_scope")
            == "cheap_extract_classify_compress_only"
        ),
        "local_model_candidate_not_mandatory_first": (
            scheduler_decision.get("local_model_candidate_when_scored") is True
            and scheduler_decision.get("local_model_default_first_when_configured") is False
            and scheduler_decision.get("local_first_mandatory") is False
            and all(
                executor_adapter.get("adapters", {}).get(provider_id, {}).get("outputs_to_staging_only")
                is True
                for provider_id in ready_local_model_ids
            )
        ),
        "search_provider_boundary_not_model_worker": (
            source_route[:1] == ["search"]
            and all(
                provider_id not in source_route[:1]
                for provider_id in [
                    LOCAL_OLLAMA_PROVIDER_ID,
                    *LOCAL_OLLAMA_POOL_PROVIDER_IDS,
                    "qwen_prepaid_cheap_worker",
                    "deepseek_dp",
                    "deepseek_v4_pro",
                ]
            )
            and any(
                provider.get("provider_id") == "search"
                and provider.get("not_model_worker") is True
                and "exa_api_first_when_configured" in (provider.get("search_provider_order") or [])
                for provider in registry.get("providers", [])
                if isinstance(provider, dict)
            )
        ),
        "qwen_outputs_staging_only": executor_adapter.get("adapters", {})
        .get("qwen_prepaid_cheap_worker", {})
        .get("outputs_to_staging_only")
        is True,
        "dp_legacy_aux_flag_compat_only": registry.get(
            "dp_is_auxiliary_draft_augmentation_legacy_compat_only"
        )
        is True,
        "model_gateway_ready": model_gateway.get("status") == "model_gateway_ready",
        "p0_004_litellm_default_binding_bound": litellm_default_bound,
        "p0_004_bounded_retry_policy_ready": bounded_retry_policy_ready,
        "executor_adapter_ready": executor_adapter.get("status") == "executor_adapter_ready",
        "staging_written": int(draft_staging.get("staged_count") or 0) >= 5,
        "codex_exec_canary_or_named_blocker": True
        if not invoke_codex_exec
        else bool(codex_exec_invocation.get("succeeded") or codex_exec_invocation.get("named_blocker")),
        "qwen_canary_or_named_blocker": True
        if not invoke_qwen
        else bool(qwen_invocation.get("succeeded") or qwen_invocation.get("named_blocker")),
        "strategy_mutation_consumed_when_active": (
            strategy_mutation_consumption.get("strategy_mutation_consumed") is not True
            or scheduler_decision.get("strategy_mutation_consumption", {}).get("strategy_mutation_consumed") is True
        ),
        "budget_gate_has_scheduler_action": (
            budget_gate.get("active") is not True
            or scheduler_decision.get("budget_gate", {}).get("scheduler_action") in {
                "reduce_width_pause_low_yield_or_drain",
                "limit_codex_only_keep_qwen_dp_dynamic_width",
                "route_qwen_dp_first_codex_final_only",
                "continue_codex_primary_with_cost_metering",
            }
        ),
        "provider_cost_routing_policy_ready": (
            provider_cost_routing_policy.get("status")
            == "provider_cost_routing_policy_ready"
            and provider_cost_routing_policy.get("effective_mode") in PROVIDER_ROUTING_MODES
        ),
        "default_token_saving_switch_available": (
            (
                provider_cost_routing_policy.get("qwen_dp_first_global_default") is True
                or provider_cost_routing_policy.get("codex_brain_only_global_default") is True
            )
            and provider_cost_routing_policy.get("codex_primary_switch_available") is True
        ),
        "codex_brain_only_global_default_ready": (
            provider_cost_routing_policy.get("default_mode") == "codex_brain_only"
            and provider_cost_routing_policy.get("effective_mode") == "codex_brain_only"
            and provider_cost_routing_policy.get("codex_brain_only_global_default") is True
        ),
        "codex_bulk_worker_paused_default": (
            scheduler_decision.get("codex_bulk_worker_default_paused") is True
            and scheduler_decision.get("active_primary_executor_pool") == []
            and "codex_exec" in scheduler_decision.get("active_codex_brain_pool", [])
            and "codex_sdk" in scheduler_decision.get("active_codex_brain_pool", [])
        ),
        "codex_route_partition_brain_only": not codex_on_disallowed_routes,
        "model_gateway_codex_partition_brain_only": not codex_on_disallowed_gateway_routes,
        "model_gateway_routes_routed_by_litellm": all(
            isinstance(route, dict)
            and route.get("routed_by") == LITELLM_ROUTED_BY
            and route.get("router_provider_id") == LITELLM_ROUTER_PROVIDER_ID
            for route in model_gateway_routes
        ),
        "codex_brain_target_share_10_20": (
            brain_budget.get("enabled") is True
            and brain_budget.get("target_codex_share_min") == 0.10
            and brain_budget.get("target_codex_share_max") == 0.20
            and brain_budget.get("default_codex_bulk_worker_allowed") is False
        ),
        "qwen_first_for_cheap_extract_classify_eval_only": (
            draft_route[: len(qwen_then_local_cheap_prefix)] == qwen_then_local_cheap_prefix
            and cheap_route[: len(qwen_then_local_cheap_prefix)] == qwen_then_local_cheap_prefix
            and route_policy.get("engineering_patch_or_test", [""])[0]
            in {LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID, "qwen_code_diversity_worker"}
        ),
        "deepseek_dynamic_escalation_before_codex_without_fixed_share": (
            scheduler_decision.get("deepseek_bulk_staging_default") is True
            and scheduler_decision.get("fixed_deepseek_share_target_used") is False
            and brain_budget.get("fixed_deepseek_share_target_used") is False
            and brain_budget.get("deepseek_worker_share_strategy")
            == "dynamic_escalation_after_qwen_when_suitable"
            and cheap_route[: len(qwen_then_local_cheap_prefix)] == qwen_then_local_cheap_prefix
            and route_policy.get("engineering_patch_or_test", [""])[0]
            in {LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID, "qwen_code_diversity_worker"}
            and route_policy.get("code_candidate_diversity", [""])[0]
            in {LOCAL_OLLAMA_QWEN_CODER_PROVIDER_ID, "qwen_code_diversity_worker"}
            and route_policy.get("complex_audit_contradiction_key_plan_review", [""])[0]
            == "deepseek_v4_pro"
        ),
        "deepseek_v4_pro_hard_execution_before_codex": (
            route_policy.get("complex_audit_contradiction_key_plan_review", [""])[0]
            == "deepseek_v4_pro"
            and not any(
                provider_id in route_policy.get("complex_audit_contradiction_key_plan_review", [])
                for provider_id in ["codex_exec", "codex_sdk", "codex_mcp_agents"]
            )
        ),
        "provider_price_catalog_ready": (
            provider_price_catalog.get("status") == "provider_price_catalog_ready"
        ),
        "deepseek_v4_pro_quality_route_visible": (
            scheduler_decision.get("route_policy", {})
            .get("complex_audit_contradiction_key_plan_review", [""])[0]
            == "deepseek_v4_pro"
        ),
    }
    artifact_acceptance_decision = (
        "accepted_for_binding" if litellm_default_bound else "named_blocker"
    )
    binding_named_blocker = "" if litellm_default_bound else "LITELLM_NOT_ON_DEFAULT_PATH"
    if binding_named_blocker:
        blockers.append(binding_named_blocker)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "codex_native_provider_scheduler_ready"
        if all(checks.values()) and not blockers
        else "codex_native_provider_scheduler_ready_with_named_blockers",
        "desktop_memo_ref": str(DESKTOP_MEMO_REF),
        "qwen_memo_ref": str(QWEN_MEMO_REF),
        "external_research": claim_cards,
        "provider_registry": registry,
        "executor_adapter": executor_adapter,
        "model_gateway": model_gateway,
        "binding_acceptance": {
            "binding_id": P0_004_LITELLM_BINDING_ID,
            "accepted_for": "accepted_for_binding",
            "artifact_acceptance_decision": artifact_acceptance_decision,
            "replace_target": P0_004_REPLACE_TARGET,
            "replacement": P0_004_REPLACEMENT,
            "success_field": "routed_by=litellm",
            "named_blocker": binding_named_blocker,
            "next_frontier_default_exit": False,
            "retry_policy": p0_004_binding_retry_policy(),
        },
        "scheduler_decision": scheduler_decision,
        "qwen_prepaid_policy": qwen_prepaid_policy,
        "provider_invocation": invocation,
        "draft_staging": draft_staging,
        "strategy_mutation_consumption": strategy_mutation_consumption,
        "provider_price_catalog": provider_price_catalog,
        "provider_cost_routing_policy": provider_cost_routing_policy,
        "budget_gate": budget_gate,
        "codex_native_default_primary": not codex_brain_only_default,
        "codex_brain_only_default": codex_brain_only_default,
        "codex_bulk_worker_default_paused": scheduler_decision.get("codex_bulk_worker_default_paused") is True,
        "codex_brain_only_budget": brain_budget,
        "default_token_saving_worker_route": (
            scheduler_decision.get("default_token_saving_worker_route") is True
        ),
        "codex_primary_switch_available": True,
        "dp_deepseek_aux_parallel_draft": True,
        "dp_deepseek_aux_parallel_draft_legacy_compat_only": True,
        "deepseek_bulk_staging_default": scheduler_decision.get("deepseek_bulk_staging_default") is True,
        "deepseek_v4_pro_hard_execution_default": (
            scheduler_decision.get("deepseek_v4_pro_hard_execution_default") is True
        ),
        "fixed_deepseek_share_target_used": scheduler_decision.get("fixed_deepseek_share_target_used")
        is True,
        "deepseek_worker_share_strategy": scheduler_decision.get("deepseek_worker_share_strategy") or "",
        "codex_supervisor_share_target_max": scheduler_decision.get("codex_supervisor_share_target_max"),
        "local_model_candidate_when_scored": scheduler_decision.get("local_model_candidate_when_scored") is True,
        "local_model_default_first_when_configured": scheduler_decision.get("local_model_default_first_when_configured") is True,
        "local_first_mandatory": scheduler_decision.get("local_first_mandatory") is True,
        "local_ollama_pool_provider_ids": list(LOCAL_OLLAMA_POOL_PROVIDER_IDS),
        "local_model_default_scope": scheduler_decision.get("local_model_default_scope") or "",
        "search_provider_boundary": scheduler_decision.get("search_provider_boundary") or "",
        "qwen_prepaid_cheap_worker_default_first": True,
        "qwen_prepaid_cheap_worker_default_first_scope": "cheap_extract_classify_compress_only",
        "artifact_acceptance_decision": artifact_acceptance_decision,
        "accepted_for": "accepted_for_binding",
        "next_frontier_default_exit": False,
        "p0_004_litellm_default_binding": litellm_default_bound,
        "named_blockers": sorted(set(item for item in blockers if item)),
        "completion_claim_allowed": False,
        "not_completion_boundary": True,
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()},
        "generated_at": now_iso(),
    }
    merge_path = paths["records"] / f"{safe_stem(wave_id)}.provider_scheduler_merge.md"
    payload["merge_artifact"] = str(merge_path)
    payload["evidence_refs"] = {
        "latest": str(paths["latest"]),
        "claim_cards": str(paths["claim_cards_latest"]),
        "provider_registry": str(paths["provider_registry_latest"]),
        "executor_adapter": str(paths["executor_adapter_latest"]),
        "model_gateway": str(paths["model_gateway_latest"]),
        "scheduler_decision": str(paths["scheduler_decision_latest"]),
        "qwen_prepaid_policy": str(paths["qwen_prepaid_policy_latest"]),
        "provider_price_catalog": str(paths["provider_price_catalog_latest"]),
        "provider_cost_routing_policy": str(paths["provider_cost_routing_policy_latest"]),
        "provider_invocation": str(paths["provider_invocation_latest"]),
        "qwen_invocation": str(paths["qwen_invocation_latest"]),
        "draft_staging": str(paths["draft_staging_latest"]),
        "merge_consumer": str(paths["merge_consumer_latest"]),
        "temporal_activity": str(paths["temporal_activity_latest"]),
        "readback": str(paths["readback"]),
        "capability_manifest": str(paths["capability_manifest"]),
    }
    merge_consumer = {
        "schema_version": f"{SCHEMA_VERSION}.merge_consumer.v1",
        "task_id": TASK_ID,
        "status": "merge_consumer_ready",
        "merged_count": 1,
        "merge_artifact": str(merge_path),
        "adopted_artifacts": draft_staging.get("items") or [],
        "rejected_artifacts": [],
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }
    payload["merge_consumer"] = merge_consumer
    manifest = build_capability_manifest(runtime, payload)
    if write:
        write_json(paths["claim_cards_latest"], claim_cards)
        write_json(paths["provider_registry_latest"], registry)
        write_json(paths["executor_adapter_latest"], executor_adapter)
        write_json(paths["model_gateway_latest"], model_gateway)
        write_json(paths["scheduler_decision_latest"], scheduler_decision)
        write_json(paths["qwen_prepaid_policy_latest"], qwen_prepaid_policy)
        write_json(paths["provider_price_catalog_latest"], provider_price_catalog)
        write_json(paths["provider_cost_routing_policy_latest"], provider_cost_routing_policy)
        write_json(paths["qwen_invocation_latest"], invocation.get("qwen_dashscope") or {})
        write_json(paths["provider_invocation_latest"], invocation)
        write_json(paths["draft_staging_latest"], draft_staging)
        write_json(paths["merge_consumer_latest"], merge_consumer)
        write_text(merge_path, render_merge_artifact(payload))
        write_json(paths["capability_manifest"], manifest)
        write_json(paths["latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.latest.json", payload)
        write_text(paths["readback"], render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wave-id", default="codex-native-provider-scheduler-phase4-wave-001")
    parser.add_argument("--skip-codex-exec-canary", action="store_true")
    parser.add_argument("--codex-exec-timeout-seconds", type=int, default=180)
    parser.add_argument("--skip-qwen-canary", action="store_true")
    parser.add_argument("--qwen-timeout-seconds", type=int, default=60)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = run_provider_scheduler(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        wave_id=args.wave_id,
        invoke_codex_exec=not args.skip_codex_exec_canary,
        codex_exec_timeout_seconds=args.codex_exec_timeout_seconds,
        invoke_qwen=not args.skip_qwen_canary,
        qwen_timeout_seconds=args.qwen_timeout_seconds,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
