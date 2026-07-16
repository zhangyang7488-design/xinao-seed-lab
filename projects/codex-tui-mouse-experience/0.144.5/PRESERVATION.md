# 本地成品保留与清理边界

本版本另有一份独立冷归档：

`E:\XINAO_EXTERNAL_SOURCES\archives\codex-input-bridge\0.144.5-wt-1.24.11911.0-20260716`

它是后续大量清理时的保留对象，不属于 worktree、编译缓存、临时 canary 或一次性测试证据。

## 冷归档必须保留

- `package/`：与远端 `projects/codex-tui-mouse-experience/0.144.5` 相同的源码恢复包、ADR、手册、
  launcher/profile 和机器清单；
- `runtime/codex/`：用户验收过的 `codex-tui.exe` 与 `codex-code-mode-host.exe`；
- `runtime/windows-terminal/`：配对 exact-tag 的完整 portable Windows Terminal，含 `.portable`，不含
  会话 `state.json`；
- `desktop/`：验收入口的 `.lnk` 副本与 launcher 副本；
- 根目录 `archive-manifest.json`、`VERIFY.ps1` 和 `DO_NOT_DELETE.md`：文件身份、完整性校验和恢复说明。

这些文件足以在不保留几十 GB 构建缓存的情况下恢复已验收版本，或从源码恢复物重建。

## 可以另行清理但不是本次操作范围

源工作树、Cargo/MSBuild 增量缓存、临时 clone、测试日志和旧 canary 在确认冷归档完整后可以单独
分类；不能仅凭目录名相似把上述冷归档一并删除。稳定 Hardmode、`.codex`、账号配置、凭据、会话、
主线工作树和其他版本也不属于本包的清理授权。

## 恢复原则

1. 先运行冷归档根的 `VERIFY.ps1`；它必须同时通过包内固定产品身份和归档逐文件清单，全部
   SHA-256 匹配后才复制。
2. 把 `runtime/codex/` 与 `runtime/windows-terminal/` 恢复到新的版本化 D 盘目录，不覆盖未知对象。
3. 检查 launcher 中两个版本化路径和 hash；路径变化时只改路径，二进制 hash 必须仍匹配。
4. 先生成新的 side-by-side shortcut 做真实窗口验收；不要直接覆盖稳定 Hardmode。
5. 需要重建时按 `package/UPGRADE-RUNBOOK.md` 和两端 recovery 文件恢复源码；不要从旧 dirty worktree
   或旧 `Cargo.lock` 开始。

冷归档不包含 `CODEX_HOME`、密钥、登录数据、Terminal `state.json` 或聊天会话。它恢复的是输入桥
程序与可验证身份，不复制用户私密状态。
