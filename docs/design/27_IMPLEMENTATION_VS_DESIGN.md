# 设计文档与当前实现差异对照（以实际代码为准）

> 状态：`CURRENT`（事实台账）· 核验日期 2026-08-15
> 本文回答一个问题：**设计文档（`docs/design/`）里写的东西，和 `backend/app/`、`frontend/src/`
> 的实际代码哪里不一致。** 凡是冲突，以实际代码为准；本文把这些差异固定下来，避免后续
> 维护者被过时设计误导。差异的“现状/完成度”见
> [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md) 与
> [24_MODULE_OUTPUT_INVENTORY.md](24_MODULE_OUTPUT_INVENTORY.md)。
> 核验方式：逐文件读代码 + 全仓 grep；每条差异都带可复验的文件路径。

## 1. 图结构与节点组织

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| 主图是 L1/L2/L3 → TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER 的**扁平线性链**（旧 `agent-graph.md`、`04_PLANNING_PIPELINE.md` 图示） | 实际是**四段子图**父图：`bootstrap_context` + `intent_loop` / `cognitive` / `spatial_chain` / `hitl` + `end_diagnostic`。跨段跳转统一由路由节点发 `Command(graph=Command.PARENT, goto=<segment>)`。证据：`workflow/root_graph.py::create_unified_planning_graph`、`workflow/segments.py::build_segments` |
| EXPLORE 是一个独立图节点（旧 Wave M2 前） | EXPLORE 已移除为节点，变为 gate 驱动的水平检索服务（`evidence/retrieval/explore_service.py::ExploreService`）；`root_graph.py` 注释明确 `explore_node removed` |
| 生产图仍为单层扁平 StateGraph、25 节点，子图化“建议最后做”（`21_WORKFLOW_SUBGRAPH_DESIGN.md`） | 四段子图已落地（`segments.py`），21 号文档已归档 |
| 路由是散落的 if-else | `workflow/gate_policy.py` 已有声明式 `GATE_ROUTE_POLICY`（6 阶段 × gate route → action）与 `DEFAULT_GATE_ROUTE_POLICY`；`GATE_ROUTED_STAGES` 显式排除 `execute`（A4 豁免） |

## 2. 认知层（L1/L2/L3）

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| L3 旧解析器生产路径：LLM 输出 Markdown `【INSTRUCTION】` 再解析（旧 `16_20260813_ITERATION_LOG` 前的描述） | LLM 只输出类型化 `PlanningClaimSet`（`contracts/program.py`）；`PlanningProgram` 由 `domain/program/assembler.py::assemble_planning_program` 确定性组装 |
| “12 维 / 28 维”混用 | `config/phases.yaml` 是唯一来源：L1=12（parallel）、L2=4（wave）、L3=12（wave），共 28 维（已实测统计） |
| L2/L3 执行方式表述不统一 | 实际：L1 `execution: parallel`、L2/L3 `execution: wave`；波次由 `config/dependency.py::calculate_waves` 计算 |

## 3. 校验（VALIDATE）

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| `validate_checks.py` 文档字符串写 “Nine pure checks” | 实际导出并执行 **10** 个检查：`check_hard_constraints`、`check_area_conservation`、`check_traceability`、`check_worker_failures`、`check_topology`、`check_overlap`、`check_continuity`、`check_accessibility`、`check_contract_completeness`、`check_classification_missing`（`app/domain/validation/validate_checks.py`） |
| 校验必须带完整 lineage（旧校验文档） | 并非所有检查都带完整 lineage；`repair_directives` 对缺失 lineage 的 finding 会整批 `blocked`（见 `25_VALIDATION_INVENTORY.md`） |

## 4. EXECUTE 与修复指令

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| `19_WIRING_ROADMAP.md` P0 标注 “EXECUTE 消费 rebuild_geometry 未接线” | `workflow/stages/execute.py` 已读取 `repair_directives` 并应用 `exclude_bsms` / `rebuild_strategy`（`_build_exec_repair_payload`）；`workflow/stages/select.py::_apply_repair_directives` 消费 `exclude_bsms` / `reallocate` |
| 修复指令消费范围 | 仍有限：`require_source_evidence` 记为 unresolved；`road_route_failed` 的 `reroute_avoiding_bsms` 只在特定 `rebuild_strategy` 分支生效（`PARTIAL`） |

