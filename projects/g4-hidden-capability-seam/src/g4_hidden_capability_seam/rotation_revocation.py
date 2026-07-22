"""Rotation/revocation registry backed by the same sqlite AtomicSeamState."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .atomic_state import AtomicSeamState
from .canonical import write_json


class RotationRevocationRegistry:
    def __init__(self, path: str | Path, *, state: AtomicSeamState | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if state is not None:
            self._state = state
            self.db_path = state.db_path
        else:
            if str(self.path).endswith(".json"):
                self.db_path = self.path.with_name(self.path.stem + ".sqlite3")
            else:
                self.db_path = Path(str(self.path) + ".sqlite3")
            self._state = AtomicSeamState(self.db_path)
        self._export()

    def _export(self) -> None:
        st = self._state.status()
        # Compact JSON projection for object export / human inspection
        write_json(
            self.path if str(self.path).endswith(".json") else self.path.with_suffix(".json"),
            {
                "schema_version": "xinao.g4.hidden_capability_seam.rotation_revocation_registry.v1",
                "active_count": st["active_suite_count"],
                "revoked_count": st["revoked_suite_count"],
                "cas_backend": "sqlite3_delete_journal_begin_immediate",
                "db_path": str(self._state.db_path),
                "authority": False,
                "synthetic_only": True,
            },
        )

    def register_identity(
        self,
        *,
        identity_kind: str,
        public_label: str,
        commitment_inputs: dict[str, Any],
        suite_identity_sha256: str | None = None,
        suite_envelope: dict[str, Any] | None = None,
        exposure_ledger_path: str | Path | None = None,
        exposure_seal_path: str | Path | None = None,
        rotated_from: str | None = None,
    ) -> dict[str, Any]:
        out = self._state.register_identity(
            identity_kind=identity_kind,
            public_label=public_label,
            commitment_inputs=commitment_inputs,
            suite_identity_sha256=suite_identity_sha256,
            suite_envelope=suite_envelope,
            exposure_ledger_path=exposure_ledger_path,
            exposure_seal_path=exposure_seal_path,
            rotated_from=rotated_from,
        )
        self._export()
        return out

    def rotate(
        self,
        *,
        old_identity_sha256: str,
        public_label: str,
        commitment_inputs: dict[str, Any],
        identity_kind: str,
        new_suite_identity_sha256: str | None = None,
        new_suite_envelope: dict[str, Any] | None = None,
        exposure_ledger_path: str | Path | None = None,
        exposure_seal_path: str | Path | None = None,
    ) -> dict[str, Any]:
        out = self._state.rotate(
            old_identity_sha256=old_identity_sha256,
            public_label=public_label,
            commitment_inputs=commitment_inputs,
            identity_kind=identity_kind,
            new_suite_identity_sha256=new_suite_identity_sha256,
            new_suite_envelope=new_suite_envelope,
            exposure_ledger_path=exposure_ledger_path,
            exposure_seal_path=exposure_seal_path,
        )
        self._export()
        return out

    def revoke(self, *, identity_sha256: str, reason: str) -> dict[str, Any]:
        out = self._state.revoke(identity_sha256=identity_sha256, reason=reason)
        self._export()
        return out

    def may_start_run(self, *, suite_identity_sha256: str) -> dict[str, Any]:
        return self._state.may_start_run(suite_identity_sha256=suite_identity_sha256)

    @property
    def state(self) -> AtomicSeamState:
        return self._state
