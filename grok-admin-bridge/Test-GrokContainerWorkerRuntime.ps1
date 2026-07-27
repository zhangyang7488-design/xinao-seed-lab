#Requires -Version 7.0
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$utf8 = [Text.UTF8Encoding]::new($false)
$bridge = $PSScriptRoot
$worker = Join-Path $bridge "Invoke-GrokComposer25Worker.ps1"
$python = Get-Command python.exe -ErrorAction Stop | Select-Object -ExpandProperty Source -First 1
$testRoot = Join-Path "D:\XINAO_RESEARCH_RUNTIME\tmp" (
    "grok-container-worker-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" +
    [guid]::NewGuid().ToString("N").Substring(0, 8)
)
$candidate = Join-Path $testRoot "candidate"
$profile = Join-Path $testRoot "grok-home"
$sessions = Join-Path $profile "sessions"
$evidenceWrite = Join-Path $testRoot "evidence-write"
$evidenceReadOnly = Join-Path $testRoot "evidence-read-only"
$sealedInputRoot = Join-Path $testRoot "sealed-inputs"
New-Item -ItemType Directory -Force -Path $candidate, $sessions, $evidenceWrite, $evidenceReadOnly, $sealedInputRoot | Out-Null
[IO.File]::WriteAllText((Join-Path $sealedInputRoot "catalog.json"), '{"test":true}', $utf8)
[IO.File]::WriteAllText((Join-Path $profile "auth.json"), '{"test_auth":true}', $utf8)
$staleFetchedAt = [DateTimeOffset]::UtcNow.AddMinutes(-10).ToString("o")
$staleCatalog = [ordered]@{
    origin = "https://cli-chat-proxy.grok.com/v1/models"
    fetched_at = $staleFetchedAt
    grok_version = "0.2.112"
    auth_method = "session"
    models = [ordered]@{ "grok-4.5" = [ordered]@{} }
}
$persistentCatalogPath = Join-Path $profile "models_cache.json"
[IO.File]::WriteAllText(
    $persistentCatalogPath,
    ($staleCatalog | ConvertTo-Json -Depth 6 -Compress),
    $utf8
)
$staleCatalogSha256 = (Get-FileHash -LiteralPath $persistentCatalogPath -Algorithm SHA256).Hash.ToLowerInvariant()

function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "GROK_CONTAINER_WORKER_TEST_FAILED: $Message" }
}

$infoScript = @'
import json
import sys

joined = " ".join(sys.argv[1:])
if ".OSType" in joined:
    print(json.dumps("linux"))
else:
    print(json.dumps(["name=seccomp,profile=builtin", "name=cgroupns"]))
'@
$imageScript = @'
import json
print(json.dumps("sha256:" + "a" * 64))
'@
$runScript = @'
import datetime
import json
import os
import sys
import uuid
from pathlib import Path

args = sys.argv[1:]
capture = Path(os.environ["XINAO_FAKE_DOCKER_CAPTURE"])
with capture.open("a", encoding="utf-8", newline="\n") as stream:
    stream.write(json.dumps(args, ensure_ascii=False, separators=(",", ":")) + "\n")

def bind_source(target):
    for value in args:
        if not value.startswith("type=bind,"):
            continue
        fields = dict(part.split("=", 1) for part in value.split(",") if "=" in part)
        if fields.get("target") == target:
            return Path(fields["source"])
    raise RuntimeError(f"missing bind target: {target}")

if args[-1] == "version":
    print("grok 0.2.112")
    raise SystemExit(0)
if args[-1] == "models":
    profile = bind_source("/grok-home/.grok")
    catalog = profile / "models_cache.json"
    payload = {
        "origin": "https://cli-chat-proxy.grok.com/v1/models",
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "grok_version": "0.2.112",
        "auth_method": "session",
        "models": {"grok-4.5": {}},
    }
    temporary = profile / f".models_cache.json.{uuid.uuid4().hex}.tmp"
    temporary.write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8", newline="\n"
    )
    temporary.replace(catalog)
    print("You are logged in with grok.com.\n\nAvailable models:\n  - grok-4.5")
    raise SystemExit(0)

