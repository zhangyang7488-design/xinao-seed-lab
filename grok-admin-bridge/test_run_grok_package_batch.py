from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from types import ModuleType

import pytest


SCRIPT = Path(__file__).with_name("run_grok_package_batch.py")
SPEC = importlib.util.spec_from_file_location("run_grok_package_batch", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _install_fake_selector_contract(
    monkeypatch: pytest.MonkeyPatch,
    *,
    envelope: dict[str, object],
    frontier: dict[str, object],
    claim=None,
) -> ModuleType:
    fixture_root = Path(str(envelope["package_manifest_ref"]["path"])).parent
    for package in envelope["validated_package_manifest"]["packages"]:
        package_id = str(package["package_id"])
        source = fixture_root / f"source-{package_id}"
        candidate = fixture_root / f"candidate-{package_id}"
        source.mkdir(exist_ok=True)
        candidate.mkdir(exist_ok=True)
        package.setdefault("cwd", str(source))
        package.setdefault("allowed_output_root", str(candidate))
        package.setdefault("logical_consumer_id", "worker_candidate_producer")
        package.setdefault(
            "logical_effect_contract",
            {
                "schema_version": "xinao.worker_candidate_effect_contract.v1",
                "effect_kind": "candidate_artifact_write",
                "output_boundary": "allowed_output_root",
                "authority": False,
                "completion_claim_allowed": False,
            },
        )
    services = ModuleType("services")
    services.__path__ = []  # type: ignore[attr-defined]
    runtime = ModuleType("services.agent_runtime")
    runtime.__path__ = []  # type: ignore[attr-defined]
    economics = ModuleType("services.agent_runtime.dispatch_economics")
    execution = ModuleType("services.agent_runtime.execution_contract")
    economics.PACKAGE_IDENTITY_SCHEMA = "xinao.worker_package_identity.v2"  # type: ignore[attr-defined]
    economics.PACKAGE_BATCH_SCHEMA = "xinao.worker_package_batch.v3"  # type: ignore[attr-defined]
    economics.DISPATCH_ENVELOPE_SCHEMA = "xinao.worker_dispatch_envelope.v2"  # type: ignore[attr-defined]
    economics.LOGICAL_CANDIDATE_CONSUMER_ID = "worker_candidate_producer"  # type: ignore[attr-defined]
    economics.LOGICAL_CANDIDATE_EFFECT_CONTRACT = {  # type: ignore[attr-defined]
        "schema_version": "xinao.worker_candidate_effect_contract.v1",
        "effect_kind": "candidate_artifact_write",
        "output_boundary": "allowed_output_root",
        "authority": False,
        "completion_claim_allowed": False,
    }
    economics.validate_dispatch_envelope = lambda _raw: envelope  # type: ignore[attr-defined]
    economics.plan_package_frontier = lambda _manifest: frontier  # type: ignore[attr-defined]
    economics.build_dispatch_outcome_event = lambda **_kwargs: {}  # type: ignore[attr-defined]
    economics.validate_candidate_consumer_binding = (  # type: ignore[attr-defined]
        lambda _raw, **_kwargs: {
            "schema_version": "xinao.worker_candidate_consumer_binding.v1",
            "leg": "A",
            "logical_consumer_id": "worker_candidate_producer",
            "logical_effect_contract": dict(
                economics.LOGICAL_CANDIDATE_EFFECT_CONTRACT  # type: ignore[attr-defined]
            ),
            "physical_consumer_id": envelope["validated_physical_consumer_id"],
            "candidate_output_base": str(fixture_root),
            "route_choice": envelope["validated_route_choice"],
            "boundaries": [
                {
                    "package_id": package["package_id"],
                    "allowed_output_root": package["allowed_output_root"],
                    "physical_output_root": package["allowed_output_root"],
                    "package_seal_sha256": package.get("package_seal_sha256", "f" * 64),
                }
                for package in envelope["validated_package_manifest"]["packages"]
                if package["package_id"] in envelope["package_ids"]
            ],
            "candidate_boundary_valid": True,
            "live_start_gate_required": True,
            "authority": False,
            "completion_claim_allowed": False,
        }
    )
    economics.claim_dispatch_route = claim or (  # type: ignore[attr-defined]
        lambda **_kwargs: {
            "schema_version": "xinao.dispatch_route_claim_result.v1",
            "status": "won",
            "alternative_group_sha256": envelope["validated_route_choice"][
                "alternative_group_sha256"
            ],
            "choice_sha256": envelope["validated_route_choice"]["choice_sha256"],
            "leg": "A",
            "physical_consumer_id": envelope["validated_physical_consumer_id"],
            "route_claim_evidence_ref": "route-claim.json#sha256=" + "9" * 64,
            "route_claim_selected": True,
            "live_start_gate_required": True,
            "authority": False,
            "completion_claim_allowed": False,
        }
    )
    economics.validate_dispatch_route_claim = (  # type: ignore[attr-defined]
        lambda **_kwargs: {
            "schema_version": "xinao.dispatch_route_claim_validation.v1",
            "alternative_group_sha256": envelope["validated_route_choice"][
                "alternative_group_sha256"
            ],
            "choice_sha256": envelope["validated_route_choice"]["choice_sha256"],
            "leg": "A",
            "physical_consumer_id": envelope["validated_physical_consumer_id"],
            "model_invocation_allowed": True,
            "authority": False,
            "completion_claim_allowed": False,
        }
    )
    execution.validate_attempt_receipt = lambda *_args: None  # type: ignore[attr-defined]
    services.agent_runtime = runtime  # type: ignore[attr-defined]
    runtime.dispatch_economics = economics  # type: ignore[attr-defined]
    runtime.execution_contract = execution  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "services", services)
    monkeypatch.setitem(sys.modules, "services.agent_runtime", runtime)
    monkeypatch.setitem(
        sys.modules, "services.agent_runtime.dispatch_economics", economics
    )
    monkeypatch.setitem(
        sys.modules, "services.agent_runtime.execution_contract", execution
    )
    return economics


