# 闭环规划管线

> **设计目标：一条闭环 | 当前实现：开环 + 断点**
> 对应 `00_SYSTEM_DESIGN` 第二部分展开。

---

## 1. 设计目标：一条闭环

```
NL输入 -> L1现状分析(12维) -> L2规划定位(4维) -> L3详细规划(12维)
    ↑↓ EXPLORE维度认知      ↑↓ EXPLORE维度认知   ↑↓ EXPLORE维度认知
    (KG空间认知注入)         (约束校核认知)        (现状结构认知)
    -> EXPLORE桥接(按需读L1+L2+L3 + KG交互 + 产出概要索引)
    -> PARSE空间意图(消费概要索引 + 按维度取L3原文)
    -> EXECUTE布局生成(多策略 + Evaluator Gate)
    -> L4成果回写(derived_from provenance)
    -> EXPLORE校核(读L4 PlannedState + L3文本对账)
    -> 文本/几何一致输出
```

全程 KG 语义桥接 + provenance 从 NL 贯通到 L4。

**闭环的核心特征**：
- EXPLORE 贯穿 L1/L2/L3 维度分析，为每个维度动态提供 KG 空间认知（替代静态 DIM_KG_MAP）
- L1/L2/L3 文本产出不是终点，而是 EXPLORE 桥接模式的输入
- EXPLORE 桥接模式产出概要索引，GIS 按维度访问对应报告原文
- EXECUTE 产出 L4，EXPLORE 校核模式读 L4 做文本/几何一致性校核
- 文本说"耕地127.18公顷"，L4 算出来也是 127.18

---

## 2. 当前实现状态：开环 + 6 断点

```
NL -> L1 -> L2 -> L3 -> phase="completed" -> END  [断点⑦]
     │KG浅查  │不查KG[②]               [无自动触发EXPLORE]
                                          gis_agent仅手动触发
                                          gis_agent只取L3[L1/L2丢失]
     PARSE纯正则不查KG[③④]              EXECUTE->L4已回写[✓]
                                         L3校核轮未实现[⑥]
```

详见 `09_INTEGRATION_BREAKPOINTS.md`。

---

## 3. 阶段1：L1 现状分析（12维并行）

### 3.1 执行方式

Map-Reduce 并行，12 维度无内部依赖，`routing.py` 用 Send API 分发。

### 3.2 实现状态

| 机制 | 状态 | 证据 |
|------|------|------|
| 12维并行 Send API | `[IMPLEMENTED]` | routing.py:297 `[Send("analyze_dimension", ...)]` |
| KG认知查询（10维度） | `[IMPLEMENTED]` 但待升级 | node.py:670-680 静态 `DIM_KG_MAP`, 待升级为 EXPLORE 维度认知模式 |
| RAG检索内嵌 | `[IMPLEMENTED]` | node.py `_run_rag()` + `RagService` |
| DataPipeline工具执行 | `[IMPLEMENTED]` 但空跑 | pipeline.py，27/28维度 `tools:[]` |
| 结构化问题清单产出 | `[PLANNED]` | I1改造，治断点①⑪ |
| EXPLORE 维度认知模式 | `[PLANNED]` | 替代 `_optimize_semantics` 静态映射, 动态提供 KG 空间认知 |

### 3.3 L1 维度与 KG 查询映射

| 维度 | KG query_types |
|------|----------------|
| land_use | land_distribution, zone_candidates |
| natural_environment | constraint_coverage |
| ecological_green | constraint_coverage |
| traffic | road_network |
| public_services | facility_coverage |
| infrastructure | facility_coverage |
| socio_economic | land_distribution |
| architecture | constraint_coverage |
| location | village_overview |
| superior_planning | constraint_coverage, zone_candidates |

> villager_wishes / historical_culture 无 KG 查询。

---

## 4. 阶段2：L2 规划定位（4维波次）

### 4.1 执行方式

