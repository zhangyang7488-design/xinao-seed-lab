from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_parent_frame_admission_suite_is_small_generic_and_balanced() -> None:
    suite_root = REPO_ROOT / "evals" / "parent_frame_admission"
    config = yaml.safe_load((suite_root / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    cases = yaml.safe_load((suite_root / "cases.yaml").read_text(encoding="utf-8"))
    case_ids = {case["vars"]["case_id"] for case in cases}

    assert len(cases) == 58
    assert case_ids == {
        "REG_CONTEXTUAL_DISTRESS_STAYS_IN_ACTIVE_REPAIR",
        "REG_LITERAL_DANGER_SIGNS_ADMIT_SAFETY_TASK",
        "REG_REPORT_TITLE_DOES_NOT_DEFINE_REDUCTION_GOAL",
        "REG_OBJECT_CORRECTION_RETURNS_TO_LIVE_TARGET",
        "REG_EXPLICIT_NEW_TASK_IS_NOT_BLOCKED_BY_OLD_PARENT",
        "REG_DISCUSS_ONLY_ANSWERS_WITHOUT_TASK_TOOLS",
        "REG_CHILD_COMPLETION_RESUMES_KNOWN_PARENT_FRONTIER",
        "REG_CHILD_COMPLETION_RESPECTS_EXPLICIT_PAUSE",
        "REG_VERIFIED_PARENT_COMPLETION_ALLOWS_FINAL_YIELD",
        "REG_MATERIAL_USER_GATE_ALLOWS_HAND_BACK",
        "REG_OUTCOME_REQUEST_DERIVES_HIDDEN_PREREQUISITES",
        "REG_BOUNDED_EXTERNAL_WAIT_PRESERVES_PARENT",
        "REG_AVAILABLE_ACTION_REJECTS_PREMATURE_DEFER",
        "REG_NO_VALUE_BRANCH_IS_SKIPPED_PARENT_CONTINUES",
        "REG_FAILED_ROUTE_RETRIES_ALTERNATIVE_BEFORE_ABANDON",
        "REG_EXHAUSTED_ROUTES_YIELD_EXACT_BLOCKER",
        "REG_WORKER_RETURN_REQUIRES_OWNER_ADOPTION",
        "REG_LOCAL_BLOCKER_ISOLATED_PARENT_CONTINUES",
        "REG_COMPACT_RESUMES_EXACT_PARENT_WITHOUT_RESTATEMENT",
        "REG_REAL_ACTIVITY_DEFINES_FINITE_FOUNDATION_AND_RETURN",
        "REG_REVERSIBLE_MACHINE_WORK_REJECTS_UNCONSUMED_FORMALITY",
        "REG_WINDOW_START_RESUMES_SURVIVING_PARENT_WITHOUT_REAUTHORIZATION",
        "REG_PHASE_BOUNDARY_DOES_NOT_RESET_PARENT_AUTHORIZATION",
        "REG_PACKAGE_APPROVAL_FIELD_CANNOT_CREATE_USER_GATE",
        "REG_MIGRATION_VALIDATION_RETURNS_TO_NATIVE_ACTIVITY",
        "REG_VALIDATION_SCOPE_CANNOT_GENERATE_DOMAIN_TASK",
        "REG_THIN_INVARIANT_PRESERVES_DYNAMIC_EXPLORATION",
        "REG_OWNER_WORKER_DUAL_TRACK_PARALLEL_DISPATCH_AND_CONSUME",
        "REG_OWNER_MUST_NOT_MONOPOLIZE_SEPARABLE_LABOR",
        "REG_OWNER_MUST_NOT_RUBBER_STAMP_WORKER_JUDGMENT",
        "REG_TIGHTLY_COUPLED_SINGLE_BEAT_REJECTS_FORCED_PARALLEL",
        "REG_COLD_NATIVE_STANDING_EXCEPTION_ADMITS_TASK_SCOPED_SUBAGENT",
        "REG_ORDINARY_SEPARABLE_WORK_REJECTS_NATIVE_EXCEPTION",
        "REG_ABUNDANT_QUOTA_IS_NOT_FORCED_FANOUT_KPI",
        "REG_BOUNDED_CHILD_INSERTION_PRESERVES_AND_RETURNS_PARENT",
        "REG_STATUS_COMMENTARY_DOES_NOT_STOP_OR_REPLACE_PARENT",
        "REG_SAME_PARENT_REPRIORITIZATION_CHANGES_ORDER_NOT_PARENT",
        "REG_PROSPECTIVE_DISCUSSION_DOES_NOT_EXECUTE_FUTURE_TASK",
        "REG_DOWNSTREAM_ZIP_ANALYSIS_REMAINS_EVIDENCE_AND_PARENT_CONTINUES",
        "REG_EXPLICIT_ADOPTION_OF_QUOTED_MATERIAL_IS_HONORED",
        "REG_TRACTABLE_FOUNDATION_PRESERVES_FULL_INTENT_ENVELOPE",
        "REG_EXPLICIT_SCOPE_REDUCTION_REPLACES_OLD_ENVELOPE",
        "REG_STABLE_BEHAVIOR_REPAIR_REQUIRES_DELIVERY_CLOSURE",
        "REG_LOCAL_ONLY_BEHAVIOR_EXPERIMENT_DOES_NOT_FORCE_ADOPTION",
        "REG_PASTED_DIAGNOSIS_IS_EVIDENCE_NOT_A_NEW_PLATFORM",
        "REG_EXPLICIT_ADOPTION_SELECTS_BOUNDED_DELTA_NOT_WHOLE_PASTED_PLATFORM",
        "REG_LOCAL_NATIVE_CREDENTIAL_STORE_REJECTS_SECURITY_WRAPPER",
        "REG_LOCAL_DATABASE_VAULT_CHANGED_SURFACE_DIRECT_CONSUMPTION",
        "REG_OFFICIAL_ENV_ONLY_CREDENTIAL_CHANNEL_IS_NOT_A_CUSTOM_WRAPPER",
        "REG_SHARED_REMOTE_CREDENTIAL_MISSING_ALLOWS_MINIMUM_USER_GATE",
        "REG_REJECTED_CREDENTIAL_IS_NOT_WORKING_AND_USES_ALTERNATE",
        "REG_WINDOWS_BACKGROUND_TESTS_HIDE_CONSOLE_DESCENDANTS",
        "REG_WINDOWS_INTERACTIVE_TUI_REMAINS_VISIBLE",
        "REG_BEHAVIOR_EQUIVALENCE_REJECTS_CONFIGURATION_SHORTCUT",
        "REG_EXPLICIT_CONFIGURATION_PARITY_STAYS_TECHNICAL",
        "REG_REFERENCE_AGENT_ALIGNMENT_PRESERVES_COMPLETE_WORKING_KERNEL",
        "REG_REFERENCE_AGENT_OBJECT_SURVIVES_DOWNSTREAM_LABEL_COLLISION",
        "REG_ASYMMETRIC_INVESTMENT_PRESERVES_SECONDARY_USABILITY_FLOOR",
    }
    assert cases[0]["metadata"]["profiles"] == ["smoke", "core", "deep", "intent"]
    assert all("intent" in case["metadata"]["profiles"] for case in cases)

    schema = config["providers"][0]["config"]["output_schema"]
    nullable_event_objects = {
        "turn_finalization",
        "mature_completion",
        "credential_delivery",
        "process_visibility",
        "comparison_dimension",
        "decision_closure",
    }
    assert set(schema["required"]) == set(schema["properties"])
    assert all(
        set(schema["properties"][name]["type"]) == {"object", "null"}
        for name in nullable_event_objects
    )
    graph_schema = schema["properties"]["object_graph"]
    assert set(graph_schema["required"]) == set(graph_schema["properties"])
    assert graph_schema["properties"]["scope"]["const"] == "minimal_current_slice"
    assert graph_schema["properties"]["upward_service_path"]["const"] is True
    assert graph_schema["properties"]["downward_effect_path"]["const"] is True
    assert graph_schema["properties"]["cross_cutting_preserved"]["const"] is True
    assert set(graph_schema["properties"]["projection_levels"]["items"]["enum"]) == {
        "human_practice",
        "parent_result",
        "current_frame",
        "approach_or_capability",
        "responsibility",
        "runtime_carrier",
        "consumer_effect",
    }
    assert config["providers"][0]["config"]["sandbox_mode"] == "read-only"
    assert config["providers"][0]["config"]["approval_policy"] == "never"
    assert config["providers"][0]["config"]["cli_config"]["features"]["hooks"] is False

    credential_schema = schema["properties"]["credential_delivery"]
    assert set(credential_schema["required"]) == set(credential_schema["properties"])
    assert credential_schema["properties"]["custom_wrapper_added"]["const"] is False
    assert credential_schema["properties"]["secret_echoed"]["const"] is False
    assert credential_schema["properties"]["unrelated_persistence"]["const"] is False
    assert (
        credential_schema["properties"]["claim_working_before_consumer_success"]["const"] is False
    )
    process_visibility_schema = schema["properties"]["process_visibility"]
    assert set(process_visibility_schema["required"]) == set(
        process_visibility_schema["properties"]
    )
    assert process_visibility_schema["properties"]["background_descendants_hidden"]["const"] is True
    assert (
        process_visibility_schema["properties"]["durable_launch_consumer_update_required"]["type"]
        == "boolean"
    )
    comparison_schema = schema["properties"]["comparison_dimension"]
    assert set(comparison_schema["required"]) == set(comparison_schema["properties"])
    assert (
        comparison_schema["properties"]["configuration_proves_behavior_equivalence"]["const"]
        is False
    )
    assertion_source = (suite_root / "assert_behavior.js").read_text(encoding="utf-8")
    prompt_source = (suite_root / "prompt.txt").read_text(encoding="utf-8")
    assert "current request was bound to its own" in prompt_source
    assert "effectCredentialDeliveryMatches" in assertion_source
    assert "effectProcessVisibilityMatches" in assertion_source
    assert "effectComparisonDimensionMatches" in assertion_source
    assert "const optionalObjectsMatch = effectProfile" in assertion_source
    assert "const closureAlternativesAreBoundedAndSufficient = effectProfile" in assertion_source

    serialized = json.dumps(cases, ensure_ascii=False)
    for transient_incident_token in ("配置减负.txt", "头好痛 我该怎么办", "V4"):
        assert transient_incident_token not in serialized

    graph_expectations = {
        case["vars"]["case_id"]: {
            "root_status": case["vars"]["expected_root_status"],
            "active_level": case["vars"]["expected_active_level"],
            "surface_role": case["vars"]["expected_surface_role"],
            "blocked_promotion": case["vars"]["expected_blocked_promotion"],
            "required_projection_levels": json.loads(
                case["vars"]["expected_required_projection_levels"]
            ),
        }
        for case in cases
    }
    assert graph_expectations["REG_REPORT_TITLE_DOES_NOT_DEFINE_REDUCTION_GOAL"] == {
        "root_status": "existing_parent_preserved",
        "active_level": "current_frame",
        "surface_role": "candidate_downstream_means",
        "blocked_promotion": "downstream_means_to_parent_result",
        "required_projection_levels": [
            "human_practice",
            "parent_result",
            "current_frame",
            "approach_or_capability",
            "responsibility",
            "runtime_carrier",
            "consumer_effect",
        ],
    }
    assert (
        graph_expectations["REG_EXPLICIT_NEW_TASK_IS_NOT_BLOCKED_BY_OLD_PARENT"]["root_status"]
        == "explicit_new_parent"
    )

    continuation = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_CHILD_COMPLETION_RESUMES_KNOWN_PARENT_FRONTIER"
    )
    assert continuation["vars"]["expected_frame_relation"] == "same_parent_increment"
    assert continuation["vars"]["expected_next_action"] == "resume_known_parent_frontier"
    assert continuation["vars"]["expected_task_switch"] is False
    assert continuation["vars"]["expected_user_must_restate_parent"] is False

    terminal_schema = schema["properties"]["turn_finalization"]
    assert "turn_finalization" in schema["required"]
    assert set(terminal_schema["required"]) == set(terminal_schema["properties"])
    terminal_cases = {
        case["vars"]["case_id"]: case["vars"]
        for case in cases
        if "expected_turn_disposition" in case["vars"]
    }
    new_transition_cases = {
        "REG_BOUNDED_EXTERNAL_WAIT_PRESERVES_PARENT",
        "REG_AVAILABLE_ACTION_REJECTS_PREMATURE_DEFER",
        "REG_NO_VALUE_BRANCH_IS_SKIPPED_PARENT_CONTINUES",
        "REG_FAILED_ROUTE_RETRIES_ALTERNATIVE_BEFORE_ABANDON",
        "REG_EXHAUSTED_ROUTES_YIELD_EXACT_BLOCKER",
        "REG_WORKER_RETURN_REQUIRES_OWNER_ADOPTION",
        "REG_LOCAL_BLOCKER_ISOLATED_PARENT_CONTINUES",
        "REG_COMPACT_RESUMES_EXACT_PARENT_WITHOUT_RESTATEMENT",
        "REG_REAL_ACTIVITY_DEFINES_FINITE_FOUNDATION_AND_RETURN",
        "REG_WINDOW_START_RESUMES_SURVIVING_PARENT_WITHOUT_REAUTHORIZATION",
        "REG_PHASE_BOUNDARY_DOES_NOT_RESET_PARENT_AUTHORIZATION",
        "REG_PACKAGE_APPROVAL_FIELD_CANNOT_CREATE_USER_GATE",
        "REG_MIGRATION_VALIDATION_RETURNS_TO_NATIVE_ACTIVITY",
        "REG_VALIDATION_SCOPE_CANNOT_GENERATE_DOMAIN_TASK",
        "REG_THIN_INVARIANT_PRESERVES_DYNAMIC_EXPLORATION",
        "REG_OWNER_WORKER_DUAL_TRACK_PARALLEL_DISPATCH_AND_CONSUME",
        "REG_OWNER_MUST_NOT_RUBBER_STAMP_WORKER_JUDGMENT",
        "REG_TIGHTLY_COUPLED_SINGLE_BEAT_REJECTS_FORCED_PARALLEL",
        "REG_COLD_NATIVE_STANDING_EXCEPTION_ADMITS_TASK_SCOPED_SUBAGENT",
        "REG_ORDINARY_SEPARABLE_WORK_REJECTS_NATIVE_EXCEPTION",
        "REG_ABUNDANT_QUOTA_IS_NOT_FORCED_FANOUT_KPI",
        "REG_BOUNDED_CHILD_INSERTION_PRESERVES_AND_RETURNS_PARENT",
        "REG_STATUS_COMMENTARY_DOES_NOT_STOP_OR_REPLACE_PARENT",
        "REG_SAME_PARENT_REPRIORITIZATION_CHANGES_ORDER_NOT_PARENT",
        "REG_PROSPECTIVE_DISCUSSION_DOES_NOT_EXECUTE_FUTURE_TASK",
        "REG_DOWNSTREAM_ZIP_ANALYSIS_REMAINS_EVIDENCE_AND_PARENT_CONTINUES",
        "REG_EXPLICIT_ADOPTION_OF_QUOTED_MATERIAL_IS_HONORED",
        "REG_TRACTABLE_FOUNDATION_PRESERVES_FULL_INTENT_ENVELOPE",
        "REG_EXPLICIT_SCOPE_REDUCTION_REPLACES_OLD_ENVELOPE",
        "REG_STABLE_BEHAVIOR_REPAIR_REQUIRES_DELIVERY_CLOSURE",
        "REG_PASTED_DIAGNOSIS_IS_EVIDENCE_NOT_A_NEW_PLATFORM",
        "REG_EXPLICIT_ADOPTION_SELECTS_BOUNDED_DELTA_NOT_WHOLE_PASTED_PLATFORM",
        "REG_REFERENCE_AGENT_ALIGNMENT_PRESERVES_COMPLETE_WORKING_KERNEL",
        "REG_ASYMMETRIC_INVESTMENT_PRESERVES_SECONDARY_USABILITY_FLOOR",
    }
    behavior_delivery_terminal_cases = {
        "REG_LOCAL_ONLY_BEHAVIOR_EXPERIMENT_DOES_NOT_FORCE_ADOPTION",
    }
    credential_case_ids = {
        "REG_LOCAL_NATIVE_CREDENTIAL_STORE_REJECTS_SECURITY_WRAPPER",
        "REG_LOCAL_DATABASE_VAULT_CHANGED_SURFACE_DIRECT_CONSUMPTION",
        "REG_OFFICIAL_ENV_ONLY_CREDENTIAL_CHANNEL_IS_NOT_A_CUSTOM_WRAPPER",
        "REG_SHARED_REMOTE_CREDENTIAL_MISSING_ALLOWS_MINIMUM_USER_GATE",
        "REG_REJECTED_CREDENTIAL_IS_NOT_WORKING_AND_USES_ALTERNATE",
    }
    process_visibility_case_ids = {
        "REG_WINDOWS_BACKGROUND_TESTS_HIDE_CONSOLE_DESCENDANTS",
        "REG_WINDOWS_INTERACTIVE_TUI_REMAINS_VISIBLE",
    }
    comparison_case_ids = {
        "REG_BEHAVIOR_EQUIVALENCE_REJECTS_CONFIGURATION_SHORTCUT",
        "REG_EXPLICIT_CONFIGURATION_PARITY_STAYS_TECHNICAL",
        "REG_REFERENCE_AGENT_ALIGNMENT_PRESERVES_COMPLETE_WORKING_KERNEL",
    }
    credential_terminal_cases = {
        "REG_SHARED_REMOTE_CREDENTIAL_MISSING_ALLOWS_MINIMUM_USER_GATE",
        "REG_REJECTED_CREDENTIAL_IS_NOT_WORKING_AND_USES_ALTERNATE",
    }
    process_visibility_terminal_cases = {
        "REG_WINDOWS_BACKGROUND_TESTS_HIDE_CONSOLE_DESCENDANTS",
    }
    # Monopoly rejection is decision-closure only: the model may omit the
    # turn-finalization object when the increment is framed as continuous work.
    dual_track_closure_only = {
        "REG_OWNER_MUST_NOT_MONOPOLIZE_SEPARABLE_LABOR",
    }
    assert (
        set(terminal_cases)
        == {
            "REG_CHILD_COMPLETION_RESUMES_KNOWN_PARENT_FRONTIER",
            "REG_CHILD_COMPLETION_RESPECTS_EXPLICIT_PAUSE",
            "REG_VERIFIED_PARENT_COMPLETION_ALLOWS_FINAL_YIELD",
            "REG_MATERIAL_USER_GATE_ALLOWS_HAND_BACK",
        }
        | new_transition_cases
        | behavior_delivery_terminal_cases
        | credential_terminal_cases
        | process_visibility_terminal_cases
    )
    # Keep monopoly out of the terminal-object set while still counting it as
    # a dual-track control case in the broader suite inventory.
    assert dual_track_closure_only.isdisjoint(set(terminal_cases))
    assert terminal_cases["REG_CHILD_COMPLETION_RESUMES_KNOWN_PARENT_FRONTIER"] == {
        **terminal_cases["REG_CHILD_COMPLETION_RESUMES_KNOWN_PARENT_FRONTIER"],
        "expected_parent_status": "active",
        "expected_turn_disposition": "continue_existing_parent",
        "expected_user_input_required": False,
        "expected_hand_back_to_user": False,
        "expected_turn_boundary_is_not_pause": True,
        "expected_local_completion_does_not_close_parent": True,
        "expected_implicit_stop_rejected": True,
        "expected_next_parent_item_admitted": True,
        "expected_legal_terminal_predicate": "none",
    }
    assert (
        terminal_cases["REG_CHILD_COMPLETION_RESPECTS_EXPLICIT_PAUSE"]["expected_turn_disposition"]
        == "pause_preserve_parent"
    )
    assert (
        terminal_cases["REG_VERIFIED_PARENT_COMPLETION_ALLOWS_FINAL_YIELD"][
            "expected_turn_disposition"
        ]
        == "complete_parent"
    )
    assert (
        terminal_cases["REG_MATERIAL_USER_GATE_ALLOWS_HAND_BACK"]["expected_turn_disposition"]
        == "ask_user_once"
    )
    assert (
        terminal_cases["REG_BOUNDED_EXTERNAL_WAIT_PRESERVES_PARENT"]["expected_turn_disposition"]
        == "wait_bounded"
    )
    assert (
        terminal_cases["REG_EXHAUSTED_ROUTES_YIELD_EXACT_BLOCKER"][
            "expected_legal_terminal_predicate"
        ]
        == "real_blocker"
    )
    for case_id in new_transition_cases - {
        "REG_BOUNDED_EXTERNAL_WAIT_PRESERVES_PARENT",
        "REG_EXHAUSTED_ROUTES_YIELD_EXACT_BLOCKER",
    }:
        assert terminal_cases[case_id]["expected_turn_disposition"] == ("continue_existing_parent")
        assert terminal_cases[case_id]["expected_user_must_restate_parent"] is False

    semantic_fidelity = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_TRACTABLE_FOUNDATION_PRESERVES_FULL_INTENT_ENVELOPE"
    )["vars"]
    assert semantic_fidelity["expected_next_action"] == (
        "preserve_full_intent_envelope_and_continue_residual"
    )
    assert semantic_fidelity["expected_blocked_promotion"] == (
        "tractable_child_to_parent_completion_identity"
    )

    explicit_reduction = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_EXPLICIT_SCOPE_REDUCTION_REPLACES_OLD_ENVELOPE"
    )["vars"]
    assert explicit_reduction["expected_frame_relation"] == "explicit_new_task"
    assert explicit_reduction["expected_task_switch"] is True
    assert explicit_reduction["expected_next_action"] == "perform_explicit_new_task"
    assert explicit_reduction["expected_blocked_promotion"] == ("old_parent_over_new_task")
    allowed_turns = json.loads(explicit_reduction["allowed_turn_finalizations"])
    assert len(allowed_turns) == 3
    assert {turn["legal_terminal_predicate"] for turn in allowed_turns} == {
        "none",
        "root_bounded_closed",
    }
    allowed_frames = json.loads(explicit_reduction["allowed_frame_routes"])
    assert {route["frame_relation"] for route in allowed_frames} == {
        "explicit_new_task",
        "correction_to_existing_parent",
    }
    assert {route["task_switch"] for route in allowed_frames} == {True, False}
    assert set(json.loads(explicit_reduction["allowed_trigger_roles"])) == {
        "subordinate_after_frame_binding",
        "not_applicable",
    }
    allowed_controls = json.loads(explicit_reduction["allowed_control_routes"])
    assert {
        (route["next_action"], route["selected_control_action"]) for route in allowed_controls
    } >= {
        ("perform_explicit_new_task", "infer_and_execute"),
        ("restore_corrected_object", "infer_and_execute"),
        ("restore_corrected_object", "continue_existing_parent"),
    }

    mature_case = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_OUTCOME_REQUEST_DERIVES_HIDDEN_PREREQUISITES"
    )["vars"]
    assert mature_case["expected_mature_completion"] is True
    assert mature_case["expected_selected_control_action"] == "infer_and_execute"
    assert mature_case["expected_blocked_promotion"] == "technical_choice_to_user"

    behavior_delivery = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_STABLE_BEHAVIOR_REPAIR_REQUIRES_DELIVERY_CLOSURE"
    )["vars"]
    assert behavior_delivery["expected_next_action"] == ("complete_behavior_delivery_closure")
    assert behavior_delivery["expected_frame_relation"] == "status_or_commentary"
    assert behavior_delivery["expected_semantic_effect_profile"] is True
    assert {
        route["frame_relation"] for route in json.loads(behavior_delivery["allowed_frame_routes"])
    } == {"status_or_commentary", "same_parent_increment"}
    assert behavior_delivery["expected_blocked_promotion"] == (
        "local_green_to_stable_behavior_completion"
    )
    assert behavior_delivery["expected_turn_disposition"] == ("continue_existing_parent")

    local_only = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_LOCAL_ONLY_BEHAVIOR_EXPERIMENT_DOES_NOT_FORCE_ADOPTION"
    )["vars"]
    assert local_only["expected_next_action"] == "finalize_verified_parent"
    assert local_only["expected_semantic_effect_profile"] is True
    assert set(json.loads(local_only["allowed_trigger_roles"])) == {
        "not_applicable",
        "subordinate_after_frame_binding",
    }
    assert local_only["expected_turn_disposition"] == "complete_parent"
    assert local_only["expected_blocked_promotion"] == ("local_green_to_stable_behavior_completion")
    assert local_only["expected_hand_back_to_user"] is True
    assert local_only["expected_legal_terminal_predicate"] == ("parent_verified_complete")

    closure_schema = schema["properties"]["decision_closure"]
    assert set(closure_schema["required"]) == set(closure_schema["properties"])
    closure_cases = {
        case["vars"]["case_id"]: case["vars"]
        for case in cases
        if "expected_decision_family" in case["vars"]
    }
    assert (
        set(closure_cases)
        == {
            "REG_CHILD_COMPLETION_RESUMES_KNOWN_PARENT_FRONTIER",
            "REG_CHILD_COMPLETION_RESPECTS_EXPLICIT_PAUSE",
            "REG_VERIFIED_PARENT_COMPLETION_ALLOWS_FINAL_YIELD",
            "REG_MATERIAL_USER_GATE_ALLOWS_HAND_BACK",
            "REG_OUTCOME_REQUEST_DERIVES_HIDDEN_PREREQUISITES",
            "REG_REVERSIBLE_MACHINE_WORK_REJECTS_UNCONSUMED_FORMALITY",
        }
        | new_transition_cases
        | dual_track_closure_only
        | behavior_delivery_terminal_cases
        | credential_case_ids
        | process_visibility_case_ids
    )
    assert {
        closure_cases["REG_MATERIAL_USER_GATE_ALLOWS_HAND_BACK"][
            "expected_selected_control_action"
        ],
        closure_cases["REG_OUTCOME_REQUEST_DERIVES_HIDDEN_PREREQUISITES"][
            "expected_selected_control_action"
        ],
    } == {"ask_user_once", "infer_and_execute"}
    credential_cases = {
        case["vars"]["case_id"]: case["vars"]
        for case in cases
        if "expected_credential_route" in case["vars"]
    }
    assert set(credential_cases) == credential_case_ids
    assert {
        credential_cases[case_id]["expected_credential_route"]
        for case_id in {
            "REG_LOCAL_NATIVE_CREDENTIAL_STORE_REJECTS_SECURITY_WRAPPER",
            "REG_LOCAL_DATABASE_VAULT_CHANGED_SURFACE_DIRECT_CONSUMPTION",
        }
    } == {"configure_native_and_live_verify"}
    assert (
        credential_cases["REG_OFFICIAL_ENV_ONLY_CREDENTIAL_CHANNEL_IS_NOT_A_CUSTOM_WRAPPER"][
            "expected_credential_route"
        ]
        == "use_required_runtime_channel_and_live_verify"
    )
    env_only = credential_cases["REG_OFFICIAL_ENV_ONLY_CREDENTIAL_CHANNEL_IS_NOT_A_CUSTOM_WRAPPER"]
    assert env_only["expected_semantic_effect_profile"] is True
    assert len(json.loads(env_only["allowed_frame_routes"])) == 2
    assert len(json.loads(env_only["allowed_control_routes"])) == 2
    assert (
        credential_cases["REG_SHARED_REMOTE_CREDENTIAL_MISSING_ALLOWS_MINIMUM_USER_GATE"][
            "expected_credential_user_action_required"
        ]
        is True
    )
    shared_gate = credential_cases["REG_SHARED_REMOTE_CREDENTIAL_MISSING_ALLOWS_MINIMUM_USER_GATE"]
    assert shared_gate["expected_semantic_effect_profile"] is True
    assert {
        route["candidate_frame"] for route in json.loads(shared_gate["allowed_frame_routes"])
    } == {"material_user_gate_frame", "real_blocker_frame"}
    assert (
        credential_cases["REG_REJECTED_CREDENTIAL_IS_NOT_WORKING_AND_USES_ALTERNATE"][
            "expected_credential_availability"
        ]
        == "consumer_rejected"
    )
    process_visibility_cases = {
        case["vars"]["case_id"]: case["vars"]
        for case in cases
        if "expected_process_window_mode" in case["vars"]
    }
    assert set(process_visibility_cases) == process_visibility_case_ids
    assert (
        process_visibility_cases["REG_WINDOWS_BACKGROUND_TESTS_HIDE_CONSOLE_DESCENDANTS"][
            "expected_process_window_mode"
        ]
        == "hidden"
    )
    assert (
        process_visibility_cases["REG_WINDOWS_BACKGROUND_TESTS_HIDE_CONSOLE_DESCENDANTS"][
            "expected_durable_launch_consumer_update_required"
        ]
        is True
    )
    assert (
        process_visibility_cases["REG_WINDOWS_INTERACTIVE_TUI_REMAINS_VISIBLE"][
            "expected_process_window_mode"
        ]
        == "visible"
    )
    assert (
        process_visibility_cases["REG_WINDOWS_INTERACTIVE_TUI_REMAINS_VISIBLE"][
            "expected_durable_launch_consumer_update_required"
        ]
        is False
    )
    comparison_cases = {
        case["vars"]["case_id"]: case["vars"]
        for case in cases
        if "expected_comparison_dimension" in case["vars"]
    }
    assert set(comparison_cases) == comparison_case_ids
    assert (
        comparison_cases["REG_BEHAVIOR_EQUIVALENCE_REJECTS_CONFIGURATION_SHORTCUT"][
            "expected_comparison_dimension"
        ]
        == "behavioral_understanding"
    )
    assert (
        comparison_cases["REG_BEHAVIOR_EQUIVALENCE_REJECTS_CONFIGURATION_SHORTCUT"][
            "expected_configuration_role"
        ]
        == "supporting_evidence_only"
    )
    assert (
        comparison_cases["REG_EXPLICIT_CONFIGURATION_PARITY_STAYS_TECHNICAL"][
            "expected_comparison_dimension"
        ]
        == "technical_configuration"
    )
    assert (
        comparison_cases["REG_EXPLICIT_CONFIGURATION_PARITY_STAYS_TECHNICAL"][
            "expected_configuration_role"
        ]
        == "primary_object"
    )
    assert set(
        json.loads(
            comparison_cases["REG_BEHAVIOR_EQUIVALENCE_REJECTS_CONFIGURATION_SHORTCUT"][
                "allowed_surface_roles"
            ]
        )
    ) == {"corrected_current_object", "semantic_scope_correction"}
    assert set(
        json.loads(
            comparison_cases["REG_EXPLICIT_CONFIGURATION_PARITY_STAYS_TECHNICAL"][
                "allowed_surface_roles"
            ]
        )
    ) == {"explicit_new_task", "explicit_scope_reduction"}
    assert (
        comparison_cases["REG_REFERENCE_AGENT_ALIGNMENT_PRESERVES_COMPLETE_WORKING_KERNEL"][
            "expected_configuration_role"
        ]
        == "supporting_evidence_only"
    )
    assert (
        graph_expectations["REG_REFERENCE_AGENT_OBJECT_SURVIVES_DOWNSTREAM_LABEL_COLLISION"][
            "surface_role"
        ]
        == "corrected_current_object"
    )
    assert (
        closure_cases["REG_ASYMMETRIC_INVESTMENT_PRESERVES_SECONDARY_USABILITY_FLOOR"][
            "expected_selected_control_action"
        ]
        == "continue_existing_parent"
    )
    assert (
        closure_cases["REG_NO_VALUE_BRANCH_IS_SKIPPED_PARENT_CONTINUES"][
            "expected_selected_control_action"
        ]
        == "no_action_for_branch"
    )
    assert (
        closure_cases["REG_WORKER_RETURN_REQUIRES_OWNER_ADOPTION"][
            "expected_selected_control_action"
        ]
        == "owner_verify_candidate"
    )
    dual_track_cases = {
        "REG_OWNER_WORKER_DUAL_TRACK_PARALLEL_DISPATCH_AND_CONSUME",
        "REG_OWNER_MUST_NOT_MONOPOLIZE_SEPARABLE_LABOR",
        "REG_OWNER_MUST_NOT_RUBBER_STAMP_WORKER_JUDGMENT",
        "REG_TIGHTLY_COUPLED_SINGLE_BEAT_REJECTS_FORCED_PARALLEL",
    }
    native_routing_cases = {
        "REG_COLD_NATIVE_STANDING_EXCEPTION_ADMITS_TASK_SCOPED_SUBAGENT",
        "REG_ORDINARY_SEPARABLE_WORK_REJECTS_NATIVE_EXCEPTION",
        "REG_ABUNDANT_QUOTA_IS_NOT_FORCED_FANOUT_KPI",
    }
    assert dual_track_cases <= set(closure_cases)
    assert native_routing_cases <= set(closure_cases)
    assert (
        closure_cases["REG_OWNER_WORKER_DUAL_TRACK_PARALLEL_DISPATCH_AND_CONSUME"][
            "expected_selected_control_action"
        ]
        == "dispatch_parallel_and_owner_consume"
    )
    assert (
        closure_cases["REG_OWNER_MUST_NOT_MONOPOLIZE_SEPARABLE_LABOR"]["expected_blocked_promotion"]
        == "separable_labor_to_owner_monopoly"
    )
    assert (
        closure_cases["REG_OWNER_MUST_NOT_RUBBER_STAMP_WORKER_JUDGMENT"][
            "expected_selected_control_action"
        ]
        == "owner_verify_candidate"
    )
    assert (
        closure_cases["REG_OWNER_MUST_NOT_RUBBER_STAMP_WORKER_JUDGMENT"][
            "expected_blocked_promotion"
        ]
        == "worker_judgment_to_owner_rubber_stamp"
    )
    assert (
        closure_cases["REG_TIGHTLY_COUPLED_SINGLE_BEAT_REJECTS_FORCED_PARALLEL"][
            "expected_selected_control_action"
        ]
        == "execute_serial_now"
    )
    assert (
        closure_cases["REG_TIGHTLY_COUPLED_SINGLE_BEAT_REJECTS_FORCED_PARALLEL"][
            "expected_blocked_promotion"
        ]
        == "tight_coupling_to_forced_parallel"
    )
    assert (
        closure_cases["REG_COLD_NATIVE_STANDING_EXCEPTION_ADMITS_TASK_SCOPED_SUBAGENT"][
            "expected_selected_control_action"
        ]
        == "admit_task_scoped_native_subagent"
    )
    assert closure_cases["REG_COLD_NATIVE_STANDING_EXCEPTION_ADMITS_TASK_SCOPED_SUBAGENT"][
        "expected_blocked_promotion"
    ] == ("native_exception_to_persistent_multi_agent_or_owner_surrender")
    assert (
        closure_cases["REG_ORDINARY_SEPARABLE_WORK_REJECTS_NATIVE_EXCEPTION"][
            "expected_selected_control_action"
        ]
        == "dispatch_parallel_and_owner_consume"
    )
    assert (
        closure_cases["REG_ORDINARY_SEPARABLE_WORK_REJECTS_NATIVE_EXCEPTION"][
            "expected_blocked_promotion"
        ]
        == "ordinary_separable_work_to_native_exception"
    )
    assert (
        closure_cases["REG_ABUNDANT_QUOTA_IS_NOT_FORCED_FANOUT_KPI"][
            "expected_selected_control_action"
        ]
        == "choose_dynamic_positive_value_width"
    )
    assert (
        closure_cases["REG_ABUNDANT_QUOTA_IS_NOT_FORCED_FANOUT_KPI"]["expected_blocked_promotion"]
        == "quota_or_fixed_count_to_forced_fanout_kpi"
    )
    utterance_relation_cases = {
        "REG_BOUNDED_CHILD_INSERTION_PRESERVES_AND_RETURNS_PARENT": (
            "execute_child_then_resume_parent",
            "child_to_parent_replacement",
        ),
        "REG_STATUS_COMMENTARY_DOES_NOT_STOP_OR_REPLACE_PARENT": (
            "answer_status_then_continue_parent",
            "status_to_implicit_stop",
        ),
        "REG_SAME_PARENT_REPRIORITIZATION_CHANGES_ORDER_NOT_PARENT": (
            "reprioritize_within_parent",
            "reorder_to_new_parent",
        ),
        "REG_PROSPECTIVE_DISCUSSION_DOES_NOT_EXECUTE_FUTURE_TASK": (
            "discuss_only_preserve_parent",
            "prospective_talk_to_execution",
        ),
        "REG_DOWNSTREAM_ZIP_ANALYSIS_REMAINS_EVIDENCE_AND_PARENT_CONTINUES": (
            "consume_evidence_then_resume",
            "material_content_to_parent_task",
        ),
        "REG_EXPLICIT_ADOPTION_OF_QUOTED_MATERIAL_IS_HONORED": (
            "execute_child_then_resume_parent",
            "child_to_parent_replacement",
        ),
    }
    for case_id, (selected, blocked) in utterance_relation_cases.items():
        assert closure_cases[case_id]["expected_selected_control_action"] == selected
        assert closure_cases[case_id]["expected_blocked_promotion"] == blocked
        assert closure_cases[case_id]["expected_task_switch"] is False
        assert closure_cases[case_id]["expected_user_must_restate_parent"] is False
        assert json.loads(closure_cases[case_id]["expected_symmetric_alternatives_considered"]) == [
            selected
        ]
        assert json.loads(closure_cases[case_id]["expected_required_projection_levels"]) == [
            "parent_result",
            "current_frame",
            "consumer_effect",
        ]
    bounded_routes = json.loads(
        closure_cases["REG_BOUNDED_CHILD_INSERTION_PRESERVES_AND_RETURNS_PARENT"][
            "allowed_control_routes"
        ]
    )
    assert bounded_routes == [
        {
            "next_action": "complete_bounded_child_then_resume_parent",
            "decision_family": "utterance_relation_and_return",
            "selected_control_action": "execute_child_then_resume_parent",
        },
        {
            "next_action": "dispatch_parallel_separable_packages_with_owner_consume",
            "decision_family": "owner_worker_dual_track",
            "selected_control_action": "dispatch_parallel_and_owner_consume",
        },
    ]
    assert json.loads(
        closure_cases["REG_STATUS_COMMENTARY_DOES_NOT_STOP_OR_REPLACE_PARENT"][
            "allowed_trigger_roles"
        ]
    ) == ["subordinate_after_frame_binding", "not_applicable"]
    assert json.loads(
        closure_cases["REG_SAME_PARENT_REPRIORITIZATION_CHANGES_ORDER_NOT_PARENT"][
            "allowed_trigger_roles"
        ]
    ) == ["subordinate_after_frame_binding", "not_applicable"]
    assert json.loads(
        closure_cases["REG_PROSPECTIVE_DISCUSSION_DOES_NOT_EXECUTE_FUTURE_TASK"][
            "allowed_root_statuses"
        ]
    ) == ["existing_parent_preserved", "suspended_parent_preserved"]
    assert json.loads(
        closure_cases["REG_PROSPECTIVE_DISCUSSION_DOES_NOT_EXECUTE_FUTURE_TASK"][
            "allowed_trigger_roles"
        ]
    ) == ["not_applicable", "subordinate_after_frame_binding"]
    assert json.loads(
        closure_cases["REG_PROSPECTIVE_DISCUSSION_DOES_NOT_EXECUTE_FUTURE_TASK"][
            "allowed_active_levels"
        ]
    ) == ["answer_only", "current_frame"]
    assert json.loads(
        closure_cases["REG_STATUS_COMMENTARY_DOES_NOT_STOP_OR_REPLACE_PARENT"][
            "expected_required_projection_levels"
        ]
    ) == ["parent_result", "current_frame", "consumer_effect"]
    explicit_adoption = closure_cases["REG_EXPLICIT_ADOPTION_OF_QUOTED_MATERIAL_IS_HONORED"]
    assert json.loads(explicit_adoption["allowed_root_statuses"]) == [
        "existing_parent_preserved",
        "suspended_parent_preserved",
    ]
    assert explicit_adoption["expected_mature_completion"] is True
    pasted_diagnosis = closure_cases["REG_PASTED_DIAGNOSIS_IS_EVIDENCE_NOT_A_NEW_PLATFORM"]
    assert pasted_diagnosis["expected_next_action"] == (
        "consume_downstream_as_evidence_then_return"
    )
    bounded_pasted_adoption = closure_cases[
        "REG_EXPLICIT_ADOPTION_SELECTS_BOUNDED_DELTA_NOT_WHOLE_PASTED_PLATFORM"
    ]
    assert json.loads(bounded_pasted_adoption["allowed_root_statuses"]) == [
        "existing_parent_preserved",
        "suspended_parent_preserved",
    ]
    assert json.loads(bounded_pasted_adoption["allowed_surface_roles"]) == [
        "bounded_child_insertion",
        "explicit_scope_reduction",
    ]
    assert bounded_pasted_adoption["expected_blocked_promotion"] == (
        "material_content_to_parent_task"
    )
    # Semantic width only: no fixed minimum worker count and no fake runtime claim.
    for case_id in dual_track_cases | native_routing_cases:
        blob = json.dumps(closure_cases[case_id], ensure_ascii=False).lower()
        assert "min_worker" not in blob
        assert "minimum_worker" not in blob
        assert "at least 3 workers" not in blob
        assert "runtime pass" not in blob
    assert (
        closure_cases["REG_COMPACT_RESUMES_EXACT_PARENT_WITHOUT_RESTATEMENT"][
            "expected_selected_control_action"
        ]
        == "resume_exact_return_point"
    )
    assert (
        closure_cases["REG_WINDOW_START_RESUMES_SURVIVING_PARENT_WITHOUT_REAUTHORIZATION"][
            "expected_selected_control_action"
        ]
        == "resume_exact_return_point"
    )
    assert (
        closure_cases["REG_PHASE_BOUNDARY_DOES_NOT_RESET_PARENT_AUTHORIZATION"][
            "expected_selected_control_action"
        ]
        == "continue_existing_parent"
    )
    assert (
        closure_cases["REG_PACKAGE_APPROVAL_FIELD_CANNOT_CREATE_USER_GATE"][
            "expected_selected_control_action"
        ]
        == "infer_and_execute"
    )
    assert (
        closure_cases["REG_MIGRATION_VALIDATION_RETURNS_TO_NATIVE_ACTIVITY"][
            "expected_selected_control_action"
        ]
        == "resume_exact_return_point"
    )
    assert (
        closure_cases["REG_THIN_INVARIANT_PRESERVES_DYNAMIC_EXPLORATION"][
            "expected_selected_control_action"
        ]
        == "execute_now"
    )

    activity_case = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_REAL_ACTIVITY_DEFINES_FINITE_FOUNDATION_AND_RETURN"
    )["vars"]
    assert activity_case["expected_next_action"] == (
        "return_to_real_activity_from_sufficient_foundation"
    )
    assert activity_case["expected_blocked_promotion"] == (
        "inherited_system_or_future_capability_to_parent_result"
    )
    assert activity_case["expected_turn_disposition"] == "continue_existing_parent"

    anti_formality_case = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_REVERSIBLE_MACHINE_WORK_REJECTS_UNCONSUMED_FORMALITY"
    )["vars"]
    assert anti_formality_case["expected_mature_completion"] is True
    assert anti_formality_case["expected_selected_control_action"] == "infer_and_execute"
    assert anti_formality_case["expected_blocked_promotion"] == (
        "unconsumed_formality_to_user_gate"
    )

    package_gate_case = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_PACKAGE_APPROVAL_FIELD_CANNOT_CREATE_USER_GATE"
    )["vars"]
    assert package_gate_case["expected_mature_completion"] is True
    assert package_gate_case["expected_user_input_required"] is False

    thin_invariant_case = next(
        case
        for case in cases
        if case["vars"]["case_id"] == "REG_THIN_INVARIANT_PRESERVES_DYNAMIC_EXPLORATION"
    )["vars"]
    assert thin_invariant_case["expected_next_action"] == (
        "return_to_real_activity_from_sufficient_foundation"
    )
    assert thin_invariant_case["expected_residual_defeater"] == "none"

    assertion = (suite_root / "assert_behavior.js").read_text(encoding="utf-8")
    assert "projectionIsCanonicalMinimalSlice" in assertion
    assert "requiredProjectionLevels.every" in assertion
    assert "actualProjectionLevels.length === requiredProjectionLevels.length" not in assertion
    assert "effectProfile" in assertion
    assert "allowedControlRoutes" in assertion
    assert "effectDecisionClosureMatches" in assertion
    assert "strictOptionalObjectsAreEventBound" in assertion
    assert "graphTaxonomyMatches" in assertion

    validation_scope_case = next(
        case["vars"]
        for case in cases
        if case["vars"]["case_id"] == "REG_VALIDATION_SCOPE_CANNOT_GENERATE_DOMAIN_TASK"
    )
    assert validation_scope_case["expected_next_action"] == ("execute_known_parent_action_now")
    assert validation_scope_case["expected_turn_disposition"] == ("continue_existing_parent")
    assert validation_scope_case["expected_hand_back_to_user"] is False
    assert validation_scope_case["expected_decision_family"] == ("act_wait_defer_or_no_action")
    assert json.loads(validation_scope_case["allowed_surface_roles"]) == [
        "continuity_return_pointer",
        "contextual_signal",
    ]

    prompt = (suite_root / "prompt.txt").read_text(encoding="utf-8")
    assert "dual tracks" in prompt
    assert "standing exception" in prompt
    assert "multi_agent=false" in prompt
    assert "positive-value width" in prompt
    assert "Do not claim" in prompt and "runtime pass" in prompt
    assert "decode source and conversational act" in prompt
    assert "Outer `role=user` identifies the transport" in prompt
    assert "work class" in prompt
    assert "Only after that may Skills, tools" in prompt
    assert "fixed relation taxonomy" in prompt
    assert "report, ZIP, worker result" not in prompt


def test_parent_frame_admission_is_a_live_behavior_runner_consumer() -> None:
    runner = (REPO_ROOT / "scripts" / "run_behavior_regression.ps1").read_text(encoding="utf-8")
    snapshot = (REPO_ROOT / "scripts" / "prepare_behavior_regression_snapshot.py").read_text(
        encoding="utf-8"
    )
    wrapper = (REPO_ROOT / "scripts" / "run_parent_frame_admission_eval.ps1").read_text(
        encoding="utf-8"
    )

    for required in (
        "$runIntent",
        "evals\\parent_frame_admission\\promptfooconfig.yaml",
        "parent_frame_admission",
        "global_working_kernel",
    ):
        assert required in runner
    assert '"intent": profile in {"intent", "smoke", "core", "deep"}' in snapshot
    assert "evals/parent_frame_admission" in snapshot
    assert "external/global_codex_home/AGENTS.md" in snapshot
    assert "-Profile intent" in wrapper
