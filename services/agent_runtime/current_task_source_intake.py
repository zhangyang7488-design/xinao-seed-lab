"""SUNSET facade — hard redirect to integrated_bus / thin_glue; handroll opt-in only."""

from __future__ import annotations

import importlib
from typing import Any

_HANDROLL = "services.agent_runtime._retired.current_task_source_intake_handroll_v1"


def _handroll():
    return importlib.import_module(_HANDROLL)


def build_current_task_source_intake(**kwargs: Any) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_facade_redirect import (
        facade_hard_redirect_enabled,
        redirect_intake,
    )

    if facade_hard_redirect_enabled():
        return redirect_intake(**kwargs)
    return _handroll().build_current_task_source_intake(**kwargs)


def __getattr__(name: str) -> Any:
    from services.agent_runtime.integrated_bus_facade_redirect import guard_facade_getattr

    guard_facade_getattr("current_task_source_intake", name)
    return getattr(_handroll(), name)