"""Initialize a fresh no-outcome G4 campaign and its first bounded batch.

This is a thin owner-side adapter over the existing hidden-suite generator,
RealHiddenBootstrapVault, GlobalTrialLedger, PowerPlan, and provider-neutral
G4 batch preregistration producer. It materializes no subject output and never
invokes the evaluator.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import secrets
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
SEAM_SRC = REPO_ROOT / "projects" / "g4-hidden-capability-seam" / "src"
for source_root in (str(XINAO_SRC), str(SEAM_SRC)):
    if source_root not in sys.path:
        sys.path.insert(0, source_root)

from g4_hidden_capability_seam.canonical import write_json  # noqa: E402
from g4_hidden_capability_seam.real_vault import (  # noqa: E402
    RealHiddenBootstrapVault,
)
from xinao.canonical import canonical_sha256, format_utc  # noqa: E402
from xinao.capability.g4_bootstrap_scoring import FORMAL_CASE_FAMILIES  # noqa: E402
from xinao.capability.g4_hidden_benchmark import (  # noqa: E402
    GeneratorProfile,
    generate_full_family_suites,
)
from xinao.capability.g4_hidden_benchmark.constants import FAMILY_IDS  # noqa: E402
from xinao.capability.g4_hidden_benchmark.public_safety import (  # noqa: E402
    scan_forbidden_public_keys,
    scan_h03_public_hints,
    scan_h04_public_hints,
)
from xinao.capability.g4_preregistration import (  # noqa: E402
    REQUEST_SCHEMA,
    SUBJECT_CONFIGURATIONS,
    TERMINAL_READY,
    build_split_manifest,
    prepare_g4_preregistration,
)
from xinao.single_home.global_trial_ledger import GlobalTrialLedger  # noqa: E402
from xinao.single_home.power_plan import build_power_plan  # noqa: E402

CAMPAIGN_PREREGISTRATION_SCHEMA = "xinao.g4.v7.preregistration_freeze_candidate.v1"
OWNER_ACCEPTANCE_SCHEMA = "xinao.g4.v7.owner_content_acceptance.v1"
INITIALIZATION_SCHEMA = "xinao.g4.fresh_campaign_initialization.v1"
DEFAULT_ADAPTER = (
    REPO_ROOT
    / "projects"
    / "g4-hidden-capability-seam"
    / "adapters"
    / "promptfoo_c0_bootstrap_adapter.py"
)
DEFAULT_EVALUATOR = (
    REPO_ROOT / "xinao_discovery" / "src" / "xinao" / "capability" / "g4_bootstrap_scoring.py"
)


class FreshCampaignError(ValueError):
    """The accepted campaign design cannot be materialized safely."""


def _raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FreshCampaignError(f"{path} must contain one JSON object")
    return value


def _copy_exact_source(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    if _raw_sha256(target) != _raw_sha256(source):
        raise FreshCampaignError(f"source copy hash drifted: {source}")


def _validate_evaluator_family_support(
    evaluator_path: Path,
    families: Sequence[str],
) -> dict[str, Any]:
    requested = list(families)
    if not requested or len(requested) != len(set(requested)):
        raise FreshCampaignError("requested evaluator families must be non-empty and unique")
    try:
        tree = ast.parse(evaluator_path.read_text(encoding="utf-8"), filename=str(evaluator_path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise FreshCampaignError(f"evaluator support registry is unreadable: {exc}") from exc
    registry: tuple[str, ...] | None = None
    entrypoint_present = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entrypoint_present = entrypoint_present or node.name == "score_formal_case"
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "FORMAL_CASE_FAMILIES"
            for target in targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (TypeError, ValueError) as exc:
            raise FreshCampaignError("evaluator family support registry must be a literal") from exc
        if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
            raise FreshCampaignError("evaluator family support registry must be a tuple of strings")
        registry = value
    if registry is None or not entrypoint_present:
        raise FreshCampaignError("evaluator lacks formal-case support registry or entrypoint")
    unsupported = sorted(set(requested) - set(registry))
    if unsupported:
        raise FreshCampaignError(
            f"evaluator does not support requested families: {','.join(unsupported)}"
        )
    if tuple(registry) != FORMAL_CASE_FAMILIES and evaluator_path == DEFAULT_EVALUATOR.resolve():
        raise FreshCampaignError(
            "default evaluator support registry drifted from imported contract"
        )
    return {
        "schema_version": "xinao.g4.evaluator_family_support_receipt.v1",
        "evaluator_sha256": _raw_sha256(evaluator_path),
        "requested_families": requested,
        "supported_families": list(registry),
        "entrypoint": "score_formal_case",
        "support_verified": True,
        "outcome_accessed": False,
    }


def _public_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "public_case_id": record["public_case_id"],
        "public_instructions": record["public_instructions"],
        "task_input": record["task_input"],
        "commitment_sha256": record["commitment_sha256"],
    }


def _verify_public_boundary(records: Sequence[Mapping[str, Any]]) -> None:
    problems: list[str] = []
    for record in records:
        payload = _public_payload(record)
        family = str(record["family_id"])
        forbidden = scan_forbidden_public_keys(payload)
        if forbidden:
            problems.append(f"forbidden_public_keys:{family}:{forbidden}")
        if family == "H03":
            hints = scan_h03_public_hints(payload)
            if hints:
                problems.append(f"h03_public_hints:{hints}")
        if family == "H04":
            hints = scan_h04_public_hints(payload)
            if hints:
                problems.append(f"h04_public_hints:{hints}")
    if problems:
        raise FreshCampaignError(f"subject public boundary failed: {problems}")


def _materialize_public_cases(
    records: Sequence[Mapping[str, Any]],
    path: Path,
) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: str(row["public_case_id"]))
    if not ordered:
        raise FreshCampaignError("subject public case set must not be empty")
    case_ids = [str(record["public_case_id"]) for record in ordered]
    if len(case_ids) != len(set(case_ids)):
        raise FreshCampaignError("subject public case IDs must be unique")
    _verify_public_boundary(ordered)
    rows: list[str] = []
    for record in ordered:
        payload = _public_payload(record)
        rows.append(
            json.dumps(
                {
                    "public_case_id": payload["public_case_id"],
                    "public_prompt": json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    "commitment_sha256": payload["commitment_sha256"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    return {
        "path": str(path),
        "sha256": _raw_sha256(path),
        "bytes": path.stat().st_size,
        "case_count": len(rows),
        "case_ids_sha256": canonical_sha256(case_ids),
        "family_labels_exposed": False,
        "outcome_accessed": False,
    }


def _runtime_root(path: Path) -> Path:
    target = path.resolve()
    runtime = Path(r"D:\XINAO_RESEARCH_RUNTIME").resolve()
    try:
        target.relative_to(runtime)
    except ValueError as exc:
        raise FreshCampaignError(
            "package_root must remain under D:\\XINAO_RESEARCH_RUNTIME"
        ) from exc
    if target.exists():
        raise FreshCampaignError(f"package_root already exists: {target}")
    return target


def _validated_designs(
    campaign: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    *,
    campaign_path: Path,
) -> dict[str, dict[str, Any]]:
    if campaign.get("schema_version") != CAMPAIGN_PREREGISTRATION_SCHEMA:
        raise FreshCampaignError("unexpected campaign preregistration schema")
    if acceptance.get("schema_version") != OWNER_ACCEPTANCE_SCHEMA:
        raise FreshCampaignError("unexpected owner acceptance schema")
    if acceptance.get("decision") != (
        "ACCEPT_SELECTION_AND_PREREGISTRATION_CONTENT__HOLD_CAPACITY"
    ):
        raise FreshCampaignError("owner did not accept the selected preregistration content")
    lifecycle = acceptance.get("lifecycle")
    if not isinstance(lifecycle, Mapping) or lifecycle.get("owner_adopted") is not True:
        raise FreshCampaignError("owner acceptance is not adopted")
    subject = acceptance.get("subject")
    if not isinstance(subject, Mapping):
        raise FreshCampaignError("owner acceptance subject is missing")
    if subject.get("preregistration_file_sha256") != _raw_sha256(campaign_path):
        raise FreshCampaignError("accepted preregistration file hash drifted")
    if subject.get("preregistration_content_hash") != campaign.get("content_hash"):
        raise FreshCampaignError("accepted preregistration content hash drifted")
    if campaign.get("frozen_for_owner_decision") is not True:
        raise FreshCampaignError("campaign content is not frozen for the owner decision")
    no_peek = campaign.get("no_peek_contract")
    if (
        not isinstance(no_peek, Mapping)
        or no_peek.get("sealed_before_real_evaluation") is not True
        or no_peek.get("attestation") != "NO_REAL_H01_H14_OUTCOME_BYTES_ACCESSED"
    ):
        raise FreshCampaignError("campaign no-peek contract is not closed")
    stopping = campaign.get("fixed_n_stopping")
    if (
        not isinstance(stopping, Mapping)
        or stopping.get("n_locked_before_results") is not True
        or stopping.get("optional_raise_n_after_peek") is not False
    ):
        raise FreshCampaignError("campaign stopping rule is not fixed before outcomes")
    seed_reducer = campaign.get("seed_reducer")
    if (
        not isinstance(seed_reducer, Mapping)
        or seed_reducer.get("unit_of_analysis") != "independent_heldout_case"
        or seed_reducer.get("seed_role") != "within_unit_replication_not_independent_n"
    ):
        raise FreshCampaignError("campaign statistical unit or seed role drifted")
    raw_designs = campaign.get("h01_h14_sample_design")
    if not isinstance(raw_designs, list):
        raise FreshCampaignError("campaign sample design is missing")
    designs: dict[str, dict[str, Any]] = {}
    for raw in raw_designs:
        if not isinstance(raw, Mapping):
            raise FreshCampaignError("campaign sample design row is invalid")
        row = dict(raw)
        family = row.get("family_id")
        n = row.get("n")
        p0 = row.get("p0")
        p1 = row.get("p1")
        attained_power = row.get("attained_power")
        if (
            family not in FAMILY_IDS
            or isinstance(n, bool)
            or not isinstance(n, int)
            or n < 1
            or not isinstance(p0, (int, float))
            or not isinstance(p1, (int, float))
            or not float(p0) < float(p1)
            or not isinstance(attained_power, (int, float))
            or float(attained_power) < 0.8
        ):
            raise FreshCampaignError(f"invalid sample design for {family!r}")
        if family in designs:
            raise FreshCampaignError(f"duplicate sample design for {family}")
        designs[str(family)] = row
    if set(designs) != set(FAMILY_IDS):
        raise FreshCampaignError("sample design must cover H01-H14 exactly")
    return designs


def _stable_cell_id(cell: Mapping[str, Any]) -> str:
    return canonical_sha256(cell)


def _all_campaign_cells(
    *,
    records_by_family: Mapping[str, Sequence[Mapping[str, Any]]],
    seed_ids: Sequence[int],
) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for family in FAMILY_IDS:
        for record in records_by_family[family]:
            for configuration in SUBJECT_CONFIGURATIONS:
                for seed_id in seed_ids:
                    cells.append(
                        {
                            "family_id": family,
                            "public_case_id": record["public_case_id"],
                            "subject_configuration": configuration,
                            "seed_id": seed_id,
                        }
                    )
    return cells


def _register_campaign_cells(
    *,
    campaign_id: str,
    cells: Sequence[Mapping[str, Any]],
) -> tuple[GlobalTrialLedger, dict[str, Any]]:
    ledger = GlobalTrialLedger()
    for cell in cells:
        cell_id = _stable_cell_id(cell)
        ledger.register(
            f"g4:{campaign_id}:{cell_id}",
            {
                "status": "REGISTERED",
                "family_id": cell["family_id"],
                "path_kind": "PRIMARY",
                "cell_id": cell_id,
                "public_case_id": cell["public_case_id"],
                "subject_configuration": cell["subject_configuration"],
                "seed_id": cell["seed_id"],
            },
        )
    export = ledger.export_disclosure()
    if export["total_trials"] != len(cells):
        raise FreshCampaignError("GlobalTrialLedger did not register every campaign cell")
    return ledger, export


def _records_by_family(
    records: Sequence[Any],
    designs: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    available: dict[str, list[dict[str, Any]]] = {family: [] for family in FAMILY_IDS}
    for record in records:
        available[record.family_id].append(record.as_private_dict())
    selected: dict[str, list[dict[str, Any]]] = {}
    for family in FAMILY_IDS:
        required = int(designs[family]["n"])
        rows = available[family][:required]
        if len(rows) != required:
            raise FreshCampaignError(
                f"fresh heldout suite has {len(rows)} {family} cases; {required} required"
            )
        selected[family] = rows
    return selected


def _first_batch_cells(
    *,
    records_by_family: Mapping[str, Sequence[Mapping[str, Any]]],
    families: Sequence[str],
    configurations: Sequence[str],
    seed_ids: Sequence[int],
    cases_per_family: int,
) -> list[dict[str, Any]]:
    if cases_per_family < 1:
        raise FreshCampaignError("first batch cases_per_family must be >= 1")
    cells: list[dict[str, Any]] = []
    for family in families:
        if family not in FAMILY_IDS:
            raise FreshCampaignError(f"unknown first-batch family {family}")
        rows = list(records_by_family[family][:cases_per_family])
        if len(rows) != cases_per_family:
            raise FreshCampaignError(f"not enough fresh {family} cases for the first batch")
        for record in rows:
            for configuration in configurations:
                if configuration not in SUBJECT_CONFIGURATIONS:
                    raise FreshCampaignError(f"unknown first-batch configuration {configuration}")
                for seed_id in seed_ids:
                    cells.append(
                        {
                            "family_id": family,
                            "public_case_id": record["public_case_id"],
                            "subject_configuration": configuration,
                            "seed_id": seed_id,
                        }
                    )
    return cells


def _timestamp() -> str:
    now = datetime.now(UTC)
    return format_utc(now.replace(microsecond=(now.microsecond // 1000) * 1000))


def initialize(args: argparse.Namespace) -> dict[str, Any]:
    package_root = _runtime_root(args.package_root)
    campaign_path = args.campaign_preregistration.resolve()
    acceptance_path = args.owner_acceptance.resolve()
    campaign_contract_path = args.campaign_contract.resolve()
    adapter_path = args.subject_adapter.resolve()
    evaluator_path = args.evaluator.resolve()
    for required_path in (
        campaign_path,
        acceptance_path,
        campaign_contract_path,
        adapter_path,
        evaluator_path,
    ):
        if not required_path.is_file():
            raise FreshCampaignError(f"required binding file is missing: {required_path}")
    evaluator_support = _validate_evaluator_family_support(evaluator_path, args.family)
    campaign = _read_json(campaign_path)
    acceptance = _read_json(acceptance_path)
    designs = _validated_designs(
        campaign,
        acceptance,
        campaign_path=campaign_path,
    )
    seed_reducer = campaign["seed_reducer"]
    seed_ids = list(seed_reducer["required_seeds_min"])
    if (
        not seed_ids
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seed_ids)
        or len(seed_ids) != len(set(seed_ids))
    ):
        raise FreshCampaignError("required campaign seed IDs are invalid")

    profile = GeneratorProfile(
        cases_per_family=max(int(row["n"]) for row in designs.values()),
        suite_version=args.suite_version,
    )
    generated = generate_full_family_suites(
        training_secret=secrets.token_bytes(32),
        heldout_secret=secrets.token_bytes(32),
        profile=profile,
    )
    records_by_family = _records_by_family(
        generated.heldout_private_bundle.records,
        designs,
    )
    campaign_id = args.campaign_id
    all_cells = _all_campaign_cells(
        records_by_family=records_by_family,
        seed_ids=seed_ids,
    )
    _ledger, ledger_export = _register_campaign_cells(
        campaign_id=campaign_id,
        cells=all_cells,
    )
    first_cells = _first_batch_cells(
        records_by_family=records_by_family,
        families=args.family,
        configurations=args.configuration,
        seed_ids=seed_ids,
        cases_per_family=args.cases_per_family,
    )
    registered_cell_ids = {work_key.rsplit(":", 1)[-1] for work_key in ledger_export["work_keys"]}
    if any(_stable_cell_id(cell) not in registered_cell_ids for cell in first_cells):
        raise FreshCampaignError("first batch is not a subset of the preregistered campaign")

    package_root.mkdir(parents=True, exist_ok=False)
    campaign_source_path = package_root / "campaign_preregistration_source.v1.json"
    acceptance_source_path = package_root / "owner_acceptance_source.v1.json"
    _copy_exact_source(campaign_path, campaign_source_path)
    _copy_exact_source(acceptance_path, acceptance_source_path)
    adapter_snapshot_path = (
        package_root / "subject" / "adapter" / "promptfoo_c0_bootstrap_adapter.py"
    )
    _copy_exact_source(adapter_path, adapter_snapshot_path)
    write_json(
        package_root / "suite" / "summary.v1.json",
        generated.as_summary_dict(),
    )
    write_json(
        package_root / "suite" / "training_public_manifest.v1.json",
        generated.training_public_manifest.as_public_dict(),
    )
    write_json(
        package_root / "suite" / "heldout_public_manifest.v1.json",
        generated.heldout_public_manifest.as_public_dict(),
    )
    write_json(
        package_root / "owner" / "planned_case_index.v1.json",
        {
            "schema_version": "xinao.g4.planned_case_index.v1",
            "campaign_id": campaign_id,
            "case_ids_by_family": {
                family: [record["public_case_id"] for record in records_by_family[family]]
                for family in FAMILY_IDS
            },
            "outcome_accessed": False,
            "authority": False,
            "g4_closed": False,
        },
    )
    ledger_path = package_root / "ledger" / "global_trial_ledger_export.v1.json"
    write_json(ledger_path, ledger_export)

    selected_records = [record for family in FAMILY_IDS for record in records_by_family[family]]
    selected_case_ids = [record["public_case_id"] for record in selected_records]
    subject_public_cases = _materialize_public_cases(
        selected_records,
        package_root / "subject" / "public_cases.v1.jsonl",
    )
    vault = RealHiddenBootstrapVault(package_root / "vault")
    deposit = vault.deposit_private_bundle(
        private_bundle=generated.heldout_private_bundle.as_private_dict(),
        suite_identity=generated.heldout_identity.as_dict(),
        generator_artifact=generated.generator_artifact.as_dict(),
        selected_case_ids=selected_case_ids,
    )
    if deposit.get("ok") is not True:
        raise FreshCampaignError(f"vault deposit failed: {deposit}")
    lockdown = vault.lock_down_host_reads(expected_receipt=False)
    if lockdown.get("ok") is not True:
        raise FreshCampaignError(f"vault lockdown failed: {lockdown}")
    lockdown_receipt = {
        "schema_version": "xinao.g4.campaign_vault_lockdown_receipt.v1",
        "campaign_id": campaign_id,
        "suite_identity_sha256": generated.heldout_identity.identity_sha256,
        "generator_artifact_sha256": generated.generator_artifact.artifact_sha256,
        "selected_case_ids_sha256": canonical_sha256(selected_case_ids),
        "selected_case_count": len(selected_case_ids),
        "target_set_exact": lockdown.get("target_set_exact") is True,
        "isolation_enforced": lockdown.get("isolation_enforced") is True,
        "content_recorded": False,
        "outcome_accessed": False,
        "authority": False,
        "g4_closed": False,
    }
    published_lockdown = vault.publish_lockdown_receipt(lockdown_receipt)
    if published_lockdown.get("ok") is not True:
        raise FreshCampaignError(f"vault receipt seal failed: {published_lockdown}")

    split = build_split_manifest(
        split_manifest_id=f"{campaign_id}:fresh-split:{args.suite_version}",
        suite_version=args.suite_version,
        boundaries={
            "training": {
                "case_count": generated.training_public_manifest.case_count,
                "suite_commitment_sha256": generated.training_identity.identity_sha256,
            },
            "heldout": {
                "case_count": generated.heldout_public_manifest.case_count,
                "suite_commitment_sha256": generated.heldout_identity.identity_sha256,
            },
        },
        purge_cases=0,
        embargo_cases=0,
        holdout_exposure_budget=len(all_cells),
    )
    power_plans = {
        family: build_power_plan(
            plan_id=f"{campaign_id}:{family}:accepted-v7",
            family_id=family,
            mde=float(designs[family]["p1"]) - float(designs[family]["p0"]),
            target_power=0.8,
            max_budget_trials=int(designs[family]["n"]),
            holdout_split_binding=split["content_hash"],
            serial_dependence_declared=True,
            status="ADEQUATE",
        )
        for family in args.family
    }
    analysis_policy = {
        "primary_endpoint_policy_sha256": canonical_sha256(
            {
                "analysis_graph_pin": campaign["analysis_graph_pin"],
                "unit_of_analysis": seed_reducer["unit_of_analysis"],
            }
        ),
        "threshold_policy_sha256": canonical_sha256(campaign["thresholds"]),
        "contingency_policy_sha256": canonical_sha256(
            campaign["missing_unknown_underpowered_no_action_rules"]
        ),
        "deviation_policy_sha256": canonical_sha256(
            {
                "no_peek_contract": campaign["no_peek_contract"],
                "retry_ceiling": campaign["retry_ceiling"],
            }
        ),
        "power_analysis_policy_sha256_by_family": {
            family: canonical_sha256(designs[family]) for family in args.family
        },
    }
    request = {
        "schema_version": REQUEST_SCHEMA,
        "campaign_id": campaign_id,
        "batch_id": args.batch_id,
        "batch_sequence": args.batch_sequence,
        "work_key": args.work_key,
        "campaign_preregistration_ref": str(campaign_source_path),
        "campaign_preregistration_sha256": _raw_sha256(campaign_source_path),
        "families": list(args.family),
        "subject_configurations": list(args.configuration),
        "batch_cells": first_cells,
        "split_manifest": split,
        "power_plans": power_plans,
        "frozen_bindings": {
            "suite_sha256": generated.heldout_identity.identity_sha256,
            "generator_sha256": generated.generator_artifact.artifact_sha256,
            "evaluator_sha256": _raw_sha256(evaluator_path),
            "scoring_policy_sha256": canonical_sha256(
                {
                    "multiplicity_procedure": campaign["multiplicity_procedure"],
                    "thresholds": campaign["thresholds"],
                }
            ),
            "subject_adapter_sha256": _raw_sha256(adapter_snapshot_path),
            "subject_public_cases_sha256": subject_public_cases["sha256"],
        },
        "unit_policy": {
            "unit_of_analysis": "INDEPENDENT_HELDOUT_CASE",
            "seed_role": "WITHIN_CASE_REPLICATION_NOT_INDEPENDENT_N",
            "fixed_seed_ids": seed_ids,
            "model_identity_policy": "PIN_EXACT_OBSERVED_IDENTITY",
        },
        "budget_policy": {
            "max_batch_executions": len(first_cells),
            "max_outcome_accesses": len(first_cells),
        },
        "stopping_policy": {
            "kind": "FIXED_BUDGET_NO_EARLY_SUCCESS",
            "allow_early_success_stop": False,
            "underpowered_terminal": "UNDERPOWERED",
        },
        "analysis_policy": analysis_policy,
        "campaign_contract_sha256": _raw_sha256(campaign_contract_path),
        "retry_policy_sha256": canonical_sha256(campaign["retry_ceiling"]),
        "global_trial_ledger_ref": str(ledger_path),
        "global_trial_ledger_snapshot_sha256": _raw_sha256(ledger_path),
        "declared_prior_outcome_receipts": [],
        "reused_outcome_evidence_ids": [],
    }
    prepared_at = _timestamp()
    prepared = prepare_g4_preregistration(
        request,
        prepared_at_utc=prepared_at,
        forbidden_suite_commitments=args.forbidden_suite_commitment,
    )
    if prepared["terminal"] != TERMINAL_READY:
        raise FreshCampaignError(
            f"fresh first batch was not admitted: {prepared['receipt']['problems']}"
        )
    from prepare_g4_batch_preregistration import publish_preparation_package

    preregistration_root = package_root / "first_batch_preregistration"
    published = publish_preparation_package(
        package_root=preregistration_root,
        result=prepared,
    )
    receipt: dict[str, Any] = {
        "schema_version": INITIALIZATION_SCHEMA,
        "created_at_utc": prepared_at,
        "campaign_id": campaign_id,
        "batch_id": args.batch_id,
        "package_root": str(package_root),
        "source_campaign_preregistration_sha256": _raw_sha256(campaign_path),
        "source_owner_acceptance_sha256": _raw_sha256(acceptance_path),
        "generator_artifact_sha256": generated.generator_artifact.artifact_sha256,
        "training_identity_sha256": generated.training_identity.identity_sha256,
        "heldout_identity_sha256": generated.heldout_identity.identity_sha256,
        "global_registered_execution_cells": len(all_cells),
        "planned_independent_cases": len(selected_case_ids),
        "subject_public_cases": subject_public_cases,
        "subject_adapter_snapshot_sha256": _raw_sha256(adapter_snapshot_path),
        "evaluator_family_support": evaluator_support,
        "first_batch_execution_cells": len(first_cells),
        "first_batch_manifest_sha256": prepared["batch_manifest"]["content_hash"],
        "published_first_batch_files": published,
        "vault_lockdown_verified": True,
        "outcome_accessed": False,
        "subject_execution_performed": False,
        "evaluator_invoked": False,
        "authority": False,
        "g4_full": False,
        "g4_closed": False,
        "g5_closed": False,
        "parent_complete": False,
    }
    receipt["content_hash"] = canonical_sha256(receipt)
    write_json(package_root / "initialization_receipt.v1.json", receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-preregistration", type=Path, required=True)
    parser.add_argument("--owner-acceptance", type=Path, required=True)
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--batch-sequence", type=int, default=1)
    parser.add_argument("--work-key", required=True)
    parser.add_argument("--suite-version", default="2")
    parser.add_argument("--family", action="append", required=True)
    parser.add_argument("--configuration", action="append", required=True)
    parser.add_argument("--cases-per-family", type=int, default=1)
    parser.add_argument("--subject-adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--evaluator", type=Path, default=DEFAULT_EVALUATOR)
    parser.add_argument("--forbidden-suite-commitment", action="append", default=[])
    return parser


def main() -> int:
    receipt = initialize(_parser().parse_args())
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
