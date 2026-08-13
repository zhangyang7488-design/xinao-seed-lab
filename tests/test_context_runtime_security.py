from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import services.agent_runtime.codex_situation_hook as hook_module
import services.agent_runtime.context_fabric as context_runtime
import services.agent_runtime.context_runtime_completion as completion_module
from services.agent_runtime.codex_situation_hook import L0_CONTEXT, handle_hook_event

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = REPO_ROOT / "scripts" / "codex_situation_context_hook.py"
MANAGER = REPO_ROOT / "scripts" / "manage_context_fabric.py"
SESSION_ID = "019ff75c-703c-7972-96cd-b0d257b13baa"
TURN_ID = "019ff75d-1749-7662-9e80-aafa605718ab"


def _database(root: Path) -> Path:
    return root / "context_fabric.sqlite3"


def _mount(tmp_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    home = tmp_path / ".codex"
    home.mkdir(exist_ok=True)
    return {str(home): "s-primary"}, {"CODEX_HOME": str(home)}


def _hook_event(
    name: str = "UserPromptSubmit",
    *,
    turn_id: str = TURN_ID,
    prompt: str = "security boundary probe",
    cwd: str | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "hook_event_name": name,
        "session_id": SESSION_ID,
        "turn_id": turn_id,
        "cwd": str(REPO_ROOT if cwd is None else cwd),
        "timestamp": "2026-08-13T00:00:00Z",
    }
    if name == "UserPromptSubmit":
        event["prompt"] = prompt
    if name == "Stop":
        event["last_assistant_message"] = prompt
    return event


def _seed_event(root: Path, index: int = 0) -> context_runtime.CaptureResult:
    return context_runtime.append_context_event(
        {
            "carrier_id": "s-primary",
            "session_id": SESSION_ID,
            "turn_id": f"security-turn-{index}",
            "event_kind": "user_message",
            "speaker": "user",
            "raw_text": f"security event {index}",
            "occurred_at": f"2026-08-13T00:00:{index:02d}Z",
            "authority_class": "human_raw_evidence",
            "source_kind": "security_test",
            "source_locator": f"security-test#{index}",
            "source_record_sha256": f"{index:064x}",
            "source_key": f"security-test:event:{index}",
            "metadata": {"case": index},
        },
        root=root,
    )


def _seed_projection(root: Path) -> dict[str, object]:
    event = _seed_event(root)
    return context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "security-derived-state",
            "statement": "This is derived non-authoritative state.",
            "source_event_ids": [event.event_id],
            "content": {"authority": False},
        },
        root=root,
    )


def _seed_legacy_v1(root: Path) -> None:
    root.mkdir()
    with sqlite3.connect(_database(root)) as connection:
        # The private constant is the exact legacy production schema.  Using it
        # avoids silently testing a v2-shaped database with only its label edited.
        connection.executescript(context_runtime._SCHEMA)


def _append_legacy_event(
    root: Path, *, source_key: str = "security-legacy:event:0"
) -> tuple[str, str]:
    raw_text = "legacy migration security event"
    raw_bytes = raw_text.encode("utf-8")
    metadata_json = json.dumps({"case": "legacy-migration"}, sort_keys=True, separators=(",", ":"))
    sha256 = context_runtime._sha256_bytes
    base: dict[str, object] = {
        "schema_version": context_runtime.EVENT_VERSION,
        "world_id": context_runtime.WORLD_ID,
        "body_id": context_runtime.BODY_ID,
        "carrier_id": "s-primary",
        "session_id": SESSION_ID,
        "turn_id": TURN_ID,
        "event_kind": "user_message",
        "speaker": "user",
        "occurred_at": "2026-08-13T00:00:00Z",
        "captured_at_unix_ns": 1_723_507_200_000_000_000,
        "raw_sha256": sha256(raw_bytes),
        "stored_text_sha256": sha256(raw_bytes),
        "raw_storage": "exact_utf8",
        "authority_class": "human_raw_evidence",
        "source_kind": "security_test",
        "source_locator": "security-test#legacy",
        "source_record_sha256": "a" * 64,
        "source_key": source_key,
        "metadata_json": metadata_json,
        "previous_event_hash": "0" * 64,
    }
    event_id = "evt_" + context_runtime._sha256_text(source_key)
    event_hash = sha256(context_runtime._canonical_bytes(base))
    columns = ["event_id", *base.keys(), "raw_text", "event_hash"]
    with sqlite3.connect(_database(root)) as connection:
        connection.execute(
            f"INSERT INTO events({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [event_id, *base.values(), raw_bytes, event_hash],
        )
        connection.executemany(
            "INSERT INTO event_terms(event_id,term) VALUES (?,?)",
            [(event_id, term) for term in context_runtime.lexical_terms(raw_text)],
        )
        connection.commit()
    return event_id, event_hash


def _child_environment(**overrides: str) -> dict[str, str]:
    # Do not forward account tokens or arbitrary user environment into test
    # children.  These variables are sufficient for an absolute Python binary.
    allowed = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP")
    environ = {name: os.environ[name] for name in allowed if name in os.environ}
    environ.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", **overrides})
    return environ


def _manager(root: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MANAGER), "--store-root", str(root), command],
        cwd=REPO_ROOT,
        env=_child_environment(),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


def _cursor(root: Path, relative_locator: str) -> tuple[object, ...]:
    with sqlite3.connect(_database(root)) as connection:
        row = connection.execute(
            "SELECT next_byte_offset,next_physical_ordinal,committed_through_ordinal,"
            "last_record_sha256,committed_prefix_sha256,admitted_count FROM rollout_cursors "
            "WHERE carrier_id='s-primary' AND relative_locator=?",
            (relative_locator,),
        ).fetchone()
    assert row is not None
    return tuple(row)


