"""Opt-in / network-marked live source canary (never always-on; no campaign state)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import pytest

from xinao.science.prospective_live_canary import run_live_source_canary
from xinao.science.prospective_source_thin import (
    CANONICAL_SITE,
    HISTORY_YEAR_TEMPLATE,
    POINT_TEMPLATE,
    ProspectiveSourceError,
    expect_to_local_date,
    next_expect_after,
)


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _contract_bytes() -> bytes:
    return (
        "macaujc2\n"
        "macaujc-source-authority-contract.v1\n"
        "https://macaujc.com/\n"
        f"{HISTORY_YEAR_TEMPLATE}\n"
        f"{POINT_TEMPLATE}\n"
        "新澳门六合彩\n"
        "ACTIVE\n"
    ).encode()


class _Fake:
    def __init__(self, mapping: dict[str, tuple[int, bytes, dict[str, str]]]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def __call__(self, url: str) -> Any:
        from xinao.science.prospective_source_thin import FetchResponse

        self.calls.append(url)
        status, body, headers = self.mapping[url]
        return FetchResponse(
            url=url,
            status=status,
            body=body,
            headers=headers,
            captured_at=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        )


def test_canary_fixture_path_authorized_endpoints_only(tmp_path: Path) -> None:
    import json

    completed = "2026211"
    target = next_expect_after(completed)
    day = expect_to_local_date(completed)
    now = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    hd = {"Date": format_datetime(now, usegmt=True)}
    app = (
        'title:"新澳門六合彩",closeTime:x("21:25:00"),'
        'liveTime:x("21:30:00")+"-"+x("21:38:00"),'
        'historyUrl:"/history/macaujc2/y/"'
    ).encode()
    history = json.dumps(
        {
            "result": True,
            "code": 200,
            "data": [
                {
                    "expect": completed,
                    "openTime": f"{day.isoformat()} 21:34:00",
                    "openCode": "01,02,03,04,05,06,07",
                }
            ],
        }
    ).encode()
    # Live unpublished shape uses code:0 + data:null
    point = b'{"result":true,"code":0,"data":null}\n'
    mapping = {
        CANONICAL_SITE: (
            200,
            b'<script src="/js/app.abc.js"></script>',
            hd,
        ),
        "https://macaujc.com/js/app.abc.js": (200, app, hd),
        HISTORY_YEAR_TEMPLATE.format(year=2026): (200, history, hd),
        POINT_TEMPLATE.format(expect=target): (200, point, hd),
    }
    contract = tmp_path / "c.txt"
    contract.write_bytes(_contract_bytes())
    fetcher = _Fake(mapping)
    result = run_live_source_canary(
        contract_path=contract,
        expected_contract_sha256=_sha(_contract_bytes()),
        fetcher=fetcher,
        clock=lambda: now,
    )
    assert result["ok"] is True
    assert result["daemon"] is False
    assert result["campaign_state_written"] is False
    assert result["latest_used"] is False
    assert result["target_expect"] == target
    assert result["schedule"]["close_time_local"] == "21:25:00"
    assert not any("latest" in u for u in fetcher.calls)
    assert not (tmp_path / "auth").exists()


def test_canary_fails_on_schedule_drift(tmp_path: Path) -> None:
    import json

    completed = "2026211"
    target = next_expect_after(completed)
    day = expect_to_local_date(completed)
    now = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    hd = {"Date": format_datetime(now, usegmt=True)}
    # Drifted: product identity present but no closeTime/liveTime.
    app = "新澳门六合彩 without schedule times".encode()
    history = json.dumps(
        {
            "result": True,
            "code": 200,
            "data": [
                {
                    "expect": completed,
                    "openTime": f"{day.isoformat()} 21:34:00",
                    "openCode": "01,02,03,04,05,06,07",
                }
            ],
        }
    ).encode()
    mapping = {
        CANONICAL_SITE: (200, b'<script src="/js/app.abc.js"></script>', hd),
        "https://macaujc.com/js/app.abc.js": (200, app, hd),
        HISTORY_YEAR_TEMPLATE.format(year=2026): (200, history, hd),
        POINT_TEMPLATE.format(expect=target): (200, b'{"result":true,"code":0,"data":null}', hd),
    }
    contract = tmp_path / "c.txt"
    contract.write_bytes(_contract_bytes())
    with pytest.raises(ProspectiveSourceError, match="PRODUCT_SCHEDULE"):
        run_live_source_canary(
            contract_path=contract,
            expected_contract_sha256=_sha(_contract_bytes()),
            fetcher=_Fake(mapping),
            clock=lambda: now,
        )


@pytest.mark.network
@pytest.mark.skipif(
    os.environ.get("XINAO_LIVE_SOURCE_CANARY", "").strip() not in {"1", "true", "yes"},
    reason="opt-in live network canary; set XINAO_LIVE_SOURCE_CANARY=1",
)
def test_live_network_canary_opt_in(tmp_path: Path) -> None:
    """Real GET against authorized endpoints only; never writes campaign state."""

    # Resolve formal contract if present on D:; otherwise skip with honest reason.
    candidates = [
        Path(
            r"D:\XINAO_RESEARCH_RUNTIME\materials\authority\macaujc-source-authority-contract.v1.txt"
        ),
        Path(r"C:\Users\xx363\Desktop\主线\macaujc-source-authority-contract.v1.txt"),
    ]
    contract = next((p for p in candidates if p.is_file()), None)
    if contract is None:
        pytest.skip("formal AuthorityContract file not found for live canary")
    raw = contract.read_bytes()
    result = run_live_source_canary(
        contract_path=contract,
        expected_contract_sha256=_sha(raw),
    )
    assert result["ok"] is True
    assert result["campaign_state_written"] is False
    assert result["daemon"] is False
    assert result["latest_used"] is False
