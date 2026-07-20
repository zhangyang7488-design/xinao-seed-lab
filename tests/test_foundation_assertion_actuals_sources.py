from __future__ import annotations

import gc
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest
from xinao.foundation.assertion_verifiers import common as verifier_common
from xinao.foundation.assertion_verifiers.common import AssertionActualsError
from xinao.foundation.assertion_verifiers.f1_assertion_actuals import (
    ASSERTION_IDS as F1_ASSERTION_IDS,
)
from xinao.foundation.assertion_verifiers.f1_assertion_actuals import (
    build_assertion_actuals_v1 as build_f1_actuals,
)
from xinao.foundation.assertion_verifiers.f2_assertion_actuals import (
    ASSERTION_IDS as F2_ASSERTION_IDS,
)
from xinao.foundation.assertion_verifiers.f2_assertion_actuals import (
    build_assertion_actuals_v1 as build_f2_actuals,
)
from xinao.foundation.assertion_verifiers.f3_assertion_actuals import (
    ASSERTION_IDS as F3_ASSERTION_IDS,
)
from xinao.foundation.assertion_verifiers.f3_assertion_actuals import (
    build_assertion_actuals_v1 as build_f3_actuals,
)
from xinao.foundation.research_weight_inputs import (
    DEFAULT_EXTERNAL_SYNTHESIS_PATH,
    DEFAULT_PRIOR_DRAFT_PATH,
    DEFAULT_SERVICE_GRAPH_PATH,
)

BLUEPRINT_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\01_主线入口"
    r"\blueprint.v1_已合并工具与执行纪律.json"
)
INPUT_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence"
    r"\foundation-closure-20260714T203234\input_bytes"
)
F1_F2_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence"
    r"\xinao-f1-f2-evidence-20260714T195300"
)
F3_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence"
    r"\xinao-f3-evidence-20260714T200713"
)

INPUT_PATHS = {
    "active_quote_projection_sha256": INPUT_ROOT / "active_quote_projection_sha256.input.json",
    "baseline_sha256": INPUT_ROOT / "baseline_sha256.csv",
    "compiler_code_sha256": INPUT_ROOT / "compiler_code_sha256.input.json",
    "compiler_config_sha256": INPUT_ROOT / "compiler_config_sha256.input.json",
    "dataset_sha256": INPUT_ROOT / "dataset_sha256.txt",
    "f3_external_synthesis_sha256": DEFAULT_EXTERNAL_SYNTHESIS_PATH,
    "f3_prior_draft_sha256": DEFAULT_PRIOR_DRAFT_PATH,
    "f3_service_graph_sha256": DEFAULT_SERVICE_GRAPH_PATH,
    "play_catalog_sha256": INPUT_ROOT / "play_catalog_sha256.v1.json",
    "rule_semantic_map_sha256": INPUT_ROOT / "rule_semantic_map_sha256.v1.json",
}


@dataclass(frozen=True)
class BlockCase:
    block_id: str
    module: str
    assertion_ids: tuple[str, ...]
    artifact_files: dict[str, Path]
    build: Callable[[dict[str, Any]], dict[str, Any]]


CASES = (
    BlockCase(
        block_id="F1_settlement_world",
        module="xinao.foundation.assertion_verifiers.f1_assertion_actuals",
        assertion_ids=F1_ASSERTION_IDS,
        artifact_files={
            "RuleSemanticMapVersion": F1_F2_ROOT / "f1_rule_semantic_map.v1.json",
            "ExpectedSelectionDomainManifestVersion": (
                F1_F2_ROOT / "f1_registry_selection_domain.v1.json"
            ),
            "AtomicTicketBindingVersion": F1_F2_ROOT / "atomic_ticket_bindings.v1.json",
            "RuleSetVersion": F1_F2_ROOT / "f1_rule_set.v1.json",
            "SettlementFunctionSetVersion": (F1_F2_ROOT / "f1_settlement_function_set.v1.json"),
            "EventMatrixSnapshot": F1_F2_ROOT / "event_matrix_snapshot.v1.json",
            "WorldSnapshot": F1_F2_ROOT / "world_snapshot.v1.json",
        },
        build=build_f1_actuals,
    ),
    BlockCase(
        block_id="F2_issuer_settlement_cost_space",
        module="xinao.foundation.assertion_verifiers.f2_assertion_actuals",
        assertion_ids=F2_ASSERTION_IDS,
        artifact_files={
            "SettlementProbabilitySnapshotVersion": (
                F1_F2_ROOT / "f2_probability_snapshot.v1.json"
            ),
            "RebateScheduleVersion": F1_F2_ROOT / "f2_rebate_schedule.v1.json",
            "SettlementCostSurfaceVersion": F1_F2_ROOT / "f2_settlement_cost_surface.v1.json",
            "OddsSpaceBenchmarkVersion": F1_F2_ROOT / "f2_odds_space_benchmark.v1.json",
            "SettlementCostCompileReport": F1_F2_ROOT / "f2_compile_report.v1.json",
        },
        build=build_f2_actuals,
    ),
    BlockCase(
        block_id="F3_research_weight",
        module="xinao.foundation.assertion_verifiers.f3_assertion_actuals",
        assertion_ids=F3_ASSERTION_IDS,
        artifact_files={
            "ResearchAttentionPriorVersion": (F3_ROOT / "f3_research_attention_prior.v1.json"),
            "ResearchWeightBaselineVersion": (F3_ROOT / "f3_research_weight_baseline.v1.json"),
            "ActiveResearchSurfaceVersion": F3_ROOT / "f3_active_research_surface.v1.json",
            "ResearchPortfolioPolicyVersion": (F3_ROOT / "f3_research_portfolio_policy.v1.json"),
            "SourceDependencyGraphVersion": (F3_ROOT / "f3_source_dependency_graph.v1.json"),
            "ContentServiceGraphVersion": F3_ROOT / "f3_content_service_graph.v1.json",
        },
        build=build_f3_actuals,
    ),
)

