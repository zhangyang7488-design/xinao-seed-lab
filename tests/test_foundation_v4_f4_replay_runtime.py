from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from xinao.foundation import foundation_v4_replay_runtime as replay_runtime
from xinao.foundation.foundation_v4_replay_runtime import FoundationV4ReplayError

F4_ASSERTION_IDS = (
    "backpressure_partial_failure_cancel_and_recovery_verified",
    "canonical_work_key_and_source_dependency_dedup_verified",
    "codex_single_writer_boundary_verified",
    "d_drive_evidence_binding_verified",
    "deterministic_fan_in_without_majority_vote_verified",
    "dynamic_multi_lane_capacity_ladder_verified",
    "fixed_time_split_and_leakage_rejection_verified",
    "independent_critique_verified",
    "negative_controls_and_error_budget_verified",
    "open_method_typed_admission_verified",
    "real_model_identity_and_lane_artifacts_verified",
    "real_temporal_workflow_history_verified",
    "research_portfolio_ready_frontier_verified",
    "typed_handoff_and_evidence_schemas_verified",
)
F4_ARTIFACT_NAMES = (
    "DedupPolicyVersion",
    "DeterministicFanInPolicyVersion",
    "DynamicCapacityPolicyVersion",
    "EvidenceSchemaVersion",
    "ResearchFactoryCanaryReport",
    "ResearchWorkItemSchemaVersion",
    "TypedHandoffSchemaVersion",
    "ValidationCourtInterfaceVersion",
)
F4_INPUT_NAMES = (
    "active_quote_projection_sha256",
    "baseline_sha256",
    "compiler_code_sha256",
    "compiler_config_sha256",
    "dataset_sha256",
    "f3_external_synthesis_sha256",
    "f3_prior_draft_sha256",
    "f3_service_graph_sha256",
    "play_catalog_sha256",
    "rule_semantic_map_sha256",
)


def _raw_bundle_for_spec(
    tmp_path: Path,
    spec: replay_runtime._ReplayBlockSpec,
) -> tuple[bytes, dict[str, str]]:
    entrypoint = tmp_path / f"{spec.block_id}.py"
    entrypoint.write_text("# sealed\n", encoding="utf-8")
    entrypoint_sha256 = replay_runtime._sha256(entrypoint.read_bytes())
    actuals = {assertion_id: {"observed": assertion_id} for assertion_id in spec.assertion_ids}
    actual_hashes = {
        assertion_id: replay_runtime._canonical_sha256(
            {"assertion_id": assertion_id, "actual": actuals[assertion_id]}
        )
        for assertion_id in spec.assertion_ids
    }
    core = {
        "schema_version": "xinao.assertion_actual_bundle.v2",
        "protocol_version": "foundation-v4-test",
        "block_id": spec.block_id,
        "request_sha256": "1" * 64,
        "entrypoint": {
            "module_name": "xinao.foundation.test_entrypoint",
            "source_path": str(entrypoint.resolve()),
            "source_sha256": entrypoint_sha256,
            "checker_id": "test-checker",
            "checker_version": "v1",
        },
        "assertion_actuals": actuals,
        "assertion_actual_content_sha256": actual_hashes,
    }
    return (
        replay_runtime._canonical_bytes(
            {**core, "content_sha256": replay_runtime._canonical_sha256(core)}
        ),
        {"path": str(entrypoint.resolve()), "sha256": entrypoint_sha256},
    )


def _valid_phase_lineage() -> dict[str, str]:
    return {
        "seed_output_sha256": "a" * 64,
        "final_input_seed_sha256": "a" * 64,
        "final_output_sha256": "b" * 64,
        "reordered_input_final_sha256": "b" * 64,
        "reordered_output_sha256": "c" * 64,
    }


def test_f4_spec_selects_exact_snapshot_and_verifier_court_hook() -> None:
    spec = replay_runtime._replay_block_spec("F4_research_factory")

    assert spec.capsule_schema_version == "xinao.foundation_v4_relocation_source_capsule.v1"
    assert spec.authority_entrypoint_relative_path == (
        "xinao_discovery/src/xinao/foundation/assertion_verifiers/f4_assertion_actuals.py"
    )
    assert spec.assertion_ids == F4_ASSERTION_IDS
    assert spec.input_names == F4_INPUT_NAMES
    assert spec.artifact_names == F4_ARTIFACT_NAMES
    assert spec.execution_excluded_payload_paths == ("blueprint/blueprint.json",)
    assert spec.actuals_mode == "DIRECT"
    assert spec.phase_order == ("outer",)
    assert spec.include_phase_lineage is False
    assert spec.extension_hook == "snapshot_and_verifier_court"


def test_extension_hook_is_valid_for_f4_only() -> None:
    f4 = replay_runtime._replay_block_spec("F4_research_factory")
    replay_runtime._validate_replay_block_spec(f4)

    for invalid in (None, "unknown_hook"):
        with pytest.raises(FoundationV4ReplayError, match="extension hook"):
            replay_runtime._validate_replay_block_spec(replace(f4, extension_hook=invalid))

    for block_id in (
        "F1_settlement_world",
        "F2_issuer_settlement_cost_space",
        "F3_research_weight",
    ):
        base = replay_runtime._replay_block_spec(block_id)
        assert base.extension_hook is None
        with pytest.raises(FoundationV4ReplayError, match="extension hook"):
            replay_runtime._validate_replay_block_spec(
                replace(base, extension_hook="snapshot_and_verifier_court")
            )


