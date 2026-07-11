"""Serialize integrated_bus Temporal client submissions — one active client per task queue."""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, write_json

SCHEMA_VERSION = "xinao.integrated_bus_temporal_client_queue.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_TEMPORAL_CLIENT_QUEUE_READY"
DEFAULT_TASK_QUEUE = "xinao-integrated-langgraph-plugin-queue"
_PROCESS_SUBMIT_GUARD = threading.Lock()


def temporal_client_queue_enabled() -> bool:
    """Default on: prevents concurrent integrated_bus --temporal clients from contending on one queue."""
    return os.environ.get("XINAO_TEMPORAL_CLIENT_QUEUE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _queue_state_dir(runtime_root: Path, task_queue: str) -> Path:
    safe = task_queue.replace("/", "_").replace("\\", "_")
    return runtime_root / "state" / "integrated_bus_temporal_client_queue" / safe


def _lock_path(runtime_root: Path, task_queue: str) -> Path:
    return _queue_state_dir(runtime_root, task_queue) / "submit.lock"


def _latest_path(runtime_root: Path, task_queue: str) -> Path:
    return _queue_state_dir(runtime_root, task_queue) / "latest.json"


def _queue_timeout_sec() -> float:
    raw = os.environ.get("XINAO_TEMPORAL_CLIENT_QUEUE_TIMEOUT", "900")
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 900.0


def _queue_poll_sec() -> float:
    raw = os.environ.get("XINAO_TEMPORAL_CLIENT_QUEUE_POLL", "2")
    try:
        return max(0.25, float(raw))
    except ValueError:
        return 2.0


def _stale_lock_sec() -> float:
    raw = os.environ.get("XINAO_TEMPORAL_CLIENT_QUEUE_STALE", "1800")
    try:
        return max(60.0, float(raw))
    except ValueError:
        return 1800.0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def _read_lock_payload(lock_path: Path) -> dict[str, Any]:
    if not lock_path.is_file():
        return {}
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _lock_is_stale(lock_path: Path) -> bool:
    if not lock_path.is_file():
        return False
    payload = _read_lock_payload(lock_path)
    pid = int(payload.get("pid") or 0)
    acquired_at = str(payload.get("acquired_at") or "")
    if pid and not _pid_alive(pid):
        return True
    if acquired_at:
        try:
            acquired = datetime.fromisoformat(acquired_at)
            age = (datetime.now(timezone.utc) - acquired.astimezone(timezone.utc)).total_seconds()
            if age > _stale_lock_sec():
                return True
        except ValueError:
            pass
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return False
    return age > _stale_lock_sec()


def _try_acquire_lock(lock_path: Path, holder: dict[str, Any]) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(holder, ensure_ascii=False) + "\n"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    with _PROCESS_SUBMIT_GUARD:
        try:
            fd = os.open(str(lock_path), flags)
        except FileExistsError:
            if _lock_is_stale(lock_path):
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    return False
                try:
                    fd = os.open(str(lock_path), flags)
                except FileExistsError:
                    return False
            else:
                return False
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
    return True


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


@contextmanager
def acquire_temporal_client_slot(
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    task_queue: str = DEFAULT_TASK_QUEUE,
    workflow_id: str = "",
    address: str = "127.0.0.1:7233",
) -> Iterator[dict[str, Any]]:
    """Block until this process owns the sole integrated_bus Temporal client submit slot."""
    if not temporal_client_queue_enabled():
        yield {
            "schema_version": SCHEMA_VERSION,
            "sentinel": SENTINEL,
            "queue_enabled": False,
            "task_queue": task_queue,
            "workflow_id": workflow_id,
            "address": address,
        }
        return

    lock_path = _lock_path(runtime_root, task_queue)
    latest_path = _latest_path(runtime_root, task_queue)
    timeout = _queue_timeout_sec()
    poll = _queue_poll_sec()
    started = time.monotonic()
    acquired_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    holder = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "queue_enabled": True,
        "pid": os.getpid(),
        "task_queue": task_queue,
        "workflow_id": workflow_id,
        "address": address,
        "acquired_at": acquired_at,
        "status": "holding",
    }
    waited_sec = 0.0
    while True:
        if _try_acquire_lock(lock_path, holder):
            waited_sec = time.monotonic() - started
            holder["waited_sec"] = round(waited_sec, 3)
            write_json(latest_path, holder)
            break
        if time.monotonic() - started >= timeout:
            blocker = _read_lock_payload(lock_path)
            raise TimeoutError(
                f"temporal client queue timeout after {timeout}s for {task_queue}; "
                f"holder={blocker.get('workflow_id') or blocker.get('pid')}"
            )
        time.sleep(poll)

    try:
        yield holder
    finally:
        released_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        holder["status"] = "released"
        holder["released_at"] = released_at
        holder["held_sec"] = round(
            (
                datetime.fromisoformat(released_at).astimezone(timezone.utc)
                - datetime.fromisoformat(acquired_at).astimezone(timezone.utc)
            ).total_seconds(),
            3,
        )
        write_json(latest_path, holder)
        _release_lock(lock_path)
