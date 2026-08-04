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
| WorkflowGraph | `agent/graph.py`, `routing.py` | 当前仍是 6 节点总图 |
| ContextProvider | `services/session_bundle.py`, `session_kg.py` | 需合并 Bundle/KG 生命周期 |
| L1/L2/L3 | `agent/analysis/`, `completion/` | 保留维度并行，改为层内子图 |
| ExploreGraph | `agent/explore/` | 删除候选地块写入职责 |
| IntentCompiler | `agent/gis/parse/` | 合并旧 `tools/gis/parse.py` |
| GroundGraph | `modules/spatial_ops/grounding.py` | 拆出语义解析和几何精化 |
| SelectGraph | `agent/gis/execute/agent.py` | 从 Execute 中提取选址决策 |
| ExecuteGraph | `agent/gis/execute/`, `tools/gis/_generation/` | Worker 化并合并道路实现 |
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

工作流 State 保存引用、Gate 和反馈，不保存上述对象的完整内容。
