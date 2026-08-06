from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LINEAGE_PATH = REPO_ROOT / "evals" / "behavior_regression" / "capability_lineage.v1.json"


def _load_lineage() -> dict[str, object]:
    return json.loads(LINEAGE_PATH.read_text(encoding="utf-8"))


def test_capability_lineage_recovers_history_without_becoming_runtime_authority() -> None:
    lineage = _load_lineage()

    assert lineage["schema_version"] == "xinao.behavior_capability_lineage.v1"
    assert lineage["sentinel"] == "SENTINEL:BEHAVIOR_CAPABILITY_LINEAGE_MIGRATION_PREFLIGHT_V1"
    assert lineage["authority"] is False
    assert lineage["runtime_loaded"] is False
    assert lineage["completion_claim_allowed"] is False
    assert lineage["frozen_baseline"]["capability_id"] == ("intent_source_parent_admission")
    assert lineage["frozen_baseline"]["decision"] == "KEEP_FROZEN"

    families = lineage["families"]
    family_ids = {family["id"] for family in families}
    assert len(families) == len(family_ids) == 21
    assert {
        "intent_source_parent_admission",
        "semantic_scope_fidelity_and_parent_completion_identity",
        "transition_reanchor_and_exact_continuation",
        "owner_worker_fanin_and_adoption",
        "effect_identity_replay_and_consumer_readback",
        "capability_discovery_module_recovery_and_cold_activation",
        "behavior_eval_snapshot_and_migration_preflight",
        "science_domain_authority",
        "legacy_continuity_catalog_and_control_plane",
        "legacy_platform_infrastructure",
    } <= family_ids

    allowed_states = set(lineage["state_values"])
    allowed_dispositions = set(lineage["migration_rule"]["allowed_dispositions"])
    for family in families:
        assert family["pain"]
        assert family["causal_work"]
        assert family["historical_carriers"]
        assert family["current_state"] in allowed_states
        assert family["disposition"] in allowed_dispositions
        assert family["cost_and_failure_radius"]
        assert family["rollback"]
        assert isinstance(family["unknowns"], list)
        if family["disposition"] not in {"RETIRE_FROM_S", "NO_ACTION"}:
            assert family["current_consumers"]

        for consumer in family["current_consumers"]:
            if consumer.startswith(
                (
                    "evals/",
                    "scripts/",
                    "services/",
                    "tests/",
                    "docs/",
                    "plugins/",
                    "projects/",
                )
            ):
                assert (REPO_ROOT / consumer).exists(), consumer

    science = next(family for family in families if family["id"] == "science_domain_authority")
    assert science["current_state"] == "RETIRED"
    assert science["disposition"] == "RETIRE_FROM_S"
    assert "never add it to S live suites" in science["rollback"]

    architecture = lineage["third_architecture"]
    assert architecture["decision"] == ("ADOPT_THIN_RECOMPOSITION_OF_EXISTING_CONSUMERS")
    assert architecture["runtime_controller"] is False
    assert architecture["new_daemon"] is False
    assert architecture["new_user_entry"] is False
    assert architecture["raw_utterance_capability_router"] is False
    delivery = architecture["stable_behavior_delivery_closure"]
    assert delivery["mandatory_for"] == (
        "admitted_cross_window_behavior_or_reusable_capability_change"
    )
    assert delivery["required_predicates"] == [
        "unique_source",
        "active_projection",
        "changed_context_fresh_consumer",
        "balanced_positive_negative_regression",
        "applicable_repository_adoption",
        "rollback_recovery",
        "migration_survival",
    ]
    assert delivery["missing_predicate_status"] == "PARTIAL_CONTINUE_FRONTIER"
    assert delivery["does_not_force"] == [
        "publication_for_explicit_local_only_or_discussion_scope",
        "repository_adoption_when_no_repository_is_a_real_consumer",
        "restoration_of_retired_science_routing",
        "new_manifest_daemon_router_or_owner",
    ]
    plane_ids = {plane["id"] for plane in architecture["planes"]}
    assert len(architecture["planes"]) == len(plane_ids) == 8
    assert {
        "semantic_admission_and_scope_fidelity",
        "post_binding_capability_resolution",
        "worker_fanin_owner_adoption_and_authority",
        "effect_readback_and_parent_completion",
        "science_engineering_continuity_role_separation",
    } <= plane_ids
    assert all(plane["consumers"] and plane["readback"] for plane in architecture["planes"])
    topology = {row["id"]: row["verdict"] for row in architecture["topology_adjudication"]}
    assert topology == {
        "T0_CURRENT_NO_ACTION": "REJECT_AS_COMPLETE_ARCHITECTURE",
        "T1_THIN_GAP_CLOSURE": "ADOPT_AS_FOUNDATION",
        "T2_CAPABILITY_COMPILER": "ADOPT_ONLY_POST_BINDING_DISCOVERY_ATOMS",
        "T3_PLATFORM_CONSOLIDATION": "NO_ACTION",
    }


