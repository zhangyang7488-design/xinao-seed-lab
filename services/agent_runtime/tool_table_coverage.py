"""Tool table coverage dashboard — five-state row map to D:\\XINAO_RESEARCH_RUNTIME."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, write_json

SCHEMA_VERSION = "xinao.tool_table_coverage.v1"
SENTINEL = "SENTINEL:XINAO_TOOL_TABLE_COVERAGE_V1"

# Five states: invoke_green | thin_bind | facade | handroll_live | deferred | not_started
ROWS: tuple[dict[str, str], ...] = (
    {"id": "L0_intake", "layer": "L0", "tool": "markitdown", "state": "invoke_green"},
    {"id": "L0_watchdog", "layer": "L0", "tool": "watchdog", "state": "thin_bind"},
    {"id": "L0_duckdb", "layer": "L0", "tool": "duckdb", "state": "thin_bind"},
    {"id": "L1_pydantic", "layer": "L1", "tool": "pydantic", "state": "thin_bind"},
    {"id": "L1_instructor", "layer": "L1", "tool": "instructor", "state": "deferred"},
    {"id": "L2_temporal", "layer": "L2", "tool": "temporal", "state": "invoke_green"},
    {"id": "L2_langgraph", "layer": "L2", "tool": "langgraph", "state": "invoke_green"},
    {"id": "L2_planner", "layer": "L2", "tool": "planner_node", "state": "thin_bind"},
    {"id": "L3_litellm", "layer": "L3", "tool": "litellm", "state": "thin_bind"},
    {"id": "L3_docker", "layer": "L3", "tool": "docker", "state": "invoke_green"},
    {"id": "L3_fastmcp", "layer": "L3", "tool": "fastmcp", "state": "thin_bind"},
    {"id": "L3_gitpython", "layer": "L3", "tool": "gitpython", "state": "thin_bind"},
    {"id": "L4_ripgrep", "layer": "L4", "tool": "ripgrep", "state": "thin_bind"},
    {"id": "L4_searxng", "layer": "L4", "tool": "searxng", "state": "thin_bind"},
    {"id": "L5_fanin_aaq", "layer": "L5", "tool": "sourceledger_aaq", "state": "thin_bind"},
    {"id": "L5_promotion", "layer": "L5", "tool": "promotion_gate", "state": "invoke_green"},
    {"id": "L5_langfuse", "layer": "L5", "tool": "langfuse", "state": "thin_bind"},
    {"id": "L5_pytest", "layer": "L5", "tool": "pytest", "state": "thin_bind"},
    {"id": "L6_retry", "layer": "L6", "tool": "temporal_retry", "state": "thin_bind"},
    {"id": "L8_token", "layer": "L8", "tool": "readback_compress", "state": "thin_bind"},
    {"id": "L9_parallel", "layer": "L9", "tool": "parallel_activity", "state": "thin_bind"},
    {"id": "L9_worker_pool", "layer": "L9", "tool": "worker_daemon", "state": "thin_bind"},
    {"id": "L4_crawl4ai", "layer": "L4", "tool": "crawl4ai", "state": "thin_bind"},
    {"id": "L5_diff_cover", "layer": "L5", "tool": "diff_cover", "state": "invoke_green"},
    {"id": "L5_otel", "layer": "L5", "tool": "opentelemetry", "state": "thin_bind"},
    {"id": "L2_checkpoint", "layer": "L2", "tool": "langgraph_checkpoint", "state": "thin_bind"},
    {"id": "sunset_facades", "layer": "—", "tool": "facade_stubs", "state": "facade"},
    {"id": "sunset_driver", "layer": "—", "tool": "root_intent_loop_driver", "state": "handroll_live"},
)


def _count_by_state(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        st = str(row.get("state") or "not_started")
        counts[st] = counts.get(st, 0) + 1
    return counts


def build_tool_table_coverage(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    write: bool = True,
    integrated_bus_evidence: str | None = None,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    rows = [dict(r) for r in ROWS]
    if integrated_bus_evidence:
        for row in rows:
            if row["state"] in {"invoke_green", "thin_bind"}:
                row["evidence_hint"] = integrated_bus_evidence

    counts = _count_by_state(rows)
    green = counts.get("invoke_green", 0)
    thin = counts.get("thin_bind", 0)
    total = len(rows)
    coverage_ratio = round((green + thin * 0.5) / max(total, 1), 4)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "run_id": run_id,
        "not_333_mainline": True,
        "completion_claim_allowed": False,
        "row_count": total,
        "counts_by_state": counts,
        "invoke_green_count": green,
        "thin_bind_count": thin,
        "coverage_ratio_est": coverage_ratio,
        "target_green_min": 25,
        "target_met": green >= 25,
        "rows": rows,
        "acceptance_now_can_invoke_cn": (
            f"工具表覆盖：绿={green} 薄绑={thin} 总计={total}；"
            f"手搓live={counts.get('handroll_live', 0)} facade={counts.get('facade', 0)}；"
            f"默认路径=xinao-seedlab thin-glue --temporal integrated_bus_v2。"
        ),
    }

    if write:
        out_dir = runtime / "state" / "tool_table_coverage"
        out_dir.mkdir(parents=True, exist_ok=True)
        latest = out_dir / "v1.json"
        write_json(latest, payload)
        write_json(runtime / "readback" / f"tool_table_coverage_{run_id}.json", payload)
        payload["output_paths"] = {"latest": str(latest)}
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build tool table coverage dashboard")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    args = parser.parse_args(argv)
    payload = build_tool_table_coverage(runtime_root=args.runtime_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())