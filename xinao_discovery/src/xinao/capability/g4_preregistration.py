"""Fail-closed preregistration producer for the provider-neutral G4 batch seam.

This module deliberately stops before subject execution or hidden scoring.  It
turns a complete, fresh design into an immutable preregistration, a pending
obligation ledger, and the existing ``xinao.g4.experiment_batch.v1`` manifest.
Missing statistical design, reused outcome evidence, or a previously exposed
suite commitment yields HOLD and no preregistration or execution artifact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from xinao.canonical import canonical_sha256, parse_utc
from xinao.capability.g4_batch import build_g4_batch, validate_g4_batch
from xinao.capability.g4_hidden_benchmark.constants import FAMILY_IDS
from xinao.single_home.errors import SingleHomeError
from xinao.single_home.power_plan import validate_power_plan

FAMILIES = FAMILY_IDS
SUBJECT_CONFIGURATIONS = (
    "C0-ALGO",
    "C1-CHEAP",
    "C2-FRONTIER",
    "C3-HYBRID",
    "C4-HUMAN_TEMPLATE",
    "C5-RANDOM_SEARCH",
    "C6-ABLATION",
)

REQUEST_SCHEMA = "xinao.g4.preregistration_request.v1"
SPLIT_SCHEMA = "xinao.g4.split_manifest.v1"
PREREGISTRATION_SCHEMA = "xinao.g4.preregistration.v1"
OBLIGATION_LEDGER_SCHEMA = "xinao.g4.obligation_ledger.v1"
PREPARATION_RECEIPT_SCHEMA = "xinao.g4.preregistration_preparation.v1"

TERMINAL_HOLD = "G4_PREREGISTRATION_HOLD_NO_OUTCOME_ACCESS"
TERMINAL_READY = "G4_PREREGISTRATION_READY_NO_OUTCOME_ACCESS"

_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "batch_id",
        "batch_sequence",
        "work_key",
        "campaign_preregistration_ref",
        "campaign_preregistration_sha256",
        "families",
        "subject_configurations",
        "batch_cells",
        "split_manifest",
        "power_plans",
        "frozen_bindings",
        "unit_policy",
        "budget_policy",
        "stopping_policy",
        "analysis_policy",
        "campaign_contract_sha256",
        "retry_policy_sha256",
        "global_trial_ledger_ref",
        "global_trial_ledger_snapshot_sha256",
        "declared_prior_outcome_receipts",
        "reused_outcome_evidence_ids",
    }
)
_SPLIT_FIELDS = frozenset(
    {
        "schema_version",
        "split_manifest_id",
        "suite_version",
        "boundaries",
        "purge_cases",
        "embargo_cases",
        "holdout_exposure_budget",
        "content_hash",
    }
)
_BOUNDARY_NAMES = ("training", "heldout")
_BOUNDARY_FIELDS = frozenset({"case_count", "suite_commitment_sha256"})
_FROZEN_BINDING_FIELDS = frozenset(
    {
        "suite_sha256",
        "generator_sha256",
        "evaluator_sha256",
        "scoring_policy_sha256",
        "subject_adapter_sha256",
        "subject_public_cases_sha256",
    }
)
_UNIT_POLICY_FIELDS = frozenset(
    {
        "unit_of_analysis",
        "seed_role",
        "fixed_seed_ids",
        "model_identity_policy",
    }
)
_BATCH_CELL_FIELDS = frozenset(
    {
        "family_id",
        "public_case_id",
        "subject_configuration",
        "seed_id",
    }
)
_BUDGET_POLICY_FIELDS = frozenset({"max_batch_executions", "max_outcome_accesses"})
_STOPPING_POLICY_FIELDS = frozenset({"kind", "allow_early_success_stop", "underpowered_terminal"})
_ANALYSIS_POLICY_FIELDS = frozenset(
    {
        "primary_endpoint_policy_sha256",
        "threshold_policy_sha256",
        "contingency_policy_sha256",
        "deviation_policy_sha256",
        "power_analysis_policy_sha256_by_family",
    }
)
_PREREGISTRATION_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "batch_id",
        "batch_sequence",
        "work_key",
        "campaign_preregistration_ref",
        "campaign_preregistration_sha256",
        "request_sha256",
        "registered_at_utc",
        "families",
        "subject_configurations",
        "split_manifest_id",
        "split_manifest_sha256",
        "power_plan_sha256_by_family",
        "power_plan_set_sha256",
        "stopping_rule_sha256",
        "retry_policy_sha256",
        "holdout_budget_sha256",
        "campaign_contract_sha256",
        "global_trial_ledger_ref",
        "global_trial_ledger_snapshot_sha256",
        "frozen_bindings",
        "unit_policy",
        "batch_cells_sha256",
        "planned_execution_cells",
        "budget_policy",
        "stopping_policy",
        "analysis_policy",
        "registered_before_outcome_access",
        "outcome_accesses_at_registration",
        "retrospective_evidence_adoption_allowed",
        "terminal",
        "authority",
        "g4_closed",
        "g4_full",
        "completion_claim_allowed",
        "content_hash",
    }
)
_OBLIGATION_LEDGER_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "batch_id",
        "batch_sequence",
        "work_key",
        "preregistration_sha256",
        "planned_cells",
        "completed_cells",
        "remaining_cells",
        "obligations",
        "all_outcomes_unopened",
        "authority",
        "g4_closed",
        "g4_full",
        "completion_claim_allowed",
        "content_hash",
    }
)
_OBLIGATION_FIELDS = frozenset(
    {
        "obligation_id",
        "batch_id",
        "family_id",
        "public_case_id",
        "subject_configuration",
        "seed_id",
        "status",
        "outcome_accessed",
        "result_sha256",
    }
)


class G4FamilyBatchError(ValueError):
    """Malformed or unsafe bounded-family batch design."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _exact_fields(name: str, value: Mapping[str, Any], expected: frozenset[str]) -> None:
    keys = frozenset(value)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise G4FamilyBatchError(
            "FIELD_DRIFT",
            f"{name} fields differ; missing={missing}, extra={extra}",
        )


