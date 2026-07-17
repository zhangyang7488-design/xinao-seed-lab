from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_bundle_runner import (
    BUNDLE_SCHEMA_VERSION,
    AssertionBundleRunnerError,
    build_assertion_request_v2,
    build_bundle_bytes_v2,
    run_canonical_bundle_fresh,
)
from xinao.foundation.assertion_verifier_registry import load_canonical_actuals_callable
from xinao.foundation.assertion_verifiers.common import (
    AssertionActualsError,
    active_quote_projection,
)
from xinao.foundation.f3_assertions import (
    F3_REQUIRED_ASSERTION_EXPECTATIONS,
    F3_REQUIRED_ASSERTION_IDS,
    compile_f3_assertion_actuals,
)
from xinao.foundation.research_weight import canonical_sha256 as f3_canonical_sha256
from xinao.foundation.research_weight_inputs import (
    DEFAULT_EXTERNAL_SYNTHESIS_PATH,
    DEFAULT_PRIOR_DRAFT_PATH,
    DEFAULT_SERVICE_GRAPH_PATH,
    compile_current_research_weight_foundation,
)
from xinao.foundation.selection_manifest import load_play_catalog
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


def _rehash_versioned_object(payload: dict[str, Any]) -> dict[str, Any]:
    core = deepcopy(payload)
    core.pop("content_sha256", None)
    core.pop("version_id", None)
    digest = f3_canonical_sha256(core)
    return {
        **core,
        "version_id": f"{core['object_type']}@{digest[:16]}",
        "content_sha256": digest,
    }


