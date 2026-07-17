"""Independent F2 assertion actuals recomputation.

The fixed runner calls :func:`build_assertion_actuals_v1`.  The callable emits
only canonical actual values; PASS/FAIL and expected values remain outside the
canonical verifier in the closure-profile comparison layer.
"""

from __future__ import annotations

from collections.abc import Mapping as _Mapping
from typing import Any as _Any

from xinao.foundation.assertion_verifiers import common as _common
from xinao.foundation.f2_assertions import (
    F2_REQUIRED_ASSERTION_IDS as _F2_REQUIRED_ASSERTION_IDS,
)
from xinao.foundation.f2_assertions import (
    compile_f2_assertion_report as _compile_f2_assertion_report,
)
from xinao.foundation.f2_compile import (
    OddsSpaceBenchmarkVersion as _OddsSpaceBenchmarkVersion,
)
from xinao.foundation.f2_compile import RebateScheduleVersion as _RebateScheduleVersion
from xinao.foundation.f2_compile import (
    SettlementCostCompileReport as _SettlementCostCompileReport,
)
from xinao.foundation.f2_compile import (
    SettlementCostSurfaceVersion as _SettlementCostSurfaceVersion,
)
from xinao.foundation.f2_compile import (
    SettlementProbabilitySnapshotVersion as _SettlementProbabilitySnapshotVersion,
)
from xinao.foundation.f2_compile import compile_f2_artifacts as _compile_f2_artifacts

BLOCK_ID = "F2_issuer_settlement_cost_space"
ARTIFACT_TYPES = frozenset(
    {
        "SettlementProbabilitySnapshotVersion",
        "RebateScheduleVersion",
        "SettlementCostSurfaceVersion",
        "OddsSpaceBenchmarkVersion",
        "SettlementCostCompileReport",
    }
)
ASSERTION_IDS = _F2_REQUIRED_ASSERTION_IDS

ARTIFACT_MODELS = {
    "SettlementProbabilitySnapshotVersion": _SettlementProbabilitySnapshotVersion,
    "RebateScheduleVersion": _RebateScheduleVersion,
    "SettlementCostSurfaceVersion": _SettlementCostSurfaceVersion,
    "OddsSpaceBenchmarkVersion": _OddsSpaceBenchmarkVersion,
    "SettlementCostCompileReport": _SettlementCostCompileReport,
}


def build_assertion_actuals_v1(request: _Mapping[str, _Any]) -> dict[str, _Any]:
    """Recompute the exact F2 actual inventory from bound source bytes."""

    prepared = _common.prepare_request(
        request,
        expected_block_id=BLOCK_ID,
        expected_artifact_types=ARTIFACT_TYPES,
        expected_assertion_ids=ASSERTION_IDS,
    )
    retained = _common.load_artifact_payloads(prepared)
    inputs = _common.compile_foundation_inputs(prepared)
    report = _compile_f2_artifacts(
        inputs.registry,
        atomic_ticket_bindings=inputs.atomic_ticket_bindings,
    )
    recomputed = {
        "SettlementProbabilitySnapshotVersion": report.probability_snapshot.model_dump(
            mode="json"
        ),
        "RebateScheduleVersion": report.rebate_schedule.model_dump(mode="json"),
        "SettlementCostSurfaceVersion": report.cost_surface.model_dump(mode="json"),
        "OddsSpaceBenchmarkVersion": report.odds_space_benchmark.model_dump(mode="json"),
        "SettlementCostCompileReport": report.model_dump(mode="json"),
    }
    _common.assert_recomputed_artifacts(retained, recomputed)
    _common.validate_model_payloads(retained, ARTIFACT_MODELS, block_label="F2")

    assertion_report = _compile_f2_assertion_report(
        inputs.registry,
        report,
        atomic_ticket_bindings=inputs.atomic_ticket_bindings,
    )
    actuals = {
        result.assertion_id: result.actual_value
        for result in assertion_report.assertion_results
    }
    return _common.ensure_exact_actuals(actuals, expected_assertion_ids=ASSERTION_IDS)


__all__ = ["build_assertion_actuals_v1"]
