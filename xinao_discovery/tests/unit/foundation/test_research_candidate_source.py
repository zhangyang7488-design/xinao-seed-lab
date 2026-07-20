from __future__ import annotations

import copy
import inspect
from collections import defaultdict
from functools import lru_cache

import pytest
from pydantic import ValidationError

from xinao.canonical import canonical_sha256
from xinao.foundation.research_candidate_source import (
    CANDIDATE_SNAPSHOT_SCHEMA_VERSION_V3,
    EXPECTED_FAMILY_IDS,
    compile_f4_canary_candidate_snapshot,
    compile_f4_canary_candidate_snapshot_v3,
    compile_f4_canary_candidate_source,
    compile_f4_canary_candidate_source_v3,
)
from xinao.foundation.research_factory import (
    ResearchWorkItem,
    ResearchWorkItemV3,
    admit_open_method,
    admit_work_item,
    canonical_work_key,
    canonical_work_key_v3,
    deterministic_fan_in,
    source_origin_index,
    source_projection_hash,
)
from xinao.foundation.research_weight import verify_versioned_object
from xinao.foundation.selection_manifest import (
    IndependentExpectedSelectionDomainManifestVersion,
    compile_default_independent_selection_manifest,
)


@lru_cache(maxsize=1)
def _manifest() -> IndependentExpectedSelectionDomainManifestVersion:
    return compile_default_independent_selection_manifest()


def _versioned(object_type: str, **payload: object) -> dict[str, object]:
    core = {
        "object_type": object_type,
        "schema_version": "xinao.research-weight-foundation-object.v1",
        "semantic_role": "RESEARCH_RESOURCE_SHARE",
        **payload,
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"{object_type}@{digest[:16]}",
        "content_sha256": digest,
    }


def _rehash_versioned(value: dict[str, object]) -> None:
    core = {
        key: item for key, item in value.items() if key not in {"version_id", "content_sha256"}
    }
    value["content_sha256"] = canonical_sha256(core)
    value["version_id"] = f"{value['object_type']}@{value['content_sha256'][:16]}"


def _surface() -> dict[str, object]:
    by_family: defaultdict[str, set[str]] = defaultdict(set)
    for spec in _manifest().specifications:
        by_family[spec.family_id].update(spec.component_baseline_ids)
    rows = [
        {
            "family_id": family_id,
            "active_component_count": len(by_family[family_id]),
            "active_component_ids": sorted(by_family[family_id]),
            "research_resource_share": "0.076923076923",
            "surface_state": "ACTIVE",
        }
        for family_id in sorted(by_family)
    ]
    return _versioned(
        "ActiveResearchSurfaceVersion",
        weight_baseline_ref="1" * 64,
        active_foundation_ref="2" * 64,
        rows=rows,
        summary={"by_surface_state": {"ACTIVE": 13}, "family_count": 13},
    )


def _graph() -> dict[str, object]:
    return _versioned(
        "SourceDependencyGraphVersion",
        sources=[
            {"source_id": f"source-{index}", "origin_cluster_id": f"origin-{index}"}
            for index in range(3)
        ],
        origin_clusters=[
            {
                "origin_cluster_id": f"origin-{index}",
                "member_source_ids": [f"source-{index}"],
            }
            for index in range(3)
        ],
        edges=[],
        summary={"source_count": 3},
    )


