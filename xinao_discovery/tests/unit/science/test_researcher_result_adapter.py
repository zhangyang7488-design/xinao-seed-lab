"""Golden, drift, and consumer-binding tests for researcher result adapter."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from xinao.canonical import canonical_sha256
from xinao.science.portfolio import PolicyCandidateVersion, PolicyRole, admit_active_set
from xinao.science.researcher_result_adapter import (
    ADAPTER_MARKER,
    CONTAINER_RESULT_SCHEMA,
    PRODUCTION_SUCCESS_RECEIPT_KEYS,
    PRODUCTION_SUCCESS_RESULT_KEYS,
    RESEARCH_CANDIDATE_SCHEMA,
    SKILL_RESEARCH_RECEIPT_SCHEMA,
    ResearcherResultAdapterError,
    adapt_researcher_result_to_policy_candidate,
    raw_sha256,
    strict_json_loads,
    verify_researcher_result_against_receipt,
)

AS_OF = "2026-07-30T12:00:00.000Z"
MATERIAL_DIGEST = "cd" * 32
MATERIAL_ID = f"sha256:{MATERIAL_DIGEST}"
MATERIAL_BUNDLE_DIGEST = "ab" * 32
MATERIAL_BUNDLE_ID = f"xinao-material-bundle-sha256:{MATERIAL_BUNDLE_DIGEST}"
HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
HEX_E = "e" * 64
HEX_F = "f" * 64


def _candidate(**overrides: Any) -> dict[str, Any]:
    payload = {
        "schema_version": RESEARCH_CANDIDATE_SCHEMA,
        "status": "CANDIDATE_READY",
        "research_question": "What bounded mechanism is supported by the sealed materials?",
        "as_of": AS_OF,
        "material_bundle_id": MATERIAL_BUNDLE_ID,
        "material_refs_used": [{"material_id": MATERIAL_ID, "sha256": MATERIAL_DIGEST}],
        "summary": "Candidate-only research product; not an action policy.",
        "hypotheses": ["one hypothesis"],
        "competing_explanations": ["one competing explanation"],
        "methods": ["bounded material analysis"],
        "evidence_used": [
            {
                "material_id": MATERIAL_ID,
                "finding": "bounded finding",
                "locator": "whole file",
            }
        ],
        "counterevidence": [],
        "limitations": ["candidate evidence only"],
        "next_evidence": ["independent observation"],
    }
    payload.update(overrides)
    return payload


def _production_result(*, candidate: dict[str, Any], status: str) -> dict[str, Any]:
    """Production-shaped formal producer result object (entrypoint #159 key set)."""

    return {
        "schema_version": CONTAINER_RESULT_SCHEMA,
        "status": status,
        "reason_codes": [],
        "candidate": candidate,
        "request_sha256": HEX_A,
        "prompt_sha256": HEX_B,
        "output_schema_sha256": HEX_C,
        "material_bundle_id": MATERIAL_BUNDLE_ID,
        "material_manifest_sha256": HEX_D,
        "material_packet_sha256": HEX_E,
        "effective_prompt_sha256": HEX_F,
        "material_refs_available": [MATERIAL_ID],
        "provider": "grok",
        "requested_model": "grok-4.5",
        "provider_stop_reason": "EndTurn",
        "provider_num_turns": 1,
        "provider_session_id_present": True,
        "provider_request_id_present": True,
        # Reconciled producer formal keys (raw ids present; runtime allowlist lags).
        "provider_session_id": "session-prod-001",
        "provider_request_id": "request-prod-001",
        "provider_model_usage": {
            "grok-4.5-build": {"inputTokens": 11, "outputTokens": 7, "modelCalls": 1}
        },
        "usage": {"total_tokens": 18},
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
    }


def _production_receipt(
    *,
    candidate: dict[str, Any],
    status: str,
    result_sha256: str,
) -> dict[str, Any]:
    """Production-shaped sealed skill research receipt (pre-transport)."""

    return {
        "schema_version": SKILL_RESEARCH_RECEIPT_SCHEMA,
        "run_id": "xrr_20260730T120000_testrun01",
        "status": status,
        "candidate": copy.deepcopy(candidate),
        "reason_codes": [],
        "release_id": "xinao-researcher-release-test-001",
        "release_manifest_path": "/state/releases/test/manifest.json",
        "release_manifest_sha256": "1" * 64,
        "execution_pointer_sha256": "2" * 64,
        "execution_pointer_generation": 3,
        "execution_activation_txn_id": "act_txn_test_001",
        "skill_bundle_tree_sha256": "3" * 64,
        "package_version": "1.3.0",
        "capability_version": "1.2.0",
        # Producer pin is REQUIRED_BOOTSTRAP_PROTOCOL = 2 (JSON integer, not text).
        "required_bootstrap_protocol": 2,
        "image_id": "sha256:" + ("4" * 64),
        "container_id": "ctr_volatile_aaa",
        "container_exit_code": 0,
        "container_terminal_attestation": {
            "schema_version": "xinao.researcher_terminal_attestation.v1",
            "status": status,
            "result_sha256": result_sha256,
            "request_sha256": HEX_A,
            "observed_model_id": "grok-4.5-build",
            "observed_model_calls": 1,
        },
        "container_security": {
            "readonly_rootfs": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "network_mode": "xinao_researcher_internal",
            "pids_limit": 128,
            "memory": 2147483648,
            "nano_cpus": 2000000000,
            "privileged": False,
            "restart_policy": {"Name": "no", "MaximumRetryCount": 0},
            "tmpfs": {
                "/tmp": "rw,nosuid,nodev,size=256m,mode=1777",
                "/grok-home": "rw,nosuid,nodev,size=256m,mode=0700",
            },
            "mounts": [
                {
                    "source": "/volatile/host/input",
                    "destination": "/input",
                    "rw": False,
                }
            ],
        },
        "provider_egress": {
            "internal_network_name": "xinao_researcher_internal",
            "internal_network_id": "net_" + ("5" * 12),
            "proxy_container_id": "proxy_volatile_bbb",
            "proxy_image_id": "sha256:" + ("6" * 64),
            "proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
            "allowlist_sha256": "7" * 64,
            "proxy_config_sha256": "8" * 64,
            "live_proxy_config_sha256": "9" * 64,
            "live_seal_sha256": "0" * 64,
            "live_seal_expires_at": "2026-07-30T18:00:00.000Z",
            "posture_sha256": "a1" * 32,
            "docker_engine_observational_id": "engine_obs_volatile",
            "observation_before_create": {"fingerprint": "create-1"},
            "observation_before_start": {"fingerprint": "start-1"},
            "proxy_env_is_routing_hint_only": True,
            "dify_cross_project": False,
            "tls_interception": False,
            "provider_egress_runtime_verified": True,
            "source_provider_egress_runtime_verified": False,
            "completion_claim_allowed": False,
        },
        "container_removed": True,
        "request_sha256": HEX_A,
        "base_prompt_sha256": HEX_B,
        "output_schema_sha256": HEX_C,
        "material_bundle_id": MATERIAL_BUNDLE_ID,
        "material_manifest_path": "/state/runs/xrr/materials/manifest.json",
        "material_manifest_sha256": HEX_D,
        "material_packet_sha256": HEX_E,
        "effective_prompt_sha256": HEX_F,
        "material_source_refs": [
            {
                "material_id": MATERIAL_ID,
                "source_path": "/volatile/host/materials/note.txt",
                "sha256": MATERIAL_DIGEST,
            }
        ],
        "material_prompt_binding_verified": True,
        "material_use_claim_bound": True,
        "result_sha256": result_sha256,
        "result_path": "/state/runs/xrr/output/result.json",
        "created_at": "2026-07-30T12:01:00.000Z",
        "route_class": "scientific_researcher",
        "ordinary_worker_chain_used": False,
        "provider_evidence": {
            "stop_reason": "EndTurn",
            "num_turns": 1,
            "session_id_present": True,
            "request_id_present": True,
            "model_usage": {
                "grok-4.5-build": {"inputTokens": 11, "outputTokens": 7, "modelCalls": 1}
            },
            "usage": {"total_tokens": 18},
        },
        "auth_handle_identity_unchanged": True,
        "user_operations_required": [],
        "owner_adopted": False,
        "research_progress_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "completion_claim_allowed": False,
    }


def _result_and_receipt(
    *,
    candidate: dict[str, Any] | None = None,
    status: str = "CANDIDATE_READY",
) -> tuple[bytes, dict[str, Any]]:
    cand = candidate if candidate is not None else _candidate(status=status)
    result = _production_result(candidate=cand, status=status)
    assert set(result) == PRODUCTION_SUCCESS_RESULT_KEYS
    result_bytes = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    receipt = _production_receipt(
        candidate=cand,
        status=status,
        result_sha256=raw_sha256(result_bytes),
    )
    assert set(receipt) == PRODUCTION_SUCCESS_RECEIPT_KEYS
    return result_bytes, receipt


def test_production_fixture_key_sets_include_reconciled_provider_ids() -> None:
    result_bytes, receipt = _result_and_receipt()
    result = json.loads(result_bytes)
    assert "provider_session_id_present" in result
    assert "provider_request_id_present" in result
    assert "provider_session_id" in result
    assert "provider_request_id" in result
    assert receipt["route_class"] == "scientific_researcher"
    assert receipt["ordinary_worker_chain_used"] is False
    assert receipt["reason_codes"] == []
    assert result["reason_codes"] == []


def test_golden_verify_and_mint_is_deterministic_and_content_addressed() -> None:
    result_bytes, receipt = _result_and_receipt()
    first = adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    second = adapt_researcher_result_to_policy_candidate(result_bytes, copy.deepcopy(receipt))

    assert first == second
    assert first.content_hash is not None
    assert first.content_hash == first.compute_content_hash()
    assert first.role == PolicyRole.SUBSTANTIVE
    assert first.policy_ref == f"science.research_candidate.v2.sha256:{raw_sha256(result_bytes)}"
    assert first.decision_signature.decision_map_ref.startswith(
        "xinao.not_projected.research_candidate.v2:"
    )
    assert first.semantic_config["adapter_marker"] == ADAPTER_MARKER
    assert first.semantic_config["decision_map_projected"] is False
    assert first.semantic_config["active_set_admitted"] is False
    assert first.semantic_config["science_progress_claimed"] is False
    assert first.semantic_config["result_sha256"] == raw_sha256(result_bytes)
    assert first.semantic_config["route_class"] == "scientific_researcher"
    assert first.knowledge_cutoff == datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    accepted = PolicyCandidateVersion.model_validate(first.model_dump(mode="python"))
    assert accepted == first
    assert accepted.content_hash == first.content_hash


def test_result_hash_drift_is_rejected() -> None:
    result_bytes, receipt = _result_and_receipt()
    receipt["result_sha256"] = "0" * 64
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "RESULT_RECEIPT_HASH_DRIFT"


def test_schema_drift_on_receipt_and_candidate_is_rejected() -> None:
    result_bytes, receipt = _result_and_receipt()
    bad_receipt = copy.deepcopy(receipt)
    bad_receipt["schema_version"] = "xinao.skill_research_receipt.v1"
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, bad_receipt)
    assert err.value.reason_code == "RECEIPT_SCHEMA_DRIFT"

    drifted_candidate = _candidate(schema_version="xinao.research_candidate.v1")
    drifted_bytes, drifted_receipt = _result_and_receipt(candidate=drifted_candidate)
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(drifted_bytes, drifted_receipt)
    assert err.value.reason_code == "RESEARCH_CANDIDATE_SCHEMA_DRIFT"


