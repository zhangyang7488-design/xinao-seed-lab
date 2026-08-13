本机代理系统完整认识论
======================

更新时间：2026-08-13 16:24（Asia/Shanghai）

这份文本是以后处理这台机器上代理、网络、Vortex/Mihomo、7897、浏览器、网页 ChatGPT、Codex、Cloudflare 验证和文件上传时的第一入口。

它不是某一天的节点记录，也不是一份“当前配置说明”。它保存的是：

  - 这套本机网络系统由哪些彼此独立又相互作用的层组成；
  - 历史上哪些不同形态都曾真正好用；
  - 什么已经证实有效，什么只局部有效，什么无效，什么是错药，什么会毁掉整套形状；
  - 哪些表象最容易让人和 AI 误判；
  - 如何从真实消费者和连接证据判因、修复、回滚与验收；
  - 当前仍然未知、不能夸大的边界。

当前节点、区域、速度和路径只是一张带时间的现场切片。以后必须先读本档，再 fresh readback live 状态，不能把任何历史切片自动当成现在。


零、当前总判断
--------------

1. 这台机器当前已经基本恢复到历史上“日常好用”的状态。

   网页、文本和约 10 MiB 文件都已达到用户可接受门槛。10 MiB 是本轮“日常上传恢复”的真实验收尺；100/200 MiB 长传是另一类稳定性问题，尚未用同等级真文件验收，不能拿它反向否定 10 MiB 已恢复，也不能提前宣称百兆已修好。

2. 当前恢复不是“找到了一个神节点”。

   它来自整套关系重新正确：live rule、系统代理 7897、分组仍分治、TUN 关、tcp-concurrent 关、绕过名单保留、浏览器没有继续握着错误叶子的旧连接。节点只是其中一个可变叶子。

3. 小 TXT 正文看起来秒传、最后再停 1–2 秒，不是当前上传带宽仍慢。

   2026-08-13 16:15–16:16 对连续小 TXT 的 live 采样显示：每次会新开一个服务端分配的区域化 oaiusercontent 连接，正文量约 23–59 KiB；对象存储在约半秒量级回响应，随后 chatgpt.com / ws 仍有附件登记与页面确认交换。体感最后 1–2 秒主要是：取得/使用上传目标、TLS、对象存储确认、ChatGPT 附件登记和 UI 就绪这几个串行尾段，不是 TXT 字节还在慢慢传。

4. 已检查并排除了当前可安全修的本机尾段旋钮。

   - Edge 没有残留“禁用 QUIC”实验项；enabled_labs 为空；
   - Edge 网络预测没有被本机偏好强制关闭；
   - 当前 7897 到五个本轮真实出现的 oai 区域均比直连探针更快；
   - 因而把 oaiusercontent 改直连、再开 TUN、再开 tcp-concurrent、乱切节点或每次都清健康连接，都会增加握手或破坏已经恢复的 10 MiB 基线。

   当前“修复”结论是：可控的错误设置已经不在；保留健康连接与当前路径。剩下约 1–2 秒属于网页附件协议/远端确认的正常尾段，目前没有已证安全的本机消除项。只有它以后明显增长、失败或影响发送，才按本档重新抓单次三拍，不能为了追零点几秒先把整机网络改坏。

5. Cloudflare 是用户记忆里那个验证公司，常见机制叫 Turnstile/Challenge。

   它不负责 ChatGPT 附件上传，但 Cloudflare 验证和 ChatGPT 上传都会敏感暴露代理出口的通用海外上行质量。它是同构旁证和判因尺，不是上传修复本身。


一、系统本体：代理不是一个开关或一个节点
----------------------------------------

这台机器上的代理是一套多层出站系统。任何一层变化，都可能让“整体好用”变成“局部绿但真实消费者坏了”。

1. Windows WinINET 系统代理

   活对象：ProxyEnable、ProxyServer、ProxyOverride、Connections 二进制。
   当前常用入口：127.0.0.1:7897。
   真相来源：HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings。

   关键关系：系统代理开着，不等于所有域名都进入 7897。ProxyOverride 中的微软、Azure、windows.net 等目标会绕过本地代理。完整走代理和半直连半绕过，在本机历史上都曾正常，不能把其中一种写成唯一真理。

