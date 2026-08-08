#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PiToolRoot,
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

function Get-NormalizedPiSCorePath {
    param([Parameter(Mandatory)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

$target = Get-NormalizedPiSCorePath -Path $PiToolRoot
$mainTarget = Get-NormalizedPiSCorePath -Path $script:PiDualEntryMainToolRoot
$backupTarget = Get-NormalizedPiSCorePath -Path $script:PiDualEntryBackupToolRoot
$labParent = Get-NormalizedPiSCorePath -Path (Join-Path $script:PiDualEntryStateRoot 'body-labs\prime-s')
$labPrefix = $labParent + [IO.Path]::DirectorySeparatorChar
$isLabCore = $false
if ($target.StartsWith($labPrefix,[StringComparison]::OrdinalIgnoreCase)) {
    $relative = $target.Substring($labPrefix.Length)
    $segments = @($relative.Split([IO.Path]::DirectorySeparatorChar,[StringSplitOptions]::RemoveEmptyEntries))
    $isLabCore = ($segments.Count -eq 2 -and $segments[1] -ceq 'pi-tool-root')
}
if ($target -notin @($mainTarget,$backupTarget) -and -not $isLabCore) {
    throw "PI_S_MIDTURN_PATCH_TARGET_OUTSIDE_MANAGED_CORE_OR_BODY_LAB: $target"
}

$packageRoot = Join-Path $target 'node_modules\@earendil-works\pi-coding-agent'
$packageJsonPath = Join-Path $packageRoot 'package.json'
$sourcePath = Join-Path $packageRoot 'dist\core\agent-session.js'
foreach ($required in @($packageJsonPath,$sourcePath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "PI_S_MIDTURN_PATCH_SOURCE_MISSING: $required"
    }
}

$package = Get-Content -Raw -LiteralPath $packageJsonPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$package.name -cne '@earendil-works/pi-coding-agent' -or [string]$package.version -cne '0.84.1') {
    throw "PI_S_MIDTURN_PATCH_VERSION_UNSUPPORTED: $($package.name)@$($package.version)"
}

$upstreamHash = '91e72d5497f665e731cbd79da6a6e826d8cae7d2ce156a7dee39f8ca205e32c8'
$patchedHash = '3d42e3311f1b7b5b72aa81dd745cf7a8e089e9b7708abe5e33b9b553651739e6'
$preimagePath = Join-Path $target 'xinao-compatibility-preimages\pi-coding-agent-0.84.1-agent-session.upstream.js'
$beforeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
$changed = $false

if ($beforeHash -ceq $upstreamHash) {
    if ($VerifyOnly) {
        throw "PI_S_MIDTURN_PATCH_NOT_APPLIED: $sourcePath"
    }
    if (Test-Path -LiteralPath $preimagePath -PathType Leaf) {
        $preimageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $preimagePath).Hash.ToLowerInvariant()
        if ($preimageHash -cne $upstreamHash) {
            throw "PI_S_MIDTURN_PATCH_PREIMAGE_CONFLICT: expected=$upstreamHash actual=$preimageHash"
        }
    } else {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $preimagePath) | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $preimagePath
    }
    $source = [IO.File]::ReadAllText($sourcePath,[Text.UTF8Encoding]::new($false))
    $fieldAnchor = @(
        '    _autoCompactionAbortController = undefined;'
        '    _overflowRecoveryAttempted = false;'
        '    // Branch summarization state'
    ) -join "`n"
    $fieldReplacement = @(
        '    _autoCompactionAbortController = undefined;'
        '    _overflowRecoveryAttempted = false;'
        '    // True only after the loop stopped at a completed tool-result boundary.'
        '    _midTurnCompactionRequested = false;'
        '    // Branch summarization state'
    ) -join "`n"
    $constructorAnchor = @(
        '        this._installAgentToolHooks();'
        '        this._installAgentNextTurnRefresh();'
        '        this._buildRuntime({'
    ) -join "`n"
    $constructorReplacement = @(
        '        this._installAgentToolHooks();'
        '        this._installAgentNextTurnRefresh();'
        '        this._installMidTurnCompactionBackpressure();'
        '        this._buildRuntime({'
    ) -join "`n"
    $methodAnchor = @(
        '    get modelRuntime() {'
        '        return this._modelRuntime;'
        '    }'
    ) -join "`n"
    $methodReplacement = @(
        '    _installMidTurnCompactionBackpressure() {'
        '        if (!["prime-s", "prime-b"].includes(process.env.XINAO_PI_PROFILE) ||'
        '            process.env.XINAO_PI_MIDTURN_COMPACTION_BACKPRESSURE !== "1") {'
        '            return;'
        '        }'
        '        const previousShouldStopAfterTurn = this.agent.shouldStopAfterTurn;'
        '        this.agent.shouldStopAfterTurn = async (context, signal) => {'
        '            if (signal?.aborted) {'
        '                return true;'
        '            }'
        '            if (previousShouldStopAfterTurn && (await previousShouldStopAfterTurn(context, signal))) {'
        '                return true;'
        '            }'
        '            if (!context.toolResults?.length || !this.model) {'
        '                return false;'
        '            }'
        '            const contextWindow = this.model.contextWindow ?? 0;'
        '            if (contextWindow <= 0) {'
        '                return false;'
        '            }'
        '            const settings = this.settingsManager.getCompactionSettings();'
        '            if (!settings.enabled) {'
        '                return false;'
        '            }'
        '            const contextTokens = estimateContextTokens(context.context.messages).tokens;'
        '            if (!shouldCompact(contextTokens, contextWindow, settings)) {'
        '                return false;'
        '            }'
        '            this._midTurnCompactionRequested = true;'
        '            return true;'
        '        };'
        '    }'
        '    get modelRuntime() {'
        '        return this._modelRuntime;'
        '    }'
    ) -join "`n"
    $postRunAnchor = @(
        '        if (msg.stopReason === "error" && this._retryAttempt > 0) {'
        '            this._emit({'
        '                type: "auto_retry_end",'
        '                success: false,'
        '                attempt: this._retryAttempt,'
        '                finalError: msg.errorMessage,'
        '            });'
        '            this._retryAttempt = 0;'
        '        }'
        '        if (await this._checkCompaction(msg)) {'
    ) -join "`n"
    $postRunReplacement = @(
        '        if (msg.stopReason === "error" && this._retryAttempt > 0) {'
        '            this._emit({'
        '                type: "auto_retry_end",'
        '                success: false,'
        '                attempt: this._retryAttempt,'
        '                finalError: msg.errorMessage,'
        '            });'
        '            this._retryAttempt = 0;'
        '        }'
        '        if (this._midTurnCompactionRequested) {'
        '            this._midTurnCompactionRequested = false;'
        '            // The last persisted message is a completed tool result, so compact and'
        '            // continue the same run instead of sending an oversized provider request.'
        '            if (await this._runAutoCompaction("threshold", true)) {'
        '                return true;'
        '            }'
        '            // Compaction cancellation/failure must settle at the completed tool result.'
        '            // Falling through to queued messages could reopen the oversized provider request.'
        '            return false;'
        '        }'
        '        if (await this._checkCompaction(msg)) {'
    ) -join "`n"
    foreach ($anchor in @($fieldAnchor,$constructorAnchor,$methodAnchor,$postRunAnchor)) {
        if (-not $source.Contains($anchor)) { throw 'PI_S_MIDTURN_PATCH_ANCHOR_MISSING' }
    }
    $updated = $source.Replace($fieldAnchor,$fieldReplacement).Replace($constructorAnchor,$constructorReplacement).Replace($methodAnchor,$methodReplacement).Replace($postRunAnchor,$postRunReplacement)
    if ($updated -ceq $source) { throw 'PI_S_MIDTURN_PATCH_NO_CHANGE' }
    [IO.File]::WriteAllText($sourcePath,$updated,[Text.UTF8Encoding]::new($false))
    $changed = $true
} elseif ($beforeHash -cne $patchedHash) {
    throw "PI_S_MIDTURN_PATCH_SOURCE_CONFLICT: expected=$upstreamHash|$patchedHash actual=$beforeHash"
}

$afterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
if ($afterHash -cne $patchedHash) {
    throw "PI_S_MIDTURN_PATCH_VERIFY_FAILED: expected=$patchedHash actual=$afterHash"
}
$preimageHash = $(if (Test-Path -LiteralPath $preimagePath -PathType Leaf) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $preimagePath).Hash.ToLowerInvariant()
} else { $null })
if ($preimageHash -cne $upstreamHash) {
    throw "PI_S_MIDTURN_PATCH_PREIMAGE_MISSING_OR_INVALID: expected=$upstreamHash actual=$preimageHash"
}
$verified = [IO.File]::ReadAllText($sourcePath,[Text.UTF8Encoding]::new($false))
if (
    -not $verified.Contains('this._installMidTurnCompactionBackpressure();') -or
    -not $verified.Contains('!["prime-s", "prime-b"].includes(process.env.XINAO_PI_PROFILE)') -or
    -not $verified.Contains('estimateContextTokens(context.context.messages).tokens') -or
    -not $verified.Contains('this._runAutoCompaction("threshold", true)')
) {
    throw 'PI_S_MIDTURN_PATCH_SEMANTIC_VERIFY_FAILED'
}

[pscustomobject]@{
    schema = 'xinao.pi_midturn_compaction_compatibility.v2'
    patch_id = 'pi-coding-agent-0.84.1-midturn-compaction-backpressure-v2'
    pi_tool_root = $target
    package = '@earendil-works/pi-coding-agent@0.84.1'
    source_path = $sourcePath
    preimage_path = $preimagePath
    preimage_sha256 = $preimageHash
    before_sha256 = $beforeHash
    after_sha256 = $afterHash
    changed = $changed
    verify_only = [bool]$VerifyOnly
    prime_s_runtime_gate_required = $true
    managed_profiles = @('prime-s','prime-b')
    profile_scoped_runtime_gate_required = $true
    completed_tool_boundary_stop = $true
    compact_and_continue_same_run = $true
    compaction_failure_stops_before_provider = $true
    provider_request_guard_is_estimated = $true
    rollback_requires_gate_off_and_verified_preimage_restore = $true
} | ConvertTo-Json -Depth 4
