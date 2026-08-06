# agent 包（村庄规划 Agent 编排层）

> 顶层规划 Agent：6 节点 LangGraph 主图（对话路由 → 工具执行 → 维度分析 → 层级完成检测 → EXPLORE 认知 → GIS 布局），驱动 L1/L2/L3 三层并行分析 + GIS 空间布局，产出最终规划文本。
> **Updated: 2026-08-04（迁移至理想阶段子包，见 docs/architecture/agent-graph.md §5）**

---

## 一、定位

`agent/` 是系统的**编排中枢**：构建统一规划图（`create_unified_planning_graph`），用 LangGraph 的 `Send` API 实现配置驱动的动态维度分发、并行分析、波次推进与级联修订。数据持久化走 `ReportStore`（报告/摘要存库），状态仅保留进度与消息。

> ⚠️ **架构现状**：`bootstrap/gis_agent_entry.py` 的 `gis_agent_node` 调用确定性 LAYOUT 混合管线（`execute/layout_pipeline.py`），PARSE 为规则解析器（`select/parse_agent.py`），EXECUTE 为确定性 worker（`execute/execute_agent.py`）。`create_parse_agent_graph` 为兼容别名。

---

## 二、目录结构（2026-08 迁移后）

```
backend/app/agent/
├── bootstrap/          # 主图工厂 + 阶段机 (graph.py, phase_machine.py, gis_agent_entry.py)
├── conversation_router/ # 中央路由 (node.py + edges.py)
├── l1_observe/         # L1 现状分析 (analysis_node.py + pipeline.py + formatters.py)
├── l2_strategize/      # L2 策略推导 (占位, 暂借 l1_observe)
├── l3_plan/            # L3 详细规划 (占位, 暂借 l1_observe)
├── explore/            # EXPLORE 认知引擎 (横向能力)
├── ground/             # GROUND 空间接地 (format_bound_intent.py)
├── select/             # SELECT/PARSE (parse_agent.py, parse_state.py, parse_fallback.py, prompts.py)
├── execute/            # EXECUTE (layout_pipeline.py, execute_agent.py, road_generator.py, vocab_*)
├── validate/           # VALIDATE (占位)
├── plan_state/         # PLAN_STATE (state.py + completion_node.py)
├── reconcile/          # RECONCILE (占位)
├── deliver/            # DELIVER (gis_pipeline_state.py)
└── tools/              # 主图工具调度 (execute_node.py)
```

> 注：L1/L2/L3 子图尚未独立（L2/L3 暂借 l1_observe 实现），GROUND/SELECT/VALIDATE/RECONCILE 核心算法仍在 `app/modules/spatial_ops` + `app/modules/kg`，后续逐模块完善时再深入。

---

## 三、主图（bootstrap/graph.py：6 节点）

```
START → conversation ─┬─ execute_tools ──→ conversation
                      ├─ analyze_dimension ─→ layer_completion_check ─┬─ analyze_dimension（Send 并行分发）
                      │                                               ├─ explore → gis_agent → END
                      │                                               └─ conversation / END
                      └─ gis_agent ──→ END
```

| 节点 | 模块 | 职责 |
|---|---|---|
| `conversation` | `conversation_router/node.py` | **中央路由（大脑）**：LLM 绑定工具（`advance_planning_intent` / `gis_analysis` / 分析工具），根据用户消息决定推进意图/调用工具/直接回复；已知意图 tool_call 直接旁路 LLM |
| `execute_tools` | `tools/execute_node.py` | 并行执行非路由工具（`asyncio.gather` + `BaseTool.ainvoke`），每个调用前后发 SSE；过滤意图类工具 |
| `analyze_dimension` | `l1_observe/analysis_node.py` | 维度分析节点：`DataPipeline`（`l1_observe/pipeline.py`）取专业数据 + `_build_prompt` 组 Prompt + LLM 生成报告 + 摘要 + KG 富化 |
| `layer_completion_check` | `plan_state/completion_node.py` | **层级完成检测**：reducer 合并并行结果后检测层完成；`step_mode` 走 `interrupt()` 审批暂停；层边界触发 bundle 快照 + **KG enrichment**（L1 村名绑定 / L2L3 实体注解） |
| `explore` | `explore/node.py` | **EXPLORE 认知引擎**：桥接 agent（`ExploreFlashAgent`）+ 确定性概要索引（`summaries.py`）——解析规划文本生成空间认知与 EXPLORE 指令，供分析/GIS 消费 |
| `gis_agent` | `bootstrap/gis_agent_entry.py` | GIS 空间布局：加载 DataCatalog bundle → 合并用户上传 → **PARSE**（intent，`select/`）→ **LAYOUT pipeline**（`execute/`）→ SSE 推送；错误经 `_gis_error_handler` 回 conversation |

