#Requires -Version 5.1
<#
.SYNOPSIS
  Codex A-leg peer: DeepSeek OpenAI-compatible worker.
.DESCRIPTION
  Thin profile over Invoke-CodexDispatchOpenAiRelayWorker.
  Default key handle = single active key (not multi-key file).
  Each call is one complete package; global concurrency remains a dynamic
  supervisor decision. Not Grok pool / not Temporal.
.EXAMPLE
  .\Invoke-CodexDispatchDeepSeekWorker.ps1 -WorkKey ds:smoke -Prompt "Reply only: DS_OK" -Model deepseek-chat -RequiredResultMarkers DS_OK
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
    # 默认 deepseek-chat（服务端常映射为 deepseek-v4-flash）；也可显式 deepseek-v4-flash / deepseek-v4-pro
    [string]$Model = "deepseek-chat",
    [ValidateSet("chat_completions", "responses")]
    [string]$ApiStyle = "chat_completions",
    [string]$BaseUrl = "https://api.deepseek.com/v1",
    [string]$KeyPath = "C:\Users\xx363\私钥\DeepSeek-api-key-active.txt",
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
    throw "DEEPSEEK_KEY_PATH_MISSING: $KeyPath"
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
