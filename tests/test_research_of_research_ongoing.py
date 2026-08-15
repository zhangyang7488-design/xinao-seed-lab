from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from services.research_of_research import ongoing


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _contract_fixture(tmp_path: Path, **overrides: object) -> tuple[Path, dict[str, Any]]:
    source_root = tmp_path / "current-reality"
    source_root.mkdir(parents=True)
    (source_root / "chronology.md").write_bytes(b"first exact reality slice\n")
    source_repo = tmp_path / "clean-room-repo"
    source_repo.mkdir()
    (source_repo / ".git").mkdir()
    launcher = tmp_path / "isolated-launcher.ps1"
    launcher.write_bytes(
        b"# fake isolated launcher; never executed\n"
        b'Write-Host "CODEX $AccountSlot | one shared clean-room runtime | credential $AccountSlot" -ForegroundColor Cyan\n'
        b'Write-Host "SHARED_RUNTIME=$canonicalCodexHome"\n'
        b'Write-Host "CODEX_HOME=$codexHome"\n'
        b'Write-Host "WORKDIR=$launchWorkdir"\n'
        b'Write-Host "MODEL=gpt-5.6-sol"\n'
        b"Write-Host \"AUTH=$(if ($hasAuth) { 'present (clean-room carrier)' } else { 'missing - login required' })\"\n"
        b'Write-Host ""\n'
        b"& $codexExe --cd $launchWorkdir --sandbox workspace-write "
        b"-c 'approval_policy=\"never\"' "
        b"-c 'sandbox_workspace_write.network_access=true' "
        b"@slotSpecificCodexArgs @CodexArgs\n"
    )
    powershell = tmp_path / "pwsh.exe"
    powershell.write_bytes(b"fake powershell; never executed\n")
    appointment = tmp_path / "current-human-appointment.txt"
    appointment.write_bytes(b"Adopt this candidate-only ongoing research contract.\n")
    contract: dict[str, Any] = {
        "schema": "xinao.research-of-research.ongoing-contract.v2",
        "human_appointment": {
            "source_path": str(appointment.resolve()),
            "source_sha256": _sha256(appointment.read_bytes()),
            "quoted_words": "Adopt this candidate-only ongoing research contract.",
        },
        "evidence_frame": {
            "source_groups": [
                {
                    "name": "chronology",
                    "root": str(source_root.resolve()),
                    "glob_patterns": ["**/*.md"],
                    "exact_files": [],
                }
            ],
            "coverage_claim": "CONTRACT_SELECTED_PARTIAL",
            "snapshot_atomicity": "PER_FILE_STABLE_NO_GLOBAL_ATOMICITY",
            "instruction_authority": False,
            "cognition_authority": False,
        },
        "wake_policy": {
            "activation": True,
            "continuation_observations": True,
            "inventory_changes": True,
            "minimum_repeat_delay_seconds": 60,
            "continuation_observation_eligibility": dict(ongoing._DEFAULT_OBSERVATION_ELIGIBILITY),
        },
        "carrier": {
            "clean_room": {
                "source_repo": str(source_repo.resolve()),
                "launcher_path": str(launcher.resolve()),
                "powershell_path": str(powershell.resolve()),
                "workspace_root": str((tmp_path / "workspaces").resolve()),
            },
            "account_order": ["A", "C"],
            "physical_quota_limit": 4,
            "model": "gpt-5.6-sol",
            "model_reasoning_effort": "high",
            "timeout_seconds": 30,
        },
    }
    for key, value in overrides.items():
        if key in {
            "clean_room",
            "account_order",
            "physical_quota_limit",
            "model",
            "model_reasoning_effort",
            "timeout_seconds",
        }:
            contract["carrier"][key] = value
        elif key == "minimum_continuation_delay_seconds":
            contract["wake_policy"]["minimum_repeat_delay_seconds"] = value
        elif key == "continuation_observation_eligibility":
            contract["wake_policy"]["continuation_observation_eligibility"] = value
        elif key == "source_groups":
            contract["evidence_frame"]["source_groups"] = value
        else:
            contract[key] = value
    contract_path = tmp_path / "ongoing-contract.json"
    _write_json(contract_path, contract)
    return contract_path, contract


