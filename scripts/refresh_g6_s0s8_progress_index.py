#!/usr/bin/env python3
"""G6 S0–S8 progress index refresh (evidence index only).

Writer scope:
- scripts/ indexer only (no dual-brain core source edits)
- evidence/index outputs under night_run saturation + kaigong_wave *index* refresh

Hard rules:
- completion_claim_allowed always false
- never promote product_closed / phase closed
- partial stays partial
- temporal: adapter_landed (source/evidence) vs live_welded (separate field)
- supersede stale "adapters missing" claims when source has temporal adapter
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(r"E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination")
KAIGONG = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave")
PEER_NIGHT = Path(r"D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712")
MAINLINE_EV = Path(r"D:\XINAO_RESEARCH_RUNTIME\evidence\dual_brain_mainline")
OUT_DIR = PEER_NIGHT / "saturation" / "G6_s0s8_index"
STATE_INDEX = KAIGONG / "overnight_S0S8_progress_index_latest.json"
TZ_CN = timezone(timedelta(hours=8))

# Primary + supporting evidence anchors per phase (latest preferred first).
PHASE_CATALOG: dict[str, dict[str, Any]] = {
    "S0": {
        "title_cn": "基线 / minimal / B01-B08 诚实 / compose 状态",
        "meaning_cn": "S0_minimal 可作审计基线；full B01-B08 未闭合；禁 live compose recreate 宣称",
        "primary": [
            "S0_minimal_latest.json",
            "S0_b01_b08_honesty_latest.json",
            "S0_compose_status_refresh.json",
            "S0_compose_config_re_latest.json",
            "S0_baseline_latest.json",
            "S0_infra_merged_latest.json",
            "S0_compose_on_disk_verify.json",
            "S0_zhuxian_freeze.json",
        ],
        "open_gaps_default": ["GAP_S0_NOT_FULL_B01_B08", "full S0 product closed not allowed"],
    },
    "S1": {
        "title_cn": "AMQ canary + W0/W1/W2 闸（禁 prod init）",
        "meaning_cn": "Canary 核心与 W1 备份绿；生产 amq 未 init；W2 HOLD；S1 产品未闭合",
        "primary": [
            "S1_phase_exit_latest.json",
            "S1_W0_preflight_latest.json",
            "S1_W1_backup_latest.json",
            "S1_W2_gate_latest.json",
            "S1_idempotent_retest_latest.json",
            "S1_cli_amq_smoke_latest.json",
            "S1_pytest_bundle_latest.json",
            "S1_amq_pin_latest.json",
            "S1_spool_canary_latest.json",
            "S1_amq_pytest_re_latest.json",
            "S1_adapters_inventory_latest.json",
            "S1_prod_wiring_plan_latest.json",
            "S1_canary_baseline_merge_latest.json",
            "S1_reconcile_formal_latest.json",
            "S1_accident_gate_latest.json",
        ],
        "open_gaps_default": [
            "prod_amq_init_not_done",
            "wiring_executed=false",
            "W2 requires user explicit",
            "S1 product not closed",
        ],
    },
    "S2": {
        "title_cn": "CLI/MCP stop_clear / no-auto / host profiles / parity",
        "meaning_cn": "stop_clear / no-auto / parity 有 scoped 证据；user host residual；≠ S2 包闭合",
        "primary": [
            "S2_stop_clear_verify_latest.json",
            "S2_no_auto_task_refresh_latest.json",
            "S2_parity_refresh_latest.json",
            "S2_user_host_ops_latest.json",
            "S2_host_profiles_inventory_latest.json",
            "S2_chat_no_auto_task_latest.json",
            "S2_cli_mcp_surface.json",
            "S2_t5_pytest_latest.json",
            "S2_wave_merged_latest.json",
            "S2_promote_idempotent_latest.json",
        ],
        "peer_extra": [
            PEER_NIGHT / "T1T2T5_e2e_canary.json",
        ],
        "open_gaps_default": [
            "GAP_USER_HOST_PROFILE_OPS",
            "S2 package not closed",
        ],
    },
    "S3": {
        "title_cn": "双源 / 只读看板 / 策略 B 钉（无迁移执行）",
        "meaning_cn": "策略 B 已锁；readback inventory 已落；dual_source residual；无 migrate/删 bus",
        "primary": [
            "S3_strategy_B_pin_latest.json",
            "S3_readonly_board_refresh_latest.json",
            "S3_readback_inventory_latest.json",
            "S3_dual_source_converge_plan_latest.json",
            "S3_dual_source_status_latest.json",
            "S3_dual_source_refresh_latest.json",
            "S3_bus_counts_latest.json",
            "S3_readonly_board.json",
            "S3_legacy_bus_inventory.json",
            "S3_mainline_evidence_index.json",
        ],
        "open_gaps_default": [
            "dual_source_high_residual",
            "converge_executed=false",
        ],
    },
    "S4": {
        "title_cn": "门铃 / route-assess / mbg-status（非产品）",
        "meaning_cn": "多路 smoke/探针 landed_*_not_product；门铃≠产品闭合",
        "primary": [
            "S4_doorbell_refresh_latest.json",
            "S4_mbg_status_latest.json",
            "S4_mbg_status_re_latest.json",
            "S4_mbg_no_auto_latest.json",
            "S4_route_refresh_latest.json",
            "S4_route_three_signals_latest.json",
            "S4_route_pytest_latest.json",
            "S4_window_visible_honesty_latest.json",
        ],
        "peer_extra": [
            PEER_NIGHT / "T6T7T8_e2e_canary.json",
        ],
        "open_gaps_default": [
            "doorbell_ne_product",
            "accepted_live=false",
            "product_ready=false",
        ],
    },
    "S5": {
        "title_cn": "Temporal 薄适配 landed + mock canary（live 未焊）",
        "meaning_cn": "adapter 源码+CLI/MCP 已落地；T9 mock PASS_SCOPED；live start 未焊；≠ C08 live PASS",
        "primary": [
            "S5_temporal_adapter_landed_latest.json",
            "T9_temporal_promoted_canary_latest.json",
            "S5_temporal_inventory_latest.json",
            "S5_temporal_containers_latest.json",
            "S5_adapter_design_latest.json",
            "S5_adapter_files_scan_latest.json",
            "S5_worker_queue_config_latest.json",
            "S5_queue_name_inventory_latest.json",
            "S5_promoted_only_shape_latest.json",
            "S5_no_chat_to_temporal_latest.json",
        ],
        "peer_extra": [
            PEER_NIGHT / "ACCEPTANCE_MATRIX.json",
            PEER_NIGHT / "pytest_t9.txt",
            PEER_NIGHT / "temporal_queue_describe_promoted_v1.txt",
        ],
        "open_gaps_default": [
            "live_welded=false",
            "live_workflow_start not implemented (ValidationError outside mock)",
            "C08 FAIL_LIVE / PARTIAL_LANDING",
            "worker poller for xinao-dualbrain-promoted-v1 not verified",
        ],
    },
    "S6": {
        "title_cn": "M-KEEP 禁用证明",
        "meaning_cn": "disabled proof scoped green；禁止 enable；非产品闭合",
        "primary": [
            "S6_mkeep_disabled_proof_latest.json",
            "S6_mkeep_default_false_latest.json",
            "S6_mkeep_grep_latest.json",
            "S6_mkeep_code_path_latest.json",
        ],
        "open_gaps_default": ["not_product", "enable_forbidden"],
    },
    "S7": {
        "title_cn": "L0 只读盘点 + peer fresh rerun 引用",
        "meaning_cn": "inventory + peer L0 fresh PASS_FRESH_RERUN；≠ L0 产品/可交付闭合；edge_claim=false",
        "primary": [
            "S7_l0_inventory_latest.json",
            "S7_l0_entry_command_latest.json",
            "S7_manifest_gap_latest.json",
            "l0_hypothesis_register_latest.json",
            "codex_L0_backtest_numbers.json",
        ],
        "peer_extra": [
            PEER_NIGHT / "l0_fresh_stdout.txt",
            PEER_NIGHT / "ACCEPTANCE_MATRIX.json",
        ],
        "open_gaps_default": [
            "inventory_only residual",
            "no L0 deliverable close",
            "edge_claim=false remains",
        ],
    },
    "S8": {
        "title_cn": "L1/L2 接口盘点",
        "meaning_cn": "接口目录盘点；budget_universe_built=false；非 S8 产品闭合",
        "primary": [
            "S8_interface_inventory_latest.json",
            "S8_interface_stubs_latest.json",
            "S8_quota_interface_gap_latest.json",
        ],
        "open_gaps_default": [
            "budget_universe_built=false",
            "inventory_only",
        ],
    },
}


def now_utc() -> datetime:
    return datetime.now(UTC)


def fmt_local(dt: datetime) -> str:
    return dt.astimezone(TZ_CN).isoformat(timespec="seconds")


def fmt_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "size_bytes": None,
            "last_write_utc": None,
            "last_write_local": None,
            "mtime_epoch": None,
        }
    st = path.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC)
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": st.st_size,
        "last_write_utc": fmt_utc(mtime),
        "last_write_local": fmt_local(mtime),
        "mtime_epoch": st.st_mtime,
    }


def try_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.suffix.lower() != ".json":
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def truthy(v: Any) -> bool:
    return v is True or v == 1 or (isinstance(v, str) and v.lower() in {"true", "yes", "1"})


def falsy(v: Any) -> bool:
    return v is False or v == 0 or (isinstance(v, str) and v.lower() in {"false", "no", "0"})


def probe_temporal_source(repo: Path) -> dict[str, Any]:
    adapters = repo / "adapters" / "temporal"
    pkg = repo / "src" / "xinao_coordination" / "temporal"
    toml = repo / "configs" / "modules" / "temporal.toml"
    client = pkg / "client.py"
    service = repo / "src" / "xinao_coordination" / "service.py"
    cli = repo / "src" / "xinao_coordination" / "cli.py"
    mcp = repo / "src" / "xinao_coordination" / "mcp_server.py"

    adapter_files = sorted(p.name for p in adapters.glob("*") if p.is_file()) if adapters.exists() else []
    pkg_files = sorted(p.name for p in pkg.glob("*.py") if p.is_file()) if pkg.exists() else []

    surfaces: list[str] = []
    for label, path in (("service", service), ("cli", cli), ("mcp", mcp)):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "temporal_start_promoted" in text:
            surfaces.append(f"{label}.temporal_start_promoted")
        if "temporal_status" in text or "temporal-status" in text:
            surfaces.append(f"{label}.temporal_status")

    live_start_code_present = False
    live_notes: list[str] = []
    if client.exists():
        ctext = client.read_text(encoding="utf-8", errors="replace")
        if re.search(r"_async_start_promoted_workflow_live|start_workflow\s*\(", ctext):
            live_start_code_present = True
            live_notes.append("client.py has live start_workflow branch (code present)")
        if "temporalio" in ctext:
            live_notes.append("client.py references temporalio (import may be optional/lazy)")
        else:
            live_notes.append("no temporalio string in client.py")
        if "ValidationError" in ctext and "mock" in ctext.lower():
            live_notes.append("client.py has ValidationError/mock gated default path")
        if re.search(r"XINAO_TEMPORAL_LIVE|live_connect", ctext):
            live_notes.append("live path gated by live_connect / XINAO_TEMPORAL_LIVE")

    adapter_landed = adapters.exists() and pkg.exists() and toml.exists() and bool(surfaces)
    # live_welded requires runtime proof — never infer from source alone
    live_welded = False

    return {
        "repo": str(repo),
        "adapters_temporal_exists": adapters.exists(),
        "package_temporal_exists": pkg.exists(),
        "config_temporal_toml_exists": toml.exists(),
        "adapter_files": adapter_files,
        "package_files": pkg_files,
        "surfaces_detected": sorted(set(surfaces)),
        "adapter_landed": adapter_landed,
        "live_start_code_present": live_start_code_present,
        "live_welded": live_welded,
        "live_notes": live_notes,
        "paths": {
            "adapters_temporal": str(adapters),
            "package_temporal": str(pkg),
            "config_temporal_toml": str(toml),
        },
    }


def probe_saturation_lane_facts() -> dict[str, Any]:
    """Index G1 live COMPLETED / G4 M2–M4 / G5 C01–C15 matrix from saturation evidence.

    Honesty:
    - G1 worker canary COMPLETED ≠ product C08 live_welded / admin client path
    - G4 M2–M4 numbers ≠ edge_claim / promote_L1 / S7 product close
    - G5 matrix 13ok/2fail keeps completion_claim_allowed=false
    """
    sat = PEER_NIGHT / "saturation"
    g1_path = sat / "G1_temporal_worker" / "G1_RESULT.json"
    g2_path = sat / "G2_temporal_live" / "T9_temporal_live_canary.json"
    g4_path = sat / "G4_s7_mainline" / "RESULT.json"
    g4_gates_path = sat / "G4_s7_mainline" / "gates.json"
    g5_path = sat / "G5_c01_c15" / "completion_matrix.json"
    g5_run_path = sat / "G5_c01_c15" / "verifier_run.json"
    ledger_path = sat / "SATURATION_LEDGER.json"

    g1 = try_load_json(g1_path) or {}
    g2 = try_load_json(g2_path) or {}
    g4 = try_load_json(g4_path) or {}
    g4_gates = try_load_json(g4_gates_path) or {}
    g5 = try_load_json(g5_path) or {}
    g5_run = try_load_json(g5_run_path) or {}
    ledger = try_load_json(ledger_path) or {}

    g1_checks = g1.get("checks") if isinstance(g1.get("checks"), dict) else {}
    g1_worker = g1_checks.get("worker") if isinstance(g1_checks.get("worker"), dict) else {}
    g1_wf = g1_checks.get("workflow_describe") if isinstance(g1_checks.get("workflow_describe"), dict) else {}
    g1_canary = (
        g1_checks.get("canary_start_workflow")
        if isinstance(g1_checks.get("canary_start_workflow"), dict)
        else {}
    )
    g1_status = str(g1.get("status") or "")
    g1_wf_status = str(g1_wf.get("status") or "")
    g1_live_completed = (
        g1_status.upper() == "PASS"
        and g1_wf_status.upper() == "COMPLETED"
        and truthy(g1_wf.get("ok") if "ok" in g1_wf else g1_wf.get("result_ok"))
        and truthy(g1_worker.get("pollers_present"))
    )

    g1_block: dict[str, Any] = {
        "lane": "G1_temporal_worker",
        "evidence_path": str(g1_path),
        "evidence_exists": g1_path.exists(),
        "status": g1_status or None,
        "live_completed": g1_live_completed,
        "workflow_status": g1_wf_status or None,
        "workflow_id": g1_wf.get("workflow_id") or g1_canary.get("workflow_id"),
        "run_id": g1_wf.get("run_id") or g1_canary.get("run_id"),
        "task_queue": g1_wf.get("task_queue") or g1_worker.get("task_queue"),
        "pollers_present": g1_worker.get("pollers_present"),
        "worker_identities_sample": g1_worker.get("identities_sample"),
        "result_ok": g1_wf.get("result_ok"),
        "terminal_status": g1_wf.get("terminal_status"),
        "timestamp_utc": g1.get("timestamp_utc"),
        "meta": file_meta(g1_path),
        "note_cn": (
            "G1 worker 任务队列 canary workflow status=COMPLETED + pollers 在线；"
            "≠ admin client product path C08 live_welded；≠ Temporal 主路闭合"
            if g1_live_completed
            else "G1 证据缺失或未 COMPLETED"
        ),
        "does_not_imply": [
            "C08_PASS",
            "live_welded=true for product admin client",
            "temporal_mainline_closed",
        ],
    }

    g2_block: dict[str, Any] = {
        "lane": "G2_temporal_live",
        "evidence_path": str(g2_path),
        "evidence_exists": g2_path.exists(),
        "verdict": g2.get("verdict"),
        "live_workflow_start_attempted": g2.get("live_workflow_start_attempted"),
        "live_via_admin_client": g2.get("live_via_admin_client"),
        "live_via_temporalio_bypass": g2.get("live_via_temporalio_bypass"),
        "admin_client_still_raises": g2.get("admin_client_still_raises"),
        "completion_claim_allowed": False,
        "product_closed": False,
        "meta": file_meta(g2_path),
        "note_cn": (
            "G2 PASS_SCOPED_BYPASS_LIVE：temporalio 旁路 live 有证据；"
            "admin client 仍 raise → 不得升 C08 / live_welded"
        ),
    }

    g4_m4 = g4.get("M4") if isinstance(g4.get("M4"), dict) else {}
    g4_gates_merged = g4.get("gates") if isinstance(g4.get("gates"), dict) else {}
    if g4_gates:
        g4_gates_merged = {**g4_gates_merged, **g4_gates}
    g4_block: dict[str, Any] = {
        "lane": "G4_s7_mainline",
        "evidence_path": str(g4_path),
        "evidence_exists": g4_path.exists(),
        "status": g4.get("status"),
        "milestones": g4.get("milestones")
        or ["M2_conditional_freq", "M3_walkforward_backtest", "M4_multiplicity_fdr"],
        "m2_m4_landed": bool(g4) and str(g4.get("status") or "").startswith("ok"),
        "n_oos_cycles": g4.get("n_oos_cycles"),
        "min_oos_cycles_required": g4.get("min_oos_cycles_required"),
        "n_trials_OOS": g4.get("n_trials_OOS"),
        "hit_rate_OOS": g4.get("hit_rate_OOS"),
        "lift": g4.get("lift"),
        "IS_vs_OOS_decay": g4.get("IS_vs_OOS_decay"),
        "M4": g4_m4 or None,
        "edge_claim": False if g4 else None,
        "promote_L1_allowed": False if g4 else None,
        "completion_claim_allowed": False,
        "product_closed": False,
        "not_m1_stub": g4.get("not_m1_stub"),
        "trial_id": g4.get("trial_id"),
        "gates": {
            "promote_L1_allowed": g4_gates_merged.get("promote_L1_allowed", False),
            "edge_claim": g4_gates_merged.get("edge_claim", False),
            "numeric_gates_all_green": g4_gates_merged.get("numeric_gates_all_green"),
            "block_reasons": g4_gates_merged.get("block_reasons"),
            "ok_signals": g4_gates_merged.get("ok_signals"),
        },
        "meta": file_meta(g4_path),
        "note_cn": (
            "G4 M2–M4 walk-forward 数字已落盘（OOS>=5）；"
            "edge_claim=false；promote_L1_allowed=false；≠ S7 产品闭合"
            if g4
            else "G4 RESULT 缺失"
        ),
        "does_not_imply": [
            "edge_claim=true",
            "promote_L1_allowed",
            "S7_product_closed",
            "completion_claim_allowed=true",
        ],
    }

    g5_summary = g5.get("summary") if isinstance(g5.get("summary"), dict) else {}
    if not g5_summary and isinstance(g5_run.get("summary"), dict):
        g5_summary = g5_run["summary"]
    g5_verdicts = g5_summary.get("verdicts") if isinstance(g5_summary.get("verdicts"), dict) else {}
    g5_block: dict[str, Any] = {
        "lane": "G5_c01_c15",
        "evidence_path": str(g5_path),
        "evidence_exists": g5_path.exists(),
        "schema_version": g5.get("schema_version"),
        "generated_at_utc": g5.get("generated_at_utc") or g5_run.get("generated_at_utc"),
        "ok_count": g5_summary.get("ok_count"),
        "fail_count": g5_summary.get("fail_count"),
        "total": g5_summary.get("total"),
        "ok_ids": g5_summary.get("ok_ids"),
        "fail_ids": g5_summary.get("fail_ids"),
        "verdicts": g5_verdicts or None,
        "c08_verdict": g5_verdicts.get("C08"),
        "c10_verdict": g5_verdicts.get("C10"),
        "completion_claim_allowed": False,
        "product_closed": False,
        "materials_all_present": (
            (g5.get("materials") or {}).get("all_present") if isinstance(g5.get("materials"), dict) else None
        ),
        "meta": file_meta(g5_path),
        "note_cn": (
            f"G5 C01–C15 matrix: ok={g5_summary.get('ok_count')}/"
            f"{g5_summary.get('total')} fail={g5_summary.get('fail_ids')}；"
            "completion_claim_allowed=false；C08 FAIL_LIVE + C10 FAIL 为硬残留"
            if g5_summary
            else "G5 completion_matrix 缺失"
        ),
        "does_not_imply": [
            "product_closed",
            "completion_claim_allowed=true",
            "C08 live PASS",
            "S0–S8 package closed",
        ],
    }

    highlights = ledger.get("highlights") if isinstance(ledger.get("highlights"), dict) else {}
    return {
        "saturation_root": str(sat),
        "saturation_exists": sat.exists(),
        "ledger_path": str(ledger_path),
        "ledger_exists": ledger_path.exists(),
        "ledger_highlights": highlights or None,
        "G1_live_completed": g1_block,
        "G2_temporal_live": g2_block,
        "G4_m2m4": g4_block,
        "G5_c01_c15_matrix": g5_block,
        "index_facts_cn": [
            f"G1 live COMPLETED={g1_live_completed} (workflow={g1_wf_status or 'n/a'})",
            f"G4 M2–M4 status={g4.get('status') or 'missing'}; "
            f"n_oos={g4.get('n_oos_cycles')}; edge_claim=false",
            (
                f"G5 matrix {g5_summary.get('ok_count')}/{g5_summary.get('total')} ok; "
                f"fail={g5_summary.get('fail_ids')}"
                if g5_summary
                else "G5 matrix missing"
            ),
            "以上均为索引事实，不翻转 completion_claim_allowed / product_closed / live_welded(product)",
        ],
    }


def classify_evidence(
    path: Path,
    data: dict[str, Any] | None,
    *,
    temporal_truth: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return (status, note_cn). status in green_scoped|partial|fail|stale|missing."""
    meta = file_meta(path)
    if not meta["exists"]:
        return "missing", "文件不存在"

    name = path.name
    note_bits: list[str] = []

    # Explicit drift correction: S5_adapter_files_scan claimed adapters missing.
    if (
        temporal_truth
        and name == "S5_adapter_files_scan_latest.json"
        and temporal_truth.get("adapter_landed")
    ):
        return (
            "stale",
            "源码已有 adapters/temporal + package/temporal + temporal.toml；"
            "本扫描仍写 missing → 事实漂移，以源码/S5_temporal_adapter_landed 为准",
        )

    if data is None:
        if path.suffix.lower() == ".json":
            return "partial", "JSON 不可解析；仅计存在性"
        return "partial", "非 JSON 证据文件（存在）"

    # Hard fail signals
    verdict = str(data.get("verdict") or data.get("C08_temporal", {}).get("verdict") or "")
    if isinstance(data.get("C08_temporal"), dict):
        c08 = data["C08_temporal"]
        if "FAIL_LIVE" in str(c08.get("verdict", "")) or str(c08.get("verdict", "")).startswith("PARTIAL"):
            # Acceptance matrix: C08 live fail is expected residual; file itself is valid evidence.
            note_bits.append(f"C08={c08.get('verdict')}")

    if (
        re.search(r"\bFAIL\b", verdict)
        and "PASS" not in verdict
        and "PASS_SCOPED" not in verdict
        and "PARTIAL" not in verdict
    ):
        # File-level fail only if not a scoped canary pass wrapper.
        return "fail", f"verdict={verdict}"

    # Product-close never green-scoped for whole product
    product_closed = (
        truthy(data.get("product_closed"))
        or truthy(data.get("s1_product_closed"))
        or truthy(data.get("s2_product_closed"))
    )
    product_ready = truthy(data.get("product_ready"))
    completion = data.get("completion_claim_allowed")
    if truthy(completion):
        # Indexer refuses to honor true; flag as stale policy violation in evidence
        note_bits.append("evidence had completion_claim_allowed=true (index forces false)")

    # Green-scoped heuristics (scoped only — never product close)
    green_hits = 0
    if truthy(data.get("ok")):
        green_hits += 1
    if truthy(data.get("canary_ok")) or truthy(data.get("canary_core_ok")):
        green_hits += 1
    if truthy(data.get("cli_smoke_ok")):
        green_hits += 1
    if truthy(data.get("backup_ok")):
        green_hits += 1
    if truthy(data.get("pytest_ok")) or truthy(data.get("doctor_ok")):
        green_hits += 1
    if str(data.get("overall", "")).lower() == "green":
        green_hits += 1
    if str(data.get("verdict", "")).startswith("PASS"):
        green_hits += 1
    if truthy(data.get("implementation_landed")) and truthy(data.get("adapter_exists")):
        green_hits += 1
        note_bits.append("adapter_landed")
    if truthy(data.get("compose_draft_config_ok")) and truthy(
        data.get("results", {}).get("pytest_ok")
        if isinstance(data.get("results"), dict)
        else data.get("pytest_ok")
    ):
        green_hits += 1
    results = data.get("results")
    if isinstance(results, dict) and truthy(results.get("doctor_ok")) and truthy(results.get("pytest_ok")):
        green_hits += 2
        note_bits.append("doctor+pytest ok")
    if data.get("status") == "landed_disabled_proof_not_product" and truthy(data.get("ok")):
        green_hits += 2
        note_bits.append("mkeep disabled proof")
    if data.get("gate_status") == "HOLD_PLAN_ONLY":
        note_bits.append("W2 HOLD_PLAN_ONLY")
        return "partial", "；".join(note_bits) or "闸门 HOLD 仅计划"
    if falsy(data.get("wiring_executed")) and "wiring" in name.lower():
        note_bits.append("wiring_executed=false")
    if truthy(data.get("inventory_only")):
        note_bits.append("inventory_only")
        # inventory alone is partial unless also scoped green signals
        if green_hits == 0:
            return "partial", "；".join(note_bits)

    # Stale: claims adapter missing while source has it
    if temporal_truth and temporal_truth.get("adapter_landed"):
        cf = data.get("critical_finding") if isinstance(data.get("critical_finding"), dict) else {}
        if cf and (
            falsy(cf.get("adapters_temporal_exists"))
            or falsy(cf.get("package_temporal_exists"))
            or "均缺失" in str(cf.get("statement_cn", ""))
        ):
            return "stale", "声明 adapters missing 但源码已 landed"
        note_cn = str(data.get("note_cn") or "")
        if "adapter 未实现" in note_cn or "adapter_not_implemented" in str(data.get("open_gaps", [])):
            return "stale", "旧 note 仍写 adapter 未实现"

    # Partial by design markers
    status_s = str(data.get("status") or "")
    if "not_product" in status_s or status_s.startswith("landed_"):
        if green_hits >= 1 and not product_closed and not product_ready:
            # doorbell etc: keep partial (landed smoke ≠ product)
            note_bits.append(status_s)
            return "partial", "；".join(note_bits) or "landed not product"
        note_bits.append(status_s or "not_product")
        return "partial", "；".join(note_bits)

    if (
        green_hits >= 1
        and not product_closed
        and (
            str(data.get("verdict", "")).startswith("PASS")
            or truthy(data.get("ok"))
            or truthy(data.get("canary_core_ok"))
            or truthy(data.get("backup_ok"))
            or truthy(data.get("implementation_landed"))
            or (
                isinstance(results, dict)
                and truthy(results.get("pytest_ok"))
                and truthy(results.get("doctor_ok"))
            )
            or str(data.get("overall", "")).lower() == "green"
            or data.get("status") == "landed_disabled_proof_not_product"
        )
    ):
        # Prefer green_scoped when evidence self-describes scoped pass.
        note_bits.append("scoped green ≠ product closed")
        return "green_scoped", "；".join(note_bits)

    if note_bits:
        return "partial", "；".join(note_bits)
    return "partial", "证据存在；未达 scoped green 启发式"


