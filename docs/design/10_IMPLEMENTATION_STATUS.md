
# 实现状态台账

> 本表按当前代码记录事实状态，不把目标设计、目录存在或单元测试通过误认为端到端已实现。

状态：`CURRENT` 当前生产路径有代码和证据；`PARTIAL` 有片段但闭环或验收不完整；`GAP` 目标要求尚未实现或接线断裂；`TARGET` 仅为设计；`HISTORICAL` 为带日期的历史证据；`DEPRECATED` 为兼容或迁移残留。

> 2026-08-12 重构分支说明：下方 7.2/7.3 的历史运行数字只作为审计证据，不能替代当前
> `tests/acceptance` 的真实图 resume 验收。当前代码已经切换到 CAS descriptor 和
> `SessionDataSnapshot/SpatialWorkspace` 边界；真实 MiniMax checkpoint、实际 PNG/HTML
> 和 GeoJSON 已有可复核记录，但尚未形成“无 HUMAN 阻塞的完整法定规划”验收。本轮早期触发
> 真实 LLM 测试时，运行环境为 `provider=deepseek` 且
> 未配置任何 provider key；preflight 未能在超时窗口内完成，测试现已在无 key 时明确 skip，
> 有 key 的环境才会执行真实调用。

> 2026-08-12 最新真实验收已通过：`test_real_graph_resume_delivery` 为 `1 passed in 800.03s`。
> 真实链使用配置的 provider，经历真实 LangGraph HUMAN interrupt/checkpoint reopen/resume，完成
> post-L3 到 DELIVER；最新产物目录为
> `.run-tmp/real-llm-41545f0093904940b7d0a47315103664/db6118ac-2efe-4cc5-9168-489444fb0f54/`。
> 本次真实读取到 660 个 `complete_planned_landuse` 地块、17 个 `planned_project_point` 和 16 个
> `planned_facility`；HTML 同时含 `current_landuse` 与 `complete_planned_landuse`，PNG 已实际查看为
> 一张现状/规划双面板。该会话仍按 manifest/DeferralLedger 表达 `partial`，不宣称法定规划完整。

## 0. 2026-08-11 阻断性纠正

- 当前真实 LLM checkpoint 在 GROUND 暂停，L3 program 含 205 个 interventions、131 个空间对象，
  GROUND 有 74 个待审项；该运行不得 approve，也不构成真实规划闭环。
- L3 的 Markdown `【INSTRUCTION】` -> 旧解析器生产路径已在本重构分支删除。当前 LLM 只输出
  `PlanningClaimSet`；这只解决传输边界，仍不能替代需求、规模、可行性、重复和跨专业冲突的领域决策。
- 目标规划形成见 [14_BACKEND_MODULE_BLUEPRINT.md](14_BACKEND_MODULE_BLUEPRINT.md)：
  `DemandModel -> SuitabilityModel -> AllocationModel -> ScenarioModel`。LLM 只产生带证据 claims。
- Artifact CAS 已完成代码级收敛：`ArtifactDescriptor`、不可覆盖 blob/descriptor、named-ref CAS、
  parent digest 和 checkpoint fork 已进入 runtime/L1/L2/L3/target-projection/post-L3/v1 查询；真实进程重启
  resume 仍需单独验收，不能由合同测试代替。
- deterministic SQLite GIS resume 只证明 checkpoint 和空间交付通路，不证明真实 LLM 规划语义；
  当前没有通过实际规划内容与视觉验收的完整真实会话。

## 1. 阶段与产物

| API/SSE 稳定边界             | CURRENT / PARTIAL | `app/api/routes.py` 聚合 `app/api/v1/routes/`；事件序号与历史由 `infrastructure/events/repository.py` 管理，`connection_hub.py` 只管理在线队列，`application/queries/run_events.py` 统一 replay/sync；outbox/跨进程发布完整拆分仍未完成。 |
| Data/Spatial typed boundary  | PARTIAL           | `app/data/model/snapshot.py` 冻结 `SessionDataSnapshot` manifest，`app/spatial/model/workspace.py` 注入 `SpatialWorkspace`；collection registry、质量报告和统一空间内核仍待完成。 |
| KG typed workspace 边界      | PARTIAL           | `app/infrastructure/kg/service.py` 消费 typed spatial input；GIS tool 已改为注入 `spatial_workspace`，KG 与空间 adapter 的参数命名/契约仍需继续收敛。 |

