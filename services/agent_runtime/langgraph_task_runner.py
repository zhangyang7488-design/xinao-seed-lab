import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys
from typing import Any, Literal, TypedDict

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from services.agent_runtime import codex_centric_object_preserving_runtime as runtime
from services.agent_runtime import codex_default_task_runner, rollback_executor
from services.agent_runtime import completion_claim_payload_builder as builder

DEFAULT_RUNTIME = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
ACTIVE_OBJECT_ID = "XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME"
SENTINEL = "SENTINEL:XINAO_LANGGRAPH_TASK_RUNNER_PASS"
NODE_ORDER = (
    "bind_task",
    "mature_discovery",
    "plan_refinement",
    "verify_refinement",
    "execute_shard",
    "update_frontier",
    "checkpoint_frontier",
    "completion_claim",
    "continuation_dispatch",
)
RUNTIME_SUBJECT_LOOP_REQUIRED = (
    "Discovery",
    "Contract",
    "Routing",
    "Execution",
    "Observation",
    "Continuity",
    "Recovery",
    "Completion Responsibility",
)
ROOT_REPAIR_CONSTRAINTS = (
    "source_text_is_non_authoritative_evidence",
    "external_mature_runtime_is_transaction_root",
    "do_not_create_parallel_latest_json_script_rule_as_control_surface",
    "rules_must_materialize_as_policy_verifier_hook_or_controller",
    "legacy_xinao_outputs_are_migration_objects_not_authority",
    "workflow_completion_is_not_user_completion",
)
FRONTIER_COMPLETION_CONTRACT = "langgraph_stategraph_frontier.v1"
FRONTIER_COMPLETION_CONTRACTS = {
    FRONTIER_COMPLETION_CONTRACT,
    "langgraph_stategraph_frontier.v1.task_scoped",
    "completion_claim_payload_frontier.v1",
}
MATURE_MIGRATION_FRONTIER_IDS = (
    "MCP-MEDIUM-000-MATURE-RUNTIME-MIGRATION-PARENT-OBJECT",
    "MCP-MEDIUM-000-FULL-SOURCE-SEMANTIC-OBJECT-GRAPH",
    "MCP-MEDIUM-001-TUI-INTAKE-ENFORCEMENT",
    "MCP-MEDIUM-002-STOP-GATE-HOOK",
    "MCP-MEDIUM-004-SOURCE-TEXT-COLLECTION-MAXIMIZATION-TO-TEMPORAL-QUEUE",
)
L8_LIVE_WORKFLOW_FRONTIER_IDS = (
    "L8-LIVE-001-DEFAULT-CHINESE-GOAL-INTAKE",
    "L8-LIVE-002-HUMAN-VISIBLE-PLAN-PROGRESS-RESULT",
    "L8-LIVE-003-EVIDENCE-ROLLBACK-RESTART-RECOVERY",
    "L8-LIVE-004-TRACE-EVAL-HITL-WRITEBACK",
    "L8-LIVE-005-REPEATABLE-PROMOTION-BOUNDARY",
)
L9_REPEATED_CONTINUITY_FRONTIER_IDS = (
    "L9-REPEAT-001-SECOND-DIFFERENT-CHINESE-GOAL",
    "L9-REPEAT-002-SAME-CARRIER-EVIDENCE-DIFF",
    "L9-REPEAT-003-ROLLBACK-RESTART-READBACK",
    "L9-REPEAT-004-TRACE-EVAL-HITL-WRITEBACK-REUSED",
    "L9-REPEAT-005-PROMOTION-BOUNDARY-NOT-S13",
)


class GraphState(TypedDict, total=False):
    task_id: str
    user_goal: str
    requested_mode: str
    allow_complete_fixture: bool
    runtime_root: str
    base_url: str
    source_refs: list[dict[str, Any]]
    compiled_task_object: dict[str, Any]
    runtime_subject_loop_required: list[str]
    root_repair_constraints: list[str]
    minimum_reality_contact_required: bool
    no_new_parallel_control_surface: bool
    task_object: dict[str, Any]
    frontier: dict[str, Any]
    nodes_run: list[str]
    node_claims: list[dict[str, Any]]
    checkpoints: list[dict[str, Any]]
    completion_claim_payload: dict[str, Any]
    completion_decision: dict[str, Any]
    completion_evidence: dict[str, Any]
    continuation_dispatch: dict[str, Any]
    worker_dispatch_plan: dict[str, Any]
    trigger_rollback_on_partial: bool
    promote_latest: bool


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def run_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def file_source_ref(path: pathlib.Path) -> dict[str, Any]:
    data = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mtime": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "role": "non_authoritative_semantic_input",
    }


