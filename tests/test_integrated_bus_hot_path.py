from __future__ import annotations

import hashlib
import inspect
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    artifact_json_bytes,
    canonical_json_bytes,
    logical_contract_sha256,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    GROK_DOCKER_CONSUMER_ID,
    expected_docker_grok_backend_models,
    grok_docker_model_identity_binding,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSER_MODEL = "grok-composer-2.5-fast"
GROK_BACKEND_BUILD = "grok-4.5-build"
GROK_MODEL_POLICY_ID = "xinao.grok.provider_model_routing.v2"
GROK_EXECUTION_CONTRACT_VERSION = "xinao.grok.shared_execution_contract.v1"


def _supervisor_decision(model: str = COMPOSER_MODEL) -> dict:
    receipt = {
        "decision": "selected",
        "selected_candidate": {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": model,
            "transport_id": "temporal-docker-langgraph",
            "declared_active": True,
            "healthy": True,
            "positive_benefit": True,
            "context_capable": False,
        },
        "eligible_candidates": [],
        "excluded_reasons": [],
        "decision_reason": "explicit_supervisor_choice",
        "schema_version": "xinao.supervisor_worker_decision_receipt.v1",
        "policy_ref": "D:/runtime/agent_runtime/routing_policy.json",
        "policy_sha256": "a" * 64,
        "policy_version": "test",
    }
    receipt["decision_sha256"] = hashlib.sha256(
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return receipt


def _session_model_evidence(model: str, session_id: str) -> dict:
    backend_models = expected_docker_grok_backend_models(model)
    return {
        "source": "grok_session_summary_and_turn_events",
        "requestedModel": model,
        "selectedSessionModel": model,
        "currentModelId": model,
        "turnModelIds": [model],
        "observedModelId": backend_models[0],
        "modelUsageIds": backend_models,
        "availableModelIds": [COMPOSER_MODEL, "grok-4.5"],
        "backendModelIds": backend_models,
        "expectedBackendModelIds": backend_models,
        "backendSessionId": session_id,
        "sessionCwd": "/app",
        "sessionGrokHome": "/grok-home/.grok",
        "sessionSummaryRef": f"/grok-home/.grok/sessions/test/{session_id}/summary.json",
        "sessionSummarySha256": "a" * 64,
        "sessionEventsRef": f"/grok-home/.grok/sessions/test/{session_id}/events.jsonl",
        "sessionEventsSha256": "b" * 64,
    }


def _common_execution_evidence(
    lane_id: str,
    *,
    model: str = COMPOSER_MODEL,
    operation_id: str | None = None,
) -> tuple[dict, dict, str]:
    operation_id = operation_id or f"op-{lane_id}"
    contract = {
        "schema_version": LOGICAL_CONTRACT_VERSION,
        "logical_operation_id": operation_id,
        "work_key": f"work-{lane_id}",
        "task_contract_ref": "",
        "parent_operation_id": "parent",
        "correlation_id": f"work-{lane_id}",
        "input_sha256": "c" * 64,
        "context_sha256": "d" * 64,
        "rules_sha256": "b" * 64,
        "output_contract_sha256": "e" * 64,
        "selection": {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": model,
            "transport_id": "grok_cli_json",
            "capability_binding_sha256": "f" * 64,
        },
        "effect_mode": "read_only",
        "idempotency_key": operation_id,
        "deadline": {
            "owner": "temporal",
            "mode": "relative_from_activity_start",
            "seconds": 1800,
        },
        "cancellation_generation": 0,
    }
    receipt = {
        "schema_version": ATTEMPT_RECEIPT_VERSION,
        "contract_sha256": logical_contract_sha256(contract),
        "consumer_id": GROK_DOCKER_CONSUMER_ID,
        "logical_operation_id": operation_id,
        "work_key": f"work-{lane_id}",
        "attempt": 1,
        "observed": {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": model,
            "transport_id": "grok_cli_json",
            "capability_binding_sha256": "f" * 64,
            "rules_sha256": "b" * 64,
            "runtime_version": "0.2.101",
            "execution_location": "docker:houtai-gongren",
            "executor_id": "container-1",
        },
        "terminal_state": "completed",
        "stop_reason": "EndTurn",
        "output": {
            "format": "text",
            "content_sha256": "1" * 64,
            "chars": 1000,
            "schema_sha256": "e" * 64,
            "schema_valid": True,
            "markers_ok": True,
            "substantive": True,
        },
        "invocations": [
            {
                "invocation": 1,
                "state": "accepted",
                "observed_model": model,
                "stop_reason": "EndTurn",
                "output_sha256": "1" * 64,
                "output_chars": 1000,
                "total_tokens": 100,
            }
        ],
        "usage": {
            "invocation_count": 1,
            "total_tokens": 100,
            "accepted_tokens": 100,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
        "lineage": {
            "workflow_id": "parent-wf",
            "lane_id": lane_id,
            "parent_operation_id": "parent",
            "correlation_id": f"work-{lane_id}",
            "session_id": f"session-{lane_id}",
        },
        "provider_contract_version": GROK_EXECUTION_CONTRACT_VERSION,
        "provider_evidence_ref": f"D:/identity-{lane_id}.json",
        "provider_evidence_sha256": "a" * 64,
        "provider_evidence_valid": True,
        "replayed": False,
    }
    receipt_sha256 = hashlib.sha256(artifact_json_bytes(receipt)).hexdigest()
    return contract, receipt, receipt_sha256


def _attested_grok_lane(
    lane_id: str,
    mode: str,
    *,
    model: str = COMPOSER_MODEL,
    identity_path: Path,
) -> dict:
    backend_models = expected_docker_grok_backend_models(model)
    identity_binding = grok_docker_model_identity_binding(model)
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(
        json.dumps({"modelUsage": {backend_models[0]: {"modelCalls": 1}}}),
        encoding="utf-8",
    )
    identity_sha256 = hashlib.sha256(identity_path.read_bytes()).hexdigest()
    session_id = f"session-{lane_id}"
    session_evidence = _session_model_evidence(model, session_id)
    session_evidence_path = identity_path.parent / f"{lane_id}-session-model-evidence.json"
    session_evidence_path.write_bytes(artifact_json_bytes(session_evidence))
    session_evidence_sha256 = hashlib.sha256(session_evidence_path.read_bytes()).hexdigest()
    contract, receipt, receipt_sha256 = _common_execution_evidence(lane_id, model=model)
    receipt["provider_evidence_ref"] = str(identity_path)
    receipt["provider_evidence_sha256"] = identity_sha256
    receipt_sha256 = hashlib.sha256(artifact_json_bytes(receipt)).hexdigest()
    return {
        "ok": True,
        "execution_contract_version": GROK_EXECUTION_CONTRACT_VERSION,
        "lane_id": lane_id,
        "mode": mode,
        "model": model,
        "requested_model": model,
        "observed_model": backend_models[0],
        "observed_models": backend_models,
        "observed_backend_models": backend_models,
        "model_identity_binding": identity_binding,
        "model_identity_ok": True,
        "model_policy_id": GROK_MODEL_POLICY_ID,
        "session_model_evidence_valid": True,
        "session_model_evidence": session_evidence,
        "session_model_evidence_ref": str(session_evidence_path),
        "session_model_evidence_sha256": session_evidence_sha256,
        "agent_session_id": session_id,
        "model_identity_ref": str(identity_path),
        "model_identity_sha256": identity_sha256,
        "operation_id": f"op-{lane_id}",
        "operation_state": "completed",
        "stop_reason": "EndTurn",
        "result_text": f"substantive result for {lane_id}",
        "model_capability_ok": True,
        "requested_rules_snapshot_sha256": "b" * 64,
        "observed_rules_snapshot_sha256": "b" * 64,
        "rules_snapshot_ok": True,
        "rules_projection_ok": True,
        "invocation_accounting": {
            "invocation_count": 1,
            "total_tokens": 100,
            "accepted_tokens": 100,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
        "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "cross_seam_attempt_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "cross_seam_contract_sha256": logical_contract_sha256(contract),
        "cross_seam_logical_contract": contract,
        "cross_seam_attempt_receipt": receipt,
        "cross_seam_attempt_receipt_sha256": receipt_sha256,
    }


def _attested_grok_manifest(
    intake: Path,
    lanes: list[tuple[str, str]],
    *,
    workflow_id: str = "parent-wf",
    model: str = COMPOSER_MODEL,
) -> dict:
    backend_models = expected_docker_grok_backend_models(model)
    identity_binding = grok_docker_model_identity_binding(model)
    lane_payloads = [
        _attested_grok_lane(
            lane_id,
            mode,
            model=model,
            identity_path=intake.parent / f"{lane_id}-cli-result.json",
        )
        for lane_id, mode in lanes
    ]
    receipt_bindings = [
        {
            "lane_id": lane["lane_id"],
            "contract_sha256": lane["cross_seam_contract_sha256"],
            "attempt_receipt_sha256": lane["cross_seam_attempt_receipt_sha256"],
        }
        for lane in lane_payloads
    ]
    return {
        "schema_version": "xinao.grok.temporal_acpx_fanin.v2",
        "execution_contract_version": GROK_EXECUTION_CONTRACT_VERSION,
        "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "cross_seam_attempt_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "cross_seam_receipt_bindings": receipt_bindings,
        "cross_seam_receipt_set_sha256": hashlib.sha256(
            canonical_json_bytes(receipt_bindings)
        ).hexdigest(),
        "ok": True,
        "sentinel": "XINAO_GROK_TEMPORAL_FANIN_V1",
        "provider_id": "grok_acpx_headless",
        "model_policy_id": GROK_MODEL_POLICY_ID,
        "model": model,
        "models": [model],
        "observed_model": backend_models[0],
        "observed_models": backend_models,
        "observed_backend_models": backend_models,
        "model_identity_binding": identity_binding,
        "model_identity_ok": True,
        "execution_location": "docker:houtai-gongren",
        "workflow_id": workflow_id,
        "succeeded": len(lane_payloads),
        "failed": 0,
        "ready_width": len(lane_payloads),
        "lanes": lane_payloads,
        "token_accounting": {
            "invocation_count": len(lane_payloads),
            "total_tokens": 100 * len(lane_payloads),
            "accepted_tokens": 100 * len(lane_payloads),
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
        "intake_sha256": hashlib.sha256(intake.read_bytes()).hexdigest(),
    }


def test_docker_grok_cli_parser_requires_observed_composer_and_real_usage() -> None:
    from services.agent_runtime.grok_build_docker_worker import _parse_cli_result

    text, session_id, usage, model_usage = _parse_cli_result(
        {
            "text": "verified",
            "stopReason": "EndTurn",
            "sessionId": "019f6ca6-c814-7fe1-8eb3-a71a7af14d23",
            "usage": {"total_tokens": 10_043},
            "modelUsage": {GROK_BACKEND_BUILD: {"modelCalls": 1}},
        },
        requested_model=COMPOSER_MODEL,
    )
    assert text == "verified"
    assert session_id.startswith("019f")
    assert usage["total_tokens"] == 10_043
    assert list(model_usage) == [GROK_BACKEND_BUILD]

    for wrong_model in (COMPOSER_MODEL, "grok-4.5"):
        with pytest.raises(ValueError, match="model identity mismatch"):
            _parse_cli_result(
                {
                    "text": "wrong model",
                    "stopReason": "EndTurn",
                    "sessionId": "session",
                    "usage": {"total_tokens": 1},
                    "modelUsage": {wrong_model: {"modelCalls": 1}},
                },
                requested_model=COMPOSER_MODEL,
            )
    with pytest.raises(ValueError, match="model identity mismatch"):
        _parse_cli_result(
            {
                "text": "mixed model",
                "stopReason": "EndTurn",
                "sessionId": "session",
                "usage": {"total_tokens": 1},
                "modelUsage": {
                    COMPOSER_MODEL: {"modelCalls": 1},
                    "grok-4.5-build": {"modelCalls": 1},
                },
            },
            requested_model=COMPOSER_MODEL,
        )
    with pytest.raises(ValueError, match="did not complete"):
        _parse_cli_result(
            {
                "text": "still gathering evidence",
                "stopReason": "Cancelled",
                "sessionId": "session",
                "usage": {"total_tokens": 70_129},
                "modelUsage": {GROK_BACKEND_BUILD: {"modelCalls": 1}},
            },
            requested_model=COMPOSER_MODEL,
        )
    with pytest.raises(ValueError, match="one JSON object"):
        _parse_cli_result(
            {
                "text": "not structured",
                "stopReason": "EndTurn",
                "sessionId": "session",
                "usage": {"total_tokens": 1},
                "modelUsage": {GROK_BACKEND_BUILD: {"modelCalls": 1}},
            },
            requested_model=COMPOSER_MODEL,
            result_format="json_object",
        )
    with pytest.raises(ValueError, match="bound JSON schema"):
        _parse_cli_result(
            {
                "text": '{"status":"wrong"}',
                "stopReason": "EndTurn",
                "sessionId": "session",
                "usage": {"total_tokens": 1},
                "modelUsage": {GROK_BACKEND_BUILD: {"modelCalls": 1}},
            },
            requested_model=COMPOSER_MODEL,
            result_format="json_object",
            result_json_schema={
                "type": "object",
                "properties": {"audit_schema": {"const": "xinao.audit.v1"}},
                "required": ["audit_schema"],
                "additionalProperties": False,
            },
        )


def test_docker_grok_catalog_admits_only_hidden_oauth_selectors(
    tmp_path: Path,
) -> None:
    from services.agent_runtime.grok_build_docker_worker import (
        DockerGrokPermanentError,
        _authenticated_model_catalog,
        _model_capability_binding,
    )

    catalog = tmp_path / "models_cache.json"
    catalog.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "grok_version": "0.2.102",
                "auth_method": "session",
                "origin": "https://cli-chat-proxy.grok.com/v1/models",
                "models": {"grok-4.5": {"id": "grok-4.5"}},
            }
        ),
        encoding="utf-8",
    )
    snapshot = _authenticated_model_catalog(
        catalog,
        requested_model=COMPOSER_MODEL,
        cli_version="0.2.102",
        observed_at=datetime.now(UTC),
    )
    assert snapshot["schema_version"] == "xinao.grok.authenticated_model_catalog.v1"
    assert snapshot["server_model_ids"] == ["grok-4.5"]
    assert snapshot["requested_model_available"] is False
    assert len(snapshot["cache_sha256"]) == 64

    first_binding = _model_capability_binding(
        requested_model=COMPOSER_MODEL,
        cli_version="0.2.102",
        merged_cli_model_ids=["grok-4.5", COMPOSER_MODEL],
        authenticated_catalog=snapshot,
    )
    refreshed_observation = {
        **snapshot,
        "fetched_at": "2099-01-01T00:00:00+00:00",
        "age_seconds": 99.5,
        "modified_at": "2099-01-01T00:00:01+00:00",
        "cache_sha256": "f" * 64,
        "sha256": "e" * 64,
    }
    second_binding = _model_capability_binding(
        requested_model=COMPOSER_MODEL,
        cli_version="0.2.102",
        merged_cli_model_ids=["grok-4.5", COMPOSER_MODEL],
        authenticated_catalog=refreshed_observation,
    )
    assert first_binding["sha256"] == second_binding["sha256"]
    assert first_binding["requested_model_available"] is True
    assert first_binding["hidden_oauth_selector"] is True
    assert first_binding["admission_source"] == "hidden_oauth_selector"
    assert first_binding["identity_policy"] == "exact_session_selector_and_backend_binding_v2"
    assert first_binding["expected_backend_model_ids"] == [GROK_BACKEND_BUILD]

    with pytest.raises(ValueError, match="no Docker Grok backend identity binding"):
        _model_capability_binding(
            requested_model="invented-local-alias",
            cli_version="0.2.102",
            merged_cli_model_ids=["grok-4.5", "invented-local-alias"],
            authenticated_catalog=snapshot,
        )
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["origin"] = "https://example.invalid/v1/models"
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DockerGrokPermanentError, match="origin is invalid"):
        _authenticated_model_catalog(
            catalog,
            requested_model=COMPOSER_MODEL,
            cli_version="0.2.102",
            observed_at=datetime.now(UTC),
        )


