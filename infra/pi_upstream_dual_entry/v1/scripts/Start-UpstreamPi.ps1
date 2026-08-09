#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile,
    [switch]$NewSession,
    [string]$Session,
    [switch]$ValidateOnly,
    [switch]$DisableMidTurnCompactionCompatibility
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

$spec = Get-PiDualEntrySpec -Profile $Profile
$capacityProfile = Get-PiSubagentCapacityProfile -Profile $Profile
Assert-PiDualEntryBinary -Spec $spec
if ($NewSession -and -not [string]::IsNullOrWhiteSpace($Session)) {
    throw 'PI_SESSION_SELECTION_CONFLICTS_WITH_NEW_SESSION'
}

function Resolve-PiProfileSessionSelection {
    param(
        [Parameter(Mandatory)][string]$SessionDir,
        [Parameter(Mandatory)][string]$Selection
    )
    $candidate = $null
    if (Test-Path -LiteralPath $Selection -PathType Leaf) {
        $candidate = [IO.Path]::GetFullPath($Selection)
    } else {
        $matches = @(Get-ChildItem -LiteralPath $SessionDir -File -Filter '*.jsonl' | Where-Object {
            $_.Name.IndexOf($Selection,[StringComparison]::OrdinalIgnoreCase) -ge 0
        })
        if ($matches.Count -ne 1) {
            throw "PI_SESSION_SELECTION_NOT_UNIQUE: profile=$Profile selection=$Selection count=$($matches.Count)"
        }
        $candidate = [IO.Path]::GetFullPath($matches[0].FullName)
    }
    $sessionPrefix = [IO.Path]::GetFullPath($SessionDir).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($sessionPrefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw "PI_SESSION_SELECTION_OUTSIDE_PROFILE: profile=$Profile path=$candidate"
    }
    try { $header = Get-Content -LiteralPath $candidate -TotalCount 1 -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "PI_SESSION_SELECTION_HEADER_INVALID: $candidate" }
    if ([string]$header.type -cne 'session' -or [string]::IsNullOrWhiteSpace([string]$header.id)) {
        throw "PI_SESSION_SELECTION_IDENTITY_INVALID: $candidate"
    }
    $candidate
}

$selectedSession = $null
if (-not [string]::IsNullOrWhiteSpace($Session)) {
    $selectedSession = Resolve-PiProfileSessionSelection -SessionDir $spec.SessionDir -Selection $Session
}

$mutex = [Threading.Mutex]::new($false,$spec.MutexName)
$held = $false
$capacityCompatibilityMutex = $null
$capacityCompatibilityHeld = $false
if ($Profile -eq 'prime-s') {
    # Hold the package/core transaction fence for the complete validation or
    # visible Pi lifetime, including intentionally disabled launches.
    $capacityCompatibilityMutex = [Threading.Mutex]::new($false,'Global\XinaoPiSHighCapacityCompatibilityV1')
}
try {
    try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) {
        Write-Host "$($spec.DisplayName) 已经开着；没有再启动第二个会话窗口。" -ForegroundColor Yellow
        exit 73
    }
    if ($null -ne $capacityCompatibilityMutex) {
        try { $capacityCompatibilityHeld = $capacityCompatibilityMutex.WaitOne(0) }
        catch [Threading.AbandonedMutexException] { $capacityCompatibilityHeld = $true }
        if (-not $capacityCompatibilityHeld) {
            throw 'PI_S_HIGH_CAPACITY_COMPATIBILITY_TRANSACTION_BUSY'
        }
    }

