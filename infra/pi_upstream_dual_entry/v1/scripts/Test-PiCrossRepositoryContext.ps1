#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-s'),
    [string]$ReceiptPath = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\acceptance\pi-cross-repository-context-v1.json'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

Assert-PiDualEntryBinary
$targetRepository = 'E:\XINAO_RESEARCH_WORKSPACES\xinao-native-research'
$expectedRepositorySentinel = 'SENTINEL:XINAO_NATIVE_RESEARCH_ROLE_V2'
$expectedStatusSentinel = 'SENTINEL:XINAO_CURRENT_PROJECTION_V7'
$results = @()

foreach ($profileName in $Profile) {
    $spec = Get-PiDualEntrySpec -Profile $profileName
    $env:PI_CODING_AGENT_DIR = $spec.AgentDir
    $env:PI_CODING_AGENT_SESSION_DIR = $spec.SessionDir
    $env:CODEX_HOME = $spec.CodexHome
    $env:PI_SKIP_VERSION_CHECK = '1'
    $env:PI_TELEMETRY = '0'

    # pi.cmd is a Windows cmd shim; embedded newlines in a positional prompt can be truncated at
    # the first physical line. Keep this transport deliberately single-line.
    $prompt = @(
        "This is a read-only cross-repository consumer probe. You start in $($spec.Workspace), but the named current object is $targetRepository."
        'Use the read tool now to read that repository AGENTS.md and STATUS.md.'
        'Do not rely on prompt memory and do not edit anything.'
        'Return exactly one minified JSON object with keys repository_sentinel, status_sentinel, local_context_read_via_tool, task_identity_created, effect_performed.'
        'Values must be the exact first sentinel from each file, true, false, false.'
    ) -join ' '

    Push-Location -LiteralPath $spec.Workspace
    try {
        $raw = @(& $script:PiDualEntryCommand --print --no-session --tools read --provider openai-codex --model gpt-5.6-sol --thinking max --append-system-prompt $spec.ContractProjection $prompt 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "PI_CROSS_REPOSITORY_PROBE_FAILED: profile=$profileName output=$($raw -join ' ')"
        }
    } finally {
        Pop-Location
    }
    $text = ($raw -join [Environment]::NewLine).Trim()
    try { $probe = $text | ConvertFrom-Json } catch {
        throw "PI_CROSS_REPOSITORY_PROBE_JSON_INVALID: profile=$profileName text=$text"
    }
    if (
        [string]$probe.repository_sentinel -ne $expectedRepositorySentinel -or
        [string]$probe.status_sentinel -ne $expectedStatusSentinel -or
        $probe.local_context_read_via_tool -ne $true -or
        $probe.task_identity_created -ne $false -or
        $probe.effect_performed -ne $false
    ) {
        throw "PI_CROSS_REPOSITORY_PROBE_MISMATCH: profile=$profileName text=$text"
    }
    $results += [ordered]@{
        profile = $profileName
        starting_workspace = $spec.Workspace
        named_object = $targetRepository
        model = 'openai-codex/gpt-5.6-sol'
        thinking = 'max'
        session = 'fresh-no-session'
        tools = @('read')
        result = $probe
    }
}

$receipt = [ordered]@{
    schema = 'xinao.pi_cross_repository_context.acceptance.v1'
    status = 'verified'
    runtime_version = $script:PiDualEntryVersion
    results = $results
}
Write-PiDualEntryJsonAtomic -Path $ReceiptPath -Value $receipt
$receipt | ConvertTo-Json -Depth 8
