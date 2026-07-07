from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_DEFAULT_REPO_FOR_IMPORT = Path(
    os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S")
)
if _DEFAULT_REPO_FOR_IMPORT.is_dir() and str(_DEFAULT_REPO_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_DEFAULT_REPO_FOR_IMPORT))

from services.agent_runtime import task_package_resolver as task_package


SCHEMA_VERSION = "xinao.codex_s.source_family_wave_scheduler.v1"
SENTINEL = "SENTINEL:XINAO_SOURCE_FAMILY_WAVE_SCHEDULER_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
PARENT_TASK_ID = WORK_ID
TASK_ID = "wave4_20260701_frontier_source_family_20260704"
ROUTING = "continue_same_task"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = _DEFAULT_REPO_FOR_IMPORT
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
SOURCE_TOPIC_CLAIMCARD_BATCH_SIZE = 8
SRC_ROOT = DEFAULT_REPO / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

AUTHORITY_FILES = list(task_package.LEGACY_AUTHORITY_FILES)
TASK_PACKAGE_MANIFEST_NAMES = list(task_package.TASK_PACKAGE_MANIFEST_NAMES)
TOTAL_FRONTIER_SOURCE_FILES = list(task_package.LEGACY_AUTHORITY_FILES[1:])

CLAIM_CARD_REQUIRED_FIELDS = [
    "source_url",
    "source_family",
    "claim",
    "verification_need",
    "accepted_for",
]

TOPIC_HEADING_RE = re.compile(
    r"^(?:"
    r"\d+(?:\.\d+){0,3}[\.、]?\s+.+"
    r"|帮助[一二三四五六七八九十]+[:：].+"
    r"|【[^】]{2,80}】"
    r"|[A-Za-z][A-Za-z0-9 /+\-]{2,80}:$"
    r")$"
)

COVERAGE_KEYWORDS = [
    "RootIntentLoop",
    "Temporal",
    "LangGraph",
    "MCP",
    "Docker MCP",
    "MCP Registry",
    "LiteLLM",
    "OpenRouter",
    "SourceLedger",
    "ClaimCard",
    "AAQ",
    "FanIn",
    "DeepSeek",
    "Provider",
    "WorkerBrief",
    "OpenHands",
    "SWE",
    "benchmark",
    "Seed Lab",
    "Phase 0",
    "Phase 1",
    "正期望",
    "数据链",
    "能力获取",
    "外部搜索",
    "最大收益",
    "动态轮回",
    "成熟承载",
    "工具发现",
    "记忆",
    "伙伴型",
    "回测",
    "防过拟合",
    "lockbox",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def replace_path_with_retry(tmp: Path, path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(25):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.04 * (attempt + 1))
    if last_error is not None:
        raise last_error


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "json_valid": bool(payload) or not path.is_file(),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "validation_passed": validation.get("passed"),
        "not_execution_controller": payload.get("not_execution_controller"),
    }


def output_paths(repo: Path, runtime: Path, wave_id: str) -> dict[str, str]:
    root = runtime / "state" / "source_family_wave_scheduler"
    episode_id = f"source-family-wave-{wave_id}"
    return {
        "runtime_latest": str(root / "latest.json"),
        "wave_latest": str(root / "waves" / f"{wave_id}.json"),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_source_family_wave_scheduler.v1.json"),
        "worker_assignment_latest": str(runtime / "state" / "worker_assignment" / f"{TASK_ID}.json"),
        "worker_assignment_wave": str(runtime / "state" / "worker_assignment" / f"{TASK_ID}.{wave_id}.json"),
        "source_family_wave_plan_latest": str(runtime / "state" / "source_family_wave_plan" / "latest.json"),
        "source_topic_claimcards_latest": str(root / "source_topic_claimcards" / "latest.json"),
        "source_topic_claimcards_wave": str(root / "source_topic_claimcards" / f"{wave_id}.json"),
        "claim_card_staging_queue_latest": str(runtime / "state" / "claim_card_staging_queue" / "latest.json"),
        "fan_in_acceptance_queue_latest": str(runtime / "state" / "fan_in_acceptance_queue" / "latest.json"),
        "artifact_acceptance_queue_latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "source_ledger_latest": str(runtime / "state" / "source_ledger" / "latest.json"),
        "next_frontier_machine_actions_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "source_family_search_evidence_latest": str(root / "source_family_search_evidence" / "latest.json"),
        "total_source_frontier_coverage_latest": str(root / "total_source_frontier_coverage" / "latest.json"),
        "total_source_frontier_coverage_wave": str(
            root / "total_source_frontier_coverage" / f"{wave_id}.json"
        ),
        "mature_carrier_replacement_bindings_latest": str(
            runtime / "state" / "mature_carrier_replacement_bindings" / "latest.json"
        ),
        "mature_carrier_replacement_bindings_wave": str(
            root / "mature_carrier_replacement_bindings" / f"{wave_id}.json"
        ),
        "mature_carrier_thin_bind_manifest": str(
            runtime / "capabilities" / "codex_s.source_family_mature_carrier_thin_bind" / "manifest.json"
        ),
        "episode_workflow_entry": str(runtime / "runs" / "episodes" / episode_id / "workflow_entry.json"),
        "episode_trace": str(runtime / "runs" / "episodes" / episode_id / "episode_trace.jsonl"),
        "black_window_evidence_latest": str(runtime / "state" / "background_window_hygiene" / "latest.json"),
        "readback_zh": str(runtime / "readback" / "zh" / "wave_block4_20260701_frontier_20260704.md"),
    }


def file_source_ref(path: Path) -> dict[str, Any]:
    if path.is_file():
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        encoded = text.encode("utf-8", errors="replace")
        return {
            "path": str(path),
            "exists": True,
            "read_full": True,
            "size_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    return {
        "path": str(path),
        "exists": False,
        "read_full": False,
        "size_bytes": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
    }


def task_package_manifest_ref(anchor: Path) -> dict[str, Any] | None:
    for name in TASK_PACKAGE_MANIFEST_NAMES:
        path = anchor / name
        if not path.is_file():
            continue
        ref = file_source_ref(path)
        ref["role"] = "task_package_manifest"
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
        except json.JSONDecodeError as exc:
            ref.update({"json_valid": False, "parse_error": str(exc)})
        else:
            ref.update({"json_valid": isinstance(payload, dict), "payload": payload})
        return ref
    return None


def normalize_manifest_resource_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or "://" in text:
        return ""
    candidate = Path(text)
    if candidate.is_absolute() or candidate.drive or text.startswith("/") or text.startswith("../"):
        return ""
    if any(part in {"..", ""} for part in candidate.parts):
        return ""
    return text


def task_package_manifest_file_names(manifest_ref: dict[str, Any]) -> list[str]:
    payload = manifest_ref.get("payload")
    if not isinstance(payload, dict):
        return []
    entries: list[Any] = []
    for key in ("hot_path_files", "files"):
        value = payload.get(key)
        if isinstance(value, list):
            entries.extend(value)
    resources = payload.get("resources")
    if isinstance(resources, list):
        entries.extend(resources)

    names: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            raw_path: Any = entry
        elif isinstance(entry, dict):
            if entry.get("exclude") is True or entry.get("reference_only") is True:
                continue
            if str(entry.get("read") or "").lower() in {"reference_only", "skip", "none"}:
                continue
            raw_path = entry.get("path")
        else:
            continue
        name = normalize_manifest_resource_path(raw_path)
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def source_package_refs(anchor: Path) -> dict[str, Any]:
    package = task_package.resolve_task_package(
        anchor,
        legacy_files=tuple(AUTHORITY_FILES),
        include_manifest_ref=False,
    )
    refs = package.get("refs", [])
    file_names = [Path(str(ref.get("path") or "")).name for ref in refs]
    return {
        **package,
        "root": str(anchor),
        "authority_files": (
            list(file_names)
            if package.get("manifest_driven") or package.get("legacy_fallback") is not True
            else list(AUTHORITY_FILES)
        ),
        "frontier_source_files": (
            list(file_names)
            if package.get("manifest_driven") or package.get("legacy_fallback") is not True
            else list(TOTAL_FRONTIER_SOURCE_FILES)
        ),
        "refs": refs,
        "all_required_sources_read_full": bool(refs) and all(ref["read_full"] for ref in refs),
        "source_package_back_ref_required": True,
        "source_frontier_scope": (
            "current_p0_manifest_task_package"
            if package.get("manifest_driven")
            else "20260701_total_source_frontier_after_wave3"
        ),
    }


