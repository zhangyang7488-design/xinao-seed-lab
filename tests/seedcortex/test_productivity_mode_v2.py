import json
import os
import subprocess
import sys
from pathlib import Path

from xinao_seedlab.application.seed_cortex import build_default_service


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_productivity_mode_v2_service_writes_invokable_wave(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    service = build_default_service(runtime, repo_root=repo)

    payload = service.productivity_mode_v2_wave(
        task_id="productivity_mode_v2_codex_surfaces_20260703",
        wave_id="productivity-mode-v2-test-wave",
        objective="deliver a callable productivity v2 lane/fan-in surface",
        write_runtime=True,
    )

    assert payload["schema_version"] == "xinao.meta_rsi_wave.v1"
    assert payload["mode"] == "productivity_v2"
    assert payload["validation"]["passed"] is True
    assert payload["adoption_state"] == "candidate_registered"
    assert payload["runtime_enforced"] is False
    assert payload["completion_claim_allowed"] is False
    assert len(payload["lanes"]) >= 6
    assert payload["fan_in"]["accepted_result_count"] >= 1
    assert payload["fan_in"]["report_only_stop"] is False
    assert payload["front_injection"]["kernel_id"] == "productivity_meta_kernel_v1"
    assert "少解释，少盘点" in payload["front_injection"]["front_injection_text_zh"]
    assert "Codex 自检前置" in payload["front_injection"]["codex_self_prelude_text_zh"]
    assert payload["validation"]["checks"]["front_injection_present"] is True
    assert payload["validation"]["checks"]["codex_self_prelude_present"] is True
    assert payload["WORKER_ASSIGNMENT"]["scope_level_target"] == "L3"
    assert payload["WORKER_ASSIGNMENT"]["completion_claim_allowed"] is False
    assert "codex_self_prelude" in payload["WORKER_ASSIGNMENT"]["can_invoke_now"]
    assert payload["productivity_baseline"]["had_code_diff"] is True
    assert payload["productivity_baseline"]["had_invoke"] is True
    assert payload["productivity_baseline"]["task_id"] == (
        "productivity_mode_v2_codex_surfaces_20260703"
    )
    assert payload["can_invoke_now"]["python_service"] == (
        "SeedCortexService.productivity_mode_v2_wave(...)"
    )
    assert "productivity-mode-v2-wave" in payload["can_invoke_now"]["cli"]

    latest = Path(payload["output_paths"]["runtime_latest"])
    task_latest = Path(payload["output_paths"]["runtime_task_latest"])
    worker_assignment = Path(payload["output_paths"]["worker_assignment"])
    meta_kernel_latest = Path(payload["output_paths"]["productivity_meta_kernel_latest"])
    front_injection_prompt = Path(payload["output_paths"]["front_injection_prompt"])
    codex_self_prelude = Path(payload["output_paths"]["codex_self_prelude"])
    baseline_latest = Path(payload["output_paths"]["productivity_baseline_latest"])
    baseline_task_latest = Path(payload["output_paths"]["productivity_baseline_task_latest"])
    readback = Path(payload["output_paths"]["runtime_readback_zh"])
    assert latest.is_file()
    assert task_latest.is_file()
    assert worker_assignment.is_file()
    assert meta_kernel_latest.is_file()
    assert front_injection_prompt.is_file()
    assert codex_self_prelude.is_file()
    assert baseline_latest.is_file()
    assert baseline_task_latest.is_file()
    assert readback.is_file()
    assert _read_json(latest)["wave_id"] == "productivity-mode-v2-test-wave"
    assert _read_json(worker_assignment)["status"] == "worker_assignment_ready"
    assert _read_json(meta_kernel_latest)["kernel_id"] == "productivity_meta_kernel_v1"
    assert "少解释，少盘点" in front_injection_prompt.read_text(encoding="utf-8")
    assert "Codex 自检前置" in codex_self_prelude.read_text(encoding="utf-8")
    assert _read_json(baseline_latest)["had_invoke"] is True
    readback_text = readback.read_text(encoding="utf-8")
    assert "现在能 invoke 什么" in readback_text
    assert "candidate_registered" in readback_text
    assert "WORKER_ASSIGNMENT" in readback_text
    assert "Codex 自检前置" in readback_text
    assert "CodexProductivityBaseline" in readback_text


def test_productivity_mode_v2_cli_invokes_service(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo_root = Path(__file__).resolve().parents[2]
    task_id = "productivity_mode_v2_cli_test"
    wave_id = "productivity-mode-v2-cli-wave"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src") + os.pathsep + str(repo_root)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "xinao_seedlab.cli.__main__",
            "--runtime-root",
            str(runtime),
            "--repo-root",
            str(repo_root),
            "productivity-mode-v2-wave",
            "--task-id",
            task_id,
            "--wave-id",
            wave_id,
        ],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["task_id"] == task_id
    assert payload["wave_id"] == wave_id
    assert payload["validation"]["passed"] is True
    assert payload["completion_claim_allowed"] is False
    assert payload["productivity_baseline"]["had_code_diff"] is True
    assert payload["productivity_baseline"]["had_invoke"] is True
    assert Path(payload["output_paths"]["worker_assignment"]).is_file()
    assert Path(payload["output_paths"]["front_injection_prompt"]).is_file()
    assert Path(payload["output_paths"]["codex_self_prelude"]).is_file()
    assert Path(payload["output_paths"]["productivity_baseline_latest"]).is_file()
    assert Path(payload["output_paths"]["runtime_latest"]).is_file()
    assert Path(payload["output_paths"]["runtime_readback_zh"]).is_file()


def test_default_trigger_candidate_invokes_productivity_mode_v2(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    service = build_default_service(runtime, repo_root=repo)

    payload = service.default_main_loop_trigger_candidate(
        anchor_package_root=r"C:\Users\xx363\Desktop\新系统",
        wave_id="default-trigger-productivity-v2-test",
        task_id="productivity_mode_v2_default_trigger_test",
        write_runtime=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["productivity_mode_v2_wave"]["invoked"] is True
    assert payload["productivity_mode_v2_wave"]["adoption_state"] == "candidate_registered"
    assert payload["productivity_mode_v2_wave"]["runtime_enforced"] is False
    assert payload["productivity_mode_v2_trigger_binding"]["runtime_enforced"] is True
    assert payload["productivity_mode_v2_trigger_binding"]["runtime_enforced_scope"] == (
        "default_main_loop_trigger_candidate_service_invocation_only"
    )
    assert payload["productivity_mode_v2_trigger_binding"]["productivity_wave_runtime_enforced"] is False
    assert payload["validation"]["checks"]["productivity_v2_meta_wave_not_overpromoted"] is True

    refs = payload["productivity_mode_v2_trigger_binding"]["evidence_refs"]
    assert Path(refs["binding_latest"]).is_file()
    assert Path(refs["meta_rsi_wave_latest"]).is_file()
    assert Path(refs["worker_assignment"]).is_file()
    assert Path(refs["productivity_baseline"]).is_file()
    assert Path(refs["readback_zh"]).is_file()

    binding = _read_json(Path(refs["binding_latest"]))
    assert binding["validation"]["passed"] is True
    assert binding["invoked_by"] == "SeedCortexService.default_main_loop_trigger_candidate"
