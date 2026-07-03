from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
SCHEMA_VERSION = "xinao.codex_s.metaminute_preflight_reflection.v1"
SENTINEL = "SENTINEL:XINAO_METAMINUTE_PREFLIGHT_REFLECTION_READY"
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")

TRIGGER_POINTS = [
    "window_start_first_hop",
    "after_gate_hook_deny",
    "before_final_pass_report",
    "before_new_parallel_wave",
]

REQUIRED_OUTPUT_FIELDS = [
    "current_user_object",
    "latest_user_delta",
    "active_authority_surfaces",
    "possible_misroute_or_old_gate",
    "safety_template_or_report_stop_risk",
    "what_can_machine_do_now",
    "highest_ev_next_action",
    "continue_or_named_blocker",
]

MATURE_PATTERN_REFS = [
    {
        "pattern_id": "react_reason_then_act",
        "source_url": "https://research.google/blog/react-synergizing-reasoning-and-acting-in-language-models/",
        "absorbed_as": "pre-action reasoning field before tool/action dispatch",
    },
    {
        "pattern_id": "reflexion_feedback_then_next_round",
        "source_url": "https://arxiv.org/abs/2303.17651",
        "absorbed_as": "failure or feedback checkpoint before retry",
    },
    {
        "pattern_id": "self_refine_iterative_feedback",
        "source_url": "https://selfrefine.info/",
        "absorbed_as": "structured self-feedback as candidate signal, not completion",
    },
    {
        "pattern_id": "tree_of_thoughts_expand_then_evaluate",
        "source_url": "https://openreview.net/pdf?id=5Xc1ecxO1h",
        "absorbed_as": "multiple next-action candidates before selecting highest EV",
    },
    {
        "pattern_id": "langgraph_interrupts_persistence",
        "source_url": "https://docs.langchain.com/oss/python/langgraph/interrupts",
        "absorbed_as": "checkpointed interrupt/resume boundary, not chat-only pause",
    },
    {
        "pattern_id": "temporal_durable_execution_for_ai",
        "source_url": "https://temporal.io/blog/durable-execution-meets-ai-why-temporal-is-the-perfect-foundation-for-ai",
        "absorbed_as": "durable workflow boundary for long agent loops",
    },
    {
        "pattern_id": "autogen_reflection_critic",
        "source_url": "https://microsoft.github.io/autogen/dev/user-guide/core-user-guide/design-patterns/reflection.html",
        "absorbed_as": "critic/reflection lane before and after action",
    },
    {
        "pattern_id": "openai_agents_guardrails",
        "source_url": "https://openai.github.io/openai-agents-python/guardrails/",
        "absorbed_as": "composable input/output checks that do not swallow the user goal",
    },
]


def global_self_prelude() -> dict[str, Any]:
    prompt = (
        "Codex S 全局自检前置：先把自己从审查/报告/守门人模式拉回执行图。"
        "看到用户意图后，第一反应是找现在能交付的 artifact：diff、capability invoke、"
        "ClaimCard、evidence 或 named blocker。测试和 readback 只是推进证据，不是停点。"
        "能推进就推进；撞到真实阻塞才命名 blocker。"
    )
    return {
        "schema_version": "xinao.codex_s.global_self_prelude.v1",
        "prelude_id": "codex_s_global_self_prelude_v1",
        "scope": "global_always_on_for_codex_s",
        "trigger_required": False,
        "keyword_required": False,
        "intent": "turn every user delta into an execution graph before review/report mode takes over",
        "default_question": "what artifact can be delivered now?",
        "artifact_units": [
            "diff",
            "capability_invoke",
            "ClaimCard",
            "evidence",
            "named_blocker",
        ],
        "forbidden_default_stop_shapes": [
            "report",
            "PASS",
            "pytest_pass",
            "latest_json",
            "readback_only",
        ],
        "prompt_zh": prompt,
        "not_completion_gate": True,
        "not_execution_controller": True,
    }


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def boundary_fields() -> dict[str, bool]:
    return {
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def read_json_summary(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
    }
    if not path.is_file():
        return summary
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        summary.update({"json_valid": False, "error": str(exc)})
        return summary
    summary.update(
        {
            "json_valid": True,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "sentinel": payload.get("sentinel"),
            "validation_passed": payload.get("validation", {}).get("passed")
            if isinstance(payload.get("validation"), dict)
            else None,
            "named_blocker": payload.get("named_blocker"),
            "completion_claim_allowed": payload.get("completion_claim_allowed"),
            "not_execution_controller": payload.get("not_execution_controller"),
        }
    )
    return summary


def file_ref(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False}
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"path": str(path), "exists": True, "read_error": str(exc)}
    return {
        "path": str(path),
        "exists": True,
        "byte_count": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
    }


