from __future__ import annotations

from pathlib import Path

from xinao_coordination.m_keep import OBSERVATION_STATES, m_keep_policy, observe_snapshot


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "m_keep.toml"
    path.write_text(
        """[m_keep]
installed = true
enabled = false
observe_only = true
sample_interval_seconds = 60
max_restart_attempts = 0
timer = false
daemon = false
notify = false
recover = false
tui_attached = false
""",
        encoding="utf-8",
    )
    return path


def test_policy_is_callable_but_default_off_and_non_resident(tmp_path: Path) -> None:
    policy = m_keep_policy(_config(tmp_path))

    assert policy["capability_installed"] is True
    assert policy["enabled"] is False
    assert policy["observe_only"] is True
    assert policy["timer"] is False
    assert policy["daemon"] is False
    assert policy["recover"] is False
    assert policy["max_restart_attempts"] == 0
    assert policy["tui_attached"] is False


def test_six_observation_states_are_classified_without_side_effects(tmp_path: Path) -> None:
    cases = {
        "CAPACITY_ERROR": {"capacity_error": True},
        "WAITING_INPUT": {"waiting_input": True},
        "PROGRESS": {"progress": True},
        "READY_IDLE": {"ready": True},
        "READINESS": {"ready": True, "active_turn": True},
        "LIVENESS": {"alive": True},
    }

    seen = {
        observe_snapshot(snapshot, config_path=_config(tmp_path))["observation"]
        for snapshot in cases.values()
    }

    assert seen == OBSERVATION_STATES
    result = observe_snapshot({"waiting_input": True}, config_path=_config(tmp_path))
    assert result["next_action"] == "NEEDS_USER"
    assert result["recovery_attempted"] is False
    assert not any(result["side_effects"].values())


def test_restart_cap_is_explicit_and_never_recovers(tmp_path: Path) -> None:
    result = observe_snapshot(
        {"managed_session": True, "capacity_error": True, "restart_count": 3},
        config_path=_config(tmp_path),
    )

    assert result["restart_count"] == 3
    assert result["restart_cap"] == 0
    assert result["restart_cap_reached"] is True
    assert result["next_action"] == "NEEDS_USER"
    assert result["recovery_attempted"] is False


def test_ambiguous_or_stopped_session_never_recovers(tmp_path: Path) -> None:
    result = observe_snapshot(
        {"managed_session": True, "ready": True},
        binding={"session_id": "only-one-field"},
        stop_active=True,
        config_path=_config(tmp_path),
    )

    assert result["identity_verified"] is False
    assert result["stop_active"] is True
    assert result["next_action"] == "NEEDS_USER"
    assert result["recovery_attempted"] is False


def test_expected_binding_fences_old_owner_and_pause_never_recovers(tmp_path: Path) -> None:
    expected = {
        "session_id": "session",
        "generation": 2,
        "pid": 123,
        "process_created_at": "created",
        "executable_path": "python.exe",
        "command_line_marker": "marker",
        "logon_session": 1,
        "parent_pid": 10,
    }
    old = {**expected, "generation": 1}

    result = observe_snapshot(
        {"managed_session": True, "ready": True},
        binding=old,
        expected_binding=expected,
        pause_active=True,
        config_path=_config(tmp_path),
    )

    assert result["identity_verified"] is False
    assert result["identity_mismatches"] == ["generation"]
    assert result["pause_active"] is True
    assert result["next_action"] == "NEEDS_USER"
    assert result["recovery_attempted"] is False


def test_old_generation_or_paused_session_never_recovers(tmp_path: Path) -> None:
    expected = {
        "session_id": "session-1",
        "generation": 2,
        "pid": 100,
        "process_created_at": "2026-07-12T00:00:00Z",
        "executable_path": "C:/python.exe",
        "command_line_marker": "marker",
        "logon_session": 1,
        "parent_pid": 50,
    }
    old = {**expected, "generation": 1}

    result = observe_snapshot(
        {"managed_session": True, "ready": True},
        binding=old,
        expected_binding=expected,
        pause_active=True,
        config_path=_config(tmp_path),
    )

    assert result["identity_verified"] is False
    assert result["identity_mismatches"] == ["generation"]
    assert result["pause_active"] is True
    assert result["next_action"] == "NEEDS_USER"
    assert result["recovery_attempted"] is False


def test_module_has_no_process_window_input_or_persistence_primitives() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "xinao_coordination" / "m_keep.py").read_text(
        encoding="utf-8"
    ).lower()
    forbidden = (
        "import subprocess",
        "start-process",
        "sendkeys",
        "register-scheduledtask",
        "win32gui",
        "popen(",
        "createprocess",
    )

    assert all(token not in source for token in forbidden)
