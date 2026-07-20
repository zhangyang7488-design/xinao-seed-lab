"""Deterministic statistical court for the first special-number candidate."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from xinao.canonical import canonical_sha256

from .protocol import PROTOCOL, ValidationProtocolVersion, partition_name

if TYPE_CHECKING:
    from xinao.world.builder import DrawRecord


def _number(value: float) -> str:
    import numpy as np

    if not np.isfinite(value):
        raise ValueError("statistical result must be finite")
    return f"{value:.12f}"


class FeatureObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_name: str
    feature_timestamp: datetime
    target_open_time: datetime


class CandidateReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_ref: str
    candidate_ref: Literal["candidate.constant-01-panel-b.v0"]
    protocol_ref: Literal["validation-protocol.special-number.v1"]
    split_ref: Literal["dataset-split.verified-913.v1"]
    evaluation_partition: Literal["VALIDATION"]
    sample_size: int
    hit_count: int
    mean_cost_adjusted_net: str
    lower_90: str
    upper_90: str
    exact_binomial_pvalue: str
    brier_score: str
    maximum_positive_contribution: str
    multiple_testing_method: Literal["HOLM"]
    adjusted_pvalue: str
    verdict: Literal["ACTION", "NO_ACTION"]
    no_action_reasons: tuple[str, ...]
    output_hash: str | None = None

    def with_hash(self) -> CandidateReport:
        content = self.model_dump(mode="json", exclude={"output_hash"})
        return self.model_copy(update={"output_hash": canonical_sha256(content)})


def validate_temporal_features(features: list[FeatureObservation]) -> None:
    for feature in features:
        if feature.feature_timestamp >= feature.target_open_time:
            raise ValueError(f"future leakage detected in feature {feature.feature_name}")


def walk_forward_folds(
    sample_size: int, protocol: ValidationProtocolVersion = PROTOCOL
) -> tuple[tuple[Any, Any], ...]:
    import numpy as np
    from sklearn.model_selection import TimeSeriesSplit

    splitter = TimeSeriesSplit(
        n_splits=protocol.walk_forward_splits,
        gap=protocol.purge_embargo_draws,
    )
    folds = tuple(splitter.split(np.arange(sample_size)))
    for train, test in folds:
        if train[-1] + protocol.purge_embargo_draws >= test[0]:
            raise AssertionError("walk-forward purge/embargo invariant failed")
        if train[-1] >= test[0]:
            raise AssertionError("walk-forward fold contains future leakage")
    return folds


def stationary_mean_interval(
    values: Any,
    *,
    protocol: ValidationProtocolVersion = PROTOCOL,
) -> tuple[float, float]:
    import numpy as np
    from arch.bootstrap import StationaryBootstrap

    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or len(array) < protocol.bootstrap_block_size * 2:
        raise ValueError("stationary bootstrap requires a sufficiently long 1-D series")
    bootstrap = StationaryBootstrap(
        protocol.bootstrap_block_size,
        array,
        seed=protocol.random_seed,
    )
    interval = bootstrap.conf_int(
        np.mean,
        reps=protocol.bootstrap_replications,
        method="percentile",
        size=0.90,
    )
    return float(interval[0, 0]), float(interval[1, 0])


def circular_shift_permutation_pvalue(
    scores: Any,
    outcomes: Any,
    *,
    protocol: ValidationProtocolVersion = PROTOCOL,
) -> float:
    import numpy as np

    left = np.asarray(scores, dtype=float)
    right = np.asarray(outcomes, dtype=float)
    if left.shape != right.shape or left.ndim != 1 or len(left) < 3:
        raise ValueError("permutation inputs must be equal-length 1-D arrays")
    observed = abs(float(np.corrcoef(left, right)[0, 1]))
    rng = np.random.default_rng(protocol.random_seed)
    shifts = rng.integers(1, len(right), size=protocol.permutation_replications)
    null = [abs(float(np.corrcoef(left, np.roll(right, int(shift)))[0, 1])) for shift in shifts]
    return (1 + sum(value >= observed for value in null)) / (len(null) + 1)


def apply_multiple_testing(pvalues: Any, *, method: Literal["BH", "HOLM"]) -> tuple[Any, Any]:
    import numpy as np
    from statsmodels.stats.multitest import multipletests

    statsmodels_method = "fdr_bh" if method == "BH" else "holm"
    rejected, adjusted, _, _ = multipletests(
        np.asarray(pvalues, dtype=float),
        alpha=0.05,
        method=statsmodels_method,
    )
    return rejected, adjusted


def _candidate_returns(draws: list[DrawRecord]) -> tuple[Any, int]:
    import numpy as np

    from xinao.settlement import settle_special_number

    values: list[float] = []
    hits = 0
    for draw in draws:
        result = settle_special_number(
            selected_number=1,
            actual_special_number=draw.special_number,
            panel="B",
            stake="1.0000",
        )
        hits += int(result.hit)
        values.append(float(result.gross_return) - float(result.stake))
    return np.asarray(values), hits


def validate_candidate(
    draws: list[DrawRecord],
    *,
    protocol: ValidationProtocolVersion = PROTOCOL,
) -> CandidateReport:
    import numpy as np
    from scipy.stats import binomtest

    validation = [draw for draw in draws if partition_name(draw) == "VALIDATION"]
    if len(validation) != 184:
        raise ValueError("candidate validation partition cardinality changed")
    _ = walk_forward_folds(len(validation), protocol)
    net, hits = _candidate_returns(validation)
    lower, upper = stationary_mean_interval(net, protocol=protocol)
    pvalue = float(binomtest(hits, len(validation), p=1 / 49, alternative="greater").pvalue)
    _, adjusted = apply_multiple_testing(np.asarray([pvalue]), method="HOLM")
    predicted = np.full(len(validation), 1 / 49)
    observed = np.asarray([int(draw.special_number == 1) for draw in validation])
    brier = float(np.mean((predicted - observed) ** 2))
    positive = net[net > 0]
    concentration = 0.0 if positive.size == 0 else float(np.max(positive) / np.sum(positive))
    reasons: list[str] = []
    if lower <= 0:
        reasons.append("LOWER_90_NOT_POSITIVE")
    if adjusted[0] > 0.05:
        reasons.append("HOLM_NOT_SIGNIFICANT")
    if concentration > 0.25:
        reasons.append("POSITIVE_CONTRIBUTION_CONCENTRATED")
    report = CandidateReport(
        report_ref="validation-report.candidate.constant-01-panel-b.v0",
        candidate_ref="candidate.constant-01-panel-b.v0",
        protocol_ref=protocol.protocol_ref,
        split_ref=protocol.split_ref,
        evaluation_partition="VALIDATION",
        sample_size=len(validation),
        hit_count=hits,
        mean_cost_adjusted_net=_number(float(np.mean(net))),
        lower_90=_number(lower),
        upper_90=_number(upper),
        exact_binomial_pvalue=_number(pvalue),
        brier_score=_number(brier),
        maximum_positive_contribution=_number(concentration),
        multiple_testing_method="HOLM",
        adjusted_pvalue=_number(float(adjusted[0])),
        verdict="NO_ACTION" if reasons else "ACTION",
        no_action_reasons=tuple(reasons),
    )
    return report.with_hash()
