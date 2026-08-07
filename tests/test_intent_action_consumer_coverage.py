from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_intent_action_baseline_is_thin_honest_and_migration_bounded() -> None:
    root = REPO_ROOT / "evals" / "intent_continuity_baseline"
    baseline = (root / "BASELINE.md").read_text(encoding="utf-8")
    ledger = json.loads((root / "consumer_coverage.v1.json").read_text(encoding="utf-8"))

    assert "SENTINEL:CODEX_INTENT_ACTION_BASELINE_V1" in baseline
    assert "manager Skill" in baseline
    assert "Ordinary low-risk continuous execution" in baseline
    assert "full first-principles activity recovery" in baseline
    assert "Productivity is not a new parent goal" in baseline
    assert ledger["authority"] is False
    assert ledger["completion_claim_allowed"] is False
    assert ledger["baseline_readiness"]["current"] == (
        "CURRENT_PARENT_AUTHORIZES_BEHAVIOR_CONFIGURATION_AND_MIGRATION_REDERIVATION_RUNTIME_PARTIAL"
    )
    assert (
        "isolated reversible migration implementation followed by native-consumer validation"
        in ledger["baseline_readiness"]["allows"]
    )

    statuses = set(ledger["status_values"])
    stages = ledger["stages"]
    assert len(stages) == 15
    assert len({stage["id"] for stage in stages}) == len(stages)
    assert all(stage["status"] in statuses for stage in stages)
    assert all(stage["open_gap"] for stage in stages)
    assert all(stage["text_contract"] for stage in stages)
    assert all(stage["live_consumer"] for stage in stages)
    assert "VERIFIED" not in {stage["status"] for stage in stages}

    assert set(ledger["known_missing_direct_fresh_families"]) == {
        "window_start_resumes_surviving_parent_without_reauthorization",
        "phase_boundary_does_not_reset_parent_authorization",
        "package_approval_field_cannot_create_user_gate",
        "migration_validation_returns_to_native_activity",
        "thin_invariant_preserves_dynamic_exploration",
    }
    assert len(ledger["remaining_nonuniversal_boundaries"]) >= 3

    serialized = json.dumps(ledger, ensure_ascii=False)
    assert "trusted A/B UserPromptSubmit zero-beat hook" in serialized
    assert "trusted A/B Stop hook" in serialized
    assert "claiming universal intent-to-action closure" in serialized
    assert "blind migration" in serialized
    assert "user-side technical Owner" in serialized
    assert "validation is exact readback rather than task generation" in serialized
    assert "architecture_migration_preserves_capability_lineage" in serialized
    assert "semantic_scope_fidelity_and_parent_completion_identity" in serialized
    assert "stable_behavior_delivery_closure" in serialized
    assert "pasted_candidate_adjudication_and_action_economy" in serialized
    assert "productive_action_value_and_meaningful_transparency" in serialized
    assert "productive_action_trajectory" in serialized
    assert "classification reversal" in serialized
    assert "repair-agent-behavior 2.5.1" in serialized
    assert "applicable repository adoption" in serialized
    assert "retired science routing remains retired" in serialized
    assert "all 124 historical context cases" in serialized
    assert "per-turn full PDM" not in serialized

    model = json.loads((root / "decision_model.v1.json").read_text(encoding="utf-8"))
    fidelity = model["semantic_scope_fidelity"]
    assert fidelity["binding_is_not_lossy_summarization"] is True
    assert "all_currently_adopted_parent_outcomes" in fidelity["preserve_together"]
    assert "explicit_human_scope_reduction" in fidelity["legitimate_narrowing"]
    assert "cannot_replace_parent_completion_identity" in fidelity["child_rule"]
    closure = model["bounded_decision_closure_assurance"]
    assert "before_the_owner_locks_the_first_candidate" in closure["independence_timing"]
    assert "minimal_delta" in closure["prompt_independence_contract"]
    assert (
        "directed_red_team_not_independent_problem_formation"
        in closure["directed_review_distinction"]
    )
    assert "lane_count" in closure["cognitive_diversity_evidence"]
