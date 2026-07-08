"""Facade hard redirect — default hot path → integrated_bus_v2 / thin_glue; no _retired import."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_runner import integrated_bus_default_enabled
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME

SCHEMA_VERSION = "xinao.integrated_bus.facade_redirect.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_FACADE_REDIRECT_V1"


def facade_allow_handroll() -> bool:
    return os.environ.get("XINAO_FACADE_ALLOW_HANDROLL", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def facade_hard_redirect_enabled() -> bool:
    return integrated_bus_default_enabled() and not facade_allow_handroll()


def _bus_evidence(runtime: Path) -> dict[str, Any] | None:
    readback = runtime / "readback"
    if not readback.is_dir():
        return None
    matches = sorted(readback.glob("integrated_bus_*.json"), reverse=True)
    for path in matches:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return {"path": str(path), "payload": payload}
    return None


def _redirect_meta(*, facade_module: str, thin_target: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "facade_hard_redirect": True,
        "handroll_blocked": True,
        "facade_module": facade_module,
        "redirect_target": thin_target,
        "integrated_bus_default": True,
        "not_333_mainline": True,
        "completion_claim_allowed": False,
    }


def redirect_intake(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    write: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    from services.agent_runtime.thin_glue_intake import build_thin_glue_intake

    payload = build_thin_glue_intake(
        runtime_root=runtime_root,
        repo_root=repo_root,
        write=write,
    )
    bus = _bus_evidence(Path(runtime_root))
    payload.update(
        _redirect_meta(
            facade_module="current_task_source_intake",
            thin_target="thin_glue_intake+integrated_bus_v2",
        )
    )
    payload["delegated_from"] = "current_task_source_intake.build_current_task_source_intake"
    if bus:
        payload["integrated_bus_evidence_ref"] = bus["path"]
        payload["integrated_bus_passed"] = (
            bus["payload"].get("validation", {}).get("passed") is True
        )
    return payload


def redirect_search_build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    write: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    from datetime import datetime

    from services.agent_runtime.thin_glue_l4_search import run_thin_glue_search

    query = str(kwargs.get("query") or kwargs.get("task_preview") or "integrated_bus")
    run_id = str(kwargs.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S"))
    payload = run_thin_glue_search(
        repo_root=Path(repo_root),
        runtime_root=Path(runtime_root),
        run_id=run_id,
        local_query=query,
        external_query=query,
        write=write,
    )
    payload.update(
        _redirect_meta(
            facade_module="codex_s_light_research_loop",
            thin_target="thin_glue_l4_search+integrated_bus_v2",
        )
    )
    payload["delegated_from"] = "codex_s_light_research_loop.build"
    return payload


def redirect_provider_scheduler(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    write: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    from services.agent_runtime.thin_glue_provider_scheduler import run_thin_glue_provider_scheduler

    del repo_root
    payload = run_thin_glue_provider_scheduler(
        runtime_root=Path(runtime_root),
        invoke_chat_smoke=bool(kwargs.get("invoke_qwen", False)),
        write=write,
    )
    payload.update(
        _redirect_meta(
            facade_module="codex_native_provider_scheduler_phase4",
            thin_target="thin_glue_provider_scheduler+integrated_bus_v2",
        )
    )
    payload["delegated_from"] = "codex_native_provider_scheduler_phase4.run_provider_scheduler"
    return payload


def redirect_worker_dispatch_ledger(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    write: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_bus_nodes import run_parallel_width_bus
    from services.agent_runtime.thin_glue_l9_ledger import run_thin_glue_ledger_mirror

    runtime = Path(runtime_root)
    parallel = run_parallel_width_bus(
        params={"parallel_width_default": int(kwargs.get("parallel_width_default", 2))},
        runtime_root=runtime,
        workflow_id=str(kwargs.get("workflow_id") or "facade-redirect"),
    )
    ledger = run_thin_glue_ledger_mirror(
        runtime_root=runtime,
        repo_root=Path(repo_root),
        write=write,
    )
    payload = {
        **ledger,
        "integrated_bus_parallel": parallel,
        "parallel_succeeded": parallel.get("parallel_succeeded"),
        "parallel_evidence_ref": parallel.get("parallel_evidence_ref"),
    }
    payload.update(
        _redirect_meta(
            facade_module="worker_dispatch_ledger",
            thin_target="thin_glue_l9_ledger+integrated_bus_parallel",
        )
    )
    payload["delegated_from"] = "worker_dispatch_ledger.build_worker_dispatch_ledger"
    return payload


def redirect_pre_pass_build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    write: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    from services.agent_runtime.thin_glue_l6_self_heal import run_thin_glue_self_heal_as_pre_pass_delegate

    payload = run_thin_glue_self_heal_as_pre_pass_delegate(
        runtime_root=runtime_root,
        repo_root=repo_root,
        task_id=str(kwargs.get("task_id") or "pre_pass_audit_loop_20260704"),
        wave_id=str(kwargs.get("wave_id") or "facade-redirect-wave"),
        invoked_by_temporal_activity=bool(kwargs.get("invoked_by_temporal_activity", False)),
        write=write,
    )
    payload.update(
        _redirect_meta(
            facade_module="pre_pass_audit_loop",
            thin_target="thin_glue_l6_self_heal+integrated_bus_v2",
        )
    )
    return payload