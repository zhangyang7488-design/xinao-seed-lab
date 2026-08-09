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


@pytest.mark.skipif(
    not WINDOWS_POWERSHELL.exists(),
    reason="Windows PowerShell 5.1 desktop consumer is not present",
)
def test_pi_native_command_capture_uses_exit_code_not_warning_stderr() -> None:
    common = SOURCE_ROOT / "scripts" / "PiDualEntry.Common.ps1"
    escaped_common = str(common).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop';"
        f". '{escaped_common}';"
        "$ok=Invoke-PiDualEntryNativeCommand -FilePath $env:ComSpec "
        "-ArgumentList @('/d','/c','echo WARN_ONLY 1>&2 & exit /b 0');"
        "$bad=Invoke-PiDualEntryNativeCommand -FilePath $env:ComSpec "
        "-ArgumentList @('/d','/c','echo REAL_ERROR 1>&2 & exit /b 7');"
        "[ordered]@{"
        "ok_exit=$ok.exit_code;ok_output=($ok.output -join '|');"
        "bad_exit=$bad.exit_code;bad_output=($bad.output -join '|');"
        "restored=[string]$ErrorActionPreference"
        "}|ConvertTo-Json -Compress"
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

    assert completed.returncode == 0, completed.stdout + completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["ok_exit"] == 0
    assert "WARN_ONLY" in receipt["ok_output"]
    assert receipt["bad_exit"] == 7
    assert "REAL_ERROR" in receipt["bad_output"]
    assert receipt["restored"] == "Stop"


def test_pi_install_consumers_use_native_exit_code_capture() -> None:
    expected_sites = {
        "New-PiSBodyLab.ps1": 2,
        "Install-UpstreamPiCapabilities.ps1": 1,
        "Install-PiSMainCore.ps1": 1,
    }
    for name, expected_count in expected_sites.items():
        text = _text(SOURCE_ROOT / "scripts" / name)
        assert text.count("Invoke-PiDualEntryNativeCommand") == expected_count
        assert " install $package --no-approve 2>&1" not in text


def test_main_prime_core_is_profile_scoped_and_cold_backup_stays_isolated() -> None:
    common = _text(SOURCE_ROOT / "scripts" / "PiDualEntry.Common.ps1")
    consumers = {
        name: _text(SOURCE_ROOT / "scripts" / name)
        for name in (
            "Start-UpstreamPi.ps1",
            "Install-UpstreamPiCapabilities.ps1",
            "Test-PiCrossRepositoryContext.ps1",
            "Test-UpstreamPiDualEntry.ps1",
            "New-PiSBodyLab.ps1",
        )
    }
    midturn_apply = _text(
        SOURCE_ROOT / "scripts" / "Apply-PiSMidTurnCompactionCompatibility.ps1"
    )
    midturn_restore = _text(
        SOURCE_ROOT / "scripts" / "Restore-PiSMidTurnCompactionCompatibility.ps1"
    )
    post_apply = _text(
        SOURCE_ROOT / "scripts" / "Apply-PiSPost0841UpstreamCompatibility.ps1"
    )
    post_restore = _text(
        SOURCE_ROOT / "scripts" / "Restore-PiSPost0841UpstreamCompatibility.ps1"
    )
    start = consumers["Start-UpstreamPi.ps1"]
    installer = _text(SOURCE_ROOT / "scripts" / "Install-PiSMainCore.ps1")
    readme = _text(SOURCE_ROOT / "README.md")
    recovery = _text(
        SOURCE_ROOT
        / "codex-skills"
        / "steward-pis-evolution"
        / "references"
        / "recovery-map.md"
    )

    assert "$script:PiDualEntryMainToolRoot = 'D:\\XINAO_RESEARCH_RUNTIME\\tools\\pi\\prime\\0.84.1'" in common
    assert "$script:PiDualEntryBackupToolRoot = 'D:\\XINAO_RESEARCH_RUNTIME\\tools\\pi\\0.84.1'" in common
    assert "PiToolRoot = $toolRoot" in common
    assert "PiCommand = Join-Path $toolRoot 'node_modules\\.bin\\pi.cmd'" in common
    assert "[Parameter(Mandatory)]$Spec" in common
    assert "$Spec.PiCommand" in common
    assert "$script:PiDualEntryToolRoot" not in common
    assert "$script:PiDualEntryCommand" not in common

    for name, text in consumers.items():
        assert "$script:PiDualEntryCommand" not in text, name
        assert "$script:PiDualEntryToolRoot" not in text, name

    assert "$script:PiDualEntryMainToolRoot" in midturn_apply
    assert "$script:PiDualEntryBackupToolRoot" in midturn_apply
    assert "$script:PiDualEntryMainToolRoot" in midturn_restore
    assert "$script:PiDualEntryBackupToolRoot" in midturn_restore
    for text in (post_apply, post_restore):
        assert "$script:PiDualEntryMainToolRoot" in text
        assert "$script:PiDualEntryBackupToolRoot" not in text
        assert "BODY_LAB" in text
    assert "shared_cold_backup_core_allowed = $false" in post_apply
    assert "Apply-PiSPost0841UpstreamCompatibility.ps1" in start
    assert "-PiToolRoot $spec.PiToolRoot" in start
    assert "xinao.pi_main_with_cold_snapshot.acceptance.v4" in consumers[
        "Test-UpstreamPiDualEntry.ps1"
    ]
    assert "Get-PiDualEntrySpec -Profile 'prime-s'" in installer
    assert "$script:PiDualEntryMainToolRoot" in installer
    assert "$script:PiDualEntryBackupToolRoot" in installer
    assert "cold_backup_touched = $false" in installer
    for text in (readme, recovery):
        assert "tools\\pi\\prime\\0.84.1" in text
        assert "tools\\pi\\0.84.1" in text
        assert "Install-PiSMainCore.ps1" in text
        assert "/dev/null" in text


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
    assert "Role = 'cold-backup-snapshot'" in common
    assert "Role = 'primary'" in common
    assert "[string[]]$Profile = @('prime-s')" in initializer
    assert "[string[]]$Profile = @('prime-s')" in installer
    assert "[string[]]$Profile = @('prime-s')" in cross_repo
    assert "profiles\\$Profile\\account-binding.json" in common
    assert "Get-PiDualEntrySpec -Profile $profileName" in initializer
    assert "$spec.OverlayAgentDir" in initializer
    assert "$settings['hideThinkingBlock'] = $false" in initializer
    assert "explicitly frozen cold backup consume the same" in initializer
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
    assert "用户未限定地说 Pi 时默认指它" in readme
    assert "隔离冷备" in readme
    assert "完成后不随主面演化" in readme
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
    assert common.count("npm:pi-subagents@0.44.0','npm:pi-autoresearch@1.6.2','npm:pi-hermes-memory@0.9.4','npm:pi-mcp-adapter@2.21.1") == 2
    assert common.count("ExcludedTools = @('skill_manage','mcp','mcpScript')") == 2

    snapshot_files = (
        "agents/body-friction-auditor.md",
        "extensions/activity-visibility.ts",
        "extensions/serper-search.ts",
        "extensions/supervisor-ingress.ts",
        "skills/understand-and-steer-prime/SKILL.md",
        "skills/understand-and-steer-prime/references/pi-runtime-and-control.md",
        "skills/understand-and-steer-prime/scripts/pi-supervisor-command.mjs",
    )
    for relative in snapshot_files:
        # PiB is an isolated frozen snapshot, not a live mirror of the main
        # surface. Both snapshot entries remain recoverable, but later main-only
        # evolution must not be forced back into byte equality here.
        assert (SOURCE_ROOT / "surface-overlays" / "prime-s" / relative).is_file()
        assert (SOURCE_ROOT / "surface-overlays" / "prime-b" / relative).is_file()
    assert (
        SOURCE_ROOT / "surface-overlays" / "prime-s" / "extensions" / "return-to-parent.ts"
    ).is_file()
    assert not (
        SOURCE_ROOT / "surface-overlays" / "prime-b" / "extensions" / "return-to-parent.ts"
    ).exists()
    assert (SOURCE_ROOT / "surface-overlays" / "prime-s" / "agents" / "peer.md").is_file()
    assert not (SOURCE_ROOT / "surface-overlays" / "prime-b" / "agents" / "peer.md").exists()
    snapshot_contract = _text(
        SOURCE_ROOT / "surface-overlays" / "prime-b" / "COLD_SNAPSHOT.md"
    )
    assert "Never copied from main or cross-linked: Codex OAuth" in snapshot_contract
    assert "ordinary maintenance, upgrade, test, reporting, and mention cone" in snapshot_contract


