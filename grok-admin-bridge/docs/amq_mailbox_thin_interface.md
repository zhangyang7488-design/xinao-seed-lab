# AMQ Mailbox 薄接口（T1/S1）

**载体：** [avivsinai/agent-message-queue](https://github.com/avivsinai/agent-message-queue) · Maildir  
**禁止：** 手搓第二套邮局；本文件只映射动作 → 官方 CLI。

## 身份钉死（纠偏 · 2026-07-12）

**用户指定的「俩 TUI 对话」主环（双脑产品脸）：**

| 快捷方式 | TUI | AM 句柄（建议） | 角色 |
|----------|-----|-----------------|------|
| `桌面\Grok 4.5.lnk` | Grok 4.5 | `grok`（MCP 角色常作 `grok_4_5`） | 讨论主方 · 全息/调研/互证 |
| `桌面\OPEN CODEX S HARDMODE.lnk` | Codex S Hardmode | `codex` | 讨论主方 · 工程/复现/终验偏 |

```text
用户
  ├─ Codex S Hardmode TUI ──┐
  │                         ├─ AMQ/Maildir ──► dual-brain 协调内核
  └─ Grok 4.5 TUI ──────────┘         （讨论→收口→可选 promote）
```

**不是对话主方：**

| 窗 / 句柄 | 位阶 |
|-----------|------|
| `Grok Admin Isolated.lnk` / 句柄 `admin` | **工人 / 自域执行 / 认领 Task** · `can_discuss=false` 语义 |
| Temporal / houtai-gongren | 耐久执行底座 · 不是聊天对方 |

**禁止再误会：** 把「交流软件 / 双 TUI 对话」演示或文档写成 `grok ↔ admin`。  
Admin 可接 Task、可当工人——**不进入双脑讨论主环**。

权威拓扑与角色：`桌面\主线\双脑\双脑主线_超级详细施工包.txt` §2.1 / roles；  
工程读我：`桌面\主线\双脑\00_工程读我_对齐工具胶水宪法_20260712.txt`。

## 本机落点

| 项 | 路径 |
|----|------|
| 二进制 | `D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe` |
| 通用/bootstrap 队列根 | `D:\XINAO_RESEARCH_RUNTIME\state\mailbox` |
| 双脑产品邮箱根（合同倾向） | `D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq` |
| 双脑 canary 邮箱根 | `D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\amq` |
| 句柄 | **主环** `grok` · `codex`；**工人** `admin`（可选存在，≠对话伙伴） |
| 证据 | `D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\S1_amq_mailbox.json` |

```powershell
$amq = 'D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe'
# 双脑主环示例根（有则优先；无则先 init 或暂用 bootstrap mailbox）
$r = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq'
if (-not (Test-Path $r)) { $r = 'D:\XINAO_RESEARCH_RUNTIME\state\mailbox' }
$env:AM_ROOT = $r
# 4.5 窗：$env:AM_ME = 'grok'
# Codex S 窗：$env:AM_ME = 'codex'
```

未入 PATH 时一律用 `$amq` 全路径。Windows 上 **核心队列可用**；`amq wake` 需 WSL。

## 目录约定（AMQ 官方，非自创）

```text
<AM_ROOT>/
  meta/config.json
  threads/
  agents/<handle>/
    inbox/{tmp,new,cur}    # 收：new 未读 → cur 已处理
    outbox/sent            # 发件副本
    dlq/{tmp,new,cur}      # 坏信
    receipts/              # 送达回执
```

原子投递：`tmp → new → cur`。

## 动作映射 open / post / list / ack

| 抽象动作 | 语义 | AMQ CLI |
|----------|------|---------|
| **open** | 打开/钉住本机邮箱根 + 身份 | `amq init --root <root> --agents grok,codex,admin,user`（一次性）<br>`$env:AM_ROOT=...; $env:AM_ME=...`<br>或每次 `--root` / `--me` |
| **post** | 投递一条消息 | `amq send --root <root> --me <from> --to <to> [--subject s] [--kind k] --body '...' [--json]` |
| **list** | 列未读 / 已读 | 未读：`amq list --root <root> --me <me> --new [--json]`<br>已读：`amq list ... --cur` |
| **ack** | 确认已处理（从 new 挪到 cur） | 单条：`amq read --root <root> --me <me> --id <id> [--json]`<br>批量：`amq drain --root <root> --me <me> [--include-body] [--json]` |

### 最小示例（主环：Grok 4.5 ↔ Codex S）

```powershell
$amq = 'D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe'
$r   = 'D:\XINAO_RESEARCH_RUNTIME\state\mailbox'   # 或 dual_brain_coordination\amq

# 4.5 窗 post → Codex
& $amq send --root $r --me grok --to codex --kind status --subject 'ping' --body 'hello from Grok 4.5' --json

# Codex S 窗 list / drain
& $amq list  --root $r --me codex --new --json
& $amq drain --root $r --me codex --include-body --json

# Codex 回复 → 4.5
& $amq send --root $r --me codex --to grok --kind answer --subject 'pong' --body 'hello from Codex S' --json
& $amq drain --root $r --me grok --include-body --json
```

### 非主环（勿当「俩 TUI 对话」示例）

```powershell
# admin = 工人句柄：派工/认领旁路可用；禁止写成双脑讨论默认对方
# & $amq send --root $r --me grok --to admin --kind todo --body 'worker task only'
```

### 可选

| 动作 | CLI |
|------|-----|
| 回复 | `amq reply --root <root> --me <me> --id <id> --body '...'` |
| 等新信 | `amq watch --root <root> --me <me>` |
| 健康 | 在项目 cwd 配 `.amqrc` 后 `amq doctor` / `amq doctor --ops`（doctor 无 `--root` 旗标） |

## 安装备忘（Windows）

- **非 npm 运行时**：`agent-message-queue` / `@avivsinai/amq-cli` 在 npm 上不是可执行二进制（skill 注册用）。
- **本机已用：** GitHub Release `amq_*_windows_amd64.zip` → `tools\amq\bin\amq.exe`。
- **备选：** `go install github.com/avivsinai/agent-message-queue/cmd/amq@latest`（Go 1.25+）。
- **macOS：** `brew install avivsinai/tap/amq`。
- **升级：** `amq upgrade` 或重下 release。

## 诚实边界

- S1 只钉：**默认可 invoke 的 AMQ 投递面** + 邮箱根 + 冒烟。
- 不等于双脑产品完工、不等于 333 主路、不等于已焊进所有 TUI 默认每回合 drain。
- **completion_claim_allowed=false**