4 维度按 Wave 1-4 逐级依赖执行：

| Wave | 维度 | 依赖 |
|------|------|------|
| 1 | resource_endowment | 6个L1维度 |
| 2 | planning_positioning | resource_endowment |
| 3 | development_goals | resource_endowment, planning_positioning |
| 4 | planning_strategies | 前3个L2维度 |

### 4.2 实现状态

| 机制 | 状态 | 证据 |
|------|------|------|
| Wave调度 | `[IMPLEMENTED]` | routing.py:252-258 同层依赖检查 |
| 策略性定位（村庄分类/发展方向/口号） | `[IMPLEMENTED]` | 文本产出，正确 |
| KG约束校核 | `[PLANNED]` | I2改造，node.py:667 `if dim_layer != 1: return ""` |
| EXPLORE 维度认知模式（L2） | `[PLANNED]` | analysis_queries + shared_queries, 治断点② |

> **L2 策略性定位是文本，本就正确，不应空间化。** L2 的"规划定位"是策略性定位（村庄分类决定分区方向、发展方向决定产业用地），不是空间定位。空间定位（ZoneTarget/grounding）是 EXPLORE+PARSE 的职责。

---

## 5. 阶段3：L3 详细规划（12维波次）

### 5.1 执行方式

12 维度按 Wave 执行，大部分 Wave 1 并行，`project_bank` Wave 2。

### 5.2 实现状态

| 机制 | 状态 | 证据 |
|------|------|------|
| Wave调度 | `[IMPLEMENTED]` | routing.py:252-258 |
| RAG检索（5维度） | `[IMPLEMENTED]` | phases.yaml `rag_query` 字段 |
| KG现状结构查询 | `[PLANNED]` | I2改造 |
| EXPLORE 维度认知模式（L3） | `[PLANNED]` | execute_queries + shared_queries, 治断点② |
| L3校核轮（EXPLORE校核模式读L4对账） | `[PLANNED]` | I5改造，治断点⑥ |

---

## 6. 阶段4：EXPLORE 桥接（顶层节点）

> 详见 `05_EXPLORE_BRIDGE.md`

### 6.1 定位

EXPLORE 是主图顶层节点（与 conversation/analyze_dimension/gis_agent 平级），**不是** gis_agent 的子步骤。

### 6.2 核心职责

1. **按需读取 L1+L2+L3 报告**：通过 `ReportStore.get_layer_summaries(session_id, layer)` 按需读取，不一次性吞掉全量文本
2. **KG 交互**：`require_session_kg` + `query_session_template` 查候选实体
3. **产出概要索引**（参考 Claude Code 代码库探索模式）：结构化概要，供 GIS agent 按维度导航
4. **路由到 gis_agent**：传递 ExplorationInstructionCollection + ReportSummaryIndex

### 6.3 触发方式

| 触发 | 条件 | 状态 |
|------|------|------|
| 自动触发 | L3 完成 + 非 step_mode | `[PLANNED]` routing.py after_analysis 增加分支 |
| 手动触发 | 用户显式请求空间探索 | `[PLANNED]` 类似 gis_analysis tool_call |

### 6.4 实现状态

| 组件 | 状态 | 证据 |
|------|------|------|
| ExploreFlashAgent | `[PLANNED]` | 源码在 25e24847 分支待合入 |
| SessionKGQuery | `[IMPLEMENTED]` | 已合入为 `require_session_kg` (087cfc6e) |
| ExplorationInstruction 契约 | `[PLANNED]` | explore/contracts.py 在 25e24847 |
| ReportSummaryIndex | `[PLANNED]` | 新设计，参考 Claude Code 概要模式 |
| Flash LLM 独立配置 | `[PLANNED]` | GIS_EXPLORE_LLM_ENABLED/MODEL/TEMPERATURE |

---

## 7. 阶段5：PARSE + EXECUTE（gis_agent 内部）

> 详见 `06_PARSE_EXECUTE.md`

