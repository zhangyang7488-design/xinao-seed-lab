"""P8 durable mainline canary and ResearchCampaign on the canonical worker daemon."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

MAINLINE_WORKFLOW_NAME = "XinaoMainlineCanaryWorkflow"
RESEARCH_WORKFLOW_NAME = "XinaoResearchCampaignWorkflow"
TASK_QUEUE = "xinao-mainline-canary-queue"
INTEGRATED_BUS_QUEUE = "xinao-integrated-langgraph-plugin-queue"
DOMAIN_ADMISSION_PATCH_ID = "domain-research-admission-report-v1"
GROK_PROVIDER_MODELS = frozenset({"grok-composer-2.5-fast", "grok-4.5"})
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_ACTIONS = {"PAUSE", "RESUME", "STOP"}


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validated_fact(value: dict[str, Any]) -> dict[str, str]:
    fact = {
        "fact_id": str(value.get("fact_id") or "").strip(),
        "kind": str(value.get("kind") or "").strip(),
        "ref": str(value.get("ref") or "").strip(),
        "fact_hash": str(value.get("fact_hash") or "").strip(),
    }
    if not all((fact["fact_id"], fact["kind"], fact["ref"])):
        raise ValueError("fact_id, kind, and ref are required")
    if not _HASH_RE.fullmatch(fact["fact_hash"]):
        raise ValueError("fact_hash must be lowercase sha256")
    return fact


def _initial_state(initial: dict[str, Any]) -> dict[str, Any]:
    operation_id = str(initial.get("operation_id") or "").strip()
    if not operation_id:
        raise ValueError("operation_id is required")
    expected = sorted({str(item).strip() for item in initial.get("expected_fact_ids", []) if item})
    facts: dict[str, dict[str, str]] = {}
    for raw in initial.get("seed_facts", []):
        fact = _validated_fact(dict(raw))
        existing = facts.get(fact["fact_id"])
        if existing is not None and existing != fact:
            raise ValueError("seed fact identity conflict")
        facts[fact["fact_id"]] = fact
    return {
        "schema_version": "xinao.mainline_canary_state.v1",
        "operation_id": operation_id,
        "expected_fact_ids": expected,
        "facts": facts,
        "fact_conflicts": [],
        "duplicate_signals": 0,
        "paused": False,
        "stop_requested": False,
        "revision": 1,
        "control_audit": [],
        "last_evidence_ref": "",
        "last_snapshot_hash": "",
    }


def _accept_fact(state: dict[str, Any], raw: dict[str, Any]) -> None:
    fact = _validated_fact(raw)
    facts = state["facts"]
    existing = facts.get(fact["fact_id"])
    if existing == fact:
        state["duplicate_signals"] += 1
        state["revision"] += 1
        return
    if existing is not None:
        state["fact_conflicts"].append(
            {
                "fact_id": fact["fact_id"],
                "existing_hash": existing["fact_hash"],
                "conflicting_hash": fact["fact_hash"],
            }
        )
        state["stop_requested"] = True
        state["revision"] += 1
        return
    facts[fact["fact_id"]] = fact
    state["revision"] += 1


def _snapshot(state: dict[str, Any]) -> dict[str, Any]:
    facts = [state["facts"][key] for key in sorted(state["facts"])]
    expected = list(state["expected_fact_ids"])
    complete = set(expected).issubset(state["facts"])
    result = {
        **state,
        "facts": facts,
        "fact_count": len(facts),
        "complete": complete,
        "status": (
            "CONFLICTED"
            if state["fact_conflicts"]
            else "STOPPED"
            if state["stop_requested"]
            else "PAUSED"
            if state["paused"]
            else "COMPLETED"
            if complete
            else "RUNNING"
        ),
    }
    result["state_hash"] = _canonical_hash(
        {key: value for key, value in result.items() if key != "last_evidence_ref"}
    )
    return result


def _write_json_atomic(path: str, value: object) -> None:
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


@activity.defn(name="xinao_write_mainline_canary_snapshot")
def write_mainline_canary_snapshot(payload: dict[str, Any]) -> dict[str, str]:
    """Write one immutable content-addressed snapshot plus a replaceable pointer."""
    from datetime import UTC, datetime
    from pathlib import Path

    snapshot = dict(payload["snapshot"])
    snapshot_hash = _canonical_hash(snapshot)
    runtime_root = Path(str(payload.get("runtime_root") or "/evidence"))
    workflow_id = str(payload["workflow_id"])
    operation_id = str(snapshot["operation_id"])
    root = (
        runtime_root
        / "projects"
        / "xinao_discovery"
        / "evidence"
        / operation_id
        / "p8_temporal"
        / workflow_id
    )
    artifact = root / "snapshots" / f"{snapshot_hash}.json"
    envelope = {
        "schema_version": "xinao.mainline_canary_snapshot.v1",
        "workflow_id": workflow_id,
        "snapshot_hash": snapshot_hash,
        "written_at": datetime.now(UTC).isoformat(),
        "snapshot": snapshot,
    }
    if artifact.is_file():
        existing = json.loads(artifact.read_text(encoding="utf-8"))
        if existing.get("snapshot") != snapshot:
            raise RuntimeError("content-addressed mainline snapshot conflict")
    else:
        _write_json_atomic(str(artifact), envelope)
    pointer = {
        "schema_version": "xinao.mainline_canary_latest.v1",
        "workflow_id": workflow_id,
        "snapshot_hash": snapshot_hash,
        "artifact_ref": str(artifact),
    }
    _write_json_atomic(str(root / "latest.json"), pointer)
    return {"snapshot_hash": snapshot_hash, "artifact_ref": str(artifact)}


@activity.defn(name="xinao_verify_domain_research_admission")
def verify_domain_research_admission_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Replay one exact admission report outside the deterministic Workflow sandbox."""

    from datetime import UTC, datetime
    from pathlib import Path

    from xinao.admission import verify_domain_research_admission_file

    return verify_domain_research_admission_file(
        Path(str(payload.get("report_ref") or "")),
        expected_file_sha256=str(payload.get("report_sha256") or ""),
        expected_scope=str(payload.get("scope") or ""),
        expected_realm=str(payload.get("realm") or ""),
        as_of=datetime.now(UTC),
        evidence_root=Path(str(payload.get("evidence_root") or "/evidence")),
    )


