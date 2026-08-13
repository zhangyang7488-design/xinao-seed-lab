"""Non-leaking cold corpus bridge for dynamic Taste qualification.

Explicit source correction episodes are projected mechanically into treatment
bytes.  Separate held-out episodes keep their correction/desired oracle and
scorer offline.  Only a recomputable source -> evaluation -> plan -> pair ->
score chain may enter the cold qualified set; this module never activates it.
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
)

SOURCE_BUNDLE_SCHEMA = "s.taste_source_bundle.v1"
EVALUATION_BUNDLE_SCHEMA = "s.taste_evaluation_bundle.v1"
QUALIFICATION_PLAN_SCHEMA = "s.taste_qualification_plan.v1"
SOURCE_PROJECTION_SCHEMA = "s.taste_source_projection.v1"
EVALUATION_REQUEST_SCHEMA = "s.taste_shadow_request.v2"
EVALUATION_ORACLE_SCHEMA = "s.taste_evaluation_oracle.v1"
NONLEAKING_QUALIFIED_BUNDLE_SCHEMA = "s.taste_qualified_chain.v1"

_EVENT_ID_RE = re.compile(r"^evt_[0-9a-f]{64}$")
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


def _assert_exact_files(root: Path, expected: set[str], field: str) -> None:
    observed: set[str] = set()
    for path in Path(root).rglob("*"):
        if path.is_symlink():
            _fail("BUNDLE_PATH_INVALID", f"{field} contains a link")
        if path.is_dir():
            continue
        if not path.is_file():
            _fail("BUNDLE_PATH_INVALID", f"{field} contains a non-regular file")
        observed.add(path.relative_to(root).as_posix())
    if observed != expected:
        _fail("BUNDLE_FILE_SET_MISMATCH", f"{field} contains undeclared or missing files")


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


def _episode_snapshot(
    *,
    context_root: Path,
    prefix_event_ids: Sequence[str],
    bad_continuation_event_id: str,
    correction_event_ids: Sequence[str],
    desired_continuation_event_id: str,
    carrier_homes: Mapping[str, Path | str] | None,
    session_rollout_paths: Mapping[str, Path | str] | None,
) -> dict[str, Any]:
    if isinstance(prefix_event_ids, (str, bytes)) or not prefix_event_ids:
        _fail("EVENT_IDS_MISSING", "prefix event IDs must be explicit and non-empty")
    if isinstance(correction_event_ids, (str, bytes)):
        _fail("CORRECTION_MISSING", "correction event IDs must be an explicit sequence")
    prefix_ids = [_event_id(item) for item in prefix_event_ids]
    bad_id = _event_id(bad_continuation_event_id)
    correction_ids = [_event_id(item) for item in correction_event_ids]
    desired_id = _event_id(desired_continuation_event_id)
    event_ids = [*prefix_ids, bad_id, *correction_ids, desired_id]
    if len(event_ids) != len(set(event_ids)):
        _fail("EVENT_IDS_DUPLICATE", "episode event IDs must be distinct")

    try:
        context_fabric.verify_event_chain(Path(context_root))
    except (OSError, context_fabric.ContextFabricError) as exc:
        raise TasteCorpusError(
            "CONTEXT_CHAIN_INVALID", "Context event chain failed verification"
        ) from exc
    homes = _carrier_homes(carrier_homes)
    rollout_paths = {
        str(session): Path(path) for session, path in (session_rollout_paths or {}).items()
    }
    bindings: list[dict[str, object]] = []
    blobs: list[bytes] = []
    records: list[bytes] = []
    for event_id in event_ids:
        binding, raw, record = _load_source(
            event_id,
            context_root=Path(context_root),
            homes=homes,
            session_rollouts=rollout_paths,
        )
        bindings.append(binding)
        blobs.append(raw)
        records.append(record)
    episode = _episode_contract(
        prefix_ids=prefix_ids,
        bad_id=bad_id,
        correction_ids=correction_ids,
        desired_id=desired_id,
        bindings=bindings,
    )
    return {
        "event_ids": event_ids,
        "prefix_count": len(prefix_ids),
        "correction_count": len(correction_ids),
        "bindings": bindings,
        "blobs": blobs,
        "records": records,
        "episode": episode,
    }


def _episode_files(snapshot: Mapping[str, object]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for event_id, blob, record in zip(
        snapshot["event_ids"], snapshot["blobs"], snapshot["records"], strict=True
    ):
        files[f"sources/{event_id}.utf8"] = blob
        files[f"sources/{event_id}.rollout.jsonl"] = record
    return files


def _source_projection(snapshot: Mapping[str, object]) -> dict[str, object]:
    prefix_count = int(snapshot["prefix_count"])
    correction_count = int(snapshot["correction_count"])
    bindings = snapshot["bindings"]
    blobs = snapshot["blobs"]
    assert isinstance(bindings, list) and isinstance(blobs, list)

    def message(index: int) -> dict[str, object]:
        binding = bindings[index]
        assert isinstance(binding, Mapping)
        return {
            "event_id": binding["event_id"],
            "role": binding["speaker"],
            "content": blobs[index].decode("utf-8"),
        }

    correction_start = prefix_count + 1
    return {
        "schema_version": SOURCE_PROJECTION_SCHEMA,
        "mode": "source_contrastive_episode",
        "episodes": [
            {
                "prefix": [message(index) for index in range(prefix_count)],
                "bad_continuation": message(prefix_count),
                "human_corrections": [
                    message(index)
                    for index in range(correction_start, correction_start + correction_count)
                ],
                "desired_continuation": message(len(blobs) - 1),
            }
        ],
    }


def _evaluation_request(snapshot: Mapping[str, object]) -> dict[str, object]:
    prefix_count = int(snapshot["prefix_count"])
    bindings = snapshot["bindings"]
    blobs = snapshot["blobs"]
    assert isinstance(bindings, list) and isinstance(blobs, list)
    messages = []
    for index in range(prefix_count):
        binding = bindings[index]
        assert isinstance(binding, Mapping)
        messages.append({"role": binding["speaker"], "content": blobs[index].decode("utf-8")})
    return {
        "schema_version": EVALUATION_REQUEST_SCHEMA,
        "messages": messages,
        "prefix_sha256": _sha(canonical_json_bytes(messages)),
    }


def _evaluation_oracle(snapshot: Mapping[str, object]) -> dict[str, object]:
    prefix_count = int(snapshot["prefix_count"])
    correction_count = int(snapshot["correction_count"])
    bindings = snapshot["bindings"]
    blobs = snapshot["blobs"]
    assert isinstance(bindings, list) and isinstance(blobs, list)

    def row(index: int) -> dict[str, object]:
        binding = bindings[index]
        assert isinstance(binding, Mapping)
        return {
            "event_id": binding["event_id"],
            "byte_sha256": binding["byte_sha256"],
            "text": blobs[index].decode("utf-8"),
        }

    correction_start = prefix_count + 1
    return {
        "schema_version": EVALUATION_ORACLE_SCHEMA,
        "mode": "offline_only",
        "available_to_consumers": False,
        "bad_continuation": row(prefix_count),
        "human_corrections": [
            row(index) for index in range(correction_start, correction_start + correction_count)
        ],
        "desired_continuation": row(len(blobs) - 1),
    }


def _binding(relative_path: str, raw: bytes) -> dict[str, object]:
    return {
        "relative_path": relative_path,
        "byte_sha256": _sha(raw),
        "byte_length": len(raw),
    }


def build_cold_taste_source(
    *,
    context_root: Path,
    corpus_root: Path,
    prefix_event_ids: Sequence[str],
    bad_continuation_event_id: str,
    correction_event_ids: Sequence[str],
    desired_continuation_event_id: str,
    carrier_homes: Mapping[str, Path | str] | None = None,
    session_rollout_paths: Mapping[str, Path | str] | None = None,
) -> dict[str, object]:
    """Seal one source-only correction episode and its mechanical Taste projection."""

    snapshot = _episode_snapshot(
        context_root=context_root,
        prefix_event_ids=prefix_event_ids,
        bad_continuation_event_id=bad_continuation_event_id,
        correction_event_ids=correction_event_ids,
        desired_continuation_event_id=desired_continuation_event_id,
        carrier_homes=carrier_homes,
        session_rollout_paths=session_rollout_paths,
    )
    projection_raw = canonical_json_bytes(_source_projection(snapshot))
    manifest = _seal(
        {
            "schema_version": SOURCE_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "selection_mode": "explicit_context_event_ids_only",
            "source_event_ids": snapshot["event_ids"],
            "prefix_count": snapshot["prefix_count"],
            "correction_count": snapshot["correction_count"],
            "episode": snapshot["episode"],
            "source_bindings": snapshot["bindings"],
            "treatment_projection": _binding("projection/treatment.condition.json", projection_raw),
        },
        "source_bundle_sha256",
    )
    bundle_sha = str(manifest["source_bundle_sha256"])
    target = Path(corpus_root) / "sources" / bundle_sha
    files = {
        "manifest.json": canonical_json_bytes(manifest),
        "projection/treatment.condition.json": projection_raw,
        **_episode_files(snapshot),
    }
    status = _write_directory(target, files)
    verified = verify_source_bundle(target)
    return {
        "status": status,
        "source_bundle_sha256": verified["source_bundle_sha256"],
        "source_directory": str(target.resolve()),
        "source_event_ids": verified["source_event_ids"],
        "live_activation_allowed": False,
    }


def _verify_episode_bundle(root: Path, manifest: Mapping[str, object]) -> dict[str, object]:
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
        _fail("SOURCE_BINDING_MISMATCH", "episode source bindings are incomplete")
    blobs: list[bytes] = []
    refs: list[dict[str, object]] = []
    normalized_bindings: list[dict[str, object]] = []
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
        _verify_rollout_record(binding, record_line=record_line, surface=blob)
        blobs.append(blob)
        refs.append(_source_ref(binding))
        normalized_bindings.append(binding)
    normalized_episode = _episode_contract(
        prefix_ids=[_event_id(item) for item in episode.get("prefix_event_ids", [])],
        bad_id=_event_id(episode.get("bad_continuation_event_id")),
        correction_ids=[_event_id(item) for item in episode.get("correction_event_ids", [])],
        desired_id=_event_id(episode.get("desired_continuation_event_id")),
        bindings=normalized_bindings,
    )
    if dict(episode) != normalized_episode or normalized_episode["ordered_event_ids"] != ids:
        _fail("EPISODE_INVALID", "episode manifest differs from exact source bindings")
    return {
        "event_ids": list(ids),
        "prefix_count": prefix_count,
        "correction_count": correction_count,
        "bindings": normalized_bindings,
        "blobs": blobs,
        "refs": refs,
        "episode": normalized_episode,
    }


def verify_source_bundle(source_dir: Path) -> dict[str, object]:
    root = Path(source_dir)
    manifest, manifest_raw = _read_json(root / "manifest.json", "source manifest")
    bundle_sha = _verify_seal(manifest, "source_bundle_sha256")
    if (
        manifest.get("schema_version") != SOURCE_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("selection_mode") != "explicit_context_event_ids_only"
        or root.name != bundle_sha
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("BUNDLE_POLICY_INVALID", "source bundle is not exact, cold, and explicit")
    episode = _verify_episode_bundle(root, manifest)
    projection_binding = manifest.get("treatment_projection")
    if not isinstance(projection_binding, Mapping):
        _fail("PROJECTION_MISSING", "source treatment projection is missing")
    projection_raw = _bound_file(root, projection_binding, "source treatment projection")
    expected = canonical_json_bytes(_source_projection(episode))
    if projection_raw != expected:
        _fail("PROJECTION_MISMATCH", "treatment projection is not a mechanical source projection")
    expected_files = {"manifest.json", str(projection_binding["relative_path"])}
    for event_id in episode["event_ids"]:
        expected_files.update(
            {
                f"sources/{event_id}.utf8",
                f"sources/{event_id}.rollout.jsonl",
            }
        )
    _assert_exact_files(root, expected_files, "source bundle")
    return {
        "manifest": manifest,
        "source_bundle_sha256": bundle_sha,
        "source_event_ids": episode["event_ids"],
        "episode": episode,
        "treatment_condition": projection_raw,
    }


def build_heldout_taste_evaluation(
    *,
    context_root: Path,
    corpus_root: Path,
    prefix_event_ids: Sequence[str],
    bad_continuation_event_id: str,
    correction_event_ids: Sequence[str],
    desired_continuation_event_id: str,
    scorer_spec: Mapping[str, object],
    carrier_homes: Mapping[str, Path | str] | None = None,
    session_rollout_paths: Mapping[str, Path | str] | None = None,
) -> dict[str, object]:
    """Seal one held-out episode with consumer prefix and offline-only oracle/scorer."""

    from services.agent_runtime.taste_shadow_runner import (
        TasteShadowRunnerError,
        validate_scorer_spec,
    )

    snapshot = _episode_snapshot(
        context_root=context_root,
        prefix_event_ids=prefix_event_ids,
        bad_continuation_event_id=bad_continuation_event_id,
        correction_event_ids=correction_event_ids,
        desired_continuation_event_id=desired_continuation_event_id,
        carrier_homes=carrier_homes,
        session_rollout_paths=session_rollout_paths,
    )
    request_raw = canonical_json_bytes(_evaluation_request(snapshot))
    oracle_raw = canonical_json_bytes(_evaluation_oracle(snapshot))
    try:
        scorer_raw = canonical_json_bytes(validate_scorer_spec(scorer_spec))
    except TasteShadowRunnerError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc
    manifest = _seal(
        {
            "schema_version": EVALUATION_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "consumer_oracle_access": False,
            "selection_mode": "explicit_context_event_ids_only",
            "source_event_ids": snapshot["event_ids"],
            "prefix_count": snapshot["prefix_count"],
            "correction_count": snapshot["correction_count"],
            "episode": snapshot["episode"],
            "source_bindings": snapshot["bindings"],
            "consumer_request": _binding("consumer/request.json", request_raw),
            "offline_oracle": _binding("offline/oracle.json", oracle_raw),
            "offline_scorer": _binding("offline/scorer.json", scorer_raw),
        },
        "evaluation_bundle_sha256",
    )
    bundle_sha = str(manifest["evaluation_bundle_sha256"])
    target = Path(corpus_root) / "evaluations" / bundle_sha
    files = {
        "manifest.json": canonical_json_bytes(manifest),
        "consumer/request.json": request_raw,
        "offline/oracle.json": oracle_raw,
        "offline/scorer.json": scorer_raw,
        **_episode_files(snapshot),
    }
    status = _write_directory(target, files)
    verified = verify_evaluation_bundle(target)
    return {
        "status": status,
        "evaluation_bundle_sha256": verified["evaluation_bundle_sha256"],
        "evaluation_directory": str(target.resolve()),
        "evaluation_event_ids": verified["evaluation_event_ids"],
        "live_activation_allowed": False,
    }


def verify_evaluation_bundle(evaluation_dir: Path) -> dict[str, object]:
    from services.agent_runtime.taste_shadow_runner import (
        TasteShadowRunnerError,
        validate_scorer_spec,
    )

    root = Path(evaluation_dir)
    manifest, manifest_raw = _read_json(root / "manifest.json", "evaluation manifest")
    bundle_sha = _verify_seal(manifest, "evaluation_bundle_sha256")
    if (
        manifest.get("schema_version") != EVALUATION_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("consumer_oracle_access") is not False
        or manifest.get("selection_mode") != "explicit_context_event_ids_only"
        or root.name != bundle_sha
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("BUNDLE_POLICY_INVALID", "evaluation bundle is not exact, cold, and offline-only")
    episode = _verify_episode_bundle(root, manifest)
    request_binding = manifest.get("consumer_request")
    oracle_binding = manifest.get("offline_oracle")
    scorer_binding = manifest.get("offline_scorer")
    if not all(
        isinstance(item, Mapping) for item in (request_binding, oracle_binding, scorer_binding)
    ):
        _fail("EVALUATION_BINDING_MISSING", "evaluation request/oracle/scorer bindings are missing")
    assert isinstance(request_binding, Mapping)
    assert isinstance(oracle_binding, Mapping)
    assert isinstance(scorer_binding, Mapping)
    request_raw = _bound_file(root, request_binding, "evaluation consumer request")
    oracle_raw = _bound_file(root, oracle_binding, "evaluation offline oracle")
    scorer_raw = _bound_file(root, scorer_binding, "evaluation offline scorer")
    if request_raw != canonical_json_bytes(_evaluation_request(episode)):
        _fail("REQUEST_MISMATCH", "consumer request is not exactly the held-out prefix")
    if oracle_raw != canonical_json_bytes(_evaluation_oracle(episode)):
        _fail("ORACLE_MISMATCH", "offline oracle differs from held-out source bytes")
    try:
        scorer_value = json.loads(scorer_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TasteCorpusError("SCORER_INVALID", "offline scorer is invalid JSON") from exc
    if not isinstance(scorer_value, Mapping):
        _fail("SCORER_INVALID", "offline scorer must be an object")
    try:
        scorer = validate_scorer_spec(scorer_value)
    except TasteShadowRunnerError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc
    if scorer_raw != canonical_json_bytes(scorer):
        _fail("SCORER_INVALID", "offline scorer is not canonical")
    expected_files = {
        "manifest.json",
        str(request_binding["relative_path"]),
        str(oracle_binding["relative_path"]),
        str(scorer_binding["relative_path"]),
    }
    for event_id in episode["event_ids"]:
        expected_files.update(
            {
                f"sources/{event_id}.utf8",
                f"sources/{event_id}.rollout.jsonl",
            }
        )
    _assert_exact_files(root, expected_files, "evaluation bundle")
    return {
        "manifest": manifest,
        "evaluation_bundle_sha256": bundle_sha,
        "evaluation_event_ids": episode["event_ids"],
        "episode": episode,
        "consumer_request": request_raw,
        "offline_oracle": oracle_raw,
        "oracle": _evaluation_oracle(episode),
        "scorer": scorer,
        "scorer_raw": scorer_raw,
    }


def _baseline_condition() -> bytes:
    return canonical_json_bytes(
        {"schema_version": SOURCE_PROJECTION_SCHEMA, "mode": "baseline_none", "episodes": []}
    )


def _oracle_text_bytes(evaluation: Mapping[str, object]) -> list[bytes]:
    oracle = evaluation["oracle"]
    assert isinstance(oracle, Mapping)
    rows = [
        oracle["bad_continuation"],
        *oracle["human_corrections"],
        oracle["desired_continuation"],
    ]
    result: list[bytes] = []
    for row in rows:
        assert isinstance(row, Mapping)
        result.append(str(row["text"]).encode("utf-8"))
    return result


def _assert_nonleaking_projection(
    *, treatment: bytes, baseline: bytes, evaluation: Mapping[str, object]
) -> None:
    for oracle_raw in _oracle_text_bytes(evaluation):
        if oracle_raw in treatment or oracle_raw in baseline:
            _fail(
                "EVALUATION_ORACLE_LEAK",
                "held-out bad/correction/desired bytes appear in a model-visible condition",
            )


def _assert_source_evaluation_independence(
    source: Mapping[str, object], evaluation: Mapping[str, object]
) -> dict[str, object]:
    source_episode = source["episode"]
    evaluation_episode = evaluation["episode"]
    assert isinstance(source_episode, Mapping) and isinstance(evaluation_episode, Mapping)
    source_ids = set(source_episode["event_ids"])
    evaluation_ids = set(evaluation_episode["event_ids"])
    if source_ids & evaluation_ids:
        _fail("EPISODE_OVERLAP", "source and held-out evaluation reuse Context events")
    source_bindings = source_episode["bindings"]
    evaluation_bindings = evaluation_episode["bindings"]
    assert isinstance(source_bindings, list) and isinstance(evaluation_bindings, list)
    source_records = {str(item["rollout_record_file_sha256"]) for item in source_bindings}
    evaluation_records = {str(item["rollout_record_file_sha256"]) for item in evaluation_bindings}
    if source_records & evaluation_records:
        _fail("ROLLOUT_OVERLAP", "source and held-out evaluation reuse exact rollout records")
    same_session = (
        source_episode["episode"]["carrier_id"] == evaluation_episode["episode"]["carrier_id"]
        and source_episode["episode"]["session_id"] == evaluation_episode["episode"]["session_id"]
    )
    if same_session:
        source_ordinals = source_episode["episode"]["ordered_rollout_ordinals"]
        evaluation_ordinals = evaluation_episode["episode"]["ordered_rollout_ordinals"]
        source_seqs = source_episode["episode"]["ordered_context_seqs"]
        evaluation_seqs = evaluation_episode["episode"]["ordered_context_seqs"]
        if max(source_ordinals) >= min(evaluation_ordinals) or max(source_seqs) >= min(
            evaluation_seqs
        ):
            _fail(
                "HELDOUT_ORDER_INVALID",
                "same-session source must end before held-out Context and rollout time",
            )
    return {
        "event_ids_disjoint": True,
        "rollout_records_disjoint": True,
        "independence_class": "same_session_later_episode" if same_session else "cross_session",
        "source_max_ordinal": max(source_episode["episode"]["ordered_rollout_ordinals"]),
        "evaluation_min_ordinal": min(evaluation_episode["episode"]["ordered_rollout_ordinals"]),
        "source_max_context_seq": max(source_episode["episode"]["ordered_context_seqs"]),
        "evaluation_min_context_seq": min(evaluation_episode["episode"]["ordered_context_seqs"]),
    }


def _build_offline_candidate(
    *,
    evaluation: Mapping[str, object],
    baseline_condition: bytes,
    treatment_condition: bytes,
    model_identity: str,
    body_identity: str,
    config_identity: str,
) -> dict[str, object]:
    episode = evaluation["episode"]
    assert isinstance(episode, Mapping)
    prefix_count = int(episode["prefix_count"])
    refs = episode["refs"]
    blobs = episode["blobs"]
    assert isinstance(refs, list) and isinstance(blobs, list)
    bad_index = prefix_count
    desired_index = len(blobs) - 1
    try:
        return build_taste_candidate(
            baseline_prefix=refs[:prefix_count],
            treatment_prefix=[dict(item) for item in refs[:prefix_count]],
            bad_continuation={
                "text": blobs[bad_index].decode("utf-8"),
                "source": refs[bad_index],
            },
            desired_continuation={
                "text": blobs[desired_index].decode("utf-8"),
                "source": refs[desired_index],
            },
            model_identity=model_identity,
            body_identity=body_identity,
            config_identity=config_identity,
            baseline_condition_sha256=_sha(baseline_condition),
            treatment_condition_sha256=_sha(treatment_condition),
        )
    except TasteQualificationError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc


def build_taste_qualification_plan(
    *,
    source_dir: Path,
    evaluation_dir: Path,
    plan_root: Path,
    model_identity: str,
    body_identity: str,
    config_identity: str,
) -> dict[str, object]:
    """Join source and held-out evaluation without accepting caller-supplied conditions."""

    if not model_identity or not all(
        isinstance(item, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", item)
        for item in (body_identity, config_identity)
    ):
        _fail("IDENTITY_INVALID", "model/body/config identities must be exact and byte-bound")
    source = verify_source_bundle(source_dir)
    evaluation = verify_evaluation_bundle(evaluation_dir)
    independence = _assert_source_evaluation_independence(source, evaluation)
    baseline = _baseline_condition()
    treatment = source["treatment_condition"]
    assert isinstance(treatment, bytes)
    _assert_nonleaking_projection(treatment=treatment, baseline=baseline, evaluation=evaluation)
    candidate = _build_offline_candidate(
        evaluation=evaluation,
        baseline_condition=baseline,
        treatment_condition=treatment,
        model_identity=model_identity,
        body_identity=body_identity,
        config_identity=config_identity,
    )
    candidate_raw = canonical_json_bytes(candidate)
    manifest = _seal(
        {
            "schema_version": QUALIFICATION_PLAN_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "source_bundle_sha256": source["source_bundle_sha256"],
            "evaluation_bundle_sha256": evaluation["evaluation_bundle_sha256"],
            "evaluation_request_sha256": _sha(evaluation["consumer_request"]),
            "candidate_sha256": candidate["candidate_sha256"],
            "identities": {
                "model": model_identity,
                "body": body_identity,
                "config": config_identity,
            },
            "conditions": {
                "baseline": _binding("conditions/baseline.condition.json", baseline),
                "treatment": _binding("conditions/treatment.condition.json", treatment),
            },
            "offline_candidate": _binding("offline/candidate.json", candidate_raw),
            "independence": independence,
            "consumer_visibility": {
                "request": "evaluation_prefix_only",
                "conditions": "baseline_none_or_source_projection_only",
                "oracle": False,
                "scorer": False,
            },
        },
        "plan_bundle_sha256",
    )
    plan_sha = str(manifest["plan_bundle_sha256"])
    target = Path(plan_root) / plan_sha
    files = {
        "manifest.json": canonical_json_bytes(manifest),
        "conditions/baseline.condition.json": baseline,
        "conditions/treatment.condition.json": treatment,
        "offline/candidate.json": candidate_raw,
    }
    status = _write_directory(target, files)
    verified = verify_qualification_plan(
        target, source_dir=Path(source_dir), evaluation_dir=Path(evaluation_dir)
    )
    return {
        "status": status,
        "plan_bundle_sha256": verified["plan_bundle_sha256"],
        "candidate_sha256": verified["candidate"]["candidate_sha256"],
        "plan_directory": str(target.resolve()),
        "live_activation_allowed": False,
    }


def verify_qualification_plan(
    plan_dir: Path, *, source_dir: Path, evaluation_dir: Path
) -> dict[str, object]:
    root = Path(plan_dir)
    manifest, manifest_raw = _read_json(root / "manifest.json", "qualification plan")
    plan_sha = _verify_seal(manifest, "plan_bundle_sha256")
    if (
        manifest.get("schema_version") != QUALIFICATION_PLAN_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or root.name != plan_sha
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("BUNDLE_POLICY_INVALID", "qualification plan is not exact and cold")
    source = verify_source_bundle(source_dir)
    evaluation = verify_evaluation_bundle(evaluation_dir)
    if (
        manifest.get("source_bundle_sha256") != source["source_bundle_sha256"]
        or manifest.get("evaluation_bundle_sha256") != evaluation["evaluation_bundle_sha256"]
        or manifest.get("evaluation_request_sha256") != _sha(evaluation["consumer_request"])
    ):
        _fail("PLAN_CHAIN_MISMATCH", "plan source/evaluation chain drifted")
    independence = _assert_source_evaluation_independence(source, evaluation)
    if manifest.get("independence") != independence:
        _fail("PLAN_CHAIN_MISMATCH", "plan independence receipt drifted")
    conditions = manifest.get("conditions")
    if not isinstance(conditions, Mapping):
        _fail("CONDITION_MISMATCH", "plan condition bindings are missing")
    baseline_binding = conditions.get("baseline")
    treatment_binding = conditions.get("treatment")
    if not isinstance(baseline_binding, Mapping) or not isinstance(treatment_binding, Mapping):
        _fail("CONDITION_MISMATCH", "plan condition bindings are invalid")
    baseline = _bound_file(root, baseline_binding, "baseline condition")
    treatment = _bound_file(root, treatment_binding, "treatment condition")
    if baseline != _baseline_condition() or treatment != source["treatment_condition"]:
        _fail("CONDITION_MISMATCH", "conditions are not canonical source-only projections")
    _assert_nonleaking_projection(treatment=treatment, baseline=baseline, evaluation=evaluation)
    identities = manifest.get("identities")
    if not isinstance(identities, Mapping) or set(identities) != {"model", "body", "config"}:
        _fail("IDENTITY_INVALID", "plan identities are incomplete")
    candidate = _build_offline_candidate(
        evaluation=evaluation,
        baseline_condition=baseline,
        treatment_condition=treatment,
        model_identity=str(identities["model"]),
        body_identity=str(identities["body"]),
        config_identity=str(identities["config"]),
    )
    candidate_binding = manifest.get("offline_candidate")
    if not isinstance(candidate_binding, Mapping):
        _fail("CANDIDATE_MISMATCH", "offline candidate binding is missing")
    candidate_raw = _bound_file(root, candidate_binding, "offline candidate")
    if (
        candidate_raw != canonical_json_bytes(candidate)
        or manifest.get("candidate_sha256") != candidate["candidate_sha256"]
    ):
        _fail("CANDIDATE_MISMATCH", "offline candidate differs from the verified chain")
    visibility = manifest.get("consumer_visibility")
    if visibility != {
        "request": "evaluation_prefix_only",
        "conditions": "baseline_none_or_source_projection_only",
        "oracle": False,
        "scorer": False,
    }:
        _fail("VISIBILITY_POLICY_INVALID", "plan consumer visibility drifted")
    _assert_exact_files(
        root,
        {
            "manifest.json",
            str(baseline_binding["relative_path"]),
            str(treatment_binding["relative_path"]),
            str(candidate_binding["relative_path"]),
        },
        "qualification plan",
    )
    return {
        "manifest": manifest,
        "plan_bundle_sha256": plan_sha,
        "source": source,
        "evaluation": evaluation,
        "candidate": candidate,
        "conditions": {"baseline": baseline, "treatment": treatment},
        "request": evaluation["consumer_request"],
    }


def _copy_tree_files(source: Path, prefix: str, files: dict[str, bytes]) -> None:
    source = Path(source)
    for path in source.rglob("*"):
        if path.is_symlink():
            _fail("BUNDLE_PATH_INVALID", f"{prefix} contains a link")
        if path.is_dir():
            continue
        relative = path.relative_to(source).as_posix()
        files[f"{prefix}/{relative}"] = _read_file(
            path,
            limit=_MAX_JSON_BYTES,
            field=f"{prefix}/{relative}",
            allow_empty=True,
        )


def promote_qualified_taste_candidate(
    *,
    source_dir: Path,
    evaluation_dir: Path,
    plan_dir: Path,
    pair_dir: Path,
    score_dir: Path,
    qualified_root: Path,
) -> dict[str, object]:
    """Admit only a fully recomputable non-leaking chain to the cold set."""

    from services.agent_runtime.taste_shadow_runner import (
        TasteShadowRunnerError,
        verify_shadow_pair,
        verify_shadow_score_bundle,
    )

    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    try:
        pair = verify_shadow_pair(
            pair_dir,
            plan_dir=plan_dir,
            source_dir=source_dir,
            evaluation_dir=evaluation_dir,
        )
        score = verify_shadow_score_bundle(
            score_dir,
            pair_dir=pair_dir,
            plan_dir=plan_dir,
            source_dir=source_dir,
            evaluation_dir=evaluation_dir,
        )
    except TasteShadowRunnerError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc
    candidate_sha = str(plan["candidate"]["candidate_sha256"])
    chain = {
        "source_bundle_sha256": plan["source"]["source_bundle_sha256"],
        "evaluation_bundle_sha256": plan["evaluation"]["evaluation_bundle_sha256"],
        "plan_bundle_sha256": plan["plan_bundle_sha256"],
        "pair_bundle_sha256": pair["pair_bundle_sha256"],
        "pair_id": pair["pair_id"],
        "score_bundle_sha256": score["score_bundle_sha256"],
        "score_id": score["score_id"],
        "candidate_sha256": candidate_sha,
        "qualification_receipt_sha256": score["qualification_receipt_sha256"],
    }
    roots = {
        "source": f"chain/source/{chain['source_bundle_sha256']}",
        "evaluation": f"chain/evaluation/{chain['evaluation_bundle_sha256']}",
        "plan": f"chain/plan/{chain['plan_bundle_sha256']}",
        "pair": f"chain/pair/{chain['pair_id']}",
        "score": f"chain/score/{chain['score_id']}",
    }
    manifest = _seal(
        {
            "schema_version": NONLEAKING_QUALIFIED_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "chain": chain,
            "roots": roots,
        },
        "qualified_bundle_sha256",
    )
    files: dict[str, bytes] = {"qualified_manifest.json": canonical_json_bytes(manifest)}
    for name, directory in (
        ("source", source_dir),
        ("evaluation", evaluation_dir),
        ("plan", plan_dir),
        ("pair", pair_dir),
        ("score", score_dir),
    ):
        _copy_tree_files(Path(directory), roots[name], files)
    target = Path(qualified_root) / candidate_sha
    status = _write_directory(target, files)
    verified = verify_qualified_bundle(target)
    if verified["chain"] != chain:
        _fail("QUALIFIED_SET_CONFLICT", "qualified member contains another evidence chain")
    return {
        "status": status,
        "candidate_sha256": candidate_sha,
        "qualified_directory": str(target.resolve()),
        "qualified_bundle_sha256": verified["qualified_bundle_sha256"],
        "qualification_receipt_sha256": verified["chain"]["qualification_receipt_sha256"],
        "live_activation_allowed": False,
    }


def verify_qualified_bundle(qualified_dir: Path) -> dict[str, object]:
    from services.agent_runtime.taste_shadow_runner import (
        TasteShadowRunnerError,
        verify_shadow_pair,
        verify_shadow_score_bundle,
    )

    root = Path(qualified_dir)
    manifest, manifest_raw = _read_json(root / "qualified_manifest.json", "qualified manifest")
    qualified_sha = _verify_seal(manifest, "qualified_bundle_sha256")
    if (
        manifest.get("schema_version") != NONLEAKING_QUALIFIED_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("BUNDLE_POLICY_INVALID", "qualified member is not exact, cold, and inert")
    roots = manifest.get("roots")
    chain = manifest.get("chain")
    if not isinstance(roots, Mapping) or not isinstance(chain, Mapping):
        _fail("QUALIFIED_CHAIN_MISSING", "qualified member lacks its evidence chain")
    expected_chain_keys = {
        "source_bundle_sha256",
        "evaluation_bundle_sha256",
        "plan_bundle_sha256",
        "pair_bundle_sha256",
        "pair_id",
        "score_bundle_sha256",
        "score_id",
        "candidate_sha256",
        "qualification_receipt_sha256",
    }
    hash_keys = expected_chain_keys - {"pair_id", "score_id"}
    if (
        set(chain) != expected_chain_keys
        or any(
            not isinstance(chain.get(key), str)
            or re.fullmatch(r"[0-9a-f]{64}", str(chain[key])) is None
            for key in hash_keys
        )
        or not isinstance(chain.get("pair_id"), str)
        or re.fullmatch(r"pair-[0-9a-f]{32}", str(chain["pair_id"])) is None
        or not isinstance(chain.get("score_id"), str)
        or re.fullmatch(r"score-[0-9a-f]{32}", str(chain["score_id"])) is None
    ):
        _fail("QUALIFIED_CHAIN_MISMATCH", "qualified chain identities are invalid")
    expected_roots = {
        "source": f"chain/source/{chain.get('source_bundle_sha256')}",
        "evaluation": f"chain/evaluation/{chain.get('evaluation_bundle_sha256')}",
        "plan": f"chain/plan/{chain.get('plan_bundle_sha256')}",
        "pair": f"chain/pair/{chain.get('pair_id')}",
        "score": f"chain/score/{chain.get('score_id')}",
    }
    if dict(roots) != expected_roots:
        _fail("QUALIFIED_CHAIN_MISMATCH", "qualified chain roots drifted")
    top_entries = {path.name for path in root.iterdir()}
    if top_entries != {"qualified_manifest.json", "chain"}:
        _fail("QUALIFIED_CHAIN_MISMATCH", "qualified root contains undeclared objects")
    chain_root = root / "chain"
    if chain_root.is_symlink() or not chain_root.is_dir():
        _fail("QUALIFIED_CHAIN_MISMATCH", "qualified chain root is invalid")
    if {path.name for path in chain_root.iterdir()} != set(expected_roots):
        _fail("QUALIFIED_CHAIN_MISMATCH", "qualified chain categories drifted")
    for category, relative in expected_roots.items():
        category_root = chain_root / category
        target_root = root / relative
        if (
            category_root.is_symlink()
            or not category_root.is_dir()
            or target_root.is_symlink()
            or not target_root.is_dir()
            or list(category_root.iterdir()) != [target_root]
        ):
            _fail("QUALIFIED_CHAIN_MISMATCH", f"qualified {category} carrier drifted")
    source_dir = root / expected_roots["source"]
    evaluation_dir = root / expected_roots["evaluation"]
    plan_dir = root / expected_roots["plan"]
    pair_dir = root / expected_roots["pair"]
    score_dir = root / expected_roots["score"]
    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    try:
        pair = verify_shadow_pair(
            pair_dir,
            plan_dir=plan_dir,
            source_dir=source_dir,
            evaluation_dir=evaluation_dir,
        )
        score = verify_shadow_score_bundle(
            score_dir,
            pair_dir=pair_dir,
            plan_dir=plan_dir,
            source_dir=source_dir,
            evaluation_dir=evaluation_dir,
        )
    except TasteShadowRunnerError as exc:
        raise TasteCorpusError(exc.reason_code, str(exc)) from exc
    observed_chain = {
        "source_bundle_sha256": plan["source"]["source_bundle_sha256"],
        "evaluation_bundle_sha256": plan["evaluation"]["evaluation_bundle_sha256"],
        "plan_bundle_sha256": plan["plan_bundle_sha256"],
        "pair_bundle_sha256": pair["pair_bundle_sha256"],
        "pair_id": pair["pair_id"],
        "score_bundle_sha256": score["score_bundle_sha256"],
        "score_id": score["score_id"],
        "candidate_sha256": plan["candidate"]["candidate_sha256"],
        "qualification_receipt_sha256": score["qualification_receipt_sha256"],
    }
    if dict(chain) != observed_chain or root.name != observed_chain["candidate_sha256"]:
        _fail("QUALIFIED_CHAIN_MISMATCH", "qualified evidence chain does not recompute")
    return {
        "qualified_bundle_sha256": qualified_sha,
        "chain": observed_chain,
        "live_activation_allowed": False,
    }
