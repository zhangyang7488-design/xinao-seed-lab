from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_bundle_runner import (
    BUNDLE_SCHEMA_VERSION,
    build_assertion_request_v2,
    run_canonical_bundle_fresh,
)
from xinao.foundation.assertion_verifier_registry import load_canonical_actuals_callable
from xinao.foundation.assertion_verifiers.common import active_quote_projection
from xinao.foundation.assertion_verifiers.f2_assertion_actuals import ASSERTION_IDS
from xinao.foundation.f2_compile import compile_f2_artifacts
from xinao.foundation.selection_manifest import (
    compile_atomic_ticket_bindings,
    compile_independent_selection_manifest,
    load_play_catalog,
)
from xinao.foundation.semantics_registry import (
    DEFAULT_PLAY_CATALOG_PATH,
    compile_semantics_registry,
)
from xinao.foundation.world_compile import DEFAULT_AUTHORITY_DATASET_PATH


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(value))
    return path


def test_f2_registry_resolves_the_actuals_only_callable() -> None:
    entry, verifier = load_canonical_actuals_callable("F2_issuer_settlement_cost_space")

    assert entry.module_name == "xinao.foundation.assertion_verifiers.f2_assertion_actuals"
    assert entry.source_path.is_file()
    assert verifier.__name__ == "build_assertion_actuals_v1"


def test_current_f2_actuals_run_through_the_v2_fresh_process_bridge(tmp_path: Path) -> None:
    catalog = load_play_catalog()
    registry = compile_semantics_registry(catalog)
    independent = compile_independent_selection_manifest(catalog)
    atomic = compile_atomic_ticket_bindings(catalog, independent)
    report = compile_f2_artifacts(registry, atomic_ticket_bindings=atomic)

    artifact_payloads = {
        "SettlementProbabilitySnapshotVersion": report.probability_snapshot.model_dump(
            mode="json"
        ),
        "RebateScheduleVersion": report.rebate_schedule.model_dump(mode="json"),
        "SettlementCostSurfaceVersion": report.cost_surface.model_dump(mode="json"),
        "OddsSpaceBenchmarkVersion": report.odds_space_benchmark.model_dump(mode="json"),
        "SettlementCostCompileReport": report.model_dump(mode="json"),
    }
    materials: dict[str, dict[str, Any]] = {}
    for artifact_type, payload in artifact_payloads.items():
        path = _write_json(tmp_path / "artifacts" / f"{artifact_type}.json", payload)
        materials[artifact_type] = {
            "version": str(payload.get("version_id") or payload["schema_version"]),
            "source_ref": {"path": str(path), "sha256": _sha256(path)},
            "payload": payload,
        }

    input_paths = {
        "play_catalog_sha256": DEFAULT_PLAY_CATALOG_PATH,
        "dataset_sha256": DEFAULT_AUTHORITY_DATASET_PATH,
        "rule_semantic_map_sha256": _write_json(
            tmp_path / "inputs" / "rule-semantic-map.json",
            registry.rule_semantic_map.model_dump(mode="json"),
        ),
        "active_quote_projection_sha256": _write_json(
            tmp_path / "inputs" / "active-quote-projection.json",
            active_quote_projection(registry),
        ),
    }
    for key in (
        "baseline_sha256",
        "compiler_code_sha256",
        "compiler_config_sha256",
        "f3_external_synthesis_sha256",
        "f3_prior_draft_sha256",
        "f3_service_graph_sha256",
    ):
        input_paths[key] = _write_json(
            tmp_path / "inputs" / f"{key}.json",
            {"test_binding": key},
        )
    input_refs = {
        key: {"path": str(path), "sha256": _sha256(path)}
        for key, path in input_paths.items()
    }
    input_hashes = {key: ref["sha256"] for key, ref in input_refs.items()}
    request = build_assertion_request_v2(
        block_id="F2_issuer_settlement_cost_space",
        assertion_ids=ASSERTION_IDS,
        input_refs=input_refs,
        input_hashes=input_hashes,
        materials=materials,
        compiler_code_sha256=input_hashes["compiler_code_sha256"],
        compiler_config_sha256=input_hashes["compiler_config_sha256"],
    )
    request_path = _write_json(tmp_path / "request.v2.json", request)
    output_path = tmp_path / "bundle.v2.json"

    receipt = run_canonical_bundle_fresh(
        request_path=request_path,
        block_id="F2_issuer_settlement_cost_space",
        output_path=output_path,
        timeout=600,
    )

    bundle = json.loads(output_path.read_text(encoding="utf-8"))
    content_hash = bundle.pop("content_sha256")
    actuals = bundle["assertion_actuals"]
    assert receipt == {"ok": True, "sha256": _sha256(output_path)}
    assert bundle["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert bundle["block_id"] == "F2_issuer_settlement_cost_space"
    assert set(actuals) == set(ASSERTION_IDS)
    assert actuals["all_active_settlement_objects_covered"] == 416
    assert actuals["normal_principal_refund_eq"] is False
    assert actuals["actual_exposure_or_realized_profit_claimed"] is False
    assert actuals["formula_replay_hash_stable"] is True
    assert canonical_sha256(bundle) == content_hash