2. 用户与进程环境变量

   HTTP_PROXY、HTTPS_PROXY、ALL_PROXY、NO_PROXY 会影响终端和部分应用。
   环境变量表面与浏览器 WinINET 表面可以不同。终端能联网不能证明浏览器走同一路；浏览器能开也不能证明某个 CLI 进程继承了正确变量。

3. GW/Vortex 应用层

   活对象：proxy_mode、tun、prefer_nodes、连接状态。
   主要文件：C:\Users\xx363\AppData\Roaming\gw\vortex.json。

   关键关系：UI/JSON 与 helper 内核 live 状态可能短暂双轨。界面显示、偏好文件和实际连接必须分开读。

4. Mihomo/Vortex helper 内核

   mixed port 当前为 7897；控制口现场通常是 http://127.0.0.1:39798。
   真正运行态：

     GET /configs       mode、tun、tcp-concurrent 等
     GET /proxies       selector 当前选择、节点状态
     GET /connections   process、host、rule、chains、start、upload/download

   连接表是判断真实消费者当前走哪条线的核心证据。selector 的 now 只说明新连接会选什么，不说明旧连接已经迁移。

5. 磁盘 config.yaml

   它是订阅和可重载模板，包含节点、规则、DNS、mode、tun 等；不是自动等于 live 状态的权威镜像。
   这台机器历史上长期出现“磁盘 mode: direct、live mode: rule”。未经核对就 force reload，会把模板假象灌成运行真相。

6. 规则、selector 与节点叶子

   规则决定流量进入哪个职责组；selector 决定该组的新连接使用哪个叶子；节点只是一片可更换叶子。
   分组分治是系统结构，具体节点编号不是永久系统定义。

7. TUN、虚拟网卡与 Tailscale

   Vortex JSON 的 tun、Mihomo /configs 的 tun.enable、Meta Tunnel 网卡是否存在，是三个必须交叉验证的事实。
   Tailscale 是另一套独立网络，不等于代理 TUN，也不能拿 Tailscale 在线证明代理 TUN 状态。

8. DNS、fake-ip、SNI 与协议

   DNS/fake-ip 会影响规则能否按主机名匹配；TLS/SNI、HTTP/2、HTTP/3/QUIC 会影响握手和连接复用。
   但协议名不是自动修复权。只有真实消费者 A/B 证明某个协议设置是断层，才改它。

9. 浏览器和应用自己的连接池

   Edge、Chrome、Codex 都会保存 TCP/TLS/WebSocket/HTTP2 连接。改变 selector 不会让已建立连接自动换线。
   旧连接既可能造成“连接裂脑”，也可能是健康复用、减少握手的资产。只在换线后或证实粘错叶子时精确清理，不能每次上传都清空。

10. 远端服务与动态区域

   ChatGPT 页面、WebSocket、会话 API、附件登记、文件对象存储是不同远端组件。
   sdmntpr 后缀区域由服务端调度，本机不能指定。相同本机路径在不同时间可能被派往 eastus2、westcentralus、australiaeast、japaneast、nznorth、indiasocentral 等；区域差异会改变短时体感。


二、流量类别与真实消费者
------------------------

1. 国内流量

   百度、中国 IP 等通常 DIRECT。它是“本机基础网络是否还活着”的尺，不是海外代理质量尺。

2. 网页 ChatGPT 页面、文本与 WebSocket

   chatgpt.com / ws.chatgpt.com 等 -> ai 组。
   页面能开、HTTP 200、甚至一条 ws 正常，都不能证明文本链路整体正常。页面和 ws 若粘在不同节点，用户可以直接表现为“连文本都发不出”。

3. 网页 ChatGPT 文件正文

   sdmntpr*.oaiusercontent.com -> ai 组。
   这条长传与页面、静态资源、WebSocket 不同。小附件能挂上不证明百兆长传稳定；大上传卡住也不等于规则没命中 ai。

4. ChatGPT 静态资源

   oaistatic.com 等主要提供前端资源，不是文件正文吞吐尺。