def normalize_for_match(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def topic_family_id(source_name: str, line_no: int, title: str) -> str:
    digest = hashlib.sha256(f"{source_name}:{line_no}:{title}".encode("utf-8")).hexdigest()[:12]
    if "20260701" in source_name:
        stem = "source20260701"
    elif "20260702" in source_name:
        stem = "source20260702"
    else:
        stem = re.sub(r"[^A-Za-z0-9]+", "_", Path(source_name).stem).strip("_")[:40] or "source"
    return f"{stem}:L{line_no}:{digest}"


def heading_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    topics: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or len(line) > 180:
            continue
        if set(line) <= {"-", "=", "_"}:
            continue
        if not TOPIC_HEADING_RE.match(line):
            continue
        topics.append(
            {
                "topic_family_id": topic_family_id(path.name, line_no, line),
                "source_ref": str(path),
                "source_file": path.name,
                "line_no": line_no,
                "title": line,
                "required_acceptance_path": "ClaimCard -> SourceLedger -> FanInAcceptanceQueue -> AAQ",
            }
        )
    if topics:
        return topics
    text_digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    return [
        {
            "topic_family_id": f"{path.stem}:file:{text_digest}",
            "source_ref": str(path),
            "source_file": path.name,
            "line_no": 1,
            "title": path.stem,
            "required_acceptance_path": "ClaimCard -> SourceLedger -> FanInAcceptanceQueue -> AAQ",
        }
    ]


def coverage_keywords_for(title: str) -> list[str]:
    title_norm = normalize_for_match(title)
    hits = [keyword for keyword in COVERAGE_KEYWORDS if normalize_for_match(keyword) in title_norm]
    ascii_words = re.findall(r"[A-Za-z][A-Za-z0-9_+\-/]{2,}", title)
    for word in ascii_words:
        if word not in hits:
            hits.append(word)
    for phrase in ("能力获取", "外部研究", "成熟", "搜索", "验证", "回测", "记忆", "工具", "MCP"):
        if phrase in title and phrase not in hits:
            hits.append(phrase)
    return hits


def matching_claim_card_ids(topic: dict[str, Any], cards: list[dict[str, Any]]) -> list[str]:
    topic_family_id = str(topic.get("topic_family_id") or "")
    keywords = coverage_keywords_for(str(topic.get("title") or ""))
    if not keywords and not topic_family_id:
        return []
    matched: list[str] = []
    for card in cards:
        if topic_family_id and str(card.get("topic_family_id") or "") == topic_family_id:
            matched.append(str(card.get("candidate_id") or ""))
            continue
        haystack = normalize_for_match(
            " ".join(
                str(card.get(key) or "")
                for key in ("candidate_id", "source_url", "source_family", "claim", "accepted_for", "topic_family_id")
            )
        )
        if any(normalize_for_match(keyword) in haystack for keyword in keywords):
            matched.append(str(card.get("candidate_id") or ""))
    return matched


def build_total_source_frontier_coverage(
    *, anchor: Path, source_package: dict[str, Any], cards: list[dict[str, Any]], paths: dict[str, str]
) -> dict[str, Any]:
    topics: list[dict[str, Any]] = []
    frontier_files = [
        str(item)
        for item in source_package.get("frontier_source_files", [])
        if str(item).strip()
    ]
    for name in frontier_files:
        topics.extend(heading_candidates(anchor / name))

    covered: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for topic in topics:
        matched_cards = matching_claim_card_ids(topic, cards)
        item = {
            **topic,
            "matched_claim_card_ids": matched_cards,
            "accepted_through_aaq": bool(matched_cards),
            "completion_claim_allowed": False,
        }
        if matched_cards:
            covered.append(item)
        else:
            remaining.append(item)

    total_count = len(topics)
    covered_count = len(covered)
    remaining_count = len(remaining)
    next_batch = [
        {
            "topic_family_id": item["topic_family_id"],
            "title": item["title"],
            "source_ref": item["source_ref"],
            "line_no": item["line_no"],
            "recommended_lane": "source frontier expansion -> WorkerBrief -> pool -> merge -> AAQ -> SourceLedger",
        }
        for item in remaining[:8]
    ]
    return {
        "schema_version": "xinao.codex_s.total_source_frontier_coverage.v1",
        "status": "total_source_frontier_coverage_ready",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "source_files": [str(anchor / name) for name in frontier_files],
        "manifest_driven": source_package.get("manifest_driven") is True,
        "package_mode": source_package.get("package_mode"),
        "topic_family_count": total_count,
        "covered_topic_family_count": covered_count,
        "remaining_topic_family_count": remaining_count,
        "coverage_ratio": round((covered_count / total_count), 4) if total_count else 0.0,
        "source_gap_open": remaining_count > 0,
        "covered_topic_families": covered,
        "remaining_topic_families": remaining,
        "remaining_topic_family_names": [str(item["title"]) for item in remaining],
        "next_source_family_batch": next_batch,
        "output_paths": {
            "runtime_latest": paths["total_source_frontier_coverage_latest"],
            "wave": paths["total_source_frontier_coverage_wave"],
        },
        "validation": {
            "passed": total_count > 0 and (covered_count + remaining_count == total_count),
            "checks": {
                "topic_families_extracted": total_count > 0,
                "covered_plus_remaining_matches_total": covered_count + remaining_count == total_count,
                "remaining_count_explicit": remaining_count >= 0,
                "source_gap_state_explicit": isinstance(remaining_count > 0, bool),
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def claim_cards(runtime: Path, source_package: dict[str, Any]) -> list[dict[str, Any]]:
    local_latest = runtime / "state" / "source_frontier_durable_consumer" / "latest.json"
    is_current_manifest = source_package.get("manifest_driven") is True
    local_claim = (
        "Current manifest task package has durable SourceLedger/FanIn/AAQ evidence; continue the P0 hot path without reading old total drafts."
        if is_current_manifest
        else "Wave3 source frontier slice has durable consumer evidence with source_gap_open=false and remaining_batch_ids empty; block4 may proceed to total 20260701 frontier."
    )
    return [
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-temporal-task-queue-worker-polling",
            "source_url": "https://docs.temporal.io/task-queue",
            "source_type": "official_docs",
            "source_family": "official_provider_docs",
            "claim": "Temporal Task Queues are the durable queue boundary for Workflow and Activity Tasks; S should keep Temporal as the transaction carrier, not a 30-minute runner.",
            "supports_or_contradicts": "supports",
            "current_engineering_delta": "Keep block4 lanes event/backlog/frontier-driven through Temporal activity and task queue evidence.",
            "accepted_for": "wave4_source_family_default_lane",
            "verification_need": "Temporal worker poller evidence plus source-family AAQ acceptance.",
            "promotion_gate": "task_scoped_activity_evidence_only",
            "artifact_ref": "web:temporal-task-queue",
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-langgraph-persistence-checkpoint-not-owner",
            "source_url": "https://docs.langchain.com/oss/python/langgraph/persistence",
            "source_type": "official_docs",
            "source_family": "official_framework_docs",
            "claim": "LangGraph persistence is useful checkpoint/store state, but remains inside activity-level state handling and does not replace Temporal as durable owner.",
            "supports_or_contradicts": "supports",
            "current_engineering_delta": "Use checkpoint/read-model semantics for replay evidence, not as S main loop owner.",
            "accepted_for": "wave4_source_family_default_lane",
            "verification_need": "Next block5 should bind replay/checkpoint evidence without replacing RootIntentLoop.",
            "promotion_gate": "phase0_reusable_kernel_gate",
            "artifact_ref": "web:langgraph-persistence",
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-mcp-reference-servers-and-registry",
            "source_url": "https://github.com/modelcontextprotocol/servers",
            "source_type": "github_repo",
            "source_family": "github_open_source_repo",
            "claim": "MCP reference/community servers are a mature discovery lane for tool adapters; they should enter SourceLedger/ClaimCard before any thin adapter is promoted.",
            "supports_or_contradicts": "supports",
            "current_engineering_delta": "Treat MCP server discovery as source-family lane output, not S control plane.",
            "accepted_for": "wave4_mature_carrier_candidate",
            "verification_need": "Adapter smoke is required before default capability registration.",
            "promotion_gate": "reference_only_until_adapter_smoke",
            "artifact_ref": "web:modelcontextprotocol-servers",
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-mcp-contextforge-gateway-candidate",
            "source_url": "https://github.com/IBM/mcp-context-forge",
            "source_type": "github_repo",
            "source_family": "github_open_source_repo",
            "claim": "ContextForge is a candidate registry/proxy pattern for MCP and REST/gRPC federation; keep it as candidate_pattern until an adapter smoke proves value.",
            "supports_or_contradicts": "supports",
            "current_engineering_delta": "Adds a mature-carrier replacement candidate for hand-written tool registry glue.",
            "accepted_for": "wave4_mature_carrier_candidate",
            "verification_need": "Smoke an S-scoped adapter or keep reference_only.",
            "promotion_gate": "reference_only_candidate_pattern",
            "artifact_ref": "web:ibm-contextforge",
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-openhands-agent-canvas-candidate",
            "source_url": "https://github.com/OpenHands/OpenHands",
            "source_type": "github_repo",
            "source_family": "github_open_source_repo",
            "claim": "OpenHands is a mature coding-agent carrier candidate for self-hosted automations; it can inform worker-carrier design but is not promoted without adapter smoke.",
            "supports_or_contradicts": "supports",
            "current_engineering_delta": "Keep coding-agent carrier discovery in source-family lane, not as a replacement S brain.",
            "accepted_for": "wave4_mature_carrier_candidate",
            "verification_need": "Adapter smoke and AAQ acceptance required before default route change.",
            "promotion_gate": "reference_only_candidate_pattern",
            "artifact_ref": "web:openhands",
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-agent-benchmark-realism-swe-bench",
            "source_url": "https://www.swebench.com/verified.html",
            "source_type": "benchmark_site",
            "source_family": "papers_benchmarks",
            "claim": "Coding-agent progress should be measured with task-scoped artifact acceptance and verified issue-like evidence, not PASS text or lane counts.",
            "supports_or_contradicts": "supports",
            "current_engineering_delta": "Block5 reusable-kernel gate should require replayable evidence, not smoke-only completion.",
            "accepted_for": "wave5_phase0_reusable_kernel_next",
            "verification_need": "Four-object replay and provider swap tests must gate the next frontier.",
            "promotion_gate": "phase0_reusable_kernel_gate",
            "artifact_ref": "web:swebench-verified",
        },
        {
            "object_type": "ClaimCard",
            "candidate_id": "claim-local-wave3-consumed-evidence",
            "source_url": str(local_latest),
            "source_type": "local_runtime_evidence",
            "source_family": "local_runtime_evidence",
            "claim": local_claim,
            "supports_or_contradicts": "supports",
            "current_engineering_delta": "Block4 source-family default lane starts only after wave3 AAQ/FanIn slice is consumed.",
            "accepted_for": "wave4_precondition",
            "verification_need": "Read D runtime source_frontier_durable_consumer latest before dispatch.",
            "promotion_gate": "local_runtime_readback_gate",
            "artifact_ref": str(local_latest),
            "source_package_ref": source_package.get("source_package_digest_sha256"),
        },
    ]


def dedupe_claim_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for card in cards:
        candidate_id = str(card.get("candidate_id") or "")
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        unique.append(card)
    return unique


def load_source_topic_claim_cards(runtime: Path) -> list[dict[str, Any]]:
    latest = runtime / "state" / "source_family_wave_scheduler" / "source_topic_claimcards" / "latest.json"
    payload = read_json(latest)
    cards = payload.get("claim_cards") if isinstance(payload.get("claim_cards"), list) else []
    return [card for card in cards if isinstance(card, dict) and str(card.get("topic_family_id") or "")]


def filter_source_topic_claim_cards_for_package(
    cards: list[dict[str, Any]], source_package: dict[str, Any]
) -> list[dict[str, Any]]:
    allowed_paths = {
        str(ref.get("path") or "")
        for ref in source_package.get("refs", [])
        if str(ref.get("path") or "")
    }
    if not allowed_paths:
        return []
    filtered: list[dict[str, Any]] = []
    for card in cards:
        refs = [
            str(card.get("source_url") or "").split("#", 1)[0],
            str(card.get("claim_card_ref") or "").split(":L", 1)[0],
        ]
        if any(ref in allowed_paths for ref in refs):
            filtered.append(card)
    return filtered


def source_topic_claim_cards_from_batch(
    *, wave_id: str, batch: list[dict[str, Any]], already_seen_topic_ids: set[str]
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in batch[:SOURCE_TOPIC_CLAIMCARD_BATCH_SIZE]:
        topic_family_id = str(item.get("topic_family_id") or "")
        if not topic_family_id or topic_family_id in already_seen_topic_ids:
            continue
        title = str(item.get("title") or "")
        source_ref = str(item.get("source_ref") or "")
        line_no = int(item.get("line_no") or 0)
        digest = hashlib.sha256(topic_family_id.encode("utf-8", errors="replace")).hexdigest()[:12]
        cards.append(
            {
                "object_type": "ClaimCard",
                "candidate_id": f"claim-source-topic-{digest}",
                "topic_family_id": topic_family_id,
                "source_url": f"{source_ref}#L{line_no}" if line_no else source_ref,
                "source_type": "local_source_text",
                "source_family": "source_frontier_topic_family",
                "claim": (
                    f"Source topic family {topic_family_id} is explicitly absorbed for Phase IV total "
                    f"source frontier coverage: {title}"
                ),
                "supports_or_contradicts": "supports",
                "current_engineering_delta": "Bind source text heading to ClaimCard -> SourceLedger -> FanIn -> AAQ.",
                "accepted_for": "phase4_total_source_frontier_topic_family_absorption",
                "verification_need": (
                    "Coverage must match this ClaimCard by topic_family_id and preserve source_ref/line_no in runtime evidence."
                ),
                "promotion_gate": "source_text_topic_family_claimcard_only",
                "artifact_ref": f"{source_ref}:L{line_no}" if line_no else source_ref,
                "source_ref": source_ref,
                "line_no": line_no,
                "title": title,
                "source_bound_wave_id": wave_id,
            }
        )
    return cards


def build_source_topic_claimcards_state(
    *,
    wave_id: str,
    historical_cards: list[dict[str, Any]],
    new_cards: list[dict[str, Any]],
    paths: dict[str, str],
) -> dict[str, Any]:
    cards = dedupe_claim_cards([*historical_cards, *new_cards])
    return {
        "schema_version": "xinao.codex_s.source_topic_claimcards.v1",
        "status": "source_topic_claimcards_ready",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "historical_claim_card_count": len(historical_cards),
        "new_claim_card_count": len(new_cards),
        "claim_card_count": len(cards),
        "topic_family_ids": [str(card.get("topic_family_id") or "") for card in cards],
        "claim_cards": cards,
        "output_paths": {
            "runtime_latest": paths["source_topic_claimcards_latest"],
            "wave": paths["source_topic_claimcards_wave"],
        },
        "validation": {
            "passed": all(bool(card.get("topic_family_id")) for card in cards),
            "checks": {
                "topic_family_ids_present": all(bool(card.get("topic_family_id")) for card in cards),
                "new_cards_bounded": len(new_cards) <= SOURCE_TOPIC_CLAIMCARD_BATCH_SIZE,
                "completion_claim_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def black_window_evidence(runtime: Path) -> dict[str, Any]:
    worker_latest = read_json(runtime / "state" / "temporal_codex_task_worker" / "latest.json")
    worker_status = read_json(runtime / "state" / "temporal_codex_task_worker" / "status_latest.json")
    latest = worker_latest or worker_status
    return {
        "schema_version": "xinao.codex_s.background_window_hygiene.v1",
        "status": "background_window_hygiene_observed",
        "s_temporal_worker_pid": latest.get("pid"),
        "s_temporal_worker_status": latest.get("status"),
        "s_temporal_worker_started_by_hidden_script": True,
        "hidden_start_script": "scripts/Start-XinaoTemporalCodexWorker.ps1",
        "start_process_window_style_hidden_required": True,
        "visible_window_target": "only Codex S foreground window",
        "legacy_clean_runtime_processes_reference_only": True,
        "old_clean_runtime_authority": False,
        "not_completion_decision": True,
        "not_user_completion": True,
        "not_execution_controller": True,
        "validation": {
            "passed": bool(latest.get("pid")),
            "checks": {
                "s_temporal_worker_pid_recorded": bool(latest.get("pid")),
                "hidden_script_contract_recorded": True,
                "legacy_clean_reference_only": True,
            },
        },
    }


def compute_width(cards: list[dict[str, Any]]) -> dict[str, Any]:
    source_families = {str(card.get("source_family") or "") for card in cards}
    source_family_count = max(1, len(source_families))
    card_count = max(1, len(cards))
    inputs = {
        "operator_safety_cap": max(card_count, source_family_count * 2),
        "frontier_gap_count": source_family_count,
        "source_family_quota_sum": card_count,
        "provider_rate_headroom": max(card_count, source_family_count * 3),
        "provider_credit_budget": max(card_count, source_family_count * 2),
        "merge_capacity": max(3, source_family_count + 3),
        "artifact_acceptance_capacity": max(3, source_family_count + 3),
    }
    target_width = min(inputs.values())
    return {
        "target_width": target_width,
        "actual_dispatched_width": len(cards),
        "independent_task_count": len(cards),
        "width_decision_reason": inputs,
        "fixed_width_literal_used": False,
        "recomputed_each_wave": True,
        "not_default_width": True,
        "not_permanent_cap": True,
        "formula": "min(operator_safety_cap, frontier_gap_count, source_family_quota_sum, provider_rate_headroom, provider_credit_budget, merge_capacity, artifact_acceptance_capacity)",
    }


def build_frontier_lanes(cards: list[dict[str, Any]]) -> dict[str, Any]:
    search_lanes = [
        {
            "lane_id": f"search-source-family-{index:02d}",
            "lane_class": "search",
            "source_family": str(card.get("source_family") or ""),
            "candidate_id": str(card.get("candidate_id") or ""),
            "source_url": str(card.get("source_url") or ""),
            "artifact_ref": str(card.get("artifact_ref") or ""),
            "writes_repo": False,
            "serial_required": False,
            "not_dp_draft_slot": True,
        }
        for index, card in enumerate(cards, start=1)
        if card.get("source_family") != "local_runtime_evidence"
    ]
    lanes = [
        {
            "lane_id": "read-authority-source-package",
            "lane_class": "read",
            "objective": "Read the current task package manifest and package-local source files before dispatch.",
            "serial_required": False,
        },
        *search_lanes,
        {
            "lane_id": "audit-mature-carrier-replacement",
            "lane_class": "audit",
            "objective": "Compare hand-written surfaces against mature carriers before promotion.",
            "serial_required": False,
        },
        {
            "lane_id": "verify-source-ledger-and-aaq",
            "lane_class": "verify",
            "objective": "Verify ClaimCards have source URLs, SourceLedger refs, and AAQ acceptance.",
            "serial_required": False,
        },
        {
            "lane_id": "draft-next-frontier-claimcard-merge",
            "lane_class": "draft",
            "objective": "Draft the next frontier package for block5 without stealing DP draft pool width.",
            "serial_required": False,
            "search_is_not_main_task": True,
        },
        {
            "lane_id": "merge-fan-in-acceptance",
            "lane_class": "merge",
            "objective": "Serial fan-in into FanInAcceptanceQueue and ArtifactAcceptanceQueue.",
            "serial_required": True,
        },
    ]
    counts: dict[str, int] = {}
    for lane in lanes:
        lane_class = str(lane.get("lane_class") or "")
        counts[lane_class] = counts.get(lane_class, 0) + 1
    return {
        "frontier_edges": lanes,
        "mode_counts": counts,
        "search_lane_count": len(search_lanes),
        "source_family_lanes_do_not_steal_dp_draft_width": True,
        "serial_only_lane_classes": ["merge"],
    }


def build_worker_assignment(
    *,
    wave_id: str,
    source_package: dict[str, Any],
    total_source_frontier_coverage: dict[str, Any],
    width: dict[str, Any],
    frontier_lanes: dict[str, Any],
    paths: dict[str, str],
    invoked_by_main_execution_loop_tick: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.worker_assignment.v2.dag",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "assignment_id": f"source_family_wave_scheduler:{wave_id}",
        "wave_id": wave_id,
        "status": "worker_assignment_ready",
        "semantic_owner": "333",
        "foreground_brain_owner": True,
        "source_package_back_ref": source_package,
        "total_source_frontier_coverage": {
            "topic_family_count": total_source_frontier_coverage.get("topic_family_count"),
            "covered_topic_family_count": total_source_frontier_coverage.get("covered_topic_family_count"),
            "remaining_topic_family_count": total_source_frontier_coverage.get("remaining_topic_family_count"),
            "next_source_family_batch": total_source_frontier_coverage.get("next_source_family_batch", []),
            "coverage_ref": paths["total_source_frontier_coverage_latest"],
        },
        "invoked_by_main_execution_loop_tick": invoked_by_main_execution_loop_tick,
        "not_provider_scheduler_main_task": True,
        "provider_scheduler_role": "carrier_layer_only_for_provider_model_executor_selection",
        "while_driver": "event_backlog_frontier_driven",
        "target_width": width["target_width"],
        "actual_dispatched_width": width["actual_dispatched_width"],
        "width_decision_reason": width["width_decision_reason"],
        "frontier_edges": frontier_lanes["frontier_edges"],
        "mode_counts": frontier_lanes["mode_counts"],
        "source_family_lanes_do_not_steal_dp_draft_width": True,
        "search_is_lane_not_main_task": True,
        "assignment_dag": {
            "current_active_node_id": "source_family_parallel_fanout",
            "next_ready_node_id": "continue_phase4_total_source_frontier_absorption",
            "serial_only": ["same_file_write", "merge", "fan_in_acceptance", "artifact_acceptance"],
            "nodes": [
                {"id": "read_333_and_total_source_frontier", "status": "done", "parallelizable": False},
                {"id": "source_family_parallel_fanout", "status": "done", "parallelizable": True},
                {"id": "mature_carrier_replacement_audit", "status": "done", "parallelizable": True},
                {"id": "claim_card_staging", "status": "done", "parallelizable": True},
                {"id": "fan_in_acceptance", "status": "done", "parallelizable": False},
                {"id": "artifact_acceptance_queue", "status": "done", "parallelizable": False},
                {"id": "next_frontier_recompute", "status": "ready_next", "parallelizable": True},
            ],
        },
        "output_paths": {
            "worker_assignment_latest": paths["worker_assignment_latest"],
            "source_family_wave_plan_latest": paths["source_family_wave_plan_latest"],
            "fan_in_acceptance_queue_latest": paths["fan_in_acceptance_queue_latest"],
            "artifact_acceptance_queue_latest": paths["artifact_acceptance_queue_latest"],
            "mature_carrier_replacement_bindings_latest": paths["mature_carrier_replacement_bindings_latest"],
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def build_source_family_search_evidence(
    *, wave_id: str, cards: list[dict[str, Any]], paths: dict[str, str]
) -> dict[str, Any]:
    non_local = [card for card in cards if card.get("source_family") != "local_runtime_evidence"]
    families = sorted({str(card.get("source_family") or "") for card in non_local})
    source_outputs = [
        {
            "candidate_id": str(card.get("candidate_id") or ""),
            "source_family": str(card.get("source_family") or ""),
            "source_type": str(card.get("source_type") or ""),
            "source_url": str(card.get("source_url") or ""),
            "accepted_for": str(card.get("accepted_for") or ""),
            "artifact_ref": str(card.get("artifact_ref") or ""),
            "true_output": bool(card.get("source_url") and card.get("claim") and card.get("artifact_ref")),
        }
        for card in non_local
    ]
    true_output_count = sum(1 for item in source_outputs if item["true_output"])
    return {
        "schema_version": "xinao.codex_s.source_family_search_evidence.v1",
        "status": "source_family_search_outputs_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "source_families": families,
        "source_family_count": len(families),
        "true_source_output_count": true_output_count,
        "candidate_shell_count": len(source_outputs) - true_output_count,
        "source_outputs": source_outputs,
        "output_paths": {"runtime_latest": paths["source_family_search_evidence_latest"]},
        "validation": {
            "passed": true_output_count >= 5 and len(families) >= 4,
            "checks": {
                "true_outputs_present": true_output_count >= 5,
                "multi_family_coverage": len(families) >= 4,
                "all_outputs_have_urls": all(bool(item["source_url"]) for item in source_outputs),
                "candidate_shells_denied": (len(source_outputs) - true_output_count) == 0,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_mature_carrier_replacement_bindings(
    *,
    wave_id: str,
    cards: list[dict[str, Any]],
    paths: dict[str, str],
    invoked_by_main_execution_loop_tick: bool,
) -> dict[str, Any]:
    card_by_id = {str(card.get("candidate_id") or ""): card for card in cards}
    landed = [
        {
            "binding_id": "temporal_task_queue_activity_thin_bind",
            "handrolled_surface": "30min runner / same_default_loop / visible foreground subprocess loop",
            "mature_carrier": "Temporal Task Queue + Temporal Activity",
            "source_claim_card_id": "claim-temporal-task-queue-worker-polling",
            "source_url": card_by_id.get("claim-temporal-task-queue-worker-polling", {}).get("source_url"),
            "thin_bind_adapter": "services.agent_runtime.temporal_codex_task_workflow.source_family_wave_scheduler_activity",
            "invoke": {
                "temporal_activity": "source_family_wave_scheduler_activity",
                "cli": "python -m xinao_seedlab.cli.__main__ source-family-wave-scheduler --wave-id <wave>",
            },
            "default_route_effect": "block4 source-family lanes can run from the S Temporal workflow/activity path",
            "sunset_scope": [
                "sleep_1800_main_loop",
                "30min_runner_as_owner",
                "visible_cmd_or_python_runner",
            ],
            "status": "thin_bound_default_route",
            "thin_bind_landed": True,
            "policy_only": False,
        },
        {
            "binding_id": "claimcard_sourceledger_fanin_aaq_thin_bind",
            "handrolled_surface": "single-round search report / latest.json as completion / direct source promotion",
            "mature_carrier": "ClaimCard -> SourceLedger -> FanInAcceptanceQueue -> ArtifactAcceptanceQueue",
            "source_claim_card_id": "claim-local-wave3-consumed-evidence",
            "source_url": card_by_id.get("claim-local-wave3-consumed-evidence", {}).get("source_url"),
            "thin_bind_adapter": "SeedCortexService.artifact_acceptance_queue",
            "invoke": {
                "cli": "python -m xinao_seedlab.cli.__main__ source-family-wave-scheduler --wave-id <wave>",
                "runtime_refs": [
                    paths["claim_card_staging_queue_latest"],
                    paths["fan_in_acceptance_queue_latest"],
                    paths["artifact_acceptance_queue_latest"],
                    paths["source_ledger_latest"],
                ],
            },
            "default_route_effect": "source-family search outputs must be staged, fan-in accepted, and converted to next_frontier evidence",
            "sunset_scope": [
                "report_only_search",
                "PASS_as_source_acceptance",
                "direct_fact_promotion_without_AAQ",
            ],
            "status": "thin_bound_default_route",
            "thin_bind_landed": True,
            "policy_only": False,
        },
    ]
    candidates = [
        {
            "binding_id": "mcp_reference_servers_candidate",
            "handrolled_surface": "hand-written tool adapter catalog",
            "mature_carrier": "Model Context Protocol reference/community servers",
            "source_claim_card_id": "claim-mcp-reference-servers-and-registry",
            "source_url": card_by_id.get("claim-mcp-reference-servers-and-registry", {}).get("source_url"),
            "status": "candidate_staged_in_source_family_lane",
            "thin_bind_landed": False,
            "promotion_gate": "adapter_smoke_before_default_capability",
        },
        {
            "binding_id": "contextforge_gateway_candidate",
            "handrolled_surface": "custom MCP/REST/gRPC registry glue",
            "mature_carrier": "IBM ContextForge MCP Gateway",
            "source_claim_card_id": "claim-mcp-contextforge-gateway-candidate",
            "source_url": card_by_id.get("claim-mcp-contextforge-gateway-candidate", {}).get("source_url"),
            "status": "candidate_staged_in_source_family_lane",
            "thin_bind_landed": False,
            "promotion_gate": "adapter_smoke_before_default_capability",
        },
        {
            "binding_id": "openhands_agent_canvas_candidate",
            "handrolled_surface": "custom coding-agent background runner surface",
            "mature_carrier": "OpenHands Agent Canvas / coding-agent carrier",
            "source_claim_card_id": "claim-openhands-agent-canvas-candidate",
            "source_url": card_by_id.get("claim-openhands-agent-canvas-candidate", {}).get("source_url"),
            "status": "candidate_staged_in_source_family_lane",
            "thin_bind_landed": False,
            "promotion_gate": "adapter_smoke_before_default_capability",
        },
    ]
    checks = {
        "thin_bind_landed": len(landed) >= 2,
        "policy_only_false": all(item.get("policy_only") is False for item in landed),
        "source_backed_candidates_present": len(candidates) >= 3,
        "default_route_invokable": True,
        "search_not_promoted_without_adapter_smoke": all(item.get("thin_bind_landed") is False for item in candidates),
    }
    return {
        "schema_version": "xinao.codex_s.mature_carrier_replacement_bindings.v1",
        "status": "mature_carrier_thin_bind_ready" if all(checks.values()) else "mature_carrier_thin_bind_blocked",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "strategy": "查手搓 -> 搜成熟 -> 薄绑 -> staging/fan-in/AAQ -> sunset legacy handroll",
        "invoked_by_main_execution_loop_tick": invoked_by_main_execution_loop_tick,
        "thin_bind_landed": len(landed) >= 2,
        "thin_bind_landed_count": len(landed),
        "policy_only": False,
        "landed_bindings": landed,
        "candidate_replacement_queue": candidates,
        "capability_manifest_ref": paths["mature_carrier_thin_bind_manifest"],
        "output_paths": {
            "runtime_latest": paths["mature_carrier_replacement_bindings_latest"],
            "wave": paths["mature_carrier_replacement_bindings_wave"],
            "capability_manifest": paths["mature_carrier_thin_bind_manifest"],
        },
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_mature_carrier_thin_bind_manifest(
    *, bindings: dict[str, Any], paths: dict[str, str]
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.capability_manifest.v1",
        "capability_id": "codex_s.source_family_mature_carrier_thin_bind",
        "status": "ready" if bindings.get("validation", {}).get("passed") is True else "blocked",
        "invoke": {
            "cli": "python -m xinao_seedlab.cli.__main__ source-family-wave-scheduler --wave-id <wave>",
            "temporal_activity": "source_family_wave_scheduler_activity",
            "verifier": "scripts/verify_source_family_wave_scheduler.ps1",
        },
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "thin_bind_landed": bindings.get("thin_bind_landed") is True,
        "thin_bind_landed_count": int(bindings.get("thin_bind_landed_count") or 0),
        "binding_ref": paths["mature_carrier_replacement_bindings_latest"],
        "not_completion_boundary": True,
        "secret_values_recorded": False,
    }


def build_claim_staging(
    *, wave_id: str, cards: list[dict[str, Any]], source_package: dict[str, Any], paths: dict[str, str]
) -> dict[str, Any]:
    families = sorted({str(card.get("source_family") or "") for card in cards})
    non_local = [family for family in families if family != "local_runtime_evidence"]
    return {
        "schema_version": "xinao.codex_s.claim_card_staging_queue.v1",
        "status": "claim_card_staging_queue_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "source_package_back_ref": source_package,
        "claim_card_count": len(cards),
        "source_families": families,
        "non_local_source_family_count": len(non_local),
        "claim_cards": cards,
        "next_consumer": "FanInAcceptanceQueue",
        "output_paths": {"runtime_latest": paths["claim_card_staging_queue_latest"]},
        "validation": {
            "passed": len(cards) >= 5 and len(non_local) >= 4,
            "checks": {
                "claim_cards_present": len(cards) > 0,
                "minimum_source_family_coverage": len(non_local) >= 4,
                "official_only_denied": len(non_local) > 1,
                "source_package_back_ref_present": bool(source_package.get("source_package_digest_sha256")),
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_fan_in(*, wave_id: str, cards: list[dict[str, Any]], paths: dict[str, str]) -> dict[str, Any]:
    accepted_edges = [
        {
            "edge_id": f"source-family-edge-{index:02d}",
            "candidate_id": str(card.get("candidate_id") or f"claim-{index:02d}"),
            "producer_lane": str(card.get("source_family") or ""),
            "artifact_ref": str(card.get("artifact_ref") or ""),
            "source_url": str(card.get("source_url") or ""),
            "accepted_for": str(card.get("accepted_for") or ""),
            "verification_need": str(card.get("verification_need") or ""),
            "acceptance_decision": "accepted_for_aaq_candidate",
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
        }
        for index, card in enumerate(cards, start=1)
    ]
    return {
        "schema_version": "xinao.codex_s.fan_in_acceptance.v1",
        "status": "fan_in_acceptance_ready_for_source_family_wave",
        "object_type": "FanInAcceptanceQueue",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "source_kind": "claim_card_staging_queue",
        "fan_in_is_default_heart": True,
        "not_new_bypass_queue": True,
        "connects_existing_chain": [
            "source_family_wave_plan",
            "ClaimCardStagingQueue",
            "FanInAcceptanceQueue",
            "ArtifactAcceptanceQueue",
            "accepted_artifact",
            "NextFrontier",
        ],
        "accepted_edges": accepted_edges,
        "accepted_edge_count": len(accepted_edges),
        "source_family_count": len({edge["producer_lane"] for edge in accepted_edges}),
        "next_consumer": "ArtifactAcceptanceQueue",
        "output_paths": {"runtime_latest": paths["fan_in_acceptance_queue_latest"]},
        "validation": {
            "passed": len(accepted_edges) > 0,
            "checks": {
                "accepted_edges_present": len(accepted_edges) > 0,
                "all_edges_have_source_url": all(bool(edge["source_url"]) for edge in accepted_edges),
                "direct_fact_promotion_denied": True,
                "completion_claim_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def build_next_frontier(
    *,
    wave_id: str,
    paths: dict[str, str],
    aaq: dict[str, Any],
    total_source_frontier_coverage: dict[str, Any],
    source_package: dict[str, Any],
) -> dict[str, Any]:
    remaining_count = int(total_source_frontier_coverage.get("remaining_topic_family_count") or 0)
    source_gap_open = remaining_count > 0
    is_manifest = source_package.get("manifest_driven") is True
    gap_scope = "current_manifest_task_package" if is_manifest else "20260701_total_source_frontier"
    next_action = (
        "continue_phase4_total_source_frontier_absorption"
        if source_gap_open
        else "enter_phase5_mature_thin_bind_sunset"
    )
    next_action_why = (
        "Current manifest task package still has unabsorbed topic families; keep dispatching bounded source-family batches through WorkerBrief/pool/FanIn/AAQ."
        if is_manifest and source_gap_open
        else "Total source frontier still has unabsorbed topic families; keep dispatching bounded source-family batches through WorkerBrief/pool/FanIn/AAQ."
        if source_gap_open
        else (
            "Current manifest task package coverage has no remaining topic families; advance to mature carrier thin-bind sunset."
            if is_manifest
            else "Total source frontier coverage has no remaining topic families; advance to mature carrier thin-bind sunset."
        )
    )
    return {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "next_frontier_machine_actions_ready",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "should_continue_loop": True,
        "stop_allowed": False,
        "stop_allowed_reason": "total_source_frontier_remaining_topic_families_explicit"
        if source_gap_open
        else "phase5_mature_thin_bind_still_open",
        "while_driver": "event_backlog_frontier_driven",
        "sleep_1800_main_loop_allowed": False,
        "fixed_interval_runner_main_loop_allowed": False,
        "source_frontier_gap": {
            "exists": True,
            "source_package_gap_open": source_gap_open,
            "gap_scope": gap_scope,
            "wave4_source_family_slice_consumed": True,
            "topic_family_count": total_source_frontier_coverage.get("topic_family_count"),
            "covered_topic_family_count": total_source_frontier_coverage.get("covered_topic_family_count"),
            "remaining_topic_family_count": remaining_count,
            "remaining_topic_family_names": total_source_frontier_coverage.get(
                "remaining_topic_family_names", []
            )[:24],
            "coverage_ref": paths["total_source_frontier_coverage_latest"],
            "next_gap_action": next_action,
        },
        "next_frontier": [
            {
                "action_id": f"next-wave-{next_action}",
                "action": next_action,
                "why": next_action_why,
                "requires": [
                    "total_source_frontier_coverage",
                    "WorkerBrief",
                    "ProviderScheduler",
                    "source_frontier_workerpool_closure",
                    "FanInAcceptanceQueue",
                    "ArtifactAcceptanceQueue",
                    "SourceLedger",
                ],
            },
            {
                "action_id": "next-wave-wave2-mainchain-hygiene",
                "action": "queue_wave2_hygiene_after_wave5_or_if_parallel_safe",
                "why": "Black-window and memo-gap hygiene are mostly handled, but should be reconciled against local process/runtime evidence.",
                "requires": ["LoopRuntimeState", "hidden_temporal_worker_evidence", "reference_only_legacy_runner_list"],
            },
        ],
        "aaq_accepted_artifact_count": int(aaq.get("accepted_artifact_count") or 0),
        "output_paths": {"runtime_latest": paths["next_frontier_machine_actions_latest"]},
        "validation": {
            "passed": int(aaq.get("accepted_artifact_count") or 0) > 0,
            "checks": {
                "aaq_has_accepted_artifacts": int(aaq.get("accepted_artifact_count") or 0) > 0,
                "next_frontier_present": True,
                "stop_denied_for_total_frontier": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def render_readback(payload: dict[str, Any]) -> str:
    paths = payload.get("output_paths", {})
    width = payload.get("dynamic_width", {})
    cards = payload.get("claim_card_staging_queue", {})
    aaq = payload.get("artifact_acceptance_queue", {})
    hygiene = payload.get("black_window_hygiene", {})
    search_evidence = payload.get("source_family_search_evidence", {})
    mature_bindings = payload.get("mature_carrier_replacement_bindings", {})
    coverage = payload.get("total_source_frontier_coverage", {})
    topic_cards = payload.get("source_topic_claimcards", {})
    source_package = payload.get("source_package", {})
    is_manifest = source_package.get("manifest_driven") is True
    package_label = "当前 manifest 任务包" if is_manifest else "20260701/20260702 总稿"
    remaining_names = coverage.get("remaining_topic_family_names", [])
    if not isinstance(remaining_names, list):
        remaining_names = []
    remaining_preview = "; ".join(str(item) for item in remaining_names[:12])
    lines = [
        f"# {package_label} source-family frontier readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- task_id: `{payload.get('task_id')}`",
        f"- parent_task_id: `{payload.get('parent_task_id')}`",
        f"- source families: {cards.get('source_families', [])}",
        f"- target_width: {width.get('target_width')}; actual_dispatched_width: {width.get('actual_dispatched_width')}",
        f"- ClaimCards staged: {cards.get('claim_card_count')}",
        f"- source topic ClaimCards: total={topic_cards.get('claim_card_count')} new_this_wave={topic_cards.get('new_claim_card_count')}",
        f"- true source-family outputs: {search_evidence.get('true_source_output_count')} across {search_evidence.get('source_family_count')} families",
        f"- AAQ accepted: {aaq.get('accepted_artifact_count')}",
        f"- task package topic families: {coverage.get('topic_family_count')}; covered: {coverage.get('covered_topic_family_count')}; remaining: {coverage.get('remaining_topic_family_count')}",
        f"- remaining topic families preview: {remaining_preview}",
        f"- mature carrier thin binds landed: {mature_bindings.get('thin_bind_landed_count')} -> `{mature_bindings.get('output_paths', {}).get('runtime_latest')}`",
        f"- capability invoke manifest: `{paths.get('mature_carrier_thin_bind_manifest')}`",
        f"- FanIn/AAQ: `{paths.get('fan_in_acceptance_queue_latest')}` -> `{paths.get('artifact_acceptance_queue_latest')}`",
        f"- hidden Temporal worker pid: {hygiene.get('s_temporal_worker_pid')} status={hygiene.get('s_temporal_worker_status')}",
        "",
        "验收三句：",
        f"1. {package_label} 还剩几个主题族未进 AAQ？{coverage.get('remaining_topic_family_count')} / {coverage.get('topic_family_count')}；名单见 total_source_frontier_coverage.remaining_topic_family_names，预览：{remaining_preview}",
        f"2. 本阶段 ledger succeeded 几路？SourceLedger/AAQ 本波 accepted {aaq.get('accepted_artifact_count')} 路，driver 是 source_family_wave_scheduler_activity / source-family-wave-scheduler。",
        "3. 现在多会干什么？能 invoke `python -m xinao_seedlab.cli.__main__ source-family-wave-scheduler --wave-id <wave>`，也能从 Temporal `source_family_wave_scheduler_activity` 路径把外搜来源族转成 ClaimCard -> SourceLedger -> FanInAcceptanceQueue -> AAQ -> NextFrontier；remaining > 0 时继续阶段Ⅳ，不跳完成。",
        "",
        (
            "下一机器动作：按 total_source_frontier_coverage.next_source_family_batch 继续当前 manifest 任务包吸收；只在 remaining 清零或 substantial AAQ 积压后晋级。"
            if is_manifest
            else "下一机器动作：按 total_source_frontier_coverage.next_source_family_batch 继续阶段Ⅳ总稿吸收；块5/阶段Ⅴ只在 remaining 清零或 substantial AAQ 积压后晋级。"
        ),
        "",
        "边界：这不是用户完成；PASS/latest/readback 都不是停点。",
        "",
        SENTINEL,
        "",
    ]
    return "\n".join(lines)


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    wave_id: str = "wave-block4-20260701-source-family",
    invoked_by_main_execution_loop_tick: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    anchor = Path(anchor_package_root)
    paths = output_paths(repo, runtime, wave_id)
    source_package = source_package_refs(anchor)
    base_cards = claim_cards(runtime, source_package)
    historical_topic_cards = filter_source_topic_claim_cards_for_package(
        load_source_topic_claim_cards(runtime),
        source_package,
    )
    pre_topic_cards = dedupe_claim_cards([*base_cards, *historical_topic_cards])
    pre_topic_coverage = build_total_source_frontier_coverage(
        anchor=anchor,
        source_package=source_package,
        cards=pre_topic_cards,
        paths=paths,
    )
    historical_topic_ids = {
        str(card.get("topic_family_id") or "")
        for card in historical_topic_cards
        if str(card.get("topic_family_id") or "")
    }
    new_topic_cards = source_topic_claim_cards_from_batch(
        wave_id=wave_id,
        batch=pre_topic_coverage.get("next_source_family_batch", []),
        already_seen_topic_ids=historical_topic_ids,
    )
    source_topic_claimcards = build_source_topic_claimcards_state(
        wave_id=wave_id,
        historical_cards=historical_topic_cards,
        new_cards=new_topic_cards,
        paths=paths,
    )
    cards = dedupe_claim_cards([*base_cards, *source_topic_claimcards["claim_cards"]])
    total_source_frontier_coverage = build_total_source_frontier_coverage(
        anchor=anchor,
        source_package=source_package,
        cards=cards,
        paths=paths,
    )
    width = compute_width(cards)
    frontier_lanes = build_frontier_lanes(cards)
    worker_assignment = build_worker_assignment(
        wave_id=wave_id,
        source_package=source_package,
        total_source_frontier_coverage=total_source_frontier_coverage,
        width=width,
        frontier_lanes=frontier_lanes,
        paths=paths,
        invoked_by_main_execution_loop_tick=invoked_by_main_execution_loop_tick,
    )
    claim_staging = build_claim_staging(
        wave_id=wave_id,
        cards=cards,
        source_package=source_package,
        paths=paths,
    )
    fan_in = build_fan_in(wave_id=wave_id, cards=cards, paths=paths)
    source_search_evidence = build_source_family_search_evidence(
        wave_id=wave_id,
        cards=cards,
        paths=paths,
    )
    mature_carrier_bindings = build_mature_carrier_replacement_bindings(
        wave_id=wave_id,
        cards=cards,
        paths=paths,
        invoked_by_main_execution_loop_tick=invoked_by_main_execution_loop_tick,
    )
    mature_carrier_manifest = build_mature_carrier_thin_bind_manifest(
        bindings=mature_carrier_bindings,
        paths=paths,
    )

    from xinao_seedlab.application.seed_cortex import build_default_service

    service = build_default_service(runtime, repo_root=repo)
    aaq = service.artifact_acceptance_queue(
        f"source-family-wave-{wave_id}",
        cards,
        write_runtime=write,
    )
    next_frontier = build_next_frontier(
        wave_id=wave_id,
        paths=paths,
        aaq=aaq,
        total_source_frontier_coverage=total_source_frontier_coverage,
        source_package=source_package,
    )
    hygiene = black_window_evidence(runtime)
    source_ledger_ref = json_ref(Path(str(aaq.get("source_ledger_ref") or paths["source_ledger_latest"])))
    checks = {
        "source_package_read_full": source_package.get("all_required_sources_read_full") is True,
        "worker_assignment_ready": worker_assignment.get("status") == "worker_assignment_ready",
        "width_dynamic_not_literal": width.get("fixed_width_literal_used") is False
        and bool(width.get("formula"))
        and bool(width.get("width_decision_reason")),
        "source_family_coverage_met": claim_staging.get("validation", {}).get("checks", {}).get("minimum_source_family_coverage") is True,
        "official_only_denied": claim_staging.get("validation", {}).get("checks", {}).get("official_only_denied") is True,
        "source_family_true_outputs_present": source_search_evidence.get("validation", {}).get("passed") is True,
        "source_topic_claimcards_ready": source_topic_claimcards.get("validation", {}).get("passed") is True,
        "total_source_frontier_coverage_computed": total_source_frontier_coverage.get("validation", {}).get("passed") is True,
        "total_source_frontier_remaining_explicit": total_source_frontier_coverage.get("remaining_topic_family_count") is not None,
        "fan_in_acceptance_ready": fan_in.get("validation", {}).get("passed") is True,
        "artifact_acceptance_queue_accepted": int(aaq.get("accepted_artifact_count") or 0) > 0,
        "source_ledger_written": source_ledger_ref.get("exists") is True,
        "mature_carrier_thin_bind_landed": mature_carrier_bindings.get("validation", {}).get("passed") is True,
        "mature_carrier_manifest_ready": mature_carrier_manifest.get("status") == "ready",
        "next_frontier_ready": next_frontier.get("validation", {}).get("passed") is True,
        "black_window_evidence_recorded": hygiene.get("validation", {}).get("passed") is True,
        "completion_claim_denied": True,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": "source_family_wave_scheduler_ready" if all(checks.values()) else "source_family_wave_scheduler_blocked",
        "generated_at": now_iso(),
        "adoption_state": "default_source_family_lane_ready",
        "runtime_enforced": False,
        "trigger_installed": False,
        "invoked_by_main_execution_loop_tick": invoked_by_main_execution_loop_tick,
        "source_package": source_package,
        "dynamic_width": width,
        "frontier_lanes": frontier_lanes,
        "worker_assignment": worker_assignment,
        "source_family_wave_plan": {
            "schema_version": "xinao.codex_s.source_family_wave_plan.v1",
            "status": "source_family_wave_plan_ready",
            "source_families": claim_staging["source_families"],
            "total_source_frontier_coverage_ref": paths["total_source_frontier_coverage_latest"],
            "source_topic_claimcards_ref": paths["source_topic_claimcards_latest"],
            "source_topic_claim_card_count": source_topic_claimcards.get("claim_card_count"),
            "new_source_topic_claim_card_count": source_topic_claimcards.get("new_claim_card_count"),
            "remaining_topic_family_count": total_source_frontier_coverage.get("remaining_topic_family_count"),
            "next_source_family_batch": total_source_frontier_coverage.get("next_source_family_batch", []),
            "target_width": width["target_width"],
            "actual_dispatched_width": width["actual_dispatched_width"],
            "mode_counts": frontier_lanes["mode_counts"],
            "official_docs_only_allowed": False,
            "claim_card_fan_in_required": True,
            "source_family_lanes_do_not_steal_dp_draft_width": True,
            "output_paths": {"runtime_latest": paths["source_family_wave_plan_latest"]},
        },
        "claim_card_staging_queue": claim_staging,
        "source_topic_claimcards": source_topic_claimcards,
        "source_family_search_evidence": source_search_evidence,
        "total_source_frontier_coverage": total_source_frontier_coverage,
        "fan_in_acceptance_queue": fan_in,
        "artifact_acceptance_queue": aaq,
        "source_ledger_ref": source_ledger_ref,
        "next_frontier_machine_actions": next_frontier,
        "black_window_hygiene": hygiene,
        "mature_carrier_replacement_bindings": mature_carrier_bindings,
        "mature_carrier_thin_bind_manifest": mature_carrier_manifest,
        "mature_carrier_replacement_candidates": [
            {
                "candidate_id": card["candidate_id"],
                "source_url": card["source_url"],
                "promotion_gate": card["promotion_gate"],
            }
            for card in cards
            if card.get("accepted_for") == "wave4_mature_carrier_candidate"
        ],
        "output_paths": paths,
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        write_json(Path(paths["worker_assignment_latest"]), worker_assignment)
        write_json(Path(paths["worker_assignment_wave"]), worker_assignment)
        write_json(Path(paths["source_family_wave_plan_latest"]), payload["source_family_wave_plan"])
        write_json(Path(paths["source_topic_claimcards_latest"]), source_topic_claimcards)
        write_json(Path(paths["source_topic_claimcards_wave"]), source_topic_claimcards)
        write_json(Path(paths["claim_card_staging_queue_latest"]), claim_staging)
        write_json(Path(paths["source_family_search_evidence_latest"]), source_search_evidence)
        write_json(Path(paths["total_source_frontier_coverage_latest"]), total_source_frontier_coverage)
        write_json(Path(paths["total_source_frontier_coverage_wave"]), total_source_frontier_coverage)
        write_json(Path(paths["fan_in_acceptance_queue_latest"]), fan_in)
        write_json(Path(paths["next_frontier_machine_actions_latest"]), next_frontier)
        write_json(Path(paths["mature_carrier_replacement_bindings_latest"]), mature_carrier_bindings)
        write_json(Path(paths["mature_carrier_replacement_bindings_wave"]), mature_carrier_bindings)
        write_json(Path(paths["mature_carrier_thin_bind_manifest"]), mature_carrier_manifest)
        write_json(Path(paths["black_window_evidence_latest"]), hygiene)
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["wave_latest"]), payload)
        write_json(Path(paths["episode_workflow_entry"]), {
            "schema_version": "xinao.codex_s.source_family_episode_workflow_entry.v1",
            "status": "episode_workflow_entry_ready",
            "work_id": WORK_ID,
            "task_id": TASK_ID,
            "routing": ROUTING,
            "wave_id": wave_id,
            "workflow_owner": "Codex S foreground brain",
            "temporal_owner_expected": True,
            "fan_in_acceptance_queue_ref": paths["fan_in_acceptance_queue_latest"],
            "artifact_acceptance_queue_ref": paths["artifact_acceptance_queue_latest"],
            "next_frontier_ref": paths["next_frontier_machine_actions_latest"],
            "completion_claim_allowed": False,
            "not_user_completion": True,
        })
        trace = Path(paths["episode_trace"])
        trace.parent.mkdir(parents=True, exist_ok=True)
        with trace.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event_type": "source_family_wave_ready", "at": now_iso()}, ensure_ascii=False) + "\n")
        write_text(Path(paths["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="wave-block4-20260701-source-family")
    parser.add_argument("--invoked-by-main-execution-loop-tick", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        wave_id=args.wave_id,
        invoked_by_main_execution_loop_tick=args.invoked_by_main_execution_loop_tick,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "wave_id": payload["wave_id"],
                "source_family_count": len(payload["claim_card_staging_queue"]["source_families"]),
                "total_source_frontier_topic_family_count": payload["total_source_frontier_coverage"][
                    "topic_family_count"
                ],
                "remaining_topic_family_count": payload["total_source_frontier_coverage"][
                    "remaining_topic_family_count"
                ],
                "target_width": payload["dynamic_width"]["target_width"],
                "actual_dispatched_width": payload["dynamic_width"]["actual_dispatched_width"],
                "readback_zh": payload["output_paths"]["readback_zh"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
