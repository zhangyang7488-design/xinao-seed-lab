from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import promote_science_revision_chain as promotion


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    projection = tmp_path / "active_parent.current.json"
    evidence = tmp_path / "science_revision.v1.json"
    rollback = tmp_path / "rollback" / "active_parent.before.json"
    _write_json(
        projection,
        {
            "schema_version": "xinao.science_active_parent_projection.v1",
            "active_parent": {"sha256": "old"},
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
    assert len(payload["science_revision_chain"]) == 1
    return {"status": "READY", "active_parent": {"sha256": "current"}}


def test_promote_revision_chain_keeps_immutable_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    original = projection.read_bytes()
    monkeypatch.setattr(promotion, "load_science_active_parent", _ready)

    result = promotion.promote_revision_chain(
        projection_path=projection,
        evidence_paths=[evidence],
        event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
        rollback_copy=rollback,
    )

    assert result["status"] == "VERIFIED"
    assert result["revision_count"] == 1
    assert rollback.read_bytes() == original
    assert (
        json.loads(projection.read_text(encoding="utf-8"))["science_revision_chain"][0]["run_id"]
        == "revision-run"
    )


def test_promote_revision_chain_restores_live_projection_on_post_swap_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    original = projection.read_bytes()
    calls = 0

    def fail_live_validation(path: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
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

    assert projection.read_bytes() == original
    assert rollback.read_bytes() == original


def test_promote_revision_chain_refuses_to_rewrite_existing_chain(
    tmp_path: Path,
) -> None:
    projection, evidence, rollback = _fixture(tmp_path)
    payload = json.loads(projection.read_text(encoding="utf-8"))
    payload["science_revision_chain"] = [{"status": "APPLIED"}]
    _write_json(projection, payload)

    with pytest.raises(ValueError, match="already contains"):
        promotion.promote_revision_chain(
            projection_path=projection,
            evidence_paths=[evidence],
            event_refs=[str(tmp_path / "events.jsonl") + "#event_id=revision"],
            rollback_copy=rollback,
        )
