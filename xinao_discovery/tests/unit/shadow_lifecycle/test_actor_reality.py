"""First-principles tests for the complete-actor candidate bridge."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from xinao.canonical import canonical_sha256
from xinao.science.episode_export_pool_adapter import EXPORT_SCHEMA
from xinao.science.prospective_source_thin import (
    PACKET_MARKER,
    SCHEMA_PACKET,
    build_source_authority_binding,
    packet_content_hash,
    write_packet_exclusive,
)
from xinao.science.research_episode_candidate_manifest import (
    CANDIDATE_MANIFEST_MARKER,
    CANDIDATE_MANIFEST_SCHEMA,
)
from xinao.science.research_feedback_pack import (
    PACK_MARKER,
    PACK_SCHEMA_VERSION,
    research_feedback_pack_cas_path,
)
from xinao.settlement import OutcomeObservation
from xinao.shadow_lifecycle.actor_reality import (
    ACTOR_BEHAVIOR_REF_PREFIX,
    ACTOR_BEHAVIOR_SOURCE_REF_PREFIX,
    RESEARCH_EPISODE_MATERIAL_PACKET_NOTICE,
    ActorAuthoredBehaviorIntent,
    ActorDecisionKind,
    ActorObjectiveTermsPacket,
    ActorRealityContract,
    BalanceSourceKind,
    CompleteActorBehavior,
    actor_objective_terms_packet_bytes,
    actor_portfolio_reality_packet_bytes,
    build_actor_portfolio_reality_packet,
    build_complete_actor_behavior,
    build_shadow_freeze_input_candidate,
)
from xinao.shadow_lifecycle.consumer import (
    feedback_portfolio_period,
    init_portfolio,
)
from xinao.shadow_lifecycle.lifecycle import (
    AccountingBasis,
    AccountRiskTicket,
    FeedbackKind,
    ScienceDecisionIdentity,
    build_account_action_from_ticket,
    build_science_decision,
    freeze_shadow_episode,
    settle_shadow_episode,
)
from xinao.shadow_lifecycle.store import (
    load_seat,
    period_directory,
    write_frozen_exclusive,
    write_outcome_and_settled_exclusive,
    write_seat_exclusive,
)

P1_OPEN = datetime(2026, 8, 2, 8, tzinfo=UTC)
P2_OPEN = datetime(2026, 8, 3, 8, tzinfo=UTC)


def _times(open_at: datetime) -> tuple[datetime, datetime, datetime]:
    return (
        open_at - timedelta(minutes=10),
        open_at - timedelta(minutes=7),
        open_at - timedelta(minutes=5),
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _runtime_canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _prior_longitudinal_materials(
    portfolio_root: Path,
    *,
    portfolio_reality,
) -> dict[str, bytes]:
    attempt_cas_digest = "1" * 64
    prior_intent = ActorAuthoredBehaviorIntent(
        authored_at="2026-08-02T07:53:00Z",
        decision_kind="NO_ACTION",
        panel=None,
        selected_number=None,
        stake="0.0000",
        research_rationale="The prior actor chose not to act after its own research.",
    ).with_content_hash()
    manifest = {
        "schema_version": CANDIDATE_MANIFEST_SCHEMA,
        "manifest_marker": CANDIDATE_MANIFEST_MARKER,
        "candidate_id": "prior-candidate",
        "candidate_version": "v1",
        "research_question": "What did the prior actor try?",
        "research_object": "The prior unknown target and the actor's method.",
        "account_recommendation": "NO_ACTION_CANDIDATE",
        "data_cutoff": {"as_of": "2026-08-02T07:50:00Z", "material_refs": []},
        "method_refs": ["prior actor-authored method"],
        "falsifiers": ["A later result may falsify the prior method."],
        "owner_adopted": False,
        "completion": False,
        "candidate_only": True,
        "episode_id": "episode.prior-complete-actor.v1",
        "attempt_cas_digest": attempt_cas_digest,
        "proposed": prior_intent.model_dump(mode="json"),
    }
    manifest_raw = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    export = {
        "schema_version": EXPORT_SCHEMA,
        "episode_id": manifest["episode_id"],
        "attempt_cas_digest": attempt_cas_digest,
        "attempt_hash": "2" * 64,
        "raw_session_hash": "3" * 64,
        "tool_trace_hash": "4" * 64,
        "artifact_manifest_hash": "5" * 64,
        "candidate_manifest_sha256": _sha256(manifest_raw),
        "pair_receipt_sha256": "6" * 64,
        "provider_session_uuid": "provider-session-prior",
        "research_profile": "OPEN_RESEARCH",
        "actual_turns": 2,
        "candidate_only": True,
        "owner_adopted": False,
        "completion_claim_allowed": False,
        "freeze_written": False,
        "settlement_written": False,
    }
    export_raw = (json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    feedback_body = {
        "schema_version": PACK_SCHEMA_VERSION,
        "pack_marker": PACK_MARKER,
        "pack_ref": "feedback.fixture.p1",
        "prior_result_sha256": _sha256(export_raw),
        "prior_receipt_content_sha256": _sha256(manifest_raw),
        "portfolio_ref": portfolio_reality.portfolio_ref,
        "period_index": portfolio_reality.period_index - 1,
        "settled_episode_hash": portfolio_reality.prior_settled_episode_hash,
        "closing_balance": portfolio_reality.current_balance,
        "account_feedback_hash": portfolio_reality.live_head_feedback_hash,
        "future_outcome_access": False,
        "scientific_promotion": False,
        "completion_claim_allowed": False,
        "auto_start_next_research": False,
        "auto_next_period_freeze": False,
    }
    feedback = {**feedback_body, "content_hash": canonical_sha256(feedback_body)}
    feedback_raw = (
        json.dumps(feedback, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    feedback_path = research_feedback_pack_cas_path(
        portfolio_root,
        feedback["content_hash"],
    )
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_bytes(feedback_raw)
    return {
        "prior-candidate-export.json": export_raw,
        "prior-candidate-manifest.json": manifest_raw,
        "prior-feedback-pack.json": feedback_raw,
    }


def _active_material_fixture(
    base: Path,
    *,
    open_at: datetime,
    portfolio_root: Path,
    include_longitudinal_materials: bool = True,
) -> tuple[Path, Path, dict[str, object], str, str]:
    cutoff, _authored, deadline = _times(open_at)
    target_expect = open_at.strftime("%Y%j")
    latest_expect = (open_at - timedelta(days=1)).strftime("%Y%j")
    packet: dict[str, object] = {
        "schema_version": SCHEMA_PACKET,
        "packet_marker": PACKET_MARKER,
        "contract": {"contract_sha256": "c" * 64},
        "latest_completed_expect": latest_expect,
        "target_expect": target_expect,
        "target_ref": f"macaujc2/expect/{target_expect}",
        "target_guard_open_time": open_at.isoformat().replace("+00:00", "Z"),
        "freeze_deadline": deadline.isoformat().replace("+00:00", "Z"),
        "capture_sha256": "d" * 64,
        "host_time_utc": cutoff.isoformat().replace("+00:00", "Z"),
        "unopened": {
            "history_max_expect": latest_expect,
            "point_next_data_null": True,
            "absent_from_history": True,
        },
    }
    packet["content_hash"] = packet_content_hash(packet)
    authority_root = base / f"authority-{target_expect}"
    sealed_packet = write_packet_exclusive(authority_root, packet)
    packet = sealed_packet["packet"]
    terms = ActorObjectiveTermsPacket.from_settlement_rule()
    portfolio_reality = build_actor_portfolio_reality_packet(portfolio_root)
    material_sources = {
        "prospective-packet.json": (
            json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "objective-terms.json": actor_objective_terms_packet_bytes(terms),
        "portfolio-reality.json": actor_portfolio_reality_packet_bytes(portfolio_reality),
    }
    if portfolio_reality.period_index > 1 and include_longitudinal_materials:
        material_sources.update(
            _prior_longitudinal_materials(
                portfolio_root,
                portfolio_reality=portfolio_reality,
            )
        )
    entries = []
    for logical_name, raw in material_sources.items():
        digest = _sha256(raw)
        entries.append(
            {
                "material_id": f"sha256:{digest}",
                "logical_name": logical_name,
                "relative_path": f"files/{digest}.utf8",
                "sha256": digest,
                "size_bytes": len(raw),
                "media_type": "text/plain",
                "encoding": "utf-8",
            }
        )
    entries.sort(key=lambda item: (item["material_id"], item["logical_name"]))
    identity = {
        "schema_version": "xinao.material_bundle.v1",
        "provider_disclosure_scope": "caller_supplied_for_bounded_research_episode",
        "materials": entries,
    }
    bundle_digest = _sha256(_runtime_canonical(identity))
    manifest = {**identity, "bundle_id": f"xinao-material-bundle-sha256:{bundle_digest}"}

    episode_root = base / f"episode-materials-{target_expect}"
    active_root = episode_root / "active_materials"
    bundle_root = active_root / "bundles" / bundle_digest
    bundle_root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        raw = material_sources[entry["logical_name"]]
        target = bundle_root / entry["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    manifest_raw = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_path = bundle_root / "manifest.json"
    manifest_path.write_bytes(manifest_raw)

    packet_materials = []
    for entry in entries:
        raw = material_sources[entry["logical_name"]]
        packet_materials.append(
            {
                "material_id": entry["material_id"],
                "logical_name": entry["logical_name"],
                "sha256": entry["sha256"],
                "size_bytes": entry["size_bytes"],
                "content": raw.decode("utf-8"),
            }
        )
    model_packet = _runtime_canonical(
        {
            "schema_version": "xinao.model_material_packet.v1",
            "bundle_id": manifest["bundle_id"],
            "materials": packet_materials,
        }
    )
    base_prompt = b"test actor prompt\n"
    effective_prompt = (
        base_prompt + RESEARCH_EPISODE_MATERIAL_PACKET_NOTICE.encode("utf-8") + model_packet
    )
    effective_hash = _sha256(effective_prompt)
    prompt_relative = f"prompts/{effective_hash}.utf8"
    prompt_path = active_root / prompt_relative
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_bytes(effective_prompt)

    ids = {entry["logical_name"]: entry["material_id"] for entry in entries}
    binding: dict[str, object] = {
        "schema_version": "xinao.research_episode_active_material_binding.v1",
        "material_bundle_id": manifest["bundle_id"],
        "material_manifest": manifest,
        "material_manifest_sha256": _sha256(manifest_raw),
        "material_manifest_relative_path": f"bundles/{bundle_digest}/manifest.json",
        "material_packet_sha256": _sha256(model_packet),
        "base_prompt_sha256": _sha256(base_prompt),
        "effective_prompt_sha256": effective_hash,
        "effective_prompt_relative_path": prompt_relative,
        "container_material_root": "/active-materials",
        "container_bundle_path": f"/active-materials/bundles/{bundle_digest}",
        "container_effective_prompt_path": f"/active-materials/{prompt_relative}",
        "material_snapshot_at": cutoff.isoformat().replace("+00:00", "Z"),
    }
    entry_by_name = {entry["logical_name"]: entry for entry in entries}
    feedback_raw = material_sources.get("prior-feedback-pack.json")
    feedback = json.loads(feedback_raw.decode("utf-8")) if feedback_raw else None
    verified: dict[str, object] = {
        "schema_version": "xinao.research_episode_verified_material_reality.v1",
        "episode_id": f"episode.actor-fixture.{target_expect}",
        "host_session_id": f"host.actor-fixture.{target_expect}",
        "cas_head_sha256": "7" * 64,
        "attempt_cas_digest": "8" * 64,
        "attempt_internal_cas_digest": "9" * 64,
        "attempt_hash": "a" * 64,
        "provider_session_uuid": "00000000-0000-4000-8000-000000000001",
        "active_material_binding": binding,
        "portfolio_reality_material_id": ids["portfolio-reality.json"],
        "portfolio_reality_material_sha256": entry_by_name["portfolio-reality.json"]["sha256"],
        "portfolio_reality_content_hash": portfolio_reality.content_hash,
        "portfolio_reality_period_index": portfolio_reality.period_index,
        "prospective_packet_material_id": ids["prospective-packet.json"],
        "prospective_packet_material_sha256": entry_by_name["prospective-packet.json"]["sha256"],
        "prospective_packet_content_hash": packet["content_hash"],
        "prospective_target_expect": packet["target_expect"],
        "prospective_target_ref": packet["target_ref"],
        "objective_terms_material_id": ids["objective-terms.json"],
        "objective_terms_material_sha256": entry_by_name["objective-terms.json"]["sha256"],
        "objective_terms_content_hash": terms.content_hash,
        "prior_feedback_material_id": (
            ids["prior-feedback-pack.json"] if feedback is not None else None
        ),
        "prior_feedback_material_sha256": (
            entry_by_name["prior-feedback-pack.json"]["sha256"] if feedback is not None else None
        ),
        "prior_feedback_content_hash": feedback.get("content_hash") if feedback else None,
        "prior_candidate_export_material_id": (
            ids["prior-candidate-export.json"] if feedback is not None else None
        ),
        "prior_candidate_export_sha256": (
            entry_by_name["prior-candidate-export.json"]["sha256"] if feedback is not None else None
        ),
        "prior_candidate_manifest_material_id": (
            ids["prior-candidate-manifest.json"] if feedback is not None else None
        ),
        "prior_candidate_manifest_sha256": (
            entry_by_name["prior-candidate-manifest.json"]["sha256"]
            if feedback is not None
            else None
        ),
    }
    return (
        episode_root,
        authority_root,
        verified,
        ids["prospective-packet.json"],
        ids["objective-terms.json"],
    )


def _portfolio_root(tmp_path: Path, *, suffix: str = "alpha") -> Path:
    root = tmp_path / f"portfolio-{suffix}"
    init_portfolio(
        root=root,
        seat_id=f"seat.complete-actor.{suffix}",
        portfolio_ref=f"portfolio.complete-actor.{suffix}",
    )
    return root


@pytest.fixture
def portfolio_root(tmp_path: Path) -> Path:
    return _portfolio_root(tmp_path)


def _contract(
    portfolio_root: Path,
    *,
    open_at: datetime = P1_OPEN,
) -> ActorRealityContract:
    episode_root, authority_root, verified, _prospective_id, _terms_id = _active_material_fixture(
        portfolio_root.parent,
        open_at=open_at,
        portfolio_root=portfolio_root,
    )
    return ActorRealityContract._from_verified_material_reality(
        portfolio_root=portfolio_root,
        episode_root=episode_root,
        authority_root=authority_root,
        verified_material_reality=verified,
    )


def _behavior_payload(contract: ActorRealityContract, **updates: Any) -> dict[str, Any]:
    _cutoff, authored, _deadline = _times(contract.target_open_time)
    values: dict[str, Any] = {
        "behavior_ref": f"behavior.{contract.research_lineage_ref}.v1",
        "actor_id": contract.actor_id,
        "research_lineage_ref": contract.research_lineage_ref,
        "reality": contract,
        "authored_at": authored,
        "science_identity": "SCIENCE_CANDIDATE",
        "candidate_ref": f"candidate.{contract.research_lineage_ref}.v1",
        "decision_kind": "ACTION",
        "panel": "B",
        "selected_number": 17,
        "stake": contract.current_balance,
        "research_rationale": "The actor chose this action from its own open-ended research.",
        "after_hit_response": "Read the hit and balance, then choose the next method freely.",
        "after_miss_response": "Read the miss and loss, then revise or retain the method freely.",
        "next_round_or_stop_response": "Continue, change course, or stop after reading reality.",
    }
    values.update(updates)
    if "actor_authored_intent_hash" not in updates:
        intent_payload = {
            field: values[field]
            for field in (
                "authored_at",
                "decision_kind",
                "panel",
                "selected_number",
                "stake",
                "research_rationale",
                "after_hit_response",
                "after_miss_response",
                "next_round_or_stop_response",
            )
        }
        values["actor_authored_intent_hash"] = (
            ActorAuthoredBehaviorIntent.model_validate(intent_payload)
            .with_content_hash()
            .content_hash
        )
    return values


def _behavior(contract: ActorRealityContract, **updates: Any) -> CompleteActorBehavior:
    payload = _behavior_payload(contract, **updates)
    return CompleteActorBehavior.model_validate(payload).with_content_hash()


def _intent(contract: ActorRealityContract, **updates: Any) -> ActorAuthoredBehaviorIntent:
    payload = _behavior_payload(contract, **updates)
    intent_payload = {
        field: payload[field]
        for field in (
            "authored_at",
            "decision_kind",
            "panel",
            "selected_number",
            "stake",
            "research_rationale",
            "after_hit_response",
            "after_miss_response",
            "next_round_or_stop_response",
        )
    }
    return ActorAuthoredBehaviorIntent.model_validate(intent_payload).with_content_hash()


def _projection(behavior: CompleteActorBehavior, portfolio_root: Path):
    target_expect = behavior.reality.material_reality.target_expect
    episode_root = portfolio_root.parent / f"episode-materials-{target_expect}"
    authority_root = portfolio_root.parent / f"authority-{target_expect}"
    live_reality = ActorRealityContract._from_verified_material_reality(
        portfolio_root=portfolio_root,
        episode_root=episode_root,
        authority_root=authority_root,
        verified_material_reality=(
            behavior.reality.material_reality._verified_material_reality_snapshot()
        ),
    )
    return build_shadow_freeze_input_candidate(
        behavior,
        live_reality=live_reality,
    )


def _settled_miss(*, seat, stake: str):
    cutoff, _authored, deadline = _times(P1_OPEN)
    frozen_at = deadline - timedelta(minutes=1)
    candidate_ref = "candidate.prior-complete-actor.v1"
    ticket = AccountRiskTicket(
        ticket_ref="account-ticket.prior-complete-actor.v1",
        target_ref="draw.20260802-001",
        target_open_time=P1_OPEN,
        freeze_deadline=deadline,
        knowledge_cutoff=cutoff,
        frozen_at=frozen_at,
        panel="B",
        selected_number=17,
        stake=stake,
        rule_ref="special-number-rule.v1",
        odds_version_ref="odds.special-number.20260802.v1",
        baseline_ref="BO0013",
        risk_policy_ref="actor-authored-prior-behavior.v1",
        information_set_ref="information.prior.cutoff",
        information_set_hash="b" * 64,
    ).with_content_hash()
    science = build_science_decision(
        science_decision_ref="science.prior-complete-actor.v1",
        identity=ScienceDecisionIdentity.SCIENCE_CANDIDATE,
        candidate_ref=candidate_ref,
        knowledge_cutoff=cutoff,
        rationale_ref="rationale.prior-complete-actor.v1",
    )
    account = build_account_action_from_ticket(
        account_decision_ref="account.prior-complete-actor.v1",
        account_ticket=ticket,
    )
    frozen = freeze_shadow_episode(
        episode_ref="episode.prior-complete-actor.v1",
        seat=seat,
        science_decision=science,
        account_decision=account,
        target_ref=ticket.target_ref,
        target_open_time=P1_OPEN,
        freeze_deadline=deadline,
        frozen_at=frozen_at,
        bound_account_ticket=ticket,
        position_journal_group_ref="journal.position.prior-complete-actor.v1",
        accounting_basis=AccountingBasis.CARRIED_BALANCE_SNAPSHOT,
    )
    outcome = OutcomeObservation(
        outcome_ref="outcome.prior-complete-actor.v1",
        source_ref="independent.test.authority",
        target_ref=ticket.target_ref,
        actual_special_number=18,
        observed_at=P1_OPEN + timedelta(minutes=1),
        verified=True,
    ).with_hash()
    settled = settle_shadow_episode(
        episode=frozen,
        outcome=outcome,
        settlement_ref="settlement.prior-complete-actor.v1",
        settlement_journal_group_ref="journal.settlement.prior-complete-actor.v1",
        statement_ref="statement.prior-complete-actor.v1",
        existing_settlements=(),
    )
    return frozen, outcome, settled


def _seal_live_miss(*, root: Path, stake: str):
    seat = load_seat(root)
    frozen, outcome, settled = _settled_miss(seat=seat, stake=stake)
    period_root = period_directory(root, 1)
    write_seat_exclusive(period_root, seat)
    write_frozen_exclusive(period_root, frozen)
    write_outcome_and_settled_exclusive(period_root, outcome=outcome, settled=settled)
    feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.TYPED_FEEDBACK,
        notes="fixture feedback: make the settled live head available to the same actor",
    )
    return settled


def test_reality_contract_reads_sealed_genesis_and_objective_terms(
    portfolio_root: Path,
) -> None:
    contract = _contract(portfolio_root)

    assert contract.period_index == 1
    assert contract.current_balance == "10000.0000"
    assert contract.balance_source_kind == BalanceSourceKind.GENESIS_SEAT
    assert contract.balance_source_hash == contract.seat_content_hash
    assert contract.material_reality.portfolio_reality.current_balance == "10000.0000"
    assert contract.material_reality.portfolio_reality.actor_id == contract.seat_id
    assert contract.outcome_available is False
    assert contract.knowledge_cutoff == contract.material_reality.material_snapshot_at
    assert contract.selection_min == 1
    assert contract.selection_max == 49
    assert [(offer.panel, offer.gross_odds) for offer in contract.objective_odds] == [
        ("A", "47.285"),
        ("B", "42.385"),
    ]
    assert contract.material_reality.objective_terms.source_kind == (
        "PINNED_SETTLEMENT_RULE_SNAPSHOT"
    )
    assert contract.odds_version_ref == (
        f"odds.special-number.sha256:{contract.material_reality.objective_terms.content_hash}"
    )
    assert contract.content_hash == contract.compute_content_hash()

    with pytest.raises(ValidationError, match="frozen"):
        contract.current_balance = "99999.0000"  # type: ignore[misc]


def test_active_binding_hash_binds_windows_provenance_outside_jcs_integer_domain(
    tmp_path: Path,
) -> None:
    portfolio_root = _portfolio_root(tmp_path)
    episode_root, authority_root, verified, _prospective_id, _terms_id = _active_material_fixture(
        tmp_path,
        open_at=P1_OPEN,
        portfolio_root=portfolio_root,
    )
    binding = verified["active_material_binding"]
    assert isinstance(binding, dict)
    binding["material_source_refs"] = [
        {
            "st_dev": 13599825006036549566,
            "st_ino": 9007199254864121,
            "st_mtime_ns": 1785573664473036700,
        }
    ]
    expected = _sha256(_runtime_canonical(binding))

    contract = ActorRealityContract._from_verified_material_reality(
        portfolio_root=portfolio_root,
        episode_root=episode_root,
        authority_root=authority_root,
        verified_material_reality=verified,
    )

    assert contract.material_reality.active_material_binding_hash == expected
    packet_path = next((authority_root / "objects" / "packet" / "sha256").rglob("*.json"))
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    expected_source_binding_hash = _sha256(
        _runtime_canonical(build_source_authority_binding(packet))
    )
    assert contract.material_reality.source_authority_binding_hash == expected_source_binding_hash
    binding["material_source_refs"][0]["st_ino"] += 1
    changed = ActorRealityContract._from_verified_material_reality(
        portfolio_root=portfolio_root,
        episode_root=episode_root,
        authority_root=authority_root,
        verified_material_reality=verified,
    )
    assert changed.material_reality.active_material_binding_hash != expected


def test_reality_contract_carries_exact_live_head_close_without_version_reset(
    portfolio_root: Path,
) -> None:
    settled = _seal_live_miss(root=portfolio_root, stake="250.0000")
    assert settled.statement.closing_balance == "9750.0000"

    contract = _contract(portfolio_root, open_at=P2_OPEN)

    assert contract.period_index == 2
    assert contract.current_balance == "9750.0000"
    assert contract.balance_source_kind == BalanceSourceKind.PRIOR_SETTLED_CLOSE
    assert contract.balance_source_hash == settled.content_hash
    assert contract.prior_settled_episode_hash == settled.content_hash
    assert contract.prior_statement_hash == settled.statement.content_hash
    assert contract.live_head_period_index == 1
    assert contract.live_head_phase == "FEEDBACK_SEALED"
    assert contract.live_head_settled_episode_hash == settled.content_hash
    assert contract.material_reality.prior_feedback_content_hash is not None
    assert contract.material_reality.prior_candidate_export_material_id is not None
    assert contract.material_reality.prior_candidate_manifest_material_id is not None


def test_reality_rejects_portfolio_packet_from_a_different_live_actor(tmp_path: Path) -> None:
    actual_root = _portfolio_root(tmp_path, suffix="actual")
    foreign_root = _portfolio_root(tmp_path, suffix="foreign")
    episode_root, authority_root, verified, _prospective_id, _terms_id = _active_material_fixture(
        tmp_path,
        open_at=P1_OPEN,
        portfolio_root=foreign_root,
    )

    with pytest.raises(ValueError, match="ACTOR_VISIBLE_PORTFOLIO_MISMATCH"):
        ActorRealityContract._from_verified_material_reality(
            portfolio_root=actual_root,
            episode_root=episode_root,
            authority_root=authority_root,
            verified_material_reality=verified,
        )


def test_period_two_requires_prior_feedback_result_receipt_and_behavior_material(
    tmp_path: Path,
) -> None:
    portfolio_root = _portfolio_root(tmp_path)
    _seal_live_miss(root=portfolio_root, stake="250.0000")
    episode_root, authority_root, verified, _prospective_id, _terms_id = _active_material_fixture(
        tmp_path,
        open_at=P2_OPEN,
        portfolio_root=portfolio_root,
        include_longitudinal_materials=False,
    )

    with pytest.raises(ValueError, match="PRIOR_FEEDBACK_MATERIAL_IDENTITY_AMBIGUOUS"):
        ActorRealityContract._from_verified_material_reality(
            portfolio_root=portfolio_root,
            episode_root=episode_root,
            authority_root=authority_root,
            verified_material_reality=verified,
        )


def test_low_level_verified_binding_factory_does_not_accept_actor_reality_fields() -> None:
    assert not hasattr(ActorRealityContract, "from_live_portfolio")
    parameters = inspect.signature(ActorRealityContract._from_verified_material_reality).parameters

    for root_name in ("portfolio_root", "episode_root", "authority_root"):
        assert root_name in parameters
        assert parameters[root_name].default is inspect.Parameter.empty
    assert "actor_id" not in parameters
    assert "research_lineage_ref" not in parameters
    assert "prior_settled" not in parameters
    assert "current_balance" not in parameters
    assert "objective_odds" not in parameters
    assert "rule_ref" not in parameters
    assert "target_ref" not in parameters
    assert "target_open_time" not in parameters
    assert "freeze_deadline" not in parameters
    assert "odds_version_ref" not in parameters
    assert "knowledge_cutoff" not in parameters
    assert "prospective_packet_material_id" not in parameters
    assert "objective_terms_material_id" not in parameters
    factory_source = inspect.getsource(ActorRealityContract._from_verified_material_reality)
    assert "getenv" not in factory_source
    assert "environ" not in factory_source


def test_reality_rejects_orphan_packet_not_selected_by_target_index(tmp_path: Path) -> None:
    portfolio_root = _portfolio_root(tmp_path)
    episode_root, authority_root, binding, _prospective_id, _terms_id = _active_material_fixture(
        tmp_path,
        open_at=P1_OPEN,
        portfolio_root=portfolio_root,
    )
    target_expect = P1_OPEN.strftime("%Y%j")
    index_path = authority_root / "index" / "target" / f"{target_expect}.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["packet_content_hash"] = "e" * 64
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="TARGET_INDEX_MISMATCH"):
        ActorRealityContract._from_verified_material_reality(
            portfolio_root=portfolio_root,
            episode_root=episode_root,
            authority_root=authority_root,
            verified_material_reality=binding,
        )


def test_reality_requires_prospective_material_bytes_to_equal_authority_cas(
    tmp_path: Path,
) -> None:
    portfolio_root = _portfolio_root(tmp_path)
    episode_root, authority_root, binding, _prospective_id, _terms_id = _active_material_fixture(
        tmp_path,
        open_at=P1_OPEN,
        portfolio_root=portfolio_root,
    )
    packet_path = next((authority_root / "objects" / "packet" / "sha256").rglob("*.json"))
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="AUTHORITY_RAW_BYTES_MISMATCH"):
        ActorRealityContract._from_verified_material_reality(
            portfolio_root=portfolio_root,
            episode_root=episode_root,
            authority_root=authority_root,
            verified_material_reality=binding,
        )


def test_reality_rejects_prompt_prefix_not_bound_by_base_prompt_hash(tmp_path: Path) -> None:
    portfolio_root = _portfolio_root(tmp_path)
    episode_root, authority_root, binding, _prospective_id, _terms_id = _active_material_fixture(
        tmp_path,
        open_at=P1_OPEN,
        portfolio_root=portfolio_root,
    )
    active_binding = binding["active_material_binding"]
    assert isinstance(active_binding, dict)
    active_binding["base_prompt_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="EFFECTIVE_PROMPT_MATERIAL_BINDING_MISMATCH"):
        ActorRealityContract._from_verified_material_reality(
            portfolio_root=portfolio_root,
            episode_root=episode_root,
            authority_root=authority_root,
            verified_material_reality=binding,
        )


def test_reality_rejects_caller_narrowed_or_forged_objective_terms(
    portfolio_root: Path,
) -> None:
    contract = _contract(portfolio_root)
    payload = contract.model_dump(mode="python", exclude={"content_hash"})
    payload["objective_odds"] = [payload["objective_odds"][1]]
    with pytest.raises(ValidationError, match=r"OBJECTIVE_(ODDS|TERMS)"):
        ActorRealityContract.model_validate(payload)

    payload = contract.model_dump(mode="python", exclude={"content_hash"})
    payload["objective_odds"][0]["gross_odds"] = "999.0"
    with pytest.raises(ValidationError, match=r"OBJECTIVE_(ODDS|TERMS)"):
        ActorRealityContract.model_validate(payload)


def test_model_copy_cannot_reseal_a_validator_bypass(portfolio_root: Path) -> None:
    contract = _contract(portfolio_root)
    forged_contract = contract.model_copy(
        update={"current_balance": "99999.0000", "content_hash": None}
    )
    with pytest.raises(ValidationError, match="ACTOR_VISIBLE_PORTFOLIO_MISMATCH"):
        forged_contract.with_content_hash()

    forged_contract = forged_contract.model_copy(
        update={"content_hash": forged_contract.compute_content_hash()}
    )
    with pytest.raises(ValidationError, match="ACTOR_VISIBLE_PORTFOLIO_MISMATCH"):
        CompleteActorBehavior.model_validate(_behavior_payload(forged_contract))

    behavior = _behavior(contract, stake="1.0000")
    forged_behavior = behavior.model_copy(update={"stake": "10000.0001", "content_hash": None})
    with pytest.raises(ValidationError, match="ACTION_STAKE_EXCEEDS_BALANCE"):
        forged_behavior.with_content_hash()

    forged_behavior = forged_behavior.model_copy(
        update={"content_hash": forged_behavior.compute_content_hash()}
    )
    with pytest.raises(ValueError, match="VALIDATION_BYPASS_REJECTED"):
        _projection(forged_behavior, portfolio_root)


def test_contract_rejects_balance_that_disagrees_with_actor_visible_packet(
    portfolio_root: Path,
) -> None:
    contract = _contract(portfolio_root)
    forged_payload = contract.model_dump(mode="python", exclude={"content_hash"})
    forged_payload["genesis_opening_balance"] = "99999.0000"
    forged_payload["current_balance"] = "99999.0000"
    with pytest.raises(ValidationError, match="ACTOR_VISIBLE_PORTFOLIO_MISMATCH"):
        ActorRealityContract.model_validate(forged_payload)


def test_actor_and_lineage_are_derived_from_live_seat_not_caller(
    portfolio_root: Path,
) -> None:
    contract = _contract(portfolio_root)
    assert contract.actor_id == contract.seat_id
    assert contract.research_lineage_ref == contract.seat_id

    forged_contract = contract.model_dump(mode="python", exclude={"content_hash"})
    forged_contract["actor_id"] = "foreign-actor"
    forged_contract["research_lineage_ref"] = "foreign-lineage"
    with pytest.raises(ValidationError, match="LIVE_SEAT_IDENTITY_MISMATCH"):
        ActorRealityContract.model_validate(forged_contract)

    forged_behavior = _behavior_payload(contract, actor_id="foreign-actor")
    with pytest.raises(ValidationError, match="COMPLETE_ACTOR_IDENTITY_MISMATCH"):
        CompleteActorBehavior.model_validate(forged_behavior)


def test_sealed_action_intent_builds_behavior_without_actor_or_reality_self_report(
    portfolio_root: Path,
) -> None:
    reality = _contract(portfolio_root)
    intent = _intent(
        reality,
        panel="A",
        selected_number=49,
        stake="4321.9876",
        research_rationale="This is the researcher's own action and sizing.",
    )
    candidate_ref = "candidate.complete-actor.intent-action.v1"
    behavior = build_complete_actor_behavior(
        reality,
        intent,
        candidate_ref=candidate_ref,
    )

    authored_fields = set(ActorAuthoredBehaviorIntent.model_fields) - {
        "schema_version",
        "content_hash",
    }
    assert authored_fields == {
        "authored_at",
        "decision_kind",
        "panel",
        "selected_number",
        "stake",
        "research_rationale",
        "after_hit_response",
        "after_miss_response",
        "next_round_or_stop_response",
    }
    assert behavior.behavior_ref.startswith(ACTOR_BEHAVIOR_SOURCE_REF_PREFIX)
    assert behavior.actor_authored_intent_hash == intent.content_hash
    assert behavior.actor_id == reality.seat_id
    assert behavior.research_lineage_ref == reality.seat_id
    assert behavior.reality == reality
    assert behavior.science_identity == "SCIENCE_CANDIDATE"
    assert behavior.candidate_ref == candidate_ref
    for field in authored_fields:
        assert getattr(behavior, field) == getattr(intent, field)


def test_sealed_no_action_intent_remains_explicit_when_joined_to_live_reality(
    portfolio_root: Path,
) -> None:
    reality = _contract(portfolio_root)
    intent = _intent(
        reality,
        decision_kind="NO_ACTION",
        panel=None,
        selected_number=None,
        stake="0.0000",
        research_rationale="The researcher chooses not to act on this target.",
    )
    behavior = build_complete_actor_behavior(
        reality,
        intent,
        candidate_ref="candidate.complete-actor.intent-no-action.v1",
    )
    projection = _projection(behavior, portfolio_root)

    assert behavior.decision_kind == ActorDecisionKind.NO_ACTION
    assert behavior.panel is None
    assert behavior.selected_number is None
    assert behavior.stake == "0.0000"
    assert projection.account_identity == "RESEARCHER_ACCOUNT_NO_ACTION"
    assert projection.executable_account_decision is None
    assert projection.no_action_intent is not None


def test_intent_tampering_or_reality_smuggling_is_rejected(portfolio_root: Path) -> None:
    reality = _contract(portfolio_root)
    raw = _intent(reality).model_dump(mode="python", exclude={"content_hash"})
    raw["current_balance"] = "99999.0000"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ActorAuthoredBehaviorIntent.model_validate(raw)

    intent = _intent(reality, stake="17.0000")
    tampered = intent.model_copy(update={"stake": "9999.0000"})
    with pytest.raises(ValueError, match="ACTOR_AUTHORED_BEHAVIOR_INTENT_VALIDATION_BYPASS"):
        build_complete_actor_behavior(
            reality,
            tampered,
            candidate_ref="candidate.complete-actor.tampered.v1",
        )

    outside_rule = _intent(reality, selected_number=50)
    with pytest.raises(ValidationError, match=r"less than or equal to 49|OUTSIDE_OBJECTIVE_RULE"):
        build_complete_actor_behavior(
            reality,
            outside_rule,
            candidate_ref="candidate.complete-actor.outside-rule.v1",
        )


@pytest.mark.parametrize("stake", ["0.0001", "17.2500", "9999.9999", "10000.0000"])
def test_actor_can_choose_any_positive_stake_up_to_balance(
    stake: str,
    portfolio_root: Path,
) -> None:
    behavior = _behavior(_contract(portfolio_root), stake=stake)

    assert behavior.decision_kind == ActorDecisionKind.ACTION
    assert behavior.stake == stake


def test_action_projects_exact_existing_researcher_core_without_freeze_identity(
    portfolio_root: Path,
) -> None:
    behavior = _behavior(
        _contract(portfolio_root),
        panel="A",
        selected_number=49,
        stake="4321.9876",
    )
    projection = _projection(behavior, portfolio_root)

    assert projection.candidate_only is True
    assert projection.owner_adopted is False
    assert projection.freeze_written is False
    assert projection.settlement_written is False
    assert projection.account_identity == "ACTION"
    assert projection.actor_authored_intent_hash == behavior.actor_authored_intent_hash
    assert projection.episode_id == behavior.reality.material_reality.episode_id
    assert projection.attempt_cas_digest == (behavior.reality.material_reality.attempt_cas_digest)
    assert projection.attempt_hash == behavior.reality.material_reality.attempt_hash
    assert projection.information_set_ref == behavior.reality.material_reality.material_bundle_id
    assert projection.information_set_hash == (
        behavior.reality.material_reality.material_manifest_sha256
    )
    assert projection.material_packet_sha256 == (
        behavior.reality.material_reality.material_packet_sha256
    )
    assert projection.effective_prompt_sha256 == (
        behavior.reality.material_reality.effective_prompt_sha256
    )
    assert projection.prospective_packet_content_hash == (
        behavior.reality.material_reality.prospective_packet_content_hash
    )
    assert projection.objective_terms_content_hash == (
        behavior.reality.material_reality.objective_terms.content_hash
    )
    assert projection.no_action_intent is None
    assert projection.executable_account_decision is not None
    core = projection.executable_account_decision.model_dump(mode="json")
    assert set(core) == {
        "panel",
        "selected_number",
        "stake",
        "target_ref",
        "target_open_time",
        "freeze_deadline",
        "knowledge_cutoff",
        "odds_version_ref",
        "baseline_ref",
        "risk_policy_ref",
        "rule_ref",
    }
    assert core["panel"] == "A"
    assert core["baseline_ref"] == "BO0001"
    assert core["selected_number"] == 49
    assert core["stake"] == "4321.9876"
    assert core["risk_policy_ref"] == f"{ACTOR_BEHAVIOR_REF_PREFIX}{behavior.content_hash}"
    assert "frozen_at" not in core
    assert "ticket_ref" not in core
    assert "information_set_ref" not in core


def test_projection_rechecks_exact_episode_material_bytes(portfolio_root: Path) -> None:
    behavior = _behavior(_contract(portfolio_root), stake="1.0000")
    materials = behavior.reality.material_reality
    entry = materials.material_manifest.entry(materials.prospective_packet_material_id)
    episode_root = portfolio_root.parent / f"episode-materials-{materials.target_expect}"
    bundle_digest = materials.material_bundle_id.split(":", 1)[1]
    material_path = (
        episode_root / "active_materials" / "bundles" / bundle_digest / entry.relative_path
    )
    material_path.write_bytes(material_path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="ACTOR_MATERIAL_FILE_IDENTITY_MISMATCH"):
        _projection(behavior, portfolio_root)


def test_projection_rejects_undeclared_file_in_actor_visible_bundle(
    portfolio_root: Path,
) -> None:
    behavior = _behavior(_contract(portfolio_root), stake="1.0000")
    materials = behavior.reality.material_reality
    episode_root = portfolio_root.parent / f"episode-materials-{materials.target_expect}"
    bundle_digest = materials.material_bundle_id.split(":", 1)[1]
    extra_path = (
        episode_root / "active_materials" / "bundles" / bundle_digest / "files" / "undeclared.utf8"
    )
    extra_path.write_text("unsealed actor-visible bytes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ACTOR_MATERIAL_BUNDLE_FILE_SET_MISMATCH"):
        _projection(behavior, portfolio_root)


def test_fresh_live_reality_requires_owner_authority_cas_packet(portfolio_root: Path) -> None:
    behavior = _behavior(_contract(portfolio_root), stake="1.0000")
    materials = behavior.reality.material_reality
    episode_root = portfolio_root.parent / f"episode-materials-{materials.target_expect}"

    with pytest.raises(ValueError, match="PACKET_MISSING"):
        ActorRealityContract._from_verified_material_reality(
            portfolio_root=portfolio_root,
            episode_root=episode_root,
            authority_root=portfolio_root.parent / "missing-authority-root",
            verified_material_reality=materials._verified_material_reality_snapshot(),
        )


def test_no_action_is_explicit_actor_intent_not_missing_action(portfolio_root: Path) -> None:
    behavior = _behavior(
        _contract(portfolio_root),
        decision_kind="NO_ACTION",
        panel=None,
        selected_number=None,
        stake="0.0000",
        research_rationale="The actor sees no worthwhile action now.",
    )
    projection = _projection(behavior, portfolio_root)

    assert behavior.decision_kind == ActorDecisionKind.NO_ACTION
    assert projection.account_identity == "RESEARCHER_ACCOUNT_NO_ACTION"
    assert projection.actor_behavior_content_hash == behavior.content_hash
    assert projection.executable_account_decision is None
    assert projection.no_action_intent is not None
    assert projection.no_action_intent.target_ref == behavior.reality.target_ref
    assert "frozen_at" not in projection.no_action_intent.model_dump(mode="json")


@pytest.mark.parametrize("stake", ["0.0000", "10000.0001", "1", "-1.0000"])
def test_invalid_action_is_rejected_never_rewritten_to_no_action(
    stake: str,
    portfolio_root: Path,
) -> None:
    with pytest.raises(ValidationError, match=r"STAKE|ACTION"):
        CompleteActorBehavior.model_validate(
            _behavior_payload(_contract(portfolio_root), stake=stake)
        )


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"stake": "1.0000"}, "NO_ACTION_STAKE_MUST_BE_ZERO"),
        ({"panel": "B", "selected_number": 7}, "NO_ACTION_MUST_NOT_SELECT"),
    ],
)
def test_no_action_cannot_smuggle_stake_or_selection(
    updates: dict[str, Any],
    reason: str,
    portfolio_root: Path,
) -> None:
    payload = _behavior_payload(
        _contract(portfolio_root),
        decision_kind="NO_ACTION",
        panel=None,
        selected_number=None,
        stake="0.0000",
    )
    payload.update(updates)
    with pytest.raises(ValidationError, match=reason):
        CompleteActorBehavior.model_validate(payload)


def test_bankruptcy_removes_action_capacity_but_not_actor_no_action(
    portfolio_root: Path,
) -> None:
    _seal_live_miss(root=portfolio_root, stake="10000.0000")
    contract = _contract(portfolio_root, open_at=P2_OPEN)
    assert contract.current_balance == "0.0000"

    with pytest.raises(ValidationError, match="ACTION_STAKE"):
        CompleteActorBehavior.model_validate(
            _behavior_payload(contract, decision_kind="ACTION", stake="0.0001")
        )

    no_action = _behavior(
        contract,
        decision_kind="NO_ACTION",
        panel=None,
        selected_number=None,
        stake="0.0000",
    )
    assert no_action.decision_kind == ActorDecisionKind.NO_ACTION


def test_only_identity_time_no_peek_and_balance_physics_are_validated(
    portfolio_root: Path,
) -> None:
    contract = _contract(portfolio_root)
    forbidden_strategy_fields = {
        "hypotheses",
        "methods",
        "risk_limit",
        "mdd",
        "miss_limit",
        "survive_threshold",
    }
    assert forbidden_strategy_fields.isdisjoint(ActorRealityContract.model_fields)
    assert forbidden_strategy_fields.isdisjoint(CompleteActorBehavior.model_fields)
    assert "information_set_ref" not in CompleteActorBehavior.model_fields
    assert "information_set_hash" not in CompleteActorBehavior.model_fields
    assert contract.material_reality.material_bundle_id.startswith("xinao-material-bundle-sha256:")

    late = _behavior_payload(
        contract,
        authored_at=contract.freeze_deadline + timedelta(seconds=1),
    )
    with pytest.raises(ValidationError, match="COMPLETE_ACTOR_TEMPORAL_VIOLATION"):
        CompleteActorBehavior.model_validate(late)

    peek = _behavior_payload(contract)
    peek["outcome"] = {"actual_special_number": 17}
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CompleteActorBehavior.model_validate(peek)


def test_actor_authored_learning_and_stop_responses_are_preserved_not_interpreted(
    portfolio_root: Path,
) -> None:
    responses = {
        "after_hit_response": "Increase, decrease, or keep stake only after my own analysis.",
        "after_miss_response": "I may reject every old method and invent another one.",
        "next_round_or_stop_response": "I decide whether to continue, abstain, split, or stop.",
    }
    behavior = _behavior(_contract(portfolio_root), **responses)

    for field, expected in responses.items():
        assert getattr(behavior, field) == expected
    assert behavior.content_hash == behavior.compute_content_hash()


def test_current_action_does_not_require_prefilled_future_reactions(
    portfolio_root: Path,
) -> None:
    payload = _behavior_payload(_contract(portfolio_root), stake="17.0000")
    payload.pop("after_hit_response")
    payload.pop("after_miss_response")
    payload.pop("next_round_or_stop_response")

    behavior = CompleteActorBehavior.model_validate(payload).with_content_hash()
    projection = _projection(behavior, portfolio_root)

    assert behavior.after_hit_response is None
    assert behavior.after_miss_response is None
    assert behavior.next_round_or_stop_response is None
    assert projection.account_identity == "ACTION"
