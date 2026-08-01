"""Wave64: sealed prospective reveal → mechanical portfolio settle-from-reveal."""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import pytest

from xinao.cli import build_parser, main
from xinao.science.freeze_adapter import apply_freeze_from_disposition
from xinao.science.prospective_source_thin import (
    CANONICAL_SITE,
    HISTORY_YEAR_TEMPLATE,
    POINT_TEMPLATE,
    SOURCE_ID,
    capture_prospective_reveal,
    capture_prospective_target_authority,
    load_reveal,
    next_expect_after,
    reveal_content_hash,
    reveal_object_path,
)
from xinao.science.settle_from_reveal_adapter import (
    ADAPTER_MARKER,
    SettleFromRevealError,
    apply_settle_from_reveal,
    assert_no_control_plane_imports,
    outcome_from_sealed_reveal,
)
from xinao.settlement.shadow import OutcomeObservation
from xinao.shadow_lifecycle.store import (
    PortfolioPeriodPhase,
    derive_portfolio_head,
    load_frozen,
    load_outcome,
    load_settled,
    period_directory,
)


def _load_sibling(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_thin = _load_sibling("test_prospective_source_thin")
FakeFetcher = _thin.FakeFetcher
_app_js = _thin._app_js
_contract_bytes = _thin._contract_bytes
_history_body = _thin._history_body
_point_null = _thin._point_null
_point_result = _thin._point_result
_sha = _thin._sha
_site_html = _thin._site_html
_seam = _load_sibling("test_candidate_freeze_seam")


def _http_date(dt: datetime) -> str:
    return format_datetime(dt.astimezone(UTC), usegmt=True)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


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


def _reveal(
    tmp_path: Path,
    capture: dict[str, Any],
    *,
    open_code: str = "01,02,03,04,05,06,12",
    after: datetime | None = None,
) -> dict[str, Any]:
    target = capture["packet"]["target_expect"]
    when = after or datetime(2026, 7, 31, 14, 0, tzinfo=UTC)
    return capture_prospective_reveal(
        authority_root=tmp_path / "authority",
        packet_content_hash=capture["packet_content_hash"],
        fetcher=FakeFetcher(
            {
                POINT_TEMPLATE.format(expect=target): (
                    200,
                    _point_result(target, open_code=open_code),
                    {"Date": _http_date(when)},
                )
            }
        ),
        clock=lambda: when,
    )


def _action_freeze(
    tmp_path: Path,
    capture: dict[str, Any],
    *,
    selected_number: int = 12,
) -> tuple[Path, Path, dict[str, Any]]:
    sab = capture["source_authority_binding"]
    target_ref = sab["target_ref"]
    kc = "2026-07-30T08:00:00Z"
    frozen_at = "2026-07-30T10:00:00Z"
    pool, entry, _, _ = _seam._ingest(
        tmp_path / "pool",
        selected_number=selected_number,
        researcher_executable_overrides={
            "target_ref": target_ref,
            "target_open_time": sab["target_guard_open_time"],
            "freeze_deadline": sab["freeze_deadline"],
            "knowledge_cutoff": kc,
        },
    )
    owner = tmp_path / "owner"
    owner.mkdir(exist_ok=True)
    portfolio = _seam._init_portfolio(tmp_path / "port")
    body = _seam._disposition_body(
        entry,
        selected_number=selected_number,
        target_ref=target_ref,
        source_authority_binding=sab,
        knowledge_cutoff=kc,
    )
    body["executable_account_decision"] = dict(body["executable_account_decision"])
    body["executable_account_decision"]["target_ref"] = target_ref
    body["executable_account_decision"]["target_open_time"] = sab["target_guard_open_time"]
    body["executable_account_decision"]["freeze_deadline"] = sab["freeze_deadline"]
    body["executable_account_decision"]["frozen_at"] = frozen_at
    body["executable_account_decision"]["knowledge_cutoff"] = kc
    body = _seam._attach_portfolio_binding(body, portfolio)
    path = _seam._write_disposition(owner, pool, body)
    freeze_now = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    result = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
        authority_root=tmp_path / "authority",
        clock=lambda: freeze_now,
    )
    assert result["ok"] is True
    return portfolio, tmp_path / "authority", result


