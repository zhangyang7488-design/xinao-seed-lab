"""File-backed exclusive store for one prospective shadow episode (leg A).

Uses create-exclusive writes for once-only freeze/settlement artifacts. No daemon,
database, or network side effects. Candidate authority only.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.decision import FrozenDecision
from xinao.settlement import OutcomeObservation
from xinao.shadow_lifecycle.lifecycle import (
    FrozenShadowEpisode,
    SettledShadowEpisode,
    ShadowSeat,
)

SEAT_NAME = "seat.v1.json"
FROZEN_NAME = "frozen_episode.v1.json"
OUTCOME_NAME = "outcome.v1.json"
SETTLED_NAME = "settled_episode.v1.json"
RECEIPT_NAME = "consumer_receipt.v1.json"
MANIFEST_NAME = "package_manifest.v1.json"

SCHEMA_RECEIPT = "xinao.shadow_lifecycle.consumer_receipt.v1"
SCHEMA_MANIFEST = "xinao.shadow_lifecycle.package_manifest.v1"


class EpisodePhase(StrEnum):
    MISSING = "MISSING"
    INIT = "INIT"
    FROZEN = "FROZEN"
    SETTLED = "SETTLED"


class StoreError(ValueError):
    """Typed store failure for CLI mapping."""


def _write_new_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
    except FileExistsError as exc:
        raise StoreError(f"exclusive create rejected; already exists: {path.name}") from exc


def write_new_json(path: Path, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write_new_bytes(path, body.encode("utf-8"))


def read_json(path: Path) -> Any:
    if not path.is_file():
        raise StoreError(f"missing artifact: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def model_to_jsonable(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def resolve_root(root: Path) -> Path:
    return root.expanduser().resolve()


def artifact_paths(root: Path) -> dict[str, Path]:
    base = resolve_root(root)
    return {
        "seat": base / SEAT_NAME,
        "frozen": base / FROZEN_NAME,
        "outcome": base / OUTCOME_NAME,
        "settled": base / SETTLED_NAME,
        "receipt": base / RECEIPT_NAME,
        "manifest": base / MANIFEST_NAME,
    }


def detect_phase(root: Path) -> EpisodePhase:
    paths = artifact_paths(root)
    if paths["settled"].is_file():
        return EpisodePhase.SETTLED
    if paths["frozen"].is_file():
        return EpisodePhase.FROZEN
    if paths["seat"].is_file():
        return EpisodePhase.INIT
    return EpisodePhase.MISSING


def load_seat(root: Path) -> ShadowSeat:
    raw = read_json(artifact_paths(root)["seat"])
    seat = ShadowSeat.model_validate(raw)
    if seat.content_hash is None or seat.content_hash != seat.compute_content_hash():
        raise StoreError("seat content seal invalid")
    return seat


def load_frozen(root: Path) -> FrozenShadowEpisode:
    raw = read_json(artifact_paths(root)["frozen"])
    episode = FrozenShadowEpisode.model_validate(raw)
    if episode.content_hash is None or episode.content_hash != episode.compute_content_hash():
        raise StoreError("frozen episode content seal invalid")
    return episode


def load_outcome(root: Path) -> OutcomeObservation:
    raw = read_json(artifact_paths(root)["outcome"])
    outcome = OutcomeObservation.model_validate(raw)
    outcome.require_valid_result_hash()
    return outcome


def load_settled(root: Path) -> SettledShadowEpisode:
    raw = read_json(artifact_paths(root)["settled"])
    settled = SettledShadowEpisode.model_validate(raw)
    if settled.content_hash is None or settled.content_hash != settled.compute_content_hash():
        raise StoreError("settled episode content seal invalid")
    return settled


def write_seat_exclusive(root: Path, seat: ShadowSeat) -> Path:
    if seat.content_hash is None:
        raise StoreError("seat must be hash sealed before write")
    path = artifact_paths(root)["seat"]
    write_new_json(path, model_to_jsonable(seat))
    return path


def write_frozen_exclusive(root: Path, episode: FrozenShadowEpisode) -> Path:
    if episode.content_hash is None:
        raise StoreError("frozen episode must be hash sealed before write")
    paths = artifact_paths(root)
    if paths["outcome"].is_file() or paths["settled"].is_file():
        raise StoreError("no-peek violation: cannot freeze after outcome or settlement artifacts")
    path = paths["frozen"]
    write_new_json(path, model_to_jsonable(episode))
    return path


def write_outcome_and_settled_exclusive(
    root: Path,
    *,
    outcome: OutcomeObservation,
    settled: SettledShadowEpisode,
) -> tuple[Path, Path]:
    outcome.require_valid_result_hash()
    if settled.content_hash is None:
        raise StoreError("settled episode must be hash sealed before write")
    paths = artifact_paths(root)
    if not paths["frozen"].is_file():
        raise StoreError("settle requires frozen episode")
    # Once-only: outcome then settled; either existing fails closed.
    outcome_path = paths["outcome"]
    settled_path = paths["settled"]
    write_new_json(outcome_path, model_to_jsonable(outcome))
    try:
        write_new_json(settled_path, model_to_jsonable(settled))
    except StoreError:
        # Leave outcome in place so the partial write is visible; do not overwrite.
        raise
    return outcome_path, settled_path


def write_receipt_exclusive_or_replace(
    root: Path,
    receipt: dict[str, Any],
    *,
    replace: bool,
) -> Path:
    path = artifact_paths(root)["receipt"]
    body = dict(receipt)
    if "content_hash" in body:
        body = {k: v for k, v in body.items() if k != "content_hash"}
    body["content_hash"] = canonical_sha256(body)
    if replace and path.is_file():
        # Status/receipt projection may advance after exclusive domain seals.
        from xinao.catalog.compiler import write_atomic

        write_atomic(path, body)
    else:
        write_new_json(path, body)
    return path


def write_manifest(root: Path) -> dict[str, Any]:
    import hashlib

    from xinao.catalog.compiler import write_atomic

    base = resolve_root(root)
    files: dict[str, str] = {}
    for path in sorted(base.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.name == MANIFEST_NAME:
            continue
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": SCHEMA_MANIFEST,
        "root": str(base),
        "files": files,
    }
    manifest["content_hash"] = canonical_sha256(manifest)
    path = artifact_paths(root)["manifest"]
    write_atomic(path, manifest)
    return manifest


def load_bound_frozen_decision(payload: dict[str, Any]) -> FrozenDecision:
    decision = FrozenDecision.model_validate(payload)
    if decision.content_hash is None or decision.content_hash != decision.compute_content_hash():
        raise StoreError("bound FrozenDecision content seal invalid")
    return decision
