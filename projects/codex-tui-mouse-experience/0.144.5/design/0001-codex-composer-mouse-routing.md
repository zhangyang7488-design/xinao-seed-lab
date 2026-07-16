# ADR 0001: Codex composer 鼠标手势按起点归属

- 状态：Accepted
- 正式 Codex 基线：`rust-v0.144.5`
- 配对宿主基线：Windows Terminal `v1.24.11911.0` exact tag
- 范围：仅 Windows Terminal 中 Codex composer 的鼠标定位与拖选

本记录固定设计意图和被否决路线，不代表某个二进制已经通过真实窗口终验。运行时是否可晋升，仍以本文的验收矩阵和独立证据为准。

## 用户不变量

唯一允许新增的可见能力是：Codex 现有输入框可以用普通左键点击定位、持续拖选，并用 Delete、Backspace 或直接输入替换选区。

以下都必须保持原对象、原路径和原体验：

- 输入框的布局、边框、颜色、光标、提示、IME 和键盘编辑不变；不叠加第二个输入控件。
- 输入框外的 transcript、scrollback、右侧滚动条、滚轮、右键、中键、原生选择、复制和 `copyOnSelect` 仍由 Windows Terminal 拥有。
- 输出区普通左键拖选不需要按 Shift；从输出区开始后即使越过输入框，也不能被 Codex 抢走。
- 不改变模型、登录、`CODEX_HOME`、config、skills、plugins、Apps、MCP、memories、goals、agents、权限或会话语义。
- 未配对、声明失效、身份不清或进程死亡时必须退回 Windows Terminal 原行为，而不是猜测。

## 决策

复用两端已有成熟对象，只补一个最薄的区域声明与手势路由接缝：

1. Codex 继续使用现有 `ChatComposer` 和 `TextArea` 作为唯一输入 UI、文本模型、Unicode 边界、选区状态、渲染、删除和替换实现。这里不是重写输入框。
2. 每个完整 frame 绘制完成后，Codex 在同一 stdout/ConPTY 输出流中发送私有、版本化的 OSC 9001 `CodexComposer` 声明。声明与画面写入具有同一顺序，不建立第二条布局数据通道。
3. exact-tag Windows Terminal 在其既有 VT parser 中解析声明，把区域绑定到 token、generation、当前 viewport、buffer、cursor 和 buffer mutation。
4. Windows Terminal 继续使用自己的 XAML pointer 事件和 pointer capture。只有“鼠标左键 Down 且命中有效 composer 区域”才把本次手势交给 Codex；其他事件进入上游原路径。
5. 手势 owner 在 Down 时冻结：
   - composer 内开始：Down、全部 Drag、Up 都由 composer 拥有，即使指针移出区域；
   - composer 外开始：整个手势保持 Windows Terminal 原生，即使随后进入区域。
6. Windows Terminal 把 composer 手势编码为标准 SGR mouse Down/Drag/Up，并通过同一个 ConPTY 输入连接发给 Codex。Codex 只在显式配对模式 `CODEX_TUI_MOUSE_COMPOSER_HOST=1` 下接收这些 mouse events；不发送终端全局 mouse-enable 序列。
7. Codex 创建进程拥有的命名 event：`Local\\Xinao.CodexComposer.v1.<WT_SESSION>.<nonzero-random-token>`。Windows Terminal 每次开始和继续手势都检查它；Codex 退出或崩溃时 handle 关闭，旧区域立即失去资格。这个 event 只证明存活，不承载布局或鼠标数据。
8. parser 与 Down 命中严格 fail closed。未知版本、字段数错误、超长/非数字/越界字段、零 token、旧 generation，或 Down 时 cursor、viewport、buffer、mutation、scrollback、main/alternate buffer、liveness 任一身份不匹配，都不得开启 composer 手势。Down 成功后 owner 冻结；continuation 只验证该手势冻结的 token/area、viewport、buffer、scroll 状态与 liveness，不再比较 cursor、mutation 或 generation，因为 composer 自己处理 Drag 后的重绘会合法地产生新 cursor、mutation 和 generation。捕获丢失或 continuation 中途失效只合成一次 Up，并回收 gesture state。