def test_candidate_object_drift_between_result_and_receipt_is_rejected() -> None:
    result_bytes, receipt = _result_and_receipt()
    receipt["candidate"] = _candidate(summary="tampered summary not in result bytes")
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "RESULT_RECEIPT_CANDIDATE_DRIFT"


def test_progress_claims_are_fail_closed() -> None:
    result_bytes, receipt = _result_and_receipt()
    receipt["science_restored"] = True
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "SCIENCE_PROGRESS_CLAIM_FORBIDDEN"


def test_consumer_binding_accepts_identity_but_rejects_single_candidate_activeset() -> None:
    result_bytes, receipt = _result_and_receipt()
    policy = adapt_researcher_result_to_policy_candidate(result_bytes, receipt)

    assert PolicyCandidateVersion.model_validate(policy.model_dump(mode="python")) == policy

    with pytest.raises((ValueError, ValidationError)):
        admit_active_set(
            active_set_ref="active-set.forbidden-single.v1",
            protocol_pin_ref="protocol.synthetic.v1",
            protocol_pin_sha256="a" * 64,
            admitted_at=datetime(2026, 7, 30, 11, 0, tzinfo=UTC),
            policies=(policy,),
            residual_axes=("research-only",),
        )


def test_does_not_fabricate_decision_map_from_research_prose() -> None:
    result_bytes, receipt = _result_and_receipt()
    policy = adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    prose = " ".join(
        [
            receipt["candidate"]["summary"],
            *receipt["candidate"]["hypotheses"],
            *receipt["candidate"]["methods"],
        ]
    )
    assert prose not in policy.decision_signature.decision_map_ref
    assert policy.decision_signature.decision_map_ref == (
        f"xinao.not_projected.research_candidate.v2:{raw_sha256(result_bytes)}"
    )
    assert "selected_number" not in policy.semantic_config
    assert "stake" not in policy.semantic_config
    assert policy.decision_signature.probe_trace_hash == canonical_sha256(
        [
            "XINAO_RESEARCHER_RESULT_ADAPTER_V1",
            policy.semantic_config["result_sha256"],
            policy.semantic_config["receipt_content_sha256"],
            policy.semantic_config["candidate_content_sha256"],
            policy.semantic_config["status"],
        ]
    )