5. Codex

   当前规则按 ProcessName 把 codex.exe 送到“国外流量”，当前实例叶子为香港 Pro-06；网页 Edge 的 ChatGPT 则走 ai。
   因而一个 Codex 窗口出现“Falling back from WebSockets to HTTPS transport”或“tls handshake eof”，而其他 Codex 和 Edge 正常，优先判为该进程/该连接的局部问题，不能上卷成整机断网，也不能因此改网页 ai。

6. 普通国外流量

   X、Google、GitHub 等是整机浏览验收面。任何上传优化若让这些站明显变卡，都不是系统改善。

7. 国外媒体

   YouTube、Netflix 等可由自动选择承担。媒体吞吐不能代替 ChatGPT 上传尺。

8. 其他流量与 Cloudflare

   未命中特定规则的流量进入“其他流量”。challenges.cloudflare.com、static.cloudflareinsights.com 等在当前规则下通常落到这里。
   Turnstile 好不好用可暴露通用海外出口质量，但不与 oai 文件桶共享同一业务服务。

9. Windows/Azure 旁路

   ProxyOverride 中的目标根本不进入 7897。它能改善微软登录或某些 Azure 路径，但不能解释全部 ChatGPT oai 长传，也不能抹掉“完整代理历史上也曾正常”的事实。


三、历史上不止一种正常形态
--------------------------

本机历史事实不支持“只有半直连才好”或“只有所有流量都走代理才好”。至少两套形态都曾达到用户正常体感：

1. 完整代理形态

   浏览器/本机主要海外出口完整进入 7897，规则分治仍在；历史上网页 ChatGPT 和大上传也曾可接受。

2. 系统代理 + 精确旁路形态

   系统代理仍开，但微软/Azure/windows.net 等经 ProxyOverride 绕过 7897；2026-07-09 好用快照属于这类，上传和日常浏览也曾正常。

成熟结论：

  - 好用是消费者效果和系统关系，不是一个唯一拓扑口号；
  - 绕过名单是重要工具，但不是所有上传问题的根因解释；
  - 8 月 11 日后真正被破坏的是多层形状与长连接现场，不只是一个节点；
  - 恢复优先重建关系，再根据真实消费者选择叶子。


四、2026-08-13 当前可接受现场切片
----------------------------------

以下只是一张恢复与对照用的 live 快照，不是永久节点真理：

  live mode                 = rule
  Windows 系统代理          = 开，127.0.0.1:7897
  ProxyOverride             = 约 560 字，保留微软/Azure/windows.net 等
  Vortex TUN                = false
  Mihomo live TUN           = false
  Meta Tunnel               = 不应存在
  tcp-concurrent            = false
  GLOBAL                    = 新加坡 Pro-02
  ai                        = 新加坡 Pro-02
  其他流量                  = 新加坡 Pro-02
  国外流量                  = 香港 Pro-06
  国外媒体                  = 自动选择
  OpenAI/ChatGPT/oai 规则    = ai
  codex.exe 进程规则         = 国外流量

真实 10 MiB 验收：

  文件：C:\Users\xx363\Desktop\当前新仓库完整快照_20260813_121959.zip
  大小：10,622,590 字节（10.13 MiB）
  SHA256：81CD12C5C365C2F5BF2FA6D418C08F9BA370FADBEFF37204C8284FD6D61147A6
  目标：sdmntpreastus2.oaiusercontent.com
  路由：Edge -> 127.0.0.1:7897 -> ai -> 新加坡 Pro-02
  live upload：10,669,447 字节（含协议开销）
  用户验收：“目前都是能接受的速度，不是特别特别慢。”

本轮分级结论：

  网页/文本                 已恢复
  小 TXT                    正文秒传，尾段约 1–2 秒可接受
  10 MiB 级上传             已恢复到用户可接受门槛
  100/200 MiB 长传          未重新验收

