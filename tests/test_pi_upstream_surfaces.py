from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "infra" / "pi_upstream_dual_entry" / "v1"
STATE_ROOT = Path("D:/XINAO_RESEARCH_RUNTIME/state/pi/0.84.1")
FAMILY_ISLAND = Path("E:/XINAO_RESEARCH_WORKSPACES/pi-local-cognition-contract-island")
PRIME_B_ISLAND = Path("E:/XINAO_RESEARCH_WORKSPACES/prime-agent-local-cognition-island")
PRIME_S_ISLAND = Path("E:/XINAO_RESEARCH_WORKSPACES/prime-s-local-cognition-island")
MAIN_CODEX = Path("C:/Users/xx363/.codex")
ACCOUNT_B_CODEX = Path("C:/Users/xx363/.codex-s-hardmode-account-b")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pi_surface_source_models_stable_leading_not_task_identities() -> None:
    common = _text(SOURCE_ROOT / "scripts" / "PiDualEntry.Common.ps1")
    start = _text(SOURCE_ROOT / "scripts" / "Start-UpstreamPi.ps1")
    readme = _text(SOURCE_ROOT / "README.md")
    initializer = _text(SOURCE_ROOT / "scripts" / "Initialize-UpstreamPiProfiles.ps1")
    installer = _text(SOURCE_ROOT / "scripts" / "Install-UpstreamPiCapabilities.ps1")
    cross_repo = _text(SOURCE_ROOT / "scripts" / "Test-PiCrossRepositoryContext.ps1")

    assert "$script:PiDualEntryVersion = '0.84.1'" in common
    assert "$script:PiDualEntryMinimumNodeVersion = [version]'22.19.0'" in common
    assert "ValidateSet('prime-b','prime-s')" in common
    assert "Role = 'minimum-usable'" in common
    assert "Role = 'primary'" in common
    assert "[string[]]$Profile = @('prime-s')" in initializer
    assert "[string[]]$Profile = @('prime-s')" in installer
    assert "[string[]]$Profile = @('prime-s')" in cross_repo
    assert "profiles\\$Profile\\account-binding.json" in common
    assert "Get-PiDualEntrySpec -Profile $profileName" in initializer
    assert "$spec.OverlayAgentDir" in initializer
    assert (
        SOURCE_ROOT
        / "surface-overlays"
        / "prime-s"
        / "agents"
        / "body-friction-auditor.md"
    ).is_file()
    assert "agents\\evolution" not in initializer
    assert "研究新澳和改进 Pi 自身" in readme
    assert "不是角色、profile 或 session 类型" in readme
    assert "prime S 是否可用和成熟由它自己的 fresh 消费者决定" in readme
    assert "不追求与 prime S 对称优化" in readme
    assert "不能用“能启动”代替" in readme
    assert "same conversation" not in readme.lower()
    assert "prime-agent.cmd" not in start.lower()
    assert "--append-system-prompt" in start
    assert "--continue" in start
    assert "PI_PROFILE_AUTH_NOT_READY_AFTER_RESEED" in start
    assert "Seed-PiCodexAuth.ps1') -Profile $Profile -Force" in start
    assert start.index("$env:PI_CODING_AGENT_DIR = $spec.AgentDir") < start.index(
        "if (-not (Test-SelectedPiAuthReady))"
    )
    assert "$spec.Packages" in installer
    assert "$matrix" not in installer
    assert "--no-session --tools read" in cross_repo
    assert "SENTINEL:XINAO_NATIVE_RESEARCH_ROLE_V2" in cross_repo
    assert "SENTINEL:XINAO_CURRENT_PROJECTION_V7" in cross_repo


def test_prime_agent_0_7_harness_is_explicitly_cold_history() -> None:
    retired = REPO_ROOT / "infra" / "retired_prime_agent_0_7_parity_test" / "v1"
    readme = _text(retired / "README.md")
    assert "PRIME_AGENT_0_7_PARITY_RETIRED_V1" in readme
    assert "cold migration and rollback evidence only" in readme
    assert not (REPO_ROOT / "infra" / "prime_codex_parity_test").exists()


def test_pi_selective_promotion_excludes_identity_and_session_state() -> None:
    promote = _text(SOURCE_ROOT / "scripts" / "Invoke-PiSelectivePromotion.ps1")
    rollback = _text(SOURCE_ROOT / "scripts" / "Restore-PiSelectivePromotion.ps1")
    for text in (promote, rollback):
        assert "^(agents|contract)" in text
        assert "destination" in text.lower()
        assert "Get-FileHash -Algorithm SHA256" in text
        assert "Test-UpstreamPiDualEntry.ps1" in text
    assert "candidate_acceptance_sha256" in promote
    assert "preimage" in promote
    assert "excluded_roots" in promote
    assert "whole profile" in promote
    assert "PI_PROMOTION_ROLLBACK_CURRENT_HASH_MISMATCH" in rollback
    assert "-RunLiveModelProbe" in promote and "-RunLiveModelProbe" in rollback


