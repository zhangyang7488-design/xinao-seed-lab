from __future__ import annotations

from pathlib import Path

import pytest

from xinao_coordination import CoordinationService


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "coordination.sqlite3"


@pytest.fixture
def service(db_path: Path) -> CoordinationService:
    return CoordinationService(db_path)


def accepted_thread(service: CoordinationService, suffix: str = "base") -> str:
    opened = service.open_thread(
        actor="grok_4_5",
        title="decision",
        body="proposal",
        idempotency_key=f"open-{suffix}",
    )
    thread = opened["thread"]
    assert isinstance(thread, dict)
    thread_id = str(thread["thread_id"])
    first = service.close_thread(
        actor="grok_4_5",
        thread_id=thread_id,
        decision="accept",
        resolution_key=f"resolution-{suffix}",
        summary="accepted by grok",
        idempotency_key=f"close-grok-{suffix}",
    )
    assert first["thread"]["state"] == "CLOSING"
    second = service.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key=f"resolution-{suffix}",
        summary="accepted by codex",
        idempotency_key=f"close-codex-{suffix}",
    )
    assert second["thread"]["state"] == "ACCEPTED"
    return thread_id
