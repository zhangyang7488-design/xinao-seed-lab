from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from scripts import promote_science_revision_chain as promotion


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


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
        "expected_transition_preimage_active_parent_sha256": (
            stale_transition_parent_sha256
        ),
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
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

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

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not rollback.exists()
    assert not projection.with_name(f"{projection.name}.promotion.lock").exists()


def test_science_v110_publication_requires_exact_live_tool_glue_pin_before_mutation(
    tmp_path: Path,
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    candidate_active_parent = tmp_path / "science-v1.10-candidate.txt"
    candidate_active_parent.write_text("science v1.10 candidate", encoding="utf-8")
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
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

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
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not rollback.exists()
    assert not active_parent_rollback.exists()
    assert not transition_rollback.exists()
    assert not archive_manifest_rollback.exists()
    assert not transaction_directory.exists()
    assert not projection.with_name(f"{projection.name}.promotion.lock").exists()


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
    assert lease_path.is_file()
    reacquired_lease = promotion._acquire_promotion_lease(projection)
    reacquired_lease.release()


def test_recovery_rejects_journal_bound_to_another_projection(tmp_path: Path) -> None:
    projection, _evidence, _rollback = _fixture(tmp_path)
    other_projection = tmp_path / "other-projection.json"
    other_projection.write_bytes(projection.read_bytes())
    journal_path = tmp_path / "transaction" / "transaction.v1.json"
    lock_path = projection.with_name(f"{projection.name}.promotion.lock")
    promotion._write_json_atomic(
        journal_path,
        {
            "schema_version": "xinao.science_revision_transaction.v1",
            "status": "COMMITTED",
            "projection_path": str(other_projection),
        },
    )
    promotion._write_json_atomic(lock_path, {"journal_path": str(journal_path)})

    with pytest.raises(RuntimeError, match="does not bind recovery target"):
        promotion.recover_interrupted_promotion(projection)

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
    lock_path = projection.with_name(f"{projection.name}.promotion.lock")
    promotion._write_json_atomic(
        journal_path,
        {
            "schema_version": "xinao.science_revision_transaction.v1",
            "status": "APPLYING",
            "projection_path": str(projection),
            "projection_preimage_sha256": promotion._sha256(projection),
            "projection_candidate_sha256": candidate_projection_sha256,
            "projection_rollback_copy": str(rollback),
            "active_parent_path": str(active_parent),
            "active_parent_preimage_sha256": old_parent_sha256,
            "active_parent_candidate_sha256": candidate_parent_sha256,
            "active_parent_rollback_copy": str(parent_rollback),
        },
    )
    lock_path.write_text(
        json.dumps({"journal_path": str(journal_path)}) + "\n",
        encoding="utf-8",
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
        ),
        (
            "active-parent",
            parent_preimage,
            parent_target,
            promotion._sha256(parent_preimage),
        ),
    ]
    real_restore = promotion._restore_file
    attempted: list[Path] = []

    def fail_projection_restore(source: Path, target: Path) -> None:
        attempted.append(target)
        if target == projection_target:
            raise PermissionError("projection rollback blocked")
        real_restore(source, target)

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
    lock_path = projection.with_name(f"{projection.name}.promotion.lock")
    promotion._write_json_atomic(
        journal_path,
        {
            "schema_version": "xinao.science_revision_transaction.v1",
            "status": "APPLYING",
            "projection_path": str(projection),
            "projection_preimage_sha256": promotion._sha256(rollback),
            "projection_candidate_sha256": candidate_projection_sha256,
            "projection_rollback_copy": str(rollback),
            "active_parent_path": str(active_parent),
            "active_parent_preimage_sha256": old_parent_sha256,
            "active_parent_candidate_sha256": candidate_parent_sha256,
            "active_parent_rollback_copy": str(parent_rollback),
        },
    )
    promotion._write_json_atomic(lock_path, {"journal_path": str(journal_path)})
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
    projection, _evidence, _rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    active_parent = Path(payload["active_parent"]["path"])
    committed_projection_sha256 = promotion._sha256(projection)
    journal_path = tmp_path / "transaction" / "transaction.v1.json"
    lock_path = projection.with_name(f"{projection.name}.promotion.lock")
    promotion._write_json_atomic(
        journal_path,
        {
            "schema_version": "xinao.science_revision_transaction.v1",
            "status": "COMMITTED",
            "projection_path": str(projection),
            "projection_committed_sha256": committed_projection_sha256,
            "active_parent_path": str(active_parent),
            "active_parent_committed_sha256": promotion._sha256(active_parent),
        },
    )
    promotion._write_json_atomic(lock_path, {"journal_path": str(journal_path)})
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
    assert result["transition_candidate_active_parent_sha256"] == fixture[
        "candidate_parent_sha256"
    ]
    assert result["transition_preimage_active_parent_sha256"] == fixture[
        "stale_transition_parent_sha256"
    ]

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
    targets[drift_target].write_bytes(b"unexpected committed drift")

    with pytest.raises(promotion.SciencePublicationError) as raised:
        promotion.rollback_science_revision_transaction(
            journal_path=fixture["journal_path"],
            projection_path=targets["projection"],
        )

    assert raised.value.code == "SCIENCE_ROLLBACK_POSTIMAGE_DRIFT"
    assert json.loads(Path(fixture["journal_path"]).read_text(encoding="utf-8"))[
        "status"
    ] == "COMMITTED"
    assert not targets["projection"].with_name(
        f"{targets['projection'].name}.promotion.lock"
    ).exists()
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
    targets["transition"].write_bytes(fixture["preimages"]["transition"])
    journal["status"] = "APPLYING"
    promotion._write_json_atomic(journal_path, journal)
    marker_path = targets["projection"].with_name(
        f"{targets['projection'].name}.promotion.lock"
    )
    promotion._write_json_atomic(marker_path, {"journal_path": str(journal_path)})

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
