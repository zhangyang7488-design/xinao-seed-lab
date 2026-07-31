"""Wave116: stable recovery launcher generation bridge.

Proves the exact pre-Wave92 historical launcher may be CAS-upgraded to the
current payload when the recovery pointer is absent, and that foreign /
pointer-present / concurrent-change cases stay fail-closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from test_xinao_skill import (
    _canary_value,
    _module,
    _prepare_v1_migration_world,
    _prepare_v2_forward_upgrade_world,
)

# Live sticky pre-Wave92 recover-current.py identity (Wave114 diagnosis).
HISTORICAL_LAUNCHER_SHA256 = "eeea9d46b80f0ba9a93b66a017e3450d01058c2c1924864703b1bad0e5b0ee19"
CURRENT_LAUNCHER_SHA256 = "5a8514bf224c618a99d30721f7637a29a7af9c5df43644f6e4c27539acc4b311"


def _prepared_migrate_journal(
    module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], dict[str, object]]:
    """Stop after PREPARED materialization; recovery cone + receipt exist."""

    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    original_continue = module._continue_migrate_journal

    def stop_after_prepare(journal, journal_path):
        assert journal["state"] == "PREPARED"
        raise module.XinaoError("INJECTED_CRASH", "prepared boundary")

    monkeypatch.setattr(module, "_continue_migrate_journal", stop_after_prepare)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "INJECTED_CRASH"
    monkeypatch.setattr(module, "_continue_migrate_journal", original_continue)
    pending = module._pending_journals()
    assert len(pending) == 1
    journal, _path = pending[0]
    assert journal["state"] == "PREPARED"
    assert journal["operation"] == "MIGRATE"
    return world, journal


def test_historical_launcher_payload_sha_is_frozen() -> None:
    module = _module()
    historical = module._stable_recovery_launcher_historical_payload()
    current = module._stable_recovery_launcher_payload()
    assert module._sha256_bytes(historical) == HISTORICAL_LAUNCHER_SHA256
    assert module._sha256_bytes(current) == CURRENT_LAUNCHER_SHA256
    assert historical != current
    assert b"-B" not in historical
    assert b"PYTHONDONTWRITEBYTECODE" not in historical
    assert b"-B" in current
    assert b"PYTHONDONTWRITEBYTECODE" in current


def test_historical_launcher_upgrades_when_pointer_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _world, journal = _prepared_migrate_journal(module, tmp_path, monkeypatch)
    launcher_path, pointer_path = module._stable_recovery_paths()
    historical = module._stable_recovery_launcher_historical_payload()
    current = module._stable_recovery_launcher_payload()
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_bytes(historical)
    assert not pointer_path.exists()

    module._publish_stable_recovery_entry(journal)

    assert launcher_path.read_bytes() == current
    assert module._sha256_bytes(launcher_path.read_bytes()) == CURRENT_LAUNCHER_SHA256
    expected_pointer = module._stable_recovery_pointer_payload(journal)
    assert pointer_path.read_bytes() == expected_pointer


def test_current_launcher_publish_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _world, journal = _prepared_migrate_journal(module, tmp_path, monkeypatch)
    launcher_path, pointer_path = module._stable_recovery_paths()
    current = module._stable_recovery_launcher_payload()
    expected_pointer = module._stable_recovery_pointer_payload(journal)

    module._publish_stable_recovery_entry(journal)
    assert launcher_path.read_bytes() == current
    assert pointer_path.read_bytes() == expected_pointer
    first_launcher = launcher_path.read_bytes()
    first_pointer = pointer_path.read_bytes()

    module._publish_stable_recovery_entry(journal)
    assert launcher_path.read_bytes() == first_launcher
    assert pointer_path.read_bytes() == first_pointer


def test_absent_launcher_creates_current_and_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _world, journal = _prepared_migrate_journal(module, tmp_path, monkeypatch)
    launcher_path, pointer_path = module._stable_recovery_paths()
    if launcher_path.exists():
        launcher_path.unlink()
    if pointer_path.exists():
        pointer_path.unlink()

    module._publish_stable_recovery_entry(journal)

    assert launcher_path.read_bytes() == module._stable_recovery_launcher_payload()
    assert pointer_path.read_bytes() == module._stable_recovery_pointer_payload(journal)


def test_foreign_and_trailing_launcher_bytes_are_preserved_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _world, journal = _prepared_migrate_journal(module, tmp_path, monkeypatch)
    launcher_path, pointer_path = module._stable_recovery_paths()
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    historical = module._stable_recovery_launcher_historical_payload()
    foreign_cases = (
        b"not-a-launcher\n",
        historical + b"\n",
        historical.replace(b"check=False", b"check=True", 1),
        module._stable_recovery_launcher_payload() + b"\nforeign",
    )
    for foreign in foreign_cases:
        if pointer_path.exists():
            pointer_path.unlink()
        launcher_path.write_bytes(foreign)
        with pytest.raises(module.XinaoError) as failure:
            module._publish_stable_recovery_entry(journal)
        assert failure.value.reason_code == "STABLE_RECOVERY_ENTRY_INVALID"
        assert launcher_path.read_bytes() == foreign
        assert not pointer_path.exists()


def test_historical_launcher_with_any_pointer_is_preserved_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _world, journal = _prepared_migrate_journal(module, tmp_path, monkeypatch)
    launcher_path, pointer_path = module._stable_recovery_paths()
    historical = module._stable_recovery_launcher_historical_payload()
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_bytes(historical)
    pointer_cases = (
        b'{"foreign":true}\n',
        module._stable_recovery_pointer_payload(journal),
        module._stable_recovery_pointer_payload(journal) + b"\n",
    )
    for pointer_bytes in pointer_cases:
        launcher_path.write_bytes(historical)
        pointer_path.write_bytes(pointer_bytes)
        with pytest.raises(module.XinaoError) as failure:
            module._publish_stable_recovery_entry(journal)
        assert failure.value.reason_code == "STABLE_RECOVERY_ENTRY_INVALID"
        assert launcher_path.read_bytes() == historical
        assert pointer_path.read_bytes() == pointer_bytes


def test_concurrent_launcher_change_at_pre_replace_reread_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _world, journal = _prepared_migrate_journal(module, tmp_path, monkeypatch)
    launcher_path, pointer_path = module._stable_recovery_paths()
    historical = module._stable_recovery_launcher_historical_payload()
    concurrent = historical + b"\nconcurrent"
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_bytes(historical)
    assert not pointer_path.exists()

    def inject_before_reread(phase: str) -> None:
        if phase == "before-replace-reread":
            launcher_path.write_bytes(concurrent)

    monkeypatch.setattr(
        module, "_stable_recovery_generation_bridge_fault_point", inject_before_reread
    )
    with pytest.raises(module.XinaoError) as failure:
        module._publish_stable_recovery_entry(journal)
    assert failure.value.reason_code == "STABLE_RECOVERY_ENTRY_INVALID"
    assert launcher_path.read_bytes() == concurrent
    assert not pointer_path.exists()


def test_concurrent_pointer_appearance_before_replace_preserves_historical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointer appearing after first check must not mutate historical launcher."""

    module = _module()
    _world, journal = _prepared_migrate_journal(module, tmp_path, monkeypatch)
    launcher_path, pointer_path = module._stable_recovery_paths()
    historical = module._stable_recovery_launcher_historical_payload()
    concurrent_pointer = b'{"schema_version":"foreign","txn_id":"x"}\n'
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_bytes(historical)
    if pointer_path.exists():
        pointer_path.unlink()

    def inject_pointer_before_commitment(phase: str) -> None:
        if phase == "before-replace-reread":
            pointer_path.write_bytes(concurrent_pointer)

    monkeypatch.setattr(
        module,
        "_stable_recovery_generation_bridge_fault_point",
        inject_pointer_before_commitment,
    )
    with pytest.raises(module.XinaoError) as failure:
        module._publish_stable_recovery_entry(journal)
    assert failure.value.reason_code == "STABLE_RECOVERY_ENTRY_INVALID"
    assert launcher_path.read_bytes() == historical
    assert pointer_path.read_bytes() == concurrent_pointer


