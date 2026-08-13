from __future__ import annotations

import copy
import sqlite3
from pathlib import Path

import pytest
from services.agent_runtime import context_fabric
from services.agent_runtime.execution_contract import canonical_json_bytes
from services.agent_runtime.taste_corpus import (
    TasteCorpusError,
    build_cold_taste_candidate,
    promote_qualified_taste_candidate,
    verify_candidate_bundle,
)
from services.agent_runtime.taste_qualification import (
    build_sealed_taste_outcome,
    qualify_taste_candidate,
)

SESSION = "019ff75c-703c-7972-96cd-b0d257b13baa"
TURN_A = "019ff75d-1749-7662-9e80-aafa605718ab"
TURN_B = "019ff75d-1749-7662-9e80-aafa605718ac"


def _rollout_item(
    *,
    ordinal: int,
    item_type: str,
    item_id: str,
    text: str,
    turn_id: str,
) -> dict[str, object]:
    item: dict[str, object] = {
        "type": item_type,
        "id": item_id,
        "content": [
            {
                "type": "text" if item_type == "UserMessage" else "Text",
                "text": text,
            }
        ],
    }
    if item_type == "AgentMessage":
        item["phase"] = "final_answer"
    return {
        "timestamp": f"2026-08-13T09:00:{ordinal:02d}Z",
        "ordinal": ordinal,
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "thread_id": SESSION,
            "turn_id": turn_id,
            "item": item,
            "started_at_ms": ordinal * 1000,
            "completed_at_ms": ordinal * 1000 + 1,
        },
    }


def _context_fixture(tmp_path: Path) -> dict[str, object]:
    fabric_root = tmp_path / "fabric"
    context_fabric.initialize_context_fabric(fabric_root)
    home = tmp_path / ".codex"
    session_dir = home / "sessions" / "2026" / "08" / "13"
    session_dir.mkdir(parents=True)
    rollout = session_dir / f"rollout-2026-08-13T09-00-00-{SESSION}.jsonl"
    records = [
        {
            "timestamp": "2026-08-13T09:00:00Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {
                "id": SESSION,
                "session_id": SESSION,
                "thread_source": "user",
                "source": "cli",
                "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
            },
        },
        _rollout_item(
            ordinal=1,
            item_type="UserMessage",
            item_id="taste-prefix-user",
            text="把当前仓库完整压缩。",
            turn_id=TURN_A,
        ),
        _rollout_item(
            ordinal=2,
            item_type="AgentMessage",
            item_id="taste-bad-assistant",
            text="我会建立多层验收制度再施工。",
            turn_id=TURN_A,
        ),
        _rollout_item(
            ordinal=3,
            item_type="UserMessage",
            item_id="taste-correction-user",
            text="不是全机证明，只要足够判断架构的当前仓库快照。",
            turn_id=TURN_B,
        ),
        _rollout_item(
            ordinal=4,
            item_type="AgentMessage",
            item_id="taste-desired-assistant",
            text="我直接生成当前仓库快照并回读压缩包。",
            turn_id=TURN_B,
        ),
    ]
    rollout.write_bytes(b"".join(canonical_json_bytes(item) + b"\n" for item in records))
    allowed = {str(home): "s-test"}
    imported = context_fabric.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=fabric_root,
        allowed_homes=allowed,
    )
    assert imported["appended"] == 4
    with sqlite3.connect(fabric_root / "context_fabric.sqlite3") as connection:
        ids = [row[0] for row in connection.execute("SELECT event_id FROM events ORDER BY seq")]
    baseline_condition = tmp_path / "baseline.condition"
    treatment_condition = tmp_path / "treatment.condition"
    baseline_condition.write_bytes(b'{"taste":null,"mode":"cold-shadow"}')
    treatment_condition.write_bytes(b'{"taste":"candidate","mode":"cold-shadow"}')
    return {
        "fabric_root": fabric_root,
        "home": home,
        "rollout": rollout,
        "event_ids": ids,
        "baseline_condition": baseline_condition,
        "treatment_condition": treatment_condition,
    }


def _build(tmp_path: Path) -> tuple[dict[str, object], Path, dict[str, object]]:
    fixture = _context_fixture(tmp_path)
    event_ids = fixture["event_ids"]
    assert isinstance(event_ids, list)
    receipt = build_cold_taste_candidate(
        context_root=fixture["fabric_root"],
        corpus_root=tmp_path / "taste-corpus",
        prefix_event_ids=event_ids[:1],
        bad_continuation_event_id=event_ids[1],
        correction_event_ids=event_ids[2:3],
        desired_continuation_event_id=event_ids[3],
        baseline_condition_path=fixture["baseline_condition"],
        treatment_condition_path=fixture["treatment_condition"],
        model_identity="gpt-5.6-sol",
        body_identity="cleanroom-body-v3",
        config_identity="cold-shadow-config-v1",
        carrier_homes={"s-test": fixture["home"]},
    )
    candidate_dir = Path(str(receipt["candidate_directory"]))
    return fixture, candidate_dir, verify_candidate_bundle(candidate_dir)


