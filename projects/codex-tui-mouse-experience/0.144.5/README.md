# Codex 0.144.5 输入框鼠标桥

状态：`verified_by_user_window_validation`

这是已经在真实窗口验收的 Codex 输入框鼠标桥交付包。交付仓是
`zhangyang7488-design/xinao-seed-lab`；`openai/codex` 与 `microsoft/terminal` 只是上游源码来源，
不是本包的发布远端。

## 交付边界

本次远端变更只能新增 `projects/codex-tui-mouse-experience/0.144.5/`。它不修改 0.144.4，
不夹带 F4、主线、模型配置或其他能力，也不提交编译缓存和大二进制。它不改变 Hook trust 或
hook-review 业务；`startup_hooks_review.rs` 只为新增事件枚举补一个 `TuiEvent::Mouse` ignore arm。

唯一新增的用户能力是：现有 Codex composer 可用普通左键点击定位、持续拖选，并由原有编辑器用
Delete、Backspace 或直接输入删除/替换选区。

必须保持不变：

- 输入框视觉、布局、边框、颜色、光标、IME、键盘编辑和唯一文本模型；
- Windows Terminal 原生输出区、scrollback、右侧滚动条、搜索、复制、`copyOnSelect`、滚轮、
  右键和中键；输出区普通左键拖选仍不需要 Shift；
- 模型、登录、`CODEX_HOME`、config、skills、plugins、Apps、MCP、memories、goals、agents、权限与会话；
- 稳定 `OPEN CODEX S HARDMODE.lnk`、稳定 Terminal、默认 Terminal 注册和稳定 settings。

用户已在真实窗口确认：输入框拖选、删除/替换和输出区负向行为符合预期，并明确回复
“可以，目前看没有问题；可以交付”。

## 最终架构

这不是第二个输入框，也不是 Codex 接管终端：

1. Codex 继续复用原有 `ChatComposer` / `TextArea` 处理布局、grapheme 边界、选区、渲染、删除和替换。
2. 每个完整 frame 后，Codex 在同一 stdout/ConPTY 流发送版本化 OSC 9001 `CodexComposer` 区域声明。
3. 配对的 Windows Terminal `v1.24.11911.0` 在上游 VT parser 中严格解析声明，并绑定当前 pane、
   viewport、buffer、cursor、mutation、generation、随机 token 和进程 liveness。
4. Windows Terminal 在自己的原生 XAML pointer source 处只对“composer 内左键 Down”接管本次手势；
   owner 在 Down 时冻结，Drag/Up 通过同一 pane 的 ConPTY 编码为标准 SGR mouse event 送回 Codex。
5. Codex 只在 `CODEX_TUI_MOUSE_COMPOSER_HOST=1` 时接收；它不发送终端全局 mouse-enable 序列。
6. 命名 event 只证明 Codex 进程仍活着，不传布局或鼠标数据；身份或 liveness 失效立即 fail closed，
   回到 Windows Terminal 原生路径。

完整协议、不变量、边缘语义、验收矩阵和成熟外部依据见
`design/0001-codex-composer-mouse-routing.md`。

## 为什么旧路线不能再用

| 路线 | 已见问题 | 最终结论 |
| --- | --- | --- |
| Crossterm `EnableMouseCapture` / 动态 VT mode | 它是终端全局模式；输出拖选需要 Shift；真实 canary 出现 `Down=1, Up=1, Drag=0` | 禁用，只对已归属 composer 手势定向注入 SGR |
| `WH_MOUSE_LL` + UIA/轮询 | 跨进程猜 geometry/pane/DPI/焦点；持续 Drag 丢失；hook 可被系统静默移除；出现过 COM 生命周期冲突 | hook、UIA 校准、轮询和吞事件全部废弃 |
| popup/overlay/透明输入面 | 第二窗口、焦点和 capture 生命周期；曾漏 `ReleaseCapture`，使其他 TUI 鼠标失效；同 HWND 不能区分 pane | 不再创建任何输入面 |
| Raw Input | 能观察 HID，不能取得另一进程特定矩形的 pointer owner 或 Terminal pane 身份 | 不进入热交互路径 |
| duplex named pipe / OSC + pipe | 两条布局通道没有共同顺序，resize/reflow 时会产生旧坐标；仍不能替宿主决定 owner | frame/声明同序走输出 ConPTY，手势走同 pane 输入 ConPTY |
| Codex 自绘 transcript/viewport | 功能能做，但输出对象不再是 Terminal 原生 scrollback/滚动条/selection | 0.144.4 旧实验不迁入 0.144.5 |

这也是为什么“看起来一样”不是完成尺：底层必须继续拥有正确的原生对象，不能只复制外观。

## 包内内容

- `source/`：Codex 与 Windows Terminal 的自包含 recovery bundle 和可审阅 patch；
- `.gitattributes`：禁止 Git/Windows 自动改写归档字节；bundle 按 binary，patch 保留原始换行并关闭
  对“补丁正文里的旧空白”的包装层误报；
- `design/0001-codex-composer-mouse-routing.md`：被接受的设计、否决路线、事故和完整验收矩阵；
- `UPGRADE-RUNBOOK.md`：下一版本从干净 exact tag 迁移、构建和真实窗口复验的固定短路；
- `PRESERVATION.md`：独立冷归档与后续清理边界；
- `launcher/Open-Codex-S-Input-Canary.ps1`：用户验收时的精确 hash-pinned launcher，不含秘密；
- `launcher/windows-terminal-profile.json`：配对 portable Terminal profile；
- `tools/Build-Local-Archive.ps1`：复制前先按交付 manifest 锁死 package、Codex runtime、WT 56 文件、
  shortcut/launcher 身份，再只收可恢复成品并排除会话状态和构建缓存；