def test_verify_binding_exposes_hashes_without_mint_side_effects() -> None:
    result_bytes, receipt = _result_and_receipt()
    binding = verify_researcher_result_against_receipt(result_bytes, receipt)
    assert binding["result_sha256"] == raw_sha256(result_bytes)
    assert len(binding["receipt_content_sha256"]) == 64
    assert binding["run_id"] == receipt["run_id"]
    assert binding["status"] == "CANDIDATE_READY"


def test_malformed_nested_material_refs_and_evidence_are_rejected() -> None:
    bad_ref = _candidate(
        material_refs_used=[{"material_id": MATERIAL_ID, "sha256": MATERIAL_DIGEST, "extra": 1}]
    )
    bad_bytes, bad_receipt = _result_and_receipt(candidate=bad_ref)
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(bad_bytes, bad_receipt)
    assert err.value.reason_code == "RESEARCH_CANDIDATE_MATERIAL_REFS_INVALID"

    bad_pattern = _candidate(
        material_refs_used=[{"material_id": "not-a-material", "sha256": MATERIAL_DIGEST}]
    )
    bad_bytes, bad_receipt = _result_and_receipt(candidate=bad_pattern)
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(bad_bytes, bad_receipt)
    assert err.value.reason_code == "RESEARCH_CANDIDATE_MATERIAL_REF_PATTERN_INVALID"

    # evidence material not bound into material_refs_used
    other_digest = "11" * 32
    other_id = f"sha256:{other_digest}"
    unbound = _candidate(
        material_refs_used=[{"material_id": MATERIAL_ID, "sha256": MATERIAL_DIGEST}],
        evidence_used=[
            {"material_id": other_id, "finding": "foreign", "locator": "x"},
        ],
    )
    # material_refs_available still only has MATERIAL_ID; unknown used ref fails first if added
    bad_bytes, bad_receipt = _result_and_receipt(candidate=unbound)
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(bad_bytes, bad_receipt)
    assert err.value.reason_code == "RESEARCH_CANDIDATE_EVIDENCE_REF_UNKNOWN"

    # evidence set must equal used set (missing evidence for used ref)
    missing_evidence = _candidate(evidence_used=[])
    bad_bytes, bad_receipt = _result_and_receipt(candidate=missing_evidence)
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(bad_bytes, bad_receipt)
    assert err.value.reason_code in {
        "RESEARCH_CANDIDATE_EVIDENCE_USE_UNBOUND",
        "RESEARCH_CANDIDATE_EVIDENCE_BINDING_INVALID",
    }