| 能力                          | 状态              | 当前实现事实                                                                                                                                                                                                                                                |
| ----------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PlanningContext               | PARTIAL           | `app/infrastructure/context/` 可构建 Bundle、KG、Gazetteer、SpatialQueryPort 和报告视图；runtime、completion、gis 仍存在重复构建/恢复风险。                                                                                                                     |
| L1 并行报告                   | CURRENT           | `app/workflow/layers/` 与 `app/domain/assessment/` 生成并聚合 12 维 `AnalysisReport`，保留 `content`、`instruction`、provenance、SSE 和报告存储写入。                                                                                                           |
| L1 typed fragment / snapshot  | PARTIAL           | `L1_OBSERVATION` compiler profile、`L1DimensionFragment` 和 `l1_aggregate` 存在；aggregate 通过 ReportStore 读取报告并写入 CAS，已返回显式 `l1_snapshot` descriptor，但认知链尚未迁移为蓝图中的 ASSESS/OBJECTIVES。 |
| DimensionReport.summary       | CURRENT / LEGACY  | summary_generator 可生成结构化预览字段；它不是权威事实，字段冲突时低于 evidence、正文和 instruction。                                                                                                                                                       |
| L2 Strategy                   | CURRENT / PARTIAL | 独立`l2_strategize/worker.py`、`aggregate.py`、G2 gate 和 review package 存在；策略对 Grounding、Selection、ExecutionPlan 的输入约束尚未完整落地。                                                                                                      |
| L3 PlanningProgram            | PARTIAL           | L3 worker 现在只通过 structured output 产生 `PlanningClaimSet`；aggregate 以确定性 adapter 生成非权威 `ProgramProposal`，再由 `domain/program/assembler.py` 唯一组装 `PlanningProgram`。`domain/program/classification.py` 为未决 polygon/parcel 生成显式 HUMAN 决策请求；闭集决定从真实 checkpoint 形成不可变 program revision，再重走空间阶段；未决定目标不得通过 EXECUTE。 |
| TARGET_PROJECTION            | CURRENT / PARTIAL | `app/workflow/stages/target_projection.py` 只对已组装 `PlanningProgram` 做确定性 spatial-reference projection；旧文本解析、LLM patch、merge/review 生产路径已删除，真实全链路仍需验收。 |
| EXPLORE                       | PARTIAL           | `retrieve_evidence()` 已检索 KG、Bundle、报告和 `【INSTRUCTION】`；typed artifact、历史证据、修订记录和 intervention-specific 查询计划尚未完全接入。                                                                                                    |
| 地名解析 / PlaceEvidenceIndex | PARTIAL / GAP     | `SpatialResolver` 已统一 KG/SpatialQueryPort、Gazetteer、Bundle 和方向 bbox 路径；当前尚未把 L1 typed location facts 纳入候选索引和评分，短名称 fuzzy 也不能作为可靠的自动解析。设计见 `12_PLACE_NAME_RESOLUTION.md`。                                  |
| GROUND                        | CURRENT / PARTIAL | `ground_aggregate` 产出 `GroundingResult/CandidateSite` 和 gate；候选与 intervention 的强关联、约束证据完整性和真实 session 接线仍需验证。                                                                                                              |
| SELECT                        | CURRENT / PARTIAL | `app/workflow/stages/select.py` 接到 `app/domain/{demand,suitability,allocation}`，使用硬约束、评分和冲突分配产出 `SiteSelectionDecision`；`PortfolioDecision` 未达 `OPTIMAL/FEASIBLE` 时 gate 强制 HUMAN，真实会话验收仍待完成。 |

| LLM 调用 binding tool         | PARTIAL / GAP     | 详见 [17_LLM_TOOL_BINDING.md](17_LLM_TOOL_BINDING.md)。意图工具 `advance_planning_intent` / `gis_analysis` 由 `workflow/conversation/node.py` bind 并路由（CURRENT）；access 读路径工具（`bundle_overview` 等 6 个）已注册到 `ToolRegistry` 但无节点 bind（GAP）；`workflow/tools/execute_node.py` 读取遗留空 `tools.py:TOOL_REGISTRY`，通用执行路径无法执行已注册工具（GAP）；L3 结构化输出走 `with_structured_output(method="function_calling")`（CURRENT）。 |

