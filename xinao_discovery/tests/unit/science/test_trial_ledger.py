from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from xinao.science.trial_ledger import (
    EMPTY_SCIENCE_TRIAL_ENTRIES_SHA256,
    ScienceTrialLedgerError,
    append_science_trial_entry,
    load_science_trial_journal,
    science_trial_journal_path,
)


def _anchor(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "science_trial_ledger.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "xinao.science_trial_ledger.v1",
                "episode_id": "episode-1",
                "append_only": True,
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    import hashlib

    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _register(
    anchor: Path,
    anchor_hash: str,
    *,
    event_id: str = "register-1",
    work_key: str = "trial-1",
    expected_count: int = 0,
    expected_head: str = EMPTY_SCIENCE_TRIAL_ENTRIES_SHA256,
) -> dict[str, object]:
    return append_science_trial_entry(
        anchor,
        expected_anchor_sha256=anchor_hash,
        episode_id="episode-1",
        event_id=event_id,
        work_key=work_key,
        status="REGISTERED",
        family_id="family-1",
        equivalence_cluster_id="variant-1",
        path_kind="PRIMARY",
        failure_reason=None,
        meta={"candidate_id": "variant-1"},
        expected_entry_count=expected_count,
        expected_entries_sha256=expected_head,
        terminal=False,
    )


def test_append_is_idempotent_for_the_same_event_identity(tmp_path: Path) -> None:
    anchor, anchor_hash = _anchor(tmp_path)
    first = _register(anchor, anchor_hash)
    replay = _register(anchor, anchor_hash)

    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert replay["entry_count"] == 1
    assert replay["entries_sha256"] == first["entries_sha256"]


def test_duplicate_event_identity_with_different_payload_is_rejected(
    tmp_path: Path,
) -> None:
    anchor, anchor_hash = _anchor(tmp_path)
    _register(anchor, anchor_hash)

    with pytest.raises(ScienceTrialLedgerError, match="different science trial payload"):
        _register(
            anchor,
            anchor_hash,
            event_id="register-1",
            work_key="different-trial",
        )


def test_compare_and_append_rejects_a_stale_head(tmp_path: Path) -> None:
    anchor, anchor_hash = _anchor(tmp_path)
    _register(anchor, anchor_hash)

    with pytest.raises(ScienceTrialLedgerError, match="entry count changed"):
        _register(
            anchor,
            anchor_hash,
            event_id="register-2",
            work_key="trial-2",
        )


def test_terminal_transition_requires_prior_registration(tmp_path: Path) -> None:
    anchor, anchor_hash = _anchor(tmp_path)

    with pytest.raises(ScienceTrialLedgerError, match="silent unregistered"):
        append_science_trial_entry(
            anchor,
            expected_anchor_sha256=anchor_hash,
            episode_id="episode-1",
            event_id="failed-1",
            work_key="trial-1",
            status="COMPILE_FAILED",
            family_id="family-1",
            equivalence_cluster_id="variant-1",
            path_kind="PRIMARY",
            failure_reason="LEAKAGE",
            meta={"candidate_id": "variant-1"},
            expected_entry_count=0,
            expected_entries_sha256=EMPTY_SCIENCE_TRIAL_ENTRIES_SHA256,
            terminal=True,
        )


def test_registered_trial_can_append_one_terminal_record(tmp_path: Path) -> None:
    anchor, anchor_hash = _anchor(tmp_path)
    registered = _register(anchor, anchor_hash)
    terminal = append_science_trial_entry(
        anchor,
        expected_anchor_sha256=anchor_hash,
        episode_id="episode-1",
        event_id="succeeded-1",
        work_key="trial-1",
        status="SUCCEEDED",
        family_id="family-1",
        equivalence_cluster_id="variant-1",
        path_kind="PRIMARY",
        failure_reason=None,
        meta={"artifact_sha256": "a" * 64},
        expected_entry_count=1,
        expected_entries_sha256=str(registered["entries_sha256"]),
        terminal=True,
    )
    replay = load_science_trial_journal(
        anchor,
        expected_anchor_sha256=anchor_hash,
        episode_id="episode-1",
    )

    assert terminal["entry_count"] == 2
    assert replay["entries"][-1]["event"] == "TERMINAL"
    assert replay["entries"][-1]["status"] == "SUCCEEDED"


def test_payload_tamper_fails_journal_replay(tmp_path: Path) -> None:
    anchor, anchor_hash = _anchor(tmp_path)
    _register(anchor, anchor_hash)
    journal = science_trial_journal_path(anchor)
    with sqlite3.connect(journal) as connection:
        connection.execute(
            "UPDATE trial_entries SET payload_hash = ? WHERE seq = 1",
            ("0" * 64,),
        )
        connection.commit()

    with pytest.raises(ScienceTrialLedgerError, match="payload hash mismatch"):
        load_science_trial_journal(
            anchor,
            expected_anchor_sha256=anchor_hash,
            episode_id="episode-1",
        )


def test_anchor_hash_remains_the_protocol_identity(tmp_path: Path) -> None:
    anchor, anchor_hash = _anchor(tmp_path)
    _register(anchor, anchor_hash)
    payload = json.loads(anchor.read_text(encoding="utf-8"))
    payload["episode_id"] = "different-episode"
    anchor.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScienceTrialLedgerError, match="anchor hash mismatch"):
        load_science_trial_journal(
            anchor,
            expected_anchor_sha256=anchor_hash,
            episode_id="episode-1",
        )
