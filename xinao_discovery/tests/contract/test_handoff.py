from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xinao.canonical import canonical_sha256
from xinao.contracts import HandoffMessage

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "handoff" / "valid_task.json"

PAYLOAD_GOLDENS = {
    "Intent": {"summary": "start", "desired_outcome": "verified result"},
    "Question": {"question": "continue?", "blocking": False},
    "Decision": {"decision": "continue", "rationale": "frontier ready"},
    "Task": {"objective": "verify", "acceptance": ["tests pass"]},
    "Claim": {"statement": "hash matches", "confidence": "high"},
    "Evidence": {"claim_refs": ["claim:1"], "verdict": "supports"},
    "Artifact": {"name": "report", "media_type": "application/json", "content_hash": "a" * 64},
    "Review": {"subject_ref": "artifact:1", "verdict": "approved", "comments": []},
    "Blocker": {"reason": "missing input", "required_input": "contract"},
    "Stop": {"reason": "user stop", "cancel_scope": ["workflow"]},
    "Resume": {"checkpoint_ref": "checkpoint:1", "resume_from": "activity:2"},
    "ResearchQuestion": {
        "question": "what evidence?",
        "expected_information_gain": "high",
        "budget": "one lane",
    },
    "EvidenceBundle": {"claims": ["claim:1"], "contradictions": [], "limitations": []},
    "CandidateProposal": {"hypothesis": "h1", "parent_refs": [], "risk": "bounded"},
    "Critique": {"target_ref": "candidate:1", "findings": ["missing negative"]},
    "VerificationResult": {"criteria": ["c1"], "verdict": "verified"},
}


def valid_payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_valid_task_handoff_roundtrips_and_hashes_deterministically() -> None:
    message = HandoffMessage.model_validate(valid_payload())
    assert message.payload.kind == "Task"
    first = canonical_sha256(message)
    second = canonical_sha256(HandoffMessage.model_validate_json(message.model_dump_json()))
    assert first == second


def test_handoff_json_schema_contains_all_sixteen_discriminated_payloads() -> None:
    schema = HandoffMessage.model_json_schema()
    mapping = schema["properties"]["payload"]["discriminator"]["mapping"]
    assert set(mapping) == {
        "Intent",
        "Question",
        "Decision",
        "Task",
        "Claim",
        "Evidence",
        "Artifact",
        "Review",
        "Blocker",
        "Stop",
        "Resume",
        "ResearchQuestion",
        "EvidenceBundle",
        "CandidateProposal",
        "Critique",
        "VerificationResult",
    }


@pytest.mark.parametrize("kind", PAYLOAD_GOLDENS)
def test_all_sixteen_payload_kinds_have_positive_roundtrip_goldens(kind: str) -> None:
    payload = valid_payload()
    payload["payload"] = {"kind": kind, **PAYLOAD_GOLDENS[kind]}
    payload["idempotency_key"] = f"handoff-golden-{kind}"
    message = HandoffMessage.model_validate(payload)
    assert message.payload.kind == kind
    assert HandoffMessage.model_validate_json(message.model_dump_json()) == message


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.update(message_id="e9ab9d1c-6c31-4e11-a142-928c625d1b18"), "pattern"),
        (lambda value: value.update(run_id=None), "supplied together"),
        (lambda value: value.update(authority_scope=[]), "at least 1"),
        (lambda value: value.update(expiry="2026-07-13T23:00:00.000Z"), "later"),
        (lambda value: value["payload"].update(kind="Unknown"), "union_tag_invalid"),
    ],
)
def test_invalid_handoff_fails_closed(mutation, match: str) -> None:
    payload = copy.deepcopy(valid_payload())
    mutation(payload)
    with pytest.raises(ValidationError, match=match):
        HandoffMessage.model_validate(payload)


def test_resume_requires_checkpoint_and_workflow_pair_is_symmetric() -> None:
    payload = valid_payload()
    payload["payload"] = {"kind": "Resume", "resume_from": "activity:2"}
    with pytest.raises(ValidationError):
        HandoffMessage.model_validate(payload)
    payload = valid_payload()
    payload["workflow_id"] = None
    with pytest.raises(ValidationError, match="supplied together"):
        HandoffMessage.model_validate(payload)
