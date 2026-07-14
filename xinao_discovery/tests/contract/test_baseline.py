from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from xinao.contracts import BaselineOddsWaterVersion

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "domain" / "baseline_odds_water_version.json"
)


def load() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_baseline_fixed_identity_counts_groups_and_semantic_role() -> None:
    baseline = BaselineOddsWaterVersion.model_validate(load())
    assert baseline.baseline_ref == "baseline-odds-water.v1"
    assert baseline.semantic_role == "REFERENCE_NORMALIZED"
    assert baseline.row_count == 433
    assert baseline.play_group_count == len(set(baseline.play_group_names)) == 13
    assert baseline.baseline_id_unique is True
    assert baseline.baseline_sha256 == (
        "634c50219fb4450332d79b232275854adf648d4c5614eaabf5a961eb9f7bfbf1"
    )
    assert baseline.with_content_hash().content_hash


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("row_count", 432),
        ("play_group_count", 12),
        ("baseline_id_unique", False),
        ("semantic_role", "MARKET_TRUTH"),
        ("baseline_sha256", "0" * 64),
    ],
)
def test_baseline_fixed_values_fail_closed(field: str, invalid: object) -> None:
    payload = copy.deepcopy(load())
    payload[field] = invalid
    with pytest.raises(ValidationError):
        BaselineOddsWaterVersion.model_validate(payload)


def test_baseline_rejects_missing_duplicate_or_unknown_groups() -> None:
    for names in (
        load()["play_group_names"][:-1],
        [*load()["play_group_names"][:-1], load()["play_group_names"][0]],
        [*load()["play_group_names"][:-1], "未知组"],
    ):
        payload = copy.deepcopy(load())
        payload["play_group_names"] = names
        with pytest.raises(ValidationError):
            BaselineOddsWaterVersion.model_validate(payload)


def test_generated_baseline_schema_validates_fixture() -> None:
    errors = list(
        Draft202012Validator(BaselineOddsWaterVersion.model_json_schema()).iter_errors(load())
    )
    assert errors == []
