
# 实现状态台账

> 本表按当前代码记录事实状态，不把目标设计、目录存在或单元测试通过误认为端到端已实现。

状态：`CURRENT` 当前生产代码存在；`PARTIAL` 有实现但未形成闭环；`TARGET` 设计目标；`DEPRECATED` 兼容或待删除路径。

## 1. 阶段与产物

| 能力                          | 状态              | 当前实现事实                                                                                                                                                                                                                                                |
| ----------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PlanningContext               | PARTIAL           | `app/services/context/` 可构建 Bundle、KG、Gazetteer、SpatialQueryPort 和报告视图；runtime、completion、gis 仍存在重复构建/恢复风险。                                                                                                                     |
| L1 并行报告                   | CURRENT           | `app/agent/l1_observe/analysis_node.py` 生成 12 维 `AnalysisReport`，保留 `content`、`instruction`、provenance、SSE 和 ReportStore 写入。                                                                                                           |
| L1 typed fragment / snapshot  | PARTIAL           | `L1_OBSERVATION` compiler profile、`L1DimensionFragment` 和 `l1_aggregate` 存在；aggregate 通过 ReportStore 读取报告并写入 FilesystemArtifactStore，尚未成为主图中所有下游的显式 ref 输入。                                                           |
| DimensionReport.summary       | CURRENT / LEGACY  | summary_generator 可生成结构化预览字段；它不是权威事实，字段冲突时低于 evidence、正文和 instruction。                                                                                                                                                       |
| L2 Strategy                   | CURRENT / PARTIAL | 独立`l2_strategize/worker.py`、`aggregate.py`、G2 gate 和 review package 存在；策略对 Grounding、Selection、ExecutionPlan 的输入约束尚未完整落地。                                                                                                      |
| L3 PlanningProgram            | CURRENT / PARTIAL | 独立`l3_plan/worker.py`、`aggregate.py`、G3 gate 和 review package 存在；PlanningProgram 仍主要是干预与依赖汇总，不是完整空间设计方案。                                                                                                                 |
| PARSE / IntentCompiler        | CURRENT / PARTIAL | `app/agent/parse/` 的确定性编译、L3 profile、REPAIR/REVISE 路由和异步 LLM patch 已存在；输出可以组件测试，但真实 session 的完整链路仍依赖 post-L3 接线和 artifact 恢复。                                                                                  |
| EXPLORE                       | PARTIAL           | `retrieve_evidence()` 已检索 KG、Bundle、报告和 `【INSTRUCTION】`；typed artifact、历史证据、修订记录和 intervention-specific 查询计划尚未完全接入。                                                                                                    |
| 地名解析 / PlaceEvidenceIndex | PARTIAL / GAP     | `SpatialResolver` 已统一 KG/SpatialQueryPort、Gazetteer、Bundle 和方向 bbox 路径；当前尚未把 L1 typed location facts 纳入候选索引和评分，短名称 fuzzy 也不能作为可靠的自动解析。设计见 `12_PLACE_NAME_RESOLUTION.md`。                                  |
| GROUND                        | CURRENT / PARTIAL | `ground_aggregate` 产出 `GroundingResult/CandidateSite` 和 gate；候选与 intervention 的强关联、约束证据完整性和真实 session 接线仍需验证。                                                                                                              |
| SELECT                        | CURRENT / PARTIAL | `select_graph/aggregate.py` 使用硬约束、评分和冲突分配产出 `SiteSelectionDecision`；空间项目/设施已改为 fail-closed，只消费目标绑定候选，缺少目标专属候选时转 `unplaced` → HUMAN，不再回退完整候选池；大量 unplaced 原因分型与真实会话验收仍待完成。 |

## 2. EXECUTE 与 GIS

