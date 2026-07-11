"""中文词表 · 禁 defer 英文逃逸 — 归一化读写."""

from __future__ import annotations

from typing import Any

# 工具表五态 + 暂缓（禁止再写 deferred）
STATE_ZANHUAN = "暂缓接线"
STATE_LEGACY_DEFERRED = "deferred"

FORBIDDEN_ESCAPE = frozenset(
    {
        "defer",
        "deferred",
        "deferred_explicit",
        "defer_until",
        "skip_wiring",
    }
)

REASON_ZH = {
    "deferred_experiment_tracking_not_wired": "实验追踪未焊接",
    "deferred_lineage_not_wired": "血缘未焊接",
    "deferred_paid_search_not_wired": "付费搜索未焊接",
}


def normalize_tool_table_state(state: str) -> str:
    s = (state or "").strip()
    if s == STATE_LEGACY_DEFERRED:
        return STATE_ZANHUAN
    return s


def registry_wiring_deferred(item: dict[str, Any]) -> bool:
    return bool(item.get("接线暂缓") or item.get("deferred"))


def normalize_task_bind_decision(decision: str) -> str:
    d = (decision or "").strip().lower()
    if d == "deferred":
        return "暂缓"
    return decision


def zh_suspend_reason(code: str) -> str:
    c = (code or "").strip()
    return REASON_ZH.get(c, c)
