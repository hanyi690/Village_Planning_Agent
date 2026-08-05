# 工作流图：当前实现与目标子图

## 1. 当前主图

当前入口为 `backend/app/agent/bootstrap/graph.py:create_unified_planning_graph`，包含 conversation、execute_tools、analyze_dimension、layer_completion_check、explore 和 gis_agent 六类节点。`gis_agent` 内部继续调用 `layout_pipeline`，因此顶层图看似简单，实际把 PARSE、KG、EXECUTE、VALIDATE、EXPORT、RENDER 聚合在一个节点中。

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

当前新 `retrieve_evidence()` 调用发生在共享维度 worker 内、报告生成之前；L3 完成后仍存在旧的
`explore -> gis_agent` 桥接。因此当前代码同时存在“按维度证据注入”和“旧后置桥接”两种语义，
后者必须在目标主图接入时删除。

当前 L1 的 12 个维度已经通过 `Send` 并行运行。每个 worker 生成完整报告后，还会生成并保存
`DimensionReport.summary`；但该字段目前只是维度 schema 外壳、字符数、正文前 200 字预览以及空的
`key_points` / `metrics`，不是语义摘要或权威事实。

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
    L3Gate -->|pass| Parse["parse_graph"]
    Parse --> ParseGate{"parse_gate"}
    ParseGate -->|needs repair/revise| Parse
    ParseGate -->|missing planning content| L3
    ParseGate -->|pass| Ground["ground_graph"]
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

### 2.1 L1 子图（并行报告与并行编译）

```mermaid
flowchart TD
    Dispatch["L1 dimension dispatch"] --> W1["12 × report worker (parallel)"]
    W1 --> Report["AnalysisReport<br/>content + instruction + provenance"]
    W1 --> Compile["12 × fragment compiler (parallel)<br/>profile=L1_OBSERVATION"]
    Compile --> Fragment["L1DimensionFragment"]
    Fragment --> Aggregate["l1_aggregate<br/>deterministic join"]
    Aggregate --> Snapshot["L1Snapshot"]
    Snapshot --> Gate{"L1 Evidence Gate"}
```

- 保留现有 12 维报告及 `【INSTRUCTION】`，继续服务 UI、SSE、KG enrichment 和人工审查。
- fragment compiler 是共享 IntentCompiler 的 L1 profile，不是 12 个新的顶层图节点。
- 每个 worker 完成后立即编译自身 fragment；不同维度可继续并行。
- `l1_aggregate` 只合并 fragment、检查重复/冲突/证据缺口、建立 provenance 并构造 Gate 输入；
  不调用 LLM，也不重新解析 12 份报告。
- `DimensionReport.summary` 只作兼容性预览，不得直接汇聚为 `L1Snapshot`。

### 2.2 PARSE 子图（独立顶层阶段）

PARSE 是**独立的顶层阶段**，形式上不属于 L1 或 select_graph。L1 只是复用同一个 compiler core
生成维度 fragment，不表示工作流提前进入顶层 PARSE。顶层 PARSE 输入为 L3 `PlanningProgram`，
输出为 `IntentCompilationResult` + `SpatialReferenceSpec`。

共享 compiler core 提供两个 profile：

- **L1_OBSERVATION**：输入 `AnalysisReport.content`、独立 `instruction`、证据引用和 legacy summary，
  输出 `L1DimensionFragment`。
- **L3_PLANNING**：输入 `PlanningProgram`，输出 `IntentCompilationResult` + `SpatialReferenceSpec`。

三种模式：

- **COMPILE**：首次编译 L3 PlanningProgram → IntentCompilationResult + SpatialReferenceSpec。
- **REPAIR**：基于已有编译结果 + 用户局部纠正（`ParseRevisionRequest.user_revisions` / `patch_ids`）做定向修复。
- **REVISE**：大范围重写（低置信度 / 结构性变更），产出新 revision。

混合设计（hybrid repair）：

```mermaid
flowchart TD
    In["PlanningProgram (L3)"] --> Det["确定性抽取 (deterministic)"]
    Det --> Amb{"歧义 / 低置信度?"}
    Amb -->|否| Merge["确定性合并 + 复验"]
    Amb -->|是| LLM["LLM 仅产出结构化 CompilationPatch"]
    LLM --> Merge
    Merge --> Check{"复验结果"}
    Check -->|缺失规划内容| Back["回传 L3"]
    Check -->|低置信度 / 大范围改写| Review["人工审查"]
    Check -->|通过| Out["IntentCompilationResult + SpatialReferenceSpec"]
```

设计要点：

- 确定性抽取优先；LLM 只产出结构化 `CompilationPatch`（actor = "llm"），不直接改写 artifact。
- 补丁由确定性合并器合并，随后重新校验（`ParseTrace.steps` 记录确定性步骤日志）。
- 缺失的规划内容路由回 L3；低置信度 / 大范围改写路由到人工审查（`CompilationStatus.NEEDS_REVIEW`）。
- `CompilationPatch` 只保存 `rationale`（简要判断依据），不保存模型内部推理链。
- 诊断统一收敛为 `ParseDiagnostic`（severity/code/message），兼容字段 `compilation_errors` 保留供旧消费者。

## 3. 子图契约

| 子图 | 输入 | 输出 |
|---|---|---|
| `l1_graph` | Context + EvidenceBundle | `L1Snapshot` |
| `l2_graph` | `L1Snapshot` | `L2Strategy` |
| `l3_graph` | L1 + L2 + evidence | `PlanningProgram` |
| `parse_graph` | `PlanningProgram` | `IntentCompilationResult` + `SpatialReferenceSpec` |
| `explore_graph` | `ExplorationRequest` | `EvidenceBundle` |
| `ground_graph` | `SpatialReferenceSpec` | `GroundingResult` |
| `select_graph` | `GroundingResult` + requirements | `SiteSelectionDecision` |
| `execute_graph` | `SiteSelectionDecision` | `PlannedState` |
| `validate_graph` | artifacts + context | `ValidationReport` |

## 4. Agent 形态

- EXPLORE：工具调用 Agent。
- L1/L2/L3：专业分析 Agent 的层内 worker。
- GROUND：确定性子图，歧义时才请求 Agent/人工。
- SELECT：规则过滤 + 可选 Top-K Selection Agent。
- EXECUTE：确定性 Worker，不使用自由规划 Agent。
- VALIDATE：确定性 Evaluator。

EXPLORE 是 L1/L2/L3 共用的 session-wide evidence service。维度 worker 可以请求空间认知，
但不直接调用 KG；请求由 EXPLORE 按阶段、维度和 query purpose 从 KG、Bundle、报告、
`【INSTRUCTION】`、typed artifacts、已有证据和外部来源中渐进式检索，返回 `EvidenceBundle`。
GROUND 才将 PARSE 的 `SpatialReferenceSpec` 接到候选实体和几何；EXPLORE 不生成候选集。

目标图允许 Bootstrap 在 L1 前准备 evidence index，但不设置一个声称“证据已经充分”的固定
EXPLORE 阶段。证据充分性只能由各阶段 Gate 判断；Gate 必须能根据结构化 EvidenceGap 再次调用
EXPLORE。L1 并行 worker 不能假设同层其他报告已经可检索。

在顶层 PARSE 完成前，真实主图测试止于报告层和独立 compiler/aggregate 组件。只有
`L2Strategy`、`PlanningProgram` 成为阶段权威产物且 `L3_PLANNING` profile 接入 Parse Gate 后，
才允许把测试称为 L1→L2→L3→PARSE 端到端验证。

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