grok_index = args.index("/usr/local/bin/xinao-grok-entrypoint")
grok_args = args[grok_index + 1 :]
model = grok_args[grok_args.index("-m") + 1]
session_id = str(uuid.uuid4())
session_root = bind_source("/grok-home/.grok") / "sessions" / "fake-project" / session_id
session_root.mkdir(parents=True)
(session_root / "summary.json").write_text(
    json.dumps(
        {
            "info": {"id": session_id, "cwd": "/workspace"},
            "grok_home": "/grok-home/.grok",
            "current_model_id": model,
        },
        separators=(",", ":"),
    ),
    encoding="utf-8",
    newline="\n",
)
(session_root / "events.jsonl").write_text(
    json.dumps(
        {"type": "turn_started", "session_id": session_id, "model_id": model},
        separators=(",", ":"),
    )
    + "\n",
    encoding="utf-8",
    newline="\n",
)
workspace_mount = next(value for value in args if "target=/workspace" in value)
if not workspace_mount.endswith(",readonly"):
    (Path(os.environ["XINAO_FAKE_CANDIDATE"]) / "container-write-marker.txt").write_text(
        "CONTAINER_WRITE_OK\n", encoding="utf-8", newline="\n"
    )
payload = {
    "text": "CONTAINER_OK",
    "stopReason": "EndTurn",
    "sessionId": session_id,
    "usage": {
        "input_tokens": 10,
        "cache_read_input_tokens": 20,
        "output_tokens": 3,
        "reasoning_tokens": 2,
        "total_tokens": 35,
    },
    "modelUsage": {"grok-4.5-build": {"modelCalls": 1}},
}
print(json.dumps(payload, separators=(",", ":")))
'@
[IO.File]::WriteAllText((Join-Path $candidate "info"), $infoScript, $utf8)
[IO.File]::WriteAllText((Join-Path $candidate "image"), $imageScript, $utf8)
[IO.File]::WriteAllText((Join-Path $candidate "run"), $runScript, $utf8)