def test_prime_s_programmatic_restart_preserves_visible_terminal_profile() -> None:
    restart = _text(
        SOURCE_ROOT / "scripts" / "Start-PrimeSInWindowsTerminal.ps1"
    )
    readme = _text(SOURCE_ROOT / "README.md")
    steward = _text(
        SOURCE_ROOT / "codex-skills" / "steward-pis-evolution" / "SKILL.md"
    )
    recovery = _text(
        SOURCE_ROOT
        / "codex-skills"
        / "steward-pis-evolution"
        / "references"
        / "recovery-map.md"
    )

    assert "$terminalProfileName = 'prime'" in restart
    assert "$desktopWrapper = 'C:\\Users\\xx363\\CodexLaunchers\\Open-Prime.ps1'" in restart
    assert "PIS_VISIBLE_RESTART_SESSION_OUTSIDE_PROFILE" in restart
    assert "PIS_VISIBLE_RESTART_SESSION_NOT_LATEST_FOR_PROFILE" in restart
    assert "PIS_VISIBLE_RESTART_TERMINAL_PROFILE_INVALID" in restart
    assert "Start-Process -FilePath $windowsTerminal" in restart
    assert "@('-w','new','-p','\"prime\"')" in restart
    assert "Supplying a replacement commandline through wt.exe" in restart
    assert "EncodedCommand" not in restart
    assert "same_profile_session_required = $true" in restart
    assert "ingress_readback_required = $true" in restart
    assert "profile-native-continue-after-latest-session-proof" in restart
    assert "Start-PrimeSInWindowsTerminal.ps1 -Session" in readme
    assert "never start" in steward and "directly under a new `pwsh`/conhost" in steward
    assert "Do not invoke the PiS desktop wrapper as a fresh `pwsh` process" in recovery


