"""Generic hidden-capability isolation seam (synthetic fixtures only).

This package is non-authority. It never mints real hidden identities, never
runs production providers, never scores real H01-H14 outcomes, and never
closes G4/G5 or writes final capability passes.

Terminal meanings for this package:
  SEAM_VERIFIED_HOLD | SEAM_VERIFICATION_FAILED
"""

from __future__ import annotations

SCHEMA_PACKAGE = "xinao.g4.hidden_capability_seam"
PACKAGE_ID = "g4_hidden_capability_seam_v1"
SYNTHETIC_LABEL = "SYNTHETIC_FIXTURE_NOT_REAL_CAPABILITY_NOT_ADMISSION_NOT_DISCOVERY"

__all__ = [
    "SCHEMA_PACKAGE",
    "PACKAGE_ID",
    "SYNTHETIC_LABEL",
]
