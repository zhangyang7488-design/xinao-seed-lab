"""Independent F3 assertion actuals recomputation.

The fixed runner calls :func:`build_assertion_actuals_v1`.  This source emits
only observed values from bound bytes; expectations and verdicts remain in the
closure-profile comparison layer.
"""

from __future__ import annotations

from collections.abc import Mapping as _Mapping
from typing import Any as _Any

from xinao.canonical import canonical_sha256 as _canonical_sha256
from xinao.foundation.assertion_verifiers import common as _common
from xinao.foundation.f2_compile import compile_f2_artifacts as _compile_f2_artifacts
from xinao.foundation.f3_assertions import (
    F3_REQUIRED_ARTIFACT_TYPES as _F3_REQUIRED_ARTIFACT_TYPES,
)
from xinao.foundation.f3_assertions import (
    F3_REQUIRED_ASSERTION_IDS as _F3_REQUIRED_ASSERTION_IDS,
)
from xinao.foundation.f3_assertions import (
    compile_f3_assertion_actuals as _compile_f3_assertion_actuals,
)
from xinao.foundation.research_weight import verify_versioned_object as _verify_versioned_object
from xinao.foundation.research_weight_inputs import (
    compile_current_research_weight_foundation as _compile_current_research_weight_foundation,
)

BLOCK_ID = "F3_research_weight"
ARTIFACT_TYPES = _F3_REQUIRED_ARTIFACT_TYPES
ASSERTION_IDS = _F3_REQUIRED_ASSERTION_IDS


def build_assertion_actuals_v1(request: _Mapping[str, _Any]) -> dict[str, _Any]:
    """Recompute the exact F3 actual inventory from hash-bound source bytes."""

    prepared = _common.prepare_request(
        request,
        expected_block_id=BLOCK_ID,
        expected_artifact_types=ARTIFACT_TYPES,
        expected_assertion_ids=ASSERTION_IDS,
    )
    retained = _common.load_artifact_payloads(prepared)
    inputs = _common.compile_foundation_inputs(prepared)
    f2_report = _compile_f2_artifacts(
        inputs.registry,
        atomic_ticket_bindings=inputs.atomic_ticket_bindings,
    )
    bundle = _compile_current_research_weight_foundation(
        prior_path=prepared.input_paths["f3_prior_draft_sha256"],
        service_graph_path=prepared.input_paths["f3_service_graph_sha256"],
        external_synthesis_path=prepared.input_paths["f3_external_synthesis_sha256"],
        semantics_registry=inputs.registry,
        f2_report=f2_report,
    )
    recomputed = dict(bundle["objects"])
    _common.assert_recomputed_artifacts(retained, recomputed)

    invalid_objects = sorted(
        artifact_type
        for artifact_type, payload in recomputed.items()
        if not _verify_versioned_object(payload)
    )
    if invalid_objects:
        raise _common.AssertionActualsError(
            f"recomputed F3 objects are not self-hash-valid: {invalid_objects}"
        )
    version_mismatches = sorted(
        artifact_type
        for artifact_type, payload in recomputed.items()
        if prepared.artifact_versions[artifact_type] != payload.get("version_id")
    )
    if version_mismatches:
        raise _common.AssertionActualsError(
            f"retained F3 artifact versions drifted: {version_mismatches}"
        )

    expected_input_bindings = {
        "external_synthesis": prepared.input_hashes["f3_external_synthesis_sha256"],
        "prior_draft": prepared.input_hashes["f3_prior_draft_sha256"],
        "service_graph": prepared.input_hashes["f3_service_graph_sha256"],
    }
    observed_input_bindings = bundle.get("input_bindings")
    if not isinstance(observed_input_bindings, _Mapping):
        raise _common.AssertionActualsError("recomputed F3 input bindings are absent")
    observed_binding_hashes = {
        key: value.get("sha256") if isinstance(value, _Mapping) else None
        for key, value in observed_input_bindings.items()
    }
    if observed_binding_hashes != expected_input_bindings:
        raise _common.AssertionActualsError(
            "recomputed F3 input bindings do not match the assertion request"
        )
    if bundle.get("input_bundle_sha256") != _canonical_sha256(observed_input_bindings):
        raise _common.AssertionActualsError("recomputed F3 input bundle hash is invalid")

    actuals = _compile_f3_assertion_actuals(bundle)
    return _common.ensure_exact_actuals(actuals, expected_assertion_ids=ASSERTION_IDS)


__all__ = ["build_assertion_actuals_v1"]
