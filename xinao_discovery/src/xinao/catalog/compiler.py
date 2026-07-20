"""Compile all 433 baseline rows into explicit catalog or NOT_COMPILED entries."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xinao.canonical import canonical_sha256, format_decimal_exact
from xinao.contracts.objects import BASELINE_REF, BASELINE_SHA256, PLAY_GROUP_NAMES

DEFAULT_BASELINE_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\03正式数据\新澳_默认基础赔率水位表_v1.csv"
)
DEFAULT_CATALOG_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\catalog\play_catalog.v1.json"
)
DEFAULT_COVERAGE_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\catalog\coverage.v1.json"
)
DEFAULT_FAMILY_REGISTRY_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\catalog\play_family.v1.json"
)

FAMILY_IDS = {
    "多选不中": "multi-select-no-hit",
    "多选中一": "multi-select-one-hit",
    "过关": "parlay",
    "连码": "linked-number",
    "六肖": "six-zodiac",
    "其它": "other-explicit",
    "生肖连": "linked-zodiac",
    "特码": "special-number",
    "特平中": "special-regular-hit",
    "尾数连": "linked-tail",
    "一肖尾数": "one-zodiac-tail",
    "正码": "regular-number",
    "正码特": "regular-position-special",
}
COMPILED_BASELINE_IDS = {"BO0001", "BO0013"}


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    play_group: str
    family_id: str = Field(min_length=1)
    play_id: str = Field(min_length=1)
    option_id: str = Field(min_length=1)
    play_name: str = Field(min_length=1)
    pid: int = Field(gt=0)
    tid: int = Field(gt=0)
    panel: str | None
    bet_shape: str | None
    option_name: str = Field(min_length=1)
    option_range: str | None
    baseline_odds_components: tuple[str, ...] = Field(min_length=1)
    compilation_status: str
    settlement_function_ref: str | None
    not_compiled_reason: str | None

    @field_validator("play_group")
    @classmethod
    def validate_group(cls, value: str) -> str:
        if value not in PLAY_GROUP_NAMES:
            raise ValueError("unknown play group")
        return value

    @field_validator("compilation_status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in {"COMPILED", "NOT_COMPILED"}:
            raise ValueError("entry must be COMPILED or NOT_COMPILED")
        return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _optional(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def _odds_components(value: str) -> tuple[str, ...]:
    components = tuple(format_decimal_exact(Decimal(part.strip())) for part in value.split("/"))
    if not components:
        raise ValueError("baseline odds are empty")
    return components


def _entry(row: dict[str, str]) -> CatalogEntry:
    baseline_id = row["基准ID"]
    group = row["玩法组"]
    family_id = FAMILY_IDS.get(group)
    if family_id is None:
        raise ValueError(f"unclassified play group: {group}")
    panel = _optional(row["盘层"])
    compiled = baseline_id in COMPILED_BASELINE_IDS
    return CatalogEntry(
        baseline_id=baseline_id,
        play_group=group,
        family_id=family_id,
        play_id=f"play:{int(row['PID'])}:{int(row['TID'])}:{panel or 'none'}",
        option_id=f"baseline-option:{baseline_id}",
        play_name=row["玩法"],
        pid=int(row["PID"]),
        tid=int(row["TID"]),
        panel=panel,
        bet_shape=_optional(row["投注形态"]),
        option_name=row["选项"],
        option_range=_optional(row["选项范围"]),
        baseline_odds_components=_odds_components(row["默认基准赔率水位"]),
        compilation_status="COMPILED" if compiled else "NOT_COMPILED",
        settlement_function_ref="special-number-settlement.v1" if compiled else None,
        not_compiled_reason=None if compiled else "settlement_function_not_yet_registered",
    )


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def compile_catalog(
    *,
    baseline_ref: str,
    input_path: Path = DEFAULT_BASELINE_PATH,
    output_path: Path = DEFAULT_CATALOG_PATH,
) -> dict[str, Any]:
    if baseline_ref != BASELINE_REF:
        raise ValueError(f"unsupported baseline ref: {baseline_ref}")
    observed_hash = sha256_file(input_path)
    if observed_hash != BASELINE_SHA256:
        raise ValueError("baseline SHA-256 does not match the fixed contract")
    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    entries = [_entry(row) for row in rows]
    ids = [entry.baseline_id for entry in entries]
    groups = {entry.play_group for entry in entries}
    if len(entries) != 433 or len(ids) != len(set(ids)) or groups != PLAY_GROUP_NAMES:
        raise ValueError("baseline row count, ID uniqueness, or 13-group identity failed")
    body: dict[str, Any] = {
        "schema_version": "xinao.play_catalog.v1",
        "catalog_ref": "play-catalog.v1",
        "baseline_ref": baseline_ref,
        "baseline_sha256": observed_hash,
        "entry_count": len(entries),
        "play_group_count": len(groups),
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }
    body["content_hash"] = canonical_sha256(body)
    write_atomic(output_path, body)
    return body


def coverage_report(
    catalog: dict[str, Any], *, output_path: Path | None = DEFAULT_COVERAGE_PATH
) -> dict[str, Any]:
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise ValueError("catalog entries are missing")
    unclassified: list[str] = []
    compiled = 0
    not_compiled = 0
    for raw in entries:
        if not isinstance(raw, dict):
            unclassified.append("non-object-entry")
            continue
        required = ("baseline_id", "family_id", "play_id", "option_id", "compilation_status")
        if any(not raw.get(field) for field in required):
            unclassified.append(str(raw.get("baseline_id", "missing-id")))
            continue
        if raw["compilation_status"] == "COMPILED" and raw.get("settlement_function_ref"):
            compiled += 1
        elif raw["compilation_status"] == "NOT_COMPILED" and raw.get("not_compiled_reason"):
            not_compiled += 1
        else:
            unclassified.append(str(raw["baseline_id"]))
    report = {
        "schema_version": "xinao.play_catalog_coverage.v1",
        "catalog_ref": catalog.get("catalog_ref"),
        "catalog_content_hash": catalog.get("content_hash"),
        "total": len(entries),
        "compiled": compiled,
        "not_compiled": not_compiled,
        "unclassified_count": len(unclassified),
        "unclassified": unclassified,
        "ok": len(entries) == 433 and compiled + not_compiled == 433 and not unclassified,
    }
    if output_path is not None:
        write_atomic(output_path, report)
    return report


def family_registry(
    catalog: dict[str, Any], *, output_path: Path | None = DEFAULT_FAMILY_REGISTRY_PATH
) -> dict[str, Any]:
    """Project the catalog into 13 explicit family identities without guessing rules."""

    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise ValueError("catalog entries are missing")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("catalog entry must be an object")
        play_group = raw.get("play_group")
        family_id = raw.get("family_id")
        baseline_id = raw.get("baseline_id")
        identity = (play_group, family_id, baseline_id)
        if not all(isinstance(value, str) and value for value in identity):
            raise ValueError("catalog family identity is missing")
        grouped.setdefault((play_group, family_id), []).append(raw)
    observed_groups = {key[0] for key in grouped}
    if observed_groups != PLAY_GROUP_NAMES or len(grouped) != len(PLAY_GROUP_NAMES):
        raise ValueError("family registry must contain the fixed 13 play groups exactly once")

    families: list[dict[str, Any]] = []
    for (play_group, family_id), rows in sorted(grouped.items(), key=lambda item: item[0][1]):
        compiled_rows = [
            row
            for row in rows
            if row.get("compilation_status") == "COMPILED" and row.get("settlement_function_ref")
        ]
        baseline_ids = sorted(str(row["baseline_id"]) for row in rows)
        function_refs = sorted({str(row["settlement_function_ref"]) for row in compiled_rows})
        if len(compiled_rows) == len(rows):
            compilation_status = "FULLY_COMPILED"
        elif compiled_rows:
            compilation_status = "PARTIALLY_COMPILED"
        else:
            compilation_status = "NOT_COMPILED"
        families.append(
            {
                "play_group": play_group,
                "family_id": family_id,
                "baseline_entry_count": len(rows),
                "baseline_ids": baseline_ids,
                "representative_baseline_id": baseline_ids[0],
                "compiled_entry_count": len(compiled_rows),
                "not_compiled_entry_count": len(rows) - len(compiled_rows),
                "compilation_status": compilation_status,
                "settlement_function_refs": function_refs,
                "rule_evidence_status": (
                    "RESEARCH_CONVENTION_ONLY" if compiled_rows else "MISSING"
                ),
                "catalog_closure_eligible": compilation_status == "FULLY_COMPILED",
            }
        )
    body: dict[str, Any] = {
        "schema_version": "xinao.play_family_registry.v1",
        "registry_ref": "play-family.v1",
        "catalog_ref": catalog.get("catalog_ref"),
        "catalog_content_hash": catalog.get("content_hash"),
        "family_count": len(families),
        "identity_complete": len(families) == 13
        and sum(family["baseline_entry_count"] for family in families) == 433,
        "foundation_compilation_complete": all(
            family["catalog_closure_eligible"] for family in families
        ),
        "families": families,
    }
    body["content_hash"] = canonical_sha256(body)
    if output_path is not None:
        write_atomic(output_path, body)
    return body
