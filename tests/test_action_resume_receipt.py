from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import services.agent_runtime.action_resume_receipt as action_resume_module
from services.agent_runtime.action_resume_receipt import (
    ActionResumeError,
    consume_action_resume_receipt,
    issue_action_resume_receipt,
    verify_action_resume_receipt,
    write_action_resume_receipt,
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _event(
    run_id: str,
    ordinal: int,
    *,
    side_effect_id: str | None = None,
    target: str | None = None,
    phase: str | None = None,
    kind: str | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "codex.verified-task-run.v1",
        "event_id": f"event-id-{ordinal}",
        "run_id": run_id,
        "timestamp": f"2026-07-20T00:{ordinal:02d}:00Z",
        "actor": "codex_owner",
        "kind": kind or ("result" if ordinal % 2 == 0 else "observation"),
        "phase": phase or f"phase-{ordinal}",
        "summary": f"事件摘要-{ordinal}",
        "evidence_refs": evidence_refs or [],
        "target": target or f"diagnostic:{ordinal}",
        "exit_code": 0,
        "duration_ms": None,
        "retry_class": "none",
        "side_effect_id": side_effect_id,
    }


def _fixture(
    tmp_path: Path,
    *,
    cursor: int = 3,
    state_status: str = "in_progress",
    tail_side_effect: str | None = None,
    work_key: str = "wk:test:apply",
) -> dict[str, Path]:
    run_id = "run-continuity-test"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    task = {
        "schema_version": "codex.verified-task-run.v1",
        "run_id": run_id,
        "mode": "bounded_task",
        "objective": "keep the parent objective stable",
        "stop_conditions": ["explicit user stop"],
    }
    events = [
        _event(
            run_id,
            1,
            target=work_key,
            phase="work_unit_planned",
            kind="result",
        ),
        _event(
            run_id,
            2,
            target=work_key,
            phase="work_unit_active",
            kind="result",
        ),
        _event(run_id, 3),
        _event(run_id, 4, side_effect_id=tail_side_effect),
    ]
    lines = [
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for row in events
    ]
    prefix = b"".join(lines[:2])
    (run_dir / "task.json").write_bytes(_json_bytes(task))
    (run_dir / "events.jsonl").write_bytes(b"".join(lines))
    state = {
        "schema_version": "codex.verified-task-run.v1",
        "run_id": run_id,
        "status": state_status,
        "current_phase": "phase-4",
        "events_count": 4,
    }
    (run_dir / "state.json").write_bytes(_json_bytes(state))
    reuse_path = tmp_path / "reuse_index.json"
    reuse = {
        "schema_version": "xinao.codex_task_run.fan_in_reuse_index.v1",
        "parent_run": run_id,
        "authority": False,
        "completion_claim_allowed": False,
        "source_cut": {
            "events_jsonl": {
                "path": str(run_dir / "events.jsonl"),
                "sha256": hashlib.sha256(prefix).hexdigest(),
                "byte_length": len(prefix),
                "event_count": 2,
                "last_event_id": "event-id-2",
            }
        },
    }
    reuse_path.write_bytes(_json_bytes(reuse))
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = {
        "schema_version": "xinao.codex_session_checkpoint.v2",
        "sentinel": "SENTINEL:XINAO_CODEX_SESSION_CHECKPOINT_V2",
        "not_authority": True,
        "status": f"phase-{cursor}",
        "user_intent_cn": "继续父级意图",
        "resume_brief_cn": f"checkpoint 到 event{cursor}",
        "next_machine_actions": ["先重放 event tail"],
        "do_not_re_explain_cn": ["不要把 checkpoint 当权威"],
        "evidence_refs": [f"{run_dir / 'events.jsonl'}#event{cursor}"],
        "reuse_index": {
            "path": str(reuse_path),
            "sha256": hashlib.sha256(reuse_path.read_bytes()).hexdigest(),
            "source_cut_event_count": 2,
            "tail_replay_from_event": 3,
        },
    }
    checkpoint_path.write_bytes(_json_bytes(checkpoint))
    fact = tmp_path / "事实账本.json"
    fact.write_text('{"状态":"之前"}\n', encoding="utf-8")
    return {
        "run_dir": run_dir,
        "checkpoint": checkpoint_path,
        "reuse": reuse_path,
        "fact": fact,
        "absent": tmp_path / "尚未生成",
    }


def _issue_apply(paths: dict[str, Path], now: datetime) -> dict[str, object]:
    return issue_action_resume_receipt(
        checkpoint_path=paths["checkpoint"],
        action_kind="apply",
        work_key="wk:test:apply",
        next_action="apply exactly once",
        side_effect_id="side-effect-new",
        observed_files=[paths["fact"]],
        expected_absent_paths=[paths["absent"]],
        work_pin="pin-1",
        now=now,
    )


def _append_event(paths: dict[str, Path], event: dict[str, object]) -> None:
    event_path = paths["run_dir"] / "events.jsonl"
    with event_path.open("ab") as handle:
        handle.write(
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            + b"\n"
        )
    state_path = paths["run_dir"] / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "events_count": int(state["events_count"]) + 1,
            "current_phase": event["phase"],
        }
    )
    state_path.write_bytes(_json_bytes(state))


