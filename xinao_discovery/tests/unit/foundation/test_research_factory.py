from __future__ import annotations

import copy
import inspect
import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import pytest
from pydantic import ValidationError

from xinao.foundation.research_factory import (
    CAPACITY_TIERS,
    F4_REQUIRED_ARTIFACT_TYPES,
    ResearchErrorBudgetPolicy,
    ResearchWorkItem,
    ResearchWorkItemV3,
    admit_open_method,
    admit_validation_court_request,
    admit_work_item,
    admit_work_item_v3,
    canonical_work_key,
    canonical_work_key_v3,
    compile_research_candidate_snapshot,
    compile_research_portfolio_allocation,
    dedupe_ready_frontier,
    dedupe_ready_frontier_v3,
    deterministic_fan_in,
    evaluate_error_budget,
    finalize_research_candidate_question,
    parse_research_work_item,
    project_allocated_ready_frontier,
    research_factory_artifact_manifest,
    research_factory_schema_payloads,
    research_factory_schema_payloads_v3,
    research_factory_supporting_payloads,
    select_dynamic_capacity,
    source_origin_index,
    source_projection_hash,
    validate_method_registry,
    verify_research_factory_artifacts,
    verify_research_factory_artifacts_v3,
)
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    FROZEN_ROUTE_QUOTE_BASELINE_IDS,
)
from xinao.foundation.validation_court_interface import (
    ValidationCourtRequest,
    ValidationCourtResult,
    verify_validation_court_result,
)


@lru_cache(maxsize=1)
def _selection_manifest() -> object:
    from xinao.foundation.selection_manifest import (
        compile_default_independent_selection_manifest,
    )

    return compile_default_independent_selection_manifest()


def _work(**overrides: object) -> dict[str, object]:
    manifest = _selection_manifest()
    value: dict[str, object] = {
        "schema_version": "xinao.research_work_item.v2",
        "physical_role": "ACTIVE_SETTLEMENT",
        "kind": "semantic-audit",
        "source_ref": "mirror-a",
        "source_dependency_refs": ("catalog",),
        "active_settlement_refs": ("BO0001",),
        "upstream_work_keys": ("4" * 64,),
        "intent_slice": "F1:regular-total",
        "selection_manifest_hash": manifest.content_hash,
        "method_id": "method.external-consensus.v1",
        "method_registration_hash": "1" * 64,
        "method_admission_hash": "9" * 64,
        "world_snapshot_hash": "2" * 64,
        "input_snapshot_hashes": ("3" * 64,),
        "knowledge_cutoff": "2026-07-14T00:00:00Z",
        "budget_ref": "budget:foundation",
        "error_budget_ledger_ref": "ledger:error-budget:foundation",
        "output_schema_ref": "schema:output.v1",
        "handoff_schema_ref": "xinao.agent_handoff.v1",
        "evidence_schema_ref": "xinao.evidence_manifest.v1",
        "correlation_id": "correlation:foundation",
        "expected_information_gain": "resolve one rule ambiguity",
        "evidence_requirements": ("independent-source",),
        "authority_scope": ("read:public",),
        "write_boundary": "READ_ONLY_WORKER",
    }
    value.update(overrides)
    return value


def _work_v3(
    execution_phase: str = "FOUNDATION_CONSTRUCTION",
    **overrides: object,
) -> dict[str, object]:
    value = _work(**overrides)
    value.update(
        {
            "schema_version": "xinao.research_work_item.v3",
            "execution_phase": execution_phase,
        }
    )
    return value


def _admitted_method(
    method_id: str = "method.external-consensus.v1",
) -> tuple[dict[str, object], str, str]:
    from xinao.canonical import canonical_sha256

    digests = {
        "pkg:method@1": "a" * 64,
        "schema:input.v1": "b" * 64,
        "schema:output.v1": "c" * 64,
        "protocol:walk-forward.v1": "d" * 64,
        "contract:fail-closed.v1": "e" * 64,
        "evidence:method-canary.v1": "f" * 64,
    }
    registration = {
        "method_id": method_id,
        "method_kind": "external-consensus",
        "executable_ref": "pkg:method@1",
        "executable_sha256": "a" * 64,
        "input_schema_ref": "schema:input.v1",
        "input_schema_sha256": "b" * 64,
        "output_schema_ref": "schema:output.v1",
        "output_schema_sha256": "c" * 64,
        "verification_protocol_ref": "protocol:walk-forward.v1",
        "verification_protocol_sha256": "d" * 64,
        "failure_contract_ref": "contract:fail-closed.v1",
        "failure_contract_sha256": "e" * 64,
        "source_refs": ("paper:one",),
        "deterministic_seed_policy": "seed is recorded per experiment",
        "canary_evidence_ref": "evidence:method-canary.v1",
        "canary_evidence_sha256": "f" * 64,
    }
    admission = admit_open_method(registration, resolved_content_hashes=digests)
    return (
        admission,
        canonical_sha256(admission["registration"]),
        str(admission["admission_sha256"]),
    )


def _court_request(
    registration_hash: str,
    admission_hash: str,
    **overrides: object,
) -> dict[str, object]:
    from xinao.canonical import canonical_sha256

    policy = ResearchErrorBudgetPolicy()
    target = datetime(2026, 1, 2, tzinfo=UTC)
    value: dict[str, object] = {
        "request_ref": "court-request:synthetic-foundation-canary.v1",
        "work_key": "1" * 64,
        "active_settlement_refs": (sorted(ACTIVE_SETTLEMENT_BASELINE_IDS)[0],),
        "candidate_artifact": {
            "ref": "artifact:synthetic-candidate.v1",
            "sha256": "2" * 64,
        },
        "method_id": "method.external-consensus.v1",
        "method_registration_sha256": registration_hash,
        "method_admission_sha256": admission_hash,
        "protocol_artifact": {
            "ref": "protocol:walk-forward.v1",
            "sha256": "d" * 64,
        },
        "split_manifest": {
            "ref": "split:synthetic-fixed.v1",
            "sha256": "3" * 64,
        },
        "evaluation_partition_ref": "partition:synthetic-validation.v1",
        "evaluation_partition_sha256": "4" * 64,
        "feature_lookback_rows": 28,
        "decision_horizon_rows": 1,
        "purge_embargo_rows": 28,
        "feature_observations": (
            {
                "feature_ref": "feature:lagged-count.v1",
                "feature_timestamp": target - timedelta(hours=1),
                "target_open_time": target,
            },
            {
                "feature_ref": "feature:lagged-count.v1",
                "feature_timestamp": target + timedelta(hours=23),
                "target_open_time": target + timedelta(days=1),
            },
        ),
        "walk_forward_folds": (
            {
                "fold_id": "fold-01",
                "train_start_index": 0,
                "train_end_index": 49,
                "test_start_index": 78,
                "test_end_index": 99,
            },
            {
                "fold_id": "fold-02",
                "train_start_index": 0,
                "train_end_index": 99,
                "test_start_index": 128,
                "test_end_index": 149,
            },
        ),
        "negative_control_kinds": (
            "CIRCULAR_SHIFT",
            "LABEL_PERMUTATION",
            "NULL_CONSTANT",
        ),
        "error_budget_policy_ref": policy.policy_ref,
        "error_budget_policy_sha256": canonical_sha256(policy.model_dump(mode="json")),
        "hypotheses_in_family": 0,
        "confirmation_queries_used": 0,
        "input_snapshot_hashes": ("5" * 64,),
        "result_schema": {
            "ref": "schema:output.v1",
            "sha256": "c" * 64,
        },
        "evidence_schema": {
            "ref": "schema:generic-court-evidence.v1",
            "sha256": "6" * 64,
        },
    }
    value.update(overrides)
    return value


