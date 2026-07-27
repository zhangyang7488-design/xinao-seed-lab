from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from xinao.canonical import canonical_sha256
from xinao.decision import DecisionGateInput, DecisionKind
from xinao.science.portfolio import (
    ActiveSet,
    DecisionSignature,
    PolicyCandidateVersion,
    PolicyRole,
    admit_active_set,
    admit_eligible_set,
    freeze_all,
    settle_all,
)
from xinao.settlement import OutcomeObservation

OPEN = datetime(2026, 7, 28, 13, 32, 32, tzinfo=UTC)
FROZEN = OPEN - timedelta(hours=2)
DEADLINE = OPEN - timedelta(hours=1)
PROTOCOL_HASH = "a" * 64


def policy(role: PolicyRole, index: int) -> PolicyCandidateVersion:
    action_count = 0 if role == PolicyRole.NO_ACTION else 32
    return PolicyCandidateVersion(
        policy_ref=f"policy.{role.value.lower()}.v1",
        family_id=f"family.{role.value.lower()}.v1",
        role=role,
        knowledge_cutoff=FROZEN - timedelta(minutes=1),
        decision_signature=DecisionSignature(
            mechanism=f"mechanism-{index}",
            feature_visibility=(f"feature-{index}",),
            time_scale=f"scale-{index}",
            update_policy="frozen",
            abstention_rule="always" if role == PolicyRole.NO_ACTION else "never",
            action_support="none" if role == PolicyRole.NO_ACTION else "special-number-1-49",
            decision_map_ref=f"decision-map.{index}.v1",
            probe_target_count=32,
            probe_action_count=action_count,
            probe_trace_hash=canonical_sha256([role.value, index, action_count]),
        ),
        semantic_config={"version": 1, "role": role.value, "index": index},
    ).with_content_hash()


def active_set():
    policies = tuple(
        policy(role, index)
        for index, role in enumerate(
            (
                PolicyRole.NO_ACTION,
                PolicyRole.NEG_CONTROL,
                PolicyRole.BASELINE,
                PolicyRole.SUBSTANTIVE,
            )
        )
    )
    return admit_active_set(
        active_set_ref="active-set.day1.v1",
        protocol_pin_ref="protocol.day1.v1",
        protocol_pin_sha256=PROTOCOL_HASH,
        admitted_at=FROZEN - timedelta(minutes=1),
        policies=policies,
        residual_axes=("wave-overlap-out-of-sample",),
    )


def eligible_set(active):
    return admit_eligible_set(
        active_set=active,
        eligible_set_ref="eligible-set.draw-1.v1",
        target_ref="draw.synthetic.1",
        target_open_time=OPEN,
        created_at=FROZEN,
    )


def gates(active, eligible):
    values: dict[str, DecisionGateInput] = {}
    for index, item in enumerate(active.policies, start=1):
        no_action = item.role == PolicyRole.NO_ACTION
        values[item.policy_ref] = DecisionGateInput(
            candidate_ref=item.policy_ref,
            requested_decision_kind=(
                DecisionKind.NO_ACTION
                if no_action
                else DecisionKind.FROZEN_EXPERIMENTAL_SHADOW
            ),
            candidate_qualification=None if no_action else "SHADOW_EXPERIMENTAL",
            adjudicated_decision_kinds=("FROZEN_EXPERIMENTAL_SHADOW", "NO_ACTION"),
            court_verdict_bundle_ref=f"courts.{item.policy_ref}",
            court_verdict_bundle_content_hash=canonical_sha256(["courts", item.policy_ref]),
            protocol_pin_ref=active.protocol_pin_ref,
            protocol_pin_sha256=active.protocol_pin_sha256,
            information_set_ref="information-set.synthetic.v1",
            information_set_hash=canonical_sha256(["history", 1]),
            validation_report_ref=f"validation.{item.policy_ref}",
            validation_output_hash=canonical_sha256(["validation", item.policy_ref]),
            validation_verdict="ACTION",
            baseline_ref="baseline-odds-water.v1",
            baseline_active=True,
            rule_ref="special-number-rule.v1",
            rule_active=True,
            odds_version_ref="baseline-odds-water.v1",
            cost_version_ref="cost.zero-shadow.v1",
            friction_version_ref="friction.zero-shadow.v1",
            exposure_policy_ref="shadow-exposure.unit.v1",
            target_ref=eligible.target_ref,
            target_window_start=eligible.target_open_time,
            target_window_end=eligible.target_open_time,
            target_open_time=eligible.target_open_time,
            freeze_deadline=DEADLINE,
            knowledge_cutoff=FROZEN - timedelta(minutes=1),
            compiled_at=FROZEN,
            panel="B",
            selected_number=index,
            stake="1.0000",
            lower_expected_net="0.0000",
            estimated_cost="0.0000",
            risk_limit="1.0000",
        )
    return values


def frozen_set():
    active = active_set()
    eligible = eligible_set(active)
    return freeze_all(
        active_set=active,
        eligible_set=eligible,
        gates=gates(active, eligible),
        freeze_set_ref="freeze-set.synthetic.1.v1",
        frozen_at=FROZEN,
    )


def outcome(*, target_ref: str = "draw.synthetic.1") -> OutcomeObservation:
    return OutcomeObservation(
        outcome_ref="outcome.synthetic.1",
        source_ref="synthetic-recovery-fixture.v1",
        target_ref=target_ref,
        actual_special_number=3,
        observed_at=OPEN + timedelta(minutes=1),
        verified=True,
    ).with_hash()