def test_fresh_and_stale_checkpoint_are_reconciled_without_authority(tmp_path: Path) -> None:
    stale_paths = _fixture(tmp_path / "stale", cursor=3)
    stale = issue_action_resume_receipt(checkpoint_path=stale_paths["checkpoint"])
    assert stale["freshness"] == {
        "checkpoint_was_stale": True,
        "reason_code": "CHECKPOINT_STALE_EVENT_TAIL",
        "reconciled": True,
    }
    assert [row["ordinal"] for row in stale["event_delta"]] == [4]
    assert stale["authority"] is False

    fresh_paths = _fixture(tmp_path / "fresh", cursor=4)
    fresh = issue_action_resume_receipt(checkpoint_path=fresh_paths["checkpoint"])
    assert fresh["freshness"]["reason_code"] == "CHECKPOINT_FRESH"
    assert fresh["event_delta"] == []


def test_cursor_reuse_hash_and_immutable_prefix_fail_closed(tmp_path: Path) -> None:
    paths = _fixture(tmp_path / "reuse")
    paths["reuse"].write_bytes(paths["reuse"].read_bytes() + b" ")
    with pytest.raises(ActionResumeError) as caught:
        issue_action_resume_receipt(checkpoint_path=paths["checkpoint"])
    assert caught.value.reason_code == "REUSE_INDEX_HASH_DRIFT"

    paths = _fixture(tmp_path / "prefix")
    events_path = paths["run_dir"] / "events.jsonl"
    events_path.write_bytes(
        events_path.read_bytes().replace("事件摘要-1".encode(), "事件摘要-X".encode(), 1)
    )
    with pytest.raises(ActionResumeError) as caught:
        issue_action_resume_receipt(checkpoint_path=paths["checkpoint"])
    assert caught.value.reason_code == "REUSE_EVENT_PREFIX_DRIFT"


def test_world_or_event_head_drift_rejects_before_effect(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "world")
    receipt = _issue_apply(paths, now)
    paths["fact"].write_text('{"状态":"之后"}\n', encoding="utf-8")
    with pytest.raises(ActionResumeError) as caught:
        verify_action_resume_receipt(
            receipt,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            now=now,
        )
    assert caught.value.reason_code == "CHECKPOINT_WORLD_DIVERGED"

    paths = _fixture(tmp_path / "head")
    receipt = _issue_apply(paths, now)
    event_path = paths["run_dir"] / "events.jsonl"
    with event_path.open("ab") as handle:
        handle.write(
            json.dumps(_event("run-continuity-test", 5), separators=(",", ":")).encode() + b"\n"
        )
    state_path = paths["run_dir"] / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({"events_count": 5, "current_phase": "phase-5"})
    state_path.write_bytes(_json_bytes(state))
    with pytest.raises(ActionResumeError) as caught:
        verify_action_resume_receipt(
            receipt,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            now=now,
        )
    assert caught.value.reason_code == "ACTION_RECEIPT_STALE"


