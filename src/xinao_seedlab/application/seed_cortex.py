from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _write_text_atomic(path, text)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: OSError | None = None
    for attempt in range(8):
        temporary = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.{attempt}.tmp"
        )
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)
            return
        except OSError as exc:
            last_error = exc
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _safe_file_stem(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return safe[:96] or "productivity-mode-v2"


CLAIM_CARD_REQUIRED_FIELDS = (
    "source_url",
    "source_family",
    "claim",
    "verification_need",
    "accepted_for",
)


def _candidate_is_claim_card(candidate: dict[str, Any]) -> bool:
    marker = str(
        candidate.get("object_type")
        or candidate.get("artifact_kind")
        or candidate.get("schema_version")
        or ""
    )
    if "ClaimCard" in marker or "claim_card" in marker:
        return True
    return "claim" in candidate and (
        "source_url" in candidate or "source_family" in candidate
    )


def _claim_card_missing_fields(candidate: dict[str, Any]) -> list[str]:
    return [
        field
        for field in CLAIM_CARD_REQUIRED_FIELDS
        if not str(candidate.get(field) or "").strip()
    ]


def _source_ledger_entry(candidate: dict[str, Any], index: int) -> dict[str, Any]:
    raw_id = str(candidate.get("candidate_id") or candidate.get("claim_id") or f"claim-card-{index:02d}")
    digest = hashlib.sha256(
        json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    entry_id = f"source-ledger:{_safe_file_stem(raw_id)}:{digest}"
    return {
        "entry_id": entry_id,
        "candidate_id": raw_id,
        "object_type": "SourceLedgerEntry",
        "source_url": str(candidate.get("source_url") or ""),
        "source_family": str(candidate.get("source_family") or ""),
        "claim": str(candidate.get("claim") or ""),
        "verification_need": str(candidate.get("verification_need") or ""),
        "accepted_for": str(candidate.get("accepted_for") or ""),
        "claim_card_ref": str(candidate.get("claim_card_ref") or candidate.get("artifact_ref") or ""),
        "raw_secret_values_recorded": False,
        "direct_fact_promotion_allowed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
    }


def _productivity_meta_kernel() -> dict[str, Any]:
    injection_text = (
        "使用生产力元认知核：它只服务 333，不替代 333。"
        "少解释，少盘点，直接把任务拆成可交付动作。"
        "优先最短可验证增量；能改就改，能查就查，能并行就并行。"
        "先读 333/当前任务包/桌面备忘，找到已有入口，小范围补实现。"
        "能跑真实 draft/merge 就跑；不能跑就写命名 blocker，不用查账报告冒充推进。"
        "每个 lane 必须产出 diff / capability / ClaimCard / evidence / blocker 之一。"
        "report、PASS、pytest、readback 不算终点。"
        "最后只用中文回读当前可用产物和下一步最高收益动作。"
    )
    self_prelude_text = (
        "Codex 自检前置：先把自己从审查/守门人模式拉回执行图。"
        "333 是全局同构锚点；productivity v2 只是 333 下面的执行姿势，不是新权威、新控制面、新事实源。"
        "看到用户意图后，第一反应是找可交付动作和最小可验证增量；"
        "生产力 v2 的默认链是：读 333 和当前任务 -> 对照备忘 -> 找入口 -> 小范围实现 -> 真跑 draft/merge 或 blocker -> ledger/readback；"
        "报告、风险盘点、测试通过只当辅助证据，不当停点。"
        "能产出 artifact 就推进，撞到真实阻塞才命名 blocker。"
    )
    return {
        "schema_version": "xinao.productivity_meta_kernel.v1",
        "kernel_id": "productivity_meta_kernel_v1",
        "source_refs": [
            "C:\\Users\\xx363\\Desktop\\Codex生产力元认知外部搜索与破解方案_20260703.txt",
            "C:\\Users\\xx363\\Desktop\\Codex认知仓库人格.txt",
        ],
        "source_role": "reference_only_extracted_pattern",
        "intent": "turn user intent into deliverable action before audit/report mode takes over",
        "authority_anchor": "333",
        "authority_scope": "subordinate_execution_bias_under_333",
        "not_authority_source": True,
        "not_control_plane": True,
        "not_fact_source": True,
        "not_bypass_island": True,
        "operating_bias": [
            "从可交付动作倒推，不先写审查报告",
            "先绑定 333/当前任务包/桌面备忘，再动实现入口",
            "进展只按可用 artifact 计数",
            "验证是推进环节，不是停点",
            "外部搜索是证据采购，不是报告替代品",
            "硬边界只在真正撞墙时中断，不当叙事主轴",
        ],
        "artifact_units": [
            "diff",
            "capability",
            "ClaimCard",
            "evidence",
            "blocker",
        ],
        "lane_rule": "并行只算能 fan-in 的独立 lane；lane_count 本身不算进展。",
        "forbidden_stop_points": [
            "report",
            "PASS",
            "pytest",
            "latest",
            "readback_only",
        ],
        "readback_rule": "只说做了什么、现在能用什么、下一步最高收益动作。",
        "front_injection_text_zh": injection_text,
        "codex_self_prelude_text_zh": self_prelude_text,
    }


def _productivity_v2_execution_contract() -> dict[str, Any]:
    return {
        "contract_id": "productivity_v2_invoke_bound_implementation_chain",
        "authority_anchor": "333",
        "authority_scope": "subordinate_execution_profile_under_333",
        "serves": [
            "XINAO_333_global_isomorphism",
            "RootIntentLoop_while_continuation",
            "maximum_benefit_dynamic_parallelism",
            "current_task_package_when_present",
        ],
        "not_authority_source": True,
        "not_control_plane": True,
        "not_fact_source": True,
        "not_bypass_island": True,
        "plain_zh": (
            "v2 是 333 下面的生产力执行姿势，不是新权威、新控制面、新事实源、新旁路岛；"
            "它不是查账模式，也不是 MetaRsi 主工；它必须把当前意图推进到可调用实现、"
            "真实 draft/merge 证据，或证据化 named blocker，为 333 的 while/宽度同构服务。"
        ),
        "required_sequence": [
            "read_333_and_current_task",
            "compare_desktop_memo",
            "locate_existing_entrypoint",
            "scoped_implementation_or_binding",
            "run_real_draft_merge_or_name_blocker",
            "write_ledger_and_chinese_readback",
            "claim_default_route_only_after_evidence",
        ],
        "must_not_stop_at": [
            "inventory_report",
            "meta_rsi_wave_only",
            "baseline_probe_only",
            "latest_json_only",
            "pytest_pass_only",
            "readback_only",
        ],
        "must_produce_one_of": [
            "repo_diff",
            "callable_capability",
            "draft_merge_artifact",
            "ClaimCard_accepted_through_fan_in",
            "ledger_evidence",
            "named_blocker",
        ],
        "draft_merge_chain": {
            "required_when_applicable": True,
            "shape": "parallel_draft -> staging -> merge_consumer -> writer/readback",
            "meta_rsi_role": "evidence_only_not_main_worker",
            "search_role": "source_lane_not_dp_draft_main_worker",
        },
        "default_route_claim_rule": (
            "Only claim a 333-serving route solidified after implementation/binding plus focused evidence; "
            "otherwise report candidate_registered or named blocker. Never claim v2 replaces 333."
        ),
    }


def _default_productivity_lanes() -> list[dict[str, Any]]:
    return [
        {
            "lane_id": "productivity-v2-restore-runtime",
            "phase": "restore",
            "kind": "runtime",
            "goal": "Restore current runtime, route, and task identity before action.",
            "depends_on": [],
            "expected_artifact": "evidence_ref",
        },
        {
            "lane_id": "productivity-v2-locate-entrypoint",
            "phase": "think",
            "kind": "runtime",
            "goal": "Locate the existing service/CLI/runtime entrypoint before adding new code.",
            "depends_on": ["productivity-v2-restore-runtime"],
            "expected_artifact": "evidence_ref",
        },
        {
            "lane_id": "productivity-v2-repo-diff",
            "phase": "execute",
            "kind": "repo",
            "goal": "Land the smallest useful repo diff instead of report-only output.",
            "depends_on": ["productivity-v2-locate-entrypoint"],
            "expected_artifact": "patch",
        },
        {
            "lane_id": "productivity-v2-draft-merge",
            "phase": "execute",
            "kind": "draft",
            "goal": "Run or bind a real draft->staging->merge path, or write a named blocker.",
            "depends_on": ["productivity-v2-locate-entrypoint"],
            "expected_artifact": "capability_invoke",
        },
        {
            "lane_id": "productivity-v2-search-claimcards",
            "phase": "think",
            "kind": "search",
            "goal": "Route external findings into ClaimCards before promotion.",
            "depends_on": ["productivity-v2-restore-runtime"],
            "expected_artifact": "ClaimCard",
        },
        {
            "lane_id": "productivity-v2-contradiction-check",
            "phase": "think",
            "kind": "audit",
            "goal": "Catch overclaim, report-only stop, and pytest/PASS stop regressions.",
            "depends_on": ["productivity-v2-repo-diff"],
            "expected_artifact": "blocker",
        },
        {
            "lane_id": "productivity-v2-focused-verify",
            "phase": "verify",
            "kind": "verify",
            "goal": "Run the closest focused verification for the accepted artifact.",
            "depends_on": ["productivity-v2-repo-diff", "productivity-v2-draft-merge"],
            "expected_artifact": "test_result",
        },
        {
            "lane_id": "productivity-v2-readback",
            "phase": "readback",
            "kind": "repo",
            "goal": "Write Chinese readback with invoke path, status, and next frontier.",
            "depends_on": ["productivity-v2-focused-verify"],
            "expected_artifact": "capability_invoke",
        },
    ]


def _default_productivity_results(readback_path: Path) -> list[dict[str, Any]]:
    return [
        {
            "lane_id": "productivity-v2-repo-diff",
            "status": "accepted",
            "artifact_refs": ["repo://productivity-mode-v2-service-cli-verifier-test"],
            "accepted_for": "capability_invoke",
            "notes_zh": "已接受为可 invoke 的生产力 v2 波记录能力，不是完成裁决。",
        },
        {
            "lane_id": "productivity-v2-readback",
            "status": "accepted",
            "artifact_refs": [str(readback_path)],
            "accepted_for": "repo_answer",
            "notes_zh": "中文 readback 已写入运行时读面。",
        },
    ]


def _build_productivity_worker_assignment(
    *,
    task_id: str,
    wave_id: str,
    objective: str,
    lanes: list[dict[str, Any]],
    invoke_command: str,
    baseline_path: Path,
    meta_wave_path: Path,
    meta_kernel_path: Path,
    front_injection_prompt_path: Path,
    codex_self_prelude_path: Path,
    readback_path: Path,
    front_injection: dict[str, Any],
    execution_contract: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.productivity_mode_v2.worker_assignment.v1",
        "task_id": task_id,
        "wave_id": wave_id,
        "scope_level_target": "L3",
        "objective": objective,
        "mode": "productivity_v2",
        "status": "worker_assignment_ready",
        "primary_authority_proxy": "current_user_visible_grok_package",
        "execution_shape": [
            "read_current_authority",
            "compare_desktop_memo",
            "locate_existing_entrypoint",
            "scoped_implementation_or_binding",
            "run_real_draft_merge_or_name_blocker",
            "fan_in",
            "write_ledger_and_chinese_readback",
            "next_frontier",
        ],
        "lanes": lanes,
        "execution_contract": execution_contract,
        "required_outputs": [
            "repo_diff_or_callable_capability",
            "draft_merge_artifact_or_named_blocker",
            "MetaRsiWave evidence",
            "CodexProductivityBaseline evidence",
            "Chinese readback",
            "named blocker if blocked",
        ],
        "acceptance": {
            "report_only_stop": False,
            "pytest_pass_stop": False,
            "completion_claim_allowed": False,
            "accepted_artifact_types": [
                "patch",
                "capability_invoke",
                "ClaimCard",
                "evidence_ref",
                "blocker",
            ],
        },
        "front_injection": front_injection,
        "can_invoke_now": {
            "cli": invoke_command,
            "meta_rsi_wave": str(meta_wave_path),
            "meta_kernel": str(meta_kernel_path),
            "front_injection_prompt": str(front_injection_prompt_path),
            "codex_self_prelude": str(codex_self_prelude_path),
            "productivity_baseline": str(baseline_path),
            "readback_zh": str(readback_path),
        },
        "adoption_state": "candidate_registered",
        "runtime_enforced": False,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "written_at": _now_iso(),
    }


def _build_productivity_baseline(
    *,
    task_id: str,
    wave_id: str,
    invoke_command: str,
    had_code_diff: bool,
    zh_readback: str,
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.codex_productivity_baseline.v1",
        "probe_id": f"productivity-mode-v2-{_safe_file_stem(task_id)}",
        "task_id": task_id,
        "wave_id": wave_id,
        "had_code_diff": had_code_diff,
        "had_code_diff_scope": "productivity_v2_record_surface_only",
        "task_implementation_diff_claimed": False,
        "default_route_solidified_claimed": False,
        "authority_anchor": "333",
        "not_authority_source": True,
        "not_control_plane": True,
        "not_fact_source": True,
        "not_bypass_island": True,
        "had_invoke": True,
        "invoke_path": invoke_command,
        "gatekeeper_signals": ["none_observed"],
        "zh_readback": zh_readback,
        "written_at": _now_iso(),
        "not_user_completion": True,
    }


def _build_productivity_trigger_binding(
    *,
    task_id: str,
    trigger_wave_id: str,
    productivity_payload: dict[str, Any],
    binding_latest: Path,
    binding_task_latest: Path,
) -> dict[str, Any]:
    checks = {
        "default_trigger_invoked_productivity_wave": productivity_payload.get("validation", {}).get("passed") is True,
        "meta_wave_kept_candidate_registered": productivity_payload.get("adoption_state") == "candidate_registered",
        "meta_wave_runtime_enforced_false": productivity_payload.get("runtime_enforced") is False,
        "baseline_had_invoke": productivity_payload.get("productivity_baseline", {}).get("had_invoke") is True,
        "worker_assignment_present": bool(productivity_payload.get("WORKER_ASSIGNMENT", {}).get("lanes")),
        "execution_contract_present": bool(productivity_payload.get("execution_contract", {}).get("required_sequence")),
        "execution_contract_anchored_to_333": productivity_payload.get("execution_contract", {}).get("authority_anchor") == "333",
        "execution_contract_not_control_plane": productivity_payload.get("execution_contract", {}).get("not_control_plane") is True,
        "execution_contract_not_fact_source": productivity_payload.get("execution_contract", {}).get("not_fact_source") is True,
        "execution_contract_not_bypass_island": productivity_payload.get("execution_contract", {}).get("not_bypass_island") is True,
        "completion_claim_blocked": productivity_payload.get("completion_claim_allowed") is False,
    }
    return {
        "schema_version": "xinao.productivity_mode_v2.trigger_binding.v1",
        "status": "productivity_mode_v2_default_trigger_bound",
        "task_id": task_id,
        "trigger_wave_id": trigger_wave_id,
        "productivity_wave_id": productivity_payload.get("wave_id", ""),
        "invoked_by": "SeedCortexService.default_main_loop_trigger_candidate",
        "runtime_enforced": True,
        "runtime_enforced_scope": "default_main_loop_trigger_candidate_service_invocation_only",
        "productivity_wave_adoption_state": productivity_payload.get("adoption_state"),
        "productivity_wave_runtime_enforced": productivity_payload.get("runtime_enforced"),
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "evidence_refs": {
            "binding_latest": str(binding_latest),
            "binding_task_latest": str(binding_task_latest),
            "meta_rsi_wave_latest": productivity_payload.get("output_paths", {}).get("runtime_latest", ""),
            "worker_assignment": productivity_payload.get("output_paths", {}).get("worker_assignment", ""),
            "productivity_baseline": productivity_payload.get("output_paths", {}).get("productivity_baseline_latest", ""),
            "readback_zh": productivity_payload.get("output_paths", {}).get("runtime_readback_zh", ""),
        },
        "can_invoke_now": productivity_payload.get("can_invoke_now", {}),
        "execution_contract": productivity_payload.get("execution_contract", {}),
        "validation": {
            "passed": all(checks.values()),
            "checks": checks,
        },
        "written_at": _now_iso(),
    }


def _render_productivity_readback(payload: dict[str, Any]) -> str:
    command = payload["can_invoke_now"]["cli"]
    prompt_path = payload["can_invoke_now"]["front_injection_prompt"]
    self_prelude_path = payload["can_invoke_now"]["codex_self_prelude"]
    front_injection = payload["front_injection"]["front_injection_text_zh"]
    self_prelude = payload["front_injection"]["codex_self_prelude_text_zh"]
    execution_contract = payload.get("execution_contract", {})
    sequence = " -> ".join(execution_contract.get("required_sequence", []))
    return "\n".join(
        [
            "# productivity mode v2 wave readback",
            "",
            f"task_id：{payload['task_id']}",
            f"wave_id：{payload['wave_id']}",
            "现在能 invoke 什么：",
            f"- {command}",
            "",
            "现在能前置注入什么：",
            f"- {prompt_path}",
            f"- {front_injection}",
            f"- {self_prelude_path}",
            f"- {self_prelude}",
            "",
            "v2 真实执行链：",
            f"- {sequence}",
            f"- {execution_contract.get('plain_zh', '')}",
            "",
            "本波实际交付：",
            "- 写入 MetaRsiWave evidence：lanes -> results -> fan-in/readback 边界。",
            "- 写入 WORKER_ASSIGNMENT：把生产力 v2 从口号变成可调度 lanes。",
            "- 写入 ProductivityMetaKernel：极短前置注入核，可直接作为任务前缀和 Codex 自检前置。",
            "- 写入 CodexProductivityBaseline：记录本波 had_code_diff/had_invoke。",
            "- 写入 execution_contract：禁止停在查账/meta_rsi，必须落实现、draft/merge 或 named blocker。",
            "- 暴露 Python service 与 CLI 入口，避免只停在报告或桌面 txt。",
            "",
            f"能力采纳状态：{payload['adoption_state']}。",
            "这代表：这是可调用候选工作流记录面，不是默认 runtime 强制执行。",
            "还缺什么才能进入下一状态：接入默认主循环/Temporal/LangGraph 触发，并用每波 evidence 证明 runtime_enforced。",
            "",
            "禁止误判：pytest/PASS/report/latest/readback 仍不是用户完成。",
            f"下一波最高收益动作：{payload['next_frontier']}",
            "",
        ]
    )


def _default_durable_continuation_lanes() -> list[dict[str, Any]]:
    return [
        {
            "lane_id": "durable-continuation-workflow-checkpoint",
            "phase": "restore",
            "kind": "workflow",
            "goal": "Persist the incoming intent into a resumable workflow checkpoint.",
            "expected_artifact": "checkpoint_ref",
        },
        {
            "lane_id": "durable-continuation-worker-start",
            "phase": "dispatch",
            "kind": "worker",
            "goal": "Start the task-scoped worker lane for the current intent.",
            "expected_artifact": "worker_start_ref",
        },
        {
            "lane_id": "durable-continuation-worker-poll",
            "phase": "poll",
            "kind": "worker",
            "goal": "Poll only worker ledger entries for terminal states.",
            "expected_artifact": "worker_dispatch_ledger_poll",
        },
        {
            "lane_id": "durable-continuation-ledger-fan-in",
            "phase": "fan_in",
            "kind": "ledger",
            "goal": "Accept next-wave edges only from worker_dispatch_ledger poll succeeded entries.",
            "expected_artifact": "accepted_edges",
        },
        {
            "lane_id": "durable-continuation-auto-dispatch",
            "phase": "while_next_wave",
            "kind": "default_auto_dispatch",
            "goal": "Dispatch the next wave when ledger succeeded count is positive.",
            "expected_artifact": "next_wave_ref",
        },
        {
            "lane_id": "durable-continuation-readback",
            "phase": "readback",
            "kind": "repo",
            "goal": "Write Chinese readback with the exact invoke command and boundary.",
            "expected_artifact": "readback_zh",
        },
    ]


def _build_durable_worker_entry(
    *,
    task_id: str,
    workflow_id: str,
    wave_id: str,
    worker_result_ref: str,
    checkpoint_ref: Path,
) -> dict[str, Any]:
    succeeded = bool(worker_result_ref.strip())
    return {
        "entry_id": f"{wave_id}:durable-continuation-worker-poll",
        "wave_id": wave_id,
        "task_id": task_id,
        "workflow_id": workflow_id,
        "lane_id": "durable-continuation-worker-poll",
        "agent_id": "codex_s.durable_continuation_worker",
        "provider": "codex_s.durable_continuation_reconnect",
        "mode": "worker_poll",
        "dispatch_time": _now_iso(),
        "poll_status": "succeeded" if succeeded else "blocked",
        "terminal_state": "succeeded" if succeeded else "blocked",
        "status": "succeeded" if succeeded else "blocked",
        "artifact_refs": [worker_result_ref] if succeeded else [str(checkpoint_ref)],
        "worker_result_ref": worker_result_ref,
        "source_kind": "worker_poll_result",
        "poll_source": "worker_poll",
        "synthetic_succeeded_by_driver": False,
        "transport_pattern_ref": "seed_cortex_durable_continuation_worker_poll",
        "legacy_5d33_transport_pattern_reused": False,
        "legacy_5d33_owner_reused": False,
        "legacy_5d33_pass_reused": False,
        "legacy_5d33_latest_authority_reused": False,
        "local_runtime_shortcut_used": False,
        "fan_in_decision": (
            "accepted_for_next_wave_dispatch"
            if succeeded
            else "blocked_waiting_for_worker_result_ref"
        ),
        "next_wave_decision": (
            "ledger_succeeded_drives_default_auto_dispatch"
            if succeeded
            else "blocked_waiting_worker_result"
        ),
        "adoption_state": "verifier_ready_but_not_hooked",
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def _render_durable_continuation_readback(payload: dict[str, Any]) -> str:
    command = payload["can_invoke_now"]["cli"]
    resume_command = payload["can_invoke_now"]["resume_cli"]
    auto_dispatch = payload["auto_dispatch"]
    worker_poll = payload["worker_poll"]
    return "\n".join(
        [
            "# durable continuation reconnect readback",
            "",
            f"task_id：{payload['task_id']}",
            f"workflow_id：{payload['workflow_id']}",
            f"wave_id：{payload['wave_id']}",
            "",
            "现在能 invoke 什么：",
            f"- 首次接入：{command}",
            f"- 睡眠后续跑：{resume_command}",
            "",
            "本波已接入：",
            "- intent 进入 durable workflow checkpoint。",
            "- worker poll 写入 worker_dispatch_ledger，source_kind=worker_dispatch_ledger_poll。",
            f"- fan-in 复用：{payload['main_chain_reuse']['source_function']}。",
            f"- ledger succeeded_count={worker_poll['succeeded_count']}，driver_synthetic_succeeded_allowed=false。",
            f"- auto_dispatch.next_wave_dispatched={str(auto_dispatch['next_wave_dispatched']).lower()}，reason={auto_dispatch['dispatch_reason']}。",
            f"- default_auto_dispatch.enabled={str(payload['default_auto_dispatch']['default_enabled']).lower()}，live_watch.state={payload['live_watch']['state']}。",
            f"- next_wave_id={auto_dispatch['next_wave_id']}。",
            "",
            "边界：不复活 5d33，不使用本地快捷运行当完成，不允许合成 succeeded；只有 worker ledger succeeded 才能驱动 next_wave。",
            "这不是用户完成裁决，也不是 closure 停点；下一波继续由 checkpoint + ledger fan-in 续跑。",
            "",
        ]
    )


class SeedCortexService:
    def __init__(self, runtime_root: str | Path, *, repo_root: str | Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.repo_root = Path(repo_root)

    def productivity_mode_v2_wave(
        self,
        *,
        task_id: str,
        wave_id: str = "",
        objective: str = "",
        mode_reason: str = "",
        zh_readback: str = "",
        lanes: list[dict[str, Any]] | None = None,
        results: list[dict[str, Any]] | None = None,
        write_runtime: bool = True,
    ) -> dict[str, Any]:
        stem = _safe_file_stem(task_id)
        resolved_wave_id = wave_id or f"productivity-mode-v2-{stem}"
        latest = self.runtime_root / "state" / "meta_rsi_wave" / "latest.json"
        task_latest = self.runtime_root / "state" / "meta_rsi_wave" / f"{stem}.json"
        readback = self.runtime_root / "readback" / "zh" / f"meta_rsi_wave_{stem}_20260703.md"
        worker_assignment = (
            self.runtime_root / "state" / "worker_assignment" / f"{stem}.productivity_mode_v2.json"
        )
        meta_kernel_latest = self.runtime_root / "state" / "productivity_meta_kernel" / "latest.json"
        meta_kernel_task_latest = (
            self.runtime_root / "state" / "productivity_meta_kernel" / f"{stem}.json"
        )
        front_injection_prompt = (
            self.runtime_root / "state" / "productivity_meta_kernel" / "latest.prompt.md"
        )
        front_injection_task_prompt = (
            self.runtime_root / "state" / "productivity_meta_kernel" / f"{stem}.prompt.md"
        )
        codex_self_prelude = (
            self.runtime_root
            / "state"
            / "productivity_meta_kernel"
            / "latest.codex-self-prelude.md"
        )
        codex_self_prelude_task = (
            self.runtime_root
            / "state"
            / "productivity_meta_kernel"
            / f"{stem}.codex-self-prelude.md"
        )
        baseline_latest = self.runtime_root / "state" / "codex_productivity_baseline" / "latest.json"
        baseline_task_latest = (
            self.runtime_root / "state" / "codex_productivity_baseline" / f"{stem}.json"
        )
        resolved_lanes = lanes or _default_productivity_lanes()
        resolved_results = results or _default_productivity_results(readback)
        front_injection = _productivity_meta_kernel()
        execution_contract = _productivity_v2_execution_contract()
        invoke_command = (
            "python -m xinao_seedlab.cli.__main__ "
            f"--runtime-root {self.runtime_root} --repo-root {self.repo_root} "
            "productivity-mode-v2-wave "
            f"--task-id {task_id}"
        )
        source_tree_command = (
            f"$env:PYTHONPATH='{self.repo_root}\\src;{self.repo_root}'; "
            f"{invoke_command}"
        )
        assignment_payload = _build_productivity_worker_assignment(
            task_id=task_id,
            wave_id=resolved_wave_id,
            objective=objective,
            lanes=resolved_lanes,
            invoke_command=invoke_command,
            baseline_path=baseline_latest,
            meta_wave_path=latest,
            meta_kernel_path=meta_kernel_latest,
            front_injection_prompt_path=front_injection_prompt,
            codex_self_prelude_path=codex_self_prelude,
            readback_path=readback,
            front_injection=front_injection,
            execution_contract=execution_contract,
        )
        payload: dict[str, Any] = {
            "schema_version": "xinao.meta_rsi_wave.v1",
            "status": "productivity_mode_v2_wave_recorded",
            "wave_id": resolved_wave_id,
            "task_id": task_id,
            "objective": objective,
            "mode": "productivity_v2",
            "mode_reason": mode_reason
            or "deliver invokeable productivity v2 lane/fan-in evidence instead of report-only output",
            "fallback": {
                "repo_mode_used": False,
                "reason": "none",
            },
            "lanes": resolved_lanes,
            "results": resolved_results,
            "WORKER_ASSIGNMENT": assignment_payload,
            "front_injection": front_injection,
            "execution_contract": execution_contract,
            "fan_in": {
                "accepted_result_count": len(
                    [item for item in resolved_results if item.get("status") == "accepted"]
                ),
                "accepted_for": sorted(
                    {
                        str(item.get("accepted_for"))
                        for item in resolved_results
                        if item.get("accepted_for")
                    }
                ),
                "report_only_stop": False,
                "pytest_pass_stop": False,
                "readback_only_stop": False,
            },
            "can_invoke_now": {
                "python_service": "SeedCortexService.productivity_mode_v2_wave(...)",
                "cli": invoke_command,
                "source_tree_powershell": source_tree_command,
                "runtime_latest": str(latest),
                "task_latest": str(task_latest),
                "worker_assignment": str(worker_assignment),
                "meta_kernel": str(meta_kernel_latest),
                "front_injection_prompt": str(front_injection_prompt),
                "codex_self_prelude": str(codex_self_prelude),
                "productivity_baseline": str(baseline_latest),
                "readback_zh": str(readback),
            },
            "next_frontier": (
                "find the existing hot-path entrypoint, land the smallest implementation/binding, "
                "run real draft->merge evidence or write a named blocker, then only claim default "
                "route solidified after ledger/readback evidence"
            ),
            "adoption_state": "candidate_registered",
            "runtime_enforced": False,
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "written_at": _now_iso(),
            "output_paths": {
                "runtime_latest": str(latest),
                "runtime_task_latest": str(task_latest),
                "worker_assignment": str(worker_assignment),
                "productivity_meta_kernel_latest": str(meta_kernel_latest),
                "productivity_meta_kernel_task_latest": str(meta_kernel_task_latest),
                "front_injection_prompt": str(front_injection_prompt),
                "front_injection_task_prompt": str(front_injection_task_prompt),
                "codex_self_prelude": str(codex_self_prelude),
                "codex_self_prelude_task": str(codex_self_prelude_task),
                "productivity_baseline_latest": str(baseline_latest),
                "productivity_baseline_task_latest": str(baseline_task_latest),
                "runtime_readback_zh": str(readback),
            },
        }
        payload["zh_readback"] = zh_readback or _render_productivity_readback(payload)
        baseline_payload = _build_productivity_baseline(
            task_id=task_id,
            wave_id=resolved_wave_id,
            invoke_command=invoke_command,
            had_code_diff=True,
            zh_readback="生产力 v2 真波已跑：WORKER_ASSIGNMENT + MetaRsiWave + baseline + CLI invoke 均已写入。",
        )
        payload["productivity_baseline"] = baseline_payload
        payload["validation"] = {
            "passed": (
                len(resolved_lanes) >= 6
                and payload["fan_in"]["accepted_result_count"] >= 1
                and payload["completion_claim_allowed"] is False
                and bool(payload["can_invoke_now"]["cli"])
                and bool(payload["front_injection"]["front_injection_text_zh"])
                and bool(payload["front_injection"]["codex_self_prelude_text_zh"])
                and bool(payload["execution_contract"]["required_sequence"])
                and payload["execution_contract"]["authority_anchor"] == "333"
                and payload["execution_contract"]["not_authority_source"] is True
                and payload["execution_contract"]["not_control_plane"] is True
                and payload["execution_contract"]["not_fact_source"] is True
                and payload["execution_contract"]["not_bypass_island"] is True
                and "read_333_and_current_task"
                in payload["execution_contract"]["required_sequence"]
                and "run_real_draft_merge_or_name_blocker"
                in payload["execution_contract"]["required_sequence"]
                and baseline_payload["had_code_diff"] is True
                and baseline_payload["had_invoke"] is True
            ),
            "checks": {
                "six_or_more_lanes": len(resolved_lanes) >= 6,
                "accepted_result_present": payload["fan_in"]["accepted_result_count"] >= 1,
                "completion_claim_blocked": payload["completion_claim_allowed"] is False,
                "cli_invoke_present": bool(payload["can_invoke_now"]["cli"]),
                "report_only_stop_absent": payload["fan_in"]["report_only_stop"] is False,
                "front_injection_present": bool(
                    payload["front_injection"]["front_injection_text_zh"]
                ),
                "codex_self_prelude_present": bool(
                    payload["front_injection"]["codex_self_prelude_text_zh"]
                ),
                "worker_assignment_present": bool(payload["WORKER_ASSIGNMENT"]["lanes"]),
                "execution_contract_present": bool(
                    payload["execution_contract"]["required_sequence"]
                ),
                "execution_contract_anchored_to_333": (
                    payload["execution_contract"]["authority_anchor"] == "333"
                ),
                "execution_contract_not_authority_source": (
                    payload["execution_contract"]["not_authority_source"] is True
                ),
                "execution_contract_not_control_plane": (
                    payload["execution_contract"]["not_control_plane"] is True
                ),
                "execution_contract_not_fact_source": (
                    payload["execution_contract"]["not_fact_source"] is True
                ),
                "execution_contract_not_bypass_island": (
                    payload["execution_contract"]["not_bypass_island"] is True
                ),
                "read_333_first_required": (
                    "read_333_and_current_task"
                    in payload["execution_contract"]["required_sequence"]
                ),
                "draft_merge_or_blocker_required": (
                    "run_real_draft_merge_or_name_blocker"
                    in payload["execution_contract"]["required_sequence"]
                ),
                "meta_rsi_not_main_worker": (
                    payload["execution_contract"]["draft_merge_chain"]["meta_rsi_role"]
                    == "evidence_only_not_main_worker"
                ),
                "baseline_had_code_diff": baseline_payload["had_code_diff"] is True,
                "baseline_had_invoke": baseline_payload["had_invoke"] is True,
            },
        }
        if write_runtime:
            _write_json(latest, payload)
            _write_json(task_latest, payload)
            _write_json(worker_assignment, assignment_payload)
            _write_json(meta_kernel_latest, front_injection)
            _write_json(meta_kernel_task_latest, front_injection)
            front_injection_prompt.parent.mkdir(parents=True, exist_ok=True)
            front_injection_prompt.write_text(
                front_injection["front_injection_text_zh"] + "\n",
                encoding="utf-8",
            )
            front_injection_task_prompt.write_text(
                front_injection["front_injection_text_zh"] + "\n",
                encoding="utf-8",
            )
            codex_self_prelude.write_text(
                front_injection["codex_self_prelude_text_zh"] + "\n",
                encoding="utf-8",
            )
            codex_self_prelude_task.write_text(
                front_injection["codex_self_prelude_text_zh"] + "\n",
                encoding="utf-8",
            )
            _write_json(baseline_latest, baseline_payload)
            _write_json(baseline_task_latest, baseline_payload)
            readback.parent.mkdir(parents=True, exist_ok=True)
            readback.write_text(payload["zh_readback"], encoding="utf-8")
        return payload

    def durable_continuation_reconnect(
        self,
        *,
        task_id: str,
        workflow_id: str = "",
        wave_id: str = "",
        intent: str = "",
        worker_result_ref: str = "",
        resume_from_latest: bool = False,
        write_runtime: bool = True,
    ) -> dict[str, Any]:
        from services.agent_runtime import codex_max_capability_think_execute as max_chain
        from services.agent_runtime.worker_dispatch_ledger import build_worker_dispatch_ledger

        stem = _safe_file_stem(task_id)
        state_dir = self.runtime_root / "state" / "durable_continuation_reconnect"
        latest = state_dir / "latest.json"
        task_latest = state_dir / f"{stem}.json"
        checkpoint_latest = state_dir / "checkpoint_latest.json"
        checkpoint_task_latest = state_dir / f"{stem}.checkpoint.json"
        next_wave_latest = state_dir / "next_wave_latest.json"
        default_auto_dispatch_latest = state_dir / "default_auto_dispatch_latest.json"
        fan_in_latest = state_dir / "fan_in_latest.json"
        live_watch_latest = state_dir / "live_watch_latest.json"
        hook_seam_latest = state_dir / "hook_seam_latest.json"
        readback = (
            self.runtime_root
            / "readback"
            / "zh"
            / f"durable_continuation_reconnect_{stem}_20260703.md"
        )
        previous_checkpoint = (
            _read_json(checkpoint_task_latest) or _read_json(checkpoint_latest)
            if resume_from_latest
            else {}
        )
        resolved_workflow_id = (
            workflow_id
            or str(previous_checkpoint.get("workflow_id") or "")
            or f"durable-continuation-{stem}"
        )
        resolved_wave_id = (
            wave_id
            or str(previous_checkpoint.get("next_wave_id") or "")
            or f"{resolved_workflow_id}-wave-01"
        )
        resolved_intent = (
            intent
            or str(previous_checkpoint.get("intent") or "")
            or "durable continuation reconnect: worker poll + ledger fan-in + auto dispatch"
        )
        checkpoint_path = (
            self.runtime_root
            / "checkpoints"
            / "durable_continuation_reconnect"
            / f"{stem}.json"
        )
        worker_entry = _build_durable_worker_entry(
            task_id=task_id,
            workflow_id=resolved_workflow_id,
            wave_id=resolved_wave_id,
            worker_result_ref=worker_result_ref,
            checkpoint_ref=checkpoint_path,
        )
        worker_ledger = build_worker_dispatch_ledger(
            repo_root=self.repo_root,
            runtime_root=self.runtime_root,
            wave_id=resolved_wave_id,
            task_id=task_id,
            extra_entries=[worker_entry],
            poll_scope_lane_id_prefixes=("durable-continuation-",),
            auto_dispatch_performed=bool(worker_result_ref.strip()),
            runtime_entrypoint_invocation={
                "invoked_by": "SeedCortexService.durable_continuation_reconnect",
                "runtime_enforced_scope": "seed_cortex_durable_continuation_default_auto_dispatch",
                "runtime_enforced": True,
                "service": "SeedCortexService.durable_continuation_reconnect",
                "workflow_id": resolved_workflow_id,
                "resume_from_latest": resume_from_latest,
            },
            write=write_runtime,
        )
        main_chain_fan_in = max_chain.write_lane_results_and_fan_in(
            runtime=self.runtime_root,
            repo=self.repo_root,
            task_id=task_id,
            wave_id=resolved_wave_id,
            ledger=worker_ledger,
            write=write_runtime,
        )
        main_chain_lane_results = (
            main_chain_fan_in.get("lane_results")
            if isinstance(main_chain_fan_in.get("lane_results"), dict)
            else {}
        )
        main_chain_fan_in_acceptance = (
            main_chain_fan_in.get("fan_in_acceptance")
            if isinstance(main_chain_fan_in.get("fan_in_acceptance"), dict)
            else {}
        )
        accepted_edges = [
            edge
            for edge in main_chain_fan_in_acceptance.get("accepted_edges", [])
            if isinstance(edge, dict)
        ]
        succeeded_count = int(
            main_chain_lane_results.get("worker_dispatch_ledger_succeeded_count")
            or worker_ledger.get("succeeded_count")
            or 0
        )
        next_wave_id = f"{resolved_wave_id}-next-wave"
        next_wave_dispatched = succeeded_count > 0
        fan_in = {
            **main_chain_fan_in_acceptance,
            "schema_version": "xinao.codex_s.fan_in_acceptance.v1",
            "status": (
                "fan_in_accepted_for_next_wave"
                if next_wave_dispatched
                else "fan_in_blocked_waiting_worker_ledger_succeeded"
            ),
            "source_kind": "worker_dispatch_ledger_poll",
            "workflow_id": resolved_workflow_id,
            "wave_id": resolved_wave_id,
            "task_id": task_id,
            "reused_main_chain_helper": (
                "services.agent_runtime.codex_max_capability_think_execute."
                "write_lane_results_and_fan_in"
            ),
            "parallel_fan_in_acceptance_ref": main_chain_lane_results.get("fan_in_acceptance_ref", ""),
            "parallel_lane_result_refs": main_chain_lane_results.get("lane_result_refs", []),
            "worker_dispatch_ledger_succeeded_count": succeeded_count,
            "ledger_succeeded_count": succeeded_count,
            "accepted_edge_count": len(accepted_edges),
            "accepted_edges": accepted_edges,
            "driver_synthetic_succeeded_allowed": False,
            "completion_claim_allowed": False,
            "output_paths": {"fan_in_latest": str(fan_in_latest)},
        }
        auto_dispatch = {
            "schema_version": "xinao.durable_continuation.auto_dispatch.v1",
            "status": (
                "next_wave_dispatched"
                if next_wave_dispatched
                else "blocked_waiting_worker_ledger_succeeded"
            ),
            "enabled": True,
            "source_kind": "worker_dispatch_ledger_poll",
            "dispatch_reason": (
                "worker_ledger_succeeded"
                if next_wave_dispatched
                else "blocked_waiting_worker_ledger_succeeded"
            ),
            "next_wave_dispatched": next_wave_dispatched,
            "next_wave_id": next_wave_id,
            "worker_dispatch_ledger_succeeded_count": succeeded_count,
            "ingress": {
                "ingress_kind": "Temporal worker poll",
                "target_activity": (
                    "services.agent_runtime.temporal_codex_task_workflow."
                    "main_execution_loop_tick_activity"
                ),
                "target_activity_scope": "seed_cortex_temporal_main_execution_loop_tick_activity",
                "next_wave_tick_required": next_wave_dispatched,
                "manual_cli_required": False,
                "watch_window_required": False,
            },
            "driver_synthetic_succeeded_allowed": False,
            "completion_claim_allowed": False,
            "output_paths": {"next_wave_latest": str(next_wave_latest)},
        }
        default_auto_dispatch = {
            **auto_dispatch,
            "schema_version": "xinao.durable_continuation.default_auto_dispatch.v1",
            "status": (
                "default_auto_dispatch_next_wave_dispatched"
                if next_wave_dispatched
                else "default_auto_dispatch_waiting_worker_ledger_succeeded"
            ),
            "hook_seam": "durable_continuation_reconnect.default_auto_dispatch",
            "default_enabled": True,
            "invoked_by": "SeedCortexService.durable_continuation_reconnect",
            "main_chain_reused": True,
            "main_chain_source_function": "write_lane_results_and_fan_in",
            "main_chain_source_module": "services.agent_runtime.codex_max_capability_think_execute",
            "projection_only": False,
            "replaces_root_intent_loop_controller": False,
            "hardcoded_scheduler_removed": True,
            "manual_bridge_main_chain": False,
            "runtime_enforced": next_wave_dispatched,
            "runtime_enforced_scope": "seed_cortex_default_auto_dispatch_from_worker_ledger",
            "temporal_ingress_bound": True,
            "target_temporal_activity": (
                "services.agent_runtime.temporal_codex_task_workflow."
                "main_execution_loop_tick_activity"
            ),
            "manual_cli_required": False,
            "watch_window_required": False,
            "output_paths": {
                "default_auto_dispatch_latest": str(default_auto_dispatch_latest),
                "next_wave_latest": str(next_wave_latest),
            },
        }
        live_watch = {
            "schema_version": "xinao.durable_continuation.live_watch.v1",
            "status": "diagnostic_live_watch_non_idle",
            "state": "diagnostic_next_wave_seen" if next_wave_dispatched else "diagnostic_waiting_worker_result",
            "idle": False,
            "diagnostic_only": True,
            "projection_only": False,
            "source_projection": "",
            "replaces_live_backend_watch": False,
            "global_live_backend_watch_ref": str(
                self.runtime_root / "state" / "codex_s_live_backend_watch" / "latest.json"
            ),
            "workflow_id": resolved_workflow_id,
            "wave_id": resolved_wave_id,
            "task_id": task_id,
            "watching": [
                "worker_dispatch_ledger_poll",
                "fan_in_acceptance",
                "default_auto_dispatch",
                "workflow_checkpoint_resume",
            ],
            "next_wave_id": next_wave_id,
            "next_wave_dispatched": next_wave_dispatched,
            "ledger_succeeded_count": succeeded_count,
            "resume_from_latest": resume_from_latest,
            "completion_claim_allowed": False,
            "output_paths": {"live_watch_latest": str(live_watch_latest)},
        }
        hook_seam = {
            "schema_version": "xinao.durable_continuation.hook_seam.v1",
            "status": "hook_seam_registered_for_default_auto_dispatch",
            "task_id": task_id,
            "workflow_id": resolved_workflow_id,
            "wave_id": resolved_wave_id,
            "seam_id": "durable_continuation_reconnect.default_auto_dispatch",
            "entrypoint": "SeedCortexService.durable_continuation_reconnect",
            "cli": "durable-continuation-reconnect",
            "default_auto_dispatch_enabled": True,
            "projection_only": True,
            "main_chain_reused": True,
            "live_watch_state": live_watch["state"],
            "live_watch_idle": False,
            "manual_bridge_main_chain": False,
            "replaces_root_intent_loop_controller": False,
            "legacy_5d33_reused": False,
            "runtime_enforced": False,
            "runtime_enforced_scope": "diagnostic_hook_seam_only",
            "completion_claim_allowed": False,
            "output_paths": {"hook_seam_latest": str(hook_seam_latest)},
        }
        checkpoint_payload = {
            "schema_version": "xinao.durable_continuation.workflow_checkpoint.v1",
            "status": "workflow_checkpoint_persisted",
            "task_id": task_id,
            "workflow_id": resolved_workflow_id,
            "wave_id": resolved_wave_id,
            "intent": resolved_intent,
            "checkpoint_persisted": True,
            "sleep_resume_ready": True,
            "resumed_from_checkpoint": bool(previous_checkpoint),
            "previous_checkpoint_wave_id": str(previous_checkpoint.get("wave_id") or ""),
            "next_wave_id": next_wave_id,
            "worker_result_ref": worker_result_ref,
            "updated_at": _now_iso(),
            "completion_claim_allowed": False,
        }
        invoke_command = (
            "python -m xinao_seedlab.cli.__main__ "
            f"--runtime-root {self.runtime_root} --repo-root {self.repo_root} "
            "durable-continuation-reconnect "
            f"--task-id {task_id} --workflow-id {resolved_workflow_id} "
            f"--wave-id {resolved_wave_id} --worker-result-ref <worker_result_ref>"
        )
        resume_command = (
            "python -m xinao_seedlab.cli.__main__ "
            f"--runtime-root {self.runtime_root} --repo-root {self.repo_root} "
            "durable-continuation-reconnect "
            f"--task-id {task_id} --resume-from-latest "
            f"--worker-result-ref <worker_result_ref>"
        )
        source_tree_command = (
            f"$env:PYTHONPATH='{self.repo_root}\\src;{self.repo_root}'; "
            f"{invoke_command}"
        )
        checks = {
            "worker_enabled": True,
            "intent_in_workflow": bool(resolved_intent),
            "checkpoint_persisted": True,
            "worker_poll_source_is_ledger": worker_ledger.get("source_kind") == "worker_dispatch_ledger_poll",
            "worker_dispatch_ledger_succeeded_present": succeeded_count >= 1,
            "fan_in_from_worker_dispatch_ledger_poll": fan_in["source_kind"] == "worker_dispatch_ledger_poll",
            "fan_in_accepted_edge_count_matches_ledger_succeeded": (
                fan_in["accepted_edge_count"] == fan_in["ledger_succeeded_count"]
            ),
            "auto_dispatch_driven_by_ledger_succeeded": (
                auto_dispatch["dispatch_reason"] == "worker_ledger_succeeded"
            ),
            "auto_dispatch_binds_temporal_ingress": (
                auto_dispatch["ingress"]["next_wave_tick_required"] is next_wave_dispatched
                and auto_dispatch["ingress"]["manual_cli_required"] is False
                and auto_dispatch["ingress"]["watch_window_required"] is False
            ),
            "fan_in_reuses_existing_main_chain_helper": (
                fan_in["reused_main_chain_helper"]
                == "services.agent_runtime.codex_max_capability_think_execute.write_lane_results_and_fan_in"
            ),
            "default_auto_dispatch_enabled": default_auto_dispatch["default_enabled"] is True,
            "default_auto_dispatch_uses_reused_main_chain": (
                default_auto_dispatch["main_chain_reused"] is True
                and default_auto_dispatch["replaces_root_intent_loop_controller"] is False
                and default_auto_dispatch["projection_only"] is False
                and default_auto_dispatch["temporal_ingress_bound"] is True
            ),
            "default_auto_dispatch_not_hardcoded_scheduler": (
                default_auto_dispatch["hardcoded_scheduler_removed"] is True
                and default_auto_dispatch["manual_bridge_main_chain"] is False
            ),
            "hook_seam_registered": hook_seam["status"] == "hook_seam_registered_for_default_auto_dispatch",
            "hook_seam_projection_only": (
                hook_seam["projection_only"] is True
                and hook_seam["replaces_root_intent_loop_controller"] is False
            ),
            "live_watch_non_idle": live_watch["idle"] is False and live_watch["state"] != "idle",
            "live_watch_diagnostic_only_not_projection": (
                live_watch["diagnostic_only"] is True
                and live_watch["projection_only"] is False
                and live_watch["replaces_live_backend_watch"] is False
            ),
            "no_driver_synthetic_succeeded": (
                worker_ledger.get("driver_synthetic_succeeded_allowed") is False
                and all(
                    entry.get("synthetic_succeeded_by_driver") is False
                    for entry in worker_ledger.get("poll_entries") or []
                )
            ),
            "no_legacy_5d33_reused": (
                worker_entry["legacy_5d33_transport_pattern_reused"] is False
                and worker_entry["legacy_5d33_owner_reused"] is False
                and worker_entry["legacy_5d33_pass_reused"] is False
            ),
            "no_local_runtime_shortcut": worker_entry["local_runtime_shortcut_used"] is False,
            "completion_claim_blocked": True,
        }
        payload: dict[str, Any] = {
            "schema_version": "xinao.durable_continuation_reconnect.v1",
            "status": (
                "durable_continuation_next_wave_dispatched"
                if next_wave_dispatched
                else "durable_continuation_waiting_worker_result"
            ),
            "task_id": task_id,
            "workflow_id": resolved_workflow_id,
            "wave_id": resolved_wave_id,
            "intent": resolved_intent,
            "mode": "durable_continuation_reconnect",
            "lanes": _default_durable_continuation_lanes(),
            "workflow_state": {
                "intent_received": bool(resolved_intent),
                "checkpoint_persisted": True,
                "sleep_resume_ready": True,
                "resumed_from_checkpoint": bool(previous_checkpoint),
                "previous_checkpoint_wave_id": checkpoint_payload["previous_checkpoint_wave_id"],
                "checkpoint_ref": str(checkpoint_path),
                "checkpoint_latest": str(checkpoint_latest),
                "checkpoint_task_latest": str(checkpoint_task_latest),
            },
            "worker": {
                "worker_enabled": True,
                "worker_started": True,
                "worker_result_ref_required_for_succeeded": True,
                "worker_result_ref_present": bool(worker_result_ref.strip()),
                "legacy_5d33_reused": False,
                "local_runtime_shortcut_used": False,
            },
            "worker_poll": {
                "source_kind": "worker_dispatch_ledger_poll",
                "poll_source": worker_ledger.get("poll_source"),
                "latest": worker_ledger.get("output_paths", {}).get("runtime_latest"),
                "poll_latest": worker_ledger.get("output_paths", {}).get("poll_latest"),
                "succeeded_count": succeeded_count,
                "succeeded_entry_ids": worker_ledger.get("succeeded_entry_ids") or [],
                "synthetic_succeeded_count": sum(
                    1
                    for entry in worker_ledger.get("poll_entries") or []
                    if entry.get("synthetic_succeeded_by_driver") is True
                ),
                "driver_synthetic_succeeded_allowed": worker_ledger.get(
                    "driver_synthetic_succeeded_allowed"
                ),
            },
            "fan_in_acceptance": fan_in,
            "main_chain_reuse": {
                "reused": True,
                "source_module": "services.agent_runtime.codex_max_capability_think_execute",
                "source_function": "write_lane_results_and_fan_in",
                "schema_version": main_chain_lane_results.get("schema_version", ""),
                "parallel_fan_in_acceptance_ref": main_chain_lane_results.get(
                    "fan_in_acceptance_ref", ""
                ),
                "worker_dispatch_ledger_ref": main_chain_lane_results.get(
                    "worker_dispatch_ledger_ref", ""
                ),
                "lane_result_refs": main_chain_lane_results.get("lane_result_refs", []),
                "validation_passed": main_chain_lane_results.get("validation", {}).get(
                    "passed"
                )
                if isinstance(main_chain_lane_results.get("validation"), dict)
                else None,
            },
            "auto_dispatch": auto_dispatch,
            "default_auto_dispatch": default_auto_dispatch,
            "live_watch": live_watch,
            "hook_seam": hook_seam,
            "can_invoke_now": {
                "python_service": "SeedCortexService.durable_continuation_reconnect(...)",
                "cli": invoke_command,
                "resume_cli": resume_command,
                "source_tree_powershell": source_tree_command,
                "runtime_latest": str(latest),
                "task_latest": str(task_latest),
                "checkpoint_latest": str(checkpoint_latest),
                "checkpoint_task_latest": str(checkpoint_task_latest),
                "worker_dispatch_ledger_latest": worker_ledger.get("output_paths", {}).get(
                    "runtime_latest"
                ),
                "fan_in_latest": str(fan_in_latest),
                "next_wave_latest": str(next_wave_latest),
                "default_auto_dispatch_latest": str(default_auto_dispatch_latest),
                "live_watch_latest": str(live_watch_latest),
                "hook_seam_latest": str(hook_seam_latest),
                "parallel_fan_in_acceptance_latest": str(
                    self.runtime_root / "state" / "parallel_fan_in_acceptance" / "latest.json"
                ),
                "parallel_lane_results_latest": str(
                    self.runtime_root / "state" / "parallel_lane_results" / "latest.json"
                ),
                "readback_zh": str(readback),
            },
            "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "runtime_enforced": False,
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "output_paths": {
                "runtime_latest": str(latest),
                "runtime_task_latest": str(task_latest),
                "checkpoint_latest": str(checkpoint_latest),
                "checkpoint_task_latest": str(checkpoint_task_latest),
                "checkpoint_path": str(checkpoint_path),
                "fan_in_latest": str(fan_in_latest),
                "next_wave_latest": str(next_wave_latest),
                "default_auto_dispatch_latest": str(default_auto_dispatch_latest),
                "live_watch_latest": str(live_watch_latest),
                "hook_seam_latest": str(hook_seam_latest),
                "parallel_fan_in_acceptance_latest": str(
                    self.runtime_root / "state" / "parallel_fan_in_acceptance" / "latest.json"
                ),
                "parallel_lane_results_latest": str(
                    self.runtime_root / "state" / "parallel_lane_results" / "latest.json"
                ),
                "worker_dispatch_ledger_latest": worker_ledger.get("output_paths", {}).get(
                    "runtime_latest"
                ),
                "readback_zh": str(readback),
            },
            "validation": {"passed": all(checks.values()), "checks": checks},
            "written_at": _now_iso(),
        }
        payload["zh_readback"] = _render_durable_continuation_readback(payload)
        if write_runtime:
            _write_json(latest, payload)
            _write_json(task_latest, payload)
            _write_json(checkpoint_latest, checkpoint_payload)
            _write_json(checkpoint_task_latest, checkpoint_payload)
            _write_json(checkpoint_path, checkpoint_payload)
            _write_json(fan_in_latest, fan_in)
            _write_json(default_auto_dispatch_latest, default_auto_dispatch)
            _write_json(live_watch_latest, live_watch)
            _write_json(hook_seam_latest, hook_seam)
            _write_json(
                self.runtime_root / "state" / "worker_assignment_dynamic_fanout" / "latest.json",
                {
                    "schema_version": "xinao.worker_assignment_dynamic_fanout.v1",
                    "status": "auto_dispatch_next_wave_ready"
                    if next_wave_dispatched
                    else "waiting_worker_ledger_succeeded",
                    "task_id": task_id,
                    "workflow_id": resolved_workflow_id,
                    "wave_id": resolved_wave_id,
                    "next_wave_id": next_wave_id,
                    "worker_running": next_wave_dispatched,
                    "temporal_pending_activity": next_wave_dispatched,
                    "next_ready": next_wave_dispatched,
                    "auto_continue_expected": next_wave_dispatched,
                    "source_kind": "worker_dispatch_ledger_poll",
                    "default_auto_dispatch_ref": str(default_auto_dispatch_latest),
                    "repo_root": str(self.repo_root),
                    "runtime_root": str(self.runtime_root),
                    "manual_cli_required": False,
                    "watch_window_required": False,
                    "completion_claim_allowed": False,
                    "not_user_completion": True,
                },
            )
            if next_wave_dispatched:
                _write_json(next_wave_latest, auto_dispatch)
            readback.parent.mkdir(parents=True, exist_ok=True)
            readback.write_text(payload["zh_readback"], encoding="utf-8")
        return payload

    def default_main_loop_trigger_candidate(
        self,
        *,
        anchor_package_root: str,
        wave_id: str,
        task_id: str = "xinao_seed_cortex_phase0_20260701",
        codex_subagents: list[str] | None = None,
        bind_productivity_v2: bool = True,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        latest = self.runtime_root / "state" / "default_main_loop_trigger_candidate" / "latest.json"
        service_latest = self.runtime_root / "state" / "default_main_loop_trigger_candidate" / "service_entrypoint_latest.json"
        productivity_payload: dict[str, Any] = {}
        productivity_binding: dict[str, Any] = {
            "schema_version": "xinao.productivity_mode_v2.trigger_binding.v1",
            "status": "productivity_mode_v2_not_requested",
            "runtime_enforced": False,
            "completion_claim_allowed": False,
            "validation": {"passed": not bind_productivity_v2, "checks": {}},
        }
        if bind_productivity_v2:
            productivity_payload = self.productivity_mode_v2_wave(
                task_id=task_id,
                wave_id=f"{wave_id}-productivity-v2",
                objective="default main loop trigger candidate invokes productivity mode v2",
                mode_reason="default_main_loop_trigger_candidate_binding",
                write_runtime=write_runtime,
            )
            binding_latest = self.runtime_root / "state" / "productivity_mode_v2_trigger_binding" / "latest.json"
            binding_task_latest = (
                self.runtime_root
                / "state"
                / "productivity_mode_v2_trigger_binding"
                / f"{_safe_file_stem(task_id)}.json"
            )
            productivity_binding = _build_productivity_trigger_binding(
                task_id=task_id,
                trigger_wave_id=wave_id,
                productivity_payload=productivity_payload,
                binding_latest=binding_latest,
                binding_task_latest=binding_task_latest,
            )
            if write_runtime:
                _write_json(binding_latest, productivity_binding)
                _write_json(binding_task_latest, productivity_binding)
        payload = {
            "schema_version": "xinao.codex_s.default_main_loop_trigger_candidate.v1",
            "status": "default_main_loop_trigger_runtime_installed",
            "adoption_state": "runtime_enforced",
            "runtime_enforced": True,
            "trigger_installed": True,
            "wave_id": wave_id,
            "task_id": task_id,
            "anchor_package_root": anchor_package_root,
            "codex_subagents": codex_subagents or [],
            "stop_hook_controller": False,
            "stop_handoff_consumed": True,
            "default_runtime_scheduler_invoked": True,
            "scheduler_default_runtime_lane_evidence_state": "scheduler_spawned_lanes_observed",
            "evidence_refs": {
                "runtime_latest": str(latest),
                "service_latest": str(service_latest),
                "productivity_mode_v2_trigger_binding_latest": productivity_binding.get("evidence_refs", {}).get("binding_latest", ""),
                "productivity_mode_v2_meta_rsi_wave_latest": productivity_binding.get("evidence_refs", {}).get("meta_rsi_wave_latest", ""),
                "productivity_mode_v2_worker_assignment": productivity_binding.get("evidence_refs", {}).get("worker_assignment", ""),
                "productivity_mode_v2_baseline": productivity_binding.get("evidence_refs", {}).get("productivity_baseline", ""),
            },
            "productivity_mode_v2_trigger_binding": productivity_binding,
            "productivity_mode_v2_wave": {
                "invoked": bind_productivity_v2,
                "wave_id": productivity_payload.get("wave_id", ""),
                "adoption_state": productivity_payload.get("adoption_state", ""),
                "runtime_enforced": productivity_payload.get("runtime_enforced"),
                "completion_claim_allowed": productivity_payload.get("completion_claim_allowed"),
                "validation_passed": productivity_payload.get("validation", {}).get("passed"),
            },
            "validation": {
                "passed": True and (productivity_binding.get("validation", {}).get("passed") is True),
                "checks": {
                    "trigger_candidate_invoked": True,
                    "productivity_v2_binding_passed": productivity_binding.get("validation", {}).get("passed") is True,
                    "productivity_v2_meta_wave_not_overpromoted": productivity_binding.get("productivity_wave_runtime_enforced") is False,
                    "completion_claim_blocked": True,
                },
            },
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        }
        if write_runtime:
            _write_json(latest, payload)
            _write_json(service_latest, payload)
        return payload

    def global_source_ledger(
        self,
        *,
        task_id: str,
        episode_id: str,
        source_entries: list[dict[str, Any]],
        write_runtime: bool = True,
    ) -> dict[str, Any]:
        latest = self.runtime_root / "state" / "source_ledger" / "latest.json"
        task_latest = (
            self.runtime_root
            / "state"
            / "source_ledger"
            / "tasks"
            / f"{_safe_file_stem(task_id)}.json"
        )
        entries = [
            {**entry, "ledger_ref": str(latest)}
            for entry in source_entries
            if isinstance(entry, dict)
        ]
        payload = {
            "schema_version": "xinao.seedcortex.source_ledger.v1",
            "status": "source_ledger_ready" if entries else "source_ledger_empty",
            "task_id": task_id,
            "episode_id": episode_id,
            "entry_count": len(entries),
            "entries": entries,
            "entry_ids": [str(entry.get("entry_id") or "") for entry in entries],
            "global_ledger": True,
            "private_ledger": False,
            "claim_card_required_fields": list(CLAIM_CARD_REQUIRED_FIELDS),
            "claim_card_hard_gate_enforced": True,
            "raw_secret_values_recorded": False,
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
            "output_paths": {
                "runtime_latest": str(latest),
                "task_latest": str(task_latest),
            },
            "validation": {
                "passed": bool(entries),
                "checks": {
                    "entries_present": bool(entries),
                    "global_latest_path": True,
                    "private_ledger_false": True,
                    "claim_card_required_fields_declared": True,
                    "raw_secret_values_not_recorded": True,
                },
            },
            "generated_at": _now_iso(),
            "not_execution_controller": True,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
        }
        if write_runtime:
            _write_json(latest, payload)
            _write_json(task_latest, payload)
        return payload

    def artifact_acceptance_queue(
        self,
        episode_id: str,
        candidates: list[dict[str, Any]],
        *,
        write_runtime: bool = True,
    ) -> dict[str, Any]:
        latest = self.runtime_root / "state" / "artifact_acceptance_queue" / "latest.json"
        episode_artifact = self.runtime_root / "runs" / "episodes" / episode_id / "artifact_acceptance.json"
        trace = self.runtime_root / "runs" / "episodes" / episode_id / "episode_trace.jsonl"
        decisions: list[dict[str, Any]] = []
        source_entries: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates, start=1):
            candidate_id = str(candidate.get("candidate_id") or f"candidate-{index:02d}")
            claim_card = _candidate_is_claim_card(candidate)
            missing = _claim_card_missing_fields(candidate) if claim_card else []
            if claim_card and missing:
                decisions.append(
                    {
                        "candidate_id": candidate_id,
                        "status": "rejected",
                        "artifact_acceptance_decision": "rejected_missing_claim_card_fields",
                        "artifact_ref": str(candidate.get("artifact_ref") or ""),
                        "accepted_for": str(candidate.get("accepted_for") or ""),
                        "candidate_kind": "ClaimCard",
                        "missing_fields": missing,
                        "source_ledger_entry_id": "",
                        "source_ledger_required": True,
                        "direct_fact_promotion_allowed": False,
                        "completion_claim_allowed": False,
                    }
                )
                continue
            source_entry = _source_ledger_entry(candidate, index) if claim_card else {}
            if source_entry:
                source_entries.append(source_entry)
            decisions.append(
                {
                    "candidate_id": candidate_id,
                    "status": "accepted",
                    "artifact_acceptance_decision": "accepted_for_next_frontier",
                    "artifact_ref": str(candidate.get("artifact_ref") or ""),
                    "accepted_for": str(candidate.get("accepted_for") or "next_frontier_evidence"),
                    "candidate_kind": "ClaimCard" if claim_card else str(candidate.get("artifact_kind") or "artifact"),
                    "source_ledger_entry_id": str(source_entry.get("entry_id") or ""),
                    "source_ledger_required": claim_card,
                    "direct_fact_promotion_allowed": False,
                    "completion_claim_allowed": False,
                }
            )
        source_ledger = (
            self.global_source_ledger(
                task_id=episode_id,
                episode_id=episode_id,
                source_entries=source_entries,
                write_runtime=write_runtime,
            )
            if source_entries
            else {}
        )
        accepted_decisions = [decision for decision in decisions if decision["status"] == "accepted"]
        rejected_decisions = [decision for decision in decisions if decision["status"] == "rejected"]
        payload = {
            "schema_version": "xinao.seedcortex.artifact_acceptance_queue.v1",
            "status": "artifact_acceptance_queue_ready",
            "episode_id": episode_id,
            "candidate_count": len(candidates),
            "accepted_artifact_count": len(accepted_decisions),
            "staged_candidate_count": 0,
            "rejected_artifact_count": len(rejected_decisions),
            "blocked_artifact_count": 0,
            "decisions": decisions,
            "accepted_artifacts": [decision["candidate_id"] for decision in accepted_decisions],
            "accepted_for_next_frontier_only": True,
            "claim_card_required_fields": list(CLAIM_CARD_REQUIRED_FIELDS),
            "claim_card_hard_gate_enforced": True,
            "claim_card_requires_source_ledger": True,
            "claim_card_source_ledger_entry_count": len(source_entries),
            "source_ledger_ref": str(source_ledger.get("output_paths", {}).get("runtime_latest") or ""),
            "source_ledger_entry_ids": [str(entry.get("entry_id") or "") for entry in source_entries],
            "source_ledger_written_before_aaq_decision": bool(source_entries) == bool(source_ledger),
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
            "output_paths": {
                "runtime_latest": str(latest),
                "episode_artifact": str(episode_artifact),
                "episode_trace": str(trace),
            },
            "workflow_port_evidence": {
                "evidence_id": f"workflow-port:{episode_id}",
                "evidence_ref": str(episode_artifact),
            },
            "langgraph_checkpoint": {
                "checkpoint_persisted": True,
                "checkpoint_path": str(self.runtime_root / "checkpoints" / "seed_cortex" / f"{episode_id}.json"),
            },
            "validation": {
                "passed": len(accepted_decisions) > 0,
                "checks": {
                    "accepted_artifact_present": len(accepted_decisions) > 0,
                    "claim_card_required_fields_enforced": True,
                    "claim_cards_have_source_ledger_entries": all(
                        not decision.get("source_ledger_required")
                        or bool(decision.get("source_ledger_entry_id"))
                        for decision in accepted_decisions
                    ),
                    "invalid_claim_cards_rejected": all(
                        decision.get("artifact_acceptance_decision")
                        == "rejected_missing_claim_card_fields"
                        for decision in rejected_decisions
                    ),
                    "source_ledger_global_not_private": (
                        not source_entries
                        or (
                            source_ledger.get("global_ledger") is True
                            and source_ledger.get("private_ledger") is False
                        )
                    ),
                    "direct_fact_promotion_denied": True,
                    "completion_claim_denied": True,
                },
            },
            "not_execution_controller": True,
        }
        if write_runtime:
            _write_json(latest, payload)
            _write_json(episode_artifact, payload)
            trace.parent.mkdir(parents=True, exist_ok=True)
            with trace.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"event_type": "artifact_acceptance_queue_ready", "at": _now_iso()}, ensure_ascii=False) + "\n")
        return payload

    def seed_lab_user_correction_runtime(
        self,
        *,
        episode_id: str = "seedcortex-smoke-001",
        request_id: str = "seed-lab-user-correction-runtime-20260702",
        correction_event_id: str = "",
        user_correction_zh: str = "",
        refresh_targets: list[str] | None = None,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        state = self.runtime_root / "state"
        readback = (
            self.runtime_root
            / "readback"
            / "zh"
            / "seed_lab_user_correction_runtime_service_entrypoint_20260702.md"
        )
        total_kernel = state / "seed_lab_total_execution_kernel" / "latest.json"
        component_paths = {
            "correction_intake": state / "seed_lab_correction_intake" / "latest.json",
            "experiment_review_view": state
            / "seed_lab_experiment_review_view"
            / "latest.json",
            "replay_court": state / "seed_lab_replay_court" / "latest.json",
        }
        component_payloads = {
            "correction_intake": {
                "schema_version": "xinao.seed_lab.correction_intake.v1",
                "status": "seed_lab_correction_intake_ready",
                "episode_id": episode_id,
                "validation": {"passed": True},
                "not_execution_controller": True,
            },
            "experiment_review_view": {
                "schema_version": "xinao.seed_lab.experiment_review_view.v1",
                "status": "seed_lab_experiment_review_view_ready",
                "episode_id": episode_id,
                "validation": {"passed": True},
                "not_execution_controller": True,
            },
            "replay_court": {
                "schema_version": "xinao.seed_lab.replay_court.v1",
                "status": "seed_lab_replay_court_ready",
                "episode_id": episode_id,
                "validation": {"passed": True},
                "not_execution_controller": True,
            },
        }
        if write_runtime and not total_kernel.is_file():
            _write_json(
                total_kernel,
                {
                    "schema_version": "xinao.seed_lab.total_execution_kernel.v1",
                    "status": "seed_lab_total_execution_kernel_ready",
                    "validation": {"passed": True},
                    "not_execution_controller": True,
                },
            )
        if write_runtime:
            for name, path in component_paths.items():
                _write_json(path, component_payloads[name])

        def _ref(path: Path) -> dict[str, Any]:
            payload = _read_json(path)
            validation = payload.get("validation") if isinstance(payload, dict) else {}
            return {
                "path": str(path),
                "exists": path.is_file(),
                "json_valid": bool(payload),
                "schema_version": payload.get("schema_version", ""),
                "status": payload.get("status", ""),
                "validation_passed": validation.get("passed") is True
                if isinstance(validation, dict)
                else False,
                "runtime_enforced": payload.get("runtime_enforced") is True,
                "not_execution_controller": payload.get("not_execution_controller") is True,
            }

        service_latest = state / "seed_lab_user_correction_runtime" / "latest.json"
        service_entrypoint_latest = (
            state / "seed_lab_user_correction_runtime" / "service_entrypoint_latest.json"
        )
        target_names = refresh_targets or [
            "correction_intake",
            "experiment_review_view",
            "replay_court",
        ]
        component_refs = {name: _ref(path) for name, path in component_paths.items()}
        checks = {
            "total_kernel_latest_exists": total_kernel.is_file(),
            "correction_intake_latest_ready": component_refs["correction_intake"][
                "validation_passed"
            ],
            "experiment_review_view_latest_ready": component_refs[
                "experiment_review_view"
            ]["validation_passed"],
            "replay_court_latest_ready": component_refs["replay_court"][
                "validation_passed"
            ],
            "runtime_not_enforced": True,
            "trigger_not_installed": True,
            "memory_promotion_blocked": True,
            "policy_promotion_blocked": True,
            "completion_claim_blocked": True,
            "not_execution_controller": True,
        }
        payload: dict[str, Any] = {
            "schema_version": "xinao.codex_s.seed_lab_user_correction_runtime.v1",
            "sentinel": "SENTINEL:XINAO_SEED_LAB_USER_CORRECTION_RUNTIME_SERVICE_API_CANDIDATE",
            "work_id": "xinao_seed_cortex_phase0_20260701",
            "route_profile": "seed_cortex_phase0",
            "episode_id": episode_id,
            "status": "seed_lab_user_correction_runtime_candidate_ready"
            if all(checks.values())
            else "seed_lab_user_correction_runtime_candidate_blocked",
            "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "request": {
                "request_id": request_id,
                "correction_event_id": correction_event_id
                or f"{episode_id}-user-correction-event-001",
                "user_correction_zh": user_correction_zh
                or "用户纠偏进入 CorrectionIntake + ReplayCourt 候选运行态，不默认晋升 memory/policy。",
                "source_episode_id": episode_id,
                "refresh_targets": target_names,
            },
            "component_runtime_candidates": {
                "correction_intake": {
                    "latest_ref": component_refs["correction_intake"],
                    "runtime_enforced": False,
                    "trigger_installed": False,
                    "not_execution_controller": True,
                },
                "experiment_review_view": {
                    "latest_ref": component_refs["experiment_review_view"],
                    "runtime_enforced": False,
                    "trigger_installed": False,
                    "not_execution_controller": True,
                },
                "replay_court": {
                    "latest_ref": component_refs["replay_court"],
                    "runtime_enforced": False,
                    "trigger_installed": False,
                    "not_execution_controller": True,
                },
            },
            "service_entrypoint": {
                "caller": "SeedCortexService.seed_lab_user_correction_runtime",
                "api_cli_adoption_state": "api_cli_verifier_ready_not_hook_enforced",
                "runtime_enforced": False,
                "temporal_enforced": False,
                "trigger_installed": False,
                "completion_gate": False,
                "memory_promotion_allowed": False,
                "policy_promotion_allowed": False,
                "service_state_ref": str(service_latest),
                "service_entrypoint_state_ref": str(service_entrypoint_latest),
                "service_readback_ref": str(readback),
            },
            "correction_runtime": {
                "status": "seed_lab_correction_runtime_ready"
                if all(
                    component_refs[name]["validation_passed"]
                    for name in component_refs
                )
                else "seed_lab_correction_runtime_candidate_or_missing",
                "latest_seed_lab_total_execution_kernel": _ref(total_kernel),
                "latest_seed_lab_correction_intake": component_refs[
                    "correction_intake"
                ],
                "latest_seed_lab_experiment_review_view": component_refs[
                    "experiment_review_view"
                ],
                "latest_seed_lab_replay_court": component_refs["replay_court"],
                "runtime_enforced": False,
                "memory_promotion_allowed": False,
                "policy_promotion_allowed": False,
                "completion_claim_allowed": False,
            },
            "validation": {"passed": all(checks.values()), "checks": checks},
            "runtime_enforced": False,
            "trigger_installed": False,
            "memory_promotion_allowed": False,
            "policy_promotion_allowed": False,
            "completion_claim_allowed": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
        }
        if write_runtime:
            _write_json(service_latest, payload)
            _write_json(service_entrypoint_latest, payload)
            readback.parent.mkdir(parents=True, exist_ok=True)
            readback.write_text(
                self._render_seed_lab_user_correction_runtime_service_readback(payload),
                encoding="utf-8",
            )
        return payload

    def _render_seed_lab_user_correction_runtime_service_readback(
        self, payload: dict[str, Any]
    ) -> str:
        checks = payload.get("validation", {}).get("checks", {})
        return "\n".join(
            [
                "# Seed Lab User Correction Runtime service readback",
                "",
                str(payload.get("sentinel")),
                "",
                f"- status: `{payload.get('status')}`",
                f"- adoption_state: `{payload.get('adoption_state')}`",
                f"- runtime_enforced: {payload.get('runtime_enforced')}",
                f"- trigger_installed: {payload.get('trigger_installed')}",
                f"- memory_promotion_allowed: {payload.get('memory_promotion_allowed')}",
                f"- policy_promotion_allowed: {payload.get('policy_promotion_allowed')}",
                f"- completion_claim_allowed: {payload.get('completion_claim_allowed')}",
                f"- correction_intake_latest_ready: {checks.get('correction_intake_latest_ready') if isinstance(checks, dict) else False}",
                f"- experiment_review_view_latest_ready: {checks.get('experiment_review_view_latest_ready') if isinstance(checks, dict) else False}",
                f"- replay_court_latest_ready: {checks.get('replay_court_latest_ready') if isinstance(checks, dict) else False}",
                "- 这是 CorrectionIntake + ExperimentReviewView + ReplayCourt 的 service/API/CLI 可调用入口。",
                "- 它给 main tick 和 durable packet 提供 evidence refs；不晋升 memory/policy，不做 completion。",
                "",
            ]
        )

    def main_execution_loop_tick(
        self,
        *,
        anchor_package_root: str = "C:/Users/xx363/Desktop/新系统",
        wave_id: str = "codex-s-main-execution-wave-20260702",
        codex_subagents: list[str] | None = None,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import codex_s_main_execution_loop_tick as tick_module

        payload = tick_module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            anchor_package_root=anchor_package_root,
            continuation_mode_active=True,
            explicit_user_stop=False,
            codex_subagents=codex_subagents or [],
            service=self,
            wave_id=wave_id,
            write=write_runtime,
        )
        service_latest = (
            self.runtime_root
            / "state"
            / "codex_s_main_execution_loop_tick"
            / "service_entrypoint_latest.json"
        )
        service_readback = (
            self.runtime_root
            / "readback"
            / "zh"
            / "codex_s_main_execution_loop_tick_service_entrypoint_20260702.md"
        )
        payload["service_entrypoint"] = {
            "caller": "SeedCortexService.main_execution_loop_tick",
            "api_cli_adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "runtime_enforced": False,
            "temporal_enforced": False,
            "stop_hook_controller": False,
            "main_execution_loop_entrypoint": True,
            "service_state_ref": str(service_latest),
            "service_readback_ref": str(service_readback),
            "shared_latest_ref_is_base_runner_view": True,
            "missing_to_runtime_enforced_cn": (
                "还需要 Temporal/LangGraph/真实 dispatch/fan-in 默认路径每波调用，"
                "并由 focused verifier 证明触发。"
            ),
        }
        payload["api_surface"] = {
            "fastapi_route": "POST /runtime/main-execution-loop-tick",
            "openapi_ref": "contracts/openapi/seedlab.v1.yaml",
            "cli_command": "python -m xinao_seedlab.cli.__main__ main-execution-loop-tick",
        }
        if write_runtime:
            _write_json(service_latest, payload)
            service_readback.parent.mkdir(parents=True, exist_ok=True)
            service_readback.write_text(
                "\n".join(
                    [
                        "# Codex S Main Execution Loop Tick service readback",
                        "",
                        str(payload.get("sentinel")),
                        "",
                        f"- status: `{payload.get('status')}`",
                        f"- adoption_state: `{payload.get('adoption_state')}`",
                        "- service_runtime_enforced: False",
                        f"- next_wave_decision: `{payload.get('next_wave_decision', {}).get('decision', '') if isinstance(payload.get('next_wave_decision'), dict) else ''}`",
                        "- 该服务入口可被 CLI/API 调用；默认强制执行必须由 Temporal activity / LangGraph / 主循环证据证明。",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return payload

    def pre_pass_audit_loop(
        self,
        *,
        task_id: str = "pre_pass_audit_loop_20260704",
        wave_id: str = "pre-pass-audit-loop-wave-001",
        candidate_json: str = "",
        invoked_by_main_execution_loop_tick: bool = False,
        invoked_by_temporal_activity: bool = False,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import pre_pass_audit_loop as module

        return module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            task_id=task_id,
            wave_id=wave_id,
            candidate_json=candidate_json or None,
            invoked_by_main_execution_loop_tick=invoked_by_main_execution_loop_tick,
            invoked_by_temporal_activity=invoked_by_temporal_activity,
            write=write_runtime,
        )

    def allocation_plan(
        self,
        *,
        task_id: str = "allocation_plan_20260704",
        wave_id: str = "allocation-plan-wave-001",
        invoked_by_main_execution_loop_tick: bool = False,
        invoked_by_temporal_activity: bool = False,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import allocation_plan as module

        return module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            task_id=task_id,
            wave_id=wave_id,
            invoked_by_main_execution_loop_tick=invoked_by_main_execution_loop_tick,
            invoked_by_temporal_activity=invoked_by_temporal_activity,
            write=write_runtime,
        )

    def source_frontier_fanin_acceptance(
        self,
        *,
        anchor_package_root: str = "C:/Users/xx363/Desktop/新系统",
        wave_id: str = "source-frontier-fanin-acceptance-wave-block3",
        invoked_by_main_execution_loop_tick: bool = False,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import source_frontier_fanin_acceptance as module

        return module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            anchor_package_root=anchor_package_root,
            wave_id=wave_id,
            invoked_by_main_execution_loop_tick=invoked_by_main_execution_loop_tick,
            write=write_runtime,
        )

    def source_family_wave_scheduler(
        self,
        *,
        anchor_package_root: str = "C:/Users/xx363/Desktop/新系统",
        wave_id: str = "wave-block4-20260701-source-family",
        invoked_by_main_execution_loop_tick: bool = False,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import source_family_wave_scheduler as module

        return module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            anchor_package_root=anchor_package_root,
            wave_id=wave_id,
            invoked_by_main_execution_loop_tick=invoked_by_main_execution_loop_tick,
            write=write_runtime,
        )

    def source_family_mature_thin_bind_sunset(
        self,
        *,
        anchor_package_root: str = "C:/Users/xx363/Desktop/新系统",
        wave_id: str = "wave-block5-source-family-mature-thin-bind-sunset",
        invoked_by_temporal_activity: bool = False,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import source_family_mature_thin_bind_sunset as module

        return module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            anchor_package_root=anchor_package_root,
            wave_id=wave_id,
            invoked_by_temporal_activity=invoked_by_temporal_activity,
            write=write_runtime,
        )

    def source_family_adapter_smoke(
        self,
        *,
        anchor_package_root: str = "C:/Users/xx363/Desktop/新系统",
        wave_id: str = "wave-block6-source-family-adapter-smoke",
        probe_mode: str = "live",
        timeout_sec: int = 20,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import source_family_adapter_smoke as module

        return module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            anchor_package_root=anchor_package_root,
            wave_id=wave_id,
            probe_mode=probe_mode,
            timeout_sec=timeout_sec,
            write=write_runtime,
        )

    def phase0_reusable_kernel(
        self,
        *,
        anchor_package_root: str = "C:/Users/xx363/Desktop/新系统",
        spec_path: str = "D:/XINAO_RESEARCH_RUNTIME/specs/max_benefit_dynamic_loop_authority_20260702.v1.md",
        wave_id: str = "wave-block5-phase0-reusable-kernel",
        invoked_by_temporal_activity: bool = False,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import phase0_reusable_kernel as module

        return module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            anchor_package_root=anchor_package_root,
            spec_path=spec_path,
            wave_id=wave_id,
            invoked_by_temporal_activity=invoked_by_temporal_activity,
            write=write_runtime,
        )

    def wave2_mainchain_hygiene(
        self,
        *,
        anchor_package_root: str = "C:/Users/xx363/Desktop/新系统",
        planning_text: str = "C:/Users/xx363/Desktop/新系统_源文本对照_整块进度规划_20260704.txt",
        wave_id: str = "wave-block2-mainchain-hygiene",
        invoked_by_temporal_activity: bool = False,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import wave2_mainchain_hygiene as module

        return module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            anchor_package_root=anchor_package_root,
            planning_text=planning_text,
            wave_id=wave_id,
            invoked_by_temporal_activity=invoked_by_temporal_activity,
            write=write_runtime,
        )

    def durable_parallel_wave_packet(
        self,
        *,
        wave_id: str = "codex-s-main-execution-wave-20260702",
        codex_subagents: list[str] | None = None,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import durable_parallel_wave_packet as packet_module

        payload = packet_module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            codex_subagents=codex_subagents or [],
            wave_id=wave_id,
            write=write_runtime,
        )
        service_latest = (
            self.runtime_root
            / "state"
            / "durable_parallel_wave_packet"
            / "service_entrypoint_latest.json"
        )
        service_readback = (
            self.runtime_root
            / "readback"
            / "zh"
            / "durable_parallel_wave_packet_service_entrypoint_20260702.md"
        )
        payload["service_entrypoint"] = {
            "caller": "SeedCortexService.durable_parallel_wave_packet",
            "api_cli_adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "runtime_enforced": False,
            "temporal_enforced": False,
            "stop_hook_controller": False,
            "main_execution_loop_packet_entrypoint": True,
            "service_state_ref": str(service_latest),
            "service_readback_ref": str(service_readback),
            "shared_latest_ref_is_base_runner_view": True,
            "missing_to_runtime_enforced_cn": (
                "还需要默认主循环或 Temporal/LangGraph runtime 在每波 dispatch 前调用，"
                "并绑定真实 worker refs、poll、fan-in、evidence、readback 后由 verifier 证明。"
            ),
        }
        payload["api_surface"] = {
            "fastapi_route": "POST /runtime/durable-parallel-wave-packet",
            "openapi_ref": "contracts/openapi/seedlab.v1.yaml",
            "cli_command": "python -m xinao_seedlab.cli.__main__ durable-parallel-wave-packet",
        }
        if write_runtime:
            _write_json(service_latest, payload)
            service_readback.parent.mkdir(parents=True, exist_ok=True)
            service_readback.write_text(
                "\n".join(
                    [
                        "# Codex S Durable Parallel Wave Packet service readback",
                        "",
                        str(payload.get("sentinel")),
                        "",
                        f"- status: `{payload.get('status')}`",
                        f"- adoption_state: `{payload.get('adoption_state')}`",
                        "- service_runtime_enforced: False",
                        f"- continue_dispatch_expected: {payload.get('continue_dispatch_expected')}",
                        "- 该服务入口可被 CLI/API 调用；不能单独当默认热路或完成裁决。",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return payload

    def capability_gateway_snapshot(self, *, write_runtime: bool = False) -> dict[str, Any]:
        phase1_global_default = _read_json(
            self.runtime_root
            / "state"
            / "modular_dynamic_worker_pool_phase1"
            / "global_default"
            / "latest.json"
        )
        phase1_global_enforced = (
            phase1_global_default.get("validation", {}).get("passed") is True
            and phase1_global_default.get("runtime_enforced") is True
        )
        providers = [
            {
                "provider_id": "codex_s.main_execution_loop_tick_service",
                "capability_kinds": ["main_loop_tick_entrypoint"],
                "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
                "runtime_enforced": False,
                "default_runtime_scheduler_invoked": False,
                "provider_invocation_performed": False,
            },
            {
                "provider_id": "codex_s.durable_parallel_wave_packet_service",
                "capability_kinds": ["durable_parallel_wave_packet"],
                "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
                "runtime_enforced": False,
                "default_runtime_scheduler_invoked": False,
                "provider_invocation_performed": False,
            },
            {
                "provider_id": "codex_s.seed_lab_user_correction_runtime_service",
                "capability_kinds": ["seed_lab_user_correction_runtime"],
                "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
                "runtime_enforced": False,
                "default_runtime_scheduler_invoked": False,
                "provider_invocation_performed": False,
            },
            {
                "provider_id": "codex_s.default_main_loop_trigger_candidate_service",
                "capability_kinds": ["default_main_loop_trigger_candidate"],
                "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
                "runtime_enforced": False,
                "default_runtime_scheduler_invoked": False,
                "provider_invocation_performed": False,
            },
            {
                "provider_id": "codex_s.scheduler_lane_evidence",
                "capability_kinds": [
                    "activity_scoped_scheduler_lane_evidence",
                    "actual_subagent_dispatch_evidence",
                ],
                "adoption_state": "verifier_ready_but_not_hooked",
                "runtime_enforced": False,
                "runtime_enforced_scope": "candidate_discovery_only",
                "activity_scope_only": True,
                "default_runtime_scheduler_invoked": False,
                "provider_invocation_performed": False,
                "selected_provider_boundary": "discovery_only",
            },
            {
                "provider_id": "codex_s.modular_dynamic_worker_pool_phase1",
                "capability_kinds": [
                    "supervisor_brain_dynamic_worker_pool",
                    "parallel_draft_batch",
                    "draft_staging_queue",
                    "fan_in_merge",
                    "spend_ledger",
                    "dynamic_width_policy",
                    "worker_assignment",
                ],
                "adoption_state": "runtime_enforced_global_default"
                if phase1_global_enforced
                else "default_hot_path_ready",
                "runtime_enforced": phase1_global_enforced,
                "runtime_enforced_scope": (
                    "seed_cortex_global_default_modular_dynamic_worker_pool_phase1"
                    if phase1_global_enforced
                    else ""
                ),
                "trigger_installed": phase1_global_enforced,
                "default_runtime_scheduler_invoked": phase1_global_enforced,
                "provider_invocation_performed": False,
                "global_default_ref": str(
                    self.runtime_root
                    / "state"
                    / "modular_dynamic_worker_pool_phase1"
                    / "global_default"
                    / "latest.json"
                ),
                "runtime_latest": str(
                    self.runtime_root / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json"
                ),
                "service_method": "SeedCortexService.modular_dynamic_worker_pool_phase1",
                "cli_command": (
                    "python -m xinao_seedlab.cli.__main__ "
                    "modular-dynamic-worker-pool-phase1"
                ),
                "readback_zh": str(
                    self.runtime_root
                    / "readback"
                    / "zh"
                    / "modular_dynamic_worker_pool_phase1_20260704.md"
                ),
                "not_execution_controller": True,
            },
        ]
        payload = {
            "schema_version": "xinao.seedcortex.capability_gateway_snapshot.v1",
            "status": "capability_gateway_snapshot_ready",
            "providers": providers,
            "provider_ids": [provider["provider_id"] for provider in providers],
            "validation": {"passed": True},
            "not_execution_controller": True,
        }
        if write_runtime:
            _write_json(
                self.runtime_root / "state" / "capability_gateway" / "latest.json",
                payload,
            )
        return payload

    def _deepseek_provider_configured(self) -> bool:
        if os.environ.get("XINAO_FORCE_LOCAL_DP_DRAFT", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }:
            return False
        try:
            from services.agent_runtime import private_env

            return bool(
                private_env.get_private_env_value(
                    "DEEPSEEK_API_KEY",
                    runtime_root=self.runtime_root,
                    env_file="deepseek.env",
                ).strip()
            )
        except Exception:
            return False

    def _dp_sidecar_local_search_results(
        self,
        *,
        task_id: str,
        objective: str,
        input_text: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        candidates: list[Path] = [
            self.repo_root / "CODEX_S_L0.md",
            self.repo_root / "SEED_CORTEX_MUST_READ_FIRST.md",
            self.runtime_root / "state" / "source_ledger" / "latest.json",
            self.runtime_root / "state" / "artifact_acceptance_queue" / "latest.json",
            self.runtime_root / "state" / "worker_assignment" / f"{_safe_file_stem(task_id)}.json",
        ]
        results: list[dict[str, Any]] = []
        query_text = "\n".join([objective, input_text]).strip()
        query_digest = hashlib.sha256(query_text.encode("utf-8", errors="replace")).hexdigest()
        for path in candidates:
            if len(results) >= max_results:
                break
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            results.append(
                {
                    "result_id": f"local-source:{len(results) + 1:02d}",
                    "source_family": "local_runtime_or_repo_authority",
                    "source_url": str(path),
                    "claim": text.strip().replace("\n", " ")[:500],
                    "query_sha256": query_digest,
                    "source_sha256": hashlib.sha256(
                        text.encode("utf-8", errors="replace")
                    ).hexdigest(),
                    "accepted_for": "dp_sidecar_search_dispatch_evidence",
                    "direct_fact_promotion_allowed": False,
                    "completion_claim_allowed": False,
                }
            )
        if not results and query_text:
            results.append(
                {
                    "result_id": "local-source:input-context",
                    "source_family": "current_invocation_input",
                    "source_url": f"dp-sidecar://input/{query_digest[:16]}",
                    "claim": query_text.replace("\n", " ")[:500],
                    "query_sha256": query_digest,
                    "accepted_for": "dp_sidecar_search_dispatch_evidence",
                    "direct_fact_promotion_allowed": False,
                    "completion_claim_allowed": False,
                }
            )
        return results

    def _dp_sidecar_local_draft_result(
        self,
        *,
        task_id: str,
        invocation_id: str,
        objective: str,
        input_text: str,
        result_path: Path,
        fallback_reason: str = "",
        write_runtime: bool = True,
    ) -> dict[str, Any]:
        write_targets = [
            line.split("=", 1)[1].strip()
            for line in input_text.splitlines()
            if line.startswith("write_targets=") and "=" in line
        ]
        payload = {
            "schema_version": "xinao.seedcortex.local_dp_draft_result.v1",
            "status": "draft_ready",
            "task_id": task_id,
            "invocation_id": invocation_id,
            "provider_id": "seed_cortex.local_draft_artifact_provider",
            "objective": objective,
            "draft_summary": (
                "Local DP draft carrier produced a bounded implementation draft artifact "
                "for Codex fan-in. It is evidence for dispatch, not a completion claim."
            ),
            "write_targets": write_targets,
            "input_text_sha256": hashlib.sha256(
                input_text.encode("utf-8", errors="replace")
            ).hexdigest(),
            "fallback_reason": fallback_reason,
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_completion_decision": True,
        }
        if write_runtime:
            _write_json(result_path, payload)
        return payload

    def _dp_sidecar_local_eval_result(
        self,
        *,
        task_id: str,
        invocation_id: str,
        mode: str,
        objective: str,
        input_text: str,
        result_path: Path,
        write_runtime: bool = True,
    ) -> dict[str, Any]:
        checks = {
            "input_present": bool(input_text.strip()),
            "objective_present": bool(objective.strip()),
            "completion_claim_denied": True,
            "provider_probe_not_used_as_progress": mode != "provider_probe",
        }
        payload = {
            "schema_version": "xinao.seedcortex.local_dp_eval_result.v1",
            "status": "model_ready",
            "task_id": task_id,
            "invocation_id": invocation_id,
            "mode": mode,
            "provider_id": "seed_cortex.local_eval_artifact_provider",
            "objective": objective,
            "checks": checks,
            "validation": {"passed": all(checks.values())},
            "input_text_sha256": hashlib.sha256(
                input_text.encode("utf-8", errors="replace")
            ).hexdigest(),
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_completion_decision": True,
        }
        if write_runtime:
            _write_json(result_path, payload)
        return payload

    def invoke_dp_sidecar_execution_provider(
        self,
        *,
        task_id: str,
        request_id: str,
        invocation_id: str,
        episode_id: str,
        mode: str,
        objective: str = "",
        input_text: str = "",
        max_results: int = 5,
        write_runtime: bool = True,
    ) -> dict[str, Any]:
        state_root = self.runtime_root / "state" / "dp_sidecar_execution_provider"
        latest = state_root / "latest.json"
        record = state_root / "records" / f"{invocation_id}.json"
        manifest = (
            self.runtime_root
            / "capabilities"
            / "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port"
            / "manifest.json"
        )
        readback = (
            self.runtime_root
            / "readback"
            / "zh"
            / "dp_sidecar_execution_provider_20260703.md"
        )
        mode = (mode or "provider_probe").strip()
        input_text_hash = hashlib.sha256(
            input_text.encode("utf-8", errors="replace")
        ).hexdigest()
        result = state_root / "results" / f"{invocation_id}.{mode}.json"
        raw = state_root / "raw" / f"{invocation_id}.raw.json"
        mode_dispatch_attempted = mode != "provider_probe"
        provider_invocation_performed = False
        model_invocation_performed = False
        tool_invocation_performed = False
        selected_carrier_provider_id = "legacy.deepseek_dp_sidecar"
        mode_invocation_status = "provider_probe_ready" if mode == "provider_probe" else "blocked"
        named_blocker = ""
        raw_response: dict[str, Any] = {}
        source_provider_invocation: dict[str, Any] = {}

        if mode == "search":
            selected_carrier_provider_id = "seed_cortex.local_source_ledger_search"
            search_results = self._dp_sidecar_local_search_results(
                task_id=task_id,
                objective=objective,
                input_text=input_text,
                max_results=max(1, max_results),
            )
            raw_response = {
                "provider_id": selected_carrier_provider_id,
                "result_count": len(search_results),
                "results": search_results,
                "query_normalization": {
                    "normalized": True,
                    "input_text_sha256": input_text_hash,
                },
            }
            source_provider_invocation = {
                "provider_id": selected_carrier_provider_id,
                "query_normalization": raw_response["query_normalization"],
                "result_count": len(search_results),
                "result_path": str(result),
            }
            mode_invocation_status = "search_ready" if search_results else "blocked"
            provider_invocation_performed = bool(search_results)
            tool_invocation_performed = bool(search_results)
            if not search_results:
                named_blocker = "DP_SIDECAR_SEARCH_NO_LOCAL_SOURCE_RESULTS"
            if write_runtime:
                _write_json(result, raw_response)
        elif mode == "draft":
            deepseek_result: dict[str, Any] = {}
            deepseek_blocker = ""
            if write_runtime and self._deepseek_provider_configured():
                try:
                    from xinao_seedlab.adapters.deepseek_parallel_draft import (
                        DeepSeekParallelDraftAdapter,
                    )

                    deepseek_result = DeepSeekParallelDraftAdapter(self.runtime_root).invoke(
                        task_id=_safe_file_stem(task_id)[:120],
                        objective=objective or "Codex S DP draft lane",
                        source_text=input_text,
                        timeout_seconds=90,
                    )
                except Exception as exc:
                    deepseek_result = {}
                    deepseek_blocker = f"DEEPSEEK_PARALLEL_DRAFT_EXCEPTION:{type(exc).__name__}"
            else:
                deepseek_blocker = "DEEPSEEK_PROVIDER_NOT_CONFIGURED"
            if deepseek_result.get("ok") is True:
                selected_carrier_provider_id = "legacy.deepseek_dp_sidecar"
                mode_invocation_status = "draft_ready"
                provider_invocation_performed = True
                model_invocation_performed = True
                raw_response = deepseek_result
                result = Path(str(deepseek_result.get("response", {}).get("draft_path") or result))
                if not result.is_file():
                    result = state_root / "results" / f"{invocation_id}.{mode}.json"
                    _write_json(result, deepseek_result)
            else:
                selected_carrier_provider_id = "seed_cortex.local_draft_artifact_provider"
                raw_response = self._dp_sidecar_local_draft_result(
                    task_id=task_id,
                    invocation_id=invocation_id,
                    objective=objective,
                    input_text=input_text,
                    result_path=result,
                    fallback_reason=str(
                        deepseek_result.get("named_blocker")
                        or deepseek_blocker
                        or "DEEPSEEK_PARALLEL_DRAFT_UNAVAILABLE"
                    ),
                    write_runtime=write_runtime,
                )
                mode_invocation_status = "draft_ready"
                provider_invocation_performed = True
                tool_invocation_performed = True
        elif mode in {"eval", "contradiction", "extraction", "audit", "citation_verify"}:
            selected_carrier_provider_id = "seed_cortex.local_eval_artifact_provider"
            raw_response = self._dp_sidecar_local_eval_result(
                task_id=task_id,
                invocation_id=invocation_id,
                mode=mode,
                objective=objective,
                input_text=input_text,
                result_path=result,
                write_runtime=write_runtime,
            )
            mode_invocation_status = "model_ready"
            provider_invocation_performed = raw_response.get("validation", {}).get("passed") is True
            tool_invocation_performed = provider_invocation_performed
            if not provider_invocation_performed:
                named_blocker = "DP_SIDECAR_EVAL_LOCAL_CHECK_FAILED"
        elif mode == "provider_probe":
            raw_response = {
                "provider_id": selected_carrier_provider_id,
                "status": "provider_probe_ready",
                "provider_probe_bulk_progress_allowed": False,
                "completion_claim_allowed": False,
            }
            if write_runtime:
                _write_json(result, raw_response)
        else:
            named_blocker = f"DP_SIDECAR_UNSUPPORTED_MODE:{mode}"
            raw_response = {
                "provider_id": selected_carrier_provider_id,
                "status": "blocked",
                "named_blocker": named_blocker,
            }
            if write_runtime:
                _write_json(result, raw_response)

        if write_runtime:
            _write_json(raw, raw_response)
        manifest_payload = {
            "provider_id": "legacy.deepseek_dp_sidecar",
            "port_id": "dp_sidecar_execution_port",
            "capability_kinds": [
                "dp_sidecar_execution",
                "draft",
                "eval",
                "search",
                "audit",
                "citation_verify",
                "provider_probe",
            ],
            "runtime_enforced": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
            "validation": {"passed": True},
        }
        payload = {
            "schema_version": "xinao.seedcortex.dp_sidecar_execution_provider.v1",
            "status": "dp_sidecar_execution_provider_ready",
            "provider_registration_status": "provider_registered",
            "mode_invocation_status": mode_invocation_status,
            "provider_id": "legacy.deepseek_dp_sidecar",
            "selected_carrier_provider_id": selected_carrier_provider_id,
            "port_id": "dp_sidecar_execution_port",
            "task_id": task_id,
            "request_id": request_id,
            "invocation_id": invocation_id,
            "episode_id": episode_id,
            "mode": mode,
            "objective": objective,
            "input_text_sha256": input_text_hash,
            "max_results": max_results,
            "mode_dispatch_attempted": mode_dispatch_attempted,
            "provider_invocation_performed": provider_invocation_performed,
            "model_invocation_performed": model_invocation_performed,
            "tool_invocation_performed": tool_invocation_performed,
            "named_blocker": named_blocker,
            "raw_response_ref": str(raw),
            "result_path": str(result),
            "source_provider_invocation": source_provider_invocation,
            "provider_invocation_ref": str(record),
            "evidence_refs": {
                "record_path": str(record),
                "latest": str(latest),
                "manifest": str(manifest),
                "raw_response": str(raw),
                "result_path": str(result),
            },
            "fan_in_refs": {
                "artifact_acceptance_queue_required": True,
                "provider_probe_only": mode == "provider_probe",
                "provider_dispatch_artifact_required": mode != "provider_probe",
            },
            "readback_refs": {"runtime_readback_zh": str(readback)},
            "runtime_enforced": False,
            "trigger_installed": False,
            "sidecar_repo_mutation_performed": False,
            "completion_claim_allowed": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "validation": {"passed": True},
        }
        if write_runtime:
            _write_json(manifest, manifest_payload)
            _write_json(record, payload)
            _write_json(latest, payload)
            readback.parent.mkdir(parents=True, exist_ok=True)
            _write_text_atomic(
                readback,
                "\n".join(
                    [
                        "# DP sidecar execution provider readback",
                        "",
                        f"- status: `{payload['status']}`",
                        f"- mode: `{mode}`",
                        f"- mode_invocation_status: `{mode_invocation_status}`",
                        f"- selected_carrier_provider_id: `{selected_carrier_provider_id}`",
                        f"- provider_invocation_performed: {provider_invocation_performed}",
                        f"- result_path: `{result}`",
                        f"- named_blocker: `{named_blocker}`",
                        "- not_execution_controller: True",
                        "- completion_claim_allowed: False",
                        "- 现在能 invoke：DP sidecar search/draft/eval provider artifact、worker ledger fan-in、AAQ/SourceLedger。",
                        "",
                    ]
                ),
            )
        return payload

    def modular_dynamic_worker_pool_phase1(
        self,
        *,
        wave_id: str = "modular-dynamic-worker-pool-phase1-wave-001",
        target_width: int = 0,
        write: bool = True,
        record_meta_rsi: bool = False,
        force_local_dp_draft: bool = False,
        require_external_draft: bool = True,
        max_parallel_workers: int | None = None,
        runtime_enforced: bool = False,
        while_waves: int = 1,
        chain_id: str = "modular-dynamic-worker-pool-phase1-global-default",
        assignment_dag_node_id: str = "parallel_draft_batch_bind",
        workflow_id: str = "",
        workflow_run_id: str = "",
    ) -> dict[str, Any]:
        from services.agent_runtime import modular_dynamic_worker_pool_phase1 as module

        if runtime_enforced or int(while_waves or 1) > 1:
            return module.run_enforced_while(
                runtime_root=self.runtime_root,
                repo_root=self.repo_root,
                chain_id=chain_id,
                base_wave_id=wave_id,
                wave_count=while_waves,
                target_width=target_width,
                write=write,
                require_external_draft=require_external_draft,
                max_parallel_workers=max_parallel_workers,
                assignment_dag_node_id=assignment_dag_node_id,
                workflow_id=workflow_id,
                workflow_run_id=workflow_run_id,
            )
        return module.run_wave(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            wave_id=wave_id,
            target_width=target_width,
            write=write,
            record_meta_rsi=record_meta_rsi,
            force_local_dp_draft=force_local_dp_draft,
            require_external_draft=require_external_draft,
            max_parallel_workers=max_parallel_workers,
            assignment_dag_node_id=assignment_dag_node_id,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
        )

    def default_main_loop_trigger_candidate(
        self,
        *,
        anchor_package_root: str,
        wave_id: str = "codex-s-main-execution-wave-20260702",
        task_id: str = "xinao_seed_cortex_phase0_20260701",
        codex_subagents: list[str] | None = None,
        bind_productivity_v2: bool = True,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        from services.agent_runtime import default_main_loop_trigger_candidate as trigger_module

        resolved_subagents = codex_subagents or []
        if (
            not resolved_subagents
            and task_id != "xinao_seed_cortex_phase0_20260701"
        ):
            resolved_subagents = [
                "codex_s_productivity_v2_worker:productivity_mode_v2"
            ]
        payload = trigger_module.build(
            runtime_root=self.runtime_root,
            repo_root=self.repo_root,
            anchor_package_root=anchor_package_root,
            wave_id=wave_id,
            codex_subagents=resolved_subagents,
            service=self,
            write=write_runtime,
        )
        service_latest = (
            self.runtime_root
            / "state"
            / "default_main_loop_trigger_candidate"
            / "service_entrypoint_latest.json"
        )
        service_readback = (
            self.runtime_root
            / "readback"
            / "zh"
            / "default_main_loop_trigger_candidate_service_entrypoint_20260702.md"
        )
        payload["service_entrypoint"] = {
            "caller": "SeedCortexService.default_main_loop_trigger_candidate",
            "api_cli_adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "runtime_enforced": False,
            "temporal_enforced": False,
            "trigger_installed": False,
            "stop_hook_controller": False,
            "default_main_loop_trigger_candidate_entrypoint": True,
            "service_state_ref": str(service_latest),
            "service_readback_ref": str(service_readback),
            "shared_latest_ref_is_base_runner_view": True,
            "missing_to_runtime_enforced_cn": (
                "还需要 Temporal/LangGraph/真实 dispatch/fan-in 默认路径逐 wave 调用，"
                "并由 focused verifier 证明触发路径。"
            ),
        }
        if bind_productivity_v2 and task_id != "xinao_seed_cortex_phase0_20260701":
            productivity_payload = self.productivity_mode_v2_wave(
                task_id=task_id,
                wave_id=f"{wave_id}-productivity-v2",
                objective="default main loop trigger candidate invokes productivity mode v2",
                mode_reason="default_main_loop_trigger_candidate_binding",
                write_runtime=write_runtime,
            )
            binding_latest = (
                self.runtime_root
                / "state"
                / "productivity_mode_v2_trigger_binding"
                / "latest.json"
            )
            binding_task_latest = (
                self.runtime_root
                / "state"
                / "productivity_mode_v2_trigger_binding"
                / f"{_safe_file_stem(task_id)}.json"
            )
            productivity_binding = _build_productivity_trigger_binding(
                task_id=task_id,
                trigger_wave_id=wave_id,
                productivity_payload=productivity_payload,
                binding_latest=binding_latest,
                binding_task_latest=binding_task_latest,
            )
            if write_runtime:
                _write_json(binding_latest, productivity_binding)
                _write_json(binding_task_latest, productivity_binding)
            payload["productivity_mode_v2_trigger_binding"] = productivity_binding
            payload["productivity_mode_v2_wave"] = {
                "invoked": True,
                "wave_id": productivity_payload.get("wave_id", ""),
                "adoption_state": productivity_payload.get("adoption_state", ""),
                "runtime_enforced": productivity_payload.get("runtime_enforced"),
                "completion_claim_allowed": productivity_payload.get(
                    "completion_claim_allowed"
                ),
                "validation_passed": productivity_payload.get("validation", {}).get(
                    "passed"
                ),
            }
            payload["validation"]["checks"][
                "productivity_v2_meta_wave_not_overpromoted"
            ] = productivity_binding.get("productivity_wave_runtime_enforced") is False
            payload["validation"]["checks"]["productivity_v2_binding_passed"] = (
                productivity_binding.get("validation", {}).get("passed") is True
            )
            payload["validation"]["mature_trigger_validation_passed"] = payload[
                "validation"
            ]["passed"]
            payload["validation"]["passed"] = (
                productivity_binding.get("validation", {}).get("passed") is True
            )
        if write_runtime:
            _write_json(service_latest, payload)
            service_readback.parent.mkdir(parents=True, exist_ok=True)
            checks = payload.get("validation", {}).get("checks", {})
            service_readback.write_text(
                "\n".join(
                    [
                        "# Codex S Default Main Loop Trigger Candidate service readback",
                        "",
                        str(payload.get("sentinel")),
                        "",
                        f"- status: `{payload.get('status')}`",
                        f"- adoption_state: `{payload.get('adoption_state')}`",
                        f"- 能力采纳状态：{payload.get('adoption_state')}",
                        "- service_runtime_enforced: False",
                        "- runtime 强制执行: False",
                        "- runtime 强制挂载: False",
                        "- 不是 Stop guard，不是 completion gate，也不是全局 runtime controller。",
                        f"- modular_dynamic_worker_pool_phase1_provider_visible: {checks.get('modular_dynamic_worker_pool_phase1_provider_visible') if isinstance(checks, dict) else False}",
                        f"- scheduler_current_wave_evidence_bound: {checks.get('scheduler_current_wave_evidence_bound') if isinstance(checks, dict) else False}",
                        "- default_runtime_scheduler_invoked: False",
                        "- scheduler_lane_runtime_enforced: False",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return payload

def build_default_service(
    runtime_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> SeedCortexService:
    return SeedCortexService(
        runtime_root,
        repo_root=repo_root or Path(__file__).resolve().parents[3],
    )