def test_missing_and_unknown_result_keys_are_rejected() -> None:
    result_bytes, receipt = _result_and_receipt()
    result = json.loads(result_bytes.decode("utf-8"))
    del result["usage"]
    missing_bytes = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    receipt["result_sha256"] = raw_sha256(missing_bytes)
    receipt["candidate"] = copy.deepcopy(result["candidate"])
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(missing_bytes, receipt)
    assert err.value.reason_code == "RESULT_FIELDS_INVALID"
    assert "usage" in err.value.detail

    result = json.loads(result_bytes.decode("utf-8"))
    result["extra_unknown"] = True
    unknown_bytes = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    receipt2 = copy.deepcopy(receipt)
    receipt2["result_sha256"] = raw_sha256(unknown_bytes)
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(unknown_bytes, receipt2)
    assert err.value.reason_code == "RESULT_FIELDS_INVALID"
    assert "extra_unknown" in err.value.detail


def test_nonempty_reason_codes_are_rejected() -> None:
    result_bytes, receipt = _result_and_receipt()
    result = json.loads(result_bytes.decode("utf-8"))
    result["reason_codes"] = ["NOT_EMPTY"]
    bad_bytes = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    receipt["result_sha256"] = raw_sha256(bad_bytes)
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(bad_bytes, receipt)
    assert err.value.reason_code == "REASON_CODES_MUST_BE_EMPTY"

    result_bytes, receipt = _result_and_receipt()
    receipt["reason_codes"] = ["RECEIPT_NOT_EMPTY"]
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "REASON_CODES_MUST_BE_EMPTY"


