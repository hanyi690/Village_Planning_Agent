# GIS 村庄规划系统 — 文档索引

> **文档根目录**: `docs/gis/`
> **更新**: 2026-07-26

## 核心文档

| 文档 | 说明 |
|------|------|
| **[00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)** | 系统总体设计文档（唯一权威）— 四层架构、KG 桥接、PARSE/EXECUTE 设计、MIP 约束编译、实现路线图 |
| **[03_GAP_ANALYSIS.md](03_GAP_ANALYSIS.md)** | 落地缺陷与设计审视 - 回归规划本质，各模块"应做 vs 实做"差距、5 个断裂点、6 个设计缺陷、P0/P1/P2 修复路径 |
| **[04_ARCHITECTURE_AUDIT.md](04_ARCHITECTURE_AUDIT.md)** | 架构规整审视 - 统一标识契约、URI 方案碎片化、各模块优美性评估、修复优先级 |
| **[05_MODULE_BOUNDARY_AUDIT.md](05_MODULE_BOUNDARY_AUDIT.md)** | 模块边界与编码体系审视 - 5 种图斑语义辨析、编码多维度并行关系、10 项编码缺陷、规划对象 vs 参考数据归属 |

## 参考资料

| 文档 | 说明 |
|------|------|
| **[reference/HUMAN_PLANNING_WORKFLOW.md](reference/HUMAN_PLANNING_WORKFLOW.md)** | 人类规划工作流对标 — 广东省技术指南、规划内容、成果要求 |
| **[reference/EXA_FINDINGS.md](reference/EXA_FINDINGS.md)** | 外部可行性验证 — 6 篇论文 + 3 个技术决策 |

## 归档

| 目录 | 说明 |
|------|------|
| **[archive/](archive/)** | 旧设计文档（v2.0 及更早）— 仅历史参考，与 00_SYSTEM_DESIGN.md 冲突时以新文档为准 |

## 模块 README

| 文档 | 说明 |
|------|------|
| `backend/app/modules/schema/README.md` | Schema 层 |
| `backend/app/modules/data/README.md` | Data 层 |
| `backend/app/modules/kg/README.md` | KG 桥接层 |
| `backend/app/agent/gis/parse/README.md` | PARSE Agent |
| `backend/app/agent/gis/execute/README.md` | EXECUTE Agent |
| `backend/app/agent/gis/README.md` | GIS Agent 包总览 |

## 文档间权威关系

```
00_SYSTEM_DESIGN.md   ← 唯一权威设计文档（设计目标）
    ↓ 审视
03_GAP_ANALYSIS.md   ← 落地缺陷与设计审视（设计 vs 实做差距）
    ↓ 审视
04_ARCHITECTURE_AUDIT.md ← 架构规整审视（标识契约、URI 方案、模块优美性）
    ↓ 审视
05_MODULE_BOUNDARY_AUDIT.md ← 模块边界与编码体系审视（数据边界、编码缺陷、归属）
    ↓ 参考
reference/            ← 外部对标（人类工作流、可行性验证）
    ↓ 历史
archive/              ← 旧设计文档（已过时，仅参考）
```