def test_capacity_claim_retries_transient_shared_admission_lock_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[tuple[str, bool]] = []
    sleeps: list[float] = []

    class ContendedQuota:
        def __init__(
            self,
            *,
            account_slot: str,
            quota_root: Path,
            limit: int,
            run_id: str,
            reclaim_bound_leases: bool,
        ) -> None:
            assert quota_root == ongoing.DEFAULT_QUOTA_ROOT
            assert limit == 4
            assert run_id == "attempt-id"
            assert reclaim_bound_leases is False
            self.account_slot = account_slot

        def try_claim_outcome(self, *, lineage_id: str, workspace: Path) -> dict[str, Any]:
            assert lineage_id == "opportunity-id"
            assert workspace == tmp_path / "workspace"
            attempts.append((self.account_slot, False))
            if self.account_slot == "C" and len(attempts) >= 5:
                return {
                    "outcome": "CLAIMED",
                    "lease": {
                        "account_slot": "C",
                        "slot": 2,
                        "lease_id": "exact-lease",
                    },
                }
            return {"outcome": "LOCK_BUSY"}

    monkeypatch.setattr(ongoing, "AccountQuota", ContendedQuota)
    clock = iter((0.0, 0.1, 0.2, 0.3))
    monkeypatch.setattr(ongoing, "_CAPACITY_ADMISSION_LOCK_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(ongoing, "_CAPACITY_ADMISSION_RETRY_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(ongoing.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(ongoing.time, "sleep", sleeps.append)

    result = ongoing._claim_capacity(
        {"account_order": ["C", "A"]},
        attempt_id="attempt-id",
        opportunity_id="opportunity-id",
        workspace=tmp_path / "workspace",
    )

    assert result["outcome"] == "CLAIMED"
    assert result["lease"]["account_slot"] == "C"
    assert result["quota"].account_slot == "C"
    assert attempts == [("C", False), ("A", False), ("C", False), ("A", False), ("C", False)]
    assert sleeps == [0.01, 0.01]


def test_capacity_lock_timeout_is_unknown_not_capacity_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class LockedQuota:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def try_claim_outcome(self, **_kwargs: object) -> dict[str, str]:
            return {"outcome": "LOCK_BUSY"}

    monkeypatch.setattr(ongoing, "AccountQuota", LockedQuota)
    monkeypatch.setattr(ongoing, "_CAPACITY_ADMISSION_LOCK_TIMEOUT_SECONDS", 0.0)

    result = ongoing._claim_capacity(
        {"account_order": ["C"]},
        attempt_id="attempt-id",
        opportunity_id="opportunity-id",
        workspace=tmp_path / "workspace",
    )

    assert result["outcome"] == "UNKNOWN"
    assert result["reason_code"] == "COMPUTE_UNKNOWN"
    assert result["detail"] == ["C:QUOTA_ADMISSION_LOCK_TIMEOUT"]


@pytest.mark.skipif(os.name != "nt", reason="exercises the live Windows byte-lock contract")
def test_capacity_claim_waits_through_a_real_cross_process_byte_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota_root = tmp_path / "quota"
    lock_path = quota_root / "C" / "admission.lock"
    ready_path = tmp_path / "holder-ready"
    holder_path = tmp_path / "hold-byte-lock.py"
    holder_path.write_text(
        """from pathlib import Path
import msvcrt
import os
import sys
import time

lock_path = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
lock_path.parent.mkdir(parents=True, exist_ok=True)
with lock_path.open("a+b") as handle:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    ready_path.write_text("LOCKED", encoding="utf-8")
    time.sleep(0.4)
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
""",
        encoding="utf-8",
    )
    holder = subprocess.Popen(
        [sys.executable, str(holder_path), str(lock_path), str(ready_path)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        ready_deadline = time.monotonic() + 5.0
        while not ready_path.is_file() and time.monotonic() < ready_deadline:
            time.sleep(0.01)
        assert ready_path.read_text(encoding="utf-8") == "LOCKED"
        monkeypatch.setattr(ongoing, "DEFAULT_QUOTA_ROOT", quota_root)
        monkeypatch.setattr(ongoing, "_CAPACITY_ADMISSION_LOCK_TIMEOUT_SECONDS", 2.0)

        result = ongoing._claim_capacity(
            {"account_order": ["C"]},
            attempt_id="attempt-id",
            opportunity_id="opportunity-id",
            workspace=tmp_path / "workspace",
        )

        assert result["outcome"] == "CLAIMED"
        assert result["lease"]["account_slot"] == "C"
        assert result["lease"]["status"] == "RESERVED"
        holder.wait(timeout=5)
        assert result["quota"].release(result["lease"]) == "RELEASED"
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5)


def _candidate_final(
    *,
    disposition: str = "WAIT",
    settlement_kind: str = "SAFE_HELD_OUT_RESEARCH",
) -> dict[str, Any]:
    del disposition, settlement_kind
    return {
        "payload": "CANDIDATE_ONLY\nA bounded candidate grounded in the frozen evidence frame.",
        "authority": False,
        "shared_effect_authorized": False,
        "completion_claim_allowed": False,
    }


def _jsonl_events(final: object, *, thread_id: str = "thread-fixture") -> str:
    rows = [
        {"type": "thread.started", "thread_id": thread_id},
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": json.dumps(final, ensure_ascii=False),
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
    ]
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


class _FakeProcess:
    next_pid = 9100

    def __init__(
        self,
        calls: list[dict[str, Any]],
        stdout_text: str,
        final: object,
        command: list[str],
        **kwargs: object,
    ) -> None:
        self.pid = type(self).next_pid
        type(self).next_pid += 1
        self.returncode: int | None = 0
        self._stdout_text = stdout_text
        self.terminated = False
        self.killed = False
        self.communicated_input: str | bytes | None = None
        self.communicate_timeout: float | None = None
        self.stdin = io.BytesIO()
        calls.append({"command": list(command), "kwargs": dict(kwargs), "process": self})
        args_path = Path(command[command.index("-CodexArgsFile") + 1])
        codex_args = json.loads(args_path.read_text(encoding="utf-8"))
        assert isinstance(codex_args, list)
        output_path = Path(codex_args[codex_args.index("-o") + 1])
        output_path.write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        stdout = kwargs.get("stdout")
        if stdout is not None:
            stdout.write(stdout_text.encode("utf-8"))
            stdout.flush()

    def communicate(
        self, input: str | bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        self.communicated_input = input
        self.communicate_timeout = timeout
        return self._stdout_text.encode("utf-8"), b""

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1

    def kill(self) -> None:
        self.killed = True
        self.returncode = 1


def _popen_factory(calls: list[dict[str, Any]], final: object) -> Any:
    stdout_text = _jsonl_events(final)

    def factory(command: list[str], **kwargs: object) -> _FakeProcess:
        return _FakeProcess(calls, stdout_text, final, command, **kwargs)

    return factory


def _job_snapshot(
    attempt_id: str,
    state: ongoing.JobState,
    *process_ids: int,
) -> ongoing.JobSnapshot:
    identity = ongoing._job_identity(attempt_id)
    return ongoing.JobSnapshot(
        job_name=str(identity["job_name"]),
        state=state,
        process_ids=tuple(process_ids),
    )


def _install_available_capacity(
    monkeypatch: pytest.MonkeyPatch,
    released: list[tuple[object, object]],
) -> None:
    counter = 0

    class FakeQuota:
        def bind(self, lease: dict[str, Any], *, child_pid: int) -> dict[str, Any]:
            bound = {
                **lease,
                "status": "BOUND",
                "child_pid": child_pid,
                "bound_at": ongoing._now_iso(),
                "counted": True,
            }
            _write_json(
                Path(str(bound["path"])),
                {key: value for key, value in bound.items() if key != "path"},
            )
            return bound

    def claim(*_args: object, **_kwargs: object) -> dict[str, Any]:
        nonlocal counter
        counter += 1
        attempt_id = str(_kwargs["attempt_id"])
        opportunity_id = str(_kwargs["opportunity_id"])
        workspace = Path(str(_kwargs["workspace"]))
        quota_root = workspace.parent.parent / "quota"
        monkeypatch.setattr(ongoing, "DEFAULT_QUOTA_ROOT", quota_root)
        slot = ((counter - 1) % 4) + 1
        lease_path = quota_root / "A" / f"world-turn-{slot:02d}.json"
        persisted_lease = {
            "schema": ongoing.WORLD_TURN_QUOTA_LEASE_SCHEMA,
            "lease_id": f"quota-fixture-{counter}",
            "counted": True,
            "status": "RESERVED",
            "account_slot": "A",
            "slot": slot,
            "limit": 4,
            "run_id": attempt_id,
            "lineage_id": opportunity_id,
            "workspace": str(workspace.resolve(strict=False)),
            "controller_pid": os.getpid(),
            "child_pid": None,
            "reserved_at": ongoing._now_iso(),
            "bound_at": None,
            "released_at": None,
            "experiment_candidate_only": True,
        }
        _write_json(lease_path, persisted_lease)
        return {
            "outcome": "CLAIMED",
            "quota": FakeQuota(),
            "lease": {**persisted_lease, "path": str(lease_path.resolve(strict=False))},
        }

    def release(quota: object, lease: object) -> str:
        released.append((quota, lease))
        assert isinstance(lease, dict)
        path = Path(str(lease["path"]))
        persisted = {
            **{key: value for key, value in lease.items() if key != "path"},
            "status": "RELEASED",
            "released_at": ongoing._now_iso(),
        }
        _write_json(path, persisted)
        return "RELEASED"

    def validate_source_repo(path: Path) -> dict[str, str]:
        return {
            "root": str(path.resolve()),
            "head": "a" * 40,
            "branch": "main",
            "status_sha256": "B" * 64,
        }

    def clone_isolated_repo(source: Path, destination: Path, head: str) -> dict[str, str]:
        assert head == "a" * 40
        assert not destination.exists()
        destination.mkdir(parents=True)
        (destination / ".git").mkdir()
        (destination / ".git" / "config").write_bytes(
            b"[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
        )
        return {
            "workspace": str(destination.resolve()),
            "head": head,
            "remote_count": "0",
            "status_sha256": "C" * 64,
        }

    def create_launcher(
        source: Path,
        destination: Path,
        *,
        network_access: bool,
        require_runtime_binding: bool = False,
    ) -> dict[str, Any]:
        assert network_access is False
        assert require_runtime_binding is False
        raw = source.read_bytes()
        raw = raw.replace(
            b"sandbox_workspace_write.network_access=true",
            b"sandbox_workspace_write.network_access=false",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        return {"path": str(destination.resolve()), "sha256": _sha256(raw)}

    def git_workspace_output(workspace: Path, arguments: object) -> str:
        args = list(arguments)
        if args == ["rev-parse", "--show-toplevel"]:
            return f"{workspace.resolve()}\n"
        if args == ["rev-parse", "HEAD"]:
            return f"{'a' * 40}\n"
        if args in (["remote"], ["status", "--porcelain=v1", "--untracked-files=no"]):
            return ""
        raise AssertionError(f"unexpected fake git text probe: {args}")

    def git_workspace_bytes(workspace: Path, arguments: object) -> bytes:
        args = list(arguments)
        assert args == ["ls-files", "--others", "-z"]
        bundle_root = workspace / ongoing.BUNDLE_RELATIVE_ROOT
        relative_paths = sorted(
            path.relative_to(workspace).as_posix()
            for path in bundle_root.rglob("*")
            if path.is_file()
        )
        return b"".join(path.encode("utf-8") + b"\0" for path in relative_paths)

    monkeypatch.setattr(ongoing, "_claim_capacity", claim)
    monkeypatch.setattr(ongoing, "_release_capacity", release)
    monkeypatch.setattr(ongoing, "validate_source_repo", validate_source_repo)
    monkeypatch.setattr(ongoing, "clone_isolated_repo", clone_isolated_repo)
    monkeypatch.setattr(ongoing, "create_world_isolated_launcher", create_launcher)
    monkeypatch.setattr(ongoing, "_git_workspace_output", git_workspace_output)
    monkeypatch.setattr(ongoing, "_git_workspace_bytes", git_workspace_bytes)


def _write_continuation_observation(
    runtime: Path,
    *,
    name: str = "observation-1",
    reported_status: str = "SEALED",
) -> Path:
    receipt_path = runtime / "cells" / "cell-fixture" / "runs" / name / "run_receipt.json"
    receipt = {
        "schema": "xinao.research-of-research.run.v1",
        "cell_id": "cell-fixture",
        "run_id": name,
        "status": reported_status,
    }
    _write_json(receipt_path, receipt)
    receipt_sha256 = _sha256(receipt_path.read_bytes())
    logical_identity_value = {
        "cell_id": "cell-fixture",
        "run_id": name,
        "source_class": "ror_run_receipt",
    }
    source_fingerprint_value = {
        **logical_identity_value,
        "receipt_digest": f"bytes_sha256:{receipt_sha256}",
    }
    observation_id = ongoing._stable_id(source_fingerprint_value)
    path = runtime / "continuation" / "observations" / observation_id / "observation.json"
    value = {
        "schema": "xinao.research-of-research.continuation-observation.v0",
        "observation_id": observation_id,
        "source_fingerprint": observation_id,
        "logical_identity": ongoing._stable_id(logical_identity_value),
        "source": {
            "source_class": "ror_run_receipt",
            "cell_id": "cell-fixture",
            "run_id": name,
            "receipt_schema": "xinao.research-of-research.run.v1",
            "receipt_digest": f"bytes_sha256:{receipt_sha256}",
            "receipt_file_sha256": receipt_sha256,
            "seal_mode": "LEGACY_EXACT_BYTES",
            "reported_status": reported_status,
            "relative_path": f"cells/cell-fixture/runs/{name}/run_receipt.json",
        },
        "contract_revision_id": "stage0-fixture",
        "protocol_stage": "STAGE_0_CONTINUITY_DETECTION_ONLY",
        "observation_semantics": "DURABLE_FACT_DETECTED_NOT_REENTRY_AUTHORIZATION",
        "authority": False,
        "instruction_source": False,
        "continuation_authorized": False,
        "dispatch_allowed": False,
        "reentry_request_derived": False,
        "main_launch_authorized": False,
        "capacity_claim_authorized": False,
        "shared_effect_authorized": False,
        "completion_claim_allowed": False,
    }
    _write_json(path, value)
    return path


def test_observation_cannot_authorize_compute_without_explicit_ongoing_contract(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    _write_continuation_observation(runtime)
    popen_calls: list[object] = []

    def forbidden_popen(*args: object, **kwargs: object) -> object:
        popen_calls.append((args, kwargs))
        raise AssertionError("observation alone must never reach subprocess creation")

    with pytest.raises(ongoing.OngoingError) as raised:
        ongoing.reconcile_ongoing(runtime, popen_factory=forbidden_popen)

    assert raised.value.reason_code == "CONTRACT_NOT_BOUND"
    assert popen_calls == []
    assert not list((runtime / "ongoing").glob("opportunities/**/*.json"))


def test_contract_revision_exact_hash_activation_inventory_idempotency_conflict_and_stop(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, contract = _contract_fixture(tmp_path)
    contract_raw = contract_path.read_bytes()
    contract_sha256 = _sha256(contract_raw)

    bound = ongoing.initialize_ongoing_contract(runtime, contract_path)

    assert bound["outcome"] == "BOUND"
    assert bound["created"] is True
    revision_id = str(bound["revision_id"])
    revision_path = runtime / "ongoing" / "contracts" / "revisions" / f"{revision_id}.json"
    revision_raw = revision_path.read_bytes()
    assert _sha256(revision_raw) == revision_id
    revision = json.loads(revision_raw)
    assert revision["contract_source_sha256"] == contract_sha256
    assert revision["contract"] == contract
    assert set(revision["contract"]) == {
        "schema",
        "human_appointment",
        "evidence_frame",
        "wake_policy",
        "carrier",
    }
    assert "parent_statement" not in revision["contract"]
    assert "candidate_continue" not in revision["contract"]["wake_policy"]
    assert revision["activation_inventory_id"]
    inventory = revision["activation_inventory"]
    assert len(inventory) == 1
    assert inventory[0]["sha256"] == _sha256(
        (tmp_path / "current-reality" / "chronology.md").read_bytes()
    )
    assert "mtime" not in json.dumps(revision, sort_keys=True).casefold()
    assert (
        runtime / "ongoing" / "contracts" / "sources" / f"{contract_sha256}.json"
    ).read_bytes() == contract_raw
    current = _read_json(runtime / "ongoing" / "contracts" / "current.json")
    assert current["revision_id"] == revision_id
    assert current["status"] == "LIVE"

    repeated = ongoing.initialize_ongoing_contract(runtime, contract_path)
    assert repeated["outcome"] == "BOUND"
    assert repeated["created"] is False
    assert repeated["revision_id"] == revision_id
    assert len(list((runtime / "ongoing" / "contracts" / "revisions").glob("*.json"))) == 1

    conflicting = json.loads(json.dumps(contract))
    conflicting["carrier"]["timeout_seconds"] = 31
    conflicting_path = tmp_path / "conflicting-contract.json"
    _write_json(conflicting_path, conflicting)
    with pytest.raises(ongoing.OngoingError) as raised:
        ongoing.initialize_ongoing_contract(runtime, conflicting_path)
    assert raised.value.reason_code == "CONTRACT_ALREADY_BOUND"

    with pytest.raises(ongoing.OngoingError) as raised:
        ongoing.stop_ongoing_contract(runtime, expected_revision_id="0" * 64)
    assert raised.value.reason_code == "CONTRACT_EXPECTED_REVISION_MISMATCH"
    stopped = ongoing.stop_ongoing_contract(runtime, expected_revision_id=revision_id)
    assert stopped["outcome"] == "STOPPED"
    stop_seal = _read_json(runtime / "ongoing" / "contracts" / "stops" / f"{revision_id}.json")
    assert stop_seal["revision_id"] == revision_id
    assert ongoing.ongoing_status(runtime)["contract_status"] == "STOPPED"

    with pytest.raises(ongoing.OngoingError) as raised:
        ongoing.initialize_ongoing_contract(runtime, contract_path)
    assert raised.value.reason_code == "CONTRACT_REVISION_STOPPED"
    rebound = ongoing.initialize_ongoing_contract(runtime, conflicting_path)
    assert rebound["outcome"] == "BOUND"
    assert rebound["created"] is True
    assert rebound["revision_id"] != revision_id
    new_current = _read_json(runtime / "ongoing" / "contracts" / "current.json")
    assert new_current["revision_id"] == rebound["revision_id"]
    assert new_current["status"] == "LIVE"
    assert stop_seal == _read_json(
        runtime / "ongoing" / "contracts" / "stops" / f"{revision_id}.json"
    )


def test_stop_seal_is_truth_before_pointer_replay_and_repair_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    bound = ongoing.initialize_ongoing_contract(runtime, contract_path)
    revision_id = str(bound["revision_id"])
    stop_path = runtime / "ongoing" / "contracts" / "stops" / f"{revision_id}.json"
    current_path = runtime / "ongoing" / "contracts" / "current.json"
    real_atomic_write_json = ongoing.atomic_write_json

    class InjectedPointerCrash(BaseException):
        pass

    def crash_after_stop_seal(path: Path, value: object) -> object:
        if path == current_path and isinstance(value, dict) and value.get("status") == "STOPPED":
            assert stop_path.is_file()
            raise InjectedPointerCrash()
        return real_atomic_write_json(path, value)

    monkeypatch.setattr(ongoing, "atomic_write_json", crash_after_stop_seal)
    with pytest.raises(InjectedPointerCrash):
        ongoing.stop_ongoing_contract(runtime, expected_revision_id=revision_id)
    monkeypatch.setattr(ongoing, "atomic_write_json", real_atomic_write_json)
    exact_stop_bytes = stop_path.read_bytes()
    stopped_at = _read_json(stop_path)["stopped_at"]
    assert _read_json(current_path)["status"] == "LIVE"

    stopped_tick = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"stop seal launched compute before pointer repair: {args!r} {kwargs!r}"
        ),
    )
    assert stopped_tick["outcome"] == "STOPPED"
    assert ongoing.ongoing_status(runtime)["contract_status"] == "STOPPED"
    assert _read_json(current_path)["status"] == "LIVE"

    repaired = ongoing.stop_ongoing_contract(runtime, expected_revision_id=revision_id)
    repeated = ongoing.stop_ongoing_contract(runtime, expected_revision_id=revision_id)
    assert repaired["outcome"] == "ALREADY_STOPPED"
    assert repeated["outcome"] == "ALREADY_STOPPED"
    assert _read_json(current_path)["status"] == "STOPPED"
    assert _read_json(current_path)["stopped_at"] == stopped_at
    assert stop_path.read_bytes() == exact_stop_bytes
    assert ongoing.reconcile_ongoing(runtime)["outcome"] == "STOPPED"
    assert ongoing.ongoing_status(runtime)["active_attempt_id"] is None


def test_v2_contract_rejects_compiled_parent_and_model_self_wake_fields(tmp_path: Path) -> None:
    _contract_path, contract = _contract_fixture(tmp_path)

    compiled_parent = json.loads(json.dumps(contract))
    compiled_parent["parent_statement"] = "S-authored epistemic reconstruction"
    with pytest.raises(ongoing.OngoingError) as parent_error:
        ongoing._validate_contract(compiled_parent, runtime_root=tmp_path / "runtime")
    assert parent_error.value.reason_code == "CONTRACT_KEYS_INVALID"

    self_wake = json.loads(json.dumps(contract))
    self_wake["wake_policy"]["candidate_continue"] = True
    with pytest.raises(ongoing.OngoingError) as wake_error:
        ongoing._validate_contract(self_wake, runtime_root=tmp_path / "runtime")
    assert wake_error.value.reason_code == "WAKE_POLICY_KEYS_INVALID"


def test_stopped_waiting_attempt_cannot_reenter_or_block_a_new_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    first_path, first_contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    first = ongoing.initialize_ongoing_contract(runtime, first_path)
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"},
    )

    waiting = ongoing.reconcile_ongoing(runtime)
    old_attempt_id = str(waiting["attempt_id"])
    old_attempt_path = runtime / "ongoing" / "attempts" / old_attempt_id / "status.json"
    old_opportunity_path = (
        runtime
        / "ongoing"
        / "opportunities"
        / str(_read_json(old_attempt_path)["opportunity_id"])
        / "status.json"
    )
    assert _read_json(old_attempt_path)["status"] == "WAITING_FOR_COMPUTE"

    ongoing.stop_ongoing_contract(runtime, expected_revision_id=str(first["revision_id"]))
    assert _read_json(old_attempt_path)["status"] == "STOPPED"
    assert _read_json(old_opportunity_path)["status"] == "STOPPED"

    second_contract = json.loads(json.dumps(first_contract))
    second_contract["carrier"]["timeout_seconds"] = 31
    second_path = tmp_path / "second-ongoing-contract.json"
    _write_json(second_path, second_contract)
    second = ongoing.initialize_ongoing_contract(runtime, second_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []

    completed = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final()),
    )

    assert completed["candidate_id"]
    assert len(calls) == 1
    candidate = _read_json(next((runtime / "ongoing" / "candidates").glob("*.json")))
    assert candidate["contract_revision_id"] == second["revision_id"]
    assert _read_json(old_attempt_path)["status"] == "STOPPED"
    assert _read_json(old_opportunity_path)["status"] == "STOPPED"


@pytest.mark.parametrize("drift_target", ["contract", "appointment"])
def test_contract_or_human_appointment_drift_fails_closed_before_compute(
    tmp_path: Path,
    drift_target: str,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    if drift_target == "contract":
        contract_path.write_bytes(contract_path.read_bytes() + b"\n")
    else:
        Path(contract["human_appointment"]["source_path"]).write_text(
            "appointment drifted after binding\n", encoding="utf-8"
        )
    popen_calls: list[object] = []

    def forbidden_popen(*args: object, **kwargs: object) -> object:
        popen_calls.append((args, kwargs))
        raise AssertionError("drift must fail before subprocess creation")

    result = ongoing.reconcile_ongoing(runtime, popen_factory=forbidden_popen)

    assert result["outcome"] == "CONTRACT_REBIND_REQUIRED"
    assert popen_calls == []
    drift_facts = [
        _read_json(path)
        for path in (runtime / "ongoing" / "facts").glob("*.json")
        if _read_json(path).get("fact_type") == "CONTRACT_DRIFT"
    ]
    assert len(drift_facts) == 1
    for key in ("authority", "shared_effect_authorized", "completion_claim_allowed"):
        assert drift_facts[0][key] is False


def test_unstable_source_read_fails_closed_before_capacity_or_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    source = (tmp_path / "current-reality" / "chronology.md").resolve()
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    real_stable_read = ongoing._stable_read

    def unstable_read(path: Path, *, expected_sha256: str | None = None) -> bytes:
        if path.resolve(strict=False) == source:
            raise ongoing.OngoingError("SOURCE_DRIFT_DURING_READ", "fixture unstable read")
        return real_stable_read(path, expected_sha256=expected_sha256)

    monkeypatch.setattr(ongoing, "_stable_read", unstable_read)
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail("capacity reached after unstable source read"),
    )

    with pytest.raises(ongoing.OngoingError) as raised:
        ongoing.reconcile_ongoing(
            runtime,
            popen_factory=lambda *_args, **_kwargs: pytest.fail(
                "Popen reached after unstable source read"
            ),
        )

    assert raised.value.reason_code == "SOURCE_DRIFT_DURING_READ"
    assert len(list((runtime / "ongoing" / "opportunities").glob("*/request.json"))) == 1


def test_transient_workspace_inventory_mismatch_is_rechecked_before_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    exact_text_probe = ongoing._git_workspace_output
    exact_probe = ongoing._git_workspace_bytes
    tracked_scans = 0
    untracked_scans = 0

    def transient_text_probe(workspace: Path, arguments: object) -> str:
        nonlocal tracked_scans
        args = list(arguments)
        if args == ["status", "--porcelain=v1", "--untracked-files=no"]:
            tracked_scans += 1
            if tracked_scans == 1:
                return " M transient-tracked-projection\n"
        return exact_text_probe(workspace, arguments)

    def transient_probe(workspace: Path, arguments: object) -> bytes:
        nonlocal untracked_scans
        untracked_scans += 1
        exact = exact_probe(workspace, arguments)
        if untracked_scans == 1:
            return exact + b"S_REENTRY_EVIDENCE/ROR_FRAME/transient.tmp\0"
        return exact

    monkeypatch.setattr(ongoing, "_git_workspace_output", transient_text_probe)
    monkeypatch.setattr(ongoing, "_git_workspace_bytes", transient_probe)
    popen_calls: list[dict[str, Any]] = []

    result = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(popen_calls, _candidate_final()),
    )

    assert result["outcome"] == "RECONCILED"
    assert tracked_scans == 3
    assert untracked_scans == 3
    assert len(popen_calls) == 1
    assert len(released) == 1


@pytest.mark.parametrize(
    ("capacity_outcome", "reason_code"),
    [("BUSY", "COMPUTE_BUSY"), ("UNKNOWN", "COMPUTE_UNKNOWN")],
)
def test_unavailable_or_unknown_capacity_waits_durably_then_launches_once_when_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capacity_outcome: str,
    reason_code: str,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    popen_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: {
            "outcome": capacity_outcome,
            "reason_code": reason_code,
        },
    )

    waiting = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"Popen reached with {args!r} {kwargs!r}"
        ),
    )

    assert waiting["outcome"] == "WAITING_FOR_COMPUTE"
    statuses = list((runtime / "ongoing" / "opportunities").glob("*/status.json"))
    assert len(statuses) == 1
    assert _read_json(statuses[0])["status"] == "WAITING_FOR_COMPUTE"

    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    completed = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(popen_calls, _candidate_final(disposition="WAIT")),
    )
    repeated = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"sealed candidate relaunched with {args!r} {kwargs!r}"
        ),
    )

    assert completed["outcome"] == "RECONCILED"
    assert len(popen_calls) == 1
    assert len(released) == 1
    bound_lease = released[0][1]
    assert isinstance(bound_lease, dict)
    assert bound_lease["counted"] is True
    assert bound_lease["child_pid"] == popen_calls[0]["process"].pid
    assert repeated["launched_attempt_ids"] == []
    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    attempt = _read_json(attempt_directory / "request.json")
    command = _read_json(attempt_directory / "command.json")
    codex_args = json.loads((attempt_directory / "codex_args.json").read_text(encoding="utf-8"))
    assert isinstance(codex_args, list)
    assert codex_args[0] == "exec"
    assert codex_args[-1] == "-"
    assert "resume" not in codex_args
    assert attempt["fresh_session_only"] is True
    assert attempt["resume_session_id"] is None
    assert attempt["root_main_used"] is False
    assert attempt["root_main_state"] == "NO_ROOT_MAIN_PATH_TOUCHED"
    assert command["codex_argv"] == codex_args
    assert command["resume_session_id"] is None
    assert command["root_main_used"] is False

    candidate_path = next((runtime / "ongoing" / "candidates").glob("*.json"))
    candidate = _read_json(candidate_path)
    unsigned_candidate = dict(candidate)
    seal = unsigned_candidate.pop("candidate_seal_sha256")
    assert seal == _sha256(ongoing.canonical_json_bytes(unsigned_candidate))
    assert candidate["session_id"] == "thread-fixture"
    assert candidate["carrier_result"] == "OPAQUE_CANDIDATE_PAYLOAD_SEALED"
    assert candidate["candidate_payload"] == _candidate_final()["payload"]
    assert candidate["candidate_payload_sha256"] == _sha256(
        candidate["candidate_payload"].encode("utf-8")
    )
    assert candidate["quota_release_status"] == "RELEASED"
    assert candidate["lease_identity"]["reserved_lease"]["counted"] is True
    assert candidate["prompt_sha256"] == _sha256(Path(candidate["prompt_path"]).read_bytes())
    prompt = Path(candidate["prompt_path"]).read_text(encoding="utf-8")
    assert "isolated clone of the clean-room repository" in prompt
    assert "coverage is partial" in prompt
    assert "carrier treats payload as opaque" in prompt
    for forbidden in (
        "Current parent contract",
        "contact the exact current reality",
        "parent_delta",
        "world_surface_debt",
        "settlement_plan",
        "CONTINUE",
    ):
        assert forbidden not in prompt
    frozen_launcher = (attempt_directory / "isolated-launcher.ps1").read_bytes()
    assert b'Write-Host "WORKDIR=' not in frozen_launcher
    assert candidate["launcher_identity"]["stdout_diagnostics_suppressed"] is True
    output_schema = _read_json(Path(candidate["output_schema_path"]))
    assert set(output_schema["properties"]) == {
        "payload",
        "authority",
        "shared_effect_authorized",
        "completion_claim_allowed",
    }
    assert output_schema["properties"]["payload"] == {"type": "string"}
    for boundary in (
        "authority",
        "shared_effect_authorized",
        "completion_claim_allowed",
    ):
        assert output_schema["properties"][boundary] == {"type": "boolean", "const": False}
    assert candidate["output_schema_sha256"] == _sha256(
        Path(candidate["output_schema_path"]).read_bytes()
    )
    assert candidate["codex_args_sha256"] == _sha256(
        Path(candidate["codex_args_path"]).read_bytes()
    )
    assert candidate["trajectory"]["raw_sha256"].casefold() == _sha256(
        Path(candidate["trajectory"]["raw_path"]).read_bytes()
    )
    assert candidate["trajectory"]["sha256"].casefold() == _sha256(
        Path(candidate["trajectory"]["path"]).read_bytes()
    )
    assert candidate["stderr_sha256"] == _sha256(Path(candidate["stderr_path"]).read_bytes())
    assert candidate["last_message_sha256"] == _sha256(
        Path(candidate["last_message_path"]).read_bytes()
    )
    assert candidate["fresh_session_only"] is True
    assert candidate["resume_session_id"] is None
    assert candidate["root_main_used"] is False
    assert candidate["root_main_state"] == "NO_ROOT_MAIN_PATH_TOUCHED"
    assert candidate["effect_gateway_called"] is False
    for key in ("authority", "shared_effect_authorized", "completion_claim_allowed"):
        assert candidate[key] is False
    status = ongoing.ongoing_status(runtime)
    assert status["contract_status"] == "LIVE"
    assert status["candidate_count"] == 1


