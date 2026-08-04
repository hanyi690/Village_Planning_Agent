# 工作流图：当前实现与目标子图

## 1. 当前主图

当前入口为 `backend/app/agent/graph.py:create_unified_planning_graph`，包含 conversation、execute_tools、analyze_dimension、layer_completion_check、explore 和 gis_agent 六类节点。`gis_agent` 内部继续调用 `layout_pipeline`，因此顶层图看似简单，实际把 PARSE、KG、EXECUTE、VALIDATE、EXPORT、RENDER 聚合在一个节点中。

当前主要路径：

```text
conversation
  → analyze_dimension (Send 并行)
  → layer_completion_check
  → explore
  → gis_agent
  → END
```

当前路径仅适合作为迁移兼容层，不是目标边界。

## 2. 目标主图

```mermaid
flowchart TD
    Bootstrap["bootstrap"] --> L1["l1_graph"]
    L1 --> L1Gate{"l1_gate"}
    L1Gate -->|evidence request| Explore["explore_graph"]
    Explore --> L1Gate
    L1Gate -->|pass| L2["l2_graph"]
    L2 --> L2Gate{"l2_gate"}
    L2Gate -->|evidence request| Explore
    L2Gate -->|pass| L3["l3_graph"]
    L3 --> L3Gate{"l3_gate"}
    L3Gate -->|evidence request| Explore
    L3Gate -->|pass| Ground["ground_graph"]
    Ground --> GroundGate{"ground_gate"}
    GroundGate -->|retry evidence| Explore
    GroundGate -->|pass| Select["select_graph"]
    Select --> SelectGate{"select_gate"}
    SelectGate -->|retry candidates| Ground
    SelectGate -->|pass| Execute["execute_graph"]
    Execute --> Validate["validate_graph"]
    Validate --> Router{"validation_router"}
    Router -->|intent| L3
    Router -->|grounding| Ground
    Router -->|selection| Select
    Router -->|execution| Execute
    Router -->|pass| Delivery["delivery_gate"]
```

## 3. 子图契约

| 子图 | 输入 | 输出 |
|---|---|---|
| `l1_graph` | Context + EvidenceBundle | `L1Snapshot` |
| `l2_graph` | `L1Snapshot` | `L2Strategy` |
| `l3_graph` | L1 + L2 + evidence | `L3PlanningIntent` |
| `explore_graph` | `ExplorationRequest` | `EvidenceBundle` |
| `ground_graph` | `SpatialReferenceSpec` | `GroundingResult` |
| `select_graph` | `GroundingResult` + requirements | `PlacementDecision` |
| `execute_graph` | `PlacementDecision` | `PlannedState` |
| `validate_graph` | artifacts + context | `ValidationReport` |

## 4. Agent 形态

- EXPLORE：工具调用 Agent。
- L1/L2/L3：专业分析 Agent 的层内 worker。
- GROUND：确定性子图，歧义时才请求 Agent/人工。
- SELECT：规则过滤 + 可选 Top-K Selection Agent。
- EXECUTE：确定性 Worker，不使用自由规划 Agent。
- VALIDATE：确定性 Evaluator。

## 5. 状态规则

LangGraph State 只保存：`context_ref`、`active_stage`、`active_gate`、`artifact_refs`、`pending_requests`、`validation_issues` 和 `human_review`。完整报告、KG、地块和图层通过 artifact store 读取。

## 6. 相关文件

> 注：本结构为 2026-08 迁移后的目录归属。L1/L2/L3 子图尚未独立（L2/L3 暂借 l1_observe 实现），GROUND/SELECT/VALIDATE/RECONCILE 核心算法仍在 app/modules/spatial_ops + app/modules/kg，后续逐模块完善时再深入。

```
backend/app/agent/
├── bootstrap/          # 主图工厂 + 阶段机 (graph.py, phase_machine.py, gis_agent_entry.py)
├── conversation_router/ # 中央路由 (node.py + edges.py)
├── l1_observe/         # L1 现状分析 (analysis_node.py + pipeline.py + formatters.py)
├── l2_strategize/      # L2 策略推导 (占位, 暂借 l1_observe)
├── l3_plan/            # L3 详细规划 (占位, 暂借 l1_observe)
├── explore/            # EXPLORE 认知引擎 (横向能力)
├── ground/             # GROUND 空间接地 (format_bound_intent.py)
├── select/             # SELECT/PARSE (parse_agent.py, parse_state.py, parse_fallback.py, prompts.py)
├── execute/            # EXECUTE (layout_pipeline.py, execute_agent.py, road_generator.py, vocab_*)
├── validate/           # VALIDATE (占位)
├── plan_state/         # PLAN_STATE (state.py + completion_node.py)
├── reconcile/          # RECONCILE (占位)
├── deliver/            # DELIVER (gis_pipeline_state.py)
└── tools/              # 主图工具调度 (execute_node.py)
```