更早误判必须保留：

  “新澳原始直觉意图1.7z”实际只有 251,407 字节（约 245 KiB），不是 200 MiB。它秒挂只证明小附件路径恢复，不能证明大上传恢复。
  15:38 一轮 westcentralus 长上传经同一 Pro-02 约 0.29 MB/s，用户判断仍慢。它证明当时那条区域长连接慢；后来 10.13 MiB eastus2 可接受，说明文件大小、区域和当时连接质量必须分开。


五、已经证实有效的做法
----------------------

1. 先绑定真实消费者，再读系统层。

   先问坏的是：一个 Codex、所有 Codex、Edge 文本/ws、小文件、10 MiB、百兆长传、X/Google，还是整机。不同消费者不能互相代替。

2. live API + 实际连接联合判因。

   /configs 和 /proxies 说明形状；/connections 说明消费者正在走的真实叶子。两者缺一不可。

3. 一次只动一个具名变量，先留 preimage。

   只改一个 selector、一个开关或一层设置；回读后用真实消费者验收。失败立即恢复 preimage，不叠第二刀。

4. 保持分组分治。

   ai、国外流量、其他流量和 GLOBAL 有不同职责。叶子可以相同，但不能用脚本把职责本身永久拍扁，也不能为测速同时切多组。

5. 本机默认 TUN 关、tcp-concurrent 关。

   这是本机实测合同，不是对 Mihomo 产品的一般定律。开 TUN 曾毁普通网页；开 tcp-concurrent 曾造成时快时慢和“无法加载使用数据”；关回后用户确认恢复。

6. 仅在必要时精确清旧连接。

   任何 ai selector 变化后，若 Edge 仍握着旧叶子，精确删除 msedge.exe 且 host 属于 chatgpt/ws/oai 的旧连接，再让浏览器重连。
   正常上传之间不要清健康连接，否则会重复付出 TLS/区域握手，反而让小 TXT 尾段更长。

7. 上传用真实文件和真实字节验收。

   看新出现的 sdmntpr host、rule、chain、upload 字节增长、总耗时和用户体感。延迟、HEAD 200、附件栏图标和小 PUT 只证明各自局部事实。

8. 普通网页是不可牺牲的联动验收。

   上传探针变快但 X/Google/国内站毁了，立即回滚该刀。

9. Cloudflare 可作通用上行旁证。

   本轮 Cloudflare 官方 2 MiB 上传探针：直连约 629 KB/s；当前“其他流量”新加坡 Pro-02 约 163 KB/s；临时日本 Pro-01 约 480 KB/s。测试后已恢复其他流量到新加坡 Pro-02。
   这能证明当时新加坡叶子存在通用上行损失，但不能代替 ChatGPT 文件实传，也不能自动授权把 ai 改日本。

10. 把 10 MiB 与百兆验收分开。

    10 MiB 是日常可接受门槛，已通过；百兆是持续长传稳定性门槛，另测。不能用更严门槛抹掉较浅真实恢复，也不能用较浅门槛冒充更严完成。


六、只局部有效或只能作辅助证据的做法
------------------------------------

1. 恢复 560 字绕过名单

   对微软/Azure 和某些系统路径有效，也有助于恢复历史形状；但 oaiusercontent 当前仍经 ai，绕过名单不是所有大上传的直接药。

2. 换单个 ai 节点

   某些区域和某些时段可能改善；日本 Pro-01 在 nznorth 768 KiB 探针和 Cloudflare 通用探针上曾较快。它仍只是候选，需要真实 ChatGPT 文件与普通网页共同验收。

3. 小 PUT、延迟和握手测试

   适合筛掉明显坏路径、比较直连/代理或共同上游；不能预测百兆中途是否僵死。

4. Cloudflare Turnstile 体感

   可提示通用出口是否变差；不能推出 Cloudflare 与 ChatGPT 上传共用后端，也不能据此直接改 OpenAI 规则。

5. QUIC/HTTP3

   以前曾做禁用 A/B，现已恢复。当前 Edge 无禁用 QUIC 实验残留；没有证据表明再改能消除 TXT 尾段。只有 fresh A/B 同时改善真实页面和上传才采用。

6. 拆分百兆压缩包

   能提高交付成功率、降低单连接失败成本；它是工作绕行，不是代理根因修复。必须保留原包与哈希，不能用拆包宣称网络修好。

