"""T1 AMQ transport + ingest + outbox: idempotent redelivery and bad-hash isolation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from xinao_coordination import CoordinationService
from xinao_coordination.amq import (
    AmqIngestor,
    AmqOutbox,
    AmqTransport,
    BadHashError,
    envelope_from_amq_message,
    payload_sha256,
)
from xinao_coordination.amq import transport as transport_module
from xinao_coordination.errors import ConflictError

AMQ_BIN = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe")
CANARY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary")
CANARY_AMQ = CANARY_ROOT / "amq"


def _amq_available() -> bool:
    return AMQ_BIN.is_file()


def test_transport_binds_child_am_root_without_mutating_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_bin = tmp_path / "amq.exe"
    fake_bin.write_bytes(b"stub")
    local_root = tmp_path / "local-amq"
    monkeypatch.setenv("AM_ROOT", r"D:\production-amq")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(transport_module.subprocess, "run", fake_run)
    transport = AmqTransport(bin_path=fake_bin, root=local_root)
    assert transport._run(["list", "--json"]) == {}
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert child_env["AM_ROOT"] == str(local_root)
    assert os.environ["AM_ROOT"] == r"D:\production-amq"


def _raw_message(
    *,
    message_id: str,
    body: str,
    sender: str = "grok",
    recipient: str = "codex",
    subject: str = "t1",
    kind: str = "status",
    context: dict | None = None,
    declare_hash: bool | str = False,
) -> dict:
    """Build a drain-shaped raw AMQ message (list-valued `to`, trailing body newline)."""
    body_with_nl = body if body.endswith("\n") else body + "\n"
    computed = payload_sha256(body_with_nl, extra={"subject": subject, "kind": kind})
    ctx = dict(context or {})
    if declare_hash is True:
        ctx["payload_sha256"] = computed
    elif isinstance(declare_hash, str):
        ctx["payload_sha256"] = declare_hash
    return {
        "id": message_id,
        "from": sender,
        "to": [recipient],  # real amq.exe shape
        "thread": f"p2p/{recipient}__{sender}",
        "subject": subject,
        "kind": kind,
        "body": body_with_nl,
        "context": ctx,
        "moved_to_cur": True,
    }


def test_mapping_handles_list_to_and_from() -> None:
    env = envelope_from_amq_message(
        {
            "id": "2026-07-11T00-00-00Z_pid1_listok",
            "from": "grok",
            "to": ["codex"],
            "kind": "status",
            "body": "hello\n",
            "subject": "s",
        }
    )
    assert env["sender_role"] == "grok_4_5"
    assert env["recipient_role"] == "codex"
    assert env["recipient_handle"] == "codex"


def test_mapping_rejects_path_traversal_message_id() -> None:
    with pytest.raises(ValueError, match=r"path-like|unsafe"):
        envelope_from_amq_message(
            {"id": "../evil", "from": "grok", "to": "codex", "body": "x", "kind": "status"}
        )


def test_bad_hash_raises_before_kernel() -> None:
    raw = _raw_message(
        message_id="2026-07-11T00-00-00Z_pid1_badhash",
        body="honest body",
        declare_hash="0" * 64,
    )
    with pytest.raises(BadHashError) as ei:
        envelope_from_amq_message(raw, verify_hash=True)
    assert ei.value.details["declared"] == "0" * 64
    assert ei.value.details["computed"] != "0" * 64


def test_duplicate_delivery_idempotent_no_second_thread(tmp_path: Path) -> None:
    """Re-ingest same raw message → replayed; single kernel thread object."""
    db = tmp_path / "coord.sqlite3"
    service = CoordinationService(db)
    transport = AmqTransport(bin_path=AMQ_BIN, root=tmp_path / "amq")
    transport.ensure_layout(["grok", "codex", "admin", "user"])
    ingestor = AmqIngestor(service, transport)
    raw = _raw_message(
        message_id="2026-07-11T00-00-00Z_pid9_dup1",
        body="duplicate delivery payload",
        subject="idem-dup",
        declare_hash=True,
    )
    first = ingestor.ingest_one(raw)
    second = ingestor.ingest_one(raw)

    assert first["ok"] is True
    assert first["replayed"] is False
    assert second["ok"] is True
    assert second["replayed"] is True
    assert second["thread_id"] == first["thread_id"]

    # Kernel has exactly one matching thread for this delivery.
    listed = service.list_threads()
    threads = listed.get("threads") or []
    matches = [
        t
        for t in threads
        if isinstance(t, dict) and (t.get("title") == "idem-dup" or t.get("thread_id") == first["thread_id"])
    ]
    assert len(matches) == 1
    got = service.get_thread(first["thread_id"])
    assert got["thread"]["thread_id"] == first["thread_id"]

    # Same key, different payload → ConflictError path via open_thread idempotency
    conflict_raw = dict(raw)
    conflict_raw["body"] = "different payload\n"
    conflict_raw["context"] = {
        "payload_sha256": payload_sha256(
            "different payload\n", extra={"subject": "idem-dup", "kind": "status"}
        )
    }
    with pytest.raises(ConflictError):
        # force same idempotency_key by keeping same message id → amq:{id}:open
        ingestor.ingest_one(conflict_raw)


def test_bad_hash_isolated_to_quarantine_not_kernel(tmp_path: Path) -> None:
    db = tmp_path / "coord.sqlite3"
    service = CoordinationService(db)
    amq_root = tmp_path / "amq"
    transport = AmqTransport(bin_path=AMQ_BIN, root=amq_root)
    transport.ensure_layout(["grok", "codex", "admin", "user"])

    raw = _raw_message(
        message_id="2026-07-11T00-00-00Z_pid9_bad1",
        body="tampered body",
        subject="bad-hash",
        declare_hash="deadbeef" + "0" * 56,
    )

    # Unit path via ingest_for_role requires drain; call isolate path through public API:
    # use a thin wrapper that feeds ingest_one via a fake drain.
    class _FakeTransport(AmqTransport):
        def drain(self, *, me: str, include_body: bool = True, limit: int = 20):  # type: ignore[override]
            return [raw]

    fake = _FakeTransport(bin_path=AMQ_BIN, root=amq_root)
    fake.ensure_layout(["grok", "codex", "admin", "user"])
    result = AmqIngestor(service, fake).ingest_for_role(recipient_role="codex", limit=5)

    assert result["drained_count"] == 1
    assert result["ingested"] == []
    assert len(result["quarantined"]) == 1
    q = result["quarantined"][0]
    assert q["error"] == "bad_hash_isolated"
    assert q["kernel_written"] is False
    qpath = Path(q["quarantine_path"])
    assert qpath.is_file()
    parked = json.loads(qpath.read_text(encoding="utf-8"))
    assert parked["kernel_written"] is False
    assert parked["reason"] == "bad_hash"

    # Kernel must not hold a thread for this subject
    listed = service.list_threads()
    threads = listed.get("threads") or []
    bad_titles = [t for t in threads if isinstance(t, dict) and t.get("title") == "bad-hash"]
    assert bad_titles == []


def test_same_key_different_payload_quarantined(tmp_path: Path) -> None:
    db = tmp_path / "coord.sqlite3"
    service = CoordinationService(db)
    amq_root = tmp_path / "amq"
    transport = AmqTransport(bin_path=AMQ_BIN, root=amq_root)
    transport.ensure_layout(["grok", "codex"])
    ingestor = AmqIngestor(service, transport)

    raw1 = _raw_message(
        message_id="2026-07-11T00-00-00Z_pid9_key1",
        body="first payload",
        subject="key-conflict",
        declare_hash=True,
    )
    # Force shared logical key via context
    raw1["context"]["idempotency_key"] = "shared-logical-key"
    first = ingestor.ingest_one(raw1)
    assert first["replayed"] is False

    raw2 = _raw_message(
        message_id="2026-07-11T00-00-00Z_pid9_key2",
        body="second different payload",
        subject="key-conflict",
        declare_hash=True,
    )
    raw2["context"]["idempotency_key"] = "shared-logical-key"

    class _FakeTransport(AmqTransport):
        def drain(self, *, me: str, include_body: bool = True, limit: int = 20):  # type: ignore[override]
            return [raw2]

    fake = _FakeTransport(bin_path=AMQ_BIN, root=amq_root)
    result = AmqIngestor(service, fake).ingest_for_role(recipient_role="codex", limit=5)
    assert result["ingested"] == []
    assert any(e.get("error") == "idempotency_conflict" for e in result["errors"])
    assert result["errors"][0]["kernel_written"] is False
    # Original thread remains the only success
    assert service.get_thread(first["thread_id"])["thread"]["thread_id"] == first["thread_id"]


@pytest.mark.skipif(not _amq_available(), reason="amq.exe not installed")
def test_live_amq_send_ingest_duplicate_drain_empty(tmp_path: Path) -> None:
    transport = AmqTransport(bin_path=AMQ_BIN, root=tmp_path / "amq")
    transport.ensure_layout(["grok", "codex", "admin", "user"])
    service = CoordinationService(tmp_path / "coord.sqlite3")
    body = "live t1 body"
    subject = "live-t1"
    kind = "status"
    # AMQ appends newline; compute after send by reading drained body.
    send = transport.send(me="grok", to="codex", body=body, subject=subject, kind=kind)
    assert send.get("id")
    ingestor = AmqIngestor(service, transport)
    first = ingestor.ingest_for_role(recipient_role="codex", limit=5)
    assert first["drained_count"] >= 1
    assert first["ingested"]
    assert first["quarantined"] == []
    thread_id = first["ingested"][0]["thread_id"]
    # Duplicate drain is empty (already cur)
    second = ingestor.ingest_for_role(recipient_role="codex", limit=5)
    assert second["drained_count"] == 0
    # Logical re-ingest of same drained payload is idempotent
    drained_shape = {
        "id": send["id"],
        "from": "grok",
        "to": ["codex"],
        "subject": subject,
        "kind": kind,
        "body": body + "\n",
        "thread": send.get("thread") or "",
    }
    replay = ingestor.ingest_one(drained_shape)
    assert replay["replayed"] is True
    assert replay["thread_id"] == thread_id


@pytest.mark.skipif(not _amq_available(), reason="amq.exe not installed")
def test_canary_root_layout_and_config(tmp_path: Path) -> None:
    """Verify canary AMQ root layout + pinned config without clobbering prod state DB."""
    assert CANARY_AMQ.is_dir()
    transport = AmqTransport(bin_path=AMQ_BIN, root=CANARY_AMQ)
    layout = transport.ensure_layout(["admin", "codex", "grok", "user"])
    assert Path(layout["quarantine"]).is_dir()
    assert Path(layout["dead_letter"]).is_dir()
    assert (CANARY_AMQ / "agents" / "codex" / "inbox" / "new").is_dir()

    # Write/refresh canary mailbox config (canary isolation)
    config = {
        "version": 1,
        "enabled": True,
        "backend": "amq_maildir",
        "auto_promote": False,
        "max_payload_bytes": 1048576,
        "max_redelivery": 3,
        "verify_payload_sha256": True,
        "root": str(CANARY_AMQ).replace("\\", "/"),
        "kernel_db": str(CANARY_ROOT / "coordination.sqlite3").replace("\\", "/"),
        "quarantine": str(CANARY_AMQ / "quarantine").replace("\\", "/"),
        "dead_letter": str(CANARY_AMQ / "dead-letter").replace("\\", "/"),
        "amq_bin": str(AMQ_BIN).replace("\\", "/"),
        "amq_version": transport.version(),
        "agents": ["admin", "codex", "grok", "user"],
    }
    cfg_path = CANARY_AMQ / "meta" / "mailbox_canary.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    assert cfg_path.is_file()

    # Live smoke on canary spool + tmp kernel DB
    os.environ["XINAO_COORD_STOP_DIR"] = str(tmp_path / "stop")
    service = CoordinationService(tmp_path / "canary_kernel.sqlite3")
    msg = transport.send(
        me="codex",
        to="grok",
        body="canary t1 discuss",
        subject="canary-t1",
        kind="question",
    )
    assert msg.get("id")
    result = AmqIngestor(service, transport).ingest_for_role(recipient_role="grok_4_5", limit=10)
    assert result["drained_count"] >= 1
    assert result["ingested"]
    assert result["quarantined"] == []


@pytest.mark.skipif(not _amq_available(), reason="amq.exe not installed")
def test_outbox_flush_adapter_delivered(tmp_path: Path) -> None:
    """Outbox: kernel notification → AMQ send → ADAPTER_DELIVERED (not model_read)."""
    db = tmp_path / "coord.sqlite3"
    service = CoordinationService(db)
    # Create a thread so notifications may enqueue (open_thread posts notify)
    service.open_thread(
        actor="grok_4_5",
        title="outbox-src",
        body="seed",
        idempotency_key="outbox-open",
    )
    transport = AmqTransport(bin_path=AMQ_BIN, root=tmp_path / "amq")
    transport.ensure_layout(["grok", "codex", "admin", "user"])
    outbox = AmqOutbox(service, transport, adapter_id="amq-t1-test")
    # Pull as codex for notifications addressed to codex if any; may be empty.
    flushed = outbox.flush_for_role(sender_role="grok_4_5", recipient_role="codex", max_items=5)
    assert flushed["action"] == "amq.outbox.flush"
    assert "model_read" not in json.dumps(flushed) or all(
        item.get("model_read") is False for item in flushed.get("delivered", [])
    )
    for item in flushed.get("delivered", []):
        assert item["receipt_stage"] == "ADAPTER_DELIVERED"
        assert item["model_read"] is False
