---
name: codex-s-direct-worker-lane
description: >
  Invoke Codex S direct Qwen/DP worker lane (not 333 mainline). Use when the user
  asks to call 千问/Qwen, DP/DeepSeek, or "直调 worker lane" for draft/eval/audit/extract
  without running full RootIntentLoop/Temporal. Triggers: 喊千问, 喊DP, worker lane,
  direct-worker-lane, 让千问草稿, 让DP审. Slash: /codex-s-direct-worker-lane.
  NOT for 333 main chain repair — use desktop construction package + Codex S for that.
---

# Codex S Direct Worker Lane (Grok tool)

直调 **Qwen/DP 单 lane**。`not_333_mainline=true`；不等于 RootIntentLoop/Temporal 主链完成。

## When to use

- User wants **one** cheap worker pass: draft, extract, eval, audit, contradiction
- User says 喊千问 / 喊 DP / 直调 worker / worker lane
- **Do NOT** use when user wants full **333 主链** (Temporal + fan-in + AAQ) — point to Codex S + construction package instead

## Invoke (always run yourself)

```powershell
Set-Location "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"
.\Invoke-GrokCodexSDirectWorkerLane.ps1 `
  -Mode draft `
  -Provider auto `
  -Objective "<one line task>" `
  -InputText "<user material or summary>"
```

| Param | Values |
|-------|--------|
| `-Mode` | draft, eval, contradiction, audit, extraction, citation_verify, search, provider_probe |
| `-Provider` | auto, qwen, dp |

Examples:

```powershell
.\Invoke-GrokCodexSDirectWorkerLane.ps1 -Mode draft -Provider auto -Objective "extract claims" -InputText "..."
.\Invoke-GrokCodexSDirectWorkerLane.ps1 -Mode audit -Provider dp -Objective "contradiction scan" -InputText "..."
.\Invoke-GrokCodexSDirectWorkerLane.ps1 -Mode draft -Provider qwen -Objective "cheap draft" -InputText "..."
```

Large input: write temp file, use `-InputFile` path.

## After invoke — read evidence

1. `grok-admin-bridge/state/grok_codex_s_direct_worker_lane/latest.json`
2. `D:\XINAO_RESEARCH_RUNTIME\state\codex_s_direct_worker_lane\latest.json`
3. Lane `artifact_ref` if succeeded

## Reply to user (≤8 lines 中文)

- 用的 mode/provider、是否真调了模型
- `named_blocker` if blocked (e.g. `TASK_NOT_SUITABLE_FOR_QWEN` on audit+qwen)
- 产物路径
- **一句边界**：这是 worker lane，不是 333 主链；晋升事实还要 fan-in/AAQ

## Infrastructure (frozen — do NOT ask user to choose)

- **Qwen cheap lane default:** `thin_provider_client` → **LiteLLM `http://127.0.0.1:20128/v1`** → Ollama `qwen3:8b` (see `materials/thin_glue_litellm_config.yaml`). **Not a new component.**
- **Start chain (Grok runs when blocked):** Docker Desktop → `E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Start-XinaoThinGlueStack.ps1` → probe `thin-provider-probe`
- **DP fallback** when Qwen path fails = lane rescue only; **never** describe as Qwen's architecture default.
- **Contract:** `grok-admin-bridge/grok_infrastructure_prerequisite_no_user_menu.v1.json` — **no menu** («要不要起网关 / 选1选2»).

## Hard rules

- `completion_claim_allowed=false` — never say 做完了/主链好了
- audit + qwen → expect block; suggest `-Provider dp` or `-Provider auto`
- Do not paste full raw JSON into chat

Contract: `grok-admin-bridge/grok_codex_s_direct_worker_lane_tool.v1.json`