def _json_line(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _session_meta() -> dict[str, object]:
    return {
        "timestamp": "2026-08-13T00:00:00Z",
        "ordinal": 0,
        "type": "session_meta",
        "payload": {
            "id": SESSION_ID,
            "session_id": SESSION_ID,
            "thread_source": "user",
            "source": "cli",
            "cwd": str(REPO_ROOT),
        },
    }


def _user_item(ordinal: int, *, marker: str = "accepted prefix") -> dict[str, object]:
    return {
        "timestamp": f"2026-08-13T00:00:{ordinal:02d}Z",
        "ordinal": ordinal,
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "thread_id": SESSION_ID,
            "turn_id": TURN_ID,
            "item": {
                "type": "UserMessage",
                "id": f"security-user-{ordinal}",
                "content": [{"type": "text", "text": marker}],
            },
        },
    }


def _directory_link_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory links are unavailable on this host: {exc}")


def _tamper_then_restore_update_trigger(
    connection: sqlite3.Connection,
    *,
    table: str,
    trigger: str,
    update_sql: str,
) -> None:
    """Model an offline attacker who hides the temporary trigger removal."""

    connection.execute(f'DROP TRIGGER "{trigger}"')
    connection.execute(update_sql)
    connection.execute(
        f'CREATE TRIGGER "{trigger}" BEFORE UPDATE ON "{table}" '
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
    )
    connection.commit()


def _tamper_temporal_metadata_and_rehash(
    root: Path,
    *,
    table: str,
    trigger: str,
    identity_column: str,
    identity_value: str,
    updates: dict[str, str],
) -> None:
    """Rehash a bad temporal row so verification must check semantics, not only its digest."""

    with sqlite3.connect(_database(root)) as connection:
        connection.row_factory = sqlite3.Row
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (trigger,)
        ).fetchone()["sql"]
        connection.execute(f'DROP TRIGGER "{trigger}"')
        assignments = ",".join(f'"{column}"=?' for column in updates)
        connection.execute(
            f'UPDATE "{table}" SET {assignments} WHERE "{identity_column}"=?',
            (*updates.values(), identity_value),
        )
        row = connection.execute(
            f'SELECT * FROM "{table}" WHERE "{identity_column}"=?', (identity_value,)
        ).fetchone()
        assert row is not None
        identity = (
            completion_module._projection_metadata_identity(row)
            if table == "projection_metadata"
            else completion_module._relation_metadata_identity(row)
        )
        connection.execute(
            f'UPDATE "{table}" SET metadata_hash=? WHERE "{identity_column}"=?',
            (
                context_runtime._sha256_bytes(context_runtime._canonical_bytes(identity)),
                identity_value,
            ),
        )
        connection.execute(trigger_sql)
        connection.commit()


