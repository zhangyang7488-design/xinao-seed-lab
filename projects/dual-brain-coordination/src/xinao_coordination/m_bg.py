"""M-BG (background load) — explicit invoke only; never auto-dispatch; never Temporal owner.

Blueprint T8:
  enabled=true (can invoke)
  auto_dispatch=false
  require_explicit_promote=true
  stop_preempts=true
  no desktop TUI / no M-KEEP / no live Temporal recreate
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .agent_operations import AgentOperationStore
from .errors import ConflictError, InvalidTransitionError, ValidationError

POLICY_ID = "xinao.m_bg.v1"
DEFAULT_MAX_PARALLEL = 2


def m_bg_policy() -> dict[str, object]:
    raw_enabled = os.environ.get("XINAO_MBG_ENABLED", "1").strip().lower()
    enabled = raw_enabled not in {"0", "false", "no", "off"}
    raw_max = os.environ.get("XINAO_MBG_MAX_PARALLEL", "").strip()
    try:
        max_parallel = int(raw_max) if raw_max else DEFAULT_MAX_PARALLEL
    except ValueError:
        max_parallel = DEFAULT_MAX_PARALLEL
    max_parallel = max(1, min(8, max_parallel))
    return {
        "policy_id": POLICY_ID,
        "enabled": enabled,
        "auto_dispatch": False,
        "require_explicit_promote": True,
        "stop_preempts": True,
        "max_parallel": max_parallel,
        "background_daemon": False,
        "temporal_owner": False,
        "note_cn": (
            "仅显式 mbg-dispatch；禁止自动派发；XINAO_MBG_ENABLED=0 可关；"
            "不碰 live Temporal / M-KEEP / 桌面 TUI"
        ),
    }


def allocate_task_scratch(task_id: str, *, root: Path | None = None) -> Path:
    """One task → one isolated scratch dir under canary-friendly root (not desktop)."""
    base = root or Path(
        os.environ.get(
            "XINAO_MBG_SCRATCH_ROOT",
            r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\mbg_scratch",
        )
    )
    path = base / str(task_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def count_active_operations(store: AgentOperationStore) -> int:
    active_states = ("queued", "running", "retry_wait", "waiting_input", "uncertain", "cancel_requested")
    total = 0
    for state in active_states:
        listed = store.list(state=state, limit=500)
        ops = listed.get("operations") if isinstance(listed, dict) else None
        if ops is None and isinstance(listed, dict):
            ops = listed.get("items")
        if isinstance(ops, list):
            total += len(ops)
        elif isinstance(listed, dict) and "count" in listed:
            total += int(listed["count"])
    return total


def assert_may_dispatch(
    *,
    stop_active: bool,
    task: dict[str, Any],
    in_flight: int,
    max_parallel: int,
) -> None:
    if stop_active:
        raise InvalidTransitionError(
            "stop is active; M-BG dispatch preempted",
            details={"stop_preempts": True},
        )
    meta = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    if not meta.get("promoted"):
        raise ValidationError(
            "M-BG requires explicitly promoted task (require_explicit_promote)",
            details={"task_id": task.get("task_id"), "promoted": False},
        )
    state = str(task.get("state") or "")
    if state not in {"queued", "leased", "running", "paused"}:
        raise InvalidTransitionError(
            "task state not eligible for M-BG dispatch",
            details={"task_id": task.get("task_id"), "state": state},
        )
    if in_flight >= max_parallel:
        raise ConflictError(
            "M-BG max_parallel capacity reached",
            details={"in_flight": in_flight, "max_parallel": max_parallel},
        )


def build_operation_prompt(task: dict[str, Any]) -> str:
    return (
        f"[M-BG explicit dispatch]\n"
        f"task_id={task.get('task_id')}\n"
        f"title={task.get('title')}\n"
        f"goal={task.get('goal')}\n"
        f"source_thread_id={task.get('source_thread_id')}\n"
        f"auto_dispatch=false\n"
    )


def default_cwd() -> str:
    return str(Path(__file__).resolve().parents[2])
