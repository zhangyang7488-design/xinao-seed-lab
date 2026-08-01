"""Production portfolio freeze -> independently verified outcome -> settle-all."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import xinao.science.portfolio_settle_all_from_reveal as settle_all_consumer
from xinao.cli import build_parser, main
from xinao.science.portfolio_settle_all_from_reveal import (
    PortfolioSettleAllError,
    apply_portfolio_settle_all_from_reveal,
    load_verified_outcome_event,
)
from xinao.science.prospective_source_thin import (
    POINT_TEMPLATE,
    SOURCE_ID,
    raw_object_path,
    reveal_content_hash,
    reveal_object_path,
)
from xinao.settlement.shadow import OutcomeObservation
from xinao.shadow_lifecycle.store import (
    PortfolioPeriodPhase,
    artifact_paths,
    derive_portfolio_head,
    load_outcome,
    period_directory,
)


def _load_sibling(name: str) -> Any:
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_legacy = _load_sibling("test_settle_from_reveal")
_source = _load_sibling("test_prospective_source_thin")


def _ready(tmp_path: Path) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    capture = _legacy._capture_auth(tmp_path)
    portfolio, authority, frozen = _legacy._action_freeze(tmp_path, capture)
    reveal = _legacy._reveal(tmp_path, capture)
    return capture, portfolio, authority, {"freeze": frozen, "reveal": reveal}


def _write_reveal(
    authority: Path,
    reveal: dict[str, Any],
    *,
    update_index: bool = True,
) -> str:
    body = dict(reveal)
    body.pop("content_hash", None)
    digest = reveal_content_hash(body)
    body["content_hash"] = digest
    path = reveal_object_path(authority, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if update_index:
        index = authority / "index" / "reveal" / f"{body['target_expect']}.json"
        index.write_text(
            json.dumps(
                {
                    "target_expect": body["target_expect"],
                    "reveal_content_hash": digest,
                    "outcome_ref": body["outcome"]["outcome_ref"],
                    "result_hash": body["outcome"]["result_hash"],
                    "admission_status": body["admission_status"],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return digest


def _correction_reveal(
    *,
    capture: dict[str, Any],
    authority: Path,
    prior: dict[str, Any],
    corrected_special: int,
    with_supersession: bool,
) -> tuple[dict[str, Any], str]:
    expect = capture["packet"]["target_expect"]
    raw = _source._point_result(expect, open_code=f"01,02,03,04,05,06,{corrected_special:02d}")
    raw_sha = hashlib.sha256(raw).hexdigest()
    raw_path = raw_object_path(authority, raw_sha)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    observed = datetime(2026, 7, 31, 14, 5, tzinfo=UTC)
    outcome_ref = f"outcome.macaujc2.expect.{expect}.sha256:{raw_sha[:16]}"
    outcome = OutcomeObservation(
        outcome_ref=outcome_ref,
        source_ref=SOURCE_ID,
        target_ref=capture["packet"]["target_ref"],
        actual_special_number=corrected_special,
        observed_at=observed,
        verified=True,
        supersedes_outcome_ref=(
            prior["reveal"]["outcome"]["outcome_ref"] if with_supersession else None
        ),
    ).with_hash()
    body: dict[str, Any] = {
        "schema_version": "xinao.prospective_reveal_correction.v1",
        "target_ref": capture["packet"]["target_ref"],
        "target_expect": expect,
        "packet_content_hash": capture["packet_content_hash"],
        "contract_sha256": capture["packet"]["contract"]["contract_sha256"],
        "source_id": SOURCE_ID,
        "raw": {
            "role": "point_reveal_correction",
            "url": POINT_TEMPLATE.format(expect=expect),
            "http_status": 200,
            "http_date": "Fri, 31 Jul 2026 14:05:00 GMT",
            "captured_at": "2026-07-31T14:05:00Z",
            "byte_length": len(raw),
            "sha256": raw_sha,
            "content_addressed_path": str(raw_path),
        },
        "open_code": [1, 2, 3, 4, 5, 6, corrected_special],
        "actual_special_number": corrected_special,
        "outcome": outcome.model_dump(mode="json"),
        "admission_status": "CORRECTION_ACCEPTED",
        "conflicting_outcome_refs": [],
        "completion_claim_allowed": False,
        "real_money_authorized": False,
        "settlement_written": False,
    }
    if with_supersession:
        body["supersedes_reveal_content_hash"] = prior["reveal"]["reveal_content_hash"]
    digest = _write_reveal(authority, body)
    return body, digest


def test_verified_boolean_without_source_raw_proof_is_rejected(tmp_path: Path) -> None:
    capture, portfolio, authority, refs = _ready(tmp_path)
    reveal = dict(refs["reveal"]["reveal"])
    reveal["raw"] = dict(reveal["raw"])
    reveal["raw"]["sha256"] = "f" * 64
    reveal["raw"]["content_addressed_path"] = str(tmp_path / "invented.bin")
    forged_hash = _write_reveal(authority, reveal)

    with pytest.raises(PortfolioSettleAllError, match="OUTCOME_RAW_CAS_MISSING"):
        apply_portfolio_settle_all_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=forged_hash,
        )
    period = period_directory(portfolio, 1)
    assert not artifact_paths(period)["intent"].exists()
    assert not artifact_paths(period)["outcome"].exists()
    assert not artifact_paths(period)["settled"].exists()


def test_reveal_index_cannot_relabel_sealed_admission_status(tmp_path: Path) -> None:
    capture, portfolio, authority, refs = _ready(tmp_path)
    expect = capture["packet"]["target_expect"]
    index_path = authority / "index" / "reveal" / f"{expect}.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["admission_status"] = "CONFLICT"
    index_path.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PortfolioSettleAllError, match="OUTCOME_REVEAL_INDEX_MISMATCH"):
        apply_portfolio_settle_all_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=refs["reveal"]["reveal_content_hash"],
        )
    period = period_directory(portfolio, 1)
    assert not artifact_paths(period)["intent"].exists()
    assert not artifact_paths(period)["outcome"].exists()
    assert not artifact_paths(period)["settled"].exists()


def test_settle_all_enumerates_formal_store_and_replay_is_idempotent(tmp_path: Path) -> None:
    capture, portfolio, authority, refs = _ready(tmp_path)
    result = apply_portfolio_settle_all_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=refs["reveal"]["reveal_content_hash"],
    )
    assert result["status"] == "SETTLE_ALL_COMMITTED"
    assert result["enumerated_due_count"] == 1
    assert result["settled_count"] == 1
    assert result["unsettled_due_count"] == 0
    assert result["settle_coverage"] == "1.0000"
    assert result["caller_verified_flag_trusted"] is False
    assert result["source_raw_reparsed"] is True
    assert result["source_execution_classification"] == "UNATTESTED_BY_LIBRARY"
    assert result["prospective_source_attested"] is False
    assert result["synthetic"] is None
    assert result["receipt_recovered"] is False
    assert derive_portfolio_head(portfolio).phase == PortfolioPeriodPhase.SETTLED

    period = period_directory(portfolio, 1)
    files_before = {
        path.relative_to(portfolio).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in portfolio.rglob("*")
        if path.is_file()
    }
    replay = apply_portfolio_settle_all_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=refs["reveal"]["reveal_content_hash"],
    )
    files_after = {
        path.relative_to(portfolio).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in portfolio.rglob("*")
        if path.is_file()
    }
    assert replay["status"] == "SETTLE_ALL_IDEMPOTENT"
    assert replay["settled_count"] == 0
    assert replay["already_settled_count"] == 1
    assert replay["receipt_recovered"] is False
    assert replay["receipt_content_hash"] == result["receipt_content_hash"]
    assert files_after == files_before
    assert load_outcome(period).result_hash == refs["reveal"]["outcome"]["result_hash"]


def test_missing_receipt_is_recovered_once_from_sealed_post_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, portfolio, authority, refs = _ready(tmp_path)
    original_write_receipt = settle_all_consumer._write_receipt

    def crash_receipt(**_kwargs: Any) -> dict[str, str]:
        raise OSError("simulated receipt crash")

    monkeypatch.setattr(settle_all_consumer, "_write_receipt", crash_receipt)
    with pytest.raises(
        PortfolioSettleAllError,
        match="SETTLE_ALL_EVIDENCE_RECOVERY_REQUIRED",
    ):
        apply_portfolio_settle_all_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=refs["reveal"]["reveal_content_hash"],
        )
    assert derive_portfolio_head(portfolio).phase == PortfolioPeriodPhase.SETTLED
    receipt_root = portfolio / "objects" / "portfolio_settle_all_receipt"
    assert not receipt_root.exists()

    monkeypatch.setattr(settle_all_consumer, "_write_receipt", original_write_receipt)
    recovered = apply_portfolio_settle_all_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=refs["reveal"]["reveal_content_hash"],
    )
    assert recovered["status"] == "SETTLE_ALL_IDEMPOTENT"
    assert recovered["receipt_recovered"] is True
    receipt_path = Path(recovered["receipt_path"])
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["inventory_basis"] == "post_state_recovery"
    assert receipt["recovered_after_formal_commit"] is True
    assert receipt["prospective_source_attested"] is False
    assert receipt["synthetic"] is None

    files_before = {
        path.relative_to(portfolio).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in portfolio.rglob("*")
        if path.is_file()
    }
    replay = apply_portfolio_settle_all_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=refs["reveal"]["reveal_content_hash"],
    )
    files_after = {
        path.relative_to(portfolio).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in portfolio.rglob("*")
        if path.is_file()
    }
    assert replay["receipt_recovered"] is False
    assert replay["receipt_content_hash"] == recovered["receipt_content_hash"]
    assert files_after == files_before


def test_foreign_second_due_period_fails_before_any_formal_commit(tmp_path: Path) -> None:
    capture, portfolio, authority, refs = _ready(tmp_path)
    period1 = period_directory(portfolio, 1)
    period2 = period_directory(portfolio, 2)
    period2.mkdir(parents=True)
    for name in ("seat.v1.json", "frozen_episode.v1.json"):
        (period2 / name).write_bytes((period1 / name).read_bytes())

    with pytest.raises(PortfolioSettleAllError, match="PORTFOLIO_STORE_INVALID"):
        apply_portfolio_settle_all_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=refs["reveal"]["reveal_content_hash"],
        )
    assert not artifact_paths(period1)["intent"].exists()
    assert not artifact_paths(period1)["outcome"].exists()
    assert not artifact_paths(period1)["settled"].exists()


def test_correction_requires_explicit_supersession_and_is_bound(tmp_path: Path) -> None:
    capture, portfolio, authority, refs = _ready(tmp_path)
    body, correction_hash = _correction_reveal(
        capture=capture,
        authority=authority,
        prior=refs,
        corrected_special=13,
        with_supersession=True,
    )
    with pytest.raises(
        PortfolioSettleAllError,
        match=("OUTCOME_CORRECTION_REQUIRES_REGISTERED_APPEND_ONLY_SOURCE_AND_ACCOUNT_ADJUSTMENT"),
    ):
        load_verified_outcome_event(
            authority_root=authority,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=correction_hash,
        )

    bad = dict(body)
    bad.pop("supersedes_reveal_content_hash")
    bad["outcome"] = dict(bad["outcome"])
    bad["outcome"]["supersedes_outcome_ref"] = None
    bad_hash = _write_reveal(authority, bad)
    with pytest.raises(PortfolioSettleAllError, match="OUTCOME_CORRECTION_SUPERSESSION_REQUIRED"):
        load_verified_outcome_event(
            authority_root=authority,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=bad_hash,
        )
    assert derive_portfolio_head(portfolio).phase == PortfolioPeriodPhase.FROZEN


def test_correction_after_settlement_never_rewrites_formal_history(tmp_path: Path) -> None:
    capture, portfolio, authority, refs = _ready(tmp_path)
    apply_portfolio_settle_all_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=refs["reveal"]["reveal_content_hash"],
    )
    period = period_directory(portfolio, 1)
    before = {name: artifact_paths(period)[name].read_bytes() for name in ("outcome", "settled")}
    _, correction_hash = _correction_reveal(
        capture=capture,
        authority=authority,
        prior=refs,
        corrected_special=13,
        with_supersession=True,
    )
    with pytest.raises(
        PortfolioSettleAllError,
        match=("OUTCOME_CORRECTION_REQUIRES_REGISTERED_APPEND_ONLY_SOURCE_AND_ACCOUNT_ADJUSTMENT"),
    ):
        apply_portfolio_settle_all_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=correction_hash,
        )
    assert artifact_paths(period)["outcome"].read_bytes() == before["outcome"]
    assert artifact_paths(period)["settled"].read_bytes() == before["settled"]


def test_public_cli_has_no_ticket_subset_or_outcome_override(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "prospective",
            "portfolio-settle-all-from-reveal",
            "--authority-root",
            str(tmp_path / "authority"),
            "--portfolio-root",
            str(tmp_path / "portfolio"),
            "--packet-content-hash",
            "a" * 64,
            "--reveal-content-hash",
            "b" * 64,
            "--dry-run",
        ]
    )
    assert args.command == "portfolio-settle-all-from-reveal"
    for forbidden in ("--ticket", "--ticket-subset", "--outcome", "--verified"):
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "prospective",
                    "portfolio-settle-all-from-reveal",
                    "--authority-root",
                    str(tmp_path / "authority"),
                    "--portfolio-root",
                    str(tmp_path / "portfolio"),
                    "--packet-content-hash",
                    "a" * 64,
                    forbidden,
                    "x",
                ]
            )
    assert (
        main(
            [
                "prospective",
                "portfolio-settle-all-from-reveal",
                "--authority-root",
                str(tmp_path / "authority"),
                "--portfolio-root",
                str(tmp_path / "portfolio"),
                "--packet-content-hash",
                "a" * 64,
                "--dry-run",
            ]
        )
        == 0
    )


def test_public_cli_replays_production_freeze_schema_with_synthetic_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capture, portfolio, authority, refs = _ready(tmp_path)
    argv = [
        "prospective",
        "portfolio-settle-all-from-reveal",
        "--authority-root",
        str(authority),
        "--portfolio-root",
        str(portfolio),
        "--packet-content-hash",
        capture["packet_content_hash"],
        "--reveal-content-hash",
        refs["reveal"]["reveal_content_hash"],
    ]
    assert main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "SETTLE_ALL_COMMITTED"
    assert first["formal_object_model"] == "production_FrozenShadowEpisode"
    assert first["settle_coverage"] == "1.0000"
    assert first["source_raw_reparsed"] is True
    assert first["caller_verified_flag_trusted"] is False
    assert first["source_execution_classification"] == "UNATTESTED_BY_LIBRARY"
    assert first["prospective_source_attested"] is False
    assert first["synthetic"] is None

    assert main(argv) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "SETTLE_ALL_IDEMPOTENT"
    assert second["already_settled_count"] == 1
