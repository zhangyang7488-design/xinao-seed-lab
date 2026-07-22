"""RunIdempotencyRegistry — thin facade over AtomicSeamState sqlite CAS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .atomic_state import AtomicSeamState


def _sqlite_path_for(path: Path) -> Path:
    path = Path(path)
    if path.suffix.lower() == ".sqlite3":
        return path
    if path.suffix.lower() == ".json":
        return path.with_name(path.stem + ".sqlite3")
    return Path(str(path) + ".sqlite3")


class RunIdempotencyRegistry:
    def __init__(
        self,
        path: str | Path,
        *,
        max_attempts: int = 3,
        state: AtomicSeamState | None = None,
    ) -> None:
        self.json_snapshot_path = Path(path)
        if self.json_snapshot_path.suffix.lower() != ".json":
            self.json_snapshot_path = (
                Path(str(path) + ".json") if path else Path("run_idempotency.json")
            )
            if Path(path).suffix.lower() == ".sqlite3":
                self.json_snapshot_path = Path(path).with_suffix(".json")
            elif Path(path).suffix == "":
                self.json_snapshot_path = Path(str(path) + ".json")
            else:
                self.json_snapshot_path = Path(path)
        self.db_path = _sqlite_path_for(Path(path) if state is None else state.db_path)
        self.max_attempts = max_attempts
        self._state = state or AtomicSeamState(self.db_path, max_attempts=max_attempts)

    @property
    def path(self) -> Path:
        return self.json_snapshot_path

    def claim_run(
        self,
        *,
        run_id: str,
        attempt_id: str,
        route_identity_sha256: str,
        suite_identity_sha256: str,
    ) -> dict[str, Any]:
        result = self._state.claim_run(
            run_id=run_id,
            attempt_id=attempt_id,
            route_identity_sha256=route_identity_sha256,
            suite_identity_sha256=suite_identity_sha256,
        )
        self._state.export_json_snapshot(self.json_snapshot_path)
        return result

    def mark_side_effect_started(self, *, run_id: str) -> dict[str, Any]:
        result = self._state.mark_side_effect_started(run_id=run_id)
        self._state.export_json_snapshot(self.json_snapshot_path)
        return result

    def mark_side_effect(self, *, run_id: str) -> dict[str, Any]:
        result = self._state.mark_side_effect(run_id=run_id)
        self._state.export_json_snapshot(self.json_snapshot_path)
        return result

    def status(self) -> dict[str, Any]:
        st = self._state.status()
        return {
            "schema_version": "xinao.g4.hidden_capability_seam.run_idempotency_registry.v1",
            "run_count": st["run_count"],
            "side_effect_count": st["side_effect_count"],
            "side_effect_started_count": st["side_effect_started_count"],
            "max_attempts": st["max_attempts"],
            "cas_backend": "sqlite3_delete_journal_begin_immediate",
            "db_path": st["db_path"],
            "authority": False,
        }

    @property
    def state(self) -> AtomicSeamState:
        return self._state