$env:PI_CODING_AGENT_DIR = $spec.AgentDir
$env:PI_CODING_AGENT_SESSION_DIR = $spec.SessionDir
$env:PI_SKIP_VERSION_CHECK = '1'
$env:PI_TELEMETRY = '0'
$env:PI_SUBAGENT_MAX_DEPTH = [string]$capacityProfile.MaxSubagentDepth
$env:CODEX_HOME = $spec.CodexHome
$env:XINAO_ACCOUNT_SLOT = $spec.AccountSlot
$env:XINAO_PI_ROLE = $spec.Role
$env:XINAO_REPO = $spec.Workspace
$env:XINAO_RUNTIME = 'D:\XINAO_RESEARCH_RUNTIME'
$env:XINAO_PI_PROFILE = $Profile
$env:XINAO_PI_SUPERVISOR_ENABLED = '1'
$env:XINAO_PI_SUPERVISOR_PIPE = $spec.SupervisorPipe
# Capacity credentials are launch-scoped. Never accept a static policy, a root
# activation binding, or a child ticket inherited from the caller.
Clear-PiSubagentCapacityEnvironment
$subagentCapacityStaticPolicy = Get-PiSubagentCapacityStaticPolicy -Profile $Profile
# Never trust an inherited continuation handshake. The root-only extension stays
# inert until this launch has verified both the MidTurn underlay and native fence.
Remove-Item Env:XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE -ErrorAction SilentlyContinue
if ($DisableMidTurnCompactionCompatibility) {
    Remove-Item Env:XINAO_PI_MIDTURN_COMPACTION_BACKPRESSURE -ErrorAction SilentlyContinue
} else {
    $env:XINAO_PI_MIDTURN_COMPACTION_BACKPRESSURE = '1'
}
$contractProjection = Sync-PiDualEntryContractProjection -Spec $spec
$surfaceOverlay = Sync-PiDualEntrySurfaceOverlay -Spec $spec
$subagentsCompatibility = $null
$subagentsOwnerSessionStopCompatibility = $null
$subagentsFilesystemPolicyCompatibility = $null
$highCapacityCompatibility = $null
$highCapacityAbsence = $null
$hermesSessionCompatibility = $null
$midTurnCompactionCompatibility = $null
$nativeContinuationCompatibility = $null
$nativeContinuationAbsence = $null
$post0841UpstreamCompatibility = $null
$numpadEnterFollow = $null
$numpadHelperProcess = $null
$numpadHelperStatus = 'not-applicable'
$numpadHelperSource = Join-Path (Split-Path -Parent $PSScriptRoot) 'helpers\PrimeS-NumPadEnter-Follow.ahk'
& (Join-Path $PSScriptRoot 'Set-PiSBodyConfiguration.ps1') -AgentDir $spec.AgentDir | Out-Null
$subagentCapacity = Assert-PiSubagentCapacityProjection -Profile $Profile -AgentDir $spec.AgentDir
if ($ValidateOnly) {
    $subagentsCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSSubagentsWindowsCompatibility.ps1') -AgentDir $spec.AgentDir -VerifyOnly) | ConvertFrom-Json
    $hermesSessionCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSHermesSessionCompatibility.ps1') -AgentDir $spec.AgentDir -VerifyOnly) | ConvertFrom-Json
} else {
    $subagentsCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSSubagentsWindowsCompatibility.ps1') -AgentDir $spec.AgentDir) | ConvertFrom-Json
    $hermesSessionCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSHermesSessionCompatibility.ps1') -AgentDir $spec.AgentDir) | ConvertFrom-Json
}
if ($DisableMidTurnCompactionCompatibility) {
    if ($Profile -eq 'prime-s') {
        $nativeContinuationAbsence = (& (Join-Path $PSScriptRoot 'Restore-PiSNativeContinuationCompatibility.ps1') -PiToolRoot $spec.PiToolRoot -VerifyOnly) | ConvertFrom-Json
    }
    $midTurnCompactionCompatibility = (& (Join-Path $PSScriptRoot 'Restore-PiSMidTurnCompactionCompatibility.ps1') -PiToolRoot $spec.PiToolRoot -VerifyOnly) | ConvertFrom-Json
} elseif ($ValidateOnly) {
    $midTurnCompactionCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSMidTurnCompactionCompatibility.ps1') -PiToolRoot $spec.PiToolRoot -VerifyOnly) | ConvertFrom-Json
    if ($Profile -eq 'prime-s') {
        $nativeContinuationCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSNativeContinuationCompatibility.ps1') -PiToolRoot $spec.PiToolRoot -VerifyOnly) | ConvertFrom-Json
    }
} else {
    $midTurnCompactionCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSMidTurnCompactionCompatibility.ps1') -PiToolRoot $spec.PiToolRoot) | ConvertFrom-Json
    if ($Profile -eq 'prime-s') {
        $nativeContinuationCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSNativeContinuationCompatibility.ps1') -PiToolRoot $spec.PiToolRoot) | ConvertFrom-Json
    }
}
if ($Profile -eq 'prime-s') {
    $ownerStopRaw = if ($ValidateOnly) {
        & (Join-Path $PSScriptRoot 'Apply-PiSSubagentsSessionStopCompatibility.ps1') -AgentDir $spec.AgentDir -VerifyOnly
    } else {
        & (Join-Path $PSScriptRoot 'Apply-PiSSubagentsSessionStopCompatibility.ps1') -AgentDir $spec.AgentDir
    }
    $subagentsOwnerSessionStopCompatibility = ($ownerStopRaw -join [Environment]::NewLine) | ConvertFrom-Json
    $filesystemPolicyRaw = if ($ValidateOnly) {
        & (Join-Path $PSScriptRoot 'Apply-PiSSubagentsFilesystemPolicy.ps1') -AgentDir $spec.AgentDir -VerifyOnly
    } else {
        & (Join-Path $PSScriptRoot 'Apply-PiSSubagentsFilesystemPolicy.ps1') -AgentDir $spec.AgentDir
    }
    $subagentsFilesystemPolicyCompatibility = ($filesystemPolicyRaw -join [Environment]::NewLine) | ConvertFrom-Json
    if ($DisableMidTurnCompactionCompatibility) {
        $highCapacityAbsence = (& (Join-Path $PSScriptRoot 'Restore-PiSHighCapacityCompatibility.ps1') -AgentDir $spec.AgentDir -PiToolRoot $spec.PiToolRoot -VerifyOnly) | ConvertFrom-Json
    } elseif ($ValidateOnly) {
        $highCapacityRaw = & (Join-Path $PSScriptRoot 'Apply-PiSHighCapacityCompatibility.ps1') -AgentDir $spec.AgentDir -PiToolRoot $spec.PiToolRoot -VerifyOnly
        $highCapacityCompatibility = ($highCapacityRaw -join [Environment]::NewLine) | ConvertFrom-Json
    } else {
        # Apply re-enters the already-held transaction mutex on this same
        # PowerShell thread. The outer ownership remains until Pi exits.
        $highCapacityRaw = & (Join-Path $PSScriptRoot 'Apply-PiSHighCapacityCompatibility.ps1') -AgentDir $spec.AgentDir -PiToolRoot $spec.PiToolRoot
        $highCapacityCompatibility = ($highCapacityRaw -join [Environment]::NewLine) | ConvertFrom-Json
    }
}
if ($Profile -eq 'prime-s') {
    $post0841Raw = if ($ValidateOnly) {
        & (Join-Path $PSScriptRoot 'Apply-PiSPost0841UpstreamCompatibility.ps1') -PiToolRoot $spec.PiToolRoot -VerifyOnly
    } else {
        & (Join-Path $PSScriptRoot 'Apply-PiSPost0841UpstreamCompatibility.ps1') -PiToolRoot $spec.PiToolRoot
    }
    $post0841UpstreamCompatibility = ($post0841Raw -join [Environment]::NewLine) | ConvertFrom-Json
}
if ($Profile -eq 'prime-s') {
    try {
        $numpadRaw = if ($ValidateOnly) {
            & (Join-Path $PSScriptRoot 'Set-PiSNumpadEnterFollow.ps1') -AgentDir $spec.AgentDir -ValidateOnly
        } else {
            & (Join-Path $PSScriptRoot 'Set-PiSNumpadEnterFollow.ps1') -AgentDir $spec.AgentDir
        }
        $numpadEnterFollow = ($numpadRaw -join [Environment]::NewLine) | ConvertFrom-Json
        $numpadHelperStatus = 'ready'
    } catch {
        # This shortcut is a convenience surface, never a prerequisite for Pi.
        $numpadHelperStatus = 'unavailable-nonblocking'
        $numpadEnterFollow = [pscustomobject]@{
            status = $numpadHelperStatus
            error = $_.Exception.Message
            helper_failure_blocks_pi = $false
        }
        if (-not $ValidateOnly) {
            Write-Warning "PiS 小键盘跟随辅助不可用；Pi 将按原生键位正常启动：$($_.Exception.Message)"
        }
    }
}
$authPath = Join-Path $spec.AgentDir 'auth.json'
$settingsPath = Join-Path $spec.AgentDir 'settings.json'
$agentsPath = Join-Path $spec.AgentDir 'AGENTS.md'
foreach ($required in @($spec.Workspace,$spec.SurfaceIsland,$spec.CodexHome,$spec.AgentsSource,$spec.CodexAuthSource,$spec.FamilyContractSource,$spec.SurfaceContractSource,$spec.ContractProjection,$spec.OverlayProjectionManifest,$spec.AccountBindingPath,$spec.AgentDir,$spec.SessionDir,$settingsPath,$agentsPath)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "PI_PROFILE_REQUIRED_PATH_MISSING: $required" }
}
& (Join-Path $PSScriptRoot 'Seed-PiCodexAuth.ps1') -Profile $Profile | Out-Null
if (-not (Test-PiDualEntryAuth -Path $authPath)) { throw "PI_PROFILE_AUTH_INVALID: $Profile" }
function Test-SelectedPiAuthReady {
    $raw = @(& $spec.PiCommand auth check --provider openai-codex --json 2>&1)
    if ($LASTEXITCODE -ne 0) { return $false }
    try {
        $result = ($raw -join [Environment]::NewLine) | ConvertFrom-Json
        return ([string]$result.status -eq 'ready' -and [string]$result.provider -eq 'openai-codex')
    } catch { return $false }
}
if (-not (Test-SelectedPiAuthReady)) {
    # Same-slot Pi OAuth can become terminal after the canonical Codex account refreshes. Repair
    # only this profile from its selected native source, then prove the real provider consumer.
    & (Join-Path $PSScriptRoot 'Seed-PiCodexAuth.ps1') -Profile $Profile -Force | Out-Null
    if (-not (Test-SelectedPiAuthReady)) { throw "PI_PROFILE_AUTH_NOT_READY_AFTER_RESEED: $Profile" }
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $agentsPath).Hash -ne (Get-FileHash -Algorithm SHA256 -LiteralPath $spec.AgentsSource).Hash) {
    throw "PI_PROFILE_AGENTS_PROJECTION_DRIFT: $Profile"
}

