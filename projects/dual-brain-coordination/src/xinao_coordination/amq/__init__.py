"""Thin AMQ/Maildir adapter; kernel service remains the authority for state."""

from .ingest import AmqIngestor
from .mapping import BadHashError, envelope_from_amq_message, payload_sha256
from .outbox import AmqOutbox
from .transport import (
    AmqTransport,
    AmqTransportError,
    default_amq_bin,
    default_canary_amq_root,
    default_canary_root,
)

__all__ = [
    "AmqIngestor",
    "AmqOutbox",
    "AmqTransport",
    "AmqTransportError",
    "BadHashError",
    "default_amq_bin",
    "default_canary_amq_root",
    "default_canary_root",
    "envelope_from_amq_message",
    "payload_sha256",
]
