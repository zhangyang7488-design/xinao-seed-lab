"""Mechanical carrier pieces for fresh world-owning Research Sol contacts.

The package intentionally knows nothing about scientific object types, research
stages, hypotheses, or adoption.  It only preserves exact world delivery,
process/lease settlement, byte trees, and verified later opens.
"""

from .runtime import (
    FROZEN_AUDIT,
    WORLD_LIVE,
    ResearchSolRuntimeError,
    build_carrier_envelope,
    build_live_contact_prompt,
    build_world_pin,
    list_cognition_objects,
    open_cognition_object,
    reconcile_carrier_truth,
    seal_cognition_object,
    validate_carrier_envelope,
    validate_world_pin,
)

__all__ = [
    "FROZEN_AUDIT",
    "WORLD_LIVE",
    "ResearchSolRuntimeError",
    "build_carrier_envelope",
    "build_live_contact_prompt",
    "build_world_pin",
    "list_cognition_objects",
    "open_cognition_object",
    "reconcile_carrier_truth",
    "seal_cognition_object",
    "validate_carrier_envelope",
    "validate_world_pin",
]