| 能力              | 状态                    | 当前实现事实                                                                                                                                                                                                                                                                                           |
| ----------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| EXECUTE 子图      | CURRENT / PARTIAL       | `execute_agent.py` 已重构为多 worker 子图：`route_tasks → prepare_inputs → project_worker → zone_worker → [facility_worker ‖ axis_worker] → road_worker → merge_worker_results → geometry_materialize → planned_state_builder → execution_review`；各 worker 返回统一 `WorkerResult`。 |
| Project Worker    | CURRENT / PARTIAL       | `land_design_worker.py` 支持项目 footprint、OBB/split 相关操作；仍由集中式 execute_agent 调度，未形成独立 WorkerResult 契约。                                                                                                                                                                        |
| Zone Worker / MIP | CURRENT / PARTIAL       | `zone_worker` 对空候选 zone 经 `ZoneAllocatorPort + PuLP adapter`（`app/agent/execute/zone_allocator_adapter.py`）求解，不可行显式 unresolved；其余 zone 仍使用确定性 reclassify。                                                                                                               |
| Custom zoning     | PARTIAL                 | `custom_zone_contracts.py`、`custom_zone_generator.py` 和 `spatial_ops/custom_planning.py` 仍存在；当前主要是词汇/图层生成与规则路径，尚未成为由 L2/L3 目标驱动、经 MIP/约束求解的新规划分区。                                                                                                   |
| Facility Worker   | CURRENT / PARTIAL       | `_execute_facility_node` 已改为决策驱动，不再默认从 KG POI 自行找点；尚未统一为独立 `FacilityWorkerResult` 并进入统一 ExecutionPlan。                                                                                                                                                              |
| Road Worker       | CURRENT / PARTIAL       | staged road pipeline 已迁移至`app/modules/spatial_ops/road/`，`spatial_ops.road_planner` fallback 已删除；`execute/road_generator.py` 为 EXECUTE 入口，RoadPlannerPort 收敛仍属后续工作。                                                                                                        |
| Axis Worker       | CURRENT / PARTIAL       | `_execute_axis_node` 和 AxisBuilder 存在，但与项目、分区、道路统一设计依赖尚未固化。                                                                                                                                                                                                                 |
| ExecutionPlan     | CONTRACT ONLY / PARTIAL | `execution_plan_contracts.py` 已存在 WorkerTask、AllocationProblem、WorkerResult 等模型；post-L3 EXECUTE 尚未只接受 `SiteSelectionDecision + ExecutionPlan`。                                                                                                                                      |
| ParcelChangeSet   | CURRENT                 | `land_design_worker` 和 `planned_state_builder` 可生成/转换统一 changeset；仍需禁止后续节点在 PlannedState 生成后静默修改 changeset。                                                                                                                                                              |
| PlannedState      | CURRENT / PARTIAL       | `changeset_to_planned_state` 和 L4 写回存在；主状态、layout configs、changeset 在部分路径仍可能出现版本不同步。                                                                                                                                                                                      |

## 3. 校验、对账与交付

| 能力                 | 状态              | 当前实现事实                                                                                                                                               |
| -------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| VALIDATE             | CURRENT / PARTIAL | `app/agent/validate/` 已有确定性检查、ValidationReport、责任阶段和 gate；真实链路可能消费旧 PlannedState，必须以唯一 changeset→planned state 流程校验。 |
| RECONCILE            | CURRENT / PARTIAL | 已有 coverage matrix、链路覆盖检查、责任归因和 gate；对 intervention/spec/candidate/selection/change/planned 的关联仍依赖 ID 与兼容对齐逻辑。              |
| DELIVER              | CURRENT / PARTIAL | 已有 DeliveryManifest、traceability、statutory completeness 和 gate；最终交付质量依赖上游状态版本一致。                                                    |
| Step report          | CURRENT / PARTIAL | `app/services/step_report.py` 与 `stage_report.py` 可生成运行记录；是否覆盖所有 post-L3 节点需以实际接线为准，不应把它当 typed artifact。              |
| Artifact persistence | CURRENT / PARTIAL | FilesystemArtifactStore、review package 和部分节点持久化已存在；GROUND/SELECT/EXECUTE/VALIDATE/RECONCILE 的 ref 尚未全部成为 AgentState 强类型字段。       |

## 4. 分层与遗留路径

