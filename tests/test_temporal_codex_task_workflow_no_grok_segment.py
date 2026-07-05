import json
import tempfile
import unittest
from pathlib import Path

from services.agent_runtime import temporal_codex_task_workflow


class TemporalWorkflowNoGrokSegmentAuditTests(unittest.TestCase):
    def test_default_chain_has_no_grok_segment_audit_entrypoints(self):
        self.assertFalse(hasattr(temporal_codex_task_workflow, "segment_audit_gate_activity"))
        self.assertFalse(hasattr(temporal_codex_task_workflow, "_grok_segment_waiting_decision_override"))
        self.assertFalse(hasattr(temporal_codex_task_workflow, "grok_wait_l1_continuation_worker_payload"))
        self.assertFalse(hasattr(temporal_codex_task_workflow, "segment_gate_allows_l1_continuation"))
        self.assertFalse(hasattr(temporal_codex_task_workflow.TemporalCodexTaskWorkflow, "grok_segment_verdict"))

    def test_local_flow_ignores_stale_grok_segment_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            stale_gate = runtime_root / "state" / "grok_l1_l2_segment_gate" / "latest.json"
            stale_gate.parent.mkdir(parents=True, exist_ok=True)
            stale_gate.write_text(
                json.dumps(
                    {
                        "task_id": "old-task",
                        "status": "WAITING_GROK_SEGMENT_AUDIT",
                        "named_blocker": "GROK_SEGMENT_AUDIT_REQUIRED",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="unit_no_grok_segment_default_chain",
                user_goal="unit no grok segment audit",
                mode="partial",
                runtime_root=runtime_root,
            )

        activity_names = [item.get("activity") for item in result["activities"]]
        self.assertNotIn("segment_audit_gate", activity_names)
        self.assertEqual(result["completion_decision"]["status"], "partial")
        self.assertNotIn("segment_audit_gate", result)
        self.assertNotIn("workflow_waiting_grok_segment_audit", result)
        self.assertNotIn("grok_report_ref", result)

    def test_panel_writeback_does_not_emit_grok_report_or_router(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            output = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="unit_panel_no_grok_report",
                user_goal="unit panel no grok report",
                mode="partial",
                runtime_root=runtime_root,
            )
            panel_ref = Path(
                next(
                    item
                    for item in output["activities"]
                    if item.get("activity") == "panel_writeback_zh"
                )["panel_task_ref"]
            )
            panel = json.loads(panel_ref.read_text(encoding="utf-8"))

        self.assertNotIn("grok_report_ref", panel)
        self.assertNotIn("human_egress_router_ref", panel)
        self.assertNotIn("segment_audit_gate", panel)
        self.assertEqual(panel["segment_audit_status_cn"], "段审状态：不参与默认主链")
        self.assertIn("worker ledger", panel["status_line_cn"])


if __name__ == "__main__":
    unittest.main()
