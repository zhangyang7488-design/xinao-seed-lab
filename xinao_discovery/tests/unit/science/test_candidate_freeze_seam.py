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

from xinao.canonical import canonical_sha256
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
    build_portfolio_binding_from_shadow,
    build_research_freeze_binding,
    extract_research_binding_hash_from_frozen,
    freeze_request_evidence_path,
    load_research_binding,
    write_freeze_request,
    write_freeze_request_evidence_exclusive,
    write_research_binding_exclusive,
)
from xinao.science.owner_disposition import (
    CODEX_OWNER_CHANNEL_SOURCE,
    DISPOSITION_MARKER,
    DISPOSITION_SCHEMA_VERSION,
    OWNER_CHANNEL_AUTHORITY_UNPROVEN,
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
    freeze_portfolio_period,
    init_portfolio,
    settle_portfolio_period,
)
from xinao.shadow_lifecycle.consumer import (
    OWNER_FREEZE_AUTHORITY_MARKER,
    OWNER_FREEZE_AUTHORITY_SCHEMA,
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


def _apply_freeze(**kwargs: Any) -> dict[str, Any]:
    """apply_freeze_from_disposition with host-time test seam (pre-deadline)."""

    kwargs.setdefault("clock", lambda: FROZEN_AT)
    return apply_freeze_from_disposition(**kwargs)


def _researcher_executable_core(
    *,
    selected_number: int = 7,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    core = {
        "panel": "B",
        "selected_number": selected_number,
        "stake": "1.0000",
        "target_ref": "draw.20260801-001",
        "target_open_time": _iso(OPEN_AT),
        "freeze_deadline": _iso(DEADLINE),
        "knowledge_cutoff": _iso(CUTOFF),
        "odds_version_ref": "odds.special-number.20260731.v1",
        "baseline_ref": "BO0013",
        "risk_policy_ref": "shadow-risk.max-one-unit.v1",
        "rule_ref": "special-number-rule.v1",
    }
    core.update(overrides or {})
    return core


def _researcher_no_action_core(
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    core = {
        "target_ref": "draw.20260801-001",
        "target_open_time": _iso(OPEN_AT),
        "freeze_deadline": _iso(DEADLINE),
        "knowledge_cutoff": _iso(CUTOFF),
        "odds_version_ref": "odds.special-number.20260731.v1",
        "rule_ref": "special-number-rule.v1",
    }
    core.update(overrides or {})
    return core


def _candidate(
    *,
    researcher_selected_number: int = 7,
    include_researcher_executable: bool = True,
    decision_kind: str = "ACTION",
    researcher_executable_overrides: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
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
    if include_researcher_executable and decision_kind == "ACTION":
        payload["executable_account_decision"] = _researcher_executable_core(
            selected_number=researcher_selected_number,
            overrides=researcher_executable_overrides,
        )
    elif decision_kind == "NO_ACTION":
        payload["no_action_intent"] = _researcher_no_action_core(
            overrides=researcher_executable_overrides,
        )
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
    cand = (
        candidate
        if candidate is not None
        else _candidate(
            status=status,
            include_researcher_executable=status == "CANDIDATE_READY",
        )
    )
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


def _ingest(
    tmp_path: Path,
    *,
    selected_number: int = 7,
    include_researcher_executable: bool = True,
    decision_kind: str = "ACTION",
    researcher_executable_overrides: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any], bytes, dict[str, Any]]:
    pool = tmp_path / "pool"
    result_bytes, receipt = _result_and_receipt(
        candidate=_candidate(
            researcher_selected_number=selected_number,
            include_researcher_executable=include_researcher_executable,
            decision_kind=decision_kind,
            researcher_executable_overrides=researcher_executable_overrides,
        )
    )
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


def _write_disposition(owner_root: Path, pool_root: Path, body: dict[str, Any]) -> Path:
    """Content-addressed exclusive write; no self-hash field."""

    written = write_owner_disposition_artifact(
        owner_state_root=owner_root,
        payload=body,
        pool_root=pool_root,
    )
    return Path(written["disposition_path"])


def _init_portfolio(
    tmp_path: Path,
    *,
    name: str = "portfolio",
    seat_id: str = "seat.freeze.seam",
    portfolio_ref: str = "portfolio.freeze.seam",
) -> Path:
    root = tmp_path / name
    init_portfolio(
        root=root,
        seat_id=seat_id,
        portfolio_ref=portfolio_ref,
    )
    return root


def _attach_portfolio_binding(body: dict[str, Any], shadow_root: Path) -> dict[str, Any]:
    """Stamp closed portfolio/head identity from live inspect onto a disposition body."""

    binding = build_portfolio_binding_from_shadow(shadow_root)
    body = dict(body)
    body["portfolio_binding"] = binding
    body["period_index"] = binding["intended_next_period_index"]
    return body


def _write_portfolio_disposition(
    owner_root: Path,
    pool_root: Path,
    entry: dict[str, Any],
    shadow_root: Path,
    **overrides: Any,
) -> Path:
    body = _attach_portfolio_binding(_disposition_body(entry, **overrides), shadow_root)
    return _write_disposition(owner_root, pool_root, body)


def _manual_production_authority_chain(
    *,
    body: dict[str, Any],
    entry: dict[str, Any],
    pool: Path,
    owner: Path,
    portfolio: Path,
    binding_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Seal a caller-built, internally consistent chain for public-consumer negatives."""

    raw = encode_disposition_bytes(body)
    disposition_sha = raw_sha256(raw)
    disposition_path = disposition_cas_path(owner, disposition_sha)
    disposition_path.parent.mkdir(parents=True, exist_ok=True)
    disposition_path.write_bytes(raw)

    normalized = copy.deepcopy(body)
    normalized["science_identity"] = "SCIENCE_CANDIDATE"
    executable = normalized["executable_account_decision"]
    researcher_core = _researcher_executable_core(
        selected_number=int(executable["selected_number"]),
    )
    researcher_binding = {
        "schema_version": "xinao.researcher_action_binding.v1",
        "account_identity": "ACTION",
        "source_kind": "ONESHOT_RESEARCH_RESULT",
        "source_artifact_sha256": entry["result_sha256"],
        "source_json_path": "$.candidate.executable_account_decision",
        "decision_content_hash": canonical_sha256(researcher_core),
        "executable_content_hash": canonical_sha256(researcher_core),
        "result_sha256": entry["result_sha256"],
        "pool_entry_content_hash": entry["content_hash"],
    }
    binding_body = build_research_freeze_binding(
        pool_entry=entry,
        disposition=normalized,
        owner_artifact_sha256=disposition_sha,
        researcher_action_binding=researcher_binding,
        portfolio_binding=body["portfolio_binding"],
        freeze_action_time=FROZEN_AT,
    )
    binding_body.update(binding_overrides or {})
    binding = write_research_binding_exclusive(shadow_root=portfolio, body=binding_body)
    binding_sha = str(binding["research_binding_sha256"])
    request = build_freeze_request_from_disposition(
        pool_entry=entry,
        disposition=normalized,
        owner_artifact_sha256=disposition_sha,
        research_binding_sha256=binding_sha,
        freeze_action_time=FROZEN_AT,
    )
    authority = {
        "schema_version": OWNER_FREEZE_AUTHORITY_SCHEMA,
        "authority_marker": OWNER_FREEZE_AUTHORITY_MARKER,
        "owner_state_root": str(owner.resolve()),
        "research_pool_root": str(pool.resolve()),
        "owner_disposition_sha256": disposition_sha,
        "research_binding_sha256": binding_sha,
        "request_content_hash": request["request_content_hash"],
    }
    return request, authority


# --- Pool tests ---------------------------------------------------------------


def test_pool_ingest_owner_adopted_false(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    assert entry["owner_adopted"] is False
    assert entry["decision_map_projected"] is False
    assert entry["completion_claim_allowed"] is False
    loaded = load_pool_entry(pool, entry["result_sha256"])
    assert loaded["content_hash"] == entry["content_hash"]


def test_legacy_oneshot_cannot_be_replayed_as_live_actor_episode(tmp_path: Path) -> None:
    """Explicit Episode roots select the actor path; one-shot bytes cannot enter it."""

    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    portfolio = _init_portfolio(tmp_path)
    disposition_path = _write_portfolio_disposition(
        owner,
        pool,
        entry,
        portfolio,
    )
    with pytest.raises(OwnerDispositionError) as exc:
        load_and_verify_disposition(
            disposition_path=disposition_path,
            owner_state_root=owner,
            pool_root=pool,
            episode_root=tmp_path / "episode-reality",
            portfolio_root=portfolio,
            authority_root=tmp_path / "source-authority",
        )
    assert exc.value.reason_code == "PRODUCTION_ACTOR_EPISODE_SOURCE_KIND_REQUIRED"


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
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry, disposition_source="worker_fixture")
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_SOURCE_NOT_OWNER_CHANNEL"):
        write_owner_disposition_artifact(owner_state_root=owner, payload=body, pool_root=pool)


def test_disposition_owner_role_codex_text_not_sufficient(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    body = _disposition_body(entry, disposition_source="mock")
    body["owner_role"] = "codex"
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_SOURCE_NOT_OWNER_CHANNEL"):
        write_owner_disposition_artifact(owner_state_root=owner, payload=body, pool_root=pool)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("owner_role", "DISPOSITION_OWNER_ROLE_INVALID"),
        ("worker_controlled", "DISPOSITION_WORKER_CONTROLLED"),
    ],
)
def test_owner_claim_fields_must_be_explicit(
    tmp_path: Path,
    field: str,
    reason: str,
) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    body = _disposition_body(entry)
    body.pop(field)
    with pytest.raises(OwnerDispositionError, match=reason):
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=body,
            pool_root=pool,
        )
    assert not owner.exists()


def test_science_identity_is_derived_not_caller_controlled(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    body = _disposition_body(entry)
    body["science_identity"] = "POLICY_NO_ACTION"
    with pytest.raises(
        OwnerDispositionError,
        match="SCIENCE_IDENTITY_CALLER_OVERRIDE_FORBIDDEN",
    ):
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=body,
            pool_root=pool,
        )
    assert not owner.exists()


def test_disposition_writer_validates_and_writes_one_immutable_byte_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation after validation cannot change the bytes written to Owner CAS."""

    import xinao.science.owner_disposition as disposition_module

    pool, entry, _, _ = _ingest(tmp_path, selected_number=7)
    owner = tmp_path / "owner_snapshot"
    body = _disposition_body(entry, selected_number=7)
    original_validate = disposition_module.validate_disposition_payload

    def _validate_then_mutate(payload, *, pool_entry):  # type: ignore[no-untyped-def]
        normalized = original_validate(payload, pool_entry=pool_entry)
        body["executable_account_decision"]["selected_number"] = 49
        return normalized

    monkeypatch.setattr(
        disposition_module,
        "validate_disposition_payload",
        _validate_then_mutate,
    )
    written = disposition_module.write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=body,
        pool_root=pool,
    )
    assert body["executable_account_decision"]["selected_number"] == 49
    sealed = parse_disposition_json_strict(Path(written["disposition_path"]).read_bytes())
    assert sealed["executable_account_decision"]["selected_number"] == 7


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
    path = _write_disposition(owner, pool, _disposition_body(entry))
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
    path = _write_disposition(elsewhere, pool, body)
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
        write_owner_disposition_artifact(owner_state_root=owner, payload=body, pool_root=pool)

    path = _write_disposition(owner, pool, _disposition_body(entry))
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


def test_owner_verdict_never_rewrites_researcher_action_as_no_action(tmp_path: Path) -> None:
    _, entry, _, _ = _ingest(tmp_path)
    for science in ("REJECT", "DEFER"):
        body = _disposition_body(entry, science_disposition=science, account_identity="ACTION")
        normalized = validate_disposition_payload(body, pool_entry=entry)
        assert normalized["science_disposition"] == science
        assert normalized["account_identity"] == "ACTION"
        assert normalized["science_identity"] == "SCIENCE_CANDIDATE"

    retained = validate_disposition_payload(
        _disposition_body(entry, science_disposition="RETAIN_FOR_SHADOW"),
        pool_entry=entry,
    )
    assert retained["account_identity"] == "ACTION"
    assert retained["science_identity"] == "SCIENCE_CANDIDATE"

    with pytest.raises(OwnerDispositionError, match="SCIENCE_DISPOSITION_INVALID"):
        validate_disposition_payload(
            _disposition_body(entry, science_disposition="ABSORB_NO_ACTION"),
            pool_entry=entry,
        )


@pytest.mark.parametrize("science_disposition", ["REJECT", "DEFER"])
def test_reject_or_defer_records_verdict_but_cannot_freeze_actor_action(
    tmp_path: Path,
    science_disposition: str,
) -> None:
    pool, entry, _, _ = _ingest(tmp_path, selected_number=9)
    owner = tmp_path / "owner-veto"
    portfolio = _init_portfolio(tmp_path, name="portfolio-veto")
    path = _write_portfolio_disposition(
        owner,
        pool,
        entry,
        portfolio,
        science_disposition=science_disposition,
        account_identity="ACTION",
        selected_number=9,
    )
    with pytest.raises(FreezeAdapterError, match="OWNER_DISPOSITION_NOT_ADOPTED"):
        _apply_freeze(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
        )
    assert not (period_directory(portfolio, 1) / "frozen_episode.v1.json").exists()


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
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio, selected_number=7)

    result = _apply_freeze(
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
    portfolio = _init_portfolio(tmp_path)
    body = _attach_portfolio_binding(_disposition_body(entry, period_index=99), portfolio)
    # Force stale intended period while keeping other identity fields from inspect.
    body["period_index"] = 99
    body["portfolio_binding"] = {
        **body["portfolio_binding"],
        "intended_next_period_index": 99,
    }
    path = _write_disposition(owner, pool, body)
    with pytest.raises(
        FreezeAdapterError,
        match=r"FREEZE_PERIOD_MISMATCH|PORTFOLIO_HEAD_BINDING_MISMATCH",
    ):
        _apply_freeze(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
        )


def test_freeze_adapter_rejects_worker_disposition(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    # write_owner rejects non-channel source at write time for closed schema.
    with pytest.raises(OwnerDispositionError, match="DISPOSITION_SOURCE_NOT_OWNER_CHANNEL"):
        _write_disposition(owner, pool, _disposition_body(entry, disposition_source="worker"))


def test_no_prose_to_selected_number(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path, include_researcher_executable=False)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    body = _attach_portfolio_binding(
        _disposition_body(entry, include_executable=False),
        portfolio,
    )
    with pytest.raises(OwnerDispositionError, match="ACTION_REQUIRES_EXECUTABLE"):
        _write_disposition(owner, pool, body)


def test_freeze_request_with_outcome_rejected(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    verified = load_and_verify_disposition(
        disposition_path=_write_disposition(owner, pool, _disposition_body(entry)),
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
    pool, entry, _, _ = _ingest(tmp_path, decision_kind="NO_ACTION")
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(
        owner,
        pool,
        entry,
        portfolio,
        account_identity="RESEARCHER_ACCOUNT_NO_ACTION",
    )
    result = _apply_freeze(
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


@pytest.mark.parametrize("science_disposition", ["ADOPT", "RETAIN_FOR_SHADOW"])
def test_owner_authorized_researcher_action_freezes(
    tmp_path: Path,
    science_disposition: str,
) -> None:
    pool, entry, _, _ = _ingest(tmp_path, selected_number=9)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(
        owner,
        pool,
        entry,
        portfolio,
        science_disposition=science_disposition,
        account_identity="ACTION",
        selected_number=9,
    )
    result = _apply_freeze(
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
    assert side["science_disposition"] == science_disposition
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
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio)
    result = _apply_freeze(
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
    pool, entry, _, _ = _ingest(tmp_path, selected_number=1)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio, selected_number=1)
    freeze = _apply_freeze(
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
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio)
    _apply_freeze(
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
    pool, entry, _, _ = _ingest(tmp_path, decision_kind="NO_ACTION")
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(
        owner,
        pool,
        entry,
        portfolio,
        account_identity="RESEARCHER_ACCOUNT_NO_ACTION",
    )
    freeze = _apply_freeze(
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
    pool, entry, _, _ = _ingest(tmp_path, selected_number=3)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio, selected_number=3)
    result = _apply_freeze(
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
    first = write_owner_disposition_artifact(owner_state_root=owner, payload=body, pool_root=pool)
    second = write_owner_disposition_artifact(owner_state_root=owner, payload=body, pool_root=pool)
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


# --- Final freeze-seam attack closures (portfolio / TOCTOU / feedback surface) ---


def test_cross_portfolio_disposition_rejected_before_write(tmp_path: Path) -> None:
    """Same disposition bound to portfolio A must fail on portfolio B before any freeze write."""

    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio_a = _init_portfolio(
        tmp_path,
        name="portfolio_a",
        seat_id="seat.a",
        portfolio_ref="portfolio.A",
    )
    portfolio_b = _init_portfolio(
        tmp_path,
        name="portfolio_b",
        seat_id="seat.b",
        portfolio_ref="portfolio.B",
    )
    path = _write_portfolio_disposition(owner, pool, entry, portfolio_a, selected_number=7)
    # No period dirs / binding objects may exist under B before rejection.
    assert not (portfolio_b / "periods").exists() or not any((portfolio_b / "periods").iterdir())
    with pytest.raises(FreezeAdapterError, match="PORTFOLIO_HEAD_BINDING_MISMATCH"):
        _apply_freeze(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio_b,
            mode="portfolio",
        )
    assert not period_directory(portfolio_b, 1).exists()
    objects = portfolio_b / "objects"
    if objects.exists():
        assert not any(objects.rglob("*.json"))


def test_stale_head_prior_seat_portfolio_hash_each_reject(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    live = build_portfolio_binding_from_shadow(portfolio)

    def _write_mutated(**field_overrides: Any) -> Path:
        body = _attach_portfolio_binding(_disposition_body(entry), portfolio)
        pb = dict(body["portfolio_binding"])
        pb.update(field_overrides)
        body["portfolio_binding"] = pb
        if "intended_next_period_index" in field_overrides:
            body["period_index"] = field_overrides["intended_next_period_index"]
        return _write_disposition(owner, pool, body)

    cases = [
        {"head_period_index": 99},
        {"head_phase": "FEEDBACK_SEALED"},
        {"prior_settled_episode_hash": "1" * 64},
        {"prior_feedback_hash": "2" * 64},
        {"seat_content_hash": "3" * 64},
        {"portfolio_content_hash": "4" * 64},
        {"portfolio_ref": "portfolio.other"},
        {"seat_id": "seat.other"},
    ]
    for overrides in cases:
        path = _write_mutated(**overrides)
        with pytest.raises(FreezeAdapterError, match="PORTFOLIO_HEAD_BINDING_MISMATCH"):
            _apply_freeze(
                pool_root=pool,
                owner_state_root=owner,
                disposition_path=path,
                shadow_root=portfolio,
                mode="portfolio",
            )
    # Sanity: live first-period priors are explicit nulls.
    assert live["prior_settled_episode_hash"] is None
    assert live["prior_feedback_hash"] is None
    assert live["intended_next_period_index"] == 1


def test_full_action_intent_in_binding_agrees_with_frozen_ticket(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio, selected_number=7)
    result = _apply_freeze(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    side = load_research_binding(portfolio, result["research_binding_sha256"])
    intent = side["executable_account_intent"]
    assert intent["account_identity"] == "ACTION"
    assert intent["selected_number"] == 7
    assert intent["stake"] == "1.0000"
    assert intent["panel"] == "B"
    assert intent["rule_ref"] == "special-number-rule.v1"
    assert intent["odds_version_ref"] == "odds.special-number.20260731.v1"
    assert intent["baseline_ref"] == "BO0013"
    assert intent["risk_policy_ref"] == "shadow-risk.max-one-unit.v1"
    assert intent["target_ref"] == "draw.20260801-001"
    for key in ("target_open_time", "freeze_deadline", "frozen_at", "knowledge_cutoff"):
        assert intent.get(key)
    assert side["portfolio_binding"]["portfolio_ref"] == "portfolio.freeze.seam"
    frozen = load_frozen(period_directory(portfolio, 1))
    ticket = frozen.bound_account_ticket
    assert ticket is not None
    assert ticket.selected_number == intent["selected_number"]
    assert ticket.stake == intent["stake"]
    assert ticket.panel == intent["panel"]
    assert ticket.rule_ref == intent["rule_ref"]
    assert ticket.odds_version_ref == intent["odds_version_ref"]
    assert ticket.baseline_ref == intent["baseline_ref"]
    assert ticket.risk_policy_ref == intent["risk_policy_ref"]
    assert ticket.target_ref == intent["target_ref"]


def test_full_no_action_intent_in_binding_agrees_with_frozen_branch(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path, decision_kind="NO_ACTION")
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(
        owner,
        pool,
        entry,
        portfolio,
        account_identity="RESEARCHER_ACCOUNT_NO_ACTION",
    )
    result = _apply_freeze(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    side = load_research_binding(portfolio, result["research_binding_sha256"])
    intent = side["executable_account_intent"]
    assert intent["account_identity"] == "RESEARCHER_ACCOUNT_NO_ACTION"
    assert intent["selected_number"] is None
    assert intent["stake"] == "0.0000"
    assert intent["rule_ref"] == "special-number-rule.v1"
    assert intent["odds_version_ref"] == "odds.special-number.20260731.v1"
    assert intent["target_ref"] == "draw.20260801-001"
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is None
    assert frozen.account_decision.identity.value == "RESEARCHER_ACCOUNT_NO_ACTION"
    assert frozen.account_decision.stake == "0.0000"
    assert frozen.account_decision.rule_ref == intent["rule_ref"]
    assert frozen.account_decision.odds_version_ref == intent["odds_version_ref"]
    assert frozen.rule_ref == intent["rule_ref"]
    assert frozen.odds_version_ref == intent["odds_version_ref"]
    assert frozen.target_ref == intent["target_ref"]


def test_monkeypatched_request_rewrite_cannot_change_frozen_ticket(tmp_path: Path) -> None:
    """Display-file TOCTOU: poisoning freeze_request*.json cannot change the ticket."""

    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio, selected_number=7)

    original = freeze_portfolio_period
    attack_seen = {"called": False, "used_path": None, "used_request": None}

    def _attacking_freeze(  # type: ignore[no-untyped-def]
        *,
        root: Path,
        request_path=None,
        request=None,
        owner_authority=None,
    ):
        attack_seen["called"] = True
        attack_seen["used_path"] = request_path
        attack_seen["used_request"] = request is not None
        # Attacker rewrites every generated freeze_request* between prepare and consumer.
        generated_dir = Path(root) / "generated"
        if generated_dir.is_dir():
            for p in generated_dir.glob("freeze_request*.json"):
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw.get("bound_account_ticket"), dict):
                    raw["bound_account_ticket"]["selected_number"] = 49
                    raw["bound_account_ticket"]["stake"] = "99.0000"
                    raw.pop("request_content_hash", None)
                    p.write_text(
                        json.dumps(raw, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
        # If adapter still handed a path, force-read that poisoned path (old TOCTOU).
        # Correct repair: only in-memory request is authority.
        return original(
            root=root,
            request_path=request_path,
            request=request,
            owner_authority=owner_authority,
        )

    import xinao.science.freeze_adapter as freeze_mod

    monkey = pytest.MonkeyPatch()
    monkey.setattr(freeze_mod, "freeze_portfolio_period", _attacking_freeze)
    try:
        result = _apply_freeze(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
        )
    finally:
        monkey.undo()

    assert attack_seen["called"] is True
    assert attack_seen["used_path"] is None
    assert attack_seen["used_request"] is True
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 7
    assert frozen.bound_account_ticket.stake == "1.0000"
    side = load_research_binding(portfolio, result["research_binding_sha256"])
    assert side["executable_account_intent"]["selected_number"] == 7
    assert side["executable_account_intent"]["stake"] == "1.0000"


def test_in_memory_request_mutation_cannot_poison_frozen_ledger(tmp_path: Path) -> None:
    """R1: mutate the actual in-memory request at consumer handoff — no forged FROZEN."""

    from xinao.shadow_lifecycle.store import StoreError, derive_portfolio_head

    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio, selected_number=7)

    original = freeze_portfolio_period
    attack_seen = {"called": False}

    def _mutate_then_freeze(  # type: ignore[no-untyped-def]
        *,
        root: Path,
        request_path=None,
        request=None,
        owner_authority=None,
    ):
        attack_seen["called"] = True
        # Improved attack: rewrite the live in-memory mapping, not only display files.
        if isinstance(request, dict) and isinstance(request.get("bound_account_ticket"), dict):
            request = copy.deepcopy(dict(request))
            request["bound_account_ticket"] = dict(request["bound_account_ticket"])
            request["bound_account_ticket"]["selected_number"] = 49
            request["bound_account_ticket"]["stake"] = "99.0000"
            # Attacker may also try to re-seal request_content_hash.
            from xinao.canonical import canonical_sha256

            request["request_content_hash"] = canonical_sha256(
                {k: v for k, v in request.items() if k != "request_content_hash"}
            )
        return original(
            root=root,
            request_path=request_path,
            request=request,
            owner_authority=owner_authority,
        )

    import xinao.science.freeze_adapter as freeze_mod

    monkey = pytest.MonkeyPatch()
    monkey.setattr(freeze_mod, "freeze_portfolio_period", _mutate_then_freeze)
    try:
        with pytest.raises(
            (FreezeAdapterError, StoreError),
            match=(
                r"FREEZE_AUTHORITY_|PRODUCTION_FREEZE_|FREEZE_REQUEST_|"
                r"FREEZE_CONSUMER_REJECTED|TICKET_MISMATCH|REQUEST_ENVELOPE"
            ),
        ):
            _apply_freeze(
                pool_root=pool,
                owner_state_root=owner,
                disposition_path=path,
                shadow_root=portfolio,
                mode="portfolio",
            )
    finally:
        monkey.undo()

    assert attack_seen["called"] is True
    # Failed authority check must leave no frozen ticket / poisoned FROZEN head.
    period_root = period_directory(portfolio, 1)
    assert not (period_root / "frozen_episode.v1.json").exists()
    head = derive_portfolio_head(portfolio)
    assert head.phase.value in {"INIT", "MISSING"}
    # Honest retry with unmutated path still works (head not stuck FROZEN).
    result = _apply_freeze(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    assert result["ok"] is True
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 7
    assert frozen.bound_account_ticket.stake == "1.0000"


def test_default_research_feedback_pack_outside_period_cone_and_next_period(
    tmp_path: Path,
) -> None:
    """R2: settle→account feedback→default emit→next-period head/disposition/freeze."""

    from xinao.shadow_lifecycle.store import derive_portfolio_head

    portfolio, entry, freeze = _freeze_settle_feedback(tmp_path)
    head_before = derive_portfolio_head(portfolio)
    assert head_before.phase.value == "FEEDBACK_SEALED"
    emitted = emit_research_feedback_pack(portfolio_root=portfolio, period_index=1)
    pack_path = Path(emitted["path"])
    period_root = period_directory(portfolio, 1)
    assert pack_path.is_file()
    assert not str(pack_path.resolve()).startswith(str(period_root.resolve()) + "\\")
    assert not str(pack_path.resolve()).startswith(str(period_root.resolve()) + "/")
    assert "objects" in pack_path.parts
    assert "research_feedback_pack" in pack_path.parts
    assert emitted.get("period_cone_artifact") is False
    # Explicit period-cone write is rejected.
    with pytest.raises(ResearchFeedbackPackError, match="FEEDBACK_PACK_PERIOD_CONE_FORBIDDEN"):
        emit_research_feedback_pack(
            portfolio_root=portfolio,
            period_index=1,
            output_path=period_root / "research_feedback_pack.v1.json",
        )
    # Head remains usable after default emit.
    head_after = derive_portfolio_head(portfolio)
    assert head_after.phase.value == "FEEDBACK_SEALED"
    assert head_after.period_index == 1
    live = build_portfolio_binding_from_shadow(portfolio)
    assert live["intended_next_period_index"] == 2
    assert live["prior_settled_episode_hash"] is not None
    assert live["prior_feedback_hash"] is not None
    # Period-2 disposition freeze still works with later prior hashes.
    owner = tmp_path / "owner_p2"
    owner.mkdir()
    pool, entry2, _, _ = _ingest(tmp_path / "pool2", selected_number=11)
    path = _write_portfolio_disposition(
        owner,
        pool,
        entry2,
        portfolio,
        selected_number=11,
        period_index=2,
        episode_ref="episode.disp.p2",
    )
    result = _apply_freeze(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    assert result["period_index"] == 2
    frozen = load_frozen(period_directory(portfolio, 2))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 11
    # Feedback pack priors still echo period-1 binding, not rewritable history.
    assert emitted["pack"]["prior_research_binding_sha256"] == freeze["research_binding_sha256"]
    assert emitted["pack"]["prior_result_sha256"] == entry["result_sha256"]


def test_direct_production_freeze_without_owner_disposition_rejected(tmp_path: Path) -> None:
    """R3: freeze_portfolio_period(request_path=forged) cannot mint production ACTION."""

    from xinao.shadow_lifecycle.store import StoreError

    portfolio = _init_portfolio(tmp_path)
    forged = {
        "episode_ref": "episode.forged.worker",
        "science_decision": {
            "science_decision_ref": "sci.forged",
            "identity": "SCIENCE_CANDIDATE",
            "knowledge_cutoff": _iso(CUTOFF),
            "rationale_ref": "rationale.forged",
            "candidate_ref": "policy.forged",
        },
        "account_decision": {
            "account_decision_ref": "acct.forged",
            "identity": "ACTION",
        },
        "bound_account_ticket": {
            "ticket_ref": "ticket.forged",
            "target_ref": "draw.20260801-001",
            "target_open_time": _iso(OPEN_AT),
            "freeze_deadline": _iso(DEADLINE),
            "knowledge_cutoff": _iso(CUTOFF),
            "frozen_at": _iso(FROZEN_AT),
            "panel": "B",
            "selected_number": 49,
            "stake": "5.0000",
            "rule_ref": "special-number-rule.v1",
            "odds_version_ref": "odds.special-number.20260731.v1",
            "baseline_ref": "BO0013",
            "risk_policy_ref": "shadow-risk.max-one-unit.v1",
            "information_set_ref": "info.forged",
            "information_set_hash": "a" * 64,
        },
        "target_ref": "draw.20260801-001",
        "target_open_time": _iso(OPEN_AT),
        "freeze_deadline": _iso(DEADLINE),
        "frozen_at": _iso(FROZEN_AT),
    }
    request_path = tmp_path / "forged_freeze_request.json"
    request_path.write_text(
        json.dumps(forged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(StoreError, match="PRODUCTION_FREEZE_REQUIRES_OWNER_AUTHORITY"):
        freeze_portfolio_period(root=portfolio, request_path=request_path)
    assert not (period_directory(portfolio, 1) / "frozen_episode.v1.json").exists()
    # Public production API must not accept a fixture-bypass flag.
    import importlib.util
    import inspect

    assert "allow_fixture_construction" not in inspect.signature(freeze_portfolio_period).parameters
    # Test-only helper under tests/ may construct fixtures without Owner CAS.
    helper_path = (
        Path(__file__).resolve().parents[1] / "shadow_lifecycle" / "fixture_portfolio_freeze.py"
    )
    spec = importlib.util.spec_from_file_location("fixture_portfolio_freeze", helper_path)
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    ok = helper.freeze_portfolio_period_for_fixture(root=portfolio, request_path=request_path)
    assert ok["ok"] is True
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 49


def test_direct_production_freeze_rechecks_researcher_source_not_self_consistent_fakes(
    tmp_path: Path,
) -> None:
    """A forged but internally consistent CAS chain cannot bypass producer re-read."""

    from xinao.shadow_lifecycle.store import StoreError

    pool, entry, _, _ = _ingest(tmp_path, selected_number=7)
    owner = tmp_path / "owner_forged_chain"
    portfolio = _init_portfolio(tmp_path, name="portfolio_forged_chain")

    # Bypass the formal writer and manually seal an ACTION for 49 while the
    # researcher's sealed result explicitly authored 7.
    body = _attach_portfolio_binding(
        _disposition_body(entry, selected_number=49),
        portfolio,
    )
    raw = encode_disposition_bytes(body)
    disposition_sha = raw_sha256(raw)
    disposition_path = disposition_cas_path(owner, disposition_sha)
    disposition_path.parent.mkdir(parents=True, exist_ok=True)
    disposition_path.write_bytes(raw)

    forged_normalized = copy.deepcopy(body)
    forged_normalized["science_identity"] = "SCIENCE_CANDIDATE"
    executable = forged_normalized["executable_account_decision"]
    researcher_core = {key: value for key, value in executable.items() if key != "frozen_at"}
    forged_researcher_binding = {
        "schema_version": "xinao.researcher_action_binding.v1",
        "account_identity": "ACTION",
        "source_kind": "ONESHOT_RESEARCH_RESULT",
        "source_artifact_sha256": entry["result_sha256"],
        "source_json_path": "$.candidate.executable_account_decision",
        "decision_content_hash": canonical_sha256(researcher_core),
        "executable_content_hash": canonical_sha256(researcher_core),
        "result_sha256": entry["result_sha256"],
        "pool_entry_content_hash": entry["content_hash"],
    }
    binding_body = build_research_freeze_binding(
        pool_entry=entry,
        disposition=forged_normalized,
        owner_artifact_sha256=disposition_sha,
        researcher_action_binding=forged_researcher_binding,
        portfolio_binding=body["portfolio_binding"],
        freeze_action_time=FROZEN_AT,
    )
    binding = write_research_binding_exclusive(
        shadow_root=portfolio,
        body=binding_body,
    )
    binding_sha = str(binding["research_binding_sha256"])
    request = build_freeze_request_from_disposition(
        pool_entry=entry,
        disposition=forged_normalized,
        owner_artifact_sha256=disposition_sha,
        research_binding_sha256=binding_sha,
        freeze_action_time=FROZEN_AT,
    )
    authority = {
        "schema_version": OWNER_FREEZE_AUTHORITY_SCHEMA,
        "authority_marker": OWNER_FREEZE_AUTHORITY_MARKER,
        "owner_state_root": str(owner.resolve()),
        "research_pool_root": str(pool.resolve()),
        "owner_disposition_sha256": disposition_sha,
        "research_binding_sha256": binding_sha,
        "request_content_hash": request["request_content_hash"],
    }

    with pytest.raises(
        StoreError,
        match=r"PRODUCTION_FREEZE_DISPOSITION_REJECTED:.*RESEARCHER_EXECUTABLE_DECISION_MISMATCH",
    ):
        freeze_portfolio_period(
            root=portfolio,
            request=request,
            owner_authority=authority,
        )
    assert not (period_directory(portfolio, 1) / "frozen_episode.v1.json").exists()


def test_direct_production_freeze_rejects_caller_science_identity_override(
    tmp_path: Path,
) -> None:
    """The low-level production consumer must use the same derived science branch."""

    from xinao.shadow_lifecycle.store import StoreError

    pool, entry, _, _ = _ingest(tmp_path, selected_number=7)
    owner = tmp_path / "owner_science_override"
    portfolio = _init_portfolio(tmp_path, name="portfolio_science_override")
    body = _attach_portfolio_binding(_disposition_body(entry, selected_number=7), portfolio)
    body["science_identity"] = "POLICY_NO_ACTION"
    raw = encode_disposition_bytes(body)
    disposition_sha = raw_sha256(raw)
    disposition_path = disposition_cas_path(owner, disposition_sha)
    disposition_path.parent.mkdir(parents=True, exist_ok=True)
    disposition_path.write_bytes(raw)

    # The request/binding are intentionally self-consistent with the forged
    # override. Formal disposition verification must reject before freeze.
    verified_source = load_and_verify_disposition(
        disposition_path=_write_disposition(
            tmp_path / "honest_owner_for_binding",
            pool,
            _attach_portfolio_binding(_disposition_body(entry, selected_number=7), portfolio),
        ),
        owner_state_root=tmp_path / "honest_owner_for_binding",
        pool_root=pool,
    )
    binding_body = build_research_freeze_binding(
        pool_entry=entry,
        disposition=body,
        owner_artifact_sha256=disposition_sha,
        researcher_action_binding=verified_source["researcher_action_binding"],
        portfolio_binding=body["portfolio_binding"],
        freeze_action_time=FROZEN_AT,
    )
    binding = write_research_binding_exclusive(shadow_root=portfolio, body=binding_body)
    binding_sha = str(binding["research_binding_sha256"])
    request = build_freeze_request_from_disposition(
        pool_entry=entry,
        disposition=body,
        owner_artifact_sha256=disposition_sha,
        research_binding_sha256=binding_sha,
        freeze_action_time=FROZEN_AT,
    )
    authority = {
        "schema_version": OWNER_FREEZE_AUTHORITY_SCHEMA,
        "authority_marker": OWNER_FREEZE_AUTHORITY_MARKER,
        "owner_state_root": str(owner.resolve()),
        "research_pool_root": str(pool.resolve()),
        "owner_disposition_sha256": disposition_sha,
        "research_binding_sha256": binding_sha,
        "request_content_hash": request["request_content_hash"],
    }
    with pytest.raises(
        StoreError,
        match="SCIENCE_IDENTITY_CALLER_OVERRIDE_FORBIDDEN",
    ):
        freeze_portfolio_period(root=portfolio, request=request, owner_authority=authority)
    assert not (period_directory(portfolio, 1) / "frozen_episode.v1.json").exists()


def test_direct_production_freeze_rejects_owner_executable_unknown_field(
    tmp_path: Path,
) -> None:
    """The public consumer must not silently project an expanded executable."""

    from xinao.shadow_lifecycle.store import StoreError

    pool, entry, _, _ = _ingest(tmp_path, selected_number=7)
    owner = tmp_path / "owner_executable_extra"
    portfolio = _init_portfolio(tmp_path, name="portfolio_executable_extra")
    body = _attach_portfolio_binding(_disposition_body(entry, selected_number=7), portfolio)
    body["executable_account_decision"]["debug_note"] = "must not be ignored"
    request, authority = _manual_production_authority_chain(
        body=body,
        entry=entry,
        pool=pool,
        owner=owner,
        portfolio=portfolio,
    )

    with pytest.raises(
        StoreError,
        match=r"PRODUCTION_FREEZE_DISPOSITION_REJECTED:.*unknown=\['debug_note'\]",
    ):
        freeze_portfolio_period(root=portfolio, request=request, owner_authority=authority)
    assert not (period_directory(portfolio, 1) / "frozen_episode.v1.json").exists()


@pytest.mark.parametrize(
    "binding_overrides",
    [
        {"episode_ref": "episode.forged"},
        {"portfolio_binding": {"forged": True}},
        {"source_authority_binding": {"forged": True}},
        {"scientific_promotion": True},
        {"owner_adopted": True},
        {"unexpected_binding_field": "forged"},
    ],
)
def test_direct_production_freeze_rejects_noncanonical_research_binding_fields(
    tmp_path: Path,
    binding_overrides: dict[str, Any],
) -> None:
    """Every formal binding field is closed and compared before a period write."""

    from xinao.shadow_lifecycle.store import StoreError

    pool, entry, _, _ = _ingest(tmp_path, selected_number=7)
    owner = tmp_path / "owner_binding_divergence"
    portfolio = _init_portfolio(tmp_path, name="portfolio_binding_divergence")
    body = _attach_portfolio_binding(_disposition_body(entry, selected_number=7), portfolio)
    request, authority = _manual_production_authority_chain(
        body=body,
        entry=entry,
        pool=pool,
        owner=owner,
        portfolio=portfolio,
        binding_overrides=binding_overrides,
    )

    with pytest.raises(StoreError):
        freeze_portfolio_period(root=portfolio, request=request, owner_authority=authority)
    assert not (period_directory(portfolio, 1) / "frozen_episode.v1.json").exists()


def test_content_addressed_request_evidence_display_only_no_overwrite(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio, selected_number=7)
    result = _apply_freeze(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    assert result["request_evidence_authority_input"] is False
    evidence_path = Path(result["request_evidence_path"])
    assert evidence_path.is_file()
    digest = result["request_evidence_sha256"]
    assert evidence_path == freeze_request_evidence_path(portfolio, digest)
    original = evidence_path.read_bytes()
    # Overwrite attempt of CAS evidence must fail closed on exclusive re-write helper.
    verified = load_and_verify_disposition(
        disposition_path=path,
        owner_state_root=owner,
        pool_root=pool,
    )
    request = build_freeze_request_from_disposition(
        pool_entry=verified["pool_entry"],
        disposition=verified["disposition"],
        owner_artifact_sha256=str(verified["owner_artifact_sha256"]),
        research_binding_sha256=result["research_binding_sha256"],
    )
    request = dict(request)
    request["bound_account_ticket"] = dict(request["bound_account_ticket"])
    request["bound_account_ticket"]["selected_number"] = 49
    request["bound_account_ticket"]["stake"] = "99.0000"
    # Existing evidence path cannot be rewritten via exclusive create.
    with pytest.raises(FileExistsError), evidence_path.open("xb") as stream:
        stream.write(b"evil")
    assert evidence_path.read_bytes() == original
    # Display path rewrite must not matter: ticket already frozen at 7.
    display = Path(result["request_path"])
    if display.is_file():
        write_freeze_request(
            display,
            {**request, "bound_account_ticket": {"selected_number": 49, "stake": "99.0000"}},
        )
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 7
    assert frozen.bound_account_ticket.stake == "1.0000"
    # Content-addressed evidence: different bytes => different path, no overwrite.
    other = write_freeze_request_evidence_exclusive(shadow_root=portfolio, request=request)
    assert other["request_evidence_sha256"] != digest
    assert Path(other["path"]) != evidence_path
    assert evidence_path.read_bytes() == original


def test_no_public_build_research_feedback_pack_export() -> None:
    import xinao.science.research_feedback_pack as mod

    assert not hasattr(mod, "build_research_feedback_pack")
    assert "build_research_feedback_pack" not in getattr(mod, "__all__", [])
    with pytest.raises(ImportError):
        from xinao.science.research_feedback_pack import build_research_feedback_pack  # noqa: F401


def test_forged_prior_cannot_mint_pack_via_any_public_function(tmp_path: Path) -> None:
    import xinao.science.research_feedback_pack as mod

    public_names = [n for n in dir(mod) if not n.startswith("_")]
    assert "build_research_feedback_pack" not in public_names
    # emit rejects free prior kwargs; private builder remains private.
    portfolio, _entry, _freeze = _freeze_settle_feedback(tmp_path)
    with pytest.raises(TypeError):
        emit_research_feedback_pack(  # type: ignore[call-arg]
            portfolio_root=portfolio,
            prior_result_sha256="a" * 64,
            prior_receipt_content_sha256="b" * 64,
            prior_pool_entry_content_hash="c" * 64,
            prior_policy_ref="forged.policy",
            prior_owner_artifact_sha256="d" * 64,
            prior_research_binding_sha256="e" * 64,
            period_index=1,
        )
    # Private pure builder may still exist for verified emit path/tests only.
    assert hasattr(mod, "_build_research_feedback_pack_body")
    assert not hasattr(mod, "build_research_feedback_pack")


def test_later_period_feedback_sealed_head_binding(tmp_path: Path) -> None:
    # Account feedback seals the head; do not drop research packs into the period cone.
    portfolio, _entry, _freeze = _freeze_settle_feedback(tmp_path)
    live = build_portfolio_binding_from_shadow(portfolio)
    assert live["head_phase"] == "FEEDBACK_SEALED"
    assert live["head_period_index"] == 1
    assert live["intended_next_period_index"] == 2
    assert live["prior_settled_episode_hash"] is not None
    assert live["prior_feedback_hash"] is not None
    owner = tmp_path / "owner_p2"
    owner.mkdir()
    pool, entry2, _, _ = _ingest(tmp_path / "pool2", selected_number=11)
    path = _write_portfolio_disposition(
        owner,
        pool,
        entry2,
        portfolio,
        selected_number=11,
        period_index=2,
        episode_ref="episode.disp.p2",
    )
    result = _apply_freeze(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    assert result["period_index"] == 2
    side = load_research_binding(portfolio, result["research_binding_sha256"])
    assert side["portfolio_binding"]["intended_next_period_index"] == 2
    assert (
        side["portfolio_binding"]["prior_settled_episode_hash"]
        == live["prior_settled_episode_hash"]
    )
    assert side["portfolio_binding"]["prior_feedback_hash"] == live["prior_feedback_hash"]
    frozen = load_frozen(period_directory(portfolio, 2))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 11


def test_flat_episode_mode_has_no_portfolio_identity(tmp_path: Path) -> None:
    from xinao.shadow_lifecycle import init_episode

    pool, entry, _, _ = _ingest(tmp_path, selected_number=5)
    owner = tmp_path / "owner"
    owner.mkdir()
    episode_root = tmp_path / "episode"
    init_episode(
        root=episode_root,
        seat_id="seat.flat.episode",
        portfolio_ref="portfolio.flat.episode",
    )
    # Flat mode: no portfolio_binding on disposition.
    body = _disposition_body(entry, period_index=1, selected_number=5)
    assert "portfolio_binding" not in body or body.get("portfolio_binding") is None
    path = _write_disposition(owner, pool, body)
    result = _apply_freeze(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=episode_root,
        mode="episode",
    )
    assert result["mode"] == "episode"
    assert result["portfolio_binding"] is None
    side = load_research_binding(episode_root, result["research_binding_sha256"])
    assert side["portfolio_binding"] is None
    assert side["executable_account_intent"]["selected_number"] == 5
    frozen = load_frozen(episode_root)
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 5


def test_exact_retry_same_disposition_fails_closed_after_freeze(tmp_path: Path) -> None:
    pool, entry, _, _ = _ingest(tmp_path)
    owner = tmp_path / "owner"
    owner.mkdir()
    portfolio = _init_portfolio(tmp_path)
    path = _write_portfolio_disposition(owner, pool, entry, portfolio, selected_number=7)
    first = _apply_freeze(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=path,
        shadow_root=portfolio,
        mode="portfolio",
    )
    assert first["ok"] is True
    # Exact retry cannot open a second freeze on the same head.
    with pytest.raises(
        FreezeAdapterError,
        match=r"FREEZE_PORTFOLIO_HEAD_NOT_READY|PORTFOLIO_HEAD",
    ):
        _apply_freeze(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=portfolio,
            mode="portfolio",
        )
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 7


def test_no_autonomous_control_surface_in_adapter() -> None:
    assert_no_control_plane_imports()
    import xinao.science.freeze_adapter as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "auto_settle" in source  # returned False only
    assert "auto_next_period" in source
    # No settle/next-period verbs invoked by adapter.
    assert "settle_portfolio_period" not in source
    assert "feedback_portfolio_period" not in source
    assert "prepare_next_period_root" not in source