def test_docker_grok_binds_official_home_and_excludes_api_credentials(tmp_path: Path) -> None:
    from services.agent_runtime.grok_build_docker_worker import _grok_cli_environment

    worker_home = tmp_path / "grok-home"
    env, profile_dir = _grok_cli_environment(
        worker_home,
        base={
            "HOME": "/root",
            "GROK_HOME": "/wrong-profile",
            "XAI_API_KEY": "must-not-reach-cli",
            "GROK_DEPLOYMENT_KEY": "must-not-reach-cli",
            "SAFE_VALUE": "preserved",
        },
    )
    assert profile_dir == worker_home / ".grok"
    assert env["HOME"] == str(worker_home)
    assert env["GROK_HOME"] == str(profile_dir)
    assert env["SAFE_VALUE"] == "preserved"
    assert "XAI_API_KEY" not in env
    assert "GROK_DEPLOYMENT_KEY" not in env


def test_docker_grok_catalog_binding_tracks_only_selected_model_semantics() -> None:
    from services.agent_runtime.grok_build_docker_worker import _model_capability_binding

    base = {
        "origin": "https://cli-chat-proxy.grok.com/v1/models",
        "auth_method": "session",
        "server_model_ids": [COMPOSER_MODEL, "grok-4.5"],
        "requested_server_entry_sha256": "a" * 64,
    }
    first = _model_capability_binding(
        requested_model=COMPOSER_MODEL,
        cli_version="0.2.102",
        merged_cli_model_ids=[COMPOSER_MODEL, "grok-4.5"],
        authenticated_catalog=base,
    )
    unrelated_added = _model_capability_binding(
        requested_model=COMPOSER_MODEL,
        cli_version="0.2.102",
        merged_cli_model_ids=[COMPOSER_MODEL, "grok-4.5", "unrelated"],
        authenticated_catalog={
            **base,
            "server_model_ids": [*base["server_model_ids"], "unrelated"],
        },
    )
    selected_changed = _model_capability_binding(
        requested_model=COMPOSER_MODEL,
        cli_version="0.2.102",
        merged_cli_model_ids=[COMPOSER_MODEL, "grok-4.5"],
        authenticated_catalog={**base, "requested_server_entry_sha256": "b" * 64},
    )
    profile_filtered = _model_capability_binding(
        requested_model=COMPOSER_MODEL,
        cli_version="0.2.102",
        merged_cli_model_ids=["grok-4.5"],
        authenticated_catalog=base,
    )
    assert first["requested_model_available"] is True
    assert first["sha256"] == unrelated_added["sha256"]
    assert first["sha256"] != selected_changed["sha256"]
    assert profile_filtered["requested_model_available"] is False
    assert first["sha256"] != profile_filtered["sha256"]


def test_docker_grok_replay_carries_fresh_catalog_observation() -> None:
    from services.agent_runtime.grok_build_docker_worker import (
        _bind_replay_capability_observation,
    )

    observation = {
        "binding_sha256": "a" * 64,
        "authenticated_catalog": {"fetched_at": "fresh"},
    }
    replayed = _bind_replay_capability_observation(
        {"ok": True, "result_text": "prior", "replayed": False}, observation
    )
    assert replayed["ok"] is True
    assert replayed["replayed"] is True
    assert replayed["replay_model_capability_observation"] == observation
    assert replayed["replay_model_capability_binding_sha256"] == "a" * 64


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("stale", "catalog is stale"),
        ("version", "CLI version mismatch"),
        ("auth", "auth mismatch"),
        ("timezone", "has no timezone"),
        ("malformed_entry", "requested entry is invalid"),
    ],
)
def test_docker_grok_catalog_rejects_invalid_cache_semantics(
    tmp_path: Path, case: str, message: str
) -> None:
    from services.agent_runtime.grok_build_docker_worker import (
        DockerGrokPermanentError,
        _authenticated_model_catalog,
    )

    now = datetime.now(UTC)
    payload = {
        "fetched_at": now.isoformat(),
        "grok_version": "0.2.102",
        "auth_method": "session",
        "origin": "https://cli-chat-proxy.grok.com/v1/models",
        "models": {COMPOSER_MODEL: {"id": COMPOSER_MODEL}},
    }
    if case == "stale":
        payload["fetched_at"] = (now - timedelta(seconds=301)).isoformat()
    elif case == "version":
        payload["grok_version"] = "0.2.101"
    elif case == "auth":
        payload["auth_method"] = "api_key"
    elif case == "timezone":
        payload["fetched_at"] = now.replace(tzinfo=None).isoformat()
    elif case == "malformed_entry":
        payload["models"] = {COMPOSER_MODEL: "not-an-object"}
    catalog = tmp_path / "models_cache.json"
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DockerGrokPermanentError, match=message):
        _authenticated_model_catalog(
            catalog,
            requested_model=COMPOSER_MODEL,
            cli_version="0.2.102",
            observed_at=now,
        )


