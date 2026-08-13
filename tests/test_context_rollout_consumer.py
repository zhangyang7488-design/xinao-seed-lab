from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from scripts import context_rollout_consumer as consumer
from services.agent_runtime import context_fabric

SESSION_A = "019ff84f-eb50-79e2-b2f8-9f808700ba56"
SESSION_B = "019ff848-3a2e-7493-baf1-c778de8399e1"
SESSION_C = "019ff995-2a5c-7391-9baa-e362ba5f5e4d"
TURN_ID = "turn-context-rollout-consumer"
BASE_NOW = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


def _line(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


def _rollout(
    home: Path,
    *,
    session_id: str,
    timestamp: datetime,
    marker: str,
    source: str = "cli",
    thread_source: str = "user",
    subagent: bool = False,
    invalid_complete_line: bool = False,
) -> Path:
    local_day = timestamp.astimezone().date()
    directory = (
        home
        / "sessions"
        / f"{local_day.year:04d}"
        / f"{local_day.month:02d}"
        / f"{local_day.day:02d}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    path = directory / f"rollout-{stamp}-{session_id}.jsonl"
    timestamp_text = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    payload: dict[str, object] = {
        "id": session_id,
        "session_id": SESSION_A if subagent else session_id,
        "thread_source": thread_source,
        "source": source,
        "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
        "timestamp": timestamp_text,
    }
    if subagent:
        payload.update(
            {
                "parent_thread_id": SESSION_A,
                "agent_path": "/root/test_worker",
                "agent_role": "worker",
            }
        )
    records = [
        {
            "timestamp": timestamp_text,
            "ordinal": 0,
            "type": "session_meta",
            "payload": payload,
        },
        {
            "timestamp": (timestamp + timedelta(seconds=1))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "ordinal": 1,
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": session_id,
                "turn_id": TURN_ID,
                "item": {
                    "type": "UserMessage",
                    "id": f"item-{session_id}",
                    "content": [{"type": "text", "text": marker}],
                },
            },
        },
    ]
    body = _line(records[0])
    body += b"{not-valid-json}\n" if invalid_complete_line else _line(records[1])
    path.write_bytes(body)
    modified_ns = int(timestamp.timestamp() * 1_000_000_000)
    os.utime(path, ns=(modified_ns, modified_ns))
    return path


def _runtime(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    root = tmp_path / "fabric"
    context_fabric.initialize_context_fabric(root)
    home = tmp_path / ".codex"
    return root, home, {str(home): "s-primary"}


def _append_user_record(
    path: Path,
    *,
    session_id: str,
    ordinal: int,
    timestamp: datetime,
    marker: str,
    newline: bool = True,
) -> None:
    timestamp_text = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    record = {
        "timestamp": timestamp_text,
        "ordinal": ordinal,
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "thread_id": session_id,
            "turn_id": TURN_ID,
            "item": {
                "type": "UserMessage",
                "id": f"item-{session_id}-{ordinal}",
                "content": [{"type": "text", "text": marker}],
            },
        },
    }
    encoded = _line(record)
    with path.open("ab") as handle:
        handle.write(encoded if newline else encoded[:-1])


def _raw_messages(root: Path) -> list[str]:
    with sqlite3.connect(root / "context_fabric.sqlite3") as connection:
        return [
            bytes(row[0]).decode("utf-8")
            for row in connection.execute("SELECT raw_text FROM events ORDER BY seq")
        ]


def test_bootstrap_imports_only_latest_recent_root_and_never_opens_old_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    old_history = _rollout(
        home,
        session_id=SESSION_C,
        timestamp=datetime(2020, 1, 2, tzinfo=timezone.utc),
        marker="OLD-HISTORY-MUST-NOT-SCAN",
    )
    older = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(hours=2),
        marker="OLDER-ROOT-MUST-NOT-BOOTSTRAP",
    )
    latest = _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW - timedelta(hours=1),
        marker="LATEST-ROOT-BOOTSTRAP",
    )
    seen: list[Path] = []
    real_classifier = consumer.classify_rollout

    def observing_classifier(path: Path) -> consumer.RolloutClassification:
        seen.append(path)
        return real_classifier(path)

    monkeypatch.setattr(consumer, "classify_rollout", observing_classifier)
    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert receipt["status"] == "completed"
    assert latest in seen
    assert older in seen
    assert old_history not in seen
    assert _raw_messages(root) == ["LATEST-ROOT-BOOTSTRAP"]
    state = json.loads((root / "_consumer" / "state.json").read_text(encoding="utf-8"))
    assert state["carriers"]["s-primary"]["bootstrap_locator"].endswith(latest.name)
    assert not list((root / "_consumer").glob("*.tmp"))


