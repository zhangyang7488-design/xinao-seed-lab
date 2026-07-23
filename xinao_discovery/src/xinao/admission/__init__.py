"""Deterministic formal-domain admission materialization and verification."""

from .domain_research import (
    DOMAIN_ADMISSION_SCHEMA_VERSION,
    DOMAIN_ADMISSION_VERIFICATION_SCHEMA_VERSION,
    REQUIRED_SOURCE_IDS,
    build_domain_research_admission_report,
    evidence_ref,
    verify_domain_research_admission_file,
    verify_domain_research_admission_report,
)

__all__ = [
    "DOMAIN_ADMISSION_SCHEMA_VERSION",
    "DOMAIN_ADMISSION_VERIFICATION_SCHEMA_VERSION",
    "REQUIRED_SOURCE_IDS",
    "build_domain_research_admission_report",
    "evidence_ref",
    "verify_domain_research_admission_file",
    "verify_domain_research_admission_report",
]
