from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import run_foundation_v2_f4_live_canary as subject
from scripts.build_grok_docker_identity_payload import compile_identity_payload
from services.agent_runtime import foundation_continuous_workflow_v2 as controller


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _bound_attempt(
    tmp_path: Path,
    *,
    attempt_id: str = "attempt-0002",
    execution_reused: bool = True,
) -> tuple[Path, Path, str, str, dict[str, Any], dict[str, Path]]:
    transaction_key = "f" * 64
    payload_sha256 = "a" * 64
    nonce = "nonce-a"
    key_sha256 = hashlib.sha256(transaction_key.encode()).hexdigest()
    root = (tmp_path / "runs").resolve()
    transaction_dir = root / f"canonical-grok-key-{key_sha256[:20]}"
    run_dir = transaction_dir / "attempts" / attempt_id
    run_dir.mkdir(parents=True)
    identity_path = _write(
        transaction_dir / "identity.json",
        {
            "schema_version": "xinao.canonical_grok_transaction.identity.v1",
            "transaction_key_semantics": subject.TRANSACTION_KEY_SEMANTICS,
            "transaction_key_sha256": key_sha256,
            "payload_sha256": payload_sha256,
            "task_queue": "queue-a",
        },
    )
    identity_sha256 = subject.file_sha256(identity_path)
    execution = {
        "schema_version": "xinao.canonical_grok_transaction.execution.v1",
        "transaction_key_semantics": subject.TRANSACTION_KEY_SEMANTICS,
        "transaction_identity_sha256": identity_sha256,
        "task_queue": "queue-a",
        "task_id": "task-a",
        "workflow_id": "workflow-a",
        "run_id": "bound-run-a",
        "first_execution_run_id": "root-run-a",
    }
    _write(transaction_dir / "execution.json", execution)
    _write(
        run_dir / "attempt.json",
        {
            "schema_version": "xinao.canonical_grok_transaction.attempt.v1",
            "attempt_id": attempt_id,
            "transaction_identity_sha256": identity_sha256,
            "transaction_key_sha256": key_sha256,
        },
    )
    started = {
        "schema_version": "xinao.canonical_grok_transaction.started.v1",
        **{
            key: execution[key]
            for key in (
                "task_id",
                "workflow_id",
                "run_id",
                "first_execution_run_id",
                "task_queue",
            )
        },
        "attempt_id": attempt_id,
        "run_dir": str(run_dir),
        "transaction_dir": str(transaction_dir),
        "transaction_identity_sha256": identity_sha256,
        "transaction_key_sha256": key_sha256,
        "execution_reused": execution_reused,
        "handshake_nonce": nonce,
    }
    handshake = _write(tmp_path / "bridge" / "handshake.json", started)
    validated, paths = subject._validate_started_handshake(
        handshake,
        expected_nonce=nonce,
        expected_queue="queue-a",
        transaction_key=transaction_key,
        expected_payload_sha256=payload_sha256,
        external_run_root=root,
    )
    return handshake, root, transaction_key, payload_sha256, validated, paths


def test_prepare_handshake_is_unique_and_does_not_precreate_file(tmp_path: Path) -> None:
    first_path, first_nonce = subject._prepare_handshake(tmp_path, "a" * 64)
    second_path, second_nonce = subject._prepare_handshake(tmp_path, "a" * 64)

    assert first_path != second_path
    assert first_nonce != second_nonce
    assert not first_path.exists()
    assert not second_path.exists()