def test_old_directory_root_is_stat_inventoried_then_promoted_only_after_growth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    old_timestamp = datetime(2020, 1, 2, tzinfo=timezone.utc)
    old = _rollout(
        home,
        session_id=SESSION_C,
        timestamp=old_timestamp,
        marker="OLD-BASELINE-ROOT",
    )
    opened: list[Path] = []
    real_classifier = consumer.classify_rollout

    def observing_classifier(path: Path) -> consumer.RolloutClassification:
        opened.append(path)
        return real_classifier(path)

    monkeypatch.setattr(consumer, "classify_rollout", observing_classifier)
    first = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    assert first["counts"]["inventoried"] == 1
    assert old not in opened
    assert _raw_messages(root) == []
    state = json.loads((root / "_consumer" / "state.json").read_text(encoding="utf-8"))
    inventory = state["carriers"]["s-primary"]["inventory"]
    old_locator = next(locator for locator in inventory if locator.endswith(old.name))
    assert inventory[old_locator] == {
        "mtime_ns": old.stat().st_mtime_ns,
        "size": old.stat().st_size,
    }

    _append_user_record(
        old,
        session_id=SESSION_C,
        ordinal=2,
        timestamp=BASE_NOW + timedelta(minutes=1),
        marker="OLD-ROOT-GREW-AFTER-BASELINE",
    )
    changed_ns = int((BASE_NOW + timedelta(minutes=1)).timestamp() * 1_000_000_000)
    os.utime(old, ns=(changed_ns, changed_ns))
    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=2),
    )

    assert old in opened
    assert second["counts"]["awaiting_stable"] == 1
    third = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=4),
    )
    assert third["counts"]["imported"] == 1
    assert _raw_messages(root) == ["OLD-BASELINE-ROOT", "OLD-ROOT-GREW-AFTER-BASELINE"]


def test_future_root_is_discovered_from_last_scan_and_imported(tmp_path: Path) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=10),
        marker="BOOTSTRAP-ROOT",
    )
    first = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    assert first["counts"]["imported"] == 1

    future = _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW + timedelta(minutes=1),
        marker="FUTURE-ROOT",
    )
    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=2),
    )

    assert second["counts"]["awaiting_stable"] == 1
    third = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=4),
    )
    assert third["counts"]["imported"] == 1
    assert _raw_messages(root) == ["BOOTSTRAP-ROOT", "FUTURE-ROOT"]
    assert any(item.get("locator", "").endswith(future.name) for item in third["files"])


def test_bootstrap_selects_one_latest_root_for_each_carrier(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_fabric.initialize_context_fabric(root)
    home_s = tmp_path / ".codex"
    home_b = tmp_path / ".codex-b"
    homes = {str(home_s): "s-primary", str(home_b): "s-account-b"}
    _rollout(
        home_s,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=2),
        marker="S-LATEST-ROOT",
    )
    _rollout(
        home_b,
        session_id=SESSION_B,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="B-LATEST-ROOT",
    )

    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert receipt["counts"]["imported"] == 2
    with sqlite3.connect(root / "context_fabric.sqlite3") as connection:
        carriers = dict(
            connection.execute(
                "SELECT carrier_id,COUNT(*) FROM events GROUP BY carrier_id ORDER BY carrier_id"
            )
        )
    assert carriers == {"s-account-b": 1, "s-primary": 1}


