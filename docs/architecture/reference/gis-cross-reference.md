# GIS 子系统交叉引用

> 本文件为 `architecture/` 与 `docs/gis/` 之间的桥接索引。
> 更新: 2026-07-29

## GIS 设计文档入口

GIS 系统的完整设计文档位于 `docs/gis/` 目录：

| 分类 | 路径 | 说明 |
|------|------|------|
| 总体设计 | [gis/design/00_SYSTEM_DESIGN.md](../../gis/design/00_SYSTEM_DESIGN.md) | North Star 设计文档 |
| 执行方案 | [gis/design/02_EXECUTION_PLAN.md](../../gis/design/02_EXECUTION_PLAN.md) | 统一执行方案（权威） |
| KG 设计 | [gis/design/KG_SPATIAL_COGNITION_DESIGN.md](../../gis/design/KG_SPATIAL_COGNITION_DESIGN.md) | KG 空间认知设计 v4.8.1 |
| 审计诊断 | [gis/audit/](../../gis/audit/) | 缺陷分析与架构审视 |
| 系统集成 | [gis/integration/](../../gis/integration/) | PARSE/EXECUTE/KG 集成设计 |
| 重构提案 | [gis/proposals/](../../gis/proposals/) | v3/v4 管道重构方案 |
| 数据相关 | [gis/data/](../../gis/data/) | 数据获取计划与数据源规范 |
| 文档索引 | [gis/INDEX.md](../../gis/INDEX.md) | GIS 文档全局索引 |

## architecture/ 中与 GIS 相关的文档

| 文档 | 关联主题 |
|------|----------|
| [core/02-agent-core.md](../core/02-agent-core.md) | gis_agent 节点、GIS 分析流程 |
| [core/06-tool-system.md](../core/06-tool-system.md) | GIS 工具包装器、GisService |
| [infrastructure/08-rag-system.md](../infrastructure/08-rag-system.md) | RAG 知识检索（与 GIS 数据互补） |

## 模块 README（实现层权威）

| 模块 | README |
|------|--------|
| Schema 层 | `backend/app/modules/schema/README.md` |
| Data 层 | `backend/app/modules/data/README.md` |
| KG 层 | `backend/app/modules/kg/README.md` |
| Spatial Ops 层 | `backend/app/modules/spatial_ops/README.md` |
| PARSE Agent | `backend/app/agent/gis/parse/README.md` |
| EXECUTE Agent | `backend/app/agent/gis/execute/README.md` |
| GIS Agent 包 | `backend/app/agent/gis/README.md` |

## 关键设计决策（2026-07-29 确认）

| 决策 | 结论 |
|------|------|
| ConstraintCompiler | 废弃 |
| MIP 定位 | 先图斑后校核（图斑操作优先，MIP 配额校核辅助） |
| ThreeZone/ThreeLine | 约束面通过 ConstraintIndex 注入 KG，非 KG 实体 |
| 管道重构 | 以 REFACTOR_V4（Pydantic v2 + DU）为准 |
| 默认 LLM | qwen3.5-plus（阿里云 DashScope） |