def test_docker_grok_rules_snapshot_binds_every_required_source(tmp_path: Path) -> None:
    from services.agent_runtime.grok_build_docker_worker import _rules_snapshot

    first = tmp_path / "AGENTS.md"
    second = tmp_path / "constitution.txt"
    first.write_text("current rules", encoding="utf-8")
    second.write_text("current constitution", encoding="utf-8")
    snapshot = _rules_snapshot((first, second))
    assert snapshot["schema_version"] == "xinao.grok.rules_snapshot.v1"
    assert len(snapshot["files"]) == 2
    second.write_text("changed constitution", encoding="utf-8")
    assert _rules_snapshot((first, second))["sha256"] != snapshot["sha256"]


def test_docker_grok_maps_both_live_repo_identities_to_app_mount() -> None:
    from services.agent_runtime.grok_build_docker_worker import _map_host_path_to_container

    assert _map_host_path_to_container(r"E:\XINAO_RESEARCH_WORKSPACES\S") == "/app"
    assert (
        _map_host_path_to_container(
            r"E:\XINAO_RESEARCH_WORKSPACES\nianhua-new-route-active\projects"
        )
        == "/app/projects"
    )
    assert (
        _map_host_path_to_container(r"D:\XINAO_RESEARCH_RUNTIME\state\evidence")
        == "/evidence/state/evidence"
    )
    with pytest.raises(ValueError, match="not mounted"):
        _map_host_path_to_container(r"E:\some-unmounted-repository")


def test_docker_grok_creates_session_once_then_resumes_on_activity_retry() -> None:
    from services.agent_runtime.grok_build_docker_worker import (
        _cli_failure_kind,
        _decode_cli_payload,
        _output_contract_recovery_prompt,
        _recoverable_effective_output_result,
        _recoverable_incomplete_result,
        _recovery_prompt,
        _retryable_session_lock,
        _safe_cli_summary,
        _session_cli_args,
    )

    session_id = "dd6e80d7-4ff6-59e8-800a-4ebb891bad11"
    assert _session_cli_args(session_id, attempt=1) == ["--session-id", session_id]
    assert _session_cli_args(session_id, attempt=2) == ["--resume", session_id]
    assert _session_cli_args(session_id, attempt=1, resume=True) == ["--resume", session_id]
    locked = b"Error: Session ID example is already in use."
    assert _retryable_session_lock(locked, attempt=1, retries=0) is False
    assert _retryable_session_lock(locked, attempt=2, retries=0) is True
    assert _retryable_session_lock(locked, attempt=2, retries=3) is False
    assert _retryable_session_lock(b"authentication failed", attempt=2, retries=0) is False

    cancelled_stdout = json.dumps(
        {
            "text": "",
            "stopReason": "Cancelled",
            "sessionId": session_id,
            "requestId": "request-1",
            "usage": {"total_tokens": 10_899},
            "modelUsage": {GROK_BACKEND_BUILD: {"modelCalls": 1}},
        }
    ).encode()
    cancelled = _decode_cli_payload(cancelled_stdout)
    assert _cli_failure_kind(b"Error: max turns reached", cancelled) == "session_incomplete"
    assert _recoverable_incomplete_result(
        cancelled,
        requested_model=COMPOSER_MODEL,
        session_id=session_id,
        model_identity_ok=True,
    )
    completed = {
        **cancelled,
        "text": '```json\n{"wrong":true}\n```',
        "stopReason": "EndTurn",
    }
    assert _recoverable_effective_output_result(
        completed,
        requested_model=COMPOSER_MODEL,
        session_id=session_id,
        model_identity_ok=True,
    )
    correction = _output_contract_recovery_prompt(
        result_format="json_object",
        result_json_schema={
            "type": "object",
            "properties": {"status": {"const": "READY"}},
            "required": ["status"],
            "additionalProperties": False,
        },
        required_result_markers=("READY",),
    )
    assert "no Markdown fence" in correction
    assert '"required":["status"]' in correction
    assert "tool calls" in correction
    summary = _safe_cli_summary(
        cancelled,
        requested_model=COMPOSER_MODEL,
        return_code=1,
        stdout=cancelled_stdout,
        stderr=b"Error: max turns reached",
    )
    assert summary["failure_kind"] == "session_incomplete"
    assert summary["usage"]["total_tokens"] == 10_899
    assert summary["observed_models"] == [GROK_BACKEND_BUILD]
    assert "text" not in summary
    assert "message" not in summary
    forged_summary = _safe_cli_summary(
        {
            **cancelled,
            "modelUsage": {COMPOSER_MODEL: {"modelCalls": 1}},
        },
        requested_model=COMPOSER_MODEL,
        return_code=0,
        stdout=cancelled_stdout,
        stderr=b"",
    )
    assert forged_summary["observed_models"] == [COMPOSER_MODEL]
    assert forged_summary["model_identity_ok"] is False
    recovery = _recovery_prompt()
    assert "without repeating" in recovery
    assert "Current intake" not in recovery

    zero_rc_summary = _safe_cli_summary(
        cancelled,
        requested_model=COMPOSER_MODEL,
        return_code=0,
        stdout=cancelled_stdout,
        stderr=b"",
    )
    assert zero_rc_summary["failure_kind"] == "session_incomplete"


def test_docker_grok_lane_limits_and_capabilities_are_dynamic_and_bounded() -> None:
    from services.agent_runtime.grok_build_docker_worker import (
        _cli_capability_args,
        _lane_capability_policy,
        _lane_execution_limits,
    )

    limits = _lane_execution_limits(
        {
            "deadline_seconds": 900,
            "max_turns": 32,
            "max_recovery_continuations": 4,
        }
    )
    assert limits == {
        "deadline_seconds": 900,
        "max_turns": 32,
        "max_recovery_continuations": 4,
    }
    assert (
        _lane_execution_limits({"deadline_seconds": 99_999, "max_turns": 99})["deadline_seconds"]
        == 7_200
    )
    assert _lane_execution_limits({"deadline_seconds": 99_999, "max_turns": 99})["max_turns"] == 40

    enabled = _lane_capability_policy(
        {"planning": "auto", "subagents": "auto", "external_research": True}
    )
    enabled_args = _cli_capability_args(enabled)
    assert "--no-plan" not in enabled_args
    assert "--no-subagents" not in enabled_args
    assert "--disable-web-search" not in enabled_args
    assert "--no-memory" not in enabled_args

    assert _cli_capability_args(_lane_capability_policy({})) == []
    disabled_args = _cli_capability_args(
        _lane_capability_policy(
            {
                "planning": "off",
                "subagents": "off",
                "external_research": "off",
                "memory": "off",
            }
        )
    )
    assert {
        "--no-plan",
        "--no-subagents",
        "--disable-web-search",
        "--no-memory",
    }.issubset(disabled_args)


def test_docker_grok_invocation_accounting_includes_cancelled_and_prior_attempts() -> None:
    from services.agent_runtime.grok_build_docker_worker import _aggregate_invocation_usage

    accounting = _aggregate_invocation_usage(
        [
            {
                "return_code": 1,
                "stop_reason": "Cancelled",
                "usage": {"total_tokens": 233_542, "input_tokens": 200_000},
            },
            {
                "return_code": 0,
                "stop_reason": "EndTurn",
                "usage": {"total_tokens": 77_622, "input_tokens": 70_000},
                "effective_output_accepted": True,
            },
            {
                "return_code": 0,
                "stop_reason": "EndTurn",
                "usage": {"total_tokens": 4_000, "input_tokens": 3_000},
                "effective_output_accepted": False,
            },
        ]
    )
    assert accounting["invocation_count"] == 3
    assert accounting["total_tokens"] == 315_164
    assert accounting["accepted_tokens"] == 77_622
    assert accounting["cancelled_tokens"] == 233_542
    assert accounting["failed_tokens"] == 4_000


def test_docker_grok_defaults_do_not_impose_turn_cap_or_invent_work() -> None:
    from services.agent_runtime.grok_build_docker_worker import (
        DEFAULT_MAX_TURNS,
        _lane_execution_limits,
        run_docker_native_grok_fanin,
    )

    assert DEFAULT_MAX_TURNS >= 2
    assert _lane_execution_limits({})["max_turns"] is None
    source = inspect.getsource(run_docker_native_grok_fanin)
    assert "explicit positive-benefit ready_frontier" in source
    assert "_default_frontier" not in source


def test_docker_grok_fanin_missing_model_fails_before_provider_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from services.agent_runtime import grok_build_docker_worker as docker_worker

    provider_calls: list[dict] = []

    async def forbidden_provider(**kwargs: object) -> dict:
        provider_calls.append(dict(kwargs))
        raise AssertionError("provider adapter ran before explicit model admission")

    monkeypatch.setattr(docker_worker, "docker_native_grok_enabled", lambda: True)
    monkeypatch.setattr(docker_worker, "_execute_lane", forbidden_provider)
    input_path = tmp_path / "input.md"
    input_path.write_text("frozen input", encoding="utf-8")
    runtime_root = tmp_path / "runtime"

    with pytest.raises(ValueError, match="explicit supervisor-selected model"):
        asyncio.run(
            docker_worker.run_docker_native_grok_fanin(
                runtime_root=runtime_root,
                workflow_id="wf-missing-model",
                input_path=input_path,
                content_md="frozen input",
                ready_frontier=[
                    {
                        "lane_id": "missing-model",
                        "prompt": "must fail closed",
                    }
                ],
                serial_reason="one negative model-admission unit",
            )
        )

    assert provider_calls == []
    assert not (runtime_root / "state" / "grok_docker_native").exists()


def test_docker_grok_fanin_missing_cwd_fails_before_provider_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from services.agent_runtime import grok_build_docker_worker as docker_worker

    provider_calls: list[dict] = []

    async def forbidden_provider(**kwargs: object) -> dict:
        provider_calls.append(dict(kwargs))
        raise AssertionError("provider adapter ran before explicit cwd admission")

    monkeypatch.setattr(docker_worker, "docker_native_grok_enabled", lambda: True)
    monkeypatch.setattr(docker_worker, "_execute_lane", forbidden_provider)
    input_path = tmp_path / "input.md"
    input_path.write_text("frozen input", encoding="utf-8")

    with pytest.raises(ValueError, match="explicit supervisor-selected cwd"):
        asyncio.run(
            docker_worker.run_docker_native_grok_fanin(
                runtime_root=tmp_path / "runtime",
                workflow_id="wf-missing-cwd",
                input_path=input_path,
                content_md="frozen input",
                ready_frontier=[
                    {
                        "lane_id": "missing-cwd",
                        "prompt": "must fail closed",
                        "model": "grok-4.5",
                    }
                ],
                serial_reason="one negative cwd-admission unit",
            )
        )

    assert provider_calls == []