def test_subagent_and_exec_rollouts_are_excluded_by_first_metadata(tmp_path: Path) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=3),
        marker="ROOT-ONLY",
    )
    _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW - timedelta(minutes=2),
        marker="SUBAGENT-MUST-NOT-IMPORT",
        thread_source="subagent",
        subagent=True,
    )
    exec_path = _rollout(
        home,
        session_id=SESSION_C,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="EXEC-MUST-NOT-IMPORT",
        source="exec",
    )

    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert receipt["counts"]["classified_excluded_subagent"] == 1
    assert receipt["counts"]["classified_excluded_non_cli"] == 1
    assert consumer.classify_rollout(exec_path).status == "excluded_non_cli"
    assert _raw_messages(root) == ["ROOT-ONLY"]


def test_unchanged_cursor_skips_public_importer_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="UNCHANGED-CURSOR",
    )
    calls = 0
    real_importer = consumer.import_codex_rollout

    def counted_importer(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return real_importer(*args, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", counted_importer)
    consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=1),
    )

    assert calls == 1
    assert second["counts"]["unchanged_cursor"] == 1


def test_unchanged_incomplete_tail_skips_rehash_until_file_grows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    rollout = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="COMPLETE-PREFIX",
    )
    _append_user_record(
        rollout,
        session_id=SESSION_A,
        ordinal=2,
        timestamp=BASE_NOW,
        marker="TAIL-WAITS-FOR-NEWLINE",
        newline=False,
    )
    calls = 0
    real_importer = consumer.import_codex_rollout

    def counted_importer(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return real_importer(*args, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", counted_importer)
    first = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    assert first["files"][0]["incomplete_tail"] is True
    assert calls == 1

    same_size = rollout.stat().st_size
    assert rollout.stat().st_size == same_size
    second = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=1),
    )
    assert calls == 1
    assert second["counts"]["unchanged_incomplete_tail"] == 1

    with rollout.open("ab") as handle:
        handle.write(b"\n")
    grown_ns = int((BASE_NOW + timedelta(minutes=2)).timestamp() * 1_000_000_000)
    os.utime(rollout, ns=(grown_ns, grown_ns))
    third = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=3),
    )
    assert calls == 1
    assert third["counts"]["awaiting_stable"] == 1
    fourth = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=5),
    )
    assert calls == 2
    assert fourth["counts"]["imported"] == 1
    assert _raw_messages(root) == ["COMPLETE-PREFIX", "TAIL-WAITS-FOR-NEWLINE"]


def test_same_size_completed_tail_is_revalidated_after_stable_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, home, homes = _runtime(tmp_path)
    rollout = _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="SAME-SIZE-PREFIX",
    )
    _append_user_record(
        rollout,
        session_id=SESSION_A,
        ordinal=2,
        timestamp=BASE_NOW,
        marker="SAME-SIZE-TAIL-COMPLETED",
        newline=False,
    )
    with rollout.open("ab") as handle:
        handle.write(b"x")
    calls = 0
    real_importer = consumer.import_codex_rollout

    def counted_importer(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return real_importer(*args, **kwargs)

    monkeypatch.setattr(consumer, "import_codex_rollout", counted_importer)
    first = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    assert first["files"][0]["incomplete_tail"] is True
    original_size = rollout.stat().st_size

    with rollout.open("r+b") as handle:
        handle.seek(-1, os.SEEK_END)
        handle.write(b"\n")
    changed_ns = int((BASE_NOW + timedelta(minutes=1)).timestamp() * 1_000_000_000)
    os.utime(rollout, ns=(changed_ns, changed_ns))
    assert rollout.stat().st_size == original_size
    pending = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=2),
    )
    assert pending["counts"]["awaiting_stable"] == 1
    completed = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=4),
    )

    assert calls == 2
    assert completed["counts"]["imported"] == 1
    assert _raw_messages(root) == ["SAME-SIZE-PREFIX", "SAME-SIZE-TAIL-COMPLETED"]


