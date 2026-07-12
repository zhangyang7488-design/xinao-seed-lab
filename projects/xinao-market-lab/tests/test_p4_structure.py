from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from xinao_market_lab.inputs import InputLayout, audit_inputs_p2, load_raw_draws
from xinao_market_lab.models import P3AcceptancePin, P4JudgeGateResult, P4Protocol
from xinao_market_lab.structure import (
    TEST_IDS,
    build_contamination_pin_artifact,
    build_null_family_artifact,
    build_p4_judge,
    build_p4_protocol,
    build_test_results,
    contamination_evidence,
    draw_array,
    observed_score_detail,
    sample_joint_without_replacement,
    score_joint_draws,
    simulate_shared_null,
    structure_test_ledger_bytes,
    validate_p4_protocol,
)

INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")


def p3_pin() -> P3AcceptancePin:
    return P3AcceptancePin(
        run_directory="D:/fixture/p3",
        input_snapshot_id="a" * 64,
        run_manifest_sha256="b" * 64,
        protocol_artifact_sha256="c" * 64,
        protocol_hash="d" * 64,
        trial_ledger_sha256="e" * 64,
        trial_chain_tip="f" * 64,
        judge_gate_sha256="1" * 64,
    )


def protocol_fixture() -> P4Protocol:
    return build_p4_protocol(snapshot_id="a" * 64, p3_evidence=p3_pin())


def test_protocol_freezes_contamination_family_rng_and_claim_boundary() -> None:
    protocol = protocol_fixture()
    validate_p4_protocol(protocol, snapshot_id="a" * 64, p3_evidence=p3_pin())
    assert tuple(test.test_id for test in protocol.spec.family) == TEST_IDS
    assert protocol.spec.family_size == 5
    assert protocol.spec.rng_bit_generator == "PCG64"
    assert protocol.spec.rng_seed == 2026071104
    assert protocol.spec.n_mc == 19_999
    assert protocol.spec.batch_size == 128
    assert protocol.spec.fold_sizes == (301, 301, 301, 301)
    assert protocol.spec.economic_claim_permitted is False
    assert build_null_family_artifact(protocol, "2" * 64)["collision_test_in_family"] is False
    assert build_contamination_pin_artifact(protocol)["gate_in_holm_family"] is False

    tampered = protocol.spec.model_dump(mode="python")
    tampered["rng_seed"] = 7
    with pytest.raises(ValidationError):
        type(protocol.spec).model_validate(tampered, strict=True)

    tampered = protocol.spec.model_dump(mode="python")
    tampered["family"] = (*tampered["family"], tampered["family"][0])
    tampered["family_size"] = 6
    with pytest.raises(ValidationError):
        type(protocol.spec).model_validate(tampered, strict=True)


def test_sampler_is_reproducible_unique_and_joint_scores_are_integer() -> None:
    first_rng = np.random.Generator(np.random.PCG64(123))
    second_rng = np.random.Generator(np.random.PCG64(123))
    first = sample_joint_without_replacement(first_rng, batch_size=5, draw_count=8)
    second = sample_joint_without_replacement(second_rng, batch_size=5, draw_count=8)
    assert np.array_equal(first, second)
    assert not np.any(np.sort(first, axis=2)[:, :, 1:] == np.sort(first, axis=2)[:, :, :-1])
    scores = score_joint_draws(first, fold_sizes=(2, 2, 2, 2))
    assert scores.shape == (5, 5)
    assert scores.dtype == np.int64
    assert np.all(scores >= 0)


