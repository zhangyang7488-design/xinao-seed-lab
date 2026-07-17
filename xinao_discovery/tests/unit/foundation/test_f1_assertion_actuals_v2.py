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
from xinao.foundation.assertion_verifiers.common import active_quote_projection
from xinao.foundation.assertion_verifiers.f1_assertion_actuals import ASSERTION_IDS
from xinao.foundation.f1_replay import compile_f1_replay_evidence
from xinao.foundation.selection_manifest import (
    compile_atomic_ticket_bindings,
    compile_independent_selection_manifest,
    load_play_catalog,
)
from xinao.foundation.semantics_registry import (
    DEFAULT_PLAY_CATALOG_PATH,
    compile_semantics_registry,
)
from xinao.foundation.world_compile import (
    DEFAULT_AUTHORITY_DATASET_PATH,
    compile_functional_world,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(value))
    return path


def test_current_f1_actuals_run_through_the_v2_fresh_process_bridge(tmp_path: Path) -> None:
    catalog = load_play_catalog()
    registry = compile_semantics_registry(catalog)
    independent = compile_independent_selection_manifest(catalog)
    atomic = compile_atomic_ticket_bindings(catalog, independent)
    seed_world = compile_functional_world(registry, DEFAULT_AUTHORITY_DATASET_PATH)
    seed_replay = compile_f1_replay_evidence(registry, seed_world.world_snapshot)
    world = compile_functional_world(
        registry,
        DEFAULT_AUTHORITY_DATASET_PATH,
        replay_results=tuple(item.result for item in seed_replay.cases),
    )

    artifact_payloads = {
        "RuleSemanticMapVersion": registry.rule_semantic_map.model_dump(mode="json"),
        "ExpectedSelectionDomainManifestVersion": (
            registry.expected_selection_domain.model_dump(mode="json")
        ),
        "AtomicTicketBindingVersion": atomic.model_dump(mode="json"),
        "RuleSetVersion": registry.rule_set.model_dump(mode="json"),
        "SettlementFunctionSetVersion": (registry.settlement_function_set.model_dump(mode="json")),
        "EventMatrixSnapshot": world.event_matrix_snapshot.model_dump(mode="json"),
        "WorldSnapshot": world.world_snapshot.model_dump(mode="json"),
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
        key: {"path": str(path), "sha256": _sha256(path)} for key, path in input_paths.items()
    }
    input_hashes = {key: ref["sha256"] for key, ref in input_refs.items()}
    request = build_assertion_request_v2(
        block_id="F1_settlement_world",
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
        block_id="F1_settlement_world",
        output_path=output_path,
        timeout=600,
    )

    bundle = json.loads(output_path.read_text(encoding="utf-8"))
    content_hash = bundle.pop("content_sha256")
    assert receipt == {"ok": True, "sha256": _sha256(output_path)}
    assert bundle["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert bundle["block_id"] == "F1_settlement_world"
    assert set(bundle["assertion_actuals"]) == set(ASSERTION_IDS)
    assert bundle["assertion_actuals"]["catalog_total_eq"] == 433
    assert bundle["assertion_actuals"]["active_settlement_compiled_eq"] == 416
    assert bundle["assertion_actuals"]["actual_event_key_set_equals_expected"] is True
    assert bundle["assertion_actuals"]["fresh_process_world_hash_equals_recorded"] is True
    assert bundle["assertion_actuals"]["reordered_input_world_hash_equals_recorded"] is True
    assert canonical_sha256(bundle) == content_hash