def _no_action_freeze(
    tmp_path: Path,
    capture: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    sab = capture["source_authority_binding"]
    target_ref = sab["target_ref"]
    kc = "2026-07-30T08:00:00Z"
    pool, entry, _, _ = _seam._ingest(
        tmp_path / "pool",
        decision_kind="NO_ACTION",
        researcher_executable_overrides={
            "target_ref": target_ref,
            "target_open_time": sab["target_guard_open_time"],
            "freeze_deadline": sab["freeze_deadline"],
            "knowledge_cutoff": kc,
        },
    )
    owner = tmp_path / "owner"
    owner.mkdir(exist_ok=True)
    portfolio = _seam._init_portfolio(tmp_path / "port")
    frozen_at = "2026-07-30T10:00:00Z"
    body = _seam._disposition_body(
        entry,
        account_identity="RESEARCHER_ACCOUNT_NO_ACTION",
        include_executable=False,
        science_disposition="ADOPT",
        target_ref=target_ref,
        source_authority_binding=sab,
        knowledge_cutoff=kc,
    )
    body["no_action_period_binding"] = dict(body["no_action_period_binding"])
    body["no_action_period_binding"]["target_ref"] = target_ref
    body["no_action_period_binding"]["target_open_time"] = sab["target_guard_open_time"]
    body["no_action_period_binding"]["freeze_deadline"] = sab["freeze_deadline"]
    body["no_action_period_binding"]["frozen_at"] = frozen_at
    body["no_action_period_binding"]["knowledge_cutoff"] = kc
    body = _seam._attach_portfolio_binding(body, portfolio)
    path = _seam._write_disposition(owner, pool, body)
    freeze_now = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    result = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
        authority_root=tmp_path / "authority",
        clock=lambda: freeze_now,
    )
    assert result["ok"] is True
    return portfolio, tmp_path / "authority", result


def test_action_positive_capture_freeze_reveal_settle(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, freeze = _action_freeze(tmp_path, capture, selected_number=12)
    frozen_path = period_directory(portfolio, 1) / "frozen_episode.v1.json"
    frozen_before = frozen_path.read_bytes()
    frozen_hash = load_frozen(period_directory(portfolio, 1)).content_hash

    reveal = _reveal(tmp_path, capture, open_code="01,02,03,04,05,06,12")
    assert reveal["admission_status"] == "ACCEPTED"
    assert reveal["settlement_written"] is False
    special = int(reveal["outcome"]["actual_special_number"])
    assert special == 12

    settled = apply_settle_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=reveal["reveal_content_hash"],
        expected_frozen_episode_hash=freeze["frozen_episode_hash"],
        period_index=1,
    )
    assert settled["ok"] is True
    assert settled["adapter_marker"] == ADAPTER_MARKER
    assert settled["settlement_written"] is True
    assert settled["actual_special_number"] == special
    assert settled["outcome_result_hash"] == reveal["outcome"]["result_hash"]
    assert settled["account_identity"] == "ACTION"
    assert settled["statement_result"] is not None
    assert settled["pnl"] is not None
    assert settled["completion_claim_allowed"] is False
    assert settled["auto_feedback"] is False
    assert settled["auto_next_period"] is False
    assert settled["auto_next_research"] is False
    assert settled["feedback_written"] is False
    assert settled["next_period_frozen"] is False
    assert settled["research_started"] is False
    assert settled["daemon"] is False
    assert settled["loop"] is False
    assert settled["caller_outcome_override_accepted"] is False
    assert settled["odds_invented_after_reveal"] is False

    # Settlement number equals sealed reveal; frozen bytes unchanged.
    outcome = load_outcome(period_directory(portfolio, 1))
    assert outcome.result_hash == reveal["outcome"]["result_hash"]
    assert outcome.actual_special_number == special
    assert outcome.source_ref == SOURCE_ID
    assert frozen_path.read_bytes() == frozen_before
    assert load_frozen(period_directory(portfolio, 1)).content_hash == frozen_hash

    head = derive_portfolio_head(portfolio)
    assert head.phase == PortfolioPeriodPhase.SETTLED


