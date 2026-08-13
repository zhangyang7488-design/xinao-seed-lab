from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import services.agent_runtime.codex_situation_hook as hook_module
import services.agent_runtime.context_fabric as context_runtime
from services.agent_runtime.current_situation import build_snapshot, initialize_store

SESSION_A = "019ff75c-703c-7972-96cd-b0d257b13baa"
SESSION_B = "019ff778-e326-7b91-9784-4fe809585e03"
TURN_A = "019ff75d-1749-7662-9e80-aafa605718ab"
TURN_B = "019ff75d-1749-7662-9e80-aafa605718ac"
TURN_C = "019ff75d-1749-7662-9e80-aafa605718ad"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _mount(tmp_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    home = tmp_path / ".codex"
    home.mkdir()
    return {str(home): "s-primary"}, {"CODEX_HOME": str(home)}


def _hook(
    name: str,
    *,
    session_id: str = SESSION_A,
    turn_id: str = TURN_A,
    timestamp: str = "2026-08-13T00:00:00Z",
    prompt: str = "",
    assistant: str = "",
    **extra: object,
) -> dict[str, object]:
    event: dict[str, object] = {
        "hook_event_name": name,
        "session_id": session_id,
        "turn_id": turn_id,
        "timestamp": timestamp,
        "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
        **extra,
    }
    if prompt:
        event["prompt"] = prompt
    if assistant:
        event["last_assistant_message"] = assistant
    return event


def _capture(
    event: Mapping[str, object],
    *,
    root: Path,
    allowed_homes: Mapping[str, str],
    environ: Mapping[str, str],
) -> Any:
    result = context_runtime.capture_hook_event(
        event,
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    assert result is not None
    return result


def _public_api(name: str) -> Callable[..., Any]:
    candidate = getattr(context_runtime, name, None)
    assert callable(candidate), (
        f"the completed context runtime needs a public {name}() entrypoint; "
        "a private table edit is not a recoverable S/B consumer contract"
    )
    return candidate


def _admit_sanitized_exact(content: bytes, *, root: Path, source: str) -> Mapping[str, object]:
    """Exercise the narrow explicit path that is allowed to create a CAS blob."""

    return _public_api("admit_artifact")(
        content,
        kind="completed_tool_result",
        media_type="text/plain",
        source_locator=source,
        source_record_sha256=_sha256_text(source),
        storage_policy="exact",
        sanitized=True,
        producer_id="s.context_runtime.explicit_sanitizer",
        producer_version="v1",
        root=root,
    )


def _materialized_payload(rendered: str) -> dict[str, object]:
    lines = rendered.splitlines()
    assert len(lines) >= 2
    payload = json.loads(lines[1])
    assert isinstance(payload, dict)
    return payload


def _projection_ids(result: Mapping[str, object]) -> list[str]:
    raw = result.get("projection_ids")
    if isinstance(raw, Mapping):
        values = list(raw.values())
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        values = list(raw)
    else:
        pytest.fail("projection producer must return its exact projection_ids")
    projection_ids = [str(value) for value in values]
    assert projection_ids
    assert all(value.startswith("prj_") for value in projection_ids)
    return projection_ids


# This is the exact first-production-slice schema, kept as an acceptance fixture
# so a future initializer cannot silently treat a newly-created database as a
# migration test.  Canonical event bytes and hashes below are deliberately
# created without importing any private runtime helper.
_LEGACY_V1_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE fabric_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    world_id TEXT NOT NULL,
    body_id TEXT NOT NULL,
    carrier_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    speaker TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    captured_at_unix_ns INTEGER NOT NULL,
    raw_text BLOB NOT NULL,
    raw_sha256 TEXT NOT NULL,
    stored_text_sha256 TEXT NOT NULL,
    raw_storage TEXT NOT NULL,
    authority_class TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    source_record_sha256 TEXT NOT NULL,
    source_key TEXT NOT NULL UNIQUE,
    metadata_json TEXT NOT NULL,
    previous_event_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX events_session_seq ON events(session_id, seq DESC);
CREATE INDEX events_kind_seq ON events(event_kind, seq DESC);
CREATE UNIQUE INDEX events_surfaced_turn_identity
ON events(carrier_id, session_id, turn_id, event_kind, raw_sha256)
WHERE event_kind IN ('user_message', 'assistant_message') AND turn_id<>'';
CREATE TABLE event_terms (
    event_id TEXT NOT NULL REFERENCES events(event_id),
    term TEXT NOT NULL,
    PRIMARY KEY(event_id, term)
) WITHOUT ROWID;
CREATE INDEX event_terms_term ON event_terms(term, event_id);
CREATE TABLE projections (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    projection_id TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    world_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    semantic_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    statement TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    temporal_scope TEXT NOT NULL,
    status_label TEXT NOT NULL,
    content_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    source_span_sha256 TEXT NOT NULL,
    supersedes_projection_id TEXT NOT NULL,
    producer TEXT NOT NULL,
    created_at_unix_ns INTEGER NOT NULL,
    authority INTEGER NOT NULL CHECK(authority = 0),
    UNIQUE(kind, semantic_key, version)
);
CREATE TABLE projection_sources (
    projection_id TEXT NOT NULL REFERENCES projections(projection_id),
    event_id TEXT NOT NULL REFERENCES events(event_id),
    source_order INTEGER NOT NULL,
    PRIMARY KEY(projection_id, event_id)
) WITHOUT ROWID;
CREATE TABLE relations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    relation_id TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    world_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    from_ref TEXT NOT NULL,
    to_ref TEXT NOT NULL,
    source_event_id TEXT NOT NULL REFERENCES events(event_id),
    temporal_scope TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at_unix_ns INTEGER NOT NULL,
    authority INTEGER NOT NULL CHECK(authority = 0)
);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER event_terms_no_update BEFORE UPDATE ON event_terms
BEGIN SELECT RAISE(ABORT, 'event terms are append-only'); END;
CREATE TRIGGER event_terms_no_delete BEFORE DELETE ON event_terms
BEGIN SELECT RAISE(ABORT, 'event terms are append-only'); END;
CREATE TRIGGER projections_no_update BEFORE UPDATE ON projections
BEGIN SELECT RAISE(ABORT, 'projections are append-only'); END;
CREATE TRIGGER projections_no_delete BEFORE DELETE ON projections
BEGIN SELECT RAISE(ABORT, 'projections are append-only'); END;
CREATE TRIGGER projection_sources_no_update BEFORE UPDATE ON projection_sources
BEGIN SELECT RAISE(ABORT, 'projection sources are append-only'); END;
CREATE TRIGGER projection_sources_no_delete BEFORE DELETE ON projection_sources
BEGIN SELECT RAISE(ABORT, 'projection sources are append-only'); END;
CREATE TRIGGER relations_no_update BEFORE UPDATE ON relations
BEGIN SELECT RAISE(ABORT, 'relations are append-only'); END;
CREATE TRIGGER relations_no_delete BEFORE DELETE ON relations
BEGIN SELECT RAISE(ABORT, 'relations are append-only'); END;
INSERT INTO fabric_meta(key, value) VALUES
    ('schema_version', 's.context_fabric.v1'),
    ('world_id', 's-engineering-interaction-world');
COMMIT;
"""


def _seed_legacy_v1(root: Path) -> dict[str, str]:
    root.mkdir()
    database = root / "context_fabric.sqlite3"
    raw_text = "迁移前已经存在的原始用户纠偏"
    raw_bytes = raw_text.encode("utf-8")
    source_key = "legacy-v1:test-source:1"
    metadata_json = "{}"
    base: dict[str, object] = {
        "schema_version": "s.context_event.v1",
        "world_id": "s-engineering-interaction-world",
        "body_id": "s-b-engineering-body",
        "carrier_id": "s-primary",
        "session_id": SESSION_A,
        "turn_id": TURN_A,
        "event_kind": "user_message",
        "speaker": "user",
        "occurred_at": "2026-08-12T23:00:00Z",
        "captured_at_unix_ns": 1_723_507_200_000_000_000,
        "raw_sha256": _sha256_bytes(raw_bytes),
        "stored_text_sha256": _sha256_bytes(raw_bytes),
        "raw_storage": "exact_utf8",
        "authority_class": "human_raw_evidence",
        "source_kind": "codex_hook",
        "source_locator": "hook:UserPromptSubmit",
        "source_record_sha256": _sha256_text("legacy source record"),
        "source_key": source_key,
        "metadata_json": metadata_json,
        "previous_event_hash": "0" * 64,
    }
    event_id = "evt_" + _sha256_text(source_key)
    event_hash = _sha256_bytes(_canonical_bytes(base))
    source_span_sha256 = _sha256_bytes(
        _canonical_bytes([{"event_id": event_id, "event_hash": event_hash}])
    )
    projection_statement = "迁移前的 derived projection 仍只是证据"
    projection_aliases = ["迁移"]
    projection_temporal_scope = "legacy fixture"
    projection_status = "current"
    projection_content = {"meaning": "legacy projection remains evidence"}
    content_json = _canonical_bytes(projection_content).decode("utf-8")
    projection_identity = {
        "kind": "semantic_identity",
        "semantic_key": "legacy-current-meaning",
        "version": 1,
        "statement": projection_statement,
        "aliases": projection_aliases,
        "temporal_scope": projection_temporal_scope,
        "status_label": projection_status,
        "content_sha256": _sha256_text(content_json),
        "source_span_sha256": source_span_sha256,
        "supersedes": "",
    }
    projection_id = "prj_" + _sha256_bytes(_canonical_bytes(projection_identity))

    with sqlite3.connect(database) as connection:
        connection.executescript(_LEGACY_V1_SCHEMA)
        columns = ["event_id", *base.keys(), "raw_text", "event_hash"]
        connection.execute(
            f"INSERT INTO events({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [event_id, *base.values(), raw_bytes, event_hash],
        )
        connection.executemany(
            "INSERT INTO event_terms(event_id,term) VALUES (?,?)",
            [(event_id, term) for term in context_runtime.lexical_terms(raw_text)],
        )
        connection.execute(
            "INSERT INTO projections("
            "projection_id,schema_version,world_id,kind,semantic_key,version,statement,"
            "aliases_json,temporal_scope,status_label,content_json,content_sha256,"
            "source_span_sha256,supersedes_projection_id,producer,created_at_unix_ns,authority"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (
                projection_id,
                "s.context_projection.v1",
                "s-engineering-interaction-world",
                "semantic_identity",
                "legacy-current-meaning",
                1,
                projection_statement,
                _canonical_bytes(projection_aliases).decode("utf-8"),
                projection_temporal_scope,
                projection_status,
                content_json,
                _sha256_text(content_json),
                source_span_sha256,
                "",
                "legacy fixture",
                1_723_507_200_000_000_001,
            ),
        )
        connection.execute(
            "INSERT INTO projection_sources(projection_id,event_id,source_order) VALUES (?,?,0)",
            (projection_id, event_id),
        )
        connection.commit()
    return {
        "event_id": event_id,
        "event_hash": event_hash,
        "projection_id": projection_id,
        "raw_text": raw_text,
    }


def _rollout_item(
    item: Mapping[str, object],
    *,
    ordinal: int,
    turn_id: str = TURN_A,
) -> dict[str, object]:
    return {
        "timestamp": f"2026-08-13T09:00:{ordinal:02d}Z",
        "ordinal": ordinal,
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "thread_id": SESSION_A,
            "turn_id": turn_id,
            "item": dict(item),
            "started_at_ms": ordinal * 1_000,
            "completed_at_ms": ordinal * 1_000 + 1,
        },
    }


def test_first_slice_store_explicit_migration_preserves_history_and_accepts_new_appends(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy-v1"
    legacy = _seed_legacy_v1(root)

    migrate = _public_api("migrate_context_fabric")
    first = migrate(root)
    first_verification = context_runtime.verify_event_chain(root)
    second = migrate(root)
    second_verification = context_runtime.verify_event_chain(root)

    assert first["authority"] is False
    assert len(str(first["backup_manifest_sha256"])) == 64
    assert Path(str(first["backup_root"])).is_dir()
    assert second["authority"] is False
    assert (
        context_runtime.read_event(legacy["event_id"], root=root)["raw_text"] == legacy["raw_text"]
    )
    assert first_verification["event_count"] == 1
    assert first_verification["tip_event_hash"] == legacy["event_hash"]
    assert second_verification == first_verification
    inventory = context_runtime.store_inventory(root)
    assert inventory["events"] == 1
    assert inventory["projections"] == 1

    allowed_homes, environ = _mount(tmp_path)
    appended = _capture(
        _hook(
            "UserPromptSubmit",
            turn_id=TURN_B,
            timestamp="2026-08-13T00:10:00Z",
            prompt="迁移后继续同一个 interaction world",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    assert appended.status == "appended"
    assert (
        context_runtime.read_event(appended.event_id, root=root)["previous_event_hash"]
        == legacy["event_hash"]
    )
    assert context_runtime.verify_event_chain(root)["event_count"] == 2


def test_explicit_migration_is_dry_runnable_idempotent_and_preserves_v1_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy-v1"
    backup_root = tmp_path / "migration-backup"
    legacy = _seed_legacy_v1(root)
    database = root / "context_fabric.sqlite3"
    before_bytes = database.read_bytes()
    before_tip = legacy["event_hash"]
    migrate = _public_api("migrate_context_fabric")

    dry_run = migrate(root, backup_root=backup_root, dry_run=True)
    assert dry_run["status"] in {"dry_run", "migration_required"}
    assert database.read_bytes() == before_bytes
    assert not backup_root.exists()

    migrated = migrate(root, backup_root=backup_root)
    assert migrated["status"] in {"migrated", "already_current"}
    assert migrated["authority"] is False
    assert (
        context_runtime.read_event(legacy["event_id"], root=root)["raw_text"] == legacy["raw_text"]
    )
    assert context_runtime.verify_event_chain(root)["tip_event_hash"] == before_tip
    assert context_runtime.store_inventory(root)["events"] == 1
    assert backup_root.is_dir()

    restored_root = tmp_path / "restored-legacy-preimage"
    restored = _public_api("restore_migration_preimage")(
        backup_root,
        restored_root,
        expected_manifest_sha256=str(migrated["backup_manifest_sha256"]),
    )
    assert restored["status"] == "restored_legacy_preimage"
    assert context_runtime.verify_event_chain(restored_root)["tip_event_hash"] == before_tip
    allowed_homes, environ = _mount(tmp_path)
    with pytest.raises(Exception, match="migrat|feature"):
        context_runtime.capture_hook_event(
            _hook("UserPromptSubmit", prompt="restored legacy remains read-only"),
            root=restored_root,
            allowed_homes=allowed_homes,
            environ=environ,
        )

    again = migrate(root)
    assert again["status"] == "already_current"
    assert context_runtime.verify_event_chain(root)["tip_event_hash"] == before_tip


def test_initializer_and_hook_do_not_implicitly_migrate_a_legacy_store(tmp_path: Path) -> None:
    root = tmp_path / "legacy-v1"
    legacy = _seed_legacy_v1(root)
    database = root / "context_fabric.sqlite3"
    before = database.read_bytes()

    # Schema lifecycle is an explicit manager operation.  A user turn must fail
    # open at the hook layer; it must never perform a surprise database rewrite.
    with pytest.raises(Exception, match="migrat|schema|version|unsupported"):
        context_runtime.initialize_context_fabric(root)
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        tip = connection.execute(
            "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    assert tip is not None and tip[0] == legacy["event_hash"]

    allowed_homes, environ = _mount(tmp_path)
    with pytest.raises(Exception, match="migrat|schema|version|unsupported"):
        context_runtime.capture_hook_event(
            _hook("UserPromptSubmit", prompt="不能让当前用户 turn 触发迁移"),
            root=root,
            allowed_homes=allowed_homes,
            environ=environ,
        )
    assert database.read_bytes() == before

    hook_result = hook_module.handle_hook_event(
        _hook("UserPromptSubmit", prompt="legacy store 不能阻塞当前用户 turn"),
        context_fabric_enabled=True,
        context_fabric_root=root,
        context_fabric_allowed_homes=allowed_homes,
        context_fabric_environ=environ,
    )
    assert hook_result["continue"] is True
    assert hook_result["hookSpecificOutput"]["additionalContext"].startswith(hook_module.L0_CONTEXT)
    assert database.read_bytes() == before


def test_automatic_projections_are_replay_idempotent_and_pin_exact_source_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    first = _capture(
        _hook(
            "UserPromptSubmit",
            timestamp="2026-08-13T00:00:00Z",
            prompt="我正在把持续上下文运行时补到真实 S/B consumer。",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    second = _capture(
        _hook(
            "Stop",
            timestamp="2026-08-13T00:01:00Z",
            assistant="先保存原始 round，再生成可重建投影。",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    produce = _public_api("run_projection_producers")

    first_run = produce(root=root, through_seq=second.seq)
    first_ids = _projection_ids(first_run)
    first_inventory = context_runtime.store_inventory(root)
    replay = produce(root=root, through_seq=second.seq)
    replay_ids = _projection_ids(replay)

    assert replay["status"] in {"duplicate", "up_to_date", "no_change"}
    assert replay_ids == first_ids
    assert context_runtime.store_inventory(root)["projections"] == first_inventory["projections"]
    assert first_run["input_tip"] == {
        "seq": second.seq,
        "event_hash": second.event_hash,
    }
    producers = first_run["producers"]
    assert isinstance(producers, Sequence) and producers
    for producer in producers:
        assert isinstance(producer, Mapping)
        assert producer["producer_id"]
        assert producer["producer_version"]
        assert len(str(producer["config_sha256"])) == 64

    rendered = context_runtime.render_materialized_context(
        query="持续上下文",
        root=root,
        session_id=SESSION_A,
        carrier_id="s-primary",
    )
    payload = _materialized_payload(rendered)
    projections = payload["derived_projections"]
    assert isinstance(projections, Sequence) and projections
    selected_ids = {str(item["projection_id"]) for item in projections}
    assert selected_ids & set(first_ids)
    for projection in projections:
        assert projection["source_event_ids"]
        assert len(str(projection["source_span_sha256"])) == 64
        assert projection["producer_id"]
        assert projection["producer_version"]


def test_hook_path_runs_trigger_scoped_structural_producers_without_full_replay(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)

    hook_module.handle_hook_event(
        _hook("UserPromptSubmit", prompt="bounded hot-path structural source"),
        context_fabric_enabled=True,
        context_fabric_root=root,
        context_fabric_allowed_homes=allowed_homes,
        context_fabric_environ=environ,
    )
    stopped = hook_module.handle_hook_event(
        _hook("Stop", assistant="bounded hot-path structural response"),
        context_fabric_enabled=True,
        context_fabric_root=root,
        context_fabric_allowed_homes=allowed_homes,
        context_fabric_environ=environ,
    )
    assert stopped == {"continue": True}
    hook_module.handle_hook_event(
        _hook("PostCompact", turn_id=TURN_B, timestamp="2026-08-13T00:03:00Z"),
        context_fabric_enabled=True,
        context_fabric_root=root,
        context_fabric_allowed_homes=allowed_homes,
        context_fabric_environ=environ,
    )

    with sqlite3.connect(root / "context_fabric.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM projections WHERE kind='local_compact'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM projections WHERE kind='activity_compact'"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM projections WHERE kind='current_materialized_seed'"
        ).fetchone() == (1,)
        runs = connection.execute(
            "SELECT trigger_event_id,input_identity_json FROM projection_runs ORDER BY seq"
        ).fetchall()
    assert len(runs) == 2
    assert all(trigger_event_id for trigger_event_id, _ in runs)
    assert all('"trigger_event_id":"evt_' in identity for _, identity in runs)


def test_current_prompt_never_reenters_through_an_automatic_projection(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    prior = _capture(
        _hook(
            "UserPromptSubmit",
            timestamp="2026-08-13T00:00:00Z",
            prompt="昨天的 durable context evidence",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    produce = _public_api("run_projection_producers")
    produce(root=root, through_seq=prior.seq)

    current_prompt = "CURRENT-PROMPT-MUST-NOT-ECHO-89f20d"
    current = _capture(
        _hook(
            "UserPromptSubmit",
            turn_id=TURN_B,
            timestamp="2026-08-13T00:02:00Z",
            prompt=current_prompt,
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    # Even if the hot-path producer is invoked after capture, materialization for
    # this turn must use the predecessor boundary or filter current-event-derived
    # projections.  Excluding only the raw row would not be enough.
    produce(root=root, trigger_event_id=current.event_id)
    materialize = _public_api("materialize_context")
    materialized = materialize(
        query=current_prompt,
        root=root,
        session_id=SESSION_A,
        carrier_id="s-primary",
        exclude_event_id=current.event_id,
        persist=False,
    )
    assert materialized["current_prompt_included"] is False
    assert current_prompt not in materialized["rendered_context"]
    assert current.event_id not in materialized["source_refs"]


def test_explicit_correction_has_temporal_current_and_historical_views(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    old_event = _capture(
        _hook(
            "UserPromptSubmit",
            timestamp="2026-08-12T20:00:00Z",
            prompt="旧理解：C 是一种研究协议。",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    old_projection = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "current-c-meaning",
            "statement": "C 是一种研究协议。",
            "aliases": ["C并发研究"],
            "temporal_scope": "before explicit user correction",
            "status_label": "historical",
            "source_event_ids": [old_event.event_id],
            "content": {"meaning": "protocol"},
        },
        root=root,
    )
    correction_event = _capture(
        _hook(
            "UserPromptSubmit",
            turn_id=TURN_B,
            timestamp="2026-08-13T01:00:00Z",
            prompt="纠正：A/C 只表示账号入口，不分配研究协议。",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    replacement = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "current-c-meaning",
            "statement": "A/C 只表示账号入口，不分配研究协议。",
            "aliases": ["C并发研究", "A/C"],
            "temporal_scope": "current runtime meaning",
            "status_label": "current",
            "source_event_ids": [correction_event.event_id],
            "supersedes_projection_id": old_projection["projection_id"],
            "content": {"meaning": "account_slot"},
        },
        root=root,
    )
    correct = _public_api("append_correction")
    spec = {
        "prior_ref": old_projection["projection_id"],
        "replacement_ref": replacement["projection_id"],
        "source_event_id": correction_event.event_id,
        "scope_key": "local-runtime:C",
        "valid_from": "2026-08-13T09:00:00+08:00",
        "temporal_basis": "explicit_user_correction",
    }
    first = correct(spec, root=root)
    duplicate = correct(spec, root=root)
    assert first["correction_id"] == duplicate["correction_id"]
    assert duplicate["status"] == "duplicate"

    materialize = _public_api("materialize_context")
    historical = materialize(
        query="C并发研究",
        root=root,
        valid_at="2026-08-12T23:00:00Z",
        persist=False,
    )
    current = materialize(
        query="C并发研究",
        root=root,
        valid_at="2026-08-13T02:00:00Z",
        persist=False,
    )
    assert old_projection["projection_id"] in historical["source_refs"]
    assert "C 是一种研究协议" in historical["rendered_context"]
    assert replacement["projection_id"] not in historical["source_refs"]
    assert replacement["projection_id"] in current["source_refs"]
    assert "只表示账号入口" in current["rendered_context"]
    assert "C 是一种研究协议" not in current["rendered_context"]
    assert current["authority"] is False
    assert current["instruction_source"] is False
    with sqlite3.connect(root / "context_fabric.sqlite3") as connection:
        assert connection.execute(
            "SELECT effective_from_at FROM relation_metadata WHERE relation_id=?",
            (first["relation_id"],),
        ).fetchone() == ("2026-08-13T01:00:00Z",)


def test_projection_valid_time_normalizes_offsets_and_rejects_naive_instants(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    source = _capture(
        _hook("UserPromptSubmit", prompt="OFFSET-VALID-PROJECTION evidence"),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    projection = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "offset-valid-projection",
            "statement": "OFFSET-VALID-PROJECTION is active after one UTC.",
            "source_event_ids": [source.event_id],
            "valid_from": "2026-08-13T09:00:00+08:00",
            "temporal_basis": "explicit_offset_instant",
        },
        root=root,
    )
    before = context_runtime.materialize_context(
        query="OFFSET-VALID-PROJECTION",
        valid_at="2026-08-13T00:59:59Z",
        root=root,
        persist=False,
    )
    after = context_runtime.materialize_context(
        query="OFFSET-VALID-PROJECTION",
        valid_at="2026-08-13T02:00:00Z",
        root=root,
        persist=False,
    )
    assert projection["projection_id"] not in before["source_refs"]
    assert projection["projection_id"] in after["source_refs"]
    with pytest.raises(context_runtime.ContextFabricError, match="timezone|ISO-8601"):
        context_runtime.append_projection(
            {
                "kind": "semantic_identity",
                "semantic_key": "naive-invalid-projection",
                "statement": "A naive valid time is ambiguous.",
                "source_event_ids": [source.event_id],
                "valid_from": "2026-08-13T01:00:00",
            },
            root=root,
        )


def test_correction_event_time_cannot_retroactively_override_earlier_as_of_view(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    old = _capture(
        _hook(
            "UserPromptSubmit",
            timestamp="2026-08-13T00:00:00Z",
            prompt="历史 scope 的定义保持可问",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    before = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "time-scoped-definition",
            "statement": "第一版定义",
            "source_event_ids": [old.event_id],
            "status_label": "historical",
            "content": {},
        },
        root=root,
    )
    correction_event = _capture(
        _hook(
            "UserPromptSubmit",
            turn_id=TURN_B,
            timestamp="2026-08-13T02:00:00Z",
            prompt="从现在起使用第二版定义",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    after = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "time-scoped-definition",
            "statement": "第二版定义",
            "source_event_ids": [correction_event.event_id],
            "status_label": "current",
            "supersedes_projection_id": before["projection_id"],
            "content": {},
        },
        root=root,
    )
    _public_api("append_correction")(
        {
            "prior_ref": before["projection_id"],
            "replacement_ref": after["projection_id"],
            "source_event_id": correction_event.event_id,
            "scope_key": "definition:test",
            "valid_from_event_id": correction_event.event_id,
            "temporal_basis": "source_event_order",
        },
        root=root,
    )
    materialized = _public_api("materialize_context")(
        query="定义",
        root=root,
        as_of_event_id=old.event_id,
        persist=False,
    )
    assert before["projection_id"] in materialized["source_refs"]
    assert after["projection_id"] not in materialized["source_refs"]
    assert "第二版定义" not in materialized["rendered_context"]


def test_compact_and_resume_lineage_records_only_observed_same_session_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    pre = _capture(
        _hook(
            "PreCompact",
            timestamp="2026-08-13T03:00:00Z",
            trigger="auto",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    post = _capture(
        _hook(
            "PostCompact",
            timestamp="2026-08-13T03:00:01Z",
            trigger="auto",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    compact_start = _capture(
        _hook(
            "SessionStart",
            turn_id="",
            timestamp="2026-08-13T03:00:02Z",
            source="compact",
            transcript_path=r"C:\Users\xx363\.codex\sessions\redacted.jsonl",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    record = _public_api("record_session_lineage")
    compact = record(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_A,
            "source": "compact",
            "transcript_locator_sha256": "a" * 64,
        },
        source_event_id=compact_start.event_id,
        predecessor_event_id=post.event_id,
        root=root,
    )
    assert compact["lineage_status"] == "resolved"
    assert compact["evidence_quality"] == "same_session_ordered"
    assert compact["session_id"] == SESSION_A
    assert compact["predecessor_event_id"] == post.event_id
    assert compact["session_id"] != SESSION_B

    resume_start = _capture(
        _hook(
            "SessionStart",
            session_id=SESSION_A,
            turn_id="",
            timestamp="2026-08-13T04:00:00Z",
            source="resume",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    resumed = record(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_A,
            "source": "resume",
            "transcript_locator_sha256": "b" * 64,
        },
        source_event_id=resume_start.event_id,
        root=root,
    )
    assert resumed["lineage_status"] == "unresolved"
    assert resumed.get("predecessor_event_id") in {None, ""}
    assert resumed.get("parent_session_id") in {None, ""}

    lineage = _public_api("read_session_lineage")(SESSION_A, root=root)
    source_events = {node["source_event_id"] for node in lineage["nodes"]}
    assert {compact_start.event_id, resume_start.event_id} <= source_events
    assert pre.event_id not in source_events


def test_fresh_session_without_explicit_parent_does_not_inherit_parallel_tui_tail(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    parallel_marker = "PARALLEL-TUI-RAW-TAIL-51df"
    _capture(
        _hook(
            "UserPromptSubmit",
            session_id=SESSION_A,
            prompt=parallel_marker,
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    startup = _capture(
        _hook(
            "SessionStart",
            session_id=SESSION_B,
            turn_id="",
            timestamp="2026-08-13T05:00:00Z",
            source="startup",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    _public_api("record_session_lineage")(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_B,
            "source": "startup",
            "transcript_locator_sha256": "c" * 64,
        },
        source_event_id=startup.event_id,
        root=root,
    )
    materialize = _public_api("materialize_context")
    neutral = materialize(
        query="继续新的窗口",
        root=root,
        session_id=SESSION_B,
        carrier_id="s-primary",
        persist=False,
    )
    assert neutral["lineage_status"] == "unresolved"
    assert parallel_marker not in neutral["rendered_context"]

    relevant = materialize(
        query=parallel_marker,
        root=root,
        session_id=SESSION_B,
        carrier_id="s-primary",
        persist=False,
    )
    assert parallel_marker in relevant["rendered_context"]
    assert relevant["retrieval_scope"] == "query_relevant_cross_session_evidence"
    assert relevant["authority"] is False


def test_artifact_admission_is_content_addressed_bounded_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    content = b'{"exit_code":0,"summary":"bounded verified result"}'
    first = _admit_sanitized_exact(
        content,
        root=root,
        source="codex:item_completed:sanitized-tool-summary-1",
    )
    duplicate = _admit_sanitized_exact(
        content,
        root=root,
        source="codex:item_completed:sanitized-tool-summary-1",
    )

    assert first["artifact_id"] == duplicate["artifact_id"]
    assert duplicate["status"] == "duplicate"
    assert first["content_sha256"] == _sha256_bytes(content)
    assert first["byte_count"] == len(content)
    assert first["storage_kind"] == "exact_blob"
    blob = root / str(first["blob_relpath"])
    assert blob.is_file()
    assert blob.read_bytes() == content
    assert _sha256_bytes(blob.read_bytes()) == first["content_sha256"]


def test_completed_tool_result_defaults_to_hash_only_without_explicit_sanitized_contract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    content = b"stdout may contain commands paths environment and arbitrary file bytes"
    receipt = _public_api("admit_artifact")(
        content,
        kind="completed_tool_result",
        media_type="text/plain",
        source_locator="codex:item_completed:ordinary-tool-result",
        source_record_sha256="d" * 64,
        root=root,
    )
    assert receipt["storage_kind"] == "hash_only"
    assert receipt["content_sha256"] == _sha256_bytes(content)
    assert receipt["byte_count"] == len(content)
    assert receipt.get("blob_relpath") in {None, ""}
    assert content not in (root / "context_fabric.sqlite3").read_bytes()


@pytest.mark.parametrize(
    ("kind", "content"),
    [
        ("tool_call", b'{"command":"Get-ChildItem","arguments":["C:/"]}'),
        ("reasoning", b"private chain of thought"),
        ("developer_wrapper", b"injected instructions"),
        ("incomplete_tool_result", b"still running"),
    ],
)
def test_unallowlisted_or_incomplete_artifact_surfaces_are_rejected(
    tmp_path: Path, kind: str, content: bytes
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    admit = _public_api("admit_artifact")
    with pytest.raises(Exception, match="admission|allow|completed|unsupported|reject"):
        admit(
            content,
            kind=kind,
            media_type="application/json",
            source_locator=f"codex:item_completed:{kind}",
            source_record_sha256="e" * 64,
            root=root,
        )


def test_secret_like_artifact_is_hash_only_and_cannot_leak_from_materialization_or_snapshot(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    secret = b"authorization: Bearer ARTIFACT_SECRET_abcdefghijklmnopqrstuvwxyz"
    receipt = _public_api("admit_artifact")(
        secret,
        kind="completed_tool_result",
        media_type="text/plain",
        source_locator="codex:item_completed:secret-tool-result",
        source_record_sha256="f" * 64,
        storage_policy="exact",
        sanitized=True,
        producer_id="s.context_runtime.explicit_sanitizer",
        producer_version="v1",
        root=root,
    )
    assert receipt["content_sha256"] == _sha256_bytes(secret)
    assert receipt["byte_count"] == len(secret)
    assert receipt["storage_kind"] == "hash_only"
    assert receipt.get("blob_relpath") in {None, ""}
    assert b"ARTIFACT_SECRET" not in (root / "context_fabric.sqlite3").read_bytes()

    rendered = _public_api("materialize_context")(
        query="authorization artifact",
        root=root,
        persist=False,
    )["rendered_context"]
    assert "ARTIFACT_SECRET" not in rendered
    snapshot = tmp_path / "snapshot"
    context_runtime.create_snapshot(snapshot, root=root)
    for path in snapshot.rglob("*"):
        if path.is_file():
            assert b"ARTIFACT_SECRET" not in path.read_bytes()


def test_context_event_binds_sorted_parent_and_artifact_ids_and_verification_detects_tamper(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    parent = _capture(
        _hook("UserPromptSubmit", prompt="parent raw event"),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    artifact_a = _admit_sanitized_exact(
        b"artifact A",
        root=root,
        source="codex:item_completed:sanitized-a",
    )
    artifact_b = _admit_sanitized_exact(
        b"artifact B",
        root=root,
        source="codex:item_completed:sanitized-b",
    )
    append = _public_api("append_context_event")
    spec = {
        "carrier_id": "s-primary",
        "session_id": SESSION_A,
        "turn_id": TURN_B,
        "event_kind": "artifact_admission",
        "speaker": "tool",
        "occurred_at": "2026-08-13T06:00:00Z",
        "raw_text": "",
        "authority_class": "mechanical_evidence",
        "source_kind": "codex_item_completed",
        "source_locator": "codex:item_completed:aggregate",
        "source_record_sha256": "3" * 64,
        "source_key": "completion-test:artifact-event",
        "metadata": {},
        "parent_event_ids": [parent.event_id],
        "artifact_ids": [artifact_b["artifact_id"], artifact_a["artifact_id"]],
    }
    event = append(spec, root=root)
    read = context_runtime.read_event(event.event_id, root=root)
    assert read["parent_event_ids"] == [parent.event_id]
    assert read["artifact_ids"] == sorted([artifact_a["artifact_id"], artifact_b["artifact_id"]])
    assert _public_api("verify_context_fabric")(root)["artifacts_verified"] == 2

    database = root / "context_fabric.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER IF EXISTS event_artifacts_no_update")
        connection.execute("DROP TRIGGER IF EXISTS event_artifacts_no_delete")
        connection.execute(
            "DELETE FROM event_artifacts WHERE event_id=? AND artifact_id=?",
            (event.event_id, artifact_b["artifact_id"]),
        )
        connection.commit()
    with pytest.raises(Exception, match="artifact|event hash|binding|mismatch|integrity"):
        _public_api("verify_context_fabric")(root)


def test_materialization_is_persisted_idempotently_with_source_and_tip_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    source = _capture(
        _hook("UserPromptSubmit", prompt="materialize exact working-world evidence"),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    _public_api("run_projection_producers")(root=root, through_seq=source.seq)
    materialize = _public_api("materialize_context")
    first = materialize(
        query="working-world evidence",
        root=root,
        session_id=SESSION_A,
        carrier_id="s-primary",
        persist=True,
    )
    duplicate = materialize(
        query="working-world evidence",
        root=root,
        session_id=SESSION_A,
        carrier_id="s-primary",
        persist=True,
    )

    assert duplicate["materialization_id"] == first["materialization_id"]
    assert duplicate["status"] == "duplicate"
    assert first["input_tip"] == {"seq": source.seq, "event_hash": source.event_hash}
    assert source.event_id in first["source_refs"]
    assert first["content_sha256"] == _sha256_text(first["rendered_context"])
    assert first["authority"] is False
    assert first["instruction_source"] is False
    assert first["completion_claim_allowed"] is False
    assert first["current_prompt_included"] is False


def test_rehydrate_from_fresh_carrier_returns_same_pinned_non_authoritative_world(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    evidence = _capture(
        _hook(
            "UserPromptSubmit",
            prompt="可重建连续性，不是 authority 或自动续跑。",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    _public_api("run_projection_producers")(root=root, through_seq=evidence.seq)
    rehydrate = _public_api("rehydrate_context")
    events_before = context_runtime.store_inventory(root)["events"]
    event = _hook(
        "SessionStart",
        session_id=SESSION_A,
        turn_id="",
        timestamp="2026-08-13T07:00:00Z",
        source="resume",
    )
    first = rehydrate(
        event,
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    second = rehydrate(
        event,
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    assert second["materialization_id"] == first["materialization_id"]
    assert evidence.event_id in first["source_refs"]
    assert "可重建连续性" in first["rendered_context"]
    assert first["authority"] is False
    assert first["instruction_source"] is False
    assert first["completion_claim_allowed"] is False
    assert first.get("continuation_authorized") in {False, None}
    assert context_runtime.store_inventory(root)["events"] == events_before


def test_snapshot_restore_is_staged_verified_and_independent_of_later_source_appends(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    source = _capture(
        _hook("UserPromptSubmit", prompt="快照应恢复这个 exact evidence"),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    artifact = _admit_sanitized_exact(
        b"snapshot-bound artifact",
        root=root,
        source="codex:item_completed:sanitized-snapshot-artifact",
    )
    _public_api("run_projection_producers")(root=root, through_seq=source.seq)
    snapshot_root = tmp_path / "snapshot"
    snapshot = context_runtime.create_snapshot(snapshot_root, root=root)
    manifest_path = Path(snapshot["manifest_path"])
    manifest_sha256 = _sha256_bytes(manifest_path.read_bytes())

    later = _capture(
        _hook(
            "UserPromptSubmit",
            turn_id=TURN_B,
            timestamp="2026-08-13T08:00:00Z",
            prompt="快照后追加，不应出现在 restore",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    assert later.seq > source.seq
    target = tmp_path / "restored"
    restored = _public_api("restore_snapshot")(
        snapshot_root,
        target,
        expected_manifest_sha256=manifest_sha256,
        require_empty=True,
    )
    assert restored["status"] == "restored"
    assert restored["source_manifest_sha256"] == manifest_sha256
    assert restored["completion_marker_written_last"] is True
    verification = _public_api("verify_context_fabric")(target)
    assert verification["event_count"] == 1
    assert verification["tip_event_hash"] == source.event_hash
    assert verification["artifacts_verified"] == 1
    assert context_runtime.read_event(source.event_id, root=target)["raw_text"].startswith(
        "快照应恢复"
    )
    with pytest.raises(Exception, match="unknown event_id"):
        context_runtime.read_event(later.event_id, root=target)
    restored_blob = target / str(artifact["blob_relpath"])
    assert restored_blob.read_bytes() == b"snapshot-bound artifact"


def test_restore_rejects_manifest_or_blob_tamper_and_never_overwrites_a_live_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    artifact = _admit_sanitized_exact(
        b"immutable recovery bytes",
        root=root,
        source="codex:item_completed:sanitized-recovery",
    )
    snapshot_root = tmp_path / "snapshot"
    snapshot = context_runtime.create_snapshot(snapshot_root, root=root)
    manifest = Path(snapshot["manifest_path"])
    expected_manifest_sha256 = _sha256_bytes(manifest.read_bytes())
    blob = snapshot_root / str(artifact["blob_relpath"])
    assert blob.is_file()
    blob.write_bytes(b"tampered")

    target = tmp_path / "restore-target"
    with pytest.raises(Exception, match="hash|manifest|artifact|snapshot|mismatch"):
        _public_api("restore_snapshot")(
            snapshot_root,
            target,
            expected_manifest_sha256=expected_manifest_sha256,
            require_empty=True,
        )
    assert not target.exists() or not any(target.iterdir())

    live_target = tmp_path / "live-target"
    context_runtime.initialize_context_fabric(live_target)
    live_before = (live_target / "context_fabric.sqlite3").read_bytes()
    with pytest.raises(Exception, match="empty|target|overwrite|initialized"):
        _public_api("restore_snapshot")(
            snapshot_root,
            live_target,
            require_empty=True,
        )
    assert (live_target / "context_fabric.sqlite3").read_bytes() == live_before


def test_full_verification_detects_blob_drift_without_rewriting_canonical_state(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    artifact = _admit_sanitized_exact(
        b"original artifact bytes",
        root=root,
        source="codex:item_completed:sanitized-drift-check",
    )
    blob = root / str(artifact["blob_relpath"])
    blob.write_bytes(b"drifted artifact bytes")
    drifted = blob.read_bytes()

    with pytest.raises(Exception, match="artifact|blob|hash|byte"):
        _public_api("verify_context_fabric")(root)
    assert blob.read_bytes() == drifted


def test_rollout_import_admits_real_tool_surfaces_as_typed_hash_only_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    home = tmp_path / ".codex"
    session_dir = home / "sessions" / "2026" / "08" / "13"
    session_dir.mkdir(parents=True)
    rollout = session_dir / f"rollout-2026-08-13T09-00-00-{SESSION_A}.jsonl"
    records: list[dict[str, object]] = [
        {
            "timestamp": "2026-08-13T09:00:00Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {
                "id": SESSION_A,
                "session_id": SESSION_A,
                "thread_source": "user",
                "source": "cli",
                "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
            },
        },
        {
            "timestamp": "2026-08-13T09:00:01Z",
            "ordinal": 1,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "INJECTED-WRAPPER-MUST-NOT-IMPORT"}],
            },
        },
        _rollout_item(
            {
                "type": "UserMessage",
                "id": "user-real-surface",
                "content": [{"type": "text", "text": "REAL-USER-SURFACE"}],
            },
            ordinal=2,
        ),
        _rollout_item(
            {
                "type": "AgentMessage",
                "id": "assistant-real-surface",
                "phase": "final_answer",
                "content": [{"type": "Text", "text": "REAL-ASSISTANT-SURFACE"}],
            },
            ordinal=3,
        ),
        _rollout_item(
            {
                "type": "CommandExecution",
                "id": "command-real-surface",
                "process_id": "1234",
                "command": ["pwsh", "-Command", "TOOL-COMMAND-MUST-NOT-STORE"],
                "cwd": r"C:\PRIVATE-PATH-MUST-NOT-STORE",
                "parsed_cmd": [{"type": "unknown", "cmd": "TOOL-PARSED-MUST-NOT-STORE"}],
                "source": "unified_exec_startup",
                "status": "completed",
                "stdout": "TOOL-STDOUT-MUST-NOT-STORE",
                "stderr": "TOOL-STDERR-MUST-NOT-STORE",
                "aggregated_output": "TOOL-AGGREGATE-MUST-NOT-STORE",
                "exit_code": 0,
                "duration": {"secs": 0, "nanos": 1},
                "formatted_output": "TOOL-FORMATTED-MUST-NOT-STORE",
            },
            ordinal=4,
        ),
        _rollout_item(
            {
                "type": "FileChange",
                "id": "file-change-real-surface",
                "changes": {
                    r"E:\PRIVATE-FILE-MUST-NOT-STORE.txt": {
                        "type": "update",
                        "unified_diff": "FILE-DIFF-MUST-NOT-STORE",
                        "move_path": None,
                    }
                },
                "status": "completed",
                "stdout": "FILE-STDOUT-MUST-NOT-STORE",
                "stderr": "",
            },
            ordinal=5,
        ),
        _rollout_item(
            {
                "type": "Extension",
                "kind": "web.search",
                "id": "extension-real-surface",
                "query": "EXTENSION-QUERY-MUST-NOT-STORE",
                "action": {
                    "type": "search",
                    "query": None,
                    "queries": ["EXTENSION-ACTION-MUST-NOT-STORE"],
                },
                "results": [
                    {
                        "type": "computer_initialize_state",
                        "domain": "private.example",
                        "ref_id": "private-ref",
                        "snippet": "EXTENSION-SNIPPET-MUST-NOT-STORE",
                        "title": "EXTENSION-TITLE-MUST-NOT-STORE",
                        "url": "https://private.example/MUST-NOT-STORE",
                    }
                ],
            },
            ordinal=6,
        ),
        _rollout_item(
            {
                "type": "Extension",
                "kind": "web.search",
                "id": "extension-other-real-surface",
                "query": "EXTENSION-OTHER-QUERY-MUST-NOT-STORE",
                "action": {"type": "other"},
                "results": [],
            },
            ordinal=7,
        ),
    ]
    complete_prefix = b"".join(_canonical_bytes(record) + b"\n" for record in records)
    tail_record = _rollout_item(
        {
            "type": "UserMessage",
            "id": "user-partial-tail",
            "content": [{"type": "text", "text": "PARTIAL-TAIL-ONLY-AFTER-COMMIT"}],
        },
        ordinal=8,
        turn_id=TURN_B,
    )
    complete_tail = _canonical_bytes(tail_record) + b"\n"
    rollout.write_bytes(complete_prefix + complete_tail[:-2])
    allowed_homes = {str(home): "s-primary"}

    first = context_runtime.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=root,
        allowed_homes=allowed_homes,
    )
    assert first["artifacts_hash_only"] == 4
    assert len(first["artifact_ids"]) == 4
    assert len(first["artifact_event_ids"]) == 4
    assert first["committed_through_ordinal"] == 7
    assert first["incomplete_tail"] is True
    assert context_runtime.store_inventory(root)["artifacts"] == 4

    item_types: set[str] = set()
    for event_id in first["artifact_event_ids"]:
        event = context_runtime.read_event(str(event_id), root=root)
        assert event["event_kind"] == "tool_artifact"
        assert event["raw_text"] == ""
        assert len(event["artifact_ids"]) == 1
        item_types.add(str(event["metadata"]["item_type"]))
    assert item_types == {"CommandExecution", "FileChange", "Extension"}

    forbidden_markers = (
        "INJECTED-WRAPPER",
        "TOOL-COMMAND",
        "TOOL-STDOUT",
        "PRIVATE-PATH",
        "PRIVATE-FILE",
        "FILE-DIFF",
        "EXTENSION-QUERY",
        "EXTENSION-SNIPPET",
        "PARTIAL-TAIL",
    )
    database_bytes = (root / "context_fabric.sqlite3").read_bytes()
    rendered = context_runtime.render_materialized_context(query="tool", root=root)
    for marker in forbidden_markers:
        assert marker.encode("utf-8") not in database_bytes
        assert marker not in rendered
    assert "REAL-USER-SURFACE" in rendered
    assert "REAL-ASSISTANT-SURFACE" in rendered

    with rollout.open("ab") as handle:
        handle.write(complete_tail[-2:])
    second = context_runtime.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=root,
        allowed_homes=allowed_homes,
    )
    assert second["committed_through_ordinal"] == 8
    assert second["incomplete_tail"] is False
    assert second["appended"] == 1
    assert context_runtime.store_inventory(root)["events"] == 7
    assert context_runtime.store_inventory(root)["artifacts"] == 4
    assert "PARTIAL-TAIL-ONLY-AFTER-COMMIT" in context_runtime.render_materialized_context(
        query="PARTIAL-TAIL", root=root
    )


@pytest.mark.parametrize("boundary_name", ["PostCompact", "SessionEnd"])
def test_structural_activity_compact_is_created_only_at_activity_boundaries_and_replays_idempotently(
    tmp_path: Path,
    boundary_name: str,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    user = _capture(
        _hook(
            "UserPromptSubmit",
            prompt=f"ACTIVITY-COMPACT-{boundary_name}-SOURCE",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    assistant = _capture(
        _hook(
            "Stop",
            assistant=f"ACTIVITY-COMPACT-{boundary_name}-RESPONSE",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    context_runtime.run_projection_producers(root=root, through_seq=assistant.seq)
    pre_compact = _capture(
        _hook(
            "PreCompact",
            turn_id=TURN_B,
            timestamp="2026-08-13T10:00:00Z",
            trigger="auto",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    context_runtime.run_projection_producers(
        root=root,
        trigger_event_id=pre_compact.event_id,
    )
    database = root / "context_fabric.sqlite3"
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM projections WHERE kind='activity_compact'"
            ).fetchone()[0]
            == 0
        )

    boundary = _capture(
        _hook(
            boundary_name,
            turn_id=TURN_C,
            timestamp="2026-08-13T10:00:01Z",
            trigger="auto",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    first = context_runtime.run_projection_producers(
        root=root,
        trigger_event_id=boundary.event_id,
    )
    replay = context_runtime.run_projection_producers(
        root=root,
        trigger_event_id=boundary.event_id,
    )
    assert replay["status"] == "duplicate"
    assert replay["projection_ids"] == first["projection_ids"]

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT p.projection_id,pm.automatic,pm.producer_id "
            "FROM projections p JOIN projection_metadata pm "
            "ON pm.projection_id=p.projection_id WHERE p.kind='activity_compact'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["automatic"] == 1
        assert rows[0]["producer_id"]
        sources = {
            row[0]
            for row in connection.execute(
                "SELECT event_id FROM projection_sources WHERE projection_id=?",
                (rows[0]["projection_id"],),
            )
        }
    assert boundary.event_id in sources
    assert {user.event_id, assistant.event_id} <= sources


def test_same_semantic_key_in_distinct_scopes_remains_simultaneously_visible(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    historical_source = _capture(
        _hook(
            "UserPromptSubmit",
            prompt="SAME-SEMANTIC-KEY historical experiment evidence",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    current_source = _capture(
        _hook(
            "UserPromptSubmit",
            turn_id=TURN_B,
            prompt="SAME-SEMANTIC-KEY current launcher evidence",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    historical = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "shared-letter-c",
            "scope_key": "historical-experiment:arm-c",
            "statement": "SAME-SEMANTIC-KEY C names a historical experiment arm.",
            "aliases": ["SAME-SEMANTIC-KEY"],
            "temporal_scope": "historical experiment",
            "status_label": "historical",
            "source_event_ids": [historical_source.event_id],
            "content": {"identity": "experiment_arm"},
        },
        root=root,
    )
    current = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "shared-letter-c",
            "scope_key": "current-runtime:account-slot-c",
            "statement": "SAME-SEMANTIC-KEY C names the current account slot.",
            "aliases": ["SAME-SEMANTIC-KEY"],
            "temporal_scope": "current runtime",
            "status_label": "current",
            "source_event_ids": [current_source.event_id],
            "content": {"identity": "account_slot"},
        },
        root=root,
    )

    materialized = context_runtime.materialize_context(
        query="SAME-SEMANTIC-KEY",
        root=root,
        persist=False,
    )
    payload = _materialized_payload(materialized["rendered_context"])
    selected = {
        item["projection_id"]: item
        for item in payload["derived_projections"]
        if item["semantic_key"] == "shared-letter-c"
    }
    assert set(selected) == {historical["projection_id"], current["projection_id"]}
    assert {item["scope_key"] for item in selected.values()} == {
        "historical-experiment:arm-c",
        "current-runtime:account-slot-c",
    }


@pytest.mark.parametrize(
    (
        "source_label",
        "parent_boundary",
        "edge_relation",
        "lineage_status",
        "evidence_basis",
        "retains_predecessor",
    ),
    [
        (
            "compact",
            "PostCompact",
            "compact_continuation",
            "resolved",
            "same_session_ordered",
            True,
        ),
        (
            "resume",
            "SessionStart",
            None,
            "unresolved",
            "explicit_boundary_only",
            False,
        ),
    ],
)
def test_resume_and_compact_lineage_preserves_only_observed_edges_and_is_idempotent(
    tmp_path: Path,
    source_label: str,
    parent_boundary: str,
    edge_relation: str | None,
    lineage_status: str,
    evidence_basis: str,
    retains_predecessor: bool,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    parent = _capture(
        _hook(
            parent_boundary,
            turn_id="" if parent_boundary == "SessionStart" else TURN_A,
            source="startup" if parent_boundary == "SessionStart" else "boundary",
            timestamp="2026-08-13T11:00:00Z",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    parent_node = context_runtime.record_session_lineage(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_A,
            "source": "startup" if parent_boundary == "SessionStart" else "compact",
            "transcript_locator_sha256": "7" * 64,
        },
        source_event_id=parent.event_id,
        root=root,
    )
    child = _capture(
        _hook(
            "SessionStart",
            turn_id="",
            timestamp="2026-08-13T11:00:01Z",
            source=source_label,
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    child_node = context_runtime.record_session_lineage(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_A,
            "source": source_label,
            "transcript_locator_sha256": "8" * 64,
        },
        source_event_id=child.event_id,
        predecessor_event_id=parent.event_id,
        root=root,
    )
    duplicate = context_runtime.record_session_lineage(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_A,
            "source": source_label,
            "transcript_locator_sha256": "8" * 64,
        },
        source_event_id=child.event_id,
        predecessor_event_id=parent.event_id,
        root=root,
    )
    assert duplicate["node_id"] == child_node["node_id"]
    assert child_node["lineage_status"] == lineage_status
    assert child_node["evidence_quality"] == evidence_basis
    assert child_node["predecessor_event_id"] == (parent.event_id if retains_predecessor else "")

    lineage = context_runtime.read_session_lineage(SESSION_A, root=root)
    assert lineage["authority"] is False
    edges = [edge for edge in lineage["edges"] if edge["child_node_id"] == child_node["node_id"]]
    if edge_relation is None:
        assert edges == []
    else:
        assert len(edges) == 1
        assert edges[0]["parent_node_id"] == parent_node["node_id"]
        assert edges[0]["relation"] == edge_relation
        assert edges[0]["evidence_basis"] == evidence_basis
        assert edges[0]["authority"] == 0


def test_explicit_parent_session_must_resolve_to_an_existing_lineage_node(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    child = _capture(
        _hook(
            "SessionStart",
            session_id=SESSION_B,
            turn_id="",
            timestamp="2026-08-13T11:30:00Z",
            source="startup",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    missing_parent = "019ff778-e326-7b91-9784-4fe809585e04"
    with pytest.raises(Exception, match="parent.*(?:exist|unknown|lineage|resolve)"):
        context_runtime.record_session_lineage(
            {
                "carrier_id": "s-primary",
                "session_id": SESSION_B,
                "source": "startup",
                "parent_session_id": missing_parent,
                "transcript_locator_sha256": "9" * 64,
            },
            source_event_id=child.event_id,
            root=root,
        )


def test_compact_without_observed_postcompact_keeps_unresolved_node_without_edge(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    earlier_start = _capture(
        _hook("SessionStart", turn_id="", source="startup"),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    context_runtime.record_session_lineage(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_A,
            "source": "startup",
            "transcript_locator_sha256": "1" * 64,
        },
        source_event_id=earlier_start.event_id,
        root=root,
    )
    compact_start = _capture(
        _hook(
            "SessionStart",
            turn_id="",
            timestamp="2026-08-13T12:00:00Z",
            source="compact",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    node = context_runtime.record_session_lineage(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_A,
            "source": "compact",
            "transcript_locator_sha256": "2" * 64,
        },
        source_event_id=compact_start.event_id,
        root=root,
    )
    lineage = context_runtime.read_session_lineage(SESSION_A, root=root)
    assert node["lineage_status"] == "unresolved"
    assert node["evidence_quality"] == "explicit_boundary_only"
    assert node["predecessor_event_id"] == ""
    assert not [edge for edge in lineage["edges"] if edge["child_node_id"] == node["node_id"]]


def test_legacy_event_chain_is_read_compatible_while_all_writers_require_migration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy-v1"
    legacy = _seed_legacy_v1(root)
    before = (root / "context_fabric.sqlite3").read_bytes()
    verification = context_runtime.verify_event_chain(root)
    assert verification["event_count"] == 1
    assert verification["tip_event_hash"] == legacy["event_hash"]

    allowed_homes, environ = _mount(tmp_path)
    with pytest.raises(Exception, match="migrat|feature|schema|version"):
        context_runtime.capture_hook_event(
            _hook("UserPromptSubmit", prompt="legacy writer must remain closed"),
            root=root,
            allowed_homes=allowed_homes,
            environ=environ,
        )
    with pytest.raises(Exception, match="migrat|feature|schema|version"):
        context_runtime.append_context_event(
            {
                "carrier_id": "s-primary",
                "session_id": SESSION_A,
                "turn_id": TURN_B,
                "event_kind": "user_message",
                "speaker": "user",
                "raw_text": "second legacy write must remain closed",
                "occurred_at": "2026-08-13T12:00:00Z",
                "authority_class": "human_raw_evidence",
                "source_kind": "completion_test",
                "source_locator": "completion-test:legacy-write",
                "source_record_sha256": "a" * 64,
                "source_key": "completion-test:legacy-write",
                "metadata": {},
            },
            root=root,
        )
    assert (root / "context_fabric.sqlite3").read_bytes() == before


def test_nonempty_fabric_materialization_suppresses_duplicate_current_situation_injection(
    tmp_path: Path,
) -> None:
    fabric_root = tmp_path / "fabric"
    situation_root = tmp_path / "current-situation"
    context_runtime.initialize_context_fabric(fabric_root)
    allowed_homes, environ = _mount(tmp_path)
    _capture(
        _hook("UserPromptSubmit", prompt="FABRIC-NONEMPTY-CONTEXT-MARKER"),
        root=fabric_root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    snapshot = build_snapshot(
        lineage_id="completion-current-situation",
        generation=0,
        last_event_ref={
            "event_id": "current-situation-event",
            "event_sha256": "b" * 64,
            "relation": "correction",
        },
        current={
            "activity": {
                "description": "CURRENT-SITUATION-MUST-NOT-DOUBLE-INJECT",
                "mode": "discussion",
            },
            "object": {"description": "separate provisional compatibility checkpoint"},
            "human_relation": {
                "description": "Fabric is canonical for this materialization",
                "user_need_not_repeat": "the already materialized context",
            },
            "understandings": [],
            "retracted": [],
            "open_relations": [],
        },
    )
    initialize_store(
        hook_module.session_store_path(SESSION_A, store_root=situation_root),
        snapshot,
    )
    result = hook_module.handle_hook_event(
        _hook(
            "SessionStart",
            turn_id="",
            timestamp="2026-08-13T12:30:00Z",
            source="resume",
        ),
        store_root=situation_root,
        context_fabric_enabled=True,
        context_fabric_root=fabric_root,
        context_fabric_environ=environ,
        context_fabric_allowed_homes=allowed_homes,
    )
    context = result["hookSpecificOutput"]["additionalContext"]
    assert context.count("[S CONTEXT FABRIC - RETRIEVED EVIDENCE, NON-AUTHORITATIVE]") == 1
    assert "FABRIC-NONEMPTY-CONTEXT-MARKER" in context
    assert "CURRENT SITUATION CHECKPOINT" not in context
    assert "CURRENT-SITUATION-MUST-NOT-DOUBLE-INJECT" not in context


def test_future_valid_from_correction_is_not_current_before_its_effective_time(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    old_source = _capture(
        _hook("UserPromptSubmit", prompt="FUTURE-CORRECTION-SCOPE old evidence"),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    old = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "future-effective-definition",
            "scope_key": "future-effective-definition",
            "statement": "FUTURE-CORRECTION-SCOPE old definition is current.",
            "aliases": ["FUTURE-CORRECTION-SCOPE"],
            "source_event_ids": [old_source.event_id],
            "status_label": "current",
            "content": {"value": "old"},
        },
        root=root,
    )
    correction_source = _capture(
        _hook(
            "UserPromptSubmit",
            turn_id=TURN_B,
            prompt="A replacement was declared for a far-future effective time.",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    replacement = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "future-effective-definition",
            "scope_key": "future-effective-definition",
            "statement": "FUTURE-CORRECTION-SCOPE future definition is not current yet.",
            "aliases": ["FUTURE-CORRECTION-SCOPE"],
            "source_event_ids": [correction_source.event_id],
            "status_label": "future",
            "supersedes_projection_id": old["projection_id"],
            "content": {"value": "future"},
        },
        root=root,
    )
    context_runtime.append_correction(
        {
            "prior_ref": old["projection_id"],
            "replacement_ref": replacement["projection_id"],
            "source_event_id": correction_source.event_id,
            "scope_key": "future-effective-definition",
            "valid_from": "2999-01-01T00:00:00Z",
            "temporal_basis": "explicit_future_effective_time",
        },
        root=root,
    )

    current = context_runtime.materialize_context(
        query="FUTURE-CORRECTION-SCOPE",
        root=root,
        persist=False,
    )
    assert old["projection_id"] in current["source_refs"]
    assert replacement["projection_id"] not in current["source_refs"]
    assert "old definition is current" in current["rendered_context"]
    assert "future definition is not current yet" not in current["rendered_context"]


def test_unresolved_fresh_session_does_not_receive_another_sessions_local_compact(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    marker = "OTHER-SESSION-LOCAL-COMPACT-6f2a"
    _capture(
        _hook("UserPromptSubmit", session_id=SESSION_A, prompt=marker),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    closed = _capture(
        _hook("Stop", session_id=SESSION_A, assistant=f"closed {marker}"),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    context_runtime.run_projection_producers(root=root, through_seq=closed.seq)
    with sqlite3.connect(root / "context_fabric.sqlite3") as connection:
        local = connection.execute(
            "SELECT p.projection_id,pm.scope_key FROM projections p "
            "JOIN projection_metadata pm ON pm.projection_id=p.projection_id "
            "WHERE p.kind='local_compact'"
        ).fetchone()
    assert local is not None
    assert local[1] == f"session:{SESSION_A}"

    startup = _capture(
        _hook(
            "SessionStart",
            session_id=SESSION_B,
            turn_id="",
            timestamp="2026-08-13T13:00:00Z",
            source="startup",
        ),
        root=root,
        allowed_homes=allowed_homes,
        environ=environ,
    )
    context_runtime.record_session_lineage(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_B,
            "source": "startup",
            "transcript_locator_sha256": "c" * 64,
        },
        source_event_id=startup.event_id,
        root=root,
    )
    fresh = context_runtime.materialize_context(
        query=marker,
        session_id=SESSION_B,
        carrier_id="s-primary",
        root=root,
        persist=False,
    )
    payload = _materialized_payload(fresh["rendered_context"])
    assert fresh["lineage_status"] == "unresolved"
    assert fresh["retrieval_scope"] == "query_relevant_cross_session_evidence"
    assert local[0] not in fresh["source_refs"]
    assert not [
        item
        for item in payload["derived_projections"]
        if item["kind"] == "local_compact" and item["scope_key"] == f"session:{SESSION_A}"
    ]


def test_same_session_uuid_on_two_carriers_keeps_structural_rounds_isolated(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    context_runtime.initialize_context_fabric(root)
    primary_home = tmp_path / ".codex-primary"
    account_b_home = tmp_path / ".codex-b"
    primary_home.mkdir()
    account_b_home.mkdir()
    allowed_homes = {
        str(primary_home): "s-primary",
        str(account_b_home): "s-account-b",
    }
    primary_environ = {"CODEX_HOME": str(primary_home)}
    account_b_environ = {"CODEX_HOME": str(account_b_home)}
    primary_marker = "PRIMARY-CARRIER-ROUND-31d4"
    account_b_marker = "ACCOUNT-B-CARRIER-ROUND-82ae"

    _capture(
        _hook("UserPromptSubmit", prompt=primary_marker),
        root=root,
        allowed_homes=allowed_homes,
        environ=primary_environ,
    )
    _capture(
        _hook("Stop", assistant=f"closed {primary_marker}"),
        root=root,
        allowed_homes=allowed_homes,
        environ=primary_environ,
    )
    _capture(
        _hook("UserPromptSubmit", prompt=account_b_marker),
        root=root,
        allowed_homes=allowed_homes,
        environ=account_b_environ,
    )
    account_b_stop = _capture(
        _hook("Stop", assistant=f"closed {account_b_marker}"),
        root=root,
        allowed_homes=allowed_homes,
        environ=account_b_environ,
    )
    context_runtime.run_projection_producers(root=root, through_seq=account_b_stop.seq)

    primary = context_runtime.materialize_context(
        session_id=SESSION_A,
        carrier_id="s-primary",
        root=root,
        persist=False,
    )
    account_b = context_runtime.materialize_context(
        session_id=SESSION_A,
        carrier_id="s-account-b",
        root=root,
        persist=False,
    )
    assert primary_marker in primary["rendered_context"]
    assert account_b_marker not in primary["rendered_context"]
    assert account_b_marker in account_b["rendered_context"]
    assert primary_marker not in account_b["rendered_context"]
