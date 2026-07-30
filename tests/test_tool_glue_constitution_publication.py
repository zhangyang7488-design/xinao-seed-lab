from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest
from xinao.tool_glue import publication


class RecordingRunner:
    def __init__(
        self,
        *,
        fail_once_on: str | None = None,
        fail_always_on: str | None = None,
        after_success: Callable[[list[str], dict[str, object]], None] | None = None,
    ) -> None:
        self.commands: list[list[str]] = []
        self.fail_once_on = fail_once_on
        self.fail_always_on = fail_always_on
        self.after_success = after_success
        self.failed = False

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        materialized = list(command)
        self.commands.append(materialized)
        should_fail_once = (
            self.fail_once_on is not None and self.fail_once_on in materialized and not self.failed
        )
        should_fail = should_fail_once or (
            self.fail_always_on is not None and self.fail_always_on in materialized
        )
        if should_fail_once:
            self.failed = True
        if should_fail:
            return subprocess.CompletedProcess(materialized, 17, "", "injected failure")
        receipt = self._receipt(materialized)
        if self.after_success is not None:
            self.after_success(materialized, receipt)
        return subprocess.CompletedProcess(materialized, 0, json.dumps(receipt), "")

    @staticmethod
    def _receipt(command: list[str]) -> dict[str, object]:
        if "--authority-path" in command:
            authority = Path(command[command.index("--authority-path") + 1]).resolve()
            expected_sha256 = command[command.index("--expected-sha256") + 1]
            expected_version = command[command.index("--expected-version") + 1]
            invariant_required = "--legacy-preimage-readback" not in command
            return {
                "schema_version": "xinao.tool_glue_constitution_consumer_readback.v1",
                "status": publication.VERIFIED,
                "authority_path": str(authority),
                "authority_sha256": expected_sha256,
                "authority_size_bytes": authority.stat().st_size,
                "constitution_version": expected_version,
                "maturation_invariant_verified": invariant_required,
                "semantic_anchors": (
                    ["XINAO_NECESSARY_CHAIN_MATURATION_INVARIANT"] if invariant_required else []
                ),
                "completion_claim_allowed": False,
            }
        if any(Path(part).name == "refresh.ps1" for part in command):
            expected_sha256 = command[command.index("-ExpectedSoftwareFoundationSha256") + 1]
            expected_version = command[command.index("-ExpectedSoftwareFoundationVersion") + 1]
            return {
                "schema_version": "xinao.mainline_projection_refresh.v1",
                "authority_text_mutated": False,
                "projection_bindings": {
                    "software_foundation_path": str(
                        Path(r"C:\Users\xx363\Desktop\主线\工具胶水宪法")
                        / "软件工具胶水宪法_当前有效.txt"
                    ),
                    "software_foundation_sha256": expected_sha256,
                    "software_foundation_version": expected_version,
                },
            }
        return {
            "schema_version": ("xinao.codex_situation_island_context_architecture_verification.v4"),
            "ready": True,
            "failed": [],
            "sentinel": "SENTINEL:XINAO_CODEX_SITUATION_ISLAND_CONTEXT_ARCHITECTURE_READY_V4",
        }


@pytest.fixture(autouse=True)
def _isolate_canonical_guard_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publication, "DEFAULT_GUARD_ROOT", tmp_path / "canonical-guards")


