# 输入桥后续升级手册

这份手册的目标是：下一次升级 Codex 或 Windows Terminal 时，不再重新发明输入框、不再重走
全局鼠标 hook、overlay、UIA 或终端全局 mouse mode 的旧路，而是把已经验收的薄桥迁到新的干净
上游基线，再做一次有限、可观察的回归。

## 先固定不变量

升级只能改变输入框里的普通左键定位与连续拖选。Delete、Backspace 和输入替换仍由 Codex 原有
`ChatComposer` / `TextArea` 完成。以下对象必须保持原生：

- 输入框视觉、布局、边框、颜色、光标、IME 和键盘编辑；
- Windows Terminal 输出区、scrollback、右侧滚动条、搜索、复制、`copyOnSelect`、滚轮、右键和中键；
- 模型、登录、`CODEX_HOME`、config、skills、plugins、Apps、MCP、memories、goals、agents、权限与会话；
- 稳定 Hardmode 入口、稳定 Terminal 安装、默认 Terminal 注册和稳定 settings。

若候选实现需要第二输入框、自绘 transcript、全局 hook、UIA 热路径、popup/overlay、Raw Input、
鼠标数据 named pipe 或 `EnableMouseCapture`，说明对象已经偏离，应停止而不是继续补丁叠补丁。

## 版本迁移顺序

1. 为 Codex 和 Windows Terminal 各建一个独立、干净、可丢弃的工作树；基线只能是目标版本的
   官方 exact tag。先记录 tag commit 和 tree hash。
2. 先阅读本包的 `design/0001-codex-composer-mouse-routing.md`，再查看目标 tag 中对应上游文件的
   当前结构。旧 patch 是语义地图，不是允许整包覆盖新版本的模板。
3. Codex 侧优先从本包的 recovery commit cherry-pick，或用 review patch 做三方应用。只迁移：
   composer/textarea 选区、frame 后区域声明、mouse event 接线和 Windows liveness 模块。
4. `TuiEvent::Mouse` 会令所有 exhaustive `match` 新增分支；非 composer 的 onboarding、migration、
   pager、picker、update 和 hook-review 界面只应显式忽略 Mouse，不能顺便改变其业务逻辑。
5. 永远以新 Codex tag 自带的 `Cargo.lock` 为起点。不得复制本包或旧实验的 `Cargo.lock`；只有
   新版本真实依赖变化才允许最小 lockfile diff。
6. Windows Terminal 侧只迁移 OSC dispatch、TerminalCore 声明身份、ControlCore liveness/connection、
   ControlInteractivity 手势 owner 和 TermControl 原生 pointer source 五个薄接缝。不得迁移视觉资源、
   settings schema、scrollback 或上游 selection 算法。
7. 保持协议 V1 的 13 字段、严格十进制解析、非零随机 token、generation 和命名 event 语义。
   若协议确实要升级，新增版本并保留未知版本 fail closed，不能静默改变 V1。

## 必须重新证明的关键语义

- 区域声明与 frame 同序走 stdout/ConPTY；鼠标手势走同一 pane 的 ConPTY 输入，不增加第二条布局通道。
- Windows Terminal 在左键 Down 时决定 owner，owner 在整次 Down/Drag/Up 中冻结。
- composer 外开始的拖动永远保持 Terminal 原生，即使后来进入输入框；composer 内开始则相反。
- Down 必须验证 cursor、viewport、buffer、mutation、scroll、buffer mode、token 和 liveness。
- 成功 Down 后，Drag/Up 不再比较 cursor、mutation 或 generation，因为合法重绘会改变它们；但仍验证
  冻结的 token/area、viewport、buffer、scroll 状态和 liveness。
- capture 丢失或 liveness 消失只合成一次 Up，并清空 gesture state。
- exact-width 行末保留 cell 可以命中；长输入拖出 textarea 上下边界会用现有 scroll 状态逐步延伸。

## 构建与测试顺序

1. 先跑格式、静态检查和专门单元测试；失败时只修真实差异，不用生成 PASS 文本替代。
2. Codex 至少重跑：协议编码/解析边界、composer Down/Drag/Up、textarea byte/grapheme 映射、
   exact-width、跨可见行 autoscroll、event-stream 顺序和非 mouse 事件不变性。
3. Windows Terminal 至少重跑 `TerminalApiTest` 与 `ControlInteractivityTests` 中的全部输入桥用例，
   包括坏声明、generation/disable、reserved cursor、pointer ID/device、pen、其他 pointer、右/中键、
   cancel 和一次性 Up。
4. 两端测试通过后再做 Release 构建。Codex TUI 与 code-mode host 顺序构建，复用缓存但不把缓存放进包。
5. Windows Terminal 只生成官方 unpackaged/portable distribution；保留 `.portable`，不执行
   `Add-AppxPackage`，不注册默认 Terminal 或 shell extension。
6. 复制稳定视觉配置时只复制 `settings.json`，不复制 `state.json`；运行前后核对稳定 settings hash。
7. 所有二进制、launcher、profile、portable manifest 和 shortcut 都记录字节数与 SHA-256。

## 真实窗口验收

自动化完成后仍必须在 side-by-side portable 窗口回验：

- 输入框单击定位；正向和反向连续拖选；Delete、Backspace、直接输入替换；
- wrapped ASCII、CJK、emoji、combining/ZWJ、exact-width 行末和长输入上下 autoscroll；
- composer 内开始后拖到输出区，owner 不变；输出区开始后拖过 composer，原生选择不变且无需 Shift；
- 输出区复制、`copyOnSelect`、搜索、scrollback、滚动条、滚轮、右键、中键、pen/touch；
- resize、DPI、历史/搜索 overlay、external-program return、alt buffer、多 tab/pane/实例；
- Codex 正常退出与 crash 后旧区域立即失效，系统 mouse capture 最终为 0。

只有用户在真实窗口确认体验，才允许把既有“输入框试验版”入口切到新版本。稳定 Hardmode 仍不改。

## 交付与归档

每个新版本都新建版本目录，不能覆盖这份 `0.144.5` 包。新包至少包含：两端 recovery
bundle/patch、ADR、launcher/profile、机器清单、测试结论、用户验收和独立冷归档说明。远端提交必须
证明相对 `origin/main` 只新增该版本目录；大二进制、portable Terminal 和构建缓存留在本地冷归档，
Git 只保存源码恢复物与精确身份。

`.gitattributes` 必须在第一次 `git add` 前就存在。若先暂存 CRLF 文件、后补 `-text`，Git index 可能
继续保留第一次清洗后的 LF blob；工作区 SHA 正确、`git status` 干净都不能证明远端字节正确。对每个
hash-pinned 文件，在提交前比较：

```powershell
git hash-object --no-filters -- <path>
git rev-parse :<path>
```

两者必须是同一个 object id。若不同，先 `git rm --cached -- <path>`，再在最终 attributes 已生效时
`git add -- <path>`，重新比较 object id。合并后必须从远端 `main` fresh clone，并按
`artifact-manifest.json` 逐文件复验；只在原 worktree 验 hash 不算远端交付完成。

## 一眼判错

出现以下任一情况就停止晋升并回滚候选入口：输出区需要 Shift、Drag 计数为零、选择一闪后消失、
产生第二窗口或透明面、其他 TUI 鼠标失效、跨 pane 串手势、崩溃后旧区域仍可命中、稳定 settings
变化、默认 Terminal 被注册、补丁带入旧 lockfile，或测试通过但真实用户无法持续拖选。