协议 V1 固定为 13 个分号字段：

```text
CodexComposer;1;TOKEN16;GEN;COLS;ROWS;ENABLED;X;Y;WIDTH;HEIGHT;CURSOR_X;CURSOR_Y
```

OSC 封装为 `ESC ] 9001 ; <declaration> BEL`。`ENABLED=0` 清除同 token 的区域，并把坐标字段归零。

## 为什么这是“复用”，不是再次手搓 UI

Codex 端复用 `codex-rs/tui/src/bottom_pane/chat_composer.rs` 与 `codex-rs/tui/src/bottom_pane/textarea.rs`；新增的 `codex-rs/tui/src/windows_composer_mouse.rs` 只发布布局身份和存活信息。frame 后发布入口在 `codex-rs/tui/src/app.rs`、输出接线在 `codex-rs/tui/src/tui.rs`，输入事件仍走 `codex-rs/tui/src/tui/event_stream.rs`。

Windows Terminal 端复用 exact-tag 的原生 pointer capture、pointer lifecycle、ConPTY connection 和原生 output selection：

- `src/cascadia/TerminalControl/TermControl.cpp`：既有 XAML PointerPressed/Moved/Released/CaptureLost 生命周期；
- `src/cascadia/TerminalControl/ControlInteractivity.cpp`：既有 pointer 坐标、modifier、原生选择和连接写入路径；
- `src/cascadia/TerminalCore/TerminalApi.cpp`：OSC 声明的严格解析与命中身份；
- `src/terminal/adapter/adaptDispatch.cpp`：从现有 OSC 9001 dispatch 接入 `CodexComposer` action。

因此本地代码不复制 Windows Terminal 的渲染器、滚动条、选区或窗口系统，也不复制 Codex 的编辑器。新代码只回答两个问题：“当前哪一小块是 composer？”和“这个 Down 开始的手势归谁？”

## 被否决路线与已见失败

### Crossterm `EnableMouseCapture` / 动态 VT mouse mode

`EnableMouseCapture` 是会话/终端级模式，不是矩形级命中协议。开启后普通输出拖动先送给应用，Windows Terminal 原生选择通常需要 Shift，直接违反“输出区不变”；动态开关仍存在 Down 与 Drag 分属不同状态的竞争。历史 hybrid canary 的真实窗口记录是 `Down=1, Up=1, Drag=0, selection_len=0`。所以本方案禁止 `EnableMouseCapture`，只让配对宿主对已归属手势定向注入 SGR。

### `WH_MOUSE_LL` + UI Automation/轮询

该路线让 Codex 跨进程推断另一个窗口中的区域、pane 身份、DPI、焦点和时序，并选择性吞掉系统鼠标事件。真实窗口多次出现 Down/Up 有而持续 Drag 为零；短自动化曾通过，但随后真实用户拖动“短暂出现后失效”。低级 hook 还可能超时后被静默移除。UI Automation caret/geometry 是可访问性观察面，不是 pointer ownership 协议；旧路径还出现过 COM `IUnknown` 生命周期访问冲突。可复用的只有 Codex 内部选区语义，hook、UIA 校准、轮询和吞事件全部废弃。

### popup / overlay / `WH_MOUSE_LL` 透明输入面

独立 popup/overlay 会制造第二个窗口、焦点和生命周期，无法天然继承真实 tab/pane/TUI 身份、IME、可访问性和 frame 几何。历史 `WS_EX_NOACTIVATE | WS_EX_NOREDIRECTIONBITMAP` 面曾在 `SetCapture` 取消路径漏掉 `ReleaseCapture`，造成其他 TUI 也收不到正常鼠标；hide 与异步 refresh 竞争又让面重新出现。同一 host HWND 还不能区分 tab/pane。这个事故说明“视觉透明”不等于行为透明，因此不再创建任何输入 popup、overlay 或全局 hook。