def test_prime_s_numpad_enter_follow_preserves_native_input_and_is_nonblocking() -> None:
    helper = _text(
        SOURCE_ROOT / "helpers" / "PrimeS-NumPadEnter-Follow.ahk"
    )
    configure = _text(SOURCE_ROOT / "scripts" / "Set-PiSNumpadEnterFollow.ps1")
    probe = _text(SOURCE_ROOT / "scripts" / "Test-PiSNumpadEnterFollow.mjs")
    initializer = _text(SOURCE_ROOT / "scripts" / "Initialize-UpstreamPiProfiles.ps1")
    start = _text(SOURCE_ROOT / "scripts" / "Start-UpstreamPi.ps1")
    readme = _text(SOURCE_ROOT / "README.md")

    assert '#HotIf WinActive("prime ahk_exe WindowsTerminal.exe")' in helper
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
    assert "Windows Terminal 全局键位均保持不变" in readme
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
    regression = _text(SOURCE_ROOT / "scripts" / "Test-PiSupervisorIngress.mjs")

    assert "Sync-PiDualEntrySurfaceOverlay" in common
    assert "xinao-surface-overlay-manifest.json" in common
    assert "owned_files" in common
    assert "Sync-PiDualEntrySurfaceOverlay -Spec $spec" in initializer
    assert "Sync-PiDualEntrySurfaceOverlay -Spec $spec" in start
    assert "$env:XINAO_PI_PROFILE = $Profile" in start
    assert "$env:XINAO_PI_SUPERVISOR_ENABLED = '1'" in start
    assert "$env:XINAO_PI_SUPERVISOR_PIPE = $spec.SupervisorPipe" in start
    assert 'SupervisorPipe = "\\\\.\\pipe\\xinao-pi-supervisor-$Profile-v1"' in common
    assert '["prime-s", "prime-b"].includes(PROFILE)' in extension

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
    assert "ctx.compact({" in extension
    assert 'emit("compact_completed"' in extension
    assert "PI_SUPERVISOR_BUSY_CANNOT_COMPACT" in extension
    assert "ctx.shutdown()" in extension
    assert "message_sha256" in extension
    assert "message:" not in extension
    assert "editor_text_present" in extension
    assert "ctx.ui.getEditorText()" in extension
    assert "ctx.ui.setEditorText(editorBefore)" in extension
    assert "owned_editor_residue_removed" in extension
    assert "owned_editor_reconcile_skipped" in extension
    assert "PI_SUPERVISOR_REQUEST_ID_CONFLICT" in extension
    assert "deduplicated: true" in extension
    assert "IDLE_DISPATCH_SETTLE_MS" in extension
    assert 'emit("dispatch_attempted"' in extension
    assert "deferred_past_idle_settlement" in extension
    assert "TARGET_BECAME_BUSY_BEFORE_PROMPT" in extension
    assert 'emit("message_consumption_missing"' in extension
    assert "process_shutdown: false" in extension
    assert "shutdown_requested: true" in extension

    assert "ACK" in skill and "consumed" in skill and "effect" in skill
    assert "pi-supervisor-command.mjs" in skill
    assert "Never type, paste, or stage supervisor text" in skill
    assert "pre-existing draft byte-for-byte" in skill
    assert "`--content-file` is only a transport input" in skill
    assert "short ingress message that names the exact existing read-only path" in skill
    assert "per-step task files into a second queue or control plane" in skill
    assert "main `prime` (internal profile `prime-s`) is the formally appointed repository Owner" in skill
    assert "prime-daemon-command.mjs" not in skill
    assert "get_state" in client and "get_events" in client
    assert "--session" in client and "--profile" in client
    assert "WAIT_CAPABLE.has(args.command) && args.until" in client
    assert "PI_SUPERVISOR_DELIVERY_FAILED" in client
    assert "message_consumption_missing" in client
    assert '"compact_completed"' in client
    assert "process.stdin" in client
    assert "request_id_idempotency: true" in regression
    assert "aborted_hash_reuse_targets_fresh_request: true" in regression
    assert "owned_abort_residue_removed: true" in regression
    assert "preexisting_draft_preserved: true" in regression
    assert "mismatch_preserved: true" in regression
    assert "plaintext_absent_from_events: true" in regression
    assert "idle_settlement_race_deferred: true" in regression
    assert "message_consumption_proven: true" in regression
    assert "prompt_never_silently_becomes_steer: true" in regression
    assert "client_fails_fast_on_typed_delivery_failure: true" in regression
    assert "stop_cancels_unconsumed_owned_delivery: true" in regression
    assert "stop_request_not_misreported_as_process_exit: true" in regression
    assert (SOURCE_ROOT / "surface-overlays" / "prime-b" / "extensions" / "supervisor-ingress.ts").is_file()
    assert (SOURCE_ROOT / "surface-overlays" / "prime-b" / "skills" / "understand-and-steer-prime" / "SKILL.md").is_file()


def test_pi_s_body_lab_is_isolated_version_pinned_and_session_empty() -> None:
    body_lab = _text(SOURCE_ROOT / "scripts" / "New-PiSBodyLab.ps1")
    assert "body-labs\\prime-s" in body_lab
    assert "PI_S_BODY_LAB_ALREADY_EXISTS" in body_lab
    assert "Get-PiDualEntrySpec -Profile 'prime-s'" in body_lab
    assert "Get-PiDualEntrySpec -Profile 'prime-b'" not in body_lab
    assert "$activeAuthSource = Join-Path $source.AgentDir 'auth.json'" in body_lab
    assert "Copy-Item -LiteralPath $activeAuthSource" in body_lab
    assert "Sync-PiDualEntrySurfaceOverlay -Spec $labSpec" in body_lab
    assert 'if ($ownedRelative -in @($overlay.OwnedFiles))' in body_lab
    assert "PI_S_BODY_LAB_OVERLAY_PROJECTION_MISSING" in body_lab
    assert "PI_S_BODY_LAB_OVERLAY_PROJECTION_DRIFT" in body_lab
    assert "surface_overlay_projection_verified = $true" in body_lab
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


