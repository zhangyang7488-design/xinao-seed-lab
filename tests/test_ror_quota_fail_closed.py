from __future__ import annotations

import errno
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from services.research_of_research import cell as cell_module
from services.xinao_perpetual_world_compute import controller as controller_module
from services.xinao_perpetual_world_compute.controller import (
    RUN_SCHEMA,
    WORLD_TURN_QUOTA_LEASE_SCHEMA,
    PerpetualController,
    ProcessLiveness,
)


def _tasklist_result(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_windows_process_liveness_requires_an_exact_pid_csv_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        controller_module.subprocess,
        "run",
        lambda *_args, **_kwargs: _tasklist_result(
            stdout='"python.exe","4321","Console","1","12,345 K"\r\n'
        ),
    )

    assert controller_module._windows_process_liveness(4321) == ProcessLiveness.ALIVE


def test_windows_process_liveness_accepts_only_explicit_no_match_as_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        controller_module.subprocess,
        "run",
        lambda *_args, **_kwargs: _tasklist_result(
            stdout="INFO: No tasks are running which match the specified criteria.\r\n"
        ),
    )

    assert controller_module._windows_process_liveness(4321) == ProcessLiveness.DEAD


@pytest.mark.parametrize(
    "result",
    [
        _tasklist_result(returncode=1, stderr="tasklist failed"),
        subprocess.TimeoutExpired(cmd="tasklist", timeout=15),
    ],
)
def test_windows_process_liveness_fails_closed_on_tasklist_failure(
    result: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(*_args: object, **_kwargs: object) -> object:
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(controller_module.subprocess, "run", run)

    assert controller_module._windows_process_liveness(4321) == ProcessLiveness.UNKNOWN


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        '"python.exe","9999","Console","1","1 K"',
        '"python.exe","4321","Console","1","1 K"\n"other.exe","4321","Console","1","1 K"',
        '"python.exe","4321"',
        "INFO: an unrecognized tasklist diagnostic",
    ],
)
def test_windows_process_liveness_treats_malformed_or_ambiguous_output_as_unknown(
    stdout: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        controller_module.subprocess,
        "run",
        lambda *_args, **_kwargs: _tasklist_result(stdout=stdout),
    )

    assert controller_module._windows_process_liveness(4321) == ProcessLiveness.UNKNOWN


def test_posix_process_liveness_is_fail_closed_for_permission_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(_pid: int, _signal: int) -> None:
        raise PermissionError(errno.EPERM, "not permitted")

    monkeypatch.setattr(controller_module.os, "kill", denied)

    assert controller_module._posix_process_liveness(4321) == ProcessLiveness.ALIVE


def test_posix_process_liveness_identifies_esrch_as_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_pid: int, _signal: int) -> None:
        raise OSError(errno.ESRCH, "no such process")

    monkeypatch.setattr(controller_module.os, "kill", missing)

    assert controller_module._posix_process_liveness(4321) == ProcessLiveness.DEAD


def test_is_process_alive_remains_a_boolean_compatibility_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.ALIVE,
    )
    assert controller_module.is_process_alive(4321) is True

    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.UNKNOWN,
    )
    assert controller_module.is_process_alive(4321) is False


def _quota(tmp_path: Path, *, reclaim_bound_leases: bool = True) -> cell_module.AccountQuota:
    return cell_module.AccountQuota(
        account_slot="C",
        quota_root=tmp_path / "quota",
        limit=1,
        run_id="candidate-run",
        reclaim_bound_leases=reclaim_bound_leases,
    )


def test_account_quota_preserves_lock_busy_as_a_typed_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota = _quota(tmp_path)
    monkeypatch.setattr(cell_module, "_try_acquire_byte_lock", lambda _path: None)

    outcome = quota.try_claim_outcome(lineage_id="candidate", workspace=tmp_path / "workspace")

    assert outcome == {"outcome": "LOCK_BUSY"}
    assert quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace") is None


