"""SUNSET facade — hard redirect to integrated_bus / thin_glue."""

from __future__ import annotations

from typing import Any


def run_provider_scheduler(**kwargs: Any) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_facade_redirect import redirect_provider_scheduler

    return redirect_provider_scheduler(**kwargs)


def __getattr__(name: str) -> Any:
    from services.agent_runtime.integrated_bus_facade_redirect import guard_facade_getattr

    guard_facade_getattr("codex_native_provider_scheduler_phase4", name)
    raise AttributeError(
        f"codex_native_provider_scheduler_phase4.{name} sunset; use thin_glue/integrated_bus"
    )