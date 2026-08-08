from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "infra" / "pi_upstream_dual_entry" / "v1"
STATE_ROOT = Path("D:/XINAO_RESEARCH_RUNTIME/state/pi/0.84.1")
FAMILY_ISLAND = Path("E:/XINAO_RESEARCH_WORKSPACES/pi-local-cognition-contract-island")
PRIME_B_ISLAND = Path("E:/XINAO_RESEARCH_WORKSPACES/prime-agent-local-cognition-island")
PRIME_S_ISLAND = Path("E:/XINAO_RESEARCH_WORKSPACES/prime-s-local-cognition-island")
MAIN_CODEX = Path("C:/Users/xx363/.codex")
ACCOUNT_B_CODEX = Path("C:/Users/xx363/.codex-s-hardmode-account-b")
WINDOWS_POWERSHELL = (
    Path(os.environ.get("WINDIR", "C:/Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frontmatter_description(path: Path) -> str:
    lines = _text(path).splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("description:"))
    head = lines[start].split(":", 1)[1].strip()
    if head not in {">", ">-", "|", "|-"}:
        return head.strip("\"'")
    parts: list[str] = []
    for line in lines[start + 1 :]:
        if line == "---" or (line and not line[0].isspace()):
            break
        if line.strip():
            parts.append(line.strip())
    return " ".join(parts)


@pytest.mark.skipif(
    not WINDOWS_POWERSHELL.exists(),
    reason="Windows PowerShell 5.1 desktop consumer is not present",
)
def test_pi_desktop_launch_chain_parses_in_windows_powershell_51() -> None:
    scripts = sorted((SOURCE_ROOT / "scripts").glob("*.ps1"))
    failures: list[str] = []
    for script in scripts:
        escaped = str(script).replace("'", "''")
        command = (
            "$tokens=$null;$errors=$null;"
            "[void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{escaped}',[ref]$tokens,[ref]$errors);"
            "if($errors.Count -gt 0){$errors|ForEach-Object{$_.Message};exit 1}"
        )
        completed = subprocess.run(
            [
                str(WINDOWS_POWERSHELL),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            failures.append(f"{script.name}: {completed.stdout}{completed.stderr}")

    assert not failures, "\n".join(failures)


def test_pi_windows_powershell_51_scripts_avoid_newer_dotnet_hash_apis() -> None:
    scripts = "\n".join(
        _text(path) for path in sorted((SOURCE_ROOT / "scripts").glob("*.ps1"))
    )
    assert "[Security.Cryptography.SHA256]::HashData" not in scripts
    assert "[Convert]::ToHexString" not in scripts


@pytest.mark.skipif(not MAIN_CODEX.exists(), reason="shared Codex skill catalog is not present")
def test_shared_skill_descriptions_fit_pi_catalog_limit() -> None:
    names = (
        "conduct-xinao-native-research",
        "human-agency-grounding",
        "maintain-personal-decision-model",
    )
    lengths = {
        name: len(_frontmatter_description(MAIN_CODEX / "skills" / name / "SKILL.md"))
        for name in names
    }
    assert all(length <= 1024 for length in lengths.values()), lengths


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
    assert "$settings['hideThinkingBlock'] = $false" in initializer
    assert "the user wants the visible reasoning stream" in initializer
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
    assert "foreach ($profileName in $Profile)" in installer
    assert "foreach ($profile in $Profile)" not in installer
    assert "--no-session --tools read" in cross_repo
    assert "SENTINEL:XINAO_NATIVE_RESEARCH_ROLE_V2" in cross_repo
    assert "SENTINEL:XINAO_CURRENT_PROJECTION_V7" in cross_repo
    assert "Resolve-PiProfileSessionSelection" in start
    assert "PI_SESSION_SELECTION_CONFLICTS_WITH_NEW_SESSION" in start
    assert "PI_SESSION_SELECTION_OUTSIDE_PROFILE" in start
    assert "$arguments += @('--session',$selectedSession)" in start


def test_prime_s_numpad_enter_follow_preserves_native_input_and_is_nonblocking() -> None:
    helper = _text(
        SOURCE_ROOT / "helpers" / "PrimeS-NumPadEnter-Follow.ahk"
    )
    configure = _text(SOURCE_ROOT / "scripts" / "Set-PiSNumpadEnterFollow.ps1")
    probe = _text(SOURCE_ROOT / "scripts" / "Test-PiSNumpadEnterFollow.mjs")
    initializer = _text(SOURCE_ROOT / "scripts" / "Initialize-UpstreamPiProfiles.ps1")
    start = _text(SOURCE_ROOT / "scripts" / "Start-UpstreamPi.ps1")
    readme = _text(SOURCE_ROOT / "README.md")

    assert '#HotIf WinActive("prime S ahk_exe WindowsTerminal.exe")' in helper
    assert "$NumpadEnter::" in helper
    assert 'Send "{Enter}"' in helper
    assert 'Send "{F12}"' in helper
    assert "$Enter::" not in helper
    assert "ClassifyPointerRoute" in helper
    assert "--owner-pid" in helper
    assert "--self-test" in helper

    assert "PI_S_NUMPAD_TARGET_NOT_ACTIVE_PRIME_S" in configure
    assert "profiles\\prime-s" in configure
    assert "tui.altScreen.bottom" in configure
    assert "@('end')" in configure
    assert "'f12'" in configure
    assert "PI_S_NUMPAD_F12_ALREADY_CLAIMED" in configure
    assert "PrimeS-NumPadEnter-Follow.selftest-$validationId.ahk" in configure
    assert "PI_S_WINDOWS_TERMINAL_CLOSE_ON_EXIT_NOT_INSTALLED" in configure
    assert "windows_terminal_profile_close_on_exit = 'always'" in configure
    assert "helper_failure_blocks_pi = $false" in configure
    assert "AutoHotkey64.exe" in configure
    assert "a2a54b8abc476d7671d4de0771bb54bf5f2373d79ff6871d0ba6a62c3b88ae00" in configure

    assert 'manager.getKeys("tui.altScreen.bottom")' in probe
    assert 'manager.getKeys("tui.input.submit")' in probe
    assert 'manager.matches("\\u001b[24~", "tui.altScreen.bottom")' in probe
    assert 'manager.matches("\\r", "tui.input.submit")' in probe
    assert 'f12Claimants.length !== 1' in probe

    assert "Set-PiSNumpadEnterFollow.ps1" in initializer
    assert "Set-PiSNumpadEnterFollow.ps1" in start
    assert "Stop-PiSNumpadEnterHelper" in start
    assert "-WindowStyle Hidden" in start
    assert "unavailable-nonblocking" in start
    assert "Pi 将按原生键位正常启动" in start
    assert "tui.altScreen.bottom" in readme
    assert "Windows Terminal 全局键位和 PrimeB 均保持不变" in readme
    assert "closeOnExit=always" in readme


def test_prime_s_supervisor_ingress_uses_owned_overlay_and_native_pi_seam() -> None:
    common = _text(SOURCE_ROOT / "scripts" / "PiDualEntry.Common.ps1")
    initializer = _text(SOURCE_ROOT / "scripts" / "Initialize-UpstreamPiProfiles.ps1")
    start = _text(SOURCE_ROOT / "scripts" / "Start-UpstreamPi.ps1")
    extension = _text(
        SOURCE_ROOT
        / "surface-overlays"
        / "prime-s"
        / "extensions"
        / "supervisor-ingress.ts"
    )
    skill_root = (
        SOURCE_ROOT
        / "surface-overlays"
        / "prime-s"
        / "skills"
        / "understand-and-steer-prime"
    )
    skill = _text(skill_root / "SKILL.md")
    client = _text(skill_root / "scripts" / "pi-supervisor-command.mjs")

    assert "Sync-PiDualEntrySurfaceOverlay" in common
    assert "xinao-surface-overlay-manifest.json" in common
    assert "owned_files" in common
    assert "Sync-PiDualEntrySurfaceOverlay -Spec $spec" in initializer
    assert "Sync-PiDualEntrySurfaceOverlay -Spec $spec" in start
    assert "$env:XINAO_PI_PROFILE = $Profile" in start
    assert "$env:XINAO_PI_SUPERVISOR_ENABLED = '1'" in start
    assert "$env:XINAO_PI_SUPERVISOR_PIPE = $spec.SupervisorPipe" in start
    assert "Remove-Item Env:XINAO_PI_SUPERVISOR_ENABLED" in start
    assert "Remove-Item Env:XINAO_PI_SUPERVISOR_PIPE" in start

    assert 'from "node:net"' in extension
    assert "pi.sendUserMessage" in extension
    assert "ctx.sessionManager.getSessionId()" in extension
    assert "PI_SUPERVISOR_TARGET_MISMATCH" in extension
    assert "runtime_accepted" in extension
    assert "message_consumed" in extension
    assert "agent_settled" in extension
    assert "active_tools: [...pi.getActiveTools()].sort()" in extension
    assert "available_tools: pi.getAllTools().map((tool) => tool.name).sort()" in extension
    assert "ctx.abort()" in extension
    assert "ctx.shutdown()" in extension
    assert "message_sha256" in extension
    assert "message:" not in extension

    assert "ACK" in skill and "consumed" in skill and "effect" in skill
    assert "pi-supervisor-command.mjs" in skill
    assert "prime-daemon-command.mjs" not in skill
    assert "get_state" in client and "get_events" in client
    assert "--session" in client and "--profile" in client
    assert "process.stdin" in client
    assert not (SOURCE_ROOT / "surface-overlays" / "prime-b" / "extensions").exists()
    assert not (SOURCE_ROOT / "surface-overlays" / "prime-b" / "skills").exists()


def test_pi_s_body_lab_is_isolated_version_pinned_and_session_empty() -> None:
    body_lab = _text(SOURCE_ROOT / "scripts" / "New-PiSBodyLab.ps1")
    assert "body-labs\\prime-s" in body_lab
    assert "PI_S_BODY_LAB_ALREADY_EXISTS" in body_lab
    assert "Get-PiDualEntrySpec -Profile 'prime-s'" in body_lab
    assert "Get-PiDualEntrySpec -Profile 'prime-b'" not in body_lab
    assert "$activeAuthSource = Join-Path $source.AgentDir 'auth.json'" in body_lab
    assert "Copy-Item -LiteralPath $activeAuthSource" in body_lab
    assert "Sync-PiDualEntrySurfaceOverlay -Spec $labSpec" in body_lab
    assert "New-Item -ItemType Directory -Force -Path $labSpec.SessionDir" in body_lab
    assert "Copy-Item -LiteralPath $source.SessionDir" not in body_lab
    assert "PI_S_BODY_LAB_PACKAGE_NOT_PINNED" in body_lab
    assert "pi-s-body-lab.json" in body_lab
    assert "SeedSerperCredential" in body_lab
    assert "Set-PiSSerperCredential.ps1" in body_lab
    assert "serper_credential_stored" in body_lab
    assert "Set-PiSBodyConfiguration.ps1" in body_lab
    assert body_lab.index("Set-PiSBodyConfiguration.ps1") < body_lab.index(
        "$env:PI_CODING_AGENT_DIR = $labSpec.AgentDir"
    )
    assert body_lab.index("$labSpec = [pscustomobject]$labValues") < body_lab.index(
        "Set-PiSSerperCredential.ps1"
    )


def test_prime_s_mature_body_is_profile_local_sparse_and_non_autonomous() -> None:
    common = _text(SOURCE_ROOT / "scripts" / "PiDualEntry.Common.ps1")
    initializer = _text(SOURCE_ROOT / "scripts" / "Initialize-UpstreamPiProfiles.ps1")
    installer = _text(SOURCE_ROOT / "scripts" / "Install-UpstreamPiCapabilities.ps1")
    start = _text(SOURCE_ROOT / "scripts" / "Start-UpstreamPi.ps1")
    body = _text(SOURCE_ROOT / "scripts" / "Set-PiSBodyConfiguration.ps1")
    hermes_compatibility = _text(
        SOURCE_ROOT / "scripts" / "Apply-PiSHermesSessionCompatibility.ps1"
    )
    hermes_probe = _text(
        SOURCE_ROOT / "scripts" / "Test-PiSHermesSessionCompatibility.mjs"
    )

    assert "npm:pi-hermes-memory@0.9.4" in common
    assert "npm:pi-mcp-adapter@2.21.0" in common
    assert "pi-interactive-shell" not in common
    assert "pi-boomerang" not in common
    assert "ExcludedTools = @('skill_manage','mcp','mcpScript')" in common
    assert "Set-PiSBodyConfiguration.ps1" in initializer
    assert "Set-PiSBodyConfiguration.ps1" in installer
    assert "Set-PiSBodyConfiguration.ps1" in start
    assert "--exclude-tools" in start and "$spec.ExcludedTools -join ','" in start

    assert "profiles\\prime-s" in body
    assert "body-labs\\prime-s" in body
    assert "PI_S_BODY_CONFIG_TARGET_OUTSIDE_PRIME_S" in body
    assert "hermes-memory-config.json" in body
    assert "memoryPolicyStyle = 'custom'" in body
    assert "reviewEnabled = $false" in body
    assert "correctionDetection = $false" in body
    assert "flushOnCompact = $false" in body
    assert "flushOnShutdown = $false" in body
    assert "memoryOverflowStrategy = 'reject'" in body
    assert "standingInstructionsEnabled = $false" in body
    assert "variant = 'anchors'" in body
    assert "mcp.json" in body
    assert "hostConfigDiscovery = 'off'" in body
    assert "directTools = $false" in body
    assert "scriptMode = $false" in body
    assert "autoAuth = $false" in body
    assert "sampling = $false" in body
    assert "elicitation = $false" in body
    assert "mcpServers = [ordered]@{}" in body
    assert "boomerang" not in body.lower()

    assert "pi-hermes-memory@0.9.4" in hermes_compatibility
    assert "PI_S_HERMES_PATCH_VERSION_UNSUPPORTED" in hermes_compatibility
    assert "subagent-artifacts" in hermes_compatibility
    assert "child_artifacts_deleted = $false" in hermes_compatibility
    assert "getSessionFiles(sessionDir)" in hermes_probe
    assert "result.errors.length > 0" in hermes_probe
    assert "subagent_artifact_transcripts_parsed_as_sessions: false" in hermes_probe
    assert "child_artifacts_deleted: false" in hermes_probe

    rpc = _text(SOURCE_ROOT / "scripts" / "Test-PiSSparseBodyRpc.mjs")
    assert 'tools: ["memory_add"]' in rpc
    assert 'tools: ["memory_search"]' in rpc
    assert 'tools: ["session_search"]' in rpc
    assert 'tools: ["mcp"]' in rpc
    assert "autonomous_memory_write: false" in rpc
    assert "standing_instruction_write: false" in rpc
    assert 'mcp_host_discovery: "off"' in rpc
    assert "Fresh process anchor session_search" in rpc


def test_prime_s_native_children_cover_openai_account_follow_deepseek_and_portable_async() -> None:
    initializer = _text(SOURCE_ROOT / "scripts" / "Initialize-UpstreamPiProfiles.ps1")
    seed = _text(SOURCE_ROOT / "scripts" / "Seed-PiCodexAuth.ps1")
    binding = _text(SOURCE_ROOT / "scripts" / "Set-UpstreamPiAccountBinding.ps1")
    child = _text(SOURCE_ROOT / "scripts" / "Test-PiSubagentRpc.mjs")
    deepseek = _text(SOURCE_ROOT / "scripts" / "Set-PiSDeepSeekCredential.ps1")
    deepseek_child = _text(SOURCE_ROOT / "scripts" / "Test-PiSDeepSeekChildRpc.mjs")
    compatibility = _text(
        SOURCE_ROOT / "scripts" / "Apply-PiSSubagentsWindowsCompatibility.ps1"
    )
    async_probe = _text(SOURCE_ROOT / "scripts" / "Test-PiSAsyncWorkflowRpc.mjs")

    assert "deepseek/deepseek-v4-*" in initializer
    assert "if ($property.Name -cne 'openai-codex')" in seed
    assert "PI_ACCOUNT_BINDING_REQUIRES_PROFILE_STOP" in binding
    assert "clean_process_boundary_enforced = $true" in binding
    assert "fresh_root_child_account_probe_required = $true" in binding
    assert "resumed_root_and_new_children_share_profile_auth" not in binding
    assert "profile_binding_matches_invocation: true" in child
    assert "account_id_sha256: accountIdSha256" in child
    assert "root_and_child_native_openai_consumed: true" in child
    assert 'item.provider !== "openai-codex"' in child

    assert "C:\\Users\\xx363\\私钥\\DeepSeek-api-key-active.txt" in deepseek
    assert "deepseek-v4-flash" in deepseek and "deepseek-v4-pro" in deepseek
    assert "merged['deepseek']" in deepseek
    assert 'provider !== "deepseek"' in deepseek_child
    assert "codex_external_worker_used: false" in deepseek_child
    assert '"--no-session"' in deepseek_child

    assert "pi-subagents@0.43.0" in compatibility
    assert "workflow-" in compatibility and "randomUUID()" in compatibility
    assert "provider_tool_id_used_as_path = $false" in compatibility
    assert '"--no-session"' in async_probe
    assert "provider_tool_id_used_as_path: false" in async_probe
    assert "windows_path_portable: true" in async_probe


def test_prime_s_serper_is_profile_native_strict_and_has_no_exa_fallback() -> None:
    extension = _text(
        SOURCE_ROOT
        / "surface-overlays"
        / "prime-s"
        / "extensions"
        / "serper-search.ts"
    )
    credential = _text(SOURCE_ROOT / "scripts" / "Set-PiSSerperCredential.ps1")

    assert 'join(AGENT_DIR, "credentials", "serper.json")' in extension
    assert 'name: "web_search"' in extension
    assert '"X-API-KEY": apiKey' in extension
    assert 'const ENDPOINT = "https://google.serper.dev/search"' in extension
    assert "SERPER_AUTH_REJECTED" in extension
    assert "SERPER_QUOTA_REJECTED" in extension
    assert "strictProvider: true" in extension
    assert "PROFILE !== \"prime-s\"" in extension
    assert "exa" not in extension.lower()

    assert "profiles\\prime-s" in credential
    assert "body-labs\\prime-s" in credential
    assert "PI_SERPER_TARGET_NOT_PRIME_S" in credential
    assert "xinao.pi_serper_credential.v1" in credential
    assert "source_path_persisted_as_runtime_dependency = $false" in credential
    assert "credential_stored = $true" in credential
    assert "apiKey = $apiKey" in credential
    assert "PrimeB" not in credential
    assert "C:\\Users\\xx363\\私钥\\serper-key.txt" in credential
    assert "serper-----key.txt" not in credential
    assert "pi-s-body-lab.json" in credential
    assert "PI_SERPER_LAB_MANIFEST_IDENTITY_MISMATCH" in credential
    assert "credential_updated_at" in credential
    assert "PI_SERPER_ACTIVE_PROFILE_REQUIRES_PROVIDER_PROBE" in credential
    assert credential.index("Invoke-WebRequest") < credential.index("Write-PiDualEntryJsonAtomic -Path $credentialPath")
    assert "PI_SERPER_AUTH_REJECTED" in credential
    assert "PI_SERPER_QUOTA_REJECTED" in credential

    rpc = _text(SOURCE_ROOT / "scripts" / "Test-PiSSerperRpc.mjs")
    assert '"--tools",\n      "web_search"' in rpc
    assert 'XINAO_PI_PROFILE: "prime-s"' in rpc
    assert 'XINAO_PI_SUPERVISOR_ENABLED: "0"' in rpc
    assert "starts.length !== 1" in rpc
    assert "SERPER_AUTH_REJECTED" in rpc
    assert "SERPER_QUOTA_REJECTED" in rpc
    assert 'strict_provider: true' in rpc
    assert 'no_other_tool_called: true' in rpc


def test_codex_pis_steward_skill_recovers_durable_intent_without_second_truth() -> None:
    skill_root = SOURCE_ROOT / "codex-skills" / "steward-pis-evolution"
    skill = _text(skill_root / "SKILL.md")
    recovery = _text(skill_root / "references" / "recovery-map.md")
    installer = _text(SOURCE_ROOT / "scripts" / "Install-CodexPiSStewardSkill.ps1")

    assert "name: steward-pis-evolution" in skill
    description = skill.split("description:", 1)[1].splitlines()[0].strip()
    assert len(description) <= 1024
    assert "pi-local-cognition-contract-island\\AGENTS.md" in skill
    assert "CURRENT_CAPABILITY_LINEAGE.md" in skill
    assert "understand-and-steer-prime\\SKILL.md" in skill
    assert "sent -> acknowledged -> runtime accepted -> message consumed" in skill
    normalized_skill = " ".join(skill.split())
    assert "PiS is the primary working and evolution surface" in skill
    assert "Two Codex accounts" in skill
    assert "Ordinary TUI competence is only the floor" in skill
    assert "form or revise its own local problem" in skill
    assert "recursively organize genuinely independent labor" in normalized_skill
    assert "Codex must not manufacture a green demonstration by pre-slicing" in skill
    assert "tool/subagent counts" in skill
    assert "Sparse activation still applies" in skill
    assert "return-to-task loop" in skill
    assert "Compile the Pi relationship, not a fixed ritual" in skill
    assert "select only the actions with positive value" in normalized_skill
    assert "does not require every invocation to launch children" in normalized_skill
    assert "Do not freeze today's construction cadence" in skill
    assert "optional supervision mechanisms" in skill
    assert "Never simulate maturity with a long-running hook" in skill
    assert "Keep PiS observable without turning it into noise" in skill
    assert "natural Simplified Chinese" in skill
    assert "leaving only a spinner" in normalized_skill
    assert "preserve `Working...`, tool cards" in skill
    assert "material evidence change" in skill
    assert "endlessly spinning activity marker" in skill
    assert "without turning every incident into a permanent command" in normalized_skill
    assert "must not be left as a visible `process exited`/launch-error page" in normalized_skill
    assert "Never kill the shared `WindowsTerminal.exe`" in normalized_skill
    assert "desktop-wide enumeration project" in normalized_skill
    assert "Do not restore Prime Agent 0.7" in skill
    assert "unattended self-modifying service" in skill
    assert "source-file path as a runtime dependency" in skill
    assert "prime-daemon-command.mjs" not in skill

    assert "Default PiS pipe" in recovery
    assert "body-labs\\prime-s" in recovery
    assert "PiB is outside the default write cone" in recovery
    assert "C:\\Users\\xx363\\私钥" in recovery
    assert "PrimeS-NumPadEnter-Follow.ahk" in recovery
    assert "Set-PiSDeepSeekCredential.ps1" in recovery
    assert "closeOnExit=always" in recovery

    assert "$CodexHome = 'C:\\Users\\xx363\\.codex'" in installer
    assert "xinao.codex_pis_steward_projection.v1" in installer
    assert "PI_CODEX_STEWARD_TARGET_ESCAPE" in installer
    assert "PI_CODEX_STEWARD_PROJECTION_CONFLICT" in installer
    assert "Write-PiDualEntryJsonAtomic" in installer
    assert ".codex-s-hardmode-account-b" not in installer


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
    assert 'root_and_child_native_openai_consumed: true' in rpc


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
        "npm:pi-hermes-memory@0.9.4",
        "npm:pi-mcp-adapter@2.21.0",
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
    assert "thinking/reasoning 块默认展开并使用自然简体中文" in prime_s
    assert "`Working...`、工具卡、subagent 的前台/后台与 lane" in prime_s
    assert "不能让一个永远旋转的 `Working...` 冒充健康" in prime_s
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