def _court_result(
    request: ValidationCourtRequest,
    admission_sha256: str,
    **overrides: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "result_ref": "court-result:synthetic-foundation-canary.v1",
        "request_sha256": request.content_hash,
        "admission_sha256": admission_sha256,
        "work_key": request.work_key,
        "active_settlement_refs": request.active_settlement_refs,
        "verdict": "NO_ACTION",
        "negative_controls": tuple(
            {
                "control_kind": kind,
                "evidence": {
                    "ref": f"evidence:negative:{kind.lower()}",
                    "sha256": character * 64,
                },
                "passed": True,
            }
            for kind, character in zip(
                request.negative_control_kinds,
                ("7", "8", "9"),
                strict=True,
            )
        ),
        "result_artifact": {
            "ref": "artifact:synthetic-court-result.v1",
            "sha256": "a" * 64,
        },
        "evidence": (
            {
                "ref": "evidence:synthetic-court-run.v1",
                "sha256": "b" * 64,
            },
        ),
    }
    value.update(overrides)
    return value


def _producer_evidence(token: str) -> dict[str, str]:
    return {
        "artifact_ref": f"D:/evidence/{token}/producer.json",
        "artifact_hash": token * 64,
        "temporal_workflow_id": f"producer-workflow-{token}",
        "temporal_run_id": f"producer-run-{token}",
        "lane_id": f"producer-lane-{token}",
        "provider_id": "grok_acpx_headless",
        "model": "grok-4.5",
    }


def _critique_evidence(token: str) -> dict[str, str]:
    return {
        "critique_artifact_ref": f"D:/evidence/{token}/critique.json",
        "critique_artifact_hash": token * 64,
        "temporal_workflow_id": f"critique-workflow-{token}",
        "temporal_run_id": f"critique-run-{token}",
        "lane_id": f"critique-lane-{token}",
        "provider_id": "grok_acpx_headless",
        "model": "grok-4.5",
    }


def _verification_evidence(token: str) -> dict[str, str]:
    return {
        "verification_artifact_ref": f"D:/evidence/{token}/verification.json",
        "verification_artifact_hash": token * 64,
        "temporal_workflow_id": f"verification-workflow-{token}",
        "temporal_run_id": f"verification-run-{token}",
        "lane_id": f"verification-lane-{token}",
        "provider_id": "grok_acpx_headless",
        "model": "grok-4.5",
    }


def test_work_key_is_order_independent_and_source_mirrors_collapse() -> None:
    left = _work(source_ref="mirror-a")
    right = _work(source_ref="mirror-b")
    origins = {"mirror-a": "origin-1", "mirror-b": "origin-1"}
    assert canonical_work_key(left, source_origin_by_ref=origins) == canonical_work_key(
        right, source_origin_by_ref=origins
    )


