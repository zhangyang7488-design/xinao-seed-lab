"""JSON-stdio adapter for the shared Codex situation hook."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_HOOK_INPUT_CHARS = 1_000_000
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.codex_situation_hook import handle_hook_event  # noqa: E402


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
        payload = handle_hook_event(event, context_fabric_enabled=True)
    except Exception:
        payload = {"continue": True}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
