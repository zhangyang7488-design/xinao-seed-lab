from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from xinao.contracts import DOMAIN_OBJECT_SPECS, domain_model, domain_schema_catalog

EXPECTED_OBJECTS = {
    "AuthorityContract",
    "SourceIdentity",
    "SourceSnapshot",
    "SourceVerification",
    "DatasetSnapshot",
    "BaselineOddsWaterVersion",
    "PlayCatalogVersion",
    "PlayFamilyVersion",
    "RuleVersion",
    "SettlementFunctionVersion",
    "EventMatrixSnapshot",
    "WorldSnapshot",
    "FeatureSnapshot",
    "ArtifactRef",
    "ResearchQuestion",
    "EvidenceBundle",
    "HypothesisSpec",
    "ExperimentSpec",
    "Finding",
    "CandidateVersion",
    "ValidationProtocolVersion",
    "ResearchErrorBudget",
    "ValidationReport",
    "ConfirmationQuery",
    "DecisionPlan",
    "NoActionReason",
    "FrozenDecision",
    "OutcomeObservation",
    "ShadowPortfolio",
    "JournalEntry",
    "SettlementRecord",
    "AccountingPeriod",
    "LedgerProjection",
    "PromotionDecision",
    "ModelLifecycleEvent",
    "AgentHandoff",
    "WorkflowRun",
}


def base_values(name: str, body: dict[str, str]) -> dict[str, object]:
    return {
        "entity_id": "0190f9c0-6f4c-7a11-8b22-334455667788",
        "entity_type": name,
        "parent_ids": (),
        "correlation_id": "0190f9c0-6f4c-7a12-8b22-334455667788",
        "causation_id": None,
        "created_at": datetime(2026, 7, 14, tzinfo=UTC),
        "effective_at": None,
        "knowledge_cutoff_at": None,
        "source_refs": (),
        "artifact_refs": (),
        "git_sha": "f" * 40,
        "config_hash": "a" * 64,
        "rule_version": None,
        "idempotency_key": f"fixture-{name}",
        "producer": "contract-test",
        "status": "ACTIVE",
        "body": body,
    }


def test_registry_exactly_covers_blueprint_first_class_objects() -> None:
    observed = {spec.name for spec in DOMAIN_OBJECT_SPECS}
    assert observed == EXPECTED_OBJECTS
    assert len(observed) == len(DOMAIN_OBJECT_SPECS) == 37


def test_catalog_generates_schema_owner_invariants_migration_and_references() -> None:
    catalog = domain_schema_catalog()
    assert catalog["object_count"] == 37
    assert set(catalog["objects"]) == EXPECTED_OBJECTS
    for name, schema in catalog["objects"].items():
        assert schema["$id"] == f"xinao.domain.{name}.v1.schema.json"
        assert schema["x-owner"]
        assert len(schema["x-invariants"]) == 4
        assert schema["x-migration"]
        assert set(schema["x-reference-targets"].values()) <= EXPECTED_OBJECTS


@pytest.mark.parametrize("spec", DOMAIN_OBJECT_SPECS, ids=lambda item: item.name)
def test_generated_models_require_declared_refs_and_reject_wrong_entity_type(spec) -> None:
    body = {reference.field: f"ref:{reference.target}" for reference in spec.references}
    model = domain_model(spec.name)
    instance = model(**base_values(spec.name, body))
    assert instance.entity_type == spec.name
    with pytest.raises(ValidationError):
        model(**base_values("WrongType", body))
    if spec.references:
        missing = dict(body)
        missing.pop(spec.references[0].field)
        with pytest.raises(ValidationError):
            model(**base_values(spec.name, missing))


def test_body_changes_alter_content_hash() -> None:
    model = domain_model("SourceIdentity")
    first = model(
        **base_values("SourceIdentity", {"authority_contract_ref": "authority:v1", "scope": "a"})
    )
    second = model(
        **base_values("SourceIdentity", {"authority_contract_ref": "authority:v1", "scope": "b"})
    )
    assert first.compute_content_hash() != second.compute_content_hash()