def test_docker_grok_fanin_invalid_selection_fails_before_provider_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from services.agent_runtime import grok_build_docker_worker as docker_worker

    provider_calls: list[dict] = []

    async def forbidden_provider(**kwargs: object) -> dict:
        provider_calls.append(dict(kwargs))
        raise AssertionError("provider adapter ran before selection admission")

    monkeypatch.setattr(docker_worker, "docker_native_grok_enabled", lambda: True)
    monkeypatch.setattr(docker_worker, "_execute_lane", forbidden_provider)
    input_path = tmp_path / "input.md"
    input_path.write_text("frozen input", encoding="utf-8")
    wrong = _supervisor_decision("grok-composer-2.5-fast")

    with pytest.raises(ValueError, match="selection receipt is invalid"):
        asyncio.run(
            docker_worker.run_docker_native_grok_fanin(
                runtime_root=tmp_path / "runtime",
                workflow_id="wf-selection-mismatch",
                input_path=input_path,
                content_md="frozen input",
                ready_frontier=[
                    {
                        "lane_id": "selected-model",
                        "prompt": "must fail closed",
                        "model": "grok-4.5",
                        "cwd": "/app",
                    }
                ],
                serial_reason="one negative selection-binding unit",
                supervisor_worker_decision=wrong,
                supervisor_selection_required=True,
            )
        )

    assert provider_calls == []


def test_integrated_bus_rejects_invalid_required_selection_before_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from services.agent_runtime import integrated_bus_graph as graph

    monkeypatch.setattr(
        graph,
        "run_validate_bus",
        lambda **kwargs: {"validate_ok": True, "validation_input": kwargs},
    )
    invalid = _supervisor_decision("grok-4.5")
    invalid["decision_sha256"] = "0" * 64
    input_path = tmp_path / "input.md"
    input_path.write_text("frozen input", encoding="utf-8")

    result = asyncio.run(
        graph._validate_node_impl(
            {
                "input_path": str(input_path),
                "content_md": "frozen input",
                "runtime_root": str(tmp_path),
                "repo_root": str(REPO_ROOT),
                "workflow_id": "wf-invalid-selection",
                "grok_ready_frontier": [
                    {
                        "lane_id": "lane-a",
                        "prompt": "must not invoke",
                        "model": "grok-4.5",
                        "cwd": "/app",
                    }
                ],
                "supervisor_selection_required": True,
                "supervisor_worker_decision": invalid,
            },
            propagate_transient=True,
        )
    )

    assert result["supervisor_selection_ok"] is False
    assert result["model_worker_named_blocker"] == "SUPERVISOR_SELECTION_INVALID"
    assert result["provider_invocation_performed"] is False
    assert result["model_invocation_performed"] is False


def test_temporal_bus_state_decodes_missing_supervisor_receipt_for_fail_closed_validation() -> None:
    from services.agent_runtime import integrated_bus_graph as graph
    from temporalio.converter import DefaultPayloadConverter

    converter = DefaultPayloadConverter()
    value = {
        "workflow_id": "wf-missing-selection",
        "supervisor_selection_required": True,
        "supervisor_worker_decision": None,
    }

    decoded = converter.from_payload(converter.to_payload(value), graph.BusState)

    assert decoded["supervisor_worker_decision"] is None


@pytest.mark.parametrize("model", [COMPOSER_MODEL, "grok-4.5"])
def test_docker_grok_fanin_passes_each_explicit_model_unchanged_to_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    import asyncio

    from services.agent_runtime import grok_build_docker_worker as docker_worker

    admitted_models: list[str] = []

    async def record_provider_selection(
        *,
        root: Path,
        workflow_id: str,
        lane: dict,
        intake: str,
    ) -> dict:
        del root, intake
        admitted_models.append(str(lane["model"]))
        return {
            "ok": False,
            "provider_id": docker_worker.PROVIDER_ID,
            "workflow_id": workflow_id,
            "lane_id": lane["lane_id"],
            "mode": lane["mode"],
            "model": lane["model"],
            "requested_model": lane["model"],
            "observed_model": "",
            "observed_models": [],
            "observed_backend_models": [],
            "model_identity_ok": False,
            "operation_state": "failed",
            "result_text": "",
            "invocation_accounting": {
                "invocation_count": 0,
                "total_tokens": 0,
                "accepted_tokens": 0,
                "cancelled_tokens": 0,
                "failed_tokens": 0,
            },
            "execution_location": "docker:houtai-gongren",
        }

    monkeypatch.setattr(docker_worker, "docker_native_grok_enabled", lambda: True)
    monkeypatch.setattr(docker_worker, "_execute_lane", record_provider_selection)
    input_path = tmp_path / "input.md"
    input_path.write_text("frozen input", encoding="utf-8")
    decision = _supervisor_decision(model)

    result = asyncio.run(
        docker_worker.run_docker_native_grok_fanin(
            runtime_root=tmp_path / "runtime",
            workflow_id=f"wf-{model}",
            input_path=input_path,
            content_md="frozen input",
            ready_frontier=[
                {
                    "lane_id": "selected-model",
                    "prompt": "preserve the supervisor selection",
                    "model": model,
                    "cwd": "/app",
                }
            ],
            serial_reason="one selected provider unit",
            supervisor_worker_decision=decision,
            supervisor_selection_required=True,
        )
    )

    assert admitted_models == [model]
    assert result["grok_fanin_requested_model"] == model
    assert result["grok_lanes"][0]["requested_model"] == model
    assert result["supervisor_worker_decision_sha256"] == decision["decision_sha256"]
    assert (
        result["grok_fanin"]["supervisor_worker_decision_sha256"] == (decision["decision_sha256"])
    )
    assert result["fallback_model_invocation_performed"] is False


def test_docker_grok_output_contract_hashes_exact_artifact_schema_bytes() -> None:
    from services.agent_runtime.grok_build_docker_worker import _lane_output_contract

    schema = {
        "type": "object",
        "properties": {"work_key": {"type": "string"}},
        "required": ["work_key"],
    }
    contract = _lane_output_contract({"result_format": "json_object", "result_json_schema": schema})
    artifact_digest = hashlib.sha256(artifact_json_bytes(schema)).hexdigest()

    assert contract["result_json_schema_sha256"] == artifact_digest
    assert artifact_digest != hashlib.sha256(canonical_json_bytes(schema)).hexdigest()


def test_docker_grok_receives_current_project_rules_read_only() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/AGENTS.md:/app/AGENTS.md:ro" in compose
    assert "}:/mainline:ro" in compose
    assert "/projects:/app/projects:ro" in compose
    assert "/scripts:/app/scripts:ro" in compose
    assert "GROK_HOME: /grok-home/.grok" in compose


def test_docker_grok_operation_binding_and_cache_cover_execution_inputs(
    tmp_path: Path,
) -> None:
    from services.agent_runtime.grok_build_docker_worker import (
        _cached_lane,
        _operation_id,
    )

    common = {
        "execution_prompt_sha256": "a" * 64,
        "mode": "audit",
        "cwd": "/app",
        "write": False,
        "max_turns": 4,
        "deadline_seconds": 240,
        "correlation_id": "corr",
        "parent_operation_id": "parent",
        "contract_id": "contract",
        "allowed_tools": ("read_file",),
    }
    operation_id = _operation_id("wf", "lane", "b" * 64, COMPOSER_MODEL, **common)
    changed_intake = _operation_id(
        "wf",
        "lane",
        "b" * 64,
        COMPOSER_MODEL,
        **{**common, "execution_prompt_sha256": "c" * 64},
    )
    changed_cwd = _operation_id(
        "wf",
        "lane",
        "b" * 64,
        COMPOSER_MODEL,
        **{**common, "cwd": "/evidence/worktrees/lane"},
    )
    changed_tools = _operation_id(
        "wf",
        "lane",
        "b" * 64,
        COMPOSER_MODEL,
        **{**common, "allowed_tools": ("grep", "read_file")},
    )
    changed_capability = _operation_id(
        "wf",
        "lane",
        "b" * 64,
        COMPOSER_MODEL,
        **{**common, "external_research": True},
    )
    changed_output_contract = _operation_id(
        "wf",
        "lane",
        "b" * 64,
        COMPOSER_MODEL,
        **{**common, "result_format": "json_object", "min_result_chars": 1_000},
    )
    assert (
        len(
            {
                operation_id,
                changed_intake,
                changed_cwd,
                changed_tools,
                changed_capability,
                changed_output_contract,
            }
        )
        == 6
    )

    operation_root = tmp_path / operation_id
    identity = operation_root / "cli_result.json"
    identity.parent.mkdir(parents=True)
    identity.write_text(
        json.dumps({"modelUsage": {GROK_BACKEND_BUILD: {"modelCalls": 1}}}),
        encoding="utf-8",
    )
    identity_sha = hashlib.sha256(identity.read_bytes()).hexdigest()
    session_id = "session-lane"
    session_evidence = _session_model_evidence(COMPOSER_MODEL, session_id)
    session_evidence_path = operation_root / "session_model_evidence.json"
    session_evidence_path.write_bytes(artifact_json_bytes(session_evidence))
    session_evidence_sha = hashlib.sha256(session_evidence_path.read_bytes()).hexdigest()
    common_contract, common_receipt, common_receipt_sha256 = _common_execution_evidence(
        "lane",
        operation_id=operation_id,
    )
    common_receipt["provider_evidence_ref"] = str(identity)
    common_receipt["provider_evidence_sha256"] = identity_sha
    common_receipt_sha256 = hashlib.sha256(artifact_json_bytes(common_receipt)).hexdigest()
    receipt_path = operation_root / "attempt_receipt.json"
    receipt_path.write_bytes(
        (json.dumps(common_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )
    operation_spec = operation_root / "operation-spec.json"
    operation_spec.write_text("{}", encoding="utf-8")
    operation_spec_sha = hashlib.sha256(operation_spec.read_bytes()).hexdigest()
    final = operation_root / "final.txt"
    final.write_text("verified cached result", encoding="utf-8")
    final_sha = hashlib.sha256(final.read_bytes()).hexdigest()
    manifest = operation_root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "state": "completed",
                "operation_spec_sha256": operation_spec_sha,
                "lane_result": {
                    "ok": True,
                    "execution_contract_version": GROK_EXECUTION_CONTRACT_VERSION,
                    "model_policy_id": GROK_MODEL_POLICY_ID,
                    "operation_id": operation_id,
                    "requested_model": COMPOSER_MODEL,
                    "observed_model": GROK_BACKEND_BUILD,
                    "observed_models": [GROK_BACKEND_BUILD],
                    "observed_backend_models": [GROK_BACKEND_BUILD],
                    "model_identity_binding": grok_docker_model_identity_binding(COMPOSER_MODEL),
                    "model_identity_ok": True,
                    "session_model_evidence": session_evidence,
                    "session_model_evidence_valid": True,
                    "session_model_evidence_ref": str(session_evidence_path),
                    "session_model_evidence_sha256": session_evidence_sha,
                    "agent_session_id": session_id,
                    "stop_reason": "EndTurn",
                    "result_text": "verified cached result",
                    "result_text_sha256": final_sha,
                    "final_ref": str(final),
                    "prompt_sha256": "b" * 64,
                    "execution_prompt_sha256": "a" * 64,
                    "operation_spec_ref": str(operation_spec),
                    "operation_spec_sha256": operation_spec_sha,
                    "model_identity_ref": str(identity),
                    "model_identity_sha256": identity_sha,
                    "model_capability_ok": True,
                    "requested_rules_snapshot_sha256": "b" * 64,
                    "observed_rules_snapshot_sha256": "b" * 64,
                    "rules_snapshot_ok": True,
                    "rules_projection_ok": True,
                    "invocation_accounting": {
                        "invocation_count": 1,
                        "total_tokens": 100,
                        "accepted_tokens": 100,
                        "cancelled_tokens": 0,
                        "failed_tokens": 0,
                    },
                    "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
                    "cross_seam_attempt_receipt_version": ATTEMPT_RECEIPT_VERSION,
                    "cross_seam_contract_sha256": logical_contract_sha256(common_contract),
                    "cross_seam_logical_contract": common_contract,
                    "cross_seam_attempt_receipt": common_receipt,
                    "cross_seam_attempt_receipt_ref": str(receipt_path),
                    "cross_seam_attempt_receipt_sha256": common_receipt_sha256,
                },
            }
        ),
        encoding="utf-8",
    )
    assert (
        _cached_lane(
            manifest,
            operation_id=operation_id,
            requested_model=COMPOSER_MODEL,
            prompt_sha256="b" * 64,
            execution_prompt_sha256="a" * 64,
            operation_spec_sha256=operation_spec_sha,
        )
        is not None
    )
    assert (
        _cached_lane(
            manifest,
            operation_id=operation_id,
            requested_model=COMPOSER_MODEL,
            prompt_sha256="b" * 64,
            execution_prompt_sha256="a" * 64,
            operation_spec_sha256="spec-b",
        )
        is None
    )

    forged = json.loads(manifest.read_text(encoding="utf-8"))
    identity.write_text(
        json.dumps({"modelUsage": {COMPOSER_MODEL: {"modelCalls": 1}}}),
        encoding="utf-8",
    )
    forged_identity_sha = hashlib.sha256(identity.read_bytes()).hexdigest()
    forged_receipt = forged["lane_result"]["cross_seam_attempt_receipt"]
    forged_receipt["provider_evidence_sha256"] = forged_identity_sha
    receipt_path.write_bytes(artifact_json_bytes(forged_receipt))
    forged["lane_result"]["model_identity_sha256"] = forged_identity_sha
    forged["lane_result"]["cross_seam_attempt_receipt_sha256"] = hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    manifest.write_text(json.dumps(forged), encoding="utf-8")
    assert (
        _cached_lane(
            manifest,
            operation_id=operation_id,
            requested_model=COMPOSER_MODEL,
            prompt_sha256="b" * 64,
            execution_prompt_sha256="a" * 64,
            operation_spec_sha256=operation_spec_sha,
        )
        is None
    )