def test_non_vacuous_freeze_all_and_settle_all_close_exactly_once() -> None:
    frozen = frozen_set()
    result = settle_all(
        freeze_set=frozen,
        outcome=outcome(),
        settlement_set_ref="settlement-set.synthetic.1.v1",
        portfolio_ref="shadow-portfolio.day1.v1",
        occurred_at=OPEN + timedelta(minutes=2),
    )

    assert frozen.freeze_coverage == "1.0000"
    assert frozen.eligible_frozen_count == 4
    assert {ticket.role for ticket in frozen.tickets} == set(PolicyRole)
    assert len(result.action_bundles) == 3
    assert result.settlement_set.closed is True
    assert result.settlement_set.eligible_frozen_count == 4
    assert result.settlement_set.settled_exactly_once_count == 4
    assert result.settlement_set.void_with_reason_count == 0
    assert result.settlement_set.missing_or_duplicate_count == 0
    no_action = next(
        row for row in result.settlement_set.score_rows if row.role == PolicyRole.NO_ACTION
    )
    assert no_action.disposition == "NO_ACTION_SETTLED"
    assert no_action.stake == "0.0000"
    assert no_action.settlement_ref is None


def test_settle_all_is_deterministic_for_the_same_frozen_identity() -> None:
    frozen = frozen_set()
    kwargs = {
        "freeze_set": frozen,
        "outcome": outcome(),
        "settlement_set_ref": "settlement-set.synthetic.1.v1",
        "portfolio_ref": "shadow-portfolio.day1.v1",
        "occurred_at": OPEN + timedelta(minutes=2),
    }

    assert settle_all(**kwargs) == settle_all(**kwargs)


def test_active_set_rejects_renamed_policy_with_same_probe_trace() -> None:
    active = active_set()
    policies = list(active.policies)
    baseline_index = next(
        index for index, item in enumerate(policies) if item.role == PolicyRole.BASELINE
    )
    substantive = next(item for item in policies if item.role == PolicyRole.SUBSTANTIVE)
    baseline = policies[baseline_index]
    policies[baseline_index] = baseline.model_copy(
        update={
            "decision_signature": baseline.decision_signature.model_copy(
                update={"probe_trace_hash": substantive.decision_signature.probe_trace_hash}
            ),
            "content_hash": None,
        }
    ).with_content_hash()

    with pytest.raises(ValidationError, match="probe traces"):
        admit_active_set(
            active_set_ref="active-set.invalid.v1",
            protocol_pin_ref="protocol.day1.v1",
            protocol_pin_sha256=PROTOCOL_HASH,
            admitted_at=FROZEN,
            policies=tuple(policies),
            residual_axes=("wave-overlap-out-of-sample",),
        )


def test_active_set_rejects_duplicate_role_coverage_rows() -> None:
    active = active_set()
    payload = active.model_dump(mode="python")
    payload["role_coverage"] = (*active.role_coverage, active.role_coverage[-1])
    payload["content_hash"] = None

    with pytest.raises(ValidationError, match="duplicate roles"):
        ActiveSet.model_validate(payload)


def test_eligible_set_cannot_shrink_away_substantive_role() -> None:
    active = active_set()
    refs = tuple(
        item.policy_ref for item in active.policies if item.role != PolicyRole.SUBSTANTIVE
    )
    with pytest.raises(ValueError, match="role coverage"):
        admit_eligible_set(
            active_set=active,
            eligible_set_ref="eligible-set.invalid.v1",
            target_ref="draw.synthetic.1",
            target_open_time=OPEN,
            created_at=FROZEN,
            eligible_policy_refs=refs,
        )


def test_freeze_all_rejects_missing_or_extra_ticket_inputs() -> None:
    active = active_set()
    eligible = eligible_set(active)
    incomplete = gates(active, eligible)
    incomplete.pop(next(iter(incomplete)))
    with pytest.raises(ValueError, match="gate coverage"):
        freeze_all(
            active_set=active,
            eligible_set=eligible,
            gates=incomplete,
            freeze_set_ref="freeze-set.invalid.v1",
            frozen_at=FROZEN,
        )


def test_settle_all_rejects_target_mismatch_and_unknown_void() -> None:
    frozen = frozen_set()
    with pytest.raises(ValueError, match="target differs"):
        settle_all(
            freeze_set=frozen,
            outcome=outcome(target_ref="draw.synthetic.other"),
            settlement_set_ref="settlement-set.invalid.v1",
            portfolio_ref="shadow-portfolio.day1.v1",
            occurred_at=OPEN + timedelta(minutes=2),
        )
    with pytest.raises(ValueError, match="unknown ticket"):
        settle_all(
            freeze_set=frozen,
            outcome=outcome(),
            settlement_set_ref="settlement-set.invalid.v1",
            portfolio_ref="shadow-portfolio.day1.v1",
            occurred_at=OPEN + timedelta(minutes=2),
            void_reason_hashes={"ticket.unknown": "f" * 64},
        )


def test_explicit_void_is_counted_without_silent_omission() -> None:
    frozen = frozen_set()
    ticket = next(
        item for item in frozen.tickets if item.role == PolicyRole.NEG_CONTROL
    )
    result = settle_all(
        freeze_set=frozen,
        outcome=outcome(),
        settlement_set_ref="settlement-set.void.v1",
        portfolio_ref="shadow-portfolio.day1.v1",
        occurred_at=OPEN + timedelta(minutes=2),
        void_reason_hashes={ticket.frozen_decision.decision_ref: canonical_sha256("fixture-void")},
    )

    assert result.settlement_set.eligible_frozen_count == 4
    assert result.settlement_set.settled_exactly_once_count == 3
    assert result.settlement_set.void_with_reason_count == 1
    assert result.settlement_set.missing_or_duplicate_count == 0