### 7.1 gis_agent 简化（EXPLORE 提升后）

```python
# 当前 gis_agent_node (graph.py:52):
#   1. 自取L3报告 (_get_reports_and_summaries, 只取layer=3)  <- 移除
#   2. 独立调 create_parse_agent_graph (双重parse)             <- 移除
#   3. 调 layout_pipeline

# 目标 gis_agent_node:
#   1. 从state读取 EXPLORE 产出的 ExplorationInstructionCollection + ReportSummaryIndex
#   2. 调 layout_pipeline (pipeline内PARSE消费概要索引, 按维度取L3原文)
#   3. SSE + return
```

### 7.2 layout_pipeline 9 节点

```
START -> fetch_gis_data -> build_kg -> parse_intent -> write_kg_l3
    -> detect_conflicts -> execute -> export_gdb -> render_map -> END
```

| 节点 | 职责 | 状态 |
|------|------|------|
| fetch_gis_data | DataCatalog 加载 VillageBundle | `[IMPLEMENTED]` layout_pipeline.py:30 |
| build_kg | 构建 L1+L2 KG | `[IMPLEMENTED]` layout_pipeline.py:56 |
| parse_intent | PARSE 消费概要索引 -> SpatialPlanningIntent | `[PARTIAL]` 当前纯正则不查KG |
| write_kg_l3 | 写 L3 intent 实体到 KG | `[IMPLEMENTED]` layout_pipeline.py:190 |
| detect_conflicts | 跨维度冲突检测 | `[IMPLEMENTED]` layout_pipeline.py:225 |
| execute | EXECUTE 子图 + Evaluator Gate + write_kg_l4 | `[IMPLEMENTED]` layout_pipeline.py:272 |
| export_gdb | GDB 汇交导出 | `[IMPLEMENTED]` layout_pipeline.py:243 |
| render_map | 地图渲染 | `[IMPLEMENTED]` layout_pipeline.py:256 |

### 7.3 EXECUTE 子图

```
execute (layout/facility/axis/road workers)
  -> validate (Evaluator Gate, 最多重试3轮)
  -> write_kg_l4 (L4 PlannedState + provenance)
```

| 机制 | 状态 | 证据 |
|------|------|------|
| 确定性骨架+ReAct子图 | `[IMPLEMENTED]` | execute/agent.py |
| Evaluator Gate 重试 | `[IMPLEMENTED]` | _route_after_validation, 最多3轮 |
| write_kg_l4 | `[IMPLEMENTED]` | execute/agent.py:374 `_write_l4_node` |
| L4 provenance 谓词 | `[IMPLEMENTED]` | layer4.py: derived_from/source_spec/decided_by/operation/area_change_ha/in_version |
| execute_queries 6模式 | `[PARTIAL]` | 大部分 reserved/exists_not_wired |

---

## 8. 阶段6：L3 校核轮（两轮 L3）

### 8.1 设计

- **L3-轮1（生成）**：L3 各维度基于 L2 intent + KG 认知生成细化文本（现状流程）
- **EXECUTE 触发**：L3-轮1 完成后触发 EXPLORE -> GIS pipeline -> write_kg_l4
- **L3-轮2（校核）**：L3 读 L4 PlannedState，对每个维度做一致性校核：
  - `land_use_planning`：`get_area_by_type` 算 L4 规划后面积 vs L3 文本表述面积
  - `spatial_structure`：读 L4 PlannedZone 的 derived_from 链校核结构
  - `project_bank`：读 L4 PlannedFacility 的 operation/area 校核项目表

### 8.2 实现状态

| 机制 | 状态 |
|------|------|
| L3-轮1 生成 | `[IMPLEMENTED]` |
| L3-轮2 校核 | `[PLANNED]` I5改造 |
| after_analysis L3完成->自动触发 | `[PLANNED]` I6改造 |

---

## 9. 阶段间路由

### 9.1 当前实现

