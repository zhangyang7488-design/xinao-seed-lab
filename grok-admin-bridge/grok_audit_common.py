"""Shared Grok parallel global audit evidence builder (thin glue)."""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(r"C:\Users\xx363\CodexWorkspaces\B\nianhua")
RUNTIME_ROOT = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
BRIDGE_ROOT = pathlib.Path(__file__).resolve().parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime import task_intake_side_audit_report_generator as gen  # noqa: E402

GROK_AUDIT_SCOPE_CN = [
    "唯一事务进度：用户说话链上还有手搓在 default 吗",
    "意图连续性：还在做用户 originally 要的那件事吗",
    "执行分工：A 是 brain+派工还是 hand-roll 全包",
    "成熟承载 vs 手搓胶水",
    "尘埃到宇宙全扫：源码/组件/胶水/架构/本地/远端/投影——真升维还是假升维？",
    "弄完后下窗默认复现：热路径+owner+panel 续接，还是自锁/全局盘点/重跑canary？",
    "功能回归（不是 Git 脏，不是 GitHub 未推送）",
    "投影与假完成：PASS 是否被当成用户完成",
    "人类可验收：用户不用懂英文技术能继续吗",
]

DEFAULT_HANDROLL_PATH_HINTS = (
    "pump",
    "typeahead",
    "visible-inject",
    "visible_inject",
    "ack_worker",
    "handroll",
    "anti_handroll",
    "ucp_dispatch",
    "mcp_spawn",
    "latest.json",
    ".vbs",
    "action_write",
    "clean_ingress",
    "19142",
    "default_work_binding",
    "auto_exec_ack",
)

SOLE_MIGRATION_REF = BRIDGE_ROOT / "sole_migration_architecture.v1.json"
DIVISION_REF = BRIDGE_ROOT / "grok_parallel_audit_division.v1.json"
EXHAUSTIVE_HANDROLL_MATURE_REF = BRIDGE_ROOT / "grok_exhaustive_handroll_mature_audit.v1.json"
GLOBAL_UPGRADE_LENS_REF = pathlib.Path(r"C:\Users\xx363\Desktop\全局升维.txt")
WINDOW_REPRO_SELF_LOCK_REF = BRIDGE_ROOT / "grok_window_reproducibility_self_lock_audit.v1.json"
L0_CONVERGENCE_REF = BRIDGE_ROOT / "l0_global_convergence.v1.json"
DISPOSITION_MATRIX_REF = RUNTIME_ROOT / "state" / "global_object_disposition_matrix" / "latest.json"


def read_json(path: pathlib.Path, default=None):
    if not path.is_file():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sole_migration_anchor() -> dict:
    payload = read_json(SOLE_MIGRATION_REF, {})
    return {
        "ref": str(SOLE_MIGRATION_REF),
        "sole_mission_cn": payload.get("sole_mission_cn", ""),
        "progress_question_cn": payload.get("progress_question_cn", ""),
        "user_acceptance_cn": payload.get("user_acceptance_cn", ""),
        "chain": payload.get("chain", []),
        "handroll_forbidden_on_default": payload.get("handroll_forbidden_on_default", []),
        "not_north_star": payload.get("not_north_star", []),
    }


def division_anchor() -> dict:
    payload = read_json(DIVISION_REF, {})
    return {
        "ref": str(DIVISION_REF),
        "anti_collision": payload.get("anti_collision", {}),
        "repo_surface_policy": payload.get("repo_surface_policy", {}),
        "roles": payload.get("roles", {}),
        "sole_migration_chain_audit_map": payload.get("sole_migration_chain_audit_map", []),
        "grok_synthesis_contract_cn": payload.get("grok_synthesis_contract_cn", {}),
    }


