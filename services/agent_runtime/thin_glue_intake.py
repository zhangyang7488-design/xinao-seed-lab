"""Thin replacement for current_task_source_intake — watchdog/materials + markitdown."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import (
    DEFAULT_REPO,
    DEFAULT_RUNTIME,
    SCHEMA_VERSION,
    SENTINEL,
    l0_scan_materials,
    now_iso,
    write_json,
)

TASK_ID = "thin_glue_materials_intake"
REPLACES_MODULE = "current_task_source_intake"


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_intake"
    return {
        "latest": state / "latest.json",
        "source_ledger": runtime / "state" / "source_ledger" / "latest.json",
        "worker_brief_queue": state / "worker_brief_queue_latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_intake_latest.md",
    }


def _entry_from_intake(item: dict[str, Any], index: int) -> dict[str, Any]:
    source = str(item.get("source") or "")
    content = str(item.get("content_md") or "")
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    return {
        "entry_id": f"thin-glue-{index:03d}",
        "source_path": source,
        "role": "materials_intake",
        "content_sha256": digest,
        "content_excerpt": content[:240],
        "adapter": "markitdown",
        "read_full": True,
    }


def build_thin_glue_intake(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    materials_dir: str | Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    materials = Path(materials_dir) if materials_dir else repo / "materials"
    paths = output_paths(runtime)

    intake_items = l0_scan_materials(materials)
    source_entries = [
        _entry_from_intake(item, idx)
        for idx, item in enumerate(intake_items, start=1)
        if item.get("content_md")
    ]
    briefs = [
        {
            "brief_id": entry["entry_id"],
            "source_ledger_entry_id": entry["entry_id"],
            "lane_class": "extraction",
            "task_hint": "thin_glue_materials_patch",
        }
        for entry in source_entries
    ]
    worker_brief_queue = {
        "status": "worker_brief_queue_ready" if briefs else "worker_brief_queue_empty",
        "brief_count": len(briefs),
        "briefs": briefs,
        "next_frontier_default_outlet": False,
    }
    source_ledger = {
        "schema_version": "xinao.seedcortex.source_ledger.v1",
        "status": "source_ledger_ready" if source_entries else "source_ledger_empty",
        "entry_count": len(source_entries),
        "entries": source_entries,
        "validation": {"passed": bool(source_entries)},
        "adapter": "thin_glue_markitdown",
    }

    checks = {
        "materials_dir_exists": materials.is_dir(),
        "markitdown_converted_at_least_one": len(source_entries) >= 1,
        "hand_rolled_task_package_resolver_bypassed": True,
        "worker_brief_queue_ready": worker_brief_queue["status"] == "worker_brief_queue_ready",
        "source_ledger_ready": source_ledger["status"] == "source_ledger_ready",
    }
    passed = all(checks.values())

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "thin_glue_intake_ready" if passed else "thin_glue_intake_blocked",
        "replaces": REPLACES_MODULE,
        "not_333_mainline": True,
        "thin_glue": True,
        "materials_dir": str(materials),
        "repo_root": str(repo),
        "runtime_root": str(runtime),
        "intake_items": intake_items,
        "source_entries": source_entries,
        "source_entry_count": len(source_entries),
        "source_ledger": source_ledger,
        "worker_brief_queue": worker_brief_queue,
        "acceptance_now_can_invoke_cn": (
            f"材料池 {materials} 经 markitdown 已转 {len(source_entries)} 条；"
            "不再走 task_package_resolver 三文本马拉松。"
            if passed
            else "materials/ 无可用 md/txt 或 markitdown 失败"
        ),
        "validation": {
            "passed": passed,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "generated_at": now_iso(),
    }

    if write:
        write_json(paths["latest"], payload)
        write_json(paths["source_ledger"], source_ledger)
        write_json(paths["worker_brief_queue"], worker_brief_queue)
        zh = paths["readback"]
        zh.parent.mkdir(parents=True, exist_ok=True)
        zh.write_text(
            "\n".join(
                [
                    "# Thin Glue Intake",
                    "",
                    f"- status: {payload['status']}",
                    f"- materials: {materials}",
                    f"- entries: {len(source_entries)}",
                    f"- 现在能干什么：{payload['acceptance_now_can_invoke_cn']}",
                ]
            ),
            encoding="utf-8",
        )
        payload["output_paths"] = {k: str(v) for k, v in paths.items()}

    return payload