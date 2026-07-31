"""WAVE124A: long ResearchEpisode vertical production package attacks.

Prior break closed by public `ensure-pair` Owner consumer. Fresh-process CLI
coverage + negatives for: hidden outcome, self-scheduling/leg-B, unauthorized
write roots, stale checkpoint/CAS, cancel/resume. No live provider call.
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
SKILL_ROOT = ROOT / "skills" / "xinao"
RUNTIME_PATH = SKILL_ROOT / "scripts" / "xinao_runtime.py"
BOOTSTRAP_PATH = SKILL_ROOT / "scripts" / "xinao.py"


def _load(name: str, path: Path) -> Any:
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def module() -> Any:
    return _load("xinao_runtime_wave124a_vertical", RUNTIME_PATH)


def _seed_receipt(
    module: Any,
    *,
    release: dict[str, Any],
    transport_image_id: str,
    tool_image_id: str,
) -> None:
    from tests.test_xinao_dual_image_namespace import _seed_canonical_receipt

    _seed_canonical_receipt(
        module,
        release=release,
        transport_image_id=transport_image_id,
        tool_image_id=tool_image_id,
    )


def _prepare_episode(
    module: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_receipt: bool = True,
    dual_synthetic: bool = True,
) -> tuple[Any, Path, dict[str, Any], dict[str, Any]]:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module,
        tmp_path,
        monkeypatch,
        package_version="1.3.6",
        capability_version="1.2.2",
    )
    skill_tests._terminal_pointer(module, manifest, path)
    if with_receipt:
        _seed_receipt(
            module,
            release=manifest,
            transport_image_id=manifest["image_id"],
            tool_image_id=manifest["tool_image_id"],
        )
    if dual_synthetic:
        monkeypatch.setenv("XINAO_DUAL_CONTAINER_SYNTHETIC", "1")
        monkeypatch.setenv("XINAO_AUTH_HOST_PATH", str(tmp_path / "auth.json"))
        (tmp_path / "auth.json").write_text("{}", encoding="utf-8")
    # Prefer D-like root (not C:).
    episode = tmp_path / "D_episode" / "ep1"
    started = module.research_episode_start(
        root=episode, question="bounded multi-round open research"
    )
    return module, episode, started, manifest


def test_public_cli_exposes_ensure_and_retire_pair() -> None:
    # Candidate source runtime is the public Skill entry after Owner build/activate.
    # Ordinary `xinao.py` help binds the *live sealed release* runtime until adoption.
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(RUNTIME_PATH), "research-episode", "--help"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0
    assert "ensure-pair" in text
    assert "retire-pair" in text
    # Companion seal must track candidate runtime bytes (bootstrap-migrate/forward path).
    expected = hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest()
    bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    assert expected in bootstrap
    runtime_src = RUNTIME_PATH.read_text(encoding="utf-8")
    assert '"ensure-pair"' in runtime_src
    assert '"retire-pair"' in runtime_src
    assert "research_episode_ensure_pair" in runtime_src
    assert "research_episode_retire_pair" in runtime_src


def test_capabilities_registry_lists_ensure_pair(module: Any) -> None:
    caps = json.loads(
        (SKILL_ROOT / "references" / "capabilities.v1.json").read_text(encoding="utf-8")
    )
    episode = next(c for c in caps["capabilities"] if c["capability_id"] == "research-episode")
    assert episode["version"] == "0.1.3"
    assert "ensure-pair" in episode["skill_verbs"]
    assert "retire-pair" in episode["skill_verbs"]
    assert episode["auto_next_task"] is False
    assert episode["candidate_only"] is True
    assert episode["completion_claim_allowed"] is False


def test_ensure_pair_requires_namespace_receipt(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(
        module, tmp_path, monkeypatch, with_receipt=False
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_ensure_pair(
            root=episode,
            expected_head_sha256=started["head_checkpoint_sha256"],
        )
    assert failure.value.reason_code == "RESEARCH_EPISODE_NAMESPACE_UNVERIFIED"


def test_ensure_pair_stale_cas_rejected(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_ensure_pair(
            root=episode,
            expected_head_sha256="0" * 64,
        )
    assert failure.value.reason_code == "RESEARCH_EPISODE_STALE_HEAD"
    # Honest checkpoint then ensure under new head.
    ckpt = module.research_episode_checkpoint(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
        progress_note="failed shell experiment retained",
        lab_relative="experiments/fail1.txt",
        lab_bytes=b"experiment failed: exit 1\n",
    )
    assert (
        (episode / "lab" / "experiments" / "fail1.txt")
        .read_bytes()
        .startswith(b"experiment failed")
    )
    assert ckpt["completion_claim_allowed"] is False
    ready = module.research_episode_ensure_pair(
        root=episode,
        expected_head_sha256=ckpt["head_checkpoint_sha256"],
    )
    assert ready["status"] in {"PAIR_READY", "PAIR_ALREADY_READY", "PAIR_STARTED"}
    assert ready["next_task_created"] is False
    assert ready["leg_b_scheduled"] is False
    assert ready["successor_episode_created"] is False
    assert ready["outcome_written"] is False
    assert ready["freeze_written"] is False
    assert ready["settlement_written"] is False
    assert ready["completion_claim_allowed"] is False
    assert ready["owner_adopted"] is False
    assert ready["parent_complete"] is False
    # Intermediate failure retained after pair ensure.
    assert (episode / "lab" / "experiments" / "fail1.txt").is_file()


def test_unauthorized_lab_roots_and_hidden_outcome_isolation(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    for bad in (
        "shadow/ledger.json",
        "freeze/ticket.json",
        "outcome/reveal.json",
        "settlement/row.json",
        "../outside.txt",
        "auth/secret.json",
    ):
        with pytest.raises(module.XinaoError) as failure:
            module.research_episode_checkpoint(
                root=episode,
                expected_head_sha256=started["head_checkpoint_sha256"],
                progress_note="attack",
                lab_relative=bad,
                lab_bytes=b"x",
            )
        assert failure.value.reason_code in {
            "RESEARCH_EPISODE_UNAUTHORIZED_LEDGER_PATH",
            "RESEARCH_EPISODE_LAB_PATH_INVALID",
        }
    # ensure-pair must not create hidden outcome/settlement files under episode.
    ready = module.research_episode_ensure_pair(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
    )
    assert ready["outcome_written"] is False
    for forbidden in ("outcome", "settlement", "freeze", "shadow"):
        assert not (episode / forbidden).exists()
    # Container contract advertises forbidden mounts when dual host identity used.
    contract = module._research_episode_container_identity(
        verb="ensure-pair",
        episode_id=started["episode_id"],
        session_id=started["session_id"],
        generation=1,
        lab_root=episode / "lab",
        root=episode,
    )
    forbidden = set(contract.get("forbidden_mounts") or [])
    assert (
        "outcome_store" in forbidden
        or contract.get("driver") == "mock_host_side_until_sibling_container"
    )
    if contract.get("driver") == "dual_container_host":
        assert "outcome_store" in forbidden
        assert "shadow_ledger" in forbidden
        assert contract.get("temporal_leg_b") is False
        assert contract.get("daemon") is False


def test_self_scheduling_and_leg_b_flags_false_on_public_verbs(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    ready = module.research_episode_ensure_pair(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
    )
    for payload in (started, ready):
        assert payload.get("next_task_created", False) is False
        assert payload.get("leg_b_scheduled", False) is False
        assert payload.get("successor_episode_created", False) is False
        assert payload.get("completion_claim_allowed") is False
    # Cancel must not schedule successor; must best-effort retire pair.
    cancelled = module.research_episode_cancel(root=episode)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["next_task_created"] is False
    assert cancelled["leg_b_scheduled"] is False
    assert cancelled["successor_episode_created"] is False
    assert cancelled["completion_claim_allowed"] is False
    assert "pair_retire" in cancelled
    # Resume after cancel is blocked.
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_resume(
            root=episode,
            expected_head_sha256=cancelled["head_checkpoint_sha256"],
        )
    assert failure.value.reason_code == "RESEARCH_EPISODE_CANCELLED"
    # ensure-pair after cancel is terminal.
    with pytest.raises(module.XinaoError) as failure2:
        module.research_episode_ensure_pair(
            root=episode,
            expected_head_sha256=cancelled["head_checkpoint_sha256"],
        )
    assert failure2.value.reason_code == "RESEARCH_EPISODE_TERMINAL"
    # Idempotent cancel.
    again = module.research_episode_cancel(root=episode)
    assert again["status"] == "CANCEL_IDEMPOTENT"


def test_cancel_resume_checkpoint_cas_chain(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    head1 = started["head_checkpoint_sha256"]
    ckpt = module.research_episode_checkpoint(
        root=episode,
        expected_head_sha256=head1,
        progress_note="round-1 notes",
        mark_interrupted=True,
    )
    assert ckpt["status"] == "INTERRUPTED_CHECKPOINT"
    # Stale resume against old head.
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_resume(root=episode, expected_head_sha256=head1)
    assert failure.value.reason_code == "RESEARCH_EPISODE_STALE_HEAD"
    resumed = module.research_episode_resume(
        root=episode,
        expected_head_sha256=ckpt["head_checkpoint_sha256"],
        expected_session_id=started["session_id"],
    )
    assert resumed["status"] == "RESUMED"
    assert resumed["exact_session_bound"] is True
    # Foreign session rejected.
    with pytest.raises(module.XinaoError) as failure2:
        module.research_episode_resume(
            root=episode,
            expected_head_sha256=resumed["head_checkpoint_sha256"],
            expected_session_id="xrsess_foreign",
        )
    assert failure2.value.reason_code == "RESEARCH_EPISODE_FOREIGN_SESSION"
    # C: root forbidden.
    with pytest.raises(module.XinaoError) as failure3:
        module.research_episode_start(root=Path(r"C:\xinao_episode_forbidden"), question="q")
    assert failure3.value.reason_code == "RESEARCH_EPISODE_ROOT_C_DRIVE_FORBIDDEN"


def test_fresh_process_ensure_pair_cli(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    env = {
        **dict(**{k: v for k, v in __import__("os").environ.items()}),
        "XINAO_SKILL_STATE_ROOT": str(tmp_path / "state"),
        "XINAO_RESEARCHER_RUN_ROOT": str(tmp_path / "runs"),
        "XINAO_DUAL_CONTAINER_SYNTHETIC": "1",
        "XINAO_AUTH_HOST_PATH": str(tmp_path / "auth.json"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # State was prepared inside the loaded module fixture; re-point env to same tmp state.
    # The module fixture already wrote under monkeypatched XINAO_SKILL_STATE_ROOT.
    # Capture actual state root used by module.
    state_root = module._state_paths()["capability_root"].parent
    env["XINAO_SKILL_STATE_ROOT"] = str(state_root)
    auth = tmp_path / "auth.json"
    if not auth.is_file():
        auth.write_text("{}", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(RUNTIME_PATH),
            "research-episode",
            "ensure-pair",
            "--root",
            str(episode),
            "--expected-head",
            started["head_checkpoint_sha256"],
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["status"] in {"PAIR_READY", "PAIR_ALREADY_READY", "PAIR_STARTED"}
    assert payload["completion_claim_allowed"] is False
    assert payload["next_task_created"] is False
    assert payload["leg_b_scheduled"] is False
    assert payload["successor_episode_created"] is False
    assert payload["outcome_written"] is False
    # Retire via fresh process.
    retired = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(RUNTIME_PATH),
            "research-episode",
            "retire-pair",
            "--root",
            str(episode),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
    )
    assert retired.returncode == 0, retired.stdout + retired.stderr
    retire_payload = json.loads(retired.stdout.strip().splitlines()[-1])
    assert retire_payload["next_task_created"] is False
    assert retire_payload["leg_b_scheduled"] is False
    assert retire_payload["successor_episode_created"] is False


def test_attach_run_without_pair_fails_closed(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    # attach-run without ensure-pair → lease missing (or synthetic live refused).
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_attach_run(
            root=episode,
            prompt="attempt without pair",
            expected_head_sha256=started["head_checkpoint_sha256"],
            plan_only=False,
        )
    assert failure.value.reason_code in {
        "DUAL_HOST_LEASE_MISSING",
        "DUAL_HOST_SYNTHETIC_LIVE_REFUSED",
        "RESEARCH_EPISODE_ATTACH_FAILED",
        "DUAL_CONTAINER_HOST_CONFIG_REQUIRED",
        "DUAL_CONTAINER_SEALED_IMAGES_REQUIRED",
    }
    ready = module.research_episode_ensure_pair(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
    )
    assert ready["status"] in {"PAIR_READY", "PAIR_ALREADY_READY", "PAIR_STARTED"}
    # Synthetic dual host is for pair/CAS plumbing only; live attach still refuse synthetic
    # (no provider theater). Production live attach requires real dual containers.
    with pytest.raises(module.XinaoError) as failure2:
        module.research_episode_attach_run(
            root=episode,
            prompt="plan only multi-turn",
            expected_head_sha256=started["head_checkpoint_sha256"],
            max_turns=16,
            plan_only=True,
        )
    assert failure2.value.reason_code in {
        "DUAL_HOST_SYNTHETIC_LIVE_REFUSED",
        "RESEARCH_EPISODE_ATTACH_FAILED",
    }
    # Stale CAS on attach after checkpoint drift.
    ckpt = module.research_episode_checkpoint(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
        progress_note="post-pair note",
    )
    with pytest.raises(module.XinaoError) as failure3:
        module.research_episode_attach_run(
            root=episode,
            prompt="stale head",
            expected_head_sha256=started["head_checkpoint_sha256"],
            plan_only=True,
        )
    assert failure3.value.reason_code == "RESEARCH_EPISODE_STALE_HEAD"
    assert ckpt["completion_claim_allowed"] is False