def test_common_f4_replay_delegates_only_to_oci_carrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack_a = tmp_path / "relocated-a"
    pack_b = tmp_path / "relocated-b"
    output = tmp_path / "replay-output"
    nonce = "a" * 64
    calls: list[dict[str, object]] = []
    expected = {"status": "VERIFIED", "execution_carrier": "OCI"}

    def fake_oci_replay(
        *,
        pack_roots: tuple[Path, Path],
        output_root: Path,
        nonce: str,
    ) -> dict[str, str]:
        calls.append(
            {
                "pack_roots": pack_roots,
                "output_root": output_root,
                "nonce": nonce,
            }
        )
        return expected

    monkeypatch.setattr(replay_runtime, "replay_foundation_v4_f4_oci", fake_oci_replay)
    monkeypatch.setattr(
        replay_runtime,
        "_launch_outer_once",
        lambda **kwargs: pytest.fail("F4 must not enter the same-host child launcher"),
    )

    result = replay_runtime.replay_foundation_v4_same_host(
        block_id="F4_research_factory",
        pack_root=pack_a,
        peer_pack_root=pack_b,
        output_root=output,
        runtime_python=tmp_path / "unused-python",
        dependency_roots=(),
        forbidden_roots=(),
        injected_live_root=tmp_path / "unused-live-root",
        sealed_entrypoint_path=tmp_path / "unused-entrypoint.py",
        sealed_entrypoint_manifest_path=tmp_path / "unused-entrypoint-manifest.json",
        nonce=nonce,
        run_count=2,
    )

    assert result is expected
    assert calls == [
        {
            "pack_roots": (pack_a, pack_b),
            "output_root": output,
            "nonce": nonce,
        }
    ]


@pytest.mark.parametrize(
    "block_id",
    (
        "F2_issuer_settlement_cost_space",
        "F3_research_weight",
        "F4_research_factory",
    ),
)
def test_direct_normalized_bundle_forbids_every_extension_field(
    tmp_path: Path,
    block_id: str,
) -> None:
    spec = replay_runtime._replay_block_spec(block_id)
    raw, entrypoint = _raw_bundle_for_spec(tmp_path, spec)
    normalized = replay_runtime._normalize_bundle(
        raw_bundle=raw,
        entrypoint_identity=entrypoint,
        source_request_sha256="0" * 64,
        executed_request_sha256="1" * 64,
        spec=spec,
        extension_fields=None,
    )
    payload = json.loads(normalized)
    assert frozenset(payload) == {
        "schema_version",
        "protocol_version",
        "block_id",
        "source_request_sha256",
        "relocated_request_sha256",
        "request_sha256",
        "entrypoint",
        "assertion_actuals",
        "assertion_actual_content_sha256",
        "content_sha256",
    }

    for invalid in ({}, {"extra": True}, {"phase_lineage": _valid_phase_lineage()}):
        with pytest.raises(FoundationV4ReplayError, match="normalized bundle extension"):
            replay_runtime._normalize_bundle(
                raw_bundle=raw,
                entrypoint_identity=entrypoint,
                source_request_sha256="0" * 64,
                executed_request_sha256="1" * 64,
                spec=spec,
                extension_fields=invalid,
            )


@pytest.mark.parametrize(
    "case",
    ("missing", "extra", "invalid_hash", "seed_link", "final_link", "reserved"),
)
def test_f1_normalized_bundle_requires_exact_phase_lineage(
    tmp_path: Path,
    case: str,
) -> None:
    spec = replay_runtime._replay_block_spec("F1_settlement_world")
    raw, entrypoint = _raw_bundle_for_spec(tmp_path, spec)
    lineage = _valid_phase_lineage()
    extension: dict[str, object] = {"phase_lineage": lineage}
    if case == "missing":
        lineage.pop("reordered_output_sha256")
    elif case == "extra":
        lineage["extra"] = "d" * 64
    elif case == "invalid_hash":
        lineage["seed_output_sha256"] = "A" * 64
    elif case == "seed_link":
        lineage["final_input_seed_sha256"] = "d" * 64
    elif case == "final_link":
        lineage["reordered_input_final_sha256"] = "d" * 64
    else:
        extension["block_id"] = "OVERRIDDEN"

    with pytest.raises(FoundationV4ReplayError, match="normalized bundle extension"):
        replay_runtime._normalize_bundle(
            raw_bundle=raw,
            entrypoint_identity=entrypoint,
            source_request_sha256="0" * 64,
            executed_request_sha256="1" * 64,
            spec=spec,
            extension_fields=extension,
        )


def test_f1_normalized_bundle_accepts_only_bound_phase_lineage(tmp_path: Path) -> None:
    spec = replay_runtime._replay_block_spec("F1_settlement_world")
    raw, entrypoint = _raw_bundle_for_spec(tmp_path, spec)
    lineage = _valid_phase_lineage()

    normalized = replay_runtime._normalize_bundle(
        raw_bundle=raw,
        entrypoint_identity=entrypoint,
        source_request_sha256="0" * 64,
        executed_request_sha256="1" * 64,
        spec=spec,
        extension_fields={"phase_lineage": lineage},
    )

    assert json.loads(normalized)["phase_lineage"] == lineage
