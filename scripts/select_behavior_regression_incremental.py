#!/usr/bin/env python3
"""Select fresh behavior cases and bind reusable terminal PASS rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "xinao.behavior_regression_incremental_selection.v1"
NON_RUNTIME_ROLES = {
    "catalog",
    "repository_safety_tests",
    "snapshot_builder_tests",
    "incremental_selector_tests",
    "static_assertion_tests",
}
NON_RUNTIME_PATHS = {
    "evals/context_intent_alignment/cases.yaml",
    "evals/context_intent_alignment/suite.json",
}


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _shared_runtime_identity(manifest: dict[str, Any]) -> str:
    rows = []
    for row in manifest.get("files", []):
        path = str(row["path"]).replace("\\", "/")
        role = str(row.get("role", ""))
        if role in NON_RUNTIME_ROLES or path in NON_RUNTIME_PATHS:
            continue
        rows.append(
            {
                "path": path,
                "role": role,
                "size_bytes": int(row["size_bytes"]),
                "sha256": str(row["sha256"]).lower(),
            }
        )
    return _sha256(sorted(rows, key=lambda row: row["path"]))


def _case_signature(case: dict[str, Any]) -> str:
    return _sha256(
        {
            "description": case.get("description"),
            "metadata": case.get("metadata", {}),
            "vars": case.get("vars", {}),
        }
    )


def _row_signature(row: dict[str, Any]) -> str:
    test_case = row.get("testCase") or {}
    variables = dict(test_case.get("vars") or row.get("vars") or {})
    variables.pop("sessionId", None)
    return _sha256(
        {
            "description": test_case.get("description"),
            "metadata": test_case.get("metadata") or row.get("metadata") or {},
            "vars": variables,
        }
    )


def _case_id(case: dict[str, Any]) -> str:
    return str(case.get("vars", {}).get("case_id") or case.get("metadata", {}).get("id"))


def _selected_cases(
    cases_path: Path,
    *,
    profile: str,
    domain: str,
    case_pattern: str,
) -> list[dict[str, Any]]:
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list):
        raise ValueError("context cases must be a YAML list")
    pattern = re.compile(case_pattern) if case_pattern else None
    selected = []
    for case in cases:
        metadata = case.get("metadata", {})
        if profile in {"smoke", "core", "deep"} and profile not in metadata.get("profiles", []):
            continue
        if domain and metadata.get("domain") != domain:
            continue
        if pattern and not pattern.search(str(case.get("description", ""))):
            continue
        selected.append(case)
    if not selected:
        raise ValueError("incremental selection matched no current cases")
    identifiers = [_case_id(case) for case in selected]
    if len(identifiers) != len(set(identifiers)) or any(not item for item in identifiers):
        raise ValueError("selected current case identities must be non-empty and unique")
    return selected


def select_incremental(
    cases_path: Path,
    current_manifest_path: Path,
    reuse_results: list[Path],
    output_path: Path,
    *,
    profile: str,
    domain: str = "",
    case_pattern: str = "",
) -> Path:
    current_manifest = _load_json(current_manifest_path)
    current_shared = _shared_runtime_identity(current_manifest)
    selected = _selected_cases(
        cases_path,
        profile=profile,
        domain=domain,
        case_pattern=case_pattern,
    )
    selected_by_id = {_case_id(case): case for case in selected}
    reusable: dict[str, dict[str, Any]] = {}
    run_checks: list[dict[str, Any]] = []

    for result_path in reuse_results:
        result_path = result_path.resolve()
        summary_path = result_path.parent / "summary.json"
        if not summary_path.is_file():
            run_checks.append(
                {"result": str(result_path), "compatible": False, "reason": "missing_summary"}
            )
            continue
        summary = _load_json(summary_path)
        if summary.get("source_manifest_unchanged") is not True or summary.get(
            "infrastructure_error"
        ):
            run_checks.append(
                {
                    "result": str(result_path),
                    "compatible": False,
                    "reason": "unstable_or_infrastructure_failed_run",
                }
            )
            continue
        prior_manifest_path = Path(str(summary.get("source_manifest", "")))
        if not prior_manifest_path.is_file():
            run_checks.append(
                {
                    "result": str(result_path),
                    "compatible": False,
                    "reason": "missing_source_manifest",
                }
            )
            continue
        prior_shared = _shared_runtime_identity(_load_json(prior_manifest_path))
        if prior_shared != current_shared:
            run_checks.append(
                {
                    "result": str(result_path),
                    "compatible": False,
                    "reason": "shared_runtime_drift",
                    "shared_runtime_identity_sha256": prior_shared,
                }
            )
            continue
        document = _load_json(result_path)
        reused_here = []
        for row in document.get("results", {}).get("results", []):
            if row.get("success") is not True:
                continue
            identifier = str(
                row.get("vars", {}).get("case_id")
                or row.get("testCase", {}).get("metadata", {}).get("id")
            )
            if identifier not in selected_by_id or identifier in reusable:
                continue
            if _row_signature(row) != _case_signature(selected_by_id[identifier]):
                continue
            reusable[identifier] = {
                "case_id": identifier,
                "result": str(result_path),
                "row_id": row.get("id"),
                "case_signature_sha256": _case_signature(selected_by_id[identifier]),
            }
            reused_here.append(identifier)
        run_checks.append(
            {
                "result": str(result_path),
                "compatible": True,
                "reason": "shared_runtime_identical",
                "reused_case_ids": sorted(reused_here),
            }
        )

    selected_ids = list(selected_by_id)
    reused_ids = [identifier for identifier in selected_ids if identifier in reusable]
    fresh_ids = [identifier for identifier in selected_ids if identifier not in reusable]
    fresh_descriptions = [
        str(selected_by_id[identifier]["description"]) for identifier in fresh_ids
    ]
    fresh_pattern = (
        "^(?:" + "|".join(re.escape(value) for value in fresh_descriptions) + ")$"
        if fresh_descriptions
        else ""
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "profile": profile,
        "domain": domain,
        "requested_case_pattern": case_pattern,
        "current_source_manifest": str(current_manifest_path.resolve()),
        "shared_runtime_identity_sha256": current_shared,
        "selected_case_ids": selected_ids,
        "reused_case_ids": reused_ids,
        "fresh_case_ids": fresh_ids,
        "fresh_case_pattern": fresh_pattern,
        "reused": [reusable[identifier] for identifier in reused_ids],
        "run_checks": run_checks,
        "reuse_requires_terminal_pass": True,
        "fail_error_or_drift_reused": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    return output_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--current-manifest", type=Path, required=True)
    parser.add_argument("--reuse-result", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--domain", default="")
    parser.add_argument("--case-pattern", default="")
    return parser


def main() -> int:
    args = _parser().parse_args()
    path = select_incremental(
        args.cases,
        args.current_manifest,
        args.reuse_result,
        args.output,
        profile=args.profile,
        domain=args.domain,
        case_pattern=args.case_pattern,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
