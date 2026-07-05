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


SCHEMA_VERSION = "xinao.codex_s.total_source_episode_entry.v1"
SENTINEL = "SENTINEL:XINAO_TOTAL_SOURCE_EPISODE_ENTRY_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = "total_source_episode_entry_20260705"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_SOURCE_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统\新系统独立并行_自由发散外部研究总稿_20260701.txt")
THEME_FAMILY = "episode_entry"
THEME_TERMS = (
    "POST /episodes",
    "WorkflowPort",
    "ResearchEpisode",
    "episode",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-_.")
    return cleaned[:120] or "wave"


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
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def source_ref(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    text = path.read_text(encoding="utf-8-sig", errors="replace") if exists else ""
    return {
        "path": str(path),
        "exists": exists,
        "read_full": exists,
        "line_count": len(text.splitlines()) if exists else 0,
        "char_count": len(text) if exists else 0,
        "sha256": digest_text(text) if exists else "",
    }


def select_theme_lines(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    selected: dict[int, dict[str, Any]] = {}
    for index, line in enumerate(lines, start=1):
        matched = [term for term in THEME_TERMS if term.lower() in line.lower()]
        if not matched:
            continue
        start = max(1, index - 2)
        end = min(len(lines), index + 2)
        selected[index] = {
            "line": index,
            "matched_terms": matched,
            "context_start_line": start,
            "context_end_line": end,
            "text": line.strip(),
            "context": "\n".join(lines[start - 1 : end]).strip(),
        }
    return [selected[key] for key in sorted(selected)[:24]]


def output_paths(runtime: Path, wave_id: str, episode_id: str) -> dict[str, str]:
    wave_stem = safe_stem(wave_id)
    root = runtime / "state" / "total_source_episode_entry"
    episode_root = runtime / "runs" / "episodes" / episode_id
    return {
        "runtime_latest": str(root / "latest.json"),
        "wave_record": str(root / "waves" / f"{wave_stem}.json"),
        "workflow_entry": str(episode_root / "workflow_entry.json"),
        "episode_trace": str(episode_root / "episode_trace.jsonl"),
        "capability_manifest": str(runtime / "capabilities" / "codex_s.total_source_episode_entry" / "manifest.json"),
        "capability_invoke_latest": str(
            runtime / "capabilities" / "codex_s.total_source_episode_entry" / "invoke_evidence" / "latest.json"
        ),
        "readback_zh": str(runtime / "readback" / "zh" / "total_source_episode_entry_20260705.md"),
    }


def build_workflow_entry(
    *,
    wave_id: str,
    episode_id: str,
    source: dict[str, Any],
    theme_lines: list[dict[str, Any]],
    paths: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.workflow_entry.v1",
        "sentinel": SENTINEL,
        "status": "episode_workflow_entry_invokable",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "episode_id": episode_id,
        "theme_family": THEME_FAMILY,
        "source_package_ref": source,
        "source_theme_line_refs": theme_lines,
        "workflow_shape": [
            "POST /episodes",
            "WorkflowPort",
            "EvidenceLedger",
            "ReflectionRecord",
            "MemoryBlock(candidate_only)",
            "StrategyUpdate",
            "NextFrontier",
            "ChineseReadback",
            "ReplayEvalResult",
        ],
        "phase0_only": True,
        "phase1_research_episode_started": False,
        "real_data_ingestion_allowed": False,
        "positive_ev_claim_allowed": False,
        "invoke_ref": paths["capability_invoke_latest"],
        "readback_ref": paths["readback_zh"],
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": (
                source.get("exists") is True
                and any("POST /episodes" in item.get("matched_terms", []) for item in theme_lines)
                and any("WorkflowPort" in item.get("matched_terms", []) for item in theme_lines)
            ),
            "checks": {
                "source_package_exists": source.get("exists") is True,
                "source_package_read_full": source.get("read_full") is True,
                "post_episodes_anchor_found": any("POST /episodes" in item.get("matched_terms", []) for item in theme_lines),
                "workflow_port_anchor_found": any("WorkflowPort" in item.get("matched_terms", []) for item in theme_lines),
                "phase0_only": True,
                "phase1_not_started": True,
                "completion_claim_denied": True,
            },
        },
    }


def render_readback(payload: dict[str, Any]) -> str:
    invoke = payload.get("can_invoke_now") if isinstance(payload.get("can_invoke_now"), dict) else {}
    return "\n".join(
        [
            "# 20260701 总稿 episode 入口主题族 readback",
            "",
            SENTINEL,
            "",
            f"- wave_id: `{payload.get('wave_id')}`",
            f"- theme_family: `{payload.get('theme_family')}`",
            f"- source_package: `{payload.get('source_package_ref', {}).get('path', '')}`",
            f"- workflow_entry_ref: `{payload.get('output_paths', {}).get('workflow_entry', '')}`",
            f"- invoke_evidence_ref: `{payload.get('output_paths', {}).get('capability_invoke_latest', '')}`",
            "",
            f"1. 现在能干什么：把 20260701 总稿里的 episode/WorkflowPort 主题族锚成一个 Phase0 episode workflow entry，并写 D 盘 workflow_entry、trace、capability invoke evidence。",
            f"2. 怎么 invoke：`{invoke.get('cli', '')}`。",
            "3. 还差什么：这只打通 episode 入口主题族；还没有启动 Phase1 ResearchEpisode 数据链，也没有宣称 20260701 总稿全量吸收完成。",
            "",
            SENTINEL,
            "",
        ]
    )


def build(
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    source_package_path: str | Path = DEFAULT_SOURCE_PACKAGE,
    wave_id: str = "total-source-episode-entry-20260705",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    source_path = Path(source_package_path)
    source = source_ref(source_path)
    text = source_path.read_text(encoding="utf-8-sig", errors="replace") if source_path.is_file() else ""
    theme_lines = select_theme_lines(text)
    episode_id = f"total-source-episode-entry-{safe_stem(wave_id)}"
    paths = output_paths(runtime, wave_id, episode_id)
    workflow_entry = build_workflow_entry(
        wave_id=wave_id,
        episode_id=episode_id,
        source=source,
        theme_lines=theme_lines,
        paths=paths,
    )
    can_invoke_now = {
        "cli": (
            "python -m xinao_seedlab.cli.__main__ total-source-episode-entry "
            f"--source-package \"{source_path}\" --wave-id {wave_id}"
        ),
        "service": "SeedCortexService.total_source_episode_entry(...)",
        "module": "python -m services.agent_runtime.total_source_episode_entry",
        "capability": "codex_s.total_source_episode_entry",
    }
    manifest = {
        "schema_version": "xinao.codex_s.capability_manifest.v1",
        "provider_id": "codex_s.total_source_episode_entry",
        "capability_kinds": [
            "total_source_episode_entry",
            "phase0_episode_workflow_entry",
            "source_bound_workflow_port",
        ],
        "theme_family": THEME_FAMILY,
        "source_package_ref": str(source_path),
        "invoke_command": can_invoke_now["cli"],
        "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
        "runtime_enforced": False,
        "phase1_research_episode_started": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "validation": workflow_entry["validation"],
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "total_source_episode_entry_invoked"
        if workflow_entry["validation"]["passed"]
        else "total_source_episode_entry_blocked",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "episode_id": episode_id,
        "theme_family": THEME_FAMILY,
        "source_package_ref": source,
        "source_theme_line_refs": theme_lines,
        "workflow_entry": workflow_entry,
        "can_invoke_now": can_invoke_now,
        "capability_manifest": manifest,
        "output_paths": paths,
        "repo_diff_required": True,
        "repo_root": str(repo),
        "phase0_only": True,
        "phase1_research_episode_started": False,
        "real_data_ingestion_allowed": False,
        "positive_ev_claim_allowed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
        "validation": workflow_entry["validation"],
    }
    if write:
        write_json(Path(paths["workflow_entry"]), workflow_entry)
        append_jsonl(
            Path(paths["episode_trace"]),
            {
                "event_type": "total_source_episode_entry_invoked",
                "episode_id": episode_id,
                "wave_id": wave_id,
                "theme_family": THEME_FAMILY,
                "workflow_entry_ref": paths["workflow_entry"],
                "generated_at": payload["generated_at"],
                "completion_claim_allowed": False,
            },
        )
        write_json(Path(paths["capability_manifest"]), manifest)
        write_json(Path(paths["capability_invoke_latest"]), payload)
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["wave_record"]), payload)
        write_text(Path(paths["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind one 20260701 total-source theme family to an episode entry.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--source-package", default=str(DEFAULT_SOURCE_PACKAGE))
    parser.add_argument("--wave-id", default="total-source-episode-entry-20260705")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=Path(args.runtime_root),
        repo_root=Path(args.repo_root),
        source_package_path=Path(args.source_package),
        wave_id=args.wave_id,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