## 2. EXECUTE 与 GIS

| 能力              | 状态                    | 当前实现事实                                                                                                                                                                                                                                                                                           |
| ----------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| EXECUTE 子图      | CURRENT / PARTIAL       | `execute_agent.py` 已重构为多 worker 子图：`route_tasks → prepare_inputs → project_worker → zone_worker → [facility_worker ‖ axis_worker] → road_worker → merge_worker_results → geometry_materialize → planned_state_builder → execution_review`；各 worker 返回统一 `WorkerResult`。 |
| Project Worker    | CURRENT / PARTIAL       | `land_design_worker.py` 支持项目 footprint、OBB/split 相关操作；仍由集中式 execute_agent 调度，未形成独立 WorkerResult 契约。                                                                                                                                                                        |
| Zone Worker / MIP | CURRENT / PARTIAL       | `workflow/stages/execute.py` 接入 zone worker 和 `ZoneAllocatorPort + PuLP adapter`，不可行显式 unresolved；其余 zone 仍使用确定性 reclassify。                                                                                                               |
| Custom zoning     | PARTIAL                 | `custom_zone_contracts.py`、`custom_zone_generator.py` 和 `spatial_ops/custom_planning.py` 仍存在；当前主要是词汇/图层生成与规则路径，尚未成为由 L2/L3 目标驱动、经 MIP/约束求解的新规划分区。                                                                                                   |
| Facility Worker   | CURRENT / PARTIAL       | `_execute_facility_node` 已改为决策驱动，不再默认从 KG POI 自行找点；尚未统一为独立 `FacilityWorkerResult` 并进入统一 ExecutionPlan。                                                                                                                                                              |
| Road Worker       | CURRENT / PARTIAL       | staged road pipeline 位于 `app/spatial/` 与 `app/domain/materialization/`；简化 fallback 已删除，RoadPlannerPort 收敛仍属后续工作。                                                                                                        |
| Axis Worker       | CURRENT / PARTIAL       | `_execute_axis_node` 和 AxisBuilder 存在，但与项目、分区、道路统一设计依赖尚未固化。                                                                                                                                                                                                                 |
| ExecutionPlan     | CURRENT / PARTIAL | `execution_plan_contracts.py` 的 `ExecutionPlan` 只保存 `portfolio_decision_ref`、worker tasks、依赖和 brief；不再嵌入 `intent`/`site_selection` 副本，task binding 是 worker 的唯一目标输入。真实链路仍需验收。 |
| ParcelChangeSet   | CURRENT                 | `land_design_worker` 和 `planned_state_builder` 可生成/转换统一 changeset；仍需禁止后续节点在 PlannedState 生成后静默修改 changeset。                                                                                                                                                              |
| PlannedState      | CURRENT / PARTIAL       | `changeset_to_planned_state` 和 L4 写回存在；主状态、layout configs、changeset 在部分路径仍可能出现版本不同步。                                                                                                                                                                                      |

## 3. 校验、对账与交付