def test_inventory_truth_is_exact_bytes_not_latest_or_mtime_and_retries_do_not_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    source = tmp_path / "current-reality" / "chronology.md"
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"},
    )

    ongoing.reconcile_ongoing(runtime)
    original_stat = source.stat()
    os.utime(
        source,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 5_000_000_000),
    )
    ongoing.reconcile_ongoing(runtime)
    ongoing.reconcile_ongoing(runtime)
    assert len(list((runtime / "ongoing" / "opportunities").glob("*/request.json"))) == 1

    source.write_bytes(b"second exact reality slice\n")
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    first_change = ongoing.reconcile_ongoing(runtime)
    repeated = ongoing.reconcile_ongoing(runtime)

    requests = [
        _read_json(path) for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
    ]
    assert len(requests) == 1
    assert requests[0]["trigger_type"] == "ACTIVATION"
    assert first_change["new_opportunity_ids"] == []
    assert repeated["new_opportunity_ids"] == []
    facts = [_read_json(path) for path in (runtime / "ongoing" / "facts").glob("*.json")]
    assert any(
        fact.get("fact_type") == "INVENTORY_CHANGE"
        and fact.get("inventory_id") == ongoing._inventory_sources(_contract)["inventory_id"]
        for fact in facts
    )
    serialized = json.dumps({"requests": requests, "facts": facts}, sort_keys=True).casefold()
    assert "mtime" not in serialized
    assert _sha256(source.read_bytes()) in serialized


def test_activation_contact_freezes_new_inventory_and_coalesces_its_inventory_wake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, contract = _contract_fixture(tmp_path)
    bound = ongoing.initialize_ongoing_contract(runtime, contract_path)
    source = tmp_path / "current-reality" / "chronology.md"
    source.write_bytes(b"inventory B became current before activation contact\n")
    inventory_b = ongoing._inventory_sources(contract)
    assert inventory_b["inventory_id"] != bound["activation_inventory_id"]
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []

    launched = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )
    repeated = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"coalesced inventory B launched twice: {args!r} {kwargs!r}"
        ),
    )

    assert launched["outcome"] == "RECONCILED"
    assert len(calls) == 1
    assert len(released) == 1
    candidate = _read_json(next((runtime / "ongoing" / "candidates").glob("*.json")))
    assert candidate["frozen_evidence_bundle"]["inventory_id"] == inventory_b["inventory_id"]
    manifest = _read_json(Path(candidate["frozen_evidence_bundle"]["manifest_path"]))
    inventory_entry = next(row for row in manifest["entries"] if row["group"] == "chronology")
    assert inventory_entry["sha256"] == _sha256(source.read_bytes())
    assert (
        Path(candidate["frozen_evidence_bundle"]["bundle_root"]) / inventory_entry["export_path"]
    ).read_bytes() == source.read_bytes()
    requests = [
        _read_json(path) for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
    ]
    assert len(requests) == 1
    assert requests[0]["trigger_type"] == "ACTIVATION"
    inventory_facts = [
        _read_json(path)
        for path in (runtime / "ongoing" / "facts").glob("*.json")
        if _read_json(path).get("fact_type") == "INVENTORY_CHANGE"
    ]
    activation_fact = next(
        _read_json(path)
        for path in (runtime / "ongoing" / "facts").glob("*.json")
        if _read_json(path).get("fact_type") == "ACTIVATION"
    )
    assert activation_fact["inventory_id"] == bound["activation_inventory_id"]
    assert [row["inventory_id"] for row in inventory_facts] == [inventory_b["inventory_id"]]
    assert repeated["outcome"] == "WAIT"
    assert repeated["new_opportunity_ids"] == []
    assert repeated["launched_attempt_ids"] == []


def test_successful_observation_contact_durably_consumes_same_tick_inventory_wake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )

    _write_continuation_observation(runtime, name="same-tick-observation")
    source = tmp_path / "current-reality" / "chronology.md"
    source.write_bytes(b"same tick observation and inventory epoch B\n")
    covered_inventory = ongoing._inventory_sources(contract)
    contacted = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )

    assert contacted["outcome"] == "RECONCILED"
    requests = [
        _read_json(path) for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
    ]
    trigger_types = [row["trigger_type"] for row in requests]
    assert trigger_types.count("ACTIVATION") == 1
    assert trigger_types.count("CONTINUATION_OBSERVATION") == 1
    assert len(trigger_types) == 2
    latest = max(
        (_read_json(path) for path in (runtime / "ongoing" / "candidates").glob("*.json")),
        key=lambda row: int(row["frozen_evidence_bundle"]["candidate_history"]["candidate_count"]),
    )
    assert (
        latest["frozen_evidence_bundle"]["wake_inventory_id"]
        == covered_inventory["wake_inventory_id"]
    )
    inventory_facts = [
        _read_json(path)
        for path in (runtime / "ongoing" / "facts").glob("*.json")
        if _read_json(path).get("fact_type") == "INVENTORY_CHANGE"
    ]
    assert len(inventory_facts) == 1
    assert inventory_facts[0]["wake_inventory_id"] == covered_inventory["wake_inventory_id"]

    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail(
            "consumed inventory wake launched a duplicate contact"
        ),
    )
    repeated = ongoing.reconcile_ongoing(runtime)

    assert repeated["outcome"] == "WAIT"
    assert repeated["new_opportunity_ids"] == []
    assert len(list((runtime / "ongoing" / "opportunities").glob("*/request.json"))) == 2
    assert not [
        path
        for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
        if _read_json(path)["trigger_type"] == "INVENTORY_CHANGE"
    ]


def test_failed_observation_contact_leaves_same_tick_inventory_wake_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )

    _write_continuation_observation(runtime, name="failed-cover-observation")
    source = tmp_path / "current-reality" / "chronology.md"
    source.write_bytes(b"failed observation contact still saw inventory epoch B\n")
    failed_inventory = ongoing._inventory_sources(contract)
    failed_contact = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, {"malformed": "no candidate schema"}),
    )

    assert failed_contact["outcome"] == "RECONCILED"
    failed_attempt = _read_json(
        runtime / "ongoing" / "attempts" / str(failed_contact["attempt_id"]) / "status.json"
    )
    assert failed_attempt["status"] == "INVALID_OUTPUT"
    assert len(list((runtime / "ongoing" / "candidates").glob("*.json"))) == 1
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"},
    )
    recovered = ongoing.reconcile_ongoing(runtime)

    assert recovered["outcome"] == "WAITING_FOR_COMPUTE"
    assert len(recovered["new_opportunity_ids"]) == 1
    inventory_requests = [
        _read_json(path)
        for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
        if _read_json(path)["trigger_type"] == "INVENTORY_CHANGE"
    ]
    assert len(inventory_requests) == 1
    fact = _read_json(
        runtime / "ongoing" / "facts" / f"{inventory_requests[0]['source_fact_id']}.json"
    )
    assert fact["wake_inventory_id"] == failed_inventory["wake_inventory_id"]


@pytest.mark.parametrize("bundle_identity_field", ["wake_inventory_id", "manifest_id"])
def test_resealed_candidate_bundle_identity_tamper_fails_closed_and_cannot_suppress_inventory_wake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bundle_identity_field: str,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )

    candidate_path = next((runtime / "ongoing" / "candidates").glob("*.json"))
    original_candidate_bytes = candidate_path.read_bytes()
    candidate = _read_json(candidate_path)
    source = tmp_path / "current-reality" / "chronology.md"
    source.write_bytes(b"new inventory wake cannot be forged as already covered\n")
    current_inventory = ongoing._inventory_sources(contract)
    activation_wake = candidate["frozen_evidence_bundle"]["wake_inventory_id"]
    assert current_inventory["wake_inventory_id"] != activation_wake

    if bundle_identity_field == "wake_inventory_id":
        candidate["frozen_evidence_bundle"]["wake_inventory_id"] = current_inventory[
            "wake_inventory_id"
        ]
    else:
        candidate["frozen_evidence_bundle"]["manifest_id"] = "f" * 64
    unsigned = dict(candidate)
    unsigned.pop("candidate_seal_sha256")
    candidate["candidate_seal_sha256"] = _sha256(ongoing.canonical_json_bytes(unsigned))
    _write_json(candidate_path, candidate)
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail("forged candidate bundle identity reached compute"),
    )

    with pytest.raises(ongoing.OngoingError) as raised:
        ongoing.reconcile_ongoing(runtime)

    assert raised.value.reason_code in {
        "CANDIDATE_PROVENANCE_INVALID",
        "CANDIDATE_SCHEMA_INVALID",
    }
    assert not [
        path
        for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
        if _read_json(path)["trigger_type"] == "INVENTORY_CHANGE"
    ]

    candidate_path.write_bytes(original_candidate_bytes)
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"},
    )
    recovered = ongoing.reconcile_ongoing(runtime)

    assert recovered["outcome"] == "WAITING_FOR_COMPUTE"
    assert len(recovered["new_opportunity_ids"]) == 1
    inventory_requests = [
        _read_json(path)
        for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
        if _read_json(path)["trigger_type"] == "INVENTORY_CHANGE"
    ]
    assert len(inventory_requests) == 1
    assert (
        _read_json(
            runtime / "ongoing" / "facts" / f"{inventory_requests[0]['source_fact_id']}.json"
        )["wake_inventory_id"]
        == current_inventory["wake_inventory_id"]
    )


def test_resealed_candidate_cannot_be_relocated_into_a_new_contract_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    first = ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )
    candidate_path = next((runtime / "ongoing" / "candidates").glob("*.json"))
    candidate = _read_json(candidate_path)
    original_candidate_id = str(candidate["candidate_id"])
    original_attempt_id = str(candidate["attempt_id"])
    assert candidate_path.stem == original_candidate_id
    assert candidate["contract_revision_id"] == first["revision_id"]

    ongoing.stop_ongoing_contract(runtime, expected_revision_id=str(first["revision_id"]))
    replacement_contract = json.loads(json.dumps(contract))
    replacement_contract["carrier"]["timeout_seconds"] = 31
    replacement_path = tmp_path / "replacement-ongoing-contract.json"
    _write_json(replacement_path, replacement_contract)
    second = ongoing.initialize_ongoing_contract(runtime, replacement_path)
    assert second["revision_id"] != first["revision_id"]

    candidate["contract_revision_id"] = second["revision_id"]
    unsigned = dict(candidate)
    unsigned.pop("candidate_seal_sha256")
    candidate["candidate_seal_sha256"] = _sha256(ongoing.canonical_json_bytes(unsigned))
    _write_json(candidate_path, candidate)
    assert _read_json(candidate_path)["candidate_id"] == original_candidate_id
    assert candidate_path.stem == original_candidate_id
    assert _read_json(candidate_path)["attempt_id"] == original_attempt_id

    root = runtime / "ongoing"
    with pytest.raises(ongoing.OngoingError) as history_error:
        ongoing._candidate_history(root, str(second["revision_id"]))
    assert history_error.value.reason_code in {
        "CANDIDATE_PROVENANCE_INVALID",
        "CANDIDATE_SCHEMA_INVALID",
    }

    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail("relocated candidate reached new-revision compute"),
    )
    with pytest.raises(ongoing.OngoingError) as reconcile_error:
        ongoing.reconcile_ongoing(runtime)
    assert reconcile_error.value.reason_code in {
        "CANDIDATE_PROVENANCE_INVALID",
        "CANDIDATE_SCHEMA_INVALID",
    }
    assert not [
        path
        for path in (root / "attempts").glob("*/request.json")
        if _read_json(path)["contract_revision_id"] == second["revision_id"]
    ]


def test_inventory_fact_crash_before_opportunity_is_rediscovered_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    bound = ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )

    root = runtime / "ongoing"
    revision = _read_json(root / "contracts" / "revisions" / f"{bound['revision_id']}.json")
    source = tmp_path / "current-reality" / "chronology.md"
    source.write_bytes(b"inventory epoch committed before opportunity projection\n")
    inventory = ongoing._inventory_sources(revision["contract"])
    fact = ongoing._inventory_fact(
        str(bound["revision_id"]),
        inventory,
        observed_at="2026-08-15T00:00:30+00:00",
    )
    ongoing._write_fact(root, fact)
    fact_path = root / "facts" / f"{fact['fact_id']}.json"
    exact_fact_bytes = fact_path.read_bytes()
    expected_opportunity_id = ongoing._stable_id(
        {
            "contract_revision_id": bound["revision_id"],
            "source_fact_id": fact["fact_id"],
            "trigger_type": "INVENTORY_CHANGE",
        }
    )
    assert not (root / "opportunities" / expected_opportunity_id / "request.json").exists()

    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"},
    )
    recovered = ongoing.reconcile_ongoing(runtime)
    repeated = ongoing.reconcile_ongoing(runtime)

    assert recovered["new_opportunity_ids"] == [expected_opportunity_id]
    assert repeated["new_opportunity_ids"] == []
    request_path = root / "opportunities" / expected_opportunity_id / "request.json"
    request = _read_json(request_path)
    assert request["source_fact_id"] == fact["fact_id"]
    assert request["trigger_type"] == "INVENTORY_CHANGE"
    assert fact_path.read_bytes() == exact_fact_bytes
    assert len(list((root / "opportunities").glob("*/request.json"))) == 2


def test_freeze_only_sources_enter_next_evidence_bundle_without_waking_until_old_style_group_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    freeze_only_root = tmp_path / "freeze-only-reality"
    freeze_only_root.mkdir()
    freeze_only_source = freeze_only_root / "background.md"
    freeze_only_source.write_bytes(b"freeze-only A\n")
    contract["evidence_frame"]["source_groups"].append(
        {
            "name": "freeze_only",
            "root": str(freeze_only_root.resolve()),
            "glob_patterns": ["**/*.md"],
            "exact_files": [],
            "wake_authoritative": False,
        }
    )
    # The original v1-shaped group deliberately omits wake_authoritative.  Its
    # historical behavior must remain wake-authoritative without gaining any
    # cognition or shared-effect authority.
    assert "wake_authoritative" not in contract["evidence_frame"]["source_groups"][0]
    _write_json(contract_path, contract)
    bound = ongoing.initialize_ongoing_contract(runtime, contract_path)
    revision = _read_json(
        runtime / "ongoing" / "contracts" / "revisions" / f"{bound['revision_id']}.json"
    )
    groups = {row["name"]: row for row in revision["contract"]["evidence_frame"]["source_groups"]}
    assert groups["chronology"].get("wake_authoritative", True) is True
    assert groups["freeze_only"]["wake_authoritative"] is False
    for key in ("authority", "shared_effect_authorized", "completion_claim_allowed"):
        assert revision[key] is False

    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )

    freeze_only_source.write_bytes(b"freeze-only B must be frozen but cannot wake\n")
    freeze_only_inventory = ongoing._inventory_sources(revision["contract"])
    assert freeze_only_inventory["inventory_id"] != revision["activation_inventory_id"]
    assert freeze_only_inventory["wake_inventory_id"] == revision["activation_wake_inventory_id"]
    freeze_only_tick = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"freeze-only source manufactured cognition: {args!r} {kwargs!r}"
        ),
    )
    assert freeze_only_tick["outcome"] == "WAIT"
    assert freeze_only_tick["new_opportunity_ids"] == []
    assert len(list((runtime / "ongoing" / "opportunities").glob("*/request.json"))) == 1
    assert not [
        path
        for path in (runtime / "ongoing" / "facts").glob("*.json")
        if _read_json(path).get("fact_type") == "INVENTORY_CHANGE"
    ]

    chronology = tmp_path / "current-reality" / "chronology.md"
    chronology.write_bytes(b"explicit wake-authoritative B\n")
    wake_inventory = ongoing._inventory_sources(revision["contract"])
    assert wake_inventory["wake_inventory_id"] != revision["activation_wake_inventory_id"]
    woken = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )

    assert len(woken["new_opportunity_ids"]) == 1
    assert len(calls) == 2
    assert len(released) == 2
    requests = [
        _read_json(path) for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
    ]
    assert [row["trigger_type"] for row in requests].count("INVENTORY_CHANGE") == 1
    candidates = [_read_json(path) for path in (runtime / "ongoing" / "candidates").glob("*.json")]
    latest = max(
        candidates,
        key=lambda row: int(row["frozen_evidence_bundle"]["candidate_history"]["candidate_count"]),
    )
    manifest = _read_json(Path(latest["frozen_evidence_bundle"]["manifest_path"]))
    freeze_entry = next(row for row in manifest["entries"] if row["group"] == "freeze_only")
    frozen_path = (
        Path(latest["frozen_evidence_bundle"]["bundle_root"]) / freeze_entry["export_path"]
    )
    assert frozen_path.read_bytes() == freeze_only_source.read_bytes()
    assert freeze_entry["sha256"] == _sha256(freeze_only_source.read_bytes())
    assert manifest["inventory_id"] == wake_inventory["inventory_id"]
    assert manifest["wake_inventory_id"] == wake_inventory["wake_inventory_id"]
    for request in requests:
        for key in ("authority", "shared_effect_authorized", "completion_claim_allowed"):
            assert request[key] is False


