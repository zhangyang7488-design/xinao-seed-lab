from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = REPO_ROOT / "evals" / "context_intent_alignment"
ASSERTION_PATH = SUITE_ROOT / "assert_behavior.js"
CASES_PATH = SUITE_ROOT / "cases.yaml"
PROMPT_PATH = SUITE_ROOT / "prompt.txt"
PAUSE_CASE_ID = "REG_PAUSE_TO_DISCUSS_BLOCKS_TASK_ACTIONS"


def _case(case_id: str) -> dict[str, Any]:
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    return next(case for case in cases if case["vars"]["case_id"] == case_id)


def _pause_case() -> dict[str, Any]:
    return _case(PAUSE_CASE_ID)


def _first_alternative(value: object) -> object:
    if isinstance(value, str) and "|" in value:
        return value.split("|", 1)[0]
    return value


def _output_from_case(case_id: str) -> dict[str, object]:
    vars_ = _case(case_id)["vars"]
    output = {
        key.removeprefix("expected_"): _first_alternative(value)
        for key, value in vars_.items()
        if key.startswith("expected_")
    }
    output.update(
        {
            "case_id": case_id,
            "active_problem_level": vars_.get(
                "expected_active_problem_level", "object_instance"
            ).split("|", 1)[0],
            "problem_level_order": vars_.get(
                "expected_problem_level_order",
                "before_rule_skill_mode_worker_and_tool_selection",
            ),
            "requested_effect_source": "current_user_increment",
            "first_validation": "object_intent_match",
            "mainline_owner": "codex_main",
            "preserve_parent_completion_bar": True,
            "reason": "The pause binds this turn to an answer and forbids task tools.",
        }
    )
    return output


def _pause_output() -> dict[str, object]:
    return _output_from_case(PAUSE_CASE_ID)


def _context(
    *,
    case_id: str = PAUSE_CASE_ID,
    extra_item: dict[str, object] | None = None,
) -> dict[str, object]:
    items: list[dict[str, object]] = [
        {"type": "userMessage"},
        {"type": "reasoning"},
        {"type": "agentMessage"},
    ]
    if extra_item is not None:
        items.insert(-1, extra_item)
    command_count = sum(item.get("type") == "commandExecution" for item in items)
    return {
        "vars": _case(case_id)["vars"],
        "providerResponse": {"tokenUsage": {"prompt": 100, "completion": 50, "total": 150}},
        "metadata": {
            "codexAppServer": {
                "threadId": "thread-pause-test",
                "turnId": "turn-pause-test",
                "sandboxMode": "read-only",
                "approvalPolicy": "never",
                "itemCounts": {
                    "commandExecution": command_count,
                    "agentMessage": 1,
                },
                "items": items,
            }
        },
    }


