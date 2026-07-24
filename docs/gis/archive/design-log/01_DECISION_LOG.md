# 关键设计决策日志

> 本文档记录 GIS Layout Engine 的关键设计决策、理由、争议及当前状态。
> 每个决策关联到具体的设计文档和参考依据（专业教材/技术规范）。

---

## Decision-001: SpatialContext 注入策略

- **决策**: DESIGN_GOALS §6 — "Parse stage injects GIS current summary (statistics only, no geometry)"
- **版本**: v5.0 确立 → v5.1 保留
- **理由**: LLM 需参照现状提取——自然村名/地类面积锚定防止幻觉。几何数据对 LLM 无用且消耗 token。
- **质疑**: `proposals/01_PARSE_SPATIAL_ENHANCEMENT.md` §5.2 提议升级为 "statistics + spatial relation summary (~2KB, no raw geometry)"，认为纯统计不足以让 LLM 建立空间心智模型
- **当前状态**: 已实现 statistics-only 方案；spatial-relations 增强待决策
- **参考依据**:
  - 李巍等《实用性村庄规划编制手册》(BIBLIOGRAPHY §A3) — GIS实验操作纳入村庄规划流程，需空间认知
  - 高宜程《实用性村庄规划：理论与实践》(BIBLIOGRAPHY §A4) — 村庄形态设计需空间关系认知
  - Spatial-Agent (BIBLIOGRAPHY §F1) — 空间关系摘要在不注入原始几何的前提下提升空间理解

---

## Decision-002: Think-Then-Format 两阶段模式

- **决策**: 分离 thinking(Phase A 探索) + json_schema(Phase B 格式化) 两阶段
- **版本**: v8 引入 → v10 完善
- **理由**: Qwen3.7-plus 的 thinking mode + json_schema 同时开启导致 token budget 冲突，输出被截断
- **实现**: Phase A: `thinking=ON, tools=ON, json_schema=OFF`; Phase B: `thinking=OFF, tools=OFF, json_schema=ON`
- **当前状态**: 已实现，运行稳定；但 explore_projects draft 太短(138 chars)导致 format 产出仅2个操作
- **参考依据**: LangGraph 官方文档（Context7 确认）
- **关联**: `diagnostics/01_PARSE_AGENT_STATUS.md` — v11改进方案：恢复单批次处理+强制写摘要

---

## Decision-003: 6套编码系统独立共存

- **决策**: 独立维护 GB/T 21010, 土规(tugui), appendix5, ghflbm, ydyhfldm, VNE 六套编码体系
- **版本**: v5.1
- **理由**: 不同数据来源使用不同编码体系，各体系之间不存在官方互转映射表。独立维护避免错误转换。
- **实现**: YAML-driven DictionaryCenter，`GISIngestionLayer` 在输入边界校验编码归属
- **当前状态**: 已实现，6套编码均通过 `backend/app/modules/gis/schema/code_sets.py` 导出
- **参考依据**:
  - GB/T 21010-2017《土地利用现状分类》(BIBLIOGRAPHY §B1)
  - 《国土空间调查、规划、用途管制用地用海分类指南》(BIBLIOGRAPHY §B5)
  - 《村庄规划用地分类指南》(BIBLIOGRAPHY §B6)
  - 广东省技术指南(2019)附录5 (BIBLIOGRAPHY §B10)

---

## Decision-004: Trinity 三层架构

- **决策**: PLANNING KG (RDF) → AGENTIC PIPELINE (ReAct) → SPATIAL GENERATOR (MIP+CA)
- **版本**: v5.0 确立
- **理由**:
  - Layer 1 (KG): 将非结构化规划文本 + GIS数据统一为结构化知识，提供 SPARQL 查询
  - Layer 2 (Agentic): LLM 动态推理 + 确定性操作序列执行
  - Layer 3 (Spatial): 数学优化 (MIP) + 元胞自动机 (CA) 程序化几何生成
- **当前状态**: Layer 1 ✅, Layer 2 ⚠️(parse完成/layout未实现), Layer 3 ❌
- **参考依据**:
  - 吴志强等《城市规划原理》(BIBLIOGRAPHY §A1) — 空间理论框架
  - 李京生《乡村规划原理》(BIBLIOGRAPHY §A2) — 乡村空间组织

---

## Decision-005: 5种原子操作

- **决策**: create / split / merge / modify / reclassify
- **版本**: v5.1
- **理由**: 覆盖村庄规划中所有空间变更类型，每条操作可追踪、可回滚
- **实现**: `OperationItem.action: Literal["create", "split", "merge", "modify", "reclassify"]`
- **当前状态**: 类型定义完成 ✅; EXECUTE_OPERATIONS ReAct 子图 ❌
- **参考依据**:
  - 《村土地利用规划编制技术导则》(BIBLIOGRAPHY §B7)
  - 李巍等《实用性村庄规划编制手册》(BIBLIOGRAPHY §A3) — 土地用途调整流程

---

## Decision-006: MIP (PuLP) 优化器

- **决策**: 使用 PuLP + MIP 求解器进行地块到规划分区的全局最优分配
- **版本**: v5.0
- **理由**: 660地块 × 7分区 = 44K二值变量，需数学优化保证约束满足
- **约束**: 建设用地 ≤30.5ha、基本农田 ≥78.83ha、生态红线 ≥362.02ha
- **当前状态**: ✅ 已实现，MIP求解正确
- **参考依据**:
  - GB 50188-2007《镇规划标准》(BIBLIOGRAPHY §B2)
  - GenPlanner (BIBLIOGRAPHY §F6) — 基于距离的分区方法

---

## 决策时间线

```
v5.0 (2026-Q2)
  ├── Decision-001: SpatialContext statistics-only
  ├── Decision-003: 6编码系统独立
  ├── Decision-004: Trinity三层架构
  ├── Decision-005: 5种原子操作
  └── Decision-006: MIP优化器

v5.1 (2026-07)
  ├── Decision-001: 保留statistics-only (争议记录)
  └── 对齐新schema结构

v8-v10 (2026-07)
  └── Decision-002: Think-Then-Format模式
```
