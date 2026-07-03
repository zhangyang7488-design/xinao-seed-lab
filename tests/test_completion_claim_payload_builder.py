import tempfile
import unittest
import json
from pathlib import Path

from services.agent_runtime import codex_centric_object_preserving_runtime as runtime
from services.agent_runtime import completion_claim_payload_builder as builder


def assert_authority_boundary(testcase, payload):
    testcase.assertTrue(payload["not_source_of_truth"])
    testcase.assertTrue(payload["not_user_completion"])
    boundary = payload["authority_boundary"]
    testcase.assertEqual(boundary["source_of_truth"], "external_mature_runtime")
    testcase.assertTrue(boundary["not_source_of_truth"])
    testcase.assertTrue(boundary["not_user_completion"])
    testcase.assertTrue(boundary["claim_payload_is_not_decision"])


def write_valid_side_audit(runtime_root: Path, task_id: str) -> None:
    payload = {
        "schema_version": "xinao.human_visible_completion_side_audit.v1",
        "task_object_id": task_id,
        "status": "external_ai_human_visual_audit_passed",
        "audit_lane": "external_ai_human_visual_completion_side_audit",
        "auditor_id": "independent_visual_ai",
        "auditor_independent_of_primary": True,
        "primary_executor_may_not_self_sign": True,
        "human_visible_status": {"current_state": "visible"},
        "human_visual_findings": {
            "user_can_understand_current_state": True,
            "no_machine_terminal_disguised_as_user_completion": True,
            "unfinished_items_visible": True,
            "next_action_visible": True,
        },
    }
    latest = runtime_root / "state" / "human_visible_completion_audit" / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_current_task_owner(runtime_root: Path, task_id: str) -> None:
    owner = runtime.default_current_task_owner(task_id, runtime_root)
    latest = runtime_root / "state" / "current_task_owner" / "latest.json"
    task_path = runtime_root / "state" / "current_task_owner" / f"{task_id}.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(owner, ensure_ascii=False), encoding="utf-8")
    task_path.write_text(json.dumps(owner, ensure_ascii=False), encoding="utf-8")