**路由**（`conversation_router/edges.py`）：
- `after_conversation`：级联修订（计算影响树 → 分发 Wave 0）> 推进意图检测（`advance_planning_intent`→`_dispatch_current`；`gis_analysis`→`gis_agent`）> 未知工具→`execute_tools` > 普通对话→`END`。
- `after_analysis`：修订分支（依赖检查分发 / 完成则 END）> 普通分支（同层依赖就绪分发 + **跨层提前分发** `cross_ready`，`step_mode` 除外）> 无就绪→END；**phase=completed 且非 step_mode** 时触发一次 `explore`（EXPLORE 桥接）→ `gis_agent` → `conversation` → END（`explore_done` 标记防重复）。

---

## 四、状态模型（plan_state/state.py）

`AgentState`（`TypedDict`，`total=False`）：

- **进度**：`phase`（init/layer1/layer2/layer3/completed）、`current_wave`、`completed_dimensions`（`{layerN: [dim_keys]}`，reducer 并行合并）、`step_mode`、`previous_layer`。
- **配置**：`config`（deep-merge reducer；village_data / village_name / task_description / constraints / rag 开关）。
- **修订**：`need_revision` / `revision_target_dimensions` / `is_revision`（OR reducer）/ `revision_impact_tree` / `revision_completed_dims` / `revision_feedback`。
- **性能优化**：`pending_reports`（批量写库缓冲，`[]` 显式清空）/ `layer_char_counts` / `user_uploaded_data`。
- **P0 数据流闭环**：`_landuse_metrics`（L1 现状用地指标 → L3 注入）、`intent_targets`（L2 规划目标面积 → L3）。
- **已移除**（存 `ReportStore`）：`reports` / `report_versions` / `summaries`。

**常量**：`PlanningPhase` 枚举（`bootstrap/phase_machine.py`）、`LAYER_DIMENSIONS` / `WAVE_DIMENSIONS`（从 config 构建波次映射）/ `TOTAL_WAVES` / `LAYER_NAMES`。

**辅助**：`create_initial_state`、`state_to_ui_status`（状态→UI 格式，含 interrupt_info / progress / messages 转换）、`get_*` 查询函数。

> ⚠️ 注意：`_messages_reducer` 用 `add_messages`（`DeltaChannel` 不兼容 SqliteSaver——见代码注释 langgraph PR #7547）。

---

## 五、数据流（L1 → L2 → L3 → GIS → 规划文本）

```
用户输入 → conversation（意图）→ analyze_dimension（L1 12 维并行）
   ↓ layer_completion_check（快照 + KG enrichment）
L2 规划思路（4 维）→ L3 详细规划（12 维，P8 INSTRUCTION 表格段）
   ↓ gis_agent_node
PARSE（L3 摘要 → SpatialPlanningIntent，select/）→ LAYOUT pipeline（execute/）
   ↓ SSE 推送 / delivery_manifest
规划文本生成（modules/planning_text：22 条条文 + RAG 附录 + DOCX 导出）
```

三层报告全文/摘要统一由 `app.services.report_store` 持久化；`pending_reports` 缓冲批量写库降低 DB 压力。

---

## 六、相关文档

- `explore/README.md` — EXPLORE 能力引擎
- `tools/README.md` — 工具执行
- `docs/architecture/agent-graph.md` — 工作流图（当前实现与目标子图）+ 迁移目录归属
- `app/services/report_store.py` — 报告/摘要存储
- `app/tools/` — 工具层（intent_tools / registry / access）
