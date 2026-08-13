from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from services.agent_runtime import context_fabric
from services.agent_runtime.execution_contract import canonical_json_bytes
from services.agent_runtime.taste_corpus import (
    build_cold_taste_source,
    build_heldout_taste_evaluation,
    build_taste_qualification_plan,
    promote_qualified_taste_candidate,
    verify_qualified_bundle,
)
from services.agent_runtime.taste_shadow_runner import (
    CONSUMER_OUTPUT_SCHEMA,
    SCORER_SCHEMA,
    TasteShadowRunnerError,
    run_fresh_shadow_pair,
    score_shadow_pair,
    verify_shadow_pair,
    verify_shadow_score_bundle,
)

SESSION = "019ff75c-703c-7972-96cd-b0d257b13baa"
TURNS = [
    "019ff75d-1749-7662-9e80-aafa605718ab",
    "019ff75d-1749-7662-9e80-aafa605718ac",
    "019ff75d-1749-7662-9e80-aafa605718ad",
    "019ff75d-1749-7662-9e80-aafa605718ae",
]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _item(*, ordinal: int, speaker: str, text: str, turn_id: str) -> dict[str, object]:
    item_type = "UserMessage" if speaker == "user" else "AgentMessage"
    item: dict[str, object] = {
        "type": item_type,
        "id": f"item-{ordinal}",
        "content": [
            {
                "type": "text" if speaker == "user" else "Text",
                "text": text,
            }
        ],
    }
    if speaker == "assistant":
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


def _scorer() -> dict[str, object]:
    return {
        "schema_version": SCORER_SCHEMA,
        "target_failure": {
            "required_substrings": ["bounded-result"],
            "forbidden_substrings": ["overbuilt", "OFFLINE-SCORER-SENTINEL"],
        },
        "capabilities": {
            "required_tool_use": {"required_substrings": ["direct-tool"]},
            "bounded_action": {"required_substrings": ["bounded"]},
            "open_representation_revision": {"required_substrings": ["revision"]},
            "world_revision": {"required_substrings": ["world"]},
        },
    }


def _chain(tmp_path: Path) -> dict[str, Path]:
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
        _item(ordinal=1, speaker="user", text="做当前仓库快照。", turn_id=TURNS[0]),
        _item(ordinal=2, speaker="assistant", text="先做全机证明。", turn_id=TURNS[0]),
        _item(ordinal=3, speaker="user", text="只做最浅充分仓库快照。", turn_id=TURNS[1]),
        _item(ordinal=4, speaker="assistant", text="直接做仓库快照。", turn_id=TURNS[1]),
        _item(ordinal=5, speaker="user", text="落实当前模块。", turn_id=TURNS[2]),
        _item(ordinal=6, speaker="assistant", text="先扩成十层制度。", turn_id=TURNS[2]),
        _item(
            ordinal=7,
            speaker="user",
            text="HELDOUT-CORRECTION-ORACLE",
            turn_id=TURNS[3],
        ),
        _item(
            ordinal=8,
            speaker="assistant",
            text="HELDOUT-DESIRED-ORACLE",
            turn_id=TURNS[3],
        ),
    ]
    rollout.write_bytes(b"".join(canonical_json_bytes(row) + b"\n" for row in records))
    imported = context_fabric.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=fabric,
        allowed_homes={str(home): "s-test"},
    )
    assert imported["appended"] == 8
    with sqlite3.connect(fabric / "context_fabric.sqlite3") as connection:
        ids = [row[0] for row in connection.execute("SELECT event_id FROM events ORDER BY seq")]
    corpus = tmp_path / "corpus"
    source = build_cold_taste_source(
        context_root=fabric,
        corpus_root=corpus,
        prefix_event_ids=ids[:1],
        bad_continuation_event_id=ids[1],
        correction_event_ids=ids[2:3],
        desired_continuation_event_id=ids[3],
        carrier_homes={"s-test": home},
    )
    evaluation = build_heldout_taste_evaluation(
        context_root=fabric,
        corpus_root=corpus,
        prefix_event_ids=ids[4:5],
        bad_continuation_event_id=ids[5],
        correction_event_ids=ids[6:7],
        desired_continuation_event_id=ids[7],
        scorer_spec=_scorer(),
        carrier_homes={"s-test": home},
    )
    body = tmp_path / "body.bin"
    config = tmp_path / "config.bin"
    body.write_bytes(b"exact-body-v2")
    config.write_bytes(b"exact-config-v2")
    source_dir = Path(str(source["source_directory"]))
    evaluation_dir = Path(str(evaluation["evaluation_directory"]))
    plan = build_taste_qualification_plan(
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
        plan_root=corpus / "plans",
        model_identity="synthetic-adapter-v2",
        body_identity=f"sha256:{_sha(body.read_bytes())}",
        config_identity=f"sha256:{_sha(config.read_bytes())}",
    )
    return {
        "source": source_dir,
        "evaluation": evaluation_dir,
        "plan": Path(str(plan["plan_directory"])),
        "body": body,
        "config": config,
    }