@pytest.mark.parametrize("field", ["source_key", "source_record_sha256"])
def test_public_event_admission_rejects_secret_or_non_digest_source_fields(
    tmp_path: Path, field: str
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    spec: dict[str, object] = {
        "carrier_id": "s-primary",
        "session_id": SESSION_ID,
        "turn_id": TURN_ID,
        "event_kind": "user_message",
        "speaker": "user",
        "raw_text": "safe surfaced text",
        "occurred_at": "2026-08-13T00:00:00Z",
        "authority_class": "human_raw_evidence",
        "source_kind": "security_test",
        "source_locator": "security-test#source-fields",
        "source_record_sha256": "b" * 64,
        "source_key": "security-test:source-fields",
        "metadata": {},
    }
    spec[field] = (
        "authorization=Bearer SECURITY_SOURCE_SECRET_123456789"
        if field == "source_key"
        else "not-a-sha256"
    )

    with pytest.raises(context_runtime.ContextFabricError, match="secret|sha256|invalid"):
        context_runtime.append_context_event(spec, root=root)
    assert context_runtime.store_inventory(root)["events"] == 0


def test_public_event_admission_rejects_conflicting_replay_of_one_source_key(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    first = _seed_event(root)
    conflicting = {
        "carrier_id": "s-primary",
        "session_id": SESSION_ID,
        "turn_id": TURN_ID,
        "event_kind": "user_message",
        "speaker": "user",
        "raw_text": "different bytes must not be hidden by duplicate status",
        "occurred_at": "2026-08-13T00:00:00Z",
        "authority_class": "human_raw_evidence",
        "source_kind": "security_test",
        "source_locator": "security-test#event-0",
        "source_record_sha256": context_runtime._sha256_text("source-record-0"),
        "source_key": "security-test:event:0",
        "metadata": {"index": 0},
    }

    with pytest.raises(context_runtime.ContextFabricError, match="replay|different|identity"):
        context_runtime.append_context_event(conflicting, root=root)
    inventory = context_runtime.store_inventory(root)
    assert inventory["events"] == 1
    assert (
        context_runtime.read_event(first.event_id, root=root)["raw_text"] != conflicting["raw_text"]
    )


def test_artifact_admission_rejects_non_digest_source_record(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)

    with pytest.raises(context_runtime.ContextFabricError, match="sha256|invalid"):
        context_runtime.admit_artifact(
            b"safe hash-only result",
            kind="completed_tool_result",
            media_type="text/plain",
            source_locator="security-test:artifact-source-field",
            source_record_sha256="authorization=Bearer SECURITY_SOURCE_SECRET_123456789",
            root=root,
        )
    assert context_runtime.store_inventory(root)["artifacts"] == 0


def test_migration_backup_round_trips_through_public_legacy_restore(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _seed_legacy_v1(root)
    event_id, event_hash = _append_legacy_event(root)
    backup = tmp_path / "external-backup"

    migrated = context_runtime.migrate_context_fabric(root, backup_root=backup)
    restored = tmp_path / "restored-legacy"
    receipt = context_runtime.restore_migration_preimage(
        backup,
        restored,
        expected_manifest_sha256=str(migrated["backup_manifest_sha256"]),
    )

    assert receipt["status"] == "restored_legacy_preimage"
    assert receipt["event_count"] == 1
    assert receipt["tip_event_hash"] == event_hash
    assert context_runtime.verify_event_chain(restored)["tip_event_hash"] == event_hash
    with sqlite3.connect(_database(restored)) as connection:
        assert connection.execute(
            "SELECT event_hash FROM events WHERE event_id=?", (event_id,)
        ).fetchone() == (event_hash,)
        assert (
            connection.execute("SELECT value FROM fabric_meta WHERE key='feature_level'").fetchone()
            is None
        )


def test_migration_rejects_external_backup_through_directory_link(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _seed_legacy_v1(root)
    _append_legacy_event(root)
    redirected_parent = tmp_path / "redirected-parent"
    redirected_parent.mkdir()
    link = tmp_path / "backup-link"
    _directory_link_or_skip(link, redirected_parent)

    with pytest.raises(context_runtime.ContextFabricError, match="link|junction|reparse"):
        context_runtime.migrate_context_fabric(root, backup_root=link / "backup")
    assert not (redirected_parent / "backup").exists()
    with sqlite3.connect(_database(root)) as connection:
        assert (
            connection.execute("SELECT value FROM fabric_meta WHERE key='feature_level'").fetchone()
            is None
        )


def test_migration_routes_external_cleanroom_backup_through_denial_before_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "legacy"
    _seed_legacy_v1(root)
    _append_legacy_event(root)
    cleanroom_backup = Path(r"\\?\E:\CODEX_CLEANROOM\security-migration-backup-must-not-create")
    original_validate = completion_module.fabric._validate_store_root
    denied: list[Path] = []

    def guarded_validate(candidate: Path, *, create: bool) -> tuple[Path, Path]:
        if completion_module.fabric._under_windows_root(
            completion_module.fabric._normalized_windows_path(candidate),
            completion_module.fabric._normalized_windows_path(r"E:\CODEX_CLEANROOM"),
        ):
            denied.append(Path(candidate))
            raise context_runtime.ContextFabricError("cleanroom backup denied before copy")
        return original_validate(candidate, create=create)

    monkeypatch.setattr(completion_module.fabric, "_validate_store_root", guarded_validate)
    with pytest.raises(context_runtime.ContextFabricError, match="cleanroom"):
        context_runtime.migrate_context_fabric(root, backup_root=cleanroom_backup)
    assert denied == [cleanroom_backup]
    with sqlite3.connect(_database(root)) as connection:
        assert (
            connection.execute("SELECT value FROM fabric_meta WHERE key='feature_level'").fetchone()
            is None
        )


def test_migration_preflight_rejects_legacy_trigger_tamper_before_backup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy"
    _seed_legacy_v1(root)
    _append_legacy_event(root)
    with sqlite3.connect(_database(root)) as connection:
        connection.execute("DROP TRIGGER events_no_update")
        connection.commit()
    backup = tmp_path / "must-not-exist"

    with pytest.raises(context_runtime.ContextFabricError, match="schema|trigger|legacy"):
        context_runtime.migrate_context_fabric(root, backup_root=backup)
    assert not backup.exists()


def test_migration_revalidates_backup_before_mutating_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "legacy"
    _seed_legacy_v1(root)
    _append_legacy_event(root)
    backup = tmp_path / "external-backup"
    original_snapshot = completion_module._legacy_preimage_snapshot

    def snapshot_then_corrupt(source: Path, output: Path) -> dict[str, object]:
        result = original_snapshot(source, output)
        with sqlite3.connect(_database(Path(str(result["snapshot_root"])))) as connection:
            connection.execute("DROP TRIGGER events_no_update")
            connection.commit()
        return result

    monkeypatch.setattr(completion_module, "_legacy_preimage_snapshot", snapshot_then_corrupt)
    with pytest.raises(
        context_runtime.ContextFabricError, match="backup|legacy|schema|trigger|manifest"
    ):
        context_runtime.migrate_context_fabric(root, backup_root=backup)
    with sqlite3.connect(_database(root)) as connection:
        assert (
            connection.execute("SELECT value FROM fabric_meta WHERE key='feature_level'").fetchone()
            is None
        )


def test_extended_length_cleanroom_alias_is_denied_before_store_access(tmp_path: Path) -> None:
    allowed_homes, environ = _mount(tmp_path)
    cleanroom_alias = r"\\?\E:\CODEX_CLEANROOM\security-probe-must-not-create"
    decision = context_runtime.evaluate_mount(
        {
            "cwd": cleanroom_alias,
            "_context_fabric_actual_cwd": cleanroom_alias,
        },
        environ=environ,
        allowed_homes=allowed_homes,
    )
    assert decision.mounted is False
    assert "cleanroom" in decision.reason

    # create=False is deliberate: even a regression in the deny comparison
    # cannot create anything in the clean-room body.
    with pytest.raises(context_runtime.ContextFabricError, match="cleanroom"):
        context_runtime._validate_store_root(Path(cleanroom_alias), create=False)


def test_official_adapter_gates_reported_cwd_with_mechanically_observed_cwd(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    child_cwd = tmp_path / "different-hook-process-cwd"
    child_cwd.mkdir()
    event = _hook_event("Stop", cwd=str(REPO_ROOT))
    process = subprocess.run(
        [sys.executable, str(ADAPTER)],
        input=json.dumps(event, ensure_ascii=False),
        cwd=child_cwd,
        env=_child_environment(
            CODEX_HOME=r"C:\Users\xx363\.codex",
            CODEX_CONTEXT_FABRIC_ROOT=str(root),
            CODEX_CURRENT_SITUATION_ROOT=str(tmp_path / "unused-current-situation"),
        ),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {"continue": True}
    assert context_runtime.store_inventory(root)["events"] == 0


@pytest.mark.parametrize("schema_state", ["legacy", "future"])
def test_manager_rejects_unsupported_schema_levels(tmp_path: Path, schema_state: str) -> None:
    root = tmp_path / schema_state
    if schema_state == "legacy":
        _seed_legacy_v1(root)
    else:
        context_runtime.initialize_context_fabric(root)
        with sqlite3.connect(_database(root)) as connection:
            connection.execute(
                "UPDATE fabric_meta SET value=? WHERE key='feature_level'",
                ("s.context_runtime.future.v999",),
            )
            connection.commit()

    with pytest.raises(context_runtime.ContextFabricError, match="schema|migration|unsupported"):
        context_runtime.initialize_context_fabric(root)
    managed = _manager(root, "inventory")
    assert managed.returncode != 0, managed.stdout


@pytest.mark.parametrize("schema_state", ["legacy", "future"])
def test_outer_hook_fails_open_at_l0_without_mutating_unsupported_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema_state: str,
) -> None:
    root = tmp_path / schema_state
    if schema_state == "legacy":
        _seed_legacy_v1(root)
    else:
        context_runtime.initialize_context_fabric(root)
        with sqlite3.connect(_database(root)) as connection:
            connection.execute(
                "UPDATE fabric_meta SET value=? WHERE key='feature_level'",
                ("s.context_runtime.future.v999",),
            )
            connection.commit()
    allowed_homes, environ = _mount(tmp_path)
    monkeypatch.setattr(hook_module, "render_runtime_context", lambda _event: "")
    with sqlite3.connect(_database(root)) as connection:
        before = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    result = handle_hook_event(
        _hook_event(),
        context_fabric_enabled=True,
        context_fabric_root=root,
        context_fabric_environ=environ,
        context_fabric_allowed_homes=allowed_homes,
    )
    assert result["continue"] is True
    assert result["hookSpecificOutput"]["additionalContext"] == L0_CONTEXT
    with sqlite3.connect(_database(root)) as connection:
        after = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    assert after == before


@pytest.mark.parametrize(
    "trigger_name",
    [
        "events_no_update",
        "event_terms_no_update",
        "projection_metadata_no_delete",
        "materializations_no_update",
    ],
)
def test_full_verifier_requires_every_append_only_trigger(
    tmp_path: Path, trigger_name: str
) -> None:
    root = tmp_path / trigger_name
    context_runtime.initialize_context_fabric(root)
    with sqlite3.connect(_database(root)) as connection:
        connection.execute(f'DROP TRIGGER "{trigger_name}"')
        connection.commit()
    with pytest.raises(context_runtime.ContextFabricError, match="trigger|append-only"):
        context_runtime.verify_context_fabric(root)


def test_full_verifier_rejects_fabric_meta_tamper(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    with sqlite3.connect(_database(root)) as connection:
        connection.execute("UPDATE fabric_meta SET value='attacker-world' WHERE key='world_id'")
        connection.commit()
    with pytest.raises(context_runtime.ContextFabricError, match="meta|world|schema"):
        context_runtime.verify_context_fabric(root)


def test_full_verifier_rejects_foreign_key_tamper(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    with sqlite3.connect(_database(root)) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO event_artifacts(event_id,artifact_id,role,ordinal) "
            "VALUES ('evt_missing','art_missing','evidence',0)"
        )
        connection.commit()
    with pytest.raises(context_runtime.ContextFabricError, match="FK|foreign|integrity"):
        context_runtime.verify_context_fabric(root)


@pytest.mark.parametrize(
    ("trigger_name", "tamper_sql"),
    [
        (
            "projections_no_update",
            "UPDATE projections SET statement='attacker-derived-statement'",
        ),
        (
            "projection_metadata_no_update",
            "UPDATE projection_metadata SET scope_key='attacker-derived-scope'",
        ),
    ],
)
def test_full_verifier_recomputes_derived_identity_hashes(
    tmp_path: Path, trigger_name: str, tamper_sql: str
) -> None:
    root = tmp_path / trigger_name
    context_runtime.initialize_context_fabric(root)
    _seed_projection(root)
    with sqlite3.connect(_database(root)) as connection:
        table = "projections" if trigger_name == "projections_no_update" else "projection_metadata"
        _tamper_then_restore_update_trigger(
            connection,
            table=table,
            trigger=trigger_name,
            update_sql=tamper_sql,
        )
    with pytest.raises(context_runtime.ContextFabricError, match="projection|derived|hash"):
        context_runtime.verify_context_fabric(root)


def test_full_verifier_rejects_rehashed_noncanonical_projection_time(tmp_path: Path) -> None:
    root = tmp_path / "projection-time"
    context_runtime.initialize_context_fabric(root)
    event = _seed_event(root)
    projection = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "canonical-projection-time",
            "statement": "Canonical UTC is part of the temporal contract.",
            "source_event_ids": [event.event_id],
            "valid_from": "2026-08-13T01:00:00Z",
            "temporal_basis": "security_test",
            "content": {"authority": False},
        },
        root=root,
    )
    with sqlite3.connect(_database(root)) as connection:
        connection.row_factory = sqlite3.Row
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='projection_metadata_no_update'"
        ).fetchone()["sql"]
        connection.execute("DROP TRIGGER projection_metadata_no_update")
        connection.execute(
            "UPDATE projection_metadata SET valid_from_at='2026-08-13T09:00:00+08:00' "
            "WHERE projection_id=?",
            (projection["projection_id"],),
        )
        metadata = connection.execute(
            "SELECT * FROM projection_metadata WHERE projection_id=?",
            (projection["projection_id"],),
        ).fetchone()
        assert metadata is not None
        metadata_hash = context_runtime._sha256_bytes(
            context_runtime._canonical_bytes(
                completion_module._projection_metadata_identity(metadata)
            )
        )
        connection.execute(
            "UPDATE projection_metadata SET metadata_hash=? WHERE projection_id=?",
            (metadata_hash, projection["projection_id"]),
        )
        connection.execute(trigger_sql)
        connection.commit()

    with pytest.raises(context_runtime.ContextFabricError, match="temporal|canonical|UTC"):
        context_runtime.verify_context_fabric(root)


def test_full_verifier_rejects_rehashed_noncanonical_relation_time(tmp_path: Path) -> None:
    root = tmp_path / "relation-time"
    context_runtime.initialize_context_fabric(root)
    event = _seed_event(root)
    prior = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "canonical-relation-prior",
            "statement": "Prior state.",
            "source_event_ids": [event.event_id],
            "content": {"authority": False},
        },
        root=root,
    )
    replacement = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "canonical-relation-replacement",
            "statement": "Replacement state.",
            "source_event_ids": [event.event_id],
            "content": {"authority": False},
        },
        root=root,
    )
    relation = context_runtime.append_relation(
        {
            "kind": "corrects",
            "from_ref": prior["projection_id"],
            "to_ref": replacement["projection_id"],
            "source_event_id": event.event_id,
            "effective_from_at": "2026-08-13T01:00:00Z",
            "temporal_basis": "security_test",
        },
        root=root,
    )
    with sqlite3.connect(_database(root)) as connection:
        connection.row_factory = sqlite3.Row
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='relation_metadata_no_update'"
        ).fetchone()["sql"]
        connection.execute("DROP TRIGGER relation_metadata_no_update")
        connection.execute(
            "UPDATE relation_metadata SET effective_from_at='2026-08-13T09:00:00+08:00' "
            "WHERE relation_id=?",
            (relation["relation_id"],),
        )
        metadata = connection.execute(
            "SELECT * FROM relation_metadata WHERE relation_id=?",
            (relation["relation_id"],),
        ).fetchone()
        assert metadata is not None
        metadata_hash = context_runtime._sha256_bytes(
            context_runtime._canonical_bytes(
                completion_module._relation_metadata_identity(metadata)
            )
        )
        connection.execute(
            "UPDATE relation_metadata SET metadata_hash=? WHERE relation_id=?",
            (metadata_hash, relation["relation_id"]),
        )
        connection.execute(trigger_sql)
        connection.commit()

    with pytest.raises(context_runtime.ContextFabricError, match="temporal|canonical|UTC"):
        context_runtime.verify_context_fabric(root)


