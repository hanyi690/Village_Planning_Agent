# 实现状态台账

> **[IMPLEMENTED] / [PLANNED] / [DEPRECATED] 三态汇总**
> 本文档是所有设计文档中实现状态标记的集中索引。

---

## 1. 主图节点

| 节点 | 状态 | 证据 |
|------|------|------|
| conversation | `[IMPLEMENTED]` | agent/conversation/node.py:74 |
| execute_tools | `[DEPRECATED?]` | agent/tools/execute_node.py:79, 过渡态仅承接闲聊检索 |
| analyze_dimension | `[IMPLEMENTED]` | agent/analysis/node.py |
| layer_completion_check | `[IMPLEMENTED]` | agent/completion/node.py:20 |
| explore | `[PLANNED]` | 待提升为主图顶层节点, 源码在25e24847分支 |
| gis_agent | `[IMPLEMENTED] but DEGRADED` | graph.py:52, 当前自取L3报告+双重parse, 待简化 |

---

## 2. 闭环管线阶段

| 阶段 | 状态 | 详情 |
|------|------|------|
| L1 现状分析 | `[IMPLEMENTED]` | 12维并行, KG认知查询(10维度), RAG内嵌 |
| L2 规划定位 | `[PARTIAL]` | Wave调度已实现, KG查询被 `dim_layer!=1 return ""` 阻断 |
| L3 详细规划 | `[PARTIAL]` | Wave调度已实现, KG查询被阻断, 校核轮未实现 |
| EXPLORE 桥接 | `[PLANNED]` | 源码在25e24847分支待合入, SessionKGQuery已合入 |
| PARSE 空间意图 | `[IMPLEMENTED but DEGRADED]` | 纯正则提取, 不查KG, 待消费ExplorationInstruction |
| EXECUTE 布局生成 | `[IMPLEMENTED]` | 混合管线+Evaluator Gate+write_kg_l4 |
| L4 成果回写 | `[IMPLEMENTED]` | execute/agent.py:374 + layer4.py |
| L3 校核轮 | `[PLANNED]` | 无L4读取机制 |

---

## 3. 关键机制

| 机制 | 状态 | 证据 |
|------|------|------|
| DataPipeline | `[IMPLEMENTED]` 但空跑 | pipeline.py, 27/28维度 tools:[] |
| ConstraintCompiler | `[DEPRECATED]` | 代码已清理, spatial_ops/ 无 constraint_compiler.py |
| write_kg_l4 | `[IMPLEMENTED]` | execute/agent.py:374 `_write_l4_node` + layer4.py:apply_planned_state |
| L4 provenance 谓词 | `[IMPLEMENTED]` | derived_from/source_spec/decided_by/operation/area_change_ha/in_version |
| execute_queries 6模式 | `[PARTIAL]` | 大部分 reserved/exists_not_wired |
| KG实例统一 | `[PLANNED]` | L1用get_any_kg, GIS用get_session_kg, 待统一 |
| 双重parse | `[DEPRECATED]` 待消除 | graph.py:97 + layout_pipeline.py:123 |
| PARSE grounding | `[PARTIAL]` | 契约+KG查询就绪(spatial_ref_contracts.py + queries/spatial_ref.py), agent不产spec |
| explore agent | `[PLANNED]` | 源码在25e24847分支, SessionKGQuery已合入(087cfc6e) |
| ReportSummaryIndex | `[PLANNED]` | 新设计, 参考Claude Code概要模式 |
| Flash LLM 独立配置 | `[PLANNED]` | GIS_EXPLORE_LLM_ENABLED/MODEL/TEMPERATURE |
| 结构化问题清单(I1) | `[PLANNED]` | L1 summary扩展产出issues/resources |
| L2/L3开放KG查询(I2) | `[PLANNED]` | node.py:667 仍 return "" |
| L3校核轮(I5) | `[PLANNED]` | 两轮L3, 轮2读L4对账 |
| L3->EXPLORE自动路由(I6) | `[PLANNED]` | routing.py:239 仍 return END |
| 管制规则生成 | `[PLANNED]` | DB4407/T 105-2023 6类, 未实现 |

---

