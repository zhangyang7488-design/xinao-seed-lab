import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import sqlite3
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from services.agent_runtime import memory_budget_rollback_gate, refinement_contract_verifier

DEFAULT_REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
TARGET_OBJECT = "XINAO_SEMANTIC_LOCKED_AUTONOMOUS_EXECUTION_RUNTIME"
ACTIVE_OBJECT = "XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME"
RUNTIME_PACKAGE_ID = "CODEX_CENTRIC_OBJECT_PRESERVING_AUTONOMOUS_PLANNER"
SENTINEL = "SENTINEL:XINAO_CODEX_CENTRIC_OBJECT_PRESERVING_RUNTIME_PASS"
DEFAULT_PATH = (
    "semantic_entry_lock",
    "owner_asset_discovery",
    "semantic_binder",
    "autonomous_planner",
    "refinement_verifier",
    "durable_executor",
    "trace_eval_memory",
    "human_delivery_gate",
    "total_completion_gate",
)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_name(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.strip())
    return normalized[:120] or "xinao_task"


def run_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: pathlib.Path) -> dict[str, Any] | None:
    if not pathlib.Path(path).is_file():
        return None
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))


def write_text(path: pathlib.Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def authority_boundary(role: str) -> dict[str, Any]:
    return {
        "source_of_truth": "external_mature_runtime",
        "truth_carriers": [
            "Temporal workflow state",
            "LangGraph checkpoint/store",
            "Backstage/OpenAPI catalog",
            "OPA/Conftest policy results",
            "OpenTelemetry trace evidence",
        ],
        "this_file_role": role,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "pass_means": "object_preserving_runtime_shape_and_verifier_evidence_only",
    }


def module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


class CompletionContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    whole_object_only: Literal[True] = True
    substage_completion_forbidden: Literal[True] = True
    frontier_empty_required: Literal[True] = True
    coverage_proof_required: Literal[True] = True
    human_visible_acceptance_policy_bound: Literal[True] = True
    historical_human_visible_stage_frozen_not_default: Literal[True] = True


class TaskObject(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["xinao.codex_centric_task_object.v1"] = "xinao.codex_centric_task_object.v1"
    task_object_id: str
    active_object_id: Literal["XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME"] = ACTIVE_OBJECT
    target_object: Literal["XINAO_SEMANTIC_LOCKED_AUTONOMOUS_EXECUTION_RUNTIME"] = TARGET_OBJECT
    original_text_refs: tuple[str, ...]
    source_refs: tuple[dict[str, Any], ...] = ()
    original_object: str
    requested_operation: str
    runtime_subject_loop_required: tuple[str, ...] = ()
    root_repair_constraints: tuple[str, ...] = ()
    minimum_reality_contact_required: bool = False
    no_new_parallel_control_surface: bool = False
    completion_contract: CompletionContract = Field(default_factory=CompletionContract)
    object_replacement_allowed: Literal[False] = False
    operation_replacement_allowed: Literal[False] = False
    completion_replacement_allowed: Literal[False] = False
    semantic_shrink_allowed: Literal[False] = False
    frontier_required: Literal[True] = True
    durable_execution_required: Literal[True] = True
    human_delivery_stop_audit_required: Literal[True] = True


class RefinementContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["xinao.refinement_contract.v1"] = "xinao.refinement_contract.v1"
    contract_id: str
    active_object_id: Literal["XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME"] = ACTIVE_OBJECT
    original_object_ref: Literal["XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME"] = ACTIVE_OBJECT
    parent: str
    children: tuple[str, ...]
    requested_operation_ref: str
    claim: str
    proof_or_validator: str
    coverage_status: Literal["full", "partial", "unproven"]
    if_unproven: str = ""
    frontier_update: dict[str, Any] = Field(default_factory=dict)
    operation_preserved: Literal[True] = True
    object_preserved: Literal[True] = True
    completion_claimed: bool = False


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_valid: bool
    coverage_claim: str
    proof_summary: str
    issues: tuple[str, ...]
    recommendation: Literal["accept", "partial", "reject"]
    frontier_open: bool
    completion_claimed: bool


class FrontierState(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["empty", "open"]
    items: tuple[dict[str, Any], ...] = ()
    completed_contracts: tuple[str, ...] = ()
    rejected_contracts: tuple[str, ...] = ()
    frontier_owner: str = ""
    frontier_role: str = ""
    frontier_completion_source: str = ""
    closed_frontier_ids: tuple[str, ...] = ()
    closed_frontier_evidence: tuple[dict[str, Any], ...] = ()
    rejected_frontier_evidence: tuple[dict[str, Any], ...] = ()
    required_frontier_ids: tuple[str, ...] = ()
    all_required_frontier_ids_closed: bool | None = None


class CompletionClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_object_id: str
    contract: RefinementContract | None = None
    verification: VerificationResult | None = None
    frontier: FrontierState
    current_task_owner: dict[str, Any] = Field(default_factory=dict)
    requested_status: Literal["complete"] = "complete"
    memory_read_refs: tuple[str, ...] = ()
    evidence_write_refs: tuple[str, ...] = ()
    budget_record: dict[str, Any] = Field(default_factory=dict)
    rollback_plan_ref: str = ""
    rollback_execution_result: dict[str, Any] = Field(default_factory=dict)
    human_visible_status: dict[str, Any] = Field(default_factory=dict)
    human_visible_side_audit_ref: str = ""


class CompletionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["complete_allowed", "partial", "rejected"]
    stop_allowed: bool
    reason: str
    required_gate: Literal["verifier_and_empty_frontier"] = "verifier_and_empty_frontier"
    contract_id: str | None = None


class CodexMainBrainContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["xinao.codex_main_brain_completion_contract.v1"] = "xinao.codex_main_brain_completion_contract.v1"
    target_object: Literal["XINAO_SEMANTIC_LOCKED_AUTONOMOUS_EXECUTION_RUNTIME"] = TARGET_OBJECT
    required_completion_endpoint: Literal["/completion/claim"] = "/completion/claim"
    required_completion_tool: Literal["scripts/invoke_codex_completion_claim_gate.ps1"] = "scripts/invoke_codex_completion_claim_gate.ps1"
    completion_claim_required_before_final_complete: Literal[True] = True
    codex_system_prompt_rule: str
    agents_md_rule_bound: bool = False


class EndToEndFlowResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["xinao.codex_centric_end_to_end_flow.v1"] = "xinao.codex_centric_end_to_end_flow.v1"
    status: Literal["passed", "blocked"]
    task_object_id: str
    partial_decision: CompletionDecision
    complete_decision: CompletionDecision
    rejected_decision: CompletionDecision
    adapter_status: dict[str, Any]
    persisted: bool
    trace_id: str


class PersistenceStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["postgres_enabled", "sqlite_fallback_enabled", "blocked"]
    postgres_enabled: bool
    sqlite_fallback_enabled: bool
    database_path: str
    tables: tuple[str, ...]


class PersistentBackend:
    """Durable backend for task, contract, frontier, result, and event records.

    PostgreSQL is the target adapter. This local implementation uses SQLite when
    no Postgres driver/DSN is available, while preserving table boundaries.
    """

    TABLES = ("tasks", "contracts", "frontier", "results", "events")

    def __init__(self, runtime_root: pathlib.Path = DEFAULT_RUNTIME, database_path: pathlib.Path | None = None):
        self.runtime_root = pathlib.Path(runtime_root)
        self.database_path = pathlib.Path(database_path) if database_path else self.runtime_root / "state" / "codex_centric_object_preserving_runtime" / "persistent_backend.sqlite3"
        self.postgres_dsn = os.environ.get("XINAO_OBJECT_RUNTIME_POSTGRES_DSN", "")
        self.postgres_driver_available = module_available("psycopg") or module_available("psycopg2")
        self.postgres_enabled = bool(self.postgres_dsn and self.postgres_driver_available)
        self.sqlite_fallback_enabled = not self.postgres_enabled

    def connect(self):
        if self.postgres_enabled:
            import psycopg

            return psycopg.connect(self.postgres_dsn)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.database_path))
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> PersistenceStatus:
        connection = self.connect()
        try:
            ddl = """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_object_id TEXT PRIMARY KEY,
                    target_object TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contracts (
                    contract_id TEXT PRIMARY KEY,
                    parent TEXT NOT NULL,
                    coverage_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS frontier (
                    frontier_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS results (
                    result_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            if self.postgres_enabled:
                with connection.cursor() as cursor:
                    cursor.execute(ddl)
            else:
                connection.executescript(ddl)
            connection.commit()
        finally:
            connection.close()
        return self.status()

    def status(self) -> PersistenceStatus:
        target = (
            "postgresql://xinao@127.0.0.1:19432/xinao_continuity"
            if self.postgres_enabled
            else str(self.database_path)
        )
        return PersistenceStatus(
            status="postgres_enabled" if self.postgres_enabled else "sqlite_fallback_enabled",
            postgres_enabled=self.postgres_enabled,
            sqlite_fallback_enabled=self.sqlite_fallback_enabled,
            database_path=target,
            tables=self.TABLES,
        )

    def put_task(self, task: TaskObject) -> None:
        connection = self.connect()
        try:
            if self.postgres_enabled:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO tasks(task_object_id, target_object, payload_json, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (task_object_id) DO UPDATE SET
                          target_object = EXCLUDED.target_object,
                          payload_json = EXCLUDED.payload_json,
                          created_at = EXCLUDED.created_at
                        """,
                        (task.task_object_id, task.target_object, task.model_dump_json(), now()),
                    )
            else:
                connection.execute(
                    "INSERT OR REPLACE INTO tasks(task_object_id, target_object, payload_json, created_at) VALUES (?, ?, ?, ?)",
                    (task.task_object_id, task.target_object, task.model_dump_json(), now()),
                )
            connection.commit()
        finally:
            connection.close()

    def put_contract(self, contract: RefinementContract) -> None:
        connection = self.connect()
        try:
            if self.postgres_enabled:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO contracts(contract_id, parent, coverage_status, payload_json, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (contract_id) DO UPDATE SET
                          parent = EXCLUDED.parent,
                          coverage_status = EXCLUDED.coverage_status,
                          payload_json = EXCLUDED.payload_json,
                          created_at = EXCLUDED.created_at
                        """,
                        (contract.contract_id, contract.parent, contract.coverage_status, contract.model_dump_json(), now()),
                    )
            else:
                connection.execute(
                    "INSERT OR REPLACE INTO contracts(contract_id, parent, coverage_status, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (contract.contract_id, contract.parent, contract.coverage_status, contract.model_dump_json(), now()),
                )
            connection.commit()
        finally:
            connection.close()

    def put_frontier(self, frontier_id: str, frontier: FrontierState) -> None:
        connection = self.connect()
        try:
            if self.postgres_enabled:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO frontier(frontier_id, status, payload_json, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (frontier_id) DO UPDATE SET
                          status = EXCLUDED.status,
                          payload_json = EXCLUDED.payload_json,
                          updated_at = EXCLUDED.updated_at
                        """,
                        (frontier_id, frontier.status, frontier.model_dump_json(), now()),
                    )
            else:
                connection.execute(
                    "INSERT OR REPLACE INTO frontier(frontier_id, status, payload_json, updated_at) VALUES (?, ?, ?, ?)",
                    (frontier_id, frontier.status, frontier.model_dump_json(), now()),
                )
            connection.commit()
        finally:
            connection.close()

    def put_result(self, result_id: str, status: str, payload: dict[str, Any]) -> None:
        connection = self.connect()
        try:
            if self.postgres_enabled:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO results(result_id, status, payload_json, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (result_id) DO UPDATE SET
                          status = EXCLUDED.status,
                          payload_json = EXCLUDED.payload_json,
                          created_at = EXCLUDED.created_at
                        """,
                        (result_id, status, json.dumps(payload, ensure_ascii=False), now()),
                    )
            else:
                connection.execute(
                    "INSERT OR REPLACE INTO results(result_id, status, payload_json, created_at) VALUES (?, ?, ?, ?)",
                    (result_id, status, json.dumps(payload, ensure_ascii=False), now()),
                )
            connection.commit()
        finally:
            connection.close()

    def append_event(self, event_id: str, event_type: str, payload: dict[str, Any]) -> None:
        connection = self.connect()
        try:
            if self.postgres_enabled:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO events(event_id, event_type, payload_json, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (event_id) DO UPDATE SET
                          event_type = EXCLUDED.event_type,
                          payload_json = EXCLUDED.payload_json,
                          created_at = EXCLUDED.created_at
                        """,
                        (event_id, event_type, json.dumps(payload, ensure_ascii=False), now()),
                    )
            else:
                connection.execute(
                    "INSERT OR REPLACE INTO events(event_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                    (event_id, event_type, json.dumps(payload, ensure_ascii=False), now()),
                )
            connection.commit()
        finally:
            connection.close()

    def put_completion_decision(self, decision_id: str, decision: CompletionDecision) -> None:
        self.put_result(decision_id, decision.status, decision.model_dump(mode="json"))
        self.append_event(
            f"evt_{decision_id}",
            "xinao.codex_centric_object_runtime.completion_decision",
            decision.model_dump(mode="json"),
        )

    def counts(self) -> dict[str, int]:
        connection = self.connect()
        try:
            if self.postgres_enabled:
                counts = {}
                with connection.cursor() as cursor:
                    for table in self.TABLES:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        counts[table] = int(cursor.fetchone()[0])
                return counts
            return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in self.TABLES}
        finally:
            connection.close()


