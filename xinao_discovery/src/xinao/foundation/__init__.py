"""Machine-checkable F1-F4 foundation closure primitives."""

from xinao.foundation.assessment import assess_foundation
from xinao.foundation.closure import (
    FOUNDATION_BLOCK_IDS,
    FoundationProfileUnavailable,
    derive_foundation_closure_report,
    evidence_ref,
    load_foundation_profile,
    resolve_foundation_profile,
    verify_foundation_closure_report,
    write_json_atomic,
)

__all__ = [
    "FOUNDATION_BLOCK_IDS",
    "FoundationProfileUnavailable",
    "assess_foundation",
    "derive_foundation_closure_report",
    "evidence_ref",
    "load_foundation_profile",
    "resolve_foundation_profile",
    "verify_foundation_closure_report",
    "write_json_atomic",
]
