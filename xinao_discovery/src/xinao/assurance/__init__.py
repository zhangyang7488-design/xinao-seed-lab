"""Fail-closed operational-assurance report construction and verification."""

from .operational import (
    DIMENSION_EVIDENCE_SCHEMA_VERSION,
    OPERATIONAL_ASSURANCE_SCHEMA_VERSION,
    OPERATIONAL_ASSURANCE_VERIFICATION_SCHEMA_VERSION,
    REQUIRED_DIMENSION_CHECKS,
    REQUIRED_DIMENSIONS,
    build_operational_assurance_dimension_evidence,
    build_operational_assurance_report,
    evidence_ref,
    verify_operational_assurance_file,
    verify_operational_assurance_report,
)

__all__ = [
    "DIMENSION_EVIDENCE_SCHEMA_VERSION",
    "OPERATIONAL_ASSURANCE_SCHEMA_VERSION",
    "OPERATIONAL_ASSURANCE_VERIFICATION_SCHEMA_VERSION",
    "REQUIRED_DIMENSIONS",
    "REQUIRED_DIMENSION_CHECKS",
    "build_operational_assurance_dimension_evidence",
    "build_operational_assurance_report",
    "evidence_ref",
    "verify_operational_assurance_file",
    "verify_operational_assurance_report",
]
