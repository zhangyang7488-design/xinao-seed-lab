from __future__ import annotations

from services.agent_runtime.quota_capacity_adapter import capacity_by_provider_from_quota


def test_live_quota_shape_maps_through_replaceable_provider_bindings() -> None:
    quota = {
        "codex": {
            "buckets": [
                {
                    "id": "codex",
                    "primary": {
                        "remainingPercent": 21,
                        "resetAt": "2026-07-23T09:14:29Z",
                    },
                },
                {
                    "id": "codex_spark",
                    "primary": {"remainingPercent": 100, "resetAt": None},
                },
            ]
        },
        "grok": {
            "remainingPercent": 96,
            "resetAt": "2026-07-19T02:52:23Z",
        },
    }
    bindings = {
        "codex_subagent": {"source_key": "codex", "bucket_id": "codex"},
        "grok_worker": {"source_key": "grok"},
    }

    assert capacity_by_provider_from_quota(quota, bindings) == {
        "codex_subagent": {
            "remaining_percent": 21,
            "reset_at": "2026-07-23T09:14:29Z",
        },
        "grok_worker": {
            "remaining_percent": 96,
            "reset_at": "2026-07-19T02:52:23Z",
        },
    }


def test_missing_or_unbound_source_is_advisory_not_a_dispatch_gate() -> None:
    assert capacity_by_provider_from_quota(
        {"grok": {"remainingPercent": 96}},
        {
            "future_worker": {"source_key": "future"},
            "grok_worker": {"source_key": "grok"},
        },
    ) == {
        "grok_worker": {"remaining_percent": 96, "reset_at": None},
    }
