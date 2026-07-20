"""Domain-first evidence lineage with lazily loaded observability adapters."""

from typing import Any

from .models import EvidenceManifest, LineageIntent, build_lineage_intent

_ADAPTER_EXPORTS = frozenset(
    {
        "complete_mlflow_run",
        "create_mlflow_run",
        "emit_openlineage_run",
        "read_marquez_run",
        "record_otel_delivery",
    }
)


def __getattr__(name: str) -> Any:
    """Load optional MLflow/OpenLineage dependencies only when actually used."""

    if name not in _ADAPTER_EXPORTS:
        raise AttributeError(name)
    from . import adapters

    return getattr(adapters, name)


__all__ = [
    "EvidenceManifest",
    "LineageIntent",
    "build_lineage_intent",
    "complete_mlflow_run",
    "create_mlflow_run",
    "emit_openlineage_run",
    "read_marquez_run",
    "record_otel_delivery",
]