### Raw Input observer

Raw Input 是应用注册设备后通过 `WM_INPUT` 获取 HID 数据的成熟观察接口，适合高频设备数据；它不提供“替另一个进程的特定矩形取得 pointer owner”，也不提供 Windows Terminal 的 tab/pane/ConPTY 身份。把它叠加到现有窗口消息只会再次要求自行校准坐标、焦点、Down owner 和事件吞吐，不能解决核心边界，所以不采用。

### UI Automation

UIA 保留给可访问性和测试观察，不用作交互传输。caret 或 bounding rectangle 可能随 DPI、resize、scroll、焦点、字体和 frame 更新而变化，且没有与 ConPTY buffer mutation 的总序；它既不能安全捕获鼠标，也不能证明事件属于哪个 pane。旧 COM 生命周期崩溃进一步说明不应把它放进热 pointer 路径。

### duplex named pipe 或 OSC + pipe

单独 named pipe 不能让 Windows Terminal 在自己的 pointer source 处决定 owner；仍需宿主改动。若用 OSC 声明画面、再用 pipe 发送区域或鼠标，就会形成两条无共同顺序的通道：resize/reflow/输出写入可能先到，pipe 中的旧坐标后到，或者反之，还增加连接、重连、背压和身份生命周期。选定方案让“frame + 区域声明”同序走输出 ConPTY，“SGR gesture”走同一 pane 的输入 ConPTY；唯一旁带对象只是无数据的 crash-liveness event。

### Codex 接管整个 transcript/viewport

该路线可以让自有输入与自有 transcript 复制工作，但输出对象已不是 Windows Terminal 原生 scrollback。它不能等价保留右侧滚动条、跨屏选择、`copyOnSelect`、终端搜索和跨区域手势；“视觉接近”不能替代“输出对象不变”。历史 0.144.4 app-owned viewport 实现因此属于“功能可用但对象错误”，不迁入正式基线。

## 两个必要边缘修复

### exact-width 行末

文本恰好填满一行时，Ratatui 光标可以位于 `area.right()` 的保留 cell，而通常的 `Rect::contains` 右边界是 exclusive。若照普通矩形命中，最后一个字符无法从行末拖选。composer mouse area 因此只在右侧扩一格，`cursor_from_screen_position` 允许 `column == area.right()` 并映射到该 wrapped line 的末尾；OSC 和 WT parser 也允许 cursor 位于 composer 的 exclusive-right cell，但仍要求它在终端 viewport 内。

### 长输入跨边界拖选

指针拖到 textarea 上方或下方时，不能永久钳在当前可见两行。`extend_selection_from_mouse_drag` 使用与 render/keyboard 相同的 `TextAreaState.scroll`，按指针越界距离逐个 Drag 推进或回退 wrapped-line viewport，再从稳定 byte anchor 延伸选区。列坐标钳到 `[left, right]`；UTF-8、CJK、emoji、combining mark、ZWJ 和原子 text elements 在设计上继续由现有 grapheme/element boundary 规则处理，其中 combining mark/ZWJ 仍需显式自动化用例和真实窗口验收，不能由一般 grapheme 测试代替。

## 基线与迁移规则

- 正式 Codex 基线只能是干净的 `rust-v0.144.5`。0.144.4 冻结事故包、dirty worktree、旧二进制和旧 `Cargo.lock` 只作历史证据，不得作为 build base，也不得整包 cherry-pick。
- 从旧实验仅按本 ADR 语义迁移最小源码接缝和相应测试；每次升级都重新对照新 tag 的 `ChatComposer`、render/frame 和 event-stream 结构。
- 配对 Windows Terminal 必须从 `v1.24.11911.0` exact tag 构建；不要用相似版本的预装二进制冒充。若将来升级 WT，先重做上游 pointer/selection diff 与完整负回归。

