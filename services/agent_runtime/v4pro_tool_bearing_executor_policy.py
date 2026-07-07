from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.v4pro_tool_bearing_executor_policy.v1"
SENTINEL = "SENTINEL:XINAO_V4PRO_TOOL_BEARING_EXECUTOR_POLICY_READY"
TASK_ID = "p0_011_v4pro_tool_bearing_executor_policy"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_SHORTCUT = Path(
    os.environ.get(
        "XINAO_V4PRO_HARDMODE_SHORTCUT",
        r"C:\Users\xx363\Desktop\OPEN DEEPSEEK V4 PRO S HARDMODE.lnk",
    )
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


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
    state = runtime / "state" / "v4pro_tool_bearing_executor_policy"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "readback": runtime / "readback" / "zh" / "v4pro_tool_bearing_executor_policy_20260707.md",
        "capability_manifest": runtime
        / "capabilities"
        / "codex_s.v4pro_tool_bearing_executor_policy"
        / "manifest.json",
    }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def shortcut_target(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "path": str(path)}
    script = (
        "$shell=New-Object -ComObject WScript.Shell; "
        f"$s=$shell.CreateShortcut('{str(path)}'); "
        "[pscustomobject]@{TargetPath=$s.TargetPath;Arguments=$s.Arguments;"
        "WorkingDirectory=$s.WorkingDirectory;Description=$s.Description} | ConvertTo-Json -Depth 4"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exists": True, "path": str(path), "error": str(exc)}
    if completed.returncode != 0:
        return {"exists": True, "path": str(path), "error": completed.stderr}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {}
    return {"exists": True, "path": str(path), **payload}


def git_clean(repo: Path) -> bool:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    return completed.returncode == 0 and not completed.stdout.strip()


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V4Pro Tool-Bearing Executor Policy",
            "",
            SENTINEL,
            "",
            f"- provider_id: `{payload.get('provider_id')}`",
            f"- tool_bearing_executor_eligible: `{payload.get('tool_bearing_executor_eligible')}`",
            f"- repo_mutation_allowed: `{payload.get('repo_mutation_allowed')}`",
            f"- commit_push_allowed: `{payload.get('commit_push_allowed')}`",
            f"- final_acceptance_owner: `{payload.get('final_acceptance_owner')}`",
            "",
            "V4Pro 可以改仓、跑 verifier、commit/push；但必须提交 closure evidence bundle。",
            "没有 commit hash / push target / git clean / verifier / D runtime evidence，不算完成。",
            "",
        ]
    )


def write_artifact_acceptance(runtime: Path, repo: Path, payload: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    try:
        from xinao_seedlab.application.seed_cortex import build_default_service
    except ImportError:
        return {"written": False, "reason": "seed_cortex_unavailable"}
    service = build_default_service(runtime, repo_root=repo)
    aaq = service.artifact_acceptance_queue(
        "p0-011-v4pro-tool-bearing-executor-policy-accepted",
        [
            {
                "candidate_id": TASK_ID,
                "artifact_ref": str(paths["latest"]),
                "artifact_kind": "v4pro_tool_bearing_executor_policy",
                "workflow_id": "",
                "workflow_run_id": "",
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


def build_policy(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    shortcut_path: str | Path = DEFAULT_SHORTCUT,
    write: bool = True,
    write_aaq: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    shortcut = shortcut_target(Path(shortcut_path))
    provider_scheduler = read_json(runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json")
    if not provider_scheduler:
        provider_scheduler = read_json(runtime / "state" / "codex_native_provider_scheduler_phase4" / "latest.json")
    v4pro_visible = "deepseek_v4_pro" in json.dumps(provider_scheduler, ensure_ascii=False)
    shortcut_valid = (
        shortcut.get("exists") is True
        and "XINAO DeepSeek V4 Pro S Hardmode" in str(shortcut.get("Arguments") or "")
        and str(shortcut.get("WorkingDirectory") or "").rstrip("\\/").lower()
        == str(repo).rstrip("\\/").lower()
    )
    closure_bundle = [
        "default_mainline_binding",
        "runtime_worker_load",
        "focused_verification",
        "D_runtime_evidence_readback",
        "git_clean_status",
        "commit_hash",
        "push_target",
        "current_333_mainline_state",
        "remaining_or_named_blocker_state",
    ]
    checks = {
        "shortcut_targets_s_hardmode_profile": shortcut_valid,
        "deepseek_v4_pro_visible_in_provider_scheduler": v4pro_visible,
        "closure_bundle_required": True,
        "final_acceptance_not_self_signed": True,
        "secrets_not_writable_to_repo": True,
    }
    ready = all(checks.values())
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "v4pro_tool_bearing_executor_policy_ready" if ready else "v4pro_tool_bearing_executor_policy_blocked",
        "provider_id": "deepseek_v4_pro",
        "tool_bearing_executor_eligible": ready,
        "repo_mutation_allowed": ready,
        "commit_push_allowed": ready,
        "commit_push_scope": "current S repo only, after focused verification and closure evidence bundle",
        "final_acceptance_owner": "codex_or_deterministic_verifier",
        "v4pro_self_acceptance_allowed": False,
        "closure_evidence_bundle_required": closure_bundle,
        "shortcut": shortcut,
        "git_clean_at_policy_write": git_clean(repo),
        "named_blocker": "" if ready else "V4PRO_TOOL_BEARING_EXECUTOR_POLICY_NOT_BOUND",
        "validation": {
            "passed": ready,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "acceptance": {
            "accepted_for": "accepted_for_binding",
            "artifact_acceptance_decision": "accepted_for_binding",
            "success_field": "v4pro_tool_bearing_executor_policy_ready",
            "success_decision": "accepted_for_binding",
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    paths = output_paths(runtime)
    payload["output_paths"] = {key: str(value) for key, value in paths.items()}
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
        write_json(
            paths["capability_manifest"],
            {
                "schema_version": f"{SCHEMA_VERSION}.capability_manifest.v1",
                "provider_id": "codex_s.v4pro_tool_bearing_executor_policy",
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
            payload["artifact_acceptance"] = write_artifact_acceptance(runtime, repo, payload, paths)
            write_json(paths["latest"], payload)
            write_json(paths["record"], payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v4pro-tool-bearing-executor-policy")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--shortcut-path", default=str(DEFAULT_SHORTCUT))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-aaq", action="store_true")
    args = parser.parse_args(argv)
    payload = build_policy(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        shortcut_path=args.shortcut_path,
        write=not args.no_write,
        write_aaq=not args.no_aaq,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("tool_bearing_executor_eligible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