| 区域                                        | 状态                 | 说明                                                                                                                                         |
| ------------------------------------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/services/modules/gis/road/`          | 已删除               | 已迁移至`app/modules/spatial_ops/road/`，`services/modules` 目录已删除。                                                                 |
| `app/modules/spatial_ops/road_planner.py` | DELETED              | 简化道路 fallback 已删除；road worker 无可用 plan 时显式 unresolved。                                                                        |
| `app/tools/gis/_generation/`              | PARTIAL / LEGACY MIX | custom zoning、facility、optimizer 辅助代码仍有调用方；需逐项标记 ACTIVE/ADAPTER/DEPRECATED 后再删除。                                       |
| `app/agent/select/`                       | DEPRECATED TARGET    | 仍有旧 parse fallback/state 兼容代码；正式 SELECT 为`app/agent/select_graph/`。                                                            |
| `layout_contracts.py`                     | DELETED              | 已删除；`ZoneIntent/UnifiedSpatialIntent/AllocationResult` 等旧 LAYOUT 契约不再由 schema 导出。                                            |
| `parse_contracts.py`                      | PARTIAL              | 同时承载 intent target、spatial operation、constraint 和指标表；后续应拆为 intent/operation/indicator 三组，但不能在未迁移调用方前直接删除。 |
| `contracts/__init__.py`                   | DEPRECATED TARGET    | wildcard 导出过多；已移除`layout_contracts` 导出，业务代码仍应从具体契约文件显式导入。                                                     |
| `PlanningTextGenerator`                   | DEPRECATED           | 见`PLANNING_TEXT_DEPRECATION.md`；不消费 typed artifacts 和 DeliveryManifest，不作为新规划成果入口。                                       |

## 5. 当前可验证边界

当前单元测试能够较好覆盖各 aggregate、gate、contract 和局部 GIS 算法；它们不能证明真实规划闭环。
必须单独完成以下验收：

```text
现状报告 + VillageBundle + Session KG
  → L1/L2/L3 typed artifacts
  → PlanningProgram
  → PARSE/GROUND/SELECT
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

## 7. 第一轮断点修补（2026-08-10）

本轮已完成并由本地回归验证：

- SELECT 对空间目标实施 fail-closed：仅消费目标绑定候选；无目标专属候选时输出 `unplaced` 及稳定原因码，进入 HUMAN/RETRY，不再使用全局地块池。
- L1/L2/L3 摘要 enrichment 统一由 `TaskSupervisor` 管理，任务键为 `session_id:summary:{layer}:{dimension}:{version}`；会话删除会取消并等待该会话任务，应用 shutdown 继续全量回收。
- `ArtifactRef.parent_checksums` 已进入 manifest；`ResumePlan` 校验父 revision/checksum，父元数据缺失或不一致时从最早失效阶段重跑，HUMAN interrupt 仍优先。
- 新增真实主图的确定性空间闭环验收，覆盖 SELECT → EXECUTE → RenderLayers → VALIDATE → RECONCILE → DELIVER，并校验 DeliveryManifest、FeatureCollection、PlannedState 与 artifact checksum/引用一致性。

验证结果：core `45 passed`；规划链与主图 replay/HITL `59 passed`；确定性空间交付闭环 `1 passed`。真实 MiniMax session 曾完成全阶段运行并生成真实渲染物；修补前最终输入因空间证据不足为 `diagnostic_only`。随后修复 DELIVER 对序列化 L1 地块字典的读取、无来源 planned parcel 进入法定平衡、DeferralLedger artifact 映射、延期后无活动空间任务的 VALIDATE 契约、阶段报告 checksum 回退和 GROUND 全量延期回环；均未放宽用地平衡门槛。最新真实复跑已越过 GROUND HUMAN，但 L3 provider 输出耗时超出验收窗口，最终 `partial/PASS` 仍未证明。

新增连续 HUMAN 路由回环与 DELIVER ledger reconciliation：延期 ExecutionPlan task 若来自后续人工修订而缺少台账链接，会在交付边界生成明确的系统审计条目，不静默转为已交付。下一断点是补齐真实输入的法定空间证据/图层闭合，使真实运行达到 `partial` 或 `PASS`，而不是放宽交付闸门。

### 2026-08-11 真实 MiniMax 验收更新

面积字段契约修复后，真实 MiniMax 主图已完成全阶段并通过 `2 passed`。土地平衡闭合偏差 `0.02%`，DeliveryGate 为 PASS；真实输出包含 HTML 地图、PNG 预览、2 个 RenderLayers FeatureCollection、PlannedState 和 DeliveryManifest。最终 manifest 为 `partial`（145 个真实延期目标，7 个预期空间输出中生成 2 层），`statutory_complete=false`，当前是“真实渲染闭环通过、法定空间成果仍不完整”，不是普通 complete 或法定 PASS。

`area_sqm` 已在执行、parcel_ops、zone allocator 路径统一换算为公顷；不再使用数值大小推断单位。摘要 enrichment 的 MiniMax 结构化调用仍有 max_tokens/schema 警告，但主报告和阶段 artifact 完整落库，异常由 TaskSupervisor 记录并回收。
