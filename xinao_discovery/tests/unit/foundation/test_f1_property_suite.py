from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from xinao.foundation.f1_property_suite import (
    F1PropertySuiteEvidence,
    compile_f1_property_suite_evidence,
    current_property_source_hashes,
)
from xinao.foundation.f1_replay import compile_f1_replay_evidence
from xinao.foundation.selection_manifest import load_play_catalog
from xinao.foundation.semantics_registry import compile_semantics_registry
from xinao.foundation.world_compile import DEFAULT_AUTHORITY_DATASET_PATH, compile_functional_world


@pytest.fixture(scope="module")
def property_evidence() -> F1PropertySuiteEvidence:
    catalog = load_play_catalog()
    registry = compile_semantics_registry(catalog)
    world = compile_functional_world(registry, DEFAULT_AUTHORITY_DATASET_PATH).world_snapshot
    replay = compile_f1_replay_evidence(registry, world)
    return compile_f1_property_suite_evidence(
        catalog=catalog,
        registry=registry,
        world=world,
        replay=replay,
    )


def test_property_suite_executes_exact_family_matrix_and_full_source_coverage(
    property_evidence: F1PropertySuiteEvidence,
) -> None:
    evidence = property_evidence

    assert evidence.family_count == 13
    assert evidence.property_check_count == 39
    assert evidence.property_kind_counts == {"POSITIVE": 13, "NEGATIVE": 13, "BOUNDARY": 13}
    assert len(evidence.covered_baseline_ids) == 416
    assert len(evidence.covered_semantic_family_refs) == 30
    assert len(evidence.covered_settlement_function_refs) == 32
    assert len(evidence.covered_atomic_binding_ids) == 37
    assert all(check.generated_draw_example_count == 64 for check in evidence.checks)
    assert all(check.failure_count == 0 for check in evidence.checks)
    assert len({check.generation_seed_sha256 for check in evidence.checks}) == 39
    assert sum(check.settlement_evaluation_count for check in evidence.checks) >= 39 * 64
    assert evidence.hypothesis_settings["draw_sample_mode"] == (
        "sha256_ranked_non_seed_draws_v1"
    )


def test_positive_and_negative_replay_seeds_are_independently_rederived(
    property_evidence: F1PropertySuiteEvidence,
) -> None:
    by_kind = {kind: [] for kind in ("POSITIVE", "NEGATIVE", "BOUNDARY")}
    for check in property_evidence.checks:
        by_kind[check.property_kind].append(check.seed_oracle_outcome)

    assert set(by_kind["POSITIVE"]) == {"HIT"}
    assert set(by_kind["NEGATIVE"]) == {"MISS"}
    assert len(by_kind["BOUNDARY"]) == 13


def test_property_suite_rejects_forged_execution_count(
    property_evidence: F1PropertySuiteEvidence,
) -> None:
    payload = property_evidence.model_dump(mode="json")
    payload["checks"][0]["generated_draw_example_count"] = 63

    with pytest.raises(ValidationError):
        F1PropertySuiteEvidence.model_validate(payload)


def test_property_suite_binds_the_two_current_independent_sources(
    property_evidence: F1PropertySuiteEvidence,
) -> None:
    assert property_evidence.source_hashes == current_property_source_hashes()


def test_property_suite_is_content_address_stable_in_a_fresh_process(
    property_evidence: F1PropertySuiteEvidence,
) -> None:
    script = (
        "from xinao.foundation.selection_manifest import load_play_catalog;"
        "from xinao.foundation.semantics_registry import compile_semantics_registry;"
        "from xinao.foundation.world_compile import "
        "DEFAULT_AUTHORITY_DATASET_PATH,compile_functional_world;"
        "from xinao.foundation.f1_replay import compile_f1_replay_evidence;"
        "from xinao.foundation.f1_property_suite import compile_f1_property_suite_evidence;"
        "c=load_play_catalog();r=compile_semantics_registry(c);"
        "w=compile_functional_world(r,DEFAULT_AUTHORITY_DATASET_PATH).world_snapshot;"
        "q=compile_f1_replay_evidence(r,w);"
        "print(compile_f1_property_suite_evidence("
        "catalog=c,registry=r,world=w,replay=q).model_dump_json())"
    )
    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        check=False,
        encoding="utf-8",
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    fresh = json.loads(completed.stdout)
    current = property_evidence.model_dump(mode="json")
    differences = [
        key
        for key in sorted(set(current) | set(fresh))
        if key != "checks" and current.get(key) != fresh.get(key)
    ]
    for index, (current_check, fresh_check) in enumerate(
        zip(current["checks"], fresh["checks"], strict=True)
    ):
        differences.extend(
            f"checks[{index}].{key}"
            for key in sorted(set(current_check) | set(fresh_check))
            if current_check.get(key) != fresh_check.get(key)
        )
    assert not differences, "\n".join(differences)