LOCAL_EVIDENCE_AVAILABLE = (
    os.environ.get("XINAO_RUN_RETAINED_FOUNDATION_ASSERTION_TESTS") == "1"
    and BLUEPRINT_PATH.is_file()
    and all(
        path.is_file()
        for path in (
            *INPUT_PATHS.values(),
            *(path for case in CASES for path in case.artifact_files.values()),
        )
    )
)
pytestmark = pytest.mark.skipif(
    not LOCAL_EVIDENCE_AVAILABLE,
    reason="current retained foundation evidence is not available on this machine",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(case: BlockCase) -> dict[str, Any]:
    artifact_refs: dict[str, dict[str, str]] = {}
    for artifact_type, path in case.artifact_files.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        artifact_refs[artifact_type] = {
            "path": str(path),
            "sha256": _sha256(path),
            "version": str(
                payload.get("version_id") or payload.get("schema_version") or artifact_type
            ),
        }
    return {
        "block_id": case.block_id,
        "input_refs": {
            key: {"path": str(path), "sha256": _sha256(path)} for key, path in INPUT_PATHS.items()
        },
        "artifact_refs": artifact_refs,
        "required_assertion_ids": list(case.assertion_ids),
    }


def _expected(case: BlockCase) -> dict[str, Any]:
    blueprint = json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))
    return blueprint["foundation_closure_profile"]["blocks"][case.block_id]["required_assertions"]


def _fresh_actuals(case: BlockCase, request: dict[str, Any], request_path: Path) -> dict[str, Any]:
    request_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
    script = (
        "import importlib,json,sys;"
        "module=importlib.import_module(sys.argv[1]);"
        "request=json.loads(open(sys.argv[2],encoding='utf-8').read());"
        "print(json.dumps(module.build_assertion_actuals_v1(request),sort_keys=True))"
    )
    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script, case.module, str(request_path)],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
        },
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.block_id)
def test_current_retained_artifacts_recompute_exact_blueprint_actuals(
    tmp_path: Path, case: BlockCase
) -> None:
    actuals = _fresh_actuals(case, _request(case), tmp_path / "request.json")

    assert tuple(sorted(actuals)) == tuple(sorted(case.assertion_ids))
    assert actuals == _expected(case)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.block_id)
def test_missing_artifact_ref_fails_before_recomputation(case: BlockCase) -> None:
    request = _request(case)
    request["artifact_refs"].pop(next(iter(case.artifact_files)))

    with pytest.raises(AssertionActualsError, match="artifact_refs key mismatch"):
        case.build(request)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.block_id)
def test_tampered_artifact_bytes_fail_hash_binding(tmp_path: Path, case: BlockCase) -> None:
    request = _request(case)
    artifact_type = next(iter(case.artifact_files))
    original = case.artifact_files[artifact_type]
    tampered = tmp_path / original.name
    tampered.write_bytes(original.read_bytes() + b"\n")
    request["artifact_refs"][artifact_type]["path"] = str(tampered)

    with pytest.raises(AssertionActualsError, match="hash mismatch"):
        case.build(request)


def test_f3_missing_payload_key_fails_even_with_updated_file_hash(tmp_path: Path) -> None:
    case = CASES[2]
    request = _request(case)
    artifact_type = "ResearchAttentionPriorVersion"
    payload = json.loads(case.artifact_files[artifact_type].read_text(encoding="utf-8"))
    payload.pop("content_sha256")
    tampered = tmp_path / "f3_missing_content_sha256.json"
    tampered.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    request["artifact_refs"][artifact_type].update(
        {"path": str(tampered), "sha256": _sha256(tampered)}
    )

    with pytest.raises(AssertionActualsError, match="retained F3 artifacts are invalid"):
        case.build(request)


@pytest.mark.parametrize("initially_enabled", (True, False))
def test_f1_does_not_override_cyclic_gc_state_when_isolated_phase_fails(
    monkeypatch: pytest.MonkeyPatch, initially_enabled: bool
) -> None:
    original_state = gc.isenabled()

    def fail_isolated_recomputation(_: object) -> dict[str, dict[str, Any]]:
        assert gc.isenabled() is initially_enabled
        raise RuntimeError("isolated phase failed")

    monkeypatch.setattr(
        verifier_common,
        "compile_registry_input",
        lambda _: ({}, object()),
    )
    monkeypatch.setattr(
        verifier_common,
        "run_f1_isolated_recomputation",
        fail_isolated_recomputation,
    )
    try:
        if initially_enabled:
            gc.enable()
        else:
            gc.disable()
        with pytest.raises(RuntimeError, match="isolated phase failed"):
            build_f1_actuals(_request(CASES[0]))
        assert gc.isenabled() is initially_enabled
    finally:
        if original_state:
            gc.enable()
        else:
            gc.disable()