## Side-by-side 交付与回滚

第一阶段只生成 portable Windows Terminal canary：

- 用上游 unpackaged distribution 的 Portable Mode 产物，保留 `.portable`；放在独立版本目录，与稳定 Terminal 并存。
- canary 可复制稳定 `settings.json` 作为初始视觉配置，但不复制 `state.json`；记录稳定 settings 文件的 SHA-256，运行前后必须相同。
- 不执行 `Add-AppxPackage`，不注册为默认 Terminal，不注册 shell extension，不覆盖稳定安装、稳定二进制或正式快捷方式。
- Codex 与 WT 都用版本化、hash-pinned 路径；只有真实矩阵通过后，才允许把既有入口原子切换到已验证版本，同时保留前一 launcher 和 binaries 作为独立 rollback。

回滚不需要卸载：关闭 portable canary、清除配对环境变量并运行未改的稳定入口。若发生 capture/liveness 异常，只终止明确属于 canary 的进程；不得按窗口外观、HWND 或同一 Windows Terminal host 猜测并关闭其他会话。回滚后再次确认稳定 settings SHA-256、默认 Terminal 注册和系统 mouse capture 均未改变。

## 验收矩阵

| 类别 | 操作 | 必须观察到 | 必须不发生 |
| --- | --- | --- | --- |
| 输入正向 | 单击 composer 不同位置 | 光标落到现有 grapheme/element 边界 | 新窗口、视觉层或焦点跳转 |
| 输入正向 | composer 内 Down 后正向/反向持续 Drag，再 Delete/Backspace/输入 | 高亮连续更新；只删除或替换选区；一次 Up 收口 | Drag 为零、卡住 capture、重复 Up |
| 输入边缘 | wrapped ASCII、CJK、emoji、combining/ZWJ、exact-width 行末 | 字符不被 UTF-8 截断；可选中最后一个 grapheme | 半个宽字符、越界 cursor |
| 输入边缘 | 长输入拖到 textarea 上/下方并继续移动 | viewport 逐步滚动，稳定 anchor 继续扩展 | 只钳在可见首/末行 |
| owner 正向 | composer 内 Down 后拖到输出区并松开 | 全程仍是 composer 手势 | 中途变成 Terminal selection |
| owner 负向 | 输出区 Down 后拖过 composer 并松开 | 全程为 Windows Terminal 原生选择；无需 Shift；复制正常 | Codex 收到 Down/Drag/Up |
| 输出负向 | 输出区点击/拖选、跨屏选择、`copyOnSelect`、搜索、scrollback、右侧滚动条 | 与稳定版本对象和体验一致 | app-owned transcript 或自绘 scrollbar |
| 其他按键 | wheel、右键、中键、pen、touch | 进入 exact-tag 上游原路径 | 被 composer 区域声明吞掉 |
| 生命周期 | resize、DPI/window move、overlay/history/search、external-program return、alt buffer | 新 frame 重新声明或清除；无效时原生 fail closed | 旧区域继续命中 |
| 身份隔离 | 多 tab、pane、实例；Codex crash/exit | 只有声明所在 ConPTY 且 liveness 存在时可命中 | 同 host HWND 下串到其他 pane |
| 分发负向 | 不配对 WT、缺 `WT_SESSION`、坏 OSC、旧 generation、区域越界、scrollback 非底部 | 不开启 composer 手势 | 猜测、降级成 hook/pipe |
| 系统不变量 | canary 前后检查 | 稳定 settings SHA-256 相同；默认 Terminal/注册不变；mouse capture 最终为 0 | 安装、注册或残留全局 capture |

单元测试不是最终用户证明，但必须覆盖回归边界：

