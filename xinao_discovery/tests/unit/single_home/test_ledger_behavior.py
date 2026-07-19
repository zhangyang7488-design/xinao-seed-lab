"""Behavioral tests for single-home GlobalTrialLedger pure interface."""

from __future__ import annotations

import pytest

from xinao.single_home.errors import SingleHomeError
from xinao.single_home.global_trial_ledger import GlobalTrialLedger


def test_append_only_idempotent_register() -> None:
    led = GlobalTrialLedger()
    a = led.register(
        "wk-1",
        {"status": "REGISTERED", "family_id": "H03", "equivalence_cluster_id": "c1"},
    )
    b = led.register(
        "wk-1",
        {"status": "REGISTERED", "family_id": "H03", "equivalence_cluster_id": "c1"},
    )
    assert a["seq"] == b["seq"]


def test_duplicate_work_key_different_payload_rejected() -> None:
    led = GlobalTrialLedger()
    led.register("wk-1", {"status": "REGISTERED", "family_id": "H03"})
    with pytest.raises(SingleHomeError) as ei:
        led.register("wk-1", {"status": "FAILED", "family_id": "H03"})
    assert ei.value.code == "IDEMPOTENCE_CONFLICT"


def test_delete_rewrite_forbidden() -> None:
    led = GlobalTrialLedger()
    led.register("wk-1", {"status": "REGISTERED"})
    with pytest.raises(SingleHomeError) as ei:
        led.delete("wk-1")
    assert ei.value.code == "APPEND_ONLY"
    with pytest.raises(SingleHomeError) as ei2:
        led.rewrite("wk-1", {"status": "SUCCEEDED"})
    assert ei2.value.code == "APPEND_ONLY"


def test_failure_timeout_exported() -> None:
    led = GlobalTrialLedger()
    led.register("wk-1", {"status": "REGISTERED", "equivalence_cluster_id": "c1"})
    led.append_terminal("wk-1", "FAILED", failure_reason="boom")
    led.register("wk-2", {"status": "REGISTERED", "equivalence_cluster_id": "c2"})
    led.append_terminal("wk-2", "TIMEOUT")
    led.register("wk-3", {"status": "DISCARDED", "path_kind": "RANDOM"})
    exp = led.export_disclosure()
    assert exp["failed_or_timeout_paths"] >= 2
    assert exp["discarded_paths"] >= 1
    assert exp["valid_equivalence_clusters"] == 2
    assert exp["authoritative"] is False
    assert exp["no_durable_state"] is True


def test_silent_unregistered_trial() -> None:
    led = GlobalTrialLedger()
    led.register("wk-1", {"status": "REGISTERED"})
    with pytest.raises(SingleHomeError) as ei:
        led.assert_no_silent_path(["wk-1", "ghost"])
    assert ei.value.code == "SILENT_UNREGISTERED_TRIAL"


def test_terminal_without_register_forbidden() -> None:
    led = GlobalTrialLedger()
    with pytest.raises(SingleHomeError) as ei:
        led.append_terminal("ghost", "SUCCEEDED")
    assert ei.value.code == "UNREGISTERED"
