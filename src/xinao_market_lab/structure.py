from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from decimal import Decimal, localcontext
from fractions import Fraction
from math import comb
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .inputs import canonical_json_bytes, sha256_file
from .models import (
    ContaminationMappingPin,
    Draw,
    LineageRecord,
    P3AcceptancePin,
    P4JudgeGateResult,
    P4Protocol,
    P4ProtocolSpec,
    P4TestDefinition,
    P4TestResult,
    P4TombstoneRecord,
)

PINNED_QUARANTINES = (
    ("2023004", "2024004", "expect_year_mismatch_exact_time_alias"),
    ("2024185", "2024156", "later_full_outcome_repetition"),
    ("2025259", "2024340", "later_full_outcome_repetition"),
    ("2025287", "2024335", "later_full_outcome_repetition"),
    ("2026019", "2024300", "later_full_outcome_repetition"),
)

TEST_IDS = ("T_special", "T_pos_max", "T_regular_incl", "T_lag1", "T_fold")

EXPECTED_OBSERVED_DETAIL = {
    "T_special": 38_514,
    "T_pos_each": [50_764, 47_726, 69_188, 48_804, 59_388, 69_580],
    "T_pos_max": 69_580,
    "T_regular_incl": 322_812,
    "lag1_equal_count": 22,
    "T_lag1": 125,
    "T_fold_each": [12_348, 12_250, 10_682, 12_348],
    "T_fold": 12_348,
}

FAMILY_DEFINITIONS = (
    (
        "T_special",
        "49*sum(special_count^2)-n^2",
        "special marginal under joint ordered 6+1 without-replacement null",
    ),
    (
        "T_pos_max",
        "max_position[49*sum(position_count^2)-n^2]",
        "maximum of six ordered regular-position marginals under the shared joint null",
    ),
    (
        "T_regular_incl",
        "49*sum(regular_inclusion_count^2)-(6*n)^2",
        "regular-set inclusion marginal under the shared joint null",
    ),
    (
        "T_lag1",
        "abs(49*equal_adjacent_special-(n-1))",
        "event-order adjacent-special equality under the shared joint null",
    ),
    (
        "T_fold",
        "max_fold[49*sum(fold_special_count^2)-fold_n^2]",
        "maximum special marginal across the four frozen 301-event folds",
    ),
)

