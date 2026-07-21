from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from services.agent_runtime.dispatch_economics import (
    DispatchEconomicsError,
    build_worker_package_identity,
    neutral_output_contract_sha256,
    plan_package_frontier,
    validate_prior_accepted_ancestor_action,
)
from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    ExecutionContractError,
    build_common_receipt_binding,
    canonical_json_bytes,
    logical_contract_sha256,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    GROK_DOCKER_CONSUMER_ID,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _sha(path)


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha(path)}


def _context_manifest(path: Path, *, input_sha256: str) -> str:
    content = "bounded\n"
    content_bytes = content.encode("utf-8")
    source_identity = [{"path": "input.txt", "sha256": input_sha256, "bytes": len(content_bytes)}]
    slice_row = {
        "selector": {"kind": "line_range", "start": 1, "end": 1},
        "line_start": 1,
        "line_end": 1,
        "content_sha256": input_sha256,
        "content_bytes": len(content_bytes),
        "content": content,
    }
    identity_slice = dict(slice_row)
    identity_slice.pop("content")
    context_identity = {
        "schema_version": "xinao.context_slice_identity.v1",
        "sources": [
            {
                "path": "input.txt",
                "source_sha256": input_sha256,
                "source_bytes": len(content_bytes),
                "slices": [identity_slice],
            }
        ],
    }
    return _write_json(
        path,
        {
            "schema_version": "xinao.context_slice_manifest.v1",
            "authority": False,
            "completion_claim_allowed": False,
            "spec_sha256": "a" * 64,
            "source_manifest_sha256": hashlib.sha256(
                canonical_json_bytes(source_identity)
            ).hexdigest(),
            "context_sha256": hashlib.sha256(canonical_json_bytes(context_identity)).hexdigest(),
            "total_content_bytes": len(content_bytes),
            "sources": [
                {
                    "path": "input.txt",
                    "source_sha256": input_sha256,
                    "source_bytes": len(content_bytes),
                    "slices": [slice_row],
                }
            ],
            "false_green_deny": "fixture context is input only",
        },
    )