```
START -> conversation -> {execute_tools | analyze_dimension | gis_agent | END}
analyze_dimension -> layer_completion_check
layer_completion_check -> {analyze_dimension | conversation | END}
  L3完成 -> phase="completed" -> END  [断点⑦: 不自动触发EXPLORE]
gis_agent -> conversation  [仅手动触发]
```

### 9.2 目标实现

```
START -> conversation -> {execute_tools | analyze_dimension | explore | gis_agent | END}
analyze_dimension -> layer_completion_check
layer_completion_check -> {analyze_dimension | conversation | explore | END}
  L3完成 + 非step_mode -> explore (自动桥接)
  L3完成 + step_mode -> conversation (等待审批)
explore -> gis_agent
gis_agent -> conversation
```

### 9.3 路由实现状态

| 路由 | 状态 | 证据 |
|------|------|------|
| conversation -> analyze_dimension | `[IMPLEMENTED]` | routing.py:111 advance_planning_intent |
| conversation -> gis_agent | `[IMPLEMENTED]` | routing.py:114 gis_analysis |
| conversation -> execute_tools | `[IMPLEMENTED]` 但过渡态 | routing.py:117 |
| L1->L2->L3 Wave调度 | `[IMPLEMENTED]` | routing.py:238-300 |
| 级联修复影响树 | `[IMPLEMENTED]` | routing.py:50-104 |
| 跨层 early dispatch | `[IMPLEMENTED]` | routing.py:262-287 |
| L3完成 -> explore 自动路由 | `[PLANNED]` | I6改造 |
| conversation -> explore 手动触发 | `[PLANNED]` | 新增 explore_analysis tool_call |
| explore -> gis_agent | `[PLANNED]` | 新增边 |

---

## 10. execute_tools 节点评估

### 10.1 当前职责

`execute_tools`（`execute_node.py:79`）仅承接 LLM 自主发起的非路由 tool_calls：
- `knowledge_search`：知识库检索
- `web_search`：网络搜索
- `population_prediction`：人口预测

### 10.2 冗余分析

- `knowledge_search` / `web_search`：仅闲聊场景使用，与主规划流程无关
- `population_prediction`：phases.yaml 中仅 socio_economic 绑定，且 DataPipeline 已有独立执行路径
- `DataPipeline`（pipeline.py）与 `execute_tools` 共用 `TOOL_REGISTRY`，但 27/28 维度 `tools:[]` 空跑

### 10.3 处置

`[DEPRECATED?]` 过渡态，待评估移除：
- 若闲聊检索改走独立 RAG 通路 -> 可删 execute_tools 节点
- 若保留闲聊检索 -> 保留但明确标注为非主流程

---

## 11. 主图节点总览

### 11.1 当前实现（5节点）

| 节点 | 文件 | 状态 |
|------|------|------|
| conversation | agent/conversation/node.py:74 | `[IMPLEMENTED]` |
| execute_tools | agent/tools/execute_node.py:79 | `[DEPRECATED?]` 过渡态 |
| analyze_dimension | agent/analysis/node.py | `[IMPLEMENTED]` |
| layer_completion_check | agent/completion/node.py:20 | `[IMPLEMENTED]` |
| gis_agent | graph.py:52 | `[IMPLEMENTED]` but DEGRADED |

### 11.2 目标实现（6节点）

| 节点 | 文件 | 状态 |
|------|------|------|
| conversation | agent/conversation/node.py:74 | `[IMPLEMENTED]` |
| execute_tools | agent/tools/execute_node.py:79 | `[DEPRECATED?]` |
| analyze_dimension | agent/analysis/node.py | `[IMPLEMENTED]` |
| layer_completion_check | agent/completion/node.py:20 | `[IMPLEMENTED]` |
| **explore** | **agent/explore/node.py** | `[PLANNED]` 待提升 |
| gis_agent | graph.py:52 | `[IMPLEMENTED]` 待简化 |
