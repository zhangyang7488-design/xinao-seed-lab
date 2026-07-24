"""Replay-safe Temporal entry for the current Xinao science parent."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from services.agent_runtime.xinao_mainline_canary import (
    INTEGRATED_BUS_QUEUE,
    TASK_QUEUE,
)

SCIENCE_EPISODE_WORKFLOW_NAME = "XinaoScienceEpisodeWorkflowV1"
SCIENCE_EPISODE_ACTIVITY_NAME = "xinao_verify_science_episode_admission_v1"
SCIENCE_STARTUP_INSTRUMENT_ACTIVITY_NAME = "xinao_verify_science_instruments_v1"
SCIENCE_STARTUP_WORKER_ACTIVITY_NAME = "xinao_run_science_startup_worker_v1"


@activity.defn(name=SCIENCE_EPISODE_ACTIVITY_NAME)
def verify_science_episode_admission_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify current-parent and ProtocolPin identity outside the Workflow sandbox."""

    from xinao.science import (
        SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
        load_science_active_parent,
        resolve_science_carrier_path,
        verify_science_episode_admission_file,
    )

    projection_path = resolve_science_carrier_path(str(SCIENCE_ACTIVE_PARENT_PROJECTION_PATH))
    parent = load_science_active_parent(projection_path)

    return verify_science_episode_admission_file(
        resolve_science_carrier_path(str(payload.get("protocol_pin_ref") or "")),
        expected_file_sha256=str(payload.get("protocol_pin_sha256") or ""),
        expected_active_parent_sha256=str(parent["active_parent"]["sha256"]),
        projection_path=projection_path,
    )