if ($ValidateOnly) {
    $node = Get-PiDualEntryNodeInfo
    [pscustomobject]@{
        profile = $Profile
        role = $spec.Role
        version = (& $spec.PiCommand --version | Select-Object -First 1)
        pi_tool_root = $spec.PiToolRoot
        node_version = $node.RawVersion
        node_path = $node.Path
        node_minimum = [string]$node.Minimum
        node_minimum_satisfied = $node.MinimumSatisfied
        workspace = $spec.Workspace
        agent_dir = $spec.AgentDir
        session_dir = $spec.SessionDir
        selected_session = $selectedSession
        auth_valid = $true
        agents_projection_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $agentsPath).Hash.ToLowerInvariant()
        contract_projection_sha256 = $contractProjection.Sha256
        surface_overlay_manifest_sha256 = $surfaceOverlay.Sha256
        supervisor_pipe = $spec.SupervisorPipe
        subagent_max_depth = [int]$env:PI_SUBAGENT_MAX_DEPTH
        subagent_capacity = $subagentCapacity
        subagent_capacity_static_policy = $subagentCapacityStaticPolicy
        subagents_windows_compatibility = $subagentsCompatibility
        subagents_owner_session_stop_compatibility = $subagentsOwnerSessionStopCompatibility
        subagents_filesystem_policy_compatibility = $subagentsFilesystemPolicyCompatibility
        high_capacity_compatibility = $highCapacityCompatibility
        high_capacity_absence = $highCapacityAbsence
        hermes_session_compatibility = $hermesSessionCompatibility
        midturn_compaction_compatibility = $midTurnCompactionCompatibility
        native_continuation_compatibility = $nativeContinuationCompatibility
        native_continuation_absence = $nativeContinuationAbsence
        post_0841_upstream_compatibility = $post0841UpstreamCompatibility
        midturn_compaction_runtime_enabled = (-not $DisableMidTurnCompactionCompatibility)
        native_continuation_runtime_enabled = $false
        high_capacity_runtime_enabled = $false
        numpad_enter_follow = $numpadEnterFollow
        family_contract = $spec.FamilyContractSource
        surface_island = $spec.SurfaceIsland
    } | ConvertTo-Json -Depth 4
    exit 0
}

