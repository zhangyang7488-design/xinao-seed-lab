#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Target = 'D:\XINAO_RESEARCH_RUNTIME\tools\prime-agent\0.7.0\node_modules\prime-agent\dist\core\tools\ipython.js',
    [string]$Backup = 'D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\islands\local-cognition-account-b\known-good\pre-codex-pis-closure-20260808T0906+0800\runtime\prime-agent\dist\core\tools\ipython.js'
)

$ErrorActionPreference = 'Stop'
$preHash = '2289467E28B6F817EDFC65B0E5AA77382B193920323B9AEF95FBDC82812975BD'
$postHash = 'C3937FE213A747591FBE10F380AD7D27B911F47209A2E0BCB71566A3402ECD3F'

function Get-Hash([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
    throw "PRIME_KERNEL_PATCH_TARGET_MISSING: $Target"
}
$observed = Get-Hash $Target
if ($observed -eq $postHash) {
    [pscustomobject]@{status='already_verified';target=$Target;sha256=$observed;backup=$Backup}
    exit 0
}
if ($observed -ne $preHash) {
    throw "PRIME_KERNEL_PATCH_UNEXPECTED_SOURCE_HASH: expected=$preHash observed=$observed"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Backup) | Out-Null
if (-not (Test-Path -LiteralPath $Backup -PathType Leaf)) {
    Copy-Item -LiteralPath $Target -Destination $Backup
}
if ((Get-Hash $Backup) -ne $preHash) {
    throw 'PRIME_KERNEL_PATCH_BACKUP_HASH_MISMATCH'
}

$text = [System.IO.File]::ReadAllText($Target)
$constantsOld = @'
const KERNEL_RESTART_NOTICE = [
    "<ipython_kernel_reset>",
    "The IPython kernel was restarted after a previous interrupted cell kept running. Variables, imports, async tasks, and open resources from before the restart are no longer available; recreate them before using them.",
    "</ipython_kernel_reset>",
].join("\n");
'@
$constantsNew = $constantsOld + "`n" + @'
const TERMINAL_KERNEL_SHUTDOWN_MESSAGE = "Kernel has been shut down";
const TERMINAL_KERNEL_RECOVERED_MESSAGE = [
    "IPython stopped unexpectedly. The host created a fresh kernel and did not replay the interrupted cell.",
    "Continue from durable files or recreate only the in-memory state that is still needed.",
].join(" ");
const TERMINAL_KERNEL_CIRCUIT_OPEN_MESSAGE = [
    "IPython stopped unexpectedly and one host-level recovery attempt failed; the circuit is open.",
    "Do not retry this tool in a loop. Reload or exactly resume the Prime runtime before using IPython again.",
].join(" ");
function isTerminalKernelShutdownError(error) {
    return error instanceof Error && error.message.includes(TERMINAL_KERNEL_SHUTDOWN_MESSAGE);
}
'@
$methodOld = @'
    }
    ensure(onProgress, signal) {
        if (signal?.aborted) {
'@
$killOld = @'
    async kill() {
        const pending = this.managerPromise;
        this.managerPromise = undefined;
        this.startedManager = undefined;
        if (this.options?.kernelManagerRef) {
'@
$killNew = @'
    async kill() {
        const pending = this.managerPromise;
        this.managerPromise = undefined;
        this.startedManager = undefined;
        this.terminalRecoveryFailure = undefined;
        if (this.options?.kernelManagerRef) {
'@
$methodNew = @'
    }
    async recoverTerminalShutdown(onProgress, signal) {
        if (this.terminalRecoveryFailure) {
            throw this.terminalRecoveryFailure;
        }
        try {
            await this.kill();
            await this.ensure(onProgress, signal);
        }
        catch (error) {
            const failure = new Error(`${TERMINAL_KERNEL_CIRCUIT_OPEN_MESSAGE} Recovery error: ${error instanceof Error ? error.message : String(error)}`);
            failure.name = "IpythonKernelRecoveryCircuitOpenError";
            this.terminalRecoveryFailure = failure;
            throw failure;
        }
    }
    ensure(onProgress, signal) {
        if (this.terminalRecoveryFailure) {
            return Promise.reject(this.terminalRecoveryFailure);
        }
        if (signal?.aborted) {
'@
$catchOld = @'
        catch (error) {
            if (!(error instanceof KernelBusyAfterInterruptError) || signal?.aborted) {
'@
$catchNew = @'
        catch (error) {
            if (isTerminalKernelShutdownError(error) && !signal?.aborted) {
                onWorkingMessage("Recovering IPython kernel outside the failed kernel...");
                await provisioner.recoverTerminalShutdown(reportStartupProgress, signal);
                const recovered = new Error(TERMINAL_KERNEL_RECOVERED_MESSAGE);
                recovered.name = "IpythonKernelRecoveredAfterShutdownError";
                throw recovered;
            }
            if (!(error instanceof KernelBusyAfterInterruptError) || signal?.aborted) {
'@

$replacements = @(
    [pscustomobject]@{Old=$constantsOld;New=$constantsNew},
    [pscustomobject]@{Old='    _lastRestore;';New=('    _lastRestore;' + "`n" + '    terminalRecoveryFailure;')},
    [pscustomobject]@{Old=$killOld;New=$killNew},
    [pscustomobject]@{Old=$methodOld;New=$methodNew},
    [pscustomobject]@{Old=$catchOld;New=$catchNew}
)
$replacementIndex = 0
foreach ($replacement in $replacements) {
    $replacementIndex++
    if (-not $text.Contains([string]$replacement.Old)) {
        throw "PRIME_KERNEL_PATCH_EXPECTED_MARKER_MISSING: replacement=$replacementIndex"
    }
    $text = $text.Replace([string]$replacement.Old,[string]$replacement.New)
}
if (-not $text.EndsWith("`n")) { $text += "`n" }

$temporary = "$Target.$PID.tmp"
[System.IO.File]::WriteAllText($temporary,$text,[System.Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporary -Destination $Target -Force
$after = Get-Hash $Target
if ($after -ne $postHash) {
    throw "PRIME_KERNEL_PATCH_POST_HASH_MISMATCH: expected=$postHash observed=$after"
}
[pscustomobject]@{status='installed';target=$Target;sha256=$after;backup=$Backup}