@pytest.mark.parametrize("boundary_case", ["missing", "inverted"])
def test_projection_temporal_event_boundaries_require_existing_ordered_refs(
    tmp_path: Path, boundary_case: str
) -> None:
    root = tmp_path / f"projection-event-boundary-{boundary_case}"
    context_runtime.initialize_context_fabric(root)
    first = _seed_event(root, 1)
    second = _seed_event(root, 2)
    projection = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": f"valid-projection-boundary-{boundary_case}",
            "statement": "Valid event boundaries before offline temporal tamper.",
            "source_event_ids": [first.event_id],
            "valid_from_event_id": first.event_id,
            "valid_to_event_id": second.event_id,
            "content": {"authority": False},
        },
        root=root,
    )
    invalid_from = "evt_" + ("f" * 64) if boundary_case == "missing" else second.event_id
    invalid_to = second.event_id if boundary_case == "missing" else first.event_id
    _tamper_temporal_metadata_and_rehash(
        root,
        table="projection_metadata",
        trigger="projection_metadata_no_update",
        identity_column="projection_id",
        identity_value=str(projection["projection_id"]),
        updates={
            "valid_from_event_id": invalid_from,
            "valid_to_event_id": invalid_to,
        },
    )

    with pytest.raises(
        context_runtime.ContextFabricError, match="temporal|boundary|event|exist|order|interval"
    ):
        context_runtime.verify_context_fabric(root)
    with pytest.raises(
        context_runtime.ContextFabricError, match="temporal|boundary|event|exist|order|interval"
    ):
        context_runtime.append_projection(
            {
                "kind": "semantic_identity",
                "semantic_key": f"invalid-projection-boundary-{boundary_case}",
                "statement": "Invalid event boundaries must fail admission.",
                "source_event_ids": [first.event_id],
                "valid_from_event_id": invalid_from,
                "valid_to_event_id": invalid_to,
                "content": {"authority": False},
            },
            root=root,
        )


