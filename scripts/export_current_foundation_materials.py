#!/usr/bin/env python3
"""Export model-validated current F1, F2, or F3 source materials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_verifiers import common
from xinao.foundation.assertion_verifiers import f2_assertion_actuals as f2_actuals
from xinao.foundation.assertion_verifiers import f3_assertion_actuals as f3_actuals
from xinao.foundation.closure import evidence_ref
from xinao.foundation.f2_compile import compile_f2_artifacts
from xinao.foundation.research_weight import verify_versioned_object
from xinao.foundation.research_weight_inputs import compile_current_research_weight_foundation
from xinao.foundation.world_compile import EventMatrixSnapshot, WorldSnapshot


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"source must be a JSON object: {path}")
    return dict(value)


def load_f1_snapshot_materials(path: Path) -> dict[str, dict[str, Any]]:
    """Extract only the two model-validated snapshots from a fresh F1 final phase."""

    value = _load_object(path)
    event = EventMatrixSnapshot.model_validate(value.get("event_matrix_snapshot"))
    world = WorldSnapshot.model_validate(value.get("world_snapshot"))
    if world.event_matrix_snapshot_hash != event.content_hash:
        raise ValueError("F1 world snapshot does not bind the event matrix snapshot")
    return {
        "EventMatrixSnapshot": event.model_dump(mode="json"),
        "WorldSnapshot": world.model_dump(mode="json"),
    }


def load_f2_materials(path: Path) -> dict[str, dict[str, Any]]:
    """Recompute all F2 materials from one hash-bound canonical request."""

    prepared = common.prepare_request(
        _load_object(path),
        expected_block_id=f2_actuals.BLOCK_ID,
        expected_artifact_types=f2_actuals.ARTIFACT_TYPES,
        expected_assertion_ids=f2_actuals.ASSERTION_IDS,
    )
    inputs = common.compile_foundation_inputs(prepared)
    report = compile_f2_artifacts(
        inputs.registry,
        atomic_ticket_bindings=inputs.atomic_ticket_bindings,
    )
    materials = {
        "SettlementProbabilitySnapshotVersion": report.probability_snapshot.model_dump(mode="json"),
        "RebateScheduleVersion": report.rebate_schedule.model_dump(mode="json"),
        "SettlementCostSurfaceVersion": report.cost_surface.model_dump(mode="json"),
        "OddsSpaceBenchmarkVersion": report.odds_space_benchmark.model_dump(mode="json"),
        "SettlementCostCompileReport": report.model_dump(mode="json"),
    }
    common.validate_model_payloads(
        materials,
        f2_actuals.ARTIFACT_MODELS,
        block_label="F2 export",
    )
    return materials


def load_f3_materials(path: Path) -> dict[str, dict[str, Any]]:
    """Recompute all F3 materials from one hash-bound canonical request."""

    prepared = common.prepare_request(
        _load_object(path),
        expected_block_id=f3_actuals.BLOCK_ID,
        expected_artifact_types=f3_actuals.ARTIFACT_TYPES,
        expected_assertion_ids=f3_actuals.ASSERTION_IDS,
    )
    inputs = common.compile_foundation_inputs(prepared)
    f2_report = compile_f2_artifacts(
        inputs.registry,
        atomic_ticket_bindings=inputs.atomic_ticket_bindings,
    )
    bundle = compile_current_research_weight_foundation(
        prior_path=prepared.input_paths["f3_prior_draft_sha256"],
        service_graph_path=prepared.input_paths["f3_service_graph_sha256"],
        external_synthesis_path=prepared.input_paths["f3_external_synthesis_sha256"],
        semantics_registry=inputs.registry,
        f2_report=f2_report,
    )
    materials = dict(bundle["objects"])
    invalid = sorted(
        name for name, payload in materials.items() if not verify_versioned_object(payload)
    )
    if invalid:
        raise ValueError(f"F3 material self-hash validation failed: {invalid}")
    return materials


def _require_available_output_root(output_root: Path) -> bool:
    """Reject occupied targets before compilation and remember empty placeholders."""

    if not output_root.exists():
        return False
    if not output_root.is_dir() or any(output_root.iterdir()):
        raise ValueError(f"output root must be empty: {output_root}")
    return True


def export_materials(block: str, source: Path, output_root: Path) -> dict[str, Any]:
    """Write canonical, content-addressed source materials for one block."""

    loaders = {
        "f1": load_f1_snapshot_materials,
        "f2": load_f2_materials,
        "f3": load_f3_materials,
    }
    source = source.resolve()
    output_root = output_root.resolve()
    output_root_was_empty = _require_available_output_root(output_root)
    source_raw = source.read_bytes()
    source_hash = hashlib.sha256(source_raw).hexdigest()
    source_ref = {
        "path": str(source),
        "sha256": source_hash,
        "size_bytes": len(source_raw),
    }

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.",
            suffix=".tmp",
            dir=output_root.parent,
        )
    )
    published = False
    try:
        source_snapshot = staging_root / f"source.{source_hash}.json"
        source_snapshot.write_bytes(source_raw)
        if evidence_ref(source_snapshot)["sha256"] != source_hash:
            raise ValueError("stable source snapshot hash mismatch")

        materials = loaders[block](source_snapshot)
        prepared: list[tuple[str, str, str, bytes]] = []
        for artifact_type, payload in sorted(materials.items()):
            version = payload.get("version_id", payload.get("schema_version"))
            if not isinstance(version, str) or not version:
                raise ValueError(f"{artifact_type} has no version identity")
            raw = canonical_dumps(payload)
            payload_hash = hashlib.sha256(raw).hexdigest()
            if payload_hash != canonical_sha256(payload):
                raise ValueError(f"{artifact_type} canonical hash mismatch")
            prepared.append((artifact_type, version, payload_hash, raw))

        refs: dict[str, dict[str, Any]] = {}
        for artifact_type, version, payload_hash, raw in prepared:
            filename = f"{artifact_type}.{payload_hash}.json"
            staged_path = staging_root / filename
            staged_path.write_bytes(raw)
            staged_ref = evidence_ref(staged_path)
            if staged_ref["sha256"] != payload_hash or staged_ref["size_bytes"] != len(raw):
                raise ValueError(f"{artifact_type} staged material identity mismatch")
            refs[artifact_type] = {
                "version": version,
                "path": str(output_root / filename),
                "sha256": payload_hash,
            }

        try:
            source_still_current = source.read_bytes() == source_raw
        except OSError as exc:
            raise ValueError("source changed during material export") from exc
        if not source_still_current:
            raise ValueError("source changed during material export")

        source_snapshot.unlink()
        result = {
            "schema_version": "xinao.current_foundation_material_export.v1",
            "block": block,
            "source": source_ref,
            "materials": refs,
        }
        canonical_dumps(result)

        _require_available_output_root(output_root)
        if output_root_was_empty:
            output_root.rmdir()
        try:
            os.replace(staging_root, output_root)
        except OSError:
            if output_root_was_empty and not output_root.exists():
                output_root.mkdir()
            raise
        published = True
        return result
    finally:
        if not published:
            shutil.rmtree(staging_root, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("block", choices=("f1", "f2", "f3"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = export_materials(args.block, args.source, args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
