#Requires -Version 5.1
<#
.SYNOPSIS
  从用户私钥库 C:\Users\xx363\私钥 提取 API 句柄（仅进程内；禁止泄露原文）。
  合同：grok_user_api_secrets_vault.v1.json
#>
param(
    [string]$VaultContractPath = "",
    [string[]]$EnvVars = @(),
    [switch]$SetProcessEnv,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
if (-not $VaultContractPath) {
    $VaultContractPath = Join-Path $bridge "grok_user_api_secrets_vault.v1.json"
}
if (-not (Test-Path -LiteralPath $VaultContractPath)) {
    throw "Vault contract missing: $VaultContractPath"
}

$contract = Get-Content -LiteralPath $VaultContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$vaultRoot = [string]$contract.vault_root

function Get-KeyLen([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return 0 }
    return $Value.Length
}

function Read-DashscopeFromTxt([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ($raw -match 'key-+\s*(sk-[^\s\r\n]+)') { return $Matches[1].Trim() }
    if ($raw -match '(sk-[^\s\r\n]+)') { return $Matches[1].Trim() }
    return ""
}

function Read-DashscopeFromCsv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^apiKey,(sk-[^\s,]+)') { return $Matches[1].Trim() }
    }
    return ""
}

function Read-SkFirstLine([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $t = $line.Trim()
        if ($t -match '^(sk-[^\s#]+)') { return $Matches[1].Trim() }
    }
    return ""
}

function Read-KeyAfterMarker([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ($raw -match 'key-+\s*([^\s\r\n]+)') { return $Matches[1].Trim() }
    return $raw.Trim()
}

function Read-WholeTrim([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Trim()
}

function Resolve-VaultEntry($Entry) {
    $primary = Join-Path $vaultRoot ([string]$Entry.primary_file)
    $value = ""
    $source = ""
    $envName = [string]$Entry.env_var

    switch ($envName) {
        "DASHSCOPE_API_KEY" {
            $value = Read-DashscopeFromTxt $primary
            if ($value) { $source = [string]$Entry.primary_file }
            if (-not $value) {
                foreach ($fb in @($Entry.fallback_files)) {
                    $fp = Join-Path $vaultRoot ([string]$fb)
                    $value = Read-DashscopeFromCsv $fp
                    if ($value) { $source = [string]$fb; break }
                }
            }
        }
        "DEEPSEEK_API_KEY" {
            $value = Read-SkFirstLine $primary
            if ($value) { $source = [string]$Entry.primary_file }
        }
        "SERPER_API_KEY" {
            $value = Read-KeyAfterMarker $primary
            if ($value) { $source = [string]$Entry.primary_file }
        }
        "EXA_API_KEY" {
            $value = Read-KeyAfterMarker $primary
            if ($value) { $source = [string]$Entry.primary_file }
        }
        "CLOUDFLARE_API_TOKEN" {
            $value = Read-WholeTrim $primary
            if ($value) { $source = [string]$Entry.primary_file }
            if (-not $value) {
                foreach ($fb in @($Entry.fallback_files)) {
                    $fp = Join-Path $vaultRoot ([string]$fb)
                    $value = Read-WholeTrim $fp
                    if ($value) { $source = [string]$fb; break }
                }
            }
        }
        "COMMAND_SHARED_SECRET" {
            $value = Read-WholeTrim $primary
            if ($value) { $source = [string]$Entry.primary_file }
            if (-not $value) {
                foreach ($fb in @($Entry.fallback_files)) {
                    $fp = Join-Path $vaultRoot ([string]$fb)
                    $value = Read-WholeTrim $fp
                    if ($value) { $source = [string]$fb; break }
                }
            }
        }
        default {
            $value = Read-WholeTrim $primary
            if ($value) { $source = [string]$Entry.primary_file }
        }
    }

    return [ordered]@{
        id           = [string]$Entry.id
        env_var      = $envName
        present      = -not [string]::IsNullOrWhiteSpace($value)
        source_file  = $source
        source_path  = if ($source) { Join-Path $vaultRoot $source } else { "" }
        key_len      = (Get-KeyLen $value)
        value        = $value
    }
}

$resolved = [ordered]@{}
foreach ($entry in @($contract.entries)) {
    $r = Resolve-VaultEntry $entry
    $resolved[[string]$entry.env_var] = $r
    if ($SetProcessEnv -and $r.present) {
        Set-Item -Path "Env:$($r.env_var)" -Value ([string]$r.value)
    }
}

if ($EnvVars.Count -gt 0) {
    $pick = [ordered]@{}
    foreach ($name in $EnvVars) {
        if ($resolved.Contains($name)) {
            $item = $resolved[$name]
            $pick[$name] = [ordered]@{
                present     = $item.present
                source_file = $item.source_file
                key_len     = $item.key_len
            }
        }
    }
    if (-not $Quiet) { $pick | ConvertTo-Json -Depth 4 }
    return $pick
}

# 默认返回无 value 字段的安全视图
$safe = [ordered]@{}
foreach ($kv in $resolved.Keys) {
    $item = $resolved[$kv]
    $safe[$kv] = [ordered]@{
        id          = $item.id
        present     = $item.present
        source_file = $item.source_file
        source_path = $item.source_path
        key_len     = $item.key_len
    }
}

$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\user_api_secrets_vault"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$evidence = [ordered]@{
    schema_version           = "xinao.grok_user_api_secrets_vault_resolve.v1"
    sentinel                 = "SENTINEL:GROK_USER_API_SECRETS_VAULT_RESOLVE"
    generated_at             = (Get-Date).ToString("o")
    vault_root               = $vaultRoot
    vault_contract           = $VaultContractPath
    completion_claim_allowed = $false
    reveal_value_no          = $true
    entries                  = $safe
}
$evidence | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outDir "latest.json") -Encoding UTF8

if (-not $Quiet) { $safe | ConvertTo-Json -Depth 5 }
return $resolved