def test_crash_after_launcher_replace_before_pointer_resumes_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _world, journal = _prepared_migrate_journal(module, tmp_path, monkeypatch)
    launcher_path, pointer_path = module._stable_recovery_paths()
    historical = module._stable_recovery_launcher_historical_payload()
    current = module._stable_recovery_launcher_payload()
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_bytes(historical)

    def stop_after_replace(phase: str) -> None:
        if phase == "after-launcher-replace":
            raise module.XinaoError("INJECTED_STOP", "after launcher upgrade")

    monkeypatch.setattr(
        module, "_stable_recovery_generation_bridge_fault_point", stop_after_replace
    )
    with pytest.raises(module.XinaoError) as stopped:
        module._publish_stable_recovery_entry(journal)
    assert stopped.value.reason_code == "INJECTED_STOP"
    assert launcher_path.read_bytes() == current
    assert not pointer_path.exists()

    monkeypatch.setattr(
        module,
        "_stable_recovery_generation_bridge_fault_point",
        lambda _phase: None,
    )
    module._publish_stable_recovery_entry(journal)
    assert launcher_path.read_bytes() == current
    assert pointer_path.read_bytes() == module._stable_recovery_pointer_payload(journal)


def test_prepared_forward_upgrade_recovers_through_historical_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same PREPARED FORWARD_UPGRADE journal continues; no new transaction."""

    module = _module()
    world = _prepare_v2_forward_upgrade_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )
    original_single = module._bootstrap_forward_upgrade_singleflight
    original_write = module._write_json_atomic

    def single_with_prepared_stop() -> dict[str, object]:
        def write_hook(path: Path, value: object, create_new: bool = False) -> None:
            original_write(path, value, create_new=create_new)
            if (
                isinstance(value, dict)
                and value.get("operation") == "FORWARD_UPGRADE"
                and value.get("state") == "PREPARED"
                and path.name == "activation.v1.json"
            ):
                raise module.XinaoError("INJECTED_CRASH", "after prepared journal")

        monkeypatch.setattr(module, "_write_json_atomic", write_hook)
        try:
            return original_single()
        finally:
            monkeypatch.setattr(module, "_write_json_atomic", original_write)

    with pytest.raises(module.XinaoError) as injected:
        single_with_prepared_stop()
    assert injected.value.reason_code == "INJECTED_CRASH"
    pending = module._pending_journals()
    assert len(pending) == 1
    journal, journal_path = pending[0]
    assert journal["operation"] == "FORWARD_UPGRADE"
    assert journal["state"] == "PREPARED"
    txn_id = journal["txn_id"]
    transaction_ids_before = sorted(
        path.name for path in module._state_paths()["transaction_root"].iterdir() if path.is_dir()
    )

    # Sticky historical launcher + absent recovery pointer (live Wave114 shape).
    launcher_path, pointer_path = module._stable_recovery_paths()
    historical = module._stable_recovery_launcher_historical_payload()
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_bytes(historical)
    if pointer_path.exists():
        pointer_path.unlink()

    recovered = module.recover_release(str(txn_id))
    assert recovered["status"] in {"UPGRADED", "VERIFIED"}
    assert recovered["txn_id"] == txn_id
    assert (
        sorted(
            path.name
            for path in module._state_paths()["transaction_root"].iterdir()
            if path.is_dir()
        )
        == transaction_ids_before
    )
    assert journal_path.is_file()
    terminal = module._load_json(journal_path)
    assert terminal["txn_id"] == txn_id
    assert terminal["state"] in module.TERMINAL_ACTIVATION_STATES
    pointer = module._load_json(module._state_paths()["pointer"])
    assert pointer["active"]["release_id"] == world["target"]["release_id"]
    assert launcher_path.read_bytes() == module._stable_recovery_launcher_payload()
    # Terminal hygiene retires the exact recovery pointer after success.
    assert not pointer_path.exists()
