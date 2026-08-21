# 设计文档与当前实现差异对照（以实际代码为准）

> 状态：`CURRENT`（事实台账）· 核验日期 2026-08-17
> 本文回答一个问题：**设计文档（`docs/design/`）里写的东西，和 `backend/app/`、`frontend/src/`
> 的实际代码哪里不一致。** 凡是冲突，以实际代码为准；本文把这些差异固定下来，避免后续
> 维护者被过时设计误导。差异的“现状/完成度”见
> [10_IMPLEMENTATION_STATUS_CURRENT_20260818.md](10_IMPLEMENTATION_STATUS_CURRENT_20260818.md)
> 与 [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)。
> 核验方式：逐文件读代码 + 全仓 grep；每条差异都带可复验的文件路径。

## 1. 图结构与节点组织

| 设计文档的说法 | 实际实现（证据） |
|---|---|
| 主图是 L1/L2/L3 → TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER 的**扁平线性链**（旧 `agent-graph.md`、`04_PLANNING_PIPELINE.md` 图示） | 实际是**四段子图**父图：`bootstrap_context` + `intent_loop` / `cognitive` / `spatial_chain` / `hitl` + `end_diagnostic`。跨段跳转统一由路由节点发 `Command(graph=Command.PARENT, goto=<segment>)`。证据：`workflow/root_graph.py::create_unified_planning_graph`、`workflow/segments.py::build_segments` |
| EXPLORE 是一个独立图节点（旧 Wave M2 前） | EXPLORE 已移除为节点；当前由 gate 驱动的 `retrieve_evidence_for_gate()` 调用统一 `retrieve_evidence()`，`root_graph.py` 注释明确 `explore_node removed` |
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
| 校验必须带完整 lineage（旧校验文档） | 并非所有检查都带完整 lineage；`repair_directives` 对缺失 lineage 的 finding 会整批 `blocked`（见当前状态覆盖页） |

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
| 后端提供 `evaluation` / `compliance` / `suitability` / `gis-test` 能力端点 | **后端没有这些旧评估端点**。当前空间现状由 `/api/v1/source-layers` 提供，规划结果由 `/api/v1/sessions/{id}/map-layers` 提供；`evaluation` / `compliance` / `suitability` 仍属于未接入的评估面板能力（`GAP`） |
| `/api/dev/gis/*` 由后端提供 | 旧独立 GIS 测试页及其 `/api/dev/gis/*` 客户端已移除；GIS 验证统一在规划工作台走 DataCatalog、空间链路和 DELIVER API |
| 真实 OpenAPI 路径 | `docs/contracts/openapi-v1.json` 实测有 10 个 v1 操作（sessions 创建/resume、state、events、events/sync、human-review GET/POST、delivery、map-layers、artifacts、evidence/query）。其中 `POST /api/v1/sessions/{session_id}/evidence/query` 是统一的村庄/设施/空间证据查询入口，返回受限的 `EvidenceBundle`、`SpatialCognitionEvidence` 和 `EvidencePacket`；几何仍只通过 feature ref 回到 bundle，不由 KG 直接下发。请求只有显式 `include_external=true` 才允许外源 provider 参与，本地不足时才调用；未配置 provider 返回 typed unavailable，配置 `EVIDENCE_EXTERNAL_PROVIDER=exa` 且提供 `EXA_API_KEY` 时走有界 Exa HTTP adapter，应用关闭时回收连接。前端 `EvidenceQueryPanel` 可点击候选 feature ref，按 BSM/source feature id 回地图缩放。 |

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
| `test-gis` 页面生产可用 | 独立 `test-gis` 页面已移除；GIS 验证统一通过规划工作台的真实 DataCatalog、空间链路和 DELIVER 结果完成 |
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
- `23_EXPLORE_RETRIEVAL_REDESIGN.md`：当前仍是活跃设计；`retrieve_evidence()` 已有局部 producer，
  但 router/query plan/sufficiency 和 gate-driven retrieval 未接入主图，不能按设计宣称已实施。