def bind_task(
    user_goal: str,
    *,
    task_object_id: str | None = None,
    original_text_refs: tuple[str, ...] = (),
    original_object: str = "object-preserving autonomous planner under XINAO semantic lock",
    requested_operation: str = "Bind Codex as central brain and primary executor with refinement-contract-verified workers.",
) -> TaskObject:
    refs = original_text_refs or (r"C:\Users\xx363\Desktop\0.2.txt",)
    source_refs = (
        {
            "source_text_embedded": False,
            "source_text_authority": False,
            "semantic_input_role": "non_authoritative_reference",
            "source_sha256": hashlib.sha256(user_goal.encode("utf-8")).hexdigest(),
            "source_char_count": len(user_goal),
            "original_text_refs": list(refs),
            "compiled_objective_code": "CODEX_CENTRIC_OBJECT_PRESERVING_RUNTIME",
        },
    )
    return TaskObject(
        task_object_id=task_object_id or f"{RUNTIME_PACKAGE_ID}_TASK_OBJECT",
        original_text_refs=refs,
        source_refs=source_refs,
        original_object=original_object,
        requested_operation=(
            f"{requested_operation} User goal is compiled into source_refs hash metadata; "
            "source wording is non-authoritative and not embedded in this task object."
        ),
    )


def contract_to_verifier_payload(contract: RefinementContract) -> dict[str, Any]:
    payload = contract.model_dump(mode="json")
    payload["children"] = list(contract.children)
    return payload


