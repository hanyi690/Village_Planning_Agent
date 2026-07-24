# GIS 村庄规划系统 — 文档索引

> **文档根目录**: `docs/gis/`
> **更新**: 2026-07-24

## 核心文档

| 文档 | 说明 |
|------|------|
| **[00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)** | 系统总体设计文档（唯一权威）— 四层架构、KG 桥接、PARSE/EXECUTE 设计、MIP 约束编译、实现路线图 |

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
00_SYSTEM_DESIGN.md  ← 唯一权威设计文档
    ↓ 参考
reference/           ← 外部对标（人类工作流、可行性验证）
    ↓ 历史
archive/             ← 旧设计文档（已过时，仅参考）
```