"""Temporarily reserve account quota slots to cap independent Sol research turns.

The holder never terminates an active turn.  It waits for natural release, then
claims enough of the four durable account slots to enforce the requested cap.
Late-fusion/root-main is outside this quota and is neither launched nor woken.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.xinao_perpetual_world_compute.controller import (
    DEFAULT_WORLD_TURN_QUOTA_ROOT,
    WORLD_TURN_QUOTA_LEASE_SCHEMA,
    _release_byte_lock,
    _try_acquire_byte_lock,
    atomic_write_bytes,
    atomic_write_json,
    is_process_alive,
    now_iso,
    read_json_object,
    validate_account_slot,
)


def _append(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _pid_alive(record: dict[str, Any]) -> bool:
    for key in ("child_pid", "controller_pid"):
        value = record.get(key)
        if isinstance(value, int) and value > 0 and is_process_alive(value):
            return True
    return False


def _archive(path: Path, record: dict[str, Any]) -> None:
    lease_id = str(record.get("lease_id", "")).strip()
    if not lease_id:
        raise RuntimeError(f"QUOTA_HISTORY_IDENTITY_INVALID:{path}")
    raw = path.read_bytes()
    history = path.parent / "history" / f"{lease_id}.json"
    if history.exists():
        if history.read_bytes() != raw:
            raise RuntimeError(f"QUOTA_HISTORY_COLLISION:{history}")
        return
    atomic_write_bytes(history, raw)


class AccountResearchCap:
    def __init__(
        self,
        *,
        account_slot: str,
        desired_cap: int,
        physical_slots: int,
        state_dir: Path,
        poll_seconds: float,
        quota_root: Path = DEFAULT_WORLD_TURN_QUOTA_ROOT,
    ) -> None:
        self.account_slot = validate_account_slot(account_slot)
        if desired_cap < 1 or desired_cap >= physical_slots:
            raise ValueError("desired cap must be positive and below physical slots")
        if poll_seconds <= 0:
            raise ValueError("poll seconds must be positive")
        self.desired_cap = desired_cap
        self.physical_slots = physical_slots
        self.required_throttles = physical_slots - desired_cap
        self.state_dir = state_dir.resolve(strict=False)
        self.poll_seconds = poll_seconds
        self.account_root = quota_root.resolve(strict=False) / self.account_slot
        self.guard_path = self.account_root / "admission.lock"
        self.record_paths = tuple(
            self.account_root / f"world-turn-{index:02d}.json"
            for index in range(1, physical_slots + 1)
        )
        self.log_path = self.state_dir / "events.jsonl"
        self.policy_path = self.state_dir / "policy.json"
        self.owned: dict[Path, str] = {}
        self.stop_requested = False
        self.run_id = f"operator-{self.account_slot.casefold()}-research-cap{desired_cap}-temporary"

    def request_stop(self, _signum: int, _frame: Any) -> None:
        self.stop_requested = True

    def _read_valid_record(self, path: Path, slot: int) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        record = read_json_object(path)
        if (
            record.get("schema") != WORLD_TURN_QUOTA_LEASE_SCHEMA
            or record.get("account_slot") != self.account_slot
            or int(record.get("slot", -1)) != slot
        ):
            raise RuntimeError(f"QUOTA_RECORD_IDENTITY_INVALID:{path}")
        return record

    def _snapshot(self) -> tuple[list[dict[str, Any]], list[Path]]:
        active_throttles: list[dict[str, Any]] = []
        available: list[Path] = []
        for slot, path in enumerate(self.record_paths, 1):
            record = self._read_valid_record(path, slot)
            if record is None:
                available.append(path)
                continue
            status = str(record.get("status", ""))
            if status == "BOUND" and record.get("operator_throttle") is True and _pid_alive(record):
                active_throttles.append(record)
                continue
            if status == "RELEASED" or (status == "BOUND" and not _pid_alive(record)):
                available.append(path)
                continue
            if status not in {"BOUND", "RESERVED"}:
                raise RuntimeError(f"QUOTA_RECORD_STATUS_INVALID:{path}:{status}")
        return active_throttles, available

    def _claim_one(self) -> bool:
        guard = _try_acquire_byte_lock(self.guard_path)
        if guard is None:
            return False
        try:
            active_throttles, available = self._snapshot()
            if len(active_throttles) >= self.required_throttles or not available:
                return False
            path = available[0]
            slot = self.record_paths.index(path) + 1
            prior = self._read_valid_record(path, slot)
            if prior is not None:
                _archive(path, prior)
            lease_id = f"quota-throttle-{uuid.uuid4().hex}"
            lease = {
                "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                "lease_id": lease_id,
                "counted": True,
                "status": "BOUND",
                "account_slot": self.account_slot,
                "slot": slot,
                "limit": self.physical_slots,
                "run_id": self.run_id,
                "lineage_id": f"temporary-account-research-cap{self.desired_cap}",
                "workspace": str(self.state_dir),
                "controller_pid": os.getpid(),
                "child_pid": os.getpid(),
                "reserved_at": now_iso(),
                "bound_at": now_iso(),
                "released_at": None,
                "operator_throttle": True,
                "desired_account_world_turn_cap": self.desired_cap,
                "late_fusion_root_counted": False,
                "late_fusion_root_compute_allowed": False,
                "temporary": True,
                "policy_path": str(self.policy_path),
            }
            atomic_write_json(path, lease)
            self.owned[path] = lease_id
            _append(
                self.log_path,
                {
                    "schema": "xinao.s.account-research-cap.v1",
                    "status": "THROTTLE_SLOT_CLAIMED",
                    "captured_at": now_iso(),
                    "account_slot": self.account_slot,
                    "slot": slot,
                    "lease_id": lease_id,
                    "desired_cap": self.desired_cap,
                },
            )
            return True
        finally:
            _release_byte_lock(guard)

    def _publish(self, status: str) -> dict[str, Any]:
        guard = _try_acquire_byte_lock(self.guard_path)
        if guard is None:
            return {}
        try:
            active_throttles, _ = self._snapshot()
            active_research: list[dict[str, Any]] = []
            for slot, path in enumerate(self.record_paths, 1):
                record = self._read_valid_record(path, slot)
                if (
                    record is not None
                    and record.get("status") == "BOUND"
                    and record.get("operator_throttle") is not True
                    and _pid_alive(record)
                ):
                    active_research.append(
                        {
                            "slot": slot,
                            "run_id": record.get("run_id"),
                            "lineage_id": record.get("lineage_id"),
                        }
                    )
            value = {
                "schema": "xinao.s.account-research-cap.v1",
                "status": status,
                "updated_at": now_iso(),
                "pid": os.getpid(),
                "account_slot": self.account_slot,
                "physical_slots": self.physical_slots,
                "simultaneous_independent_world_turn_cap": self.desired_cap,
                "active_throttle_slots": sorted(int(item["slot"]) for item in active_throttles),
                "required_throttle_count": self.required_throttles,
                "active_research": active_research,
                "natural_drain_only": True,
                "hard_kill_allowed": False,
                "late_fusion_root_counted": False,
                "late_fusion_root_compute_allowed": False,
                "provisional": True,
                "completion_claim_allowed": False,
            }
            atomic_write_json(self.policy_path, value)
            return value
        finally:
            _release_byte_lock(guard)

    def _release_owned(self) -> None:
        for path, lease_id in list(self.owned.items()):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                guard = _try_acquire_byte_lock(self.guard_path)
                if guard is None:
                    time.sleep(self.poll_seconds)
                    continue
                try:
                    current = read_json_object(path)
                    if current.get("lease_id") != lease_id:
                        break
                    current.update({"status": "RELEASED", "released_at": now_iso()})
                    atomic_write_json(path, current)
                    break
                finally:
                    _release_byte_lock(guard)

    def run(self) -> int:
        if self.state_dir.exists():
            raise RuntimeError(f"CAP_STATE_ALREADY_EXISTS:{self.state_dir}")
        self.state_dir.mkdir(parents=True)
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)
        _append(
            self.log_path,
            {
                "schema": "xinao.s.account-research-cap.v1",
                "status": "STARTED",
                "started_at": now_iso(),
                "pid": os.getpid(),
                "account_slot": self.account_slot,
                "physical_slots": self.physical_slots,
                "desired_cap": self.desired_cap,
                "natural_drain_only": True,
                "late_fusion_root_compute_allowed": False,
            },
        )
        last_status = ""
        try:
            while not self.stop_requested:
                while self._claim_one():
                    pass
                state = self._publish(last_status or "WAITING_FOR_NATURAL_DRAIN")
                if state:
                    active = len(state["active_throttle_slots"])
                    status = (
                        "ACTIVE"
                        if active >= self.required_throttles
                        else "WAITING_FOR_NATURAL_DRAIN"
                    )
                    if status != last_status:
                        state = self._publish(status)
                        _append(self.log_path, state)
                        last_status = status
                time.sleep(self.poll_seconds)
        finally:
            self._release_owned()
            _append(self.log_path, {"status": "RELEASED_OWNED_SLOTS", "stopped_at": now_iso()})
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-slot", required=True, choices=("A", "C"))
    parser.add_argument("--desired-cap", required=True, type=int)
    parser.add_argument("--physical-slots", type=int, default=4)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--poll-seconds", type=float, default=0.025)
    parser.add_argument("--quota-root", type=Path, default=DEFAULT_WORLD_TURN_QUOTA_ROOT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return AccountResearchCap(
        account_slot=args.account_slot,
        desired_cap=args.desired_cap,
        physical_slots=args.physical_slots,
        state_dir=args.state_dir,
        poll_seconds=args.poll_seconds,
        quota_root=args.quota_root,
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