def test_one_bad_rollout_does_not_block_another_future_root(tmp_path: Path) -> None:
    root, home, homes = _runtime(tmp_path)
    _rollout(
        home,
        session_id=SESSION_A,
        timestamp=BASE_NOW - timedelta(minutes=1),
        marker="BOOTSTRAP",
    )
    consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    bad = _rollout(
        home,
        session_id=SESSION_B,
        timestamp=BASE_NOW + timedelta(minutes=1),
        marker="BAD-MUST-NOT-IMPORT",
        invalid_complete_line=True,
    )
    good = _rollout(
        home,
        session_id=SESSION_C,
        timestamp=BASE_NOW + timedelta(minutes=2),
        marker="GOOD-SURVIVES-BAD-NEIGHBOR",
    )

    deferred = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=3),
    )
    assert deferred["counts"]["awaiting_stable"] == 2
    receipt = consumer.run_consumer(
        root=root,
        allowed_homes=homes,
        now=BASE_NOW + timedelta(minutes=5),
    )

    assert receipt["status"] == "completed_with_errors"
    by_name = {Path(str(item["locator"])).name: item for item in receipt["files"]}
    assert by_name[bad.name]["status"] == "error"
    assert by_name[good.name]["status"] == "imported"
    assert _raw_messages(root) == ["BOOTSTRAP", "GOOD-SURVIVES-BAD-NEIGHBOR"]


def test_overlap_returns_typed_skip_without_mutating_consumer_state(tmp_path: Path) -> None:
    root, _home, homes = _runtime(tmp_path)
    consumer_dir = consumer._consumer_directory(root)
    lock = consumer.ConsumerFileLock(consumer_dir / consumer.LOCK_FILE_NAME)
    assert lock.acquire() is True
    try:
        receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)
    finally:
        lock.release()

    assert receipt["status"] == "skipped_overlap"
    assert receipt["reason"] == "consumer_lock_busy"
    assert not (consumer_dir / "state.json").exists()


def test_file_receipts_are_bounded_while_errors_remain_counted(tmp_path: Path) -> None:
    root, home, homes = _runtime(tmp_path)
    directory = home / "sessions" / "2026" / "08" / "13"
    directory.mkdir(parents=True)
    for index in range(consumer.MAX_RECEIPT_FILES + 7):
        path = directory / f"rollout-invalid-{index:03d}.jsonl"
        path.write_bytes(b"not-json\n")
        modified_ns = int((BASE_NOW - timedelta(minutes=1)).timestamp() * 1_000_000_000)
        os.utime(path, ns=(modified_ns, modified_ns))

    receipt = consumer.run_consumer(root=root, allowed_homes=homes, now=BASE_NOW)

    assert len(receipt["files"]) == consumer.MAX_RECEIPT_FILES
    assert receipt["file_receipts_total"] == consumer.MAX_RECEIPT_FILES + 7
    assert receipt["file_receipts_omitted"] == 7
    assert receipt["counts"]["classified_invalid"] == consumer.MAX_RECEIPT_FILES + 7


def test_installer_has_exact_current_user_ignore_new_contract() -> None:
    script = (consumer.REPO_ROOT / "scripts" / "Install-SContextRolloutConsumer.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "[ValidateSet(1, 2, 5)]" in script
    assert "[int]$Minutes = 2" in script
    assert "XINAO-S-Context-Rollout-Consumer-v1" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "-AllowStartIfOnBatteries" in script
    assert "-DontStopIfGoingOnBatteries" in script
    assert "-I -B" in script
    assert "-RunLevel Limited" in script
    assert "WindowsIdentity]::GetCurrent().Name" in script
    assert "D:\\XINAO_RESEARCH_RUNTIME\\tools\\cpython-3.13.14-official\\python.exe" in script
    assert "E:\\XINAO_RESEARCH_WORKSPACES\\S\\scripts\\context_rollout_consumer.py" in script
    assert "Get-ConsumerTaskAudit" in script
    assert "action_valid" in script
    assert "disallow_start_on_batteries" in script
    assert "contract_valid" in script
    assert "-TaskPath $taskPath" in script
    assert "Principal.LogonType" in script
    assert "Refusing to remove" in script
    assert "Refusing to overwrite" in script
    assert (
        "Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -InputObject $definition |"
        in script
    )
    assert (
        "Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -InputObject $definition -Force"
        not in script
    )
    assert "-Apply" in script and "-Remove" in script and "-Audit" in script
    assert "RunLevel Highest" not in script
    assert consumer.PRODUCTION_CONTEXT_FABRIC_ROOT == Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric"
    )
    with pytest.raises(SystemExit):
        consumer._parser().parse_args(["--store-root", "elsewhere"])
