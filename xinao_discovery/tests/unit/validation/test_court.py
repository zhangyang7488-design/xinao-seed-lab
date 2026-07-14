from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from xinao.validation import (
    FeatureObservation,
    apply_multiple_testing,
    circular_shift_permutation_pvalue,
    stationary_mean_interval,
    validate_candidate,
    validate_temporal_features,
)
from xinao.validation.court import walk_forward_folds
from xinao.world.builder import load_draws


def test_walk_forward_folds_have_real_gap_and_no_future_rows() -> None:
    for train, test in walk_forward_folds(184):
        assert train[-1] + 28 < test[0]


def test_stationary_bootstrap_is_reproducible() -> None:
    values = np.sin(np.arange(184) / 9) + 0.1
    first = stationary_mean_interval(values)
    second = stationary_mean_interval(values)
    assert first == second
    assert first[0] < np.mean(values) < first[1]


def test_known_signal_survives_bh_and_holm() -> None:
    pvalues = np.asarray([1e-12, 0.2, 0.4, 0.8])
    bh, _ = apply_multiple_testing(pvalues, method="BH")
    holm, _ = apply_multiple_testing(pvalues, method="HOLM")
    assert bh.tolist() == holm.tolist() == [True, False, False, False]


def test_circular_shift_permutation_detects_aligned_signal() -> None:
    scores = np.sin(np.arange(200) / 7)
    outcomes = scores + np.cos(np.arange(200) / 11) * 0.05
    assert circular_shift_permutation_pvalue(scores, outcomes) <= 0.01


def test_future_leakage_is_rejected() -> None:
    open_time = datetime(2026, 7, 15, tzinfo=UTC)
    validate_temporal_features(
        [
            FeatureObservation(
                feature_name="safe",
                feature_timestamp=open_time - timedelta(1),
                target_open_time=open_time,
            )
        ]
    )
    with pytest.raises(ValueError, match="future leakage"):
        validate_temporal_features(
            [
                FeatureObservation(
                    feature_name="leak", feature_timestamp=open_time, target_open_time=open_time
                )
            ]
        )


def test_real_baseline_candidate_is_repeatable_and_may_no_action() -> None:
    draws = load_draws()
    first = validate_candidate(draws)
    second = validate_candidate(draws)
    assert first == second
    assert first.verdict == "NO_ACTION"
    assert first.output_hash is not None
    assert "LOWER_90_NOT_POSITIVE" in first.no_action_reasons
