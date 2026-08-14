from __future__ import annotations

import json
import os
from pathlib import Path

import scripts.hold_xinao_account_research_cap as cap_module
from scripts.hold_xinao_account_research_cap import AccountResearchCap
from services.xinao_perpetual_world_compute.controller import (
    WORLD_TURN_QUOTA_LEASE_SCHEMA,
)


def _make_cap(tmp_path: Path, *, desired_cap: int = 2) -> AccountResearchCap:
    return AccountResearchCap(
        account_slot="A",
        desired_cap=desired_cap,
        physical_slots=4,
        state_dir=tmp_path / "state",
        poll_seconds=0.001,
        quota_root=tmp_path / "quota",
    )


def _write_bound_record(
    path: Path,
    *,
    slot: int,
    lease_id: str,
    operator_throttle: bool,
    pid: int = 424_242,
) -> bytes:
    value = {
        "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
        "lease_id": lease_id,
        "counted": True,
        "status": "BOUND",
        "account_slot": "A",
        "slot": slot,
        "limit": 4,
        "run_id": f"run-{lease_id}",
        "lineage_id": f"lineage-{lease_id}",
        "workspace": "isolated-test-workspace",
        "controller_pid": pid,
        "child_pid": pid,
        "reserved_at": "2026-08-14T00:00:00Z",
        "bound_at": "2026-08-14T00:00:00Z",
        "released_at": None,
        "operator_throttle": operator_throttle,
    }
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_claims_exactly_physical_slots_minus_desired_cap(tmp_path: Path) -> None:
    cap = _make_cap(tmp_path)

    assert cap._claim_one() is True
    assert cap._claim_one() is True
    assert cap._claim_one() is False

    bound = [_read(path) for path in cap.record_paths if path.is_file()]
    assert len(bound) == cap.physical_slots - cap.desired_cap == 2
    assert all(record["status"] == "BOUND" for record in bound)
    assert all(record["operator_throttle"] is True for record in bound)
    assert set(cap.owned) == set(cap.record_paths[:2])


def test_natural_drain_preserves_live_research_and_only_uses_free_slots(
    tmp_path: Path, monkeypatch
) -> None:
    cap = _make_cap(tmp_path)
    research_path = cap.record_paths[0]
    research_raw = _write_bound_record(
        research_path,
        slot=1,
        lease_id="live-research",
        operator_throttle=False,
    )
    monkeypatch.setattr(
        cap_module,
        "is_process_alive",
        lambda pid: pid in {424_242, os.getpid()},
    )

    while cap._claim_one():
        pass

    assert research_path.read_bytes() == research_raw
    assert _read(research_path)["status"] == "BOUND"
    assert research_path not in cap.owned
    assert set(cap.owned) == {cap.record_paths[1], cap.record_paths[2]}
    assert not cap.record_paths[3].exists()


def test_release_owned_does_not_release_foreign_throttle(
    tmp_path: Path, monkeypatch
) -> None:
    cap = _make_cap(tmp_path)
    foreign_path = cap.record_paths[0]
    foreign_raw = _write_bound_record(
        foreign_path,
        slot=1,
        lease_id="foreign-throttle",
        operator_throttle=True,
    )
    monkeypatch.setattr(
        cap_module,
        "is_process_alive",
        lambda pid: pid in {424_242, os.getpid()},
    )

    assert cap._claim_one() is True
    owned_path = next(iter(cap.owned))
    owned_lease_id = cap.owned[owned_path]

    cap._release_owned()

    assert foreign_path.read_bytes() == foreign_raw
    assert _read(foreign_path)["status"] == "BOUND"
    released = _read(owned_path)
    assert released["lease_id"] == owned_lease_id
    assert released["status"] == "RELEASED"
    assert released["released_at"]


def test_policy_excludes_root_main_from_counting_and_compute(tmp_path: Path) -> None:
    cap = _make_cap(tmp_path)
    assert cap._claim_one() is True
    assert cap._claim_one() is True

    policy = cap._publish("ACTIVE")

    assert policy["simultaneous_independent_world_turn_cap"] == 2
    assert policy["required_throttle_count"] == 2
    assert policy["late_fusion_root_counted"] is False
    assert policy["late_fusion_root_compute_allowed"] is False
    assert _read(cap.policy_path) == policy
