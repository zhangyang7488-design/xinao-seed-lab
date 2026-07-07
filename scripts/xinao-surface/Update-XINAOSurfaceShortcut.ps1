# SENTINEL:XINAO_XINAOSURFACE_SHORTCUT_UPDATE_V1
# Updates desktop shortcut to point at the latest XINAOSurface build artifact.
# Called by 333 mainline event-wave source_family handler after build.
param(
    [string]$TargetVersionLabel,
    [string]$ArtifactRoot = "D:\XINAO_RESEARCH_RUNTIME\artifacts\xinao-surface",
    [string]$ShortcutPath = "$env:USERPROFILE\Desktop\XINAOSurface.lnk"
)

$ErrorActionPreference = "Stop"

# Find the version directory
$versionDir = "$ArtifactRoot\app-s-mainline-$TargetVersionLabel"
if (-not (Test-Path $versionDir)) {
    Write-Error "VERSION_DIR_NOT_FOUND: $versionDir"
    exit 1
}

# Find the exe
$exePath = Get-ChildItem -Path $versionDir -Filter "XINAOSurface.exe" -Recurse -Depth 3 | Select-Object -First 1
if (-not $exePath) {
    Write-Error "EXE_NOT_FOUND in $versionDir"
    exit 1
}

# Create/update shortcut
$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $exePath.FullName
$shortcut.WorkingDirectory = Split-Path $exePath.FullName -Parent
$shortcut.Description = "XINAOSurface S-mainline $TargetVersionLabel"
$shortcut.IconLocation = "$($exePath.FullName),0"
$shortcut.Save()

Write-Output "OK: shortcut updated -> $ShortcutPath -> $($exePath.FullName)"

# Write evidence
$evidenceDir = "D:\XINAO_RESEARCH_RUNTIME\state\xinao_surface_deploy"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
@{
    schema_version = "xinao.codex_s.xinao_surface_deploy.shortcut.v1"
    sentinel = "XINAO_XINAOSURFACE_SHORTCUT_UPDATED"
    status = "xinao_surface_shortcut_ready"
    action = "xinao_surface_shortcut_update"
    app_id = "xinao-surface"
    version_label = $TargetVersionLabel
    shortcut_path = $ShortcutPath
    exe_path = $exePath.FullName
    deployed_exe = $exePath.FullName
    shortcut_promoted = $true
    validation = @{
        passed = $true
        checks = @{
            version_dir_present = $true
            deployed_exe_present = $true
            shortcut_present = (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)
        }
    }
    deployed_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
    completion_claim_allowed = $false
    not_user_completion = $true
    not_completion_decision = $true
    not_execution_controller = $true
} | ConvertTo-Json | Out-File "$evidenceDir\latest.json" -Encoding utf8

Write-Output "OK: deploy evidence written to $evidenceDir\latest.json"
