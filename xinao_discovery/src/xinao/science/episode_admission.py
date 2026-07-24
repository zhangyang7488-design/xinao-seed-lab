"""Admission consumer for one bounded episode under the active science parent."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.contracts.objects import BASELINE_REF, BASELINE_SHA256, DATASET_REF, DATASET_SHA256
from xinao.science.active_parent import (
    SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
    ScienceActiveParentError,
    load_science_active_parent,
    resolve_science_carrier_path,
)
from xinao.science.trial_ledger import (
    ScienceTrialLedgerError,
    load_science_trial_journal,
)
from xinao.settlement import SPECIAL_NUMBER_FUNCTION, SPECIAL_NUMBER_RULE

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CLAIM_INTENTS = {"EXPLORATORY", "CONFIRMATORY", "STARTUP_VALIDATION"}
_EXPOSURE_STATES = {"UNEXPOSED", "CONTAMINATED", "UNKNOWN"}
_RESEARCH_POWER_STATUSES = {"PINNED", "UNDERPOWERED"}
_SCIENCE_TRIAL_STATUSES = {
    "REGISTERED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "TIMEOUT",
    "COMPILE_FAILED",
    "CANCELLED",
    "DISCARDED",
    "NO_ACTION",
}


class ScienceEpisodeAdmissionError(ValueError):
    """Raised when an episode tries to bypass the active science protocol."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScienceEpisodeAdmissionError(f"{label} must be an object")
    return value


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ScienceEpisodeAdmissionError(
            f"{label} fields do not match its exact contract: missing={missing}, extra={extra}"
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScienceEpisodeAdmissionError(f"{label} must be a non-empty string")
    return value.strip()


def _hash(value: Any, label: str) -> str:
    text = _text(value, label)
    if not _HASH_RE.fullmatch(text):
        raise ScienceEpisodeAdmissionError(f"{label} must be lowercase sha256")
    return text


def _iso_time(value: Any, label: str) -> datetime:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScienceEpisodeAdmissionError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ScienceEpisodeAdmissionError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ScienceEpisodeAdmissionError(f"{label} must be a non-empty list")
    return [_text(item, f"{label}[]") for item in value]


def _binding_file(
    value: Any,
    label: str,
    *,
    schema_version: str,
    expected_parent: Path,
) -> tuple[Mapping[str, Any], Path, str]:
    binding = _object(value, label)
    allowed_binding_fields = (
        {"ref", "sha256", "status"} if label == "exposure_inventory" else {"ref", "sha256"}
    )
    if set(binding) != allowed_binding_fields:
        raise ScienceEpisodeAdmissionError(
            f"{label} binding fields do not match its exact contract"
        )
    raw_ref = _text(binding.get("ref"), f"{label}.ref")
    expected_hash = _hash(binding.get("sha256"), f"{label}.sha256")
    path = resolve_science_carrier_path(raw_ref)
    if not path.is_file():
        raise ScienceEpisodeAdmissionError(f"{label} file is missing: {path}")
    try:
        path.resolve().relative_to(expected_parent.resolve())
    except ValueError as exc:
        raise ScienceEpisodeAdmissionError(
            f"{label} must be colocated with its ProtocolPin"
        ) from exc
    if path.resolve().parent != expected_parent.resolve():
        raise ScienceEpisodeAdmissionError(f"{label} must be a direct sibling of its ProtocolPin")
    observed_hash = _sha256(path)
    if observed_hash != expected_hash:
        raise ScienceEpisodeAdmissionError(f"{label} file hash mismatch")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScienceEpisodeAdmissionError(f"{label} is not valid JSON") from exc
    payload = _object(payload, label)
    if payload.get("schema_version") != schema_version:
        raise ScienceEpisodeAdmissionError(f"unsupported {label} schema")
    return payload, path, observed_hash


def canonical_world_measurement_bindings(
    *,
    background_contract_sha256: str,
) -> dict[str, dict[str, str]]:
    """Return the exact five identities consumed by the current world builder."""

    return {
        "dataset": {
            "ref": DATASET_REF,
            "sha256": DATASET_SHA256,
        },
        "rule": {
            "ref": SPECIAL_NUMBER_RULE.rule_ref,
            "sha256": canonical_sha256(SPECIAL_NUMBER_RULE),
        },
        "settlement": {
            "ref": SPECIAL_NUMBER_FUNCTION.function_ref,
            "sha256": canonical_sha256(SPECIAL_NUMBER_FUNCTION),
        },
        "baseline": {
            "ref": BASELINE_REF,
            "sha256": BASELINE_SHA256,
        },
        "world_axiom": {
            "ref": "xinao-background-axioms-contract.current",
            "sha256": _hash(
                background_contract_sha256,
                "background_contract_sha256",
            ),
        },
    }


def _validate_world_measurement_bundle(
    value: Any,
    *,
    episode_id: str,
    protocol_frozen_at: datetime,
    protocol_parent: Path,
    background_contract_sha256: str,
) -> dict[str, Any]:
    bundle, path, observed_hash = _binding_file(
        value,
        "world_measurement_bundle",
        schema_version="xinao.world_measurement_bundle.v1",
        expected_parent=protocol_parent,
    )
    _exact_fields(
        bundle,
        {
            "schema_version",
            "episode_id",
            "status",
            "knowledge_cutoff",
            "target_open_time",
            "frozen_at",
            "bindings",
        },
        "world_measurement_bundle",
    )
    if bundle.get("episode_id") != episode_id or bundle.get("status") != "WORLD_BOUND":
        raise ScienceEpisodeAdmissionError("WorldMeasurementBundle is not bound to this episode")
    knowledge_cutoff = _iso_time(
        bundle.get("knowledge_cutoff"), "world_measurement_bundle.knowledge_cutoff"
    )
    target_open_time = _iso_time(
        bundle.get("target_open_time"), "world_measurement_bundle.target_open_time"
    )
    world_frozen_at = _iso_time(bundle.get("frozen_at"), "world_measurement_bundle.frozen_at")
    if knowledge_cutoff > world_frozen_at:
        raise ScienceEpisodeAdmissionError(
            "WorldMeasurementBundle violates knowledge_cutoff <= frozen_at"
        )
    if not knowledge_cutoff < target_open_time:
        raise ScienceEpisodeAdmissionError(
            "WorldMeasurementBundle violates knowledge_cutoff < target_open_time"
        )
    if not protocol_frozen_at < target_open_time:
        raise ScienceEpisodeAdmissionError(
            "ProtocolPin must be frozen before the target outcome time"
        )
    if world_frozen_at > protocol_frozen_at:
        raise ScienceEpisodeAdmissionError("WorldMeasurementBundle was frozen after ProtocolPin")
    bindings = _object(bundle.get("bindings"), "world_measurement_bundle.bindings")
    expected_bindings = canonical_world_measurement_bindings(
        background_contract_sha256=background_contract_sha256
    )
    if set(bindings) != set(expected_bindings):
        raise ScienceEpisodeAdmissionError(
            "WorldMeasurementBundle bindings do not match the current world contract"
        )
    resolved_bindings: dict[str, dict[str, str]] = {}
    for name, expected in expected_bindings.items():
        item = _object(bindings.get(name), f"world_measurement_bundle.bindings.{name}")
        if set(item) != {"ref", "sha256"}:
            raise ScienceEpisodeAdmissionError(
                f"world_measurement_bundle.bindings.{name} must contain only ref and sha256"
            )
        observed = {
            "ref": _text(item.get("ref"), f"world_measurement_bundle.bindings.{name}.ref"),
            "sha256": _hash(item.get("sha256"), f"world_measurement_bundle.bindings.{name}.sha256"),
        }
        if observed != expected:
            raise ScienceEpisodeAdmissionError(
                f"WorldMeasurementBundle {name} binding drifted from the current world contract"
            )
        resolved_bindings[name] = observed
    return {
        "ref": str(path),
        "sha256": observed_hash,
        "knowledge_cutoff": knowledge_cutoff.isoformat().replace("+00:00", "Z"),
        "target_open_time": target_open_time.isoformat().replace("+00:00", "Z"),
        "bindings": resolved_bindings,
    }


def _validate_exposure_inventory(
    value: Any,
    *,
    episode_id: str,
    protocol_parent: Path,
) -> dict[str, Any]:
    inventory, path, observed_hash = _binding_file(
        value,
        "exposure_inventory",
        schema_version="xinao.exposure_inventory.v1",
        expected_parent=protocol_parent,
    )
    _exact_fields(
        inventory,
        {"schema_version", "episode_id", "status", "items"},
        "exposure_inventory",
    )
    if inventory.get("episode_id") != episode_id:
        raise ScienceEpisodeAdmissionError("ExposureInventory is not bound to this episode")
    state = _text(inventory.get("status"), "exposure_inventory.status").upper()
    declared_state = _text(
        _object(value, "exposure_inventory").get("status"),
        "exposure_inventory.status",
    ).upper()
    if state not in _EXPOSURE_STATES or declared_state != state:
        raise ScienceEpisodeAdmissionError("unsupported or drifted exposure inventory status")
    items = inventory.get("items")
    if not isinstance(items, list) or not items:
        raise ScienceEpisodeAdmissionError("ExposureInventory.items must be non-empty")
    item_states: list[str] = []
    for index, raw_item in enumerate(items):
        item = _object(raw_item, f"exposure_inventory.items[{index}]")
        _exact_fields(
            item,
            {
                "window_id",
                "fields",
                "disclosure_granularity",
                "status",
                "evidence_refs",
            },
            f"exposure_inventory.items[{index}]",
        )
        _text(item.get("window_id"), f"exposure_inventory.items[{index}].window_id")
        _string_list(item.get("fields"), f"exposure_inventory.items[{index}].fields")
        _text(
            item.get("disclosure_granularity"),
            f"exposure_inventory.items[{index}].disclosure_granularity",
        )
        item_state = _text(item.get("status"), f"exposure_inventory.items[{index}].status").upper()
        if item_state not in _EXPOSURE_STATES:
            raise ScienceEpisodeAdmissionError(f"unsupported exposure state in item {index}")
        item_states.append(item_state)
        _string_list(
            item.get("evidence_refs"),
            f"exposure_inventory.items[{index}].evidence_refs",
        )
    aggregate_state = (
        "CONTAMINATED"
        if "CONTAMINATED" in item_states
        else "UNKNOWN"
        if "UNKNOWN" in item_states
        else "UNEXPOSED"
    )
    if state != aggregate_state:
        raise ScienceEpisodeAdmissionError(
            "ExposureInventory status does not match its item-level exposure states"
        )
    return {
        "ref": str(path),
        "sha256": observed_hash,
        "status": state,
        "item_count": len(items),
    }


def _validate_trial_ledger(
    value: Any,
    *,
    episode_id: str,
    protocol_parent: Path,
) -> dict[str, Any]:
    ledger, path, observed_hash = _binding_file(
        value,
        "trial_ledger",
        schema_version="xinao.science_trial_ledger.v1",
        expected_parent=protocol_parent,
    )
    _exact_fields(
        ledger,
        {"schema_version", "episode_id", "append_only", "entries"},
        "trial_ledger",
    )
    if ledger.get("episode_id") != episode_id or ledger.get("append_only") is not True:
        raise ScienceEpisodeAdmissionError(
            "science TrialLedger must be append-only and bound to this episode"
        )
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise ScienceEpisodeAdmissionError("science TrialLedger.entries must be a list")
    required_entry_fields = {
        "seq",
        "work_key",
        "status",
        "family_id",
        "equivalence_cluster_id",
        "path_kind",
        "failure_reason",
        "payload_hash",
        "meta",
        "immutable",
    }
    for index, raw_entry in enumerate(entries, start=1):
        entry = _object(raw_entry, f"trial_ledger.entries[{index - 1}]")
        expected_fields = set(required_entry_fields)
        if "event" in entry:
            expected_fields.add("event")
        _exact_fields(
            entry,
            expected_fields,
            f"trial_ledger.entries[{index - 1}]",
        )
        seq = entry.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq != index:
            raise ScienceEpisodeAdmissionError(
                "science TrialLedger entry sequence must be contiguous and one-based"
            )
        _text(entry.get("work_key"), f"trial_ledger.entries[{index - 1}].work_key")
        status = _text(
            entry.get("status"),
            f"trial_ledger.entries[{index - 1}].status",
        ).upper()
        if status not in _SCIENCE_TRIAL_STATUSES:
            raise ScienceEpisodeAdmissionError(
                f"unsupported science TrialLedger status at entry {index - 1}"
            )
        for name in ("family_id", "equivalence_cluster_id", "failure_reason"):
            optional_value = entry.get(name)
            if optional_value is not None:
                _text(
                    optional_value,
                    f"trial_ledger.entries[{index - 1}].{name}",
                )
        _text(entry.get("path_kind"), f"trial_ledger.entries[{index - 1}].path_kind")
        _hash(
            entry.get("payload_hash"),
            f"trial_ledger.entries[{index - 1}].payload_hash",
        )
        _object(entry.get("meta"), f"trial_ledger.entries[{index - 1}].meta")
        if entry.get("immutable") is not True:
            raise ScienceEpisodeAdmissionError(
                f"science TrialLedger entry {index - 1} must be immutable"
            )
        if "event" in entry and entry.get("event") != "TERMINAL":
            raise ScienceEpisodeAdmissionError(
                f"science TrialLedger entry {index - 1} has an unsupported event"
            )
    try:
        journal = load_science_trial_journal(
            path,
            expected_anchor_sha256=observed_hash,
            episode_id=episode_id,
        )
    except ScienceTrialLedgerError as exc:
        raise ScienceEpisodeAdmissionError(str(exc)) from exc
    return {
        "ref": str(path),
        "sha256": observed_hash,
        "anchor_sha256": observed_hash,
        "append_only": True,
        "entry_count": journal["entry_count"],
        "entries_sha256": journal["entries_sha256"],
        "journal_ref": journal["journal_ref"],
        "journal_exists": journal["journal_exists"],
        "journal_file_sha256": journal["journal_file_sha256"],
    }


def _validate_protocol_controls(value: Any, *, claim_intent: str) -> dict[str, Any]:
    controls = _object(value, "protocol_controls")
    _exact_fields(
        controls,
        {
            "split_id",
            "metrics",
            "baselines",
            "negative_controls",
            "stopping_rule",
            "trial_family_id",
            "error_budget_ledger_id",
            "e4_eligibility_rule",
            "confirmation_query_budget",
            "power_plan",
        },
        "protocol_controls",
    )
    result: dict[str, Any] = {
        "split_id": _text(controls.get("split_id"), "protocol_controls.split_id"),
        "metrics": _string_list(controls.get("metrics"), "protocol_controls.metrics"),
        "baselines": _string_list(controls.get("baselines"), "protocol_controls.baselines"),
        "negative_controls": _string_list(
            controls.get("negative_controls"), "protocol_controls.negative_controls"
        ),
        "stopping_rule": _text(controls.get("stopping_rule"), "protocol_controls.stopping_rule"),
        "trial_family_id": _text(
            controls.get("trial_family_id"), "protocol_controls.trial_family_id"
        ),
        "error_budget_ledger_id": _text(
            controls.get("error_budget_ledger_id"),
            "protocol_controls.error_budget_ledger_id",
        ),
        "e4_eligibility_rule": _text(
            controls.get("e4_eligibility_rule"),
            "protocol_controls.e4_eligibility_rule",
        ),
    }
    budget = _object(
        controls.get("confirmation_query_budget"),
        "protocol_controls.confirmation_query_budget",
    )
    _exact_fields(
        budget,
        {"total", "remaining"},
        "protocol_controls.confirmation_query_budget",
    )
    total = budget.get("total")
    remaining = budget.get("remaining")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
        or not isinstance(remaining, int)
        or isinstance(remaining, bool)
        or remaining < 0
        or remaining > total
    ):
        raise ScienceEpisodeAdmissionError(
            "confirmation query budget must be non-negative and internally consistent"
        )
    result["confirmation_query_budget"] = {
        "total": total,
        "remaining": remaining,
    }
    power = _object(controls.get("power_plan"), "protocol_controls.power_plan")
    power_status = _text(power.get("status"), "protocol_controls.power_plan.status").upper()
    if claim_intent == "STARTUP_VALIDATION":
        if power_status != "NOT_APPLICABLE_STARTUP_VALIDATION":
            raise ScienceEpisodeAdmissionError(
                "startup validation PowerPlan must be explicitly not applicable"
            )
        expected_power_fields = {"power_plan_id", "status"}
    else:
        if power_status not in _RESEARCH_POWER_STATUSES:
            raise ScienceEpisodeAdmissionError("unsupported research PowerPlan status")
        expected_power_fields = {"power_plan_id", "status", "mde", "ess_assumption"}
    _exact_fields(power, expected_power_fields, "protocol_controls.power_plan")
    result["power_plan"] = {
        "power_plan_id": _text(
            power.get("power_plan_id"), "protocol_controls.power_plan.power_plan_id"
        ),
        "status": power_status,
    }
    if claim_intent != "STARTUP_VALIDATION":
        result["power_plan"]["mde"] = _text(
            power.get("mde"),
            "protocol_controls.power_plan.mde",
        )
        result["power_plan"]["ess_assumption"] = _text(
            power.get("ess_assumption"),
            "protocol_controls.power_plan.ess_assumption",
        )
    if claim_intent == "CONFIRMATORY" and power_status != "PINNED":
        raise ScienceEpisodeAdmissionError("confirmatory research requires a pinned PowerPlan")
    return result