def _set_main_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    envelope_path: Path,
    selection_path: Path,
    summary_path: Path,
) -> None:
    selector_root = tmp_path / "selector"
    selector_root.mkdir(exist_ok=True)
    selector_python = tmp_path / "selector-python.exe"
    selector_python.write_text("stub", encoding="utf-8")
    dispatch_script = tmp_path / "dispatch.ps1"
    dispatch_script.write_text("# stub", encoding="utf-8")
    checkpoint = tmp_path / "session_checkpoint.json"
    _write_json(checkpoint, {"schema_version": "test.checkpoint.v1"})
    task_run_cli = tmp_path / "task_run.py"
    task_run_cli.write_text("# stub", encoding="utf-8")
    task_run_root = tmp_path / "task-runs"
    task_run_dir = task_run_root / "run-1"
    task_run_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--dispatch-envelope",
            str(envelope_path),
            "--selector-root",
            str(selector_root),
            "--selector-python",
            str(selector_python),
            "--dispatch-script",
            str(dispatch_script),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--model",
            "grok-test",
            "--selection-path",
            str(selection_path),
            "--checkpoint-path",
            str(checkpoint),
            "--task-run-cli",
            str(task_run_cli),
            "--task-run-root",
            str(task_run_root),
            "--task-run-id",
            "run-1",
            "--summary-output",
            str(summary_path),
        ],
    )


def _direct_route_validation_fields(decision_sha256: str) -> dict[str, object]:
    return {
        "validated_selected_candidate": {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": "grok-test",
            "transport_id": "direct-grok-worker-pool",
            "route_identity_sha256": "a" * 64,
            "route_decision_binding_sha256": "b" * 64,
        },
        "validated_execution_adapter": None,
        "validated_physical_consumer_id": "grok_direct_worker_pool_consumer",
        "validated_route_choice": {
            "schema_version": "xinao.worker_route_choice.v1",
            "alternative_group_sha256": "c" * 64,
            "leg": "A",
            "selection_decision_sha256": decision_sha256,
            "route_decision_binding_sha256": "b" * 64,
            "choice_sha256": "e" * 64,
        },
    }


def _route_claim_result(
    envelope: dict[str, object], *, status: str = "won"
) -> dict[str, object]:
    route_choice = envelope["validated_route_choice"]
    assert isinstance(route_choice, dict)
    return {
        "schema_version": "xinao.dispatch_route_claim_result.v1",
        "status": status,
        "alternative_group_sha256": route_choice["alternative_group_sha256"],
        "choice_sha256": route_choice["choice_sha256"],
        "leg": "A",
        "physical_consumer_id": envelope["validated_physical_consumer_id"],
        "route_claim_evidence_ref": "route-claim.json#sha256=" + "9" * 64,
        "route_claim_selected": True,
        "live_start_gate_required": True,
        "authority": False,
        "completion_claim_allowed": False,
    }


def test_extracts_exact_plain_and_structured_final_text(tmp_path: Path) -> None:
    plain = tmp_path / "plain.json"
    _write_json(plain, {"text": "最终行\r\nsecond", "structuredOutput": None})
    assert (
        subject._extract_cli_final_text(plain, {"effective_output_source": "text"})
        == "最终行\r\nsecond"
    )

    structured = tmp_path / "structured.json"
    _write_json(structured, {"structuredOutput": {"z": "值", "a": 1}})
    assert (
        subject._extract_cli_final_text(
            structured, {"effective_output_source": "structuredOutput"}
        )
        == '{"z":"值","a":1}'
    )


def test_provider_output_write_is_atomic_and_immutable(tmp_path: Path) -> None:
    target = tmp_path / "provider-output"
    expected = hashlib.sha256("精确 final".encode("utf-8")).hexdigest()
    assert subject._atomic_bytes(target, "精确 final".encode("utf-8")) == expected
    assert target.read_bytes() == "精确 final".encode("utf-8")
    with pytest.raises(FileExistsError):
        subject._atomic_bytes(target, b"replacement")


def test_rules_ref_and_candidate_write_boundary_are_hash_bound_before_model(
    tmp_path: Path,
) -> None:
    rules = tmp_path / "rules.txt"
    rules.write_text("sealed rules", encoding="utf-8")
    rules_sha = subject._sha(rules)
    package = {
        "rules_ref": {"path": str(rules), "sha256": rules_sha},
        "rules_sha256": rules_sha,
    }
    assert subject._package_artifact_ref(
        package, "rules_ref", expected_sha256_field="rules_sha256"
    ) == {"path": str(rules.resolve()), "sha256": rules_sha}

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    assert subject._candidate_write_domain(candidate) == (
        "candidate_output_root:"
        + str(candidate.resolve()).replace("\\", "/").casefold()
    )

    rules.write_text("drifted rules", encoding="utf-8")
    with pytest.raises(ValueError, match="hash-bound artifact drifted"):
        subject._package_artifact_ref(
            package, "rules_ref", expected_sha256_field="rules_sha256"
        )