@activity.defn(name=SCIENCE_STARTUP_INSTRUMENT_ACTIVITY_NAME)
def verify_science_instruments_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Build/replay the canonical science world without appending a trial."""

    from xinao.catalog.compiler import sha256_file, write_atomic
    from xinao.science import (
        SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
        load_science_active_parent,
        resolve_science_carrier_path,
        verify_science_episode_admission_file,
    )
    from xinao.world.builder import (
        build_science_episode_world,
        replay_science_episode_world,
    )

    episode_id = str(payload.get("episode_id") or "").strip()
    if not episode_id:
        raise ValueError("episode_id is required")
    protocol_pin_path = resolve_science_carrier_path(str(payload.get("protocol_pin_ref") or ""))
    protocol_pin_sha256 = str(payload.get("protocol_pin_sha256") or "")
    projection_path = resolve_science_carrier_path(str(SCIENCE_ACTIVE_PARENT_PROJECTION_PATH))
    parent = load_science_active_parent(projection_path)
    active_parent_sha256 = str(parent["active_parent"]["sha256"])
    admission = verify_science_episode_admission_file(
        protocol_pin_path,
        expected_file_sha256=protocol_pin_sha256,
        expected_active_parent_sha256=active_parent_sha256,
        projection_path=projection_path,
    )
    if admission["episode_id"] != episode_id:
        raise ValueError("instrument episode does not match its ProtocolPin")
    info = activity.info()
    built = build_science_episode_world(
        dataset="verified-913",
        baseline="baseline-odds-water.v1",
        rule="special-number-rule.v1",
        protocol_pin_path=protocol_pin_path,
        protocol_pin_sha256=protocol_pin_sha256,
        workflow_id=info.workflow_id,
        run_id=info.workflow_run_id,
        code_git_sha=str(payload.get("code_git_sha") or "") or None,
    )
    output_root = Path(str(built["output_root"]))
    replay_report = output_root / "science_world_replay.json"
    replay = replay_science_episode_world(
        output_root,
        protocol_pin_path=protocol_pin_path,
        protocol_pin_sha256=protocol_pin_sha256,
        report_path=replay_report,
    )
    ledger_path = Path(str(admission["trial_ledger"]["ref"]))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    checks = {
        "science_world_built": built.get("ok") is True,
        "science_world_replayed": replay.get("ok") is True,
        "science_trial_ledger_bound": ledger.get("episode_id") == episode_id
        and ledger.get("append_only") is True,
        "science_trial_appends_zero": ledger.get("entries") == [],
        "evaluation_outcome_access_denied": admission["evaluation_outcome_access"] is False,
        "legacy_parent_scope_not_consumed": admission["old_g6_equivalent"] is False,
    }
    frozen_inputs = {
        "protocol_pin": {
            "ref": str(protocol_pin_path),
            "sha256": sha256_file(protocol_pin_path),
        },
        "world_measurement_bundle": {
            "ref": admission["world_measurement_bundle"]["ref"],
            "sha256": sha256_file(Path(str(admission["world_measurement_bundle"]["ref"]))),
        },
        "exposure_inventory": {
            "ref": admission["exposure_inventory"]["ref"],
            "sha256": sha256_file(Path(str(admission["exposure_inventory"]["ref"]))),
        },
        "trial_ledger": {
            "ref": admission["trial_ledger"]["ref"],
            "sha256": sha256_file(ledger_path),
        },
        "active_parent_projection": {
            "ref": str(projection_path),
            "sha256": sha256_file(projection_path),
        },
    }
    receipt = {
        "schema_version": "xinao.science_instrument_validation.v1",
        "episode_id": episode_id,
        "workflow_id": info.workflow_id,
        "workflow_run_id": info.workflow_run_id,
        "ok": all(checks.values()),
        "checks": checks,
        "output_root": str(output_root),
        "frozen_inputs": frozen_inputs,
        "world_snapshot_ref": str(output_root / "world_snapshot.json"),
        "world_content_hash": built["world_snapshot"]["content_hash"],
        "world_replay_ref": str(replay_report),
        "world_replay_sha256": sha256_file(replay_report),
        "science_trial_appends": 0,
        "outcome_accessed": False,
        "research_progress_claim_allowed": False,
        "completion_claim_allowed": False,
    }
    receipt_path = output_root / "science_instrument_validation.json"
    write_atomic(receipt_path, receipt)
    return {
        **receipt,
        "receipt_ref": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
    }


@activity.defn(name=SCIENCE_STARTUP_WORKER_ACTIVITY_NAME)
async def run_science_startup_worker_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one real, no-tools Grok lane in the canonical episode root."""

    from xinao.catalog.compiler import sha256_file, write_atomic
    from xinao.science import (
        SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
        load_science_active_parent,
        resolve_science_carrier_path,
        verify_science_episode_admission_file,
    )
    from xinao.world import science_episode_world_root

    from services.agent_runtime.execution_contract import validate_attempt_receipt
    from services.agent_runtime.grok_build_docker_worker import (
        PROVIDER_ID,
        READ_ONLY_PERMISSION_MODE,
        READ_ONLY_SANDBOX_PROFILE,
        run_docker_native_grok_fanin,
    )
    from services.agent_runtime.grok_execution_contract_adapter import (
        GROK_DOCKER_CONSUMER_ID,
    )
    from services.agent_runtime.integrated_bus_bus_nodes import run_checkpoint_bus

    episode_id = str(payload.get("episode_id") or "").strip()
    model = str(payload.get("model") or "").strip()
    protocol_pin_path = resolve_science_carrier_path(str(payload.get("protocol_pin_ref") or ""))
    protocol_pin_sha256 = str(payload.get("protocol_pin_sha256") or "")
    projection_path = resolve_science_carrier_path(str(SCIENCE_ACTIVE_PARENT_PROJECTION_PATH))
    parent = load_science_active_parent(projection_path)
    admission = verify_science_episode_admission_file(
        protocol_pin_path,
        expected_file_sha256=protocol_pin_sha256,
        expected_active_parent_sha256=str(parent["active_parent"]["sha256"]),
        projection_path=projection_path,
    )
    if (
        admission["episode_id"] != episode_id
        or admission["claim_intent"] != "STARTUP_VALIDATION"
        or not model
    ):
        raise ValueError("startup worker identity does not match its admitted episode")
    output_root = science_episode_world_root(
        episode_id,
        protocol_pin_sha256,
        requested=Path(str(payload.get("output_root") or "")),
    )
    worker_runtime = output_root / "worker_runtime"
    worker_scratch = worker_runtime / "scratch"
    worker_scratch.mkdir(parents=True, exist_ok=True)
    intake_path = worker_runtime / "science_startup_worker_intake.md"
    intake_text = (
        "# SCIENCE_STARTUP_VALIDATION\n\n"
        f"episode_id={episode_id}\n"
        "Validate only that the reusable Grok worker returns the required JSON receipt. "
        "No tools, external research, memory, scientific conclusion, or file mutation is allowed.\n"
    )
    intake_path.write_text(intake_text, encoding="utf-8")
    info = activity.info()
    result_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "status",
            "validation_only",
            "scientific_conclusion_produced",
            "external_state_modified",
        ],
        "properties": {
            "status": {"const": "SCIENCE_STARTUP_WORKER_OK"},
            "validation_only": {"const": True},
            "scientific_conclusion_produced": {"const": False},
            "external_state_modified": {"const": False},
        },
    }
    fanin = await run_docker_native_grok_fanin(
        runtime_root=worker_runtime,
        workflow_id=info.workflow_id,
        input_path=intake_path,
        content_md=intake_text,
        ready_frontier=[
            {
                "lane_id": "science-startup-no-tools-audit",
                "prompt": (
                    "Return exactly the bound JSON object confirming startup validation only. "
                    "Do not use any tool or produce a domain-science conclusion."
                ),
                "model": model,
                "mode": "audit",
                "write": False,
                "cwd": str(worker_scratch),
                "sandbox_read_only": True,
                "tool_allowlist_enforced": True,
                "allowed_tools": [],
                "planning": "off",
                "subagents": "off",
                "external_research": "off",
                "memory": "off",
                "max_turns": 1,
                "deadline_seconds": 300,
                "result_format": "json_object",
                "result_json_schema": result_schema,
                "min_result_chars": 40,
            }
        ],
        serial_reason="science_startup_validation_single_no_tools_lane",
        correlation_id=episode_id,
        parent_operation_id=info.workflow_run_id,
    )
    lanes = fanin.get("grok_lanes")
    if not isinstance(lanes, list) or len(lanes) != 1 or not isinstance(lanes[0], dict):
        raise ValueError("startup Grok fan-in did not return exactly one lane")
    lane = dict(lanes[0])
    logical_path = Path(str(lane.get("cross_seam_logical_contract_ref") or ""))
    attempt_path = Path(str(lane.get("cross_seam_attempt_receipt_ref") or ""))
    manifest_path = Path(str(fanin.get("grok_fanin_manifest_ref") or ""))
    final_path = Path(str(lane.get("final_ref") or ""))
    for label, path in (
        ("logical_contract", logical_path),
        ("attempt_receipt", attempt_path),
        ("fanin_manifest", manifest_path),
        ("final_output", final_path),
    ):
        try:
            path.resolve().relative_to(worker_runtime.resolve())
        except ValueError as exc:
            raise ValueError(f"startup worker {label} escaped the episode root") from exc
        if not path.is_file():
            raise ValueError(f"startup worker {label} is missing")
    logical = json.loads(logical_path.read_text(encoding="utf-8"))
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    verdict = validate_attempt_receipt(
        logical,
        attempt,
        expected_consumer_id=GROK_DOCKER_CONSUMER_ID,
    )
    usage = dict(fanin.get("grok_token_accounting") or {})
    usage_balanced = int(usage.get("total_tokens") or 0) == sum(
        int(usage.get(key) or 0) for key in ("accepted_tokens", "cancelled_tokens", "failed_tokens")
    )
    parsed_output = json.loads(str(lane.get("result_text") or ""))
    expected_output = {
        "status": "SCIENCE_STARTUP_WORKER_OK",
        "validation_only": True,
        "scientific_conclusion_produced": False,
        "external_state_modified": False,
    }
    worker_checks = {
        "fanin_ok": fanin.get("grok_fanin_ok") is True,
        "provider_exact": lane.get("provider_id") == PROVIDER_ID,
        "model_identity_ok": lane.get("model_identity_ok") is True,
        "provider_invoked": fanin.get("provider_invocation_performed") is True,
        "model_invoked": fanin.get("model_invocation_performed") is True,
        "one_accepted_invocation": int(usage.get("invocation_count") or 0) >= 1
        and int(usage.get("total_tokens") or 0) > 0
        and int(usage.get("accepted_tokens") or 0) > 0
        and usage_balanced,
        "terminal_completed": lane.get("operation_state") == "completed"
        and str(lane.get("stop_reason") or "").casefold() == "endturn",
        "cross_seam_receipt": verdict.accepted,
        "sandboxed_no_tools": lane.get("write") is False
        and lane.get("sandbox_read_only") is True
        and lane.get("tool_allowlist_enforced") is True
        and lane.get("allowed_tools") == []
        and lane.get("permission_mode") == READ_ONLY_PERMISSION_MODE
        and lane.get("sandbox_profile") == READ_ONLY_SANDBOX_PROFILE
        and lane.get("security_cli_args")
        == [
            "--sandbox",
            READ_ONLY_SANDBOX_PROFILE,
            "--permission-mode",
            READ_ONLY_PERMISSION_MODE,
            "--tools",
            "",
        ],
        "capabilities_disabled": lane.get("planning") == "off"
        and lane.get("subagents") == "off"
        and lane.get("external_research") == "off"
        and lane.get("memory") == "off",
        "bound_output": parsed_output == expected_output,
        "non_grok_invocations_zero": int(fanin.get("non_grok_model_invocations") or 0) == 0,
    }
    if not all(worker_checks.values()):
        raise ValueError(
            "startup Grok receipt failed: "
            + ",".join(name for name, ok in worker_checks.items() if not ok)
        )
    checkpoint = run_checkpoint_bus(
        runtime_root=worker_runtime,
        workflow_id=info.workflow_id,
        state_snapshot={
            "episode_id": episode_id,
            "phase": "WORKER_TERMINAL_ACCEPTED",
            "grok_fanin_manifest_sha256": sha256_file(manifest_path),
            "cross_seam_attempt_receipt_sha256": sha256_file(attempt_path),
            "science_trial_appends": 0,
            "outcome_accessed": False,
        },
    )
    if checkpoint.get("checkpoint_ok") is not True:
        raise ValueError("startup worker checkpoint was not persisted")
    frozen_before = dict(payload.get("frozen_inputs") or {})
    frozen_after: dict[str, dict[str, str]] = {}
    for name, binding in frozen_before.items():
        if not isinstance(binding, dict):
            raise ValueError(f"invalid frozen input binding: {name}")
        path = Path(str(binding.get("ref") or ""))
        frozen_after[name] = {"ref": str(path), "sha256": sha256_file(path)}
    if frozen_after != frozen_before:
        raise ValueError("a frozen science input changed during startup worker execution")
    ledger_path = Path(str(admission["trial_ledger"]["ref"]))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("entries") != []:
        raise ValueError("startup worker changed the science TrialLedger")
    checkpoint_path = output_root / "science_startup_worker_checkpoint.json"
    science_checkpoint = {
        "schema_version": "xinao.science_startup_worker_checkpoint.v1",
        "episode_id": episode_id,
        "workflow_id": info.workflow_id,
        "workflow_run_id": info.workflow_run_id,
        "phase": "WORKER_TERMINAL_ACCEPTED",
        "worker_checks": worker_checks,
        "grok_fanin_manifest_ref": str(manifest_path),
        "grok_fanin_manifest_sha256": sha256_file(manifest_path),
        "cross_seam_attempt_receipt_ref": str(attempt_path),
        "cross_seam_attempt_receipt_sha256": sha256_file(attempt_path),
        "langgraph_checkpoint_ref": str(checkpoint["checkpoint_evidence_ref"]),
        "langgraph_checkpoint_sha256": sha256_file(
            Path(str(checkpoint["checkpoint_evidence_ref"]))
        ),
        "frozen_inputs": frozen_after,
        "science_trial_appends": 0,
        "outcome_accessed": False,
        "research_progress_claim_allowed": False,
        "completion_claim_allowed": False,
    }
    write_atomic(checkpoint_path, science_checkpoint)
    receipt = {
        "schema_version": "xinao.science_startup_worker_receipt.v1",
        "status": "WORKER_TERMINAL_ACCEPTED",
        "episode_id": episode_id,
        "workflow_id": info.workflow_id,
        "workflow_run_id": info.workflow_run_id,
        "activity_id": info.activity_id,
        "activity_attempt": info.attempt,
        "run_root": str(output_root),
        "worker_runtime_root": str(worker_runtime),
        "lane_id": lane["lane_id"],
        "operation_id": lane["operation_id"],
        "selected_provider": lane["provider_id"],
        "requested_model": lane["requested_model"],
        "observed_model": lane["observed_model"],
        "model_identity_ok": True,
        "sandbox_profile": lane["sandbox_profile"],
        "permission_mode": lane["permission_mode"],
        "security_cli_args": lane["security_cli_args"],
        "usage": usage,
        "output_ref": str(final_path),
        "output_sha256": sha256_file(final_path),
        "output_chars": int(lane["result_text_chars"]),
        "terminal_state": lane["operation_state"],
        "stop_reason": lane["stop_reason"],
        "logical_contract_ref": str(logical_path),
        "logical_contract_sha256": sha256_file(logical_path),
        "attempt_receipt_ref": str(attempt_path),
        "attempt_receipt_sha256": sha256_file(attempt_path),
        "fanin_manifest_ref": str(manifest_path),
        "fanin_manifest_sha256": sha256_file(manifest_path),
        "checkpoint_ref": str(checkpoint_path),
        "science_trial_appends": 0,
        "outcome_accessed": False,
        "research_progress_claim_allowed": False,
        "completion_claim_allowed": False,
        "legacy_parent_scope_consumed": False,
    }
    receipt_path = output_root / "science_startup_worker_receipt.json"
    write_atomic(receipt_path, receipt)
    return {
        **receipt,
        "ok": True,
        "worker_checks": worker_checks,
        "receipt_ref": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "checkpoint_sha256": sha256_file(checkpoint_path),
    }


