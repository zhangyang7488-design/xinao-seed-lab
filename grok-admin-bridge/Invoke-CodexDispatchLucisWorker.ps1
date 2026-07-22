#Requires -Version 5.1
<#
.SYNOPSIS
  Thin Lucis binding for the fixed OpenAI-compatible cognitive entry.
.DESCRIPTION
  Supplies replaceable provider defaults only. Work identity, cognitive audit
  contract, evidence ledger, and Owner authority remain in the neutral core.
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
    [string]$Model = "gpt-5.6-sol",
    [ValidateSet("chat_completions", "responses")]
    [string]$ApiStyle = "chat_completions",
    [string]$BaseUrl = "https://lucisapi.ai/v1",
    [string]$KeyPath = "C:\Users\xx363\私钥\lucis-Codex-api.txt",
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
$dispatch = Join-Path $PSScriptRoot "Invoke-CodexDispatchOpenAiRelayWorker.ps1"
if (-not (Test-Path -LiteralPath $dispatch -PathType Leaf)) {
    throw "RELAY_DISPATCH_MISSING: $dispatch"
}
if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
    throw "LUCIS_KEY_PATH_MISSING: $KeyPath"
}
$providerContractPath = Join-Path $PSScriptRoot "grok_lucis_relay_worker.v1.json"
$providerContractSha256 = (Get-FileHash -LiteralPath $providerContractPath -Algorithm SHA256).Hash.ToLowerInvariant()

$arguments = @{
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
    $arguments.PromptFile = $PromptFile
}
else {
    $arguments.Prompt = $Prompt
}

& $dispatch @arguments
exit $LASTEXITCODE