def _prior_reuse_binding_fixture(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object], Path, str]:
    ancestor_path = tmp_path / "manifest-r1.json"
    package: dict[str, object] = {
        "package_id": "pkg-1",
        "work_key": "wk-1",
        "parent_work_key": "parent-1",
        "package_identity_sha256": "1" * 64,
    }
    ancestor = {
        "schema_version": "xinao.worker_package_batch.v3",
        "parent_work_key": "parent-1",
        "graph_revision": 1,
        "predecessor_manifest_ref": None,
        "packages": [dict(package)],
    }
    ancestor_sha = _write_json(ancestor_path, ancestor)
    operation_id = subject._operation_id(package)
    lane = tmp_path / "prior" / "lane_00"
    contract_path = lane / "common_logical_contract.json"
    contract = {
        "logical_operation_id": operation_id,
        "work_key": "wk-1",
        "task_contract_ref": f"{ancestor_path.resolve()}#sha256={ancestor_sha}",
    }
    contract_file_sha = _write_json(contract_path, contract)
    contract_digest = "2" * 64
    provider_path = lane / "latest.json"
    provider_sha = _write_json(
        provider_path,
        {
            "common_contract_preflight": {
                "validated": True,
                "logical_contract_sha256": contract_digest,
                "subject_manifest_sha256": ancestor_sha,
                "frozen_context_sha256": "3" * 64,
            }
        },
    )
    attempt_path = lane / "common_attempt_receipt.json"
    attempt_sha = _write_json(
        attempt_path,
        {
            "logical_operation_id": operation_id,
            "work_key": "wk-1",
            "contract_sha256": contract_digest,
            "provider_evidence_ref": str(provider_path.resolve()),
            "provider_evidence_sha256": provider_sha,
        },
    )
    _write_json(
        lane / "common_adapter_receipt.json",
        {
            "common_receipt_accepted": True,
            "provider_native_accepted": True,
            "authority": False,
            "completion_claim_allowed": False,
            "contract_sha256": contract_digest,
            "artifact_paths": {
                "attempt_receipt": str(attempt_path.resolve()),
                "logical_contract": str(contract_path.resolve()),
            },
            "artifact_sha256": {
                "attempt_receipt": attempt_sha,
                "logical_contract": contract_file_sha,
            },
        },
    )
    package["prior_attempt_receipt_ref"] = {
        "path": str(attempt_path.resolve()),
        "sha256": attempt_sha,
    }
    validated = {
        "schema_version": "xinao.worker_package_batch.v3",
        "parent_work_key": "parent-1",
        "graph_revision": 2,
        "predecessor_manifest_ref": {
            "path": str(ancestor_path.resolve()),
            "sha256": ancestor_sha,
        },
        "packages": [package],
    }
    current_path = tmp_path / "manifest-r2.json"
    current_sha = _write_json(current_path, {"schema_version": "test.current"})
    return package, validated, current_path, current_sha


def test_prior_reuse_binds_exact_accepted_ancestor_contract(tmp_path: Path) -> None:
    package, validated, current_path, current_sha = _prior_reuse_binding_fixture(tmp_path)
    binding = subject._prior_reuse_contract_binding(
        package=package,
        validated_manifest=validated,
        current_manifest_path=current_path,
        current_manifest_sha256=current_sha,
        validate_attempt_receipt=lambda *_args, **_kwargs: SimpleNamespace(
            accepted=True, reason_codes=()
        ),
    )
    predecessor = validated["predecessor_manifest_ref"]
    assert isinstance(predecessor, dict)
    assert binding["binding_source"] == "prior_accepted_ancestor_manifest"
    assert binding["task_contract_ref"] == (
        f"{Path(str(predecessor['path'])).resolve()}#sha256={predecessor['sha256']}"
    )
    assert binding["subject_manifest_sha256"] == predecessor["sha256"]


def test_prior_reuse_rejects_ancestor_bytes_drift_before_claim(tmp_path: Path) -> None:
    package, validated, current_path, current_sha = _prior_reuse_binding_fixture(tmp_path)
    predecessor = validated["predecessor_manifest_ref"]
    assert isinstance(predecessor, dict)
    ancestor_path = Path(str(predecessor["path"]))
    ancestor = json.loads(ancestor_path.read_text(encoding="utf-8"))
    ancestor["packages"][0]["package_identity_sha256"] = "9" * 64
    _write_json(ancestor_path, ancestor)
    with pytest.raises(ValueError, match="task_contract_ref bytes drifted"):
        subject._prior_reuse_contract_binding(
            package=package,
            validated_manifest=validated,
            current_manifest_path=current_path,
            current_manifest_sha256=current_sha,
            validate_attempt_receipt=lambda *_args, **_kwargs: SimpleNamespace(
                accepted=True, reason_codes=()
            ),
        )


def test_prior_reuse_rejects_adapter_artifact_drift_before_claim(tmp_path: Path) -> None:
    package, validated, current_path, current_sha = _prior_reuse_binding_fixture(tmp_path)
    prior = package["prior_attempt_receipt_ref"]
    assert isinstance(prior, dict)
    adapter_path = Path(str(prior["path"])).parent / "common_adapter_receipt.json"
    adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
    adapter["artifact_sha256"]["attempt_receipt"] = "0" * 64
    _write_json(adapter_path, adapter)
    with pytest.raises(ValueError, match="artifact binding drifted"):
        subject._prior_reuse_contract_binding(
            package=package,
            validated_manifest=validated,
            current_manifest_path=current_path,
            current_manifest_sha256=current_sha,
            validate_attempt_receipt=lambda *_args, **_kwargs: SimpleNamespace(
                accepted=True, reason_codes=()
            ),
        )


def test_direct_runner_rejects_b_temporal_and_fake_adapter_before_provider() -> None:
    envelope = {
        "leg": "A",
        "selection": {"decision_sha256": "d" * 64},
        **_direct_route_validation_fields("d" * 64),
    }
    assert (
        subject._require_direct_route_envelope(envelope)["route_choice"]["leg"] == "A"
    )

    wrong_leg = {**envelope, "leg": "B"}
    with pytest.raises(ValueError, match="leg-A"):
        subject._require_direct_route_envelope(wrong_leg)

    temporal = json.loads(json.dumps(envelope))
    temporal["validated_selected_candidate"]["transport_id"] = (
        "temporal-docker-langgraph"
    )
    with pytest.raises(ValueError, match="transport_id"):
        subject._require_direct_route_envelope(temporal)

    fake_adapter = {**envelope, "validated_execution_adapter": {"fake": True}}
    with pytest.raises(ValueError, match="cannot consume a provider route adapter"):
        subject._require_direct_route_envelope(fake_adapter)