def test_no_action_positive_settle_from_reveal(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, freeze = _no_action_freeze(tmp_path, capture)
    reveal = _reveal(tmp_path, capture)
    settled = apply_settle_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        expected_frozen_episode_hash=freeze["frozen_episode_hash"],
    )
    assert settled["ok"] is True
    assert settled["account_identity"] == "RESEARCHER_ACCOUNT_NO_ACTION"
    assert settled["statement_result"] == "NO_EXPOSURE"
    assert settled["pnl"] in {"0", "0.0000", 0, "0.0"} or str(settled["pnl"]).startswith("0")
    sealed = load_settled(period_directory(portfolio, 1))
    assert sealed.settlement_bundle is None
    assert sealed.outcome.result_hash == reveal["outcome"]["result_hash"]
    assert settled["auto_feedback"] is False
    assert settled["completion_claim_allowed"] is False


def test_settle_uses_reveal_number_no_caller_override(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, _ = _action_freeze(tmp_path, capture, selected_number=7)
    reveal = _reveal(tmp_path, capture, open_code="01,02,03,04,05,06,12")
    # Caller cannot pass outcome fields.
    with pytest.raises(SettleFromRevealError, match="CALLER_OUTCOME_OVERRIDE_FORBIDDEN"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            actual_special_number=99,  # type: ignore[call-arg]
        )
    with pytest.raises(SettleFromRevealError, match="CALLER_OUTCOME_OVERRIDE_FORBIDDEN"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            outcome={"actual_special_number": 1},  # type: ignore[call-arg]
        )
    # Signature itself has no outcome override parameters.
    sig = inspect.signature(apply_settle_from_reveal)
    for forbidden in (
        "outcome",
        "actual_special_number",
        "source_ref",
        "observed_at",
        "result_hash",
    ):
        assert forbidden not in sig.parameters

    settled = apply_settle_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=reveal["reveal_content_hash"],
    )
    assert settled["actual_special_number"] == 12
    assert settled["actual_special_number"] == reveal["outcome"]["actual_special_number"]
    assert settled["outcome_result_hash"] == reveal["outcome"]["result_hash"]
    assert load_outcome(period_directory(portfolio, 1)).actual_special_number == 12