- Codex `windows_composer_mouse.rs`：GUID/session 校验、固定字段编码、越界 fail closed、disabled 清零、exact-width reserved cursor。
- Codex `bottom_pane/textarea.rs`：screen-cell 到安全 byte/grapheme 映射、exact-width 最后字符。
- Codex `bottom_pane/chat_composer.rs`：Down/Drag/Up 高亮与删除、composer 区右扩一格、上/下越界 autoscroll。
- Codex `tui/event_stream.rs`：配对模式下 Down/Drag/Up 顺序，非 mouse 事件不变。
- WT `src/cascadia/UnitTests_TerminalCore/TerminalApiTest.cpp`：`CodexComposerRegionStrictParsing`、`CodexComposerRegionGenerationAndDisable`、`CodexComposerRegionAcceptsReservedCursorCell`。
- WT `src/cascadia/UnitTests_Control/ControlInteractivityTests.cpp`：`CodexComposerPointerLifecycle` 当前覆盖 Down/Drag/Up 与 capture cancel 一次性 Up。
- 待补自动化并进入真实窗口验收：WT modifier 编码/透传、composer 外 Down 不接管；Codex combining mark/ZWJ 的定位、跨 grapheme 拖选与删除/替换。在相应用例落地前，不得把这些项目记作已覆盖。

最终晋升还必须在 portable 真实窗口逐项手测正负矩阵，并与稳定入口 side-by-side 比较；配置、进程存在、PASS 字样或只跑单元测试都不能代替该证明。

## 维护时的静态护栏

- Codex 生产代码不得出现 `EnableMouseCapture`、`WH_MOUSE_LL`、UIA、Raw Input、popup/overlay surface 或鼠标数据 named pipe。
- WT patch 只能位于 OSC dispatch、TerminalCore identity、ControlCore liveness/connection、ControlInteractivity gesture 和 TermControl pointer source 的薄接缝；不得改视觉资源、settings schema、scrollback 或原生 selection 算法。
- 每个新 Codex tag 都以 tag 自身 lockfile 为起点，只接受因实际依赖变化产生的最小 lockfile diff。
- 文档、launcher 和 evidence 必须写明两端确切版本和 hash；不能把 0.144.4 历史产物描述成 0.144.5 证明。

## 外部成熟依据

- Microsoft `SetCapture`：capture 属于一个窗口/线程且必须配对释放，也不能替另一个进程捕获输入。<https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setcapture>
- Microsoft Raw Input：应用注册 HID 后通过 `WM_INPUT` 取得原始数据；这是设备输入接口，不是跨进程区域 owner 协议。<https://learn.microsoft.com/en-us/windows/win32/inputdev/about-raw-input>
- Crossterm 0.28.1 `EnableMouseCapture`：终端 mouse capture command，而非矩形路由。<https://docs.rs/crossterm/0.28.1/crossterm/event/struct.EnableMouseCapture.html>
- Windows Terminal `v1.24.11911.0` 原生 pointer source/capture：<https://github.com/microsoft/terminal/blob/v1.24.11911.0/src/cascadia/TerminalControl/TermControl.cpp#L2013-L2170>
- Windows Terminal `v1.24.11911.0` 原生选择与 mouse lifecycle：<https://github.com/microsoft/terminal/blob/v1.24.11911.0/src/cascadia/TerminalControl/ControlInteractivity.cpp#L252-L494>
- Windows Terminal 官方 portable/unpackaged distribution：<https://learn.microsoft.com/en-us/windows/terminal/distributions>
- xterm SGR mouse report 格式（1006）：<https://invisible-island.net/xterm/ctlseqs/ctlseqs.html>

## 结论

这个方案的核心不是“再做一个输入框”，而是在 Windows Terminal 已有 pointer source 处按 Down 决定 owner，再把 composer 手势送回 Codex 已有编辑器。它用同一 ConPTY 的顺序、exact pane identity、进程 liveness 和 fail-closed 校验消除旧桥接的几何/时序猜测，同时把输入框之外的每一种交互留在原生路径。
