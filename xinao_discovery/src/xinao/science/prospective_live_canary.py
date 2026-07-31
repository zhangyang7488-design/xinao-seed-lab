"""Opt-in live source canary (authorized endpoints only; no campaign state).

Kept separate from the thin capture seam so schedule/CAS strictness stays focused.
Not a daemon. Requires explicit CLI opt-in or pytest network mark.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xinao.science.prospective_source_thin import (
    ASIA_SHANGHAI,
    CANONICAL_SITE,
    HISTORY_YEAR_TEMPLATE,
    POINT_TEMPLATE,
    SOURCE_ID,
    Clock,
    Fetcher,
    ProspectiveSourceError,
    default_clock,
    default_fetcher,
    discover_same_origin_app_js,
    extract_product_schedule,
    next_expect_after,
    parse_history_max_expect,
    parse_point_payload,
    point_is_null,
    reject_unsupported_latest_authority,
    verify_macaujc2_contract_bytes,
)


def run_live_source_canary(
    *,
    contract_path: Path,
    expected_contract_sha256: str,
    fetcher: Fetcher | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Opt-in network canary over authorized site/history/point only."""

    fetch = fetcher or default_fetcher
    now_fn = clock or default_clock
    contract_path = contract_path.expanduser().resolve()
    if not contract_path.is_file():
        raise ProspectiveSourceError("CONTRACT_FILE_MISSING", str(contract_path))
    contract = verify_macaujc2_contract_bytes(
        contract_path.read_bytes(),
        expected_sha256=expected_contract_sha256.lower(),
    )
    host_now = now_fn()
    if host_now.tzinfo is None or host_now.utcoffset() is None:
        raise ProspectiveSourceError("HOST_TIME_NOT_AWARE", "clock must be aware")

    site_resp = fetch(CANONICAL_SITE)
    if site_resp.status != 200:
        raise ProspectiveSourceError("HTTP_STATUS_NOT_OK", f"site_html status={site_resp.status}")
    app_js_url = discover_same_origin_app_js(site_resp.body, canonical_site=CANONICAL_SITE)
    reject_unsupported_latest_authority(app_js_url)
    app_resp = fetch(app_js_url)
    if app_resp.status != 200:
        raise ProspectiveSourceError("HTTP_STATUS_NOT_OK", f"app_js status={app_resp.status}")
    schedule = extract_product_schedule(app_resp.body, app_js_url=app_js_url)

    year = host_now.astimezone(ASIA_SHANGHAI).year
    history_url = HISTORY_YEAR_TEMPLATE.format(year=year)
    history_resp = fetch(history_url)
    if history_resp.status != 200:
        raise ProspectiveSourceError(
            "HTTP_STATUS_NOT_OK", f"history_year status={history_resp.status}"
        )
    hist_max, _hist_open, _ = parse_history_max_expect(history_resp.body)
    target = next_expect_after(hist_max)
    point_url = POINT_TEMPLATE.format(expect=target)
    reject_unsupported_latest_authority(point_url)
    point_resp = fetch(point_url)
    if point_resp.status != 200:
        raise ProspectiveSourceError("HTTP_STATUS_NOT_OK", f"point_next status={point_resp.status}")
    point_payload = parse_point_payload(point_resp.body)
    if not point_is_null(point_payload):
        raise ProspectiveSourceError(
            "CANARY_TARGET_ALREADY_PUBLISHED",
            f"point {target} is result-bearing",
        )
    if point_payload.get("result") is not True:
        raise ProspectiveSourceError("CANARY_POINT_ENVELOPE_DRIFT", "result!=true")
    # Live unpublished envelope uses code 0 or 200 with data null — both accepted.
    code = point_payload.get("code")
    if code not in (0, 200, "0", "200"):
        raise ProspectiveSourceError("CANARY_POINT_ENVELOPE_DRIFT", f"code={code!r}")

    return {
        "ok": True,
        "canary": True,
        "daemon": False,
        "campaign_state_written": False,
        "freeze": False,
        "source_id": SOURCE_ID,
        "contract_sha256": contract["contract_sha256"],
        "latest_completed_expect": hist_max,
        "target_expect": target,
        "target_ref": f"macaujc2/expect/{target}",
        "schedule": {
            "close_time_local": schedule["close_time_local"],
            "live_window_start_local": schedule["live_window_start_local"],
            "live_window_end_local": schedule["live_window_end_local"],
            "schedule_form": schedule.get("schedule_form"),
            "schedule_source_sha256": schedule["schedule_source_sha256"],
        },
        "point_data_null": True,
        "frontier_source": "history_year+point_next",
        "authorized_endpoints_only": True,
        "latest_used": False,
        "completion_claim_allowed": False,
        "owner_channel_authority": "UNPROVEN_BY_LIBRARY",
    }


__all__ = ["run_live_source_canary"]