def test_next_contact_receives_full_chronological_candidate_history_not_latest_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    clock = {"value": "2026-08-15T00:00:00+00:00"}
    monkeypatch.setattr(ongoing, "_now_iso", lambda: clock["value"])
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    source = tmp_path / "current-reality" / "chronology.md"
    calls: list[dict[str, Any]] = []
    warning = "WARNING_A_MUST_SURVIVE_LATER_OMISSION"
    final_a = _candidate_final(disposition="WAIT")
    final_a["payload"] = f"CANDIDATE_A\n{warning}"
    final_b = _candidate_final(disposition="WAIT")
    final_b["payload"] = "CANDIDATE_B_WITHOUT_THE_EARLIER_SENTINEL"
    final_c = _candidate_final(disposition="WAIT")
    final_c["payload"] = "CANDIDATE_C_READS_THE_FULL_HISTORY_BUNDLE"

    ongoing.reconcile_ongoing(runtime, popen_factory=_popen_factory(calls, final_a))
    # Controller timestamps currently have one-second resolution.  All three
    # candidates intentionally settle in the same second so chronology cannot
    # silently fall back to candidate-id lexical order.
    source.write_bytes(b"inventory B external epoch\n")
    ongoing.reconcile_ongoing(runtime, popen_factory=_popen_factory(calls, final_b))
    source.write_bytes(b"inventory C external epoch\n")
    ongoing.reconcile_ongoing(runtime, popen_factory=_popen_factory(calls, final_c))

    candidates = [_read_json(path) for path in (runtime / "ongoing" / "candidates").glob("*.json")]
    candidate_a = next(
        row for row in candidates if row["candidate_payload"].startswith("CANDIDATE_A")
    )
    candidate_b = next(
        row for row in candidates if row["candidate_payload"].startswith("CANDIDATE_B")
    )
    candidate_c = next(
        row for row in candidates if row["candidate_payload"].startswith("CANDIDATE_C")
    )
    history = candidate_c["frozen_evidence_bundle"]["candidate_history"]
    assert history["candidate_count"] == 2
    index_path = Path(history["index_path"])
    index = _read_json(index_path)
    assert [row["candidate_id"] for row in index["candidates"]] == [
        candidate_a["candidate_id"],
        candidate_b["candidate_id"],
    ]
    assert [row["chronology_ordinal"] for row in index["candidates"]] == [0, 1]
    bundle_root = Path(candidate_c["frozen_evidence_bundle"]["bundle_root"])
    for prior in (candidate_a, candidate_b):
        durable = runtime / "ongoing" / "candidates" / f"{prior['candidate_id']}.json"
        frozen = bundle_root / "HISTORY" / "candidates" / f"{prior['candidate_id']}.json"
        assert frozen.read_bytes() == durable.read_bytes()
    frozen_a = _read_json(
        bundle_root / "HISTORY" / "candidates" / f"{candidate_a['candidate_id']}.json"
    )
    frozen_b = _read_json(
        bundle_root / "HISTORY" / "candidates" / f"{candidate_b['candidate_id']}.json"
    )
    assert warning in json.dumps(frozen_a, ensure_ascii=False)
    assert warning not in json.dumps(frozen_b, ensure_ascii=False)
    manifest = _read_json(Path(candidate_c["frozen_evidence_bundle"]["manifest_path"]))
    history_exports = {
        row["export_path"] for row in manifest["entries"] if row["group"] == "candidate_history"
    }
    assert history_exports == {
        "HISTORY/CANDIDATE_INDEX.json",
        f"HISTORY/candidates/{candidate_a['candidate_id']}.json",
        f"HISTORY/candidates/{candidate_b['candidate_id']}.json",
    }
    prompt = Path(candidate_c["prompt_path"]).read_text(encoding="utf-8")
    assert f"- candidate-history index: {index_path}" in prompt
    assert len(calls) == 3
    assert len(released) == 3


def test_reentry_evidence_manifest_copies_source_bytes_and_binds_every_hash(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    bound = ongoing.initialize_ongoing_contract(runtime, contract_path)
    revision_path = runtime / "ongoing" / "contracts" / "revisions" / f"{bound['revision_id']}.json"
    revision = _read_json(revision_path)
    revision["revision_id"] = bound["revision_id"]
    inventory = {
        "inventory_id": revision["activation_inventory_id"],
        "entries": revision["activation_inventory"],
    }
    workspace = tmp_path / "isolated-workspace"
    workspace.mkdir()

    frozen = ongoing._freeze_reentry_evidence(
        revision["contract"],
        revision,
        inventory,
        workspace,
        source_identity={"head": "a" * 40, "status_sha256": "B" * 64},
    )

    manifest_path = Path(frozen["manifest_path"])
    manifest = _read_json(manifest_path)
    assert frozen["manifest_sha256"] == _sha256(manifest_path.read_bytes())
    assert manifest["manifest_id"] == frozen["manifest_id"]
    assert manifest["inventory_id"] == revision["activation_inventory_id"]
    assert manifest["bound_reentry_contract"]["contract_source_sha256"] == _sha256(
        contract_path.read_bytes()
    )
    entry = manifest["entries"][0]
    source = Path(entry["source_path"])
    copied = Path(frozen["bundle_root"]) / entry["export_path"]
    assert copied.read_bytes() == source.read_bytes()
    assert entry["sha256"] == _sha256(copied.read_bytes())
    assert entry["size"] == len(copied.read_bytes())
    assert manifest["root_main_used"] is False
    assert manifest["coverage_claim"] == "PARTIAL"
    assert manifest["snapshot_atomicity"] == "PER_FILE_STABLE_NO_GLOBAL_ATOMICITY"
    assert manifest["instruction_authority"] is False
    assert manifest["cognition_authority"] is False
    assert manifest["source_repository_is_cognition_body"] is True
    assert manifest["evidence_frame_replaces_repository_world"] is False
    assert manifest["shared_effect_authorized"] is False
    assert manifest["completion_claim_allowed"] is False


def test_preflight_rejects_resealed_manifest_inventory_omission_before_popen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    (tmp_path / "current-reality" / "second.md").write_bytes(b"second exact current entry\n")
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    real_build_runner_request = ongoing._build_runner_request
    omitted: dict[str, Any] = {}

    def build_with_resealed_omission(
        root: Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        environment = kwargs["environment"]
        manifest_path = Path(environment["bundle"]["manifest_path"])
        manifest = _read_json(manifest_path)
        original_inventory_id = manifest["inventory_id"]
        inventory_entry = next(
            row
            for row in manifest["entries"]
            if not row["export_path"].startswith(("HISTORY/", "TRIGGER/"))
        )
        manifest["entries"].remove(inventory_entry)
        unsigned = dict(manifest)
        unsigned.pop("manifest_id")
        manifest["manifest_id"] = ongoing._stable_id(unsigned)
        _write_json(manifest_path, manifest)
        assert manifest["inventory_id"] == original_inventory_id
        omitted.update(inventory_entry)
        return real_build_runner_request(root, **kwargs)

    monkeypatch.setattr(ongoing, "_build_runner_request", build_with_resealed_omission)
    popen_calls: list[tuple[object, object]] = []

    def forbidden_popen(*args: object, **kwargs: object) -> object:
        popen_calls.append((args, kwargs))
        raise AssertionError("semantically incomplete manifest reached model Popen")

    result = ongoing.reconcile_ongoing(runtime, popen_factory=forbidden_popen)

    assert omitted["group"] == "chronology"
    assert result["outcome"] == "RETRYABLE"
    assert popen_calls == []
    assert len(released) == 1
    reserved = released[0][1]
    assert isinstance(reserved, dict)
    assert reserved["status"] == "RESERVED"
    assert reserved["child_pid"] is None
    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    assert not (attempt_directory / "runner_started.json").exists()
    terminal = _read_json(attempt_directory / "runner_terminal.json")
    assert terminal["error_code"] == "RUNNER_EXACT_BUNDLE_INVENTORY_OMISSION"
    assert terminal["child_pid"] is None
    assert terminal["release_status"] == "RELEASED"
    assert _read_json(attempt_directory / "status.json")["status"] == "TERMINAL_FAILED"
    opportunity_status = _read_json(
        next((runtime / "ongoing" / "opportunities").glob("*/status.json"))
    )
    assert opportunity_status["status"] == "RETRYABLE"
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


@pytest.mark.parametrize(
    ("eligibility_override", "expected_new_opportunities", "expected_eligible"),
    [
        (None, 0, False),
        (
            {
                "schema": ongoing.OBSERVATION_ELIGIBILITY_SCHEMA,
                "field": "reported_status",
                "operator": "IN",
                "values": ["INVALID_EXPERIMENT"],
                "missing_is_eligible": False,
            },
            1,
            True,
        ),
    ],
)
def test_invalid_experiment_is_durable_evidence_and_only_contract_data_can_make_it_eligible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eligibility_override: dict[str, Any] | None,
    expected_new_opportunities: int,
    expected_eligible: bool,
) -> None:
    runtime = tmp_path / "runtime"
    overrides: dict[str, object] = {}
    if eligibility_override is not None:
        overrides["continuation_observation_eligibility"] = eligibility_override
    contract_path, _contract = _contract_fixture(tmp_path, **overrides)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"},
    )
    ongoing.reconcile_ongoing(runtime)
    observation_path = _write_continuation_observation(
        runtime,
        name="invalid-source",
        reported_status="INVALID_EXPERIMENT",
    )

    observed = ongoing.reconcile_ongoing(runtime)
    repeated = ongoing.reconcile_ongoing(runtime)

    assert len(observed["new_opportunity_ids"]) == expected_new_opportunities
    assert repeated["new_opportunity_ids"] == []
    opportunity_requests = list((runtime / "ongoing" / "opportunities").glob("*/request.json"))
    assert len(opportunity_requests) == 1 + expected_new_opportunities
    facts = [_read_json(path) for path in (runtime / "ongoing" / "facts").glob("*.json")]
    matching = [row for row in facts if row.get("source_path") == str(observation_path.resolve())]
    assert len(matching) == 1
    fact = matching[0]
    assert fact["reported_status"] == "INVALID_EXPERIMENT"
    assert fact["source_sha256"] == _sha256(observation_path.read_bytes())
    assert fact["cognition_eligibility"]["observed_value"] == "INVALID_EXPERIMENT"
    assert fact["cognition_eligibility"]["eligible"] is expected_eligible
    expected_predicate = (
        eligibility_override
        if eligibility_override is not None
        else {
            "schema": ongoing.OBSERVATION_ELIGIBILITY_SCHEMA,
            "field": "reported_status",
            "operator": "NOT_IN",
            "values": ["INVALID_EXPERIMENT"],
            "missing_is_eligible": False,
        }
    )
    assert fact["cognition_eligibility"]["predicate"] == expected_predicate
    for key in ("authority", "shared_effect_authorized", "completion_claim_allowed"):
        assert fact[key] is False


@pytest.mark.parametrize(
    "corruption",
    [
        "index_forged",
        "index_omitted",
        "candidate_bytes",
        "candidate_omitted",
        "latest_locator",
    ],
)
def test_preflight_rejects_any_candidate_history_corruption_before_popen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    first_calls: list[dict[str, Any]] = []
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(first_calls, _candidate_final(disposition="WAIT")),
    )
    assert len(first_calls) == 1
    first_candidate = _read_json(next((runtime / "ongoing" / "candidates").glob("*.json")))
    (tmp_path / "current-reality" / "chronology.md").write_bytes(
        b"new wake epoch requiring history preflight\n"
    )
    real_build_runner_request = ongoing._build_runner_request

    def build_with_history_corruption(root: Path, **kwargs: Any) -> dict[str, Any]:
        environment = kwargs["environment"]
        manifest_path = Path(environment["bundle"]["manifest_path"])
        bundle_root = Path(environment["bundle"]["bundle_root"])
        manifest = _read_json(manifest_path)
        index_path = bundle_root / "HISTORY" / "CANDIDATE_INDEX.json"
        candidate_path = (
            bundle_root / "HISTORY" / "candidates" / f"{first_candidate['candidate_id']}.json"
        )

        if corruption == "index_forged":
            index = _read_json(index_path)
            index["candidates"][0]["file_sha256"] = "0" * 64
            unsigned = dict(index)
            unsigned.pop("history_id")
            index["history_id"] = ongoing._stable_id(unsigned)
            _write_json(index_path, index)
        elif corruption == "index_omitted":
            index_path.unlink()
            manifest["entries"] = [
                row
                for row in manifest["entries"]
                if row["export_path"] != "HISTORY/CANDIDATE_INDEX.json"
            ]
        elif corruption == "candidate_bytes":
            candidate_path.write_bytes(candidate_path.read_bytes() + b"\n")
        elif corruption == "candidate_omitted":
            candidate_path.unlink()
            manifest["entries"] = [
                row
                for row in manifest["entries"]
                if row["export_path"]
                != f"HISTORY/candidates/{first_candidate['candidate_id']}.json"
            ]
        elif corruption == "latest_locator":
            index = _read_json(index_path)
            index["latest_candidate_id"] = None
            unsigned = dict(index)
            unsigned.pop("history_id")
            index["history_id"] = ongoing._stable_id(unsigned)
            _write_json(index_path, index)
        else:  # pragma: no cover - the parametrization is exhaustive
            raise AssertionError(corruption)

        for entry in manifest["entries"]:
            destination = bundle_root / entry["export_path"]
            if entry["export_path"].startswith("HISTORY/") and destination.is_file():
                raw = destination.read_bytes()
                entry["size"] = len(raw)
                entry["sha256"] = _sha256(raw)
        unsigned_manifest = dict(manifest)
        unsigned_manifest.pop("manifest_id")
        manifest["manifest_id"] = ongoing._stable_id(unsigned_manifest)
        _write_json(manifest_path, manifest)
        return real_build_runner_request(root, **kwargs)

    monkeypatch.setattr(ongoing, "_build_runner_request", build_with_history_corruption)
    popen_calls: list[tuple[object, object]] = []

    def forbidden_popen(*args: object, **kwargs: object) -> object:
        popen_calls.append((args, kwargs))
        raise AssertionError("corrupt candidate history reached model Popen")

    result = ongoing.reconcile_ongoing(runtime, popen_factory=forbidden_popen)

    assert result["outcome"] == "RETRYABLE"
    assert popen_calls == []
    assert len(released) == 2
    assert len(list((runtime / "ongoing" / "candidates").glob("*.json"))) == 1
    terminal = _read_json(
        runtime / "ongoing" / "attempts" / str(result["attempt_id"]) / "runner_terminal.json"
    )
    assert terminal["error_code"].startswith("RUNNER_")
    assert terminal["child_pid"] is None
    assert terminal["release_status"] == "RELEASED"


def test_external_observation_and_receipt_are_frozen_exactly_into_the_contact_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )
    observation = _write_continuation_observation(runtime, name="external-evidence")
    observation_value = _read_json(observation)
    receipt = runtime / observation_value["source"]["relative_path"]

    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )

    assert len(calls) == 2
    assert len(released) == 2
    requests = [
        _read_json(path) for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
    ]
    external_request = next(
        row for row in requests if row["trigger_type"] == "CONTINUATION_OBSERVATION"
    )
    candidates = [_read_json(path) for path in (runtime / "ongoing" / "candidates").glob("*.json")]
    candidate = next(
        row for row in candidates if row["opportunity_id"] == external_request["opportunity_id"]
    )
    bundle_root = Path(candidate["frozen_evidence_bundle"]["bundle_root"])
    manifest_path = Path(candidate["frozen_evidence_bundle"]["manifest_path"])
    manifest = _read_json(manifest_path)
    observation_raw = observation.read_bytes()
    receipt_raw = receipt.read_bytes()
    entries_by_source = {
        Path(entry["source_path"]).resolve(): entry for entry in manifest["entries"]
    }
    observation_entry = entries_by_source[observation.resolve()]
    receipt_entry = entries_by_source[receipt.resolve()]
    assert observation_entry["sha256"] == _sha256(observation_raw)
    assert observation_entry["size"] == len(observation_raw)
    assert receipt_entry["sha256"] == _sha256(receipt_raw)
    assert receipt_entry["size"] == len(receipt_raw)
    assert (bundle_root / observation_entry["export_path"]).read_bytes() == observation_raw
    assert (bundle_root / receipt_entry["export_path"]).read_bytes() == receipt_raw
    for key in ("authority", "shared_effect_authorized", "completion_claim_allowed"):
        assert manifest[key] is False


