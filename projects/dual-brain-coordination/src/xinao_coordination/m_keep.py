"""M-KEEP observation capability: callable, default-off, and side-effect free.

This module deliberately has no timer, subprocess, input injection, recovery,
or persistence surface.  It classifies one caller-supplied snapshot and returns
``NEEDS_USER`` whenever exact owned-session recovery cannot be proven.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .module_config import load_module_config, resolve_module_config

POLICY_ID = "xinao.m_keep.observe_only.v1"
OBSERVATION_STATES = frozenset(
    {"LIVENESS", "READINESS", "PROGRESS", "WAITING_INPUT", "READY_IDLE", "CAPACITY_ERROR"}
)
REQUIRED_BINDING_FIELDS = (
    "session_id",
    "generation",
    "pid",
    "process_created_at",
    "executable_path",
    "command_line_marker",
    "logon_session",
    "parent_pid",
)
PACKAGED_CONFIG = Path(__file__).resolve().parent / "configs" / "m_keep.toml"
DEFAULT_CONFIG = resolve_module_config("m_keep")


def m_keep_policy(config_path: str | Path | None = None) -> dict[str, object]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    loaded, provenance = load_module_config("m_keep") if config_path is None else ({}, {})
    if config_path is not None and path.is_file():
        import tomllib

        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
        provenance = {"path": str(path), "exists": True}
    raw = loaded.get("m_keep", {}) if isinstance(loaded, dict) else {}
    return {
        "policy_id": POLICY_ID,
        "capability_installed": True,
        "enabled": raw.get("enabled") is True,
        "observe_only": True,
        "sample_interval_seconds": int(raw.get("sample_interval_seconds") or 60),
        # No native owned-session recovery adapter is installed.  A zero cap is
        # explicit evidence that this observe-only module can never restart a
        # session, even when a caller reports a capacity error.
        "max_restart_attempts": int(raw.get("max_restart_attempts") or 0),
        "timer": False,
        "daemon": False,
        "notify": False,
        "recover": False,
        "tui_attached": False,
        "config_path": str(path),
        "config_provenance": provenance,
    }


def _classify(snapshot: dict[str, Any]) -> str:
    if snapshot.get("capacity_error") is True:
        return "CAPACITY_ERROR"
    if snapshot.get("waiting_input") is True:
        return "WAITING_INPUT"
    if snapshot.get("progress") is True:
        return "PROGRESS"
    if snapshot.get("ready") is True and snapshot.get("active_turn") is not True:
        return "READY_IDLE"
    if snapshot.get("ready") is True:
        return "READINESS"
    return "LIVENESS"


def observe_snapshot(
    snapshot: dict[str, Any],
    *,
    binding: dict[str, Any] | None = None,
    expected_binding: dict[str, Any] | None = None,
    stop_active: bool = False,
    pause_active: bool = False,
    config_path: str | Path | None = None,
) -> dict[str, object]:
    """Classify one snapshot without observing or changing a live process."""
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be an object")
    policy = m_keep_policy(config_path)
    binding_data = binding if isinstance(binding, dict) else {}
    expected_data = expected_binding if isinstance(expected_binding, dict) else {}
    complete_binding = bool(binding_data) and all(
        binding_data.get(field) not in (None, "") for field in REQUIRED_BINDING_FIELDS
    )
    identity_mismatches = [
        field
        for field in REQUIRED_BINDING_FIELDS
        if expected_data and binding_data.get(field) != expected_data.get(field)
    ]
    identity_verified = complete_binding and not identity_mismatches
    observation = _classify(snapshot)
    restart_count = max(0, int(snapshot.get("restart_count") or 0))
    restart_cap = max(0, int(policy["max_restart_attempts"]))
    restart_cap_reached = restart_count >= restart_cap
    return {
        "ok": True,
        "action": "mkeep.observe",
        "observation": observation,
        "observation_valid": observation in OBSERVATION_STATES,
        "policy": policy,
        "stop_active": bool(stop_active),
        "pause_active": bool(pause_active),
        "identity_verified": identity_verified,
        "identity_mismatches": identity_mismatches,
        "managed_session": bool(snapshot.get("managed_session")),
        "restart_count": restart_count,
        "restart_cap": restart_cap,
        "restart_cap_reached": restart_cap_reached,
        "next_action": "NEEDS_USER",
        "recovery_attempted": False,
        "side_effects": {
            "subprocess": False,
            "window": False,
            "focus": False,
            "input": False,
            "persistence": False,
            "session_resume": False,
        },
    }