def phase_aggregate(statuses: list[str]) -> str:
    if not statuses:
        return "missing"
    if all(s == "missing" for s in statuses):
        return "missing"
    non_missing = [s for s in statuses if s != "missing"]
    if any(s == "fail" for s in non_missing) and not any(s == "green_scoped" for s in non_missing):
        return "fail"
    if all(s == "stale" for s in non_missing):
        return "stale"
    # Phase never fully green product; green_scoped only if majority green and no fail
    if non_missing and all(s == "green_scoped" for s in non_missing):
        return "green_scoped"
    # Mix of green + partial/stale → partial (honest)
    return "partial"


def scan_phase(
    phase: str,
    catalog: dict[str, Any],
    temporal_truth: dict[str, Any],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for name in catalog["primary"]:
        path = KAIGONG / name
        data = try_load_json(path)
        status, note = classify_evidence(path, data, temporal_truth=temporal_truth if phase == "S5" else None)
        meta = file_meta(path)
        item = {
            "id": Path(name).stem,
            "file": name,
            "evidence_status": status,
            "note_cn": note,
            **meta,
        }
        if data:
            for k in (
                "verdict",
                "ok",
                "canary_ok",
                "canary_core_ok",
                "backup_ok",
                "product_closed",
                "product_ready",
                "completion_claim_allowed",
                "implementation_landed",
                "adapter_exists",
                "live_workflow_start_attempted",
                "inventory_only",
                "gate_status",
                "wiring_executed",
                "status",
            ):
                if k in data:
                    item[k] = data[k]
            if isinstance(data.get("results"), dict):
                item["results_subset"] = {
                    kk: data["results"].get(kk)
                    for kk in ("doctor_ok", "pytest_ok", "compose_draft_config_ok")
                    if kk in data["results"]
                }
        items.append(item)

    for extra in catalog.get("peer_extra") or []:
        path = Path(extra)
        data = try_load_json(path)
        status, note = classify_evidence(path, data, temporal_truth=temporal_truth if phase == "S5" else None)
        meta = file_meta(path)
        items.append(
            {
                "id": path.stem,
                "file": path.name,
                "evidence_status": status,
                "note_cn": note,
                "source": "peer_or_external",
                **meta,
            }
        )

    statuses = [it["evidence_status"] for it in items]
    counts = {
        "green_scoped": sum(1 for s in statuses if s == "green_scoped"),
        "partial": sum(1 for s in statuses if s == "partial"),
        "fail": sum(1 for s in statuses if s == "fail"),
        "stale": sum(1 for s in statuses if s == "stale"),
        "missing": sum(1 for s in statuses if s == "missing"),
        "total": len(statuses),
    }
    phase_status = phase_aggregate(statuses)

    # Latest evidence by mtime among existing
    existing = [it for it in items if it.get("exists") and it.get("mtime_epoch")]
    latest = max(existing, key=lambda x: x["mtime_epoch"]) if existing else None

    out: dict[str, Any] = {
        "phase": phase,
        "title_cn": catalog["title_cn"],
        "status": phase_status,
        "phase_status": phase_status,  # alias for older consumers
        "product_closed": False,
        "completion_claim_allowed": False,
        "meaning_cn": catalog["meaning_cn"],
        "latest_evidence_path": latest["path"] if latest else None,
        "latest_evidence_file": latest["file"] if latest else None,
        "timestamp_utc": latest["last_write_utc"] if latest else None,
        "timestamp_local": latest["last_write_local"] if latest else None,
        "counts": counts,
        "open_gaps": list(catalog.get("open_gaps_default") or []),
        "evidence_files": items,
    }

    if phase == "S5":
        landed_ev = try_load_json(KAIGONG / "S5_temporal_adapter_landed_latest.json") or {}
        t9 = try_load_json(KAIGONG / "T9_temporal_promoted_canary_latest.json") or {}
        matrix = try_load_json(PEER_NIGHT / "ACCEPTANCE_MATRIX.json") or {}
        c08 = matrix.get("C08_temporal") if isinstance(matrix.get("C08_temporal"), dict) else {}

        adapter_landed = bool(
            temporal_truth.get("adapter_landed")
            or truthy(landed_ev.get("implementation_landed"))
            or truthy(landed_ev.get("adapter_exists"))
            or truthy(t9.get("implementation_landed"))
            or truthy(c08.get("adapter_landed_in_worktree"))
        )
        live_attempted = bool(
            truthy(landed_ev.get("live_workflow_start_attempted"))
            or truthy(t9.get("live_workflow_start_attempted"))
        )
        # live_welded = runtime/mainline proof only. Code branch ≠ welded.
        # Require explicit live success evidence; T9 mock PASS is NOT live weld.
        live_success_evidence = False
        for blob in (landed_ev, t9, matrix):
            if not isinstance(blob, dict):
                continue
            if truthy(blob.get("live_welded")) or truthy(blob.get("live_start_succeeded")):
                live_success_evidence = True
            v = str(blob.get("verdict") or "")
            if "LIVE" in v and "PASS" in v and "FAIL" not in v and "MOCK" not in v.upper():
                live_success_evidence = True
        c08_live_ok = truthy(c08.get("live_start_implemented")) and "FAIL" not in str(
            c08.get("verdict") or ""
        )
        live_welded = bool(live_success_evidence or c08_live_ok)
        # Peer night_run still records FAIL_LIVE / live_start_implemented=false → force false
        if falsy(c08.get("live_start_implemented")) or "FAIL_LIVE" in str(c08.get("verdict") or ""):
            live_welded = False
        if not live_attempted and str(t9.get("verdict") or "").startswith("PASS_SCOPED"):
            # mock scoped canary never promotes live_welded
            live_welded = False

        out["adapter_landed"] = adapter_landed
        out["live_welded"] = live_welded
        out["live_start_code_present"] = bool(temporal_truth.get("live_start_code_present"))
        out["live_workflow_start_attempted"] = live_attempted
        out["t9_verdict"] = t9.get("verdict") or landed_ev.get("t9_verdict")
        out["c08_verdict"] = c08.get("verdict")
        out["temporal_source_probe"] = temporal_truth
        out["drift_corrections"] = [
            {
                "claim": "adapters missing / adapter_not_implemented",
                "was": "S5_adapter_files_scan + old overnight index open_gaps",
                "now": "adapter_landed=true (source + S5_temporal_adapter_landed + T9 + peer C08)",
                "live_welded": live_welded,
                "live_start_code_present": bool(temporal_truth.get("live_start_code_present")),
                "note_cn": "code live branch may exist; live_welded still false without live canary proof",
            }
        ]
        # Phase status: adapter landed + mock green but live fail → partial (not fail whole S5)
        if adapter_landed and not live_welded:
            out["status"] = "partial"
            out["phase_status"] = "partial"
            out["meaning_cn"] = (
                "Temporal adapter 已 landed（源码+表面+T9 mock）；live_welded=false；"
                "C08 live FAIL；禁止宣称 adapters missing；禁止宣称 Temporal 主路闭合"
            )

    if phase == "S2":
        # parity was missing in old index; now present
        parity = next((i for i in items if i["file"] == "S2_parity_refresh_latest.json"), None)
        if parity and parity.get("exists"):
            out["open_gaps"] = [g for g in out["open_gaps"] if "parity" not in g.lower()]
            if parity.get("evidence_status") == "green_scoped":
                out.setdefault("notes_cn", []).append("parity_refresh 已补盘")

    if phase == "S3":
        rb = next((i for i in items if i["file"] == "S3_readback_inventory_latest.json"), None)
        if rb and rb.get("exists"):
            out["open_gaps"] = [
                g for g in out["open_gaps"] if "readback" not in g.lower() or "missing" not in g.lower()
            ]
            out.setdefault("notes_cn", []).append("readback_inventory 已补盘（inventory only）")

    # Never allow green_scoped phase if product would be implied for residual-heavy phases
    if phase in {"S0", "S1", "S2", "S3", "S4", "S5", "S7", "S8"} and out["status"] == "green_scoped":
        # Demote phase to partial unless truly all green with no known residual (S6 only typical)
        out["status"] = "partial"
        out["phase_status"] = "partial"
        out.setdefault("notes_cn", []).append("phase 有 residual/open_gaps → 保持 partial（禁假绿包）")

    if phase == "S6" and counts["green_scoped"] >= 1 and counts["fail"] == 0 and counts["missing"] == 0:
        # S6 disabled-proof scoped green is allowed as phase green_scoped but still not product
        out["status"] = "green_scoped"
        out["phase_status"] = "green_scoped"
        out["product_closed"] = False

    return out


def build_index() -> dict[str, Any]:
    generated = now_utc()
    temporal_truth = probe_temporal_source(REPO)
    lane_facts = probe_saturation_lane_facts()

    phases: dict[str, Any] = {}
    phase_summary: list[dict[str, Any]] = []
    total_counts = {"green_scoped": 0, "partial": 0, "fail": 0, "stale": 0, "missing": 0, "total": 0}

    for phase, catalog in PHASE_CATALOG.items():
        block = scan_phase(phase, catalog, temporal_truth)
        # Attach peer saturation lane facts that inform S5/S7 without flipping product closes.
        if phase == "S5":
            g1f = lane_facts.get("G1_live_completed") or {}
            g2f = lane_facts.get("G2_temporal_live") or {}
            block["peer_lane_G1_live_completed"] = bool(g1f.get("live_completed"))
            block["peer_lane_G1"] = {
                "status": g1f.get("status"),
                "live_completed": g1f.get("live_completed"),
                "workflow_status": g1f.get("workflow_status"),
                "workflow_id": g1f.get("workflow_id"),
                "pollers_present": g1f.get("pollers_present"),
                "evidence_path": g1f.get("evidence_path"),
            }
            block["peer_lane_G2"] = {
                "verdict": g2f.get("verdict"),
                "live_via_admin_client": g2f.get("live_via_admin_client"),
                "live_via_temporalio_bypass": g2f.get("live_via_temporalio_bypass"),
                "admin_client_still_raises": g2f.get("admin_client_still_raises"),
                "evidence_path": g2f.get("evidence_path"),
            }
            # G1 COMPLETED is worker/canary proof, not product live_welded.
            if g1f.get("live_completed"):
                block.setdefault("notes_cn", []).append(
                    "G1 live canary workflow COMPLETED + pollers；"
                    "仍保持 live_welded=false（admin product path 未焊）"
                )
                # Soften residual wording for worker existence, not C08.
                if "worker poller for xinao-dualbrain-promoted-v1 not verified" in block.get("open_gaps", []):
                    block["open_gaps"] = [
                        g
                        for g in block["open_gaps"]
                        if g != "worker poller for xinao-dualbrain-promoted-v1 not verified"
                    ]
                    block["open_gaps"].append(
                        "worker poller verified via G1 (scoped); "
                        "admin client product path still not live_welded"
                    )
            if g2f.get("live_via_temporalio_bypass") and not g2f.get("live_via_admin_client"):
                block.setdefault("notes_cn", []).append(
                    "G2 bypass live attempted；admin_client_still_raises → C08 FAIL_LIVE residual"
                )
        if phase == "S7":
            g4f = lane_facts.get("G4_m2m4") or {}
            block["peer_lane_G4_m2m4"] = {
                "status": g4f.get("status"),
                "m2_m4_landed": g4f.get("m2_m4_landed"),
                "n_oos_cycles": g4f.get("n_oos_cycles"),
                "edge_claim": False,
                "promote_L1_allowed": False,
                "milestones": g4f.get("milestones"),
                "evidence_path": g4f.get("evidence_path"),
            }
            if g4f.get("m2_m4_landed"):
                block.setdefault("notes_cn", []).append(
                    f"G4 M2–M4 numbers landed n_oos={g4f.get('n_oos_cycles')}; edge_claim=false"
                )
                # Inventory residual remains; numbers do not close S7 product.
                if "inventory_only residual" in block.get("open_gaps", []):
                    block["open_gaps"] = [g for g in block["open_gaps"] if g != "inventory_only residual"]
                    block["open_gaps"].append(
                        "G4 M2-M4 numbers present; inventory residual reduced; still ≠ L0 product close"
                    )
        phases[phase] = block
        c = block["counts"]
        for k in total_counts:
            total_counts[k] += c.get(k, 0)
        phase_summary.append(
            {
                "phase": phase,
                "status": block["status"],
                "product_closed": False,
                "green_scoped": c["green_scoped"],
                "partial": c["partial"],
                "fail": c["fail"],
                "stale": c["stale"],
                "missing": c["missing"],
                "total": c["total"],
                "title_cn": block["title_cn"],
                "latest_evidence_path": block["latest_evidence_path"],
                "timestamp_local": block["timestamp_local"],
                **(
                    {
                        "adapter_landed": block.get("adapter_landed"),
                        "live_welded": block.get("live_welded"),
                        "peer_lane_G1_live_completed": block.get("peer_lane_G1_live_completed"),
                    }
                    if phase == "S5"
                    else {}
                ),
                **(
                    {
                        "peer_lane_G4_m2m4_landed": (block.get("peer_lane_G4_m2m4") or {}).get(
                            "m2_m4_landed"
                        ),
                        "peer_lane_G4_n_oos": (block.get("peer_lane_G4_m2m4") or {}).get("n_oos_cycles"),
                    }
                    if phase == "S7"
                    else {}
                ),
            }
        )

    # Peer + mainline scan notes
    peer_files = []
    if PEER_NIGHT.exists():
        for p in sorted(PEER_NIGHT.glob("*")):
            if p.is_file():
                peer_files.append(file_meta(p) | {"name": p.name})

    mainline_note = {
        "path": str(MAINLINE_EV),
        "exists": MAINLINE_EV.exists(),
        "note_cn": "dual_brain_mainline 证据根存在性检查；本索引以 kaigong_wave + grok45 peer night_run 为主",
    }

    # Stale frontier missing list (recompute)
    missing_frontier = []
    for phase, block in phases.items():
        for it in block["evidence_files"]:
            if (
                it["evidence_status"] == "missing"
                and it.get("source") != "peer_or_external"
                and it["file"]
                in {
                    "S2_parity_refresh_latest.json",
                    "S3_readback_inventory_latest.json",
                    "S5_temporal_adapter_landed_latest.json",
                }
            ):
                # Only primary kaigong expected files that were historically core.
                missing_frontier.append(
                    {
                        "file": it["file"],
                        "phase": phase,
                        "evidence_status": "missing",
                    }
                )

    stale_items = []
    for phase, block in phases.items():
        for it in block["evidence_files"]:
            if it["evidence_status"] == "stale":
                stale_items.append(
                    {
                        "phase": phase,
                        "file": it["file"],
                        "path": it["path"],
                        "note_cn": it["note_cn"],
                    }
                )

    s5 = phases["S5"]
    g1f = lane_facts.get("G1_live_completed") or {}
    g4f = lane_facts.get("G4_m2m4") or {}
    g5f = lane_facts.get("G5_c01_c15_matrix") or {}
    overall = "partial"
    if any(p["status"] == "fail" for p in phase_summary) and all(
        p["status"] in {"fail", "missing"} for p in phase_summary
    ):
        overall = "fail"

    g1_completed_flag = bool(g1f.get("live_completed"))
    overall_cn_bits = [
        "S0–S8 均有证据；无一阶段产品闭合",
        f"S5 adapter_landed={s5.get('adapter_landed')} live_welded={s5.get('live_welded')}",
        f"G1 live COMPLETED={g1_completed_flag}",
        f"G4 M2M4={g4f.get('status') or 'missing'} n_oos={g4f.get('n_oos_cycles')}",
        f"G5 matrix {g5f.get('ok_count')}/{g5f.get('total')} ok fail={g5f.get('fail_ids')}",
        f"stale_items={len(stale_items)}",
        "completion_claim_allowed=false",
    ]

    payload: dict[str, Any] = {
        "schema_version": "xinao.kaigong.G6_s0s8_progress_index.v2",
        "title_cn": "G6 S0–S8 progress index refresh（证据存在性 + green_scoped/partial/fail/stale/missing）",
        "generated_at_utc": fmt_utc(generated),
        "generated_at_local": fmt_local(generated),
        "executor": "grok_build_subagent_g16_refresh_g6_index",
        "station": "G6_S0S8_index_refresh",
        "contract": "autonomous_pool_execution_contract_v1",
        "overnight": True,
        "refresh_role": "G16",
        "completion_claim_allowed": False,
        "product_closed": False,
        "s0_s8_package_closed": False,
        "p0_closed": False,
        "temporal_mainline_closed": False,
        "hard_bans": {
            "no_prod_amq_init": True,
            "no_codex": True,
            "no_live_temporal_recreate": True,
            "no_m_keep_enable": True,
            "no_desktop_delete": True,
            "no_product_close_claim": True,
            "no_flip_completion_claim_allowed": True,
            "no_partial_to_closed": True,
        },
        "hard_bans_honored_this_turn": [
            "index-only write",
            "no product/S0-S8 close claim",
            "completion_claim_allowed forced false",
            "partial not promoted to closed",
            "no dual-brain core source edit",
            "no prod amq init",
            "no live temporal recreate",
        ],
        "traffic_light": {
            "overall": overall,
            "overall_cn": "；".join(overall_cn_bits),
            **total_counts,
        },
        "phase_summary": phase_summary,
        "phases": phases,
        "saturation_lane_facts": lane_facts,
        "index_facts": {
            "G1_live_completed": g1_completed_flag,
            "G1_workflow_status": g1f.get("workflow_status"),
            "G1_workflow_id": g1f.get("workflow_id"),
            "G1_pollers_present": g1f.get("pollers_present"),
            "G4_m2m4_status": g4f.get("status"),
            "G4_m2m4_landed": bool(g4f.get("m2_m4_landed")),
            "G4_n_oos_cycles": g4f.get("n_oos_cycles"),
            "G4_edge_claim": False,
            "G4_promote_L1_allowed": False,
            "G5_ok_count": g5f.get("ok_count"),
            "G5_fail_count": g5f.get("fail_count"),
            "G5_fail_ids": g5f.get("fail_ids"),
            "G5_c08_verdict": g5f.get("c08_verdict"),
            "G5_c10_verdict": g5f.get("c10_verdict"),
            "G5_completion_claim_allowed": False,
            "note_cn": "G1/G4/G5 为 saturation 车道索引事实；不翻转 product/live_welded(product)/completion",
        },
        "temporal_fact_correction": {
            "adapters_missing_claim": False,
            "adapter_landed": s5.get("adapter_landed"),
            "live_welded": s5.get("live_welded"),
            "live_start_code_present": s5.get("live_start_code_present"),
            "live_workflow_start_attempted": s5.get("live_workflow_start_attempted"),
            "t9_verdict": s5.get("t9_verdict"),
            "c08_verdict": s5.get("c08_verdict") or g5f.get("c08_verdict"),
            "g1_live_completed": g1_completed_flag,
            "g1_workflow_status": g1f.get("workflow_status"),
            "g2_verdict": (lane_facts.get("G2_temporal_live") or {}).get("verdict"),
            "source_probe": temporal_truth,
            "note_cn": (
                "消除 adapters missing 漂移：源码 adapters/temporal + "
                "src/.../temporal + temporal.toml 均存在；"
                "live_start_code_present 可与 live_welded 分离；"
                f"G1 live canary COMPLETED={g1_completed_flag}（worker/queue 证据）；"
                "live_welded=false 仍成立（admin product path / C08 ≠ G1 canary COMPLETED；"
                "G2 bypass ≠ admin client live weld）"
            ),
        },
        "stale_evidence": stale_items,
        "missing_frontier_expected": missing_frontier,
        "peer_acceptance": {
            "root": str(PEER_NIGHT),
            "exists": PEER_NIGHT.exists(),
            "acceptance_matrix": str(PEER_NIGHT / "ACCEPTANCE_MATRIX.json"),
            "findings": str(PEER_NIGHT / "FINDINGS.md"),
            "file_count": len(peer_files),
            "saturation_root": str(PEER_NIGHT / "saturation"),
        },
        "dual_brain_mainline_evidence": mainline_note,
        "strong_scoped_greens_cn": [
            "S0_minimal doctor/pytest（≠ full B01-B08）",
            "S1 W0/W1/phase_exit/idempotent canary（≠ prod amq init）",
            "S2 stop_clear / no-auto / parity refresh（≠ S2 包闭合）",
            "S3 strategy B pin + readonly board（≠ converge 执行）",
            "S5 adapter landed + T9 PASS_SCOPED_CANARY mock（≠ live welded）",
            "G1 worker live canary COMPLETED + pollers（≠ C08 product）",
            "G4 M2–M4 walk-forward numbers OOS>=5（≠ edge_claim）",
            "G5 C01–C15 matrix majority ok（≠ product_closed；C08/C10 fail）",
            "S6 M-KEEP disabled proof",
            "peer T1T2T5/T6T7T8 isolated canaries ok",
        ],
        "residual_high_cn": [
            "S0 full B01-B08 未闭合",
            "S1 W2 HOLD — prod amq 未 init",
            "S2 GAP_USER_HOST_PROFILE_OPS",
            "S3 dual-source residual；converge_executed=false",
            "S4 门铃/mbg/route 全是 not_product",
            "S5 live_welded=false；G5 C08 FAIL_LIVE；admin client asyncio residual",
            "G5 C10 FAIL（L1/L2 budget universe）",
            "S7 G4 numbers landed but edge_claim=false / no L0 product close",
            "S8 budget_universe_built=false",
        ],
        "now_can_do_cn": [
            "用本索引做 G6 进度盘点与派工优先级",
            "S5 下一刀：Admin 修 client live async path + C08 product live 证据",
            "禁止再写 adapters missing",
            "禁止把 G1 COMPLETED 误写成 C08 PASS / live_welded=true",
            "S1 W2 仅用户明示后",
        ],
        "cannot_claim_cn": [
            "S0–S8 整包闭合",
            "P0 / Temporal 主路闭合",
            "adapters missing（已漂移纠正）",
            "T9 mock = C08 live PASS",
            "G1 worker COMPLETED = C08 live PASS / live_welded",
            "G4 M2–M4 numbers = edge_claim / promote_L1",
            "G5 13/15 ok = product_closed",
            "completion_claim_allowed=true",
            "partial → closed",
            "inventory green = 交付闭合",
        ],
        "related_refs": {
            "state_index": str(STATE_INDEX),
            "out_dir": str(OUT_DIR),
            "kaigong_wave": str(KAIGONG),
            "peer_night": str(PEER_NIGHT),
            "s5_adapter_landed": str(KAIGONG / "S5_temporal_adapter_landed_latest.json"),
            "t9_canary": str(KAIGONG / "T9_temporal_promoted_canary_latest.json"),
            "acceptance_matrix": str(PEER_NIGHT / "ACCEPTANCE_MATRIX.json"),
            "phase_lock": str(KAIGONG / "phase_lock_latest.json"),
            "g1_result": str(PEER_NIGHT / "saturation" / "G1_temporal_worker" / "G1_RESULT.json"),
            "g4_result": str(PEER_NIGHT / "saturation" / "G4_s7_mainline" / "RESULT.json"),
            "g5_matrix": str(PEER_NIGHT / "saturation" / "G5_c01_c15" / "completion_matrix.json"),
            "saturation_ledger": str(PEER_NIGHT / "saturation" / "SATURATION_LEDGER.json"),
        },
        "honesty_cn": [
            "本文件=G6 索引刷新，只陈述证据存在与 scoped 状态",
            "completion_claim_allowed=false（强制）",
            "phase_status=partial 表示有证据但未产品闭合，不是假绿",
            "scoped green ≠ 阶段闭合 ≠ 产品闭合",
            "adapter_landed ≠ live_welded",
            "G1 live COMPLETED ≠ product live_welded / C08 PASS",
            "G4 M2M4 numbers ≠ edge_claim",
            "G5 matrix ≠ product_closed",
            "未执行 prod amq init；未改 dual-brain 核心源码；未宣称 S0–S8/P0 闭合",
        ],
        "sentinel": "SENTINEL:G6_S0S8_PROGRESS_INDEX_V2",
    }
    return payload


def write_outputs(payload: dict[str, Any]) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TZ_CN).strftime("%Y%m%dT%H%M%S%z")
    out_full = OUT_DIR / "G6_s0s8_progress_index_latest.json"
    out_stamp = OUT_DIR / f"G6_s0s8_progress_index_{stamp}.json"
    out_summary = OUT_DIR / "G6_s0s8_progress_index_summary.json"
    out_md = OUT_DIR / "G6_s0s8_progress_index_SUMMARY.md"

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    out_full.write_text(text, encoding="utf-8")
    out_stamp.write_text(text, encoding="utf-8")

    # Compact summary for operators
    idx = payload.get("index_facts") or {}
    summary = {
        "schema_version": "xinao.kaigong.G6_s0s8_progress_index_summary.v1",
        "generated_at_utc": payload["generated_at_utc"],
        "generated_at_local": payload["generated_at_local"],
        "refresh_role": payload.get("refresh_role", "G16"),
        "completion_claim_allowed": False,
        "product_closed": False,
        "traffic_light": payload["traffic_light"],
        "phase_summary": payload["phase_summary"],
        "index_facts": idx,
        "temporal_fact_correction": {
            "adapter_landed": payload["temporal_fact_correction"]["adapter_landed"],
            "live_welded": payload["temporal_fact_correction"]["live_welded"],
            "live_start_code_present": payload["temporal_fact_correction"].get("live_start_code_present"),
            "adapters_missing_claim": False,
            "t9_verdict": payload["temporal_fact_correction"]["t9_verdict"],
            "c08_verdict": payload["temporal_fact_correction"]["c08_verdict"],
            "g1_live_completed": payload["temporal_fact_correction"].get("g1_live_completed"),
            "g1_workflow_status": payload["temporal_fact_correction"].get("g1_workflow_status"),
            "g2_verdict": payload["temporal_fact_correction"].get("g2_verdict"),
        },
        "stale_evidence": payload["stale_evidence"],
        "cannot_claim_cn": payload["cannot_claim_cn"],
        "full_index": str(out_full),
        "sentinel": "SENTINEL:G6_S0S8_PROGRESS_INDEX_SUMMARY_V1",
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# G6 S0–S8 Progress Index Summary",
        "",
        f"- generated: {payload['generated_at_local']}",
        "- refresh_role: **G16**",
        "- completion_claim_allowed: **false**",
        "- product_closed: **false**",
        f"- overall: **{payload['traffic_light']['overall']}**",
        f"- evidence items: green_scoped={payload['traffic_light']['green_scoped']} "
        f"partial={payload['traffic_light']['partial']} fail={payload['traffic_light']['fail']} "
        f"stale={payload['traffic_light']['stale']} missing={payload['traffic_light']['missing']}",
        "",
        "## Index facts (G1 / G4 / G5)",
        "",
        f"- **G1 live COMPLETED**: `{idx.get('G1_live_completed')}` "
        f"(workflow_status=`{idx.get('G1_workflow_status')}`, "
        f"pollers=`{idx.get('G1_pollers_present')}`, wf=`{idx.get('G1_workflow_id')}`)",
        f"- **G4 M2–M4**: status=`{idx.get('G4_m2m4_status')}` landed=`{idx.get('G4_m2m4_landed')}` "
        f"n_oos=`{idx.get('G4_n_oos_cycles')}` edge_claim=`false` promote_L1=`false`",
        f"- **G5 C01–C15 matrix**: ok=`{idx.get('G5_ok_count')}` fail=`{idx.get('G5_fail_count')}` "
        f"fail_ids=`{idx.get('G5_fail_ids')}` C08=`{idx.get('G5_c08_verdict')}` "
        f"C10=`{idx.get('G5_c10_verdict')}`",
        "",
        "## Phases",
        "",
        "| Phase | Status | Latest evidence | Timestamp | Notes |",
        "|-------|--------|-----------------|-----------|-------|",
    ]
    for p in payload["phase_summary"]:
        notes = ""
        if p["phase"] == "S5":
            notes = (
                f"adapter_landed={p.get('adapter_landed')} live_welded={p.get('live_welded')} "
                f"G1_COMPLETED={p.get('peer_lane_G1_live_completed')}"
            )
        if p["phase"] == "S7":
            notes = f"G4_m2m4={p.get('peer_lane_G4_m2m4_landed')} n_oos={p.get('peer_lane_G4_n_oos')}"
        lines.append(
            f"| {p['phase']} | {p['status']} | `"
            f"{p.get('latest_evidence_file') or p.get('latest_evidence_path') or '-'}` "
            f"| {p.get('timestamp_local') or '-'} | {notes} |"
        )
    lines.extend(
        [
            "",
            "## Temporal fact correction",
            "",
            "- adapters_missing_claim: **false**",
            f"- adapter_landed: **{payload['temporal_fact_correction']['adapter_landed']}**",
            "- live_start_code_present: **"
            f"{payload['temporal_fact_correction'].get('live_start_code_present')}**",
            f"- live_welded: **{payload['temporal_fact_correction']['live_welded']}**",
            f"- g1_live_completed: **{payload['temporal_fact_correction'].get('g1_live_completed')}** "
            f"(`{payload['temporal_fact_correction'].get('g1_workflow_status')}`)",
            f"- g2_verdict: `{payload['temporal_fact_correction'].get('g2_verdict')}`",
            f"- t9_verdict: `{payload['temporal_fact_correction']['t9_verdict']}`",
            f"- c08_verdict: `{payload['temporal_fact_correction']['c08_verdict']}`",
            "",
            "## Stale evidence (do not trust literal claims)",
            "",
        ]
    )
    if payload["stale_evidence"]:
        for s in payload["stale_evidence"]:
            lines.append(f"- `{s['file']}` ({s['phase']}): {s['note_cn']}")
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "## Hard bans honored",
            "",
            "- completion_claim_allowed not flipped true",
            "- partial not promoted to closed",
            "- G1 COMPLETED not promoted to C08/live_welded",
            "- G4 numbers not promoted to edge_claim",
            "- G5 matrix not promoted to product_closed",
            "- no dual-brain core source edits",
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")

    # Refresh state index (index only; keep completion false; keep partial)
    # Preserve v1 consumer fields where possible.
    state_payload = dict(payload)
    state_payload["schema_version"] = "xinao.kaigong.overnight_S0S8_progress_index.v2"
    state_payload["title_cn"] = "过夜/G6 S0–S8 综合进度索引（refresh；证据存在性 + status）"
    state_payload["g6_out_dir"] = str(OUT_DIR)
    state_payload["refreshed_from"] = "scripts/refresh_g6_s0s8_progress_index.py"
    # Map green_scoped count key for older readers
    state_payload["traffic_light"] = {
        **payload["traffic_light"],
        "green_scoped": payload["traffic_light"]["green_scoped"],
        "green": payload["traffic_light"]["green_scoped"],
    }
    STATE_INDEX.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "full": str(out_full),
        "stamped": str(out_stamp),
        "summary": str(out_summary),
        "summary_md": str(out_md),
        "state_index": str(STATE_INDEX),
    }


