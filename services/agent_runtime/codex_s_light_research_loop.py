"""SUNSET facade — hard redirect to integrated_bus / thin_glue; handroll opt-in only."""

from __future__ import annotations

import importlib
from typing import Any

_HANDROLL = "services.agent_runtime._retired.codex_s_light_research_loop_handroll_v1"


def _handroll():
    return importlib.import_module(_HANDROLL)


def build(**kwargs: Any) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_facade_redirect import (
        facade_hard_redirect_enabled,
        redirect_search_build,
    )

    if facade_hard_redirect_enabled():
        return redirect_search_build(**kwargs)
    return _handroll().build(**kwargs)


def __getattr__(name: str) -> Any:
    return getattr(_handroll(), name)