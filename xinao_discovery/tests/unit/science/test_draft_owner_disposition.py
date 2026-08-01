"""draft-owner-disposition: mechanical assembly only; Owner judgment still required.

Fail-closed against auto ACTION/NO_ACTION, manifest projection, and bypass of
write-owner-disposition validators. Reuses production load/binding consumers.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import pytest

from xinao.cli import build_parser, main
from xinao.science.owner_disposition import (
    ACCOUNT_ACTION,
    ACCOUNT_NO_ACTION,
    CODEX_OWNER_CHANNEL_SOURCE,
    DRAFT_SOURCE,
    DRAFT_STATUS,
    OWNER_CHANNEL_AUTHORITY_UNPROVEN,
    REQUIRED_OWNER_INPUT,
    OwnerDispositionError,
    draft_owner_disposition,
    validate_disposition_payload,
    write_owner_disposition_artifact,
)
from xinao.science.prospective_source_thin import (
    CANONICAL_SITE,
    HISTORY_YEAR_TEMPLATE,
    POINT_TEMPLATE,
    capture_prospective_target_authority,
    next_expect_after,
)
from xinao.shadow_lifecycle import init_portfolio

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"


def _load_sibling(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_seam = _load_sibling("test_candidate_freeze_seam")
_thin = _load_sibling("test_prospective_source_thin")
FakeFetcher = _thin.FakeFetcher
_app_js = _thin._app_js
_contract_bytes = _thin._contract_bytes
_history_body = _thin._history_body
_point_null = _thin._point_null
_sha = _thin._sha
_site_html = _thin._site_html


def _http_date(dt: datetime) -> str:
    return format_datetime(dt.astimezone(UTC), usegmt=True)


def _capture_auth(tmp_path: Path, completed: str = "2026211") -> dict[str, Any]:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    now = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    target = next_expect_after(completed)
    hd = {"Date": _http_date(now)}
    history_url = HISTORY_YEAR_TEMPLATE.format(year=int(completed[:4]))
    point_url = POINT_TEMPLATE.format(expect=target)
    mapping = {
        CANONICAL_SITE: (200, _site_html(), hd),
        "https://macaujc.com/js/app.abc123.js": (200, _app_js(), hd),
        history_url: (200, _history_body([completed]), hd),
        point_url: (200, _point_null(), hd),
    }
    return capture_prospective_target_authority(
        authority_root=tmp_path / "authority",
        contract_path=contract,
        expected_contract_sha256=_sha(_contract_bytes()),
        fetcher=FakeFetcher(mapping),
        clock=lambda: now,
    )


def _env() -> dict[str, str]:
    import os

    return {**os.environ, "PYTHONPATH": str(SRC)}


def _run_cli(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "xinao.cli", *argv],
        cwd=str(ROOT),
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _owner_fill_action(payload_draft: dict[str, Any], branch: dict[str, Any]) -> dict[str, Any]:
    """Codex-shaped minimal judgment fill for ACTION (tests only)."""

    body = copy.deepcopy(payload_draft)
    body["disposition_source"] = CODEX_OWNER_CHANNEL_SOURCE
    body["owner_role"] = "codex"
    body["worker_controlled"] = False
    body["science_disposition"] = "ADOPT"
    body["account_identity"] = ACCOUNT_ACTION
    body["rationale_ref"] = "owner-filled-from-draft.test"
    exec_dec = dict(branch["executable_account_decision"])
    exec_dec["panel"] = "B"
    exec_dec["selected_number"] = 17
    exec_dec["stake"] = "1.0000"
    exec_dec["baseline_ref"] = "BO0013"
    exec_dec["risk_policy_ref"] = "shadow-risk.max-one-unit.v1"
    exec_dec["odds_version_ref"] = "odds.special-number.20260731.v1"
    exec_dec["frozen_at"] = "2026-07-30T10:00:00Z"
    # Owner confirms cutoff <= frozen_at (pool as_of may be later than freeze action).
    exec_dec["knowledge_cutoff"] = "2026-07-30T08:00:00Z"
    body["knowledge_cutoff"] = exec_dec["knowledge_cutoff"]
    body["executable_account_decision"] = exec_dec
    body.pop("no_action_period_binding", None)
    return body


def _ingest_owner_action_candidate(
    tmp_path: Path,
    capture: dict[str, Any],
) -> tuple[Path, dict[str, Any], bytes, dict[str, Any]]:
    """Seal a synthetic researcher core matching this prospective authority packet."""

    authority = capture["source_authority_binding"]
    return _seam._ingest(
        tmp_path / "pool",
        selected_number=17,
        researcher_executable_overrides={
            "target_ref": authority["target_ref"],
            "target_open_time": authority["target_guard_open_time"],
            "freeze_deadline": authority["freeze_deadline"],
            "knowledge_cutoff": "2026-07-30T08:00:00Z",
        },
    )


def _owner_fill_no_action(payload_draft: dict[str, Any], branch: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(payload_draft)
    body["disposition_source"] = CODEX_OWNER_CHANNEL_SOURCE
    body["owner_role"] = "codex"
    body["worker_controlled"] = False
    body["science_disposition"] = "ABSORB_NO_ACTION"
    body["account_identity"] = ACCOUNT_NO_ACTION
    body["rationale_ref"] = "owner-filled-no-action-from-draft.test"
    na = dict(branch["no_action_period_binding"])
    na["odds_version_ref"] = "odds.special-number.20260731.v1"
    na["frozen_at"] = "2026-07-30T10:00:00Z"
    na["knowledge_cutoff"] = "2026-07-30T08:00:00Z"
    body["knowledge_cutoff"] = na["knowledge_cutoff"]
    body["no_action_period_binding"] = na
    body.pop("executable_account_decision", None)
    return body


# --- Library -----------------------------------------------------------------


def test_draft_assembles_mechanical_fields_deterministically(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    sab = capture["source_authority_binding"]
    pool, entry, _, _ = _seam._ingest(tmp_path / "pool")
    portfolio = tmp_path / "portfolio"
    init_portfolio(
        root=portfolio,
        seat_id="seat.draft.mech",
        portfolio_ref="portfolio.draft.mech",
    )

    first = draft_owner_disposition(
        pool_root=pool,
        result_sha256=entry["result_sha256"],
        authority_root=tmp_path / "authority",
        packet_content_hash=capture["packet_content_hash"],
        portfolio_root=portfolio,
    )
    second = draft_owner_disposition(
        pool_root=pool,
        result_sha256=entry["result_sha256"],
        authority_root=tmp_path / "authority",
        packet_content_hash=capture["packet_content_hash"],
        portfolio_root=portfolio,
    )

    assert first["status"] == DRAFT_STATUS
    assert first["draft_source"] == DRAFT_SOURCE
    assert first["tool_generated"] is True
    assert first["owner_adopted"] is False
    assert first["owner_channel_authority"] == OWNER_CHANNEL_AUTHORITY_UNPROVEN
    assert first["account_identity_selected"] is False
    assert first["science_disposition_selected"] is False
    assert first["selected_number_selected"] is False
    assert first["stake_selected"] is False
    assert first["manifest_recommendation_projected"] is False

    pd = first["payload_draft"]
    assert pd["result_sha256"] == entry["result_sha256"]
    assert pd["receipt_content_sha256"] == entry["receipt_content_sha256"]
    assert pd["pool_entry_content_hash"] == entry["content_hash"]
    assert pd["source_authority_binding"] == sab
    assert pd["portfolio_binding"]["intended_next_period_index"] == 1
    assert pd["period_index"] == 1
    assert pd["target_ref"] == sab["target_ref"]
    assert pd["science_disposition"] == REQUIRED_OWNER_INPUT
    assert pd["account_identity"] == REQUIRED_OWNER_INPUT
    assert pd["disposition_source"] == REQUIRED_OWNER_INPUT
    assert pd["owner_role"] == REQUIRED_OWNER_INPUT
    assert pd["worker_controlled"] == REQUIRED_OWNER_INPUT
    assert "executable_account_decision" not in pd
    assert "no_action_period_binding" not in pd
    assert first["protocol_constants_for_owner"]["disposition_source"] == (
        CODEX_OWNER_CHANNEL_SOURCE
    )

    # Deterministic mechanical payload (exclude operator path metadata).
    assert first["payload_draft"] == second["payload_draft"]
    assert first["branch_templates"] == second["branch_templates"]
    assert first["required_owner_inputs"] == second["required_owner_inputs"]

    # Both branches offered; neither pre-selected.
    assert set(first["branch_templates"]) == {ACCOUNT_ACTION, ACCOUNT_NO_ACTION}
    action_exec = first["branch_templates"][ACCOUNT_ACTION]["executable_account_decision"]
    assert action_exec["selected_number"] == REQUIRED_OWNER_INPUT
    assert action_exec["stake"] == REQUIRED_OWNER_INPUT
    assert action_exec["panel"] == REQUIRED_OWNER_INPUT
    assert action_exec["target_ref"] == sab["target_ref"]
    assert action_exec["target_open_time"] == sab["target_guard_open_time"]
    assert action_exec["freeze_deadline"] == sab["freeze_deadline"]
    na = first["branch_templates"][ACCOUNT_NO_ACTION]["no_action_period_binding"]
    assert na["target_ref"] == sab["target_ref"]
    assert na["frozen_at"] == REQUIRED_OWNER_INPUT


def test_draft_never_projects_manifest_recommendation(tmp_path: Path) -> None:
    """Even if research candidate prose exists, judgment stays REQUIRED_OWNER_INPUT."""

    pool, entry, _, _ = _seam._ingest(tmp_path)
    # Candidate summary historically contains "buy 17" prose; must not leak.
    draft = draft_owner_disposition(pool_root=pool, result_sha256=entry["result_sha256"])
    blob = json.dumps(draft, sort_keys=True)
    assert draft["payload_draft"]["account_identity"] == REQUIRED_OWNER_INPUT
    assert draft["payload_draft"]["science_disposition"] == REQUIRED_OWNER_INPUT
    assert '"selected_number": 17' not in blob
    assert (
        draft["branch_templates"][ACCOUNT_ACTION]["executable_account_decision"]["selected_number"]
        == REQUIRED_OWNER_INPUT
    )


def test_raw_payload_draft_fails_validate_and_write_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _capture_auth(tmp_path)
    pool, entry, _, _ = _seam._ingest(tmp_path / "pool")
    portfolio = tmp_path / "portfolio"
    init_portfolio(root=portfolio, seat_id="seat.fail", portfolio_ref="portfolio.fail")
    draft = draft_owner_disposition(
        pool_root=pool,
        result_sha256=entry["result_sha256"],
        authority_root=tmp_path / "authority",
        packet_content_hash=capture["packet_content_hash"],
        portfolio_root=portfolio,
    )
    payload = draft["payload_draft"]
    with pytest.raises(OwnerDispositionError) as exc_info:
        validate_disposition_payload(payload, pool_entry=entry)
    assert exc_info.value.reason_code in {
        "DISPOSITION_SOURCE_NOT_OWNER_CHANNEL",
        "PERIOD_ACCOUNT_IDENTITY_REQUIRED",
        "SCIENCE_DISPOSITION_INVALID",
    }

    owner = tmp_path / "owner"
    owner.mkdir()
    payload_path = tmp_path / "raw_draft_payload.json"
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    code = main(
        [
            "prospective",
            "write-owner-disposition",
            "--owner-state-root",
            str(owner),
            "--pool-root",
            str(pool),
            "--payload",
            str(payload_path),
        ]
    )
    assert code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["completion_claim_allowed"] is False
    assert out["parent_complete"] is False
    # Fail closed before/without successful owner CAS claim.
    assert out.get("status") != "OWNER_DISPOSITION_WRITTEN"
    assert out["reason_code"] == "DISPOSITION_SOURCE_NOT_OWNER_CHANNEL"
    assert not any(owner.rglob("*.json"))


def test_owner_filled_action_and_no_action_both_validate(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    pool, entry, _, _ = _seam._ingest(tmp_path / "pool")
    portfolio = tmp_path / "portfolio"
    init_portfolio(root=portfolio, seat_id="seat.fill", portfolio_ref="portfolio.fill")
    draft = draft_owner_disposition(
        pool_root=pool,
        result_sha256=entry["result_sha256"],
        authority_root=tmp_path / "authority",
        packet_content_hash=capture["packet_content_hash"],
        portfolio_root=portfolio,
    )
    action_body = _owner_fill_action(
        draft["payload_draft"],
        draft["branch_templates"][ACCOUNT_ACTION],
    )
    normalized_action = validate_disposition_payload(action_body, pool_entry=entry)
    assert normalized_action["account_identity"] == ACCOUNT_ACTION
    assert normalized_action["executable_account_decision"]["selected_number"] == 17

    no_action_body = _owner_fill_no_action(
        draft["payload_draft"],
        draft["branch_templates"][ACCOUNT_NO_ACTION],
    )
    normalized_na = validate_disposition_payload(no_action_body, pool_entry=entry)
    assert normalized_na["account_identity"] == ACCOUNT_NO_ACTION
    assert normalized_na["executable_account_decision"] is None

    # Neither path was auto-chosen by draft itself.
    assert draft["payload_draft"]["account_identity"] == REQUIRED_OWNER_INPUT


def test_owner_filled_write_owner_disposition_accepts(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    pool, entry, _, _ = _ingest_owner_action_candidate(tmp_path, capture)
    portfolio = tmp_path / "portfolio"
    init_portfolio(root=portfolio, seat_id="seat.write", portfolio_ref="portfolio.write")
    draft = draft_owner_disposition(
        pool_root=pool,
        result_sha256=entry["result_sha256"],
        authority_root=tmp_path / "authority",
        packet_content_hash=capture["packet_content_hash"],
        portfolio_root=portfolio,
    )
    body = _owner_fill_action(
        draft["payload_draft"],
        draft["branch_templates"][ACCOUNT_ACTION],
    )
    owner = tmp_path / "owner"
    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=body,
        pool_root=pool,
    )
    assert written["bytes_written"] is True
    from xinao.science.owner_disposition import load_and_verify_disposition

    verified = load_and_verify_disposition(
        disposition_path=Path(written["disposition_path"]),
        owner_state_root=owner,
        pool_root=pool,
    )
    assert verified["disposition"]["result_sha256"] == entry["result_sha256"]
    assert verified["owner_disposition_authentic"] is False
    assert verified["owner_channel_authority"] == OWNER_CHANNEL_AUTHORITY_UNPROVEN


def test_wrong_pool_entry_rejected(tmp_path: Path) -> None:
    pool, _entry, _, _ = _seam._ingest(tmp_path)
    with pytest.raises(OwnerDispositionError, match="POOL_ENTRY_MISSING"):
        draft_owner_disposition(pool_root=pool, result_sha256="0" * 64)


def test_wrong_authority_packet_rejected(tmp_path: Path) -> None:
    pool, entry, _, _ = _seam._ingest(tmp_path / "pool")
    _capture_auth(tmp_path)
    with pytest.raises(OwnerDispositionError) as exc_info:
        draft_owner_disposition(
            pool_root=pool,
            result_sha256=entry["result_sha256"],
            authority_root=tmp_path / "authority",
            packet_content_hash="f" * 64,
        )
    assert exc_info.value.reason_code in {
        "PACKET_MISSING",
        "PACKET_HASH_MISMATCH",
        "PACKET_PATH_MISMATCH",
    }


def test_authority_args_must_pair(tmp_path: Path) -> None:
    pool, entry, _, _ = _seam._ingest(tmp_path)
    with pytest.raises(OwnerDispositionError, match="DRAFT_AUTHORITY_ARGS_INCOMPLETE"):
        draft_owner_disposition(
            pool_root=pool,
            result_sha256=entry["result_sha256"],
            authority_root=tmp_path / "authority",
        )
    with pytest.raises(OwnerDispositionError, match="DRAFT_AUTHORITY_ARGS_INCOMPLETE"):
        draft_owner_disposition(
            pool_root=pool,
            result_sha256=entry["result_sha256"],
            packet_content_hash="a" * 64,
        )


def test_portfolio_head_not_ready_rejected(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    pool, entry, _, _ = _ingest_owner_action_candidate(tmp_path, capture)
    portfolio = tmp_path / "portfolio"
    init_portfolio(root=portfolio, seat_id="seat.bad", portfolio_ref="portfolio.bad")
    # Force a non-ready head by freezing period 1 then trying draft without feedback.
    from xinao.science.freeze_adapter import apply_freeze_from_disposition
    from xinao.science.owner_disposition import write_owner_disposition_artifact as write_disp

    draft = draft_owner_disposition(
        pool_root=pool,
        result_sha256=entry["result_sha256"],
        authority_root=tmp_path / "authority",
        packet_content_hash=capture["packet_content_hash"],
        portfolio_root=portfolio,
    )
    body = _owner_fill_action(
        draft["payload_draft"],
        draft["branch_templates"][ACCOUNT_ACTION],
    )
    owner = tmp_path / "owner"
    written = write_disp(owner_state_root=owner, payload=body, pool_root=pool)
    apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=Path(written["disposition_path"]),
        shadow_root=portfolio,
        mode="portfolio",
        authority_root=tmp_path / "authority",
        clock=lambda: datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
    )
    # Head is now FROZEN — cannot freeze next; draft portfolio binding must fail.
    with pytest.raises(OwnerDispositionError, match="FREEZE_PORTFOLIO_HEAD_NOT_READY"):
        draft_owner_disposition(
            pool_root=pool,
            result_sha256=entry["result_sha256"],
            portfolio_root=portfolio,
        )


def test_draft_does_not_write_owner_cas_or_pool(tmp_path: Path) -> None:
    pool, entry, _, _ = _seam._ingest(tmp_path / "pool")
    owner = tmp_path / "owner"
    owner.mkdir()
    before_pool = {p.relative_to(pool) for p in pool.rglob("*") if p.is_file()}
    draft_owner_disposition(pool_root=pool, result_sha256=entry["result_sha256"])
    after_pool = {p.relative_to(pool) for p in pool.rglob("*") if p.is_file()}
    assert before_pool == after_pool
    assert not any(owner.rglob("*"))


# --- CLI ---------------------------------------------------------------------


def test_parser_lists_draft_owner_disposition() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "prospective",
            "draft-owner-disposition",
            "--pool-root",
            "p",
            "--result-sha256",
            "a" * 64,
        ]
    )
    assert args.command == "draft-owner-disposition"
    help_proc = _run_cli(["prospective", "--help"])
    assert help_proc.returncode == 0, help_proc.stderr
    assert "draft-owner-disposition" in help_proc.stdout
    assert "write-owner-disposition" in help_proc.stdout


def test_cli_draft_stdout_and_optional_output(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    pool, entry, _, _ = _seam._ingest(tmp_path / "pool")
    portfolio = tmp_path / "portfolio"
    init_portfolio(root=portfolio, seat_id="seat.cli", portfolio_ref="portfolio.cli")
    out_path = tmp_path / "candidate" / "draft.json"
    proc = _run_cli(
        [
            "prospective",
            "draft-owner-disposition",
            "--pool-root",
            str(pool),
            "--result-sha256",
            entry["result_sha256"],
            "--authority-root",
            str(tmp_path / "authority"),
            "--packet-content-hash",
            capture["packet_content_hash"],
            "--portfolio-root",
            str(portfolio),
            "--output",
            str(out_path),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out["status"] == DRAFT_STATUS
    assert out["draft_source"] == DRAFT_SOURCE
    assert out["owner_adopted"] is False
    assert out["output_authoritative"] is False
    assert out["output_is_owner_cas"] is False
    assert out_path.is_file()
    disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert disk["status"] == DRAFT_STATUS
    assert disk["payload_draft"]["pool_entry_content_hash"] == entry["content_hash"]
    # No owner CAS objects minted.
    assert not (tmp_path / "owner").exists()


def test_cli_fresh_process_fail_closed_on_missing_pool(tmp_path: Path) -> None:
    proc = _run_cli(
        [
            "prospective",
            "draft-owner-disposition",
            "--pool-root",
            str(tmp_path / "empty_pool"),
            "--result-sha256",
            "a" * 64,
        ]
    )
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["ok"] is False
    assert out["completion_claim_allowed"] is False
    assert out["auto_freeze"] is False
    assert out["daemon"] is False


def test_cli_raw_draft_then_owner_fill_roundtrip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _capture_auth(tmp_path)
    pool, entry, _, _ = _ingest_owner_action_candidate(tmp_path, capture)
    portfolio = tmp_path / "portfolio"
    init_portfolio(root=portfolio, seat_id="seat.rt", portfolio_ref="portfolio.rt")
    code = main(
        [
            "prospective",
            "draft-owner-disposition",
            "--pool-root",
            str(pool),
            "--result-sha256",
            entry["result_sha256"],
            "--authority-root",
            str(tmp_path / "authority"),
            "--packet-content-hash",
            capture["packet_content_hash"],
            "--portfolio-root",
            str(portfolio),
        ]
    )
    assert code == 0
    draft = json.loads(capsys.readouterr().out)
    filled = _owner_fill_action(
        draft["payload_draft"],
        draft["branch_templates"][ACCOUNT_ACTION],
    )
    payload_path = tmp_path / "filled.json"
    payload_path.write_text(
        json.dumps(filled, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    owner = tmp_path / "owner"
    owner.mkdir()
    code2 = main(
        [
            "prospective",
            "write-owner-disposition",
            "--owner-state-root",
            str(owner),
            "--pool-root",
            str(pool),
            "--payload",
            str(payload_path),
        ]
    )
    assert code2 == 0
    written = json.loads(capsys.readouterr().out)
    assert written["ok"] is True
    assert written["status"] == "OWNER_DISPOSITION_WRITTEN"
    assert written["owner_adopted"] is False
    assert written["freeze_written"] is False