def _method_registry() -> tuple[dict[str, object], str]:
    method_id = "method.f4-canary.v1"
    resolved = {
        "pkg:method@1": "a" * 64,
        "schema:input.v1": "b" * 64,
        "schema:output.v1": "c" * 64,
        "protocol:verify.v1": "d" * 64,
        "contract:failure.v1": "e" * 64,
        "evidence:canary.v1": "f" * 64,
    }
    admission = admit_open_method(
        {
            "method_id": method_id,
            "method_kind": "evidence-bound-canary",
            "executable_ref": "pkg:method@1",
            "executable_sha256": "a" * 64,
            "input_schema_ref": "schema:input.v1",
            "input_schema_sha256": "b" * 64,
            "output_schema_ref": "schema:output.v1",
            "output_schema_sha256": "c" * 64,
            "verification_protocol_ref": "protocol:verify.v1",
            "verification_protocol_sha256": "d" * 64,
            "failure_contract_ref": "contract:failure.v1",
            "failure_contract_sha256": "e" * 64,
            "source_refs": ("source-0",),
            "deterministic_seed_policy": "work key binds the deterministic seed",
            "canary_evidence_ref": "evidence:canary.v1",
            "canary_evidence_sha256": "f" * 64,
        },
        resolved_content_hashes=resolved,
    )
    return {"registrations": {method_id: admission}}, method_id


def _compile() -> dict[str, dict[str, object]]:
    registry, method_id = _method_registry()
    return compile_f4_canary_candidate_source(
        active_research_surface=_surface(),
        selection_manifest=_manifest(),
        method_registry=registry,
        method_id=method_id,
        source_dependency_graph=_graph(),
        world_snapshot_hash="9" * 64,
        knowledge_cutoff="2026-07-14T00:00:00.000Z",
    )


def _compile_v3() -> dict[str, dict[str, object]]:
    registry, method_id = _method_registry()
    return compile_f4_canary_candidate_source_v3(
        active_research_surface=_surface(),
        selection_manifest=_manifest(),
        method_registry=registry,
        method_id=method_id,
        source_dependency_graph=_graph(),
        world_snapshot_hash="9" * 64,
        knowledge_cutoff="2026-07-14T00:00:00.000Z",
    )


def test_api_has_no_caller_candidate_or_ready_frontier_input() -> None:
    parameters = set(inspect.signature(compile_f4_canary_candidate_source).parameters)
    assert parameters == {
        "active_research_surface",
        "selection_manifest",
        "method_registry",
        "method_id",
        "source_dependency_graph",
        "world_snapshot_hash",
        "knowledge_cutoff",
    }
    assert parameters.isdisjoint({"candidate_specs", "candidate_entries", "ready_frontier"})


def test_compiler_derives_exactly_one_canonical_candidate_per_family() -> None:
    result = _compile()
    assert result == _compile()
    question = result["research_question"]
    snapshot = result["candidate_source_snapshot"]
    assert verify_versioned_object(question)
    assert verify_versioned_object(snapshot)
    assert question["content_sha256"] == (
        "768d4a484a69446eb9739c04ee8c2f4d1697462453ae5959e4bbc5fef2e81e88"
    )
    assert snapshot["content_sha256"] == (
        "05ade9d3c9362fa3c8d4c8c0392f05d5c70281c0da9dfb466f4087c65053b70c"
    )
    assert snapshot["research_question_ref"] == question["content_sha256"]
    assert question["expected_family_ids"] == list(EXPECTED_FAMILY_IDS)
    assert snapshot["coverage"] == {
        "expected_family_count": 13,
        "observed_family_count": 13,
        "expected_family_ids": list(EXPECTED_FAMILY_IDS),
        "observed_family_ids": list(EXPECTED_FAMILY_IDS),
        "complete": True,
    }
    entries = snapshot["candidate_entries"]
    assert snapshot["candidate_count"] == len(entries) == 13
    assert all("portfolio_lane" not in entry for entry in entries)
    assert "exploration" not in str(result).casefold()


