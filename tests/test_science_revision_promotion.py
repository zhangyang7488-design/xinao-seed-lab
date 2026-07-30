from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from scripts import promote_science_revision_chain as promotion


def _force_write_bytes(path: Path, payload: bytes) -> None:
    """Clear the Windows read-only bit before mutating a sealed postimage."""

    path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWRITE)
    path.write_bytes(payload)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _install_bound_transaction(
    *,
    projection: Path,
    journal_path: Path,
    journal: dict[str, object],
    phase: str = "JOURNAL_BOUND",
) -> Path:
    """Persist a marker+journal pair with a sealed transaction identity digest."""

    transaction_directory = Path(
        str(journal.get("transaction_directory") or journal_path.parent)
    ).resolve()
    journal = dict(journal)
    journal.setdefault("schema_version", "xinao.science_revision_transaction.v1")
    journal["transaction_directory"] = str(transaction_directory)
    journal["projection_path"] = str(Path(str(journal["projection_path"])).resolve())
    if journal.get("active_parent_path") is not None:
        journal["active_parent_path"] = str(Path(str(journal["active_parent_path"])).resolve())
    identity = promotion._transaction_identity_sha256(
        journal, transaction_directory=transaction_directory
    )
    journal["transaction_identity_sha256"] = identity
    promotion._write_json_atomic(journal_path, journal)
    marker_path = projection.with_name(f"{projection.name}.promotion.lock")
    promotion._write_json_atomic(
        marker_path,
        promotion._marker_payload(
            phase=phase,
            journal_path=journal_path,
            projection_path=projection,
            transaction_directory=transaction_directory,
            transaction_identity_sha256=identity,
        ),
    )
    return marker_path


def _semantic_files(root: Path) -> dict[Path, bytes]:
    """Snapshot files excluding the durable empty promotion.guard carrier."""

    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.name.endswith(".promotion.guard")
    }


def _assert_stable_empty_guard(projection: Path) -> None:
    guard = promotion._promotion_lease_path(projection)
    assert guard.is_file()
    assert guard.stat().st_size == 0
    assert not promotion._is_reparse_path(guard)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    projection = tmp_path / "active_parent.current.json"
    evidence = tmp_path / "science_revision.v1.json"
    rollback = tmp_path / "rollback" / "active_parent.before.json"
    active_parent = tmp_path / "active-parent.txt"
    active_parent.write_text("old active parent", encoding="utf-8")
    _write_json(
        projection,
        {
            "schema_version": "xinao.science_active_parent_projection.v1",
            "active_parent": {
                "path": str(active_parent),
                "sha256": promotion._sha256(active_parent),
            },
        },
    )
    _write_json(
        evidence,
        {
            "schema_version": "xinao.science_revision.v1",
            "status": "APPLIED",
            "run_id": "revision-run",
        },
    )
    return projection, evidence, rollback


def _ready(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload.get("science_revision_chain", []), list)
    return {"status": "READY", "active_parent": {"sha256": "current"}}


def _exception_messages(error: BaseException) -> list[str]:
    if isinstance(error, BaseExceptionGroup):
        return [message for nested in error.exceptions for message in _exception_messages(nested)]
    return [str(error)]


def _four_target_v110_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    projection, evidence, projection_rollback = _fixture(tmp_path)
    projection_payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(projection_payload["active_parent"]["path"])
    old_parent_sha256 = promotion._sha256(active_parent)
    candidate_parent = tmp_path / "science-v1.10-candidate.txt"
    candidate_parent.write_text(
        "版本：正式融合稿 v1.10\nscience candidate\n",  # noqa: RUF001
        encoding="utf-8",
    )
    candidate_parent_sha256 = promotion._sha256(candidate_parent)

    tool_glue = tmp_path / "software-tool-glue-v3.4.txt"
    tool_glue.write_text("版本：v3.4\n", encoding="utf-8")  # noqa: RUF001
    tool_glue_sha256 = promotion._sha256(tool_glue)
    projection_payload["software_foundation"] = {
        "path": str(tool_glue),
        "sha256": tool_glue_sha256,
        "version": "v3.4",
    }
    _write_json(projection, projection_payload)

    stale_transition_parent_sha256 = (
        "6256cb50c6359ec25d63a958f3126dd7a4bcddeb1e36a36812bd0ceb305ff428"
    )
    transition = tmp_path / "science-transition.txt"
    transition.write_text(
        "【当前研究接续入口｜非权威】\n"
        "唯一科学父目标：\n"  # noqa: RUF001
        f"`{active_parent}`\n"
        f"SHA256：`{stale_transition_parent_sha256}`\n"  # noqa: RUF001
        "其余接续内容保持不变。\n",
        encoding="utf-8",
    )
    transition_candidate = tmp_path / "science-transition.candidate.txt"
    transition_candidate.write_text(
        transition.read_text(encoding="utf-8").replace(
            stale_transition_parent_sha256,
            candidate_parent_sha256,
        ),
        encoding="utf-8",
    )

    old_snapshot = tmp_path / "science-v1.9.snapshot.txt"
    old_snapshot.write_bytes(active_parent.read_bytes())
    candidate_snapshot = tmp_path / "science-v1.10.snapshot.txt"
    candidate_snapshot.write_bytes(candidate_parent.read_bytes())
    archive_manifest = tmp_path / "archive_relocation_manifest.json"
    archive_payload = {
        "schema_version": "xinao.archive-relocation-manifest.v1",
        "status": "ARCHIVE_RELOCATION_VERIFIED",
        "opaque_history": {"preserved": True},
        "current_publication": {
            "stable_spec_path": str(active_parent),
            "stable_spec_sha256": old_parent_sha256,
            "versioned_snapshot_path": str(old_snapshot),
            "versioned_snapshot_sha256": old_parent_sha256,
            "background_contract_path": str(tmp_path / "background.txt"),
            "background_contract_sha256": "a" * 64,
        },
    }
    _write_json(archive_manifest, archive_payload)
    archive_candidate = tmp_path / "archive_relocation_manifest.candidate.json"
    archive_candidate_payload = json.loads(json.dumps(archive_payload))
    archive_candidate_payload["current_publication"].update(
        {
            "stable_spec_sha256": candidate_parent_sha256,
            "versioned_snapshot_path": str(candidate_snapshot),
            "versioned_snapshot_sha256": candidate_parent_sha256,
        }
    )
    _write_json(archive_candidate, archive_candidate_payload)

    def candidate_binding(
        _projection: dict[str, object],
        *,
        science_candidate_path: Path,
        software_foundation_candidate_path: Path,
    ) -> dict[str, object]:
        assert science_candidate_path == candidate_parent
        assert software_foundation_candidate_path == tool_glue
        return {
            "science_parent_version": "v1.10",
            "software_foundation_version": "v3.4",
            "maturation_invariant_required": True,
        }

    monkeypatch.setattr(
        promotion,
        "validate_science_revision_candidate_binding",
        candidate_binding,
    )
    monkeypatch.setattr(promotion, "load_science_active_parent", _ready)

    transaction_directory = tmp_path / "science-transaction"
    active_parent_rollback = tmp_path / "rollback" / "science-parent.before.txt"
    transition_rollback = tmp_path / "rollback" / "science-transition.before.txt"
    archive_rollback = tmp_path / "rollback" / "archive-manifest.before.json"
    publish_kwargs = {
        "projection_path": projection,
        "evidence_paths": [evidence],
        "event_refs": [str(tmp_path / "events.jsonl") + "#event_id=revision"],
        "rollback_copy": projection_rollback,
        "expected_projection_sha256": promotion._sha256(projection),
        "candidate_active_parent": candidate_parent,
        "expected_candidate_active_parent_sha256": candidate_parent_sha256,
        "expected_active_parent_sha256": old_parent_sha256,
        "active_parent_rollback_copy": active_parent_rollback,
        "tool_glue_authority_path": tool_glue,
        "expected_tool_glue_authority_sha256": tool_glue_sha256,
        "expected_tool_glue_version": "v3.4",
        "transition_path": transition,
        "transition_candidate": transition_candidate,
        "expected_transition_sha256": promotion._sha256(transition),
        "expected_transition_preimage_active_parent_sha256": (stale_transition_parent_sha256),
        "transition_rollback_copy": transition_rollback,
        "archive_manifest_path": archive_manifest,
        "archive_manifest_candidate": archive_candidate,
        "expected_archive_manifest_sha256": promotion._sha256(archive_manifest),
        "archive_manifest_rollback_copy": archive_rollback,
        "transaction_directory": transaction_directory,
    }
    return {
        "publish_kwargs": publish_kwargs,
        "journal_path": transaction_directory / "transaction.v1.json",
        "targets": {
            "active_parent": active_parent,
            "projection": projection,
            "archive_manifest": archive_manifest,
            "transition": transition,
        },
        "rollback_copies": {
            "active_parent": active_parent_rollback,
            "projection": projection_rollback,
            "archive_manifest": archive_rollback,
            "transition": transition_rollback,
        },
        "preimages": {
            "active_parent": active_parent.read_bytes(),
            "projection": projection.read_bytes(),
            "archive_manifest": archive_manifest.read_bytes(),
            "transition": transition.read_bytes(),
        },
        "candidate_parent_sha256": candidate_parent_sha256,
        "stale_transition_parent_sha256": stale_transition_parent_sha256,
    }


def test_promote_revision_chain_keeps_immutable_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    original = projection.read_bytes()
    monkeypatch.setattr(promotion, "load_science_active_parent", _ready)
    science_episode_gate = {
        "id": "XINAO_SCIENCE_EPISODE_ALLOWED",
        "definition_source": "active_parent_section_12_1",
        "first_frontier": [
            "ParentRealityObject",
            "ObjectContact",
            "ExplorationTrace",
        ],
        "old_g6_equivalent": False,
    }

    result = promotion.promote_revision_chain(
        projection_path=projection,
        evidence_paths=[evidence],
        event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
        rollback_copy=rollback,
        science_episode_gate=science_episode_gate,
    )

    assert result["status"] == "VERIFIED"
    assert result["revision_count"] == 1
    assert rollback.read_bytes() == original
    assert (
        json.loads(projection.read_text(encoding="utf-8"))["science_revision_chain"][0]["run_id"]
        == "revision-run"
    )
    assert json.loads(projection.read_text(encoding="utf-8"))["science_episode_gate"] == (
        science_episode_gate
    )


def test_dependency_preflight_failure_precedes_all_persistent_promotion_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    before = _semantic_files(tmp_path)

    def reject_unready_tool_glue(_path: Path) -> dict[str, object]:
        raise ValueError("SCIENCE_DEPENDENCY_TOOL_GLUE_PIN_MISMATCH")

    monkeypatch.setattr(promotion, "load_science_active_parent", reject_unready_tool_glue)

    with pytest.raises(ValueError, match="SCIENCE_DEPENDENCY_TOOL_GLUE_PIN_MISMATCH"):
        promotion.promote_revision_chain(
            projection_path=projection,
            evidence_paths=[evidence],
            event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
            rollback_copy=rollback,
        )

    after = _semantic_files(tmp_path)
    assert after == before
    assert not rollback.exists()
    assert not projection.with_name(f"{projection.name}.promotion.lock").exists()
    # Stable empty guard is a lock carrier, not semantic transaction residue.
    _assert_stable_empty_guard(projection)


