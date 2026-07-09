"""Grok bridge: B/C engineering audit via codex exec --json with local sync observe plane."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys

BRIDGE_ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = pathlib.Path(r"C:\Users\xx363\CodexWorkspaces\B\nianhua")
RUNTIME_ROOT = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BRIDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(BRIDGE_ROOT))

from grok_audit_common import ENGINEERING_PROFILES, grok_audit_prompt, grok_audit_state  # noqa: E402
from grok_codex_exec_observe import run_codex_exec_json_observed, write_json  # noqa: E402
from services.agent_runtime import task_intake_side_audit_report_generator as gen  # noqa: E402


def run_codex_exec_audit(
    profile: dict,
    role: str,
    state: dict,
    output_dir: pathlib.Path,
    timeout_seconds: int,
    *,
    ticket_id: str = "",
    auditor_code: str = "",
    observe_path: pathlib.Path | None = None,
) -> dict:
    repo = profile["repo"]
    codex_home = profile["codex_home"]
    output_dir.mkdir(parents=True, exist_ok=True)
    final_message = output_dir / f"{role}.codex.final.json"
    stdout_jsonl = output_dir / f"{role}.codex.stdout.jsonl"
    if stdout_jsonl.exists():
        stdout_jsonl.unlink()

    codex_binary = shutil.which("codex.cmd") or shutil.which("codex.exe") or shutil.which("codex")
    if not codex_binary:
        raise FileNotFoundError("CODEX_CLI_NOT_FOUND")

    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    command = [
        codex_binary,
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "-C",
        str(repo),
        "--output-last-message",
        str(final_message),
        "-",
    ]
    prompt = grok_audit_prompt(role, state)
    run_result = run_codex_exec_json_observed(
        command=command,
        cwd=str(repo),
        env=env,
        stdin_text=prompt,
        stdout_jsonl_path=stdout_jsonl,
        observe_path=observe_path,
        timeout_seconds=timeout_seconds,
        ticket_id=ticket_id,
        auditor_code=auditor_code,
        role=role,
    )
    if run_result["exit_code"] != 0:
        raise RuntimeError(run_result["stderr"][-1200:] or f"codex exec returned {run_result['exit_code']}")
    raw = gen.extract_json_object(final_message.read_text(encoding="utf-8-sig"))
    report = gen.normalize_report(
        raw,
        role,
        "codex_exec_jsonl_worker",
        {
            "codex_stdout_jsonl": str(stdout_jsonl),
            "codex_final_message": str(final_message),
            "codex_home": str(codex_home),
            "repo_root": str(repo),
            "carrier": "codex_exec_json_sync_observe",
            "visible_window": False,
            "observe_path": str(observe_path or ""),
            "observe_status": run_result.get("observe", {}).get("status", ""),
            "jsonl_line_count": run_result.get("observe", {}).get("jsonl_line_count", 0),
            "token_usage": run_result.get("observe", {}).get("token_usage", {}),
        },
        {"route": "codex_exec_jsonl_worker", "output_ref": str(final_message)},
    )
    if observe_path is not None:
        observe = dict(run_result.get("observe") or {})
        observe["status"] = "report_written"
        observe["report_path"] = ""
        write_json(observe_path, observe)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Grok parallel global engineering audit (codex exec + local observe).")
    parser.add_argument("--auditor", choices=sorted(ENGINEERING_PROFILES), required=True)
    parser.add_argument("--evidence-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--user-focus-cn", default="")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--ticket-id", default="")
    parser.add_argument("--observe-state-path", default="")
    args = parser.parse_args()

    profile = ENGINEERING_PROFILES[args.auditor]
    role = profile["role"]
    evidence_path = pathlib.Path(args.evidence_path)
    output_path = pathlib.Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    observe_path = pathlib.Path(args.observe_state_path) if args.observe_state_path else None

    state = grok_audit_state(evidence_path, args.user_focus_cn)
    state["engineering_profile"] = {
        "auditor_code": args.auditor,
        "codex_home": str(profile["codex_home"]),
        "repo_root": str(profile["repo"]),
        "quota_label": profile["quota_label"],
        "carrier": "codex_exec_json_sync_observe",
        "visible_window": False,
        "ticket_id": args.ticket_id,
        "observe_state_path": str(observe_path or ""),
    }

    try:
        report = run_codex_exec_audit(
            profile,
            role,
            state,
            output_path.parent,
            args.timeout_seconds,
            ticket_id=args.ticket_id,
            auditor_code=args.auditor,
            observe_path=observe_path,
        )
    except Exception as exc:
        report = gen.blocker_report(
            role,
            "codex_exec_jsonl_worker",
            {
                "evidence_path": str(evidence_path),
                "codex_home": str(profile["codex_home"]),
                "repo_root": str(profile["repo"]),
                "observe_state_path": str(observe_path or ""),
            },
            f"GROK_{args.auditor}_ENGINEERING_AUDIT_ROUTE_FAILED",
            str(exc),
        )
        if observe_path is not None and observe_path.is_file():
            try:
                observe = json.loads(observe_path.read_text(encoding="utf-8"))
                observe["status"] = "failed"
                observe["named_blocker"] = f"GROK_{args.auditor}_ENGINEERING_AUDIT_ROUTE_FAILED"
                observe["error"] = str(exc)[-2000:]
                write_json(observe_path, observe)
            except Exception:
                pass

    report["audit_lane"] = "grok_parallel_global_side_audit"
    report["grok_evidence_path"] = str(evidence_path)
    report["visible_window"] = False
    report["carrier"] = "codex_exec_json_sync_observe"
    report["observe_state_path"] = str(observe_path or "")
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if observe_path is not None:
        try:
            observe = json.loads(observe_path.read_text(encoding="utf-8"))
            observe["status"] = "completed"
            observe["report_path"] = str(output_path)
            observe["report_decision"] = str(report.get("decision") or "")
            write_json(observe_path, observe)
        except Exception:
            pass

    print(json.dumps({"status": report.get("decision", "BLOCK"), "output_path": str(output_path)}, ensure_ascii=False))
    return 0 if report.get("decision") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())