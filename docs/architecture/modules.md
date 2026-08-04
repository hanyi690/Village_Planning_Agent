# 模块实现映射与依赖规则

## 1. 目标依赖方向

```text
schema
  ↑
data repositories
  ↑
spatial query services
  ↑
kg semantic services
  ↑
planning domain services
  ↑
workflow subgraphs / API adapters
```

箭头表示“上层依赖下层”。`tools` 是适配器，不是独立业务层。

## 2. Schema

位置：`backend/app/modules/schema/`

负责 contracts、编码、层注册、规则描述和 provenance。目标新增或整理：

- `PlanningContext`
- `EvidenceBundle`
- `L1Snapshot`
- `L2Strategy`
- `L3PlanningIntent`
- `GroundingResult`
- `PlacementDecision`
- `ValidationReport`

## 3. Data

位置：`backend/app/modules/data/`、`services/session_bundle.py`。

负责原始资料、GeoJSON/GeoTIFF、外部锚点、Provider、版本和缓存。业务节点不能在读取 Bundle 时隐式刷新外部数据。

## 4. Spatial Query

位置：`backend/app/modules/spatial_ops/`。

负责几何、空间索引、距离、拓扑、约束和候选精化。它消费 `SpatialReferenceSpec` 或实体引用，不消费自然语言长文本。

## 5. KG

位置：`backend/app/modules/kg/`。

维护 `BaseFacts`、`DerivedRelations`、`IntentGraph`、`PlannedState`。KG 提供 semantic query port；完整几何仍由 Spatial Query Service 计算。

## 6. Planning domain

目标位置：`backend/app/modules/planning/`。

| 服务 | 职责 |
|---|---|
| IntentCompiler | L3 文本和证据 → Target、Constraint、SpatialReferenceSpec |
| GroundingService | 语义实体和空间描述 → GroundingResult |
| SelectionService | 候选过滤、评分、分配 → PlacementDecision |
| ExecutionService | PlacementDecision → PlannedState |
| ReconciliationService | IntentGraph ↔ PlannedState |

## 7. Workflow / Agent

位置：`backend/app/agent/`。

`agent` 只负责 StateGraph、Send 并行、Gate、人工中断、反馈路由和 Agent tool loop。领域算法不能因为位于 `agent` 目录就绕过 contracts。

## 8. 当前重复实现

迁移前需要处理：

- ~~`tools/gis/parse.py` 与 `agent/gis/parse/agent.py` 的双重解析。~~（2026-08 已迁移：`tools/gis/parse.py` 删除，PARSE 归 `agent/select/parse_agent.py`）
- `modules/spatial_ops/grounding.py`、Explore 节点和 Bundle Binder 的多轨空间接地。
- staged road planner 与 `spatial_ops/road_planner.py` 的重复道路实现。
- `AgentState`、`GISPipelineState`、`ParseAgentState`、`ExecuteAgentState` 的重复状态字段。

## 9. 边界检查

CI 应阻止以下依赖：

- `modules → agent`
- `modules → services`
- `tools → agent`（除兼容转发模块）
- `planning domain → LangGraph / SSE / ReportStore 实现`
- 同一目标类型存在两个正式执行器