def test_science_v110_publication_requires_exact_live_tool_glue_pin_before_mutation(
    tmp_path: Path,
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    candidate_active_parent = tmp_path / "science-v1.10-candidate.txt"
    candidate_active_parent.write_text(
        "版本：正式融合稿 v1.10\nscience v1.10 candidate\n",  # noqa: RUF001
        encoding="utf-8",
    )
    tool_glue_authority = tmp_path / "software-tool-glue-authority.txt"
    tool_glue_authority.write_text("版本：v3.3\n", encoding="utf-8")  # noqa: RUF001
    transaction_directory = tmp_path / "science-transaction"
    active_parent_rollback = tmp_path / "rollback" / "science-parent.before.txt"
    transition = tmp_path / "science-transition.txt"
    transition.write_text(
        "唯一科学父目标：\n"  # noqa: RUF001
        f"`{active_parent}`\n"
        "SHA256：`6256cb50c6359ec25d63a958f3126dd7a4bcddeb1e36a36812bd0ceb305ff428`\n",  # noqa: RUF001
        encoding="utf-8",
    )
    transition_candidate = tmp_path / "science-transition.candidate.txt"
    transition_candidate.write_text(
        "唯一科学父目标：\n"  # noqa: RUF001
        f"`{active_parent}`\n"
        f"SHA256：`{promotion._sha256(candidate_active_parent)}`\n",  # noqa: RUF001
        encoding="utf-8",
    )
    transition_rollback = tmp_path / "rollback" / "science-transition.before.txt"
    archive_manifest = tmp_path / "archive_relocation_manifest.json"
    _write_json(archive_manifest, {"current_publication": {"version": "v1.9"}})
    archive_manifest_candidate = tmp_path / "archive_relocation_manifest.candidate.json"
    _write_json(archive_manifest_candidate, {"current_publication": {"version": "v1.10"}})
    archive_manifest_rollback = tmp_path / "rollback" / "archive-manifest.before.json"
    expected_tool_glue_v34_sha256 = (
        "eb6677d9cf87d152b91b119f92488e90969145c0dabfc4cb0e3b1d0437643703"
    )
    before = _semantic_files(tmp_path)

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.publish_science_revision_transaction(
            projection_path=projection,
            evidence_paths=[evidence],
            event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
            rollback_copy=rollback,
            expected_projection_sha256=promotion._sha256(projection),
            candidate_active_parent=candidate_active_parent,
            expected_candidate_active_parent_sha256=promotion._sha256(candidate_active_parent),
            expected_active_parent_sha256=promotion._sha256(active_parent),
            active_parent_rollback_copy=active_parent_rollback,
            tool_glue_authority_path=tool_glue_authority,
            expected_tool_glue_authority_sha256=expected_tool_glue_v34_sha256,
            expected_tool_glue_version="v3.4",
            transition_path=transition,
            transition_candidate=transition_candidate,
            expected_transition_sha256=promotion._sha256(transition),
            expected_transition_preimage_active_parent_sha256=(
                "6256cb50c6359ec25d63a958f3126dd7a4bcddeb1e36a36812bd0ceb305ff428"
            ),
            transition_rollback_copy=transition_rollback,
            archive_manifest_path=archive_manifest,
            archive_manifest_candidate=archive_manifest_candidate,
            expected_archive_manifest_sha256=promotion._sha256(archive_manifest),
            archive_manifest_rollback_copy=archive_manifest_rollback,
            transaction_directory=transaction_directory,
        )

    assert raised.value.code == "SCIENCE_DEPENDENCY_TOOL_GLUE_PIN_MISMATCH"
    after = _semantic_files(tmp_path)
    assert after == before
    assert not rollback.exists()
    assert not active_parent_rollback.exists()
    assert not transition_rollback.exists()
    assert not archive_manifest_rollback.exists()
    assert not transaction_directory.exists()
    assert not projection.with_name(f"{projection.name}.promotion.lock").exists()
    _assert_stable_empty_guard(projection)


def test_promote_revision_chain_retains_commit_on_post_commit_readback_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    original = projection.read_bytes()
    calls = 0
    lock_path = projection.with_name(f"{projection.name}.promotion.lock")
    journal_path = rollback.parent / f"{projection.name}.transaction" / "transaction.v1.json"

    def fail_live_validation(path: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert path == projection
            assert not lock_path.exists()
        if calls >= 3:
            assert path == projection
            assert lock_path.is_file()
            assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == ("COMMITTED")
            raise ValueError("evidence drifted after candidate validation")
        return _ready(path)

    monkeypatch.setattr(promotion, "load_science_active_parent", fail_live_validation)

    with pytest.raises(ValueError, match="evidence drifted"):
        promotion.promote_revision_chain(
            projection_path=projection,
            evidence_paths=[evidence],
            event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
            rollback_copy=rollback,
        )

    assert projection.read_bytes() != original
    assert rollback.read_bytes() == original
    assert lock_path.is_file()
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "COMMITTED"
    with pytest.raises(ValueError, match="evidence drifted"):
        promotion.recover_interrupted_promotion(projection)
    assert lock_path.is_file()
    monkeypatch.setattr(promotion, "load_science_active_parent", _ready)
    recovery = promotion.recover_interrupted_promotion(projection)
    assert recovery["status"] == "COMMITTED_LOCK_CLEARED"
    assert not lock_path.exists()
    assert projection.read_bytes() != original


def test_promote_revision_chain_appends_without_rewriting_existing_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    original_entry = {
        "status": "APPLIED",
        "run_id": "old-run",
        "event_ref": "old-events.jsonl#event_id=old",
        "revision_evidence_ref": "old-evidence.json",
        "revision_evidence_sha256": "a" * 64,
    }
    payload["science_revision_chain"] = [original_entry]
    _write_json(projection, payload)
    monkeypatch.setattr(promotion, "load_science_active_parent", _ready)

    result = promotion.promote_revision_chain(
        projection_path=projection,
        evidence_paths=[evidence],
        event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
        rollback_copy=rollback,
    )

    revised = json.loads(projection.read_text(encoding="utf-8"))
    assert result["revision_count"] == 2
    assert revised["science_revision_chain"][0] == original_entry
    assert revised["science_revision_chain"][1]["run_id"] == "revision-run"


def test_promote_revision_chain_refuses_duplicate_chain_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    event_ref = str(tmp_path / "events.jsonl") + "#event_id=revision"
    payload = json.loads(projection.read_text(encoding="utf-8"))
    payload["science_revision_chain"] = [promotion._revision_entry(evidence, event_ref)]
    _write_json(projection, payload)
    monkeypatch.setattr(promotion, "load_science_active_parent", _ready)

    with pytest.raises(ValueError, match="duplicates"):
        promotion.promote_revision_chain(
            projection_path=projection,
            evidence_paths=[evidence],
            event_refs=[event_ref],
            rollback_copy=rollback,
        )


def test_promote_revision_chain_rejects_stale_projection_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    original = projection.read_bytes()
    monkeypatch.setattr(promotion, "load_science_active_parent", _ready)

    with pytest.raises(ValueError, match="projection changed"):
        promotion.promote_revision_chain(
            projection_path=projection,
            evidence_paths=[evidence],
            event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
            rollback_copy=rollback,
            expected_projection_sha256="0" * 64,
        )

    assert projection.read_bytes() == original
    assert not rollback.exists()


def test_promote_revision_chain_cas_swaps_parent_and_appends_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    old_parent = active_parent.read_bytes()
    old_parent_sha256 = promotion._sha256(active_parent)
    candidate = tmp_path / "candidate-parent.txt"
    candidate.write_text("new active parent", encoding="utf-8")
    projection.chmod(stat.S_IREAD)
    active_parent.chmod(stat.S_IREAD)
    candidate.chmod(stat.S_IREAD)
    candidate_sha256 = promotion._sha256(candidate)
    evidence_payload = json.loads(evidence.read_text(encoding="utf-8"))
    evidence_payload.update(
        {
            "predecessor_active_parent": {"sha256": old_parent_sha256},
            "active_parent": {
                "id": "XINAO_SCIENCE_PROTOCOL_ACTIVE",
                "status": "CURRENT_ACTIVE_PARENT",
                "path": str(active_parent),
                "sha256": candidate_sha256,
            },
        }
    )
    _write_json(evidence, evidence_payload)
    projection_sha256 = promotion._sha256(projection)
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"

    def ready(path: Path) -> dict[str, object]:
        current = json.loads(path.read_text(encoding="utf-8"))
        expected = str(current["active_parent"]["sha256"])
        assert promotion._sha256(Path(current["active_parent"]["path"])) == expected
        return {"status": "READY", "active_parent": {"sha256": expected}}

    monkeypatch.setattr(promotion, "load_science_active_parent", ready)
    result = promotion.promote_revision_chain(
        projection_path=projection,
        evidence_paths=[evidence],
        event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
        rollback_copy=rollback,
        expected_projection_sha256=projection_sha256,
        candidate_active_parent=candidate,
        expected_active_parent_sha256=old_parent_sha256,
        active_parent_rollback_copy=parent_rollback,
    )

    revised = json.loads(projection.read_text(encoding="utf-8"))
    assert result["status"] == "VERIFIED"
    assert active_parent.read_text(encoding="utf-8") == "new active parent"
    assert not active_parent.stat().st_mode & stat.S_IWRITE
    assert not projection.stat().st_mode & stat.S_IWRITE
    assert revised["active_parent"]["sha256"] == candidate_sha256
    assert len(revised["science_revision_chain"]) == 1
    assert parent_rollback.read_bytes() == old_parent


def test_promote_revision_chain_refuses_post_swap_candidate_digest_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    original_projection = projection.read_bytes()
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    original_parent = active_parent.read_bytes()
    old_parent_sha256 = promotion._sha256(active_parent)
    candidate = tmp_path / "candidate-parent.txt"
    candidate.write_text("new active parent", encoding="utf-8")
    candidate_sha256 = promotion._sha256(candidate)
    evidence_payload = json.loads(evidence.read_text(encoding="utf-8"))
    evidence_payload.update(
        {
            "predecessor_active_parent": {"sha256": old_parent_sha256},
            "active_parent": {
                "id": "XINAO_SCIENCE_PROTOCOL_ACTIVE",
                "status": "CURRENT_ACTIVE_PARENT",
                "path": str(active_parent),
                "sha256": candidate_sha256,
            },
        }
    )
    _write_json(evidence, evidence_payload)
    real_replace = promotion._replace_file
    projection_corrupted = False

    def corrupt_projection_once(
        source: Path, target: Path, *, installed_mode: int | None = None
    ) -> None:
        nonlocal projection_corrupted
        real_replace(source, target, installed_mode=installed_mode)
        if target == projection and not projection_corrupted:
            projection_corrupted = True
            # Sealed postimages install without S_IWRITE; clear it only for the
            # deliberate post-swap corruption probe.
            os.chmod(target, stat.S_IMODE(target.stat().st_mode) | stat.S_IWRITE)
            with target.open("a", encoding="utf-8") as stream:
                stream.write(" ")

    monkeypatch.setattr(promotion, "_replace_file", corrupt_projection_once)
    monkeypatch.setattr(promotion, "load_science_active_parent", _ready)

    with pytest.raises(RuntimeError, match="does not match prepared candidate"):
        promotion.promote_revision_chain(
            projection_path=projection,
            evidence_paths=[evidence],
            event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
            rollback_copy=rollback,
            expected_projection_sha256=promotion._sha256(projection),
            candidate_active_parent=candidate,
            expected_active_parent_sha256=old_parent_sha256,
            active_parent_rollback_copy=tmp_path / "rollback" / "parent.before.txt",
        )

    assert projection.read_bytes() == original_projection
    assert active_parent.read_bytes() == original_parent
    journal_path = rollback.parent / f"{projection.name}.transaction" / "transaction.v1.json"
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "ROLLED_BACK"


def test_promote_revision_chain_restores_parent_after_candidate_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    original_projection = projection.read_bytes()
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    original_parent = active_parent.read_bytes()
    old_parent_sha256 = promotion._sha256(active_parent)
    candidate = tmp_path / "candidate-parent.txt"
    candidate.write_text("new active parent", encoding="utf-8")
    projection.chmod(stat.S_IREAD)
    active_parent.chmod(stat.S_IREAD)
    candidate.chmod(stat.S_IREAD)
    evidence_payload = json.loads(evidence.read_text(encoding="utf-8"))
    evidence_payload.update(
        {
            "predecessor_active_parent": {"sha256": old_parent_sha256},
            "active_parent": {
                "id": "XINAO_SCIENCE_PROTOCOL_ACTIVE",
                "status": "CURRENT_ACTIVE_PARENT",
                "path": str(active_parent),
                "sha256": promotion._sha256(candidate),
            },
        }
    )
    _write_json(evidence, evidence_payload)
    calls = 0

    def fail_candidate_validation(path: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("candidate projection failed")
        current = json.loads(path.read_text(encoding="utf-8"))
        return {"status": "READY", "active_parent": current["active_parent"]}

    monkeypatch.setattr(promotion, "load_science_active_parent", fail_candidate_validation)
    with pytest.raises(ValueError, match="candidate projection failed"):
        promotion.promote_revision_chain(
            projection_path=projection,
            evidence_paths=[evidence],
            event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
            rollback_copy=rollback,
            expected_projection_sha256=promotion._sha256(projection),
            candidate_active_parent=candidate,
            expected_active_parent_sha256=old_parent_sha256,
            active_parent_rollback_copy=tmp_path / "rollback" / "parent.before.txt",
        )

    assert projection.read_bytes() == original_projection
    assert active_parent.read_bytes() == original_parent
    assert not active_parent.stat().st_mode & stat.S_IWRITE
    assert not projection.stat().st_mode & stat.S_IWRITE
    lock_path = projection.with_name(f"{projection.name}.promotion.lock")
    journal_path = rollback.parent / f"{projection.name}.transaction" / "transaction.v1.json"
    assert lock_path.is_file()
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "ROLLED_BACK"
    recovery = promotion.recover_interrupted_promotion(projection)
    assert recovery["status"] == "ROLLED_BACK"
    assert not lock_path.exists()


def test_promote_revision_chain_retains_dual_file_commit_on_readback_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    original_projection = projection.read_bytes()
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    original_parent = active_parent.read_bytes()
    old_parent_sha256 = promotion._sha256(active_parent)
    candidate = tmp_path / "candidate-parent.txt"
    candidate.write_text("new active parent", encoding="utf-8")
    candidate_sha256 = promotion._sha256(candidate)
    evidence_payload = json.loads(evidence.read_text(encoding="utf-8"))
    evidence_payload.update(
        {
            "predecessor_active_parent": {"sha256": old_parent_sha256},
            "active_parent": {
                "id": "XINAO_SCIENCE_PROTOCOL_ACTIVE",
                "status": "CURRENT_ACTIVE_PARENT",
                "path": str(active_parent),
                "sha256": candidate_sha256,
            },
        }
    )
    _write_json(evidence, evidence_payload)
    calls = 0

    def fail_post_commit_readback(path: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("post-commit readback failed")
        current = json.loads(path.read_text(encoding="utf-8"))
        return {"status": "READY", "active_parent": current["active_parent"]}

    monkeypatch.setattr(promotion, "load_science_active_parent", fail_post_commit_readback)
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    with pytest.raises(ValueError, match="post-commit readback failed"):
        promotion.promote_revision_chain(
            projection_path=projection,
            evidence_paths=[evidence],
            event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
            rollback_copy=rollback,
            expected_projection_sha256=promotion._sha256(projection),
            candidate_active_parent=candidate,
            expected_active_parent_sha256=old_parent_sha256,
            active_parent_rollback_copy=parent_rollback,
        )

    lock_path = projection.with_name(f"{projection.name}.promotion.lock")
    journal_path = rollback.parent / f"{projection.name}.transaction" / "transaction.v1.json"
    assert projection.read_bytes() != original_projection
    assert active_parent.read_bytes() != original_parent
    assert promotion._sha256(active_parent) == candidate_sha256
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "COMMITTED"
    assert lock_path.is_file()
    recovery = promotion.recover_interrupted_promotion(projection)
    assert recovery["status"] == "COMMITTED_LOCK_CLEARED"
    assert not lock_path.exists()
    assert promotion._sha256(active_parent) == candidate_sha256


def test_promote_revision_chain_refuses_concurrent_lock(tmp_path: Path) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    original_projection = projection.read_bytes()
    marker_path = projection.with_name(f"{projection.name}.promotion.lock")
    lease_path = promotion._promotion_lease_path(projection)
    lease = promotion._acquire_promotion_lease(projection)
    try:
        with pytest.raises(RuntimeError, match="still owned"):
            promotion.promote_revision_chain(
                projection_path=projection,
                evidence_paths=[evidence],
                event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
                rollback_copy=rollback,
            )
    finally:
        lease.release()
    assert projection.read_bytes() == original_projection
    assert not rollback.exists()
    assert not marker_path.exists()
    # Persistent empty ordinary-file guard remains after release; reacquire reuses it.
    assert lease_path.is_file()
    assert lease_path.stat().st_size == 0
    reacquired_lease = promotion._acquire_promotion_lease(projection)
    reacquired_lease.release()
    assert lease_path.is_file()
    assert lease_path.stat().st_size == 0


def test_recovery_rejects_journal_bound_to_another_projection(tmp_path: Path) -> None:
    projection, _evidence, _rollback = _fixture(tmp_path)
    other_projection = tmp_path / "other-projection.json"
    other_projection.write_bytes(projection.read_bytes())
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    journal_path = tmp_path / "transaction" / "transaction.v1.json"
    lock_path = _install_bound_transaction(
        projection=projection,
        journal_path=journal_path,
        journal={
            "status": "COMMITTED",
            "projection_path": str(other_projection),
            "active_parent_path": str(active_parent),
            "projection_committed_sha256": promotion._sha256(other_projection),
            "active_parent_committed_sha256": promotion._sha256(active_parent),
        },
    )

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.recover_interrupted_promotion(projection)

    assert raised.value.code == "CROSS_OBJECT_RESTORE"
    assert lock_path.is_file()


@pytest.mark.parametrize("projection_swapped", [False, True])
def test_recover_interrupted_promotion_restores_persisted_applying_state(
    tmp_path: Path, projection_swapped: bool
) -> None:
    projection, _evidence, rollback = _fixture(tmp_path)
    original_projection = projection.read_bytes()
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    original_parent = active_parent.read_bytes()
    old_parent_sha256 = promotion._sha256(active_parent)
    candidate = tmp_path / "candidate-parent.txt"
    candidate.write_text("new active parent", encoding="utf-8")
    projection.chmod(stat.S_IREAD)
    active_parent.chmod(stat.S_IREAD)
    candidate.chmod(stat.S_IREAD)
    candidate_parent_sha256 = promotion._sha256(candidate)
    candidate_projection = tmp_path / "active_parent.current.candidate.json"
    candidate_projection_payload = json.loads(projection.read_text(encoding="utf-8"))
    candidate_projection_payload["active_parent"]["sha256"] = candidate_parent_sha256
    _write_json(candidate_projection, candidate_projection_payload)
    candidate_projection_sha256 = promotion._sha256(candidate_projection)

    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.parent.mkdir(parents=True, exist_ok=True)
    parent_rollback.write_bytes(original_parent)
    parent_rollback.chmod(stat.S_IREAD)
    rollback.write_bytes(original_projection)
    rollback.chmod(stat.S_IREAD)
    transaction_directory = tmp_path / "transaction"
    journal_path = transaction_directory / "transaction.v1.json"
    # Durable APPLYING cut with JOURNAL_BOUND identity before live swaps.
    lock_path = _install_bound_transaction(
        projection=projection,
        journal_path=journal_path,
        journal={
            "status": "APPLYING",
            "projection_path": str(projection),
            "projection_preimage_sha256": promotion._sha256(rollback),
            "projection_candidate_sha256": candidate_projection_sha256,
            "projection_rollback_copy": str(rollback),
            "projection_candidate_path": str(candidate_projection),
            "active_parent_path": str(active_parent),
            "active_parent_preimage_sha256": old_parent_sha256,
            "active_parent_candidate_sha256": candidate_parent_sha256,
            "active_parent_rollback_copy": str(parent_rollback),
            "active_parent_candidate_path": str(candidate),
            "transaction_directory": str(transaction_directory),
        },
    )
    # Materialize the exact durable state left by a process death without killing
    # pytest (or its Codex tool host) as part of the regression itself.
    promotion._replace_file(candidate, active_parent)
    if projection_swapped:
        promotion._replace_file(
            candidate_projection,
            projection,
            installed_mode=stat.S_IREAD,
        )
    assert promotion._sha256(active_parent) == candidate_parent_sha256
    assert promotion._sha256(projection) == (
        candidate_projection_sha256 if projection_swapped else promotion._sha256(rollback)
    )
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "APPLYING"
    assert lock_path.is_file()
    recovery = promotion.recover_interrupted_promotion(projection)
    assert recovery["status"] == "ROLLED_BACK_AFTER_CRASH"
    assert active_parent.read_bytes() == original_parent
    assert not active_parent.stat().st_mode & stat.S_IWRITE
    assert projection.read_bytes() == original_projection
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (
        "ROLLED_BACK_AFTER_CRASH"
    )
    assert not lock_path.exists()
    second_recovery = promotion.recover_interrupted_promotion(projection)
    assert second_recovery["status"] == "NO_INTERRUPTED_TRANSACTION"


def test_restore_preimages_attempts_every_target_after_one_restore_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection_preimage = tmp_path / "projection.before.json"
    parent_preimage = tmp_path / "parent.before.txt"
    projection_target = tmp_path / "projection.json"
    parent_target = tmp_path / "parent.txt"
    projection_preimage.write_text("old projection", encoding="utf-8")
    parent_preimage.write_text("old parent", encoding="utf-8")
    projection_target.write_text("new projection", encoding="utf-8")
    parent_target.write_text("new parent", encoding="utf-8")
    parent_preimage.chmod(stat.S_IREAD)
    parent_target.chmod(stat.S_IREAD)
    specs = [
        (
            "projection",
            projection_preimage,
            projection_target,
            promotion._sha256(projection_preimage),
            None,
        ),
        (
            "active-parent",
            parent_preimage,
            parent_target,
            promotion._sha256(parent_preimage),
            stat.S_IREAD,
        ),
    ]
    real_restore = promotion._restore_file
    attempted: list[Path] = []

    def fail_projection_restore(
        source: Path, target: Path, *, installed_mode: int | None = None
    ) -> None:
        attempted.append(target)
        if target == projection_target:
            raise PermissionError("projection rollback blocked")
        real_restore(source, target, installed_mode=installed_mode)

    monkeypatch.setattr(promotion, "_restore_file", fail_projection_restore)
    errors = promotion._restore_preimages(specs)

    assert attempted == [projection_target, parent_target]
    assert len(errors) == 1
    assert "projection rollback blocked" in str(errors[0])
    assert projection_target.read_text(encoding="utf-8") == "new projection"
    assert parent_target.read_text(encoding="utf-8") == "old parent"
    assert not parent_target.stat().st_mode & stat.S_IWRITE


def test_restore_file_preserves_primary_and_cleanup_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "before.txt"
    target = tmp_path / "target.txt"
    source.write_text("before", encoding="utf-8")
    target.write_text("after", encoding="utf-8")

    def fail_replace(_source: Path, _target: Path, **_kwargs: object) -> None:
        raise ValueError("primary replace failure")

    def fail_cleanup(_path: Path) -> None:
        raise PermissionError("secondary cleanup failure")

    monkeypatch.setattr(promotion, "_replace_file", fail_replace)
    monkeypatch.setattr(promotion, "_unlink_temporary", fail_cleanup)

    with pytest.raises(ExceptionGroup) as caught:
        promotion._restore_file(source, target)

    messages = _exception_messages(caught.value)
    assert any("primary replace failure" in message for message in messages)
    assert any("secondary cleanup failure" in message for message in messages)


def test_recovery_validates_all_preimages_before_mutating_either_target(
    tmp_path: Path,
) -> None:
    projection, _evidence, rollback = _fixture(tmp_path)
    original_projection = projection.read_bytes()
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    original_parent = active_parent.read_bytes()
    old_parent_sha256 = promotion._sha256(active_parent)
    candidate_parent = tmp_path / "candidate-parent.txt"
    candidate_parent.write_text("new active parent", encoding="utf-8")
    candidate_parent_sha256 = promotion._sha256(candidate_parent)
    candidate_projection = tmp_path / "candidate-projection.json"
    candidate_payload = json.loads(projection.read_text(encoding="utf-8"))
    candidate_payload["active_parent"]["sha256"] = candidate_parent_sha256
    _write_json(candidate_projection, candidate_payload)
    candidate_projection_sha256 = promotion._sha256(candidate_projection)
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.parent.mkdir(parents=True, exist_ok=True)
    parent_rollback.write_bytes(b"drifted parent preimage")
    rollback.write_bytes(original_projection)
    journal_path = tmp_path / "transaction" / "transaction.v1.json"
    lock_path = _install_bound_transaction(
        projection=projection,
        journal_path=journal_path,
        journal={
            "status": "APPLYING",
            "projection_path": str(projection),
            "projection_preimage_sha256": promotion._sha256(rollback),
            "projection_candidate_sha256": candidate_projection_sha256,
            "projection_rollback_copy": str(rollback),
            "projection_candidate_path": str(candidate_projection),
            "active_parent_path": str(active_parent),
            "active_parent_preimage_sha256": old_parent_sha256,
            "active_parent_candidate_sha256": candidate_parent_sha256,
            "active_parent_rollback_copy": str(parent_rollback),
            "active_parent_candidate_path": str(candidate_parent),
            "transaction_directory": str(journal_path.parent),
        },
    )
    promotion._replace_file(candidate_parent, active_parent)
    promotion._replace_file(candidate_projection, projection)

    with pytest.raises(RuntimeError, match="active-parent.*missing or drifted"):
        promotion.recover_interrupted_promotion(projection)

    assert promotion._sha256(projection) == candidate_projection_sha256
    assert promotion._sha256(active_parent) == candidate_parent_sha256
    assert projection.read_bytes() != original_projection
    assert active_parent.read_bytes() != original_parent
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "APPLYING"
    assert lock_path.is_file()


def test_committed_recovery_retains_marker_when_postimage_drifted(tmp_path: Path) -> None:
    projection, _evidence, rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    original_projection = projection.read_bytes()
    rollback.parent.mkdir(parents=True, exist_ok=True)
    rollback.write_bytes(original_projection)
    committed_projection_sha256 = promotion._sha256(projection)
    committed_parent_sha256 = promotion._sha256(active_parent)
    journal_path = tmp_path / "transaction" / "transaction.v1.json"
    lock_path = _install_bound_transaction(
        projection=projection,
        journal_path=journal_path,
        journal={
            "status": "COMMITTED",
            "projection_path": str(projection),
            "projection_preimage_sha256": promotion._sha256(rollback),
            "projection_rollback_copy": str(rollback),
            "projection_committed_sha256": committed_projection_sha256,
            "active_parent_path": str(active_parent),
            "active_parent_committed_sha256": committed_parent_sha256,
            "transaction_directory": str(journal_path.parent),
        },
    )
    projection.write_text("drifted after commit", encoding="utf-8")

    with pytest.raises(RuntimeError, match="projection target does not match COMMITTED"):
        promotion.recover_interrupted_promotion(projection)

    assert lock_path.is_file()
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "COMMITTED"


def test_v110_four_target_publish_and_clean_rollback_are_dependency_ordered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    replace_targets: list[Path] = []
    original_replace = promotion._replace_file

    def record_replace(source: Path, target: Path, **kwargs: object) -> None:
        replace_targets.append(target.resolve())
        original_replace(source, target, **kwargs)

    monkeypatch.setattr(promotion, "_replace_file", record_replace)
    result = promotion.publish_science_revision_transaction(**fixture["publish_kwargs"])

    assert replace_targets == [
        targets["active_parent"].resolve(),
        targets["projection"].resolve(),
        targets["archive_manifest"].resolve(),
        targets["transition"].resolve(),
    ]
    assert result["transaction_status"] == "COMMITTED"
    assert result["tool_glue_rollback_ready"] is False
    assert result["transition_candidate_active_parent_sha256"] == fixture["candidate_parent_sha256"]
    assert (
        result["transition_preimage_active_parent_sha256"]
        == fixture["stale_transition_parent_sha256"]
    )

    replace_targets.clear()
    rollback = promotion.rollback_science_revision_transaction(
        journal_path=fixture["journal_path"],
        projection_path=targets["projection"],
    )
    assert replace_targets == [
        targets["transition"].resolve(),
        targets["archive_manifest"].resolve(),
        targets["projection"].resolve(),
        targets["active_parent"].resolve(),
    ]
    assert rollback["transaction_status"] == "ROLLED_BACK"
    assert rollback["rollback_order"] == [
        "transition",
        "archive_manifest",
        "projection",
        "active_parent",
    ]
    assert rollback["tool_glue_rollback_ready"] is True
    assert rollback["next_rollback_dependency"] == "tool-glue-v3.4"
    for label, path in targets.items():
        assert path.read_bytes() == fixture["preimages"][label]


def test_v110_transition_stale_pin_must_be_explicitly_acknowledged_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    kwargs = dict(fixture["publish_kwargs"])
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    kwargs["expected_transition_preimage_active_parent_sha256"] = promotion._sha256(
        targets["active_parent"]
    )

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.publish_science_revision_transaction(**kwargs)

    assert raised.value.code == "SCIENCE_REVISION_PREFLIGHT_FAILED"
    assert any(
        defect["code"] == "SCIENCE_TRANSITION_CONSUMER_REJECTED"
        for defect in raised.value.receipt["defects"]
    )
    assert not Path(fixture["journal_path"]).exists()
    for label, path in targets.items():
        assert path.read_bytes() == fixture["preimages"][label]
    for rollback_copy in fixture["rollback_copies"].values():
        assert not rollback_copy.exists()


@pytest.mark.parametrize(
    "drift_target",
    ["active_parent", "projection", "archive_manifest", "transition"],
)
def test_v110_clean_rollback_refuses_any_committed_postimage_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift_target: str,
) -> None:
    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    promotion.publish_science_revision_transaction(**fixture["publish_kwargs"])
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    committed = {label: path.read_bytes() for label, path in targets.items()}
    _force_write_bytes(targets[drift_target], b"unexpected committed drift")

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.rollback_science_revision_transaction(
            journal_path=fixture["journal_path"],
            projection_path=targets["projection"],
        )

    assert raised.value.code == "SCIENCE_ROLLBACK_POSTIMAGE_DRIFT"
    assert (
        json.loads(Path(fixture["journal_path"]).read_text(encoding="utf-8"))["status"]
        == "COMMITTED"
    )
    assert (
        not targets["projection"].with_name(f"{targets['projection'].name}.promotion.lock").exists()
    )
    for label, path in targets.items():
        expected = b"unexpected committed drift" if label == drift_target else committed[label]
        assert path.read_bytes() == expected


def test_v110_interrupted_apply_recovers_all_four_targets_in_reverse_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    promotion.publish_science_revision_transaction(**fixture["publish_kwargs"])
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    journal_path = Path(fixture["journal_path"])
    journal = json.loads(journal_path.read_text(encoding="utf-8"))

    # Durable crash cut: source/projection/archive were swapped, transition was not.
    _force_write_bytes(targets["transition"], fixture["preimages"]["transition"])
    journal["status"] = "APPLYING"
    # Drop committed postimage pins so recovery treats this as APPLYING, not COMMITTED.
    for key in (
        "projection_committed_sha256",
        "active_parent_committed_sha256",
        "transition_committed_sha256",
        "archive_manifest_committed_sha256",
    ):
        journal.pop(key, None)
    marker_path = _install_bound_transaction(
        projection=targets["projection"],
        journal_path=journal_path,
        journal=journal,
    )

    replace_targets: list[Path] = []
    original_replace = promotion._replace_file

    def record_replace(source: Path, target: Path, **kwargs: object) -> None:
        replace_targets.append(target.resolve())
        original_replace(source, target, **kwargs)

    monkeypatch.setattr(promotion, "_replace_file", record_replace)
    recovery = promotion.recover_interrupted_promotion(targets["projection"])

    assert replace_targets == [
        targets["transition"].resolve(),
        targets["archive_manifest"].resolve(),
        targets["projection"].resolve(),
        targets["active_parent"].resolve(),
    ]
    assert recovery["transaction_status"] == "ROLLED_BACK_AFTER_CRASH"
    assert recovery["tool_glue_rollback_ready"] is True
    assert recovery["next_rollback_dependency"] == "tool-glue-v3.4"
    for label, path in targets.items():
        assert path.read_bytes() == fixture["preimages"][label]
    assert not marker_path.exists()


def test_restore_file_unlinks_readonly_staging_temp_on_windows(tmp_path: Path) -> None:
    source = tmp_path / "before.txt"
    target = tmp_path / "target.txt"
    source.write_text("sealed preimage", encoding="utf-8")
    target.write_text("mutated", encoding="utf-8")
    source.chmod(stat.S_IREAD)
    target.chmod(stat.S_IREAD)

    promotion._restore_file(source, target)

    assert target.read_text(encoding="utf-8") == "sealed preimage"
    assert not target.stat().st_mode & stat.S_IWRITE
    leftovers = list(tmp_path.glob("*.restore"))
    assert leftovers == []


def test_foreign_nonempty_promotion_guard_is_fail_closed(tmp_path: Path) -> None:
    projection, _evidence, _rollback = _fixture(tmp_path)
    guard = promotion._promotion_lease_path(projection)
    guard.write_bytes(b"foreign-tamper-bytes")

    with pytest.raises(RuntimeError, match="foreign or tampered"):
        promotion._acquire_promotion_lease(projection)

    assert guard.read_bytes() == b"foreign-tamper-bytes"


def test_v110_transition_preimage_parent_pin_must_be_explicitly_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    kwargs = dict(fixture["publish_kwargs"])
    kwargs["expected_transition_preimage_active_parent_sha256"] = None
    targets = fixture["targets"]
    assert isinstance(targets, dict)

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.publish_science_revision_transaction(**kwargs)

    assert raised.value.code == "SCIENCE_REVISION_PREFLIGHT_FAILED"
    assert any(
        defect["code"] == "SCIENCE_TRANSITION_PREIMAGE_PARENT_PIN_UNBOUND"
        for defect in raised.value.receipt["defects"]
    )
    assert not Path(fixture["journal_path"]).exists()
    _assert_stable_empty_guard(targets["projection"])
    for label, path in targets.items():
        assert path.read_bytes() == fixture["preimages"][label]


@pytest.mark.parametrize(
    ("mutate", "expected_defect"),
    [
        (
            "drop_projection_version",
            "SCIENCE_DEPENDENCY_TOOL_GLUE_VERSION_MISMATCH",
        ),
        (
            "drift_projection_version",
            "SCIENCE_DEPENDENCY_TOOL_GLUE_VERSION_MISMATCH",
        ),
        (
            "drop_authority_version_line",
            "SCIENCE_DEPENDENCY_TOOL_GLUE_VERSION_MISMATCH",
        ),
        (
            "drift_authority_version_line",
            "SCIENCE_DEPENDENCY_TOOL_GLUE_VERSION_MISMATCH",
        ),
    ],
)
def test_v110_selector_tool_glue_version_missing_or_drift_is_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: str,
    expected_defect: str,
) -> None:
    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    kwargs = dict(fixture["publish_kwargs"])
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    projection = targets["projection"]
    payload = json.loads(projection.read_text(encoding="utf-8"))
    tool_glue = Path(str(kwargs["tool_glue_authority_path"]))

    if mutate == "drop_projection_version":
        payload["software_foundation"].pop("version", None)
        _write_json(projection, payload)
    elif mutate == "drift_projection_version":
        payload["software_foundation"]["version"] = "v3.3"
        _write_json(projection, payload)
    elif mutate == "drop_authority_version_line":
        tool_glue.write_text("no version line\n", encoding="utf-8")
        payload["software_foundation"]["sha256"] = promotion._sha256(tool_glue)
        _write_json(projection, payload)
        kwargs["expected_tool_glue_authority_sha256"] = payload["software_foundation"]["sha256"]
        monkeypatch.setattr(
            promotion,
            "validate_science_revision_candidate_binding",
            lambda *_args, **_kwargs: {
                "science_parent_version": "v1.10",
                "software_foundation_version": None,
                "maturation_invariant_required": True,
            },
        )
    else:
        tool_glue.write_text("版本：v3.3\n", encoding="utf-8")  # noqa: RUF001
        payload["software_foundation"]["sha256"] = promotion._sha256(tool_glue)
        payload["software_foundation"]["version"] = "v3.4"
        _write_json(projection, payload)
        kwargs["expected_tool_glue_authority_sha256"] = payload["software_foundation"]["sha256"]
        monkeypatch.setattr(
            promotion,
            "validate_science_revision_candidate_binding",
            lambda *_args, **_kwargs: {
                "science_parent_version": "v1.10",
                "software_foundation_version": "v3.3",
                "maturation_invariant_required": True,
            },
        )

    kwargs["expected_projection_sha256"] = promotion._sha256(projection)

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.publish_science_revision_transaction(**kwargs)

    assert raised.value.code == "SCIENCE_DEPENDENCY_TOOL_GLUE_PIN_MISMATCH"
    assert any(defect["code"] == expected_defect for defect in raised.value.receipt["defects"])
    assert not Path(fixture["journal_path"]).exists()
    _assert_stable_empty_guard(projection)


@pytest.mark.parametrize(
    "crash_after",
    ["projection", "active_parent", "transition", "archive_manifest"],
)
def test_materializing_crash_cut_is_recoverable_at_each_seal_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_after: str,
) -> None:
    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    order = ["projection", "active_parent", "transition", "archive_manifest"]
    stop_index = order.index(crash_after)
    journal_path = Path(fixture["journal_path"])
    real_write = promotion._write_json_atomic

    def write_until_boundary(path: Path, payload: dict[str, object]) -> None:
        real_write(path, payload)
        if path.resolve() != journal_path.resolve():
            return
        if payload.get("status") != "MATERIALIZING":
            return
        sealed_count = sum(1 for label in order if payload.get(f"{label}_sealed") is True)
        if sealed_count == stop_index + 1 and payload.get(f"{crash_after}_sealed") is True:
            raise RuntimeError(f"simulated crash after sealing {crash_after}")

    monkeypatch.setattr(promotion, "_write_json_atomic", write_until_boundary)
    with pytest.raises(RuntimeError, match=f"simulated crash after sealing {crash_after}"):
        promotion.publish_science_revision_transaction(**fixture["publish_kwargs"])

    marker_path = targets["projection"].with_name(f"{targets['projection'].name}.promotion.lock")
    assert journal_path.is_file()
    assert marker_path.is_file()
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["status"] == "MATERIALIZING"
    for label in order[: stop_index + 1]:
        assert journal[f"{label}_sealed"] is True
        assert journal[f"{label}_original_mode"] is not None
        assert fixture["rollback_copies"][label].is_file()
        assert promotion._sha256(fixture["rollback_copies"][label]) == promotion._sha256_bytes(
            fixture["preimages"][label]
        )
        assert not fixture["rollback_copies"][label].stat().st_mode & stat.S_IWRITE
    for label in order[stop_index + 1 :]:
        assert journal.get(f"{label}_sealed") is False
    for label, path in targets.items():
        assert path.read_bytes() == fixture["preimages"][label]

    recovery = promotion.recover_interrupted_promotion(targets["projection"])
    assert recovery["status"] == "ROLLED_BACK_AFTER_CRASH"
    assert recovery.get("materializing_aborted") is True
    assert not marker_path.exists()
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (
        "ROLLED_BACK_AFTER_CRASH"
    )
    for label, path in targets.items():
        assert path.read_bytes() == fixture["preimages"][label]

    # Exact-hash convergence reuses already sealed rollback copies on retry.
    kwargs = dict(fixture["publish_kwargs"])
    kwargs["transaction_directory"] = tmp_path / "science-transaction-retry"
    kwargs["expected_projection_sha256"] = promotion._sha256(targets["projection"])
    result = promotion.publish_science_revision_transaction(**kwargs)
    assert result["transaction_status"] == "COMMITTED"


def test_promotion_guard_is_persistent_empty_carrier_under_real_concurrency(
    tmp_path: Path,
) -> None:
    projection, _evidence, _rollback = _fixture(tmp_path)
    guard = promotion._promotion_lease_path(projection)
    holder_ready = threading.Event()
    contender_done = threading.Event()
    contender_error: list[str] = []

    def holder() -> None:
        lease = promotion._acquire_promotion_lease(projection)
        holder_ready.set()
        assert contender_done.wait(timeout=5)
        lease.release()

    def contender() -> None:
        assert holder_ready.wait(timeout=5)
        try:
            promotion._acquire_promotion_lease(projection)
            contender_error.append("unexpected acquire")
        except RuntimeError as exc:
            contender_error.append(str(exc))
        finally:
            contender_done.set()

    threads = [threading.Thread(target=holder), threading.Thread(target=contender)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert contender_error == ["science promotion lease is still owned"]
    assert guard.is_file()
    assert guard.stat().st_size == 0
    # Second serial acquire reuses the same durable carrier without unlink race.
    lease = promotion._acquire_promotion_lease(projection)
    lease.release()
    assert guard.is_file()
    assert guard.stat().st_size == 0


def test_promotion_guard_rejects_reparse_and_directory_carriers(tmp_path: Path) -> None:
    projection, _evidence, _rollback = _fixture(tmp_path)
    guard = promotion._promotion_lease_path(projection)
    # Directory is not an ordinary empty file carrier.
    guard.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="not a regular file"):
        promotion._acquire_promotion_lease(projection)
    guard.rmdir()
    # Symlink/reparse is fail-closed.
    target = tmp_path / "foreign-guard-target"
    target.write_bytes(b"")
    try:
        guard.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation requires privilege on this Windows host")
    with pytest.raises(RuntimeError, match="reparse point"):
        promotion._acquire_promotion_lease(projection)


def test_rollback_copy_seal_mode_is_independent_of_live_original_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    # Force writable originals so restore must reinstall write bits from journal.
    for path in targets.values():
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
    original_modes = {label: stat.S_IMODE(path.stat().st_mode) for label, path in targets.items()}
    kwargs = dict(fixture["publish_kwargs"])
    kwargs["expected_projection_sha256"] = promotion._sha256(targets["projection"])
    kwargs["expected_active_parent_sha256"] = promotion._sha256(targets["active_parent"])
    kwargs["expected_transition_sha256"] = promotion._sha256(targets["transition"])
    kwargs["expected_archive_manifest_sha256"] = promotion._sha256(targets["archive_manifest"])

    result = promotion.publish_science_revision_transaction(**kwargs)
    assert result["transaction_status"] == "COMMITTED"
    journal = json.loads(Path(fixture["journal_path"]).read_text(encoding="utf-8"))
    for label in ("projection", "active_parent", "transition", "archive_manifest"):
        assert journal[f"{label}_original_mode"] == original_modes[label]
        assert not fixture["rollback_copies"][label].stat().st_mode & stat.S_IWRITE
        # Live commit installs the original mode, not the sealed rollback mode.
        assert targets[label].stat().st_mode & stat.S_IWRITE
        promotion._assert_restored_mode(label, targets[label], original_modes[label])

    rollback = promotion.rollback_science_revision_transaction(
        journal_path=fixture["journal_path"],
        projection_path=targets["projection"],
    )
    assert rollback["transaction_status"] == "ROLLED_BACK"
    for label, path in targets.items():
        assert path.read_bytes() == fixture["preimages"][label]
        assert path.stat().st_mode & stat.S_IWRITE
        promotion._assert_restored_mode(label, path, original_modes[label])


def test_restore_file_uses_journal_original_mode_not_seal_mode(tmp_path: Path) -> None:
    source = tmp_path / "before.txt"
    target = tmp_path / "target.txt"
    source.write_text("sealed preimage", encoding="utf-8")
    target.write_text("mutated", encoding="utf-8")
    source.chmod(stat.S_IREAD)
    target.chmod(stat.S_IREAD | stat.S_IWRITE)
    # Capture the platform-normalized writable mode, not a bare Unix constant.
    original_mode = stat.S_IMODE(target.stat().st_mode)
    assert original_mode & stat.S_IWRITE

    promotion._restore_file(source, target, installed_mode=original_mode)

    assert target.read_text(encoding="utf-8") == "sealed preimage"
    assert target.stat().st_mode & stat.S_IWRITE
    promotion._assert_restored_mode("target", target, original_mode)
    leftovers = list(tmp_path.glob("*.restore"))
    assert leftovers == []


def test_exact_hash_seal_is_idempotent_across_crash_convergence(tmp_path: Path) -> None:
    live = tmp_path / "live.txt"
    archive = tmp_path / "archive.txt"
    live.write_text("payload", encoding="utf-8")
    live.chmod(stat.S_IREAD | stat.S_IWRITE)
    first = promotion._seal_preimage(live, archive)
    second = promotion._seal_preimage(live, archive)
    assert first.sha256 == second.sha256
    assert first.original_mode == second.original_mode
    assert not archive.stat().st_mode & stat.S_IWRITE
    divergent = tmp_path / "divergent.txt"
    divergent.write_text("other", encoding="utf-8")
    with pytest.raises(FileExistsError, match="divergent content"):
        promotion._seal_preimage(divergent, archive)


def test_seal_preimage_rejects_hardlink_samefile_before_chmod(
    tmp_path: Path,
) -> None:
    """Hardlinked/samefile rollback carriers must never touch live mode/content."""

    live = tmp_path / "live.txt"
    archive = tmp_path / "archive.txt"
    live.write_text("live-payload", encoding="utf-8")
    live.chmod(stat.S_IREAD | stat.S_IWRITE)
    original_live_mode = stat.S_IMODE(live.stat().st_mode)
    original_live_bytes = live.read_bytes()
    try:
        os.link(live, archive)
    except OSError:
        pytest.skip("hardlink creation unsupported on this volume")
    assert archive.samefile(live)
    assert archive.stat().st_nlink >= 2

    with pytest.raises(FileExistsError, match="hardlink|shared inode|samefile"):
        promotion._seal_preimage(live, archive)

    assert live.read_bytes() == original_live_bytes
    assert stat.S_IMODE(live.stat().st_mode) == original_live_mode
    assert live.stat().st_mode & stat.S_IWRITE


def test_seal_preimage_rejects_existing_hardlink_peer_before_chmod(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live.txt"
    archive = tmp_path / "archive.txt"
    peer = tmp_path / "peer.txt"
    live.write_text("live-payload", encoding="utf-8")
    live.chmod(stat.S_IREAD | stat.S_IWRITE)
    archive.write_text("live-payload", encoding="utf-8")
    try:
        os.link(archive, peer)
    except OSError:
        pytest.skip("hardlink creation unsupported on this volume")
    assert archive.stat().st_nlink >= 2
    original_live_mode = stat.S_IMODE(live.stat().st_mode)
    original_live_bytes = live.read_bytes()

    with pytest.raises(FileExistsError, match="hardlink|shared inode"):
        promotion._seal_preimage(live, archive)

    assert live.read_bytes() == original_live_bytes
    assert stat.S_IMODE(live.stat().st_mode) == original_live_mode


def test_v110_four_target_retains_commit_on_post_commit_readback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable COMMITTED four-target journal is never rolled back on readback fail."""

    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    preimages = fixture["preimages"]
    assert isinstance(preimages, dict)
    journal_path = Path(fixture["journal_path"])
    marker_path = targets["projection"].with_name(f"{targets['projection'].name}.promotion.lock")
    calls = 0

    def fail_post_commit_readback(path: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        # Candidate projection validation uses the staged candidate once; live
        # post-commit readback is the final load_science_active_parent call.
        if path.resolve() == targets["projection"].resolve() and journal_path.is_file():
            status = json.loads(journal_path.read_text(encoding="utf-8")).get("status")
            if status == "COMMITTED":
                raise ValueError("v1.10 post-commit consumer readback failed")
        return _ready(path)

    monkeypatch.setattr(promotion, "load_science_active_parent", fail_post_commit_readback)
    with pytest.raises(ValueError, match="v1.10 post-commit consumer readback failed"):
        promotion.publish_science_revision_transaction(**fixture["publish_kwargs"])

    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["status"] == "COMMITTED"
    assert marker_path.is_file()
    for label, path in targets.items():
        assert path.read_bytes() != preimages[label]
        committed_key = f"{label}_committed_sha256"
        if committed_key in journal:
            assert promotion._sha256(path) == journal[committed_key]
    assert promotion._sha256(targets["active_parent"]) == journal["active_parent_committed_sha256"]
    assert promotion._sha256(targets["projection"]) == journal["projection_committed_sha256"]
    assert promotion._sha256(targets["transition"]) == journal["transition_committed_sha256"]
    assert (
        promotion._sha256(targets["archive_manifest"])
        == journal["archive_manifest_committed_sha256"]
    )

    with pytest.raises(ValueError, match="v1.10 post-commit consumer readback failed"):
        promotion.recover_interrupted_promotion(targets["projection"])
    assert marker_path.is_file()
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "COMMITTED"

    monkeypatch.setattr(promotion, "load_science_active_parent", _ready)
    recovery = promotion.recover_interrupted_promotion(targets["projection"])
    assert recovery["status"] == "COMMITTED_LOCK_CLEARED"
    assert not marker_path.exists()
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "COMMITTED"
    assert promotion._sha256(targets["active_parent"]) == journal["active_parent_committed_sha256"]
    assert promotion._sha256(targets["projection"]) == journal["projection_committed_sha256"]


@pytest.mark.parametrize(
    "crash_side",
    [
        "after_pre_journal_before_journal",
        "after_journal_before_journal_bound",
        "after_journal_bound_before_seal",
    ],
)
def test_pre_materialization_crash_cuts_are_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_side: str,
) -> None:
    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    journal_path = Path(fixture["journal_path"])
    marker_path = targets["projection"].with_name(f"{targets['projection'].name}.promotion.lock")
    real_write = promotion._write_json_atomic
    journal_writes = 0

    def crash_at_boundary(path: Path, payload: dict[str, object]) -> None:
        nonlocal journal_writes
        resolved = path.resolve()
        if resolved == marker_path.resolve():
            real_write(path, payload)
            if crash_side == "after_pre_journal_before_journal" and payload.get("phase") == (
                "PRE_JOURNAL"
            ):
                raise RuntimeError("simulated crash after PRE_JOURNAL before journal")
            if crash_side == "after_journal_bound_before_seal" and payload.get("phase") == (
                "JOURNAL_BOUND"
            ):
                raise RuntimeError("simulated crash after JOURNAL_BOUND before first seal")
            return
        if resolved == journal_path.resolve() and payload.get("status") == "MATERIALIZING":
            journal_writes += 1
            real_write(path, payload)
            if crash_side == "after_journal_before_journal_bound" and journal_writes == 1:
                raise RuntimeError("simulated crash after journal before JOURNAL_BOUND")
            return
        real_write(path, payload)

    monkeypatch.setattr(promotion, "_write_json_atomic", crash_at_boundary)
    with pytest.raises(RuntimeError, match="simulated crash"):
        promotion.publish_science_revision_transaction(**fixture["publish_kwargs"])

    for label, path in targets.items():
        assert path.read_bytes() == fixture["preimages"][label]
    for rollback_copy in fixture["rollback_copies"].values():
        assert not Path(str(rollback_copy)).exists()

    if crash_side in {
        "after_pre_journal_before_journal",
        "after_journal_before_journal_bound",
    }:
        assert marker_path.is_file()
        if crash_side == "after_pre_journal_before_journal":
            assert not journal_path.exists()
            assert json.loads(marker_path.read_text(encoding="utf-8"))["phase"] == "PRE_JOURNAL"
        else:
            assert journal_path.is_file()
            assert json.loads(marker_path.read_text(encoding="utf-8"))["phase"] == "PRE_JOURNAL"
        recovery = promotion.recover_interrupted_promotion(targets["projection"])
        assert recovery["status"] == "PRE_MATERIALIZATION_ABORTED"
        assert recovery.get("pre_materialization_anchor_cleared") is True
        assert not marker_path.exists()
        # Republish must not be permanently blocked by a PRE_JOURNAL anchor.
        monkeypatch.setattr(promotion, "_write_json_atomic", real_write)
        kwargs = dict(fixture["publish_kwargs"])
        if crash_side == "after_journal_before_journal_bound":
            kwargs["transaction_directory"] = tmp_path / "science-transaction-retry"
        kwargs["expected_projection_sha256"] = promotion._sha256(targets["projection"])
        result = promotion.publish_science_revision_transaction(**kwargs)
        assert result["transaction_status"] == "COMMITTED"
        return

    assert marker_path.is_file()
    assert journal_path.is_file()
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["status"] == "MATERIALIZING"
    assert journal.get("projection_sealed") is False
    assert json.loads(marker_path.read_text(encoding="utf-8"))["phase"] == "JOURNAL_BOUND"
    recovery = promotion.recover_interrupted_promotion(targets["projection"])
    assert recovery["status"] == "ROLLED_BACK_AFTER_CRASH"
    assert recovery.get("materializing_aborted") is True
    assert not marker_path.exists()
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == (
        "ROLLED_BACK_AFTER_CRASH"
    )
    for label, path in targets.items():
        assert path.read_bytes() == fixture["preimages"][label]
    monkeypatch.setattr(promotion, "_write_json_atomic", real_write)
    kwargs = dict(fixture["publish_kwargs"])
    kwargs["transaction_directory"] = tmp_path / "science-transaction-retry"
    kwargs["expected_projection_sha256"] = promotion._sha256(targets["projection"])
    result = promotion.publish_science_revision_transaction(**kwargs)
    assert result["transaction_status"] == "COMMITTED"


def test_cross_object_restore_rejects_foreign_active_parent_path(
    tmp_path: Path,
) -> None:
    """Forged APPLYING journals may not restore a substituted active-parent object."""

    projection, _evidence, rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    live_parent = Path(payload["active_parent"]["path"])
    original_parent = live_parent.read_bytes()
    original_projection = projection.read_bytes()
    foreign_parent = tmp_path / "foreign-active-parent.txt"
    foreign_parent.write_text("foreign object body", encoding="utf-8")
    foreign_original = foreign_parent.read_bytes()
    foreign_preimage = tmp_path / "rollback" / "foreign.before.txt"
    foreign_preimage.parent.mkdir(parents=True, exist_ok=True)
    foreign_preimage.write_bytes(b"foreign preimage that must not land")
    rollback.parent.mkdir(parents=True, exist_ok=True)
    rollback.write_bytes(original_projection)
    rollback.chmod(stat.S_IREAD)
    parent_rollback = tmp_path / "rollback" / "live-parent.before.txt"
    parent_rollback.write_bytes(original_parent)
    parent_rollback.chmod(stat.S_IREAD)
    candidate = tmp_path / "candidate-parent.txt"
    candidate.write_text("candidate active parent", encoding="utf-8")
    candidate_projection = tmp_path / "candidate-projection.json"
    candidate_payload = json.loads(projection.read_text(encoding="utf-8"))
    candidate_payload["active_parent"]["sha256"] = promotion._sha256(candidate)
    _write_json(candidate_projection, candidate_payload)
    journal_path = tmp_path / "transaction" / "transaction.v1.json"
    lock_path = _install_bound_transaction(
        projection=projection,
        journal_path=journal_path,
        journal={
            "status": "APPLYING",
            "projection_path": str(projection),
            "projection_preimage_sha256": promotion._sha256(rollback),
            "projection_candidate_sha256": promotion._sha256(candidate_projection),
            "projection_rollback_copy": str(rollback),
            "projection_candidate_path": str(candidate_projection),
            # Cross-object substitution: journal points restore at a foreign path.
            "active_parent_path": str(foreign_parent),
            "active_parent_preimage_sha256": promotion._sha256(foreign_preimage),
            "active_parent_candidate_sha256": promotion._sha256(candidate),
            "active_parent_rollback_copy": str(foreign_preimage),
            "active_parent_candidate_path": str(candidate),
            "transaction_directory": str(journal_path.parent),
        },
    )
    # Mid-apply look: foreign object appears mutated while live parent is untouched.
    foreign_parent.write_bytes(candidate.read_bytes())

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.recover_interrupted_promotion(projection)

    assert raised.value.code == "CROSS_OBJECT_RESTORE"
    assert lock_path.is_file()
    assert live_parent.read_bytes() == original_parent
    assert projection.read_bytes() == original_projection
    assert foreign_parent.read_bytes() == candidate.read_bytes()
    assert foreign_preimage.read_bytes() == b"foreign preimage that must not land"
    assert json.loads(journal_path.read_text(encoding="utf-8"))["status"] == "APPLYING"
    # Foreign original body must not be restored from the forged preimage.
    assert foreign_parent.read_bytes() != foreign_original
    assert foreign_parent.read_bytes() != foreign_preimage.read_bytes()


def test_delete_after_journal_bound_fails_closed_and_retains_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Journal deletion under JOURNAL_BOUND must never false-abort mid-apply live state."""

    fixture = _four_target_v110_fixture(tmp_path, monkeypatch)
    targets = fixture["targets"]
    assert isinstance(targets, dict)
    preimages = dict(fixture["preimages"])
    assert isinstance(preimages, dict)
    promotion.publish_science_revision_transaction(**fixture["publish_kwargs"])
    journal_path = Path(fixture["journal_path"])
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    # Simulate crash after apply began: keep postimages, re-open APPLYING under JOURNAL_BOUND.
    for key in (
        "projection_committed_sha256",
        "active_parent_committed_sha256",
        "transition_committed_sha256",
        "archive_manifest_committed_sha256",
    ):
        journal.pop(key, None)
    journal["status"] = "APPLYING"
    marker_path = _install_bound_transaction(
        projection=targets["projection"],
        journal_path=journal_path,
        journal=journal,
    )
    mid_apply = {label: path.read_bytes() for label, path in targets.items()}
    assert any(mid_apply[label] != preimages[label] for label in mid_apply)
    journal_path.unlink()
    assert not journal_path.exists()
    assert marker_path.is_file()
    assert json.loads(marker_path.read_text(encoding="utf-8"))["phase"] == "JOURNAL_BOUND"

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.recover_interrupted_promotion(targets["projection"])

    assert raised.value.code == "SCIENCE_JOURNAL_BOUND_MISSING"
    assert raised.value.receipt.get("marker_retained") is True
    assert marker_path.is_file()
    assert json.loads(marker_path.read_text(encoding="utf-8"))["phase"] == "JOURNAL_BOUND"
    for label, path in targets.items():
        assert path.read_bytes() == mid_apply[label]
    # Still blocked for republish while JOURNAL_BOUND marker remains without journal.
    with pytest.raises(RuntimeError, match="interrupted science promotion requires recovery"):
        kwargs = dict(fixture["publish_kwargs"])
        kwargs["transaction_directory"] = tmp_path / "science-transaction-retry"
        kwargs["expected_projection_sha256"] = promotion._sha256(targets["projection"])
        promotion.publish_science_revision_transaction(**kwargs)


def test_forged_identity_and_path_pins_are_rejected(tmp_path: Path) -> None:
    projection, _evidence, rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    original_parent = active_parent.read_bytes()
    original_projection = projection.read_bytes()
    rollback.parent.mkdir(parents=True, exist_ok=True)
    rollback.write_bytes(original_projection)
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.parent.mkdir(parents=True, exist_ok=True)
    parent_rollback.write_bytes(original_parent)
    journal_path = tmp_path / "transaction" / "transaction.v1.json"
    journal = {
        "schema_version": "xinao.science_revision_transaction.v1",
        "status": "APPLYING",
        "projection_path": str(projection),
        "projection_preimage_sha256": promotion._sha256(rollback),
        "projection_candidate_sha256": "a" * 64,
        "projection_rollback_copy": str(rollback),
        "projection_candidate_path": str(tmp_path / "cand-projection.json"),
        "active_parent_path": str(active_parent),
        "active_parent_preimage_sha256": promotion._sha256(active_parent),
        "active_parent_candidate_sha256": "b" * 64,
        "active_parent_rollback_copy": str(parent_rollback),
        "active_parent_candidate_path": str(tmp_path / "cand-parent.txt"),
        "transaction_directory": str(journal_path.parent),
    }
    identity = promotion._transaction_identity_sha256(
        journal, transaction_directory=journal_path.parent
    )
    journal["transaction_identity_sha256"] = identity
    promotion._write_json_atomic(journal_path, journal)
    # Marker carries a forged identity digest that does not match journal pins.
    marker_path = projection.with_name(f"{projection.name}.promotion.lock")
    promotion._write_json_atomic(
        marker_path,
        promotion._marker_payload(
            phase="JOURNAL_BOUND",
            journal_path=journal_path,
            projection_path=projection,
            transaction_directory=journal_path.parent,
            transaction_identity_sha256="c" * 64,
        ),
    )
    # Also forge a path pin after the journal was sealed into identity.
    tampered = json.loads(journal_path.read_text(encoding="utf-8"))
    tampered["active_parent_path"] = str(tmp_path / "substituted-parent.txt")
    (tmp_path / "substituted-parent.txt").write_text("substituted", encoding="utf-8")
    promotion._write_json_atomic(journal_path, tampered)

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.recover_interrupted_promotion(projection)

    assert raised.value.code in {
        "SCIENCE_TRANSACTION_IDENTITY_MISMATCH",
        "CROSS_OBJECT_RESTORE",
    }
    assert marker_path.is_file()
    assert active_parent.read_bytes() == original_parent
    assert projection.read_bytes() == original_projection


def test_foreign_marker_bytes_are_fail_closed(tmp_path: Path) -> None:
    projection, _evidence, _rollback = _fixture(tmp_path)
    marker_path = projection.with_name(f"{projection.name}.promotion.lock")
    marker_path.write_bytes(b"foreign-marker-bytes-not-json")

    with pytest.raises((promotion.SciencePublicationError, ValueError, json.JSONDecodeError)):
        promotion.recover_interrupted_promotion(projection)

    assert marker_path.is_file()
    assert marker_path.read_bytes() == b"foreign-marker-bytes-not-json"


def test_promotion_guard_rejects_hardlink_carrier(tmp_path: Path) -> None:
    projection, _evidence, _rollback = _fixture(tmp_path)
    guard = promotion._promotion_lease_path(projection)
    peer = tmp_path / "guard-peer"
    guard.write_bytes(b"")
    try:
        os.link(guard, peer)
    except OSError:
        pytest.skip("hardlink creation unsupported on this volume")
    assert guard.stat().st_nlink >= 2

    with pytest.raises(RuntimeError, match="hardlink|shared inode"):
        promotion._acquire_promotion_lease(projection)

    assert guard.is_file()
    assert guard.stat().st_size == 0


def test_promotion_guard_serializes_independent_processes(tmp_path: Path) -> None:
    """True cross-process lock serialization on the persistent empty guard."""

    projection, _evidence, _rollback = _fixture(tmp_path)
    guard = promotion._promotion_lease_path(projection)
    ready_path = tmp_path / "holder_ready"
    release_path = tmp_path / "holder_release"
    holder_script = f"""
import sys, time
from pathlib import Path
sys.path.insert(0, {str(Path.cwd().resolve())!r})
from scripts import promote_science_revision_chain as promotion
projection = Path({str(projection.resolve())!r})
ready = Path({str(ready_path.resolve())!r})
release = Path({str(release_path.resolve())!r})
lease = promotion._acquire_promotion_lease(projection)
ready.write_text("ready", encoding="utf-8")
deadline = time.time() + 20
while not release.exists() and time.time() < deadline:
    time.sleep(0.05)
lease.release()
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_script],
        cwd=str(Path.cwd()),
    )
    try:
        deadline = time.time() + 20
        while not ready_path.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert ready_path.exists(), "holder process failed to acquire lease"
        with pytest.raises(RuntimeError, match="still owned"):
            promotion._acquire_promotion_lease(projection)
        release_path.write_text("release", encoding="utf-8")
        assert holder.wait(timeout=20) == 0
        lease = promotion._acquire_promotion_lease(projection)
        lease.release()
        assert guard.is_file()
        assert guard.stat().st_size == 0
        assert not promotion._is_reparse_path(guard)
        assert guard.stat().st_nlink == 1
    finally:
        release_path.write_text("release", encoding="utf-8")
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)


def _v110_topology_journal(
    tmp_path: Path,
    *,
    projection: Path,
    active_parent: Path,
    projection_rollback: Path,
    parent_rollback: Path,
    transition_rollback: Path | None = None,
    archive_rollback: Path | None = None,
    transition_candidate: Path | None = None,
    archive_candidate: Path | None = None,
    active_parent_candidate: Path | None = None,
    projection_candidate: Path | None = None,
) -> dict[str, object]:
    """Build a minimal four-object journal body for topology unit probes."""

    transition = tmp_path / "topology-transition.txt"
    archive = tmp_path / "topology-archive.json"
    if not transition.exists():
        transition.write_text("transition-body", encoding="utf-8")
    if not archive.exists():
        archive.write_text("{}", encoding="utf-8")
    tc = transition_candidate or (tmp_path / "topology-transition.candidate.txt")
    ac = archive_candidate or (tmp_path / "topology-archive.candidate.json")
    if not tc.exists():
        tc.write_text("transition-candidate", encoding="utf-8")
    if not ac.exists():
        ac.write_text("{}", encoding="utf-8")
    trb = transition_rollback or (tmp_path / "rollback" / "transition.before.txt")
    arb = archive_rollback or (tmp_path / "rollback" / "archive.before.json")
    trb.parent.mkdir(parents=True, exist_ok=True)
    if not trb.exists():
        trb.write_bytes(transition.read_bytes())
    if not arb.exists():
        arb.write_bytes(archive.read_bytes())
    parent_cand = active_parent_candidate or active_parent
    proj_cand = projection_candidate or (tmp_path / "projection.candidate.json")
    if not proj_cand.exists():
        proj_cand.write_bytes(projection.read_bytes())
    return {
        "projection_path": str(projection),
        "projection_preimage_sha256": promotion._sha256(projection_rollback),
        "projection_rollback_copy": str(projection_rollback),
        "projection_candidate_path": str(proj_cand),
        "active_parent_path": str(active_parent),
        "active_parent_preimage_sha256": promotion._sha256(active_parent),
        "active_parent_rollback_copy": str(parent_rollback),
        "active_parent_candidate_path": str(parent_cand),
        "transition_path": str(transition),
        "transition_preimage_sha256": promotion._sha256(transition),
        "transition_candidate_sha256": promotion._sha256(tc),
        "transition_candidate_path": str(tc),
        "transition_rollback_copy": str(trb),
        "archive_manifest_path": str(archive),
        "archive_manifest_preimage_sha256": promotion._sha256(archive),
        "archive_manifest_candidate_sha256": promotion._sha256(ac),
        "archive_manifest_candidate_path": str(ac),
        "archive_manifest_rollback_copy": str(arb),
    }


def test_topology_rejects_transition_rollback_aliasing_active_parent(
    tmp_path: Path,
) -> None:
    """Transition/archive rollback carriers must not alias live parent/projection."""

    projection, _evidence, projection_rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    projection_rollback.parent.mkdir(parents=True, exist_ok=True)
    projection_rollback.write_bytes(projection.read_bytes())
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.write_bytes(active_parent.read_bytes())

    journal = _v110_topology_journal(
        tmp_path,
        projection=projection,
        active_parent=active_parent,
        projection_rollback=projection_rollback,
        parent_rollback=parent_rollback,
        transition_rollback=active_parent,
    )
    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion._validate_journal_object_topology(journal, projection_path=projection)
    assert raised.value.code == "CROSS_OBJECT_RESTORE"
    assert "transition_rollback_copy" in str(raised.value)

    journal_archive = _v110_topology_journal(
        tmp_path,
        projection=projection,
        active_parent=active_parent,
        projection_rollback=projection_rollback,
        parent_rollback=parent_rollback,
        archive_rollback=projection,
    )
    with pytest.raises(promotion.SciencePublicationError) as raised_archive:
        promotion._validate_journal_object_topology(journal_archive, projection_path=projection)
    assert raised_archive.value.code == "CROSS_OBJECT_RESTORE"
    assert "archive_manifest_rollback_copy" in str(raised_archive.value)


def test_topology_rejects_projection_rollback_aliasing_active_parent(
    tmp_path: Path,
) -> None:
    projection, _evidence, _rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.parent.mkdir(parents=True, exist_ok=True)
    parent_rollback.write_bytes(active_parent.read_bytes())
    journal = {
        "projection_path": str(projection),
        "projection_preimage_sha256": promotion._sha256(projection),
        "projection_rollback_copy": str(active_parent),
        "active_parent_path": str(active_parent),
        "active_parent_preimage_sha256": promotion._sha256(active_parent),
        "active_parent_rollback_copy": str(parent_rollback),
    }
    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion._validate_journal_object_topology(journal, projection_path=projection)
    assert raised.value.code == "CROSS_OBJECT_RESTORE"


def test_topology_allows_in_place_candidate_equals_own_live(tmp_path: Path) -> None:
    """candidate == its own live target remains legitimate in-place publication."""

    projection, _evidence, projection_rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    projection_rollback.parent.mkdir(parents=True, exist_ok=True)
    projection_rollback.write_bytes(projection.read_bytes())
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.write_bytes(active_parent.read_bytes())
    journal = _v110_topology_journal(
        tmp_path,
        projection=projection,
        active_parent=active_parent,
        projection_rollback=projection_rollback,
        parent_rollback=parent_rollback,
        active_parent_candidate=active_parent,
        projection_candidate=projection,
    )
    promotion._validate_journal_object_topology(journal, projection_path=projection)


def test_topology_rejects_cross_object_candidate_live_alias(tmp_path: Path) -> None:
    projection, _evidence, projection_rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    projection_rollback.parent.mkdir(parents=True, exist_ok=True)
    projection_rollback.write_bytes(projection.read_bytes())
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.write_bytes(active_parent.read_bytes())
    journal = _v110_topology_journal(
        tmp_path,
        projection=projection,
        active_parent=active_parent,
        projection_rollback=projection_rollback,
        parent_rollback=parent_rollback,
        # Cross-object: active-parent candidate points at the projection live path.
        active_parent_candidate=projection,
    )
    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion._validate_journal_object_topology(journal, projection_path=projection)
    assert raised.value.code == "CROSS_OBJECT_RESTORE"
    assert "active_parent_candidate_path" in str(raised.value)


def test_topology_rejects_identical_content_rollback_path_alias_of_live(
    tmp_path: Path,
) -> None:
    """Same-bytes rollback path that is another live authority is still rejected."""

    projection, _evidence, projection_rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    projection_rollback.parent.mkdir(parents=True, exist_ok=True)
    projection_rollback.write_bytes(projection.read_bytes())
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.write_bytes(active_parent.read_bytes())
    transition = tmp_path / "topology-transition.txt"
    body = b"IDENTICAL_AUTHORITY_BODY"
    transition.write_bytes(body)
    # Another live authority holds identical content; using it as transition rollback
    # would let seal strip its write bit without hardlink identity.
    active_parent.write_bytes(body)
    # Keep projection binding consistent with the rewritten parent bytes.
    payload["active_parent"]["sha256"] = promotion._sha256(active_parent)
    _write_json(projection, payload)
    projection_rollback.write_bytes(projection.read_bytes())
    parent_rollback.write_bytes(active_parent.read_bytes())

    journal = _v110_topology_journal(
        tmp_path,
        projection=projection,
        active_parent=active_parent,
        projection_rollback=projection_rollback,
        parent_rollback=parent_rollback,
        transition_rollback=active_parent,
    )
    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion._validate_journal_object_topology(journal, projection_path=projection)
    assert raised.value.code == "CROSS_OBJECT_RESTORE"
    assert "transition_rollback_copy" in str(raised.value)


def test_topology_rejects_hardlink_rollback_to_live_authority(tmp_path: Path) -> None:
    projection, _evidence, projection_rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    projection_rollback.parent.mkdir(parents=True, exist_ok=True)
    projection_rollback.write_bytes(projection.read_bytes())
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.write_bytes(active_parent.read_bytes())
    transition_rollback = tmp_path / "rollback" / "transition.hardlink.txt"
    transition_rollback.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(active_parent, transition_rollback)
    except OSError:
        pytest.skip("hardlink creation unsupported on this volume")
    assert transition_rollback.samefile(active_parent)
    journal = _v110_topology_journal(
        tmp_path,
        projection=projection,
        active_parent=active_parent,
        projection_rollback=projection_rollback,
        parent_rollback=parent_rollback,
        transition_rollback=transition_rollback,
    )
    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion._validate_journal_object_topology(journal, projection_path=projection)
    assert raised.value.code == "CROSS_OBJECT_RESTORE"


def test_topology_rejects_hardlink_between_rollback_carriers(tmp_path: Path) -> None:
    projection, _evidence, projection_rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    projection_rollback.parent.mkdir(parents=True, exist_ok=True)
    projection_rollback.write_bytes(projection.read_bytes())
    parent_rollback = tmp_path / "rollback" / "parent.before.txt"
    parent_rollback.write_bytes(active_parent.read_bytes())
    transition_rollback = tmp_path / "rollback" / "transition.before.txt"
    try:
        os.link(parent_rollback, transition_rollback)
    except OSError:
        pytest.skip("hardlink creation unsupported on this volume")
    journal = _v110_topology_journal(
        tmp_path,
        projection=projection,
        active_parent=active_parent,
        projection_rollback=projection_rollback,
        parent_rollback=parent_rollback,
        transition_rollback=transition_rollback,
    )
    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion._validate_journal_object_topology(journal, projection_path=projection)
    assert raised.value.code == "CROSS_OBJECT_RESTORE"


def test_topology_rejects_shared_path_between_rollback_carriers(tmp_path: Path) -> None:
    projection, _evidence, projection_rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    projection_rollback.parent.mkdir(parents=True, exist_ok=True)
    projection_rollback.write_bytes(projection.read_bytes())
    parent_rollback = tmp_path / "rollback" / "shared.rollback.txt"
    parent_rollback.write_bytes(active_parent.read_bytes())
    journal = _v110_topology_journal(
        tmp_path,
        projection=projection,
        active_parent=active_parent,
        projection_rollback=projection_rollback,
        parent_rollback=parent_rollback,
        transition_rollback=parent_rollback,
    )
    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion._validate_journal_object_topology(journal, projection_path=projection)
    assert raised.value.code == "CROSS_OBJECT_RESTORE"


def test_recovery_trust_boundary_rejects_inconsistent_substitution_and_documents_scope(
    tmp_path: Path,
) -> None:
    """Honest recovery scope: inconsistent path substitution blocked; no crypto claim.

    Existing thin anchors (projection recovery target, marker identity, sealed
    projection preimage + topology pins) rebind the original live object graph for
    *inconsistent* journals without a second truth. Coherent rewrite of every
    transaction and authority file under the same-user filesystem is outside the
    recovery adversary model (see RECOVERY_TRUST_BOUNDARY).
    """

    assert promotion.RECOVERY_TRUST_BOUNDARY == (
        "same-user-filesystem-crash-and-inconsistent-substitution"
    )
    projection, _evidence, rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    live_parent = Path(payload["active_parent"]["path"])
    original_parent = live_parent.read_bytes()
    original_projection = projection.read_bytes()
    foreign_parent = tmp_path / "foreign-active-parent.txt"
    foreign_parent.write_text("foreign object body", encoding="utf-8")
    foreign_preimage = tmp_path / "rollback" / "foreign.before.txt"
    foreign_preimage.parent.mkdir(parents=True, exist_ok=True)
    foreign_preimage.write_bytes(b"foreign preimage that must not land")
    rollback.parent.mkdir(parents=True, exist_ok=True)
    # Sealed preimage still binds the *original* live parent — inconsistent with
    # the journal's substituted foreign active_parent_path.
    rollback.write_bytes(original_projection)
    rollback.chmod(stat.S_IREAD)
    candidate = tmp_path / "candidate-parent.txt"
    candidate.write_text("candidate active parent", encoding="utf-8")
    candidate_projection = tmp_path / "candidate-projection.json"
    candidate_payload = json.loads(projection.read_text(encoding="utf-8"))
    candidate_payload["active_parent"]["sha256"] = promotion._sha256(candidate)
    _write_json(candidate_projection, candidate_payload)
    journal_path = tmp_path / "transaction" / "transaction.v1.json"
    lock_path = _install_bound_transaction(
        projection=projection,
        journal_path=journal_path,
        journal={
            "status": "APPLYING",
            "projection_path": str(projection),
            "projection_preimage_sha256": promotion._sha256(rollback),
            "projection_candidate_sha256": promotion._sha256(candidate_projection),
            "projection_rollback_copy": str(rollback),
            "projection_candidate_path": str(candidate_projection),
            "active_parent_path": str(foreign_parent),
            "active_parent_preimage_sha256": promotion._sha256(foreign_preimage),
            "active_parent_candidate_sha256": promotion._sha256(candidate),
            "active_parent_rollback_copy": str(foreign_preimage),
            "active_parent_candidate_path": str(candidate),
            "transaction_directory": str(journal_path.parent),
        },
    )
    foreign_parent.write_bytes(candidate.read_bytes())

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.recover_interrupted_promotion(projection)

    assert raised.value.code == "CROSS_OBJECT_RESTORE"
    assert lock_path.is_file()
    assert live_parent.read_bytes() == original_parent
    assert projection.read_bytes() == original_projection
    assert foreign_parent.read_bytes() != foreign_preimage.read_bytes()
    assert "coherent" in (promotion.recover_interrupted_promotion.__doc__ or "").lower() or (
        "RECOVERY_TRUST_BOUNDARY" in (promotion.recover_interrupted_promotion.__doc__ or "")
    )


def test_seal_preimage_identical_content_independent_archive_converges(
    tmp_path: Path,
) -> None:
    """Independent same-content archive remains valid crash-convergence for its live."""

    live = tmp_path / "live.txt"
    archive = tmp_path / "archive.txt"
    body = b"IDENTICAL_BODY"
    live.write_bytes(body)
    archive.write_bytes(body)
    live.chmod(stat.S_IREAD | stat.S_IWRITE)
    archive.chmod(stat.S_IREAD | stat.S_IWRITE)
    original_live_mode = stat.S_IMODE(live.stat().st_mode)
    sealed = promotion._seal_preimage(live, archive)
    assert sealed.sha256 == promotion._sha256_bytes(body)
    assert not archive.stat().st_mode & stat.S_IWRITE
    # Independent archive seal must not strip write from the live target.
    assert stat.S_IMODE(live.stat().st_mode) == original_live_mode
    assert live.stat().st_mode & stat.S_IWRITE
    assert live.read_bytes() == body
