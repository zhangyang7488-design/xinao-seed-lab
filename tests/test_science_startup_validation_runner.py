from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import verify_science_startup_validation as subject
from scripts.build_s_runtime_release import build_release
from services.agent_runtime.grok_build_docker_worker import (
    PROVIDER_ID,
    READ_ONLY_PERMISSION_MODE,
    READ_ONLY_SANDBOX_PROFILE,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    expected_docker_grok_backend_models,
)
from xinao.science import (
    canonical_world_measurement_bindings,
    verify_science_episode_admission_file,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()


def test_materialized_startup_episode_uses_the_canonical_five_world_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = subject.load_science_active_parent()
    materials = subject._materialize_validation_episode(
        tmp_path,
        active_parent_sha256=str(parent["active_parent"]["sha256"]),
        background_contract_sha256=str(parent["background_contract"]["sha256"]),
    )
    world = json.loads(materials["world_path"].read_text(encoding="utf-8"))
    assert world["bindings"] == canonical_world_measurement_bindings(
        background_contract_sha256=str(parent["background_contract"]["sha256"])
    )
    admission = verify_science_episode_admission_file(
        materials["protocol_pin_path"],
        expected_file_sha256=_sha256(materials["protocol_pin_path"]),
        expected_active_parent_sha256=str(parent["active_parent"]["sha256"]),
    )
    assert admission["allowed"] is True
    assert admission["claim_intent"] == "STARTUP_VALIDATION"
    assert admission["pre_registration_claim_allowed"] is False
    pin = json.loads(materials["protocol_pin_path"].read_text(encoding="utf-8"))
    assert pin["startup_validation_contract"]["target_kind"] == "RUNTIME_CANARY_EVENT"
    monkeypatch.setattr(
        subject,
        "_host_to_container",
        lambda path: f"/evidence/test/{Path(path).name}",
    )
    initial = subject._science_initial(
        materials,
        code_git_sha="a" * 40,
        model="grok-4.5",
    )
    assert initial["model"] == "grok-4.5"
    assert "active_parent_projection_ref" not in initial
    assert "active_parent_sha256" not in initial
    assert "instrument_output_root" not in initial
    assert "bus_state" not in initial


def test_startup_verifier_binds_exact_release_and_read_only_app_mounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    releases = tmp_path / "releases"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "release-test@local")
    _git(repo, "config", "user.name", "Release Test")
    for relative in subject.SOURCE_RELEASE_CRITICAL_FILES:
        path = repo.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n", encoding="utf-8")
    for relative in subject.RELEASE_APP_MOUNTS.values():
        path = repo.joinpath(*relative.split("/"))
        if "." in path.name:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
            (path / ".release-fixture").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "release fixture")
    commit = _git(repo, "rev-parse", "HEAD")
    built = build_release(repo, releases, commit)
    release_dir = Path(str(built["release_dir"]))
    manifest_path = releases / f"{commit}.release-manifest.json"
    monkeypatch.setattr(subject, "REPO", release_dir)

    identity = subject._expected_source_release(
        release_dir=release_dir,
        manifest_path=manifest_path,
        git_repo=repo,
        code_git_sha=commit,
    )
    assert identity["commit"] == commit
    mounts = [
        {
            "source": str(release_dir.joinpath(*relative.split("/"))),
            "destination": destination,
            "rw": False,
        }
        for destination, relative in subject.RELEASE_APP_MOUNTS.items()
    ]
    verified = subject._verify_container_release_mounts(
        {"mounts": mounts},
        release_dir=release_dir,
    )
    assert verified["mount_count"] == len(subject.RELEASE_APP_MOUNTS)

    mounts[0]["source"] = str(repo / "AGENTS.md")
    with pytest.raises(RuntimeError, match="not from the selected release"):
        subject._verify_container_release_mounts(
            {"mounts": mounts},
            release_dir=release_dir,
        )


def test_no_retained_pre_cutover_history_is_explicitly_not_applicable() -> None:
    result = asyncio.run(subject._retained_legacy_history_replay([]))
    assert result["status"] == "NOT_APPLICABLE_NO_RETAINED_PRE_CUTOVER_HISTORY"
    assert result["production_history_claim_allowed"] is False


