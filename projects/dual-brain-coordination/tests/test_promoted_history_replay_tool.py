from __future__ import annotations

from adapters.temporal.replay_promoted_histories import (
    canonical_json_bytes,
    history_set_sha256,
)


def test_canonical_json_bytes_are_key_order_independent() -> None:
    assert canonical_json_bytes({"b": 2, "a": 1}) == canonical_json_bytes({"a": 1, "b": 2})


def test_history_set_hash_is_order_independent_and_identity_bounded() -> None:
    first = {
        "workflow_id": "wf-b",
        "run_id": "run-2",
        "history_sha256": "B" * 64,
        "status": "COMPLETED",
    }
    second = {
        "workflow_id": "wf-a",
        "run_id": "run-1",
        "history_sha256": "A" * 64,
        "status": "FAILED",
    }
    expected = history_set_sha256([first, second])
    assert history_set_sha256([second, first]) == expected

    second_with_non_identity_change = {**second, "status": "COMPLETED"}
    assert history_set_sha256([first, second_with_non_identity_change]) == expected

    second_with_history_change = {**second, "history_sha256": "C" * 64}
    assert history_set_sha256([first, second_with_history_change]) != expected
