---
knowledge_id: local_windows_proxy_node_chatgpt_upload_20260811
scope: this_machine_network_proxy_and_chatgpt_web_upload
evidence_cutoff: 2026-08-11 Asia/Shanghai
source_kind: user_supplied_incident_reconstruction_and_live_observations
fresh_live_readback_required_before_mutation: true
retrieval_terms:
  - 代理
  - 节点
  - 分组形状
  - GLOBAL
  - ai
  - 国外流量
  - 国外媒体
  - 其他流量
  - Rule
  - Global
  - Direct
  - 7897
  - 系统代理
  - Vortex
  - TUN
  - GW
  - helper
  - ChatGPT 上传
  - OpenAI 文件上传
  - oaiusercontent.com
  - oaistatic.com
  - sdmntpr
  - live_groups.json
  - now_nodes.txt
  - bench_and_switch_v2.py
---

# 本机代理节点与 ChatGPT 网页上传知识存档（2026-08-11）

这是一份可检索的本机知识存档，不是当前运行态配置、自动恢复脚本或节点切换授权。它整理的是用户在 2026-08-11 提供的事故对账、运行态观察和上传链路证据。以后遇到本机代理、节点、ChatGPT 上传、`7897`、Vortex/TUN 或 `oaiusercontent.com` 问题，应先读本文件，再只查问题所需的精确 live API、连接或日志；不要先全机搜索。

材料引用了 `live_groups.json`、`now_nodes.txt`、`service_20260811.out.log`、Vortex JSON 和若干 restore 备份，但没有提供这些文件的完整绝对路径。本存档不反向猜路径。

## 语义解码

| 人话或现象 | 在这台机器上应解码成什么 |
|---|---|
| “代理形状”“昨天那套代理” | 不只是一个节点名，而是运行 mode、各 selector 组是否保持独立、域名规则落到哪个组、浏览器从哪个本地端口进入、Vortex/TUN 与磁盘模板是否双轨。 |
| “AI 节点” | `ai` selector 组；OpenAI/ChatGPT/上传域名规则可把连接送到该组。它不等于 `GLOBAL`，也不应默认和 `国外流量` 绑成同一点。 |
| “国外流量” | 普通海外流量 selector；中午前基线是独立的香港 Pro-06，不是 AI 组的同义词。 |
| “上传站” | ChatGPT 大文件正文通常去服务端分配的区域化 `*.oaiusercontent.com` 对象存储；不是本机固定写死的单一“上传官网”。 |
| “网页能开但文件传不动” | 要区分页面/API 连接与大文件对象存储长传。聊天可用不能证明百兆上传稳定；上传卡死也不能直接推断为完全没走代理。 |
| 磁盘 `config.yaml` 写 `mode: direct` | 这是长期存在的模板写法，不能代表真实运行 mode。运行态以 API、连接和服务日志为准。 |
| Vortex 里 TUN 开、磁盘 YAML 里 `tun: false` | 已知双轨现象，不是 2026-08-11 当天才出现；诊断时分别读取，不能拿其中一份替代另一份。 |
| “换节点” | 只改变 selector 的当前选择，并不等于改 DNS 或删规则；但同时把 `GLOBAL`、`ai`、`国外流量` 设成同一点，会破坏原有分组形状。 |

## 中午动手前的已知可用形状

最完整的事故前证据是 2026-08-11 12:01、切点脚本开始时读取的 `live_groups.json`。运行日志含 `DomainSuffix/microsoft.com`、`GeoIP/cn` 匹配，因此真实运行模式是 `rule`；磁盘 YAML 的 `mode: direct` 不能推翻它。

| 对象 | 12:01 的运行态 |
|---|---|
| mode | `rule` |
| `GLOBAL` | `Pro-新加坡-BGP-02` |
| `ai` | `Pro-新加坡-BGP-02` |
| `国外流量` | `Pro-香港-BGP-06`，与 AI 组保持独立 |
| `国外媒体` | `♻️自动选择` |
| `⚓️其他流量` | `Pro-新加坡-BGP-02` |
| 苹果 / Adobe / Steam / 哔哩哔哩 | `DIRECT` |
| 浏览器/系统入口 | 混合口 `127.0.0.1:7897`，系统代理开启 |
| OpenAI 规则 | `openai.com`、`chatgpt.com`、`oaistatic.com`、`oaiusercontent.com` 指向 `ai`，规则未被删除 |
| Vortex TUN | 运行 JSON 显示开启；磁盘 `tun: false`，属于既有双轨 |