## 4. 模块层级口径

**统一为五层**：`Schema ← Data ← SpatialOps ← KG ← Agent`

| 旧口径 | 来源 | 修正 |
|--------|------|------|
| "四层 Schema←Data←KG←Agent" | schema/README.md:3 | -> 五层（补 SpatialOps） |
| "五层 Schema←Data←SpatialOps←KG←Agent" | kg/README.md:5 | 正确，保持 |
| "五层 Schema/Data/KG/PARSE/EXECUTE" | 旧00_SYSTEM_DESIGN §1.1 | -> 统一为 Schema←Data←SpatialOps←KG←Agent(PARSE/EXECUTE) |

---

## 5. 配置口径

| 项 | 文档旧值 | 实际值 | 修正 |
|----|----------|--------|------|
| 默认LLM | DeepSeek / qwen3.5-plus | qwen3.7-plus (DashScope) | 文档写"qwen-plus系列"，不写死版本号 |
| API端点 | /api/planning/* | /api/sessions/{id}/* | 7端点: stream/sync/feedback/checkpoints/resume/reports + POST创建 |
| 前端 | React + Zustand | Next.js 14 + Zustand 5 + MapLibre GL | 修正 |
| 模块路径 | src/orchestration/, src/rag/ | backend/app/ | 修正 |
| 主图节点数 | "Router Agent" | 5节点(当前) / 6节点(目标+explore) | 修正 |

---

## 6. 提案实现状态

| 提案 | 状态 | 处置 |
|------|------|------|
| v4 Pydantic DU Pipeline | `[IMPLEMENTED]` | proposals/_implemented/ |
| v3 Encoding-Centric | `[SUPERSEDED by v4]` | proposals/_implemented/ |
| ZONING Custom Functional | `[PARTIAL]` ~3/7 | proposals/ |
| KG Scalability SRE+Topology | `[PENDING-DESIGN]` 纯设计 | proposals/ |
| THREE_STAGE_INTEGRATION | `[PARTIAL]` I4已实现 | proposals/ + design/09 |
| PARSE_SPATIAL_GROUNDING | `[PARTIAL]` ~2/5 | proposals/ |
| EXECUTE_KG_UTILIZATION | `[PARTIAL]` L4已实现 | proposals/ |
| ANALYSIS_KG_INTEGRATION | `[PARTIAL]` L1已实现 | proposals/ |
| RAG Differentiated Chunking | `[EXPLORATION]` | proposals/ |

---

## 7. explore agent 历史与处置

### 7.1 状态：`[PLANNED]`（源码在25e24847分支待合入）

explore agent 是 `feature/flash-llm-explore-agent` 分支上的实验性拆分，其有价值部分已合入主线，主体待合入。

### 7.2 已合入部分

| 组件 | 合入commit | 现位置 |
|------|-----------|--------|
| SessionKGQuery -> require_session_kg | 087cfc6e | app/modules/kg/ |
| query_session_template | 087cfc6e | app/modules/kg/ |
| Think-Then-Format 概念残留 | - | parse/state.py:153-168 注释 |

### 7.3 待合入部分

| 组件 | 源位置(25e24847) | 目标位置 |
|------|------------------|----------|
| ExploreFlashAgent | explore/agent.py | agent/explore/node.py (提升为顶层节点) |
| ExplorationInstruction 契约 | explore/contracts.py | modules/schema/contracts/ 或 agent/explore/ |
| Flash LLM 配置 | settings.py | app/core/settings.py |

### 7.4 陈旧产物

`backend/app/agent/gis/explore/__pycache__/` 下的 `.pyc` 文件为陈旧构建产物（其他分支运行时遗留），已清理。

### 7.5 设计意图

explore 不是"被放弃的实验"，而是"应有的拆分还没完成"。当前 PARSE 承担了文本理解+KG交互的双重职责但只实现了纯正则提取，KG交互完全缺失。explore 的拆分使：
- EXPLORE 负责文本探索+KG交互+概要索引
- PARSE 负责结构化提取（消费EXPLORE产出）
- EXECUTE 负责空间生成+L4回写

详见 `design/05_EXPLORE_BRIDGE.md`。