def _write(path: Path, raw: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _bindings(tmp_path: Path) -> publication.PublicationBindings:
    bindings_root = tmp_path / "bindings"
    return publication.PublicationBindings(
        pwsh_path=_write(bindings_root / "pwsh.exe", b"pwsh binding"),
        updater_path=_write(bindings_root / "refresh.ps1", b"refresh binding"),
        verifier_path=_write(bindings_root / "selftest.ps1", b"selftest binding"),
        python_path=_write(bindings_root / "python.exe", b"python binding"),
        consumer_path=_write(bindings_root / "consumer.py", b"consumer binding"),
    ).resolved()


def _hash(raw: bytes) -> str:
    return publication.sha256_bytes(raw)


def _old_document(label: str = "old") -> bytes:
    return f"软件工具胶水宪法｜当前有效\n版本：v3.3\n{label}\n".encode()


def _new_document(label: str = "new") -> bytes:
    return (
        "软件工具胶水宪法｜当前有效\n"
        "版本：v3.4\n"
        "## 4. 父级持续成熟化不变量的工程兑现与成熟实现准入\n"
        "XINAO_NECESSARY_CHAIN_MATURATION_INVARIANT\n"
        "bounded_probe_not_yet_maturable -> MATURATION_REQUIRED\n"
        "真实消费者调用；fresh-process 发现。\n"
        "晋升后的默认路径不得静默退化，也不得创建第二控制面。\n"
        f"{label}\n"
    ).encode()


def test_default_python_binding_uses_stable_base_interpreter() -> None:
    expected = Path(getattr(sys, "_base_executable", None) or sys.executable).resolve()
    assert publication.discover_python() == expected
    assert expected.is_file()


def test_default_updater_is_si_operational_entry_not_parents_walk() -> None:
    from xinao.tool_glue.canonical_paths import (
        DEFAULT_OPERATIONAL_UPDATER_PATH,
        discover_canonical_updater_path,
    )

    # Production default is the SI operational consumer entry, never parents[N].
    assert publication.DEFAULT_UPDATER_PATH == DEFAULT_OPERATIONAL_UPDATER_PATH
    source = Path(publication.__file__).read_text(encoding="utf-8")
    assert ".parents[" not in source
    # Canonical source is package-local and present in this checkout.
    canonical = discover_canonical_updater_path()
    assert canonical.is_file()
    assert canonical.name == "Update-CodexContextCatalog.ps1"
    assert "tool_glue" in canonical.parts
    assert "resources" in canonical.parts
    # Formally selected replacement verifier is package-local.
    assert publication.DEFAULT_VERIFIER_PATH.is_file()
    assert publication.DEFAULT_VERIFIER_PATH.name == "projection_binding_verifier.py"
    assert publication.discover_consumer_path().is_file()


def test_projection_refresh_receipt_requires_software_foundation_version() -> None:
    authority = Path(r"C:\Users\xx363\Desktop\主线\工具胶水宪法\软件工具胶水宪法_当前有效.txt")
    with pytest.raises(publication.PublicationError) as raised:
        publication._validate_receipt_payload(
            name="projection_refresh",
            receipt={
                "schema_version": "xinao.mainline_projection_refresh.v1",
                "authority_text_mutated": False,
                "projection_bindings": {
                    "software_foundation_path": str(authority),
                    "software_foundation_sha256": "a" * 64,
                    # version deliberately omitted — sha-only refresh is not enough
                },
            },
            authority_path=authority,
            expected_sha256="a" * 64,
            expected_version="v3.4",
            legacy_preimage_readback=False,
        )
    assert raised.value.code == "POSTFLIGHT_RECEIPT_INVALID"


def test_projection_refresh_receipt_binds_version_with_sha() -> None:
    authority = Path(r"C:\Users\xx363\Desktop\主线\工具胶水宪法\软件工具胶水宪法_当前有效.txt")
    publication._validate_receipt_payload(
        name="projection_refresh",
        receipt={
            "schema_version": "xinao.mainline_projection_refresh.v1",
            "authority_text_mutated": False,
            "projection_bindings": {
                "software_foundation_path": str(authority),
                "software_foundation_sha256": "b" * 64,
                "software_foundation_version": "v3.4",
            },
        },
        authority_path=authority,
        expected_sha256="b" * 64,
        expected_version="v3.4",
        legacy_preimage_readback=False,
    )


def _materialize_transaction(
    *,
    state_root: Path,
    authority_path: Path,
    old_raw: bytes,
    new_raw: bytes,
    status: str,
    bindings: publication.PublicationBindings,
    transaction_id: str,
) -> Path:
    old_digest = _hash(old_raw)
    new_digest = _hash(new_raw)
    preimage = publication._seal_archive_bytes(state_root, "preimages", old_raw, old_digest)
    candidate = publication._seal_archive_bytes(state_root, "candidates", new_raw, new_digest)
    consumer_raw = bindings.consumer_path.read_bytes()
    consumer_digest = _hash(consumer_raw)
    durable_consumer = publication._seal_archive_bytes(
        state_root, "consumers", consumer_raw, consumer_digest
    )
    effective_bindings = publication.PublicationBindings(
        pwsh_path=bindings.pwsh_path,
        updater_path=bindings.updater_path,
        verifier_path=bindings.verifier_path,
        python_path=bindings.python_path,
        consumer_path=durable_consumer,
    )
    journal_path = publication._journal_path(state_root, transaction_id).resolve()
    journal = {
        "schema_version": publication.JOURNAL_SCHEMA,
        "transaction_id": transaction_id,
        "status": status,
        "authority_path": str(authority_path.resolve()),
        "authority_binding_sha256": publication._path_binding_sha256(authority_path),
        "expected_old_sha256": old_digest,
        "expected_new_sha256": new_digest,
        "old_document_version": publication._document_version(old_raw),
        "new_document_version": publication._document_version(new_raw),
        "candidate_source_path": str(state_root / "source.txt"),
        "candidate_archive_path": str(candidate),
        "preimage_archive_path": str(preimage),
        "postflight_bindings": publication._binding_snapshot(effective_bindings),
        "authority_metadata": publication._capture_file_metadata(authority_path),
        "candidate_preflight": [
            {
                "name": "fresh_subprocess_candidate_preflight",
                "returncode": 0,
                "receipt": {
                    "schema_version": ("xinao.tool_glue_constitution_consumer_readback.v1"),
                    "status": publication.VERIFIED,
                    "authority_path": str(candidate.resolve()),
                    "authority_sha256": new_digest,
                    "authority_size_bytes": len(new_raw),
                    "constitution_version": publication._document_version(new_raw),
                    "maturation_invariant_verified": True,
                    "semantic_anchors": ["XINAO_NECESSARY_CHAIN_MATURATION_INVARIANT"],
                    "completion_claim_allowed": False,
                },
            }
        ],
        "completion_claim_allowed": False,
    }
    publication._write_json_atomic(journal_path, journal)
    publication._write_json_atomic(
        publication._marker_path(state_root),
        publication._marker_payload(authority_path, journal_path, journal),
    )
    return journal_path


def test_publish_seals_cas_and_verifies_all_postflight_steps(tmp_path: Path) -> None:
    old_raw = _old_document("tool glue v1")
    new_raw = _new_document("tool glue v2")
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    runner = RecordingRunner()

    result = publication.publish_tool_glue_constitution(
        candidate_path=candidate,
        expected_old_sha256=_hash(old_raw),
        expected_new_sha256=_hash(new_raw),
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=runner,
        transaction_id="publish-success",
    )

    assert result["status"] == publication.VERIFIED
    assert result["completion_claim_allowed"] is False
    assert authority.read_bytes() == new_raw
    assert len(runner.commands) == 4
    assert [item["name"] for item in result["postflight"]] == [
        "projection_refresh",
        "projection_selftest",
        "fresh_subprocess_consumer",
    ]
    assert Path(result["candidate_archive_path"]).read_bytes() == new_raw
    assert Path(result["preimage_archive_path"]).read_bytes() == old_raw
    journal = json.loads(Path(result["transaction_journal"]).read_text(encoding="utf-8"))
    assert journal["status"] == publication.VERIFIED
    durable_consumer = Path(journal["postflight_bindings"]["consumer"]["path"])
    assert durable_consumer.is_file()
    assert durable_consumer != bindings.consumer_path
    assert Path(runner.commands[0][1]) == durable_consumer
    assert Path(runner.commands[3][1]) == durable_consumer
    assert "--expected-version" in runner.commands[3]
    assert "v3.4" in runner.commands[3]
    assert "--legacy-preimage-readback" not in runner.commands[3]
    assert not publication._marker_path(state_root).exists()


def test_expected_hashes_are_rechecked_after_exclusive_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_raw = _old_document()
    new_raw = _new_document()
    drifted_raw = b"outside-writer"
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", new_raw)
    bindings = _bindings(tmp_path)

    @contextmanager
    def drift_before_locked_recheck(_state_root: Path):
        authority.write_bytes(drifted_raw)
        yield

    monkeypatch.setattr(publication, "_publication_lease", drift_before_locked_recheck)
    with pytest.raises(publication.PublicationError) as raised:
        publication.publish_tool_glue_constitution(
            candidate_path=candidate,
            expected_old_sha256=_hash(old_raw),
            expected_new_sha256=_hash(new_raw),
            authority_path=authority,
            state_root=tmp_path / "state",
            bindings=bindings,
            command_runner=RecordingRunner(),
        )

    assert raised.value.code == "EXPECTED_OLD_MISMATCH_AFTER_LOCK"
    assert raised.value.receipt["completion_claim_allowed"] is False
    assert authority.read_bytes() == drifted_raw


@pytest.mark.parametrize(
    "status", [publication.PREPARED, publication.APPLYING, publication.ROLLING_BACK]
)
def test_recover_rollback_states_converge_to_old_without_hard_exit(
    tmp_path: Path, status: str
) -> None:
    old_raw = _old_document("old durable value")
    new_raw = _new_document("new durable value")
    installed_raw = old_raw if status == publication.PREPARED else new_raw
    authority = _write(tmp_path / "authority.txt", installed_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    journal_path = _materialize_transaction(
        state_root=state_root,
        authority_path=authority,
        old_raw=old_raw,
        new_raw=new_raw,
        status=status,
        bindings=bindings,
        transaction_id=f"recover-{status.lower()}",
    )
    runner = RecordingRunner()

    result = publication.recover_tool_glue_constitution(
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=runner,
    )

    assert result["status"] == publication.ROLLED_BACK_VERIFIED
    assert authority.read_bytes() == old_raw
    assert len(runner.commands) == 3
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (
        publication.ROLLED_BACK_VERIFIED
    )
    assert not publication._marker_path(state_root).exists()


def test_recover_authority_applied_resumes_postflight(tmp_path: Path) -> None:
    old_raw = _old_document("old authority")
    new_raw = _new_document("new authority")
    authority = _write(tmp_path / "authority.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    journal_path = _materialize_transaction(
        state_root=state_root,
        authority_path=authority,
        old_raw=old_raw,
        new_raw=new_raw,
        status=publication.AUTHORITY_APPLIED,
        bindings=bindings,
        transaction_id="resume-postflight",
    )
    runner = RecordingRunner()

    result = publication.recover_tool_glue_constitution(
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=runner,
    )

    assert result["status"] == publication.VERIFIED
    assert authority.read_bytes() == new_raw
    assert len(runner.commands) == 3
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (publication.VERIFIED)


def test_authority_applied_postflight_failure_keeps_new_and_marker_for_retry(
    tmp_path: Path,
) -> None:
    old_raw = _old_document("old authority")
    new_raw = _new_document("new authority")
    authority = _write(tmp_path / "authority.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    journal_path = _materialize_transaction(
        state_root=state_root,
        authority_path=authority,
        old_raw=old_raw,
        new_raw=new_raw,
        status=publication.AUTHORITY_APPLIED,
        bindings=bindings,
        transaction_id="postflight-retry",
    )
    runner = RecordingRunner(fail_once_on=str(bindings.verifier_path))

    with pytest.raises(publication.PublicationError) as raised:
        publication.recover_tool_glue_constitution(
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=runner,
        )

    assert raised.value.code == "POSTFLIGHT_FAILED"
    assert raised.value.receipt["completion_claim_allowed"] is False
    assert authority.read_bytes() == new_raw
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (
        publication.AUTHORITY_APPLIED
    )
    assert publication._marker_path(state_root).is_file()

    recovered = publication.recover_tool_glue_constitution(
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=runner,
    )
    assert recovered["status"] == publication.VERIFIED
    assert authority.read_bytes() == new_raw
    assert not publication._marker_path(state_root).exists()


def test_recovery_fails_closed_on_postflight_binding_drift(tmp_path: Path) -> None:
    old_raw = _old_document("old authority")
    new_raw = _new_document("new authority")
    authority = _write(tmp_path / "authority.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    journal_path = _materialize_transaction(
        state_root=state_root,
        authority_path=authority,
        old_raw=old_raw,
        new_raw=new_raw,
        status=publication.AUTHORITY_APPLIED,
        bindings=bindings,
        transaction_id="binding-drift",
    )
    bindings.verifier_path.write_bytes(b"drifted verifier")

    with pytest.raises(publication.PublicationError) as raised:
        publication.recover_tool_glue_constitution(
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=RecordingRunner(),
        )

    assert raised.value.code == "BINDING_DRIFT"
    assert authority.read_bytes() == new_raw
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (
        publication.AUTHORITY_APPLIED
    )
    assert publication._marker_path(state_root).is_file()


def test_recovery_fails_closed_when_target_matches_neither_old_nor_new(
    tmp_path: Path,
) -> None:
    old_raw = _old_document("old authority")
    new_raw = _new_document("new authority")
    unrelated_raw = b"unrelated authority"
    authority = _write(tmp_path / "authority.txt", unrelated_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    journal_path = _materialize_transaction(
        state_root=state_root,
        authority_path=authority,
        old_raw=old_raw,
        new_raw=new_raw,
        status=publication.APPLYING,
        bindings=bindings,
        transaction_id="target-drift",
    )

    with pytest.raises(publication.PublicationError) as raised:
        publication.recover_tool_glue_constitution(
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=RecordingRunner(),
        )

    assert raised.value.code == "AUTHORITY_TARGET_DRIFT"
    assert authority.read_bytes() == unrelated_raw
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (publication.APPLYING)
    assert publication._marker_path(state_root).is_file()


def test_recovery_rejects_forged_verified_state_without_postflight_evidence(
    tmp_path: Path,
) -> None:
    old_raw = _old_document("old authority")
    new_raw = _new_document("new authority")
    authority = _write(tmp_path / "authority.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    journal_path = _materialize_transaction(
        state_root=state_root,
        authority_path=authority,
        old_raw=old_raw,
        new_raw=new_raw,
        status=publication.VERIFIED,
        bindings=bindings,
        transaction_id="forged-verified",
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["postflight"] = [
        {"name": "projection_refresh", "returncode": 0},
        {"name": "projection_selftest", "returncode": 0},
        {"name": "fresh_subprocess_consumer", "returncode": 0},
    ]
    journal["postflight_final_authority_sha256"] = _hash(new_raw)
    publication._write_json_atomic(journal_path, journal)

    with pytest.raises(publication.PublicationError) as raised:
        publication.recover_tool_glue_constitution(
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=RecordingRunner(),
        )

    assert raised.value.code == "POSTFLIGHT_EVIDENCE_INVALID"
    assert authority.read_bytes() == new_raw
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (publication.VERIFIED)
    assert publication._marker_path(state_root).is_file()


def test_persistent_postflight_failure_keeps_new_and_marker_for_recovery(
    tmp_path: Path,
) -> None:
    old_raw = _old_document()
    new_raw = _new_document()
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    runner = RecordingRunner(fail_always_on=str(bindings.verifier_path))

    with pytest.raises(publication.PublicationError) as raised:
        publication.publish_tool_glue_constitution(
            candidate_path=candidate,
            expected_old_sha256=_hash(old_raw),
            expected_new_sha256=_hash(new_raw),
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=runner,
            transaction_id="postflight-failure",
        )

    assert raised.value.receipt["completion_claim_allowed"] is False
    assert authority.read_bytes() == new_raw
    journal = json.loads(
        (state_root / "transactions" / "postflight-failure" / "transaction.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["status"] == publication.AUTHORITY_APPLIED
    assert publication._marker_path(state_root).is_file()

    recovered = publication.recover_tool_glue_constitution(
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=RecordingRunner(),
    )
    assert recovered["status"] == publication.VERIFIED
    assert authority.read_bytes() == new_raw
    assert not publication._marker_path(state_root).exists()


def test_publish_retries_fail_once_postflight_from_authority_applied(
    tmp_path: Path,
) -> None:
    old_raw = _old_document()
    new_raw = _new_document()
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    runner = RecordingRunner(fail_once_on=str(bindings.verifier_path))

    result = publication.publish_tool_glue_constitution(
        candidate_path=candidate,
        expected_old_sha256=_hash(old_raw),
        expected_new_sha256=_hash(new_raw),
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=runner,
        transaction_id="postflight-fail-once",
    )

    assert result["status"] == publication.VERIFIED
    assert result["authority_sha256"] == _hash(new_raw)
    assert authority.read_bytes() == new_raw
    assert not publication._marker_path(state_root).exists()


def test_verified_marker_cleanup_failure_never_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_raw = _old_document()
    new_raw = _new_document()
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    real_remove = publication._remove_marker
    calls = 0

    def fail_first_cleanup(marker_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected marker cleanup failure")
        real_remove(marker_path)

    monkeypatch.setattr(publication, "_remove_marker", fail_first_cleanup)
    result = publication.publish_tool_glue_constitution(
        candidate_path=candidate,
        expected_old_sha256=_hash(old_raw),
        expected_new_sha256=_hash(new_raw),
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=RecordingRunner(),
        transaction_id="verified-cleanup-failure",
    )

    assert calls == 2
    assert result["status"] == publication.VERIFIED
    assert authority.read_bytes() == new_raw
    journal = json.loads(Path(result["transaction_journal"]).read_text(encoding="utf-8"))
    assert journal["status"] == publication.VERIFIED
    assert journal["postflight_final_authority_sha256"] == _hash(new_raw)
    assert not publication._marker_path(state_root).exists()


def test_authority_keyed_guard_excludes_different_state_roots(tmp_path: Path) -> None:
    authority = _write(tmp_path / "authority.txt", _old_document())
    first_state_root = tmp_path / "state-a"
    second_state_root = tmp_path / "state-b"

    assert publication._guard_path(authority) == publication._guard_path(
        authority.parent / "." / authority.name
    )
    with publication._publication_lease(authority):
        with pytest.raises(publication.PublicationError) as raised:
            publication.recover_tool_glue_constitution(
                authority_path=authority,
                state_root=second_state_root,
                bindings=_bindings(tmp_path),
                command_runner=RecordingRunner(),
            )

    assert raised.value.code == "LEASE_HELD"
    assert not publication._marker_path(first_state_root).exists()
    assert not publication._marker_path(second_state_root).exists()


def test_journal_without_marker_is_discovered_and_recovered(tmp_path: Path) -> None:
    old_raw = _old_document("journal orphan old")
    new_raw = _new_document("journal orphan new")
    authority = _write(tmp_path / "authority.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    journal_path = _materialize_transaction(
        state_root=state_root,
        authority_path=authority,
        old_raw=old_raw,
        new_raw=new_raw,
        status=publication.APPLYING,
        bindings=bindings,
        transaction_id="journal-without-marker",
    )
    publication._marker_path(state_root).unlink()

    result = publication.recover_tool_glue_constitution(
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=RecordingRunner(),
    )

    assert result["status"] == publication.ROLLED_BACK_VERIFIED
    assert authority.read_bytes() == old_raw
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (
        publication.ROLLED_BACK_VERIFIED
    )
    assert not publication._marker_path(state_root).exists()


def test_marker_without_journal_rebuilds_snapshot_and_recovers(tmp_path: Path) -> None:
    old_raw = _old_document("marker orphan old")
    new_raw = _new_document("marker orphan new")
    authority = _write(tmp_path / "authority.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    journal_path = _materialize_transaction(
        state_root=state_root,
        authority_path=authority,
        old_raw=old_raw,
        new_raw=new_raw,
        status=publication.APPLYING,
        bindings=bindings,
        transaction_id="marker-without-journal",
    )
    journal_path.unlink()

    result = publication.recover_tool_glue_constitution(
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=RecordingRunner(),
    )

    assert result["status"] == publication.ROLLED_BACK_VERIFIED
    assert authority.read_bytes() == old_raw
    rebuilt = json.loads(journal_path.read_text(encoding="utf-8"))
    assert rebuilt["status"] == publication.ROLLED_BACK_VERIFIED
    assert not publication._marker_path(state_root).exists()


def test_applying_recovery_restores_old_before_live_binding_validation(
    tmp_path: Path,
) -> None:
    old_raw = _old_document("old before binding drift")
    new_raw = _new_document("new before binding drift")
    authority = _write(tmp_path / "authority.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    journal_path = _materialize_transaction(
        state_root=state_root,
        authority_path=authority,
        old_raw=old_raw,
        new_raw=new_raw,
        status=publication.APPLYING,
        bindings=bindings,
        transaction_id="restore-before-binding-check",
    )
    bindings.verifier_path.write_bytes(b"drifted verifier")

    with pytest.raises(publication.PublicationError) as raised:
        publication.recover_tool_glue_constitution(
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=RecordingRunner(),
        )

    assert raised.value.code == "BINDING_DRIFT"
    assert authority.read_bytes() == old_raw
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (
        publication.ROLLING_BACK
    )
    assert publication._marker_path(state_root).is_file()


def test_candidate_semantics_fail_before_authority_or_projection_mutation(
    tmp_path: Path,
) -> None:
    old_raw = _old_document()
    malformed_new = _new_document().replace(b"MATURATION_REQUIRED", b"MISSING_REQUIREMENT")
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", malformed_new)
    state_root = tmp_path / "state"
    dummy = _bindings(tmp_path)
    consumer = Path(__file__).resolve().parents[1] / "scripts" / "verify_tool_glue_consumer.py"
    bindings = publication.PublicationBindings(
        pwsh_path=dummy.pwsh_path,
        updater_path=dummy.updater_path,
        verifier_path=dummy.verifier_path,
        python_path=Path(sys.executable),
        consumer_path=consumer,
    )

    with pytest.raises(publication.PublicationError) as raised:
        publication.publish_tool_glue_constitution(
            candidate_path=candidate,
            expected_old_sha256=_hash(old_raw),
            expected_new_sha256=_hash(malformed_new),
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            transaction_id="semantic-preflight-failure",
        )

    assert raised.value.code == "CANDIDATE_PREFLIGHT_FAILED"
    assert authority.read_bytes() == old_raw
    assert not publication._marker_path(state_root).exists()
    assert not (state_root / "transactions").exists()


def test_final_physical_rehash_rejects_postflight_authority_drift(tmp_path: Path) -> None:
    old_raw = _old_document()
    new_raw = _new_document()
    drifted_raw = b"external postflight drift"
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)

    def drift_after_live_consumer(command: list[str], _receipt: dict[str, object]) -> None:
        if "--authority-path" not in command:
            return
        observed = Path(command[command.index("--authority-path") + 1]).resolve()
        if observed == authority.resolve():
            authority.write_bytes(drifted_raw)

    with pytest.raises(publication.PublicationError) as raised:
        publication.publish_tool_glue_constitution(
            candidate_path=candidate,
            expected_old_sha256=_hash(old_raw),
            expected_new_sha256=_hash(new_raw),
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=RecordingRunner(after_success=drift_after_live_consumer),
            transaction_id="final-physical-drift",
        )

    assert raised.value.code == "FINAL_AUTHORITY_HASH_MISMATCH"
    assert authority.read_bytes() == drifted_raw
    journal = json.loads(
        (state_root / "transactions" / "final-physical-drift" / "transaction.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["status"] == publication.AUTHORITY_APPLIED
    assert publication._marker_path(state_root).is_file()


def test_authority_metadata_is_journaled_and_preserved(tmp_path: Path) -> None:
    old_raw = _old_document()
    new_raw = _new_document()
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    original_windows_attributes: int | None = None
    if os.name == "nt":
        current_windows_attributes = publication._get_windows_file_attributes(authority)
        original_windows_attributes = current_windows_attributes
        publication._set_windows_file_attributes(authority, current_windows_attributes | 0x2)
    authority.chmod(0o444)
    expected_metadata = publication._capture_file_metadata(authority)

    try:
        published = publication.publish_tool_glue_constitution(
            candidate_path=candidate,
            expected_old_sha256=_hash(old_raw),
            expected_new_sha256=_hash(new_raw),
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=RecordingRunner(),
            transaction_id="metadata-preserved",
        )
        journal = json.loads(Path(published["transaction_journal"]).read_text(encoding="utf-8"))
        assert journal["authority_metadata"] == expected_metadata
        assert publication._capture_file_metadata(authority) == expected_metadata

        rolled_back = publication.rollback_tool_glue_constitution(
            journal_path=Path(published["transaction_journal"]),
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=RecordingRunner(),
        )
        assert rolled_back["status"] == publication.ROLLED_BACK_VERIFIED
        assert publication._capture_file_metadata(authority) == expected_metadata
        assert authority.read_bytes() == old_raw
    finally:
        if authority.exists():
            if os.name == "nt":
                assert original_windows_attributes is not None
                publication._set_windows_file_attributes(
                    authority, original_windows_attributes & ~0x1
                )
            authority.chmod(0o666)


def test_explicit_rollback_requires_exact_new_hash(tmp_path: Path) -> None:
    old_raw = _old_document()
    new_raw = _new_document()
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    published = publication.publish_tool_glue_constitution(
        candidate_path=candidate,
        expected_old_sha256=_hash(old_raw),
        expected_new_sha256=_hash(new_raw),
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=RecordingRunner(),
        transaction_id="rollback-drift",
    )
    authority.write_bytes(b"unrelated third value")

    with pytest.raises(publication.PublicationError) as raised:
        publication.rollback_tool_glue_constitution(
            journal_path=Path(published["transaction_journal"]),
            authority_path=authority,
            state_root=state_root,
            bindings=bindings,
            command_runner=RecordingRunner(),
        )

    assert raised.value.code == "ROLLBACK_TARGET_NOT_NEW"
    assert authority.read_bytes() == b"unrelated third value"
    journal = json.loads(Path(published["transaction_journal"]).read_text(encoding="utf-8"))
    assert journal["status"] == publication.VERIFIED


def test_explicit_rollback_refreshes_and_verifies_old_consumer(tmp_path: Path) -> None:
    old_raw = _old_document()
    new_raw = _new_document()
    authority = _write(tmp_path / "authority.txt", old_raw)
    candidate = _write(tmp_path / "candidate.txt", new_raw)
    state_root = tmp_path / "state"
    bindings = _bindings(tmp_path)
    published = publication.publish_tool_glue_constitution(
        candidate_path=candidate,
        expected_old_sha256=_hash(old_raw),
        expected_new_sha256=_hash(new_raw),
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=RecordingRunner(),
        transaction_id="rollback-success",
    )
    runner = RecordingRunner()
    candidate.unlink()
    bindings.consumer_path.unlink()

    result = publication.rollback_tool_glue_constitution(
        journal_path=Path(published["transaction_journal"]),
        authority_path=authority,
        state_root=state_root,
        bindings=bindings,
        command_runner=runner,
    )

    assert result["status"] == publication.ROLLED_BACK_VERIFIED
    assert authority.read_bytes() == old_raw
    assert len(runner.commands) == 3
    durable_consumer = Path(runner.commands[2][1])
    assert durable_consumer.is_file()
    assert durable_consumer != bindings.consumer_path
    assert "--legacy-preimage-readback" in runner.commands[2]


def test_fresh_subprocess_consumer_reads_exact_bytes(tmp_path: Path) -> None:
    raw = _new_document("fresh process authority")
    authority = _write(tmp_path / "authority.txt", raw)
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_tool_glue_consumer.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--authority-path",
            str(authority),
            "--expected-sha256",
            _hash(raw),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["status"] == publication.VERIFIED
    assert receipt["authority_sha256"] == _hash(raw)
    assert receipt["constitution_version"] == "v3.4"
    assert receipt["maturation_invariant_verified"] is True
    assert "XINAO_NECESSARY_CHAIN_MATURATION_INVARIANT" in receipt["semantic_anchors"]
    assert receipt["completion_claim_allowed"] is False


def test_fresh_subprocess_consumer_rejects_v34_with_incomplete_invariant(
    tmp_path: Path,
) -> None:
    raw = _new_document().replace(b"MATURATION_REQUIRED", b"MISSING_REQUIREMENT")
    authority = _write(tmp_path / "authority.txt", raw)
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_tool_glue_consumer.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--authority-path",
            str(authority),
            "--expected-sha256",
            _hash(raw),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 2
    failure = json.loads(completed.stderr)
    assert failure["status"] == "FAILED"
    assert "semantics are incomplete" in failure["error"]
    assert failure["completion_claim_allowed"] is False