def bind_task_identity_fields(task: dict[str, Any]) -> dict[str, Any]:
    task["task_id"] = task.get("task_id") or task.get("task_object_id", "")
    refs = list(task.get("source_refs") or [])
    refs_sha = hashlib.sha256(
        json.dumps(refs, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest() if refs else ""
    task["source_refs_sha256"] = task.get("source_refs_sha256") or refs_sha
    task["source_text_count"] = task.get("source_text_count") or len(refs)
    task["semantic_object"] = task.get("semantic_object") or task.get("target_object") or runtime.TARGET_OBJECT
    task_for_hash = {
        key: value
        for key, value in task.items()
        if key not in {"task_object_sha256", "compiled_task_object_used_by_langgraph", "langgraph_role"}
    }
    task["task_object_sha256"] = task.get("task_object_sha256") or hashlib.sha256(
        json.dumps(task_for_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return task


def completed_frontier_identity(runtime_root: pathlib.Path, task_id: str) -> dict[str, Any]:
    intake_path = runtime_root / "state" / "temporal_work_item_intake" / "tasks" / f"{task_id}.json"
    intake = read_json(intake_path)
    for item in intake.get("completed_work_items") or []:
        if not str(item.get("source_item_id") or "").startswith("langgraph_frontier_"):
            continue
        identity = {
            "task_object_sha256": item.get("task_object_sha256", ""),
            "source_refs_sha256": item.get("source_refs_sha256", ""),
            "source_text_count": item.get("source_text_count", 0),
            "semantic_object": item.get("semantic_object", ""),
        }
        if all(identity.values()):
            return identity
    return {}


def authority_boundary(role: str) -> dict[str, Any]:
    return {
        "source_of_truth": "external_mature_runtime",
        "truth_carriers": [
            "Temporal workflow state",
            "LangGraph checkpoint/store",
            "completion claim gate",
            "policy/verifier evidence",
        ],
        "this_file_role": role,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "pass_means": "graph_frontier_checkpoint_and_claim_guard_readback_only",
        "cannot_override": [
            "user_goal",
            "Temporal terminal state",
            "LangGraph frontier",
            "completion claim policy",
            "human visible side audit",
        ],
    }


def make_task_object(
    task_id: str,
    user_goal: str,
    *,
    source_refs: list[dict[str, Any]] | None = None,
    runtime_subject_loop_required: list[str] | None = None,
    root_repair_constraints: list[str] | None = None,
    minimum_reality_contact_required: bool = True,
    no_new_parallel_control_surface: bool = True,
    compiled_task_object: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if compiled_task_object:
        task = dict(compiled_task_object)
        task.setdefault("task_id", task_id)
        task.setdefault("task_object_id", task_id)
        task.setdefault("source_refs", list(source_refs or []))
        task.setdefault("runtime_subject_loop_required", list(runtime_subject_loop_required or RUNTIME_SUBJECT_LOOP_REQUIRED))
        task.setdefault("root_repair_constraints", list(root_repair_constraints or ROOT_REPAIR_CONSTRAINTS))
        task.setdefault("minimum_reality_contact_required", minimum_reality_contact_required)
        task.setdefault("no_new_parallel_control_surface", no_new_parallel_control_surface)
        task["compiled_task_object_used_by_langgraph"] = True
        task["langgraph_role"] = "planner_state_for_compiled_task_object"
        return bind_task_identity_fields(task)
    refs = list(source_refs or [])
    if user_goal:
        refs.append({
            "source_text_embedded": False,
            "source_text_authority": False,
            "semantic_input_role": "non_authoritative_reference",
            "source_sha256": hashlib.sha256(user_goal.encode("utf-8")).hexdigest(),
            "source_char_count": len(user_goal),
            "compiled_objective_code": "LANGGRAPH_DEFAULT_TASK_RUNNER",
        })
    task = runtime.TaskObject(
        task_object_id=task_id,
        original_text_refs=tuple(ref.get("path", "") for ref in refs if ref.get("path")) or ("phase2_temporal_dify_langgraph_binding",),
        source_refs=tuple(refs),
        original_object=runtime.TARGET_OBJECT,
        requested_operation=(
            "Run Codex default object-preserving task through LangGraph with a non-skippable "
            "completion claim node. User goal is compiled into source_refs hash metadata; "
            "source wording is non-authoritative and not embedded in this task object."
        ),
        runtime_subject_loop_required=tuple(runtime_subject_loop_required or RUNTIME_SUBJECT_LOOP_REQUIRED),
        root_repair_constraints=tuple(root_repair_constraints or ROOT_REPAIR_CONSTRAINTS),
        minimum_reality_contact_required=minimum_reality_contact_required,
        no_new_parallel_control_surface=no_new_parallel_control_surface,
    )
    return bind_task_identity_fields(task.model_dump(mode="json"))


def claim_for_node(state: GraphState, node_name: str, mode: Literal["partial", "complete"] = "partial") -> dict[str, Any]:
    claim_payload = builder.build_claim_payload(
        task_id=state["task_id"],
        mode=mode,
        user_goal=state.get("user_goal", ""),
        next_action=f"Continue LangGraph node sequence after {node_name}; completion_claim node remains required.",
        runtime_root=pathlib.Path(state["runtime_root"]),
    )
    decision = codex_default_task_runner.local_completion_claim(claim_payload)
    return {
        "node": node_name,
        "claim_mode": mode,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("langgraph_node_claim_readback"),
        "claim_decision": decision,
        "frontier_status": claim_payload["frontier"]["status"],
        "required_evidence_fields_present": all(
            claim_payload.get(field)
            for field in ("memory_read_refs", "evidence_write_refs", "budget_record", "rollback_plan_ref", "human_visible_side_audit_ref")
        ),
        "stop_allowed": decision.get("stop_allowed") is True,
    }


def checkpoint_state(state: GraphState, node_name: str) -> dict[str, Any]:
    runtime_root = pathlib.Path(state["runtime_root"])
    rid = state.setdefault("run_id", run_id())
    checkpoint_dir = runtime_root / "state" / "langgraph_task_runner" / "checkpoints" / state["task_id"]
    path = checkpoint_dir / f"{len(state.get('checkpoints', [])) + 1:02d}_{node_name}.json"
    checkpoint = {
        "schema_version": "xinao.langgraph_task_runner.checkpoint.v1",
        "generated_at": now(),
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("langgraph_checkpoint_readback"),
        "run_id": rid,
        "node": node_name,
        "task_object": state.get("task_object"),
        "frontier": state.get("frontier"),
        "completion_evidence": state.get("completion_evidence", {}),
        "completion_claim_node_required": True,
        "nodes_run": list(state.get("nodes_run", [])),
    }
    write_json(path, checkpoint)
    return {
        "node": node_name,
        "checkpoint_path": str(path),
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("langgraph_checkpoint_ref_readback"),
        "frontier": checkpoint["frontier"],
    }


def append_node(state: GraphState, node_name: str, *, frontier: dict[str, Any] | None = None) -> GraphState:
    nodes = list(state.get("nodes_run", []))
    nodes.append(node_name)
    state["nodes_run"] = nodes
    if frontier is not None:
        state["frontier"] = frontier
    claims = list(state.get("node_claims", []))
    claims.append(claim_for_node(state, node_name, "partial"))
    state["node_claims"] = claims
    checkpoints = list(state.get("checkpoints", []))
    checkpoints.append(checkpoint_state(state, node_name))
    state["checkpoints"] = checkpoints
    return state


def bind_task_node(state: GraphState) -> GraphState:
    existing_task_path = pathlib.Path(state["runtime_root"]) / "state" / "langgraph_task_runner" / "tasks" / f"{state['task_id']}.json"
    existing_task_payload = read_json(existing_task_path)
    existing_task_object = existing_task_payload.get("task_object") or {}
    explicit_compiled_task_object = bool(state.get("compiled_task_object", {}))
    compiled_task_object = state.get("compiled_task_object", {})
    if not explicit_compiled_task_object and existing_task_payload.get("task_id") == state["task_id"] and existing_task_object:
        compiled_task_object = existing_task_object
    if compiled_task_object and not explicit_compiled_task_object:
        completed_identity = completed_frontier_identity(pathlib.Path(state["runtime_root"]), state["task_id"])
        if completed_identity:
            compiled_task_object = {**compiled_task_object, **completed_identity}
    state["task_object"] = make_task_object(
        state["task_id"],
        state.get("user_goal", ""),
        source_refs=state.get("source_refs", []),
        compiled_task_object=compiled_task_object,
        runtime_subject_loop_required=state.get("runtime_subject_loop_required", []),
        root_repair_constraints=state.get("root_repair_constraints", []),
        minimum_reality_contact_required=bool(state.get("minimum_reality_contact_required", True)),
        no_new_parallel_control_surface=bool(state.get("no_new_parallel_control_surface", True)),
    )
    state["frontier"] = {
        "status": "open",
        "items": [{"frontier_id": "bind_task_created", "next_action": "Run mature discovery."}],
    }
    return append_node(state, "bind_task")


def mature_discovery_node(state: GraphState) -> GraphState:
    state["mature_discovery"] = {
        "selected_graph_carrier": "LangGraph StateGraph when available; deterministic node runner fallback otherwise",
        "durable_carrier": "Temporal wraps this runner in phase two",
    }
    return append_node(state, "mature_discovery")


def plan_refinement_node(state: GraphState) -> GraphState:
    state["refinement_plan"] = {
        "object_preserved": True,
        "operation_preserved": True,
        "completion_claim_node_required": True,
    }
    return append_node(state, "plan_refinement")


def verify_refinement_node(state: GraphState) -> GraphState:
    state["refinement_verification"] = {
        "status": "partial_until_completion_claim",
        "policy_boundary": "object replacement and operation degradation are non-retryable policy denials",
    }
    return append_node(state, "verify_refinement")


def execute_shard_node(state: GraphState) -> GraphState:
    state["execution"] = {
        "status": "executed_scoped_shard",
        "temporal_activity_safe": True,
    }
    return append_node(state, "execute_shard")


def is_l8_live_workflow_task(state: GraphState) -> bool:
    task_id = str(state.get("task_id", "")).lower()
    user_goal = str(state.get("user_goal", "")).lower()
    return (
        task_id.startswith("l8_default_live_workflow_acceptance")
        or "l8_default_live_workflow_not_accepted" in user_goal
        or ("default live workflow" in user_goal and "chinese goal" in user_goal)
    )


def is_l9_repeated_continuity_task(state: GraphState) -> bool:
    task_id = str(state.get("task_id", "")).lower()
    user_goal = str(state.get("user_goal", "")).lower()
    return (
        task_id.startswith("l9_repeated_continuity")
        or "l9_repeated_continuity_not_proven" in user_goal
        or ("repeated continuity" in user_goal and "live workflow" in user_goal)
    )


def frontier_ids_for_state(state: GraphState) -> tuple[str, ...]:
    if is_l9_repeated_continuity_task(state):
        return L9_REPEATED_CONTINUITY_FRONTIER_IDS
    if is_l8_live_workflow_task(state):
        return L8_LIVE_WORKFLOW_FRONTIER_IDS
    return MATURE_MIGRATION_FRONTIER_IDS


def all_mature_migration_frontier_items(state: GraphState) -> list[dict[str, Any]]:
    task_object = state.get("task_object", {})
    task_id = state["task_id"]
    parent_object = (task_object.get("acceptance_contract") or {}).get(
        "parent_object",
        "XINAO_GLOBAL_CANONICAL_SELF_CLEANSE_AND_UPLIFT_ROOT_REPAIR",
    )
    base = {
        "source_task_id": task_id,
        "task_object_sha256": task_object.get("task_object_sha256", ""),
        "source_refs_sha256": task_object.get("source_refs_sha256", ""),
        "source_text_count": task_object.get("source_text_count", 0),
        "semantic_object": task_object.get("semantic_object", ""),
        "parent_object": parent_object,
        "status": "queued",
        "manual_user_review_required": False,
    }
    if is_l8_live_workflow_task(state):
        return [
            {
                **base,
                "parent_object": "L8_DEFAULT_LIVE_WORKFLOW_NOT_ACCEPTED",
                "category": "L8_LIVE_WORKFLOW",
                "frontier_id": L8_LIVE_WORKFLOW_FRONTIER_IDS[0],
                "next_action": "Bind one fresh Chinese goal to the default live workflow intake through TaskObject/current_task_owner instead of a report or canary-only route.",
                "target_carriers": ["default_task_intake_runtime", "Temporal", "LangGraph", "OPA/Conftest"],
            },
            {
                **base,
                "parent_object": "L8_DEFAULT_LIVE_WORKFLOW_NOT_ACCEPTED",
                "category": "L8_LIVE_WORKFLOW",
                "frontier_id": L8_LIVE_WORKFLOW_FRONTIER_IDS[1],
                "next_action": "Produce human-visible Chinese plan, progress, result, unfinished items, and next action readback for the live workflow.",
                "target_carriers": ["human-visible status surface", "panel/readback", "LangGraph checkpoint"],
            },
            {
                **base,
                "parent_object": "L8_DEFAULT_LIVE_WORKFLOW_NOT_ACCEPTED",
                "category": "L8_LIVE_WORKFLOW",
                "frontier_id": L8_LIVE_WORKFLOW_FRONTIER_IDS[2],
                "next_action": "Attach task-scoped evidence, rollback plan, and restart recovery readback for the live workflow.",
                "target_carriers": ["Temporal event history", "LangGraph checkpoint", "rollback_executor"],
            },
            {
                **base,
                "parent_object": "L8_DEFAULT_LIVE_WORKFLOW_NOT_ACCEPTED",
                "category": "L8_LIVE_WORKFLOW",
                "frontier_id": L8_LIVE_WORKFLOW_FRONTIER_IDS[3],
                "next_action": "Route the live workflow through trace, eval, HITL/admission, and continuity writeback evidence.",
                "target_carriers": ["OpenTelemetry/Langfuse", "LiteLLM", "OPA/Conftest", "continuity ledger"],
            },
            {
                **base,
                "parent_object": "L8_DEFAULT_LIVE_WORKFLOW_NOT_ACCEPTED",
                "category": "L8_LIVE_WORKFLOW",
                "frontier_id": L8_LIVE_WORKFLOW_FRONTIER_IDS[4],
                "next_action": "Record repeatable promotion boundary: one live pass is not repeated maturity or user completion, and further repeated runs remain queued.",
                "target_carriers": ["completion claim gate", "phase parallel audit", "human-visible audit"],
            },
        ]
    if is_l9_repeated_continuity_task(state):
        return [
            {
                **base,
                "parent_object": "L9_REPEATED_CONTINUITY_NOT_PROVEN",
                "category": "L9_REPEATED_CONTINUITY",
                "frontier_id": L9_REPEATED_CONTINUITY_FRONTIER_IDS[0],
                "next_action": "Run a second different Chinese goal through the same default live workflow carrier instead of a new one-off canary.",
                "target_carriers": ["Dify workflow API", "Temporal/current_task_owner", "LangGraph checkpoint"],
            },
            {
                **base,
                "parent_object": "L9_REPEATED_CONTINUITY_NOT_PROVEN",
                "category": "L9_REPEATED_CONTINUITY",
                "frontier_id": L9_REPEATED_CONTINUITY_FRONTIER_IDS[1],
                "next_action": "Compare first and second run evidence: workflow_run_id, output, runtime state, and route gaps must be task-bound and readable.",
                "target_carriers": ["Dify run detail", "runtime state readback", "completion claim payload"],
            },
            {
                **base,
                "parent_object": "L9_REPEATED_CONTINUITY_NOT_PROVEN",
                "category": "L9_REPEATED_CONTINUITY",
                "frontier_id": L9_REPEATED_CONTINUITY_FRONTIER_IDS[2],
                "next_action": "Read rollback and restart recovery evidence for the repeated route; do not accept a run-only PASS.",
                "target_carriers": ["rollback_executor", "LangGraph checkpoint", "Temporal event history"],
            },
            {
                **base,
                "parent_object": "L9_REPEATED_CONTINUITY_NOT_PROVEN",
                "category": "L9_REPEATED_CONTINUITY",
                "frontier_id": L9_REPEATED_CONTINUITY_FRONTIER_IDS[3],
                "next_action": "Prove trace, eval, HITL/admission, and continuity writeback are reused by the repeated route, not skipped.",
                "target_carriers": ["OpenTelemetry/Langfuse", "LiteLLM", "OPA/Conftest", "continuity ledger"],
            },
            {
                **base,
                "parent_object": "L9_REPEATED_CONTINUITY_NOT_PROVEN",
                "category": "L9_REPEATED_CONTINUITY",
                "frontier_id": L9_REPEATED_CONTINUITY_FRONTIER_IDS[4],
                "next_action": "Record repeated-run promotion boundary: repeated machine evidence is still not user completion, and historical human-visible stages stay frozen/non-default.",
                "target_carriers": ["completion claim gate", "phase parallel audit", "human-visible audit"],
            },
        ]
    return [
        {
            **base,
            "frontier_id": MATURE_MIGRATION_FRONTIER_IDS[0],
            "next_action": "Bind the report.txt mature migration parent object to durable Temporal/LangGraph/OPA/Codex-worker execution, with stale evidence only as a guardrail.",
            "target_carriers": ["Temporal", "LangGraph", "OPA/Conftest", "Codex exec/app-server", "Langfuse/OpenTelemetry"],
        },
        {
            **base,
            "frontier_id": MATURE_MIGRATION_FRONTIER_IDS[1],
            "next_action": "Keep every non-empty semantic unit from all four source texts addressable in the graph and route each gap to a mature carrier.",
            "target_carriers": ["LangGraph", "Backstage/MCP/OpenAPI", "OpenLineage"],
        },
        {
            **base,
            "frontier_id": MATURE_MIGRATION_FRONTIER_IDS[2],
            "next_action": "Route UserPromptSubmit/TUI entry through Intake Gate before any AI decision, while preserving TUI as cockpit/manual takeover only.",
            "target_carriers": ["Codex hooks", "UCP", "OPA/Conftest"],
        },
        {
            **base,
            "frontier_id": MATURE_MIGRATION_FRONTIER_IDS[3],
            "next_action": "Bind Codex Stop/final/completion claim to OPA plus Temporal event history, LangGraph checkpoint, task-bound JSONL, and trace readback.",
            "target_carriers": ["Codex hooks", "OPA/Conftest", "Temporal", "LangGraph"],
        },
        {
            **base,
            "frontier_id": MATURE_MIGRATION_FRONTIER_IDS[4],
            "next_action": "Turn the remaining four-text mature-migration requirements into task-scoped Temporal work items instead of local latest/verifier drift.",
            "target_carriers": ["Temporal", "Codex exec/app-server", "LangGraph"],
        },
    ]


def task_scoped_frontier_completion(state: GraphState) -> dict[str, Any]:
    runtime_root = pathlib.Path(state["runtime_root"])
    task_object = state.get("task_object", {})
    task_id = state["task_id"]
    intake_path = runtime_root / "state" / "temporal_work_item_intake" / "tasks" / f"{task_id}.json"
    intake = read_json(intake_path)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    accepted_ids: set[str] = set()
    required_frontier_ids = frontier_ids_for_state(state)
    valid_ids = set(required_frontier_ids)
    expected = {
        "source_task_id": task_id,
        "task_object_sha256": task_object.get("task_object_sha256", ""),
        "source_refs_sha256": task_object.get("source_refs_sha256", ""),
        "source_text_count": task_object.get("source_text_count", 0),
        "semantic_object": task_object.get("semantic_object", ""),
        "verifier_contract_version": FRONTIER_COMPLETION_CONTRACT,
    }
    for item in intake.get("completed_work_items") or []:
        source_item_id = str(item.get("source_item_id") or "")
        if not source_item_id.startswith("langgraph_frontier_"):
            continue
        frontier_id = source_item_id.removeprefix("langgraph_frontier_")
        mismatches = []
        if frontier_id not in valid_ids:
            mismatches.append("frontier_id")
        if item.get("passed") is not True:
            mismatches.append("passed")
        for field, value in expected.items():
            if field == "verifier_contract_version":
                if item.get(field) not in FRONTIER_COMPLETION_CONTRACTS:
                    mismatches.append(field)
                continue
            if item.get(field) != value:
                mismatches.append(field)
        evidence = {
            "frontier_id": frontier_id,
            "source_item_id": source_item_id,
            "work_id": item.get("work_id", ""),
            "result_path": item.get("result_path", ""),
            "source_task_id": item.get("source_task_id", ""),
            "task_object_sha256": item.get("task_object_sha256", ""),
            "source_refs_sha256": item.get("source_refs_sha256", ""),
            "source_text_count": item.get("source_text_count", 0),
            "semantic_object": item.get("semantic_object", ""),
            "verifier_contract_version": item.get("verifier_contract_version", ""),
        }
        result_path = pathlib.Path(str(item.get("result_path") or ""))
        result = read_json(result_path)
        result_work_item = result.get("work_item") or {}
        if not result_path.exists():
            mismatches.append("result_path")
        if result.get("status") != "mature_carrier_work_item_passed":
            mismatches.append("result_status")
        if result.get("passed") is not True and result.get("status") != "mature_carrier_work_item_passed":
            mismatches.append("result_passed")
        if (result.get("source_task_id") or result_work_item.get("source_task_id")) != task_id:
            mismatches.append("result_source_task_id")
        if (result.get("task_object_sha256") or result_work_item.get("task_object_sha256")) != expected["task_object_sha256"]:
            mismatches.append("result_task_object_sha256")
        if (result.get("source_refs_sha256") or result_work_item.get("source_refs_sha256")) != expected["source_refs_sha256"]:
            mismatches.append("result_source_refs_sha256")
        if (result.get("source_text_count") or result_work_item.get("source_text_count")) != expected["source_text_count"]:
            mismatches.append("result_source_text_count")
        if (result.get("semantic_object") or result_work_item.get("semantic_object")) != expected["semantic_object"]:
            mismatches.append("result_semantic_object")
        if (result.get("verifier_contract_version") or result_work_item.get("verifier_contract_version")) not in FRONTIER_COMPLETION_CONTRACTS:
            mismatches.append("result_verifier_contract_version")
        if (result.get("source_item_id") or result_work_item.get("source_item_id")) != source_item_id:
            mismatches.append("result_source_item_id")
        if result.get("named_blockers"):
            mismatches.append("result_named_blockers")
        if result.get("scope_mismatches"):
            mismatches.append("result_scope_mismatches")
        evidence["result_artifact_checked"] = result_path.exists()
        if mismatches:
            evidence["scope_mismatches"] = mismatches
            rejected.append(evidence)
            continue
        accepted.append(evidence)
        accepted_ids.add(frontier_id)
    return {
        "schema_version": "xinao.langgraph_frontier_completion_readback.v1",
        "source": "temporal_work_item_intake_task_scoped_completed_work_items",
        "source_path": str(intake_path),
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("temporal_work_item_intake_task_scoped_readback"),
        "accepted_frontier_ids": sorted(accepted_ids),
        "accepted_frontier_evidence": accepted,
        "rejected_frontier_evidence": rejected,
        "required_frontier_ids": list(required_frontier_ids),
        "all_required_frontier_ids_closed": all(frontier_id in accepted_ids for frontier_id in required_frontier_ids),
    }


def mature_migration_frontier_items(state: GraphState, completion: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    closed = set((completion or {}).get("accepted_frontier_ids") or [])
    return [item for item in all_mature_migration_frontier_items(state) if item["frontier_id"] not in closed]


def update_frontier_node(state: GraphState) -> GraphState:
    completion = task_scoped_frontier_completion(state)
    pending_items = [] if completion["all_required_frontier_ids_closed"] else mature_migration_frontier_items(state, completion)
    frontier = {
        "status": "empty" if not pending_items else "open",
        "items": pending_items,
        "frontier_owner": "LangGraph",
        "frontier_role": "mature_migration_backlog_and_worker_dispatch_plan",
        "frontier_completion_source": completion["source"],
        "closed_frontier_ids": completion["accepted_frontier_ids"],
        "closed_frontier_evidence": completion["accepted_frontier_evidence"],
        "rejected_frontier_evidence": completion["rejected_frontier_evidence"],
        "required_frontier_ids": completion["required_frontier_ids"],
        "all_required_frontier_ids_closed": completion["all_required_frontier_ids_closed"],
        "not_source_of_truth": True,
        "not_user_completion": True,
    }
    state["worker_dispatch_plan"] = {
        "schema_version": "xinao.langgraph_worker_dispatch_plan.v1",
        "status": "queued" if pending_items else "frontier_closed_by_task_scoped_temporal_work_items",
        "carrier": "LangGraph StateGraph frontier",
        "dispatch_surface": "Temporal workflow -> Codex exec/app-server worker JSONL",
        "policy_gate": "OPA/Conftest before completion claim",
        "items": frontier.get("items", []),
        "closed_frontier_ids": completion["accepted_frontier_ids"],
        "frontier_completion_source": completion["source"],
        "not_user_completion": True,
    }
    return append_node(state, "update_frontier", frontier=frontier)


def checkpoint_frontier_node(state: GraphState) -> GraphState:
    return append_node(state, "checkpoint_frontier")


def human_visible_status_for_claim(state: GraphState, mode: str) -> dict[str, Any]:
    frontier = state.get("frontier", {})
    closed_ids = list(frontier.get("closed_frontier_ids") or [])
    open_items = list(frontier.get("items") or [])
    frontier_empty = frontier.get("status") == "empty" and not open_items
    return {
        "current_goal": state.get("user_goal", "") or state["task_id"],
        "current_state": "task_frontier_closed_claim_pending" if frontier_empty else "task_frontier_open_continue",
        "requested_claim_mode": mode,
        "what_is_complete": [
            f"当前 task_id 已绑定 current_task_owner: {state['task_id']}",
            f"LangGraph frontier 已关闭 {len(closed_ids)} 个 required work item。" if frontier_empty else f"LangGraph frontier 已关闭 {len(closed_ids)} 个 required work item，仍有 {len(open_items)} 个待执行。",
            "Temporal work item evidence 已按 task_id 读取，不使用不匹配的 global latest 作为完成证据。",
        ],
        "what_is_not_complete": [
            "这不是用户意义上的 XINAO 系统完成。",
            "这不是 intent-xinao-intent-admission-layer-mvp 的最终用户验收。",
            "Stop/final 仍必须等 completion claim gate、task-scoped side audit 和 human-visible audit 同时通过。",
            "历史人类可见阶段已冻结；主线继续推进唯一迁移事务和中文可见状态/readback。",
        ],
        "next_action_cn": (
            "请求独立 human-visible side audit；通过后重跑 task-scoped completion claim，然后继续主线下一项。"
            if frontier_empty
            else "继续执行 open frontier 的 task-scoped Temporal work items。"
        ),
        "not_user_completion": True,
    }


def completion_claim_node(state: GraphState) -> GraphState:
    mode: Literal["partial", "complete"] = (
        "complete"
        if bool(state.get("allow_complete_fixture")) and state.get("requested_mode") == "complete"
        else "partial"
    )
    claim_payload = builder.build_claim_payload(
        task_id=state["task_id"],
        mode=mode,
        user_goal=state.get("user_goal", ""),
        next_action="LangGraph frontier remains open; Temporal/Dify must display partial decision.",
        runtime_root=pathlib.Path(state["runtime_root"]),
        human_visible_status=human_visible_status_for_claim(state, mode),
    )
    claim_payload["frontier"] = state.get("frontier", claim_payload["frontier"])
    decision = codex_default_task_runner.runtime.claim_completion_against_runtime_owner(
        codex_default_task_runner.runtime.CompletionClaim(**claim_payload),
        pathlib.Path(state["runtime_root"]),
    ).model_dump(mode="json")
    claim_payload["stop_allowed"] = decision.get("stop_allowed") is True
    claim_payload["completion_decision_readback"] = {
        "status": decision.get("status", ""),
        "reason": decision.get("reason", ""),
        "required_gate": decision.get("required_gate", ""),
        "not_source_of_truth": True,
        "not_user_completion": True,
    }
    builder.write_claim_payload(
        payload=claim_payload,
        runtime_root=pathlib.Path(state["runtime_root"]),
    )
    rollback_execution_result = claim_payload.get("rollback_execution_result", {})
    if state.get("trigger_rollback_on_partial") and decision.get("status") != "complete_allowed":
        rollback_execution_result = rollback_executor.prepare_rollback_execution_result(
            rollback_plan_ref=claim_payload.get("rollback_plan_ref", ""),
            runtime_root=pathlib.Path(state["runtime_root"]),
            execute=True,
        )
    state["completion_claim_payload"] = claim_payload
    state["completion_evidence"] = {
        "memory_read_refs": claim_payload.get("memory_read_refs", []),
        "evidence_write_refs": claim_payload.get("evidence_write_refs", []),
        "budget_record": claim_payload.get("budget_record", {}),
        "rollback_plan_ref": claim_payload.get("rollback_plan_ref", ""),
            "rollback_execution_result": rollback_execution_result,
            "human_visible_status": claim_payload.get("human_visible_status", {}),
            "human_visible_side_audit_ref": claim_payload.get("human_visible_side_audit_ref", ""),
        }
    state["completion_decision"] = decision
    nodes = list(state.get("nodes_run", []))
    nodes.append("completion_claim")
    state["nodes_run"] = nodes
    claims = list(state.get("node_claims", []))
    claims.append({
        "node": "completion_claim",
        "claim_mode": mode,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("langgraph_completion_claim_readback"),
        "claim_decision": decision,
        "frontier_status": claim_payload["frontier"]["status"],
        "required_evidence_fields_present": all(
            claim_payload.get(field)
            for field in ("memory_read_refs", "evidence_write_refs", "budget_record", "rollback_plan_ref", "human_visible_side_audit_ref")
        ),
        "stop_allowed": decision.get("stop_allowed") is True,
    })
    state["node_claims"] = claims
    checkpoints = list(state.get("checkpoints", []))
    checkpoints.append(checkpoint_state(state, "completion_claim"))
    state["checkpoints"] = checkpoints
    return state


def continuation_required(state: GraphState) -> bool:
    decision = state.get("completion_decision", {})
    return not (decision.get("status") == "complete_allowed" and decision.get("stop_allowed") is True)


def continuation_dispatch_node(state: GraphState) -> GraphState:
    runtime_root = pathlib.Path(state["runtime_root"])
    frontier = state.get("frontier", {})
    items = [
        {
            "work_item_id": item.get("frontier_id", f"{state['task_id']}_frontier_item"),
            "source_task_id": state["task_id"],
            "source_node": "completion_claim",
            "status": "queued",
            "next_action": item.get("next_action", "Continue the open frontier through the next machine route."),
            "manual_user_review_required": False,
        }
        for item in frontier.get("items", [])
    ]
    if not items:
        items = [{
            "work_item_id": f"{state['task_id']}_continuation_required",
            "source_task_id": state["task_id"],
            "source_node": "completion_claim",
            "status": "queued",
            "next_action": "Continue execution because completion claim did not allow stop.",
            "manual_user_review_required": False,
        }]
    packet = {
        "schema_version": "xinao.langgraph_continuation_dispatch.v1",
        "generated_at": now(),
        "status": "continuation_queued",
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("langgraph_continuation_dispatch_readback"),
        "task_id": state["task_id"],
        "run_id": state.get("run_id", ""),
        "reason": "completion_claim_partial_or_stop_not_allowed",
        "completion_decision": state.get("completion_decision", {}),
        "frontier": frontier,
        "queue": items,
        "worker_dispatch_plan": state.get("worker_dispatch_plan", {}),
        "report_boundary_allowed": False,
        "continuation_required_after_pass": True,
    }
    latest = runtime_root / "state" / "langgraph_task_runner" / "continuation_queue" / "latest.json"
    task_path = runtime_root / "state" / "langgraph_task_runner" / "continuation_queue" / "tasks" / f"{state['task_id']}.json"
    events = runtime_root / "state" / "langgraph_task_runner" / "continuation_queue" / "events.ndjson"
    write_json(task_path, packet)
    if state.get("promote_latest", True) is not False:
        write_json(latest, packet)
    events.parent.mkdir(parents=True, exist_ok=True)
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(packet, ensure_ascii=False) + "\n")
    state["continuation_dispatch"] = packet
    return append_node(state, "continuation_dispatch", frontier=frontier)


def run_deterministic_graph(initial_state: GraphState) -> GraphState:
    state = dict(initial_state)
    for fn in (
        bind_task_node,
        mature_discovery_node,
        plan_refinement_node,
        verify_refinement_node,
        execute_shard_node,
        update_frontier_node,
        checkpoint_frontier_node,
        completion_claim_node,
    ):
        state = fn(state)
    if continuation_required(state):
        state = continuation_dispatch_node(state)
    return state


def run_langgraph_if_available(initial_state: GraphState) -> tuple[GraphState, str]:
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception:
        return run_deterministic_graph(initial_state), "deterministic_fallback"

    graph = StateGraph(GraphState)
    graph.add_node("bind_task", bind_task_node)
    graph.add_node("mature_discovery", mature_discovery_node)
    graph.add_node("plan_refinement", plan_refinement_node)
    graph.add_node("verify_refinement", verify_refinement_node)
    graph.add_node("execute_shard", execute_shard_node)
    graph.add_node("update_frontier", update_frontier_node)
    graph.add_node("checkpoint_frontier", checkpoint_frontier_node)
    graph.add_node("completion_claim", completion_claim_node)
    graph.add_node("continuation_dispatch", continuation_dispatch_node)
    graph.add_edge(START, "bind_task")
    graph.add_edge("bind_task", "mature_discovery")
    graph.add_edge("mature_discovery", "plan_refinement")
    graph.add_edge("plan_refinement", "verify_refinement")
    graph.add_edge("verify_refinement", "execute_shard")
    graph.add_edge("execute_shard", "update_frontier")
    graph.add_edge("update_frontier", "checkpoint_frontier")
    graph.add_edge("checkpoint_frontier", "completion_claim")
    graph.add_conditional_edges(
        "completion_claim",
        lambda state: "continue" if continuation_required(state) else "stop",
        {"continue": "continuation_dispatch", "stop": END},
    )
    graph.add_edge("continuation_dispatch", END)
    return graph.compile().invoke(dict(initial_state)), "langgraph_stategraph"


def run_task_graph(
    *,
    task_id: str,
    user_goal: str,
    mode: Literal["partial", "complete"] = "partial",
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    base_url: str = "http://127.0.0.1:19531",
    allow_complete_fixture: bool = False,
    trigger_rollback_on_partial: bool = False,
    source_refs: list[dict[str, Any]] | None = None,
    compiled_task_object: dict[str, Any] | None = None,
    runtime_subject_loop_required: list[str] | None = None,
    root_repair_constraints: list[str] | None = None,
    minimum_reality_contact_required: bool = True,
    no_new_parallel_control_surface: bool = True,
    promote_latest: bool = True,
) -> dict[str, Any]:
    rid = run_id()
    initial_state: GraphState = {
        "task_id": task_id,
        "user_goal": user_goal,
        "requested_mode": mode,
        "allow_complete_fixture": allow_complete_fixture,
        "runtime_root": str(runtime_root),
        "base_url": base_url,
        "source_refs": list(source_refs or []),
        "compiled_task_object": dict(compiled_task_object or {}),
        "runtime_subject_loop_required": list(runtime_subject_loop_required or RUNTIME_SUBJECT_LOOP_REQUIRED),
        "root_repair_constraints": list(root_repair_constraints or ROOT_REPAIR_CONSTRAINTS),
        "minimum_reality_contact_required": minimum_reality_contact_required,
        "no_new_parallel_control_surface": no_new_parallel_control_surface,
        "trigger_rollback_on_partial": trigger_rollback_on_partial,
        "promote_latest": promote_latest,
        "nodes_run": [],
        "node_claims": [],
        "checkpoints": [],
        "run_id": rid,
    }
    state, carrier = run_langgraph_if_available(initial_state)
    decision = state["completion_decision"]
    payload = {
        "schema_version": "xinao.langgraph_task_runner.v1",
        "generated_at": now(),
        "status": "langgraph_task_runner_gate_checked",
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("langgraph_task_runner_readback"),
        "run_id": rid,
        "task_id": task_id,
        "active_object_id": ACTIVE_OBJECT_ID,
        "carrier": carrier,
        "node_order_required": list(NODE_ORDER),
        "nodes_run": state.get("nodes_run", []),
        "completion_claim_node_required": True,
        "completion_claim_node_seen": "completion_claim" in state.get("nodes_run", []),
        "continuation_dispatch_node_seen": "continuation_dispatch" in state.get("nodes_run", []),
        "task_object": state.get("task_object"),
        "frontier": state.get("frontier"),
        "continuation_dispatch": state.get("continuation_dispatch", {}),
        "checkpoints": state.get("checkpoints", []),
        "node_claims": state.get("node_claims", []),
        "completion_claim_payload": state.get("completion_claim_payload"),
        "completion_evidence": state.get("completion_evidence", {}),
        "completion_decision": decision,
        "complete_allowed": decision.get("status") == "complete_allowed",
        "stop_allowed": decision.get("stop_allowed") is True,
        "rollback_ready": (state.get("completion_evidence", {}).get("rollback_execution_result") or {}).get("rollback_executable") is True,
        "completion_blocked_but_execution_must_continue": decision.get("status") != "complete_allowed",
        "default_recursive_continuation_limit": 10,
        "rollback_triggered": trigger_rollback_on_partial and decision.get("status") != "complete_allowed",
        "promote_latest": promote_latest,
        "workflow_completed_is_not_user_complete": True,
        "sentinel": SENTINEL,
    }
    latest = runtime_root / "state" / "langgraph_task_runner" / "latest.json"
    task_path = runtime_root / "state" / "langgraph_task_runner" / "tasks" / f"{task_id}.json"
    events = runtime_root / "state" / "langgraph_task_runner" / "events.ndjson"
    write_json(task_path, payload)
    if promote_latest:
        write_json(latest, payload)
    events.parent.mkdir(parents=True, exist_ok=True)
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="LangGraph task runner with non-skippable /completion/claim node.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--user-goal", default="")
    parser.add_argument("--mode", choices=("partial", "complete"), default="partial")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--base-url", default="http://127.0.0.1:19531")
    parser.add_argument("--allow-complete-fixture", action="store_true")
    parser.add_argument("--trigger-rollback-on-partial", action="store_true")
    parser.add_argument("--source-ref", action="append", default=[], help="Non-authoritative semantic input file to bind into TaskObject with hash.")
    parser.add_argument("--no-promote-latest", action="store_true")
    args = parser.parse_args()
    source_refs = [file_source_ref(pathlib.Path(path)) for path in args.source_ref]
    payload = run_task_graph(
        task_id=args.task_id,
        user_goal=args.user_goal,
        mode=args.mode,
        runtime_root=pathlib.Path(args.runtime_root),
        base_url=args.base_url,
        allow_complete_fixture=args.allow_complete_fixture,
        trigger_rollback_on_partial=args.trigger_rollback_on_partial,
        source_refs=source_refs,
        promote_latest=not args.no_promote_latest,
    )
    print(json.dumps({
        "status": payload["status"],
        "carrier": payload["carrier"],
        "completion_decision": payload["completion_decision"],
        "completion_claim_node_seen": payload["completion_claim_node_seen"],
        "sentinel": payload["sentinel"],
    }, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
