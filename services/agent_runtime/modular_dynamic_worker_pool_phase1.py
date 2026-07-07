from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from services.agent_runtime import task_package_resolver as task_package
from services.agent_runtime.provider_price_catalog import (
    estimate_usage_cost,
    price_catalog_payload,
)

SCHEMA_VERSION = "xinao.codex_s.modular_dynamic_worker_pool_phase1.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_MODULAR_DYNAMIC_WORKER_POOL_PHASE1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
TASK_ID = "modular_dynamic_worker_pool_phase1_20260704"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DESKTOP_MEMO_REF = Path(
    r"C:\Users\xx363\Desktop\新系统\备用历史\Codex_DeepSeek_高并行草稿主脑合并模式_20260704.txt"
)
DESKTOP_MEMO_FALLBACK_REFS = (
    Path(
        r"C:\Users\xx363\Desktop\新系统\已经完成的历史备用\Codex_DeepSeek_高并行草稿主脑合并模式_20260704.txt"
    ),
    Path(r"C:\Users\xx363\Desktop\新系统\当前源文本增量_20260704.txt"),
)
SOURCE_ENTRY_ROOT = Path(r"C:\Users\xx363\Desktop\新系统")
TASK_PACKAGE_MANIFEST_NAMES = (
    "TASK_PACKAGE.json",
    "task_package.json",
    "datapackage.json",
)
CURRENT_INTENT_PACKAGE_REF = (
    r"C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"
    r"\intent_packages\grok_faithful_modular_dynamic_worker_pool_20260704.json"
)
ASSIGNMENT_DAG_NODE_ID = "parallel_draft_batch_bind"
LATEST_USER_CORRECTION_TASK_ID = "foreground_brain_dp_worker_pool_correction_20260704"
LATEST_USER_CORRECTION_DIGEST_POINTS = [
    "333 is the highest semantic line; phase1/same_default/productivity/latest cannot replace it.",
    "C:\\Users\\xx363\\Desktop\\新系统 is the changing source entry; read/sample it each wave.",
    "Foreground Codex brain owns understanding, split, dispatch, fan-in merge, correction, and next wave.",
    "same_default_loop is only a background runner/engine, never task owner or completion boundary.",
    "DP/DeepSeek is a draft worker pool; draft_count>0, staging, and human-readable merge are required.",
]
GLOBAL_DEFAULT_ENFORCED_SCOPE = "seed_cortex_global_default_modular_dynamic_worker_pool_phase1"
PARENT_SAME_DEFAULT_RUNTIME_SCOPE = "seed_cortex_parent_overnight_same_default_phase1_loop"
PHASE2_QUEUE_CONSUMER_RUNTIME_SCOPE = "seed_cortex_loop_runtime_state_supervisor_worker_pool_phase2"
PHASE3_TEMPORAL_ACTIVITY_RUNTIME_SCOPE = (
    "seed_cortex_temporal_activity_no_window_dp_worker_pool_phase3"
)
ALLOWED_RUNTIME_ENFORCED_SCOPES = {
    GLOBAL_DEFAULT_ENFORCED_SCOPE,
    PARENT_SAME_DEFAULT_RUNTIME_SCOPE,
    PHASE2_QUEUE_CONSUMER_RUNTIME_SCOPE,
    PHASE3_TEMPORAL_ACTIVITY_RUNTIME_SCOPE,
}
GLOBAL_DEFAULT_ADOPTION_STATE = "runtime_enforced_global_default"
GLOBAL_DEFAULT_BLOCKED_ADOPTION_STATE = "global_default_candidate_blocked"
PROVIDER_SCHEDULER_TASK_ID = "codex_native_provider_scheduler_phase4_20260704"
PROVIDER_SCHEDULER_CAPABILITY_ID = "codex_s.provider_scheduler"
FOREGROUND_BRAIN_REQUIRED_FIELDS = [
    "source_entry_read_at",
    "user_latest_correction_digest",
    "333_alignment",
    "current_frontier",
    "worker_briefs_generated",
    "why_this_width",
    "draft_artifacts_consumed",
    "merge_decision",
    "next_wave_decision",
    "blocker_or_continue_reason",
]
BACKGROUND_RUNNER_DOWNGRADE_FLAGS = {
    "background_runner_only": True,
    "not_foreground_brain": True,
    "not_task_owner": True,
    "not_completion_boundary": True,
    "requires_foreground_brain_fanin": True,
}
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
NON_DRAFT_ORDER = ("eval", "contradiction", "audit", "extraction", "citation_verify")
PARALLEL_DRAFT_POOL_CONTRACT = "parallel_draft_pool"
CONTROL_PLANE_REPAIR_CONTRACT = "control_plane_repair"
CONTROL_PLANE_REPAIR_NODE_TOKENS = (
    "heartbeat",
    "control_plane",
    "liveness",
    "watch",
    "result_wait",
    "readback",
    "blocker",
    "repair",
)
CONTROL_PLANE_REPAIR_MATURE_SOURCES = [
    {
        "source": "Temporal Activity failure detection",
        "url": "https://docs.temporal.io/encyclopedia/detecting-activity-failures",
        "claim": "Heartbeats and timeouts detect activity failure and drive retry; they are not the business repair artifact.",
    },
    {
        "source": "Kubernetes controllers",
        "url": "https://kubernetes.io/docs/concepts/architecture/controller/",
        "claim": "A controller observes current state and changes it toward desired state.",
    },
    {
        "source": "Kubebuilder reconciliation good practices",
        "url": "https://book.kubebuilder.io/reference/good-practices.html",
        "claim": "Reconciliation loops should be idempotent and keep synchronizing until desired state is reached.",
    },
    {
        "source": "Argo Workflows retries",
        "url": "https://argo-workflows.readthedocs.io/en/latest/retries/",
        "claim": "Retry policy and expressions decide retry after a failed attempt, instead of blind polling.",
    },
    {
        "source": "LangGraph interrupts",
        "url": "https://docs.langchain.com/oss/python/langgraph/interrupts",
        "claim": "Interrupt/resume persists state and makes pause/resume explicit control flow.",
    },
]
SUCCESS_STATUSES = {"draft_ready", "model_ready", "search_ready"}
LOCAL_OLLAMA_WORKER_PROVIDER_ID = "local_ollama_qwen"
QWEN_CHEAP_WORKER_PROVIDER_ID = "qwen_prepaid_cheap_worker"
QWEN_QUALITY_WORKER_PROVIDER_ID = "qwen_quality_aux_worker"
QWEN_DASHSCOPE_PROVIDER_ID = "qwen_dashscope"
DEEPSEEK_DP_PROVIDER_ID = "legacy.deepseek_dp_sidecar"
DEEPSEEK_DP_ROUTE_ID = "deepseek_dp"
CODEX_EXEC_PROVIDER_ID = "codex_exec"
CHEAP_QWEN_FIRST_MODES = {"draft", "extraction", "eval"}
QWEN_QUALITY_MODES = {"audit", "contradiction"}
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
EXTERNAL_DRAFT_PROVIDER_IDS = {
    DEEPSEEK_DP_PROVIDER_ID,
    QWEN_CHEAP_WORKER_PROVIDER_ID,
    QWEN_QUALITY_WORKER_PROVIDER_ID,
}
LOCAL_STUB_PROVIDER_PREFIXES = ("seed_cortex.local_",)
REAL_WORKER_PROVIDER_IDS = {
    QWEN_CHEAP_WORKER_PROVIDER_ID,
    QWEN_QUALITY_WORKER_PROVIDER_ID,
    DEEPSEEK_DP_PROVIDER_ID,
    DEEPSEEK_DP_ROUTE_ID,
    CODEX_EXEC_PROVIDER_ID,
}
HARD_ACCEPTANCE_FIELDS = [
    "target_width",
    "actual_dispatched_width",
    "actual_completed_width",
    "draft_count",
    "eval_count",
    "audit_count",
    "staged_count",
    "merged_count",
    "provider_tier_usage",
    "token_cost_spend",
    "rate_limit_error",
    "named_blocker",
]
MUST_DO_10 = [
    "BrainProvider schema: Codex S is supervisor brain and final merge owner",
    "WorkerProvider schema: DP is a draft-heavy worker pool, not second brain",
    "ModelGateway route schema: draft first, search/provider_probe not main task",
    "ExecutorAdapter schema: every lane invokes dp_sidecar_execution_port",
    "WorkerBrief schema: each worker receives mode/objective/input/write targets",
    "DraftStagingQueue: draft artifacts are staged before merge",
    "SpendLedger: every lane records usage/spend entry",
    "DynamicWidthPolicy: target width >= 3 and draft is dominant",
    "MergeConsumer: staged drafts produce one merged output artifact",
    "WidthBlocker: insufficient width or missing artifacts become named blockers",
]
WAVE_STEPS_8 = [
    "supervisor reads intent/source/runtime/ledger/staging/headroom/spend",
    "supervisor generates frontier/DAG/worker briefs/target_width/mode_counts/routing",
    "durable workflow dispatches activities",
    "worker pool executes draft/eval/contradiction/audit/extraction/citation_verify",
    "worker outputs artifact/draft/claim/confidence/risk/usage/blocker",
    "fan-in reducer writes staging queue, lineage, and spend ledger",
    "supervisor merge writes merged artifact/readback/next_wave",
    "continue unless stop/user-only/hard risk/named blocker/task accepted",
]


DpInvoker = Callable[..., dict[str, Any]]
QwenInvoker = Callable[..., dict[str, Any]]
CodexInvoker = Callable[..., dict[str, Any]]


def classify_provider_result(result: dict[str, Any]) -> str:
    selected = str(result.get("selected_carrier_provider_id") or "")
    if result.get("local_stub") is True or selected.startswith(LOCAL_STUB_PROVIDER_PREFIXES):
        return "local_stub"
    if (
        result.get("status") == "succeeded"
        and result.get("provider_invocation_performed") is True
        and result.get("model_invocation_performed") is True
        and selected in REAL_WORKER_PROVIDER_IDS
        and bool(result.get("provider_invocation_ref"))
    ):
        return "real_remote_model"
    if result.get("tool_invocation_performed") is True or result.get("mode") in {
        "provider_probe",
        "search",
    }:
        return "tool_diagnostic"
    return "unknown"


def is_real_remote_model_result(result: dict[str, Any]) -> bool:
    return classify_provider_result(result) == "real_remote_model"


def is_local_stub_result(result: dict[str, Any]) -> bool:
    return classify_provider_result(result) == "local_stub"


def is_tool_diagnostic_result(result: dict[str, Any]) -> bool:
    return classify_provider_result(result) == "tool_diagnostic"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    last_error: OSError | None = None
    for attempt in range(12):
        temporary = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.{attempt}.tmp"
        )
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)
            return
        except OSError as exc:
            last_error = exc
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
            time.sleep(0.03 * (attempt + 1))
    if last_error is not None:
        raise last_error


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: OSError | None = None
    for attempt in range(12):
        temporary = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.{attempt}.tmp"
        )
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)
            return
        except OSError as exc:
            last_error = exc
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
            time.sleep(0.03 * (attempt + 1))
    if last_error is not None:
        raise last_error


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def read_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def safe_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
    cleaned = cleaned.strip("-") or "wave"
    if len(cleaned) <= 120:
        return cleaned
    digest = hashlib.sha256(cleaned.encode("utf-8", errors="replace")).hexdigest()[:16]
    prefix = cleaned[:103].rstrip("-_") or "wave"
    return f"{prefix}-{digest}"


def wave_digest_stem(wave_id: str) -> str:
    return f"mdwp-{hashlib.sha256(wave_id.encode('utf-8')).hexdigest()[:16]}"


def gateway_meter_usage(
    *,
    input_text: str,
    output_text: str,
    observed_usage: dict[str, Any],
    provider_model: str,
    provider_tier: str,
    latency_ms: int,
) -> dict[str, Any]:
    prompt_tokens = int(
        observed_usage.get("prompt_tokens")
        or observed_usage.get("input_tokens")
        or max(1, math.ceil(len(input_text) / 4))
    )
    completion_tokens = int(
        observed_usage.get("completion_tokens")
        or observed_usage.get("output_tokens")
        or max(1, math.ceil(len(output_text) / 4))
    )
    total_tokens = int(observed_usage.get("total_tokens") or prompt_tokens + completion_tokens)
    input_rate = float(
        os.environ.get("XINAO_MODEL_GATEWAY_INPUT_USD_PER_1M")
        or os.environ.get("XINAO_DEEPSEEK_INPUT_USD_PER_1M")
        or 0.0
    )
    output_rate = float(
        os.environ.get("XINAO_MODEL_GATEWAY_OUTPUT_USD_PER_1M")
        or os.environ.get("XINAO_DEEPSEEK_OUTPUT_USD_PER_1M")
        or 0.0
    )
    provider_cost = observed_usage.get("cost") or observed_usage.get("cost_usd")
    try:
        provider_cost_float = float(provider_cost) if provider_cost not in (None, "") else None
    except (TypeError, ValueError):
        provider_cost_float = None
    estimated = estimate_usage_cost(
        provider=provider_tier,
        model=provider_model,
        provider_tier=provider_tier,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_hit_tokens=int(
            observed_usage.get("cache_hit_tokens") or observed_usage.get("cached_input_tokens") or 0
        ),
        observed_cost_usd=provider_cost_float,
    )
    if (
        estimated.get("price_catalog_applied") is not True
        and not provider_cost_float
        and (input_rate > 0 or output_rate > 0)
    ):
        env_rate_cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
        estimated = {
            **estimated,
            "cost_usd": round(env_rate_cost, 10),
            "estimated_cost_usd": round(env_rate_cost, 10),
            "cost_source": "gateway_env_rate",
            "input_cost_usd": round(prompt_tokens * input_rate / 1_000_000, 10),
            "output_cost_usd": round(completion_tokens * output_rate / 1_000_000, 10),
            "input_rate_usd_per_1m": input_rate,
            "output_rate_usd_per_1m": output_rate,
        }
    provider_usage_observed = bool(observed_usage)
    source = (
        estimated.get("cost_source")
        if estimated.get("price_catalog_applied")
        else "provider_usage"
        if provider_usage_observed
        else "gateway_deterministic_io_meter"
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "metered_usage_observed": True,
        "provider_usage_observed": provider_usage_observed,
        "gateway_metered_usage": True,
        "estimated_usage": False,
        "cost_usd": float(estimated.get("cost_usd") or 0.0),
        "estimated_cost_usd": float(estimated.get("estimated_cost_usd") or 0.0),
        "cost_source": source,
        "metering_source": source,
        "input_rate_usd_per_1m": input_rate,
        "output_rate_usd_per_1m": output_rate,
        **estimated,
        "provider_model": provider_model,
        "provider_tier": provider_tier,
        "latency_ms": latency_ms,
    }


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "modular_dynamic_worker_pool_phase1"
    return {
        "state": state,
        "latest": state / "latest.json",
        "records": state / "records",
        "brain_provider_latest": runtime / "state" / "brain_provider" / "latest.json",
        "worker_provider_latest": runtime / "state" / "worker_provider" / "latest.json",
        "model_gateway_route_latest": runtime / "state" / "model_gateway_route" / "latest.json",
        "executor_adapter_latest": runtime / "state" / "executor_adapter" / "latest.json",
        "worker_brief_latest": runtime / "state" / "worker_brief" / "latest.json",
        "foreground_brain_decision_latest": state / "foreground_brain_decision" / "latest.json",
        "draft_staging_latest": state / "draft_staging_queue" / "latest.json",
        "merge_consumer_latest": state / "merge_consumer" / "latest.json",
        "merge_artifacts": state / "merge_artifacts",
        "spend_ledger_latest": state / "spend_ledger" / "latest.json",
        "dynamic_width_policy_latest": runtime / "state" / "dynamic_width_policy" / "latest.json",
        "width_blocker_latest": runtime / "state" / "width_blocker" / "latest.json",
        "trigger_binding_latest": state / "trigger_binding" / "latest.json",
        "watchdog_downgrade_latest": state / "watchdog_downgrade" / "latest.json",
        "worker_assignment": runtime / "state" / "worker_assignment" / f"{TASK_ID}.json",
        "global_worker_assignment": (runtime / "state" / "worker_assignment" / f"{WORK_ID}.json"),
        "parallel_draft_batch_dir": runtime / "state" / "parallel_draft_batch",
        "parallel_draft_batch_latest": runtime / "state" / "parallel_draft_batch" / "latest.json",
        "assignment_dag_node_evidence_dir": (
            runtime / "state" / "task_bound_evidence" / WORK_ID / "assignment_dag"
        ),
        "phase_boundary_dir": (
            runtime / "state" / "task_bound_evidence" / WORK_ID / "phase_boundary"
        ),
        "fan_in_staging_merge_spend_dir": state / "fan_in_staging_merge_spend",
        "fan_in_staging_merge_spend_latest": state / "fan_in_staging_merge_spend" / "latest.json",
        "fan_in_staging_merge_spend_jsonl": (
            state / "fan_in_staging_merge_spend" / "fan_in_staging_merge_spend.jsonl"
        ),
        "blocker_repair_escalation_latest": (
            runtime / "state" / "blocker_repair_escalation" / "latest.json"
        ),
        "blocker_repair_escalation_records": (
            runtime / "state" / "blocker_repair_escalation" / "records"
        ),
        "default_route_binding_latest": state / "default_route_binding" / "latest.json",
        "global_default_latest": state / "global_default" / "latest.json",
        "while_chain_latest": state / "while_chain" / "latest.json",
        "while_chain_records": state / "while_chain" / "records",
        "global_default_readback": (
            runtime
            / "readback"
            / "zh"
            / "modular_dynamic_worker_pool_phase1_global_default_20260704.md"
        ),
        "capability_manifest": (
            runtime
            / "capabilities"
            / "codex_s.modular_dynamic_worker_pool_phase1"
            / "manifest.json"
        ),
        "parallel_draft_capability_manifest": (
            runtime / "capabilities" / "legacy.deepseek_dp_sidecar.parallel_draft" / "manifest.json"
        ),
        "cheap_worker_pool_capability_manifest": (
            runtime
            / "capabilities"
            / "codex_s.modular_cheap_worker_pool.parallel_draft"
            / "manifest.json"
        ),
        "capability_invoke_latest": (
            runtime
            / "capabilities"
            / "codex_s.modular_dynamic_worker_pool_phase1"
            / "invoke_evidence"
            / "latest.json"
        ),
        "readback": (
            runtime / "readback" / "zh" / "modular_dynamic_worker_pool_phase1_20260704.md"
        ),
    }


def s_venv_python(repo: Path = DEFAULT_REPO) -> Path:
    canonical = DEFAULT_REPO / ".venv" / "Scripts" / "python.exe"
    if canonical.is_file():
        return canonical
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


def resolve_desktop_memo_ref() -> Path:
    if DESKTOP_MEMO_REF.is_file():
        return DESKTOP_MEMO_REF
    for candidate in DESKTOP_MEMO_FALLBACK_REFS:
        if candidate.is_file():
            return candidate
    return DESKTOP_MEMO_REF


def mode_counts_for_width(target_width: int) -> dict[str, int]:
    width = max(4, int(target_width or 4))
    counts = {mode: 0 for mode in MODE_ORDER}
    counts["search_assist"] = 0
    if width >= 20:
        base = {
            "draft": 12,
            "extraction": 2,
            "contradiction": 2,
            "eval": 2,
            "audit": 1,
            "citation_verify": 1,
        }
        counts.update(base)
        remaining = width - sum(base.values())
        growth_order = (
            "draft",
            "eval",
            "extraction",
            "contradiction",
            "audit",
            "citation_verify",
            "search_assist",
        )
        index = 0
        while remaining > 0:
            mode = growth_order[index % len(growth_order)]
            if mode == "draft" and counts[mode] >= 30:
                index += 1
                continue
            if mode == "search_assist" and counts[mode] >= 6:
                index += 1
                continue
            counts[mode] += 1
            remaining -= 1
            index += 1
        counts["search"] = 0
        counts["provider_probe"] = 0
        return counts
    counts["eval"] = 1
    counts["audit"] = 1
    draft_count = max(2, math.ceil(width * 0.6))
    if width >= 12:
        draft_count = max(7, draft_count)
    draft_count = min(draft_count, width - 2)
    counts["draft"] = draft_count
    remaining = width - draft_count - 2
    support_growth_order = ("contradiction", "extraction", "citation_verify", "eval", "audit")
    index = 0
    while remaining > 0:
        mode = support_growth_order[index % len(support_growth_order)]
        counts[mode] += 1
        remaining -= 1
        index += 1
    counts["search"] = 0
    counts["provider_probe"] = 0
    return counts


def memo_facts() -> dict[str, Any]:
    memo_ref = resolve_desktop_memo_ref()
    raw = memo_ref.read_bytes() if memo_ref.is_file() else b""
    text = raw.decode("utf-8", errors="replace") if raw else ""
    return {
        "path": str(memo_ref),
        "configured_path": str(DESKTOP_MEMO_REF),
        "fallback_paths": [str(item) for item in DESKTOP_MEMO_FALLBACK_REFS],
        "exists": memo_ref.is_file(),
        "line_count": len(text.splitlines()) if text else 0,
        "char_count": len(text) if text else 0,
        "sha256": hashlib.sha256(raw).hexdigest() if raw else "",
        "read_in_full_before_assignment": bool(raw),
    }