## 5. LLM 工具注册与绑定

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| `17_LLM_TOOL_BINDING.md` §3.4：`execute_node` 读遗留空 `TOOL_REGISTRY`（`tools.py`），通用执行路径“无法执行任何 access 工具” | **已过时**。`workflow/tools/execute_node.py` 现走 `ToolRegistry.get_tool_info()` / `ToolRegistry.get_tool()`，`base_tool.ainvoke({**args, "state": state})`；access 工具在 `infrastructure/llm/tools/` 注册（`access/{bundle,knowledge,rag,reports,shared}`） |
| `17` §3.3：access 工具是“死注册”，无节点 `bind_tools(for_agent("explore"))` | 读型工具仍只注册不绑定（`GAP` 属实）；但通用 `execute_tools` 已能执行已注册工具 |
| 工具列表只有 `advance_planning_intent`、`gis_analysis` 两个意图工具 | 属实：`conversation/node.py::_bind_tool_list` 只 bind 这两个路由工具；其余走 `execute_tools` |

## 6. 产物 key（artifact refs）

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| `backend-state-contract.md` 早期版本未完整列出 artifact key | 权威注册表是 `workflow/stage_adapter.py::_KEY_BY_TYPE`（实测 25 项），包含 `demand_portfolio`、`suitability_surface`、`global_zone_allocation`、`global_site_allocation`、`portfolio_decision`、`execution_diagnostics`、`render_artifacts`、`export_result` 等 |

## 7. 目录与路径

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| 旧文档大量引用 `app/agent`、`app/modules`、`app/services`、`app/tools`、`app/schema`、`modules/parsing`、`spatial_ops`、`schema/contracts` | 这些路径已全部删除/收敛。当前只有 `backend/app/{api,application,bootstrap,config,contracts,core,data,database,domain,evidence,infrastructure,spatial,workflow}` |
| 交付链路引用 `app.modules.spatial_ops.io.delivery_snapshot`、`app.agent.deliver.render_layers`（旧 `output-lineage.md`） | 当前链路：`domain/delivery`（快照构建/清单）→ `spatial/delivery` + `infrastructure/export` + `infrastructure/rendering` → `DeliverySpatialSnapshot` → `/map-layers` |

## 8. API 面（重点）

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| 历史存在 `/api/sessions/*`、`/api/projects/*` 等遗留端点 | 已全部下线；唯一稳定面是 `/api/v1/*`（`api/v1/contracts.py`）。前端 `data-api.ts` 对已下线端点保留签名但运行时抛错 |
| 后端提供 `evaluation` / `compliance` / `suitability` / `gis-test` 能力端点 | **后端没有任何这些路由**。全仓 grep `"/api/compliance|/api/evaluation|/api/suitability|/api/dev/gis|/api/gis-test` 零命中（`app/api/routes.py` 只有 v1 + `/api/health` + `/api/tiles/tianditu/*`）。前端 `features/{compliance,evaluation,suitability}/api.ts`、`gis-test/api/gis-test-api.ts` 调用的端点目前会 404（`GAP` / 开发占位） |
| `/api/dev/gis/*` 由后端提供 | 仅 `/api/dev/gis/complete-result` 由 **Next.js 本地路由**（`frontend/src/app/api/dev/gis/complete-result/route.ts`）读取静态文件 `output/gis/jintian-complete-road-plan/frontend_layers.json` 提供；其余 `/api/dev/gis/*` 无后端路由（`GAP`，仅测试页使用） |
| 真实 OpenAPI 路径 | `docs/contracts/openapi-v1.json` 实测只有 9 个 v1 操作（sessions 创建/resume、state、events、events/sync、human-review GET/POST、delivery、map-layers、artifacts） |

