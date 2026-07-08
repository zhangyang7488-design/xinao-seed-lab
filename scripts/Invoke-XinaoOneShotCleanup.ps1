# One-shot cleanup after wave5 global sunset (2026-07-08).
$ErrorActionPreference = "Continue"
$repo = "E:\XINAO_RESEARCH_WORKSPACES\S"
$runtime = "D:\XINAO_RESEARCH_RUNTIME"

Write-Host "=== One-shot cleanup start ==="

# 1) S repo: verify marathon scripts
$verify = Get-ChildItem "$repo\scripts\verify_*.ps1" -File -ErrorAction SilentlyContinue
if ($verify) {
    $verify | Remove-Item -Force -ErrorAction SilentlyContinue
    Write-Host "Removed verify scripts: $($verify.Count)"
}

# 2) S repo: seedcortex handroll tests
$seed = "$repo\tests\seedcortex"
if (Test-Path $seed) {
    Remove-Item $seed -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Removed tests/seedcortex"
}

# 3) S repo: __pycache__
Get-ChildItem $repo -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Cleared __pycache__ under S repo"

# 4) D runtime: readback — keep integrated_bus + thin_glue only
if (Test-Path "$runtime\readback") {
    $rb = Get-ChildItem "$runtime\readback" -Recurse -File -ErrorAction SilentlyContinue
    $rbDel = $rb | Where-Object { $_.FullName -notmatch 'integrated_bus|thin_glue' }
    $rbDel | Remove-Item -Force -ErrorAction SilentlyContinue
    Write-Host "D readback removed files: $($rbDel.Count) kept: $($rb.Count - $rbDel.Count)"
}

# 5) D runtime: state — keep integrated_bus + thin_glue + aaq/integrated_bus
if (Test-Path "$runtime\state") {
    $keep = @('integrated_bus', 'thin_glue', 'integrated_bus_worker_daemon', 'integrated_bus_parallel', 'integrated_bus_pytest_slice')
    Get-ChildItem "$runtime\state" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $name = $_.Name
        if ($name -eq 'aaq') {
            Get-ChildItem $_.FullName -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -ne 'integrated_bus' } |
                Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
            return
        }
        if ($keep -notcontains $name -and $name -notlike 'thin_glue*') {
            Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "D state pruned (kept integrated_bus + thin_glue + aaq/integrated_bus)"
}

# 6) D runtime: sunset log folder ok to keep; drop overnight glue scratch
@("$runtime\overnight", "$runtime\sunset") | ForEach-Object {
    if (Test-Path $_) {
        Remove-Item $_ -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Removed $_"
    }
}

Write-Host "=== One-shot cleanup done ==="
$eFree = [math]::Round((Get-PSDrive E).Free / 1GB, 2)
$dFree = [math]::Round((Get-PSDrive D).Free / 1GB, 2)
Write-Host "E free GB: $eFree | D free GB: $dFree"