def load_work_package_arg(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text:
        return {}
    if not text.startswith("{"):
        path = Path(text)
        if path.is_file():
            text = path.read_text(encoding="utf-8-sig")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("--work-package-json must be a JSON object")
    return payload


def latest_user_correction_digest() -> dict[str, Any]:
    payload = {
        "task_id": LATEST_USER_CORRECTION_TASK_ID,
        "source": "current_user_visible_correction_package",
        "digest_points": LATEST_USER_CORRECTION_DIGEST_POINTS,
        "received_by": "Codex S foreground brain",
        "serves": "333 foreground brain + DP draft worker pool correction",
    }
    return {
        **payload,
        "sha256": sha256_json(payload),
    }


def source_entry_file_priority(path: Path, mtime: float) -> tuple[int, float, str]:
    name = path.name
    if name == "XINAO_333_固定锚点.txt":
        return (0, -mtime, name)
    if name == task_package.LEGACY_AUTHORITY_FILES[0]:
        return (1, -mtime, name)
    return (2, -mtime, name)


def read_task_package_manifest(root: Path) -> tuple[Path | None, dict[str, Any]]:
    manifest_path = task_package.explicit_manifest_path(root)
    if manifest_path is None:
        return None, {}
    return manifest_path, task_package.read_json(manifest_path)


def manifest_resource_paths(root: Path, manifest: dict[str, Any]) -> list[Path]:
    return task_package.manifest_resource_paths(root, manifest)


def scan_source_entry(
    *,
    root: Path = SOURCE_ENTRY_ROOT,
    max_files: int = 16,
    excerpt_chars: int = 1200,
) -> dict[str, Any]:
    package = task_package.resolve_task_package(root)
    sampled_files: list[dict[str, Any]] = []
    for item in package.get("sampled_files", [])[: max(1, int(max_files or 1))]:
        path = Path(str(item.get("path") or ""))
        stat = path.stat() if path.is_file() else None
        text = path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else ""
        sampled_files.append(
            {
                **item,
                "mtime_epoch": float(stat.st_mtime) if stat else 0.0,
                "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(stat.st_mtime))
                if stat
                else "",
                "excerpt": text[:excerpt_chars] if text else "",
            }
        )
    package["source_entry_root"] = str(root)
    package["source_entry_read_at"] = package.get("read_at")
    package["exists"] = root.is_dir()
    package["is_directory"] = root.is_dir()
    package["file_count"] = len(sampled_files)
    package["sampled_count"] = len(sampled_files)
    package["sampled_files"] = sampled_files
    package["dynamic_source_entry"] = True
    return package


def derive_dynamic_target_width(
    *,
    source_entry: dict[str, Any],
    latest_correction: dict[str, Any],
) -> int:
    sampled_count = max(1, int(source_entry.get("sampled_count") or 0))
    correction_points = latest_correction.get("digest_points")
    correction_count = len(correction_points) if isinstance(correction_points, list) else 1
    # Bootstrap width only. Temporal phase3 replaces this with provider/executor telemetry.
    # Four lanes are the smallest honest default wave: draft stays primary while eval
    # and side-audit lanes are both present.
    return max(4, sampled_count + max(1, correction_count))


def build_dynamic_width_policy(
    *,
    runtime: Path,
    wave_id: str,
    target_width: int,
    mode_counts: dict[str, int],
    actual_dispatched_width: int = 0,
    actual_completed_width: int = 0,
    width_decision: dict[str, Any] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    width = sum(int(value or 0) for value in mode_counts.values())
    decision = width_decision if isinstance(width_decision, dict) else {}
    target_width_source = str(
        decision.get("target_width_source") or "dynamic_width_scheduler_not_provided"
    )
    width_decision_reason = str(
        decision.get("width_decision_reason")
        or "no upstream DynamicWidthScheduler decision was provided"
    )
    payload = {
        "schema_version": "xinao.codex_s.dynamic_width_policy.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "dynamic_width_policy_ready",
        "policy_id": "modular_dynamic_worker_pool_phase1.dynamic_width_scheduler",
        "target_width": width,
        "requested_target_width": target_width,
        "target_width_source": target_width_source,
        "width_decision_reason": width_decision_reason,
        "width_decision_inputs": decision.get("width_decision_inputs") or {},
        "width_candidates": decision.get("width_candidates") or {},
        "operator_cap_applied": decision.get("operator_cap_applied") is True,
        "recomputed_each_wave": decision.get("recomputed_each_wave") is True,
        "fixed_width_literal_used": decision.get("fixed_20_or_50_used") is True,
        "not_default_width": True,
        "not_permanent_cap": True,
        "capacity_observation_required_for_future_higher_width": True,
        "actual_dispatched_width": actual_dispatched_width,
        "actual_completed_width": actual_completed_width,
        "mode_counts": mode_counts,
        "formula": (
            "min(independent_task_count, provider_available_slots, executor_available_slots, "
            "budget_headroom, rate_limit_headroom, useful_frontier_count, operator_safety_cap)"
        ),
        "drivers": [
            "frontier_decomposability",
            "provider_headroom",
            "task_value",
            "cost_token_budget",
            "rate_limit",
            "queue_backlog",
            "fan_in_backlog",
            "merge_bandwidth",
            "failure_rate",
            "expected_marginal_gain",
        ],
        "guidance_not_hardcode": {
            "draft": "12-30 for large cheap worker pool waves",
            "extraction": "4-8",
            "contradiction": "2-6",
            "eval": "4-8",
            "audit": "2-4",
            "search_assist": "0-6, support lane only",
            "citation_verify": "1-3",
            "provider_probe": "0-1, never progress",
        },
        "fan_in_backlog_limits_acceptance_not_dispatch": True,
        "width_one_requires_named_blocker": True,
        "fixed_20_or_50_used": (
            width in {20, 50}
            and target_width_source
            not in {
                "dynamic_width_scheduler",
                "dynamic_width_scheduler_with_operator_cap",
                "modular_phase1_bootstrap_dynamic_width",
            }
        ),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["dynamic_width_policy_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.dynamic_width_policy.json", payload)
    return payload


def build_provider_schemas(runtime: Path) -> dict[str, Any]:
    provider_context = load_provider_route_context(runtime)
    return {
        "brain_provider_schema": {
            "schema_version": "xinao.codex_s.brain_provider.v1",
            "provider_id": "codex_s.supervisor_brain",
            "current_binding": "Codex S",
            "provider_role": "SupervisorBrainProvider",
            "role": "supervisor_brain_planner_dispatcher_merge_owner",
            "final_writer": True,
            "current_provider_is_replaceable": True,
            "future_provider_candidates": [
                "DeepSeek Pro",
                "Codex Pro",
                "OpenAI Agents manager",
                "LangGraph supervisor node",
            ],
            "dp_is_second_brain": False,
            "qwen_first_can_override_supervisor_brain": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
        "worker_provider_schema": {
            "schema_version": "xinao.codex_s.worker_provider.v1",
            "provider_id": "modular_dynamic_cheap_worker_pool",
            "current_binding": "Qwen prepaid cheap worker first for cheap modes; DeepSeek/DP sidecar fallback and quality supplement",
            "provider_role": "CheapWorkerProvider",
            "role": "draft_main_worker_pool",
            "default_primary_mode": "draft",
            "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
            "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
            "qwen_prepaid_cheap_worker": {
                "provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
                "status": "ready"
                if provider_context.get("qwen_prepaid_cheap_worker_ready")
                else "blocked_or_not_refreshed",
                "default": "first_for_draft_extraction_classify_low_risk_eval",
                "model": provider_context.get("qwen_selected_model") or "qwen3.6-flash",
                "policy_ref": provider_context.get("qwen_prepaid_policy_ref"),
                "invocation_ref": provider_context.get("qwen_invocation_ref"),
                "outputs_to_staging_only": True,
                "direct_repo_write_allowed": False,
            },
            "deepseek_dp": {
                "provider_id": DEEPSEEK_DP_PROVIDER_ID,
                "role": "cheap draft fallback, parallel supplement, contradiction/audit support",
                "outputs_to_staging_only": True,
                "direct_repo_write_allowed": False,
            },
            "supported_modes": [
                "draft",
                "eval",
                "audit",
                "extraction",
                "contradiction",
                "search_assist",
                "citation_verify",
            ],
            "not_final_owner": True,
            "not_source_owner": True,
            "not_second_brain": True,
            "future_provider_candidates": [
                "DeepSeek Pro",
                "Qwen",
                "local model",
                "vLLM",
                "OpenRouter",
                "OpenAI-compatible provider",
                "Batch API",
            ],
            "local_stub_counts_as_real_dp": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
        "model_gateway_route_schema": {
            "schema_version": "xinao.codex_s.model_gateway_route.v1",
            "gateway_id": "seed_cortex.model_gateway.phase1",
            "gateway_role": "ModelGatewayPort",
            "route_policy": "provider_neutral_qwen_prepaid_cheap_first_then_deepseek_dp_fallback",
            "default_routes": {
                "engineering_patch_test_env_provider": "codex_exec -> codex_sdk",
                "draft": "qwen_prepaid_cheap_worker -> DeepSeek/DP -> Codex",
                "extraction": "qwen_prepaid_cheap_worker -> DeepSeek/DP -> Codex",
                "classify": "qwen_prepaid_cheap_worker -> DeepSeek/DP -> Codex",
                "eval": "qwen_prepaid_cheap_worker -> DeepSeek/DP -> Codex for low-risk eval",
                "contradiction": "DeepSeek/DP quality lane -> Qwen plus/max -> Codex",
                "audit": "DeepSeek/DP quality lane -> Qwen plus/max -> Codex",
                "citation_verify": "dp_sidecar_execution_port -> local eval/model carrier",
            },
            "qwen_prepaid_cheap_worker_default_first": provider_context.get(
                "qwen_prepaid_cheap_worker_default_first"
            )
            is True,
            "qwen_prepaid_cheap_worker_ready": provider_context.get(
                "qwen_prepaid_cheap_worker_ready"
            )
            is True,
            "qwen_prepaid_policy_ref": provider_context.get("qwen_prepaid_policy_ref"),
            "qwen_invocation_ref": provider_context.get("qwen_invocation_ref"),
            "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
            "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
            "fallback_allowed_reasons": sorted(QWEN_FALLBACK_ALLOWED_REASONS),
            "required_accounting_fields": [
                "provider",
                "model",
                "provider_tier",
                "token",
                "cost",
                "latency",
                "task_type",
                "fallback",
                "result_quality",
            ],
            "search_is_main_task": False,
            "provider_probe_used_as_progress": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
        "executor_adapter_schema": {
            "schema_version": "xinao.codex_s.executor_adapter.v1",
            "adapter_id": "services.agent_runtime.modular_dynamic_worker_pool_phase1.provider_gateway_lane",
            "adapter_role": "ExecutorAdapterPort",
            "callable": "invoke_lane_with_provider_route",
            "runtime_root": str(runtime),
            "lane_contract": "mode/objective/input_text -> provider_payload/result_path",
            "engineering_execution_default": ["codex_exec", "codex_sdk"],
            "qwen_can_execute_repo_patch": False,
            "qwen_can_final_merge": False,
            "current_candidates": [
                "codex exec --json",
                "OpenAI Agents SDK",
                "app-server worker",
                "dp_sidecar_execution_port",
                "local venv/docker",
                "OpenHands",
                "SWE-ReX",
                "E2B",
            ],
            "domain_imports_executor_sdk": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
        "worker_brief_schema": {
            "schema_version": "xinao.codex_s.worker_brief.v1",
            "required_fields": [
                "lane_id",
                "mode",
                "objective",
                "input_text",
                "write_targets",
                "artifact_contract",
            ],
            "artifact_contract": "each lane must return an artifact_ref or named_blocker",
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    }


def write_provider_schema_surfaces(
    *,
    runtime: Path,
    wave_id: str,
    provider_schemas: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    refs = {
        "brain_provider": paths["brain_provider_latest"],
        "worker_provider": paths["worker_provider_latest"],
        "model_gateway_route": paths["model_gateway_route_latest"],
        "executor_adapter": paths["executor_adapter_latest"],
    }
    payloads = {
        "brain_provider": {
            **provider_schemas["brain_provider_schema"],
            "task_id": TASK_ID,
            "wave_id": wave_id,
            "status": "brain_provider_schema_ready",
            "adoption_state": "default_hot_path_ready",
            "missing_to_runtime_enforced": "Temporal/LangGraph/default route must invoke this phase1 surface per real wave",
            "generated_at": now_iso(),
        },
        "worker_provider": {
            **provider_schemas["worker_provider_schema"],
            "task_id": TASK_ID,
            "wave_id": wave_id,
            "status": "worker_provider_schema_ready",
            "adoption_state": "default_hot_path_ready",
            "generated_at": now_iso(),
        },
        "model_gateway_route": {
            **provider_schemas["model_gateway_route_schema"],
            "task_id": TASK_ID,
            "wave_id": wave_id,
            "status": "model_gateway_route_schema_ready",
            "adoption_state": "default_hot_path_ready",
            "generated_at": now_iso(),
        },
        "executor_adapter": {
            **provider_schemas["executor_adapter_schema"],
            "task_id": TASK_ID,
            "wave_id": wave_id,
            "status": "executor_adapter_schema_ready",
            "adoption_state": "default_hot_path_ready",
            "generated_at": now_iso(),
        },
    }
    if write:
        for key, path in refs.items():
            write_json(path, payloads[key])
            write_json(paths["records"] / f"{safe_stem(wave_id)}.{key}.json", payloads[key])
    return {key: str(path) for key, path in refs.items()}


def build_worker_briefs(
    *,
    wave_id: str,
    mode_counts: dict[str, int],
    repo: Path,
    source_entry: dict[str, Any],
    latest_correction: dict[str, Any],
    provider_route_context: dict[str, Any],
) -> list[dict[str, Any]]:
    briefs: list[dict[str, Any]] = []
    lane_number = 0
    wave_stem = wave_digest_stem(wave_id)
    for mode in MODE_ORDER:
        for mode_index in range(1, int(mode_counts.get(mode) or 0) + 1):
            lane_number += 1
            lane_id = f"{wave_stem}-{mode}-{mode_index:02d}"
            provider_route = provider_route_for_mode(mode, provider_route_context)
            briefs.append(
                {
                    "lane_id": lane_id,
                    "lane_number": lane_number,
                    "source_wave_id": wave_id,
                    "source_wave_digest": wave_stem,
                    "mode": mode,
                    "objective": (
                        "Produce bounded implementation draft artifacts for "
                        "parallel_draft -> merge phase1"
                        if mode == "draft"
                        else f"Check/support the draft pool with {mode} evidence"
                    ),
                    "input_text": build_lane_input_text(
                        lane_id=lane_id,
                        mode=mode,
                        repo=repo,
                        source_entry=source_entry,
                        latest_correction=latest_correction,
                        provider_route=provider_route,
                    ),
                    "write_targets": [
                        "services/agent_runtime/modular_dynamic_worker_pool_phase1.py",
                        "D:/XINAO_RESEARCH_RUNTIME/state/modular_dynamic_worker_pool_phase1",
                    ],
                    "artifact_contract": "result_path from ProviderGateway lane payload; Qwen/DP outputs go to staging/fan-in only",
                    "provider_route": provider_route,
                    "provider_scheduler_context": {
                        "provider_scheduler_task_id": provider_route_context.get(
                            "provider_scheduler_task_id"
                        ),
                        "qwen_prepaid_policy_ref": provider_route_context.get(
                            "qwen_prepaid_policy_ref"
                        ),
                        "qwen_invocation_ref": provider_route_context.get("qwen_invocation_ref"),
                        "qwen_prepaid_cheap_worker_ready": provider_route_context.get(
                            "qwen_prepaid_cheap_worker_ready"
                        )
                        is True,
                    },
                    "not_execution_controller": True,
                }
            )
    return briefs


def assignment_dag_node_id_from_work_package(work_package: dict[str, Any]) -> str:
    if not isinstance(work_package, dict) or not work_package:
        return ""
    next_ready = str(work_package.get("next_ready_node_id") or "").strip()
    if next_ready:
        return next_ready
    items = work_package.get("work_items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and str(item.get("id") or "").strip():
                return str(item.get("id") or "").strip()
    return ""


def work_package_node(
    work_package: dict[str, Any],
    assignment_dag_node_id: str,
) -> dict[str, Any]:
    if not isinstance(work_package, dict) or not work_package:
        return {}
    node_id = assignment_dag_node_id or assignment_dag_node_id_from_work_package(work_package)
    items = work_package.get("work_items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and str(item.get("id") or "") == node_id:
                return item
    return {}


def work_package_lanes(
    work_package: dict[str, Any],
    assignment_dag_node_id: str,
) -> list[dict[str, Any]]:
    node = work_package_node(work_package, assignment_dag_node_id)
    lanes = node.get("lanes") if isinstance(node.get("lanes"), list) else []
    return [lane for lane in lanes if isinstance(lane, dict) and str(lane.get("lane_id") or "")]


def mode_counts_for_work_package_lanes(lanes: list[dict[str, Any]]) -> dict[str, int]:
    counts = {mode: 0 for mode in MODE_ORDER}
    counts["search_assist"] = 0
    for lane in lanes:
        mode = str(lane.get("mode") or "draft")
        if mode == "search_assist":
            counts["search_assist"] += 1
        elif mode in counts:
            counts[mode] += 1
        else:
            counts["draft"] += 1
    counts["search"] = 0
    counts["provider_probe"] = 0
    return counts


def work_package_contract_kind(
    work_package: dict[str, Any],
    assignment_dag_node_id: str,
    lanes: list[dict[str, Any]],
) -> str:
    if not lanes:
        return PARALLEL_DRAFT_POOL_CONTRACT
    if any(str(lane.get("mode") or "draft") == "draft" for lane in lanes):
        return PARALLEL_DRAFT_POOL_CONTRACT
    node = work_package_node(work_package, assignment_dag_node_id)
    text_parts = [
        assignment_dag_node_id,
        str(work_package.get("objective") or ""),
        str(node.get("objective") or ""),
        str(node.get("lane_kind") or ""),
        str(node.get("provider_route_key") or ""),
    ]
    for lane in lanes:
        text_parts.extend(
            [
                str(lane.get("lane_id") or ""),
                str(lane.get("mode") or ""),
                str(lane.get("lane_kind") or ""),
                str(lane.get("provider_role") or ""),
                str(lane.get("objective") or ""),
            ]
        )
    haystack = " ".join(text_parts).lower()
    if any(token in haystack for token in CONTROL_PLANE_REPAIR_NODE_TOKENS):
        return CONTROL_PLANE_REPAIR_CONTRACT
    return PARALLEL_DRAFT_POOL_CONTRACT


def provider_route_for_work_package_lane(
    lane: dict[str, Any],
    mode: str,
    provider_route_context: dict[str, Any],
) -> dict[str, Any]:
    route = dict(provider_route_for_mode(mode, provider_route_context))
    preferred_provider_id = str(lane.get("preferred_provider_id") or "").strip()
    if preferred_provider_id:
        route["preferred_provider_id"] = preferred_provider_id
        route["preferred_provider_label"] = str(lane.get("provider") or preferred_provider_id)
    if isinstance(lane.get("fallback_provider_ids"), list):
        route["fallback_provider_ids"] = [
            str(item) for item in lane.get("fallback_provider_ids", []) if str(item)
        ]
    if str(lane.get("lane_kind") or "").strip():
        route["lane_kind"] = str(lane.get("lane_kind") or "").strip()
    if str(lane.get("provider_role") or "").strip():
        route["provider_role"] = str(lane.get("provider_role") or "").strip()
    if lane.get("qwen_prepaid_first_required") is True:
        route["qwen_prepaid_first_required"] = True
        route["qwen_prepaid_first_reason"] = (
            "explicit assignment_dag work_package lane requires Qwen prepaid first"
        )
    route["outputs_to_staging_only"] = lane.get("outputs_to_staging_only") is not False
    route["direct_repo_write_allowed"] = False
    route["artifact_acceptance_required"] = lane.get("artifact_acceptance_required") is not False
    route["not_execution_controller"] = True
    return route


def build_worker_briefs_from_work_package(
    *,
    wave_id: str,
    lanes: list[dict[str, Any]],
    work_package: dict[str, Any],
    repo: Path,
    source_entry: dict[str, Any],
    latest_correction: dict[str, Any],
    provider_route_context: dict[str, Any],
) -> list[dict[str, Any]]:
    briefs: list[dict[str, Any]] = []
    wave_stem = wave_digest_stem(wave_id)
    package_objective = str(work_package.get("objective") or "").strip()
    for lane_number, lane in enumerate(lanes, start=1):
        mode = str(lane.get("mode") or "draft")
        if mode not in set(MODE_ORDER) | {"search_assist"}:
            mode = "draft"
        lane_id = str(lane.get("lane_id") or f"{wave_stem}-{mode}-{lane_number:02d}")
        provider_route = provider_route_for_work_package_lane(
            lane,
            mode,
            provider_route_context,
        )
        objective = (
            package_objective
            or str(lane.get("objective") or "").strip()
            or (
                "Produce bounded implementation draft artifacts for parallel_draft -> merge phase1"
                if mode == "draft"
                else f"Check/support the draft pool with {mode} evidence"
            )
        )
        briefs.append(
            {
                "lane_id": lane_id,
                "lane_number": lane_number,
                "source_wave_id": wave_id,
                "source_wave_digest": wave_stem,
                "mode": mode,
                "objective": objective,
                "input_text": build_lane_input_text(
                    lane_id=lane_id,
                    mode=mode,
                    repo=repo,
                    source_entry=source_entry,
                    latest_correction=latest_correction,
                    provider_route=provider_route,
                ),
                "write_targets": [
                    "D:/XINAO_RESEARCH_RUNTIME/state/modular_dynamic_worker_pool_phase1",
                    "D:/XINAO_RESEARCH_RUNTIME/state/task_bound_evidence",
                ],
                "artifact_contract": "explicit work_package lane result_path; Qwen/DP outputs go to staging/fan-in only",
                "provider_route": provider_route,
                "provider_scheduler_context": {
                    "provider_scheduler_task_id": provider_route_context.get(
                        "provider_scheduler_task_id"
                    ),
                    "qwen_prepaid_policy_ref": provider_route_context.get(
                        "qwen_prepaid_policy_ref"
                    ),
                    "qwen_invocation_ref": provider_route_context.get("qwen_invocation_ref"),
                    "qwen_prepaid_cheap_worker_ready": provider_route_context.get(
                        "qwen_prepaid_cheap_worker_ready"
                    )
                    is True,
                },
                "work_package_lane": {
                    "status": str(lane.get("status") or ""),
                    "outputs_to_staging_only": lane.get("outputs_to_staging_only") is not False,
                    "direct_repo_write_allowed": False,
                    "artifact_acceptance_required": lane.get("artifact_acceptance_required")
                    is not False,
                    "not_execution_controller": True,
                },
                "not_execution_controller": True,
            }
        )
    return briefs


def write_worker_brief_queue(
    *,
    runtime: Path,
    wave_id: str,
    worker_briefs: list[dict[str, Any]],
    mode_counts: dict[str, int],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    qwen_required_count = len(
        [
            brief
            for brief in worker_briefs
            if brief.get("provider_route", {}).get("qwen_prepaid_first_required") is True
        ]
    )
    qwen_preferred_count = len(
        [
            brief
            for brief in worker_briefs
            if brief.get("provider_route", {}).get("preferred_provider_id")
            == QWEN_CHEAP_WORKER_PROVIDER_ID
        ]
    )
    payload = {
        "schema_version": "xinao.codex_s.worker_brief_queue.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "worker_brief_queue_ready" if worker_briefs else "worker_brief_queue_blocked",
        "queue_id": "modular_dynamic_worker_pool_phase1.worker_brief_queue",
        "mode_counts": mode_counts,
        "brief_count": len(worker_briefs),
        "draft_brief_count": len(
            [brief for brief in worker_briefs if brief.get("mode") == "draft"]
        ),
        "qwen_prepaid_first_required_count": qwen_required_count,
        "qwen_prepaid_preferred_count": qwen_preferred_count,
        "provider_route_summary": {
            "qwen_prepaid_cheap_worker": qwen_preferred_count,
            "deepseek_dp": len(
                [
                    brief
                    for brief in worker_briefs
                    if brief.get("provider_route", {}).get("preferred_provider_id")
                    == DEEPSEEK_DP_PROVIDER_ID
                ]
            ),
            "fallback_allowed_reasons": sorted(QWEN_FALLBACK_ALLOWED_REASONS),
        },
        "briefs": worker_briefs,
        "draft_is_primary": int(mode_counts.get("draft") or 0)
        > max(int(value or 0) for key, value in mode_counts.items() if key != "draft"),
        "search_is_main_task": False,
        "provider_probe_used_as_progress": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["worker_brief_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.worker_brief_queue.json", payload)
    return payload


def write_worker_assignment(
    *,
    runtime: Path,
    wave_id: str,
    assignment_dag_node_id: str,
    worker_briefs: list[dict[str, Any]],
    mode_counts: dict[str, int],
    dynamic_width_policy: dict[str, Any],
    source_entry: dict[str, Any],
    latest_correction: dict[str, Any],
    work_package: dict[str, Any] | None = None,
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    facts = memo_facts()
    previous_assignment = read_json(paths["global_worker_assignment"])
    previous_digest = sha256_json(previous_assignment) if previous_assignment else ""
    package = work_package if isinstance(work_package, dict) else {}
    package_node_id = (
        assignment_dag_node_id
        or assignment_dag_node_id_from_work_package(package)
        or ASSIGNMENT_DAG_NODE_ID
    )
    package_node = work_package_node(package, package_node_id)
    package_lanes = work_package_lanes(package, package_node_id)
    package_digest = sha256_json(package) if package else ""
    lanes = [
        {
            "lane_id": brief["lane_id"],
            "mode": brief["mode"],
            "lane_kind": brief.get("provider_route", {}).get("lane_kind")
            or "provider_gateway_execution",
            "provider_role": brief.get("provider_route", {}).get("provider_role")
            or "CheapWorkerProvider",
            "provider": brief.get("provider_route", {}).get("preferred_provider_label")
            or brief.get("provider_route", {}).get("preferred_provider_id")
            or "ProviderGateway",
            "preferred_provider_id": brief.get("provider_route", {}).get("preferred_provider_id"),
            "fallback_provider_ids": brief.get("provider_route", {}).get("fallback_provider_ids")
            or [],
            "qwen_prepaid_first_required": brief.get("provider_route", {}).get(
                "qwen_prepaid_first_required"
            )
            is True,
            "outputs_to_staging_only": True,
            "direct_repo_write_allowed": False,
            "status": "planned",
            "artifact_acceptance_required": True,
            "not_execution_controller": True,
        }
        for brief in worker_briefs
    ]
    payload = {
        "schema_version": "xinao.worker_assignment.v2.dag",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": TASK_ID,
        "assignment_id": TASK_ID,
        "wave_id": wave_id,
        "status": "worker_assignment_ready",
        "source_intent_package_ref": CURRENT_INTENT_PACKAGE_REF,
        "source_intent_package_id": "grok_faithful_modular_dynamic_worker_pool_20260704",
        "semantic_owner": "333",
        "foreground_brain_owner": True,
        "source_entry_binding": {
            "root": source_entry.get("source_entry_root"),
            "read_at": source_entry.get("source_entry_read_at"),
            "sampled_count": source_entry.get("sampled_count"),
            "digest_sha256": source_entry.get("source_entry_digest_sha256"),
            "dynamic_directory_entry": True,
            "not_fixed_two_text_task_slicer": True,
        },
        "user_latest_correction_digest": latest_correction,
        "primary_contract_source": {
            "path": str(facts["path"]),
            "configured_path": str(DESKTOP_MEMO_REF),
            "mandatory_read_first": True,
            "read_in_full_before_assignment": facts["read_in_full_before_assignment"],
            "line_count": facts["line_count"],
            "char_count": facts["char_count"],
            "sha256": facts["sha256"],
            "role": "mode memo serving 333, not highest authority",
        },
        "productivity_mode_v2": False,
        "deprecated_mode_refs": [
            "grok_mode_switch_*",
            "grok_overnight_extend_*",
            "accounting_watchdog_default",
        ],
        "hot_path_shape": "parallel_draft->merge->writer",
        "dp_worker_role": "fallback_and_quality_worker_pool_not_second_brain",
        "cheap_worker_role": "qwen_prepaid_first_then_deepseek_dp_fallback",
        "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
        "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
        "assignment_role": "faithful_modular_dynamic_worker_pool_phase1",
        "architecture": (
            "SupervisorBrain + DynamicWorkerPool + ProviderGateway + ExecutorAdapter + FanInMerge"
        ),
        "current_binding": {
            "SupervisorBrainProvider": "Codex S",
            "CheapWorkerProvider": "Qwen prepaid cheap worker -> DeepSeek/DP fallback",
            "EngineeringExecutor": "Codex exec -> Codex SDK",
            "QualityEscalation": "DeepSeek Pro / DP quality lane -> Qwen plus/max -> Codex",
            "FinalMerge": "Codex S / Codex exec / SDK",
            "DurableWorkflowPort": "S-native Temporal",
            "ModelGatewayPort": "LiteLLM Proxy or equivalent",
        },
        "future_replaceability": {
            "BrainProvider": ["DeepSeek Pro", "Codex Pro", "other strong manager"],
            "ExecutorAdapter": ["codex exec", "SDK", "app-server", "OpenHands", "SWE-ReX", "E2B"],
            "WorkerProvider": ["local", "vLLM", "OpenRouter", "Batch", "OpenAI-compatible"],
        },
        "must_close": MUST_DO_10,
        "wave_steps_8": WAVE_STEPS_8,
        "mode_counts": mode_counts,
        "dynamic_width_policy_ref": str(paths["dynamic_width_policy_latest"]),
        "worker_brief_queue_ref": str(paths["worker_brief_latest"]),
        "explicit_work_package_bound": bool(package_lanes),
        "work_package_digest_sha256": package_digest,
        "work_package_next_ready_node_id": str(package.get("next_ready_node_id") or package_node_id)
        if package
        else "",
        "work_package_objective": str(package.get("objective") or "") if package else "",
        "explicit_work_package_lane_ids": [
            str(lane.get("lane_id") or "") for lane in package_lanes
        ],
        "assignment_dag": {
            "current_active_node_id": package_node_id,
            "next_ready_node_id": str(package.get("next_ready_node_id") or package_node_id)
            if package
            else package_node_id,
            "nodes": [
                {
                    "id": "schema_and_queue_bind",
                    "status": "ready",
                    "outputs": [
                        str(paths["brain_provider_latest"]),
                        str(paths["worker_provider_latest"]),
                        str(paths["model_gateway_route_latest"]),
                        str(paths["executor_adapter_latest"]),
                        str(paths["worker_brief_latest"]),
                    ],
                },
                {
                    "id": package_node_id,
                    "status": str(package_node.get("status") or "ready_next"),
                    "lanes": lanes,
                    "explicit_work_package_bound": bool(package_lanes),
                },
                {
                    "id": "fan_in_staging_merge_spend",
                    "status": "planned",
                    "outputs": [
                        str(paths["draft_staging_latest"]),
                        str(paths["merge_consumer_latest"]),
                        str(paths["spend_ledger_latest"]),
                    ],
                },
            ],
        },
        "hard_acceptance_fields": HARD_ACCEPTANCE_FIELDS,
        "previous_global_assignment_digest_sha256": previous_digest,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
        "validation": {
            "passed": bool(worker_briefs) and facts["read_in_full_before_assignment"],
            "checks": {
                "desktop_memo_read_full": facts["read_in_full_before_assignment"],
                "source_entry_dynamic_read": bool(source_entry.get("source_entry_read_at"))
                and int(source_entry.get("sampled_count") or 0) > 0,
                "user_latest_correction_bound": latest_correction.get("task_id")
                == LATEST_USER_CORRECTION_TASK_ID,
                "333_semantic_owner_bound": True,
                "draft_count_positive": int(mode_counts.get("draft") or 0) > 0,
                "productivity_mode_v2_false": True,
                "source_package_rebound_to_faithful_package": True,
            },
        },
    }
    previous_dag = (
        previous_assignment.get("assignment_dag")
        if isinstance(previous_assignment, dict)
        and isinstance(previous_assignment.get("assignment_dag"), dict)
        else {}
    )
    previous_active_node_id = str(previous_dag.get("current_active_node_id") or "")
    previous_next_node_id = str(previous_dag.get("next_ready_node_id") or "")
    preserve_existing_explicit_assignment = (
        package_node_id == ASSIGNMENT_DAG_NODE_ID
        and bool(previous_assignment)
        and previous_assignment.get("explicit_work_package_bound") is True
        and bool(previous_active_node_id or previous_next_node_id)
        and package_node_id not in {previous_active_node_id, previous_next_node_id}
    )
    payload["global_worker_assignment_write_skipped"] = preserve_existing_explicit_assignment
    payload["global_worker_assignment_write_skip_reason"] = (
        "preserve_current_explicit_assignment_dag_node"
        if preserve_existing_explicit_assignment
        else ""
    )
    if write:
        write_json(paths["worker_assignment"], payload)
        if not preserve_existing_explicit_assignment:
            write_json(paths["global_worker_assignment"], payload)
    return payload


def build_lane_input_text(
    *,
    lane_id: str,
    mode: str,
    repo: Path,
    source_entry: dict[str, Any],
    latest_correction: dict[str, Any],
    provider_route: dict[str, Any] | None = None,
) -> str:
    route = provider_route if isinstance(provider_route, dict) else {}
    sampled_names = [
        str(item.get("name") or "")
        for item in source_entry.get("sampled_files", [])
        if isinstance(item, dict)
    ][:8]
    return "\n".join(
        [
            f"task_id={TASK_ID}",
            f"lane_id={lane_id}",
            f"mode={mode}",
            "semantic_owner=333",
            f"source_entry_root={source_entry.get('source_entry_root')}",
            f"source_entry_read_at={source_entry.get('source_entry_read_at')}",
            f"source_entry_digest_sha256={source_entry.get('source_entry_digest_sha256')}",
            "source_entry_sampled_files=" + " | ".join(sampled_names),
            f"user_latest_correction_task_id={latest_correction.get('task_id')}",
            f"user_latest_correction_sha256={latest_correction.get('sha256')}",
            "mode_memo=Codex_DeepSeek_高并行草稿主脑合并模式_20260704.txt serves_333_not_authority",
            "current_binding=SupervisorBrainProvider:Codex S; CheapWorkerProvider:Qwen prepaid cheap worker + DeepSeek/DP",
            f"provider_route_class={route.get('route_class') or ''}",
            f"preferred_provider_id={route.get('preferred_provider_id') or ''}",
            "fallback_provider_ids="
            + " | ".join([str(item) for item in route.get("fallback_provider_ids", [])]),
            f"qwen_prepaid_first_required={route.get('qwen_prepaid_first_required') is True}",
            "main_shape=parallel_draft->merge->writer",
            "cheap_worker_role=draft_extract_eval_pool_not_second_brain",
            "forbidden_main_tasks=search,provider_probe,meta_rsi,watchdog_accounting",
            "write_targets=services/agent_runtime/modular_dynamic_worker_pool_phase1.py",
            "write_targets=D:/XINAO_RESEARCH_RUNTIME/state/modular_dynamic_worker_pool_phase1",
            f"repo={repo}",
            "must_do_10=" + " | ".join(MUST_DO_10),
            "wave_steps_8=" + " | ".join(WAVE_STEPS_8),
        ]
    )


def default_dp_invoker() -> DpInvoker:
    from services.agent_runtime.dp_sidecar_execution_port import (
        invoke_dp_sidecar_execution_port,
    )

    return invoke_dp_sidecar_execution_port


def provider_scheduler_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / PROVIDER_SCHEDULER_TASK_ID
    return {
        "state": state,
        "latest": state / "latest.json",
        "qwen_prepaid_policy": state / "qwen_prepaid_policy" / "latest.json",
        "qwen_invocation": state / "qwen_invocation" / "latest.json",
        "capability_manifest": runtime
        / "capabilities"
        / PROVIDER_SCHEDULER_CAPABILITY_ID
        / "manifest.json",
    }


def load_provider_route_context(runtime: Path) -> dict[str, Any]:
    paths = provider_scheduler_paths(runtime)
    latest = read_json(paths["latest"])
    qwen_policy = read_json(paths["qwen_prepaid_policy"])
    qwen_invocation = read_json(paths["qwen_invocation"])
    qwen_ready = qwen_policy.get("status") == "qwen_prepaid_policy_ready" and (
        qwen_invocation.get("status") == "qwen_dashscope_canary_ready"
        or qwen_invocation.get("succeeded") is True
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
        "provider_scheduler_task_id": PROVIDER_SCHEDULER_TASK_ID,
        "provider_scheduler_latest_ref": str(paths["latest"]),
        "qwen_prepaid_policy_ref": str(paths["qwen_prepaid_policy"]),
        "qwen_invocation_ref": str(paths["qwen_invocation"]),
        "qwen_prepaid_policy_status": str(qwen_policy.get("status") or ""),
        "qwen_invocation_status": str(qwen_invocation.get("status") or ""),
        "qwen_prepaid_cheap_worker_ready": qwen_ready,
        "qwen_prepaid_cheap_worker_default_first": (
            latest.get("qwen_prepaid_cheap_worker_default_first") is True or qwen_ready
        ),
        "qwen_selected_model": selected_model,
        "qwen_api_key_source_label": str(
            qwen_policy.get("secret_status", {}).get("api_key_source_label")
            if isinstance(qwen_policy.get("secret_status"), dict)
            else ""
        ),
        "routing_contract": qwen_policy.get("routing_contract", {}),
        "fallback_allowed_reasons": sorted(QWEN_FALLBACK_ALLOWED_REASONS),
        "outputs_to_staging_only": qwen_policy.get("outputs_to_staging_only") is not False,
        "direct_repo_write_allowed": False,
        "refs": {key: str(path) for key, path in paths.items()},
        "not_completion_boundary": True,
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
            "fallback_provider_ids": [DEEPSEEK_DP_PROVIDER_ID, "codex_exec"],
            "qwen_prepaid_first_required": True,
            "qwen_prepaid_first_reason": (
                "desktop memo: prepaid Qwen cheap worker is first for "
                "draft/extraction/classify/low-risk eval when ready"
            ),
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
            "fallback_provider_ids": ["codex_exec"],
            "qwen_prepaid_first_required": False,
            "qwen_prepaid_first_reason": "QWEN_NOT_READY",
            "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
            "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
            "fallback_allowed_reasons": sorted(QWEN_FALLBACK_ALLOWED_REASONS),
            "outputs_to_staging_only": True,
            "direct_repo_write_allowed": False,
        }
    if mode in {"contradiction", "audit"}:
        route_class = "quality_aux_worker"
        fallback = ["qwen_quality_aux_worker", "codex_exec"]
    elif mode == "citation_verify":
        route_class = "citation_verify_support"
        fallback = ["qwen_prepaid_cheap_worker", "codex_exec"]
    else:
        route_class = "support_worker"
        fallback = ["codex_exec"]
    return {
        "route_class": route_class,
        "lane_kind": "dp_sidecar_execution",
        "provider_role": "CheapWorkerProvider",
        "preferred_provider_id": DEEPSEEK_DP_PROVIDER_ID,
        "preferred_provider_label": "DeepSeek/DP sidecar",
        "fallback_provider_ids": fallback,
        "qwen_prepaid_first_required": False,
        "qwen_prepaid_first_reason": "mode_not_qwen_cheap_first",
        "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
        "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
        "fallback_allowed_reasons": sorted(QWEN_FALLBACK_ALLOWED_REASONS),
        "outputs_to_staging_only": True,
        "direct_repo_write_allowed": False,
    }


def classify_qwen_blocker(value: Any) -> str:
    text = str(value or "")
    upper = text.upper()
    if not text:
        return "QWEN_WORKER_POOL_INVOKE_FAILED"
    if "429" in upper or "RATE" in upper or "LIMIT" in upper or "TOO MANY" in upper:
        return "QWEN_RATE_LIMIT"
    if "401" in upper or "403" in upper or "AUTH" in upper or "API_KEY" in upper or "KEY" in upper:
        return "QWEN_AUTH_FAILED"
    if (
        "TIMEOUT" in upper
        or "TIMED OUT" in upper
        or "ENDPOINT" in upper
        or "CONNECTION" in upper
        or "CONNECT" in upper
        or "TEMPORARY" in upper
        or "UNAVAILABLE" in upper
        or "GATEWAY" in upper
        or "502" in upper
        or "503" in upper
        or "504" in upper
    ):
        return "QWEN_TRANSIENT_OR_ENDPOINT_FAILED"
    if "QUALITY" in upper:
        return "QWEN_QUALITY_BLOCKER"
    if "NOT_SUITABLE" in upper or "UNSUPPORTED" in upper:
        return "TASK_NOT_SUITABLE_FOR_QWEN"
    if "NOT_READY" in upper or "NOT_CONFIGURED" in upper:
        return "QWEN_NOT_READY"
    return text if upper.startswith("QWEN_") else "QWEN_WORKER_POOL_INVOKE_FAILED"


def qwen_mode_status(mode: str) -> str:
    return "draft_ready" if mode == "draft" else "model_ready"


def default_qwen_invoker() -> QwenInvoker:
    return invoke_qwen_cheap_worker_lane


def default_qwen_quality_invoker() -> QwenInvoker:
    return invoke_qwen_quality_aux_worker_lane


def default_codex_invoker() -> CodexInvoker:
    return invoke_codex_exec_worker_lane


def invoke_local_ollama_qwen_lane(
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
    selected_model: str = "",
    selected_pool_provider_id: str = "",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    paths = output_paths(runtime)
    state = paths["state"] / "local_ollama_worker_invocation"
    record_path = state / "records" / f"{safe_stem(invocation_id)}.json"
    latest_path = state / "latest.json"
    artifact_path = state / "artifacts" / f"{safe_stem(invocation_id)}.{mode}.json"
    raw_response_path = state / "raw" / f"{safe_stem(invocation_id)}.raw.txt"
    local_supported_modes = set(CHEAP_QWEN_FIRST_MODES)
    if selected_model == "deepseek-r1:8b" or "deepseek_r1" in selected_pool_provider_id:
        local_supported_modes.update({"audit", "contradiction"})
    base_payload: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.local_ollama_qwen_worker_lane.v1",
        "provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
        "carrier_provider_id": "ollama_local_cli",
        "selected_pool_provider_id": selected_pool_provider_id,
        "task_id": task_id,
        "request_id": request_id,
        "invocation_id": invocation_id,
        "episode_id": episode_id,
        "mode": mode,
        "objective": objective,
        "local_model_first_attempted": True,
        "local_model_first_required": False,
        "local_first_mandatory": False,
        "dynamic_router_selected_local": bool(selected_model or selected_pool_provider_id),
        "outputs_to_staging_only": True,
        "direct_repo_write_allowed": False,
        "can_search_directly": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if mode not in local_supported_modes:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "TASK_NOT_SUITABLE_FOR_LOCAL_OLLAMA",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner
    try:
        from services.agent_runtime import codex_native_provider_scheduler_phase4 as phase4
    except Exception as exc:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": f"LOCAL_OLLAMA_QWEN_NOT_READY:{type(exc).__name__}",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner
    status = phase4.local_ollama_status(selected_model=selected_model or None)
    if status.get("ready") is not True:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "selected_model": status.get("selected_model") or selected_model or "",
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": str(status.get("named_blocker") or "LOCAL_OLLAMA_QWEN_NOT_READY"),
            "local_ollama_status": status,
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner
    selected_model = str(status.get("selected_model") or selected_model or "qwen3:8b")
    executable = str(status.get("executable") or "ollama")
    user_prompt = "\n".join(
        [
            "You are the local cheap draft worker for Codex S.",
            "Produce bounded staging output only. Do not claim completion. Do not write repo files. Do not search.",
            f"mode={mode}",
            f"objective={objective}",
            f"max_results={max_results}",
            "",
            input_text[:12000],
        ]
    )
    try:
        completed = subprocess.run(
            [executable, "run", selected_model],
            input=user_prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(os.environ.get("XINAO_LOCAL_OLLAMA_TIMEOUT_SECONDS", "120")),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "selected_model": selected_model,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "LOCAL_OLLAMA_QWEN_TIMEOUT",
            "error_tail": str(exc)[-500:],
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner
    content = (completed.stdout or "").strip()
    if write:
        write_text(raw_response_path, completed.stdout or "")
    if completed.returncode != 0 or not content:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "selected_model": selected_model,
            "result_path": "",
            "raw_response_ref": str(raw_response_path) if raw_response_path.is_file() else "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "LOCAL_OLLAMA_QWEN_INVOKE_FAILED",
            "returncode": completed.returncode,
            "stderr_tail": (completed.stderr or "")[-500:],
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner
    artifact = {
        "schema_version": f"{SCHEMA_VERSION}.local_ollama_qwen_worker_artifact.v1",
        "provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
        "carrier_provider_id": "ollama_local_cli",
        "selected_carrier_provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
        "model": selected_model,
        "selected_pool_provider_id": selected_pool_provider_id,
        "mode": mode,
        "objective": objective,
        "content": content,
        "completion_claim_allowed": False,
        "direct_repo_write_allowed": False,
        "outputs_to_staging_only": True,
        "can_search_directly": False,
        "generated_at": now_iso(),
    }
    if write:
        write_json(artifact_path, artifact)
    provider_payload = {
        **base_payload,
        "mode_invocation_status": qwen_mode_status(mode),
        "selected_carrier_provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
        "provider_invocation_performed": True,
        "model_invocation_performed": True,
        "tool_invocation_performed": False,
        "selected_model": selected_model,
        "selected_pool_provider_id": selected_pool_provider_id,
        "result_path": str(artifact_path),
        "raw_response_ref": str(raw_response_path),
        "provider_invocation_ref": str(record_path),
        "evidence_refs": {
            "latest": str(latest_path),
            "record_path": str(record_path),
            "result_path": str(artifact_path),
            "raw_response_ref": str(raw_response_path),
        },
        "named_blocker": "",
    }
    runner = {
        "schema_version": f"{SCHEMA_VERSION}.local_ollama_qwen_worker_runner.v1",
        "status": "local_ollama_qwen_worker_lane_ready",
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "provider_invocation_ref": str(record_path),
            "provider_latest_ref": str(latest_path),
            "result_path": str(artifact_path),
            "raw_response_ref": str(raw_response_path),
            "selected_carrier_provider_id": LOCAL_OLLAMA_WORKER_PROVIDER_ID,
            "model_invocation_performed": True,
            "refs_are_not_execution_controllers": True,
        },
    }
    if write:
        write_json(record_path, runner)
        write_json(latest_path, runner)
    return runner


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
    runtime = Path(runtime_root)
    paths = output_paths(runtime)
    state = paths["state"] / "qwen_worker_invocation"
    record_path = state / "records" / f"{safe_stem(invocation_id)}.json"
    latest_path = state / "latest.json"
    artifact_path = state / "artifacts" / f"{safe_stem(invocation_id)}.{mode}.json"
    raw_response_path = state / "raw" / f"{safe_stem(invocation_id)}.raw.json"
    route_context = load_provider_route_context(runtime)
    base_payload: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.qwen_cheap_worker_lane.v1",
        "provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
        "carrier_provider_id": QWEN_DASHSCOPE_PROVIDER_ID,
        "task_id": task_id,
        "request_id": request_id,
        "invocation_id": invocation_id,
        "episode_id": episode_id,
        "mode": mode,
        "objective": objective,
        "qwen_prepaid_first_attempted": True,
        "qwen_prepaid_first_required": mode in CHEAP_QWEN_FIRST_MODES,
        "qwen_prepaid_policy_ref": route_context.get("qwen_prepaid_policy_ref"),
        "qwen_invocation_ref": route_context.get("qwen_invocation_ref"),
        "api_key_source_label": route_context.get("qwen_api_key_source_label") or "",
        "selected_model": route_context.get("qwen_selected_model") or "qwen3.6-flash",
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
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "TASK_NOT_SUITABLE_FOR_QWEN",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner
    try:
        from services.agent_runtime import codex_native_provider_scheduler_phase4 as phase4
    except Exception as exc:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": f"QWEN_WORKER_POOL_INVOKER_NOT_ROUTED:{type(exc).__name__}",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner

    key = phase4.load_qwen_api_key(runtime)
    if key.get("available") is not True:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "QWEN_AUTH_FAILED",
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
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "QWEN_WORKER_POOL_WRONG_PYTHON_CARRIER",
            "python_carrier": carrier,
            "environment_blocker_only": True,
            "provider_readiness_fact_allowed": False,
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner
    if not phase4.module_available("openai"):
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "QWEN_WORKER_POOL_INVOKER_NOT_ROUTED",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner

    from openai import OpenAI

    try:
        import httpx
    except Exception:
        httpx = None  # type: ignore[assignment]

    api_key = str(key.get("api_key") or "")
    source_label = str(key.get("source_label") or "")
    system_prompt = (
        "You are Qwen prepaid cheap worker for Codex S. Produce bounded "
        "draft/extraction/eval support only. Do not claim completion, do not "
        "write repo files, and keep output suitable for staging/fan-in."
    )
    user_prompt = "\n".join(
        [
            f"mode={mode}",
            f"objective={objective}",
            f"max_results={max_results}",
            "Return concise Markdown with actionable bullets and blockers if any.",
            "",
            input_text[:12000],
        ]
    )
    attempts: list[dict[str, Any]] = []
    selected_content = ""
    selected_model = ""
    selected_base_url_label = ""
    selected_usage: dict[str, Any] = {}
    named_blocker = "QWEN_WORKER_POOL_INVOKE_FAILED"
    for base in phase4.qwen_base_url_candidates(runtime):
        for model in [str(route_context.get("qwen_selected_model") or "qwen3.6-flash")]:
            attempt = {
                "api_key_source_label": source_label,
                "base_url_label": base["label"],
                "model": model,
                "request_shape": "openai.chat.completions.create",
                "trust_env_proxy": False,
            }
            http_client = None
            try:
                client_kwargs: dict[str, Any] = {
                    "api_key": api_key,
                    "base_url": base["base_url"],
                    "timeout": 45,
                    "max_retries": 0,
                }
                if httpx is not None:
                    http_client = httpx.Client(timeout=45, trust_env=False)
                    client_kwargs["http_client"] = http_client
                client = OpenAI(**client_kwargs)
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2 if mode == "draft" else 0,
                    max_tokens=900,
                    extra_body={"enable_thinking": False},
                )
                selected_content = (
                    completion.choices[0].message.content if completion.choices else ""
                )
                selected_model = model
                selected_base_url_label = base["label"]
                try:
                    dumped = completion.model_dump()
                except Exception:
                    dumped = {"text": str(completion)}
                selected_usage = (
                    dumped.get("usage") if isinstance(dumped.get("usage"), dict) else {}
                )
                attempt["status"] = "succeeded" if selected_content else "empty_response"
                attempts.append(attempt)
                if write:
                    write_json(raw_response_path, {"response": dumped, "usage": selected_usage})
                if selected_content:
                    artifact = {
                        "schema_version": f"{SCHEMA_VERSION}.qwen_cheap_worker_artifact.v1",
                        "provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
                        "carrier_provider_id": QWEN_DASHSCOPE_PROVIDER_ID,
                        "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
                        "model": selected_model,
                        "mode": mode,
                        "objective": objective,
                        "content": selected_content,
                        "completion_claim_allowed": False,
                        "direct_repo_write_allowed": False,
                        "outputs_to_staging_only": True,
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
                        "selected_model": selected_model,
                        "selected_base_url_label": selected_base_url_label,
                        "selected_api_key_source_label": source_label,
                        "attempts": attempts,
                        "usage": selected_usage,
                    }
                    runner = {
                        "schema_version": f"{SCHEMA_VERSION}.qwen_cheap_worker_runner.v1",
                        "status": "qwen_cheap_worker_lane_ready",
                        "provider_payload": provider_payload,
                        "actual_dispatch_refs": {
                            "provider_invocation_ref": str(record_path),
                            "provider_latest_ref": str(latest_path),
                            "result_path": str(artifact_path),
                            "raw_response_ref": str(raw_response_path),
                            "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
                            "model_invocation_performed": True,
                            "refs_are_not_execution_controllers": True,
                        },
                    }
                    if write:
                        write_json(record_path, runner)
                        write_json(latest_path, runner)
                    return runner
            except Exception as exc:
                blocker = classify_qwen_blocker(exc)
                named_blocker = blocker
                attempt.update(
                    {
                        "status": "failed",
                        "error_type": exc.__class__.__name__,
                        "named_blocker": blocker,
                        "error_tail": phase4.scrub_secret_text(exc, api_key=api_key),
                    }
                )
                attempts.append(attempt)
            finally:
                if http_client is not None:
                    http_client.close()

    provider_payload = {
        **base_payload,
        "mode_invocation_status": "blocked",
        "selected_carrier_provider_id": QWEN_CHEAP_WORKER_PROVIDER_ID,
        "provider_invocation_performed": False,
        "model_invocation_performed": False,
        "tool_invocation_performed": False,
        "result_path": "",
        "raw_response_ref": str(raw_response_path) if raw_response_path.is_file() else "",
        "provider_invocation_ref": str(record_path),
        "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
        "named_blocker": named_blocker,
        "attempts": attempts,
    }
    runner = {
        "schema_version": f"{SCHEMA_VERSION}.qwen_cheap_worker_runner.v1",
        "status": "qwen_cheap_worker_lane_blocked",
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {},
    }
    if write:
        write_json(record_path, runner)
        write_json(latest_path, runner)
    return runner


def invoke_qwen_quality_aux_worker_lane(
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
    runtime = Path(runtime_root)
    paths = output_paths(runtime)
    state = paths["state"] / "qwen_quality_worker_invocation"
    record_path = state / "records" / f"{safe_stem(invocation_id)}.json"
    latest_path = state / "latest.json"
    artifact_path = state / "artifacts" / f"{safe_stem(invocation_id)}.{mode}.json"
    raw_response_path = state / "raw" / f"{safe_stem(invocation_id)}.raw.json"
    route_context = load_provider_route_context(runtime)
    policy = read_json(str(route_context.get("qwen_prepaid_policy_ref") or ""))
    policy_models = (
        policy.get("models", {}).get("quality_aux")
        if isinstance(policy.get("models"), dict)
        else []
    )
    model_candidates = [
        str(item)
        for item in (policy_models if isinstance(policy_models, list) else [])
        if str(item)
    ] or ["qwen3.7-plus", "qwen3.7-max"]
    base_payload: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.qwen_quality_aux_worker_lane.v1",
        "provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
        "carrier_provider_id": QWEN_DASHSCOPE_PROVIDER_ID,
        "task_id": task_id,
        "request_id": request_id,
        "invocation_id": invocation_id,
        "episode_id": episode_id,
        "mode": mode,
        "objective": objective,
        "qwen_quality_aux_attempted": True,
        "qwen_prepaid_first_attempted": False,
        "qwen_prepaid_first_required": False,
        "qwen_prepaid_policy_ref": route_context.get("qwen_prepaid_policy_ref"),
        "qwen_invocation_ref": route_context.get("qwen_invocation_ref"),
        "api_key_source_label": route_context.get("qwen_api_key_source_label") or "",
        "selected_model": model_candidates[0],
        "outputs_to_staging_only": True,
        "direct_repo_write_allowed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if mode not in QWEN_QUALITY_MODES:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "TASK_NOT_SUITABLE_FOR_QWEN_QUALITY",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner
    try:
        from services.agent_runtime import codex_native_provider_scheduler_phase4 as phase4
    except Exception as exc:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": f"QWEN_WORKER_POOL_INVOKER_NOT_ROUTED:{type(exc).__name__}",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner

    key = phase4.load_qwen_api_key(runtime)
    if key.get("available") is not True:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "QWEN_AUTH_FAILED",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner
    if not phase4.module_available("openai"):
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": "QWEN_WORKER_POOL_INVOKER_NOT_ROUTED",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner

    from openai import OpenAI

    try:
        import httpx
    except Exception:
        httpx = None  # type: ignore[assignment]

    api_key = str(key.get("api_key") or "")
    source_label = str(key.get("source_label") or "")
    system_prompt = (
        "You are Qwen quality auxiliary worker for Codex S. Produce bounded "
        "audit/contradiction reasoning only. Do not claim completion, do not "
        "write repo files, and keep output suitable for Codex S fan-in."
    )
    user_prompt = "\n".join(
        [
            f"mode={mode}",
            f"objective={objective}",
            f"max_results={max_results}",
            "Return concise Markdown with findings, contradictions, risks, and blockers.",
            "completion_claim_allowed=false",
            "",
            input_text[:16000],
        ]
    )
    attempts: list[dict[str, Any]] = []
    selected_content = ""
    selected_model = ""
    selected_base_url_label = ""
    selected_usage: dict[str, Any] = {}
    named_blocker = "QWEN_WORKER_POOL_INVOKE_FAILED"
    for base in phase4.qwen_base_url_candidates(runtime):
        for model in model_candidates:
            attempt = {
                "api_key_source_label": source_label,
                "base_url_label": base["label"],
                "model": model,
                "request_shape": "openai.chat.completions.create",
                "trust_env_proxy": False,
            }
            http_client = None
            try:
                client_kwargs: dict[str, Any] = {
                    "api_key": api_key,
                    "base_url": base["base_url"],
                    "timeout": 60,
                    "max_retries": 0,
                }
                if httpx is not None:
                    http_client = httpx.Client(timeout=60, trust_env=False)
                    client_kwargs["http_client"] = http_client
                client = OpenAI(**client_kwargs)
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    max_tokens=1000,
                    extra_body={"enable_thinking": False},
                )
                selected_content = (
                    completion.choices[0].message.content if completion.choices else ""
                )
                selected_model = model
                selected_base_url_label = base["label"]
                try:
                    dumped = completion.model_dump()
                except Exception:
                    dumped = {"text": str(completion)}
                selected_usage = (
                    dumped.get("usage") if isinstance(dumped.get("usage"), dict) else {}
                )
                attempt["status"] = "succeeded" if selected_content else "empty_response"
                attempts.append(attempt)
                if write:
                    write_json(raw_response_path, {"response": dumped, "usage": selected_usage})
                if selected_content:
                    artifact = {
                        "schema_version": f"{SCHEMA_VERSION}.qwen_quality_aux_worker_artifact.v1",
                        "provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
                        "carrier_provider_id": QWEN_DASHSCOPE_PROVIDER_ID,
                        "selected_carrier_provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
                        "model": selected_model,
                        "mode": mode,
                        "objective": objective,
                        "content": selected_content,
                        "completion_claim_allowed": False,
                        "direct_repo_write_allowed": False,
                        "outputs_to_staging_only": True,
                        "generated_at": now_iso(),
                    }
                    if write:
                        write_json(artifact_path, artifact)
                    provider_payload = {
                        **base_payload,
                        "mode_invocation_status": qwen_mode_status(mode),
                        "selected_carrier_provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
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
                        "selected_model": selected_model,
                        "selected_base_url_label": selected_base_url_label,
                        "selected_api_key_source_label": source_label,
                        "attempts": attempts,
                        "usage": selected_usage,
                    }
                    runner = {
                        "schema_version": f"{SCHEMA_VERSION}.qwen_quality_aux_worker_runner.v1",
                        "status": "qwen_quality_aux_worker_lane_ready",
                        "provider_payload": provider_payload,
                        "actual_dispatch_refs": {
                            "provider_invocation_ref": str(record_path),
                            "provider_latest_ref": str(latest_path),
                            "result_path": str(artifact_path),
                            "raw_response_ref": str(raw_response_path),
                            "selected_carrier_provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
                            "model_invocation_performed": True,
                            "refs_are_not_execution_controllers": True,
                        },
                    }
                    if write:
                        write_json(record_path, runner)
                        write_json(latest_path, runner)
                    return runner
            except Exception as exc:
                blocker = classify_qwen_blocker(exc)
                named_blocker = blocker
                attempt.update(
                    {
                        "status": "failed",
                        "error_type": exc.__class__.__name__,
                        "named_blocker": blocker,
                        "error_tail": phase4.scrub_secret_text(exc, api_key=api_key),
                    }
                )
                attempts.append(attempt)
            finally:
                if http_client is not None:
                    http_client.close()

    provider_payload = {
        **base_payload,
        "mode_invocation_status": "blocked",
        "selected_carrier_provider_id": QWEN_QUALITY_WORKER_PROVIDER_ID,
        "provider_invocation_performed": False,
        "model_invocation_performed": False,
        "tool_invocation_performed": False,
        "result_path": "",
        "raw_response_ref": str(raw_response_path) if raw_response_path.is_file() else "",
        "provider_invocation_ref": str(record_path),
        "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
        "named_blocker": named_blocker,
        "attempts": attempts,
    }
    runner = {
        "schema_version": f"{SCHEMA_VERSION}.qwen_quality_aux_worker_runner.v1",
        "status": "qwen_quality_aux_worker_lane_blocked",
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {},
    }
    if write:
        write_json(record_path, runner)
        write_json(latest_path, runner)
    return runner


def invoke_codex_exec_worker_lane(
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
    runtime = Path(runtime_root)
    paths = output_paths(runtime)
    state = paths["state"] / "codex_exec_worker_invocation"
    record_path = state / "records" / f"{safe_stem(invocation_id)}.json"
    latest_path = state / "latest.json"
    schema_path = state / "schemas" / f"{safe_stem(invocation_id)}.schema.json"
    artifact_path = state / "artifacts" / f"{safe_stem(invocation_id)}.{mode}.json"
    stdout_path = state / "logs" / f"{safe_stem(invocation_id)}.stdout.jsonl"
    stderr_path = state / "logs" / f"{safe_stem(invocation_id)}.stderr.txt"
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "provider_id",
            "status",
            "mode",
            "content",
            "no_file_edits",
            "completion_claim_allowed",
        ],
        "properties": {
            "provider_id": {"type": "string"},
            "status": {"type": "string"},
            "mode": {"type": "string"},
            "content": {"type": "string"},
            "no_file_edits": {"type": "boolean"},
            "completion_claim_allowed": {"type": "boolean"},
        },
    }
    write_json(schema_path, schema)
    base_payload = {
        "schema_version": f"{SCHEMA_VERSION}.codex_exec_worker_lane.v1",
        "provider_id": CODEX_EXEC_PROVIDER_ID,
        "task_id": task_id,
        "request_id": request_id,
        "invocation_id": invocation_id,
        "episode_id": episode_id,
        "mode": mode,
        "objective": objective,
        "selected_carrier_provider_id": CODEX_EXEC_PROVIDER_ID,
        "outputs_to_staging_only": True,
        "direct_repo_write_allowed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    try:
        from services.agent_runtime import codex_native_provider_scheduler_phase4 as phase4
    except Exception as exc:
        provider_payload = {
            **base_payload,
            "mode_invocation_status": "blocked",
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record_path),
            "evidence_refs": {"latest": str(latest_path), "record_path": str(record_path)},
            "named_blocker": f"CODEX_EXEC_WORKER_NOT_ROUTED:{type(exc).__name__}",
        }
        runner = {"provider_payload": provider_payload, "actual_dispatch_refs": {}}
        if write:
            write_json(record_path, runner)
            write_json(latest_path, runner)
        return runner

    prompt = "\n".join(
        [
            "You are a bounded Codex exec fallback worker for Seed Cortex S.",
            "Do not edit files. Do not run shell commands. Do not claim completion.",
            "Return only the requested JSON object.",
            f"provider_id={CODEX_EXEC_PROVIDER_ID}",
            f"mode={mode}",
            f"objective={objective}",
            f"max_results={max_results}",
            "completion_claim_allowed=false",
            "",
            "input:",
            input_text[:20000],
        ]
    )
    command, codex_path = phase4.codex_command(
        [
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--cd",
            str(DEFAULT_REPO),
            "--ephemeral",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(artifact_path),
            prompt,
        ]
    )
    if not command:
        result = {
            "returncode": -1,
            "timed_out": False,
            "named_blocker": "CODEX_CLI_NOT_INSTALLED",
            "stdout_ref": str(stdout_path),
            "stderr_ref": str(stderr_path),
        }
    else:
        result = phase4.run_hidden_command(
            command,
            cwd=DEFAULT_REPO,
            timeout_seconds=180,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        result["codex_path"] = codex_path
    artifact_payload: dict[str, Any] = {}
    if artifact_path.is_file():
        artifact_payload = read_json(artifact_path)
    succeeded = (
        result.get("returncode") == 0
        and artifact_payload.get("provider_id") == CODEX_EXEC_PROVIDER_ID
        and artifact_payload.get("completion_claim_allowed") is False
    )
    provider_payload = {
        **base_payload,
        "mode_invocation_status": qwen_mode_status(mode) if succeeded else "blocked",
        "provider_invocation_performed": succeeded,
        "model_invocation_performed": succeeded,
        "tool_invocation_performed": True,
        "result_path": str(artifact_path) if artifact_path.is_file() else "",
        "raw_response_ref": str(stdout_path) if stdout_path.is_file() else "",
        "provider_invocation_ref": str(record_path),
        "evidence_refs": {
            "latest": str(latest_path),
            "record_path": str(record_path),
            "result_path": str(artifact_path),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        },
        "named_blocker": ""
        if succeeded
        else str(result.get("named_blocker") or "CODEX_EXEC_WORKER_FAILED"),
        "selected_model": "codex_exec",
        "codex_exec_result": result,
    }
    runner = {
        "schema_version": f"{SCHEMA_VERSION}.codex_exec_worker_runner.v1",
        "status": "codex_exec_worker_lane_ready" if succeeded else "codex_exec_worker_lane_blocked",
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "provider_invocation_ref": str(record_path),
            "provider_latest_ref": str(latest_path),
            "result_path": str(artifact_path) if artifact_path.is_file() else "",
            "raw_response_ref": str(stdout_path) if stdout_path.is_file() else "",
            "selected_carrier_provider_id": CODEX_EXEC_PROVIDER_ID,
            "model_invocation_performed": succeeded,
            "refs_are_not_execution_controllers": True,
        }
        if succeeded
        else {},
    }
    if write:
        write_json(record_path, runner)
        write_json(latest_path, runner)
    return runner


def provider_payload_succeeded(payload: dict[str, Any]) -> bool:
    return (
        str(payload.get("mode_invocation_status") or "") in SUCCESS_STATUSES
        and payload.get("provider_invocation_performed") is True
    )


def classify_dp_blocker(value: Any) -> str:
    text = str(value or "")
    upper = text.upper()
    if not text:
        return "DP_WORKER_POOL_INVOKE_FAILED"
    if "429" in upper or "RATE" in upper or "LIMIT" in upper or "TOO MANY" in upper:
        return "DEEPSEEK_RATE_LIMIT"
    if "401" in upper or "403" in upper or "AUTH" in upper or "API_KEY" in upper or "KEY" in upper:
        return "DEEPSEEK_AUTH_FAILED"
    if "TIMEOUT" in upper or "TIMED OUT" in upper:
        return "DEEPSEEK_TIMEOUT"
    if "UNAVAILABLE" in upper or "CONNECTION" in upper or "CONNECT" in upper:
        return "DEEPSEEK_ENDPOINT_UNAVAILABLE"
    if "EMPTY" in upper:
        return "DEEPSEEK_EMPTY_MODEL_RESPONSE"
    return text if upper.startswith("DEEPSEEK_") else "DEEPSEEK_MODEL_INVOCATION_FAILED"


def invoke_lane_with_provider_route(
    *,
    runtime: Path,
    wave_id: str,
    brief: dict[str, Any],
    dp_invoker: DpInvoker,
    qwen_invoker: QwenInvoker,
    write: bool,
    qwen_quality_invoker: QwenInvoker | None = None,
    codex_invoker: CodexInvoker | None = None,
) -> dict[str, Any]:
    mode = str(brief["mode"])
    lane_id = str(brief["lane_id"])
    wave_stem = wave_digest_stem(wave_id)
    invocation_id = safe_stem(lane_id)
    route = brief.get("provider_route") if isinstance(brief.get("provider_route"), dict) else {}
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
            dp_runner = dp_invoker(**common)
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
                    "qwen_attempt_status": qwen_status,
                    "qwen_attempt_named_blocker": str(qwen_payload.get("named_blocker") or ""),
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
    dp_runner = dp_invoker(**common)
    dp_payload = (
        dp_runner.get("provider_payload")
        if isinstance(dp_runner.get("provider_payload"), dict)
        else {}
    )
    if provider_payload_succeeded(dp_payload):
        return dp_runner

    fallback_provider_ids = [
        str(item) for item in route.get("fallback_provider_ids", []) if str(item)
    ]
    quality_route = mode in QWEN_QUALITY_MODES or route.get("route_class") == "quality_aux_worker"
    dp_fallback_reason = classify_dp_blocker(dp_payload.get("named_blocker"))
    last_runner = dp_runner
    last_payload = dp_payload
    qwen_quality_payload: dict[str, Any] = {}
    if quality_route and QWEN_QUALITY_WORKER_PROVIDER_ID in fallback_provider_ids:
        quality_common = {
            **common,
            "request_id": f"{wave_stem}-{mode}-qwen-quality-request",
            "invocation_id": safe_stem(f"{lane_id}-qwen-quality"),
            "objective": (f"{common['objective']} | fallback_after={DEEPSEEK_DP_PROVIDER_ID}"),
        }
        quality_runner = (qwen_quality_invoker or default_qwen_quality_invoker())(**quality_common)
        qwen_quality_payload = (
            quality_runner.get("provider_payload")
            if isinstance(quality_runner.get("provider_payload"), dict)
            else {}
        )
        qwen_quality_payload.update(
            {
                "fallback_from_provider_id": DEEPSEEK_DP_PROVIDER_ID,
                "fallback_reason": dp_fallback_reason,
                "fallback_allowed": dp_fallback_reason in DP_FALLBACK_ALLOWED_REASONS,
                "dp_attempt_ref": str(dp_payload.get("provider_invocation_ref") or ""),
                "dp_attempt_status": str(dp_payload.get("mode_invocation_status") or ""),
                "dp_attempt_named_blocker": str(dp_payload.get("named_blocker") or ""),
            }
        )
        quality_runner["provider_payload"] = qwen_quality_payload
        quality_runner["deepseek_dp_attempt"] = dp_payload
        last_runner = quality_runner
        last_payload = qwen_quality_payload
        if provider_payload_succeeded(qwen_quality_payload):
            return quality_runner

    if quality_route and CODEX_EXEC_PROVIDER_ID in fallback_provider_ids:
        qwen_blocker = classify_qwen_blocker(qwen_quality_payload.get("named_blocker"))
        codex_common = {
            **common,
            "request_id": f"{wave_stem}-{mode}-codex-exec-request",
            "invocation_id": safe_stem(f"{lane_id}-codex-exec"),
            "objective": (
                f"{common['objective']} | fallback_after="
                f"{last_payload.get('selected_carrier_provider_id') or DEEPSEEK_DP_PROVIDER_ID}"
            ),
        }
        codex_runner = (codex_invoker or default_codex_invoker())(**codex_common)
        codex_payload = (
            codex_runner.get("provider_payload")
            if isinstance(codex_runner.get("provider_payload"), dict)
            else {}
        )
        codex_payload.update(
            {
                "fallback_from_provider_id": str(
                    last_payload.get("selected_carrier_provider_id") or DEEPSEEK_DP_PROVIDER_ID
                ),
                "fallback_reason": qwen_blocker if qwen_quality_payload else dp_fallback_reason,
                "fallback_allowed": True,
                "dp_attempt_ref": str(dp_payload.get("provider_invocation_ref") or ""),
                "dp_attempt_status": str(dp_payload.get("mode_invocation_status") or ""),
                "dp_attempt_named_blocker": str(dp_payload.get("named_blocker") or ""),
                "qwen_quality_attempt_ref": str(
                    qwen_quality_payload.get("provider_invocation_ref") or ""
                ),
                "qwen_quality_attempt_status": str(
                    qwen_quality_payload.get("mode_invocation_status") or ""
                ),
                "qwen_quality_attempt_named_blocker": str(
                    qwen_quality_payload.get("named_blocker") or ""
                ),
            }
        )
        codex_runner["provider_payload"] = codex_payload
        codex_runner["deepseek_dp_attempt"] = dp_payload
        if qwen_quality_payload:
            codex_runner["qwen_quality_attempt"] = qwen_quality_payload
        return codex_runner

    return last_runner


def run_lane(
    *,
    runtime: Path,
    wave_id: str,
    brief: dict[str, Any],
    dp_invoker: DpInvoker,
    qwen_invoker: QwenInvoker,
    write: bool,
    qwen_quality_invoker: QwenInvoker | None = None,
    codex_invoker: CodexInvoker | None = None,
) -> dict[str, Any]:
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
        qwen_quality_invoker=qwen_quality_invoker,
        codex_invoker=codex_invoker,
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
    raw_response = (
        read_json(raw_response_ref) if raw_response_ref and not raw_response_missing else {}
    )
    artifact_ref = str(
        dispatch_refs.get("result_path")
        or provider_payload.get("result_path")
        or dispatch_refs.get("provider_invocation_ref")
        or ""
    )
    selected_provider = str(provider_payload.get("selected_carrier_provider_id") or "")
    named_blocker = str(provider_payload.get("named_blocker") or "")
    provider_performed = provider_payload.get("provider_invocation_performed") is True
    model_invocation_performed = provider_payload.get("model_invocation_performed") is True
    tool_invocation_performed = provider_payload.get("tool_invocation_performed") is True
    completed = status in SUCCESS_STATUSES and (provider_performed or mode == "provider_probe")
    artifact_exists = bool(artifact_ref) and Path(artifact_ref).is_file()
    artifact_text = ""
    if artifact_exists:
        try:
            artifact_text = Path(artifact_ref).read_text(encoding="utf-8", errors="replace")[
                :200000
            ]
        except Exception:
            artifact_text = ""
    raw_usage = raw_response.get("usage") if isinstance(raw_response.get("usage"), dict) else {}
    response_payload = (
        raw_response.get("response") if isinstance(raw_response.get("response"), dict) else {}
    )
    response_usage = (
        response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else {}
    )
    observed_usage = raw_usage or response_usage
    qwen_invocation = (
        selected_provider == QWEN_CHEAP_WORKER_PROVIDER_ID and model_invocation_performed
    )
    qwen_quality_invocation = (
        selected_provider == QWEN_QUALITY_WORKER_PROVIDER_ID and model_invocation_performed
    )
    deepseek_dp_invocation = (
        selected_provider in {DEEPSEEK_DP_PROVIDER_ID, DEEPSEEK_DP_ROUTE_ID}
        and model_invocation_performed
    )
    codex_exec_invocation = (
        selected_provider == CODEX_EXEC_PROVIDER_ID and model_invocation_performed
    )
    external_draft_invocation = (
        mode == "draft"
        and selected_provider in EXTERNAL_DRAFT_PROVIDER_IDS
        and model_invocation_performed
    )
    local_stub = selected_provider.startswith(LOCAL_STUB_PROVIDER_PREFIXES)
    provider_tier = (
        "qwen_prepaid_cheap_worker"
        if qwen_invocation
        else "qwen_quality_aux_worker"
        if qwen_quality_invocation
        else "deepseek_dp_external_model"
        if deepseek_dp_invocation
        else "codex_exec_engineering_worker"
        if codex_exec_invocation
        else "local_stub_or_local_eval"
        if local_stub
        else "sidecar_tool"
    )
    provider_model = (
        str(provider_payload.get("selected_model") or "qwen3.6-flash")
        if selected_provider in {QWEN_CHEAP_WORKER_PROVIDER_ID, QWEN_QUALITY_WORKER_PROVIDER_ID}
        else "deepseek-chat"
        if selected_provider == DEEPSEEK_DP_PROVIDER_ID
        else "codex_exec"
        if selected_provider == CODEX_EXEC_PROVIDER_ID
        else selected_provider or "unknown"
    )
    usage_meter = gateway_meter_usage(
        input_text=str(brief.get("input_text") or ""),
        output_text=artifact_text,
        observed_usage=observed_usage,
        provider_model=provider_model,
        provider_tier=provider_tier,
        latency_ms=latency_ms,
    )
    rate_limit_error = ""
    blocker_upper = named_blocker.upper()
    if "429" in blocker_upper or "RATE" in blocker_upper or "LIMIT" in blocker_upper:
        rate_limit_error = named_blocker
    provider_route = (
        brief.get("provider_route") if isinstance(brief.get("provider_route"), dict) else {}
    )
    qwen_prepaid_first_required = (
        provider_payload.get("qwen_prepaid_first_required") is True
        or provider_route.get("qwen_prepaid_first_required") is True
    )
    qwen_prepaid_first_attempted = provider_payload.get("qwen_prepaid_first_attempted") is True
    fallback_allowed = provider_payload.get("fallback_allowed") is True
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
        "model": provider_model,
        "provider_tier": provider_tier,
        "provider_invocation_performed": provider_performed,
        "model_invocation_performed": model_invocation_performed,
        "tool_invocation_performed": tool_invocation_performed,
        "qwen_prepaid_invocation": qwen_invocation,
        "qwen_quality_aux_invocation": qwen_quality_invocation,
        "deepseek_dp_invocation": deepseek_dp_invocation,
        "codex_exec_invocation": codex_exec_invocation,
        "qwen_prepaid_first_required": qwen_prepaid_first_required,
        "qwen_prepaid_first_attempted": qwen_prepaid_first_attempted,
        "qwen_prepaid_first_succeeded": qwen_invocation,
        "fallback_from_provider_id": str(provider_payload.get("fallback_from_provider_id") or ""),
        "fallback_reason": str(provider_payload.get("fallback_reason") or ""),
        "fallback_allowed": fallback_allowed,
        "qwen_attempt_ref": str(provider_payload.get("qwen_attempt_ref") or ""),
        "dp_attempt_ref": str(provider_payload.get("dp_attempt_ref") or ""),
        "qwen_quality_attempt_ref": str(provider_payload.get("qwen_quality_attempt_ref") or ""),
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
        "claim_candidate": {
            "claim": f"{mode} lane returned {status}",
            "artifact_ref": artifact_ref,
            "accepted_for": "draft_staging" if mode == "draft" else "merge_support",
        },
        "confidence": 0.75 if completed else 0.0,
        "risk": "local_stub_not_real_dp" if local_stub else "normal",
        "usage": {
            **usage_meter,
        },
        "rate_limit_error": rate_limit_error,
        "named_blocker": named_blocker,
        "runner_payload_digest_sha256": sha256_json(runner_payload),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_draft_staging_queue(
    *,
    runtime: Path,
    wave_id: str,
    lane_results: list[dict[str, Any]],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    drafts = [
        {
            "lane_id": item["lane_id"],
            "artifact_ref": item["artifact_ref"],
            "selected_carrier_provider_id": item["selected_carrier_provider_id"],
            "stage_status": "staged_for_merge",
            "completion_claim_allowed": False,
        }
        for item in lane_results
        if item.get("mode") == "draft" and item.get("status") == "succeeded"
    ]
    payload = {
        "schema_version": "xinao.codex_s.draft_staging_queue.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "queue_id": "modular_dynamic_worker_pool_phase1.draft_staging_queue",
        "status": "draft_staging_queue_ready" if drafts else "draft_staging_queue_blocked",
        "draft_count": len(drafts),
        "staged_count": len(drafts),
        "entries": drafts,
        "merge_required": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["draft_staging_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.draft_staging_queue.json", payload)
    return payload


def render_merge_artifact(
    *,
    wave_id: str,
    staging_queue: dict[str, Any],
    lane_results: list[dict[str, Any]],
    source_entry: dict[str, Any],
    latest_correction: dict[str, Any],
) -> str:
    draft_entries = (
        staging_queue.get("entries") if isinstance(staging_queue.get("entries"), list) else []
    )
    staged_lane_ids = {
        str(entry.get("lane_id") or "") for entry in draft_entries if isinstance(entry, dict)
    }
    rejected_drafts = [
        item
        for item in lane_results
        if item.get("mode") == "draft" and str(item.get("lane_id") or "") not in staged_lane_ids
    ]
    sampled_names = [
        str(item.get("name") or "")
        for item in source_entry.get("sampled_files", [])
        if isinstance(item, dict)
    ][:8]
    lines = [
        "# Modular Dynamic Worker Pool Phase1 Merge",
        "",
        f"- task_id: `{TASK_ID}`",
        f"- wave_id: `{wave_id}`",
        "- semantic_owner: `333`",
        f"- source_entry_root: `{source_entry.get('source_entry_root')}`",
        f"- source_entry_read_at: `{source_entry.get('source_entry_read_at')}`",
        f"- latest_user_correction: `{latest_correction.get('task_id')}`",
        "- stage_order: `parallel_draft -> merge -> writer`",
        f"- draft_count: {len(draft_entries)}",
        "- foreground_brain_role: Codex S owns understanding, dispatch, fan-in merge, correction, and next-wave decision.",
        "- DP role: draft-main worker pool, not exploration/search worker, not second brain, and not final owner.",
        "",
        "## Progress This Wave / 这波推进了什么",
        "",
        "- 前台主脑重新绑定 333、动态源入口和最新用户纠偏，再把本波 DP 草稿池输出收敛成一个可读合并稿。",
        f"- 源入口本波抽样：{', '.join(sampled_names) if sampled_names else '无可读样本'}。",
        "- 这不是完成声明；它是本波 foreground fan-in 产物。",
        "",
        "## Adopted Drafts / 采用的草稿",
        "",
    ]
    for entry in draft_entries:
        if not isinstance(entry, dict):
            continue
        lines.append(f"- {entry.get('lane_id')}: `{entry.get('artifact_ref')}`")
    if not draft_entries:
        lines.append("- 无；这是 blocker。")
    lines.extend(
        [
            "",
            "## Rejected Or Deferred Drafts / 否决或暂缓的草稿",
            "",
        ]
    )
    if rejected_drafts:
        for item in rejected_drafts:
            lines.append(
                f"- {item.get('lane_id')}: "
                f"{item.get('named_blocker') or item.get('mode_invocation_status') or 'not_staged'} "
                f"`{item.get('artifact_ref')}`"
            )
    else:
        lines.append("- 无；所有成功 draft lane 均进入 staging。")
    lines.extend(
        [
            "",
            "## Support Lanes",
            "",
        ]
    )
    for item in lane_results:
        if item.get("mode") == "draft":
            continue
        lines.append(
            f"- {item.get('lane_id')} ({item.get('mode')}): "
            f"{item.get('mode_invocation_status')} `{item.get('artifact_ref')}`"
        )
    lines.extend(
        [
            "",
            "## Current Gaps / 当前还差什么",
            "",
            "- 333 源入口仍会变化，下一波必须重新读取目录并更新 frontier。",
            "- same_default_loop 只能作为后台发动机，不能替代前台主脑 fan-in 决策。",
            "- PASS/latest/readback/runtime_enforced 只算证据面，不是完成边界。",
            "",
            "## Next Dispatch / 下一波怎么派",
            "",
            "- 继续 draft 主力：DP/DeepSeek 产多路草稿，search/provider_probe 不做主任务。",
            "- 前台主脑先看 source_entry + 最新纠偏，再生成下一波 WorkerBrief/DAG/width/mode_counts。",
            "- 草稿必须先 staging，再由前台主脑合并和纠偏。",
            "",
            "## Writer Result",
            "",
            "The writer output is this merged artifact plus runtime readback. It is a fan-in product, not a completion claim.",
            "",
        ]
    )
    return "\n".join(lines)


def build_merge_consumer(
    *,
    runtime: Path,
    wave_id: str,
    staging_queue: dict[str, Any],
    lane_results: list[dict[str, Any]],
    source_entry: dict[str, Any],
    latest_correction: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    merge_artifact_path = paths["merge_artifacts"] / f"{safe_stem(wave_id)}.merged.md"
    merge_text = render_merge_artifact(
        wave_id=wave_id,
        staging_queue=staging_queue,
        lane_results=lane_results,
        source_entry=source_entry,
        latest_correction=latest_correction,
    )
    if write:
        write_text(merge_artifact_path, merge_text)
    draft_count = int(staging_queue.get("draft_count") or 0)
    payload = {
        "schema_version": "xinao.codex_s.fan_in_merge_consumer.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "consumer_id": "modular_dynamic_worker_pool_phase1.merge_consumer",
        "status": "merge_consumer_merged" if draft_count > 0 else "merge_consumer_blocked",
        "stage_order": ["parallel_draft", "merge", "writer"],
        "draft_count": draft_count,
        "merged_count": 1 if draft_count > 0 else 0,
        "merge_artifact": str(merge_artifact_path),
        "merge_artifact_sha256": (
            hashlib.sha256(merge_text.encode("utf-8")).hexdigest() if draft_count > 0 else ""
        ),
        "writer_output_ref": str(merge_artifact_path),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["merge_consumer_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.merge_consumer.json", payload)
    return payload


def build_spend_ledger(
    *,
    runtime: Path,
    wave_id: str,
    lane_results: list[dict[str, Any]],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    entries = []
    provider_tier_usage: dict[str, int] = {}
    total_tokens = 0
    total_cost = 0.0
    total_estimated_cost = 0.0
    token_with_zero_cost_entry_count = 0
    price_catalog_applied_count = 0
    for item in lane_results:
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        tier = str(item.get("provider_tier") or "unknown")
        provider = str(item.get("provider") or item.get("selected_carrier_provider_id") or "")
        model = str(item.get("model") or "unknown")
        usage_total_tokens = int(usage.get("total_tokens") or 0)
        usage_cost = float(usage.get("cost_usd") or 0.0)
        if usage_total_tokens > 0 and usage_cost <= 0.0:
            estimated_usage = estimate_usage_cost(
                provider=provider,
                model=model,
                provider_tier=tier,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                cache_hit_tokens=int(usage.get("cache_hit_tokens") or 0),
            )
            usage = {**usage, **estimated_usage}
            usage_cost = float(usage.get("cost_usd") or 0.0)
        provider_tier_usage[tier] = provider_tier_usage.get(tier, 0) + 1
        total_tokens += usage_total_tokens
        total_cost += usage_cost
        total_estimated_cost += float(usage.get("estimated_cost_usd") or usage_cost or 0.0)
        if usage_total_tokens > 0 and usage_cost <= 0.0:
            token_with_zero_cost_entry_count += 1
        if usage.get("price_catalog_applied") is True:
            price_catalog_applied_count += 1
        entries.append(
            {
                "lane_id": item["lane_id"],
                "mode": item["mode"],
                "provider": provider,
                "model": model,
                "provider_tier": tier,
                "selected_carrier_provider_id": item["selected_carrier_provider_id"],
                "usage_recorded": True,
                "metered_usage_observed": bool(usage.get("metered_usage_observed") is True),
                "provider_usage_observed": bool(usage.get("provider_usage_observed") is True),
                "gateway_metered_usage": bool(usage.get("gateway_metered_usage") is True),
                "estimated_usage": bool(usage.get("estimated_usage") is True),
                "metering_source": str(
                    usage.get("metering_source") or usage.get("cost_source") or ""
                ),
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
                "cost_usd": float(usage.get("cost_usd") or 0.0),
                "estimated_cost_usd": float(usage.get("estimated_cost_usd") or 0.0),
                "input_cost_usd": float(usage.get("input_cost_usd") or 0.0),
                "cached_input_cost_usd": float(usage.get("cached_input_cost_usd") or 0.0),
                "output_cost_usd": float(usage.get("output_cost_usd") or 0.0),
                "cache_hit_tokens": int(usage.get("cache_hit_tokens") or 0),
                "cache_miss_tokens": int(usage.get("cache_miss_tokens") or 0),
                "price_catalog_applied": usage.get("price_catalog_applied") is True,
                "price_catalog_id": str(usage.get("price_catalog_id") or ""),
                "price_catalog_source_url": str(usage.get("price_catalog_source_url") or ""),
                "cost_source": str(usage.get("cost_source") or ""),
                "latency_ms": int(usage.get("latency_ms") or item.get("latency_ms") or 0),
                "rate_limit_error": str(item.get("rate_limit_error") or ""),
                "artifact_ref": item["artifact_ref"],
                "external_draft_invocation": item.get("external_draft_invocation") is True,
                "qwen_prepaid_invocation": item.get("qwen_prepaid_invocation") is True,
                "deepseek_dp_invocation": item.get("deepseek_dp_invocation") is True,
                "qwen_prepaid_first_required": item.get("qwen_prepaid_first_required") is True,
                "qwen_prepaid_first_attempted": item.get("qwen_prepaid_first_attempted") is True,
                "qwen_prepaid_first_succeeded": item.get("qwen_prepaid_first_succeeded") is True,
                "fallback_from_provider_id": str(item.get("fallback_from_provider_id") or ""),
                "fallback_reason": str(item.get("fallback_reason") or ""),
                "fallback_allowed": item.get("fallback_allowed") is True,
                "local_stub": item.get("local_stub") is True,
            }
        )
    payload = {
        "schema_version": "xinao.codex_s.modular_worker_pool_spend_ledger.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "ledger_id": "modular_dynamic_worker_pool_phase1.spend_ledger",
        "status": "spend_ledger_ready" if entries else "spend_ledger_blocked",
        "entry_count": len(entries),
        "spend_entry_count": len(entries),
        "provider_price_catalog": price_catalog_payload(),
        "provider_tier_usage": provider_tier_usage,
        "token_cost_spend": {
            "prompt_tokens": sum(item["prompt_tokens"] for item in entries),
            "completion_tokens": sum(item["completion_tokens"] for item in entries),
            "total_tokens": total_tokens,
            "cost_usd": round(total_cost, 10),
            "estimated_cost_usd": round(total_estimated_cost, 10),
            "input_cost_usd": round(sum(item["input_cost_usd"] for item in entries), 10),
            "cached_input_cost_usd": round(
                sum(item["cached_input_cost_usd"] for item in entries), 10
            ),
            "output_cost_usd": round(sum(item["output_cost_usd"] for item in entries), 10),
            "cache_hit_tokens": sum(item["cache_hit_tokens"] for item in entries),
            "cache_miss_tokens": sum(item["cache_miss_tokens"] for item in entries),
            "price_catalog_applied_entry_count": price_catalog_applied_count,
            "token_with_zero_cost_entry_count": token_with_zero_cost_entry_count,
            "zero_cost_with_tokens_forbidden": token_with_zero_cost_entry_count == 0,
            "metered_usage_entry_count": len(
                [item for item in entries if item["metered_usage_observed"]]
            ),
            "provider_usage_entry_count": len(
                [item for item in entries if item["provider_usage_observed"]]
            ),
            "gateway_metered_usage_entry_count": len(
                [item for item in entries if item["gateway_metered_usage"]]
            ),
            "estimated_usage_entry_count": len(
                [item for item in entries if item["estimated_usage"]]
            ),
            "metering_sources": sorted(
                {str(item["metering_source"]) for item in entries if item["metering_source"]}
            ),
        },
        "qwen_prepaid_usage": {
            "qwen_invocation_count": len(
                [item for item in entries if item["qwen_prepaid_invocation"]]
            ),
            "qwen_first_required_count": len(
                [item for item in entries if item["qwen_prepaid_first_required"]]
            ),
            "qwen_first_attempted_count": len(
                [item for item in entries if item["qwen_prepaid_first_attempted"]]
            ),
            "qwen_first_succeeded_count": len(
                [item for item in entries if item["qwen_prepaid_first_succeeded"]]
            ),
            "deepseek_fallback_after_qwen_count": len(
                [
                    item
                    for item in entries
                    if item["fallback_from_provider_id"] == QWEN_CHEAP_WORKER_PROVIDER_ID
                ]
            ),
            "qwen_fallback_allowed_count": len(
                [
                    item
                    for item in entries
                    if item["fallback_from_provider_id"] == QWEN_CHEAP_WORKER_PROVIDER_ID
                    and item["fallback_allowed"]
                ]
            ),
        },
        "budget_gate_input": {
            "active": True,
            "routing_switch_enabled": True,
            "default_without_user_preference": "codex_brain_only",
            "legacy_default_alias": "qwen_dp_first",
            "qwen_dp_first_global_default": True,
            "codex_brain_only_global_default": True,
            "switch_can_restore_codex_primary": True,
            "codex_final_patch_acceptance_only": True,
            "codex_bulk_worker_default_paused": True,
            "target_codex_share_min": 0.10,
            "target_codex_share_max": 0.20,
            "codex_quota_is_constrained_resource": True,
            "qwen_dp_dynamic_width_unlimited_by_codex_budget": True,
            "max_codex_width_cap": 1,
            "max_qwen_dp_width_cap": 0,
            "cost_catalog_required": True,
            "token_with_zero_cost_entry_count": token_with_zero_cost_entry_count,
            "scheduler_action": (
                "route_qwen_dp_first_codex_final_only"
                if token_with_zero_cost_entry_count == 0
                else "block_or_reprice_before_dispatch"
            ),
        },
        "estimated_total_cost_usd": round(total_estimated_cost or total_cost, 10),
        "entries": entries,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["spend_ledger_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.spend_ledger.json", payload)
    return payload


def build_foreground_brain_decision(
    *,
    runtime: Path,
    wave_id: str,
    source_entry: dict[str, Any],
    latest_correction: dict[str, Any],
    worker_briefs: list[dict[str, Any]],
    mode_counts: dict[str, int],
    lane_results: list[dict[str, Any]],
    staging_queue: dict[str, Any],
    merge_consumer: dict[str, Any],
    spend_ledger: dict[str, Any],
    target_width: int,
    named_blocker: str,
    next_wave_id: str,
    contract_kind: str = PARALLEL_DRAFT_POOL_CONTRACT,
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    control_plane_repair = contract_kind == CONTROL_PLANE_REPAIR_CONTRACT
    staged_lane_ids = {
        str(entry.get("lane_id") or "")
        for entry in staging_queue.get("entries", [])
        if isinstance(entry, dict)
    }
    draft_results = [item for item in lane_results if item.get("mode") == "draft"]
    draft_artifacts_consumed = []
    rejected_drafts = []
    for item in draft_results:
        lane_id = str(item.get("lane_id") or "")
        consumed = lane_id in staged_lane_ids
        entry = {
            "lane_id": lane_id,
            "status": item.get("status"),
            "artifact_ref": item.get("artifact_ref"),
            "provider": item.get("selected_carrier_provider_id"),
            "external_draft_invocation": item.get("external_draft_invocation") is True,
            "qwen_prepaid_invocation": item.get("qwen_prepaid_invocation") is True,
            "deepseek_dp_invocation": item.get("deepseek_dp_invocation") is True,
            "qwen_prepaid_first_required": item.get("qwen_prepaid_first_required") is True,
            "fallback_reason": item.get("fallback_reason") or "",
            "local_stub": item.get("local_stub") is True,
            "staged_for_merge": consumed,
            "adopted_for_merge": consumed,
            "risk": item.get("risk"),
            "named_blocker": item.get("named_blocker") or "",
        }
        draft_artifacts_consumed.append(entry)
        if not consumed:
            rejected_drafts.append(
                {
                    "lane_id": lane_id,
                    "reason": item.get("named_blocker")
                    or item.get("mode_invocation_status")
                    or "not_staged_for_merge",
                    "artifact_ref": item.get("artifact_ref"),
                }
            )
    sampled_files = [
        {
            "name": item.get("name"),
            "path": item.get("path"),
            "sha256": item.get("sha256"),
            "mtime_iso": item.get("mtime_iso"),
        }
        for item in source_entry.get("sampled_files", [])
        if isinstance(item, dict)
    ]
    support_lanes = [
        {
            "lane_id": item.get("lane_id"),
            "mode": item.get("mode"),
            "status": item.get("status"),
            "artifact_ref": item.get("artifact_ref"),
            "provider": item.get("selected_carrier_provider_id"),
            "qwen_prepaid_invocation": item.get("qwen_prepaid_invocation") is True,
            "fallback_reason": item.get("fallback_reason") or "",
        }
        for item in lane_results
        if item.get("mode") != "draft"
    ]
    token_cost = (
        spend_ledger.get("token_cost_spend")
        if isinstance(spend_ledger.get("token_cost_spend"), dict)
        else {}
    )
    next_wave_should_continue = not bool(named_blocker)
    fallback_next_wave_id = f"{safe_stem(wave_id)}-foreground-next"
    decision = {
        "schema_version": "xinao.codex_s.foreground_brain_decision.v1",
        "sentinel": "SENTINEL:XINAO_CODEX_S_FOREGROUND_BRAIN_DECISION_V1",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "decision_id": f"{safe_stem(wave_id)}.foreground_brain_decision",
        "owner": "foreground_codex_brain",
        "owner_role": "understand_split_dispatch_fanin_merge_correct_next_wave",
        "contract_kind": contract_kind,
        "control_plane_repair_mode": control_plane_repair,
        "source_entry_read_at": source_entry.get("source_entry_read_at") or "",
        "source_entry": source_entry,
        "user_latest_correction_digest": latest_correction,
        "333_alignment": {
            "highest_semantic_anchor": "333",
            "333_is_owner_semantic_line": True,
            "phase1_serves_333": True,
            "same_default_loop_not_owner": True,
            "productivity_mode_v2_not_authority": True,
            "meta_rsi_not_main_worker": True,
            "latest_json_not_completion_boundary": True,
            "desktop_memo_role": "mode memo serving 333, not new authority",
            "source_entry_role": "dynamic changing entry for understanding and dispatch",
        },
        "current_frontier": {
            "summary": (
                "Keep foreground Codex brain anchored on 333, latest correction, and dynamic "
                "source entry; dispatch DP as draft pool, then fan-in merge and decide next wave."
            ),
            "source_entry_root": source_entry.get("source_entry_root"),
            "sampled_file_count": source_entry.get("sampled_count"),
            "sampled_files": sampled_files,
            "support_lanes_available": len(support_lanes),
        },
        "worker_briefs_generated": {
            "brief_count": len(worker_briefs),
            "draft_brief_count": len(
                [brief for brief in worker_briefs if brief.get("mode") == "draft"]
            ),
            "mode_counts": mode_counts,
            "brief_ids": [brief.get("lane_id") for brief in worker_briefs],
        },
        "why_this_width": {
            "requested_target_width": target_width,
            "actual_target_width": sum(int(value or 0) for value in mode_counts.values()),
            "draft_is_primary": int(mode_counts.get("draft") or 0)
            > max(int(value or 0) for key, value in mode_counts.items() if key != "draft"),
            "reason": (
                "Evaluate a control-plane repair node with non-draft evidence lanes; do not "
                "misclassify liveness or repair work as a cheap draft pool."
                if control_plane_repair
                else "Use draft-heavy DP width for cheap parallel draft production; keep eval/audit/"
                "contradiction/extraction/citation_verify as support lanes and reserve merge "
                "ownership for foreground Codex brain."
            ),
        },
        "draft_artifacts_consumed": draft_artifacts_consumed,
        "merge_decision": {
            "merge_artifact": merge_consumer.get("merge_artifact") or "",
            "merged_count": merge_consumer.get("merged_count") or 0,
            "adopted_draft_count": len(
                [item for item in draft_artifacts_consumed if item["adopted_for_merge"]]
            ),
            "rejected_or_deferred_draft_count": len(rejected_drafts),
            "rejected_or_deferred_drafts": rejected_drafts,
            "support_lanes_consumed": support_lanes,
            "spend_entry_count": spend_ledger.get("spend_entry_count") or 0,
            "total_tokens": token_cost.get("total_tokens") or 0,
            "summary": (
                "Foreground brain accepted control-plane repair evidence without requiring draft staging."
                if control_plane_repair
                else "Foreground brain fan-in accepted staged DP drafts into one human-readable merge artifact."
            ),
        },
        "next_wave_decision": {
            "should_continue": next_wave_should_continue,
            "next_wave_id": next_wave_id or fallback_next_wave_id,
            "dispatch_basis": [
                "Re-read dynamic source entry instead of freezing two fixed texts.",
                "Carry latest user correction into every worker brief.",
                (
                    "For control-plane repair, require worker lane evidence and spend, not draft_count."
                    if control_plane_repair
                    else "Keep draft_count>0 and draft as primary DP mode."
                ),
                (
                    "Resume the existing workflow after repair evidence is written."
                    if control_plane_repair
                    else "Consume staged drafts through foreground brain merge before next dispatch."
                ),
            ],
            "if_blocked": "write named_blocker and do not claim completion",
        },
        "blocker_or_continue_reason": named_blocker
        or "CONTINUE_333_FOREGROUND_BRAIN_FANIN: source_entry, user correction, draft merge, and next dispatch remain active.",
        "same_default_loop_semantics": BACKGROUND_RUNNER_DOWNGRADE_FLAGS,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }
    decision["required_fields"] = FOREGROUND_BRAIN_REQUIRED_FIELDS
    decision["required_fields_present"] = all(
        field in decision
        and (
            bool(decision.get(field))
            or (control_plane_repair and field == "draft_artifacts_consumed")
        )
        for field in FOREGROUND_BRAIN_REQUIRED_FIELDS
    )
    decision["validation"] = {
        "passed": bool(decision["required_fields_present"])
        and int(source_entry.get("sampled_count") or 0) > 0
        and (
            (len(draft_artifacts_consumed) > 0 and int(merge_consumer.get("merged_count") or 0) > 0)
            or (control_plane_repair and len(support_lanes) > 0)
        ),
        "checks": {
            "required_fields_present": decision["required_fields_present"],
            "source_entry_dynamic_read": int(source_entry.get("sampled_count") or 0) > 0,
            "latest_user_correction_bound": latest_correction.get("task_id")
            == LATEST_USER_CORRECTION_TASK_ID,
            "333_alignment_bound": decision["333_alignment"]["333_is_owner_semantic_line"],
            "worker_briefs_generated": len(worker_briefs) > 0,
            "draft_artifacts_consumed": (
                True if control_plane_repair else len(draft_artifacts_consumed) > 0
            ),
            "merge_artifact_bound": (
                True if control_plane_repair else bool(merge_consumer.get("merge_artifact"))
            ),
            "next_wave_decision_written": bool(decision["next_wave_decision"]),
            "control_plane_repair_support_lanes_consumed": (
                True if not control_plane_repair else len(support_lanes) > 0
            ),
        },
    }
    if write:
        write_json(paths["foreground_brain_decision_latest"], decision)
        write_json(
            paths["records"] / f"{safe_stem(wave_id)}.foreground_brain_decision.json", decision
        )
    return decision


def build_trigger_binding(
    *,
    runtime: Path,
    wave_id: str,
    mode_counts: dict[str, int],
    contract_kind: str = PARALLEL_DRAFT_POOL_CONTRACT,
    runtime_enforced: bool = False,
    runtime_enforced_scope: str = "",
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    control_plane_repair = contract_kind == CONTROL_PLANE_REPAIR_CONTRACT
    payload = {
        "schema_version": "xinao.codex_s.modular_worker_pool_trigger_binding.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "contract_kind": contract_kind,
        "control_plane_repair_mode": control_plane_repair,
        "status": (
            "control_plane_repair_hot_path_bound"
            if control_plane_repair
            else "parallel_draft_to_merge_hot_path_bound"
        ),
        "hot_path": (
            "detect_blocker->repair_lanes->fan_in_repair_evidence->resume"
            if control_plane_repair
            else "parallel_draft->merge->writer"
        ),
        "trigger_shape": (
            "controller_detects_structural_blocker_then_routes_v4pro_repair_evidence"
            if control_plane_repair
            else "supervisor_brain_dispatches_dp_draft_pool_then_merge_consumer"
        ),
        "dp_worker_role": (
            "repair_support_worker" if control_plane_repair else "draft_main_worker_pool"
        ),
        "default_trigger_candidate_ref": str(
            runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
        ),
        "root_driver_dp_mode_counts": mode_counts,
        "draft_is_primary": (
            None
            if control_plane_repair
            else int(mode_counts.get("draft") or 0)
            > max(int(count or 0) for mode, count in mode_counts.items() if mode != "draft")
        ),
        "search_is_main_task": False,
        "provider_probe_used_as_progress": False,
        "watchdog_role": "downgraded_side_evidence_not_mainline",
        "runtime_enforced": runtime_enforced,
        "runtime_enforced_scope": runtime_enforced_scope if runtime_enforced else "",
        "trigger_installed": runtime_enforced,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["trigger_binding_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.trigger_binding.json", payload)
    return payload


def build_watchdog_downgrade(
    *,
    runtime: Path,
    wave_id: str,
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    payload = {
        "schema_version": "xinao.codex_s.modular_worker_pool_watchdog_downgrade.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "watchdog_downgraded_for_phase1_fast_path",
        "mainline": "parallel_draft->merge->writer",
        "watchdog_may_observe": True,
        "watchdog_may_block_safe_repair": False,
        "watchdog_may_drive_completion": False,
        "overnight_slow_poll_not_required": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["watchdog_downgrade_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.watchdog_downgrade.json", payload)
    return payload


def build_width_blocker(
    *,
    runtime: Path,
    wave_id: str,
    mode_counts: dict[str, int],
    lane_results: list[dict[str, Any]],
    spend_ledger: dict[str, Any],
    contract_kind: str = PARALLEL_DRAFT_POOL_CONTRACT,
    require_external_draft: bool = True,
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    width = sum(int(value or 0) for value in mode_counts.values())
    control_plane_repair = contract_kind == CONTROL_PLANE_REPAIR_CONTRACT
    draft_count = int(mode_counts.get("draft") or 0)
    true_dp_draft_count = len(
        [
            item
            for item in lane_results
            if item.get("mode") == "draft" and item.get("deepseek_dp_invocation") is True
        ]
    )
    qwen_prepaid_draft_count = len(
        [
            item
            for item in lane_results
            if item.get("mode") == "draft" and item.get("qwen_prepaid_invocation") is True
        ]
    )
    external_cheap_draft_count = len(
        [
            item
            for item in lane_results
            if item.get("mode") == "draft"
            and (
                item.get("qwen_prepaid_invocation") is True
                or item.get("deepseek_dp_invocation") is True
            )
        ]
    )
    local_stub_draft_count = len(
        [
            item
            for item in lane_results
            if item.get("mode") == "draft" and item.get("local_stub") is True
        ]
    )
    blockers: list[str] = []
    if width <= 1 and not control_plane_repair:
        blockers.append("WORKERPOOL_WIDTH_ONE")
    if draft_count <= 0 and not control_plane_repair:
        blockers.append("CHEAP_DRAFT_WIDTH_ZERO")
    if require_external_draft and external_cheap_draft_count <= 0 and not control_plane_repair:
        blockers.append("EXTERNAL_CHEAP_DRAFT_NOT_OBSERVED")
    if (
        require_external_draft
        and local_stub_draft_count >= max(1, external_cheap_draft_count)
        and not control_plane_repair
    ):
        blockers.append("LOCAL_STUB_USED_AS_DRAFT_POOL")
    qwen_required = [
        item for item in lane_results if item.get("qwen_prepaid_first_required") is True
    ]
    qwen_not_attempted = [
        item for item in qwen_required if item.get("qwen_prepaid_first_attempted") is not True
    ]
    qwen_bypassed_without_allowed_fallback = [
        item
        for item in qwen_required
        if item.get("qwen_prepaid_first_succeeded") is not True
        and item.get("fallback_allowed") is not True
    ]
    if qwen_not_attempted:
        blockers.append("QWEN_PREPAID_FIRST_NOT_ATTEMPTED")
    if qwen_bypassed_without_allowed_fallback:
        blockers.append("QWEN_PREPAID_FIRST_BYPASSED_WITHOUT_ALLOWED_FALLBACK")
    if int(spend_ledger.get("spend_entry_count") or 0) <= 0:
        blockers.append("TOKEN_SPEND_LEDGER_MISSING")
    rate_limit_errors = [
        str(item.get("rate_limit_error") or "")
        for item in lane_results
        if str(item.get("rate_limit_error") or "")
    ]
    payload = {
        "schema_version": "xinao.codex_s.width_blocker.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "width_blocker_clear" if not blockers else "width_blocker_present",
        "named_blockers": blockers,
        "named_blocker": blockers[0] if blockers else "",
        "contract_kind": contract_kind,
        "control_plane_repair_mode": control_plane_repair,
        "draft_pool_contract_required": not control_plane_repair,
        "suppressed_draft_pool_blockers": (
            [
                "CHEAP_DRAFT_WIDTH_ZERO",
                "EXTERNAL_CHEAP_DRAFT_NOT_OBSERVED",
                "LOCAL_STUB_USED_AS_DRAFT_POOL",
            ]
            if control_plane_repair and draft_count <= 0
            else []
        ),
        "target_width": width,
        "draft_count": draft_count,
        "true_dp_draft_count": true_dp_draft_count,
        "qwen_prepaid_draft_count": qwen_prepaid_draft_count,
        "external_cheap_draft_count": external_cheap_draft_count,
        "local_stub_draft_count": local_stub_draft_count,
        "qwen_prepaid_first_required_count": len(qwen_required),
        "qwen_prepaid_first_attempted_count": len(
            [item for item in qwen_required if item.get("qwen_prepaid_first_attempted") is True]
        ),
        "qwen_prepaid_first_succeeded_count": len(
            [item for item in qwen_required if item.get("qwen_prepaid_first_succeeded") is True]
        ),
        "deepseek_fallback_after_qwen_count": len(
            [
                item
                for item in qwen_required
                if item.get("fallback_from_provider_id") == QWEN_CHEAP_WORKER_PROVIDER_ID
            ]
        ),
        "qwen_fallback_allowed_count": len(
            [
                item
                for item in qwen_required
                if item.get("fallback_from_provider_id") == QWEN_CHEAP_WORKER_PROVIDER_ID
                and item.get("fallback_allowed") is True
            ]
        ),
        "require_external_draft": require_external_draft,
        "rate_limit_error": "; ".join(rate_limit_errors),
        "width_one_requires_named_blocker": True,
        "provider_probe_used_as_progress": False,
        "search_used_as_execute_progress": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["width_blocker_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.width_blocker.json", payload)
    return payload


def build_blocker_repair_escalation(
    *,
    runtime: Path,
    wave_id: str,
    workflow_id: str,
    workflow_run_id: str,
    assignment_dag_node_id: str,
    contract_kind: str,
    mode_counts: dict[str, int],
    lane_results: list[dict[str, Any]],
    spend_ledger: dict[str, Any],
    width_blocker: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    control_plane_repair = contract_kind == CONTROL_PLANE_REPAIR_CONTRACT
    if not control_plane_repair:
        return {
            "status": "skipped_not_control_plane_repair",
            "contract_kind": contract_kind,
            "not_execution_controller": True,
        }
    paths = output_paths(runtime)
    latest_path = paths["blocker_repair_escalation_latest"]
    record_path = (
        paths["blocker_repair_escalation_records"]
        / f"{safe_stem(wave_id)}.{safe_stem(assignment_dag_node_id)}.json"
    )
    lane_count = len(lane_results)
    succeeded_count = len([item for item in lane_results if item.get("status") == "succeeded"])
    spend_entry_count = int(spend_ledger.get("spend_entry_count") or 0)
    checks = {
        "workflow_id_present": bool(workflow_id),
        "workflow_run_id_present": bool(workflow_run_id),
        "assignment_dag_node_bound": bool(assignment_dag_node_id),
        "non_draft_control_plane_contract": int(mode_counts.get("draft") or 0) == 0,
        "lane_results_present": lane_count > 0,
        "lane_results_succeeded": succeeded_count == lane_count and lane_count > 0,
        "spend_recorded_for_lanes": spend_entry_count == lane_count and lane_count > 0,
        "width_blocker_not_blocking_draft_pool": not bool(width_blocker.get("named_blocker")),
        "external_mature_sources_bound": bool(CONTROL_PLANE_REPAIR_MATURE_SOURCES),
        "codex_final_acceptance_deferred": True,
    }
    ready = all(checks.values())
    payload = {
        "schema_version": "xinao.codex_s.blocker_repair_escalation.v1",
        "sentinel": "SENTINEL:XINAO_CODEX_S_BLOCKER_REPAIR_ESCALATION_READY",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "assignment_dag_node_id": assignment_dag_node_id,
        "contract_kind": contract_kind,
        "trigger_kind": "structural_blocker_repair",
        "previous_blocker_symptom": "CHEAP_DRAFT_WIDTH_ZERO",
        "repair_action": (
            "Classify heartbeat/control-plane/liveness non-draft assignment DAG nodes "
            "as control_plane_repair, not parallel_draft_pool."
        ),
        "repair_provider_policy": {
            "default_brain_provider": "deepseek_v4_pro",
            "codex_role": "final_acceptance_only_or_deferred",
            "qwen_local_role": "cheap extraction or local draft lane, not structural repair owner",
            "external_mature_research_required": True,
        },
        "external_mature_sources": CONTROL_PLANE_REPAIR_MATURE_SOURCES,
        "lane_count": lane_count,
        "succeeded_count": succeeded_count,
        "spend_entry_count": spend_entry_count,
        "mode_counts": mode_counts,
        "width_blocker_ref": str(paths["width_blocker_latest"]),
        "latest_ref": str(latest_path),
        "record_ref": str(record_path),
        "status": (
            "blocker_repair_escalation_ready" if ready else "blocker_repair_escalation_blocked"
        ),
        "named_blocker": "" if ready else "BLOCKER_REPAIR_ESCALATION_NOT_READY",
        "validation": {
            "passed": ready,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(record_path, payload)
        write_json(latest_path, payload)
    return payload


def write_parallel_draft_batch(
    *,
    runtime: Path,
    wave_id: str,
    lane_results: list[dict[str, Any]],
    spend_ledger: dict[str, Any],
    merge_consumer: dict[str, Any],
    write: bool,
) -> dict[str, str]:
    paths = output_paths(runtime)
    batch_dir = paths["parallel_draft_batch_dir"]
    stem = safe_stem(wave_id)
    batch_path = batch_dir / f"{stem}.json"
    cost_path = batch_dir / f"{stem}.cost.json"
    merge_review_path = batch_dir / f"{stem}.merge_review.json"
    batch_payload = {
        "schema_version": "xinao.codex_s.parallel_draft_batch.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "parallel_draft_batch_ready",
        "draft_lanes": [item for item in lane_results if item.get("mode") == "draft"],
        "support_lanes": [item for item in lane_results if item.get("mode") != "draft"],
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    merge_review = {
        "schema_version": "xinao.codex_s.parallel_draft_batch_merge_review.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "merge_review_ready",
        "merge_consumer_ref": str(paths["merge_consumer_latest"]),
        "merge_artifact": merge_consumer.get("merge_artifact"),
        "merged_count": merge_consumer.get("merged_count"),
        "supervisor_brain_provider": "Codex S",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(batch_path, batch_payload)
        write_json(cost_path, spend_ledger)
        write_json(merge_review_path, merge_review)
        write_json(paths["parallel_draft_batch_latest"], batch_payload)
    return {
        "parallel_draft_batch": str(batch_path),
        "parallel_cost_ledger": str(cost_path),
        "parallel_merge_review": str(merge_review_path),
        "parallel_draft_batch_latest": str(paths["parallel_draft_batch_latest"]),
    }


def assignment_node_from_worker_assignment(
    worker_assignment: dict[str, Any],
    assignment_dag_node_id: str,
) -> dict[str, Any]:
    dag = (
        worker_assignment.get("assignment_dag")
        if isinstance(worker_assignment.get("assignment_dag"), dict)
        else {}
    )
    nodes = dag.get("nodes") if isinstance(dag.get("nodes"), list) else []
    for node in nodes:
        if isinstance(node, dict) and str(node.get("id") or "") == assignment_dag_node_id:
            return node
    return {}


def write_assignment_dag_node_evidence(
    *,
    runtime: Path,
    wave_id: str,
    assignment_dag_node_id: str,
    workflow_id: str,
    workflow_run_id: str,
    worker_assignment: dict[str, Any],
    worker_briefs: list[dict[str, Any]],
    lane_results: list[dict[str, Any]],
    staging_queue: dict[str, Any],
    merge_consumer: dict[str, Any],
    spend_ledger: dict[str, Any],
    parallel_draft_batch_refs: dict[str, str],
    work_package: dict[str, Any] | None = None,
    contract_kind: str = PARALLEL_DRAFT_POOL_CONTRACT,
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    node_id = assignment_dag_node_id or ASSIGNMENT_DAG_NODE_ID
    package = work_package if isinstance(work_package, dict) else {}
    package_lanes = work_package_lanes(package, node_id)
    package_lane_ids = [str(lane.get("lane_id") or "") for lane in package_lanes]
    evidence_dir = paths["assignment_dag_node_evidence_dir"]
    latest_path = evidence_dir / "latest.json"
    node_latest_path = evidence_dir / f"{safe_stem(node_id)}.latest.json"
    workflow_run_latest_path = (
        evidence_dir
        / "workflow_runs"
        / safe_stem(workflow_id or "workflow-unbound")
        / safe_stem(workflow_run_id or "run-unbound")
        / f"{safe_stem(node_id)}.latest.json"
    )
    jsonl_path = evidence_dir / f"{safe_stem(node_id)}.jsonl"
    node = assignment_node_from_worker_assignment(worker_assignment, node_id)
    dag = (
        worker_assignment.get("assignment_dag")
        if isinstance(worker_assignment.get("assignment_dag"), dict)
        else {}
    )
    lane_bindings = []
    result_by_lane = {str(item.get("lane_id") or ""): item for item in lane_results}
    for brief in worker_briefs:
        lane_id = str(brief.get("lane_id") or "")
        result = result_by_lane.get(lane_id, {})
        route = brief.get("provider_route") if isinstance(brief.get("provider_route"), dict) else {}
        preferred_provider_id = str(route.get("preferred_provider_id") or "")
        selected_carrier_provider_id = str(
            result.get("selected_carrier_provider_id")
            or result.get("provider")
            or preferred_provider_id
        )
        lane_bindings.append(
            {
                "lane_id": lane_id,
                "source_wave_id": str(brief.get("source_wave_id") or wave_id),
                "source_wave_digest": str(
                    brief.get("source_wave_digest") or wave_digest_stem(wave_id)
                ),
                "mode": str(brief.get("mode") or ""),
                "provider_role": str(route.get("provider_role") or ""),
                "preferred_provider_id": preferred_provider_id,
                "selected_carrier_provider_id": selected_carrier_provider_id,
                "status": str(result.get("status") or "not_returned"),
                "artifact_ref": str(result.get("artifact_ref") or ""),
                "outputs_to_staging_only": True,
                "direct_repo_write_allowed": False,
                "artifact_acceptance_required": True,
                "not_execution_controller": True,
            }
        )
    draft_count = int(staging_queue.get("draft_count") or 0)
    staged_count = int(staging_queue.get("staged_count") or 0)
    merged_count = int(merge_consumer.get("merged_count") or 0)
    control_plane_repair = contract_kind == CONTROL_PLANE_REPAIR_CONTRACT
    evidence_checks = {
        "workflow_id_present": bool(workflow_id),
        "workflow_run_id_present": bool(workflow_run_id),
        "assignment_dag_node_found": bool(node),
        "lane_bindings_present": bool(lane_bindings),
        "explicit_work_package_lanes_bound": True
        if not package_lanes
        else all(
            lane_id in {str(item.get("lane_id") or "") for item in lane_bindings}
            for lane_id in package_lane_ids
        ),
        "staging_ref_present": bool(paths["draft_staging_latest"]),
        "merge_ref_present": bool(paths["merge_consumer_latest"]),
        "staged_count_positive": True if control_plane_repair else staged_count > 0,
        "merged_count_positive": True if control_plane_repair else merged_count > 0,
        "control_plane_repair_lane_results_present": (
            True if not control_plane_repair else bool(lane_bindings)
        ),
        "completion_claim_denied": True,
    }
    missing_evidence_checks = [key for key, value in evidence_checks.items() if value is not True]
    evidence_ready = not missing_evidence_checks
    event_payload = {
        "schema_version": "xinao.codex_s.assignment_dag_node_task_bound_evidence.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": WORK_ID,
        "phase_task_id": TASK_ID,
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "workflow_id_present": evidence_checks["workflow_id_present"],
        "workflow_run_id_present": evidence_checks["workflow_run_id_present"],
        "assignment_dag_node_id": node_id,
        "assignment_dag_node_found": evidence_checks["assignment_dag_node_found"],
        "next_ready_node_id": str(dag.get("next_ready_node_id") or ""),
        "current_active_node_id": str(dag.get("current_active_node_id") or ""),
        "node_status": str(node.get("status") or ""),
        "contract_kind": contract_kind,
        "control_plane_repair_mode": control_plane_repair,
        "status": (
            "assignment_dag_node_evidence_written"
            if evidence_ready
            else "assignment_dag_node_evidence_blocked"
        ),
        "source_kind": (
            "assignment_dag_auto_continue_control_plane_repair"
            if control_plane_repair
            else "assignment_dag_auto_continue_implementation_worker"
        ),
        "worker_kind": (
            "control_plane_repair_worker" if control_plane_repair else "implementation_worker"
        ),
        "phase_scope": "assignment_dag_auto_continue",
        "objective": (
            "Execute assignment_dag next_ready_node_id="
            + node_id
            + " under the existing Temporal workflow; write task-bound JSONL evidence."
        ),
        "explicit_work_package_bound": bool(package_lanes),
        "work_package_digest_sha256": sha256_json(package) if package else "",
        "work_package_objective": str(package.get("objective") or "") if package else "",
        "explicit_work_package_lane_ids": package_lane_ids,
        "lane_count": len(lane_bindings),
        "draft_count": draft_count,
        "staged_count": staged_count,
        "merged_count": merged_count,
        "spend_entry_count": int(spend_ledger.get("spend_entry_count") or 0),
        "provider_tier_usage": spend_ledger.get("provider_tier_usage") or {},
        "token_cost_spend": spend_ledger.get("token_cost_spend") or {},
        "lane_bindings": lane_bindings,
        "named_blocker": ""
        if evidence_ready
        else "ASSIGNMENT_DAG_NODE_TEMPORAL_EVIDENCE_NOT_READY",
        "blocker_reasons": missing_evidence_checks,
        "staging_queue_ref": str(paths["draft_staging_latest"]),
        "merge_consumer_ref": str(paths["merge_consumer_latest"]),
        "spend_ledger_ref": str(paths["spend_ledger_latest"]),
        "parallel_draft_batch_refs": parallel_draft_batch_refs,
        "worker_assignment_ref": str(paths["global_worker_assignment"]),
        "latest_ref": str(latest_path),
        "node_latest_ref": str(node_latest_path),
        "workflow_run_latest_ref": str(workflow_run_latest_path),
        "jsonl_ref": str(jsonl_path),
        "jsonl_path": str(jsonl_path),
        "verification": ["assignment_dag node evidence written"],
        "validation": {
            "passed": evidence_ready,
            "checks": evidence_checks,
            "validated_at": now_iso(),
        },
        "spawn_new_owner_allowed": False,
        "pump_default_used": False,
        "phase_boundary_ready": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "next_machine_action": "fan_in_staging_merge_spend",
        "generated_at": now_iso(),
    }
    event_payload["event_id"] = sha256_json(
        {
            "work_id": WORK_ID,
            "phase_task_id": TASK_ID,
            "wave_id": wave_id,
            "assignment_dag_node_id": node_id,
            "generated_at": event_payload["generated_at"],
        }
    )
    event_payload["record_digest_sha256"] = sha256_json(event_payload)
    if write:
        append_jsonl(jsonl_path, event_payload)
        write_json(latest_path, event_payload)
        write_json(node_latest_path, event_payload)
        write_json(workflow_run_latest_path, event_payload)
    return {
        **event_payload,
        "latest_ref": str(latest_path),
        "node_latest_ref": str(node_latest_path),
        "workflow_run_latest_ref": str(workflow_run_latest_path),
        "jsonl_ref": str(jsonl_path),
        "jsonl_written": jsonl_path.is_file() if write else True,
    }


def write_phase_boundary_named_blocker(
    *,
    runtime: Path,
    wave_id: str,
    assignment_dag_node_id: str,
    assignment_dag_node_evidence: dict[str, Any],
    next_wave_id: str = "",
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    boundary_dir = paths["phase_boundary_dir"]
    latest_path = boundary_dir / "latest.json"
    jsonl_path = boundary_dir / "phase_boundary_named_blocker.jsonl"
    workflow_id = str(assignment_dag_node_evidence.get("workflow_id") or "")
    workflow_run_id = str(assignment_dag_node_evidence.get("workflow_run_id") or "")
    workflow_run_latest_path = (
        boundary_dir
        / "workflow_runs"
        / safe_stem(workflow_id or "workflow-unbound")
        / safe_stem(workflow_run_id or "run-unbound")
        / "phase_boundary_named_blocker.latest.json"
    )
    loop_state_ref = runtime / "state" / "loop_runtime_state" / "latest.json"
    phase3_latest_ref = (
        runtime
        / "state"
        / "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
        / "latest.json"
    )
    loop_state = read_json(loop_state_ref)
    stop = loop_state.get("stop") if isinstance(loop_state.get("stop"), dict) else {}
    reason_flags = stop.get("reason_flags") if isinstance(stop.get("reason_flags"), dict) else {}
    active_reasons = [key for key, value in reason_flags.items() if value is True] or [
        "fan_in_staging_merge_spend_pending"
    ]
    task_backlog = (
        loop_state.get("task_backlog") if isinstance(loop_state.get("task_backlog"), list) else []
    )
    ready_frontier = (
        loop_state.get("ready_frontier")
        if isinstance(loop_state.get("ready_frontier"), list)
        else []
    )
    next_frontier = (
        loop_state.get("next_frontier") if isinstance(loop_state.get("next_frontier"), list) else []
    )
    loop_state_next_wave_id = ""
    if next_frontier and isinstance(next_frontier[0], dict):
        loop_state_next_wave_id = str(next_frontier[0].get("wave_id") or "")
    explicit_next_wave_id = str(next_wave_id or "")
    selected_next_wave_id = (
        explicit_next_wave_id
        if explicit_next_wave_id and explicit_next_wave_id != wave_id
        else loop_state_next_wave_id
        if loop_state_next_wave_id and loop_state_next_wave_id != wave_id
        else ""
    )
    next_machine_action = (
        f"consume queued {selected_next_wave_id} through existing Temporal workflow; then fan_in_staging_merge_spend"
        if selected_next_wave_id
        else str(
            assignment_dag_node_evidence.get("next_machine_action") or "fan_in_staging_merge_spend"
        )
    )
    assignment_dag_node_id = str(
        assignment_dag_node_evidence.get("assignment_dag_node_id") or ASSIGNMENT_DAG_NODE_ID
    )
    payload = {
        "schema_version": "xinao.codex_s.phase_boundary_named_blocker.v1",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": WORK_ID,
        "phase_task_id": TASK_ID,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "wave_id": wave_id,
        "assignment_dag_node_id": assignment_dag_node_id or ASSIGNMENT_DAG_NODE_ID,
        "named_blocker": "PHASE_BOUNDARY_NOT_READY_CONTINUE_REQUIRED",
        "blocker_reason": "continue_required:" + ",".join(active_reasons),
        "phase_boundary_ready": False,
        "stop_allowed": stop.get("stop_allowed") is True,
        "task_backlog_count": len(task_backlog),
        "ready_frontier_count": len(ready_frontier),
        "next_frontier_count": len(next_frontier),
        "next_wave_id": selected_next_wave_id,
        "explicit_next_wave_id": explicit_next_wave_id,
        "loop_runtime_state_next_wave_id": loop_state_next_wave_id,
        "next_machine_action": next_machine_action,
        "evidence_refs": {
            "assignment_dag_node_evidence": str(
                assignment_dag_node_evidence.get("workflow_run_latest_ref")
                or assignment_dag_node_evidence.get("latest_ref")
                or ""
            ),
            "assignment_dag_node_jsonl": str(assignment_dag_node_evidence.get("jsonl_ref") or ""),
            "loop_runtime_state": str(loop_state_ref),
            "temporal_phase3_latest": str(phase3_latest_ref),
            "modular_phase1_latest": str(paths["latest"]),
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    payload["record_digest_sha256"] = sha256_json(payload)
    if write:
        append_jsonl(jsonl_path, payload)
        write_json(latest_path, payload)
        write_json(workflow_run_latest_path, payload)
    return {
        **payload,
        "latest_ref": str(latest_path),
        "workflow_run_latest_ref": str(workflow_run_latest_path),
        "jsonl_ref": str(jsonl_path),
        "jsonl_written": jsonl_path.is_file() if write else True,
    }


def write_default_route_binding(
    *,
    runtime: Path,
    wave_id: str,
    runtime_enforced: bool = False,
    runtime_enforced_scope: str = "",
    runtime_enforced_requested: bool = False,
    runtime_enforced_blocker: str = "",
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    scheduler_paths = provider_scheduler_paths(runtime)
    provider_scheduler_latest = scheduler_paths["latest"]
    provider_scheduler_policy = scheduler_paths["qwen_prepaid_policy"]
    provider_scheduler_invocation = scheduler_paths["qwen_invocation"]
    provider_scheduler_manifest = scheduler_paths["capability_manifest"]
    provider_latest = read_json(provider_scheduler_latest)
    qwen_invocation = read_json(provider_scheduler_invocation)
    provider_manifest = read_json(provider_scheduler_manifest)
    qwen_worker_invocation_latest = (
        runtime
        / "state"
        / "modular_dynamic_worker_pool_phase1"
        / "qwen_worker_invocation"
        / "latest.json"
    )
    qwen_worker_invocation = read_json(qwen_worker_invocation_latest)
    qwen_worker_payload = (
        qwen_worker_invocation.get("provider_payload")
        if isinstance(qwen_worker_invocation.get("provider_payload"), dict)
        else {}
    )
    qwen_scheduler_canary_ready = qwen_invocation.get("status") == "qwen_dashscope_canary_ready"
    qwen_worker_model_ready = (
        qwen_worker_invocation.get("status") == "qwen_cheap_worker_lane_ready"
        and qwen_worker_payload.get("carrier_provider_id") == "qwen_dashscope"
        and qwen_worker_payload.get("provider_id") == "qwen_prepaid_cheap_worker"
        and qwen_worker_payload.get("model_invocation_performed") is True
        and not str(qwen_worker_payload.get("named_blocker") or "")
    )
    qwen_dashscope_ready = qwen_scheduler_canary_ready or qwen_worker_model_ready
    provider_scheduler_ready = (
        provider_latest.get("status") == "codex_native_provider_scheduler_ready"
        and qwen_dashscope_ready
        and provider_manifest.get("status") == "registered"
        and provider_latest.get("codex_brain_only_default") is True
        and provider_latest.get("codex_bulk_worker_default_paused") is True
    )
    payload = {
        "schema_version": "xinao.codex_s.modular_dynamic_worker_pool_default_route_binding.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": (
            "global_default_runtime_enforced"
            if runtime_enforced
            else "global_default_candidate_blocked"
            if runtime_enforced_requested
            else "default_route_discovery_bound"
        ),
        "adoption_state": (
            GLOBAL_DEFAULT_ADOPTION_STATE
            if runtime_enforced
            else GLOBAL_DEFAULT_BLOCKED_ADOPTION_STATE
            if runtime_enforced_requested
            else "default_hot_path_ready"
        ),
        "source_intent_package_ref": CURRENT_INTENT_PACKAGE_REF,
        "source_intent_package_id": "grok_faithful_modular_dynamic_worker_pool_20260704",
        "hot_path_shape": "parallel_draft->merge->writer",
        "dp_worker_role": "draft_main_worker_pool",
        "meaning_cn": (
            "phase1 新模式已冻结为全局默认执行入口；默认路线看到 phase1 provider/queue/policy/merge refs 后直接走 parallel_draft->merge->writer，并通过 phase4 ProviderScheduler 选择 Qwen-first、DeepSeek escalation、Codex brain/AAQ provider 层。"
            if runtime_enforced
            else "phase1 被请求作为全局默认，但账本/唯一 AAQ/validation 尚未全部对齐；保留候选阻断，不写 runtime_enforced。"
            if runtime_enforced_requested
            else "默认可发现，不是 runtime 强制执行；后续默认路线能看到 phase1 provider/queue/policy/merge refs，并发现 phase4 ProviderScheduler provider 层。"
        ),
        "missing_to_runtime_enforced_cn": ""
        if runtime_enforced and provider_scheduler_ready
        else "还需 validation.passed、worker_dispatch_ledger.succeeded_count 对齐 actual_completed_width、AAQ 唯一 artifact 验收通过，并由 focused verifier 证明。",
        "capability_gateway_provider_id": "codex_s.modular_dynamic_worker_pool_phase1",
        "provider_scheduler_default_layer": {
            "provider_id": PROVIDER_SCHEDULER_CAPABILITY_ID,
            "task_id": PROVIDER_SCHEDULER_TASK_ID,
            "status": "ready" if provider_scheduler_ready else "blocked_or_not_refreshed",
            "role": "default_provider_scheduler_for_qwen_deepseek_codex_brain_routing",
            "latest_ref": str(provider_scheduler_latest),
            "qwen_prepaid_policy_ref": str(provider_scheduler_policy),
            "qwen_invocation_ref": str(provider_scheduler_invocation),
            "qwen_worker_invocation_ref": str(qwen_worker_invocation_latest),
            "capability_manifest_ref": str(provider_scheduler_manifest),
            "qwen_prepaid_cheap_worker_default_first": (
                provider_latest.get("qwen_prepaid_cheap_worker_default_first") is True
            ),
            "qwen_dashscope_canary_ready": qwen_dashscope_ready,
            "qwen_dashscope_canary_source": (
                "provider_scheduler_qwen_invocation"
                if qwen_scheduler_canary_ready
                else "phase1_qwen_worker_invocation"
                if qwen_worker_model_ready
                else ""
            ),
            "codex_native_default_primary": provider_latest.get("codex_native_default_primary")
            is True,
            "codex_brain_only_default": provider_latest.get("codex_brain_only_default") is True,
            "codex_bulk_worker_default_paused": provider_latest.get(
                "codex_bulk_worker_default_paused"
            )
            is True,
            "default_token_saving_worker_route": provider_latest.get(
                "default_token_saving_worker_route"
            )
            is True,
            "codex_brain_only_budget": provider_latest.get("codex_brain_only_budget", {}),
            "outputs_to_staging_only": True,
            "direct_repo_write_allowed": False,
            "secret_policy": "default route stores refs/status only; key values stay in runtime private config/env",
            "not_execution_controller": True,
            "not_completion_boundary": True,
        },
        "default_trigger_candidate_ref": str(
            runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
        ),
        "worker_assignment_ref": str(paths["worker_assignment"]),
        "runtime_latest": str(paths["latest"]),
        "parallel_draft_batch_latest": str(paths["parallel_draft_batch_latest"]),
        "runtime_enforced": runtime_enforced,
        "runtime_enforced_scope": runtime_enforced_scope if runtime_enforced else "",
        "runtime_enforced_requested": runtime_enforced_requested,
        "runtime_enforced_blocker": runtime_enforced_blocker,
        "trigger_installed": runtime_enforced,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["default_route_binding_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.default_route_binding.json", payload)
    return payload


def write_artifact_acceptance(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    workflow_id: str,
    workflow_run_id: str,
    merge_consumer: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    if not write:
        return {"status": "skipped_no_write"}
    try:
        src = repo / "src"
        for path in (str(src), str(repo)):
            if path not in sys.path:
                sys.path.insert(0, path)
        from xinao_seedlab.adapters.local_fs import to_plain
        from xinao_seedlab.application.seed_cortex import build_default_service

        service = build_default_service(runtime, repo_root=repo)
        payload = service.artifact_acceptance_queue(
            f"{TASK_ID}-{safe_stem(wave_id)}",
            [
                {
                    "candidate_id": f"{safe_stem(wave_id)}-merge-review",
                    "artifact_ref": str(merge_consumer.get("merge_artifact") or ""),
                    "artifact_kind": "merge_review",
                    "workflow_id": workflow_id,
                    "workflow_run_id": workflow_run_id,
                    "accepted_for": "next_frontier_evidence",
                }
            ],
            write_runtime=True,
        )
        return to_plain(payload)
    except Exception as exc:
        return {
            "schema_version": "xinao.codex_s.artifact_acceptance_queue_invocation.v1",
            "status": "artifact_acceptance_queue_blocked",
            "named_blocker": f"AAQ_INVOCATION_FAILED:{type(exc).__name__}",
            "error": str(exc),
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        }


def write_fan_in_staging_merge_spend_evidence(
    *,
    runtime: Path,
    wave_id: str,
    workflow_id: str,
    workflow_run_id: str,
    staging_queue: dict[str, Any],
    merge_consumer: dict[str, Any],
    spend_ledger: dict[str, Any],
    artifact_acceptance: dict[str, Any],
    foreground_brain_decision: dict[str, Any],
    assignment_dag_node_evidence: dict[str, Any],
    phase_boundary_named_blocker: dict[str, Any],
    contract_kind: str = PARALLEL_DRAFT_POOL_CONTRACT,
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    latest_path = paths["fan_in_staging_merge_spend_latest"]
    jsonl_path = paths["fan_in_staging_merge_spend_jsonl"]
    record_path = paths["records"] / f"{safe_stem(wave_id)}.fan_in_staging_merge_spend.json"
    workflow_run_latest_path = (
        paths["fan_in_staging_merge_spend_dir"]
        / "workflow_runs"
        / safe_stem(workflow_id or "workflow-unbound")
        / safe_stem(workflow_run_id or "run-unbound")
        / "latest.json"
    )
    next_wave_decision = (
        foreground_brain_decision.get("next_wave_decision")
        if isinstance(foreground_brain_decision.get("next_wave_decision"), dict)
        else {}
    )
    staged_count = int(staging_queue.get("staged_count") or 0)
    merged_count = int(merge_consumer.get("merged_count") or 0)
    spend_entry_count = int(spend_ledger.get("spend_entry_count") or 0)
    accepted_artifact_count = int(artifact_acceptance.get("accepted_artifact_count") or 0)
    unique_accepted_artifact_count = int(
        artifact_acceptance.get("unique_accepted_artifact_count") or 0
    )
    control_plane_repair = contract_kind == CONTROL_PLANE_REPAIR_CONTRACT
    checks = {
        "workflow_id_present": bool(workflow_id),
        "workflow_run_id_present": bool(workflow_run_id),
        "assignment_dag_node_evidence_written": (
            assignment_dag_node_evidence.get("status") == "assignment_dag_node_evidence_written"
        ),
        "staging_wave_bound": str(staging_queue.get("wave_id") or "") == wave_id,
        "merge_wave_bound": str(merge_consumer.get("wave_id") or "") == wave_id,
        "spend_wave_bound": str(spend_ledger.get("wave_id") or "") == wave_id,
        "staged_count_positive": True if control_plane_repair else staged_count > 0,
        "merged_count_positive": True if control_plane_repair else merged_count > 0,
        "spend_entry_count_positive": spend_entry_count > 0,
        "artifact_acceptance_queue_accepted": (
            True if control_plane_repair else unique_accepted_artifact_count > 0
        ),
        "artifact_acceptance_queue_unique_count_bound": accepted_artifact_count
        == unique_accepted_artifact_count
        and (unique_accepted_artifact_count > 0 or control_plane_repair),
        "foreground_next_wave_decision_present": bool(next_wave_decision),
        "control_plane_repair_lane_results_present": (
            True
            if not control_plane_repair
            else int(assignment_dag_node_evidence.get("lane_count") or 0) > 0
        ),
        "completion_claim_denied": True,
    }
    missing = [key for key, value in checks.items() if value is not True]
    ready = not missing
    assignment_dag_node_id = str(
        assignment_dag_node_evidence.get("assignment_dag_node_id") or ASSIGNMENT_DAG_NODE_ID
    )
    payload = {
        "schema_version": "xinao.codex_s.fan_in_staging_merge_spend.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "assignment_dag_node_id": assignment_dag_node_id,
        "contract_kind": contract_kind,
        "control_plane_repair_mode": control_plane_repair,
        "fan_in_node_id": "fan_in_staging_merge_spend",
        "status": (
            "fan_in_staging_merge_spend_ready" if ready else "fan_in_staging_merge_spend_blocked"
        ),
        "named_blocker": "" if ready else "FAN_IN_STAGING_MERGE_SPEND_EVIDENCE_NOT_READY",
        "blocker_reasons": missing,
        "staging_ref": str(paths["draft_staging_latest"]),
        "merge_ref": str(paths["merge_consumer_latest"]),
        "spend_ref": str(paths["spend_ledger_latest"]),
        "aaq_ref": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "assignment_dag_node_evidence_ref": str(
            assignment_dag_node_evidence.get("workflow_run_latest_ref")
            or assignment_dag_node_evidence.get("latest_ref")
            or ""
        ),
        "phase_boundary_ref": str(
            phase_boundary_named_blocker.get("workflow_run_latest_ref")
            or phase_boundary_named_blocker.get("latest_ref")
            or ""
        ),
        "next_frontier_ref": str(paths["foreground_brain_decision_latest"]),
        "next_frontier": {
            "source": "foreground_brain_decision.next_wave_decision",
            "next_wave_id": str(next_wave_decision.get("next_wave_id") or ""),
            "should_continue": next_wave_decision.get("should_continue") is True,
            "dispatch_basis": next_wave_decision.get("dispatch_basis") or [],
        },
        "staged_count": staged_count,
        "merged_count": merged_count,
        "spend_entry_count": spend_entry_count,
        "accepted_artifact_count": accepted_artifact_count,
        "unique_accepted_artifact_count": unique_accepted_artifact_count,
        "provider_tier_usage": spend_ledger.get("provider_tier_usage") or {},
        "token_cost_spend": spend_ledger.get("token_cost_spend") or {},
        "record_ref": str(record_path),
        "latest_ref": str(latest_path),
        "workflow_run_latest_ref": str(workflow_run_latest_path),
        "jsonl_ref": str(jsonl_path),
        "validation": {
            "passed": ready,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    payload["record_digest_sha256"] = sha256_json(payload)
    if write:
        write_json(record_path, payload)
        write_json(latest_path, payload)
        write_json(workflow_run_latest_path, payload)
        append_jsonl(jsonl_path, payload)
    return {
        **payload,
        "jsonl_written": jsonl_path.is_file() if write else True,
    }


def refresh_capability_gateway(
    *,
    runtime: Path,
    repo: Path,
    write: bool,
) -> dict[str, Any]:
    if not write:
        return {"status": "skipped_no_write"}
    try:
        src = repo / "src"
        for path in (str(src), str(repo)):
            if path not in sys.path:
                sys.path.insert(0, path)
        from xinao_seedlab.application.seed_cortex import build_default_service

        service = build_default_service(runtime, repo_root=repo)
        return service.capability_gateway_snapshot(write_runtime=True)
    except Exception as exc:
        return {
            "status": "capability_gateway_refresh_blocked",
            "named_blocker": f"CAPABILITY_GATEWAY_REFRESH_FAILED:{type(exc).__name__}",
            "error": str(exc),
        }


def build_capability_evidence(
    *,
    runtime: Path,
    wave_id: str,
    latest_ref: str,
    merge_artifact: str,
    runtime_enforced: bool = False,
    runtime_enforced_scope: str = "",
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    manifest = {
        "schema_version": "xinao.codex_s.capability_manifest.v1",
        "provider_id": "codex_s.modular_dynamic_worker_pool_phase1",
        "task_id": TASK_ID,
        "capability_kinds": [
            "parallel_draft",
            "draft_staging_queue",
            "fan_in_merge",
            "spend_ledger",
            "readback",
            "default_route_discovery",
        ],
        "adoption_state": GLOBAL_DEFAULT_ADOPTION_STATE
        if runtime_enforced
        else "default_hot_path_ready",
        "invoke_command": (
            f"{s_venv_python()} -m xinao_seedlab.cli.__main__ modular-dynamic-worker-pool-phase1"
        ),
        "runtime_enforced": runtime_enforced,
        "runtime_enforced_scope": runtime_enforced_scope if runtime_enforced else "",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "validation": {"passed": True},
    }
    cheap_worker_pool_manifest = {
        "schema_version": "xinao.codex_s.capability_manifest.v1",
        "provider_id": "codex_s.modular_cheap_worker_pool.parallel_draft",
        "task_id": TASK_ID,
        "capability_kinds": [
            "cheap_parallel_draft",
            "qwen_prepaid_cheap_worker_first",
            "deepseek_dp_fallback",
            "parallel_draft_batch",
        ],
        "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
        "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
        "runtime_latest": str(paths["parallel_draft_batch_latest"]),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "validation": {"passed": True},
    }
    parallel_manifest = {
        "schema_version": "xinao.codex_s.capability_manifest.v1",
        "provider_id": "legacy.deepseek_dp_sidecar.parallel_draft",
        "task_id": TASK_ID,
        "capability_kinds": [
            "cheap_parallel_draft",
            "deepseek_dp_draft_worker_pool",
            "parallel_draft_batch",
        ],
        "reference_only_fallback_provider": True,
        "not_unique_default_primary": True,
        "runtime_latest": str(paths["parallel_draft_batch_latest"]),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "validation": {"passed": True},
    }
    invoke = {
        "schema_version": "xinao.codex_s.capability_invoke_evidence.v1",
        "provider_id": "codex_s.modular_dynamic_worker_pool_phase1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "invoke_performed": True,
        "invoke_kind": "parallel_draft_to_merge_wave",
        "latest_ref": latest_ref,
        "merge_artifact": merge_artifact,
        "runtime_enforced": runtime_enforced,
        "runtime_enforced_scope": runtime_enforced_scope if runtime_enforced else "",
        "generated_at": now_iso(),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    if write:
        write_json(paths["capability_manifest"], manifest)
        write_json(paths["cheap_worker_pool_capability_manifest"], cheap_worker_pool_manifest)
        write_json(paths["parallel_draft_capability_manifest"], parallel_manifest)
        write_json(paths["capability_invoke_latest"], invoke)
    return {
        "manifest": manifest,
        "cheap_worker_pool_manifest": cheap_worker_pool_manifest,
        "parallel_draft_manifest": parallel_manifest,
        "invoke": invoke,
    }


def run_meta_rsi_evidence(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    lane_results: list[dict[str, Any]],
    write: bool,
) -> dict[str, Any]:
    if not write:
        return {"status": "skipped_no_write", "role": "evidence_only_not_main_worker"}
    script = repo / "scripts" / "hardmode" / "Write-MetaRsiWave.ps1"
    if not script.is_file():
        return {
            "status": "skipped_script_missing",
            "role": "evidence_only_not_main_worker",
            "script": str(script),
        }
    lanes_json = json.dumps(
        [
            {"lane_id": item["lane_id"], "mode": item["mode"], "artifact_ref": item["artifact_ref"]}
            for item in lane_results
        ],
        ensure_ascii=False,
    )
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-TaskId",
        TASK_ID,
        "-WaveId",
        wave_id,
        "-Mode",
        "productivity_v2",
        "-ModeReason",
        "modular_dynamic_worker_pool_phase1_evidence_only",
        "-ZhReadback",
        "phase1 真波：DP=draft 主力；parallel_draft->merge->writer；meta_rsi=evidence_only_not_main_worker。",
        "-RuntimeRoot",
        str(runtime),
        "-LanesJson",
        lanes_json,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return {
            "status": "meta_rsi_evidence_failed",
            "role": "evidence_only_not_main_worker",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": "meta_rsi_evidence_written"
        if completed.returncode == 0
        else "meta_rsi_evidence_blocked",
        "role": "evidence_only_not_main_worker",
        "returncode": completed.returncode,
        "latest": str(runtime / "state" / "meta_rsi_wave" / "latest.json"),
        "stdout_digest_sha256": hashlib.sha256(
            (completed.stdout or "").encode("utf-8", errors="replace")
        ).hexdigest(),
        "stderr": (completed.stderr or "")[-1000:],
    }


def build_phase1_worker_ledger_entries(
    *,
    wave_id: str,
    lane_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    dispatch_time = now_iso()
    entries: list[dict[str, Any]] = []
    for item in lane_results:
        lane_id = str(item.get("lane_id") or "")
        ledger_lane_id = f"phase1-lane-{safe_stem(lane_id)}"
        succeeded = item.get("status") == "succeeded"
        artifact_refs = [
            str(item.get(key) or "")
            for key in (
                "artifact_ref",
                "draft_ref",
                "provider_invocation_ref",
                "provider_latest_ref",
                "raw_response_ref",
            )
            if str(item.get(key) or "").strip()
        ]
        if not artifact_refs:
            artifact_refs = [f"phase1_lane_result:{lane_id}"]
        entries.append(
            {
                "entry_id": f"{wave_id}:{ledger_lane_id}",
                "wave_id": wave_id,
                "task_id": TASK_ID,
                "lane_id": ledger_lane_id,
                "agent_id": lane_id,
                "provider": str(
                    item.get("selected_carrier_provider_id") or item.get("provider") or ""
                ),
                "mode": str(item.get("mode") or ""),
                "dispatch_time": dispatch_time,
                "poll_status": "succeeded" if succeeded else "blocked",
                "artifact_refs": artifact_refs,
                "fan_in_decision": (
                    "accepted_for_next_wave_dispatch" if succeeded else "staged_candidate_only"
                ),
                "next_wave_decision": (
                    "ledger_succeeded_drives_default_auto_dispatch"
                    if succeeded
                    else "blocked_waiting_worker_result"
                ),
                "adoption_state": "verifier_ready_but_not_hooked",
                "transport_pattern_ref": "codex_s_modular_dynamic_worker_pool_phase1_terminal_lane",
                "legacy_5d33_transport_pattern_reused": False,
                "legacy_5d33_owner_reused": False,
                "legacy_5d33_pass_reused": False,
                "legacy_5d33_latest_authority_reused": False,
                "phase1_lane_status": str(item.get("status") or ""),
                "mode_invocation_status": str(item.get("mode_invocation_status") or ""),
                "qwen_prepaid_first_required": item.get("qwen_prepaid_first_required") is True,
                "qwen_prepaid_first_attempted": item.get("qwen_prepaid_first_attempted") is True,
                "qwen_prepaid_first_succeeded": item.get("qwen_prepaid_first_succeeded") is True,
                "fallback_allowed": item.get("fallback_allowed") is True,
                "completion_claim_allowed": False,
                "not_source_of_truth": True,
                "not_user_completion": True,
                "not_completion_decision": True,
                "not_execution_controller": True,
            }
        )
    return entries


def write_phase1_worker_dispatch_ledger(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    workflow_id: str,
    workflow_run_id: str,
    lane_results: list[dict[str, Any]],
    completed_results: list[dict[str, Any]],
    write: bool,
) -> dict[str, Any]:
    try:
        from services.agent_runtime.worker_dispatch_ledger import build_worker_dispatch_ledger

        extra_entries = build_phase1_worker_ledger_entries(
            wave_id=wave_id,
            lane_results=lane_results,
        )
        payload = build_worker_dispatch_ledger(
            repo_root=repo,
            runtime_root=runtime,
            wave_id=wave_id,
            task_id=TASK_ID,
            extra_entries=extra_entries,
            poll_scope_lane_id_prefixes=("phase1-lane-",),
            runtime_entrypoint_invocation={
                "invoked_by": "modular_dynamic_worker_pool_phase1.run_wave",
                "runtime_enforced_scope": "seed_cortex_modular_dynamic_worker_pool_phase1_terminal_ledger_write",
                "runtime_enforced": True,
                "workflow_id": workflow_id,
                "workflow_run_id": workflow_run_id,
            },
            auto_dispatch_performed=False,
            write=write,
        )
    except Exception as exc:
        return {
            "schema_version": "xinao.codex_s.worker_dispatch_ledger.phase1_binding.v1",
            "status": "phase1_worker_dispatch_ledger_blocked",
            "named_blocker": f"PHASE1_WORKER_DISPATCH_LEDGER_WRITE_FAILED:{type(exc).__name__}",
            "error": str(exc),
            "wave_id": wave_id,
            "task_id": TASK_ID,
            "actual_completed_width": len(completed_results),
            "succeeded_count": 0,
            "validation": {"passed": False, "checks": {"ledger_write_failed": True}},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        }
    payload["phase1_binding"] = {
        "schema_version": "xinao.codex_s.worker_dispatch_ledger.phase1_binding.v1",
        "status": "phase1_worker_dispatch_ledger_aligned"
        if int(payload.get("succeeded_count") or 0) == len(completed_results)
        else "phase1_worker_dispatch_ledger_misaligned",
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "actual_completed_width": len(completed_results),
        "ledger_succeeded_count": int(payload.get("succeeded_count") or 0),
        "ledger_succeeded_matches_completed": int(payload.get("succeeded_count") or 0)
        == len(completed_results),
        "planned_is_progress": False,
        "progress_truth_fields": ["dispatched", "completed", "accepted"],
    }
    if write:
        output = (
            payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}
        )
        runtime_latest = str(output.get("runtime_latest") or "")
        poll_latest = str(output.get("poll_latest") or "")
        if runtime_latest:
            write_json(Path(runtime_latest), payload)
        if poll_latest and payload.get("poll_entries"):
            write_json(Path(poll_latest), payload)
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    checks = payload["validation"]["checks"]
    lines = [
        "# modular_dynamic_worker_pool_phase1 回读",
        "",
        SENTINEL,
        "",
        f"- task_id: `{payload['task_id']}`",
        f"- wave_id: `{payload['wave_id']}`",
        f"- status: `{payload['status']}`",
        f"- adoption_state: `{payload.get('adoption_state')}`",
        f"- runtime_enforced: {payload.get('runtime_enforced')}",
        f"- runtime_enforced_requested: {payload.get('runtime_enforced_requested')}",
        f"- runtime_enforced_blocker: `{payload.get('runtime_enforced_blocker')}`",
        f"- runtime_enforced_scope: `{payload.get('runtime_enforced_scope')}`",
        f"- runtime_enforcement_truth_chain_ready: {payload.get('runtime_enforcement_truth_chain', {}).get('ready')}",
        f"- python_carrier: `{payload.get('python_carrier', {}).get('current_python')}`",
        f"- expected_s_venv_python: `{payload.get('python_carrier', {}).get('expected_python')}`",
        f"- global_default_enforced: {payload.get('global_default_enforced')}",
        f"- metered: {payload.get('metered')}",
        f"- while_self_chain: `{json.dumps(payload.get('while_self_chain', {}), ensure_ascii=False)}`",
        f"- stage_order: `{payload['stage_order_text']}`",
        f"- target_width: {payload['target_width']}",
        f"- target_width_source: `{payload.get('target_width_source')}`",
        f"- width_decision_reason: `{payload.get('width_decision_reason')}`",
        f"- actual_dispatched_width: {payload['actual_dispatched_width']}",
        f"- actual_completed_width: {payload['actual_completed_width']}",
        f"- worker_dispatch_ledger_succeeded_count: {payload.get('worker_dispatch_ledger_succeeded_count')}",
        f"- ledger_succeeded_matches_completed: {payload.get('worker_dispatch_ledger_succeeded_matches_completed')}",
        f"- planned_is_progress: {payload.get('progress_counts', {}).get('planned_is_progress')}",
        f"- mode_counts: `{json.dumps(payload['mode_counts'], ensure_ascii=False)}`",
        f"- draft_count: {payload['draft_count']}",
        f"- true_dp_draft_count: {payload['true_dp_draft_count']}",
        f"- qwen_prepaid_draft_count: {payload.get('qwen_prepaid_draft_count')}",
        f"- external_cheap_draft_count: {payload.get('external_cheap_draft_count')}",
        f"- local_stub_draft_count: {payload['local_stub_draft_count']}",
        f"- qwen_prepaid_cheap_worker_ready: {payload.get('qwen_prepaid_cheap_worker_ready')}",
        f"- qwen_prepaid_first_required_count: {payload.get('qwen_prepaid_first_required_count')}",
        f"- qwen_prepaid_first_attempted_count: {payload.get('qwen_prepaid_first_attempted_count')}",
        f"- qwen_prepaid_first_succeeded_count: {payload.get('qwen_prepaid_first_succeeded_count')}",
        f"- qwen_fallback_allowed_count: {payload.get('qwen_fallback_allowed_count')}",
        f"- qwen_first_applies_only_to: `{payload.get('qwen_first_applies_only_to')}`",
        f"- eval_count: {payload['eval_count']}",
        f"- audit_count: {payload['audit_count']}",
        f"- staged_count: {payload['staged_count']}",
        f"- merged_count: {payload['merged_count']}",
        f"- spend_entry_count: {payload['spend_entry_count']}",
        f"- fan_in_staging_merge_spend: `{payload.get('evidence_refs', {}).get('fan_in_staging_merge_spend_latest')}`",
        f"- provider_tier_usage: `{json.dumps(payload['provider_tier_usage'], ensure_ascii=False)}`",
        f"- token_cost_spend: `{json.dumps(payload['token_cost_spend'], ensure_ascii=False)}`",
        f"- rate_limit_error: `{payload['rate_limit_error']}`",
        f"- named_blocker: `{payload['named_blocker']}`",
        f"- merge_artifact: `{payload['merge_artifact']}`",
        f"- source_entry_root: `{payload.get('source_entry_root')}`",
        f"- source_entry_read_at: `{payload.get('foreground_brain_decision', {}).get('source_entry_read_at')}`",
        f"- foreground_brain_decision: `{payload.get('evidence_refs', {}).get('foreground_brain_decision_latest')}`",
        f"- user_latest_correction: `{payload.get('user_latest_correction_digest', {}).get('task_id')}`",
        f"- default_route_adoption_state: `{payload['default_route_binding']['adoption_state']}`",
        f"- validation_passed: {payload['validation']['passed']}",
        f"- check.width_gte_3: {checks['width_gte_3']}",
        f"- check.draft_is_primary: {checks['draft_is_primary']}",
        f"- check.dp_not_search_or_probe_main: {checks['dp_not_search_or_probe_main']}",
        f"- check.external_cheap_draft_observed: {checks['external_cheap_draft_observed']}",
        f"- check.qwen_prepaid_first_attempted_when_required: {checks['qwen_prepaid_first_attempted_when_required']}",
        f"- check.qwen_prepaid_first_succeeded_or_allowed_fallback: {checks['qwen_prepaid_first_succeeded_or_allowed_fallback']}",
        f"- check.token_cost_spend_present: {checks['token_cost_spend_present']}",
        f"- check.metered_usage_for_every_lane: {checks['metered_usage_for_every_lane']}",
        f"- check.artifact_acceptance_queue_accepted: {checks['artifact_acceptance_queue_accepted']}",
        f"- check.fan_in_staging_merge_spend_written: {checks['fan_in_staging_merge_spend_written']}",
        f"- check.merge_artifact_exists: {checks['merge_artifact_exists']}",
        f"- check.foreground_brain_decision_has_required_fields: {checks['foreground_brain_decision_has_required_fields']}",
        f"- check.source_entry_dynamic_read: {checks['source_entry_dynamic_read']}",
        f"- check.333_alignment_bound: {checks['333_alignment_bound']}",
        "",
        "## 现在能 invoke 什么",
        "",
        "- cli: `python -m xinao_seedlab.cli.__main__ modular-dynamic-worker-pool-phase1`",
        "- service: `SeedCortexService.modular_dynamic_worker_pool_phase1(...)`",
        "- direct: `python -m services.agent_runtime.modular_dynamic_worker_pool_phase1`",
        "- callable: `services.agent_runtime.modular_dynamic_worker_pool_phase1.run_wave(...)`",
        "- capability: `codex_s.modular_dynamic_worker_pool_phase1`",
        "- cheap worker capability: `codex_s.modular_cheap_worker_pool.parallel_draft`",
        "- cheap worker pool: `qwen_prepaid_cheap_worker -> legacy.deepseek_dp_sidecar fallback`",
        "",
        "## 当前绑定",
        "",
        "- SupervisorBrainProvider: Codex S，负责切意图、发 brief、fan-in merge、writer/readback。",
        "- CheapWorkerProvider: Qwen prepaid cheap worker 只优先 draft/extraction/低风险 eval；DeepSeek/DP 是 fallback/并行补足/反证评审。",
        "- Qwen-first applies only to cheap_worker_lane；不得覆盖 quality_escalation/hard_reasoning/engineering_executor/final_merge。",
        "- Qwen/DP 都不是第二主脑，不是最终完成判定，不是 source owner；search/provider_probe 不算本主线进展。",
        "- local_* provider 只算 fallback/stub；不允许冒充真实 DP 草稿池。",
        "- productivity_mode_v2: false；meta_rsi 不作为本包主工。",
        "- default route: default_hot_path_ready = 默认可发现，不是 runtime 强制执行。",
        "- watchdog_status: downgraded_side_evidence_not_mainline；昨晚慢 poll/查账模式不参与本包验收。",
        "",
        "## Evidence",
        "",
    ]
    for key, value in payload["evidence_refs"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", SENTINEL, ""])
    return "\n".join(lines)


def run_wave(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "modular-dynamic-worker-pool-phase1-wave-001",
    target_width: int = 0,
    dynamic_width_decision: dict[str, Any] | None = None,
    write: bool = True,
    dp_invoker: DpInvoker | None = None,
    qwen_invoker: QwenInvoker | None = None,
    record_meta_rsi: bool = False,
    force_local_dp_draft: bool = False,
    require_external_draft: bool = True,
    max_parallel_workers: int | None = None,
    runtime_enforced: bool = False,
    runtime_enforced_scope: str = GLOBAL_DEFAULT_ENFORCED_SCOPE,
    while_chain_id: str = "",
    while_wave_index: int = 1,
    while_wave_count: int = 1,
    previous_wave_id: str = "",
    next_wave_id: str = "",
    assignment_dag_node_id: str = ASSIGNMENT_DAG_NODE_ID,
    workflow_id: str = "",
    workflow_run_id: str = "",
    work_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    source_entry = scan_source_entry()
    latest_correction = latest_user_correction_digest()
    package = work_package if isinstance(work_package, dict) else {}
    package_node_id = (
        assignment_dag_node_id
        or assignment_dag_node_id_from_work_package(package)
        or ASSIGNMENT_DAG_NODE_ID
    )
    package_lanes = work_package_lanes(package, package_node_id)
    decision = dynamic_width_decision if isinstance(dynamic_width_decision, dict) else {}
    if package_lanes:
        target_width = len(package_lanes)
        mode_counts = mode_counts_for_work_package_lanes(package_lanes)
        decision = {
            "target_width": target_width,
            "target_width_source": "explicit_assignment_dag_work_package",
            "width_decision_reason": (
                "target width and modes are bound to the existing Temporal "
                "assignment_dag work package supplied to the implementation worker"
            ),
            "width_decision_inputs": {
                "work_package_digest_sha256": sha256_json(package),
                "assignment_dag_node_id": package_node_id,
                "explicit_lane_count": len(package_lanes),
            },
            "width_candidates": {
                "explicit_work_package_lane_ids": [
                    str(lane.get("lane_id") or "") for lane in package_lanes
                ],
            },
            "operator_cap_applied": False,
            "recomputed_each_wave": True,
            "fixed_20_or_50_used": False,
        }
    else:
        decision_target_width = int(decision.get("target_width") or 0)
        if decision_target_width > 0:
            target_width = decision_target_width
        if int(target_width or 0) <= 0:
            target_width = derive_dynamic_target_width(
                source_entry=source_entry, latest_correction=latest_correction
            )
            decision = {
                "target_width": target_width,
                "target_width_source": "modular_phase1_bootstrap_dynamic_width",
                "width_decision_reason": (
                    "target_width derived from current source_entry sample count plus latest correction points; "
                    "Temporal phase3 replaces this bootstrap decision with provider/executor telemetry"
                ),
                "width_decision_inputs": {
                    "source_sampled_count": int(source_entry.get("sampled_count") or 0),
                    "correction_point_count": len(latest_correction.get("digest_points") or []),
                },
                "width_candidates": {},
                "operator_cap_applied": False,
                "recomputed_each_wave": True,
                "fixed_20_or_50_used": False,
            }
        mode_counts = mode_counts_for_width(target_width)
    contract_kind = work_package_contract_kind(package, package_node_id, package_lanes)
    control_plane_repair = contract_kind == CONTROL_PLANE_REPAIR_CONTRACT
    width = sum(int(value or 0) for value in mode_counts.values())
    provider_route_context = load_provider_route_context(runtime)
    provider_schemas = build_provider_schemas(runtime)
    if package_lanes:
        worker_briefs = build_worker_briefs_from_work_package(
            wave_id=wave_id,
            lanes=package_lanes,
            work_package=package,
            repo=repo,
            source_entry=source_entry,
            latest_correction=latest_correction,
            provider_route_context=provider_route_context,
        )
    else:
        worker_briefs = build_worker_briefs(
            wave_id=wave_id,
            mode_counts=mode_counts,
            repo=repo,
            source_entry=source_entry,
            latest_correction=latest_correction,
            provider_route_context=provider_route_context,
        )
    provider_schema_refs = write_provider_schema_surfaces(
        runtime=runtime,
        wave_id=wave_id,
        provider_schemas=provider_schemas,
        write=write,
    )
    dynamic_width_policy = build_dynamic_width_policy(
        runtime=runtime,
        wave_id=wave_id,
        target_width=target_width,
        mode_counts=mode_counts,
        actual_dispatched_width=0,
        actual_completed_width=0,
        width_decision=decision,
        write=write,
    )
    worker_brief_queue = write_worker_brief_queue(
        runtime=runtime,
        wave_id=wave_id,
        worker_briefs=worker_briefs,
        mode_counts=mode_counts,
        write=write,
    )
    worker_assignment = write_worker_assignment(
        runtime=runtime,
        wave_id=wave_id,
        assignment_dag_node_id=package_node_id,
        worker_briefs=worker_briefs,
        mode_counts=mode_counts,
        dynamic_width_policy=dynamic_width_policy,
        source_entry=source_entry,
        latest_correction=latest_correction,
        work_package=package,
        write=write,
    )
    invoker = dp_invoker or default_dp_invoker()
    qwen_lane_invoker = qwen_invoker or default_qwen_invoker()
    previous_force_local = os.environ.get("XINAO_FORCE_LOCAL_DP_DRAFT")
    if force_local_dp_draft:
        os.environ["XINAO_FORCE_LOCAL_DP_DRAFT"] = "1"
    try:
        lane_results: list[dict[str, Any]] = []
        worker_count = max_parallel_workers or min(max(1, len(worker_briefs)), 16)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_brief = {
                executor.submit(
                    run_lane,
                    runtime=runtime,
                    wave_id=wave_id,
                    brief=brief,
                    dp_invoker=invoker,
                    qwen_invoker=qwen_lane_invoker,
                    write=write,
                ): brief
                for brief in worker_briefs
            }
            for future in as_completed(future_to_brief):
                brief = future_to_brief[future]
                try:
                    lane_results.append(future.result())
                except Exception as exc:
                    lane_results.append(
                        {
                            "lane_id": str(brief.get("lane_id") or ""),
                            "mode": str(brief.get("mode") or ""),
                            "objective": str(brief.get("objective") or ""),
                            "status": "blocked",
                            "mode_invocation_status": "blocked",
                            "selected_carrier_provider_id": "",
                            "provider": "",
                            "model": "unknown",
                            "provider_tier": "blocked",
                            "provider_invocation_performed": False,
                            "model_invocation_performed": False,
                            "tool_invocation_performed": False,
                            "qwen_prepaid_invocation": False,
                            "deepseek_dp_invocation": False,
                            "qwen_prepaid_first_required": brief.get("provider_route", {}).get(
                                "qwen_prepaid_first_required"
                            )
                            is True,
                            "qwen_prepaid_first_attempted": False,
                            "qwen_prepaid_first_succeeded": False,
                            "fallback_from_provider_id": "",
                            "fallback_reason": "",
                            "fallback_allowed": False,
                            "qwen_attempt_ref": "",
                            "provider_route": brief.get("provider_route", {}),
                            "external_draft_invocation": False,
                            "local_stub": False,
                            "artifact_ref": "",
                            "draft_ref": "",
                            "artifact_exists": False,
                            "provider_invocation_ref": "",
                            "provider_latest_ref": "",
                            "raw_response_ref": "",
                            "claim_candidate": {},
                            "confidence": 0.0,
                            "risk": "lane_exception",
                            "usage": {
                                "prompt_tokens": 0,
                                "completion_tokens": 0,
                                "total_tokens": 0,
                                "metered_usage_observed": False,
                                "estimated_usage": False,
                                "cost_usd": 0.0,
                                "cost_source": "lane_exception",
                                "latency_ms": 0,
                            },
                            "rate_limit_error": "",
                            "named_blocker": f"LANE_EXECUTION_EXCEPTION:{type(exc).__name__}",
                            "error_message": str(exc),
                            "completion_claim_allowed": False,
                            "not_source_of_truth": True,
                            "not_user_completion": True,
                            "not_completion_decision": True,
                            "not_execution_controller": True,
                        }
                    )
    finally:
        if force_local_dp_draft:
            if previous_force_local is None:
                os.environ.pop("XINAO_FORCE_LOCAL_DP_DRAFT", None)
            else:
                os.environ["XINAO_FORCE_LOCAL_DP_DRAFT"] = previous_force_local
    lane_order = {str(brief["lane_id"]): int(brief["lane_number"]) for brief in worker_briefs}
    lane_results = sorted(
        lane_results, key=lambda item: lane_order.get(str(item.get("lane_id")), 9999)
    )
    completed_results = [item for item in lane_results if item.get("status") == "succeeded"]
    worker_dispatch_ledger = write_phase1_worker_dispatch_ledger(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        lane_results=lane_results,
        completed_results=completed_results,
        write=write,
    )
    ledger_succeeded_count = int(worker_dispatch_ledger.get("succeeded_count") or 0)
    ledger_succeeded_matches_completed = ledger_succeeded_count == len(completed_results)
    actual_mode_counts = {mode: 0 for mode in MODE_ORDER}
    actual_mode_counts["search_assist"] = 0
    for item in lane_results:
        actual_mode_counts[str(item.get("mode") or "")] = (
            actual_mode_counts.get(str(item.get("mode") or ""), 0) + 1
        )
    dynamic_width_policy = build_dynamic_width_policy(
        runtime=runtime,
        wave_id=wave_id,
        target_width=target_width,
        mode_counts=mode_counts,
        actual_dispatched_width=len(lane_results),
        actual_completed_width=len(completed_results),
        width_decision=decision,
        write=write,
    )
    staging_queue = build_draft_staging_queue(
        runtime=runtime,
        wave_id=wave_id,
        lane_results=lane_results,
        write=write,
    )
    merge_consumer = build_merge_consumer(
        runtime=runtime,
        wave_id=wave_id,
        staging_queue=staging_queue,
        lane_results=lane_results,
        source_entry=source_entry,
        latest_correction=latest_correction,
        write=write,
    )
    spend_ledger = build_spend_ledger(
        runtime=runtime,
        wave_id=wave_id,
        lane_results=lane_results,
        write=write,
    )
    width_blocker = build_width_blocker(
        runtime=runtime,
        wave_id=wave_id,
        mode_counts=mode_counts,
        lane_results=lane_results,
        spend_ledger=spend_ledger,
        contract_kind=contract_kind,
        require_external_draft=require_external_draft,
        write=write,
    )
    blocker_repair_escalation = build_blocker_repair_escalation(
        runtime=runtime,
        wave_id=wave_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        assignment_dag_node_id=package_node_id,
        contract_kind=contract_kind,
        mode_counts=mode_counts,
        lane_results=lane_results,
        spend_ledger=spend_ledger,
        width_blocker=width_blocker,
        write=write,
    )
    watchdog_downgrade = build_watchdog_downgrade(runtime=runtime, wave_id=wave_id, write=write)
    parallel_draft_batch_refs = write_parallel_draft_batch(
        runtime=runtime,
        wave_id=wave_id,
        lane_results=lane_results,
        spend_ledger=spend_ledger,
        merge_consumer=merge_consumer,
        write=write,
    )
    assignment_dag_node_evidence = write_assignment_dag_node_evidence(
        runtime=runtime,
        wave_id=wave_id,
        assignment_dag_node_id=package_node_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        worker_assignment=worker_assignment,
        worker_briefs=worker_briefs,
        lane_results=lane_results,
        staging_queue=staging_queue,
        merge_consumer=merge_consumer,
        spend_ledger=spend_ledger,
        parallel_draft_batch_refs=parallel_draft_batch_refs,
        work_package=package,
        contract_kind=contract_kind,
        write=write,
    )
    phase_boundary_named_blocker = (
        write_phase_boundary_named_blocker(
            runtime=runtime,
            wave_id=wave_id,
            assignment_dag_node_id=package_node_id,
            assignment_dag_node_evidence=assignment_dag_node_evidence,
            next_wave_id=next_wave_id,
            write=write,
        )
        if assignment_dag_node_evidence.get("phase_boundary_ready") is False
        else {}
    )
    artifact_acceptance = write_artifact_acceptance(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        merge_consumer=merge_consumer,
        write=write,
    )
    meta_rsi = (
        run_meta_rsi_evidence(
            runtime=runtime,
            repo=repo,
            wave_id=wave_id,
            lane_results=lane_results,
            write=write,
        )
        if record_meta_rsi
        else {"status": "skipped_productivity_mode_v2_false", "role": "not_main_worker"}
    )
    merge_artifact = str(merge_consumer.get("merge_artifact") or "")
    artifact_paths_present = all(
        bool(item.get("artifact_ref")) and Path(str(item.get("artifact_ref"))).is_file()
        for item in lane_results
    )
    eval_count = len([item for item in lane_results if item.get("mode") == "eval"])
    audit_count = len([item for item in lane_results if item.get("mode") == "audit"])
    explicit_package_modes = {
        str(lane.get("mode") or "draft") for lane in package_lanes if isinstance(lane, dict)
    }
    eval_required_for_wave = not package_lanes or "eval" in explicit_package_modes
    audit_required_for_wave = not package_lanes or "audit" in explicit_package_modes
    true_dp_draft_count = len(
        [
            item
            for item in lane_results
            if item.get("mode") == "draft" and item.get("deepseek_dp_invocation") is True
        ]
    )
    qwen_prepaid_draft_count = len(
        [
            item
            for item in lane_results
            if item.get("mode") == "draft" and item.get("qwen_prepaid_invocation") is True
        ]
    )
    external_cheap_draft_count = len(
        [
            item
            for item in lane_results
            if item.get("mode") == "draft"
            and (
                item.get("qwen_prepaid_invocation") is True
                or item.get("deepseek_dp_invocation") is True
            )
        ]
    )
    local_stub_draft_count = len(
        [
            item
            for item in lane_results
            if item.get("mode") == "draft" and item.get("local_stub") is True
        ]
    )
    provider_tier_usage = spend_ledger.get("provider_tier_usage", {})
    token_cost_spend = spend_ledger.get("token_cost_spend", {})
    qwen_prepaid_usage = (
        spend_ledger.get("qwen_prepaid_usage")
        if isinstance(spend_ledger.get("qwen_prepaid_usage"), dict)
        else {}
    )
    rate_limit_error = str(width_blocker.get("rate_limit_error") or "")
    named_blocker = str(width_blocker.get("named_blocker") or "")
    external_draft_ok = (
        external_cheap_draft_count > 0 and external_cheap_draft_count > local_stub_draft_count
    )
    qwen_first_required_count = int(
        qwen_prepaid_usage.get("qwen_first_required_count")
        or width_blocker.get("qwen_prepaid_first_required_count")
        or 0
    )
    qwen_first_attempted_count = int(
        qwen_prepaid_usage.get("qwen_first_attempted_count")
        or width_blocker.get("qwen_prepaid_first_attempted_count")
        or 0
    )
    qwen_first_succeeded_count = int(
        qwen_prepaid_usage.get("qwen_first_succeeded_count")
        or width_blocker.get("qwen_prepaid_first_succeeded_count")
        or 0
    )
    qwen_fallback_allowed_count = int(
        qwen_prepaid_usage.get("qwen_fallback_allowed_count")
        or width_blocker.get("qwen_fallback_allowed_count")
        or 0
    )
    qwen_first_route_ok = qwen_first_required_count <= 0 or (
        qwen_first_attempted_count == qwen_first_required_count
        and qwen_first_succeeded_count + qwen_fallback_allowed_count == qwen_first_required_count
    )
    foreground_brain_decision = build_foreground_brain_decision(
        runtime=runtime,
        wave_id=wave_id,
        source_entry=source_entry,
        latest_correction=latest_correction,
        worker_briefs=worker_briefs,
        mode_counts=mode_counts,
        lane_results=lane_results,
        staging_queue=staging_queue,
        merge_consumer=merge_consumer,
        spend_ledger=spend_ledger,
        target_width=target_width,
        named_blocker=named_blocker,
        next_wave_id=next_wave_id,
        contract_kind=contract_kind,
        write=write,
    )
    fan_in_staging_merge_spend = write_fan_in_staging_merge_spend_evidence(
        runtime=runtime,
        wave_id=wave_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        staging_queue=staging_queue,
        merge_consumer=merge_consumer,
        spend_ledger=spend_ledger,
        artifact_acceptance=artifact_acceptance,
        foreground_brain_decision=foreground_brain_decision,
        assignment_dag_node_evidence=assignment_dag_node_evidence,
        phase_boundary_named_blocker=phase_boundary_named_blocker,
        contract_kind=contract_kind,
        write=write,
    )
    unique_accepted_artifact_count = int(
        artifact_acceptance.get("unique_accepted_artifact_count") or 0
    )
    runtime_enforcement_truth_chain_checks = {
        "validation_candidate_inputs_ready": True,
        "worker_dispatch_ledger_succeeded_matches_completed": ledger_succeeded_matches_completed,
        "artifact_acceptance_unique_count_positive": (
            True if control_plane_repair else unique_accepted_artifact_count > 0
        ),
        "artifact_acceptance_count_is_unique": int(
            artifact_acceptance.get("accepted_artifact_count") or 0
        )
        == unique_accepted_artifact_count
        or control_plane_repair,
        "fan_in_staging_merge_spend_ready": fan_in_staging_merge_spend.get(
            "validation",
            {},
        ).get("passed")
        is True,
        "runtime_enforced_scope_allowed": (
            not runtime_enforced or runtime_enforced_scope in ALLOWED_RUNTIME_ENFORCED_SCOPES
        ),
    }
    runtime_enforcement_truth_chain_ready = all(runtime_enforcement_truth_chain_checks.values())
    effective_runtime_enforced = bool(runtime_enforced and runtime_enforcement_truth_chain_ready)
    effective_runtime_enforced_scope = runtime_enforced_scope if effective_runtime_enforced else ""
    runtime_enforced_blocker = (
        ""
        if effective_runtime_enforced or not runtime_enforced
        else "RUNTIME_ENFORCED_WRITE_GATE_NOT_READY"
    )
    trigger_binding = build_trigger_binding(
        runtime=runtime,
        wave_id=wave_id,
        mode_counts=mode_counts,
        contract_kind=contract_kind,
        runtime_enforced=effective_runtime_enforced,
        runtime_enforced_scope=effective_runtime_enforced_scope,
        write=write,
    )
    default_route_binding = write_default_route_binding(
        runtime=runtime,
        wave_id=wave_id,
        runtime_enforced=effective_runtime_enforced,
        runtime_enforced_scope=effective_runtime_enforced_scope,
        runtime_enforced_requested=runtime_enforced,
        runtime_enforced_blocker=runtime_enforced_blocker,
        write=write,
    )
    python_carrier = python_carrier_status(repo)
    s_python = str(s_venv_python(repo))
    draft_mode_count = int(mode_counts.get("draft") or 0)
    non_draft_mode_max = max(
        [int(count or 0) for mode, count in mode_counts.items() if mode != "draft"] or [0]
    )
    draft_primary_check = (
        True
        if control_plane_repair
        else draft_mode_count > 0
        if package_lanes
        else draft_mode_count > non_draft_mode_max
    )
    checks = {
        "width_gte_3": True if control_plane_repair else width >= 3,
        "actual_dispatched_width_gte_3": True if control_plane_repair else len(lane_results) >= 3,
        "actual_completed_width_gte_3": True
        if control_plane_repair
        else len(completed_results) >= 3,
        "worker_dispatch_ledger_written": worker_dispatch_ledger.get("validation", {}).get("passed")
        is True,
        "worker_dispatch_ledger_succeeded_matches_completed": ledger_succeeded_matches_completed,
        "planned_lanes_not_counted_as_progress": True,
        "draft_count_positive": True
        if control_plane_repair
        else int(staging_queue.get("draft_count") or 0) > 0,
        "draft_is_primary": draft_primary_check,
        "dp_not_search_or_probe_main": (
            int(mode_counts.get("search") or 0) == 0
            and int(mode_counts.get("provider_probe") or 0) == 0
        ),
        "staged_count_positive": True
        if control_plane_repair
        else int(staging_queue.get("staged_count") or 0) > 0,
        "merged_count_positive": True
        if control_plane_repair
        else int(merge_consumer.get("merged_count") or 0) > 0,
        "spend_recorded_for_every_lane": int(spend_ledger.get("spend_entry_count") or 0)
        == len(lane_results),
        "provider_tier_usage_present": bool(provider_tier_usage),
        "token_cost_spend_present": int(token_cost_spend.get("total_tokens") or 0) > 0,
        "metered_usage_for_every_lane": int(token_cost_spend.get("metered_usage_entry_count") or 0)
        == len(lane_results),
        "eval_count_present": True if not eval_required_for_wave else eval_count > 0,
        "audit_count_present": True if not audit_required_for_wave else audit_count > 0,
        "external_cheap_draft_observed": True
        if control_plane_repair or not require_external_draft
        else external_draft_ok,
        "qwen_prepaid_first_attempted_when_required": qwen_first_required_count <= 0
        or qwen_first_attempted_count == qwen_first_required_count,
        "qwen_prepaid_first_succeeded_or_allowed_fallback": qwen_first_route_ok,
        "qwen_prepaid_usage_recorded": qwen_first_required_count <= 0 or bool(qwen_prepaid_usage),
        "external_deepseek_draft_observed": True
        if control_plane_repair or not require_external_draft
        else external_draft_ok,
        "local_stub_not_used_as_draft_pool": True
        if control_plane_repair or not require_external_draft
        else local_stub_draft_count < external_cheap_draft_count,
        "worker_assignment_written": paths["worker_assignment"].is_file() if write else True,
        "global_worker_assignment_rebound": paths["global_worker_assignment"].is_file()
        if write
        else True,
        "provider_schema_surfaces_written": all(
            Path(path).is_file() for path in provider_schema_refs.values()
        )
        if write
        else True,
        "worker_brief_queue_written": paths["worker_brief_latest"].is_file() if write else True,
        "dynamic_width_policy_written": paths["dynamic_width_policy_latest"].is_file()
        if write
        else True,
        "width_blocker_written": paths["width_blocker_latest"].is_file() if write else True,
        "parallel_draft_batch_written": all(
            Path(path).is_file() for path in parallel_draft_batch_refs.values()
        )
        if write
        else True,
        "assignment_dag_node_evidence_written": (
            assignment_dag_node_evidence.get("jsonl_written") is True
            and assignment_dag_node_evidence.get("status") == "assignment_dag_node_evidence_written"
        ),
        "explicit_work_package_lanes_bound": True
        if not package_lanes
        else all(
            str(lane.get("lane_id") or "")
            in {str(brief.get("lane_id") or "") for brief in worker_briefs}
            for lane in package_lanes
        ),
        "phase_boundary_named_blocker_written": (
            phase_boundary_named_blocker.get("jsonl_written") is True
            and phase_boundary_named_blocker.get("named_blocker")
            == "PHASE_BOUNDARY_NOT_READY_CONTINUE_REQUIRED"
        )
        if assignment_dag_node_evidence.get("phase_boundary_ready") is False
        else True,
        "artifact_acceptance_queue_accepted": True
        if control_plane_repair
        else int(artifact_acceptance.get("unique_accepted_artifact_count") or 0) > 0,
        "artifact_acceptance_queue_unique_count_bound": int(
            artifact_acceptance.get("accepted_artifact_count") or 0
        )
        == int(artifact_acceptance.get("unique_accepted_artifact_count") or 0),
        "fan_in_staging_merge_spend_written": (
            fan_in_staging_merge_spend.get("jsonl_written") is True
            and fan_in_staging_merge_spend.get("status") == "fan_in_staging_merge_spend_ready"
        ),
        "productivity_mode_v2_false": record_meta_rsi is False,
        "merge_artifact_exists": bool(merge_artifact) and Path(merge_artifact).is_file(),
        "lane_artifact_refs_present": artifact_paths_present,
        "capability_invoke_recorded": True,
        "meta_rsi_not_main": meta_rsi.get("status") == "skipped_productivity_mode_v2_false"
        or meta_rsi.get("role") == "evidence_only_not_main_worker",
        "foreground_brain_decision_written": paths["foreground_brain_decision_latest"].is_file()
        if write
        else True,
        "foreground_brain_decision_has_required_fields": foreground_brain_decision.get(
            "required_fields_present"
        )
        is True,
        "blocker_repair_escalation_written": True
        if not control_plane_repair
        else blocker_repair_escalation.get("validation", {}).get("passed") is True,
        "source_entry_dynamic_read": int(source_entry.get("sampled_count") or 0) > 0,
        "latest_user_correction_digest_bound": latest_correction.get("task_id")
        == LATEST_USER_CORRECTION_TASK_ID,
        "333_alignment_bound": foreground_brain_decision.get("333_alignment", {}).get(
            "333_is_owner_semantic_line"
        )
        is True,
        "foreground_brain_owner_not_background_runner": foreground_brain_decision.get("owner")
        == "foreground_codex_brain"
        and foreground_brain_decision.get("same_default_loop_semantics", {}).get(
            "background_runner_only"
        )
        is True,
    }
    if (
        runtime_enforced
        and runtime_enforced_scope
        == "seed_cortex_temporal_activity_no_window_dp_worker_pool_phase3"
    ):
        checks["dynamic_width_scheduler_decision_bound"] = (
            dynamic_width_policy.get("target_width_source")
            in {
                "dynamic_width_scheduler",
                "dynamic_width_scheduler_with_operator_cap",
            }
            and bool(dynamic_width_policy.get("width_decision_reason"))
            and dynamic_width_policy.get("recomputed_each_wave") is True
            and dynamic_width_policy.get("fixed_20_or_50_used") is False
        )
    if runtime_enforced:
        checks["runtime_enforced_write_gate_passed"] = effective_runtime_enforced
        checks["runtime_enforced_scope_bound"] = (
            runtime_enforced_scope in ALLOWED_RUNTIME_ENFORCED_SCOPES
        )
        checks["while_self_chain_index_bound"] = (
            1 <= int(while_wave_index or 0) <= int(while_wave_count or 0)
        )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "status": "modular_dynamic_worker_pool_phase1_wave_merged"
        if all(checks.values())
        else "modular_dynamic_worker_pool_phase1_wave_blocked",
        "generated_at": now_iso(),
        "source_intent_package_ref": CURRENT_INTENT_PACKAGE_REF,
        "explicit_work_package_bound": bool(package_lanes),
        "work_package_digest_sha256": sha256_json(package) if package else "",
        "contract_kind": contract_kind,
        "control_plane_repair_mode": control_plane_repair,
        "work_package_next_ready_node_id": str(package.get("next_ready_node_id") or package_node_id)
        if package
        else "",
        "explicit_work_package_lane_ids": [
            str(lane.get("lane_id") or "") for lane in package_lanes
        ],
        "adoption_state": (
            GLOBAL_DEFAULT_ADOPTION_STATE
            if effective_runtime_enforced
            else GLOBAL_DEFAULT_BLOCKED_ADOPTION_STATE
            if runtime_enforced
            else "default_hot_path_ready"
        ),
        "runtime_enforced": effective_runtime_enforced,
        "runtime_enforced_requested": runtime_enforced,
        "runtime_enforced_scope": effective_runtime_enforced_scope,
        "runtime_enforced_blocker": runtime_enforced_blocker,
        "runtime_enforcement_truth_chain": {
            "ready": runtime_enforcement_truth_chain_ready,
            "checks": runtime_enforcement_truth_chain_checks,
        },
        "python_carrier": python_carrier,
        "global_default_enforced": effective_runtime_enforced,
        "metered": int(token_cost_spend.get("metered_usage_entry_count") or 0) == len(lane_results),
        "while_self_chain": {
            "chain_id": while_chain_id,
            "wave_index": while_wave_index,
            "wave_count": while_wave_count,
            "previous_wave_id": previous_wave_id,
            "current_wave_id": wave_id,
            "next_wave_id": next_wave_id,
            "should_continue_loop": bool(next_wave_id),
            "self_chain_pop_ready": effective_runtime_enforced
            and int(while_wave_index or 0) >= int(while_wave_count or 0),
        },
        "desktop_memo_ref": str(memo_facts().get("path") or DESKTOP_MEMO_REF),
        "desktop_memo_facts": memo_facts(),
        "source_entry_root": str(SOURCE_ENTRY_ROOT),
        "source_entry": source_entry,
        "user_latest_correction_digest": latest_correction,
        "foreground_brain_decision": foreground_brain_decision,
        "stage_order": ["parallel_draft", "merge", "writer"],
        "stage_order_text": "parallel_draft -> merge -> writer",
        "must_do_10": MUST_DO_10,
        "wave_steps_8": WAVE_STEPS_8,
        "hard_acceptance_fields": HARD_ACCEPTANCE_FIELDS,
        "target_width": width,
        "target_width_source": dynamic_width_policy.get("target_width_source"),
        "width_decision_reason": dynamic_width_policy.get("width_decision_reason"),
        "width_decision_inputs": dynamic_width_policy.get("width_decision_inputs"),
        "width_candidates": dynamic_width_policy.get("width_candidates"),
        "operator_cap_applied": dynamic_width_policy.get("operator_cap_applied"),
        "recomputed_each_wave": dynamic_width_policy.get("recomputed_each_wave"),
        "actual_dispatched_width": len(lane_results),
        "actual_completed_width": len(completed_results),
        "progress_counts": {
            "planned": len(worker_briefs),
            "dispatched": len(lane_results),
            "completed": len(completed_results),
            "accepted": int(artifact_acceptance.get("accepted_artifact_count") or 0),
            "planned_is_progress": False,
        },
        "worker_dispatch_ledger": worker_dispatch_ledger,
        "worker_dispatch_ledger_ref": worker_dispatch_ledger.get("output_paths", {}).get(
            "runtime_latest",
            str(runtime / "state" / "worker_dispatch_ledger" / "latest.json"),
        ),
        "worker_dispatch_ledger_succeeded_count": ledger_succeeded_count,
        "worker_dispatch_ledger_succeeded_matches_completed": ledger_succeeded_matches_completed,
        "mode_counts": mode_counts,
        "actual_mode_counts": actual_mode_counts,
        "draft_count": int(staging_queue.get("draft_count") or 0),
        "true_dp_draft_count": true_dp_draft_count,
        "qwen_prepaid_draft_count": qwen_prepaid_draft_count,
        "external_cheap_draft_count": external_cheap_draft_count,
        "local_stub_draft_count": local_stub_draft_count,
        "qwen_prepaid_cheap_worker_ready": provider_route_context.get(
            "qwen_prepaid_cheap_worker_ready"
        )
        is True,
        "qwen_first_applies_only_to": QWEN_FIRST_APPLIES_ONLY_TO,
        "qwen_first_must_not_override": QWEN_FIRST_MUST_NOT_OVERRIDE_LANES,
        "qwen_prepaid_usage": qwen_prepaid_usage,
        "qwen_prepaid_first_required_count": qwen_first_required_count,
        "qwen_prepaid_first_attempted_count": qwen_first_attempted_count,
        "qwen_prepaid_first_succeeded_count": qwen_first_succeeded_count,
        "qwen_fallback_allowed_count": qwen_fallback_allowed_count,
        "eval_count": eval_count,
        "audit_count": audit_count,
        "staged_count": int(staging_queue.get("staged_count") or 0),
        "merged_count": int(merge_consumer.get("merged_count") or 0),
        "spend_entry_count": int(spend_ledger.get("spend_entry_count") or 0),
        "provider_tier_usage": provider_tier_usage,
        "token_cost_spend": token_cost_spend,
        "rate_limit_error": rate_limit_error,
        "named_blocker": named_blocker,
        "provider_schemas": provider_schemas,
        "provider_schema_refs": provider_schema_refs,
        "worker_assignment": worker_assignment,
        "worker_brief_queue": worker_brief_queue,
        "dynamic_width_policy": dynamic_width_policy,
        "worker_briefs": worker_briefs,
        "lane_results": lane_results,
        "draft_staging_queue": staging_queue,
        "merge_consumer": merge_consumer,
        "spend_ledger": spend_ledger,
        "width_blocker": width_blocker,
        "blocker_repair_escalation": blocker_repair_escalation,
        "trigger_binding": trigger_binding,
        "watchdog_downgrade": watchdog_downgrade,
        "parallel_draft_batch_refs": parallel_draft_batch_refs,
        "assignment_dag_node_evidence": assignment_dag_node_evidence,
        "phase_boundary_named_blocker": phase_boundary_named_blocker,
        "default_route_binding": default_route_binding,
        "artifact_acceptance_queue": artifact_acceptance,
        "fan_in_staging_merge_spend": fan_in_staging_merge_spend,
        "meta_rsi_wave": meta_rsi,
        "merge_artifact": merge_artifact,
        "can_invoke_now": {
            "cli": f"{s_python} -m xinao_seedlab.cli.__main__ modular-dynamic-worker-pool-phase1",
            "service": "SeedCortexService.modular_dynamic_worker_pool_phase1",
            "direct_module": f"{s_python} -m services.agent_runtime.modular_dynamic_worker_pool_phase1",
            "callable": "services.agent_runtime.modular_dynamic_worker_pool_phase1.run_wave",
            "capability": "codex_s.modular_dynamic_worker_pool_phase1",
            "cheap_worker_pool_capability": "codex_s.modular_cheap_worker_pool.parallel_draft",
            "python_carrier": s_python,
            "system_python_environment_blocker_only": python_carrier.get(
                "system_python_environment_blocker_only"
            ),
            "dp_modes_bound": [mode for mode, count in mode_counts.items() if int(count or 0) > 0],
            "search_is_main_task": False,
            "provider_probe_used_as_progress": False,
        },
        "evidence_refs": {
            "runtime_latest": str(paths["latest"]),
            "schema": str(
                repo
                / "contracts"
                / "schemas"
                / "codex_s_modular_dynamic_worker_pool_phase1.v1.json"
            ),
            "runner": str(
                repo / "services" / "agent_runtime" / "modular_dynamic_worker_pool_phase1.py"
            ),
            "verifier": str(repo / "scripts" / "verify_modular_dynamic_worker_pool_phase1.ps1"),
            "tests": str(
                repo / "tests" / "seedcortex" / "test_modular_dynamic_worker_pool_phase1.py"
            ),
            "worker_assignment": str(paths["worker_assignment"]),
            "global_worker_assignment": str(paths["global_worker_assignment"]),
            "worker_dispatch_ledger_latest": worker_dispatch_ledger.get("output_paths", {}).get(
                "runtime_latest",
                str(runtime / "state" / "worker_dispatch_ledger" / "latest.json"),
            ),
            "worker_dispatch_ledger_poll_latest": worker_dispatch_ledger.get(
                "output_paths",
                {},
            ).get(
                "poll_latest",
                str(runtime / "state" / "worker_dispatch_ledger" / "poll_latest.json"),
            ),
            "foreground_brain_decision_latest": str(paths["foreground_brain_decision_latest"]),
            "brain_provider_latest": str(paths["brain_provider_latest"]),
            "worker_provider_latest": str(paths["worker_provider_latest"]),
            "model_gateway_route_latest": str(paths["model_gateway_route_latest"]),
            "executor_adapter_latest": str(paths["executor_adapter_latest"]),
            "worker_brief_latest": str(paths["worker_brief_latest"]),
            "draft_staging_queue_latest": str(paths["draft_staging_latest"]),
            "merge_consumer_latest": str(paths["merge_consumer_latest"]),
            "spend_ledger_latest": str(paths["spend_ledger_latest"]),
            "dynamic_width_policy_latest": str(paths["dynamic_width_policy_latest"]),
            "width_blocker_latest": str(paths["width_blocker_latest"]),
            "blocker_repair_escalation_latest": str(paths["blocker_repair_escalation_latest"]),
            "parallel_draft_batch_latest": str(paths["parallel_draft_batch_latest"]),
            "parallel_draft_batch": parallel_draft_batch_refs.get("parallel_draft_batch", ""),
            "parallel_cost_ledger": parallel_draft_batch_refs.get("parallel_cost_ledger", ""),
            "parallel_merge_review": parallel_draft_batch_refs.get("parallel_merge_review", ""),
            "assignment_dag_node_evidence_latest": assignment_dag_node_evidence.get(
                "latest_ref", ""
            ),
            "assignment_dag_node_evidence_jsonl": assignment_dag_node_evidence.get("jsonl_ref", ""),
            "phase_boundary_named_blocker_latest": phase_boundary_named_blocker.get(
                "latest_ref", ""
            ),
            "phase_boundary_named_blocker_jsonl": phase_boundary_named_blocker.get("jsonl_ref", ""),
            "default_route_binding_latest": str(paths["default_route_binding_latest"]),
            "artifact_acceptance_queue_latest": str(
                runtime / "state" / "artifact_acceptance_queue" / "latest.json"
            ),
            "fan_in_staging_merge_spend_latest": str(paths["fan_in_staging_merge_spend_latest"]),
            "fan_in_staging_merge_spend_jsonl": str(paths["fan_in_staging_merge_spend_jsonl"]),
            "trigger_binding_latest": str(paths["trigger_binding_latest"]),
            "watchdog_downgrade_latest": str(paths["watchdog_downgrade_latest"]),
            "capability_manifest": str(paths["capability_manifest"]),
            "cheap_worker_pool_capability_manifest": str(
                paths["cheap_worker_pool_capability_manifest"]
            ),
            "parallel_draft_capability_manifest": str(paths["parallel_draft_capability_manifest"]),
            "capability_invoke_latest": str(paths["capability_invoke_latest"]),
            "readback_zh": str(paths["readback"]),
            "meta_rsi_status": str(meta_rsi.get("status") or ""),
        },
        "readback_refs": {"runtime_readback_zh": str(paths["readback"])},
        "named_blockers": [
            item["named_blocker"] for item in lane_results if item.get("named_blocker")
        ]
        + ([named_blocker] if named_blocker else []),
        "search_as_main_task": False,
        "provider_probe_used_as_progress": False,
        "force_local_dp_draft_carrier": force_local_dp_draft,
        "require_external_draft": require_external_draft,
        "productivity_mode_v2": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()},
    }
    capability_evidence = build_capability_evidence(
        runtime=runtime,
        wave_id=wave_id,
        latest_ref=str(paths["latest"]),
        merge_artifact=merge_artifact,
        runtime_enforced=effective_runtime_enforced,
        runtime_enforced_scope=effective_runtime_enforced_scope,
        write=write,
    )
    payload["capability_evidence"] = capability_evidence
    readback = render_readback(payload)
    payload["readback_contains_invoke_answer"] = "现在能 invoke 什么" in readback
    payload["validation"]["checks"]["readback_answers_invoke"] = payload[
        "readback_contains_invoke_answer"
    ]
    payload["validation"]["passed"] = all(payload["validation"]["checks"].values())
    payload["status"] = (
        "modular_dynamic_worker_pool_phase1_wave_merged"
        if payload["validation"]["passed"]
        else "modular_dynamic_worker_pool_phase1_wave_blocked"
    )
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.latest.json", payload)
        write_text(paths["readback"], readback)
    return payload


def render_global_default_readback(payload: dict[str, Any]) -> str:
    checks = payload["validation"]["checks"]
    lines = [
        "# modular_dynamic_worker_pool_phase1 全局默认冻结回读",
        "",
        SENTINEL,
        "",
        f"- task_id: `{payload['task_id']}`",
        f"- status: `{payload['status']}`",
        f"- adoption_state: `{payload['adoption_state']}`",
        f"- runtime_enforced: {payload['runtime_enforced']}",
        f"- runtime_enforced_scope: `{payload['runtime_enforced_scope']}`",
        f"- chain_id: `{payload['chain_id']}`",
        f"- enforced_wave_count: {payload['enforced_wave_count']}",
        f"- metered_wave_count: {payload['metered_wave_count']}",
        f"- self_chain_wave_count: {payload['self_chain_wave_count']}",
        f"- pop_ready: {payload['while_pop']['pop_ready']}",
        f"- check.three_waves_enforced: {checks['three_waves_enforced']}",
        f"- check.three_waves_metered: {checks['three_waves_metered']}",
        f"- check.three_waves_self_chained: {checks['three_waves_self_chained']}",
        f"- check.default_route_runtime_enforced: {checks['default_route_runtime_enforced']}",
        f"- check.capability_manifest_runtime_enforced: {checks['capability_manifest_runtime_enforced']}",
        f"- check.capability_gateway_phase1_runtime_enforced: {checks.get('capability_gateway_phase1_runtime_enforced')}",
        "",
        "## Waves",
        "",
    ]
    for wave in payload["waves"]:
        lines.append(
            "- "
            f"{wave['wave_index']}/"
            f"{payload['required_wave_count']} `{wave['wave_id']}` "
            f"enforced={wave['runtime_enforced']} "
            f"metered={wave['metered']} "
            f"draft={wave['draft_count']} "
            f"merged={wave['merged_count']} "
            f"tokens={wave['total_tokens']} "
            f"next=`{wave['next_wave_id']}`"
        )
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            f"- global_default_latest: `{payload['evidence_refs']['global_default_latest']}`",
            f"- while_chain_latest: `{payload['evidence_refs']['while_chain_latest']}`",
            f"- phase1_latest: `{payload['evidence_refs']['phase1_latest']}`",
            f"- readback_zh: `{payload['evidence_refs']['readback_zh']}`",
            "",
            SENTINEL,
            "",
        ]
    )
    return "\n".join(lines)


def run_enforced_while(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    chain_id: str = "modular-dynamic-worker-pool-phase1-global-default",
    base_wave_id: str = "modular-dynamic-worker-pool-phase1-global-default",
    wave_count: int = 3,
    target_width: int = 0,
    write: bool = True,
    dp_invoker: DpInvoker | None = None,
    qwen_invoker: QwenInvoker | None = None,
    require_external_draft: bool = True,
    max_parallel_workers: int | None = None,
    assignment_dag_node_id: str = ASSIGNMENT_DAG_NODE_ID,
    workflow_id: str = "",
    workflow_run_id: str = "",
    work_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    required_wave_count = max(3, int(wave_count or 3))
    wave_ids = [
        f"{safe_stem(base_wave_id)}-wave-{index:02d}" for index in range(1, required_wave_count + 1)
    ]
    wave_payloads: list[dict[str, Any]] = []
    for index, wave_id in enumerate(wave_ids, start=1):
        previous_wave_id = wave_ids[index - 2] if index > 1 else ""
        next_wave_id = wave_ids[index] if index < len(wave_ids) else ""
        wave_payloads.append(
            run_wave(
                runtime_root=runtime,
                repo_root=repo,
                wave_id=wave_id,
                target_width=target_width,
                write=write,
                dp_invoker=dp_invoker,
                qwen_invoker=qwen_invoker,
                record_meta_rsi=False,
                require_external_draft=require_external_draft,
                max_parallel_workers=max_parallel_workers,
                runtime_enforced=True,
                runtime_enforced_scope=GLOBAL_DEFAULT_ENFORCED_SCOPE,
                while_chain_id=chain_id,
                while_wave_index=index,
                while_wave_count=required_wave_count,
                previous_wave_id=previous_wave_id,
                next_wave_id=next_wave_id,
                assignment_dag_node_id=assignment_dag_node_id,
                workflow_id=workflow_id,
                workflow_run_id=workflow_run_id,
                work_package=work_package if index == 1 else None,
            )
        )
    waves = []
    for payload in wave_payloads:
        self_chain = (
            payload.get("while_self_chain")
            if isinstance(payload.get("while_self_chain"), dict)
            else {}
        )
        token_cost = (
            payload.get("token_cost_spend")
            if isinstance(payload.get("token_cost_spend"), dict)
            else {}
        )
        waves.append(
            {
                "wave_id": payload.get("wave_id"),
                "wave_index": self_chain.get("wave_index"),
                "previous_wave_id": self_chain.get("previous_wave_id"),
                "next_wave_id": self_chain.get("next_wave_id"),
                "should_continue_loop": self_chain.get("should_continue_loop"),
                "self_chain_pop_ready": self_chain.get("self_chain_pop_ready"),
                "runtime_enforced": payload.get("runtime_enforced") is True,
                "runtime_enforced_scope": payload.get("runtime_enforced_scope"),
                "metered": payload.get("metered") is True,
                "metered_usage_entry_count": token_cost.get("metered_usage_entry_count"),
                "actual_dispatched_width": payload.get("actual_dispatched_width"),
                "draft_count": payload.get("draft_count"),
                "merged_count": payload.get("merged_count"),
                "total_tokens": token_cost.get("total_tokens"),
                "validation_passed": payload.get("validation", {}).get("passed") is True,
                "latest_ref": str(
                    paths["records"] / f"{safe_stem(str(payload.get('wave_id') or ''))}.latest.json"
                ),
            }
        )
    enforced_wave_count = len([wave for wave in waves if wave["runtime_enforced"]])
    metered_wave_count = len([wave for wave in waves if wave["metered"]])
    self_chain_wave_count = len(
        [
            wave
            for index, wave in enumerate(waves, start=1)
            if wave.get("wave_index") == index
            and (index == 1 or wave.get("previous_wave_id") == waves[index - 2]["wave_id"])
            and (index == len(waves) or wave.get("next_wave_id") == waves[index]["wave_id"])
        ]
    )
    default_route = read_json(paths["default_route_binding_latest"])
    capability_manifest = read_json(paths["capability_manifest"])
    checks = {
        "three_waves_enforced": enforced_wave_count >= 3
        and all(wave["validation_passed"] for wave in waves[:3]),
        "three_waves_metered": metered_wave_count >= 3,
        "three_waves_self_chained": self_chain_wave_count >= 3
        and bool(waves[-1].get("self_chain_pop_ready")),
        "default_route_runtime_enforced": default_route.get("runtime_enforced") is True
        and default_route.get("adoption_state") == GLOBAL_DEFAULT_ADOPTION_STATE,
        "capability_manifest_runtime_enforced": capability_manifest.get("runtime_enforced") is True
        and capability_manifest.get("adoption_state") == GLOBAL_DEFAULT_ADOPTION_STATE,
        "old_accounting_mode_not_default": True,
        "productivity_mode_v2_not_main": True,
    }
    global_default_ready = all(checks.values())
    payload = {
        "schema_version": "xinao.codex_s.modular_dynamic_worker_pool_phase1.global_default.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": TASK_ID,
        "chain_id": chain_id,
        "status": "global_default_runtime_enforced_while_self_chain_pop_ready"
        if global_default_ready
        else "global_default_candidate_blocked",
        "adoption_state": GLOBAL_DEFAULT_ADOPTION_STATE
        if global_default_ready
        else GLOBAL_DEFAULT_BLOCKED_ADOPTION_STATE,
        "runtime_enforced": global_default_ready,
        "runtime_enforced_requested": True,
        "runtime_enforced_scope": GLOBAL_DEFAULT_ENFORCED_SCOPE if global_default_ready else "",
        "runtime_enforced_blocker": ""
        if global_default_ready
        else "GLOBAL_DEFAULT_TRUTH_CHAIN_NOT_READY",
        "required_wave_count": required_wave_count,
        "enforced_wave_count": enforced_wave_count,
        "metered_wave_count": metered_wave_count,
        "self_chain_wave_count": self_chain_wave_count,
        "waves": waves,
        "while_pop": {
            "pop_ready": global_default_ready,
            "pop_after_wave_id": waves[-1]["wave_id"] if waves else "",
            "parent_task_id": "overnight_supervisor_loop_phase0_batch_20260704",
            "pop_meaning_cn": "3波 enforced+metered+self-chain 后才允许回父主线；不是用户完成。",
        },
        "default_route_binding": default_route,
        "capability_manifest": capability_manifest,
        "source_intent_package_ref": CURRENT_INTENT_PACKAGE_REF,
        "productivity_mode_v2": False,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "evidence_refs": {
            "global_default_latest": str(paths["global_default_latest"]),
            "while_chain_latest": str(paths["while_chain_latest"]),
            "phase1_latest": str(paths["latest"]),
            "default_route_binding_latest": str(paths["default_route_binding_latest"]),
            "capability_manifest": str(paths["capability_manifest"]),
            "readback_zh": str(paths["global_default_readback"]),
        },
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()},
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["global_default_latest"], payload)
        write_json(paths["while_chain_latest"], payload)
        write_json(paths["while_chain_records"] / f"{safe_stem(chain_id)}.json", payload)
    gateway_snapshot = refresh_capability_gateway(runtime=runtime, repo=repo, write=write)
    phase1_gateway_provider = {}
    for provider in (
        gateway_snapshot.get("providers", []) if isinstance(gateway_snapshot, dict) else []
    ):
        if (
            isinstance(provider, dict)
            and provider.get("provider_id") == "codex_s.modular_dynamic_worker_pool_phase1"
        ):
            phase1_gateway_provider = provider
            break
    checks["capability_gateway_phase1_runtime_enforced"] = (
        phase1_gateway_provider.get("runtime_enforced") is True
        and phase1_gateway_provider.get("adoption_state") == GLOBAL_DEFAULT_ADOPTION_STATE
    )
    payload["gateway_snapshot"] = gateway_snapshot
    payload["phase1_gateway_provider"] = phase1_gateway_provider
    payload["validation"] = {
        "passed": all(checks.values()),
        "checks": checks,
        "validated_at": now_iso(),
    }
    final_global_default_ready = payload["validation"]["passed"]
    payload["status"] = (
        "global_default_runtime_enforced_while_self_chain_pop_ready"
        if final_global_default_ready
        else "global_default_candidate_blocked"
    )
    payload["adoption_state"] = (
        GLOBAL_DEFAULT_ADOPTION_STATE
        if final_global_default_ready
        else GLOBAL_DEFAULT_BLOCKED_ADOPTION_STATE
    )
    payload["runtime_enforced"] = final_global_default_ready
    payload["runtime_enforced_scope"] = (
        GLOBAL_DEFAULT_ENFORCED_SCOPE if final_global_default_ready else ""
    )
    payload["runtime_enforced_blocker"] = (
        "" if final_global_default_ready else "GLOBAL_DEFAULT_TRUTH_CHAIN_NOT_READY"
    )
    payload["while_pop"]["pop_ready"] = final_global_default_ready
    readback = render_global_default_readback(payload)
    if write:
        write_json(paths["global_default_latest"], payload)
        write_json(paths["while_chain_latest"], payload)
        write_json(paths["while_chain_records"] / f"{safe_stem(chain_id)}.json", payload)
        write_text(paths["global_default_readback"], readback)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wave-id", default="modular-dynamic-worker-pool-phase1-wave-001")
    parser.add_argument("--target-width", type=int, default=0)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--record-meta-rsi", action="store_true")
    parser.add_argument("--force-local-dp-draft", action="store_true")
    parser.add_argument("--allow-local-stub-acceptance", action="store_true")
    parser.add_argument("--max-parallel-workers", type=int, default=0)
    parser.add_argument("--enforced", action="store_true")
    parser.add_argument("--while-waves", type=int, default=1)
    parser.add_argument("--assignment-dag-node-id", default=ASSIGNMENT_DAG_NODE_ID)
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--work-package-json", default="")
    parser.add_argument(
        "--chain-id",
        default="modular-dynamic-worker-pool-phase1-global-default",
    )
    args = parser.parse_args(argv)
    if args.enforced or int(args.while_waves or 1) > 1:
        payload = run_enforced_while(
            runtime_root=args.runtime_root,
            repo_root=args.repo_root,
            chain_id=args.chain_id,
            base_wave_id=args.wave_id,
            wave_count=args.while_waves,
            target_width=args.target_width,
            write=not args.no_write,
            require_external_draft=not args.allow_local_stub_acceptance,
            max_parallel_workers=args.max_parallel_workers or None,
            assignment_dag_node_id=args.assignment_dag_node_id,
            workflow_id=args.workflow_id,
            workflow_run_id=args.workflow_run_id,
            work_package=load_work_package_arg(args.work_package_json),
        )
    else:
        payload = run_wave(
            runtime_root=args.runtime_root,
            repo_root=args.repo_root,
            wave_id=args.wave_id,
            target_width=args.target_width,
            write=not args.no_write,
            record_meta_rsi=args.record_meta_rsi,
            force_local_dp_draft=args.force_local_dp_draft,
            require_external_draft=not args.allow_local_stub_acceptance,
            max_parallel_workers=args.max_parallel_workers or None,
            assignment_dag_node_id=args.assignment_dag_node_id,
            workflow_id=args.workflow_id,
            workflow_run_id=args.workflow_run_id,
            work_package=load_work_package_arg(args.work_package_json),
        )
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
