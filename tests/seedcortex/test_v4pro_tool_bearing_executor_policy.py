import json
from pathlib import Path

from services.agent_runtime import v4pro_tool_bearing_executor_policy as policy


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_v4pro_policy_requires_hardmode_shortcut_and_closure_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {
            "provider_registry": {
                "providers": [
                    {
                        "provider_id": "deepseek_v4_pro",
                        "status": "ready",
                        "deepseek_v4_pro_main_worker_eligible": True,
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        policy,
        "shortcut_target",
        lambda path: {
            "exists": True,
            "path": str(path),
            "TargetPath": "wt.exe",
            "Arguments": '-w new -p "XINAO DeepSeek V4 Pro S Hardmode"',
            "WorkingDirectory": str(repo),
            "Description": "hardmode",
        },
    )
    monkeypatch.setattr(policy, "git_clean", lambda repo: True)

    payload = policy.build_policy(
        runtime_root=runtime,
        repo_root=repo,
        shortcut_path=tmp_path / "OPEN DEEPSEEK V4 PRO S HARDMODE.lnk",
        write=True,
        write_aaq=False,
    )

    assert payload["tool_bearing_executor_eligible"] is True
    assert payload["repo_mutation_allowed"] is True
    assert payload["commit_push_allowed"] is True
    assert payload["v4pro_self_acceptance_allowed"] is False
    assert payload["final_acceptance_owner"] == "codex_or_deterministic_verifier"
    assert {"commit_hash", "push_target", "git_clean_status"}.issubset(
        set(payload["closure_evidence_bundle_required"])
    )
    assert (runtime / "state" / "v4pro_tool_bearing_executor_policy" / "latest.json").is_file()


def test_v4pro_policy_blocks_without_tool_surface(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {"provider_registry": {"providers": [{"provider_id": "deepseek_v4_pro"}]}},
    )
    monkeypatch.setattr(
        policy,
        "shortcut_target",
        lambda path: {"exists": False, "path": str(path)},
    )
    monkeypatch.setattr(policy, "git_clean", lambda repo: True)

    payload = policy.build_policy(
        runtime_root=runtime,
        repo_root=repo,
        shortcut_path=tmp_path / "missing.lnk",
        write=False,
        write_aaq=False,
    )

    assert payload["tool_bearing_executor_eligible"] is False
    assert payload["named_blocker"] == "V4PRO_TOOL_BEARING_EXECUTOR_POLICY_NOT_BOUND"