7. 重开页面或浏览器

   能清除浏览器旧连接和局部状态；但会丢失健康复用。只在连接粘错、页面状态坏或 selector 变更后使用。


七、已证无效、误导或不成立的解释
----------------------------------

1. “延迟最低的节点就是上传最快的节点”——不成立。

   握手延迟与持续上行吞吐、丢包恢复、区域路径不同。

2. “chatgpt.com 200，所以文本和上传都正常”——不成立。

   文本/ws 可裂脑；文件正文走 oaiusercontent。

3. “小附件秒挂，所以 200 MiB 已修好”——不成立。

   245 KiB 被误认成 200 MiB 已经实际发生。

4. “组 now 已是 Pro-02，所以浏览器也在 Pro-02”——不成立。

   旧 TCP/WebSocket 可继续在 Pro-03。

5. “磁盘写 direct，所以 live 一定直连”——不成立。

6. “PATCH 返回成功，所以 sniffer 已生效”——不成立。

   本机 helper 1.10.0 曾返回成功，但 GET /configs 读不到相应 live 字段。

7. “SSR 过滤器已经覆盖 ShadowsocksR”——不成立。

   节点类型全名是 ShadowsocksR；只匹配 SSR 会漏测。

8. “一个 Codex 窗口 TLS EOF，说明整机没网”——不成立。

   别的 Codex 正常时，应先处理该进程/该连接。

9. “Cloudflare 验证好，说明它就是 ChatGPT 上传站”——不成立。

   两者只是共同暴露上游出口质量。

10. “让 oaiusercontent 直连会去掉 TXT 最后 1–2 秒”——本轮实测否定。

    对 eastus2、australiaeast、westus、japaneast、northeu 五个实际区域做 768 KiB 同目标探针，当前 7897 全部快于直连。该探针端点最终返回 400/404，不能当生产上传测速绝对值，但足以否决“直连显然更快”这个候选。

11. “每次上传前都清 oai 连接会更干净、更快”——不成立。

    健康连接复用可以省掉 TLS；只有换 selector 或证实粘错叶子才清。


八、错药：看似相关，但会把问题治偏
----------------------------------

1. 文本发不出时继续切节点。

   先看 Edge chatgpt/ws 是否同一叶子。2026-08-13 文本事故的正确药是清三条旧连接，不是再换点。

2. 为 TXT 尾段开启 TUN、tcp-concurrent 或全局代理。

   尾段是确认/登记串行阶段；这些旋钮已证会破坏普通网页或稳定性。

3. 为网页上传故障修改 Codex 进程路由，或反过来。

   两个消费者当前走不同职责组。

4. 把 oai 全部加入 Windows 旁路。

   当前同目标探针显示代理更快；旁路还会改变隐私、出口与区域路径。

5. 为了“彻底”清空所有连接。

   这会同时打断多个 Codex、浏览器和健康长连接，扩大影响半径。

6. 用报告、脚本回执、curl 绿灯替代用户真实体验。

   工具证据只证明其测量面。


九、毁灭性事故与禁止事项
------------------------

1. 同时把 GLOBAL、ai、国外流量切成同一 Basic 叶子

   2026-08-11 的 bench_and_switch_v2 做过。规则文件还在，但职责分治被运行态选择拍扁，网页 GPT 上传和海外体感恶化。禁止再跑这种多组联动测速。

2. 为修局部 Codex 把 live mode 改成 Global 后不恢复

   会让原本分治的规则失效，局部问题扩大成整机路由变化。

3. 未核磁盘模板就 PUT /configs?force=true

   config.yaml 长期可能写 direct；force reload 曾把 live rule 真打成 direct。任何整份重载前必须检查模板并准备回滚，重载后立刻读 /configs。

4. TUN 与系统代理叠开而不验收普通网页

   本机出现 Meta Tunnel 后，ChatGPT 小探针可变快，但 X 和普通网页极慢。关 TUN 后恢复。禁止用单点收益交换整机可用性。

5. 打开 tcp-concurrent 并保留

   本机出现时快时慢和“无法加载使用数据”；关掉后用户确认非常快。默认保持 false。