def test_one_shot_consumer_executes_effect_once(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "one-shot")
    receipt = _issue_apply(paths, now)
    receipt_path = tmp_path / "one-shot" / "receipt.json"
    write_action_resume_receipt(receipt_path, receipt)
    effects: list[str] = []

    def effect() -> dict[str, int]:
        effects.append("ran")
        return {"effect_count": len(effects)}

    report = consume_action_resume_receipt(
        receipt_path,
        expected_action_kind="apply",
        expected_work_key="wk:test:apply",
        expected_side_effect_id="side-effect-new",
        expected_next_action="apply exactly once",
        consumer=effect,
        now=now + timedelta(minutes=1),
    )
    assert report["status"] == "consumed"
    assert report["reason_code"] == "ACTION_RECEIPT_CONSUMED"
    assert effects == ["ran"]
    with pytest.raises(ActionResumeError) as caught:
        consume_action_resume_receipt(
            receipt_path,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            consumer=effect,
            now=now + timedelta(minutes=2),
        )
    assert caught.value.reason_code == "SIDE_EFFECT_CLAIM_EXISTS"
    assert effects == ["ran"]


def test_one_shot_consumer_reverifies_after_exclusive_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "post-claim-reverify")
    receipt = _issue_apply(paths, now)
    receipt_path = tmp_path / "post-claim-reverify" / "receipt.json"
    write_action_resume_receipt(receipt_path, receipt)
    original_verify = action_resume_module.verify_action_resume_receipt
    verify_count = 0
    effects: list[str] = []

    def verify_with_intervening_drift(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal verify_count
        verify_count += 1
        if verify_count == 2:
            paths["fact"].write_text("drifted after initial verification", encoding="utf-8")
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(
        action_resume_module, "verify_action_resume_receipt", verify_with_intervening_drift
    )
    with pytest.raises(ActionResumeError) as caught:
        consume_action_resume_receipt(
            receipt_path,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            consumer=lambda: effects.append("ran"),
            now=now + timedelta(minutes=1),
        )
    assert caught.value.reason_code == "CHECKPOINT_WORLD_DIVERGED"
    assert verify_count == 2
    assert effects == []
    claim_path = next((paths["run_dir"] / "action_consumptions").glob("*.json"))
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    assert claim["status"] == "rejected"
    assert claim["reason_code"] == "CHECKPOINT_WORLD_DIVERGED"


def test_duplicate_effect_pause_and_expiry_are_blocked(tmp_path: Path) -> None:
    duplicate = _fixture(
        tmp_path / "duplicate", tail_side_effect="already-used", work_key="wk:test"
    )
    with pytest.raises(ActionResumeError) as caught:
        issue_action_resume_receipt(
            checkpoint_path=duplicate["checkpoint"],
            action_kind="dispatch",
            work_key="wk:test",
            next_action="dispatch",
            side_effect_id="already-used",
        )
    assert caught.value.reason_code == "DUPLICATE_SIDE_EFFECT_BLOCKED"

    paused = _fixture(tmp_path / "paused", state_status="paused", work_key="wk:test")
    with pytest.raises(ActionResumeError) as caught:
        issue_action_resume_receipt(
            checkpoint_path=paused["checkpoint"],
            action_kind="dispatch",
            work_key="wk:test",
            next_action="dispatch",
            side_effect_id="new",
        )
    assert caught.value.reason_code == "RUN_MUTATION_FROZEN"


@pytest.mark.parametrize("terminal_status", ["verified", "partial", "blocked", "unverified"])
def test_terminal_task_run_cannot_issue_a_mutating_receipt(
    tmp_path: Path, terminal_status: str
) -> None:
    paths = _fixture(
        tmp_path / terminal_status,
        state_status=terminal_status,
        work_key="wk:test:terminal",
    )
    with pytest.raises(ActionResumeError) as caught:
        issue_action_resume_receipt(
            checkpoint_path=paths["checkpoint"],
            action_kind="land",
            work_key="wk:test:terminal",
            next_action="merge verified branch into remote main",
            side_effect_id=f"land-after-{terminal_status}",
            observed_files=[paths["fact"]],
        )
    assert caught.value.reason_code == "RUN_MUTATION_FROZEN"

    paths = _fixture(tmp_path / "expiry")
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    receipt = _issue_apply(paths, now)
    with pytest.raises(ActionResumeError) as caught:
        verify_action_resume_receipt(
            receipt,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            now=now + timedelta(hours=2),
        )
    assert caught.value.reason_code == "ACTION_RECEIPT_EXPIRED"


def test_exact_next_action_and_live_fact_are_required_for_land_and_retire(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "land", work_key="wk:test:land")
    paths["fact"].write_text('{"remote_main":"merge-sha-42"}\n', encoding="utf-8")
    receipt = issue_action_resume_receipt(
        checkpoint_path=paths["checkpoint"],
        action_kind="land",
        work_key="wk:test:land",
        next_action="merge PR 42 then read back remote main",
        side_effect_id="se:land:42",
        semantic_facts=[
            {
                "kind": "git_remote_ref",
                "subject": "origin/main",
                "work_key": "wk:test:land",
                "observed_value": "merge-sha-42",
                "source_path": str(paths["fact"]),
            }
        ],
        now=now,
    )
    assert receipt["action"]["action_digest"]
    assert receipt["work_pin_reverified"] is False
    with pytest.raises(ActionResumeError) as caught:
        verify_action_resume_receipt(
            receipt,
            expected_action_kind="land",
            expected_work_key="wk:test:land",
            expected_side_effect_id="se:land:42",
            expected_next_action="merge a different PR",
            now=now,
        )
    assert caught.value.reason_code == "ACTION_IDENTITY_MISMATCH"

    verified = verify_action_resume_receipt(
        receipt,
        expected_action_kind="land",
        expected_work_key="wk:test:land",
        expected_side_effect_id="se:land:42",
        expected_next_action="merge PR 42 then read back remote main",
        now=now,
    )
    assert verified["action_digest"] == receipt["action"]["action_digest"]
    assert verified["completion_claim_allowed"] is False

    paths = _fixture(tmp_path / "retire", work_key="wk:test:retire")
    with pytest.raises(ActionResumeError) as caught:
        issue_action_resume_receipt(
            checkpoint_path=paths["checkpoint"],
            action_kind="retire",
            work_key="wk:test:retire",
            next_action="remove one verified carrier",
            side_effect_id="se:retire:1",
            work_pin="self-declared-only",
            now=now,
        )
    assert caught.value.reason_code == "WORLD_FACT_REQUIRED"


def test_work_key_binding_pause_isolation_and_hash_bound_resume(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "isolation", work_key="work-A")
    _append_event(
        paths,
        _event(
            "run-continuity-test",
            5,
            target="work-B",
            phase="work_unit_planned",
            kind="result",
        ),
    )
    _append_event(
        paths,
        _event(
            "run-continuity-test",
            6,
            target="work-B",
            phase="work_unit_active",
            kind="result",
        ),
    )
    _append_event(
        paths,
        _event(
            "run-continuity-test",
            7,
            target="work-A",
            phase="work_unit_paused",
            kind="pause",
        ),
    )

    receipt_b = issue_action_resume_receipt(
        checkpoint_path=paths["checkpoint"],
        action_kind="dispatch",
        work_key="work-B",
        next_action="dispatch work B only",
        side_effect_id="dispatch-B-1",
        now=now,
    )
    assert receipt_b["action"]["work_key"] == "work-B"
    with pytest.raises(ActionResumeError) as paused:
        issue_action_resume_receipt(
            checkpoint_path=paths["checkpoint"],
            action_kind="dispatch",
            work_key="work-A",
            next_action="dispatch work A",
            side_effect_id="dispatch-A-before-resume",
            now=now,
        )
    assert paused.value.reason_code == "RUN_MUTATION_FROZEN"

    _append_event(paths, _event("run-continuity-test", 8, target="unrelated"))
    with pytest.raises(ActionResumeError) as still_paused:
        issue_action_resume_receipt(
            checkpoint_path=paths["checkpoint"],
            action_kind="dispatch",
            work_key="work-A",
            next_action="dispatch work A",
            side_effect_id="dispatch-A-after-unrelated",
            now=now,
        )
    assert still_paused.value.reason_code == "RUN_MUTATION_FROZEN"

    proof = tmp_path / "isolation" / "resume-readback.json"
    proof.write_text('{"work_key":"work-A","reconciled":true}\n', encoding="utf-8")
    proof_sha = hashlib.sha256(proof.read_bytes()).hexdigest()
    _append_event(
        paths,
        _event(
            "run-continuity-test",
            9,
            target="work-A",
            phase="work_unit_resume_reconciled",
            kind="result",
            side_effect_id="resume-A-1",
            evidence_refs=[f"{proof}#sha256={proof_sha}"],
        ),
    )
    resumed = issue_action_resume_receipt(
        checkpoint_path=paths["checkpoint"],
        action_kind="dispatch",
        work_key="work-A",
        next_action="dispatch work A after exact reconciliation",
        side_effect_id="dispatch-A-after-resume",
        now=now,
    )
    assert resumed["action"]["work_key"] == "work-A"

    with pytest.raises(ActionResumeError) as unrelated:
        issue_action_resume_receipt(
            checkpoint_path=paths["checkpoint"],
            action_kind="dispatch",
            work_key="never-declared",
            next_action="must not run",
            side_effect_id="unrelated-key",
            now=now,
        )
    assert unrelated.value.reason_code == "WORK_KEY_UNBOUND"


def test_durable_claim_blocks_post_effect_pre_event_replay(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "crash-window")
    receipt = _issue_apply(paths, now)
    receipt_path = tmp_path / "crash-window" / "receipt.json"
    write_action_resume_receipt(receipt_path, receipt)
    effect_marker = tmp_path / "crash-window" / "effect.marker"

    def effect_then_crash() -> None:
        effect_marker.write_text("effect happened", encoding="utf-8")
        raise SystemExit(99)

    with pytest.raises(SystemExit):
        consume_action_resume_receipt(
            receipt_path,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            consumer=effect_then_crash,
            now=now + timedelta(minutes=1),
        )
    assert effect_marker.read_text(encoding="utf-8") == "effect happened"
    claim_path = next((paths["run_dir"] / "action_consumptions").glob("*.json"))
    assert json.loads(claim_path.read_text(encoding="utf-8"))["status"] == "claimed"

    with pytest.raises(ActionResumeError) as replay:
        _issue_apply(paths, now + timedelta(minutes=2))
    assert replay.value.reason_code == "SIDE_EFFECT_CLAIM_EXISTS"


def test_land_rejects_untyped_or_unrelated_readback(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "semantic", work_key="work-land")
    with pytest.raises(ActionResumeError) as untyped:
        issue_action_resume_receipt(
            checkpoint_path=paths["checkpoint"],
            action_kind="land",
            work_key="work-land",
            next_action="merge and read remote main",
            side_effect_id="land-untyped",
            observed_files=[paths["fact"]],
            now=now,
        )
    assert untyped.value.reason_code == "SEMANTIC_FACT_REQUIRED"

    with pytest.raises(ActionResumeError) as wrong_key:
        issue_action_resume_receipt(
            checkpoint_path=paths["checkpoint"],
            action_kind="land",
            work_key="work-land",
            next_action="merge and read remote main",
            side_effect_id="land-wrong-key",
            semantic_facts=[
                {
                    "kind": "git_remote_ref",
                    "subject": "origin/main",
                    "work_key": "another-work",
                    "observed_value": "abc",
                    "source_path": str(paths["fact"]),
                }
            ],
            now=now,
        )
    assert wrong_key.value.reason_code == "WORLD_FACT_INVALID"