@pytest.mark.parametrize("boundary_case", ["missing", "inverted"])
def test_relation_temporal_event_boundaries_require_existing_ordered_refs(
    tmp_path: Path, boundary_case: str
) -> None:
    root = tmp_path / f"relation-event-boundary-{boundary_case}"
    context_runtime.initialize_context_fabric(root)
    first = _seed_event(root, 1)
    second = _seed_event(root, 2)
    prior = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": f"relation-prior-{boundary_case}",
            "statement": "Prior relation endpoint.",
            "source_event_ids": [first.event_id],
            "content": {"authority": False},
        },
        root=root,
    )
    replacement = context_runtime.append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": f"relation-replacement-{boundary_case}",
            "statement": "Replacement relation endpoint.",
            "source_event_ids": [second.event_id],
            "content": {"authority": False},
        },
        root=root,
    )
    relation = context_runtime.append_relation(
        {
            "kind": "corrects",
            "from_ref": prior["projection_id"],
            "to_ref": replacement["projection_id"],
            "source_event_id": first.event_id,
            "effective_from_event_id": first.event_id,
            "effective_to_event_id": second.event_id,
            "temporal_basis": "security_test",
            "note": f"valid relation {boundary_case}",
        },
        root=root,
    )
    invalid_from = "evt_" + ("e" * 64) if boundary_case == "missing" else second.event_id
    invalid_to = second.event_id if boundary_case == "missing" else first.event_id
    _tamper_temporal_metadata_and_rehash(
        root,
        table="relation_metadata",
        trigger="relation_metadata_no_update",
        identity_column="relation_id",
        identity_value=str(relation["relation_id"]),
        updates={
            "effective_from_event_id": invalid_from,
            "effective_to_event_id": invalid_to,
        },
    )

    with pytest.raises(
        context_runtime.ContextFabricError, match="temporal|boundary|event|exist|order|interval"
    ):
        context_runtime.verify_context_fabric(root)
    with pytest.raises(
        context_runtime.ContextFabricError, match="temporal|boundary|event|exist|order|interval"
    ):
        context_runtime.append_relation(
            {
                "kind": "corrects",
                "from_ref": prior["projection_id"],
                "to_ref": replacement["projection_id"],
                "source_event_id": first.event_id,
                "effective_from_event_id": invalid_from,
                "effective_to_event_id": invalid_to,
                "temporal_basis": "security_test",
                "note": f"invalid relation {boundary_case}",
            },
            root=root,
        )