def test_docker_grok_late_failure_cannot_downgrade_completed_manifest(
    tmp_path: Path,
) -> None:
    from services.agent_runtime.grok_build_docker_worker import _record_operation_failure

    manifest = tmp_path / "operations" / "op" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"state": "completed", "revision": 9, "lease_token": "current"}),
        encoding="utf-8",
    )
    before = manifest.read_bytes()
    _record_operation_failure(
        root=tmp_path,
        workflow_id="wf",
        lane={
            "_operation_manifest_path": str(manifest),
            "_lease_token": "stale",
        },
        exc=RuntimeError("late failure"),
    )
    assert manifest.read_bytes() == before


def test_only_docker_grok_validate_activity_has_fast_worker_loss_detection() -> None:
    from services.agent_runtime.integrated_bus_graph import _activity_options

    assert "heartbeat_timeout" not in _activity_options()
    assert _activity_options(heartbeat=True)["heartbeat_timeout"].total_seconds() == 15
    recovery = _activity_options(heartbeat=True, grok_retry=True)
    assert recovery["start_to_close_timeout"].total_seconds() == 7_380
    assert recovery["schedule_to_close_timeout"].total_seconds() == 22_500
    assert recovery["retry_policy"].maximum_attempts == 3
    assert "DockerGrokPermanentError" in recovery["retry_policy"].non_retryable_error_types


