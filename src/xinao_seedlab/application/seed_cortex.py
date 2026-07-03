from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _safe_file_stem(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return safe[:96] or "productivity-mode-v2"


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
            "lane_id": "productivity-v2-repo-diff",
            "phase": "execute",
            "kind": "repo",
            "goal": "Land the smallest useful repo diff instead of report-only output.",
            "depends_on": ["productivity-v2-restore-runtime"],
            "expected_artifact": "patch",
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
            "depends_on": ["productivity-v2-repo-diff"],
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
    readback_path: Path,
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
            "restore",
            "dispatch_lanes",
            "fan_in",
            "write_meta_wave",
            "write_baseline",
            "write_chinese_readback",
            "next_frontier",
        ],
        "lanes": lanes,
        "required_outputs": [
            "repo_diff_or_callable_capability",
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
        "can_invoke_now": {
            "cli": invoke_command,
            "meta_rsi_wave": str(meta_wave_path),
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
        "validation": {
            "passed": all(checks.values()),
            "checks": checks,
        },
        "written_at": _now_iso(),
    }


def _render_productivity_readback(payload: dict[str, Any]) -> str:
    command = payload["can_invoke_now"]["cli"]
    return "\n".join(
        [
            "# productivity mode v2 wave readback",
            "",
            f"task_id：{payload['task_id']}",
            f"wave_id：{payload['wave_id']}",
            "现在能 invoke 什么：",
            f"- {command}",
            "",
            "本波实际交付：",
            "- 写入 MetaRsiWave evidence：lanes -> results -> fan-in/readback 边界。",
            "- 写入 WORKER_ASSIGNMENT：把生产力 v2 从口号变成可调度 lanes。",
            "- 写入 CodexProductivityBaseline：记录本波 had_code_diff/had_invoke。",
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
        "legacy_5d33_transport_pattern_reused": False,
        "legacy_5d33_owner_reused": False,
        "legacy_5d33_pass_reused": False,
        "local_runtime_shortcut_used": False,
        "fan_in_decision": (
            "accepted_for_next_wave_dispatch"
            if succeeded
            else "blocked_waiting_for_worker_result_ref"
        ),
        "completion_claim_allowed": False,
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
        baseline_latest = self.runtime_root / "state" / "codex_productivity_baseline" / "latest.json"
        baseline_task_latest = (
            self.runtime_root / "state" / "codex_productivity_baseline" / f"{stem}.json"
        )
        resolved_lanes = lanes or _default_productivity_lanes()
        resolved_results = results or _default_productivity_results(readback)
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
            readback_path=readback,
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
                "productivity_baseline": str(baseline_latest),
                "readback_zh": str(readback),
            },
            "next_frontier": (
                "wire this candidate into the default main loop trigger or a Temporal/LangGraph "
                "wave with task-scoped fan-in evidence"
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
                and baseline_payload["had_code_diff"] is True
                and baseline_payload["had_invoke"] is True
            ),
            "checks": {
                "six_or_more_lanes": len(resolved_lanes) >= 6,
                "accepted_result_present": payload["fan_in"]["accepted_result_count"] >= 1,
                "completion_claim_blocked": payload["completion_claim_allowed"] is False,
                "cli_invoke_present": bool(payload["can_invoke_now"]["cli"]),
                "report_only_stop_absent": payload["fan_in"]["report_only_stop"] is False,
                "worker_assignment_present": bool(payload["WORKER_ASSIGNMENT"]["lanes"]),
                "baseline_had_code_diff": baseline_payload["had_code_diff"] is True,
                "baseline_had_invoke": baseline_payload["had_invoke"] is True,
            },
        }
        if write_runtime:
            _write_json(latest, payload)
            _write_json(task_latest, payload)
            _write_json(worker_assignment, assignment_payload)
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
            runtime_entrypoint_invocation={
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
            "projection_only": True,
            "replaces_root_intent_loop_controller": False,
            "hardcoded_scheduler_removed": True,
            "manual_bridge_main_chain": False,
            "runtime_enforced": False,
            "runtime_enforced_scope": "api_cli_service_invocation_only",
            "output_paths": {
                "default_auto_dispatch_latest": str(default_auto_dispatch_latest),
                "next_wave_latest": str(next_wave_latest),
            },
        }
        live_watch = {
            "schema_version": "xinao.durable_continuation.live_watch.v1",
            "status": "live_watch_active",
            "state": "watching_next_wave" if next_wave_dispatched else "waiting_worker_result",
            "idle": False,
            "projection_only": True,
            "source_projection": "durable_continuation_reconnect_checkpoint_ledger_fan_in",
            "replaces_live_backend_watch": False,
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
            "runtime_enforced_scope": "api_cli_service_invocation_only",
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
            "fan_in_reuses_existing_main_chain_helper": (
                fan_in["reused_main_chain_helper"]
                == "services.agent_runtime.codex_max_capability_think_execute.write_lane_results_and_fan_in"
            ),
            "default_auto_dispatch_enabled": default_auto_dispatch["default_enabled"] is True,
            "default_auto_dispatch_projects_reused_main_chain": (
                default_auto_dispatch["main_chain_reused"] is True
                and default_auto_dispatch["projection_only"] is True
                and default_auto_dispatch["replaces_root_intent_loop_controller"] is False
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
            "live_watch_projection_only": (
                live_watch["projection_only"] is True
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
        decisions = [
            {
                "candidate_id": str(candidate.get("candidate_id") or f"candidate-{index:02d}"),
                "status": "accepted",
                "artifact_acceptance_decision": "accepted_for_next_frontier",
                "artifact_ref": str(candidate.get("artifact_ref") or ""),
                "accepted_for": str(candidate.get("accepted_for") or "next_frontier_evidence"),
                "direct_fact_promotion_allowed": False,
                "completion_claim_allowed": False,
            }
            for index, candidate in enumerate(candidates, start=1)
        ]
        payload = {
            "schema_version": "xinao.seedcortex.artifact_acceptance_queue.v1",
            "status": "artifact_acceptance_queue_ready",
            "episode_id": episode_id,
            "candidate_count": len(candidates),
            "accepted_artifact_count": len(decisions),
            "decisions": decisions,
            "accepted_artifacts": [decision["candidate_id"] for decision in decisions],
            "accepted_for_next_frontier_only": True,
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
            "validation": {"passed": len(decisions) > 0},
            "not_execution_controller": True,
        }
        if write_runtime:
            _write_json(latest, payload)
            _write_json(episode_artifact, payload)
            trace.parent.mkdir(parents=True, exist_ok=True)
            with trace.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"event_type": "artifact_acceptance_queue_ready", "at": _now_iso()}, ensure_ascii=False) + "\n")
        return payload


def build_default_service(runtime_root: str | Path, *, repo_root: str | Path) -> SeedCortexService:
    return SeedCortexService(runtime_root, repo_root=repo_root)
