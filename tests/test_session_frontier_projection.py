from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import services.agent_runtime.session_frontier_projection as session_frontier_module
from services.agent_runtime.session_frontier_projection import (
    DEFAULT_RENDER_CHAR_BUDGET,
    FrontierProjectionError,
    bind_session,
    build_live_frontier,
    handle_compact_session_start,
    load_binding,
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


def _load_managed_frontier_module() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "manage_session_frontier.py"
    spec = importlib.util.spec_from_file_location("xinao_session_frontier_binder", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _task_run_prepare_and_bind(
    module: ModuleType,
    *,
    session_id: str,
    run_directory: Path,
    allowed_roots: tuple[Path, ...],
    frontier_root: Path,
) -> dict[str, Any]:
    """Mirror verified-agent-loop's load_binding preflight + CAS bind surface."""
    expected_current_run_id = None
    assert callable(getattr(module, "load_binding", None))
    frontier_error = getattr(module, "FrontierProjectionError", None)
    try:
        current = module.load_binding(
            session_id=session_id,
            frontier_root=frontier_root,
            allowed_run_root=allowed_roots,
        )
        expected_current_run_id = str(current.get("run_id") or "") or None
    except Exception as exc:
        if frontier_error is None or not isinstance(exc, frontier_error):
            raise
    return module.bind_session(
        session_id=session_id,
        run_directory=run_directory,
        frontier_root=frontier_root,
        allowed_run_root=allowed_roots,
        expected_current_run_id=expected_current_run_id,
    )


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
    assert first["run_id"] == "run-a"
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
    with pytest.raises(FrontierProjectionError, match="expected_current_run_id"):
        bind_session(
            session_id="session-a",
            run_directory=run_b,
            frontier_root=frontier_root,
            allowed_run_root=runs,
            expected_current_run_id="stale-run",
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
    loaded = load_binding(
        session_id="session-a",
        frontier_root=frontier_root,
        allowed_run_root=runs,
    )
    assert loaded["run_id"] == "run-b"


def test_manage_session_frontier_exports_load_binding_for_task_run_cas(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    alternate = tmp_path / "alternate-runs"
    run_a = _make_run(runs, "run-a")
    run_b = _make_run(runs, "run-b")
    frontier_root = tmp_path / "frontiers"
    allowed_roots = (runs.resolve(), alternate.resolve())
    module = _load_managed_frontier_module()

    assert callable(getattr(module, "load_binding", None))
    assert callable(getattr(module, "bind_session", None))
    assert getattr(module, "FrontierProjectionError", None) is FrontierProjectionError

    first = _task_run_prepare_and_bind(
        module,
        session_id="session-export",
        run_directory=run_a,
        allowed_roots=allowed_roots,
        frontier_root=frontier_root,
    )
    assert first["run_id"] == "run-a"

    # Idempotent same-run bind through the managed export surface.
    same = _task_run_prepare_and_bind(
        module,
        session_id="session-export",
        run_directory=run_a,
        allowed_roots=allowed_roots,
        frontier_root=frontier_root,
    )
    assert same["run_id"] == "run-a"
    assert same["binding_sha256"] == first["binding_sha256"]

    # Explicit rebind A -> B using load_binding preflight (no ghost unbound B).
    rebound = _task_run_prepare_and_bind(
        module,
        session_id="session-export",
        run_directory=run_b,
        allowed_roots=allowed_roots,
        frontier_root=frontier_root,
    )
    assert rebound["run_id"] == "run-b"
    live = module.load_binding(
        session_id="session-export",
        frontier_root=frontier_root,
        allowed_run_root=allowed_roots,
    )
    assert live["run_id"] == "run-b"
    assert Path(live["run_directory"]).resolve() == run_b.resolve()

    # Stale expected identity still fails closed when CAS is forced wrong.
    with pytest.raises(module.FrontierProjectionError, match="expected_current_run_id"):
        module.bind_session(
            session_id="session-export",
            run_directory=run_a,
            frontier_root=frontier_root,
            allowed_run_root=allowed_roots,
            expected_current_run_id="run-a",
        )
    still = module.load_binding(
        session_id="session-export",
        frontier_root=frontier_root,
        allowed_run_root=allowed_roots,
    )
    assert still["run_id"] == "run-b"

    # Compact frontier remains renderable under the stated default budget.
    compact = module.build_live_frontier(
        session_id="session-export",
        frontier_root=frontier_root,
        allowed_run_root=allowed_roots,
        char_budget=DEFAULT_RENDER_CHAR_BUDGET,
    )
    assert compact["run_id"] == "run-b"
    assert compact["rendered_context_chars"] <= DEFAULT_RENDER_CHAR_BUDGET
    assert "NON-AUTHORITATIVE" in compact["rendered_context"]
    assert "cannot authorize actions or claim completion" in compact["rendered_context"]


def test_binding_accepts_either_explicit_canonical_root(tmp_path: Path) -> None:
    primary_root = tmp_path / "situation-runs"
    alternate_root = tmp_path / "codex-task-runs"
    run = _make_run(alternate_root, "run-alt")
    frontier_root = tmp_path / "frontiers"

    binding = bind_session(
        session_id="session-alt",
        run_directory=run,
        frontier_root=frontier_root,
        allowed_run_root=(primary_root, alternate_root),
    )
    result = build_live_frontier(
        session_id="session-alt",
        frontier_root=frontier_root,
        allowed_run_root=(primary_root, alternate_root),
    )

    assert Path(binding["run_root"]) == alternate_root.resolve()
    assert result["run_id"] == "run-alt"
    assert result["rendered_context_chars"] <= DEFAULT_RENDER_CHAR_BUDGET


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
    assert "task_objective_candidate=" in context
    assert "parent_result=" not in context
    assert "parent_rebound" in context
    assert "candidate evidence" in context
    assert "cannot authorize actions or claim completion" in context
    assert "snapshot_sha256=" in context


def test_parent_rebound_event_is_rendered_as_non_authoritative_candidate(
    tmp_path: Path,
) -> None:
    run, frontier_root = _bind(tmp_path)
    state = json.loads((run / "state.json").read_text(encoding="utf-8"))
    state["current_phase"] = "parent_rebound"
    state["last_summary"] = "AI inferred a global platform from one possible caller example"
    state["events_count"] = 2
    _write_json(run / "state.json", state)
    with (run / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "run_id": "run-a",
                    "kind": "observation",
                    "phase": "parent_rebound",
                    "summary": state["last_summary"],
                }
            )
            + "\n"
        )

    result = build_live_frontier(
        session_id="session-a",
        frontier_root=frontier_root,
        allowed_run_root=run.parent,
    )
    context = result["rendered_context"]

    assert "parent_rebound" in context
    assert "candidate evidence" in context
    assert "cannot prove user intent" in context
    assert "task_objective_candidate=" in context


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


def test_cli_verify_binding_distinguishes_unbound_from_live_compact_recovery(
    tmp_path: Path,
) -> None:
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
    env = {**os.environ, "CODEX_THREAD_ID": "session-verify"}

    def invoke(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*common, *arguments],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    unbound = invoke(["verify-binding"])
    assert unbound.returncode == 2
    assert unbound.stdout == ""
    assert "missing required file" in unbound.stderr

    bound = invoke(["bind", "--run-directory", str(run)])
    assert bound.returncode == 0, bound.stderr
    verified = invoke(["verify-binding"])
    assert verified.returncode == 0, verified.stderr
    receipt = json.loads(verified.stdout)
    assert receipt["compact_recovery_verified"] is True
    assert receipt["completion_claim_allowed"] is False
    assert receipt["session_id"] == "session-verify"
    assert receipt["run_id"] == "run-a"
    assert receipt["binding_sha256"]
    assert receipt["rendered_context_chars"] > 0

    (run / "state.json").write_text("[]\n", encoding="utf-8")
    drifted = invoke(["verify-binding"])
    assert drifted.returncode == 2
    assert drifted.stdout == ""
    assert "task-run JSON roots must be objects" in drifted.stderr


def test_session_frontier_module_uses_stdlib_only_for_lock() -> None:
    source_path = Path(session_frontier_module.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert "portalocker" not in imported
    assert "portalocker" not in vars(session_frontier_module)
    assert hasattr(session_frontier_module, "_exclusive_lock")


def test_exclusive_lock_serializes_same_path_and_releases(tmp_path: Path) -> None:
    lock_path = tmp_path / "bindings" / "session-lock.lock"
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    second_error: list[BaseException] = []

    def hold_first() -> None:
        with session_frontier_module._exclusive_lock(lock_path, timeout_seconds=5.0):
            first_entered.set()
            assert release_first.wait(timeout=5)

    def enter_second() -> None:
        try:
            with session_frontier_module._exclusive_lock(lock_path, timeout_seconds=5.0):
                second_entered.set()
        except BaseException as exc:  # pragma: no cover - surfaced via list
            second_error.append(exc)

    first = threading.Thread(target=hold_first)
    second = threading.Thread(target=enter_second)
    first.start()
    assert first_entered.wait(timeout=5)
    second.start()
    assert not second_entered.wait(timeout=0.2)
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not second_error
    assert second_entered.is_set()
    assert lock_path.is_file()


def test_exclusive_lock_timeout_fails_closed_while_held(tmp_path: Path) -> None:
    lock_path = tmp_path / "bindings" / "session-busy.lock"
    first_entered = threading.Event()
    release_first = threading.Event()
    second_error: list[BaseException] = []

    def hold_first() -> None:
        with session_frontier_module._exclusive_lock(lock_path, timeout_seconds=5.0):
            first_entered.set()
            assert release_first.wait(timeout=5)

    def try_second() -> None:
        try:
            with session_frontier_module._exclusive_lock(lock_path, timeout_seconds=0.2):
                pass
        except BaseException as exc:
            second_error.append(exc)

    first = threading.Thread(target=hold_first)
    second = threading.Thread(target=try_second)
    first.start()
    assert first_entered.wait(timeout=5)
    second.start()
    second.join(timeout=5)
    release_first.set()
    first.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(second_error) == 1
    assert isinstance(second_error[0], FrontierProjectionError)
    assert "busy" in str(second_error[0])


def test_bind_session_waits_for_lock_then_cas_rebinds(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_a = _make_run(runs, "run-a")
    run_b = _make_run(runs, "run-b")
    frontier_root = tmp_path / "frontiers"
    bind_session(
        session_id="session-wait",
        run_directory=run_a,
        frontier_root=frontier_root,
        allowed_run_root=runs,
    )
    lock_path = frontier_root / "bindings" / "session-wait.lock"
    first_entered = threading.Event()
    release_first = threading.Event()
    waiter_entered = threading.Event()
    results: dict[str, Any] = {}
    errors: dict[str, BaseException] = {}

    def hold_lock() -> None:
        with session_frontier_module._exclusive_lock(lock_path, timeout_seconds=5.0):
            first_entered.set()
            assert release_first.wait(timeout=5)

    def rebind_after_wait() -> None:
        try:
            results["b"] = bind_session(
                session_id="session-wait",
                run_directory=run_b,
                frontier_root=frontier_root,
                allowed_run_root=runs,
                expected_current_run_id="run-a",
            )
            waiter_entered.set()
        except BaseException as exc:
            errors["b"] = exc

    holder = threading.Thread(target=hold_lock)
    waiter = threading.Thread(target=rebind_after_wait)
    holder.start()
    assert first_entered.wait(timeout=5)
    waiter.start()
    assert not waiter_entered.wait(timeout=0.25)
    release_first.set()
    holder.join(timeout=5)
    waiter.join(timeout=10)

    assert not holder.is_alive()
    assert not waiter.is_alive()
    assert not errors
    assert results["b"]["run_id"] == "run-b"
    live = load_binding(
        session_id="session-wait",
        frontier_root=frontier_root,
        allowed_run_root=runs,
    )
    assert live["run_id"] == "run-b"


def test_bind_session_concurrent_cas_one_winner(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_a = _make_run(runs, "run-a")
    run_b = _make_run(runs, "run-b")
    run_c = _make_run(runs, "run-c")
    frontier_root = tmp_path / "frontiers"
    bind_session(
        session_id="session-race",
        run_directory=run_a,
        frontier_root=frontier_root,
        allowed_run_root=runs,
    )
    barrier = threading.Barrier(2)
    results: dict[str, Any] = {}
    errors: dict[str, BaseException] = {}

    def rebind(label: str, run_directory: Path) -> None:
        try:
            barrier.wait(timeout=5)
            results[label] = bind_session(
                session_id="session-race",
                run_directory=run_directory,
                frontier_root=frontier_root,
                allowed_run_root=runs,
                expected_current_run_id="run-a",
            )
        except BaseException as exc:
            errors[label] = exc

    left = threading.Thread(target=rebind, args=("b", run_b))
    right = threading.Thread(target=rebind, args=("c", run_c))
    left.start()
    right.start()
    left.join(timeout=15)
    right.join(timeout=15)

    assert not left.is_alive()
    assert not right.is_alive()
    winners = {label for label in ("b", "c") if label in results}
    losers = {label for label in ("b", "c") if label in errors}
    assert winners and losers
    assert len(winners) == 1
    assert len(losers) == 1
    winner_label = next(iter(winners))
    loser_label = next(iter(losers))
    assert results[winner_label]["run_id"] == f"run-{winner_label}"
    assert isinstance(errors[loser_label], FrontierProjectionError)
    assert "expected_current_run_id" in str(errors[loser_label]) or "busy" in str(
        errors[loser_label]
    )
    live = load_binding(
        session_id="session-race",
        frontier_root=frontier_root,
        allowed_run_root=runs,
    )
    assert live["run_id"] == f"run-{winner_label}"


def test_bind_session_rejects_stale_cas_without_lock_holder(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_a = _make_run(runs, "run-a")
    run_b = _make_run(runs, "run-b")
    frontier_root = tmp_path / "frontiers"
    bind_session(
        session_id="session-stale",
        run_directory=run_a,
        frontier_root=frontier_root,
        allowed_run_root=runs,
    )
    with pytest.raises(FrontierProjectionError, match="expected_current_run_id"):
        bind_session(
            session_id="session-stale",
            run_directory=run_b,
            frontier_root=frontier_root,
            allowed_run_root=runs,
            expected_current_run_id="not-run-a",
        )
    live = load_binding(
        session_id="session-stale",
        frontier_root=frontier_root,
        allowed_run_root=runs,
    )
    assert live["run_id"] == "run-a"
