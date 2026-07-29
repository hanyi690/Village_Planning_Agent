# GIS 村庄规划系统 — 文档索引

> **文档根目录**: `docs/gis/`
> **更新**: 2026-07-29（归档重组）
> **关联**: `docs/architecture/reference/gis-cross-reference.md`

---

## 系统设计

| 文档 | 说明 |
|------|------|
| **[design/00_SYSTEM_DESIGN.md](design/00_SYSTEM_DESIGN.md)** | 总体设计文档（North Star）— 四层架构、KG 桥接、PARSE/EXECUTE |
| **[design/02_EXECUTION_PLAN.md](design/02_EXECUTION_PLAN.md)** | 执行方案 — 全局目标、模块化分解、分波次执行计划。§5.1 中推翻 00 的条款已回填到 00 v4.8 |
| **[design/KG_SPATIAL_COGNITION_DESIGN.md](design/KG_SPATIAL_COGNITION_DESIGN.md)** | KG 空间认知设计 v4.8.1 — 三维度谓词、四命名空间、语义层 |
| **[design/CONTEXT_PLAN_BLOCK_DESIGN.md](design/CONTEXT_PLAN_BLOCK_DESIGN.md)** | ContextBlock & PlanBlock 设计 — LLM 工作记忆摘要层 |
| **[design/HOW_TO_ADD_LAYER.md](design/HOW_TO_ADD_LAYER.md)** | 图层新增指南 — 4 种 Pattern，90% 仅需 YAML 条目 |
| **[design/2026-07-29-VKG-DESIGN-DECISION.md](design/2026-07-29-VKG-DESIGN-DECISION.md)** | VKG 设计决策日志 |

## 审计与诊断

| 文档 | 说明 |
|------|------|
| **[audit/03_GAP_ANALYSIS.md](audit/03_GAP_ANALYSIS.md)** | 落地缺陷审视 — "应做 vs 实做"差距、5 断裂点、6 设计缺陷 |
| **[audit/04_ARCHITECTURE_AUDIT.md](audit/04_ARCHITECTURE_AUDIT.md)** | 架构规整审视 — 统一标识契约、URI 方案碎片化 |
| **[audit/05_MODULE_BOUNDARY_AUDIT.md](audit/05_MODULE_BOUNDARY_AUDIT.md)** | 模块边界审视 — 5 种图斑语义、10 项编码缺陷 |
| **[audit/SCENE2_GAP_ANALYSIS.md](audit/SCENE2_GAP_ANALYSIS.md)** | scene#2 深度研究 vs 当前实现的差距分析 |
| **[audit/SCHEMA_COVERAGE_AUDIT_2026-07-25.md](audit/SCHEMA_COVERAGE_AUDIT_2026-07-25.md)** | Schema 覆盖度审计 |

> 审计文档的 P0/P1/P2 优先级编号以模块 README 和实际代码为准，历史编号仅作参考。

## 系统集成

| 文档 | 说明 |
|------|------|
| **[integration/ANALYSIS_KG_INTEGRATION.md](integration/ANALYSIS_KG_INTEGRATION.md)** | 28 维度分析 + KG 语义集成（P1-13/14 修复） |
| **[integration/PARSE_SPATIAL_GROUNDING_DESIGN.md](integration/PARSE_SPATIAL_GROUNDING_DESIGN.md)** | PARSE 空间接地 — NL→BSM 候选→精确 BSM |
| **[integration/THREE_STAGE_INTEGRATION_DESIGN.md](integration/THREE_STAGE_INTEGRATION_DESIGN.md)** | 三阶段有机集成 — 现状分析 ⇄ 规划定位 ⇄ 规划细化 |
| **[integration/EXECUTE_KG_UTILIZATION_DESIGN.md](integration/EXECUTE_KG_UTILIZATION_DESIGN.md)** | EXECUTE KG 利用 — 生成期上下文 + 冲突校核 + L4 写入 |

## 重构提案