def _write_bound_record(
    quota: cell_module.AccountQuota,
    *,
    lease_id: str = "prior-bound",
    child_pid: int = 111,
    controller_pid: int = 222,
    operator_throttle: bool = False,
) -> Path:
    path = quota.records[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                "lease_id": lease_id,
                "counted": True,
                "status": "BOUND",
                "account_slot": "C",
                "slot": 1,
                "limit": 1,
                "run_id": "prior-run",
                "lineage_id": "prior-lineage",
                "workspace": "prior-workspace",
                "controller_pid": controller_pid,
                "child_pid": child_pid,
                "operator_throttle": operator_throttle,
                "reserved_at": "2026-08-15T00:00:00Z",
                "bound_at": "2026-08-15T00:00:01Z",
                "released_at": None,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "states",
    [
        {111: ProcessLiveness.UNKNOWN, 222: ProcessLiveness.DEAD},
        {111: ProcessLiveness.DEAD, 222: ProcessLiveness.UNKNOWN},
        {111: ProcessLiveness.ALIVE, 222: ProcessLiveness.DEAD},
        {111: ProcessLiveness.DEAD, 222: ProcessLiveness.ALIVE},
    ],
)
def test_account_quota_skips_bound_lease_unless_both_processes_are_dead(
    states: dict[int, ProcessLiveness],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quota = _quota(tmp_path)
    path = _write_bound_record(quota)
    before = path.read_bytes()
    monkeypatch.setattr(cell_module, "process_liveness", states.__getitem__)

    claimed = quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace")

    assert claimed is None
    assert path.read_bytes() == before
    assert not (path.parent / "history").exists()


def test_account_quota_reclaims_bound_lease_only_when_both_processes_are_dead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota = _quota(tmp_path)
    path = _write_bound_record(quota)
    monkeypatch.setattr(
        cell_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.DEAD,
    )

    claimed = quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace")

    assert claimed is not None
    assert claimed["lease_id"] != "prior-bound"
    assert (path.parent / "history" / "prior-bound.json").is_file()


def test_account_quota_can_disable_automatic_bound_lease_reclamation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota = _quota(tmp_path, reclaim_bound_leases=False)
    path = _write_bound_record(quota)
    before = path.read_bytes()

    def unexpected_probe(_pid: int) -> ProcessLiveness:
        raise AssertionError("disabled reclamation must not probe the bound processes")

    monkeypatch.setattr(cell_module, "process_liveness", unexpected_probe)

    assert quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace") is None
    assert path.read_bytes() == before


def test_account_quota_never_reclaims_operator_throttle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota = _quota(tmp_path)
    path = _write_bound_record(quota, operator_throttle=True)
    before = path.read_bytes()

    def unexpected_probe(_pid: int) -> ProcessLiveness:
        raise AssertionError("operator throttle must not be probed for reclamation")

    monkeypatch.setattr(cell_module, "process_liveness", unexpected_probe)

    assert quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace") is None
    assert path.read_bytes() == before


def test_account_quota_can_claim_a_released_operator_throttle_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota = _quota(tmp_path)
    path = _write_bound_record(quota, operator_throttle=True)
    released = json.loads(path.read_text(encoding="utf-8"))
    released.update(
        {
            "status": "RELEASED",
            "released_at": "2026-08-15T00:00:02Z",
        }
    )
    path.write_text(json.dumps(released, sort_keys=True), encoding="utf-8")

    def unexpected_probe(_pid: int) -> ProcessLiveness:
        raise AssertionError("a released record is available without a liveness probe")

    monkeypatch.setattr(cell_module, "process_liveness", unexpected_probe)

    claimed = quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace")
    assert claimed is not None
    assert claimed["lease_id"] != "prior-bound"


def test_account_quota_release_preserves_bound_lease_when_child_liveness_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota = _quota(tmp_path)
    lease = quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace")
    assert lease is not None
    bound = quota.bind(lease, child_pid=111)
    monkeypatch.setattr(
        cell_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.UNKNOWN,
    )

    result = quota.release(bound)
    record = json.loads(Path(str(bound["path"])).read_text(encoding="utf-8"))

    assert result == "CHILD_LIVENESS_UNKNOWN"
    assert record["status"] == "BOUND"
    assert record["released_at"] is None


def test_account_quota_release_reports_a_live_child_without_releasing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota = _quota(tmp_path)
    lease = quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace")
    assert lease is not None
    bound = quota.bind(lease, child_pid=111)
    monkeypatch.setattr(
        cell_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.ALIVE,
    )

    result = quota.release(bound)
    record = json.loads(Path(str(bound["path"])).read_text(encoding="utf-8"))

    assert result == "CHILD_STILL_ALIVE"
    assert record["status"] == "BOUND"
    assert record["released_at"] is None


def test_account_quota_release_rejects_unknown_status_without_mutating(
    tmp_path: Path,
) -> None:
    quota = _quota(tmp_path)
    lease = quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace")
    assert lease is not None
    path = Path(str(lease["path"]))
    corrupt = json.loads(path.read_text(encoding="utf-8"))
    corrupt["status"] = "CORRUPT"
    path.write_text(json.dumps(corrupt, sort_keys=True), encoding="utf-8")
    before = path.read_bytes()

    assert quota.release(lease) == "OWNERSHIP_DRIFT"
    assert path.read_bytes() == before


def test_account_quota_release_requires_full_immutable_owner_identity(
    tmp_path: Path,
) -> None:
    quota = _quota(tmp_path)
    lease = quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace")
    assert lease is not None
    path = Path(str(lease["path"]))
    before = path.read_bytes()
    forged = {**lease, "lineage_id": "foreign-lineage"}

    assert quota.release(forged) == "OWNERSHIP_DRIFT"
    assert path.read_bytes() == before


def test_account_quota_bind_transfers_release_window_owner_to_binding_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota = _quota(tmp_path)
    lease = quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace")
    assert lease is not None
    monkeypatch.setattr(cell_module.os, "getpid", lambda: 9876)

    bound = quota.bind(lease, child_pid=111)
    record = json.loads(Path(str(bound["path"])).read_text(encoding="utf-8"))

    assert bound["controller_pid"] == 9876
    assert record["controller_pid"] == 9876
    assert record["child_pid"] == 111


def _controller(
    tmp_path: Path, *, run_id: str, quota_root: Path
) -> tuple[PerpetualController, dict[str, str]]:
    run_dir = tmp_path / "run"
    root_workspace = tmp_path / "root-main"
    world_workspace = tmp_path / "world-01"
    root_workspace.mkdir(parents=True)
    world_workspace.mkdir()
    branch = {
        "lineage_id": "world-01",
        "role": "independent_world",
        "workspace": str(world_workspace),
    }
    config = {
        "schema": RUN_SCHEMA,
        "account_slot": "C",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "source_head": "a" * 40,
        "branch_lineages": [branch],
        "root_lineage": {
            "lineage_id": "root-main",
            "role": "late_fusion_root",
            "workspace": str(root_workspace),
        },
        "world_turn_concurrency_limit": 1,
        "world_turn_quota_root": str(quota_root),
        "continuation_delay_seconds": 0,
        "park_poll_seconds": 0,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return PerpetualController(config_path), branch


def test_controller_can_reserve_a_released_operator_throttle_slot(tmp_path: Path) -> None:
    controller, branch = _controller(
        tmp_path / "controller",
        run_id="controller",
        quota_root=tmp_path / "shared-quota",
    )
    prior = controller.try_reserve_world_turn_quota(branch)
    assert prior is not None
    path = Path(str(prior["path"]))
    released = json.loads(path.read_text(encoding="utf-8"))
    released.update(
        {
            "status": "RELEASED",
            "operator_throttle": True,
            "released_at": "2026-08-15T00:00:02Z",
        }
    )
    path.write_text(json.dumps(released, sort_keys=True), encoding="utf-8")
    controller._world_turn_leases.clear()

    claimed = controller.try_reserve_world_turn_quota(branch)

    assert claimed is not None
    assert claimed["lease_id"] != prior["lease_id"]


def test_controller_does_not_reclaim_bound_quota_on_unknown_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota_root = tmp_path / "shared-quota"
    first, first_branch = _controller(tmp_path / "first", run_id="first", quota_root=quota_root)
    second, second_branch = _controller(tmp_path / "second", run_id="second", quota_root=quota_root)
    lease = first.try_reserve_world_turn_quota(first_branch)
    assert lease is not None
    first.bind_world_turn_quota_child(first_branch, child_pid=111)
    first._world_turn_leases.clear()
    record_path = Path(str(lease["path"]))
    before = record_path.read_bytes()
    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.UNKNOWN,
    )

    assert second.try_reserve_world_turn_quota(second_branch) is None
    assert record_path.read_bytes() == before


def test_controller_does_not_release_bound_quota_on_unknown_child_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, branch = _controller(
        tmp_path / "controller",
        run_id="controller",
        quota_root=tmp_path / "shared-quota",
    )
    lease = controller.try_reserve_world_turn_quota(branch)
    assert lease is not None
    bound = controller.bind_world_turn_quota_child(branch, child_pid=111)
    assert bound is not None
    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.UNKNOWN,
    )

    assert controller.release_world_turn_quota(branch) is False
    record = json.loads(Path(str(bound["path"])).read_text(encoding="utf-8"))
    assert record["status"] == "BOUND"
    assert record["released_at"] is None