class CompletionClaimPayloadBuilderTests(unittest.TestCase):
    def test_partial_payload_preserves_frontier(self):
        payload = builder.build_claim_payload(task_id="unit_partial", mode="partial")
        decision = runtime.claim_completion(runtime.CompletionClaim(**payload))

        self.assertEqual(payload["frontier"]["status"], "open")
        assert_authority_boundary(self, payload)
        self.assertEqual(decision.status, "partial")
        self.assertFalse(decision.stop_allowed)

    def test_complete_payload_allows_only_full_empty_frontier(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            write_valid_side_audit(runtime_root, "unit_complete")
            write_current_task_owner(runtime_root, "unit_complete")
            payload = builder.build_claim_payload(task_id="unit_complete", mode="complete", runtime_root=runtime_root)
            decision = runtime.claim_completion(runtime.CompletionClaim(**payload))

        self.assertEqual(payload["frontier"]["status"], "empty")
        self.assertNotIn("Completion fixture", payload["contract"]["proof_or_validator"])
        self.assertNotIn("Completion fixture", payload["verification"]["proof_summary"])
        self.assertIn("Task-scoped completion claim", payload["verification"]["proof_summary"])
        self.assertTrue(payload["memory_read_refs"])
        self.assertTrue(payload["evidence_write_refs"])
        self.assertTrue(payload["budget_record"])
        self.assertTrue(payload["rollback_plan_ref"])
        self.assertTrue(payload["rollback_execution_result"]["rollback_executable"])
        self.assertTrue(payload["human_visible_side_audit_ref"])
        self.assertEqual(payload["current_task_owner"]["task_id"], "unit_complete")
        assert_authority_boundary(self, payload)
        self.assertEqual(decision.status, "complete_allowed")
        self.assertTrue(decision.stop_allowed)

    def test_complete_payload_without_current_task_owner_stays_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            write_valid_side_audit(runtime_root, "unit_complete_no_owner")
            payload = builder.build_claim_payload(task_id="unit_complete_no_owner", mode="complete", runtime_root=runtime_root)
            decision = runtime.claim_completion(runtime.CompletionClaim(**payload))

        self.assertEqual(decision.status, "partial")
        self.assertFalse(decision.stop_allowed)
        self.assertIn("CURRENT_TASK_OWNER_BINDING_MISSING", decision.reason)

    def test_complete_claim_does_not_embed_user_goal_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            write_valid_side_audit(runtime_root, "unit_complete_no_raw_goal")
            payload = builder.build_claim_payload(
                task_id="unit_complete_no_raw_goal",
                mode="complete",
                user_goal="这是我的中文原话，不要进入 completion claim",
                runtime_root=runtime_root,
            )

        contract_text = json.dumps(payload["contract"], ensure_ascii=False)
        self.assertNotIn("这是我的中文原话", contract_text)
        self.assertIn("non_authoritative_user_goal_sha256:", contract_text)

    def test_complete_payload_without_external_side_audit_stays_partial_and_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = builder.build_claim_payload(task_id="unit_complete_no_side_audit", mode="complete", runtime_root=Path(tmp))
            decision = runtime.claim_completion(runtime.CompletionClaim(**payload))

        self.assertEqual(decision.status, "partial")
        self.assertFalse(decision.stop_allowed)
        self.assertIn("EXTERNAL_AI_HUMAN_VISUAL_SIDE_AUDIT_NOT_PASSED", decision.reason)

    def test_complete_payload_without_evidence_stays_partial(self):
        payload = builder.build_claim_payload(task_id="unit_complete_no_evidence", mode="complete", include_evidence=False)
        decision = runtime.claim_completion(runtime.CompletionClaim(**payload))

        self.assertEqual(decision.status, "partial")
        self.assertFalse(decision.stop_allowed)
        self.assertIn("MEMORY_BUDGET_ROLLBACK_EVIDENCE_MISSING", decision.reason)

    def test_over_budget_without_user_confirmation_stays_partial(self):
        payload = builder.build_claim_payload(task_id="unit_over_budget", mode="complete", over_budget=True)
        decision = runtime.claim_completion(runtime.CompletionClaim(**payload))

        self.assertEqual(decision.status, "partial")
        self.assertFalse(decision.stop_allowed)
        self.assertIn("OVER_BUDGET_WITHOUT_USER_CONFIRMATION", decision.reason)

    def test_rejected_payload_has_no_contract_or_verification(self):
        payload = builder.build_claim_payload(task_id="unit_rejected", mode="rejected")
        decision = runtime.claim_completion(runtime.CompletionClaim(**payload))

        self.assertIsNone(payload["contract"])
        self.assertIsNone(payload["verification"])
        assert_authority_boundary(self, payload)
        self.assertEqual(decision.status, "rejected")
        self.assertFalse(decision.stop_allowed)

    def test_completion_like_detection_covers_chinese_and_english(self):
        self.assertTrue(builder.completion_like("阶段一已完成，准备写回"))
        self.assertTrue(builder.completion_like("final handoff is ready"))
        self.assertFalse(builder.completion_like("继续处理 open frontier"))

    def test_report_with_next_action_requires_continuation(self):
        text = "final report: 昨晚做到投影刷新；下一步修复 route gap 并继续执行。"

        self.assertTrue(builder.completion_like(text))
        self.assertTrue(builder.report_requires_continuation(text))
        envelope = builder.build_report_continuation_envelope(
            task_id="unit_report_stop_inversion",
            report_text=text,
        )

        self.assertEqual(envelope["status"], "partial_continue_required")
        assert_authority_boundary(self, envelope)
        self.assertTrue(envelope["report_stop_inversion"])
        self.assertFalse(envelope["stop_allowed"])
        self.assertEqual(envelope["reason"], "REPORT_CONTAINS_CONTINUATION_MARKERS")

    def test_plain_report_without_gap_is_not_promoted_to_terminal_or_work_item(self):
        text = "status: current state visible."

        self.assertFalse(builder.report_requires_continuation(text))
        self.assertEqual(
            builder.build_report_continuation_envelope(
                task_id="unit_plain_report",
                report_text=text,
            ),
            {},
        )

    def test_write_claim_payload_uses_runtime_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = builder.build_claim_payload(task_id="unit_path", mode="partial")
            path = builder.write_claim_payload(payload=payload, runtime_root=Path(tmp))

        self.assertIn("completion_claim_payloads", str(path))


if __name__ == "__main__":
    unittest.main()
