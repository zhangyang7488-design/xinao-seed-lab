"""Packaged Owner product surface: disposition write + feedback pack emit.

Thin CLI wrappers only. Never claim Owner adoption, live effect, campaign
completion, or scientific proof. Negative authority/hash/CAS/overwrite/no-auto
tests included.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

# Reuse sealed production fixtures from the freeze-seam suite.
from tests.unit.science.test_candidate_freeze_seam import (
    FROZEN_AT,
    OPEN_AT,
    _disposition_body,
    _ingest,
)
from xinao.cli import build_parser, main
from xinao.science.freeze_adapter import (
    apply_freeze_from_disposition,
    build_portfolio_binding_from_shadow,
)
from xinao.science.owner_disposition import (
    OWNER_CHANNEL_AUTHORITY_UNPROVEN,
    disposition_cas_path,
    encode_disposition_bytes,
    raw_sha256,
)
from xinao.science.research_feedback_material import bind_feedback_pack_as_episode_material
from xinao.shadow_lifecycle import (
    FeedbackKind,
    feedback_portfolio_period,
    init_portfolio,
    settle_portfolio_period,
)
from xinao.shadow_lifecycle.store import period_directory

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"


def _write_payload(tmp_path: Path, body: dict[str, Any], name: str = "payload.json") -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _env() -> dict[str, str]:
    return {
        **{k: v for k, v in __import__("os").environ.items()},
        "PYTHONPATH": str(SRC),
    }


def _run_cli(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "xinao.cli", *argv],
        cwd=str(ROOT),
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _attach_portfolio(body: dict[str, Any], portfolio: Path) -> dict[str, Any]:
    body = dict(body)
    body["portfolio_binding"] = build_portfolio_binding_from_shadow(portfolio)
    body["period_index"] = body["portfolio_binding"]["intended_next_period_index"]
    return body


def _write_disp_cli(
    *,
    owner: Path,
    pool: Path,
    payload: Path,
    expected_result: str | None = None,
    expected_entry: str | None = None,
) -> int:
    argv = [
        "prospective",
        "write-owner-disposition",
        "--owner-state-root",
        str(owner),
        "--pool-root",
        str(pool),
        "--payload",
        str(payload),
    ]
    if expected_result is not None:
        argv.extend(["--expected-result-sha256", expected_result])
    if expected_entry is not None:
        argv.extend(["--expected-pool-entry-content-hash", expected_entry])
    return main(argv)


# --- Parser / help -----------------------------------------------------------


def test_packaged_commands_present_in_parser() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "prospective" in help_text
    assert "research-episode" in help_text
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
    args2 = parser.parse_args(
        [
            "research-episode",
            "emit-research-feedback-pack",
            "--portfolio-root",
            "pf",
        ]
    )
    assert args2.command == "emit-research-feedback-pack"


def test_fresh_help_lists_owner_surface_commands() -> None:
    p1 = _run_cli(["prospective", "--help"])
    assert p1.returncode == 0, p1.stderr
    assert "draft-owner-disposition" in p1.stdout
    assert "write-owner-disposition" in p1.stdout
    assert "freeze-from-disposition" in p1.stdout
    p2 = _run_cli(["research-episode", "--help"])
    assert p2.returncode == 0, p2.stderr
    assert "emit-research-feedback-pack" in p2.stdout
    assert "pool-ingest" in p2.stdout
    assert "pool-ingest-result" in p2.stdout
    assert "pool-ingest-oneshot" in p2.stdout
    assert "feedback-bind" in p2.stdout


# --- Positive paths ----------------------------------------------------------


def test_write_owner_disposition_cli_happy_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    payload = _write_payload(tmp_path, _disposition_body(entry))
    code = _write_disp_cli(
        owner=owner,
        pool=pool,
        payload=payload,
        expected_result=entry["result_sha256"],
        expected_entry=entry["content_hash"],
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["status"] == "OWNER_DISPOSITION_WRITTEN"
    assert out["bytes_written"] is True
    assert out["owner_channel_authority"] == OWNER_CHANNEL_AUTHORITY_UNPROVEN
    assert out["owner_disposition_authentic"] is False
    assert out["physical_owner_write_isolation_verified"] is False
    assert out["owner_adopted"] is False
    assert out["freeze_written"] is False
    assert out["settlement_written"] is False
    assert out["auto_freeze"] is False
    assert out["auto_settle"] is False
    assert out["auto_next_period"] is False
    assert out["next_task_created"] is False
    assert out["completion_claim_allowed"] is False
    assert out["parent_complete"] is False
    assert Path(out["disposition_path"]).is_file()
    assert out["owner_artifact_sha256"] in out["disposition_path"]


def test_write_disposition_composes_with_freeze_from_disposition(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = tmp_path / "portfolio"
    init_portfolio(
        root=portfolio,
        seat_id="seat.owner.surface",
        portfolio_ref="portfolio.owner.surface",
    )
    payload = _write_payload(tmp_path, _attach_portfolio(_disposition_body(entry), portfolio))
    write_proc = _run_cli(
        [
            "prospective",
            "write-owner-disposition",
            "--owner-state-root",
            str(owner),
            "--pool-root",
            str(pool),
            "--payload",
            str(payload),
        ]
    )
    assert write_proc.returncode == 0, write_proc.stdout + write_proc.stderr
    written = json.loads(write_proc.stdout)
    freeze = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=Path(written["disposition_path"]),
        shadow_root=portfolio,
        mode="portfolio",
        clock=lambda: FROZEN_AT,
    )
    assert freeze.get("ok", True) is True
    assert freeze.get("frozen_episode_hash")
    assert period_directory(portfolio, 1).is_dir()


def test_emit_feedback_pack_cli_and_feedback_bind_compose(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = tmp_path / "portfolio"
    init_portfolio(
        root=portfolio,
        seat_id="seat.fb.surface",
        portfolio_ref="portfolio.fb.surface",
    )
    payload = _write_payload(tmp_path, _attach_portfolio(_disposition_body(entry), portfolio))
    assert _write_disp_cli(owner=owner, pool=pool, payload=payload) == 0
    written = json.loads(capsys.readouterr().out)
    freeze = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=Path(written["disposition_path"]),
        shadow_root=portfolio,
        mode="portfolio",
        clock=lambda: FROZEN_AT,
    )
    assert freeze.get("ok", True) is True
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(
        json.dumps(
            {
                "outcome_ref": "outcome.owner.surface.p1",
                "source_ref": "synthetic-test-fixture-only",
                "target_ref": "draw.20260801-001",
                "actual_special_number": 1,
                "observed_at": (OPEN_AT + timedelta(hours=1)).isoformat(),
                "verified": True,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    settle_portfolio_period(root=portfolio, outcome_path=outcome_path)
    feedback_portfolio_period(
        root=portfolio,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="CONTINUE_TO_NEXT_PROSPECTIVE_PERIOD",
    )
    code = main(
        [
            "research-episode",
            "emit-research-feedback-pack",
            "--portfolio-root",
            str(portfolio),
            "--period-index",
            "1",
            "--require-account-feedback",
        ]
    )
    assert code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["ok"] is True
    assert emitted["status"] == "RESEARCH_FEEDBACK_PACK_EMITTED"
    assert emitted["scientific_promotion"] is False
    assert emitted["future_outcome_access"] is False
    assert emitted["auto_start_next_research"] is False
    assert emitted["auto_next_period_freeze"] is False
    assert emitted["next_task_created"] is False
    assert emitted["owner_adopted"] is False
    assert emitted["completion_claim_allowed"] is False
    assert Path(emitted["path"]).is_file()
    binding = bind_feedback_pack_as_episode_material(
        portfolio_root=portfolio,
        feedback_content_hash=emitted["content_hash"],
        prior_candidate_result_sha256=entry["result_sha256"],
    )
    assert binding["feedback_content_hash"] == emitted["content_hash"]
    assert not period_directory(portfolio, 2).exists()


# --- Negatives ---------------------------------------------------------------


def test_worker_authored_disposition_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    payload = _write_payload(
        tmp_path,
        _disposition_body(entry, disposition_source="worker"),
        "worker.json",
    )
    code = _write_disp_cli(owner=owner, pool=pool, payload=payload)
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False
    assert "DISPOSITION_SOURCE_NOT_OWNER_CHANNEL" in err["reason_code"]
    assert err["completion_claim_allowed"] is False
    assert err["auto_freeze"] is False


def test_worker_controlled_true_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry)
    body["worker_controlled"] = True
    payload = _write_payload(tmp_path, body, "wc.json")
    code = _write_disp_cli(owner=owner, pool=pool, payload=payload)
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert "DISPOSITION_WORKER_CONTROLLED" in err["reason_code"]


def test_missing_candidate_binding_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry)
    body["result_sha256"] = "0" * 64
    payload = _write_payload(tmp_path, body, "missing.json")
    code = _write_disp_cli(owner=owner, pool=pool, payload=payload)
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False
    assert err["completion_claim_allowed"] is False


def test_mismatched_expected_result_hash_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    payload = _write_payload(tmp_path, _disposition_body(entry))
    code = _write_disp_cli(
        owner=owner,
        pool=pool,
        payload=payload,
        expected_result="f" * 64,
    )
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["reason_code"] == "DISPOSITION_RESULT_HASH_MISMATCH"


def test_mismatched_pool_entry_content_hash_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry)
    body["pool_entry_content_hash"] = "e" * 64
    payload = _write_payload(tmp_path, body, "bad_entry.json")
    code = _write_disp_cli(owner=owner, pool=pool, payload=payload)
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False
    assert "POOL_ENTRY" in err["reason_code"] or "MISMATCH" in err["reason_code"]


def test_stale_cas_conflict_on_disposition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry)
    payload = _write_payload(tmp_path, body)
    assert _write_disp_cli(owner=owner, pool=pool, payload=payload) == 0
    capsys.readouterr()
    raw = encode_disposition_bytes(body)
    digest = raw_sha256(raw)
    cas = disposition_cas_path(owner, digest)
    cas.write_bytes(b'{"poison":true}\n')
    code = _write_disp_cli(owner=owner, pool=pool, payload=payload)
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert "DISPOSITION_CAS_CONTENT_CONFLICT" in err["reason_code"]


def test_emit_unsealed_settlement_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    portfolio = tmp_path / "portfolio"
    init_portfolio(root=portfolio, seat_id="seat.unsealed", portfolio_ref="portfolio.unsealed")
    code = main(
        [
            "research-episode",
            "emit-research-feedback-pack",
            "--portfolio-root",
            str(portfolio),
            "--period-index",
            "1",
        ]
    )
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False
    assert "FEEDBACK_PACK" in err["reason_code"]
    assert err["auto_start_next_research"] is False
    assert err["completion_claim_allowed"] is False


def test_emit_pre_outcome_after_freeze_only_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = tmp_path / "portfolio"
    init_portfolio(root=portfolio, seat_id="seat.pre", portfolio_ref="portfolio.pre")
    payload = _write_payload(tmp_path, _attach_portfolio(_disposition_body(entry), portfolio))
    assert _write_disp_cli(owner=owner, pool=pool, payload=payload) == 0
    written = json.loads(capsys.readouterr().out)
    apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=Path(written["disposition_path"]),
        shadow_root=portfolio,
        mode="portfolio",
        clock=lambda: FROZEN_AT,
    )
    code = main(
        [
            "research-episode",
            "emit-research-feedback-pack",
            "--portfolio-root",
            str(portfolio),
            "--period-index",
            "1",
        ]
    )
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert "FEEDBACK_PACK" in err["reason_code"]
    assert err["auto_start_next_research"] is False


def test_emit_output_overwrite_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = tmp_path / "portfolio"
    init_portfolio(root=portfolio, seat_id="seat.ow", portfolio_ref="portfolio.ow")
    payload = _write_payload(tmp_path, _attach_portfolio(_disposition_body(entry), portfolio))
    assert _write_disp_cli(owner=owner, pool=pool, payload=payload) == 0
    written = json.loads(capsys.readouterr().out)
    apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=Path(written["disposition_path"]),
        shadow_root=portfolio,
        mode="portfolio",
        clock=lambda: FROZEN_AT,
    )
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(
        json.dumps(
            {
                "outcome_ref": "outcome.ow.p1",
                "source_ref": "synthetic-test-fixture-only",
                "target_ref": "draw.20260801-001",
                "actual_special_number": 3,
                "observed_at": (OPEN_AT + timedelta(hours=1)).isoformat(),
                "verified": True,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    settle_portfolio_period(root=portfolio, outcome_path=outcome_path)
    out_path = tmp_path / "custom_pack.json"
    out_path.write_text('{"already":"there"}\n', encoding="utf-8")
    code = main(
        [
            "research-episode",
            "emit-research-feedback-pack",
            "--portfolio-root",
            str(portfolio),
            "--period-index",
            "1",
            "--output",
            str(out_path),
        ]
    )
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert "EXCLUSIVE" in err["reason_code"] or "REJECTED" in err["reason_code"]
    assert err["auto_start_next_research"] is False


def test_no_auto_loop_flags_on_success_and_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "research-episode",
            "emit-research-feedback-pack",
            "--portfolio-root",
            str(tmp_path / "missing"),
        ]
    )
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["auto_start_next_research"] is False
    assert err["auto_next_period_freeze"] is False
    assert err["auto_freeze"] is False
    assert err["auto_settle"] is False
    assert err["next_task_created"] is False
    assert err["daemon"] is False


def test_owner_root_nested_in_pool_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = pool / "nested_owner"
    owner.mkdir()
    payload = _write_payload(tmp_path, _disposition_body(entry))
    code = _write_disp_cli(owner=owner, pool=pool, payload=payload)
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False
    assert err["completion_claim_allowed"] is False


def test_idempotent_same_bytes_disposition_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    payload = _write_payload(tmp_path, _disposition_body(entry))
    assert _write_disp_cli(owner=owner, pool=pool, payload=payload) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["bytes_written"] is True
    assert _write_disp_cli(owner=owner, pool=pool, payload=payload) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["bytes_written"] is False
    assert second["owner_artifact_sha256"] == first["owner_artifact_sha256"]
