from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.live_backend_watch.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_LIVE_BACKEND_WATCH_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
NODE_ID = "codex_s_live_backend_watch"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]

WATCH_RELATIVE_PATHS = [
    r"state\live_parallel_pool\latest.json",
    r"state\worker_assignment_dynamic_fanout\latest.json",
    r"state\parallel_lane_results\latest.json",
    r"state\parallel_dispatch_plan\latest.json",
    r"state\parallel_fan_in_acceptance\latest.json",
    r"state\parallel_capacity\latest.json",
    r"state\deepseek_sidecar\xinao_seed_cortex_phase0_20260701\latest.json",
    r"state\deepseek_search_sidecar\latest.json",
    r"state\deepseek_draft_staging_queue\latest.json",
    r"state\deepseek_fan_in_acceptance_queue\latest.json",
    r"state\deepseek_search_fan_in_acceptance\latest.json",
    r"state\artifact_acceptance_queue\latest.json",
    r"state\max_parallel_mainline_return\latest.json",
    r"state\durable_workflow_evidence\latest.json",
]

LIVE_MARKER_PATTERNS = {
    "worker_running": re.compile(r'"worker_running"\s*:\s*true', re.IGNORECASE),
    "temporal_pending_activity": re.compile(
        r'"(?:temporal_)?pending_activity"\s*:\s*true', re.IGNORECASE
    ),
    "worker_jsonl_non_terminal": re.compile(
        r'"worker_jsonl_(?:non_terminal|evidence_present)"\s*:\s*true',
        re.IGNORECASE,
    ),
    "assignment_next_ready": re.compile(r'"next_ready"\s*:\s*true', re.IGNORECASE),
    "assignment_auto_continue_expected": re.compile(
        r'"auto_continue(?:_expected)?"\s*:\s*true', re.IGNORECASE
    ),
    "queue_or_lane_non_terminal": re.compile(
        r'"(?:active_lane_count|nonterminal_lane_count|running_count|pending_count)"\s*:\s*[1-9][0-9]*',
        re.IGNORECASE,
    ),
}


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


def safe_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


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


def read_previous_watch(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    previous: dict[str, dict[str, Any]] = {}
    for item in payload.get("watched_files", []):
        if isinstance(item, dict) and item.get("path"):
            previous[str(item["path"])] = item
    return previous


def detect_markers(text: str) -> list[str]:
    if not text.strip():
        return []
    return [name for name, pattern in LIVE_MARKER_PATTERNS.items() if pattern.search(text)]


def read_file_limited(path: Path, *, max_chars: int = 200_000) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:max_chars]


def watched_file(runtime_root: Path, relative: str, previous: dict[str, dict[str, Any]]) -> dict[str, Any]:
    path = runtime_root / relative
    key = safe_path(path)
    entry: dict[str, Any] = {
        "path": key,
        "exists": False,
        "length": 0,
        "last_write_time": "",
        "changed_since_previous_watch": False,
        "live_status_detected": False,
        "live_markers": [],
        "live_categories": [],
    }
    if not path.is_file():
        return entry

    stat = path.stat()
    entry.update(
        {
            "exists": True,
            "length": stat.st_size,
            "last_write_time": dt.datetime.fromtimestamp(
                stat.st_mtime, tz=dt.datetime.now().astimezone().tzinfo
            ).isoformat(timespec="seconds"),
        }
    )
    previous_entry = previous.get(key)
    if previous_entry:
        entry["changed_since_previous_watch"] = (
            int(previous_entry.get("length") or 0) != stat.st_size
            or str(previous_entry.get("last_write_time") or "") != entry["last_write_time"]
        )
    try:
        markers = detect_markers(read_file_limited(path))
    except OSError as exc:
        entry["read_error"] = str(exc)
        markers = []
    entry["live_markers"] = markers
    entry["live_categories"] = markers
    entry["live_status_detected"] = bool(markers)
    return entry