- `tools/VERIFY.ps1`：复制后同时按固定产品身份与归档逐文件清单复验，无多余文件、无 Terminal state，
  并验证两份 Git bundle；
- `artifact-manifest.json`：所有源码、二进制、入口、测试、归档和不变项身份。

大二进制和 portable Terminal 不进入 Git；它们存入本地独立冷归档，manifest 记录字节数和 SHA-256。

## 源码恢复

### Codex：独立、离线可恢复工作树

```powershell
git -c core.longpaths=true -c core.autocrlf=false clone `
  --branch recovery/codex-input-wt-bridge-0.144.5 `
  "source/codex-input-wt-bridge-0.144.5.bundle" "D:\codex-input-bridge"
```

恢复后 HEAD 必须是 `3a7a19df93328b7fa3a098562f951c4e461f9d5c`，tree 必须是
`fa716bda2443b45cbd9e6d46ed2d5f7776075260`。

迁入官方 Git 历史时不要 merge 合成 orphan branch；从干净 `rust-v0.144.5` 开始，使用 patch：

```powershell
git switch --detach rust-v0.144.5
git apply --check --index --binary "source/codex-input-wt-bridge-0.144.5.patch"
git apply --index --binary "source/codex-input-wt-bridge-0.144.5.patch"
git diff --cached --check
```

官方 tag commit 是 `87db9bc18ba5bc82c1cb4e4381b44f693ee35623`，base tree 是
`c0163db45e747ae70030b4c4c1ebe33e2efb3ba3`。不要复制旧 `Cargo.lock`。

### Windows Terminal：独立、离线可恢复工作树

```powershell
git -c core.longpaths=true clone `
  --branch recovery/windows-terminal-composer-region-v1.24.11911.0 `
  "source/windows-terminal-composer-region-v1.24.11911.0.bundle" `
  "D:\wt-input-bridge"
git -C "D:\wt-input-bridge" config core.longpaths true
```

恢复后 HEAD 必须是 `2c8d7bf01a734710be366276c23250ac0dd657ce`，tree 必须是
`df29dbf6e6a3c909e715ac3cbbb00a5822780592`。

迁入官方 Git 历史时使用 patch：

```powershell
git switch --detach v1.24.11911.0
git apply --check --index "source/windows-terminal-composer-region-v1.24.11911.0.patch"
git apply --index "source/windows-terminal-composer-region-v1.24.11911.0.patch"
git -c core.whitespace=cr-at-eol diff --cached --check
```

官方 tag commit 是 `5a830b2bf7c053d5c7ac22208fe5a346cb5dd3dc`，base tree 是
`4d60079f92d8b13ade328f333da7e60edeffeaf2`。合成 bundle 的 base tree 与官方 tag 相同，但没有
upstream ancestry，不能直接 merge。14 个 touched 文件保持 CRLF，`adaptDispatch.cpp` 保持 LF；
不要批量规范化换行。Windows 全新检出使用短 D 盘路径和 `core.longpaths=true`。

## 已验证结果

- Codex：协议 helper 5/5、配对 event-stream sequence 1/1、新增 composer 4 + textarea 4 = 8/8；cargo check、
  格式/差异检查与 0.144.5 Release 构建通过；
- Windows Terminal：`TerminalApiTest` 13/13、`ControlInteractivityTests` 13/13，聚焦用例 3/3 + 1/1，
  Release portable package 0 errors；
- portable distribution：构建 manifest 56/56，保留 `.portable`；验收前无 `state.json`；
- 真实进程：portable `WindowsTerminal.exe` 与其子进程 `codex-tui.exe` 均来自 manifest 指定路径；
- 真实窗口：用户完成输入拖选、删除、替换及输出区负向检查并接受交付；
- 回滚：稳定 shortcut、launcher 和 settings 的 SHA-256 保持不变。

单元测试和 PASS 文本不代替真实窗口；下一次升级仍须执行 `UPGRADE-RUNBOOK.md` 的完整正负矩阵。

## 本地成品与回滚

活动入口：`C:\Users\xx363\Desktop\Codex 输入框试验版.lnk`。

独立保留归档：

`E:\XINAO_EXTERNAL_SOURCES\archives\codex-input-bridge\0.144.5-wt-1.24.11911.0-20260716`

归档完成后可清理被它替代的本次 source worktree、build cache、publication staging 和临时验证目录，
但不能删除活动快捷方式实际引用的 D 盘 Codex runtime 与 portable Terminal。稳定 Hardmode 也不属于
本包清理范围。

回滚时关闭明确属于 canary 的进程，启动未修改的稳定 Hardmode；不按窗口外观、HWND 或相似进程名
猜测并终止其他会话。无需卸载、无需改默认 Terminal、无需恢复系统级 mouse hook，因为最终方案没有
安装这些对象。

## 安全与所有权

包和冷归档都不复制 `CODEX_HOME`、密钥、登录数据、聊天会话或 Terminal `state.json`。
`secrets_copied=false`。所有恢复和升级都先验证 hash，再在 side-by-side 目录启动；不得把配置存在、
进程存在或报告写着 PASS 当成用户体验已恢复。
