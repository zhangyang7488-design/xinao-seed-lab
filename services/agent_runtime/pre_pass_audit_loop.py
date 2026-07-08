"""SUNSET facade — hard redirect to integrated_bus / thin_glue."""

from __future__ import annotations

from typing import Any


def build(**kwargs: Any) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_facade_redirect import redirect_pre_pass_build

    return redirect_pre_pass_build(**kwargs)


def __getattr__(name: str) -> Any:
    from services.agent_runtime.integrated_bus_facade_redirect import guard_facade_getattr

    guard_facade_getattr("pre_pass_audit_loop", name)
    raise AttributeError(f"pre_pass_audit_loop.{name} sunset; use thin_glue/integrated_bus")