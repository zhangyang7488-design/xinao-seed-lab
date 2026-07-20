"""Single-home EffectiveSampleSizeReport pure validator (AF-005 / O38).

G5 owns ESS. Must bind PowerPlanVersion hash and plan_id; serial-dependence fail-closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from xinao.single_home.errors import SingleHomeError
from xinao.single_home.field_contracts import assert_ess_fields
from xinao.single_home.hashing import content_sha256, require_sha256
from xinao.single_home.power_plan import compute_content_hash as plan_hash
from xinao.single_home.power_plan import validate_power_plan
from xinao.single_home.provisional_versions import (
    ESS_REQUIRED_FIELDS,
    LOGICAL_OBJECT_IDS,
    SCHEMA_VERSIONS,
    assert_provisional_version,
)

REQUIRED = ESS_REQUIRED_FIELDS
LOGICAL_OBJECT_ID = LOGICAL_OBJECT_IDS["EffectiveSampleSizeReport"]
HOME_MODULE = "xinao.single_home.ess_report"


def _reject_bool(name: str, value: object, *, code: str) -> None:
    """bool is a subclass of int; reject it wherever a real number is required."""

    if isinstance(value, bool):
        raise SingleHomeError(code, f"{name} must be a real number, not bool")


def content_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {k: report[k] for k in report if k != "content_hash"}


def compute_content_hash(report: Mapping[str, Any]) -> str:
    return content_sha256(content_payload(report))


def validate_ess_report(
    raw: Mapping[str, Any],
    *,
    power_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise SingleHomeError("BAD_TYPE", "ess report must be object")
    data = dict(raw)
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise SingleHomeError("MISSING_FIELDS", f"missing {missing}")
    assert_provisional_version(str(data["schema_version"]))
    if data["schema_version"] != SCHEMA_VERSIONS["ess_report"]:
        raise SingleHomeError("BAD_VERSION", "unexpected ess schema_version")
    if not isinstance(data["power_plan_ref"], str) or not data["power_plan_ref"]:
        raise SingleHomeError("BAD_PLAN_REF", "power_plan_ref required")
    require_sha256("power_plan_hash", data["power_plan_hash"])
    _reject_bool("nominal_n", data["nominal_n"], code="BAD_NOMINAL_N")
    if not isinstance(data["nominal_n"], (int, float)) or data["nominal_n"] <= 0:
        raise SingleHomeError("BAD_NOMINAL_N", "nominal_n must be positive")
    _reject_bool("effective_n", data["effective_n"], code="BAD_ESS")
    if not isinstance(data["effective_n"], (int, float)) or data["effective_n"] <= 0:
        raise SingleHomeError("BAD_ESS", "effective_n must be positive")
    if float(data["effective_n"]) > float(data["nominal_n"]):
        raise SingleHomeError("ESS_GT_NOMINAL", "effective_n cannot exceed nominal_n")
    if not isinstance(data["serial_dependence_adjusted"], bool):
        raise SingleHomeError("BAD_SERIAL_ADJ", "serial_dependence_adjusted must be bool")
    ih = data["input_hashes"]
    if not isinstance(ih, Mapping) or not ih:
        raise SingleHomeError("BAD_INPUT_HASHES", "input_hashes required")
    for k, v in ih.items():
        require_sha256(f"input_hashes.{k}", v)
    if power_plan is not None:
        plan = validate_power_plan(power_plan)
        # Bind to exact governed power-plan identity, not only caller-consistent hash.
        if data["power_plan_ref"] != plan["plan_id"]:
            raise SingleHomeError(
                "PLAN_REF_MISMATCH",
                "ess power_plan_ref must equal governed plan_id",
            )
        if data["power_plan_hash"] != plan_hash(plan):
            raise SingleHomeError("PLAN_HASH_MISMATCH", "ess not bound to provided plan")
        if plan["serial_dependence_declared"] and not data["serial_dependence_adjusted"]:
            raise SingleHomeError(
                "SERIAL_DEPENDENCE_IGNORED",
                "ESS must adjust when plan declares serial dependence",
            )
    expected = compute_content_hash(data)
    got = require_sha256("content_hash", data["content_hash"])
    if got != expected:
        raise SingleHomeError("TAMPER_HASH", "content_hash mismatch")
    assert_ess_fields(data)
    return data


def build_ess_report(**fields: Any) -> dict[str, Any]:
    data = dict(fields)
    data.setdefault("schema_version", SCHEMA_VERSIONS["ess_report"])
    data["content_hash"] = compute_content_hash(data)
    return validate_ess_report(data)