def test_orphan_recovery_preserves_pid_and_returns_typed_unknown_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _branch = _controller(
        tmp_path / "controller",
        run_id="controller",
        quota_root=tmp_path / "quota",
    )
    state = controller._lineage_states["world-01"]
    state["active_pid"] = 111
    state_path = controller.lineage_state_path("world-01")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    before = state_path.read_bytes()
    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.UNKNOWN,
    )

    with pytest.raises(
        controller_module.PerpetualRuntimeError,
        match="ORPHAN_CHILD_LIVENESS_UNKNOWN_BEFORE_RECOVERY",
    ) as raised:
        controller.reject_live_orphaned_children()

    assert '"liveness": "UNKNOWN"' in str(raised.value)
    assert controller._lineage_states["world-01"]["active_pid"] == 111
    assert state_path.read_bytes() == before


def _runtime_gate_fixture(tmp_path: Path) -> tuple[Path, Path]:
    runtime_root = tmp_path / "runtime"
    run_dir = runtime_root / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    pointer = {
        "schema": RUN_SCHEMA,
        "run_id": "run-1",
        "run_dir": str(run_dir),
        "controller_pid": 111,
        "account_slot": "C",
    }
    state = {
        "schema": "controller",
        "run_id": "run-1",
        "account_slot": "C",
        "pid": 111,
        "status": "STOPPED",
        "active_processes": {"world-01": 222},
    }
    config = {
        "schema": RUN_SCHEMA,
        "account_slot": "C",
        "run_id": "run-1",
        "run_dir": str(run_dir),
        "branch_lineages": [{"lineage_id": "world-01", "role": "independent_world"}],
        "root_lineage": {"lineage_id": "root-main", "role": "late_fusion_root"},
    }
    (runtime_root / "current.json").write_text(json.dumps(pointer), encoding="utf-8")
    (run_dir / "controller_state.json").write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
    return runtime_root, run_dir


