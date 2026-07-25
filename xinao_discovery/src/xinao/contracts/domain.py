"""Registry and generated schemas for every first-class Xinao domain object."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from .common import CommonEnvelope

COMMON_INVARIANTS = (
    "semantic_change_creates_a_new_id_or_version",
    "state_changes_only_through_domain_events",
    "source_code_config_rule_and_evidence_lineage_is_recoverable",
    "failure_and_negative_results_are_never_deleted",
)
DEFAULT_MIGRATION = "create_new_version_preserve_prior_and_link_supersession"


@dataclass(frozen=True, slots=True)
class ReferenceSpec:
    field: str
    target: str


@dataclass(frozen=True, slots=True)
class DomainObjectSpec:
    name: str
    description: str
    owner: str
    references: tuple[ReferenceSpec, ...] = ()
    invariants: tuple[str, ...] = COMMON_INVARIANTS
    migration: str = DEFAULT_MIGRATION


def _refs(**values: str) -> tuple[ReferenceSpec, ...]:
    return tuple(ReferenceSpec(field=field, target=target) for field, target in values.items())


DOMAIN_OBJECT_SPECS = (
    DomainObjectSpec(
        "AuthorityContract",
        "Authoritative source contract",
        "User Direction/Source Verifier",
    ),
    DomainObjectSpec(
        "SourceIdentity",
        "Stable source identity and scope",
        "Source Verifier",
        _refs(authority_contract_ref="AuthorityContract"),
    ),
    DomainObjectSpec(
        "SourceSnapshot",
        "Raw response capture, hash, and parser identity",
        "Source Ingest",
        _refs(source_identity_ref="SourceIdentity"),
    ),
    DomainObjectSpec(
        "SourceVerification",
        "Source and snapshot verdict",
        "Source Verifier",
        _refs(source_snapshot_ref="SourceSnapshot"),
    ),
    DomainObjectSpec(
        "DatasetSnapshot",
        "Normalized fixed-range dataset version",
        "Source Verifier",
        _refs(authority_contract_ref="AuthorityContract", source_snapshot_ref="SourceSnapshot"),
    ),
    DomainObjectSpec(
        "BaselineOddsWaterVersion",
        "Default reference value coordinate version",
        "Domain Compiler",
        _refs(dataset_ref="DatasetSnapshot"),
    ),
    DomainObjectSpec(
        "PlayCatalogVersion",
        "Play, market, and option catalog",
        "Domain Compiler",
        _refs(baseline_ref="BaselineOddsWaterVersion"),
    ),
    DomainObjectSpec(
        "PlayFamilyVersion",
        "Settlement-structure family",
        "Domain Compiler",
        _refs(catalog_ref="PlayCatalogVersion"),
    ),
    DomainObjectSpec(
        "RuleVersion",
        "Rules, tiers, rounding, and effective period",
        "Domain Compiler",
        _refs(play_family_ref="PlayFamilyVersion"),
    ),
    DomainObjectSpec(
        "SettlementFunctionVersion",
        "Executable pure settlement function and tests",
        "Domain Compiler",
        _refs(rule_ref="RuleVersion"),
    ),
    DomainObjectSpec(
        "RuleSemanticMapVersion",
        "All catalog rows bound to parameterized settlement semantics",
        "Domain Compiler",
        _refs(catalog_ref="PlayCatalogVersion", family_ref="PlayFamilyVersion"),
    ),
    DomainObjectSpec(
        "ExpectedSelectionDomainManifestVersion",
        "Independent expected selection domain derived before rule compilation",
        "Independent Verifier",
        _refs(catalog_ref="PlayCatalogVersion", baseline_ref="BaselineOddsWaterVersion"),
    ),
    DomainObjectSpec(
        "RuleSetVersion",
        "Versioned complete rule set for the current catalog",
        "Domain Compiler",
        _refs(semantic_map_ref="RuleSemanticMapVersion"),
    ),
    DomainObjectSpec(
        "SettlementFunctionSetVersion",
        "Versioned registry of parameterized settlement functions",
        "Domain Compiler",
        _refs(rule_set_ref="RuleSetVersion"),
    ),
    DomainObjectSpec(
        "QuoteVersion",
        "The single ACTIVE A/default-highest issuer settlement price coordinate",
        "Domain Compiler",
        _refs(baseline_ref="BaselineOddsWaterVersion"),
    ),
    DomainObjectSpec(
        "SettlementProbabilitySnapshotVersion",
        "Exact theoretical settlement-tier probabilities",
        "Domain Compiler",
        _refs(rule_set_ref="RuleSetVersion"),
    ),
    DomainObjectSpec(
        "RebateScheduleVersion",
        (
            "Effective-turnover rebate schedule for ACTIVE settlement objects, "
            "separated from result payout"
        ),
        "Domain Compiler",
        _refs(catalog_ref="PlayCatalogVersion", active_quote_ref="QuoteVersion"),
    ),
    DomainObjectSpec(
        "SettlementCostSurfaceVersion",
        "Event payout and expected unit cost surface over the single ACTIVE issuer quote",
        "Domain Compiler",
        _refs(
            probability_ref="SettlementProbabilitySnapshotVersion",
            rebate_ref="RebateScheduleVersion",
            active_quote_ref="QuoteVersion",
        ),
    ),
    DomainObjectSpec(
        "OddsSpaceBenchmarkVersion",
        "Structural unit-margin and feasible price benchmark",
        "Domain Compiler",
        _refs(cost_surface_ref="SettlementCostSurfaceVersion"),
    ),
    DomainObjectSpec(
        "SettlementCostCompileReport",
        "Recomputable trace from rule, probability, quote, and rebate to unit cost",
        "Independent Verifier",
        _refs(cost_surface_ref="SettlementCostSurfaceVersion"),
    ),
    DomainObjectSpec(
        "EventMatrixSnapshot",
        "Dataset and rule event matrix",
        "Domain Compiler",
        _refs(
            dataset_ref="DatasetSnapshot",
            catalog_ref="PlayCatalogVersion",
            rule_ref="RuleVersion",
        ),
    ),
    DomainObjectSpec(
        "WorldSnapshot",
        "Complete research-visible world",
        "Domain Compiler",
        _refs(event_matrix_ref="EventMatrixSnapshot"),
    ),
    DomainObjectSpec(
        "FeatureSnapshot",
        "Point-in-time feature version",
        "Research Workflow",
        _refs(world_ref="WorldSnapshot"),
    ),
    DomainObjectSpec(
        "BeliefStateSnapshot",
        "Versioned beliefs and uncertainty over mechanisms and parameters",
        "Research Workflow",
        _refs(world_ref="WorldSnapshot"),
    ),
    DomainObjectSpec(
        "ResearchAttentionPriorVersion",
        "Qualitative or measured attention prior with explicit identity",
        "Research Portfolio",
        _refs(catalog_ref="PlayCatalogVersion"),
    ),
    DomainObjectSpec(
        "ResearchWeightBaselineVersion",
        "Deterministic baseline allocation of research resources",
        "Research Portfolio",
        _refs(
            attention_prior_ref="ResearchAttentionPriorVersion",
            cost_surface_ref="SettlementCostSurfaceVersion",
        ),
    ),
    DomainObjectSpec(
        "ActiveResearchSurfaceVersion",
        "ACTIVE, WATCH, TAIL, and DORMANT research-resource surface",
        "Research Portfolio",
        _refs(weight_baseline_ref="ResearchWeightBaselineVersion"),
    ),
    DomainObjectSpec(
        "ResearchPortfolioPolicyVersion",
        "Dynamic evidence-value allocation and exploration policy",
        "Research Portfolio",
        _refs(active_surface_ref="ActiveResearchSurfaceVersion"),
    ),
    DomainObjectSpec(
        "ResearchPortfolioAllocation",
        "Episode-frozen research budget and candidate allocation",
        "Research Portfolio",
        _refs(
            policy_ref="ResearchPortfolioPolicyVersion",
            active_surface_ref="ActiveResearchSurfaceVersion",
        ),
    ),
    DomainObjectSpec(
        "SourceDependencyGraphVersion",
        "Versioned source-copy and independence graph",
        "Source Verifier",
    ),
    DomainObjectSpec(
        "ContentServiceGraphVersion",
        "Versioned map from public content to served play families",
        "Research Portfolio",
        _refs(source_dependency_ref="SourceDependencyGraphVersion"),
    ),
    DomainObjectSpec(
        "DecisionRegretReport",
        "Ex-ante-information policy loss and choice-regret report",
        "Independent Verifier",
        _refs(allocation_ref="ResearchPortfolioAllocation"),
    ),
    DomainObjectSpec(
        "FoundationClosureReport",
        "Derived F1-F4 closure verdict and the only formal research gate",
        "Independent Verifier",
        _refs(
            world_ref="WorldSnapshot",
            cost_surface_ref="SettlementCostSurfaceVersion",
            research_weight_ref="ResearchWeightBaselineVersion",
            workflow_ref="WorkflowRun",
        ),
    ),
    DomainObjectSpec("ArtifactRef", "Content-addressed artifact reference", "Artifact Store"),
    DomainObjectSpec(
        "ResearchQuestion",
        "Research gap, information gain, and budget",
        "Research Workflow",
        _refs(world_ref="WorldSnapshot"),
    ),
    DomainObjectSpec(
        "EvidenceBundle",
        "Claims, evidence, contradictions, and limits",
        "Research Workflow",
        _refs(question_ref="ResearchQuestion"),
    ),
    DomainObjectSpec(
        "HypothesisSpec",
        "Falsifiable proposition and invalidation conditions",
        "Research Workflow",
        _refs(question_ref="ResearchQuestion"),
    ),
    DomainObjectSpec(
        "ExperimentSpec",
        "Data, world, algorithm, seed, protocol, and budget",
        "Research Workflow",
        _refs(hypothesis_ref="HypothesisSpec", world_ref="WorldSnapshot"),
    ),
    DomainObjectSpec(
        "Finding",
        "Result and boundary under a fixed protocol",
        "Research Workflow",
        _refs(experiment_ref="ExperimentSpec"),
    ),
    DomainObjectSpec(
        "CandidateVersion",
        "Immutable candidate and parent lineage",
        "Research Workflow",
        _refs(finding_ref="Finding"),
    ),
    DomainObjectSpec(
        "ValidationProtocolVersion",
        "Machine-executable statistical protocol",
        "Independent Verifier",
    ),
    DomainObjectSpec(
        "ResearchErrorBudget",
        "Hypothesis-family and confirmation-query budget",
        "Confirmation Service",
        _refs(protocol_ref="ValidationProtocolVersion"),
    ),
    DomainObjectSpec(
        "ValidationReport",
        "Adjusted evidence and gate verdict",
        "Independent Verifier",
        _refs(candidate_ref="CandidateVersion", protocol_ref="ValidationProtocolVersion"),
    ),
    DomainObjectSpec(
        "ConfirmationQuery",
        "Limited vault query and atomic budget debit",
        "Confirmation Service",
        _refs(candidate_ref="CandidateVersion", error_budget_ref="ResearchErrorBudget"),
    ),
    DomainObjectSpec(
        "DecisionPlan",
        "Target, play, selection, price, risk, and expiry",
        "Freeze Service",
        _refs(validation_report_ref="ValidationReport"),
    ),
    DomainObjectSpec("NoActionReason", "Enumerated refusal reason", "Freeze Service"),
    DomainObjectSpec(
        "FrozenDecision",
        (
            "Immutable pre-outcome experimental shadow, claim-eligible shadow, "
            "or NO_ACTION with exact decision kind and content hash"
        ),
        "Freeze Service",
        _refs(decision_plan_ref="DecisionPlan"),
    ),
    DomainObjectSpec(
        "OutcomeObservation",
        "Observed result and conflict or revision relation",
        "Outcome Service",
        _refs(frozen_decision_ref="FrozenDecision"),
    ),
    DomainObjectSpec("ShadowPortfolio", "Shadow account and policy", "Settlement Service"),
    DomainObjectSpec(
        "JournalEntry",
        "Strict double-entry journal record",
        "Settlement Service",
        _refs(portfolio_ref="ShadowPortfolio"),
    ),
    DomainObjectSpec(
        "SettlementRecord",
        "Deterministic settlement from freeze, outcome, and rule",
        "Settlement Service",
        _refs(
            frozen_decision_ref="FrozenDecision",
            outcome_ref="OutcomeObservation",
            rule_ref="RuleVersion",
        ),
    ),
    DomainObjectSpec(
        "AccountingPeriod",
        "Draw, day, business-week, or long-period close",
        "Settlement Service",
    ),
    DomainObjectSpec(
        "LedgerProjection",
        "Event and journal rebuilt ledger and risk projection",
        "Projection Worker",
        _refs(accounting_period_ref="AccountingPeriod"),
    ),
    DomainObjectSpec(
        "PromotionDecision",
        "Formal promote, deny, suspend, or retire verdict",
        "Promotion Transition",
        _refs(candidate_ref="CandidateVersion", validation_report_ref="ValidationReport"),
    ),
    DomainObjectSpec(
        "ModelLifecycleEvent",
        "Activation, decay, revalidation, suspension, or retirement",
        "Promotion Transition",
        _refs(promotion_decision_ref="PromotionDecision"),
    ),
    DomainObjectSpec("AgentHandoff", "Typed delegation and result", "Codex Orchestrator"),
    DomainObjectSpec("WorkflowRun", "Temporal execution identity and state", "Temporal Workflow"),
)

DOMAIN_OBJECT_BY_NAME = {spec.name: spec for spec in DOMAIN_OBJECT_SPECS}


class DomainObjectBase(CommonEnvelope):
    """Base generated object; each registered type narrows entity_type and refs."""

    body: BaseModel


@cache
def domain_model(name: str) -> type[DomainObjectBase]:
    spec = DOMAIN_OBJECT_BY_NAME.get(name)
    if spec is None:
        raise KeyError(f"unknown first-class domain object: {name}")
    body_fields: dict[str, Any] = {
        reference.field: (str, Field(min_length=1)) for reference in spec.references
    }
    body_model = create_model(
        f"{name}Body",
        __config__=ConfigDict(extra="allow", frozen=True),
        **body_fields,
    )
    literal_type = Literal.__getitem__((name,))
    model = create_model(
        name,
        __base__=DomainObjectBase,
        entity_type=(literal_type, name),
        body=(body_model, ...),
    )
    return model


def domain_schema(name: str) -> dict[str, Any]:
    spec = DOMAIN_OBJECT_BY_NAME[name]
    schema = domain_model(name).model_json_schema()
    schema["$id"] = f"xinao.domain.{name}.v1.schema.json"
    schema["x-owner"] = spec.owner
    schema["x-invariants"] = list(spec.invariants)
    schema["x-migration"] = spec.migration
    schema["x-reference-targets"] = {
        reference.field: reference.target for reference in spec.references
    }
    return schema


def domain_schema_catalog() -> dict[str, Any]:
    return {
        "schema_version": "xinao.domain_schema_catalog.v1",
        "object_count": len(DOMAIN_OBJECT_SPECS),
        "objects": {spec.name: domain_schema(spec.name) for spec in DOMAIN_OBJECT_SPECS},
    }
