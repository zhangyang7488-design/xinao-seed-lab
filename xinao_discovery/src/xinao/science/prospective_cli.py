"""Owner one-shot prospective CLI surfaces.

Packaged via ``xinao prospective …`` (project.scripts):
capture / reveal / write-owner-disposition / freeze-from-disposition /
settle-from-reveal / settle-all-from-reveal / canary.

``settle-from-reveal`` = single-seat shadow portfolio head only.
``settle-all-from-reveal`` = multipolicy FrozenDecisionSet (every ticket once).

One-shot only: no loop, poll, auto-freeze, auto-settle, next-period start, or daemon.
Does not authenticate Codex.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from xinao.science.freeze_adapter import FreezeAdapterError, apply_freeze_from_disposition
from xinao.science.owner_disposition import (
    OwnerDispositionError,
    load_and_verify_disposition,
    parse_disposition_json_strict,
    write_owner_disposition_artifact,
)
from xinao.science.prospective_live_canary import run_live_source_canary
from xinao.science.prospective_source_thin import (
    ProspectiveSourceError,
    capture_prospective_reveal,
    capture_prospective_target_authority,
    default_clock,
)
from xinao.science.settle_all_from_reveal_adapter import (
    SettleAllFromRevealError,
    apply_settle_all_from_reveal,
)
from xinao.science.settle_from_reveal_adapter import (
    SettleFromRevealError,
    apply_settle_from_reveal,
)


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _fail(reason: str, detail: str = "") -> int:
    _print(
        {
            "ok": False,
            "error": f"{reason}: {detail}" if detail else reason,
            "reason_code": reason,
            "completion_claim_allowed": False,
            "parent_complete": False,
            "auto_freeze": False,
            "auto_settle": False,
            "auto_feedback": False,
            "auto_next_period": False,
            "auto_next_research": False,
            "daemon": False,
            "caller_outcome_override_accepted": False,
            "owner_channel_authority": "UNPROVEN_BY_LIBRARY",
            "physical_owner_write_isolation_verified": False,
        }
    )
    return 1


def add_prospective_parsers(groups: argparse._SubParsersAction[Any]) -> None:
    prospective = groups.add_parser(
        "prospective",
        help=(
            "Owner one-shot macaujc2 capture/reveal/write-owner-disposition/"
            "freeze-from-disposition/settle-from-reveal/settle-all-from-reveal "
            "(not a daemon; does not authenticate Codex)"
        ),
    )
    commands = prospective.add_subparsers(dest="command", required=True)

    capture = commands.add_parser(
        "capture",
        help="Capture prospective target into Owner authority root (one-shot, no freeze)",
    )
    capture.add_argument("--authority-root", type=Path, required=True)
    capture.add_argument("--contract", type=Path, required=True)
    capture.add_argument("--expected-contract-sha256", required=True)
    capture.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate args and print plan only; do not fetch or write",
    )

    reveal = commands.add_parser(
        "reveal",
        help="Reveal sealed target after guard from Owner authority CAS (no settlement write)",
    )
    reveal.add_argument("--authority-root", type=Path, required=True)
    reveal.add_argument("--packet-content-hash", required=True)
    reveal.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate args only; do not fetch or write",
    )

    write_disp = commands.add_parser(
        "write-owner-disposition",
        help=(
            "Write sealed Codex Owner disposition artifact under owner-state-root CAS. "
            "Validates pool binding/hashes/role boundaries; never freezes/settles/adopts "
            "or starts the next Episode. Does not authenticate Codex."
        ),
    )
    write_disp.add_argument(
        "--owner-state-root",
        type=Path,
        required=True,
        help="Owner-selected state root for disposition CAS (must be path-separated from pool)",
    )
    write_disp.add_argument(
        "--pool-root",
        type=Path,
        required=True,
        help="Candidate pool root the disposition must bind",
    )
    write_disp.add_argument(
        "--payload",
        type=Path,
        required=True,
        help="Explicit sealed disposition payload JSON (no self-hash field)",
    )
    write_disp.add_argument(
        "--expected-result-sha256",
        default=None,
        help="Optional caller-claimed result_sha256 that must match payload+pool entry",
    )
    write_disp.add_argument(
        "--expected-pool-entry-content-hash",
        default=None,
        help="Optional caller-claimed pool_entry_content_hash that must match payload+pool",
    )

    freeze = commands.add_parser(
        "freeze-from-disposition",
        help=(
            "Production Owner freeze from sealed disposition via apply_freeze_from_disposition. "
            "Host UTC is sampled at freeze (authoritative action time <= sealed deadline); "
            "no public --owner-freeze-time override."
        ),
    )
    freeze.add_argument("--pool-root", type=Path, required=True)
    freeze.add_argument("--owner-state-root", type=Path, required=True)
    freeze.add_argument("--disposition", type=Path, required=True)
    freeze.add_argument(
        "--portfolio-root",
        type=Path,
        required=True,
        help="Live portfolio/shadow root (Owner-controlled)",
    )
    freeze.add_argument(
        "--authority-root",
        type=Path,
        required=True,
        help="Owner authority CAS root holding the sealed packet",
    )
    freeze.add_argument("--mode", choices=("portfolio", "episode"), default="portfolio")
    freeze.add_argument("--request-out", type=Path)
    freeze.add_argument("--result-sha256")

    settle = commands.add_parser(
        "settle-from-reveal",
        help=(
            "One-shot mechanical portfolio settlement from sealed prospective reveal. "
            "Outcome number/source/time are derived only from Owner authority CAS; "
            "no public --outcome / --actual-special-number override. Does not "
            "feedback, freeze next period, or start research."
        ),
    )
    settle.add_argument(
        "--authority-root",
        type=Path,
        required=True,
        help="Owner authority CAS root holding sealed packet + reveal",
    )
    settle.add_argument(
        "--portfolio-root",
        type=Path,
        required=True,
        help="Live portfolio/shadow root with already-frozen period head",
    )
    settle.add_argument(
        "--packet-content-hash",
        required=True,
        help="Exact sealed packet content hash (authority identity pin)",
    )
    settle.add_argument(
        "--reveal-content-hash",
        help="Optional exact reveal content hash pin (must match durable reveal index)",
    )
    settle.add_argument(
        "--expected-frozen-episode-hash",
        help="Optional exact frozen episode content hash (stale head fail-closed)",
    )
    settle.add_argument(
        "--period-index",
        type=int,
        help="Optional exact portfolio period index pin",
    )
    settle.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate args only; do not settle",
    )

    settle_all = commands.add_parser(
        "settle-all-from-reveal",
        help=(
            "Multipolicy settle-all: every FrozenDecisionSet ticket exactly once "
            "from one sealed reveal (authority CAS or independently authored "
            "reveal artifact). Not single-seat portfolio settle-from-reveal. "
            "No public --outcome / --actual-special-number / ticket subset. "
            "Does not claim scientific promotion or formal campaign completion."
        ),
    )
    settle_all.add_argument(
        "--settlement-root",
        type=Path,
        required=True,
        help="Isolated multipolicy settlement write root (not formal commission root)",
    )
    settle_all.add_argument(
        "--freeze-set",
        type=Path,
        required=True,
        help="Path to sealed FrozenDecisionSet JSON",
    )
    settle_all.add_argument(
        "--expected-freeze-set-hash",
        required=True,
        help="Exact FrozenDecisionSet content_hash pin (fail-closed on drift)",
    )
    settle_all.add_argument(
        "--reveal-artifact",
        type=Path,
        default=None,
        help=(
            "Independently authored sealed reveal JSON (authority envelope or "
            "explicitly labeled isolated fixture). Mutually exclusive with "
            "authority-root+reveal-content-hash."
        ),
    )
    settle_all.add_argument(
        "--authority-root",
        type=Path,
        default=None,
        help="Owner authority CAS root holding sealed prospective reveal",
    )
    settle_all.add_argument(
        "--reveal-content-hash",
        default=None,
        help="Exact reveal content hash pin under authority-root",
    )
    settle_all.add_argument(
        "--settlement-set-ref",
        default=None,
        help="Optional settlement_set_ref identity (deterministic default if omitted)",
    )
    settle_all.add_argument(
        "--portfolio-ref",
        default=None,
        help="Optional multipolicy portfolio_ref for ACTION accounting bundles",
    )
    settle_all.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate args only; do not settle or write settlement-root",
    )

    canary = commands.add_parser(
        "canary",
        help=(
            "Opt-in live-source canary (authorized history/point/site only). "
            "Requires --i-accept-network-canary. Never writes campaign state."
        ),
    )
    canary.add_argument("--contract", type=Path, required=True)
    canary.add_argument("--expected-contract-sha256", required=True)
    canary.add_argument(
        "--i-accept-network-canary",
        action="store_true",
        required=True,
        help="Explicit opt-in to network GETs against authorized endpoints",
    )


def dispatch_prospective(args: argparse.Namespace) -> int:
    try:
        if args.command == "capture":
            if args.dry_run:
                _print(
                    {
                        "ok": True,
                        "dry_run": True,
                        "command": "prospective capture",
                        "authority_root": str(args.authority_root),
                        "contract": str(args.contract),
                        "expected_contract_sha256": args.expected_contract_sha256,
                        "writes": False,
                        "auto_freeze": False,
                        "daemon": False,
                        "frontier_source": "history_year+point_next+same_origin_schedule",
                        "latest_used": False,
                        "completion_claim_allowed": False,
                    }
                )
                return 0
            result = capture_prospective_target_authority(
                authority_root=args.authority_root,
                contract_path=args.contract,
                expected_contract_sha256=args.expected_contract_sha256,
            )
            _print(
                {
                    "ok": result.get("ok", True),
                    "command": "prospective capture",
                    "target_expect": result["packet"]["target_expect"],
                    "target_ref": result["packet"]["target_ref"],
                    "freeze_deadline": result["packet"]["freeze_deadline"],
                    "target_guard_open_time": result["packet"]["target_guard_open_time"],
                    "packet_content_hash": result["packet_content_hash"],
                    "capture_sha256": result["packet"]["capture_sha256"],
                    "schedule_source_sha256": result["packet"]["schedule"][
                        "schedule_source_sha256"
                    ],
                    "owner_channel_authority": result.get("owner_channel_authority"),
                    "physical_owner_write_isolation_verified": False,
                    "trusted_time_proof": False,
                    "completion_claim_allowed": False,
                    "parent_complete": False,
                    "auto_freeze": False,
                    "daemon": False,
                }
            )
            return 0 if result.get("ok") else 1

        if args.command == "reveal":
            if args.dry_run:
                _print(
                    {
                        "ok": True,
                        "dry_run": True,
                        "command": "prospective reveal",
                        "authority_root": str(args.authority_root),
                        "packet_content_hash": args.packet_content_hash,
                        "settlement_written": False,
                        "writes_reveal_cas_only": True,
                        "completion_claim_allowed": False,
                    }
                )
                return 0
            result = capture_prospective_reveal(
                authority_root=args.authority_root,
                packet_content_hash=args.packet_content_hash,
            )
            _print(
                {
                    "ok": result.get("ok", True),
                    "command": "prospective reveal",
                    "target_expect": result["reveal"]["target_expect"],
                    "reveal_content_hash": result["reveal_content_hash"],
                    "admission_status": result["admission_status"],
                    "settlement_written": False,
                    "completion_claim_allowed": False,
                    "parent_complete": False,
                    "owner_channel_authority": "UNPROVEN_BY_LIBRARY",
                }
            )
            return 0 if result.get("ok") else 1

        if args.command == "write-owner-disposition":
            return _dispatch_write_owner_disposition(args)

        if args.command == "freeze-from-disposition":
            # Host UTC sampled inside apply_freeze_from_disposition (not CLI override).
            result = apply_freeze_from_disposition(
                pool_root=args.pool_root,
                owner_state_root=args.owner_state_root,
                disposition_path=args.disposition,
                shadow_root=args.portfolio_root,
                mode=args.mode,
                result_sha256=args.result_sha256,
                request_out=args.request_out,
                authority_root=args.authority_root,
            )
            _print(
                {
                    "ok": result.get("ok", True),
                    "command": "prospective freeze-from-disposition",
                    "mode": result.get("mode"),
                    "period_index": result.get("period_index"),
                    "frozen_episode_hash": result.get("frozen_episode_hash"),
                    "research_binding_sha256": result.get("research_binding_sha256"),
                    "request_content_hash": result.get("request_content_hash"),
                    "freeze_action_time": result.get("freeze_action_time"),
                    "disposition_frozen_at": result.get("disposition_frozen_at"),
                    "owner_channel_authority": result.get("owner_channel_authority"),
                    "physical_owner_write_isolation_verified": False,
                    "completion_claim_allowed": False,
                    "auto_settle": False,
                    "auto_next_period": False,
                    "daemon": False,
                }
            )
            return 0 if result.get("ok") else 1

        if args.command == "settle-from-reveal":
            if args.dry_run:
                _print(
                    {
                        "ok": True,
                        "dry_run": True,
                        "command": "prospective settle-from-reveal",
                        "authority_root": str(args.authority_root),
                        "portfolio_root": str(args.portfolio_root),
                        "packet_content_hash": args.packet_content_hash,
                        "reveal_content_hash": args.reveal_content_hash,
                        "expected_frozen_episode_hash": args.expected_frozen_episode_hash,
                        "period_index": args.period_index,
                        "writes": False,
                        "settlement_written": False,
                        "caller_outcome_override_accepted": False,
                        "auto_feedback": False,
                        "auto_next_period": False,
                        "auto_next_research": False,
                        "daemon": False,
                        "completion_claim_allowed": False,
                    }
                )
                return 0
            result = apply_settle_from_reveal(
                authority_root=args.authority_root,
                portfolio_root=args.portfolio_root,
                packet_content_hash=args.packet_content_hash,
                reveal_content_hash=args.reveal_content_hash,
                expected_frozen_episode_hash=args.expected_frozen_episode_hash,
                period_index=args.period_index,
            )
            _print(result)
            return 0 if result.get("ok") else 1

        if args.command == "settle-all-from-reveal":
            if args.dry_run:
                _print(
                    {
                        "ok": True,
                        "dry_run": True,
                        "command": "prospective settle-all-from-reveal",
                        "object_model": "multipolicy_FrozenDecisionSet",
                        "not_single_seat_shadow_portfolio": True,
                        "settlement_root": str(args.settlement_root),
                        "freeze_set": str(args.freeze_set),
                        "expected_freeze_set_hash": args.expected_freeze_set_hash,
                        "reveal_artifact": (
                            str(args.reveal_artifact) if args.reveal_artifact else None
                        ),
                        "authority_root": (
                            str(args.authority_root) if args.authority_root else None
                        ),
                        "reveal_content_hash": args.reveal_content_hash,
                        "writes": False,
                        "settlement_written": False,
                        "caller_outcome_override_accepted": False,
                        "caller_ticket_subset_accepted": False,
                        "scientific_promotion": False,
                        "completion_claim_allowed": False,
                        "auto_feedback": False,
                        "daemon": False,
                    }
                )
                return 0
            result = apply_settle_all_from_reveal(
                settlement_root=args.settlement_root,
                freeze_set_path=args.freeze_set,
                expected_freeze_set_hash=args.expected_freeze_set_hash,
                reveal_artifact=args.reveal_artifact,
                authority_root=args.authority_root,
                reveal_content_hash=args.reveal_content_hash,
                settlement_set_ref=args.settlement_set_ref,
                portfolio_ref=args.portfolio_ref,
            )
            _print(result)
            return 0 if result.get("ok") else 1

        if args.command == "canary":
            if not args.i_accept_network_canary:
                return _fail(
                    "CANARY_OPT_IN_REQUIRED",
                    "pass --i-accept-network-canary for explicit network canary",
                )
            result = run_live_source_canary(
                contract_path=args.contract,
                expected_contract_sha256=args.expected_contract_sha256,
                clock=default_clock,
            )
            _print({"command": "prospective canary", **result})
            return 0 if result.get("ok") else 1

        return _fail("UNKNOWN_PROSPECTIVE_COMMAND", str(args.command))
    except OwnerDispositionError as exc:
        return _fail(exc.reason_code, exc.detail)
    except ProspectiveSourceError as exc:
        return _fail(exc.reason_code, exc.detail)
    except FreezeAdapterError as exc:
        return _fail(exc.reason_code, exc.detail)
    except SettleFromRevealError as exc:
        return _fail(exc.reason_code, exc.detail)
    except SettleAllFromRevealError as exc:
        return _fail(exc.reason_code, exc.detail)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return _fail("PROSPECTIVE_CLI_ERROR", str(exc))


def _dispatch_write_owner_disposition(args: argparse.Namespace) -> int:
    """Seal disposition under Owner CAS; verify pool binding; never continue."""

    payload_path = Path(args.payload)
    if not payload_path.is_file():
        return _fail("DISPOSITION_PAYLOAD_MISSING", str(payload_path))
    raw = payload_path.read_bytes()
    if not raw:
        return _fail("DISPOSITION_PAYLOAD_EMPTY", str(payload_path))
    payload = parse_disposition_json_strict(raw)

    if args.expected_result_sha256 is not None:
        claimed = payload.get("result_sha256")
        if claimed != args.expected_result_sha256:
            return _fail(
                "DISPOSITION_RESULT_HASH_MISMATCH",
                f"caller={args.expected_result_sha256} payload={claimed}",
            )
    if args.expected_pool_entry_content_hash is not None:
        claimed_entry = payload.get("pool_entry_content_hash")
        if claimed_entry != args.expected_pool_entry_content_hash:
            return _fail(
                "DISPOSITION_POOL_ENTRY_HASH_MISMATCH",
                f"caller={args.expected_pool_entry_content_hash} payload={claimed_entry}",
            )

    written = write_owner_disposition_artifact(
        owner_state_root=args.owner_state_root,
        payload=payload,
        pool_root=args.pool_root,
    )
    verified = load_and_verify_disposition(
        disposition_path=Path(written["disposition_path"]),
        owner_state_root=args.owner_state_root,
        pool_root=args.pool_root,
        result_sha256=args.expected_result_sha256,
    )
    _print(
        {
            "ok": True,
            "command": "prospective write-owner-disposition",
            "status": "OWNER_DISPOSITION_WRITTEN",
            "disposition_path": written["disposition_path"],
            "owner_artifact_sha256": written["owner_artifact_sha256"],
            "owner_state_root": written["owner_state_root"],
            "bytes_written": written["bytes_written"],
            "result_sha256": verified["disposition"]["result_sha256"],
            "pool_entry_content_hash": verified["disposition"]["pool_entry_content_hash"],
            "period_index": verified["disposition"]["period_index"],
            "science_disposition": verified["disposition"]["science_disposition"],
            "account_identity": verified["disposition"]["account_identity"],
            "owner_channel_authority": verified["owner_channel_authority"],
            "owner_disposition_authentic": verified["owner_disposition_authentic"],
            "path_separated_from_pool": verified["path_separated_from_pool"],
            "physical_owner_write_isolation_verified": False,
            "candidate_only": True,
            "owner_adopted": False,
            "freeze_written": False,
            "settlement_written": False,
            "auto_freeze": False,
            "auto_settle": False,
            "auto_next_period": False,
            "next_task_created": False,
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "daemon": False,
        }
    )
    return 0


__all__ = ["add_prospective_parsers", "dispatch_prospective"]
