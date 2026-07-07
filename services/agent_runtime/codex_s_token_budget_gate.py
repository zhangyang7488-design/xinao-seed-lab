from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.token_budget_gate.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_TOKEN_BUDGET_GATE"
STATE_NAME = "codex_s_token_budget_gate"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(
    os.environ.get("XINAO_CODEX_S_REPO_ROOT")
    or os.environ.get("XINAO_REPO")
    or Path(__file__).resolve().parents[2]
)

SHORT_PROMPT_TOKENS = 512
SMALL_DIRECT_TOKENS = 2048
LARGE_TEXT_TOKENS = 8192
SMALL_FILE_BYTES = 16 * 1024
LARGE_FILE_BYTES = 64 * 1024
MAX_REPORTED_FILE_REFS = 12
GLOBAL_ROUTER_NAME = "GlobalCostQualityQuotaRouter"


KNOWN_FILE_EXTENSIONS = (
    "txt",
    "md",
    "json",
    "jsonl",
    "py",
    "ps1",
    "psm1",
    "bat",
    "cmd",
    "ts",
    "tsx",
    "js",
    "jsx",
    "css",
    "html",
    "htm",
    "yaml",
    "yml",
    "toml",
    "ini",
    "csv",
    "log",
    "xml",
    "sql",
    "rst",
    "pdf",
    "doc",
    "docx",
    "xlsx",
    "png",
    "jpg",
    "jpeg",
    "webp",
)