SAMPLE_SPACES = (
    ("ordered_regular_6_plus_special", 432_938_943_360),
    ("regular_set_plus_special", 601_304_088),
    ("unordered_seven", 85_900_584),
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def build_p3_acceptance_pin(p3_run: Path, verification: dict[str, Any]) -> P3AcceptancePin:
    p3_run = p3_run.resolve()
    if verification.get("status") != "verified":
        raise ValueError("P4 requires a semantically verified P3 run")
    judge = _read_json(p3_run / "judge_gate.json")
    return P3AcceptancePin(
        run_directory=str(p3_run),
        input_snapshot_id=str(verification["input_snapshot_id"]),
        run_manifest_sha256=sha256_file(p3_run / "run_manifest.json"),
        protocol_artifact_sha256=sha256_file(p3_run / "research_protocol.json"),
        protocol_hash=str(verification["protocol_hash"]),
        trial_ledger_sha256=str(verification["trial_ledger_sha256"]),
        trial_chain_tip=str(verification["trial_chain_tip"]),
        judge_gate_sha256=sha256_file(p3_run / "judge_gate.json"),
        mechanics_status=str(judge["mechanics_status"]),  # type: ignore[arg-type]
        economic_claim_status=str(judge["economic_claim_status"]),  # type: ignore[arg-type]
    )


def build_p4_protocol(*, snapshot_id: str, p3_evidence: P3AcceptancePin) -> P4Protocol:
    pins = tuple(
        ContaminationMappingPin(
            source_expect=source_expect,
            canonical_expect=canonical_expect,
            reason_code=reason_code,  # type: ignore[arg-type]
        )
        for source_expect, canonical_expect, reason_code in PINNED_QUARANTINES
    )
    family = tuple(
        P4TestDefinition(test_id=test_id, statistic=statistic, null_projection=null_projection)  # type: ignore[arg-type]
        for test_id, statistic, null_projection in FAMILY_DEFINITIONS
    )
    spec = P4ProtocolSpec(
        input_snapshot_id=snapshot_id,
        p3_evidence=p3_evidence,
        contamination_pin=pins,
        family=family,
    )
    protocol_hash = hashlib.sha256(canonical_json_bytes(spec.model_dump(mode="json"))).hexdigest()
    return P4Protocol(
        spec=spec,
        protocol_hash=protocol_hash,
        experiment_id=f"experiment-p4-{protocol_hash[:24]}",
    )


def validate_p4_protocol(
    protocol: P4Protocol,
    *,
    snapshot_id: str,
    p3_evidence: P3AcceptancePin,
) -> None:
    expected_hash = hashlib.sha256(canonical_json_bytes(protocol.spec.model_dump(mode="json"))).hexdigest()
    if protocol.protocol_hash != expected_hash:
        raise ValueError("P4 protocol hash mismatch")
    if protocol.experiment_id != f"experiment-p4-{expected_hash[:24]}":
        raise ValueError("P4 experiment id does not derive from the protocol")
    if protocol.spec.input_snapshot_id != snapshot_id:
        raise ValueError("P4 protocol input snapshot mismatch")
    if protocol.spec.p3_evidence != p3_evidence:
        raise ValueError("P4 protocol P3 acceptance pin mismatch")
    if np.__version__ != protocol.spec.numpy_version:
        raise ValueError(
            f"P4 NumPy runtime drift: expected {protocol.spec.numpy_version}, got {np.__version__}"
        )
    if sys.byteorder != protocol.spec.sampler_byte_order:
        raise ValueError("P4 sampler requires the frozen little-endian runtime")


def build_null_family_artifact(protocol: P4Protocol, protocol_artifact_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "experiment_id": protocol.experiment_id,
        "protocol_hash": protocol.protocol_hash,
        "protocol_artifact_sha256": protocol_artifact_sha256,
        "family_size": protocol.spec.family_size,
        "tests": [test.model_dump(mode="json") for test in protocol.spec.family],
        "alpha_fwer_fraction": protocol.spec.alpha_fwer_fraction,
        "multiplicity_method": protocol.spec.multiplicity_method,
        "rng": {
            "bit_generator": protocol.spec.rng_bit_generator,
            "seed": protocol.spec.rng_seed,
            "numpy_version": protocol.spec.numpy_version,
            "n_mc": protocol.spec.n_mc,
            "batch_size": protocol.spec.batch_size,
        },
        "sampler": {
            "algorithm_id": protocol.spec.sampler_algorithm_id,
            "dtype": protocol.spec.sampler_dtype,
            "byte_order": protocol.spec.sampler_byte_order,
            "stream_traversal": protocol.spec.stream_traversal,
            "api": protocol.spec.sampler_api,
            "within_draw_policy": "reject_and_resample_rows_with_any_duplicate",
        },
        "fold_sizes": list(protocol.spec.fold_sizes),
        "null_ledger_contract": protocol.spec.null_ledger_contract,
        "p_value_method": protocol.spec.p_value_method,
        "shared_joint_stream_for_all_tests": True,
        "collision_test_in_family": False,
        "alias_gate_in_family": False,
    }


def build_contamination_pin_artifact(protocol: P4Protocol) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "experiment_id": protocol.experiment_id,
        "protocol_hash": protocol.protocol_hash,
        "lineage_policy_id": protocol.spec.lineage_policy_id,
        "source_draw_count": protocol.spec.source_draw_count,
        "canonical_draw_count": protocol.spec.canonical_draw_count,
        "expected_quarantines": [pin.model_dump(mode="json") for pin in protocol.spec.contamination_pin],
        "identity_spaces": [
            {"identity": identity, "sample_space_size": sample_space}
            for identity, sample_space in SAMPLE_SPACES
        ],
        "gate_is_p_value": False,
        "gate_in_holm_family": False,
        "raw_collision_is_descriptive_only": True,
        "generator_mechanism_claim_permitted": False,
    }