def test_source_compiles_to_exact_allocation_ready_snapshot() -> None:
    source = _compile()
    registry, method_id = _method_registry()
    snapshot = compile_f4_canary_candidate_snapshot(
        research_question=source["research_question"],
        candidate_source_snapshot=source["candidate_source_snapshot"],
        active_research_surface=_surface(),
        selection_manifest=_manifest(),
        method_registry=registry,
        method_id=method_id,
        source_dependency_graph=_graph(),
    )
    assert verify_versioned_object(snapshot)
    assert snapshot["candidate_count"] == 13
    assert snapshot["coverage"]["exact"] is True
    assert snapshot["coverage"]["omitted_source_ids"] == []
    assert [row["family_id"] for row in snapshot["candidate_rows"]] == list(EXPECTED_FAMILY_IDS)
    assert all(row["portfolio_lane"] == "EXPLOITATION" for row in snapshot["candidate_rows"])

    shortened = copy.deepcopy(source["candidate_source_snapshot"])
    shortened["candidate_entries"] = shortened["candidate_entries"][:-1]
    shortened["candidate_count"] = 12
    shortened["coverage"] = {
        **shortened["coverage"],
        "observed_family_count": 12,
        "observed_family_ids": shortened["coverage"]["observed_family_ids"][:-1],
        "complete": False,
    }
    core = {
        key: value
        for key, value in shortened.items()
        if key not in {"version_id", "content_sha256"}
    }
    shortened["content_sha256"] = canonical_sha256(core)
    shortened["version_id"] = f"ResearchCandidateSourceSnapshot@{shortened['content_sha256'][:16]}"
    with pytest.raises(ValueError, match="exact 13-family coverage"):
        compile_f4_canary_candidate_snapshot(
            research_question=source["research_question"],
            candidate_source_snapshot=shortened,
            active_research_surface=_surface(),
            selection_manifest=_manifest(),
            method_registry=registry,
            method_id=method_id,
            source_dependency_graph=_graph(),
        )


def test_v3_source_phase_qualifies_the_exact_v2_canary_universe() -> None:
    base = _compile()
    upgraded = _compile_v3()
    assert upgraded == _compile_v3()
    base_entries = base["candidate_source_snapshot"]["candidate_entries"]
    upgraded_entries = upgraded["candidate_source_snapshot"]["candidate_entries"]
    assert len(base_entries) == len(upgraded_entries) == 13

    unchanged_entry_fields = {
        "candidate_id",
        "family_id",
        "selected_component_id",
        "source_ref",
        "source_origin_cluster_id",
        "source_projection_sha256",
        "lane_templates_sha256",
        "lane_templates",
    }
    for base_entry, upgraded_entry in zip(base_entries, upgraded_entries, strict=True):
        assert {key: base_entry[key] for key in unchanged_entry_fields} == {
            key: upgraded_entry[key] for key in unchanged_entry_fields
        }
        base_work = dict(base_entry["work_item"])
        upgraded_work = dict(upgraded_entry["work_item"])
        assert base_work.pop("schema_version") == "xinao.research_work_item.v2"
        assert upgraded_work.pop("schema_version") == "xinao.research_work_item.v3"
        assert upgraded_work.pop("execution_phase") == "FOUNDATION_CONSTRUCTION"
        assert upgraded_work == base_work
        assert ResearchWorkItemV3.model_validate(upgraded_entry["work_item"])
        assert upgraded_entry["work_key"] != base_entry["work_key"]
        assert upgraded_entry["work_item_sha256"] != base_entry["work_item_sha256"]
        assert upgraded_entry["entry_sha256"] != base_entry["entry_sha256"]

    assert upgraded["research_question"]["execution_phase"] == "FOUNDATION_CONSTRUCTION"
    assert (
        upgraded["candidate_source_snapshot"]["execution_phase"]
        == "FOUNDATION_CONSTRUCTION"
    )
    assert upgraded["candidate_source_snapshot"]["coverage"] == base[
        "candidate_source_snapshot"
    ]["coverage"]
    assert upgraded["candidate_source_snapshot"]["input_hashes"] == base[
        "candidate_source_snapshot"
    ]["input_hashes"]


