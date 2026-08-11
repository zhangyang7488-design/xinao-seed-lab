"""Manage one explicit, provisional CurrentSituation checkpoint per Codex session."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.codex_situation_hook import (  # noqa: E402
    DEFAULT_CURRENT_SITUATION_ROOT,
    compact_checkpoint,
    session_store_path,
)
from services.agent_runtime.current_situation import (  # noqa: E402
    MAX_SNAPSHOT_BYTES,
    apply_transition,
    initialize_store,
    load_current,
    retire_store,
)


def _json_object(path: Path) -> dict[str, object]:
    if path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError(f"JSON input exceeds {MAX_SNAPSHOT_BYTES} bytes: {path}")
    value = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create, revise, or inspect a non-authoritative per-session current-world checkpoint."
        )
    )
    parser.add_argument("--store-root", type=Path, default=DEFAULT_CURRENT_SITUATION_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("initialize")
    initialize.add_argument("--session-id", required=True)
    initialize.add_argument("--snapshot-file", required=True, type=Path)

    apply = subparsers.add_parser("apply")
    apply.add_argument("--session-id", required=True)
    apply.add_argument("--transition-file", required=True, type=Path)

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--session-id", required=True)
    inspect.add_argument("--compact", action="store_true")

    retire = subparsers.add_parser("retire")
    retire.add_argument("--session-id", required=True)
    retire.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = _parser().parse_args(argv)
    store = session_store_path(args.session_id, store_root=args.store_root)
    if args.command == "initialize":
        current_path = initialize_store(store, _json_object(args.snapshot_file))
        result: dict[str, object] = {
            "status": "initialized",
            "session_id": args.session_id,
            "current_path": str(current_path),
            "authority": False,
        }
    elif args.command == "apply":
        result = {
            "status": "evaluated",
            "session_id": args.session_id,
            **apply_transition(store, _json_object(args.transition_file)),
            "authority": False,
        }
    elif args.command == "retire":
        result = {
            "session_id": args.session_id,
            **retire_store(store, reason=args.reason),
            "authority": False,
        }
    else:
        snapshot = load_current(store)
        result = compact_checkpoint(snapshot) if args.compact else snapshot
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
