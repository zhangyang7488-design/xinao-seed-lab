"""Deterministic settlement functions."""

from __future__ import annotations

from typing import Any

from .rule_source import (
    AUTHORITY_BASIS,
    DEFAULT_SOURCE_BUNDLE_PATH,
    SOURCE_BUNDLE_HASH,
    SOURCE_BUNDLE_REF,
    SOURCE_TYPE,
    SemanticClaim,
    TargetMarketSnapshotRuleVersion,
    verify_source_bundle,
)
from .shadow import (
    OutcomeAdmission,
    OutcomeObservation,
    SettlementBundle,
    SettlementRecord,
    admit_outcome,
    admit_settlement,
    settle_frozen_decision,
)
from .special_number import (
    SPECIAL_NUMBER_FUNCTION,
    SPECIAL_NUMBER_RULE,
    SettlementResult,
    settle_special_number,
)

# Evidence compiler is intentionally not imported at package load: it pulls full-tree
# helpers (e.g. xinao.world.builder) outside the sealed shadow-runtime inventory.
# Full discovery still reaches it via lazy attribute export below.

__all__ = [
    "AUTHORITY_BASIS",
    "DEFAULT_SOURCE_BUNDLE_PATH",
    "SOURCE_BUNDLE_HASH",
    "SOURCE_BUNDLE_REF",
    "SOURCE_TYPE",
    "SPECIAL_NUMBER_FUNCTION",
    "SPECIAL_NUMBER_RULE",
    "OutcomeAdmission",
    "OutcomeObservation",
    "SemanticClaim",
    "SettlementBundle",
    "SettlementRecord",
    "SettlementResult",
    "TargetMarketSnapshotRuleVersion",
    "admit_outcome",
    "admit_settlement",
    "evaluate_special_number_page_evidence",
    "settle_frozen_decision",
    "settle_special_number",
    "verify_source_bundle",
    "verify_special_number_rule_evidence",
]

_EVIDENCE_EXPORTS = frozenset(
    {
        "evaluate_special_number_page_evidence",
        "verify_special_number_rule_evidence",
    }
)


def __getattr__(name: str) -> Any:
    if name in _EVIDENCE_EXPORTS:
        from .special_number_evidence import (
            evaluate_special_number_page_evidence,
            verify_special_number_rule_evidence,
        )

        mapping = {
            "evaluate_special_number_page_evidence": evaluate_special_number_page_evidence,
            "verify_special_number_rule_evidence": verify_special_number_rule_evidence,
        }
        value = mapping[name]
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
