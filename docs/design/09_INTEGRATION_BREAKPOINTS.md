# 集成断点与迁移计划

> 本文只记录迁移断点和历史修复线索；目标目录与推荐顺序以 [14_BACKEND_MODULE_BLUEPRINT.md](14_BACKEND_MODULE_BLUEPRINT.md) 为准，当前事实以 [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md) 为准。

## 1. 当前主要断点

| 断点 | 当前表现 | 目标修复 |
|---|---|---|
| Context 重复构建 | runtime、completion、gis 各自刷新 Bundle/KG | 单一 `PlanningContextProvider` |
| EXPLORE 查询粒度 | 当前已统一多源 evidence retriever，但多数请求仍按维度名 context injection | 按 intervention、evidence gap 和空间问题生成查询计划 |
| TARGET_PROJECTION 输入 | 目标投影已切到 `PlanningProgram` artifact；历史 PARSE 语义可能仍残留在旧测试或文档 | 只保留 `PlanningProgram → IntentCompilationResult + SpatialReferenceSpec` 的确定性入口 |
| GROUND 隐式回退 | Gazetteer、中心 BBox 和 resolver 兼容路径仍存在 | 统一 SpatialReference → CandidateSite 失败码，禁止静默扩大候选范围 |
| SELECT 候选回退 | 无项目专属候选时仍可能回退到完整候选池 | RETRY_GROUND / EXPLORE / HUMAN，不得把全池当项目候选 |
| 道路契约 | staged planner 已成为 canonical；RoadPlannerPort 和 worker 输入输出仍需完整收敛 | 单一 Road Worker / RoadPlannerPort，失败显式 unresolved |
| 总重试 | 一个异常可能触发空意图或另一个算法 | Validation Router 定向反馈 |
| L1 命名冲突 | 规划 L1/L2/L3 与 KG L1/L2/L3/L4 混用 | KG 改名 BaseFacts/DerivedRelations/IntentGraph/PlannedState |
| 状态复制 | AgentState、PostL3ChainState、ExecuteAgentState 和兼容 GIS 字段并存 | Artifact 引用 + 单一 Context + 唯一 PlannedState |
| checkpoint 恢复计划缺失 | LangGraph `next`、HUMAN API、层完成 checkpoint 和 post-L3 resume 分别解释恢复 | `ResumePlan` 统一输出 `resume_from/reuse/rerun/reason/checksums`，再由同一 runtime 执行 |
| 稳定 checkpoint 判定 | 旧逻辑依赖未统一写入的 `is_interrupted`，且无法识别 pending interrupt | 以 `PregelTask.interrupts`、`layer_just_completed`、revision 和终态组合判定，不再把 `next` 当 HUMAN 标记 |
| GROUND geometry 缺失 | `source_parcels` 存在但 `available_geometry_wkt` 为空，SELECT 无法生成可执行 anchor | BSM/source parcel → geometry 回查必须是 GROUND 的硬契约；失败显式 `GEOMETRY_UNAVAILABLE`，禁止静默空 geometry |
| post-L3 状态回写 | post-L3 resolve 结果可能成功但主会话仍显示旧 layer pause | 只允许主图 checkpoint 成为 SSOT；resolve 后重新读取同一 thread 的 canonical interrupt/state，禁止旁路结果覆盖状态 |
| EXECUTE 输入 | 当前同时接收 intent、bundle、selection 和 legacy layout 数据 | 只接收 `SiteSelectionDecision + ExecutionPlan` |
| 分区求解缺失 | Wave I 删除 MIP allocator，当前 layout 使用确定性 reclassify | ZoneAllocatorPort + MIPZoneAllocator，失败显式 degraded/unresolved |
| 道路实现重复 | 历史重复入口已删除；保留的迁移残留以 `10_IMPLEMENTATION_STATUS.md` 为准 | staged planner 为 canonical Road Worker，失败显式 unresolved |
| 契约重复 | `parse_contracts`、`layout_contracts`、`custom_zone_contracts`、`execution_plan_contracts` 有概念重叠 | 先冻结 canonical contracts，再删除 layout/legacy 模型 |
| service/module 混层 | 已解决：`services/modules/gis/road` 已迁移至 `app/modules/spatial_ops/road/`，`services/modules` 目录已删除 | RoadPlannerPort + application service + infrastructure adapter |

## 2. 分阶段迁移

### M0：文档和契约冻结

- 冻结目标图、目录和 canonical 命名。
- 新增或整理 contracts：Context、Evidence、Intent、Grounding、Placement、Validation。
- 为旧入口加 `[DEPRECATED]` 标记。

### M1：单一 Context

- 实现 `PlanningContextProvider`。
- runtime 只构建一次 Bundle/KG snapshot。
- completion 和 gis 只读取 artifact 引用。
- 添加同 session、同版本断言。

### M2：拆分 EXPLORE 与 TARGET_PROJECTION（主要完成）

- EXPLORE 删除候选 BSM 写入。
- TARGET_PROJECTION 统一生成 `SpatialReferenceSpec`。
- 删除 Binder 作为业务中间层的职责。

### M3：建立 GROUND / SELECT 子图（主要完成，仍需闭环修复）

- 先迁移 GroundingResult 和 CandidateSet。
- 再迁移 hard filter、评分和 `SiteSelectionDecision`。
- 将低置信度模型排序限制在 Top-K 候选内。

### M4：拆分 L1/L2/L3 子图（主要完成，artifact 接线未完全收敛）

- 每层内部保留并行维度分析。
- 层级完成改为层内 Gate，不再由总路由器解释所有 phase 和 revision。
- 各层只提交一个版本化 snapshot。

### M5：执行、对账和交付（基础完成，能力收敛未完成）

- 通过 `ExecutionPlan`、ZoneAllocatorPort 和 RoadPlannerPort 重构 EXECUTE。
- Execute 最终只消费 `SiteSelectionDecision + ExecutionPlan`。
- 自定义功能区必须由规划目标和分配求解产生，不能由现状地类直接映射。
- 增加 Intent ↔ PlannedState Reconcile。
- Delivery Gate 只交付通过的成果包。

### M6：checkpoint resume planner（新增，目标优先）

- 用 `ResumePlan` 将 LangGraph cursor、pending interrupt、artifact refs、context fingerprint 和 Gate checksum 组合为一个可审计决策。
- checkpoint API 只能恢复 `ResumePlan.mode` 为 `resume_checkpoint` 或 `rerun_from_stage` 的 checkpoint；HUMAN 必须走对应的 canonical interrupt resolve。
- 通过 `artifact_refs` 的父版本与 checksum 计算最早失效阶段；仅重跑该阶段及其下游。
- 为每个阶段补充 replay contract test：输入 context/artifact 不变时必须复用；输入或父 artifact revision 变化时必须生成新的 plan。
- 在 SELECT→EXECUTE→RenderLayers→VALIDATE→RECONCILE→DELIVER 完成一次无外部 provider 的闭环验收后，才能宣称 checkpoint resume planner 可用。

## 3. 迁移验收

- 静态 import 检查不允许 `modules → agent/services/api`。
- 每个子图有 contract test、replay test 和 failure routing test。
- 同一输入和 context version 可重放出相同 GroundingResult。
- 任何最终选址都有 `SiteSelectionDecision` 和证据。
- 任意失败都能定位到 L1/L2/L3/GROUND/SELECT/EXECUTE/DELIVERY 之一。
- 任意稳定 checkpoint 都能导出与实际执行一致的 `ResumePlan`；HUMAN checkpoint 不被普通 `/resume/{checkpoint_id}` 误恢复。