- `05_EXPLORE_BRIDGE.md` / `07_VALIDATION_FEEDBACK.md` 中的部分目标：证据/反馈闭环仍 `PARTIAL`。
- 前端 `compliance/evaluation/suitability` 的评估类端点：后端无路由（`GAP`）；旧 `gis-test` 开发入口已移除。

## 13. 维护规则

- 本文件与当前状态覆盖页同属“以实际代码为准”的事实台账
  的台账；设计文档修改后，先在本文件登记差异再改设计。
- 发现新的不一致：在对应小节追加一行（设计说法 / 实际实现 / 证据路径），不要在多个文档
  各写一套。
- 归档文档（`docs/_archive/`）与审计历史中的旧路径只作为历史证据，不作为当前事实。


## 14. 新增差异登记（2026-08-15，以代码为准）

- 子图 checkpoint 实证：四段子图均带 checkpointer，`checkpoints.checkpoint_ns` 存在 `spatial_chain:<uuid>` / `cognitive:<uuid>` / `hitl:<uuid>`；父层 `aget_state_values` 在 spatial_chain 运行期间冻结，恢复必须用子图 ns checkpoint。
- 崩溃恢复：新增 `PlanningRuntimeService.resume_from_deepest_checkpoint`（读 `aget_state(subgraphs=True)` 取最深 pending 子图 task config，按官方 time-travel 从该 checkpoint 续跑），driver startup kick 改用它；`resume_execution` 不再用于崩溃恢复。
- `apply_human_review_decision`：空 `deferred_target_ids` + defer 标记 -> 纯 approve（不再 `HUMAN_DEFER_TARGET_IDS_REQUIRED` 死态）。
- `_approve_ground` / `_approve_default`：审批后按 `STAGE_FORWARD_TARGET` 继续（ground->select），不再静默 END 或回环 HUMAN（修复 run#6 post_l3 死态）。
- 校验预算：`validation_budget_used` 通道 + `VALIDATION_BUDGET_PER_SESSION`。

## 15. 关系感知空间规划生成差异（2026-08-17）

[28_RELATION_AWARE_SPATIAL_PLAN_GENERATION.md](modules/spatial-execution/28_RELATION_AWARE_SPATIAL_PLAN_GENERATION.md)
是 TARGET / NORTH STAR，以下能力不得按文档宣称已经实现：

| TARGET 设计 | 当前实现（证据） |
|---|---|
| L1 mention、PlaceIdentifier、canonical SpatialFeature 分层，并写入独立 KG overlay | domain/ground/anchors.py 的 _inject_anchors_into_kg 会把 anchor 增强重放到会话 KG；当前没有完整的 l1_observations / entity_bindings named graph 生命周期 |
| 地名采用 mention graph + Top-K 联合消歧 | evidence/index/place_evidence_index.py 已有多来源候选、别名/类型/拓扑评分，但主要仍按单 mention 解析；LLM fallback 尚未形成关系组级闭集联合解析 |
| 村级 anchor 只表示 village_scope | 当前 PlaceEvidenceIndex._bind_village_anchor_bsms 可把村庄 BSM 集绑定给未命中的非村级 L1 fact；契约尚无 geometry_granularity，下游可能误读为实体级候选 |
| 现状关系、desired relation、constraint factor、satisfaction 分层 | v2 contracts、projection compiler、ScenarioSolver 和 final validator 已形成可测试闭环；SELECT 已持久化 `planning_scenario`，VALIDATE 已从最终 PlannedState/网络上下文计算并持久化 `final_relation_validation`，DELIVER 已读取该结果并在缺失/失败时降级 partial；当前活动 demo 尚无有效交付图层，因此真实主链 acceptance 仍为 `PARTIAL` |
| 设施服务使用真实 demand–facility 网络阻抗和容量 | `NetworkGraphSnapshot`、`DemandSnapshot`、service-area evaluator 和 ScenarioSolver network subproblem 已实现，明确拒绝现状设施邻近代理；主链 demand/network artifact 与真实村庄验收仍待完成 |
| 点、线、面分别生成 typed CandidateGeometry 并联合求解 | GROUND candidate-domain builder 与 ScenarioSolver 已保留 execution/candidate-only geometry role，并在统一 scenario ledger 中选择；KG L1 现已持久化 source-backed road line/facility point WKT，但 fresh 主链尚未证明这些 exact features 下沉到 map-layers |
| KG 约束与精确空间查询可直接供约束编译和最终验证 | `KGSemanticQueryAdapter.get_constraints()` 会按 scope 查询实体并读取 `legal_constraint`/`allowed_operation` 谓词，找不到匹配实体或约束时才返回空列表；`resolve_ambiguous()` 会按实体名称/别名进行 exact/substring 评分，唯一最高分才返回 URI，空输入、无匹配或并列最高分返回 `None`；`KGSpatialQueryAdapter.compute_overlap()` 使用 Shapely WKT 几何计算交集面积与较小面积之比，零面积时返回 intersects 的 0/1，异常时返回 0，前提是输入几何有效，不是 bbox 面积近似。当前仍应视为 adapter 级能力，不能替代全链最终关系 acceptance |
| 缺失 capability 的目标持久化 deferred，未来 resume | 当前部分路径能产出 deferred/diagnostic，但 typed capability registry、durable deferred ledger 与恢复后的目标重规划闭环尚未完整实现 |

