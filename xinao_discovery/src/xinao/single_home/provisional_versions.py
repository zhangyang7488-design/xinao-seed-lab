"""Provisional schema version pins for the single-home interface.

Codex must pin final versions before main-tree promotion.
Pins intentionally embed ``.provisional.`` and share G5 path strings so
G3/G5 soft-align collapses to one identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

PROVISIONAL: Final[bool] = True
PROVISIONAL_LABEL: Final[str] = "provisional"

SCHEMA_VERSIONS: Final[Mapping[str, str]] = {
    "global_trial_ledger_export": ("xinao.gates.g5.global_trial_ledger_export.provisional.v1"),
    "power_plan_version": "xinao.gates.g5.power_plan_version.provisional.v1",
    "ess_report": "xinao.gates.g5.effective_sample_size_report.provisional.v1",
}

LOGICAL_OBJECT_IDS: Final[Mapping[str, str]] = {
    "GlobalTrialLedger": "xinao.global_trial_ledger.v1",
    "PowerPlanVersion": "xinao.power_plan_version.v1",
    "EffectiveSampleSizeReport": "xinao.effective_sample_size_report.v1",
}

STAGE_GATE: Final[str] = "STAGE_GATED_BEHIND_G3_G5_CODEX_FAN_IN"

COORDINATES_WITH_PACKAGES: Final[tuple[str, ...]] = (
    "PKG-CODE-G3-LOOP-CONTRACTS",
    "PKG-CODE-G5-ADM-PURE-CORE",
)

# Frozen required field contracts — silent drift DENY.
ENTRY_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {
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
)

EXPORT_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "logical_object_id",
        "total_trials",
        "valid_equivalence_clusters",
        "discarded_paths",
        "failed_or_timeout_paths",
        "statuses_observed",
        "work_keys",
        "export_hash",
        "stage_gate",
        "authoritative",
        "not_market_lab_ledger",
        "no_durable_state",
        "coordinates_with_packages",
    }
)

POWER_PLAN_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "plan_id",
    "family_id",
    "mde",
    "target_power",
    "max_budget_trials",
    "holdout_split_binding",
    "serial_dependence_declared",
    "status",
    "content_hash",
)

ESS_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "ess_report_id",
    "power_plan_ref",
    "power_plan_hash",
    "nominal_n",
    "effective_n",
    "serial_dependence_adjusted",
    "input_hashes",
    "content_hash",
)

TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "REGISTERED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "TIMEOUT",
        "DISCARDED",
        "NO_ACTION",
    }
)

POWER_PLAN_STATUSES: Final[frozenset[str]] = frozenset({"PLANNED", "UNDERPOWERED", "ADEQUATE"})

# Historical dual homes — not current truth.
FORBIDDEN_PARALLEL_HOME_MODULES: Final[frozenset[str]] = frozenset(
    {
        "drafts.xinao.g3.global_trial_ledger",
        "drafts.xinao.gates.g5_global_trial_ledger",
        "drafts.xinao.g3.power_plan_version",
        "drafts.xinao.gates.g5_power_plan",
    }
)

SINGLE_HOME_MODULES: Final[frozenset[str]] = frozenset(
    {
        "xinao.single_home.global_trial_ledger",
        "xinao.single_home.power_plan",
        "xinao.single_home.ess_report",
    }
)

# Facets that must not be claimed as GlobalTrialLedger.
NOT_LEDGER_IDENTITIES: Final[frozenset[str]] = frozenset(
    {
        "ResearchErrorBudgetPolicy",
        "FamilyErrorBudgetLedger",
        "HoldoutExposureLedger",
        "StatisticalValidityReport",
        "ResearchQuestion",
        "write_research_trial_ledger",
    }
)


def assert_provisional_version(schema_version: str) -> None:
    if PROVISIONAL_LABEL not in schema_version:
        raise ValueError(
            f"draft schema_version must remain provisional until Codex pin: {schema_version!r}"
        )