| 文档 | 说明 |
|------|------|
| **[proposals/REFACTOR_V4_PYDANTIC_DU_PIPELINE.md](proposals/REFACTOR_V4_PYDANTIC_DU_PIPELINE.md)** | **v4 管道重构（当前）** — Pydantic v2 + DU + 声明式管道 |
| **[proposals/REFACTOR_V3_ENCODING_CENTRIC_PIPELINE.md](proposals/REFACTOR_V3_ENCODING_CENTRIC_PIPELINE.md)** | v3 编码中心化（历史参考，被 v4 替代） |
| **[proposals/ZONING_CUSTOM_FUNCTIONAL_GENERATION.md](proposals/ZONING_CUSTOM_FUNCTIONAL_GENERATION.md)** | 非常规功能分区生成设计 |
| **[proposals/KG_SCALABILITY_RELATION_POLICY.md](proposals/KG_SCALABILITY_RELATION_POLICY.md)** | KG 可扩展性 — SRE+Topology 替代 O(n²) |

## 数据相关

| 文档 | 说明 |
|------|------|
| **[data/01_DATA_ACQUISITION_PLAN.md](data/01_DATA_ACQUISITION_PLAN.md)** | 数据获取计划 — Schema 空间要素全覆盖 |
| **[data/02_DATA_SOURCE.md](data/02_DATA_SOURCE.md)** | 金田村数据源规范 — GDB 图层、字段结构 |

## 参考资料

| 文档 | 说明 |
|------|------|
| **[reference/HUMAN_PLANNING_WORKFLOW.md](reference/HUMAN_PLANNING_WORKFLOW.md)** | 人类规划工作流对标 — 广东省技术指南 |
| **[reference/EXA_FINDINGS.md](reference/EXA_FINDINGS.md)** | 外部可行性验证 — 6 篇论文 + 3 个技术决策 |
| **[BIBLIOGRAPHY.md](BIBLIOGRAPHY.md)** | 统一参考文献索引 |

## scene#2 专项

| 文档 | 说明 |
|------|------|
| **[scene2/scene2_深度研究_乡村规划数据需求溯源.md](scene2/scene2_深度研究_乡村规划数据需求溯源.md)** | 数据需求溯源（29 来源） |

## KG 可视化

| 文档 | 说明 |
|------|------|
| **[kg_visualization/README.md](kg_visualization/README.md)** | 金田村 KG 渲染结果（21,253 三元组） |

## 归档

| 目录 | 说明 |
|------|------|
| **[archive/](archive/)** | 旧设计文档（v2.0 及更早）— 仅历史参考 |

---

## 文档间权威关系

```
模块 README（schema / data / kg / spatial_ops / parse / execute）
    ↑ 最权威，最贴近代码实现。涉及实现细节时以 README 为准。

design/00_SYSTEM_DESIGN.md（已 reconciliation）
    ↑ North Star 设计文档。模块 README 的"为什么"在此解释。
    ↑ 02_EXECUTION_PLAN 中推翻 00 的条款已全部回填。

audit/（03/04/05/SCENE2/SCHEMA）
    ↑ 诊断参考。P0/P1/P2 优先级以模块 README 和实际代码为准。

proposals/
    ↑ 重构提案。v4 为当前方向，v3 为历史参考。

integration/
    ↑ 系统集成设计。实现前须与模块 README 对齐。

archive/
    ↑ 历史参考（已过时）
```

## 关键设计决策

| 决策 | 结论 | 确认日期 |
|------|------|----------|
| ConstraintCompiler | **废弃** | 2026-07-29 |
| MIP 定位 | **先图斑后校核**（图斑操作优先，MIP 配额校核辅助） | 2026-07-29 |
| ThreeZone/ThreeLine | 约束面通过 `ConstraintIndex` 注入 KG，非 KG 实体 | 2026-07-29 |
| 数据模型 | **Pydantic v2 + Discriminated Union**（v4 方案） | 2026-07-29 |
| KG Builder 注册 | `@kg_builder` 装饰器（v4 方案） | 2026-07-29 |
| 编码消歧 LLM | ingest 阶段保持确定性，analysis 阶段做 LLM 选择 | 2026-07-29 |
| KG L1 实体范围 | 只存有几何的空间实体。ThreeZone/ThreeLine/FarmlandProtection/EcologicalRedline 已移出 | 2026-07-29 |
