#Requires -Version 5.1
<#
.SYNOPSIS
  Codex A-leg peer: 阿里云百炼 / 通义千问 (OpenAI-compatible).
.DESCRIPTION
  Thin profile over Invoke-CodexDispatchOpenAiRelayWorker.
  Default key = Bailian workspace CSV export (apiKey + openAiCompatible).
  Does NOT enter Grok WorkerPool. Not Temporal/333. Each call is one complete
  package; global concurrency remains a dynamic supervisor decision.
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

# If BaseUrl omitted, worker will pull openAiCompatible from CSV.
if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = "https://api.ssstoken.net/v1" # sentinel; worker replaces from CSV when KeyPath is .csv
}

$args = @{
    N = 1
    WorkKey = $WorkKey
    Attempt = $Attempt
    LogicalOperationId = $LogicalOperationId
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