def test_nonzero_provider_exit_with_valid_common_receipt_is_terminal_recordable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root = tmp_path / "runtime"
    output_root = tmp_path / "package-output"
    output_root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("bounded task", encoding="utf-8")
    context = tmp_path / "context.json"
    _write_json(context, {"authority": False, "completion_claim_allowed": False})
    rules = tmp_path / "rules.txt"
    rules.write_text("candidate-only rules", encoding="utf-8")
    rules_sha = subject._sha(rules)
    manifest = tmp_path / "worker-package-batch.json"
    envelope = tmp_path / "dispatch-envelope.json"
    selection = tmp_path / "selection.json"
    dispatch_script = tmp_path / "dispatch.ps1"
    selector_python = tmp_path / "python.exe"
    selector_root = tmp_path / "selector-root"
    selector_root.mkdir()
    for path in (manifest, envelope, selection, dispatch_script, selector_python):
        path.write_text("{}", encoding="utf-8")

    package = {
        "package_id": "pkg-1",
        "work_key": "wk-1",
        "parent_work_key": "parent-1",
        "package_identity_sha256": "1" * 64,
        "prompt_ref": {"path": str(prompt)},
        "context_manifest_ref": {"path": str(context)},
        "rules_ref": {"path": str(rules), "sha256": rules_sha},
        "rules_sha256": rules_sha,
        "cwd": str(cwd),
        "phase": "VERIFY",
        "role": "critic",
        "acceptance": {
            "min_result_chars": 1,
            "required_result_markers": [],
            "require_json_object": False,
            "json_schema_ref": None,
        },
        "write_domains": [],
        "depends_on": [],
        "timeout_sec": 30,
        "allowed_output_root": str(output_root),
    }
    final_text = "rejected but receipted\r\n最终"
    final_sha = hashlib.sha256(final_text.encode("utf-8")).hexdigest()
    route_validation_calls = 0

    def validate_route_claim(**_kwargs: object) -> dict[str, object]:
        nonlocal route_validation_calls
        route_validation_calls += 1
        return {
            "leg": "A",
            "choice_sha256": "e" * 64,
            "physical_consumer_id": "grok_direct_worker_pool_consumer",
            "model_invocation_allowed": True,
        }

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert route_validation_calls == 3
        assert command[command.index("-DispatchEpochId") + 1] == "epoch-1"
        assert command[command.index("-DispatchEpochSource") + 1] == (
            "neutral_package_manifest"
        )
        assert command[command.index("-QuotaSnapshotId") + 1] == "quota-1"
        assert command[command.index("-QuotaResolutionStatus") + 1] == (
            "sealed_manifest"
        )
        assert command[command.index("-CommonRulesFile") + 1] == str(rules.resolve())
        assert command[command.index("-CommonRulesSha256") + 1] == rules_sha
        assert command[command.index("-CommonCandidateOutputRoot") + 1] == str(
            output_root.resolve()
        )
        assert command[command.index("-CommonTaskContractRef") + 1] == "task-ref"
        assert command[command.index("-CommonSubjectManifestSha256") + 1] == "7" * 64
        write_domain_index = command.index("-CommonWriteDomains") + 1
        assert command[write_domain_index] == (
            "candidate_output_root:"
            + str(output_root.resolve()).replace("\\", "/").casefold()
        )
        pool_id = command[command.index("-PoolId") + 1]
        operation_id = command[command.index("-CommonOperationId") + 1]
        lane_dir = runtime_root / "state" / "grok_worker_pool" / pool_id / "lane_00"
        cli_json = lane_dir / "provider-cli.json"
        _write_json(cli_json, {"text": final_text})
        meta_path = lane_dir / "latest.json"
        meta_sha = _write_json(
            meta_path,
            {
                "cli_json": str(cli_json),
                "effective_output_source": "text",
            },
        )
        contract_path = lane_dir / "common_logical_contract.json"
        contract_sha = _write_json(
            contract_path,
            {
                "logical_operation_id": operation_id,
                "work_key": package["work_key"],
            },
        )
        attempt_path = lane_dir / "common_attempt_receipt.json"
        attempt_sha = _write_json(
            attempt_path,
            {
                "logical_operation_id": operation_id,
                "work_key": package["work_key"],
                "attempt": 2,
                "output": {"content_sha256": final_sha},
            },
        )
        common_path = lane_dir / "common_adapter_receipt.json"
        common_sha = _write_json(
            common_path,
            {
                "work_key": package["work_key"],
                "logical_operation_id": operation_id,
                "provider_evidence_ref": str(meta_path),
                "provider_evidence_sha256": meta_sha,
                "artifact_paths": {
                    "attempt_receipt": str(attempt_path),
                    "logical_contract": str(contract_path),
                },
                "artifact_sha256": {
                    "attempt_receipt": attempt_sha,
                    "logical_contract": contract_sha,
                },
            },
        )
        summary_path = (
            runtime_root / "state" / "grok_worker_pool" / pool_id / "pool_summary.json"
        )
        _write_json(
            summary_path,
            {
                "n": 1,
                "model": "grok-test",
                "selection_decision_sha256": "2" * 64,
                "results": [
                    {
                        "status": "rejected",
                        "meta_path": str(meta_path),
                        "evidence_dir": str(lane_dir),
                    }
                ],
                "common_adapter_receipt_path": str(common_path),
                "common_adapter_receipt_sha256": common_sha,
            },
        )
        return subprocess.CompletedProcess(command, 3, "", "provider rejected")

    def fake_guarded_run(
        command: list[str],
        *,
        timeout_seconds: int,
        live_guard: object,
    ) -> subprocess.CompletedProcess[str]:
        del timeout_seconds
        assert callable(live_guard)
        live_guard()
        return fake_run(command)

    monkeypatch.setattr(subject, "_run_process_with_live_guard", fake_guarded_run)
    expected_consumers: list[str | None] = []

    def validate_terminal_attempt(
        _contract: object,
        _attempt: object,
        *,
        expected_consumer_id: str | None = None,
    ) -> SimpleNamespace:
        expected_consumers.append(expected_consumer_id)
        return SimpleNamespace(
            accepted=False, reason_codes=("TERMINAL_STATE_NOT_COMPLETED",)
        )

    result = subject._run_package(
        package=package,
        candidate_cwd=output_root,
        manifest_path=manifest,
        manifest_sha256=subject._sha(manifest),
        dispatch_envelope_path=envelope,
        dispatch_envelope_sha256=subject._sha(envelope),
        dispatch_script=dispatch_script,
        pwsh="pwsh",
        runtime_root=runtime_root,
        model="grok-test",
        selection_path=selection,
        selection_sha256="2" * 64,
        dispatch_epoch={
            "epoch_id": "epoch-1",
            "quota_snapshot_id": "quota-1",
            "quota_snapshot_ref": str(tmp_path / "quota.json"),
            "quota_snapshot_sha256": "3" * 64,
        },
        selector_root=selector_root,
        selector_python=selector_python,
        route_claim_evidence_ref="route-claim.json#sha256=" + "9" * 64,
        route_choice_sha256="e" * 64,
        physical_consumer_id="grok_direct_worker_pool_consumer",
        task_run_dir=tmp_path / "run-1",
        task_run_id="run-1",
        common_contract_binding={
            "task_contract_ref": "task-ref",
            "subject_manifest_sha256": "7" * 64,
            "binding_source": "fixture",
        },
        validate_dispatch_route_claim=validate_route_claim,
        timeout_sec=30,
        validate_attempt_receipt=validate_terminal_attempt,
    )

    assert result["status"] == "terminal_ready"
    assert expected_consumers == [subject.EXPECTED_DIRECT_ATTEMPT_CONSUMER_ID]
    assert route_validation_calls == 3
    assert result["terminal_recordable"] is True
    assert result["exit_code"] == 3
    assert result["attempt"] == 2
    provider_output = Path(result["provider_output_ref"]["path"])
    assert provider_output.name == "provider-output"
    assert provider_output.read_bytes() == final_text.encode("utf-8")
    assert result["provider_output_ref"]["sha256"] == final_sha
    event_shas = {ref["sha256"] for ref in result["event_artifact_refs"]}
    assert result["provider_output_ref"]["sha256"] in event_shas
    assert result["common_attempt_sha256"] not in event_shas
    assert result["common_contract_sha256"] not in event_shas
    assert result["common_adapter_receipt_sha256"] not in event_shas
    assert result["pool_summary_sha256"] not in event_shas
    package_result = json.loads(
        Path(result["package_result_ref"]).read_text(encoding="utf-8")
    )
    assert "provider_accepted" not in package_result
    assert "usage" not in package_result
    assert package_result["package_manifest_ref"]["sha256"] == subject._sha(manifest)
    assert package_result["dispatch_envelope_ref"]["sha256"] == subject._sha(envelope)


