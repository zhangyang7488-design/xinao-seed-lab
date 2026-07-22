"""G4 full-family hidden-benchmark deterministic generator (domain core).

Pure producer port: mints immutable in-memory public/private case views for
H01-H14. Does not score subjects, call providers, write vaults, or close G4.
"""

from __future__ import annotations

from .constants import (
    FAMILY_IDS,
    NON_CLAIMS,
    TERMINAL_POSITIVE,
)
from .generator import (
    family_inventory,
    generate_full_family_suites,
    generate_split_suite,
    public_export,
    result_canonical_hash,
)
from .public_safety import (
    contains_secret_material,
    scan_forbidden_public_keys,
    scan_h03_public_hints,
    scan_h04_public_hints,
)
from .report import terminal_ready_report
from .types import (
    FullFamilyGeneratorResult,
    GeneratorProfile,
    PrivateCaseRecord,
    PublicCaseView,
    recompute_commitment,
    verify_commitment,
)
from .verification import verify_full_family_result

__all__ = [
    "FAMILY_IDS",
    "NON_CLAIMS",
    "TERMINAL_POSITIVE",
    "FullFamilyGeneratorResult",
    "GeneratorProfile",
    "PrivateCaseRecord",
    "PublicCaseView",
    "contains_secret_material",
    "family_inventory",
    "generate_full_family_suites",
    "generate_split_suite",
    "public_export",
    "recompute_commitment",
    "result_canonical_hash",
    "scan_forbidden_public_keys",
    "scan_h03_public_hints",
    "scan_h04_public_hints",
    "terminal_ready_report",
    "verify_commitment",
    "verify_full_family_result",
]
