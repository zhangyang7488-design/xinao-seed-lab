"""Cold corpus bridge from explicit Context events to qualified Taste pairs.

This module does not search for examples, run a model, retrieve into a live
prompt, or mutate AGENTS/Skills.  It only (1) snapshots an explicitly named
real trajectory and its cold conditions, and (2) admits that snapshot to the
qualified cold set after the existing Taste qualifier accepts both sealed
shadow outcomes and their receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from services.agent_runtime import context_fabric
from services.agent_runtime.context_runtime_completion import _strict_surface_text
from services.agent_runtime.execution_contract import canonical_json_bytes
from services.agent_runtime.taste_qualification import (
    TasteQualificationError,
    build_taste_candidate,
    validate_sealed_taste_outcome,
    validate_taste_candidate,
    validate_taste_qualification_receipt,
)

CANDIDATE_BUNDLE_SCHEMA = "s.taste_corpus_candidate_bundle.v2"
QUALIFIED_BUNDLE_SCHEMA = "s.taste_corpus_qualified_bundle.v2"

_EVENT_ID_RE = re.compile(r"^evt_[0-9a-f]{64}$")
_MAX_CONDITION_BYTES = 8 * 1024 * 1024
_MAX_JSON_BYTES = 16 * 1024 * 1024


class TasteCorpusError(ValueError):
    """A source or cold-corpus binding failed closed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(code: str, message: str) -> None:
    raise TasteCorpusError(code, message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _seal(value: Mapping[str, object], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = _sha(canonical_json_bytes(result))
    return result


def _verify_seal(value: Mapping[str, object], field: str) -> str:
    observed = value.get(field)
    if not isinstance(observed, str) or re.fullmatch(r"[0-9a-f]{64}", observed) is None:
        _fail("HASH_MISMATCH", f"{field} is invalid")
    unsigned = dict(value)
    unsigned.pop(field, None)
    if _sha(canonical_json_bytes(unsigned)) != observed:
        _fail("HASH_MISMATCH", f"{field} does not seal the record")
    return observed


def _read_file(path: Path, *, limit: int, field: str, allow_empty: bool = False) -> bytes:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        _fail("SOURCE_NOT_REGULAR", f"{field} is not a regular non-link file")
    size = path.stat().st_size
    minimum = 0 if allow_empty else 1
    if size < minimum or size > limit:
        _fail("SOURCE_SIZE_INVALID", f"{field} must contain {minimum}..{limit} bytes")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) != size:
        _fail("SOURCE_CHANGED", f"{field} changed while it was read")
    return raw


def _read_json(path: Path, field: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_file(path, limit=_MAX_JSON_BYTES, field=field)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TasteCorpusError("JSON_INVALID", f"{field} is not UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        _fail("JSON_INVALID", f"{field} must be a JSON object")
    return dict(value), raw


def _event_id(value: object) -> str:
    if not isinstance(value, str) or _EVENT_ID_RE.fullmatch(value) is None:
        _fail("EVENT_ID_INVALID", "Taste sources require explicit canonical event IDs")
    return value


def _carrier_homes(
    supplied: Mapping[str, Path | str] | None,
) -> dict[str, Path]:
    if supplied is not None:
        result = {str(carrier): Path(home) for carrier, home in supplied.items()}
    else:
        result = {
            carrier: Path(home)
            for home, carrier in context_fabric.DEFAULT_ALLOWED_CODEX_HOMES.items()
        }
    if not result or any(not key for key in result):
        _fail("CARRIER_HOME_MISSING", "carrier homes are empty or invalid")
    return result


def _line_record(raw_line: bytes, *, field: str) -> tuple[bytes, dict[str, Any]]:
    record_raw = raw_line.rstrip(b"\r\n")
    if not record_raw or len(raw_line) - len(record_raw) not in {1, 2}:
        _fail("ROLLOUT_RECORD_INCOMPLETE", f"{field} is not one complete JSONL record")
    try:
        value = json.loads(record_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TasteCorpusError("ROLLOUT_RECORD_INVALID", f"{field} is invalid") from exc
    if not isinstance(value, Mapping):
        _fail("ROLLOUT_RECORD_INVALID", f"{field} is not a JSON object")
    return record_raw, dict(value)


def _response_item_surface(
    record: Mapping[str, object], *, expected_speaker: str
) -> tuple[str, str]:
    if record.get("type") != "response_item" or not isinstance(record.get("payload"), Mapping):
        return "", ""
    payload = record["payload"]
    expected_role = "user" if expected_speaker == "user" else "assistant"
    if payload.get("type") != "message" or payload.get("role") != expected_role:
        return "", ""
    content = payload.get("content")
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return "", ""
    expected_block = "input_text" if expected_role == "user" else "output_text"
    parts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != expected_block:
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    metadata = payload.get("internal_chat_message_metadata_passthrough")
    turn_id = str(metadata.get("turn_id") or "") if isinstance(metadata, Mapping) else ""
    return "\n".join(parts), turn_id


def _item_completed_surface(
    record: Mapping[str, object], *, expected_speaker: str
) -> tuple[str, str, str]:
    payload = record.get("payload")
    if (
        record.get("type") != "event_msg"
        or not isinstance(payload, Mapping)
        or payload.get("type") != "item_completed"
        or not isinstance(payload.get("item"), Mapping)
    ):
        return "", "", ""
    item = payload["item"]
    item_type = str(item.get("type") or "")
    expected_type = "UserMessage" if expected_speaker == "user" else "AgentMessage"
    if item_type != expected_type:
        return "", "", ""
    return (
        _strict_surface_text(item, item_type=item_type),
        str(payload.get("thread_id") or ""),
        str(payload.get("turn_id") or ""),
    )


def _reopen_rollout(event: Mapping[str, object], carrier_home: Path) -> tuple[int, str, bytes, str]:
    locator = str(event.get("source_locator") or "")
    relative, marker, ordinal_text = locator.rpartition("#")
    metadata = event.get("metadata")
    ordinal = int(ordinal_text) if marker and ordinal_text.isdigit() else -1
    if (
        ordinal < 1
        or not isinstance(metadata, Mapping)
        or metadata.get("ordinal") != ordinal
        or not relative.replace("/", "\\").lower().startswith("sessions\\")
    ):
        _fail("ROLLOUT_LOCATOR_INVALID", "event does not have an exact rollout ordinal")

    requested = Path(carrier_home) / Path(relative.replace("\\", os.sep))
    try:
        rollout, canonical_locator = context_fabric._contained_rollout_path(
            requested, Path(carrier_home)
        )
    except (OSError, ValueError, context_fabric.ContextFabricError) as exc:
        raise TasteCorpusError(
            "ROLLOUT_SOURCE_UNAVAILABLE", "exact rollout source is unavailable or unsafe"
        ) from exc
    if canonical_locator.replace("/", "\\").lower() != relative.replace("/", "\\").lower():
        _fail("ROLLOUT_LOCATOR_INVALID", "rollout locator resolves to another source")

    selected_line = b""
    with rollout.open("rb") as handle:
        for current in range(ordinal + 1):
            line = handle.readline(context_fabric._MAX_ROLLOUT_LINE_BYTES + 2)
            if not line:
                _fail("ROLLOUT_SOURCE_TRUNCATED", "rollout ended before the event")
            if current == ordinal:
                selected_line = line
    selected, record = _line_record(selected_line, field="rollout record")
    if _sha(selected) != event.get("source_record_sha256"):
        _fail("ROLLOUT_RECORD_HASH_MISMATCH", "rollout record no longer matches Context")
    if record.get("ordinal") != ordinal:
        _fail("ROLLOUT_RECORD_INVALID", "rollout record is not the referenced surface")
    text, thread_id, turn_id = _item_completed_surface(
        record, expected_speaker=str(event.get("speaker") or "")
    )
    if (
        text != event.get("raw_text")
        or thread_id != event.get("session_id")
        or turn_id != event.get("turn_id")
    ):
        _fail("ROLLOUT_SURFACE_MISMATCH", "rollout and canonical surface bytes differ")
    return ordinal, canonical_locator, selected_line, "item_completed"


def _reopen_exec_rollout(
    event: Mapping[str, object], *, carrier_home: Path, rollout_path: Path
) -> tuple[int, str, bytes, str]:
    try:
        rollout, canonical_locator = context_fabric._contained_rollout_path(
            Path(rollout_path), Path(carrier_home)
        )
    except (OSError, ValueError, context_fabric.ContextFabricError) as exc:
        raise TasteCorpusError(
            "ROLLOUT_SOURCE_UNAVAILABLE", "exact exec rollout source is unavailable or unsafe"
        ) from exc

    matches: list[tuple[int, bytes]] = []
    session_id = str(event.get("session_id") or "")
    turn_id = str(event.get("turn_id") or "")
    expected_text = str(event.get("raw_text") or "")
    observed_session = ""
    with rollout.open("rb") as handle:
        for ordinal, raw_line in enumerate(handle):
            if len(raw_line) > context_fabric._MAX_ROLLOUT_LINE_BYTES + 1:
                _fail("ROLLOUT_RECORD_INVALID", "exec rollout record exceeds the line limit")
            record_raw, record = _line_record(raw_line, field=f"exec rollout record {ordinal}")
            if record.get("type") == "session_meta" and isinstance(record.get("payload"), Mapping):
                payload = record["payload"]
                observed_session = str(payload.get("id") or payload.get("session_id") or "")
            text, record_turn = _response_item_surface(
                record, expected_speaker=str(event.get("speaker") or "")
            )
            if text == expected_text and record_turn == turn_id:
                matches.append((ordinal, raw_line))
    if observed_session != session_id:
        _fail("ROLLOUT_SESSION_MISMATCH", "exec rollout belongs to another session")
    if len(matches) != 1:
        _fail(
            "ROLLOUT_SURFACE_AMBIGUOUS",
            "exec rollout must contain exactly one response_item for the Context event",
        )
    ordinal, raw_line = matches[0]
    return ordinal, canonical_locator, raw_line, "exec_response_item"


def _load_source(
    event_id: str,
    *,
    context_root: Path,
    homes: Mapping[str, Path],
    session_rollouts: Mapping[str, Path],
) -> tuple[dict[str, object], bytes, bytes]:
    try:
        event = context_fabric.read_event(event_id, root=Path(context_root))
    except (OSError, context_fabric.ContextFabricError) as exc:
        raise TasteCorpusError("EVENT_NOT_FOUND", f"event is unavailable: {event_id}") from exc
    if (
        event.get("event_id") != event_id
        or event.get("raw_storage") != "exact_utf8"
        or event.get("event_kind") not in {"user_message", "assistant_message"}
    ):
        _fail("SOURCE_UNSUPPORTED", "Taste requires exact surfaced rollout events")
    raw = str(event.get("raw_text") or "").encode("utf-8")
    if (
        not raw
        or _sha(raw) != event.get("raw_sha256")
        or _sha(raw) != event.get("stored_text_sha256")
    ):
        _fail("EVENT_TEXT_HASH_MISMATCH", "canonical event bytes failed readback")
    carrier = str(event.get("carrier_id") or "")
    if carrier not in homes:
        _fail("CARRIER_HOME_MISSING", f"no source home supplied for {carrier}")
    source_kind = str(event.get("source_kind") or "")
    if source_kind == "codex_rollout_import":
        ordinal, rollout_locator, record_line, record_format = _reopen_rollout(
            event, homes[carrier]
        )
        admission_kind = "canonical_rollout_import"
    elif source_kind == "codex_hook":
        session_id = str(event.get("session_id") or "")
        rollout_override = session_rollouts.get(session_id)
        if rollout_override is None:
            _fail(
                "EXEC_ROLLOUT_REQUIRED",
                f"hook event {event_id} requires an explicit exact exec rollout",
            )
        ordinal, rollout_locator, record_line, record_format = _reopen_exec_rollout(
            event,
            carrier_home=homes[carrier],
            rollout_path=rollout_override,
        )
        admission_kind = "hook_rebound_to_exact_exec_rollout"
    else:
        _fail("SOURCE_UNSUPPORTED", f"unsupported Context source kind: {source_kind}")
    record_raw, _ = _line_record(record_line, field=f"source record {event_id}")
    binding = {
        "event_id": event_id,
        "event_hash": event["event_hash"],
        "seq": event["seq"],
        "carrier_id": carrier,
        "session_id": event["session_id"],
        "turn_id": event["turn_id"],
        "event_kind": event["event_kind"],
        "speaker": event["speaker"],
        "context_source_kind": source_kind,
        "context_source_locator": event["source_locator"],
        "context_source_record_sha256": event["source_record_sha256"],
        "admission_kind": admission_kind,
        "rollout_locator": f"{rollout_locator}#{ordinal}",
        "rollout_record_sha256": _sha(record_raw),
        "rollout_record_file_sha256": _sha(record_line),
        "rollout_record_byte_length": len(record_line),
        "rollout_record_format": record_format,
        "ordinal": ordinal,
        "relative_path": f"sources/{event_id}.utf8",
        "rollout_record_relative_path": f"sources/{event_id}.rollout.jsonl",
        "byte_sha256": _sha(raw),
        "byte_length": len(raw),
    }
    return binding, raw, record_line


def _source_ref(binding: Mapping[str, object]) -> dict[str, object]:
    return {
        "source_ref": f"context-event://{binding['event_id']}",
        "byte_sha256": binding["byte_sha256"],
        "byte_length": binding["byte_length"],
        "rollout_locator": binding["rollout_locator"],
        "ordinal": binding["ordinal"],
    }


def _write_directory(target: Path, files: Mapping[str, bytes]) -> str:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return "existing"
    staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        for relative, raw in files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        staging.rename(target)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return "created"


def _bound_file(root: Path, binding: Mapping[str, object], field: str) -> bytes:
    relative = binding.get("relative_path")
    if not isinstance(relative, str) or not relative:
        _fail("BUNDLE_FILE_MISMATCH", f"{field} has no relative path")
    try:
        path = (root / relative).resolve(strict=True)
        path.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise TasteCorpusError("BUNDLE_PATH_INVALID", f"{field} escaped the bundle") from exc
    raw = _read_file(path, limit=_MAX_JSON_BYTES, field=field)
    if len(raw) != binding.get("byte_length") or _sha(raw) != binding.get("byte_sha256"):
        _fail("BUNDLE_FILE_MISMATCH", f"{field} bytes differ from the manifest")
    return raw


def _episode_contract(
    *,
    prefix_ids: Sequence[str],
    bad_id: str,
    correction_ids: Sequence[str],
    desired_id: str,
    bindings: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if not correction_ids:
        _fail("CORRECTION_MISSING", "a real Taste episode requires human correction evidence")
    if len(bindings) != len(prefix_ids) + len(correction_ids) + 2:
        _fail("EPISODE_INVALID", "episode bindings are incomplete")
    carriers = {str(item.get("carrier_id") or "") for item in bindings}
    sessions = {str(item.get("session_id") or "") for item in bindings}
    rollout_bases = {str(item.get("rollout_locator") or "").rpartition("#")[0] for item in bindings}
    if len(carriers) != 1 or "" in carriers or len(sessions) != 1 or "" in sessions:
        _fail("EPISODE_IDENTITY_MISMATCH", "episode events must share one carrier and session")
    if len(rollout_bases) != 1 or "" in rollout_bases:
        _fail("EPISODE_IDENTITY_MISMATCH", "episode events must share one exact rollout")
    seqs = [item.get("seq") for item in bindings]
    ordinals = [item.get("ordinal") for item in bindings]
    if (
        any(type(value) is not int for value in seqs)
        or any(type(value) is not int for value in ordinals)
        or seqs != sorted(seqs)
        or ordinals != sorted(ordinals)
        or len(set(seqs)) != len(seqs)
        or len(set(ordinals)) != len(ordinals)
    ):
        _fail("EPISODE_ORDER_INVALID", "episode events are not in strict Context/rollout order")

    prefix_count = len(prefix_ids)
    bad = bindings[prefix_count]
    corrections = bindings[prefix_count + 1 : -1]
    desired = bindings[-1]
    if bindings[prefix_count - 1].get("speaker") != "user":
        _fail("PREFIX_ROLE_INVALID", "the replay prefix must end with the user's request")
    if bad.get("speaker") != "assistant" or bad.get("turn_id") != bindings[prefix_count - 1].get(
        "turn_id"
    ):
        _fail("BAD_CONTINUATION_INVALID", "bad continuation must answer the prefix turn")
    if any(item.get("speaker") != "user" for item in corrections):
        _fail("CORRECTION_ROLE_INVALID", "correction evidence must be human messages")
    if desired.get("speaker") != "assistant" or desired.get("turn_id") != corrections[-1].get(
        "turn_id"
    ):
        _fail("DESIRED_CONTINUATION_INVALID", "desired continuation must answer the correction")
    return {
        "relation": "prefix_bad_human_correction_desired",
        "carrier_id": next(iter(carriers)),
        "session_id": next(iter(sessions)),
        "rollout_locator": next(iter(rollout_bases)),
        "prefix_event_ids": list(prefix_ids),
        "bad_continuation_event_id": bad_id,
        "correction_event_ids": list(correction_ids),
        "desired_continuation_event_id": desired_id,
        "ordered_event_ids": [str(item["event_id"]) for item in bindings],
        "ordered_context_seqs": [int(value) for value in seqs],
        "ordered_rollout_ordinals": [int(value) for value in ordinals],
    }


def build_cold_taste_candidate(
    *,
    context_root: Path,
    corpus_root: Path,
    prefix_event_ids: Sequence[str],
    bad_continuation_event_id: str,
    correction_event_ids: Sequence[str],
    desired_continuation_event_id: str,
    baseline_condition_path: Path,
    treatment_condition_path: Path,
    model_identity: str,
    body_identity: str,
    config_identity: str,
    carrier_homes: Mapping[str, Path | str] | None = None,
    session_rollout_paths: Mapping[str, Path | str] | None = None,
) -> dict[str, object]:
    """Snapshot one explicit real-trajectory contrastive candidate."""

    if isinstance(prefix_event_ids, (str, bytes)) or not prefix_event_ids:
        _fail("EVENT_IDS_MISSING", "prefix event IDs must be explicit and non-empty")
    prefix_ids = [_event_id(item) for item in prefix_event_ids]
    bad_id = _event_id(bad_continuation_event_id)
    if isinstance(correction_event_ids, (str, bytes)):
        _fail("CORRECTION_MISSING", "correction event IDs must be an explicit sequence")
    correction_ids = [_event_id(item) for item in correction_event_ids]
    desired_id = _event_id(desired_continuation_event_id)
    event_ids = [*prefix_ids, bad_id, *correction_ids, desired_id]
    if len(event_ids) != len(set(event_ids)):
        _fail("EVENT_IDS_DUPLICATE", "Taste source event IDs must be distinct")

    homes = _carrier_homes(carrier_homes)
    rollout_paths = {
        str(session): Path(path) for session, path in (session_rollout_paths or {}).items()
    }
    try:
        context_chain = context_fabric.verify_event_chain(Path(context_root))
    except (OSError, context_fabric.ContextFabricError) as exc:
        raise TasteCorpusError(
            "CONTEXT_CHAIN_INVALID", "Context event chain failed verification"
        ) from exc
    bindings: list[dict[str, object]] = []
    source_bytes: dict[str, bytes] = {}
    record_bytes: dict[str, bytes] = {}
    for event_id in event_ids:
        binding, raw, record = _load_source(
            event_id,
            context_root=context_root,
            homes=homes,
            session_rollouts=rollout_paths,
        )
        bindings.append(binding)
        source_bytes[event_id] = raw
        record_bytes[event_id] = record
    episode = _episode_contract(
        prefix_ids=prefix_ids,
        bad_id=bad_id,
        correction_ids=correction_ids,
        desired_id=desired_id,
        bindings=bindings,
    )

    baseline = _read_file(
        baseline_condition_path, limit=_MAX_CONDITION_BYTES, field="baseline condition"
    )
    treatment = _read_file(
        treatment_condition_path, limit=_MAX_CONDITION_BYTES, field="treatment condition"
    )
    refs = [_source_ref(item) for item in bindings]
    bad_index = len(prefix_ids)
    desired_index = len(bindings) - 1
    try:
        candidate = build_taste_candidate(
            baseline_prefix=refs[: len(prefix_ids)],
            treatment_prefix=[dict(item) for item in refs[: len(prefix_ids)]],
            bad_continuation={
                "text": source_bytes[bad_id].decode("utf-8"),
                "source": refs[bad_index],
            },
            desired_continuation={
                "text": source_bytes[desired_id].decode("utf-8"),
                "source": refs[desired_index],
            },
            model_identity=model_identity,
            body_identity=body_identity,
            config_identity=config_identity,
            baseline_condition_sha256=_sha(baseline),
            treatment_condition_sha256=_sha(treatment),
        )
    except TasteQualificationError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc

    candidate_sha = str(candidate["candidate_sha256"])
    conditions = {
        "baseline": {
            "relative_path": "conditions/baseline.condition",
            "byte_sha256": _sha(baseline),
            "byte_length": len(baseline),
        },
        "treatment": {
            "relative_path": "conditions/treatment.condition",
            "byte_sha256": _sha(treatment),
            "byte_length": len(treatment),
        },
    }
    manifest = _seal(
        {
            "schema_version": CANDIDATE_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "selection_mode": "explicit_context_event_ids_only",
            "candidate_sha256": candidate_sha,
            "source_event_ids": event_ids,
            "prefix_count": len(prefix_ids),
            "correction_count": len(correction_ids),
            "episode": episode,
            "context_chain": {
                "event_count": context_chain["event_count"],
                "tip_event_hash": context_chain["tip_event_hash"],
                "sqlite_quick_check": context_chain["sqlite_quick_check"],
            },
            "source_bindings": bindings,
            "conditions": conditions,
        },
        "bundle_sha256",
    )
    target = Path(corpus_root) / "candidates" / candidate_sha
    files = {
        "candidate.json": canonical_json_bytes(candidate),
        "manifest.json": canonical_json_bytes(manifest),
        "conditions/baseline.condition": baseline,
        "conditions/treatment.condition": treatment,
        **{f"sources/{event_id}.utf8": source_bytes[event_id] for event_id in event_ids},
        **{f"sources/{event_id}.rollout.jsonl": record_bytes[event_id] for event_id in event_ids},
    }
    status = _write_directory(target, files)
    verified = verify_candidate_bundle(target)
    return {
        "status": status,
        "candidate_sha256": candidate_sha,
        "bundle_sha256": verified["bundle_sha256"],
        "candidate_directory": str(target.resolve()),
        "source_event_ids": event_ids,
        "live_activation_allowed": False,
    }


def _verify_rollout_record(
    binding: Mapping[str, object], *, record_line: bytes, surface: bytes
) -> None:
    if len(record_line) != binding.get("rollout_record_byte_length") or _sha(
        record_line
    ) != binding.get("rollout_record_file_sha256"):
        _fail("SOURCE_BINDING_MISMATCH", "rollout record file identity drifted")
    record_raw, record = _line_record(record_line, field="bundled rollout record")
    if _sha(record_raw) != binding.get("rollout_record_sha256"):
        _fail("SOURCE_BINDING_MISMATCH", "rollout record content identity drifted")
    expected_text = surface.decode("utf-8")
    record_format = binding.get("rollout_record_format")
    if record_format == "item_completed":
        if record.get("ordinal") != binding.get("ordinal"):
            _fail("SOURCE_BINDING_MISMATCH", "item_completed ordinal drifted")
        text, session_id, turn_id = _item_completed_surface(
            record, expected_speaker=str(binding.get("speaker") or "")
        )
        if session_id != binding.get("session_id") or turn_id != binding.get("turn_id"):
            _fail("SOURCE_BINDING_MISMATCH", "item_completed identity drifted")
    elif record_format == "exec_response_item":
        text, turn_id = _response_item_surface(
            record, expected_speaker=str(binding.get("speaker") or "")
        )
        if turn_id != binding.get("turn_id"):
            _fail("SOURCE_BINDING_MISMATCH", "exec response turn identity drifted")
    else:
        _fail("SOURCE_BINDING_MISMATCH", "unknown bundled rollout record format")
    if text != expected_text:
        _fail("SOURCE_BINDING_MISMATCH", "rollout record surface bytes drifted")


def verify_candidate_bundle(candidate_dir: Path) -> dict[str, Any]:
    """Verify all bytes needed to replay a cold candidate."""

    root = Path(candidate_dir)
    manifest, _ = _read_json(root / "manifest.json", "candidate manifest")
    bundle_sha = _verify_seal(manifest, "bundle_sha256")
    if (
        manifest.get("schema_version") != CANDIDATE_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("selection_mode") != "explicit_context_event_ids_only"
    ):
        _fail("BUNDLE_POLICY_INVALID", "candidate bundle is not cold and explicit")
    candidate_value, candidate_raw = _read_json(root / "candidate.json", "candidate")
    try:
        candidate = validate_taste_candidate(candidate_value)
    except TasteQualificationError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc
    candidate_sha = candidate["candidate_sha256"]
    if (
        candidate_raw != canonical_json_bytes(candidate)
        or candidate_sha != manifest.get("candidate_sha256")
        or root.name != candidate_sha
    ):
        _fail("CANDIDATE_MISMATCH", "candidate bytes or identity differ from the manifest")

    ids = manifest.get("source_event_ids")
    bindings = manifest.get("source_bindings")
    prefix_count = manifest.get("prefix_count")
    correction_count = manifest.get("correction_count")
    episode = manifest.get("episode")
    if (
        not isinstance(ids, list)
        or not ids
        or not isinstance(bindings, list)
        or len(bindings) != len(ids)
        or type(prefix_count) is not int
        or prefix_count < 1
        or type(correction_count) is not int
        or correction_count < 1
        or len(ids) != prefix_count + correction_count + 2
        or not isinstance(episode, Mapping)
    ):
        _fail("SOURCE_BINDING_MISMATCH", "source event bindings are incomplete")
    refs: list[dict[str, object]] = []
    blobs: list[bytes] = []
    for event_id, raw_binding in zip(ids, bindings, strict=True):
        event_id = _event_id(event_id)
        if not isinstance(raw_binding, Mapping) or raw_binding.get("event_id") != event_id:
            _fail("SOURCE_BINDING_MISMATCH", "source binding identity drifted")
        binding = dict(raw_binding)
        blob = _bound_file(root, binding, f"source {event_id}")
        record_binding = {
            "relative_path": binding.get("rollout_record_relative_path"),
            "byte_sha256": binding.get("rollout_record_file_sha256"),
            "byte_length": binding.get("rollout_record_byte_length"),
        }
        record_line = _bound_file(root, record_binding, f"rollout record {event_id}")
        if binding.get("rollout_record_sha256") is None or binding.get("ordinal") is None:
            _fail("SOURCE_BINDING_MISMATCH", "source lacks exact rollout provenance")
        _verify_rollout_record(binding, record_line=record_line, surface=blob)
        refs.append(_source_ref(binding))
        blobs.append(blob)
    normalized_episode = _episode_contract(
        prefix_ids=[_event_id(item) for item in episode.get("prefix_event_ids", [])],
        bad_id=_event_id(episode.get("bad_continuation_event_id")),
        correction_ids=[_event_id(item) for item in episode.get("correction_event_ids", [])],
        desired_id=_event_id(episode.get("desired_continuation_event_id")),
        bindings=bindings,
    )
    if dict(episode) != normalized_episode or normalized_episode["ordered_event_ids"] != ids:
        _fail("EPISODE_INVALID", "episode manifest differs from exact source bindings")
    if candidate["baseline_prefix"]["sources"] != refs[:prefix_count]:
        _fail("SOURCE_BINDING_MISMATCH", "candidate prefix refs differ from source blobs")
    provenance = candidate["offline_oracle"]["source_provenance"]
    oracle = candidate["offline_oracle"]
    bad_index = prefix_count
    desired_index = len(ids) - 1
    if (
        provenance["bad_continuation"] != refs[bad_index]
        or provenance["desired_continuation"] != refs[desired_index]
        or oracle["bad_continuation"]["text"].encode("utf-8") != blobs[bad_index]
        or oracle["desired_continuation"]["text"].encode("utf-8") != blobs[desired_index]
    ):
        _fail("SOURCE_BINDING_MISMATCH", "continuation refs or bytes drifted")

    conditions = manifest.get("conditions")
    if not isinstance(conditions, Mapping):
        _fail("CONDITION_MISMATCH", "condition bindings are missing")
    for arm in ("baseline", "treatment"):
        binding = conditions.get(arm)
        if not isinstance(binding, Mapping):
            _fail("CONDITION_MISMATCH", f"{arm} condition binding is missing")
        _bound_file(root, binding, f"{arm} condition")
        if binding.get("byte_sha256") != candidate["conditions"][arm]:
            _fail("CONDITION_MISMATCH", f"{arm} condition differs from the candidate")
    return {
        "candidate": candidate,
        "candidate_sha256": candidate_sha,
        "bundle_sha256": bundle_sha,
        "source_event_ids": ids,
        "manifest": manifest,
    }


def promote_qualified_taste_candidate(
    *,
    candidate_dir: Path,
    qualified_root: Path,
    baseline_outcome_path: Path,
    treatment_outcome_path: Path,
    qualification_receipt_path: Path,
    baseline_shadow_dir: Path | None = None,
    treatment_shadow_dir: Path | None = None,
) -> dict[str, object]:
    """Admit one receipt-verified pair to the cold qualified set."""

    if baseline_shadow_dir is None or treatment_shadow_dir is None:
        _fail(
            "SHADOW_EVIDENCE_MISSING",
            "qualified cold admission requires both exact shadow outcome bundles",
        )
    bundle = verify_candidate_bundle(candidate_dir)
    candidate = bundle["candidate"]
    baseline_value, _ = _read_json(baseline_outcome_path, "baseline outcome")
    treatment_value, _ = _read_json(treatment_outcome_path, "treatment outcome")
    receipt_value, _ = _read_json(qualification_receipt_path, "qualification receipt")
    try:
        baseline = validate_sealed_taste_outcome(
            baseline_value, candidate=candidate, expected_arm="baseline"
        )
        treatment = validate_sealed_taste_outcome(
            treatment_value, candidate=candidate, expected_arm="treatment"
        )
        receipt = validate_taste_qualification_receipt(
            receipt_value,
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=treatment,
        )
    except TasteQualificationError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc

    from services.agent_runtime.taste_shadow_runner import (
        TasteShadowRunnerError,
        verify_shadow_outcome_bundle,
    )

    try:
        shadow = {
            "baseline": verify_shadow_outcome_bundle(
                Path(baseline_shadow_dir), candidate_dir=Path(candidate_dir)
            ),
            "treatment": verify_shadow_outcome_bundle(
                Path(treatment_shadow_dir), candidate_dir=Path(candidate_dir)
            ),
        }
    except TasteShadowRunnerError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc
    if (
        shadow["baseline"]["outcome"] != baseline
        or shadow["treatment"]["outcome"] != treatment
        or shadow["baseline"]["consumer_session_identity"]
        == shadow["treatment"]["consumer_session_identity"]
        or shadow["baseline"]["process_id"] == shadow["treatment"]["process_id"]
        or shadow["baseline"]["same_inputs"] != shadow["treatment"]["same_inputs"]
        or shadow["baseline"]["condition_sha256"] == shadow["treatment"]["condition_sha256"]
    ):
        _fail("SHADOW_EVIDENCE_MISMATCH", "shadow evidence differs or reused one session")

    candidate_sha = str(bundle["candidate_sha256"])
    nested = f"candidate/{candidate_sha}"
    baseline_raw = canonical_json_bytes(baseline)
    treatment_raw = canonical_json_bytes(treatment)
    receipt_raw = canonical_json_bytes(receipt)
    files = {
        f"{nested}/manifest.json": canonical_json_bytes(bundle["manifest"]),
        f"{nested}/candidate.json": canonical_json_bytes(candidate),
        "outcomes/baseline.json": baseline_raw,
        "outcomes/treatment.json": treatment_raw,
        "qualification_receipt.json": receipt_raw,
    }
    source_root = Path(candidate_dir)
    for binding in bundle["manifest"]["source_bindings"]:
        relative = str(binding["relative_path"])
        files[f"{nested}/{relative}"] = _bound_file(source_root, binding, relative)
        record_binding = {
            "relative_path": binding["rollout_record_relative_path"],
            "byte_sha256": binding["rollout_record_file_sha256"],
            "byte_length": binding["rollout_record_byte_length"],
        }
        record_relative = str(binding["rollout_record_relative_path"])
        files[f"{nested}/{record_relative}"] = _bound_file(
            source_root, record_binding, record_relative
        )
    for binding in bundle["manifest"]["conditions"].values():
        relative = str(binding["relative_path"])
        files[f"{nested}/{relative}"] = _bound_file(source_root, binding, relative)

    outputs = {
        "baseline": {
            "relative_path": "outcomes/baseline.json",
            "logical_sha256": baseline["outcome_sha256"],
            "byte_sha256": _sha(baseline_raw),
            "byte_length": len(baseline_raw),
        },
        "treatment": {
            "relative_path": "outcomes/treatment.json",
            "logical_sha256": treatment["outcome_sha256"],
            "byte_sha256": _sha(treatment_raw),
            "byte_length": len(treatment_raw),
        },
        "receipt": {
            "relative_path": "qualification_receipt.json",
            "logical_sha256": receipt["receipt_sha256"],
            "byte_sha256": _sha(receipt_raw),
            "byte_length": len(receipt_raw),
        },
    }
    qualified_manifest = _seal(
        {
            "schema_version": QUALIFIED_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "candidate_sha256": candidate_sha,
            "candidate_bundle_sha256": bundle["bundle_sha256"],
            "sealed_outputs": outputs,
            "shadow_outcomes": {
                arm: {
                    "relative_path": f"shadow/{arm}",
                    "bundle_sha256": shadow[arm]["bundle_sha256"],
                    "outcome_sha256": shadow[arm]["outcome"]["outcome_sha256"],
                    "consumer_session_identity": shadow[arm]["consumer_session_identity"],
                }
                for arm in ("baseline", "treatment")
            },
        },
        "qualified_bundle_sha256",
    )
    for arm, source in (
        ("baseline", Path(baseline_shadow_dir)),
        ("treatment", Path(treatment_shadow_dir)),
    ):
        for path in source.rglob("*"):
            if path.is_dir():
                continue
            if path.is_symlink():
                _fail("BUNDLE_PATH_INVALID", "shadow evidence contains a link")
            relative = path.relative_to(source).as_posix()
            files[f"shadow/{arm}/{relative}"] = _read_file(
                path,
                limit=_MAX_JSON_BYTES,
                field=f"shadow {arm} {relative}",
                allow_empty=True,
            )
    files["qualified_manifest.json"] = canonical_json_bytes(qualified_manifest)
    target = Path(qualified_root) / candidate_sha
    status = _write_directory(target, files)
    verified = verify_qualified_bundle(target)
    if verified["qualification_receipt_sha256"] != receipt["receipt_sha256"] or verified[
        "shadow_bundle_sha256"
    ] != {
        "baseline": shadow["baseline"]["bundle_sha256"],
        "treatment": shadow["treatment"]["bundle_sha256"],
    }:
        _fail(
            "QUALIFIED_SET_CONFLICT",
            "candidate already has a different qualified shadow pair",
        )
    return {
        "status": status,
        "candidate_sha256": candidate_sha,
        "qualified_directory": str(target.resolve()),
        "qualified_bundle_sha256": verified["qualified_bundle_sha256"],
        "qualification_receipt_sha256": verified["qualification_receipt_sha256"],
        "live_activation_allowed": False,
    }


def verify_qualified_bundle(qualified_dir: Path) -> dict[str, object]:
    """Recompute the qualification before accepting a cold-set member."""

    root = Path(qualified_dir)
    manifest, _ = _read_json(root / "qualified_manifest.json", "qualified manifest")
    qualified_sha = _verify_seal(manifest, "qualified_bundle_sha256")
    if (
        manifest.get("schema_version") != QUALIFIED_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
    ):
        _fail("BUNDLE_POLICY_INVALID", "qualified member is not cold and non-authoritative")
    candidate_sha = str(manifest.get("candidate_sha256") or "")
    bundle = verify_candidate_bundle(root / "candidate" / candidate_sha)
    if (
        bundle["candidate_sha256"] != candidate_sha
        or bundle["bundle_sha256"] != manifest.get("candidate_bundle_sha256")
        or root.name != candidate_sha
    ):
        _fail("CANDIDATE_MISMATCH", "qualified member contains another candidate")
    outputs = manifest.get("sealed_outputs")
    if not isinstance(outputs, Mapping):
        _fail("SEALED_OUTPUT_MISMATCH", "sealed output bindings are missing")
    values: dict[str, dict[str, Any]] = {}
    for name in ("baseline", "treatment", "receipt"):
        binding = outputs.get(name)
        if not isinstance(binding, Mapping):
            _fail("SEALED_OUTPUT_MISMATCH", f"{name} binding is missing")
        raw = _bound_file(root, binding, name)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TasteCorpusError("SEALED_OUTPUT_MISMATCH", f"{name} is invalid") from exc
        if not isinstance(value, Mapping):
            _fail("SEALED_OUTPUT_MISMATCH", f"{name} is not an object")
        values[name] = dict(value)
    candidate = bundle["candidate"]
    try:
        baseline = validate_sealed_taste_outcome(
            values["baseline"], candidate=candidate, expected_arm="baseline"
        )
        treatment = validate_sealed_taste_outcome(
            values["treatment"], candidate=candidate, expected_arm="treatment"
        )
        receipt = validate_taste_qualification_receipt(
            values["receipt"],
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=treatment,
        )
    except TasteQualificationError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc
    if (
        outputs["baseline"].get("logical_sha256") != baseline["outcome_sha256"]
        or outputs["treatment"].get("logical_sha256") != treatment["outcome_sha256"]
        or outputs["receipt"].get("logical_sha256") != receipt["receipt_sha256"]
    ):
        _fail("SEALED_OUTPUT_MISMATCH", "sealed logical identities drifted")
    shadow_manifest = manifest.get("shadow_outcomes")
    if not isinstance(shadow_manifest, Mapping) or set(shadow_manifest) != {
        "baseline",
        "treatment",
    }:
        _fail("SHADOW_EVIDENCE_MISSING", "qualified member lacks exact shadow evidence")
    from services.agent_runtime.taste_shadow_runner import (
        TasteShadowRunnerError,
        verify_shadow_outcome_bundle,
    )

    verified_shadow: dict[str, dict[str, object]] = {}
    try:
        for arm in ("baseline", "treatment"):
            binding = shadow_manifest[arm]
            if not isinstance(binding, Mapping):
                _fail("SHADOW_EVIDENCE_MISMATCH", f"{arm} shadow binding is invalid")
            relative = binding.get("relative_path")
            if relative != f"shadow/{arm}":
                _fail("SHADOW_EVIDENCE_MISMATCH", f"{arm} shadow path drifted")
            verified_shadow[arm] = verify_shadow_outcome_bundle(
                root / str(relative), candidate_dir=root / "candidate" / candidate_sha
            )
            if (
                verified_shadow[arm]["bundle_sha256"] != binding.get("bundle_sha256")
                or verified_shadow[arm]["outcome"]["outcome_sha256"]
                != binding.get("outcome_sha256")
                or verified_shadow[arm]["consumer_session_identity"]
                != binding.get("consumer_session_identity")
                or verified_shadow[arm]["outcome"] != values[arm]
            ):
                _fail("SHADOW_EVIDENCE_MISMATCH", f"{arm} shadow evidence drifted")
    except TasteShadowRunnerError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc
    if (
        verified_shadow["baseline"]["consumer_session_identity"]
        == verified_shadow["treatment"]["consumer_session_identity"]
        or verified_shadow["baseline"]["process_id"] == verified_shadow["treatment"]["process_id"]
        or verified_shadow["baseline"]["same_inputs"] != verified_shadow["treatment"]["same_inputs"]
        or verified_shadow["baseline"]["condition_sha256"]
        == verified_shadow["treatment"]["condition_sha256"]
    ):
        _fail("SHADOW_EVIDENCE_MISMATCH", "qualified member reused one shadow session")
    return {
        "candidate_sha256": candidate_sha,
        "qualified_bundle_sha256": qualified_sha,
        "qualification_receipt_sha256": receipt["receipt_sha256"],
        "shadow_bundle_sha256": {
            arm: verified_shadow[arm]["bundle_sha256"] for arm in ("baseline", "treatment")
        },
        "live_activation_allowed": False,
    }
