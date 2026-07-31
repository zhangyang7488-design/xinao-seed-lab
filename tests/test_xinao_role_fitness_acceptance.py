"""Focused tests for role-fitness + prospective shadow consumer acceptance harness."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Load harness from skills path (not a package install).
_HARNESS_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "xinao"
    / "scripts"
    / "xinao_role_fitness_acceptance.py"
)


def _load_harness():
    # Ensure discovery package is importable.
    discovery_src = Path(__file__).resolve().parents[1] / "xinao_discovery" / "src"
    if discovery_src.is_dir() and str(discovery_src) not in sys.path:
        sys.path.insert(0, str(discovery_src))
    spec = importlib.util.spec_from_file_location(
        "xinao_role_fitness_acceptance", _HARNESS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["xinao_role_fitness_acceptance"] = module
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


def test_reject_one_shot_text_only_transcript() -> None:
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="one-shot|multi-turn|canary"):
        harness.reject_one_shot_text_only_transcript(
            {
                "route": harness.INSTRUMENT_CANARY_ROUTE,
                "turns": [{"turn": 1, "content": "essay only"}],
                "tool_actions": [],
            }
        )
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="tool"):
        harness.reject_one_shot_text_only_transcript(
            {
                "route": harness.GENUINE_SCIENTIST_ROUTE,
                "turns": [{"t": 1}, {"t": 2}],
                "tool_actions": [],
            }
        )


def test_protocol_pin_shape_is_not_formal_admission() -> None:
    pin = harness.build_fixture_protocol_pin()
    result = harness.validate_prospective_protocol_pin(pin)
    assert result["exposure_status"] == "UNEXPOSED"
    assert result["evaluation_outcome_access"] is False
    assert result["prospective_shape_ok"] is True
    assert result["formal_admission"] is False
    assert result["proof_class"] == harness.PROOF_PROTOCOL_PIN_SHAPE


def test_protocol_pin_rejects_future_peek_and_late_freeze() -> None:
    open_at = datetime(2026, 9, 1, 8, tzinfo=UTC)
    late = {
        "episode_id": "ep",
        "protocol_pin_id": "pin",
        "frozen_at": (open_at + timedelta(minutes=1)).isoformat(),
        "target_open_time": open_at.isoformat(),
        "exposure_status": "UNEXPOSED",
        "evaluation_outcome_access": False,
    }
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="late freeze|before target"):
        harness.validate_prospective_protocol_pin(late)

    peek = harness.build_fixture_protocol_pin(open_at=open_at)
    peek["outcome"] = {"actual_special_number": 1}
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="peek|outcome"):
        harness.validate_prospective_protocol_pin(peek)


def test_scientist_episode_requires_native_session_mcp_and_crypto_binding() -> None:
    good = harness._minimal_scientist_evidence()
    out = harness.validate_scientist_episode_evidence(good)
    assert out["turn_count"] >= 2
    assert out["tool_action_count"] >= 1
    assert out["revised_after_failure"] is True
    assert out["resume_verified"] is True
    assert out["cryptographic_event_binding"] is True
    assert out["native_session_mcp_bound"] is True
    assert out["proof_class"] == harness.PROOF_NATIVE_SESSION_MCP
    assert out["genuine_role_fitness"] is False
    assert out["scientist_evidence_shape_ok"] is True
    assert out["mcp_tool_call_count"] >= 1
    assert out["session_num_turns"] >= 2

    unbound = harness._minimal_scientist_evidence()
    unbound.pop("event_chain")
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="event_chain|cryptographic"):
        harness.validate_scientist_episode_evidence(unbound)

    no_raw = harness._minimal_scientist_evidence()
    no_raw.pop("raw_session_artifact")
    no_raw.pop("raw_mcp_artifacts")
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="raw|session|MCP"):
        harness.validate_scientist_episode_evidence(no_raw)

    no_revise = harness._minimal_scientist_evidence()
    no_revise["experiments"] = [
        {
            "experiment_id": "e1",
            "status": "FAILED",
            "event_hash": no_revise["experiments"][0]["event_hash"],
        }
    ]
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="revise"):
        harness.validate_scientist_episode_evidence(no_revise)

    forged = harness._minimal_scientist_evidence()
    forged["resume"]["checkpoint_id"] = "wrong-ckpt"
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="forged resume|checkpoint"):
        harness.validate_scientist_episode_evidence(forged)

    # Retired DI proof class is fail-closed even with native artifacts present.
    di = harness._minimal_scientist_evidence()
    di["proof_class"] = harness.PROOF_DI_SCIENTIST_SEAM
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="retired|NATIVE"):
        harness.validate_scientist_episode_evidence(di)


def test_raw_session_mcp_hash_mismatch_rejected() -> None:
    evidence = harness._minimal_scientist_evidence()
    evidence["raw_session_artifact"]["sha256"] = "a" * 64
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="sha256 mismatch"):
        harness.validate_scientist_episode_evidence(evidence)


def test_candidate_action_without_science_adopt_is_orthogonal() -> None:
    bundle = harness.build_fixture_candidate_disposition(
        science_identity="SCIENCE_CANDIDATE",
        account_identity="ACTION",
        owner_decision="DEFER",
    )
    result = harness.validate_candidate_and_owner_disposition(bundle)
    assert result["account_action"] is True
    assert result["science_adopted"] is False
    assert result["orthogonal_axes"] is True
    assert result["scientific_promotion_from_pnl"] is False
    assert result["owner_disposition_authentic"] is False
    assert result["disposition_proof_class"] == harness.PROOF_OWNER_DISPOSITION_STRUCTURE


def test_no_action_science_and_account_pair() -> None:
    bundle = harness.build_fixture_candidate_disposition(
        science_identity="POLICY_NO_ACTION",
        account_identity="RESEARCHER_ACCOUNT_NO_ACTION",
        owner_decision="ABSORB_NO_ACTION",
    )
    result = harness.validate_candidate_and_owner_disposition(bundle)
    assert result["science_identity"] == "POLICY_NO_ACTION"
    assert result["account_identity"] == "RESEARCHER_ACCOUNT_NO_ACTION"
    assert result["owner_role"] == "codex"


def test_worker_controlled_disposition_rejected() -> None:
    bundle = harness.build_fixture_candidate_disposition()
    bundle["owner_disposition"]["worker_controlled"] = True
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="worker-controlled"):
        harness.validate_candidate_and_owner_disposition(bundle)


def test_fake_owner_fields_not_authentic() -> None:
    harness.negative_fake_owner_fields()


def test_cross_green_and_rq008_backfill_rejected() -> None:
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="cross-green|promote"):
        harness.validate_candidate_and_owner_disposition(
            {
                "science_decision": {
                    "identity": "POLICY_NO_ACTION",
                    "science_decision_ref": "s1",
                },
                "account_decision": {"identity": "ACTION"},
                "owner_disposition": {
                    "owner_role": "codex",
                    "decision": "DEFER",
                    "disposition_source": "worker_fixture",
                },
                "scientific_promotion_from_pnl": True,
            }
        )
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="RQ008|ineligible"):
        harness.reject_rq008_retrospective_backfill(
            {
                "source": "RQ008",
                "retrospective": True,
                "ticket": {"ticket_ref": "t"},
            }
        )


def test_action_hit_and_no_action_two_period_shadow(tmp_path: Path) -> None:
    result = harness.run_two_period_shadow_consumer(
        portfolio_root=tmp_path / "portfolio",
        work_dir=tmp_path / "work",
        p1_mode="ACTION_HIT",
        p2_mode="NO_ACTION",
    )
    assert result["ok"] is True
    assert result["period_1"]["settled"]["statement_result"] == "HIT"
    assert result["period_1"]["settled"]["pnl"] == "41.3850"
    assert result["period_1"]["settled"]["closing_balance"] == "10041.3850"
    assert result["period_2"]["settled"]["statement_result"] == "NO_EXPOSURE"
    assert result["period_2"]["pre_freeze_balance"] == "10041.3850"
    assert result["period_2"]["prior_closing_balance"] == "10041.3850"
    assert result["period_2"]["settled"]["closing_balance"] == "10041.3850"
    assert result["replay_match"]["period_1"] is True
    assert result["replay_match"]["period_2"] is True
    assert result["scientific_promotion"] is False
    assert result["same_seat"] is True
    assert result["closing_balance_carried"] is True
    assert result["parent_completion"] is False
    assert result["proof_class"] == harness.PROOF_REAL_SHADOW_CONSUMER


def test_integrated_acceptance_receipt_axes(tmp_path: Path) -> None:
    receipt = harness.run_integrated_acceptance(
        work_root=tmp_path / "integrated",
        p1_mode="ACTION_HIT",
        p2_mode="NO_ACTION",
    )
    assert receipt["schema_version"] == harness.RECEIPT_SCHEMA
    assert receipt["carrier_control"] is True
    # Live role fitness must not be greened from native fixture evidence + pin shape.
    assert receipt["role_fitness"] is False
    assert receipt["genuine_role_fitness"] is False
    assert receipt["scientist_evidence_shape_ok"] is True
    assert receipt["formal_protocol_pin_admitted"] is False
    assert receipt["candidate_integrity"] is True
    assert receipt["account_continuity"] is True
    assert receipt["parent_completion"] is False
    assert receipt["completion_claim_allowed"] is False
    assert receipt["scientific_promotion"] is False
    assert receipt["rq008_retrospective_backfill_eligible"] is False
    assert receipt["status"] == "PASS"
    assert receipt["axes"]["parent_completion"] is False
    assert receipt["axes"]["role_fitness"] is False
    assert receipt["proof_classes"]["scientist"] == harness.PROOF_NATIVE_SESSION_MCP
    assert receipt["proof_classes"]["account"] == harness.PROOF_REAL_SHADOW_CONSUMER
    assert "content_hash" in receipt
    assert "first_live_episode_command" in receipt
    # Synthetic HIT must not imply parent completion.
    assert (
        receipt["details"]["shadow_consumer"]["period_1"]["settled"]["statement_result"]
        == "HIT"
    )
    assert receipt["details"]["shadow_consumer"]["parent_completion"] is False


def test_integrated_rejects_fake_one_shot_scientist(tmp_path: Path) -> None:
    fake = {
        "route": harness.INSTRUMENT_CANARY_ROUTE,
        "episode_id": "ep.fake",
        "session_id": "sess.fake",
        "turns": [{"turn": 1, "content": "one shot essay"}],
        "bounded_tool_actions": [],
        "experiments": [],
        "interruption": {"interrupted": False},
        "resume": {"resumed": False},
    }
    receipt = harness.run_integrated_acceptance(
        work_root=tmp_path / "fake-integrated",
        scientist_evidence=fake,
    )
    assert receipt["role_fitness"] is False
    assert receipt["scientist_evidence_shape_ok"] is False
    assert receipt["parent_completion"] is False
    assert receipt["status"] == "FAIL"
    assert any("scientist" in f.lower() or "canary" in f.lower() for f in receipt["failures"])


def test_integrated_rejects_unbound_multi_turn_assertions(tmp_path: Path) -> None:
    """Multi-turn/tool narrative without event_chain must not green scientist shape."""

    fake = harness._minimal_scientist_evidence()
    fake.pop("event_chain")
    receipt = harness.run_integrated_acceptance(
        work_root=tmp_path / "unbound-integrated",
        scientist_evidence=fake,
    )
    assert receipt["scientist_evidence_shape_ok"] is False
    assert receipt["role_fitness"] is False
    assert receipt["status"] == "FAIL"
    assert any("event_chain" in f.lower() or "cryptographic" in f.lower() for f in receipt["failures"])


def test_integrated_rejects_transcript_without_raw_session_mcp(tmp_path: Path) -> None:
    fake = harness._minimal_scientist_evidence()
    fake.pop("raw_session_artifact")
    fake.pop("raw_mcp_artifacts")
    receipt = harness.run_integrated_acceptance(
        work_root=tmp_path / "no-raw-integrated",
        scientist_evidence=fake,
    )
    assert receipt["scientist_evidence_shape_ok"] is False
    assert receipt["role_fitness"] is False
    assert receipt["status"] == "FAIL"
    assert any("raw" in f.lower() or "session" in f.lower() or "mcp" in f.lower() for f in receipt["failures"])


def test_owner_vertical_pre_outcome_and_continuation(tmp_path: Path) -> None:
    work = tmp_path / "vertical"
    pre = harness.run_owner_invoked_vertical(work_root=work, mode="pre_outcome")
    assert pre["schema_version"] == harness.PRE_OUTCOME_RECEIPT_SCHEMA
    assert pre["status"] == "PRE_OUTCOME_PASS"
    assert pre["awaiting_external_outcome"] is True
    assert pre["pre_outcome_freeze_ok"] is True
    assert pre["role_fitness"] is False
    assert pre["genuine_role_fitness"] is False
    assert pre["parent_completion"] is False
    assert pre["completion_claim_allowed"] is False
    assert pre["scientific_promotion"] is False
    assert pre["scientist_evidence_shape_ok"] is True
    assert pre["details"]["scientist_episode"]["native_session_mcp_bound"] is True
    assert pre["details"]["pre_outcome_freeze"]["outcome_present"] is False
    assert "first_live_episode_command" in pre
    assert "owner-vertical" in pre["first_live_episode_command"]

    cont = harness.run_owner_invoked_vertical(
        work_root=work,
        mode="continue_outcome",
        pre_outcome_receipt=pre,
        synthetic_fixture_outcome=True,
        outcome_number=1,
    )
    assert cont["schema_version"] == harness.CONTINUATION_RECEIPT_SCHEMA
    assert cont["status"] == "CONTINUATION_PASS"
    assert cont["account_continuity"] is True
    assert cont["closing_balance_carried"] is True
    assert cont["same_seat"] is True
    assert cont["parent_completion"] is False
    assert cont["completion_claim_allowed"] is False
    assert cont["outcome_proof_class"] == "SYNTHETIC_FIXTURE_OUTCOME"
    assert cont["details"]["period_1"]["settled"]["statement_result"] == "HIT"
    # Synthetic HIT still must not green parent completion.
    assert cont["details"]["period_1"]["settled"].get("parent_complete") is not True


def test_owner_vertical_full_synthetic(tmp_path: Path) -> None:
    receipt = harness.run_owner_invoked_vertical(
        work_root=tmp_path / "full",
        mode="full_synthetic",
    )
    assert receipt["schema_version"] == harness.VERTICAL_RECEIPT_SCHEMA
    assert receipt["status"] == "PASS"
    assert receipt["role_fitness"] is False
    assert receipt["parent_completion"] is False
    assert receipt["completion_claim_allowed"] is False
    assert receipt["outcome_proof_class"] == "SYNTHETIC_FIXTURE_OUTCOME"
    assert receipt["pre_outcome"]["status"] == "PRE_OUTCOME_PASS"
    assert receipt["continuation"]["status"] == "CONTINUATION_PASS"


def test_negative_suite_all_pass(tmp_path: Path) -> None:
    suite = harness.run_negatives_suite(tmp_path / "negatives")
    assert suite["status"] == "PASS", suite
    expected = {
        "future_peek",
        "late_freeze",
        "missing_tool_evidence",
        "no_revise_after_failure",
        "forged_resume",
        "unbound_transcript",
        "transcript_without_raw_session_mcp",
        "mock_protocol_pin_formal",
        "worker_controlled_disposition",
        "fake_owner_fields",
        "selective_settlement",
        "recapitalization",
        "stale_portfolio_head",
        "science_account_cross_green",
        "rq008_backfill",
        "synthetic_hit_parent_completion",
        "fixture_glued_to_live_paths",
        "synthetic_profit_promotion",
    }
    assert set(suite["cases"]) == expected
    assert all(v == "PASS" for v in suite["cases"].values())
    assert suite["parent_completion"] is False
    assert suite["completion_claim_allowed"] is False


def test_acceptance_receipt_schema_document() -> None:
    schema = harness.acceptance_receipt_schema()
    assert schema["integrated_receipt_schema"] == harness.RECEIPT_SCHEMA
    assert schema["pre_outcome_receipt_schema"] == harness.PRE_OUTCOME_RECEIPT_SCHEMA
    assert schema["continuation_receipt_schema"] == harness.CONTINUATION_RECEIPT_SCHEMA
    assert schema["scientist_proof_class"] == harness.PROOF_NATIVE_SESSION_MCP
    assert schema["completion_claim_allowed"] is False
    assert schema["parent_completion"] is False
    assert "pre_outcome_freeze" in schema["order"]
    assert "external_outcome" in schema["order"]
    assert "owner-vertical" in schema["first_live_episode_command"]


def test_cli_both_modes(tmp_path: Path) -> None:
    code = harness.main(
        [
            "--work-root",
            str(tmp_path / "cli"),
            "--mode",
            "both",
            "--receipt-out",
            str(tmp_path / "cli-receipt.json"),
        ]
    )
    assert code == 0
    receipt = json.loads((tmp_path / "cli-receipt.json").read_text(encoding="utf-8"))
    assert receipt["integrated"]["status"] == "PASS"
    assert receipt["integrated"]["role_fitness"] is False
    assert receipt["integrated"]["genuine_role_fitness"] is False
    assert receipt["integrated"]["account_continuity"] is True
    assert receipt["integrated"]["proof_classes"]["scientist"] == harness.PROOF_NATIVE_SESSION_MCP
    assert receipt["negatives"]["status"] == "PASS"
    assert receipt["parent_completion"] is False
    assert "first_live_episode_command" in receipt


def test_cli_owner_vertical_pre_outcome(tmp_path: Path) -> None:
    code = harness.main(
        [
            "owner-vertical",
            "--work-root",
            str(tmp_path / "ov"),
            "--mode",
            "pre_outcome",
            "--receipt-out",
            str(tmp_path / "ov-receipt.json"),
        ]
    )
    assert code == 0
    receipt = json.loads((tmp_path / "ov-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "PRE_OUTCOME_PASS"
    assert receipt["parent_completion"] is False
    assert receipt["awaiting_external_outcome"] is True


def test_cli_print_schema(tmp_path: Path) -> None:
    code = harness.main(
        [
            "print-schema",
            "--receipt-out",
            str(tmp_path / "schema.json"),
        ]
    )
    assert code == 0
    schema = json.loads((tmp_path / "schema.json").read_text(encoding="utf-8"))
    assert schema["scientist_proof_class"] == harness.PROOF_NATIVE_SESSION_MCP
    assert schema["parent_completion"] is False
    assert "--scientist-evidence" in schema["first_live_episode_command"]


def test_consume_native_receipt_refuses_fixture_glue(tmp_path: Path) -> None:
    """Live path hashes alone must not green scientist shape via synthetic fixture."""

    fixture = harness._minimal_scientist_evidence()
    session = tmp_path / "grok-session.json"
    mcp = tmp_path / "mcp-events.jsonl"
    session.write_text(fixture["raw_session_artifact"]["content_utf8"], encoding="utf-8")
    mcp.write_text(fixture["raw_mcp_artifacts"][0]["content_utf8"], encoding="utf-8")
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="scientist-evidence|fixture|refusing"):
        harness.consume_native_episode_receipt(
            session_artifact=session,
            mcp_events=mcp,
            scientist_evidence_path=None,
        )


def test_consume_native_receipt_binds_paths(tmp_path: Path) -> None:
    """Minimum interface: structured evidence + path-hashed session/MCP."""

    fixture = harness._minimal_scientist_evidence()
    session = tmp_path / "grok-session.json"
    mcp = tmp_path / "mcp-events.jsonl"
    evidence_path = tmp_path / "scientist-evidence.json"
    session.write_text(fixture["raw_session_artifact"]["content_utf8"], encoding="utf-8")
    mcp.write_text(fixture["raw_mcp_artifacts"][0]["content_utf8"], encoding="utf-8")
    # Strip inline raw bytes; native paths must re-bind.
    structured = {k: v for k, v in fixture.items() if k not in {"raw_session_artifact", "raw_mcp_artifacts"}}
    evidence_path.write_text(json.dumps(structured, sort_keys=True), encoding="utf-8")
    bound = harness.consume_native_episode_receipt(
        session_artifact=session,
        mcp_events=mcp,
        scientist_evidence_path=evidence_path,
    )
    out = harness.validate_scientist_episode_evidence(bound)
    assert out["scientist_evidence_shape_ok"] is True
    assert out["native_session_mcp_bound"] is True
    assert out["genuine_role_fitness"] is False
    assert bound["raw_session_artifact"]["path"] == str(session)
    assert bound["raw_mcp_artifacts"][0]["path"] == str(mcp)


def test_negative_rawless_forged_owner_rq008_late_freeze_profit() -> None:
    """Focused negative attacks required by the vertical-reduction package."""

    harness.negative_transcript_without_raw_session_mcp()
    harness.negative_fake_owner_fields()
    harness.negative_rq008_backfill()
    harness.negative_late_freeze_protocol_pin()
    harness.negative_synthetic_profit_promotion()


def test_two_owner_commands_united_not_live_runner() -> None:
    """Exactly two Owner commands; fat shadow live_runner is not the product path."""

    cmds = harness.two_owner_commands()
    assert "owner-vertical" in cmds["pre_outcome"]
    assert "pre_outcome" in cmds["pre_outcome"]
    assert "owner-vertical" in cmds["post_outcome"]
    assert "continue_outcome" in cmds["post_outcome"]
    assert "live_runner" not in cmds["pre_outcome"]
    assert "live_runner" not in cmds["post_outcome"]
    assert "shadow_lifecycle.live_runner" not in cmds["pre_outcome"]
    audit = harness.self_audit_hidden_human_burden()
    assert audit["completion_claim_allowed"] is False
    assert audit["hidden_technical_burden_returned_to_human"] is False
    assert audit["retired_duplicate_stack"] == harness.RETIRED_LIVE_RUNNER_MODULE
    assert "consume_native_episode_receipt" in audit["native_receipt_interface"]
    # Product tree must not ship the duplicate 1.3k-line runner.
    live_runner = (
        Path(__file__).resolve().parents[1]
        / "xinao_discovery"
        / "src"
        / "xinao"
        / "shadow_lifecycle"
        / "live_runner.py"
    )
    assert not live_runner.is_file()


def test_science_no_action_cannot_substitute_account() -> None:
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="substituted for account"):
        harness.validate_candidate_and_owner_disposition(
            {
                "science_decision": {
                    "identity": "POLICY_NO_ACTION",
                    "science_decision_ref": "s1",
                },
                "account_decision": {"identity": "POLICY_NO_ACTION"},
                "owner_disposition": {
                    "owner_role": "codex",
                    "decision": "ABSORB_NO_ACTION",
                    "disposition_source": "worker_fixture",
                },
            }
        )
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="substituted for account"):
        harness.validate_candidate_and_owner_disposition(
            {
                "science_decision": {
                    "identity": "POLICY_NO_ACTION",
                    "science_decision_ref": "s1",
                },
                "account_decision": {
                    "identity": "RESEARCHER_ACCOUNT_NO_ACTION",
                    "derived_from_science_policy_no_action": True,
                    "rule_ref": "special-number-rule.v1",
                    "odds_version_ref": "odds.special-number.20260731.v1",
                },
                "owner_disposition": {
                    "owner_role": "codex",
                    "decision": "ABSORB_NO_ACTION",
                    "disposition_source": "worker_fixture",
                },
            }
        )


def test_reject_synthetic_outcome_as_live() -> None:
    with pytest.raises(harness.RoleFitnessAcceptanceError, match="synthetic.*live"):
        harness.reject_synthetic_outcome_as_live(
            {
                "outcome_ref": "o1",
                "source_ref": "synthetic-harness-fixture-only",
                "target_ref": "draw.t",
                "actual_special_number": 1,
                "observed_at": "2026-08-01T09:00:00+00:00",
                "verified": True,
            }
        )


def test_live_continue_stops_without_fabricating_next_period(tmp_path: Path) -> None:
    """External outcome path: settle-all/replay/feedback then stop (no period-2 mint)."""

    work = tmp_path / "live-cont"
    pre = harness.run_owner_invoked_vertical(work_root=work, mode="pre_outcome")
    assert pre["status"] == "PRE_OUTCOME_PASS"
    portfolio_root = Path(pre["details"]["portfolio_root"])
    open_1 = datetime(2026, 8, 1, 8, tzinfo=UTC)
    outcome = harness.build_outcome(
        work / "independent-outcome.json",
        open_at=open_1,
        period=1,
        number=1,
        source_ref="independent-external-observation",
    )
    # Mark verified for live gate (OutcomeObservation may already require it).
    body = json.loads(outcome.read_text(encoding="utf-8"))
    body["verified"] = True
    outcome.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")

    cont = harness.run_owner_invoked_vertical(
        work_root=work,
        mode="continue_outcome",
        pre_outcome_receipt=pre,
        external_outcome_path=outcome,
    )
    assert cont["status"] == "CONTINUATION_PASS"
    assert cont["live_single_period_stop"] is True
    assert cont["stopped_without_fabricating_next_period"] is True
    assert cont["same_seat"] is True
    assert cont["account_continuity"] is True
    assert cont["parent_completion"] is False
    assert cont["completion_claim_allowed"] is False
    assert cont["outcome_proof_class"] == harness.PROOF_FUTURE_OUTCOME
    assert cont["details"]["period_2"] is None
    assert not (portfolio_root / "periods" / "0002").exists()
    assert cont["details"]["inspect"]["next_action"] == "portfolio-freeze"

    # Synthetic presented as live external outcome must fail closed.
    synth = harness.build_outcome(
        work / "synthetic-as-live.json",
        open_at=open_1,
        period=1,
        number=1,
        source_ref="synthetic-harness-fixture-only",
    )
    work2 = tmp_path / "live-cont-synth"
    pre2 = harness.run_owner_invoked_vertical(work_root=work2, mode="pre_outcome")
    cont2 = harness.run_owner_invoked_vertical(
        work_root=work2,
        mode="continue_outcome",
        pre_outcome_receipt=pre2,
        external_outcome_path=synth,
    )
    assert cont2["status"] == "FAIL"
    assert any("synthetic" in f.lower() for f in cont2["failures"])
