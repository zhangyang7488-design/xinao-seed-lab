"""wave52: demote legacy flat freeze public verb; one production freeze path.

Reproduces the pre-repair defect shape (caller-authored frozen_at + no Owner
authority) against production CLI/Skill entrypoints and proves fail-closed.
Library freeze_episode remains for tests-only fixtures and disposition adapter.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xinao.cli import main as xinao_main
from xinao.shadow_lifecycle.consumer import (
    build_parser as shadow_build_parser,
)
from xinao.shadow_lifecycle.consumer import (
    dispatch as shadow_dispatch,
)
from xinao.shadow_lifecycle.consumer import (
    freeze_episode,
    init_episode,
    inspect_episode,
    settle_episode,
)
from xinao.shadow_lifecycle.store import StoreError, detect_phase

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"

OPEN_AT = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
FREEZE_AT = OPEN_AT - timedelta(minutes=5)
DEADLINE = OPEN_AT - timedelta(minutes=1)
CUTOFF = FREEZE_AT - timedelta(minutes=1)


def _unsafe_flat_request(path: Path, *, episode_ref: str = "ep.unsafe.flat") -> Path:
    """Exact old unsafe shape: caller-authored frozen_at, no Owner authority."""

    body = {
        "episode_ref": episode_ref,
        "target_ref": "macaujc2:2026-07-31",
        "target_open_time": OPEN_AT.isoformat().replace("+00:00", "Z"),
        "freeze_deadline": DEADLINE.isoformat().replace("+00:00", "Z"),
        "frozen_at": FREEZE_AT.isoformat().replace("+00:00", "Z"),
        "science_decision": {
            "science_decision_ref": "sci.unsafe.1",
            "identity": "POLICY_NO_ACTION",
            "knowledge_cutoff": CUTOFF.isoformat().replace("+00:00", "Z"),
            "rationale_ref": "rationale.unsafe.1",
        },
        "account_decision": {
            "account_decision_ref": "acct.unsafe.1",
            "identity": "RESEARCHER_ACCOUNT_NO_ACTION",
            "rule_ref": "rule.1",
            "odds_version_ref": "odds.1",
        },
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_public_flat_freeze_cli_failclosed_exact_old_unsafe_call(tmp_path: Path) -> None:
    root = tmp_path / "ep"
    init_episode(root=root, seat_id="seat-1", portfolio_ref="port-1", opening_balance="1000")
    req = _unsafe_flat_request(tmp_path / "req.json")

    # Library remains available for tests-only / adapter construction.
    library = freeze_episode(root=root, request_path=req)
    assert library["ok"] is True
    assert library["phase"] == "FROZEN"

    # Re-init for CLI (already frozen above).
    root2 = tmp_path / "ep2"
    init_episode(root=root2, seat_id="seat-1", portfolio_ref="port-1", opening_balance="1000")
    args = shadow_build_parser().parse_args(["freeze", "--root", str(root2), "--request", str(req)])
    with pytest.raises(StoreError, match="FLAT_FREEZE_NOT_PRODUCTION"):
        shadow_dispatch(args)

    # Packaged xinao entry.
    root3 = tmp_path / "ep3"
    init_episode(root=root3, seat_id="seat-1", portfolio_ref="port-1", opening_balance="1000")
    code = xinao_main(["shadow", "freeze", "--root", str(root3), "--request", str(req)])
    assert code == 1
    assert detect_phase(root3).value == "INIT"


def test_flat_freeze_help_not_advertise_production(tmp_path: Path) -> None:
    shadow_help = shadow_build_parser().format_help()
    assert "FLAT_FREEZE_NOT_PRODUCTION" in shadow_help
    assert "freeze-from-disposition" in shadow_help

    freeze_help = subprocess.run(
        [sys.executable, "-m", "xinao.cli", "shadow", "freeze", "--help"],
        cwd=str(ROOT),
        env={
            **dict(**{k: v for k, v in __import__("os").environ.items()}),
            "PYTHONPATH": str(SRC),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert freeze_help.returncode == 0, freeze_help.stderr
    assert "FLAT_FREEZE_NOT_PRODUCTION" in freeze_help.stdout
    assert "freeze-from-disposition" in freeze_help.stdout


def test_historical_inspect_settle_compatible_after_library_freeze(tmp_path: Path) -> None:
    """Sealed historical freezes (library/fixture) still inspect/settle/replay."""

    root = tmp_path / "hist"
    init_episode(root=root, seat_id="seat-h", portfolio_ref="port-h", opening_balance="1000")
    req = _unsafe_flat_request(tmp_path / "hist_req.json", episode_ref="ep.hist.1")
    frozen = freeze_episode(root=root, request_path=req)
    assert frozen["phase"] == "FROZEN"

    status = inspect_episode(root=root)
    assert status["phase"] == "FROZEN"
    assert status["ok"] is True

    outcome = {
        "outcome_ref": "out.hist.1",
        "target_ref": "macaujc2:2026-07-31",
        "actual_special_number": 7,
        "observed_at": (OPEN_AT + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "source_ref": "source.hist.1",
        "verified": True,
    }
    out_path = tmp_path / "outcome.json"
    out_path.write_text(json.dumps(outcome) + "\n", encoding="utf-8")
    settled = settle_episode(root=root, outcome_path=out_path)
    assert settled["ok"] is True
    assert settled["phase"] == "SETTLED"

    # Public freeze still fail-closed on a fresh root (no bypass).
    fresh = tmp_path / "fresh"
    init_episode(root=fresh, seat_id="seat-f", portfolio_ref="port-f", opening_balance="1000")
    with pytest.raises(StoreError, match="FLAT_FREEZE_NOT_PRODUCTION"):
        shadow_dispatch(
            shadow_build_parser().parse_args(
                ["freeze", "--root", str(fresh), "--request", str(req)]
            )
        )


def test_fresh_process_flat_freeze_failclosed(tmp_path: Path) -> None:
    root = tmp_path / "ep"
    init_episode(root=root, seat_id="s", portfolio_ref="p", opening_balance="1000")
    req = _unsafe_flat_request(tmp_path / "r.json")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "xinao.cli",
            "shadow",
            "freeze",
            "--root",
            str(root),
            "--request",
            str(req),
        ],
        cwd=str(ROOT),
        env={
            **dict(**{k: v for k, v in __import__("os").environ.items()}),
            "PYTHONPATH": str(SRC),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert "FLAT_FREEZE_NOT_PRODUCTION" in payload["error"]
    assert payload.get("production_owner_path") is False
