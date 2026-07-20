"""Deterministic F4 research-factory contracts and reconciliation primitives.

The durable clock is Temporal.  This module deliberately contains only pure,
versionable policy: stable work identity, dependency-aware deduplication,
capacity selection, typed open-method admission, and evidence-based fan-in.
It never starts a process, schedules a timer, or creates another control plane.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import (
    canonical_dumps,
    canonical_sha256,
    format_utc,
    is_uuid7,
    require_uuid7,
    to_json_value,
)
from xinao.foundation.research_weight import verify_versioned_object
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    FROZEN_ROUTE_QUOTE_BASELINE_IDS,
    IndependentExpectedSelectionDomainManifestVersion,
    active_catalog_projection_hash,
    classify_catalog_physical_roles,
)
from xinao.foundation.validation_court_interface import (
    COURT_ADMISSION_INVARIANTS,
    CourtArtifactBinding,
    CourtFeatureObservation,
    CourtNegativeControlEvidence,
    CourtWalkForwardFold,
    ValidationCourtAdmission,
    ValidationCourtRequest,
    ValidationCourtResult,
    verify_validation_court_result,
)

CAPACITY_TIERS = (1, 2, 4, 8, 16, 32)
FACTORY_POLICY_VERSION = "xinao.research_factory_policy.v1"
F4_REQUIRED_ARTIFACT_TYPES = (
    "TypedHandoffSchemaVersion",
    "EvidenceSchemaVersion",
    "ValidationCourtInterfaceVersion",
    "ResearchWorkItemSchemaVersion",
    "DynamicCapacityPolicyVersion",
    "DedupPolicyVersion",
    "DeterministicFanInPolicyVersion",
)


def _callable_source_hash(value: object) -> str:
    """Bind a policy artifact to the executable implementation it describes."""

    return canonical_sha256(
        {
            "module": getattr(value, "__module__", ""),
            "qualname": getattr(value, "__qualname__", ""),
            "source": inspect.getsource(value),
        }
    )


def _finalize_factory_artifact(
    object_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Create one content-addressed F4 contract artifact."""

    core = {
        "object_type": object_type,
        "artifact_schema_version": "xinao.research_factory_artifact.v1",
        **dict(payload),
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"{object_type}@{digest[:16]}",
        "content_sha256": digest,
    }


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class ResearchWorkItem(BaseModel):
    """One typed, replayable unit at a research ready frontier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.research_work_item.v2"] = "xinao.research_work_item.v2"
    physical_role: Literal["ACTIVE_SETTLEMENT"]
    kind: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_dependency_refs: tuple[str, ...] = ()
    active_settlement_refs: tuple[str, ...] = Field(min_length=1)
    upstream_work_keys: tuple[str, ...] = ()
    intent_slice: str = Field(min_length=1)
    selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_id: str = Field(min_length=1)
    method_registration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_admission_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_snapshot_hashes: tuple[str, ...] = Field(min_length=1)
    knowledge_cutoff: str = Field(min_length=1)
    budget_ref: str = Field(min_length=1)
    error_budget_ledger_ref: str = Field(min_length=1)
    output_schema_ref: str = Field(min_length=1)
    handoff_schema_ref: str = Field(min_length=1)
    evidence_schema_ref: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    expected_information_gain: str = Field(min_length=1)
    evidence_requirements: tuple[str, ...] = Field(min_length=1)
    authority_scope: tuple[str, ...] = Field(min_length=1)
    write_boundary: Literal["READ_ONLY_WORKER", "CODEX_SINGLE_WRITER"]

    @model_validator(mode="after")
    def normalize_identity_sets(self) -> Self:
        if tuple(sorted(set(self.source_dependency_refs))) != self.source_dependency_refs:
            raise ValueError("source_dependency_refs must be unique and sorted")
        if tuple(sorted(set(self.active_settlement_refs))) != self.active_settlement_refs:
            raise ValueError("active_settlement_refs must be unique and sorted")
        if not set(self.active_settlement_refs) <= ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError("active_settlement_refs must contain canonical ACTIVE identities")
        source_identities = {self.source_ref, *self.source_dependency_refs}
        if source_identities & FROZEN_ROUTE_QUOTE_BASELINE_IDS:
            raise ValueError("catalog-only frozen quote identity cannot create research work")
        if tuple(sorted(set(self.upstream_work_keys))) != self.upstream_work_keys:
            raise ValueError("upstream_work_keys must be unique and sorted")
        if not all(len(value) == 64 for value in self.upstream_work_keys):
            raise ValueError("upstream_work_keys must contain canonical SHA-256 keys")
        if tuple(sorted(set(self.evidence_requirements))) != self.evidence_requirements:
            raise ValueError("evidence_requirements must be unique and sorted")
        if tuple(sorted(set(self.authority_scope))) != self.authority_scope:
            raise ValueError("authority_scope must be unique and sorted")
        if tuple(sorted(set(self.input_snapshot_hashes))) != self.input_snapshot_hashes:
            raise ValueError("input_snapshot_hashes must be unique and sorted")
        return self


class ResearchWorkItemV3(BaseModel):
    """Phase-qualified work identity for construction versus formal research."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.research_work_item.v3"] = "xinao.research_work_item.v3"
    execution_phase: Literal["FOUNDATION_CONSTRUCTION", "AUTONOMOUS_RESEARCH"]
    physical_role: Literal["ACTIVE_SETTLEMENT"]
    kind: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_dependency_refs: tuple[str, ...] = ()
    active_settlement_refs: tuple[str, ...] = Field(min_length=1)
    upstream_work_keys: tuple[str, ...] = ()
    intent_slice: str = Field(min_length=1)
    selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_id: str = Field(min_length=1)
    method_registration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_admission_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_snapshot_hashes: tuple[str, ...] = Field(min_length=1)
    knowledge_cutoff: str = Field(min_length=1)
    budget_ref: str = Field(min_length=1)
    error_budget_ledger_ref: str = Field(min_length=1)
    output_schema_ref: str = Field(min_length=1)
    handoff_schema_ref: str = Field(min_length=1)
    evidence_schema_ref: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    expected_information_gain: str = Field(min_length=1)
    evidence_requirements: tuple[str, ...] = Field(min_length=1)
    authority_scope: tuple[str, ...] = Field(min_length=1)
    write_boundary: Literal["READ_ONLY_WORKER", "CODEX_SINGLE_WRITER"]

    @model_validator(mode="after")
    def normalize_identity_sets(self) -> Self:
        if tuple(sorted(set(self.source_dependency_refs))) != self.source_dependency_refs:
            raise ValueError("source_dependency_refs must be unique and sorted")
        if tuple(sorted(set(self.active_settlement_refs))) != self.active_settlement_refs:
            raise ValueError("active_settlement_refs must be unique and sorted")
        if not set(self.active_settlement_refs) <= ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError("active_settlement_refs must contain canonical ACTIVE identities")
        source_identities = {self.source_ref, *self.source_dependency_refs}
        if source_identities & FROZEN_ROUTE_QUOTE_BASELINE_IDS:
            raise ValueError("catalog-only frozen quote identity cannot create research work")
        if tuple(sorted(set(self.upstream_work_keys))) != self.upstream_work_keys:
            raise ValueError("upstream_work_keys must be unique and sorted")
        if not all(len(value) == 64 for value in self.upstream_work_keys):
            raise ValueError("upstream_work_keys must contain canonical SHA-256 keys")
        if tuple(sorted(set(self.evidence_requirements))) != self.evidence_requirements:
            raise ValueError("evidence_requirements must be unique and sorted")
        if tuple(sorted(set(self.authority_scope))) != self.authority_scope:
            raise ValueError("authority_scope must be unique and sorted")
        if tuple(sorted(set(self.input_snapshot_hashes))) != self.input_snapshot_hashes:
            raise ValueError("input_snapshot_hashes must be unique and sorted")
        return self


ResearchWorkItemLike = ResearchWorkItem | ResearchWorkItemV3


def parse_research_work_item(
    value: ResearchWorkItemLike | Mapping[str, Any],
) -> ResearchWorkItemLike:
    """Parse a work item without silently upgrading historical v2 identities."""

    if isinstance(value, ResearchWorkItemV3):
        return value
    if isinstance(value, ResearchWorkItem):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("research work item must be an object")
    schema_version = value.get("schema_version")
    if schema_version == "xinao.research_work_item.v2":
        return ResearchWorkItem.model_validate(value)
    if schema_version == "xinao.research_work_item.v3":
        return ResearchWorkItemV3.model_validate(value)
    raise ValueError(f"unsupported research work item schema: {schema_version!r}")


class OpenMethodRegistration(BaseModel):
    """Typed admission surface that does not restrict research to a method list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.open_method_registration.v1"] = (
        "xinao.open_method_registration.v1"
    )
    method_id: str = Field(min_length=1)
    method_kind: str = Field(min_length=1)
    executable_ref: str = Field(min_length=1)
    executable_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_schema_ref: str = Field(min_length=1)
    input_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_ref: str = Field(min_length=1)
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_protocol_ref: str = Field(min_length=1)
    verification_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_contract_ref: str = Field(min_length=1)
    failure_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_refs: tuple[str, ...] = Field(min_length=1)
    deterministic_seed_policy: str = Field(min_length=1)
    canary_evidence_ref: str = Field(min_length=1)
    canary_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canary_status: Literal["VERIFIED"] = "VERIFIED"

    @model_validator(mode="after")
    def canonical_sources(self) -> Self:
        if tuple(sorted(set(self.source_refs))) != self.source_refs:
            raise ValueError("source_refs must be unique and sorted")
        bound_refs = (
            self.executable_ref,
            self.input_schema_ref,
            self.output_schema_ref,
            self.verification_protocol_ref,
            self.failure_contract_ref,
            self.canary_evidence_ref,
        )
        if len(set(bound_refs)) != len(bound_refs):
            raise ValueError("open method bound artifact refs must be distinct")
        return self


class ResearchErrorBudgetPolicy(BaseModel):
    """Finite confirmation budget with an explicit negative-control contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.research_error_budget_policy.v1"] = (
        "xinao.research_error_budget_policy.v1"
    )
    policy_ref: Literal["research-error-budget.foundation.v1"] = (
        "research-error-budget.foundation.v1"
    )
    maximum_hypotheses_per_family: int = Field(default=20, ge=1)
    maximum_confirmation_queries_per_candidate: int = Field(default=3, ge=1)
    required_negative_control_kinds: tuple[
        Literal["CIRCULAR_SHIFT", "LABEL_PERMUTATION", "NULL_CONSTANT"], ...
    ] = ("CIRCULAR_SHIFT", "LABEL_PERMUTATION", "NULL_CONSTANT")
    exploration_multiple_testing: Literal["BH_FDR_0.05"] = "BH_FDR_0.05"
    confirmation_multiple_testing: Literal["HOLM_FWER_0.05"] = "HOLM_FWER_0.05"
    debit_semantics: Literal["ATOMIC_BEFORE_QUERY"] = "ATOMIC_BEFORE_QUERY"


