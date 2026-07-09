"""Thin Grok bridge glue: semantic side-audit via mature LiteLLM/DeepSeek route (no window)."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(r"C:\Users\xx363\CodexWorkspaces\B\nianhua")
RUNTIME_ROOT = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
BRIDGE_ROOT = pathlib.Path(__file__).resolve().parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BRIDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(BRIDGE_ROOT))

from grok_audit_common import grok_audit_prompt, grok_audit_state  # noqa: E402
from services.agent_runtime import task_intake_side_audit_report_generator as gen  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Grok parallel global semantic audit worker (thin binding).")
    parser.add_argument("--evidence-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--role", default="dp_semantic_audit")
    parser.add_argument("--user-focus-cn", default="")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    evidence_path = pathlib.Path(args.evidence_path)
    output_path = pathlib.Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    state = grok_audit_state(evidence_path, args.user_focus_cn)
    original_prompt = gen.audit_prompt
    gen.audit_prompt = grok_audit_prompt
    try:
        report = gen.run_deepseek_audit(RUNTIME_ROOT, args.role, state, args.timeout_seconds)
    except Exception as exc:
        report = gen.blocker_report(
            args.role,
            "deepseek_via_litellm_gateway",
            {"evidence_path": str(evidence_path), "runtime_root": str(RUNTIME_ROOT)},
            "GROK_SEMANTIC_AUDIT_ROUTE_FAILED",
            str(exc),
        )
    finally:
        gen.audit_prompt = original_prompt

    report["audit_lane"] = "grok_parallel_global_side_audit"
    report["grok_evidence_path"] = str(evidence_path)
    report["visible_window"] = False
    report["carrier"] = "litellm_deepseek_gateway_background"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report.get("decision", "BLOCK"), "output_path": str(output_path)}, ensure_ascii=False))
    return 0 if report.get("decision") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())