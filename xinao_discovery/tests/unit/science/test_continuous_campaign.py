from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from xinao.canonical import canonical_sha256
from xinao.science.continuous_campaign import (
    CampaignCadence,
    build_continuous_campaign_package,
    select_next_legal_target,
    split_fixed_cutoff_stream,
    verify_continuous_campaign_package,
)
from xinao.science.day1_portfolio import (
    SpecialNumberObservation,
    build_day1_policy_compilation,
)
from xinao.science.multipolicy_episode import run_live_freeze


def observations(count: int = 190) -> tuple[SpecialNumberObservation, ...]:
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


def co_collapsed_observations(count: int = 196) -> tuple[SpecialNumberObservation, ...]:
    """History where baseline and substantive policies are distinct but act alike."""

    start = datetime(2026, 1, 1, 13, 32, 32, tzinfo=UTC)
    return tuple(
        SpecialNumberObservation(
            expect=f"2026{index + 1:03d}",
            open_time=start + timedelta(days=index),
            special_number=(index * index * 14 + index * 16 + index // 7 + 13) % 49 + 1,
            source_row_hash=canonical_sha256(["co-collapsed-row", index]),
        )
        for index in range(count)
    )


def test_fixed_policy_identity_survives_the_full_post_cutoff_window() -> None:
    history = observations(182)
    cutoff = history[-1].open_time + timedelta(seconds=1)
    first = build_day1_policy_compilation(
        history,
        target_ref="macaujc2/expect/2026183",
        knowledge_cutoff=cutoff,
        horizon_draws=1,
    )
    last = build_day1_policy_compilation(
        history,
        target_ref="macaujc2/expect/2026207",
        knowledge_cutoff=cutoff,
        horizon_draws=25,
    )

    assert tuple(item.content_hash for item in first.policies) == tuple(
        item.content_hash for item in last.policies
    )
    assert all(
        item.decision_signature.update_policy == "FROZEN_INCUMBENT_NO_POST_CUTOFF_OUTCOME"
        for item in first.policies
    )
    assert all(item.knowledge_cutoff == cutoff for item in last.policies)


def test_stream_split_preserves_formal_prefix_and_returns_only_validation() -> None:
    source = observations(187)
    fixed, validation = split_fixed_cutoff_stream(source[:182], source)

    assert fixed == source[:182]
    assert tuple(item.expect for item in validation) == tuple(
        f"2026{index:03d}" for index in range(183, 188)
    )

    drifted = list(source)
    drifted[181] = drifted[181].model_copy(update={"special_number": 49})
    with pytest.raises(ValueError, match="formal prefix"):
        split_fixed_cutoff_stream(source[:182], tuple(drifted))


def test_next_target_skips_a_missed_freeze_deadline_without_waiting_for_its_outcome() -> None:
    latest = SpecialNumberObservation(
        expect="2026207",
        open_time=datetime(2026, 7, 26, 13, 32, 32, tzinfo=UTC),
        special_number=17,
        source_row_hash="a" * 64,
    )
    now = datetime(2026, 7, 27, 13, 21, 0, tzinfo=UTC)

    target = select_next_legal_target(latest, now=now)

    assert target.target_ref == "macaujc2/expect/2026209"
    assert target.skipped_missed_deadline_refs == ("macaujc2/expect/2026208",)
    assert target.freeze_deadline > now


def test_continuous_campaign_replays_known_window_then_freezes_one_future_target(
    tmp_path,
) -> None:
    source = observations(187)
    fixed = source[:182]
    pinned_at = source[-1].open_time + timedelta(hours=12)
    root = tmp_path / "campaign"

    result = build_continuous_campaign_package(
        output_dir=root,
        campaign_id="campaign.fixed-cutoff.v1",
        policy_observations=fixed,
        observed_source=source,
        policy_dataset_ref="formal-dataset.fixture",
        policy_dataset_sha256="a" * 64,
        validation_source_ref="validation-source.fixture",
        validation_source_sha256="b" * 64,
        validation_source_captured_at=pinned_at,
        active_parent_ref="active-parent.current",
        active_parent_sha256="c" * 64,
        source_contract_ref="macaujc-source-authority-contract.v1",
        source_contract_sha256="d" * 64,
        pinned_at=pinned_at,
    )
    readback = verify_continuous_campaign_package(
        root,
        expected_manifest_sha256=result["manifest_sha256"],
    )

    assert result["state"] == "HISTORICAL_REPLAY_SETTLED_AND_PROSPECTIVE_FROZEN"
    assert readback["ok"] is True
    assert readback["cadence"] == CampaignCadence.FROZEN_INCUMBENT
    assert readback["candidate_information_latest_expect"] == "2026182"
    assert readback["historical_settled_target_count"] == 5
    assert readback["historical_settled_ticket_count"] == 20
    assert readback["prospective_pending_target_count"] == 1
    assert readback["post_cutoff_candidate_observation_count"] == 0
    assert readback["historical_claim_ceiling"] == "E2"
    assert readback["evaluation_conclusion"] == "NO_PREDICTIVE_ADVANTAGE_ESTABLISHED"
    assert readback["next_question_set_ref"].startswith("next-question-set/")
    assert readback["complete_weekly_period_count"] == 0
    assert readback["partial_weekly_period_count"] == 2
    assert readback["waiting_scope"] == "TARGET_ONLY"
    assert readback["parent_idle"] is False
    assert readback["real_money_authorized"] is False
    assert readback["parent_complete"] is False


def test_campaign_audits_cross_role_co_collapse_and_opens_a_new_protocol_question(
    tmp_path,
) -> None:
    source = co_collapsed_observations()
    fixed = source[:182]
    pinned_at = source[-1].open_time + timedelta(hours=12)
    root = tmp_path / "co-collapsed-campaign"

    result = build_continuous_campaign_package(
        output_dir=root,
        campaign_id="campaign.co-collapsed.v1",
        policy_observations=fixed,
        observed_source=source,
        policy_dataset_ref="formal-dataset.fixture",
        policy_dataset_sha256="a" * 64,
        validation_source_ref="validation-source.fixture",
        validation_source_sha256="b" * 64,
        validation_source_captured_at=pinned_at,
        active_parent_ref="active-parent.current",
        active_parent_sha256="c" * 64,
        source_contract_ref="macaujc-source-authority-contract.v1",
        source_contract_sha256="d" * 64,
        pinned_at=pinned_at,
    )
    readback = verify_continuous_campaign_package(
        root,
        expected_manifest_sha256=result["manifest_sha256"],
    )
    evaluation = json.loads(
        (root / "continuous_campaign_evaluation.v1.json").read_text(encoding="utf-8")
    )

    assert readback["portfolio_health"] == "DEGRADED_HOMOGENEITY"
    assert readback["complete_weekly_period_count"] == 1
    assert readback["partial_weekly_period_count"] == 2
    assert evaluation["historical_claim_ceiling"] == "E2"
    assert evaluation["prospective_evidence_inherited"] is False
    assert evaluation["next_question_set"]["requires_new_protocol_version"] is True
    assert evaluation["next_question_set"]["parent_idle"] is False
    assert any(
        set(cluster["policy_refs"])
        == {
            "policy.day1.baseline-rolling-marginal-w90.v1",
            "policy.day1.substantive-multiscale-overlap-7-14-28.v1",
        }
        for cluster in evaluation["behavior_equivalence_clusters"]
    )


def test_campaign_rejects_an_empty_validation_window(tmp_path) -> None:
    fixed = observations(182)
    with pytest.raises(ValueError, match="post-cutoff validation"):
        build_continuous_campaign_package(
            output_dir=tmp_path / "campaign",
            campaign_id="campaign.empty.v1",
            policy_observations=fixed,
            observed_source=fixed,
            policy_dataset_ref="formal-dataset.fixture",
            policy_dataset_sha256="a" * 64,
            validation_source_ref="validation-source.fixture",
            validation_source_sha256="b" * 64,
            validation_source_captured_at=fixed[-1].open_time + timedelta(hours=12),
            active_parent_ref="active-parent.current",
            active_parent_sha256="c" * 64,
            source_contract_ref="macaujc-source-authority-contract.v1",
            source_contract_sha256="d" * 64,
            pinned_at=fixed[-1].open_time + timedelta(hours=12),
        )


def test_retired_single_target_live_entry_fails_before_creating_output(tmp_path) -> None:
    output = tmp_path / "retired"
    with pytest.raises(ValueError, match="fixed-cutoff continuous campaign"):
        run_live_freeze(
            output_dir=output,
            episode_id="retired.single-target.v1",
            target_expect="2026209",
            target_open_time=datetime(2026, 7, 28, 13, 32, 32, tzinfo=UTC),
            freeze_deadline=datetime(2026, 7, 28, 12, 32, 32, tzinfo=UTC),
            active_parent_path=tmp_path / "parent.txt",
            active_parent_sha256="a" * 64,
            source_contract_path=tmp_path / "contract.txt",
            source_contract_sha256="b" * 64,
        )
    assert not output.exists()
