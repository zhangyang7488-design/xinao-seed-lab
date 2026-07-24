"""Build and replay the 913-draw special-number event matrix."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from xinao.canonical import canonical_dumps, canonical_sha256, generate_uuid7
from xinao.catalog.compiler import DEFAULT_CATALOG_PATH, sha256_file, write_atomic
from xinao.contracts.objects import BASELINE_REF, BASELINE_SHA256, DATASET_REF, DATASET_SHA256
from xinao.science.active_parent import (
    SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
    load_science_active_parent,
    resolve_science_carrier_path,
)
from xinao.settlement import SPECIAL_NUMBER_FUNCTION, SPECIAL_NUMBER_RULE

DEFAULT_DATASET_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\03正式数据\新澳门六合彩_macaujc2_完整权威数据_2024-01-01_至_2026-07-01.txt"
)
DEFAULT_BASELINE_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\03正式数据\新澳_默认基础赔率水位表_v1.csv"
)
DEFAULT_WORLD_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\world\special-number-settlement.v1"
)
LEGACY_WORLD_ROOT = DEFAULT_WORLD_ROOT
SCIENCE_WORLD_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\science_episodes"
)
LEGACY_BLUEPRINT_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\mainline_domain_research_current"
    r"\blueprint.current_domain_research.json"
)
_SAFE_EPISODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def science_episode_world_root(
    episode_id: str,
    protocol_pin_sha256: str,
    *,
    requested: Path | None = None,
) -> Path:
    """Derive the sole writable world root for one admitted science episode."""

    if not _SAFE_EPISODE_ID.fullmatch(episode_id) or episode_id in {".", ".."}:
        raise ValueError("science episode_id must be one safe path component")
    if not _SHA256.fullmatch(protocol_pin_sha256):
        raise ValueError("science ProtocolPin sha256 is invalid")
    base = resolve_science_carrier_path(str(SCIENCE_WORLD_ROOT)).resolve()
    expected = (base / episode_id / protocol_pin_sha256).resolve()
    try:
        expected.relative_to(base)
    except ValueError as exc:
        raise ValueError("science world root escaped its canonical base") from exc
    if requested is not None:
        resolved_requested = resolve_science_carrier_path(str(requested)).resolve()
        if resolved_requested != expected:
            raise ValueError("science world output_root is not the canonical episode root")
    legacy = resolve_science_carrier_path(str(LEGACY_WORLD_ROOT)).resolve()
    if expected == legacy or legacy in expected.parents:
        raise ValueError("current science world cannot write inside the legacy world root")
    return expected


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
    path = resolve_science_carrier_path(str(path))
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


def _git_sha(explicit: str | None = None) -> str:
    candidate = str(explicit or "").strip().lower()
    if candidate:
        if len(candidate) != 40 or any(char not in "0123456789abcdef" for char in candidate):
            raise ValueError("code_git_sha must be a lowercase 40-character Git commit")
        return candidate
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


def _build_world(
    *,
    dataset: str,
    baseline: str,
    rule: str,
    output_root: Path,
    correlation_id: str | None = None,
    workflow_id: str = "xinao-build-001-world-local",
    run_id: str | None = None,
    config_ref: str,
    config_hash: str,
    config_authority_scope: str,
    session_id: str,
    science_episode_binding: dict[str, Any] | None = None,
    code_git_sha: str | None = None,
) -> dict[str, Any]:
    resolved_code_git_sha = _git_sha(code_git_sha)
    if dataset not in {"verified-913", DATASET_REF}:
        raise ValueError("unsupported dataset ref")
    if baseline != BASELINE_REF or rule != SPECIAL_NUMBER_RULE.rule_ref:
        raise ValueError("baseline or rule does not match the registered vertical slice")
    dataset_path = resolve_science_carrier_path(str(DEFAULT_DATASET_PATH))
    if sha256_file(dataset_path) != DATASET_SHA256:
        raise ValueError("dataset hash changed")
    baseline_path = resolve_science_carrier_path(str(DEFAULT_BASELINE_PATH))
    if sha256_file(baseline_path) != BASELINE_SHA256:
        raise ValueError("baseline hash changed")
    catalog_path = resolve_science_carrier_path(str(DEFAULT_CATALOG_PATH))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    coverage = {
        item["baseline_id"]: item
        for item in catalog["entries"]
        if item["baseline_id"] in {"BO0001", "BO0013"}
    }
    if set(coverage) != {"BO0001", "BO0013"} or any(
        item["compilation_status"] != "COMPILED" for item in coverage.values()
    ):
        raise ValueError("catalog does not activate both special-number price identities")
    admitted_bindings = (
        dict(science_episode_binding["world_measurement_bundle"]["bindings"])
        if science_episode_binding is not None
        else {
            "dataset": {"ref": DATASET_REF, "sha256": DATASET_SHA256},
            "baseline": {"ref": BASELINE_REF, "sha256": BASELINE_SHA256},
            "rule": {
                "ref": SPECIAL_NUMBER_RULE.rule_ref,
                "sha256": canonical_sha256(SPECIAL_NUMBER_RULE),
            },
            "settlement": {
                "ref": SPECIAL_NUMBER_FUNCTION.function_ref,
                "sha256": canonical_sha256(SPECIAL_NUMBER_FUNCTION),
            },
        }
    )
    draws = load_draws()
    matrix_path = output_root / "event_matrix.jsonl"
    matrix = _compute_matrix(draws, matrix_path)
    if matrix["row_count"] != 913 * 2 * 49 or matrix["hit_count"] != 913 * 2:
        raise AssertionError("matrix cardinality invariant failed")
    snapshot: dict[str, Any] = {
        "schema_version": "xinao.event_matrix_snapshot.v1",
        "snapshot_ref": "event-matrix.special-number.verified-913.v1",
        "dataset_ref": admitted_bindings["dataset"]["ref"],
        "dataset_sha256": admitted_bindings["dataset"]["sha256"],
        "baseline_ref": admitted_bindings["baseline"]["ref"],
        "baseline_sha256": admitted_bindings["baseline"]["sha256"],
        "catalog_ref": catalog["catalog_ref"],
        "catalog_hash": catalog["content_hash"],
        "rule_ref": admitted_bindings["rule"]["ref"],
        "rule_hash": admitted_bindings["rule"]["sha256"],
        "settlement_ref": admitted_bindings["settlement"]["ref"],
        "settlement_hash": admitted_bindings["settlement"]["sha256"],
        "draw_count": len(draws),
        "row_count": matrix["row_count"],
        "nnz": matrix["hit_count"],
        "rows_per_draw": 98,
        "first_draw_id": draws[0].expect,
        "last_draw_id": draws[-1].expect,
        "matrix_path": "event_matrix.jsonl",
        "matrix_sha256": matrix["matrix_sha256"],
    }
    snapshot["content_hash"] = canonical_sha256(snapshot)
    snapshot_path = output_root / "event_matrix_snapshot.json"
    write_atomic(snapshot_path, snapshot)
    world: dict[str, Any] = {
        "schema_version": (
            "xinao.world_snapshot.science_episode.v1"
            if science_episode_binding is not None
            else "xinao.world_snapshot.v1"
        ),
        "world_ref": "world.special-number.verified-913.v1",
        "event_matrix_snapshot_ref": snapshot["snapshot_ref"],
        "event_matrix_snapshot_hash": snapshot["content_hash"],
        "authority_contract_ref": "macaujc-source-authority-contract.v1",
        "dataset_ref": admitted_bindings["dataset"]["ref"],
        "dataset_sha256": admitted_bindings["dataset"]["sha256"],
        "baseline_ref": admitted_bindings["baseline"]["ref"],
        "baseline_sha256": admitted_bindings["baseline"]["sha256"],
        "rule_ref": admitted_bindings["rule"]["ref"],
        "rule_sha256": admitted_bindings["rule"]["sha256"],
        "settlement_ref": admitted_bindings["settlement"]["ref"],
        "settlement_sha256": admitted_bindings["settlement"]["sha256"],
        "knowledge_cutoff_at": (
            science_episode_binding["world_measurement_bundle"]["knowledge_cutoff"]
            if science_episode_binding is not None
            else "2026-07-01T21:32:32.000Z"
        ),
    }
    if science_episode_binding is not None:
        world["science_episode_binding"] = science_episode_binding
        world["world_axiom_ref"] = admitted_bindings["world_axiom"]["ref"]
        world["world_axiom_sha256"] = admitted_bindings["world_axiom"]["sha256"]
    world["content_hash"] = canonical_sha256(world)
    world_path = output_root / "world_snapshot.json"
    write_atomic(world_path, world)
    correlation = correlation_id or generate_uuid7()
    run = run_id or generate_uuid7()
    manifest = {
        "schema_version": "xinao.evidence_manifest.v1",
        "correlation_id": correlation,
        "session_id": session_id,
        "workflow_id": workflow_id,
        "run_id": run,
        "code_git_sha": resolved_code_git_sha,
        "config_ref": config_ref,
        "config_hash": config_hash,
        "config_authority_scope": config_authority_scope,
        "usable_as_current_science_episode": science_episode_binding is not None,
        "authority_contract_id": "macaujc-source-authority-contract.v1",
        "dataset_hash": DATASET_SHA256,
        "baseline_hash": BASELINE_SHA256,
        "rule_version": SPECIAL_NUMBER_RULE.rule_ref,
        "input_snapshot_hashes": [
            DATASET_SHA256,
            BASELINE_SHA256,
            catalog["content_hash"],
            snapshot["rule_hash"],
            snapshot["settlement_hash"],
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
    if science_episode_binding is not None:
        manifest["science_episode_binding"] = science_episode_binding
        manifest["input_bindings"] = admitted_bindings
        manifest["input_snapshot_hashes"] = [
            science_episode_binding["world_measurement_bundle"]["sha256"],
            *(admitted_bindings[name]["sha256"] for name in sorted(admitted_bindings)),
            catalog["content_hash"],
        ]
    manifest_path = output_root / "evidence_manifest.json"
    write_atomic(manifest_path, manifest)
    return {
        "ok": True,
        "output_root": str(output_root),
        "event_matrix_snapshot": snapshot,
        "world_snapshot": world,
        "evidence_manifest": manifest,
    }


def build_world(
    *,
    dataset: str,
    baseline: str,
    rule: str,
    output_root: Path = LEGACY_WORLD_ROOT,
    correlation_id: str | None = None,
    workflow_id: str = "xinao-build-001-world-local",
    run_id: str | None = None,
    code_git_sha: str | None = None,
) -> dict[str, Any]:
    """Build the preserved G0-G8 world carrier for explicit legacy replay."""

    return _build_world(
        dataset=dataset,
        baseline=baseline,
        rule=rule,
        output_root=output_root,
        correlation_id=correlation_id,
        workflow_id=workflow_id,
        run_id=run_id,
        config_ref=str(LEGACY_BLUEPRINT_PATH),
        config_hash=sha256_file(resolve_science_carrier_path(str(LEGACY_BLUEPRINT_PATH))),
        config_authority_scope="LEGACY_PARENT_G0_G8",
        session_id="codex-xinao-mainline-20260714",
        code_git_sha=code_git_sha,
    )


def _verify_admitted_world_bindings(admission: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Recompute the five current world identities before any science write."""

    from xinao.science import canonical_world_measurement_bindings

    background = dict(admission["background_contract"])
    background_path = resolve_science_carrier_path(str(background["path"]))
    background_hash = sha256_file(background_path)
    if background_hash != str(background["sha256"]):
        raise ValueError("current world-axiom contract hash changed")
    expected = canonical_world_measurement_bindings(
        background_contract_sha256=background_hash,
    )
    if sha256_file(resolve_science_carrier_path(str(DEFAULT_DATASET_PATH))) != DATASET_SHA256:
        raise ValueError("current science dataset hash changed")
    if sha256_file(resolve_science_carrier_path(str(DEFAULT_BASELINE_PATH))) != BASELINE_SHA256:
        raise ValueError("current science baseline hash changed")
    observed = dict(admission["world_measurement_bundle"]["bindings"])
    if observed != expected:
        raise ValueError("admitted WorldMeasurementBundle does not bind the executed world")
    return expected


