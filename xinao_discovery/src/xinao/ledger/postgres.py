"""Thin Psycopg adapter for the single formal event append function."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .events import EventRecord

APPEND_SQL = "SELECT xinao_append_event(" + ",".join(["%s"] * 24) + ")"


def append_event(
    connection: psycopg.Connection,
    event: EventRecord,
    *,
    outbox_id: str,
    topic: str = "xinao.domain-events.v1",
) -> str:
    values: list[Any] = list(event.append_arguments(outbox_id=outbox_id, topic=topic))
    values[12] = Jsonb(values[12])
    values[21] = Jsonb(values[21])
    return connection.execute(APPEND_SQL, tuple(values)).fetchone()[0]