def verify_science_episode_admission_file(
    protocol_pin_path: Path,
    *,
    expected_file_sha256: str,
    expected_active_parent_sha256: str,
    projection_path: Path = SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
) -> dict[str, Any]:
    """Verify active-parent and ProtocolPin identity before any child/tool call."""

    try:
        projection_path = resolve_science_carrier_path(str(projection_path))
        parent = load_science_active_parent(projection_path)
    except ScienceActiveParentError as exc:
        raise ScienceEpisodeAdmissionError(str(exc)) from exc

    expected_file = _hash(expected_file_sha256, "expected_file_sha256")
    expected_parent = _hash(expected_active_parent_sha256, "expected_active_parent_sha256")
    observed_parent = str(parent["active_parent"]["sha256"])
    if observed_parent != expected_parent:
        raise ScienceEpisodeAdmissionError("active science parent hash mismatch")
    protocol_pin_path = resolve_science_carrier_path(str(protocol_pin_path))
    if not protocol_pin_path.is_file():
        raise ScienceEpisodeAdmissionError(f"ProtocolPin is missing: {protocol_pin_path}")
    observed_file = _sha256(protocol_pin_path)
    if observed_file != expected_file:
        raise ScienceEpisodeAdmissionError("ProtocolPin file hash mismatch")
    try:
        pin = json.loads(protocol_pin_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScienceEpisodeAdmissionError("ProtocolPin is not valid JSON") from exc
    pin = _object(pin, "ProtocolPin")
    if pin.get("schema_version") != "xinao.science_protocol_pin.v1":
        raise ScienceEpisodeAdmissionError("unsupported ProtocolPin schema")
    if _hash(pin.get("active_parent_sha256"), "active_parent_sha256") != observed_parent:
        raise ScienceEpisodeAdmissionError("ProtocolPin is bound to another active parent")

    episode_id = _text(pin.get("episode_id"), "episode_id")
    protocol_pin_id = _text(pin.get("protocol_pin_id"), "protocol_pin_id")
    protocol_frozen_at = _iso_time(pin.get("frozen_at"), "frozen_at")
    claim_intent = _text(pin.get("claim_intent"), "claim_intent").upper()
    if claim_intent not in _CLAIM_INTENTS:
        raise ScienceEpisodeAdmissionError("unsupported claim_intent")
    pin_fields = {
        "schema_version",
        "episode_id",
        "protocol_pin_id",
        "frozen_at",
        "active_parent_sha256",
        "claim_intent",
        "research_question",
        "hypothesis",
        "null_hypothesis",
        "world_measurement_bundle",
        "exposure_inventory",
        "trial_ledger",
        "science_instrument_minimum",
        "protocol_controls",
        "evaluation_outcome_access",
    }
    if claim_intent == "STARTUP_VALIDATION":
        pin_fields.add("startup_validation_contract")
    _exact_fields(pin, pin_fields, "ProtocolPin")

    question = _object(pin.get("research_question"), "research_question")
    _exact_fields(
        question,
        {"question_id", "target", "non_goals"},
        "research_question",
    )
    _text(question.get("question_id"), "research_question.question_id")
    _text(question.get("target"), "research_question.target")
    _string_list(question.get("non_goals"), "research_question.non_goals")

    hypothesis = _object(pin.get("hypothesis"), "hypothesis")
    _exact_fields(hypothesis, {"claim", "counterexample"}, "hypothesis")
    _text(hypothesis.get("claim"), "hypothesis.claim")
    _text(hypothesis.get("counterexample"), "hypothesis.counterexample")
    null_hypothesis = _object(pin.get("null_hypothesis"), "null_hypothesis")
    _exact_fields(
        null_hypothesis,
        {"claim", "falsification_rule"},
        "null_hypothesis",
    )
    _text(null_hypothesis.get("claim"), "null_hypothesis.claim")
    _text(null_hypothesis.get("falsification_rule"), "null_hypothesis.falsification_rule")

    world = _validate_world_measurement_bundle(
        pin.get("world_measurement_bundle"),
        episode_id=episode_id,
        protocol_frozen_at=protocol_frozen_at,
        protocol_parent=protocol_pin_path.parent,
        background_contract_sha256=str(parent["background_contract"]["sha256"]),
    )
    exposure = _validate_exposure_inventory(
        pin.get("exposure_inventory"),
        episode_id=episode_id,
        protocol_parent=protocol_pin_path.parent,
    )
    if claim_intent == "CONFIRMATORY" and exposure["status"] != "UNEXPOSED":
        raise ScienceEpisodeAdmissionError(
            "confirmatory research requires an UNEXPOSED evaluation window"
        )
    ledger = _validate_trial_ledger(
        pin.get("trial_ledger"),
        episode_id=episode_id,
        protocol_parent=protocol_pin_path.parent,
    )
    instruments = _object(pin.get("science_instrument_minimum"), "science_instrument_minimum")
    _exact_fields(
        instruments,
        {
            "world_replay",
            "worker_bus",
            "checkpoint",
            "append_only_trial_ledger",
        },
        "science_instrument_minimum",
    )
    for name in (
        "world_replay",
        "worker_bus",
        "checkpoint",
        "append_only_trial_ledger",
    ):
        if instruments.get(name) is not True:
            raise ScienceEpisodeAdmissionError(f"science_instrument_minimum.{name} must be true")
    controls = _validate_protocol_controls(
        pin.get("protocol_controls"),
        claim_intent=claim_intent,
    )

    if pin.get("evaluation_outcome_access") is not False:
        raise ScienceEpisodeAdmissionError(
            "ProtocolPin evaluation_outcome_access must be explicitly false"
        )
    outcome_access = False
    if claim_intent == "STARTUP_VALIDATION":
        contract = _object(
            pin.get("startup_validation_contract"),
            "startup_validation_contract",
        )
        _exact_fields(
            contract,
            {
                "research_progress_claim_allowed",
                "completion_claim_allowed",
                "pre_registration_claim_allowed",
                "outcome_access_allowed",
                "science_trial_appends",
                "target_kind",
            },
            "startup_validation_contract",
        )
        required_false = (
            "research_progress_claim_allowed",
            "completion_claim_allowed",
            "pre_registration_claim_allowed",
            "outcome_access_allowed",
        )
        if any(contract.get(name) is not False for name in required_false):
            raise ScienceEpisodeAdmissionError(
                "startup validation contract permits a research or completion claim"
            )
        if contract.get("science_trial_appends") != 0 or ledger["entry_count"] != 0:
            raise ScienceEpisodeAdmissionError("startup validation must append zero science trials")
        if contract.get("target_kind") != "RUNTIME_CANARY_EVENT":
            raise ScienceEpisodeAdmissionError(
                "startup validation target must be a runtime canary event"
            )

    return {
        "schema_version": "xinao.science_episode_admission.v1",
        "allowed": True,
        "episode_id": episode_id,
        "protocol_pin_id": protocol_pin_id,
        "protocol_pin_ref": str(protocol_pin_path),
        "protocol_pin_sha256": observed_file,
        "active_parent_id": parent["active_parent"]["id"],
        "active_parent_sha256": observed_parent,
        "background_contract": dict(parent["background_contract"]),
        "claim_intent": claim_intent,
        "world_measurement_bundle": world,
        "exposure_inventory": exposure,
        "exposure_status": exposure["status"],
        "trial_ledger": ledger,
        "protocol_controls": controls,
        "evaluation_outcome_access": outcome_access,
        "pre_registration_claim_allowed": False,
        "old_g6_equivalent": False,
    }


__all__ = [
    "ScienceEpisodeAdmissionError",
    "canonical_world_measurement_bindings",
    "verify_science_episode_admission_file",
]