class ProducerStageEvidence(BaseModel):
    """Typed producer artifact admitted by deterministic fan-in."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    work_key: str = Field(min_length=1)
    producer_id: str = Field(min_length=1)
    status: Literal["VERIFIED", "PARTIAL", "FAILED", "FALSIFIED", "NO_ACTION"]
    claim_refs: tuple[str, ...] = ()
    artifact_ref: str = Field(min_length=1)
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    temporal_workflow_id: str = Field(min_length=1)
    temporal_run_id: str = Field(min_length=1)
    lane_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1)


class CritiqueStageEvidence(BaseModel):
    """Typed critique artifact bound to one producer artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    work_key: str = Field(min_length=1)
    critic_id: str = Field(min_length=1)
    target_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["APPROVED", "CHANGES_REQUESTED", "REJECTED"]
    finding_refs: tuple[str, ...] = ()
    critique_artifact_ref: str = Field(min_length=1)
    critique_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    temporal_workflow_id: str = Field(min_length=1)
    temporal_run_id: str = Field(min_length=1)
    lane_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1)


class VerificationStageEvidence(BaseModel):
    """Typed independent verification bound to producer and critique bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    work_key: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    target_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_critique_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["VERIFIED", "PARTIAL", "REJECTED"]
    evidence_refs: tuple[str, ...] = ()
    verification_artifact_ref: str = Field(min_length=1)
    verification_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    temporal_workflow_id: str = Field(min_length=1)
    temporal_run_id: str = Field(min_length=1)
    lane_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1)


def evaluate_error_budget(
    policy: ResearchErrorBudgetPolicy,
    *,
    hypotheses_in_family: int,
    confirmation_queries_used: int,
    negative_control_kinds: Sequence[str],
) -> dict[str, Any]:
    """Return a fail-closed, non-mutating admission decision for one query."""

    observed_controls = set(negative_control_kinds)
    missing_controls = sorted(set(policy.required_negative_control_kinds) - observed_controls)
    reasons: list[str] = []
    if hypotheses_in_family >= policy.maximum_hypotheses_per_family:
        reasons.append("HYPOTHESIS_FAMILY_BUDGET_EXHAUSTED")
    if confirmation_queries_used >= policy.maximum_confirmation_queries_per_candidate:
        reasons.append("CONFIRMATION_QUERY_BUDGET_EXHAUSTED")
    if missing_controls:
        reasons.append("NEGATIVE_CONTROLS_INCOMPLETE")
    return {
        "schema_version": "xinao.research_error_budget_decision.v1",
        "policy_ref": policy.policy_ref,
        "admitted": not reasons,
        "reasons": reasons,
        "missing_negative_controls": missing_controls,
        "next_confirmation_queries_used": (
            confirmation_queries_used + 1 if not reasons else confirmation_queries_used
        ),
        "debit_semantics": policy.debit_semantics,
    }


def canonical_work_key(
    item: ResearchWorkItem | Mapping[str, Any],
    *,
    source_origin_by_ref: Mapping[str, str] | None = None,
    source_projection_hash: str | None = None,
) -> str:
    """Hash semantic work identity, collapsing known mirrors to one origin."""

    value = item if isinstance(item, ResearchWorkItem) else ResearchWorkItem.model_validate(item)
    origins = source_origin_by_ref or {}
    source_origin = str(origins.get(value.source_ref) or value.source_ref)
    source_dependency_origins = sorted(
        {str(origins.get(dependency) or dependency) for dependency in value.source_dependency_refs}
    )
    if {
        source_origin,
        *source_dependency_origins,
    } & FROZEN_ROUTE_QUOTE_BASELINE_IDS:
        raise ValueError("frozen quote origin cannot create research work")
    return canonical_sha256(
        {
            "physical_role": value.physical_role,
            "active_settlement_refs": list(value.active_settlement_refs),
            "kind": value.kind,
            "source_origin": source_origin,
            "source_dependency_origins": source_dependency_origins,
            "source_projection_hash": source_projection_hash or "UNBOUND",
            "intent_slice": value.intent_slice,
            "selection_manifest_hash": value.selection_manifest_hash,
            "method_id": value.method_id,
            "method_registration_hash": value.method_registration_hash,
            "method_admission_hash": value.method_admission_hash,
            "world_snapshot_hash": value.world_snapshot_hash,
            "input_snapshot_hashes": list(value.input_snapshot_hashes),
        }
    )


def canonical_work_key_v3(
    item: ResearchWorkItemV3 | Mapping[str, Any],
    *,
    source_origin_by_ref: Mapping[str, str] | None = None,
    source_projection_hash: str | None = None,
) -> str:
    """Hash phase-qualified v3 work without weakening the historical v2 API."""

    value = (
        item if isinstance(item, ResearchWorkItemV3) else ResearchWorkItemV3.model_validate(item)
    )
    origins = source_origin_by_ref or {}
    source_origin = str(origins.get(value.source_ref) or value.source_ref)
    source_dependency_origins = sorted(
        {str(origins.get(dependency) or dependency) for dependency in value.source_dependency_refs}
    )
    if {
        source_origin,
        *source_dependency_origins,
    } & FROZEN_ROUTE_QUOTE_BASELINE_IDS:
        raise ValueError("frozen quote origin cannot create research work")
    return canonical_sha256(
        {
            "physical_role": value.physical_role,
            "execution_phase": value.execution_phase,
            "active_settlement_refs": list(value.active_settlement_refs),
            "kind": value.kind,
            "source_origin": source_origin,
            "source_dependency_origins": source_dependency_origins,
            "source_projection_hash": source_projection_hash or "UNBOUND",
            "intent_slice": value.intent_slice,
            "selection_manifest_hash": value.selection_manifest_hash,
            "method_id": value.method_id,
            "method_registration_hash": value.method_registration_hash,
            "method_admission_hash": value.method_admission_hash,
            "world_snapshot_hash": value.world_snapshot_hash,
            "input_snapshot_hashes": list(value.input_snapshot_hashes),
        }
    )


def source_projection_hash(
    graph: Mapping[str, Any],
    source_refs: Sequence[str],
) -> str:
    """Hash only the origin/lineage projection relevant to one work item."""

    origins, _ = source_origin_index(graph)
    relevant = sorted(set(source_refs))
    missing = sorted(set(relevant) - set(origins))
    if missing:
        raise ValueError(f"source projection contains unknown refs: {missing}")
    relevant_set = set(relevant)
    if {origins[ref] for ref in relevant} & FROZEN_ROUTE_QUOTE_BASELINE_IDS:
        raise ValueError("source projection resolves to a frozen quote origin")
    edges = [
        {
            "from": str(row.get("from") or ""),
            "to": str(row.get("to") or ""),
            "relation": str(row.get("relation") or ""),
        }
        for row in graph.get("edges") or []
        if isinstance(row, Mapping)
        and str(row.get("from") or "") in relevant_set
        and str(row.get("to") or "") in relevant_set
    ]
    return canonical_sha256(
        {
            "sources": [{"source_ref": ref, "origin_cluster_id": origins[ref]} for ref in relevant],
            "lineage_edges": sorted(
                edges,
                key=lambda row: (row["from"], row["to"], row["relation"]),
            ),
        }
    )


def source_origin_index(graph: Mapping[str, Any]) -> tuple[dict[str, str], str]:
    """Validate one source-lineage DAG without confusing lineage with sameness.

    ``origin_cluster_id`` is the only equivalence relation used for mirror
    deduplication.  Directed edges express derivation/dependency and are
    cycle-checked, but they never merge two otherwise independent origins.
    """

    if not verify_versioned_object(graph) or graph.get("object_type") != (
        "SourceDependencyGraphVersion"
    ):
        raise ValueError("source dependency graph is not version/hash bound")
    graph_hash = str(graph["content_sha256"])
    sources = graph.get("sources")
    edges = graph.get("edges")
    if not isinstance(sources, list) or not isinstance(edges, list):
        raise TypeError("source dependency graph sources and edges must be lists")
    declared: dict[str, str] = {}
    for row in sources:
        if not isinstance(row, Mapping):
            raise TypeError("source dependency graph source must be an object")
        source_id = str(row.get("source_id") or "")
        origin_id = str(row.get("origin_cluster_id") or "")
        if not source_id or not origin_id or source_id in declared:
            raise ValueError("source dependency graph source identity is invalid")
        declared[source_id] = origin_id

    outgoing: dict[str, set[str]] = {source_id: set() for source_id in declared}
    for row in edges:
        if not isinstance(row, Mapping):
            raise TypeError("source dependency graph edge must be an object")
        left = str(row.get("from") or "")
        right = str(row.get("to") or "")
        if left not in declared or right not in declared or left == right:
            raise ValueError("source dependency graph edge identity is invalid")
        outgoing[left].add(right)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("source dependency graph contains a directed cycle")
        if node in visited:
            return
        visiting.add(node)
        for child in sorted(outgoing[node]):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for source_id in sorted(declared):
        visit(source_id)

    return dict(declared), graph_hash


def dedupe_ready_frontier(
    items: Sequence[ResearchWorkItem | Mapping[str, Any]],
    *,
    closed_work_keys: Sequence[str] = (),
    in_flight_work_keys: Sequence[str] = (),
    source_origin_by_ref: Mapping[str, str] | None = None,
    source_dependency_graph: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a stable ready frontier and explicit deferral/dedup evidence."""

    excluded = set(closed_work_keys) | set(in_flight_work_keys)
    seen: set[str] = set()
    ready: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    graph_hash: str | None = None
    origins = dict(source_origin_by_ref or {})
    if source_dependency_graph is not None:
        graph_origins, graph_hash = source_origin_index(source_dependency_graph)
        if origins and origins != graph_origins:
            raise ValueError("explicit origin mapping disagrees with source dependency graph")
        origins = graph_origins
    parsed = [
        item if isinstance(item, ResearchWorkItem) else ResearchWorkItem.model_validate(item)
        for item in items
    ]
    for item in sorted(
        parsed,
        key=lambda value: (
            value.kind,
            value.source_ref,
            value.intent_slice,
            value.method_id,
        ),
    ):
        projection_hash = (
            source_projection_hash(
                source_dependency_graph,
                (item.source_ref, *item.source_dependency_refs),
            )
            if source_dependency_graph is not None
            else None
        )
        work_key = canonical_work_key(
            item,
            source_origin_by_ref=origins,
            source_projection_hash=projection_hash,
        )
        missing = sorted(set(item.upstream_work_keys) - set(closed_work_keys))
        record = {
            "work_key": work_key,
            "item": item.model_dump(mode="json"),
        }
        if missing:
            deferred.append({**record, "reason": "DEPENDENCY_NOT_SATISFIED", "missing": missing})
            continue
        if work_key in excluded:
            duplicates.append({**record, "reason": "ALREADY_CLOSED_OR_IN_FLIGHT"})
            continue
        if work_key in seen:
            duplicates.append({**record, "reason": "DUPLICATE_OR_SOURCE_MIRROR"})
            continue
        seen.add(work_key)
        ready.append(record)
    return {
        "schema_version": "xinao.deduped_ready_frontier.v1",
        "ready": ready,
        "deferred": deferred,
        "duplicates": duplicates,
        "ready_work_keys": [item["work_key"] for item in ready],
        "source_dependency_graph_hash": graph_hash or "UNBOUND",
        "content_sha256": canonical_sha256(
            {
                "ready": ready,
                "deferred": deferred,
                "duplicates": duplicates,
            }
        ),
    }


