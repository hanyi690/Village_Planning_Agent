# 项目结构与目标实现映射

## 1. 目录边界

```text
backend/app/
├── api/                         # HTTP / SSE adapter
├── agent/                       # workflow subgraphs and gates
│   ├── layers/                  # target: l1/l2/l3 subgraphs
│   ├── explore/                 # evidence exploration agent
│   ├── spatial/                 # target: ground/select subgraphs
│   └── delivery/                # validation and delivery routing
├── modules/
│   ├── schema/                  # contracts and encodings
│   ├── data/                    # repositories and providers
│   ├── spatial_ops/             # geometry and spatial query services
│   ├── kg/                      # semantic query and snapshots
│   ├── planning/                # target domain services
│   └── rag/                     # retrieval adapter
├── services/                    # application adapters and persistence
└── tools/                       # external tool adapters only
```

## 2. 目标运行结构

```text
API
  → WorkflowGraph
    → PlanningContextProvider
    → L1Graph → L2Graph → L3Graph
    → GroundGraph → SelectGraph → ExecuteGraph
    → Validate/Reconcile → Delivery
```

EXPLORE 可由任一 Gate 通过 `ExplorationRequest` 调用，返回 `EvidenceBundle`，不直接连接 Execute。

## 3. 当前代码映射

| 目标组件 | 当前主要入口 | 迁移说明 |
|---|---|---|
| WorkflowGraph | `agent/bootstrap/graph.py`, `conversation_router/edges.py` | 19 个显式节点；L1–L3 编排和 post-L3 七阶段在同一根图 |
| ContextProvider | `modules/context/planning_context.py`, `services/session_kg.py` | 当前为进程内缓存；跨重启持久化仍待完成 |
| L1/L2/L3 | `agent/l1_observe/`, `l2_strategize/`, `l3_plan/`, `plan_state/completion_node.py` | 三层均由根图 worker 调度；层内职责仍持续拆分 |
| ExploreGraph | `agent/explore/` | 删除候选地块写入职责 |
| IntentCompiler | `modules/parsing/compiler/`, `agent/parse/` | 顶层 PARSE 在 post-L3 主图中运行 |
| GroundGraph | `modules/spatial_ops/grounding.py` | 拆出语义解析和几何精化 |
| SelectGraph | `agent/select/`, `agent/execute/execute_agent.py` | 从 Execute 中提取选址决策 |
| ExecuteGraph | `agent/execute/`, `tools/gis/_generation/` | Worker 化并合并道路实现 |
| Reconcile | `agent/explore/verification.py` | 扩展为 Intent ↔ PlannedState 对账 |

## 4. 一次会话的 artifact 流

```text
PlanningContext
  → L1Snapshot
  → L2Strategy
  → L3PlanningIntent
  → GroundingResult
  → PlacementDecision
  → PlannedState
  → ValidationReport
  → DeliveryPackage
```

目标是仅保存引用、Gate 和反馈；当前 `AgentState` 还保留 legacy 完整对象和图层字段，不能将其描述为纯引用状态。
