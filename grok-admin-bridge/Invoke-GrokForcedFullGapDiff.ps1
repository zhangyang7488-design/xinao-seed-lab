#Requires -Version 5.1
<#
.SYNOPSIS
  别名入口 → 统一到 Invoke-GrokFullGapScan.ps1（避免双真相扫描器）
.DESCRIPTION
  桌面/宪法夹「强制.txt」与多轴 forced 合同均落到 FullGapScan 唯一实现。
#>
param(
    [string]$ConfigPath = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$args = @{}
if ($ConfigPath) { $args.ConfigPath = $ConfigPath }
if ($Quiet) { $args.Quiet = $true }
& (Join-Path $bridge "Invoke-GrokFullGapScan.ps1") @args
exit $LASTEXITCODE