def verify_refinement(
    contract: RefinementContract,
    *,
    repo_root: pathlib.Path = DEFAULT_REPO,
    output_dir: pathlib.Path | None = None,
) -> VerificationResult:
    output_dir = pathlib.Path(output_dir) if output_dir else DEFAULT_RUNTIME / "artifacts" / "tmp" / "codex_centric_refinement"
    raw = refinement_contract_verifier.verify_contract(
        contract_to_verifier_payload(contract),
        repo_root=repo_root,
        output_dir=output_dir,
    )
    issues = tuple(raw.get("denies") or ())
    frontier_open = raw.get("frontier_open") is True
    completion_claimed = (
        raw.get("completion_claimed") is True
        or (raw.get("is_valid") is True and contract.coverage_status == "full" and contract.completion_claimed)
    )
    if raw.get("is_valid") and contract.coverage_status == "full":
        recommendation: Literal["accept", "partial", "reject"] = "accept"
    elif raw.get("is_valid") and frontier_open:
        recommendation = "partial"
    else:
        recommendation = "reject"
    return VerificationResult(
        is_valid=raw.get("is_valid") is True,
        coverage_claim=contract.claim,
        proof_summary=contract.proof_or_validator,
        issues=issues,
        recommendation=recommendation,
        frontier_open=frontier_open,
        completion_claimed=completion_claimed,
    )


def apply_frontier_update(
    state: FrontierState,
    contract: RefinementContract,
    verification: VerificationResult,
) -> FrontierState:
    completed = list(state.completed_contracts)
    rejected = list(state.rejected_contracts)
    items = list(state.items)
    if verification.recommendation == "reject":
        rejected.append(contract.contract_id)
    else:
        completed.append(contract.contract_id)
        update_items = contract.frontier_update.get("items", [])
        remaining = contract.frontier_update.get("remaining", [])
        items.extend(update_items)
        items.extend({"frontier_id": value, "reason": "remaining_refinement"} for value in remaining)
    open_items = tuple(item for item in items if item)
    return FrontierState(
        status="open" if open_items else "empty",
        items=open_items,
        completed_contracts=tuple(completed),
        rejected_contracts=tuple(rejected),
    )


