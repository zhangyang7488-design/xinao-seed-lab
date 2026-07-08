"""SUNSET facade — hard redirect to integrated_bus / thin_glue; handroll opt-in only."""

from __future__ import annotations

import importlib
from typing import Any

_HANDROLL = "services.agent_runtime._retired.codex_native_provider_scheduler_phase4_handroll_v1"


def _handroll():
    return importlib.import_module(_HANDROLL)


def run_provider_scheduler(**kwargs: Any) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_facade_redirect import (
        facade_hard_redirect_enabled,
        redirect_provider_scheduler,
    )

    if facade_hard_redirect_enabled():
        return redirect_provider_scheduler(**kwargs)
    return _handroll().run_provider_scheduler(**kwargs)


def __getattr__(name: str) -> Any:
    from services.agent_runtime.integrated_bus_facade_redirect import guard_facade_getattr

    guard_facade_getattr("codex_native_provider_scheduler_phase4", name)
    return getattr(_handroll(), name)