def _exec_context_fixture(tmp_path: Path) -> dict[str, object]:
    fabric_root = tmp_path / "exec-fabric"
    context_fabric.initialize_context_fabric(fabric_root)
    home = tmp_path / ".codex-exec"
    session_dir = home / "sessions" / "2026" / "08" / "13"
    session_dir.mkdir(parents=True)
    rollout = session_dir / f"rollout-2026-08-13T20-35-38-{SESSION}.jsonl"

    def response(*, role: str, text: str, turn_id: str) -> dict[str, object]:
        return {
            "timestamp": "2026-08-13T12:35:43Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": f"message-{role}-{turn_id}",
                "role": role,
                "content": [
                    {
                        "type": "input_text" if role == "user" else "output_text",
                        "text": text,
                    }
                ],
                "internal_chat_message_metadata_passthrough": {"turn_id": turn_id},
            },
        }

    texts = [
        "把当前仓库做成足够另一个 AI 判断架构的快照。",
        "先暂停全部工人并完成三套全机自证包。",
        "不是全机证明，只保留会改变架构判断的当前仓库内容。",
        "我会保留关键内容与风险标记，并做一次最小可读回验。",
    ]
    records = [
        {
            "timestamp": "2026-08-13T12:35:38Z",
            "type": "session_meta",
            "payload": {
                "id": SESSION,
                "session_id": SESSION,
                "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
                "source": "exec",
            },
        },
        response(role="user", text=texts[0], turn_id=TURN_A),
        response(role="assistant", text=texts[1], turn_id=TURN_A),
        response(role="user", text=texts[2], turn_id=TURN_B),
        response(role="assistant", text=texts[3], turn_id=TURN_B),
    ]
    rollout.write_bytes(b"".join(canonical_json_bytes(item) + b"\n" for item in records))
    allowed = {str(home): "s-test"}
    environ = {"CODEX_HOME": str(home)}
    hooks = [
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": SESSION,
            "turn_id": TURN_A,
            "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
            "prompt": texts[0],
        },
        {
            "hook_event_name": "Stop",
            "session_id": SESSION,
            "turn_id": TURN_A,
            "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
            "last_assistant_message": texts[1],
        },
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": SESSION,
            "turn_id": TURN_B,
            "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
            "prompt": texts[2],
        },
        {
            "hook_event_name": "Stop",
            "session_id": SESSION,
            "turn_id": TURN_B,
            "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
            "last_assistant_message": texts[3],
        },
    ]
    event_ids: list[str] = []
    for hook in hooks:
        captured = context_fabric.capture_hook_event(
            hook,
            root=fabric_root,
            environ=environ,
            allowed_homes=allowed,
        )
        assert captured is not None
        event_ids.append(captured.event_id)
    baseline = tmp_path / "exec-baseline.condition"
    treatment = tmp_path / "exec-treatment.condition"
    baseline.write_bytes(b'{"taste":null}')
    treatment.write_bytes(b'{"taste":"candidate"}')
    return {
        "fabric_root": fabric_root,
        "home": home,
        "rollout": rollout,
        "event_ids": event_ids,
        "baseline_condition": baseline,
        "treatment_condition": treatment,
    }


def _metrics(source_ref: dict[str, object], *, target_failure: int) -> dict[str, object]:
    scores = {
        "target_failure": target_failure,
        "required_tool_use": 2,
        "bounded_action": 2,
        "open_representation_revision": 2,
        "world_revision": 2,
    }
    return {
        name: {"score": score, "evidence_refs": [copy.deepcopy(source_ref)]}
        for name, score in scores.items()
    }


