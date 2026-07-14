"""Strict first vertical-slice registration objects for CODEX-XINAO-BUILD-001."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from .common import CommonEnvelope

DATASET_REF = "macaujc2-authority-dataset-2024-01-01--2026-07-01"
DATASET_SHA256 = "57f9fc68f48416fd38610da1cf0bba3476537318514f0093fcb86af3a94ab2c6"
BASELINE_REF = "baseline-odds-water.v1"
BASELINE_SHA256 = "634c50219fb4450332d79b232275854adf648d4c5614eaabf5a961eb9f7bfbf1"
AUTHORITY_CONTRACT_REF = "macaujc-source-authority-contract.v1"
PLAY_GROUP_NAMES = frozenset(
    {
        "多选不中",
        "多选中一",
        "过关",
        "连码",
        "六肖",
        "其它",
        "生肖连",
        "特码",
        "特平中",
        "尾数连",
        "一肖尾数",
        "正码",
        "正码特",
    }
)


class AuthorityContract(CommonEnvelope):
    entity_type: Literal["AuthorityContract"] = "AuthorityContract"
    contract_ref: Literal["macaujc-source-authority-contract.v1"]
    source_id: Literal["macaujc2"]
    product_identity: Literal["新澳门六合彩"]
    source_role: Literal["result_origin_for_user_defined_research_world"]
    canonical_site: Literal["https://macaujc.com/"]
    api_documentation: Literal["https://macaujc.com/api/"]
    history_endpoint_template: Literal["https://history.macaumarksix.com/history/macaujc2/y/{year}"]
    point_endpoint_template: Literal[
        "https://history.macaumarksix.com/history/macaujc2/expect/{expect}"
    ]
    user_confirmed: Literal[True]
    default_trust: Literal[True]
    owner: Literal["User Direction/Source Verifier"]
    status: Literal["ACTIVE", "REVOKED"]


class DatasetSnapshot(CommonEnvelope):
    entity_type: Literal["DatasetSnapshot"] = "DatasetSnapshot"
    dataset_ref: Literal["macaujc2-authority-dataset-2024-01-01--2026-07-01"]
    authority_contract_ref: Literal["macaujc-source-authority-contract.v1"]
    source_id: Literal["macaujc2"]
    period_start: str = Field(pattern=r"^2024-01-01$")
    period_end: str = Field(pattern=r"^2026-07-01$")
    record_count: Literal[913]
    human_record_lines: Literal[913]
    json_record_lines: Literal[913]
    dataset_sha256: Literal["57f9fc68f48416fd38610da1cf0bba3476537318514f0093fcb86af3a94ab2c6"]
    duplicate_policy: Literal["KEEP_ALL"]
    status: Literal["VERIFIED", "SUPERSEDED", "REVOKED"]


class BaselineOddsWaterVersion(CommonEnvelope):
    entity_type: Literal["BaselineOddsWaterVersion"] = "BaselineOddsWaterVersion"
    baseline_ref: Literal["baseline-odds-water.v1"]
    semantic_role: Literal["REFERENCE_NORMALIZED"]
    baseline_sha256: Literal["634c50219fb4450332d79b232275854adf648d4c5614eaabf5a961eb9f7bfbf1"]
    row_count: Literal[433]
    play_group_count: Literal[13]
    baseline_id_unique: Literal[True]
    play_group_names: tuple[str, ...] = Field(min_length=13, max_length=13)
    status: Literal["ACTIVE", "RETIRED"]

    @field_validator("play_group_names")
    @classmethod
    def validate_play_groups(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("play_group_names must be unique")
        if set(value) != PLAY_GROUP_NAMES:
            raise ValueError("play_group_names must equal the fixed 13-group baseline catalog")
        return value
