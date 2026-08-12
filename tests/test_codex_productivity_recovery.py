from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECOVERY_ROOT = REPO_ROOT / "infra" / "codex_productivity_recovery"
LEGACY_ROOT = RECOVERY_ROOT / "v1"
LEGACY_MANIFEST = LEGACY_ROOT / "manifest.v1.json"
LEGACY_ARCHIVE = LEGACY_ROOT / "codex-productivity-recovery.v1.zip"
LEGACY_ARCHIVE_SHA256 = "f083dd04186859d528083047d862558b1ee308ff3059da5bf20083767984a96d"

RECOVERY_ROOT_V2 = RECOVERY_ROOT / "v2"
MANIFEST = RECOVERY_ROOT_V2 / "manifest.v2.json"
ARCHIVE = RECOVERY_ROOT_V2 / "codex-productivity-recovery.non-pi.v2.zip"
SCRIPT = REPO_ROOT / "scripts" / "build_codex_productivity_recovery.py"
EXCLUDED_PRODUCT_SKILL = "steward-pis-evolution"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_builder(action: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), action, *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_legacy_v1_recovery_media_remains_byte_frozen() -> None:
    manifest = json.loads(LEGACY_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "xinao.codex_productivity_recovery.v1"
    assert manifest["archive_sha256"] == LEGACY_ARCHIVE_SHA256
    assert _sha256(LEGACY_ARCHIVE) == LEGACY_ARCHIVE_SHA256


def test_non_pi_v2_recovery_archive_is_scoped_and_self_contained(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["archive_sha256"] == _sha256(ARCHIVE)
    installed_verified = _run_builder("verify-archive")
    assert installed_verified.returncode == 0, installed_verified.stderr
    package_root = RECOVERY_ROOT_V2
    package_archive = ARCHIVE
    assert manifest["archive_sha256"] == _sha256(package_archive)
    verified = _run_builder("verify-archive", "--output-root", str(package_root))
    assert verified.returncode == 0, verified.stderr
    assert manifest["schema_version"] == "xinao.codex_productivity_recovery.v2"
    assert manifest["sentinel"] == "SENTINEL:CODEX_NON_PI_PRODUCTIVITY_RECOVERY_COLD_V2"
    assert manifest["authority"] is False
    assert manifest["runtime_loaded"] is False
    assert manifest["completion_claim_allowed"] is False
    assert manifest["effect_scope"] == {
        "id": "codex_non_pi_productivity_runtime",
        "self_contained": True,
        "excluded_product_skill_trees": [EXCLUDED_PRODUCT_SKILL],
        "excluded_trees_are_not_read_verified_or_restored": True,
    }
    assert manifest["archive_sha256"] == _sha256(package_archive)
    assert manifest["entry_count"] == len(manifest["entries"])
    assert manifest["source_and_projection"] == {
        "main_home_is_canonical_shared_runtime_source": True,
        "account_b_credential_home_links_to_shared_runtime": True,
        "account_b_is_not_a_configuration_or_recovery_source": True,
        "desktop_s_and_b_are_one_s_body_with_two_account_slots": True,
        "desktop_a_and_c_are_one_separate_cleanroom_body_with_two_account_slots": True,
        "s_b_and_a_c_bodies_must_not_cross": True,
        "cleanroom_body_is_external_to_this_s_recovery_payload": True,
        "cold_archive_is_immutable_recovery_media_not_a_second_runtime_truth": True,
        "legacy_v1_is_separate_history_not_a_build_input": True,
        "grok_worker_pool_live_manifest_is_the_runtime_truth": True,
        "local_docker_is_exception_only_not_a_default_runtime_dependency": True,
        "dated_worker_pool_recovery_snapshots_are_not_current_sources": True,
        "live_continuation_locator_is_not_a_recovery_source": True,
    }
    assert manifest["recovery_contract"]["legacy_v1_must_not_be_refreshed_or_used_as_a_source"]

    names = {entry["archive_path"] for entry in manifest["entries"]}
    assert "main-home/AGENTS.md" in names
    assert "main-home/hooks.json" in names
    assert "main-home/config.toml" in names
    assert "main-home/native-collaboration.config.toml" in names
    assert "launchers/Open-Codex-S-SharedRuntime.ps1" in names
    assert "contracts/CODEX_SHARED_RUNTIME_ACCOUNT_SLOTS_CURRENT.md" in names
    assert "contracts/CODEX_ACCOUNT_SLOT_TOPOLOGY_CURRENT.md" in names
    assert "contracts/CODEX_GROK_WORKER_POOL_OPERATOR.md" in names
    assert "contracts/CODEX_GROK_WORKER_POOL_DEFAULT.md" not in names
    assert "launchers/Invoke-Codex-GrokWorkerPool.ps1" in names
    assert "launchers/Invoke-GrokWorkerOAuthRecovery.ps1" in names
    assert "runtime/grok-worker-pool/runtime-manifest.v1.json" in names
    grok_bridge_names = {
        name for name in names if name.startswith("runtime/grok-worker-pool/bridge/")
    }
    assert len(grok_bridge_names) == 15
    assert "runtime/grok-worker-pool/bridge/GrokSupervisorRootCapability.ps1" in grok_bridge_names
    assert "main-home/skills/repair-agent-behavior/SKILL.md" in names
    assert "main-home/skills/operate-for-user/SKILL.md" in names
    assert "main-home/skills/productivity/SKILL.md" in names
    assert "main-home/skills/productivity/references/protocol.md" in names
    assert "main-home/skills/productivity/references/skill-ecology.md" in names
    assert "main-home/skills/research-external-reality/SKILL.md" in names
    assert "main-home/skills/research-external-reality/agents/openai.yaml" in names
    assert "main-home/skills/research-external-reality/references/evaluation-cases.md" in names
    assert "runtime/Codex_Situation_Island/scripts/user_prompt_zero_beat_v1.ps1" in names
    situation_runtime_roles = {
        "repository/services/agent_runtime/runtime_observation.py": "situation_runtime_source",
        "repository/services/agent_runtime/current_situation.py": "situation_runtime_source",
        "repository/services/agent_runtime/context_fabric.py": "context_fabric_runtime_source",
        "repository/services/agent_runtime/codex_situation_hook.py": "situation_hook_adapter",
        "repository/scripts/codex_situation_context_hook.py": "situation_hook_adapter",
        "repository/scripts/manage_current_situation.py": "explicit_situation_manager",
        "repository/scripts/manage_context_fabric.py": "explicit_context_fabric_manager",
        "repository/scripts/Protect-SContextFabricState.ps1": "context_fabric_acl_installer",
        "contracts/CODEX_SITUATION_CONTEXT_PRODUCTION.md": "situation_context_contract",
        "contracts/S_CONTEXT_FABRIC_CURRENT.md": "context_fabric_contract",
    }
    assert situation_runtime_roles.keys() <= names
    assert (
        "runtime/Codex_Situation_Island/scripts/"
        "manage_explicit_continuation_locator_v1.ps1" in names
    )
    assert "human-entries/00_先读我_主线入口与读取顺序.txt" in names
    roles = {entry["archive_path"]: entry["role"] for entry in manifest["entries"]}
    assert roles["runtime/Codex_Situation_Island/README.md"] == "situation_island_contract"
    assert (
        roles["runtime/grok-worker-pool/runtime-manifest.v1.json"]
        == "grok_worker_pool_runtime_manifest"
    )
    assert {roles[name] for name in grok_bridge_names} == {"grok_worker_pool_sealed_transport"}
    assert (
        roles["runtime/Codex_Situation_Island/scripts/user_prompt_zero_beat_v1.ps1"]
        == "cold_previous_user_prompt_hook"
    )
    assert {name: roles[name] for name in situation_runtime_roles} == situation_runtime_roles
    assert (
        roles["runtime/Codex_Situation_Island/scripts/manage_explicit_continuation_locator_v1.ps1"]
        == "on_demand_explicit_continuation_consumer"
    )
    assert roles["human-entries/00_先读我_主线入口与读取顺序.txt"] == "stable_human_reentry_entry"
    for cold_script in (
        "bind_active_task_continuation_v1.ps1",
        "restore_parent_task_continuation_v1.ps1",
        "session_start_continuity_pointer_v1.ps1",
        "turn_finalization_gate_v1.ps1",
    ):
        assert (
            roles[f"runtime/Codex_Situation_Island/scripts/{cold_script}"]
            == "cold_continuity_repair_material"
        )
    excluded_prefix = f"main-home/skills/{EXCLUDED_PRODUCT_SKILL}/"
    assert not any(name.startswith(excluded_prefix) for name in names)
    assert not any(
        f"\\skills\\{EXCLUDED_PRODUCT_SKILL}\\" in entry["live_source"].lower()
        or f"/skills/{EXCLUDED_PRODUCT_SKILL}/" in entry["live_source"].lower()
        for entry in manifest["entries"]
    )
    serialized_names = "\n".join(names).lower()
    for forbidden in (
        "conduct-xinao-native-research",
        "pretool_task_provenance_guard_v1.ps1",
        "auth.json",
        "/sessions/",
        "/memories/",
        ".grok-bg-workers",
        "explicit_continuation_locator.v1.json",
        "/runs/continue_prior_issues_20260811/",
    ):
        assert forbidden not in serialized_names

    verified = _run_builder("verify-archive", "--output-root", str(package_root))
    assert verified.returncode == 0, verified.stderr

    restore_root = tmp_path / "restored"
    restored = _run_builder(
        "restore-to",
        "--output-root",
        str(package_root),
        "--target",
        str(restore_root),
    )
    assert restored.returncode == 0, restored.stderr
    with zipfile.ZipFile(package_archive) as archive:
        assert set(archive.namelist()) == names
        agents_text = archive.read("main-home/AGENTS.md").decode("utf-8")
        assert "SENTINEL:LOCAL_DOCKER_EXCEPTION_ONLY_V1" in agents_text
        assert "SENTINEL:ROLE_SEPARATED_CONTROL_TOWER_V1" in agents_text
        assert "已经被任命为 world-owning Sol 的 branch 自己面对领域现实" in agents_text
        assert "SENTINEL:OWNER_DIRECT_GROK_DEFAULT_DUAL_TRACK_V1" not in agents_text
        amplify_text = archive.read("main-home/skills/amplify-supervisor-worker/SKILL.md").decode(
            "utf-8"
        )
        assert "Operate S as a cognition control tower" in amplify_text
        assert "Use fresh late fusion without manufacturing consensus" in amplify_text
        assert "advances the inseparable main line" not in amplify_text
        operator_text = archive.read("contracts/CODEX_GROK_WORKER_POOL_OPERATOR.md").decode("utf-8")
        assert "daemon 未启动是正常状态" in operator_text
        assert "普通 Grok 是可分离正收益劳动的默认" in operator_text
        assert "world-owning Sol 的研究不因该入口存在" in operator_text
        assert "默认 cognition 路线" in operator_text
        launcher_text = archive.read("launchers/Invoke-Codex-GrokWorkerPool.ps1").decode("utf-8")
        assert "New-CodexGrokTemporaryWorktree" in launcher_text
        worker_text = archive.read(
            "runtime/grok-worker-pool/bridge/Invoke-GrokComposer25Worker.ps1"
        ).decode("utf-8")
        assert "GROK_DOCKER_EXCEPTION_OPT_IN_REQUIRED" in worker_text
    for entry in manifest["entries"]:
        restored_path = restore_root / Path(*entry["archive_path"].split("/"))
        assert restored_path.is_file()
        assert _sha256(restored_path) == entry["sha256"]


def test_non_pi_v2_recovery_archive_rebuild_is_reproducible_when_live_sources_are_installed(
    tmp_path: Path,
) -> None:
    installed_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    live_sources = [Path(str(entry["live_source"])) for entry in installed_manifest["entries"]]
    if not all(path.is_file() for path in live_sources):
        pytest.skip("live non-Pi recovery sources are not installed on this consumer")

    candidate_root = tmp_path / "candidate-v2"
    built = _run_builder("build", "--output-root", str(candidate_root))
    assert built.returncode == 0, built.stderr
    verified = _run_builder("verify-archive", "--output-root", str(candidate_root))
    assert verified.returncode == 0, verified.stderr
    candidate_manifest = json.loads(
        (candidate_root / "manifest.v2.json").read_text(encoding="utf-8")
    )

    rebuilt_root = tmp_path / "rebuilt-v2"
    rebuilt = _run_builder("build", "--output-root", str(rebuilt_root))
    assert rebuilt.returncode == 0, rebuilt.stderr
    rebuilt_manifest = json.loads((rebuilt_root / "manifest.v2.json").read_text(encoding="utf-8"))
    assert candidate_manifest["archive_sha256"] == installed_manifest["archive_sha256"]
    assert rebuilt_manifest["archive_sha256"] == candidate_manifest["archive_sha256"]

    def portable_entries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return [{key: value for key, value in row.items() if key != "live_source"} for row in rows]

    assert portable_entries(candidate_manifest["entries"]) == portable_entries(
        installed_manifest["entries"]
    )
    assert portable_entries(rebuilt_manifest["entries"]) == portable_entries(
        candidate_manifest["entries"]
    )


def test_builder_refuses_to_refresh_legacy_v1_media() -> None:
    before_manifest = _sha256(LEGACY_MANIFEST)
    before_archive = _sha256(LEGACY_ARCHIVE)
    blocked = _run_builder("build", "--output-root", str(LEGACY_ROOT))
    assert blocked.returncode != 0
    assert "legacy v1 recovery media is immutable" in blocked.stderr
    assert _sha256(LEGACY_MANIFEST) == before_manifest
    assert _sha256(LEGACY_ARCHIVE) == before_archive


def test_live_non_pi_productivity_projection_matches_v2_recovery_media_when_installed() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    live_sources = [Path(str(entry["live_source"])) for entry in manifest["entries"]]
    if not all(path.is_file() for path in live_sources):
        return
    verified = _run_builder("verify-live")
    assert verified.returncode == 0, verified.stderr