def _identity_keys(draw: Draw) -> dict[str, tuple[Any, ...]]:
    return {
        "ordered_regular_6_plus_special": (*draw.regular_numbers, draw.special),
        "regular_set_plus_special": (*sorted(draw.regular_numbers), draw.special),
        "unordered_seven": tuple(sorted((*draw.regular_numbers, draw.special))),
    }


def _collision_groups(raw_draws: tuple[Draw, ...], identity: str) -> list[list[str]]:
    grouped: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for draw in raw_draws:
        grouped[_identity_keys(draw)[identity]].append(draw.source_expect)
    return sorted(
        (sorted(expects) for expects in grouped.values() if len(expects) > 1),
        key=lambda expects: (expects[0], expects),
    )


def contamination_evidence(
    *,
    raw_draws: tuple[Draw, ...],
    canonical_draws: tuple[Draw, ...],
    lineage: tuple[LineageRecord, ...],
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    if len(raw_draws) != 1_209 or len(canonical_draws) != 1_204 or len(lineage) != 1_209:
        raise ValueError("P4 contamination gate requires the frozen 1209/1204 lineage surface")
    raw_by_expect = {draw.source_expect: draw for draw in raw_draws}
    lineage_by_expect = {record.source_expect: record for record in lineage}
    if len(raw_by_expect) != len(raw_draws) or len(lineage_by_expect) != len(lineage):
        raise ValueError("P4 contamination identities require unique source_expect values")

    quarantines = tuple(record for record in lineage if record.status == "quarantined")
    actual_pins = tuple(
        (record.source_expect, record.canonical_expect, record.reason_code) for record in quarantines
    )
    expected_pins = PINNED_QUARANTINES
    residual_alias_count = len(set(actual_pins).symmetric_difference(expected_pins))
    if actual_pins != expected_pins or residual_alias_count != 0:
        raise ValueError(f"P4 contamination pin mismatch: expected={expected_pins} actual={actual_pins}")

    audit_records: list[dict[str, Any]] = []
    for sequence, (source_expect, canonical_expect, reason_code) in enumerate(expected_pins):
        source_record = lineage_by_expect[source_expect]
        canonical_record = lineage_by_expect[canonical_expect]
        source_draw = raw_by_expect[source_expect]
        canonical_draw = raw_by_expect[canonical_expect]
        identity_matches = {
            identity: _identity_keys(source_draw)[identity] == _identity_keys(canonical_draw)[identity]
            for identity, _sample_space in SAMPLE_SPACES
        }
        if (
            not all(identity_matches.values())
            or source_record.outcome_sha256 != canonical_record.outcome_sha256
        ):
            raise ValueError(f"P4 pinned contamination pair identity mismatch: {source_expect}")
        material = {
            "schema_version": 1,
            "sequence": sequence,
            "source_expect": source_expect,
            "canonical_expect": canonical_expect,
            "reason_code": reason_code,
            "source_open_time": source_draw.open_time.isoformat(),
            "canonical_open_time": canonical_draw.open_time.isoformat(),
            "outcome_sha256": source_record.outcome_sha256,
            "identity_matches": identity_matches,
            "interpretation": "pinned_source_copy_or_alias_not_generator_mechanism_evidence",
        }
        audit_records.append(
            {
                **material,
                "record_hash": hashlib.sha256(canonical_json_bytes(material)).hexdigest(),
            }
        )

    pair_count = comb(len(raw_draws), 2)
    collision_rows: list[dict[str, Any]] = []
    for identity, sample_space in SAMPLE_SPACES:
        groups = _collision_groups(raw_draws, identity)
        observed_pairs = sum(comb(len(group), 2) for group in groups)
        expectation = Fraction(pair_count, sample_space)
        with localcontext() as context:
            context.prec = 30
            expectation_decimal = Decimal(expectation.numerator) / Decimal(expectation.denominator)
        collision_rows.append(
            {
                "identity": identity,
                "sample_space_size": sample_space,
                "source_pair_count": pair_count,
                "expected_pair_collisions_fraction": str(expectation),
                "expected_pair_collisions_decimal": format(expectation_decimal, ".15f"),
                "observed_pair_collisions": observed_pairs,
                "observed_collision_groups": groups,
                "in_statistical_family": False,
                "p_value_computed": False,
            }
        )
    if any(row["observed_pair_collisions"] != 5 for row in collision_rows):
        raise ValueError(f"P4 raw collision pin mismatch: {collision_rows}")

    summary = {
        "schema_version": 1,
        "gate_status": "CONTAMINATION_PIN_MATCHED",
        "lineage_policy_id": "validation-ranked-exact-time-alias-then-chronological-outcome-v2",
        "raw_source_draw_count": len(raw_draws),
        "canonical_draw_count": len(canonical_draws),
        "pinned_quarantine_count": len(audit_records),
        "residual_alias_count": residual_alias_count,
        "collision_diagnostics": collision_rows,
        "statistical_family_membership": False,
        "generator_mechanism_claim_permitted": False,
        "interpretation": (
            "The five raw-source pairs are descriptive source duplication or curation evidence. "
            "They are not a p-value and do not identify a generating mechanism."
        ),
    }
    return tuple(audit_records), summary


def contamination_ledger_bytes(records: tuple[dict[str, Any], ...]) -> bytes:
    for record in records:
        material = dict(record)
        actual_hash = material.pop("record_hash")
        if hashlib.sha256(canonical_json_bytes(material)).hexdigest() != actual_hash:
            raise ValueError("P4 contamination record hash mismatch")
    return b"".join(canonical_json_bytes(record) for record in records)


def draw_array(draws: tuple[Draw, ...]) -> NDArray[np.int16]:
    return np.asarray(
        [(*draw.regular_numbers, draw.special) for draw in draws],
        dtype=np.int16,
    )


def _counts_49(values: NDArray[np.int16]) -> NDArray[np.int64]:
    batch = values.shape[0]
    offsets_shape = (batch, *(1 for _ in values.shape[1:]))
    offsets = (np.arange(batch, dtype=np.int64) * 49).reshape(offsets_shape)
    encoded = values.astype(np.int64) - 1 + offsets
    return np.bincount(encoded.ravel(), minlength=batch * 49).reshape(batch, 49)


def score_joint_draws(
    values: NDArray[np.int16], *, fold_sizes: tuple[int, int, int, int]
) -> NDArray[np.int64]:
    if values.ndim != 3 or values.shape[2] != 7:
        raise ValueError("P4 score input must be batch x draws x ordered-7")
    batch, draw_count, _width = values.shape
    if sum(fold_sizes) != draw_count or any(size < 1 for size in fold_sizes):
        raise ValueError("P4 fold sizes must cover the score input exactly")
    sorted_values = np.sort(values, axis=2)
    if np.any(sorted_values[:, :, 1:] == sorted_values[:, :, :-1]):
        raise ValueError("P4 joint score input contains within-draw duplicate numbers")

    special_counts = _counts_49(values[:, :, 6])
    special_score = 49 * np.square(special_counts).sum(axis=1) - draw_count**2

    position_scores = np.empty((batch, 6), dtype=np.int64)
    for position in range(6):
        counts = _counts_49(values[:, :, position])
        position_scores[:, position] = 49 * np.square(counts).sum(axis=1) - draw_count**2
    position_max_score = position_scores.max(axis=1)

    regular_counts = _counts_49(values[:, :, :6])
    regular_total = 6 * draw_count
    regular_score = 49 * np.square(regular_counts).sum(axis=1) - regular_total**2

    equal_adjacent = (values[:, 1:, 6] == values[:, :-1, 6]).sum(axis=1, dtype=np.int64)
    lag1_score = np.abs(49 * equal_adjacent - (draw_count - 1))

    fold_scores: list[NDArray[np.int64]] = []
    start = 0
    for fold_size in fold_sizes:
        counts = _counts_49(values[:, start : start + fold_size, 6])
        fold_scores.append(49 * np.square(counts).sum(axis=1) - fold_size**2)
        start += fold_size
    fold_max_score = np.column_stack(fold_scores).max(axis=1)
    return np.column_stack(
        (special_score, position_max_score, regular_score, lag1_score, fold_max_score)
    ).astype(np.int64, copy=False)


def observed_score_detail(
    values: NDArray[np.int16], *, fold_sizes: tuple[int, int, int, int]
) -> dict[str, Any]:
    if values.ndim != 2:
        raise ValueError("P4 observed values must be draws x ordered-7")
    scores = score_joint_draws(values[np.newaxis, :, :], fold_sizes=fold_sizes)[0]
    draw_count = values.shape[0]
    position_each = []
    for position in range(6):
        counts = np.bincount(values[:, position].astype(np.int64) - 1, minlength=49)
        position_each.append(int(49 * np.square(counts).sum() - draw_count**2))
    fold_each = []
    start = 0
    for fold_size in fold_sizes:
        counts = np.bincount(
            values[start : start + fold_size, 6].astype(np.int64) - 1,
            minlength=49,
        )
        fold_each.append(int(49 * np.square(counts).sum() - fold_size**2))
        start += fold_size
    detail = {
        "T_special": int(scores[0]),
        "T_pos_each": position_each,
        "T_pos_max": int(scores[1]),
        "T_regular_incl": int(scores[2]),
        "lag1_equal_count": int((values[1:, 6] == values[:-1, 6]).sum()),
        "T_lag1": int(scores[3]),
        "T_fold_each": fold_each,
        "T_fold": int(scores[4]),
    }
    if draw_count == 1_204 and detail != EXPECTED_OBSERVED_DETAIL:
        raise ValueError(f"P4 observed statistic pin mismatch: {detail}")
    return detail


def sample_joint_without_replacement(
    rng: np.random.Generator, *, batch_size: int, draw_count: int
) -> NDArray[np.int16]:
    values = rng.integers(1, 50, size=(batch_size, draw_count, 7), dtype=np.int16)
    while True:
        ordered = np.sort(values, axis=2)
        invalid = np.any(ordered[:, :, 1:] == ordered[:, :, :-1], axis=2)
        invalid_count = int(invalid.sum())
        if invalid_count == 0:
            return values
        values[invalid] = rng.integers(1, 50, size=(invalid_count, 7), dtype=np.int16)


def simulate_shared_null(
    *,
    observed_scores: NDArray[np.int64],
    draw_count: int,
    fold_sizes: tuple[int, int, int, int],
    seed: int,
    n_mc: int,
    batch_size: int,
) -> dict[str, Any]:
    if observed_scores.shape != (5,):
        raise ValueError("P4 observed score vector must contain exactly five statistics")
    rng = np.random.Generator(np.random.PCG64(seed))
    if type(rng.bit_generator).__name__ != "PCG64":
        raise RuntimeError("P4 requires the explicitly pinned PCG64 bit generator")
    exceedances = np.zeros(5, dtype=np.int64)
    score_min = np.full(5, np.iinfo(np.int64).max, dtype=np.int64)
    score_max = np.zeros(5, dtype=np.int64)
    score_sum = np.zeros(5, dtype=np.int64)
    digest = hashlib.sha256()
    ledger = bytearray()
    previous_hash = "0" * 64
    sentinel_event_hashes: list[str] = []
    completed = 0
    while completed < n_mc:
        current_batch = min(batch_size, n_mc - completed)
        values = sample_joint_without_replacement(
            rng,
            batch_size=current_batch,
            draw_count=draw_count,
        )
        scores = score_joint_draws(values, fold_sizes=fold_sizes)
        exceedances += (scores >= observed_scores).sum(axis=0, dtype=np.int64)
        score_min = np.minimum(score_min, scores.min(axis=0))
        score_max = np.maximum(score_max, scores.max(axis=0))
        score_sum += scores.sum(axis=0, dtype=np.int64)
        for offset, row in enumerate(scores):
            material = {
                "schema_version": 1,
                "simulation_index": completed + offset,
                "scores": [int(value) for value in row],
                "previous_hash": previous_hash,
            }
            event_hash = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
            payload = canonical_json_bytes({**material, "event_hash": event_hash})
            ledger.extend(payload)
            digest.update(payload)
            previous_hash = event_hash
            if len(sentinel_event_hashes) < 3:
                sentinel_event_hashes.append(event_hash)
        completed += current_batch
    rng_state_sha256 = hashlib.sha256(canonical_json_bytes(rng.bit_generator.state)).hexdigest()
    return {
        "schema_version": 1,
        "score_order": list(TEST_IDS),
        "score_stream_serialization": "hash_chained_canonical_jsonl_v1",
        "simulation_count": completed,
        "observed_scores": [int(value) for value in observed_scores],
        "exceedance_counts": [int(value) for value in exceedances],
        "null_score_min": [int(value) for value in score_min],
        "null_score_max": [int(value) for value in score_max],
        "null_score_sum": [int(value) for value in score_sum],
        "null_score_stream_sha256": digest.hexdigest(),
        "null_score_chain_tip": previous_hash,
        "early_stream_sentinel_event_hashes": sentinel_event_hashes,
        "rng_final_state_sha256": rng_state_sha256,
        "_ledger_bytes": bytes(ledger),
    }


def _holm_adjust(raw_p: dict[str, Fraction]) -> dict[str, tuple[int, int, Fraction]]:
    frozen_order = {test_id: index for index, test_id in enumerate(TEST_IDS)}
    if set(raw_p) != set(frozen_order):
        raise ValueError("Holm input must be exactly the frozen P4 family")
    ordered = sorted(raw_p.items(), key=lambda item: (item[1], frozen_order[item[0]]))
    adjusted: dict[str, tuple[int, int, Fraction]] = {}
    running = Fraction(0, 1)
    total = len(ordered)
    for offset, (test_id, raw) in enumerate(ordered):
        rank = offset + 1
        multiplier = total - offset
        running = max(running, min(Fraction(1, 1), raw * multiplier))
        adjusted[test_id] = (rank, multiplier, running)
    return adjusted


def build_test_results(
    *,
    protocol: P4Protocol,
    protocol_artifact_sha256: str,
    null_summary: dict[str, Any],
) -> tuple[P4TestResult, ...]:
    observed = [int(value) for value in null_summary["observed_scores"]]
    exceedances = [int(value) for value in null_summary["exceedance_counts"]]
    denominator = protocol.spec.n_mc + 1
    raw_p = {
        test_id: Fraction(exceedance + 1, denominator)
        for test_id, exceedance in zip(TEST_IDS, exceedances, strict=True)
    }
    adjusted = _holm_adjust(raw_p)
    alpha = Fraction(1, 20)
    results: list[P4TestResult] = []
    for test_id, statistic, exceedance in zip(TEST_IDS, observed, exceedances, strict=True):
        rank, multiplier, adjusted_p = adjusted[test_id]
        results.append(
            P4TestResult(
                experiment_id=protocol.experiment_id,
                protocol_hash=protocol.protocol_hash,
                protocol_artifact_sha256=protocol_artifact_sha256,
                test_id=test_id,  # type: ignore[arg-type]
                observed_statistic=statistic,
                exceedance_count=exceedance,
                raw_p_numerator=exceedance + 1,
                raw_p_fraction=str(raw_p[test_id]),
                holm_rank=rank,
                holm_multiplier=multiplier,
                adjusted_p_fraction=str(adjusted_p),
                decision="REJECT_FWER" if adjusted_p <= alpha else "RETAIN",
                null_score_stream_sha256=str(null_summary["null_score_stream_sha256"]),
            )
        )
    return tuple(results)


def structure_test_ledger_bytes(records: tuple[P4TestResult, ...]) -> bytes:
    if tuple(record.test_id for record in records) != TEST_IDS:
        raise ValueError("P4 structure result ledger must contain exactly the frozen five tests")
    return b"".join(canonical_json_bytes(record.model_dump(mode="json")) for record in records)


def build_p4_tombstones(protocol: P4Protocol) -> tuple[P4TombstoneRecord, ...]:
    definitions = (
        (
            "tombstone-p3-cell-ranking-still-blocked-v1",
            "p3_candidate_ranking",
            ("p3_cells_are_mechanics_only", "payout_basis_unresolved"),
        ),
        (
            "tombstone-structure-reject-is-not-edge-v1",
            "structure_rejection_as_edge",
            ("null_rejection_is_not_predictive_edge", "no_forward_validation"),
        ),
        (
            "tombstone-quote-fill-still-absent-v1",
            "quote_fill_claim",
            ("contemporaneous_quote_absent", "fill_and_liability_absent"),
        ),
        (
            "tombstone-source-verify-false-v1",
            "source_truth_claim",
            ("all_source_rows_verify_false", "mirror_is_not_independent_confirmation"),
        ),
    )
    records: list[P4TombstoneRecord] = []
    for tombstone_id, subject, reason_codes in definitions:
        material = {
            "schema_version": 1,
            "experiment_id": protocol.experiment_id,
            "protocol_hash": protocol.protocol_hash,
            "tombstone_id": tombstone_id,
            "subject": subject,
            "status": "BLOCKED_BY_EVIDENCE",
            "reason_codes": reason_codes,
            "evidence_refs": (
                "p3_acceptance_pin.json",
                "p4_protocol.json",
                "contamination_summary.json",
                "structure_tests.jsonl",
                "judge_gate_p4.json",
            ),
        }
        records.append(
            P4TombstoneRecord(
                **material,  # type: ignore[arg-type]
                record_hash=hashlib.sha256(canonical_json_bytes(material)).hexdigest(),
            )
        )
    return tuple(records)


def p4_tombstone_ledger_bytes(records: tuple[P4TombstoneRecord, ...]) -> bytes:
    for record in records:
        material = record.model_dump(mode="json")
        actual = material.pop("record_hash")
        if hashlib.sha256(canonical_json_bytes(material)).hexdigest() != actual:
            raise ValueError(f"P4 tombstone hash mismatch: {record.tombstone_id}")
    return b"".join(canonical_json_bytes(record.model_dump(mode="json")) for record in records)


def build_p4_judge(
    *,
    protocol: P4Protocol,
    protocol_artifact_sha256: str,
    test_results: tuple[P4TestResult, ...],
    checks: dict[str, bool],
) -> P4JudgeGateResult:
    rejected = tuple(record.test_id for record in test_results if record.decision == "REJECT_FWER")
    return P4JudgeGateResult(
        experiment_id=protocol.experiment_id,
        protocol_hash=protocol.protocol_hash,
        protocol_artifact_sha256=protocol_artifact_sha256,
        structure_status=("STRUCTURE_NULL_REJECTED_FWER" if rejected else "STRUCTURE_NULL_RETAINED"),
        rejected_tests=rejected,  # type: ignore[arg-type]
        checks=checks,
    )
