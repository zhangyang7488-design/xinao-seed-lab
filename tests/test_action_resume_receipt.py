from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import services.agent_runtime.action_resume_receipt as action_resume_module
from services.agent_runtime.action_resume_receipt import (
    ActionResumeError,
    append_pending_action_event_and_reconcile,
    build_action_effect_outcome,
    consume_action_resume_receipt,
    git_update_ref_cas_adapter,
    issue_action_resume_receipt,
    reconcile_action_resume_claim,
    verify_action_resume_receipt,
    write_action_resume_receipt,
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _finalizer_ref(
    path: Path,
    *,
    work_key: str,
    kind: str,
    subject: str,
    observed_value: str,
    evidence_refs: list[str],
) -> str:
    path.write_bytes(
        _json_bytes(
            {
                "schema_version": "xinao.work_unit_finalizer_evidence.v1",
                "kind": kind,
                "work_key": work_key,
                "subject": subject,
                "observed_value": observed_value,
                "readback_verified": True,
                "evidence_refs": evidence_refs,
                "authority": False,
                "completion_claim_allowed": False,
            }
        )
    )
    return f"{path}#sha256={hashlib.sha256(path.read_bytes()).hexdigest()}"


def _write_task_run_cli_fixture(path: Path) -> None:
    path.write_text(
        """from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
sub = parser.add_subparsers(dest="command", required=True)
event = sub.add_parser("event")
event.add_argument("--run-id", required=True)
event.add_argument("--event-id", required=True)
event.add_argument("--actor", required=True)
event.add_argument("--kind", required=True)
event.add_argument("--phase", required=True)
event.add_argument("--summary", required=True)
event.add_argument("--evidence-ref", action="append", default=[])
event.add_argument("--target", required=True)
event.add_argument("--exit-code", type=int, required=True)
event.add_argument("--retry-class", required=True)
event.add_argument("--side-effect-id", required=True)
args = parser.parse_args()
run_dir = args.root.resolve() / args.run_id
events_path = run_dir / "events.jsonl"
events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
candidate = {
    "schema_version": "codex.verified-task-run.v1",
    "event_id": args.event_id,
    "run_id": args.run_id,
    "timestamp": "2026-07-20T02:00:00Z",
    "actor": args.actor,
    "kind": args.kind,
    "phase": args.phase,
    "summary": args.summary,
    "evidence_refs": args.evidence_ref,
    "target": args.target,
    "exit_code": args.exit_code,
    "duration_ms": None,
    "retry_class": args.retry_class,
    "side_effect_id": args.side_effect_id,
    "idempotency_keyed": True,
}
semantic_fields = (
    "actor", "kind", "phase", "summary", "evidence_refs", "target",
    "exit_code", "duration_ms", "retry_class", "side_effect_id",
)
existing = next((row for row in events if row.get("event_id") == args.event_id), None)
if existing is not None:
    if any(existing.get(key) != candidate.get(key) for key in semantic_fields):
        raise SystemExit("event_id replay changed event semantics")
    replayed = True
else:
    with events_path.open("a", encoding="utf-8", newline="\\n") as handle:
        handle.write(json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\\n")
        handle.flush()
        os.fsync(handle.fileno())
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({
        "events_count": len(events) + 1,
        "current_phase": candidate["phase"],
        "last_summary": candidate["summary"],
        "updated_at": candidate["timestamp"],
    })
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    replayed = False
print(json.dumps({"ok": True, "event_id": args.event_id, "replayed": replayed}))
""",
        encoding="utf-8",
    )


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
        "created_at": "2026-07-20T00:01:00Z",
        "updated_at": "2026-07-20T00:04:00Z",
        "current_phase": "phase-4",
        "events_count": 4,
        "transient_retries_used": 0,
        "last_summary": "事件摘要-4",
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
        expected_result_phase="work_unit_effect_verified",
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
            "last_summary": event["summary"],
            "updated_at": event["timestamp"],
        }
    )
    state_path.write_bytes(_json_bytes(state))


