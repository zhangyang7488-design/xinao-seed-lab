#Requires -Version 7.2
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$toolchain = Get-Content (Join-Path $PSScriptRoot 'toolchain-lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json

function Get-Sha256([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

$keyFiles = @(
    'provisioning/Invoke-XinaoCoordManaged.ps1',
    'provisioning/toolchain-lock.json',
    'pyproject.toml',
    'uv.lock',
    'configs/modules/temporal.toml',
    'src/xinao_coordination/temporal/client.py',
    'src/xinao_coordination/temporal/policy.py',
    'adapters/temporal/README.md',
    'adapters/temporal/requirements-temporal.txt',
    'adapters/temporal/worker_deployment.v1.json',
    'adapters/temporal/replay_promoted_histories.py',
    'docs/TEMPORAL_WORKER_OPS.md'
)
$fileHashes = [ordered]@{}
foreach ($rel in $keyFiles) {
    $path = Join-Path $root ($rel -replace '/', '\')
    $fileHashes[$rel] = Get-Sha256 -Path $path
}

$pyVersion = ''
$temporalioVersion = $null
$temporalioResolved = $null
$devPython = Join-Path $root '.venv\Scripts\python.exe'
$deploymentManifestPath = Join-Path $root 'adapters\temporal\worker_deployment.v1.json'
$deploymentManifest = Get-Content $deploymentManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
try {
    if (-not (Test-Path -LiteralPath $devPython -PathType Leaf)) { throw 'dev python missing' }
    $pyVersion = (& $devPython -c 'import platform; print(platform.python_version())').Trim()
}
catch {
    $pyVersion = [string]$toolchain.python.request
}
try {
    if (-not (Test-Path -LiteralPath $devPython -PathType Leaf)) { throw 'dev python missing' }
    $temporalioVersion = (& $devPython -c 'import importlib.metadata as m; print(m.version("temporalio"))').Trim()
}
catch {
    $temporalioVersion = $null
}
if ($temporalioVersion -eq '' -or $temporalioVersion -match 'not found|No package') { $temporalioVersion = $null }

$pyproject = Get-Content (Join-Path $root 'pyproject.toml') -Raw -Encoding UTF8
if ($pyproject -match 'temporalio[=<> ]+([0-9][^\s",]+)') {
    $temporalioResolved = $Matches[1]
}
else {
    $lock = Get-Content (Join-Path $root 'uv.lock') -Raw -Encoding UTF8
    if ($lock -match 'name = "temporalio"[\s\S]*?version = "([^"]+)"') {
        $temporalioResolved = $Matches[1]
    }
}

$pin = [ordered]@{
    schema_version = 1
    project = 'xinao-dual-brain-coordination'
    recorded_at_utc = [DateTime]::UtcNow.ToString('o')
    lane = 'C'
    purpose = 'managed_temporal_mcp_pin'
    python = [ordered]@{
        request = [string]$toolchain.python.request
        dev_sync_actual = $pyVersion
        implementation = [string]$toolchain.python.implementation
        platform = [string]$toolchain.python.platform
    }
    temporalio = [ordered]@{
        pyproject_dependency = $temporalioResolved
        installed_in_dev_env = $temporalioVersion
        note = 'GA Worker Deployments pin; official samples-server commit ca1106b647c34323876bd6f221f4310271096dd8'
    }
    temporal_env = [ordered]@{
        supported = @(
            'XINAO_TEMPORAL_ENABLED',
            'XINAO_TEMPORAL_LIVE',
            'XINAO_TEMPORAL_MOCK',
            'XINAO_TEMPORAL_ADDRESS',
            'XINAO_TEMPORAL_NAMESPACE',
            'XINAO_TEMPORAL_TASK_QUEUE',
            'XINAO_TEMPORAL_WORKER_VERSIONING',
            'XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME',
            'XINAO_TEMPORAL_WORKER_BUILD_ID'
        )
        invoke_parameters = @('TemporalEnabled', 'TemporalLive', 'TemporalMock', 'TemporalAddress')
        defaults = [ordered]@{
            XINAO_TEMPORAL_ENABLED = '0'
            XINAO_TEMPORAL_MOCK = '1'
            XINAO_TEMPORAL_LIVE = '0'
            XINAO_TEMPORAL_ADDRESS = '127.0.0.1:7233'
        }
    }
    worker_deployment = [ordered]@{
        manifest = 'adapters/temporal/worker_deployment.v1.json'
        deployment_name = [string]$deploymentManifest.deployment_name
        build_id = [string]$deploymentManifest.build_id
        default_versioning_behavior = [string]$deploymentManifest.default_versioning_behavior
        target_server = [string]$deploymentManifest.target_server
        replay_gate = 'adapters/temporal/replay_promoted_histories.py'
    }
    invoke = [ordered]@{
        managed_script = 'provisioning/Invoke-XinaoCoordManaged.ps1'
        convenience_targets = @('temporal-status', 'temporal-start-promoted')
        target_args_pattern = "-Target cli -TargetArgs @('temporal-status')"
        rebuild_generation_switch = '-RebuildGeneration'
        rebuild_generation_alias_of = '-ForceRepair'
        runtime_root = [string]$toolchain.runtime_root
    }
    key_files_sha256 = $fileHashes
}
$pinPath = Join-Path $PSScriptRoot 'temporal_mcp_pin.json'
$json = ($pin | ConvertTo-Json -Depth 12) + [Environment]::NewLine
[IO.File]::WriteAllText($pinPath, $json, [Text.UTF8Encoding]::new($false))
Write-Output $pinPath