def test_v3_source_compiles_to_phase_qualified_allocation_snapshot() -> None:
    source = _compile_v3()
    registry, method_id = _method_registry()
    snapshot = compile_f4_canary_candidate_snapshot_v3(
        research_question=source["research_question"],
        candidate_source_snapshot=source["candidate_source_snapshot"],
        active_research_surface=_surface(),
        selection_manifest=_manifest(),
        method_registry=registry,
        method_id=method_id,
        source_dependency_graph=_graph(),
    )
    assert verify_versioned_object(snapshot)
    assert snapshot["content_sha256"] == (
        "40cfd187d51b739a4ed0e12720bc5fec8bfef7ced8a3646929f593d19ddd20b8"
    )
    assert snapshot["schema_version"] == CANDIDATE_SNAPSHOT_SCHEMA_VERSION_V3
    assert snapshot["execution_phase"] == "FOUNDATION_CONSTRUCTION"
    assert snapshot["candidate_count"] == 13
    assert all(
        row["entry"]["work_item"]["execution_phase"] == "FOUNDATION_CONSTRUCTION"
        for row in snapshot["candidate_rows"]
    )


def test_v2_snapshot_compiler_rejects_v3_work_inside_a_rehashed_v1_source() -> None:
    legacy = _compile()
    v3 = _compile_v3()
    source_snapshot = copy.deepcopy(legacy["candidate_source_snapshot"])
    source_snapshot["candidate_entries"][0] = copy.deepcopy(
        v3["candidate_source_snapshot"]["candidate_entries"][0]
    )
    _rehash_versioned(source_snapshot)
    registry, method_id = _method_registry()
    with pytest.raises(ValidationError):
        compile_f4_canary_candidate_snapshot(
            research_question=legacy["research_question"],
            candidate_source_snapshot=source_snapshot,
            active_research_surface=_surface(),
            selection_manifest=_manifest(),
            method_registry=registry,
            method_id=method_id,
            source_dependency_graph=_graph(),
        )


def test_v3_snapshot_rejects_self_consistent_generator_spoof() -> None:
    source = _compile_v3()
    question = copy.deepcopy(source["research_question"])
    snapshot = copy.deepcopy(source["candidate_source_snapshot"])
    question["candidate_generator_source_sha256"] = "0" * 64
    question["base_candidate_generator_source_sha256"] = "1" * 64
    _rehash_versioned(question)
    snapshot["research_question_ref"] = question["content_sha256"]
    snapshot["candidate_generator_source_sha256"] = "0" * 64
    snapshot["base_candidate_generator_source_sha256"] = "1" * 64
    _rehash_versioned(snapshot)
    registry, method_id = _method_registry()
    with pytest.raises(ValueError, match="current exact generator"):
        compile_f4_canary_candidate_snapshot_v3(
            research_question=question,
            candidate_source_snapshot=snapshot,
            active_research_surface=_surface(),
            selection_manifest=_manifest(),
            method_registry=registry,
            method_id=method_id,
            source_dependency_graph=_graph(),
        )


@pytest.mark.parametrize("replacement", ["AUTONOMOUS_RESEARCH", None])
def test_v3_snapshot_rejects_self_consistent_nonconstruction_work(
    replacement: str | None,
) -> None:
    source = _compile_v3()
    snapshot = copy.deepcopy(source["candidate_source_snapshot"])
    entry = snapshot["candidate_entries"][0]
    if replacement is None:
        entry["work_item"] = _compile()["candidate_source_snapshot"]["candidate_entries"][0][
            "work_item"
        ]
    else:
        entry["work_item"]["execution_phase"] = replacement
    work = (
        ResearchWorkItem.model_validate(entry["work_item"])
        if replacement is None
        else ResearchWorkItemV3.model_validate(entry["work_item"])
    )
    origins, _ = source_origin_index(_graph())
    key_compiler = canonical_work_key if replacement is None else canonical_work_key_v3
    entry["work_key"] = key_compiler(
        work,
        source_origin_by_ref=origins,
        source_projection_hash=entry["source_projection_sha256"],
    )
    entry["work_item_sha256"] = canonical_sha256(entry["work_item"])
    entry_core = dict(entry)
    entry_core.pop("entry_sha256")
    entry["entry_sha256"] = canonical_sha256(entry_core)
    snapshot_core = {
        key: value for key, value in snapshot.items() if key not in {"version_id", "content_sha256"}
    }
    snapshot["content_sha256"] = canonical_sha256(snapshot_core)
    snapshot["version_id"] = f"ResearchCandidateSourceSnapshot@{snapshot['content_sha256'][:16]}"
    registry, method_id = _method_registry()
    with pytest.raises(ValueError, match="non-construction work"):
        compile_f4_canary_candidate_snapshot_v3(
            research_question=source["research_question"],
            candidate_source_snapshot=snapshot,
            active_research_surface=_surface(),
            selection_manifest=_manifest(),
            method_registry=registry,
            method_id=method_id,
            source_dependency_graph=_graph(),
        )