@pytest.mark.parametrize(
    ("drift_mode", "expected_reason"),
    [
        ("missing", "PREPARE_SOURCE_NOT_REGULAR"),
        ("changed", "PREPARE_SOURCE_HASH_MISMATCH"),
    ],
)
def test_missing_or_changed_observation_receipt_fails_closed_before_popen_and_releases_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift_mode: str,
    expected_reason: str,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(
        tmp_path,
        minimum_continuation_delay_seconds=0,
    )
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    activation_calls: list[dict[str, Any]] = []
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(
            activation_calls,
            _candidate_final(disposition="WAIT"),
        ),
    )
    assert len(activation_calls) == 1
    observation = _write_continuation_observation(runtime, name=f"receipt-{drift_mode}")
    receipt = runtime / _read_json(observation)["source"]["relative_path"]
    if drift_mode == "missing":
        receipt.unlink()
    else:
        receipt.write_bytes(receipt.read_bytes() + b"\nchanged after observation\n")

    result = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *_args, **_kwargs: pytest.fail(
            "Popen reached after receipt evidence drift"
        ),
    )

    assert result["outcome"] == "RETRYABLE"
    assert result["reason_code"] == expected_reason
    assert len(released) == 2
    reserved_lease = released[1][1]
    assert isinstance(reserved_lease, dict)
    assert reserved_lease["status"] == "RESERVED"
    assert len(list((runtime / "ongoing" / "candidates").glob("*.json"))) == 1


def test_model_payload_cannot_self_renew_but_a_later_external_epoch_can_wake_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    clock = {"value": "2026-08-15T00:00:00+00:00"}
    monkeypatch.setattr(ongoing, "_now_iso", lambda: clock["value"])
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []
    disabled_continue = _candidate_final()
    disabled_continue["payload"] = json.dumps(
        {"disposition": "CONTINUE", "not_before_seconds": 31_536_000}
    )

    first = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, disabled_continue),
    )

    assert len(calls) == 1
    assert first["new_opportunity_ids"] == []
    candidate = _read_json(next((runtime / "ongoing" / "candidates").glob("*.json")))
    assert candidate["carrier_result"] == "OPAQUE_CANDIDATE_PAYLOAD_SEALED"
    assert '"CONTINUE"' in candidate["candidate_payload"]
    assert candidate["continuation_authorized"] is False

    clock["value"] = "2026-08-15T00:00:09+00:00"
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"model output or timer self-renewed: {args!r} {kwargs!r}"
        ),
    )
    assert len(calls) == 1
    assert len(list((runtime / "ongoing" / "opportunities").glob("*/request.json"))) == 1

    observation = _write_continuation_observation(runtime, name="genuinely-later-epoch")
    clock["value"] = "2026-08-15T00:00:10+00:00"
    later = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"external fact bypassed predecessor floor: {args!r} {kwargs!r}"
        ),
    )
    assert len(later["new_opportunity_ids"]) == 1
    assert len(list((runtime / "ongoing" / "opportunities").glob("*/request.json"))) == 2
    requests = [
        _read_json(path) for path in (runtime / "ongoing" / "opportunities").glob("*/request.json")
    ]
    external_request = next(
        row for row in requests if row["trigger_type"] == "CONTINUATION_OBSERVATION"
    )
    assert (
        datetime.fromisoformat(external_request["not_before"])
        - datetime.fromisoformat("2026-08-15T00:00:00+00:00")
    ).total_seconds() == 60

    clock["value"] = "2026-08-15T00:00:59+00:00"
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"minimum not-before floor bypassed: {args!r} {kwargs!r}"
        ),
    )
    assert len(calls) == 1
    clock["value"] = "2026-08-15T00:01:00+00:00"
    ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, _candidate_final(disposition="WAIT")),
    )
    assert len(calls) == 2
    facts = [_read_json(path) for path in (runtime / "ongoing" / "facts").glob("*.json")]
    assert any(row.get("source_path") == str(observation.resolve()) for row in facts)
    assert len(released) == 2


def test_claiming_crash_after_exact_reserved_commit_is_adopted_and_released_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    quota_root = tmp_path / "quota"
    monkeypatch.setattr(ongoing, "DEFAULT_QUOTA_ROOT", quota_root)
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    committed: dict[str, Any] = {}

    class InjectedClaimCrash(BaseException):
        pass

    def commit_reserved_then_crash(
        _contract: dict[str, Any],
        *,
        attempt_id: str,
        opportunity_id: str,
        workspace: Path,
    ) -> dict[str, Any]:
        lease_path = quota_root / "A" / "world-turn-01.json"
        record = {
            "schema": ongoing.WORLD_TURN_QUOTA_LEASE_SCHEMA,
            "lease_id": "claim-commit-before-identity",
            "counted": True,
            "status": "RESERVED",
            "account_slot": "A",
            "slot": 1,
            "limit": 4,
            "run_id": attempt_id,
            "lineage_id": opportunity_id,
            "workspace": str(workspace.resolve(strict=False)),
            "controller_pid": os.getpid(),
            "child_pid": None,
            "reserved_at": "2026-08-15T00:00:00+00:00",
            "bound_at": None,
            "released_at": None,
            "experiment_candidate_only": True,
        }
        _write_json(lease_path, record)
        committed.update({"path": lease_path, "record": record})
        raise InjectedClaimCrash()

    monkeypatch.setattr(ongoing, "_claim_capacity", commit_reserved_then_crash)
    with pytest.raises(InjectedClaimCrash):
        ongoing.reconcile_ongoing(
            runtime,
            popen_factory=lambda *args, **kwargs: pytest.fail(
                f"claim crash reached Popen: {args!r} {kwargs!r}"
            ),
        )

    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    assert _read_json(attempt_directory / "status.json")["status"] == "CLAIMING_COMPUTE"
    for name in (
        "lease_identity.json",
        "runner_launch_intent.json",
        "runner_spawn.json",
        "runner_started.json",
        "runner_terminal.json",
    ):
        assert not (attempt_directory / name).exists()

    releases: list[dict[str, Any]] = []

    class RecoveryQuota:
        def release(self, lease: dict[str, Any]) -> str:
            releases.append(dict(lease))
            path = Path(str(lease["path"]))
            persisted = _read_json(path)
            assert persisted["status"] == "RESERVED"
            assert persisted["lease_id"] == lease["lease_id"]
            persisted.update(
                {
                    "status": "RELEASED",
                    "released_at": ongoing._now_iso(),
                }
            )
            _write_json(path, persisted)
            return "RELEASED"

    monkeypatch.setattr(ongoing, "_quota_from_identity", lambda _identity: RecoveryQuota())
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail("recovery duplicated the durable quota claim"),
    )
    real_try_acquire = ongoing._try_acquire_byte_lock
    scan_attempts = {"A": 0, "C": 0}

    def transiently_contended_scan(path: Path):
        account = path.parent.name
        if account not in scan_attempts:
            return real_try_acquire(path)
        scan_attempts[account] += 1
        if scan_attempts[account] == 1:
            return None
        return real_try_acquire(path)

    monkeypatch.setattr(ongoing, "_try_acquire_byte_lock", transiently_contended_scan)
    monkeypatch.setattr(ongoing, "_CAPACITY_ADMISSION_LOCK_TIMEOUT_SECONDS", 1.0)
    recovered = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"claim recovery reached Popen: {args!r} {kwargs!r}"
        ),
    )

    assert recovered["outcome"] == "RETRYABLE"
    assert recovered["reason_code"] == "PRE_RUNNER_CRASH_RECOVERED"
    assert len(list((runtime / "ongoing" / "attempts").glob("*/request.json"))) == 1
    identity = _read_json(attempt_directory / "lease_identity.json")
    assert identity["lease_id"] == committed["record"]["lease_id"]
    assert identity["lease_path"] == str(committed["path"].resolve(strict=False))
    assert len(releases) == 1
    assert releases[0]["lease_id"] == committed["record"]["lease_id"]
    assert releases[0]["run_id"] == identity["attempt_id"]
    assert releases[0]["lineage_id"] == identity["opportunity_id"]
    assert releases[0]["status"] == "RESERVED"
    assert scan_attempts == {"A": 2, "C": 2}
    assert _read_json(committed["path"])["status"] == "RELEASED"
    assert _read_json(attempt_directory / "status.json")["status"] == "RETRYABLE"
    assert (
        _read_json(next((runtime / "ongoing" / "opportunities").glob("*/status.json")))["status"]
        == "RETRYABLE"
    )
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


def test_claiming_crash_scan_lock_timeout_preserves_identity_barrier_then_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    quota_root = tmp_path / "quota"
    monkeypatch.setattr(ongoing, "DEFAULT_QUOTA_ROOT", quota_root)
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    committed: dict[str, Any] = {}

    class InjectedClaimCrash(BaseException):
        pass

    def commit_reserved_then_crash(
        _contract: dict[str, Any],
        *,
        attempt_id: str,
        opportunity_id: str,
        workspace: Path,
    ) -> dict[str, Any]:
        lease_path = quota_root / "C" / "world-turn-02.json"
        record = {
            "schema": ongoing.WORLD_TURN_QUOTA_LEASE_SCHEMA,
            "lease_id": "claim-commit-before-identity-timeout",
            "counted": True,
            "status": "RESERVED",
            "account_slot": "C",
            "slot": 2,
            "limit": 4,
            "run_id": attempt_id,
            "lineage_id": opportunity_id,
            "workspace": str(workspace.resolve(strict=False)),
            "controller_pid": os.getpid(),
            "child_pid": None,
            "reserved_at": "2026-08-15T00:00:00+00:00",
            "bound_at": None,
            "released_at": None,
            "experiment_candidate_only": True,
        }
        _write_json(lease_path, record)
        committed.update({"path": lease_path, "record": record})
        raise InjectedClaimCrash()

    monkeypatch.setattr(ongoing, "_claim_capacity", commit_reserved_then_crash)
    with pytest.raises(InjectedClaimCrash):
        ongoing.reconcile_ongoing(runtime)

    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    opportunity_status = next((runtime / "ongoing" / "opportunities").glob("*/status.json"))
    exact_attempt_bytes = (attempt_directory / "status.json").read_bytes()
    exact_opportunity_bytes = opportunity_status.read_bytes()
    exact_lease_bytes = committed["path"].read_bytes()
    real_try_acquire = ongoing._try_acquire_byte_lock
    monkeypatch.setattr(ongoing, "_CAPACITY_ADMISSION_LOCK_TIMEOUT_SECONDS", 0.0)

    def busy_admission_only(path: Path):
        if path.parent.name in {"A", "C"}:
            return None
        return real_try_acquire(path)

    monkeypatch.setattr(ongoing, "_try_acquire_byte_lock", busy_admission_only)
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail("scan timeout duplicated the durable quota claim"),
    )
    monkeypatch.setattr(
        ongoing,
        "_release_capacity",
        lambda *_args, **_kwargs: pytest.fail("scan timeout released an uninspected lease"),
    )

    waiting = ongoing.reconcile_ongoing(runtime)

    assert waiting["outcome"] == "LOCK_BUSY"
    assert waiting["reason_code"] == "QUOTA_SCAN_LOCK_TIMEOUT"
    assert (attempt_directory / "status.json").read_bytes() == exact_attempt_bytes
    assert opportunity_status.read_bytes() == exact_opportunity_bytes
    assert committed["path"].read_bytes() == exact_lease_bytes
    assert _read_json(attempt_directory / "status.json")["status"] == "CLAIMING_COMPUTE"
    assert not (attempt_directory / "lease_identity.json").exists()
    assert len(list((runtime / "ongoing" / "attempts").glob("*/request.json"))) == 1

    releases: list[str] = []

    class RecoveryQuota:
        def release(self, lease: dict[str, Any]) -> str:
            releases.append(str(lease["lease_id"]))
            path = Path(str(lease["path"]))
            record = _read_json(path)
            record.update({"status": "RELEASED", "released_at": ongoing._now_iso()})
            _write_json(path, record)
            return "RELEASED"

    monkeypatch.setattr(ongoing, "_try_acquire_byte_lock", real_try_acquire)
    monkeypatch.setattr(ongoing, "_quota_from_identity", lambda _identity: RecoveryQuota())
    monkeypatch.setattr(ongoing, "_release_capacity", lambda quota, lease: quota.release(lease))
    recovered = ongoing.reconcile_ongoing(runtime)

    assert recovered["outcome"] == "RETRYABLE"
    assert recovered["reason_code"] == "PRE_RUNNER_CRASH_RECOVERED"
    assert releases == [committed["record"]["lease_id"]]
    assert _read_json(committed["path"])["status"] == "RELEASED"
    assert _read_json(attempt_directory / "status.json")["status"] == "RETRYABLE"
    assert len(list((runtime / "ongoing" / "attempts").glob("*/request.json"))) == 1
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


def test_claiming_crash_with_zero_durable_claim_retries_the_same_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(ongoing, "DEFAULT_QUOTA_ROOT", tmp_path / "quota")
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)

    class InjectedPreClaimCrash(BaseException):
        pass

    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(InjectedPreClaimCrash()),
    )
    with pytest.raises(InjectedPreClaimCrash):
        ongoing.reconcile_ongoing(runtime)

    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    attempt_id = attempt_directory.name
    recovered = ongoing.reconcile_ongoing(runtime)
    assert recovered["outcome"] == "WAITING_FOR_COMPUTE"
    assert recovered["attempt_id"] == attempt_id
    assert recovered["reason_code"] == "PRE_CLAIM_CRASH_RECOVERED"
    assert not (attempt_directory / "lease_identity.json").exists()

    claims: list[str] = []

    def busy_same_attempt(
        _contract: dict[str, Any],
        *,
        attempt_id: str,
        opportunity_id: str,
        workspace: Path,
    ) -> dict[str, Any]:
        del opportunity_id, workspace
        claims.append(attempt_id)
        return {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"}

    monkeypatch.setattr(ongoing, "_claim_capacity", busy_same_attempt)
    retried = ongoing.reconcile_ongoing(runtime)

    assert retried["outcome"] == "WAITING_FOR_COMPUTE"
    assert retried["attempt_id"] == attempt_id
    assert claims == [attempt_id]
    assert len(list((runtime / "ongoing" / "attempts").glob("*/request.json"))) == 1
    assert _read_json(attempt_directory / "status.json")["status"] == "WAITING_FOR_COMPUTE"


def test_claiming_crash_quota_scan_unknown_fails_closed_without_claim_or_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    quota_root = tmp_path / "quota"
    monkeypatch.setattr(ongoing, "DEFAULT_QUOTA_ROOT", quota_root)
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)

    class InjectedPreClaimCrash(BaseException):
        pass

    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(InjectedPreClaimCrash()),
    )
    with pytest.raises(InjectedPreClaimCrash):
        ongoing.reconcile_ongoing(runtime)

    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    malformed = quota_root / "A" / "world-turn-01.json"
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_bytes(b"{truncated quota record")
    exact_bytes = malformed.read_bytes()
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail("UNKNOWN scan authorized a new quota claim"),
    )
    monkeypatch.setattr(
        ongoing,
        "_release_capacity",
        lambda *_args, **_kwargs: pytest.fail("UNKNOWN scan authorized quota release"),
    )

    failed = ongoing.reconcile_ongoing(runtime)

    assert failed["outcome"] == "FAILED_UNKNOWN"
    assert failed["reason_code"] == "QUOTA_SCAN_RECORD_INVALID"
    assert _read_json(attempt_directory / "status.json")["status"] == "CLAIMING_COMPUTE"
    assert not (attempt_directory / "lease_identity.json").exists()
    assert malformed.read_bytes() == exact_bytes
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