def _pending_typed_apply(
    paths: dict[str, Path], directory: Path, now: datetime
) -> dict[str, object]:
    receipt = _issue_apply(paths, now)
    receipt_path = directory / "receipt.json"
    physical_path = directory / "runtime-readback.json"
    write_action_resume_receipt(receipt_path, receipt)

    def effect(context: dict[str, object]) -> dict[str, object]:
        physical_path.write_text('{"consumed":true}\n', encoding="utf-8")
        digest = hashlib.sha256(physical_path.read_bytes()).hexdigest()
        physical_ref = f"{physical_path}#sha256={digest}"
        finalizer_ref = _finalizer_ref(
            directory / "runtime-finalizer.json",
            work_key="wk:test:apply",
            kind="runtime_consumer",
            subject="fixture.runtime_consumer",
            observed_value=digest,
            evidence_refs=[physical_ref],
        )
        return build_action_effect_outcome(
            context,
            status="applied",
            adapter_kind="fixture.runtime_consumer.v1",
            observed_before="absent",
            observed_after=digest,
            evidence_refs=[physical_ref],
            result_phase="work_unit_effect_verified",
            task_run_evidence_refs=[finalizer_ref],
        )

    return consume_action_resume_receipt(
        receipt_path,
        expected_action_kind="apply",
        expected_work_key="wk:test:apply",
        expected_side_effect_id="side-effect-new",
        expected_next_action="apply exactly once",
        expected_result_phase="work_unit_effect_verified",
        consumer=effect,
        now=now + timedelta(minutes=1),
    )


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


def test_result_phase_is_bound_into_receipt_identity(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "phase-binding")
    receipt = _issue_apply(paths, now)
    assert receipt["action"]["expected_result_phase"] == "work_unit_effect_verified"

    tampered = json.loads(json.dumps(receipt))
    tampered["action"]["expected_result_phase"] = "work_unit_land_verified"
    tampered.pop("receipt_sha256")
    tampered["receipt_sha256"] = hashlib.sha256(
        action_resume_module.canonical_json_bytes(tampered)
    ).hexdigest()
    with pytest.raises(ActionResumeError) as caught:
        verify_action_resume_receipt(
            tampered,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            expected_result_phase="work_unit_effect_verified",
            now=now,
        )
    assert caught.value.reason_code == "ACTION_RESULT_PHASE_MISMATCH"


def test_untyped_callback_cannot_mark_effect_consumed(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "one-shot")
    receipt = _issue_apply(paths, now)
    receipt_path = tmp_path / "one-shot" / "receipt.json"
    write_action_resume_receipt(receipt_path, receipt)
    effects: list[str] = []

    def effect() -> dict[str, int]:
        effects.append("ran")
        return {"effect_count": len(effects)}

    with pytest.raises(ActionResumeError) as unproven:
        consume_action_resume_receipt(
            receipt_path,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            consumer=effect,
            now=now + timedelta(minutes=1),
        )
    assert unproven.value.reason_code == "ACTION_EFFECT_OUTCOME_UNPROVEN"
    assert effects == ["ran"]
    claim_path = next((paths["run_dir"] / "action_consumptions").glob("*.json"))
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    assert claim["status"] == "effect_unknown"
    assert claim["reason_code"] == "ACTION_EFFECT_OUTCOME_UNPROVEN"
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


def test_typed_effect_is_event_pending_until_matching_task_run_event(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "typed")
    receipt = _issue_apply(paths, now)
    receipt_path = tmp_path / "typed" / "receipt.json"
    evidence_path = tmp_path / "typed" / "effect-readback.json"
    write_action_resume_receipt(receipt_path, receipt)

    def effect(context: dict[str, object]) -> dict[str, object]:
        evidence_path.write_text('{"applied":true}\n', encoding="utf-8")
        evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        physical_ref = f"{evidence_path}#sha256={evidence_sha}"
        finalizer_ref = _finalizer_ref(
            evidence_path.with_name("effect-finalizer.json"),
            work_key="wk:test:apply",
            kind="runtime_consumer",
            subject="test_file_cas.v1",
            observed_value=evidence_sha,
            evidence_refs=[physical_ref],
        )
        return build_action_effect_outcome(
            context,
            status="applied",
            adapter_kind="test_file_cas.v1",
            observed_before="absent",
            observed_after=evidence_sha,
            evidence_refs=[physical_ref],
            task_run_evidence_refs=[finalizer_ref],
        )

    report = consume_action_resume_receipt(
        receipt_path,
        expected_action_kind="apply",
        expected_work_key="wk:test:apply",
        expected_side_effect_id="side-effect-new",
        expected_next_action="apply exactly once",
        consumer=effect,
        now=now + timedelta(minutes=1),
    )
    assert report["status"] == "event_pending"
    assert report["reason_code"] == "ACTION_EFFECT_EVENT_PENDING"
    assert report["claim_generation"] == 1
    assert report["required_task_run_event"]["phase"] == "work_unit_effect_verified"

    evidence_ref = report["effect_outcome"]["task_run_result"]["evidence_refs"][0]
    _append_event(
        paths,
        _event(
            "run-continuity-test",
            5,
            target="wk:test:apply",
            phase="work_unit_effect_verified",
            kind="result",
            side_effect_id="side-effect-new",
            evidence_refs=[],
        ),
    )
    still_pending = reconcile_action_resume_claim(
        Path(report["consumption_path"]), now=now + timedelta(seconds=90)
    )
    assert still_pending["status"] == "event_pending"

    _append_event(
        paths,
        _event(
            "run-continuity-test",
            6,
            target="wk:test:apply",
            phase="work_unit_effect_verified",
            kind="result",
            side_effect_id="side-effect-new",
            evidence_refs=[evidence_ref],
        ),
    )
    closed = reconcile_action_resume_claim(
        Path(report["consumption_path"]), now=now + timedelta(minutes=2)
    )
    assert closed["status"] == "closed"
    assert closed["reason_code"] == "ACTION_EFFECT_EVENT_CLOSED"
    assert closed["task_run_event"]["event_id"] == "event-id-6"


