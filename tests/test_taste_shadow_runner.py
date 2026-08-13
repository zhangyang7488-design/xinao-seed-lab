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
    build_cold_taste_candidate,
    promote_qualified_taste_candidate,
    verify_qualified_bundle,
)
from services.agent_runtime.taste_shadow_runner import (
    CONSUMER_OUTPUT_SCHEMA,
    SCORER_SCHEMA,
    TasteShadowRunnerError,
    run_fresh_shadow_pair,
    verify_shadow_pair,
)

SESSION = "019ff75c-703c-7972-96cd-b0d257b13baa"
TURN_A = "019ff75d-1749-7662-9e80-aafa605718ab"
TURN_B = "019ff75d-1749-7662-9e80-aafa605718ac"


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


def _candidate(tmp_path: Path) -> tuple[Path, Path, Path]:
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
            text="把当前仓库做成足够另一个 AI 判断架构的快照。",
            turn_id=TURN_A,
        ),
        _item(
            ordinal=2,
            item_type="AgentMessage",
            text="先暂停全部工人并建立三套全机证明。",
            turn_id=TURN_A,
        ),
        _item(
            ordinal=3,
            item_type="UserMessage",
            text="不是全机证明，只做当前仓库最小充分快照。",
            turn_id=TURN_B,
        ),
        _item(
            ordinal=4,
            item_type="AgentMessage",
            text="直接制作当前仓库快照并做最小可读回验。",
            turn_id=TURN_B,
        ),
    ]
    rollout.write_bytes(b"".join(canonical_json_bytes(item) + b"\n" for item in records))
    imported = context_fabric.import_codex_rollout(
        rollout,
        carrier_home=home,
        root=fabric,
        allowed_homes={str(home): "s-test"},
    )
    assert imported["appended"] == 4
    with sqlite3.connect(fabric / "context_fabric.sqlite3") as connection:
        ids = [row[0] for row in connection.execute("SELECT event_id FROM events ORDER BY seq")]

    baseline = tmp_path / "baseline.condition"
    treatment = tmp_path / "treatment.condition"
    baseline.write_bytes(canonical_json_bytes({"taste": None}))
    treatment.write_bytes(canonical_json_bytes({"taste": "candidate"}))
    body = tmp_path / "body.bin"
    config = tmp_path / "config.bin"
    body.write_bytes(b"exact-cleanroom-body-v1")
    config.write_bytes(b"exact-cleanroom-config-v1")
    receipt = build_cold_taste_candidate(
        context_root=fabric,
        corpus_root=tmp_path / "taste-corpus",
        prefix_event_ids=ids[:1],
        bad_continuation_event_id=ids[1],
        correction_event_ids=ids[2:3],
        desired_continuation_event_id=ids[3],
        baseline_condition_path=baseline,
        treatment_condition_path=treatment,
        model_identity="synthetic-subprocess-consumer-v1",
        body_identity=f"sha256:{_sha(body.read_bytes())}",
        config_identity=f"sha256:{_sha(config.read_bytes())}",
        carrier_homes={"s-test": home},
    )
    return Path(str(receipt["candidate_directory"])), body, config


def _scorer(tmp_path: Path) -> Path:
    scorer = {
        "schema_version": SCORER_SCHEMA,
        "target_failure": {
            "required_substrings": ["minimal-snapshot"],
            "forbidden_substrings": ["pause-all", "hash-everything"],
        },
        "capabilities": {
            "required_tool_use": {"required_substrings": ["direct-tool"]},
            "bounded_action": {"required_substrings": ["bounded"]},
            "open_representation_revision": {"required_substrings": ["revision"]},
            "world_revision": {"required_substrings": ["world"]},
        },
    }
    path = tmp_path / "scorer.json"
    path.write_bytes(canonical_json_bytes(scorer))
    return path


def _consumer(tmp_path: Path) -> Path:
    path = tmp_path / "consumer.py"
    path.write_text(
        """
import hashlib
import json
import pathlib
import sys
import uuid

request_bytes = sys.stdin.buffer.read()
request = json.loads(request_bytes.decode("utf-8"))
body_bytes = pathlib.Path("body.bin").read_bytes()
config_bytes = pathlib.Path("config.bin").read_bytes()
condition_bytes = pathlib.Path("condition.bin").read_bytes()
condition = json.loads(condition_bytes.decode("utf-8"))
assert request["schema_version"] == "s.taste_shadow_request.v1"
assert body_bytes
assert config_bytes
if condition["taste"] is None:
    response = "pause-all hash-everything direct-tool bounded revision world"
else:
    response = "minimal-snapshot direct-tool bounded revision world"
result = {
    "schema_version": "s.taste_shadow_consumer_output.v1",
    "response_text": response,
    "session_identity": str(uuid.uuid4()),
    "fresh_session": True,
    "cache_used": False,
    "observed_model_identity": request["model_identity"],
    "observed_request_sha256": hashlib.sha256(request_bytes).hexdigest(),
    "observed_body_sha256": hashlib.sha256(body_bytes).hexdigest(),
    "observed_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
    "observed_condition_sha256": hashlib.sha256(condition_bytes).hexdigest(),
}
sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
""".strip(),
        encoding="utf-8",
    )
    return path