def main() -> int:
    payload = build_index()
    # Force safety invariants
    payload["completion_claim_allowed"] = False
    payload["product_closed"] = False
    payload["s0_s8_package_closed"] = False
    payload["p0_closed"] = False
    payload["temporal_mainline_closed"] = False
    for _ph, block in payload["phases"].items():
        block["completion_claim_allowed"] = False
        block["product_closed"] = False
        if block.get("status") == "closed":
            block["status"] = "partial"
            block["phase_status"] = "partial"

    paths = write_outputs(payload)
    print(
        json.dumps(
            {
                "ok": True,
                "refresh_role": "G16",
                "completion_claim_allowed": False,
                "overall": payload["traffic_light"]["overall"],
                "index_facts": payload.get("index_facts"),
                "phase_summary": payload["phase_summary"],
                "temporal_fact_correction": {
                    "adapter_landed": payload["temporal_fact_correction"]["adapter_landed"],
                    "live_welded": payload["temporal_fact_correction"]["live_welded"],
                    "g1_live_completed": payload["temporal_fact_correction"].get("g1_live_completed"),
                    "adapters_missing_claim": False,
                    "c08_verdict": payload["temporal_fact_correction"].get("c08_verdict"),
                },
                "stale_count": len(payload["stale_evidence"]),
                "outputs": paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
