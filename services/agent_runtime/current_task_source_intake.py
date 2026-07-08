"""SUNSET facade — hard redirect to integrated_bus / thin_glue."""

from __future__ import annotations

from typing import Any


def build_current_task_source_intake(**kwargs: Any) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_facade_redirect import redirect_intake

    payload = redirect_intake(**kwargs)
    payload["handroll_blocked"] = True
    return payload


def __getattr__(name: str) -> Any:
    from services.agent_runtime.integrated_bus_facade_redirect import guard_facade_getattr

    guard_facade_getattr("current_task_source_intake", name)
    raise AttributeError(f"current_task_source_intake.{name} sunset; use thin_glue/integrated_bus")