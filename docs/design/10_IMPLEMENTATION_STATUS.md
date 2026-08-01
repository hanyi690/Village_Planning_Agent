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
| explore | `[PLANNED]` | 待提升为主图顶层节点, 源码在25e24847分支. 三种模式: 维度认知(L1/L2/L3) + 桥接(L3后) + 校核(L3轮2) |
| gis_agent | `[IMPLEMENTED] but DEGRADED` | graph.py:52, 当前自取L3报告+双重parse, 待简化 |

---

## 2. 闭环管线阶段

| 阶段 | 状态 | 详情 |
|------|------|------|
| L1 现状分析 | `[IMPLEMENTED]` | 12维并行, KG认知查询(10维度), RAG内嵌 |
| L2 规划定位 | `[PARTIAL]` | Wave调度已实现, KG查询已解除阻断(`_optimize_semantics` 经 EXPLORE 动态认知) |
| L3 详细规划 | `[PARTIAL]` | Wave调度已实现, KG查询已解除阻断, 校核轮未实现 |
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
| explore agent | `[PLANNED]` | 源码在25e24847分支, SessionKGQuery已合入(087cfc6e). 三种模式: 维度认知(替代_optimize_semantics) + 桥接 + 校核 |
| _optimize_semantics 升级为 EXPLORE | `[IMPLEMENTED]` | node.py 异步调用 `build_spatial_cognition`, 替代静态 DIM_KG_MAP, L2/L3 不再阻断 |
| SpatialCognitionSummary | `[IMPLEMENTED]` | agent/explore/summaries.py `build_spatial_cognition` (KG语义+空间统计, 确定性) |
| ReportSummaryIndex | `[IMPLEMENTED]` | agent/explore/summaries.py `build_report_summary_index` (维度级概要索引, 无LLM) |
| EXPLORE 访问层 (6 工具) | `[IMPLEMENTED]` | tools/access/: bundle_overview / spatial_context / spatial_features / layer_reports / knowledge_graph / rag_search + index_bundle_texts |
| ExploreAccess 门面 | `[IMPLEMENTED]` | services/explore_access.py, 8 kinds 统一 dict 返回 |
| 工具注册表升级 | `[IMPLEMENTED]` | tools/registry.py register/get_tool/registered_tools/for_agent("explore") |
| RagService 惰性导出修复 | `[IMPLEMENTED]` | services/__init__.py `_LAZY` 路径 `.modules.rag.service` -> `app.modules.rag.service` |
| ConsistencyReport | `[PLANNED]` | EXPLORE 校核模式产出, L4对账 |
| Flash LLM 独立配置 | `[PLANNED]` | GIS_EXPLORE_LLM_ENABLED/MODEL/TEMPERATURE |
| 结构化问题清单(I1) | `[PLANNED]` | L1 summary扩展产出issues/resources |
| L2/L3开放KG查询(I2) | `[IMPLEMENTED]` | node.py `_optimize_semantics` 无 session/L2/L3 不再 return "", 经 EXPLORE 动态认知 |
| L3校核轮(I5) | `[PLANNED]` | 两轮L3, 轮2读L4对账 |
| L3->EXPLORE自动路由(I6) | `[PLANNED]` | routing.py:239 仍 return END |
| 管制规则生成 | `[PLANNED]` | DB4407/T 105-2023 6类, 未实现 |
| 会话Bundle统一数据源 | `[IMPLEMENTED]` | services/session_bundle.py + bundle_store.py, layer_completion_check 逐层自动快照(trigger: layer1/2/3/final/revision), 上传GIS合并入bundle |
| planning_bundles 读路径替换 dimension_reports | `[PARTIAL]` | access 层已 snapshot-first 读 Bundle 快照 (layer_reports 回退 dimension_reports), 消费方迁移随 EXPLORE 桥接轮 |
| L4成果入Bundle | `[PLANNED]` | L4 PlannedState 在KG, EXPLORE 校核模式经 KG 工具读取 |
| 上传管线修复 | `[IMPLEMENTED]` | operations.py `delete_uploaded_files_async` 未 await `session.delete` 已修; engine.py 补 `PRAGMA foreign_keys=ON` 使 FK CASCADE 清理生效 |
| 上传流程测试 | `[IMPLEMENTED]` | tests/unit/test_upload_flow.py (47例): classify/推断/parse/DB payload/真实SQLite往返, 需 fastapi 环境 |
| 运行时数据管线 E2E | `[IMPLEMENTED]` | tests/integration/test_pipeline_e2e.py (1例, ~97s, 需 fastapi): 上传入库→真实build_session_bundle→bulk_save→快照→KG构建→resolve_bundle快照优先→EXPLORE工具实测. 依赖共享 tests/fixtures/db.py (sqlite_db/pipeline_reset/make_session_with_uploads) |
| ReportStore 单测 | `[IMPLEMENTED]` | tests/unit/test_report_store.py (7例): save读回/版本自增/bulk_save/get_layer_summaries/upsert/delete/级联删除 |
| WMS 兜底地雷修复 | `[IMPLEMENTED]` | catalog.py `load_village_bundle` 对 data_type=="url" 结果 warning+skip, 否则 adapter 抛 ValueError 被 snapshot 吞掉致 bundle 静默空 |
| bundle 全图层加载 | `[IMPLEMENTED]` | sources.yaml 6处 layer_type 对齐 GIS_LAYER_REGISTRY (current_road/current_annotation/planned_road/planned_annotation/conditional_construction_zone/geological_hazard_point); canonical.py `add()` 按 bundle_target 路由 rasters/tables (DEM 不再丢弃) |
| 结构化 summary 生成 | `[IMPLEMENTED]` | modules/parsing/summary_generator.py + summary_parser.py (规则化无LLM); report_store.py 坏相对导入 + `db.delete(r)` 缺 await 已修 |

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
