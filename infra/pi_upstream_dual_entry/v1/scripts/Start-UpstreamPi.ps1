#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('prime-b','prime-s')][string]$Profile,
    [switch]$NewSession,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

Assert-PiDualEntryBinary
$spec = Get-PiDualEntrySpec -Profile $Profile
$env:PI_CODING_AGENT_DIR = $spec.AgentDir
$env:PI_CODING_AGENT_SESSION_DIR = $spec.SessionDir
$env:PI_SKIP_VERSION_CHECK = '1'
$env:PI_TELEMETRY = '0'
$env:PI_SUBAGENT_MAX_DEPTH = '2'
$env:CODEX_HOME = $spec.CodexHome
$env:XINAO_ACCOUNT_SLOT = $spec.AccountSlot
$env:XINAO_PI_ROLE = $spec.Role
$env:XINAO_REPO = $spec.Workspace
$env:XINAO_RUNTIME = 'D:\XINAO_RESEARCH_RUNTIME'
$contractProjection = Sync-PiDualEntryContractProjection -Spec $spec
$authPath = Join-Path $spec.AgentDir 'auth.json'
$settingsPath = Join-Path $spec.AgentDir 'settings.json'
$agentsPath = Join-Path $spec.AgentDir 'AGENTS.md'
foreach ($required in @($spec.Workspace,$spec.SurfaceIsland,$spec.CodexHome,$spec.AgentsSource,$spec.CodexAuthSource,$spec.FamilyContractSource,$spec.SurfaceContractSource,$spec.ContractProjection,$spec.AccountBindingPath,$spec.AgentDir,$spec.SessionDir,$settingsPath,$agentsPath)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "PI_PROFILE_REQUIRED_PATH_MISSING: $required" }
}
& (Join-Path $PSScriptRoot 'Seed-PiCodexAuth.ps1') -Profile $Profile | Out-Null
if (-not (Test-PiDualEntryAuth -Path $authPath)) { throw "PI_PROFILE_AUTH_INVALID: $Profile" }
function Test-SelectedPiAuthReady {
    $raw = @(& $script:PiDualEntryCommand auth check --provider openai-codex --json 2>&1)
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
        version = (& $script:PiDualEntryCommand --version | Select-Object -First 1)
        node_version = $node.RawVersion
        node_path = $node.Path
        node_minimum = [string]$node.Minimum
        node_minimum_satisfied = $node.MinimumSatisfied
        workspace = $spec.Workspace
        agent_dir = $spec.AgentDir
        session_dir = $spec.SessionDir
        auth_valid = $true
        agents_projection_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $agentsPath).Hash.ToLowerInvariant()
        contract_projection_sha256 = $contractProjection.Sha256
        family_contract = $spec.FamilyContractSource
        surface_island = $spec.SurfaceIsland
    } | ConvertTo-Json -Depth 4
    exit 0
}

$mutex = [Threading.Mutex]::new($false,$spec.MutexName)
$held = $false
try {
    try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) {
        Write-Host "$($spec.DisplayName) 已经开着；没有再启动第二个会话窗口。" -ForegroundColor Yellow
        exit 73
    }

    Get-ChildItem Env: | Where-Object { $_.Name -like 'PRIME_AGENT_*' -or $_.Name -like 'RLM_*' } | ForEach-Object {
        Remove-Item -LiteralPath ("Env:" + $_.Name) -ErrorAction SilentlyContinue
    }
    if ($env:NODE_OPTIONS -match 'prime-agent|windows-compat|rlm-model-catalog-compat') {
        Remove-Item Env:NODE_OPTIONS -ErrorAction SilentlyContinue
    }

    Clear-Host
    Write-Host "$($spec.DisplayName) | Pi $script:PiDualEntryVersion | $($spec.AccountDisplayName)" -ForegroundColor Cyan
    Write-Host "完整 Pi 主体 · $($spec.Profile) | 起点 $($spec.Workspace)" -ForegroundColor Green
    if ($Profile -eq 'prime-b') {
        Write-Host '最低可用与回退表面；保留真实工作能力，但不做与 prime S 对称的优化。' -ForegroundColor DarkGray
    } else {
        Write-Host '当前主要工作表面；直接服务真实事务并从实际使用中成熟。' -ForegroundColor DarkGray
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
    if (-not $NewSession) { $arguments += '--continue' }
    & $script:PiDualEntryCommand @arguments
    exit $LASTEXITCODE
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
