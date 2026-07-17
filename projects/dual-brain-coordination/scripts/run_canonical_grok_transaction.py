#!/usr/bin/env python3
"""Run one bounded Grok -> Temporal -> Docker LangGraph transaction.

The Windows host worker owns only the Grok-facing Temporal workflow and
activities for this transaction.  The promoted workflow delegates its
LangGraph child to the canonical Docker ``houtai-gongren`` task queue, then
this process exits.  No resident scheduler or second control plane is added.
"""

# ruff: noqa: E402 -- this standalone entrypoint bootstraps project src before imports.

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import threading
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
SRC = PROJECT_ROOT / "src"
for candidate in (str(SRC), str(PROJECT_ROOT), str(REPO_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from services.agent_runtime.routing_policy_reader import draft_model
from temporalio.client import Client

from adapters.temporal.canary_start_workflow import create_kernel_backed_canary_task
from adapters.temporal.deployment_management import (
    ensure_deployment_current,
    load_verified_deployment,
)
from adapters.temporal.worker_runtime import build_promoted_worker
from xinao_coordination.service import CoordinationService
from xinao_coordination.temporal.activities import PROMOTED_ACTIVITIES
from xinao_coordination.temporal.grok_parallel import validate_ready_frontier
from xinao_coordination.temporal.workflow import PROMOTED_WORKFLOWS

DEFAULT_DB = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3")
DEFAULT_RUN_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\canonical_grok_transactions")
DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
CANONICAL_LANGGRAPH_QUEUE = "xinao-integrated-langgraph-plugin-queue"
CANONICAL_HOST_QUEUE = "xinao-canonical-grok-host-v1"
DEPLOYMENT_MANIFEST = PROJECT_ROOT / "adapters" / "temporal" / "canonical_grok_host_deployment.v1.json"
TRANSACTION_IDENTITY_VERSION = "xinao.canonical_grok_transaction.identity.v1"
TRANSACTION_ATTEMPT_VERSION = "xinao.canonical_grok_transaction.attempt.v1"
TRANSACTION_EXECUTION_VERSION = "xinao.canonical_grok_transaction.execution.v1"
TRANSACTION_ATTEMPT_OUTCOME_VERSION = "xinao.canonical_grok_transaction.attempt_outcome.v1"
TRANSACTION_KEY_SEMANTICS = (
    "same_key_reconnects_exact_execution;new_execution_requires_new_key"
)
MAX_TRANSACTION_ATTEMPTS = 9_999
CANCEL_CONFIRM_TIMEOUT_SECONDS = 30.0
CANCEL_RPC_TIMEOUT_SECONDS = 5.0
TERMINAL_WORKFLOW_STATUSES = frozenset(
    {"CANCELED", "COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"}
)
_PROCESS_ENVIRONMENT_GUARD = threading.Lock()


class TransactionIdentityConflict(ValueError):
    """One stable transaction key was reused for different immutable inputs."""


class TransactionBusyError(RuntimeError):
    """Another process currently owns this stable transaction."""


@dataclass(frozen=True)
class TransactionAttempt:
    transaction_dir: Path
    run_dir: Path
    attempt_id: str
    transaction_key_sha256: str
    transaction_identity_sha256: str


class _TransactionClaim:
    """Hold one cross-process advisory lock for the lifetime of a transaction attempt."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any | None = None

    def __enter__(self) -> _TransactionClaim:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise TransactionBusyError(
                f"stable transaction is already active: {self.path.parent.name}"
            ) from exc
        owner = json.dumps(
            {
                "schema_version": "xinao.canonical_grok_transaction.claim.v1",
                "pid": os.getpid(),
                "claimed_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        handle.seek(0)
        handle.truncate()
        handle.write(owner)
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _read_payload(
    raw: bytes,
    *,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    langgraph_task_queue: str = CANONICAL_LANGGRAPH_QUEUE,
) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("payload must be a JSON object")
    frontier = validate_ready_frontier(
        payload.get("grok_ready_frontier"),
        serial_reason=str(payload.get("grok_serial_reason") or ""),
        default_model=draft_model(runtime_root=runtime_root),
    )
    if not frontier:
        raise ValueError("canonical Grok transaction requires a non-empty ready frontier")
    payload["grok_ready_frontier"] = frontier
    child = dict(payload.get("langgraph_child") or {})
    child.setdefault("enabled", True)
    child.setdefault("task_queue", langgraph_task_queue)
    child.setdefault("workflow_type", "XinaoIntegratedBusWorkflow")
    payload["langgraph_child"] = child
    return payload


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json_atomic(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _json_bytes(value)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)
    return _sha256(raw)


def _write_json_exclusive(path: Path, value: object) -> str:
    """Create immutable JSON without ever replacing an existing file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _json_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    return _sha256(raw)


def _read_json_object(
    path: Path,
    *,
    label: str = "stable transaction identity",
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransactionIdentityConflict(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise TransactionIdentityConflict(
            f"{label} is not an object: {path}"
        )
    return value


def _create_or_validate_transaction_identity(path: Path, expected: dict[str, Any]) -> str:
    if path.exists():
        observed = _read_json_object(path)
        if observed != expected:
            raise TransactionIdentityConflict(
                "stable transaction key conflicts with existing payload or route identity"
            )
        return _sha256(path.read_bytes())
    return _write_json_exclusive(path, expected)


def _allocate_attempt_dir(transaction_dir: Path) -> tuple[str, Path]:
    attempts_dir = transaction_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    for number in range(1, MAX_TRANSACTION_ATTEMPTS + 1):
        attempt_id = f"attempt-{number:04d}"
        run_dir = attempts_dir / attempt_id
        try:
            run_dir.mkdir()
        except FileExistsError:
            continue
        return attempt_id, run_dir
    raise RuntimeError("stable transaction exhausted its bounded attempt namespace")


@contextmanager
def _transaction_attempt(
    *,
    run_root: Path,
    suffix: str,
    transaction_key: str,
    identity: dict[str, Any],
) -> Iterator[TransactionAttempt]:
    root = run_root.resolve()
    stable_key = transaction_key.strip()
    if not stable_key:
        run_dir = root / f"canonical-grok-{suffix}"
        run_dir.mkdir(parents=True, exist_ok=False)
        yield TransactionAttempt(
            transaction_dir=run_dir,
            run_dir=run_dir,
            attempt_id="single",
            transaction_key_sha256="",
            transaction_identity_sha256="",
        )
        return

    key_sha256 = _sha256(stable_key.encode("utf-8"))
    if str(identity.get("transaction_key_sha256") or "") != key_sha256:
        raise TransactionIdentityConflict(
            "stable transaction identity does not bind the supplied transaction key"
        )
    transaction_dir = root / f"canonical-grok-key-{key_sha256[:20]}"
    transaction_dir.mkdir(parents=True, exist_ok=True)
    with _TransactionClaim(transaction_dir / "execution.lock"):
        identity_sha256 = _create_or_validate_transaction_identity(
            transaction_dir / "identity.json",
            identity,
        )
        attempt_id, run_dir = _allocate_attempt_dir(transaction_dir)
        _write_json_exclusive(
            run_dir / "attempt.json",
            {
                "schema_version": TRANSACTION_ATTEMPT_VERSION,
                "attempt_id": attempt_id,
                "created_at": datetime.now(UTC).isoformat(),
                "pid": os.getpid(),
                "transaction_identity_sha256": identity_sha256,
                "transaction_key_sha256": key_sha256,
            },
        )
        yield TransactionAttempt(
            transaction_dir=transaction_dir,
            run_dir=run_dir,
            attempt_id=attempt_id,
            transaction_key_sha256=key_sha256,
            transaction_identity_sha256=identity_sha256,
        )


@contextmanager
def _exclusive_process_environment(updates: dict[str, str]) -> Iterator[None]:
    """Bind process-global runtime settings without allowing in-process cross-talk.

    Independent processes remain the supported parallel-width unit.  A single
    Python process cannot safely run two workers with different database or
    queue environment because activities resolve those values at execution
    time rather than worker construction time.
    """

    if not _PROCESS_ENVIRONMENT_GUARD.acquire(blocking=False):
        raise TransactionBusyError(
            "another canonical transaction owns the process-global worker environment"
        )
    previous = {name: os.environ.get(name) for name in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _PROCESS_ENVIRONMENT_GUARD.release()


def _load_execution_binding(
    path: Path,
    *,
    transaction_identity_sha256: str,
    task_queue: str,
) -> dict[str, Any]:
    binding = _read_json_object(path, label="stable transaction execution binding")
    required = {
        "schema_version": TRANSACTION_EXECUTION_VERSION,
        "transaction_key_semantics": TRANSACTION_KEY_SEMANTICS,
        "transaction_identity_sha256": transaction_identity_sha256,
        "task_queue": task_queue,
    }
    if any(binding.get(name) != value for name, value in required.items()):
        raise TransactionIdentityConflict(
            "stable transaction execution binding conflicts with immutable identity"
        )
    for name in ("task_id", "workflow_id", "run_id", "first_execution_run_id"):
        if not str(binding.get(name) or "").strip():
            raise TransactionIdentityConflict(
                f"stable transaction execution binding is missing {name}"
            )
    return binding


def _attempt_outcome(
    *,
    transaction: TransactionAttempt,
    status: str,
    phase: str,
    error_type: str = "",
    started_record: dict[str, Any] | None = None,
    cancellation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": TRANSACTION_ATTEMPT_OUTCOME_VERSION,
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": status,
        "phase": phase,
        "error_type": error_type,
        "attempt_id": transaction.attempt_id,
        "transaction_identity_sha256": transaction.transaction_identity_sha256,
        "transaction_key_sha256": transaction.transaction_key_sha256,
        "transaction_key_semantics": TRANSACTION_KEY_SEMANTICS,
    }
    if started_record is not None:
        for name in ("task_id", "workflow_id", "run_id", "first_execution_run_id", "task_queue"):
            if started_record.get(name):
                record[name] = started_record[name]
    if cancellation is not None:
        for name in (
            "workflow_cancel_attempted",
            "workflow_cancel_requested",
            "workflow_terminal_confirmed",
            "workflow_cancel_confirmed",
            "workflow_cancel_terminal_status",
            "workflow_cancel_error_type",
            "workflow_cancel_chain_identity_ok",
        ):
            if name in cancellation:
                record[name] = cancellation[name]
    return record


def _load_verified_deployment() -> dict[str, Any]:
    return load_verified_deployment(PROJECT_ROOT, DEPLOYMENT_MANIFEST)


def _build_transaction_identity(
    *,
    transaction_key: str,
    payload_sha256: str,
    payload: dict[str, Any],
    task_queue: str,
    langgraph_task_queue: str,
    deployment_name: str,
    deployment_build_id: str,
    runtime_root: Path,
    db_path: Path,
    resume_workflow_id: str,
    resume_run_id: str,
    resume_first_execution_run_id: str,
    resume_task_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": TRANSACTION_IDENTITY_VERSION,
        "transaction_key_semantics": TRANSACTION_KEY_SEMANTICS,
        "transaction_key_sha256": _sha256(transaction_key.strip().encode("utf-8")),
        "payload_sha256": payload_sha256,
        "requested_task_id": str(payload["task_id"]),
        "requested_workflow_id": str(payload["workflow_id"]),
        "task_queue": task_queue,
        "langgraph_task_queue": langgraph_task_queue,
        "worker_deployment_name": deployment_name,
        "worker_build_id": deployment_build_id,
        "runtime_root": str(runtime_root.resolve()),
        "coordination_db": str(db_path.resolve()),
        "requested_models": sorted(
            {str(item.get("model") or "") for item in payload["grok_ready_frontier"]}
        ),
        "mode": "resume" if resume_workflow_id.strip() else "start",
        "resume_workflow_id": resume_workflow_id.strip(),
        "resume_run_id": resume_run_id.strip(),
        "resume_first_execution_run_id": resume_first_execution_run_id.strip(),
        "resume_task_id": resume_task_id.strip(),
    }


async def _cancel_exact_workflow(
    handle: Any,
    *,
    expected_first_execution_run_id: str,
    timeout_seconds: float = CANCEL_CONFIRM_TIMEOUT_SECONDS,
) -> dict[str, object]:
    outcome: dict[str, object] = {
        "workflow_cancel_attempted": True,
        "workflow_cancel_requested": False,
        "workflow_terminal_confirmed": False,
        "workflow_cancel_confirmed": False,
        "workflow_cancel_terminal_status": "",
        "workflow_cancel_error_type": "",
        "workflow_cancel_chain_identity_ok": False,
    }
    rpc_timeout = timedelta(
        seconds=max(0.001, min(CANCEL_RPC_TIMEOUT_SECONDS, timeout_seconds))
    )
    try:
        async with asyncio.timeout(max(0.001, timeout_seconds)):
            try:
                await handle.cancel(
                    reason="canonical transaction owner exiting before verified completion",
                    rpc_timeout=rpc_timeout,
                )
                outcome["workflow_cancel_requested"] = True
            except Exception as exc:
                outcome["workflow_cancel_error_type"] = type(exc).__name__
            while True:
                try:
                    description = await handle.describe(rpc_timeout=rpc_timeout)
                except Exception as exc:
                    if not outcome["workflow_cancel_error_type"]:
                        outcome["workflow_cancel_error_type"] = type(exc).__name__
                    break
                raw_info = getattr(description, "raw_info", None)
                observed_first_run_id = str(
                    getattr(raw_info, "first_run_id", "") or ""
                )
                chain_identity_ok = (
                    observed_first_run_id == expected_first_execution_run_id
                )
                outcome["workflow_cancel_chain_identity_ok"] = chain_identity_ok
                if not chain_identity_ok:
                    outcome["workflow_cancel_error_type"] = "WorkflowChainIdentityMismatch"
                    break
                status = str(getattr(getattr(description, "status", None), "name", ""))
                outcome["workflow_cancel_terminal_status"] = status
                if status in TERMINAL_WORKFLOW_STATUSES:
                    outcome["workflow_terminal_confirmed"] = True
                    outcome["workflow_cancel_confirmed"] = status == "CANCELED"
                    break
                await asyncio.sleep(0.1)
    except TimeoutError:
        if not outcome["workflow_cancel_error_type"]:
            outcome["workflow_cancel_error_type"] = "TimeoutError"
    return outcome


async def _observe_started_workflow(
    *,
    client: Client,
    started_record: dict[str, Any],
    run_dir: Path,
    timeout_seconds: float,
    handshake_path: Path | None,
    on_started: Callable[[dict[str, Any]], Awaitable[None]] | None,
    execution_binding_path: Path | None = None,
    execution_binding: dict[str, Any] | None = None,
    resolve_first_execution_run_id: bool = False,
) -> tuple[object, object]:
    """Persist, notify, and await one exact started workflow under cancel protection."""

    handle: Any | None = None
    try:
        handle = client.get_workflow_handle(
            str(started_record["workflow_id"]),
            run_id=str(started_record["run_id"]),
        )
        initial_description = await handle.describe(
            rpc_timeout=timedelta(seconds=CANCEL_RPC_TIMEOUT_SECONDS)
        )
        observed_first_run_id = str(
            getattr(getattr(initial_description, "raw_info", None), "first_run_id", "")
            or ""
        )
        if not observed_first_run_id:
            raise TransactionIdentityConflict(
                "started workflow did not expose a first execution run id"
            )
        if resolve_first_execution_run_id:
            started_record["first_execution_run_id"] = observed_first_run_id
            if execution_binding is not None:
                execution_binding["first_execution_run_id"] = observed_first_run_id
        elif observed_first_run_id != str(started_record["first_execution_run_id"]):
            raise TransactionIdentityConflict(
                "started workflow does not match the bound execution chain"
            )
        handle = client.get_workflow_handle(
            str(started_record["workflow_id"]),
            run_id=str(started_record["run_id"]),
            first_execution_run_id=str(started_record["first_execution_run_id"]),
        )
        if execution_binding_path is not None:
            if execution_binding is None:
                raise ValueError("execution binding path requires immutable binding data")
            _write_json_exclusive(execution_binding_path, execution_binding)
        _write_json_atomic(run_dir / "started.json", started_record)
        if handshake_path is not None:
            _write_json_exclusive(handshake_path.resolve(), started_record)
        if on_started is not None:
            await on_started(dict(started_record))
        async with asyncio.timeout(timeout_seconds):
            result = await handle.result()
        chain_handle = client.get_workflow_handle(
            str(started_record["workflow_id"]),
            first_execution_run_id=str(started_record["first_execution_run_id"]),
        )
        description = await chain_handle.describe(
            rpc_timeout=timedelta(seconds=CANCEL_RPC_TIMEOUT_SECONDS)
        )
        observed_first_run_id = str(
            getattr(getattr(description, "raw_info", None), "first_run_id", "")
            or ""
        )
        if observed_first_run_id != str(started_record["first_execution_run_id"]):
            raise TransactionIdentityConflict(
                "completed workflow description does not match the bound execution chain"
            )
        return result, description
    except BaseException as exc:
        cancel_outcome: dict[str, object] = {
            "workflow_cancel_attempted": False,
            "workflow_cancel_requested": False,
            "workflow_terminal_confirmed": False,
            "workflow_cancel_confirmed": False,
            "workflow_cancel_terminal_status": "",
            "workflow_cancel_error_type": "",
            "workflow_cancel_chain_identity_ok": False,
        }
        if handle is not None:
            cancel_outcome["workflow_cancel_attempted"] = True
            cancellation_handle = client.get_workflow_handle(
                str(started_record["workflow_id"]),
                first_execution_run_id=str(started_record["first_execution_run_id"]),
            )
            cleanup_task = asyncio.create_task(
                _cancel_exact_workflow(
                    cancellation_handle,
                    expected_first_execution_run_id=str(
                        started_record["first_execution_run_id"]
                    ),
                )
            )
            try:
                try:
                    cancel_outcome = await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    # The cleanup task owns its own bounded deadline and remains
                    # strongly referenced even if a second caller cancellation arrives.
                    cancel_outcome = await cleanup_task
            except BaseException as cleanup_exc:
                cancel_outcome["workflow_cancel_error_type"] = type(cleanup_exc).__name__
        aborted = {
            "schema_version": "xinao.canonical_grok_transaction.aborted.v1",
            "aborted_at": datetime.now(UTC).isoformat(),
            "reason": type(exc).__name__,
            "task_id": started_record.get("task_id"),
            "workflow_id": started_record.get("workflow_id"),
            "run_id": started_record.get("run_id"),
            "first_execution_run_id": started_record.get("first_execution_run_id"),
            "task_queue": started_record.get("task_queue"),
            "attempt_id": started_record.get("attempt_id"),
            **cancel_outcome,
        }
        with suppress(Exception):
            _write_json_atomic(run_dir / "aborted.json", aborted)
        raise


async def run(
    *,
    payload_path: Path,
    db: Path,
    run_root: Path,
    timeout_seconds: float,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    host_task_queue: str = CANONICAL_HOST_QUEUE,
    langgraph_task_queue: str = CANONICAL_LANGGRAPH_QUEUE,
    worker_deployment_name: str = "",
    task_queue: str = "",
    transaction_key: str = "",
    handshake_path: Path | None = None,
    handshake_nonce: str = "",
    on_started: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    resume_workflow_id: str = "",
    resume_run_id: str = "",
    resume_first_execution_run_id: str = "",
    resume_task_queue: str = "",
    resume_task_id: str = "",
) -> dict[str, Any]:
    payload_path = payload_path.resolve()
    payload_raw = payload_path.read_bytes()
    payload_sha256 = _sha256(payload_raw)
    payload = _read_payload(
        payload_raw,
        runtime_root=runtime_root,
        langgraph_task_queue=langgraph_task_queue,
    )
    if handshake_path is not None:
        if not handshake_nonce.strip():
            raise ValueError("handshake path requires a caller-generated nonce")
        if handshake_path.resolve().exists():
            raise FileExistsError(f"handshake path already exists: {handshake_path.resolve()}")
    stable_key = transaction_key.strip()
    suffix = (
        f"key-{_sha256(stable_key.encode('utf-8'))[:20]}"
        if stable_key
        else f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    )
    queue = (
        resume_task_queue.strip()
        or task_queue.strip()
        or host_task_queue.strip()
        or CANONICAL_HOST_QUEUE
    )
    workflow_id = str(payload.get("workflow_id") or f"xinao-canonical-grok-{suffix}")
    payload["workflow_id"] = workflow_id
    payload.setdefault("task_id", f"canonical-grok-{suffix}")
    payload.setdefault("generation", 0)
    payload.setdefault("immutable_intent_hash", payload_sha256)
    payload.setdefault("owner", "codex")
    payload.setdefault("decision_hash", str(payload["immutable_intent_hash"]))
    payload.setdefault("promoted_only", True)
    correlation_id = str(payload.get("correlation_id") or "").strip()
    parent_operation_id = str(payload.get("parent_operation_id") or payload.get("operation_id") or "").strip()
    if resume_workflow_id.strip() and (
        not resume_run_id.strip()
        or not resume_first_execution_run_id.strip()
        or not resume_task_queue.strip()
        or not resume_task_id.strip()
    ):
        raise ValueError(
            "resume requires workflow id, run id, first execution run id, task queue, and task id"
        )

    deployment = _load_verified_deployment()
    deployment_name = worker_deployment_name.strip() or str(deployment["deployment_name"])
    deployment_build_id = str(deployment["build_id"])
    transaction_identity = _build_transaction_identity(
        transaction_key=stable_key,
        payload_sha256=payload_sha256,
        payload=payload,
        task_queue=queue,
        langgraph_task_queue=langgraph_task_queue,
        deployment_name=deployment_name,
        deployment_build_id=deployment_build_id,
        runtime_root=runtime_root,
        db_path=db,
        resume_workflow_id=resume_workflow_id,
        resume_run_id=resume_run_id,
        resume_first_execution_run_id=resume_first_execution_run_id,
        resume_task_id=resume_task_id,
    )

    with _transaction_attempt(
        run_root=run_root,
        suffix=suffix,
        transaction_key=stable_key,
        identity=transaction_identity,
    ) as transaction:
        run_dir = transaction.run_dir
        phase = "attempt_created"
        started_record: dict[str, Any] | None = None
        try:
            environment = {
                "XINAO_COORD_DB": str(db.resolve()),
                "XINAO_TEMPORAL_ENABLED": "1",
                "XINAO_TEMPORAL_MOCK": "0",
                "XINAO_TEMPORAL_LIVE": "1",
                "XINAO_TEMPORAL_ADDRESS": "127.0.0.1:7233",
                "XINAO_TEMPORAL_NAMESPACE": "default",
                "XINAO_TEMPORAL_TASK_QUEUE": queue,
                "XINAO_TEMPORAL_WORKER_VERSIONING": "1",
                "XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME": deployment_name,
                "XINAO_TEMPORAL_WORKER_BUILD_ID": deployment_build_id,
            }
            with _exclusive_process_environment(environment):
                phase = "environment_bound"
                service = CoordinationService(db.resolve())
                phase = "connecting_temporal"
                client = await Client.connect("127.0.0.1:7233", namespace="default")
                worker_identity = (
                    f"canonical-grok-one-shot@{suffix}:{transaction.attempt_id}"
                )
                phase = "building_worker"
                worker = build_promoted_worker(
                    client,
                    task_queue=queue,
                    workflows=PROMOTED_WORKFLOWS,
                    activities=PROMOTED_ACTIVITIES,
                    identity=worker_identity,
                )

                async with worker:
                    phase = "ensuring_deployment"
                    await ensure_deployment_current(
                        "127.0.0.1:7233",
                        deployment_name,
                        deployment_build_id,
                    )
                    execution_path = (
                        transaction.transaction_dir / "execution.json"
                        if stable_key
                        else None
                    )
                    existing_execution = (
                        _load_execution_binding(
                            execution_path,
                            transaction_identity_sha256=(
                                transaction.transaction_identity_sha256
                            ),
                            task_queue=queue,
                        )
                        if execution_path is not None and execution_path.exists()
                        else None
                    )
                    execution_reused = existing_execution is not None
                    fresh_execution_started = False
                    if existing_execution is not None:
                        phase = "reconnecting_exact_execution"
                        task_id = str(existing_execution["task_id"])
                        actual_workflow_id = str(existing_execution["workflow_id"])
                        run_id = str(existing_execution["run_id"])
                        first_execution_run_id = str(
                            existing_execution["first_execution_run_id"]
                        )
                    elif resume_workflow_id.strip():
                        phase = "binding_resumed_execution"
                        task_id = resume_task_id.strip()
                        actual_workflow_id = resume_workflow_id.strip()
                        run_id = resume_run_id.strip()
                        first_execution_run_id = resume_first_execution_run_id.strip()
                    else:
                        fresh_execution_started = True
                        phase = "creating_kernel_task"
                        task_id = create_kernel_backed_canary_task(
                            service,
                            payload,
                            seed=suffix,
                        )
                        phase = "starting_temporal_workflow"
                        started = await asyncio.to_thread(
                            service.temporal_start_promoted,
                            actor="codex",
                            task_id=task_id,
                            idempotency_key=(
                                f"canonical-grok-live-start:{stable_key}"
                                if stable_key
                                else f"canonical-grok-live-start-{suffix}"
                            ),
                        )
                        actual_workflow_id = str(started["workflow_id"])
                        run_id = str(started["run_id"])
                        first_execution_run_id = run_id
                    execution_binding = {
                        "schema_version": TRANSACTION_EXECUTION_VERSION,
                        "transaction_key_semantics": TRANSACTION_KEY_SEMANTICS,
                        "bound_at": datetime.now(UTC).isoformat(),
                        "task_id": task_id,
                        "workflow_id": actual_workflow_id,
                        "run_id": run_id,
                        "first_execution_run_id": first_execution_run_id,
                        "task_queue": queue,
                        "transaction_identity_sha256": (
                            transaction.transaction_identity_sha256
                        ),
                    }
                    started_record = {
                        "schema_version": "xinao.canonical_grok_transaction.started.v1",
                        "started_at": datetime.now(UTC).isoformat(),
                        "task_id": task_id,
                        "workflow_id": actual_workflow_id,
                        "run_id": run_id,
                        "first_execution_run_id": first_execution_run_id,
                        "task_queue": queue,
                        "worker_identity": worker_identity,
                        "attempt_id": transaction.attempt_id,
                        "run_dir": str(run_dir),
                        "transaction_dir": str(transaction.transaction_dir),
                        "transaction_identity_sha256": (
                            transaction.transaction_identity_sha256
                        ),
                        "transaction_key_sha256": transaction.transaction_key_sha256,
                        "execution_reused": execution_reused,
                    }
                    if handshake_nonce.strip():
                        started_record["handshake_nonce"] = handshake_nonce.strip()
                    if correlation_id:
                        started_record["correlation_id"] = correlation_id
                    if parent_operation_id:
                        started_record["parent_operation_id"] = parent_operation_id
                    phase = "observing_workflow"
                    result, description = await _observe_started_workflow(
                        client=client,
                        started_record=started_record,
                        run_dir=run_dir,
                        timeout_seconds=timeout_seconds,
                        handshake_path=handshake_path,
                        on_started=on_started,
                        execution_binding_path=(
                            execution_path if not execution_reused else None
                        ),
                        execution_binding=execution_binding,
                        resolve_first_execution_run_id=fresh_execution_started,
                    )

                phase = "validating_result"
                if not isinstance(result, dict):
                    raise TypeError("workflow result must be an object")
                # `_observe_started_workflow` resolves the authoritative chain root
                # from Temporal before it persists the execution binding.  A fresh
                # start may return a continued run id, so do not reuse the provisional
                # local value that existed before that describe.
                authoritative_first_execution_run_id = str(
                    started_record["first_execution_run_id"]
                )
                grok_fanin = result.get("grok_fanin")
                output = {
                    "ok": (
                        result.get("ok") is True
                        and result.get("terminal_status") == "completed"
                        and isinstance(grok_fanin, dict)
                        and grok_fanin.get("ok") is True
                    ),
                    "task_id": task_id,
                    "workflow_id": actual_workflow_id,
                    "run_id": run_id,
                    "first_execution_run_id": authoritative_first_execution_run_id,
                    "task_queue": queue,
                    "worker_identity": worker_identity,
                    "worker_deployment_name": deployment_name,
                    "worker_build_id": deployment_build_id,
                    "langgraph_task_queue": langgraph_task_queue,
                    "runtime_root": str(runtime_root.resolve()),
                    "requested_models": transaction_identity["requested_models"],
                    "payload_path": str(payload_path),
                    "payload_sha256": payload_sha256,
                    "workflow_status": description.status.name.lower(),
                    "attempt_id": transaction.attempt_id,
                    "run_dir": str(run_dir),
                    "transaction_dir": str(transaction.transaction_dir),
                    "transaction_identity_sha256": (
                        transaction.transaction_identity_sha256
                    ),
                    "transaction_key_sha256": transaction.transaction_key_sha256,
                    "transaction_key_semantics": TRANSACTION_KEY_SEMANTICS,
                    "execution_reused": execution_reused,
                    "result": result,
                }
                if correlation_id:
                    output["correlation_id"] = correlation_id
                if parent_operation_id:
                    output["parent_operation_id"] = parent_operation_id
                phase = "persisting_result"
                _write_json_atomic(run_dir / "result.json", output)
                phase = "result_persisted"
            _write_json_exclusive(
                run_dir / "attempt_outcome.json",
                _attempt_outcome(
                    transaction=transaction,
                    status="accepted" if output["ok"] else "rejected",
                    phase=phase,
                    started_record=started_record,
                ),
            )
            return output
        except BaseException as exc:
            cancellation: dict[str, Any] | None = None
            aborted_path = run_dir / "aborted.json"
            if aborted_path.exists():
                with suppress(Exception):
                    cancellation = _read_json_object(
                        aborted_path,
                        label="attempt cancellation receipt",
                    )
            with suppress(Exception):
                _write_json_exclusive(
                    run_dir / "attempt_outcome.json",
                    _attempt_outcome(
                        transaction=transaction,
                        status="failed",
                        phase=phase,
                        error_type=type(exc).__name__,
                        started_record=started_record,
                        cancellation=cancellation,
                    ),
                )
            raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--timeout-seconds", type=float, default=1_800)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--host-task-queue", default=CANONICAL_HOST_QUEUE)
    parser.add_argument("--langgraph-task-queue", default=CANONICAL_LANGGRAPH_QUEUE)
    parser.add_argument("--worker-deployment-name", default="")
    parser.add_argument("--task-queue", default="")
    parser.add_argument("--transaction-key", default="")
    parser.add_argument("--handshake-path", type=Path)
    parser.add_argument("--handshake-nonce", default="")
    parser.add_argument("--resume-workflow-id", default="")
    parser.add_argument("--resume-run-id", default="")
    parser.add_argument("--resume-first-execution-run-id", default="")
    parser.add_argument("--resume-task-queue", default="")
    parser.add_argument("--resume-task-id", default="")
    args = parser.parse_args()
    output = asyncio.run(
        run(
            payload_path=args.payload,
            db=args.db,
            run_root=args.run_root,
            timeout_seconds=args.timeout_seconds,
            runtime_root=args.runtime_root,
            host_task_queue=args.host_task_queue,
            langgraph_task_queue=args.langgraph_task_queue,
            worker_deployment_name=args.worker_deployment_name,
            task_queue=args.task_queue,
            transaction_key=args.transaction_key,
            handshake_path=args.handshake_path,
            handshake_nonce=args.handshake_nonce,
            resume_workflow_id=args.resume_workflow_id,
            resume_run_id=args.resume_run_id,
            resume_first_execution_run_id=args.resume_first_execution_run_id,
            resume_task_queue=args.resume_task_queue,
            resume_task_id=args.resume_task_id,
        )
    )
    print(
        json.dumps(
            {
                key: output[key]
                for key in (
                    "ok",
                    "task_id",
                    "workflow_id",
                    "run_id",
                    "attempt_id",
                    "run_dir",
                    "transaction_dir",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
