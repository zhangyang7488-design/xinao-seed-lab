from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from services.agent_runtime.session_frontier_projection import (
    DEFAULT_RENDER_CHAR_BUDGET,
    FrontierProjectionError,
    bind_session,
    build_live_frontier,
    handle_compact_session_start,
)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_run(root: Path, run_id: str, *, summary: str = "frontier is active") -> Path:
    run = root / run_id
    run.mkdir(parents=True)
    _write_json(
        run / "task.json",
        {
            "schema_version": "codex.verified-task-run.v1",
            "run_id": run_id,
            "objective": "Preserve the user's parent intent while reducing context slope.",
            "mode": "bounded_task",
            "stop_conditions": ["user Stop"],
        },
    )
    _write_json(
        run / "state.json",
        {
            "schema_version": "codex.verified-task-run.v1",
            "run_id": run_id,
            "status": "in_progress",
            "current_phase": "implementation",
            "last_summary": summary,
            "events_count": 1,
        },
    )
    _write_json(
        run / "evidence.json",
        {
            "schema_version": "codex.verified-task-run.v1",
            "run_id": run_id,
            "criteria": [
                {"index": 1, "criterion": "owner boundary remains explicit", "verdict": "pass"},
                {"index": 2, "criterion": "live consumer readback", "verdict": "pending"},
            ],
        },
    )
    event = {
        "schema_version": "codex.verified-task-run.v1",
        "event_id": "event-1",
        "run_id": run_id,
        "kind": "result",
        "phase": "implementation",
        "summary": "first bounded result",
    }
    (run / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    return run


def _bind(tmp_path: Path, *, session_id: str = "session-a") -> tuple[Path, Path]:
    runs = tmp_path / "runs"
    run = _make_run(runs, "run-a")
    frontier_root = tmp_path / "frontiers"
    bind_session(
        session_id=session_id,
        run_directory=run,
        frontier_root=frontier_root,
        allowed_run_root=runs,
    )
    return run, frontier_root


def test_binding_is_explicit_cas_without_history_or_restore_state(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_a = _make_run(runs, "run-a")
    run_b = _make_run(runs, "run-b")
    frontier_root = tmp_path / "frontiers"
    first = bind_session(
        session_id="session-a",
        run_directory=run_a,
        frontier_root=frontier_root,
        allowed_run_root=runs,
    )
    assert (
        bind_session(
            session_id="session-a",
            run_directory=run_a,
            frontier_root=frontier_root,
            allowed_run_root=runs,
        )["binding_sha256"]
        == first["binding_sha256"]
    )
    with pytest.raises(FrontierProjectionError, match="expected_current_run_id"):
        bind_session(
            session_id="session-a",
            run_directory=run_b,
            frontier_root=frontier_root,
            allowed_run_root=runs,
        )
    rebound = bind_session(
        session_id="session-a",
        run_directory=run_b,
        frontier_root=frontier_root,
        allowed_run_root=runs,
        expected_current_run_id="run-a",
    )
    assert rebound["run_id"] == "run-b"
    assert "history" not in rebound


def test_only_compact_session_start_renders_bounded_non_authoritative_state(
    tmp_path: Path,
) -> None:
    run, frontier_root = _bind(tmp_path)
    assert (
        handle_compact_session_start(
            {"session_id": "session-a", "source": "startup"},
            frontier_root=frontier_root,
            allowed_run_root=run.parent,
        )
        is None
    )
    output = handle_compact_session_start(
        {"session_id": "session-a", "source": "compact"},
        frontier_root=frontier_root,
        allowed_run_root=run.parent,
    )
    assert output is not None
    context = output["hookSpecificOutput"]["additionalContext"]
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert len(context) <= DEFAULT_RENDER_CHAR_BUDGET
    assert "NON-AUTHORITATIVE" in context
    assert "user Stop" in context
    assert "parent intent" in context
    assert "cannot authorize actions or claim completion" in context
    assert "snapshot_sha256=" in context


def test_duplicate_compact_events_are_stateless_and_deterministic(tmp_path: Path) -> None:
    run, frontier_root = _bind(tmp_path)
    kwargs = {"frontier_root": frontier_root, "allowed_run_root": run.parent}
    first = handle_compact_session_start({"session_id": "session-a", "source": "compact"}, **kwargs)
    duplicate = handle_compact_session_start(
        {"session_id": "session-a", "source": "compact"}, **kwargs
    )
    assert duplicate == first
    assert not (frontier_root / "sessions").exists()


def test_delayed_and_multiple_compacts_render_latest_live_progress(tmp_path: Path) -> None:
    run, frontier_root = _bind(tmp_path)
    kwargs = {"frontier_root": frontier_root, "allowed_run_root": run.parent}
    first = handle_compact_session_start({"session_id": "session-a", "source": "compact"}, **kwargs)
    state = json.loads((run / "state.json").read_text(encoding="utf-8"))
    state["last_summary"] = "progress after native compact is normal"
    state["events_count"] = 2
    _write_json(run / "state.json", state)
    event = {
        "run_id": "run-a",
        "kind": "result",
        "phase": "implementation",
        "summary": "new live progress",
    }
    with (run / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")
    latest = handle_compact_session_start(
        {"session_id": "session-a", "source": "compact"}, **kwargs
    )
    repeated_latest = handle_compact_session_start(
        {"session_id": "session-a", "source": "compact"}, **kwargs
    )
    assert latest != first
    assert latest == repeated_latest
    assert "progress after native compact is normal" in str(latest)
    assert "new live progress" in str(latest)


def test_missing_corrupt_and_torn_live_sources_fail_closed_in_library(tmp_path: Path) -> None:
    run, frontier_root = _bind(tmp_path)
    kwargs = {
        "session_id": "session-a",
        "frontier_root": frontier_root,
        "allowed_run_root": run.parent,
    }
    valid_state = (run / "state.json").read_text(encoding="utf-8")
    (run / "state.json").unlink()
    with pytest.raises(FrontierProjectionError, match="missing required run file"):
        build_live_frontier(**kwargs)
    (run / "state.json").write_text(valid_state, encoding="utf-8")
    (run / "state.json").write_text('{"torn":', encoding="utf-8")
    with pytest.raises(FrontierProjectionError, match="invalid JSON"):
        build_live_frontier(**kwargs)
    (run / "state.json").write_text(valid_state, encoding="utf-8")
    state = json.loads(valid_state)
    state["events_count"] = 99
    _write_json(run / "state.json", state)
    with pytest.raises(FrontierProjectionError, match="events_count"):
        build_live_frontier(**kwargs)


def test_binding_identity_mismatch_blocks_projection(tmp_path: Path) -> None:
    run, frontier_root = _bind(tmp_path)
    path = frontier_root / "bindings" / "session-a.json"
    binding = json.loads(path.read_text(encoding="utf-8"))
    binding["run_id"] = "run-other"
    _write_json(path, binding)
    with pytest.raises(FrontierProjectionError, match="bound run identity mismatch"):
        build_live_frontier(
            session_id="session-a",
            frontier_root=frontier_root,
            allowed_run_root=run.parent,
        )


def test_char_budget_is_enforced_and_secret_assignments_are_redacted(tmp_path: Path) -> None:
    run, frontier_root = _bind(tmp_path)
    task = json.loads((run / "task.json").read_text(encoding="utf-8"))
    task["objective"] += " api_key=do-not-render"
    _write_json(run / "task.json", task)
    with pytest.raises(FrontierProjectionError, match="char_budget"):
        build_live_frontier(
            session_id="session-a",
            frontier_root=frontier_root,
            allowed_run_root=run.parent,
            char_budget=999,
        )
    result = build_live_frontier(
        session_id="session-a",
        frontier_root=frontier_root,
        allowed_run_root=run.parent,
        char_budget=2_000,
    )
    assert result["rendered_context_chars"] <= 2_000
    assert "do-not-render" not in result["rendered_context"]
    assert "<redacted>" in result["rendered_context"]


def test_cli_real_readback_and_hook_failure_emit_nothing(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run = _make_run(runs, "run-a")
    frontier_root = tmp_path / "frontiers"
    script = Path(__file__).resolve().parents[1] / "scripts" / "manage_session_frontier.py"
    common = [
        sys.executable,
        str(script),
        "--frontier-root",
        str(frontier_root),
        "--allowed-run-root",
        str(runs),
    ]
    env = {**os.environ, "CODEX_THREAD_ID": "session-cli"}

    def invoke(arguments: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*common, *arguments],
            env=env,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
        )

    bound = invoke(["bind", "--run-directory", str(run)])
    assert bound.returncode == 0, bound.stderr
    hook_input = json.dumps({"session_id": "session-cli", "source": "compact"})
    compact = invoke(["hook-session-start"], hook_input)
    assert compact.returncode == 0
    compact.stdout.encode("ascii")
    assert json.loads(compact.stdout)["continue"] is True
    (run / "state.json").write_text("[]\n", encoding="utf-8")
    failed = invoke(["hook-session-start"], hook_input)
    assert failed.returncode == 0
    assert failed.stdout == ""