def test_duplicate_json_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        strict_json_loads('{"a":1,"a":2}')

    # Full result bytes with duplicate top-level key must fail closed.
    result_bytes, receipt = _result_and_receipt()
    text = result_bytes.decode("utf-8").rstrip("\n")
    # Inject a second "status" key before the closing brace.
    dup = text[:-1] + ',"status":"CANDIDATE_READY"}'
    dup_bytes = (dup + "\n").encode("utf-8")
    receipt["result_sha256"] = raw_sha256(dup_bytes)
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(dup_bytes, receipt)
    assert err.value.reason_code == "RESEARCH_RESULT_JSON_INVALID"
    assert "duplicate" in err.value.detail.lower()


def test_receipt_volatility_does_not_move_policy_identity() -> None:
    result_bytes, receipt = _result_and_receipt()
    baseline = adapt_researcher_result_to_policy_candidate(result_bytes, receipt)

    volatile = copy.deepcopy(receipt)
    volatile["created_at"] = "2026-07-30T23:59:59.000Z"
    volatile["result_path"] = "/other/path/result.json"
    volatile["container_id"] = "ctr_volatile_zzz"
    volatile["container_removed"] = False
    volatile["release_manifest_path"] = "/other/release/manifest.json"
    volatile["material_manifest_path"] = "/other/materials/manifest.json"
    volatile["material_source_refs"] = [
        {
            "material_id": MATERIAL_ID,
            "source_path": "/completely/different/source.txt",
            "sha256": MATERIAL_DIGEST,
        }
    ]
    volatile["container_security"] = copy.deepcopy(receipt["container_security"])
    volatile["container_security"]["mounts"] = [
        {"source": "/other/host", "destination": "/input", "rw": False}
    ]
    volatile["provider_egress"] = copy.deepcopy(receipt["provider_egress"])
    volatile["provider_egress"]["observation_before_create"] = {"fingerprint": "create-CHANGED"}
    volatile["provider_egress"]["observation_before_start"] = {"fingerprint": "start-CHANGED"}
    volatile["provider_egress"]["live_seal_expires_at"] = "2099-01-01T00:00:00.000Z"
    volatile["provider_egress"]["live_seal_sha256"] = "f" * 64
    volatile["provider_egress"]["live_proxy_config_sha256"] = "e" * 64
    volatile["provider_egress"]["docker_engine_observational_id"] = "engine_CHANGED"
    volatile["provider_egress"]["proxy_container_id"] = "proxy_CHANGED"
    # Transport-only return fields must also be ignored for identity.
    volatile["receipt_path"] = "/tmp/returned/receipt.json"
    volatile["receipt_sha256"] = "d" * 64

    moved = adapt_researcher_result_to_policy_candidate(result_bytes, volatile)
    assert moved.policy_ref == baseline.policy_ref
    assert moved.content_hash == baseline.content_hash
    assert (
        moved.semantic_config["receipt_content_sha256"]
        == baseline.semantic_config["receipt_content_sha256"]
    )
    assert moved.decision_signature.probe_trace_hash == baseline.decision_signature.probe_trace_hash