@workflow.defn(name=SCIENCE_EPISODE_WORKFLOW_NAME)
class XinaoScienceEpisodeWorkflowV1:
    """Current science-parent wrapper; admission precedes every child/tool call."""

    def __init__(self) -> None:
        self._phase = "CREATED"
        self._paused = False
        self._stop_requested = False
        self._last_control = "NONE"

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {
            "phase": self._phase,
            "paused": self._paused,
            "stop_requested": self._stop_requested,
            "last_control": self._last_control,
        }

    @workflow.signal
    def control(self, command: str) -> None:
        normalized = str(command or "").strip().upper()
        if normalized == "PAUSE":
            self._paused = True
        elif normalized == "RESUME":
            self._paused = False
        elif normalized == "STOP":
            self._stop_requested = True
            self._paused = False
        else:
            raise ApplicationError(
                "science episode control must be PAUSE, RESUME, or STOP",
                non_retryable=True,
            )
        self._last_control = normalized

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        episode_id = str(initial.get("episode_id") or "").strip()
        mode = str(initial.get("mode") or "").strip().upper()
        if not episode_id or mode not in {"SCIENCE_STARTUP_VALIDATION", "RESEARCH"}:
            raise ApplicationError(
                "episode_id and a supported mode are required",
                non_retryable=True,
            )
        caller_owned_authority = (
            "active_parent_projection_ref",
            "active_parent_sha256",
            "instrument_output_root",
        )
        if any(initial.get(name) not in (None, "") for name in caller_owned_authority):
            raise ApplicationError(
                "science authority and episode output roots are derived by the worker",
                non_retryable=True,
            )
        admission = await workflow.execute_activity(
            verify_science_episode_admission_activity,
            {
                "protocol_pin_ref": str(initial.get("protocol_pin_ref") or ""),
                "protocol_pin_sha256": str(initial.get("protocol_pin_sha256") or ""),
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if admission.get("allowed") is not True or admission.get("episode_id") != episode_id:
            raise ApplicationError("science episode admission denied", non_retryable=True)

        claim_intent = str(admission.get("claim_intent") or "").upper()
        if mode == "SCIENCE_STARTUP_VALIDATION" and claim_intent != "STARTUP_VALIDATION":
            raise ApplicationError(
                "startup validation requires STARTUP_VALIDATION claim intent",
                non_retryable=True,
            )
        if mode == "RESEARCH" and claim_intent not in {"EXPLORATORY", "CONFIRMATORY"}:
            raise ApplicationError(
                "research mode rejects startup-only claim intent",
                non_retryable=True,
            )

        self._phase = "ADMITTED"
        if initial.get("start_paused") is True:
            self._paused = True
            self._phase = "PAUSED_AFTER_ADMISSION"
        await workflow.wait_condition(lambda: not self._paused or self._stop_requested)
        if self._stop_requested:
            return {
                "schema_version": "xinao.science_episode_result.v1",
                "status": "STOPPED_BEFORE_INSTRUMENT",
                "episode_id": episode_id,
                "workflow_id": workflow.info().workflow_id,
                "workflow_type": SCIENCE_EPISODE_WORKFLOW_NAME,
                "child_scheduled": False,
                "worker_activity_scheduled": False,
                "outcome_accessed": False,
                "research_progress_claim_allowed": False,
                "completion_claim_allowed": False,
                "pre_registration_claim_allowed": False,
                "old_g6_consumed": False,
                "science_episode_admission": admission,
            }

        self._phase = "VERIFYING_INSTRUMENTS"
        instrument = await workflow.execute_activity(
            verify_science_instruments_activity,
            {
                "episode_id": episode_id,
                "protocol_pin_ref": str(initial.get("protocol_pin_ref") or ""),
                "protocol_pin_sha256": str(initial.get("protocol_pin_sha256") or ""),
                "code_git_sha": str(initial.get("code_git_sha") or ""),
            },
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        if instrument.get("ok") is not True:
            raise ApplicationError(
                "science instrument validation failed",
                non_retryable=True,
            )
        if self._stop_requested:
            raise ApplicationError(
                "science episode stopped after instrument validation",
                non_retryable=True,
            )

        if mode == "SCIENCE_STARTUP_VALIDATION":
            model = str(initial.get("model") or "").strip()
            if not model:
                raise ApplicationError(
                    "startup validation requires an explicit Grok model",
                    non_retryable=True,
                )
            self._phase = "EXECUTING_STARTUP_WORKER"
            worker_result = await workflow.execute_activity(
                run_science_startup_worker_activity,
                {
                    "episode_id": episode_id,
                    "protocol_pin_ref": str(initial.get("protocol_pin_ref") or ""),
                    "protocol_pin_sha256": str(initial.get("protocol_pin_sha256") or ""),
                    "output_root": str(instrument.get("output_root") or ""),
                    "frozen_inputs": dict(instrument.get("frozen_inputs") or {}),
                    "model": model,
                },
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            usage = dict(worker_result.get("usage") or {})
            usage_balanced = int(usage.get("total_tokens") or 0) == sum(
                int(usage.get(name) or 0)
                for name in ("accepted_tokens", "cancelled_tokens", "failed_tokens")
            )
            worker_receipt_ok = (
                worker_result.get("ok") is True
                and worker_result.get("status") == "WORKER_TERMINAL_ACCEPTED"
                and worker_result.get("model_identity_ok") is True
                and int(usage.get("invocation_count") or 0) >= 1
                and int(usage.get("total_tokens") or 0) > 0
                and int(usage.get("accepted_tokens") or 0) > 0
                and usage_balanced
                and worker_result.get("terminal_state") == "completed"
                and str(worker_result.get("stop_reason") or "").casefold() == "endturn"
                and bool(worker_result.get("receipt_ref"))
                and bool(worker_result.get("receipt_sha256"))
                and bool(worker_result.get("checkpoint_ref"))
                and bool(worker_result.get("checkpoint_sha256"))
                and int(worker_result.get("science_trial_appends") or 0) == 0
                and worker_result.get("outcome_accessed") is False
                and worker_result.get("research_progress_claim_allowed") is False
                and worker_result.get("completion_claim_allowed") is False
                and worker_result.get("legacy_parent_scope_consumed") is False
            )
            if not worker_receipt_ok:
                raise ApplicationError(
                    "startup worker did not return a complete accepted receipt",
                    non_retryable=True,
                )
            self._phase = "COMPLETED"
            return {
                "schema_version": "xinao.science_episode_result.v1",
                "status": "STARTUP_VALIDATED",
                "episode_id": episode_id,
                "workflow_id": workflow.info().workflow_id,
                "workflow_type": SCIENCE_EPISODE_WORKFLOW_NAME,
                "instrument_child_workflow_id": None,
                "child_scheduled": False,
                "worker_activity_scheduled": True,
                "outcome_accessed": False,
                "science_trial_appends": 0,
                "research_progress_claim_allowed": False,
                "completion_claim_allowed": False,
                "pre_registration_claim_allowed": False,
                "old_g6_consumed": False,
                "science_episode_admission": admission,
                "science_instrument_validation": instrument,
                "science_startup_worker_receipt": worker_result,
            }

        bus_state = dict(initial.get("bus_state") or {})
        if not bus_state:
            raise ApplicationError(
                "bus_state is required for a research instrument execution",
                non_retryable=True,
            )
        bus_state["science_episode_admission"] = admission
        bus_state["science_instrument_mode"] = mode
        bus_state["science_trial_appends"] = 0
        bus_state["research_progress_claim_allowed"] = False
        bus_state["completion_claim_allowed"] = False
        bus_state["evaluation_outcome_access"] = False
        bus_state["legacy_parent_scope_consumed"] = False
        bus_state["runtime_root"] = (
            str(instrument.get("output_root") or "").rstrip("/\\") + "/research_worker_runtime"
        )
        child_id = f"{workflow.info().workflow_id}-instrument"
        self._phase = "EXECUTING_REUSABLE_INSTRUMENT_BUS"
        result = await workflow.execute_child_workflow(
            "XinaoIntegratedBusWorkflow",
            bus_state,
            id=child_id,
            task_queue=INTEGRATED_BUS_QUEUE,
        )
        if (
            result.get("science_instrument_admission_consumed") is not True
            or result.get("research_progress_claim_allowed") is not False
            or result.get("completion_claim_allowed") is not False
            or result.get("evaluation_outcome_access") is not False
            or int(result.get("science_trial_appends") or 0) != 0
            or result.get("legacy_parent_scope_consumed") is not False
        ):
            raise ApplicationError(
                "reusable instrument bus did not consume the science boundary",
                non_retryable=True,
            )
        self._phase = "COMPLETED"
        return {
            "schema_version": "xinao.science_episode_result.v1",
            "status": "INSTRUMENT_EXECUTED",
            "episode_id": episode_id,
            "workflow_id": workflow.info().workflow_id,
            "workflow_type": SCIENCE_EPISODE_WORKFLOW_NAME,
            "instrument_child_workflow_id": child_id,
            "child_scheduled": True,
            "worker_activity_scheduled": False,
            "outcome_accessed": False,
            "science_trial_appends": 0,
            "research_progress_claim_allowed": False,
            "completion_claim_allowed": False,
            "old_g6_consumed": False,
            "science_episode_admission": admission,
            "science_instrument_validation": instrument,
            "instrument_result": result,
        }


def temporal_exports_v1() -> tuple[list[type], list[Any]]:
    return (
        [XinaoScienceEpisodeWorkflowV1],
        [
            verify_science_episode_admission_activity,
            verify_science_instruments_activity,
            run_science_startup_worker_activity,
        ],
    )


__all__ = [
    "SCIENCE_EPISODE_ACTIVITY_NAME",
    "SCIENCE_EPISODE_WORKFLOW_NAME",
    "SCIENCE_STARTUP_INSTRUMENT_ACTIVITY_NAME",
    "SCIENCE_STARTUP_WORKER_ACTIVITY_NAME",
    "TASK_QUEUE",
    "XinaoScienceEpisodeWorkflowV1",
    "temporal_exports_v1",
    "run_science_startup_worker_activity",
    "verify_science_episode_admission_activity",
    "verify_science_instruments_activity",
]