TERM_GROUPS = {
    "dialogue": (
        "讨论",
        "解释",
        "人话",
        "什么意思",
        "是不是",
        "为什么",
        "怎么看",
        "what does",
        "explain",
        "discuss",
    ),
    "watch": ("轮询", "镜像", "监工", "后台还在跑", "watch", "poll"),
    "execution": (
        "读取",
        "读",
        "看下",
        "检查",
        "搜索",
        "修",
        "弄",
        "落地",
        "实现",
        "写入",
        "更新",
        "追加",
        "生成",
        "跑",
        "调用",
        "喊",
        "commit",
        "push",
        "patch",
        "implement",
        "search",
        "inspect",
        "run",
        "完整收口",
        "全部收口",
        "收口基础",
        "默认主路绑定",
        "运行态加载",
    ),
    "extract": ("提取", "摘要", "总结", "盘点", "整理", "归纳", "extract", "summarize", "inventory"),
    "audit": (
        "审计",
        "冲突",
        "风险",
        "架构",
        "全局",
        "孤岛",
        "断层",
        "矛盾",
        "复盘",
        "audit",
        "conflict",
        "risk",
        "architecture",
    ),
    "mutation": (
        "修改",
        "修复",
        "落地",
        "写代码",
        "提交",
        "合并",
        "推送",
        "repo mutation",
        "aaq",
        "commit",
        "push",
        "merge",
    ),
    "closure": (
        "完整收口",
        "全部收口",
        "收口基础",
        "默认主路绑定",
        "运行态加载",
        "证据/readback",
        "提交推送",
        "提交合并",
        "origin/main",
        "closure bundle",
        "closeout",
        "full closeout",
    ),
    "external": (
        "外部",
        "自由搜索",
        "开源",
        "公开",
        "exa",
        "成熟",
        "官方",
        "upstream",
        "external",
        "web search",
        "open research",
    ),
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def safe_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)
    cleaned = cleaned.strip("-") or "prompt"
    if len(cleaned) <= 96:
        return cleaned
    digest = hashlib.sha256(cleaned.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{cleaned[:83].rstrip('-_')}-{digest}"


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / STATE_NAME
    return {
        "state": state,
        "latest": state / "latest.json",
        "records": state / "records",
        "readback": runtime / "readback" / "zh" / f"{STATE_NAME}.md",
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_event(raw_event_json: str) -> dict[str, Any]:
    if not raw_event_json.strip():
        return {}
    try:
        payload = json.loads(raw_event_json)
    except json.JSONDecodeError:
        return {"user_prompt": raw_event_json}
    return payload if isinstance(payload, dict) else {"user_prompt": str(payload)}


def event_prompt(event: dict[str, Any]) -> str:
    for key in ("user_prompt", "last_user_message", "prompt", "message", "latest_user_delta"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    messages = event.get("messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if isinstance(item, dict) and item.get("role") == "user":
                content = item.get("content")
                if isinstance(content, str):
                    return content
    return ""


def _strip_path_tail(value: str) -> str:
    stripped = value.strip().strip("'\"`“”‘’()[]{}<>，。；;：:,")
    ext_match = re.search(
        r"(?i)^(.+?\.(" + "|".join(re.escape(ext) for ext in KNOWN_FILE_EXTENSIONS) + r"))(?:\s+.*)?$",
        stripped,
    )
    if ext_match:
        return ext_match.group(1).strip().strip("'\"`，。；;：:,")
    return stripped


def extract_windows_paths(text: str) -> list[str]:
    candidates: list[str] = []
    file_pattern = re.compile(
        r"(?i)([a-z]:\\[^\r\n\"<>|]+?\.("
        + "|".join(re.escape(ext) for ext in KNOWN_FILE_EXTENSIONS)
        + r"))(?=$|[\s，。；;：:,])"
    )
    for match in file_pattern.finditer(text):
        candidates.append(_strip_path_tail(match.group(1)))
    generic_pattern = re.compile(r"(?i)([a-z]:\\[^\r\n\"<>|]+)")
    for match in generic_pattern.finditer(text):
        candidates.append(_strip_path_tail(match.group(1)))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(candidate)
    return deduped[:MAX_REPORTED_FILE_REFS]


def inspect_file_ref(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    exists = path.exists()
    is_file = path.is_file()
    is_dir = path.is_dir()
    size_bytes = 0
    child_count = 0
    line_count = 0
    if exists and is_file:
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
        if size_bytes <= 1_000_000:
            try:
                line_count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                line_count = 0
    elif exists and is_dir:
        try:
            child_count = sum(1 for _ in path.iterdir())
        except OSError:
            child_count = 0
    return {
        "path": str(path),
        "exists": exists,
        "is_file": is_file,
        "is_dir": is_dir,
        "size_bytes": size_bytes,
        "estimated_tokens": max(0, math.ceil(size_bytes / 4)) if is_file else 0,
        "line_count": line_count,
        "child_count": child_count,
    }


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def classify_prompt(prompt: str) -> dict[str, bool]:
    flags = {name: has_any(prompt, terms) for name, terms in TERM_GROUPS.items()}
    flags["human_dialogue_only"] = (
        flags["dialogue"]
        and not flags["execution"]
        and not flags["extract"]
        and not flags["audit"]
        and not flags["mutation"]
        and not flags["closure"]
        and not flags["external"]
    )
    return flags


def _file_totals(file_refs: list[dict[str, Any]]) -> dict[str, Any]:
    existing_files = [item for item in file_refs if item.get("is_file")]
    dirs = [item for item in file_refs if item.get("is_dir")]
    return {
        "file_count": len(existing_files),
        "dir_count": len(dirs),
        "total_file_bytes": sum(int(item.get("size_bytes") or 0) for item in existing_files),
        "total_estimated_file_tokens": sum(int(item.get("estimated_tokens") or 0) for item in existing_files),
        "any_large_file": any(int(item.get("size_bytes") or 0) >= LARGE_FILE_BYTES for item in existing_files),
        "any_directory": bool(dirs),
    }


def choose_route(
    *,
    prompt: str,
    prompt_tokens: int,
    file_refs: list[dict[str, Any]],
    flags: dict[str, bool],
) -> dict[str, Any]:
    totals = _file_totals(file_refs)
    has_files = bool(file_refs)
    large_context = (
        totals["total_estimated_file_tokens"] >= SMALL_DIRECT_TOKENS
        or prompt_tokens >= LARGE_TEXT_TOKENS
        or totals["any_large_file"]
        or totals["any_directory"]
        or totals["file_count"] > 1
    )
    small_context = (
        prompt_tokens <= SHORT_PROMPT_TOKENS
        and totals["total_estimated_file_tokens"] <= SMALL_DIRECT_TOKENS
        and not totals["any_directory"]
        and totals["file_count"] <= 1
    )
    if flags["human_dialogue_only"]:
        return {
            "route_id": "codex_direct_human_dialogue",
            "provider_order": ["codex"],
            "action": "answer_directly_no_worker_evidence",
            "codex_read_policy": "no_hot_path_reads_for_dialogue",
            "reason": "ordinary dialogue is cheaper and safer as direct Codex answer",
            "estimated_roundtrip_waste": True,
            "qwen_quota_priority_applies": False,
            "deepseek_codex_replacement_applies": False,
            "codex_boundary": "direct_dialogue_answer_only",
        }
    if flags["watch"] and not flags["mutation"]:
        return {
            "route_id": "foreground_mirror_watch",
            "provider_order": ["codex"],
            "action": "poll_or_watch_existing_backend_without_new_worker_evidence",
            "codex_read_policy": "read only mirror/latest pointers needed for watch",
            "reason": "watch mode should not spawn fresh Qwen/DP just to report status",
            "estimated_roundtrip_waste": True,
            "qwen_quota_priority_applies": False,
            "deepseek_codex_replacement_applies": False,
            "codex_boundary": "foreground_watch_and_status_synthesis",
        }
    if flags["mutation"] or flags["closure"]:
        pre_patch_order = (
            ["local_ollama_or_qwen_pre_extract", "deepseek_v4_pro_pre_patch_review", "codex_final_patch_aaq"]
            if large_context or flags["audit"] or flags["external"]
            else ["local_or_qwen_or_deepseek_optional_claimcard", "codex_final_patch_aaq"]
        )
        closure_reason = (
            " Execution closure additionally requires a closure evidence bundle: default mainline binding, runtime worker load, verification, evidence/readback, git clean status, commit hash, push target, 333/mainline state, and remaining/named-blocker state."
            if flags["closure"]
            else ""
        )
        return {
            "route_id": "codex_mutation_final_owner",
            "provider_order": pre_patch_order,
            "action": "Codex owns repo mutation/final patch; use local/Qwen/DP only for draft, pre-extract, or side audit",
            "codex_read_policy": "read focused files/diffs only; do not read raw long corpora unless gate routes direct",
            "reason": "repo mutation and acceptance need Codex ownership, but local/Qwen/DeepSeek should replace avoidable Codex bulk reading/thinking before final patch" + closure_reason,
            "estimated_roundtrip_waste": False,
            "qwen_quota_priority_applies": large_context or flags["extract"] or flags["external"],
            "deepseek_codex_replacement_applies": large_context or flags["audit"] or flags["external"],
            "codex_boundary": "final_patch_merge_aaq_high_risk_owner",
            "execution_closure_bundle_required": flags["closure"],
        }
    if has_files and small_context:
        return {
            "route_id": "codex_direct_small_read",
            "provider_order": ["codex"],
            "action": "read small file or short prompt directly",
            "codex_read_policy": "direct_read_allowed",
            "reason": "Qwen/DP roundtrip costs more than direct reading for small bounded context",
            "estimated_roundtrip_waste": True,
            "qwen_quota_priority_applies": False,
            "deepseek_codex_replacement_applies": False,
            "codex_boundary": "small_direct_read",
        }
    if flags["external"] and not has_files:
        return {
            "route_id": "search_then_local_qwen_dp_claimcards",
            "provider_order": ["search_exa_or_sourceledger", "codex_s_light_research_loop", "local_ollama_or_qwen_claimcard_draft", "deepseek_v4_pro_audit_if_needed", "codex_fan_in"],
            "action": "use codex_s.light_research_loop for foreground light research when a full 333 backend wave is not warranted; search/exa produces SourceLedger/ClaimCards; local/Qwen draft or compress results; DP/Pro audits when needed; Codex fan-in only",
            "codex_read_policy": "read search summaries and ClaimCards first, raw sources only when needed",
            "reason": "open research needs a separate retrieval lane plus cheap local/Qwen compression before Codex synthesis",
            "estimated_roundtrip_waste": False,
            "qwen_quota_priority_applies": True,
            "deepseek_codex_replacement_applies": True,
            "codex_boundary": "fan_in_synthesis_and_acceptance",
            "search_lane_boundary": "search/exa is retrieval only; models consume source artifacts and must not be described as the search provider",
            "local_model_role": "cheap_draft_summary_classify_compress_staging_only",
            "light_research_loop_entrypoint": "python -m xinao_seedlab.cli.__main__ light-research-loop",
        }
    if large_context and flags["audit"]:
        return {
            "route_id": "qwen_then_deepseek_pro_large_architecture_audit",
            "provider_order": ["qwen_extract", "deepseek_v4_pro_audit", "codex_fan_in"],
            "action": "Qwen extracts pointers, DeepSeek V4 Pro audits/conflicts/plans, Codex reads ClaimCards/artifact refs",
            "codex_read_policy": "do_not_read_full_raw_context_first",
            "reason": "large architecture/conflict audit should not burn Codex as the primary reader or thinker",
            "estimated_roundtrip_waste": False,
            "qwen_quota_priority_applies": True,
            "deepseek_codex_replacement_applies": True,
            "codex_boundary": "fan_in_final_judgment_not_raw_bulk_work",
        }
    if flags["audit"]:
        return {
            "route_id": "qwen_then_deepseek_pro_audit",
            "provider_order": ["qwen_extract_or_quality", "deepseek_v4_pro_audit", "codex_fan_in"],
            "action": "Qwen handles suitable cheap extraction/quality pass, DeepSeek V4 Pro replaces Codex for heavy audit thinking, Codex fan-in decides",
            "codex_read_policy": "read focused local evidence and DP artifact, not unrelated raw context",
            "reason": "audit/conflict work should spend Qwen quota first when suitable and use DeepSeek Pro before Codex final judgment",
            "estimated_roundtrip_waste": False,
            "qwen_quota_priority_applies": True,
            "deepseek_codex_replacement_applies": True,
            "codex_boundary": "final_judgment_and_acceptance",
        }
    if large_context or flags["extract"]:
        return {
            "route_id": "qwen_pre_extract",
            "provider_order": ["qwen_or_local_candidate", "codex"],
            "action": "Qwen/prepaid cheap lane extracts first; local Ollama is a scored candidate when suitable; Codex reads compact artifact/ref",
            "codex_read_policy": "do_not_read_full_raw_context_first",
            "reason": "bulk extraction and inventory are cheaper through Qwen/local candidate workers before Codex fan-in",
            "estimated_roundtrip_waste": False,
            "qwen_quota_priority_applies": True,
            "deepseek_codex_replacement_applies": False,
            "codex_boundary": "reads_compact_artifact_refs",
        }
    return {
        "route_id": "codex_direct_short_prompt",
        "provider_order": ["codex"],
        "action": "answer or inspect directly unless later context expands",
        "codex_read_policy": "direct_small_context_allowed",
        "reason": "short bounded request is cheaper than provider roundtrip",
        "estimated_roundtrip_waste": prompt_tokens <= SHORT_PROMPT_TOKENS,
        "qwen_quota_priority_applies": False,
        "deepseek_codex_replacement_applies": False,
        "codex_boundary": "short_direct_answer_or_inspection",
    }


def build_global_router(decision: dict[str, Any], flags: dict[str, bool]) -> dict[str, Any]:
    return {
        "router_name": GLOBAL_ROUTER_NAME,
        "layer": "UserPromptSubmit_pre_read_global_router",
        "not_model_worker_scheduler": True,
        "not_333_mainline": True,
        "serves_333_by_preventing_unnecessary_codex_context_burn": True,
        "default_ladder": [
            "codex_direct_for_short_bounded_or_dialogue",
            "qwen_prepaid_quota_first_when_task_suitable",
            "local_ollama_candidate_when_router_scores_positive",
            "deepseek_v4_flash_for_qwen_gap_or_bulk_staging",
            "deepseek_v4_pro_for_hard_audit_architecture_multifile_planning",
            "codex_only_for_high_risk_patch_final_merge_aaq",
        ],
        "selected_route_id": decision.get("route_id", ""),
        "selected_provider_order": decision.get("provider_order", []),
        "qwen_quota_priority_applies": decision.get("qwen_quota_priority_applies") is True,
        "deepseek_codex_replacement_applies": decision.get("deepseek_codex_replacement_applies") is True,
        "fixed_deepseek_share_target_used": False,
        "codex_boundary": decision.get("codex_boundary", ""),
        "must_not": [
            "do_not_make_deepseek_fixed_80_90_target",
            "do_not_treat_search_exa_as_deepseek_execution",
            "do_not_treat_local_model_as_search_provider",
            "do_not_make_qwen_global_primary_when_unsuitable",
            "do_not_let_codex_read_large_raw_context_before_gate",
            "do_not_replace_final_patch_merge_aaq_with_worker_output",
        ],
        "provider_scheduler_hint": {
            "qwen_quota_priority_default": True,
            "local_ollama_qwen_default_first_when_configured": False,
            "local_model_candidate_when_scored": True,
            "local_first_mandatory": False,
            "ollama_resource_limits_not_route_policy": True,
            "local_model_scope": "cheap_draft_summary_classify_compress_staging_only_candidate",
            "search_provider_boundary": "search/exa retrieves SourceLedger/ClaimCards; local/Qwen/DeepSeek consume results",
            "light_research_loop_entrypoint": "python -m xinao_seedlab.cli.__main__ light-research-loop",
            "light_research_loop_scope": "foreground_temporary_search_audit_not_333_mainline",
            "deepseek_v4_pro_codex_replacement": True,
            "codex_bulk_worker_default_paused": True,
            "codex_allowed_boundary": [
                "codex_brain_decision",
                "high_risk_patch_or_repo_mutation",
                "final_merge_artifact_acceptance",
            ],
            "task_flags": flags,
        },
    }


def build_payload(
    *,
    raw_event_json: str,
    repo_root: str | Path = DEFAULT_REPO,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    event = load_event(raw_event_json)
    prompt = event_prompt(event)
    prompt_tokens = estimate_tokens(prompt)
    file_refs = [inspect_file_ref(path) for path in extract_windows_paths(prompt)]
    flags = classify_prompt(prompt)
    decision = choose_route(
        prompt=prompt,
        prompt_tokens=prompt_tokens,
        file_refs=file_refs,
        flags=flags,
    )
    global_router = build_global_router(decision, flags)
    paths = output_paths(runtime)
    prompt_hash = hashlib.sha256(prompt.encode("utf-8", errors="replace")).hexdigest()
    record_path = paths["records"] / f"{safe_stem(prompt_hash[:16])}.json"
    context = (
        "GlobalCostQualityQuotaRouter: "
        f"route={decision['route_id']}; "
        f"action={decision['action']}; "
        f"codex_read_policy={decision['codex_read_policy']}; "
        "small bounded context stays Codex-direct; Qwen/prepaid quota is first cloud cheap lane when suitable; "
        "local Ollama/Qwen is a scored cheap candidate, not a mandatory first hop; "
        "OLLAMA_MAX_LOADED_MODELS/OLLAMA_NUM_PARALLEL are resource limits, not route policy; "
        "search/Exa is a separate retrieval lane that produces SourceLedger/ClaimCards; "
        "DeepSeek V4 Flash/Pro replaces avoidable Codex bulk thinking after Qwen/local candidates when needed; "
        "Codex remains final patch/merge/AAQ/high-risk owner."
    )
    if flags.get("closure"):
        context = (
            context
            + " Execution closure/full closeout requires a closure evidence bundle before final wording: "
            "default mainline binding, runtime worker load, verification, evidence/readback, git clean status, "
            "commit hash, push target, 333/mainline state, and remaining/named-blocker state."
        )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "token_budget_gate_ready",
        "generated_at": now_iso(),
        "repo_root": str(repo),
        "runtime_root": str(runtime),
        "prompt_sha256": prompt_hash,
        "estimated_user_prompt_tokens": prompt_tokens,
        "thresholds": {
            "short_prompt_tokens": SHORT_PROMPT_TOKENS,
            "small_direct_tokens": SMALL_DIRECT_TOKENS,
            "large_text_tokens": LARGE_TEXT_TOKENS,
            "small_file_bytes": SMALL_FILE_BYTES,
            "large_file_bytes": LARGE_FILE_BYTES,
        },
        "flags": flags,
        "file_refs": file_refs,
        "file_totals": _file_totals(file_refs),
        "decision": decision,
        "global_router": global_router,
        "hook_additional_context": context,
        "not_execution_controller": True,
        "not_completion_gate": True,
        "not_stop_condition": True,
        "completion_claim_allowed": False,
        "fail_open": True,
        "adoption_state": "user_prompt_submit_hook_advisory",
        "evidence_refs": {
            "latest": str(paths["latest"]),
            "record": str(record_path),
            "readback": str(paths["readback"]),
        },
    }
    if write:
        write_json(record_path, payload)
        write_json(paths["latest"], payload)
        write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    return "\n".join(
        [
            "# Codex S TokenBudgetGate 回读",
            "",
            SENTINEL,
            "",
            f"- status: `{payload.get('status')}`",
            f"- route: `{decision.get('route_id')}`",
            f"- action: `{decision.get('action')}`",
            f"- provider_order: `{', '.join(decision.get('provider_order') or [])}`",
            f"- search_lane_boundary: `{decision.get('search_lane_boundary', '')}`",
            f"- local_model_role: `{decision.get('local_model_role', 'cheap_draft_summary_classify_compress_staging_only_when_configured')}`",
            f"- global_router: `{payload.get('global_router', {}).get('router_name')}`",
            f"- qwen_quota_priority: {payload.get('global_router', {}).get('qwen_quota_priority_applies')}",
            f"- deepseek_codex_replacement: {payload.get('global_router', {}).get('deepseek_codex_replacement_applies')}",
            f"- prompt_tokens_estimate: {payload.get('estimated_user_prompt_tokens')}",
            f"- file_tokens_estimate: {payload.get('file_totals', {}).get('total_estimated_file_tokens')}",
            "- boundary: advisory only; not execution controller; not completion gate.",
            "",
            SENTINEL,
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-s-token-budget-gate")
    parser.add_argument("--raw-event-json", default="")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    raw_event_json = args.raw_event_json
    if not raw_event_json:
        raw_event_json = sys.stdin.read()
    payload = build_payload(
        raw_event_json=raw_event_json,
        repo_root=args.repo_root,
        runtime_root=args.runtime_root,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