@workflow.defn(name=MAINLINE_WORKFLOW_NAME)
class XinaoMainlineCanaryWorkflow:
    """Durable fact accumulator with pure Query and validated operator Updates."""

    @workflow.init
    def __init__(self, initial: dict[str, Any]) -> None:
        self._state = _initial_state(initial)

    @workflow.signal(name="submit_fact")
    def submit_fact(self, fact: dict[str, Any]) -> None:
        _accept_fact(self._state, fact)

    @workflow.query(name="state")
    def state(self) -> dict[str, Any]:
        return _snapshot(self._state)

    @workflow.update(name="control")
    def control(self, command: dict[str, Any]) -> dict[str, Any]:
        action = str(command["action"]).upper()
        operation_id = str(command["operation_id"])
        prior = next(
            (item for item in self._state["control_audit"] if item["operation_id"] == operation_id),
            None,
        )
        if prior is not None:
            if prior["action"] != action:
                raise ApplicationError("control operation identity conflict", non_retryable=True)
            return dict(prior)
        record = {
            "operation_id": operation_id,
            "action": action,
            "reason": str(command["reason"]),
            "revision": self._state["revision"] + 1,
        }
        if action == "PAUSE":
            self._state["paused"] = True
        elif action == "RESUME":
            self._state["paused"] = False
        else:
            self._state["stop_requested"] = True
        self._state["control_audit"].append(record)
        self._state["revision"] += 1
        return dict(record)

    @control.validator
    def validate_control(self, command: dict[str, Any]) -> None:
        action = str(command.get("action") or "").upper()
        if action not in _CONTROL_ACTIONS:
            raise ValueError("unsupported control action")
        if not str(command.get("operation_id") or "").strip():
            raise ValueError("control operation_id is required")
        if not str(command.get("reason") or "").strip():
            raise ValueError("control reason is required")
        if self._state["stop_requested"]:
            raise ValueError("workflow is already stopping")
        if action == "PAUSE" and self._state["paused"]:
            raise ValueError("workflow is already paused")
        if action == "RESUME" and not self._state["paused"]:
            raise ValueError("workflow is not paused")

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        del initial
        flushed_revision = 0
        while True:
            if self._state["revision"] != flushed_revision:
                current = _snapshot(self._state)
                receipt = await workflow.execute_activity(
                    write_mainline_canary_snapshot,
                    {
                        "workflow_id": workflow.info().workflow_id,
                        "runtime_root": "/evidence",
                        "snapshot": current,
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                self._state["last_evidence_ref"] = receipt["artifact_ref"]
                self._state["last_snapshot_hash"] = receipt["snapshot_hash"]
                flushed_revision = self._state["revision"]
            current = _snapshot(self._state)
            if self._state["stop_requested"] or (current["complete"] and not self._state["paused"]):
                await workflow.wait_condition(workflow.all_handlers_finished)
                return _snapshot(self._state)
            await workflow.wait_condition(
                lambda: self._state["revision"] != flushed_revision or self._state["stop_requested"]
            )


@workflow.defn(name=RESEARCH_WORKFLOW_NAME)
class XinaoResearchCampaignWorkflow:
    """Typed wrapper over the existing Temporal LangGraphPlugin research wave."""

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        campaign_id = str(initial.get("campaign_id") or "").strip()
        bus_state = dict(initial.get("bus_state") or {})
        if not campaign_id or not bus_state:
            raise ApplicationError("campaign_id and bus_state are required", non_retryable=True)
        guarded = workflow.patched(DOMAIN_ADMISSION_PATCH_ID)
        admission: dict[str, Any] = {}
        if guarded:
            admission = await workflow.execute_activity(
                verify_domain_research_admission_activity,
                {
                    "report_ref": str(initial.get("domain_admission_report_ref") or ""),
                    "report_sha256": str(initial.get("domain_admission_report_sha256") or ""),
                    "scope": str(initial.get("domain_scope") or ""),
                    "realm": str(initial.get("domain_realm") or ""),
                    "evidence_root": str(
                        initial.get("domain_admission_evidence_root") or "/evidence"
                    ),
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if admission.get("allowed") is not True:
                reasons = ",".join(str(item) for item in admission.get("reasons") or [])
                raise ApplicationError(
                    f"domain research admission denied: {reasons or 'DENY'}",
                    non_retryable=True,
                )
            bus_state["domain_research_admission"] = {
                "report_ref": admission["report_ref"],
                "report_file_sha256": admission["report_file_sha256"],
                "report_content_hash": admission["content_hash"],
                "report_id": admission["report_id"],
                "scope": admission["scope"],
                "realm": admission["realm"],
                "expires_at": admission["expires_at"],
            }
        result = await workflow.execute_child_workflow(
            "XinaoIntegratedBusWorkflow",
            bus_state,
            id=f"{workflow.info().workflow_id}-langgraph",
            task_queue=INTEGRATED_BUS_QUEUE,
        )
        checks = {
            "real_grok_provider": result.get("worker_lane_provider") == "grok_acpx_headless",
            "real_grok_model": result.get("worker_lane_model") in GROK_PROVIDER_MODELS
            and result.get("grok_fanin_model_identity_ok") is True,
            "typed_fanin": result.get("grok_fanin_ok") is True
            and int(result.get("grok_fanin_lane_count") or 0) >= 1,
            "checkpoint": result.get("checkpoint_ok") is True
            and result.get("checkpoint_invoked") is True,
            "critic_gate": result.get("critic_edge_wired") is True,
            "schema_gate": result.get("instructor_ok") is True,
            "verifier_gate": result.get("pro_review_ok") is True
            and result.get("promotion_gate_passed") is True,
        }
        if not all(checks.values()):
            raise ApplicationError(
                "research campaign gate failed: "
                + ",".join(key for key, passed in checks.items() if not passed),
                non_retryable=True,
            )
        response = {
            "schema_version": "xinao.research_campaign_result.v1",
            "campaign_id": campaign_id,
            "workflow_id": workflow.info().workflow_id,
            "langgraph_child_workflow_id": f"{workflow.info().workflow_id}-langgraph",
            "checks": checks,
            "model": result.get("worker_lane_model"),
            "provider": result.get("worker_lane_provider"),
            "fanin_manifest_ref": result.get("grok_fanin_manifest_ref"),
            "checkpoint_evidence_ref": result.get("checkpoint_evidence_ref"),
            "promotion_evidence_ref": result.get("promotion_evidence_ref"),
            "proof_path": result.get("proof_path"),
        }
        if guarded:
            response["domain_research_admission"] = bus_state["domain_research_admission"]
        return response


def temporal_exports() -> tuple[list[type], list[Any]]:
    return (
        [XinaoMainlineCanaryWorkflow, XinaoResearchCampaignWorkflow],
        [write_mainline_canary_snapshot, verify_domain_research_admission_activity],
    )


__all__ = [
    "INTEGRATED_BUS_QUEUE",
    "DOMAIN_ADMISSION_PATCH_ID",
    "MAINLINE_WORKFLOW_NAME",
    "RESEARCH_WORKFLOW_NAME",
    "TASK_QUEUE",
    "XinaoMainlineCanaryWorkflow",
    "XinaoResearchCampaignWorkflow",
    "temporal_exports",
    "verify_domain_research_admission_activity",
    "write_mainline_canary_snapshot",
]
