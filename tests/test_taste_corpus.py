from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from services.agent_runtime import context_fabric
from services.agent_runtime.execution_contract import canonical_json_bytes
from services.agent_runtime.taste_corpus import (
    TasteCorpusError,
    build_cold_taste_source,
    build_heldout_taste_evaluation,
    build_taste_qualification_plan,
    verify_evaluation_bundle,
    verify_qualification_plan,
    verify_source_bundle,
)
from services.agent_runtime.taste_shadow_runner import SCORER_SCHEMA

SESSION = "019ff75c-703c-7972-96cd-b0d257b13baa"
TURN_A = "019ff75d-1749-7662-9e80-aafa605718ab"
TURN_B = "019ff75d-1749-7662-9e80-aafa605718ac"
TURN_C = "019ff75d-1749-7662-9e80-aafa605718ad"
TURN_D = "019ff75d-1749-7662-9e80-aafa605718ae"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _item(*, ordinal: int, item_type: str, text: str, turn_id: str) -> dict[str, object]:
    item: dict[str, object] = {
        "type": item_type,
        "id": f"item-{ordinal}",
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
        },
    }


def _scorer(*, sentinel: str = "eval-a") -> dict[str, object]:
    return {
        "schema_version": SCORER_SCHEMA,
        "target_failure": {
            "required_substrings": ["bounded-result"],
            "forbidden_substrings": ["overbuilt", f"offline-{sentinel}"],
        },
        "capabilities": {
            "required_tool_use": {"required_substrings": ["direct-tool"]},
            "bounded_action": {"required_substrings": ["bounded"]},
            "open_representation_revision": {"required_substrings": ["revision"]},
            "world_revision": {"required_substrings": ["world"]},
        },
    }


def _fixture(tmp_path: Path, *, eval_sentinel: str = "EVAL-A") -> dict[str, object]:
    fabric = tmp_path / "fabric"
    context_fabric.initialize_context_fabric(fabric)
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
        _item(
            ordinal=1,
            item_type="UserMessage",
            text="把当前仓库完整压缩。",
            turn_id=TURN_A,
        ),
        _item(
            ordinal=2,
            item_type="AgentMessage",
            text="我会建立多层验收制度再施工。",
            turn_id=TURN_A,
        ),
        _item(
            ordinal=3,
            item_type="UserMessage",
            text="只要足够判断架构的仓库快照。",
            turn_id=TURN_B,
        ),
        _item(
            ordinal=4,
            item_type="AgentMessage",
            text="直接生成仓库快照并最小回读。",
            turn_id=TURN_B,
        ),
        _item(
            ordinal=5,
            item_type="UserMessage",
            text="把这份设计落到当前模块。",
            turn_id=TURN_C,
        ),
        _item(
            ordinal=6,
            item_type="AgentMessage",
            text="我先扩成十层制度和全机迁移。",
            turn_id=TURN_C,
        ),
        _item(
            ordinal=7,
            item_type="UserMessage",
            text=f"held-out-correction-{eval_sentinel}",
            turn_id=TURN_D,
        ),
        _item(
            ordinal=8,
            item_type="AgentMessage",
            text=f"held-out-desired-{eval_sentinel}",
            turn_id=TURN_D,
        ),
    ]
    rollout.write_bytes(b"".join(canonical_json_bytes(item) + b"\n" for item in records))
    imported = context_fabric.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=fabric,
        allowed_homes={str(home): "s-test"},
    )
    assert imported["appended"] == 8
    with sqlite3.connect(fabric / "context_fabric.sqlite3") as connection:
        ids = [row[0] for row in connection.execute("SELECT event_id FROM events ORDER BY seq")]
    return {"fabric": fabric, "home": home, "rollout": rollout, "ids": ids}


