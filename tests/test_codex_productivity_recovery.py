from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECOVERY_ROOT = REPO_ROOT / "infra" / "codex_productivity_recovery" / "v1"
MANIFEST = RECOVERY_ROOT / "manifest.v1.json"
ARCHIVE = RECOVERY_ROOT / "codex-productivity-recovery.v1.zip"
SCRIPT = REPO_ROOT / "scripts" / "build_codex_productivity_recovery.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_productivity_recovery_archive_is_cold_self_contained_and_science_free(
    tmp_path: Path,
) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "xinao.codex_productivity_recovery.v1"
    assert manifest["authority"] is False
    assert manifest["runtime_loaded"] is False
    assert manifest["completion_claim_allowed"] is False
    assert manifest["archive_sha256"] == _sha256(ARCHIVE)
    assert manifest["entry_count"] == len(manifest["entries"])
    assert manifest["source_and_projection"] == {
        "main_home_is_live_source": True,
        "account_b_is_generated_projection": True,
        "cold_archive_is_immutable_recovery_media_not_a_second_runtime_truth": True,
    }
    assert manifest["science_boundary"]["restore_into_s_or_global_generic_router"] is False
    assert manifest["science_boundary"]["retired_science_routing_remains_retired"] is True

    names = {entry["archive_path"] for entry in manifest["entries"]}
    assert "main-home/AGENTS.md" in names
    assert "main-home/hooks.json" in names
    assert "main-home/config.toml" in names
    assert "main-home/skills/repair-agent-behavior/SKILL.md" in names
    assert "main-home/skills/operate-for-user/SKILL.md" in names
    assert "main-home/skills/productivity/SKILL.md" in names
    assert "main-home/skills/productivity/references/protocol.md" in names
    assert "main-home/skills/productivity/references/skill-ecology.md" in names
    assert "runtime/Codex_Situation_Island/scripts/user_prompt_zero_beat_v1.ps1" in names
    serialized_names = "\n".join(names).lower()
    for forbidden in (
        "conduct-xinao-native-research",
        "pretool_task_provenance_guard_v1.ps1",
        "auth.json",
        "/sessions/",
        "/memories/",
    ):
        assert forbidden not in serialized_names

    verified = subprocess.run(
        [sys.executable, str(SCRIPT), "verify-archive"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert verified.returncode == 0, verified.stderr

    restore_root = tmp_path / "restored"
    restored = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "restore-to",
            "--target",
            str(restore_root),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert restored.returncode == 0, restored.stderr
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert set(archive.namelist()) == names
    for entry in manifest["entries"]:
        restored_path = restore_root / Path(*entry["archive_path"].split("/"))
        assert restored_path.is_file()
        assert _sha256(restored_path) == entry["sha256"]


def test_live_productivity_projection_matches_cold_recovery_media_when_installed() -> None:
    live_sources = [
        Path(r"C:\Users\xx363\.codex\AGENTS.md"),
        Path(r"C:\Users\xx363\.codex-s-hardmode-account-b\AGENTS.md"),
        Path(
            r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island"
            r"\scripts\user_prompt_zero_beat_v1.ps1"
        ),
    ]
    if not all(path.is_file() for path in live_sources):
        return
    verified = subprocess.run(
        [sys.executable, str(SCRIPT), "verify-live"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
