"""Frozen field contracts and silent-drift denial helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet

from xinao.single_home.errors import FieldDriftDenyError
from xinao.single_home.provisional_versions import (
    ENTRY_REQUIRED_FIELDS,
    ESS_REQUIRED_FIELDS,
    EXPORT_REQUIRED_FIELDS,
    POWER_PLAN_REQUIRED_FIELDS,
)


def assert_fields_match_contract(
    *,
    object_name: str,
    observed: Iterable[str],
    required: AbstractSet[str] | Iterable[str],
    allow_extra: bool = True,
) -> None:
    """Deny silent removal of required fields; optionally allow extras."""

    obs = set(observed)
    req = set(required)
    missing = sorted(req - obs)
    if missing:
        raise FieldDriftDenyError(
            "SILENT_FIELD_DRIFT_FORBIDDEN",
            f"{object_name} missing required fields: {missing}",
        )
    if not allow_extra:
        extra = sorted(obs - req)
        if extra:
            raise FieldDriftDenyError(
                "SILENT_FIELD_DRIFT_FORBIDDEN",
                f"{object_name} unexpected extra required-set fields: {extra}",
            )


def assert_entry_fields(entry: Mapping[str, object]) -> None:
    assert_fields_match_contract(
        object_name="GlobalTrialLedger.entry",
        observed=entry.keys(),
        required=ENTRY_REQUIRED_FIELDS,
        allow_extra=True,  # terminal events may add event=
    )


def assert_export_fields(export: Mapping[str, object]) -> None:
    assert_fields_match_contract(
        object_name="GlobalTrialLedger.export",
        observed=export.keys(),
        required=EXPORT_REQUIRED_FIELDS,
        allow_extra=False,
    )


def assert_power_plan_fields(plan: Mapping[str, object]) -> None:
    assert_fields_match_contract(
        object_name="PowerPlanVersion",
        observed=plan.keys(),
        required=POWER_PLAN_REQUIRED_FIELDS,
        allow_extra=True,
    )


def assert_ess_fields(report: Mapping[str, object]) -> None:
    assert_fields_match_contract(
        object_name="EffectiveSampleSizeReport",
        observed=report.keys(),
        required=ESS_REQUIRED_FIELDS,
        allow_extra=True,
    )


def compare_field_sets(
    *,
    left_name: str,
    left: AbstractSet[str],
    right_name: str,
    right: AbstractSet[str],
) -> None:
    """Deny any mismatch between two claimed homes' required field sets."""

    if set(left) != set(right):
        only_left = sorted(set(left) - set(right))
        only_right = sorted(set(right) - set(left))
        raise FieldDriftDenyError(
            "SILENT_FIELD_DRIFT_FORBIDDEN",
            f"{left_name} vs {right_name} field drift "
            f"only_left={only_left} only_right={only_right}",
        )