def test_receipt_route_class_must_be_scientific_researcher() -> None:
    result_bytes, receipt = _result_and_receipt()
    receipt["route_class"] = "ordinary_worker"
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "RECEIPT_ROUTE_CLASS_INVALID"


@pytest.mark.parametrize(
    "bad_value",
    [
        True,
        False,
        "xinao.researcher_bootstrap.v2",
        "2",
        None,
        2.0,
        2.5,
        0,
        1,
        -1,
        3,
        [],
        {},
    ],
)
def test_required_bootstrap_protocol_rejects_every_value_except_exact_int_2(
    bad_value: object,
) -> None:
    result_bytes, receipt = _result_and_receipt()
    receipt["required_bootstrap_protocol"] = bad_value
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "RECEIPT_BOOTSTRAP_PROTOCOL_INVALID"


def test_missing_required_bootstrap_protocol_remains_an_exact_key_failure() -> None:
    result_bytes, receipt = _result_and_receipt()
    del receipt["required_bootstrap_protocol"]
    with pytest.raises(ResearcherResultAdapterError) as err:
        adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert err.value.reason_code == "RECEIPT_FIELDS_INVALID"
    assert "required_bootstrap_protocol" in err.value.detail


def test_rq008_live_immutable_pair_replays_with_bootstrap_int_2_portable() -> None:
    """Replay sealed real RQ008 pair from in-tree fixtures (no host absolute path).

    Retrospective E1 only: typed NO_ACTION projection stance; zero Ticket/Settlement.
    """

    from pathlib import Path

    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "rq008_live"
    result_path = fixture_dir / "result.json"
    receipt_path = fixture_dir / "receipt.json"
    pins_path = fixture_dir / "sha256_pins.json"
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    result_bytes = result_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    assert raw_sha256(result_bytes) == pins["result.json"]
    assert raw_sha256(receipt_bytes) == pins["receipt.json"]
    # Sealed Owner-run content digests (portable pin file, not a mount path).
    assert pins["result.json"] == (
        "5460a71b5db33b43a486ef2a4999b142cc0fa0cc953dfa73b4adacbb5b5d3d76"
    )
    assert pins["receipt.json"] == (
        "13812f6d75a000338bdc9ef39def8faacb2e6bae2ebba06abc38df812e06e253"
    )
    receipt = strict_json_loads(receipt_bytes.decode("utf-8"))
    assert type(receipt["required_bootstrap_protocol"]) is int
    assert receipt["required_bootstrap_protocol"] == 2
    assert receipt["result_sha256"] == pins["result.json"]
    policy = adapt_researcher_result_to_policy_candidate(result_bytes, receipt)
    assert policy.policy_ref == (
        "science.research_candidate.v2.sha256:"
        "5460a71b5db33b43a486ef2a4999b142cc0fa0cc953dfa73b4adacbb5b5d3d76"
    )
    assert policy.content_hash == policy.compute_content_hash()
    assert policy.semantic_config["completion_claim_allowed"] is False
    assert policy.semantic_config["science_progress_claimed"] is False
    assert policy.semantic_config["decision_map_projected"] is False
    assert policy.semantic_config["active_set_admitted"] is False
    assert policy.semantic_config["route_class"] == "scientific_researcher"
    assert policy.decision_signature.abstention_rule == ("NO_ACTION_MAP_UNTIL_EXPLICIT_PROJECTION")
    assert policy.decision_signature.action_support == "NOT_PROJECTED"
    # RQ008 retrospective inventory: NO_ACTION text, not a Ticket/Settlement episode.
    candidate = receipt["candidate"]
    assert "NO_ACTION" in candidate["summary"]
    assert "Ticket" not in candidate["summary"]
    assert "Settlement" not in candidate["summary"]
    assert "ticket" not in json.dumps(policy.semantic_config).lower()
    assert "settlement" not in json.dumps(policy.semantic_config).lower()