function Stop-PiSNumpadEnterHelper {
    if ($Profile -ne 'prime-s') { return }
    $scriptNeedle = [string]$numpadHelperSource
    if ([string]::IsNullOrWhiteSpace($scriptNeedle)) { return }
    $victims = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -in @('AutoHotkey64.exe','AutoHotkey.exe') -and
        ([string]$_.CommandLine).IndexOf($scriptNeedle,[StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    foreach ($victim in $victims) {
        Stop-Process -Id ([int]$victim.ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

    Get-ChildItem Env: | Where-Object { $_.Name -like 'PRIME_AGENT_*' -or $_.Name -like 'RLM_*' } | ForEach-Object {
        Remove-Item -LiteralPath ("Env:" + $_.Name) -ErrorAction SilentlyContinue
    }
    if ($env:NODE_OPTIONS -match 'prime-agent|windows-compat|rlm-model-catalog-compat') {
        Remove-Item Env:NODE_OPTIONS -ErrorAction SilentlyContinue
    }

    if ($Profile -eq 'prime-s') {
        try { Stop-PiSNumpadEnterHelper } catch {
            Write-Warning "无法清理旧 PiS 小键盘辅助；Pi 将继续正常启动：$($_.Exception.Message)"
        }
        if ($numpadHelperStatus -eq 'ready') {
            try {
                $numpadHelperProcess = Start-Process -FilePath ([string]$numpadEnterFollow.autohotkey) -ArgumentList @($numpadHelperSource,'--owner-pid',[string]$PID) -WindowStyle Hidden -PassThru
                Start-Sleep -Milliseconds 150
                if ($numpadHelperProcess.HasExited) {
                    throw "helper exited with code $($numpadHelperProcess.ExitCode)"
                }
                $numpadHelperStatus = 'active'
            } catch {
                $numpadHelperStatus = 'unavailable-nonblocking'
                try { Stop-PiSNumpadEnterHelper } catch {}
                Write-Warning "PiS 小键盘跟随辅助启动失败；Pi 将按原生键位正常启动：$($_.Exception.Message)"
            }
        }
    }

    Clear-Host
    Write-Host "$($spec.DisplayName) | Pi $script:PiDualEntryVersion | $($spec.AccountDisplayName)" -ForegroundColor Cyan
    Write-Host "完整 Pi 主体 · $($spec.Profile) | 起点 $($spec.Workspace)" -ForegroundColor Green
    if ($Profile -eq 'prime-b') {
        Write-Host '隔离冷备快照；仅在明确恢复场景使用，不参与主 prime 的日常演化。' -ForegroundColor DarkGray
    } else {
        Write-Host '当前主要工作表面；直接服务真实事务并从实际使用中成熟。' -ForegroundColor DarkGray
        if ($numpadHelperStatus -eq 'active') {
            Write-Host '小键盘回车：鼠标在输入区时发送；在输出区时回到底部并恢复跟随。' -ForegroundColor DarkGray
        }
    }
    Write-Host ''

    Set-Location -LiteralPath $spec.Workspace
    $arguments = @(
        '--provider','openai-codex',
        '--model','gpt-5.6-sol',
        '--thinking','max',
        '--append-system-prompt',$spec.ContractProjection,
        '--session-dir',$spec.SessionDir,
        '--tui-mode','fullscreen'
    )
    if (@($spec.ExcludedTools).Count -gt 0) {
        $arguments += @('--exclude-tools',($spec.ExcludedTools -join ','))
    }
    if ($null -ne $selectedSession) {
        $arguments += @('--session',$selectedSession)
    } elseif (-not $NewSession) {
        $arguments += '--continue'
    }
    if ($Profile -eq 'prime-s' -and -not $DisableMidTurnCompactionCompatibility) {
        if ($null -eq $nativeContinuationCompatibility -or [string]$nativeContinuationCompatibility.schema -cne 'xinao.pi_native_continuation_compatibility.v1') {
            throw 'PI_S_NATIVE_CONTINUATION_RUNTIME_HANDSHAKE_WITHOUT_VERIFIED_CORE'
        }
        if ($null -eq $highCapacityCompatibility -or [string]$highCapacityCompatibility.schema -cne 'xinao.pi_s_high_capacity_compatibility.v1') {
            throw 'PI_S_HIGH_CAPACITY_RUNTIME_HANDSHAKE_WITHOUT_VERIFIED_PACKAGE_AND_CORE'
        }
        $env:XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE = '1'
        $subagentCapacityStaticPolicy = Enable-PiSubagentCapacityEnvironment -Profile $Profile
    }
    & $spec.PiCommand @arguments
    exit $LASTEXITCODE
} finally {
    Clear-PiSubagentCapacityEnvironment
    Remove-Item Env:XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE -ErrorAction SilentlyContinue
    if ($Profile -eq 'prime-s' -and $null -ne (Get-Command Stop-PiSNumpadEnterHelper -ErrorAction SilentlyContinue)) {
        try { Stop-PiSNumpadEnterHelper } catch { Write-Warning $_.Exception.Message }
    }
    if ($capacityCompatibilityHeld) { $capacityCompatibilityMutex.ReleaseMutex() }
    if ($null -ne $capacityCompatibilityMutex) { $capacityCompatibilityMutex.Dispose() }
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
