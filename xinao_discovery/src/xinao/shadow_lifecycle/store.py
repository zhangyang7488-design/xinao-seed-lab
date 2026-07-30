"""File-backed exclusive store for one prospective shadow episode (leg A).

Uses create-exclusive writes for once-only freeze/settlement artifacts. No daemon,
database, or network side effects. Candidate authority only.
"""

from __future__ import annotations

import json
import os
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
SETTLEMENT_INTENT_NAME = "settlement_intent.v1.json"
OUTCOME_NAME = "outcome.v1.json"
SETTLED_NAME = "settled_episode.v1.json"
RECEIPT_NAME = "consumer_receipt.v1.json"
MANIFEST_NAME = "package_manifest.v1.json"

SCHEMA_RECEIPT = "xinao.shadow_lifecycle.consumer_receipt.v1"
SCHEMA_MANIFEST = "xinao.shadow_lifecycle.package_manifest.v1"
SCHEMA_SETTLEMENT_INTENT = "xinao.shadow_lifecycle.settlement_intent.v1"


class EpisodePhase(StrEnum):
    MISSING = "MISSING"
    INIT = "INIT"
    FROZEN = "FROZEN"
    # Intent sealed (and optionally outcome) but settled missing. Recoverable only on
    # exact full-intent match; outcome-only match is insufficient.
    SETTLEMENT_RECOVERY_REQUIRED = "SETTLEMENT_RECOVERY_REQUIRED"
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


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Stdlib-only replace write for receipt/manifest projection (sealed cone).

    Matches catalog.compiler.write_atomic: temp sibling + os.replace. Does not
    import outside the locked shadow-runtime inventory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


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
        "intent": base / SETTLEMENT_INTENT_NAME,
        "outcome": base / OUTCOME_NAME,
        "settled": base / SETTLED_NAME,
        "receipt": base / RECEIPT_NAME,
        "manifest": base / MANIFEST_NAME,
    }


def detect_phase(root: Path) -> EpisodePhase:
    """Map exclusive artifacts to phase; fail closed on corrupt combinations.

    Settlement is a three-step exclusive journal: intent → outcome → settled.
    Intent-only or intent+outcome (no settled) is SETTLEMENT_RECOVERY_REQUIRED so an
    exact full-intent retry may resume once; settled remains required for SETTLED/replay.
    Outcome without a sealed intent is corrupt (settlement identity unbound).
    """
    paths = artifact_paths(root)
    has_settled = paths["settled"].is_file()
    has_outcome = paths["outcome"].is_file()
    has_intent = paths["intent"].is_file()
    has_frozen = paths["frozen"].is_file()
    has_seat = paths["seat"].is_file()

    if has_settled:
        if not has_frozen:
            raise StoreError("corrupt store: settled without frozen episode")
        if not has_outcome:
            raise StoreError("corrupt store: settled without outcome")
        if not has_intent:
            raise StoreError("corrupt store: settled without settlement intent")
        _assert_outcome_matches_intent(root)
        return EpisodePhase.SETTLED
    if has_intent or has_outcome:
        if has_outcome and not has_intent:
            raise StoreError("corrupt store: outcome without settlement intent")
        if not has_frozen:
            raise StoreError("corrupt store: settlement intent without frozen episode")
        if has_outcome:
            _assert_outcome_matches_intent(root)
        return EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED
    if has_frozen:
        return EpisodePhase.FROZEN
    if has_seat:
        return EpisodePhase.INIT
    return EpisodePhase.MISSING


def _sealed_outcome_jsonable(outcome: OutcomeObservation) -> dict[str, Any]:
    outcome.require_valid_result_hash()
    return model_to_jsonable(outcome)


def _sealed_settled_jsonable(settled: SettledShadowEpisode) -> dict[str, Any]:
    if settled.content_hash is None:
        raise StoreError("settled episode must be hash sealed before intent bind")
    if settled.content_hash != settled.compute_content_hash():
        raise StoreError("settled episode content seal invalid")
    return model_to_jsonable(settled)


def build_settlement_intent(
    *,
    outcome: OutcomeObservation,
    settled: SettledShadowEpisode,
) -> dict[str, Any]:
    """Hash-seal complete proposed outcome + settled artifacts before any outcome write."""
    outcome_body = _sealed_outcome_jsonable(outcome)
    settled_body = _sealed_settled_jsonable(settled)
    if settled_body.get("outcome") != outcome_body:
        raise StoreError("settlement intent binds mismatched outcome and settled.outcome")
    body: dict[str, Any] = {
        "schema_version": SCHEMA_SETTLEMENT_INTENT,
        "outcome": outcome_body,
        "settled": settled_body,
        "settled_episode_hash": settled.content_hash,
    }
    body["content_hash"] = canonical_sha256(
        {key: value for key, value in body.items() if key != "content_hash"}
    )
    return body


def _require_valid_intent_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StoreError("settlement intent must be a JSON object")
    if raw.get("schema_version") != SCHEMA_SETTLEMENT_INTENT:
        raise StoreError("settlement intent schema invalid")
    required = ("outcome", "settled", "settled_episode_hash", "content_hash")
    missing = [key for key in required if key not in raw]
    if missing:
        raise StoreError(f"settlement intent missing fields: {', '.join(missing)}")
    body = {key: value for key, value in raw.items() if key != "content_hash"}
    expected = canonical_sha256(body)
    if raw.get("content_hash") != expected:
        raise StoreError("settlement intent content seal invalid")
    settled_body = raw["settled"]
    if not isinstance(settled_body, dict):
        raise StoreError("settlement intent settled payload invalid")
    if settled_body.get("content_hash") != raw.get("settled_episode_hash"):
        raise StoreError("settlement intent settled_episode_hash mismatch")
    if settled_body.get("outcome") != raw.get("outcome"):
        raise StoreError("settlement intent outcome/settled.outcome mismatch")
    return raw


