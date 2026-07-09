# Grok Admin Bridge — Canonical Pointer

SENTINEL:GROK_ADMIN_BRIDGE_CANONICAL_POINTER_README

**机器合同：** `grok_admin_bridge_canonical_pointer.v1.json`

## 权威

| 角色 | 路径 |
|------|------|
| **CANONICAL** | `C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge` |
| **STALE_MIRROR** | `C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace-grok-4.5-island\grok-admin-bridge` |

## 策略

- `sync_policy=read_only_pointer` — 4.5 副本仅供旁窗只读对照，**不是**第二真相源。
- Admin 窗**不写** 4.5 岛路径（见 `grok_admin_isolated_window_boundary.v1.json`）。
- 差距扫描：本 POINTER 存在时，`ISLAND_DUAL_BRIDGE_COPY` 降为 **P2 mitigated**（副本未删，但合同已封口）。

## 盘点（2026-07-10）

- Admin bridge（CANONICAL）：158 顶层层文件 / 206 递归
- 4.5 mirror（STALE_MIRROR）：118 顶层层文件 / 164 递归
- 漂移：镜像缺 41 个 Admin 独有合同；镜像独有 `grok_4_5_self_isolation.v1.json`