#!/usr/bin/env python3
"""Publish, recover, or explicitly roll back the tool-glue constitution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from xinao.tool_glue.publication import (
    DEFAULT_AUTHORITY_PATH,
    DEFAULT_STATE_ROOT,
    DEFAULT_UPDATER_PATH,
    DEFAULT_VERIFIER_PATH,
    PublicationBindings,
    PublicationError,
    discover_pwsh,
    discover_python,
    publish_tool_glue_constitution,
    recover_tool_glue_constitution,
    rollback_tool_glue_constitution,
)


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--authority-path", type=Path, default=DEFAULT_AUTHORITY_PATH)
    parser.add_argument(
        "--state-root",
        type=Path,
        default=DEFAULT_STATE_ROOT,
        help=(
            "transaction journals and CAS archives only; mutual exclusion is always "
            "keyed by the normalized authority path in the canonical guard root"
        ),
    )
    parser.add_argument("--updater", type=Path, default=DEFAULT_UPDATER_PATH)
    parser.add_argument("--verifier", type=Path, default=DEFAULT_VERIFIER_PATH)
    parser.add_argument("--pwsh", type=Path)
    parser.add_argument("--python", type=Path, default=discover_python())
    parser.add_argument(
        "--consumer",
        type=Path,
        default=Path(__file__).resolve().with_name("verify_tool_glue_consumer.py"),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    publish = commands.add_parser("publish", help="CAS-publish and postflight one candidate")
    _add_common_arguments(publish)
    publish.add_argument("--candidate", type=Path, required=True)
    publish.add_argument("--expected-old-sha256", required=True)
    publish.add_argument("--expected-new-sha256", required=True)
    publish.add_argument("--transaction-id")

    recover = commands.add_parser("recover", help="recover the active durable transaction")
    _add_common_arguments(recover)

    rollback = commands.add_parser(
        "rollback", help="roll back one VERIFIED journal from its exact postimage"
    )
    _add_common_arguments(rollback)
    rollback.add_argument("--journal", type=Path, required=True)
    return parser


def _bindings(args: argparse.Namespace) -> PublicationBindings:
    return PublicationBindings(
        pwsh_path=args.pwsh or discover_pwsh(),
        updater_path=args.updater,
        verifier_path=args.verifier,
        python_path=args.python,
        consumer_path=args.consumer,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "publish":
            result = publish_tool_glue_constitution(
                candidate_path=args.candidate,
                expected_old_sha256=args.expected_old_sha256,
                expected_new_sha256=args.expected_new_sha256,
                authority_path=args.authority_path,
                state_root=args.state_root,
                bindings=_bindings(args),
                transaction_id=args.transaction_id,
            )
        elif args.command == "recover":
            result = recover_tool_glue_constitution(
                authority_path=args.authority_path,
                state_root=args.state_root,
                bindings=_bindings(args),
            )
        else:
            result = rollback_tool_glue_constitution(
                journal_path=args.journal,
                authority_path=args.authority_path,
                state_root=args.state_root,
                bindings=_bindings(args),
            )
    except PublicationError as exc:
        print(json.dumps(exc.receipt, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    except Exception as exc:
        failure = {
            "schema_version": "xinao.tool_glue_constitution_publication_result.v1",
            "status": "FAILED",
            "error_code": "UNEXPECTED_FAILURE",
            "error": str(exc),
            "completion_claim_allowed": False,
        }
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
