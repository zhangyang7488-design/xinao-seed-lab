from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = REPO_ROOT / "evals" / "recursive_frame_reconstitution"


def _cases() -> list[dict[str, object]]:
    return yaml.safe_load((SUITE_ROOT / "cases.yaml").read_text(encoding="utf-8"))


def test_recursive_frame_suite_is_balanced_and_not_keyword_routed() -> None:
    cases = _cases()
    by_id = {case["vars"]["case_id"]: case["vars"] for case in cases}
    assert len(cases) == 9
    assert set(by_id) == {
        "REG_CURRENT_ACTION_BINDS_TO_SELF",
        "REG_XINAO_WORLD_PRECEDES_QUESTION",
        "REG_RIGOR_AT_CLAIM_BOUNDARY",
        "REG_SECOND_SOL_REMAINS_UNALLOCATED",
        "REG_XINAO_REALITY_REMAINS_PRIMARY_OBJECT",
        "REG_XINAO_SELF_MODEL_REMAINS_CONDITIONAL",
        "NEG_EXACT_HASH_STAYS_BOUNDED",
        "NEG_LOCAL_FIX_STAYS_LOCAL",
        "NEG_EXPLICIT_STOP_PRESERVED",
    }
    assert by_id["REG_CURRENT_ACTION_BINDS_TO_SELF"]["expected_current_action_in_object"]
    assert by_id["REG_XINAO_WORLD_PRECEDES_QUESTION"][
        "expected_whole_reality_before_compression"
    ]
    assert by_id["REG_XINAO_WORLD_PRECEDES_QUESTION"]["expected_next_behavior"] == (
        "compute_xinao_reality_directly"
    )
    assert by_id["REG_SECOND_SOL_REMAINS_UNALLOCATED"]["expected_next_behavior"] == (
        "leave_second_sol_unallocated"
    )
    assert by_id["REG_XINAO_REALITY_REMAINS_PRIMARY_OBJECT"][
        "accepted_object_behavior_pairs"
    ] == [
        {
            "active_object": "current_agent_action",
            "next_behavior": "change_current_behavior_now",
        },
        {
            "active_object": "xinao_whole_reality",
            "next_behavior": "compute_xinao_reality_directly",
        },
    ]
    assert by_id["REG_XINAO_SELF_MODEL_REMAINS_CONDITIONAL"][
        "expected_next_behavior"
    ] == "change_current_behavior_now"
    assert by_id["REG_XINAO_SELF_MODEL_REMAINS_CONDITIONAL"][
        "expected_active_object"
    ] == "current_agent_action"
    assert by_id["REG_XINAO_SELF_MODEL_REMAINS_CONDITIONAL"][
        "expected_current_action_in_object"
    ]
    assert not by_id["NEG_EXACT_HASH_STAYS_BOUNDED"][
        "expected_whole_reality_before_compression"
    ]
    assert by_id["NEG_LOCAL_FIX_STAYS_LOCAL"]["expected_next_behavior"] == (
        "execute_bounded_operation"
    )
    assert by_id["NEG_EXPLICIT_STOP_PRESERVED"]["expected_next_behavior"] == (
        "preserve_stop"
    )


def test_recursive_frame_promptfoo_consumer_is_fresh_read_only_and_non_ceremonial() -> None:
    config = yaml.safe_load((SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    provider = config["providers"][0]
    assert provider["id"] == "openai:codex-app-server"
    provider_config = provider["config"]
    assert provider_config["sandbox_mode"] == "read-only"
    assert provider_config["approval_policy"] == "never"
    assert provider_config["ephemeral"] is True
    assert provider_config["reuse_server"] is False
    assert provider_config["inherit_process_env"] is False
    properties = provider_config["output_schema"]["properties"]
    for key in (
        "question_is_mandatory_gateway",
        "rigor_blocks_initial_perception",
        "new_meta_control_plane",
        "immediate_self_test",
        "permanent_uptake_claim",
        "self_inventory_precedes_xinao",
    ):
        assert properties[key]["const"] is False


def test_recursive_frame_suite_is_a_production_behavior_consumer() -> None:
    runner = (REPO_ROOT / "scripts" / "run_behavior_regression.ps1").read_text(
        encoding="utf-8"
    )
    snapshot = (REPO_ROOT / "scripts" / "prepare_behavior_regression_snapshot.py").read_text(
        encoding="utf-8"
    )
    assert "recursive_frame_reconstitution" in runner
    assert "recursive_frame_reconstitution" in snapshot
    assert "conduct-xinao-native-research" in runner
    assert "conduct-xinao-native-research" in snapshot
