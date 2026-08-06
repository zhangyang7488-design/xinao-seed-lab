"""Fail-closed byte-snapshot preflight before rendering outcome-bearing text.

This module is deliberately narrow.  It recognizes configured literal period
identifiers and an explicit post-cutoff-consumption marker.  It does not infer
scientific value, prove arbitrary prose safe, or grant authority.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, BinaryIO

PREFLIGHT_SCHEMA_VERSION = "xinao.outcome_boundary_preflight.v1"
DEFAULT_MAX_BYTES = 4 * 1024 * 1024

_DECLARED_CONSUMPTION = re.compile(
    r"(?i)(?<![A-Za-z0-9])"
    r"[\"']?post[ _-]*cutoff[ _-]*outcomes?[ _-]*consumed[\"']?"
    r"\s*[:=]\s*(?:true|1|yes)\b"
)


class OutcomeBoundaryPreflightError(ValueError):
    """The requested preflight itself is invalid or cannot identify a file."""


def _validate_policy(cutoff_period: int, max_bytes: int) -> tuple[int, int, int]:
    if isinstance(cutoff_period, bool) or not isinstance(cutoff_period, int):
        raise OutcomeBoundaryPreflightError("cutoff_period must be an integer")
    if cutoff_period <= 0:
        raise OutcomeBoundaryPreflightError("cutoff_period must be positive")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise OutcomeBoundaryPreflightError("max_bytes must be a positive integer")
    width = len(str(cutoff_period))
    return cutoff_period, width, max_bytes


def _read_snapshot(path: Path) -> tuple[Path, bytes]:
    requested = Path(path)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise OutcomeBoundaryPreflightError("source path is unavailable") from exc
    if not resolved.is_file():
        raise OutcomeBoundaryPreflightError("source path is not a file")
    try:
        return resolved, resolved.read_bytes()
    except OSError as exc:
        raise OutcomeBoundaryPreflightError("source file cannot be read") from exc


def _period_pattern(width: int) -> re.Pattern[str]:
    # Alphanumeric guards prevent a run inside a digest or identifier from
    # masquerading as a standalone period.  Separators such as `_` and `=`
    # intentionally remain valid boundaries for ordinary period fields.
    return re.compile(rf"(?<![A-Za-z0-9])([0-9]{{{width}}})(?![A-Za-z0-9])")


def _report_for_snapshot(
    *,
    resolved: Path,
    raw: bytes,
    cutoff_period: int,
    max_bytes: int,
) -> dict[str, Any]:
    cutoff_period, width, max_bytes = _validate_policy(cutoff_period, max_bytes)
    reasons: list[str] = []
    potential_match_count = 0

    if len(raw) > max_bytes:
        reasons.append("SOURCE_EXCEEDS_MAX_BYTES")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            reasons.append("SOURCE_NOT_UTF8_TEXT")
        else:
            if "\x00" in text:
                reasons.append("SOURCE_NOT_UTF8_TEXT")
            else:
                post_cutoff_periods = sum(
                    1
                    for match in _period_pattern(width).finditer(text)
                    if int(match.group(1)) >= cutoff_period
                )
                declared_consumption = len(_DECLARED_CONSUMPTION.findall(text))
                if declared_consumption:
                    reasons.append("DECLARED_POST_CUTOFF_CONSUMPTION")
                    potential_match_count += declared_consumption
                if post_cutoff_periods:
                    reasons.append("POST_CUTOFF_PERIOD_REFERENCE")
                    potential_match_count += post_cutoff_periods

    reasons = sorted(set(reasons))
    allowed = not reasons
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "authority": False,
        "completion_claim_allowed": False,
        "source_path": str(resolved),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": len(raw),
        "cutoff_period": cutoff_period,
        "period_width": width,
        "max_bytes": max_bytes,
        "disposition": "ALLOW_SEMANTIC_READ" if allowed else "DENY_SEMANTIC_READ",
        "semantic_read_allowed": allowed,
        "reason_codes": reasons,
        "potential_match_count": potential_match_count,
        "claim_scope": "literal_period_and_explicit_consumption_marker_only",
        "false_green_deny": (
            "An ALLOW result only means this exact byte snapshot contains no configured literal "
            "post-cutoff period or explicit consumption marker. It does not prove arbitrary "
            "natural-language, encoded, encrypted, or externally referenced content safe; it "
            "does not select research, authorize reveal, or prove parent completion."
        ),
    }


def inspect_outcome_boundary(
    path: Path,
    *,
    cutoff_period: int,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Return only non-content metadata and the narrow mechanical disposition."""

    resolved, raw = _read_snapshot(path)
    return _report_for_snapshot(
        resolved=resolved,
        raw=raw,
        cutoff_period=cutoff_period,
        max_bytes=max_bytes,
    )


def emit_if_outcome_boundary_allows(
    path: Path,
    *,
    cutoff_period: int,
    stream: BinaryIO,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Write the exact inspected bytes only when that same snapshot is allowed."""

    resolved, raw = _read_snapshot(path)
    report = _report_for_snapshot(
        resolved=resolved,
        raw=raw,
        cutoff_period=cutoff_period,
        max_bytes=max_bytes,
    )
    if report["semantic_read_allowed"] is True:
        stream.write(raw)
    return report


__all__ = [
    "DEFAULT_MAX_BYTES",
    "OutcomeBoundaryPreflightError",
    "emit_if_outcome_boundary_allows",
    "inspect_outcome_boundary",
]