@pytest.mark.parametrize(
    "defect",
    ["wrong_kind", "wrong_work_key", "wrong_schema", "hash_drift"],
)
def test_effect_phase_rejects_non_finalizer_or_unbound_evidence(
    tmp_path: Path, defect: str
) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    directory = tmp_path / defect
    paths = _fixture(directory)
    receipt_path = directory / "receipt.json"
    write_action_resume_receipt(receipt_path, _issue_apply(paths, now))

    def invalid_effect(context: dict[str, object]) -> dict[str, object]:
        physical_path = directory / "physical.json"
        physical_path.write_text('{"consumed":true}\n', encoding="utf-8")
        digest = hashlib.sha256(physical_path.read_bytes()).hexdigest()
        physical_ref = f"{physical_path}#sha256={digest}"
        finalizer_path = directory / "finalizer.json"
        payload = {
            "schema_version": "xinao.work_unit_finalizer_evidence.v1",
            "kind": "runtime_consumer",
            "work_key": "wk:test:apply",
            "subject": "invalid-fixture",
            "observed_value": digest,
            "readback_verified": True,
            "evidence_refs": [physical_ref],
            "authority": False,
            "completion_claim_allowed": False,
        }
        if defect == "wrong_kind":
            payload["kind"] = "git_remote_ref"
        elif defect == "wrong_work_key":
            payload["work_key"] = "wk:another"
        elif defect == "wrong_schema":
            payload["schema_version"] = "xinao.work_unit_finalizer_evidence.v0"
        finalizer_path.write_bytes(_json_bytes(payload))
        finalizer_ref = (
            f"{finalizer_path}#sha256={hashlib.sha256(finalizer_path.read_bytes()).hexdigest()}"
        )
        if defect == "hash_drift":
            finalizer_path.write_bytes(finalizer_path.read_bytes() + b" ")
        return build_action_effect_outcome(
            context,
            status="applied",
            adapter_kind="invalid-fixture.v1",
            observed_before="absent",
            observed_after=digest,
            evidence_refs=[physical_ref],
            task_run_evidence_refs=[finalizer_ref],
        )

    with pytest.raises(ActionResumeError) as caught:
        consume_action_resume_receipt(
            receipt_path,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            consumer=invalid_effect,
            now=now + timedelta(minutes=1),
        )
    assert caught.value.reason_code == "ACTION_EFFECT_OUTCOME_UNPROVEN"
    claim_path = next((paths["run_dir"] / "action_consumptions").glob("*.json"))
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    assert claim["status"] == "effect_unknown"
    assert len((paths["run_dir"] / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 4


def test_stale_fence_typed_outcome_cannot_advance_claim(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "stale-fence")
    receipt = _issue_apply(paths, now)
    receipt_path = tmp_path / "stale-fence" / "receipt.json"
    evidence_path = tmp_path / "stale-fence" / "readback.json"
    write_action_resume_receipt(receipt_path, receipt)

    def stale_adapter(context: dict[str, object]) -> dict[str, object]:
        evidence_path.write_text('{"applied":true}\n', encoding="utf-8")
        digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        physical_ref = f"{evidence_path}#sha256={digest}"
        finalizer_ref = _finalizer_ref(
            evidence_path.with_name("finalizer.json"),
            work_key="wk:test:apply",
            kind="runtime_consumer",
            subject="test_stale_fence.v1",
            observed_value=digest,
            evidence_refs=[physical_ref],
        )
        outcome = build_action_effect_outcome(
            context,
            status="applied",
            adapter_kind="test_stale_fence.v1",
            observed_before="absent",
            observed_after=digest,
            evidence_refs=[physical_ref],
            task_run_evidence_refs=[finalizer_ref],
        )
        outcome["fence_token"] = "0" * 64
        return outcome

    with pytest.raises(ActionResumeError) as stale:
        consume_action_resume_receipt(
            receipt_path,
            expected_action_kind="apply",
            expected_work_key="wk:test:apply",
            expected_side_effect_id="side-effect-new",
            expected_next_action="apply exactly once",
            consumer=stale_adapter,
            now=now + timedelta(minutes=1),
        )
    assert stale.value.reason_code == "ACTION_EFFECT_OUTCOME_UNPROVEN"
    claim_path = next((paths["run_dir"] / "action_consumptions").glob("*.json"))
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    assert claim["status"] == "effect_unknown"


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
    assert claim["status"] == "aborted_pre_effect"
    assert claim["reason_code"] == "CHECKPOINT_WORLD_DIVERGED"

    paths["fact"].write_text('{"状态":"之前"}\n', encoding="utf-8")
    readback = tmp_path / "post-claim-reverify" / "retry-readback.json"

    def retry_effect(context: dict[str, object]) -> dict[str, object]:
        readback.write_text('{"applied":true}\n', encoding="utf-8")
        digest = hashlib.sha256(readback.read_bytes()).hexdigest()
        physical_ref = f"{readback}#sha256={digest}"
        finalizer_ref = _finalizer_ref(
            readback.with_name("retry-finalizer.json"),
            work_key="wk:test:apply",
            kind="runtime_consumer",
            subject="test_file_cas.v1",
            observed_value=digest,
            evidence_refs=[physical_ref],
        )
        return build_action_effect_outcome(
            context,
            status="applied",
            adapter_kind="test_file_cas.v1",
            observed_before="absent",
            observed_after=digest,
            evidence_refs=[physical_ref],
            task_run_evidence_refs=[finalizer_ref],
        )

    retried = consume_action_resume_receipt(
        receipt_path,
        expected_action_kind="apply",
        expected_work_key="wk:test:apply",
        expected_side_effect_id="side-effect-new",
        expected_next_action="apply exactly once",
        consumer=retry_effect,
        now=now + timedelta(minutes=2),
    )
    assert retried["status"] == "event_pending"
    assert retried["claim_generation"] == 2
    assert retried["attempts"][0]["status"] == "aborted_pre_effect"


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


def test_undefined_retire_phase_cannot_enter_effect_claim(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    retire_paths = _fixture(tmp_path / "retire-undefined", work_key="wk:retire")
    retire = issue_action_resume_receipt(
        checkpoint_path=retire_paths["checkpoint"],
        action_kind="retire",
        work_key="wk:retire",
        next_action="retire one classified carrier",
        side_effect_id="se:retire:undefined",
        semantic_facts=[
            {
                "kind": "carrier_inventory",
                "subject": "carrier:test",
                "work_key": "wk:retire",
                "observed_value": "present",
                "source_path": str(retire_paths["fact"]),
            }
        ],
        now=now,
    )
    assert retire["action"]["expected_result_phase"] is None
    retire_path = tmp_path / "retire-undefined" / "receipt.json"
    write_action_resume_receipt(retire_path, retire)
    with pytest.raises(ActionResumeError) as retire_error:
        consume_action_resume_receipt(
            retire_path,
            expected_action_kind="retire",
            expected_work_key="wk:retire",
            expected_side_effect_id="se:retire:undefined",
            expected_next_action="retire one classified carrier",
            consumer=lambda: None,
            now=now,
        )
    assert retire_error.value.reason_code == "ACTION_RESULT_PHASE_UNDEFINED"
    assert not (retire_paths["run_dir"] / "action_consumptions").exists()


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
    assert json.loads(claim_path.read_text(encoding="utf-8"))["status"] == "effect_in_progress"

    with pytest.raises(ActionResumeError) as replay:
        _issue_apply(paths, now + timedelta(minutes=2))
    assert replay.value.reason_code == "SIDE_EFFECT_CLAIM_EXISTS"

    marker_sha = hashlib.sha256(effect_marker.read_bytes()).hexdigest()

    def readback(context: dict[str, object]) -> dict[str, object]:
        physical_ref = f"{effect_marker}#sha256={marker_sha}"
        finalizer_ref = _finalizer_ref(
            effect_marker.with_name("effect-finalizer.json"),
            work_key="wk:test:apply",
            kind="runtime_consumer",
            subject="test_file_readback.v1",
            observed_value=marker_sha,
            evidence_refs=[physical_ref],
        )
        return build_action_effect_outcome(
            context,
            status="already_applied",
            adapter_kind="test_file_readback.v1",
            observed_before=marker_sha,
            observed_after=marker_sha,
            evidence_refs=[physical_ref],
            task_run_evidence_refs=[finalizer_ref],
        )

    with pytest.raises(ActionResumeError) as lease_active:
        reconcile_action_resume_claim(
            claim_path,
            readback=readback,
            holder_id="reconciler:too-early",
            now=now + timedelta(minutes=2),
        )
    assert lease_active.value.reason_code == "ACTION_CLAIM_LEASE_ACTIVE"

    reconciled = reconcile_action_resume_claim(
        claim_path,
        readback=readback,
        holder_id="reconciler:test",
        now=now + timedelta(minutes=10),
    )
    assert reconciled["status"] == "event_pending"
    assert reconciled["claim_generation"] == 2
    assert reconciled["previous_fence_token"]

    evidence_ref = reconciled["effect_outcome"]["task_run_result"]["evidence_refs"][0]
    _append_event(
        paths,
        _event(
            "run-continuity-test",
            5,
            target="wk:test:apply",
            phase="work_unit_effect_verified",
            kind="result",
            side_effect_id="side-effect-new",
            evidence_refs=[evidence_ref],
        ),
    )
    closed = reconcile_action_resume_claim(claim_path, now=now + timedelta(minutes=11))
    assert closed["status"] == "closed"


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "CAS Canary",
        "GIT_AUTHOR_EMAIL": "cas-canary@example.invalid",
        "GIT_COMMITTER_NAME": "CAS Canary",
        "GIT_COMMITTER_EMAIL": "cas-canary@example.invalid",
    }
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=env,
    )
    return completed.stdout.decode("ascii").strip()


def _git_land_fixture(
    tmp_path: Path,
    *,
    name: str,
) -> tuple[Path, str, str, str]:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "--quiet")
    tree = _git(repo, "mktree", input_bytes=b"")
    old_oid = _git(repo, "commit-tree", tree, input_bytes=b"old\n")
    new_oid = _git(repo, "commit-tree", tree, "-p", old_oid, input_bytes=b"new\n")
    other_oid = _git(repo, "commit-tree", tree, "-p", old_oid, input_bytes=b"other\n")
    _git(repo, "update-ref", "refs/heads/canary", old_oid)
    return repo, old_oid, new_oid, other_oid


