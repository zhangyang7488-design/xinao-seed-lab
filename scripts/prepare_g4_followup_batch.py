"""Freeze one later G4 batch inside an existing unopened campaign suite.

The fresh-campaign initializer owns suite creation and the first batch.  This
entrypoint reuses that exact suite, public subject boundary, scientific design,
and global campaign ledger while binding one later batch to exactly one subject
configuration and one byte-exact adapter snapshot.  It never reads the vault,
executes a subject, invokes an evaluator, or opens an outcome.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
for source_root in (str(XINAO_SRC), str(SCRIPTS_ROOT)):
    if source_root not in sys.path:
        sys.path.insert(0, source_root)

from xinao.canonical import canonical_sha256, format_utc  # noqa: E402
from xinao.capability.g4_preregistration import (  # noqa: E402
    REQUEST_SCHEMA,
    SUBJECT_CONFIGURATIONS,
    TERMINAL_READY,
    prepare_g4_preregistration,
    validate_g4_preregistration_package,
)
from xinao.single_home.power_plan import build_power_plan  # noqa: E402

from prepare_g4_batch_preregistration import publish_preparation_package  # noqa: E402

INITIALIZATION_SCHEMA = "xinao.g4.fresh_campaign_initialization.v1"
FOLLOWUP_FREEZE_SCHEMA = "xinao.g4.followup_batch_freeze.v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class FollowupBatchError(ValueError):
    """The existing campaign cannot safely freeze the requested later batch."""


def _raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FollowupBatchError(f"JSON binding is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise FollowupBatchError(f"JSON binding must be one object: {path}")
    return value


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _verify_content_hash(payload: Mapping[str, Any], *, label: str) -> None:
    expected = payload.get("content_hash")
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    if not isinstance(expected, str) or canonical_sha256(body) != expected:
        raise FollowupBatchError(f"{label} content hash drifted")


def _runtime_root() -> Path:
    return Path(
        os.environ.get("XINAO_RESEARCH_RUNTIME_ROOT", r"D:\XINAO_RESEARCH_RUNTIME")
    ).resolve()


def _campaign_root(path: Path) -> Path:
    target = path.resolve()
    try:
        target.relative_to(_runtime_root())
    except ValueError as exc:
        raise FollowupBatchError(
            "campaign package root must remain under the research runtime"
        ) from exc
    if not target.is_dir():
        raise FollowupBatchError(f"campaign package root is missing: {target}")
    return target


def _contains_outcome_access(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("outcome_accessed") is True:
            return True
        if value.get("all_outcomes_unopened") is False:
            return True
        return any(_contains_outcome_access(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_outcome_access(child) for child in value)
    return False


def _safe_public_json_paths(root: Path) -> list[Path]:
    paths = [
        root / "initialization_receipt.v1.json",
        root / "owner" / "planned_case_index.v1.json",
    ]
    paths.extend(sorted((root / "first_batch_preregistration").glob("*.json")))
    later = root / "subsequent_batches"
    if later.is_dir():
        paths.extend(sorted(later.glob("*/*.json")))
    return [path for path in paths if path.is_file()]


def _load_preregistration_package(root: Path) -> dict[str, Any]:
    request = _read_json(root / "request.v1.json")
    preregistration = _read_json(root / "preregistration.v1.json")
    obligation_ledger = _read_json(root / "obligation_ledger.v1.json")
    batch_manifest = _read_json(root / "batch_manifest.v1.json")
    validate_g4_preregistration_package(
        request=request,
        preregistration=preregistration,
        obligation_ledger=obligation_ledger,
        batch_manifest=batch_manifest,
    )
    return {
        "root": root,
        "request": request,
        "preregistration": preregistration,
        "obligation_ledger": obligation_ledger,
        "batch_manifest": batch_manifest,
    }


def _existing_packages(campaign_root: Path) -> list[dict[str, Any]]:
    packages = [_load_preregistration_package(campaign_root / "first_batch_preregistration")]
    later = campaign_root / "subsequent_batches"
    if later.is_dir():
        for root in sorted(path for path in later.iterdir() if path.is_dir()):
            packages.append(_load_preregistration_package(root))
    return packages


def _designs(campaign: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = campaign.get("h01_h14_sample_design")
    if not isinstance(rows, list):
        raise FollowupBatchError("campaign sample design is missing")
    designs: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise FollowupBatchError("campaign sample design row is invalid")
        row = dict(raw)
        family = row.get("family_id")
        if (
            not isinstance(family, str)
            or not family
            or family in designs
            or isinstance(row.get("n"), bool)
            or not isinstance(row.get("n"), int)
            or int(row["n"]) < 1
            or not isinstance(row.get("p0"), (int, float))
            or not isinstance(row.get("p1"), (int, float))
            or not float(row["p0"]) < float(row["p1"])
        ):
            raise FollowupBatchError(f"campaign sample design is invalid for {family!r}")
        designs[family] = row
    return designs


def _public_case_ids(path: Path) -> set[str]:
    case_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        row = json.loads(line)
        case_id = row.get("public_case_id") if isinstance(row, Mapping) else None
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise FollowupBatchError(
                f"subject public case row {line_number} has an invalid identity"
            )
        case_ids.add(case_id)
    if not case_ids:
        raise FollowupBatchError("subject public case boundary is empty")
    return case_ids


def _select_cells(
    *,
    case_index: Mapping[str, Any],
    families: Sequence[str],
    configuration: str,
    seed_ids: Sequence[int],
    case_offset: int,
    cases_per_family: int,
) -> list[dict[str, Any]]:
    if not families or len(families) != len(set(families)):
        raise FollowupBatchError("families must be non-empty and unique")
    if configuration not in SUBJECT_CONFIGURATIONS:
        raise FollowupBatchError(f"unknown subject configuration: {configuration}")
    if case_offset < 0 or cases_per_family < 1:
        raise FollowupBatchError("case offset/count is invalid")
    by_family = case_index.get("case_ids_by_family")
    if not isinstance(by_family, Mapping):
        raise FollowupBatchError("planned case index is missing family bindings")
    cells: list[dict[str, Any]] = []
    for family in families:
        available = by_family.get(family)
        if not isinstance(available, list) or not all(
            isinstance(case_id, str) and case_id for case_id in available
        ):
            raise FollowupBatchError(f"planned cases are missing for {family}")
        selected = available[case_offset : case_offset + cases_per_family]
        if len(selected) != cases_per_family:
            raise FollowupBatchError(f"not enough planned {family} cases for this batch")
        for case_id in selected:
            for seed_id in seed_ids:
                cells.append(
                    {
                        "family_id": family,
                        "public_case_id": case_id,
                        "subject_configuration": configuration,
                        "seed_id": seed_id,
                    }
                )
    return cells


def freeze_followup_batch(
    *,
    campaign_package_root: Path,
    batch_id: str,
    batch_sequence: int,
    work_key: str,
    families: Sequence[str],
    configuration: str,
    case_offset: int,
    cases_per_family: int,
    subject_adapter: Path,
    known_prior_outcome_receipts: Sequence[str] = (),
    forbidden_suite_commitments: Sequence[str] = (),
) -> dict[str, Any]:
    root = _campaign_root(campaign_package_root)
    if not _SAFE_ID.fullmatch(batch_id):
        raise FollowupBatchError("batch_id is not safe for an append-only package path")
    if not work_key:
        raise FollowupBatchError("work_key is required")
    if known_prior_outcome_receipts:
        raise FollowupBatchError("known prior outcome access forbids a follow-up batch")
    adapter_path = subject_adapter.resolve()
    if not adapter_path.is_file():
        raise FollowupBatchError(f"subject adapter is missing: {adapter_path}")

    initialization_path = root / "initialization_receipt.v1.json"
    initialization = _read_json(initialization_path)
    if initialization.get("schema_version") != INITIALIZATION_SCHEMA:
        raise FollowupBatchError("unexpected campaign initialization schema")
    _verify_content_hash(initialization, label="campaign initialization")
    if Path(str(initialization.get("package_root") or "")).resolve() != root:
        raise FollowupBatchError("campaign initialization root binding drifted")
    if (
        initialization.get("vault_lockdown_verified") is not True
        or initialization.get("outcome_accessed") is not False
        or initialization.get("evaluator_invoked") is not False
    ):
        raise FollowupBatchError("campaign is not in a locked pre-outcome state")
    for path in _safe_public_json_paths(root):
        if _contains_outcome_access(_read_json(path)):
            raise FollowupBatchError(f"outcome access is already recorded: {path}")

    campaign_source = root / "campaign_preregistration_source.v1.json"
    acceptance_source = root / "owner_acceptance_source.v1.json"
    planned_index_path = root / "owner" / "planned_case_index.v1.json"
    public_cases_path = root / "subject" / "public_cases.v1.jsonl"
    global_ledger_path = root / "ledger" / "global_trial_ledger_export.v1.json"
    required_hashes = (
        (
            campaign_source,
            initialization.get("source_campaign_preregistration_sha256"),
            "campaign source",
        ),
        (
            acceptance_source,
            initialization.get("source_owner_acceptance_sha256"),
            "owner acceptance",
        ),
        (
            public_cases_path,
            (initialization.get("subject_public_cases") or {}).get("sha256"),
            "subject public cases",
        ),
    )
    for path, expected, label in required_hashes:
        if not path.is_file() or _raw_sha256(path) != expected:
            raise FollowupBatchError(f"{label} hash drifted")

    existing = _existing_packages(root)
    first = existing[0]["request"]
    if first.get("campaign_id") != initialization.get("campaign_id"):
        raise FollowupBatchError("campaign identity drifted from the first batch")
    if first["frozen_bindings"]["suite_sha256"] != initialization.get("heldout_identity_sha256"):
        raise FollowupBatchError("heldout suite binding drifted")
    if _raw_sha256(global_ledger_path) != first.get("global_trial_ledger_snapshot_sha256"):
        raise FollowupBatchError("global trial ledger snapshot drifted")
    if Path(str(first.get("global_trial_ledger_ref") or "")).resolve() != global_ledger_path:
        raise FollowupBatchError("global trial ledger path binding drifted")
    if first["frozen_bindings"]["subject_public_cases_sha256"] != _raw_sha256(public_cases_path):
        raise FollowupBatchError("first batch public boundary binding drifted")

    existing_ids = {str(package["request"]["batch_id"]) for package in existing}
    existing_work_keys = {str(package["request"]["work_key"]) for package in existing}
    sequences = [int(package["request"]["batch_sequence"]) for package in existing]
    if batch_id in existing_ids or work_key in existing_work_keys:
        raise FollowupBatchError("batch identity or work_key is already frozen")
    if batch_sequence != max(sequences) + 1:
        raise FollowupBatchError("batch_sequence must append exactly after the latest batch")
    used_cell_ids = {
        canonical_sha256(cell) for package in existing for cell in package["request"]["batch_cells"]
    }

    evaluator_support = initialization.get("evaluator_family_support")
    supported_families = (
        evaluator_support.get("supported_families")
        if isinstance(evaluator_support, Mapping)
        else None
    )
    if not isinstance(supported_families, list) or any(
        family not in supported_families for family in families
    ):
        raise FollowupBatchError("the frozen evaluator does not support every requested family")

    case_index = _read_json(planned_index_path)
    if (
        case_index.get("campaign_id") != initialization.get("campaign_id")
        or case_index.get("outcome_accessed") is not False
    ):
        raise FollowupBatchError("planned case index is not bound to an unopened campaign")
    seed_ids = first["unit_policy"]["fixed_seed_ids"]
    cells = _select_cells(
        case_index=case_index,
        families=families,
        configuration=configuration,
        seed_ids=seed_ids,
        case_offset=case_offset,
        cases_per_family=cases_per_family,
    )
    overlap = sorted(
        canonical_sha256(cell) for cell in cells if canonical_sha256(cell) in used_cell_ids
    )
    if overlap:
        raise FollowupBatchError(f"batch cells overlap an existing batch: {overlap}")

    public_ids = _public_case_ids(public_cases_path)
    if any(str(cell["public_case_id"]) not in public_ids for cell in cells):
        raise FollowupBatchError("selected batch cell is missing from the public subject boundary")
    global_ledger = _read_json(global_ledger_path)
    registered_ids = {
        str(work_key_value).rsplit(":", 1)[-1]
        for work_key_value in global_ledger.get("work_keys") or []
    }
    missing = sorted(
        canonical_sha256(cell) for cell in cells if canonical_sha256(cell) not in registered_ids
    )
    if missing:
        raise FollowupBatchError(f"batch cells are absent from the global ledger: {missing}")

    campaign = _read_json(campaign_source)
    designs = _designs(campaign)
    if any(family not in designs for family in families):
        raise FollowupBatchError("campaign design does not cover every requested family")
    split = deepcopy(first["split_manifest"])
    power_plans = {
        family: build_power_plan(
            plan_id=f"{first['campaign_id']}:{family}:accepted-v7",
            family_id=family,
            mde=float(designs[family]["p1"]) - float(designs[family]["p0"]),
            target_power=0.8,
            max_budget_trials=int(designs[family]["n"]),
            holdout_split_binding=split["content_hash"],
            serial_dependence_declared=True,
            status="ADEQUATE",
        )
        for family in families
    }
    analysis_policy = deepcopy(first["analysis_policy"])
    analysis_policy["power_analysis_policy_sha256_by_family"] = {
        family: canonical_sha256(designs[family]) for family in families
    }
    adapter_bytes = adapter_path.read_bytes()
    adapter_sha256 = hashlib.sha256(adapter_bytes).hexdigest()
    request = {
        "schema_version": REQUEST_SCHEMA,
        "campaign_id": first["campaign_id"],
        "batch_id": batch_id,
        "batch_sequence": batch_sequence,
        "work_key": work_key,
        "campaign_preregistration_ref": str(campaign_source),
        "campaign_preregistration_sha256": _raw_sha256(campaign_source),
        "families": list(families),
        "subject_configurations": [configuration],
        "batch_cells": cells,
        "split_manifest": split,
        "power_plans": power_plans,
        "frozen_bindings": {
            **deepcopy(first["frozen_bindings"]),
            "subject_adapter_sha256": adapter_sha256,
        },
        "unit_policy": deepcopy(first["unit_policy"]),
        "budget_policy": {
            "max_batch_executions": len(cells),
            "max_outcome_accesses": len(cells),
        },
        "stopping_policy": deepcopy(first["stopping_policy"]),
        "analysis_policy": analysis_policy,
        "campaign_contract_sha256": first["campaign_contract_sha256"],
        "retry_policy_sha256": first["retry_policy_sha256"],
        "global_trial_ledger_ref": str(global_ledger_path),
        "global_trial_ledger_snapshot_sha256": _raw_sha256(global_ledger_path),
        "declared_prior_outcome_receipts": [],
        "reused_outcome_evidence_ids": [],
    }
    now = datetime.now(UTC)
    frozen_at = format_utc(now.replace(microsecond=(now.microsecond // 1000) * 1000))
    prepared = prepare_g4_preregistration(
        request,
        prepared_at_utc=frozen_at,
        known_prior_outcome_receipts=known_prior_outcome_receipts,
        forbidden_suite_commitments=forbidden_suite_commitments,
    )
    if prepared["terminal"] != TERMINAL_READY:
        raise FollowupBatchError(
            f"follow-up batch was not admitted: {prepared['receipt']['problems']}"
        )

    relative_adapter = f"subject/adapter/{adapter_path.name}"
    freeze_receipt: dict[str, Any] = {
        "schema_version": FOLLOWUP_FREEZE_SCHEMA,
        "frozen_at_utc": frozen_at,
        "campaign_id": first["campaign_id"],
        "campaign_package_root": str(root),
        "campaign_initialization_receipt_sha256": _raw_sha256(initialization_path),
        "batch_id": batch_id,
        "batch_sequence": batch_sequence,
        "work_key": work_key,
        "families": list(families),
        "subject_configuration": configuration,
        "subject_adapter_snapshot": relative_adapter,
        "subject_adapter_sha256": adapter_sha256,
        "batch_cells_sha256": canonical_sha256(prepared["request"]["batch_cells"]),
        "planned_execution_cells": len(cells),
        "global_trial_ledger_snapshot_sha256": _raw_sha256(global_ledger_path),
        "suite_sha256": first["frozen_bindings"]["suite_sha256"],
        "registered_before_outcome_access": True,
        "outcome_accessed": False,
        "subject_execution_performed": False,
        "evaluator_invoked": False,
        "authority": False,
        "g4_full": False,
        "g4_closed": False,
        "parent_complete": False,
    }
    freeze_receipt["content_hash"] = canonical_sha256(freeze_receipt)
    package_root = root / "subsequent_batches" / batch_id
    published = publish_preparation_package(
        package_root=package_root,
        result=prepared,
        extra_files={
            relative_adapter: adapter_bytes,
            "followup_freeze_receipt.v1.json": _json_bytes(freeze_receipt),
        },
    )
    return {
        "terminal": prepared["terminal"],
        "campaign_id": first["campaign_id"],
        "batch_id": batch_id,
        "batch_sequence": batch_sequence,
        "package_root": str(package_root),
        "subject_configuration": configuration,
        "subject_adapter_sha256": adapter_sha256,
        "planned_execution_cells": len(cells),
        "published": published,
        "outcome_accessed": False,
        "subject_execution_performed": False,
        "evaluator_invoked": False,
        "authority": False,
        "g4_full": False,
        "g4_closed": False,
        "parent_complete": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-package-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--batch-sequence", type=int, required=True)
    parser.add_argument("--work-key", required=True)
    parser.add_argument("--family", action="append", required=True)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--case-offset", type=int, default=0)
    parser.add_argument("--cases-per-family", type=int, required=True)
    parser.add_argument("--subject-adapter", type=Path, required=True)
    parser.add_argument("--known-prior-outcome-receipt", action="append", default=[])
    parser.add_argument("--forbidden-suite-commitment", action="append", default=[])
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary = freeze_followup_batch(
        campaign_package_root=args.campaign_package_root,
        batch_id=args.batch_id,
        batch_sequence=args.batch_sequence,
        work_key=args.work_key,
        families=args.family,
        configuration=args.configuration,
        case_offset=args.case_offset,
        cases_per_family=args.cases_per_family,
        subject_adapter=args.subject_adapter,
        known_prior_outcome_receipts=args.known_prior_outcome_receipt,
        forbidden_suite_commitments=args.forbidden_suite_commitment,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