def test_small_null_ledger_is_hash_linked_and_reproducible() -> None:
    rng = np.random.Generator(np.random.PCG64(5))
    values = sample_joint_without_replacement(rng, batch_size=1, draw_count=8)[0]
    observed = score_joint_draws(values[np.newaxis, :, :], fold_sizes=(2, 2, 2, 2))[0]
    first = simulate_shared_null(
        observed_scores=observed,
        draw_count=8,
        fold_sizes=(2, 2, 2, 2),
        seed=99,
        n_mc=17,
        batch_size=4,
    )
    second = simulate_shared_null(
        observed_scores=observed,
        draw_count=8,
        fold_sizes=(2, 2, 2, 2),
        seed=99,
        n_mc=17,
        batch_size=4,
    )
    assert first == second
    ledger = first["_ledger_bytes"]
    assert isinstance(ledger, bytes)
    assert hashlib.sha256(ledger).hexdigest() == first["null_score_stream_sha256"]
    rows = [json.loads(line) for line in ledger.splitlines()]
    assert len(rows) == 17
    previous = "0" * 64
    for index, row in enumerate(rows):
        assert row["simulation_index"] == index
        assert len(row["scores"]) == len(TEST_IDS)
        assert all(isinstance(value, int) for value in row["scores"])
        assert row["previous_hash"] == previous
        material = dict(row)
        actual = material.pop("event_hash")
        from xinao_market_lab.inputs import canonical_json_bytes

        assert hashlib.sha256(canonical_json_bytes(material)).hexdigest() == actual
        previous = actual
    assert previous == first["null_score_chain_tip"]


def test_plus_one_and_holm_use_exact_fractions_and_frozen_tie_order() -> None:
    protocol = protocol_fixture()
    null_summary = {
        "observed_scores": [1, 2, 3, 4, 5],
        "exceedance_counts": [99, 99, 199, 9999, 19999],
        "null_score_stream_sha256": "3" * 64,
    }
    results = build_test_results(
        protocol=protocol,
        protocol_artifact_sha256="4" * 64,
        null_summary=null_summary,
    )
    assert tuple(record.test_id for record in results) == TEST_IDS
    assert results[0].raw_p_numerator == results[1].raw_p_numerator == 100
    assert results[0].raw_p_fraction == results[1].raw_p_fraction == "1/200"
    assert results[0].holm_rank == 1
    assert results[1].holm_rank == 2
    assert results[0].adjusted_p_fraction == "1/40"
    assert results[1].adjusted_p_fraction == "1/40"
    assert results[-1].adjusted_p_fraction == "1"
    assert len(structure_test_ledger_bytes(results).splitlines()) == 5


def test_judge_is_derived_from_five_tests_and_schema_blocks_claim_escalation() -> None:
    protocol = protocol_fixture()
    results = build_test_results(
        protocol=protocol,
        protocol_artifact_sha256="4" * 64,
        null_summary={
            "observed_scores": [1, 2, 3, 4, 5],
            "exceedance_counts": [19_999] * 5,
            "null_score_stream_sha256": "3" * 64,
        },
    )
    judge = build_p4_judge(
        protocol=protocol,
        protocol_artifact_sha256="4" * 64,
        test_results=results,
        checks={"all_mechanics": True},
    )
    assert judge.structure_status == "STRUCTURE_NULL_RETAINED"
    assert judge.economic_claim_status == "ECONOMIC_CLAIM_BLOCKED"
    invalid = judge.model_dump(mode="python")
    invalid["ranking_permitted"] = True
    with pytest.raises(ValidationError):
        P4JudgeGateResult.model_validate(invalid, strict=True)


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user input is unavailable")
def test_actual_contamination_and_observed_integer_statistic_pins() -> None:
    layout = InputLayout.from_root(INPUT_ROOT)
    draws, _quote, _audit, lineage, _catalog = audit_inputs_p2(layout)
    records, summary = contamination_evidence(
        raw_draws=load_raw_draws(layout),
        canonical_draws=draws,
        lineage=lineage,
    )
    assert len(records) == 5
    assert summary["residual_alias_count"] == 0
    assert [row["observed_pair_collisions"] for row in summary["collision_diagnostics"]] == [
        5,
        5,
        5,
    ]
    assert observed_score_detail(draw_array(draws), fold_sizes=(301, 301, 301, 301)) == {
        "T_special": 38_514,
        "T_pos_each": [50_764, 47_726, 69_188, 48_804, 59_388, 69_580],
        "T_pos_max": 69_580,
        "T_regular_incl": 322_812,
        "lag1_equal_count": 22,
        "T_lag1": 125,
        "T_fold_each": [12_348, 12_250, 10_682, 12_348],
        "T_fold": 12_348,
    }
