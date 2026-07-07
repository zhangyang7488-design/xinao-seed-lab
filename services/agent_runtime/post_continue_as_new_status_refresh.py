from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import bounded_result_wait, codex_333_run_reconciler

SCHEMA_VERSION = "xinao.codex_s.post_continue_as_new_status_refresh.v1"
SENTINEL = "SENTINEL:XINAO_POST_CONTINUE_AS_NEW_STATUS_REFRESH_READY"
TASK_ID = "p0_010_post_continue_as_new_status_refresh"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "post_continue_as_new_status_refresh"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "readback": runtime / "readback" / "zh" / "post_continue_as_new_status_refresh_20260707.md",
        "capability_manifest": runtime
        / "capabilities"
        / "codex_s.post_continue_as_new_status_refresh"
        / "manifest.json",
    }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Post Continue-As-New Status Refresh",
            "",
            SENTINEL,
            "",
            "## 结果",
            "",
            f"- status: `{payload.get('status')}`",
            f"- current_run_id: `{payload.get('current_workflow_run_id')}`",
            f"- bounded_result_wait_run_id: `{payload.get('bounded_result_wait_run_id')}`",
            f"- refresh_source: `{payload.get('refresh_source')}`",
            f"- named_blocker: `{payload.get('named_blocker') or '(none)'}`",
            "",
            "## 意义",
            "",
            "- Continue-As-New 后会刷新 current_333_run_index 和 bounded_result_wait。",
            "- 用户问后台状态时，不再读到上一代 run_id。",
            "- 本层不是 completion gate。",
            "",
        ]
    )


def write_artifact_acceptance(
    runtime: Path, repo: Path, payload: dict[str, Any], paths: dict[str, Path]
) -> dict[str, Any]:
    try:
        from xinao_seedlab.application.seed_cortex import build_default_service
    except ImportError:
        return {"written": False, "reason": "seed_cortex_unavailable"}
    service = build_default_service(runtime, repo_root=repo)
    aaq = service.artifact_acceptance_queue(
        "p0-010-post-continue-as-new-status-refresh-accepted",
        [
            {
                "candidate_id": TASK_ID,
                "artifact_ref": str(paths["latest"]),
                "artifact_kind": "post_continue_as_new_status_refresh",
                "workflow_id": str(payload.get("current_workflow_id") or ""),
                "workflow_run_id": str(payload.get("current_workflow_run_id") or ""),
                "accepted_for": "accepted_for_binding",
            }
        ],
        write_runtime=True,
    )
    return {
        "written": True,
        "episode_id": str(aaq.get("episode_id") or ""),
        "decision": "accepted_for_binding",
    }


def build_post_continue_as_new_status_refresh(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    workflow_id: str = "",
    workflow_run_id: str = "",
    refresh_source: str = "manual",
    write: bool = True,
    write_aaq: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)

    reconciler_payload = codex_333_run_reconciler.build(runtime_root=runtime, repo_root=repo)
    bounded_payload = bounded_result_wait.build_bounded_result_wait(
        runtime_root=runtime,
        repo_root=repo,
        write=True,
        write_aaq=False,
    )
    current = read_json(runtime / "state" / "current_333_run_index" / "latest.json")
    bounded_latest = read_json(runtime / "state" / "bounded_result_wait" / "latest.json")
    current_workflow_id = str(current.get("workflow_id") or "")
    current_workflow_run_id = str(current.get("workflow_run_id") or "")
    bounded_workflow_run_id = str(bounded_latest.get("current_workflow_run_id") or "")
    expected_workflow_matches = not workflow_id or current_workflow_id == workflow_id
    expected_run_matches = not workflow_run_id or current_workflow_run_id == workflow_run_id
    checks = {
        "current_333_run_index_ready": current.get("status") == "current_333_run_index_ready",
        "bounded_result_wait_ready": bounded_latest.get("bounded_result_wait_ready") is True,
        "current_and_bounded_run_aligned": current_workflow_run_id == bounded_workflow_run_id,
        "expected_workflow_matches": expected_workflow_matches,
        "expected_run_matches": expected_run_matches,
        "completion_claim_blocked": True,
    }
    ready = all(checks.values())
    named_blocker = "" if ready else "POST_CONTINUE_AS_NEW_STATUS_REFRESH_NOT_BOUND"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "post_continue_as_new_status_refresh_ready"
        if ready
        else "post_continue_as_new_status_refresh_blocked",
        "post_continue_as_new_status_refresh_ready": ready,
        "refresh_source": refresh_source,
        "current_workflow_id": current_workflow_id,
        "current_workflow_run_id": current_workflow_run_id,
        "bounded_result_wait_run_id": bounded_workflow_run_id,
        "input_workflow_id": workflow_id,
        "input_workflow_run_id": workflow_run_id,
        "named_blocker": named_blocker,
        "current_333_run_index": {
            "status": current.get("status"),
            "workflow_id": current_workflow_id,
            "workflow_run_id": current_workflow_run_id,
        },
        "bounded_result_wait": {
            "status": bounded_latest.get("status"),
            "ready": bounded_latest.get("bounded_result_wait_ready") is True,
            "current_state": bounded_latest.get("current_state"),
            "current_workflow_run_id": bounded_workflow_run_id,
        },
        "reconciler_status": reconciler_payload.get("status"),
        "validation": {
            "passed": ready,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "acceptance": {
            "accepted_for": "accepted_for_binding",
            "artifact_acceptance_decision": "accepted_for_binding",
            "success_field": "post_continue_as_new_status_refresh_ready",
            "success_decision": "accepted_for_binding",
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "output_paths": {key: str(value) for key, value in paths.items()},
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
        write_json(
            paths["capability_manifest"],
            {
                "schema_version": f"{SCHEMA_VERSION}.capability_manifest.v1",
                "provider_id": "codex_s.post_continue_as_new_status_refresh",
                "status": "registered",
                "task_id": TASK_ID,
                "runtime_latest": str(paths["latest"]),
                "readback": str(paths["readback"]),
                "completion_claim_allowed": False,
                "not_execution_controller": True,
                "generated_at": now_iso(),
            },
        )
        if write_aaq and ready:
            payload["artifact_acceptance"] = write_artifact_acceptance(
                runtime, repo, payload, paths
            )
            write_json(paths["latest"], payload)
            write_json(paths["record"], payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="post-continue-as-new-status-refresh")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--refresh-source", default="manual")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-aaq", action="store_true")
    args = parser.parse_args(argv)
    payload = build_post_continue_as_new_status_refresh(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        workflow_id=args.workflow_id,
        workflow_run_id=args.workflow_run_id,
        refresh_source=args.refresh_source,
        write=not args.no_write,
        write_aaq=not args.no_aaq,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "ready": payload["post_continue_as_new_status_refresh_ready"],
                "current_workflow_run_id": payload["current_workflow_run_id"],
                "bounded_result_wait_run_id": payload["bounded_result_wait_run_id"],
                "named_blocker": payload["named_blocker"],
                "validation": payload["validation"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("post_continue_as_new_status_refresh_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