def test_f4_structured_schema_binds_computed_method_evidence() -> None:
    from jsonschema import ValidationError, validate

    work_key = "a" * 52 + "123456789abc"
    binding = {
        "method_admission_hash": "b" * 64,
        "method_executable_ref": r"D:\evidence\method.json",
        "method_executable_sha256": "c" * 64,
        "method_material_bundle_sha256": "d" * 64,
    }
    method_input = {
        "upstream": {
            "producer_ref": "",
            "producer_sha256": "",
            "critique_ref": "",
            "critique_sha256": "",
        }
    }
    schema = controller._f4_lane_result_json_schema(
        stage="PRODUCER",
        lane_id="producer-a",
        work_key=work_key,
        method_binding=binding,
        method_input=method_input,
        method_input_sha256="e" * 64,
    )
    result = {
        "work_key": work_key,
        "producer_id": "producer-a",
        "status": "VERIFIED",
        "claim_refs": ["claim:a"],
        **binding,
        "method_input_sha256": "e" * 64,
        "method_output": {
            "applied": True,
            "stage": "PRODUCER",
            "work_key": work_key,
            "method_evidence": "F4_EVIDENCE_BOUND_CANARY:PRODUCER:123456789abc",
        },
    }

    validate(result, schema)
    result["method_output"]["method_evidence"] = "F4_EVIDENCE_BOUND_CANARY:PRODUCER:023456789abc"
    with pytest.raises(ValidationError):
        validate(result, schema)


def test_f4_external_worker_cwd_must_be_explicit_and_existing(tmp_path: Path) -> None:
    assert controller._external_worker_cwd(
        {"external_worker_cwd": str(tmp_path)}
    ) == str(tmp_path.resolve())

    with pytest.raises(ValueError, match="explicit supervisor-selected"):
        controller._external_worker_cwd({})
    with pytest.raises(ValueError, match="does not exist"):
        controller._external_worker_cwd(
            {"external_worker_cwd": str(tmp_path / "missing")}
        )


def _composer_fanin_identity() -> dict[str, Any]:
    selected = "grok-composer-2.5-fast"
    backend = controller.expected_docker_grok_backend_models(selected)
    return {
        "model": selected,
        "model_identity_ok": True,
        "model_identity_binding": controller.grok_docker_model_identity_binding(selected),
        "observed_model": backend[0],
        "observed_models": backend,
        "observed_backend_models": backend,
    }


def test_f4_external_fanin_keeps_session_selector_and_backend_identity_distinct() -> None:
    controller._verify_external_fanin_model_identity(
        _composer_fanin_identity(),
        expected_model="grok-composer-2.5-fast",
    )


def test_live_report_requires_selected_session_backend_and_binding() -> None:
    fanin = _composer_fanin_identity()
    receipt = {
        "selected_model": fanin["model"],
        "observed_model": fanin["observed_model"],
        "observed_backend_models": fanin["observed_backend_models"],
        "model_identity_binding": fanin["model_identity_binding"],
    }

    assert subject.live_receipt_model_identity_checks([receipt]) == {
        "selected_session_model": True,
        "observed_backend_model": True,
        "model_identity_binding": True,
    }


@pytest.mark.parametrize(
    ("field", "value", "failed_check"),
    (
        ("selected_model", "grok-4.5", "selected_session_model"),
        ("observed_model", "grok-composer-2.5-fast", "observed_backend_model"),
        ("observed_backend_models", ["grok-4.5"], "observed_backend_model"),
        ("model_identity_binding", {}, "model_identity_binding"),
    ),
)
def test_live_report_rejects_each_model_identity_layer_drift(
    field: str,
    value: object,
    failed_check: str,
) -> None:
    fanin = _composer_fanin_identity()
    receipt = {
        "selected_model": fanin["model"],
        "observed_model": fanin["observed_model"],
        "observed_backend_models": fanin["observed_backend_models"],
        "model_identity_binding": fanin["model_identity_binding"],
    }
    receipt[field] = value

    checks = subject.live_receipt_model_identity_checks([receipt])

    assert checks[failed_check] is False


