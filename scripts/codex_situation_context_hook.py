"""JSON-stdio adapter for the shared Codex situation hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_HOOK_INPUT_CHARS = 1_000_000
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.codex_situation_hook import handle_hook_event  # noqa: E402
from services.agent_runtime.context_fabric import evaluate_mount  # noqa: E402

CONTEXT_CONSUMER_TASK_NAME = r"\XINAO-S-Context-Rollout-Consumer-v1"
CONTEXT_CONSUMER_WAKE_EVENTS = frozenset(
    {"SessionStart", "Stop", "PostCompact", "SessionEnd"}
)


def request_context_consumer_wake(
    event: Mapping[str, object],
    *,
    runner: Callable[..., object] = subprocess.Popen,
    system_root: str | None = None,
) -> bool:
    """Best-effort wake of the persistent one-shot disk consumer.

    The hook itself remains the synchronous surfaced-dialogue consumer.  This
    wake only asks Task Scheduler to run the already-installed rollout and
    presentation sidecar; it never opens rollout files on the hook hot path.
    """

    if str(event.get("hook_event_name") or "") not in CONTEXT_CONSUMER_WAKE_EVENTS:
        return False
    try:
        if not evaluate_mount(event).mounted:
            return False
        windows_root = system_root or os.environ.get("SystemRoot", "")
        if not windows_root:
            return False
        schtasks = Path(windows_root) / "System32" / "schtasks.exe"
        if not schtasks.is_file():
            return False
        runner(
            [str(schtasks), "/Run", "/TN", CONTEXT_CONSUMER_TASK_NAME],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        # The scheduled watchdog remains the recovery path.  A wake failure
        # must never reject or delay the user's Codex lifecycle event.
        return False


def main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    try:
        raw = sys.stdin.read(MAX_HOOK_INPUT_CHARS + 1)
        if len(raw) > MAX_HOOK_INPUT_CHARS:
            raise ValueError("hook input exceeds bounded adapter limit")
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("hook input must be an object")
        # Bind mount admission to the hook child's mechanically observed cwd as
        # well as the event-reported cwd.  Direct unit callers can omit this
        # private field; the installed consumer never does.
        event["_context_fabric_actual_cwd"] = str(Path.cwd())
        try:
            payload = handle_hook_event(event, context_fabric_enabled=True)
        finally:
            # A valid mounted lifecycle event should still wake the disk
            # recovery consumer if synchronous capture itself fails.
            request_context_consumer_wake(event)
    except Exception:
        payload = {"continue": True}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