def runtime_refs(runtime_root: Path) -> dict[str, dict[str, Any]]:
    refs = {
        "current_route": runtime_root / "state" / "current_route" / "latest.json",
        "worker_assignment": runtime_root
        / "state"
        / "worker_assignment"
        / "xinao_seed_cortex_phase0_20260701.json",
        "default_parallelism_policy": runtime_root
        / "state"
        / "default_parallelism_policy"
        / "latest.json",
        "parallel_dispatch_plan": runtime_root
        / "state"
        / "parallel_dispatch_plan"
        / "latest.json",
        "parallel_fan_in_acceptance": runtime_root
        / "state"
        / "parallel_fan_in_acceptance"
        / "latest.json",
        "max_benefit_dynamic_parallelism": runtime_root
        / "state"
        / "max_benefit_dynamic_parallelism"
        / "latest.json",
        "deepseek_search_sidecar": runtime_root
        / "state"
        / "deepseek_search_sidecar"
        / "latest.json",
        "deepseek_search_source_family_fanout": runtime_root
        / "state"
        / "deepseek_search_source_family_fanout"
        / "latest.json",
        "deepseek_search_fan_in_acceptance": runtime_root
        / "state"
        / "deepseek_search_fan_in_acceptance"
        / "latest.json",
        "verification_topology": runtime_root
        / "state"
        / "verification_topology"
        / "latest.json",
    }
    return {key: read_json_summary(path) for key, path in refs.items()}


def dp_search_fan_in_refs(runtime_root: Path) -> dict[str, dict[str, Any]]:
    base = runtime_root / "state" / "deepseek_search_sidecar" / "fan_in"
    refs = {
        "dp_metaminute_10lane": base / "dp_metaminute_10lane_20260702.json",
        "dp_metaminute_free_10lane": base / "dp_metaminute_free_10lane_20260702.json",
    }
    return {key: file_ref(path) for key, path in refs.items()}


def required_output(
    *,
    trigger: str,
    current_user_object: str,
    latest_user_delta: str,
    runtime_root: Path,
) -> dict[str, Any]:
    surfaces = [
        "CODEX_S_L0.md",
        "SEED_CORTEX_MUST_READ_FIRST.md",
        "contracts/codex-s-workspace-boundary.v1.json",
        str(runtime_root / "state" / "default_parallelism_policy" / "latest.json"),
        str(runtime_root / "state" / "max_benefit_dynamic_parallelism" / "latest.json"),
        str(runtime_root / "state" / "metaminute_preflight_reflection" / "latest.json"),
    ]
    misroutes = [
        {
            "risk": "time_based_prompt_pause",
            "decision": "deny",
            "replacement": "bounded runtime checkpoint with required fields",
        },
        {
            "risk": "old_a_b_c_or_d_clean_gate_as_s_authority",
            "decision": "deny",
            "replacement": "S L0 + S contract island + D_RESEARCH state only",
        },
        {
            "risk": "report_final_or_pass_before_acceptance",
            "decision": "deny",
            "replacement": "fan-in acceptance or named blocker before final-shaped wording",
        },
        {
            "risk": "single_lane_serial_default",
            "decision": "deny",
            "replacement": "default max-benefit frontier parallelism unless serial reason is named",
        },
    ]
    safety_report_risks = [
        {
            "risk": "safety_template_swallowing_safe_engineering_goal",
            "decision": "repair_to_safe_action_variant_before_refusal",
        },
        {
            "risk": "report_pass_or_final_used_as_stop_condition",
            "decision": "deny_stop_semantics_until acceptance evidence or named blocker",
        },
        {
            "risk": "hook_gate_blocks_safe_repair_external_research_or_discussion",
            "decision": "mark possible_misroute_or_old_gate before obeying stale authority",
        },
    ]
    machine_actions = [
        "restore S runtime refs before acting",
        "classify trigger and current user delta",
        "detect old-gate or report-only misroute risk",
        "score highest-EV next machine action",
        "continue execution or emit a named blocker with evidence",
    ]
    if trigger == "before_new_parallel_wave":
        next_action = "run default max-benefit frontier classifier, dispatch independent high-EV lanes, then fan-in acceptance"
    elif trigger == "before_final_pass_report":
        next_action = "check completion wording against fan-in acceptance and side-audit evidence; continue if not accepted"
    elif trigger == "after_gate_hook_deny":
        next_action = "classify deny source, preserve safe repair/external research lanes, and convert true deny to named blocker"
    else:
        next_action = "restore current route, L0, boundary contract, default parallel policy, and choose the highest-EV next machine action"
    return {
        "current_user_object": current_user_object,
        "latest_user_delta": latest_user_delta,
        "active_authority_surfaces": surfaces,
        "possible_misroute_or_old_gate": misroutes,
        "safety_template_or_report_stop_risk": safety_report_risks,
        "what_can_machine_do_now": machine_actions,
        "highest_ev_next_action": {
            "action": next_action,
            "selection_basis": "user_visible_value * acceptance_probability * unblock_reuse_value / cost_verification_merge_risk",
            "requires_fan_in_acceptance": True,
        },
        "continue_or_named_blocker": "continue",
    }