| 能力                 | 状态              | 当前实现事实                                                                                                                                               |
| -------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| VALIDATE             | CURRENT / PARTIAL | `app/workflow/stages/validate.py` 与 `app/domain/validation/` 提供确定性检查、ValidationReport、责任阶段和 gate；必须以唯一 changeset→planned state 流程校验。 |
| RECONCILE            | CURRENT / PARTIAL | 已有 coverage matrix、链路覆盖检查、责任归因和 gate；对 intervention/spec/candidate/selection/change/planned 的关联仍依赖 ID 与兼容对齐逻辑。              |
| DELIVER              | CURRENT / PARTIAL | `DeliverySpatialSnapshot` 已成为 render/export/land-balance/map 的唯一输入；真实产物写出 660 current/planned features、17 个项目点、16 个设施点、双 panel PNG 和 HTML。无任何非 preserve/unchanged `ParcelChange` 时快照强制为 `partial`，PNG/HTML 明示“地类变更 0 个”，不能把现状复制图当作规划成果；法定完整规划仍受显式分类决定、延期和交付闸门约束。 |
| Step report          | CURRENT / PARTIAL | `app/infrastructure/reports/step_report.py` 与 `app/infrastructure/reports/stage_report.py` 生成运行审计；是否覆盖所有 post-L3 节点需以实际接线为准，不应把它当 typed artifact。 |
| Artifact persistence | CURRENT / MIGRATING | `artifact_schema_version=3` 的 `ArtifactDescriptor` 已接入 runtime、L1/L2/L3/target-projection、post-L3、v1 查询和 StepReport；blob/descriptor create-if-absent，named ref compare-and-set，parent digests 和 branch identity 可验证。旧 `FilesystemArtifactStore`、`ArtifactRef`、revision 路径已删除；EventRepository 已承接事件历史；根图已使用 `WorkflowState`，`workflow_progress` 已收紧为身份、refs 与显式 `stage_payload`，但其中的旧阶段载荷仍需继续拆成 typed artifacts。 |

## 4. 分层与遗留路径

| 区域                                        | 状态                 | 说明                                                                                                                                         |
| ------------------------------------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/services/modules/gis/road/`          | 已删除               | 已迁移至`app/modules/spatial_ops/road/`，`services/modules` 目录已删除。                                                                 |
| `app/modules/spatial_ops/road_planner.py` | DELETED              | 简化道路 fallback 已删除；road worker 无可用 plan 时显式 unresolved。                                                                        |
| `app/tools/gis/_generation/`              | DELETED | 旧 dev layout pipeline 已删除；正式 EXECUTE/DELIVER 只走 `agent/execute` + `modules/spatial_ops`。 |
| `app/agent/select/`                       | CURRENT              | 正式 SELECT 入口；空间候选只消费 `target_projection` artifact，不再承担文本解析 fallback。 |
| `layout_contracts.py`                     | DELETED              | 已删除；`ZoneIntent/UnifiedSpatialIntent/AllocationResult` 等旧 LAYOUT 契约不再由 schema 导出。                                            |
| `parse_contracts.py`                      | PARTIAL              | 同时承载 intent target、spatial operation、constraint 和指标表；后续应拆为 intent/operation/indicator 三组，但不能在未迁移调用方前直接删除。 |
| `contracts/__init__.py`                   | DEPRECATED TARGET    | wildcard 导出过多；已移除`layout_contracts` 导出，业务代码仍应从具体契约文件显式导入。                                                     |
| `planning_text/`                           | DELETED              | 旧的报告复制/模板文档生成器无生产调用，已删除；当前规划交付以 typed artifacts、DeliveryManifest 和空间快照为准。 |

## 5. 当前可验证边界

当前单元测试能够较好覆盖各 aggregate、gate、contract 和局部 GIS 算法；它们不能证明真实规划闭环。
必须单独完成以下验收：

```text
现状报告 + VillageBundle + Session KG
  → L1/L2/L3 typed artifacts
  → PlanningProgram
  → TARGET_PROJECTION/GROUND/SELECT
  → ExecutionPlan
  → Project/Zone/Facility/Road/Axis Workers
  → ParcelChangeSet
  → PlannedState
  → VALIDATE/RECONCILE/DELIVER