@pytest.fixture(scope="module")
def current_f3_case(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("f3-actuals")
    catalog = load_play_catalog()
    registry = compile_semantics_registry(catalog)
    bundle = compile_current_research_weight_foundation(semantics_registry=registry)

    materials: dict[str, dict[str, Any]] = {}
    for artifact_type, payload in bundle["objects"].items():
        path = _write_json(root / "artifacts" / f"{artifact_type}.json", payload)
        materials[artifact_type] = {
            "version": payload["version_id"],
            "source_ref": {"path": str(path), "sha256": _sha256(path)},
            "payload": payload,
        }

    input_paths = {
        "active_quote_projection_sha256": _write_json(
            root / "inputs" / "active-quote-projection.json",
            active_quote_projection(registry),
        ),
        "dataset_sha256": DEFAULT_AUTHORITY_DATASET_PATH,
        "f3_external_synthesis_sha256": DEFAULT_EXTERNAL_SYNTHESIS_PATH,
        "f3_prior_draft_sha256": DEFAULT_PRIOR_DRAFT_PATH,
        "f3_service_graph_sha256": DEFAULT_SERVICE_GRAPH_PATH,
        "play_catalog_sha256": DEFAULT_PLAY_CATALOG_PATH,
        "rule_semantic_map_sha256": _write_json(
            root / "inputs" / "rule-semantic-map.json",
            registry.rule_semantic_map.model_dump(mode="json"),
        ),
    }
    for key in ("baseline_sha256", "compiler_code_sha256", "compiler_config_sha256"):
        input_paths[key] = _write_json(
            root / "inputs" / f"{key}.json",
            {"test_binding": key},
        )
    input_refs = {
        key: {"path": str(path), "sha256": _sha256(path)}
        for key, path in input_paths.items()
    }
    input_hashes = {key: ref["sha256"] for key, ref in input_refs.items()}
    request = build_assertion_request_v2(
        block_id="F3_research_weight",
        assertion_ids=F3_REQUIRED_ASSERTION_IDS,
        input_refs=input_refs,
        input_hashes=input_hashes,
        materials=materials,
        compiler_code_sha256=input_hashes["compiler_code_sha256"],
        compiler_config_sha256=input_hashes["compiler_config_sha256"],
    )
    return {"root": root, "bundle": bundle, "request": request}


def test_f3_registry_resolves_the_actuals_only_callable() -> None:
    entry, verifier = load_canonical_actuals_callable("F3_research_weight")

    assert entry.module_name == "xinao.foundation.assertion_verifiers.f3_assertion_actuals"
    assert entry.source_path.is_file()
    assert verifier.__name__ == "build_assertion_actuals_v1"


def test_current_f3_actuals_run_through_the_v2_fresh_process_bridge(
    current_f3_case: dict[str, Any],
) -> None:
    root = current_f3_case["root"]
    request_path = _write_json(root / "request.v2.json", current_f3_case["request"])
    output_path = root / "bundle.v2.json"

    receipt = run_canonical_bundle_fresh(
        request_path=request_path,
        block_id="F3_research_weight",
        output_path=output_path,
        timeout=600,
    )

    bundle = json.loads(output_path.read_text(encoding="utf-8"))
    content_hash = bundle.pop("content_sha256")
    actuals = bundle["assertion_actuals"]
    assert receipt == {"ok": True, "sha256": _sha256(output_path)}
    assert bundle["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert bundle["block_id"] == "F3_research_weight"
    assert actuals == F3_REQUIRED_ASSERTION_EXPECTATIONS
    assert canonical_sha256(bundle) == content_hash


def test_f3_actuals_reject_missing_bound_input(
    current_f3_case: dict[str, Any],
) -> None:
    request = deepcopy(current_f3_case["request"])
    del request["input_evidence"]["f3_prior_draft_sha256"]
    del request["input_hashes"]["f3_prior_draft_sha256"]

    with pytest.raises(AssertionActualsError, match="input_refs key mismatch"):
        build_bundle_bytes_v2(request=request, block_id="F3_research_weight")


def test_f3_actuals_reject_hash_consistent_staged_object_drift(
    current_f3_case: dict[str, Any],
) -> None:
    request = deepcopy(current_f3_case["request"])
    artifact_type = "ResearchPortfolioPolicyVersion"
    envelope = request["artifacts"][artifact_type]["staged_envelope"]
    mutated = deepcopy(envelope["payload"])
    mutated["exploration_share"] = "0"
    mutated = _rehash_versioned_object(mutated)
    path = _write_json(current_f3_case["root"] / "negative" / "policy.json", mutated)
    envelope["payload"] = mutated
    envelope["payload_sha256"] = canonical_sha256(mutated)
    envelope["source_ref"] = {"path": str(path), "sha256": _sha256(path)}
    envelope["version"] = mutated["version_id"]
    request["artifacts"][artifact_type]["staged_envelope_content_sha256"] = canonical_sha256(
        envelope
    )

    with pytest.raises(AssertionActualsError, match="do not equal current recomputation"):
        build_bundle_bytes_v2(request=request, block_id="F3_research_weight")


def test_f3_assertions_expose_measured_and_full_space_claims_as_failures(
    current_f3_case: dict[str, Any],
) -> None:
    bundle = deepcopy(current_f3_case["bundle"])
    prior = bundle["objects"]["ResearchAttentionPriorVersion"]
    prior["prior_identity"] = "MEASURED_ATTENTION_PRIOR"
    bundle["objects"]["ResearchAttentionPriorVersion"] = _rehash_versioned_object(prior)
    bundle["discovery_language_ready"] = "DISCOVERY_LANGUAGE_READY"

    actuals = compile_f3_assertion_actuals(bundle)

    assert actuals["research_attention_prior_identity_eq"] == "MEASURED_ATTENTION_PRIOR"
    assert actuals["full_research_space_claimed"] is True


def test_f3_request_cannot_smuggle_expectations(
    current_f3_case: dict[str, Any],
) -> None:
    request = {**deepcopy(current_f3_case["request"]), "expected": {"status": "PASS"}}

    with pytest.raises(AssertionBundleRunnerError, match="request keys are not exact"):
        build_bundle_bytes_v2(request=request, block_id="F3_research_weight")
