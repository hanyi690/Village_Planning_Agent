# 集成断点与迁移计划

## 1. 当前主要断点

| 断点 | 当前表现 | 目标修复 |
|---|---|---|
| Context 重复构建 | runtime、completion、gis 各自刷新 Bundle/KG | 单一 `PlanningContextProvider` |
| EXPLORE 越权 | 直接 grounding 并写候选 BSM | 只返回 EvidenceBundle |
| PARSE 双轨 | `parse.agent`、`tools/gis/parse`、Binder 共同解释文本 | 唯一 IntentCompiler |
| GROUND 隐式回退 | Gazetteer、中心 BBox、KG callback 混合 | 独立 Grounding 子图和失败码 |
| SELECT 缺失 | EXECUTE 按候选顺序选择第一个可用地块 | 独立 Selection 子图 |
| 道路重复 | staged planner 与 local planner 并存 | 单一 Road Worker |
| 总重试 | 一个异常可能触发空意图或另一个算法 | Validation Router 定向反馈 |
| L1 命名冲突 | 规划 L1/L2/L3 与 KG L1/L2/L3/L4 混用 | KG 改名 BaseFacts/DerivedRelations/IntentGraph/PlannedState |
| 状态复制 | AgentState、GIS State、Parse State、Execute State 字段重叠 | Artifact 引用 + 单一 Context |

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

### M2：拆分 EXPLORE 与 PARSE

- EXPLORE 删除候选 BSM 写入。
- PARSE 统一生成 `SpatialReferenceSpec`。
- 删除 Binder 作为业务中间层的职责。

### M3：建立 GROUND / SELECT 子图

- 先迁移 GroundingResult 和 CandidateSet。
- 再迁移 hard filter、评分和 PlacementDecision。
- 将低置信度模型排序限制在 Top-K 候选内。

### M4：拆分 L1/L2/L3 子图

- 每层内部保留并行维度分析。
- 层级完成改为层内 Gate，不再由总路由器解释所有 phase 和 revision。
- 各层只提交一个版本化 snapshot。

### M5：执行、对账和交付

- 合并道路实现。
- Execute 只消费 PlacementDecision。
- 增加 Intent ↔ PlannedState Reconcile。
- Delivery Gate 只交付通过的成果包。

## 3. 迁移验收

- 静态 import 检查不允许 `modules → agent/services/api`。
- 每个子图有 contract test、replay test 和 failure routing test。
- 同一输入和 context version 可重放出相同 GroundingResult。
- 任何最终选址都有 PlacementDecision 和证据。
- 任意失败都能定位到 L1/L2/L3/GROUND/SELECT/EXECUTE/DELIVERY 之一。
