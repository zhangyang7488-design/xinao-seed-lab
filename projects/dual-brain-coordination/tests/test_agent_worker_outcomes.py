from __future__ import annotations

import sys
from pathlib import Path

import pytest

from xinao_coordination.agent_operations import AgentOperationStore
from xinao_coordination.agent_worker import run


def submit(store: AgentOperationStore, cwd: Path, suffix: str) -> str:
    operation = store.submit(
        actor="codex",
        prompt=f"fake runner {suffix}",
        session_name=f"fake-{suffix}",
        cwd=cwd,
        idempotency_key=f"fake-{suffix}",
    )["operation"]
    return str(operation["operation_id"])


def configure_fake_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str) -> None:
    runner = tmp_path / "fake_runner.py"
    runtime = tmp_path / "runtime.js"
    runner.write_text(body, encoding="utf-8")
    runtime.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(
        "xinao_coordination.agent_worker.read_acpx_runtime",
        lambda: {"node": Path(sys.executable), "runner": runner, "runtime_module": runtime},
    )


def test_post_start_non_authoritative_terminal_is_uncertain(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_fake_runner(
        monkeypatch,
        tmp_path,
        """
import json
import sys
command = json.loads(sys.stdin.readline())
assert command["action"] == "start"
print(json.dumps({"type": "turn_starting", "requestId": "fake"}), flush=True)
print(json.dumps({
    "type": "terminal",
    "status": "failed",
    "turnStarted": True,
    "resultAuthoritative": False,
    "error": {"message": "result stream lost"}
}), flush=True)
raise SystemExit(2)
""".lstrip(),
    )
    store = AgentOperationStore(db_path)
    operation_id = submit(store, tmp_path, "unknown")

    assert run(operation_id, db_path) == 1
    current = store.get(operation_id)["operation"]
    assert current["state"] == "uncertain"
    assert "authoritative ACP result" in current["error"]


def test_prestart_authoritative_failure_is_failed_not_uncertain(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_fake_runner(
        monkeypatch,
        tmp_path,
        """
import json
import sys
command = json.loads(sys.stdin.readline())
assert command["action"] == "start"
print(json.dumps({
    "type": "terminal",
    "status": "failed",
    "turnStarted": False,
    "resultAuthoritative": False,
    "error": {"message": "probe failed"}
}), flush=True)
raise SystemExit(2)
""".lstrip(),
    )
    store = AgentOperationStore(db_path)
    operation_id = submit(store, tmp_path, "prestart")

    assert run(operation_id, db_path) == 1
    current = store.get(operation_id)["operation"]
    assert current["state"] == "failed"
    assert current["error"] is not None
