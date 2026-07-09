#Requires -Version 5.1
<#
.SYNOPSIS
  从私钥库提取 DASHSCOPE/DEEPSEEK → 写 S 仓 .env → 可选重启 moxing-wangguan。
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
if ($resolved.DASHSCOPE_API_KEY.present) { $dash = [string]$resolved.DASHSCOPE_API_KEY.value }
if ($resolved.DEEPSEEK_API_KEY.present) { $deep = [string]$resolved.DEEPSEEK_API_KEY.value }

$missing = @()
if (-not $dash) { $missing += "DASHSCOPE_API_KEY" }
if (-not $deep) { $missing += "DEEPSEEK_API_KEY" }

$envPath = Join-Path $SRepo ".env"
$master = $env:LITELLM_MASTER_KEY
if (-not $master) { $master = "sk-xinao-thin-glue-local" }

$lines = @(
    "# AUTO-GENERATED from user secrets vault — do not commit",
    "# Contract: grok_user_api_secrets_vault.v1.json",
    "# Generated: $((Get-Date).ToString('o'))",
    "DASHSCOPE_API_KEY=$dash",
    "DEEPSEEK_API_KEY=$deep",
    "LITELLM_MASTER_KEY=$master"
)
$lines -join "`n" | Set-Content -LiteralPath $envPath -Encoding UTF8 -NoNewline
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
    dashscope_present        = [bool]$dash
    deepseek_present         = [bool]$deep
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