## 9. SSE 协议（重点：双重词汇表）

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| 公开 SSE 只有 `progress / human_review / delivery_ready / completed / failed / resync_required` 六种顶层类型（`api/v1/contracts.py::PublicEvent`、`API_SSE_DEVELOPER_GUIDE.md`） | 内部真实词汇是 `contracts/events.py::SSEEventType` 的 **32 种**事件（`dimension_start/dimension_delta/dimension_complete/tool_started/tool_status/gis_result/layer_started/...`）。`application/projections/events.py::public_event` 只把 `human_review_paused→human_review`、`completed→completed`、`error→failed` 映射成顶层类型，**其余全部折叠为 `type=progress` 且原始类型保留在 `data.type`** |
| `delivery_ready` 是公开事件类型 | `public_event` **从不产出** `delivery_ready` 顶层类型；全仓只有 `api/v1/contracts.py` 声明它，没有任何 publisher 发出。前端通过 `data.type` 间接收到 |
| 前端只依赖公开六类型 | 前端实际消费内部词汇：`dimension_start/dimension_delta/dimension_complete/layer_started/layer_completed/tool_status/gis_result/human_review_paused/delivery_ready/resync_required/completed/failed`（`features/planning/store/planningStore.ts`、`hooks/useSSE.ts`、`api/planning-api.ts::createStream` 显式读 `envelope.data.type`） |

结论：**“公开六类型”只是信封，真实流上跑的是 32 种内部事件**。`API_SSE_DEVELOPER_GUIDE.md` 的协议描述不完整，应以 `SSEEventType` + `public_event` 为准。

## 10. 前端实现面

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| `evaluation`、`kg-inspection` 是独立页面 | 已改为重定向：`src/app/evaluation/page.tsx` → `/?view=overview&panel=evaluation`；`src/app/kg-inspection/page.tsx` → `/` |
| `test-gis` 页面生产可用 | `src/app/test-gis/page.tsx` 有生产守卫（`NODE_ENV === 'production'` 显示“页面不可访问”），仅开发期可用 |
| 前端状态可持久化恢复 | `usePersistence`（localStorage）、`useSessionRestore`、`/events/sync?after=N` 补偿真实存在；前端状态是可丢弃 UI 投影，SSOT 在后端 |

## 11. 配置与数据库（与设计一致性确认）

以下条目核验后**与设计一致**，仅记录证据，便于后续抽查：

- 维度配置：`config/phases.yaml` L1=12 / L2=4 / L3=12（28 维），唯一来源。
- 数据库：`database/models.py` 共 7 张 SQLModel 表（PlanningSession/UISession/DimensionReport/UploadedFile/PlanningBundle/StepReportModel/RunEvent）；运行状态由 LangGraph `checkpoints` 表管理，业务表不存运行状态。
- LLM provider：`infrastructure/llm/factory.py` 实现 openai / zhipuai / minimax 三家；默认 `LLM_PROVIDER=minimax`、`MINIMAX_MODEL=MiniMax-M2.7-highspeed`（`core/settings.py`）。`settings.py` 另有 DASHSCOPE key/base，但 factory 未实现 dashscope 客户端。
- RAG：`infrastructure/rag/vector_store.py` 提供 AliyunEmbeddings + HierarchyVectorStore；settings 支持 chroma（默认）/ faiss / qdrant。
- `docs/contracts/openapi-v1.json` 与前端 `generate:api-types`（→ `src/generated/v1.ts`）对应。

## 12. 尚未落地 / 仍是 TARGET 的设计

以下设计文档描述的能力**尚未实现**，不能按文档宣称已存在：

- `13_AUTOREPAIR_MULTIMODAL.md`：多模态自动迭代设计（`TARGET`）。
- `26_LLM_VALIDATION_ORCHESTRATION.md`：LLM 监督式校验编排（`TARGET`，本轮不实现）。
- `23_EXPLORE_RETRIEVAL_REDESIGN.md`（已归档）：EXPLORE 检索体系重构（未实施）。
- `05_EXPLORE_BRIDGE.md` / `07_VALIDATION_FEEDBACK.md` 中的部分目标：证据/反馈闭环仍 `PARTIAL`。
- 前端 `compliance/evaluation/suitability/gis-test` 的评估类端点：后端无路由（`GAP`）。

## 13. 维护规则

- 本文件与 `24_MODULE_OUTPUT_INVENTORY.md`、`25_VALIDATION_INVENTORY.md` 同属“以实际代码为准”
  的台账；设计文档修改后，先在本文件登记差异再改设计。
- 发现新的不一致：在对应小节追加一行（设计说法 / 实际实现 / 证据路径），不要在多个文档
  各写一套。
- 归档文档（`docs/_archive/`）与审计历史中的旧路径只作为历史证据，不作为当前事实。