@pytest.mark.parametrize(
    (
        "attempt_status",
        "ordinal",
        "reason_code",
        "model_started",
        "expected_status",
        "expected_reason",
    ),
    [
        (
            "WAITING_FOR_COMPUTE",
            1,
            "COMPUTE_BUSY",
            False,
            "WAITING_FOR_COMPUTE",
            "COMPUTE_BUSY",
        ),
        ("SEALED", 1, None, False, "COMPLETED", None),
        (
            "INVALID_OUTPUT",
            1,
            "FINAL_OUTPUT_INVALID",
            False,
            "COMPLETED",
            "FINAL_OUTPUT_INVALID",
        ),
        (
            "TERMINAL_FAILED",
            1,
            "MODEL_TERMINAL_FAILED",
            True,
            "RETRYABLE",
            "MODEL_TERMINAL_FAILED",
        ),
        (
            "TERMINAL_FAILED",
            2,
            "MODEL_TERMINAL_FAILED",
            True,
            "COMPLETED",
            "BOUNDED_MODEL_RETRY_EXHAUSTED",
        ),
        (
            "TERMINAL_FAILED",
            2,
            "RUNNER_PREMODEL_FAILURE",
            False,
            "RETRYABLE",
            "RUNNER_PREMODEL_FAILURE",
        ),
        (
            "TERMINAL_FAILED",
            4,
            "RUNNER_PREMODEL_FAILURE",
            False,
            "RETRYABLE",
            "RUNNER_PREMODEL_FAILURE",
        ),
        (
            "TERMINAL_FAILED",
            6,
            "RUNNER_PREMODEL_FAILURE",
            False,
            "COMPLETED",
            "BOUNDED_CARRIER_RETRY_EXHAUSTED",
        ),
        ("STOPPED", 1, "CONTRACT_STOPPED", False, "STOPPED", "CONTRACT_STOPPED"),
    ],
)
def test_attempt_projection_gap_repairs_opportunity_from_latest_durable_attempt(
    tmp_path: Path,
    attempt_status: str,
    ordinal: int,
    reason_code: str | None,
    model_started: bool,
    expected_status: str,
    expected_reason: str | None,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    root = runtime / "ongoing"
    opportunity_path = next((root / "opportunities").glob("*/request.json"))
    opportunity = _read_json(opportunity_path)
    attempts: list[tuple[dict[str, Any], dict[str, Path]]] = []
    for prior_ordinal in range(1, ordinal + 1):
        attempt, paths = ongoing._next_attempt(root, opportunity)
        assert attempt["ordinal"] == prior_ordinal
        projected_status = attempt_status if prior_ordinal == ordinal else "SEALED"
        if attempt_status == "TERMINAL_FAILED":
            projected_status = "TERMINAL_FAILED"
        ongoing._write_attempt_status(
            paths["status"],
            attempt_id=str(attempt["attempt_id"]),
            opportunity_id=str(opportunity["opportunity_id"]),
            status=projected_status,
            child_pid=(9000 + prior_ordinal if model_started else None),
            reason_code=(
                reason_code
                if projected_status == "TERMINAL_FAILED" or prior_ordinal == ordinal
                else None
            ),
        )
        attempts.append((attempt, paths))

    opportunity_status_path = opportunity_path.with_name("status.json")
    stale = _read_json(opportunity_status_path)
    assert stale["status"] == "DUE"
    latest_attempt_id = str(attempts[-1][0]["attempt_id"])

    repaired = ongoing._repair_attempt_opportunity_projections(root)
    repeated = ongoing._repair_attempt_opportunity_projections(root)

    assert repaired == [latest_attempt_id]
    assert repeated == []
    projection = _read_json(opportunity_status_path)
    assert projection["status"] == expected_status
    assert projection["attempt_id"] == latest_attempt_id
    assert projection["reason_code"] == expected_reason


def test_projection_repair_uses_highest_ordinal_not_a_terminal_historical_attempt(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    root = runtime / "ongoing"
    opportunity_path = next((root / "opportunities").glob("*/request.json"))
    opportunity = _read_json(opportunity_path)

    first, first_paths = ongoing._next_attempt(root, opportunity)
    ongoing._write_attempt_status(
        first_paths["status"],
        attempt_id=str(first["attempt_id"]),
        opportunity_id=str(opportunity["opportunity_id"]),
        status="SEALED",
    )
    second, second_paths = ongoing._next_attempt(root, opportunity)
    ongoing._write_attempt_status(
        second_paths["status"],
        attempt_id=str(second["attempt_id"]),
        opportunity_id=str(opportunity["opportunity_id"]),
        status="WAITING_FOR_COMPUTE",
        reason_code="COMPUTE_BUSY",
    )
    ongoing._write_opportunity_status(
        opportunity_path.with_name("status.json"),
        opportunity_id=str(opportunity["opportunity_id"]),
        status="COMPLETED",
        attempt_id=str(first["attempt_id"]),
        reason_code=None,
    )

    repaired = ongoing._repair_attempt_opportunity_projections(root)

    assert repaired == [second["attempt_id"]]
    projection = _read_json(opportunity_path.with_name("status.json"))
    assert projection["status"] == "WAITING_FOR_COMPUTE"
    assert projection["attempt_id"] == second["attempt_id"]
    assert projection["reason_code"] == "COMPUTE_BUSY"


def test_attempt_request_crash_before_status_reuses_ordinal_one_on_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(ongoing, "DEFAULT_QUOTA_ROOT", tmp_path / "quota")
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    real_write_attempt_status = ongoing._write_attempt_status

    class InjectedStatusGapCrash(BaseException):
        pass

    def crash_before_first_status(path: Path, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("status") == "CLAIMING_COMPUTE":
            raise InjectedStatusGapCrash()
        return real_write_attempt_status(path, **kwargs)

    monkeypatch.setattr(ongoing, "_write_attempt_status", crash_before_first_status)
    with pytest.raises(InjectedStatusGapCrash):
        ongoing.reconcile_ongoing(runtime)

    root = runtime / "ongoing"
    request_path = next((root / "attempts").glob("*/request.json"))
    request = _read_json(request_path)
    assert request["ordinal"] == 1
    assert not request_path.with_name("status.json").exists()

    monkeypatch.setattr(ongoing, "_write_attempt_status", real_write_attempt_status)
    claims: list[str] = []

    def busy(
        _contract: dict[str, Any],
        *,
        attempt_id: str,
        opportunity_id: str,
        workspace: Path,
    ) -> dict[str, Any]:
        del opportunity_id, workspace
        claims.append(attempt_id)
        return {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"}

    monkeypatch.setattr(ongoing, "_claim_capacity", busy)
    restarted = ongoing.reconcile_ongoing(runtime)

    assert restarted["outcome"] == "WAITING_FOR_COMPUTE"
    assert restarted["attempt_id"] == request["attempt_id"]
    assert claims == [request["attempt_id"]]
    requests = list((root / "attempts").glob("*/request.json"))
    assert requests == [request_path]
    assert _read_json(request_path.with_name("status.json"))["status"] == "WAITING_FOR_COMPUTE"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("account_slot", "C"),
        ("slot", 4),
        ("run_id", "0" * 64),
        ("lineage_id", "1" * 64),
        ("workspace", "OTHER_WORKSPACE"),
        ("path", "OTHER_LEASE_PATH"),
        ("lease_id", "forged-lease-id"),
        ("status", "BOUND"),
    ],
)
def test_nested_reserved_lease_identity_drift_is_fail_closed_without_touching_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)

    class FakeRunner:
        pid = 8123

    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: FakeRunner(),
    )
    launched = ongoing.reconcile_ongoing(runtime)
    attempt_id = str(launched["attempt_id"])
    root = runtime / "ongoing"
    identity_path = root / "attempts" / attempt_id / "lease_identity.json"
    identity = _read_json(identity_path)
    quota_path = Path(identity["lease_path"])
    exact_quota_bytes = quota_path.read_bytes()
    reserved = dict(identity["reserved_lease"])
    if field == "workspace":
        replacement = str((tmp_path / str(replacement)).resolve(strict=False))
    elif field == "path":
        replacement = str((quota_path.parent / "world-turn-04.json").resolve(strict=False))
    reserved[field] = replacement
    identity["reserved_lease"] = reserved
    _write_json(identity_path, identity)

    with pytest.raises(ongoing.OngoingError) as raised:
        ongoing._lease_identity(root, attempt_id)

    assert raised.value.reason_code.startswith("LEASE_")
    assert quota_path.read_bytes() == exact_quota_bytes
    assert released == []
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


def test_preparing_crash_recovers_only_the_exact_provable_reserved_lease_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    quota_root = tmp_path / "quota"
    monkeypatch.setattr(ongoing, "DEFAULT_QUOTA_ROOT", quota_root)
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    releases: list[dict[str, Any]] = []

    class FakeQuota:
        def release(self, lease: dict[str, Any]) -> str:
            releases.append(dict(lease))
            return "RELEASED"

    quota = FakeQuota()

    def claim(
        _contract: dict[str, Any],
        *,
        attempt_id: str,
        opportunity_id: str,
        workspace: Path,
    ) -> dict[str, Any]:
        lease_path = quota_root / "A" / "world-turn-01.json"
        persisted_lease = {
            "schema": ongoing.WORLD_TURN_QUOTA_LEASE_SCHEMA,
            "lease_id": "provable-reserved-lease",
            "run_id": attempt_id,
            "lineage_id": opportunity_id,
            "account_slot": "A",
            "slot": 1,
            "limit": 4,
            "counted": True,
            "status": "RESERVED",
            "workspace": str(workspace),
            "controller_pid": os.getpid(),
            "child_pid": None,
            "reserved_at": "2026-08-15T00:00:00+00:00",
            "bound_at": None,
            "released_at": None,
            "experiment_candidate_only": True,
        }
        _write_json(lease_path, persisted_lease)
        lease = {**persisted_lease, "path": str(lease_path.resolve(strict=False))}
        return {"outcome": "CLAIMED", "quota": quota, "lease": lease}

    monkeypatch.setattr(ongoing, "_claim_capacity", claim)
    monkeypatch.setattr(ongoing, "_quota_from_identity", lambda _identity: quota)
    real_write_attempt_status = ongoing._write_attempt_status
    armed = {"value": True}

    class InjectedPreparingCrash(BaseException):
        pass

    def crash_after_preparing(path: Path, **kwargs: Any) -> dict[str, Any]:
        value = real_write_attempt_status(path, **kwargs)
        if kwargs.get("status") == "PREPARING" and armed["value"]:
            armed["value"] = False
            raise InjectedPreparingCrash()
        return value

    monkeypatch.setattr(ongoing, "_write_attempt_status", crash_after_preparing)
    with pytest.raises(InjectedPreparingCrash):
        ongoing.reconcile_ongoing(runtime)

    monkeypatch.setattr(ongoing, "_write_attempt_status", real_write_attempt_status)
    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    identity = _read_json(attempt_directory / "lease_identity.json")
    exact_reserved = _read_json(Path(identity["lease_path"]))
    assert identity["lease_id"] == exact_reserved["lease_id"]
    assert exact_reserved["status"] == "RESERVED"
    assert _read_json(attempt_directory / "status.json")["status"] == "PREPARING"

    recovered = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"preparing recovery reached Popen: {args!r} {kwargs!r}"
        ),
    )

    assert recovered["launched_attempt_ids"] == []
    assert len(releases) == 1
    assert releases[0]["lease_id"] == exact_reserved["lease_id"]
    assert releases[0]["run_id"] == exact_reserved["run_id"]
    assert releases[0]["lineage_id"] == exact_reserved["lineage_id"]
    assert releases[0]["status"] == "RESERVED"
    assert len(list((runtime / "ongoing" / "attempts").glob("*/request.json"))) == 1
    assert _read_json(attempt_directory / "status.json")["status"] == "RETRYABLE"
    assert (
        _read_json(next((runtime / "ongoing" / "opportunities").glob("*/status.json")))["status"]
        == "RETRYABLE"
    )
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


def test_detached_runner_bootstrap_is_valid_python_source() -> None:
    source = ongoing._runner_bootstrap_source()

    compile(source, "<ongoing-runner-bootstrap>", "exec")
    assert "encode('utf-8')+b'\\n'" in source


def test_production_runner_recovery_uses_job_state_and_never_duplicates_the_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    spawn_calls: list[dict[str, Any]] = []

    class FakeRunner:
        pid = 8123

    def spawn(
        runtime_root: Path,
        attempt_id: str,
        paths: dict[str, Path],
        *,
        request: dict[str, Any],
        request_sha256: str,
        launch_nonce: str,
    ) -> FakeRunner:
        assert request == _read_json(paths["runner_request"])
        assert request_sha256 == _sha256(paths["runner_request"].read_bytes())
        assert launch_nonce == ongoing._stable_id(
            {
                "attempt_id": attempt_id,
                "runner_request_id": request["runner_request_id"],
                "runner_request_sha256": request_sha256,
            }
        )
        intent = _read_json(paths["runner_launch_intent"])
        assert intent["runner_request_sha256"] == request_sha256
        assert intent["launch_nonce"] == launch_nonce
        spawn_calls.append(
            {
                "runtime_root": runtime_root,
                "attempt_id": attempt_id,
                "request_sha256": request_sha256,
                "launch_nonce": launch_nonce,
            }
        )
        return FakeRunner()

    monkeypatch.setattr(ongoing, "_spawn_detached_runner", spawn)
    monkeypatch.setattr(
        ongoing,
        "_run_attempt_runner",
        lambda *_args, **_kwargs: pytest.fail("scheduled-task tick waited in the runner"),
    )

    launched = ongoing.reconcile_ongoing(runtime)

    assert launched["outcome"] == "RUNNING"
    assert len(spawn_calls) == 1
    assert launched["runner_pid"] == FakeRunner.pid
    assert released == []
    attempt_id = str(launched["attempt_id"])
    attempt_directory = runtime / "ongoing" / "attempts" / attempt_id
    identity = _read_json(attempt_directory / "lease_identity.json")
    quota_path = Path(identity["lease_path"])
    assert _read_json(quota_path)["status"] == "RESERVED"

    monkeypatch.setattr(
        ongoing,
        "_job_snapshot",
        lambda actual_attempt_id: _job_snapshot(actual_attempt_id, ongoing.JobState.UNKNOWN),
    )
    monkeypatch.setattr(ongoing, "_process_liveness", lambda _pid: "UNKNOWN")
    unknown = ongoing.reconcile_ongoing(runtime)
    assert unknown["outcome"] == "RUNNING_UNKNOWN"
    assert unknown["reason_code"] == "JOB_LIVENESS_UNKNOWN"
    assert len(spawn_calls) == 1
    assert released == []

    monkeypatch.setattr(
        ongoing,
        "_job_snapshot",
        lambda actual_attempt_id: _job_snapshot(
            actual_attempt_id,
            ongoing.JobState.PRESENT_NONEMPTY,
            9777,
        ),
    )
    monkeypatch.setattr(ongoing, "_process_liveness", lambda _pid: "DEAD")
    owned = ongoing.reconcile_ongoing(runtime)
    assert owned["outcome"] == "RUNNING"
    assert owned["reason_code"] == "KERNEL_JOB_OWNS_PROCESS_TREE"
    assert len(spawn_calls) == 1
    assert released == []
    assert _read_json(quota_path)["status"] == "RESERVED"
    status = _read_json(attempt_directory / "status.json")
    assert status["status"] == "CHILD_SPAWNED"
    assert status["lease"]["status"] == "RESERVED"

    monkeypatch.setattr(
        ongoing,
        "_job_snapshot",
        lambda actual_attempt_id: _job_snapshot(actual_attempt_id, ongoing.JobState.ABSENT),
    )
    terminal = ongoing.reconcile_ongoing(runtime)
    assert terminal["outcome"] == "RETRYABLE"
    assert terminal["reason_code"] == "KERNEL_JOB_TERMINAL_RECOVERED"
    assert len(spawn_calls) == 1
    assert len(released) == 1
    assert released[0][1]["status"] == "RESERVED"
    assert _read_json(quota_path)["status"] == "RELEASED"
    assert _read_json(attempt_directory / "status.json")["status"] == "RETRYABLE"


@pytest.mark.parametrize(
    "terminal_job_state",
    [ongoing.JobState.ABSENT, ongoing.JobState.PRESENT_EMPTY],
)
def test_launch_intent_without_spawn_receipt_releases_only_after_job_terminal_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_job_state: ongoing.JobState,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    spawn_calls: list[str] = []

    class FakeRunner:
        pid = 8123

    def spawn(
        _runtime: Path, attempt_id: str, _paths: dict[str, Path], **_kwargs: Any
    ) -> FakeRunner:
        spawn_calls.append(attempt_id)
        return FakeRunner()

    monkeypatch.setattr(ongoing, "_spawn_detached_runner", spawn)
    real_write_once_json = ongoing._write_once_json

    class InjectedPreReceiptCrash(BaseException):
        pass

    def crash_before_spawn_receipt(path: Path, value: object, **kwargs: Any) -> None:
        if path.name == "runner_spawn.json":
            raise InjectedPreReceiptCrash()
        real_write_once_json(path, value, **kwargs)

    monkeypatch.setattr(ongoing, "_write_once_json", crash_before_spawn_receipt)
    with pytest.raises(InjectedPreReceiptCrash):
        ongoing.reconcile_ongoing(runtime)
    monkeypatch.setattr(ongoing, "_write_once_json", real_write_once_json)
    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    attempt_id = attempt_directory.name
    attempt_directory = runtime / "ongoing" / "attempts" / attempt_id
    assert _read_json(attempt_directory / "status.json")["status"] == "LAUNCHING"
    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: pytest.fail("ambiguous launch intent was respawned"),
    )
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail("same attempt claimed capacity again"),
    )
    monkeypatch.setattr(
        ongoing,
        "_job_snapshot",
        lambda actual_attempt_id: _job_snapshot(actual_attempt_id, terminal_job_state),
    )

    replay = ongoing.reconcile_ongoing(runtime)

    assert replay["outcome"] == "RETRYABLE"
    assert replay["reason_code"] == "RUNNER_SPAWN_GAP_JOB_TERMINAL"
    assert spawn_calls == [attempt_id]
    assert len(released) == 1
    assert released[0][1]["status"] == "RESERVED"
    assert (attempt_directory / "runner_launch_intent.json").is_file()
    assert not (attempt_directory / "runner_spawn.json").exists()
    assert not (attempt_directory / "runner_started.json").exists()
    assert _read_json(attempt_directory / "status.json")["status"] == "RETRYABLE"
    assert len(list((runtime / "ongoing" / "attempts").glob("*/request.json"))) == 1
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


