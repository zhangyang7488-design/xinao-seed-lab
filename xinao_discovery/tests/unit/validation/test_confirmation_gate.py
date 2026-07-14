from __future__ import annotations

import pytest

from xinao.validation import (
    CandidateVersion,
    bind_confirmation,
    require_new_candidate_id,
    validate_candidate,
)
from xinao.world.builder import load_draws


def candidate(candidate_ref: str = "candidate.constant-01-panel-b.v0", number: int = 1):
    return CandidateVersion(
        candidate_ref=candidate_ref,
        semantic_config={"panel": "B", "selected_number": number, "stake": "1.0000"},
    )


def test_no_action_cannot_consume_confirmation_budget() -> None:
    report = validate_candidate(load_draws())
    with pytest.raises(ValueError, match="cannot consume"):
        bind_confirmation(candidate(), report)


def test_semantic_change_requires_new_candidate_identity_after_confirmation() -> None:
    no_action = validate_candidate(load_draws())
    action = no_action.model_copy(update={"verdict": "ACTION", "no_action_reasons": ()})
    action = action.model_copy(update={"output_hash": None}).with_hash()
    binding = bind_confirmation(candidate(), action)
    with pytest.raises(ValueError, match="new CandidateVersion ID"):
        require_new_candidate_id(binding, candidate(number=2))
    assert (
        require_new_candidate_id(
            binding, candidate(candidate_ref="candidate.constant-02-panel-b.v1", number=2)
        ).candidate_ref
        == "candidate.constant-02-panel-b.v1"
    )