def test_real_subprocess_twins_are_recomputable_and_promote_with_exact_evidence(
    tmp_path: Path,
) -> None:
    candidate_dir, body, config = _candidate(tmp_path)
    result = run_fresh_shadow_pair(
        candidate_dir=candidate_dir,
        output_root=tmp_path / "shadow",
        command=[sys.executable, str(_consumer(tmp_path))],
        body_path=body,
        config_path=config,
        scorer_spec_path=_scorer(tmp_path),
        timeout_seconds=30,
    )
    pair = verify_shadow_pair(Path(str(result["pair_directory"])), candidate_dir=candidate_dir)
    assert pair["baseline"]["process_id"] != pair["treatment"]["process_id"]
    assert (
        pair["baseline"]["consumer_session_identity"]
        != pair["treatment"]["consumer_session_identity"]
    )
    assert pair["baseline"]["outcome"]["metrics"]["target_failure"]["score"] == 3
    assert pair["treatment"]["outcome"]["metrics"]["target_failure"]["score"] == 0
    baseline_dir = Path(str(result["baseline_directory"]))
    treatment_dir = Path(str(result["treatment_directory"]))
    for name in ("request.json", "body.bin", "config.bin", "scorer.json"):
        assert (baseline_dir / name).read_bytes() == (treatment_dir / name).read_bytes()
    assert (baseline_dir / "condition.bin").read_bytes() != (
        treatment_dir / "condition.bin"
    ).read_bytes()

    promoted = promote_qualified_taste_candidate(
        candidate_dir=candidate_dir,
        qualified_root=tmp_path / "qualified",
        baseline_outcome_path=Path(str(result["baseline_outcome_path"])),
        treatment_outcome_path=Path(str(result["treatment_outcome_path"])),
        qualification_receipt_path=Path(str(result["qualification_receipt_path"])),
        baseline_shadow_dir=baseline_dir,
        treatment_shadow_dir=treatment_dir,
    )
    qualified = verify_qualified_bundle(Path(str(promoted["qualified_directory"])))
    assert qualified["qualification_receipt_sha256"] == pair["qualification_receipt_sha256"]
    assert qualified["live_activation_allowed"] is False
    assert (
        Path(str(promoted["qualified_directory"])) / "shadow" / "treatment" / "stdout.json"
    ).read_bytes() == (treatment_dir / "stdout.json").read_bytes()


def test_shadow_verification_rejects_output_byte_drift(tmp_path: Path) -> None:
    candidate_dir, body, config = _candidate(tmp_path)
    result = run_fresh_shadow_pair(
        candidate_dir=candidate_dir,
        output_root=tmp_path / "shadow",
        command=[sys.executable, str(_consumer(tmp_path))],
        body_path=body,
        config_path=config,
        scorer_spec_path=_scorer(tmp_path),
        timeout_seconds=30,
    )
    treatment_stdout = Path(str(result["treatment_directory"])) / "stdout.json"
    value = json.loads(treatment_stdout.read_text(encoding="utf-8"))
    value["response_text"] = "pause-all"
    treatment_stdout.write_bytes(canonical_json_bytes(value))
    with pytest.raises(TasteShadowRunnerError) as raised:
        verify_shadow_pair(Path(str(result["pair_directory"])), candidate_dir=candidate_dir)
    assert raised.value.reason_code == "BINDING_MISMATCH"


def test_consumer_must_report_a_fresh_uncached_session(tmp_path: Path) -> None:
    candidate_dir, body, config = _candidate(tmp_path)
    consumer = _consumer(tmp_path)
    text = consumer.read_text(encoding="utf-8").replace(
        '"fresh_session": True', '"fresh_session": False'
    )
    consumer.write_text(text, encoding="utf-8")
    with pytest.raises(TasteShadowRunnerError) as raised:
        run_fresh_shadow_pair(
            candidate_dir=candidate_dir,
            output_root=tmp_path / "shadow",
            command=[sys.executable, str(consumer)],
            body_path=body,
            config_path=config,
            scorer_spec_path=_scorer(tmp_path),
            timeout_seconds=30,
        )
    assert raised.value.reason_code == "RUN_NOT_FRESH"


def test_consumer_output_schema_constant_matches_subprocess_contract() -> None:
    assert CONSUMER_OUTPUT_SCHEMA == "s.taste_shadow_consumer_output.v1"
