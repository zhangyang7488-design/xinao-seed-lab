import tempfile
import unittest
import json
import asyncio
import datetime as dt
from unittest import mock
from pathlib import Path

from services.agent_runtime import codex_default_task_runner
from services.agent_runtime import temporal_codex_task_workflow
from services.agent_runtime import langgraph_task_runner
from services.codex_activator.codex_activator import guard_prompt


def assert_authority_boundary(testcase: unittest.TestCase, payload: dict):
    testcase.assertTrue(payload["not_source_of_truth"])
    testcase.assertTrue(payload["not_user_completion"])
    boundary = payload["authority_boundary"]
    testcase.assertEqual(boundary["source_of_truth"], "external_mature_runtime")
    testcase.assertTrue(boundary["not_source_of_truth"])
    testcase.assertTrue(boundary["not_user_completion"])
    testcase.assertTrue(boundary["workflow_completed_is_not_user_complete"])


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def write_seed_cortex_dp_sidecar_capability_reuse(runtime_root: Path) -> None:
    payload = {
        "schema_version": "xinao.seed_cortex.sidecar_capability_reuse.v1",
        "status": "sidecar_capability_reuse_verified",
        "work_id": "xinao_seed_cortex_phase0_20260701",
        "capabilities": {
            "deepseek_dp_sidecar": {
                "status": "verified_reusable_dp_sidecar",
                "role": "dp_sidecar_execution_port_no_repo_mutation",
                "route": (
                    "python services/agent_runtime/agent_runtime.py "
                    "--runtime D:/XINAO_RESEARCH_RUNTIME draft-deepseek"
                ),
                "draft_path": str(runtime_root / "drafts" / "deepseek" / "draft.md"),
                "delegation_path": str(
                    runtime_root / "state" / "delegations" / "deepseek" / "task.json"
                ),
                "review_index_path": str(
                    runtime_root
                    / "agent_runtime"
                    / "codex_review_queue"
                    / "review_index.json"
                ),
                "max_parallel_verified_ref": str(
                    runtime_root
                    / "state"
                    / "parallel_draft_batch"
                    / "seedcortex-parallel-dp-002.json"
                ),
                "parallel_cost_ledger_ref": str(
                    runtime_root
                    / "state"
                    / "parallel_draft_batch"
                    / "seedcortex-parallel-dp-002.cost.json"
                ),
                "parallel_merge_review_ref": str(
                    runtime_root
                    / "state"
                    / "parallel_draft_batch"
                    / "seedcortex-parallel-dp-002.merge_review.json"
                ),
                "execution_modes": [
                    "draft",
                    "eval",
                    "contradiction",
                    "extraction",
                    "audit",
                    "search",
                    "citation_verify",
                    "provider_probe",
                ],
                "dp_search_is_mode_not_port_definition": True,
                "final_owner": "codex",
                "not_source_of_truth": True,
                "not_completion_decision": True,
                "not_execution_controller": True,
                "not_old_control_plane": True,
                "not_phase1_unlock": True,
                "may_mutate_repo_directly": False,
            }
        },
        "parallel_policy": {
            "codex_role": "main_integrator_verifier_and_repo_owner",
            "deepseek_role": "dp_sidecar_execution_port_no_repo_mutation",
            "deepseek_execution_modes": [
                "draft",
                "eval",
                "contradiction",
                "extraction",
                "audit",
                "search",
                "citation_verify",
                "provider_probe",
            ],
            "dp_search_is_mode_not_port_definition": True,
            "deepseek_search_role": "external_research_sourceledger_claimcard_sidecar_no_repo_mutation",
            "local_model_role": "cheap_readonly_summary_classification_memory_compression",
            "grok_role": "external_research_planning_aid_visible_gateway_no_owner",
            "outputs_must_enter": "Codex fan-in, ArtifactAcceptanceQueue, and verifier before promotion.",
            "forbidden": [
                "sidecar writes repo directly",
                "sidecar claims completion",
                "sidecar becomes old 5d33 control plane",
                "latest.json as truth",
                "worker PASS as completion",
            ],
        },
        "authority_boundary": {
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
        },
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    latest = runtime_root / "state" / "seed_cortex_sidecar_capability_reuse" / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class AssignmentDrivenImplementationTimeoutTest(unittest.TestCase):
    def test_continue_same_task_worker_uses_assignment_timeout_and_not_segment_pass_default(self):
        payload = temporal_codex_task_workflow.continue_same_task_worker_payload(
            {
                "runtime_root": r"D:\XINAO_CLEAN_RUNTIME",
                "task_id": "unit_continue_same_task_assignment",
                "workflow_id": "wf-unit-continue",
                "user_goal": "5d33 assignment-driven implementation",
            },
            {
                "worker_kind": "implementation_worker",
                "phase_scope": "5d33_assignment_driven_implementation_narrow_fix",
                "codex_worker_timeout_sec": 7200,
                "work_package": {"files": ["runtime/ingress/clean_ingress.py"]},
                "verification": ["python -m py_compile runtime/ingress/clean_ingress.py"],
                "user_goal": "implementation must exceed five minutes when assignment says so",
            },
            1,
        )

        self.assertEqual(payload["codex_worker_timeout_sec"], 7200)
        self.assertEqual(payload["codex_worker_activity_timeout_sec"], 7200)
        self.assertEqual(payload["worker_kind"], "implementation_worker")
        self.assertTrue(payload["implementation_worker_required"])
        self.assertFalse(payload["segment_pass_next_worker_required"])
        self.assertEqual(payload["mature_execution_carrier"], "codex_exec_json_app_server_sdk_worker")
        self.assertEqual(payload["worker_evidence_contract"], "task_bound_codex_exec_jsonl_or_app_server_sdk")
        self.assertEqual(payload["authorization_lane"], "codex_a_brain_dispatch")
        self.assertEqual(payload["continuation_authorization_lane"], "codex_a_brain_dispatch")
        self.assertEqual(payload["segment_audit_authorization_lane"], "grok_segment_audit_dual_visible_and_backend_verdict")
        self.assertEqual(payload["segment_audit_verdict_authorization_lane"], "grok_segment_audit_dual_visible_and_backend_verdict")
        self.assertFalse(payload["waiting_grok_blocks_continuation"])
        self.assertTrue(payload["waiting_grok_blocks_completion_stop_l2"])
        self.assertFalse(payload["grok_mainchain_authorization_allowed"])
        self.assertFalse(payload["segment_pass_checker_default"])
        self.assertIn("Do not use the old segment-pass four-line checker format", payload["codex_worker_prompt"])

    def test_continue_same_task_worker_blocks_missing_assignment_scope(self):
        payload = temporal_codex_task_workflow.continue_same_task_worker_payload(
            {
                "runtime_root": r"D:\XINAO_CLEAN_RUNTIME",
                "task_id": "unit_continue_same_task_missing_assignment_scope",
                "workflow_id": "wf-unit-missing-assignment",
                "user_goal": "missing assignment must not start implementation default",
            },
            {
                "worker_kind": "implementation_worker",
                "phase_scope": "5d33_assignment_driven_implementation_narrow_fix",
                "codex_worker_timeout_sec": 7200,
                "assignment_missing_fields": ["work_package", "verification"],
            },
            1,
        )

        self.assertFalse(payload["execute_codex_worker"])
        self.assertEqual(payload["named_blocker"], "BLOCKED_NO_WORKER_ASSIGNMENT_SCOPE")
        self.assertIn("work_package", payload["assignment_missing_fields"])
        self.assertIn("verification", payload["assignment_missing_fields"])
        self.assertFalse(payload["segment_pass_next_worker_required"])

    def test_continue_same_task_worker_blocks_segment_pass_as_implementation_default(self):
        payload = temporal_codex_task_workflow.continue_same_task_worker_payload(
            {
                "runtime_root": r"D:\XINAO_CLEAN_RUNTIME",
                "task_id": "unit_continue_same_task_invalid_segment_pass_default",
                "workflow_id": "wf-unit-invalid-assignment",
                "user_goal": "segment-pass must not become implementation default",
            },
            {
                "worker_kind": "segment_pass_checker",
                "phase_scope": "Phase2E_execution_default_carrier_enforcement",
                "codex_worker_prompt": "CALLER PROMPT MUST NOT RUN",
                "codex_worker_timeout_sec": 7200,
                "work_package": {"files": ["runtime/ingress/clean_ingress.py"]},
                "verification": ["python -m unittest tests.test_ingress_result_recovery"],
                "segment_pass_checker_default": True,
                "worker_assignment_ref": r"D:\XINAO_CLEAN_RUNTIME\state\worker_assignment\invalid.json",
            },
            1,
        )

        self.assertFalse(payload["execute_codex_worker"])
        self.assertEqual(payload["named_blocker"], "BLOCKED_INVALID_WORKER_ASSIGNMENT_SCOPE")
        self.assertIn("worker_kind_not_implementation_worker", payload["assignment_invalid_fields"])
        self.assertIn("segment_pass_checker_not_implementation_worker", payload["assignment_invalid_fields"])
        self.assertNotIn("CALLER PROMPT MUST NOT RUN", payload["codex_worker_prompt"])
        self.assertFalse(payload["assignment_driven_dispatch"])
        self.assertFalse(payload["implementation_worker_required"])
        self.assertFalse(payload["segment_pass_checker_default"])
        self.assertEqual(payload["codex_a_role"], "brain_turn_and_worker_dispatch_coordinator_only")
        self.assertFalse(payload["codex_a_execution_owner"])

    def test_assignment_dag_auto_continue_prepares_one_ready_same_workflow_signal(self):
        task_id = "unit_assignment_dag_auto_continue"
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            assignment_dir = runtime_root / "state" / "worker_assignment"
            assignment_dir.mkdir(parents=True, exist_ok=True)
            assignment = {
                "task_id": task_id,
                "source_task_id": task_id,
                "workflow_id": "wf-unit-dag",
                "workflow_run_id": "run-unit-dag",
                "assignment_id": "assignment-unit-dag",
                "dag_scope": "unit_dag_scope",
                "objective_cn": "unit objective",
                "phase_execution": {
                    "worker_kind": "implementation_worker",
                    "phase_scope": "unit_phase_scope",
                    "work_package": {"objective": "old objective", "files": ["old.py"]},
                },
                "assignment_dag": {
                    "next_ready_node_id": "phase5_observability_discovery_increment",
                    "blocked_terminal_node_id": "phase7_completion_claim_side_audit_gate",
                    "nodes": [
                        {
                            "id": "phase5_observability_discovery_increment",
                            "status": "ready_next",
                            "files": ["runtime/ingress/clean_ingress.py"],
                            "acceptance": ["A/B/C/D/E/F read model joined"],
                        },
                        {
                            "id": "phase7_completion_claim_side_audit_gate",
                            "status": "blocked_until_all_prior_evidence_and_side_audit",
                        },
                    ],
                },
            }
            (assignment_dir / f"{task_id}.json").write_text(json.dumps(assignment, ensure_ascii=False), encoding="utf-8")

            signal = temporal_codex_task_workflow.assignment_dag_auto_continue_signal(
                runtime_root,
                task_id,
                {"workflow_id": "wf-unit-dag", "workflow_run_id": "run-unit-dag"},
            )
            duplicate = temporal_codex_task_workflow.assignment_dag_auto_continue_signal(
                runtime_root,
                task_id,
                {"continue_same_task_signal": {"assignment_dag_node_id": "phase5_observability_discovery_increment"}},
            )
            assignment["assignment_dag"]["next_ready_node_id"] = "phase7_completion_claim_side_audit_gate"
            (assignment_dir / f"{task_id}.json").write_text(json.dumps(assignment, ensure_ascii=False), encoding="utf-8")
            terminal = temporal_codex_task_workflow.assignment_dag_auto_continue_signal(runtime_root, task_id, {})

        self.assertEqual(signal["task_id"], task_id)
        self.assertEqual(signal["routing_verb"], "continue_same_task")
        self.assertEqual(signal["source_kind"], "assignment_dag_auto_continue")
        self.assertEqual(signal["workflow_id"], "wf-unit-dag")
        self.assertEqual(signal["workflow_run_id"], "run-unit-dag")
        self.assertEqual(signal["assignment_dag_node_id"], "phase5_observability_discovery_increment")
        self.assertEqual(signal["phase_execution"]["work_package"]["next_ready_node_id"], "phase5_observability_discovery_increment")
        self.assertEqual(len(signal["phase_execution"]["work_package"]["work_items"]), 1)
        self.assertEqual(signal["phase_execution"]["work_package"]["files"], ["runtime/ingress/clean_ingress.py"])
        self.assertEqual(signal["phase_execution"]["verification"], ["A/B/C/D/E/F read model joined"])
        self.assertEqual(signal["phase_execution"]["timeout_sec"], 1800)
        self.assertEqual(signal["codex_worker_timeout_sec"], 1800)
        worker_payload = temporal_codex_task_workflow.continue_same_task_worker_payload(
            {
                "runtime_root": str(runtime_root),
                "task_id": task_id,
                "workflow_id": "wf-unit-dag",
                "workflow_run_id": "run-unit-dag",
            },
            signal,
            2,
        )
        self.assertTrue(worker_payload["execute_codex_worker"])
        self.assertTrue(worker_payload["implementation_worker_required"])
        self.assertEqual(worker_payload["named_blocker"], "")
        self.assertTrue(signal["assignment_dag_auto_continue"])
        self.assertEqual(signal["authorization_lane"], "codex_a_brain_dispatch")
        self.assertEqual(signal["continuation_authorization_lane"], "codex_a_brain_dispatch")
        self.assertEqual(signal["segment_audit_authorization_lane"], "grok_segment_audit_dual_visible_and_backend_verdict")
        self.assertFalse(signal["waiting_grok_blocks_continuation"])
        self.assertFalse(signal["spawn_new_owner_allowed"])
        self.assertFalse(signal["completion_claim_allowed"])
        self.assertTrue(signal["not_user_completion"])
        self.assertEqual(duplicate, {})
        self.assertEqual(terminal, {})

    def test_codex_worker_activity_timeout_follows_worker_timeout_above_five_minutes(self):
        timeout = temporal_codex_task_workflow.codex_worker_activity_timeout(
            {"codex_worker_timeout_sec": 7200}
        )

        self.assertEqual(timeout.total_seconds(), 7320)

    def test_assignment_dag_workerpool_node_raises_short_supervisor_timeout(self):
        task_id = "unit_assignment_dag_workerpool_timeout_floor"
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            assignment_dir = runtime_root / "state" / "worker_assignment"
            assignment_dir.mkdir(parents=True, exist_ok=True)
            assignment = {
                "task_id": task_id,
                "workflow_id": "wf-unit-workerpool-timeout",
                "workflow_run_id": "run-unit-workerpool-timeout",
                "assignment_id": "assignment-unit-workerpool-timeout",
                "assignment_dag": {
                    "next_ready_node_id": "parallel_draft_batch_bind",
                    "nodes": [
                        {
                            "id": "parallel_draft_batch_bind",
                            "status": "ready_next",
                            "lanes": [{"lane_id": "mdwp-unit-draft-01"}],
                        }
                    ],
                },
            }
            (assignment_dir / f"{task_id}.json").write_text(
                json.dumps(assignment, ensure_ascii=False),
                encoding="utf-8",
            )

            signal = temporal_codex_task_workflow.assignment_dag_auto_continue_signal(
                runtime_root,
                task_id,
                {
                    "workflow_id": "wf-unit-workerpool-timeout",
                    "workflow_run_id": "run-unit-workerpool-timeout",
                    "codex_worker_timeout_sec": 120,
                    "implementation_worker_timeout_sec": 120,
                },
            )

        self.assertEqual(signal["assignment_dag_node_id"], "parallel_draft_batch_bind")
        self.assertEqual(signal["codex_worker_timeout_sec"], 1800)
        self.assertEqual(signal["implementation_worker_timeout_sec"], 1800)
        self.assertEqual(signal["phase_execution"]["timeout_sec"], 1800)
        self.assertEqual(signal["phase_execution"]["max_activity_timeout_sec"], 1800)

    def test_continue_same_task_worker_uses_nested_phase_execution(self):
        payload = temporal_codex_task_workflow.continue_same_task_worker_payload(
            {
                "runtime_root": r"D:\XINAO_CLEAN_RUNTIME",
                "task_id": "unit_continue_same_task_nested_phase",
                "workflow_id": "wf-unit-nested-phase",
                "user_goal": "nested phase execution must drive implementation",
            },
            {
                "phase_execution": {
                    "worker_kind": "implementation_worker",
                    "phase_scope": "Phase2_WP1_WP2_assignment_driven_infinite_continuation",
                    "timeout_sec": 1800,
                    "max_activity_timeout_sec": 3600,
                    "work_package": {"files": ["runtime/ingress/clean_ingress.py"]},
                    "verification": ["python -m unittest tests.test_temporal_codex_task_workflow"],
                },
                "codex_worker_prompt": "CALLER PROMPT MUST NOT RUN",
                "worker_assignment_ref": r"D:\XINAO_CLEAN_RUNTIME\state\worker_assignment\nested.json",
            },
            1,
        )

        self.assertEqual(payload["worker_kind"], "implementation_worker")
        self.assertEqual(payload["phase_scope"], "Phase2_WP1_WP2_assignment_driven_infinite_continuation")
        self.assertEqual(payload["codex_worker_timeout_sec"], 1800)
        self.assertEqual(payload["codex_worker_activity_timeout_sec"], 3600)
        self.assertEqual(payload["work_package"]["files"], ["runtime/ingress/clean_ingress.py"])
        self.assertNotIn("CALLER PROMPT MUST NOT RUN", payload["codex_worker_prompt"])
        self.assertTrue(payload["caller_prompt_ignored_by_assignment"])
        self.assertFalse(payload["segment_pass_next_worker_required"])

    def test_implementation_worker_ignores_caller_prompt_and_uses_assignment_package(self):
        payload = temporal_codex_task_workflow.continue_same_task_worker_payload(
            {
                "runtime_root": r"D:\XINAO_CLEAN_RUNTIME",
                "task_id": "unit_continue_same_task_prompt_assignment",
                "workflow_id": "wf-unit-prompt",
                "user_goal": "5d33 assignment-driven implementation",
            },
            {
                "worker_kind": "implementation_worker",
                "phase_scope": "5d33_assignment_driven_implementation_narrow_fix",
                "codex_worker_prompt": "CALLER PROMPT MUST NOT RUN",
                "caller_codex_worker_prompt": "CALLER PROMPT MUST NOT RUN",
                "codex_worker_timeout_sec": 7200,
                "worker_assignment_ref": r"D:\XINAO_CLEAN_RUNTIME\state\worker_assignment\unit.json",
                "work_package": {"target_files": ["runtime/ingress/clean_ingress.py"]},
                "verification": ["pytest narrow"],
            },
            1,
        )

        self.assertNotIn("CALLER PROMPT MUST NOT RUN", payload["codex_worker_prompt"])
        self.assertIn("work_package_json=", payload["codex_worker_prompt"])
        self.assertIn("runtime/ingress/clean_ingress.py", payload["codex_worker_prompt"])
        self.assertIn("pytest narrow", payload["codex_worker_prompt"])
        self.assertTrue(payload["caller_prompt_ignored_by_assignment"])

    def test_partial_continuation_non_partial_does_not_require_next_worker_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = asyncio.run(
                temporal_codex_task_workflow.partial_continuation_dispatch_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": "unit_non_partial_no_next_worker",
                        "completion_decision": {"status": "complete_allowed", "stop_allowed": True},
                        "segment_audit_gate": {},
                    }
                )
            )

        self.assertEqual(result["status"], "skipped_completion_claim_not_partial")
        self.assertFalse(result["continuation_dispatched"])

    def test_partial_continuation_prepares_assignment_dag_auto_continue(self):
        task_id = "unit_assignment_dag_auto_continue"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assignment_dir = root / "state" / "worker_assignment"
            assignment_dir.mkdir(parents=True)
            assignment = {
                "schema_version": "xinao.worker_assignment.v2.dag",
                "task_id": task_id,
                "source_task_id": task_id,
                "workflow_id": "wf-dag-unit",
                "workflow_run_id": "run-dag-unit",
                "assignment_id": "UNIT_DAG",
                "dag_scope": "unit_full_dag",
                "objective_cn": "unit dag continuation",
                "spawn_new_owner_allowed": False,
                "completion_claim_allowed": False,
                "assignment_dag": {
                    "next_ready_node_id": "phase5_observability_discovery_increment",
                    "blocked_terminal_node_id": "phase7_completion_claim_side_audit_gate",
                    "nodes": [
                        {
                            "id": "phase5_observability_discovery_increment",
                            "status": "ready_next",
                            "files": ["runtime/ingress/clean_ingress.py"],
                            "acceptance": ["snapshot joined"],
                        }
                    ],
                },
                "phase_execution": {
                    "worker_kind": "implementation_worker",
                    "phase_scope": "5d33_full_assignment_dag_auto_continue",
                    "timeout_sec": 7200,
                    "work_package": {"objective": "old", "next_ready_node_id": "phase6_repo_runtime_sync_and_git"},
                    "verification": ["old verify"],
                },
            }
            (assignment_dir / f"{task_id}.json").write_text(json.dumps(assignment, ensure_ascii=False), encoding="utf-8")
            result = asyncio.run(
                temporal_codex_task_workflow.partial_continuation_dispatch_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": task_id,
                        "workflow_id": "wf-dag-unit",
                        "workflow_run_id": "run-dag-unit",
                        "completion_decision": {"status": "partial", "stop_allowed": False},
                        "segment_audit_gate": {"status": "WAITING_GROK_SEGMENT_AUDIT"},
                        "segment_pass_next_worker": {},
                        "continue_same_task_signal": {
                            "phase_execution": {
                                "work_package": {"next_ready_node_id": "phase6_repo_runtime_sync_and_git"}
                            }
                        },
                    }
                )
            )

        self.assertEqual(result["status"], "assignment_dag_auto_continue_signal_prepared")
        self.assertEqual(result["named_blocker"], "")
        self.assertTrue(result["assignment_dag_auto_continue"])
        self.assertTrue(result["auto_continue_same_workflow"])
        self.assertTrue(result["one_segment_does_not_wait_for_user"])
        self.assertEqual(result["authorization_lane"], "codex_a_brain_dispatch")
        self.assertEqual(result["continuation_authorization_lane"], "codex_a_brain_dispatch")
        self.assertEqual(result["segment_audit_authorization_lane"], "grok_segment_audit_dual_visible_and_backend_verdict")
        self.assertFalse(result["waiting_grok_blocks_continuation"])
        signal = result["auto_continue_same_task_signal"]
        self.assertEqual(signal["assignment_dag_node_id"], "phase5_observability_discovery_increment")
        self.assertEqual(signal["workflow_id"], "wf-dag-unit")
        self.assertEqual(signal["workflow_run_id"], "run-dag-unit")
        self.assertEqual(signal["authorization_lane"], "codex_a_brain_dispatch")
        self.assertEqual(signal["segment_audit_authorization_lane"], "grok_segment_audit_dual_visible_and_backend_verdict")
        self.assertFalse(signal["spawn_new_owner_allowed"])
        self.assertFalse(signal["completion_claim_allowed"])
        self.assertEqual(signal["phase_execution"]["worker_kind"], "implementation_worker")
        self.assertEqual(signal["phase_execution"]["work_package"]["next_ready_node_id"], "phase5_observability_discovery_increment")
        self.assertEqual(signal["phase_execution"]["timeout_sec"], 7200)
        self.assertEqual(signal["codex_worker_timeout_sec"], 7200)

    def test_workflow_enqueues_assignment_dag_auto_continue_signal(self):
        wf = temporal_codex_task_workflow.TemporalCodexTaskWorkflow()
        wf._enqueue_assignment_dag_auto_continue({
            "auto_continue_same_workflow": True,
            "auto_continue_same_task_signal": {
                "task_id": "unit",
                "assignment_dag_node_id": "phase5_observability_discovery_increment",
            },
        })

        self.assertEqual(len(wf.continue_same_task_signals), 1)
        self.assertEqual(
            wf.continue_same_task_signals[0]["assignment_dag_node_id"],
            "phase5_observability_discovery_increment",
        )

    def test_workflow_preserves_assignment_dag_auto_continue_while_replaying(self):
        wf = temporal_codex_task_workflow.TemporalCodexTaskWorkflow()
        with mock.patch.object(temporal_codex_task_workflow.workflow.unsafe, "is_replaying", return_value=True):
            wf._enqueue_assignment_dag_auto_continue({
                "auto_continue_same_workflow": True,
                "auto_continue_same_task_signal": {
                    "task_id": "unit",
                    "assignment_dag_node_id": "phase5_observability_discovery_increment",
                },
            })

        self.assertEqual(len(wf.continue_same_task_signals), 1)
        self.assertEqual(
            wf.continue_same_task_signals[0]["assignment_dag_node_id"],
            "phase5_observability_discovery_increment",
        )

    def test_temporal_patch_markers_preserve_replay_compatibility_names(self):
        self.assertEqual(
            temporal_codex_task_workflow.TEMPORAL_PATCH_ASSIGNMENT_DRIVEN_PHASE_EXIT_SEGMENT_PASS,
            "assignment-driven-phase-exit-segment-pass-v1",
        )
        self.assertEqual(
            temporal_codex_task_workflow.TEMPORAL_PATCH_GROK_WAIT_L1_CONTINUATION_WORKER,
            "grok-wait-l1-continuation-worker-v1",
        )
        self.assertEqual(
            temporal_codex_task_workflow.TEMPORAL_PATCH_PHASE_EXIT_NO_GROK_WAIT_BEFORE_PARTIAL_CONTINUATION,
            "phase-exit-no-grok-wait-before-partial-continuation-v1",
        )
        self.assertEqual(
            temporal_codex_task_workflow.TEMPORAL_PATCH_SEED_CORTEX_WORKER_DISPATCH_LEDGER,
            "seed-cortex-worker-dispatch-ledger-v1",
        )
        self.assertEqual(
            temporal_codex_task_workflow.TEMPORAL_PATCH_SEED_CORTEX_DURABLE_PARALLEL_WAVE_PACKET,
            "seed-cortex-durable-parallel-wave-packet-v1",
        )
        self.assertEqual(
            temporal_codex_task_workflow.TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE,
            "seed-cortex-default-main-loop-trigger-candidate-v1",
        )
        self.assertEqual(
            temporal_codex_task_workflow.TEMPORAL_PATCH_SEED_CORTEX_SCHEDULER_INVOCATION_PACKET,
            "seed-cortex-scheduler-invocation-packet-v1",
        )
        self.assertEqual(
            temporal_codex_task_workflow.TEMPORAL_PATCH_SEED_CORTEX_ALLOCATION_PLAN,
            "seed-cortex-allocation-plan-v1",
        )
        patch_markers = temporal_codex_task_workflow.temporal_patch_marker_policy()[
            "patch_markers"
        ]
        self.assertEqual(
            patch_markers["seed_cortex_scheduler_invocation_packet"],
            temporal_codex_task_workflow.TEMPORAL_PATCH_SEED_CORTEX_SCHEDULER_INVOCATION_PACKET,
        )
        self.assertEqual(
            patch_markers["seed_cortex_allocation_plan"],
            temporal_codex_task_workflow.TEMPORAL_PATCH_SEED_CORTEX_ALLOCATION_PLAN,
        )

    def test_temporal_patch_helper_uses_temporal_marker_decision_when_available(self):
        with mock.patch.object(temporal_codex_task_workflow.workflow, "patched", return_value=False, create=True) as patched:
            enabled = temporal_codex_task_workflow.temporal_patch_enabled(
                temporal_codex_task_workflow.TEMPORAL_PATCH_PHASE_EXIT_NO_GROK_WAIT_BEFORE_PARTIAL_CONTINUATION
            )

        self.assertFalse(enabled)
        patched.assert_called_once_with(
            temporal_codex_task_workflow.TEMPORAL_PATCH_PHASE_EXIT_NO_GROK_WAIT_BEFORE_PARTIAL_CONTINUATION
        )

    def test_allocation_plan_activity_writes_temporal_evidence(self):
        original_seed_runtime = temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT = root
            self.addCleanup(
                setattr,
                temporal_codex_task_workflow,
                "SEED_CORTEX_RUNTIME_ROOT",
                original_seed_runtime,
            )
            write_json(
                root / "state" / "loop_runtime_state" / "latest.json",
                {
                    "schema_version": "xinao.codex_s.loop_runtime_state.v1",
                    "status": "phase3_temporal_activity_event_queue_wave_ready",
                    "active_workers": [{"worker_id": "temporal-worker"}],
                    "task_backlog": [{"task_item_id": "item-1"}],
                    "ready_frontier": [{"frontier_id": "frontier-1"}],
                    "draft_staging": {"staged_count": 3, "merged_count": 1, "unmerged_count": 0},
                    "source_gaps": [],
                    "next_frontier": [{"frontier_id": "next-1"}],
                    "capacity_by_lane_class": {
                        "dynamic_width_record": {
                            "width_candidates": {
                                "provider_available_slots": 6,
                                "independent_task_count": 8,
                            }
                        }
                    },
                    "validation": {"passed": True},
                },
            )
            write_json(
                root
                / "state"
                / "codex_native_provider_scheduler_phase4_20260704"
                / "latest.json",
                {
                    "schema_version": "xinao.codex_s.codex_native_provider_scheduler_phase4.v1",
                    "status": "codex_native_provider_scheduler_ready",
                    "provider_registry": {
                        "providers": [
                            {"provider_id": "qwen_prepaid_cheap_worker", "status": "ready"},
                            {"provider_id": "deepseek_dp", "status": "ready"},
                            {"provider_id": "codex_exec", "status": "ready"},
                            {"provider_id": "temporal_activity", "status": "ready"},
                        ]
                    },
                    "validation": {"passed": True},
                },
            )

            result = asyncio.run(
                temporal_codex_task_workflow.allocation_plan_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
                        "route_profile": temporal_codex_task_workflow.SEED_CORTEX_ROUTE_PROFILE,
                        "workflow_id": "unit-allocation-plan",
                        "wave_id": "unit-allocation-plan-wave",
                    }
                )
            )
            temporal_latest_exists = Path(
                result["allocation_plan_temporal_activity_latest_ref"]
            ).is_file()
            worker_brief_queue_exists = Path(result["worker_brief_queue_ref"]).is_file()

        self.assertEqual(result["activity"], "allocation_plan")
        self.assertEqual(result["status"], "activity_gate_checked")
        self.assertTrue(result["runtime_enforced"])
        self.assertEqual(
            result["runtime_enforced_scope"],
            "seed_cortex_temporal_allocation_plan_activity",
        )
        self.assertEqual(result["target_width_source"], "derived_from_runtime_feedback_inputs")
        self.assertFalse(result["fixed_20_or_50_used"])
        self.assertGreaterEqual(result["lane_class_count"], 3)
        self.assertTrue(temporal_latest_exists)
        self.assertTrue(worker_brief_queue_exists)
        self.assertFalse(result["completion_claim_allowed"])
        self.assertTrue(result["not_execution_controller"])

    def test_scheduler_invocation_spawned_lanes_include_allocation_plan_lanes(self):
        lanes = temporal_codex_task_workflow.scheduler_invocation_spawned_lanes(
            {"workflow_id": "unit-scheduler", "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID},
            {},
            {},
            {},
            {
                "activity": "allocation_plan",
                "allocation_plan_temporal_activity_latest_ref": "D:/runtime/state/allocation_plan/temporal_activity_latest.json",
                "readback_zh_ref": "D:/runtime/readback/zh/allocation_plan.md",
                "lane_allocations": [
                    {
                        "lane_id": "wave:cheap-draft",
                        "lane_class": "cheap_draft",
                        "provider_candidates": ["qwen_prepaid_cheap_worker", "deepseek_dp"],
                        "requested_width": 4,
                    },
                    {
                        "lane_id": "wave:merge-accept",
                        "lane_class": "merge_accept",
                        "provider_candidates": ["codex_s_foreground"],
                        "requested_width": 1,
                    },
                ],
            },
        )

        self.assertGreaterEqual(len(lanes), 2)
        self.assertTrue(
            any(lane["source"] == "allocation_plan_activity_result.lane_allocations" for lane in lanes)
        )
        cheap_lane = next(lane for lane in lanes if lane["lane_ref"] == "wave:cheap-draft")
        self.assertEqual(cheap_lane["lane_kind"], "dp_sidecar_execution")
        self.assertEqual(cheap_lane["lane_class"], "cheap_draft")
        self.assertEqual(cheap_lane["requested_width"], 4)
        merge_lane = next(lane for lane in lanes if lane["lane_ref"] == "wave:merge-accept")
        self.assertEqual(merge_lane["lane_kind"], "local_tool_lane")
        self.assertEqual(merge_lane["lane_class"], "merge_accept")

    def test_old_replay_patch_false_keeps_codex_a_mainchain_authorization(self):
        with mock.patch.object(temporal_codex_task_workflow.workflow, "patched", return_value=False, create=True):
            marker_enabled = temporal_codex_task_workflow.temporal_patch_enabled(
                temporal_codex_task_workflow.TEMPORAL_PATCH_GROK_WAIT_L1_CONTINUATION_WORKER
            )
        fields = temporal_codex_task_workflow.continuation_authorization_fields()

        self.assertFalse(marker_enabled)
        self.assertEqual(fields["mainchain_authorization_lane"], "codex_a_brain_dispatch")
        self.assertEqual(fields["continuation_authorization_lane"], "codex_a_brain_dispatch")
        self.assertFalse(fields["grok_mainchain_authorization_allowed"])
        self.assertFalse(fields["waiting_grok_blocks_continuation"])
        self.assertEqual(
            fields["temporal_patch_marker_policy"]["old_replay_mainchain_authorization_lane"],
            "codex_a_brain_dispatch",
        )
        self.assertTrue(
            fields["temporal_patch_marker_policy"]["old_replay_does_not_restore_grok_mainchain_authorization"]
        )
        self.assertTrue(fields["phase_exit_segment_audit_unchanged"])


def compiled_medium_task_object(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "task_object_id": task_id,
        "task_object_sha256": "task-sha",
        "source_refs_sha256": "refs-sha",
        "source_text_count": 4,
        "source_refs": [{"path": f"source-{idx}.txt"} for idx in range(4)],
        "semantic_object": "PROCESS_SOURCE_TEXTS_AS_MAXIMIZED_ROOT_OBJECT",
    }


def write_frontier_intake(runtime_root: Path, task_object: dict) -> None:
    completed = []
    for frontier_id in langgraph_task_runner.MATURE_MIGRATION_FRONTIER_IDS:
        result_path = runtime_root / "artifacts" / f"{frontier_id}.json"
        item = {
            "work_id": f"tw-{frontier_id[-6:].lower()}",
            "result_path": str(result_path),
            "passed": True,
            "status": "mature_carrier_work_item_passed",
            "named_blockers": [],
            "scope_mismatches": [],
            "source_item_id": f"langgraph_frontier_{frontier_id}",
            "source_task_id": task_object["task_id"],
            "task_object_sha256": task_object["task_object_sha256"],
            "source_refs_sha256": task_object["source_refs_sha256"],
            "source_text_count": task_object["source_text_count"],
            "semantic_object": task_object["semantic_object"],
            "verifier_contract_version": "langgraph_stategraph_frontier.v1",
        }
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        completed.append(item)
    path = runtime_root / "state" / "temporal_work_item_intake" / "tasks" / f"{task_object['task_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "xinao.temporal_work_item_intake.task_scoped.v1",
        "source_task_id": task_object["task_id"],
        "work_items": [],
        "completed_work_items": completed,
        "not_user_completion": True,
    }, ensure_ascii=False), encoding="utf-8")