def _accepted_receipt(
    *,
    contract: dict[str, object],
    provider_evidence_ref: dict[str, str],
) -> dict[str, object]:
    selection = contract["selection"]
    assert isinstance(selection, dict)
    output_sha256 = "e" * 64
    return {
        "schema_version": ATTEMPT_RECEIPT_VERSION,
        "contract_sha256": logical_contract_sha256(contract),
        "consumer_id": GROK_DOCKER_CONSUMER_ID,
        "logical_operation_id": contract["logical_operation_id"],
        "work_key": contract["work_key"],
        "attempt": 1,
        "observed": {
            **selection,
            "rules_sha256": contract["rules_sha256"],
            "runtime_version": "0.2.101",
            "execution_location": "docker:houtai-gongren",
            "executor_id": "container-1",
        },
        "terminal_state": "completed",
        "stop_reason": "EndTurn",
        "output": {
            "format": "text",
            "content_sha256": output_sha256,
            "chars": 120,
            "schema_sha256": contract["output_contract_sha256"],
            "schema_valid": True,
            "markers_ok": True,
            "substantive": True,
        },
        "invocations": [
            {
                "invocation": 1,
                "state": "accepted",
                "observed_model": selection["model_id"],
                "stop_reason": "EndTurn",
                "output_sha256": output_sha256,
                "output_chars": 120,
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
            "workflow_id": "workflow-1",
            "lane_id": "p1",
            "parent_operation_id": "",
            "correlation_id": "",
            "session_id": "session-1",
        },
        "provider_contract_version": "xinao.grok.shared_execution_contract.v1",
        "provider_evidence_ref": provider_evidence_ref["path"],
        "provider_evidence_sha256": provider_evidence_ref["sha256"],
        "provider_evidence_valid": True,
        "replayed": False,
    }


def _fixture(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "source"
    source.mkdir(parents=True)
    candidate_base = tmp_path / "candidate"
    candidate_root = candidate_base / "p1"
    candidate_root.mkdir(parents=True)

    prompt = source / "prompt.md"
    prompt.write_text("produce one candidate\n", encoding="utf-8")
    input_path = source / "input.txt"
    input_path.write_bytes(b"bounded\n")
    context_path = source / "context.json"
    context_ref_sha256 = _context_manifest(context_path, input_sha256=_sha(input_path))
    rules_path = source / "rules.txt"
    rules_path.write_text("bounded worker rules\n", encoding="utf-8")
    acceptance = {
        "min_result_chars": 1,
        "required_result_markers": ["OK"],
        "require_json_object": False,
    }
    identity = build_worker_package_identity(
        package_id="p1",
        work_key="wk-1",
        parent_work_key="parent-1",
        work_class="local_audit",
        role="candidate-author",
        phase="CONSTRUCT",
        input_sha256=_sha(input_path),
        context_sha256=context_ref_sha256,
        rules_sha256=_sha(rules_path),
        output_contract_sha256=neutral_output_contract_sha256(acceptance),
        write_domains=[],
        candidate_only=True,
    )
    package = {
        **identity,
        "prompt_ref": _ref(prompt),
        "context_manifest_ref": _ref(context_path),
        "rules_ref": _ref(rules_path),
        "input_refs": [_ref(input_path)],
        "allowed_output_root": str(candidate_root.resolve()),
        "cwd": str(source.resolve()),
        "depends_on": [],
        "acceptance": acceptance,
        "timeout_sec": 60,
    }
    limits = {
        "max_parallel": 1,
        "fan_in_capacity": 1,
        "candidate_ingestion_capacity": 1,
    }
    ancestor = {
        "schema_version": "xinao.worker_package_batch.v3",
        "authority": False,
        "completion_claim_allowed": False,
        "parent_work_key": "parent-1",
        "candidate_output_base": str(candidate_base.resolve()),
        "graph_revision": 1,
        "predecessor_manifest_ref": None,
        "reseal_of": None,
        "affected_cone": [],
        "limits": limits,
        "packages": [copy.deepcopy(package)],
    }
    ancestor_path = tmp_path / "manifest-r1.json"
    ancestor_sha256 = _write_json(ancestor_path, ancestor)

    provider_path = tmp_path / "prior" / "provider-evidence.json"
    provider_ref = {
        "path": str(provider_path.resolve()),
        "sha256": _write_json(provider_path, {"provider": "grok", "accepted": True}),
    }
    selection = {
        "provider_id": "grok_acpx_headless",
        "profile_ref": "grok.com.cached_profile",
        "model_id": "grok-4.5",
        "transport_id": "grok-cli-container",
        "capability_binding_sha256": "d" * 64,
    }
    operation_id = "op-package-p1"
    contract = {
        "schema_version": LOGICAL_CONTRACT_VERSION,
        "logical_operation_id": operation_id,
        "work_key": package["work_key"],
        "task_contract_ref": (f"{ancestor_path.resolve()}#sha256={ancestor_sha256}"),
        "parent_operation_id": "",
        "correlation_id": "",
        "input_sha256": package["prompt_ref"]["sha256"],
        "context_sha256": package["context_sha256"],
        "rules_sha256": package["rules_sha256"],
        "output_contract_sha256": package["output_contract_sha256"],
        "selection": selection,
        "effect_mode": "authorized_write",
        "idempotency_key": operation_id,
        "deadline": {
            "owner": "temporal",
            "mode": "relative_from_activity_start",
            "seconds": 1800,
        },
        "cancellation_generation": 0,
    }
    contract_path = tmp_path / "prior" / "logical_contract.json"
    contract_ref = {
        "path": str(contract_path.resolve()),
        "sha256": _write_json(contract_path, contract),
    }
    attempt_path = tmp_path / "prior" / "attempt_receipt.json"
    attempt = _accepted_receipt(contract=contract, provider_evidence_ref=provider_ref)
    attempt_ref = {
        "path": str(attempt_path.resolve()),
        "sha256": _write_json(attempt_path, attempt),
    }

    current_package = copy.deepcopy(package)
    current_package["prior_attempt_receipt_ref"] = attempt_ref
    current_package["prior_logical_contract_ref"] = contract_ref
    current = {
        **copy.deepcopy(ancestor),
        "graph_revision": 2,
        "predecessor_manifest_ref": {
            "path": str(ancestor_path.resolve()),
            "sha256": ancestor_sha256,
        },
        "reseal_of": {
            "package_id": "p1",
            "package_identity_sha256": package["package_identity_sha256"],
            "graph_revision": 1,
        },
        "affected_cone": ["p1"],
        "packages": [current_package],
    }
    current_path = tmp_path / "manifest-r2.json"
    current_ref = {
        "path": str(current_path.resolve()),
        "sha256": _write_json(current_path, current),
    }
    action_binding = {
        "logical_operation_id": operation_id,
        "package_input_sha256": package["input_sha256"],
        "input_sha256": package["prompt_ref"]["sha256"],
        "frozen_context_sha256": package["context_sha256"],
        "context_sha256": contract["context_sha256"],
        "rules_sha256": package["rules_sha256"],
        "package_output_contract_sha256": package["output_contract_sha256"],
        "output_contract_sha256": contract["output_contract_sha256"],
        "selection": selection,
    }
    return {
        "root": tmp_path,
        "ancestor_path": ancestor_path,
        "current_path": current_path,
        "current": current,
        "current_ref": current_ref,
        "contract_path": contract_path,
        "contract_ref": contract_ref,
        "attempt_path": attempt_path,
        "provider_path": provider_path,
        "action_binding": action_binding,
    }


def _validate(fixture: dict[str, object], **overrides: object) -> dict[str, object]:
    args = {
        "current_manifest_ref": fixture["current_ref"],
        "package_id": "p1",
        "prior_logical_contract_ref": fixture["contract_ref"],
        "expected_consumer_id": GROK_DOCKER_CONSUMER_ID,
        "expected_action_binding": fixture["action_binding"],
    }
    args.update(overrides)
    return validate_prior_accepted_ancestor_action(**args)


def _rewrite_current(fixture: dict[str, object]) -> None:
    current_path = fixture["current_path"]
    assert isinstance(current_path, Path)
    current = fixture["current"]
    assert isinstance(current, dict)
    fixture["current_ref"] = {
        "path": str(current_path.resolve()),
        "sha256": _write_json(current_path, current),
    }


def test_valid_reseal_returns_zero_model_prior_action_binding_without_writes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    before = {
        str(path.relative_to(tmp_path)): _sha(path)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    result = _validate(fixture)

    after = {
        str(path.relative_to(tmp_path)): _sha(path)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert result["schema_version"] == "xinao.prior_accepted_ancestor_action.v1"
    assert result["binding_source"] == "prior_accepted_ancestor_manifest"
    assert result["reuse_disposition"] == "ACCEPTED_IDENTICAL_REUSE"
    assert result["skip_provider_execution"] is True
    assert result["model_invocation_allowed"] is False
    assert result["authority"] is False
    assert result["completion_claim_allowed"] is False
    assert result["subject_manifest_ref"]["sha256"] == _sha(fixture["ancestor_path"])
    assert result["prior_attempt_receipt_ref"]["sha256"] == _sha(fixture["attempt_path"])
    assert result["prior_logical_contract_ref"] == fixture["contract_ref"]
    assert result["provider_evidence_ref"]["sha256"] == _sha(fixture["provider_path"])
    assert result["prior_action_binding"] == fixture["action_binding"]
    assert len(result["prior_action_binding_sha256"]) == 64


def test_frontier_execution_seal_binds_both_prior_receipt_refs(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    frontier = plan_package_frontier(fixture["current"])
    admitted = frontier["admitted"]

    assert len(admitted) == 1
    package = admitted[0]
    expected_seal = hashlib.sha256(
        canonical_json_bytes(
            {
                "schema_version": "xinao.worker_package_execution_seal.v1",
                "graph_revision": 2,
                "package_identity_sha256": package["package_identity_sha256"],
                "depends_on": [],
                "prior_attempt_receipt_ref": fixture["current"]["packages"][0][
                    "prior_attempt_receipt_ref"
                ],
                "prior_logical_contract_ref": fixture["current"]["packages"][0][
                    "prior_logical_contract_ref"
                ],
            }
        )
    ).hexdigest()
    assert package["package_seal_sha256"] == expected_seal


def test_common_receipt_binding_separates_current_carrier_from_prior_subject(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    ancestor = _validate(fixture)
    contract = json.loads(Path(fixture["contract_path"]).read_text(encoding="utf-8"))
    attempt = json.loads(Path(fixture["attempt_path"]).read_text(encoding="utf-8"))

    binding = build_common_receipt_binding(
        contract,
        lane_id="p1",
        attempt_receipt_sha256=_sha(fixture["attempt_path"]),
        attempt_receipt=attempt,
        work_key="wk-1",
        package_manifest_sha256=fixture["current_ref"]["sha256"],
        prior_accepted_ancestor_binding=ancestor,
    )

    assert binding["package_manifest_sha256"] == fixture["current_ref"]["sha256"]
    assert binding["subject_manifest_sha256"] == _sha(fixture["ancestor_path"])
    assert binding["reuse_disposition"] == "ACCEPTED_IDENTICAL_REUSE"

    drifted = copy.deepcopy(ancestor)
    drifted["current_manifest_ref"]["sha256"] = "f" * 64
    with pytest.raises(ExecutionContractError, match="current carrier or subject"):
        build_common_receipt_binding(
            contract,
            lane_id="p1",
            attempt_receipt_sha256=_sha(fixture["attempt_path"]),
            attempt_receipt=attempt,
            work_key="wk-1",
            package_manifest_sha256=fixture["current_ref"]["sha256"],
            prior_accepted_ancestor_binding=drifted,
        )


def test_leg_b_consumer_reuses_validated_ancestor_without_current_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.agent_runtime import grok_build_docker_worker as docker_worker

    fixture = _fixture(tmp_path)
    current = fixture["current"]
    package = current["packages"][0]
    contract = json.loads(Path(fixture["contract_path"]).read_text(encoding="utf-8"))
    cached = {
        "ok": True,
        "operation_id": contract["logical_operation_id"],
        "work_key": package["work_key"],
        "package_id": package["package_id"],
        "package_manifest_sha256": _sha(fixture["ancestor_path"]),
        "cross_seam_logical_contract": contract,
        "cross_seam_logical_contract_ref": str(fixture["contract_path"]),
        "cross_seam_logical_contract_artifact_sha256": _sha(fixture["contract_path"]),
        "cross_seam_attempt_receipt_ref": str(fixture["attempt_path"]),
        "cross_seam_attempt_receipt_sha256": _sha(fixture["attempt_path"]),
        "invocation_accounting": {
            "invocation_count": 1,
            "total_tokens": 100,
            "accepted_tokens": 100,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
    }
    monkeypatch.setattr(docker_worker, "_cached_lane", lambda *_args, **_kwargs: cached)
    monkeypatch.setattr(docker_worker, "_map_host_path_to_container", lambda value: str(value))
    lane = {
        "package_id": package["package_id"],
        "work_key": package["work_key"],
        "input_sha256": package["input_sha256"],
        "prompt_ref": package["prompt_ref"],
        "context_sha256": package["context_sha256"],
        "rules_sha256": package["rules_sha256"],
        "output_contract_sha256": package["output_contract_sha256"],
        "prior_attempt_receipt_ref": package["prior_attempt_receipt_ref"],
        "prior_logical_contract_ref": package["prior_logical_contract_ref"],
        "package_manifest_ref": fixture["current_ref"]["path"],
        "package_manifest_sha256": fixture["current_ref"]["sha256"],
        "dispatch_envelope_ref": str(tmp_path / "current-envelope.json"),
        "dispatch_envelope_sha256": "9" * 64,
        "dispatch_route_claim_ref": str(tmp_path / "route-claim.json"),
        "dispatch_task_run_dir": str(tmp_path / "run-current"),
        "dispatch_task_run_id": "run-current",
        "package_seal_sha256": "8" * 64,
    }

    reused = docker_worker._prior_accepted_ancestor_lane(
        lane=lane,
        requested_model="grok-4.5",
        prompt_sha256=package["prompt_ref"]["sha256"],
        execution_prompt_sha256="7" * 64,
        current_operation_id="op-current-carrier",
        current_manifest_ref=fixture["current_ref"],
        expected_provider_selection=fixture["action_binding"]["selection"],
        model_capabilities={"binding_sha256": "6" * 64},
    )

    assert reused is not None
    assert reused["operation_id"] == contract["logical_operation_id"]
    assert reused["terminal_record_id"] == "op-current-carrier"
    assert reused["package_manifest_sha256"] == fixture["current_ref"]["sha256"]
    assert reused["dispatch_task_run_dir"] == str(tmp_path / "run-current")
    assert reused["dispatch_task_run_id"] == "run-current"
    assert reused["replayed"] is True
    assert reused["reuse_disposition"] == "ACCEPTED_IDENTICAL_REUSE"
    assert reused["prior_accepted_ancestor_binding"]["skip_provider_execution"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("package_input_sha256", "1" * 64),
        ("input_sha256", "2" * 64),
        ("frozen_context_sha256", "3" * 64),
        ("context_sha256", "4" * 64),
        ("rules_sha256", "5" * 64),
        ("package_output_contract_sha256", "6" * 64),
        ("output_contract_sha256", "7" * 64),
    ],
)
def test_current_package_or_action_hash_drift_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    fixture = _fixture(tmp_path)
    action = copy.deepcopy(fixture["action_binding"])
    action[field] = value

    with pytest.raises(DispatchEconomicsError, match="current action binding|prior logical"):
        _validate(fixture, expected_action_binding=action)


def test_current_selection_drift_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    action = copy.deepcopy(fixture["action_binding"])
    action["selection"]["model_id"] = "grok-composer-2.5-fast"

    with pytest.raises(DispatchEconomicsError, match="selection drifted"):
        _validate(fixture, expected_action_binding=action)


def test_expected_consumer_drift_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(DispatchEconomicsError, match="CONSUMER_MISMATCH"):
        _validate(fixture, expected_consumer_id="wrong-consumer")


def test_prior_receipt_content_drift_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    attempt_path = fixture["attempt_path"]
    assert isinstance(attempt_path, Path)
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    attempt["contract_sha256"] = "0" * 64
    attempt_sha256 = _write_json(attempt_path, attempt)
    current = fixture["current"]
    assert isinstance(current, dict)
    current["packages"][0]["prior_attempt_receipt_ref"]["sha256"] = attempt_sha256
    current["packages"][0]["prior_logical_contract_ref"] = fixture["contract_ref"]
    _rewrite_current(fixture)

    with pytest.raises(DispatchEconomicsError, match="CONTRACT_DIGEST_MISMATCH"):
        _validate(fixture)


def test_ancestor_bytes_drift_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    ancestor_path = fixture["ancestor_path"]
    assert isinstance(ancestor_path, Path)
    ancestor = json.loads(ancestor_path.read_text(encoding="utf-8"))
    ancestor["packages"][0]["role"] = "drifted-role"
    _write_json(ancestor_path, ancestor)

    with pytest.raises(DispatchEconomicsError, match="predecessor_manifest_ref.*sha256 mismatch"):
        _validate(fixture)


def test_hash_valid_non_ancestor_task_contract_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    ancestor_path = fixture["ancestor_path"]
    contract_path = fixture["contract_path"]
    attempt_path = fixture["attempt_path"]
    assert isinstance(ancestor_path, Path)
    assert isinstance(contract_path, Path)
    assert isinstance(attempt_path, Path)
    unrelated_path = tmp_path / "unrelated-manifest.json"
    unrelated_path.write_bytes(ancestor_path.read_bytes())

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["task_contract_ref"] = f"{unrelated_path.resolve()}#sha256={_sha(unrelated_path)}"
    fixture["contract_ref"] = {
        "path": str(contract_path.resolve()),
        "sha256": _write_json(contract_path, contract),
    }
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    attempt["contract_sha256"] = logical_contract_sha256(contract)
    attempt_sha256 = _write_json(attempt_path, attempt)
    current = fixture["current"]
    assert isinstance(current, dict)
    current["packages"][0]["prior_attempt_receipt_ref"]["sha256"] = attempt_sha256
    current["packages"][0]["prior_logical_contract_ref"] = fixture["contract_ref"]
    _rewrite_current(fixture)

    with pytest.raises(DispatchEconomicsError, match="not in the reseal ancestor chain"):
        _validate(fixture)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("work_key", "wk-drift"),
        ("parent_work_key", "parent-drift"),
        ("package_identity_sha256", "9" * 64),
    ],
)
def test_current_package_identity_drift_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    fixture = _fixture(tmp_path)
    current = fixture["current"]
    assert isinstance(current, dict)
    current["packages"][0][field] = value
    _rewrite_current(fixture)

    with pytest.raises(DispatchEconomicsError, match="identity|parent_work_key"):
        _validate(fixture)


def test_logical_contract_bytes_drift_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    contract_path = fixture["contract_path"]
    assert isinstance(contract_path, Path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["selection"]["model_id"] = "grok-composer-2.5-fast"
    _write_json(contract_path, contract)

    with pytest.raises(DispatchEconomicsError, match="prior_logical_contract_ref sha256 mismatch"):
        _validate(fixture)


def test_provider_evidence_bytes_drift_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    provider_path = fixture["provider_path"]
    assert isinstance(provider_path, Path)
    _write_json(provider_path, {"provider": "grok", "accepted": False})

    with pytest.raises(DispatchEconomicsError, match="provider evidence sha256 mismatch"):
        _validate(fixture)