def test_identity_probe_rebinds_all_supervisor_selected_model_fields() -> None:
    source = {
        "operation_id": "old",
        "grok_ready_frontier": [{"lane_id": "lane-1", "model": "old"}],
        "lane_bindings": {"lane-1": {"requested_model": "old"}},
        "supervisor_routing": {
            "candidates": [{"model_id": "old"}],
            "supervisor_choice": {"model_id": "old"},
        },
        "supervisor_worker_decision": {"decision_sha256": "stale"},
    }

    compiled = compile_identity_payload(source, model="grok-4.5", operation_id="probe-1")

    assert compiled["operation_id"] == compiled["parent_operation_id"] == "probe-1"
    assert compiled["grok_ready_frontier"][0]["model"] == "grok-4.5"
    assert compiled["lane_bindings"]["lane-1"]["requested_model"] == "grok-4.5"
    assert compiled["supervisor_routing"]["candidates"][0]["model_id"] == "grok-4.5"
    assert compiled["supervisor_routing"]["supervisor_choice"]["model_id"] == "grok-4.5"
    assert "supervisor_worker_decision" not in compiled


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("model", "grok-4.5"),
        ("model_identity_ok", False),
        ("model_identity_binding", {}),
        ("observed_model", "grok-composer-2.5-fast"),
        ("observed_models", ["grok-composer-2.5-fast"]),
        ("observed_backend_models", ["grok-composer-2.5-fast"]),
    ),
)
def test_f4_external_fanin_rejects_any_identity_layer_drift(
    field: str,
    value: object,
) -> None:
    fanin = _composer_fanin_identity()
    fanin[field] = value

    with pytest.raises(ValueError, match="identity does not match dispatch"):
        controller._verify_external_fanin_model_identity(
            fanin,
            expected_model="grok-composer-2.5-fast",
        )


