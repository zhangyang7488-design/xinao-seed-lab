"""Translate the canonical quota result into provider-agnostic capacity facts."""

from __future__ import annotations

from typing import Any, Mapping


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _quota_window(source: Mapping[str, Any], *, bucket_id: str) -> Mapping[str, Any] | None:
    if bucket_id:
        buckets = source.get("buckets")
        if not isinstance(buckets, list):
            return None
        matches = [
            bucket
            for bucket in buckets
            if isinstance(bucket, Mapping) and str(bucket.get("id") or "") == bucket_id
        ]
        if len(matches) != 1:
            return None
        selected = matches[0]
    else:
        selected = source
    primary = selected.get("primary")
    return primary if isinstance(primary, Mapping) else selected


def capacity_by_provider_from_quota(
    quota_result: Mapping[str, Any],
    binding_by_provider: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Map quota sources to provider identities using declarative bindings.

    A binding contains ``source_key`` and, for multi-bucket sources, an
    optional ``bucket_id``.  Adding or replacing a worker changes policy data,
    not this adapter.
    """

    if not isinstance(quota_result, Mapping):
        raise TypeError("quota_result must be an object")
    if not isinstance(binding_by_provider, Mapping):
        raise TypeError("binding_by_provider must be an object")

    capacity: dict[str, dict[str, Any]] = {}
    for provider_id, raw_binding in sorted(binding_by_provider.items()):
        provider = _required_text(provider_id, field="provider_id")
        if not isinstance(raw_binding, Mapping):
            raise TypeError(f"quota binding for {provider!r} must be an object")
        source_key = _required_text(raw_binding.get("source_key"), field="source_key")
        bucket_id = str(raw_binding.get("bucket_id") or "").strip()
        source = quota_result.get(source_key)
        if not isinstance(source, Mapping):
            continue
        window = _quota_window(source, bucket_id=bucket_id)
        if window is None:
            continue
        remaining = window.get("remainingPercent", window.get("remaining_percent"))
        reset_at = window.get("resetAt", window.get("reset_at"))
        if remaining is None and reset_at in (None, ""):
            continue
        capacity[provider] = {
            "remaining_percent": remaining,
            "reset_at": reset_at,
        }
    return capacity