def load_settlement_intent(root: Path) -> dict[str, Any]:
    return _require_valid_intent_payload(read_json(artifact_paths(root)["intent"]))


def settlement_intents_identical(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """True iff sealed full intent matches (outcome + settled artifacts + intent hash)."""
    left = _require_valid_intent_payload(existing)
    right = _require_valid_intent_payload(candidate)
    return left == right


def _assert_outcome_matches_intent(root: Path) -> None:
    intent = load_settlement_intent(root)
    outcome = load_outcome(root)
    if intent["outcome"] != _sealed_outcome_jsonable(outcome):
        raise StoreError("corrupt store: outcome does not match sealed settlement intent")


def outcomes_identical_for_recovery(
    existing: OutcomeObservation, candidate: OutcomeObservation
) -> bool:
    """True iff sealed outcome content matches (byte-stable JSON dump)."""
    return _sealed_outcome_jsonable(existing) == _sealed_outcome_jsonable(candidate)


def _try_write_new_json_or_load(path: Path, payload: Any) -> tuple[bool, Any | None]:
    """Exclusive create; on race-loss re-read existing JSON. Returns (created, existing)."""
    try:
        write_new_json(path, payload)
        return True, None
    except StoreError as exc:
        if "already exists" not in str(exc):
            raise
        if not path.is_file():
            raise
        return False, read_json(path)


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
    if paths["intent"].is_file() or paths["outcome"].is_file() or paths["settled"].is_file():
        raise StoreError("no-peek violation: cannot freeze after outcome or settlement artifacts")
    path = paths["frozen"]
    write_new_json(path, model_to_jsonable(episode))
    return path


def write_outcome_and_settled_exclusive(
    root: Path,
    *,
    outcome: OutcomeObservation,
    settled: SettledShadowEpisode,
) -> tuple[Path, Path, Path]:
    """Exclusive settlement journal: intent → outcome → settled; exact-intent recovery.

    Normal path: exclusive create hash-sealed settlement intent (binds full proposed
    outcome and settled artifacts), then exclusive create outcome, then settled.
    Crash after intent (before outcome) or after outcome (before settled) leaves
    SETTLEMENT_RECOVERY_REQUIRED. Recovery accepts only an exact full-intent match;
    differing settlement_ref/journal refs/statement_ref/occurred_at (or outcome)
    fail closed with no overwrite. Fully settled remains once-only.
    """
    intent = build_settlement_intent(outcome=outcome, settled=settled)
    paths = artifact_paths(root)
    if not paths["frozen"].is_file():
        raise StoreError("settle requires frozen episode")
    intent_path = paths["intent"]
    outcome_path = paths["outcome"]
    settled_path = paths["settled"]
    outcome_body = intent["outcome"]
    settled_body = intent["settled"]

    # Fully sealed ledger: never overwrite settled.
    if settled_path.is_file():
        raise StoreError(f"exclusive create rejected; already exists: {settled_path.name}")

    # Step 1: exclusive settlement intent (complete outcome + settled identity).
    if intent_path.is_file():
        existing_intent = load_settlement_intent(root)
        if not settlement_intents_identical(existing_intent, intent):
            raise StoreError(
                "conflicting settlement recovery rejected: sealed settlement intent "
                "does not match retry (outcome and/or settlement identity differ)"
            )
    else:
        created, existing_raw = _try_write_new_json_or_load(intent_path, intent)
        if not created:
            existing_intent = _require_valid_intent_payload(existing_raw)
            if not settlement_intents_identical(existing_intent, intent):
                raise StoreError(
                    "conflicting settlement recovery rejected: sealed settlement intent "
                    "does not match retry (outcome and/or settlement identity differ)"
                )

    # Step 2: exclusive outcome bound by sealed intent.
    if outcome_path.is_file():
        existing_outcome = load_outcome(root)
        if _sealed_outcome_jsonable(existing_outcome) != outcome_body:
            raise StoreError("corrupt store: outcome does not match sealed settlement intent")
        if not outcomes_identical_for_recovery(existing_outcome, outcome):
            raise StoreError(
                "conflicting settlement recovery rejected: sealed outcome "
                "does not match retry outcome"
            )
    else:
        created, existing_raw = _try_write_new_json_or_load(outcome_path, outcome_body)
        if not created:
            existing_outcome = OutcomeObservation.model_validate(existing_raw)
            existing_outcome.require_valid_result_hash()
            if _sealed_outcome_jsonable(existing_outcome) != outcome_body:
                raise StoreError("corrupt store: outcome does not match sealed settlement intent")
            if not outcomes_identical_for_recovery(existing_outcome, outcome):
                raise StoreError(
                    "conflicting settlement recovery rejected: sealed outcome "
                    "does not match retry outcome"
                )

    # Step 3: exclusive settled; leave intent/outcome in place on failure (no overwrite).
    try:
        write_new_json(settled_path, settled_body)
    except StoreError:
        raise
    return intent_path, outcome_path, settled_path


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
        _write_json_atomic(path, body)
    else:
        write_new_json(path, body)
    return path


def write_manifest(root: Path) -> dict[str, Any]:
    import hashlib

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
    _write_json_atomic(path, manifest)
    return manifest


def load_bound_frozen_decision(payload: dict[str, Any]) -> FrozenDecision:
    decision = FrozenDecision.model_validate(payload)
    if decision.content_hash is None or decision.content_hash != decision.compute_content_hash():
        raise StoreError("bound FrozenDecision content seal invalid")
    return decision
