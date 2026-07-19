"""Single-home PowerPlanVersion pure validator (AF-005 / O37).

G5 primary validator ownership; G3 loop stage consumes the same pin.
Silent field drift DENY via frozen REQUIRED contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from xinao.single_home.errors import SingleHomeError
from xinao.single_home.field_contracts import assert_power_plan_fields
from xinao.single_home.hashing import content_sha256, require_sha256
from xinao.single_home.provisional_versions import (
    LOGICAL_OBJECT_IDS,
    POWER_PLAN_REQUIRED_FIELDS,
    POWER_PLAN_STATUSES,
    SCHEMA_VERSIONS,
    assert_provisional_version,
)

REQUIRED = POWER_PLAN_REQUIRED_FIELDS
LOGICAL_OBJECT_ID = LOGICAL_OBJECT_IDS["PowerPlanVersion"]
HOME_MODULE = "xinao.single_home.power_plan"


def _reject_bool(name: str, value: object, *, code: str) -> None:
    """bool is a subclass of int; reject it wherever a real number is required."""

    if isinstance(value, bool):
        raise SingleHomeError(code, f"{name} must be a real number, not bool")


def content_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {k: plan[k] for k in plan if k != "content_hash"}


def compute_content_hash(plan: Mapping[str, Any]) -> str:
    return content_sha256(content_payload(plan))


def validate_power_plan(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise SingleHomeError("BAD_TYPE", "power plan must be object")
    data = dict(raw)
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise SingleHomeError("MISSING_FIELDS", f"missing {missing}")
    assert_provisional_version(str(data["schema_version"]))
    if data["schema_version"] != SCHEMA_VERSIONS["power_plan_version"]:
        raise SingleHomeError("BAD_VERSION", "unexpected power_plan schema_version")
    if not isinstance(data["plan_id"], str) or not data["plan_id"]:
        raise SingleHomeError("BAD_PLAN_ID", "plan_id required")
    if not isinstance(data["family_id"], str) or not data["family_id"]:
        raise SingleHomeError("BAD_FAMILY", "family_id required")
    mde = data["mde"]
    _reject_bool("mde", mde, code="BAD_MDE")
    if not isinstance(mde, (int, float)) or mde <= 0:
        raise SingleHomeError("BAD_MDE", "mde must be positive number")
    power = data["target_power"]
    _reject_bool("target_power", power, code="BAD_POWER")
    if not isinstance(power, (int, float)) or not (0 < float(power) < 1):
        raise SingleHomeError("BAD_POWER", "target_power must be in (0,1)")
    budget = data["max_budget_trials"]
    _reject_bool("max_budget_trials", budget, code="BAD_BUDGET")
    if not isinstance(budget, int) or budget < 1:
        raise SingleHomeError("BAD_BUDGET", "max_budget_trials must be int >= 1")
    if not isinstance(data["holdout_split_binding"], str) or not data["holdout_split_binding"]:
        raise SingleHomeError("BAD_SPLIT", "holdout_split_binding required")
    if not isinstance(data["serial_dependence_declared"], bool):
        raise SingleHomeError("BAD_SERIAL_FLAG", "serial_dependence_declared must be bool")
    status = data["status"]
    if status not in POWER_PLAN_STATUSES:
        raise SingleHomeError("BAD_STATUS", f"unknown status {status!r}")
    if data.get("strong_model_confidence_substitute") is True:
        raise SingleHomeError(
            "STRONG_MODEL_SUBSTITUTE_FORBIDDEN",
            "model confidence cannot substitute for power plan",
        )
    expected = compute_content_hash(data)
    got = require_sha256("content_hash", data["content_hash"])
    if got != expected:
        raise SingleHomeError("TAMPER_HASH", "content_hash mismatch")
    assert_power_plan_fields(data)
    return data


def build_power_plan(**fields: Any) -> dict[str, Any]:
    data = dict(fields)
    data.setdefault("schema_version", SCHEMA_VERSIONS["power_plan_version"])
    data["content_hash"] = compute_content_hash(data)
    return validate_power_plan(data)


def is_statistically_adequate(plan: Mapping[str, Any]) -> bool:
    return validate_power_plan(plan)["status"] == "ADEQUATE"