这里的关键不是“新加坡节点最好”，而是三类流量没有被无意抹平成一个 selector 选择：AI、普通国外流量和 GLOBAL 的职责仍可分开。

## 2026-08-11 事故时间线

### 12:03–12:06：`bench_and_switch_v2.py` 冲坏分组选择

脚本对 `GLOBAL`、`国外流量`、`ai` 连续执行 PUT 换节点；没有修改 Rule/DNS/规则正文。`now_nodes.txt` 记录它最终把三组都改成：

| 组 | 被改后的选择 |
|---|---|
| `GLOBAL` | `Basic-新加坡-BGP-01` |
| `ai` | `Basic-新加坡-BGP-01` |
| `国外流量` | `Basic-新加坡-BGP-01` |

这抹掉了原来 `ai/新加坡 Pro-02` 与 `国外流量/香港 Pro-06` 的独立形状。规则仍在，但规则命中的组被选到了同一 Basic 节点。

### 15:36–16:00：GW/helper 重启与 mode 漂移

- 出现多份 `bak_before_restore_*`，GW 约 15:48 重启。
- 15:45 观察到 `mode=global` 且 `api.openai.com=421`。
- 15:49 观察到 `mode=rule` 但仍为 `421`。
- Vortex JSON 一度为 `proxy_mode=global`，`GLOBAL` 偏好 `Pro-新加坡-BGP-01`，TUN 开启。
- 磁盘 YAML 仍写 `mode: direct`；这是磁盘模板与运行态不一致，不能单凭 YAML 判因。

### 后续恢复与单组试验

材料记录曾按 12:01 形状恢复到：`mode=rule`；`GLOBAL`、`ai`、`⚓️其他流量` 为 `Pro-新加坡-BGP-02`；`国外流量` 为 `Pro-香港-BGP-06`；`国外媒体` 为 `♻️自动选择`；Vortex `proxy_mode=rule`，对应 prefer 已对齐并留有备份。

随后为诊断百兆上传，只把 `ai` 从 `Pro-新加坡-BGP-02` 改为 `Pro-日本-BGP-01`（约 212 ms），没有动 `GLOBAL`、`国外流量`、`mode=rule` 或系统代理。因此：

- `Pro-新加坡-BGP-02` 是 12:01 已知可用形状中的 AI 基线；
- `Pro-日本-BGP-01` 是后来的单组上传试验；
- 本材料不能证明现在此刻 `ai` 最终停在哪个点，实际操作前必须 live readback。

## ChatGPT 网页文件上传的真实链路

当次文件为：

- `Desktop\CURRENT_LOCAL_WORLD_HANDOFF_20260811_141610.zip`
- `135,805,029` 字节，约 `129.5 MiB`

Edge 的 live 连接证明大文件正文实际走过：

```text
Edge -> 127.0.0.1:7897 -> DomainSuffix oaiusercontent.com -> ai -> 当前代理节点 -> OpenAI 区域对象存储
```

卡住的连接目标为 `sdmntpraustraliaeast.oaiusercontent.com`。它已上传约 `44,437,671` 字节（约 44 MB）后几乎不再增长，但连接仍挂着。这证明当轮不是“上传域名完全没走代理”，而是代理链上的大文件长传中途僵住。

相关主机的职责：

| 主机族 | 作用 |
|---|---|
| `files.oaiusercontent.com` | 通用文件入口或探测入口 |
| `sdmntpr*.oaiusercontent.com` | 按服务端区域分配的分片/大文件对象存储落点 |
| `cdn.oaistatic.com` | ChatGPT 前端静态资源，不是百兆文件正文 |
| `chatgpt.com` / `ab.chatgpt.com` / `ws.chatgpt.com` | 页面、会话 API、WebSocket 等；不等于大文件正文存储 |

`sdmntpr` 后面的区域由 OpenAI/云端调度决定，本机只能影响如何出站，不能指定 ChatGPT 必须把文件派到哪个区域桶。

