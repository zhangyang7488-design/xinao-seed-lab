"""Package-owned, pytest-free production checks for the F4 research factory."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from xinao.foundation.research_factory import (
    F4_REQUIRED_ARTIFACT_TYPES,
    ResearchErrorBudgetPolicy,
    admit_open_method,
    admit_validation_court_request,
    admit_work_item,
    canonical_work_key,
    dedupe_ready_frontier,
    evaluate_error_budget,
    research_factory_artifact_manifest,
    research_factory_schema_payloads,
    research_factory_supporting_payloads,
    source_origin_index,
    source_projection_hash,
    validate_method_registry,
    verify_research_factory_artifacts,
)
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    FROZEN_ROUTE_QUOTE_BASELINE_IDS,
)
from xinao.foundation.validation_court_interface import (
    ValidationCourtRequest,
    ValidationCourtResult,
    verify_validation_court_result,
)

SCHEMA_VERSION = "xinao.f4_production_checker.v1"


class ProductionCheckError(ValueError):
    """Raised when a package-owned F4 production invariant fails."""


def _require_check(condition: object, message: object) -> None:
    if not condition:
        raise ProductionCheckError(str(message))


@contextmanager
def _raises(
    expected: type[BaseException] | tuple[type[BaseException], ...], *, match: str | None = None
) -> Iterator[None]:
    try:
        yield
    except expected as exc:
        if match is not None and re.search(match, str(exc)) is None:
            raise ProductionCheckError(f"exception text did not match {match!r}: {exc}") from exc
    else:
        raise ProductionCheckError(f"expected exception was not raised: {expected}")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _selection_manifest() -> object:
    from xinao.foundation.selection_manifest import compile_default_independent_selection_manifest

    return compile_default_independent_selection_manifest()


def _work(**overrides: object) -> dict[str, object]:
    manifest = _selection_manifest()
    value: dict[str, object] = {
        "schema_version": "xinao.research_work_item.v2",
        "physical_role": "ACTIVE_SETTLEMENT",
        "kind": "semantic-audit",
        "source_ref": "mirror-a",
        "source_dependency_refs": ("catalog",),
        "active_settlement_refs": ("BO0001",),
        "upstream_work_keys": ("4" * 64,),
        "intent_slice": "F1:regular-total",
        "selection_manifest_hash": manifest.content_hash,
        "method_id": "method.external-consensus.v1",
        "method_registration_hash": "1" * 64,
        "method_admission_hash": "9" * 64,
        "world_snapshot_hash": "2" * 64,
        "input_snapshot_hashes": ("3" * 64,),
        "knowledge_cutoff": "2026-07-14T00:00:00Z",
        "budget_ref": "budget:foundation",
        "error_budget_ledger_ref": "ledger:error-budget:foundation",
        "output_schema_ref": "schema:output.v1",
        "handoff_schema_ref": "xinao.agent_handoff.v1",
        "evidence_schema_ref": "xinao.evidence_manifest.v1",
        "correlation_id": "correlation:foundation",
        "expected_information_gain": "resolve one rule ambiguity",
        "evidence_requirements": ("independent-source",),
        "authority_scope": ("read:public",),
        "write_boundary": "READ_ONLY_WORKER",
    }
    value.update(overrides)
    return value


def _admitted_method(
    method_id: str = "method.external-consensus.v1",
) -> tuple[dict[str, object], str, str]:
    from xinao.canonical import canonical_sha256

    digests = {
        "pkg:method@1": "a" * 64,
        "schema:input.v1": "b" * 64,
        "schema:output.v1": "c" * 64,
        "protocol:walk-forward.v1": "d" * 64,
        "contract:fail-closed.v1": "e" * 64,
        "evidence:method-canary.v1": "f" * 64,
    }
    registration = {
        "method_id": method_id,
        "method_kind": "external-consensus",
        "executable_ref": "pkg:method@1",
        "executable_sha256": "a" * 64,
        "input_schema_ref": "schema:input.v1",
        "input_schema_sha256": "b" * 64,
        "output_schema_ref": "schema:output.v1",
        "output_schema_sha256": "c" * 64,
        "verification_protocol_ref": "protocol:walk-forward.v1",
        "verification_protocol_sha256": "d" * 64,
        "failure_contract_ref": "contract:fail-closed.v1",
        "failure_contract_sha256": "e" * 64,
        "source_refs": ("paper:one",),
        "deterministic_seed_policy": "seed is recorded per experiment",
        "canary_evidence_ref": "evidence:method-canary.v1",
        "canary_evidence_sha256": "f" * 64,
    }
    admission = admit_open_method(registration, resolved_content_hashes=digests)
    return (
        admission,
        canonical_sha256(admission["registration"]),
        str(admission["admission_sha256"]),
    )


def _court_request(
    registration_hash: str, admission_hash: str, **overrides: object
) -> dict[str, object]:
    from xinao.canonical import canonical_sha256

    policy = ResearchErrorBudgetPolicy()
    target = datetime(2026, 1, 2, tzinfo=UTC)
    value: dict[str, object] = {
        "request_ref": "court-request:synthetic-foundation-canary.v1",
        "work_key": "1" * 64,
        "active_settlement_refs": (sorted(ACTIVE_SETTLEMENT_BASELINE_IDS)[0],),
        "candidate_artifact": {"ref": "artifact:synthetic-candidate.v1", "sha256": "2" * 64},
        "method_id": "method.external-consensus.v1",
        "method_registration_sha256": registration_hash,
        "method_admission_sha256": admission_hash,
        "protocol_artifact": {"ref": "protocol:walk-forward.v1", "sha256": "d" * 64},
        "split_manifest": {"ref": "split:synthetic-fixed.v1", "sha256": "3" * 64},
        "evaluation_partition_ref": "partition:synthetic-validation.v1",
        "evaluation_partition_sha256": "4" * 64,
        "feature_lookback_rows": 28,
        "decision_horizon_rows": 1,
        "purge_embargo_rows": 28,
        "feature_observations": (
            {
                "feature_ref": "feature:lagged-count.v1",
                "feature_timestamp": target - timedelta(hours=1),
                "target_open_time": target,
            },
            {
                "feature_ref": "feature:lagged-count.v1",
                "feature_timestamp": target + timedelta(hours=23),
                "target_open_time": target + timedelta(days=1),
            },
        ),
        "walk_forward_folds": (
            {
                "fold_id": "fold-01",
                "train_start_index": 0,
                "train_end_index": 49,
                "test_start_index": 78,
                "test_end_index": 99,
            },
            {
                "fold_id": "fold-02",
                "train_start_index": 0,
                "train_end_index": 99,
                "test_start_index": 128,
                "test_end_index": 149,
            },
        ),
        "negative_control_kinds": ("CIRCULAR_SHIFT", "LABEL_PERMUTATION", "NULL_CONSTANT"),
        "error_budget_policy_ref": policy.policy_ref,
        "error_budget_policy_sha256": canonical_sha256(policy.model_dump(mode="json")),
        "hypotheses_in_family": 0,
        "confirmation_queries_used": 0,
        "input_snapshot_hashes": ("5" * 64,),
        "result_schema": {"ref": "schema:output.v1", "sha256": "c" * 64},
        "evidence_schema": {"ref": "schema:generic-court-evidence.v1", "sha256": "6" * 64},
    }
    value.update(overrides)
    return value


def _court_result(
    request: ValidationCourtRequest, admission_sha256: str, **overrides: object
) -> dict[str, object]:
    value: dict[str, object] = {
        "result_ref": "court-result:synthetic-foundation-canary.v1",
        "request_sha256": request.content_hash,
        "admission_sha256": admission_sha256,
        "work_key": request.work_key,
        "active_settlement_refs": request.active_settlement_refs,
        "verdict": "NO_ACTION",
        "negative_controls": tuple(
            (
                {
                    "control_kind": kind,
                    "evidence": {
                        "ref": f"evidence:negative:{kind.lower()}",
                        "sha256": character * 64,
                    },
                    "passed": True,
                }
                for kind, character in zip(
                    request.negative_control_kinds, ("7", "8", "9"), strict=True
                )
            )
        ),
        "result_artifact": {"ref": "artifact:synthetic-court-result.v1", "sha256": "a" * 64},
        "evidence": ({"ref": "evidence:synthetic-court-run.v1", "sha256": "b" * 64},),
    }
    value.update(overrides)
    return value


def check_validation_court_interface_is_generic_and_hash_bound() -> None:
    artifact = research_factory_schema_payloads()["ValidationCourtInterfaceVersion"]
    interface = artifact["interface"]
    _require_check(
        artifact["schema_version"] == "xinao.validation_court_interface.v2",
        "checker assertion failed",
    )
    _require_check(
        interface["interface_kind"] == "GENERIC_TYPED_COURT_NO_ACTIVE_DOMAIN_INSTANCE",
        "checker assertion failed",
    )
    _require_check(
        set(interface["schemas"])
        == {
            "CourtArtifactBinding",
            "CourtFeatureObservation",
            "CourtNegativeControlEvidence",
            "CourtWalkForwardFold",
            "ValidationCourtAdmission",
            "ValidationCourtRequest",
            "ValidationCourtResult",
        },
        "checker assertion failed",
    )
    _require_check(
        set(interface["callable_source_sha256"])
        == {"admit_validation_court_request", "verify_validation_court_result"},
        "checker assertion failed",
    )
    _require_check(
        all(len(value) == 64 for value in interface["model_source_sha256"].values()),
        "checker assertion failed",
    )
    _require_check(
        all(len(value) == 64 for value in interface["callable_source_sha256"].values()),
        "checker assertion failed",
    )
    _require_check("active_protocol" not in interface, "checker assertion failed")
    _require_check("active_windows" not in interface, "checker assertion failed")
    rendered = json.dumps(interface, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "candidate.constant-01-panel-b.v0",
        "validation-protocol.special-number.v1",
        "dataset-split.verified-913.v1",
        "CONFIRMATION_VAULT",
        "FINAL_HOLDOUT",
    ):
        _require_check(forbidden not in rendered, "checker assertion failed")


def check_validation_court_request_accepts_generic_fixed_temporal_contract() -> None:
    method, registration_hash, admission_hash = _admitted_method()
    request = ValidationCourtRequest.model_validate(
        _court_request(registration_hash, admission_hash)
    )
    admission = admit_validation_court_request(
        request,
        method_registry={"method.external-consensus.v1": method},
        error_budget_policy=ResearchErrorBudgetPolicy(),
    )
    _require_check(admission.admitted is True, "checker assertion failed")
    _require_check(admission.request_sha256 == request.content_hash, "checker assertion failed")
    result = ValidationCourtResult.model_validate(_court_result(request, admission.content_hash))
    verification = verify_validation_court_result(request, admission, result)
    _require_check(verification["verified"] is True, "checker assertion failed")
    _require_check(verification["verdict"] == "NO_ACTION", "checker assertion failed")
    _require_check(verification["negative_control_count"] == 3, "checker assertion failed")
    featureless = ValidationCourtRequest.model_validate(
        _court_request(
            registration_hash,
            admission_hash,
            request_ref="court-request:featureless-constant-special-canary.v1",
            candidate_artifact={
                "ref": "artifact:featureless-constant-special-canary.v1",
                "sha256": "e" * 64,
            },
            feature_observations=(),
        )
    )
    featureless_admission = admit_validation_court_request(
        featureless,
        method_registry={"method.external-consensus.v1": method},
        error_budget_policy=ResearchErrorBudgetPolicy(),
    )
    _require_check(featureless.feature_observations == (), "checker assertion failed")
    _require_check(
        featureless_admission.request_sha256 == featureless.content_hash, "checker assertion failed"
    )


def check_validation_court_request_rejects_future_features_and_unpurged_folds() -> None:
    _, registration_hash, admission_hash = _admitted_method()
    valid = _court_request(registration_hash, admission_hash)
    leaked = copy.deepcopy(valid)
    leaked_feature = leaked["feature_observations"][0]
    leaked_feature["feature_timestamp"] = leaked_feature["target_open_time"]
    with _raises(ValidationError, match="future leakage"):
        ValidationCourtRequest.model_validate(leaked)
    short_horizon = copy.deepcopy(valid)
    short_horizon["purge_embargo_rows"] = 27
    with _raises(ValidationError, match="maximum information horizon"):
        ValidationCourtRequest.model_validate(short_horizon)
    unpurged = copy.deepcopy(valid)
    unpurged["walk_forward_folds"][0]["test_start_index"] = 77
    with _raises(ValidationError, match="preserve purge/embargo"):
        ValidationCourtRequest.model_validate(unpurged)


def check_validation_court_admission_and_result_reject_binding_or_control_drift() -> None:
    method, registration_hash, admission_hash = _admitted_method()
    registry = {"method.external-consensus.v1": method}
    policy = ResearchErrorBudgetPolicy()
    request = ValidationCourtRequest.model_validate(
        _court_request(registration_hash, admission_hash)
    )
    admission = admit_validation_court_request(
        request, method_registry=registry, error_budget_policy=policy
    )
    frozen_ref = sorted(FROZEN_ROUTE_QUOTE_BASELINE_IDS)[0]
    with _raises(ValidationError, match="frozen route quote"):
        ValidationCourtRequest.model_validate(
            _court_request(registration_hash, admission_hash, active_settlement_refs=(frozen_ref,))
        )
    wrong_protocol = ValidationCourtRequest.model_validate(
        _court_request(
            registration_hash,
            admission_hash,
            protocol_artifact={"ref": "protocol:walk-forward.v1", "sha256": "0" * 64},
        )
    )
    with _raises(ValueError, match="admitted method protocol"):
        admit_validation_court_request(
            wrong_protocol, method_registry=registry, error_budget_policy=policy
        )
    missing_controls = ValidationCourtRequest.model_validate(
        _court_request(
            registration_hash, admission_hash, negative_control_kinds=("CIRCULAR_SHIFT",)
        )
    )
    with _raises(ValueError, match="exceeds its error budget"):
        admit_validation_court_request(
            missing_controls, method_registry=registry, error_budget_policy=policy
        )
    unbound_result = ValidationCourtResult.model_validate(
        _court_result(request, admission.content_hash, request_sha256="0" * 64)
    )
    with _raises(ValueError, match="not bound to request and admission"):
        verify_validation_court_result(request, admission, unbound_result)
    other_active_ref = sorted(ACTIVE_SETTLEMENT_BASELINE_IDS)[1]
    wrong_active_result = ValidationCourtResult.model_validate(
        _court_result(request, admission.content_hash, active_settlement_refs=(other_active_ref,))
    )
    with _raises(ValueError, match="not bound to request and admission"):
        verify_validation_court_result(request, admission, wrong_active_result)
    failed_controls_payload = _court_result(request, admission.content_hash)
    failed_controls_payload["negative_controls"][0]["passed"] = False
    failed_controls = ValidationCourtResult.model_validate(failed_controls_payload)
    with _raises(ValueError, match="incomplete or failed"):
        verify_validation_court_result(request, admission, failed_controls)


def check_error_budget_requires_negative_controls_and_debits_only_on_admission() -> None:
    policy = ResearchErrorBudgetPolicy()
    admitted = evaluate_error_budget(
        policy,
        hypotheses_in_family=3,
        confirmation_queries_used=1,
        negative_control_kinds=("CIRCULAR_SHIFT", "LABEL_PERMUTATION", "NULL_CONSTANT"),
    )
    _require_check(admitted["admitted"] is True, "checker assertion failed")
    _require_check(admitted["next_confirmation_queries_used"] == 2, "checker assertion failed")
    missing_control = evaluate_error_budget(
        policy,
        hypotheses_in_family=3,
        confirmation_queries_used=1,
        negative_control_kinds=("CIRCULAR_SHIFT",),
    )
    _require_check(missing_control["admitted"] is False, "checker assertion failed")
    _require_check(
        missing_control["next_confirmation_queries_used"] == 1, "checker assertion failed"
    )
    _require_check(
        "NEGATIVE_CONTROLS_INCOMPLETE" in missing_control["reasons"], "checker assertion failed"
    )
    exhausted = evaluate_error_budget(
        policy,
        hypotheses_in_family=20,
        confirmation_queries_used=3,
        negative_control_kinds=("CIRCULAR_SHIFT", "LABEL_PERMUTATION", "NULL_CONSTANT"),
    )
    _require_check(exhausted["admitted"] is False, "checker assertion failed")
    _require_check(
        set(exhausted["reasons"])
        == {"HYPOTHESIS_FAMILY_BUDGET_EXHAUSTED", "CONFIRMATION_QUERY_BUDGET_EXHAUSTED"},
        "checker assertion failed",
    )


def check_work_key_is_order_independent_and_source_mirrors_collapse() -> None:
    left = _work(source_ref="mirror-a")
    right = _work(source_ref="mirror-b")
    origins = {"mirror-a": "origin-1", "mirror-b": "origin-1"}
    _require_check(
        canonical_work_key(left, source_origin_by_ref=origins)
        == canonical_work_key(right, source_origin_by_ref=origins),
        "checker assertion failed",
    )


def check_frozen_origin_mirror_cannot_create_a_work_key() -> None:
    with _raises(ValueError, match="frozen quote origin"):
        canonical_work_key(
            _work(source_ref="mirror-of-frozen"),
            source_origin_by_ref={"mirror-of-frozen": "BO0013"},
        )


def check_ready_frontier_is_dependency_aware_and_deduplicates_mirrors() -> None:
    result = dedupe_ready_frontier(
        [
            _work(source_ref="mirror-b", upstream_work_keys=()),
            _work(source_ref="mirror-a", upstream_work_keys=()),
        ],
        source_origin_by_ref={"mirror-a": "origin-1", "mirror-b": "origin-1"},
    )
    _require_check(len(result["ready"]) == 1, "checker assertion failed")
    _require_check(len(result["duplicates"]) == 1, "checker assertion failed")
    _require_check(
        result["duplicates"][0]["reason"] == "DUPLICATE_OR_SOURCE_MIRROR",
        "checker assertion failed",
    )


def check_ready_frontier_defers_unsatisfied_dependencies() -> None:
    result = dedupe_ready_frontier([_work()], closed_work_keys=[])
    _require_check(not result["ready"], "checker assertion failed")
    _require_check(result["deferred"][0]["missing"] == ["4" * 64], "checker assertion failed")


def check_ready_frontier_uses_upstream_work_keys_not_source_refs() -> None:
    item = _work(source_dependency_refs=("catalog",), upstream_work_keys=("4" * 64,))
    blocked = dedupe_ready_frontier([item], closed_work_keys=[])
    ready = dedupe_ready_frontier([item], closed_work_keys=["4" * 64])
    _require_check(not blocked["ready"], "checker assertion failed")
    _require_check(len(ready["ready"]) == 1, "checker assertion failed")


def check_source_dependency_graph_is_hash_bound_transitive_and_cycle_safe() -> None:
    from xinao.foundation.research_weight_inputs import compile_current_research_weight_foundation

    graph = compile_current_research_weight_foundation()["objects"]["SourceDependencyGraphVersion"]
    origins, graph_hash = source_origin_index(graph)
    _require_check(graph_hash == graph["content_sha256"], "checker assertion failed")
    _require_check(
        origins["local-prior-draft"] == origins["local-service-graph"], "checker assertion failed"
    )
    drifted = copy.deepcopy(graph)
    drifted["edges"].append(
        {
            "from": "local-service-graph",
            "to": "local-prior-draft",
            "relation": "CO_DERIVED_PROJECT_MATERIAL",
        }
    )
    core = {
        key: value for key, value in drifted.items() if key not in {"version_id", "content_sha256"}
    }
    from xinao.canonical import canonical_sha256

    drifted["content_sha256"] = canonical_sha256(core)
    drifted["version_id"] = f"SourceDependencyGraphVersion@{drifted['content_sha256'][:16]}"
    with _raises(ValueError, match="cycle"):
        source_origin_index(drifted)


def check_source_lineage_edge_does_not_merge_independent_origin_clusters() -> None:
    from xinao.canonical import canonical_sha256

    core = {
        "object_type": "SourceDependencyGraphVersion",
        "sources": [
            {"source_id": "origin-a-copy-1", "origin_cluster_id": "origin-a"},
            {"source_id": "origin-a-copy-2", "origin_cluster_id": "origin-a"},
            {"source_id": "derived-b", "origin_cluster_id": "origin-b"},
        ],
        "origin_clusters": [
            {
                "origin_cluster_id": "origin-a",
                "member_source_ids": ["origin-a-copy-1", "origin-a-copy-2"],
            },
            {"origin_cluster_id": "origin-b", "member_source_ids": ["derived-b"]},
        ],
        "edges": [{"from": "origin-a-copy-1", "to": "derived-b", "relation": "DERIVED_FROM"}],
        "summary": {"independent_origin_cluster_count": 2, "source_count": 3},
    }
    digest = canonical_sha256(core)
    graph = {
        **core,
        "version_id": f"SourceDependencyGraphVersion@{digest[:16]}",
        "content_sha256": digest,
    }
    origins, _ = source_origin_index(graph)
    _require_check(
        origins["origin-a-copy-1"] == origins["origin-a-copy-2"] == "origin-a",
        "checker assertion failed",
    )
    _require_check(origins["derived-b"] == "origin-b", "checker assertion failed")


def check_unrelated_source_graph_growth_does_not_change_work_key() -> None:
    from xinao.canonical import canonical_sha256
    from xinao.foundation.research_weight_inputs import compile_current_research_weight_foundation

    graph = compile_current_research_weight_foundation()["objects"]["SourceDependencyGraphVersion"]
    expanded = copy.deepcopy(graph)
    expanded["sources"].append(
        {"source_id": "unrelated-new-source", "origin_cluster_id": "unrelated-origin"}
    )
    expanded["origin_clusters"].append(
        {"origin_cluster_id": "unrelated-origin", "member_source_ids": ["unrelated-new-source"]}
    )
    expanded["summary"] = {
        **expanded["summary"],
        "independent_origin_cluster_count": expanded["summary"]["independent_origin_cluster_count"]
        + 1,
        "source_count": expanded["summary"]["source_count"] + 1,
    }
    core = {
        key: value for key, value in expanded.items() if key not in {"version_id", "content_sha256"}
    }
    expanded["content_sha256"] = canonical_sha256(core)
    expanded["version_id"] = f"SourceDependencyGraphVersion@{expanded['content_sha256'][:16]}"
    refs = ("local-prior-draft",)
    base_origins, _ = source_origin_index(graph)
    expanded_origins, _ = source_origin_index(expanded)
    work = _work(source_ref="local-prior-draft", source_dependency_refs=(), upstream_work_keys=())
    _require_check(
        canonical_work_key(
            work,
            source_origin_by_ref=base_origins,
            source_projection_hash=source_projection_hash(graph, refs),
        )
        == canonical_work_key(
            work,
            source_origin_by_ref=expanded_origins,
            source_projection_hash=source_projection_hash(expanded, refs),
        ),
        "checker assertion failed",
    )


def check_open_method_admission_is_typed_but_not_a_whitelist() -> None:
    digests = {
        "pkg:novel-method@1": "a" * 64,
        "schema:input.v1": "b" * 64,
        "schema:output.v1": "c" * 64,
        "protocol:walk-forward.v1": "d" * 64,
        "contract:fail-closed.v1": "e" * 64,
        "evidence:novel-method-canary.v1": "f" * 64,
    }
    method = {
        "method_id": "novel.method.that.did.not_exist.v1",
        "method_kind": "new-scientific-method",
        "executable_ref": "pkg:novel-method@1",
        "executable_sha256": "a" * 64,
        "input_schema_ref": "schema:input.v1",
        "input_schema_sha256": "b" * 64,
        "output_schema_ref": "schema:output.v1",
        "output_schema_sha256": "c" * 64,
        "verification_protocol_ref": "protocol:walk-forward.v1",
        "verification_protocol_sha256": "d" * 64,
        "failure_contract_ref": "contract:fail-closed.v1",
        "failure_contract_sha256": "e" * 64,
        "source_refs": ("paper:one",),
        "deterministic_seed_policy": "seed is recorded per experiment",
        "canary_evidence_ref": "evidence:novel-method-canary.v1",
        "canary_evidence_sha256": "f" * 64,
    }
    result = admit_open_method(method, resolved_content_hashes=digests)
    _require_check(result["admitted"] is True, "checker assertion failed")
    _require_check(result["method_whitelist_used"] is False, "checker assertion failed")
    invalid = copy.deepcopy(method)
    invalid.pop("verification_protocol_ref")
    with _raises(ValidationError):
        admit_open_method(invalid, resolved_content_hashes=digests)
    with _raises(ValueError, match="hash drifted"):
        admit_open_method(
            method, resolved_content_hashes={**digests, "pkg:novel-method@1": "0" * 64}
        )
    collapsed = copy.deepcopy(method)
    for field in (
        "input_schema_ref",
        "output_schema_ref",
        "verification_protocol_ref",
        "failure_contract_ref",
        "canary_evidence_ref",
    ):
        collapsed[field] = collapsed["executable_ref"]
    with _raises(ValidationError, match="must be distinct"):
        admit_open_method(collapsed, resolved_content_hashes=digests)


def check_work_item_requires_the_admitted_method_registration_hash() -> None:
    admission, registration_hash, admission_hash = _admitted_method()
    work = _work(method_registration_hash=registration_hash, method_admission_hash=admission_hash)
    result = admit_work_item(
        work,
        selection_manifest=_selection_manifest(),
        method_registry={"method.external-consensus.v1": admission},
    )
    _require_check(result["admitted"] is True, "checker assertion failed")
    with _raises(ValueError, match="registry is empty"):
        admit_work_item(work, selection_manifest=_selection_manifest(), method_registry={})
    with _raises((TypeError, ValueError, ValidationError)):
        validate_method_registry(
            {
                "method.external-consensus.v1": {
                    "method_id": "method.external-consensus.v1",
                    "status": "VERIFIED",
                }
            }
        )
    with _raises(ValueError, match="output schema"):
        admit_work_item(
            _work(
                output_schema_ref="schema:unbound-output.v1",
                method_registration_hash=registration_hash,
                method_admission_hash=admission_hash,
            ),
            selection_manifest=_selection_manifest(),
            method_registry={"method.external-consensus.v1": admission},
        )


def check_factory_native_schemas_are_hash_bound() -> None:
    from xinao.foundation.research_weight import verify_versioned_object

    payloads = research_factory_schema_payloads()
    _require_check(tuple(payloads) == F4_REQUIRED_ARTIFACT_TYPES, "checker assertion failed")
    _require_check(
        payloads["DeterministicFanInPolicyVersion"]["policy"]["stages"]
        == ["PRODUCER", "CRITIQUE", "VERIFIER"],
        "checker assertion failed",
    )
    _require_check(
        all(verify_versioned_object(value) for value in payloads.values()),
        "checker assertion failed",
    )
    _require_check(
        all(len(value["content_sha256"]) == 64 for value in payloads.values()),
        "checker assertion failed",
    )
    supporting = research_factory_supporting_payloads()
    _require_check(
        set(supporting)
        == {"OpenMethodRegistrationSchemaVersion", "ResearchErrorBudgetPolicySchemaVersion"},
        "checker assertion failed",
    )
    _require_check(
        all(verify_versioned_object(value) for value in supporting.values()),
        "checker assertion failed",
    )
    tampered = copy.deepcopy(payloads["DynamicCapacityPolicyVersion"])
    tampered["policy"]["maximum_width"] = 64
    _require_check(verify_versioned_object(tampered) is False, "checker assertion failed")
    _require_check(
        all(
            payloads[name]["version_id"].startswith(f"{name}@")
            for name in F4_REQUIRED_ARTIFACT_TYPES
        ),
        "checker assertion failed",
    )
    work_item_artifact = payloads["ResearchWorkItemSchemaVersion"]
    implementation_hashes = work_item_artifact["implementation_source_sha256"]
    _require_check(
        {
            "admit_open_method",
            "admit_work_item",
            "canonical_work_key",
            "open_method_registration",
            "validate_method_admission",
            "validate_method_registry",
        }
        <= set(implementation_hashes),
        "checker assertion failed",
    )
    _require_check(
        all(len(value) == 64 for value in implementation_hashes.values()),
        "checker assertion failed",
    )


def check_factory_artifacts_reject_self_consistent_stale_rehash_and_pin_drift() -> None:
    from xinao.canonical import canonical_sha256

    payloads = research_factory_schema_payloads()
    manifest = research_factory_artifact_manifest(payloads)
    result = verify_research_factory_artifacts(payloads, pinned_manifest=manifest)
    _require_check(result["ok"] is True, "checker assertion failed")
    _require_check(
        result["manifest_content_sha256"] == manifest["content_sha256"], "checker assertion failed"
    )
    verify_research_factory_artifacts(payloads, expected_manifest_sha256=manifest["content_sha256"])
    with _raises(ValueError, match="external pin"):
        verify_research_factory_artifacts(payloads, expected_manifest_sha256="0" * 64)
    stale = copy.deepcopy(payloads)
    dynamic = stale["DynamicCapacityPolicyVersion"]
    dynamic["policy"]["maximum_width"] = 64
    dynamic["policy_sha256"] = canonical_sha256(dynamic["policy"])
    core = {
        key: value for key, value in dynamic.items() if key not in {"version_id", "content_sha256"}
    }
    dynamic["content_sha256"] = canonical_sha256(core)
    dynamic["version_id"] = f"DynamicCapacityPolicyVersion@{dynamic['content_sha256'][:16]}"
    with _raises(ValueError, match="STALE_OR_NOT_CURRENT_GENERATOR"):
        verify_research_factory_artifacts(stale)
    stale_pin = copy.deepcopy(manifest)
    stale_pin["artifact_content_sha256"]["DynamicCapacityPolicyVersion"] = "0" * 64
    pin_core = {
        key: value
        for key, value in stale_pin.items()
        if key not in {"version_id", "content_sha256"}
    }
    stale_pin["content_sha256"] = canonical_sha256(pin_core)
    stale_pin["version_id"] = (
        f"ResearchFactoryArtifactManifestVersion@{stale_pin['content_sha256'][:16]}"
    )
    with _raises(ValueError, match="pinned F4 artifact manifest"):
        verify_research_factory_artifacts(payloads, pinned_manifest=stale_pin)


GROUPS: dict[str, tuple[str, ...]] = {
    "fixed_time_split_and_leakage": (
        "validation_court_interface_is_generic_and_hash_bound",
        "validation_court_request_accepts_generic_fixed_temporal_contract",
        "validation_court_request_rejects_future_features_and_unpurged_folds",
        "validation_court_admission_and_result_reject_binding_or_control_drift",
    ),
    "negative_controls_and_error_budget": (
        "error_budget_requires_negative_controls_and_debits_only_on_admission",
    ),
    "canonical_work_key_and_dependency_dedup": (
        "work_key_is_order_independent_and_source_mirrors_collapse",
        "frozen_origin_mirror_cannot_create_a_work_key",
        "ready_frontier_is_dependency_aware_and_deduplicates_mirrors",
        "ready_frontier_defers_unsatisfied_dependencies",
        "ready_frontier_uses_upstream_work_keys_not_source_refs",
        "source_dependency_graph_is_hash_bound_transitive_and_cycle_safe",
        "source_lineage_edge_does_not_merge_independent_origin_clusters",
        "unrelated_source_graph_growth_does_not_change_work_key",
    ),
    "open_method_typed_admission": (
        "open_method_admission_is_typed_but_not_a_whitelist",
        "work_item_requires_the_admitted_method_registration_hash",
    ),
    "factory_schema_current_and_tamper": (
        "factory_native_schemas_are_hash_bound",
        "factory_artifacts_reject_self_consistent_stale_rehash_and_pin_drift",
    ),
}

CHECKS = {
    "validation_court_interface_is_generic_and_hash_bound": (
        check_validation_court_interface_is_generic_and_hash_bound
    ),
    "validation_court_request_accepts_generic_fixed_temporal_contract": (
        check_validation_court_request_accepts_generic_fixed_temporal_contract
    ),
    "validation_court_request_rejects_future_features_and_unpurged_folds": (
        check_validation_court_request_rejects_future_features_and_unpurged_folds
    ),
    "validation_court_admission_and_result_reject_binding_or_control_drift": (
        check_validation_court_admission_and_result_reject_binding_or_control_drift
    ),
    "error_budget_requires_negative_controls_and_debits_only_on_admission": (
        check_error_budget_requires_negative_controls_and_debits_only_on_admission
    ),
    "work_key_is_order_independent_and_source_mirrors_collapse": (
        check_work_key_is_order_independent_and_source_mirrors_collapse
    ),
    "frozen_origin_mirror_cannot_create_a_work_key": (
        check_frozen_origin_mirror_cannot_create_a_work_key
    ),
    "ready_frontier_is_dependency_aware_and_deduplicates_mirrors": (
        check_ready_frontier_is_dependency_aware_and_deduplicates_mirrors
    ),
    "ready_frontier_defers_unsatisfied_dependencies": (
        check_ready_frontier_defers_unsatisfied_dependencies
    ),
    "ready_frontier_uses_upstream_work_keys_not_source_refs": (
        check_ready_frontier_uses_upstream_work_keys_not_source_refs
    ),
    "source_dependency_graph_is_hash_bound_transitive_and_cycle_safe": (
        check_source_dependency_graph_is_hash_bound_transitive_and_cycle_safe
    ),
    "source_lineage_edge_does_not_merge_independent_origin_clusters": (
        check_source_lineage_edge_does_not_merge_independent_origin_clusters
    ),
    "unrelated_source_graph_growth_does_not_change_work_key": (
        check_unrelated_source_graph_growth_does_not_change_work_key
    ),
    "open_method_admission_is_typed_but_not_a_whitelist": (
        check_open_method_admission_is_typed_but_not_a_whitelist
    ),
    "work_item_requires_the_admitted_method_registration_hash": (
        check_work_item_requires_the_admitted_method_registration_hash
    ),
    "factory_native_schemas_are_hash_bound": check_factory_native_schemas_are_hash_bound,
    "factory_artifacts_reject_self_consistent_stale_rehash_and_pin_drift": (
        check_factory_artifacts_reject_self_consistent_stale_rehash_and_pin_drift
    ),
}


def run_production_checks() -> dict[str, Any]:
    if "pytest" in sys.modules:
        raise ProductionCheckError("production checker cannot run in a pytest-loaded process")
    expected = tuple(name for group in GROUPS.values() for name in group)
    if len(expected) != 17 or len(set(expected)) != 17 or set(expected) != set(CHECKS):
        raise ProductionCheckError("production checker inventory drifted")
    _selection_manifest.cache_clear()
    results = []
    for name in expected:
        CHECKS[name]()
        results.append({"check_id": name, "status": "VERIFIED"})
    source = Path(__file__).resolve()
    core = {
        "schema_version": SCHEMA_VERSION,
        "status": "VERIFIED",
        "group_count": len(GROUPS),
        "groups": {key: list(value) for key, value in GROUPS.items()},
        "check_count": len(results),
        "verified_check_count": len(results),
        "checks": results,
        "checker_source_sha256": _file_sha256(source),
        "pytest_loaded": False,
    }
    return {**core, "content_sha256": _canonical_sha256(core)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = run_production_checks()
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw + "\n", encoding="utf-8")
    print(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