def test_process_until_closed_serves_bounded_compensation_wave(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[int] = []

    async def fake_process(*args: object, **kwargs: object) -> dict[str, Any]:
        calls.append(len(calls) + 1)
        return {"request": calls[-1]}

    async def fake_settle(*args: object, **kwargs: object) -> tuple[dict[str, Any], bool]:
        closed = len(calls) == 4
        return (
            {
                "closed_work_keys": ["one"] if closed else [],
                "batch_stage": "IDLE" if closed else "PRODUCER",
                "current_wave": None if closed else {"wave": len(calls)},
            },
            closed,
        )

    monkeypatch.setattr(subject, "process_one_wave", fake_process)
    monkeypatch.setattr(subject, "_wait_for_closed_or_next_request", fake_settle)
    receipts, state = asyncio.run(
        subject._process_until_closed(
            object(),
            object(),
            expected_closed=1,
            minimum_requests=3,
            max_requests=5,
            pack=tmp_path,
            request_root=tmp_path,
            processed=set(),
            external_queue="queue",
            db_path=tmp_path / "db.sqlite3",
            external_run_root=tmp_path / "runs",
            expected_deployment={},
        )
    )

    assert calls == [1, 2, 3, 4]
    assert [item["request"] for item in receipts] == calls
    assert state["closed_work_keys"] == ["one"]


def test_attempt_0002_reconnect_is_accepted_but_stale_nonce_is_rejected(
    tmp_path: Path,
) -> None:
    handshake, root, key, payload_hash, started, paths = _bound_attempt(tmp_path)

    assert started["attempt_id"] == "attempt-0002"
    assert started["execution_reused"] is True
    assert paths["result_path"] == Path(started["run_dir"]) / "result.json"
    with pytest.raises(ValueError, match="nonce mismatch"):
        subject._validate_started_handshake(
            handshake,
            expected_nonce="stale-nonce",
            expected_queue="queue-a",
            transaction_key=key,
            expected_payload_sha256=payload_hash,
            external_run_root=root,
        )


def test_transaction_identity_tamper_is_rejected(tmp_path: Path) -> None:
    handshake, root, key, payload_hash, _, _ = _bound_attempt(tmp_path)
    started = json.loads(handshake.read_text(encoding="utf-8"))
    identity_path = Path(started["transaction_dir"]) / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["payload_sha256"] = "0" * 64
    _write(identity_path, identity)

    with pytest.raises(ValueError, match="identity hash mismatch"):
        subject._validate_started_handshake(
            handshake,
            expected_nonce="nonce-a",
            expected_queue="queue-a",
            transaction_key=key,
            expected_payload_sha256=payload_hash,
            external_run_root=root,
        )


class _ExitedProcess:
    returncode = 17


def test_child_exit_before_handshake_fails_immediately(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="exited before handshake"):
        asyncio.run(
            subject._wait_for_handshake_or_exit(  # type: ignore[arg-type]
                _ExitedProcess(),
                tmp_path / "missing.json",
                timeout_seconds=1,
            )
        )


class _Handle:
    def __init__(
        self,
        events: list[str],
        *,
        status: str = "RUNNING",
        first_run_id: str = "root-run-a",
        terminal_run_id: str = "terminal-run-b",
        cancel_changes_status: bool = True,
        history: object | None = None,
    ) -> None:
        self.events = events
        self.status = status
        self.first_run_id = first_run_id
        self.terminal_run_id = terminal_run_id
        self.cancel_changes_status = cancel_changes_status
        self.history = history

    async def cancel(self, **_: object) -> None:
        self.events.append("cancel")
        if self.cancel_changes_status:
            self.status = "CANCELED"

    async def describe(self, **_: object) -> object:
        return SimpleNamespace(
            status=SimpleNamespace(name=self.status),
            raw_info=SimpleNamespace(
                first_run_id=self.first_run_id,
                execution=SimpleNamespace(run_id=self.terminal_run_id),
            ),
        )

    async def fetch_history(self) -> object:
        self.events.append("history")
        return self.history


class _Client:
    def __init__(self, chain: _Handle, terminal: _Handle | None = None) -> None:
        self.chain = chain
        self.terminal = terminal or chain
        self.requests: list[tuple[str, str | None, str | None]] = []

    def get_workflow_handle(
        self,
        workflow_id: str,
        *,
        run_id: str | None = None,
        first_execution_run_id: str | None = None,
    ) -> _Handle:
        self.requests.append((workflow_id, run_id, first_execution_run_id))
        return self.terminal if run_id else self.chain


class _HungProcess:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.returncode: int | None = None
        self._stopped = asyncio.Event()

    async def wait(self) -> int:
        await self._stopped.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.events.append("terminate")
        self.returncode = -15
        self._stopped.set()

    def kill(self) -> None:
        self.events.append("kill")
        self.returncode = -9
        self._stopped.set()


def test_timeout_cleanup_cancels_and_confirms_terminal_before_process_stop() -> None:
    async def exercise() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        events: list[str] = []
        started = {
            "workflow_id": "workflow-a",
            "first_execution_run_id": "root-run-a",
        }
        cleanup = await subject._cancel_exact_chain(
            _Client(_Handle(events)),  # type: ignore[arg-type]
            started,
            timeout_seconds=1,
        )
        process_result = await subject._stop_process_after_cleanup(
            _HungProcess(events),  # type: ignore[arg-type]
            cleanup=cleanup,
            grace_seconds=0.01,
        )
        return cleanup, process_result, events

    cleanup, process_result, events = asyncio.run(exercise())
    assert cleanup["workflow_terminal_confirmed"] is True
    assert cleanup["workflow_cancel_confirmed"] is True
    assert process_result["temporal_terminal_confirmed_before_process_stop"] is True
    assert events.index("cancel") < events.index("terminate")


def test_completed_cancel_race_is_terminal_but_not_cancel_confirmed() -> None:
    events: list[str] = []
    result = asyncio.run(
        subject._cancel_exact_chain(
            _Client(
                _Handle(
                    events,
                    status="COMPLETED",
                    cancel_changes_status=False,
                )
            ),  # type: ignore[arg-type]
            {
                "workflow_id": "workflow-a",
                "first_execution_run_id": "root-run-a",
            },
            timeout_seconds=1,
        )
    )
    assert result["workflow_terminal_confirmed"] is True
    assert result["workflow_cancel_confirmed"] is False
    assert result["workflow_cancel_terminal_status"] == "COMPLETED"


def test_parent_failure_is_terminal_confirmed_while_worker_is_still_active(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    outcome = asyncio.run(
        subject._cancel_parent_before_worker_exit(
            _Handle(events),  # type: ignore[arg-type]
            pack=tmp_path,
            phase="worker-a-failure",
            timeout_seconds=1,
        )
    )

    assert events == ["cancel"]
    assert outcome["terminal_confirmed"] is True
    assert outcome["terminal_status"] == "CANCELED"
    persisted = json.loads(
        (tmp_path / "worker_cleanup" / "worker-a-failure.json").read_text(encoding="utf-8")
    )
    assert persisted == outcome


def test_wrong_first_run_id_fails_closed() -> None:
    result = asyncio.run(
        subject._cancel_exact_chain(
            _Client(_Handle([], first_run_id="wrong-root")),  # type: ignore[arg-type]
            {
                "workflow_id": "workflow-a",
                "first_execution_run_id": "root-run-a",
            },
            timeout_seconds=1,
        )
    )
    assert result["workflow_terminal_confirmed"] is False
    assert result["workflow_cancel_chain_identity_ok"] is False
    assert result["workflow_cancel_error_type"] == "WorkflowChainIdentityMismatch"


def test_continue_as_new_history_uses_terminal_run_and_chain_root() -> None:
    events: list[str] = []
    history = object()
    chain = _Handle(events, status="COMPLETED")
    terminal = _Handle(events, status="COMPLETED", history=history)
    client = _Client(chain, terminal)

    observed_history, terminal_run_id = asyncio.run(
        subject._describe_and_fetch_terminal_history(
            client,  # type: ignore[arg-type]
            {
                "workflow_id": "workflow-a",
                "run_id": "bound-run-a",
                "first_execution_run_id": "root-run-a",
            },
        )
    )

    assert observed_history is history
    assert terminal_run_id == "terminal-run-b"
    assert client.requests == [
        ("workflow-a", None, "root-run-a"),
        ("workflow-a", "terminal-run-b", "root-run-a"),
    ]


def test_result_envelope_and_attempt_outcome_are_both_hash_bound(tmp_path: Path) -> None:
    _, _, _, payload_hash, started, paths = _bound_attempt(tmp_path)
    deployment = {"deployment_name": "deployment-a", "build_id": "build-a"}
    result = {
        "ok": True,
        "payload_sha256": payload_hash,
        "task_queue": started["task_queue"],
        "task_id": started["task_id"],
        "workflow_id": started["workflow_id"],
        "run_id": started["run_id"],
        "first_execution_run_id": started["first_execution_run_id"],
        "attempt_id": started["attempt_id"],
        "run_dir": str(paths["run_dir"]),
        "transaction_dir": str(paths["transaction_dir"]),
        "transaction_identity_sha256": started["transaction_identity_sha256"],
        "transaction_key_sha256": started["transaction_key_sha256"],
        "transaction_key_semantics": subject.TRANSACTION_KEY_SEMANTICS,
        "execution_reused": started["execution_reused"],
        "worker_deployment_name": deployment["deployment_name"],
        "worker_build_id": deployment["build_id"],
    }
    _write(paths["result_path"], result)
    _write(
        paths["attempt_outcome_path"],
        {
            "schema_version": "xinao.canonical_grok_transaction.attempt_outcome.v1",
            "status": "accepted",
            "attempt_id": started["attempt_id"],
            "transaction_identity_sha256": started["transaction_identity_sha256"],
            "transaction_key_sha256": started["transaction_key_sha256"],
            "transaction_key_semantics": subject.TRANSACTION_KEY_SEMANTICS,
            "workflow_id": started["workflow_id"],
            "first_execution_run_id": started["first_execution_run_id"],
        },
    )
    accepted, _ = subject._validate_result_envelope(
        paths["result_path"],
        started=started,
        paths=paths,
        request={"payload_sha256": payload_hash},
        external_queue="queue-a",
        expected_deployment=deployment,
    )
    assert accepted["attempt_id"] == "attempt-0002"

    result["first_execution_run_id"] = "tampered"
    _write(paths["result_path"], result)
    with pytest.raises(ValueError, match="result envelope"):
        subject._validate_result_envelope(
            paths["result_path"],
            started=started,
            paths=paths,
            request={"payload_sha256": payload_hash},
            external_queue="queue-a",
            expected_deployment=deployment,
        )