def test_spawn_receipt_is_adopted_after_status_write_crash_without_second_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    spawn_calls: list[str] = []

    class FakeRunner:
        pid = 8123

    def spawn(
        _runtime: Path, attempt_id: str, _paths: dict[str, Path], **_kwargs: Any
    ) -> FakeRunner:
        spawn_calls.append(attempt_id)
        return FakeRunner()

    monkeypatch.setattr(ongoing, "_spawn_detached_runner", spawn)
    real_write_attempt_status = ongoing._write_attempt_status

    class InjectedPostSpawnCrash(BaseException):
        pass

    def crash_before_runner_starting(path: Path, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("status") == "RUNNER_STARTING":
            raise InjectedPostSpawnCrash()
        return real_write_attempt_status(path, **kwargs)

    monkeypatch.setattr(ongoing, "_write_attempt_status", crash_before_runner_starting)
    with pytest.raises(InjectedPostSpawnCrash):
        ongoing.reconcile_ongoing(runtime)
    monkeypatch.setattr(ongoing, "_write_attempt_status", real_write_attempt_status)
    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    attempt_id = attempt_directory.name
    attempt_directory = runtime / "ongoing" / "attempts" / attempt_id
    spawn_path = attempt_directory / "runner_spawn.json"
    spawn_bytes = spawn_path.read_bytes()
    assert _read_json(attempt_directory / "status.json")["status"] == "LAUNCHING"
    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: pytest.fail(
            "valid runner spawn receipt was ignored and respawned"
        ),
    )
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail("spawn-receipt replay claimed capacity again"),
    )
    probed: list[int | None] = []

    def alive(pid: int | None) -> str:
        probed.append(pid)
        return "ALIVE"

    monkeypatch.setattr(ongoing, "_process_liveness", alive)
    monkeypatch.setattr(
        ongoing,
        "_job_snapshot",
        lambda actual_attempt_id: _job_snapshot(
            actual_attempt_id,
            ongoing.JobState.PRESENT_NONEMPTY,
            9777,
        ),
    )
    replay = ongoing.reconcile_ongoing(runtime)

    assert replay["outcome"] == "RUNNING"
    assert replay["reason_code"] == "KERNEL_JOB_OWNS_PROCESS_TREE"
    assert replay["runner_pid"] == FakeRunner.pid
    assert probed == [FakeRunner.pid]
    assert spawn_calls == [attempt_id]
    assert spawn_path.read_bytes() == spawn_bytes
    assert released == []
    recovered_status = _read_json(attempt_directory / "status.json")
    assert recovered_status["status"] == "CHILD_SPAWNED"
    assert recovered_status["runner_pid"] == FakeRunner.pid
    assert recovered_status["lease"]["status"] == "RESERVED"
    assert len(list((runtime / "ongoing" / "attempts").glob("*/request.json"))) == 1


def test_started_job_receipt_is_adopted_while_production_quota_stays_reserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    quota_root = tmp_path / "quota"
    monkeypatch.setattr(ongoing, "DEFAULT_QUOTA_ROOT", quota_root)
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)

    class FakeRunner:
        pid = 8123

    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: FakeRunner(),
    )
    launched = ongoing.reconcile_ongoing(runtime)
    attempt_id = str(launched["attempt_id"])
    attempt_directory = runtime / "ongoing" / "attempts" / attempt_id
    attempt = _read_json(attempt_directory / "request.json")
    identity = _read_json(attempt_directory / "lease_identity.json")
    child_pid = 9777
    reserved_lease = {
        **identity["reserved_lease"],
        "schema": ongoing.WORLD_TURN_QUOTA_LEASE_SCHEMA,
        "run_id": attempt_id,
        "lineage_id": attempt["opportunity_id"],
        "account_slot": identity["account_slot"],
        "slot": identity["slot"],
        "limit": identity["limit"],
        "counted": True,
        "status": "RESERVED",
        "child_pid": None,
        "workspace": str(attempt["workspace"]),
        "controller_pid": os.getpid(),
        "reserved_at": "2026-08-15T00:00:00+00:00",
        "bound_at": None,
        "released_at": None,
        "experiment_candidate_only": True,
    }
    _write_json(
        Path(identity["lease_path"]),
        {key: value for key, value in reserved_lease.items() if key != "path"},
    )
    spawn = _read_json(attempt_directory / "runner_spawn.json")
    command = _read_json(attempt_directory / "command.json")
    started_unsigned = {
        "schema": ongoing.RUNNER_STARTED_SCHEMA,
        "attempt_id": attempt_id,
        "runner_request_id": spawn["runner_request_id"],
        "runner_request_sha256": spawn["runner_request_sha256"],
        "launch_nonce": spawn["launch_nonce"],
        "job_identity_id": identity["job_identity"]["job_identity_id"],
        "job_name": identity["job_identity"]["job_name"],
        "runner_pid": FakeRunner.pid,
        "child_pid": child_pid,
        "started_at": "2026-08-15T00:00:00+00:00",
        "command_sha256": ongoing._stable_id(command["argv"]),
        "protocol_stage": ongoing.PROTOCOL_STAGE,
        "authority": False,
        "shared_effect_authorized": False,
        "completion_claim_allowed": False,
    }
    started = {
        **started_unsigned,
        "started_seal_sha256": _sha256(ongoing.canonical_json_bytes(started_unsigned)),
    }
    _write_json(attempt_directory / "runner_started.json", started)
    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: pytest.fail("started child was duplicated"),
    )
    monkeypatch.setattr(
        ongoing,
        "_claim_capacity",
        lambda *_args, **_kwargs: pytest.fail("started child claimed capacity again"),
    )
    monkeypatch.setattr(
        ongoing,
        "_release_capacity",
        lambda *_args, **_kwargs: pytest.fail("live started child lease was released"),
    )
    monkeypatch.setattr(ongoing, "_process_liveness", lambda _pid: "ALIVE")
    monkeypatch.setattr(
        ongoing,
        "_job_snapshot",
        lambda actual_attempt_id: _job_snapshot(
            actual_attempt_id,
            ongoing.JobState.PRESENT_NONEMPTY,
            child_pid,
        ),
    )

    replay = ongoing.reconcile_ongoing(runtime)

    assert replay["outcome"] == "RUNNING"
    assert replay["reason_code"] == "KERNEL_JOB_OWNS_PROCESS_TREE"
    recovered_status = _read_json(attempt_directory / "status.json")
    assert recovered_status["status"] == "RUNNING"
    assert recovered_status["runner_pid"] == FakeRunner.pid
    assert recovered_status["child_pid"] == child_pid
    assert recovered_status["lease"]["lease_id"] == reserved_lease["lease_id"]
    assert recovered_status["lease"]["status"] == "RESERVED"
    assert recovered_status["lease"]["child_pid"] is None
    assert released == []
    assert len(list((runtime / "ongoing" / "attempts").glob("*/request.json"))) == 1


def test_inline_popen_timeout_uses_test_only_pid_helper_then_seals_and_releases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path, timeout_seconds=1)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []

    class TimeoutProcess(_FakeProcess):
        def __init__(
            self,
            stdout_text: str,
            final: object,
            command: list[str],
            **kwargs: object,
        ) -> None:
            super().__init__(calls, stdout_text, final, command, **kwargs)
            self.returncode = None

        def communicate(
            self, input: str | bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            self.communicated_input = input
            self.communicate_timeout = timeout
            raise subprocess.TimeoutExpired("fake-model", timeout)

        def wait(self, timeout: float | None = None) -> int:
            assert timeout == 30
            assert self.returncode is not None
            return self.returncode

    final = _candidate_final(disposition="WAIT")
    stdout_text = _jsonl_events(final)

    def factory(command: list[str], **kwargs: object) -> TimeoutProcess:
        return TimeoutProcess(stdout_text, final, command, **kwargs)

    terminated: list[_FakeProcess] = []

    def terminate_exact(process: _FakeProcess) -> None:
        terminated.append(process)
        process.terminated = True
        process.returncode = 124

    monkeypatch.setattr(ongoing, "terminate_process_tree", terminate_exact)

    result = ongoing.reconcile_ongoing(runtime, popen_factory=factory)

    assert result["outcome"] == "RETRYABLE"
    assert len(calls) == 1
    process = calls[0]["process"]
    assert terminated == [process]
    assert process.communicate_timeout == 1
    assert len(released) == 1
    released_lease = released[0][1]
    assert isinstance(released_lease, dict)
    assert released_lease["lease_id"] == "quota-fixture-1"
    assert released_lease["child_pid"] == process.pid
    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    terminal = _read_json(attempt_directory / "runner_terminal.json")
    assert terminal["child_pid"] == process.pid
    assert terminal["timed_out"] is True
    assert terminal["error_code"] == "MODEL_TIMEOUT"
    assert terminal["exit_code"] == 124
    assert terminal["release_status"] == "RELEASED"
    status = _read_json(attempt_directory / "status.json")
    assert status["status"] == "TERMINAL_FAILED"
    assert status["reason_code"] == "MODEL_TIMEOUT"
    opportunity_status = _read_json(
        next((runtime / "ongoing" / "opportunities").glob("*/status.json"))
    )
    assert opportunity_status["status"] == "RETRYABLE"


def test_inline_popen_timeout_with_unconfirmed_death_keeps_lease_and_blocks_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path, timeout_seconds=1)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []

    class UnkillableTimeoutProcess(_FakeProcess):
        def __init__(
            self,
            stdout_text: str,
            final: object,
            command: list[str],
            **kwargs: object,
        ) -> None:
            super().__init__(calls, stdout_text, final, command, **kwargs)
            self.returncode = None

        def communicate(
            self, input: str | bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            self.communicated_input = input
            self.communicate_timeout = timeout
            raise subprocess.TimeoutExpired("fake-model", timeout)

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired("fake-model-still-alive", timeout)

    final = _candidate_final(disposition="WAIT")
    stdout_text = _jsonl_events(final)

    def factory(command: list[str], **kwargs: object) -> UnkillableTimeoutProcess:
        return UnkillableTimeoutProcess(stdout_text, final, command, **kwargs)

    termination_attempts: list[_FakeProcess] = []
    monkeypatch.setattr(
        ongoing,
        "terminate_process_tree",
        lambda process: termination_attempts.append(process),
    )

    result = ongoing.reconcile_ongoing(runtime, popen_factory=factory)

    assert len(calls) == 1
    assert termination_attempts == [calls[0]["process"]]
    assert result["outcome"] != "RETRYABLE"
    assert released == []
    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    assert not (attempt_directory / "runner_terminal.json").exists()
    opportunity_status_path = next((runtime / "ongoing" / "opportunities").glob("*/status.json"))
    assert _read_json(opportunity_status_path)["status"] != "RETRYABLE"

    repeated = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=lambda *args, **kwargs: pytest.fail(
            f"unconfirmed-live child duplicated: {args!r} {kwargs!r}"
        ),
    )
    assert repeated["launched_attempt_ids"] == []
    assert len(calls) == 1
    assert released == []


def test_inline_popen_failure_releases_the_exact_reserved_lease_before_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    def fail_before_child(command: list[str], **kwargs: object) -> object:
        popen_calls.append((list(command), dict(kwargs)))
        raise OSError("fixture failed before child creation")

    result = ongoing.reconcile_ongoing(runtime, popen_factory=fail_before_child)

    assert result["outcome"] == "RETRYABLE"
    assert len(popen_calls) == 1
    assert len(released) == 1
    reserved_lease = released[0][1]
    assert isinstance(reserved_lease, dict)
    assert reserved_lease["lease_id"] == "quota-fixture-1"
    assert reserved_lease["status"] == "RESERVED"
    assert reserved_lease["counted"] is True
    assert reserved_lease["child_pid"] is None
    attempt_directory = next((runtime / "ongoing" / "attempts").iterdir())
    runner_request_path = attempt_directory / "runner_request.json"
    runner_request = _read_json(runner_request_path)
    launch_intent = _read_json(attempt_directory / "runner_launch_intent.json")
    assert launch_intent["runner_request_id"] == runner_request["runner_request_id"]
    assert launch_intent["runner_request_sha256"] == _sha256(runner_request_path.read_bytes())
    assert launch_intent["launch_nonce"] == ongoing._stable_id(
        {
            "attempt_id": runner_request["attempt_id"],
            "runner_request_id": runner_request["runner_request_id"],
            "runner_request_sha256": launch_intent["runner_request_sha256"],
        }
    )
    spawn = _read_json(attempt_directory / "runner_spawn.json")
    assert spawn["launch_nonce"] == launch_intent["launch_nonce"]
    assert spawn["inline_test_runner"] is True
    terminal = _read_json(attempt_directory / "runner_terminal.json")
    assert terminal["child_pid"] is None
    assert terminal["error_code"] == "RUNNER_OSERROR"
    assert terminal["release_status"] == "RELEASED"
    assert _read_json(attempt_directory / "status.json")["status"] == "TERMINAL_FAILED"

    second = ongoing.reconcile_ongoing(runtime, popen_factory=fail_before_child)

    assert second["outcome"] == "RETRYABLE"
    assert len(popen_calls) == 2
    assert len(released) == 2
    attempts = [
        _read_json(path) for path in (runtime / "ongoing" / "attempts").glob("*/request.json")
    ]
    assert sorted(attempt["ordinal"] for attempt in attempts) == [1, 2]
    opportunity_status = _read_json(
        next((runtime / "ongoing" / "opportunities").glob("*/status.json"))
    )
    assert opportunity_status["status"] == "RETRYABLE"


def test_transient_production_quota_release_failure_recovers_after_job_absent_without_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    ignored_releases: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, ignored_releases)

    class FakeRunner:
        pid = os.getpid()

    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: FakeRunner(),
    )
    launched = ongoing.reconcile_ongoing(runtime)
    attempt_id = str(launched["attempt_id"])
    attempt_directory = runtime / "ongoing" / "attempts" / attempt_id
    identity = _read_json(attempt_directory / "lease_identity.json")
    lease_path = Path(str(identity["lease_path"]))
    assert _read_json(lease_path)["status"] == "RESERVED"

    calls: list[dict[str, Any]] = []
    final = _candidate_final(disposition="WAIT")

    class CompletedJobProcess(_FakeProcess):
        def __init__(self, command: list[str], *, job_name: str, **kwargs: object) -> None:
            assert job_name == identity["job_identity"]["job_name"]
            prompt_stream = kwargs.get("stdin")
            assert prompt_stream not in {None, subprocess.PIPE}
            assert (
                Path(str(prompt_stream.name)).resolve()
                == (attempt_directory / "prompt.txt").resolve()
            )
            assert prompt_stream.read() == (attempt_directory / "prompt.txt").read_bytes()
            prompt_stream.seek(0)
            super().__init__(calls, _jsonl_events(final), final, command, **kwargs)
            self.stdin = None

        def job_snapshot(self) -> ongoing.JobSnapshot:
            return _job_snapshot(attempt_id, ongoing.JobState.ABSENT)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        ongoing,
        "spawn_windows_job_process",
        lambda command, *, job_name, **kwargs: CompletedJobProcess(
            command, job_name=job_name, **kwargs
        ),
    )
    release_attempts: list[dict[str, Any]] = []

    def transient_then_release(_quota: object, lease: object) -> str:
        assert isinstance(lease, dict)
        release_attempts.append(dict(lease))
        if len(release_attempts) == 1:
            return "RELEASE_TIMEOUT"
        persisted = _read_json(Path(str(lease["path"])))
        assert persisted["lease_id"] == lease["lease_id"]
        assert persisted["status"] == "RESERVED"
        persisted.update({"status": "RELEASED", "released_at": ongoing._now_iso()})
        _write_json(Path(str(lease["path"])), persisted)
        return "RELEASED"

    monkeypatch.setattr(ongoing, "_release_capacity", transient_then_release)

    result = ongoing._run_attempt_runner(
        runtime,
        attempt_id,
        expected_request_sha256=_sha256((attempt_directory / "runner_request.json").read_bytes()),
        launch_nonce=str(
            _read_json(attempt_directory / "runner_launch_intent.json")["launch_nonce"]
        ),
    )

    assert result["outcome"] == "FAILED_UNKNOWN"
    assert result["reason_code"] == "QUOTA_RELEASE_TIMEOUT"
    assert len(calls) == 1
    assert len(release_attempts) == 1
    assert release_attempts[0]["lease_id"] == identity["lease_id"]
    assert release_attempts[0]["status"] == "RESERVED"
    assert release_attempts[0]["child_pid"] is None
    assert not (attempt_directory / "runner_terminal.json").exists()
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))
    assert result.get("candidate_id") is None
    assert _read_json(attempt_directory / "status.json")["status"] == "FAILED_UNKNOWN"
    assert _read_json(lease_path)["status"] == "RESERVED"

    monkeypatch.setattr(
        ongoing,
        "_job_snapshot",
        lambda actual_attempt_id: _job_snapshot(actual_attempt_id, ongoing.JobState.ABSENT),
    )
    recovered = ongoing.reconcile_ongoing(runtime)

    assert recovered["outcome"] == "RETRYABLE"
    assert recovered["attempt_id"] == attempt_id
    assert recovered["reason_code"] == "KERNEL_JOB_TERMINAL_RECOVERED"
    assert len(release_attempts) == 2
    assert release_attempts[1]["lease_id"] == identity["lease_id"]
    assert release_attempts[1]["status"] == "RESERVED"
    assert _read_json(lease_path)["status"] == "RELEASED"
    assert _read_json(attempt_directory / "status.json")["status"] == "RETRYABLE"
    assert not (attempt_directory / "runner_terminal.json").exists()
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))

    retried_attempts: list[str] = []

    def retry_busy(
        _contract: dict[str, Any],
        *,
        attempt_id: str,
        opportunity_id: str,
        workspace: Path,
    ) -> dict[str, Any]:
        del opportunity_id, workspace
        retried_attempts.append(attempt_id)
        return {"outcome": "BUSY", "reason_code": "COMPUTE_BUSY"}

    monkeypatch.setattr(ongoing, "_claim_capacity", retry_busy)
    retried = ongoing.reconcile_ongoing(runtime)
    assert retried["outcome"] == "WAITING_FOR_COMPUTE"
    assert retried_attempts == [retried["attempt_id"]]
    assert retried["attempt_id"] != attempt_id
    assert len(list((runtime / "ongoing" / "attempts").glob("*/request.json"))) == 2
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