def _current_science_authority() -> tuple[Path, str]:
    projection_path = resolve_science_carrier_path(str(SCIENCE_ACTIVE_PARENT_PROJECTION_PATH))
    parent = load_science_active_parent(projection_path)
    return projection_path, str(parent["active_parent"]["sha256"])


def _science_logical_binding(
    admission: dict[str, Any],
    admitted_bindings: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Build a carrier-neutral binding for hashed world artifacts."""

    episode_id = str(admission["episode_id"])
    protocol_pin_id = str(admission["protocol_pin_id"])
    return {
        "episode_id": episode_id,
        "protocol_pin_id": protocol_pin_id,
        "protocol_pin_ref": f"science-protocol-pin:{protocol_pin_id}",
        "protocol_pin_sha256": admission["protocol_pin_sha256"],
        "active_parent_sha256": admission["active_parent_sha256"],
        "claim_intent": admission["claim_intent"],
        "exposure_status": admission["exposure_status"],
        "evaluation_outcome_access": admission["evaluation_outcome_access"],
        "world_measurement_bundle": {
            "ref": f"world-measurement-bundle:{episode_id}",
            "sha256": admission["world_measurement_bundle"]["sha256"],
            "knowledge_cutoff": admission["world_measurement_bundle"]["knowledge_cutoff"],
            "target_open_time": admission["world_measurement_bundle"]["target_open_time"],
            "bindings": admitted_bindings,
        },
        "old_g6_equivalent": False,
    }


def _publish_science_world(staging: Path, target: Path) -> None:
    """Atomically replace one canonical episode directory with a complete build."""

    backup = target.with_name(f".{target.name}.backup-{generate_uuid7()}")
    had_target = target.exists()
    if had_target:
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except Exception:
        if had_target and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build_science_episode_world(
    *,
    dataset: str,
    baseline: str,
    rule: str,
    protocol_pin_path: Path,
    protocol_pin_sha256: str,
    output_root: Path | None = None,
    correlation_id: str | None = None,
    workflow_id: str = "xinao-science-world-local",
    run_id: str | None = None,
    code_git_sha: str | None = None,
) -> dict[str, Any]:
    """Build a world whose identity is bound to one verified science ProtocolPin."""

    from xinao.science import verify_science_episode_admission_file

    projection_path, active_parent_sha256 = _current_science_authority()
    admission = verify_science_episode_admission_file(
        protocol_pin_path,
        expected_file_sha256=protocol_pin_sha256,
        expected_active_parent_sha256=active_parent_sha256,
        projection_path=projection_path,
    )
    admitted_bindings = _verify_admitted_world_bindings(admission)
    target = science_episode_world_root(
        str(admission["episode_id"]),
        str(admission["protocol_pin_sha256"]),
        requested=output_root,
    )
    binding = _science_logical_binding(admission, admitted_bindings)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.staging-{generate_uuid7()}")
    try:
        result = _build_world(
            dataset=dataset,
            baseline=baseline,
            rule=rule,
            output_root=staging,
            correlation_id=correlation_id,
            workflow_id=workflow_id,
            run_id=run_id,
            config_ref=str(binding["protocol_pin_ref"]),
            config_hash=str(admission["protocol_pin_sha256"]),
            config_authority_scope="XINAO_SCIENCE_PROTOCOL_ACTIVE",
            session_id=str(admission["episode_id"]),
            science_episode_binding=binding,
            code_git_sha=code_git_sha,
        )
        _publish_science_world(staging, target)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    result["output_root"] = str(target)
    return result


def replay_world(
    output_root: Path = LEGACY_WORLD_ROOT, *, report_path: Path | None = None
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


def replay_science_episode_world(
    output_root: Path,
    *,
    protocol_pin_path: Path,
    protocol_pin_sha256: str,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Replay matrix and all science episode bindings from independent sources."""

    from xinao.science import verify_science_episode_admission_file

    projection_path, active_parent_sha256 = _current_science_authority()
    admission = verify_science_episode_admission_file(
        protocol_pin_path,
        expected_file_sha256=protocol_pin_sha256,
        expected_active_parent_sha256=active_parent_sha256,
        projection_path=projection_path,
    )
    expected_root = science_episode_world_root(
        str(admission["episode_id"]),
        str(admission["protocol_pin_sha256"]),
        requested=output_root,
    )
    admitted_bindings = _verify_admitted_world_bindings(admission)
    matrix = replay_world(expected_root)
    snapshot = json.loads(
        (expected_root / "event_matrix_snapshot.json").read_text(encoding="utf-8")
    )
    world = json.loads((expected_root / "world_snapshot.json").read_text(encoding="utf-8"))
    manifest = json.loads((expected_root / "evidence_manifest.json").read_text(encoding="utf-8"))
    recorded_world_hash = str(world.pop("content_hash", ""))
    world_hash_ok = canonical_sha256(world) == recorded_world_hash
    expected_binding = _science_logical_binding(admission, admitted_bindings)
    outputs = {
        str(item.get("artifact")): str(item.get("sha256"))
        for item in manifest.get("output_hashes", [])
        if isinstance(item, dict)
    }
    checks = {
        "matrix_replay": matrix["ok"] is True,
        "science_world_schema": world.get("schema_version")
        == "xinao.world_snapshot.science_episode.v1",
        "world_content_hash": world_hash_ok,
        "world_snapshot_binding": (
            world.get("event_matrix_snapshot_ref") == snapshot.get("snapshot_ref")
            and world.get("event_matrix_snapshot_hash") == snapshot.get("content_hash")
        ),
        "world_binding": world.get("science_episode_binding") == expected_binding,
        "manifest_binding": manifest.get("science_episode_binding") == expected_binding,
        "snapshot_bindings": (
            snapshot.get("matrix_path") == "event_matrix.jsonl"
            and snapshot.get("dataset_ref") == admitted_bindings["dataset"]["ref"]
            and snapshot.get("dataset_sha256") == admitted_bindings["dataset"]["sha256"]
            and snapshot.get("baseline_ref") == admitted_bindings["baseline"]["ref"]
            and snapshot.get("baseline_sha256") == admitted_bindings["baseline"]["sha256"]
            and snapshot.get("rule_ref") == admitted_bindings["rule"]["ref"]
            and snapshot.get("rule_hash") == admitted_bindings["rule"]["sha256"]
            and snapshot.get("settlement_ref") == admitted_bindings["settlement"]["ref"]
            and snapshot.get("settlement_hash") == admitted_bindings["settlement"]["sha256"]
        ),
        "world_bindings": (
            world.get("dataset_ref") == admitted_bindings["dataset"]["ref"]
            and world.get("dataset_sha256") == admitted_bindings["dataset"]["sha256"]
            and world.get("baseline_ref") == admitted_bindings["baseline"]["ref"]
            and world.get("baseline_sha256") == admitted_bindings["baseline"]["sha256"]
            and world.get("rule_ref") == admitted_bindings["rule"]["ref"]
            and world.get("rule_sha256") == admitted_bindings["rule"]["sha256"]
            and world.get("settlement_ref") == admitted_bindings["settlement"]["ref"]
            and world.get("settlement_sha256") == admitted_bindings["settlement"]["sha256"]
            and world.get("world_axiom_ref") == admitted_bindings["world_axiom"]["ref"]
            and world.get("world_axiom_sha256") == admitted_bindings["world_axiom"]["sha256"]
        ),
        "manifest_input_bindings": manifest.get("input_bindings") == admitted_bindings,
        "manifest_config": manifest.get("config_hash") == admission["protocol_pin_sha256"]
        and manifest.get("config_ref") == expected_binding["protocol_pin_ref"]
        and manifest.get("config_authority_scope") == "XINAO_SCIENCE_PROTOCOL_ACTIVE",
        "manifest_scope": manifest.get("session_id") == admission["episode_id"]
        and manifest.get("usable_as_current_science_episode") is True,
        "output_hashes": outputs
        == {
            "event_matrix.jsonl": snapshot["matrix_sha256"],
            "event_matrix_snapshot.json": snapshot["content_hash"],
            "world_snapshot.json": recorded_world_hash,
        },
    }
    result = {
        "ok": all(checks.values()),
        "checks": checks,
        "episode_id": admission["episode_id"],
        "protocol_pin_sha256": admission["protocol_pin_sha256"],
        "world_content_hash": recorded_world_hash,
    }
    canonical_report = expected_root / "science_world_replay.json"
    if report_path is not None:
        resolved_report = resolve_science_carrier_path(str(report_path)).resolve()
        if resolved_report != canonical_report.resolve():
            raise ValueError("science replay report must use the canonical episode report path")
    write_atomic(canonical_report, result)
    result["report_ref"] = str(canonical_report)
    result["report_sha256"] = sha256_file(canonical_report)
    return result
