"""Build and replay the 913-draw special-number event matrix."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from xinao.canonical import canonical_dumps, canonical_sha256, generate_uuid7
from xinao.catalog.compiler import DEFAULT_CATALOG_PATH, sha256_file, write_atomic
from xinao.contracts.objects import BASELINE_REF, BASELINE_SHA256, DATASET_REF, DATASET_SHA256
from xinao.settlement import SPECIAL_NUMBER_FUNCTION, SPECIAL_NUMBER_RULE

DEFAULT_DATASET_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\03正式数据\新澳门六合彩_macaujc2_完整权威数据_2024-01-01_至_2026-07-01.txt"
)
DEFAULT_WORLD_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\world\special-number-settlement.v1"
)
DEFAULT_BLUEPRINT_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\mainline_domain_research_current"
    r"\blueprint.current_domain_research.json"
)


class DrawRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    expect: str = Field(pattern=r"^\d{7}$")
    openTime: str
    openCode: str

    @property
    def numbers(self) -> tuple[int, ...]:
        values = tuple(int(part) for part in self.openCode.split(","))
        if len(values) != 7 or any(value < 1 or value > 49 for value in values):
            raise ValueError("openCode must contain seven values from 1 to 49")
        if len(set(values)) != 7:
            raise ValueError("openCode values must be unique")
        return values

    @property
    def special_number(self) -> int:
        return self.numbers[6]


class EventRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draw_id: str
    event_id: str
    selected_number: int = Field(ge=1, le=49)
    actual_special_number: int = Field(ge=1, le=49)
    panel: Literal["A", "B"]
    hit: bool
    settlement_tier: Literal["exact-hit", "miss"]
    baseline_odds_ref: Literal["BO0001", "BO0013"]
    rule_ref: Literal["special-number-rule.v1"]
    attribute_refs: tuple[str, ...]


def load_draws(path: Path = DEFAULT_DATASET_PATH) -> list[DrawRecord]:
    if sha256_file(path) != DATASET_SHA256:
        raise ValueError("dataset SHA-256 does not match the fixed contract")
    records: list[DrawRecord] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith('{"suit"'):
                records.append(DrawRecord.model_validate_json(line))
    if len(records) != 913:
        raise ValueError("formal dataset must contain exactly 913 JSON records")
    identifiers = [record.expect for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("draw identifiers must be unique")
    if identifiers[0] != "2024001" or identifiers[-1] != "2026182":
        raise ValueError("fixed dataset range identity failed")
    for record in records:
        _ = record.numbers
    return records


def iter_event_rows(draws: list[DrawRecord]) -> Iterator[EventRow]:
    for draw in draws:
        actual = draw.special_number
        for panel, baseline_ref in (
            ("A", SPECIAL_NUMBER_FUNCTION.a_baseline_ref),
            ("B", SPECIAL_NUMBER_FUNCTION.b_baseline_ref),
        ):
            for selected in range(1, 50):
                hit = selected == actual
                yield EventRow(
                    draw_id=draw.expect,
                    event_id=f"special-number:{panel}:{selected:02d}",
                    selected_number=selected,
                    actual_special_number=actual,
                    panel=panel,
                    hit=hit,
                    settlement_tier="exact-hit" if hit else "miss",
                    baseline_odds_ref=baseline_ref,
                    rule_ref=SPECIAL_NUMBER_RULE.rule_ref,
                    attribute_refs=(
                        f"special-number:{actual:02d}",
                        f"panel:{panel}",
                        f"open-time:{draw.openTime}",
                    ),
                )


def _event_bytes(row: EventRow) -> bytes:
    return canonical_dumps(row.model_dump(mode="python")) + b"\n"


def _compute_matrix(draws: list[DrawRecord], output_path: Path | None) -> dict[str, Any]:
    digest = hashlib.sha256()
    row_count = 0
    hit_count = 0
    temporary: Path | None = None
    stream = None
    try:
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
            stream = temporary.open("wb")
        for row in iter_event_rows(draws):
            payload = _event_bytes(row)
            digest.update(payload)
            if stream is not None:
                stream.write(payload)
            row_count += 1
            hit_count += int(row.hit)
        if stream is not None:
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            stream = None
            os.replace(temporary, output_path)
    finally:
        if stream is not None:
            stream.close()
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {
        "matrix_sha256": digest.hexdigest(),
        "row_count": row_count,
        "hit_count": hit_count,
    }


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[4],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return completed.stdout.strip()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_world(
    *,
    dataset: str,
    baseline: str,
    rule: str,
    output_root: Path = DEFAULT_WORLD_ROOT,
    correlation_id: str | None = None,
    workflow_id: str = "xinao-build-001-world-local",
    run_id: str | None = None,
) -> dict[str, Any]:
    if dataset not in {"verified-913", DATASET_REF}:
        raise ValueError("unsupported dataset ref")
    if baseline != BASELINE_REF or rule != SPECIAL_NUMBER_RULE.rule_ref:
        raise ValueError("baseline or rule does not match the registered vertical slice")
    if sha256_file(DEFAULT_DATASET_PATH) != DATASET_SHA256:
        raise ValueError("dataset hash changed")
    baseline_path = Path(r"C:\Users\xx363\Desktop\主线\03正式数据\新澳_默认基础赔率水位表_v1.csv")
    if sha256_file(baseline_path) != BASELINE_SHA256:
        raise ValueError("baseline hash changed")
    catalog = json.loads(DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))
    coverage = {
        item["baseline_id"]: item
        for item in catalog["entries"]
        if item["baseline_id"] in {"BO0001", "BO0013"}
    }
    if set(coverage) != {"BO0001", "BO0013"} or any(
        item["compilation_status"] != "COMPILED" for item in coverage.values()
    ):
        raise ValueError("catalog does not activate both special-number price identities")
    draws = load_draws()
    matrix_path = output_root / "event_matrix.jsonl"
    matrix = _compute_matrix(draws, matrix_path)
    if matrix["row_count"] != 913 * 2 * 49 or matrix["hit_count"] != 913 * 2:
        raise AssertionError("matrix cardinality invariant failed")
    snapshot: dict[str, Any] = {
        "schema_version": "xinao.event_matrix_snapshot.v1",
        "snapshot_ref": "event-matrix.special-number.verified-913.v1",
        "dataset_ref": DATASET_REF,
        "dataset_sha256": DATASET_SHA256,
        "baseline_ref": BASELINE_REF,
        "baseline_sha256": BASELINE_SHA256,
        "catalog_ref": catalog["catalog_ref"],
        "catalog_hash": catalog["content_hash"],
        "rule_ref": SPECIAL_NUMBER_RULE.rule_ref,
        "rule_hash": canonical_sha256(SPECIAL_NUMBER_RULE),
        "draw_count": len(draws),
        "row_count": matrix["row_count"],
        "nnz": matrix["hit_count"],
        "rows_per_draw": 98,
        "first_draw_id": draws[0].expect,
        "last_draw_id": draws[-1].expect,
        "matrix_path": str(matrix_path),
        "matrix_sha256": matrix["matrix_sha256"],
    }
    snapshot["content_hash"] = canonical_sha256(snapshot)
    snapshot_path = output_root / "event_matrix_snapshot.json"
    write_atomic(snapshot_path, snapshot)
    world: dict[str, Any] = {
        "schema_version": "xinao.world_snapshot.v1",
        "world_ref": "world.special-number.verified-913.v1",
        "event_matrix_snapshot_ref": snapshot["snapshot_ref"],
        "event_matrix_snapshot_hash": snapshot["content_hash"],
        "authority_contract_ref": "macaujc-source-authority-contract.v1",
        "dataset_ref": DATASET_REF,
        "baseline_ref": BASELINE_REF,
        "rule_ref": SPECIAL_NUMBER_RULE.rule_ref,
        "knowledge_cutoff_at": "2026-07-01T21:32:32.000Z",
    }
    world["content_hash"] = canonical_sha256(world)
    world_path = output_root / "world_snapshot.json"
    write_atomic(world_path, world)
    correlation = correlation_id or generate_uuid7()
    run = run_id or generate_uuid7()
    manifest = {
        "schema_version": "xinao.evidence_manifest.v1",
        "correlation_id": correlation,
        "session_id": "codex-xinao-mainline-20260714",
        "workflow_id": workflow_id,
        "run_id": run,
        "code_git_sha": _git_sha(),
        "config_hash": sha256_file(DEFAULT_BLUEPRINT_PATH),
        "authority_contract_id": "macaujc-source-authority-contract.v1",
        "dataset_hash": DATASET_SHA256,
        "baseline_hash": BASELINE_SHA256,
        "rule_version": SPECIAL_NUMBER_RULE.rule_ref,
        "input_snapshot_hashes": [
            DATASET_SHA256,
            BASELINE_SHA256,
            catalog["content_hash"],
            snapshot["rule_hash"],
        ],
        "output_hashes": [
            {"artifact": "event_matrix.jsonl", "sha256": matrix["matrix_sha256"]},
            {"artifact": "event_matrix_snapshot.json", "sha256": snapshot["content_hash"]},
            {"artifact": "world_snapshot.json", "sha256": world["content_hash"]},
        ],
        "mlflow_run_id": None,
        "openlineage_run_id": None,
        "trace_id": generate_uuid7(),
        "result_status": "verified",
        "verifier": "xinao.world.replay_world",
        "created_at": _now(),
    }
    manifest_path = output_root / "evidence_manifest.json"
    write_atomic(manifest_path, manifest)
    return {
        "ok": True,
        "event_matrix_snapshot": snapshot,
        "world_snapshot": world,
        "evidence_manifest": manifest,
    }


def replay_world(
    output_root: Path = DEFAULT_WORLD_ROOT, *, report_path: Path | None = None
) -> dict[str, Any]:
    snapshot_path = output_root / "event_matrix_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    recorded_content_hash = snapshot.pop("content_hash")
    if canonical_sha256(snapshot) != recorded_content_hash:
        raise ValueError("event matrix snapshot content hash mismatch")
    recorded_matrix_hash = snapshot["matrix_sha256"]
    observed_file_hash = sha256_file(output_root / "event_matrix.jsonl")
    recomputed = _compute_matrix(load_draws(), None)
    ok = (
        recorded_matrix_hash == observed_file_hash == recomputed["matrix_sha256"]
        and snapshot["row_count"] == recomputed["row_count"] == 913 * 2 * 49
        and snapshot["nnz"] == recomputed["hit_count"] == 913 * 2
    )
    result = {
        "ok": ok,
        "recorded_matrix_sha256": recorded_matrix_hash,
        "file_matrix_sha256": observed_file_hash,
        "recomputed_matrix_sha256": recomputed["matrix_sha256"],
        "row_count": recomputed["row_count"],
        "nnz": recomputed["hit_count"],
    }
    if report_path is not None:
        write_atomic(report_path, result)
    return result
