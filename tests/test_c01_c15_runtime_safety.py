from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_c01_c15.py"
    spec = importlib.util.spec_from_file_location("verify_c01_c15_runtime_safety", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_materials_prefer_current_authority_and_fall_back_per_file(tmp_path: Path) -> None:
    module = _module()
    current = tmp_path / "主线" / "双脑"
    legacy = tmp_path / "新建文件夹"
    current.mkdir(parents=True)
    legacy.mkdir()
    (current / module.MATERIAL_FILENAMES["开工规划"]).write_text("current", encoding="utf-8")
    (legacy / module.MATERIAL_FILENAMES["施工包"]).write_text("legacy", encoding="utf-8")

    resolved = module.resolve_materials((current, legacy))

    assert resolved["开工规划"].parent == current
    assert resolved["施工包"].parent == legacy
    assert resolved["硬合同"] == current / module.MATERIAL_FILENAMES["硬合同"]


def test_windows_child_probes_request_no_window(monkeypatch) -> None:
    module = _module()
    calls: list[dict] = []

    def fake_run(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.probe_os_persistence_fresh()

    assert len(calls) == 2
    assert all(call["creationflags"] == module.WINDOWLESS_CREATIONFLAGS for call in calls)


def test_scoped_verdict_cannot_close_whole_product(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "OUT_DIR", tmp_path)
    monkeypatch.setattr(module, "OUT_MATRIX", tmp_path / "completion_matrix.json")
    monkeypatch.setattr(module, "OUT_RUNLOG", tmp_path / "verifier_run.json")
    for probe in (
        "probe_materials",
        "probe_worktree",
        "probe_prod_kernel",
        "probe_l0_assets",
        "probe_generation_pin",
        "probe_os_persistence_fresh",
    ):
        monkeypatch.setattr(module, probe, lambda: {})

    for index in range(1, 16):
        cid = f"C{index:02d}"
        verdict = "PASS_SCOPED" if cid == "C12" else "PASS"
        row = {
            "id": cid,
            "criterion_cn": cid,
            "source": "test",
            "verdict": verdict,
            "ok": True,
            "evidence": [],
            "missing_evidence": [],
            "checks": {},
            "notes": [],
        }
        monkeypatch.setattr(module, f"check_{cid.lower()}", lambda *_args, row=row: row)

    exit_code = module.main()
    matrix = json.loads(module.OUT_MATRIX.read_text(encoding="utf-8"))

    assert exit_code == 2
    assert matrix["product_closed"] is False
    assert matrix["completion_claim_allowed"] is False
    assert "C12" in matrix["summary"]["terminal_gap_ids"]
    assert any(item.startswith("C12:") for item in matrix["ready_frontier_next"])


def test_c12_synthetic_default_off_canary_stays_scoped(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "KAIGONG", tmp_path)
    payload = {
        "schema_version": "xinao.m_keep.canary.v1",
        "ok": True,
        "policy": {
            "capability_installed": True,
            "enabled": False,
            "observe_only": True,
            "timer": False,
            "daemon": False,
            "tui_attached": False,
        },
        "checks": {"default_disabled": True, "no_side_effects": True},
    }
    (tmp_path / "S6_mkeep_canary_latest.json").write_text(json.dumps(payload), encoding="utf-8")

    result = module.check_c12({"mkeep_impl_present": True, "mkeep_artifact_files": ["m_keep.py"]})

    assert result["ok"] is True
    assert result["verdict"] == "PASS_SCOPED"
    assert result["checks"]["s6"]["callable_canary_ok"] is False


def test_c11_self_reported_reader_exit_stays_scoped(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "KAIGONG", tmp_path)
    (tmp_path / "S3_readonly_board_refresh_latest.json").write_text("{}", encoding="utf-8")
    index = tmp_path / "overnight_S0S8_progress_index_latest.json"
    index.write_text("{}", encoding="utf-8")
    proof = {
        "schema_version": "xinao.c11.readonly_independence.v1",
        "generated_at_utc": "2026-07-12T00:00:00Z",
        "ok": True,
        "checks": {
            "board_visible": True,
            "fresh_process_closed_after_read": True,
            "doctor_after_ok": True,
            "business_counts_unchanged": True,
        },
        "matrix": {"sha256": "abc"},
    }
    (tmp_path / "C11_readonly_independence_latest.json").write_text(
        json.dumps(proof), encoding="utf-8"
    )

    result = module.check_c11()

    assert result["ok"] is True
    assert result["verdict"] == "PASS_SCOPED"
    assert result["checks"]["readonly_independence"]["ok"] is False


def test_c14_v1_boolean_audit_cannot_claim_full_supply_chain(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "SAT", tmp_path)
    monkeypatch.setattr(module, "CURRENT_JSON", tmp_path / "current.json")
    (tmp_path / "current.json").write_text("{}", encoding="utf-8")
    (tmp_path / "G10_generation_pin").mkdir()
    audit = {
        "schema_version": "xinao.c14.supply_chain.v1",
        "ok": True,
        "checks": {"current_pointer_matches_manifest": True, "rollback_dry_run_ok": True},
        "current": {"generation_id": "coord-current"},
    }
    (tmp_path / "G10_generation_pin" / "pin_audit_current.json").write_text(
        json.dumps(audit), encoding="utf-8"
    )
    required = {
        "toolchain_lock": {"exists": True},
        "temporal_mcp_pin": {"exists": True},
        "ops_doc": {"exists": True},
        "rollback_doc": {"exists": True},
        "managed_entry": {"exists": True},
    }
    for name in ("toolchain-lock.json", "temporal_mcp_pin.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "REPO", tmp_path)
    (tmp_path / "provisioning").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "provisioning" / "toolchain-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "provisioning" / "Invoke-XinaoCoordManaged.ps1").write_text("", encoding="utf-8")
    (tmp_path / "docs" / "ROLLBACK_NEGATIVE.md").write_text("", encoding="utf-8")

    result = module.check_c14({"generation_id": "coord-current"}, required)

    assert result["ok"] is True
    assert result["verdict"] == "PASS_SCOPED"
    assert result["checks"]["pin_audit"]["full_supply_chain_ok"] is False


def test_c14_incomplete_v3_true_boole_cannot_claim_full_supply_chain(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()
    monkeypatch.setattr(module, "SAT", tmp_path)
    monkeypatch.setattr(module, "CURRENT_JSON", tmp_path / "current.json")
    (tmp_path / "current.json").write_text(
        json.dumps({"generation_id": "coord-current"}), encoding="utf-8"
    )
    (tmp_path / "G10_generation_pin").mkdir()
    audit = {
        "schema_version": "xinao.c14.supply_chain.v3",
        "ok": True,
        "checks": {"only_one_forged_check": True},
        "current": {"generation_id": "coord-current"},
        "modules": [],
        "bindings": {},
    }
    (tmp_path / "G10_generation_pin" / "pin_audit_current.json").write_text(
        json.dumps(audit), encoding="utf-8"
    )
    monkeypatch.setattr(module, "REPO", tmp_path)
    (tmp_path / "provisioning").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "provisioning" / "toolchain-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "provisioning" / "Invoke-XinaoCoordManaged.ps1").write_text(
        "", encoding="utf-8"
    )
    (tmp_path / "docs" / "ROLLBACK_NEGATIVE.md").write_text("", encoding="utf-8")
    required = {
        "toolchain_lock": {"exists": True},
        "temporal_mcp_pin": {"exists": True},
        "ops_doc": {"exists": True},
        "rollback_doc": {"exists": True},
        "managed_entry": {"exists": True},
    }

    result = module.check_c14(
        {"generation_id": "coord-current", "generation_path": str(tmp_path / "generation")},
        required,
    )

    assert result["verdict"] != "PASS"
    assert result["checks"]["pin_audit"]["full_supply_chain_ok"] is False


def test_c14_binding_rejects_stale_source_hash_and_static_interface(
    tmp_path: Path,
) -> None:
    module = _module()
    source = tmp_path / "source.py"
    source.write_text("first\n", encoding="utf-8")
    binding = module.file_meta(source)

    assert module._c14_binding_matches(binding, source) is True
    assert module._c14_interface_invoked("xinao-coord doctor") is False

    source.write_text("second\n", encoding="utf-8")

    assert module._c14_binding_matches(binding, source) is False


def test_c07_incomplete_self_authored_boole_cannot_promote_scoped_canary(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()
    monkeypatch.setattr(module, "SAT", tmp_path)
    monkeypatch.setattr(module, "PEER", tmp_path / "peer")
    monkeypatch.setattr(module, "KAIGONG", tmp_path / "state")
    evidence_dir = tmp_path / "G7_amq_cli_mcp"
    evidence_dir.mkdir()
    (evidence_dir / "T6T7T8_e2e_canary.json").write_text(
        json.dumps({"ok": True, "steps": []}), encoding="utf-8"
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "S4_mbg_status_latest.json").write_text("{}", encoding="utf-8")
    full = {
        "schema_version": "xinao.c07.headless_full_evidence.v1",
        "ok": True,
        "workflow_id": "wf",
        "lane_count": 2,
        "checks": {"real_headless_lane_completed": True, "all_artifacts_match": True},
    }
    (evidence_dir / "C07_headless_full_evidence.json").write_text(
        json.dumps(full), encoding="utf-8"
    )

    result = module.check_c07()

    assert result["ok"] is True
    assert result["verdict"] == "PASS_SCOPED"
    assert result["checks"]["headless_full_evidence"]["ok"] is False


def _write_complete_c07_fixture(module, tmp_path: Path) -> Path:
    evidence_dir = tmp_path / "G7_amq_cli_mcp"
    evidence_dir.mkdir(exist_ok=True)
    (evidence_dir / "T6T7T8_e2e_canary.json").write_text(
        json.dumps({"ok": True, "steps": [{"name": "finish"}]}), encoding="utf-8"
    )
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / "S4_mbg_status_latest.json").write_text("{}", encoding="utf-8")
    source_result = tmp_path / "source_result.json"
    source_result.write_text('{"ok":true}', encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"workflow_id":"wf-exact"}', encoding="utf-8")
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("verified", encoding="utf-8")
    source_result_meta = module.file_meta(source_result)
    manifest_meta = module.file_meta(manifest)
    artifact_meta = module.file_meta(artifact)
    source_hashes = {
        name: module.file_meta(path)["sha256"]
        for name, path in module.C07_REQUIRED_SOURCES.items()
    }
    full = {
        "schema_version": "xinao.c07.headless_full_evidence.v3",
        "ok": True,
        "completion_claim_allowed": True,
        "failed_checks": [],
        "checks": {name: True for name in module.C07_REQUIRED_CHECKS},
        "source_result": str(source_result),
        "source_result_sha256": source_result_meta["sha256"],
        "source_hashes": source_hashes,
        "workflow_id": "wf-exact",
        "run_id": "run-exact",
        "lane_count": 2,
        "operation_ids": ["op-1", "op-2"],
        "file_verification": [
            {
                "path": str(artifact),
                "expected_sha256": artifact_meta["sha256"],
                "actual_sha256": artifact_meta["sha256"],
                "expected_size_bytes": artifact_meta["size_bytes"],
                "actual_size_bytes": artifact_meta["size_bytes"],
            }
        ],
        "manifest_verification": {
            "path": str(manifest),
            "exists": True,
            "hash_computed": True,
            "size_computed": True,
            "json_valid": True,
            "actual_sha256": manifest_meta["sha256"],
            "actual_size_bytes": manifest_meta["size_bytes"],
        },
        "runtime_identity": {
            "parent": {
                "expected_workflow_id": "wf-exact",
                "observed_workflow_id": "wf-exact",
                "expected_run_id": "run-exact",
                "observed_run_id": "run-exact",
                "exact_identity_match": True,
            },
            "children": [
                {
                    "expected_workflow_id": "child-exact",
                    "observed_workflow_id": "child-exact",
                    "expected_run_id": "child-run-exact",
                    "observed_run_id": "child-run-exact",
                    "exact_identity_match": True,
                }
            ],
        },
        "parent_history": {
            "requested_workflow_id": "wf-exact",
            "requested_run_id": "run-exact",
            "workflow_id": "wf-exact",
            "run_id": "run-exact",
            "exact_identity_match": True,
        },
        "no_new_worker_invocation": True,
    }
    output = evidence_dir / "C07_headless_full_evidence.json"
    output.write_text(json.dumps(full), encoding="utf-8")
    return output


def test_c07_complete_exact_v3_evidence_promotes_scoped_canary(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()
    monkeypatch.setattr(module, "SAT", tmp_path)
    monkeypatch.setattr(module, "PEER", tmp_path / "peer")
    monkeypatch.setattr(module, "KAIGONG", tmp_path / "state")
    _write_complete_c07_fixture(module, tmp_path)

    result = module.check_c07()

    assert result["ok"] is True
    assert result["verdict"] == "PASS"
    assert result["checks"]["headless_full_evidence"]["ok"] is True
    assert result["checks"]["headless_full_evidence"]["runtime_identity_bound"] is True


def test_c07_stale_source_hash_or_missing_run_identity_cannot_promote(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()
    monkeypatch.setattr(module, "SAT", tmp_path)
    monkeypatch.setattr(module, "PEER", tmp_path / "peer")
    monkeypatch.setattr(module, "KAIGONG", tmp_path / "state")
    output = _write_complete_c07_fixture(module, tmp_path)
    full = json.loads(output.read_text(encoding="utf-8"))
    full["run_id"] = ""
    full["source_hashes"][r"scripts\verify_c07_headless_evidence.py"] = "0" * 64
    output.write_text(json.dumps(full), encoding="utf-8")

    result = module.check_c07()

    assert result["ok"] is True
    assert result["verdict"] == "PASS_SCOPED"
    evidence = result["checks"]["headless_full_evidence"]
    assert evidence["source_hashes_match"] is False
    assert evidence["runtime_identity_bound"] is False


def test_c07_malformed_manifest_and_file_claims_fail_closed(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()
    monkeypatch.setattr(module, "SAT", tmp_path)
    monkeypatch.setattr(module, "PEER", tmp_path / "peer")
    monkeypatch.setattr(module, "KAIGONG", tmp_path / "state")
    output = _write_complete_c07_fixture(module, tmp_path)
    full = json.loads(output.read_text(encoding="utf-8"))
    full["manifest_verification"]["actual_size_bytes"] = {"not": "an integer"}
    full["file_verification"][0]["path"] = ""
    output.write_text(json.dumps(full), encoding="utf-8")

    result = module.check_c07()

    assert result["verdict"] == "PASS_SCOPED"
    evidence = result["checks"]["headless_full_evidence"]
    assert evidence["manifest_bound"] is False
    assert evidence["artifact_rows_bound"] is False


def test_c13_self_reported_live_boole_stay_service_scoped(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()
    monkeypatch.setattr(module, "SAT", tmp_path)
    monkeypatch.setattr(module, "PEER", tmp_path / "peer")
    monkeypatch.setattr(module, "KAIGONG", tmp_path / "state")
    g11 = tmp_path / "G11_stop_lease"
    g7 = tmp_path / "G7_amq_cli_mcp"
    g11.mkdir()
    g7.mkdir()
    (g11 / "RESULT.json").write_text(
        json.dumps({"ok": True, "exit_code": 0}), encoding="utf-8"
    )
    (g7 / "T6T7T8_e2e_canary.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    live_checks = {
        name: True
        for name in (
            "parent_reached_real_child",
            "child_running_before_stop",
            "parent_temporal_canceled",
            "child_temporal_canceled",
            "kernel_task_canceled",
            "stop_epoch_active",
            "service_cancel_all_confirmed",
            "native_cancel_terminal_confirmed",
            "fresh_process_no_revival",
            "single_parent_execution",
            "single_child_execution",
            "no_grok_activity_scheduled",
        )
    }
    (g11 / "C13_live_stop_current.json").write_text(
        json.dumps(
            {
                "schema_version": "xinao.c13.live_stop.v1",
                "ok": True,
                "checks": live_checks,
                "workflow": {
                    "parent_id": "parent",
                    "parent_status": "CANCELED",
                    "child_id": "child",
                    "child_status": "CANCELED",
                },
                "side_effects": {
                    "grok_invocations": 0,
                    "admin_invocations": 0,
                    "visible_window": False,
                    "timer_scheduler_daemon": False,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO", tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_stop_lease_deep.py").write_text("", encoding="utf-8")

    result = module.check_c13()

    assert result["ok"] is True
    assert result["verdict"] == "PASS_SERVICE"
    assert result["checks"]["live_stop"]["ok"] is False


def test_c01_requires_fresh_native_capability_and_no_window(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "KAIGONG", tmp_path)
    source = module.REPO / "scripts" / "verify_c01_native_capability.py"
    required = {
        "shortcuts_exist",
        "shortcuts_target_windows_terminal",
        "shortcut_profiles_distinct",
        "shortcut_workdirs_exist",
        "terminal_profiles_present",
        "terminal_profiles_distinct",
        "native_binaries_present",
        "all_fresh_probes_exit_zero",
        "all_fresh_probes_nonempty",
        "no_probe_timed_out",
        "no_visible_windows",
        "foreground_unchanged",
        "all_probe_roots_exited",
        "probe_processes_exited_without_window",
    }
    evidence = {
        "schema_version": "xinao.c01.native_capability.v1",
        "run_id": "c01-test",
        "ok": True,
        "completion_claim_allowed": True,
        "checks": {name: True for name in required},
        "source_hashes": {
            r"scripts\verify_c01_native_capability.py": module.file_meta(source)["sha256"]
        },
    }
    (tmp_path / "C01_native_capability_latest.json").write_text(
        json.dumps(evidence), encoding="utf-8"
    )

    result = module.check_c01(
        {
            "managed_entry": {"exists": True},
            "grok_lnk_script": {"exists": True},
            "cli": {"exists": True},
            "mcp_server": {"exists": True},
        }
    )

    assert result["verdict"] == "PASS"
    assert result["checks"]["native_capability"]["ok"] is True
