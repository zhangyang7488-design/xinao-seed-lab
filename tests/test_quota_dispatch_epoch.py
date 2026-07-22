from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from services.agent_runtime.quota_dispatch_epoch import (
    QuotaDispatchEpochError,
    _EpochLock,
    get_or_refresh_dispatch_epoch,
    record_dispatch_epoch_usage,
    validate_dispatch_epoch_pointer,
)


def test_epoch_lock_uses_os_lock_not_stale_file_deletion(tmp_path: Path) -> None:
    directory = tmp_path / "epoch"
    with _EpochLock(directory, timeout_sec=1):
        lock_path = directory / ".refresh.lock"
        old = time.time() - 3600
        os.utime(lock_path, (old, old))
        with pytest.raises(QuotaDispatchEpochError, match="lock timeout"):
            with _EpochLock(directory, timeout_sec=0.1):
                pytest.fail("an active OS lock was stolen because its mtime looked stale")

    with _EpochLock(directory, timeout_sec=0.1):
        assert (directory / ".refresh.lock").is_file()


def test_epoch_lock_is_released_when_holder_process_dies(tmp_path: Path) -> None:
    directory = tmp_path / "epoch"
    code = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from services.agent_runtime.quota_dispatch_epoch import _EpochLock\n"
        "with _EpochLock(Path(sys.argv[1]), timeout_sec=2):\n"
        " print('READY', flush=True)\n"
        " time.sleep(60)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(directory)],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"
        with pytest.raises(QuotaDispatchEpochError, match="lock timeout"):
            with _EpochLock(directory, timeout_sec=0.1):
                pytest.fail("a second process stole an active epoch lock")
    finally:
        process.terminate()
        process.wait(timeout=5)

    with _EpochLock(directory, timeout_sec=0.5):
        assert (directory / ".refresh.lock").is_file()


def _report(call_count: int) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "queriedAt": f"2026-07-21T00:00:0{call_count}Z",
        "trustedResource": {"codexLive": True, "grokLive": True},
        "codex": {"live": True, "buckets": []},
        "grok": {"live": True, "buckets": []},
    }


def test_same_epoch_reuses_one_live_query_and_invalidation_refreshes_once(
    tmp_path: Path,
) -> None:
    calls: list[int] = []

    def collector() -> dict[str, object]:
        calls.append(len(calls) + 1)
        return _report(calls[-1])

    first = get_or_refresh_dispatch_epoch(
        runtime_root=tmp_path,
        epoch_id="episode-1",
        source_identity="quota-query.mjs@sha256:test",
        collector=collector,
    )
    second = get_or_refresh_dispatch_epoch(
        runtime_root=tmp_path,
        epoch_id="episode-1",
        source_identity="quota-query.mjs@sha256:test",
        collector=collector,
    )
    assert calls == [1]
    assert first["status"] == "refreshed"
    assert second["status"] == "cache_hit"
    assert first["snapshot"]["snapshot_id"] == second["snapshot"]["snapshot_id"]

    invalidated = get_or_refresh_dispatch_epoch(
        runtime_root=tmp_path,
        epoch_id="episode-1",
        source_identity="quota-query.mjs@sha256:test",
        collector=collector,
        invalidate_reason="provider identity changed",
    )
    again = get_or_refresh_dispatch_epoch(
        runtime_root=tmp_path,
        epoch_id="episode-1",
        source_identity="quota-query.mjs@sha256:test",
        collector=collector,
    )
    assert calls == [1, 2]
    assert invalidated["snapshot"]["generation"] == 2
    assert again["snapshot"]["snapshot_id"] == invalidated["snapshot"]["snapshot_id"]


def test_source_identity_change_invalidates_but_unknown_quota_does_not_block(
    tmp_path: Path,
) -> None:
    first = get_or_refresh_dispatch_epoch(
        runtime_root=tmp_path,
        epoch_id="episode-2",
        source_identity="collector@one",
        collector=lambda: _report(1),
    )

    def unavailable() -> dict[str, object]:
        raise RuntimeError("temporary telemetry failure")

    second = get_or_refresh_dispatch_epoch(
        runtime_root=tmp_path,
        epoch_id="episode-2",
        source_identity="collector@two",
        collector=unavailable,
    )
    assert first["snapshot"]["freshness"] == "fresh"
    assert second["status"] == "refreshed_unknown"
    assert second["snapshot"]["freshness"] == "unknown"
    assert second["snapshot"]["dispatch_blocked"] is False
    assert "temporary telemetry failure" in second["snapshot"]["collector_error"]


def test_pointer_is_hash_bound_and_usage_is_append_only(tmp_path: Path) -> None:
    result = get_or_refresh_dispatch_epoch(
        runtime_root=tmp_path,
        epoch_id="episode-3",
        source_identity="collector@one",
        collector=lambda: _report(1),
    )
    pointer = Path(result["pointer_path"])
    validated = validate_dispatch_epoch_pointer(pointer, expected_epoch_id="episode-3")
    assert validated["snapshot_id"] == result["snapshot"]["snapshot_id"]

    usage_one = record_dispatch_epoch_usage(
        runtime_root=tmp_path,
        epoch_id="episode-3",
        work_key="wk-1",
        provider_id="grok_acpx_headless",
        input_tokens=60,
        output_tokens=40,
    )
    usage_two = record_dispatch_epoch_usage(
        runtime_root=tmp_path,
        epoch_id="episode-3",
        work_key="wk-2",
        provider_id="grok_acpx_headless",
        input_tokens=10,
        output_tokens=20,
    )
    assert usage_one["totals"]["total_tokens"] == 100
    assert usage_two["totals"] == {
        "attempt_count": 2,
        "input_tokens": 70,
        "output_tokens": 60,
        "total_tokens": 130,
    }
    lines = (pointer.parent / "usage.events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["epoch_id"] == "episode-3" for line in lines)
