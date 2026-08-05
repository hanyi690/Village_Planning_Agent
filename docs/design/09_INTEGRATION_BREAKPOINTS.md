# 集成断点与迁移计划

## 1. 当前主要断点

| 断点 | 当前表现 | 目标修复 |
|---|---|---|
| Context 重复构建 | runtime、completion、gis 各自刷新 Bundle/KG | 单一 `PlanningContextProvider` |
| EXPLORE 查询粒度 | 当前已统一多源 evidence retriever，但多数请求仍按维度名 context injection | 按 intervention、evidence gap 和空间问题生成查询计划 |
| PARSE 入口 | `app/agent/parse/` 已是正式 compiler；旧 `agent/select` parse state/fallback 仍被测试和兼容代码引用 | 只保留共享 IntentCompiler，删除旧 SELECT/PARSE 入口 |
| GROUND 隐式回退 | Gazetteer、中心 BBox 和 resolver 兼容路径仍存在 | 统一 SpatialReference → CandidateSite 失败码，禁止静默扩大候选范围 |
| SELECT 候选回退 | 无项目专属候选时仍可能回退到完整候选池 | RETRY_GROUND / EXPLORE / HUMAN，不得把全池当项目候选 |
| 道路重复 | 已解决：staged planner 迁至 `app/modules/spatial_ops/road/`，local `road_planner` fallback 已删除 | 单一 Road Worker / RoadPlannerPort 收敛 |
| 总重试 | 一个异常可能触发空意图或另一个算法 | Validation Router 定向反馈 |
| L1 命名冲突 | 规划 L1/L2/L3 与 KG L1/L2/L3/L4 混用 | KG 改名 BaseFacts/DerivedRelations/IntentGraph/PlannedState |
| 状态复制 | AgentState、PostL3ChainState、ExecuteAgentState 和兼容 GIS 字段并存 | Artifact 引用 + 单一 Context + 唯一 PlannedState |
| EXECUTE 输入 | 当前同时接收 intent、bundle、selection 和 legacy layout 数据 | 只接收 `SiteSelectionDecision + ExecutionPlan` |
| 分区求解缺失 | Wave I 删除 MIP allocator，当前 layout 使用确定性 reclassify | ZoneAllocatorPort + MIPZoneAllocator，失败显式 degraded/unresolved |
| 道路实现重复 | 已解决：staged road planner 迁至 `app/modules/spatial_ops/road/`，`spatial_ops.road_planner` fallback 已删除 | staged planner 为 canonical Road Worker，失败显式 unresolved |
| 契约重复 | `parse_contracts`、`layout_contracts`、`custom_zone_contracts`、`execution_plan_contracts` 有概念重叠 | 先冻结 canonical contracts，再删除 layout/legacy 模型 |
| service/module 混层 | 已解决：`services/modules/gis/road` 已迁移至 `app/modules/spatial_ops/road/`，`services/modules` 目录已删除 | RoadPlannerPort + application service + infrastructure adapter |

## 2. 分阶段迁移

### M0：文档和契约冻结

- 冻结目标图和命名。
- 新增或整理 contracts：Context、Evidence、Intent、Grounding、Placement、Validation。
- 为旧入口加 `[DEPRECATED]` 标记。

### M1：单一 Context

- 实现 `PlanningContextProvider`。
- runtime 只构建一次 Bundle/KG snapshot。
- completion 和 gis 只读取 artifact 引用。
- 添加同 session、同版本断言。

### M2：拆分 EXPLORE 与 PARSE（主要完成）

- EXPLORE 删除候选 BSM 写入。
- PARSE 统一生成 `SpatialReferenceSpec`。
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

## 3. 迁移验收

- 静态 import 检查不允许 `modules → agent/services/api`。
- 每个子图有 contract test、replay test 和 failure routing test。
- 同一输入和 context version 可重放出相同 GroundingResult。
- 任何最终选址都有 `SiteSelectionDecision` 和证据。
- 任意失败都能定位到 L1/L2/L3/GROUND/SELECT/EXECUTE/DELIVERY 之一。