def test_active_controller_admission_blocks_on_unknown_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root, run_dir = _runtime_gate_fixture(tmp_path)
    state_path = run_dir / "controller_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["pid"] = 333
    state_path.write_text(json.dumps(state), encoding="utf-8")
    pointer_before = (runtime_root / "current.json").read_bytes()
    state_before = state_path.read_bytes()
    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda pid: ProcessLiveness.UNKNOWN if pid == 111 else ProcessLiveness.DEAD,
    )

    with pytest.raises(
        controller_module.PerpetualRuntimeError,
        match="CONTROLLER_LIVENESS_UNKNOWN_START_BLOCKED",
    ) as raised:
        controller_module.ensure_no_active_controller(runtime_root)

    assert '"liveness": "UNKNOWN"' in str(raised.value)
    assert (runtime_root / "current.json").read_bytes() == pointer_before
    assert state_path.read_bytes() == state_before


def test_typed_runtime_liveness_includes_unknown_while_live_wrapper_stays_compatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, branch = _controller(
        tmp_path / "controller",
        run_id="controller",
        quota_root=tmp_path / "quota",
    )
    lineage_path = controller.lineage_state_path("world-01")
    lineage_path.parent.mkdir(parents=True, exist_ok=True)
    lineage_path.write_text(json.dumps({"active_pid": 104}), encoding="utf-8")
    lease = controller.try_reserve_world_turn_quota(branch)
    assert lease is not None
    controller.bind_world_turn_quota_child(branch, child_pid=105)
    pointer = {"controller_pid": 101}
    state = {"pid": 102, "active_processes": {"world-01": 103}}
    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.UNKNOWN,
    )

    evidence = controller_module.find_runtime_process_liveness(pointer, state, controller.config)

    assert evidence == {
        "pointer.controller": {"pid": 101, "liveness": "UNKNOWN"},
        "state.controller": {"pid": 102, "liveness": "UNKNOWN"},
        "state.child.world-01": {"pid": 103, "liveness": "UNKNOWN"},
        "lineage.child.world-01": {"pid": 104, "liveness": "UNKNOWN"},
        "quota.child.world-01": {"pid": 105, "liveness": "UNKNOWN"},
    }
    assert controller_module.find_live_runtime_processes(pointer, state, controller.config) == {}

    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda pid: ProcessLiveness.ALIVE if pid == 101 else ProcessLiveness.DEAD,
    )
    assert controller_module.find_live_runtime_processes(pointer, state, controller.config) == {
        "pointer.controller": 101
    }