def test_docker_native_manifest_is_consumed_without_host_prefan_marker(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_graph import _grok_fanin_worker_lane

    runtime = tmp_path / "runtime"
    input_path = runtime / "input.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_text("docker native intake", encoding="utf-8")
    manifest_path = runtime / "state" / "grok_docker_native" / "wf" / "fanin.json"
    manifest_path.parent.mkdir(parents=True)
    manifest = _attested_grok_manifest(input_path, [("native", "audit")], workflow_id="wf")
    manifest.update(
        {
            "execution_location": "docker:houtai-gongren",
            "container_id": "container-1",
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    lane = _grok_fanin_worker_lane(
        {
            "runtime_root": str(runtime),
            "repo_root": str(REPO_ROOT),
            "workflow_id": "wf",
            "input_path": str(input_path),
            "content_md": "plain original intake without host marker",
            "grok_fanin_manifest_ref": str(manifest_path),
        }
    )
    assert lane is not None
    assert lane["worker_lane_ok"] is True
    assert lane["worker_lane_model"] == COMPOSER_MODEL
    assert lane["worker_lane_adapter"] == "grok_build_cli_docker_native"
    assert lane["grok_execution_location"] == "docker:houtai-gongren"


def test_docker_native_manifest_rejects_unbound_receipt_digest(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_graph import _grok_fanin_worker_lane

    runtime = tmp_path / "runtime"
    input_path = runtime / "input.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_text("docker native intake", encoding="utf-8")
    manifest_path = runtime / "fanin.json"
    manifest = _attested_grok_manifest(input_path, [("native", "audit")], workflow_id="wf")
    forged_digest = "f" * 64
    manifest["lanes"][0]["cross_seam_attempt_receipt_sha256"] = forged_digest
    manifest["cross_seam_receipt_bindings"][0]["attempt_receipt_sha256"] = forged_digest
    manifest["cross_seam_receipt_set_sha256"] = hashlib.sha256(
        canonical_json_bytes(manifest["cross_seam_receipt_bindings"])
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    lane = _grok_fanin_worker_lane(
        {
            "runtime_root": str(runtime),
            "repo_root": str(REPO_ROOT),
            "workflow_id": "wf",
            "input_path": str(input_path),
            "content_md": "plain original intake without host marker",
            "grok_fanin_manifest_ref": str(manifest_path),
        }
    )

    assert lane is not None
    assert lane["worker_lane_ok"] is False
    assert lane["worker_lane_named_blocker"] == "GROK_FANIN_COMMON_RECEIPT_INVALID"


def test_integrated_bus_json_output_survives_narrow_windows_console_codec() -> None:
    from services.agent_runtime.integrated_bus_runner import _write_json_payload

    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="gbk", errors="strict")
    _write_json_payload({"message": "Grok result 🚀"}, stream=stream)
    stream.flush()
    emitted = buffer.getvalue().decode("gbk")
    assert json.loads(emitted) == {"message": "Grok result 🚀"}


def test_integrated_bus_promotion_slice_contract() -> None:
    from services.agent_runtime.integrated_bus_graph import GRAPH_ID
    from services.agent_runtime.integrated_bus_promotion_gate import (
        evaluate_current_promotion,
    )
    from services.agent_runtime.integrated_bus_runner import SENTINEL
    from services.agent_runtime.thin_glue_sunset_registry import summarize_sunset_registry

    assert GRAPH_ID == "xinao-integrated-bus-v2"
    assert SENTINEL == "SENTINEL:XINAO_INTEGRATED_BUS_RUNNER_READY"
    assert summarize_sunset_registry().get("handroll_intact") is False
    workflow_id = "wf-current"
    fanin_ref = "/evidence/state/source_ledger/integrated_bus/fanin.json"
    fanin_sha256 = "f" * 64
    aaq_sha256 = "a" * 64
    state = {
        "workflow_id": workflow_id,
        "worker_lane_provider": "grok_acpx_headless",
        "validate_ok": True,
        "worker_lane_ok": True,
        "grok_fanin_ok": True,
        "provider_fanin_ok": True,
        "fanin_ok": True,
        "worker_lane_cross_seam_receipt_ok": True,
        "worker_lane_cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "worker_lane_cross_seam_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "worker_lane_cross_seam_receipt_set_sha256": "9" * 64,
        "fanin_evidence_ref": fanin_ref,
        "fanin_evidence_sha256": fanin_sha256,
        "aaq_claim_sha256": aaq_sha256,
    }
    ledger = {
        "workflow_id": workflow_id,
        "worker_lane_provider": "grok_acpx_headless",
        "validate_ok": True,
        "worker_lane_ok": True,
        "grok_fanin_ok": True,
        "provider_fanin_ok": True,
        "provider_validator_id": "xinao.grok.shared_execution_contract.v1",
        "provider_evidence_bound": True,
        "provider_evidence_sha256": "e" * 64,
        "cross_seam_receipt_ok": True,
        "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "cross_seam_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "cross_seam_receipt_set_sha256": "9" * 64,
        "substantive_lane_ok": True,
        "fanin_ok": True,
    }
    aaq = {
        "workflow_id": workflow_id,
        "fanin_evidence_ref": fanin_ref,
        "fanin_evidence_sha256": fanin_sha256,
        "fanin_bound": True,
        "fanin_ok": True,
        "completion_claim_allowed": False,
    }
    checks = evaluate_current_promotion(
        state,
        workflow_id=workflow_id,
        fanin_ledger=ledger,
        aaq_claim=aaq,
        fanin_sha256=fanin_sha256,
        aaq_sha256=aaq_sha256,
    )
    assert all(checks.values())
    for field in ("validate_ok", "worker_lane_ok", "grok_fanin_ok", "fanin_ok"):
        rejected = evaluate_current_promotion(
            {**state, field: False},
            workflow_id=workflow_id,
            fanin_ledger=ledger,
            aaq_claim=aaq,
            fanin_sha256=fanin_sha256,
            aaq_sha256=aaq_sha256,
        )
        assert not all(rejected.values()), field
    unknown = evaluate_current_promotion(
        {
            **state,
            "worker_lane_provider": "totally-wrong-provider",
        },
        workflow_id=workflow_id,
        fanin_ledger={
            **ledger,
            "worker_lane_provider": "totally-wrong-provider",
        },
        aaq_claim=aaq,
        fanin_sha256=fanin_sha256,
        aaq_sha256=aaq_sha256,
    )
    assert unknown["current_provider_validator_known"] is False
    assert not all(unknown.values())


def test_promotion_gate_requires_bound_substantive_fanin_before_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.agent_runtime.integrated_bus_promotion_gate as gate

    monkeypatch.setattr(gate, "run_l5_pytest_verify", lambda **_: {"passed": True})
    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "source_ledger" / "integrated_bus" / "fanin.json"
    aaq = runtime / "state" / "aaq" / "integrated_bus" / "claim.json"
    fanin.parent.mkdir(parents=True)
    aaq.parent.mkdir(parents=True)
    workflow_id = "wf-bound"
    fanin.write_text(
        json.dumps(
            {
                "schema_version": "xinao.integrated_bus.fanin_slice.v1",
                "workflow_id": workflow_id,
                "worker_lane_provider": "grok_acpx_headless",
                "validate_ok": True,
                "worker_lane_ok": True,
                "grok_fanin_ok": True,
                "provider_fanin_ok": True,
                "provider_validator_id": "xinao.grok.shared_execution_contract.v1",
                "provider_evidence_bound": True,
                "provider_evidence_sha256": "e" * 64,
                "cross_seam_receipt_ok": True,
                "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
                "cross_seam_receipt_version": ATTEMPT_RECEIPT_VERSION,
                "cross_seam_receipt_set_sha256": "9" * 64,
                "substantive_lane_ok": True,
                "fanin_ok": True,
            }
        ),
        encoding="utf-8",
    )
    fanin_sha256 = hashlib.sha256(fanin.read_bytes()).hexdigest()
    aaq.write_text(
        json.dumps(
            {
                "schema_version": "xinao.integrated_bus.aaq_claim.v1",
                "workflow_id": workflow_id,
                "fanin_evidence_ref": str(fanin),
                "fanin_evidence_sha256": fanin_sha256,
                "fanin_bound": True,
                "fanin_ok": True,
                "completion_claim_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    aaq_sha256 = hashlib.sha256(aaq.read_bytes()).hexdigest()
    state = {
        "workflow_id": workflow_id,
        "gateway_trace_ok": True,
        "content_md": "substantive intake",
        "execution_stdout": "sandbox completed",
        "worker_lane_provider": "grok_acpx_headless",
        "validate_ok": True,
        "worker_lane_ok": False,
        "grok_fanin_ok": True,
        "provider_fanin_ok": True,
        "fanin_ok": True,
        "worker_lane_cross_seam_receipt_ok": True,
        "worker_lane_cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "worker_lane_cross_seam_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "worker_lane_cross_seam_receipt_set_sha256": "9" * 64,
        "fanin_evidence_ref": str(fanin),
        "fanin_evidence_sha256": fanin_sha256,
        "aaq_claim_ref": str(aaq),
        "aaq_claim_sha256": aaq_sha256,
    }
    rejected = gate.run_promotion_gate(
        state,
        runtime_root=runtime,
        repo_root=tmp_path,
        workflow_id=workflow_id,
    )
    assert rejected["validation"]["passed"] is False
    assert rejected["memory_promoted"] is False
    assert not (runtime / "state" / "memory_candidates").exists()

    accepted = gate.run_promotion_gate(
        {**state, "worker_lane_ok": True},
        runtime_root=runtime,
        repo_root=tmp_path,
        workflow_id=workflow_id,
    )
    assert accepted["validation"]["passed"] is True
    assert accepted["memory_promoted"] is True
    assert Path(accepted["memory_candidate_ref"]).is_file()
    assert (
        accepted["memory_candidate_sha256"]
        == hashlib.sha256(Path(accepted["memory_candidate_ref"]).read_bytes()).hexdigest()
    )
    from services.agent_runtime.integrated_bus_bus_nodes import run_memory_bus

    memory = run_memory_bus(
        runtime_root=runtime,
        state={
            "workflow_id": workflow_id,
            "memory_candidate_id": accepted["memory_candidate_id"],
            "memory_candidate_ref": accepted["memory_candidate_ref"],
            "memory_candidate_sha256": accepted["memory_candidate_sha256"],
        },
        params={"mem0_bind_enabled": False},
    )
    assert memory["memory_bus_ok"] is True
    memory_record = json.loads(Path(memory["memory_bus_ref"]).read_text(encoding="utf-8"))
    assert memory_record["replay_promoted"] is True


def test_memory_bus_rejects_forged_candidate_id_without_mem0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.agent_runtime import integrated_bus_bus_nodes as nodes

    def forbidden(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("mem0 must not run for an unbound candidate")

    monkeypatch.setattr(nodes, "_try_mem0_add", forbidden)
    result = nodes.run_memory_bus(
        runtime_root=tmp_path,
        state={
            "workflow_id": "wf-forged",
            "memory_candidate_id": "forged-id",
            "memory_candidate_ref": str(tmp_path / "missing.json"),
            "memory_candidate_sha256": "f" * 64,
        },
        params={"mem0_bind_enabled": True},
    )
    assert result["memory_bus_ok"] is False
    assert result["memory_named_blocker"] == "MEMORY_CANDIDATE_LINEAGE_INVALID"
    record = json.loads(Path(result["memory_bus_ref"]).read_text(encoding="utf-8"))
    assert record["replay_promoted"] is False


def test_integrated_bus_workflow_sandbox_prepares_with_selective_passthrough() -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import XinaoIntegratedBusWorkflow
    from services.agent_runtime.integrated_bus_runner import integrated_bus_workflow_runner
    from temporalio import workflow

    async def prepare() -> object:
        runner = integrated_bus_workflow_runner()
        definition = workflow._Definition.must_from_class(XinaoIntegratedBusWorkflow)
        runner.prepare_workflow(definition)
        return runner

    runner = asyncio.run(prepare())
    assert runner.restrictions.passthrough_all_modules is False
    assert {
        "langgraph",
        "langchain_core",
        "portalocker",
        "rich",
        "services.agent_runtime.integrated_bus_bus_nodes",
    }.issubset(runner.restrictions.passthrough_modules)


def test_integrated_bus_default_route_is_readonly_at_finalize() -> None:
    from services.agent_runtime.integrated_bus_graph import finalize_node

    params = json.loads(
        (REPO_ROOT / "materials/authority_glue/seams/integrated_bus_params.v1.json").read_text(
            encoding="utf-8"
        )
    )
    source = inspect.getsource(finalize_node)
    assert params["task_queue"] == "xinao-integrated-langgraph-plugin-queue"
    assert params["git_finalize_mode"] == "gitpython_readonly_snapshot"
    assert "git_commit_all" not in source
    assert 'runtime / "state" / "integrated_bus_proof"' in source


def test_parallel_lane_routing_accepts_explicit_same_tier() -> None:
    from services.agent_runtime.integrated_bus_runner import _parallel_lane_tier_routing_ok

    result = {
        "parallel_lane_models": [
            {
                "lane_id": 0,
                "task_id": "wf-lane-0",
                "model": "qwen3.6-flash",
                "tier_used": "tier_cheap_draft",
            },
            {
                "lane_id": 1,
                "task_id": "wf-lane-1",
                "model": "qwen3.6-flash",
                "tier_used": "tier_cheap_draft",
            },
        ]
    }
    assert _parallel_lane_tier_routing_ok(result) is True


@pytest.mark.parametrize(
    ("review_required", "pro_review_ok", "contract_satisfied", "expected"),
    [
        (False, False, True, True),
        (False, False, False, False),
        (True, False, False, False),
        (True, True, True, True),
    ],
)
def test_ephemeral_host_rescue_uses_review_contract_not_optional_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_required: bool,
    pro_review_ok: bool,
    contract_satisfied: bool,
    expected: bool,
) -> None:
    from services.agent_runtime import integrated_bus_runner as runner

    monkeypatch.setattr(runner, "_docker_worker_daemon_ready", lambda *_args, **_kwargs: True)
    result = {
        "worker_lane_ok": True,
        "review_required": review_required,
        "pro_review_ok": pro_review_ok,
        "pro_review_contract_satisfied": contract_satisfied,
    }

    observed = runner._resolve_docker_worker_enforced(
        invoke_mode="temporal_langgraph_plugin",
        worker_ownership="ephemeral_host",
        runtime_root=tmp_path,
        task_queue="queue",
        result=result,
    )

    assert observed is expected
    assert ("docker_worker_named_blocker" in result) is expected


def test_integrated_bus_worker_registry_contains_real_temporal_langgraph_route() -> None:
    from services.agent_runtime.integrated_bus_workflow_registry import registry_summary

    registry = registry_summary()
    expected_queues = {
        "xinao-integrated-langgraph-plugin-queue",
        "xinao-integrated-bus-parent-queue",
        "xinao-integrated-bus-child-queue",
        "xinao-mainline-canary-queue",
    }
    assert set(registry["task_queues"]) == expected_queues
    assert registry["langgraph_plugin_queues"] == ["xinao-integrated-langgraph-plugin-queue"]
    assert registry["workflows_registered"] == [
        "XinaoIntegratedBusWorkflow",
        "XinaoIntegratedBusParentWorkflow",
        "XinaoIntegratedBusChildWorkflow",
        "XinaoMainlineCanaryWorkflow",
        "XinaoResearchCampaignWorkflow",
        "FoundationContinuousWorkflowV1",
        "FoundationWaveChildWorkflowV1",
        "FoundationContinuousWorkflowV2",
    ]
    assert registry["activity_count"] == 10
    assert not any("ThinGlue" in name for name in registry["workflows_registered"])
    assert not any(queue.startswith("xinao-thin-glue-") for queue in registry["task_queues"])
    assert "xinao-integrated-bus-v2" in registry["graph_ids"]


def test_integrated_bus_worker_registry_allows_bounded_isolated_canary_queue(
    monkeypatch,
) -> None:
    from services.agent_runtime.integrated_bus_workflow_registry import registry_summary

    queue = "xinao-integrated-langgraph-plugin-queue-composer-canary"
    monkeypatch.setenv("XINAO_INTEGRATED_LANGGRAPH_TASK_QUEUE", queue)
    registry = registry_summary()
    assert queue in registry["task_queues"]
    assert registry["langgraph_plugin_queues"] == [queue]


def test_promoted_grok_fanin_bypasses_legacy_qwen_worker(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_PROVIDER,
        GROK_FANIN_SENTINEL,
        _grok_fanin_worker_lane,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    manifest = fanin / "manifest.json"
    intake = fanin / "input.md"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
        "Grok worker result\n"
    )
    intake.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(_attested_grok_manifest(intake, [("research", "research"), ("audit", "audit")])),
        encoding="utf-8",
    )
    lane = _grok_fanin_worker_lane(
        {
            "runtime_root": str(runtime),
            "repo_root": str(REPO_ROOT),
            "workflow_id": "parent-wf-langgraph-s0",
            "input_path": str(intake),
            "content_md": content,
        }
    )
    assert lane is not None
    assert lane["worker_lane_ok"] is True
    assert lane["worker_lane_provider"] == GROK_FANIN_PROVIDER
    assert lane["worker_lane_model"] == "grok-composer-2.5-fast"
    assert lane["grok_fanin_model_identity_ok"] is True
    assert lane["worker_lane_adapter"] == "grok_build_cli_docker_native"


def test_promoted_grok_fanin_rejects_backend_build_without_exact_composer_session(
    tmp_path: Path,
) -> None:
    from services.agent_runtime.integrated_bus_graph import _grok_raw_model_identity_valid

    runtime = tmp_path / "runtime"
    intake = runtime / "state" / "grok" / "input.md"
    intake.parent.mkdir(parents=True)
    intake.write_text("identity input", encoding="utf-8")
    manifest = _attested_grok_manifest(intake, [("audit", "audit")])
    lane = manifest["lanes"][0]
    assert _grok_raw_model_identity_valid(
        lane,
        requested_model=COMPOSER_MODEL,
        runtime=runtime,
        repo_root=REPO_ROOT,
    )

    session_evidence_path = Path(lane["session_model_evidence_ref"])
    forged_evidence = dict(lane["session_model_evidence"])
    forged_evidence["currentModelId"] = "grok-4.5"
    session_evidence_path.write_bytes(artifact_json_bytes(forged_evidence))
    lane["session_model_evidence"] = forged_evidence
    lane["session_model_evidence_sha256"] = hashlib.sha256(
        session_evidence_path.read_bytes()
    ).hexdigest()

    assert not _grok_raw_model_identity_valid(
        lane,
        requested_model=COMPOSER_MODEL,
        runtime=runtime,
        repo_root=REPO_ROOT,
    )


def test_promoted_grok_fanin_accepts_4_5_escalation_and_rejects_invalid_evidence(
    tmp_path: Path,
) -> None:
    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_PROVIDER,
        GROK_FANIN_SENTINEL,
        _grok_fanin_worker_lane,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    manifest = fanin / "manifest.json"
    intake = fanin / "input.md"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
    )
    intake.write_text(content, encoding="utf-8")
    base = _attested_grok_manifest(intake, [("one", "audit"), ("two", "audit")])
    escalated = _attested_grok_manifest(
        intake,
        [("one", "audit"), ("two", "audit")],
        model="grok-4.5",
    )
    manifest.write_text(json.dumps(escalated), encoding="utf-8")
    escalation_lane = _grok_fanin_worker_lane(
        {
            "runtime_root": str(runtime),
            "repo_root": str(REPO_ROOT),
            "workflow_id": "parent-wf-langgraph-s0",
            "input_path": str(intake),
            "content_md": content,
        }
    )
    assert escalation_lane is not None
    assert escalation_lane["worker_lane_ok"] is True
    assert escalation_lane["worker_lane_model"] == "grok-4.5"

    cases = [
        {**base, "model": "grok-unknown", "models": ["grok-unknown"]},
        {**base, "model_identity_ok": False},
        {**base, "succeeded": 1, "failed": 1},
    ]
    for payload in cases:
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        lane = _grok_fanin_worker_lane(
            {
                "runtime_root": str(runtime),
                "repo_root": str(REPO_ROOT),
                "workflow_id": "parent-wf-langgraph-s0",
                "input_path": str(intake),
                "content_md": content,
            }
        )
        assert lane is not None
        assert lane["worker_lane_ok"] is False
        assert lane["worker_lane_named_blocker"] == "GROK_FANIN_FULL_FRONTIER_OR_MODEL_INVALID"


def test_promoted_grok_fanin_rejects_cancelled_progress_text_as_fake_success(
    tmp_path: Path,
) -> None:
    from services.agent_runtime.integrated_bus_graph import _grok_fanin_worker_lane

    runtime = tmp_path / "runtime"
    input_path = runtime / "input.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_text("wave input", encoding="utf-8")
    manifest_path = runtime / "fanin.json"
    manifest = _attested_grok_manifest(
        input_path,
        [("accepted", "audit"), ("cancelled", "audit")],
        workflow_id="wf",
    )
    manifest["lanes"][1].update(
        {
            "stop_reason": "Cancelled",
            "result_text": "Gathering files and preparing the report...",
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    lane = _grok_fanin_worker_lane(
        {
            "runtime_root": str(runtime),
            "repo_root": str(REPO_ROOT),
            "workflow_id": "wf",
            "input_path": str(input_path),
            "grok_fanin_manifest_ref": str(manifest_path),
        }
    )
    assert lane is not None
    assert lane["worker_lane_ok"] is False
    assert lane["worker_lane_named_blocker"] == "GROK_FANIN_LANE_EFFECTIVE_OUTPUT_INVALID"


def test_route_parallel_send_never_creates_child_side_model_fanout() -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import route_parallel_send

    route = asyncio.run(
        route_parallel_send(
            {
                "content_md": "plain intake",
                "parallel_width_n": 2,
                "repo_root": str(REPO_ROOT),
                "runtime_root": str(REPO_ROOT),
                "workflow_id": "parent-wf",
            }
        )
    )
    assert route == "grok_worker_fanin"


def test_route_parallel_send_skips_send_for_grok_fanin_marker() -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_SENTINEL,
        route_parallel_send,
    )

    route = asyncio.run(
        route_parallel_send(
            {
                "content_md": f"<!-- {GROK_FANIN_SENTINEL} -->\n",
                "parallel_width_n": 2,
            }
        )
    )
    assert route == "grok_worker_fanin"


def test_hot_graph_registers_no_legacy_model_worker_nodes() -> None:
    from services.agent_runtime.integrated_bus_graph import BusState, make_integrated_graph

    graph = make_integrated_graph()
    node_names = set(graph.nodes)
    assert "grok_worker_fanin" in node_names
    assert not any(
        marker in node_name.lower()
        for node_name in node_names
        for marker in ("qwen", "deepseek", "ollama", "codex_subagent", "admin_worker")
    )
    assert {
        "selected_provider_fail_closed",
        "grok_fanin_ok",
        "grok_fanin_manifest_ref",
        "grok_fanin_lane_count",
        "non_grok_model_invocations",
        "fallback_model_invocation_performed",
        "memory_model_bind_frozen",
    }.issubset(BusState.__annotations__)


def test_selected_grok_adapter_fails_closed_without_valid_fanin() -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import (
        gateway_trace_node,
        grok_worker_fanin_node,
        pro_review_after_draft_node,
        validate_node,
    )

    state = {
        "content_md": "plain intake without a Grok fan-in manifest",
        "input_path": "missing.md",
        "workflow_id": "wf-no-grok",
        "repo_root": str(REPO_ROOT),
        "runtime_root": str(REPO_ROOT),
    }

    async def exercise_nodes() -> list[dict[str, object]]:
        return [
            await validate_node(state),
            await gateway_trace_node(state),
            await grok_worker_fanin_node(state),
            await pro_review_after_draft_node(state),
        ]

    payloads = asyncio.run(exercise_nodes())
    assert payloads[0]["validate_ok"] is False
    assert payloads[1]["gateway_trace_ok"] is False
    assert payloads[2]["worker_lane_ok"] is False
    assert payloads[3]["pro_review_ok"] is False
    assert all(payload["non_grok_model_invocations"] == 0 for payload in payloads)
    assert all(payload.get("fallback_model_invocation_performed") is False for payload in payloads)


def test_post_draft_review_is_optional_or_requires_bound_evidence(tmp_path: Path) -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import pro_review_after_draft_node

    runtime = tmp_path / "runtime"
    input_path = runtime / "input.md"
    input_path.parent.mkdir(parents=True)
    input_path.write_text("review input", encoding="utf-8")
    manifest_path = runtime / "fanin.json"

    base_state: dict[str, object] = {
        "runtime_root": str(runtime),
        "repo_root": str(REPO_ROOT),
        "workflow_id": "wf",
        "input_path": str(input_path),
        "content_md": "draft output",
        "grok_fanin_manifest_ref": str(manifest_path),
    }

    def review_for(mode: str, **extra: object) -> dict[str, object]:
        manifest_path.write_text(
            json.dumps(_attested_grok_manifest(input_path, [("lane", mode)], workflow_id="wf")),
            encoding="utf-8",
        )
        return asyncio.run(pro_review_after_draft_node({**base_state, **extra}))

    optional = review_for("audit")
    assert optional["pro_review_ok"] is False
    assert optional["pro_review_contract_satisfied"] is True
    assert optional["fanin_audit_presence"] is True
    assert optional["model_invocation_performed"] is False

    missing = review_for("audit", review_required=True)
    assert missing["pro_review_contract_satisfied"] is False
    assert missing["pro_review_named_blocker"] == "POST_DRAFT_REVIEW_EVIDENCE_REQUIRED"

    evidence = runtime / "post-review.json"
    evidence.write_text('{"verdict":"APPROVED"}', encoding="utf-8")
    accepted = review_for(
        "audit",
        review_required=True,
        post_draft_review={
            "provider_id": "grok_acpx_headless",
            "model": COMPOSER_MODEL,
            "target_draft_sha256": hashlib.sha256(b"draft output").hexdigest(),
            "verdict": "APPROVED",
            "stop_reason": "EndTurn",
            "total_tokens": 100,
            "evidence_ref": str(evidence),
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        },
    )
    assert accepted["pro_review_ok"] is True
    assert accepted["pro_review_contract_satisfied"] is True
    assert accepted["pro_review_reused_fanin_audit"] is False
    assert accepted["pro_review_model_invocation_performed"] is True
    assert accepted["model_invocation_performed"] is True


def test_params_keep_provider_choice_dynamic_and_grok_exact_after_selection() -> None:
    params = json.loads(
        (
            REPO_ROOT / "materials" / "authority_glue" / "seams" / "integrated_bus_params.v1.json"
        ).read_text(encoding="utf-8")
    )
    assert params["model_worker_policy"] == "positive_benefit_dynamic"
    assert params["stable_preferred_provider_id"] == "grok_acpx_headless"
    assert params["provider_preference_scope"] == "all_positive_benefit_separable_work"
    assert params["worker_output_authority"] == "non_authoritative_candidate"
    assert params["quota_policy"] == "telemetry_only_not_an_activation_gate"
    assert params["codex_inner_optimization_policy"] == {
        "scope": "codex_responsibility_cone_after_outer_provider_decision",
        "mechanisms": [
            "deterministic_no_model_precheck",
            "native_model_and_reasoning",
            "bounded_subagents",
        ],
        "selection_rule": (
            "lowest_usage_that_preserves_reasoning_evidence_and_parent_completion_bar"
        ),
        "native_execution_binding": {
            "surface": "codex_agents",
            "config_scope": "codex_home",
            "agent_refs": [
                "inner_luna_probe",
                "inner_terra_explorer",
                "inner_sol_verifier",
            ],
            "selection": "supervisor_dynamic_not_fixed_ladder",
        },
        "may_override_outer_provider_preference": False,
        "may_create_router_scheduler_or_state_truth": False,
    }
    assert params["quota_capacity_bindings"]["grok_acpx_headless"] == {"source_key": "grok"}
    assert set(params["allowed_model_worker_providers"]) == {
        "grok_acpx_headless",
        "codex_subagent",
    }
    assert params["inactive_model_worker_providers"] == []
    assert params["selected_durable_adapter_provider"] == "grok_acpx_headless"
    assert params["gateway_model_invocation_enabled"] is False
    assert params["mem0_bind_enabled"] is False
    assert params["instructor_enabled"] is False


def test_parallel_width_plan_never_sets_langgraph_send_from_width(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_bus_nodes import run_parallel_width_bus

    runtime = tmp_path / "runtime"
    parallel = run_parallel_width_bus(
        params={"parallel_width_default": 2},
        runtime_root=runtime,
        workflow_id="wf-plan-only",
        repo_root=REPO_ROOT,
        content_md="plan-only intake",
        plan_only=True,
    )
    assert parallel["parallel_width_n"] == 2
    assert parallel["langgraph_send_wired"] is False
    assert parallel["adapter"] == "langgraph_send_plan"
    assert parallel["parallel_lane_models"] == []


def test_parallel_fanin_sets_langgraph_send_only_from_lane_results(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_bus_nodes import run_parallel_fanin_bus

    runtime = tmp_path / "runtime"
    lane = {
        "lane_id": 0,
        "task_id": "wf-lane-0",
        "search_ok": True,
        "lane_ok": True,
        "model": "local_rg_search",
        "lane_role": "parallel_search_slice",
        "tier_used": "tier_local_search",
    }
    single = run_parallel_fanin_bus(
        lane_results=[lane],
        params={"parallel_width_default": 2},
        runtime_root=runtime,
        workflow_id="wf-fanin-single",
    )
    assert single["langgraph_send_wired"] is False

    multi = run_parallel_fanin_bus(
        lane_results=[{**lane, "lane_id": 0}, {**lane, "lane_id": 1, "task_id": "wf-lane-1"}],
        params={"parallel_width_default": 2},
        runtime_root=runtime,
        workflow_id="wf-fanin-multi",
    )
    assert multi["langgraph_send_wired"] is True
    assert len(multi["parallel_lane_models"]) == 2


def test_promoted_grok_fanin_uses_parent_dynamic_width(tmp_path: Path) -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_SENTINEL,
        parallel_width_node,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    intake = fanin / "input.md"
    manifest = fanin / "manifest.json"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
    )
    intake.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(
            _attested_grok_manifest(
                intake,
                [("research", "research"), ("audit", "audit"), ("draft", "draft")],
            )
        ),
        encoding="utf-8",
    )
    payload = asyncio.run(
        parallel_width_node(
            {
                "content_md": content,
                "input_path": str(intake),
                "workflow_id": "parent-wf-langgraph-s0",
                "repo_root": str(REPO_ROOT),
                "runtime_root": str(runtime),
            }
        )
    )
    assert payload["grok_fanin_parallel_bypass"] is True
    assert payload["langgraph_send_wired"] is False
    assert payload["parallel_width_n"] == 3
    assert payload["parallel_succeeded"] == 3


def test_promoted_grok_fanin_is_the_only_model_worker(tmp_path: Path) -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_PROVIDER,
        GROK_FANIN_SENTINEL,
        grok_worker_fanin_node,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    manifest = fanin / "manifest.json"
    intake = fanin / "input.md"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
        "Grok worker result\n"
    )
    intake.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(_attested_grok_manifest(intake, [("only", "audit")])),
        encoding="utf-8",
    )
    lane = asyncio.run(
        grok_worker_fanin_node(
            {
                "runtime_root": str(runtime),
                "repo_root": str(REPO_ROOT),
                "workflow_id": "parent-wf-langgraph-s0",
                "input_path": str(intake),
                "content_md": content,
            }
        )
    )
    assert lane["worker_lane_provider"] == GROK_FANIN_PROVIDER
    assert lane["worker_lane_adapter"] == "grok_build_cli_docker_native"
    assert lane["non_grok_model_invocations"] == 0


def test_promoted_grok_fanin_marker_fails_closed_on_hash_drift(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_PROVIDER,
        GROK_FANIN_SENTINEL,
        _grok_fanin_worker_lane,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    manifest = fanin / "manifest.json"
    intake = fanin / "input.md"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
    )
    intake.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "ok": True,
                "sentinel": GROK_FANIN_SENTINEL,
                "provider_id": GROK_FANIN_PROVIDER,
                "workflow_id": "parent-wf",
                "succeeded": 1,
                "intake_sha256": "stale",
            }
        ),
        encoding="utf-8",
    )
    lane = _grok_fanin_worker_lane(
        {
            "runtime_root": str(runtime),
            "repo_root": str(REPO_ROOT),
            "workflow_id": "parent-wf-langgraph-s0",
            "input_path": str(intake),
            "content_md": content,
        }
    )
    assert lane is not None
    assert lane["worker_lane_ok"] is False
    assert lane["worker_lane_named_blocker"] == "GROK_FANIN_INPUT_HASH_MISMATCH"


def test_diff_cover_uses_retained_hot_path_test() -> None:
    from services.agent_runtime.integrated_bus_bus_nodes import run_diff_cover_slice

    default = inspect.signature(run_diff_cover_slice).parameters["pytest_node"].default
    assert default == (
        "tests/test_integrated_bus_hot_path.py::"
        "test_integrated_bus_default_route_is_readonly_at_finalize"
    )


def test_fanin_evidence_paths_are_unique_lineage_bound_and_atomic(
    tmp_path: Path, monkeypatch
) -> None:
    from services.agent_runtime import integrated_bus_bus_nodes as nodes

    runtime = tmp_path / "runtime"
    monkeypatch.setattr(
        nodes,
        "_temporal_evidence_lineage",
        lambda workflow_id: (workflow_id, "019f-run/id"),
    )
    monkeypatch.setattr(
        nodes,
        "run_diff_cover_slice",
        lambda **_kwargs: {"diff_cover_ok": True, "diff_cover_skipped": False},
    )
    monkeypatch.setattr(nodes, "run_otel_trace_slice", lambda **_kwargs: {"otel_ok": True})

    first = nodes.run_fanin_bus(
        {}, runtime_root=runtime, workflow_id="wf/fanin", repo_root=REPO_ROOT
    )
    second = nodes.run_fanin_bus(
        {}, runtime_root=runtime, workflow_id="wf/fanin", repo_root=REPO_ROOT
    )
    assert first["fanin_ok"] is False
    assert second["provider_fanin_ok"] is False

    provider_manifest = runtime / "state" / "grok" / "manifest.json"
    provider_manifest.parent.mkdir(parents=True)
    provider_manifest.write_text('{"ok":true}', encoding="utf-8")
    accepted = nodes.run_fanin_bus(
        {
            "worker_lane_provider": "grok_acpx_headless",
            "worker_lane_ok": True,
            "validate_ok": True,
            "grok_fanin_ok": True,
            "grok_fanin_manifest_ref": str(provider_manifest),
            "worker_lane_cross_seam_receipt_ok": True,
            "worker_lane_cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
            "worker_lane_cross_seam_receipt_version": ATTEMPT_RECEIPT_VERSION,
            "worker_lane_cross_seam_receipt_set_sha256": "9" * 64,
        },
        runtime_root=runtime,
        workflow_id="wf/fanin-accepted",
        repo_root=REPO_ROOT,
    )
    assert accepted["fanin_ok"] is True
    accepted_record = json.loads(Path(accepted["fanin_evidence_ref"]).read_text(encoding="utf-8"))
    assert accepted_record["validate_ok"] is True
    assert accepted_record["grok_fanin_ok"] is True
    assert accepted_record["substantive_lane_ok"] is True

    first_path = Path(first["fanin_evidence_ref"])
    second_path = Path(second["fanin_evidence_ref"])
    assert first_path != second_path
    assert "wf_fanin" in first_path.name
    assert "019f-run_id" in first_path.name
    assert len(first_path.stem.rsplit("_", 1)[-1]) == 32
    assert json.loads(first_path.read_text(encoding="utf-8"))["temporal_run_id"] == ("019f-run/id")
    assert json.loads(second_path.read_text(encoding="utf-8"))["workflow_id"] == "wf/fanin"
    assert not list(runtime.rglob("*.tmp"))

    lane = {"lane_id": 0, "task_id": "lane-0", "search_ok": True, "lane_ok": True}
    parallel_first = nodes.run_parallel_fanin_bus(
        lane_results=[lane],
        params={"parallel_width_default": 1},
        runtime_root=runtime,
        workflow_id="wf/parallel",
    )
    parallel_second = nodes.run_parallel_fanin_bus(
        lane_results=[lane],
        params={"parallel_width_default": 1},
        runtime_root=runtime,
        workflow_id="wf/parallel",
    )
    assert parallel_first["parallel_evidence_ref"] != parallel_second["parallel_evidence_ref"]
    assert "wf_parallel" in Path(parallel_first["parallel_evidence_ref"]).name
    assert not list(runtime.rglob("*.tmp"))


def test_parallel_fanin_concurrent_writes_do_not_collide(tmp_path: Path, monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from services.agent_runtime import integrated_bus_bus_nodes as nodes

    runtime = tmp_path / "runtime"
    monkeypatch.setattr(
        nodes,
        "_temporal_evidence_lineage",
        lambda workflow_id: (workflow_id, "run-concurrent"),
    )
    lane = {"lane_id": 0, "task_id": "lane-0", "search_ok": True, "lane_ok": True}

    def write_one(index: int) -> str:
        result = nodes.run_parallel_fanin_bus(
            lane_results=[{**lane, "task_id": f"lane-{index}"}],
            params={"parallel_width_default": 1},
            runtime_root=runtime,
            workflow_id="wf-concurrent",
        )
        return str(result["parallel_evidence_ref"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(write_one, range(16)))

    assert len(paths) == len(set(paths)) == 16
    assert all(json.loads(Path(path).read_text(encoding="utf-8")) for path in paths)
    latest = runtime / "state" / "integrated_bus_parallel" / "latest.json"
    assert json.loads(latest.read_text(encoding="utf-8"))["evidence_id"] in {
        json.loads(Path(path).read_text(encoding="utf-8"))["evidence_id"] for path in paths
    }
    assert not list(runtime.rglob("*.tmp"))
