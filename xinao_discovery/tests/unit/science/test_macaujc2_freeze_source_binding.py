"""Mandatory source authority binding on macaujc2 freeze + production freeze gate."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import pytest

from xinao.science.freeze_adapter import FreezeAdapterError, apply_freeze_from_disposition
from xinao.science.owner_disposition import (
    OwnerDispositionError,
    validate_disposition_payload,
)
from xinao.science.prospective_source_thin import (
    CANONICAL_SITE,
    HISTORY_YEAR_TEMPLATE,
    POINT_TEMPLATE,
    capture_prospective_target_authority,
    next_expect_after,
)
from xinao.shadow_lifecycle.consumer import freeze_portfolio_period
from xinao.shadow_lifecycle.store import StoreError, load_frozen, period_directory


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
_sha = _thin._sha
_site_html = _thin._site_html
_seam = _load_sibling("test_candidate_freeze_seam")


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


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


def test_disposition_macaujc2_requires_sab(tmp_path: Path) -> None:
    _, entry, _, _ = _seam._ingest(tmp_path / "pool")
    body = _seam._disposition_body(
        entry,
        selected_number=7,
        target_ref="macaujc2/expect/2026212",
        knowledge_cutoff="2026-07-30T08:00:00Z",
    )
    body["executable_account_decision"] = dict(body["executable_account_decision"])
    body["executable_account_decision"]["target_ref"] = "macaujc2/expect/2026212"
    body["executable_account_decision"]["target_open_time"] = "2026-07-31T13:32:00Z"
    body["executable_account_decision"]["freeze_deadline"] = "2026-07-31T13:30:00Z"
    body["executable_account_decision"]["frozen_at"] = "2026-07-30T10:00:00Z"
    body["executable_account_decision"]["knowledge_cutoff"] = "2026-07-30T08:00:00Z"
    with pytest.raises(OwnerDispositionError, match="SOURCE_AUTHORITY_BINDING_REQUIRED"):
        validate_disposition_payload(body, pool_entry=entry)


def test_disposition_legacy_synthetic_target_without_sab_ok(tmp_path: Path) -> None:
    _, entry, _, _ = _seam._ingest(tmp_path / "pool")
    body = _seam._disposition_body(entry, selected_number=7)
    normalized = validate_disposition_payload(body, pool_entry=entry)
    assert normalized["source_authority_binding"] is None
    assert normalized["target_ref"] == "draw.20260801-001"


def test_direct_production_freeze_without_envelope(tmp_path: Path) -> None:
    root = _seam._init_portfolio(tmp_path)
    forged = {
        "episode_ref": "episode.forged",
        "science_decision": {
            "science_decision_ref": "sci.f",
            "identity": "SCIENCE_CANDIDATE",
            "knowledge_cutoff": _iso(datetime(2026, 7, 30, tzinfo=UTC)),
            "rationale_ref": "r",
            "candidate_ref": "c",
        },
        "account_decision": {"account_decision_ref": "a", "identity": "ACTION"},
        "bound_account_ticket": {
            "ticket_ref": "t",
            "target_ref": "draw.x",
            "target_open_time": _iso(datetime(2026, 8, 1, 8, tzinfo=UTC)),
            "freeze_deadline": _iso(datetime(2026, 8, 1, 7, 50, tzinfo=UTC)),
            "knowledge_cutoff": _iso(datetime(2026, 7, 30, tzinfo=UTC)),
            "frozen_at": _iso(datetime(2026, 8, 1, 7, 40, tzinfo=UTC)),
            "panel": "B",
            "selected_number": 49,
            "stake": "5.0000",
            "rule_ref": "special-number-rule.v1",
            "odds_version_ref": "odds.special-number.20260731.v1",
            "baseline_ref": "BO0013",
            "risk_policy_ref": "shadow-risk.max-one-unit.v1",
            "information_set_ref": "info",
            "information_set_hash": "a" * 64,
        },
        "target_ref": "draw.x",
        "target_open_time": _iso(datetime(2026, 8, 1, 8, tzinfo=UTC)),
        "freeze_deadline": _iso(datetime(2026, 8, 1, 7, 50, tzinfo=UTC)),
        "frozen_at": _iso(datetime(2026, 8, 1, 7, 40, tzinfo=UTC)),
    }
    req = tmp_path / "req.json"
    req.write_text(json.dumps(forged, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(StoreError, match="PRODUCTION_FREEZE_REQUIRES_OWNER_AUTHORITY"):
        freeze_portfolio_period(root=root, request_path=req)
    assert not (period_directory(root, 1) / "frozen_episode.v1.json").exists()


def _macaujc2_action_disposition(
    tmp_path: Path,
    *,
    selected_number: int = 7,
) -> tuple[Path, Path, Path, Path, Path, dict[str, Any], str]:
    capture = _capture_auth(tmp_path)
    sab = capture["source_authority_binding"]
    target_ref = sab["target_ref"]
    pool, entry, _, _ = _seam._ingest(tmp_path / "pool")
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _seam._init_portfolio(tmp_path / "port")
    kc = "2026-07-30T08:00:00Z"
    frozen_at = "2026-07-30T10:00:00Z"
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
    path = _seam._write_disposition(owner, body)
    return pool, owner, path, portfolio, tmp_path / "authority", sab, target_ref


def test_action_freeze_with_sab_binding(tmp_path: Path) -> None:
    pool, owner, path, portfolio, authority, _sab, target_ref = _macaujc2_action_disposition(
        tmp_path
    )
    freeze_now = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    result = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
        authority_root=authority,
        clock=lambda: freeze_now,
    )
    assert result["ok"] is True
    assert result["source_authority_binding"] is not None
    assert result["source_authority_binding"]["target_ref"] == target_ref
    assert result["freeze_action_time"] == _iso(freeze_now)
    assert result["disposition_frozen_at"] == "2026-07-30T10:00:00Z"
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 7
    assert frozen.target_ref == target_ref
    # Host freeze-action time is what the episode/ticket record.
    assert _iso(frozen.frozen_at) == _iso(freeze_now)
    assert _iso(frozen.bound_account_ticket.frozen_at) == _iso(freeze_now)


def test_no_action_freeze_with_sab_binding(tmp_path: Path) -> None:
    capture = _capture_auth(tmp_path)
    sab = capture["source_authority_binding"]
    target_ref = sab["target_ref"]
    pool, entry, _, _ = _seam._ingest(tmp_path / "pool")
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _seam._init_portfolio(tmp_path / "port")

    kc = "2026-07-30T08:00:00Z"
    frozen_at = "2026-07-30T10:00:00Z"
    body = _seam._disposition_body(
        entry,
        account_identity="RESEARCHER_ACCOUNT_NO_ACTION",
        include_executable=False,
        science_disposition="ABSORB_NO_ACTION",
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
    path = _seam._write_disposition(owner, body)

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
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is None
    assert frozen.account_decision.identity.value == "RESEARCHER_ACCOUNT_NO_ACTION"
    assert _iso(frozen.frozen_at) == _iso(freeze_now)


def test_macaujc2_freeze_without_authority_root_rejected(tmp_path: Path) -> None:
    pool, owner, path, portfolio, _, _, _ = _macaujc2_action_disposition(tmp_path)
    with pytest.raises(FreezeAdapterError, match=r"AUTHORITY_ROOT_REQUIRED|SOURCE_AUTHORITY"):
        apply_freeze_from_disposition(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
            clock=lambda: datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
            # missing authority_root
        )


def test_after_deadline_host_freeze_rejected(tmp_path: Path) -> None:
    pool, owner, path, portfolio, authority, _, _ = _macaujc2_action_disposition(tmp_path)
    late = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)
    with pytest.raises(FreezeAdapterError, match="OWNER_FREEZE_AFTER_DEADLINE"):
        apply_freeze_from_disposition(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
            authority_root=authority,
            clock=lambda: late,
        )


def test_backdated_owner_freeze_rejected_when_host_after_deadline(tmp_path: Path) -> None:
    """Pre-deadline disposition + backdated audit stamp cannot pass post-deadline host."""

    pool, owner, path, portfolio, authority, _, _ = _macaujc2_action_disposition(tmp_path)
    host_after = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)
    backdated = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    with pytest.raises(
        FreezeAdapterError,
        match=r"OWNER_FREEZE_AFTER_DEADLINE|OWNER_FREEZE_TIME_HOST_SKEW",
    ):
        apply_freeze_from_disposition(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
            authority_root=authority,
            clock=lambda: host_after,
            owner_freeze_time=backdated,
        )


def test_predeadline_disposition_applied_after_deadline_host_rejected(tmp_path: Path) -> None:
    """Disposition sealed before deadline but freeze host after deadline must fail."""

    pool, owner, path, portfolio, authority, _, _ = _macaujc2_action_disposition(tmp_path)
    with pytest.raises(FreezeAdapterError, match="OWNER_FREEZE_AFTER_DEADLINE"):
        apply_freeze_from_disposition(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
            authority_root=authority,
            clock=lambda: datetime(2026, 7, 31, 13, 30, 1, tzinfo=UTC),
        )


def test_owner_freeze_time_skew_vs_host_rejected(tmp_path: Path) -> None:
    pool, owner, path, portfolio, authority, _, _ = _macaujc2_action_disposition(tmp_path)
    host = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    skewed = datetime(2026, 7, 30, 10, 30, tzinfo=UTC)  # 30m > 5m MAX_HOST_HTTP_SKEW
    with pytest.raises(FreezeAdapterError, match="OWNER_FREEZE_TIME_HOST_SKEW"):
        apply_freeze_from_disposition(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
            authority_root=authority,
            clock=lambda: host,
            owner_freeze_time=skewed,
        )
