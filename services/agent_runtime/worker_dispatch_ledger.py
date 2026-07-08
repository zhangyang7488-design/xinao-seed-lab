"""SUNSET facade — hard redirect to integrated_bus / thin_glue."""

from __future__ import annotations

from typing import Any


def build_worker_dispatch_ledger(**kwargs: Any) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_facade_redirect import redirect_worker_dispatch_ledger

    return redirect_worker_dispatch_ledger(**kwargs)


def __getattr__(name: str) -> Any:
    from services.agent_runtime.integrated_bus_facade_redirect import guard_facade_getattr

    guard_facade_getattr("worker_dispatch_ledger", name)
    raise AttributeError(f"worker_dispatch_ledger.{name} sunset; use thin_glue/integrated_bus")