def test_pi_child_acceptance_reads_native_profile_session_root() -> None:
    rpc = _text(SOURCE_ROOT / "scripts" / "Test-PiSubagentRpc.mjs")
    assert "findCompletedChild(sessionDir" in rpc
    assert "visit(sessionRoot, 0)" in rpc
    assert "child_sessions_under_profile_root: true" in rpc
    assert 'startsWith(normalizedSessionRoot)' in rpc
    assert 'pi-subagent-session-' not in rpc


@pytest.mark.skipif(not STATE_ROOT.exists(), reason="local Pi surface runtime is not present")
def test_live_pi_profiles_are_isolated_and_exa_is_not_installed() -> None:
    manifests: dict[str, dict[str, object]] = {}
    for profile in ("prime-b", "prime-s"):
        root = STATE_ROOT / "profiles" / profile
        settings = json.loads(_text(root / "settings.json"))
        subagent_config = json.loads(_text(root / "extensions" / "subagent" / "config.json"))
        binding = json.loads(_text(root / "account-binding.json"))
        manifests[profile] = {
            "session": settings["sessionDir"],
            "binding": binding["active_slot"],
            "packages": settings.get("packages", []),
        }
        assert all("exa" not in str(package).lower() for package in settings.get("packages", []))
        assert subagent_config["artifactDir"] == "session"
        assert subagent_config["missions"]["enabled"] is False
        assert subagent_config["scheduledRuns"]["enabled"] is False
        assert "artifactDir" not in settings["subagents"]
        projection = _text(root / "PI_CONTRACT.md")
        assert "PI_LOCAL_COGNITION_CONTRACT_ISLAND_V1" in projection

    assert manifests["prime-b"]["binding"] == "account-b"
    assert manifests["prime-s"]["binding"] == "main"
    assert manifests["prime-b"]["session"] != manifests["prime-s"]["session"]
    assert manifests["prime-b"]["packages"] == ["npm:pi-subagents@0.43.0"]
    assert manifests["prime-s"]["packages"] == [
        "npm:pi-subagents@0.43.0",
        "npm:pi-autoresearch@1.6.2",
    ]


@pytest.mark.skipif(not FAMILY_ISLAND.exists(), reason="local Pi contract islands are not present")
def test_pi_contract_islands_keep_body_knowledge_outside_codex_and_s() -> None:
    family = _text(FAMILY_ISLAND / "AGENTS.md")
    prime_b = _text(PRIME_B_ISLAND / "AGENTS.md")
    prime_s = _text(PRIME_S_ISLAND / "AGENTS.md")

    assert "PI_LOCAL_COGNITION_CONTRACT_ISLAND_V1" in family
    assert "PI_SURFACE_PRIME_B_V3" in prime_b
    assert "PI_SURFACE_PRIME_S_V1" in prime_s
    assert "研究 session" in family and "进化 session" in family
    assert "prime S" in family and "PrimeB" in family
    assert "选择性晋升" in family
    assert "需要你：否" in family
    assert "不得恢复" in prime_b
    assert "不是“Evolution Pi”" in prime_s
    assert not (PRIME_B_ISLAND / "contracts" / "IDENTITY_AND_TRUST.md").exists()
    assert not (PRIME_B_ISLAND / "contracts" / "USER_RULES_AND_COMPLETION.md").exists()
    assert not (PRIME_B_ISLAND / "scripts" / "Start-Prime-Local-Cognition.ps1").exists()
    retired = _text(
        PRIME_B_ISLAND
        / "contracts"
        / "evidence"
        / "prime-agent-0.7.0-pre-upgrade-20260808"
        / "RETIRED.md"
    )
    assert "PRIME_AGENT_0_7_ISLAND_EPOCH_RETIRED_V1" in retired
    assert not str(FAMILY_ISLAND).lower().startswith(str(REPO_ROOT).lower())
    assert not str(FAMILY_ISLAND).lower().startswith(str(MAIN_CODEX).lower())


@pytest.mark.skipif(
    not (MAIN_CODEX / "AGENTS.md").exists() or not (ACCOUNT_B_CODEX / "AGENTS.md").exists(),
    reason="canonical Codex behavior projections are not present",
)
def test_both_pi_surfaces_share_the_same_canonical_behavior_and_general_skills() -> None:
    assert _sha256(MAIN_CODEX / "AGENTS.md") == _sha256(ACCOUNT_B_CODEX / "AGENTS.md")
    assert (MAIN_CODEX / "skills" / "dispatch-grok-worker-pool" / "SKILL.md").is_file()
    assert (MAIN_CODEX / "skills" / "research-external-reality" / "SKILL.md").is_file()
    test_script = _text(SOURCE_ROOT / "scripts" / "Test-UpstreamPiDualEntry.ps1")
    assert "skill:dispatch-grok-worker-pool" in test_script
    assert "skill:research-external-reality" in test_script
    assert "open_external_query_is_seed_not_automatic_boundary=true" in test_script
    assert "external_findings_must_collide_with_live_local_baseline=true" in test_script
    assert "exact_or_explicitly_narrow_lookup_stays_bounded=true" in test_script