## 16. 关系感知规划当前验收门槛（2026-08-17）

当前活动 demo 的有效规划图层为 0；默认 `.run-tmp/runs` 最近会话没有
`render_layers`、`delivery_spatial_snapshot`、`planned_state` named ref。2026-08-12
历史隔离运行的 660 个 `complete_planned_landuse` 是 baseline 延续，实际 `ParcelChange` 为 0，
另有 17 个 project points、16 个 facilities；这些数字不得写进 CURRENT 规划产出。

`scripts/render_integrated_map.py` 直接读取静态 current/planned 文件和报告，属于 standalone
展示，不是 `DeliverySpatialSnapshot → RenderLayers → /map-layers` 主链证据。

关系感知实现的五列台账见
[`RELATION_AWARE_MODIFICATION_LEDGER.md`](RELATION_AWARE_MODIFICATION_LEDGER.md)。任何模块只有在
schema、producer、consumer、validator、acceptance 五列同时有证据时，才可标记 `CURRENT`；其中
acceptance 必须包含主 workflow 的非 baseline feature、稳定 lineage、最终关系重测量，以及 fresh/resume
和 `/map-layers` 读取。

### 2026-08-18 状态增量：clone-only replay28 已有 partial 非空产出

上述“默认活动 demo 为零”的判断仍适用于尚未切换到 source-aware fresh bundle 的默认入口，
但不能覆盖后续的 clone-only replay28 证据。该分支从 clean main cursor 完成了
`TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`，
产出 42 个 exact Point 候选、16 个 selected/final features、15 个 render layers，且独立
final relation validation 为 0 findings；delivery 状态为 `partial`，154/170 个目标仍延期，
道路/轴线 exact Line 仍为 0。因而当前五列表的 acceptance 应写成：模块级和隔离 replay 已有证据，
默认 fresh live/resume acceptance 尚未完成，不得将 replay28 标为 `complete`。

另一个已修复的入口问题：`scripts/run_pipeline_real_jintian.py` 现在先创建 planning session，再调用
`ensure_session_kg()`。这样 KG 的 snapshot-first 逻辑可以读取该 session 的 bundle，而不是在 session
尚未存在时退回 village-wide catalog；这只修正 source-aware bundle 的初始化顺序，不代表已经完成
高内存 real graph acceptance。该入口仍应通过 `low_memory_spatial_acceptance.py` 的 clone/preflight
约束运行，运行后检查无 Python/uvicorn 残留。