## 2026-08-11 日志中出现过的上传区域

当天 `service_20260811.out.log` 里出现过以下相关主机；更早两天没有同类 service 日志，因此不能证明“昨天固定上传到某一区”。

| 约略时段 | 主机/区域 | 备注 |
|---|---|---|
| 14:40 起，最密 | `sdmntprindiasocentral.oaiusercontent.com`，印度中南 | 有时显示走 `GLOBAL`，有时走 `ai` |
| 15:38–15:49 | `sdmntprwestus.oaiusercontent.com`，美西 | Edge 连接 |
| 15:52 | `sdmntprwestus3.oaiusercontent.com`，美西 3 | Edge 连接 |
| 15:54 | `sdmntprnorthcentralus...`，美中北 | 材料标注为 Codex 连接 |
| 16:00、16:46 | `sdmntpraustraliaeast...`，澳洲东 | 129.5 MiB ZIP 卡在约 44 MB 的当轮 |
| 16:25 | 日本东、巴西南、印度等区域 | Edge 混合出现 |
| 16:51 | `sdmntprnznorth...`，新西兰北 | `ai` 改为日本节点后的观察 |

当天出现频度按材料概括为：印度区域最多，其次 `files.oaiusercontent.com`，然后美西/美西 3；澳洲东并非唯一或最常见，只是那次大 ZIP 的 live 落点。

部分 `chatgpt.com` / `ws.chatgpt.com` 连接可显示走 `GLOBAL`，而明确命中 `DomainSuffix oaiusercontent.com` 的上传正文走 `ai`。所以“页面能开、上传仍脆”与连接证据并不矛盾。

## 已证事实、合理推断与不能说的话

已证事实：

- OpenAI/ChatGPT/oaiusercontent 规则没有在中午脚本中被删除。
- 中午脚本改变了 selector 选择，并把三个本应有区别的组抹成同一个 Basic 节点。
- 某次 129.5 MiB 上传经 `7897 -> ai -> 代理节点 -> australiaeast.oaiusercontent.com` 传到约 44 MB 后停滞。
- 2026-08-11 同一域名族被调度到多个区域，而非固定澳洲。

合理但未最终证明的推断：

- 百兆 ZIP、代理长传、跨区域对象存储组合对链路稳定性敏感；节点延迟低不等于长上传稳定。
- 中午后的 mode/selector 混乱会改变同一域名族的出口路径，足以造成与之前明显不同的体感。

不能从现有材料推出：

- “上传完全没有走代理”。
- “澳洲东是 ChatGPT 唯一或固定上传站”。
- “磁盘写 direct，所以运行态一定是 Direct”。
- “日本节点一定更好”或“新加坡节点一定是根因”。
- “现在的 selector 仍和材料最后一刻完全相同”。

## 后续诊断与恢复顺序

以后再次出现“网页 ChatGPT 几乎传不动”时：

1. 先读本存档，不先全机搜索，不凭旧文件名猜当前状态。
2. 从 live API/服务日志确认真实运行 mode；不要用磁盘 `mode: direct` 代替。
3. readback `GLOBAL`、`ai`、`国外流量`、`国外媒体`、`⚓️其他流量` 的当前选择，区分已知可用基线与后来的日本单组试验。
4. 确认系统代理和 Edge 是否仍经 `127.0.0.1:7897`。
5. 在 live connections 中看本次新上传的 host、规则名、实际 selector/节点和上传字节是否增长；取消旧的僵死连接后再判断。
6. 若规则/入口正确但仍卡，再核对 Vortex 运行态 TUN 与磁盘 `tun: false` 的双轨，而不是继续同时乱切多个组。
7. 任何 selector mutation 前先留精确 preimage；一次只改一个具名组，不能再次把三组抹平。
8. 为区分链路问题与载荷问题，可先用小文件复现；实际交付可把 129.5 MiB ZIP 只读拆成约 20–40 MB 的多个包，保留原 ZIP，不以拆包掩盖代理形状错误。

需要回到事故前形状时，参考的是“中午动手前的已知可用形状”整表，而不是只把所有组换回某一个新加坡节点。