def write_leg1_summon(runtime_root: Path, task_id: str) -> None:
    window_id = f"codex-to-grok-segment-audit-{task_id}"
    action_trace = runtime_root / "state" / "action_delivery_trace" / f"{task_id}.jsonl"
    action_trace.parent.mkdir(parents=True, exist_ok=True)
    action_trace.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "window_id": window_id,
                "event_name": "codex_to_grok_segment_audit_summon.sent",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    visible_trace = runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "visible_trace" / "latest.json"
    visible_trace.parent.mkdir(parents=True, exist_ok=True)
    visible_trace.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "window_id": window_id,
                "action_delivery_trace_task_id": task_id,
                "session_modified_or_inbox_written": True,
                "action_delivery_trace_same_window": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    frontend = runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "frontend_tui_send" / "tasks" / f"{task_id}.json"
    frontend.parent.mkdir(parents=True, exist_ok=True)
    frontend.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "frontend_tui_sent": True,
                "session_modified_after_send": True,
                "input_area_clicked_before_paste": True,
                "submit_enter_sent_after_paste": True,
                "native_keybd_event_typeahead": True,
                "old_inbox_only_is_not_full_visible_delivery": True,
                "rescue_cockpit_channel_preserved": True,
                "used_existing_grok_tui": True,
                "shortcut_launched": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summon = runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "tasks" / f"{task_id}.json"
    summon.parent.mkdir(parents=True, exist_ok=True)
    summon.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "segment_audit_ready": True,
                "workflow_waiting_grok_segment_audit": True,
                "delivery_mode": "dual_visible_and_backend",
                "window_id": window_id,
                "backend_task_ref": str(summon),
                "visible_trace_ref": str(visible_trace),
                "frontend_tui_send_ref": str(frontend),
                "action_delivery_trace_ref": str(action_trace),
                "frontend_tui_send_ref": str(runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "frontend_tui_send" / "tasks" / f"{task_id}.json"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    frontend = runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "frontend_tui_send" / "tasks" / f"{task_id}.json"
    frontend.parent.mkdir(parents=True, exist_ok=True)
    frontend.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "window_id": window_id,
                "frontend_tui_sent": True,
                "session_modified_after_send": True,
                "input_area_clicked_before_paste": True,
                "submit_enter_sent_after_paste": True,
                "native_keybd_event_typeahead": True,
                "old_inbox_only_is_not_full_visible_delivery": True,
                "rescue_cockpit_channel_preserved": True,
                "used_existing_grok_tui": True,
                "shortcut_launched": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def write_grok_leg2_verdict(runtime_root: Path, task_id: str, verdict: str = "pass") -> None:
    summon = runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "tasks" / f"{task_id}.json"
    action_trace = runtime_root / "state" / "action_delivery_trace" / f"{task_id}.jsonl"
    visible = runtime_root / "state" / "codexa_managed_visible_inject" / "latest.json"
    visible.parent.mkdir(parents=True, exist_ok=True)
    visible.write_text(
        json.dumps({"message_sha256": "unit-visible-sha", "evidence": {"session_modified_after_send": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    grok_path = runtime_root / "state" / "grok_l1_l2_segment_gate" / "tasks" / f"{task_id}.json"
    grok_path.parent.mkdir(parents=True, exist_ok=True)
    grok_path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "segment_audit_ready": True,
                "grok_verdict": verdict,
                "verdict": verdict,
                "verdict_delivery_mode": "dual_visible_and_backend",
                "delivery_mode": "dual_visible_and_backend",
                "dual_visible_and_backend_verdict": True,
                "backend_only_verdict": False,
                "backend_only_verdict_seen": False,
                "leg1_summon_ref": str(summon),
                "leg1_summon_cross_check_valid": True,
                "visible_inject_sha256": "unit-visible-sha",
                "evidence_refs": [str(summon), str(action_trace), str(visible)],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class TemporalCodexTaskWorkflowTests(unittest.TestCase):
    def test_workflow_completed_is_not_user_complete_when_claim_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="temporal_partial",
                user_goal="unit temporal partial",
                mode="partial",
                runtime_root=Path(tmp),
            )

        self.assertFalse(result["temporal_workflow_completed"])
        self.assertFalse(result["temporal_live_route"])
        self.assertEqual(result["verification_level"], temporal_codex_task_workflow.VERIFICATION_LEVEL_READ_MODEL)
        self.assertEqual(result["legacy_continuation_policy"], "legacy_rescue_only_not_mainline")
        self.assertTrue(result["workflow_completed_is_not_user_complete"])
        self.assertFalse(result["user_task_complete"])
        self.assertEqual(result["completion_decision"]["status"], "partial")
        self.assertEqual(result["current_task_owner"]["task_id"], "temporal_partial")
        self.assertEqual(result["current_task_owner"]["owner_kind"], "TemporalWorkflow")
        self.assertEqual(result["current_task_owner"]["stop_gate_scope"], "current_task_id_only")
        self.assertTrue(result["current_task_owner"]["compiled_task_object_sha256"])
        self.assertTrue(result["current_task_owner"]["source_refs_sha256"])
        self.assertTrue(result["current_task_owner"]["not_completion_decision"])
        assert_authority_boundary(self, result)
        for activity in result["activities"]:
            if activity["activity"] == "codex_worker_turn":
                continue
            if activity["activity"] == "segment_audit_gate":
                continue
            if activity["activity"] != "run_langgraph" or activity["status"] != "transient_failed_then_retried":
                self.assertIn("completion_decision", activity)
        codex_activity = next(item for item in result["activities"] if item["activity"] == "codex_worker_turn")
        self.assertEqual(codex_activity["status"], "skipped_until_route_requires_codex_execution")
        self.assertTrue(codex_activity["required_for_production_completion"])

    def test_workflow_carries_source_refs_into_langgraph_task_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "plan.txt"
            source.write_text("root repair plan", encoding="utf-8")
            source_ref = temporal_codex_task_workflow.file_source_ref(source)
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="temporal_source_ref",
                user_goal="unit temporal source ref",
                mode="partial",
                runtime_root=Path(tmp),
                source_refs=[source_ref],
            )

            graph = next(item for item in result["activities"] if item["activity"] == "run_langgraph")["graph_result"]
            task_object = graph["task_object"]
            claim_payload = graph["completion_claim_payload"]
            claim_activity = next(item for item in result["activities"] if item["activity"] == "completion_claim")
            self.assertEqual(result["source_refs"][0]["sha256"], source_ref["sha256"])
            self.assertFalse(result["source_refs"][0]["source_text_authority"])
            self.assertEqual(result["source_refs"][0]["semantic_input_role"], "non_authoritative_reference")
            self.assertEqual(task_object["source_refs"][0]["path"], str(source))
            self.assertEqual(claim_payload["current_task_owner"]["task_id"], "temporal_source_ref")
            self.assertEqual(claim_payload["current_task_owner"]["stop_gate_scope"], "current_task_id_only")
            self.assertTrue(Path(claim_activity["claim_path"]).is_file())
            persisted_claim = json.loads(Path(claim_activity["claim_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted_claim["current_task_owner"]["task_id"], "temporal_source_ref")
            self.assertIn("Observation", task_object["runtime_subject_loop_required"])
            self.assertTrue(task_object["minimum_reality_contact_required"])
            self.assertTrue(task_object["no_new_parallel_control_surface"])
            task_state = Path(tmp) / "state" / "temporal_codex_task_workflow" / "tasks" / "temporal_source_ref.json"
            self.assertTrue(task_state.is_file())
            owner_state = Path(tmp) / "state" / "current_task_owner" / "temporal_source_ref.json"
            self.assertTrue(owner_state.is_file())
            assignment_state = Path(tmp) / "state" / "worker_assignment" / "temporal_source_ref.json"
            self.assertTrue(assignment_state.is_file())
            assignment = json.loads(assignment_state.read_text(encoding="utf-8"))
            self.assertEqual(assignment["task_id"], "temporal_source_ref")
            self.assertTrue(assignment["codex_not_all_roles_at_once"])
            self.assertTrue(assignment["not_user_completion"])
            self.assertTrue(assignment["not_completion_decision"])
            self.assertEqual(result["current_task_owner"]["worker_assignment_ref"], str(assignment_state))
            self.assertEqual(result["worker_assignment_ref"], str(assignment_state))

    def test_reference_delivery_can_skip_promoting_current_task_owner_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner_dir = root / "state" / "current_task_owner"
            owner_dir.mkdir(parents=True)
            (owner_dir / "latest.json").write_text(json.dumps({
                "schema_version": "xinao.current_task_owner.v1",
                "task_id": "main-task",
            }), encoding="utf-8")

            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="reference-delivery",
                user_goal="reference only",
                mode="partial",
                runtime_root=root,
                promote_current_task_owner_latest=False,
            )

            latest = json.loads((owner_dir / "latest.json").read_text(encoding="utf-8"))
            scoped = json.loads((owner_dir / "reference-delivery.json").read_text(encoding="utf-8"))
            langgraph_latest = root / "state" / "langgraph_task_runner" / "latest.json"
            langgraph_scoped = root / "state" / "langgraph_task_runner" / "tasks" / "reference-delivery.json"
            self.assertFalse(result["promote_current_task_owner_latest"])
            self.assertEqual(latest["task_id"], "main-task")
            self.assertEqual(scoped["task_id"], "reference-delivery")
            self.assertFalse(langgraph_latest.exists())
            self.assertTrue(langgraph_scoped.is_file())

    def test_workflow_uses_compiled_task_object_as_lifecycle_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "report.txt"
            source.write_text("mature migration root object", encoding="utf-8")
            source_ref = temporal_codex_task_workflow.file_source_ref(source)
            compiled_task_object = {
                "schema_version": "xinao.codex_centric_task_object.v1",
                "task_id": "compiled_medium",
                "task_object_id": "compiled_medium",
                "task_object_sha256": "compiled-sha",
                "compiler_role": "object_compiler_only_not_lifecycle_owner",
                "source_refs": [source_ref],
                "source_refs_sha256": "refs-sha",
                "semantic_object": "PROCESS_SOURCE_TEXTS_AS_MAXIMIZED_ROOT_OBJECT",
                "acceptance_contract": {
                    "parent_object": "XINAO_GLOBAL_CANONICAL_SELF_CLEANSE_AND_UPLIFT_ROOT_REPAIR",
                    "root_object": "XINAO_GLOBAL_CANONICAL_SELF_CLEANSE_AND_UPLIFT_ROOT_REPAIR",
                    "migration_subobject": "XINAO_MATURE_RUNTIME_MIGRATION_FROM_STATUS_CARD_STACK",
                    "script_uplift_subdomain": "SUBDOMAIN_SCRIPT_SURFACE_UPLIFT",
                    "lifecycle_owner": "TemporalWorkflow",
                    "local_xinao_role": "object_compiler_and_chinese_read_model_only",
                },
            }
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="compiled_medium",
                user_goal="compiled object should not be rebuilt by local control plane",
                mode="partial",
                runtime_root=Path(tmp),
                source_refs=[source_ref],
                compiled_task_object=compiled_task_object,
            )

            graph = next(item for item in result["activities"] if item["activity"] == "run_langgraph")["graph_result"]
            task_object = graph["task_object"]
            self.assertEqual(result["compiled_task_object_sha256"], "compiled-sha")
            self.assertEqual(result["source_refs_sha256"], "refs-sha")
            self.assertEqual(result["acceptance_contract"]["lifecycle_owner"], "TemporalWorkflow")
            self.assertEqual(result["current_task_owner"]["compiled_task_object_sha256"], "compiled-sha")
            self.assertEqual(result["current_task_owner"]["source_refs_sha256"], "refs-sha")
            self.assertEqual(task_object["task_object_sha256"], "compiled-sha")
            self.assertTrue(task_object["compiled_task_object_used_by_langgraph"])
            self.assertEqual(task_object["acceptance_contract"]["parent_object"], "XINAO_GLOBAL_CANONICAL_SELF_CLEANSE_AND_UPLIFT_ROOT_REPAIR")
            self.assertEqual(task_object["acceptance_contract"]["migration_subobject"], "XINAO_MATURE_RUNTIME_MIGRATION_FROM_STATUS_CARD_STACK")

    def test_complete_fixture_allows_user_task_complete_only_from_claim(self):
        original = temporal_codex_task_workflow.call_codex_activator
        with tempfile.TemporaryDirectory() as tmp:
            runroot = Path(tmp)

            def fake_call(payload, *, timeout_sec):
                task_root = runroot / "codex_results" / payload["task_id"]
                task_root.mkdir(parents=True, exist_ok=True)
                jsonl = task_root / "codex-events.jsonl"
                final = task_root / "final.md"
                jsonl.write_text('{"type":"thread.started"}\n{"type":"turn.completed"}\n', encoding="utf-8")
                final.write_text(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER + "\n", encoding="utf-8")
                return {
                    "ok": True,
                    "status": "PASS",
                    "task_id": payload["task_id"],
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "named_blocker": "",
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original)
            task_object = compiled_medium_task_object("temporal_complete")
            write_valid_side_audit(runroot, task_object["task_id"])
            write_frontier_intake(runroot, task_object)
            write_leg1_summon(runroot, task_object["task_id"])
            write_grok_leg2_verdict(runroot, task_object["task_id"], "pass")
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id=task_object["task_id"],
                user_goal="unit temporal complete",
                mode="complete",
                runtime_root=runroot,
                allow_complete_fixture=True,
                compiled_task_object=task_object,
                extra_input={"phase_exit_ready": True},
            )

        self.assertFalse(result["temporal_workflow_completed"])
        self.assertFalse(result["user_task_complete"])
        self.assertEqual(result["completion_decision"]["status"], "partial")
        self.assertFalse(result["completion_decision"]["stop_allowed"])
        self.assertEqual(result["segment_audit_status"], "GROK_SEGMENT_AUDIT_PASS")
        self.assertTrue(result["same_workflow_next_worker_dispatched"])
        assert_authority_boundary(self, result)

    def test_retry_policy_separates_transient_and_policy_denials(self):
        policy = temporal_codex_task_workflow.retry_policy_dict()
        self.assertIn("XINAO_OBJECT_REPLACEMENT_DENIED", policy["non_retryable_error_types"])
        self.assertIn("XINAO_TRANSIENT_TOOL_ERROR", policy["retryable_error_types"])

    def test_codex_worker_missing_tool_surface_returns_named_blocker(self):
        original = temporal_codex_task_workflow.DEFAULT_RUNTIME
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "missing_default_runtime"
            temporal_codex_task_workflow.DEFAULT_RUNTIME = fake_root
            self.addCleanup(setattr, temporal_codex_task_workflow, "DEFAULT_RUNTIME", original)
            result = asyncio.run(temporal_codex_task_workflow.codex_worker_turn_activity({
                "runtime_root": str(Path(tmp) / "task_runtime_without_tools"),
                "task_id": "missing_tool_surface",
                "execute_codex_worker": True,
            }))

        self.assertEqual(result["status"], "activity_blocked")
        self.assertEqual(result["named_blocker"], "CODEX_WORKER_UCP_TOOL_SURFACE_MISSING")
        self.assertFalse(result["python_exists"])
        self.assertFalse(result["ucp_exists"])

    def test_codex_worker_task_bound_activator_evidence_passes(self):
        original = temporal_codex_task_workflow.call_codex_activator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jsonl = root / "codex-events.jsonl"
            final = root / "final.md"
            jsonl.write_text('{"type":"thread.started"}\n{"type":"turn.completed"}\n', encoding="utf-8")
            final.write_text(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER + "\n", encoding="utf-8")

            def fake_call(payload, *, timeout_sec):
                return {
                    "ok": True,
                    "status": "PASS",
                    "task_id": payload["task_id"],
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "named_blocker": "",
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original)
            result = asyncio.run(temporal_codex_task_workflow.codex_worker_turn_activity({
                "runtime_root": str(root),
                "task_id": "task_bound_unit",
                "execute_codex_worker": True,
                "codex_worker_task_id": "task_bound_unit.codex-worker",
                "codex_worker_prompt": "Return " + temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                "codex_worker_expected_marker": temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
            }))

        self.assertEqual(result["status"], "activity_gate_checked")
        self.assertTrue(result["task_bound_worker"])
        self.assertFalse(result["fallback_canary_only"])
        self.assertTrue(result["jsonl_exists"])
        self.assertTrue(result["expected_marker_seen"])

    def test_codex_worker_reuses_existing_success_result_on_temporal_retry(self):
        original = temporal_codex_task_workflow.call_codex_activator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_task_id = "task_bound_retry_unit.codex-worker"
            result_dir = root / "state" / "codex_results" / worker_task_id
            result_dir.mkdir(parents=True, exist_ok=True)
            jsonl = result_dir / "codex-events.jsonl"
            final = result_dir / "final.md"
            raw_final = result_dir / "raw-final.md"
            jsonl.write_text('{"type":"thread.started"}\n{"type":"turn.completed"}\n', encoding="utf-8")
            final.write_text(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER + "\n", encoding="utf-8")
            raw_final.write_text(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER + "\n", encoding="utf-8")
            write_json(
                result_dir / "result.json",
                {
                    "ok": True,
                    "status": "PASS",
                    "task_id": worker_task_id,
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "raw_final_path": str(raw_final),
                    "named_blocker": "",
                },
            )

            def fail_if_called(payload, *, timeout_sec):
                raise AssertionError("activator should not be called for existing success result")

            temporal_codex_task_workflow.call_codex_activator = fail_if_called
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original)
            result = asyncio.run(temporal_codex_task_workflow.codex_worker_turn_activity({
                "runtime_root": str(root),
                "task_id": "task_bound_retry_unit",
                "execute_codex_worker": True,
                "codex_worker_task_id": worker_task_id,
                "codex_worker_prompt": "Return " + temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                "codex_worker_expected_marker": temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
            }))

        self.assertEqual(result["status"], "activity_gate_checked")
        self.assertTrue(result["reused_existing_task_result"])
        self.assertEqual(result["existing_task_result_ref"], str(result_dir / "result.json"))
        self.assertTrue(result["task_bound_worker"])
        self.assertTrue(result["expected_marker_seen"])

    def test_codex_worker_activity_propagates_activator_failure_classification(self):
        original = temporal_codex_task_workflow.call_codex_activator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jsonl = root / "codex-events.jsonl"
            final = root / "final.md"
            jsonl.write_text('{"type":"thread.started"}\n', encoding="utf-8")
            final.write_text(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER + "\n", encoding="utf-8")

            def fake_call(payload, *, timeout_sec):
                return {
                    "ok": False,
                    "status": "FAIL",
                    "http_status": 500,
                    "named_blocker": "CODEX_USAGE_LIMIT_RETRY_AFTER",
                    "activator_response": {
                        "ok": False,
                        "status": "FAIL",
                        "task_id": payload["task_id"],
                        "jsonl_path": str(jsonl),
                        "final_path": str(final),
                        "named_blocker": "CODEX_USAGE_LIMIT_RETRY_AFTER",
                        "failure_classification": {
                            "named_blocker": "CODEX_USAGE_LIMIT_RETRY_AFTER",
                            "external_condition": True,
                            "retryable": True,
                            "retry_after_text": "2:16 AM",
                        },
                    },
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original)
            result = asyncio.run(temporal_codex_task_workflow.codex_worker_turn_activity({
                "runtime_root": str(root),
                "task_id": "task_bound_quota_unit",
                "execute_codex_worker": True,
                "codex_worker_task_id": "task_bound_quota_unit.codex-worker",
                "codex_worker_prompt": "Return " + temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                "codex_worker_expected_marker": temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
            }))

        self.assertEqual(result["status"], "activity_blocked")
        self.assertEqual(result["named_blocker"], "CODEX_USAGE_LIMIT_RETRY_AFTER")
        self.assertEqual(
            result["failure_classification"]["named_blocker"],
            "CODEX_USAGE_LIMIT_RETRY_AFTER",
        )
        self.assertEqual(result["jsonl_path"], str(jsonl))
        self.assertEqual(result["final_path"], str(final))
        self.assertTrue(result["external_condition"])
        self.assertTrue(result["retryable"])
        self.assertEqual(result["retry_after_text"], "2:16 AM")

    def test_codex_worker_activity_passes_assignment_metadata_to_activator(self):
        original = temporal_codex_task_workflow.call_codex_activator
        captured = {}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jsonl = root / "codex-events.jsonl"
            final = root / "final.md"
            jsonl.write_text('{"type":"thread.started"}\n{"type":"turn.completed"}\n', encoding="utf-8")
            final.write_text(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER + "\n", encoding="utf-8")

            def fake_call(payload, *, timeout_sec):
                captured["payload"] = dict(payload)
                captured["timeout_sec"] = timeout_sec
                return {
                    "ok": True,
                    "status": "PASS",
                    "task_id": payload["task_id"],
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "named_blocker": "",
                    "worker_kind": payload.get("worker_kind", ""),
                    "phase_scope": payload.get("phase_scope", ""),
                    "worker_assignment_ref": payload.get("worker_assignment_ref", ""),
                    "assignment_driven_dispatch": payload.get("assignment_driven_dispatch") is True,
                    "implementation_worker_required": payload.get("implementation_worker_required") is True,
                    "segment_pass_checker_default": payload.get("segment_pass_checker_default") is True,
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original)
            result = asyncio.run(temporal_codex_task_workflow.codex_worker_turn_activity({
                "runtime_root": str(root),
                "task_id": "task_bound_assignment_meta_unit",
                "execute_codex_worker": True,
                "codex_worker_task_id": "task_bound_assignment_meta_unit.continue-same-task.worker.1.unit",
                "codex_worker_prompt": "Return " + temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                "codex_worker_expected_marker": temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                "worker_kind": "implementation_worker",
                "phase_scope": "Phase2_execution_carrier_replacement_mature_worker",
                "worker_assignment_ref": r"D:\XINAO_CLEAN_RUNTIME\state\worker_assignment\unit.json",
                "phase_execution": {"worker_kind": "implementation_worker"},
                "work_package": {"files": ["services/agent_runtime/temporal_codex_task_workflow.py"]},
                "verification": ["python -m unittest tests.test_temporal_codex_task_workflow"],
                "assignment_driven_dispatch": True,
                "implementation_worker_required": True,
                "continue_same_task_signal_worker_required": True,
                "segment_boundary_policy": "phase_exit_only",
                "grok_audit_policy": "only_after_phase_ready",
                "segment_pass_checker_default": False,
            }))

        self.assertEqual(captured["payload"]["worker_kind"], "implementation_worker")
        self.assertEqual(captured["payload"]["phase_scope"], "Phase2_execution_carrier_replacement_mature_worker")
        self.assertEqual(captured["payload"]["worker_assignment_ref"], r"D:\XINAO_CLEAN_RUNTIME\state\worker_assignment\unit.json")
        self.assertEqual(captured["payload"]["work_package"]["files"], ["services/agent_runtime/temporal_codex_task_workflow.py"])
        self.assertEqual(captured["payload"]["verification"], ["python -m unittest tests.test_temporal_codex_task_workflow"])
        self.assertTrue(captured["payload"]["assignment_driven_dispatch"])
        self.assertTrue(captured["payload"]["implementation_worker_required"])
        self.assertFalse(captured["payload"]["segment_pass_checker_default"])
        self.assertEqual(result["worker_kind"], "implementation_worker")
        self.assertEqual(result["work_package"]["files"], ["services/agent_runtime/temporal_codex_task_workflow.py"])
        self.assertEqual(result["verification"], ["python -m unittest tests.test_temporal_codex_task_workflow"])
        self.assertTrue(result["implementation_worker_required"])
        self.assertFalse(result["segment_pass_checker_default"])

    def test_seed_cortex_worker_dispatch_ledger_activity_binds_task_worker_result(self):
        original_call = temporal_codex_task_workflow.call_codex_activator
        original_seed_runtime = temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT = root
            write_seed_cortex_dp_sidecar_capability_reuse(root)
            anchor = root / "Desktop" / "新系统"
            anchor.mkdir(parents=True, exist_ok=True)
            for name in [
                "新系统独立并行_自由发散外部研究总稿_20260701.txt",
                "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
                "新系统步骤程序_大骨架_并行研究收口_20260702.txt",
                "新系统前置材料_收口合并_20260702.txt",
            ]:
                (anchor / name).write_text(name + "\n", encoding="utf-8")

            def fake_call(payload, *, timeout_sec):
                task_root = root / "codex_results" / payload["task_id"]
                task_root.mkdir(parents=True, exist_ok=True)
                jsonl = task_root / "codex-events.jsonl"
                final = task_root / "final.md"
                raw_final = task_root / "raw-final.md"
                jsonl.write_text(
                    '{"type":"thread.started"}\n{"type":"turn.completed"}\n',
                    encoding="utf-8",
                )
                marker = temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER
                final.write_text(marker + "\n", encoding="utf-8")
                raw_final.write_text(marker + "\n", encoding="utf-8")
                return {
                    "ok": True,
                    "status": "PASS",
                    "task_id": payload["task_id"],
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "raw_final_path": str(raw_final),
                    "named_blocker": "",
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original_call)
            self.addCleanup(
                setattr,
                temporal_codex_task_workflow,
                "SEED_CORTEX_RUNTIME_ROOT",
                original_seed_runtime,
            )
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id=temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
                user_goal="unit seed cortex worker ledger binding",
                mode="partial",
                runtime_root=root,
                execute_codex_worker=True,
                codex_worker_task_id="seed-cortex-unit.worker.1",
                codex_worker_prompt=(
                    "Return "
                    + temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER
                ),
                codex_worker_expected_marker=(
                    temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER
                ),
                extra_input={
                    "route_profile": temporal_codex_task_workflow.SEED_CORTEX_ROUTE_PROFILE,
                    "anchor_package_root": str(anchor),
                },
            )

            latest = root / "state" / "worker_dispatch_ledger" / "latest.json"
            temporal_latest = (
                root
                / "state"
                / "worker_dispatch_ledger"
                / "temporal_activity_latest.json"
            )
            main_tick_temporal_latest = (
                root
                / "state"
                / "codex_s_main_execution_loop_tick"
                / "temporal_activity_latest.json"
            )
            durable_packet_temporal_latest = (
                root
                / "state"
                / "durable_parallel_wave_packet"
                / "temporal_activity_latest.json"
            )
            default_trigger_temporal_latest = (
                root
                / "state"
                / "default_main_loop_trigger_candidate"
                / "temporal_activity_latest.json"
            )
            scheduler_packet_temporal_latest = (
                root
                / "state"
                / "scheduler_invocation_packet"
                / "temporal_activity_latest.json"
            )
            payload = json.loads(temporal_latest.read_text(encoding="utf-8"))
            durable_payload = json.loads(
                durable_packet_temporal_latest.read_text(encoding="utf-8")
            )
            default_trigger_payload = json.loads(
                default_trigger_temporal_latest.read_text(encoding="utf-8")
            )
            scheduler_packet_payload = json.loads(
                scheduler_packet_temporal_latest.read_text(encoding="utf-8")
            )
            ledger_latest_exists = Path(result["worker_dispatch_ledger_latest_ref"]).is_file()
            ledger_temporal_latest_exists = temporal_latest.is_file()
            main_tick_temporal_latest_exists = main_tick_temporal_latest.is_file()
            durable_packet_temporal_latest_exists = durable_packet_temporal_latest.is_file()
            default_trigger_temporal_latest_exists = default_trigger_temporal_latest.is_file()
            scheduler_packet_temporal_latest_exists = scheduler_packet_temporal_latest.is_file()
            auto_dispatch_latest_exists = (
                root
                / "state"
                / "temporal_codex_task_workflow"
                / "auto_dispatch_latest.json"
            ).is_file()
            default_auto_dispatch_latest_exists = (
                root / "state" / "default_auto_dispatch" / "latest.json"
            ).is_file()

        ledger_activity = next(
            item for item in result["activities"] if item["activity"] == "worker_dispatch_ledger"
        )
        self.assertEqual(ledger_activity["status"], "activity_gate_checked")
        self.assertTrue(ledger_activity["runtime_enforced"])
        self.assertTrue(ledger_activity["ledger_validation_passed"])
        self.assertEqual(
            ledger_activity["runtime_enforced_scope"],
            "seed_cortex_temporal_worker_dispatch_ledger_write_activity",
        )
        self.assertTrue(result["worker_dispatch_ledger_runtime_enforced"])
        self.assertTrue(ledger_latest_exists)
        self.assertTrue(ledger_temporal_latest_exists)
        self.assertTrue(result["worker_dispatch_ledger_temporal_activity_latest_ref"])
        main_tick_activity = next(
            item for item in result["activities"] if item["activity"] == "main_execution_loop_tick"
        )
        self.assertIn(main_tick_activity["status"], {"activity_gate_checked", "activity_blocked"})
        self.assertTrue(main_tick_activity["runtime_enforced"])
        self.assertTrue(main_tick_temporal_latest_exists)
        self.assertTrue(result["main_execution_loop_tick_runtime_enforced"])
        self.assertTrue(result["main_execution_loop_tick_temporal_activity_latest_ref"])
        if main_tick_activity["status"] == "activity_blocked":
            self.assertEqual(
                main_tick_activity["named_blocker"],
                "CODEX_S_MAIN_EXECUTION_LOOP_TICK_VALIDATION_FAILED",
            )
        else:
            self.assertTrue(main_tick_activity["tick_validation_passed"])
        durable_activity = next(
            item for item in result["activities"] if item["activity"] == "durable_parallel_wave_packet"
        )
        self.assertIn(durable_activity["status"], {"activity_gate_checked", "activity_blocked"})
        self.assertTrue(durable_activity["runtime_enforced"])
        self.assertEqual(
            durable_activity["runtime_enforced_scope"],
            "seed_cortex_temporal_durable_parallel_wave_packet_activity",
        )
        self.assertTrue(durable_packet_temporal_latest_exists)
        self.assertTrue(result["durable_parallel_wave_packet_runtime_enforced"])
        self.assertEqual(
            result["durable_parallel_wave_packet_runtime_enforced_scope"],
            "seed_cortex_temporal_durable_parallel_wave_packet_activity",
        )
        self.assertTrue(result["durable_parallel_wave_packet_temporal_activity_latest_ref"])
        self.assertTrue(durable_activity["worker_dispatch_ledger_activity_ref"])
        self.assertTrue(durable_activity["main_execution_loop_tick_activity_ref"])
        self.assertGreaterEqual(
            durable_activity["actual_dispatch_refs"]["codex_subagent_count"],
            1,
        )
        self.assertTrue(
            durable_activity["actual_dispatch_refs"][
                "derived_codex_subagent_refs_from_worker_activity"
            ]
        )
        self.assertGreaterEqual(
            len(
                durable_activity["actual_dispatch_refs"][
                    "worker_dispatch_ledger_actual_entry_ids"
                ]
            ),
            1,
        )
        self.assertGreaterEqual(
            durable_payload["actual_dispatch_refs"]["codex_subagent_count"],
            1,
        )
        self.assertEqual(
            durable_activity["actual_dispatch_refs"]["dp_sidecar_execution_port"],
            "dp_sidecar_execution_port",
        )
        self.assertTrue(
            durable_activity["actual_dispatch_refs"][
                "dp_sidecar_execution_callable_entrypoint_bound"
            ]
        )
        self.assertTrue(
            durable_activity["actual_dispatch_refs"][
                "dp_sidecar_execution_port_runner_ref"
            ]["exists"]
        )
        self.assertTrue(
            durable_activity["actual_dispatch_refs"][
                "dp_sidecar_execution_provider_ref"
            ]["exists"]
        )
        self.assertTrue(
            durable_activity["actual_dispatch_refs"][
                "dp_sidecar_execution_provider_manifest_ref"
            ]["exists"]
        )
        self.assertEqual(
            durable_payload["dp_sidecar_execution"]["port_id"],
            "dp_sidecar_execution_port",
        )
        self.assertTrue(durable_payload["dp_sidecar_execution"]["callable_entrypoint_bound"])
        self.assertIn("search", durable_payload["dp_sidecar_execution"]["mode_counts"])
        self.assertGreater(
            len(
                [
                    mode
                    for mode in durable_payload["dp_sidecar_execution"]["mode_counts"]
                    if mode != "search"
                ]
            ),
            0,
        )
        self.assertTrue(
            durable_payload["validation"]["checks"][
                "actual_codex_subagent_or_worker_refs_present"
            ]
        )
        self.assertTrue(
            durable_payload["validation"]["checks"][
                "dp_sidecar_execution_callable_refs_bound"
            ]
        )
        self.assertFalse(durable_activity["completion_claim_allowed"])
        self.assertTrue(durable_activity["not_execution_controller"])
        if durable_activity["status"] == "activity_blocked":
            self.assertEqual(
                durable_activity["named_blocker"],
                "CODEX_S_DURABLE_PARALLEL_WAVE_PACKET_VALIDATION_FAILED",
            )
        else:
            self.assertTrue(durable_activity["durable_packet_validation_passed"])
            self.assertTrue(result["durable_parallel_wave_packet_validation_passed"])
        temporal_entries = [
            entry
            for entry in payload["dispatch_entries"]
            if entry["provider"] == "temporal.codex_worker_turn_activity"
        ]
        self.assertEqual(len(temporal_entries), 1)
        self.assertEqual(temporal_entries[0]["agent_id"], "seed-cortex-unit.worker.1")
        self.assertEqual(temporal_entries[0]["poll_status"], "succeeded")
        self.assertFalse(temporal_entries[0]["legacy_5d33_owner_reused"])
        self.assertFalse(temporal_entries[0]["legacy_5d33_pass_reused"])
        self.assertFalse(temporal_entries[0]["legacy_5d33_latest_authority_reused"])
        self.assertTrue(payload["runtime_entrypoint_invocation"]["runtime_enforced"])
        self.assertEqual(payload["summary"]["hooked_runtime_entrypoint_count"], 1)

        default_dp_activity = next(
            item
            for item in result["activities"]
            if item["activity"] == "dp_worker_pool_wave_activity"
        )
        self.assertIn(
            default_dp_activity["status"],
            {"dp_worker_pool_wave_activity_ready", "dp_worker_pool_wave_activity_blocked"},
        )
        self.assertEqual(
            default_dp_activity["dynamic_width_decision"]["target_width_source"],
            "dynamic_width_scheduler",
        )
        self.assertFalse(
            default_dp_activity["dynamic_width_decision"]["operator_cap_applied"]
        )
        self.assertFalse(
            default_dp_activity["dynamic_width_decision"]["fixed_20_or_50_used"]
        )
        self.assertTrue(default_dp_activity["capacity_observation"]["not_default_width"])
        self.assertTrue(default_dp_activity["capacity_observation"]["not_permanent_cap"])
        self.assertGreaterEqual(
            result["default_dp_worker_pool_actual_dispatched_width"],
            3,
        )
        self.assertEqual(
            result["default_dp_worker_pool_dynamic_width_source"],
            "dynamic_width_scheduler",
        )
        self.assertTrue(result["default_dp_worker_pool_phase1_latest_ref"])

        auto_dispatch_activity = next(
            item
            for item in result["activities"]
            if item["activity"] == "ledger_auto_dispatch_ingress"
        )
        self.assertTrue(auto_dispatch_activity["worker_dispatch_ledger_runtime_enforced"])
        self.assertEqual(auto_dispatch_activity["worker_dispatch_ledger_succeeded_count"], 1)
        self.assertIn(
            auto_dispatch_activity["status"],
            {
                "auto_dispatch_ingress_enqueued",
                "auto_dispatch_waiting_assignment_signal",
            },
        )
        self.assertFalse(auto_dispatch_activity["ingress"]["manual_cli_required"])
        self.assertFalse(auto_dispatch_activity["ingress"]["watch_window_required"])
        if auto_dispatch_activity["runtime_enforced"]:
            self.assertTrue(auto_dispatch_activity["auto_continue_same_workflow"])
            self.assertEqual(
                auto_dispatch_activity["dispatch_reason"],
                "worker_ledger_succeeded",
            )
        else:
            self.assertEqual(
                auto_dispatch_activity["named_blocker"],
                "ASSIGNMENT_DAG_NEXT_READY_SIGNAL_NOT_AVAILABLE",
            )
        self.assertTrue(auto_dispatch_latest_exists)
        self.assertTrue(default_auto_dispatch_latest_exists)

        default_trigger_activity = next(
            item
            for item in result["activities"]
            if item["activity"] == "default_main_loop_trigger_candidate"
        )
        self.assertIn(
            default_trigger_activity["status"],
            {"activity_gate_checked", "activity_blocked"},
        )
        self.assertTrue(default_trigger_activity["runtime_enforced"])
        self.assertEqual(
            default_trigger_activity["runtime_enforced_scope"],
            "seed_cortex_temporal_default_main_loop_trigger_candidate_activity",
        )
        self.assertTrue(default_trigger_temporal_latest_exists)
        self.assertTrue(result["default_main_loop_trigger_candidate_runtime_enforced"])
        self.assertEqual(
            result["default_main_loop_trigger_candidate_runtime_enforced_scope"],
            "seed_cortex_temporal_default_main_loop_trigger_candidate_activity",
        )
        self.assertTrue(
            result["default_main_loop_trigger_candidate_temporal_activity_latest_ref"]
        )
        self.assertTrue(default_trigger_activity["main_execution_loop_tick_activity_ref"])
        self.assertTrue(default_trigger_activity["durable_parallel_wave_packet_activity_ref"])
        self.assertFalse(default_trigger_activity["completion_claim_allowed"])
        self.assertTrue(default_trigger_activity["not_execution_controller"])
        self.assertTrue(
            default_trigger_payload["runtime_entrypoint_invocation"]["runtime_enforced"]
        )
        self.assertEqual(
            default_trigger_payload["runtime_entrypoint_adoption_state"],
            "runtime_enforced_for_temporal_default_main_loop_trigger_candidate_activity_only",
        )
        self.assertTrue(
            default_trigger_payload["actual_activity_refs"][
                "refs_are_not_execution_controllers"
            ]
        )
        self.assertEqual(
            default_trigger_payload["actual_dispatch_refs"]["dp_sidecar_execution_port"],
            "dp_sidecar_execution_port",
        )
        self.assertTrue(
            default_trigger_payload["actual_dispatch_refs"][
                "dp_sidecar_execution_callable_entrypoint_bound"
            ]
        )
        self.assertTrue(
            default_trigger_payload["actual_dispatch_refs"][
                "dp_sidecar_execution_port_runner_ref"
            ]["exists"]
        )
        self.assertTrue(
            default_trigger_payload["validation"]["checks"][
                "dp_sidecar_execution_callable_refs_bound"
            ]
        )
        self.assertTrue(
            default_trigger_payload["validation"]["checks"][
                "scheduler_current_wave_immutable_ref_bound"
            ]
        )
        self.assertFalse(
            default_trigger_payload["activity_scope_boundary"][
                "global_default_trigger_installed"
            ]
        )
        if default_trigger_activity["status"] == "activity_blocked":
            self.assertEqual(
                default_trigger_activity["named_blocker"],
                "CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_VALIDATION_FAILED",
            )
        else:
            self.assertTrue(default_trigger_activity["trigger_candidate_validation_passed"])
            self.assertTrue(result["default_main_loop_trigger_candidate_validation_passed"])

        scheduler_packet_activity = next(
            item
            for item in result["activities"]
            if item["activity"] == "scheduler_invocation_packet"
        )
        self.assertIn(
            scheduler_packet_activity["status"],
            {"activity_gate_checked", "activity_blocked"},
        )
        self.assertTrue(scheduler_packet_activity["runtime_enforced"])
        self.assertEqual(
            scheduler_packet_activity["runtime_enforced_scope"],
            "seed_cortex_temporal_scheduler_invocation_packet_activity",
        )
        self.assertTrue(scheduler_packet_temporal_latest_exists)
        self.assertTrue(result["scheduler_invocation_packet_runtime_enforced"])
        self.assertEqual(
            result["scheduler_invocation_packet_runtime_enforced_scope"],
            "seed_cortex_temporal_scheduler_invocation_packet_activity",
        )
        self.assertTrue(
            result["scheduler_invocation_packet_temporal_activity_latest_ref"]
        )
        self.assertFalse(result["scheduler_invocation_packet_packet_runtime_enforced"])
        self.assertFalse(
            result["scheduler_invocation_packet_packet_default_runtime_scheduler_invoked"]
        )
        self.assertEqual(
            scheduler_packet_payload["schema_version"],
            "xinao.codex_s.scheduler_invocation_packet.v1",
        )
        self.assertEqual(
            scheduler_packet_payload["adoption_state"],
            "verifier_ready_but_not_hooked",
        )
        self.assertEqual(
            scheduler_packet_payload["runtime_entrypoint_adoption_state"],
            "runtime_enforced_for_temporal_scheduler_invocation_packet_activity_only",
        )
        self.assertEqual(
            scheduler_packet_payload["runtime_entrypoint_invocation"]["invoked_by"],
            "temporal_codex_task_workflow.scheduler_invocation_packet_activity",
        )
        self.assertTrue(
            scheduler_packet_payload["runtime_entrypoint_invocation"]["runtime_enforced"]
        )
        self.assertFalse(scheduler_packet_payload["runtime_enforced"])
        self.assertFalse(scheduler_packet_payload["default_runtime_scheduler_invoked"])
        self.assertFalse(scheduler_packet_payload["completion_claim_allowed"])
        self.assertTrue(
            scheduler_packet_payload["actual_activity_refs"][
                "worker_dispatch_ledger_activity_ref"
            ]["runtime_enforced"]
        )
        self.assertEqual(
            scheduler_packet_payload["actual_activity_refs"][
                "durable_parallel_wave_packet_activity_ref"
            ]["actual_dispatch_refs"]["dp_sidecar_execution_port"],
            "dp_sidecar_execution_port",
        )
        self.assertTrue(
            scheduler_packet_payload["actual_activity_refs"][
                "durable_parallel_wave_packet_activity_ref"
            ]["actual_dispatch_refs"]["dp_sidecar_execution_callable_entrypoint_bound"]
        )
        self.assertTrue(
            scheduler_packet_payload["actual_activity_refs"][
                "durable_parallel_wave_packet_activity_ref"
            ]["actual_dispatch_refs"]["dp_sidecar_execution_port_runner_ref"]["exists"]
        )
        self.assertTrue(scheduler_packet_payload["scheduler_invoked"])
        self.assertGreaterEqual(scheduler_packet_payload["spawned_lane_count"], 1)
        self.assertGreaterEqual(
            len(scheduler_packet_payload["scheduler_spawned_lane_refs"]),
            1,
        )
        self.assertEqual(scheduler_packet_payload["named_blocker"], "")
        self.assertTrue(
            scheduler_packet_payload["validation"]["checks"]["poll_refs_bound"]
        )
        self.assertTrue(
            scheduler_packet_payload["validation"]["checks"]["fan_in_refs_bound"]
        )
        self.assertTrue(
            scheduler_packet_payload["validation"]["checks"]["evidence_refs_bound"]
        )
        self.assertTrue(
            scheduler_packet_payload["validation"]["checks"]["readback_refs_bound"]
        )
        self.assertTrue(scheduler_packet_activity["packet_scheduler_invoked"])
        self.assertGreaterEqual(
            scheduler_packet_activity["packet_spawned_lane_count"],
            1,
        )
        self.assertGreaterEqual(
            len(scheduler_packet_activity["packet_scheduler_spawned_lane_refs"]),
            1,
        )
        self.assertTrue(
            scheduler_packet_payload["actual_activity_refs"][
                "spawned_lanes_derived_from_activity_refs"
            ]
        )
        self.assertTrue(
            scheduler_packet_payload["actual_activity_refs"][
                "spawned_lanes_derived_from_worker_dispatch_ledger_activity"
            ]
        )
        self.assertIn(
            True,
            [
                scheduler_packet_payload["actual_activity_refs"].get(
                    "spawned_lanes_derived_from_durable_activity"
                ),
                scheduler_packet_payload["actual_activity_refs"].get(
                    "spawned_lanes_derived_from_worker_dispatch_ledger_activity"
                ),
                scheduler_packet_payload["actual_activity_refs"].get(
                    "spawned_lanes_derived_from_activity_refs"
                ),
            ],
        )
        self.assertGreaterEqual(
            scheduler_packet_payload["activity_scope_boundary"][
                "activity_scoped_spawned_lane_count"
            ],
            1,
        )
        self.assertFalse(scheduler_packet_activity["packet_runtime_enforced"])
        self.assertFalse(
            scheduler_packet_activity["packet_default_runtime_scheduler_invoked"]
        )
        self.assertFalse(scheduler_packet_activity["completion_claim_allowed"])
        self.assertTrue(scheduler_packet_activity["not_execution_controller"])
        self.assertTrue(scheduler_packet_payload["not_execution_controller"])
        self.assertFalse(scheduler_packet_payload["legacy_5d33_owner_reused"])
        if scheduler_packet_activity["status"] == "activity_blocked":
            self.assertEqual(
                scheduler_packet_activity["named_blocker"],
                "CODEX_S_SCHEDULER_INVOCATION_PACKET_VALIDATION_FAILED",
            )
        else:
            self.assertTrue(
                scheduler_packet_activity[
                    "scheduler_invocation_packet_validation_passed"
                ]
            )

    def test_scheduler_invocation_packet_activity_returns_compact_refs_only(self):
        original_seed_runtime = temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT = root
            self.addCleanup(
                setattr,
                temporal_codex_task_workflow,
                "SEED_CORTEX_RUNTIME_ROOT",
                original_seed_runtime,
            )

            large_marker = "unit-large-upstream-ref-" + ("x" * 200000)
            result = asyncio.run(
                temporal_codex_task_workflow.scheduler_invocation_packet_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
                        "route_profile": (
                            temporal_codex_task_workflow.SEED_CORTEX_ROUTE_PROFILE
                        ),
                        "workflow_id": "unit-scheduler-compact",
                        "main_execution_loop_tick_activity": {
                            "tick_latest_ref": str(
                                root
                                / "state"
                                / "codex_s_main_execution_loop_tick"
                                / "latest.json"
                            ),
                            "large_tick_payload": large_marker,
                        },
                        "durable_parallel_wave_packet_activity": {
                            "durable_packet_latest_ref": str(
                                root
                                / "state"
                                / "durable_parallel_wave_packet"
                                / "latest.json"
                            ),
                            "actual_dispatch_refs": {
                                "codex_subagents": [
                                    {
                                        "agent_id": "unit-agent-1",
                                        "role": "temporal_worker_activity",
                                        "provider": "codex.subagent",
                                        "mode": "worker",
                                    }
                                ],
                            },
                            "large_durable_payload": large_marker,
                        },
                        "worker_dispatch_ledger_activity": {
                            "runtime_enforced": True,
                            "actual_dispatch_entry_ids": ["unit-agent-1"],
                            "large_worker_payload": large_marker,
                        },
                    }
                )
            )

            result_json = json.dumps(result, ensure_ascii=False)
            self.assertLess(len(result_json), 20000)
            self.assertNotIn(large_marker, result_json)
            self.assertEqual(
                result["latest_ref"],
                result["scheduler_invocation_packet_latest_ref"],
            )
            self.assertTrue(result["packet_scheduler_spawned_lane_refs"])
            self.assertTrue(result["scheduler_invocation_packet_validation_passed"])

            latest = Path(result["scheduler_invocation_packet_latest_ref"])
            packet_json = latest.read_text(encoding="utf-8")
            self.assertIn(large_marker, packet_json)
            packet_payload = json.loads(packet_json)
            self.assertTrue(
                packet_payload["actual_activity_refs"][
                    "spawned_lanes_derived_from_durable_activity"
                ]
            )

    def test_ledger_auto_dispatch_ingress_enqueues_next_wave_from_succeeded_ledger(self):
        original_seed_runtime = temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT = root
            self.addCleanup(
                setattr,
                temporal_codex_task_workflow,
                "SEED_CORTEX_RUNTIME_ROOT",
                original_seed_runtime,
            )

            result = asyncio.run(
                temporal_codex_task_workflow.ledger_auto_dispatch_ingress_activity(
                    {
                        "runtime_root": str(root),
                        "repo_root": str(Path.cwd()),
                        "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
                        "workflow_id": "unit-hotpath",
                        "wave_id": "unit-hotpath-wave-01",
                        "wave_index": 1,
                        "worker_dispatch_ledger_activity": {
                            "activity": "worker_dispatch_ledger",
                            "runtime_enforced": True,
                            "ledger_succeeded_count": 1,
                            "ledger_temporal_activity_latest_ref": str(
                                root
                                / "state"
                                / "worker_dispatch_ledger"
                                / "temporal_activity_latest.json"
                            ),
                        },
                        "main_execution_loop_tick_activity": {
                            "activity": "main_execution_loop_tick",
                            "runtime_enforced": True,
                            "tick_temporal_activity_latest_ref": str(
                                root
                                / "state"
                                / "codex_s_main_execution_loop_tick"
                                / "temporal_activity_latest.json"
                            ),
                        },
                        "partial_continuation_dispatch": {
                            "auto_continue_same_task_signal": {
                                "source_kind": "assignment_dag_auto_continue",
                                "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
                            }
                        },
                    }
                )
            )
            latest_exists = Path(result["output_paths"]["latest"]).is_file()
            default_latest_exists = Path(
                result["output_paths"]["default_auto_dispatch_latest"]
            ).is_file()

        self.assertEqual(result["status"], "auto_dispatch_ingress_enqueued")
        self.assertTrue(result["runtime_enforced"])
        self.assertTrue(result["auto_continue_same_workflow"])
        self.assertEqual(
            result["auto_continue_same_task_signal"]["source_kind"],
            "worker_dispatch_ledger_auto_dispatch",
        )
        self.assertTrue(latest_exists)
        self.assertTrue(default_latest_exists)

    def test_ledger_auto_dispatch_ingress_accepts_global_worker_ledger_payload(self):
        original_seed_runtime = temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT = root
            self.addCleanup(
                setattr,
                temporal_codex_task_workflow,
                "SEED_CORTEX_RUNTIME_ROOT",
                original_seed_runtime,
            )

            result = asyncio.run(
                temporal_codex_task_workflow.ledger_auto_dispatch_ingress_activity(
                    {
                        "runtime_root": str(root),
                        "repo_root": str(Path.cwd()),
                        "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
                        "workflow_id": "unit-hotpath-global-ledger",
                        "wave_id": "unit-hotpath-global-ledger-wave-01",
                        "wave_index": 1,
                        "worker_dispatch_ledger_activity": {
                            "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
                            "runtime_entrypoint_invocation": {
                                "runtime_enforced": True,
                                "invoked_by": "codex_max_capability_think_execute.worker_dispatch_ledger_poll",
                            },
                            "hot_path_binding": {"runtime_enforced": True},
                            "succeeded_count": 3,
                            "poll_result_summary": {"succeeded_count": 3},
                            "output_paths": {
                                "runtime_latest": str(
                                    root / "state" / "worker_dispatch_ledger" / "latest.json"
                                )
                            },
                        },
                        "main_execution_loop_tick_activity": {
                            "activity": "main_execution_loop_tick",
                            "runtime_enforced": True,
                            "tick_temporal_activity_latest_ref": str(
                                root
                                / "state"
                                / "codex_s_main_execution_loop_tick"
                                / "temporal_activity_latest.json"
                            ),
                        },
                        "partial_continuation_dispatch": {
                            "auto_continue_same_task_signal": {
                                "source_kind": "assignment_dag_auto_continue",
                                "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
                            }
                        },
                    }
                )
            )

        self.assertEqual(result["status"], "auto_dispatch_ingress_enqueued")
        self.assertTrue(result["runtime_enforced"])
        self.assertTrue(result["worker_dispatch_ledger_runtime_enforced"])
        self.assertEqual(result["worker_dispatch_ledger_succeeded_count"], 3)
        self.assertEqual(result["next_wave_index"], 2)
        self.assertFalse(result["ingress"]["manual_cli_required"])
        self.assertFalse(result["ingress"]["watch_window_required"])

    def test_ledger_auto_dispatch_ingress_propagates_worker_external_blocker(self):
        original_seed_runtime = temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            temporal_codex_task_workflow.SEED_CORTEX_RUNTIME_ROOT = root
            self.addCleanup(
                setattr,
                temporal_codex_task_workflow,
                "SEED_CORTEX_RUNTIME_ROOT",
                original_seed_runtime,
            )

            result = asyncio.run(
                temporal_codex_task_workflow.ledger_auto_dispatch_ingress_activity(
                    {
                        "runtime_root": str(root),
                        "repo_root": str(Path.cwd()),
                        "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
                        "workflow_id": "unit-hotpath-quota-blocker",
                        "wave_id": "unit-hotpath-quota-blocker-wave-01",
                        "wave_index": 1,
                        "worker_dispatch_evidence": [
                            {
                                "activity": "codex_worker_turn",
                                "status": "activity_blocked",
                                "named_blocker": "CODEX_USAGE_LIMIT_RETRY_AFTER",
                                "worker_task_id": "unit-worker-quota-blocked",
                                "activator_result": {
                                    "activator_response": {
                                        "failure_classification": {
                                            "external_condition": True,
                                            "retryable": True,
                                            "retry_after_text": "2:16 AM",
                                        },
                                    },
                                },
                            }
                        ],
                        "worker_dispatch_ledger_activity": {
                            "activity": "worker_dispatch_ledger",
                            "runtime_enforced": True,
                            "ledger_succeeded_count": 0,
                            "ledger_temporal_activity_latest_ref": str(
                                root
                                / "state"
                                / "worker_dispatch_ledger"
                                / "temporal_activity_latest.json"
                            ),
                        },
                        "partial_continuation_dispatch": {
                            "auto_continue_same_task_signal": {
                                "source_kind": "assignment_dag_auto_continue",
                                "task_id": temporal_codex_task_workflow.SEED_CORTEX_WORK_ID,
                            }
                        },
                    }
                )
            )

        self.assertEqual(result["status"], "auto_dispatch_blocked_waiting_worker_ledger_succeeded")
        self.assertEqual(result["named_blocker"], "CODEX_USAGE_LIMIT_RETRY_AFTER")
        self.assertEqual(result["upstream_named_blocker"], "CODEX_USAGE_LIMIT_RETRY_AFTER")
        self.assertTrue(result["external_condition"])
        self.assertTrue(result["retryable"])
        self.assertEqual(result["retry_after_text"], "2:16 AM")
        self.assertFalse(result["auto_continue_same_workflow"])
        self.assertFalse(result["runtime_enforced"])
        self.assertTrue(
            result["validation"]["checks"]["upstream_external_condition_named"]
        )

    def test_primary_ledger_selection_keeps_succeeded_wave_over_later_blocker(self):
        activities = [
            {
                "activity": "worker_dispatch_ledger",
                "runtime_enforced": True,
                "ledger_succeeded_count": 1,
                "wave_id": "main-wave",
            },
            {
                "activity": "worker_dispatch_ledger",
                "runtime_enforced": True,
                "ledger_succeeded_count": 0,
                "wave_id": "continuation-wave",
                "named_blocker": "WORKER_DISPATCH_LEDGER_NO_SUCCEEDED_POLL",
            },
        ]

        selected = temporal_codex_task_workflow.select_primary_worker_dispatch_ledger_activity(
            activities
        )

        self.assertEqual(selected["wave_id"], "main-wave")
        self.assertEqual(selected["ledger_succeeded_count"], 1)

    def test_primary_auto_dispatch_selection_keeps_enqueued_wave_over_later_blocker(self):
        activities = [
            {
                "activity": "ledger_auto_dispatch_ingress",
                "status": "auto_dispatch_ingress_enqueued",
                "runtime_enforced": True,
                "wave_id": "main-wave",
                "validation": {"passed": True},
            },
            {
                "activity": "ledger_auto_dispatch_ingress",
                "status": "auto_dispatch_blocked_waiting_worker_ledger_succeeded",
                "runtime_enforced": False,
                "wave_id": "continuation-wave",
                "validation": {"passed": False},
                "named_blocker": "WORKER_DISPATCH_LEDGER_NO_SUCCEEDED_POLL",
            },
        ]

        selected = (
            temporal_codex_task_workflow.select_primary_ledger_auto_dispatch_ingress_activity(
                activities
            )
        )

        self.assertEqual(selected["wave_id"], "main-wave")
        self.assertEqual(selected["status"], "auto_dispatch_ingress_enqueued")

    def test_partial_completion_keeps_workflow_open_with_internal_timer(self):
        original = temporal_codex_task_workflow.call_codex_activator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            continuation_payloads = []

            def fake_call(payload, *, timeout_sec):
                if "continuation" in payload["task_id"]:
                    continuation_payloads.append((payload, timeout_sec))
                task_root = root / "codex_results" / payload["task_id"]
                task_root.mkdir(parents=True, exist_ok=True)
                jsonl = task_root / "codex-events.jsonl"
                final = task_root / "final.md"
                jsonl.write_text('{"type":"thread.started"}\n{"type":"turn.completed"}\n', encoding="utf-8")
                marker = (
                    temporal_codex_task_workflow.TASK_CONTINUATION_WORKER_MARKER
                    if "continuation" in payload["task_id"]
                    else temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER
                )
                final.write_text(marker + "\n", encoding="utf-8")
                return {
                    "ok": True,
                    "status": "PASS",
                    "task_id": payload["task_id"],
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "named_blocker": "",
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original)
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="temporal_partial_continue",
                user_goal="unit partial continuation",
                mode="partial",
                runtime_root=root,
                execute_codex_worker=True,
                codex_worker_prompt="Return " + temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                codex_worker_expected_marker=temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
            )

        continuation = next(item for item in result["activities"] if item["activity"] == "partial_continuation_dispatch")
        self.assertEqual(result["completion_decision"]["status"], "partial")
        self.assertFalse(result["partial_continuation_dispatched"])
        self.assertEqual(result["partial_continuation_ref"], "")
        self.assertEqual(continuation["status"], "l1_continuation_worker_not_dispatched_yet")
        self.assertFalse(continuation["continuation_dispatched"])
        self.assertFalse(continuation["external_continuation_worker_dispatched"])
        self.assertTrue(continuation["workflow_internal_timer_scheduled"])
        self.assertTrue(continuation["workflow_kept_open_by_durable_timer"])
        self.assertFalse(continuation["workflow_waiting_signal"])
        self.assertEqual(continuation["workflow_signal_name"], "continue_same_task")
        self.assertTrue(continuation["grok_waiting_does_not_block_continuation"])
        self.assertEqual(continuation["named_blocker"], "L1_CONTINUATION_WORKER_NOT_DISPATCHED")
        self.assertEqual(continuation["legacy_continuation_policy"], "legacy_rescue_only_not_mainline")
        self.assertEqual(result["mainline_next_hop"], "temporal_workflow_internal_timer_or_signal_wait")
        self.assertEqual(continuation_payloads, [])

    def test_waiting_grok_does_not_block_assignment_l1_continuation_worker(self):
        original = temporal_codex_task_workflow.call_codex_activator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []

            def fake_call(payload, *, timeout_sec):
                calls.append(dict(payload))
                task_root = root / "codex_results" / payload["task_id"]
                task_root.mkdir(parents=True, exist_ok=True)
                jsonl = task_root / "codex-events.jsonl"
                final = task_root / "final.md"
                jsonl.write_text('{"type":"thread.started"}\n{"type":"turn.completed"}\n', encoding="utf-8")
                final.write_text(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER + "\n", encoding="utf-8")
                return {
                    "ok": True,
                    "status": "PASS",
                    "task_id": payload["task_id"],
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "named_blocker": "",
                    "worker_kind": payload.get("worker_kind", ""),
                    "phase_scope": payload.get("phase_scope", ""),
                    "worker_assignment_ref": payload.get("worker_assignment_ref", ""),
                    "implementation_worker_required": payload.get("implementation_worker_required") is True,
                    "assignment_driven_dispatch": payload.get("assignment_driven_dispatch") is True,
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original)
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="temporal_waiting_grok_nonblocking_l1",
                user_goal="unit waiting Grok must not park L1 implementation worker",
                mode="partial",
                runtime_root=root,
                execute_codex_worker=True,
                codex_worker_prompt="Return " + temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                codex_worker_expected_marker=temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                extra_input={
                    "worker_kind": "implementation_worker",
                    "phase_scope": "Phase1_WP1A_human_egress_WP1B_durable_continuation",
                    "worker_assignment_ref": r"D:\XINAO_CLEAN_RUNTIME\state\worker_assignment\unit.json",
                    "work_package": {"objective": "continue same workflow while Grok gates only completion"},
                    "verification": ["same workflow history grows", "task-bound worker JSONL exists"],
                    "implementation_worker_timeout_sec": 1800,
                },
            )

        continuation = next(item for item in result["activities"] if item["activity"] == "partial_continuation_dispatch")
        self.assertEqual(result["completion_decision"]["status"], "partial")
        self.assertFalse(result["completion_decision"]["stop_allowed"])
        self.assertEqual(result["segment_audit_status"], "WAITING_GROK_SEGMENT_AUDIT")
        self.assertTrue(result["workflow_waiting_grok_segment_audit"])
        self.assertTrue(result["same_workflow_next_worker_dispatched"])
        self.assertTrue(result["assignment_driven_implementation_worker_dispatched"])
        self.assertEqual(continuation["status"], "grok_wait_l1_continuation_worker_dispatched")
        self.assertTrue(continuation["grok_waiting_does_not_block_continuation"])
        self.assertTrue(continuation["completion_stop_l2_still_gated_by_grok"])
        self.assertFalse(result["user_task_complete"])
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(any(call.get("grok_waiting_does_not_block_continuation") is True for call in calls))

    def test_partial_completion_writes_temporal_panel_readback_zh(self):
        original = temporal_codex_task_workflow.call_codex_activator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_call(payload, *, timeout_sec):
                task_root = root / "codex_results" / payload["task_id"]
                task_root.mkdir(parents=True, exist_ok=True)
                jsonl = task_root / "codex-events.jsonl"
                raw_final = task_root / "raw-final.md"
                final = task_root / "final.md"
                egress = task_root / "human-egress-filter.json"
                jsonl.write_text('{"type":"thread.started"}\n{"type":"turn.completed"}\n', encoding="utf-8")
                marker = (
                    temporal_codex_task_workflow.TASK_CONTINUATION_WORKER_MARKER
                    if "continuation" in payload["task_id"]
                    else temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER
                )
                raw_final.write_text("pytest wall 92 OK PASS\n" + marker + "\n", encoding="utf-8")
                final.write_text("段边界后台 worker 已执行；用户面只等 Grok 中文报告。\n", encoding="utf-8")
                egress_payload = {
                    "status": "SEGMENT_BOUNDARY_USER_EGRESS_BLOCKED",
                    "jobs_json_observe": {
                        "event_count": 2,
                        "event_type_counts": {"thread.started": 1, "turn.completed": 1},
                        "agent_message_count": 1,
                        "command_execution_count": 1,
                        "turn_completed_count": 1,
                        "token_usage": {"input_tokens": 19, "output_tokens": 23, "total_tokens": 42},
                        "files_modified": ["services/agent_runtime/temporal_codex_task_workflow.py"],
                        "files_modified_count": 1,
                        "command_executions": [{"command": "python -m py_compile services/agent_runtime/temporal_codex_task_workflow.py", "exit_code": 0, "output_chars": 0}],
                    },
                }
                egress.write_text(json.dumps(egress_payload, ensure_ascii=False), encoding="utf-8")
                return {
                    "ok": True,
                    "status": "PASS",
                    "task_id": payload["task_id"],
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "raw_final_path": str(raw_final),
                    "human_egress_filter_ref": str(egress),
                    "human_egress_filter": egress_payload,
                    "raw_final_backend_evidence_only": True,
                    "worker_final_user_visible_allowed": False,
                    "codex_final_to_user_allowed": False,
                    "no_pytest_wall_to_user": True,
                    "named_blocker": "",
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original)
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="temporal_panel_zh",
                user_goal="unit panel zh",
                mode="partial",
                runtime_root=root,
                execute_codex_worker=True,
                codex_worker_prompt="Return " + temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
            )
            panel_activity = next(item for item in result["activities"] if item["activity"] == "panel_writeback_zh")
            task_panel = json.loads(Path(panel_activity["panel_task_ref"]).read_text(encoding="utf-8"))
            latest_panel = json.loads((root / "state" / "codex_a_panel_readback" / "latest_intent_status.json").read_text(encoding="utf-8"))
            grok_report_text = Path(task_panel["grok_report_ref"]).read_text(encoding="utf-8")

        self.assertEqual(panel_activity["status"], "panel_writeback_zh_written")
        self.assertEqual(task_panel["task_id"], "temporal_panel_zh")
        self.assertEqual(latest_panel["task_id"], "temporal_panel_zh")
        self.assertIn("一句话状态", task_panel["panel_lines_cn"]["status_line_cn"])
        self.assertIn("卡在哪", task_panel["panel_lines_cn"]["blocked_line_cn"])
        self.assertIn("下一机器动作", task_panel["panel_lines_cn"]["next_line_cn"])
        self.assertTrue(task_panel["user_egress_sanitized"])
        self.assertEqual(task_panel["human_egress_route"], "grok_report_only")
        self.assertIn("worker final", task_panel["panel_lines_cn"]["blocked_line_cn"])
        self.assertIn("系统已自动拉 Grok 审核/授权", task_panel["panel_lines_cn"]["blocked_line_cn"])
        self.assertTrue(task_panel["grok_report_verify_pass"])
        self.assertFalse(task_panel["codex_final_to_user_allowed"])
        self.assertFalse(task_panel["worker_final_user_visible_allowed"])
        self.assertFalse(task_panel["partial_continuation_dispatched"])
        self.assertTrue(task_panel["workflow_internal_timer_scheduled"])
        self.assertEqual(task_panel["mainline_next_hop"], "temporal_workflow_internal_timer_or_signal_wait")
        self.assertTrue(task_panel["backend_codex_worker_dispatch"])
        self.assertTrue(task_panel["not_user_completion"])
        self.assertTrue(task_panel["jobs_json_observe_joined"])
        self.assertEqual(task_panel["task_bound_worker_token_usage"]["total_tokens"], 42)
        self.assertEqual(task_panel["task_bound_worker_files_modified"], ["services/agent_runtime/temporal_codex_task_workflow.py"])
        self.assertTrue(task_panel["backend_evidence_refs"]["jobs_json_observe_backend_readback"])
        self.assertTrue(task_panel["backend_evidence_refs"]["phase5_observability_discovery_readback"])
        self.assertEqual(task_panel["phase5_observability_discovery_readback"]["task_id"], "temporal_panel_zh")
        self.assertEqual(task_panel["phase5_observability_discovery_readback"]["workflow_id"], result["workflow_id"])
        self.assertTrue(task_panel["phase5_observability_discovery_readback"]["authority_boundary"]["not_source_of_truth"])
        self.assertFalse(task_panel["progress_truth_sources"]["observability_discovery_read_models"]["progress_truth_allowed"])
        self.assertTrue(task_panel["phase5_observability_discovery_readback"]["a_b_c_d_e_f_read_model_joined"])
        self.assertTrue(task_panel["phase5_observability_discovery_readback"]["trace_correlation_only"])
        self.assertTrue(task_panel["phase5_observability_discovery_readback"]["app_server_stale_cannot_override_temporal_jsonl"])
        self.assertFalse(task_panel["current_task_owner_replacement_allowed"])
        self.assertTrue(result["backend_evidence_refs"]["phase5_observability_discovery_readback"])
        self.assertEqual(result["phase5_observability_discovery_readback"]["workflow_run_id"], result["workflow_run_id"])
        self.assertFalse(result["phase5_observability_discovery_readback"]["completion_claim_allowed"])
        self.assertTrue(result["phase5_observability_discovery_readback"]["a_b_c_d_e_f_read_model_joined"])
        self.assertNotIn("92 OK", grok_report_text)
        self.assertNotIn("pytest wall", grok_report_text)

    def test_phase5_temporal_readback_keeps_observability_refs_evidence_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            readback = temporal_codex_task_workflow.phase5_observability_discovery_panel_readback(
                runtime_root,
                "task-phase5",
                "workflow-phase5",
                "run-phase5",
                str(runtime_root / "state" / "codex_results" / "task-phase5" / "codex-events.jsonl"),
            )

        self.assertEqual(readback["task_id"], "task-phase5")
        self.assertEqual(readback["workflow_id"], "workflow-phase5")
        self.assertEqual(readback["workflow_run_id"], "run-phase5")
        self.assertTrue(readback["same_workflow_required"])
        self.assertTrue(readback["task_workflow_correlated"])
        self.assertEqual(readback["default_progress_truth"], "Temporal Event History + task-bound worker JSONL evidence")
        self.assertFalse(readback["observability_progress_truth_allowed"])
        self.assertFalse(readback["catalog_progress_truth_allowed"])
        self.assertFalse(readback["model_gateway_progress_truth_allowed"])
        self.assertFalse(readback["current_task_owner_replacement_allowed"])
        self.assertFalse(readback["completion_claim_allowed"])
        self.assertTrue(readback["trace_catalog_model_refs_are_evidence_only"])
        self.assertTrue(readback["a_b_c_d_e_f_read_model_joined"])
        self.assertEqual(readback["read_model_joined_labels"], ["A", "B", "C", "D", "E", "F"])
        self.assertTrue(readback["trace_correlation_only"])
        self.assertTrue(readback["app_server_stale_cannot_override_temporal_jsonl"])
        for group in readback["read_model_join_groups"].values():
            self.assertFalse(group["completion_source_allowed"])
            self.assertFalse(group["owner_replacement_allowed"])
            self.assertTrue(group["not_source_of_truth"])
            self.assertTrue(group["not_user_completion"])
        self.assertFalse(readback["read_model_join_groups"]["F_trace_correlation"]["progress_truth_allowed"])
        self.assertEqual(
            readback["read_model_join_groups"]["F_trace_correlation"]["truth_role"],
            "correlation_only_not_completion_or_owner_truth",
        )
        self.assertTrue(readback["progress_truth_sources"]["temporal_event_history"]["progress_truth_allowed"])
        self.assertTrue(readback["progress_truth_sources"]["task_bound_worker_jsonl"]["progress_truth_allowed"])
        self.assertFalse(readback["progress_truth_sources"]["observability_discovery_read_models"]["progress_truth_allowed"])
        self.assertFalse(readback["progress_truth_sources"]["observability_discovery_read_models"]["completion_source_allowed"])
        self.assertFalse(readback["progress_truth_sources"]["observability_discovery_read_models"]["owner_replacement_allowed"])
        self.assertEqual(
            readback["truth_promotion_denied_reason"],
            "observability_discovery_read_models_are_backend_evidence_only_not_progress_truth",
        )
        self.assertTrue(readback["authority_boundary"]["observability_read_model_only"])
        self.assertTrue(readback["not_current_task_owner"])
        self.assertIn("langfuse_trace_readback", readback["evidence_refs"])
        self.assertIn("litellm_model_gateway", readback["evidence_refs"])
        self.assertIn("backstage_catalog", readback["evidence_refs"])

    def test_segment_audit_pass_forces_partial_no_auto_complete(self):
        original_activator = temporal_codex_task_workflow.call_codex_activator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_leg1_summon(root, "temporal_segment_pass_no_complete")
            write_grok_leg2_verdict(root, "temporal_segment_pass_no_complete", "pass")

            def fake_call(payload, *, timeout_sec):
                task_root = root / "codex_results" / payload["task_id"]
                task_root.mkdir(parents=True, exist_ok=True)
                jsonl = task_root / "codex-events.jsonl"
                final = task_root / "final.md"
                jsonl.write_text('{"type":"thread.started"}\n{"type":"turn.completed"}\n', encoding="utf-8")
                final.write_text(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER + "\n", encoding="utf-8")
                return {
                    "ok": True,
                    "status": "PASS",
                    "task_id": payload["task_id"],
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "named_blocker": "",
                }

            original_claim = temporal_codex_task_workflow.codex_default_task_runner.local_completion_claim

            def fake_local_completion_claim(payload, runtime_root=None):
                return {
                    "status": "complete_allowed",
                    "stop_allowed": True,
                    "reason": "unit-test-simulated-complete",
                    "named_blocker": "",
                    "not_source_of_truth": True,
                    "not_user_completion": True,
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original_activator)
            temporal_codex_task_workflow.codex_default_task_runner.local_completion_claim = fake_local_completion_claim
            self.addCleanup(
                setattr,
                temporal_codex_task_workflow.codex_default_task_runner,
                "local_completion_claim",
                original_claim,
            )
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id="temporal_segment_pass_no_complete",
                user_goal="unit segment pass must remain partial",
                mode="partial",
                runtime_root=root,
                extra_input={"phase_exit_ready": True},
            )

        self.assertEqual(result["completion_decision"]["status"], "partial")
        self.assertFalse(result["completion_decision"]["stop_allowed"])
        self.assertEqual(result["completion_decision"]["segment_audit_status"], "GROK_SEGMENT_AUDIT_PASS")
        self.assertEqual(result["completion_decision"]["segment_audit_next_lane"], "L2")
        self.assertTrue(result["same_workflow_next_worker_dispatched"])
        self.assertEqual(result["mainline_next_hop"], "same_workflow_segment_pass_next_bounded_worker")
        self.assertTrue(result["workflow_completed_is_not_user_complete"])
        self.assertFalse(result["user_task_complete"])

    def test_segment_pass_ring_regression_dispatches_same_workflow_worker_and_panel(self):
        original = temporal_codex_task_workflow.call_codex_activator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_id = "temporal_segment_pass_ring_regression"
            calls = []

            def fake_call(payload, *, timeout_sec):
                calls.append(dict(payload))
                task_root = root / "codex_results" / payload["task_id"]
                task_root.mkdir(parents=True, exist_ok=True)
                jsonl = task_root / "codex-events.jsonl"
                final = task_root / "final.md"
                jsonl.write_text('{"type":"thread.started"}\n{"type":"turn.completed"}\n', encoding="utf-8")
                final.write_text(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER + "\n", encoding="utf-8")
                return {
                    "ok": True,
                    "status": "PASS",
                    "task_id": payload["task_id"],
                    "jsonl_path": str(jsonl),
                    "final_path": str(final),
                    "named_blocker": "",
                }

            temporal_codex_task_workflow.call_codex_activator = fake_call
            self.addCleanup(setattr, temporal_codex_task_workflow, "call_codex_activator", original)
            write_leg1_summon(root, task_id)
            write_grok_leg2_verdict(root, task_id, "pass")
            result = temporal_codex_task_workflow.run_local_durable_flow(
                task_id=task_id,
                user_goal="unit pass ring must continue same workflow",
                mode="partial",
                runtime_root=root,
                execute_codex_worker=True,
                codex_worker_task_id=f"{task_id}.worker",
                codex_worker_prompt="Return " + temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER,
                extra_input={"phase_exit_ready": True},
            )
            panel_path = root / "state" / "codex_a_panel_readback" / "tasks" / f"{task_id}.json"
            panel_payload = json.loads(panel_path.read_text(encoding="utf-8"))
            router_path = root / "state" / "human_egress_router" / "tasks" / f"{task_id}.json"
            router_payload = json.loads(router_path.read_text(encoding="utf-8"))
            grok_report_exists = Path(panel_payload["grok_report_ref"]).is_file()
            router_ref_exists = Path(panel_payload["human_egress_router_ref"]).is_file()
            report_text = Path(panel_payload["grok_report_ref"]).read_text(encoding="utf-8")
            next_worker_jsonl_exists = Path(result["same_workflow_next_worker_jsonl_path"]).is_file()

        self.assertEqual(result["segment_audit_status"], "GROK_SEGMENT_AUDIT_PASS")
        self.assertTrue(result["segment_audit_pass_dual_visible_and_backend"])
        self.assertTrue(result["segment_pass_must_dispatch_next_bounded_worker"])
        self.assertTrue(result["same_workflow_next_worker_dispatched"])
        self.assertEqual(result["mainline_next_hop"], "same_workflow_segment_pass_next_bounded_worker")
        self.assertTrue(result["same_workflow_next_worker_task_id"].startswith(task_id + ".segment-pass.L2.worker"))
        self.assertTrue(next_worker_jsonl_exists)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["task_id"], f"{task_id}.worker")
        self.assertEqual(calls[1]["task_id"], result["same_workflow_next_worker_task_id"])
        self.assertIn("BOUNDED SEGMENT-PASS L2 WORKER", calls[1]["prompt"])
        self.assertIn("do not call /codex-a/intent", calls[1]["prompt"])
        self.assertIn("worker_assignment=", calls[1]["prompt"])
        self.assertIn(temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER, calls[1]["prompt"])
        self.assertTrue(panel_payload["same_workflow_next_worker_dispatched"])
        self.assertEqual(panel_payload["mainline_next_hop"], "same_workflow_segment_pass_next_bounded_worker")
        self.assertEqual(panel_payload["segment_audit_status_cn"], "等 Grok 审查")
        self.assertEqual(panel_payload["panel_lines_cn"]["segment_audit_status_cn"], "等 Grok 审查")
        self.assertIn("Grok", panel_payload["panel_lines_cn"]["next_line_cn"])
        self.assertIn("worker final", panel_payload["panel_lines_cn"]["blocked_line_cn"])
        self.assertNotIn("等待 Grok leg2 verdict", panel_payload["panel_lines_cn"]["blocked_line_cn"])
        self.assertNotIn("等待 Grok leg2 verdict", panel_payload["panel_lines_cn"]["next_line_cn"])
        self.assertTrue(panel_payload["user_egress_sanitized"])
        self.assertEqual(panel_payload["human_egress_route"], "grok_report_only")
        self.assertEqual(panel_payload["worker_final_path"], "")
        self.assertEqual(panel_payload["worker_jsonl_path"], "")
        self.assertEqual(panel_payload["same_workflow_next_worker_task_id"], "")
        self.assertEqual(panel_payload["same_workflow_next_worker_jsonl_path"], "")
        self.assertNotIn("partial_continuation_dispatch", panel_payload)
        self.assertNotIn("segment_pass_next_worker", panel_payload)
        self.assertTrue(grok_report_exists)
        self.assertTrue(router_ref_exists)
        self.assertTrue(panel_payload["backend_evidence_refs"]["worker_final_backend_only"])
        self.assertTrue(panel_payload["backend_evidence_refs"]["worker_jsonl_backend_evidence"])
        self.assertEqual(result["human_egress_route"], "grok_report_only")
        self.assertTrue(result["grok_report_verify_pass"])
        self.assertFalse(result["codex_final_to_user_allowed"])
        self.assertFalse(result["worker_final_user_visible_allowed"])
        self.assertTrue(result["no_pytest_wall_to_user"])
        self.assertEqual(panel_payload["human_egress_route"], "grok_report_only")
        self.assertTrue(panel_payload["grok_report_verify_pass"])
        self.assertTrue(router_payload["task_aligned"])
        self.assertEqual(router_payload["status"], "desktop_grok_context_reused")
        self.assertTrue(router_payload["desktop_context_continuity_verified"])
        self.assertTrue(router_payload["used_existing_grok_tui"])
        self.assertFalse(router_payload["shortcut_launched"])
        self.assertFalse(router_payload["codex_final_to_user_allowed"])
        self.assertFalse(router_payload["worker_final_user_visible_allowed"])
        self.assertIn("Codex→Grok 人类出口路由回执", report_text)
        self.assertIn("no_pytest_wall_to_user: true", report_text)
        self.assertNotIn("Ran 92", report_text)

    def test_segment_pass_next_worker_prompt_passes_activator_guard(self):
        task_id = "temporal_segment_pass_prompt_guard"
        payload = temporal_codex_task_workflow.segment_pass_next_worker_payload(
            {"task_id": task_id, "runtime_root": "D:\\XINAO_CLEAN_RUNTIME"},
            {"status": "partial", "segment_audit_next_lane": "L2"},
            {"status": "GROK_SEGMENT_AUDIT_PASS", "next_lane": "L2"},
        )

        self.assertEqual("", guard_prompt(payload["codex_worker_prompt"]))
        self.assertNotIn("Stop", payload["codex_worker_prompt"])

    def test_continue_same_task_worker_uses_assignment_implementation_not_segment_pass_default(self):
        task_id = "temporal_continue_assignment_worker_unit"
        payload = temporal_codex_task_workflow.continue_same_task_worker_payload(
            {
                "task_id": task_id,
                "runtime_root": "D:\\XINAO_CLEAN_RUNTIME",
                "workflow_id": "wf-assignment-unit",
                "workflow_run_id": "run-assignment-unit",
            },
            {
                "worker_kind": "implementation_worker",
                "phase_scope": "Phase2_WP1_WP2_assignment_driven_infinite_continuation",
                "worker_assignment_ref": "D:\\XINAO_CLEAN_RUNTIME\\state\\worker_assignment\\unit.json",
                "work_package": {"objective": "wire assignment driven implementation"},
                "verification": ["py_compile", "unittest"],
                "implementation_worker_timeout_sec": 1800,
            },
            3,
        )

        self.assertEqual(payload["worker_kind"], "implementation_worker")
        self.assertEqual(payload["phase_scope"], "Phase2_WP1_WP2_assignment_driven_infinite_continuation")
        self.assertEqual(payload["codex_worker_timeout_sec"], 1800)
        self.assertTrue(payload["implementation_worker_required"])
        self.assertFalse(payload["segment_pass_next_worker_required"])
        self.assertEqual(payload["mature_execution_carrier"], "codex_exec_json_app_server_sdk_worker")
        self.assertIn("openai/codex exec --json", payload["mature_execution_carrier_refs"])
        self.assertEqual(payload["worker_evidence_contract"], "task_bound_codex_exec_jsonl_or_app_server_sdk")
        self.assertFalse(payload["segment_pass_checker_default"])
        self.assertIn("IMPLEMENTATION WORKER", payload["codex_worker_prompt"])
        self.assertIn("work_package_json=", payload["codex_worker_prompt"])
        self.assertNotIn("BOUNDED SEGMENT-PASS L2 WORKER", payload["codex_worker_prompt"])
        self.assertNotIn("Return exactly four short lines", payload["codex_worker_prompt"])

    def test_ring_regression_segment_pass_without_next_worker_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = asyncio.run(
                temporal_codex_task_workflow.partial_continuation_dispatch_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": "RING_REGRESSION_SEGMENT_PASS_CONTINUE_V1",
                        "completion_decision": {
                            "status": "partial",
                            "stop_allowed": False,
                            "segment_audit_status": "GROK_SEGMENT_AUDIT_PASS",
                        },
                        "segment_audit_gate": {"status": "GROK_SEGMENT_AUDIT_PASS"},
                        "segment_pass_next_worker": {},
                    }
                )
            )

        self.assertEqual(result["status"], "segment_pass_next_worker_blocked")
        self.assertFalse(result["continuation_dispatched"])
        self.assertTrue(result["segment_pass_must_dispatch_next_bounded_worker"])
        self.assertFalse(result["same_workflow_next_worker_dispatched"])
        self.assertEqual(result["named_blocker"], "SEGMENT_PASS_WITHOUT_NEXT_BOUNDED_WORKER")

    def test_segment_audit_waiting_or_fail_stays_partial_with_l1_next(self):
        decision = temporal_codex_task_workflow._grok_segment_waiting_decision_override(
            {
                "status": "complete_allowed",
                "stop_allowed": True,
                "named_blocker": "",
                "not_source_of_truth": True,
                "not_user_completion": True,
            },
            {"status": "GROK_SEGMENT_AUDIT_FAIL", "next_lane": "L1", "named_blocker": "GROK_SEGMENT_AUDIT_FAILED_CONTINUE_L1"},
        )
        self.assertEqual(decision["status"], "partial")
        self.assertFalse(decision["stop_allowed"])
        self.assertEqual(decision["segment_audit_status"], "GROK_SEGMENT_AUDIT_FAIL")
        self.assertEqual(decision["segment_audit_next_lane"], "L1")
        self.assertEqual(decision["named_blocker"], "GROK_SEGMENT_AUDIT_FAILED_CONTINUE_L1")

    def test_audit_authorization_pull_request_is_segment_audit_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = temporal_codex_task_workflow._write_audit_authorization_pull_request(
                root,
                "unit_auth_pull_segment_only",
                {
                    "segment_id": "phase_exit_unit",
                    "named_blocker": "GROK_SEGMENT_AUDIT_VERDICT_REQUIRED",
                },
                source="unit_test",
            )
            task_payload = json.loads(Path(result["task_ref"]).read_text(encoding="utf-8"))

        self.assertTrue(task_payload["segment_audit_only"])
        self.assertEqual(task_payload["reviewer_lane"], "grok_segment_audit")
        self.assertEqual(task_payload["authorization_lane"], "grok_segment_audit_dual_visible_and_backend_verdict")
        self.assertEqual(task_payload["authorization_scope"], "phase_exit_segment_audit_only")
        self.assertEqual(task_payload["segment_audit_authorization_lane"], "grok_segment_audit_dual_visible_and_backend_verdict")
        self.assertEqual(task_payload["segment_audit_verdict_authorization_lane"], "grok_segment_audit_dual_visible_and_backend_verdict")
        self.assertEqual(task_payload["continuation_authorization_lane"], "codex_a_brain_dispatch")
        self.assertEqual(task_payload["continuation_gate_owner"], "codex_a_brain_plus_temporal_assignment_dag")
        self.assertFalse(task_payload["waiting_grok_blocks_continuation"])
        self.assertTrue(task_payload["waiting_grok_blocks_completion_stop_l2"])
        self.assertFalse(task_payload["grok_mainchain_authorization_allowed"])

    def test_segment_audit_not_ready_blocks_completion_claim_and_keeps_frontier(self):
        decision = temporal_codex_task_workflow._grok_segment_waiting_decision_override(
            {
                "status": "complete_allowed",
                "stop_allowed": True,
                "named_blocker": "",
                "not_source_of_truth": True,
                "not_user_completion": True,
            },
            {"status": "segment_audit_not_ready", "next_lane": "L1"},
        )

        self.assertEqual(decision["status"], "partial")
        self.assertFalse(decision["stop_allowed"])
        self.assertEqual(decision["named_blocker"], "GROK_SEGMENT_AUDIT_REQUIRED")
        self.assertEqual(decision["segment_audit_status"], "segment_audit_not_ready")
        self.assertEqual(decision["segment_audit_next_lane"], "L1")

    def test_grok_180s_no_reply_allows_codexa_brain_fallback_l1_only(self):
        task_id = "unit_grok_timeout_codexa_brain"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_path = root / "state" / "l1_l2_segment_gate" / "latest.json"
            gate_path.parent.mkdir(parents=True, exist_ok=True)
            stale = (dt.datetime.now(dt.timezone.utc).astimezone() - dt.timedelta(seconds=181)).isoformat()
            gate_path.write_text(
                json.dumps(
                    {
                        "schema_version": "xinao.l1_l2_segment_gate.v1",
                        "predecessor_task_id": task_id,
                        "segment_audit_ready": True,
                        "segment_id": "phase0_phase1",
                        "generated_at": stale,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {"runtime_root": str(root), "task_id": task_id}
                )
            )

        self.assertEqual(result["status"], "GROK_SEGMENT_AUDIT_TIMEOUT_CODEXA_BRAIN_FALLBACK")
        self.assertEqual(result["next_lane"], "L1")
        self.assertTrue(result["codexa_brain_fallback_allowed"])
        self.assertTrue(result["codexa_brain_fallback_active"])
        self.assertFalse(result["codexa_brain_fallback_is_l2"])
        self.assertEqual(result["named_blocker"], "GROK_180S_NO_REPLY_CODEXA_BRAIN_FALLBACK_L1")

    def test_grok_timeout_fallback_dispatches_l1_implementation_continuation(self):
        task_id = "unit_grok_timeout_l1_dispatch"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_jsonl = root / "state" / "codex_results" / f"{task_id}.worker" / "codex-events.jsonl"
            worker_jsonl.parent.mkdir(parents=True, exist_ok=True)
            worker_jsonl.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
            result = asyncio.run(
                temporal_codex_task_workflow.partial_continuation_dispatch_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": task_id,
                        "completion_decision": {"status": "partial", "stop_allowed": False},
                        "segment_audit_gate": {
                            "status": "GROK_SEGMENT_AUDIT_TIMEOUT_CODEXA_BRAIN_FALLBACK",
                            "next_lane": "L1",
                            "workflow_waiting_grok_segment_audit": False,
                            "codexa_brain_fallback_allowed": True,
                            "codexa_brain_fallback_active": True,
                            "named_blocker": "GROK_180S_NO_REPLY_CODEXA_BRAIN_FALLBACK_L1",
                        },
                        "segment_pass_next_worker": {
                            "status": "activity_gate_checked",
                            "worker_kind": "implementation_worker",
                            "implementation_worker_required": True,
                            "worker_task_id": f"{task_id}.continue-same-task.worker.1",
                            "jsonl_path": str(worker_jsonl),
                        },
                    }
                )
            )

        self.assertEqual(result["status"], "grok_wait_l1_continuation_worker_dispatched")
        self.assertTrue(result["continuation_dispatched"])
        self.assertTrue(result["same_workflow_next_worker_dispatched"])
        self.assertTrue(result["assignment_driven_implementation_worker_dispatched"])
        self.assertEqual(result["authorization_lane"], "codex_a_brain_dispatch")
        self.assertTrue(result["completion_stop_l2_still_gated_by_grok"])
        self.assertFalse(result["waiting_grok_blocks_continuation"])

    def test_panel_show_waiting_segment_gates(self):
        task_id = "unit_panel_segment_wait"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = root / "state" / "l1_l2_segment_gate" / "latest.json"
            gate.parent.mkdir(parents=True, exist_ok=True)
            gate.write_text(
                json.dumps(
                    {
                        "schema_version": "xinao.l1_l2_segment_gate.v1",
                        "segment_audit_ready": True,
                        "predecessor_task_id": task_id,
                        "segment_id": "phase0_phase1",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            segment_gate = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {"runtime_root": str(root), "task_id": task_id}
                )
            )
            panel = asyncio.run(
                temporal_codex_task_workflow.panel_writeback_zh_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": task_id,
                        "completion_decision": {"status": "complete_allowed", "stop_allowed": True},
                        "partial_continuation_dispatch": {"continuation_dispatched": False},
                        "worker_dispatch_evidence": {"status": "activity_gate_checked"},
                        "segment_audit_gate": segment_gate,
                    }
                )
            )
            panel_payload = json.loads(Path(panel["panel_task_ref"]).read_text(encoding="utf-8"))

        self.assertEqual(panel["status"], "panel_writeback_zh_written")
        self.assertIn("Grok", panel_payload["panel_lines_cn"]["blocked_line_cn"])
        self.assertIn("worker final", panel_payload["panel_lines_cn"]["blocked_line_cn"])
        self.assertTrue(panel_payload["user_egress_sanitized"])
        self.assertEqual(panel_payload["human_egress_route"], "grok_report_only")
        self.assertIn("下一机器动作", panel_payload["panel_lines_cn"]["next_line_cn"])

    def test_segment_audit_gate_writes_human_egress_before_summon(self):
        task_id = "unit_segment_gate_egress_before_summon"
        original = temporal_codex_task_workflow._send_codex_segment_audit_summon_to_grok
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seen = {}

            def fake_send(runtime_root, task_id_arg, segment_gate, *, source):
                report = runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "reports" / f"{task_id}.grok_report.zh.md"
                router = runtime_root / "state" / "human_egress_router" / "tasks" / f"{task_id}.json"
                seen["report_exists_before_summon"] = report.is_file()
                seen["router_exists_before_summon"] = router.is_file()
                return {
                    "task_ref": str(runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "tasks" / f"{task_id}.json"),
                    "latest_ref": str(runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "latest.json"),
                    "delivery_mode": "dual_visible_and_backend",
                    "visible_ref": "visible.md",
                    "visible_trace_ref": "visible_trace.json",
                    "cross_check": {"same_task_id_and_window": True},
                }

            temporal_codex_task_workflow._send_codex_segment_audit_summon_to_grok = fake_send
            self.addCleanup(
                setattr,
                temporal_codex_task_workflow,
                "_send_codex_segment_audit_summon_to_grok",
                original,
            )
            result = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": task_id,
                        "segment_complete": True,
                        "segment_id": "phase0_phase1",
                    }
                )
            )

        self.assertTrue(seen["report_exists_before_summon"])
        self.assertTrue(seen["router_exists_before_summon"])
        self.assertTrue(result["human_egress_report_written_before_summon"])
        self.assertEqual(result["egress_before_summon_order"], "human_egress_report_then_leg1_summon")

    def test_segment_completion_candidate_materializes_ready_and_waits_for_grok(self):
        task_id = "unit_segment_complete_waits_grok"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner_dir = root / "state" / "current_task_owner"
            owner_dir.mkdir(parents=True, exist_ok=True)
            (owner_dir / "latest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "xinao.current_task_owner.v1",
                        "task_id": task_id,
                        "segment_audit_ready": False,
                        "workflow_waiting_grok_segment_audit": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            trace_dir = root / "state" / "action_delivery_trace"
            trace_dir.mkdir(parents=True, exist_ok=True)
            (trace_dir / f"{task_id}.jsonl").write_text(
                json.dumps(
                    {
                        "schema_version": "xinao.action-delivery-trace-event.v1",
                        "task_id": task_id,
                        "event_name": "unit.segment.ready",
                        "timestamp": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            segment_gate = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": task_id,
                        "completion_decision": {"status": "partial", "stop_allowed": False},
                        "segment_complete": True,
                        "worker_dispatch_evidence": {"status": "activity_gate_checked"},
                    }
                )
            )
            panel = asyncio.run(
                temporal_codex_task_workflow.panel_writeback_zh_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": task_id,
                        "completion_decision": {"status": "complete_allowed", "stop_allowed": True},
                        "partial_continuation_dispatch": {"continuation_dispatched": False},
                        "worker_dispatch_evidence": {"status": "activity_gate_checked"},
                        "segment_audit_gate": segment_gate,
                    }
                )
            )
            l1_task = json.loads(
                (root / "state" / "l1_l2_segment_gate" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8")
            )
            grok_task_path = root / "state" / "grok_l1_l2_segment_gate" / "tasks" / f"{task_id}.json"
            request_task = json.loads(
                (root / "state" / "grok_segment_audit_request" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8")
            )
            summon_task = json.loads(
                (root / "state" / "codex_to_grok_segment_audit_summon" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8")
            )
            summon_latest = json.loads(
                (root / "state" / "codex_to_grok_segment_audit_summon" / "latest.json").read_text(encoding="utf-8")
            )
            action_trace = (root / "state" / "action_delivery_trace" / f"{task_id}.jsonl").read_text(encoding="utf-8")
            visible_md = root / "grok-admin-bridge" / "inbox" / "segment_audit_summon_visible.md"
            owner_latest = json.loads((owner_dir / "latest.json").read_text(encoding="utf-8"))
            panel_payload = json.loads(Path(panel["panel_task_ref"]).read_text(encoding="utf-8"))
            human_egress_router_exists = (root / "state" / "human_egress_router" / "tasks" / f"{task_id}.json").is_file()
            grok_report_exists = Path(panel_payload["grok_report_ref"]).is_file()

        self.assertEqual(segment_gate["status"], "WAITING_GROK_SEGMENT_AUDIT")
        self.assertTrue(segment_gate["segment_complete_seen"])
        self.assertTrue(segment_gate["segment_audit_ready"])
        self.assertTrue(segment_gate["segment_audit_ready_projection_written"])
        self.assertTrue(segment_gate["workflow_waiting_grok_segment_audit"])
        self.assertFalse(segment_gate["tui_self_stop_allowed"])
        self.assertFalse(segment_gate["completion_claim_allowed"])
        self.assertFalse(segment_gate["stop_allowed_without_grok_pass"])
        self.assertEqual(l1_task["task_id"], task_id)
        self.assertTrue(l1_task["segment_audit_ready"])
        self.assertEqual(l1_task["status"], "SEGMENT_COMPLETE_WAITING_GROK_HOTPATH_READY")
        self.assertFalse(grok_task_path.exists())
        self.assertEqual(request_task["task_id"], task_id)
        self.assertTrue(request_task["grok_notified"])
        self.assertFalse(request_task["grok_chat_window_push_allowed"])
        self.assertFalse(request_task["automatic_verdict_allowed"])
        self.assertEqual(request_task["grok_verdict"], "")
        self.assertEqual(summon_task["task_id"], task_id)
        self.assertEqual(summon_task["delivery_mode"], "backend_only_state")
        self.assertFalse(summon_task["frontend_tui_required"])
        self.assertFalse(summon_task["frontend_tui_sent"])
        self.assertFalse(summon_task["grok_visible_delivery_auto_open_allowed"])
        self.assertFalse(summon_task["grok_reads_state_only_when_user_requests_review"])
        self.assertTrue(summon_task["auto_review_requested"])
        self.assertEqual(summon_task["audit_request_status"], "pending_recoverable")
        self.assertEqual(summon_task["grok_bridge_availability"], "degraded")
        self.assertFalse(summon_task["user_must_carry_logs"])
        self.assertEqual(summon_latest["task_id"], task_id)
        self.assertTrue(summon_task["cross_check"]["same_task_id_and_window"])
        self.assertFalse(visible_md.exists())
        self.assertIn("codex_to_grok_segment_audit_summon.backend_state_written", action_trace)
        self.assertTrue(owner_latest["segment_audit_ready"])
        self.assertTrue(owner_latest["workflow_waiting_grok_segment_audit"])
        self.assertEqual(owner_latest["segment_audit_status"], "WAITING_GROK_SEGMENT_AUDIT")
        self.assertIn("系统已自动拉 Grok 审核/授权", panel_payload["panel_lines_cn"]["blocked_line_cn"])
        self.assertIn("Codex 不直出验收报告", panel_payload["panel_lines_cn"]["status_line_cn"])
        self.assertIn("Grok 可自动采证据后回 Codex", panel_payload["panel_lines_cn"]["next_line_cn"])
        self.assertTrue(panel_payload["grok_segment_audit_request_written"])
        self.assertTrue(panel_payload["codex_to_grok_segment_audit_summon_written"])
        self.assertEqual(panel_payload["codex_to_grok_segment_audit_summon_delivery_mode"], "backend_only_state")
        self.assertFalse(panel_payload["grok_visible_delivery_auto_open_allowed"])
        self.assertFalse(panel_payload["grok_reads_state_only_when_user_requests_review"])
        self.assertTrue(panel_payload["auto_review_requested"])
        self.assertTrue(panel_payload["grok_auto_review_requested"])
        self.assertFalse(panel_payload["user_requested_grok_review_required"])
        self.assertTrue(panel_payload["grok_notified"])
        self.assertFalse(panel_payload["grok_chat_window_push_allowed"])
        self.assertFalse(panel_payload["automatic_verdict_allowed"])
        self.assertEqual(panel_payload["panel_lines_cn"]["next_human_action_cn"], "")
        self.assertEqual(panel_payload["next_human_action_cn"], "")
        self.assertEqual(panel_payload["human_egress_route"], "grok_report_only")
        self.assertTrue(panel_payload["grok_report_verify_pass"])
        self.assertFalse(panel_payload["codex_final_to_user_allowed"])
        self.assertFalse(panel_payload["worker_final_user_visible_allowed"])
        self.assertTrue(human_egress_router_exists)
        self.assertTrue(grok_report_exists)

    def test_new_continue_worker_reopens_segment_audit_after_old_pass(self):
        task_id = "unit_continue_worker_reopens_segment_audit"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_gate_dir = root / "state" / "l1_l2_segment_gate" / "tasks"
            old_gate_dir.mkdir(parents=True, exist_ok=True)
            (old_gate_dir / f"{task_id}.json").write_text(
                json.dumps(
                    {
                        "schema_version": "xinao.l1_l2_segment_gate.v1",
                        "task_id": task_id,
                        "segment_id": "phase0_phase1",
                        "worker_task_id": f"{task_id}.continue-same-task.worker.1.old",
                        "segment_audit_ready": True,
                        "workflow_waiting_grok_segment_audit": False,
                        "status": "GROK_SEGMENT_AUDIT_PASS",
                        "grok_verdict": "pass",
                        "verdict_delivery_mode": "dual_visible_and_backend",
                        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_grok_dir = root / "state" / "grok_l1_l2_segment_gate" / "tasks"
            old_grok_dir.mkdir(parents=True, exist_ok=True)
            (old_grok_dir / f"{task_id}.json").write_text(
                json.dumps(
                    {
                        "task_id": task_id,
                        "segment_id": "phase0_phase1",
                        "segment_audit_ready": True,
                        "grok_verdict": "pass",
                        "verdict_delivery_mode": "dual_visible_and_backend",
                        "dual_visible_and_backend_verdict": True,
                        "leg1_summon_cross_check_valid": True,
                        "leg1_summon_ref": "old-leg1.json",
                        "evidence_refs": ["state/action_delivery_trace/old.jsonl"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            segment_gate = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": task_id,
                        "segment_id": "Phase5_observability_discovery_trace_binding",
                        "segment_complete": True,
                        "completion_decision": {"status": "partial", "stop_allowed": False},
                        "worker_dispatch_evidence": {
                            "ok": True,
                            "status": "PASS",
                            "worker_task_id": f"{task_id}.continue-same-task.worker.30.new",
                            "jsonl_path": str(root / "state" / "codex_results" / "new" / "codex-events.jsonl"),
                        },
                    }
                )
            )
            l1_task = json.loads((old_gate_dir / f"{task_id}.json").read_text(encoding="utf-8"))

        self.assertEqual(segment_gate["status"], "WAITING_GROK_SEGMENT_AUDIT")
        self.assertEqual(segment_gate["segment_id"], "Phase5_observability_discovery_trace_binding")
        self.assertEqual(l1_task["segment_id"], "Phase5_observability_discovery_trace_binding")
        self.assertEqual(l1_task["worker_task_id"], f"{task_id}.continue-same-task.worker.30.new")
        self.assertTrue(segment_gate["workflow_waiting_grok_segment_audit"])
        self.assertEqual(segment_gate["grok_verdict"], "")
        self.assertFalse(segment_gate["grok_segment_verdict_leg2_valid"])

    def test_workflow_wait_condition_timeouts_are_durable_not_failed(self):
        source = Path(temporal_codex_task_workflow.__file__).read_text(encoding="utf-8")
        self.assertIn("except (asyncio.TimeoutError, TimeoutError):", source)
        self.assertNotIn("lambda: bool(self.grok_segment_verdict_signal)", source)
        self.assertIn("lambda: bool(self.continue_same_task_signals)", source)

    def test_live_workflow_grok_wait_branch_has_activity_accumulator_before_l1_worker(self):
        source = Path(temporal_codex_task_workflow.__file__).read_text(encoding="utf-8")
        accumulator = "activities = [bound, graph, codex_worker, claim, status, segment_gate]"
        l1_worker = (
            "grok_wait_l1_continuation_worker_payload(input_payload, decision, "
            "segment_gate if isinstance(segment_gate, dict) else {}, len(activities) + 1)"
        )

        self.assertIn(accumulator, source)
        self.assertIn(l1_worker, source)
        self.assertLess(source.index(accumulator), source.index(l1_worker))

    def test_l1_l2_segment_gate_pass_evaluation_updates_task_file(self):
        task_id = "unit_l1_l2_gate_pass_file_sync"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_dir = root / "state" / "l1_l2_segment_gate" / "tasks"
            gate_dir.mkdir(parents=True, exist_ok=True)
            (gate_dir / f"{task_id}.json").write_text(
                json.dumps(
                    {
                        "schema_version": "xinao.l1_l2_segment_gate.v1",
                        "task_id": task_id,
                        "segment_id": "PhaseExit_unit",
                        "worker_task_id": f"{task_id}.worker.1",
                        "segment_audit_ready": True,
                        "workflow_waiting_grok_segment_audit": True,
                        "status": "SEGMENT_COMPLETE_WAITING_GROK_HOTPATH_READY",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            temporal_codex_task_workflow._sync_l1_l2_segment_gate_evaluation(
                root,
                task_id,
                {
                    "status": "GROK_SEGMENT_AUDIT_PASS",
                    "segment_id": "PhaseExit_unit",
                    "worker_task_id": f"{task_id}.worker.1",
                    "worker_jsonl_path": str(root / "state" / "codex_results" / "worker" / "codex-events.jsonl"),
                    "segment_audit_ready": True,
                    "workflow_waiting_grok_segment_audit": False,
                    "grok_verdict": "pass",
                    "verdict_delivery_mode": "dual_visible_and_backend",
                    "dual_visible_and_backend_verdict": True,
                    "codex_to_grok_segment_audit_summon_valid": True,
                    "grok_segment_verdict_leg2_valid": True,
                    "bidirectional_dual_delivery_full_ring_valid": True,
                    "next_lane": "L2",
                    "l2_release_allowed": True,
                },
            )
            task_gate = json.loads((gate_dir / f"{task_id}.json").read_text(encoding="utf-8"))
            latest_gate = json.loads((root / "state" / "l1_l2_segment_gate" / "latest.json").read_text(encoding="utf-8"))

        self.assertEqual(task_gate["status"], "GROK_SEGMENT_AUDIT_PASS")
        self.assertFalse(task_gate["workflow_waiting_grok_segment_audit"])
        self.assertEqual(task_gate["grok_verdict"], "pass")
        self.assertEqual(task_gate["next_lane"], "L2")
        self.assertTrue(task_gate["l2_release_allowed"])
        self.assertEqual(latest_gate["task_id"], task_id)

    def test_segment_gate_reuses_existing_worker_result_after_reset_conflict(self):
        task_id = "unit_segment_gate_reuses_reset_conflict_result"
        worker_task = f"{task_id}.continue-same-task.worker.33.same"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_dir = root / "state" / "codex_results" / worker_task
            result_dir.mkdir(parents=True, exist_ok=True)
            (result_dir / "codex-events.jsonl").write_text('{"event":"ok"}\n', encoding="utf-8")
            (result_dir / "result.json").write_text(
                json.dumps(
                    {
                        "task_id": worker_task,
                        "ok": True,
                        "status": "PASS",
                        "exit_code": 0,
                        "named_blocker": "",
                        "jsonl_path": str(result_dir / "codex-events.jsonl"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            segment_gate = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {
                        "runtime_root": str(root),
                        "task_id": task_id,
                        "segment_id": "PhaseExit_phase1_5_mature_max_segment_audit",
                        "segment_complete": True,
                        "completion_decision": {"status": "partial", "stop_allowed": False},
                        "worker_dispatch_evidence": {
                            "status": "activity_blocked",
                            "named_blocker": "CODEX_ACTIVATOR_TASK_ID_CONFLICT",
                            "worker_task_id": worker_task,
                        },
                    }
                )
            )
            l1_task = json.loads(
                (root / "state" / "l1_l2_segment_gate" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8")
            )

        self.assertEqual(segment_gate["status"], "WAITING_GROK_SEGMENT_AUDIT")
        self.assertTrue(segment_gate["workflow_waiting_grok_segment_audit"])
        self.assertEqual(l1_task["worker_task_id"], worker_task)
        self.assertEqual(l1_task["worker_jsonl_path"], str(result_dir / "codex-events.jsonl"))
        self.assertTrue(l1_task["segment_audit_ready"])

    def test_old_grok_latest_does_not_smear_into_current_task(self):
        task_id = "unit_current_without_grok_task"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "state" / "grok_l1_l2_segment_gate" / "latest.json"
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text(
                json.dumps(
                    {
                        "task_id": "old-task",
                        "segment_audit_ready": True,
                        "verdict": "pass",
                        "verdict_delivery_mode": "dual_visible_and_backend",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ready = root / "state" / "l1_l2_segment_gate" / "tasks" / f"{task_id}.json"
            ready.parent.mkdir(parents=True, exist_ok=True)
            ready.write_text(
                json.dumps(
                    {
                        "schema_version": "xinao.l1_l2_segment_gate.v1",
                        "task_id": task_id,
                        "segment_audit_ready": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {"runtime_root": str(root), "task_id": task_id}
                )
            )

        self.assertEqual(result["status"], "WAITING_GROK_SEGMENT_AUDIT")
        self.assertTrue(result["grok_latest_stale_for_task"])
        self.assertEqual(result["grok_verdict"], "")
        self.assertEqual(result["grok_gate_ref"], "")

    def test_codex_default_runner_can_use_temporal_binding(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            task_id = f"default_temporal_{Path(tmp).name}"
            state = codex_default_task_runner.run_task(
                task_id=task_id,
                user_goal="unit default temporal",
                mode="complete",
                runtime_root=Path(tmp),
                use_temporal_binding=True,
                execute_codex_worker=False,
        )

        self.assertEqual(state["status"], "default_task_live_temporal_binding_checked")
        self.assertIn(state["decision"]["status"], {"partial", "blocked"})
        self.assertFalse(state["complete_allowed"])
        self.assertIn("temporal_workflow", state)
        self.assertTrue(state["not_source_of_truth"])
        self.assertTrue(state["not_user_completion"])
        self.assertTrue(state["temporal_workflow"]["not_source_of_truth"])
        self.assertTrue(state["temporal_workflow"]["not_user_completion"])
        self.assertTrue(state["temporal_workflow"]["workflow_completed_is_not_user_complete"])
        if state["decision"]["status"] == "blocked":
            self.assertFalse(state["temporal_workflow"]["worker_service_polling"])
            self.assertEqual(
                state["decision"]["named_blocker"],
                "TEMPORAL_WORKER_SERVICE_NOT_POLLING",
            )
        else:
            self.assertTrue(state["temporal_workflow"]["worker_service_polling"])

    def test_segment_audit_ready_waits_for_dual_visible_and_backend_grok_verdict(self):
        task_id = "unit_segment_wait"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_path = root / "state" / "l1_l2_segment_gate" / "latest.json"
            gate_path.parent.mkdir(parents=True, exist_ok=True)
            gate_path.write_text(
                json.dumps(
                    {
                        "schema_version": "xinao.l1_l2_segment_gate.v1",
                        "predecessor_task_id": task_id,
                        "segment_audit_ready": True,
                        "segment_id": "phase0_phase1",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {"runtime_root": str(root), "task_id": task_id}
                )
            )

        self.assertEqual(result["status"], "WAITING_GROK_SEGMENT_AUDIT")
        self.assertTrue(result["segment_audit_ready"])
        self.assertTrue(result["workflow_waiting_grok_segment_audit"])
        self.assertEqual(result["named_blocker"], "")
        self.assertTrue(result["grok_waiting_does_not_block_continuation"])
        self.assertTrue(result["grok_segment_verdict_gates_completion_stop_l2_only"])
        self.assertFalse(result["grok_segment_verdict_wait_blocking"])
        self.assertTrue(result["dual_visible_and_backend_required"])
        self.assertFalse(result["backend_only_verdict_allowed"])
        self.assertFalse(result["continuation_n_segment_audit_pass_allowed"])

    def test_segment_audit_backend_only_grok_verdict_does_not_release_l2(self):
        task_id = "unit_segment_backend_only"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grok_path = root / "state" / "grok_l1_l2_segment_gate" / "tasks" / f"{task_id}.json"
            grok_path.parent.mkdir(parents=True, exist_ok=True)
            grok_path.write_text(
                json.dumps(
                    {
                        "segment_audit_ready": True,
                        "verdict": "pass",
                        "verdict_delivery_mode": "backend_only",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {"runtime_root": str(root), "task_id": task_id}
                )
            )

        self.assertEqual(result["status"], "WAITING_GROK_SEGMENT_AUDIT")
        self.assertEqual(result["named_blocker"], "GROK_SEGMENT_VERDICT_DUAL_DELIVERY_REQUIRED")
        self.assertTrue(result["backend_only_verdict_seen"])
        self.assertFalse(result["dual_visible_and_backend_verdict"])
        self.assertEqual(result["next_lane"], "L1")

    def test_segment_audit_dual_visible_and_backend_pass_releases_l2(self):
        task_id = "unit_segment_dual_pass"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_leg1_summon(root, task_id)
            write_grok_leg2_verdict(root, task_id, "pass")

            result = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {"runtime_root": str(root), "task_id": task_id}
                )
            )

        self.assertEqual(result["status"], "GROK_SEGMENT_AUDIT_PASS")
        self.assertEqual(result["named_blocker"], "")
        self.assertTrue(result["dual_visible_and_backend_verdict"])
        self.assertEqual(result["next_lane"], "L2")

    def test_segment_audit_dual_visible_pass_without_leg1_stays_l1(self):
        task_id = "unit_segment_dual_pass_without_leg1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grok_path = root / "state" / "grok_l1_l2_segment_gate" / "tasks" / f"{task_id}.json"
            grok_path.parent.mkdir(parents=True, exist_ok=True)
            grok_path.write_text(
                json.dumps(
                    {
                        "segment_audit_ready": True,
                        "verdict": "pass",
                        "verdict_delivery_mode": "dual_visible_and_backend",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {"runtime_root": str(root), "task_id": task_id}
                )
            )

        self.assertEqual(result["status"], "WAITING_GROK_SEGMENT_AUDIT")
        self.assertEqual(result["named_blocker"], "CODEX_TO_GROK_SEGMENT_AUDIT_SUMMON_REQUIRED")
        self.assertEqual(result["next_lane"], "L1")

    def test_segment_audit_dual_visible_and_backend_fail_blocks_l2(self):
        task_id = "unit_segment_dual_fail"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_leg1_summon(root, task_id)
            write_grok_leg2_verdict(root, task_id, "fail")

            result = asyncio.run(
                temporal_codex_task_workflow.segment_audit_gate_activity(
                    {"runtime_root": str(root), "task_id": task_id}
                )
            )

        self.assertEqual(result["status"], "GROK_SEGMENT_AUDIT_FAIL")
        self.assertEqual(result["named_blocker"], "GROK_SEGMENT_AUDIT_FAILED_CONTINUE_L1")
        self.assertTrue(result["dual_visible_and_backend_verdict"])
        self.assertEqual(result["next_lane"], "L1")


if __name__ == "__main__":
    unittest.main()