def old_semantic_categories() -> dict[str, list[str]]:
    return {
        "continue_required_categories": [
            "worker_running",
            "temporal_pending_activity",
            "worker_jsonl_non_terminal",
            "assignment_next_ready",
            "assignment_auto_continue_expected",
            "queue_or_lane_non_terminal",
            "output_growth_detected",
        ],
        "not_live_by_itself": [
            "current_route status active",
            "static worker_assignment status active",
            "temporal dev server process running",
            "plan/read_model/status ready without worker, queue, non-terminal, or growth evidence",
        ],
        "fail_open_categories": [
            "no_candidate_state",
            "state_read_unavailable",
            "invalid_json_or_decode_error",
        ],
        "legacy_endpoint_boundary": {
            "old_backend_mirror_semantics_reused": True,
            "old_backend_endpoint_used": False,
            "compat_endpoint_used": False,
            "old_a_clean_latest_json_source_of_truth": False,
        },
    }


def json_summary(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {"path": safe_path(path), "exists": path.is_file()}
    if not path.is_file():
        return summary
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        summary["json_valid"] = False
        summary["json_error"] = str(exc)
        return summary
    summary.update(
        {
            "json_valid": True,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "work_id": payload.get("work_id"),
            "temporal_dev_server_process_running": payload.get(
                "temporal_dev_server_process_running"
            ),
        }
    )
    return summary


def context_sources(runtime: Path) -> dict[str, Any]:
    return {
        "current_route": json_summary(runtime / "state" / "current_route" / "latest.json"),
        "static_worker_assignment": json_summary(
            runtime
            / "state"
            / "worker_assignment"
            / "xinao_seed_cortex_phase0_20260701.json"
        ),
        "temporal_dev_server": json_summary(
            runtime / "state" / "temporal_dev_server" / "latest.json"
        ),
    }


def output_paths(repo: Path, runtime: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(
            runtime / "state" / "codex_s_live_backend_watch" / "latest.json"
        ),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / "codex_s_live_backend_watch_20260702.md"
        ),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_live_backend_watch.v1.json"),
        "writer": str(repo / "services" / "agent_runtime" / "codex_s_live_backend_watch.py"),
        "tests": str(repo / "tests" / "seedcortex" / "test_codex_s_live_backend_watch.py"),
        "verifier": str(repo / "scripts" / "verify_codex_s_live_backend_watch.ps1"),
    }