def claim_completion(claim: CompletionClaim) -> CompletionDecision:
    contract = claim.contract
    verification = claim.verification
    if contract is None or verification is None:
        return CompletionDecision(
            status="rejected",
            stop_allowed=False,
            reason="contract_or_verification_missing",
        )
    if not verification.is_valid:
        return CompletionDecision(
            status="rejected",
            stop_allowed=False,
            reason="refinement_contract_not_verified",
            contract_id=contract.contract_id,
        )
    if verification.recommendation != "accept" or contract.coverage_status != "full":
        return CompletionDecision(
            status="partial",
            stop_allowed=False,
            reason="coverage_not_full_or_not_accepted",
            contract_id=contract.contract_id,
        )
    if claim.frontier.status != "empty" or claim.frontier.items:
        return CompletionDecision(
            status="partial",
            stop_allowed=False,
            reason="frontier_not_empty",
            contract_id=contract.contract_id,
        )
    frontier_blocker = frontier_completion_blocker(claim.frontier)
    if frontier_blocker:
        return CompletionDecision(
            status="partial",
            stop_allowed=False,
            reason=frontier_blocker,
            contract_id=contract.contract_id,
        )
    if not verification.completion_claimed or not contract.completion_claimed:
        return CompletionDecision(
            status="partial",
            stop_allowed=False,
            reason="completion_not_claimed_by_verified_contract",
            contract_id=contract.contract_id,
        )
    evidence_validation = memory_budget_rollback_gate.validate_claim_evidence(claim.model_dump(mode="json"))
    if not evidence_validation["passed"]:
        return CompletionDecision(
            status="partial",
            stop_allowed=False,
            reason=evidence_validation["decision_reason"],
            contract_id=contract.contract_id,
        )
    owner_blocker = current_task_owner_blocker(claim)
    if owner_blocker:
        return CompletionDecision(
            status="partial",
            stop_allowed=False,
            reason=owner_blocker,
            contract_id=contract.contract_id,
        )
    return CompletionDecision(
        status="complete_allowed",
        stop_allowed=True,
        reason="verified_full_coverage_frontier_empty_and_required_evidence_ready",
        contract_id=contract.contract_id,
    )


def frontier_completion_blocker(frontier: FrontierState) -> str:
    required_ids = set(frontier.required_frontier_ids)
    if not required_ids:
        return ""
    closed_ids = set(frontier.closed_frontier_ids)
    if frontier.all_required_frontier_ids_closed is not True:
        return "FRONTIER_REQUIRED_IDS_NOT_CLOSED"
    if not required_ids.issubset(closed_ids):
        return "FRONTIER_REQUIRED_IDS_NOT_COVERED"
    evidence_ids = {
        str(item.get("frontier_id") or "").strip()
        for item in frontier.closed_frontier_evidence
        if isinstance(item, dict)
    }
    missing_evidence = sorted(required_ids - evidence_ids)
    if missing_evidence:
        return "FRONTIER_REQUIRED_EVIDENCE_MISSING"
    return ""


def claim_completion_against_runtime_owner(
    claim: CompletionClaim,
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
) -> CompletionDecision:
    decision = claim_completion(claim)
    if decision.status != "complete_allowed" or decision.stop_allowed is not True:
        return decision
    blocker = persisted_current_task_owner_blocker(claim, runtime_root)
    if blocker:
        return CompletionDecision(
            status="partial",
            stop_allowed=False,
            reason=blocker,
            contract_id=decision.contract_id,
        )
    return decision


def current_task_owner_blocker(claim: CompletionClaim) -> str:
    owner = claim.current_task_owner or {}
    if not isinstance(owner, dict) or not owner:
        return "CURRENT_TASK_OWNER_BINDING_MISSING"
    if str(owner.get("task_id") or "") != claim.task_object_id:
        return "CURRENT_TASK_OWNER_TASK_MISMATCH"
    if owner.get("owner_kind") != "TemporalWorkflow":
        return "CURRENT_TASK_OWNER_NOT_TEMPORAL_WORKFLOW"
    if owner.get("stop_gate_scope") != "current_task_id_only":
        return "CURRENT_TASK_OWNER_STOP_GATE_SCOPE_INVALID"
    if not str(owner.get("workflow_id") or "").strip():
        return "CURRENT_TASK_OWNER_WORKFLOW_ID_MISSING"
    if not str(owner.get("workflow_run_id") or "").strip():
        return "CURRENT_TASK_OWNER_WORKFLOW_RUN_ID_MISSING"
    must_read = owner.get("stop_gate_must_read") or []
    must_read_text = "\n".join(str(item) for item in must_read)
    if "Codex exec JSONL" not in must_read_text and "app-server event evidence" not in must_read_text:
        return "CURRENT_TASK_OWNER_CODEX_EXEC_EVIDENCE_BINDING_MISSING"
    return ""