def _sha256(name: str, value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise G4FamilyBatchError("BAD_SHA256", f"{name} must be 64 lowercase hex")
    return value


def _nonempty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise G4FamilyBatchError("BAD_STRING", f"{name} must be a non-empty string")
    return value


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise G4FamilyBatchError("BAD_INTEGER", f"{name} must be an integer >= 1")
    return value


def _nonnegative_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise G4FamilyBatchError("BAD_INTEGER", f"{name} must be an integer >= 0")
    return value


def _sequence_of_unique_strings(
    name: str,
    value: Any,
    *,
    allowed: frozenset[str] | None = None,
    allow_empty: bool = False,
) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise G4FamilyBatchError("BAD_SEQUENCE", f"{name} must be a sequence")
    rows = list(value)
    if not allow_empty and not rows:
        raise G4FamilyBatchError("EMPTY_SEQUENCE", f"{name} must not be empty")
    if any(not isinstance(row, str) or not row for row in rows):
        raise G4FamilyBatchError("BAD_SEQUENCE_ITEM", f"{name} must contain strings")
    if len(rows) != len(set(rows)):
        raise G4FamilyBatchError("DUPLICATE_SEQUENCE_ITEM", f"{name} contains duplicates")
    if allowed is not None:
        unknown = sorted(set(rows) - allowed)
        if unknown:
            raise G4FamilyBatchError("UNKNOWN_SEQUENCE_ITEM", f"{name} has {unknown}")
    return rows


def _split_content_payload(split_manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in split_manifest.items() if key != "content_hash"}


def build_split_manifest(
    *,
    split_manifest_id: str,
    suite_version: str,
    boundaries: Mapping[str, Mapping[str, Any]],
    purge_cases: int,
    embargo_cases: int,
    holdout_exposure_budget: int,
) -> dict[str, Any]:
    """Build and validate the generator's training/heldout public commitments."""

    manifest: dict[str, Any] = {
        "schema_version": SPLIT_SCHEMA,
        "split_manifest_id": split_manifest_id,
        "suite_version": suite_version,
        "boundaries": {key: dict(value) for key, value in boundaries.items()},
        "purge_cases": purge_cases,
        "embargo_cases": embargo_cases,
        "holdout_exposure_budget": holdout_exposure_budget,
    }
    manifest["content_hash"] = canonical_sha256(manifest)
    return validate_split_manifest(manifest)


def validate_split_manifest(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise G4FamilyBatchError("BAD_SPLIT", "split_manifest must be an object")
    manifest = deepcopy(dict(raw))
    _exact_fields("split_manifest", manifest, _SPLIT_FIELDS)
    if manifest["schema_version"] != SPLIT_SCHEMA:
        raise G4FamilyBatchError("BAD_SPLIT_VERSION", "unexpected split manifest version")
    _nonempty_string("split_manifest_id", manifest["split_manifest_id"])
    _nonempty_string("suite_version", manifest["suite_version"])
    boundaries = manifest["boundaries"]
    if not isinstance(boundaries, Mapping):
        raise G4FamilyBatchError("BAD_BOUNDARIES", "boundaries must be an object")
    if set(boundaries) != set(_BOUNDARY_NAMES):
        raise G4FamilyBatchError(
            "BAD_BOUNDARIES",
            "boundaries must cover exactly training and heldout",
        )
    commitments: list[str] = []
    for name in _BOUNDARY_NAMES:
        boundary = boundaries[name]
        if not isinstance(boundary, Mapping):
            raise G4FamilyBatchError("BAD_BOUNDARY", f"{name} must be an object")
        _exact_fields(f"boundaries.{name}", boundary, _BOUNDARY_FIELDS)
        _positive_int(f"boundaries.{name}.case_count", boundary["case_count"])
        commitments.append(
            _sha256(
                f"boundaries.{name}.suite_commitment_sha256",
                boundary["suite_commitment_sha256"],
            )
        )
    if len(set(commitments)) != len(commitments):
        raise G4FamilyBatchError(
            "SUITE_COMMITMENT_REUSE",
            "training and heldout commitments must be distinct",
        )
    _nonnegative_int("purge_cases", manifest["purge_cases"])
    _nonnegative_int("embargo_cases", manifest["embargo_cases"])
    _positive_int("holdout_exposure_budget", manifest["holdout_exposure_budget"])
    got_hash = _sha256("split_manifest.content_hash", manifest["content_hash"])
    expected_hash = canonical_sha256(_split_content_payload(manifest))
    if got_hash != expected_hash:
        raise G4FamilyBatchError("TAMPER_HASH", "split manifest content_hash mismatch")
    return manifest


def _validate_request(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise G4FamilyBatchError("BAD_REQUEST", "request must be an object")
    request = deepcopy(dict(raw))
    _exact_fields("request", request, _REQUEST_FIELDS)
    if request["schema_version"] != REQUEST_SCHEMA:
        raise G4FamilyBatchError("BAD_REQUEST_VERSION", "unexpected request version")
    for field in (
        "campaign_id",
        "batch_id",
        "work_key",
        "campaign_preregistration_ref",
        "global_trial_ledger_ref",
    ):
        _nonempty_string(field, request[field])
    _positive_int("batch_sequence", request["batch_sequence"])
    for field in (
        "campaign_contract_sha256",
        "campaign_preregistration_sha256",
        "retry_policy_sha256",
        "global_trial_ledger_snapshot_sha256",
    ):
        _sha256(field, request[field])
    request["families"] = _sequence_of_unique_strings(
        "families",
        request["families"],
        allowed=frozenset(FAMILIES),
    )
    request["subject_configurations"] = _sequence_of_unique_strings(
        "subject_configurations",
        request["subject_configurations"],
        allowed=frozenset(SUBJECT_CONFIGURATIONS),
    )

    unit_policy = request["unit_policy"]
    if not isinstance(unit_policy, Mapping):
        raise G4FamilyBatchError("BAD_UNIT_POLICY", "unit_policy must be an object")
    _exact_fields("unit_policy", unit_policy, _UNIT_POLICY_FIELDS)
    if unit_policy["unit_of_analysis"] != "INDEPENDENT_HELDOUT_CASE":
        raise G4FamilyBatchError(
            "BAD_UNIT_OF_ANALYSIS",
            "unit_of_analysis must be INDEPENDENT_HELDOUT_CASE",
        )
    if unit_policy["seed_role"] != "WITHIN_CASE_REPLICATION_NOT_INDEPENDENT_N":
        raise G4FamilyBatchError(
            "BAD_SEED_ROLE",
            "seed repetitions must not be counted as independent observations",
        )
    fixed_seed_ids = unit_policy["fixed_seed_ids"]
    if (
        isinstance(fixed_seed_ids, (str, bytes))
        or not isinstance(fixed_seed_ids, Sequence)
        or not fixed_seed_ids
        or any(
            isinstance(seed_id, bool) or not isinstance(seed_id, int) or seed_id < 0
            for seed_id in fixed_seed_ids
        )
        or len(fixed_seed_ids) != len(set(fixed_seed_ids))
    ):
        raise G4FamilyBatchError(
            "BAD_FIXED_SEEDS",
            "fixed_seed_ids must be a non-empty unique non-negative integer array",
        )
    unit_policy = deepcopy(dict(unit_policy))
    unit_policy["fixed_seed_ids"] = list(fixed_seed_ids)
    _nonempty_string("model_identity_policy", unit_policy["model_identity_policy"])
    request["unit_policy"] = unit_policy

    raw_cells = request["batch_cells"]
    if isinstance(raw_cells, (str, bytes)) or not isinstance(raw_cells, Sequence) or not raw_cells:
        raise G4FamilyBatchError(
            "BAD_BATCH_CELLS",
            "batch_cells must be a non-empty array",
        )
    cells: list[dict[str, Any]] = []
    cell_identities: set[tuple[str, str, str, int]] = set()
    for index, raw_cell in enumerate(raw_cells):
        if not isinstance(raw_cell, Mapping):
            raise G4FamilyBatchError(
                "BAD_BATCH_CELL",
                f"batch_cells[{index}] must be an object",
            )
        cell = deepcopy(dict(raw_cell))
        _exact_fields(f"batch_cells[{index}]", cell, _BATCH_CELL_FIELDS)
        family = _nonempty_string(f"batch_cells[{index}].family_id", cell["family_id"])
        configuration = _nonempty_string(
            f"batch_cells[{index}].subject_configuration",
            cell["subject_configuration"],
        )
        public_case_id = _nonempty_string(
            f"batch_cells[{index}].public_case_id",
            cell["public_case_id"],
        )
        seed_id = cell["seed_id"]
        if isinstance(seed_id, bool) or not isinstance(seed_id, int) or seed_id < 0:
            raise G4FamilyBatchError(
                "BAD_SEED_ID",
                f"batch_cells[{index}].seed_id must be a non-negative integer",
            )
        if family not in request["families"]:
            raise G4FamilyBatchError(
                "BATCH_CELL_FAMILY_OUT_OF_SCOPE",
                f"batch_cells[{index}] family is not declared",
            )
        if configuration not in request["subject_configurations"]:
            raise G4FamilyBatchError(
                "BATCH_CELL_CONFIGURATION_OUT_OF_SCOPE",
                f"batch_cells[{index}] configuration is not declared",
            )
        if seed_id not in fixed_seed_ids:
            raise G4FamilyBatchError(
                "BATCH_CELL_SEED_OUT_OF_SCOPE",
                f"batch_cells[{index}] seed is not preregistered",
            )
        identity = (family, public_case_id, configuration, seed_id)
        if identity in cell_identities:
            raise G4FamilyBatchError(
                "DUPLICATE_BATCH_CELL",
                f"duplicate batch cell identity at index {index}",
            )
        cell_identities.add(identity)
        cells.append(cell)
    if {cell["family_id"] for cell in cells} != set(request["families"]):
        raise G4FamilyBatchError(
            "BATCH_FAMILY_COVERAGE",
            "batch cells must cover exactly the declared families",
        )
    if {cell["subject_configuration"] for cell in cells} != set(request["subject_configurations"]):
        raise G4FamilyBatchError(
            "BATCH_CONFIGURATION_COVERAGE",
            "batch cells must cover exactly the declared configurations",
        )
    grouped_seed_ids: dict[tuple[str, str, str], set[int]] = {}
    for cell in cells:
        group = (
            cell["family_id"],
            cell["public_case_id"],
            cell["subject_configuration"],
        )
        grouped_seed_ids.setdefault(group, set()).add(cell["seed_id"])
    expected_seed_ids = set(fixed_seed_ids)
    if any(seed_ids != expected_seed_ids for seed_ids in grouped_seed_ids.values()):
        raise G4FamilyBatchError(
            "INCOMPLETE_WITHIN_CASE_SEEDS",
            "every family/case/configuration cell must include every fixed seed",
        )
    request["batch_cells"] = sorted(
        cells,
        key=lambda cell: (
            cell["family_id"],
            cell["public_case_id"],
            cell["subject_configuration"],
            cell["seed_id"],
        ),
    )
    request["split_manifest"] = validate_split_manifest(request["split_manifest"])

    power_plans = request["power_plans"]
    if not isinstance(power_plans, Mapping):
        raise G4FamilyBatchError("BAD_POWER_PLANS", "power_plans must be an object")
    if set(power_plans) != set(request["families"]):
        raise G4FamilyBatchError(
            "POWER_PLAN_COVERAGE",
            "power_plans must cover exactly the requested families",
        )
    validated_plans: dict[str, dict[str, Any]] = {}
    for family in request["families"]:
        try:
            plan = validate_power_plan(power_plans[family])
        except (SingleHomeError, TypeError, ValueError) as exc:
            raise G4FamilyBatchError(
                "POWER_PLAN_INVALID",
                f"{family} power plan invalid: {exc}",
            ) from exc
        if plan["family_id"] != family:
            raise G4FamilyBatchError(
                "POWER_PLAN_FAMILY_MISMATCH",
                f"{family} power plan binds {plan['family_id']}",
            )
        if plan["holdout_split_binding"] != request["split_manifest"]["content_hash"]:
            raise G4FamilyBatchError(
                "POWER_PLAN_SPLIT_MISMATCH",
                f"{family} does not bind the split manifest hash",
            )
        if plan["status"] != "ADEQUATE":
            raise G4FamilyBatchError(
                "POWER_PLAN_NOT_ADEQUATE",
                f"{family} power plan status is {plan['status']}",
            )
        validated_plans[family] = plan
        independent_cases = {
            cell["public_case_id"] for cell in request["batch_cells"] if cell["family_id"] == family
        }
        if len(independent_cases) > plan["max_budget_trials"]:
            raise G4FamilyBatchError(
                "POWER_PLAN_CASE_BUDGET_EXCEEDED",
                f"{family} batch has more independent cases than its power-plan budget",
            )
    request["power_plans"] = validated_plans

    frozen_bindings = request["frozen_bindings"]
    if not isinstance(frozen_bindings, Mapping):
        raise G4FamilyBatchError("BAD_FROZEN_BINDINGS", "frozen_bindings must be an object")
    _exact_fields("frozen_bindings", frozen_bindings, _FROZEN_BINDING_FIELDS)
    for name, value in frozen_bindings.items():
        _sha256(f"frozen_bindings.{name}", value)

    budget_policy = request["budget_policy"]
    if not isinstance(budget_policy, Mapping):
        raise G4FamilyBatchError("BAD_BUDGET_POLICY", "budget_policy must be an object")
    _exact_fields("budget_policy", budget_policy, _BUDGET_POLICY_FIELDS)
    max_batch_executions = _positive_int(
        "max_batch_executions",
        budget_policy["max_batch_executions"],
    )
    max_outcome_accesses = _positive_int(
        "max_outcome_accesses",
        budget_policy["max_outcome_accesses"],
    )
    planned_cells = len(request["batch_cells"])
    if planned_cells > max_batch_executions:
        raise G4FamilyBatchError(
            "BATCH_BUDGET_EXCEEDED",
            f"planned executions {planned_cells} exceed bounded budget {max_batch_executions}",
        )
    if max_outcome_accesses < planned_cells:
        raise G4FamilyBatchError(
            "OUTCOME_ACCESS_BUDGET_TOO_SMALL",
            "each planned family/configuration/repeat cell needs one outcome access",
        )
    if max_outcome_accesses > request["split_manifest"]["holdout_exposure_budget"]:
        raise G4FamilyBatchError(
            "HOLDOUT_EXPOSURE_BUDGET_EXCEEDED",
            "batch outcome budget exceeds the split manifest budget",
        )

    stopping_policy = request["stopping_policy"]
    if not isinstance(stopping_policy, Mapping):
        raise G4FamilyBatchError("BAD_STOPPING_POLICY", "stopping_policy must be an object")
    _exact_fields("stopping_policy", stopping_policy, _STOPPING_POLICY_FIELDS)
    if stopping_policy["kind"] != "FIXED_BUDGET_NO_EARLY_SUCCESS":
        raise G4FamilyBatchError(
            "BAD_STOPPING_RULE",
            "only FIXED_BUDGET_NO_EARLY_SUCCESS is accepted",
        )
    if stopping_policy["allow_early_success_stop"] is not False:
        raise G4FamilyBatchError(
            "EARLY_SUCCESS_STOP_FORBIDDEN",
            "successful outcomes cannot stop a formal batch early",
        )
    if stopping_policy["underpowered_terminal"] not in {"UNDERPOWERED", "UNKNOWN"}:
        raise G4FamilyBatchError(
            "BAD_UNDERPOWERED_TERMINAL",
            "underpowered_terminal must be UNDERPOWERED or UNKNOWN",
        )

    analysis_policy = request["analysis_policy"]
    if not isinstance(analysis_policy, Mapping):
        raise G4FamilyBatchError("BAD_ANALYSIS_POLICY", "analysis_policy must be an object")
    _exact_fields("analysis_policy", analysis_policy, _ANALYSIS_POLICY_FIELDS)
    for name, value in analysis_policy.items():
        if name == "power_analysis_policy_sha256_by_family":
            continue
        _sha256(f"analysis_policy.{name}", value)
    power_analysis_policies = analysis_policy["power_analysis_policy_sha256_by_family"]
    if not isinstance(power_analysis_policies, Mapping):
        raise G4FamilyBatchError(
            "BAD_POWER_ANALYSIS_POLICIES",
            "power_analysis_policy_sha256_by_family must be an object",
        )
    if set(power_analysis_policies) != set(request["families"]):
        raise G4FamilyBatchError(
            "POWER_ANALYSIS_POLICY_COVERAGE",
            "power analysis policies must cover exactly the requested families",
        )
    for family in request["families"]:
        _sha256(
            f"power_analysis_policy_sha256_by_family.{family}",
            power_analysis_policies[family],
        )

    request["declared_prior_outcome_receipts"] = _sequence_of_unique_strings(
        "declared_prior_outcome_receipts",
        request["declared_prior_outcome_receipts"],
        allow_empty=True,
    )
    if request["declared_prior_outcome_receipts"]:
        raise G4FamilyBatchError(
            "RETROSPECTIVE_OUTCOME_ACCESS_FORBIDDEN",
            "a batch with prior outcome access cannot be preregistered",
        )
    request["reused_outcome_evidence_ids"] = _sequence_of_unique_strings(
        "reused_outcome_evidence_ids",
        request["reused_outcome_evidence_ids"],
        allow_empty=True,
    )
    if request["reused_outcome_evidence_ids"]:
        raise G4FamilyBatchError(
            "RETROSPECTIVE_EVIDENCE_REUSE_FORBIDDEN",
            "prior outcome evidence cannot be adopted into a fresh batch",
        )
    return request


def _suite_commitments(split_manifest: Mapping[str, Any]) -> set[str]:
    return {
        str(split_manifest["boundaries"][name]["suite_commitment_sha256"])
        for name in _BOUNDARY_NAMES
    }


def _derived_scientific_pins(request: Mapping[str, Any]) -> dict[str, str]:
    power_plan_set = {
        "schema_version": "xinao.g4.power_plan_set.v1",
        "power_plan_sha256_by_family": {
            family: request["power_plans"][family]["content_hash"] for family in request["families"]
        },
    }
    holdout_budget = {
        "schema_version": "xinao.g4.holdout_budget.v1",
        "split_manifest_sha256": request["split_manifest"]["content_hash"],
        "holdout_exposure_budget": request["split_manifest"]["holdout_exposure_budget"],
        "max_outcome_accesses": request["budget_policy"]["max_outcome_accesses"],
    }
    return {
        "power_plan_sha256": canonical_sha256(power_plan_set),
        "stopping_rule_sha256": canonical_sha256(request["stopping_policy"]),
        "holdout_budget_sha256": canonical_sha256(holdout_budget),
    }


def _build_preregistration(
    request: Mapping[str, Any],
    *,
    registered_at_utc: str,
) -> dict[str, Any]:
    request_hash = canonical_sha256(request)
    derived_pins = _derived_scientific_pins(request)
    body: dict[str, Any] = {
        "schema_version": PREREGISTRATION_SCHEMA,
        "campaign_id": request["campaign_id"],
        "batch_id": request["batch_id"],
        "batch_sequence": request["batch_sequence"],
        "work_key": request["work_key"],
        "campaign_preregistration_ref": request["campaign_preregistration_ref"],
        "campaign_preregistration_sha256": request["campaign_preregistration_sha256"],
        "request_sha256": request_hash,
        "registered_at_utc": registered_at_utc,
        "families": list(request["families"]),
        "subject_configurations": list(request["subject_configurations"]),
        "split_manifest_id": request["split_manifest"]["split_manifest_id"],
        "split_manifest_sha256": request["split_manifest"]["content_hash"],
        "power_plan_sha256_by_family": {
            family: request["power_plans"][family]["content_hash"] for family in request["families"]
        },
        "power_plan_set_sha256": derived_pins["power_plan_sha256"],
        "stopping_rule_sha256": derived_pins["stopping_rule_sha256"],
        "retry_policy_sha256": request["retry_policy_sha256"],
        "holdout_budget_sha256": derived_pins["holdout_budget_sha256"],
        "campaign_contract_sha256": request["campaign_contract_sha256"],
        "global_trial_ledger_ref": request["global_trial_ledger_ref"],
        "global_trial_ledger_snapshot_sha256": request["global_trial_ledger_snapshot_sha256"],
        "frozen_bindings": deepcopy(request["frozen_bindings"]),
        "unit_policy": deepcopy(request["unit_policy"]),
        "batch_cells_sha256": canonical_sha256(request["batch_cells"]),
        "planned_execution_cells": len(request["batch_cells"]),
        "budget_policy": deepcopy(request["budget_policy"]),
        "stopping_policy": deepcopy(request["stopping_policy"]),
        "analysis_policy": deepcopy(request["analysis_policy"]),
        "registered_before_outcome_access": True,
        "outcome_accesses_at_registration": 0,
        "retrospective_evidence_adoption_allowed": False,
        "terminal": TERMINAL_READY,
        "authority": False,
        "g4_closed": False,
        "g4_full": False,
        "completion_claim_allowed": False,
    }
    body["content_hash"] = canonical_sha256(body)
    return body


def _build_obligation_ledger(
    request: Mapping[str, Any],
    preregistration: Mapping[str, Any],
) -> dict[str, Any]:
    obligations: list[dict[str, Any]] = []
    for cell in request["batch_cells"]:
        cell_identity = deepcopy(cell)
        obligations.append(
            {
                "obligation_id": canonical_sha256(cell_identity),
                "batch_id": request["batch_id"],
                **cell_identity,
                "status": "PENDING",
                "outcome_accessed": False,
                "result_sha256": None,
            }
        )
    body: dict[str, Any] = {
        "schema_version": OBLIGATION_LEDGER_SCHEMA,
        "campaign_id": request["campaign_id"],
        "batch_id": request["batch_id"],
        "batch_sequence": request["batch_sequence"],
        "work_key": request["work_key"],
        "preregistration_sha256": preregistration["content_hash"],
        "planned_cells": len(obligations),
        "completed_cells": 0,
        "remaining_cells": len(obligations),
        "obligations": obligations,
        "all_outcomes_unopened": True,
        "authority": False,
        "g4_closed": False,
        "g4_full": False,
        "completion_claim_allowed": False,
    }
    body["content_hash"] = canonical_sha256(body)
    return body


def _build_batch_manifest(
    request: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    obligation_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    pins = _derived_scientific_pins(request)
    return build_g4_batch(
        campaign_id=request["campaign_id"],
        batch_id=request["batch_id"],
        batch_sequence=request["batch_sequence"],
        work_key=request["work_key"],
        cell_ids=[row["obligation_id"] for row in obligation_ledger["obligations"]],
        campaign_contract_sha256=request["campaign_contract_sha256"],
        suite_sha256=request["frozen_bindings"]["suite_sha256"],
        evaluator_sha256=request["frozen_bindings"]["evaluator_sha256"],
        policy_sha256=request["frozen_bindings"]["scoring_policy_sha256"],
        preregistration_sha256=preregistration["content_hash"],
        power_plan_sha256=pins["power_plan_sha256"],
        stopping_rule_sha256=pins["stopping_rule_sha256"],
        retry_policy_sha256=request["retry_policy_sha256"],
        holdout_budget_sha256=pins["holdout_budget_sha256"],
        global_trial_ledger_ref=request["global_trial_ledger_ref"],
        global_trial_ledger_snapshot_sha256=request["global_trial_ledger_snapshot_sha256"],
    )


def validate_g4_preregistration_package(
    *,
    request: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    obligation_ledger: Mapping[str, Any],
    batch_manifest: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Validate a complete pre-outcome package against the one G4 batch seam."""

    validated_request = _validate_request(request)
    if not isinstance(preregistration, Mapping):
        raise G4FamilyBatchError("BAD_PREREGISTRATION", "preregistration must be an object")
    observed_preregistration = deepcopy(dict(preregistration))
    _exact_fields(
        "preregistration",
        observed_preregistration,
        _PREREGISTRATION_FIELDS,
    )
    registered_at_utc = observed_preregistration.get("registered_at_utc")
    try:
        parse_utc(registered_at_utc)
    except (TypeError, ValueError) as exc:
        raise G4FamilyBatchError(
            "BAD_REGISTRATION_TIMESTAMP",
            "registered_at_utc must use the pinned UTC millisecond profile",
        ) from exc
    expected_preregistration = _build_preregistration(
        validated_request,
        registered_at_utc=str(registered_at_utc),
    )
    if observed_preregistration != expected_preregistration:
        raise G4FamilyBatchError(
            "PREREGISTRATION_MISMATCH",
            "preregistration does not match the validated request",
        )

    if not isinstance(obligation_ledger, Mapping):
        raise G4FamilyBatchError(
            "BAD_OBLIGATION_LEDGER",
            "obligation_ledger must be an object",
        )
    observed_ledger = deepcopy(dict(obligation_ledger))
    _exact_fields(
        "obligation_ledger",
        observed_ledger,
        _OBLIGATION_LEDGER_FIELDS,
    )
    obligations = observed_ledger.get("obligations")
    if not isinstance(obligations, list):
        raise G4FamilyBatchError(
            "BAD_OBLIGATIONS",
            "obligations must be an array",
        )
    for obligation in obligations:
        if not isinstance(obligation, Mapping):
            raise G4FamilyBatchError(
                "BAD_OBLIGATION",
                "each obligation must be an object",
            )
        _exact_fields("obligation", obligation, _OBLIGATION_FIELDS)
    expected_ledger = _build_obligation_ledger(
        validated_request,
        expected_preregistration,
    )
    if observed_ledger != expected_ledger:
        raise G4FamilyBatchError(
            "OBLIGATION_LEDGER_MISMATCH",
            "obligation ledger does not match the preregistered design",
        )

    try:
        observed_batch = validate_g4_batch(batch_manifest)
    except (TypeError, ValueError) as exc:
        raise G4FamilyBatchError(
            "BATCH_MANIFEST_INVALID",
            f"provider-neutral batch manifest is invalid: {exc}",
        ) from exc
    expected_batch = _build_batch_manifest(
        validated_request,
        expected_preregistration,
        expected_ledger,
    )
    if observed_batch != expected_batch:
        raise G4FamilyBatchError(
            "BATCH_MANIFEST_MISMATCH",
            "batch manifest does not match the preregistration and obligations",
        )
    return {
        "request": validated_request,
        "preregistration": expected_preregistration,
        "obligation_ledger": expected_ledger,
        "batch_manifest": expected_batch,
    }


def prepare_g4_preregistration(
    raw_request: Mapping[str, Any],
    *,
    prepared_at_utc: str | None = None,
    known_prior_outcome_receipts: Sequence[str] = (),
    forbidden_suite_commitments: Sequence[str] = (),
) -> dict[str, Any]:
    """Adjudicate a design without touching any hidden outcome.

    READY includes the preregistration, pending ledger, and the existing
    provider-neutral batch manifest. HOLD includes only a preparation receipt;
    callers must not publish a preregistration or run a subject from a HOLD
    result.
    """

    problems: list[str] = []
    request: dict[str, Any] | None = None
    try:
        if prepared_at_utc is None:
            raise G4FamilyBatchError(
                "REGISTRATION_TIMESTAMP_REQUIRED",
                "prepared_at_utc is required for a timestamped preregistration",
            )
        try:
            parse_utc(prepared_at_utc)
        except (TypeError, ValueError) as exc:
            raise G4FamilyBatchError(
                "BAD_REGISTRATION_TIMESTAMP",
                "prepared_at_utc must use the pinned UTC millisecond profile",
            ) from exc
        known_receipts = _sequence_of_unique_strings(
            "known_prior_outcome_receipts",
            known_prior_outcome_receipts,
            allow_empty=True,
        )
        if known_receipts:
            raise G4FamilyBatchError(
                "RETROSPECTIVE_OUTCOME_ACCESS_FORBIDDEN",
                "the owner supplied known prior outcome receipts for this batch",
            )
        forbidden_commitments = {
            _sha256("forbidden_suite_commitment", value)
            for value in _sequence_of_unique_strings(
                "forbidden_suite_commitments",
                forbidden_suite_commitments,
                allow_empty=True,
            )
        }
        request = _validate_request(raw_request)
        reused_commitments = sorted(
            _suite_commitments(request["split_manifest"]) & forbidden_commitments
        )
        if reused_commitments:
            raise G4FamilyBatchError(
                "SUITE_COMMITMENT_REUSE",
                f"split reuses forbidden commitments {reused_commitments}",
            )
    except G4FamilyBatchError as exc:
        problems.append(exc.code)

    receipt: dict[str, Any] = {
        "schema_version": PREPARATION_RECEIPT_SCHEMA,
        "batch_id": (
            request["batch_id"]
            if request is not None
            else str(raw_request.get("batch_id") or "INVALID")
            if isinstance(raw_request, Mapping)
            else "INVALID"
        ),
        "request_sha256": canonical_sha256(raw_request),
        "prepared_at_utc": prepared_at_utc,
        "terminal": TERMINAL_HOLD if problems else TERMINAL_READY,
        "problems": problems,
        "outcome_accessed": False,
        "preregistration_included": not problems,
        "authority": False,
        "g4_closed": False,
        "g4_full": False,
        "completion_claim_allowed": False,
    }
    if problems:
        receipt["content_hash"] = canonical_sha256(receipt)
        return {
            "terminal": TERMINAL_HOLD,
            "receipt": receipt,
            "request": None,
            "preregistration": None,
            "obligation_ledger": None,
            "batch_manifest": None,
        }

    assert request is not None
    assert prepared_at_utc is not None
    preregistration = _build_preregistration(
        request,
        registered_at_utc=prepared_at_utc,
    )
    obligation_ledger = _build_obligation_ledger(request, preregistration)
    batch_manifest = _build_batch_manifest(
        request,
        preregistration,
        obligation_ledger,
    )
    package = validate_g4_preregistration_package(
        request=request,
        preregistration=preregistration,
        obligation_ledger=obligation_ledger,
        batch_manifest=batch_manifest,
    )
    request = package["request"]
    preregistration = package["preregistration"]
    obligation_ledger = package["obligation_ledger"]
    batch_manifest = package["batch_manifest"]
    receipt["preregistration_sha256"] = preregistration["content_hash"]
    receipt["obligation_ledger_sha256"] = obligation_ledger["content_hash"]
    receipt["batch_manifest_sha256"] = batch_manifest["content_hash"]
    receipt["content_hash"] = canonical_sha256(receipt)
    return {
        "terminal": TERMINAL_READY,
        "receipt": receipt,
        "request": request,
        "preregistration": preregistration,
        "obligation_ledger": obligation_ledger,
        "batch_manifest": batch_manifest,
    }


__all__ = [
    "FAMILIES",
    "OBLIGATION_LEDGER_SCHEMA",
    "PREPARATION_RECEIPT_SCHEMA",
    "PREREGISTRATION_SCHEMA",
    "REQUEST_SCHEMA",
    "SPLIT_SCHEMA",
    "SUBJECT_CONFIGURATIONS",
    "TERMINAL_HOLD",
    "TERMINAL_READY",
    "G4FamilyBatchError",
    "build_split_manifest",
    "prepare_g4_preregistration",
    "validate_g4_preregistration_package",
    "validate_split_manifest",
]
