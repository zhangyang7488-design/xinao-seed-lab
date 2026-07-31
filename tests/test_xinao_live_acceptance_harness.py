"""Fakes-only control-flow tests for Owner live-acceptance harness.

No live Docker engine required for the default suite. No live model, activation,
shadow ledger, or role-fitness claims. Exact host commands are asserted present
for Codex's later real run.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "skills" / "xinao" / "scripts" / "live_acceptance_harness.py"
PKG = ROOT / "docker" / "xinao-researcher"
SEALED_CANARY_SHA256 = "c9c1a132ac00ebde9b198db6eb12a1be456cbcfb8c66d892856997595e40c47e"


def _load() -> Any:
    name = "xinao_live_acceptance_harness_under_test"
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # dual_container_host sibling import path
    scripts = str(HARNESS_PATH.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness_mod() -> Any:
    return _load()


def test_canary_entrypoint_byte_identity_preserved() -> None:
    digest = hashlib.sha256((PKG / "entrypoint.py").read_bytes()).hexdigest()
    assert digest == SEALED_CANARY_SHA256


def test_synthetic_harness_all_control_axes_partial_ok(harness_mod: Any, tmp_path: Path) -> None:
    cfg = harness_mod.HarnessConfig(
        work_root=tmp_path / "work",
        repo_root=ROOT,
        mode="synthetic",
        synthetic_docker=True,
        canary_static_only=True,
        invoke_live_model=False,
    )
    harness = harness_mod.LiveAcceptanceHarness(cfg)
    result = harness.run()
    assert result["schema_version"] == harness_mod.HARNESS_SCHEMA
    assert result["completion_claim_allowed"] is False
    assert result["daemon"] is False
    assert result["live_model_invoked"] is False
    assert result["activation_performed"] is False
    assert result["shadow_ledger_touched"] is False
    assert result["instrument_canary_preserved"] is True
    assert result["role_fitness_claimed"] is False
    assert result["status"] == "HARNESS_PARTIAL_OK"
    axes = result["axes"]
    for name in harness_mod.AXIS_ORDER:
        assert name in axes
        assert axes[name]["status"] == "passed", name
    # Capability remains non-role-fitness even when control flow is green.
    assert result["genuine_scientist_status"] in {
        harness_mod.CAPABILITY_PARTIAL,
        harness_mod.CAPABILITY_UNAVAILABLE,
    }
    assert result["genuine_scientist_status"] != "AVAILABLE"
    assert "terminal_candidate_sha256" in result["export_hashes"]
    assert "canary_entrypoint_sha256" in result["export_hashes"]
    assert result["export_hashes"]["canary_entrypoint_sha256"] == SEALED_CANARY_SHA256
    assert (tmp_path / "work" / "harness_result.json").is_file()
    assert (tmp_path / "work" / "immutable_export.json").is_file()
    assert (tmp_path / "work" / "candidate_build_lock.json").is_file()


def test_plan_mode_emits_exact_host_commands(harness_mod: Any, tmp_path: Path) -> None:
    cfg = harness_mod.HarnessConfig(work_root=tmp_path / "plan", mode="plan")
    result = harness_mod.LiveAcceptanceHarness(cfg).run()
    assert result["status"] == "PLAN_ONLY"
    commands = result["exact_host_commands"]
    assert isinstance(commands, list) and len(commands) >= 5
    joined = json.dumps(commands)
    assert "docker build" in joined
    assert "live_acceptance_harness" in joined
    assert "INSTRUMENT_CANARY" in joined or "instrument canary" in joined.lower()
    assert "research-episode" in joined
    assert result["rollback"]["completion_claim_allowed"] is False


def test_failed_pointer_marks_capability_unavailable(harness_mod: Any, tmp_path: Path) -> None:
    # Live mode without pointer path fails pointer axis.
    cfg = harness_mod.HarnessConfig(
        work_root=tmp_path / "live-fail",
        repo_root=ROOT,
        mode="live",
        synthetic_docker=True,  # still fake docker for this unit seat
        pointer_path=tmp_path / "missing_pointer.json",
        canary_static_only=True,
        invoke_live_model=False,
    )
    result = harness_mod.LiveAcceptanceHarness(cfg).run()
    assert result["axes"]["pointer_identity"]["status"] == "failed"
    assert result["genuine_scientist_status"] == harness_mod.CAPABILITY_UNAVAILABLE
    assert result["role_fitness_claimed"] is False
    assert result["completion_claim_allowed"] is False


def test_invoke_live_model_forbidden_in_harness_seat(harness_mod: Any, tmp_path: Path) -> None:
    cfg = harness_mod.HarnessConfig(
        work_root=tmp_path / "model-forbid",
        repo_root=ROOT,
        mode="synthetic",
        invoke_live_model=True,
    )
    result = harness_mod.LiveAcceptanceHarness(cfg).run()
    assert result["axes"]["multi_turn_fail_revise_success"]["status"] == "failed"
    assert (
        result["axes"]["multi_turn_fail_revise_success"]["reason_code"]
        == "LIVE_MODEL_FORBIDDEN_IN_HARNESS_SEAT"
    )
    assert result["genuine_scientist_status"] == harness_mod.CAPABILITY_UNAVAILABLE


def test_lab_fail_revise_success_events(harness_mod: Any, tmp_path: Path) -> None:
    cfg = harness_mod.HarnessConfig(
        work_root=tmp_path / "lab",
        repo_root=ROOT,
        mode="synthetic",
    )
    harness = harness_mod.LiveAcceptanceHarness(cfg)
    lab = tmp_path / "lab" / "episode" / "lab"
    out = harness._run_lab_fail_revise_success(lab)
    assert out["fail_then_revise"] is True
    assert out["success"] is True
    assert out["live_model"] is False
    kinds = [e["kind"] for e in out["events"]]
    assert kinds.count("experiment") >= 2
    assert "revision" in kinds
    assert (tmp_path / "lab" / "output" / "terminal_candidate.json").is_file()


def test_non_reachability_negatives_standalone(harness_mod: Any, tmp_path: Path) -> None:
    cfg = harness_mod.HarnessConfig(
        work_root=tmp_path / "neg",
        repo_root=ROOT,
        mode="synthetic",
    )
    harness = harness_mod.LiveAcceptanceHarness(cfg)
    axis = harness.axis_non_reachability_negatives()
    assert axis.status == "passed"
    case_ids = {c["case_id"] for c in axis.evidence["cases"]}
    assert "tool_rejects_auth_mount" in case_ids
    assert "tool_rejects_docker_socket" in case_ids
    assert "tool_rejects_ledger" in case_ids
    assert "tool_rejects_shadow" in case_ids
    assert "tool_rejects_bridge_network" in case_ids
    assert axis.evidence["live_kernel_namespace_proof"] is False


def test_canary_sha_mismatch_fails_axis(harness_mod: Any, tmp_path: Path) -> None:
    cfg = harness_mod.HarnessConfig(
        work_root=tmp_path / "sha",
        repo_root=ROOT,
        mode="synthetic",
        expected_canary_sha256="0" * 64,
    )
    result = harness_mod.LiveAcceptanceHarness(cfg).run()
    assert result["axes"]["canary_identity"]["status"] == "failed"
    assert result["axes"]["canary_identity"]["reason_code"] == "CANARY_ENTRYPOINT_SHA_MISMATCH"
    assert result["genuine_scientist_status"] == harness_mod.CAPABILITY_UNAVAILABLE


def test_cli_run_synthetic_exit_zero(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HARNESS_PATH),
            "run-synthetic",
            "--work-root",
            str(tmp_path / "cli"),
            "--repo-root",
            str(ROOT),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "HARNESS_PARTIAL_OK"
    assert payload["completion_claim_allowed"] is False


def test_cli_plan_lists_rollback(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HARNESS_PATH),
            "plan",
            "--work-root",
            str(tmp_path / "cli-plan"),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "PLAN_ONLY"
    assert "Unset dual-host" in " ".join(payload["rollback"]["steps"])
    titles = [
        str(step.get("title", ""))
        for step in payload["exact_host_commands"]
        if isinstance(step, dict)
    ]
    assert any("\u2192" in title for title in titles)


def test_emit_json_stdout_survives_cp1252_text_console(harness_mod: Any) -> None:
    """Windows console cp1252 must not break Unicode JSON emission."""
    import io

    payload = {
        "status": "PLAN_ONLY",
        "title": "Interrupt \u2192 remove attempt containers \u2192 fresh-process resume",
        "completion_claim_allowed": False,
    }
    buffer = io.BytesIO()
    text = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict", line_buffering=True)
    original = sys.stdout
    try:
        sys.stdout = text
        harness_mod._emit_json_stdout(payload)
        text.flush()
    finally:
        sys.stdout = original
        try:
            text.detach()
        except Exception:
            pass
    raw = buffer.getvalue()
    assert raw.endswith(b"\n")
    decoded = json.loads(raw.decode("utf-8"))
    assert decoded["title"] == payload["title"]
    assert "\u2192" in decoded["title"]
    assert b"\xe2\x86\x92" in raw


def test_no_daemon_or_temporal_in_harness_source() -> None:
    text = HARNESS_PATH.read_text(encoding="utf-8")
    assert "from temporal" not in text.lower()
    assert "temporalio" not in text.lower()
    assert "APScheduler" not in text
    assert "no daemon" in text.lower() or "non-daemon" in text.lower()
    assert "shadow ledger" in text.lower() or "shadow_ledger" in text


def test_build_lock_tree_stable(harness_mod: Any, tmp_path: Path) -> None:
    cfg = harness_mod.HarnessConfig(work_root=tmp_path / "lock", repo_root=ROOT, mode="synthetic")
    h1 = harness_mod.LiveAcceptanceHarness(cfg)
    lock1 = h1.compute_candidate_build_lock()
    lock2 = harness_mod.LiveAcceptanceHarness(cfg).compute_candidate_build_lock()
    assert (
        lock1["researcher_image_modules_tree_sha256"]
        == lock2["researcher_image_modules_tree_sha256"]
    )
    assert len(lock1["modules"]) == len(harness_mod.RESEARCHER_IMAGE_MODULE_INVENTORY)