def test_entries_bind_minimum_component_rotated_source_and_read_only_lanes() -> None:
    result = _compile()
    entries = result["candidate_source_snapshot"]["candidate_entries"]
    surface = _surface()
    components = {row["family_id"]: row["active_component_ids"] for row in surface["rows"]}
    graph = _graph()
    origins, _ = source_origin_index(graph)
    registry, method_id = _method_registry()
    expected_sources = [f"source-{index % 3}" for index in range(13)]
    assert [entry["source_ref"] for entry in entries] == expected_sources
    for entry in entries:
        family_id = entry["family_id"]
        assert entry["selected_component_id"] == min(components[family_id])
        work = ResearchWorkItem.model_validate(entry["work_item"])
        admit_work_item(
            work,
            selection_manifest=_manifest(),
            method_registry=registry["registrations"],
        )
        projection = source_projection_hash(graph, (work.source_ref,))
        assert entry["work_key"] == canonical_work_key(
            work,
            source_origin_by_ref=origins,
            source_projection_hash=projection,
        )
        assert work.method_id == method_id
        assert work.active_settlement_refs == (entry["selected_component_id"],)
        assert set(entry["lane_templates"]) == {"PRODUCER", "CRITIQUE", "VERIFIER"}
        assert len({lane["lane_id"] for lane in entry["lane_templates"].values()}) == 3
        for lane in entry["lane_templates"].values():
            assert lane["write"] is False
            assert lane["allowed_tools"] == ["read_file"]
        core = dict(entry)
        digest = core.pop("entry_sha256")
        assert canonical_sha256(core) == digest


def test_generated_producer_status_is_accepted_by_deterministic_fan_in() -> None:
    entry = _compile()["candidate_source_snapshot"]["candidate_entries"][0]
    work_key = entry["work_key"]
    lanes = entry["lane_templates"]
    assert "status=VERIFIED" in lanes["PRODUCER"]["prompt"]
    assert "status=SUPPORTED" not in lanes["PRODUCER"]["prompt"]

    producer_hash = "a" * 64
    critique_hash = "b" * 64
    common_runtime = {
        "temporal_workflow_id": "wf-fake",
        "temporal_run_id": "run-fake",
        "provider_id": "grok_acpx_headless",
        "model": "grok-composer-2.5-fast",
    }
    producer = {
        "work_key": work_key,
        "producer_id": lanes["PRODUCER"]["lane_id"],
        "status": "VERIFIED",
        "claim_refs": ["claim:f4-live"],
        "artifact_ref": "D:/fake/producer.json",
        "artifact_hash": producer_hash,
        "lane_id": lanes["PRODUCER"]["lane_id"],
        **common_runtime,
    }
    critique = {
        "work_key": work_key,
        "critic_id": lanes["CRITIQUE"]["lane_id"],
        "target_artifact_hash": producer_hash,
        "critique_artifact_ref": "D:/fake/critique.json",
        "critique_artifact_hash": critique_hash,
        "verdict": "APPROVED",
        "finding_refs": [],
        "lane_id": lanes["CRITIQUE"]["lane_id"],
        **common_runtime,
    }
    verification = {
        "work_key": work_key,
        "verifier_id": lanes["VERIFIER"]["lane_id"],
        "target_artifact_hash": producer_hash,
        "target_critique_hash": critique_hash,
        "verification_artifact_ref": "D:/fake/verification.json",
        "verification_artifact_hash": "c" * 64,
        "verdict": "VERIFIED",
        "evidence_refs": ["evidence:f4-live"],
        "lane_id": lanes["VERIFIER"]["lane_id"],
        **common_runtime,
    }

    fanin = deterministic_fan_in(
        [producer],
        critiques=[critique],
        verifications=[verification],
        expected_work_keys=[work_key],
    )
    assert fanin["completion_status"] == "VERIFIED"
    assert fanin["accepted_work_keys"] == [work_key]