def test_prime_s_midturn_compaction_uses_gated_core_seam_and_durable_resume() -> None:
    compatibility = _text(
        SOURCE_ROOT / "scripts" / "Apply-PiSMidTurnCompactionCompatibility.ps1"
    )
    restore = _text(
        SOURCE_ROOT / "scripts" / "Restore-PiSMidTurnCompactionCompatibility.ps1"
    )
    regression = _text(
        SOURCE_ROOT / "scripts" / "Test-PiSMidTurnCompaction.mjs"
    )
    installer = _text(SOURCE_ROOT / "scripts" / "Install-UpstreamPiCapabilities.ps1")
    start = _text(SOURCE_ROOT / "scripts" / "Start-UpstreamPi.ps1")
    body_lab = _text(SOURCE_ROOT / "scripts" / "New-PiSBodyLab.ps1")
    surface_test = _text(SOURCE_ROOT / "scripts" / "Test-UpstreamPiDualEntry.ps1")
    readme = _text(SOURCE_ROOT / "README.md")

    assert "@earendil-works/pi-coding-agent@0.84.1" in compatibility
    assert "91e72d5497f665e731cbd79da6a6e826d8cae7d2ce156a7dee39f8ca205e32c8" in compatibility
    assert "3d42e3311f1b7b5b72aa81dd745cf7a8e089e9b7708abe5e33b9b553651739e6" in compatibility
    assert "afdb16fdacf1a66ac56a96bdcf924beddd3763a97eb8ee39ca2ae410faa7ce93" in compatibility
    assert "PI_S_MIDTURN_NATIVE_CONTINUATION_COMBINATION_CONFLICT" in compatibility
    assert "native_continuation_downstream_composed" in compatibility
    assert "PI_S_MIDTURN_PATCH_SOURCE_CONFLICT" in compatibility
    assert "PI_S_MIDTURN_PATCH_PREIMAGE_CONFLICT" in compatibility
    assert "PI_S_MIDTURN_PATCH_PREIMAGE_MISSING_OR_INVALID" in compatibility
    assert "xinao-compatibility-preimages" in compatibility
    assert "this.agent.shouldStopAfterTurn" in compatibility
    assert '!["prime-s", "prime-b"].includes(process.env.XINAO_PI_PROFILE)' in compatibility
    assert "context.toolResults?.length" in compatibility
    assert "estimateContextTokens(context.context.messages).tokens" in compatibility
    assert "contextWindow <= 0" in compatibility
    assert 'this._runAutoCompaction("threshold", true)' in compatibility
    assert "completed_tool_boundary_stop = $true" in compatibility
    assert "compact_and_continue_same_run = $true" in compatibility
    assert "compaction_failure_stops_before_provider = $true" in compatibility
    assert "rollback_requires_gate_off_and_verified_preimage_restore = $true" in compatibility

    assert "xinao.pi_midturn_compaction_restore.v2" in restore
    assert "PI_S_MIDTURN_RESTORE_PREIMAGE_INVALID" in restore
    assert "PI_S_MIDTURN_RESTORE_SOURCE_CONFLICT" in restore
    assert "3d42e3311f1b7b5b72aa81dd745cf7a8e089e9b7708abe5e33b9b553651739e6" in restore
    assert "604748b31a08b583aa056c1527b4f4d62afc69aefea28e094e53a8d7ce81185a" in restore

    assert "PIS_MIDTURN_COMPACTION_REGRESSION_V1" in regression
    assert '"warmup"' in regression and '"tool-call"' in regression
    assert '"compact"' in regression and '"resume-after-tool"' in regression
    assert "compaction_before_resume" in regression
    assert "compaction_persisted" in regression
    assert "completed_tool_result_consumed_after_compaction" in regression
    assert "completed_tool_result_present_in_resume_request" in regression
    assert "provider_request_blocked_after_compaction_cancel_with_queued_steer" in regression
    assert '"cancel-with-steer"' in regression
    assert 'const testAgentDir = join(testRoot, "agent")' in regression
    assert "PI_CODING_AGENT_DIR: testAgentDir" in regression
    assert 'readFile(join(agentDir, "settings.json")' in regression
    assert 'join(testRoot, "receipt.json")' in regression
    assert 'XINAO_PI_MIDTURN_COMPACTION_BACKPRESSURE: args.gate === "on" ? "1" : "0"' in regression
    assert "external_provider_used: false" in regression

    assert "Apply-PiSMidTurnCompactionCompatibility.ps1" in installer
    assert "midturn_compaction_compatibility" in installer
    assert "Apply-PiSMidTurnCompactionCompatibility.ps1" in start
    assert "$env:XINAO_PI_MIDTURN_COMPACTION_BACKPRESSURE = '1'" in start
    assert "Remove-Item Env:XINAO_PI_MIDTURN_COMPACTION_BACKPRESSURE" in start
    assert "midturn_compaction_compatibility" in start
    assert "midturn_compaction_runtime_enabled = (-not $DisableMidTurnCompactionCompatibility)" in start
    assert "DisableMidTurnCompactionCompatibility" in start
    assert "Restore-PiSMidTurnCompactionCompatibility.ps1" in start
    assert "PI_SURFACE_TEST_MIDTURN_PATCH_STATUS_INVALID" in surface_test
    assert "midturn_compaction_compatibility" in surface_test

    assert "IsolatePiCore" in body_lab
    assert "ApplyMidTurnCompactionCompatibility" in body_lab
    assert "PI_S_BODY_LAB_MIDTURN_PATCH_REQUIRES_ISOLATED_CORE" in body_lab
    assert "pi-tool-root" in body_lab
    assert "PI_S_BODY_LAB_CORE_VERSION_MISMATCH" in body_lab
    assert "midturn_compaction_compatibility" in body_lab

    assert "shouldStopAfterTurn" in readme
    assert "同一 durable session" in readme
    assert "未带 gate 的普通 Pi consumer" in readme


def test_prime_s_native_continuation_is_root_only_abort_fenced_and_reversible() -> None:
    extension = _text(
        SOURCE_ROOT / "surface-overlays" / "prime-s" / "extensions" / "return-to-parent.ts"
    )
    mechanical = _text(SOURCE_ROOT / "scripts" / "Test-PiSReturnToParent.mjs")
    live = _text(SOURCE_ROOT / "scripts" / "Test-PiSReturnToParentLive.mjs")
    core_patch = _text(
        SOURCE_ROOT
        / "patches"
        / "pi-coding-agent-0.84.1-native-continuation-abort-fence.patch"
    )
    apply_native = _text(
        SOURCE_ROOT / "scripts" / "Apply-PiSNativeContinuationCompatibility.ps1"
    )
    restore_native = _text(
        SOURCE_ROOT / "scripts" / "Restore-PiSNativeContinuationCompatibility.ps1"
    )
    start = _text(SOURCE_ROOT / "scripts" / "Start-UpstreamPi.ps1")
    installer = _text(SOURCE_ROOT / "scripts" / "Install-UpstreamPiCapabilities.ps1")
    main_core = _text(SOURCE_ROOT / "scripts" / "Install-PiSMainCore.ps1")
    body_lab = _text(SOURCE_ROOT / "scripts" / "New-PiSBodyLab.ps1")
    surface_test = _text(SOURCE_ROOT / "scripts" / "Test-UpstreamPiDualEntry.ps1")
    readme = _text(SOURCE_ROOT / "README.md")

    assert 'process.env.PI_SUBAGENT_CHILD === "1"' in extension
    handshake = 'process.env.XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE !== "1"'
    assert handshake in extension
    assert extension.index(handshake) < extension.index("pi.registerTool")
    assert 'stopReason !== "stop"' in extension
    assert 'deliverAs: "followUp", triggerTurn: true' in extension
    assert "continuationRunSignal" in extension
    assert "xinao-return-to-parent-continuation" in extension
    assert "provider_context_visibility: \"single_current_arm\"" in extension

    assert "xinao.pi_return_to_parent.acceptance.v3" in mechanical
    assert "provider_calls_multi_provider_continuation" in mechanical
    assert "tagged_context_same_continuation_run_all_providers" in mechanical
    assert "stop_during_continuation_provider_delta" in mechanical
    assert "parserAmbiguousResult" in mechanical and "parserNonFirstArm" in mechanical
    assert "normalized_argument_binding" in live
    assert "matching_tool_result_unique" in live
    assert "matching_arm_first_and_unique" in live

    assert "_extensionAbortEpoch" in core_patch
    assert "signal?.throwIfAborted();" in core_patch
    assert "xinao.pi_native_continuation_compatibility.v1" in apply_native
    assert "requires_midturn_preimage = $true" in apply_native
    assert "$script:PiDualEntryBackupToolRoot" not in apply_native
    assert "native_continuation_absent = $true" in restore_native
    assert "restored_to_midturn_preimage" in restore_native
    assert "fully_restored_upstream_accepted" in restore_native

    clear_index = start.index("Remove-Item Env:XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE")
    midturn_index = start.index("Apply-PiSMidTurnCompactionCompatibility.ps1")
    native_index = start.index("Apply-PiSNativeContinuationCompatibility.ps1")
    owner_stop_index = start.index("Apply-PiSSubagentsSessionStopCompatibility.ps1")
    assert clear_index < midturn_index < native_index < owner_stop_index
    assert "$env:XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE = '1'" in start
    assert "PI_S_NATIVE_CONTINUATION_RUNTIME_HANDSHAKE_WITHOUT_VERIFIED_CORE" in start
    assert "Restore-PiSNativeContinuationCompatibility.ps1" in start
    assert "native_continuation_runtime_enabled = $false" in start

    for consumer in (installer, main_core, body_lab):
        assert "Apply-PiSNativeContinuationCompatibility.ps1" in consumer
        assert consumer.index("Apply-PiSMidTurnCompactionCompatibility.ps1") < consumer.index(
            "Apply-PiSNativeContinuationCompatibility.ps1"
        )
    assert "native_continuation_compatibility" in surface_test
    assert "xinao.pi_return_to_parent.acceptance.v3" in surface_test
    assert "PI_SURFACE_TEST_COLD_BACKUP_NATIVE_CONTINUATION_PRESENT_OR_MIXED" in surface_test
    assert readme.index("Restore-PiSNativeContinuationCompatibility.ps1") < readme.index(
        "Restore-PiSMidTurnCompactionCompatibility.ps1"
    )


