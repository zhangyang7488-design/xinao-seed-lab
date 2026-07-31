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
    for cmd in (
        "capture",
        "reveal",
        "write-owner-disposition",
        "freeze-from-disposition",
        "settle-from-reveal",
        "canary",
    ):
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
        elif cmd == "write-owner-disposition":
            args = parser.parse_args(
                [
                    "prospective",
                    "write-owner-disposition",
                    "--owner-state-root",
                    "o",
                    "--pool-root",
                    "p",
                    "--payload",
                    "d.json",
                ]
            )
            assert args.command == "write-owner-disposition"
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
                ]
            )
            assert args.command == "freeze-from-disposition"
            assert not hasattr(args, "owner_freeze_time")
        elif cmd == "settle-from-reveal":
            args = parser.parse_args(
                [
                    "prospective",
                    "settle-from-reveal",
                    "--authority-root",
                    "a",
                    "--portfolio-root",
                    "p",
                    "--packet-content-hash",
                    "0" * 64,
                    "--dry-run",
                ]
            )
            assert args.command == "settle-from-reveal"
            assert not hasattr(args, "actual_special_number")
            assert not hasattr(args, "outcome")
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


def test_portfolio_freeze_cli_always_not_production(tmp_path: Path) -> None:
    parser = shadow_build_parser()
    args = parser.parse_args(
        ["portfolio-freeze", "--root", str(tmp_path), "--request", str(tmp_path / "r.json")]
    )
    with pytest.raises(StoreError, match="PORTFOLIO_FREEZE_CLI_NOT_PRODUCTION"):
        shadow_dispatch(args)


def test_flat_freeze_cli_always_not_production(tmp_path: Path) -> None:
    """Legacy flat freeze is not a second production path (caller frozen_at rejected)."""

    parser = shadow_build_parser()
    args = parser.parse_args(
        ["freeze", "--root", str(tmp_path), "--request", str(tmp_path / "r.json")]
    )
    with pytest.raises(StoreError, match="FLAT_FREEZE_NOT_PRODUCTION"):
        shadow_dispatch(args)

    # Packaged xinao shadow freeze also fails closed (exact old unsafe verb).
    req = tmp_path / "unsafe_req.json"
    req.write_text("{}", encoding="utf-8")
    code = main(["shadow", "freeze", "--root", str(tmp_path / "ep"), "--request", str(req)])
    assert code == 1


def test_removed_public_flags_absent_from_parsers() -> None:
    """Both public CLI overrides removed: owner-freeze-time and allow-nonproduction-fixture-path."""

    main_parser = build_parser()
    main_help = main_parser.format_help()
    assert "--owner-freeze-time" not in main_help
    # Nested freeze-from-disposition help.
    freeze_help = subprocess.run(
        [sys.executable, "-m", "xinao.cli", "prospective", "freeze-from-disposition", "--help"],
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
    assert "--owner-freeze-time" not in freeze_help.stdout

    shadow_parser = shadow_build_parser()
    shadow_help = shadow_parser.format_help()
    assert "--allow-nonproduction-fixture-path" not in shadow_help
    # Unknown flag must not parse.
    with pytest.raises(SystemExit):
        shadow_parser.parse_args(
            [
                "portfolio-freeze",
                "--root",
                "r",
                "--request",
                "q",
                "--allow-nonproduction-fixture-path",
            ]
        )
    with pytest.raises(SystemExit):
        main_parser.parse_args(
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
    assert "write-owner-disposition" in proc.stdout
    assert "freeze-from-disposition" in proc.stdout
    assert "settle-from-reveal" in proc.stdout
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


def test_write_owner_disposition_still_parses_and_dispatches_missing_payload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Wave59 packaging retained: write-owner-disposition still routes and fails closed."""

    code = main(
        [
            "prospective",
            "write-owner-disposition",
            "--owner-state-root",
            str(tmp_path / "owner"),
            "--pool-root",
            str(tmp_path / "pool"),
            "--payload",
            str(tmp_path / "missing_disp.json"),
        ]
    )
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False
    assert err["reason_code"] == "DISPOSITION_PAYLOAD_MISSING"
    assert err["completion_claim_allowed"] is False


def test_nested_owner_pool_roots_rejected_by_wave59_owner_disposition(tmp_path: Path) -> None:
    """Trusted Wave59 owner_disposition rejects true nested owner/pool roots."""

    from xinao.science.owner_disposition import (
        OwnerDispositionError,
        assert_owner_root_separated_from_pool,
    )

    pool = tmp_path / "pool"
    pool.mkdir()
    nested_owner = pool / "owner_nested"
    nested_owner.mkdir()
    with pytest.raises(OwnerDispositionError, match=r"OWNER_ROOT_NESTED_IN_POOL|NESTED"):
        assert_owner_root_separated_from_pool(owner_state_root=nested_owner, pool_root=pool)

    owner = tmp_path / "owner"
    owner.mkdir()
    nested_pool = owner / "pool_nested"
    nested_pool.mkdir()
    with pytest.raises(OwnerDispositionError, match=r"POOL_NESTED_IN_OWNER_ROOT|NESTED"):
        assert_owner_root_separated_from_pool(owner_state_root=owner, pool_root=nested_pool)


def test_settle_from_reveal_parser_rejects_caller_outcome_override() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "prospective",
                "settle-from-reveal",
                "--authority-root",
                "a",
                "--portfolio-root",
                "p",
                "--packet-content-hash",
                "0" * 64,
                "--actual-special-number",
                "12",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "prospective",
                "settle-from-reveal",
                "--authority-root",
                "a",
                "--portfolio-root",
                "p",
                "--packet-content-hash",
                "0" * 64,
                "--outcome",
                "x.json",
            ]
        )