def test_provider_process_is_terminated_when_live_route_guard_freezes() -> None:
    checks = 0

    def frozen_guard() -> None:
        nonlocal checks
        checks += 1
        raise RuntimeError("RUN_MUTATION_FROZEN")

    with pytest.raises(RuntimeError, match="RUN_MUTATION_FROZEN"):
        subject._run_process_with_live_guard(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout_seconds=10,
            live_guard=frozen_guard,
        )
    assert checks == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows console semantics")
def test_production_guarded_spawn_is_windowless_and_keeps_stdout() -> None:
    completed = subject._run_process_with_live_guard(
        [
            sys.executable,
            "-c",
            (
                "import ctypes; "
                "print(int(ctypes.windll.kernel32.GetConsoleWindow()))"
            ),
        ],
        timeout_seconds=10,
        live_guard=lambda: None,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "0"


def test_candidate_cwd_is_exact_existing_output_not_source_repo_or_traversal(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "candidate-output"
    runtime = tmp_path / "runtime"
    selector = tmp_path / "selector"
    for path in (source, output, runtime, selector):
        path.mkdir()
    package = {"cwd": str(source), "allowed_output_root": str(output)}

    assert subject._require_exact_candidate_cwd(
        package=package,
        candidate_cwd=output,
        selector_root=selector,
        runtime_root=runtime,
    ) == output.resolve(strict=True)

    with pytest.raises(ValueError, match="dot path traversal"):
        subject._require_exact_candidate_cwd(
            package={**package, "allowed_output_root": str(output / ".." / "other")},
            candidate_cwd=output,
            selector_root=selector,
            runtime_root=runtime,
        )
    with pytest.raises(ValueError, match="source cwd"):
        subject._require_exact_candidate_cwd(
            package={**package, "allowed_output_root": str(source)},
            candidate_cwd=source,
            selector_root=selector,
            runtime_root=runtime,
        )
    repo_root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="Grok repository"):
        subject._require_exact_candidate_cwd(
            package={**package, "allowed_output_root": str(repo_root)},
            candidate_cwd=repo_root,
            selector_root=selector,
            runtime_root=runtime,
        )


def test_candidate_cwd_rejects_symlink_or_junction_escape(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    link = tmp_path / "linked-output"
    runtime = tmp_path / "runtime"
    selector = tmp_path / "selector"
    for path in (source, target, runtime, selector):
        path.mkdir()
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            pytest.skip("this host cannot create a symlink or junction")
    try:
        with pytest.raises(ValueError, match="symlink, junction, or reparse"):
            subject._require_exact_candidate_cwd(
                package={"cwd": str(source), "allowed_output_root": str(link)},
                candidate_cwd=link,
                selector_root=selector,
                runtime_root=runtime,
            )
    finally:
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            os.rmdir(link)


def test_worker_terminal_v2_builder_receives_only_hash_bound_predecessors() -> None:
    captured: dict[str, object] = {}

    def builder(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"schema_version": "xinao.dispatch_outcome_event.v2"}

    event = subject._build_worker_terminal_event(
        builder=builder,
        package={
            "package_id": "pkg-1",
            "parent_work_key": "parent-1",
            "work_key": "wk-1",
            "role": "critic",
        },
        result={
            "operation_id": "op-1",
            "event_artifact_refs": [{"path": "provider-output", "sha256": "a" * 64}],
            "common_attempt_ref": "attempt.json",
            "common_attempt_sha256": "b" * 64,
            "common_contract_ref": "contract.json",
            "common_contract_sha256": "c" * 64,
        },
        package_manifest_ref={"path": "manifest.json", "sha256": "d" * 64},
        dispatch_envelope_ref={"path": "envelope.json", "sha256": "e" * 64},
        leg="A",
    )

    assert event["schema_version"] == "xinao.dispatch_outcome_event.v2"
    assert captured["event_type"] == "worker_terminal"
    assert captured["package_manifest_ref"] == {
        "path": "manifest.json",
        "sha256": "d" * 64,
    }
    assert captured["dispatch_envelope_ref"] == {
        "path": "envelope.json",
        "sha256": "e" * 64,
    }
    assert "provider_accepted" not in captured
    assert "usage" not in captured


def test_side_effect_identity_separates_operation_attempt_and_retry() -> None:
    first = subject._terminal_side_effect_id(
        logical_operation_id="op-1", attempt=1, dispatch_id="cdx-first"
    )
    second_attempt = subject._terminal_side_effect_id(
        logical_operation_id="op-1", attempt=2, dispatch_id="cdx-second"
    )
    other_operation = subject._terminal_side_effect_id(
        logical_operation_id="op-2", attempt=1, dispatch_id="cdx-first"
    )
    assert len({first, second_attempt, other_operation}) == 3
    assert "op-1:attempt-1:retry-cdx-first" in first


def test_typed_common_dependency_is_canonical_and_preserves_exact_pin() -> None:
    dependency = {
        "result_selector": "consumer_readback",
        "pin": {
            "artifact_ref": {"sha256": "b" * 64, "path": "effect.json"},
            "event_ref": {"sha256": "a" * 64, "path": "event.json"},
        },
        "condition": "effect_verified",
        "package_id": "pkg-upstream",
    }
    reordered = {
        "package_id": "pkg-upstream",
        "condition": "effect_verified",
        "result_selector": "consumer_readback",
        "pin": {
            "event_ref": {"path": "event.json", "sha256": "a" * 64},
            "artifact_ref": {"path": "effect.json", "sha256": "b" * 64},
        },
    }

    encoded = subject._common_dependency_arg(dependency)

    assert encoded == subject._common_dependency_arg(reordered)
    assert json.loads(encoded) == reordered
    assert subject._common_dependency_arg("legacy-package") == "legacy-package"


def test_runtime_dependencies_only_include_batch_worker_terminal_edges() -> None:
    packages = {
        "p1": {"depends_on": []},
        "p2": {
            "depends_on": [
                {
                    "package_id": "p1",
                    "condition": "worker_terminal",
                    "result_selector": "primary_artifact",
                    "pin": {
                        "event_ref": {"path": "worker.json", "sha256": "a" * 64},
                        "artifact_ref": {
                            "path": "candidate.json",
                            "sha256": "b" * 64,
                        },
                    },
                },
                {
                    "package_id": "p3",
                    "condition": "owner_adopted",
                    "result_selector": "outcome_artifact",
                    "pin": {
                        "event_ref": {"path": "owner.json", "sha256": "c" * 64},
                        "artifact_ref": {"path": "land.json", "sha256": "d" * 64},
                    },
                },
                {
                    "package_id": "outside",
                    "condition": "worker_terminal",
                    "result_selector": "primary_artifact",
                    "pin": {
                        "event_ref": {"path": "old.json", "sha256": "e" * 64},
                        "artifact_ref": {"path": "old-result", "sha256": "f" * 64},
                    },
                },
            ]
        },
        "p3": {
            "depends_on": [
                {
                    "package_id": "p1",
                    "condition": "effect_verified",
                    "result_selector": "consumer_readback",
                    "pin": {
                        "event_ref": {"path": "effect.json", "sha256": "1" * 64},
                        "artifact_ref": {
                            "path": "readback.json",
                            "sha256": "2" * 64,
                        },
                    },
                }
            ]
        },
    }

    assert subject._runtime_worker_dependencies(packages) == {
        "p1": set(),
        "p2": {"p1"},
        "p3": set(),
    }


def test_rejected_worker_terminal_blocks_only_its_runtime_dependents() -> None:
    runtime_dependencies = {
        "p1": set(),
        "p2": {"p1"},
        "p3": set(),
    }

    assert subject._pending_dependency_state(
        "p2",
        runtime_dependencies=runtime_dependencies,
        provider_satisfied=set(),
        failed={"p1"},
        blocked=set(),
    ) == (False, {"p1"})
    assert subject._pending_dependency_state(
        "p3",
        runtime_dependencies=runtime_dependencies,
        provider_satisfied=set(),
        failed={"p1"},
        blocked=set(),
    ) == (True, set())


def test_main_accepts_typed_pinned_owner_edge_without_provider_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    envelope_path = tmp_path / "envelope.json"
    selection_path = tmp_path / "selection.json"
    summary_path = tmp_path / "summary.json"
    for path in (manifest_path, envelope_path, selection_path):
        _write_json(path, {})
    packages = [
        {
            "package_id": "p1",
            "work_key": "wk-1",
            "lane_index": 0,
            "candidate_only": True,
            "execution_seal_ready": True,
            "depends_on": [],
        },
        {
            "package_id": "p2",
            "work_key": "wk-2",
            "lane_index": 1,
            "candidate_only": True,
            "execution_seal_ready": True,
            "depends_on": [
                {
                    "package_id": "p1",
                    "condition": "owner_adopted",
                    "result_selector": "outcome_artifact",
                    "pin": {
                        "event_ref": {"path": "owner.json", "sha256": "a" * 64},
                        "artifact_ref": {"path": "land.json", "sha256": "b" * 64},
                    },
                }
            ],
        },
    ]
    validated = {
        "packages": packages,
        "limits": {"max_parallel": 2, "fan_in_capacity": 2},
        "validated_manifest_sha256": "c" * 64,
    }
    envelope = {
        "package_manifest_ref": {
            "path": str(manifest_path),
            "sha256": subject._sha(manifest_path),
        },
        "validated_package_manifest": validated,
        "package_ids": ["p1", "p2"],
        "selection": {
            "model_id": "grok-test",
            "receipt_ref": str(selection_path),
            "decision_sha256": "d" * 64,
        },
        "dispatch_epoch": {
            "epoch_id": "epoch-1",
            "quota_snapshot_id": "quota-1",
            "quota_snapshot_ref": str(tmp_path / "quota.json"),
            "quota_snapshot_sha256": "3" * 64,
        },
        "leg": "A",
        **_direct_route_validation_fields("d" * 64),
    }
    claim_calls: list[dict[str, object]] = []

    def claim(**kwargs: object) -> dict[str, object]:
        claim_calls.append(dict(kwargs))
        return _route_claim_result(envelope)

    _install_fake_selector_contract(
        monkeypatch,
        envelope=envelope,
        frontier={"admitted": packages},
        claim=claim,
    )
    _set_main_argv(
        monkeypatch,
        tmp_path,
        envelope_path=envelope_path,
        selection_path=selection_path,
        summary_path=summary_path,
    )
    observed: list[str] = []

    def fake_run_package(**kwargs: object) -> dict[str, object]:
        assert len(claim_calls) == 1
        package = kwargs["package"]
        assert isinstance(package, dict)
        candidate_cwd = kwargs["candidate_cwd"]
        assert isinstance(candidate_cwd, Path)
        assert candidate_cwd == Path(str(package["allowed_output_root"])).resolve()
        assert candidate_cwd != Path(str(package["cwd"])).resolve()
        observed.append(str(package["package_id"]))
        return {
            "package_id": package["package_id"],
            "work_key": package["work_key"],
            "status": "reused",
        }

    monkeypatch.setattr(subject, "_run_package", fake_run_package)

    assert subject.main() == 0
    assert len(claim_calls) == 1
    assert claim_calls[0]["task_run_dir"] == tmp_path / "task-runs" / "run-1"
    assert set(observed) == {"p1", "p2"}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["satisfied_package_ids"] == ["p1", "p2"]
    assert summary["dispatch_route_claim"]["status"] == "won"


def test_main_rejects_conflicting_route_claim_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    envelope_path = tmp_path / "envelope.json"
    selection_path = tmp_path / "selection.json"
    summary_path = tmp_path / "summary.json"
    for path in (manifest_path, envelope_path, selection_path):
        _write_json(path, {})
    package = {
        "package_id": "p1",
        "work_key": "wk-1",
        "lane_index": 0,
        "candidate_only": True,
        "execution_seal_ready": True,
        "depends_on": [],
    }
    envelope = {
        "package_manifest_ref": {
            "path": str(manifest_path),
            "sha256": subject._sha(manifest_path),
        },
        "validated_package_manifest": {
            "packages": [package],
            "limits": {"max_parallel": 1, "fan_in_capacity": 1},
            "validated_manifest_sha256": "c" * 64,
        },
        "package_ids": ["p1"],
        "selection": {
            "model_id": "grok-test",
            "receipt_ref": str(selection_path),
            "decision_sha256": "d" * 64,
        },
        "dispatch_epoch": {
            "epoch_id": "epoch-1",
            "quota_snapshot_id": "quota-1",
            "quota_snapshot_ref": str(tmp_path / "quota.json"),
            "quota_snapshot_sha256": "3" * 64,
        },
        "leg": "A",
        **_direct_route_validation_fields("d" * 64),
    }

    def conflicting_claim(**_kwargs: object) -> dict[str, object]:
        raise ValueError("alternative group is already claimed by another route choice")

    _install_fake_selector_contract(
        monkeypatch,
        envelope=envelope,
        frontier={"admitted": [package]},
        claim=conflicting_claim,
    )
    _set_main_argv(
        monkeypatch,
        tmp_path,
        envelope_path=envelope_path,
        selection_path=selection_path,
        summary_path=summary_path,
    )
    monkeypatch.setattr(
        subject,
        "_run_package",
        lambda **_kwargs: pytest.fail("provider started after route-claim conflict"),
    )

    with pytest.raises(ValueError, match="already claimed by another route choice"):
        subject.main()
    assert not summary_path.exists()


def test_main_rejects_selector_schema_pin_drift_before_claim_or_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    envelope_path = tmp_path / "envelope.json"
    selection_path = tmp_path / "selection.json"
    summary_path = tmp_path / "summary.json"
    for path in (manifest_path, envelope_path, selection_path):
        _write_json(path, {})
    package = {
        "package_id": "p1",
        "work_key": "wk-1",
        "lane_index": 0,
        "candidate_only": True,
        "execution_seal_ready": True,
        "depends_on": [],
    }
    envelope = {
        "package_manifest_ref": {
            "path": str(manifest_path),
            "sha256": subject._sha(manifest_path),
        },
        "validated_package_manifest": {
            "packages": [package],
            "limits": {"max_parallel": 1, "fan_in_capacity": 1},
            "validated_manifest_sha256": "c" * 64,
        },
        "package_ids": ["p1"],
        "selection": {
            "model_id": "grok-test",
            "receipt_ref": str(selection_path),
            "decision_sha256": "d" * 64,
        },
        "dispatch_epoch": {
            "epoch_id": "epoch-1",
            "quota_snapshot_id": "quota-1",
            "quota_snapshot_ref": str(tmp_path / "quota.json"),
            "quota_snapshot_sha256": "3" * 64,
        },
        "leg": "A",
        **_direct_route_validation_fields("d" * 64),
    }
    claim_calls: list[object] = []
    contract = _install_fake_selector_contract(
        monkeypatch,
        envelope=envelope,
        frontier={"admitted": [package]},
        claim=lambda **kwargs: claim_calls.append(kwargs),
    )
    contract.PACKAGE_BATCH_SCHEMA = "xinao.worker_package_batch.v2"  # type: ignore[attr-defined]
    _set_main_argv(
        monkeypatch,
        tmp_path,
        envelope_path=envelope_path,
        selection_path=selection_path,
        summary_path=summary_path,
    )
    monkeypatch.setattr(
        subject,
        "_run_package",
        lambda **_kwargs: pytest.fail("provider started after selector pin drift"),
    )

    with pytest.raises(RuntimeError, match="PACKAGE_BATCH_SCHEMA"):
        subject.main()
    assert claim_calls == []


def test_main_rejects_envelope_outside_planned_worker_frontier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    envelope_path = tmp_path / "envelope.json"
    selection_path = tmp_path / "selection.json"
    summary_path = tmp_path / "summary.json"
    for path in (manifest_path, envelope_path, selection_path):
        _write_json(path, {})
    packages = [
        {
            "package_id": package_id,
            "work_key": f"wk-{package_id}",
            "lane_index": index,
            "candidate_only": True,
            "execution_seal_ready": True,
            "depends_on": [],
        }
        for index, package_id in enumerate(("p1", "p2"))
    ]
    validated = {
        "packages": packages,
        "limits": {"max_parallel": 1, "fan_in_capacity": 1},
        "validated_manifest_sha256": "c" * 64,
    }
    envelope = {
        "package_manifest_ref": {
            "path": str(manifest_path),
            "sha256": subject._sha(manifest_path),
        },
        "validated_package_manifest": validated,
        "package_ids": ["p2"],
        "selection": {
            "model_id": "grok-test",
            "receipt_ref": str(selection_path),
            "decision_sha256": "d" * 64,
        },
        "dispatch_epoch": {
            "epoch_id": "epoch-1",
            "quota_snapshot_id": "quota-1",
            "quota_snapshot_ref": str(tmp_path / "quota.json"),
            "quota_snapshot_sha256": "3" * 64,
        },
        "leg": "A",
        **_direct_route_validation_fields("d" * 64),
    }
    _install_fake_selector_contract(
        monkeypatch,
        envelope=envelope,
        frontier={"admitted": [packages[0]]},
    )
    _set_main_argv(
        monkeypatch,
        tmp_path,
        envelope_path=envelope_path,
        selection_path=selection_path,
        summary_path=summary_path,
    )
    monkeypatch.setattr(
        subject,
        "_run_package",
        lambda **_kwargs: pytest.fail("outside-frontier package was dispatched"),
    )

    with pytest.raises(ValueError, match="outside the planned worker frontier: p2"):
        subject.main()


def test_rejected_terminal_is_appended_with_retry_specific_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[str] = []
    observed_kwargs: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.extend(command)
        observed_kwargs.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    subject._append_task_run_event(
        task_run_cli=tmp_path / "task_run.py",
        task_run_root=tmp_path / "runs",
        task_run_id="run-1",
        event_path=tmp_path / "worker-terminal-event.json",
        event_sha256="a" * 64,
        work_key="wk-1",
        package_id="pkg-1",
        logical_operation_id="op-1",
        attempt=2,
        dispatch_id="cdx-retry",
        provider_accepted=False,
        provider_exit_code=7,
    )

    assert observed[observed.index("--exit-code") + 1] == "7"
    assert observed[observed.index("--side-effect-id") + 1].endswith(
        "op-1:attempt-2:retry-cdx-retry"
    )
    assert (
        "provider rejected package pkg-1" in observed[observed.index("--summary") + 1]
    )
    assert observed[0] == sys.executable
    assert not str(observed[0]).casefold().endswith(".py")
    assert observed_kwargs["creationflags"] == subject.WINDOWLESS_CREATIONFLAGS


def test_non_conversion_is_hash_bound_to_native_pool_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[str] = []
    observed_kwargs: dict[str, object] = {}
    pool_summary = tmp_path / "pool-summary.json"
    pool_summary.write_text(
        '{"pool_id":"gwp-1","results":[{"status":"accepted","usage":{"total_tokens":17}}]}\n',
        encoding="utf-8",
    )
    pool_sha = subject._sha(pool_summary)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.extend(command)
        observed_kwargs.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    recorded = subject._append_task_run_non_conversion(
        task_run_cli=tmp_path / "task_run.py",
        task_run_root=tmp_path / "runs",
        task_run_id="run-1",
        result={
            "package_id": "pkg-1",
            "work_key": "wk-1",
            "pool_summary_ref": str(pool_summary),
            "failure": "fan-in rejected control evidence",
            "exit_code": 0,
        },
    )

    assert recorded is True
    assert observed[observed.index("--kind") + 1] == "failure"
    assert observed[observed.index("--phase") + 1] == "dispatch_attempt_non_conversion"
    assert observed[observed.index("--exit-code") + 1] == "20"
    assert observed[observed.index("--evidence-ref") + 1] == (
        f"{pool_summary.resolve()}#sha256={pool_sha}"
    )
    assert observed[observed.index("--side-effect-id") + 1].endswith(pool_sha[:32])
    assert observed[0] == sys.executable
    assert observed_kwargs["creationflags"] == subject.WINDOWLESS_CREATIONFLAGS


def test_non_conversion_does_not_claim_recorded_without_pool_summary(tmp_path: Path) -> None:
    assert (
        subject._append_task_run_non_conversion(
            task_run_cli=tmp_path / "task_run.py",
            task_run_root=tmp_path / "runs",
            task_run_id="run-1",
            result={"package_id": "pkg-1", "work_key": "wk-1"},
        )
        is False
    )


def test_non_conversion_rehashes_and_rejects_drifted_pool_summary(tmp_path: Path) -> None:
    pool_summary = tmp_path / "pool-summary.json"
    pool_summary.write_text('{"pool_id":"gwp-1","results":[]}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="pool summary sha256 drifted"):
        subject._append_task_run_non_conversion(
            task_run_cli=tmp_path / "task_run.py",
            task_run_root=tmp_path / "runs",
            task_run_id="run-1",
            result={
                "package_id": "pkg-1",
                "work_key": "wk-1",
                "pool_summary_ref": str(pool_summary),
                "pool_summary_sha256": "0" * 64,
            },
        )


def test_non_conversion_preserves_timeout_as_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[str] = []
    pool_summary = tmp_path / "pool-summary.json"
    pool_summary.write_text(
        '{"pool_id":"gwp-1","results":[{"status":"timeout","usage":{"total_tokens":3}}]}\n',
        encoding="utf-8",
    )

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        observed.extend(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    assert subject._append_task_run_non_conversion(
        task_run_cli=tmp_path / "task_run.py",
        task_run_root=tmp_path / "runs",
        task_run_id="run-1",
        result={
            "package_id": "pkg-1",
            "work_key": "wk-1",
            "pool_summary_ref": str(pool_summary),
            "failure": "worker timeout after provider start",
            "exit_code": 124,
            "timed_out": True,
        },
    )
    assert observed[observed.index("--retry-class") + 1] == "transient"


def test_dispatch_envelope_is_primary_powershell_parameter() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bridge = (
        repo_root / "grok-admin-bridge" / "Invoke-CodexGrokPackageBatch.ps1"
    ).read_text(encoding="utf-8-sig")
    launcher = (repo_root / "launchers" / "Invoke-Codex-GrokWorkerPool.ps1").read_text(
        encoding="utf-8-sig"
    )
    for text in (bridge, launcher):
        assert '[Alias("PackageManifestPath")]' in text
        assert "[string]$DispatchEnvelopePath" in text
        assert "$PackageManifestPath" not in text
