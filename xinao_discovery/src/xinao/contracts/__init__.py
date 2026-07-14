"""Versioned Xinao domain and handoff contracts."""

from .common import CommonEnvelope
from .domain import DOMAIN_OBJECT_SPECS, domain_model, domain_schema, domain_schema_catalog
from .handoff import HandoffMessage
from .objects import AuthorityContract, BaselineOddsWaterVersion, DatasetSnapshot

__all__ = [
    "DOMAIN_OBJECT_SPECS",
    "AuthorityContract",
    "BaselineOddsWaterVersion",
    "CommonEnvelope",
    "DatasetSnapshot",
    "HandoffMessage",
    "domain_model",
    "domain_schema",
    "domain_schema_catalog",
]
