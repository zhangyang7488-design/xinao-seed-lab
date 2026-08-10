#!/usr/bin/env python3
"""Build and verify one physically isolated semantic-implication case workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "xinao.semantic_implication_case_workspace.v3"
CASE_INPUT_SCHEMA = "xinao.semantic_implication_case_input.v3"
CASE_ID_PATTERN = re.compile(r"^[A-Z0-9_]+$")
CANONICAL_SELECTORS = {"canonical_variant", "canonical_recovery"}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _normalize_stdout(value: str) -> str:
    return value.replace("\r\n", "\n").rstrip()


def _safe_source(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"source escapes suite root: {relative}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _load_cases(cases_path: Path) -> list[dict[str, Any]]:
    document = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
    if not isinstance(document, list) or not document:
        raise ValueError("case source must be a non-empty list")
    return document


def _case_row(cases_path: Path, case_id: str) -> dict[str, Any]:
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError(f"unsafe case id: {case_id}")
    matches = [
        row
        for row in _load_cases(cases_path)
        if str(row.get("vars", {}).get("case_id") or "") == case_id
    ]
    if len(matches) != 1:
        raise ValueError(f"case id must resolve exactly once: {case_id}")
    return matches[0]


def _validated_case_input(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != CASE_INPUT_SCHEMA:
        raise ValueError("case input schema drift")
    case_input = dict(value)
    for field in ("read_nonce", "analysis_object_id"):
        if not isinstance(case_input.get(field), str) or not case_input[field].strip():
            raise ValueError(f"case input {field} must be a non-empty string")

    source_witnesses = case_input.get("source_witness_ids")
    if not isinstance(source_witnesses, list) or any(
        not isinstance(item, str) or not item.strip() for item in source_witnesses
    ):
        raise ValueError("case input source_witness_ids must be a string list")
    if len(source_witnesses) != len(set(source_witnesses)):
        raise ValueError("case input source_witness_ids must be unique")
    witness_set = set(source_witnesses)

    observations = case_input.get("observation_ids")
    if not isinstance(observations, list) or any(
        not isinstance(item, str) or not item.strip() for item in observations
    ):
        raise ValueError("case input observation_ids must be a string list")
    if len(observations) != len(set(observations)):
        raise ValueError("case input observation_ids must be unique")

    representations = case_input.get("representations")
    if not isinstance(representations, list):
        raise ValueError("case input representations must be a list")
    dimension_ids: list[str] = []
    used_witnesses: set[str] = set()
    for index, row in enumerate(representations):
        if not isinstance(row, dict):
            raise ValueError(f"case input representation {index} must be an object")
        dimension = row.get("dimension_id")
        witness = row.get("source_witness_id")
        if not isinstance(dimension, str) or not dimension.strip():
            raise ValueError(f"case input representation {index} has no dimension_id")
        if not isinstance(witness, str) or witness not in witness_set:
            raise ValueError(
                f"case input representation {index} references an undeclared source witness"
            )
        dimension_ids.append(dimension)
        used_witnesses.add(witness)
    if len(dimension_ids) != len(set(dimension_ids)):
        raise ValueError("case input representation dimension_ids must be unique")
    if representations and used_witnesses != witness_set:
        raise ValueError("case input declares an unused representation source witness")

    consumer = case_input.get("named_consumer")
    if not isinstance(consumer, dict) or not isinstance(consumer.get("consumer_id"), str):
        raise ValueError("case input named_consumer is invalid")
    consumer_dimensions = consumer.get("dimension_ids")
    if not isinstance(consumer_dimensions, list) or any(
        not isinstance(item, str) or item not in set(dimension_ids) for item in consumer_dimensions
    ):
        raise ValueError("case input consumer dimensions are not declared representations")
    if len(consumer_dimensions) != len(set(consumer_dimensions)):
        raise ValueError("case input consumer dimensions must be unique")
    return case_input


def workspace_inventory(workspace: Path) -> list[dict[str, object]]:
    root = workspace.resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"workspace contains a symbolic link: {relative}")
        if path.is_dir():
            rows.append({"path": relative, "type": "directory"})
        elif path.is_file():
            rows.append(
                {
                    "path": relative,
                    "type": "file",
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        else:
            raise ValueError(f"workspace contains a special entry: {relative}")
    return rows


def _selected_stimulus(canonical_path: Path, vars_: dict[str, Any]) -> dict[str, Any]:
    document = json.loads(canonical_path.read_text(encoding="utf-8"))
    matches = [row for row in document["cases"] if row.get("case_id") == vars_["source_case_id"]]
    if len(matches) != 1:
        raise ValueError("canonical selected case identity is missing or duplicated")
    case = matches[0]
    selector = str(vars_["source_selector"])
    if selector == "canonical_variant":
        members = [
            row
            for row in case["metamorphic_variants"]
            if row.get("variant_id") == vars_["source_member_id"]
        ]
        if len(members) != 1:
            raise ValueError("canonical selected variant identity is missing or duplicated")
        turns = list(members[0]["turns"])
    elif selector == "canonical_recovery":
        recovery = case["recovery_stimulus"]
        if recovery.get("stimulus_id") != vars_["source_member_id"]:
            raise ValueError("canonical selected recovery identity is missing")
        turns = list(recovery["turns"])
    else:
        raise ValueError(f"unsupported canonical selector: {selector}")
    order = str(vars_["pair_order"])
    if order == "BA":
        turns.reverse()
    return {
        "schema_version": "xinao.semantic_implication_delivered_stimulus.v2",
        "source_selector": selector,
        "source_case_id": str(vars_["source_case_id"]),
        "source_member_id": str(vars_["source_member_id"]),
        "turn_order": order,
        "turns": turns,
    }


def _command_sequence(vars_: dict[str, Any], case_input: dict[str, Any]) -> list[str]:
    case_id = str(vars_["case_id"])
    if str(vars_["family"]) == "stop_control":
        return []
    consumer = f"python -B consumer.py --case {case_id}"
    commands = [consumer]
    if str(vars_["source_selector"]) in CANONICAL_SELECTORS:
        commands.append(
            "python -B source_reader.py "
            f"--selector {vars_['source_selector']} "
            f"--case {vars_['source_case_id']} "
            f"--member {vars_['source_member_id']} "
            f"--order {vars_['pair_order']}"
        )
    if str(vars_["family"]) == "lifecycle":
        commands.extend(
            [
                f"python -B return_local_result.py --case {case_id}",
                consumer,
            ]
        )
    effect = case_input.get("effect") or {}
    if effect.get("authorized") is True:
        commands.extend(
            [
                f"python -B apply_change.py --case {case_id}",
                consumer,
            ]
        )
    return commands


def _execute_exact_command(workspace: Path, command: str) -> subprocess.CompletedProcess[str]:
    parts = command.split()
    if parts[:2] != ["python", "-B"] or len(parts) < 3:
        raise ValueError(f"unsupported oracle command: {command}")
    script = workspace / parts[2]
    if not script.is_file():
        raise FileNotFoundError(script)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(script), *parts[3:]],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
        timeout=30,
    )


def _stdout_observation_contract(command: str, stdout: str) -> dict[str, object]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "mode": "exact_text",
            "allowlisted_redaction_json_pointers": [],
        }
    if not isinstance(payload, dict):
        raise ValueError(f"oracle JSON stdout must be an object: {command}")
    allowlisted: list[str] = []
    if "consumer.py" in command:
        if "case_input_sha256" in payload:
            allowlisted.append("/case_input_sha256")
        facts = payload.get("facts")
        if isinstance(facts, dict):
            if "authorization" in facts:
                allowlisted.append("/facts/authorization")
            effect = facts.get("effect")
            if isinstance(effect, dict) and "authorized" in effect:
                allowlisted.append("/facts/effect/authorized")
    elif "source_reader.py" in command:
        for field in ("selected_file_sha256", "selected_stimulus_sha256"):
            if field in payload:
                allowlisted.append(f"/{field}")
    return {
        "mode": "exact_or_allowlisted_json_redaction",
        "allowlisted_redaction_json_pointers": allowlisted,
    }


def _simulate_trace(
    workspace: Path, commands: list[str]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    with tempfile.TemporaryDirectory(prefix="semantic-implication-oracle-") as temp:
        simulation = Path(temp) / "workspace"
        shutil.copytree(workspace, simulation)
        trace: list[dict[str, object]] = []
        for command in commands:
            completed = _execute_exact_command(simulation, command)
            stdout = _normalize_stdout(completed.stdout)
            stderr = _normalize_stdout(completed.stderr)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"oracle command failed ({command}): rc={completed.returncode}; stderr={stderr}"
                )
            trace.append(
                {
                    "command": command,
                    "exit_code": completed.returncode,
                    "stdout": stdout,
                    "stdout_sha256": _sha256_bytes(stdout.encode("utf-8")),
                    "stdout_observation": _stdout_observation_contract(command, stdout),
                }
            )
        return trace, workspace_inventory(simulation)


def _changed_paths(before: list[dict[str, object]], after: list[dict[str, object]]) -> list[str]:
    before_by_path = {str(row["path"]): row for row in before}
    after_by_path = {str(row["path"]): row for row in after}
    return sorted(
        path
        for path in before_by_path.keys() | after_by_path.keys()
        if before_by_path.get(path) != after_by_path.get(path)
    )


def prepare_workspace(
    *,
    suite_root: Path,
    cases_path: Path,
    canonical_path: Path,
    case_id: str,
    workspace: Path,
    manifest_path: Path,
) -> Path:
    suite_root = suite_root.resolve()
    cases_path = cases_path.resolve()
    canonical_path = canonical_path.resolve()
    workspace = workspace.resolve()
    manifest_path = manifest_path.resolve()
    row = _case_row(cases_path, case_id)
    vars_ = dict(row["vars"])
    fixture_source = _safe_source(suite_root / "fixtures", str(vars_["fixture_source"]))
    case_input = _validated_case_input(json.loads(fixture_source.read_text(encoding="utf-8")))
    case_input.update(
        {
            "case_id": case_id,
            "family": str(vars_["family"]),
            "source_selector": str(vars_["source_selector"]),
        }
    )
    if workspace.exists():
        raise FileExistsError(workspace)
    workspace.mkdir(parents=True)
    template = suite_root / "fixture_template"
    shutil.copyfile(_safe_source(template, "AGENTS.md"), workspace / "AGENTS.md")
    (workspace / "case_input.json").write_text(
        json.dumps(case_input, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    if str(vars_["family"]) != "stop_control":
        shutil.copyfile(_safe_source(template, "consumer.py"), workspace / "consumer.py")
    if str(vars_["source_selector"]) in CANONICAL_SELECTORS:
        stimulus = _selected_stimulus(canonical_path, vars_)
        (workspace / "selected_stimulus.json").write_text(
            json.dumps(stimulus, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="",
        )
        shutil.copyfile(_safe_source(template, "source_reader.py"), workspace / "source_reader.py")
    effect = case_input.get("effect")
    if isinstance(effect, dict):
        shutil.copyfile(_safe_source(template, "apply_change.py"), workspace / "apply_change.py")
        effect_root = workspace / "effects" / case_id
        effect_root.mkdir(parents=True)
        (effect_root / "target.txt").write_text(
            str(effect["initial_target"]) + "\n", encoding="utf-8", newline=""
        )
    if str(vars_["family"]) == "lifecycle":
        shutil.copyfile(
            _safe_source(template, "return_local_result.py"),
            workspace / "return_local_result.py",
        )
        (workspace / "parent_state.json").write_text(
            json.dumps(
                case_input["initial_parent_state"],
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="",
        )

    initial = workspace_inventory(workspace)
    commands = _command_sequence(vars_, case_input)
    trace, final = _simulate_trace(workspace, commands)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "description": str(row["description"]),
        "family": str(vars_["family"]),
        "pair_id": str(vars_["pair_id"]),
        "pair_order": str(vars_["pair_order"]),
        "workspace": str(workspace),
        "case_input_sha256": _sha256(workspace / "case_input.json"),
        "canonical_source_sha256": (
            _sha256(canonical_path)
            if str(vars_["source_selector"]) in CANONICAL_SELECTORS
            else None
        ),
        "selected_stimulus_sha256": (
            _sha256_bytes(
                _canonical_json(
                    json.loads((workspace / "selected_stimulus.json").read_text(encoding="utf-8"))
                ).encode("utf-8")
            )
            if (workspace / "selected_stimulus.json").is_file()
            else None
        ),
        "trace": trace,
        "initial_inventory": initial,
        "final_inventory": final,
        "changed_paths": _changed_paths(initial, final),
        "oracle_files_exposed": False,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    return manifest_path


def verify_workspace(manifest_path: Path, *, phase: str) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("workspace manifest schema drift")
    workspace = Path(manifest["workspace"])
    actual = workspace_inventory(workspace)
    key = "initial_inventory" if phase == "initial" else "final_inventory"
    if actual != manifest[key]:
        raise ValueError(
            f"workspace inventory differs from {phase} contract: "
            f"actual={_sha256_bytes(_canonical_json(actual).encode('utf-8'))}; "
            f"contract={_sha256_bytes(_canonical_json(manifest[key]).encode('utf-8'))}"
        )
    return {
        "schema_version": "xinao.semantic_implication_case_workspace_verification.v3",
        "case_id": manifest["case_id"],
        "workspace": str(workspace),
        "phase": phase,
        "inventory_sha256": _sha256_bytes(_canonical_json(actual).encode("utf-8")),
        "changed_paths": manifest["changed_paths"],
        "verified": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_cases = subparsers.add_parser("list")
    list_cases.add_argument("--cases", type=Path, required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--suite-root", type=Path, required=True)
    prepare.add_argument("--cases", type=Path, required=True)
    prepare.add_argument("--canonical", type=Path, required=True)
    prepare.add_argument("--case-id", required=True)
    prepare.add_argument("--workspace", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--phase", choices=("initial", "final"), required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "list":
        rows = [
            {
                "case_id": row["vars"]["case_id"],
                "description": row["description"],
            }
            for row in _load_cases(args.cases)
        ]
        print(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
        return 0
    if args.command == "prepare":
        print(
            prepare_workspace(
                suite_root=args.suite_root,
                cases_path=args.cases,
                canonical_path=args.canonical,
                case_id=args.case_id,
                workspace=args.workspace,
                manifest_path=args.manifest,
            )
        )
        return 0
    result = verify_workspace(args.manifest, phase=args.phase)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