def exhaustive_handroll_mature_anchor() -> dict:
    payload = read_json(EXHAUSTIVE_HANDROLL_MATURE_REF, {})
    return {
        "ref": str(EXHAUSTIVE_HANDROLL_MATURE_REF),
        "binding": payload.get("binding", "always_on_any_audit_lane"),
        "north_star_cn": payload.get("north_star_cn", ""),
        "progress_question_cn": payload.get("progress_question_cn", ""),
        "scan_layers": payload.get("scan_layers", []),
        "verdict_axes": payload.get("verdict_axes", []),
        "handroll_redlines_default": payload.get("handroll_redlines_default", []),
        "global_upgrade_intent_cn": payload.get("global_upgrade_intent_cn", ""),
        "fake_upgrade_redlines_cn": payload.get("fake_upgrade_redlines_cn", []),
        "mature_carriers_allowed": payload.get("mature_carriers_allowed", []),
        "required_fix_pattern_cn": payload.get("required_fix_pattern_cn", ""),
        "parallel_audit_note_cn": payload.get("parallel_audit_note_cn", ""),
        "evidence_refs": payload.get("evidence_refs", []),
        "audit_scope_cn": payload.get("audit_scope_cn", ""),
        "global_upgrade_lens_ref": payload.get("global_upgrade_lens_ref", str(GLOBAL_UPGRADE_LENS_REF)),
    }


def window_reproducibility_self_lock_anchor() -> dict:
    payload = read_json(WINDOW_REPRO_SELF_LOCK_REF, {})
    l0_live = read_json(RUNTIME_ROOT / "state" / "l0_global_convergence" / "latest.json", {})
    return {
        "ref": str(WINDOW_REPRO_SELF_LOCK_REF),
        "north_star_cn": payload.get("north_star_cn", ""),
        "reproduce_via_cn": payload.get("reproduce_via_cn", []),
        "not_reproduce_via_cn": payload.get("not_reproduce_via_cn", []),
        "self_lock_redlines_cn": payload.get("self_lock_redlines_cn", []),
        "admission_closeout_invariants_cn": payload.get("admission_closeout_invariants_cn", []),
        "audit_questions_cn": payload.get("audit_questions_cn", []),
        "verdict_axes": payload.get("verdict_axes", []),
        "l0_convergence_live": {
            "exists": bool(l0_live),
            "status": l0_live.get("status"),
            "hot_path_count": (l0_live.get("drift_signals") or {}).get("hot_path_count")
            or l0_live.get("hot_path_count"),
        },
    }


def global_upgrade_lens_anchor() -> dict:
    path = GLOBAL_UPGRADE_LENS_REF
    if not path.is_file():
        return {
            "ref": str(path),
            "exists": False,
            "note_cn": "用户桌面全局升维透镜缺失；审计仍按 exhaustive 合同执行",
        }
    text = path.read_text(encoding="utf-8-sig")
    return {
        "ref": str(path),
        "exists": True,
        "binding_cn": "所有审计车道统一六段透镜；尘埃到宇宙全范围；不绑历史案例",
        "sections_cn": [
            "旧框架识别",
            "目标函数重写",
            "成熟方案对照",
            "平行发散",
            "反死逻辑检查",
            "非技术用户可判断结果",
        ],
        "audit_scope_cn": "源码·组件·胶水·架构·default·本地·远端·运行时·仓库·投影·叙事·面板；meta 不豁免",
        "body_excerpt_cn": text[:1200],
    }


def disposition_matrix_summary(max_samples: int = 24) -> dict:
    payload = read_json(DISPOSITION_MATRIX_REF, {})
    if not payload:
        return {
            "ref": str(DISPOSITION_MATRIX_REF),
            "exists": False,
            "note_cn": "disposition_matrix missing; exhaustive scan must fall back to runtime + repo grep",
        }

    rows = payload.get("rows") or []
    disposition_counts: dict[str, int] = {}
    risk_flag_counts: dict[str, int] = {}
    default_handroll_candidates: list[dict] = []

    for row in rows:
        disposition = str(row.get("disposition") or "unknown")
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
        for flag in row.get("risk_flags") or []:
            risk_flag_counts[str(flag)] = risk_flag_counts.get(str(flag), 0) + 1

        path = str(row.get("path") or "")
        path_lower = path.lower()
        if any(hint in path_lower for hint in DEFAULT_HANDROLL_PATH_HINTS):
            default_handroll_candidates.append(
                {
                    "path": path,
                    "scope": row.get("scope"),
                    "disposition": row.get("disposition"),
                    "current_role": row.get("current_role"),
                    "mature_replacement": row.get("mature_replacement"),
                    "risk_flags": row.get("risk_flags") or [],
                }
            )

    default_handroll_candidates.sort(key=lambda item: str(item.get("path") or ""))
    return {
        "ref": str(DISPOSITION_MATRIX_REF),
        "exists": True,
        "status": payload.get("status"),
        "generated_at": payload.get("generated_at"),
        "coverage": payload.get("coverage", {}),
        "disposition_counts": disposition_counts,
        "risk_flag_counts_top": sorted(
            risk_flag_counts.items(), key=lambda item: item[1], reverse=True
        )[:12],
        "default_handroll_candidate_count": len(default_handroll_candidates),
        "default_handroll_candidates_sample": default_handroll_candidates[:max_samples],
        "audit_use_cn": (
            "穷举结论：对照 disposition + mature_replacement + default_work_binding.live；"
            "禁止把 matrix PASS/ready 当用户完成"
        ),
    }


