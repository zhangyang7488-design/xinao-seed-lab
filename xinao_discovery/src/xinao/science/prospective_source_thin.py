"""Thin prospective macaujc2 source seam (Owner one-shot capture + reveal).

Composes existing ``AuthorityContract`` endpoint pins, raw CAS, and
``OutcomeObservation`` / ``admit_outcome``. Not a parallel authority platform.

Evidence validation only: this library does **not** authenticate Codex. Physical
Owner authority is mount/write-domain separation of the authority root.
Capture and reveal are one-shot callable surfaces — no loop, timer, watcher,
auto-freeze, auto-settle, or next-period start.

Schedule rule: expect IDs are YYYY + day-of-year (verified against openTime local
date). Target calendar day is derived from the next expect day-of-year (including
leap/year rollover), never as openTime + 1 alone.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final, Literal, get_args
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from xinao.canonical import canonical_sha256
from xinao.contracts.objects import AuthorityContract
from xinao.settlement.shadow import OutcomeObservation, admit_outcome


def _authority_literal(field: str) -> str:
    """Compose pin values from AuthorityContract field Literals (single contract source)."""

    args = get_args(AuthorityContract.model_fields[field].annotation)
    if not args or not isinstance(args[0], str):
        raise RuntimeError(f"AuthorityContract.{field} is not a string Literal pin")
    return args[0]


# --- pins composed from AuthorityContract (not redeclared free-form) ---
SOURCE_ID: Final = _authority_literal("source_id")
CONTRACT_REF: Final = _authority_literal("contract_ref")
PRODUCT_IDENTITY_CN: Final = _authority_literal("product_identity")
PRODUCT_IDENTITY_TW: Final = "新澳門六合彩"  # live site traditional form of product_identity
CANONICAL_SITE: Final = _authority_literal("canonical_site")
CANONICAL_HOST: Final = urlparse(CANONICAL_SITE).hostname or "macaujc.com"
HISTORY_YEAR_TEMPLATE: Final = _authority_literal("history_endpoint_template")
POINT_TEMPLATE: Final = _authority_literal("point_endpoint_template")
HISTORY_HOST: Final = urlparse(HISTORY_YEAR_TEMPLATE).hostname or "history.macaumarksix.com"
# /latest is NOT in AuthorityContract and is not an authorized parent capture path.
UNSUPPORTED_LATEST_PATH: Final = "/history/macaujc2/latest"

SCHEMA_PACKET: Final = "xinao.prospective_target_authority_packet.v1"
PACKET_MARKER: Final = "XINAO_PROSPECTIVE_TARGET_AUTHORITY_V1"
BINDING_SCHEMA: Final = "xinao.source_authority_binding.v1"
CLOCK_TRUST_GRADE: Final = "OPERATIONAL_HOST_AND_HTTP_DATE"
MAX_HOST_HTTP_SKEW: Final = timedelta(minutes=5)
DEFAULT_FETCH_TIMEOUT_S: Final = 20
ASIA_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
MACAUJC2_HISTORY_MARKER: Final = "/history/macaujc2/"

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXPECT_RE = re.compile(r"^\d{7}$")
_TARGET_REF_RE = re.compile(r"^macaujc2/expect/\d{7}$")
_APP_JS_REL_RE = re.compile(
    r"""(?:src|href)\s*=\s*["'](/js/app\.[^"'/]+\.js)["']""",
    re.IGNORECASE,
)
# closeTime may be bare quoted or live x("HH:MM:SS") wrapper.
_CLOSE_TIME_RE = re.compile(
    r"""closeTime\s*[:=]\s*(?:x\s*\(\s*)?['"](\d{2}:\d{2}:\d{2})['"]\s*\)?""",
    re.IGNORECASE,
)
# Prior valid form: liveTime:['HH:MM:SS','HH:MM:SS']
_LIVE_ARRAY_RE = re.compile(
    r"""liveTime\s*[:=]\s*\[\s*['"](\d{2}:\d{2}:\d{2})['"]\s*,\s*['"](\d{2}:\d{2}:\d{2})['"]\s*\]""",
    re.IGNORECASE,
)
# Live app form: liveTime:x("HH:MM:SS")+"-"+x("HH:MM:SS")
_LIVE_CONCAT_RE = re.compile(
    r"""liveTime\s*[:=]\s*(?:x\s*\(\s*)?['"](\d{2}:\d{2}:\d{2})['"]\s*\)?"""
    r"""\s*\+\s*['"]-['"]\s*\+\s*(?:x\s*\(\s*)?['"](\d{2}:\d{2}:\d{2})['"]\s*\)?""",
    re.IGNORECASE,
)
_HISTORY_URL_RE = re.compile(
    r"""historyUrl\s*[:=]\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_PRODUCT_IDENTITY_RE = re.compile(r"新澳門六合彩|新澳门六合彩")
_FORBIDDEN_OUTCOME_KEYS: Final = frozenset(
    {
        "outcome",
        "openCode",
        "open_code",
        "actual_special_number",
        "special_number",
        "settlement",
        "settled",
        "result_numbers",
        "numbers",
        "peeked_outcome",
        "future_outcome",
    }
)

Fetcher = Callable[[str], "FetchResponse"]
Clock = Callable[[], datetime]


class ProspectiveSourceError(ValueError):
    """Fail-closed prospective source rejection with stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    body: bytes
    headers: Mapping[str, str]
    captured_at: datetime


@dataclass(frozen=True)
class ResultRow:
    expect: str
    open_time: datetime
    open_code: tuple[int, ...] | None


def raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_hex64(value: object, reason: str, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise ProspectiveSourceError(reason, f"{label} must be lowercase sha256")
    return value


def _require_text(value: object, reason: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProspectiveSourceError(reason, f"{label} required")
    return value


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_aware(value: object, label: str) -> datetime:
    text = _require_text(value, "TIME_INVALID", label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProspectiveSourceError("TIME_INVALID", f"{label}: {exc}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveSourceError("TIME_INVALID", f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def parse_expect(expect: str) -> tuple[int, int]:
    if _EXPECT_RE.fullmatch(expect) is None:
        raise ProspectiveSourceError("EXPECT_INVALID", expect)
    year = int(expect[:4])
    doy = int(expect[4:])
    max_doy = 366 if is_leap_year(year) else 365
    if doy < 1 or doy > max_doy:
        raise ProspectiveSourceError(
            "EXPECT_SEQ_OUT_OF_RANGE",
            f"{expect} exceeds year calendar max={max_doy}",
        )
    return year, doy


def expect_to_local_date(expect: str) -> date:
    year, doy = parse_expect(expect)
    return date(year, 1, 1) + timedelta(days=doy - 1)


def next_expect_after(latest: str) -> str:
    """Next expect = next day-of-year with leap/year rollover."""

    year, doy = parse_expect(latest)
    max_doy = 366 if is_leap_year(year) else 365
    if doy >= max_doy:
        return f"{year + 1}001"
    return f"{year}{doy + 1:03d}"


def validate_expect_matches_open_date(expect: str, open_time: datetime) -> None:
    local = open_time.astimezone(ASIA_SHANGHAI).date()
    expected = expect_to_local_date(expect)
    if local != expected:
        raise ProspectiveSourceError(
            "EXPECT_OPEN_DATE_MISMATCH",
            f"expect={expect} implies {expected.isoformat()} local, open={local.isoformat()}",
        )


def resolve_authority_root(root: Path) -> Path:
    return root.expanduser().resolve()


def _cas_path(root: Path, kind: str, digest: str, ext: str) -> Path:
    base = resolve_authority_root(root) / "objects" / kind / "sha256" / digest[:2]
    return base / f"{digest}{ext}"


def raw_object_path(root: Path, digest: str) -> Path:
    return _cas_path(root, "raw", digest, ".bin")


def packet_object_path(root: Path, digest: str) -> Path:
    return _cas_path(root, "packet", digest, ".json")


def reveal_object_path(root: Path, digest: str) -> Path:
    return _cas_path(root, "reveal", digest, ".json")


def target_index_path(root: Path, expect: str) -> Path:
    return resolve_authority_root(root) / "index" / "target" / f"{expect}.json"


def _honest_library_flags() -> dict[str, Any]:
    """Shared fail-closed honesty surface — library never authenticates Codex."""

    return {
        "completion_claim_allowed": False,
        "real_money_authorized": False,
        "parent_complete": False,
        "auto_freeze": False,
        "auto_settle": False,
        "daemon": False,
        "temporal": False,
        "trusted_time_proof": False,
        "owner_channel_authority": "UNPROVEN_BY_LIBRARY",
        "physical_owner_write_isolation_verified": False,
    }


def _write_exclusive_bytes(path: Path, payload: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
        return True
    except FileExistsError as exc:
        existing = path.read_bytes()
        if existing != payload:
            raise ProspectiveSourceError(
                "CAS_CONTENT_CONFLICT",
                f"path={path} already sealed with different bytes",
            ) from exc
        return False


def write_raw_bytes_cas(root: Path, payload: bytes) -> dict[str, Any]:
    digest = raw_sha256(payload)
    path = raw_object_path(root, digest)
    written = _write_exclusive_bytes(path, payload)
    return {
        "sha256": digest,
        "byte_length": len(payload),
        "path": str(path),
        "bytes_written": written,
    }


def _object_pairs_hook_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ProspectiveSourceError(
                "JSON_DUPLICATE_KEY",
                f"duplicate key {key!r}",
            )
        out[key] = value
    return out


def parse_json_strict(raw: bytes, *, reason: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProspectiveSourceError(reason, str(exc)) from exc
    try:
        return json.loads(text, object_pairs_hook=_object_pairs_hook_no_duplicates)
    except ProspectiveSourceError:
        raise
    except json.JSONDecodeError as exc:
        raise ProspectiveSourceError(reason, str(exc)) from exc


def reject_outcome_material(node: object, *, path: str = "$") -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            key_text = str(key)
            if key_text in _FORBIDDEN_OUTCOME_KEYS or key_text.lower() in _FORBIDDEN_OUTCOME_KEYS:
                raise ProspectiveSourceError("OUTCOME_MATERIAL_FORBIDDEN", f"{path}.{key_text}")
            lower = key_text.lower()
            if lower.startswith("peeked_") or lower.startswith("future_"):
                raise ProspectiveSourceError("OUTCOME_MATERIAL_FORBIDDEN", f"{path}.{key_text}")
            reject_outcome_material(value, path=f"{path}.{key_text}")
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            reject_outcome_material(item, path=f"{path}[{index}]")


def default_clock() -> datetime:
    value = datetime.now(UTC)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def default_fetcher(url: str, *, timeout: float = DEFAULT_FETCH_TIMEOUT_S) -> FetchResponse:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "xinao-prospective-source-thin/1.0"},
        method="GET",
    )
    captured_at = default_clock()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = int(response.status)
            headers = {str(k): str(v) for k, v in response.headers.items()}
            effective = response.geturl()
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        status = int(exc.code)
        headers = {str(k): str(v) for k, v in (exc.headers.items() if exc.headers else [])}
        effective = url
    except urllib.error.URLError as exc:
        raise ProspectiveSourceError("FETCH_FAILED", f"{url}: {exc}") from exc
    if effective.split("#", 1)[0] != url.split("#", 1)[0]:
        raise ProspectiveSourceError("FETCH_URL_DRIFT", f"requested={url} effective={effective}")
    return FetchResponse(
        url=url,
        status=status,
        body=body,
        headers=headers,
        captured_at=captured_at,
    )


def _require_http_ok(response: FetchResponse, role: str) -> None:
    if response.status != 200:
        raise ProspectiveSourceError("HTTP_STATUS_NOT_OK", f"{role} status={response.status}")


def _http_date_from_headers(headers: Mapping[str, str]) -> datetime | None:
    for key, value in headers.items():
        if key.lower() == "date":
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError, IndexError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
    return None


def _assert_pinned_url(url: str, *, allowed_hosts: set[str], role: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ProspectiveSourceError("SOURCE_HOST_PATH_DRIFT", f"{role} must be https: {url}")
    host = (parsed.hostname or "").lower()
    if host not in allowed_hosts:
        raise ProspectiveSourceError(
            "SOURCE_HOST_PATH_DRIFT",
            f"{role} host={host!r} not in {sorted(allowed_hosts)}",
        )


def _assert_exact_url(url: str, expected: str, role: str) -> None:
    if url.split("#", 1)[0] != expected.split("#", 1)[0]:
        raise ProspectiveSourceError(
            "SOURCE_HOST_PATH_DRIFT",
            f"{role} requested={url} expected={expected}",
        )


def verify_macaujc2_contract_bytes(raw: bytes, *, expected_sha256: str) -> dict[str, str]:
    digest = raw_sha256(raw)
    expected = expected_sha256.lower()
    if digest != expected:
        raise ProspectiveSourceError(
            "CONTRACT_SHA256_MISMATCH",
            f"observed={digest} expected={expected}",
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProspectiveSourceError("CONTRACT_NOT_UTF8", str(exc)) from exc
    required = (
        SOURCE_ID,
        CONTRACT_REF,
        "https://macaujc.com/",
        HISTORY_YEAR_TEMPLATE,
        POINT_TEMPLATE,
        PRODUCT_IDENTITY_CN,
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise ProspectiveSourceError("CONTRACT_TOKEN_MISSING", f"missing={missing}")
    return {
        "contract_sha256": digest,
        "source_id": SOURCE_ID,
        "contract_ref": CONTRACT_REF,
        "canonical_site": CANONICAL_SITE,
        "history_endpoint_template": HISTORY_YEAR_TEMPLATE,
        "point_endpoint_template": POINT_TEMPLATE,
    }


def discover_same_origin_app_js(site_html: bytes, *, canonical_site: str = CANONICAL_SITE) -> str:
    """Canonical site may discover only a same-origin relative app asset path."""

    text = site_html.decode("utf-8", errors="ignore")
    match = _APP_JS_REL_RE.search(text)
    if match is None:
        # Reject absolute app/latest URLs as discovery authority.
        if re.search(r"""(?:src|href)\s*=\s*["']https?://""", text, re.IGNORECASE):
            abs_js = re.search(
                r"""(?:src|href)\s*=\s*["'](https?://[^"']*/js/app\.[^"']+\.js)["']""",
                text,
                re.IGNORECASE,
            )
            if abs_js is not None:
                raise ProspectiveSourceError(
                    "APP_JS_ABSOLUTE_URL_FORBIDDEN",
                    abs_js.group(1),
                )
        raise ProspectiveSourceError("APP_JS_ASSET_NOT_FOUND", "no same-origin /js/app.*.js")
    asset = match.group(1)
    base = canonical_site.rstrip("/")
    return base + asset


def extract_product_schedule(app_js: bytes, *, app_js_url: str) -> dict[str, str]:
    """Extract macaujc2 product close/live times from same-origin app JS.

    Supports:
    - live form: ``closeTime:x("HH:MM:SS"), liveTime:x("HH:MM:SS")+"-"+x("HH:MM:SS")``
    - prior form: ``closeTime:'HH:MM:SS' liveTime:['HH:MM:SS','HH:MM:SS']``

    Times always come from sealed JS (never hardcoded calendar day). Binds to
    macaujc2 product/history identity; rejects ambiguous or wrong-product blocks.
    """

    text = app_js.decode("utf-8", errors="ignore")
    _assert_pinned_url(
        app_js_url, allowed_hosts={CANONICAL_HOST, f"www.{CANONICAL_HOST}"}, role="app_js"
    )
    identity_hits = list(_PRODUCT_IDENTITY_RE.finditer(text))
    if not identity_hits:
        raise ProspectiveSourceError("PRODUCT_BLOCK_MISSING", "product identity absent")

    candidates: list[dict[str, str]] = []
    for hit in identity_hits:
        window = text[hit.start() : hit.start() + 4000]
        product = hit.group(0)
        history_m = _HISTORY_URL_RE.search(window)
        if history_m is not None:
            history_url = history_m.group(1)
            if MACAUJC2_HISTORY_MARKER not in history_url and SOURCE_ID not in history_url:
                # Wrong product block (e.g. foreign lottery with different historyUrl).
                continue
        close_m = _CLOSE_TIME_RE.search(window)
        if close_m is None:
            continue
        live_arr = _LIVE_ARRAY_RE.search(window)
        live_concat = _LIVE_CONCAT_RE.search(window)
        if live_arr is not None:
            live_start, live_end = live_arr.group(1), live_arr.group(2)
            schedule_form = "array_literal"
        elif live_concat is not None:
            live_start, live_end = live_concat.group(1), live_concat.group(2)
            schedule_form = "x_concat"
        else:
            continue
        close_time = close_m.group(1)
        if live_start >= live_end:
            raise ProspectiveSourceError("LIVE_WINDOW_INVALID", f"{live_start}..{live_end}")
        if close_time >= live_start:
            raise ProspectiveSourceError("CLOSE_AFTER_LIVE_START", f"close={close_time}")
        candidates.append(
            {
                "product_identity": product,
                "close_time_local": close_time,
                "live_window_start_local": live_start,
                "live_window_end_local": live_end,
                "schedule_form": schedule_form,
                "history_url": history_m.group(1) if history_m is not None else "",
            }
        )

    if not candidates:
        raise ProspectiveSourceError(
            "PRODUCT_SCHEDULE_NOT_FOUND",
            "closeTime/liveTime missing for macaujc2 product block",
        )
    # Prefer blocks explicitly bound to macaujc2 historyUrl when present.
    bound = [c for c in candidates if MACAUJC2_HISTORY_MARKER in c.get("history_url", "")]
    pool = bound if bound else candidates
    unique_schedules = {
        (c["close_time_local"], c["live_window_start_local"], c["live_window_end_local"])
        for c in pool
    }
    if len(unique_schedules) != 1:
        raise ProspectiveSourceError(
            "PRODUCT_SCHEDULE_AMBIGUOUS",
            f"multiple macaujc2 schedule candidates={len(pool)}",
        )
    chosen = pool[0]
    return {
        "product_identity": chosen["product_identity"],
        "close_time_local": chosen["close_time_local"],
        "live_window_start_local": chosen["live_window_start_local"],
        "live_window_end_local": chosen["live_window_end_local"],
        "schedule_form": chosen["schedule_form"],
        "history_url": chosen["history_url"],
        "app_js_url": app_js_url,
        "schedule_source_sha256": raw_sha256(app_js),
        "source_id": SOURCE_ID,
    }


def _parse_open_code(value: object) -> tuple[int, ...]:
    text = str(value)
    numbers = tuple(int(part) for part in text.split(","))
    if len(numbers) != 7 or len(set(numbers)) != 7 or any(not 1 <= n <= 49 for n in numbers):
        raise ProspectiveSourceError(
            "OPEN_CODE_INVALID", f"require seven unique 1..49, got {value!r}"
        )
    return numbers


def _parse_open_time(value: object) -> datetime:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=ASIA_SHANGHAI)
    except ValueError as exc:
        raise ProspectiveSourceError("OPEN_TIME_INVALID", str(value)) from exc


def parse_history_max_expect(raw: bytes) -> tuple[str, datetime, set[str]]:
    payload = parse_json_strict(raw, reason="HISTORY_JSON_INVALID")
    if (
        not isinstance(payload, dict)
        or payload.get("result") is not True
        or payload.get("code") != 200
    ):
        raise ProspectiveSourceError("HISTORY_ENVELOPE_INVALID", "result/code")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ProspectiveSourceError("HISTORY_DATA_EMPTY", "no rows")
    max_expect: str | None = None
    max_open: datetime | None = None
    expects: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        expect = str(row.get("expect", ""))
        if _EXPECT_RE.fullmatch(expect) is None:
            continue
        if row.get("openCode") in (None, "", "null"):
            continue
        _parse_open_code(row.get("openCode"))
        open_time = _parse_open_time(row.get("openTime"))
        validate_expect_matches_open_date(expect, open_time)
        expects.add(expect)
        if max_expect is None or int(expect) > int(max_expect):
            max_expect = expect
            max_open = open_time
    if max_expect is None or max_open is None:
        raise ProspectiveSourceError("HISTORY_NO_RESULT_ROWS", "empty after filter")
    return max_expect, max_open, expects


def reject_unsupported_latest_authority(url: str) -> None:
    """Parent capture must never treat /latest as authority (not in AuthorityContract)."""

    path = urlparse(url).path or ""
    if path.rstrip("/") == UNSUPPORTED_LATEST_PATH.rstrip("/") or path.endswith("/macaujc2/latest"):
        raise ProspectiveSourceError(
            "LATEST_NOT_AUTHORIZED",
            "history+point+same-origin schedule only; /latest is not AuthorityContract",
        )


def parse_point_payload(raw: bytes) -> dict[str, Any]:
    payload = parse_json_strict(raw, reason="POINT_JSON_INVALID")
    if not isinstance(payload, dict):
        raise ProspectiveSourceError("POINT_JSON_INVALID", "object required")
    return payload


def point_is_null(payload: Mapping[str, Any]) -> bool:
    data = payload.get("data")
    return data is None or data == []


def point_result_row(payload: Mapping[str, Any]) -> ResultRow:
    if payload.get("result") is not True or payload.get("code") != 200 or point_is_null(payload):
        raise ProspectiveSourceError("POINT_NOT_RESULT_BEARING", "data null or unsuccessful")
    data = payload.get("data")
    row = data[0] if isinstance(data, list) and data else data
    if not isinstance(row, dict):
        raise ProspectiveSourceError("POINT_ROW_INVALID", type(row).__name__)
    expect = str(row.get("expect", ""))
    open_time = _parse_open_time(row.get("openTime"))
    validate_expect_matches_open_date(expect, open_time)
    return ResultRow(
        expect=expect,
        open_time=open_time,
        open_code=_parse_open_code(row.get("openCode")),
    )


def _parse_local_wall(hhmmss: str, day: date) -> datetime:
    hour, minute, second = (int(part) for part in hhmmss.split(":"))
    return datetime.combine(day, time(hour, minute, second), tzinfo=ASIA_SHANGHAI)


def _clock_evidence(
    *,
    host_now: datetime,
    http_dates: list[datetime],
    freeze_deadline: datetime,
) -> dict[str, Any]:
    if not http_dates:
        raise ProspectiveSourceError(
            "HTTP_DATE_REQUIRED",
            "at least one relevant HTTP Date header required (OPERATIONAL, not cryptographic)",
        )
    host_utc = host_now.astimezone(UTC)
    deadline_utc = freeze_deadline.astimezone(UTC)
    for hd in http_dates:
        if abs(hd - host_utc) > MAX_HOST_HTTP_SKEW:
            raise ProspectiveSourceError(
                "HOST_HTTP_DATE_SKEW",
                f"host={_iso_z(host_utc)} http={_iso_z(hd)}",
            )
        if hd > deadline_utc:
            raise ProspectiveSourceError(
                "HTTP_DATE_AFTER_DEADLINE",
                f"http={_iso_z(hd)} deadline={_iso_z(deadline_utc)}",
            )
    if host_utc > deadline_utc:
        raise ProspectiveSourceError(
            "HOST_TIME_AFTER_DEADLINE",
            f"host={_iso_z(host_utc)} deadline={_iso_z(deadline_utc)}",
        )
    return {
        "host_time_utc": _iso_z(host_utc),
        "http_dates_utc": tuple(_iso_z(hd) for hd in http_dates),
        "max_host_http_skew_seconds": int(MAX_HOST_HTTP_SKEW.total_seconds()),
        "trust_grade": CLOCK_TRUST_GRADE,
        "trusted_time_proof": False,
        "time_authority": "OPERATIONAL_NOT_CRYPTOGRAPHIC",
    }


def _capture_ref(*, role: str, response: FetchResponse, cas: Mapping[str, Any]) -> dict[str, Any]:
    http_date = _http_date_from_headers(response.headers)
    return {
        "role": role,
        "url": response.url,
        "http_status": response.status,
        "http_date": _iso_z(http_date) if http_date is not None else None,
        "captured_at": _iso_z(response.captured_at.astimezone(UTC)),
        "byte_length": int(cas["byte_length"]),
        "sha256": str(cas["sha256"]),
        "content_addressed_path": str(cas["path"]),
    }


def packet_content_hash(packet: Mapping[str, Any]) -> str:
    body = {k: v for k, v in packet.items() if k != "content_hash"}
    return canonical_sha256(body)


def write_packet_exclusive(root: Path, packet: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(packet)
    digest = packet_content_hash(body)
    body["content_hash"] = digest
    raw = (json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path = packet_object_path(root, digest)
    written = _write_exclusive_bytes(path, raw)
    idx = target_index_path(root, str(body["target_expect"]))
    idx_body = (
        json.dumps(
            {
                "target_expect": body["target_expect"],
                "packet_content_hash": digest,
                "target_ref": body["target_ref"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    try:
        _write_exclusive_bytes(idx, idx_body)
    except ProspectiveSourceError as exc:
        if exc.reason_code == "CAS_CONTENT_CONFLICT":
            raise ProspectiveSourceError(
                "TARGET_INDEX_CONFLICT",
                f"target {body['target_expect']} already bound to a different packet",
            ) from exc
        raise
    return {
        "packet_content_hash": digest,
        "path": str(path),
        "bytes_written": written,
        "packet": body,
    }


def load_packet(root: Path, packet_content_hash_value: str) -> dict[str, Any]:
    """Load sealed packet from Owner-controlled CAS only (no caller in-memory substitute)."""

    digest = _require_hex64(packet_content_hash_value, "PACKET_HASH_INVALID", "packet_content_hash")
    path = packet_object_path(root, digest)
    if not path.is_file() or path.is_symlink():
        raise ProspectiveSourceError("PACKET_MISSING", str(path))
    if path.name != f"{digest}.json" or path.parent.name != digest[:2]:
        raise ProspectiveSourceError("PACKET_PATH_MISMATCH", str(path))
    raw = path.read_bytes()
    payload = parse_json_strict(raw, reason="PACKET_JSON_INVALID")
    if not isinstance(payload, dict):
        raise ProspectiveSourceError("PACKET_JSON_INVALID", "object required")
    if payload.get("content_hash") != digest or packet_content_hash(payload) != digest:
        raise ProspectiveSourceError("PACKET_HASH_MISMATCH", digest)
    reject_outcome_material(payload)
    for ref in payload.get("raw_captures") or ():
        if not isinstance(ref, Mapping):
            continue
        sha = str(ref.get("sha256", ""))
        raw_path = Path(str(ref.get("content_addressed_path", "")))
        if not raw_path.is_file():
            alt = raw_object_path(root, sha)
            if not alt.is_file():
                raise ProspectiveSourceError("RAW_CAS_MISSING", sha)
            raw_path = alt
        if raw_sha256(raw_path.read_bytes()) != sha:
            raise ProspectiveSourceError("RAW_CAS_TAMPERED", sha)
    return payload


def build_source_authority_binding(packet: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BINDING_SCHEMA,
        "packet_content_hash": str(packet["content_hash"]),
        "source_id": SOURCE_ID,
        "contract_sha256": str(packet["contract"]["contract_sha256"]),
        "target_ref": str(packet["target_ref"]),
        "target_expect": str(packet["target_expect"]),
        "target_guard_open_time": str(packet["target_guard_open_time"]),
        "freeze_deadline": str(packet["freeze_deadline"]),
        "latest_completed_expect": str(packet["latest_completed_expect"]),
        "capture_sha256": str(packet["capture_sha256"]),
    }


def validate_source_authority_binding(
    raw: Mapping[str, Any],
    *,
    packet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    required = {
        "schema_version",
        "packet_content_hash",
        "source_id",
        "contract_sha256",
        "target_ref",
        "target_expect",
        "target_guard_open_time",
        "freeze_deadline",
        "latest_completed_expect",
        "capture_sha256",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ProspectiveSourceError("SOURCE_AUTHORITY_BINDING_INCOMPLETE", f"missing={missing}")
    unknown = sorted(set(raw) - required)
    if unknown:
        raise ProspectiveSourceError(
            "SOURCE_AUTHORITY_BINDING_UNKNOWN_FIELDS", f"unknown={unknown}"
        )
    if raw.get("schema_version") != BINDING_SCHEMA:
        raise ProspectiveSourceError(
            "SOURCE_AUTHORITY_BINDING_SCHEMA_DRIFT",
            str(raw.get("schema_version")),
        )
    if raw.get("source_id") != SOURCE_ID:
        raise ProspectiveSourceError(
            "SOURCE_AUTHORITY_BINDING_SOURCE_MISMATCH",
            str(raw.get("source_id")),
        )
    packet_hash = _require_hex64(
        raw.get("packet_content_hash"),
        "SOURCE_AUTHORITY_BINDING_HASH_INVALID",
        "packet_content_hash",
    )
    contract_hash = _require_hex64(
        raw.get("contract_sha256"),
        "SOURCE_AUTHORITY_BINDING_HASH_INVALID",
        "contract_sha256",
    )
    capture_hash = _require_hex64(
        raw.get("capture_sha256"),
        "SOURCE_AUTHORITY_BINDING_HASH_INVALID",
        "capture_sha256",
    )
    target_ref = _require_text(
        raw.get("target_ref"), "SOURCE_AUTHORITY_BINDING_TARGET_INVALID", "target_ref"
    )
    target_expect = _require_text(
        raw.get("target_expect"),
        "SOURCE_AUTHORITY_BINDING_TARGET_INVALID",
        "target_expect",
    )
    if target_ref != f"macaujc2/expect/{target_expect}":
        raise ProspectiveSourceError("SOURCE_AUTHORITY_BINDING_TARGET_MISMATCH", target_ref)
    guard = _parse_aware(raw.get("target_guard_open_time"), "target_guard_open_time")
    deadline = _parse_aware(raw.get("freeze_deadline"), "freeze_deadline")
    if deadline >= guard:
        raise ProspectiveSourceError(
            "SOURCE_AUTHORITY_BINDING_TEMPORAL_VIOLATION",
            "freeze_deadline must precede target_guard_open_time",
        )
    latest = _require_text(
        raw.get("latest_completed_expect"),
        "SOURCE_AUTHORITY_BINDING_LATEST_INVALID",
        "latest_completed_expect",
    )
    parse_expect(latest)
    normalized = {
        "schema_version": BINDING_SCHEMA,
        "packet_content_hash": packet_hash,
        "source_id": SOURCE_ID,
        "contract_sha256": contract_hash,
        "target_ref": target_ref,
        "target_expect": target_expect,
        "target_guard_open_time": _iso_z(guard),
        "freeze_deadline": _iso_z(deadline),
        "latest_completed_expect": latest,
        "capture_sha256": capture_hash,
    }
    if packet is not None:
        expected = build_source_authority_binding(packet)
        for key, value in expected.items():
            if normalized.get(key) != value:
                raise ProspectiveSourceError(
                    "SOURCE_AUTHORITY_BINDING_PACKET_MISMATCH",
                    f"{key}: binding={normalized.get(key)!r} packet={value!r}",
                )
    return normalized


def is_live_macaujc2_target(target_ref: str) -> bool:
    return _TARGET_REF_RE.fullmatch(target_ref) is not None


def verify_disposition_times_against_packet(
    *,
    disposition: Mapping[str, Any],
    packet: Mapping[str, Any],
    owner_freeze_time: datetime | None = None,
) -> None:
    if disposition.get("target_ref") != packet["target_ref"]:
        raise ProspectiveSourceError(
            "DISPOSITION_TARGET_PACKET_MISMATCH",
            f"disposition={disposition.get('target_ref')!r} packet={packet['target_ref']!r}",
        )
    account = disposition.get("account_identity")
    if account == "ACTION":
        branch = disposition.get("executable_account_decision")
    else:
        branch = disposition.get("no_action_period_binding")
    if not isinstance(branch, Mapping):
        raise ProspectiveSourceError("DISPOSITION_PERIOD_BRANCH_MISSING", str(account))
    if str(branch.get("target_ref")) != packet["target_ref"]:
        raise ProspectiveSourceError(
            "DISPOSITION_BRANCH_TARGET_MISMATCH", str(branch.get("target_ref"))
        )
    guard_iso = str(packet["target_guard_open_time"])
    deadline_iso = str(packet["freeze_deadline"])
    if str(branch.get("target_open_time")) != guard_iso:
        raise ProspectiveSourceError(
            "DISPOSITION_GUARD_OPEN_MISMATCH",
            f"disposition={branch.get('target_open_time')!r} packet={guard_iso!r}",
        )
    if str(branch.get("freeze_deadline")) != deadline_iso:
        raise ProspectiveSourceError(
            "DISPOSITION_FREEZE_DEADLINE_MISMATCH",
            f"disposition={branch.get('freeze_deadline')!r} packet={deadline_iso!r}",
        )
    frozen_at = _parse_aware(branch.get("frozen_at"), "frozen_at")
    deadline = _parse_aware(deadline_iso, "freeze_deadline")
    if frozen_at > deadline:
        raise ProspectiveSourceError(
            "OWNER_FREEZE_AFTER_DEADLINE",
            f"frozen_at={_iso_z(frozen_at)} deadline={deadline_iso}",
        )
    if owner_freeze_time is not None:
        oft = owner_freeze_time.astimezone(UTC)
        if oft > deadline:
            raise ProspectiveSourceError(
                "OWNER_FREEZE_AFTER_DEADLINE",
                f"owner_freeze_time={_iso_z(oft)} deadline={deadline_iso}",
            )


def capture_prospective_target_authority(
    *,
    authority_root: Path,
    contract_path: Path,
    expected_contract_sha256: str,
    fetcher: Fetcher | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Owner one-shot prospective capture. Seals packet exclusively under authority_root.

    Authority inputs: active AuthorityContract pins + history year + point-next +
    same-origin schedule only. Does not use /latest. Does not prove the caller is
    Codex — physical isolation of authority_root is required outside this library.
    """

    fetch = fetcher or default_fetcher
    now_fn = clock or default_clock
    root = resolve_authority_root(authority_root)
    root.mkdir(parents=True, exist_ok=True)

    contract_path = contract_path.expanduser().resolve()
    if not contract_path.is_file():
        raise ProspectiveSourceError("CONTRACT_FILE_MISSING", str(contract_path))
    contract_bytes = contract_path.read_bytes()
    contract = verify_macaujc2_contract_bytes(
        contract_bytes,
        expected_sha256=expected_contract_sha256.lower(),
    )
    contract_cas = write_raw_bytes_cas(root, contract_bytes)

    host_now = now_fn()
    if host_now.tzinfo is None or host_now.utcoffset() is None:
        raise ProspectiveSourceError("HOST_TIME_NOT_AWARE", "clock must be aware")

    # 1) Canonical site HTML → same-origin app JS only.
    site_resp = fetch(CANONICAL_SITE)
    _require_http_ok(site_resp, "site_html")
    _assert_exact_url(site_resp.url, CANONICAL_SITE, "site_html")
    site_cas = write_raw_bytes_cas(root, site_resp.body)
    app_js_url = discover_same_origin_app_js(site_resp.body, canonical_site=CANONICAL_SITE)
    reject_unsupported_latest_authority(app_js_url)

    # 2) App JS → product schedule times only (not frontier authority).
    app_resp = fetch(app_js_url)
    _require_http_ok(app_resp, "app_js")
    _assert_exact_url(app_resp.url, app_js_url, "app_js")
    app_cas = write_raw_bytes_cas(root, app_resp.body)
    schedule = extract_product_schedule(app_resp.body, app_js_url=app_js_url)

    # 3) History frontier (result authority). No /latest path.
    year_guess = host_now.astimezone(ASIA_SHANGHAI).year
    history_url = HISTORY_YEAR_TEMPLATE.format(year=year_guess)
    reject_unsupported_latest_authority(history_url)
    history_resp = fetch(history_url)
    _require_http_ok(history_resp, "history_year")
    _assert_exact_url(history_resp.url, history_url, "history_year")
    history_cas = write_raw_bytes_cas(root, history_resp.body)
    hist_max, hist_open, hist_expects = parse_history_max_expect(history_resp.body)

    # Near year boundary (low day-of-year), also consider previous year max.
    _completed_year, completed_doy = parse_expect(hist_max)
    if completed_doy <= 2 and year_guess > 2000:
        prev_url = HISTORY_YEAR_TEMPLATE.format(year=year_guess - 1)
        prev_resp = fetch(prev_url)
        if prev_resp.status == 200:
            try:
                prev_max, prev_open, prev_expects = parse_history_max_expect(prev_resp.body)
                if int(prev_max) > int(hist_max):
                    hist_max, hist_open = prev_max, prev_open
                    hist_expects |= prev_expects
                    _completed_year, completed_doy = parse_expect(hist_max)
            except ProspectiveSourceError:
                pass

    completed_expect = hist_max
    completed_open = hist_open
    raw_captures: list[dict[str, Any]] = [
        {
            "role": "contract",
            "url": f"file://{contract_path.as_posix()}",
            "http_status": 200,
            "http_date": None,
            "captured_at": _iso_z(host_now.astimezone(UTC)),
            "byte_length": int(contract_cas["byte_length"]),
            "sha256": str(contract_cas["sha256"]),
            "content_addressed_path": str(contract_cas["path"]),
        },
        _capture_ref(role="site_html", response=site_resp, cas=site_cas),
        _capture_ref(role="app_js", response=app_resp, cas=app_cas),
        _capture_ref(role="history_year", response=history_resp, cas=history_cas),
    ]
    relevant_responses = [site_resp, app_resp, history_resp]

    target_expect = next_expect_after(completed_expect)
    target_ref = f"macaujc2/expect/{target_expect}"
    point_url = POINT_TEMPLATE.format(expect=target_expect)
    reject_unsupported_latest_authority(point_url)

    # 4) Point-next must be null / unopened; must not appear in history.
    point_resp = fetch(point_url)
    _require_http_ok(point_resp, "point_next")
    _assert_exact_url(point_resp.url, point_url, "point_next")
    point_cas = write_raw_bytes_cas(root, point_resp.body)
    point_payload = parse_point_payload(point_resp.body)
    if not point_is_null(point_payload):
        raise ProspectiveSourceError(
            "TARGET_ALREADY_PUBLISHED",
            f"point {target_expect} is result-bearing",
        )
    reject_outcome_material(
        {k: v for k, v in point_payload.items() if k != "data"},
        path="$.point",
    )
    if target_expect in hist_expects:
        raise ProspectiveSourceError("TARGET_PRESENT_IN_HISTORY", target_expect)

    # Schedule day from next expect day-of-year (YYYYDDD via next_expect_after).
    # Adjacency uses real calendar dates from DOY (year/leap-safe); never day-of-month.
    completed_day = expect_to_local_date(completed_expect)
    target_day = expect_to_local_date(target_expect)
    if target_day != completed_day + timedelta(days=1):
        raise ProspectiveSourceError(
            "MISSED_DRAW_SCHEDULE",
            f"completed={completed_day} doy={completed_doy} target={target_day} "
            f"(expect YYYYDDD adjacency via next_expect_after)",
        )

    freeze_deadline = _parse_local_wall(schedule["close_time_local"], target_day)
    target_guard_open = _parse_local_wall(schedule["live_window_start_local"], target_day)
    if freeze_deadline >= target_guard_open:
        raise ProspectiveSourceError(
            "SCHEDULE_TEMPORAL_INVALID",
            "closeTime must precede live window start",
        )

    relevant_responses.append(point_resp)
    raw_captures.append(_capture_ref(role="point_next", response=point_resp, cas=point_cas))

    http_dates: list[datetime] = []
    for resp in relevant_responses:
        hd = _http_date_from_headers(resp.headers)
        if hd is not None:
            http_dates.append(hd)
    clock_ev = _clock_evidence(
        host_now=host_now,
        http_dates=http_dates,
        freeze_deadline=freeze_deadline,
    )

    capture_basis = {
        "schema": "xinao.source_authority_capture.v1",
        "contract_sha256": contract["contract_sha256"],
        "raw": [
            {
                "role": r["role"],
                "sha256": r["sha256"],
                "url": r["url"],
                "byte_length": r["byte_length"],
            }
            for r in raw_captures
        ],
        "latest_completed_expect": completed_expect,
        "target_expect": target_expect,
        "host_time_utc": _iso_z(host_now.astimezone(UTC)),
    }
    capture_sha = canonical_sha256(capture_basis)

    packet: dict[str, Any] = {
        "schema_version": SCHEMA_PACKET,
        "packet_marker": PACKET_MARKER,
        "contract": {
            **contract,
            "contract_path": str(contract_path),
            "status": "ACTIVE_VERIFIED",
        },
        "latest_completed_expect": completed_expect,
        "latest_completed_open_time": _iso_z(completed_open.astimezone(UTC)),
        "target_expect": target_expect,
        "target_ref": target_ref,
        "schedule": schedule,
        "target_guard_open_time": _iso_z(target_guard_open.astimezone(UTC)),
        "freeze_deadline": _iso_z(freeze_deadline.astimezone(UTC)),
        "unopened": {
            "history_max_expect": completed_expect,
            "point_next_data_null": True,
            "absent_from_history": True,
            "frontier_source": "history_year+point_next",
        },
        "clock": clock_ev,
        "raw_captures": raw_captures,
        "capture_sha256": capture_sha,
        "completion_claim_allowed": False,
        "real_money_authorized": False,
        "owner_channel_authority": "UNPROVEN_BY_LIBRARY",
        "physical_owner_write_isolation_verified": False,
    }
    reject_outcome_material(packet)
    sealed = write_packet_exclusive(root, packet)
    sealed_packet = sealed["packet"]
    return {
        "ok": True,
        "packet": sealed_packet,
        "packet_content_hash": sealed["packet_content_hash"],
        "packet_path": sealed["path"],
        "source_authority_binding": build_source_authority_binding(sealed_packet),
        "bytes_written": sealed["bytes_written"],
        **_honest_library_flags(),
    }


def capture_prospective_reveal(
    *,
    authority_root: Path,
    packet_content_hash: str,
    fetcher: Fetcher | None = None,
    clock: Clock | None = None,
    existing_outcomes: tuple[OutcomeObservation, ...] = (),
) -> dict[str, Any]:
    """Owner one-shot reveal after guard. No settlement write; uses admit_outcome."""

    fetch = fetcher or default_fetcher
    now_fn = clock or default_clock
    root = resolve_authority_root(authority_root)
    packet = load_packet(root, packet_content_hash)
    host_now = now_fn()
    if host_now.tzinfo is None or host_now.utcoffset() is None:
        raise ProspectiveSourceError("HOST_TIME_NOT_AWARE", "clock must be aware")
    host_utc = host_now.astimezone(UTC)
    guard = _parse_aware(packet["target_guard_open_time"], "target_guard_open_time")
    if host_utc < guard:
        raise ProspectiveSourceError(
            "REVEAL_BEFORE_GUARD_OPEN",
            f"host={_iso_z(host_utc)} guard={_iso_z(guard)}",
        )

    point_url = POINT_TEMPLATE.format(expect=packet["target_expect"])
    point_resp = fetch(point_url)
    _require_http_ok(point_resp, "point_reveal")
    _assert_exact_url(point_resp.url, point_url, "point_reveal")
    http_date = _http_date_from_headers(point_resp.headers)
    if http_date is None:
        raise ProspectiveSourceError("HTTP_DATE_REQUIRED", "reveal point response")
    if abs(http_date - host_utc) > MAX_HOST_HTTP_SKEW:
        raise ProspectiveSourceError("HOST_HTTP_DATE_SKEW", "reveal clock skew")
    cas = write_raw_bytes_cas(root, point_resp.body)
    payload = parse_point_payload(point_resp.body)
    row = point_result_row(payload)
    if row.expect != packet["target_expect"]:
        raise ProspectiveSourceError(
            "REVEAL_EXPECT_MISMATCH",
            f"point={row.expect} packet={packet['target_expect']}",
        )
    assert row.open_code is not None
    # Source openTime must be >= guard and match target day-of-year.
    if row.open_time.astimezone(UTC) < guard:
        raise ProspectiveSourceError(
            "REVEAL_OPEN_BEFORE_GUARD",
            f"openTime={_iso_z(row.open_time.astimezone(UTC))} guard={_iso_z(guard)}",
        )
    validate_expect_matches_open_date(row.expect, row.open_time)
    special = row.open_code[-1]

    raw_ref = _capture_ref(role="point_reveal", response=point_resp, cas=cas)
    outcome_ref = f"outcome.macaujc2.expect.{packet['target_expect']}.sha256:{cas['sha256'][:16]}"
    # verified is derived from endpoint/result validation — not a caller-selected flag.
    verified = (
        point_resp.url == point_url
        and point_resp.status == 200
        and row.open_code is not None
        and len(row.open_code) == 7
        and len(set(row.open_code)) == 7
    )
    outcome = OutcomeObservation(
        outcome_ref=outcome_ref,
        source_ref=SOURCE_ID,
        target_ref=str(packet["target_ref"]),
        actual_special_number=special,
        observed_at=host_utc,
        verified=verified,
        result_hash=None,
    ).with_hash()

    admission = admit_outcome(existing_outcomes, outcome)
    admission_status: Literal["ACCEPTED", "DUPLICATE", "CONFLICT", "QUARANTINED"] = admission.status

    # Durable conflict/duplicate index from sealed history — no overwrite of differing reveal.
    reveal_body = {
        "schema_version": "xinao.prospective_reveal_capture.v1",
        "target_ref": packet["target_ref"],
        "target_expect": packet["target_expect"],
        "packet_content_hash": packet["content_hash"],
        "contract_sha256": packet["contract"]["contract_sha256"],
        "source_id": SOURCE_ID,
        "raw": raw_ref,
        "open_code": list(row.open_code),
        "actual_special_number": special,
        "outcome": outcome.model_dump(mode="json"),
        "admission_status": admission_status,
        "conflicting_outcome_refs": list(admission.conflicting_outcome_refs),
        "completion_claim_allowed": False,
        "real_money_authorized": False,
        "settlement_written": False,
    }
    reveal_hash = canonical_sha256(reveal_body)
    reveal_body["content_hash"] = reveal_hash
    reveal_raw = (
        json.dumps(reveal_body, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    rpath = reveal_object_path(root, reveal_hash)
    written = _write_exclusive_bytes(rpath, reveal_raw)

    idx = resolve_authority_root(root) / "index" / "reveal" / f"{packet['target_expect']}.json"
    idx_payload = {
        "target_expect": packet["target_expect"],
        "reveal_content_hash": reveal_hash,
        "outcome_ref": outcome.outcome_ref,
        "result_hash": outcome.result_hash,
        "admission_status": admission_status,
    }
    if idx.is_file() and not idx.is_symlink():
        try:
            existing_idx = parse_json_strict(idx.read_bytes(), reason="REVEAL_INDEX_JSON_INVALID")
        except ProspectiveSourceError:
            raise ProspectiveSourceError(
                "REVEAL_TARGET_CONFLICT",
                f"target {packet['target_expect']} has unreadable sealed reveal index",
            ) from None
        if not isinstance(existing_idx, dict):
            raise ProspectiveSourceError("REVEAL_TARGET_CONFLICT", "index not object")
        # Durable history: same result_hash is duplicate OK; different is conflict (no overwrite).
        if existing_idx.get("result_hash") != outcome.result_hash:
            raise ProspectiveSourceError(
                "REVEAL_TARGET_CONFLICT",
                f"target {packet['target_expect']} already has a different reveal",
            )
        # Same sealed outcome identity — do not rewrite index; surface duplicate honestly.
        return {
            "ok": True,
            "reveal": reveal_body,
            "reveal_content_hash": reveal_hash,
            "reveal_path": str(rpath),
            "outcome": outcome.model_dump(mode="json"),
            "admission_status": (
                "DUPLICATE" if admission_status in {"ACCEPTED", "DUPLICATE"} else admission_status
            ),
            "bytes_written": written,
            "settlement_written": False,
            "reveal_index_reused": True,
            **_honest_library_flags(),
        }
    idx_body = (
        json.dumps(idx_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _write_exclusive_bytes(idx, idx_body)

    return {
        "ok": True,
        "reveal": reveal_body,
        "reveal_content_hash": reveal_hash,
        "reveal_path": str(rpath),
        "outcome": outcome.model_dump(mode="json"),
        "admission_status": admission_status,
        "bytes_written": written,
        "settlement_written": False,
        **_honest_library_flags(),
    }


__all__ = [
    "ASIA_SHANGHAI",
    "BINDING_SCHEMA",
    "CANONICAL_SITE",
    "CLOCK_TRUST_GRADE",
    "HISTORY_YEAR_TEMPLATE",
    "PACKET_MARKER",
    "POINT_TEMPLATE",
    "SOURCE_ID",
    "UNSUPPORTED_LATEST_PATH",
    "Clock",
    "FetchResponse",
    "Fetcher",
    "ProspectiveSourceError",
    "ResultRow",
    "build_source_authority_binding",
    "capture_prospective_reveal",
    "capture_prospective_target_authority",
    "default_clock",
    "default_fetcher",
    "discover_same_origin_app_js",
    "expect_to_local_date",
    "extract_product_schedule",
    "is_leap_year",
    "is_live_macaujc2_target",
    "load_packet",
    "next_expect_after",
    "parse_expect",
    "parse_history_max_expect",
    "parse_json_strict",
    "parse_point_payload",
    "point_is_null",
    "point_result_row",
    "raw_sha256",
    "reject_outcome_material",
    "reject_unsupported_latest_authority",
    "validate_expect_matches_open_date",
    "validate_source_authority_binding",
    "verify_disposition_times_against_packet",
    "verify_macaujc2_contract_bytes",
]
