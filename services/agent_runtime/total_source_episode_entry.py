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

from services.agent_runtime import task_package_resolver as task_package

SCHEMA_VERSION = "xinao.codex_s.total_source_episode_entry.v1"
SENTINEL = "SENTINEL:XINAO_TOTAL_SOURCE_EPISODE_ENTRY_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = "total_source_episode_entry_20260705"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_SOURCE_PACKAGE = task_package.DEFAULT_TASK_PACKAGE_ROOT / "TASK_PACKAGE.json"
SRC_ROOT = DEFAULT_REPO / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
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


def resolve_episode_source(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_dir():
        package = task_package.resolve_task_package(path, include_manifest_ref=False)
    elif path.name in task_package.TASK_PACKAGE_MANIFEST_NAMES and path.is_file():
        package = task_package.resolve_task_package(
            path.parent,
            manifest_path=path,
            include_manifest_ref=False,
        )
    elif path == DEFAULT_SOURCE_PACKAGE:
        package = task_package.resolve_current_task_package(include_manifest_ref=False)
    else:
        source = source_ref(path)
        text = path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else ""
        return source, text

    parts: list[str] = []
    for ref in package.get("refs", []):
        resource_path = Path(str(ref.get("path") or ""))
        if resource_path.is_file():
            parts.append(resource_path.read_text(encoding="utf-8-sig", errors="replace"))
    source = {
        "path": str(package.get("entrypoint_ref") or package.get("task_package_manifest_path") or path),
        "exists": package.get("all_required_sources_read_full") is True,
        "read_full": package.get("all_required_sources_read_full") is True,
        "line_count": sum(int(ref.get("line_count") or 0) for ref in package.get("refs", [])),
        "char_count": sum(int(ref.get("char_count") or 0) for ref in package.get("refs", [])),
        "sha256": str(package.get("source_package_digest_sha256") or ""),
        "task_package": package,
        "manifest_driven": package.get("manifest_driven") is True,
        "single_entry_driven": package.get("single_entry_driven") is True,
        "legacy_fallback": package.get("legacy_fallback") is True,
    }
    return source, "\n\n".join(parts)


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
        "aaq_latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "next_frontier": str(root / "next_frontier" / f"{wave_stem}.json"),
        "next_frontier_latest": str(root / "next_frontier" / "latest.json"),
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
    aaq = payload.get("artifact_acceptance_queue") if isinstance(payload.get("artifact_acceptance_queue"), dict) else {}
    next_frontier = payload.get("next_frontier") if isinstance(payload.get("next_frontier"), dict) else {}
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
            f"- aaq_ref: `{payload.get('output_paths', {}).get('aaq_latest', '')}`",
            f"- next_frontier_ref: `{payload.get('output_paths', {}).get('next_frontier_latest', '')}`",
            "",
            f"1. 现在能干什么：把 20260701 总稿里的 episode/WorkflowPort 主题族锚成一个 Phase0 episode workflow entry，并可选回流 AAQ/next_frontier；本次 AAQ accepted={aaq.get('accepted_artifact_count', 0)}，next_frontier_open={next_frontier.get('source_gap_open', '')}。",
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
    submit_aaq: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    source_path = Path(source_package_path)
    source, text = resolve_episode_source(source_path)
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
            + (" --submit-aaq" if submit_aaq else "")
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
        "source_package_ref": source,
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
    aaq_payload: dict[str, Any] = {}
    next_frontier: dict[str, Any] = {}
    if submit_aaq:
        from xinao_seedlab.application.seed_cortex import build_default_service

        candidate = {
            "object_type": "ClaimCard",
            "candidate_id": f"{episode_id}-workflow-entry",
            "source_url": str(source_path),
            "source_family": "local_total_source_20260701",
            "claim": (
                "20260701 total source defines POST /episodes -> WorkflowPort "
                "as the Phase0 episode ingress theme family."
            ),
            "verification_need": (
                "total_source_episode_entry workflow_entry validation must find "
                "POST /episodes and WorkflowPort anchors before AAQ acceptance."
            ),
            "accepted_for": "next_frontier_evidence",
            "artifact_ref": paths["workflow_entry"],
            "claim_card_ref": paths["workflow_entry"],
        }
        service = build_default_service(runtime, repo_root=repo)
        aaq_payload = service.artifact_acceptance_queue(
            episode_id,
            [candidate],
            write_runtime=write,
        )
        next_frontier = {
            "schema_version": f"{SCHEMA_VERSION}.next_frontier.v1",
            "sentinel": SENTINEL,
            "status": "total_source_episode_entry_next_frontier_ready"
            if aaq_payload.get("validation", {}).get("passed") is True
            else "total_source_episode_entry_next_frontier_blocked",
            "work_id": WORK_ID,
            "task_id": TASK_ID,
            "wave_id": wave_id,
            "episode_id": episode_id,
            "theme_family": THEME_FAMILY,
            "source_gap_open": True,
            "next_frontier": [
                {
                    "frontier_id": "total_source_next_theme_after_episode_entry",
                    "theme_family": "fan_in_heart_or_default_runtime_binding",
                    "reason": "Only one 20260701 theme family was landed in this wave.",
                    "requires": [
                        "choose_one_next_total_source_theme",
                        "invoke_bound_diff",
                        "AAQ_or_named_blocker",
                    ],
                }
            ],
            "workflow_entry_ref": paths["workflow_entry"],
            "aaq_ref": str(aaq_payload.get("output_paths", {}).get("runtime_latest") or paths["aaq_latest"]),
            "accepted_artifact_count": int(aaq_payload.get("accepted_artifact_count") or 0),
            "completion_claim_allowed": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "validation": {
                "passed": aaq_payload.get("validation", {}).get("passed") is True,
                "checks": {
                    "aaq_accepted_episode_entry": int(aaq_payload.get("accepted_artifact_count") or 0) > 0,
                    "source_gap_remains_open": True,
                    "completion_claim_denied": True,
                },
            },
            "generated_at": now_iso(),
        }
    if submit_aaq:
        payload["artifact_acceptance_queue"] = aaq_payload
        payload["next_frontier"] = next_frontier
        payload["output_paths"]["next_frontier"] = paths["next_frontier"]
        payload["output_paths"]["next_frontier_latest"] = paths["next_frontier_latest"]
        payload["validation"]["checks"]["aaq_accepted_episode_entry"] = (
            int(aaq_payload.get("accepted_artifact_count") or 0) > 0
        )
        payload["validation"]["checks"]["next_frontier_written"] = (
            next_frontier.get("validation", {}).get("passed") is True
        )
        payload["validation"]["passed"] = (
            payload["validation"]["passed"] is True
            and payload["validation"]["checks"]["aaq_accepted_episode_entry"] is True
            and payload["validation"]["checks"]["next_frontier_written"] is True
        )
        workflow_entry["artifact_acceptance_queue_ref"] = str(
            aaq_payload.get("output_paths", {}).get("runtime_latest") or paths["aaq_latest"]
        )
        workflow_entry["next_frontier_ref"] = paths["next_frontier_latest"]
        manifest["aaq_bound"] = True
        manifest["next_frontier_ref"] = paths["next_frontier_latest"]
        payload["workflow_entry"] = workflow_entry
        payload["capability_manifest"] = manifest
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
                "artifact_acceptance_queue_ref": workflow_entry.get("artifact_acceptance_queue_ref", ""),
                "next_frontier_ref": workflow_entry.get("next_frontier_ref", ""),
                "generated_at": payload["generated_at"],
                "completion_claim_allowed": False,
            },
        )
        write_json(Path(paths["capability_manifest"]), manifest)
        if submit_aaq:
            write_json(Path(paths["next_frontier"]), next_frontier)
            write_json(Path(paths["next_frontier_latest"]), next_frontier)
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
    parser.add_argument("--submit-aaq", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=Path(args.runtime_root),
        repo_root=Path(args.repo_root),
        source_package_path=Path(args.source_package),
        wave_id=args.wave_id,
        submit_aaq=args.submit_aaq,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