def test_full_verifier_recomputes_artifact_identity_hash(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    artifact = context_runtime.admit_artifact(
        b"ordinary tool result remains hash-only",
        kind="completed_tool_result",
        media_type="text/plain",
        source_locator="security-test:artifact",
        storage_policy="hash_only",
        root=root,
    )
    with sqlite3.connect(_database(root)) as connection:
        _tamper_then_restore_update_trigger(
            connection,
            table="artifacts",
            trigger="artifacts_no_update",
            update_sql=(
                "UPDATE artifacts SET content_sha256='"
                + ("0" * 64)
                + f"' WHERE artifact_id='{artifact['artifact_id']}'"
            ),
        )
    with pytest.raises(context_runtime.ContextFabricError, match="artifact|hash"):
        context_runtime.verify_context_fabric(root)


def test_busy_database_keeps_outer_hook_bounded_and_l0_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    allowed_homes, environ = _mount(tmp_path)
    monkeypatch.setattr(hook_module, "render_runtime_context", lambda _event: "")
    lock = sqlite3.connect(_database(root), timeout=0)
    lock.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        result = handle_hook_event(
            _hook_event(),
            context_fabric_enabled=True,
            context_fabric_root=root,
            context_fabric_environ=environ,
            context_fabric_allowed_homes=allowed_homes,
        )
    finally:
        elapsed = time.monotonic() - started
        lock.rollback()
        lock.close()
    assert result["continue"] is True
    assert result["hookSpecificOutput"]["additionalContext"] == L0_CONTEXT
    assert elapsed < 4.0
    assert context_runtime.store_inventory(root)["events"] == 0


@pytest.mark.parametrize("bad_tail", ["ordinal_gap", "complete_bad_json"])
def test_rollout_cursor_does_not_advance_past_complete_invalid_tail(
    tmp_path: Path, bad_tail: str
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    home = tmp_path / ".codex"
    session_dir = home / "sessions" / "2026" / "08" / "13"
    session_dir.mkdir(parents=True)
    rollout = session_dir / f"rollout-security-{bad_tail}-{SESSION_ID}.jsonl"
    rollout.write_bytes(_json_line(_session_meta()) + _json_line(_user_item(1)))
    allowed_homes = {str(home): "s-primary"}
    context_runtime.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=root,
        allowed_homes=allowed_homes,
    )
    relative_locator = str(rollout.relative_to(home))
    before = _cursor(root, relative_locator)
    if bad_tail == "ordinal_gap":
        tail = _json_line(_user_item(3, marker="must not cross ordinal gap"))
        expected = "ordinal"
    else:
        tail = b'{"ordinal":2,"type":"event_msg","payload":BROKEN}\n'
        expected = "invalid"
    with rollout.open("ab") as handle:
        handle.write(tail)

    with pytest.raises(context_runtime.ContextFabricError, match=expected):
        context_runtime.import_codex_rollout(
            rollout,
            carrier_home=home,
            root=root,
            allowed_homes=allowed_homes,
        )
    assert _cursor(root, relative_locator) == before
    assert context_runtime.store_inventory(root)["events"] == 1


def test_rollout_cursor_rejects_same_length_rewrite_of_committed_tail(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    home = tmp_path / ".codex"
    session_dir = home / "sessions" / "2026" / "08" / "13"
    session_dir.mkdir(parents=True)
    rollout = session_dir / f"rollout-security-rewrite-{SESSION_ID}.jsonl"
    original = _json_line(_user_item(1, marker="accepted prefix A"))
    rewritten = _json_line(_user_item(1, marker="accepted prefix B"))
    assert len(rewritten) == len(original)
    rollout.write_bytes(_json_line(_session_meta()) + original)
    allowed_homes = {str(home): "s-primary"}

    context_runtime.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=root,
        allowed_homes=allowed_homes,
    )
    relative_locator = str(rollout.relative_to(home))
    before = _cursor(root, relative_locator)
    rollout.write_bytes(_json_line(_session_meta()) + rewritten)

    with pytest.raises(context_runtime.ContextFabricError, match="rewritten|committed|cursor"):
        context_runtime.import_codex_rollout(
            rollout,
            carrier_home=home,
            root=root,
            allowed_homes=allowed_homes,
        )
    assert _cursor(root, relative_locator) == before


def test_rollout_cursor_rejects_same_length_rewrite_before_committed_tail(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    home = tmp_path / ".codex"
    session_dir = home / "sessions" / "2026" / "08" / "13"
    session_dir.mkdir(parents=True)
    rollout = session_dir / f"rollout-security-prefix-rewrite-{SESSION_ID}.jsonl"
    first = _json_line(_user_item(1, marker="committed prefix A"))
    rewritten_first = _json_line(_user_item(1, marker="committed prefix B"))
    last = _json_line(_user_item(2, marker="unchanged committed tail"))
    assert len(rewritten_first) == len(first)
    session_meta = _json_line(_session_meta())
    rollout.write_bytes(session_meta + first + last)
    allowed_homes = {str(home): "s-primary"}

    context_runtime.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=root,
        allowed_homes=allowed_homes,
    )
    relative_locator = str(rollout.relative_to(home))
    before = _cursor(root, relative_locator)
    rollout.write_bytes(session_meta + rewritten_first + last)

    with pytest.raises(
        context_runtime.ContextFabricError, match="rewritten|committed|prefix|cursor"
    ):
        context_runtime.import_codex_rollout(
            rollout,
            carrier_home=home,
            root=root,
            allowed_homes=allowed_homes,
        )
    assert _cursor(root, relative_locator) == before


def test_rollout_cursor_fails_if_committed_prefix_is_truncated_during_recheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    home = tmp_path / ".codex"
    session_dir = home / "sessions" / "2026" / "08" / "13"
    session_dir.mkdir(parents=True)
    rollout = session_dir / f"rollout-security-racing-truncate-{SESSION_ID}.jsonl"
    rollout.write_bytes(_json_line(_session_meta()) + _json_line(_user_item(1)))
    allowed_homes = {str(home): "s-primary"}
    context_runtime.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=root,
        allowed_homes=allowed_homes,
    )
    relative_locator = str(rollout.relative_to(home))
    before = _cursor(root, relative_locator)
    committed_offset = int(before[0])
    with rollout.open("ab") as handle:
        handle.write(_json_line(_user_item(2, marker="uncommitted append")))

    original_open = Path.open
    rollout_identity = rollout.resolve()
    read_count = 0

    def racing_open(self: Path, mode: str = "r", *args: object, **kwargs: object):
        nonlocal read_count
        if self.resolve() == rollout_identity and mode == "rb":
            read_count += 1
            if read_count == 4:
                with original_open(self, "r+b") as mutator:
                    mutator.truncate(committed_offset - 1)
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)
    with pytest.raises(context_runtime.ContextFabricError, match="truncat|changed|prefix|cursor"):
        context_runtime.import_codex_rollout(
            rollout,
            carrier_home=home,
            root=root,
            allowed_homes=allowed_homes,
        )
    assert read_count >= 4
    assert _cursor(root, relative_locator) == before