def test_prime_s_filesystem_policy_receipt_is_bound_to_current_active_packages() -> None:
    surface_test = _text(SOURCE_ROOT / "scripts" / "Test-UpstreamPiDualEntry.ps1")

    assert "function Get-PiSubagentsSourceAggregateSha256" in surface_test
    assert (
        "active_pi_subagents_source_after_sha256 -cne $currentActivePiSubagentsSourceSha256"
        in surface_test
    )
    assert (
        "prime_b_pi_subagents_source_after_sha256 -cne $currentPrimeBPiSubagentsSourceSha256"
        in surface_test
    )


def test_prime_s_high_capacity_is_typed_main_only_and_transactional() -> None:
    common = _text(SOURCE_ROOT / "scripts" / "PiDualEntry.Common.ps1")
    initializer = _text(SOURCE_ROOT / "scripts" / "Initialize-UpstreamPiProfiles.ps1")
    start = _text(SOURCE_ROOT / "scripts" / "Start-UpstreamPi.ps1")
    installer = _text(SOURCE_ROOT / "scripts" / "Install-UpstreamPiCapabilities.ps1")
    main_core = _text(SOURCE_ROOT / "scripts" / "Install-PiSMainCore.ps1")
    body_lab = _text(SOURCE_ROOT / "scripts" / "New-PiSBodyLab.ps1")
    surface_test = _text(SOURCE_ROOT / "scripts" / "Test-UpstreamPiDualEntry.ps1")
    recursive_peer = _text(SOURCE_ROOT / "surface-overlays" / "prime-s" / "agents" / "recursive-peer.md")
    readme = _text(SOURCE_ROOT / "README.md")

    assert "maxSubagentDepth = 3" in common
    assert "MaxSubagentSpawnsPerSession = 40" in common
    assert "GlobalConcurrencyLimit = 6" in common
    assert "ParallelMaxTasks = 10" in common
    assert "TaskTurnMinimum = 10" in common and "TaskTurnMaximum = 30" in common
    assert "bf6ba259cf937cf9b5bd0d9afd89243206ea15b759bbebf96c27fb651231a1dc" in common
    assert "New-PiSubagentCapacityConfig" in initializer
    assert "New-PiSubagentCapacityConfig" in body_lab
    assert "Enter-PiDualEntryMaintenanceLocks" in common
    assert "Exit-PiDualEntryMaintenanceLocks" in common
    assert "PI_DUAL_ENTRY_MAINTENANCE_TARGET_ACTIVE_OR_BUSY" in common
    for write_installer in (installer, main_core):
        assert "Enter-PiDualEntryMaintenanceLocks" in write_installer
        assert "Exit-PiDualEntryMaintenanceLocks" in write_installer
        assert write_installer.index("Enter-PiDualEntryMaintenanceLocks") < write_installer.index(
            "Apply-PiSMidTurnCompactionCompatibility.ps1"
        )

    clear_index = start.index("Clear-PiSubagentCapacityEnvironment")
    apply_index = start.index("Apply-PiSHighCapacityCompatibility.ps1")
    handshake_index = start.index("Enable-PiSubagentCapacityEnvironment")
    assert clear_index < apply_index < handshake_index
    assert "Global\\XinaoPiSHighCapacityCompatibilityV1" in start
    assert "if ($Profile -eq 'prime-s')" in start
    assert "including intentionally disabled launches" in start
    assert start.index("$capacityCompatibilityMutex = [Threading.Mutex]::new") < start.index(
        "Sync-PiDualEntrySurfaceOverlay"
    )
    assert start.index("$held = $mutex.WaitOne(0)") < start.index(
        "Sync-PiDualEntrySurfaceOverlay"
    )
    assert start.index("$capacityCompatibilityHeld = $capacityCompatibilityMutex.WaitOne(0)") < start.index(
        "Sync-PiDualEntrySurfaceOverlay"
    )
    assert "PI_S_HIGH_CAPACITY_RUNTIME_HANDSHAKE_WITHOUT_VERIFIED_PACKAGE_AND_CORE" in start
    for consumer in (installer, main_core, body_lab):
        assert "Apply-PiSHighCapacityCompatibility.ps1" in consumer
    assert "PI_SURFACE_TEST_COLD_BACKUP_INHERITED_HIGH_CAPACITY" in surface_test
    assert "xinao.pi_s_high_capacity_compatibility.v1" in surface_test

    assert "tools: subagent" in recursive_peer
    assert 'turnBudget: {"maxTurns":30,"graceTurns":0}' in recursive_peer
    assert "maxSubagentDepth: 3" in recursive_peer
    assert "model:" not in recursive_peer
    assert "typed `tasks:[...]`" in readme
    assert "maxTurns + graceTurns" in readme
    assert 'tasks: [{ agent: "peer"' in _text(
        SOURCE_ROOT / "scripts" / "Test-PiSHighCapacityPublicTasks.test.mjs"
    )

    for relative in (
        "patches/pi-subagents-0.44.0-high-capacity-v1.patch",
        "patches/pi-coding-agent-0.84.1-high-capacity-v1.patch",
        "scripts/Apply-PiSHighCapacityCompatibility.ps1",
        "scripts/Restore-PiSHighCapacityCompatibility.ps1",
        "scripts/Test-PiSHighCapacityReplay.ps1",
    ):
        assert (SOURCE_ROOT / relative).is_file()


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
    hermes_capacity = _text(
        SOURCE_ROOT / "scripts" / "Test-PiSHermesMemoryCapacity.mjs"
    )

    assert "npm:pi-hermes-memory@0.9.4" in common
    assert "npm:pi-mcp-adapter@2.21.1" in common
    assert "pi-interactive-shell" not in common
    assert "pi-boomerang" not in common
    assert "ExcludedTools = @('skill_manage','mcp','mcpScript')" in common
    assert "Set-PiSBodyConfiguration.ps1" in initializer
    assert "Set-PiSBodyConfiguration.ps1" in installer
    assert "Set-PiSBodyConfiguration.ps1" in start
    assert "--exclude-tools" in start and "$spec.ExcludedTools -join ','" in start
    surface_test = _text(SOURCE_ROOT / "scripts" / "Test-UpstreamPiDualEntry.ps1")
    assert "PI_SURFACE_TEST_PROVIDER_MODEL_CATALOG_MISSING" in surface_test
    assert "PI_SURFACE_TEST_SOL_CONTEXT_WINDOW_CATALOG_INVALID" in surface_test
    assert "PI_SURFACE_TEST_UNSUPPORTED_SOL_CONTEXT_WINDOW_OVERRIDE" in surface_test
    assert "provider_catalog_context_window" in surface_test
    assert "profile_context_window_override_absent" in surface_test

    assert "profiles\\prime-s" in body
    assert "body-labs\\prime-s" in body
    assert "profiles\\prime-b" in body
    assert "PI_BODY_CONFIG_TARGET_OUTSIDE_MANAGED_PROFILE" in body
    assert "hermes-memory-config.json" in body
    assert "memoryPolicyStyle = 'custom'" in body
    assert "reviewEnabled = $false" in body
    assert "correctionDetection = $false" in body
    assert "flushOnCompact = $false" in body
    assert "flushOnShutdown = $false" in body
    assert "memoryOverflowStrategy = 'reject'" in body
    assert "standingInstructionsEnabled = $false" in body
    assert "variant = 'anchors'" in body
    assert "$isMainPrimeSBody" in body
    assert "$target -eq $primeSProfileTarget -or $targetParent -eq $primeSLabParent" in body
    assert "$hermesConfig['memoryCharLimit'] = 10000" in body
    assert "$hermesConfig['userCharLimit'] = 5000" in body
    assert "$hermesConfig['projectCharLimit'] = 5000" in body
    assert "main-prime-s-explicit" in body
    assert "upstream-default-derived" in body
    assert "mcp.json" in body
    assert "hostConfigDiscovery = 'off'" in body
    assert "directTools = $false" in body
    assert "scriptMode = $false" in body
    assert "autoAuth = $false" in body
    assert "sampling = $false" in body
    assert "elicitation = $false" in body
    assert "mcpServers = [ordered]@{}" in body
    assert "models.json" in body
    assert "unsupported_context_window_override_removed" in body
    assert "context_window_source = 'provider_model_catalog'" in body
    assert "Remove-Item -LiteralPath $modelsPath -Force" in body
    assert "1050000" not in body
    assert "boomerang" not in body.lower()

    assert "pi-hermes-memory@0.9.4" in hermes_compatibility
    assert "PI_S_HERMES_PATCH_VERSION_UNSUPPORTED" in hermes_compatibility
    assert "subagent-artifacts" in hermes_compatibility
    assert "child_artifacts_deleted = $false" in hermes_compatibility
    assert "getSessionFiles(sessionDir)" in hermes_probe
    assert "result.errors.length > 0" in hermes_probe
    assert "subagent_artifact_transcripts_parsed_as_sessions: false" in hermes_probe
    assert "child_artifacts_deleted: false" in hermes_probe
    assert 'assertNoExplicitLimits(raw.primeB.parsed, "PrimeB raw")' in hermes_capacity
    assert 'assertNoExplicitLimits(raw.primeBLab.parsed, "PrimeB lab raw")' in hermes_capacity
    assert "PI_HERMES_MEMORY_CONFIG_INVALID" in hermes_capacity
    assert "Main memory limit changed the first provider system prompt" in hermes_capacity
    assert 'includes("/20000 chars")' in hermes_capacity
    assert "fresh_process_memory_search" in hermes_capacity

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
    file_only_probe = _text(
        SOURCE_ROOT / "scripts" / "Test-PiSFileOnlyAcceptanceRpc.mjs"
    )

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

    assert "pi-subagents-0.44.0-windows-compatibility-v3" in compatibility
    assert "const workflowRunId = randomUUID();" in compatibility
    assert "provider_tool_id_used_as_path = $false" in compatibility
    assert "upstream_portable_workflow_id" in compatibility
    assert "single-output.ts" in compatibility
    assert "comparableOutputPath" in compatibility
    assert "(?:mnt\\/|cygdrive\\/)?([a-z])" in compatibility
    assert "PI_S_SUBAGENTS_SINGLE_OUTPUT_PATCH_SOURCE_CONFLICT" in compatibility
    assert "msys_drive_path_authorship_equivalence = $true" in compatibility
    assert '"--no-session"' in async_probe
    assert "provider_tool_id_used_as_path: false" in async_probe
    assert "windows_path_portable: true" in async_probe
    assert '"--no-session"' in file_only_probe
    assert "FRESH_PIS_MSYS_FILE_ONLY_STRUCTURED" in file_only_probe
    assert "writeCalls.length !== 1" in file_only_probe
    assert "structured_acceptance_consumed: true" in file_only_probe
    assert '"wrong-drive", "sibling", "failed-write", "unanswered-write", "edit", "non-authored-prose"' in file_only_probe


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
    assert '["prime-s", "prime-b"].includes(PROFILE)' in extension
    assert "exa" not in extension.lower()

    assert "profiles\\prime-s" in credential
    assert "body-labs\\prime-s" in credential
    assert "profiles\\prime-b" in credential
    assert "PI_SERPER_TARGET_OUTSIDE_MANAGED_PROFILE" in credential
    assert "xinao.pi_serper_credential.v1" in credential
    assert "source_path_persisted_as_runtime_dependency = $false" in credential
    assert "credential_stored = $true" in credential
    assert "apiKey = $apiKey" in credential
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
    normalized_recovery = " ".join(recovery.split())
    installer = _text(SOURCE_ROOT / "scripts" / "Install-CodexPiSStewardSkill.ps1")

    assert "name: steward-pis-evolution" in skill
    description = skill.split("description:", 1)[1].splitlines()[0].strip()
    assert len(description) <= 1024
    assert "pi-local-cognition-contract-island\\AGENTS.md" in skill
    assert "CURRENT_CAPABILITY_LINEAGE.md" in skill
    assert "understand-and-steer-prime\\SKILL.md" in skill
    assert "sent -> acknowledged -> runtime accepted -> message consumed" in skill
    normalized_skill = " ".join(skill.split())
    assert "user-visible main subject is exactly `prime`" in skill
    assert "PrimeB.lnk` is an isolated cold backup" in skill
    assert "do not routinely maintain, upgrade, test, report, or mention it" in normalized_skill
    assert "Sparse activation applies to organs, children, searches, and supervision cadence" in normalized_skill
    assert "must never be reinterpreted as sparse root intelligence" in normalized_skill
    assert "active root research remains `gpt-5.6-sol` at `max`" in normalized_skill
    assert "never silently downgrade the root for cost" in normalized_skill
    assert "formal repository-local Owner" in skill
    assert "Codex remains the broader user proxy" in skill
    assert "old text that binds all science to Codex is superseded" in normalized_skill
    assert "Ordinary TUI competence is only the floor" in skill
    assert "form or revise its own local problem" in skill
    assert "recursively organize genuinely independent labor" in normalized_skill
    assert "PiS itself is the hands-on research subject" in skill
    assert "not a passive executor that waits for Codex to poll" in normalized_skill
    assert "dynamically selecting, recursively supervising, attacking, and absorbing" in normalized_skill
    assert "recursion is intelligence amplification and independent evidence" in normalized_skill
    assert "not a cheaper substitute for the root Sol" in normalized_skill
    assert "does not mean mandatory fanout or maximum model consumption" in normalized_skill
    assert "Codex must not manufacture a green demonstration by pre-slicing" in skill
    assert "tool/subagent counts" in skill
    assert "Sparse activation still applies" in skill
    assert "repository-owned, revisable semantic world" in skill
    assert "latest current words and architecture supersede" in normalized_skill
    assert "not a fixed ontology" in normalized_skill
    assert "XINAO epistemic body is also situated" in skill
    assert "without Codex feeding another work package" in normalized_skill
    assert "cannot be promoted to a mature self-research/self-evolution loop" in normalized_skill
    assert "not a daemon, fixed state machine, or prewritten research queue" in normalized_skill
    assert "Keep stability scopes separate" in skill
    assert "never make a transient return point a required semantic-root marker" in normalized_skill
    assert "without turning a stale return point into a research queue" in normalized_skill
    assert "return-to-task loop" in skill
    assert "Track detection provenance as part of this loop" in skill
    assert "legitimate **local body optimization objectives**" in normalized_skill
    assert "marginal real cognition and consumer effect" in normalized_skill
    assert "task-local `pi-subagents` model override" in normalized_skill
    assert "Marker probes prove connectivity only" in normalized_skill
    assert "spend alone proves neither value nor body maturity" in normalized_skill
    assert "verifies steering and plasticity, not autonomous self-evolution" in normalized_skill
    assert "does not contain the incident wording or answer" in normalized_skill
    assert "do not build a resident self-auditor" in normalized_skill
    assert "Compile the Pi relationship, not a fixed ritual" in skill
    assert "select only the actions with positive value" in normalized_skill
    assert "does not require every invocation to launch children" in normalized_skill
    assert "Keep human availability separate from Pi lifecycle" in skill
    assert 'even without an extra formula such as "keep going"' in skill
    assert "Do not leave Pi idle merely because the human is away" in normalized_skill
    assert "human going to sleep is not the optional Codex/Pi sleeping" in normalized_skill
    assert "no live parent means no work may be invented" in normalized_skill
    assert "keep both live pressures visible" in normalized_skill
    assert "Run that cycle by dynamic positive value" in skill
    assert "consuming no model turn merely to look busy" in normalized_skill
    assert "no preselected acceptance point" in normalized_skill
    assert "Do not freeze today's construction cadence" in skill
    assert "optional **Codex-side outer-supervision** mechanisms" in skill
    assert "Codex-side outer-supervision" in skill
    assert "not evidence that PiS should wait for Codex to wake or assign work" in normalized_skill
    assert "Only the mechanism and cadence are optional" in skill
    assert "no sparse supervision policy authorizes reducing PiS root model quality" in normalized_skill
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
    assert "PiB is outside the default write, maintenance, upgrade, test, report, and mention cone" in normalized_recovery
    assert "C:\\Users\\xx363\\私钥" in recovery
    assert "PrimeS-NumPadEnter-Follow.ahk" in recovery
    assert "Set-PiSDeepSeekCredential.ps1" in recovery
    assert "deepseek/deepseek-v4-flash" in recovery
    assert "deepseek/deepseek-v4-pro" in recovery
    assert "per-run `model` override" in normalized_recovery
    assert "closeOnExit=always" in recovery
    assert "`refine`, `refine.show`, and `refine.rollback`" in recovery
    assert ".pi-subagents\\refinements" in recovery
    assert "scalar metric and external correctness checks" in normalized_recovery
    assert "real friction -> bounded diagnosis -> isolated" in normalized_recovery
    assert r"C:\Users\xx363\Desktop\历史备用 不动" in recovery
    assert "preservation of a historical event never restores its authority" in normalized_recovery
    assert "Context-window authority and recovery" in recovery
    assert "prime-s\\models-store.json" in recovery
    assert "providers.openai-codex.modelOverrides.gpt-5.6-sol.contextWindow" in recovery
    assert "cannot rescue a branch that already exceeds the real window" in normalized_recovery
    assert "a file pointer is transport, not epistemic authority" in normalized_recovery

    assert "$CodexHome = 'C:\\Users\\xx363\\.codex'" in installer
    assert "xinao.codex_pis_steward_projection.v1" in installer
    assert "PI_CODEX_STEWARD_TARGET_ESCAPE" in installer
    assert "PI_CODEX_STEWARD_PROJECTION_CONFLICT" in installer
    assert "Write-PiDualEntryJsonAtomic" in installer
    assert ".codex-s-hardmode-account-b" not in installer

    live_skill_root = MAIN_CODEX / "skills" / "steward-pis-evolution"
    if live_skill_root.exists():
        assert (skill_root / "SKILL.md").read_bytes() == (
            live_skill_root / "SKILL.md"
        ).read_bytes()
        assert (skill_root / "references" / "recovery-map.md").read_bytes() == (
            live_skill_root / "references" / "recovery-map.md"
        ).read_bytes()


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
        assert settings["compaction"] == {
            "enabled": True,
            "reserveTokens": 65536,
            "keepRecentTokens": 24000,
        }
        assert subagent_config["artifactDir"] == "session"
        assert subagent_config["missions"]["enabled"] is False
        assert subagent_config["scheduledRuns"]["enabled"] is False
        assert "artifactDir" not in settings["subagents"]
        assert "agentOverrides" not in settings["subagents"]
        projection = _text(root / "PI_CONTRACT.md")
        assert "PI_LOCAL_COGNITION_CONTRACT_ISLAND_V1" in projection

    assert manifests["prime-b"]["binding"] == "account-b"
    assert manifests["prime-s"]["binding"] in {"main", "account-b"}
    assert manifests["prime-b"]["session"] != manifests["prime-s"]["session"]
    assert manifests["prime-b"]["packages"] == manifests["prime-s"]["packages"] == [
        "npm:pi-subagents@0.44.0",
        "npm:pi-autoresearch@1.6.2",
        "npm:pi-hermes-memory@0.9.4",
        "npm:pi-mcp-adapter@2.21.1",
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
    assert "主 `prime`" in family and "PrimeB" in family
    assert "一次性冷备快照" in family
    assert "不做例行升级、测试、报告或提起" in family
    assert "当前开放成熟周期同时保留两条未闭压力" in family
    assert "已有正收益前沿时继续推进" in family
    assert "不得假称不存在的自动唤醒能力" in family
    assert "不是由用户或 Codex 逐包续命的作业终端" in family
    assert "coherent effect unit" in family
    assert "不能自行产生父任务完成、等待或" in family
    assert "不得再说成“没有任务”或等待下一包" in family
    assert "不得用无收益计算、形式提交、重复 fanout 或报告墙假装" in family
    assert "每次进化还要记录错误最先由谁发现" in family
    assert "不能冒充 PiS 已能自发发现同类缺口" in family
    assert "不建立常驻自审、固定巡逻或每步检查表" in family
    assert "仓库级 Owner" in family
    assert "外层用户代理职责" in family
    assert "旧材料中“科学只能由 Codex 形成”" in family
    assert "当前有效层" in family and "历史层" in family
    assert "PiS 新澳认识不只覆盖领域内部" in family
    assert "自己的仓库 Owner 和根研究职责" in family
    assert "完整主体的可观察闭环" in family
    assert "不得上卷成“自循环研究/进化已经成熟”" in family
    assert "稳定性层级必须分开" in family
    assert "token、context、延迟、cache、孩子数量、重试和总 API 成本" in family
    assert "单位昂贵认知资源带来的真实认识与消费者效果" in family
    assert "不能作为认识根的 required marker" in family
    assert "不能把旧续点变成新题库" in family
    assert "需要你：否" in family
    assert "不得恢复" in prime_b
    assert "不是“Evolution Pi”" in prime_s
    assert "thinking/reasoning 块默认展开并使用自然简体中文" in prime_s
    assert "`Working...`、工具卡、subagent 的前台/后台与 lane" in prime_s
    assert "不能让一个永远旋转的 `Working...` 冒充健康" in prime_s
    assert "阶段摘要是用户观察连续工作的界面" in prime_s
    assert "不得因刚完成提交、验证或一段 coherent effect unit 就停成" in prime_s
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

    lineage = _text(FAMILY_ISLAND / "cognition" / "CURRENT_CAPABILITY_LINEAGE.md")
    assert "PiS 身体成熟与新澳真实研究两条未闭压力" in lineage
    assert "当前 Codex TUI 尚无已验证的" in lineage
    assert "refine/refine.show/refine.rollback" in lineage
    assert "现已进入主与冷备身体" in lineage
    assert "没有配置 server、direct schema 或常驻工具面" in lineage


@pytest.mark.skipif(
    not (MAIN_CODEX / "AGENTS.md").exists() or not (ACCOUNT_B_CODEX / "AGENTS.md").exists(),
    reason="canonical Codex behavior projections are not present",
)
def test_both_pi_surfaces_share_the_same_canonical_behavior_and_general_skills() -> None:
    assert _sha256(MAIN_CODEX / "AGENTS.md") == _sha256(ACCOUNT_B_CODEX / "AGENTS.md")
    live_agents = _text(MAIN_CODEX / "AGENTS.md")
    assert "Owner 责任席按 effect scope 分辨" in live_agents
    assert "科学或其他领域工作由当前具名 effect scope 的正式 Owner" in live_agents
    assert "Codex、Pi 或其他 agent 都不因产品名天然取得或失去该资格" in live_agents
    assert (MAIN_CODEX / "skills" / "dispatch-grok-worker-pool" / "SKILL.md").is_file()
    assert (MAIN_CODEX / "skills" / "research-external-reality" / "SKILL.md").is_file()
    test_script = _text(SOURCE_ROOT / "scripts" / "Test-UpstreamPiDualEntry.ps1")
    assert "skill:dispatch-grok-worker-pool" in test_script
    assert "skill:research-external-reality" in test_script
    assert "open_external_query_is_seed_not_automatic_boundary=true" in test_script
    assert "external_findings_must_collide_with_live_local_baseline=true" in test_script
    assert "exact_or_explicitly_narrow_lookup_stays_bounded=true" in test_script