def default_work_binding_live_hint() -> dict:
    binding_path = RUNTIME_ROOT / "state" / "default_work_binding" / "latest.json"
    payload = read_json(binding_path, {})
    if not payload:
        return {"ref": str(binding_path), "exists": False}
    return {
        "ref": str(binding_path),
        "exists": True,
        "status": payload.get("status"),
        "generated_at": payload.get("generated_at"),
        "main_chain_default": payload.get("main_chain_default"),
        "default_dispatch_policy": payload.get("default_dispatch_policy"),
        "live_evidence": payload.get("live_evidence"),
        "rescue_only": payload.get("rescue_only"),
        "named_blockers": payload.get("named_blockers") or payload.get("blockers") or [],
    }

ENGINEERING_PROFILES = {
    "B": {
        "role": "codex_b_engineering_audit",
        "repo": pathlib.Path(r"C:\Users\xx363\CodexWorkspaces\B\nianhua"),
        "codex_home": pathlib.Path(r"C:\Users\xx363\.codex-b"),
        "quota_label": "gpt-5.3-codex-spark",
    },
    "C": {
        "role": "codex_c_engineering_audit",
        "repo": pathlib.Path(r"C:\Users\xx363\CodexWorkspaces\C\nianhua"),
        "codex_home": pathlib.Path(r"C:\Users\xx363\.codex-c"),
        "quota_label": "standby",
    },
}


def grok_audit_state(evidence_path: pathlib.Path, user_focus_cn: str) -> dict:
    evidence = {}
    if evidence_path.is_file():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    base = gen.state_summary(RUNTIME_ROOT)
    git_surfaces = (evidence.get("git_surfaces") or []) if isinstance(evidence, dict) else []
    deferred_cleanup = (evidence.get("deferred_cleanup_hints") or []) if isinstance(evidence, dict) else []
    return {
        "audit_lane": "grok_parallel_global_side_audit",
        "protocol_id": "PHASE_PARALLEL_AUDIT_V1",
        "does_not_block_codex_a": True,
        "user_focus_cn": user_focus_cn,
        "sole_migration": sole_migration_anchor(),
        "division": division_anchor(),
        "global_upgrade_lens": global_upgrade_lens_anchor(),
        "window_reproducibility_self_lock": window_reproducibility_self_lock_anchor(),
        "exhaustive_handroll_mature": exhaustive_handroll_mature_anchor(),
        "disposition_matrix_summary": disposition_matrix_summary(),
        "default_work_binding_live": default_work_binding_live_hint(),
        "grok_global_human_audit_evidence": evidence,
        "machine_runtime_summary": base,
        "audit_scope_cn": GROK_AUDIT_SCOPE_CN,
        "repo_surface_observe_only": {
            "git_repo_not_mainline": True,
            "git_repo_tier": "opportunistic_cleanup_at_wrap_up",
            "github_not_progress_signal": True,
            "git_surfaces_observed": git_surfaces,
            "deferred_cleanup_hints": deferred_cleanup,
        },
        "forbidden": [
            "claim_user_completion",
            "block_codex_a_mainline",
            "elevate_git_dirty_to_mainline",
            "elevate_github_unpushed_to_mainline",
            "require_codex_modify_grok_workspace",
            "post_to_codex_a_during_audit_summon",
        ],
    }


