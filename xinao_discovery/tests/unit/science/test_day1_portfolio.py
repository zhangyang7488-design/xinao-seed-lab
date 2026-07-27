from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from xinao.canonical import canonical_sha256
from xinao.decision import DecisionKind
from xinao.science.day1_portfolio import (
    DAY1_POLICY_REFS,
    Day1PolicyCompilation,
    MultipolicyProtocolPin,
    PolicyHashBinding,
    RuntimeSourceBinding,
    SpecialNumberObservation,
    build_day1_gates,
    build_day1_policy_compilation,
    multiscale_overlap_prediction,
    null_target_prediction,
    parse_macaujc_history_response,
    rolling_marginal_prediction,
)
from xinao.science.portfolio import PolicyRole


def observations(count: int = 220) -> tuple[SpecialNumberObservation, ...]:
    start = datetime(2026, 1, 1, 13, 32, 32, tzinfo=UTC)
    return tuple(
        SpecialNumberObservation(
            expect=f"2026{index + 1:03d}",
            open_time=start + timedelta(days=index),
            special_number=(index * index * 3 + index * 17 + (index // 7) * 5) % 49 + 1,
            source_row_hash=canonical_sha256(["row", index]),
        )
        for index in range(count)
    )


def compilation() -> Day1PolicyCompilation:
    history = observations()
    return build_day1_policy_compilation(
        history,
        target_ref="macaujc2/expect/2026221",
        knowledge_cutoff=history[-1].open_time + timedelta(minutes=1),
        horizon_draws=1,
    )


def pin(compiled: Day1PolicyCompilation) -> MultipolicyProtocolPin:
    cutoff = compiled.knowledge_cutoff
    return MultipolicyProtocolPin(
        protocol_pin_ref="protocol.day1.2026221.v1",
        episode_id="episode.day1.2026221.v1",
        evidence_class="PROSPECTIVE_EXPERIMENTAL",
        active_parent_ref="active-parent.current",
        active_parent_sha256="a" * 64,
        source_contract_ref="macaujc-source-authority-contract.v1",
        source_contract_sha256="b" * 64,
        source_snapshot_ref="source-response.2026.json",
        source_snapshot_sha256="c" * 64,
        source_captured_at=cutoff,
        trial_ledger_anchor_ref="science-trial-ledger.v1.json",
        trial_ledger_anchor_sha256="d" * 64,
        trial_ledger_prefix_entry_count=4,
        trial_ledger_prefix_entries_sha256="e" * 64,
        research_question="Can any bounded Day-1 policy outperform controls prospectively?",
        target_ref=compiled.target_ref,
        target_open_time=cutoff + timedelta(hours=3),
        knowledge_cutoff=cutoff,
        frozen_at=cutoff + timedelta(minutes=1),
        freeze_deadline=cutoff + timedelta(hours=2),
        required_roles=tuple(PolicyRole),
        policy_bindings=tuple(
            PolicyHashBinding(
                policy_ref=item.policy_ref,
                content_hash=str(item.content_hash),
                role=item.role,
            )
            for item in compiled.policies
        ),
        runtime_source_bindings=tuple(
            RuntimeSourceBinding(ref=f"src/runtime-{index}.py", sha256=str(index) * 64)
            for index in range(1, 8)
        ),
        residual_axes=("wave-overlap-live-score",),
        forbidden_claims=("predictive advantage", "real-money recommendation"),
        next_move="Settle every frozen ticket after the verified target outcome arrives.",
    ).with_content_hash()


def test_day1_compilation_is_non_vacuous_and_deterministic() -> None:
    first = compilation()
    second = compilation()

    assert first == second
    assert first.content_hash is not None
    assert tuple(item.policy_ref for item in first.policies) == DAY1_POLICY_REFS
    assert {item.role for item in first.policies} == set(PolicyRole)
    assert len({item.content_hash for item in first.policies}) == 4
    assert len({item.decision_signature.probe_trace_hash for item in first.policies}) == 4
    assert next(
        item for item in first.decisions if item.policy_ref == "policy.day1.no-action.v1"
    ).requested_decision_kind == DecisionKind.NO_ACTION


def test_day1_gates_cover_exact_policy_bindings() -> None:
    compiled = compilation()
    protocol = pin(compiled)
    gates = build_day1_gates(
        pin=protocol,
        compilation=compiled,
        information_set_ref="information-set.day1.v1",
        information_set_hash=compiled.history_identity_hash,
    )

    assert tuple(sorted(gates)) == DAY1_POLICY_REFS
    assert all(item.protocol_pin_sha256 == protocol.content_hash for item in gates.values())
    assert gates["policy.day1.no-action.v1"].requested_decision_kind == DecisionKind.NO_ACTION
    assert all(item.target_ref == compiled.target_ref for item in gates.values())


def test_compilation_and_protocol_pin_accept_owner_adopted_external_substantive() -> None:
    compiled = compilation()
    substantive = next(item for item in compiled.policies if item.role == PolicyRole.SUBSTANTIVE)
    external = substantive.model_copy(
        update={
            "policy_ref": "policy.external.owner-adopted-ai.v1",
            "semantic_config": {
                **substantive.semantic_config,
                "origin": "owner-adopted-external-candidate",
            },
            "content_hash": None,
        }
    ).with_content_hash()
    policies = tuple(
        sorted(
            (
                external if item.role == PolicyRole.SUBSTANTIVE else item
                for item in compiled.policies
            ),
            key=lambda item: item.policy_ref,
        )
    )
    decisions = tuple(
        sorted(
            (
                item.model_copy(update={"policy_ref": external.policy_ref})
                if item.policy_ref == substantive.policy_ref
                else item
                for item in compiled.decisions
            ),
            key=lambda item: item.policy_ref,
        )
    )
    external_compilation = Day1PolicyCompilation(
        **{
            **compiled.model_dump(mode="python", exclude={"policies", "decisions", "content_hash"}),
            "policies": policies,
            "decisions": decisions,
        }
    ).with_content_hash()
    protocol = pin(external_compilation)
    gates = build_day1_gates(
        pin=protocol,
        compilation=external_compilation,
        information_set_ref="information-set.external.v1",
        information_set_hash=external_compilation.history_identity_hash,
    )

    assert external.policy_ref in gates
    assert tuple(sorted(gates)) == tuple(item.policy_ref for item in policies)
    assert protocol.policy_bindings[-1].policy_ref == external.policy_ref


def test_compilation_rejects_missing_required_role_after_generalization() -> None:
    compiled = compilation()
    policies = list(compiled.policies)
    substantive_index = next(
        index for index, item in enumerate(policies) if item.role == PolicyRole.SUBSTANTIVE
    )
    policies[substantive_index] = policies[substantive_index].model_copy(
        update={"role": PolicyRole.BASELINE, "content_hash": None}
    ).with_content_hash()

    with pytest.raises(ValueError, match="exact required roles"):
        Day1PolicyCompilation(
            **{
                **compiled.model_dump(
                    mode="python", exclude={"policies", "decisions", "content_hash"}
                ),
                "policies": tuple(policies),
                "decisions": compiled.decisions,
            }
        )


def test_frozen_predictors_have_distinct_mechanisms_and_stable_outputs() -> None:
    values = tuple(item.special_number for item in observations())

    assert null_target_prediction("macaujc2/expect/2026221") == null_target_prediction(
        "macaujc2/expect/2026221"
    )
    assert 1 <= rolling_marginal_prediction(values) <= 49
    assert 1 <= multiscale_overlap_prediction(values) <= 49
    with pytest.raises(ValueError, match="frozen Day-1"):
        multiscale_overlap_prediction(values, windows=(7, 14, 21))


def test_macaujc_history_parser_respects_cutoff_and_envelope() -> None:
    start = datetime(2026, 1, 1, 21, 32, 32)
    rows = []
    for index in range(181):
        numbers = [((index + offset) % 49) + 1 for offset in range(7)]
        rows.append(
            {
                "expect": f"2026{index + 1:03d}",
                "openTime": (start + timedelta(days=index)).strftime("%Y-%m-%d %H:%M:%S"),
                "openCode": ",".join(f"{number:02d}" for number in numbers),
            }
        )
    raw = json.dumps({"result": True, "code": 200, "data": rows}).encode()
    cutoff = datetime(2026, 6, 30, 22, 32, 32, tzinfo=observations()[0].open_time.tzinfo)
    parsed = parse_macaujc_history_response(raw, knowledge_cutoff=cutoff)

    assert len(parsed) == 181
    assert parsed[0].expect == "2026001"
    assert parsed[-1].expect == "2026181"
    with pytest.raises(ValueError, match="envelope"):
        parse_macaujc_history_response(b'{"result":false}', knowledge_cutoff=cutoff)


def test_protocol_pin_rejects_policy_binding_drift() -> None:
    compiled = compilation()
    valid = pin(compiled)
    drifted = list(valid.policy_bindings)
    drifted[0] = drifted[0].model_copy(update={"content_hash": "f" * 64})
    drifted_pin = valid.model_copy(
        update={"policy_bindings": tuple(drifted), "content_hash": None}
    ).with_content_hash()

    with pytest.raises(ValueError, match="policy bindings differ"):
        build_day1_gates(
            pin=drifted_pin,
            compilation=compiled,
            information_set_ref="information-set.day1.v1",
            information_set_hash=compiled.history_identity_hash,
        )