```

验收必须证明：项目不是简单匹配现状点；自定义功能区由规划目标和约束求解产生；道路连接正确目标；
changeset、planned state、validation、reconciliation 和 delivery 的版本和 provenance 一致。

## 6. 近期优先级

1. 冻结 canonical contracts 和显式 import，清理 `layout_contracts`/旧 SELECT 入口的新增依赖。
2. 统一 PlanningContext 与 artifact refs 的主状态传递。
3. 定义 `ExecutionPlan`、`ZoneAllocatorPort`、`RoadPlannerPort` 和统一 WorkerResult。
4. 恢复/重构 MIP ZoneAllocator，收敛 staged Road Planner，禁止静默 fallback。
5. 再重构 EXECUTE 子图，并进行真实 GIS + 报告端到端验收。

## 7. HISTORICAL：状态更新与历史修补

本节及其子节保留审计轨迹，不是当前台账。它们可能包含已经删除的路径、当时的测试数字
和一次性迁移结论；若与第 2–6 节或当前代码冲突，以当前代码和前面的汇总为准。

### 7.1 自动迭代与多模态状态（2026-08-11）

| 能力 | 状态 | 当前实现事实 |
|---|---|---|
| `ValidationReport` 检查与责任归因 | CURRENT / PARTIAL | `backend/app/agent/validate/` 已有 checks、issues_by_stage、GateDecision 和 issue fingerprint。 |
| `ValidationReport.adjustments` | PARTIAL | 契约字段和部分调整逻辑存在，但尚未由统一执行器驱动 GROUND/SELECT/EXECUTE 的自动修复。 |
| 产出驱动自动迭代 | GAP | 当前主要是 retry、HUMAN 或 diagnostic，尚未稳定形成“诊断→调整→受影响阶段重算→复验”闭环。 |
| 自动迭代设计 | TARGET | 见 `docs/design/13_AUTOREPAIR_MULTIMODAL.md`；设计要求复用现有 adjustment/revision/artifact 体系。 |
| 图片 API 输入 | PARTIAL | `ImageData` 和会话 images 字段存在；主运行链尚未形成统一媒体 artifact。 |
| 图片 State 引用 | PARTIAL | `image_ids` 可保存引用，但没有可解析的媒体元数据、区域和版本链。 |
| MiniMax 图像消息 | GAP | L1 目前主要发送文本并记录 `has_images`，尚未证明相关图片进入真实 `image_url` 请求。 |
| OCR/版面/视觉证据 | GAP | 尚无统一 ImageEvidence/VisualFact/VisualReview artifact 链路。 |
| 多阶段视觉消费 | GAP | L2/L3/TARGET_PROJECTION/GROUND/SELECT/VALIDATE/DELIVER 尚未正式消费视觉 evidence。 |
| 视觉驱动自动迭代 | GAP | 图片问题尚未稳定绑定 target 并写入现有 ValidationReport adjustments。 |

以上状态是当前实现事实；不得因为 `ImageData` 字段存在、设计文档存在或单元测试
通过，就把多模态能力标记为 CURRENT。

### 7.2 第一轮断点修补（2026-08-10）

本轮已完成并由本地回归验证：

- SELECT 对空间目标实施 fail-closed：仅消费目标绑定候选；无目标专属候选时输出 `unplaced` 及稳定原因码，进入 HUMAN/RETRY，不再使用全局地块池。
- L1/L2/L3 摘要 enrichment 统一由 `TaskSupervisor` 管理，任务键为 `session_id:summary:{layer}:{dimension}:{version}`；会话删除会取消并等待该会话任务，应用 shutdown 继续全量回收。
- `ArtifactDescriptor.parent_digests` 已进入 descriptor；resume 校验父 blob/descriptor identity，父元数据缺失或不一致时从最早失效阶段重跑，HUMAN interrupt 仍优先。
- 新增生产主图的确定性空间闭环验收，覆盖 SELECT → EXECUTE → RenderLayers → VALIDATE → RECONCILE → DELIVER，并校验 DeliveryManifest、FeatureCollection、PlannedState 与 artifact checksum/引用一致性；该用例使用合成 GIS bundle，不等同于真实村庄成果验收。

历史验证曾覆盖 `jintian` GIS SQLite checkpoint → resume → DELIVER，并读取过 PNG/HTML；该记录不是本轮真实 LLM 验收证明。当前核心回归为 `101 passed`；真实 LangGraph + provider resume 仍必须实际执行，不能由单元测试替代。随后修复 DELIVER 对序列化 L1 地块字典的读取、无来源 planned parcel 进入法定平衡、DeferralLedger artifact 映射、延期后无活动空间任务的 VALIDATE 契约、阶段报告 checksum 回退和 GROUND 全量延期回环；均未放宽用地平衡门槛。EXECUTE 的跨阶段根引用现已收敛为 `ExecutionResult`，其精确子引用承载 `ParcelChangeSet` 与 `PlannedState`。

### 0.1 2026-08-12 真实迁移验收增量

本分支随后已在配置的 MiniMax provider 上执行真实会话 `3ff1dcf6-8ece-4368-9a51-f3edfc6419bd`：

- 真实输入边界：660 个现状地块、131 条道路、235 个约束图层、25068 条 KG 三元组；输入经过
  `SessionDataSnapshot/SpatialWorkspace`，没有把裸 `gis_data` 注入 Agent。
- 真实 checkpoint/resume：L1、L2、L3、GROUND、SELECT、VALIDATE 均发生真实中断/恢复；HUMAN
  明确延期空间目标后生成新的 `ExecutionPlan` revision，剩余 action/point/axis 继续执行。
- 真实阶段闭环：`TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`
  已写入真实 StepReport；交付状态为 `partial`，DeferralLedger 有 123 条明确延期记录。
- 真实空间产物：`DeliverySpatialSnapshot` 中 current 与 complete planned 均为 660 个 Feature；
  `planning_map.html` 与双面板 `planning_preview.png` 已写出并实际读取。
- 发现并修复两个新架构边界缺陷：`RenderLayers` 是合法列表 artifact，却被 v1 API 当成缺失；规划
  侧占位 `POINT (0 0)` 参与共享范围计算，导致真实 PNG 空白。API 列表投影和现状边界主导范围
  已修复，并在后续真实分支中复核了双面板 PNG、HTML、GeoJSON 与 snapshot quality report。

新增连续 HUMAN 路由回环与 DELIVER ledger reconciliation：延期 ExecutionPlan task 若来自后续人工修订而缺少台账链接，会在交付边界生成明确的系统审计条目，不静默转为已交付。下一断点是补齐真实输入的法定空间证据/图层闭合，使真实运行达到 `partial` 或 `PASS`，而不是放宽交付闸门。

### 0.2 2026-08-12 真实检查点续接与阶段迁移

问题登记与迁移边界见 [backend-migration-issue-register-2026-08-12.md](../audits/backend-migration-issue-register-2026-08-12.md)。本轮核对确认真实运行产出了 17 个规划项目点和 16 个公共服务设施点，但 660 个期末地块全部 `preserved`，`ParcelChangeSet` 为 0；因此不能把点位存在解释为地类规划已落地。`workflow_progress` 已取消开放式顶层扩展，但旧阶段载荷和阶段 ad-hoc 出口仍是迁移项；SSE 进程内事实缓存已删除，跨进程 outbox/publisher 仍是迁移项。

本轮代码迁移增量：`workflow_progress` 使用显式 `stage_payload`；TARGET_PROJECTION/GROUND/SELECT/VALIDATE/RECONCILE/DELIVER 六个新阶段统一通过 `StageCompletion` helper 持久化输出 refs 和 CAS `GateDecision` ref。当前非 E2E 回归为 `131 passed, 14 deselected`；真实 acceptance 因当前 shell 未配置 provider credential 为 `2 skipped`，不能替代新的真实 checkpoint resume。

真实会话 `77c3dfc7-30cb-460e-8266-26027401e6f2` 在验收驱动提前退出 HUMAN 循环后，使用保留的
SQLite LangGraph checkpoint 和官方 `Command(resume=...)` 重新续接；不是读取预置输出。新分支
`resume-delivery-snapshot-fix-3` 实际完成 `EXECUTE → VALIDATE → RECONCILE → DELIVER`，写出
`DeliverySpatialSnapshot`、`RenderArtifacts`、`DeliveryManifest`、PNG、HTML 和
`complete_planned_landuse.geojson`。EXECUTE 统计为 37 个 worker task、104 个明确延期、0 个
`ParcelChange`，交付层有 2 个设施点 overlay；manifest 为 `partial`，660 个期末地块全部为
`change_status=preserved`。这说明交付链可运行，但该真实会话的规划语义没有形成地块变更，不能
宣称为完整规划成果。

本次真实产出质量复核通过：current/planned 各 660 个 feature，`invalid_geometry=0`、空几何 0、
占位点 0；源数据中的可恢复拓扑错误在 Data→DELIVER 边界由 `make_valid` 收敛，规划 `(0,0)` 点
被省略而不是被猜测。`planning_preview.png` 是一个包含现状/规划两个面板的 PNG；规划面使用真实
快照地类字段着色并增加细边界，`planning_map.html` 与 GeoJSON 均来自同一快照。

同时修复了真实验收驱动：resume 中间态不能被当作终态，后续 HUMAN checkpoint 必须继续处理；新增
`resume_graph_checkpoint.py --branch-id ... --deferred-target-ids ...`；历史 checkpoint continuation
现在先 fork immutable artifact refs，再继续图，不会把另一分支的 named ref 误判为 replay 冲突。真实
新分支回放已实际完成 `EXECUTE → VALIDATE → RECONCILE → DELIVER`；期间修复了历史分支
`branch_id` reducer、HUMAN checkpoint generation、结构性延期从 HUMAN item 读取目标 ID，以及
Delivery snapshot 的几何/占位质量闸门。DELIVER 入口已迁移到 `backend/app/workflow/stages/deliver.py`，
旧 `main_nodes.py` 已删除，HUMAN projection 归 `application/interrupts.py`；`partial` 必须继续作为前端和法定成果判断的硬边界。

### 7.3 历史真实 MiniMax 验收记录（非当前验收）

面积字段契约修复后，历史真实 MiniMax 主图曾完成全阶段并通过 `2 passed`。该记录仍只用于追溯；
当前真实产物与证据以 0.2 的 `resume-delivery-snapshot-fix-3` 分支为准。

`area_sqm` 已在执行、parcel_ops、zone allocator 路径统一换算为公顷；不再使用数值大小推断单位。摘要 enrichment 的 MiniMax 结构化调用仍有 max_tokens/schema 警告，但主报告和阶段 artifact 完整落库，异常由 TaskSupervisor 记录并回收。
| GIS 输入边界 | PARTIAL | DELIVER、EXECUTE workers、render/export tools 统一从 data-owned `SpatialWorkspace` 经 adapter 读取；已删除 `ExecuteAgentState.gis_data`、`gis_bundle` 与 GIS tool 的 `InjectedState("gis_data")`，仍需完成所有 spatial adapter 的 typed contract。 |
| AgentState 原始上传 GIS | COMPLETE | 删除 `user_uploaded_data`，原始上传内容只由 upload/data layer 持有；主图保留文件元数据与引用。 |
| 旧 GIS 全量状态模型 | COMPLETE | 删除 `app/agent/deliver/gis_pipeline_state.py`；交付统一由 `DeliverySpatialSnapshot` 和 `DeliveryManifest` 驱动。 |
| DELIVER 渲染职责 | COMPLETE | PNG/HTML 渲染已抽离至 `agent/deliver/delivery_renderer.py`，主节点只负责阶段编排与 artifact 持久化。 |
| 交付渲染输入 | COMPLETE | `build_delivery_render_layers()` 改为只接收 `DeliverySpatialSnapshot`，current/constraint 图层从 snapshot source refs 加载。 |
| 交付导出输入 | COMPLETE | `export_delivery_package()` 只接收 `DeliverySpatialSnapshot`；current/constraint/planned 和土地平衡均从同一 snapshot 读取，旧 `export_gdb_package()` 入口已删除。 |
| 前端空间查询 | CURRENT / PARTIAL | 稳定 `/api/v1/sessions/{id}/map-layers` 只读取 DELIVER 已持久化的 `RenderLayers` artifact；旧 PlannedState-only 重算路径已删除，未挂载旧 render route 不作为稳定入口。 |
| GIS 工具数据边界 | PARTIAL | `build_knowledge_graph`/render 工具只注入 `spatial_workspace`，GeoJSON 只在 data→spatial/delivery adapter 边界物化；KG service 的旧参数命名仍待清理。 |
| TARGET_PROJECTION 输入恢复 | COMPLETE | `target_projection` 只从 `artifact_refs.planning_program` 读取 PlanningProgram；缺失 ref 直接失败并交给 resume integrity policy，不构造空对象或接受内联业务状态。 |
| Resume 终态产出 | COMPLETE | `post_l3_resume` 返回 `delivery_spatial_snapshot`，终态缺 snapshot 或 PNG/HTML 时降级为 `diagnostic_only`。 |
| DELIVER planned 输入 | COMPLETE | DELIVER 与 EXECUTE 状态均不再保存或读取 `allocated_geojson`；Snapshot 只接收 `ParcelChangeSet` 的 `planned_changes`。 |
| HITL resume 路由 | COMPLETE | SELECT approve 直接继续 EXECUTE；显式 deferral 才生成新 revision，避免 checkpoint 元数据导致重复 HUMAN。 |
| GIS checkpoint resume | CURRENT / PARTIAL | deterministic GIS E2E 已证明主图在 SELECT HUMAN 中断后可通过 SQLite checkpoint 关闭/重开并继续到 DELIVER，产出 660 个期末地块、项目面和定位点；这不是完整真实 LLM/L3 规划验收。当前 acceptance 在缺 provider key 时明确 skip，尚无本轮新真实空间规划 checkpoint。 |

## 8. 2026-08-12 收敛完成状态

本轮后端蓝图重构收敛完成，`tests/e2e tests/core tests/contracts` 全量回归通过
`238 passed`（含新增 `test_blueprint_architecture.py` 的 5 个聚合架构守门测试）。

- 全部阶段已迁移到 `app/domain/`；`app/agent/` 已删除。
- `workflow_progress` carrier 已退役，改为 `runtime` channel；`LEGACY_GATE_STAGES`
  已移除，统一走 CAS `gate_ref`。
- `root_graph.py` 已收敛为唯一 artifact 生产者，不再直接写领域 artifact。
- `app/services/` 已折叠（leaf 模块 → application/infrastructure）；仅 `runtime.py` +
  `context/planning_context.py` 保留（Phase-5 延期项）。
- `app/modules/` 已全部归并到 blueprint 归属目录并删除。
- 存储：checkpoints 分离到 `checkpoints.db`；KG Layer-1 turtle 入 CAS；bundle blob 入
  CAS 且 sha256 校验；session 删除清理全部存储。
- `DimensionReport.summary` 仅为 UI 预览字段，不再作为权威事实读取。

## 9. 2026-08-12 收敛完成（services/tools/utils 消除）

上一节 Phase 9 完成后，继续消除了最后三个遗留 god-module 目录，全量回归为 `242 passed`：

- `app/utils/` 已删除：logger → `infrastructure/logging`（133 文件重指）；sse/event → `infrastructure/events`；
  空间工具 → `spatial/model`；文档加载器 → `data/ingestion/documents`；code_lookup → `data/encodings`；
  rate_limiter/retry/stats → `infrastructure/llm`；删除死代码 parse_reporter/coord_utils。
- `app/services/` 已删除：`PlanningRuntimeService` → `infrastructure/runtime/planning_runtime_service.py`
  （`_trigger_planning_execution` 已公开为 `trigger_planning_execution`）；context 工厂 →
  `infrastructure/context/planning_context_factory.py`。
- `app/tools/` 已删除：LLM 工具注册表 + access 工具 → `infrastructure/llm/tools/`；html/static render →
  `infrastructure/rendering/`；删除死 gis tools（conflict/extract/kg/lookup）与 dangling `.analytics` 3 工具。
- `app/core/` 收敛：events → `contracts/events`（修复 domain→core 依赖方向）；llm → `infrastructure/llm/factory`；
  instructor_client/tracing → `infrastructure/llm/`。仅剩 `settings.py`（52 文件依赖 + 深度敏感路径，保留为 infra-config singleton）。
- `app/graphify-out/` 已删除（stale 工具缓存，gitignored）。
- 输入文档重命名：`bundle.documents.planning_texts` → `input_documents`，与未来的 DELIVER 规划文本输出区分命名。

`app/` 当前仅含 blueprint 目标目录（api/application/bootstrap/contracts/data/domain/evidence/infrastructure/spatial/workflow）
加 3 个文档化 residual：`app/config/`（domain config，12 importer）、`app/core/settings.py`（infra config singleton）、
`app/database/`（persistence adapter，作为 `infrastructure/persistence/` 的别名保留）。

剩余项：真实 LLM acceptance 待验证（需配置 MINIMAX key）；DELIVER 规划文本组装器尚未实现（已确认设计方向，
见 `docs/audits/round-3/storage-architecture.md` 与 DELIVER 导出集成计划）。
