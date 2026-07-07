"""One loop = glue replacement + closure. 胶水与闭环同跑，不分两条线."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_bootstrap_runner import git_commit_all
from services.agent_runtime.thin_glue_l3_execute import run_l3_repo_patch
from services.agent_runtime.thin_glue_l4_search import derive_search_query, run_thin_glue_search
from services.agent_runtime.thin_glue_intake import build_thin_glue_intake
from services.agent_runtime.thin_glue_l5_verify import run_l5_pytest_verify
from services.agent_runtime.thin_glue_provider_scheduler import run_thin_glue_provider_scheduler
from services.agent_runtime.thin_glue_stack import (
    DEFAULT_REPO,
    DEFAULT_RUNTIME,
    SCHEMA_VERSION,
    SENTINEL,
    l0_intake_markdown,
    l8_write_zh_readback,
    now_iso,
    write_json,
)

LOOP_PHASE = "thin_glue_loop_v1"


def run_thin_glue_loop(
    input_path: Path | None = None,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    materials_dir: Path | None = None,
    prefer_docker: bool = True,
    invoke_gateway_chat: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    """胶水+闭环一体：材料池 → 网关薄绑 → 沙箱执行 → commit → D盘证据+中文 readback."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    materials = materials_dir or (repo_root / "materials")
    trigger = input_path or (materials / "thin_bootstrap_input.md")

    # L0 材料池（替换 current_task_source_intake 手搓马拉松）
    intake_pool = build_thin_glue_intake(
        runtime_root=runtime_root,
        repo_root=repo_root,
        materials_dir=materials,
        write=write,
    )
    trigger_intake = l0_intake_markdown(trigger) if trigger.is_file() else {}
    task_preview = (trigger_intake.get("content_md") or "thin_glue_loop")[:200]
    search_query = derive_search_query(task_preview)

    # L4 搜索（替 codex_s_light_research_loop 手搓；ripgrep + SearXNG/DDGS）
    l4_search = run_thin_glue_search(
        runtime_root=runtime_root,
        repo_root=repo_root,
        run_id=run_id,
        local_query=search_query,
        external_query=f"searxng {search_query}",
        write=write,
    )

    # L9 网关（替换 codex_native_provider_scheduler 3400 行）
    provider = run_thin_glue_provider_scheduler(
        runtime_root=runtime_root,
        repo_root=repo_root,
        wave_id=f"thin-glue-loop-{run_id}",
        invoke_chat_smoke=invoke_gateway_chat,
        write=write,
    )

    l3_patch = run_l3_repo_patch(
        repo_root=repo_root,
        runtime_root=runtime_root,
        run_id=run_id,
        task_preview=task_preview,
        prefer_docker=prefer_docker,
    )
    if not l3_patch.get("ok"):
        raise RuntimeError(f"L3 repo patch failed: {l3_patch.get('stderr') or l3_patch.get('stdout')}")

    commit_info = git_commit_all(repo_root, f"thin_glue_loop: {run_id}")

    l5_pytest = run_l5_pytest_verify(repo=repo_root, runtime=runtime_root, run_id=run_id)

    gateway_ok = provider.get("validation", {}).get("passed") is True
    intake_ok = intake_pool.get("validation", {}).get("passed") is True
    search_ok = l4_search.get("validation", {}).get("passed") is True
    closure_ok = l3_patch.get("ok") is True and bool(commit_info.get("commit_hash"))

    checks = {
        "L0_materials_intake": intake_ok,
        "L4_local_rg_search": search_ok,
        "L4_external_search_hits": l4_search.get("external_hit_count", 0) > 0,
        "L9_provider_gateway_bound": gateway_ok or bool(provider.get("named_blockers")),
        "L3_repo_patch_executed": l3_patch.get("ok") is True,
        "L3_real_repo_patch": l3_patch.get("real_repo_patch") is True,
        "git_commit_written": bool(commit_info.get("commit_hash")),
        "hand_rolled_scheduler_bypassed": provider.get("thin_glue") is True,
        "hand_rolled_intake_bypassed": intake_pool.get("thin_glue") is True,
        "hand_rolled_light_research_bypassed": l4_search.get("thin_glue") is True,
        "L5_pytest_passed": l5_pytest.get("passed") is True,
        "temporal_workflow": False,
    }
    passed = intake_ok and search_ok and closure_ok and l5_pytest.get("passed") is True

    acceptance_cn = (
        f"薄胶闭环一体已跑：材料{intake_pool.get('source_entry_count', 0)}条 → "
        f"rg「{search_query}」{l4_search.get('local_hit_count', 0)}条/"
        f"外搜{l4_search.get('external_hit_count', 0)}条 → "
        f"网关{'通' if gateway_ok else '未起'} → "
        f"沙箱{l3_patch.get('adapter')}真改文件 → commit {commit_info['commit_hash'][:12]} → "
        f"pytest {'绿' if l5_pytest.get('passed') else '失败'}。"
        " 默认走外部胶，未走 verify PS1 马拉松。"
    )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "run_id": run_id,
        "phase": LOOP_PHASE,
        "not_333_mainline": True,
        "thin_glue_loop": True,
        "glue_and_closure_together": True,
        "replaces": [
            "current_task_source_intake",
            "codex_s_light_research_loop",
            "codex_native_provider_scheduler_phase4",
            "thin_bootstrap_runner",
        ],
        "layers": {
            "L0_intake_pool": intake_pool,
            "L0_trigger_intake": trigger_intake,
            "L4_search": l4_search,
            "L9_provider_gateway": provider,
            "L3_repo_patch": l3_patch,
            "L5_pytest": l5_pytest,
            "L8_commit": commit_info,
        },
        "workspace_proof": l3_patch.get("proof_path"),
        "acceptance_now_can_invoke_cn": acceptance_cn,
        "validation": {
            "passed": passed,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "named_blocker": None
        if passed
        else (
            provider.get("named_blockers", [None])[0]
            if not gateway_ok and not intake_ok
            else "THIN_GLUE_LOOP_PARTIAL"
        ),
        "timestamp": now_iso(),
    }

    if write:
        loop_dir = runtime_root / "thin_glue_loop" / run_id
        readback_json = runtime_root / "readback" / f"thin_glue_loop_{run_id}.json"
        manifest = loop_dir / "loop_manifest.json"
        write_json(readback_json, payload)
        write_json(
            manifest,
            {
                "run_id": run_id,
                "status": "loop_passed" if passed else "loop_partial",
                "git_commit_hash": commit_info["commit_hash"],
                "gateway_ok": gateway_ok,
                "intake_count": intake_pool.get("source_entry_count"),
                "search_query": search_query,
                "local_search_hits": l4_search.get("local_hit_count"),
                "external_search_hits": l4_search.get("external_hit_count"),
                "sandbox_backend": l3_patch.get("adapter"),
                "pytest_passed": l5_pytest.get("passed"),
                "evidence_path": str(readback_json),
                "acceptance_now_can_invoke_cn": acceptance_cn,
            },
        )
        zh_path = l8_write_zh_readback(
            runtime_root,
            run_id=f"thin_glue_loop_{run_id}",
            title=f"薄胶闭环一体 {run_id}",
            lines=[
                "## 一层一句",
                f"- L0 材料池：{intake_pool.get('source_entry_count')} 条（markitdown，替 intake 手搓）",
                f"- L4 搜索：rg「{search_query}」{l4_search.get('local_hit_count', 0)} 条 / 外搜 {l4_search.get('external_hit_count', 0)} 条",
                f"- L9 网关：{'OK ' + str(provider.get('gateway', {}).get('base_url', '')) if gateway_ok else '未起 → scripts/Start-XinaoThinGlueStack.ps1'}",
                f"- L3 真改文件：{l3_patch.get('adapter')} → {l3_patch.get('proof_path')}",
                f"- L5 pytest：{l5_pytest.get('passed')} ({l5_pytest.get('test_paths', [])})",
                f"- commit：{commit_info['commit_hash'][:12]}",
                "",
                "## 现在能干什么",
                acceptance_cn,
            ],
        )
        payload["output_paths"] = {
            "readback_json": str(readback_json),
            "loop_manifest": str(manifest),
            "readback_zh": str(zh_path),
            "intake_latest": str(runtime_root / "state" / "thin_glue_intake" / "latest.json"),
            "provider_latest": str(runtime_root / "state" / "thin_glue_provider" / "latest.json"),
            "search_latest": str(runtime_root / "state" / "thin_glue_search" / "latest.json"),
        }
        write_json(readback_json, payload)

    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="XINAO thin glue loop — 胶水替换+闭环一体（默认入口）"
    )
    parser.add_argument(
        "--input",
        default="",
        help="触发材料（默认 materials/thin_bootstrap_input.md）",
    )
    parser.add_argument("--materials-dir", default="")
    parser.add_argument("--no-docker", action="store_true")
    parser.add_argument("--gateway-chat", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    input_path = Path(args.input) if args.input else None
    materials = Path(args.materials_dir) if args.materials_dir else None
    if input_path and not input_path.is_file():
        print(f"input missing: {input_path}", file=sys.stderr)
        return 2

    payload = run_thin_glue_loop(
        input_path,
        materials_dir=materials,
        prefer_docker=not args.no_docker,
        invoke_gateway_chat=args.gateway_chat,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())