def test_concurrent_duplicate_and_unique_appends_leave_one_linear_chain(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)

    def same_event(_index: int) -> context_runtime.CaptureResult:
        return _seed_event(root, 0)

    with ThreadPoolExecutor(max_workers=8) as executor:
        duplicate_results = list(executor.map(same_event, range(8)))
    assert [result.status for result in duplicate_results].count("appended") == 1
    assert [result.status for result in duplicate_results].count("duplicate") == 7
    assert len({result.event_id for result in duplicate_results}) == 1

    with ThreadPoolExecutor(max_workers=8) as executor:
        unique_results = list(executor.map(lambda index: _seed_event(root, index), range(1, 9)))
    assert all(result.status == "appended" for result in unique_results)
    verification = context_runtime.verify_context_fabric(root)
    assert verification["event_count"] == 9


def test_producer_projection_and_run_receipt_roll_back_atomically_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    event = _seed_event(root)
    original_append = completion_module.fabric.append_projection

    def append_then_crash(
        spec: object, *, root: Path, _connection: sqlite3.Connection | None = None
    ) -> object:
        original_append(spec, root=root, _connection=_connection)
        raise RuntimeError("simulated crash after projection commit")

    monkeypatch.setattr(completion_module.fabric, "append_projection", append_then_crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        context_runtime.run_projection_producers(
            root=root,
            through_seq=event.seq,
            producer_ids=["s.context_runtime.current_seed"],
        )
    with sqlite3.connect(_database(root)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM projection_metadata WHERE automatic=1"
        ).fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM projection_runs").fetchone() == (0,)
    assert context_runtime.verify_context_fabric(root)["projection_runs_verified"] == 0

    monkeypatch.setattr(completion_module.fabric, "append_projection", original_append)
    retry = context_runtime.run_projection_producers(
        root=root,
        through_seq=event.seq,
        producer_ids=["s.context_runtime.current_seed"],
    )
    assert retry["status"] == "appended"
    assert len(retry["projection_ids"]) == 1
    assert context_runtime.verify_context_fabric(root)["projection_runs_verified"] == 1


def test_concurrent_identical_producer_runs_return_appended_then_duplicates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "concurrent-identical-producer"
    context_runtime.initialize_context_fabric(root)
    event = _seed_event(root)
    worker_count = 8
    gate = threading.Barrier(worker_count)

    def run_identical(_index: int) -> dict[str, object]:
        gate.wait(timeout=5)
        return context_runtime.run_projection_producers(
            root=root,
            through_seq=event.seq,
            producer_ids=["s.context_runtime.current_seed"],
        )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(run_identical, range(worker_count)))

    statuses = [str(result["status"]) for result in results]
    assert statuses.count("appended") == 1
    assert statuses.count("duplicate") == worker_count - 1
    assert len({str(result["run_id"]) for result in results}) == 1
    assert len({tuple(result["projection_ids"]) for result in results}) == 1
    verification = context_runtime.verify_context_fabric(root)
    assert verification["projections_verified"] == 1
    assert verification["projection_runs_verified"] == 1


def test_a_later_trigger_never_inherits_output_from_a_failed_atomic_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    first_event = _seed_event(root)
    original_append = completion_module.fabric.append_projection

    def append_then_crash(
        spec: object, *, root: Path, _connection: sqlite3.Connection | None = None
    ) -> object:
        original_append(spec, root=root, _connection=_connection)
        raise RuntimeError("first trigger failed before receipt")

    monkeypatch.setattr(completion_module.fabric, "append_projection", append_then_crash)
    with pytest.raises(RuntimeError, match="first trigger failed"):
        context_runtime.run_projection_producers(
            root=root,
            trigger_event_id=first_event.event_id,
            producer_ids=["s.context_runtime.current_seed"],
        )
    monkeypatch.setattr(completion_module.fabric, "append_projection", original_append)
    second_event = _seed_event(root, 1)
    second = context_runtime.run_projection_producers(
        root=root,
        trigger_event_id=second_event.event_id,
        producer_ids=["s.context_runtime.current_seed"],
    )
    assert second["status"] == "appended"
    with sqlite3.connect(_database(root)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM projection_metadata WHERE automatic=1"
        ).fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM projection_runs").fetchone() == (1,)
    assert context_runtime.verify_context_fabric(root)["projection_runs_verified"] == 1


