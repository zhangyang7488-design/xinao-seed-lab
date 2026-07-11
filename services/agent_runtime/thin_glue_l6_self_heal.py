"""L6 自修复 — Temporal retry policy + 薄 critic（替 pre_pass_audit_loop 马拉松）."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME, write_json

REPLACES_TARGET = "pre_pass_audit_loop.py"
SCHEMA_VERSION = "xinao.codex_s.thin_glue_l6_self_heal.v1"
SENTINEL = "SENTINEL:XINAO_THIN_GLUE_L6_SELF_HEAL_READY"


def thin_glue_self_heal_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_SELF_HEAL", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def temporal_retry_policy_spec() -> dict[str, Any]:
    """Mirror temporalio/samples-python RetryPolicy defaults — thin bind, no handroll."""
    return {
        "adapter": "temporalio.samples-python.RetryPolicy",
        "initial_interval_seconds": 1,
        "backoff_coefficient": 2.0,
        "maximum_interval_seconds": 30,
        "maximum_attempts": 3,
        "non_retryable_error_types": ["ValueError", "TypeError"],
        "hand_rolled_pre_pass_audit_bypassed": True,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _latest_bus_readback(runtime: Path) -> dict[str, Any] | None:
    path = runtime / "state" / "integrated_bus_v2" / "latest.json"
    payload = _read_json(path)
    return {"path": str(path), "payload": payload} if payload else None


def run_thin_glue_critic(*, loop_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not loop_payload:
        return {
            "decision": "retry_recommended",
            "named_blocker": "THIN_GLUE_LOOP_READBACK_MISSING",
            "retry_recommended": True,
            "repair_required": True,
            "final_allowed": False,
            "action": "reinvoke_integrated_bus",
        }
    passed = loop_payload.get("validation", {}).get("passed") is True
    blocker = loop_payload.get("named_blocker")
    checks = (
        loop_payload.get("validation", {}).get("checks")
        if isinstance(loop_payload.get("validation"), dict)
        else {}
    )
    failed_checks = [k for k, v in (checks or {}).items() if v is False]
    if passed:
        return {
            "decision": "all_pass_final_allowed",
            "named_blocker": "",
            "retry_recommended": False,
            "repair_required": False,
            "final_allowed": True,
            "action": "continue_mainline",
        }
    return {
        "decision": "repair_required",
        "named_blocker": blocker or "THIN_GLUE_LOOP_PARTIAL",
        "retry_recommended": True,
        "repair_required": True,
        "final_allowed": False,
        "failed_checks": failed_checks,
        "action": "retry_with_temporal_policy",
    }


def run_thin_glue_self_heal(
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    wave_id: str = "thin-glue-self-heal-wave",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    loop_hit = _latest_bus_readback(runtime)
    loop_payload = loop_hit["payload"] if loop_hit else None
    critic = run_thin_glue_critic(loop_payload=loop_payload)
    retry_policy = temporal_retry_policy_spec()
    passed = critic.get("decision") == "all_pass_final_allowed"

    acceptance_cn = (
        "L6 薄自修复：loop 绿，主链继续；Temporal retry policy 已登记，未跑审计马拉松。"
        if passed
        else f"L6 薄自修复：loop 未绿 → {critic.get('action')}；"
        f"blocker={critic.get('named_blocker') or '无'}；"
        "handroll pre_pass_audit_loop 已旁路。"
    )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "run_id": run_id,
        "wave_id": wave_id,
        "thin_glue": True,
        "replaces": REPLACES_TARGET,
        "not_333_mainline": True,
        "handroll_intact": False,
        "hand_rolled_pre_pass_audit_bypassed": True,
        "temporal_retry_policy": retry_policy,
        "latest_integrated_bus_readback": loop_hit["path"] if loop_hit else None,
        "critic": critic,
        "acceptance_now_can_invoke_cn": acceptance_cn,
        "validation": {
            "passed": passed,
            "checks": {
                "loop_readback_present": loop_hit is not None,
                "critic_decision_ready": bool(critic.get("decision")),
                "temporal_retry_policy_documented": True,
                "hand_rolled_pre_pass_audit_bypassed": True,
            },
            "validated_at": run_id,
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
    }

    if write:
        latest = runtime / "state" / "thin_glue_self_heal" / "latest.json"
        evidence = runtime / "readback" / f"thin_glue_self_heal_{run_id}.json"
        write_json(latest, payload)
        write_json(evidence, payload)
        zh = runtime / "readback" / "zh" / f"thin_glue_self_heal_{run_id}.md"
        zh.parent.mkdir(parents=True, exist_ok=True)
        zh.write_text(
            "\n".join(
                [
                    f"# L6 薄自修复 {run_id}",
                    f"- passed: {passed}",
                    f"- decision: {critic.get('decision')}",
                    acceptance_cn,
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        payload["output_paths"] = {
            "latest": str(latest),
            "evidence": str(evidence),
            "readback_zh": str(zh),
        }

    return payload


def run_thin_glue_self_heal_as_pre_pass_delegate(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_id: str = "pre_pass_audit_loop_20260704",
    wave_id: str = "pre-pass-audit-loop-wave-001",
    invoked_by_temporal_activity: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    """Drop-in delegate for pre_pass_audit_loop.build when L6 thin glue is on."""
    runtime = Path(runtime_root)
    thin = run_thin_glue_self_heal(
        runtime_root=runtime,
        repo_root=Path(repo_root),
        wave_id=wave_id,
        write=write,
    )
    critic = thin.get("critic") if isinstance(thin.get("critic"), dict) else {}
    paths = {
        "latest": str(runtime / "state" / "thin_glue_self_heal" / "latest.json"),
        "candidate_snapshot_latest": str(runtime / "state" / "thin_glue_self_heal" / "latest.json"),
        "audit_lane_registry_latest": str(
            runtime / "state" / "thin_glue_self_heal" / "latest.json"
        ),
        "audit_fan_in_latest": str(runtime / "state" / "thin_glue_self_heal" / "latest.json"),
        "readback_zh": (thin.get("output_paths") or {}).get("readback_zh", ""),
        "task_wave": str(runtime / "state" / "thin_glue_self_heal" / "latest.json"),
    }
    fan_in = {
        "decision": critic.get("decision", "repair_required"),
        "fixable_count": 0 if critic.get("final_allowed") else 1,
        "final_allowed": critic.get("final_allowed") is True,
    }
    return {
        "schema_version": "xinao.codex_s.pre_pass_audit_loop.v1",
        "task_id": task_id,
        "wave_id": wave_id,
        "status": "thin_glue_l6_delegate_ready",
        "delegated_from": "pre_pass_audit_loop.build",
        "thin_glue_l6_self_heal": thin,
        "audit_fan_in": fan_in,
        "repair_plan_ref": "",
        "pre_pass_payload": {
            "all_pass": critic.get("decision") == "all_pass_final_allowed",
            "repair_required": critic.get("repair_required") is True,
            "named_blocker": critic.get("named_blocker", ""),
            "continue_main_loop": critic.get("repair_required") is True,
            "decision": critic.get("decision", ""),
        },
        "named_blocker": critic.get("named_blocker", ""),
        "invoked_by_temporal_activity": invoked_by_temporal_activity,
        "runtime_enforced": invoked_by_temporal_activity,
        "runtime_enforced_scope": "seed_cortex_temporal_pre_pass_audit_loop_activity"
        if invoked_by_temporal_activity
        else "",
        "not_completion_gate": True,
        "not_execution_controller": True,
        "completion_claim_allowed": False,
        "final_allowed": critic.get("final_allowed") is True,
        "not_user_completion": True,
        "output_paths": paths,
        "validation": thin.get("validation", {}),
        "acceptance_now_can_invoke_cn": thin.get("acceptance_now_can_invoke_cn", ""),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="L6 thin glue self-heal critic")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wave-id", default="thin-glue-self-heal-wave")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    payload = run_thin_glue_self_heal(
        runtime_root=Path(args.runtime_root),
        repo_root=Path(args.repo_root),
        wave_id=args.wave_id,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
