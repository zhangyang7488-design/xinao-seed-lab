#Requires -Version 5.1
<#
.SYNOPSIS
  从私钥库提取 API 句柄 → 合并写入 S 仓 .env（不抹掉 Langfuse/compose 其余项）。
  不向聊天/证据写密钥原文。
#>
param(
    [string]$ConfigPath = "",
    [string]$SRepo = "",
    [switch]$RecreateGateway,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
if (Test-Path $ConfigPath) {
    $cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.repo_root) { $SRepo = [string]$cfg.repo_root }
}
if (-not $SRepo) { $SRepo = "E:\XINAO_RESEARCH_WORKSPACES\S" }

$resolved = & (Join-Path $bridge "Resolve-GrokUserApiSecrets.ps1") -SetProcessEnv -Quiet
$dash = ""
$deep = ""
$exa = ""
$serper = ""
if ($resolved.DASHSCOPE_API_KEY.present) { $dash = [string]$resolved.DASHSCOPE_API_KEY.value }
if ($resolved.DEEPSEEK_API_KEY.present) { $deep = [string]$resolved.DEEPSEEK_API_KEY.value }
if ($resolved.EXA_API_KEY.present) { $exa = [string]$resolved.EXA_API_KEY.value }
if ($resolved.SERPER_API_KEY.present) { $serper = [string]$resolved.SERPER_API_KEY.value }

$missing = @()
if (-not $dash) { $missing += "DASHSCOPE_API_KEY" }
if (-not $deep) { $missing += "DEEPSEEK_API_KEY" }

$envPath = Join-Path $SRepo ".env"
$examplePath = Join-Path $SRepo ".env.example"
$master = $env:LITELLM_MASTER_KEY
if (-not $master) { $master = "sk-xinao-thin-glue-local" }

$vaultManaged = [ordered]@{
    DASHSCOPE_API_KEY = $dash
    DEEPSEEK_API_KEY  = $deep
    EXA_API_KEY       = $exa
    SERPER_API_KEY    = $serper
}

function Read-DotenvMap([string]$Path) {
    $map = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^\s*#' -or [string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -match '^([^=]+)=(.*)$') {
            $map[$Matches[1].Trim()] = $Matches[2]
        }
    }
    return $map
}

$merged = @{}
if (Test-Path -LiteralPath $examplePath) {
    foreach ($kv in (Read-DotenvMap $examplePath).GetEnumerator()) { $merged[$kv.Key] = $kv.Value }
}
foreach ($kv in (Read-DotenvMap $envPath).GetEnumerator()) {
    if (-not [string]::IsNullOrWhiteSpace([string]$kv.Value)) { $merged[$kv.Key] = $kv.Value }
}
foreach ($kv in $vaultManaged.GetEnumerator()) {
    if ($kv.Key -eq "LITELLM_MASTER_KEY") { continue }
    if ([string]::IsNullOrWhiteSpace([string]$kv.Value)) { continue }
    $merged[$kv.Key] = [string]$kv.Value
}
if (-not $merged.Contains("LITELLM_MASTER_KEY") -or [string]::IsNullOrWhiteSpace([string]$merged["LITELLM_MASTER_KEY"])) {
    $merged["LITELLM_MASTER_KEY"] = $master
}

$outLines = @(
    "# AUTO-MERGED from user secrets vault — do not commit",
    "# Contract: grok_user_api_secrets_vault.v1.json",
    "# Generated: $((Get-Date).ToString('o'))",
    "# 合并写入：仅覆盖 vault 管理项，保留 Langfuse/compose 其余变量"
)
foreach ($kv in $merged.GetEnumerator()) {
    $outLines += ("{0}={1}" -f $kv.Key, $kv.Value)
}
$outLines -join "`n" | Set-Content -LiteralPath $envPath -Encoding UTF8 -NoNewline
Add-Content -LiteralPath $envPath -Value "" -Encoding UTF8

$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
$outDir = Join-Path $runtime "state\cloud_api_keys_sync"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$recreateOk = $false
$recreateMsg = ""
if ($RecreateGateway -and $missing.Count -eq 0) {
    Push-Location $SRepo
    try {
        docker compose up -d moxing-wangguan --force-recreate 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $recreateOk = $true }
        else { $recreateMsg = "docker compose exit $LASTEXITCODE" }
    }
    catch { $recreateMsg = $_.Exception.Message }
    finally { Pop-Location }
}

$out = [ordered]@{
    schema_version           = "xinao.grok_cloud_api_keys_sync.v1"
    sentinel                 = "SENTINEL:GROK_CLOUD_API_KEYS_SYNC"
    generated_at             = (Get-Date).ToString("o")
    vault_contract           = "grok_user_api_secrets_vault.v1.json"
    dotenv_path              = $envPath
    merge_mode               = "vault_keys_only_preserve_compose"
    dashscope_present        = [bool]$dash
    deepseek_present         = [bool]$deep
    exa_present              = [bool]$exa
    serper_present           = [bool]$serper
    missing_env_vars         = @($missing)
    recreate_gateway         = [bool]$RecreateGateway
    recreate_ok              = $recreateOk
    recreate_msg             = $recreateMsg
    completion_claim_allowed = $false
    reveal_value_no          = $true
}
$out | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outDir "latest.json") -Encoding UTF8

if (-not $Quiet) { $out | ConvertTo-Json -Depth 5 }
if ($missing.Count -gt 0) { exit 2 }
exit 0