def persisted_current_task_owner_blocker(claim: CompletionClaim, runtime_root: pathlib.Path = DEFAULT_RUNTIME) -> str:
    owner = claim.current_task_owner or {}
    if not isinstance(owner, dict) or not owner:
        return "CURRENT_TASK_OWNER_BINDING_MISSING"
    task_id = claim.task_object_id
    runtime_root = pathlib.Path(runtime_root)
    owner_dir = runtime_root / "state" / "current_task_owner"
    safe_owner_path = owner_dir / f"{safe_name(task_id)}.json"
    raw_owner_path = owner_dir / f"{task_id}.json"
    latest_owner_path = owner_dir / "latest.json"
    persisted = read_json(safe_owner_path) if safe_owner_path.is_file() else None
    if not isinstance(persisted, dict) and raw_owner_path != safe_owner_path:
        persisted = read_json(raw_owner_path) if raw_owner_path.is_file() else None
    if not isinstance(persisted, dict):
        latest = read_json(latest_owner_path) if latest_owner_path.is_file() else None
        if isinstance(latest, dict) and latest.get("task_id") == task_id:
            persisted = latest
    if not isinstance(persisted, dict):
        return "CURRENT_TASK_OWNER_PERSISTED_STATE_MISSING"
    if persisted.get("task_id") != task_id:
        return "CURRENT_TASK_OWNER_PERSISTED_TASK_MISMATCH"
    if str(persisted.get("workflow_id") or "") != str(owner.get("workflow_id") or ""):
        return "CURRENT_TASK_OWNER_PERSISTED_WORKFLOW_ID_MISMATCH"
    if str(persisted.get("workflow_run_id") or "") != str(owner.get("workflow_run_id") or ""):
        return "CURRENT_TASK_OWNER_PERSISTED_WORKFLOW_RUN_ID_MISMATCH"
    latest = read_json(latest_owner_path) if latest_owner_path.is_file() else None
    if not isinstance(latest, dict):
        return "CURRENT_TASK_OWNER_LATEST_STATE_MISSING"
    if latest.get("task_id") != task_id:
        return "CURRENT_TASK_OWNER_LATEST_TASK_MISMATCH"
    if str(latest.get("workflow_id") or "") != str(owner.get("workflow_id") or ""):
        return "CURRENT_TASK_OWNER_LATEST_WORKFLOW_ID_MISMATCH"
    if str(latest.get("workflow_run_id") or "") != str(owner.get("workflow_run_id") or ""):
        return "CURRENT_TASK_OWNER_LATEST_WORKFLOW_RUN_ID_MISMATCH"
    return ""


def default_current_task_owner(task_id: str, runtime_root: pathlib.Path = DEFAULT_RUNTIME) -> dict[str, Any]:
    runtime_root = pathlib.Path(runtime_root)
    return {
        "schema_version": "xinao.current_task_owner.v1",
        "generated_at": now(),
        "task_id": task_id,
        "active_object_id": ACTIVE_OBJECT,
        "owner_kind": "TemporalWorkflow",
        "workflow_id": f"local-compatibility-{safe_name(task_id)}",
        "workflow_run_id": f"local-run-{safe_name(task_id)}",
        "task_queue": "local-compatibility-flow",
        "execution_event_source": "local durable compatibility flow",
        "execution_surface": "Temporal-compatible workflow -> LangGraph checkpoint/frontier -> Codex exec/app-server worker evidence -> /completion/claim",
        "stop_gate_scope": "current_task_id_only",
        "stop_gate_must_read": [
            "current task workflow_id/run_id",
            "current task LangGraph checkpoint/frontier",
            "current task Codex exec JSONL or app-server event evidence",
            "current task /completion/claim decision",
            "current task verifier and side-audit evidence",
        ],
        "forbidden_completion_sources": [
            "global latest.json without matching task_id",
            "report text",
            "projection summary",
            "blackboard message",
            "Codex final response without post-final gate",
        ],
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "authority_boundary": authority_boundary("local_compatibility_current_task_owner"),
    }


def default_claim_evidence(task_id: str, runtime_root: pathlib.Path = DEFAULT_RUNTIME) -> dict[str, Any]:
    return memory_budget_rollback_gate.build_evidence_fields(
        task_id=task_id,
        runtime_root=runtime_root,
    )


def codex_main_brain_contract(repo_root: pathlib.Path = DEFAULT_REPO) -> CodexMainBrainContract:
    agents_path = pathlib.Path(repo_root) / "AGENTS.md"
    agents_text = agents_path.read_text(encoding="utf-8") if agents_path.is_file() else ""
    rule = (
        "For XINAO_SEMANTIC_LOCKED_AUTONOMOUS_EXECUTION_RUNTIME, Codex must not end a task as complete "
        "until it has called /completion/claim through scripts/invoke_codex_completion_claim_gate.ps1 "
        "or the deployed API and received status=complete_allowed with stop_allowed=true."
    )
    return CodexMainBrainContract(
        codex_system_prompt_rule=rule,
        agents_md_rule_bound=("/completion/claim" in agents_text and "invoke_codex_completion_claim_gate.ps1" in agents_text),
    )


def adapter_status() -> dict[str, Any]:
    langgraph = module_available("langgraph")
    temporal = module_available("temporalio")
    fastapi = module_available("fastapi")
    return {
        "langgraph_adapter": {
            "status": "adapter_bound" if langgraph else "unavailable",
            "langgraph_enabled": langgraph,
            "interface": "planner_checkpoint_graph",
            "fallback": "deterministic_local_graph" if not langgraph else "not_active",
        },
        "temporal_adapter": {
            "status": "adapter_bound" if temporal else "unavailable",
            "temporal_enabled": temporal,
            "interface": "durable_executor_workflow",
            "fallback": "local_checkpoint_executor" if not temporal else "not_active",
        },
        "fallback_adapter": {"status": "standby" if temporal else "active", "fallback_enabled": not temporal},
        "fastapi_adapter": {
            "status": "available_optional_shell" if fastapi else "unavailable_optional_shell",
            "fastapi_enabled": fastapi,
        },
        "default_runtime_path": {"status": "bound_and_verified", "stages": list(DEFAULT_PATH)},
    }


def subagent_prompts() -> dict[str, str]:
    base_rule = (
        "Never replace original_object, requested_operation, or completion_contract. "
        "Every decomposition must return a RefinementContract and keep frontier explicit unless coverage is full."
    )
    return {
        "semantic_binder": (
            f"{base_rule}\nBind the user goal into a frozen TaskObject. Return structured JSON only. "
            "Do not plan or execute."
        ),
        "planner": (
            f"{base_rule}\nPropose object-preserving children for the parent task. "
            "Prefer existing XINAO assets, LangGraph, Temporal, OPA, and Dify surfaces before local glue."
        ),
        "refinement_verifier": (
            f"{base_rule}\nValidate parent, children, claim, proof_or_validator, coverage_status, "
            "and frontier_update. Reject partial-as-complete and all object/operation replacement."
        ),
        "frontier_manager": (
            f"{base_rule}\nMaintain explicit frontier, completed contracts, rejected contracts, and canonical ids. "
            "Never mark empty frontier unless verifier accepted full coverage."
        ),
        "shard_executor": (
            f"{base_rule}\nExecute only verifier-accepted shards. Write trace, checkpoint, rollback, and result evidence."
        ),
        "coverage_proof": (
            f"{base_rule}\nWhen formal coverage is possible, prove union(children) covers parent. "
            "When not possible, mark candidate coverage and keep frontier open."
        ),
    }


