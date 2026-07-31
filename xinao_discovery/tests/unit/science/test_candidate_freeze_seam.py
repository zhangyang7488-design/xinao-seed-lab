"""Attack-focused tests for candidate pool → disposition → freeze → feedback seam.

Includes counterexamples that must fail against the pre-fix authority theater
(sibling authentic, outcome smuggle, forged priors, partial CAS poison, etc.).
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xinao.science.candidate_pool import (
    CandidatePoolError,
    ingest_verified_research_result,
    load_pool_entry,
    pool_entry_path,
    pool_receipt_path,
    pool_result_bytes_path,
)
from xinao.science.freeze_adapter import (
    RESEARCH_BINDING_REF_PREFIX,
    FreezeAdapterError,
    apply_freeze_from_disposition,
    assert_no_control_plane_imports,
    build_freeze_request_from_disposition,
    extract_research_binding_hash_from_frozen,
    load_research_binding,
)
from xinao.science.owner_disposition import (
    CODEX_OWNER_CHANNEL_SOURCE,
    DISPOSITION_MARKER,
    DISPOSITION_SCHEMA_VERSION,
    OWNER_CHANNEL_AUTHORITY_UNPROVEN,
    SCIENCE_RETAIN_FOR_SHADOW,
    OwnerDispositionError,
    disposition_cas_path,
    encode_disposition_bytes,
    load_and_verify_disposition,
    parse_disposition_json_strict,
    raw_sha256,
    validate_disposition_payload,
    write_owner_disposition_artifact,
)
from xinao.science.research_feedback_pack import (
    ResearchFeedbackPackError,
    emit_research_feedback_pack,
    reject_pre_outcome_emit,
)
from xinao.science.researcher_result_adapter import (
    CONTAINER_RESULT_SCHEMA,
    PRODUCTION_SUCCESS_RECEIPT_KEYS,
    PRODUCTION_SUCCESS_RESULT_KEYS,
    RESEARCH_CANDIDATE_SCHEMA,
)
from xinao.science.researcher_result_adapter import (
    raw_sha256 as result_raw_sha256,
)
from xinao.shadow_lifecycle import (
    FeedbackKind,
    feedback_portfolio_period,
    init_portfolio,
    settle_portfolio_period,
)
from xinao.shadow_lifecycle.store import detect_phase, load_frozen, period_directory

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

OPEN_AT = datetime(2026, 8, 1, 8, tzinfo=UTC)
CUTOFF = OPEN_AT - timedelta(minutes=10)
FROZEN_AT = OPEN_AT - timedelta(minutes=6)
DEADLINE = OPEN_AT - timedelta(minutes=5)


def _candidate(**overrides: Any) -> dict[str, Any]:
    payload = {
        "schema_version": RESEARCH_CANDIDATE_SCHEMA,
        "status": "CANDIDATE_READY",
        "research_question": "What bounded mechanism is supported by the sealed materials?",
        "as_of": AS_OF,
        "material_bundle_id": MATERIAL_BUNDLE_ID,
        "material_refs_used": [{"material_id": MATERIAL_ID, "sha256": MATERIAL_DIGEST}],
        "summary": "Candidate-only research product; prose says buy 17 but that is not a ticket.",
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
    return {
        "schema_version": "xinao.skill_research_receipt.v2",
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
        result_sha256=result_raw_sha256(result_bytes),
    )
    assert set(receipt) == PRODUCTION_SUCCESS_RECEIPT_KEYS
    return result_bytes, receipt


def _ingest(tmp_path: Path) -> tuple[Path, dict[str, Any], bytes, dict[str, Any]]:
    pool = tmp_path / "pool"
    result_bytes, receipt = _result_and_receipt()
    entry = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    return pool, entry, result_bytes, receipt


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _disposition_body(
    entry: dict[str, Any],
    *,
    account_identity: str = "ACTION",
    disposition_source: str = CODEX_OWNER_CHANNEL_SOURCE,
    selected_number: int | None = 7,
    include_executable: bool = True,
    science_disposition: str = "ADOPT",
    period_index: int = 1,
    **overrides: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": DISPOSITION_SCHEMA_VERSION,
        "disposition_marker": DISPOSITION_MARKER,
        "disposition_source": disposition_source,
        "owner_role": "codex",
        "worker_controlled": False,
        "result_sha256": entry["result_sha256"],
        "receipt_content_sha256": entry["receipt_content_sha256"],
        "pool_entry_content_hash": entry["content_hash"],
        "period_index": period_index,
        "episode_ref": "episode.disp.p1",
        "target_ref": "draw.20260801-001",
        "knowledge_cutoff": _iso(CUTOFF),
        "science_disposition": science_disposition,
        "account_identity": account_identity,
        "rationale_ref": "owner-reviewed-candidate",
    }
    if account_identity == "ACTION" and include_executable:
        body["executable_account_decision"] = {
            "panel": "B",
            "selected_number": selected_number if selected_number is not None else 7,
            "stake": "1.0000",
            "target_ref": "draw.20260801-001",
            "target_open_time": _iso(OPEN_AT),
            "freeze_deadline": _iso(DEADLINE),
            "frozen_at": _iso(FROZEN_AT),
            "knowledge_cutoff": _iso(CUTOFF),
            "odds_version_ref": "odds.special-number.20260731.v1",
            "baseline_ref": "BO0013",
            "risk_policy_ref": "shadow-risk.max-one-unit.v1",
            "rule_ref": "special-number-rule.v1",
        }
    if account_identity == "RESEARCHER_ACCOUNT_NO_ACTION":
        body["no_action_period_binding"] = {
            "target_ref": "draw.20260801-001",
            "target_open_time": _iso(OPEN_AT),
            "freeze_deadline": _iso(DEADLINE),
            "frozen_at": _iso(FROZEN_AT),
            "knowledge_cutoff": _iso(CUTOFF),
            "rule_ref": "special-number-rule.v1",
            "odds_version_ref": "odds.special-number.20260731.v1",
        }
    body.update(overrides)
    return body


def _write_disposition(owner_root: Path, body: dict[str, Any]) -> Path:
    """Content-addressed exclusive write; no self-hash field."""

    written = write_owner_disposition_artifact(
        owner_state_root=owner_root,
        payload=body,
    )
    return Path(written["disposition_path"])


def _init_portfolio(tmp_path: Path) -> Path:
    root = tmp_path / "portfolio"
    init_portfolio(
        root=root,
        seat_id="seat.freeze.seam",
        portfolio_ref="portfolio.freeze.seam",
    )
    return root


# --- Pool tests ---------------------------------------------------------------


def test_pool_ingest_owner_adopted_false(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    assert entry["owner_adopted"] is False
    assert entry["decision_map_projected"] is False
    assert entry["completion_claim_allowed"] is False
    loaded = load_pool_entry(pool, entry["result_sha256"])
    assert loaded["content_hash"] == entry["content_hash"]


def test_pool_rejects_receipt_result_hash_mismatch(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    result_bytes, receipt = _result_and_receipt()
    receipt = dict(receipt)
    receipt["result_sha256"] = "0" * 64
    with pytest.raises(CandidatePoolError, match="RESULT_RECEIPT_HASH_DRIFT"):
        ingest_verified_research_result(
            pool_root=pool,
            result_bytes=result_bytes,
            receipt=receipt,
        )


def test_pool_rejects_tampered_result_bytes(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    result_bytes, receipt = _result_and_receipt()
    tampered = result_bytes + b" "
    with pytest.raises(CandidatePoolError, match="RESULT_RECEIPT_HASH_DRIFT"):
        ingest_verified_research_result(
            pool_root=pool,
            result_bytes=tampered,
            receipt=receipt,
        )


def test_pool_cas_no_overwrite_different_bytes(tmp_path: Path) -> None:
    pool, entry, result_bytes, receipt = _ingest(tmp_path)
    entry_path = pool_entry_path(pool, entry["result_sha256"])
    # Idempotent same content is OK.
    again = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    assert again["content_hash"] == entry["content_hash"]

    # Tampered seal on existing CAS path must fail closed on load.
    corrupted = dict(entry)
    corrupted["run_id"] = "mutated-run"
    corrupted.pop("content_hash", None)
    entry_path.write_text(
        json.dumps({**corrupted, "content_hash": "f" * 64}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CandidatePoolError, match="POOL_ENTRY_SEAL_INVALID"):
        load_pool_entry(pool, entry["result_sha256"])

    # Exclusive create must refuse overwrite of existing result blob path.
    alt_path = pool_result_bytes_path(pool, entry["result_sha256"])
    from xinao.science.candidate_pool import _write_new_bytes

    with pytest.raises(CandidatePoolError, match="POOL_CAS_EXCLUSIVE_CREATE_REJECTED"):
        _write_new_bytes(alt_path, b"different")


def test_pool_idempotent_same_bytes(tmp_path: Path) -> None:
    pool, entry, result_bytes, receipt = _ingest(tmp_path)
    again = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    assert again == entry


def test_pool_cas_partial_same_bytes_recovers(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    result_bytes, receipt = _result_and_receipt()
    # First compute what the full ingest would write, then simulate crash after result blob.
    entry = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    # Tear down to partial: keep only result blob.
    pool_entry_path(pool, entry["result_sha256"]).unlink()
    pool_receipt_path(pool, entry["result_sha256"]).unlink()
    assert pool_result_bytes_path(pool, entry["result_sha256"]).is_file()
    assert not pool_entry_path(pool, entry["result_sha256"]).is_file()

    recovered = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    assert recovered == entry
    assert pool_entry_path(pool, entry["result_sha256"]).is_file()
    assert pool_receipt_path(pool, entry["result_sha256"]).is_file()


def test_pool_cas_partial_conflict_fails_closed(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    result_bytes, receipt = _result_and_receipt()
    entry = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    # Leave only a conflicting result blob with same path but different bytes is impossible
    # for same hash; simulate partial with different receipt bytes for same result hash path.
    pool_entry_path(pool, entry["result_sha256"]).unlink()
    receipt_path = pool_receipt_path(pool, entry["result_sha256"])
    # Poison receipt with different bytes while keeping path (same result_sha256 identity).
    receipt_path.write_bytes(b'{"poison": true}\n')

    with pytest.raises(CandidatePoolError, match="POOL_CAS_CONTENT_CONFLICT"):
        ingest_verified_research_result(
            pool_root=pool,
            result_bytes=result_bytes,
            receipt=receipt,
        )
    # Unknown partial not deleted.
    assert receipt_path.is_file()
    assert receipt_path.read_bytes() == b'{"poison": true}\n'


# --- Disposition tests --------------------------------------------------------


def test_disposition_worker_fields_not_authentic(tmp_path: Path) -> None:
    _pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry, disposition_source="worker_fixture")
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_SOURCE_NOT_OWNER_CHANNEL"):
        write_owner_disposition_artifact(owner_state_root=owner, payload=body)


def test_disposition_owner_role_codex_text_not_sufficient(tmp_path: Path) -> None:
    _pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry, disposition_source="mock")
    body["owner_role"] = "codex"
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_SOURCE_NOT_OWNER_CHANNEL"):
        write_owner_disposition_artifact(owner_state_root=owner, payload=body)


def test_sibling_worker_dirs_do_not_self_certify_authentic(tmp_path: Path) -> None:
    """CE1: any sibling paths + codex_owner_channel must NOT mint authentic=True."""

    worker_ws = tmp_path / "worker_ws"
    pool = worker_ws / "pool"
    owner = worker_ws / "owner_state_root"
    owner.mkdir(parents=True)
    result_bytes, receipt = _result_and_receipt()
    entry = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    path = _write_disposition(owner, _disposition_body(entry))
    verified = load_and_verify_disposition(
        disposition_path=path,
        owner_state_root=owner,
        pool_root=pool,
    )
    assert verified["owner_disposition_authentic"] is False
    assert verified["owner_channel_authority"] == OWNER_CHANNEL_AUTHORITY_UNPROVEN
    assert verified["path_separated_from_pool"] is True
    assert verified["physical_owner_write_isolation_verified"] is False
    assert verified.get("physical_owner_write_isolation") in (None, False)


def test_disposition_not_under_owner_root(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    body = _disposition_body(entry)
    path = _write_disposition(elsewhere, body)
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_NOT_UNDER_OWNER_ROOT"):
        load_and_verify_disposition(
            disposition_path=path,
            owner_state_root=owner,
            pool_root=pool,
        )


def test_disposition_owner_root_must_separate_from_pool(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    body = _disposition_body(entry)
    with pytest.raises(
        OwnerDispositionError,
        match=r"OWNER_ROOT_POOL_NOT_SEPARATED|NESTED",
    ):
        write_owner_disposition_artifact(
            owner_state_root=pool,
            payload=body,
            pool_root=pool,
        )


def test_disposition_single_raw_hash_mode_no_self_field(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry)
    body["owner_artifact_sha256"] = "a" * 64
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_SELF_HASH_FORBIDDEN"):
        write_owner_disposition_artifact(owner_state_root=owner, payload=body)

    path = _write_disposition(owner, _disposition_body(entry))
    verified = load_and_verify_disposition(
        disposition_path=path,
        owner_state_root=owner,
        pool_root=pool,
    )
    expected = raw_sha256(path.read_bytes())
    assert verified["owner_artifact_sha256"] == expected
    assert path == disposition_cas_path(owner, expected)
    assert "owner_artifact_sha256" not in json.loads(path.read_text(encoding="utf-8"))


def test_disposition_duplicate_json_keys_rejected(tmp_path: Path) -> None:
    raw = b'{"a": 1, "a": 2}\n'
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_JSON_DUPLICATE_KEY"):
        parse_disposition_json_strict(raw)


def test_disposition_outcome_and_unknown_fields_rejected(tmp_path: Path) -> None:
    _, entry, _, _ = _ingest(tmp_path)
    body = _disposition_body(entry)
    body["outcome"] = {"actual_special_number": 1}
    with pytest.raises(OwnerDispositionError, match=r"DISPOSITION_UNKNOWN_FIELDS|OUTCOME"):
        validate_disposition_payload(body, pool_entry=entry)

    body2 = _disposition_body(entry)
    body2["executable_account_decision"]["actual_special_number"] = 7
    with pytest.raises(
        OwnerDispositionError,
        match=r"EXECUTABLE_DECISION_UNKNOWN_FIELDS|OUTCOME",
    ):
        validate_disposition_payload(body2, pool_entry=entry)

    body3 = _disposition_body(entry, account_identity="RESEARCHER_ACCOUNT_NO_ACTION")
    body3["no_action_period_binding"]["settlement"] = {"pnl": "1.0000"}
    with pytest.raises(
        OwnerDispositionError,
        match=r"NO_ACTION_BINDING_UNKNOWN_FIELDS|OUTCOME",
    ):
        validate_disposition_payload(body3, pool_entry=entry)

    # Nested outcome in rationale-shaped unknown prose bag still fails closed.
    body4 = _disposition_body(entry)
    body4["future_outcome"] = {"peeked_special_number": 3}
    with pytest.raises(OwnerDispositionError, match=r"DISPOSITION_UNKNOWN_FIELDS|OUTCOME"):
        validate_disposition_payload(body4, pool_entry=entry)


def test_stake_nan_inf_exponent_scale_rejected(tmp_path: Path) -> None:
    _, entry, _, _ = _ingest(tmp_path)
    for bad in ("NaN", "Infinity", "inf", "1e10", "1.00001", "-1.0000", "0.0000"):
        body = _disposition_body(entry)
        body["executable_account_decision"]["stake"] = bad
        with pytest.raises(OwnerDispositionError, match="EXECUTABLE_STAKE_INVALID"):
            validate_disposition_payload(body, pool_entry=entry)


def test_reject_plus_action_matrix_and_retain_for_shadow(tmp_path: Path) -> None:
    _, entry, _, _ = _ingest(tmp_path)
    for science in ("REJECT", "ABSORB_NO_ACTION", "DEFER"):
        body = _disposition_body(entry, science_disposition=science, account_identity="ACTION")
        with pytest.raises(OwnerDispositionError, match="SCIENCE_ACCOUNT_MATRIX_VIOLATION"):
            validate_disposition_payload(body, pool_entry=entry)

    # Positive: RETAIN_FOR_SHADOW + ACTION is explicit shadow production without science adopt.
    ok = _disposition_body(
        entry,
        science_disposition=SCIENCE_RETAIN_FOR_SHADOW,
        account_identity="ACTION",
    )
    normalized = validate_disposition_payload(ok, pool_entry=entry)
    assert normalized["science_disposition"] == SCIENCE_RETAIN_FOR_SHADOW
    assert normalized["account_identity"] == "ACTION"
    assert normalized["science_identity"] == "SCIENCE_CANDIDATE"


def test_action_requires_executable_not_prose(tmp_path: Path) -> None:
    _pool, entry, _, _ = _ingest(tmp_path)
    body = _disposition_body(entry, account_identity="ACTION", include_executable=False)
    with pytest.raises(OwnerDispositionError, match="ACTION_REQUIRES_EXECUTABLE_DECISION"):
        validate_disposition_payload(body, pool_entry=entry)


def test_no_action_must_not_carry_ticket(tmp_path: Path) -> None:
    _, entry, _, _ = _ingest(tmp_path)
    body = _disposition_body(entry, account_identity="RESEARCHER_ACCOUNT_NO_ACTION")
    body["executable_account_decision"] = {
        "panel": "A",
        "selected_number": 1,
        "stake": "1.0000",
        "target_ref": "draw.20260801-001",
        "target_open_time": _iso(OPEN_AT),
        "freeze_deadline": _iso(DEADLINE),
        "frozen_at": _iso(FROZEN_AT),
        "knowledge_cutoff": _iso(CUTOFF),
        "odds_version_ref": "odds.special-number.20260731.v1",
        "baseline_ref": "BO0001",
        "risk_policy_ref": "shadow-risk.max-one-unit.v1",
        "rule_ref": "special-number-rule.v1",
    }
    with pytest.raises(OwnerDispositionError, match="NO_ACTION_MUST_NOT_CARRY_EXECUTABLE"):
        validate_disposition_payload(body, pool_entry=entry)


def test_period_account_identity_required(tmp_path: Path) -> None:
    _, entry, _, _ = _ingest(tmp_path)
    body = _disposition_body(entry)
    body["account_identity"] = "MAYBE_LATER"
    with pytest.raises(OwnerDispositionError, match="PERIOD_ACCOUNT_IDENTITY_REQUIRED"):
        validate_disposition_payload(body, pool_entry=entry)


# --- Freeze adapter tests -----------------------------------------------------


def test_decision_freeze_calls_real_shadow_store(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(owner, _disposition_body(entry, selected_number=7))
    portfolio = _init_portfolio(tmp_path)

    result = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    assert result["ok"] is True
    assert result["phase"] == "FROZEN"
    assert result["trusted_time_proof"] is False
    assert result["auto_next_period"] is False
    assert result["auto_settle"] is False
    assert result["bound_result_sha256"] == entry["result_sha256"]
    assert result["owner_disposition_authentic"] is False
    assert result["owner_channel_authority"] == OWNER_CHANNEL_AUTHORITY_UNPROVEN
    assert result["physical_owner_write_isolation_verified"] is False

    period_root = period_directory(portfolio, 1)
    assert detect_phase(period_root).value == "FROZEN"
    frozen = load_frozen(period_root)
    assert frozen.content_hash == result["frozen_episode_hash"]
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 7
    assert frozen.science_decision.candidate_ref == entry["policy_ref"]
    binding_hash = extract_research_binding_hash_from_frozen(frozen)
    assert frozen.science_decision.science_decision_ref == (
        f"{RESEARCH_BINDING_REF_PREFIX}{binding_hash}"
    )
    assert frozen.account_decision.account_decision_ref == (
        f"{RESEARCH_BINDING_REF_PREFIX}{binding_hash}"
    )
    # Binding token is inside fields covered by frozen.content_hash.
    canonical = frozen.canonical_content()
    assert (
        f"{RESEARCH_BINDING_REF_PREFIX}{binding_hash}"
        == canonical["science_decision"]["science_decision_ref"]
    )
    assert (
        f"{RESEARCH_BINDING_REF_PREFIX}{binding_hash}"
        == canonical["account_decision"]["account_decision_ref"]
    )
    assert frozen.content_hash == frozen.compute_content_hash()
    side = load_research_binding(portfolio, binding_hash)
    assert side["result_sha256"] == entry["result_sha256"]
    assert side["owner_artifact_sha256"] == result["bound_owner_artifact_sha256"]


def test_period_99_cannot_freeze_portfolio_period_1(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(owner, _disposition_body(entry, period_index=99))
    portfolio = _init_portfolio(tmp_path)
    with pytest.raises(FreezeAdapterError, match="FREEZE_PERIOD_MISMATCH"):
        apply_freeze_from_disposition(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
        )


def test_freeze_adapter_rejects_worker_disposition(tmp_path: Path) -> None:
    _pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    # write_owner rejects non-channel source at write time for closed schema.
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_SOURCE_NOT_OWNER_CHANNEL"):
        _write_disposition(owner, _disposition_body(entry, disposition_source="worker"))


def test_no_prose_to_selected_number(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    body = _disposition_body(entry, include_executable=False)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(owner, body)
    portfolio = _init_portfolio(tmp_path)
    with pytest.raises(FreezeAdapterError, match="ACTION_REQUIRES_EXECUTABLE"):
        apply_freeze_from_disposition(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
        )


def test_freeze_request_with_outcome_rejected(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    verified = load_and_verify_disposition(
        disposition_path=_write_disposition(owner, _disposition_body(entry)),
        owner_state_root=owner,
        pool_root=pool,
    )
    request = build_freeze_request_from_disposition(
        pool_entry=verified["pool_entry"],
        disposition=verified["disposition"],
        owner_artifact_sha256=str(verified["owner_artifact_sha256"]),
        research_binding_sha256="ab" * 32,
    )
    request["outcome"] = {"actual_special_number": 1}
    with pytest.raises(FreezeAdapterError, match="FREEZE_NO_PEEK"):
        from xinao.science.freeze_adapter import _no_peek_guard

        _no_peek_guard(request)


def test_no_action_freeze_zero_stake(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(
        owner,
        _disposition_body(entry, account_identity="RESEARCHER_ACCOUNT_NO_ACTION"),
    )
    portfolio = _init_portfolio(tmp_path)
    result = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    assert result["account_identity"] == "RESEARCHER_ACCOUNT_NO_ACTION"
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is None
    assert frozen.account_decision.stake == "0.0000"
    # NO_ACTION also seals binding into both decision refs.
    binding_hash = extract_research_binding_hash_from_frozen(frozen)
    assert binding_hash == result["research_binding_sha256"]


def test_retain_for_shadow_action_freezes(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(
        owner,
        _disposition_body(
            entry,
            science_disposition=SCIENCE_RETAIN_FOR_SHADOW,
            account_identity="ACTION",
            selected_number=9,
        ),
    )
    portfolio = _init_portfolio(tmp_path)
    result = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    assert result["ok"] is True
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 9
    assert frozen.science_decision.identity.value == "SCIENCE_CANDIDATE"
    side = load_research_binding(portfolio, result["research_binding_sha256"])
    assert side["science_disposition"] == SCIENCE_RETAIN_FOR_SHADOW
    assert side["scientific_promotion"] is False


def test_no_temporal_goal_in_freeze_adapter() -> None:
    assert_no_control_plane_imports()
    import ast

    import xinao.science.freeze_adapter as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "temporalio" not in imported
    assert "temporal" not in imported


def test_file_freeze_trusted_time_proof_false(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(owner, _disposition_body(entry))
    portfolio = _init_portfolio(tmp_path)
    result = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    assert result["trusted_time_proof"] is False
    assert result["consumer_result"].get("trusted_time_proof") is False


# --- Feedback pack tests ------------------------------------------------------


def _freeze_settle_feedback(tmp_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(owner, _disposition_body(entry, selected_number=1))
    portfolio = _init_portfolio(tmp_path)
    freeze = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(
        json.dumps(
            {
                "outcome_ref": "outcome.portfolio.p1",
                "source_ref": "synthetic-test-fixture-only",
                "target_ref": "draw.20260801-001",
                "actual_special_number": 1,
                "observed_at": (OPEN_AT + timedelta(hours=1)).isoformat(),
                "verified": True,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    settle_portfolio_period(root=portfolio, outcome_path=outcome_path)
    feedback_portfolio_period(
        root=portfolio,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="CONTINUE_TO_NEXT_PROSPECTIVE_PERIOD",
    )
    return portfolio, entry, freeze


def test_feedback_pack_scientific_promotion_false(tmp_path: Path) -> None:
    portfolio, entry, freeze = _freeze_settle_feedback(tmp_path)
    emitted = emit_research_feedback_pack(
        portfolio_root=portfolio,
        period_index=1,
    )
    assert emitted["scientific_promotion"] is False
    assert emitted["pack"]["scientific_promotion"] is False
    assert emitted["future_outcome_access"] is False
    assert emitted["auto_start_next_research"] is False
    assert emitted["auto_next_period_freeze"] is False
    assert emitted["pack"]["public_outcome"]["actual_special_number"] == 1
    assert emitted["pack"]["prior_result_sha256"] == entry["result_sha256"]
    assert emitted["pack"]["prior_research_binding_sha256"] == freeze["research_binding_sha256"]


def test_binding_survives_feedback_via_frozen_and_side_object(tmp_path: Path) -> None:
    portfolio, entry, freeze = _freeze_settle_feedback(tmp_path)
    # After account feedback, period receipt bindings may be wiped; frozen must still hold.
    period_root = period_directory(portfolio, 1)
    frozen = load_frozen(period_root)
    binding_hash = extract_research_binding_hash_from_frozen(frozen)
    assert binding_hash == freeze["research_binding_sha256"]
    side = load_research_binding(portfolio, binding_hash)
    assert side["result_sha256"] == entry["result_sha256"]
    assert side["pool_entry_content_hash"] == entry["content_hash"]
    assert side["period_index"] == 1
    # content_hash of frozen covers the decision refs that embed the binding.
    dumped = frozen.model_dump(mode="json")
    assert (
        f"{RESEARCH_BINDING_REF_PREFIX}{binding_hash}"
        in (dumped["science_decision"]["science_decision_ref"])
    )
    assert (
        f"{RESEARCH_BINDING_REF_PREFIX}{binding_hash}"
        in (dumped["account_decision"]["account_decision_ref"])
    )
    assert frozen.content_hash == frozen.compute_content_hash()
    emitted = emit_research_feedback_pack(portfolio_root=portfolio, period_index=1)
    assert emitted["prior_research_binding_sha256"] == binding_hash
    assert emitted["pack"]["prior_owner_artifact_sha256"] == freeze["bound_owner_artifact_sha256"]


def test_forged_prior_hashes_cannot_emit_via_public_api(tmp_path: Path) -> None:
    portfolio, _entry, _freeze = _freeze_settle_feedback(tmp_path)
    # Public emit accepts no free prior_*; kwargs must not open a forgery channel.
    with pytest.raises(TypeError):
        emit_research_feedback_pack(  # type: ignore[call-arg]
            portfolio_root=portfolio,
            prior_result_sha256="a" * 64,
            prior_receipt_content_sha256="b" * 64,
            prior_pool_entry_content_hash="c" * 64,
            prior_policy_ref="forged.policy",
            period_index=1,
        )
    # Honest emit still works from frozen binding.
    emitted = emit_research_feedback_pack(portfolio_root=portfolio, period_index=1)
    assert emitted["pack"]["prior_result_sha256"] != "a" * 64


def test_feedback_pack_absent_pre_outcome(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(owner, _disposition_body(entry))
    portfolio = _init_portfolio(tmp_path)
    apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    with pytest.raises(ResearchFeedbackPackError, match="FEEDBACK_PACK_ABSENT_PRE_OUTCOME"):
        reject_pre_outcome_emit(portfolio_root=portfolio, period_index=1)
    with pytest.raises(ResearchFeedbackPackError, match="FEEDBACK_PACK_REQUIRES_SETTLED"):
        emit_research_feedback_pack(
            portfolio_root=portfolio,
            period_index=1,
        )


def test_no_auto_freeze_without_new_disposition(tmp_path: Path) -> None:
    portfolio, _entry, _ = _freeze_settle_feedback(tmp_path)
    emitted = emit_research_feedback_pack(
        portfolio_root=portfolio,
        period_index=1,
    )
    assert emitted["auto_next_period_freeze"] is False
    assert not period_directory(portfolio, 2).exists()


def test_happy_path_no_action_then_feedback(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(
        owner,
        _disposition_body(entry, account_identity="RESEARCHER_ACCOUNT_NO_ACTION"),
    )
    portfolio = _init_portfolio(tmp_path)
    freeze = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(
        json.dumps(
            {
                "outcome_ref": "outcome.portfolio.p1",
                "source_ref": "synthetic-test-fixture-only",
                "target_ref": "draw.20260801-001",
                "actual_special_number": 42,
                "observed_at": (OPEN_AT + timedelta(hours=1)).isoformat(),
                "verified": True,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    settle_portfolio_period(root=portfolio, outcome_path=outcome_path)
    feedback_portfolio_period(
        root=portfolio,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="NO_EXPOSURE_CONTINUE",
    )
    pack = emit_research_feedback_pack(
        portfolio_root=portfolio,
        period_index=1,
    )
    assert pack["pack"]["statement_result"] == "NO_EXPOSURE"
    assert pack["pack"]["scientific_promotion"] is False
    assert pack["prior_research_binding_sha256"] == freeze["research_binding_sha256"]


def test_action_information_set_includes_binding_hash(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    path = _write_disposition(owner, _disposition_body(entry, selected_number=3))
    portfolio = _init_portfolio(tmp_path)
    result = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is not None
    binding_hash = result["research_binding_sha256"]
    # Recompute expected information_set_hash components via public helper.
    from xinao.science.owner_disposition import disposition_information_set_hash

    expected = disposition_information_set_hash(
        result_sha256=entry["result_sha256"],
        receipt_content_sha256=entry["receipt_content_sha256"],
        target_ref="draw.20260801-001",
        research_binding_sha256=binding_hash,
    )
    assert frozen.bound_account_ticket.information_set_hash == expected


def test_encode_disposition_bytes_stable_and_cas_conflict(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry)
    first = write_owner_disposition_artifact(owner_state_root=owner, payload=body)
    second = write_owner_disposition_artifact(owner_state_root=owner, payload=body)
    assert first["owner_artifact_sha256"] == second["owner_artifact_sha256"]
    assert second["bytes_written"] is False
    # Same path different bytes: craft by writing raw to CAS path is blocked on re-write helper
    # when payload differs → different hash path; force conflict via open path reuse.
    path = Path(first["disposition_path"])
    other_body = _disposition_body(entry, selected_number=8)
    other_raw = encode_disposition_bytes(other_body)
    # Force-write different bytes under the first digest path.
    path.write_bytes(other_raw)
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_CAS_PATH_MISMATCH"):
        load_and_verify_disposition(
            disposition_path=path,
            owner_state_root=owner,
            pool_root=pool,
        )
