"""SUNSET facade — hard redirect to integrated_bus / thin_glue."""

from __future__ import annotations

from typing import Any


def build(**kwargs: Any) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_facade_redirect import redirect_search_build

    return redirect_search_build(**kwargs)


def __getattr__(name: str) -> Any:
    from services.agent_runtime.integrated_bus_facade_redirect import guard_facade_getattr

    guard_facade_getattr("codex_s_light_research_loop", name)
    raise AttributeError(f"codex_s_light_research_loop.{name} sunset; use thin_glue/integrated_bus")