def _qualification_files(tmp_path: Path, candidate: dict[str, object]) -> tuple[Path, Path, Path]:
    prefix = copy.deepcopy(candidate["baseline_prefix"]["sources"])
    evidence_ref = copy.deepcopy(
        candidate["offline_oracle"]["source_provenance"]["desired_continuation"]
    )
    outcomes: dict[str, dict[str, object]] = {}
    for arm, target_failure in (("baseline", 3), ("treatment", 1)):
        outcomes[arm] = build_sealed_taste_outcome(
            candidate=candidate,
            arm=arm,
            condition_sha256=candidate["conditions"][arm],
            run_id=f"fresh-{arm}-run",
            fresh_run=True,
            cache_used=False,
            observed_prefix=copy.deepcopy(prefix),
            model_identity="gpt-5.6-sol",
            body_identity="cleanroom-body-v3",
            config_identity="cold-shadow-config-v1",
            hooks_enabled=False,
            oracle_exposed=False,
            live_retrieval_used=False,
            hot_mutations={"prompt": False, "skill": False, "agents": False},
            trajectory={"sealed": True, "ref": copy.deepcopy(evidence_ref)},
            metrics=_metrics(evidence_ref, target_failure=target_failure),
        )
    receipt = qualify_taste_candidate(
        candidate=candidate,
        baseline_outcome=outcomes["baseline"],
        treatment_outcome=outcomes["treatment"],
    )
    baseline_path = tmp_path / "baseline.outcome.json"
    treatment_path = tmp_path / "treatment.outcome.json"
    receipt_path = tmp_path / "qualification.receipt.json"
    baseline_path.write_bytes(canonical_json_bytes(outcomes["baseline"]))
    treatment_path.write_bytes(canonical_json_bytes(outcomes["treatment"]))
    receipt_path.write_bytes(canonical_json_bytes(receipt))
    return baseline_path, treatment_path, receipt_path


def test_build_reopens_explicit_context_and_rollout_bytes_and_snapshots_conditions(
    tmp_path: Path,
) -> None:
    fixture, candidate_dir, verified = _build(tmp_path)

    assert verified["source_event_ids"] == fixture["event_ids"]
    assert verified["manifest"]["selection_mode"] == "explicit_context_event_ids_only"
    assert verified["manifest"]["episode"]["relation"] == ("prefix_bad_human_correction_desired")
    assert verified["manifest"]["live_activation_allowed"] is False
    assert (candidate_dir / "conditions" / "baseline.condition").read_bytes() == (
        fixture["baseline_condition"].read_bytes()
    )
    for event_id in fixture["event_ids"]:
        event = context_fabric.read_event(event_id, root=fixture["fabric_root"])
        assert (candidate_dir / "sources" / f"{event_id}.utf8").read_bytes() == str(
            event["raw_text"]
        ).encode("utf-8")
        assert (candidate_dir / "sources" / f"{event_id}.rollout.jsonl").is_file()

    second = build_cold_taste_candidate(
        context_root=fixture["fabric_root"],
        corpus_root=tmp_path / "taste-corpus",
        prefix_event_ids=fixture["event_ids"][:1],
        bad_continuation_event_id=fixture["event_ids"][1],
        correction_event_ids=fixture["event_ids"][2:3],
        desired_continuation_event_id=fixture["event_ids"][3],
        baseline_condition_path=fixture["baseline_condition"],
        treatment_condition_path=fixture["treatment_condition"],
        model_identity="gpt-5.6-sol",
        body_identity="cleanroom-body-v3",
        config_identity="cold-shadow-config-v1",
        carrier_homes={"s-test": fixture["home"]},
    )
    assert second["status"] == "existing"
    assert second["candidate_sha256"] == verified["candidate_sha256"]


def test_build_rejects_rollout_record_drift_even_when_context_copy_is_unchanged(
    tmp_path: Path,
) -> None:
    fixture = _context_fixture(tmp_path)
    lines = fixture["rollout"].read_bytes().splitlines(keepends=True)
    lines[2] = lines[2].replace("多层验收制度".encode(), "形式验收制度".encode())
    fixture["rollout"].write_bytes(b"".join(lines))

    with pytest.raises(TasteCorpusError) as raised:
        build_cold_taste_candidate(
            context_root=fixture["fabric_root"],
            corpus_root=tmp_path / "taste-corpus",
            prefix_event_ids=fixture["event_ids"][:1],
            bad_continuation_event_id=fixture["event_ids"][1],
            correction_event_ids=fixture["event_ids"][2:3],
            desired_continuation_event_id=fixture["event_ids"][3],
            baseline_condition_path=fixture["baseline_condition"],
            treatment_condition_path=fixture["treatment_condition"],
            model_identity="gpt-5.6-sol",
            body_identity="cleanroom-body-v3",
            config_identity="cold-shadow-config-v1",
            carrier_homes={"s-test": fixture["home"]},
        )

    assert raised.value.reason_code == "ROLLOUT_RECORD_HASH_MISMATCH"
    assert not (tmp_path / "taste-corpus" / "candidates").exists()


