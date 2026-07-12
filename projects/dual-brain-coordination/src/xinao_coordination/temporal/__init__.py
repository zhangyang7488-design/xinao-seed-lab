"""T9 Temporal thin adapter — promoted-task only; never chat/discuss owner."""

from .client import TemporalClient, describe_promoted_queue, reset_mock_registry
from .envelope import (
    PromotedTaskEnvelope,
    envelope_from_kernel_task,
    immutable_intent_hash,
    validate_task_envelope,
    workflow_id_for,
)
from .policy import temporal_policy

__all__ = [
    "PromotedTaskEnvelope",
    "TemporalClient",
    "describe_promoted_queue",
    "envelope_from_kernel_task",
    "immutable_intent_hash",
    "reset_mock_registry",
    "temporal_policy",
    "validate_task_envelope",
    "workflow_id_for",
]
