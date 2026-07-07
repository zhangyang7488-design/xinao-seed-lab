import json
import tempfile
import unittest
from pathlib import Path

from services.agent_runtime import codex_centric_object_preserving_runtime as runtime
from services.agent_runtime import codex_default_task_runner, temporal_codex_task_workflow


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


class CodexDefaultTaskRunnerTests(unittest.TestCase):
    def assert_authority_boundary(self, state: dict) -> None:
        self.assertTrue(state["not_source_of_truth"])
        self.assertTrue(state["not_user_completion"])
        self.assertEqual(state["authority_boundary"]["source_of_truth"], "external_mature_runtime")
        self.assertTrue(state["decision"]["not_source_of_truth"])
        self.assertTrue(state["decision"]["not_user_completion"])

    def _patch_temporal_with_task_bound_worker(self):
        original = temporal_codex_task_workflow.run_live_temporal_workflow

        async def fake_run_live_temporal_workflow(payload):
            self.assertTrue(payload.get("execute_worker_turn"))
            self.assertTrue(payload.get("execute_codex_worker"))
            self.assertIn(
                temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                payload.get("codex_worker_prompt", ""),
            )
            return {
                "schema_version": "xinao.temporal_codex_task_workflow.result.v1",
                "task_id": payload["task_id"],
                "temporal_live_route": True,
                "temporal_workflow_completed": True,
                "workflow_completed_is_not_user_complete": True,
                "user_task_complete": False,
                "completion_decision": {"status": "partial", "stop_allowed": False},
                "current_task_owner": {
                    "task_id": payload["task_id"],
                    "owner_kind": "TemporalWorkflow",
                    "stop_gate_scope": "current_task_id_only",
                    "execution_event_source": "Temporal Event History",
                },
                "activities": [
                    {
                        "activity": "codex_worker_turn",
                        "status": "activity_gate_checked",
                        "task_bound_worker": True,
                        "fallback_canary_only": False,
                        "codex_jsonl_is_execution_evidence": True,
                        "jsonl_exists": True,
                        "jsonl_path": str(Path(payload["runtime_root"]) / "codex-events.jsonl"),
                        "final_path": str(Path(payload["runtime_root"]) / "final.md"),
                        "expected_marker": temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                        "expected_marker_seen": True,
                        "worker_task_id": payload.get("codex_worker_task_id", ""),
                        "command_surface": "Temporal activity -> codex_activator -> codex exec --json",
                        "execute_worker_turn": payload.get("execute_worker_turn") is True,
                        "actual_provider_id": "codex_exec",
                    }
                ],
            }

        temporal_codex_task_workflow.run_live_temporal_workflow = fake_run_live_temporal_workflow
        self.addCleanup(
            setattr, temporal_codex_task_workflow, "run_live_temporal_workflow", original
        )

    def test_default_runner_forces_partial_when_complete_fixture_not_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = codex_default_task_runner.run_task(
                task_id="runner_partial",
                user_goal="unit",
                mode="complete",
                runtime_root=Path(tmp),
                base_url="http://127.0.0.1:9",
                allow_complete_fixture=False,
                use_temporal_binding=False,
            )

        self.assert_authority_boundary(state)
        self.assertEqual(state["requested_mode"], "partial")
        self.assertEqual(state["status"], "default_task_legacy_completion_gate_checked")
        self.assertTrue(state["legacy_completion_gate_fallback"])
        self.assertEqual(state["decision"]["status"], "partial")
        self.assertFalse(state["stop_allowed"])
        self.assertTrue(state["frontier_preserved"])

    def test_default_runner_complete_fixture_still_goes_through_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            runroot = Path(tmp)
            write_valid_side_audit(runroot, "runner_complete")
            write_current_task_owner(runroot, "runner_complete")
            state = codex_default_task_runner.run_task(
                task_id="runner_complete",
                user_goal="unit",
                mode="complete",
                runtime_root=runroot,
                base_url="http://127.0.0.1:9",
                allow_complete_fixture=True,
                use_temporal_binding=False,
            )

        self.assert_authority_boundary(state)
        self.assertEqual(state["status"], "default_task_legacy_completion_gate_checked")
        self.assertEqual(state["decision"]["status"], "complete_allowed")
        self.assertFalse(state["complete_allowed"])
        self.assertFalse(state["stop_allowed"])
        self.assertTrue(state["production_completion_forbidden"])
        self.assertTrue(state["legacy_gate_complete_allowed_readback"])
        self.assertEqual(
            state["named_blocker"], "LEGACY_COMPLETION_GATE_FALLBACK_NOT_PRODUCTION_AUTHORITY"
        )
        self.assertIn("completion_claim_payloads", state["claim_path"])
        self.assertTrue(
            state["completion_evidence"]["rollback_execution_result"]["rollback_executable"]
        )

    def test_default_runner_can_trigger_rollback_on_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = codex_default_task_runner.run_task(
                task_id="runner_rollback",
                user_goal="unit rollback",
                mode="partial",
                runtime_root=Path(tmp),
                base_url="http://127.0.0.1:9",
                trigger_rollback_on_partial=True,
                use_temporal_binding=False,
            )

        self.assert_authority_boundary(state)
        self.assertTrue(state["rollback_triggered"])
        self.assertEqual(
            state["completion_evidence"]["rollback_execution_result"]["status"],
            "rollback_execution_executed",
        )

    def test_default_runner_uses_temporal_binding_by_default(self):
        self._patch_temporal_with_task_bound_worker()
        with tempfile.TemporaryDirectory() as tmp:
            state = codex_default_task_runner.run_task(
                task_id="runner_temporal",
                user_goal="unit",
                mode="complete",
                runtime_root=Path(tmp),
            )

        self.assert_authority_boundary(state)
        self.assertEqual(state["status"], "default_task_live_temporal_binding_checked")
        self.assertTrue(state["durable_default_enforced"])
        self.assertTrue(state["temporal_live_route_required"])
        self.assertFalse(state["temporal_compat_rescue_allowed"])
        self.assertTrue(state["task_bound_worker_turn_required"])
        self.assertTrue(state["task_bound_codex_worker_required"])
        self.assertTrue(state["execute_codex_worker_legacy_alias"])
        self.assertTrue(state["codex_worker_evidence"]["accepted_as_task_bound_worker_evidence"])
        self.assertTrue(state["codex_worker_evidence"]["execute_worker_turn"])
        self.assertEqual(state["codex_worker_evidence"]["actual_provider_id"], "codex_exec")
        self.assertFalse(state["legacy_completion_gate_fallback"])
        self.assertEqual(state["gate_source"], "live_temporal_codex_task_workflow")
        self.assertEqual(state["decision"]["status"], "partial")
        self.assertFalse(state["complete_allowed"])
        self.assertEqual(state["current_task_owner"]["task_id"], "runner_temporal")
        self.assertEqual(state["current_task_owner"]["stop_gate_scope"], "current_task_id_only")

    def test_default_runner_blocks_local_temporal_compat_without_explicit_rescue(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = codex_default_task_runner.run_task(
                task_id="runner_local_blocked",
                user_goal="unit",
                mode="partial",
                runtime_root=Path(tmp),
                use_live_temporal=False,
            )

        self.assertEqual(state["status"], "blocked_temporal_live_route_required")
        self.assertEqual(state["named_blocker"], "BLOCKED_TEMPORAL_LIVE_ROUTE_REQUIRED")
        self.assertTrue(state["temporal_live_route_required"])
        self.assertFalse(state["temporal_compat_rescue_allowed"])


if __name__ == "__main__":
    unittest.main()