def test_candidate_snapshot_rejects_worker_claiming_codex_single_writer() -> None:
    source = _compile()
    snapshot = copy.deepcopy(source["candidate_source_snapshot"])
    entry = snapshot["candidate_entries"][0]
    entry["work_item"]["write_boundary"] = "CODEX_SINGLE_WRITER"
    entry["work_item_sha256"] = canonical_sha256(entry["work_item"])
    entry_core = dict(entry)
    entry_core.pop("entry_sha256")
    entry["entry_sha256"] = canonical_sha256(entry_core)
    snapshot_core = {
        key: value for key, value in snapshot.items() if key not in {"version_id", "content_sha256"}
    }
    snapshot["content_sha256"] = canonical_sha256(snapshot_core)
    snapshot["version_id"] = f"ResearchCandidateSourceSnapshot@{snapshot['content_sha256'][:16]}"
    registry, method_id = _method_registry()

    with pytest.raises(ValueError, match="work item binding drifted"):
        compile_f4_canary_candidate_snapshot(
            research_question=source["research_question"],
            candidate_source_snapshot=snapshot,
            active_research_surface=_surface(),
            selection_manifest=_manifest(),
            method_registry=registry,
            method_id=method_id,
            source_dependency_graph=_graph(),
        )


def test_compiler_rejects_surface_partition_drift_even_when_rehashed() -> None:
    surface = copy.deepcopy(_surface())
    surface["rows"][0]["active_component_ids"][0] = surface["rows"][1]["active_component_ids"][0]
    surface["rows"][0]["active_component_ids"].sort()
    core = dict(surface)
    core.pop("content_sha256")
    core.pop("version_id")
    digest = canonical_sha256(core)
    surface["content_sha256"] = digest
    surface["version_id"] = f"ActiveResearchSurfaceVersion@{digest[:16]}"
    registry, method_id = _method_registry()
    with pytest.raises(ValueError, match="canonical manifest partition"):
        compile_f4_canary_candidate_source(
            active_research_surface=surface,
            selection_manifest=_manifest(),
            method_registry=registry,
            method_id=method_id,
            source_dependency_graph=_graph(),
            world_snapshot_hash="9" * 64,
            knowledge_cutoff="2026-07-14T00:00:00.000Z",
        )


def test_compiler_rejects_unadmitted_method_and_unbound_world_or_cutoff() -> None:
    registry, method_id = _method_registry()
    inputs = {
        "active_research_surface": _surface(),
        "selection_manifest": _manifest(),
        "method_registry": registry,
        "method_id": method_id,
        "source_dependency_graph": _graph(),
        "world_snapshot_hash": "9" * 64,
        "knowledge_cutoff": "2026-07-14T00:00:00.000Z",
    }
    with pytest.raises(ValueError, match="method_id"):
        compile_f4_canary_candidate_source(**{**inputs, "method_id": "missing"})
    with pytest.raises(ValueError, match="world_snapshot_hash"):
        compile_f4_canary_candidate_source(**{**inputs, "world_snapshot_hash": "not-a-hash"})
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        compile_f4_canary_candidate_source(**{**inputs, "knowledge_cutoff": "2026-07-14"})
