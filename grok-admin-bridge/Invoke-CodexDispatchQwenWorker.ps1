#Requires -Version 5.1
<#
.SYNOPSIS
  Thin 阿里云百炼 / 通义千问 binding for the fixed cognitive entry.
.DESCRIPTION
  Thin profile over Invoke-CodexDispatchOpenAiRelayWorker.
  Default key = Bailian workspace CSV export (apiKey + openAiCompatible).
  It supplies replaceable provider defaults only. Each call is one complete
  package; the neutral core owns work identity and audit semantics.
.EXAMPLE
  .\Invoke-CodexDispatchQwenWorker.ps1 -WorkKey qwen:smoke -Prompt "只回复: QWEN_OK" -Model qwen-plus -RequiredResultMarkers QWEN_OK
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$WorkKey,
    [ValidateRange(1, 2147483647)]
    [int]$Attempt = 1,
    [string]$LogicalOperationId = "",
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [ValidateSet("general_cognitive", "cognitive_audit")]
    [string]$WorkClass = "general_cognitive",
    [string]$ContextManifestFile = "",
    [string]$ExpectedContextManifestSha256 = "",
    [string]$JsonSchemaPath = "",
    [string]$ExpectedJsonSchemaSha256 = "",
    [string]$Model = "qwen-plus",
    [ValidateSet("chat_completions", "responses")]
    [string]$ApiStyle = "chat_completions",
    [string]$BaseUrl = "",
    [string]$KeyPath = "C:\Users\xx363\私钥\千问默认业务空间-apiKey-5983797.csv",
    [string]$PythonExe = "",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [ValidateRange(1, 200000)]
    [int]$MaxTokens = 2048,
    [ValidateRange(1, 86400)]
    [int]$TimeoutSec = 120,
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 1,
    [string[]]$RequiredResultMarkers = @(),
    [string]$DispatchId = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$dispatch = Join-Path $bridge "Invoke-CodexDispatchOpenAiRelayWorker.ps1"
if (-not (Test-Path -LiteralPath $dispatch -PathType Leaf)) {
    throw "RELAY_DISPATCH_MISSING: $dispatch"
}
if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
    throw "QWEN_KEY_PATH_MISSING: $KeyPath"
}

# Resolve the provider endpoint from the bound workspace export before entering
# the neutral core. The core never carries a provider-specific fallback.
if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $rawBinding = [IO.File]::ReadAllText($KeyPath, [Text.UTF8Encoding]::new($false))
    foreach ($line in ($rawBinding -split "`r?`n")) {
        if ($line -match '^\s*openAiCompatible\s*,\s*(.+)\s*$') {
            $BaseUrl = $Matches[1].Trim().Trim('"').Trim("'")
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
        throw "QWEN_OPENAI_COMPATIBLE_BASE_URL_MISSING: $KeyPath"
    }
}
$providerContractPath = Join-Path $PSScriptRoot "grok_qwen_bailian_relay_worker.v1.json"
$providerContractSha256 = (Get-FileHash -LiteralPath $providerContractPath -Algorithm SHA256).Hash.ToLowerInvariant()

$args = @{
    N = 1
    WorkKey = $WorkKey
    Attempt = $Attempt
    LogicalOperationId = $LogicalOperationId
    WorkClass = $WorkClass
    ProviderContractPath = $providerContractPath
    ExpectedProviderContractSha256 = $providerContractSha256
    ContextManifestFile = $ContextManifestFile
    ExpectedContextManifestSha256 = $ExpectedContextManifestSha256
    JsonSchemaPath = $JsonSchemaPath
    ExpectedJsonSchemaSha256 = $ExpectedJsonSchemaSha256
    Model = $Model
    ApiStyle = $ApiStyle
    BaseUrl = $BaseUrl
    KeyPath = $KeyPath
    PythonExe = $PythonExe
    RuntimeRoot = $RuntimeRoot
    MaxTokens = $MaxTokens
    TimeoutSec = $TimeoutSec
    MinResultChars = $MinResultChars
    RequiredResultMarkers = $RequiredResultMarkers
    DispatchId = $DispatchId
    Quiet = $Quiet
}
if (-not [string]::IsNullOrWhiteSpace($PromptFile)) {
    $args.PromptFile = $PromptFile
}
else {
    $args.Prompt = $Prompt
}

& $dispatch @args
exit $LASTEXITCODE