def _unknown_process_evidence() -> dict[str, dict[str, int | str]]:
    return {
        "pointer.controller": {
            "pid": 111,
            "liveness": ProcessLiveness.UNKNOWN.value,
        }
    }


def test_reality_migration_admission_blocks_on_unknown_process_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root, run_dir = _runtime_gate_fixture(tmp_path)
    monkeypatch.setattr(
        controller_module,
        "find_runtime_process_liveness",
        lambda *_args: _unknown_process_evidence(),
    )

    with pytest.raises(
        controller_module.PerpetualRuntimeError,
        match="REALITY_MIGRATION_REFUSED_PROCESS_LIVENESS_UNKNOWN",
    ) as raised:
        controller_module.prepare_reality_migration(
            SimpleNamespace(
                runtime_root=runtime_root,
                expected_account_slot="C",
                live_reality_root=tmp_path / "live-reality",
                world_compute_root=tmp_path / "world-compute",
            )
        )

    assert '"liveness": "UNKNOWN"' in str(raised.value)
    assert not (run_dir / "reality-migration-preparation").exists()


@pytest.mark.skipif(controller_module.os.name != "nt", reason="recover_runtime is Windows-only")
def test_recovery_admission_blocks_on_unknown_process_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root, run_dir = _runtime_gate_fixture(tmp_path)
    monkeypatch.setattr(
        controller_module,
        "find_runtime_process_liveness",
        lambda *_args: _unknown_process_evidence(),
    )

    with pytest.raises(
        controller_module.PerpetualRuntimeError,
        match="RECOVERY_REFUSED_PROCESS_LIVENESS_UNKNOWN",
    ) as raised:
        controller_module.recover_runtime(
            SimpleNamespace(
                runtime_root=runtime_root,
                expected_account_slot="C",
                reason="test unknown liveness",
            )
        )

    assert '"liveness": "UNKNOWN"' in str(raised.value)
    assert not (run_dir / "recovery").exists()


def test_stop_runtime_never_reports_success_on_unknown_process_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root, run_dir = _runtime_gate_fixture(tmp_path)
    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.UNKNOWN,
    )

    with pytest.raises(
        controller_module.PerpetualRuntimeError,
        match="STOP_PROCESS_LIVENESS_UNKNOWN",
    ) as raised:
        controller_module.stop_runtime(
            SimpleNamespace(runtime_root=runtime_root, reason="test", wait_seconds=0)
        )

    assert '"liveness": "UNKNOWN"' in str(raised.value)
    assert (run_dir / "STOP.json").is_file()


def test_status_runtime_exposes_unknown_liveness_without_breaking_boolean_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root, _run_dir = _runtime_gate_fixture(tmp_path)
    monkeypatch.setattr(
        controller_module,
        "process_liveness",
        lambda _pid: ProcessLiveness.UNKNOWN,
    )

    status = controller_module.status_runtime(SimpleNamespace(runtime_root=runtime_root))

    assert status["controller_alive"] is False
    assert status["controller_liveness"] == "UNKNOWN"