def _land_receipt(
    directory: Path,
    *,
    old_oid: str,
    now: datetime,
    work_key: str,
    side_effect_id: str,
) -> tuple[dict[str, Path], Path]:
    paths = _fixture(directory, work_key=work_key)
    fact = directory / "remote-ref.json"
    fact.write_text(
        json.dumps({"ref": "refs/heads/canary", "oid": old_oid}),
        encoding="utf-8",
    )
    receipt = issue_action_resume_receipt(
        checkpoint_path=paths["checkpoint"],
        action_kind="land",
        work_key=work_key,
        next_action="advance canary ref with remote expected-old CAS",
        side_effect_id=side_effect_id,
        expected_result_phase="work_unit_land_verified",
        semantic_facts=[
            {
                "kind": "git_remote_ref",
                "subject": "refs/heads/canary",
                "work_key": work_key,
                "observed_value": old_oid,
                "source_path": str(fact),
            }
        ],
        now=now,
    )
    receipt_path = directory / "receipt.json"
    write_action_resume_receipt(receipt_path, receipt)
    return paths, receipt_path


def test_git_update_ref_local_only_never_proves_remote_land(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    repo, old_oid, new_oid, _ = _git_land_fixture(tmp_path, name="git-local-only")
    paths, receipt_path = _land_receipt(
        tmp_path / "git-local-only-receipt",
        old_oid=old_oid,
        now=now,
        work_key="wk:test:git-local-only",
        side_effect_id="git-local-only",
    )

    with pytest.raises(ActionResumeError) as local_only:
        consume_action_resume_receipt(
            receipt_path,
            expected_action_kind="land",
            expected_work_key="wk:test:git-local-only",
            expected_side_effect_id="git-local-only",
            expected_next_action="advance canary ref with remote expected-old CAS",
            expected_result_phase="work_unit_land_verified",
            expected_version=old_oid,
            consumer=git_update_ref_cas_adapter(
                repo_path=repo,
                ref_name="refs/heads/canary",
                new_oid=new_oid,
                expected_old_oid=old_oid,
                evidence_path=tmp_path / "git-local-only-receipt" / "git-cas-readback.json",
            ),
            now=now + timedelta(minutes=1),
        )
    assert local_only.value.reason_code == "ACTION_EFFECT_READBACK_UNKNOWN"
    assert _git(repo, "rev-parse", "refs/heads/canary") == new_oid
    claims = list((paths["run_dir"] / "action_consumptions").glob("*.json"))
    assert len(claims) == 1
    claim = json.loads(claims[0].read_text(encoding="utf-8"))
    assert claim["status"] == "effect_unknown"
    assert claim["effect_outcome"]["adapter_kind"] == "git.local-update-ref.expected-old.v1"
    assert claim["effect_outcome"]["cas"]["applied"] is True
    assert not claim.get("required_task_run_event")
    local_finalizers = list((tmp_path / "git-local-only-receipt").glob("*.local-finalizer.json"))
    assert len(local_finalizers) == 1
    local_finalizer = json.loads(local_finalizers[0].read_text(encoding="utf-8"))
    assert local_finalizer["kind"] == "git_local_ref"
    assert local_finalizer["readback_verified"] is True
    assert not list((tmp_path / "git-local-only-receipt").glob("*.remote-finalizer.json"))
    assert not any(
        json.loads(line).get("phase") == "work_unit_land_verified"
        for line in (paths["run_dir"] / "events.jsonl").read_text(encoding="utf-8").splitlines()
    )


def test_git_remote_land_fails_closed_on_mismatch_or_unreachable(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    repo, old_oid, new_oid, other_oid = _git_land_fixture(tmp_path, name="git-remote-negative")

    def mismatch_runner(command: list[str]) -> subprocess.CompletedProcess[bytes]:
        if "ls-remote" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"{other_oid}\trefs/heads/canary\n".encode("ascii"),
                stderr=b"",
            )
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    _, mismatch_receipt = _land_receipt(
        tmp_path / "git-remote-mismatch",
        old_oid=old_oid,
        now=now,
        work_key="wk:test:git-remote-mismatch",
        side_effect_id="git-remote-mismatch",
    )
    mismatched = consume_action_resume_receipt(
        mismatch_receipt,
        expected_action_kind="land",
        expected_work_key="wk:test:git-remote-mismatch",
        expected_side_effect_id="git-remote-mismatch",
        expected_next_action="advance canary ref with remote expected-old CAS",
        expected_result_phase="work_unit_land_verified",
        expected_version=old_oid,
        consumer=git_update_ref_cas_adapter(
            repo_path=repo,
            ref_name="refs/heads/canary",
            new_oid=new_oid,
            expected_old_oid=old_oid,
            evidence_path=tmp_path / "git-remote-mismatch" / "git-cas-readback.json",
            remote="origin",
            remote_ref_name="refs/heads/canary",
            runner=mismatch_runner,
        ),
        now=now + timedelta(minutes=1),
    )
    assert mismatched["status"] == "aborted_pre_effect"
    assert mismatched["reason_code"] == "ACTION_CAS_CONFLICT_NO_EFFECT"
    assert _git(repo, "rev-parse", "refs/heads/canary") == old_oid
    assert not list((tmp_path / "git-remote-mismatch").glob("*.remote-finalizer.json"))

    def unreachable_runner(command: list[str]) -> subprocess.CompletedProcess[bytes]:
        if "ls-remote" in command:
            return subprocess.CompletedProcess(command, 128, stdout=b"", stderr=b"unreachable")
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    _, unreachable_receipt = _land_receipt(
        tmp_path / "git-remote-unreachable",
        old_oid=old_oid,
        now=now,
        work_key="wk:test:git-remote-unreachable",
        side_effect_id="git-remote-unreachable",
    )
    unreachable = consume_action_resume_receipt(
        unreachable_receipt,
        expected_action_kind="land",
        expected_work_key="wk:test:git-remote-unreachable",
        expected_side_effect_id="git-remote-unreachable",
        expected_next_action="advance canary ref with remote expected-old CAS",
        expected_result_phase="work_unit_land_verified",
        expected_version=old_oid,
        consumer=git_update_ref_cas_adapter(
            repo_path=repo,
            ref_name="refs/heads/canary",
            new_oid=new_oid,
            expected_old_oid=old_oid,
            evidence_path=tmp_path / "git-remote-unreachable" / "git-cas-readback.json",
            remote="origin",
            remote_ref_name="refs/heads/canary",
            runner=unreachable_runner,
        ),
        now=now + timedelta(minutes=1),
    )
    assert unreachable["status"] == "aborted_pre_effect"
    assert unreachable["reason_code"] == "ACTION_READBACK_PROVED_NO_EFFECT"
    assert _git(repo, "rev-parse", "refs/heads/canary") == old_oid
    assert not list((tmp_path / "git-remote-unreachable").glob("*.remote-finalizer.json"))


def test_git_remote_land_uses_force_with_lease_and_exact_ls_remote(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    repo, old_oid, new_oid, _ = _git_land_fixture(tmp_path, name="git-remote-positive")
    bare = tmp_path / "git-remote-positive.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "--quiet")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "origin", f"{old_oid}:refs/heads/canary")

    _, receipt_path = _land_receipt(
        tmp_path / "git-remote-positive-receipt",
        old_oid=old_oid,
        now=now,
        work_key="wk:test:git-remote-positive",
        side_effect_id="git-remote-positive",
    )
    applied = consume_action_resume_receipt(
        receipt_path,
        expected_action_kind="land",
        expected_work_key="wk:test:git-remote-positive",
        expected_side_effect_id="git-remote-positive",
        expected_next_action="advance canary ref with remote expected-old CAS",
        expected_result_phase="work_unit_land_verified",
        expected_version=old_oid,
        consumer=git_update_ref_cas_adapter(
            repo_path=repo,
            ref_name="refs/heads/canary",
            new_oid=new_oid,
            expected_old_oid=old_oid,
            evidence_path=tmp_path / "git-remote-positive-receipt" / "git-land-readback.json",
            remote="origin",
            remote_ref_name="refs/heads/canary",
        ),
        now=now + timedelta(minutes=1),
    )
    assert applied["status"] == "event_pending"
    assert _git(repo, "rev-parse", "refs/heads/canary") == new_oid
    assert _git(bare, "rev-parse", "refs/heads/canary") == new_oid
    outcome = applied["effect_outcome"]
    assert outcome["cas"]["expected_version"] == old_oid
    assert outcome["task_run_result"]["phase"] == "work_unit_land_verified"
    assert outcome["details"]["remote_ref_name"] == "refs/heads/canary"
    land_ref = outcome["task_run_result"]["evidence_refs"][0]
    land_evidence = json.loads(Path(land_ref.rsplit("#sha256=", 1)[0]).read_text(encoding="utf-8"))
    assert land_evidence["schema_version"] == "xinao.work_unit_finalizer_evidence.v1"
    assert land_evidence["kind"] == "git_remote_ref"
    assert land_evidence["work_key"] == "wk:test:git-remote-positive"
    assert land_evidence["subject"].endswith("#refs/heads/canary")
    assert land_evidence["observed_value"] == new_oid


def test_git_local_ref_finalizer_cannot_release_retire(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    paths = _fixture(tmp_path / "git-local-retire", work_key="wk:test:git-local-retire")
    local_fact = tmp_path / "git-local-retire" / "local-ref.json"
    local_fact.write_text('{"ref":"refs/heads/canary"}\n', encoding="utf-8")
    with pytest.raises(ActionResumeError) as rejected:
        issue_action_resume_receipt(
            checkpoint_path=paths["checkpoint"],
            action_kind="retire",
            work_key="wk:test:git-local-retire",
            next_action="retire carrier after remote land",
            side_effect_id="git-local-retire",
            semantic_facts=[
                {
                    "kind": "git_local_ref",
                    "subject": "refs/heads/canary",
                    "work_key": "wk:test:git-local-retire",
                    "observed_value": "a" * 40,
                    "source_path": str(local_fact),
                }
            ],
            now=now,
        )
    assert rejected.value.reason_code == "WORLD_FACT_INVALID"


def test_git_update_ref_adapter_rejects_non_land_phase_before_mutation(tmp_path: Path) -> None:
    repo, old_oid, new_oid, _ = _git_land_fixture(tmp_path, name="git-wrong-phase")
    effect_phase_adapter = git_update_ref_cas_adapter(
        repo_path=repo,
        ref_name="refs/heads/canary",
        new_oid=new_oid,
        expected_old_oid=old_oid,
        evidence_path=tmp_path / "git-wrong-phase" / "must-not-run.json",
        remote="origin",
        remote_ref_name="refs/heads/canary",
    )
    with pytest.raises(ActionResumeError) as wrong_phase:
        effect_phase_adapter(
            {
                "expected_result_phase": "work_unit_effect_verified",
                "expected_version": old_oid,
            }
        )
    assert wrong_phase.value.reason_code == "ACTION_RESULT_PHASE_MISMATCH"
    assert _git(repo, "rev-parse", "refs/heads/canary") == old_oid
    assert not (tmp_path / "git-wrong-phase" / "must-not-run.g0.json").exists()


def test_legacy_consumption_is_readable_but_never_promoted_to_closed(tmp_path: Path) -> None:
    claim_path = tmp_path / "legacy-claim.json"
    legacy = {
        "schema_version": "xinao.action_resume_consumption.v1",
        "status": "consumed",
        "work_key": "wk:legacy",
        "side_effect_id": "legacy-side-effect",
        "result_sha256": "0" * 64,
    }
    claim_path.write_bytes(_json_bytes(legacy))
    before = claim_path.read_bytes()
    projection = reconcile_action_resume_claim(claim_path)
    assert projection["status"] == "effect_unknown"
    assert projection["reason_code"] == "LEGACY_CONSUMPTION_UNPROVEN"
    assert projection["legacy_status"] == "consumed"
    assert claim_path.read_bytes() == before


def test_consume_canary_cli_uses_typed_adapter_in_a_fresh_process(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    paths = _fixture(tmp_path / "fresh-cli")
    receipt = _issue_apply(paths, now)
    receipt_path = tmp_path / "fresh-cli" / "receipt.json"
    canary_path = tmp_path / "fresh-cli" / "canary.txt"
    write_action_resume_receipt(receipt_path, receipt)
    repo_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_action_resume_consumer.py"),
            "consume-canary",
            "--receipt",
            str(receipt_path),
            "--action-kind",
            "apply",
            "--work-key",
            "wk:test:apply",
            "--side-effect-id",
            "side-effect-new",
            "--next-action",
            "apply exactly once",
            "--canary-output",
            str(canary_path),
            "--payload",
            "typed-cli-canary",
        ],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "event_pending"
    assert report["effect_outcome"]["schema_version"] == "xinao.action_effect_outcome.v3"
    assert canary_path.read_text(encoding="utf-8") == "typed-cli-canary"

    reconciled = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_action_resume_consumer.py"),
            "reconcile-claim",
            "--consumption-record",
            report["consumption_path"],
        ],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert reconciled.returncode == 0, reconciled.stderr
    assert json.loads(reconciled.stdout)["status"] == "event_pending"


def test_owner_command_reuses_stable_event_after_append_before_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    directory = tmp_path / "owner-replay"
    paths = _fixture(directory)
    pending = _pending_typed_apply(paths, directory, now)
    claim_path = Path(pending["consumption_path"])
    task_run_cli = directory / "task_run_fixture.py"
    _write_task_run_cli_fixture(task_run_cli)

    original_reconcile = action_resume_module.reconcile_action_resume_claim

    def crash_before_reconcile(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("simulated process loss after canonical append")

    monkeypatch.setattr(
        action_resume_module,
        "reconcile_action_resume_claim",
        crash_before_reconcile,
    )
    with pytest.raises(RuntimeError, match="after canonical append"):
        append_pending_action_event_and_reconcile(
            claim_path,
            task_run_cli=task_run_cli,
            now=now + timedelta(minutes=2),
        )
    monkeypatch.setattr(
        action_resume_module,
        "reconcile_action_resume_claim",
        original_reconcile,
    )
    after_append = (paths["run_dir"] / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(after_append) == 5
    assert json.loads(claim_path.read_text(encoding="utf-8"))["status"] == "event_pending"

    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_action_resume_consumer.py"),
            "close-pending",
            "--consumption-record",
            str(claim_path),
            "--task-run-cli",
            str(task_run_cli),
        ],
        cwd=repo_root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    closed = json.loads(completed.stdout)
    assert closed["status"] == "closed"
    assert closed["owner_event_replayed"] is True
    assert closed["owner_event_id"].startswith("action-resume:")
    final_events = (paths["run_dir"] / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(final_events) == 5
    appended = json.loads(final_events[-1])
    assert appended["event_id"] == closed["owner_event_id"]
    assert appended["phase"] == "work_unit_effect_verified"
    assert appended["evidence_refs"] == pending["required_task_run_event"]["evidence_refs"]


def test_owner_command_revalidates_finalizer_before_canonical_append(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)
    directory = tmp_path / "owner-tamper"
    paths = _fixture(directory)
    pending = _pending_typed_apply(paths, directory, now)
    claim_path = Path(pending["consumption_path"])
    finalizer_ref = pending["required_task_run_event"]["evidence_refs"][0]
    finalizer_path = Path(finalizer_ref.rsplit("#sha256=", 1)[0])
    finalizer_path.write_bytes(finalizer_path.read_bytes() + b" ")
    task_run_cli = directory / "task_run_fixture.py"
    _write_task_run_cli_fixture(task_run_cli)

    with pytest.raises(ActionResumeError) as caught:
        append_pending_action_event_and_reconcile(
            claim_path,
            task_run_cli=task_run_cli,
            now=now + timedelta(minutes=2),
        )
    assert caught.value.reason_code == "ACTION_EFFECT_OUTCOME_UNPROVEN"
    events = (paths["run_dir"] / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 4
    assert json.loads(claim_path.read_text(encoding="utf-8"))["status"] == "event_pending"


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
