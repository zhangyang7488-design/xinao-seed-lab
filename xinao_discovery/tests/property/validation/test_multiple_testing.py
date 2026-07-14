from __future__ import annotations

import numpy as np

from xinao.validation import apply_multiple_testing


def test_seeded_global_null_controls_holm_family_error() -> None:
    rng = np.random.default_rng(20260714)
    family_rejections = []
    total_rejections = 0
    for _ in range(400):
        rejected, _ = apply_multiple_testing(rng.uniform(size=20), method="HOLM")
        family_rejections.append(bool(np.any(rejected)))
        total_rejections += int(np.sum(rejected))
    assert np.mean(family_rejections) <= 0.07
    assert total_rejections <= 30


def test_seeded_global_null_controls_bh_false_discovery_rate() -> None:
    rng = np.random.default_rng(20260714)
    proportions = []
    for _ in range(400):
        rejected, _ = apply_multiple_testing(rng.uniform(size=20), method="BH")
        proportions.append(float(np.mean(rejected)))
    assert np.mean(proportions) <= 0.01