def dedupe_ready_frontier_v3(
    items: Sequence[ResearchWorkItemV3 | Mapping[str, Any]],
    *,
    expected_phase: Literal["FOUNDATION_CONSTRUCTION", "AUTONOMOUS_RESEARCH"],
    closed_work_keys: Sequence[str] = (),
    in_flight_work_keys: Sequence[str] = (),
    source_origin_by_ref: Mapping[str, str] | None = None,
    source_dependency_graph: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a stable phase-qualified v3 frontier without entering v2 dispatch."""

    excluded = set(closed_work_keys) | set(in_flight_work_keys)
    seen: set[str] = set()
    ready: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    graph_hash: str | None = None
    origins = dict(source_origin_by_ref or {})
    if source_dependency_graph is not None:
        graph_origins, graph_hash = source_origin_index(source_dependency_graph)
        if origins and origins != graph_origins:
            raise ValueError("explicit origin mapping disagrees with source dependency graph")
        origins = graph_origins
    parsed = [
        item if isinstance(item, ResearchWorkItemV3) else ResearchWorkItemV3.model_validate(item)
        for item in items
    ]
    if any(item.execution_phase != expected_phase for item in parsed):
        raise ValueError("v3 frontier contains work outside its expected execution phase")
    for item in sorted(
        parsed,
        key=lambda value: (
            value.kind,
            value.source_ref,
            value.intent_slice,
            value.method_id,
        ),
    ):
        projection_hash = (
            source_projection_hash(
                source_dependency_graph,
                (item.source_ref, *item.source_dependency_refs),
            )
            if source_dependency_graph is not None
            else None
        )
        work_key = canonical_work_key_v3(
            item,
            source_origin_by_ref=origins,
            source_projection_hash=projection_hash,
        )
        missing = sorted(set(item.upstream_work_keys) - set(closed_work_keys))
        record = {
            "work_key": work_key,
            "item": item.model_dump(mode="json"),
        }
        if missing:
            deferred.append({**record, "reason": "DEPENDENCY_NOT_SATISFIED", "missing": missing})
            continue
        if work_key in excluded:
            duplicates.append({**record, "reason": "ALREADY_CLOSED_OR_IN_FLIGHT"})
            continue
        if work_key in seen:
            duplicates.append({**record, "reason": "DUPLICATE_OR_SOURCE_MIRROR"})
            continue
        seen.add(work_key)
        ready.append(record)
    return {
        "schema_version": "xinao.deduped_ready_frontier.v2",
        "execution_phase": expected_phase,
        "ready": ready,
        "deferred": deferred,
        "duplicates": duplicates,
        "ready_work_keys": [item["work_key"] for item in ready],
        "source_dependency_graph_hash": graph_hash or "UNBOUND",
        "content_sha256": canonical_sha256(
            {
                "execution_phase": expected_phase,
                "ready": ready,
                "deferred": deferred,
                "duplicates": duplicates,
            }
        ),
    }


def finalize_research_candidate_question(
    *,
    question_id: str,
    candidate_generator_id: str,
    candidate_generator_source_sha256: str,
    active_surface_ref: str,
    selection_manifest_ref: str,
    method_registry_sha256: str,
    source_dependency_graph_ref: str,
    candidate_specs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Freeze one complete episode candidate universe as a ResearchQuestion."""

    refs = (
        candidate_generator_source_sha256,
        active_surface_ref,
        selection_manifest_ref,
        method_registry_sha256,
        source_dependency_graph_ref,
    )
    if not question_id or not candidate_generator_id or not all(map(_is_sha256, refs)):
        raise ValueError("research candidate question identity is incomplete")
    normalized: list[dict[str, Any]] = []
    for raw in candidate_specs:
        if not isinstance(raw, Mapping) or set(raw) != {
            "candidate_id",
            "work_item",
            "lane_templates_sha256",
            "portfolio_lane",
        }:
            raise ValueError("candidate spec fields are not exact")
        candidate_id = str(raw.get("candidate_id") or "")
        lane = str(raw.get("portfolio_lane") or "").upper()
        if (
            not candidate_id
            or not _is_sha256(raw.get("lane_templates_sha256"))
            or lane not in {"EXPLOITATION", "EXPLORATION"}
        ):
            raise ValueError("candidate spec identity is invalid")
        item = ResearchWorkItem.model_validate(raw.get("work_item"))
        normalized.append(
            {
                "candidate_id": candidate_id,
                "work_item": item.model_dump(mode="json"),
                "lane_templates_sha256": str(raw["lane_templates_sha256"]),
                "portfolio_lane": lane,
            }
        )
    if [row["candidate_id"] for row in normalized] != sorted(
        {row["candidate_id"] for row in normalized}
    ):
        raise ValueError("candidate specs must have unique canonical candidate order")
    core = {
        "object_type": "ResearchQuestion",
        "schema_version": "xinao.research_candidate_question.v1",
        "question_id": question_id,
        "scope_type": "EPISODE_CANDIDATE_UNIVERSE",
        "scope_complete": True,
        "candidate_generation_rule": "EXACT_BOUND_CANDIDATE_SPECS",
        "candidate_generator_id": candidate_generator_id,
        "candidate_generator_source_sha256": candidate_generator_source_sha256,
        "active_surface_ref": active_surface_ref,
        "selection_manifest_ref": selection_manifest_ref,
        "method_registry_sha256": method_registry_sha256,
        "source_dependency_graph_ref": source_dependency_graph_ref,
        "candidate_count": len(normalized),
        "candidate_specs": normalized,
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"ResearchQuestion@{digest[:16]}",
        "content_sha256": digest,
    }


def compile_research_candidate_snapshot(
    candidate_entries: Sequence[Mapping[str, Any]],
    *,
    research_question: Mapping[str, Any],
    active_surface: Mapping[str, Any],
    selection_manifest: Mapping[str, Any],
    method_registry: Mapping[str, Mapping[str, Any]],
    source_dependency_graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile the exact admitted universe defined by a bound ResearchQuestion."""

    if (
        research_question.get("object_type") != "ResearchQuestion"
        or research_question.get("schema_version") != "xinao.research_candidate_question.v1"
        or research_question.get("scope_complete") is not True
        or not verify_versioned_object(research_question)
    ):
        raise ValueError("candidate snapshot requires a complete verified ResearchQuestion")
    if (
        active_surface.get("object_type") != "ActiveResearchSurfaceVersion"
        or not verify_versioned_object(active_surface)
        or research_question.get("active_surface_ref") != active_surface.get("content_sha256")
    ):
        raise ValueError("candidate question active surface binding drifted")
    manifest = IndependentExpectedSelectionDomainManifestVersion.model_validate(selection_manifest)
    validate_method_registry(method_registry)
    _, graph_hash = source_origin_index(source_dependency_graph)
    if (
        research_question.get("selection_manifest_ref") != manifest.content_hash
        or research_question.get("method_registry_sha256") != canonical_sha256(method_registry)
        or research_question.get("source_dependency_graph_ref") != graph_hash
    ):
        raise ValueError("candidate question source bindings drifted")

    component_family: dict[str, str] = {}
    surface_rows = active_surface.get("rows")
    if not isinstance(surface_rows, list):
        raise TypeError("active research surface rows must be a list")
    for row in surface_rows:
        if not isinstance(row, Mapping):
            raise TypeError("active research surface row must be an object")
        family_id = str(row.get("family_id") or "")
        component_ids = row.get("active_component_ids")
        if not family_id or not isinstance(component_ids, list):
            raise ValueError("active research surface row is incomplete")
        for component_id in map(str, component_ids):
            if component_id in component_family:
                raise ValueError("active component belongs to multiple families")
            component_family[component_id] = family_id

    specs = research_question.get("candidate_specs")
    if (
        not isinstance(specs, list)
        or research_question.get("candidate_count") != len(specs)
        or len(candidate_entries) != len(specs)
    ):
        raise ValueError("candidate question coverage is incomplete")
    entries_by_item_hash: dict[str, Mapping[str, Any]] = {}
    for entry in candidate_entries:
        if not isinstance(entry, Mapping):
            raise TypeError("candidate entry must be an object")
        candidate_item = ResearchWorkItem.model_validate(entry.get("work_item"))
        item_hash = canonical_sha256(candidate_item.model_dump(mode="json"))
        if item_hash in entries_by_item_hash:
            raise ValueError("candidate entry universe contains a duplicate item")
        entries_by_item_hash[item_hash] = entry

    origins, _ = source_origin_index(source_dependency_graph)
    candidate_rows: list[dict[str, Any]] = []
    work_keys: set[str] = set()
    for spec in specs:
        if not isinstance(spec, Mapping):
            raise TypeError("candidate spec must be an object")
        expected_item = ResearchWorkItem.model_validate(spec.get("work_item"))
        item_hash = canonical_sha256(expected_item.model_dump(mode="json"))
        entry = entries_by_item_hash.pop(item_hash, None)
        if entry is None:
            raise ValueError("candidate question has a missing or replaced entry")
        lane_templates = entry.get("lane_templates")
        if not isinstance(lane_templates, Mapping) or canonical_sha256(lane_templates) != spec.get(
            "lane_templates_sha256"
        ):
            raise ValueError("candidate lane template binding drifted")
        declared_lane = str(entry.get("portfolio_lane") or spec.get("portfolio_lane")).upper()
        if declared_lane != spec.get("portfolio_lane"):
            raise ValueError("candidate cannot self-assign a portfolio lane")
        admit_work_item(
            expected_item,
            selection_manifest=manifest,
            method_registry=method_registry,
        )
        families = {
            component_family.get(component_id)
            for component_id in expected_item.active_settlement_refs
        }
        if None in families or len(families) != 1:
            raise ValueError("candidate must bind exactly one active research family")
        work_key = canonical_work_key(
            expected_item,
            source_origin_by_ref=origins,
            source_projection_hash=source_projection_hash(
                source_dependency_graph,
                (expected_item.source_ref, *expected_item.source_dependency_refs),
            ),
        )
        if work_key in work_keys:
            raise ValueError("candidate universe contains duplicate canonical work")
        work_keys.add(work_key)
        candidate_rows.append(
            {
                "candidate_id": str(spec["candidate_id"]),
                "entry": dict(entry),
                "entry_sha256": canonical_sha256(entry),
                "work_key": work_key,
                "family_id": next(iter(families)),
                "portfolio_lane": declared_lane,
                "active_settlement_refs": list(expected_item.active_settlement_refs),
            }
        )
    if entries_by_item_hash:
        raise ValueError("candidate entry universe contains an unscoped item")
    core = {
        "object_type": "ResearchCandidateSnapshot",
        "schema_version": "xinao.research_candidate_snapshot.v1",
        "research_question_ref": research_question["content_sha256"],
        "candidate_generator_id": research_question["candidate_generator_id"],
        "candidate_generator_source_sha256": research_question["candidate_generator_source_sha256"],
        "active_surface_ref": active_surface["content_sha256"],
        "selection_manifest_ref": manifest.content_hash,
        "method_registry_sha256": canonical_sha256(method_registry),
        "source_dependency_graph_ref": graph_hash,
        "compiler_source_sha256": _callable_source_hash(compile_research_candidate_snapshot),
        "candidate_count": len(candidate_rows),
        "candidate_rows": candidate_rows,
        "candidate_universe_sha256": canonical_sha256(candidate_rows),
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"ResearchCandidateSnapshot@{digest[:16]}",
        "content_sha256": digest,
    }


def compile_research_portfolio_allocation(
    candidate_snapshot: Mapping[str, Any],
    *,
    active_surface: Mapping[str, Any],
    portfolio_policy: Mapping[str, Any],
    source_dependency_graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Allocate a complete bound candidate snapshot with weighted-fair prefixes."""

    if candidate_snapshot.get(
        "object_type"
    ) != "ResearchCandidateSnapshot" or not verify_versioned_object(candidate_snapshot):
        raise ValueError("portfolio allocation requires a verified candidate snapshot")
    if (
        active_surface.get("object_type") != "ActiveResearchSurfaceVersion"
        or not verify_versioned_object(active_surface)
        or candidate_snapshot.get("active_surface_ref") != active_surface.get("content_sha256")
    ):
        raise ValueError("portfolio allocation requires the candidate active surface")
    if (
        portfolio_policy.get("object_type") != "ResearchPortfolioPolicyVersion"
        or not verify_versioned_object(portfolio_policy)
        or portfolio_policy.get("active_surface_ref") != active_surface.get("content_sha256")
    ):
        raise ValueError("portfolio allocation policy is not bound to active surface")
    _, graph_hash = source_origin_index(source_dependency_graph)
    if candidate_snapshot.get("source_dependency_graph_ref") != graph_hash:
        raise ValueError("candidate snapshot source graph binding drifted")

    def positive_decimal(value: object, field: str, *, allow_zero: bool = False) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field} must be a decimal") from exc
        if not parsed.is_finite() or parsed < 0 or (parsed == 0 and not allow_zero):
            raise ValueError(f"{field} must be {'non-negative' if allow_zero else 'positive'}")
        return parsed

    rows = active_surface.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("active research surface rows are required")
    family_share: dict[str, Decimal] = {}
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise TypeError("active research surface row must be an object")
        family_id = str(raw_row.get("family_id") or "")
        if not family_id or family_id in family_share:
            raise ValueError("active research surface family identity is invalid")
        family_share[family_id] = positive_decimal(
            raw_row.get("research_resource_share"),
            "research_resource_share",
        )

    exploitation_share = positive_decimal(
        portfolio_policy.get("exploitation_share"),
        "exploitation_share",
        allow_zero=True,
    )
    exploration_share = positive_decimal(
        portfolio_policy.get("exploration_share"),
        "exploration_share",
        allow_zero=True,
    )
    if exploitation_share + exploration_share != Decimal("1"):
        raise ValueError("portfolio policy shares must sum to one")
    if sum(family_share.values(), Decimal("0")) != exploitation_share:
        raise ValueError("active research surface shares do not equal exploitation share")

    raw_candidates = candidate_snapshot.get("candidate_rows")
    if not isinstance(raw_candidates, list) or candidate_snapshot.get("candidate_count") != len(
        raw_candidates
    ):
        raise ValueError("candidate snapshot inventory is invalid")
    candidates: list[dict[str, Any]] = []
    exploration_buckets: set[str] = set()
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            raise TypeError("candidate snapshot row must be an object")
        family_id = str(raw.get("family_id") or "")
        lane = str(raw.get("portfolio_lane") or "")
        if family_id not in family_share or lane not in {"EXPLOITATION", "EXPLORATION"}:
            raise ValueError("candidate snapshot row has an invalid portfolio bucket")
        bucket_id = f"{lane}:{family_id}"
        if lane == "EXPLORATION":
            exploration_buckets.add(bucket_id)
        candidate = dict(raw)
        candidate["bucket_id"] = bucket_id
        candidates.append(candidate)

    bucket_weights: dict[str, Fraction] = {}
    for candidate in candidates:
        bucket_id = str(candidate["bucket_id"])
        if bucket_id in bucket_weights:
            continue
        if candidate["portfolio_lane"] == "EXPLORATION":
            if exploration_share == 0 or not exploration_buckets:
                raise ValueError("exploration candidate has no reserved policy share")
            bucket_weights[bucket_id] = Fraction(exploration_share) / len(exploration_buckets)
        else:
            bucket_weights[bucket_id] = Fraction(family_share[str(candidate["family_id"])])

    by_bucket: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_bucket.setdefault(str(candidate["bucket_id"]), []).append(candidate)
    scheduled: list[tuple[Fraction, str, dict[str, Any]]] = []
    for bucket_id, bucket_candidates in sorted(by_bucket.items()):
        weight = bucket_weights[bucket_id]
        if weight <= 0:
            raise ValueError("portfolio candidate bucket has zero policy weight")
        for ordinal, candidate in enumerate(
            sorted(
                bucket_candidates,
                key=lambda value: (value["candidate_id"], value["work_key"]),
            ),
            start=1,
        ):
            scheduled.append((Fraction(ordinal, 1) / weight, bucket_id, candidate))
    scheduled.sort(
        key=lambda value: (
            value[0],
            value[1],
            value[2]["candidate_id"],
            value[2]["work_key"],
        )
    )
    allocations = []
    for rank, (virtual_finish, bucket_id, candidate) in enumerate(scheduled, start=1):
        allocations.append(
            {
                "rank": rank,
                "candidate_id": candidate["candidate_id"],
                "work_key": candidate["work_key"],
                "entry_sha256": candidate["entry_sha256"],
                "portfolio_lane": candidate["portfolio_lane"],
                "bucket_id": bucket_id,
                "family_id": candidate["family_id"],
                "active_settlement_refs": candidate["active_settlement_refs"],
                "bucket_weight_fraction": (
                    f"{bucket_weights[bucket_id].numerator}/{bucket_weights[bucket_id].denominator}"
                ),
                "virtual_finish_fraction": (
                    f"{virtual_finish.numerator}/{virtual_finish.denominator}"
                ),
            }
        )
    ordered_entries = [candidate["entry"] for _, _, candidate in scheduled]
    core = {
        "object_type": "ResearchPortfolioAllocation",
        "schema_version": "xinao.research_portfolio_allocation.v2",
        "candidate_snapshot_ref": candidate_snapshot["content_sha256"],
        "candidate_universe_sha256": candidate_snapshot["candidate_universe_sha256"],
        "policy_ref": portfolio_policy["content_sha256"],
        "active_surface_ref": active_surface["content_sha256"],
        "source_dependency_graph_ref": graph_hash,
        "allocation_scope": "EPISODE_FROZEN_COMPLETE_CANDIDATE_UNIVERSE",
        "scheduling_policy": "DETERMINISTIC_WEIGHTED_VIRTUAL_FINISH_V1",
        "compiler_source_sha256": _callable_source_hash(compile_research_portfolio_allocation),
        "reserved_exploration_share": str(exploration_share),
        "candidate_count": len(allocations),
        "allocations": allocations,
        "ready_work_keys": [str(row["work_key"]) for row in allocations],
        "ordered_entry_sha256s": [str(row["entry_sha256"]) for row in allocations],
        "ready_frontier_sha256": canonical_sha256(ordered_entries),
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"ResearchPortfolioAllocation@{digest[:16]}",
        "content_sha256": digest,
    }


def project_allocated_ready_frontier(
    portfolio_allocation: Mapping[str, Any],
    *,
    candidate_snapshot: Mapping[str, Any],
    closed_work_keys: Sequence[str] = (),
    in_flight_work_keys: Sequence[str] = (),
) -> dict[str, Any]:
    """Filter one frozen allocation without ever changing its canonical rank."""

    if (
        portfolio_allocation.get("object_type") != "ResearchPortfolioAllocation"
        or not verify_versioned_object(portfolio_allocation)
        or candidate_snapshot.get("object_type") != "ResearchCandidateSnapshot"
        or not verify_versioned_object(candidate_snapshot)
        or portfolio_allocation.get("candidate_snapshot_ref")
        != candidate_snapshot.get("content_sha256")
    ):
        raise ValueError("ready projection requires its verified candidate allocation")

    raw_candidates = candidate_snapshot.get("candidate_rows")
    raw_allocations = portfolio_allocation.get("allocations")
    if (
        not isinstance(raw_candidates, list)
        or candidate_snapshot.get("candidate_count") != len(raw_candidates)
        or not isinstance(raw_allocations, list)
        or portfolio_allocation.get("candidate_count") != len(raw_allocations)
        or len(raw_candidates) != len(raw_allocations)
    ):
        raise ValueError("ready projection candidate inventory is incomplete")

    candidates: dict[str, Mapping[str, Any]] = {}
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            raise TypeError("candidate snapshot row must be an object")
        candidate_id = str(raw.get("candidate_id") or "")
        if not candidate_id or candidate_id in candidates:
            raise ValueError("candidate snapshot identity is not unique")
        candidates[candidate_id] = raw

    closed = {str(value) for value in closed_work_keys}
    in_flight = {str(value) for value in in_flight_work_keys}
    excluded = closed | in_flight
    ready: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen_candidates: set[str] = set()
    seen_work_keys: set[str] = set()
    ordered_entry_sha256s: list[str] = []
    ordered_work_keys: list[str] = []

    for expected_rank, raw in enumerate(raw_allocations, start=1):
        if not isinstance(raw, Mapping):
            raise TypeError("portfolio allocation row must be an object")
        candidate_id = str(raw.get("candidate_id") or "")
        work_key = str(raw.get("work_key") or "")
        candidate = candidates.get(candidate_id)
        if (
            raw.get("rank") != expected_rank
            or candidate is None
            or candidate_id in seen_candidates
            or work_key in seen_work_keys
            or work_key != candidate.get("work_key")
            or raw.get("entry_sha256") != candidate.get("entry_sha256")
            or raw.get("family_id") != candidate.get("family_id")
            or raw.get("portfolio_lane") != candidate.get("portfolio_lane")
        ):
            raise ValueError("portfolio allocation rank or candidate binding drifted")
        seen_candidates.add(candidate_id)
        seen_work_keys.add(work_key)
        ordered_work_keys.append(work_key)
        ordered_entry_sha256s.append(str(raw["entry_sha256"]))

        entry = candidate.get("entry")
        if not isinstance(entry, Mapping):
            raise TypeError("candidate entry must be an object")
        item = ResearchWorkItem.model_validate(entry.get("work_item"))
        record = {
            "rank": expected_rank,
            "candidate_id": candidate_id,
            "work_key": work_key,
            "item": item.model_dump(mode="json"),
            "entry_sha256": str(raw["entry_sha256"]),
        }
        missing = sorted(set(item.upstream_work_keys) - closed)
        if missing:
            deferred.append(
                {
                    **record,
                    "reason": "DEPENDENCY_NOT_SATISFIED",
                    "missing": missing,
                }
            )
        elif work_key in excluded:
            duplicates.append(
                {
                    **record,
                    "reason": "ALREADY_CLOSED_OR_IN_FLIGHT",
                }
            )
        else:
            ready.append(record)

    if (
        set(candidates) != seen_candidates
        or portfolio_allocation.get("ready_work_keys") != ordered_work_keys
        or portfolio_allocation.get("ordered_entry_sha256s") != ordered_entry_sha256s
    ):
        raise ValueError("portfolio allocation does not cover the exact candidate snapshot")

    core = {
        "object_type": "AllocatedReadyFrontierProjection",
        "schema_version": "xinao.allocated_ready_frontier_projection.v1",
        "allocation_ref": portfolio_allocation["content_sha256"],
        "candidate_snapshot_ref": candidate_snapshot["content_sha256"],
        "closed_work_keys": sorted(closed),
        "in_flight_work_keys": sorted(in_flight),
        "execution_state_sha256": canonical_sha256(
            {
                "closed_work_keys": sorted(closed),
                "in_flight_work_keys": sorted(in_flight),
            }
        ),
        "ready": ready,
        "deferred": deferred,
        "duplicates": duplicates,
        "ready_work_keys": [record["work_key"] for record in ready],
        "ready_frontier_sha256": canonical_sha256(ready),
        "order_policy": "FILTER_FROZEN_ALLOCATION_RANK_WITHOUT_REORDER",
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"AllocatedReadyFrontierProjection@{digest[:16]}",
        "content_sha256": digest,
    }


def _tier_at_or_below(value: int) -> int:
    return max(tier for tier in CAPACITY_TIERS if tier <= max(1, min(value, CAPACITY_TIERS[-1])))


def select_dynamic_capacity(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Choose capacity from current evidence, never from a fixed lane count."""

    host_state = str(observation.get("host_state") or "absent").lower()
    ready_count = max(0, int(observation.get("ready_count") or 0))
    available_slots = max(0, min(int(observation.get("available_slots") or 0), 32))
    previous_width = _tier_at_or_below(int(observation.get("previous_width") or 1))
    succeeded = max(0, int(observation.get("succeeded") or 0))
    failed = max(0, int(observation.get("failed") or 0))
    partial = bool(observation.get("partial"))
    queue_depth = max(0, int(observation.get("queue_depth") or ready_count))

    if host_state != "available" or available_slots == 0 or ready_count == 0:
        reason = "HOST_NOT_READY" if host_state != "available" or available_slots == 0 else "EMPTY"
        payload = {
            "schema_version": "xinao.dynamic_capacity_decision.v1",
            "policy_version": FACTORY_POLICY_VERSION,
            "capacity_tier": previous_width,
            "dispatch_width": 0,
            "reason": reason,
            "backpressure": reason == "HOST_NOT_READY",
            "observation": dict(observation),
        }
        return {**payload, "content_sha256": canonical_sha256(payload)}

    if partial or failed:
        tier_index = CAPACITY_TIERS.index(previous_width)
        capacity_tier = CAPACITY_TIERS[max(0, tier_index - 1)]
        reason = "DOWNSHIFT_AFTER_PARTIAL_OR_FAILURE"
    elif succeeded >= previous_width and queue_depth > previous_width:
        tier_index = CAPACITY_TIERS.index(previous_width)
        capacity_tier = CAPACITY_TIERS[min(len(CAPACITY_TIERS) - 1, tier_index + 1)]
        reason = "UPSHIFT_AFTER_FULL_SUCCESS"
    elif succeeded == 0 and failed == 0:
        capacity_tier = previous_width
        reason = "INITIAL_VERIFIED_CAPACITY"
    else:
        capacity_tier = previous_width
        reason = "HOLD_CURRENT_TIER"

    dispatch_width = min(capacity_tier, available_slots, ready_count)
    payload = {
        "schema_version": "xinao.dynamic_capacity_decision.v1",
        "policy_version": FACTORY_POLICY_VERSION,
        "capacity_tier": capacity_tier,
        "dispatch_width": dispatch_width,
        "reason": reason,
        "backpressure": dispatch_width < ready_count,
        "observation": dict(observation),
    }
    return {**payload, "content_sha256": canonical_sha256(payload)}


def deterministic_fan_in(
    lane_results: Sequence[Mapping[str, Any]],
    *,
    critiques: Sequence[Mapping[str, Any]],
    verifications: Sequence[Mapping[str, Any]],
    expected_work_keys: Sequence[str],
) -> dict[str, Any]:
    """Resolve an exact frontier through producer AND critic AND verifier evidence."""

    expected = list(expected_work_keys)
    if not expected or len(set(expected)) != len(expected):
        raise ValueError("expected_work_keys must be a nonempty exact set")

    def stage_identity(
        raw: Mapping[str, Any],
        *,
        ref_field: str,
        hash_field: str,
    ) -> dict[str, str]:
        values = {
            ref_field: str(raw.get(ref_field) or ""),
            hash_field: str(raw.get(hash_field) or ""),
            "temporal_workflow_id": str(raw.get("temporal_workflow_id") or ""),
            "temporal_run_id": str(raw.get("temporal_run_id") or ""),
            "lane_id": str(raw.get("lane_id") or ""),
            "provider_id": str(raw.get("provider_id") or ""),
            "model": str(raw.get("model") or ""),
        }
        if any(not value for value in values.values()) or not _is_sha256(values[hash_field]):
            raise ValueError("fan-in stage artifact or runtime identity is missing")
        return values

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    producer_ids: set[str] = set()
    for raw_value in lane_results:
        raw = ProducerStageEvidence.model_validate(raw_value).model_dump(mode="json")
        work_key = str(raw.get("work_key") or "")
        producer_id = str(raw.get("producer_id") or "")
        artifact_hash = str(raw.get("artifact_hash") or "")
        status = str(raw.get("status") or "").upper()
        if not work_key or not producer_id or len(artifact_hash) != 64:
            raise ValueError("lane result identity or artifact hash is missing")
        if work_key in seen:
            raise ValueError(f"duplicate work_key in fan-in: {work_key}")
        if status not in {"VERIFIED", "PARTIAL", "FAILED", "FALSIFIED", "NO_ACTION"}:
            raise ValueError(f"unsupported lane status: {status}")
        identity = stage_identity(
            raw,
            ref_field="artifact_ref",
            hash_field="artifact_hash",
        )
        seen.add(work_key)
        producer_ids.add(producer_id)
        normalized.append(
            {
                "work_key": work_key,
                "producer_id": producer_id,
                "status": status,
                "claim_refs": sorted({str(item) for item in raw.get("claim_refs", [])}),
                **identity,
            }
        )
    ordered = sorted(normalized, key=lambda item: item["work_key"])
    result_by_key = {item["work_key"]: item for item in ordered}
    if set(result_by_key) != set(expected):
        raise ValueError("producer work key set does not equal expected frontier")

    critique_by_key: dict[str, dict[str, Any]] = {}
    critic_ids: set[str] = set()
    for raw_value in critiques:
        raw = CritiqueStageEvidence.model_validate(raw_value).model_dump(mode="json")
        work_key = str(raw.get("work_key") or "")
        critic_id = str(raw.get("critic_id") or "")
        target_hash = str(raw.get("target_artifact_hash") or "")
        verdict = str(raw.get("verdict") or "").upper()
        if work_key in critique_by_key or work_key not in result_by_key:
            raise ValueError("critique work_key is duplicate or unknown")
        if not critic_id or verdict not in {"APPROVED", "CHANGES_REQUESTED", "REJECTED"}:
            raise ValueError("critique identity or verdict is invalid")
        if target_hash != result_by_key[work_key]["artifact_hash"]:
            raise ValueError("critique is not bound to the producer artifact")
        identity = stage_identity(
            raw,
            ref_field="critique_artifact_ref",
            hash_field="critique_artifact_hash",
        )
        critic_ids.add(critic_id)
        critique_by_key[work_key] = {
            "work_key": work_key,
            "critic_id": critic_id,
            "target_artifact_hash": target_hash,
            "verdict": verdict,
            "finding_refs": sorted({str(item) for item in raw.get("finding_refs", [])}),
            **identity,
        }

    verification_by_key: dict[str, dict[str, Any]] = {}
    verifier_ids: set[str] = set()
    for raw_value in verifications:
        raw = VerificationStageEvidence.model_validate(raw_value).model_dump(mode="json")
        work_key = str(raw.get("work_key") or "")
        verifier_id = str(raw.get("verifier_id") or "")
        target_hash = str(raw.get("target_artifact_hash") or "")
        verdict = str(raw.get("verdict") or "").upper()
        if work_key in verification_by_key or work_key not in result_by_key:
            raise ValueError("verification work_key is duplicate or unknown")
        if not verifier_id or verdict not in {"VERIFIED", "PARTIAL", "REJECTED"}:
            raise ValueError("verification identity or verdict is invalid")
        if target_hash != result_by_key[work_key]["artifact_hash"]:
            raise ValueError("verification is not bound to the producer artifact")
        critique_hash = str(raw.get("target_critique_hash") or "")
        if (
            work_key not in critique_by_key
            or critique_hash != critique_by_key[work_key]["critique_artifact_hash"]
        ):
            raise ValueError("verification is not bound to the critique artifact")
        identity = stage_identity(
            raw,
            ref_field="verification_artifact_ref",
            hash_field="verification_artifact_hash",
        )
        verifier_ids.add(verifier_id)
        verification_by_key[work_key] = {
            "work_key": work_key,
            "verifier_id": verifier_id,
            "target_artifact_hash": target_hash,
            "target_critique_hash": critique_hash,
            "verdict": verdict,
            "evidence_refs": sorted({str(item) for item in raw.get("evidence_refs", [])}),
            **identity,
        }

    if set(result_by_key) != set(critique_by_key) or set(result_by_key) != set(verification_by_key):
        raise ValueError("every producer artifact requires one critique and one verification")
    if producer_ids & critic_ids or producer_ids & verifier_ids or critic_ids & verifier_ids:
        raise ValueError("producer, critique, and verifier roles must be disjoint")

    resolved = [
        item
        for item in ordered
        if item["status"] in {"VERIFIED", "FALSIFIED", "NO_ACTION"}
        and critique_by_key[item["work_key"]]["verdict"] == "APPROVED"
        and verification_by_key[item["work_key"]]["verdict"] == "VERIFIED"
    ]
    resolved_keys = {item["work_key"] for item in resolved}
    accepted = [item for item in resolved if item["status"] == "VERIFIED"]
    terminal_nonpositive = [
        item for item in resolved if item["status"] in {"FALSIFIED", "NO_ACTION"}
    ]
    unresolved = [item for item in ordered if item["work_key"] not in resolved_keys]
    payload = {
        "schema_version": "xinao.deterministic_fan_in.v1",
        "policy_version": FACTORY_POLICY_VERSION,
        "ordered_results": ordered,
        "critiques": [critique_by_key[item["work_key"]] for item in ordered],
        "verifications": [verification_by_key[item["work_key"]] for item in ordered],
        "accepted_work_keys": [item["work_key"] for item in accepted],
        "resolved_work_keys": [item["work_key"] for item in resolved],
        "terminal_nonpositive_work_keys": [item["work_key"] for item in terminal_nonpositive],
        "unresolved_work_keys": [item["work_key"] for item in unresolved],
        "expected_work_keys": sorted(expected),
        "producer_ids": sorted(producer_ids),
        "critic_ids": sorted(critic_ids),
        "verifier_ids": sorted(verifier_ids),
        "majority_vote_used": False,
        "completion_status": "VERIFIED" if ordered and not unresolved else "PARTIAL",
    }
    return {**payload, "content_sha256": canonical_sha256(payload)}


def admit_open_method(
    value: Mapping[str, Any],
    *,
    resolved_content_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Admit any method whose pinned refs and canary resolve to their hashes."""

    registration = OpenMethodRegistration.model_validate(value)
    payload = registration.model_dump(mode="json")
    expected = {
        registration.executable_ref: registration.executable_sha256,
        registration.input_schema_ref: registration.input_schema_sha256,
        registration.output_schema_ref: registration.output_schema_sha256,
        registration.verification_protocol_ref: registration.verification_protocol_sha256,
        registration.failure_contract_ref: registration.failure_contract_sha256,
        registration.canary_evidence_ref: registration.canary_evidence_sha256,
    }
    if any(resolved_content_hashes.get(ref) != digest for ref, digest in expected.items()):
        raise ValueError("open method ref is missing or content hash drifted")
    core = {
        "schema_version": "xinao.open_method_admission.v1",
        "admitted": True,
        "registration": payload,
        "registration_sha256": canonical_sha256(payload),
        "method_whitelist_used": False,
        "resolved_ref_count": len(expected),
        "resolved_content_hashes": {ref: expected[ref] for ref in sorted(expected)},
    }
    return {**core, "admission_sha256": canonical_sha256(core)}


def _validate_method_admission(value: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Recompute one typed open-method admission artifact."""

    core = dict(value)
    admission_hash = str(core.pop("admission_sha256", ""))
    if not _is_sha256(admission_hash) or canonical_sha256(core) != admission_hash:
        raise ValueError("method admission content hash drifted")
    if (
        core.get("schema_version") != "xinao.open_method_admission.v1"
        or core.get("admitted") is not True
        or core.get("method_whitelist_used") is not False
    ):
        raise ValueError("method registry entry is not an admitted open method")
    registration = OpenMethodRegistration.model_validate(core.get("registration"))
    registration_payload = registration.model_dump(mode="json")
    registration_hash = canonical_sha256(registration_payload)
    if (
        core.get("registration") != registration_payload
        or core.get("registration_sha256") != registration_hash
    ):
        raise ValueError("method registration schema or hash drifted")
    expected = {
        registration.executable_ref: registration.executable_sha256,
        registration.input_schema_ref: registration.input_schema_sha256,
        registration.output_schema_ref: registration.output_schema_sha256,
        registration.verification_protocol_ref: registration.verification_protocol_sha256,
        registration.failure_contract_ref: registration.failure_contract_sha256,
        registration.canary_evidence_ref: registration.canary_evidence_sha256,
    }
    if core.get("resolved_content_hashes") != {
        ref: expected[ref] for ref in sorted(expected)
    } or core.get("resolved_ref_count") != len(expected):
        raise ValueError("method admission is not bound to every pinned ref")
    return registration_payload, admission_hash


def validate_method_registry(
    value: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Validate every registry entry even when the ready frontier is empty."""

    if not value:
        raise ValueError("verified method registry is empty")
    normalized: dict[str, dict[str, Any]] = {}
    for method_id, raw in sorted(value.items()):
        if not isinstance(raw, Mapping):
            raise TypeError("method registry entry must be an object")
        registration, admission_hash = _validate_method_admission(raw)
        if registration["method_id"] != method_id:
            raise ValueError("method registry key does not match registration method_id")
        normalized[method_id] = {
            "registration": registration,
            "registration_sha256": canonical_sha256(registration),
            "admission_sha256": admission_hash,
        }
    return normalized


def admit_work_item(
    item: ResearchWorkItem | Mapping[str, Any],
    *,
    selection_manifest: (IndependentExpectedSelectionDomainManifestVersion | Mapping[str, Any]),
    method_registry: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind a work item to an already verified open-method registration."""

    work = item if isinstance(item, ResearchWorkItem) else ResearchWorkItem.model_validate(item)
    manifest = (
        selection_manifest
        if isinstance(
            selection_manifest,
            IndependentExpectedSelectionDomainManifestVersion,
        )
        else IndependentExpectedSelectionDomainManifestVersion.model_validate(selection_manifest)
    )
    if work.selection_manifest_hash != manifest.content_hash:
        raise ValueError("work item selection manifest hash drifted")
    manifest_components = {
        baseline_id
        for specification in manifest.specifications
        for baseline_id in specification.component_baseline_ids
    }
    if not set(work.active_settlement_refs) <= manifest_components:
        raise ValueError("work item ACTIVE refs are not admitted by selection manifest")
    registry = validate_method_registry(method_registry)
    registration = registry.get(work.method_id)
    if registration is None:
        raise ValueError("work item method_id is not admitted")
    registration_hash = str(registration["registration_sha256"])
    if registration_hash != work.method_registration_hash:
        raise ValueError("work item method registration hash drifted")
    if registration["admission_sha256"] != work.method_admission_hash:
        raise ValueError("work item method admission hash drifted")
    registered_output_schema_ref = str(registration["registration"]["output_schema_ref"])
    if work.output_schema_ref != registered_output_schema_ref:
        raise ValueError("work item output schema is not the admitted method schema")
    return {
        "schema_version": "xinao.research_work_item_admission.v1",
        "admitted": True,
        "work_key": canonical_work_key(work),
        "method_registration_hash": registration_hash,
        "method_admission_hash": registration["admission_sha256"],
        "selection_manifest_hash": manifest.content_hash,
        "active_settlement_refs": list(work.active_settlement_refs),
    }


def admit_work_item_v3(
    item: ResearchWorkItemV3 | Mapping[str, Any],
    *,
    selection_manifest: (IndependentExpectedSelectionDomainManifestVersion | Mapping[str, Any]),
    method_registry: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Admit phase-qualified v3 work while retaining its execution authority."""

    work = (
        item if isinstance(item, ResearchWorkItemV3) else ResearchWorkItemV3.model_validate(item)
    )
    compatibility_payload = work.model_dump(mode="json")
    compatibility_payload.pop("execution_phase")
    compatibility_payload["schema_version"] = "xinao.research_work_item.v2"
    admission = admit_work_item(
        compatibility_payload,
        selection_manifest=selection_manifest,
        method_registry=method_registry,
    )
    return {
        **admission,
        "schema_version": "xinao.research_work_item_admission.v2",
        "work_item_schema_version": work.schema_version,
        "execution_phase": work.execution_phase,
        "work_key": canonical_work_key_v3(work),
    }


def admit_validation_court_request(
    request: ValidationCourtRequest | Mapping[str, Any],
    *,
    method_registry: Mapping[str, Mapping[str, Any]],
    error_budget_policy: ResearchErrorBudgetPolicy | Mapping[str, Any],
) -> ValidationCourtAdmission:
    """Admit one generic court request without instantiating a P5 protocol."""

    court_request = (
        request
        if isinstance(request, ValidationCourtRequest)
        else ValidationCourtRequest.model_validate(request)
    )
    registry = validate_method_registry(method_registry)
    registered = registry.get(court_request.method_id)
    if registered is None:
        raise ValueError("validation-court method is not admitted")
    if (
        registered["registration_sha256"] != court_request.method_registration_sha256
        or registered["admission_sha256"] != court_request.method_admission_sha256
    ):
        raise ValueError("validation-court method identity drifted")
    registration = registered["registration"]
    if (
        registration["verification_protocol_ref"] != court_request.protocol_artifact.ref
        or registration["verification_protocol_sha256"] != court_request.protocol_artifact.sha256
    ):
        raise ValueError("validation-court protocol is not the admitted method protocol")
    if (
        registration["output_schema_ref"] != court_request.result_schema.ref
        or registration["output_schema_sha256"] != court_request.result_schema.sha256
    ):
        raise ValueError("validation-court result schema is not the admitted method schema")

    policy = (
        error_budget_policy
        if isinstance(error_budget_policy, ResearchErrorBudgetPolicy)
        else ResearchErrorBudgetPolicy.model_validate(error_budget_policy)
    )
    policy_payload = policy.model_dump(mode="json")
    if (
        policy.policy_ref != court_request.error_budget_policy_ref
        or canonical_sha256(policy_payload) != court_request.error_budget_policy_sha256
    ):
        raise ValueError("validation-court error-budget policy identity drifted")
    decision = evaluate_error_budget(
        policy,
        hypotheses_in_family=court_request.hypotheses_in_family,
        confirmation_queries_used=court_request.confirmation_queries_used,
        negative_control_kinds=court_request.negative_control_kinds,
    )
    if decision["admitted"] is not True:
        raise ValueError("validation-court request exceeds its error budget")
    return ValidationCourtAdmission(
        request_sha256=court_request.content_hash,
        work_key=court_request.work_key,
        active_settlement_refs=court_request.active_settlement_refs,
        method_id=court_request.method_id,
        method_registration_sha256=court_request.method_registration_sha256,
        method_admission_sha256=court_request.method_admission_sha256,
        error_budget_decision_sha256=canonical_sha256(decision),
    )


def _research_factory_artifact_payloads() -> tuple[
    dict[str, dict[str, Any]], dict[str, dict[str, Any]]
]:
    """Build required and supporting payloads from their executable contracts."""

    from xinao.contracts import handoff as handoff_contract
    from xinao.foundation import selection_manifest as selection_contract
    from xinao.foundation.research_candidate_source import (
        compile_f4_canary_candidate_snapshot,
        compile_f4_canary_candidate_source,
    )
    from xinao.lineage.models import (
        EvidenceManifest,
        LineageIntent,
        build_lineage_intent,
    )

    compiler_source_sha256 = _callable_source_hash(_research_factory_artifact_payloads)
    canonical_profile_source_sha256 = {
        "canonical_dumps": _callable_source_hash(canonical_dumps),
        "canonical_sha256": _callable_source_hash(canonical_sha256),
        "to_json_value": _callable_source_hash(to_json_value),
    }
    handoff_model_names = (
        "PayloadBase",
        "IntentPayload",
        "QuestionPayload",
        "DecisionPayload",
        "TaskPayload",
        "ClaimPayload",
        "EvidencePayload",
        "ArtifactPayload",
        "ReviewPayload",
        "BlockerPayload",
        "StopPayload",
        "ResumePayload",
        "ResearchQuestionPayload",
        "EvidenceBundlePayload",
        "CandidateProposalPayload",
        "CritiquePayload",
        "VerificationResultPayload",
        "HandoffMessage",
    )
    handoff_models = {name: getattr(handoff_contract, name) for name in handoff_model_names}
    HandoffMessage = handoff_contract.HandoffMessage
    handoff_schema = HandoffMessage.model_json_schema()
    work_item_schema = ResearchWorkItem.model_json_schema()
    evidence_contract = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "models": {
            "LineageIntent": LineageIntent.model_json_schema(),
            "EvidenceManifest": EvidenceManifest.model_json_schema(),
            "ProducerStageEvidence": ProducerStageEvidence.model_json_schema(),
            "CritiqueStageEvidence": CritiqueStageEvidence.model_json_schema(),
            "VerificationStageEvidence": VerificationStageEvidence.model_json_schema(),
        },
        "model_source_sha256": {
            "LineageIntent": _callable_source_hash(LineageIntent),
            "EvidenceManifest": _callable_source_hash(EvidenceManifest),
            "ProducerStageEvidence": _callable_source_hash(ProducerStageEvidence),
            "CritiqueStageEvidence": _callable_source_hash(CritiqueStageEvidence),
            "VerificationStageEvidence": _callable_source_hash(VerificationStageEvidence),
        },
        "builder_source_sha256": _callable_source_hash(build_lineage_intent),
        "canonical_profile_source_sha256": canonical_profile_source_sha256,
    }
    validation_models = {
        model.__name__: model
        for model in (
            CourtArtifactBinding,
            CourtFeatureObservation,
            CourtWalkForwardFold,
            CourtNegativeControlEvidence,
            ValidationCourtRequest,
            ValidationCourtAdmission,
            ValidationCourtResult,
        )
    }
    validation_interface = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "interface_kind": "GENERIC_TYPED_COURT_NO_ACTIVE_DOMAIN_INSTANCE",
        "schemas": {name: model.model_json_schema() for name, model in validation_models.items()},
        "model_source_sha256": {
            name: _callable_source_hash(model) for name, model in validation_models.items()
        },
        "callable_source_sha256": {
            "admit_validation_court_request": _callable_source_hash(admit_validation_court_request),
            "verify_validation_court_result": _callable_source_hash(verify_validation_court_result),
        },
        "active_identity_partition_sha256": canonical_sha256(
            {
                "active": sorted(ACTIVE_SETTLEMENT_BASELINE_IDS),
                "frozen": sorted(FROZEN_ROUTE_QUOTE_BASELINE_IDS),
            }
        ),
        "canonical_profile_source_sha256": canonical_profile_source_sha256,
        "invariants": [
            *COURT_ADMISSION_INVARIANTS,
            "NEGATIVE_CONTROL_EVIDENCE_EXACTLY_MATCHES_REQUEST",
            "RESULT_BINDS_REQUEST_AND_ADMISSION",
            "VERIFIED_FALSIFIED_AND_NO_ACTION_ARE_TERMINAL_RESULTS",
        ],
    }
    dynamic_capacity_policy = {
        "policy_version": FACTORY_POLICY_VERSION,
        "capacity_tiers": list(CAPACITY_TIERS),
        "maximum_width": CAPACITY_TIERS[-1],
        "inputs": [
            "available_slots",
            "failed",
            "host_state",
            "partial",
            "previous_width",
            "queue_depth",
            "ready_count",
            "succeeded",
        ],
        "invariants": [
            "DISPATCH_WIDTH_LTE_AVAILABLE_SLOTS",
            "DISPATCH_WIDTH_LTE_READY_COUNT",
            "NO_DISPATCH_WHEN_HOST_UNAVAILABLE",
            "DOWNSHIFT_AFTER_PARTIAL_OR_FAILURE",
            "UPSHIFT_ONLY_AFTER_FULL_SUCCESS",
        ],
        "implementation_ref": ("xinao.foundation.research_factory.select_dynamic_capacity"),
        "implementation_sha256": {
            "select_dynamic_capacity": _callable_source_hash(select_dynamic_capacity),
            "tier_at_or_below": _callable_source_hash(_tier_at_or_below),
        },
        "canonical_profile_source_sha256": canonical_profile_source_sha256,
    }
    dedup_policy = {
        "policy_version": FACTORY_POLICY_VERSION,
        "identity_fields": [
            "physical_role",
            "active_settlement_refs",
            "kind",
            "source_origin",
            "source_dependency_origins",
            "source_projection_hash",
            "intent_slice",
            "selection_manifest_hash",
            "method_id",
            "method_registration_hash",
            "method_admission_hash",
            "world_snapshot_hash",
            "input_snapshot_hashes",
        ],
        "active_identity_projection_sha256": canonical_sha256(
            {
                "active": sorted(ACTIVE_SETTLEMENT_BASELINE_IDS),
                "frozen": sorted(FROZEN_ROUTE_QUOTE_BASELINE_IDS),
            }
        ),
        "research_work_item_source_sha256": _callable_source_hash(ResearchWorkItem),
        "invariants": [
            "KNOWN_MIRRORS_COLLAPSE_BY_ORIGIN_CLUSTER_ONLY",
            "LINEAGE_EDGE_DOES_NOT_IMPLY_SOURCE_EQUIVALENCE",
            "UNSATISFIED_UPSTREAM_WORK_IS_DEFERRED",
            "CLOSED_OR_IN_FLIGHT_WORK_IS_NOT_REDISPATCHED",
            "F3_SURFACE_CANARY_SOURCE_COVERS_EXACT_13_FAMILIES",
            "STRICT_FRONTIER_FORBIDS_CALLER_READY_AUTHORITY",
            "STRICT_READY_ORDER_EQUALS_FROZEN_PORTFOLIO_ALLOCATION",
            "ALLOCATED_READY_FRONTIER_FILTERS_WITHOUT_REORDER",
            "LEGACY_DEDUP_ORDER_CANNOT_SATISFY_PORTFOLIO_ASSERTION",
            "FROZEN_QUOTE_IDENTITY_NEVER_CREATES_WORK",
        ],
        "implementation_sha256": {
            "canonical_work_key": _callable_source_hash(canonical_work_key),
            "compile_f4_canary_candidate_source": _callable_source_hash(
                compile_f4_canary_candidate_source
            ),
            "compile_f4_canary_candidate_snapshot": _callable_source_hash(
                compile_f4_canary_candidate_snapshot
            ),
            "compile_research_candidate_snapshot": _callable_source_hash(
                compile_research_candidate_snapshot
            ),
            "compile_research_portfolio_allocation": _callable_source_hash(
                compile_research_portfolio_allocation
            ),
            "dedupe_ready_frontier": _callable_source_hash(dedupe_ready_frontier),
            "project_allocated_ready_frontier": _callable_source_hash(
                project_allocated_ready_frontier
            ),
            "source_origin_index": _callable_source_hash(source_origin_index),
            "source_projection_hash": _callable_source_hash(source_projection_hash),
            "verify_versioned_object": _callable_source_hash(verify_versioned_object),
        },
        "canonical_profile_source_sha256": canonical_profile_source_sha256,
    }
    fan_in_policy = {
        "policy_version": FACTORY_POLICY_VERSION,
        "stages": ["PRODUCER", "CRITIQUE", "VERIFIER"],
        "terminal_positive_statuses": ["VERIFIED"],
        "terminal_nonpositive_statuses": ["FALSIFIED", "NO_ACTION"],
        "invariants": [
            "EXPECTED_WORK_KEY_SET_MUST_MATCH_EXACTLY",
            "ONE_ARTIFACT_PER_STAGE_PER_WORK_KEY",
            "CRITIQUE_BINDS_PRODUCER_ARTIFACT_HASH",
            "VERIFICATION_BINDS_PRODUCER_AND_CRITIQUE_HASHES",
            "PRODUCER_CRITIQUE_VERIFIER_IDENTITIES_ARE_DISJOINT",
            "UNRESOLVED_WORK_REMAINS_PARTIAL",
            "MAJORITY_VOTE_IS_NEVER_USED",
        ],
        "implementation_ref": "xinao.foundation.research_factory.deterministic_fan_in",
        "implementation_sha256": {
            "deterministic_fan_in": _callable_source_hash(deterministic_fan_in),
            "is_sha256": _callable_source_hash(_is_sha256),
            "producer_model": _callable_source_hash(ProducerStageEvidence),
            "critique_model": _callable_source_hash(CritiqueStageEvidence),
            "verification_model": _callable_source_hash(VerificationStageEvidence),
        },
        "canonical_profile_source_sha256": canonical_profile_source_sha256,
    }

    required = {
        "TypedHandoffSchemaVersion": {
            "schema_version": "xinao.typed_handoff_schema.v1",
            "schema": handoff_schema,
            "schema_sha256": canonical_sha256(handoff_schema),
            "model_source_sha256": {
                name: _callable_source_hash(model) for name, model in handoff_models.items()
            },
            "helper_source_sha256": {
                "format_utc": _callable_source_hash(format_utc),
                "is_uuid7": _callable_source_hash(is_uuid7),
                "require_uuid7": _callable_source_hash(require_uuid7),
            },
            "compiler_source_sha256": compiler_source_sha256,
        },
        "EvidenceSchemaVersion": {
            "schema_version": "xinao.research_evidence_schema.v1",
            "schema": evidence_contract,
            "schema_sha256": canonical_sha256(evidence_contract),
            "compiler_source_sha256": compiler_source_sha256,
        },
        "ValidationCourtInterfaceVersion": {
            "schema_version": "xinao.validation_court_interface.v2",
            "interface": validation_interface,
            "interface_sha256": canonical_sha256(validation_interface),
            "compiler_source_sha256": compiler_source_sha256,
        },
        "ResearchWorkItemSchemaVersion": {
            "schema_version": "xinao.research_work_item_schema.v2",
            "schema": work_item_schema,
            "schema_sha256": canonical_sha256(work_item_schema),
            "model_source_sha256": _callable_source_hash(ResearchWorkItem),
            "implementation_source_sha256": {
                "admit_open_method": _callable_source_hash(admit_open_method),
                "admit_work_item": _callable_source_hash(admit_work_item),
                "canonical_work_key": _callable_source_hash(canonical_work_key),
                "open_method_registration": _callable_source_hash(OpenMethodRegistration),
                "validate_method_admission": _callable_source_hash(_validate_method_admission),
                "validate_method_registry": _callable_source_hash(validate_method_registry),
            },
            "selection_binding_source_sha256": {
                "content_hashed_model": _callable_source_hash(
                    selection_contract._ContentHashedModel
                ),
                "selection_canonical_sha256": _callable_source_hash(
                    selection_contract.canonical_sha256
                ),
                "manifest_model": _callable_source_hash(
                    IndependentExpectedSelectionDomainManifestVersion
                ),
                "selection_domain_spec_model": _callable_source_hash(
                    selection_contract.IndependentSelectionDomainSpec
                ),
                "active_catalog_projection_hash": _callable_source_hash(
                    active_catalog_projection_hash
                ),
                "classify_catalog_physical_roles": _callable_source_hash(
                    classify_catalog_physical_roles
                ),
            },
            "selection_binding_value_sha256": {
                "expected_active_family_counts": canonical_sha256(
                    selection_contract.EXPECTED_ACTIVE_FAMILY_COUNTS
                ),
            },
            "active_identity_partition_sha256": canonical_sha256(
                {
                    "active": sorted(ACTIVE_SETTLEMENT_BASELINE_IDS),
                    "frozen": sorted(FROZEN_ROUTE_QUOTE_BASELINE_IDS),
                }
            ),
            "compiler_source_sha256": compiler_source_sha256,
        },
        "DynamicCapacityPolicyVersion": {
            "schema_version": "xinao.dynamic_capacity_policy.v1",
            "policy": dynamic_capacity_policy,
            "policy_sha256": canonical_sha256(dynamic_capacity_policy),
            "compiler_source_sha256": compiler_source_sha256,
        },
        "DedupPolicyVersion": {
            "schema_version": "xinao.research_dedup_policy.v2",
            "policy": dedup_policy,
            "policy_sha256": canonical_sha256(dedup_policy),
            "compiler_source_sha256": compiler_source_sha256,
        },
        "DeterministicFanInPolicyVersion": {
            "schema_version": "xinao.deterministic_fan_in_policy.v1",
            "policy": fan_in_policy,
            "policy_sha256": canonical_sha256(fan_in_policy),
            "compiler_source_sha256": compiler_source_sha256,
        },
    }
    open_method_schema = OpenMethodRegistration.model_json_schema()
    error_budget_schema = ResearchErrorBudgetPolicy.model_json_schema()
    supporting = {
        "OpenMethodRegistrationSchemaVersion": {
            "schema_version": "xinao.open_method_registration_schema.v1",
            "schema": open_method_schema,
            "schema_sha256": canonical_sha256(open_method_schema),
            "model_source_sha256": _callable_source_hash(OpenMethodRegistration),
            "admission_source_sha256": _callable_source_hash(admit_open_method),
        },
        "ResearchErrorBudgetPolicySchemaVersion": {
            "schema_version": "xinao.research_error_budget_policy_schema.v1",
            "schema": error_budget_schema,
            "schema_sha256": canonical_sha256(error_budget_schema),
            "model_source_sha256": _callable_source_hash(ResearchErrorBudgetPolicy),
            "evaluation_source_sha256": _callable_source_hash(evaluate_error_budget),
        },
    }
    return required, supporting


def research_factory_schema_payloads() -> dict[str, dict[str, Any]]:
    """Compile exactly the seven blueprint-required executable F4 artifacts."""

    required, _ = _research_factory_artifact_payloads()
    if tuple(required) != F4_REQUIRED_ARTIFACT_TYPES:
        raise AssertionError("required F4 artifact inventory drifted")
    return {
        object_type: _finalize_factory_artifact(object_type, payload)
        for object_type, payload in required.items()
    }


def research_factory_schema_payloads_v3() -> dict[str, dict[str, Any]]:
    """Compile the phase-qualified F4 contracts without rewriting v2 history."""

    from xinao.foundation.research_candidate_source import (
        _payload_without_version_identity,
        compile_f4_canary_candidate_snapshot,
        compile_f4_canary_candidate_snapshot_v3,
        compile_f4_canary_candidate_source,
        compile_f4_canary_candidate_source_v3,
    )

    artifacts = research_factory_schema_payloads()
    compiler_source_sha256 = _callable_source_hash(research_factory_schema_payloads_v3)

    work_item_artifact = artifacts["ResearchWorkItemSchemaVersion"]
    work_item_payload = {
        key: value
        for key, value in work_item_artifact.items()
        if key not in {"object_type", "artifact_schema_version", "version_id", "content_sha256"}
    }
    work_item_schema = ResearchWorkItemV3.model_json_schema()
    work_item_payload.update(
        {
            "schema_version": "xinao.research_work_item_schema.v3",
            "schema": work_item_schema,
            "schema_sha256": canonical_sha256(work_item_schema),
            "model_source_sha256": _callable_source_hash(ResearchWorkItemV3),
            "base_v2_artifact_content_sha256": work_item_artifact["content_sha256"],
            "compiler_source_sha256": compiler_source_sha256,
        }
    )
    implementation_hashes = dict(work_item_payload["implementation_source_sha256"])
    implementation_hashes.pop("admit_work_item")
    implementation_hashes.pop("canonical_work_key")
    implementation_hashes.update(
        {
            "admit_work_item_v3": _callable_source_hash(admit_work_item_v3),
            "base_admit_work_item_v2": _callable_source_hash(admit_work_item),
            "canonical_work_key_v3": _callable_source_hash(canonical_work_key_v3),
        }
    )
    implementation_hashes["parse_research_work_item"] = _callable_source_hash(
        parse_research_work_item
    )
    work_item_payload["implementation_source_sha256"] = implementation_hashes

    dedup_artifact = artifacts["DedupPolicyVersion"]
    dedup_payload = {
        key: value
        for key, value in dedup_artifact.items()
        if key not in {"object_type", "artifact_schema_version", "version_id", "content_sha256"}
    }
    dedup_policy = dict(dedup_payload["policy"])
    identity_fields = list(dedup_policy["identity_fields"])
    identity_fields.insert(1, "execution_phase")
    legacy_portfolio_invariants = {
        "STRICT_READY_ORDER_EQUALS_FROZEN_PORTFOLIO_ALLOCATION",
        "ALLOCATED_READY_FRONTIER_FILTERS_WITHOUT_REORDER",
        "LEGACY_DEDUP_ORDER_CANNOT_SATISFY_PORTFOLIO_ASSERTION",
    }
    dedup_policy.update(
        {
            "identity_fields": identity_fields,
            "research_work_item_source_sha256": _callable_source_hash(ResearchWorkItemV3),
            "invariants": [
                *(
                    invariant
                    for invariant in dedup_policy["invariants"]
                    if invariant not in legacy_portfolio_invariants
                ),
                "CONSTRUCTION_AND_AUTONOMOUS_RESEARCH_IDENTITIES_NEVER_COLLIDE",
                "EXPECTED_EXECUTION_PHASE_IS_REQUIRED",
            ],
        }
    )
    implementation_hashes = dict(dedup_policy["implementation_sha256"])
    for legacy_key in (
        "canonical_work_key",
        "compile_f4_canary_candidate_source",
        "compile_f4_canary_candidate_snapshot",
        "compile_research_candidate_snapshot",
        "compile_research_portfolio_allocation",
        "dedupe_ready_frontier",
        "project_allocated_ready_frontier",
    ):
        implementation_hashes.pop(legacy_key)
    implementation_hashes.update(
        {
            "base_compile_f4_canary_candidate_source_v2": _callable_source_hash(
                compile_f4_canary_candidate_source
            ),
            "base_compile_f4_canary_candidate_snapshot_v2": _callable_source_hash(
                compile_f4_canary_candidate_snapshot
            ),
            "candidate_version_adapter": _callable_source_hash(
                _payload_without_version_identity
            ),
            "canonical_work_key_v3": _callable_source_hash(canonical_work_key_v3),
            "compile_f4_canary_candidate_source_v3": _callable_source_hash(
                compile_f4_canary_candidate_source_v3
            ),
            "compile_f4_canary_candidate_snapshot_v3": _callable_source_hash(
                compile_f4_canary_candidate_snapshot_v3
            ),
            "dedupe_ready_frontier_v3": _callable_source_hash(dedupe_ready_frontier_v3),
        }
    )
    implementation_hashes["parse_research_work_item"] = _callable_source_hash(
        parse_research_work_item
    )
    dedup_policy["implementation_sha256"] = implementation_hashes
    dedup_payload.update(
        {
            "schema_version": "xinao.research_dedup_policy.v3",
            "policy": dedup_policy,
            "policy_sha256": canonical_sha256(dedup_policy),
            "base_v2_artifact_content_sha256": dedup_artifact["content_sha256"],
            "compiler_source_sha256": compiler_source_sha256,
        }
    )

    artifacts["ResearchWorkItemSchemaVersion"] = _finalize_factory_artifact(
        "ResearchWorkItemSchemaVersion",
        work_item_payload,
    )
    artifacts["DedupPolicyVersion"] = _finalize_factory_artifact(
        "DedupPolicyVersion",
        dedup_payload,
    )
    return artifacts


def research_factory_supporting_payloads() -> dict[str, dict[str, Any]]:
    """Compile non-gate schemas used to prove open admission and error budgets."""

    _, supporting = _research_factory_artifact_payloads()
    return {
        object_type: _finalize_factory_artifact(object_type, payload)
        for object_type, payload in supporting.items()
    }


def research_factory_artifact_manifest(
    artifacts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create the exact current seven-artifact inventory manifest."""

    values = dict(research_factory_schema_payloads() if artifacts is None else artifacts)
    if set(values) != set(F4_REQUIRED_ARTIFACT_TYPES):
        raise ValueError("F4 artifact set does not equal the required inventory")
    hashes: dict[str, str] = {}
    versions: dict[str, str] = {}
    for artifact_type in F4_REQUIRED_ARTIFACT_TYPES:
        value = values[artifact_type]
        if not verify_versioned_object(value) or value.get("object_type") != artifact_type:
            raise ValueError(f"F4 artifact is not content-addressed: {artifact_type}")
        hashes[artifact_type] = str(value["content_sha256"])
        versions[artifact_type] = str(value["version_id"])
    bundle_sha256 = canonical_sha256(
        {
            "required_artifact_types": list(F4_REQUIRED_ARTIFACT_TYPES),
            "artifact_versions": versions,
            "artifact_content_sha256": hashes,
        }
    )
    return _finalize_factory_artifact(
        "ResearchFactoryArtifactManifestVersion",
        {
            "schema_version": "xinao.research_factory_artifact_manifest.v1",
            "required_artifact_types": list(F4_REQUIRED_ARTIFACT_TYPES),
            "artifact_versions": versions,
            "artifact_content_sha256": hashes,
            "bundle_sha256": bundle_sha256,
        },
    )


def _verify_research_factory_artifacts(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    current: Mapping[str, Mapping[str, Any]],
    profile: Literal["V2", "V3"],
    pinned_manifest: Mapping[str, Any] | None = None,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Reject self-consistent stale/rehashed artifacts that differ from current code."""

    current = dict(current)
    if set(current) != set(F4_REQUIRED_ARTIFACT_TYPES):
        raise ValueError("current F4 artifact set does not equal the required inventory")
    if set(artifacts) != set(F4_REQUIRED_ARTIFACT_TYPES):
        raise ValueError("F4 artifact set does not equal the required inventory")
    mismatches: list[str] = []
    for artifact_type in F4_REQUIRED_ARTIFACT_TYPES:
        candidate = artifacts[artifact_type]
        if not verify_versioned_object(candidate):
            mismatches.append(f"{artifact_type}:INVALID_CONTENT_IDENTITY")
        elif dict(candidate) != current[artifact_type]:
            mismatches.append(f"{artifact_type}:STALE_OR_NOT_CURRENT_GENERATOR")
    if mismatches:
        raise ValueError(";".join(mismatches))
    manifest = research_factory_artifact_manifest(artifacts)
    if pinned_manifest is not None and (
        not verify_versioned_object(pinned_manifest)
        or pinned_manifest.get("object_type") != "ResearchFactoryArtifactManifestVersion"
        or dict(pinned_manifest) != manifest
    ):
        raise ValueError("pinned F4 artifact manifest does not match current code")
    if expected_manifest_sha256 is not None and (
        not _is_sha256(expected_manifest_sha256)
        or manifest["content_sha256"] != expected_manifest_sha256
    ):
        raise ValueError("current F4 artifact manifest does not match external pin")
    result = {
        "schema_version": "xinao.research_factory_artifact_verification.v1",
        "ok": True,
        "required_artifact_types": list(F4_REQUIRED_ARTIFACT_TYPES),
        "current_generator_match": True,
        "manifest": manifest,
        "manifest_content_sha256": manifest["content_sha256"],
    }
    if profile == "V3":
        result["profile"] = profile
    return result


def verify_research_factory_artifacts(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    pinned_manifest: Mapping[str, Any] | None = None,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify the historical v2 profile against its current executable generator."""

    return _verify_research_factory_artifacts(
        artifacts,
        current=research_factory_schema_payloads(),
        profile="V2",
        pinned_manifest=pinned_manifest,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def verify_research_factory_artifacts_v3(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    pinned_manifest: Mapping[str, Any] | None = None,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify phase-qualified v3 artifacts without caller-supplied truth."""

    return _verify_research_factory_artifacts(
        artifacts,
        current=research_factory_schema_payloads_v3(),
        profile="V3",
        pinned_manifest=pinned_manifest,
        expected_manifest_sha256=expected_manifest_sha256,
    )


__all__ = [
    "CAPACITY_TIERS",
    "F4_REQUIRED_ARTIFACT_TYPES",
    "FACTORY_POLICY_VERSION",
    "CritiqueStageEvidence",
    "OpenMethodRegistration",
    "ProducerStageEvidence",
    "ResearchErrorBudgetPolicy",
    "ResearchWorkItem",
    "ResearchWorkItemLike",
    "ResearchWorkItemV3",
    "VerificationStageEvidence",
    "admit_open_method",
    "admit_validation_court_request",
    "admit_work_item",
    "admit_work_item_v3",
    "canonical_work_key",
    "canonical_work_key_v3",
    "compile_research_candidate_snapshot",
    "compile_research_portfolio_allocation",
    "dedupe_ready_frontier",
    "dedupe_ready_frontier_v3",
    "deterministic_fan_in",
    "evaluate_error_budget",
    "finalize_research_candidate_question",
    "parse_research_work_item",
    "project_allocated_ready_frontier",
    "research_factory_artifact_manifest",
    "research_factory_schema_payloads",
    "research_factory_schema_payloads_v3",
    "research_factory_supporting_payloads",
    "select_dynamic_capacity",
    "source_origin_index",
    "source_projection_hash",
    "validate_method_registry",
    "verify_research_factory_artifacts",
    "verify_research_factory_artifacts_v3",
]
