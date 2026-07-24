# 归档文档

> 本目录包含 v2.0 及更早版本的 GIS 设计文档。这些文档已被
> `docs/gis/00_SYSTEM_DESIGN.md` 取代，仅作为历史参考。

## 归档原因

旧文档存在以下问题：

1. **设计矛盾**：多份文档对同一概念（如"操作执行引擎" vs "Plan-then-Execute"）有不同理解
2. **内容冗余**：INDEX.md、00_PLANNING_SYSTEM_VISION.md、01_DESIGN_GOALS.md 重复描述同一架构
3. **状态混乱**：部分文档标注为 [CURRENT] 但描述的是已废弃的实现
4. **与代码脱节**：多处设计描述与当前代码实现不一致
5. **文档结构臃肿**：docs/gis 有 20+ markdown 文件分布在 4 层子目录中

## 新文档

系统设计已统一到 `docs/gis/00_SYSTEM_DESIGN.md`，回答以下 6 个核心设计问题：

1. Schema + Data 双层设计是否冗余？（不冗余，是"定义 vs. 操作"的分离）
2. 如何迁入数据库？（GeoPackage + SQLite 分层持久化）
3. KG 如何利用 Schema 对接 PARSE 和 EXECUTE？（Schema→KG Builder→PARSE写入→EXECUTE读取）
4. PARSE 如何完成空间理解和辅助 EXECUTE？（SpatialContext + KG工具 + LLM推理）
5. MIP 能否合理利用 KG？（通过约束编译器一次性编译，非直接查询）
6. EXECUTE 如何实现意图？（多策略：MIP批量 + 约束满足 + 程序化生成）

## 归档文件清单

| 原文件 | 归档路径 | 原用途 |
|--------|---------|--------|
| 00_PLANNING_SYSTEM_VISION.md | archive/ | 北极星愿景 |
| 01_DESIGN_GOALS.md | archive/ | 设计目标 |
| 02_OUTPUT_ARCHITECTURE.md | archive/ | 输出架构 |
| 03_DATA_SOURCE.md | archive/ | 数据源 |
| 04_DATA_ACQUISITION_PLAN.md | archive/ | 数据获取计划 |
| BIBLIOGRAPHY.md | archive/ | 参考文献 |
| INDEX.md | archive/ | 旧索引 |
| schema对接kg，parse.md | archive/ | Schema/KG/PARSE 对接分析 |
| diagnostics/01_PARSE_AGENT_STATUS.md | archive/diagnostics/ | PARSE状态诊断 |
| diagnostics/02_RELIABILITY_ASSESSMENT.md | archive/diagnostics/ | 可靠性评估 |
| diagnostics/03_DATA_GAP_ANALYSIS.md | archive/diagnostics/ | 数据缺口分析 |
| diagnostics/04_PROFESSIONAL_PARADIGM_GAPS.md | archive/diagnostics/ | 专业范式缺口 |
| proposals/01_PARSE_SPATIAL_ENHANCEMENT.md | archive/proposals/ | 空间增强提案 |
| proposals/02_GIS_PLANNING_INTEGRATION.md | archive/proposals/ | GIS集成提案 |
| proposals/03_TOOL_FIRST_ARCHITECTURE.md | archive/proposals/ | Tool-First架构提案 |
| proposals/04_MULTI_SOURCE_DATA_ARCHITECTURE.md | archive/proposals/ | 多源数据架构提案 |
| design-log/01_DECISION_LOG.md | archive/design-log/ | 设计决策日志 |