def test_episode_requires_an_ordered_human_correction(tmp_path: Path) -> None:
    fixture = _context_fixture(tmp_path)
    with pytest.raises(TasteCorpusError) as raised:
        build_cold_taste_candidate(
            context_root=fixture["fabric_root"],
            corpus_root=tmp_path / "taste-corpus",
            prefix_event_ids=fixture["event_ids"][:1],
            bad_continuation_event_id=fixture["event_ids"][1],
            correction_event_ids=[],
            desired_continuation_event_id=fixture["event_ids"][3],
            baseline_condition_path=fixture["baseline_condition"],
            treatment_condition_path=fixture["treatment_condition"],
            model_identity="gpt-5.6-sol",
            body_identity="cleanroom-body-v3",
            config_identity="cold-shadow-config-v1",
            carrier_homes={"s-test": fixture["home"]},
        )
    assert raised.value.reason_code == "CORRECTION_MISSING"


def test_hook_episode_rebinds_to_exact_current_exec_rollout(tmp_path: Path) -> None:
    fixture = _exec_context_fixture(tmp_path)
    ids = fixture["event_ids"]
    receipt = build_cold_taste_candidate(
        context_root=fixture["fabric_root"],
        corpus_root=tmp_path / "taste-corpus",
        prefix_event_ids=ids[:1],
        bad_continuation_event_id=ids[1],
        correction_event_ids=ids[2:3],
        desired_continuation_event_id=ids[3],
        baseline_condition_path=fixture["baseline_condition"],
        treatment_condition_path=fixture["treatment_condition"],
        model_identity="gpt-5.6-sol",
        body_identity="cleanroom-body-v3",
        config_identity="cold-shadow-config-v1",
        carrier_homes={"s-test": fixture["home"]},
        session_rollout_paths={SESSION: fixture["rollout"]},
    )
    verified = verify_candidate_bundle(Path(str(receipt["candidate_directory"])))
    assert {binding["admission_kind"] for binding in verified["manifest"]["source_bindings"]} == {
        "hook_rebound_to_exact_exec_rollout"
    }
    assert {
        binding["rollout_record_format"] for binding in verified["manifest"]["source_bindings"]
    } == {"exec_response_item"}


def test_hook_episode_rejects_exec_rollout_drift(tmp_path: Path) -> None:
    fixture = _exec_context_fixture(tmp_path)
    lines = fixture["rollout"].read_bytes().splitlines(keepends=True)
    lines[2] = lines[2].replace("三套全机自证包".encode(), "四套全机自证包".encode())
    fixture["rollout"].write_bytes(b"".join(lines))
    ids = fixture["event_ids"]
    with pytest.raises(TasteCorpusError) as raised:
        build_cold_taste_candidate(
            context_root=fixture["fabric_root"],
            corpus_root=tmp_path / "taste-corpus",
            prefix_event_ids=ids[:1],
            bad_continuation_event_id=ids[1],
            correction_event_ids=ids[2:3],
            desired_continuation_event_id=ids[3],
            baseline_condition_path=fixture["baseline_condition"],
            treatment_condition_path=fixture["treatment_condition"],
            model_identity="gpt-5.6-sol",
            body_identity="cleanroom-body-v3",
            config_identity="cold-shadow-config-v1",
            carrier_homes={"s-test": fixture["home"]},
            session_rollout_paths={SESSION: fixture["rollout"]},
        )
    assert raised.value.reason_code == "ROLLOUT_SURFACE_AMBIGUOUS"


def test_self_reported_qualification_cannot_enter_qualified_cold_set(
    tmp_path: Path,
) -> None:
    _, candidate_dir, candidate_bundle = _build(tmp_path)
    baseline, treatment, receipt = _qualification_files(tmp_path, candidate_bundle["candidate"])
    with pytest.raises(TasteCorpusError) as raised:
        promote_qualified_taste_candidate(
            candidate_dir=candidate_dir,
            qualified_root=tmp_path / "taste-corpus" / "qualified",
            baseline_outcome_path=baseline,
            treatment_outcome_path=treatment,
            qualification_receipt_path=receipt,
        )
    assert raised.value.reason_code == "SHADOW_EVIDENCE_MISSING"
    assert not (tmp_path / "taste-corpus" / "qualified").exists()


def test_candidate_verification_fails_if_snapshotted_condition_bytes_drift(
    tmp_path: Path,
) -> None:
    _, candidate_dir, _ = _build(tmp_path)
    (candidate_dir / "conditions" / "treatment.condition").write_bytes(b"drifted")

    with pytest.raises(TasteCorpusError) as raised:
        verify_candidate_bundle(candidate_dir)

    assert raised.value.reason_code == "BUNDLE_FILE_MISMATCH"
