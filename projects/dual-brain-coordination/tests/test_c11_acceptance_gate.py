from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_c01_c15.py"
    spec = importlib.util.spec_from_file_location("verify_c01_c15_c11_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_c11_readonly_independence.py"
    spec = importlib.util.spec_from_file_location("verify_c11_readonly_runtime_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daemon_startup_record_does_not_expire_as_a_fake_heartbeat() -> None:
    module = _runtime_module()
    daemon = {
        "status": "polling",
        "graph_id": "xinao-integrated-bus-v2",
        "workflows_registered": ["XinaoIntegratedBusWorkflow"],
        "generated_at": "2000-01-01T00:00:00+00:00",
    }

    assert module._daemon_binding_ready(daemon) is True
    assert module._daemon_binding_ready({**daemon, "graph_id": "wrong"}) is False


def test_c11_zero_exit_code_is_a_success_not_a_falsy_fallback(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    state = tmp_path / "state"
    sat = tmp_path / "sat"
    (sat / "G6_s0s8_index").mkdir(parents=True)
    state.mkdir()
    (state / "S3_readonly_board_current.json").write_text(
        json.dumps(
            {
                "schema_version": "xinao.s3.readback_snapshot.v1",
                "mode": "strict_read_only",
                "all_named_sources_visible": True,
            }
        ),
        encoding="utf-8",
    )
    (state / "C11_readback_index_current.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    sources = {
        name: module.file_meta(path)["sha256"]
        for name, path in {
            r"scripts\_s3_ssot_read_adapter.py": module.REPO / "scripts" / "_s3_ssot_read_adapter.py",
            r"scripts\verify_c11_readonly_independence.py": module.REPO
            / "scripts"
            / "verify_c11_readonly_independence.py",
            r"scripts\verify_c01_native_capability.py": module.REPO
            / "scripts"
            / "verify_c01_native_capability.py",
            r"scripts\verify_temporal_kernel_convergence.py": module.REPO
            / "scripts"
            / "verify_temporal_kernel_convergence.py",
        }.items()
    }
    required_checks = {
        "strict_reader_schema",
        "strict_reader_mode",
        "all_named_sources_visible_and_hashed",
        "fresh_kernel_counts_match_reader",
        "fresh_process_adapter_exit_zero",
        "fresh_process_closed_after_read",
        "database_unchanged_by_reader",
        "external_observer_no_window",
        "external_observer_no_focus",
        "external_observer_exited",
        "canonical_daemon_ready_after_reader_exit",
        "canonical_queue_pollers_fresh_after_reader_exit",
        "last_verified_main_route_sources_current",
        "last_verified_main_route_temporal_completed",
        "last_verified_main_route_d_artifact_hashed",
        "grok_admin_remained_paused_during_readiness_probe",
        "worker_runner_binding_visible",
        "fresh_board_and_index_written",
        "sources_stable_during_run",
    }
    artifact = tmp_path / "artifact.json"
    artifact.write_text("evidence", encoding="utf-8")
    artifact_hash = module.file_meta(artifact)["sha256"]
    evidence = {
        "schema_version": "xinao.c11.readonly_independence.v3",
        "ok": True,
        "checks": {name: True for name in required_checks},
        "source_hashes_start": sources,
        "source_hashes_end": sources,
        "main_route_before_after": {
            "canonical_daemon_ready_after_reader_exit": True,
            "canonical_queue_pollers_fresh_after_reader_exit": True,
            "terminal": True,
            "status": "COMPLETED",
            "workflow_id": "wf-test",
            "run_id": "run-test",
            "artifact_path": str(artifact),
            "artifact_sha256": artifact_hash,
            "artifact_expected_sha256": artifact_hash,
        },
        "observer_evidence": {
            "pid": 123,
            "exit_code": 0,
            "process_exited": True,
            "foreground_unchanged": True,
            "visible_window_count": 0,
        },
        "post_reader_daemon": {
            "status": "polling",
            "graph_id": "xinao-integrated-bus-v2",
        },
        "post_reader_queue_snapshot": {
            "workflow": {"pollers": [{"identity": "worker"}]},
            "activity": {"pollers": [{"identity": "worker"}]},
        },
        "worker_runner_binding": {
            "path": str(artifact),
            "sha256": artifact_hash,
        },
    }
    (state / "C11_readonly_independence_latest.json").write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(module, "KAIGONG", state)
    monkeypatch.setattr(module, "SAT", sat)

    result = module.check_c11()

    assert result["verdict"] == "PASS"
    assert result["checks"]["readonly_independence"]["observer_effects_verified"] is True