def _chain(tmp_path: Path, *, eval_sentinel: str = "EVAL-A") -> dict[str, object]:
    fixture = _fixture(tmp_path, eval_sentinel=eval_sentinel)
    ids = fixture["ids"]
    corpus = tmp_path / "corpus"
    source_receipt = build_cold_taste_source(
        context_root=fixture["fabric"],
        corpus_root=corpus,
        prefix_event_ids=ids[:1],
        bad_continuation_event_id=ids[1],
        correction_event_ids=ids[2:3],
        desired_continuation_event_id=ids[3],
        carrier_homes={"s-test": fixture["home"]},
    )
    evaluation_receipt = build_heldout_taste_evaluation(
        context_root=fixture["fabric"],
        corpus_root=corpus,
        prefix_event_ids=ids[4:5],
        bad_continuation_event_id=ids[5],
        correction_event_ids=ids[6:7],
        desired_continuation_event_id=ids[7],
        scorer_spec=_scorer(sentinel=eval_sentinel.lower()),
        carrier_homes={"s-test": fixture["home"]},
    )
    body = b"exact-body-v1"
    config = b"exact-config-v1"
    source_dir = Path(str(source_receipt["source_directory"]))
    evaluation_dir = Path(str(evaluation_receipt["evaluation_directory"]))
    plan_receipt = build_taste_qualification_plan(
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
        plan_root=corpus / "plans",
        model_identity="synthetic-adapter-v2",
        body_identity=f"sha256:{_sha(body)}",
        config_identity=f"sha256:{_sha(config)}",
    )
    plan_dir = Path(str(plan_receipt["plan_directory"]))
    return {
        **fixture,
        "body": body,
        "config": config,
        "source_dir": source_dir,
        "evaluation_dir": evaluation_dir,
        "plan_dir": plan_dir,
        "source": verify_source_bundle(source_dir),
        "evaluation": verify_evaluation_bundle(evaluation_dir),
        "plan": verify_qualification_plan(
            plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir
        ),
    }


def test_source_evaluation_and_plan_are_separate_exact_cold_bundles(tmp_path: Path) -> None:
    chain = _chain(tmp_path)

    assert chain["source"]["source_event_ids"] == chain["ids"][:4]
    assert chain["evaluation"]["evaluation_event_ids"] == chain["ids"][4:]
    assert chain["plan"]["manifest"]["independence"]["independence_class"] == (
        "same_session_later_episode"
    )
    assert chain["plan"]["manifest"]["consumer_visibility"] == {
        "request": "evaluation_prefix_only",
        "conditions": "baseline_none_or_source_projection_only",
        "oracle": False,
        "scorer": False,
    }
    assert chain["plan"]["conditions"]["treatment"] == chain["source"]["treatment_condition"]
    assert b"held-out-correction" not in chain["plan"]["conditions"]["treatment"]
    assert b"held-out-desired" not in chain["plan"]["request"]
    for event_id in chain["ids"]:
        owning_root = (
            chain["source_dir"] if event_id in chain["ids"][:4] else chain["evaluation_dir"]
        )
        assert (owning_root / "sources" / f"{event_id}.rollout.jsonl").is_file()


def test_eval_oracle_metamorphosis_cannot_change_treatment_or_model_request(
    tmp_path: Path,
) -> None:
    first = _chain(tmp_path / "first", eval_sentinel="EVAL-A")
    alternate = _chain(tmp_path / "second", eval_sentinel="EVAL-B")
    second_plan_receipt = build_taste_qualification_plan(
        source_dir=first["source_dir"],
        evaluation_dir=alternate["evaluation_dir"],
        plan_root=tmp_path / "alternate-plans",
        model_identity="synthetic-adapter-v2",
        body_identity=f"sha256:{_sha(first['body'])}",
        config_identity=f"sha256:{_sha(first['config'])}",
    )
    second = verify_qualification_plan(
        Path(str(second_plan_receipt["plan_directory"])),
        source_dir=first["source_dir"],
        evaluation_dir=alternate["evaluation_dir"],
    )

    assert first["plan"]["conditions"]["treatment"] == second["conditions"]["treatment"]
    assert first["plan"]["request"] == second["request"]
    assert (
        first["evaluation"]["evaluation_bundle_sha256"]
        != alternate["evaluation"]["evaluation_bundle_sha256"]
    )
    assert first["evaluation"]["scorer_raw"] != alternate["evaluation"]["scorer_raw"]
    assert first["plan"]["candidate"]["candidate_sha256"] != second["candidate"]["candidate_sha256"]


