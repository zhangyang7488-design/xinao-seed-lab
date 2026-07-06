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
        "final",
        "aaq",
        "commit",
        "push",
        "merge",
    ),
    "external": (
        "外部",
        "自由搜索",
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
        }
    if flags["watch"] and not flags["mutation"]:
        return {
            "route_id": "foreground_mirror_watch",
            "provider_order": ["codex"],
            "action": "poll_or_watch_existing_backend_without_new_worker_evidence",
            "codex_read_policy": "read only mirror/latest pointers needed for watch",
            "reason": "watch mode should not spawn fresh Qwen/DP just to report status",
            "estimated_roundtrip_waste": True,
        }
    if flags["mutation"]:
        return {
            "route_id": "codex_mutation_final_owner",
            "provider_order": ["qwen_or_dp_optional_claimcard", "codex"],
            "action": "Codex owns repo mutation/final patch; use Qwen/DP only for large pre-extract or side audit",
            "codex_read_policy": "read focused files/diffs only; do not read raw long corpora unless gate routes direct",
            "reason": "repo mutation and acceptance need Codex ownership, but bulk context can be compressed first",
            "estimated_roundtrip_waste": False,
        }
    if has_files and small_context:
        return {
            "route_id": "codex_direct_small_read",
            "provider_order": ["codex"],
            "action": "read small file or short prompt directly",
            "codex_read_policy": "direct_read_allowed",
            "reason": "Qwen/DP roundtrip costs more than direct reading for small bounded context",
            "estimated_roundtrip_waste": True,
        }
    if flags["external"] and not has_files:
        return {
            "route_id": "search_qwen_dp_claimcards",
            "provider_order": ["search", "qwen", "dp", "codex"],
            "action": "external mature search plus Qwen/DP ClaimCards, Codex fan-in",
            "codex_read_policy": "read search summaries and ClaimCards first, raw sources only when needed",
            "reason": "open research needs source fanout and cheap compression before Codex synthesis",
            "estimated_roundtrip_waste": False,
        }
    if large_context and flags["audit"]:
        return {
            "route_id": "dp_pre_audit_large_context",
            "provider_order": ["qwen_extract", "dp_audit", "codex"],
            "action": "Qwen extracts pointers, DP audits conflicts, Codex reads ClaimCards/artifact refs",
            "codex_read_policy": "do_not_read_full_raw_context_first",
            "reason": "large architecture/conflict audit is high-risk and expensive if Codex reads everything first",
            "estimated_roundtrip_waste": False,
        }
    if large_context or flags["extract"]:
        return {
            "route_id": "qwen_pre_extract",
            "provider_order": ["qwen", "codex"],
            "action": "Qwen extracts/summarizes first, Codex reads compact artifact/ref",
            "codex_read_policy": "do_not_read_full_raw_context_first",
            "reason": "bulk extraction and inventory are cheaper through Qwen before Codex fan-in",
            "estimated_roundtrip_waste": False,
        }
    if flags["audit"]:
        return {
            "route_id": "dp_audit_first",
            "provider_order": ["dp", "codex"],
            "action": "DP audits first, Codex fan-in and decides",
            "codex_read_policy": "read focused local evidence and DP artifact, not unrelated raw context",
            "reason": "audit/conflict work benefits from cheap independent contradiction before Codex final judgment",
            "estimated_roundtrip_waste": False,
        }
    return {
        "route_id": "codex_direct_short_prompt",
        "provider_order": ["codex"],
        "action": "answer or inspect directly unless later context expands",
        "codex_read_policy": "direct_small_context_allowed",
        "reason": "short bounded request is cheaper than provider roundtrip",
        "estimated_roundtrip_waste": prompt_tokens <= SHORT_PROMPT_TOKENS,
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
    paths = output_paths(runtime)
    prompt_hash = hashlib.sha256(prompt.encode("utf-8", errors="replace")).hexdigest()
    record_path = paths["records"] / f"{safe_stem(prompt_hash[:16])}.json"
    context = (
        "TokenBudgetGate: "
        f"route={decision['route_id']}; "
        f"action={decision['action']}; "
        f"codex_read_policy={decision['codex_read_policy']}; "
        "small bounded context stays Codex-direct; large extraction/audit/search goes Qwen/DP first; "
        "repo mutation/final acceptance stays Codex-owned."
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
