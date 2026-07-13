[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ResultPath,
    [ValidateSet(
        'productivity',
        'topology',
        'external_effect',
        'continuity',
        'authorization',
        'preference_learning',
        'worker_routing',
        'capability_admission',
        'mature_first',
        'control_plane',
        'incident_lifecycle'
    )]
    [string]$FallbackDomain = 'productivity',
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' })
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
    throw "Promptfoo result is missing: $ResultPath"
}
$resolvedResult = (Resolve-Path -LiteralPath $ResultPath).Path
$document = Get-Content -LiteralPath $resolvedResult -Raw | ConvertFrom-Json
$rows = @($document.results.results)
$failures = @($rows | Where-Object { $_.success -ne $true })
if (-not $failures) {
    Write-Output '[]'
    return
}

$newCandidate = Join-Path $PSScriptRoot 'New-BehaviorRegressionCandidate.ps1'
$created = @()
foreach ($row in $failures) {
    $caseId = [string]$row.vars.case_id
    if (-not $caseId) { $caseId = [string]$row.testCase.description }
    $safeCase = ($caseId.ToUpperInvariant() -replace '[^A-Z0-9_]', '_').Trim('_')
    if ($safeCase.Length -gt 54) { $safeCase = $safeCase.Substring(0, 54) }
    $identity = "$resolvedResult|$caseId|$($row.id)"
    $hashBytes = [System.Security.Cryptography.SHA256]::HashData(
        [System.Text.Encoding]::UTF8.GetBytes($identity)
    )
    $hash = [Convert]::ToHexString($hashBytes).ToLowerInvariant()
    $candidateId = "REG_FAIL_${safeCase}_$($hash.Substring(0, 12).ToUpperInvariant())"
    $operationId = [guid]::new([byte[]]$hashBytes[0..15]).ToString()
    $domain = [string]$row.vars.domain
    if (-not $domain) { $domain = [string]$row.testCase.metadata.domain }
    if (-not $domain) { $domain = $FallbackDomain }
    $traceId = [string]$row.response.metadata.codexAppServer.threadId
    $turnId = [string]$row.response.metadata.codexAppServer.turnId
    $traceRefs = @("promptfoo-result:$resolvedResult#row=$($row.id)")
    if ($traceId) { $traceRefs += "codex-thread:$traceId" }
    if ($turnId) { $traceRefs += "codex-turn:$turnId" }
    $expected = [ordered]@{}
    foreach ($property in $row.vars.PSObject.Properties) {
        if ($property.Name -like 'expected_*') {
            $expected[$property.Name] = $property.Value
        }
    }
    $observed = [string]($row.error ?? $row.gradingResult.reason ?? 'Promptfoo case failed.')
    if ($observed.Length -gt 1900) { $observed = $observed.Substring(0, 1900) }
    $desired = ($expected | ConvertTo-Json -Compress -Depth 8)
    if ($desired.Length -gt 1900) { $desired = $desired.Substring(0, 1900) }
    $path = & $newCandidate `
        -Id $candidateId `
        -OperationId $operationId `
        -SourceType observed_failure `
        -SourceRef "promptfoo:$resolvedResult#row=$($row.id)" `
        -Domain $domain `
        -ObservedOutcome $observed `
        -DesiredOutcome $desired `
        -RestoredContext ([string]$row.vars.restored_context) `
        -UserIncrement ([string]$row.vars.user_increment) `
        -TraceRefs $traceRefs `
        -RuntimeRoot $RuntimeRoot
    $created += $path
}
ConvertTo-Json -InputObject @($created)
