#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-s'),
    [string]$ReceiptPath = 'D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\acceptance\pi-cross-repository-context-v1.json'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

$targetRepository = 'E:\XINAO_RESEARCH_WORKSPACES\xinao-native-research'
$expectedRepositorySentinel = 'SENTINEL:XINAO_REALITY_DIRECT_TO_CURRENT_SOL_V2'
$expectedReadmeHeading = [Text.Encoding]::UTF8.GetString(
    [Convert]::FromBase64String('IyDmlrDmvrPnjrDlrp7jgIHor4Hmja7kuI7lsYDpg6jnoJTnqbblmajlrpg=')
)
$results = @()

foreach ($profileName in $Profile) {
    $spec = Get-PiDualEntrySpec -Profile $profileName
    Assert-PiDualEntryBinary -Spec $spec
    $env:PI_CODING_AGENT_DIR = $spec.AgentDir
    $env:PI_CODING_AGENT_SESSION_DIR = $spec.SessionDir
    $env:CODEX_HOME = $spec.CodexHome
    $env:PI_SKIP_VERSION_CHECK = '1'
    $env:PI_TELEMETRY = '0'

    # pi.cmd is a Windows cmd shim; embedded newlines in a positional prompt can be truncated at
    # the first physical line. Keep this transport deliberately single-line.
    $prompt = @(
        "This is a read-only cross-repository consumer probe. You start in $($spec.Workspace), but the named current object is $targetRepository."
        'Use the read tool now to read that repository AGENTS.md and README.md.'
        'Do not rely on prompt memory and do not edit anything.'
        'Return exactly one minified JSON object with keys repository_sentinel, readme_heading, local_context_read_via_tool, task_identity_created, effect_performed.'
        'Values must be the exact first sentinel from each file, true, false, false.'
    ) -join ' '

    Push-Location -LiteralPath $spec.Workspace
    try {
        $raw = @(& $spec.PiCommand --print --no-session --tools read --provider openai-codex --model gpt-5.6-sol --thinking max --append-system-prompt $spec.ContractProjection $prompt 2>&1)
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
        [string]$probe.readme_heading -ne $expectedReadmeHeading -or
        $probe.local_context_read_via_tool -ne $true -or
        $probe.task_identity_created -ne $false -or
        $probe.effect_performed -ne $false
    ) {
        throw "PI_CROSS_REPOSITORY_PROBE_MISMATCH: profile=$profileName text=$text"
    }
    $results += [ordered]@{
        profile = $profileName
        pi_tool_root = $spec.PiToolRoot
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
    schema = 'xinao.pi_cross_repository_context.acceptance.v2'
    status = 'verified'
    runtime_version = $script:PiDualEntryVersion
    results = $results
}
Write-PiDualEntryJsonAtomic -Path $ReceiptPath -Value $receipt
$receipt | ConvertTo-Json -Depth 8
