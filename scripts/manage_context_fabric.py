"""Manage the S/B-only continuous conversation context runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.context_fabric import (  # noqa: E402
    DEFAULT_CONTEXT_FABRIC_ROOT,
    append_projection,
    append_relation,
    create_snapshot,
    evaluate_mount,
    import_codex_rollout,
    initialize_context_fabric,
    read_event,
    render_materialized_context,
    search_events,
    store_inventory,
    verify_event_chain,
)

MAX_SPEC_BYTES = 262_144


def _json_object(path: Path) -> dict[str, object]:
    if path.stat().st_size > MAX_SPEC_BYTES:
        raise ValueError(f"JSON specification exceeds {MAX_SPEC_BYTES} bytes: {path}")
    value = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON specification must be an object: {path}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Initialize, import, project, inspect, and verify the non-authoritative "
            "S/B conversation context runtime."
        )
    )
    parser.add_argument("--store-root", type=Path, default=DEFAULT_CONTEXT_FABRIC_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("initialize")

    importer = subparsers.add_parser("import-rollout")
    importer.add_argument("--codex-home", type=Path, required=True)
    importer.add_argument("--rollout", type=Path, required=True)

    project = subparsers.add_parser("project")
    project.add_argument("--spec-file", type=Path, required=True)

    relate = subparsers.add_parser("relate")
    relate.add_argument("--spec-file", type=Path, required=True)

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--query", default="")
    inspect.add_argument("--max-chars", type=int, default=6_000)
    inspect.add_argument("--session-id", default="")
    inspect.add_argument("--carrier-id", default="")

    search = subparsers.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=20)

    event = subparsers.add_parser("event")
    event.add_argument("--event-id", required=True)

    mount = subparsers.add_parser("mount-check")
    mount.add_argument("--codex-home", required=True)
    mount.add_argument("--cwd", required=True)

    subparsers.add_parser("inventory")
    subparsers.add_parser("verify")
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = _parser().parse_args(argv)
    if args.command == "initialize":
        result: object = initialize_context_fabric(args.store_root)
    elif args.command == "import-rollout":
        result = import_codex_rollout(
            args.rollout,
            carrier_home=args.codex_home,
            root=args.store_root,
        )
    elif args.command == "project":
        result = append_projection(_json_object(args.spec_file), root=args.store_root)
    elif args.command == "relate":
        result = append_relation(_json_object(args.spec_file), root=args.store_root)
    elif args.command == "inspect":
        result = {
            "context": render_materialized_context(
                query=args.query or None,
                root=args.store_root,
                session_id=args.session_id,
                carrier_id=args.carrier_id,
                max_chars=args.max_chars,
            ),
            "authority": False,
        }
    elif args.command == "event":
        result = read_event(args.event_id, root=args.store_root)
    elif args.command == "search":
        result = {
            "query": args.query,
            "events": search_events(args.query, root=args.store_root, limit=args.limit),
            "authority": False,
        }
    elif args.command == "mount-check":
        result = {
            **evaluate_mount({"cwd": args.cwd}, environ={"CODEX_HOME": args.codex_home}).__dict__,
            "authority": False,
        }
    elif args.command == "inventory":
        result = store_inventory(args.store_root)
    elif args.command == "snapshot":
        result = create_snapshot(args.output_dir, root=args.store_root)
    else:
        result = verify_event_chain(args.store_root)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