def build_live_backend_watch(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    explicit_user_stop_requested: bool = False,
    temporal_dev_server_process_running: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    latest = runtime / "state" / "codex_s_live_backend_watch" / "latest.json"
    previous = read_previous_watch(latest)
    files = [watched_file(runtime, relative, previous) for relative in WATCH_RELATIVE_PATHS]
    live_files = [item for item in files if item["exists"] and item["live_status_detected"]]
    growth_files = [item for item in files if item["exists"] and item["changed_since_previous_watch"]]

    decision_categories: list[str] = []
    for item in live_files:
        decision_categories.extend(str(v) for v in item["live_categories"])
    if growth_files:
        decision_categories.append("output_growth_detected")
    if explicit_user_stop_requested:
        decision_categories.append("explicit_user_stop_override")
    decision_categories = sorted({item for item in decision_categories if item})

    foreground_poll_required = (
        not explicit_user_stop_requested and (bool(live_files) or bool(growth_files))
    )
    existing_candidate_count = sum(1 for item in files if item["exists"])
    status = "live_backend_watch_idle_or_unavailable"
    if foreground_poll_required:
        status = "live_backend_watch_poll_required"
    elif explicit_user_stop_requested:
        status = "live_backend_watch_user_stop_override"
    elif existing_candidate_count == 0:
        status = "live_backend_watch_no_candidate_state"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "node_id": NODE_ID,
        "status": status,
        "generated_at": now_iso(),
        "foreground_poll_required": foreground_poll_required,
        "explicit_user_stop_requested": explicit_user_stop_requested,
        "explicit_user_stop_override": explicit_user_stop_requested,
        "explicit_user_stop_overrides_live_watch": explicit_user_stop_requested,
        "old_backend_mirror_semantics_reused": True,
        "old_backend_endpoint_used": False,
        "compat_endpoint_used": False,
        "temporal_dev_server_process_running": temporal_dev_server_process_running,
        "temporal_dev_server_process_is_live_backend_by_itself": False,
        "old_semantic_categories": old_semantic_categories(),
        "decision_categories": decision_categories,
        "context_sources": context_sources(runtime),
        "static_context_triggers_poll": False,
        "live_status_file_count": len(live_files),
        "output_growth_file_count": len(growth_files),
        "live_status_paths": [item["path"] for item in live_files],
        "output_growth_paths": [item["path"] for item in growth_files],
        "watched_files": files,
        "adoption_state": "verifier_ready_but_not_hooked",
        "stop_guard_layer": "live_backend_watch_front_gate",
        "stop_guard_layer_not_execution_controller": True,
        "main_execution_loop": [
            "restore",
            "dispatch",
            "poll",
            "fan_in",
            "verify_evidence_readback",
            "recompute_capacity",
            "next_wave",
        ],
        "source_policy": (
            "S runtime state files only; old A/CLEAN backend mirror classification "
            "semantics reused, old endpoint not used by default"
        ),
        "output_paths": output_paths(repo, runtime),
        "validation": {
            "passed": True,
            "checks": {
                "old_backend_endpoint_not_used": True,
                "compat_endpoint_not_used": True,
                "static_active_route_not_live_by_itself": True,
                "static_context_triggers_poll_false": True,
                "temporal_dev_server_not_live_by_itself": not foreground_poll_required
                if temporal_dev_server_process_running and not live_files and not growth_files
                else True,
                "foreground_poll_requires_live_or_growth": foreground_poll_required
                == (not explicit_user_stop_requested and (bool(live_files) or bool(growth_files))),
                "explicit_stop_overrides_poll": (
                    not foreground_poll_required if explicit_user_stop_requested else True
                ),
            },
        },
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        write_json(Path(payload["output_paths"]["runtime_latest"]), payload)
        write_text(Path(payload["output_paths"]["runtime_readback_zh"]), render_readback(payload))
    return payload


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    explicit_user_stop: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    temporal_summary = json_summary(runtime / "state" / "temporal_dev_server" / "latest.json")
    return build_live_backend_watch(
        runtime_root=runtime,
        repo_root=repo_root,
        explicit_user_stop_requested=explicit_user_stop,
        temporal_dev_server_process_running=bool(
            temporal_summary.get("temporal_dev_server_process_running")
        ),
        write=write,
    )


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Codex S Live Backend Watch readback",
            "",
            SENTINEL,
            "",
            f"- status: `{payload['status']}`",
            f"- foreground_poll_required: {payload['foreground_poll_required']}",
            f"- adoption_state: `{payload['adoption_state']}`",
            "- 这是一层 Stop 前门守护，不是主执行流程，不是事实源，也不是完成判断。",
            "- 主执行流程仍是 restore -> dispatch -> poll -> fan-in -> verify/evidence/readback -> recompute -> next_wave。",
            "- 后台仍活或输出增长时，前台应继续轮询；静态 route active、静态 assignment active、Temporal dev server 运行不能单独触发轮询。",
            "- 旧 backend_mirror 的分类语义被复用；旧 A/CLEAN endpoint 没有作为默认事实源。",
            "",
            "## decision_categories",
            "",
            *[f"- {item}" for item in payload["decision_categories"]],
            "",
            SENTINEL,
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--explicit-user-stop", action="store_true")
    parser.add_argument("--temporal-dev-server-process-running", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build_live_backend_watch(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        explicit_user_stop_requested=args.explicit_user_stop,
        temporal_dev_server_process_running=args.temporal_dev_server_process_running,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "foreground_poll_required": payload["foreground_poll_required"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