def test_reveal_missing_and_mismatches(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, freeze = _action_freeze(tmp_path, capture)

    # No reveal yet.
    with pytest.raises(SettleFromRevealError, match="REVEAL_MISSING"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
        )

    reveal = _reveal(tmp_path, capture)

    # Wrong packet pin.
    with pytest.raises(SettleFromRevealError, match=r"PACKET_MISSING|PACKET_HASH"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash="0" * 64,
        )

    # Reveal hash pin mismatch.
    with pytest.raises(SettleFromRevealError, match="REVEAL_HASH_MISMATCH"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash="a" * 64,
        )

    # Frozen head hash mismatch (stale).
    with pytest.raises(SettleFromRevealError, match="FROZEN_HEAD_MISMATCH"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=reveal["reveal_content_hash"],
            expected_frozen_episode_hash="b" * 64,
        )

    # Period mismatch.
    with pytest.raises(SettleFromRevealError, match="PERIOD_INDEX_MISMATCH"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            period_index=99,
        )

    # Tampered reveal bytes.
    rpath = reveal_object_path(authority, reveal["reveal_content_hash"])
    raw = json.loads(rpath.read_text(encoding="utf-8"))
    raw["actual_special_number"] = 49
    # Keep content_hash so path still loads, but recompute fails → tampered.
    rpath.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(SettleFromRevealError, match="REVEAL_BYTES_TAMPERED"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=reveal["reveal_content_hash"],
            expected_frozen_episode_hash=freeze["frozen_episode_hash"],
        )


def test_quarantined_and_conflicting_reveal_rejected(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, _ = _action_freeze(tmp_path, capture)
    reveal = _reveal(tmp_path, capture)
    rpath = reveal_object_path(authority, reveal["reveal_content_hash"])
    body = json.loads(rpath.read_text(encoding="utf-8"))

    # Quarantined: verified false + re-seal under new hash path via outcome helper.
    body_q = dict(body)
    body_q["admission_status"] = "QUARANTINED"
    outcome = dict(body_q["outcome"])
    outcome["verified"] = False
    # Drop result_hash so with_hash can reseal after model_validate path in helper.
    outcome.pop("result_hash", None)
    body_q["outcome"] = outcome
    body_q.pop("content_hash", None)
    # outcome_from_sealed_reveal rejects quarantine before settle.
    with pytest.raises(SettleFromRevealError, match="REVEAL_NOT_ACCEPTED"):
        outcome_from_sealed_reveal(body_q)

    body_c = dict(body)
    body_c["admission_status"] = "CONFLICT"
    with pytest.raises(SettleFromRevealError, match="REVEAL_NOT_ACCEPTED"):
        outcome_from_sealed_reveal(body_c)

    # Index-level conflict status must fail closed.
    idx = authority / "index" / "reveal" / f"{capture['packet']['target_expect']}.json"
    idx_payload = json.loads(idx.read_text(encoding="utf-8"))
    idx_payload["admission_status"] = "CONFLICT"
    idx.write_text(json.dumps(idx_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(SettleFromRevealError, match="REVEAL_NOT_ACCEPTED"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
        )


def test_target_source_authority_mismatch(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, _ = _action_freeze(tmp_path, capture)
    reveal = _reveal(tmp_path, capture)

    # Wrong portfolio (unfrozen / different head).
    other = _seam._init_portfolio(tmp_path / "other", portfolio_ref="portfolio.other")
    with pytest.raises(SettleFromRevealError, match="PORTFOLIO_HEAD_NOT_FROZEN"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=other,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=reveal["reveal_content_hash"],
        )

    # Capture a second authority packet/target and attempt settle with wrong packet.
    b_root = tmp_path / "b"
    b_root.mkdir()
    capture_b = _capture_auth(b_root, completed="2026212")
    with pytest.raises(
        SettleFromRevealError,
        match=r"REVEAL_MISSING|AUTHORITY_HEAD_MISMATCH|REVEAL_PACKET|PACKET",
    ):
        apply_settle_from_reveal(
            authority_root=b_root / "authority",
            portfolio_root=portfolio,
            packet_content_hash=capture_b["packet_content_hash"],
        )


def test_duplicate_settle_exact_and_conflicting(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, freeze = _action_freeze(tmp_path, capture, selected_number=12)
    reveal = _reveal(tmp_path, capture, open_code="01,02,03,04,05,06,12")
    first = apply_settle_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=reveal["reveal_content_hash"],
        expected_frozen_episode_hash=freeze["frozen_episode_hash"],
    )
    assert first["ok"] is True
    settled_hash = first["settled_episode_hash"]

    # Duplicate settle fails closed (already settled head).
    with pytest.raises(SettleFromRevealError, match=r"ALREADY_SETTLED|PORTFOLIO_HEAD_NOT_FROZEN"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=reveal["reveal_content_hash"],
        )

    # Settled artifact stable; no second write.
    assert load_settled(period_directory(portfolio, 1)).content_hash == settled_hash


def test_pre_open_observation_rejected(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, freeze = _action_freeze(tmp_path, capture)
    reveal = _reveal(tmp_path, capture)
    # Build a pre-open outcome mechanically from sealed shape but earlier observed_at.
    outcome = OutcomeObservation.model_validate(reveal["outcome"])
    early = freeze and load_frozen(period_directory(portfolio, 1)).target_open_time - timedelta(
        hours=2
    )
    pre_open = outcome.model_copy(update={"observed_at": early, "result_hash": None}).with_hash()
    fake_reveal = dict(load_reveal(authority, reveal["reveal_content_hash"]))
    fake_reveal["outcome"] = pre_open.model_dump(mode="json")
    fake_reveal.pop("content_hash", None)
    # outcome_from_sealed_reveal still accepts (admission ACCEPTED); consumer rejects pre-open.
    derived = outcome_from_sealed_reveal(fake_reveal)
    assert derived.observed_at < load_frozen(period_directory(portfolio, 1)).target_open_time

    # Write derived outcome path and call settle consumer through adapter path by
    # planting a reveal with early observed_at under a new content hash + index.
    from xinao.canonical import canonical_sha256
    from xinao.science.prospective_source_thin import reveal_index_path

    body = dict(fake_reveal)
    body["admission_status"] = "ACCEPTED"
    digest = canonical_sha256(body)
    body["content_hash"] = digest
    rpath = reveal_object_path(authority, digest)
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    idx = reveal_index_path(authority, capture["packet"]["target_expect"])
    idx.write_text(
        json.dumps(
            {
                "target_expect": capture["packet"]["target_expect"],
                "reveal_content_hash": digest,
                "outcome_ref": pre_open.outcome_ref,
                "result_hash": pre_open.result_hash,
                "admission_status": "ACCEPTED",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SettleFromRevealError, match=r"PRE_OPEN_OBSERVATION|SETTLE_CONSUMER"):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
            reveal_content_hash=digest,
        )


def test_no_auto_loop_feedback_or_next_freeze_invoked(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, _ = _action_freeze(tmp_path, capture, selected_number=12)
    _reveal(tmp_path, capture, open_code="01,02,03,04,05,06,12")
    source = Path(
        inspect.getsourcefile(apply_settle_from_reveal)  # type: ignore[arg-type]
        or ""
    )
    assert source.is_file()
    text = source.read_text(encoding="utf-8")
    # Adapter source must not call feedback / next freeze / research / capture loops.
    assert "feedback_portfolio_period" not in text
    assert "apply_freeze_from_disposition" not in text
    assert "capture_prospective_target_authority" not in text
    assert "capture_prospective_reveal" not in text
    assert "emit_research_feedback_pack" not in text
    assert "ingest_verified_research_result" not in text
    assert "while True" not in text
    # No scheduler/daemon control plane; product reuses settle_portfolio_period only.
    assert "APScheduler" not in text
    assert "schedule.every" not in text
    assert "BackgroundScheduler" not in text
    assert text.count("settle_portfolio_period") >= 1
    assert "settle_portfolio_period" in text
    assert_no_control_plane_imports()

    settled = apply_settle_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
    )
    for key in (
        "auto_feedback",
        "auto_next_period",
        "auto_next_research",
        "auto_freeze",
        "auto_capture",
        "auto_reveal",
        "feedback_written",
        "next_period_frozen",
        "research_started",
        "daemon",
        "temporal",
        "poll",
        "loop",
    ):
        assert settled[key] is False, key
    # Head remains SETTLED — no auto feedback advance.
    assert derive_portfolio_head(portfolio).phase == PortfolioPeriodPhase.SETTLED
    # No period-2 freeze created.
    assert (
        not period_directory(portfolio, 2).exists()
        or not (period_directory(portfolio, 2) / "frozen_episode.v1.json").exists()
    )


def test_replay_hash_stability(tmp_path: Path) -> None:
    from xinao.shadow_lifecycle.consumer import replay_portfolio_period

    capture = _capture_auth(tmp_path)
    portfolio, authority, freeze = _action_freeze(tmp_path, capture, selected_number=12)
    frozen_path = period_directory(portfolio, 1) / "frozen_episode.v1.json"
    frozen_before = frozen_path.read_bytes()
    reveal = _reveal(tmp_path, capture, open_code="01,02,03,04,05,06,12")
    settled = apply_settle_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=reveal["reveal_content_hash"],
        expected_frozen_episode_hash=freeze["frozen_episode_hash"],
    )
    assert frozen_path.read_bytes() == frozen_before
    # Replay is stable and does not mutate frozen.
    replay = replay_portfolio_period(root=portfolio, period_index=1)
    assert replay.get("ok", True) is True or "settled_episode_hash" in replay or "phase" in replay
    assert frozen_path.read_bytes() == frozen_before
    settled_reload = load_settled(period_directory(portfolio, 1))
    assert settled_reload.content_hash == settled["settled_episode_hash"]
    # Second settle-from-reveal still fails closed.
    with pytest.raises(SettleFromRevealError):
        apply_settle_from_reveal(
            authority_root=authority,
            portfolio_root=portfolio,
            packet_content_hash=capture["packet_content_hash"],
        )


def test_cli_settle_from_reveal_packaged_and_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
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
    # Nested subcommand help lists settle-from-reveal; top-level may not expand all.
    settle_help = parser.parse_args(
        [
            "prospective",
            "settle-from-reveal",
            "--authority-root",
            "a",
            "--portfolio-root",
            "p",
            "--packet-content-hash",
            "0" * 64,
        ]
    )
    assert settle_help.command == "settle-from-reveal"
    assert not hasattr(settle_help, "actual_special_number")
    assert not hasattr(settle_help, "outcome")
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

    code = main(
        [
            "prospective",
            "settle-from-reveal",
            "--authority-root",
            str(tmp_path / "auth"),
            "--portfolio-root",
            str(tmp_path / "port"),
            "--packet-content-hash",
            "c" * 64,
            "--dry-run",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["settlement_written"] is False
    assert out["caller_outcome_override_accepted"] is False
    assert out["completion_claim_allowed"] is False


def test_cli_end_to_end_settle_from_reveal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _capture_auth(tmp_path)
    portfolio, authority, freeze = _action_freeze(tmp_path, capture, selected_number=12)
    reveal = _reveal(tmp_path, capture, open_code="01,02,03,04,05,06,12")
    code = main(
        [
            "prospective",
            "settle-from-reveal",
            "--authority-root",
            str(authority),
            "--portfolio-root",
            str(portfolio),
            "--packet-content-hash",
            capture["packet_content_hash"],
            "--reveal-content-hash",
            reveal["reveal_content_hash"],
            "--expected-frozen-episode-hash",
            freeze["frozen_episode_hash"],
            "--period-index",
            "1",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["settlement_written"] is True
    assert out["actual_special_number"] == 12
    assert out["outcome_result_hash"] == reveal["outcome"]["result_hash"]
    assert out["auto_feedback"] is False
    assert out["completion_claim_allowed"] is False


def test_adapter_ast_no_control_plane() -> None:
    assert_no_control_plane_imports()
    path = Path(__file__).resolve().parents[3] / "src/xinao/science/settle_from_reveal_adapter.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "temporalio" not in imported
    assert "temporal" not in imported


def test_reveal_content_hash_helper_stable(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    reveal = _reveal(tmp_path, capture)
    body = load_reveal(tmp_path / "authority", reveal["reveal_content_hash"])
    assert reveal_content_hash(body) == reveal["reveal_content_hash"]
    assert body["content_hash"] == reveal["reveal_content_hash"]


def test_no_production_module_accepts_caller_outcome_or_second_ledger() -> None:
    """Product route: no caller outcome overrides; single settle consumer, no second ledger."""

    adapter_path = (
        Path(__file__).resolve().parents[3] / "src/xinao/science/settle_from_reveal_adapter.py"
    )
    cli_path = Path(__file__).resolve().parents[3] / "src/xinao/science/prospective_cli.py"
    adapter_text = adapter_path.read_text(encoding="utf-8")
    cli_text = cli_path.read_text(encoding="utf-8")
    assert "settle_portfolio_period" in adapter_text
    # No alternate settlement path or second ledger import surface.
    for forbidden in (
        "settle_episode_period",
        "second_ledger",
        "LedgerV2",
        "parallel_ledger",
        "import settle_ledger",
    ):
        assert forbidden not in adapter_text, forbidden
        assert forbidden not in cli_text, forbidden
    sig = inspect.signature(apply_settle_from_reveal)
    for forbidden_param in (
        "outcome",
        "actual_special_number",
        "source_ref",
        "observed_at",
        "result_hash",
        "open_code",
        "odds",
        "stake",
    ):
        assert forbidden_param not in sig.parameters
