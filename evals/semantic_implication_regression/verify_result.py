from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

PAIR_FIELDS = (
    "analysis_object_id",
    "evidence_source_witness_ids",
    "functional_dimension_ids",
    "relation_evidence_refs",
)


def _walk(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _identity(row: dict[str, Any], key: str) -> str:
    values = [value for name, value in _walk(row) if name == key and value]
    if not values:
        raise ValueError(f"fresh-consumer row has no {key}")
    return str(values[0])


def _vars(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("vars") or row.get("testCase", {}).get("vars") or {}
    if not isinstance(value, dict):
        raise ValueError("result row has no case vars")
    return value


def _output(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("response", {}).get("output")
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("result row has no model output")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("model output is not an object")
    return parsed


def _app_server(row: dict[str, Any]) -> dict[str, Any]:
    for candidate in (
        row.get("metadata", {}).get("codexAppServer"),
        row.get("response", {}).get("metadata", {}).get("codexAppServer"),
    ):
        if isinstance(candidate, dict):
            return candidate
    raise ValueError("fresh-consumer row has no app-server trace")


def _stdout_hash(app_server: dict[str, Any], command_name: str) -> str | None:
    outputs = [
        str(item.get("aggregatedOutput") or "").replace("\r\n", "\n").rstrip()
        for item in app_server.get("items", [])
        if item.get("type") == "commandExecution"
        and command_name.lower() in str(item.get("command") or "").lower()
    ]
    if not outputs:
        return None
    return hashlib.sha256("\n".join(outputs).encode("utf-8")).hexdigest()


def _selected_stimulus_hash(app_server: dict[str, Any]) -> str | None:
    outputs = [
        str(item.get("aggregatedOutput") or "")
        for item in app_server.get("items", [])
        if item.get("type") == "commandExecution"
        and "source_reader.py" in str(item.get("command") or "").lower()
    ]
    if not outputs:
        return None
    if len(outputs) != 1:
        raise ValueError("selected source was delivered more than once in one fresh turn")
    payload = json.loads(outputs[0])
    if payload.get("status") != "SEMANTIC_IMPLICATION_SOURCE_OK":
        raise ValueError("source reader status is invalid")
    stimulus = payload.get("stimulus")
    if not isinstance(stimulus, dict):
        raise ValueError("source reader stimulus is missing")
    computed = hashlib.sha256(
        json.dumps(
            stimulus,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    declared = str(payload.get("selected_stimulus_sha256") or "")
    if declared not in {computed, "[REDACTED]"}:
        raise ValueError("source reader stimulus hash is neither exact nor redacted")
    return computed


def _rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        selected = document.get("results", {}).get("results", [])
        if not isinstance(selected, list) or not selected:
            raise ValueError(f"Promptfoo result contains no rows: {path}")
        rows.extend(selected)
    return rows


def _normalized_pair_field(value: Any) -> Any:
    if isinstance(value, list):
        return sorted(str(item) for item in value)
    return value


def verify_results(
    result_paths: list[Path],
    manifest_paths: list[Path],
    *,
    required_case_count: int | None = None,
    canonical_source_sha256: str | None = None,
) -> dict[str, Any]:
    rows = _rows(result_paths)
    if required_case_count is not None and len(rows) != required_case_count:
        raise ValueError(f"required {required_case_count} selected rows, observed {len(rows)}")
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in manifest_paths]
    manifest_by_id = {str(row.get("case_id") or ""): row for row in manifests}
    if len(manifest_by_id) != len(manifests) or "" in manifest_by_id:
        raise ValueError("case workspace manifests are missing or duplicated")

    by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    threads: list[str] = []
    turns: list[str] = []
    workspaces: list[str] = []
    stimuli: list[dict[str, Any]] = []
    for row in rows:
        if row.get("success") is not True:
            raise ValueError("result contains a non-passing row")
        vars_ = _vars(row)
        case_id = str(vars_.get("case_id") or "")
        if not case_id or case_id in by_id:
            raise ValueError("result case identities are missing or duplicated")
        output = _output(row)
        if output.get("case_id") != case_id:
            raise ValueError(f"output identity mismatch for {case_id}")
        manifest = manifest_by_id.get(case_id)
        if manifest is None:
            raise ValueError(f"case has no workspace manifest: {case_id}")
        app_server = _app_server(row)
        thread_id = _identity(row, "threadId")
        turn_id = _identity(row, "turnId")
        workspace = str(manifest["workspace"])
        if Path(str(app_server.get("cwd") or "")).resolve() != Path(workspace).resolve():
            raise ValueError(f"consumer workspace identity mismatch for {case_id}")
        prompt_raw = row.get("prompt", {}).get("raw")
        if not isinstance(prompt_raw, str) or case_id not in prompt_raw:
            raise ValueError(f"rendered stimulus is missing for {case_id}")
        provider = row.get("provider", {})
        provider_id = str(provider.get("id") or "") if isinstance(provider, dict) else ""
        if not provider_id:
            raise ValueError(f"provider entry identity is missing for {case_id}")
        selected_stimulus_sha256 = _selected_stimulus_hash(app_server)
        manifest_stimulus = manifest.get("selected_stimulus_sha256")
        if selected_stimulus_sha256 != manifest_stimulus:
            raise ValueError(f"selected source readback mismatch for {case_id}")
        by_id[case_id] = (vars_, output)
        threads.append(thread_id)
        turns.append(turn_id)
        workspaces.append(str(Path(workspace).resolve()).lower())
        stimuli.append(
            {
                "case_id": case_id,
                "provider_id": provider_id,
                "thread_id": thread_id,
                "turn_id": turn_id,
                "workspace": workspace,
                "prompt_sha256": hashlib.sha256(prompt_raw.encode("utf-8")).hexdigest(),
                "source_reader_stdout_sha256": _stdout_hash(app_server, "source_reader.py"),
                "selected_stimulus_sha256": selected_stimulus_sha256,
                "consumer_stdout_sha256": _stdout_hash(app_server, "consumer.py"),
                "effect_stdout_sha256": _stdout_hash(app_server, "apply_change.py"),
                "local_return_stdout_sha256": _stdout_hash(app_server, "return_local_result.py"),
                "workspace_initial_inventory_sha256": hashlib.sha256(
                    json.dumps(
                        manifest["initial_inventory"],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "workspace_final_inventory_sha256": hashlib.sha256(
                    json.dumps(
                        manifest["final_inventory"],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "changed_paths": manifest["changed_paths"],
            }
        )

    if set(by_id) != set(manifest_by_id):
        raise ValueError("result and workspace manifest case sets differ")
    if len(threads) != len(set(threads)):
        raise ValueError("fresh-consumer cases reused a thread")
    if len(turns) != len(set(turns)):
        raise ValueError("fresh-consumer cases reused a turn")
    if len(workspaces) != len(set(workspaces)):
        raise ValueError("fresh-consumer cases reused a physical workspace")

    pair_members: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
    for case_id, (vars_, output) in by_id.items():
        pair_id = str(vars_.get("pair_id") or "")
        if pair_id:
            pair_members.setdefault(pair_id, []).append((case_id, vars_, output))
    checked_pairs: list[str] = []
    for pair_id, members in pair_members.items():
        if len(members) != 2:
            raise ValueError(f"metamorphic pair {pair_id} has {len(members)} results")
        orders = {str(member[1].get("pair_order") or "") for member in members}
        if orders != {"AB", "BA"}:
            raise ValueError(f"metamorphic pair {pair_id} lacks exact AB/BA members")
        left = {key: _normalized_pair_field(members[0][2].get(key)) for key in PAIR_FIELDS}
        right = {key: _normalized_pair_field(members[1][2].get(key)) for key in PAIR_FIELDS}
        if left != right:
            raise ValueError(f"metamorphic pair {pair_id} changed under AB/BA order")
        checked_pairs.append(pair_id)

    return {
        "schema_version": "xinao.semantic_implication_result_verification.v2",
        "selected_case_count": len(by_id),
        "case_ids": sorted(by_id),
        "fresh_thread_count": len(threads),
        "fresh_turn_count": len(turns),
        "fresh_workspace_count": len(workspaces),
        "checked_metamorphic_pairs": sorted(checked_pairs),
        "canonical_source_sha256": canonical_source_sha256,
        "delivered_stimuli": sorted(stimuli, key=lambda item: item["case_id"]),
        "result_files": [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in result_paths
        ],
        "all_rows_passed": True,
        "runtime_claim_scope": "observed fresh trajectories only",
        "hidden_state_claim_allowed": False,
        "automatic_core_rewrite_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, action="append", required=True)
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--required-case-count", type=int)
    parser.add_argument("--canonical-source-sha256")
    args = parser.parse_args()
    receipt = verify_results(
        args.result,
        args.manifest,
        required_case_count=args.required_case_count,
        canonical_source_sha256=args.canonical_source_sha256,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    print(args.receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