def test_all_legacy_context_cases_are_partitioned_once_and_stay_cold() -> None:
    lineage = _load_lineage()
    legacy = lineage["legacy_context_suite"]
    groups = legacy["groups"]
    ids = [case_id for group in groups for case_id in group["case_ids"]]

    assert legacy["source_ref"] == "4096f52^"
    assert legacy["source_blob"] == "6ef1b1d495f0010e5150cc10123722be6cde67e9"
    assert legacy["live_restore_allowed"] is False
    assert legacy["case_count"] == len(ids) == len(set(ids)) == 124
    digest = hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()
    assert digest == legacy["sorted_case_ids_sha256"]

    family_ids = {family["id"] for family in lineage["families"]}
    assert all(group["family_id"] in family_ids for group in groups)
    assert all(group["disposition"] for group in groups)

    retired_science = next(
        group for group in groups if group["family_id"] == "science_domain_authority"
    )
    assert retired_science["disposition"] == ("RETIRE_CASES_FROM_GENERIC_S_LIVE_SUITE")
    assert {
        "POS_AUTONOMOUS_NATIVE_GOAL_ADMISSION",
        "REG_XINAO_FRESH_WINDOW_DEFAULTS_TO_NATIVE_RESEARCH",
        "REG_XINAO_DEFAULT_CONTINUOUS_SURVIVES_STATUS_AND_LOCAL_CLOSE",
    } <= set(retired_science["case_ids"])

    live_cases = yaml.safe_load(
        (REPO_ROOT / "evals" / "parent_frame_admission" / "cases.yaml").read_text(encoding="utf-8")
    )
    live_ids = {case["vars"]["case_id"] for case in live_cases}
    assert live_ids.isdisjoint(retired_science["case_ids"])
    assert not any("XINAO" in case_id or "NATIVE_GOAL" in case_id for case_id in live_ids)


def test_every_behavior_run_consumes_the_lineage_migration_preflight() -> None:
    registry = json.loads(
        (REPO_ROOT / "evals" / "suite_registry.v1.json").read_text(encoding="utf-8")
    )
    lineage_ref = registry["loops"]["behavior"]["capability_lineage"]
    assert lineage_ref == "evals/behavior_regression/capability_lineage.v1.json"
    assert registry["capability_migration_preflight"]["authority"] is False
    assert registry["capability_migration_preflight"]["runtime_loaded"] is False
    assert registry["capability_migration_preflight"]["test"] == (
        "tests/test_behavior_capability_lineage.py"
    )
    assert registry["capability_migration_preflight"]["recovery_archive"] == (
        "infra/codex_productivity_recovery/v1/codex-productivity-recovery.v1.zip"
    )
    assert registry["capability_migration_preflight"]["recovery_test"] == (
        "tests/test_codex_productivity_recovery.py"
    )

    runner = (REPO_ROOT / "scripts" / "run_behavior_regression.ps1").read_text(encoding="utf-8")
    snapshot = (REPO_ROOT / "scripts" / "prepare_behavior_regression_snapshot.py").read_text(
        encoding="utf-8"
    )
    for text in (runner, snapshot):
        assert "capability_lineage.v1.json" in text
        assert "test_behavior_capability_lineage.py" in text
        assert "codex_productivity_recovery" in text
        assert "test_codex_productivity_recovery.py" in text

    assert "tests/test_behavior_capability_lineage.py" in runner
    assert "tests/test_codex_productivity_recovery.py" in runner
    assert "capability lineage" in registry["capability_migration_preflight"]["failure_meaning"]


def test_current_catalog_counts_include_delivery_closure_cases() -> None:
    catalog = json.loads(
        (REPO_ROOT / "evals" / "behavior_regression" / "catalog.json").read_text(encoding="utf-8")
    )
    intent = next(suite for suite in catalog["suites"] if suite["id"] == "parent_frame_admission")
    assert intent["case_count"] == 44
    assert catalog["live_profile_case_counts"]["intent"] == 44
    assert catalog["declared_case_count"] == sum(suite["case_count"] for suite in catalog["suites"])
