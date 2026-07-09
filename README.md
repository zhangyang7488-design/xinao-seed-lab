# Grok Admin Isolated Workspace

This workspace is the **Grok intent preservation entry** for XINAO. CodexA remains the local execution brain.

## Bridge installed

- MCP: `.grok/config.toml` → `xinao` @ `http://127.0.0.1:19460/mcp`
- Scripts: `grok-admin-bridge/`
- State: `D:\XINAO_CLEAN_RUNTIME\state\grok_admin_bridge\latest.json`

## Quick use

```powershell
.\grok-admin-bridge\Get-GrokLocalCapabilityStatus.ps1
.\grok-admin-bridge\Send-GrokIntentToCodexA.ps1 -UserIntentCn "你的完整意图"
```

After first install or config change: **restart Grok** or run `/mcps` refresh to load `xinao` tools.

Do not delete this directory; the desktop shortcut uses it as the startup directory.
