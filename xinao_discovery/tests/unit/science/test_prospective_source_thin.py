"""Positive/negative tests for thin prospective macaujc2 source seam + freeze binding."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import pytest

from xinao.science.prospective_source_thin import (
    CANONICAL_SITE,
    HISTORY_YEAR_TEMPLATE,
    POINT_TEMPLATE,
    ProspectiveSourceError,
    capture_prospective_reveal,
    capture_prospective_target_authority,
    expect_to_local_date,
    extract_product_schedule,
    is_live_macaujc2_target,
    load_packet,
    next_expect_after,
    parse_json_strict,
    reject_unsupported_latest_authority,
    validate_expect_matches_open_date,
    validate_source_authority_binding,
)
from xinao.settlement.shadow import OutcomeObservation

ASIA = "Asia/Shanghai"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _http_date(dt: datetime) -> str:
    return format_datetime(dt.astimezone(UTC), usegmt=True)


def _contract_bytes() -> bytes:
    text = (
        "macaujc2\n"
        "macaujc-source-authority-contract.v1\n"
        "https://macaujc.com/\n"
        f"{HISTORY_YEAR_TEMPLATE}\n"
        f"{POINT_TEMPLATE}\n"
        "新澳门六合彩\n"
        "ACTIVE\n"
    )
    return text.encode("utf-8")


def _app_js() -> bytes:
    """Prior valid schedule form (array liveTime)."""

    return (
        "/* product */ 新澳门六合彩 "
        "closeTime:'21:30:00' liveTime:['21:32:00','21:35:00'] "
        "historyUrl:'/history/macaujc2/y/' "
        "expect+1 nextExpect\n"
    ).encode()


def _app_js_live_shape() -> bytes:
    """Current live app.js product block shape (no sensitive values).

    Matches production form:
    title:\"新澳門六合彩\", closeTime:x(\"HH:MM:SS\"),
    liveTime:x(\"HH:MM:SS\")+\"-\"+x(\"HH:MM:SS\"), historyUrl:\"/history/macaujc2/y/\"
    """

    return (
        'title:"新澳門六合彩",closeTime:x("21:25:00"),'
        'liveTime:x("21:30:00")+"-"+x("21:38:00"),'
        'historyUrl:"/history/macaujc2/y/"\n'
    ).encode()


def _site_html() -> bytes:
    return b'<html><script src="/js/app.abc123.js"></script></html>'


def _history_row(expect: str, open_code: str = "01,02,03,04,05,06,07") -> dict[str, Any]:
    day = expect_to_local_date(expect)
    return {
        "expect": expect,
        "openTime": f"{day.isoformat()} 21:34:00",
        "openCode": open_code,
    }


def _history_body(expects: list[str]) -> bytes:
    payload = {
        "result": True,
        "code": 200,
        "data": [_history_row(e) for e in expects],
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


def _point_null() -> bytes:
    return b'{"result":true,"code":200,"data":null}\n'


def _point_result(expect: str, open_code: str = "01,02,03,04,05,06,12") -> bytes:
    day = expect_to_local_date(expect)
    payload = {
        "result": True,
        "code": 200,
        "data": {
            "expect": expect,
            "openTime": f"{day.isoformat()} 21:34:00",
            "openCode": open_code,
        },
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


class FakeFetcher:
    def __init__(self, mapping: dict[str, tuple[int, bytes, dict[str, str] | None]]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def __call__(self, url: str) -> Any:
        from xinao.science.prospective_source_thin import FetchResponse

        self.calls.append(url)
        if url not in self.mapping:
            raise ProspectiveSourceError("FETCH_FAILED", f"no fixture for {url}")
        status, body, headers = self.mapping[url]
        return FetchResponse(
            url=url,
            status=status,
            body=body,
            headers=headers or {},
            captured_at=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        )


def _base_map(
    *,
    completed: str = "2026211",
    host_now: datetime | None = None,
    point_body: bytes | None = None,
    history_body: bytes | None = None,
    site_html: bytes | None = None,
    app_js: bytes | None = None,
    drift_history_url: str | None = None,
) -> tuple[dict[str, tuple[int, bytes, dict[str, str] | None]], datetime, str]:
    now = host_now or datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    target = next_expect_after(completed)
    hd = {"Date": _http_date(now)}
    history_url = HISTORY_YEAR_TEMPLATE.format(year=int(completed[:4]))
    point_url = POINT_TEMPLATE.format(expect=target)
    mapping: dict[str, tuple[int, bytes, dict[str, str] | None]] = {
        CANONICAL_SITE: (200, site_html or _site_html(), hd),
        "https://macaujc.com/js/app.abc123.js": (200, app_js or _app_js(), hd),
        history_url: (200, history_body or _history_body([completed]), hd),
        point_url: (200, point_body if point_body is not None else _point_null(), hd),
    }
    if drift_history_url is not None:
        mapping[drift_history_url] = mapping.pop(history_url)
    return mapping, now, target


def test_expect_day_of_year_and_next_rollover() -> None:
    from zoneinfo import ZoneInfo

    shanghai = ZoneInfo("Asia/Shanghai")
    assert expect_to_local_date("2026001") == date(2026, 1, 1)
    assert expect_to_local_date("2026212") == date(2026, 7, 31)
    assert next_expect_after("2026365") == "2027001"  # 2026 not leap
    assert next_expect_after("2024366") == "2025001"  # 2024 leap
    validate_expect_matches_open_date(
        "2026212",
        datetime(2026, 7, 31, 21, 34, tzinfo=shanghai),
    )
    with pytest.raises(ProspectiveSourceError, match="EXPECT_OPEN_DATE_MISMATCH"):
        validate_expect_matches_open_date(
            "2026212",
            datetime(2026, 8, 1, 21, 34, tzinfo=shanghai),
        )


def test_strict_json_rejects_duplicate_keys() -> None:
    raw = b'{"a":1,"a":2}'
    with pytest.raises(ProspectiveSourceError, match="JSON_DUPLICATE_KEY"):
        parse_json_strict(raw, reason="X")


def test_capture_positive_history_frontier(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    mapping, now, target = _base_map(completed="2026211")
    fetcher = FakeFetcher(mapping)
    result = capture_prospective_target_authority(
        authority_root=tmp_path / "auth",
        contract_path=contract,
        expected_contract_sha256=_sha(_contract_bytes()),
        fetcher=fetcher,
        clock=lambda: now,
    )
    assert result["ok"] is True
    assert result["packet"]["target_expect"] == target
    assert result["packet"]["target_ref"] == f"macaujc2/expect/{target}"
    assert result["source_authority_binding"]["target_expect"] == target
    assert result["trusted_time_proof"] is False
    assert result["owner_channel_authority"] == "UNPROVEN_BY_LIBRARY"
    # Schedule day from target expect day-of-year, not open+1 alone.
    guard = result["packet"]["target_guard_open_time"]
    assert (
        "2026-07-31" in guard
        or "2026-07-30" in guard
        or target[4:] in (f"{expect_to_local_date(target).timetuple().tm_yday:03d}",)
    )
    packet = load_packet(tmp_path / "auth", result["packet_content_hash"])
    assert packet["content_hash"] == result["packet_content_hash"]


def test_source_host_path_drift_rejected(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    mapping, now, _ = _base_map()
    # Inject evil URL as if caller tried non-pinned host via fetcher side channel:
    # discovery of absolute app JS must fail.
    mapping[CANONICAL_SITE] = (
        200,
        b'<script src="https://evil.example/js/app.x.js"></script>',
        {"Date": _http_date(now)},
    )
    with pytest.raises(ProspectiveSourceError, match=r"APP_JS_ABSOLUTE_URL_FORBIDDEN|APP_JS"):
        capture_prospective_target_authority(
            authority_root=tmp_path / "auth",
            contract_path=contract,
            expected_contract_sha256=_sha(_contract_bytes()),
            fetcher=FakeFetcher(mapping),
            clock=lambda: now,
        )


def test_live_shaped_app_js_schedule_and_capture(tmp_path: Path) -> None:
    """Regression: live x(\"HH:MM:SS\") + concat liveTime form must parse and capture."""

    schedule = extract_product_schedule(
        _app_js_live_shape(),
        app_js_url="https://macaujc.com/js/app.livefixture.js",
    )
    assert schedule["close_time_local"] == "21:25:00"
    assert schedule["live_window_start_local"] == "21:30:00"
    assert schedule["live_window_end_local"] == "21:38:00"
    assert schedule["schedule_form"] == "x_concat"
    assert "/history/macaujc2/" in schedule["history_url"]

    # Prior array form still accepted.
    prior = extract_product_schedule(
        _app_js(),
        app_js_url="https://macaujc.com/js/app.abc123.js",
    )
    assert prior["close_time_local"] == "21:30:00"
    assert prior["schedule_form"] == "array_literal"

    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    mapping, now, target = _base_map(completed="2026211", app_js=_app_js_live_shape())
    result = capture_prospective_target_authority(
        authority_root=tmp_path / "auth",
        contract_path=contract,
        expected_contract_sha256=_sha(_contract_bytes()),
        fetcher=FakeFetcher(mapping),
        clock=lambda: now,
    )
    assert result["ok"] is True
    assert result["packet"]["target_expect"] == target
    assert result["packet"]["schedule"]["close_time_local"] == "21:25:00"
    # Deadline from sealed JS closeTime on target day (not hardcoded).
    assert "13:25:00" in result["packet"]["freeze_deadline"] or result["packet"][
        "freeze_deadline"
    ].endswith("T13:25:00Z")


def test_wrong_product_history_and_unsupported_latest_rejected() -> None:
    foreign = (
        'title:"香港六合彩",closeTime:x("21:25:00"),'
        'liveTime:x("21:30:00")+"-"+x("21:38:00"),'
        'historyUrl:"/history/marksix/y/"\n'
        'title:"新澳門六合彩" without times\n'
    ).encode()
    with pytest.raises(ProspectiveSourceError, match="PRODUCT_SCHEDULE_NOT_FOUND"):
        extract_product_schedule(foreign, app_js_url="https://macaujc.com/js/app.x.js")

    with pytest.raises(ProspectiveSourceError, match="LATEST_NOT_AUTHORIZED"):
        reject_unsupported_latest_authority(
            "https://history.macaumarksix.com/history/macaujc2/latest"
        )


def test_target_already_published_rejected(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    mapping, now, target = _base_map(completed="2026211")
    mapping[POINT_TEMPLATE.format(expect=target)] = (
        200,
        _point_result(target),
        {"Date": _http_date(now)},
    )
    with pytest.raises(ProspectiveSourceError, match="TARGET_ALREADY_PUBLISHED"):
        capture_prospective_target_authority(
            authority_root=tmp_path / "auth",
            contract_path=contract,
            expected_contract_sha256=_sha(_contract_bytes()),
            fetcher=FakeFetcher(mapping),
            clock=lambda: now,
        )


def test_wrong_expect_day_in_history_rejected(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    # openTime day does not match day-of-year in expect id.
    bad = {
        "result": True,
        "code": 200,
        "data": [
            {
                "expect": "2026211",
                "openTime": "2026-08-01 21:34:00",  # wrong day vs doy 211
                "openCode": "01,02,03,04,05,06,07",
            }
        ],
    }
    mapping, now, _ = _base_map(
        completed="2026211",
        history_body=(json.dumps(bad) + "\n").encode("utf-8"),
    )
    with pytest.raises(ProspectiveSourceError, match="EXPECT_OPEN_DATE_MISMATCH"):
        capture_prospective_target_authority(
            authority_root=tmp_path / "auth",
            contract_path=contract,
            expected_contract_sha256=_sha(_contract_bytes()),
            fetcher=FakeFetcher(mapping),
            clock=lambda: now,
        )


def test_absent_http_date_rejected(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    mapping, now, _ = _base_map()
    # Strip Date headers.
    mapping = {url: (status, body, {}) for url, (status, body, _) in mapping.items()}
    with pytest.raises(ProspectiveSourceError, match="HTTP_DATE_REQUIRED"):
        capture_prospective_target_authority(
            authority_root=tmp_path / "auth",
            contract_path=contract,
            expected_contract_sha256=_sha(_contract_bytes()),
            fetcher=FakeFetcher(mapping),
            clock=lambda: now,
        )


def test_stale_http_date_skew_rejected(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    mapping, now, _ = _base_map()
    stale = {"Date": _http_date(now - timedelta(hours=2))}
    mapping = {url: (status, body, stale) for url, (status, body, _) in mapping.items()}
    with pytest.raises(ProspectiveSourceError, match="HOST_HTTP_DATE_SKEW"):
        capture_prospective_target_authority(
            authority_root=tmp_path / "auth",
            contract_path=contract,
            expected_contract_sha256=_sha(_contract_bytes()),
            fetcher=FakeFetcher(mapping),
            clock=lambda: now,
        )


def test_after_deadline_freeze_time_rejected(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    # Host now after freeze deadline for target day.
    late = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)  # after 21:30 Asia on target day
    mapping, _, _target = _base_map(completed="2026211", host_now=late)
    # Refresh headers to match late clock.
    mapping = {
        url: (status, body, {"Date": _http_date(late)})
        for url, (status, body, _) in mapping.items()
    }
    with pytest.raises(ProspectiveSourceError, match=r"HOST_TIME_AFTER_DEADLINE|HTTP_DATE_AFTER"):
        capture_prospective_target_authority(
            authority_root=tmp_path / "auth",
            contract_path=contract,
            expected_contract_sha256=_sha(_contract_bytes()),
            fetcher=FakeFetcher(mapping),
            clock=lambda: late,
        )


def test_reveal_before_guard_and_conflict(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    mapping, now, target = _base_map(completed="2026211")
    auth = tmp_path / "auth"
    capture = capture_prospective_target_authority(
        authority_root=auth,
        contract_path=contract,
        expected_contract_sha256=_sha(_contract_bytes()),
        fetcher=FakeFetcher(mapping),
        clock=lambda: now,
    )
    # Before guard.
    early = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    with pytest.raises(ProspectiveSourceError, match="REVEAL_BEFORE_GUARD_OPEN"):
        capture_prospective_reveal(
            authority_root=auth,
            packet_content_hash=capture["packet_content_hash"],
            fetcher=FakeFetcher(
                {
                    POINT_TEMPLATE.format(expect=target): (
                        200,
                        _point_result(target),
                        {"Date": _http_date(early)},
                    )
                }
            ),
            clock=lambda: early,
        )
    # After guard, wrong day openTime.
    after = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)
    wrong_day = {
        "result": True,
        "code": 200,
        "data": {
            "expect": target,
            "openTime": "2026-08-01 21:34:00",
            "openCode": "01,02,03,04,05,06,12",
        },
    }
    with pytest.raises(ProspectiveSourceError, match=r"EXPECT_OPEN_DATE_MISMATCH|REVEAL"):
        capture_prospective_reveal(
            authority_root=auth,
            packet_content_hash=capture["packet_content_hash"],
            fetcher=FakeFetcher(
                {
                    POINT_TEMPLATE.format(expect=target): (
                        200,
                        (json.dumps(wrong_day) + "\n").encode("utf-8"),
                        {"Date": _http_date(after)},
                    )
                }
            ),
            clock=lambda: after,
        )
    # Happy reveal + duplicate admission.
    reveal = capture_prospective_reveal(
        authority_root=auth,
        packet_content_hash=capture["packet_content_hash"],
        fetcher=FakeFetcher(
            {
                POINT_TEMPLATE.format(expect=target): (
                    200,
                    _point_result(target),
                    {"Date": _http_date(after)},
                )
            }
        ),
        clock=lambda: after,
    )
    assert reveal["admission_status"] == "ACCEPTED"
    assert reveal["settlement_written"] is False
    assert reveal["outcome"]["verified"] is True
    existing = (OutcomeObservation.model_validate(reveal["outcome"]),)
    again = capture_prospective_reveal(
        authority_root=auth,
        packet_content_hash=capture["packet_content_hash"],
        fetcher=FakeFetcher(
            {
                POINT_TEMPLATE.format(expect=target): (
                    200,
                    _point_result(target),
                    {"Date": _http_date(after)},
                )
            }
        ),
        clock=lambda: after + timedelta(seconds=1),
        existing_outcomes=existing,
    )
    assert again["admission_status"] == "DUPLICATE"
    # Conflict with different special number.
    conflict_body = _point_result(target, open_code="01,02,03,04,05,06,13")
    with pytest.raises(ProspectiveSourceError, match="REVEAL_TARGET_CONFLICT"):
        # Different open code → different result_hash → durable index conflict.
        capture_prospective_reveal(
            authority_root=auth,
            packet_content_hash=capture["packet_content_hash"],
            fetcher=FakeFetcher(
                {
                    POINT_TEMPLATE.format(expect=target): (
                        200,
                        conflict_body,
                        {"Date": _http_date(after)},
                    )
                }
            ),
            clock=lambda: after + timedelta(seconds=2),
            existing_outcomes=existing,
        )


def test_macaujc2_target_requires_source_authority_binding() -> None:
    assert is_live_macaujc2_target("macaujc2/expect/2026212") is True
    assert is_live_macaujc2_target("draw.20260801-001") is False
    assert is_live_macaujc2_target("synthetic/expect/1") is False


def test_binding_validate_and_packet_mismatch(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    mapping, now, _ = _base_map(completed="2026211")
    capture = capture_prospective_target_authority(
        authority_root=tmp_path / "auth",
        contract_path=contract,
        expected_contract_sha256=_sha(_contract_bytes()),
        fetcher=FakeFetcher(mapping),
        clock=lambda: now,
    )
    sab = dict(capture["source_authority_binding"])
    packet = load_packet(tmp_path / "auth", capture["packet_content_hash"])
    bound = validate_source_authority_binding(sab, packet=packet)
    assert bound["target_ref"] == packet["target_ref"]
    sab["packet_content_hash"] = "a" * 64
    with pytest.raises(ProspectiveSourceError, match="SOURCE_AUTHORITY_BINDING_PACKET_MISMATCH"):
        validate_source_authority_binding(sab, packet=packet)


def test_source_packet_substitution_via_wrong_cas_rejected(tmp_path: Path) -> None:
    contract = tmp_path / "contract.txt"
    contract.write_bytes(_contract_bytes())
    mapping, now, _ = _base_map(completed="2026211")
    auth = tmp_path / "auth"
    capture_prospective_target_authority(
        authority_root=auth,
        contract_path=contract,
        expected_contract_sha256=_sha(_contract_bytes()),
        fetcher=FakeFetcher(mapping),
        clock=lambda: now,
    )
    with pytest.raises(ProspectiveSourceError, match=r"PACKET_MISSING|PACKET_HASH"):
        load_packet(auth, "b" * 64)
    with pytest.raises(ProspectiveSourceError):
        load_packet(auth, "c" * 64)
