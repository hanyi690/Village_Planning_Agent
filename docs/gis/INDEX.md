# GIS 村庄规划系统 — 文档索引

> **文档根目录**: `docs/gis/`
> **更新**: 2026-07-26

## 执行方案

| 文档 | 说明 |
|------|------|
| **[02_EXECUTION_PLAN.md](02_EXECUTION_PLAN.md)** | 统一执行方案（当前权威）— 全局目标、模块化分解、分波次执行计划 |

## 审计与诊断

| 文档 | 说明 |
|------|------|
| **[03_GAP_ANALYSIS.md](03_GAP_ANALYSIS.md)** | 落地缺陷与设计审视 - 回归规划本质，各模块"应做 vs 实做"差距、5 个断裂点、6 个设计缺陷 |
| **[04_ARCHITECTURE_AUDIT.md](04_ARCHITECTURE_AUDIT.md)** | 架构规整审视 - 统一标识契约、URI 方案碎片化、各模块优美性评估 |
| **[05_MODULE_BOUNDARY_AUDIT.md](05_MODULE_BOUNDARY_AUDIT.md)** | 模块边界与编码体系审视 - 5 种图斑语义辨析、编码多维度并行关系、10 项编码缺陷、规划对象 vs 参考数据归属 |

> **注**：上述审计文档的 P0/P1/P2 优先级编号以 `02_EXECUTION_PLAN.md` Wave 1/2/3 为准。已完成项目不再追溯。

## 参考资料

| 文档 | 说明 |
|------|------|
| **[reference/HUMAN_PLANNING_WORKFLOW.md](reference/HUMAN_PLANNING_WORKFLOW.md)** | 人类规划工作流对标 — 广东省技术指南、规划内容、成果要求 |
| **[reference/EXA_FINDINGS.md](reference/EXA_FINDINGS.md)** | 外部可行性验证 — 6 篇论文 + 3 个技术决策 |

## 归档

| 目录 | 说明 |
|------|------|
| **[archive/](archive/)** | 旧设计文档（v2.0 及更早 + 01/OPTIMIZATION_TASKS）— 仅历史参考，以 `02_EXECUTION_PLAN.md` 为准 |

## 模块 README（实现层权威）

| 文档 | 说明 |
|------|------|
| `backend/app/modules/schema/README.md` | Schema 层 — 四形态结构优先、阶段抽象、实体/表达分离、BaseControlZone |
| `backend/app/modules/data/README.md` | Data 层 — 双轨接入、四形态、VillageBundle 形态优先 |
| `backend/app/modules/kg/README.md` | KG 桥接层 — L1-L4 四层架构、EntityIdPolicy、SemanticMemoryStore |
| `backend/app/modules/spatial_ops/README.md` | 空间计算层 — 三职责分工（KG输入/PARSE接地/EXECUTE桥接） |
| `backend/app/agent/gis/parse/README.md` | PARSE Agent — Think-Then-Format、空间接地、统一Intent |
| `backend/app/agent/gis/execute/README.md` | EXECUTE Agent — Worker-Evaluator 循环、子任务分解 |
| `backend/app/agent/gis/README.md` | GIS Agent 包总览 |

## 文档间权威关系

```
模块 README（schema/kg/spatial_ops/parse/execute/data）
    ↑ 最权威，最贴近代码实现

02_EXECUTION_PLAN.md
    ↑ 执行方案，统一各 README 先进设计

03_GAP_ANALYSIS.md / 04_ARCHITECTURE_AUDIT.md / 05_MODULE_BOUNDARY_AUDIT.md
    ↑ 诊断参考，P0/P1/P2 优先级编号以 02_EXECUTION_PLAN.md 为准

00_SYSTEM_DESIGN.md
    ↑ 架构参考（§3.2/§3.5/§3.6/§5.1 以 02_EXECUTION_PLAN.md 和 README 为准）

reference/
    ↑ 外部对标

archive/
    ↑ 历史参考（已过时）