$rulesPath = Join-Path $testRoot "rules.txt"
[IO.File]::WriteAllText($rulesPath, "bounded container test rules`n", $utf8)
$rulesSha256 = (Get-FileHash -LiteralPath $rulesPath -Algorithm SHA256).Hash.ToLowerInvariant()
$capturePath = Join-Path $testRoot "docker-run-argv.jsonl"
$priorCapture = $env:XINAO_FAKE_DOCKER_CAPTURE
$priorHome = $env:XINAO_FAKE_GROK_HOME
$priorSessions = $env:XINAO_FAKE_GROK_SESSIONS
$priorCandidate = $env:XINAO_FAKE_CANDIDATE
try {
    $env:XINAO_FAKE_DOCKER_CAPTURE = $capturePath
    $env:XINAO_FAKE_GROK_HOME = $profile
    $env:XINAO_FAKE_GROK_SESSIONS = $sessions
    $env:XINAO_FAKE_CANDIDATE = $candidate
    foreach ($case in @(
        [pscustomobject]@{ effect = "authorized_write"; evidence = $evidenceWrite },
        [pscustomobject]@{ effect = "read_only"; evidence = $evidenceReadOnly }
    )) {
        & $worker `
            -Prompt "Return CONTAINER_OK" `
            -Cwd $candidate `
            -Model "grok-4.5" `
            -GrokHome $profile `
            -GrokExe $python `
            -EvidenceDir $case.evidence `
            -TimeoutSec 30 `
            -MinResultChars 1 `
            -RequiredResultMarkers "CONTAINER_OK" `
            -RulesFile $rulesPath `
            -RulesSha256 $rulesSha256 `
            -ExecutionBackend "linux-container" `
            -ContainerEffectMode $case.effect `
            -SealedInputRoot $sealedInputRoot `
            -ContainerImage "fake-grok-worker:test" `
            -DockerExe $python `
            -Quiet
        Assert-Contract ($LASTEXITCODE -eq 0) ("worker_exit_" + $case.effect)
        $meta = Get-Content -LiteralPath (Join-Path $case.evidence "latest.json") -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        Assert-Contract ($meta.status -eq "accepted") ("worker_accepted_" + $case.effect)
        Assert-Contract ($meta.execution_backend -eq "linux-container") "execution_backend"
        Assert-Contract ($meta.sandbox_enforcement -eq "linux_docker_mount_boundary_plus_tool_shell_bwrap_profile_mask") "sandbox_enforcement"
        Assert-Contract ($meta.container_profile_tmpfs -eq $false) "profile_not_tmpfs"
        Assert-Contract ($meta.container_profile_ephemeral_host_directory -eq $true) "ephemeral_profile_directory"
        Assert-Contract ($meta.outer_rootfs_read_only -eq $true) "rootfs_read_only"
        Assert-Contract ($meta.outer_non_root -eq $false) "transport_root_required_for_auth_bind"
        Assert-Contract ($meta.outer_capabilities_dropped -eq $true) "capabilities_dropped"
        Assert-Contract ($meta.outer_no_new_privileges -eq $true) "no_new_privileges"
        Assert-Contract ($meta.container_runtime_user -eq "0:0") "runtime_user"
        Assert-Contract ($meta.container_tool_user -eq "65532:65532") "tool_user"
        Assert-Contract ($meta.outer_capability_policy -eq "drop_all_add_setuid_setgid_for_tool_shell_wrapper_only") "capability_policy"
        Assert-Contract ($meta.outer_seccomp_mode -eq "unconfined_for_unprivileged_bubblewrap_bootstrap") "seccomp_mode"
        Assert-Contract ($meta.session_path_binding_mode -eq "container_mount_alias_plus_host_lease") "session_alias_binding"
        Assert-Contract ($meta.container_persistent_profile_mounted -eq $false) "persistent_profile_not_mounted"
        Assert-Contract ($meta.container_persistent_auth_read_only -eq $true) "persistent_auth_read_only"
        Assert-Contract ($meta.container_persistent_auth_unchanged -eq $true) "persistent_auth_unchanged"
        Assert-Contract ($meta.container_auth_secret_copied -eq $false) "auth_secret_not_copied"
        Assert-Contract ($meta.container_tool_shell -eq "/usr/bin/bash") "tool_shell"
        Assert-Contract ($meta.container_tool_profile_masked -eq $true) "tool_profile_masked"
        Assert-Contract ($meta.container_auth_placeholder_clean -eq $true) "auth_placeholder_clean"
        Assert-Contract ($meta.container_logs_tmpfs -eq $true) "logs_nested_tmpfs"
        Assert-Contract ($meta.container_sensitive_logs_retained -eq $false) "sensitive_logs_not_retained"
        Assert-Contract ($meta.sealed_input_root -eq $sealedInputRoot) "sealed_input_root"
        Assert-Contract ($meta.container_sealed_input_root -eq "/sealed-inputs") "container_sealed_input_root"
        Assert-Contract ($meta.container_sealed_input_read_only -eq $true) "container_sealed_input_read_only"
        Assert-Contract ([string]$meta.model_catalog.cache_sha256 -ne $staleCatalogSha256) "catalog_atomic_refresh_sha_advanced"
        Assert-Contract ([DateTimeOffset]::Parse([string]$meta.model_catalog.fetched_at) -gt [DateTimeOffset]::Parse($staleFetchedAt)) "catalog_atomic_refresh_time_advanced"
    }
}
finally {
    if ($null -eq $priorCapture) { Remove-Item Env:XINAO_FAKE_DOCKER_CAPTURE -ErrorAction SilentlyContinue } else { $env:XINAO_FAKE_DOCKER_CAPTURE = $priorCapture }
    if ($null -eq $priorHome) { Remove-Item Env:XINAO_FAKE_GROK_HOME -ErrorAction SilentlyContinue } else { $env:XINAO_FAKE_GROK_HOME = $priorHome }
    if ($null -eq $priorSessions) { Remove-Item Env:XINAO_FAKE_GROK_SESSIONS -ErrorAction SilentlyContinue } else { $env:XINAO_FAKE_GROK_SESSIONS = $priorSessions }
    if ($null -eq $priorCandidate) { Remove-Item Env:XINAO_FAKE_CANDIDATE -ErrorAction SilentlyContinue } else { $env:XINAO_FAKE_CANDIDATE = $priorCandidate }
}

$captured = [Collections.Generic.List[object]]::new()
foreach ($line in Get-Content -LiteralPath $capturePath -Encoding UTF8) {
    $captured.Add(@($line | ConvertFrom-Json -ErrorAction Stop))
}
$actualRuns = @($captured | Where-Object { @($_) -contains "/usr/local/bin/xinao-grok-entrypoint" -and @($_) -contains "--prompt-file" })
Assert-Contract ($actualRuns.Count -eq 2) "two_actual_container_runs"
$writeRun = @($actualRuns[0])
$readOnlyRun = @($actualRuns[1])
foreach ($required in @("--read-only", "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "SETUID", "SETGID", "--security-opt", "seccomp=unconfined", "no-new-privileges:true", "--sandbox", "off", "--always-approve", "--no-subagents", "--no-memory", "SHELL=/usr/bin/bash")) {
    Assert-Contract ($writeRun -contains $required) ("write_run_required_arg:" + $required)
}
$writeMounts = @($writeRun | Where-Object { $_ -like "type=bind,*" })
$readOnlyMounts = @($readOnlyRun | Where-Object { $_ -like "type=bind,*" })
$writeWorkspaceMount = @($writeMounts | Where-Object { $_ -like "*target=/workspace*" })
$readOnlyWorkspaceMount = @($readOnlyMounts | Where-Object { $_ -like "*target=/workspace*" })
$writeSealedInputMount = @($writeMounts | Where-Object { $_ -like "*target=/sealed-inputs*" })
$readOnlySealedInputMount = @($readOnlyMounts | Where-Object { $_ -like "*target=/sealed-inputs*" })
Assert-Contract ($writeWorkspaceMount.Count -eq 1 -and -not $writeWorkspaceMount[0].EndsWith(",readonly")) "write_workspace_rw"
Assert-Contract ($readOnlyWorkspaceMount.Count -eq 1 -and $readOnlyWorkspaceMount[0].EndsWith(",readonly")) "read_only_workspace_ro"
Assert-Contract ($writeSealedInputMount.Count -eq 1 -and $writeSealedInputMount[0].EndsWith(",readonly")) "write_sealed_input_ro"
Assert-Contract ($readOnlySealedInputMount.Count -eq 1 -and $readOnlySealedInputMount[0].EndsWith(",readonly")) "read_only_sealed_input_ro"
Assert-Contract (@($writeMounts | Where-Object { $_ -like "*target=/inputs/prompt.md,readonly" }).Count -eq 1) "prompt_mount_ro"
Assert-Contract (@($writeMounts | Where-Object { $_ -like "*target=/grok-home/.grok" }).Count -eq 1) "ephemeral_profile_directory_mount"
Assert-Contract (@($writeMounts | Where-Object { $_ -like "*target=/grok-home/.grok/auth.json,readonly" }).Count -eq 1) "persistent_auth_mount_ro"
Assert-Contract (@($writeRun | Where-Object { $_ -like "/grok-home/.grok:rw,*" }).Count -eq 0) "profile_has_no_conflicting_tmpfs"
Assert-Contract (@($writeRun | Where-Object { $_ -like "/grok-home/.grok/logs:rw,*" }).Count -eq 1) "logs_nested_tmpfs"
Assert-Contract (@($writeMounts | Where-Object { $_ -like "*target=/grok-home/.grok/sessions" }).Count -eq 0) "session_uses_profile_directory"
Assert-Contract (@($writeMounts | Where-Object { $_ -like "*target=/grok-home/.grok/models_cache.json" }).Count -eq 0) "catalog_has_no_single_file_mount"
Assert-Contract (Test-Path -LiteralPath (Join-Path $candidate "container-write-marker.txt") -PathType Leaf) "authorized_write_effect"

[ordered]@{
    status = "verified"
    test_root = $testRoot
    actual_run_count = $actualRuns.Count
    authorized_workspace_mount = $writeWorkspaceMount[0]
    read_only_workspace_mount = $readOnlyWorkspaceMount[0]
    authorized_sealed_input_mount = $writeSealedInputMount[0]
    read_only_sealed_input_mount = $readOnlySealedInputMount[0]
    prompt_mount_read_only = $true
    rootfs_read_only = $true
    transport_root_for_read_only_auth = $true
    tool_user = "65532:65532"
    capabilities_dropped = $true
    no_new_privileges = $true
    outer_seccomp_mode = "unconfined_for_unprivileged_bubblewrap_bootstrap"
    sandbox_profile = "off"
    sandbox_profile_extends = ""
    tool_shell = "/usr/bin/bash"
    tool_profile_masked = $true
    persistent_profile_mounted = $false
    persistent_auth_read_only = $true
    persistent_auth_unchanged = $true
    auth_secret_copied = $false
    sensitive_logs_retained = $false
    profile_tmpfs = $false
    profile_ephemeral_host_directory = $true
    logs_nested_tmpfs = $true
    catalog_atomic_replace_verified = $true
    container_session_alias_verified = $true
} | ConvertTo-Json -Depth 5

if (Test-Path -LiteralPath $testRoot -PathType Container) {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