def test_snapshot_and_restore_refuse_nonempty_targets_without_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    _seed_event(root)
    occupied_snapshot = tmp_path / "occupied-snapshot"
    occupied_snapshot.mkdir()
    snapshot_sentinel = occupied_snapshot / "keep.txt"
    snapshot_sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(context_runtime.ContextFabricError, match="new|empty|non-link"):
        context_runtime.create_snapshot(occupied_snapshot, root=root)
    assert snapshot_sentinel.read_text(encoding="utf-8") == "keep"

    snapshot = tmp_path / "snapshot"
    context_runtime.create_snapshot(snapshot, root=root)
    occupied_restore = tmp_path / "occupied-restore"
    occupied_restore.mkdir()
    restore_sentinel = occupied_restore / "keep.txt"
    restore_sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(context_runtime.ContextFabricError, match="empty|overwrite"):
        context_runtime.restore_snapshot(snapshot, occupied_restore)
    assert restore_sentinel.read_text(encoding="utf-8") == "keep"
    assert not (occupied_restore / "restore.complete.v1.json").exists()


def test_snapshot_output_and_restore_target_refuse_directory_links(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    _seed_event(root)
    snapshot_link_target = tmp_path / "snapshot-link-target"
    snapshot_link_target.mkdir()
    snapshot_link = tmp_path / "snapshot-link"
    _directory_link_or_skip(snapshot_link, snapshot_link_target)
    with pytest.raises(context_runtime.ContextFabricError, match="link|junction|directory"):
        context_runtime.create_snapshot(snapshot_link, root=root)

    snapshot = tmp_path / "snapshot"
    context_runtime.create_snapshot(snapshot, root=root)
    restore_link_target = tmp_path / "restore-link-target"
    restore_link_target.mkdir()
    restore_link = tmp_path / "restore-link"
    _directory_link_or_skip(restore_link, restore_link_target)
    with pytest.raises(context_runtime.ContextFabricError, match="link|junction|directory"):
        context_runtime.restore_snapshot(snapshot, restore_link)
    assert not (restore_link_target / "context_fabric.sqlite3").exists()


def test_restore_rejects_snapshot_root_link_instead_of_resolving_it(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    _seed_event(root)
    snapshot = tmp_path / "snapshot"
    context_runtime.create_snapshot(snapshot, root=root)
    snapshot_alias = tmp_path / "snapshot-alias"
    _directory_link_or_skip(snapshot_alias, snapshot)
    target = tmp_path / "restore-target"
    with pytest.raises(context_runtime.ContextFabricError, match="link|redirect"):
        context_runtime.restore_snapshot(snapshot_alias, target)
    assert not target.exists()


def test_restore_rejects_manifest_database_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    _seed_event(root)
    snapshot = tmp_path / "snapshot"
    result = context_runtime.create_snapshot(snapshot, root=root)
    escaped = tmp_path / "escaped-manifest"
    escaped.mkdir()
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    manifest["database"] = "../snapshot/context_fabric.sqlite3"
    (escaped / "snapshot.v2.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    target = tmp_path / "restore-target"
    with pytest.raises(context_runtime.ContextFabricError, match="escape|contain|path|snapshot"):
        context_runtime.restore_snapshot(escaped, target)
    assert not target.exists()


def test_restore_rejects_manifest_artifact_identity_not_present_in_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    context_runtime.admit_artifact(
        b"sanitized exact inventory member",
        kind="completed_tool_result",
        media_type="text/plain",
        source_locator="security-test:snapshot-inventory",
        source_record_sha256="c" * 64,
        storage_policy="exact",
        sanitized=True,
        producer_id="s.context_runtime.explicit_sanitizer",
        producer_version="v1",
        root=root,
    )
    snapshot = tmp_path / "snapshot"
    result = context_runtime.create_snapshot(snapshot, root=root)
    manifest_path = Path(str(result["manifest_path"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["artifacts"]) == 1
    manifest["artifacts"][0]["artifact_id"] = "art_" + ("f" * 64)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    target = tmp_path / "restore-target"
    with pytest.raises(context_runtime.ContextFabricError, match="artifact|inventory|database"):
        context_runtime.restore_snapshot(snapshot, target)
    assert not target.exists() or not any(target.iterdir())


def test_snapshot_restores_hash_only_artifact_row_without_inventing_a_blob(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fabric"
    context_runtime.initialize_context_fabric(root)
    artifact = context_runtime.admit_artifact(
        b"tool output retained only by digest",
        kind="completed_tool_result",
        media_type="text/plain",
        source_locator="security-test:hash-only-snapshot",
        source_record_sha256="d" * 64,
        storage_policy="hash_only",
        root=root,
    )
    snapshot = tmp_path / "snapshot"
    result = context_runtime.create_snapshot(snapshot, root=root)
    manifest = json.loads(Path(str(result["manifest_path"])).read_text(encoding="utf-8"))
    assert artifact["artifact_id"] not in {
        str(item["artifact_id"]) for item in manifest["artifacts"]
    }

    restored = tmp_path / "restored"
    context_runtime.restore_snapshot(snapshot, restored)
    assert context_runtime.verify_context_fabric(restored)["artifacts_verified"] == 1
    with sqlite3.connect(_database(restored)) as connection:
        row = connection.execute(
            "SELECT storage_kind,blob_relpath,content_sha256 FROM artifacts WHERE artifact_id=?",
            (artifact["artifact_id"],),
        ).fetchone()
    assert row == ("hash_only", "", artifact["content_sha256"])
    assert not (restored / "blobs").exists()