6. 先覆盖 current 再想恢复旧好用快照

   Backup-NetworkProfile.ps1 会更新 current。需要保存新现场时必须保留不可变 history；恢复时点名具体快照，不能让回滚来源被当前坏状态覆盖。

7. 把 Grok_一键恢复 当网络恢复包

   那是已撤的窗口/身份包，不是网络药。网络入口是 C:\Users\xx363\Network_一键恢复。

8. 把报告绿、延迟榜、队列空、HTTP 200 当成系统完成

   2026-08-13 形状全绿时，Edge 文本仍因旧连接裂脑而死。


十、关键事故与认识转折
----------------------

1. 2026-08-11 分组形状事故

   多组被脚本同时切换；随后大文件连接曾明确经 7897 -> ai -> australiaeast 上传到约 44 MiB 后僵住。它证明“规则命中代理”与“长传稳定”是两回事。

2. 2026-08-13 TUN/tcp-concurrent 实验

   上传小探针一度变快，但普通网页和使用数据变坏。回滚 TUN、关闭 tcp-concurrent 后，日常浏览恢复。认识从“某项测速绿”转向“整机消费者联合验收”。

3. 2026-08-13 15:24 文本裂脑

   live rule、TUN 关、并发关、系统代理 7897、绕过 560、分组选择和 HTTP 200 全正常；Edge 页面与 ws 却分别粘在 Pro-03/Pro-02。
   只删除 3 条 Edge ChatGPT 旧连接后，它们自动回到 Pro-02，用户确认文本完全恢复。

   成熟认识：形状绿不等于文本通；selector now 不等于消费者叶子；文本/ws 和上传都会粘旧连接。

4. 245 KiB 被误认成 200 MiB

   这次用户纠正阻止了错误完成宣称。成熟认识：文件身份与字节数必须先钉住，小附件不能冒充大上传。

5. Cloudflare 记忆线索

   用户回忆“Google、X、GPT 经常出现的验证公司，那个好时上传也常好”。确定为 Cloudflare/Turnstile 后，官方上传探针证明当前代理叶子存在通用上行损失；这把判因从“OpenAI 单站坏”推进到“共同海外出口质量”，但没有把 Cloudflare误写成上传后端。

6. 10.13 MiB 当前验收

   eastus2 实传完成，用户判断速度可接受。成熟认识：日常恢复门槛已经通过；百兆长传保留为更严格但独立的未知。

7. 小 TXT 尾段实测

   连续上传时捕获多个动态区域 oai 连接。正文量几十 KiB，响应约半秒，之后 chatgpt/ws 还有登记交换；Edge 无禁用 QUIC/预连接残留，五区域代理探针均快于直连。

   成熟认识：当前 1–2 秒不是需要用代理旋钮治疗的“慢上传”。安全最优动作是保持当前路径和健康连接；若未来尾段变成明显卡顿/失败，再做单次 UI+网络三拍 A/B。


十一、当前仍未知或只可保留为假设的东西
--------------------------------------

1. 当前 100/200 MiB 文件经现有形状能否从头到尾保持可接受速度——未验收。

2. 8 月 11 日后长传恶化中，节点上游拥塞、区域对象存储路径、丢包、服务端调度各占多少——没有单因果证明。

3. 相同文件为何被分配到不同 sdmntpr 区域，以及区域选择能否通过合法客户端行为间接影响——本机不能指定，机制未知。

4. Edge 的 ChatGPT 扩展拥有较宽站点权限，但没有证据证明它参与或拖慢附件上传。只有尾段异常增长时才做禁用/启用 A/B；当前不动。

5. Edge 的硬件加速和 Renderer Code Integrity 当前受本机策略影响，但没有证据把它们与附件网络尾段相连，不为上传擅改。

6. Cloudflare 探针与 OpenAI 实传的速度相关性有多稳定——它只能作旁证，不能当恒定换算器。

7. QUIC 在不同节点和不同 oai 区域是否长期更好——当前无足够证据；现状无禁用残留，保持默认。


十二、以后任何排障的最浅充分顺序
----------------------------------

