from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import rfc8785

from xinao.foundation import f1_pure_ascii_stream_worker as worker


def _baseline(
    baseline_id: str,
    family_id: str,
    digit: str,
    *,
    atomic: bool,
) -> dict[str, object]:
    return {
        "family_id": family_id,
        "payload": {
            "atomic_ticket_binding_hash": digit * 64 if atomic else None,
            "atomic_ticket_binding_id": f"atomic-{baseline_id}" if atomic else None,
            "baseline_id": baseline_id,
            "registry_selection_domain_hash": digit * 64,
            "selection_domain_hash": digit * 64,
            "selection_domain_spec_id": f"selection-{baseline_id}",
            "semantic_record_hash": digit * 64,
            "settlement_function_ref": f"settle-{baseline_id}",
        },
    }


def _draw(draw_id: str, draw_date: str, digit: str) -> dict[str, str]:
    return {
        "draw_date": draw_date,
        "draw_fingerprint": digit * 64,
        "draw_id": draw_id,
        "draw_replay_input_hash": digit * 64,
    }


def _projection() -> dict[str, object]:
    baselines = [
        _baseline("BO0001", "family-a", "1", atomic=False),
        _baseline("BO0002", "family-b", "2", atomic=True),
    ]
    draws = [
        _draw("2024001", "2024-01-01", "3"),
        _draw("2024002", "2024-01-01", "4"),
    ]
    return {
        "schema_version": worker.PROJECTION_SCHEMA,
        "expected_baseline_count": len(baselines),
        "expected_draw_count": len(draws),
        "expected_cell_count": len(baselines) * len(draws),
        "baselines": baselines,
        "draws": draws,
    }


def _projection_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _run_worker(value: dict[str, object]) -> subprocess.CompletedProcess[bytes]:
    environment = {
        key: item for key, item in os.environ.items() if not key.upper().startswith("PYTHON")
    }
    return subprocess.run(
        [
            str(Path(sys.executable).resolve()),
            "-X",
            "faulthandler",
            "-I",
            "-S",
            str(Path(worker.__file__).resolve()),
        ],
        input=_projection_bytes(value),
        capture_output=True,
        check=False,
        env=environment,
        timeout=30,
    )


def _full_cell(draw: dict[str, str], baseline: dict[str, object]) -> dict[str, object]:
    payload = baseline["payload"]
    assert isinstance(payload, dict)
    return {
        "schema_version": "xinao.functional_event_cell.v1",
        "surface_kind": "FUNCTIONAL_EVENT_SURFACE",
        "physical_role": "ACTIVE_SETTLEMENT",
        "draw_id": draw["draw_id"],
        **payload,
        "draw_fingerprint": draw["draw_fingerprint"],
        "draw_replay_input_hash": draw["draw_replay_input_hash"],
        "draw_date": draw["draw_date"],
        "zodiac_basis_ref": "SOURCE_API_ZODIAC_FIELDS_UNMODIFIED.v1",
    }


def test_fixed_ascii_encoder_is_rfc8785_equivalent_for_both_binding_variants() -> None:
    projection = _projection()
    baselines = projection["baselines"]
    draws = projection["draws"]
    assert isinstance(baselines, list) and isinstance(draws, list)
    assert (
        tuple(sorted(worker.CELL_KEYS, key=lambda value: value.encode("utf-16be")))
        == worker.CELL_KEYS
    )

    for baseline_index, baseline in enumerate(baselines):
        assert isinstance(baseline, dict)
        prepared_baseline = worker._prepare_baseline(baseline, baseline_index)
        for draw_index, draw in enumerate(draws):
            assert isinstance(draw, dict)
            prepared_draw = worker._prepare_draw(draw, draw_index)
            assert worker._canonical_cell(prepared_draw, prepared_baseline) == rfc8785.dumps(
                _full_cell(draw, baseline)
            )


def test_worker_is_order_independent_and_accepts_same_day_distinct_draw_ids() -> None:
    ordered = _projection()
    reversed_projection = deepcopy(ordered)
    reversed_projection["baselines"] = list(reversed(reversed_projection["baselines"]))
    reversed_projection["draws"] = list(reversed(reversed_projection["draws"]))

    first = _run_worker(ordered)
    second = _run_worker(reversed_projection)
    assert first.returncode == second.returncode == 0
    first_result = json.loads(first.stdout)
    second_result = json.loads(second.stdout)
    for field in (
        "ordered_cell_stream_sha256",
        "ordered_merkle_root",
        "family_cell_counts",
        "key_proof",
        "cell_count",
    ):
        assert first_result[field] == second_result[field]
    assert first_result["key_proof"] == {
        "actual_stream_key_count": 4,
        "duplicate_cartesian_keys": 0,
        "expected_cartesian_key_count": 4,
        "first_canonical_key": ["2024001", "BO0001"],
        "last_canonical_key": ["2024002", "BO0002"],
        "missing_cartesian_keys": 0,
        "strictly_ordered": True,
        "unexpected_cartesian_keys": 0,
    }
    source = Path(worker.__file__).read_bytes()
    assert first_result["worker_sha256"] == hashlib.sha256(source).hexdigest()
    assert first_result["worker_size_bytes"] == len(source)
    assert (
        first_result["projection_sha256"] == hashlib.sha256(_projection_bytes(ordered)).hexdigest()
    )
    assert first_result["isolated_mode"] is True
    assert first_result["no_site"] is True
    assert first_result["forbidden_module_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("extra", "projection keys are not exact"),
        ("missing", "projection keys are not exact"),
        ("count", "expected cell count is not baseline x draw"),
        ("unsafe", "requires JSON escaping"),
        ("type", "must be a positive integer"),
        ("duplicate_baseline", "duplicate identities"),
        ("duplicate_draw", "duplicate identities"),
    ),
)
def test_worker_rejects_projection_shape_type_domain_and_identity_tampering(
    mutation: str, message: str
) -> None:
    projection = _projection()
    if mutation == "extra":
        projection["extra"] = True
    elif mutation == "missing":
        projection.pop("draws")
    elif mutation == "count":
        projection["expected_cell_count"] = 5
    elif mutation == "unsafe":
        projection["baselines"][0]["payload"]["settlement_function_ref"] = 'bad"ref'
    elif mutation == "type":
        projection["expected_draw_count"] = True
    elif mutation == "duplicate_baseline":
        projection["baselines"][1]["payload"]["baseline_id"] = "BO0001"
    elif mutation == "duplicate_draw":
        projection["draws"][1]["draw_id"] = "2024001"
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(mutation)

    completed = _run_worker(projection)
    assert completed.returncode != 0
    assert message in completed.stderr.decode("utf-8", errors="replace")


def test_worker_source_imports_only_stdlib_and_has_no_hidden_runtime_adapter() -> None:
    source_path = Path(worker.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots == {
        "__future__",
        "collections",
        "hashlib",
        "json",
        "pathlib",
        "sys",
    }
    assert not {"xinao", "pydantic", "pydantic_core", "rfc8785"} & imported_roots
