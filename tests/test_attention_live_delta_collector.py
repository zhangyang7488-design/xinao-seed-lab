from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = REPO_ROOT / "scripts" / "collect_attention_live_delta.ps1"
HOOK = REPO_ROOT / "scripts" / "predecision_intent_guard_v1.ps1"
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="pwsh not found on PATH")

SECRET_MARKERS = (
    "sk-secret",
    "sk-proj-",
    "OPENAI_API_KEY",
    "api_key=",
    "api-key=",
    "Bearer ",
    "password=",
    "secret_value",
    "BEGIN PRIVATE KEY",
    "sk-secret-must-not-leak",
)
DESKTOP_MARKERS = (
    "Users\\xx363\\Desktop",
    "Users/xx363/Desktop",
    "C:\\Users\\Public\\Desktop",
    "Desktop\\主线",
)


def _run_ps(
    script: Path,
    *,
    args: list[str] | None = None,
    stdin: str | None = None,
    timeout: float = 15.0,
) -> subprocess.CompletedProcess[str]:
    assert PWSH is not None
    cmd = [PWSH, "-NoProfile", "-File", str(script)]
    if args:
        cmd.extend(args)
    return subprocess.run(
        cmd,
        input=stdin,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture_gen8(tmp_path: Path) -> dict[str, Path]:
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text("[features]\nhooks = true\n", encoding="utf-8")
    (codex_home / "auth.json").write_text(
        '{"OPENAI_API_KEY":"sk-secret-must-not-leak","password":"secret_value"}\n',
        encoding="utf-8",
    )
    (codex_home / "hooks.json").write_text("{}\n", encoding="utf-8")

    xinao_state = tmp_path / "xinao_skill"
    release_dir = (
        xinao_state / "researcher_container" / "releases" / "researcher-1.2.2-deadbeefdeadbeef"
    )
    release_dir.mkdir(parents=True)
    release_path = release_dir / "release.json"
    _write_json(
        release_path,
        {
            "release_id": "researcher-1.2.2-deadbeefdeadbeef",
            "source_identity": {"source_commit": "b" * 40},
        },
    )
    _write_json(
        xinao_state / "researcher_container" / "current.json",
        {
            "schema_version": "xinao.researcher_current_pointer.v2",
            "generation": 8,
            "active": {
                "release_id": "researcher-1.2.2-deadbeefdeadbeef",
                "release_manifest_path": str(release_path),
            },
        },
    )

    skill_root = codex_home / "skills" / "xinao"
    (skill_root / "scripts").mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# xinao\n", encoding="utf-8")
    (skill_root / "scripts" / "xinao.py").write_text("# entry exists only\n", encoding="utf-8")

    return {
        "codex_home": codex_home,
        "xinao_state": xinao_state,
        "skill_root": skill_root,
    }


def test_gen8_fixture_invalidates_stale_uninstalled_audit(tmp_path: Path) -> None:
    fx = _fixture_gen8(tmp_path)
    result = _run_ps(
        COLLECTOR,
        args=[
            "-CodexHome",
            str(fx["codex_home"]),
            "-XinaoStateRoot",
            str(fx["xinao_state"]),
            "-InstalledSkillRoot",
            str(fx["skill_root"]),
        ],
    )
    assert result.returncode == 0, result.stderr
    text = result.stdout
    assert "SENTINEL:XINAO_ATTENTION_LIVE_DELTA_V1" in text
    assert "generation=8" in text
    assert "release_id=researcher-1.2.2-deadbeefdeadbeef" in text
    assert "source_commit=" + ("b" * 40) in text
    assert "installed_skill_entry=exists" in text
    assert "config.toml=exists" in text
    assert "auth.json=exists" in text
    assert "hooks.json=exists" in text
    # Exists is not consumer READY; script must not invent readiness claims.
    assert "READY" not in text
    assert "runtime_status=" not in text
    assert "owner_source_tip" not in text
    assert "DUPLICATE" not in text
    assert "UNIQUE_DELTA" not in text
    # Stale audit claim "not installed" is contradicted by live facts.
    assert "generation=8" in text
    assert "installed_skill_entry=exists" in text


def test_missing_paths_fail_open_without_usable_claims(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    missing_state = tmp_path / "no_xinao"
    missing_skill = codex_home / "skills" / "absent"
    result = _run_ps(
        COLLECTOR,
        args=[
            "-CodexHome",
            str(codex_home),
            "-XinaoStateRoot",
            str(missing_state),
            "-InstalledSkillRoot",
            str(missing_skill),
        ],
    )
    assert result.returncode == 0, result.stderr
    text = result.stdout
    assert "SENTINEL:XINAO_ATTENTION_LIVE_DELTA_V1" in text
    assert "current_pointer=missing" in text
    assert "installed_skill_entry=missing" in text
    assert "READY" not in text
    assert "runtime_status=" not in text


def test_no_secret_bytes_or_desktop_paths(tmp_path: Path) -> None:
    fx = _fixture_gen8(tmp_path)
    result = _run_ps(
        COLLECTOR,
        args=[
            "-CodexHome",
            str(fx["codex_home"]),
            "-XinaoStateRoot",
            str(fx["xinao_state"]),
            "-InstalledSkillRoot",
            str(fx["skill_root"]),
        ],
    )
    assert result.returncode == 0, result.stderr
    blob = result.stdout + result.stderr
    for marker in SECRET_MARKERS:
        assert marker not in blob, marker
    for marker in DESKTOP_MARKERS:
        assert marker not in blob, marker
    for path in (COLLECTOR, HOOK):
        src = path.read_text(encoding="utf-8")
        for marker in DESKTOP_MARKERS:
            assert marker not in src, f"{path.name}:{marker}"
        # No absolute human-report path binding in source.
        assert "主线" not in src


def test_hook_fail_open_injects_delta_or_unavailable_and_stays_fast() -> None:
    started = time.perf_counter()
    result = _run_ps(
        HOOK,
        stdin=json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-live-delta-thin",
                "prompt": "继续",
            }
        ),
        timeout=20.0,
    )
    elapsed = time.perf_counter() - started
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["continue"] is True
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "XINAO_PREDECISION_INTENT_GUARD_V1" in context
    assert "XINAO_GLOBAL_ATTENTION_RECONSIDERATION_V1" in context
    assert "XINAO_ATTENTION_LIVE_DELTA_V1" in context or "LIVE_DELTA_UNAVAILABLE" in context
    assert "continue = $true" in HOOK.read_text(encoding="utf-8") or output["continue"] is True
    # Reasonable local budget; not a fragile microbenchmark.
    assert elapsed < 5.0, f"fresh hook took {elapsed:.3f}s"
    for marker in SECRET_MARKERS + DESKTOP_MARKERS:
        assert marker not in context


def test_hook_missing_collector_marker_is_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Static contract: missing collector path yields LIVE_DELTA_UNAVAILABLE without blocking.
    hook_text = HOOK.read_text(encoding="utf-8")
    assert "LIVE_DELTA_UNAVAILABLE:collector_missing" in hook_text
    assert "Get-AttentionLiveDeltaContext" in hook_text
    assert "continue = $true" in hook_text