def _accepted_worker_result(runtime_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    expected_root = runtime_root / "projects" / "episode" / ("a" * 64)
    expected_root.mkdir(parents=True)
    fields: dict[str, str] = {}
    for name in (
        "receipt",
        "checkpoint",
        "output",
        "logical_contract",
        "attempt_receipt",
        "fanin_manifest",
    ):
        path = expected_root / f"{name}.json"
        path.write_text(json.dumps({"artifact": name}), encoding="utf-8")
        fields[f"{name}_ref"] = "/evidence/" + path.relative_to(runtime_root).as_posix()
        fields[f"{name}_sha256"] = _sha256(path)
    required_checks = {
        "fanin_ok": True,
        "provider_exact": True,
        "model_identity_ok": True,
        "provider_invoked": True,
        "model_invoked": True,
        "one_accepted_invocation": True,
        "terminal_completed": True,
        "cross_seam_receipt": True,
        "sandboxed_no_tools": True,
        "capabilities_disabled": True,
        "bound_output": True,
        "non_grok_invocations_zero": True,
    }
    worker: dict[str, object] = {
        "status": "WORKER_TERMINAL_ACCEPTED",
        "run_root": "/evidence/" + expected_root.relative_to(runtime_root).as_posix(),
        "selected_provider": PROVIDER_ID,
        "requested_model": "grok-4.5",
        "observed_model": expected_docker_grok_backend_models("grok-4.5")[0],
        "model_identity_ok": True,
        "sandbox_profile": READ_ONLY_SANDBOX_PROFILE,
        "permission_mode": READ_ONLY_PERMISSION_MODE,
        "security_cli_args": [
            "--sandbox",
            READ_ONLY_SANDBOX_PROFILE,
            "--permission-mode",
            READ_ONLY_PERMISSION_MODE,
            "--tools",
            "",
        ],
        "terminal_state": "completed",
        "stop_reason": "endturn",
        "usage": {
            "invocation_count": 1,
            "total_tokens": 100,
            "accepted_tokens": 100,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
        "worker_checks": required_checks,
        "science_trial_appends": 0,
        "outcome_accessed": False,
        "research_progress_claim_allowed": False,
        "completion_claim_allowed": False,
        "legacy_parent_scope_consumed": False,
        **fields,
    }
    return {"science_startup_worker_receipt": worker}, {"output_root": expected_root}


def test_positive_worker_receipt_requires_identity_usage_and_bound_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subject, "RUNTIME", tmp_path)
    result, materials = _accepted_worker_result(tmp_path)
    accepted = subject._verify_positive_worker_receipt(
        result,
        materials=materials,
        expected_model="grok-4.5",
    )
    assert accepted["identity_ok"] is True
    assert accepted["usage_ok"] is True
    assert set(accepted["artifacts"]) == {
        "receipt",
        "checkpoint",
        "output",
        "logical_contract",
        "attempt_receipt",
        "fanin_manifest",
    }


def test_positive_worker_receipt_rejects_zero_token_false_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subject, "RUNTIME", tmp_path)
    result, materials = _accepted_worker_result(tmp_path)
    worker = result["science_startup_worker_receipt"]
    assert isinstance(worker, dict)
    worker["usage"] = {
        "invocation_count": 0,
        "total_tokens": 0,
        "accepted_tokens": 0,
        "cancelled_tokens": 0,
        "failed_tokens": 0,
    }
    with pytest.raises(AssertionError, match="identity, usage"):
        subject._verify_positive_worker_receipt(
            result,
            materials=materials,
            expected_model="grok-4.5",
        )


def test_cleanup_rpc_timeout_is_bounded_when_cancel_stalls() -> None:
    class NeverCancels:
        async def describe(self) -> SimpleNamespace:
            return SimpleNamespace(status=subject.WorkflowExecutionStatus.RUNNING)

        async def cancel(self) -> None:
            await asyncio.Event().wait()

        async def result(self) -> None:
            await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        asyncio.run(
            subject._cancel_and_verify_terminal(
                NeverCancels(),
                "stalled-negative",
                rpc_timeout=0.01,
            )
        )