ROLE_SCALE_FOCUS_CN = {
    "codex_b_engineering_audit": (
        "【本审计员尺度=小】专责尘埃级：单行源码、函数、hook、配置项、命名、薄胶水几行；"
        "穷举 default 路径上仍手搓的微观入口。"
    ),
    "codex_c_engineering_audit": (
        "【本审计员尺度=中】专责组件级：服务、适配器、脚本入口、state 文件、合同片段、MCP/UCP 包装；"
        "组件是否真换成熟承载还是假升维墙。"
    ),
    "dp_semantic_audit": (
        "【本审计员尺度=大】专责宇宙级：子系统、架构分层、default 路径、owner/事务模型、"
        "本地/远端/投影/叙事/用户可见面；真全局升维还是假升维叙事。"
    ),
    "deepseek_semantic_audit": (
        "【本审计员尺度=大】专责宇宙级：子系统、架构分层、default 路径、owner/事务模型、"
        "本地/远端/投影/叙事/用户可见面；真全局升维还是假升维叙事。"
    ),
}


def grok_audit_prompt(role: str, state: dict) -> str:
    scale_focus = ROLE_SCALE_FOCUS_CN.get(
        role,
        "【本审计员尺度=全】若未分工则尘埃到宇宙全扫。",
    )
    return (
        "Return one JSON object only. No markdown.\n"
        "Do not return {\"status\":\"ready\"}. Perform the audit from the evidence below now.\n"
        f"role must be {role}.\n"
        f"{scale_focus}\n"
        "Lens authority: C:\\Users\\xx363\\Desktop\\全局升维.txt six-section structure.\n"
        "Schema: {\"role\": string, \"decision\": \"PASS|NEEDS_REPAIR|REPAIR|BLOCK\", "
        "\"summary\": string, \"findings\": [{\"finding_id\": string, \"severity\": string, "
        "\"summary\": string, \"evidence\": string, \"recommended_action\": string, \"redline\": boolean}]}.\n"
        "You are an independent side auditor. CodexA mainline continues; do not block it. "
        "Do not claim user completion. Git/GitHub/local repo dirty is deferred_cleanup only, never mainline drift. "
        "Truth reads from runtime state under D:\\XINAO_CLEAN_RUNTIME\\state, not from repo PASS text. "
        "Answer sole_migration.progress_question_cn: is any handroll still on the default user-speech chain? "
        "Apply global_upgrade_lens (C:\\Users\\xx363\\Desktop\\全局升维.txt) six-section lens to EVERY audit object "
        "at EVERY scale (source line to architecture) and EVERY surface (local/remote/runtime/projection/narrative). "
        "No self-exemption for meta rules or audit contracts. "
        "Global upgrade (升维) is REQUIRED north star — user wants full stack elevation to mature carriers. "
        "Always run exhaustive_handroll_mature scan: for any object at any scale/surface, is handroll still on default, "
        "was real global upgrade applied on default (mature carrier + thin binding), or was fake upgrade "
        "(walls/docs/projection/new-control-plane narrative only) used while handroll remains on default? "
        "Use disposition_matrix_summary + default_work_binding_live as primary evidence; "
        "grok_parallel_global_audit/latest.json is dispatch receipt only, not verdict. "
        "Do not require CodexA to modify the Grok isolated workspace.\n"
        "Audit using audit_scope_cn, exhaustive_handroll_mature, and sole_migration_chain_audit_map in the evidence.\n"
        "Each finding on handroll/mature must cite path or runtime object and verdict_axis "
        "(still_handroll_on_default|real_global_upgrade_mature_on_default|fake_upgrade_narrative_only).\n"
        "After any 'done' claim, audit window_reproducibility_self_lock: can next window default-reproduce "
        "via Intent Spine + hot path + owner + panel without global inventory paralysis or hook self-lock? "
        "Verdict axes include window_default_reproducible|self_lock_risk|admission_closeout_gap.\n"
        "Current machine evidence JSON follows:\n"
        f"{json.dumps(state, ensure_ascii=False, indent=2)}"
    )