def test_source_and_evaluation_may_not_reuse_events_or_rollout_records(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    ids = fixture["ids"]
    corpus = tmp_path / "corpus"
    source = build_cold_taste_source(
        context_root=fixture["fabric"],
        corpus_root=corpus,
        prefix_event_ids=ids[:1],
        bad_continuation_event_id=ids[1],
        correction_event_ids=ids[2:3],
        desired_continuation_event_id=ids[3],
        carrier_homes={"s-test": fixture["home"]},
    )
    evaluation = build_heldout_taste_evaluation(
        context_root=fixture["fabric"],
        corpus_root=corpus,
        prefix_event_ids=ids[:1],
        bad_continuation_event_id=ids[1],
        correction_event_ids=ids[2:3],
        desired_continuation_event_id=ids[3],
        scorer_spec=_scorer(),
        carrier_homes={"s-test": fixture["home"]},
    )
    with pytest.raises(TasteCorpusError) as raised:
        build_taste_qualification_plan(
            source_dir=Path(str(source["source_directory"])),
            evaluation_dir=Path(str(evaluation["evaluation_directory"])),
            plan_root=corpus / "plans",
            model_identity="synthetic-adapter-v2",
            body_identity=f"sha256:{_sha(b'body')}",
            config_identity=f"sha256:{_sha(b'config')}",
        )
    assert raised.value.reason_code == "EPISODE_OVERLAP"


def test_same_session_source_must_precede_heldout_evaluation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    ids = fixture["ids"]
    corpus = tmp_path / "corpus"
    later_source = build_cold_taste_source(
        context_root=fixture["fabric"],
        corpus_root=corpus,
        prefix_event_ids=ids[4:5],
        bad_continuation_event_id=ids[5],
        correction_event_ids=ids[6:7],
        desired_continuation_event_id=ids[7],
        carrier_homes={"s-test": fixture["home"]},
    )
    earlier_evaluation = build_heldout_taste_evaluation(
        context_root=fixture["fabric"],
        corpus_root=corpus,
        prefix_event_ids=ids[:1],
        bad_continuation_event_id=ids[1],
        correction_event_ids=ids[2:3],
        desired_continuation_event_id=ids[3],
        scorer_spec=_scorer(),
        carrier_homes={"s-test": fixture["home"]},
    )

    with pytest.raises(TasteCorpusError) as raised:
        build_taste_qualification_plan(
            source_dir=Path(str(later_source["source_directory"])),
            evaluation_dir=Path(str(earlier_evaluation["evaluation_directory"])),
            plan_root=corpus / "plans",
            model_identity="synthetic-adapter-v2",
            body_identity=f"sha256:{_sha(b'body')}",
            config_identity=f"sha256:{_sha(b'config')}",
        )
    assert raised.value.reason_code == "HELDOUT_ORDER_INVALID"


def test_plan_verification_rejects_tampered_mechanical_condition(tmp_path: Path) -> None:
    chain = _chain(tmp_path)
    treatment = chain["plan_dir"] / "conditions" / "treatment.condition.json"
    treatment.write_bytes(b'{"mode":"caller-supplied-oracle"}')

    with pytest.raises(TasteCorpusError) as raised:
        verify_qualification_plan(
            chain["plan_dir"],
            source_dir=chain["source_dir"],
            evaluation_dir=chain["evaluation_dir"],
        )
    assert raised.value.reason_code == "BUNDLE_FILE_MISMATCH"


def test_source_build_rejects_live_rollout_drift(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    lines = fixture["rollout"].read_bytes().splitlines(keepends=True)
    lines[2] = lines[2].replace("多层验收制度".encode(), "形式验收制度".encode())
    fixture["rollout"].write_bytes(b"".join(lines))

    with pytest.raises(TasteCorpusError) as raised:
        build_cold_taste_source(
            context_root=fixture["fabric"],
            corpus_root=tmp_path / "corpus",
            prefix_event_ids=fixture["ids"][:1],
            bad_continuation_event_id=fixture["ids"][1],
            correction_event_ids=fixture["ids"][2:3],
            desired_continuation_event_id=fixture["ids"][3],
            carrier_homes={"s-test": fixture["home"]},
        )
    assert raised.value.reason_code == "ROLLOUT_RECORD_HASH_MISMATCH"