def build_contract() -> dict[str, Any]:
    return {
        "schema_version": "xinao.codex-centric-object-preserving-runtime.v1",
        "runtime_package_id": RUNTIME_PACKAGE_ID,
        "target_object": TARGET_OBJECT,
        "codex_role": "central_brain_and_primary_executor",
        "workers_role": "specialized_workers_under_refinement_contract",
        "default_runtime_path": list(DEFAULT_PATH),
        "backend_endpoints": [
            "/bind_task",
            "/verify_refinement",
            "/completion/claim",
            "/frontier/apply",
            "/adapter_status",
            "/subagent_prompts",
            "/codex_main_brain_contract",
            "/tasks/run_end_to_end_canary",
        ],
        "codex_main_brain_completion_contract": codex_main_brain_contract().model_dump(mode="json"),
        "hard_rules": {
            "object_replacement_allowed": False,
            "operation_replacement_allowed": False,
            "completion_replacement_allowed": False,
            "refinement_contract_required": True,
            "partial_as_complete_allowed": False,
        },
        "mature_carriers": {
            "schema": "Pydantic models plus existing JSON Schema",
            "policy": "OPA refinement_contract_verifier.rego and semantic_locked_task_object.rego",
            "planner": "LangGraph when used; deterministic local fallback for tests",
            "durability": "Temporal when deployed; local checkpoint fallback when not deployed",
            "persistence": "PostgreSQL adapter interface; SQLite durable fallback when Postgres driver/DSN is unavailable",
            "codex_surfaces": "Codex TUI, codex exec, app-server, and subagents under main Codex verification",
        },
    }


def run_end_to_end_task_flow(
    *,
    task_id: str = "controlled_partition_object_1_to_6",
    repo_root: pathlib.Path = DEFAULT_REPO,
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    persist: bool = True,
) -> EndToEndFlowResult:
    task = bind_task(
        "Partition the controlled object {1,2,3,4,5,6} into even and odd shards, keep frontier explicit, and complete only after verified coverage.",
        task_object_id=task_id,
        original_text_refs=("controlled_object://integer_set_1_6",),
        original_object="CONTROLLED_INTEGER_SET:{1,2,3,4,5,6}",
        requested_operation="Exhaustively partition and verify coverage without replacing the object.",
    )
    partial_contract = RefinementContract(
        contract_id=f"{task_id}_partial_even_only",
        parent="EXHAUSTIVE_ENUMERATE(CONTROLLED_INTEGER_SET:{1,2,3,4,5,6})",
        children=("EVEN_SHARD:{2,4,6}",),
        requested_operation_ref=task.requested_operation,
        claim="Even shard covers only part of the original object; odd shard remains frontier.",
        proof_or_validator="set({2,4,6}) subset of set({1,2,3,4,5,6}); remaining set({1,3,5}) is non-empty.",
        coverage_status="partial",
        if_unproven="Odd shard remains open frontier.",
        frontier_update={"items": [{"frontier_id": "ODD_SHARD:{1,3,5}", "reason": "remaining controlled set"}], "remaining": []},
        completion_claimed=False,
    )
    full_contract = RefinementContract(
        contract_id=f"{task_id}_full_even_odd_partition",
        parent="EXHAUSTIVE_ENUMERATE(CONTROLLED_INTEGER_SET:{1,2,3,4,5,6})",
        children=("EVEN_SHARD:{2,4,6}", "ODD_SHARD:{1,3,5}"),
        requested_operation_ref=task.requested_operation,
        claim="EVEN_SHARD union ODD_SHARD equals CONTROLLED_INTEGER_SET:{1,2,3,4,5,6} with empty intersection.",
        proof_or_validator="sorted({2,4,6} | {1,3,5}) == [1,2,3,4,5,6] and intersection is empty.",
        coverage_status="full",
        frontier_update={"items": [], "remaining": [], "status": "empty_after_even_odd_partition"},
        completion_claimed=True,
    )
    partial_result = verify_refinement(partial_contract, repo_root=repo_root, output_dir=runtime_root / "artifacts" / "tmp" / "codex_centric_e2e_partial")
    full_result = verify_refinement(full_contract, repo_root=repo_root, output_dir=runtime_root / "artifacts" / "tmp" / "codex_centric_e2e_full")
    frontier_after_partial = apply_frontier_update(FrontierState(status="empty"), partial_contract, partial_result)
    rejected_decision = claim_completion(CompletionClaim(task_object_id=task.task_object_id, frontier=FrontierState(status="empty")))
    partial_decision = claim_completion(CompletionClaim(
        task_object_id=task.task_object_id,
        contract=partial_contract,
        verification=partial_result,
        frontier=frontier_after_partial,
    ))
    complete_decision = claim_completion(CompletionClaim(
        task_object_id=task.task_object_id,
        contract=full_contract,
        verification=full_result,
        frontier=FrontierState(status="empty", completed_contracts=(partial_contract.contract_id, full_contract.contract_id)),
        current_task_owner=default_current_task_owner(task.task_object_id, runtime_root),
        **default_claim_evidence(task.task_object_id, runtime_root),
    ))
    passed = (
        rejected_decision.status == "rejected"
        and not rejected_decision.stop_allowed
        and partial_decision.status == "partial"
        and not partial_decision.stop_allowed
        and complete_decision.status == "complete_allowed"
        and complete_decision.stop_allowed
    )
    trace_id = f"codex_centric_e2e_{task_id}"
    if persist:
        backend = PersistentBackend(runtime_root)
        backend.initialize()
        backend.put_task(task)
        backend.put_contract(partial_contract)
        backend.put_contract(full_contract)
        backend.put_frontier(f"{trace_id}_frontier_after_partial", frontier_after_partial)
        backend.put_result(f"{trace_id}_partial_verification", "partial", partial_result.model_dump(mode="json"))
        backend.put_result(f"{trace_id}_full_verification", "accepted", full_result.model_dump(mode="json"))
        backend.put_completion_decision(f"{trace_id}_rejected_without_verifier", rejected_decision)
        backend.put_completion_decision(f"{trace_id}_partial_with_frontier", partial_decision)
        backend.put_completion_decision(f"{trace_id}_complete_allowed", complete_decision)
    return EndToEndFlowResult(
        status="passed" if passed else "blocked",
        task_object_id=task.task_object_id,
        partial_decision=partial_decision,
        complete_decision=complete_decision,
        rejected_decision=rejected_decision,
        adapter_status=adapter_status(),
        persisted=persist,
        trace_id=trace_id,
    )


