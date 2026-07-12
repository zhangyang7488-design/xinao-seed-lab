"""Product hot-bridge regression: AMQ drain must persist into the kernel exactly once."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from xinao_coordination import CoordinationService
from xinao_coordination.amq import AmqTransport


REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "adapters" / "amq" / "Invoke-XinaoAmqInboxBridge.ps1"
ROLE_ENV = REPO / "adapters" / "env" / "Set-XinaoDualBrainRoleEnv.ps1"
AMQ_BIN = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe")
COORD_CURRENT = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination\current.json")


def _pwsh() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def _run_bridge(*, amq_root: Path, db: Path, state_root: Path) -> dict[str, object]:
    shell = _pwsh()
    if shell is None:
        pytest.skip("PowerShell is unavailable")
    completed = subprocess.run(
        [
            shell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(BRIDGE),
            "-Action",
            "Drain",
            "-Role",
            "codex",
            "-AmRoot",
            str(amq_root),
            "-AmqBin",
            str(AMQ_BIN),
            "-StateRoot",
            str(state_root),
            "-KernelDb",
            str(db),
            "-CoordCurrent",
            str(COORD_CURRENT),
            "-Quiet",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stderr.strip() == "", completed.stderr
    try:
        value = json.loads(completed.stdout.strip().lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        raise AssertionError(completed.stdout) from exc
    assert isinstance(value, dict)
    return value


@pytest.mark.skipif(not AMQ_BIN.is_file(), reason="pinned amq.exe unavailable")
@pytest.mark.skipif(not COORD_CURRENT.is_file(), reason="managed coordination generation unavailable")
def test_drain_persists_amq_message_into_kernel_exactly_once(tmp_path: Path) -> None:
    amq_root = tmp_path / "amq"
    db = tmp_path / "coordination.sqlite3"
    state_root = tmp_path / "bridge-state"
    transport = AmqTransport(bin_path=AMQ_BIN, root=amq_root)
    transport.ensure_layout()
    body = "BRIDGE_KERNEL_PERSIST_SENTINEL"
    sent = transport.send(
        me="grok",
        to="codex",
        subject="bridge kernel regression",
        body=body,
        kind="answer",
    )
    message_id = str(sent.get("id") or sent.get("message_id") or "")
    assert message_id

    first = _run_bridge(amq_root=amq_root, db=db, state_root=state_root)
    assert first["ok"] is True
    assert first["drained_count"] == 1
    assert first["kernel_persisted_count"] == 1
    assert first["receipt_stage"] == "PERSISTED"
    assert first["items"][0]["id"] == message_id
    assert body in first["items"][0]["body"]

    service = CoordinationService(db)
    threads = service.list_threads()["threads"]
    assert len(threads) == 1
    thread = service.get_thread(str(threads[0]["thread_id"]))
    assert sum(message["body"].strip() == body for message in thread["messages"]) == 1

    second = _run_bridge(amq_root=amq_root, db=db, state_root=state_root)
    assert second["ok"] is True
    assert second["drained_count"] == 0
    assert service.get_thread(str(threads[0]["thread_id"]))["messages"] == thread["messages"]


def test_role_environment_points_to_existing_inbox_bridge() -> None:
    text = ROLE_ENV.read_text(encoding="utf-8-sig")
    assert "Invoke-XinaoDualBrainTurnDrain.ps1" not in text
    assert "amq\\Invoke-XinaoAmqInboxBridge.ps1" in text


def test_bridge_has_one_canonical_consumer() -> None:
    text = BRIDGE.read_text(encoding="utf-8-sig")
    assert "amq-ingest" in text
    assert "& $AmqBin drain" not in text
