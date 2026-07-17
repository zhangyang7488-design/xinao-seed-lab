"""Private fresh-process phases for the canonical F1 actuals source."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from xinao.foundation.f1_property_suite import compile_f1_property_suite_evidence
from xinao.foundation.f1_replay import (
    F1RepresentativeReplayEvidence,
    compile_f1_replay_evidence,
)
from xinao.foundation.selection_manifest import load_play_catalog
from xinao.foundation.semantics_registry import compile_semantics_registry
from xinao.foundation.world_compile import (
    FamilyReplayResult,
    compile_functional_world,
)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"phase input must be a JSON object: {path}")
    return value


def _write_object(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def _registry(catalog_path: Path) -> Any:
    return compile_semantics_registry(load_play_catalog(catalog_path))


def _seed(catalog_path: Path, dataset_path: Path, output_path: Path) -> None:
    registry = _registry(catalog_path)
    seed_world = compile_functional_world(registry, dataset_path)
    seed_replay = compile_f1_replay_evidence(registry, seed_world.world_snapshot)
    _write_object(
        output_path,
        {"replay_results": [item.result.model_dump(mode="json") for item in seed_replay.cases]},
    )


def _final(
    catalog_path: Path,
    dataset_path: Path,
    seed_path: Path,
    output_path: Path,
) -> None:
    catalog = load_play_catalog(catalog_path)
    registry = compile_semantics_registry(catalog)
    seed_payload = _read_object(seed_path)
    raw_results = seed_payload.get("replay_results")
    if not isinstance(raw_results, list):
        raise ValueError("seed phase did not emit replay_results")
    seed_results = tuple(FamilyReplayResult.model_validate(item) for item in raw_results)
    world = compile_functional_world(registry, dataset_path, replay_results=seed_results)
    replay = compile_f1_replay_evidence(registry, world.world_snapshot)
    property_suite = compile_f1_property_suite_evidence(
        catalog=catalog,
        registry=registry,
        world=world.world_snapshot,
        replay=replay,
    )
    _write_object(
        output_path,
        {
            "event_matrix_snapshot": world.event_matrix_snapshot.model_dump(mode="json"),
            "world_snapshot": world.world_snapshot.model_dump(mode="json"),
            "replay": replay.model_dump(mode="json"),
            "property_suite": property_suite.model_dump(mode="json"),
            "draw_total": len(world.loaded_dataset.draws),
            "event_keys": world.functional_key_proof,
        },
    )


def _reordered(
    catalog_path: Path,
    dataset_path: Path,
    final_path: Path,
    output_path: Path,
) -> None:
    registry = _registry(catalog_path)
    final_payload = _read_object(final_path)
    replay = F1RepresentativeReplayEvidence.model_validate(final_payload.get("replay"))
    event_snapshot = final_payload.get("event_matrix_snapshot")
    world_snapshot = final_payload.get("world_snapshot")
    event_keys = final_payload.get("event_keys")
    if not all(isinstance(item, dict) for item in (event_snapshot, world_snapshot, event_keys)):
        raise ValueError("final phase did not emit both world snapshots and key proof")

    lines = dataset_path.read_text(encoding="utf-8").splitlines()
    marker = next(
        index for index, line in enumerate(lines) if line.startswith("【API完整字段 JSONL")
    )
    with tempfile.TemporaryDirectory(prefix="xinao-f1-reordered-phase-") as temporary:
        reordered_dataset = Path(temporary) / "authority_reordered.txt"
        reordered_dataset.write_text(
            "\n".join([*lines[: marker + 1], *reversed(lines[marker + 1 :])]) + "\n",
            encoding="utf-8",
        )
        reordered = compile_functional_world(
            registry,
            reordered_dataset,
            replay_results=tuple(item.result for item in replay.cases),
        )
    _write_object(
        output_path,
        {
            "matches": (
                reordered.event_matrix_snapshot.content_hash == event_snapshot.get("content_hash")
                and reordered.world_snapshot.content_hash == world_snapshot.get("content_hash")
                and reordered.functional_key_proof == event_keys
            )
        },
    )


def _dispatch(argv: list[str]) -> None:
    if len(argv) < 4:
        raise ValueError("phase worker requires phase, catalog, dataset, and output paths")
    phase = argv[0]
    catalog_path = Path(argv[1]).resolve()
    dataset_path = Path(argv[2]).resolve()
    paths = [Path(value).resolve() for value in argv[3:]]
    if phase == "seed" and len(paths) == 1:
        _seed(catalog_path, dataset_path, paths[0])
    elif phase == "final" and len(paths) == 2:
        _final(catalog_path, dataset_path, paths[0], paths[1])
    elif phase == "reordered" and len(paths) == 2:
        _reordered(catalog_path, dataset_path, paths[0], paths[1])
    else:
        raise ValueError(f"unknown or malformed F1 phase: {phase}")


if __name__ == "__main__":
    _dispatch(sys.argv[1:])