def test_stop_tick_terminates_named_job_then_releases_reserved_capacity_without_pid_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    bound = ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)

    class FakeRunner:
        pid = 8123

    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: FakeRunner(),
    )
    launched = ongoing.reconcile_ongoing(runtime)
    attempt_id = str(launched["attempt_id"])
    attempt_directory = runtime / "ongoing" / "attempts" / attempt_id
    identity = _read_json(attempt_directory / "lease_identity.json")
    assert _read_json(Path(identity["lease_path"]))["status"] == "RESERVED"
    monkeypatch.setattr(ongoing, "_process_liveness", lambda pid: "ALIVE" if pid else "DEAD")
    monkeypatch.setattr(
        ongoing,
        "_terminate_pid",
        lambda pid: pytest.fail(f"stop task tick PID-killed {pid}"),
    )
    monkeypatch.setattr(
        ongoing,
        "terminate_process_tree",
        lambda process: pytest.fail(f"stop task tick used process-tree helper: {process!r}"),
    )
    snapshots = [
        _job_snapshot(attempt_id, ongoing.JobState.PRESENT_NONEMPTY, 777),
        _job_snapshot(attempt_id, ongoing.JobState.PRESENT_EMPTY),
    ]
    monkeypatch.setattr(ongoing, "_job_snapshot", lambda _attempt_id: snapshots.pop(0))
    terminated_jobs: list[str] = []

    def terminate_job(actual_attempt_id: str) -> ongoing.JobSnapshot:
        terminated_jobs.append(actual_attempt_id)
        return _job_snapshot(actual_attempt_id, ongoing.JobState.PRESENT_NONEMPTY, 777)

    monkeypatch.setattr(ongoing, "_terminate_job", terminate_job)

    stopped = ongoing.stop_ongoing_contract(
        runtime,
        expected_revision_id=str(bound["revision_id"]),
    )

    assert stopped["outcome"] == "STOPPED"
    assert stopped["pid_only_taskkill_used"] is False
    assert stopped["runner_owned_termination"] is True
    assert stopped["process_readback"] == [
        {"role": "RUNNER", "pid": FakeRunner.pid, "liveness": "ALIVE"},
        {"role": "MODEL_CHILD", "pid": None, "liveness": "NO_RECEIPT"},
    ]
    assert terminated_jobs == [attempt_id]
    assert len(released) == 1
    assert released[0][1]["status"] == "RESERVED"
    stopped_status = _read_json(attempt_directory / "status.json")
    assert stopped_status["status"] == "STOPPED"
    assert stopped_status["child_pid"] is None
    assert _read_json(Path(identity["lease_path"]))["status"] == "RELEASED"


def test_production_timeout_terminates_named_job_and_never_binds_or_pid_kills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(
        tmp_path,
        timeout_seconds=1,
    )
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)

    class FakeRunner:
        pid = os.getpid()

    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: FakeRunner(),
    )
    launched = ongoing.reconcile_ongoing(runtime)
    attempt_id = str(launched["attempt_id"])
    attempt_directory = runtime / "ongoing" / "attempts" / attempt_id
    identity = _read_json(attempt_directory / "lease_identity.json")
    reserved_lease = identity["reserved_lease"]
    request_sha256 = _sha256((attempt_directory / "runner_request.json").read_bytes())
    launch_nonce = _read_json(attempt_directory / "runner_launch_intent.json")["launch_nonce"]
    assert 0 < (attempt_directory / "prompt.txt").stat().st_size < 64 * 1024
    monkeypatch.setattr(
        ongoing,
        "terminate_process_tree",
        lambda process: pytest.fail(f"production timeout used PID-tree authority: {process!r}"),
    )
    calls: list[dict[str, Any]] = []
    final = _candidate_final(disposition="WAIT")
    terminated_jobs: list[str] = []

    class TimeoutJobProcess(_FakeProcess):
        def __init__(self, command: list[str], *, job_name: str, **kwargs: object) -> None:
            assert job_name == identity["job_identity"]["job_name"]
            assert _read_json(Path(identity["lease_path"]))["status"] == "RESERVED"
            prompt_stream = kwargs.get("stdin")
            assert prompt_stream not in {None, subprocess.PIPE}
            assert (
                Path(str(prompt_stream.name)).resolve()
                == (attempt_directory / "prompt.txt").resolve()
            )
            assert prompt_stream.read() == (attempt_directory / "prompt.txt").read_bytes()
            prompt_stream.seek(0)
            super().__init__(calls, _jsonl_events(final), final, command, **kwargs)
            # The production runner must enter its timeout/Stop poll without
            # requiring a writable pipe or any child-side read acknowledgement.
            self.stdin = None
            self.returncode = None

        def wait(self, timeout: float | None = None) -> int:
            assert timeout == 30
            assert self.returncode is not None
            return self.returncode

        def terminate_tree(self, *, exit_code: int) -> ongoing.JobSnapshot:
            assert exit_code == 1
            terminated_jobs.append(str(identity["job_identity"]["job_name"]))
            self.returncode = 124
            return _job_snapshot(attempt_id, ongoing.JobState.PRESENT_EMPTY)

        def job_snapshot(self) -> ongoing.JobSnapshot:
            return _job_snapshot(attempt_id, ongoing.JobState.PRESENT_EMPTY)

        def close(self) -> None:
            return None

    def spawn_job(command: list[str], *, job_name: str, **kwargs: object) -> TimeoutJobProcess:
        return TimeoutJobProcess(command, job_name=job_name, **kwargs)

    class RunnerQuota:
        def bind(self, *_args: object, **_kwargs: object) -> object:
            pytest.fail("production Job carrier bound its quota lease to a child PID")

    clock = {"value": 0.0}
    monkeypatch.setattr(ongoing.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(
        ongoing.time,
        "sleep",
        lambda seconds: clock.__setitem__("value", clock["value"] + float(seconds)),
    )
    monkeypatch.setattr(ongoing, "spawn_windows_job_process", spawn_job)
    monkeypatch.setattr(ongoing, "_quota_from_identity", lambda _identity: RunnerQuota())

    runner_result = ongoing._run_attempt_runner(
        runtime,
        attempt_id,
        expected_request_sha256=request_sha256,
        launch_nonce=str(launch_nonce),
    )

    assert runner_result["outcome"] == "RETRYABLE"
    assert len(calls) == 1
    assert calls[0]["process"].stdin is None
    assert terminated_jobs == [identity["job_identity"]["job_name"]]
    assert len(released) == 1
    assert released[0][1]["lease_id"] == reserved_lease["lease_id"]
    assert released[0][1]["status"] == "RESERVED"
    assert released[0][1]["child_pid"] is None
    terminal_path = attempt_directory / "runner_terminal.json"
    terminal = _read_json(terminal_path)
    assert terminal["child_pid"] == calls[0]["process"].pid
    assert terminal["child_definitely_dead"] is True
    assert terminal["timed_out"] is True
    assert terminal["stop_requested"] is False
    assert terminal["job_terminal_state"] == ongoing.JobState.PRESENT_EMPTY.value
    assert terminal["release_status"] == "RELEASED"
    assert terminal["error_code"] == "MODEL_TIMEOUT"
    started = _read_json(attempt_directory / "runner_started.json")
    assert started["job_identity_id"] == identity["job_identity"]["job_identity_id"]
    assert started["job_name"] == identity["job_identity"]["job_name"]
    assert _read_json(attempt_directory / "status.json")["status"] == "TERMINAL_FAILED"
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


def test_production_stop_poll_starts_with_sealed_prompt_file_and_no_process_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(
        tmp_path,
        timeout_seconds=30,
    )
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)

    class FakeRunner:
        pid = os.getpid()

    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: FakeRunner(),
    )
    launched = ongoing.reconcile_ongoing(runtime)
    attempt_id = str(launched["attempt_id"])
    attempt_directory = runtime / "ongoing" / "attempts" / attempt_id
    prompt_path = attempt_directory / "prompt.txt"
    assert 0 < prompt_path.stat().st_size < 64 * 1024
    identity = _read_json(attempt_directory / "lease_identity.json")
    request_sha256 = _sha256((attempt_directory / "runner_request.json").read_bytes())
    launch_nonce = str(_read_json(attempt_directory / "runner_launch_intent.json")["launch_nonce"])
    calls: list[dict[str, Any]] = []
    final = _candidate_final(disposition="WAIT")
    terminated_jobs: list[str] = []
    spawned = {"value": False}

    class StopPolledJobProcess(_FakeProcess):
        def __init__(self, command: list[str], *, job_name: str, **kwargs: object) -> None:
            assert job_name == identity["job_identity"]["job_name"]
            prompt_stream = kwargs.get("stdin")
            assert prompt_stream not in {None, subprocess.PIPE}
            assert Path(str(prompt_stream.name)).resolve() == prompt_path.resolve()
            assert prompt_stream.read() == prompt_path.read_bytes()
            prompt_stream.seek(0)
            super().__init__(calls, _jsonl_events(final), final, command, **kwargs)
            self.stdin = None
            self.returncode = None

        def wait(self, timeout: float | None = None) -> int:
            assert timeout == 30
            assert self.returncode is not None
            return self.returncode

        def terminate_tree(self, *, exit_code: int) -> ongoing.JobSnapshot:
            assert exit_code == 1
            terminated_jobs.append(str(identity["job_identity"]["job_name"]))
            self.returncode = 143
            return _job_snapshot(attempt_id, ongoing.JobState.PRESENT_EMPTY)

        def job_snapshot(self) -> ongoing.JobSnapshot:
            return _job_snapshot(attempt_id, ongoing.JobState.PRESENT_EMPTY)

        def close(self) -> None:
            return None

    def spawn_job(command: list[str], *, job_name: str, **kwargs: object) -> StopPolledJobProcess:
        process = StopPolledJobProcess(command, job_name=job_name, **kwargs)
        spawned["value"] = True
        return process

    real_contract_is_stopped = ongoing._contract_is_stopped

    def stop_only_after_spawn(root: Path, current: dict[str, Any]) -> bool:
        return spawned["value"] or real_contract_is_stopped(root, current)

    monkeypatch.setattr(ongoing, "spawn_windows_job_process", spawn_job)
    monkeypatch.setattr(ongoing, "_contract_is_stopped", stop_only_after_spawn)

    result = ongoing._run_attempt_runner(
        runtime,
        attempt_id,
        expected_request_sha256=request_sha256,
        launch_nonce=launch_nonce,
    )

    assert result["outcome"] == "STOPPED"
    assert len(calls) == 1
    assert calls[0]["process"].stdin is None
    assert terminated_jobs == [identity["job_identity"]["job_name"]]
    assert len(released) == 1
    assert released[0][1]["status"] == "RESERVED"
    assert released[0][1]["child_pid"] is None
    terminal = _read_json(attempt_directory / "runner_terminal.json")
    assert terminal["stop_requested"] is True
    assert terminal["timed_out"] is False
    assert terminal["error_code"] == "CONTRACT_STOPPED"
    assert terminal["job_terminal_state"] == ongoing.JobState.PRESENT_EMPTY.value
    assert _read_json(attempt_directory / "status.json")["status"] == "STOPPED"
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))


def test_production_runner_preflight_rejects_released_lease_before_job_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)

    class FakeRunner:
        pid = os.getpid()

    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: FakeRunner(),
    )
    launched = ongoing.reconcile_ongoing(runtime)
    attempt_id = str(launched["attempt_id"])
    attempt_directory = runtime / "ongoing" / "attempts" / attempt_id
    identity = _read_json(attempt_directory / "lease_identity.json")
    quota_path = Path(identity["lease_path"])
    released_record = _read_json(quota_path)
    released_record.update(
        {
            "status": "RELEASED",
            "released_at": ongoing._now_iso(),
        }
    )
    _write_json(quota_path, released_record)
    released_bytes = quota_path.read_bytes()
    monkeypatch.setattr(
        ongoing,
        "spawn_windows_job_process",
        lambda *_args, **_kwargs: pytest.fail("released lease reached model Job creation"),
    )
    monkeypatch.setattr(
        ongoing,
        "terminate_process_tree",
        lambda process: pytest.fail(f"preflight failure PID-killed {process!r}"),
    )

    result = ongoing._run_attempt_runner(
        runtime,
        attempt_id,
        expected_request_sha256=_sha256((attempt_directory / "runner_request.json").read_bytes()),
        launch_nonce=str(
            _read_json(attempt_directory / "runner_launch_intent.json")["launch_nonce"]
        ),
    )

    assert result["outcome"] == "CANCELLED_BEFORE_PROCESS"
    assert result["reason_code"] == "RUNNER_RUNNER_LEASE_NOT_RESERVED"
    assert quota_path.read_bytes() == released_bytes
    assert released == []
    assert not (attempt_directory / "runner_started.json").exists()
    assert not (attempt_directory / "runner_terminal.json").exists()


@pytest.mark.parametrize(
    ("terminal_job_state", "accepted"),
    [
        (ongoing.JobState.PRESENT_EMPTY, True),
        (ongoing.JobState.ABSENT, True),
        (ongoing.JobState.PRESENT_NONEMPTY, False),
        (ongoing.JobState.UNKNOWN, False),
    ],
)
def test_production_terminal_accepts_only_empty_or_absent_exact_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_job_state: ongoing.JobState,
    accepted: bool,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)

    class FakeRunner:
        pid = os.getpid()

    monkeypatch.setattr(
        ongoing,
        "_spawn_detached_runner",
        lambda *_args, **_kwargs: FakeRunner(),
    )
    launched = ongoing.reconcile_ongoing(runtime)
    attempt_id = str(launched["attempt_id"])
    root = runtime / "ongoing"
    attempt_directory = root / "attempts" / attempt_id
    request_path = attempt_directory / "runner_request.json"
    request = _read_json(request_path)
    ongoing._write_runner_terminal(
        root,
        attempt_id,
        runner_pid=os.getpid(),
        child_pid=None,
        exit_code=0,
        timed_out=False,
        started_at=ongoing._now_iso(),
        ended_at=ongoing._now_iso(),
        release_status="RELEASED",
        error_code=None,
        runner_request_id=str(request["runner_request_id"]),
        runner_request_sha256=_sha256(request_path.read_bytes()),
        child_definitely_dead=True,
        stop_requested=False,
        job_terminal_state=terminal_job_state.value,
    )
    monkeypatch.setattr(
        ongoing,
        "_job_snapshot",
        lambda actual_attempt_id: _job_snapshot(actual_attempt_id, terminal_job_state),
    )

    if accepted:
        terminal = ongoing._read_runner_terminal(root, attempt_id)
        assert terminal["job_terminal_state"] == terminal_job_state.value
        assert terminal["child_definitely_dead"] is True
    else:
        with pytest.raises(ongoing.OngoingError) as raised:
            ongoing._read_runner_terminal(root, attempt_id)
        assert raised.value.reason_code == "RUNNER_TERMINAL_JOB_INVALID"


def test_old_research_ontology_inside_payload_is_opaque_and_never_creates_an_opportunity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    bare = _candidate_final()
    bare["payload"] = json.dumps(
        {
            "disposition": "CONTINUE",
            "parent_delta": {"survives": [], "dies": []},
            "world_surface_debt": [],
            "settlement_plan": {"kind": "NONE"},
        }
    )
    calls: list[dict[str, Any]] = []

    result = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, bare),
    )

    assert len(calls) == 1
    assert result["new_opportunity_ids"] == []
    assert len(list((runtime / "ongoing" / "opportunities").glob("*/request.json"))) == 1
    candidate = _read_json(next((runtime / "ongoing" / "candidates").glob("*.json")))
    assert candidate["carrier_result"] == "OPAQUE_CANDIDATE_PAYLOAD_SEALED"
    assert candidate["candidate_payload"] == bare["payload"]
    assert candidate["continuation_authorized"] is False
    for key in ("authority", "shared_effect_authorized", "completion_claim_allowed"):
        assert candidate[key] is False


@pytest.mark.parametrize("final", ["not-an-object", {"payload": ""}])
def test_malformed_final_output_cannot_continue_or_create_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final: object,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    calls: list[dict[str, Any]] = []

    result = ongoing.reconcile_ongoing(
        runtime,
        popen_factory=_popen_factory(calls, final),
    )

    assert len(calls) == 1
    assert result["new_opportunity_ids"] == []
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))
    assert len(list((runtime / "ongoing" / "opportunities").glob("*/request.json"))) == 1
    status = _read_json(next((runtime / "ongoing" / "attempts").glob("*/status.json")))
    assert status["status"] == "INVALID_OUTPUT"
    assert status["shared_effect_authorized"] is False
    assert status["completion_claim_allowed"] is False


def test_unsafe_structured_output_is_rejected_before_candidate_or_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    contract_path, _contract = _contract_fixture(tmp_path)
    ongoing.initialize_ongoing_contract(runtime, contract_path)
    released: list[tuple[object, object]] = []
    _install_available_capacity(monkeypatch, released)
    unsafe = _candidate_final()
    unsafe["authority"] = True
    calls: list[dict[str, Any]] = []

    ongoing.reconcile_ongoing(runtime, popen_factory=_popen_factory(calls, unsafe))

    assert len(calls) == 1
    assert not list((runtime / "ongoing" / "candidates").glob("*.json"))
    assert len(list((runtime / "ongoing" / "opportunities").glob("*/request.json"))) == 1
    status = _read_json(next((runtime / "ongoing" / "attempts").glob("*/status.json")))
    assert status["status"] == "INVALID_OUTPUT"
    assert status["authority"] is False
    assert status["shared_effect_authorized"] is False
    assert status["completion_claim_allowed"] is False