def _consumer(tmp_path: Path, *, mutate_tree: bool = False) -> Path:
    path = tmp_path / ("mutating-consumer.py" if mutate_tree else "consumer.py")
    mutation = 'pathlib.Path("scorer.json").write_text("leak")' if mutate_tree else ""
    path.write_text(
        f"""
import hashlib
import json
import pathlib
import sys
import uuid

request_bytes = sys.stdin.buffer.read()
body_bytes = pathlib.Path("body.bin").read_bytes()
config_bytes = pathlib.Path("config.bin").read_bytes()
condition_bytes = pathlib.Path("condition.bin").read_bytes()
condition = json.loads(condition_bytes.decode("utf-8"))
assert not pathlib.Path("scorer.json").exists()
assert not pathlib.Path("oracle.json").exists()
assert not (pathlib.Path("..").resolve() / "scorer.json").exists()
{mutation}
if condition["mode"] == "baseline_none":
    response = "overbuilt direct-tool bounded revision world"
else:
    response = "bounded-result direct-tool bounded revision world"
result = {{
    "schema_version": "s.taste_shadow_consumer_output.v2",
    "response_text": response,
    "session_identity": str(uuid.uuid4()),
    "observed_model_identity": "synthetic-adapter-v2",
    "observed_request_sha256": hashlib.sha256(request_bytes).hexdigest(),
    "observed_body_sha256": hashlib.sha256(body_bytes).hexdigest(),
    "observed_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
    "observed_condition_sha256": hashlib.sha256(condition_bytes).hexdigest(),
}}
sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
""".strip(),
        encoding="utf-8",
    )
    return path


def _run(tmp_path: Path) -> tuple[dict[str, Path], dict[str, object], Path]:
    chain = _chain(tmp_path)
    result = run_fresh_shadow_pair(
        source_dir=chain["source"],
        evaluation_dir=chain["evaluation"],
        plan_dir=chain["plan"],
        output_root=tmp_path / "shadow",
        command=[sys.executable, str(_consumer(tmp_path))],
        body_path=chain["body"],
        config_path=chain["config"],
        timeout_seconds=30,
        environment={"PYTHONIOENCODING": "utf-8"},
    )
    pair_dir = Path(str(result["pair_directory"]))
    return chain, result, pair_dir


def test_twins_are_sealed_before_offline_score_and_full_chain_promotes_cold(
    tmp_path: Path,
) -> None:
    chain, result, pair_dir = _run(tmp_path)
    pair = verify_shadow_pair(
        pair_dir,
        plan_dir=chain["plan"],
        source_dir=chain["source"],
        evaluation_dir=chain["evaluation"],
    )
    assert result["scoring_complete"] is False
    assert pair["baseline"]["process_id"] != pair["treatment"]["process_id"]
    assert pair["baseline"]["same_inputs"] == pair["treatment"]["same_inputs"]
    assert pair["baseline"]["condition_sha256"] != pair["treatment"]["condition_sha256"]
    pair_manifest = json.loads((pair_dir / "pair_manifest.json").read_text(encoding="utf-8"))
    assert pair_manifest["environment"] == {"PYTHONIOENCODING": "utf-8"}
    assert {row["argv_index"] for row in pair_manifest["command_files"]} == {0, 1}
    assert "scorer_sha256" not in pair_manifest["model_visible_same_inputs"]
    for path in pair_dir.rglob("*"):
        if not path.is_file():
            continue
        assert "scorer" not in path.name.casefold()
        assert "oracle" not in path.name.casefold()
        raw = path.read_bytes()
        assert b"HELDOUT-CORRECTION-ORACLE" not in raw
        assert b"HELDOUT-DESIRED-ORACLE" not in raw
        assert b"OFFLINE-SCORER-SENTINEL" not in raw

    scored = score_shadow_pair(
        pair_dir=pair_dir,
        plan_dir=chain["plan"],
        source_dir=chain["source"],
        evaluation_dir=chain["evaluation"],
        score_root=tmp_path / "scores",
    )
    score_dir = Path(str(scored["score_directory"]))
    score = verify_shadow_score_bundle(
        score_dir,
        pair_dir=pair_dir,
        plan_dir=chain["plan"],
        source_dir=chain["source"],
        evaluation_dir=chain["evaluation"],
    )
    assert score["baseline_outcome"]["metrics"]["target_failure"]["score"] == 2
    assert score["treatment_outcome"]["metrics"]["target_failure"]["score"] == 0
    promoted = promote_qualified_taste_candidate(
        source_dir=chain["source"],
        evaluation_dir=chain["evaluation"],
        plan_dir=chain["plan"],
        pair_dir=pair_dir,
        score_dir=score_dir,
        qualified_root=tmp_path / "qualified",
    )
    qualified = verify_qualified_bundle(Path(str(promoted["qualified_directory"])))
    assert (
        qualified["chain"]["qualification_receipt_sha256"] == score["qualification_receipt_sha256"]
    )
    assert qualified["live_activation_allowed"] is False