def _run_assertion(
    context: dict[str, object],
    *,
    output: dict[str, object] | None = None,
) -> dict[str, object]:
    node = shutil.which("node")
    assert node, "Node.js is required to execute Promptfoo JavaScript assertions"
    program = """
const fs = require("fs");
const assertion = require(process.argv[1]);
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(assertion(JSON.stringify(payload.output), payload.context)));
"""
    completed = subprocess.run(
        [node, "-e", program, str(ASSERTION_PATH)],
        input=json.dumps(
            {"output": output or _pause_output(), "context": context},
            ensure_ascii=False,
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def test_pause_prompt_short_circuits_before_any_agents_read() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    pause_guard = prompt.index("If it is a\nPause or discuss-first increment")
    agents_read = prompt.index("read the applicable AGENTS.md")
    assert pause_guard < agents_read
    assert "including no AGENTS.md read" in prompt
    assert "ongoing dialogue is not itself a blocking decision" in prompt


def test_pause_answer_only_accepts_a_real_tool_free_trace() -> None:
    result = _run_assertion(_context())
    assert result["pass"] is True, result["reason"]


def test_pause_answer_only_rejects_command_or_other_tool_trace() -> None:
    command = _run_assertion(_context(extra_item={"type": "commandExecution"}))
    assert command["pass"] is False
    assert '"answerOnlyTraceIsCoherent":false' in command["reason"]

    mcp = _run_assertion(_context(extra_item={"type": "mcpToolCall"}))
    assert mcp["pass"] is False
    assert '"answerOnlyTaskToolTypes":["mcpToolCall"]' in mcp["reason"]


def test_pause_answer_only_rejects_learning_repair_or_capture_sidecar() -> None:
    output = _pause_output()
    output.update(
        {
            "learning_loop": "double_loop_structural",
            "repair_target": "governing_invariant",
            "closure_evidence": "cross_context_entry_and_negative",
        }
    )
    result = _run_assertion(_context(), output=output)
    assert result["pass"] is False
    assert '"answerOnlyLearningIsCoherent":false' in result["reason"]


def test_pause_answer_only_accepts_no_action_responsibility() -> None:
    output = _pause_output()
    output["decision_responsibility"] = "no_action_on_excluded_route"
    result = _run_assertion(_context(), output=output)
    assert result["pass"] is True, result["reason"]


def test_behavior_repair_boundary_accepts_only_declared_causal_granularities() -> None:
    case_id = "NEG_MAX_BEHAVIOR_DELEGATION_PRESERVES_MAJOR_EXTERNAL_BOUNDARIES"
    output = _output_from_case(case_id)
    output.update(
        {
            "quota_action": "not_applicable",
            "quota_query_disposition": "not_applicable",
            "freeze_unaffected_provider": False,
            "recovery_probe": "not_applicable",
        }
    )
    parent_level = _run_assertion(_context(case_id=case_id), output=output)
    assert parent_level["pass"] is True, parent_level["reason"]

    output.update(
        {
            "learning_loop": "not_applicable",
            "repair_target": "not_applicable",
            "closure_evidence": "not_applicable",
            "durable_behavior_closure": "not_applicable",
        }
    )
    local_boundary_only = _run_assertion(_context(case_id=case_id), output=output)
    assert local_boundary_only["pass"] is True, local_boundary_only["reason"]

    output["repair_target"] = "unrelated_control_plane"
    outside_gold = _run_assertion(_context(case_id=case_id), output=output)
    assert outside_gold["pass"] is False
    assert '"optionalFieldMatches":false' in outside_gold["reason"]


def test_temporary_pain_inputs_are_not_release_dependencies() -> None:
    case_id = "REG_TEMPORARY_PAIN_INPUTS_ARE_NOT_RELEASE_DEPENDENCIES"
    case = _case(case_id)
    vars_ = case["vars"]
    assert vars_["expected_ask_user"] is False
    assert vars_["expected_next_step"] == "act"
    assert vars_["expected_effect_scope"] == "reversible_local"
    assert vars_["expected_repair_target"] == "instance_action"
    assert vars_["expected_constraint_governance_disposition"] == "minimally_relax_or_retire"
    assert vars_["expected_local_completion_transition"] == "resume_suspended_parent"
    assert "about to be deleted" in vars_["restored_context"]

    result = _run_assertion(_context(case_id=case_id), output=_output_from_case(case_id))
    assert result["pass"] is True, result["reason"]


def test_complete_closure_activates_full_lifecycle_transaction() -> None:
    case_id = "REG_COMPLETE_CLOSURE_ACTIVATES_FULL_LIFECYCLE_TRANSACTION"
    case = _case(case_id)
    vars_ = case["vars"]
    recovered = vars_["expected_recovered_requirement_atoms"].split("|")
    rejected = vars_["expected_rejected_proxy_atoms"].split("|")
    assert "完整收口" in vars_["user_increment"]
    assert vars_["expected_next_step"] == "act"
    assert vars_["expected_ask_user"] is False
    assert "ATOM_REMOTE_MAINLINE_ADOPTION" in recovered
    assert "ATOM_LOCAL_MAINLINE_ADOPTION" in recovered
    assert "ATOM_ACTIVE_PROJECTION_AND_REAL_CONSUMER" in recovered
    assert "ATOM_CLASSIFIED_CARRIER_RETIREMENT" in recovered
    assert "ATOM_REQUIRE_USER_TO_ENUMERATE_LIFECYCLE" in rejected

    output = _output_from_case(case_id)
    output["recovered_requirement_atoms"] = vars_["expected_recovered_requirement_atoms"]
    output["rejected_proxy_atoms"] = vars_["expected_rejected_proxy_atoms"]
    result = _run_assertion(_context(case_id=case_id), output=output)
    assert result["pass"] is True, result["reason"]


def test_legacy_continuous_case_accepts_safe_new_binding_defaults() -> None:
    case_id = "REG_ENTER_PERPETUAL_MODE_DOES_NOT_CREATE_GOAL"
    context = _context(case_id=case_id)
    context["vars"].pop("expected_action_binding")
    context["vars"].pop("expected_named_goal_relation")
    output = _output_from_case(case_id)
    result = _run_assertion(context, output=output)
    assert result["pass"] is True, result["reason"]


def test_problem_level_fields_are_required_by_the_behavior_assertion() -> None:
    output = _pause_output()
    output.pop("active_problem_level")
    missing_level = _run_assertion(_context(), output=output)
    assert missing_level["pass"] is False

    output = _pause_output()
    output.pop("problem_level_order")
    missing_order = _run_assertion(_context(), output=output)
    assert missing_order["pass"] is False


def test_constraint_symmetry_cases_pin_three_distinct_dispositions() -> None:
    expected = {
        "REG_ASYMMETRIC_RITUAL_CONSTRAINT_RETIRES_MINIMALLY": ("minimally_relax_or_retire"),
        "NEG_EXPENSIVE_HARD_BOUNDARY_STAYS_PROTECTED": "retain_protected_boundary",
        "NEG_INCOMPLETE_CONSTRAINT_EVIDENCE_PRESERVES_CANDIDATE": (
            "retain_as_candidate_pending_evidence"
        ),
    }
    for case_id, disposition in expected.items():
        case = _case(case_id)["vars"]
        assert case["expected_constraint_governance_disposition"] == disposition
        output = _output_from_case(case_id)
        result = _run_assertion(_context(case_id=case_id), output=output)
        assert result["pass"] is True, f"{case_id}: {result['reason']}"

        output["constraint_governance_disposition"] = "not_applicable"
        mismatch = _run_assertion(_context(case_id=case_id), output=output)
        assert mismatch["pass"] is False
        assert '"optionalFieldMatches":false' in mismatch["reason"]


def test_constraint_symmetry_is_a_required_live_output_field() -> None:
    config = yaml.safe_load((SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    schema = config["providers"][0]["config"]["output_schema"]
    assert "constraint_governance_disposition" in schema["required"]
    assert set(schema["properties"]["constraint_governance_disposition"]["enum"]) == {
        "retain_protected_boundary",
        "retain_as_candidate_pending_evidence",
        "minimally_relax_or_retire",
        "not_applicable",
    }
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    assert "reproducible relaxation harm" in prompt
    assert "unique authority" in prompt


def test_upstream_and_false_escalation_cases_pin_distinct_problem_levels() -> None:
    expected = {
        "REG_MULTI_LEAF_TEXT_REFLEX_SELECTS_SHARED_UPSTREAM": "shared_upstream_generator",
        "REG_SYMPTOM_PROBE_RECOVERS_PROBLEM_DEFINITION": "problem_definition",
        "REG_USER_BURDEN_REANCHORS_PARENT_INTENT": "parent_intent_and_harm",
        "NEG_KNOWN_GENERATOR_DOES_NOT_REPLACE_PARENT_COMPLETION_IDENTITY": (
            "parent_intent_and_harm"
        ),
        "NEG_SINGLE_LOCAL_CAUSE_STAYS_OBJECT_INSTANCE": "object_instance",
        "NEG_INDEPENDENT_BUGS_DO_NOT_INVENT_GENERATOR": "object_instance",
    }
    for case_id, level in expected.items():
        case = _case(case_id)
        assert case["vars"]["expected_active_problem_level"] == level
        output = _output_from_case(case_id)
        result = _run_assertion(_context(case_id=case_id), output=output)
        assert result["pass"] is True, f"{case_id}: {result['reason']}"


def test_mode_goal_and_pause_do_not_promote_merely_because_they_touch_a_parent() -> None:
    for case_id in (
        "REG_ENTER_PERPETUAL_MODE_DOES_NOT_CREATE_GOAL",
        "POS_EXPLICIT_NATIVE_GOAL_REQUEST",
        "REG_PAUSE_TO_DISCUSS_BLOCKS_TASK_ACTIONS",
    ):
        assert _case(case_id)["vars"]["expected_active_problem_level"] == "object_instance"


def test_dual_subject_personal_burden_cannot_be_dropped_as_task_only_diagnosis() -> None:
    case_id = "REG_SYMPTOM_PROBE_RECOVERS_PROBLEM_DEFINITION"
    output = _output_from_case(case_id)
    output["metacognition_disposition"] = "do_not_capture"
    result = _run_assertion(_context(case_id=case_id), output=output)
    assert result["pass"] is False
    assert '"optionalFieldMatches":false' in result["reason"]


def test_already_preserved_personal_burden_is_consumed_without_duplicate_capture() -> None:
    case_id = "REG_USER_BURDEN_REANCHORS_PARENT_INTENT"
    case = _case(case_id)
    assert "evt-rule-subset-lockin-upstream-level-20260727" in case["vars"]["restored_context"]
    assert case["vars"]["expected_metacognition_disposition"] == "do_not_capture"
    result = _run_assertion(_context(case_id=case_id), output=_output_from_case(case_id))
    assert result["pass"] is True, result["reason"]


def test_causal_problem_level_does_not_collapse_software_blast_radius() -> None:
    multi_leaf = _case("REG_MULTI_LEAF_TEXT_REFLEX_SELECTS_SHARED_UPSTREAM")["vars"]
    assert multi_leaf["expected_active_problem_level"] == "shared_upstream_generator"
    assert set(multi_leaf["expected_degraded_scope"].split("|")) == {
        "frontier_only",
        "dependency_cone_only",
        "parent_replanned_by_current_authority",
        "none",
    }

    symptom = _case("REG_SYMPTOM_PROBE_RECOVERS_PROBLEM_DEFINITION")["vars"]
    assert symptom["expected_active_problem_level"] == "problem_definition"
    assert set(symptom["expected_degraded_scope"].split("|")) == {
        "frontier_only",
        "none",
    }


def test_known_generator_remains_a_means_under_parent_completion_identity() -> None:
    case_id = "NEG_KNOWN_GENERATOR_DOES_NOT_REPLACE_PARENT_COMPLETION_IDENTITY"
    case = _case(case_id)["vars"]
    assert case["expected_active_problem_level"] == "parent_intent_and_harm"
    assert case["expected_repair_target"] == "governing_invariant"
    assert case["expected_completion_claim_scope"] == "not_applicable"
    assert "generator is actionable technical background" in case["restored_context"]

    output = _output_from_case(case_id)
    output["active_problem_level"] = "shared_upstream_generator"
    result = _run_assertion(_context(case_id=case_id), output=output)
    assert result["pass"] is False
