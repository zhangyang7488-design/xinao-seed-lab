"""Owner prospective CLI packaging + negative misuse tests (fresh-process style)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from xinao.cli import build_parser, main
from xinao.science.prospective_source_thin import ProspectiveSourceError
from xinao.shadow_lifecycle.consumer import build_parser as shadow_build_parser
from xinao.shadow_lifecycle.consumer import dispatch as shadow_dispatch
from xinao.shadow_lifecycle.store import StoreError

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"


def test_prospective_commands_packaged_in_xinao_parser() -> None:
    parser = build_parser()
    # Help includes prospective owner commands.
    help_text = parser.format_help()
    assert "prospective" in help_text
    # Subcommands exist.
    for cmd in ("capture", "reveal", "freeze-from-disposition", "canary"):
        # Nested parse succeeds to the command level when dry-run args present.
        if cmd == "capture":
            args = parser.parse_args(
                [
                    "prospective",
                    "capture",
                    "--authority-root",
                    "a",
                    "--contract",
                    "c",
                    "--expected-contract-sha256",
                    "0" * 64,
                    "--dry-run",
                ]
            )
            assert args.group == "prospective"
            assert args.command == "capture"
        elif cmd == "reveal":
            args = parser.parse_args(
                [
                    "prospective",
                    "reveal",
                    "--authority-root",
                    "a",
                    "--packet-content-hash",
                    "0" * 64,
                    "--dry-run",
                ]
            )
            assert args.command == "reveal"
        elif cmd == "freeze-from-disposition":
            args = parser.parse_args(
                [
                    "prospective",
                    "freeze-from-disposition",
                    "--pool-root",
                    "p",
                    "--owner-state-root",
                    "o",
                    "--disposition",
                    "d",
                    "--portfolio-root",
                    "s",
                    "--authority-root",
                    "a",
                    "--owner-freeze-time",
                    "2026-07-31T12:00:00Z",
                ]
            )
            assert args.command == "freeze-from-disposition"
        elif cmd == "canary":
            args = parser.parse_args(
                [
                    "prospective",
                    "canary",
                    "--contract",
                    "c",
                    "--expected-contract-sha256",
                    "0" * 64,
                    "--i-accept-network-canary",
                ]
            )
            assert args.command == "canary"


def test_capture_dry_run_and_missing_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "prospective",
            "capture",
            "--authority-root",
            str(tmp_path / "auth"),
            "--contract",
            str(tmp_path / "missing.txt"),
            "--expected-contract-sha256",
            "a" * 64,
            "--dry-run",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["latest_used"] is False
    assert out["auto_freeze"] is False

    code = main(
        [
            "prospective",
            "capture",
            "--authority-root",
            str(tmp_path / "auth"),
            "--contract",
            str(tmp_path / "missing.txt"),
            "--expected-contract-sha256",
            "a" * 64,
        ]
    )
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False
    assert "CONTRACT" in err["reason_code"]


def test_portfolio_freeze_cli_not_production_without_flag(tmp_path: Path) -> None:
    parser = shadow_build_parser()
    args = parser.parse_args(
        ["portfolio-freeze", "--root", str(tmp_path), "--request", str(tmp_path / "r.json")]
    )
    with pytest.raises(StoreError, match="PORTFOLIO_FREEZE_CLI_NOT_PRODUCTION"):
        shadow_dispatch(args)


def test_portfolio_freeze_cli_still_requires_owner_envelope(tmp_path: Path) -> None:
    """Even with non-production flag, no owner_authority => production gate reject."""

    from xinao.shadow_lifecycle.consumer import init_portfolio

    init_portfolio(root=tmp_path, seat_id="seat-1", portfolio_ref="pf-1", opening_balance="1000")
    req = tmp_path / "req.json"
    req.write_text("{}", encoding="utf-8")
    parser = shadow_build_parser()
    args = parser.parse_args(
        [
            "portfolio-freeze",
            "--root",
            str(tmp_path),
            "--request",
            str(req),
            "--allow-nonproduction-fixture-path",
        ]
    )
    with pytest.raises(StoreError, match="PRODUCTION_FREEZE_REQUIRES_OWNER_AUTHORITY"):
        shadow_dispatch(args)


def test_fresh_process_cli_help_lists_prospective() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "xinao.cli", "prospective", "--help"],
        cwd=str(ROOT),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "capture" in proc.stdout
    assert "freeze-from-disposition" in proc.stdout
    assert "canary" in proc.stdout


def test_fresh_process_capture_dry_run() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "xinao.cli",
            "prospective",
            "capture",
            "--authority-root",
            "tmp-auth",
            "--contract",
            "tmp-contract",
            "--expected-contract-sha256",
            "0" * 64,
            "--dry-run",
        ],
        cwd=str(ROOT),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["dry_run"] is True
    assert payload["writes"] is False


def test_project_scripts_entry_documents_xinao() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'xinao = "xinao.cli:main"' in text
    # prospective is a subcommand of packaged xinao entry, not a missing second script.
    assert "xinao.cli:main" in text


def test_foreign_authority_path_load_rejected(tmp_path: Path) -> None:
    from xinao.science.prospective_source_thin import load_packet

    with pytest.raises(ProspectiveSourceError, match=r"PACKET_MISSING|PACKET_HASH"):
        load_packet(tmp_path / "foreign", "f" * 64)