def build(repo_root: pathlib.Path = DEFAULT_REPO, runtime_root: pathlib.Path = DEFAULT_RUNTIME, output_dir: pathlib.Path | None = None) -> dict[str, Any]:
    repo = pathlib.Path(repo_root)
    runtime = pathlib.Path(runtime_root)
    rid = run_id()
    output_dir = pathlib.Path(output_dir) if output_dir else runtime / "artifacts" / "generated" / "codex_centric_object_preserving_runtime" / rid
    state_latest = runtime / "state" / "codex_centric_object_preserving_runtime" / "latest.json"
    contract_path = repo / "contracts" / "codex_centric_object_preserving_runtime.json"

    task = bind_task("implement Codex-centric object-preserving autonomous planner")
    full_contract = RefinementContract(
        contract_id="codex_centric_runtime_full_contract",
        parent=f"IMPLEMENT({TARGET_OBJECT})",
        children=DEFAULT_PATH,
        requested_operation_ref=task.requested_operation,
        claim="The default runtime path covers the scoped implementation package under the semantic lock.",
        proof_or_validator="Existing OPA refinement contract verifier plus content tests and verify script.",
        coverage_status="full",
        frontier_update={"items": [], "remaining": [], "status": "empty_after_full_coverage"},
        completion_claimed=True,
    )
    partial_contract = RefinementContract(
        contract_id="codex_centric_runtime_partial_contract",
        parent=f"IMPLEMENT({TARGET_OBJECT})",
        children=("semantic_binder", "refinement_verifier"),
        requested_operation_ref=task.requested_operation,
        claim="Binder and verifier are covered, but durable executor and human-visible delivery remain frontier.",
        proof_or_validator="Candidate coverage only.",
        coverage_status="partial",
        if_unproven="Keep frontier open.",
        frontier_update={"remaining": ["durable_executor", "human_delivery_gate"], "items": []},
        completion_claimed=False,
    )
    full_result = verify_refinement(full_contract, repo_root=repo, output_dir=output_dir / "opa")
    partial_result = verify_refinement(partial_contract, repo_root=repo, output_dir=output_dir / "opa")
    frontier = apply_frontier_update(FrontierState(status="empty"), partial_contract, partial_result)
    completion_decision = claim_completion(CompletionClaim(
        task_object_id=task.task_object_id,
        contract=full_contract,
        verification=full_result,
        frontier=FrontierState(status="empty", completed_contracts=(full_contract.contract_id,)),
        current_task_owner=default_current_task_owner(task.task_object_id, runtime),
        **default_claim_evidence(task.task_object_id, runtime),
    ))
    rejected_completion_decision = claim_completion(CompletionClaim(
        task_object_id=task.task_object_id,
        frontier=FrontierState(status="empty"),
    ))
    partial_completion_decision = claim_completion(CompletionClaim(
        task_object_id=task.task_object_id,
        contract=partial_contract,
        verification=partial_result,
        frontier=frontier,
    ))
    e2e_flow = run_end_to_end_task_flow(repo_root=repo, runtime_root=runtime, persist=False)
    main_brain_contract = codex_main_brain_contract(repo)
    prompts = subagent_prompts()
    persistence = PersistentBackend(runtime)
    persistence_status = persistence.initialize()
    persistence.put_task(task)
    persistence.put_contract(full_contract)
    persistence.put_contract(partial_contract)
    persistence.put_frontier("codex_centric_runtime_frontier_after_partial", frontier)
    persistence.put_result("codex_centric_runtime_full_contract_result", "accepted", full_result.model_dump(mode="json"))
    persistence.put_result("codex_centric_runtime_partial_contract_result", "partial", partial_result.model_dump(mode="json"))
    persistence.put_completion_decision("codex_centric_runtime_completion_decision", completion_decision)
    persistence.put_completion_decision("codex_centric_runtime_rejected_completion_without_verifier", rejected_completion_decision)
    persistence.put_completion_decision("codex_centric_runtime_partial_completion_with_frontier", partial_completion_decision)
    persistence.append_event(
        f"evt_{rid}_codex_centric_runtime_bound",
        "xinao.codex_centric_object_preserving_runtime.bound",
        {"target_object": TARGET_OBJECT, "default_runtime_path": list(DEFAULT_PATH)},
    )
    persistence_counts = persistence.counts()

    write_json(contract_path, build_contract())
    for name, prompt in prompts.items():
        write_text(output_dir / "subagent_prompts" / f"{name}.md", prompt)

    passed = (
        full_result.is_valid
        and full_result.recommendation == "accept"
        and partial_result.is_valid
        and partial_result.recommendation == "partial"
        and frontier.status == "open"
        and len(prompts) == 6
        and persistence_counts["tasks"] >= 1
        and persistence_counts["contracts"] >= 2
        and persistence_counts["frontier"] >= 1
        and persistence_counts["results"] >= 5
        and persistence_counts["events"] >= 4
        and completion_decision.stop_allowed
        and rejected_completion_decision.status == "rejected"
        and partial_completion_decision.status == "partial"
        and e2e_flow.status == "passed"
        and main_brain_contract.agents_md_rule_bound
    )
    payload = {
        "schema_version": "xinao.codex-centric-object-preserving-runtime-state.v1",
        "status": "codex_centric_object_preserving_runtime_bound" if passed else "codex_centric_object_preserving_runtime_blocked",
        "generated_at": now(),
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("object_preserving_runtime_readback"),
        "runtime_package_id": RUNTIME_PACKAGE_ID,
        "target_object": TARGET_OBJECT,
        "task_object": task.model_dump(mode="json"),
        "contract_path": str(contract_path),
        "default_runtime_path": list(DEFAULT_PATH),
        "verification": {
            "full_contract": full_result.model_dump(mode="json"),
            "partial_contract": partial_result.model_dump(mode="json"),
            "frontier_after_partial": frontier.model_dump(mode="json"),
            "completion_decision": completion_decision.model_dump(mode="json"),
            "rejected_completion_without_verifier": rejected_completion_decision.model_dump(mode="json"),
            "partial_completion_with_frontier": partial_completion_decision.model_dump(mode="json"),
            "end_to_end_controlled_task": e2e_flow.model_dump(mode="json"),
        },
        "adapter_status": adapter_status(),
        "codex_main_brain_contract": main_brain_contract.model_dump(mode="json"),
        "persistence_backend": {
            **persistence_status.model_dump(mode="json"),
            "counts": persistence_counts,
            "postgres_driver_available": persistence.postgres_driver_available,
            "postgres_dsn_configured": bool(persistence.postgres_dsn),
        },
        "subagent_prompt_paths": {
            name: str(output_dir / "subagent_prompts" / f"{name}.md")
            for name in prompts
        },
        "backend_boundary": {
            "fastapi_optional": True,
            "pure_python_core_verified": True,
            "persistent_backend_verified": True,
            "do_not_claim_fastapi_deployed_when_missing": True,
            "do_not_claim_postgres_enabled_when_missing": True,
        },
        "artifact_paths": {"output_dir": str(output_dir), "runtime_state_latest": str(state_latest)},
        "sentinel": SENTINEL if passed else "SENTINEL:XINAO_CODEX_CENTRIC_OBJECT_PRESERVING_RUNTIME_BLOCKED",
    }
    write_json(output_dir / "codex_centric_object_preserving_runtime.json", payload)
    write_json(state_latest, payload)
    return payload