def build_validation(payload: dict[str, Any]) -> dict[str, Any]:
    return validate_payload(payload)


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    required = payload["required_output"]
    highest_ev = required.get("highest_ev_next_action")
    if not isinstance(highest_ev, dict):
        highest_ev = {}
    safety_risks = required.get("safety_template_or_report_stop_risk", [])
    if not isinstance(safety_risks, list):
        safety_risks = []
    report_stop_risk_denied = any(
        isinstance(item, dict)
        and item.get("risk") == "report_pass_or_final_used_as_stop_condition"
        and "deny" in str(item.get("decision", "")).lower()
        for item in safety_risks
    )
    checks = {
        "trigger_known": payload["trigger"] in TRIGGER_POINTS,
        "required_output_fields_present": all(
            key in required for key in REQUIRED_OUTPUT_FIELDS
        ),
        "required_output_fields_nonempty": all(
            bool(required.get(key)) for key in REQUIRED_OUTPUT_FIELDS
        ),
        "keeps_one_minute_cognitive_budget_semantics": (
            "metaminute_seconds" not in payload
            and
            payload["min_required_reflection"] is True
            and payload["intended_cognitive_budget_seconds"] == 60
            and isinstance(payload.get("actual_elapsed_seconds"), (int, float))
            and payload["actual_elapsed_seconds"] >= 0
            and bool(payload.get("early_exit_reason"))
            and payload["early_exit_allowed"] is True
            and payload["mechanical_sleep_required"] is False
            and payload["bounded_checkpoint_not_pause"] is True
            and payload["completeness_check_passed"] is True
            and bool(highest_ev.get("action"))
        ),
        "possible_misroute_present": bool(required.get("possible_misroute_or_old_gate")),
        "highest_ev_next_action_nonempty": bool(highest_ev.get("action")),
        "report_pass_final_not_stop_condition": (
            report_stop_risk_denied
            and payload.get("report_pass_final_as_stop_condition_allowed") is False
            and payload.get("report_stop_allowed") is False
        ),
        "mature_patterns_recorded": len(payload["mature_pattern_refs"]) >= 8,
        "continues_or_names_blocker": required["continue_or_named_blocker"] == "continue"
        or str(required["continue_or_named_blocker"]).startswith("BLOCKER:"),
        "default_parallelism_surface_present": any(
            "default_parallelism_policy" in surface
            for surface in required["active_authority_surfaces"]
        ),
        "no_completion_claim": payload["completion_claim_allowed"] is False,
        "not_execution_controller": payload["not_execution_controller"] is True,
        "default_trigger_points_bound": all(
            trigger in payload.get("default_hot_path_triggers", {})
            for trigger in TRIGGER_POINTS
        ),
        "global_self_prelude_present": (
            isinstance(payload.get("global_self_prelude"), dict)
            and payload["global_self_prelude"].get("scope")
            == "global_always_on_for_codex_s"
            and payload["global_self_prelude"].get("keyword_required") is False
            and bool(payload["global_self_prelude"].get("prompt_zh"))
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "validated_at": now_iso(),
    }


def output_paths(repo_root: Path, runtime_root: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(
            runtime_root / "state" / "metaminute_preflight_reflection" / "latest.json"
        ),
        "global_self_prelude_latest": str(
            runtime_root / "state" / "codex_s_global_self_prelude" / "latest.json"
        ),
        "global_self_prelude_prompt": str(
            runtime_root / "state" / "codex_s_global_self_prelude" / "latest.prompt.md"
        ),
        "runtime_readback_zh": str(
            runtime_root
            / "readback"
            / "zh"
            / "metaminute_preflight_reflection_20260702.md"
        ),
        "repo_readback": str(
            repo_root
            / "docs"
            / "current"
            / "CODEX_S_METAMINUTE_PREFLIGHT_REFLECTION_2026-07-02.md"
        ),
    }


def build(
    *,
    trigger: str = "window_start_first_hop",
    current_user_object: str = "Seed Cortex Phase 0 current task",
    latest_user_delta: str = "restore runtime facts and choose highest-EV next machine action",
    repo_root: str | Path = DEFAULT_REPO,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    write: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    repo = Path(repo_root)
    runtime = Path(runtime_root)
    generated_at = now_iso()
    paths = output_paths(repo, runtime)
    required = required_output(
        trigger=trigger,
        current_user_object=current_user_object,
        latest_user_delta=latest_user_delta,
        runtime_root=runtime,
    )
    self_prelude = global_self_prelude()
    completeness_check_passed = all(
        bool(required.get(key))
        for key in (
            "current_user_object",
            "latest_user_delta",
            "active_authority_surfaces",
            "possible_misroute_or_old_gate",
            "safety_template_or_report_stop_risk",
            "what_can_machine_do_now",
            "highest_ev_next_action",
            "continue_or_named_blocker",
        )
    ) and bool(required["highest_ev_next_action"].get("action"))
    actual_elapsed_seconds = round(time.perf_counter() - started, 4)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "node_id": "metaminute_preflight_reflection",
        "status": "metaminute_preflight_checkpoint_ready",
        "trigger": trigger,
        "trigger_points": TRIGGER_POINTS,
        "generated_at": generated_at,
        "min_required_reflection": True,
        "intended_cognitive_budget_seconds": 60,
        "actual_elapsed_seconds": actual_elapsed_seconds,
        "early_exit_allowed": True,
        "early_exit_reason": (
            "structured_fields_complete_and_next_machine_action_non_empty"
            if completeness_check_passed
            else "not_applicable_incomplete_checkpoint"
        ),
        "completeness_check_passed": completeness_check_passed,
        "mechanical_sleep_required": False,
        "bounded_checkpoint_not_pause": True,
        "time_wait_required": False,
        "not_plain_checklist": True,
        "report_pass_final_as_stop_condition_allowed": False,
        "report_stop_allowed": False,
        "cognitive_budget_semantics": (
            "preserve a one-minute no-interruption metacognitive budget; "
            "engineering may early-exit only after structured fields are complete and next_machine_action is non-empty"
        ),
        "mature_pattern_refs": MATURE_PATTERN_REFS,
        "global_self_prelude": self_prelude,
        "required_output": required,
        "runtime_refs": runtime_refs(runtime),
        "dp_search_parallel_fan_in_refs": dp_search_fan_in_refs(runtime),
        "default_hot_path_triggers": {
            "window_start_first_hop": "C:\\Users\\xx363\\.codex-seed-cortex\\hooks.json#/hooks/SessionStart -> scripts/hardmode/Invoke-CodexSMetaMinutePreflight.ps1",
            "after_gate_hook_deny": "scripts/hardmode/Invoke-CodexSSideAuditHook.ps1 blocking branch -> Invoke-CodexSMetaMinutePreflight.ps1 -Trigger after_gate_hook_deny",
            "before_final_pass_report": "C:\\Users\\xx363\\.codex-seed-cortex\\hooks.json#/hooks/Stop -> scripts/hardmode/Invoke-CodexSMetaMinutePreflight.ps1",
            "before_new_parallel_wave": "services/agent_runtime/default_max_parallel_policy.py -> build_default_max_parallel_policy pre-dispatch MetaMinute checkpoint",
        },
        "policy": {
            "when_to_run": TRIGGER_POINTS,
            "must_not_be": [
                "prompt_only_calm_down_instruction",
                "time_based_sleep_gate",
                "completion_decision_engine",
                "execution_controller",
            ],
            "must_emit": [
                "current_user_object",
                "latest_user_delta",
                "active_authority_surfaces",
                "possible_misroute_or_old_gate",
                "what_can_machine_do_now",
                "highest_ev_next_action",
                "continue_or_named_blocker",
            ],
            "parallel_integration": (
                "before_new_parallel_wave must call the default max-benefit frontier policy "
                "and fan-in results before fact promotion"
            ),
        },
        "output_paths": paths,
        **boundary_fields(),
    }
    payload["validation"] = build_validation(payload)
    if write:
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["global_self_prelude_latest"]), self_prelude)
        write_text(Path(paths["global_self_prelude_prompt"]), self_prelude["prompt_zh"] + "\n")
        readback = render_readback(payload)
        write_text(Path(paths["runtime_readback_zh"]), readback)
        write_text(Path(paths["repo_readback"]), readback)
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    required = payload["required_output"]
    lines = [
        "# Codex S MetaMinute / PreflightReflection readback",
        "",
        "SENTINEL:CODEX_S_METAMINUTE_PREFLIGHT_REFLECTION_20260702",
        "",
        "## 当前作用",
        "",
        "MetaMinute 已落成 runtime checkpoint。它保留“一分钟元思考”的认知预算语义，但不是机械 sleep；只有结构化字段完整且下一机器动作非空时才允许提前通过。",
        "",
        f"- trigger：`{payload['trigger']}`",
        f"- intended_cognitive_budget_seconds：{payload['intended_cognitive_budget_seconds']}",
        f"- actual_elapsed_seconds：{payload['actual_elapsed_seconds']}",
        f"- early_exit_allowed：{payload['early_exit_allowed']}",
        f"- early_exit_reason：{payload['early_exit_reason']}",
        f"- completeness_check_passed：{payload['completeness_check_passed']}",
        f"- 当前对象：{required['current_user_object']}",
        f"- 最新用户增量：{required['latest_user_delta']}",
        f"- 下一机器动作：{required['highest_ev_next_action']['action']}",
        f"- continue_or_named_blocker：{required['continue_or_named_blocker']}",
        f"- 全局 Codex self-prelude：{payload['global_self_prelude']['prompt_zh']}",
        "",
        "## 证据路径",
        "",
        f"- D latest：`{payload['output_paths']['runtime_latest']}`",
        f"- 全局 self-prelude latest：`{payload['output_paths']['global_self_prelude_latest']}`",
        f"- 全局 self-prelude prompt：`{payload['output_paths']['global_self_prelude_prompt']}`",
        f"- D 中文 readback：`{payload['output_paths']['runtime_readback_zh']}`",
        f"- E repo readback：`{payload['output_paths']['repo_readback']}`",
        "- 验证入口：`tests/seedcortex/test_metaminute_preflight_reflection.py` 和 `scripts/verify_metaminute_preflight_reflection.ps1`",
        "",
        "## 不允许",
        "",
        "- 不允许把它变成 prompt-only 的“冷静一分钟”。",
        "- 不允许把它缩水成 `metaminute_seconds=0` 或普通 checklist。",
        "- 不允许把它变成 completion gate、事实源或执行控制器。",
        "- 不允许用旧 A/B/C/CLEAN gate 覆盖 S 当前对象。",
        "- 不允许在 final/report/PASS 前跳过 fan-in acceptance。",
        "",
        "## 成熟模式吸收",
        "",
    ]
    for ref in payload["mature_pattern_refs"]:
        lines.append(f"- `{ref['pattern_id']}` -> {ref['absorbed_as']}")
    lines.extend(["", payload["sentinel"]])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", choices=TRIGGER_POINTS, default="window_start_first_hop")
    parser.add_argument("--current-user-object", default="Seed Cortex Phase 0 current task")
    parser.add_argument(
        "--latest-user-delta",
        default="restore runtime facts and choose highest-EV next machine action",
    )
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--validate-file", default="")
    args = parser.parse_args()
    if args.validate_file:
        candidate = json.loads(Path(args.validate_file).read_text(encoding="utf-8"))
        validation = validate_payload(candidate)
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 0 if validation["passed"] else 1
    payload = build(
        trigger=args.trigger,
        current_user_object=args.current_user_object,
        latest_user_delta=args.latest_user_delta,
        repo_root=args.repo_root,
        runtime_root=args.runtime_root,
        write=True,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "trigger": payload["trigger"],
                "validation_passed": payload["validation"]["passed"],
                "runtime_latest": payload["output_paths"]["runtime_latest"],
                "global_self_prelude_latest": payload["output_paths"]["global_self_prelude_latest"],
                "global_self_prelude_prompt": payload["output_paths"]["global_self_prelude_prompt"],
                "runtime_readback_zh": payload["output_paths"]["runtime_readback_zh"],
                "repo_readback": payload["output_paths"]["repo_readback"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(payload["sentinel"])
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
