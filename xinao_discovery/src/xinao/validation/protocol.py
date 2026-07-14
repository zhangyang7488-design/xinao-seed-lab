"""Machine-executable P4/P5 split and validation protocol contracts."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import canonical_sha256
from xinao.contracts.objects import DATASET_REF, DATASET_SHA256
from xinao.world.builder import DrawRecord


class SplitWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["EXPLORATION", "VALIDATION", "CONFIRMATION_VAULT", "FINAL_HOLDOUT"]
    start: date
    end: date
    disclosure: Literal["ROW_LEVEL", "AGGREGATE_ONLY", "SINGLE_FINAL_GATE"]

    @model_validator(mode="after")
    def ordered(self) -> SplitWindow:
        if self.start > self.end:
            raise ValueError("split start must not follow split end")
        return self


class ValidationProtocolVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_ref: Literal["validation-protocol.special-number.v1"] = (
        "validation-protocol.special-number.v1"
    )
    split_ref: Literal["dataset-split.verified-913.v1"] = "dataset-split.verified-913.v1"
    dataset_ref: Literal[DATASET_REF] = DATASET_REF
    walk_forward_splits: Literal[5] = 5
    feature_lookback_draws: Literal[28] = 28
    decision_horizon_draws: Literal[1] = 1
    purge_embargo_draws: Literal[28] = 28
    bootstrap_method: Literal["STATIONARY_BLOCK"] = "STATIONARY_BLOCK"
    bootstrap_block_size: Literal[14] = 14
    bootstrap_replications: Literal[500] = 500
    permutation_method: Literal["CIRCULAR_SHIFT"] = "CIRCULAR_SHIFT"
    permutation_replications: Literal[499] = 499
    exploration_multiple_testing: Literal["BH_FDR_0.05"] = "BH_FDR_0.05"
    confirmation_multiple_testing: Literal["HOLM_FWER_0.05"] = "HOLM_FWER_0.05"
    calibration_metric: Literal["BRIER"] = "BRIER"
    cost_adjusted: Literal[True] = True
    maximum_single_positive_contribution: Literal["0.25"] = "0.25"
    expectation_lower_bound: Literal["ONE_SIDED_90"] = "ONE_SIDED_90"
    random_seed: Literal[20260714] = 20260714
    causal_language: Literal["PREDICTION_OR_CORRELATION_ONLY"] = "PREDICTION_OR_CORRELATION_ONLY"

    @model_validator(mode="after")
    def purge_matches_information_horizon(self) -> ValidationProtocolVersion:
        if self.purge_embargo_draws != max(
            self.feature_lookback_draws, self.decision_horizon_draws
        ):
            raise ValueError("purge/embargo must equal the maximum information horizon")
        return self

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class DatasetSplitVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    split_ref: Literal["dataset-split.verified-913.v1"] = "dataset-split.verified-913.v1"
    dataset_ref: Literal[DATASET_REF] = DATASET_REF
    dataset_sha256: Literal[DATASET_SHA256] = DATASET_SHA256
    windows: tuple[SplitWindow, ...] = Field(min_length=4, max_length=4)
    row_counts: dict[str, int]
    total_rows: Literal[913] = 913
    research_visible_partitions: tuple[Literal["EXPLORATION", "VALIDATION"], ...] = (
        "EXPLORATION",
        "VALIDATION",
    )
    research_forbidden_partitions: tuple[Literal["CONFIRMATION_VAULT", "FINAL_HOLDOUT"], ...] = (
        "CONFIRMATION_VAULT",
        "FINAL_HOLDOUT",
    )

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


WINDOWS = (
    SplitWindow(
        name="EXPLORATION",
        start=date(2024, 1, 1),
        end=date(2025, 6, 30),
        disclosure="ROW_LEVEL",
    ),
    SplitWindow(
        name="VALIDATION",
        start=date(2025, 7, 1),
        end=date(2025, 12, 31),
        disclosure="ROW_LEVEL",
    ),
    SplitWindow(
        name="CONFIRMATION_VAULT",
        start=date(2026, 1, 1),
        end=date(2026, 5, 31),
        disclosure="AGGREGATE_ONLY",
    ),
    SplitWindow(
        name="FINAL_HOLDOUT",
        start=date(2026, 6, 1),
        end=date(2026, 7, 1),
        disclosure="SINGLE_FINAL_GATE",
    ),
)

PROTOCOL = ValidationProtocolVersion()


def partition_name(draw: DrawRecord) -> str:
    draw_date = date.fromisoformat(draw.openTime[:10])
    matches = [window.name for window in WINDOWS if window.start <= draw_date <= window.end]
    if len(matches) != 1:
        raise ValueError(f"draw {draw.expect} does not map to exactly one split")
    return matches[0]


def build_split_version(draws: list[DrawRecord]) -> DatasetSplitVersion:
    counts = {window.name: 0 for window in WINDOWS}
    for draw in draws:
        counts[partition_name(draw)] += 1
    if counts != {
        "EXPLORATION": 547,
        "VALIDATION": 184,
        "CONFIRMATION_VAULT": 151,
        "FINAL_HOLDOUT": 31,
    }:
        raise ValueError("fixed split cardinalities changed")
    return DatasetSplitVersion(windows=WINDOWS, row_counts=counts)