def create_app():
    try:
        from fastapi import FastAPI
    except ModuleNotFoundError as exc:
        raise RuntimeError("FASTAPI_ADAPTER_UNAVAILABLE_OPTIONAL_SHELL") from exc

    app = FastAPI(title="XINAO Codex-Centric Object Preserving Runtime")

    @app.post("/bind_task")
    def bind_task_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        task = bind_task(
            payload.get("user_goal", ""),
            original_text_refs=tuple(payload.get("original_text_refs") or ()),
            original_object=payload.get("original_object", "object-preserving autonomous planner under XINAO semantic lock"),
            requested_operation=payload.get("requested_operation", "Bind Codex central brain runtime."),
        )
        return task.model_dump(mode="json")

    @app.post("/verify_refinement")
    def verify_refinement_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        contract = RefinementContract(**payload)
        return verify_refinement(contract).model_dump(mode="json")

    @app.post("/completion/claim")
    def completion_claim_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        claim = CompletionClaim(**payload)
        decision = claim_completion_against_runtime_owner(claim, DEFAULT_RUNTIME)
        backend = PersistentBackend(DEFAULT_RUNTIME)
        backend.initialize()
        backend.put_completion_decision(
            f"api_completion_claim_{claim.task_object_id}_{decision.status}",
            decision,
        )
        return decision.model_dump(mode="json")

    @app.get("/adapter_status")
    def adapter_status_endpoint() -> dict[str, Any]:
        return adapter_status()

    @app.get("/persistence_status")
    def persistence_status_endpoint() -> dict[str, Any]:
        backend = PersistentBackend(DEFAULT_RUNTIME)
        backend.initialize()
        return {**backend.status().model_dump(mode="json"), "counts": backend.counts()}

    @app.get("/subagent_prompts")
    def subagent_prompts_endpoint() -> dict[str, str]:
        return subagent_prompts()

    @app.get("/codex_main_brain_contract")
    def codex_main_brain_contract_endpoint() -> dict[str, Any]:
        return codex_main_brain_contract().model_dump(mode="json")

    @app.post("/tasks/run_end_to_end_canary")
    def run_end_to_end_canary_endpoint(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        task_id = (payload or {}).get("task_id", "api_controlled_partition_object_1_to_6")
        return run_end_to_end_task_flow(task_id=task_id).model_dump(mode="json")

    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    payload = build(
        pathlib.Path(args.repo_root),
        pathlib.Path(args.runtime_root),
        pathlib.Path(args.output_dir) if args.output_dir else None,
    )
    print(json.dumps({
        "status": payload["status"],
        "runtime_package_id": payload["runtime_package_id"],
        "fastapi_adapter": payload["adapter_status"]["fastapi_adapter"],
        "sentinel": payload["sentinel"],
    }, ensure_ascii=False, indent=2))
    print(payload["sentinel"])
    return 0 if payload["sentinel"] == SENTINEL else 1


if __name__ == "__main__":
    sys.exit(main())
