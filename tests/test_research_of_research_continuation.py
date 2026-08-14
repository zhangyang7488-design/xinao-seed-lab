from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
from scripts import research_of_research_continuation as continuation_cli
from services.research_of_research import cell, continuation
from services.xinao_perpetual_world_compute.controller import (
    _release_byte_lock,
    _try_acquire_byte_lock,
)


def _binding(tmp_path: Path) -> dict[str, str]:
    path = tmp_path / "current-contract-source.txt"
    path.write_text("current scoped Stage 0 contract\n", encoding="utf-8")
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _run_dir(root: Path, cell_id: str, run_id: str) -> Path:
    path = root / "cells" / cell_id / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_state(root: Path, cell_id: str, run_id: str, status: str) -> Path:
    path = _run_dir(root, cell_id, run_id) / "run_state.json"
    path.write_text(
        json.dumps(
            {
                "schema": continuation.CURRENT_RUN_SCHEMA,
                "run_id": run_id,
                "status": status,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_receipt(
    root: Path,
    cell_id: str,
    run_id: str,
    *,
    status: str = "SEALED",
    schema: str = continuation.CURRENT_RUN_SCHEMA,
) -> Path:
    receipt: dict[str, object] = {
        "schema": schema,
        "cell_id": cell_id,
        "run_id": run_id,
        "status": status,
        "authority": False,
        "completion_claim_allowed": False,
    }
    if schema == continuation.CURRENT_RUN_SCHEMA:
        receipt["receipt_sha256"] = hashlib.sha256(cell._canonical_bytes(receipt)).hexdigest()
    path = _run_dir(root, cell_id, run_id) / "run_receipt.json"
    path.write_bytes(cell._canonical_bytes(receipt))
    return path


def _initialize(root: Path, tmp_path: Path) -> dict[str, object]:
    return continuation.initialize_contract(
        root,
        contract_name="stage0-test",
        source_binding=_binding(tmp_path),
    )


def test_activation_inventory_is_exact_and_does_not_create_historical_observations(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    historical = _write_receipt(runtime, "cell-a", "run-old")
    _write_state(runtime, "cell-a", "run-old", "SEALED")
    _write_state(runtime, "cell-b", "run-preparing", "PREPARING")

    bound = _initialize(runtime, tmp_path)

    assert bound["outcome"] == "BOUND"
    assert bound["baseline_count"] == 1
    assert bound["observation_count"] == 0
    assert len(list((runtime / "continuation" / "seen").glob("*.json"))) == 1
    assert not (runtime / "continuation" / "observations").exists()
    baseline = json.loads(
        next((runtime / "continuation" / "contracts" / "revisions").glob("*.json")).read_text(
            encoding="utf-8"
        )
    )["baseline"]
    assert baseline[0]["source"]["relative_path"] == historical.relative_to(runtime).as_posix()
    assert "mtime" not in json.dumps(baseline)


def test_initialize_rejects_a_drifted_contract_binding(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    binding = _binding(tmp_path)
    Path(binding["path"]).write_text("changed after hashing\n", encoding="utf-8")

    with pytest.raises(continuation.ContinuationError) as error:
        continuation.initialize_contract(
            runtime,
            contract_name="stage0-test",
            source_binding=binding,
        )

    assert error.value.reason_code == "CONTRACT_BINDING_HASH_MISMATCH"
    assert not (runtime / "continuation" / "contracts" / "current.json").exists()


def test_receipt_appearing_after_activation_becomes_one_non_dispatchable_observation(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    _write_receipt(runtime, "cell-a", "run-old")
    _write_state(runtime, "cell-b", "run-later", "PREPARING")
    _initialize(runtime, tmp_path)

    receipt = _write_receipt(
        runtime,
        "cell-b",
        "run-later",
        status="INVALID_EXPERIMENT",
    )
    first = continuation.reconcile(runtime)
    repeats = [continuation.reconcile(runtime) for _ in range(20)]

    assert first["outcome"] == "RECONCILED"
    assert len(first["new_observation_ids"]) == 1
    assert all(row["new_observation_ids"] == [] for row in repeats)
    assert first["observation_count"] == 1
    observation_id = first["new_observation_ids"][0]
    observation_path = (
        runtime / "continuation" / "observations" / observation_id / "observation.json"
    )
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    assert observation["schema"] == continuation.CONTINUATION_OBSERVATION_SCHEMA
    assert observation["source"]["relative_path"] == receipt.relative_to(runtime).as_posix()
    assert observation["source"]["reported_status"] == "INVALID_EXPERIMENT"
    seen = json.loads(
        (runtime / "continuation" / "seen" / f"{observation_id}.json").read_text(encoding="utf-8")
    )
    observation_status = json.loads(
        (observation_path.parent / "status.json").read_text(encoding="utf-8")
    )
    for record in (observation, seen, observation_status):
        for key in continuation._NO_AUTHORITY:
            assert record[key] is False
    assert not (runtime / "continuation" / "requests").exists()


def test_receiptless_run_is_not_a_source_but_later_receipt_is(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _write_state(runtime, "cell-a", "run-gap", "RUNNING")
    _initialize(runtime, tmp_path)

    before = continuation.reconcile(runtime)
    _write_receipt(runtime, "cell-a", "run-gap")
    after = continuation.reconcile(runtime)

    assert before["observation_count"] == 0
    assert before["new_observation_ids"] == []
    assert len(after["new_observation_ids"]) == 1


def test_run_state_never_gates_a_valid_receipt(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _initialize(runtime, tmp_path)
    _write_state(runtime, "cell-a", "run-crash-seam", "PREPARING")
    _write_receipt(runtime, "cell-a", "run-crash-seam")

    result = continuation.reconcile(runtime)

    assert len(result["new_observation_ids"]) == 1


def test_legacy_receipt_is_inventoried_by_exact_bytes_without_fabricating_a_seal(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    _write_receipt(
        runtime,
        "legacy-cell",
        "legacy-run",
        schema=continuation.LEGACY_RUN_SCHEMA,
    )

    bound = _initialize(runtime, tmp_path)
    revision = json.loads(
        next((runtime / "continuation" / "contracts" / "revisions").glob("*.json")).read_text(
            encoding="utf-8"
        )
    )

    assert bound["baseline_count"] == 1
    assert revision["baseline"][0]["source"]["seal_mode"] == "LEGACY_EXACT_BYTES"
    assert revision["baseline"][0]["source"]["receipt_digest"].startswith("bytes_sha256:")


def test_mutated_receipt_identity_is_an_incident_not_a_second_observation(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    _write_receipt(runtime, "cell-a", "run-old", status="SEALED")
    _initialize(runtime, tmp_path)
    _write_receipt(runtime, "cell-a", "run-old", status="INVALID_EXPERIMENT")

    result = continuation.reconcile(runtime)

    assert result["new_observation_ids"] == []
    assert result["observation_count"] == 0
    incidents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (runtime / "continuation" / "incidents").glob("*.json")
    ]
    assert {row["reason_code"] for row in incidents} == {"SOURCE_LOGICAL_IDENTITY_DRIFT"}


def test_same_v2_seal_with_different_file_bytes_is_incident_and_scan_continues(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    _initialize(runtime, tmp_path)
    path = _write_receipt(runtime, "cell-a", "run-new")
    first = continuation.reconcile(runtime)
    value = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")

    second = continuation.reconcile(runtime)
    third = continuation.reconcile(runtime)

    assert len(first["new_observation_ids"]) == 1
    assert second["new_observation_ids"] == []
    assert third["new_observation_ids"] == []
    assert second["observation_count"] == 1
    incidents = [
        json.loads(item.read_text(encoding="utf-8"))
        for item in (runtime / "continuation" / "incidents").glob("*.json")
    ]
    assert {row["reason_code"] for row in incidents} == {"SOURCE_FILE_BYTES_DRIFT"}


def test_bad_current_receipt_seal_is_incident_only(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _initialize(runtime, tmp_path)
    path = _write_receipt(runtime, "cell-a", "run-bad")
    value = json.loads(path.read_text(encoding="utf-8"))
    value["receipt_sha256"] = "0" * 64
    path.write_bytes(cell._canonical_bytes(value))

    result = continuation.reconcile(runtime)

    assert result["observation_count"] == 0
    assert result["incident_count"] == 1
    incident = json.loads(
        next((runtime / "continuation" / "incidents").glob("*.json")).read_text(encoding="utf-8")
    )
    for key in continuation._NO_AUTHORITY:
        assert incident[key] is False


def test_stop_is_expected_revision_bound_and_blocks_new_observations(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    bound = _initialize(runtime, tmp_path)
    revision_id = str(bound["revision_id"])
    with pytest.raises(continuation.ContinuationError) as error:
        continuation.stop_contract(runtime, expected_revision_id="0" * 64)
    assert error.value.reason_code == "CONTRACT_EXPECTED_REVISION_MISMATCH"

    stopped = continuation.stop_contract(runtime, expected_revision_id=revision_id)
    _write_receipt(runtime, "cell-a", "run-after-stop")
    result = continuation.reconcile(runtime)

    assert stopped["outcome"] == "STOPPED"
    assert result["outcome"] == "STOPPED"
    assert result["observation_count"] == 0


def test_nonblocking_adapter_lock_defers_overlapping_scan(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _initialize(runtime, tmp_path)
    lock = _try_acquire_byte_lock(runtime / "continuation" / ".adapter.lock")
    assert lock is not None
    try:
        assert continuation.reconcile(runtime)["outcome"] == "LOCK_BUSY"
    finally:
        _release_byte_lock(lock)


def test_cli_reports_lock_busy_as_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        continuation_cli,
        "reconcile",
        lambda _root: {
            "outcome": "LOCK_BUSY",
            "authority": False,
            "completion_claim_allowed": False,
        },
    )

    exit_code = continuation_cli.main(["--runtime-root", str(tmp_path / "runtime"), "reconcile"])

    assert exit_code == 3
    assert json.loads(capsys.readouterr().out)["outcome"] == "LOCK_BUSY"


def test_restart_repairs_observation_seen_and_status_gap_without_duplication(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    _initialize(runtime, tmp_path)
    _write_receipt(runtime, "cell-a", "run-new")
    first = continuation.reconcile(runtime)
    observation_id = first["new_observation_ids"][0]
    seen_path = runtime / "continuation" / "seen" / f"{observation_id}.json"
    status_path = runtime / "continuation" / "observations" / observation_id / "status.json"
    seen_path.unlink()
    status_path.unlink()

    repaired = continuation.reconcile(runtime)

    assert repaired["new_observation_ids"] == []
    assert repaired["observation_count"] == 1
    assert seen_path.is_file()
    assert status_path.is_file()


def test_initialize_resumes_exact_unpublished_revision_without_expanding_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    binding = _binding(tmp_path)
    _write_receipt(runtime, "cell-a", "run-old")
    real_atomic_write_json = continuation.atomic_write_json

    def fail_current_pointer(path: Path, value: object) -> str:
        if path.name == "current.json" and path.parent.name == "contracts":
            raise OSError("fixture crash before current pointer")
        return real_atomic_write_json(path, value)

    monkeypatch.setattr(continuation, "atomic_write_json", fail_current_pointer)
    with pytest.raises(OSError):
        continuation.initialize_contract(
            runtime,
            contract_name="stage0-test",
            source_binding=binding,
        )
    revision_path = next((runtime / "continuation" / "contracts" / "revisions").glob("*.json"))
    first_revision_id = revision_path.stem
    _write_receipt(runtime, "cell-b", "run-after-revision")
    monkeypatch.setattr(continuation, "atomic_write_json", real_atomic_write_json)

    resumed = continuation.initialize_contract(
        runtime,
        contract_name="stage0-test",
        source_binding=binding,
    )
    detected = continuation.reconcile(runtime)

    assert resumed["revision_id"] == first_revision_id
    assert resumed["baseline_count"] == 1
    assert len(detected["new_observation_ids"]) == 1


def test_write_once_conflict_is_translated_to_continuation_error(tmp_path: Path) -> None:
    path = tmp_path / "immutable" / "row.json"
    assert continuation._write_once_json(path, {"value": 1}, conflict_code="FIXTURE") == "CREATED"

    with pytest.raises(continuation.ContinuationError) as error:
        continuation._write_once_json(path, {"value": 2}, conflict_code="FIXTURE")

    assert error.value.reason_code == "FIXTURE"


def test_authority_flag_drift_fails_closed(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _initialize(runtime, tmp_path)
    current_path = runtime / "continuation" / "contracts" / "current.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    current["dispatch_allowed"] = True
    current_path.write_text(json.dumps(current), encoding="utf-8")

    with pytest.raises(continuation.ContinuationError) as error:
        continuation.reconcile(runtime)

    assert error.value.reason_code == "CONTRACT_POINTER_AUTHORITY_INVALID"


def test_best_effort_bell_requires_live_contract_and_exact_receipt_path(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    receipt = _write_receipt(runtime, "cell-a", "run-old")
    system_root = tmp_path / "Windows"
    schtasks = system_root / "System32" / "schtasks.exe"
    schtasks.parent.mkdir(parents=True)
    schtasks.write_bytes(b"fixture")
    calls: list[tuple[object, ...]] = []

    def runner(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return object()

    assert not continuation.request_continuation_reconcile(
        receipt_path=receipt,
        runtime_root=runtime,
        runner=runner,
        system_root=str(system_root),
    )
    _initialize(runtime, tmp_path)
    assert continuation.request_continuation_reconcile(
        receipt_path=receipt,
        runtime_root=runtime,
        runner=runner,
        system_root=str(system_root),
    )
    assert len(calls) == 1
    argv = calls[0][0][0]
    assert argv == [
        str(schtasks),
        "/Run",
        "/TN",
        continuation.CONTINUATION_TASK_NAME,
    ]


def test_cell_rings_only_after_receipt_commit_and_before_terminal_state() -> None:
    source = inspect.getsource(cell.run_cell)
    receipt_commit = source.index("atomic_write_json(receipt_path, receipt)")
    bell = source.index("request_continuation_reconcile(")
    terminal_state = source.index('"status": status', bell)
    assert receipt_commit < bell < terminal_state
    assert "runtime_root=cell_dir.parent.parent" in source[bell:terminal_state]


def test_stage0_module_has_no_main_capacity_or_dispatch_effect_surface() -> None:
    source = inspect.getsource(continuation)
    forbidden = (
        "create_world_isolated_launcher(",
        "AccountQuota(",
        "root-main",
        "WAITING_FOR_COMPUTE",
        "subprocess.run(",
    )
    assert all(token not in source for token in forbidden)
    assert 'dispatch_allowed": False' in source


def test_sibling_task_installer_is_stage0_scoped_and_recoverable() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "Install-SResearchOfResearchContinuation.ps1"
    )
    source = path.read_text(encoding="utf-8")
    for required in (
        "XINAO-S-RoR-Continuation-Detect-v0",
        "-MultipleInstances IgnoreNew",
        "-StartWhenAvailable",
        "-RepetitionInterval (New-TimeSpan -Minutes 15)",
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5)",
        "TASK_EXECUTION_TIME_LIMIT_INVALID",
        "TASK_PRINCIPAL_INVALID",
        "TASK_LOGON_TYPE_INVALID",
        "TASK_RUN_LEVEL_INVALID",
        "Register-ScheduledTask",
        "Export-ScheduledTask",
        "Unregister-ScheduledTask",
        "Start-ScheduledTask",
        "scripts/research_of_research_continuation.py",
        'reconcile"',
        "bundle_manifest.json",
        "BUNDLE_FILE_SET_MISMATCH",
        "BUNDLE_RUNTIME_ROOT_MISMATCH",
        "Assert-RegularTree -Root $BundleRoot",
        "cpython-3.13.14-official",
    ):
        assert required in source
    assert "XINAO-S-Context-Rollout-Consumer-v1" not in source
    assert "main_reentry" not in source.casefold()
    assert "WAITING_FOR_COMPUTE" not in source