def test_v3_work_identity_is_phase_qualified_and_v2_remains_strict() -> None:
    construction = ResearchWorkItemV3.model_validate(_work_v3())
    autonomous = ResearchWorkItemV3.model_validate(_work_v3("AUTONOMOUS_RESEARCH"))
    assert canonical_work_key_v3(construction) != canonical_work_key_v3(autonomous)
    with pytest.raises(ValidationError):
        canonical_work_key(construction.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        ResearchWorkItemV3.model_validate(_work())
    with pytest.raises(ValidationError):
        ResearchWorkItemV3.model_validate(_work_v3("INVALID"))


def test_work_item_parser_preserves_versions_without_silent_upgrade() -> None:
    assert set(ResearchWorkItemV3.model_fields) == {
        *ResearchWorkItem.model_fields,
        "execution_phase",
    }
    parsed_v2 = parse_research_work_item(_work())
    parsed_v3 = parse_research_work_item(json.loads(json.dumps(_work_v3())))
    assert type(parsed_v2) is ResearchWorkItem
    assert type(parsed_v3) is ResearchWorkItemV3
    assert parsed_v3.execution_phase == "FOUNDATION_CONSTRUCTION"
    with pytest.raises(ValidationError):
        parse_research_work_item({**_work(), "execution_phase": "FOUNDATION_CONSTRUCTION"})
    missing_phase = _work_v3()
    missing_phase.pop("execution_phase")
    with pytest.raises(ValidationError):
        parse_research_work_item(missing_phase)
    with pytest.raises(ValueError, match="unsupported research work item schema"):
        parse_research_work_item({**_work(), "schema_version": "unknown"})
    missing_schema = _work()
    missing_schema.pop("schema_version")
    with pytest.raises(ValueError, match="unsupported research work item schema"):
        parse_research_work_item(missing_schema)


def test_v3_dedup_is_permutation_invariant_across_phases() -> None:
    items = [_work_v3(intent_slice="z"), _work_v3(intent_slice="a")]
    expected = dedupe_ready_frontier_v3(
        items,
        expected_phase="FOUNDATION_CONSTRUCTION",
        closed_work_keys=("4" * 64,),
    )
    assert dedupe_ready_frontier_v3(
        list(reversed(items)),
        expected_phase="FOUNDATION_CONSTRUCTION",
        closed_work_keys=("4" * 64,),
    ) == expected
    assert len(expected["ready_work_keys"]) == 2
    with pytest.raises(ValueError, match="expected execution phase"):
        dedupe_ready_frontier_v3(
            [_work_v3(), _work_v3("AUTONOMOUS_RESEARCH")],
            expected_phase="FOUNDATION_CONSTRUCTION",
            closed_work_keys=("4" * 64,),
        )
    construction_empty = dedupe_ready_frontier_v3(
        [], expected_phase="FOUNDATION_CONSTRUCTION"
    )
    autonomous_empty = dedupe_ready_frontier_v3(
        [], expected_phase="AUTONOMOUS_RESEARCH"
    )
    assert construction_empty["execution_phase"] == "FOUNDATION_CONSTRUCTION"
    assert autonomous_empty["execution_phase"] == "AUTONOMOUS_RESEARCH"
    assert construction_empty["content_sha256"] != autonomous_empty["content_sha256"]


def test_v3_admission_retains_schema_and_execution_phase() -> None:
    method, registration_hash, admission_hash = _admitted_method()
    result = admit_work_item_v3(
        _work_v3(
            method_registration_hash=registration_hash,
            method_admission_hash=admission_hash,
        ),
        selection_manifest=_selection_manifest(),
        method_registry={"method.external-consensus.v1": method},
    )
    assert result["admitted"] is True
    assert result["work_item_schema_version"] == "xinao.research_work_item.v3"
    assert result["execution_phase"] == "FOUNDATION_CONSTRUCTION"


def test_frozen_origin_mirror_cannot_create_a_work_key() -> None:
    with pytest.raises(ValueError, match="frozen quote origin"):
        canonical_work_key(
            _work(source_ref="mirror-of-frozen"),
            source_origin_by_ref={"mirror-of-frozen": "BO0013"},
        )


def test_ready_frontier_is_dependency_aware_and_deduplicates_mirrors() -> None:
    result = dedupe_ready_frontier(
        [
            _work(source_ref="mirror-b", upstream_work_keys=()),
            _work(source_ref="mirror-a", upstream_work_keys=()),
        ],
        source_origin_by_ref={"mirror-a": "origin-1", "mirror-b": "origin-1"},
    )
    assert len(result["ready"]) == 1
    assert len(result["duplicates"]) == 1
    assert result["duplicates"][0]["reason"] == "DUPLICATE_OR_SOURCE_MIRROR"


def test_ready_frontier_defers_unsatisfied_dependencies() -> None:
    result = dedupe_ready_frontier([_work()], closed_work_keys=[])
    assert not result["ready"]
    assert result["deferred"][0]["missing"] == ["4" * 64]


def test_ready_frontier_uses_upstream_work_keys_not_source_refs() -> None:
    item = _work(source_dependency_refs=("catalog",), upstream_work_keys=("4" * 64,))
    blocked = dedupe_ready_frontier([item], closed_work_keys=[])
    ready = dedupe_ready_frontier([item], closed_work_keys=["4" * 64])
    assert not blocked["ready"]
    assert len(ready["ready"]) == 1


def test_portfolio_allocation_compiles_weighted_canonical_frontier() -> None:
    from xinao.canonical import canonical_sha256
    from xinao.foundation.research_weight import verify_versioned_object

    def versioned(object_type: str, **payload: object) -> dict[str, object]:
        core = {"object_type": object_type, **payload}
        digest = canonical_sha256(core)
        return {
            **core,
            "version_id": f"{object_type}@{digest[:16]}",
            "content_sha256": digest,
        }

    graph = versioned(
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
    )
    surface = versioned(
        "ActiveResearchSurfaceVersion",
        rows=[
            {
                "family_id": "family-a",
                "active_component_ids": ["BO0001"],
                "research_resource_share": "0.5",
                "surface_state": "ACTIVE",
            },
            {
                "family_id": "family-b",
                "active_component_ids": ["BO0002"],
                "research_resource_share": "0.4",
                "surface_state": "WATCH",
            },
        ],
    )
    policy = versioned(
        "ResearchPortfolioPolicyVersion",
        active_surface_ref=surface["content_sha256"],
        exploitation_share="0.9",
        exploration_share="0.1",
    )
    admission, registration_hash, admission_hash = _admitted_method()
    method_registry = {"method.external-consensus.v1": admission}
    candidates = [
        {
            "work_item": _work(
                source_ref="source-0",
                source_dependency_refs=(),
                active_settlement_refs=("BO0001",),
                upstream_work_keys=(),
                intent_slice="family-a:first",
                method_registration_hash=registration_hash,
                method_admission_hash=admission_hash,
            ),
            "lane_templates": {"PRODUCER": {"lane_id": "producer-0"}},
        },
        {
            "work_item": _work(
                source_ref="source-1",
                source_dependency_refs=(),
                active_settlement_refs=("BO0002",),
                upstream_work_keys=(),
                intent_slice="family-b:first",
                method_registration_hash=registration_hash,
                method_admission_hash=admission_hash,
            ),
            "lane_templates": {"PRODUCER": {"lane_id": "producer-1"}},
        },
        {
            "work_item": _work(
                source_ref="source-2",
                source_dependency_refs=(),
                active_settlement_refs=("BO0001",),
                upstream_work_keys=(),
                intent_slice="family-a:second",
                method_registration_hash=registration_hash,
                method_admission_hash=admission_hash,
            ),
            "lane_templates": {"PRODUCER": {"lane_id": "producer-2"}},
        },
    ]
    question = finalize_research_candidate_question(
        question_id="question:weighted-frontier",
        candidate_generator_id="generator:test-bound-universe.v1",
        candidate_generator_source_sha256="a" * 64,
        active_surface_ref=str(surface["content_sha256"]),
        selection_manifest_ref=_selection_manifest().content_hash,
        method_registry_sha256=canonical_sha256(method_registry),
        source_dependency_graph_ref=str(graph["content_sha256"]),
        candidate_specs=[
            {
                "candidate_id": f"candidate-{index}",
                "work_item": candidate["work_item"],
                "lane_templates_sha256": canonical_sha256(candidate["lane_templates"]),
                "portfolio_lane": "EXPLOITATION",
            }
            for index, candidate in enumerate(candidates)
        ],
    )
    snapshot = compile_research_candidate_snapshot(
        list(reversed(candidates)),
        research_question=question,
        active_surface=surface,
        selection_manifest=_selection_manifest().model_dump(mode="json"),
        method_registry=method_registry,
        source_dependency_graph=graph,
    )
    allocation = compile_research_portfolio_allocation(
        snapshot,
        active_surface=surface,
        portfolio_policy=policy,
        source_dependency_graph=graph,
    )
    assert verify_versioned_object(allocation)
    assert allocation["candidate_count"] == 3
    assert allocation["candidate_snapshot_ref"] == snapshot["content_sha256"]
    assert [row["bucket_id"] for row in allocation["allocations"]] == [
        "EXPLOITATION:family-a",
        "EXPLOITATION:family-b",
        "EXPLOITATION:family-a",
    ]
    projection = project_allocated_ready_frontier(
        allocation,
        candidate_snapshot=snapshot,
    )
    assert projection["ready_work_keys"] == allocation["ready_work_keys"]
    assert [row["rank"] for row in projection["ready"]] == [1, 2, 3]
    filtered = project_allocated_ready_frontier(
        allocation,
        candidate_snapshot=snapshot,
        closed_work_keys=[allocation["ready_work_keys"][0]],
    )
    assert filtered["ready_work_keys"] == allocation["ready_work_keys"][1:]
    assert [row["rank"] for row in filtered["ready"]] == [2, 3]
    assert filtered["duplicates"][0]["rank"] == 1
    drifted_allocation = copy.deepcopy(allocation)
    drifted_allocation["allocations"] = list(reversed(drifted_allocation["allocations"]))
    drifted_core = {
        key: value
        for key, value in drifted_allocation.items()
        if key not in {"version_id", "content_sha256"}
    }
    drifted_allocation["content_sha256"] = canonical_sha256(drifted_core)
    drifted_allocation["version_id"] = (
        f"ResearchPortfolioAllocation@{drifted_allocation['content_sha256'][:16]}"
    )
    with pytest.raises(ValueError, match="rank or candidate binding drifted"):
        project_allocated_ready_frontier(
            drifted_allocation,
            candidate_snapshot=snapshot,
        )
    with pytest.raises(ValueError, match="coverage is incomplete"):
        compile_research_candidate_snapshot(
            candidates[:-1],
            research_question=question,
            active_surface=surface,
            selection_manifest=_selection_manifest().model_dump(mode="json"),
            method_registry=method_registry,
            source_dependency_graph=graph,
        )


def test_source_dependency_graph_is_hash_bound_transitive_and_cycle_safe() -> None:
    from xinao.foundation.research_weight_inputs import compile_current_research_weight_foundation

    graph = compile_current_research_weight_foundation()["objects"]["SourceDependencyGraphVersion"]
    origins, graph_hash = source_origin_index(graph)
    assert graph_hash == graph["content_sha256"]
    assert origins["local-prior-draft"] == origins["local-service-graph"]

    drifted = copy.deepcopy(graph)
    drifted["edges"].append(
        {
            "from": "local-service-graph",
            "to": "local-prior-draft",
            "relation": "CO_DERIVED_PROJECT_MATERIAL",
        }
    )
    core = {
        key: value for key, value in drifted.items() if key not in {"version_id", "content_sha256"}
    }
    from xinao.canonical import canonical_sha256

    drifted["content_sha256"] = canonical_sha256(core)
    drifted["version_id"] = f"SourceDependencyGraphVersion@{drifted['content_sha256'][:16]}"
    with pytest.raises(ValueError, match="cycle"):
        source_origin_index(drifted)


def test_source_lineage_edge_does_not_merge_independent_origin_clusters() -> None:
    from xinao.canonical import canonical_sha256

    core = {
        "object_type": "SourceDependencyGraphVersion",
        "sources": [
            {"source_id": "origin-a-copy-1", "origin_cluster_id": "origin-a"},
            {"source_id": "origin-a-copy-2", "origin_cluster_id": "origin-a"},
            {"source_id": "derived-b", "origin_cluster_id": "origin-b"},
        ],
        "origin_clusters": [
            {
                "origin_cluster_id": "origin-a",
                "member_source_ids": ["origin-a-copy-1", "origin-a-copy-2"],
            },
            {"origin_cluster_id": "origin-b", "member_source_ids": ["derived-b"]},
        ],
        "edges": [
            {
                "from": "origin-a-copy-1",
                "to": "derived-b",
                "relation": "DERIVED_FROM",
            }
        ],
        "summary": {"independent_origin_cluster_count": 2, "source_count": 3},
    }
    digest = canonical_sha256(core)
    graph = {
        **core,
        "version_id": f"SourceDependencyGraphVersion@{digest[:16]}",
        "content_sha256": digest,
    }
    origins, _ = source_origin_index(graph)
    assert origins["origin-a-copy-1"] == origins["origin-a-copy-2"] == "origin-a"
    assert origins["derived-b"] == "origin-b"


def test_unrelated_source_graph_growth_does_not_change_work_key() -> None:
    from xinao.canonical import canonical_sha256
    from xinao.foundation.research_weight_inputs import (
        compile_current_research_weight_foundation,
    )

    graph = compile_current_research_weight_foundation()["objects"]["SourceDependencyGraphVersion"]
    expanded = copy.deepcopy(graph)
    expanded["sources"].append(
        {"source_id": "unrelated-new-source", "origin_cluster_id": "unrelated-origin"}
    )
    expanded["origin_clusters"].append(
        {
            "origin_cluster_id": "unrelated-origin",
            "member_source_ids": ["unrelated-new-source"],
        }
    )
    expanded["summary"] = {
        **expanded["summary"],
        "independent_origin_cluster_count": (
            expanded["summary"]["independent_origin_cluster_count"] + 1
        ),
        "source_count": expanded["summary"]["source_count"] + 1,
    }
    core = {
        key: value for key, value in expanded.items() if key not in {"version_id", "content_sha256"}
    }
    expanded["content_sha256"] = canonical_sha256(core)
    expanded["version_id"] = f"SourceDependencyGraphVersion@{expanded['content_sha256'][:16]}"
    refs = ("local-prior-draft",)
    base_origins, _ = source_origin_index(graph)
    expanded_origins, _ = source_origin_index(expanded)
    work = _work(
        source_ref="local-prior-draft",
        source_dependency_refs=(),
        upstream_work_keys=(),
    )
    assert canonical_work_key(
        work,
        source_origin_by_ref=base_origins,
        source_projection_hash=source_projection_hash(graph, refs),
    ) == canonical_work_key(
        work,
        source_origin_by_ref=expanded_origins,
        source_projection_hash=source_projection_hash(expanded, refs),
    )


def test_dynamic_capacity_uses_live_slots_and_reacts_to_partial_failure() -> None:
    initial = select_dynamic_capacity(
        {
            "host_state": "available",
            "ready_count": 8,
            "available_slots": 8,
            "previous_width": 1,
            "succeeded": 0,
            "failed": 0,
        }
    )
    assert initial["capacity_tier"] == 1
    assert initial["dispatch_width"] == 1
    assert initial["reason"] == "INITIAL_VERIFIED_CAPACITY"
    assert len(initial["content_sha256"]) == 64

    ramped = select_dynamic_capacity(
        {
            "host_state": "available",
            "ready_count": 8,
            "available_slots": 8,
            "previous_width": 1,
            "succeeded": 1,
            "failed": 0,
        }
    )
    assert ramped["capacity_tier"] == 2
    assert ramped["dispatch_width"] == 2

    retry = select_dynamic_capacity(
        {
            "host_state": "available",
            "ready_count": 1,
            "available_slots": 8,
            "previous_width": 8,
            "succeeded": 7,
            "failed": 1,
            "partial": True,
        }
    )
    assert retry["capacity_tier"] == 4
    assert retry["dispatch_width"] == 1
    assert retry["reason"] == "DOWNSHIFT_AFTER_PARTIAL_OR_FAILURE"


@pytest.mark.parametrize("slots", [1, 2, 4, 8, 16, 32, 99])
def test_dynamic_capacity_never_exceeds_ceiling(slots: int) -> None:
    result = select_dynamic_capacity(
        {
            "host_state": "available",
            "ready_count": 100,
            "available_slots": slots,
            "previous_width": 32,
            "succeeded": 32,
        }
    )
    assert result["capacity_tier"] in CAPACITY_TIERS
    assert result["dispatch_width"] <= 32


def test_absent_host_produces_wait_capacity_not_fake_serial_fallback() -> None:
    result = select_dynamic_capacity(
        {
            "host_state": "absent",
            "ready_count": 4,
            "available_slots": 4,
            "previous_width": 4,
        }
    )
    assert result["dispatch_width"] == 0
    assert result["reason"] == "HOST_NOT_READY"


def test_fan_in_is_deterministic_and_never_votes() -> None:
    lanes = [
        {
            "work_key": "b",
            "producer_id": "producer-b",
            "status": "PARTIAL",
            "claim_refs": ["claim-2"],
            **_producer_evidence("b"),
        },
        {
            "work_key": "a",
            "producer_id": "producer-a",
            "status": "VERIFIED",
            "claim_refs": ["claim-1"],
            **_producer_evidence("a"),
        },
    ]
    critiques = [
        {
            "work_key": "a",
            "critic_id": "critic-a",
            "target_artifact_hash": "a" * 64,
            "verdict": "APPROVED",
            **_critique_evidence("c"),
        },
        {
            "work_key": "b",
            "critic_id": "critic-b",
            "target_artifact_hash": "b" * 64,
            "verdict": "APPROVED",
            **_critique_evidence("d"),
        },
    ]
    verifications = [
        {
            "work_key": "a",
            "verifier_id": "verifier-a",
            "target_artifact_hash": "a" * 64,
            "target_critique_hash": "c" * 64,
            "verdict": "VERIFIED",
            **_verification_evidence("e"),
        },
        {
            "work_key": "b",
            "verifier_id": "verifier-b",
            "target_artifact_hash": "b" * 64,
            "target_critique_hash": "d" * 64,
            "verdict": "PARTIAL",
            **_verification_evidence("f"),
        },
    ]
    left = deterministic_fan_in(
        lanes,
        critiques=critiques,
        verifications=verifications,
        expected_work_keys=["a", "b"],
    )
    right = deterministic_fan_in(
        list(reversed(lanes)),
        critiques=list(reversed(critiques)),
        verifications=list(reversed(verifications)),
        expected_work_keys=["b", "a"],
    )
    assert left == right
    assert left["accepted_work_keys"] == ["a"]
    assert left["unresolved_work_keys"] == ["b"]
    assert left["majority_vote_used"] is False
    assert left["completion_status"] == "PARTIAL"


def test_fan_in_rejects_role_reuse() -> None:
    with pytest.raises(ValueError, match="roles must be disjoint"):
        deterministic_fan_in(
            [
                {
                    "work_key": "a",
                    "producer_id": "critic",
                    "status": "VERIFIED",
                    **_producer_evidence("a"),
                }
            ],
            critiques=[
                {
                    "work_key": "a",
                    "critic_id": "critic",
                    "target_artifact_hash": "a" * 64,
                    "verdict": "APPROVED",
                    **_critique_evidence("c"),
                }
            ],
            verifications=[
                {
                    "work_key": "a",
                    "verifier_id": "verifier",
                    "target_artifact_hash": "a" * 64,
                    "target_critique_hash": "c" * 64,
                    "verdict": "VERIFIED",
                    **_verification_evidence("e"),
                }
            ],
            expected_work_keys=["a"],
        )


def test_fan_in_rejects_unbound_or_missing_independent_evidence() -> None:
    lane = {
        "work_key": "a",
        "producer_id": "producer",
        "status": "VERIFIED",
        **_producer_evidence("a"),
    }
    with pytest.raises(ValueError, match="requires one critique"):
        deterministic_fan_in(
            [lane],
            critiques=[],
            verifications=[],
            expected_work_keys=["a"],
        )
    with pytest.raises(ValueError, match="not bound"):
        deterministic_fan_in(
            [lane],
            critiques=[
                {
                    "work_key": "a",
                    "critic_id": "critic",
                    "target_artifact_hash": "b" * 64,
                    "verdict": "APPROVED",
                    **_critique_evidence("c"),
                }
            ],
            verifications=[
                {
                    "work_key": "a",
                    "verifier_id": "verifier",
                    "target_artifact_hash": "a" * 64,
                    "target_critique_hash": "c" * 64,
                    "verdict": "VERIFIED",
                    **_verification_evidence("e"),
                }
            ],
            expected_work_keys=["a"],
        )


def test_open_method_admission_is_typed_but_not_a_whitelist() -> None:
    digests = {
        "pkg:novel-method@1": "a" * 64,
        "schema:input.v1": "b" * 64,
        "schema:output.v1": "c" * 64,
        "protocol:walk-forward.v1": "d" * 64,
        "contract:fail-closed.v1": "e" * 64,
        "evidence:novel-method-canary.v1": "f" * 64,
    }
    method = {
        "method_id": "novel.method.that.did.not_exist.v1",
        "method_kind": "new-scientific-method",
        "executable_ref": "pkg:novel-method@1",
        "executable_sha256": "a" * 64,
        "input_schema_ref": "schema:input.v1",
        "input_schema_sha256": "b" * 64,
        "output_schema_ref": "schema:output.v1",
        "output_schema_sha256": "c" * 64,
        "verification_protocol_ref": "protocol:walk-forward.v1",
        "verification_protocol_sha256": "d" * 64,
        "failure_contract_ref": "contract:fail-closed.v1",
        "failure_contract_sha256": "e" * 64,
        "source_refs": ("paper:one",),
        "deterministic_seed_policy": "seed is recorded per experiment",
        "canary_evidence_ref": "evidence:novel-method-canary.v1",
        "canary_evidence_sha256": "f" * 64,
    }
    result = admit_open_method(method, resolved_content_hashes=digests)
    assert result["admitted"] is True
    assert result["method_whitelist_used"] is False

    invalid = copy.deepcopy(method)
    invalid.pop("verification_protocol_ref")
    with pytest.raises(ValidationError):
        admit_open_method(invalid, resolved_content_hashes=digests)
    with pytest.raises(ValueError, match="hash drifted"):
        admit_open_method(
            method,
            resolved_content_hashes={**digests, "pkg:novel-method@1": "0" * 64},
        )

    collapsed = copy.deepcopy(method)
    for field in (
        "input_schema_ref",
        "output_schema_ref",
        "verification_protocol_ref",
        "failure_contract_ref",
        "canary_evidence_ref",
    ):
        collapsed[field] = collapsed["executable_ref"]
    with pytest.raises(ValidationError, match="must be distinct"):
        admit_open_method(collapsed, resolved_content_hashes=digests)


def test_work_item_requires_the_admitted_method_registration_hash() -> None:
    admission, registration_hash, admission_hash = _admitted_method()
    work = _work(
        method_registration_hash=registration_hash,
        method_admission_hash=admission_hash,
    )
    result = admit_work_item(
        work,
        selection_manifest=_selection_manifest(),
        method_registry={"method.external-consensus.v1": admission},
    )
    assert result["admitted"] is True
    with pytest.raises(ValueError, match="registry is empty"):
        admit_work_item(
            work,
            selection_manifest=_selection_manifest(),
            method_registry={},
        )

    with pytest.raises((TypeError, ValueError, ValidationError)):
        validate_method_registry(
            {
                "method.external-consensus.v1": {
                    "method_id": "method.external-consensus.v1",
                    "status": "VERIFIED",
                }
            }
        )

    with pytest.raises(ValueError, match="output schema"):
        admit_work_item(
            _work(
                output_schema_ref="schema:unbound-output.v1",
                method_registration_hash=registration_hash,
                method_admission_hash=admission_hash,
            ),
            selection_manifest=_selection_manifest(),
            method_registry={"method.external-consensus.v1": admission},
        )


def test_frozen_agent_route_quote_is_never_admitted_as_research_work() -> None:
    admission, registration_hash, admission_hash = _admitted_method()
    frozen = _work(
        source_ref="BO0013",
        method_registration_hash=registration_hash,
        method_admission_hash=admission_hash,
    )
    with pytest.raises(ValueError, match="frozen quote identity"):
        admit_work_item(
            frozen,
            selection_manifest=_selection_manifest(),
            method_registry={"method.external-consensus.v1": admission},
        )

    relabeled_active_ref = _work(
        active_settlement_refs=("BO0013",),
        method_registration_hash=registration_hash,
        method_admission_hash=admission_hash,
    )
    with pytest.raises(ValueError, match="canonical ACTIVE identities"):
        admit_work_item(
            relabeled_active_ref,
            selection_manifest=_selection_manifest(),
            method_registry={"method.external-consensus.v1": admission},
        )


def test_work_item_binds_selection_manifest_and_method_admission() -> None:
    admission, registration_hash, admission_hash = _admitted_method()
    registry = {"method.external-consensus.v1": admission}
    with pytest.raises(ValueError, match="selection manifest hash drifted"):
        admit_work_item(
            _work(
                selection_manifest_hash="0" * 64,
                method_registration_hash=registration_hash,
                method_admission_hash=admission_hash,
            ),
            selection_manifest=_selection_manifest(),
            method_registry=registry,
        )
    with pytest.raises(ValueError, match="method admission hash drifted"):
        admit_work_item(
            _work(
                method_registration_hash=registration_hash,
                method_admission_hash="0" * 64,
            ),
            selection_manifest=_selection_manifest(),
            method_registry=registry,
        )


def test_error_budget_requires_negative_controls_and_debits_only_on_admission() -> None:
    policy = ResearchErrorBudgetPolicy()
    admitted = evaluate_error_budget(
        policy,
        hypotheses_in_family=3,
        confirmation_queries_used=1,
        negative_control_kinds=("CIRCULAR_SHIFT", "LABEL_PERMUTATION", "NULL_CONSTANT"),
    )
    assert admitted["admitted"] is True
    assert admitted["next_confirmation_queries_used"] == 2

    missing_control = evaluate_error_budget(
        policy,
        hypotheses_in_family=3,
        confirmation_queries_used=1,
        negative_control_kinds=("CIRCULAR_SHIFT",),
    )
    assert missing_control["admitted"] is False
    assert missing_control["next_confirmation_queries_used"] == 1
    assert "NEGATIVE_CONTROLS_INCOMPLETE" in missing_control["reasons"]

    exhausted = evaluate_error_budget(
        policy,
        hypotheses_in_family=20,
        confirmation_queries_used=3,
        negative_control_kinds=("CIRCULAR_SHIFT", "LABEL_PERMUTATION", "NULL_CONSTANT"),
    )
    assert exhausted["admitted"] is False
    assert set(exhausted["reasons"]) == {
        "HYPOTHESIS_FAMILY_BUDGET_EXHAUSTED",
        "CONFIRMATION_QUERY_BUDGET_EXHAUSTED",
    }


def test_validation_court_interface_is_generic_and_hash_bound() -> None:
    artifact = research_factory_schema_payloads()["ValidationCourtInterfaceVersion"]
    interface = artifact["interface"]
    assert artifact["schema_version"] == "xinao.validation_court_interface.v2"
    assert interface["interface_kind"] == "GENERIC_TYPED_COURT_NO_ACTIVE_DOMAIN_INSTANCE"
    assert set(interface["schemas"]) == {
        "CourtArtifactBinding",
        "CourtFeatureObservation",
        "CourtNegativeControlEvidence",
        "CourtWalkForwardFold",
        "ValidationCourtAdmission",
        "ValidationCourtRequest",
        "ValidationCourtResult",
    }
    assert set(interface["callable_source_sha256"]) == {
        "admit_validation_court_request",
        "verify_validation_court_result",
    }
    assert all(len(value) == 64 for value in interface["model_source_sha256"].values())
    assert all(len(value) == 64 for value in interface["callable_source_sha256"].values())
    assert "active_protocol" not in interface
    assert "active_windows" not in interface
    rendered = json.dumps(interface, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "candidate.constant-01-panel-b.v0",
        "validation-protocol.special-number.v1",
        "dataset-split.verified-913.v1",
        "CONFIRMATION_VAULT",
        "FINAL_HOLDOUT",
    ):
        assert forbidden not in rendered


def test_validation_court_request_accepts_generic_fixed_temporal_contract() -> None:
    method, registration_hash, admission_hash = _admitted_method()
    request = ValidationCourtRequest.model_validate(
        _court_request(registration_hash, admission_hash)
    )
    admission = admit_validation_court_request(
        request,
        method_registry={"method.external-consensus.v1": method},
        error_budget_policy=ResearchErrorBudgetPolicy(),
    )
    assert admission.admitted is True
    assert admission.request_sha256 == request.content_hash
    result = ValidationCourtResult.model_validate(_court_result(request, admission.content_hash))
    verification = verify_validation_court_result(request, admission, result)
    assert verification["verified"] is True
    assert verification["verdict"] == "NO_ACTION"
    assert verification["negative_control_count"] == 3

    featureless = ValidationCourtRequest.model_validate(
        _court_request(
            registration_hash,
            admission_hash,
            request_ref="court-request:featureless-constant-special-canary.v1",
            candidate_artifact={
                "ref": "artifact:featureless-constant-special-canary.v1",
                "sha256": "e" * 64,
            },
            feature_observations=(),
        )
    )
    featureless_admission = admit_validation_court_request(
        featureless,
        method_registry={"method.external-consensus.v1": method},
        error_budget_policy=ResearchErrorBudgetPolicy(),
    )
    assert featureless.feature_observations == ()
    assert featureless_admission.request_sha256 == featureless.content_hash


def test_validation_court_request_rejects_future_features_and_unpurged_folds() -> None:
    _, registration_hash, admission_hash = _admitted_method()
    valid = _court_request(registration_hash, admission_hash)

    leaked = copy.deepcopy(valid)
    leaked_feature = leaked["feature_observations"][0]
    leaked_feature["feature_timestamp"] = leaked_feature["target_open_time"]
    with pytest.raises(ValidationError, match="future leakage"):
        ValidationCourtRequest.model_validate(leaked)

    short_horizon = copy.deepcopy(valid)
    short_horizon["purge_embargo_rows"] = 27
    with pytest.raises(ValidationError, match="maximum information horizon"):
        ValidationCourtRequest.model_validate(short_horizon)

    unpurged = copy.deepcopy(valid)
    unpurged["walk_forward_folds"][0]["test_start_index"] = 77
    with pytest.raises(ValidationError, match="preserve purge/embargo"):
        ValidationCourtRequest.model_validate(unpurged)


def test_validation_court_admission_and_result_reject_binding_or_control_drift() -> None:
    method, registration_hash, admission_hash = _admitted_method()
    registry = {"method.external-consensus.v1": method}
    policy = ResearchErrorBudgetPolicy()
    request = ValidationCourtRequest.model_validate(
        _court_request(registration_hash, admission_hash)
    )
    admission = admit_validation_court_request(
        request,
        method_registry=registry,
        error_budget_policy=policy,
    )

    frozen_ref = sorted(FROZEN_ROUTE_QUOTE_BASELINE_IDS)[0]
    with pytest.raises(ValidationError, match="frozen route quote"):
        ValidationCourtRequest.model_validate(
            _court_request(
                registration_hash,
                admission_hash,
                active_settlement_refs=(frozen_ref,),
            )
        )

    wrong_protocol = ValidationCourtRequest.model_validate(
        _court_request(
            registration_hash,
            admission_hash,
            protocol_artifact={
                "ref": "protocol:walk-forward.v1",
                "sha256": "0" * 64,
            },
        )
    )
    with pytest.raises(ValueError, match="admitted method protocol"):
        admit_validation_court_request(
            wrong_protocol,
            method_registry=registry,
            error_budget_policy=policy,
        )

    missing_controls = ValidationCourtRequest.model_validate(
        _court_request(
            registration_hash,
            admission_hash,
            negative_control_kinds=("CIRCULAR_SHIFT",),
        )
    )
    with pytest.raises(ValueError, match="exceeds its error budget"):
        admit_validation_court_request(
            missing_controls,
            method_registry=registry,
            error_budget_policy=policy,
        )

    unbound_result = ValidationCourtResult.model_validate(
        _court_result(request, admission.content_hash, request_sha256="0" * 64)
    )
    with pytest.raises(ValueError, match="not bound to request and admission"):
        verify_validation_court_result(request, admission, unbound_result)

    other_active_ref = sorted(ACTIVE_SETTLEMENT_BASELINE_IDS)[1]
    wrong_active_result = ValidationCourtResult.model_validate(
        _court_result(
            request,
            admission.content_hash,
            active_settlement_refs=(other_active_ref,),
        )
    )
    with pytest.raises(ValueError, match="not bound to request and admission"):
        verify_validation_court_result(request, admission, wrong_active_result)

    failed_controls_payload = _court_result(request, admission.content_hash)
    failed_controls_payload["negative_controls"][0]["passed"] = False
    failed_controls = ValidationCourtResult.model_validate(failed_controls_payload)
    with pytest.raises(ValueError, match="incomplete or failed"):
        verify_validation_court_result(request, admission, failed_controls)


def test_factory_native_schemas_are_hash_bound() -> None:
    from xinao.foundation.research_weight import verify_versioned_object

    payloads = research_factory_schema_payloads()
    assert (
        payloads["ResearchWorkItemSchemaVersion"]["content_sha256"]
        == "4243e6b02dc09c9a3eef27ae1e275b31afd2f931478812bf50ca9af1faff0475"
    )
    assert (
        payloads["DedupPolicyVersion"]["content_sha256"]
        == "39b6d1f31088bd8a6b59df993853a02414c47d5991494fcf1931bb4811db059d"
    )
    assert (
        research_factory_artifact_manifest(payloads)["content_sha256"]
        == "7e0c171913f42103e1c95d94d5d6984fb3fbbb9e412228e62d7b02ee4f5a9baf"
    )
    assert tuple(payloads) == F4_REQUIRED_ARTIFACT_TYPES
    assert payloads["DeterministicFanInPolicyVersion"]["policy"]["stages"] == [
        "PRODUCER",
        "CRITIQUE",
        "VERIFIER",
    ]
    assert all(verify_versioned_object(value) for value in payloads.values())
    assert all(len(value["content_sha256"]) == 64 for value in payloads.values())

    supporting = research_factory_supporting_payloads()
    assert set(supporting) == {
        "OpenMethodRegistrationSchemaVersion",
        "ResearchErrorBudgetPolicySchemaVersion",
    }
    assert all(verify_versioned_object(value) for value in supporting.values())

    tampered = copy.deepcopy(payloads["DynamicCapacityPolicyVersion"])
    tampered["policy"]["maximum_width"] = 64
    assert verify_versioned_object(tampered) is False

    assert all(
        payloads[name]["version_id"].startswith(f"{name}@") for name in F4_REQUIRED_ARTIFACT_TYPES
    )
    work_item_artifact = payloads["ResearchWorkItemSchemaVersion"]
    implementation_hashes = work_item_artifact["implementation_source_sha256"]
    assert {
        "admit_open_method",
        "admit_work_item",
        "canonical_work_key",
        "open_method_registration",
        "validate_method_admission",
        "validate_method_registry",
    } <= set(implementation_hashes)
    assert all(len(value) == 64 for value in implementation_hashes.values())


def test_factory_v3_artifacts_are_explicit_and_not_caller_redefinable() -> None:
    v2 = research_factory_schema_payloads()
    v3 = research_factory_schema_payloads_v3()
    assert tuple(v3) == F4_REQUIRED_ARTIFACT_TYPES
    unchanged = set(F4_REQUIRED_ARTIFACT_TYPES) - {
        "ResearchWorkItemSchemaVersion",
        "DedupPolicyVersion",
    }
    assert all(v3[name] == v2[name] for name in unchanged)
    work_item = v3["ResearchWorkItemSchemaVersion"]
    dedup = v3["DedupPolicyVersion"]
    assert work_item["schema_version"] == "xinao.research_work_item_schema.v3"
    assert work_item["base_v2_artifact_content_sha256"] == v2[
        "ResearchWorkItemSchemaVersion"
    ]["content_sha256"]
    assert "execution_phase" in work_item["schema"]["required"]
    assert dedup["schema_version"] == "xinao.research_dedup_policy.v3"
    assert dedup["base_v2_artifact_content_sha256"] == v2["DedupPolicyVersion"][
        "content_sha256"
    ]
    assert "execution_phase" in dedup["policy"]["identity_fields"]
    assert "canonical_work_key_v3" in dedup["policy"]["implementation_sha256"]
    assert "canonical_work_key" not in dedup["policy"]["implementation_sha256"]
    assert "current_artifacts" not in inspect.signature(
        verify_research_factory_artifacts_v3
    ).parameters
    manifest = research_factory_artifact_manifest(v3)
    assert verify_research_factory_artifacts_v3(v3, pinned_manifest=manifest)["profile"] == "V3"
    with pytest.raises(ValueError, match="required inventory"):
        research_factory_artifact_manifest({})
    with pytest.raises(ValueError, match="STALE_OR_NOT_CURRENT_GENERATOR"):
        verify_research_factory_artifacts(v3)
    with pytest.raises(ValueError, match="STALE_OR_NOT_CURRENT_GENERATOR"):
        verify_research_factory_artifacts_v3(v2)

    tampered = copy.deepcopy(v3)
    dedup = tampered["DedupPolicyVersion"]
    dedup["policy"]["identity_fields"].remove("execution_phase")
    from xinao.canonical import canonical_sha256

    dedup["policy_sha256"] = canonical_sha256(dedup["policy"])
    core = {
        key: value for key, value in dedup.items() if key not in {"version_id", "content_sha256"}
    }
    dedup["content_sha256"] = canonical_sha256(core)
    dedup["version_id"] = f"DedupPolicyVersion@{dedup['content_sha256'][:16]}"
    with pytest.raises(ValueError, match="STALE_OR_NOT_CURRENT_GENERATOR"):
        verify_research_factory_artifacts_v3(tampered)


def test_factory_artifacts_reject_self_consistent_stale_rehash_and_pin_drift() -> None:
    from xinao.canonical import canonical_sha256

    payloads = research_factory_schema_payloads()
    manifest = research_factory_artifact_manifest(payloads)
    result = verify_research_factory_artifacts(payloads, pinned_manifest=manifest)
    assert result["ok"] is True
    assert set(result) == {
        "schema_version",
        "ok",
        "required_artifact_types",
        "current_generator_match",
        "manifest",
        "manifest_content_sha256",
    }
    assert result["manifest_content_sha256"] == manifest["content_sha256"]
    verify_research_factory_artifacts(
        payloads,
        expected_manifest_sha256=manifest["content_sha256"],
    )
    with pytest.raises(ValueError, match="external pin"):
        verify_research_factory_artifacts(
            payloads,
            expected_manifest_sha256="0" * 64,
        )

    stale = copy.deepcopy(payloads)
    dynamic = stale["DynamicCapacityPolicyVersion"]
    dynamic["policy"]["maximum_width"] = 64
    dynamic["policy_sha256"] = canonical_sha256(dynamic["policy"])
    core = {
        key: value for key, value in dynamic.items() if key not in {"version_id", "content_sha256"}
    }
    dynamic["content_sha256"] = canonical_sha256(core)
    dynamic["version_id"] = f"DynamicCapacityPolicyVersion@{dynamic['content_sha256'][:16]}"
    with pytest.raises(ValueError, match="STALE_OR_NOT_CURRENT_GENERATOR"):
        verify_research_factory_artifacts(stale)

    stale_pin = copy.deepcopy(manifest)
    stale_pin["artifact_content_sha256"]["DynamicCapacityPolicyVersion"] = "0" * 64
    pin_core = {
        key: value
        for key, value in stale_pin.items()
        if key not in {"version_id", "content_sha256"}
    }
    stale_pin["content_sha256"] = canonical_sha256(pin_core)
    stale_pin["version_id"] = (
        f"ResearchFactoryArtifactManifestVersion@{stale_pin['content_sha256'][:16]}"
    )
    with pytest.raises(ValueError, match="pinned F4 artifact manifest"):
        verify_research_factory_artifacts(payloads, pinned_manifest=stale_pin)


def test_fan_in_stage_models_reject_invalid_hash_and_status() -> None:
    lane = {
        "work_key": "a",
        "producer_id": "producer",
        "status": "VERIFIED",
        **_producer_evidence("a"),
    }
    lane["artifact_hash"] = "not-a-hash"
    with pytest.raises(ValidationError):
        deterministic_fan_in([lane], critiques=[], verifications=[], expected_work_keys=["a"])

    lane = {
        "work_key": "a",
        "producer_id": "producer",
        "status": "MAYBE",
        **_producer_evidence("a"),
    }
    with pytest.raises(ValidationError):
        deterministic_fan_in([lane], critiques=[], verifications=[], expected_work_keys=["a"])
