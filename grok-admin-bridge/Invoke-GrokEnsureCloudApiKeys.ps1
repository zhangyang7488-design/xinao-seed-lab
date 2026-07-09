#Requires -Version 5.1
<#
.SYNOPSIS
  云 API 密钥预检：私钥库 vault → .env → shell/User → 网关容器。
  合同：grok_user_api_secrets_vault.v1.json
  不泄露密钥原文；只报 SET/MISSING 与下一动作。
#>
param(
    [string]$ConfigPath = "",
    [string]$SRepo = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
if (Test-Path $ConfigPath) {
    $cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.repo_root) { $SRepo = [string]$cfg.repo_root }
}

function Test-KeyPresent([string]$Name, [string]$Value) {
    return -not [string]::IsNullOrWhiteSpace($Value)
}

function Mask-Len([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return 0 }
    return $Value.Length
}

$vaultDash = ""
$vaultDeep = ""
$vaultScript = Join-Path $bridge "Resolve-GrokUserApiSecrets.ps1"
if (Test-Path $vaultScript) {
    try {
        $vr = & $vaultScript -Quiet
        if ($vr.DASHSCOPE_API_KEY.present) { $vaultDash = "present" }
        if ($vr.DEEPSEEK_API_KEY.present) { $vaultDeep = "present" }
    }
    catch {}
}

$sources = [ordered]@{}
$sources.vault_dashscope = $vaultDash
$sources.vault_deepseek = $vaultDeep
$sources.shell_dashscope = $env:DASHSCOPE_API_KEY
$sources.shell_deepseek = $env:DEEPSEEK_API_KEY
$sources.user_dashscope = [Environment]::GetEnvironmentVariable("DASHSCOPE_API_KEY", "User")
$sources.user_deepseek = [Environment]::GetEnvironmentVariable("DEEPSEEK_API_KEY", "User")

$envFile = Join-Path $SRepo ".env"
$dotDash = ""
$dotDeep = ""
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        if ($line -match '^\s*DASHSCOPE_API_KEY\s*=\s*(.+)\s*$') { $dotDash = $Matches[1].Trim().Trim('"').Trim("'") }
        if ($line -match '^\s*DEEPSEEK_API_KEY\s*=\s*(.+)\s*$') { $dotDeep = $Matches[1].Trim().Trim('"').Trim("'") }
    }
}
$sources.dotenv_dashscope = $dotDash
$sources.dotenv_deepseek = $dotDeep

$containerDash = ""
$containerDeep = ""
try {
    $cDash = docker exec moxing-wangguan sh -c 'printf "%s" "${DASHSCOPE_API_KEY:-}"' 2>$null
    $cDeep = docker exec moxing-wangguan sh -c 'printf "%s" "${DEEPSEEK_API_KEY:-}"' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $containerDash = [string]$cDash
        $containerDeep = [string]$cDeep
    }
}
catch {}
$sources.container_dashscope = $containerDash
$sources.container_deepseek = $containerDeep

$dashOk = ($vaultDash -eq "present") -or @(
    $sources.shell_dashscope,
    $sources.user_dashscope,
    $sources.dotenv_dashscope,
    $sources.container_dashscope
) | Where-Object { Test-KeyPresent "x" $_ } | Select-Object -First 1

$deepOk = ($vaultDeep -eq "present") -or @(
    $sources.shell_deepseek,
    $sources.user_deepseek,
    $sources.dotenv_deepseek,
    $sources.container_deepseek
) | Where-Object { Test-KeyPresent "x" $_ } | Select-Object -First 1

$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
$outDir = Join-Path $runtime "state\cloud_api_keys_preflight"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$actions = [System.Collections.Generic.List[string]]::new()
if (-not $dashOk -or -not $deepOk) {
    [void]$actions.Add("检查 C:\Users\xx363\私钥 内千问/DeepSeek 文件是否存在且可读")
    [void]$actions.Add(".\Invoke-GrokSyncCloudApiKeysToCompose.ps1 -RecreateGateway")
}
elseif ($sources.container_dashscope -eq "" -or $sources.container_deepseek -eq "") {
    [void]$actions.Add("vault 有密钥但容器未注入 → .\Invoke-GrokSyncCloudApiKeysToCompose.ps1 -RecreateGateway")
}
if ($actions.Count -gt 0) {
    [void]$actions.Add("Invoke-GrokCodexSDirectWorkerLane.ps1 -Provider qwen -Mode draft -Objective 烟测")
}

$out = [ordered]@{
    schema_version           = "xinao.grok_cloud_api_keys_preflight.v1"
    sentinel                 = "SENTINEL:GROK_CLOUD_API_KEYS_PREFLIGHT"
    generated_at             = (Get-Date).ToString("o")
    dashscope_present        = [bool]$dashOk
    deepseek_present         = [bool]$deepOk
    all_cloud_keys_ready     = ([bool]$dashOk -and [bool]$deepOk)
    completion_claim_allowed = $false
    vault_root               = "C:\Users\xx363\私钥"
    vault_contract           = "grok_user_api_secrets_vault.v1.json"
    vault_dashscope_present  = ($vaultDash -eq "present")
    vault_deepseek_present   = ($vaultDeep -eq "present")
    key_len_hint             = [ordered]@{
        vault_dashscope    = if ($vaultDash -eq "present") { 1 } else { 0 }
        vault_deepseek     = if ($vaultDeep -eq "present") { 1 } else { 0 }
        shell_dashscope    = (Mask-Len $sources.shell_dashscope)
        shell_deepseek     = (Mask-Len $sources.shell_deepseek)
        user_dashscope     = (Mask-Len $sources.user_dashscope)
        user_deepseek      = (Mask-Len $sources.user_deepseek)
        dotenv_dashscope   = (Mask-Len $sources.dotenv_dashscope)
        dotenv_deepseek    = (Mask-Len $sources.dotenv_deepseek)
        container_dashscope = (Mask-Len $sources.container_dashscope)
        container_deepseek  = (Mask-Len $sources.container_deepseek)
    }
    env_example              = (Join-Path $SRepo ".env.example")
    dotenv_path              = $envFile
    dotenv_exists            = (Test-Path $envFile)
    named_blocker            = if (-not $dashOk -or -not $deepOk) { "CLOUD_API_KEYS_MISSING" } else { "" }
    next_actions_cn          = @($actions)
}

$latest = Join-Path $outDir "latest.json"
$out | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $latest -Encoding UTF8
if (-not $Quiet) { $out | ConvertTo-Json -Depth 6 }
if (-not $out.all_cloud_keys_ready) { exit 2 }
exit 0