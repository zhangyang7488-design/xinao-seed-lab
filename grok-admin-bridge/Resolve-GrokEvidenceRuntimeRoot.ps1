# Returns evidence runtime root for Grok bridge scripts (RESEARCH by default).
param(
    [string]$ConfigPath = ""
)

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $PSScriptRoot "bridge.config.json"
}

$default = "D:\XINAO_RESEARCH_RUNTIME"
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    return $default
}

try {
    $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.runtime_roots -and $config.runtime_roots.evidence) {
        return [string]$config.runtime_roots.evidence
    }
    if ($config.grok_codex_s_hardmode -and $config.grok_codex_s_hardmode.runtime_root) {
        return [string]$config.grok_codex_s_hardmode.runtime_root
    }
}
catch {
}

return $default