def test_pair_verification_rejects_tampered_actual_output(tmp_path: Path) -> None:
    chain, result, pair_dir = _run(tmp_path)
    stdout = Path(str(result["treatment_directory"])) / "stdout.json"
    value = json.loads(stdout.read_text(encoding="utf-8"))
    value["response_text"] = "overbuilt"
    stdout.write_bytes(canonical_json_bytes(value))

    with pytest.raises(TasteShadowRunnerError) as raised:
        verify_shadow_pair(
            pair_dir,
            plan_dir=chain["plan"],
            source_dir=chain["source"],
            evaluation_dir=chain["evaluation"],
        )
    assert raised.value.reason_code == "BINDING_MISMATCH"


def test_pair_verification_rejects_tampered_condition(tmp_path: Path) -> None:
    chain, result, pair_dir = _run(tmp_path)
    condition = Path(str(result["treatment_directory"])) / "condition.bin"
    condition.write_bytes(b'{"mode":"oracle-injected"}')

    with pytest.raises(TasteShadowRunnerError) as raised:
        verify_shadow_pair(
            pair_dir,
            plan_dir=chain["plan"],
            source_dir=chain["source"],
            evaluation_dir=chain["evaluation"],
        )
    assert raised.value.reason_code == "BINDING_MISMATCH"


def test_consumer_cannot_add_scorer_or_oracle_to_accessible_tree(tmp_path: Path) -> None:
    chain = _chain(tmp_path)
    with pytest.raises(TasteShadowRunnerError) as raised:
        run_fresh_shadow_pair(
            source_dir=chain["source"],
            evaluation_dir=chain["evaluation"],
            plan_dir=chain["plan"],
            output_root=tmp_path / "shadow",
            command=[sys.executable, str(_consumer(tmp_path, mutate_tree=True))],
            body_path=chain["body"],
            config_path=chain["config"],
            timeout_seconds=30,
            environment={"PYTHONIOENCODING": "utf-8"},
        )
    assert raised.value.reason_code == "HOT_MUTATION_DETECTED"


def test_pair_verifier_rejects_late_scorer_path_injection(tmp_path: Path) -> None:
    chain, _, pair_dir = _run(tmp_path)
    (pair_dir / "scorer.json").write_text("OFFLINE-SCORER-SENTINEL", encoding="utf-8")

    with pytest.raises(TasteShadowRunnerError) as raised:
        verify_shadow_pair(
            pair_dir,
            plan_dir=chain["plan"],
            source_dir=chain["source"],
            evaluation_dir=chain["evaluation"],
        )
    assert raised.value.reason_code == "ACCESSIBLE_TREE_INVALID"


def test_launch_rejects_evaluation_path_in_environment(tmp_path: Path) -> None:
    chain = _chain(tmp_path)
    with pytest.raises(TasteShadowRunnerError) as raised:
        run_fresh_shadow_pair(
            source_dir=chain["source"],
            evaluation_dir=chain["evaluation"],
            plan_dir=chain["plan"],
            output_root=tmp_path / "shadow",
            command=[sys.executable, str(_consumer(tmp_path))],
            body_path=chain["body"],
            config_path=chain["config"],
            timeout_seconds=30,
            environment={"TEMP": str(chain["evaluation"])},
        )
    assert raised.value.reason_code == "EVALUATION_PATH_LEAK"


def test_consumer_output_schema_is_v2_without_freshness_self_attestation() -> None:
    assert CONSUMER_OUTPUT_SCHEMA == "s.taste_shadow_consumer_output.v2"