第一拍：界定真实消费者与完成尺。

  一个 Codex / 所有 Codex / Edge 文本/ws / 小 TXT / 10 MiB / 百兆 / X/Google / 整机。

第二拍：读取当前形状，不做变更。

  /configs：mode、tun、tcp-concurrent
  /proxies：GLOBAL、ai、国外流量、其他流量、媒体
  Windows：ProxyEnable、ProxyServer、ProxyOverride
  网卡：Meta Tunnel
  应用：进程身份、版本、Edge 相关策略

第三拍：读取真实连接。

  process、host、rule、chains、start、upload、download；比较 selector now 与消费者实际叶子。

第四拍：恢复事故轨迹。

  先问刚才是否切过组、开过 TUN/并发、force reload、刷新/重启、覆盖快照。后来的静态文件不能代替这条时序。

第五拍：提出一个可证伪候选，并与不行动/更浅路线比较。

  能用精确清旧连接解决，就不切节点；能保持现状，就不为零点几秒引入整机风险。

第六拍：一刀、回读、真实消费者验收。

  保留 preimage；只动一个变量；同时验收目标流量和普通网页；失败立即回滚。

第七拍：只按证据更新结论。

  使用：已证有效 / 局部有效 / 无效 / 错药 / 灾难 / 未知 / 暂时可接受 / 未验收。
  不把一次成功写成永久节点真理，不把一次失败扩大成整机规律。


十三、完成口径
--------------

文本完成：用户实际能发送；Edge chatgpt/ws 新连接同属 ai 当前叶子。

小 TXT 完成：正文连接达到文件量级并收到对象存储响应；附件栏随后完成登记。最后 1–2 秒若稳定且不失败，属于协议尾段，不判慢上传。

10 MiB 日常上传完成：真实 10.13 MiB 文件达到对应 oai upload 字节，用户当场确认速度可接受。本轮已满足。

百兆上传完成：真实 100 MiB 以上文件从头到尾持续传输，记录区域、chain、速率/总耗时并由用户验收。本轮未满足。

Codex 窗口完成：目标窗口自己的 WebSocket 或 HTTPS fallback 能完成流；其他窗口正常只证明整机未全坏。

代理系统完成：目标消费者、普通网页、分组形状、live mode、连接叶子与恢复来源都同时成立。任何报告、哈希或测试只证明其覆盖面。


十四、证据、恢复与安全入口
--------------------------

当前人话入口：
  C:\Users\xx363\Desktop\本机代理系统认识论.txt

本次整理前原文备份：
  D:\XINAO_RESEARCH_RUNTIME\backups\network_knowledge\本机代理系统认识论.pre_edit_20260813-160253.txt

文本裂脑完整事故：
  D:\XINAO_RESEARCH_RUNTIME\state\network_route\INCIDENT_20260813T1524_TEXT_SPLIT_BRAIN.md

失败模式原始坑位：
  D:\XINAO_RESEARCH_RUNTIME\state\network_route\PROXY_FAILURE_MODES.md

本轮原始诊断与测速：
  D:\XINAO_RESEARCH_RUNTIME\tmp\gpt_upload_diag_20260813\

当前唯一仓库入口（本文件的去秘密同步正文）：
  E:\XINAO_RESEARCH_WORKSPACES\S\docs\local_machine\LOCAL_PROXY_NODE_CHATGPT_UPLOAD_KNOWLEDGE_20260811.md

历史可恢复网络快照：
  D:\XINAO_RESEARCH_RUNTIME\backups\network_profile\history\snapshot_20260709-172958

网络恢复入口：
  C:\Users\xx363\Network_一键恢复
  D:\XINAO_RESEARCH_RUNTIME\backups\network_profile\

秘密边界：
  订阅地址、密码、token、UUID、auth、.store.json 等只在本机精确恢复面使用，不复制到聊天或公开仓库。仓库只保存去秘密的因果认识、操作边界和证据索引。

本档更新必须遵循：先修真实消费者、fresh 验收、再写回认识；不能为了“记录”跳过修复，也不能为了某个当前节点删掉仍有效的历史因果。
