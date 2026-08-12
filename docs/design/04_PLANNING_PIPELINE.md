# L1/L2/L3 与空间决策闭环

## 1. 总体结构

```text
BOOTSTRAP
  → L1 OBSERVE
  → L1 Evidence Gate
  → L2 STRATEGIZE
  → L2 Consistency Gate
  → L3 PLAN
  → L3 Program Gate
  → TARGET_PROJECTION (deterministic)
  → Target Projection Gate
  → GROUND
  → SELECT
  → EXECUTE
  → VALIDATE
  → RECONCILE
  → DELIVERY
```

EXPLORE 作为横向服务被 Gate 调用，不作为固定的 L3 后桥接阶段。

## 2. L1 OBSERVE

目标：形成可引用、可核验的现状快照。

内部流程：

```text
L1 dimension dispatch
  → 12 × parallel analysis workers
  → per-worker AnalysisReport(content + instruction + provenance)
  → per-worker L1_OBSERVATION compilation (parallel)
  → 12 × L1DimensionFragment
  → deterministic l1_aggregate
  → L1Snapshot
```

`AnalysisReport` 保留当前报告正文和 `【INSTRUCTION】` 的表达能力，继续供 UI、SSE、KG enrichment、
L2/L3 共享阅读和人工审查。ReportStore 落盘时将其拆为 `content`、`instruction` 和 provenance；
报告不是要被结构化产物替代的临时文本。

`L1DimensionFragment` 是机器消费的维度级权威产物，至少包含：

- `facts`、`constraints`、`issues`、`opportunities`
- `evidence_gaps`
- `classification_refs`
- `source_report_ref`
- `compilation_trace`

每个维度报告完成后立即调用共享 compiler core 的 `L1_OBSERVATION` profile，不等待 12 份报告全部
完成后再集中理解。它不是新增 12 个顶层图节点。唯一的 `l1_aggregate` 只做确定性合并、跨维冲突
检查、证据缺口归并和 provenance 建立，不调用 LLM、不重复解析报告。

`L1Snapshot` 至少包含：

- `facts`
- `constraints`
- `problems`
- `opportunities`
- `evidence_gaps`
- `dimension_provenance`

缺少关键事实或空间认知时，Gate 或维度 worker 生成带 `stage`、`dimension_key`、`query_purpose`、
`context_refs` 和 `evidence_gap` 的 `ExplorationRequest`。EXPLORE 从整个 session 检索并返回
`EvidenceBundle` / `SpatialCognitionEvidence`，之后只重跑受影响维度。

L1/L2/L3 的 prompt 可以使用空间认知，但空间认知的来源边界统一为 EXPLORE：维度 worker 不直接
调用 KG 查询函数。KG、VillageBundle、报告正文、`【INSTRUCTION】`、typed artifacts、既有证据和
必要外部来源由 EXPLORE 按查询目的裁剪，避免把整个 session 原文一次性注入 prompt。

L1 前允许执行 evidence index preparation，但它只准备 Bundle、KG 和 session artifact 索引。
每个维度仍需根据自己的分析问题发起 `context_injection` 请求；L1 Evidence Gate 再根据
`EvidenceGap` 发起 `gap_resolution` 请求。固定维度名查询不构成 Gate 通过依据。

## 3. L2 STRATEGIZE

输入：批准的 `L1Snapshot`。

输出：

- 规划目标
- 村庄定位
- 空间结构策略
- 设施、交通、生态和用地策略
- 策略约束和冲突
- `L2Strategy`

L2 不直接创建候选地块，也不把策略文本写入 IntentGraph。策略 Gate 失败时，反馈到 L1、EXPLORE 或 L2 内部，不触发整个主图重跑。

## 4. L3 PLAN

输入：`L1Snapshot + L2Strategy + EvidenceBundle`，其中空间认知必须带来源和 context/KG 版本。

L3 的权威输出是 `PlanningProgram`，Markdown 报告仍是供人阅读和审查的视图。

内部流程：

```text
L3 dimension workers
  → intervention / requirement draft
  → cross-dimension merge
  → PlanningProgram
  → L3 Program Gate
```

L3 Gate 通过后，独立顶层 TARGET_PROJECTION 对 `PlanningProgram` 做确定性空间投影：

```text
PlanningProgram
  → deterministic target projection
  → IntentCompilationResult + SpatialReferenceSpec
  → Target Projection Gate
```

缺少规划内容或空间证据时进入 GROUND/VALIDATE 的人工审查路径；不再通过另一次模型调用修复规划事实。

TARGET_PROJECTION 不读取 Markdown、`【INSTRUCTION】` 或原始 GeoJSON；它只加载
`artifact_refs.planning_program`，并输出可供 GROUND 消费的 typed artifact。

## 5. GROUND

输入：`SpatialReferenceSpec + PlanningContext + IntentGraph`。

内部流程：

```text
normalize spec
  → resolve semantic reference
  → query KG relations
  → spatial geometry refinement
  → candidate evidence assembly
  → Grounding Gate
```

输出 `GroundingResult`。GROUND 不做候选评分和最终选址。

## 6. SELECT

输入：`GroundingResult + L2Strategy + target requirements`。

内部流程：

```text
hard constraints
  → area / capacity / suitability filter
  → multi-factor scoring
  → optional model ranking on Top-K
  → conflict-aware allocation
  → Selection Gate
```

输出 `SiteSelectionDecision`，必须包含完整排名、选择理由、淘汰理由和证据。

## 7. EXECUTE

目标结构按目标类型分派 Worker：

- Zone：MIP / zoning allocator
- Facility：facility placer
- Road：唯一正式 road planner
- Axis：axis builder
- Project：project placement worker

Worker 只消费 `SiteSelectionDecision` 和 `ExecutionPlan`。不可在 Worker 内重新解析文本或偷偷选另一个候选。

当前实现尚未完全达到该目标。`backend/app/agent/execute/execute_agent.py` 仍将路由、布局、项目、设施、
轴线、道路、局部校验和 L4 写入集中在同一子图中；当前 `execute_layout` 使用确定性 zone reclassify，
不调用 MIP。`ExecutionPlan` 尚未成为 post-L3 EXECUTE 的唯一输入，正式 Zone Worker 和 Worker 结果合并器
仍待实现。道路的 staged planner 与 `spatial_ops.road_planner` fallback 也尚未收敛为唯一入口。

因此“Zone = MIP / zoning allocator”和“Road = 唯一正式 road planner”是目标设计，不应标记为 CURRENT。

## 8. 分层门控

| Gate | 检查 | 失败去向 |
|---|---|---|
| L1 Evidence Gate | 事实、来源、维度完整性 | EXPLORE 或 L1 |
| L2 Consistency Gate | 策略与事实、约束一致 | L1、EXPLORE 或 L2 |
| L3 Program Gate | 干预、需求、依赖和来源完整 | EXPLORE、L3 或人工 |
| Target Projection Gate | typed targets、空间引用和诊断完整 | L3、GROUND 或人工 |
| Grounding Gate | 实体、候选、几何证据 | EXPLORE、L3 或人工 |
| Selection Gate | 可实施、无冲突、满足指标 | GROUND、L3 或 SELECT |
| Validation Gate | 规则、几何、拓扑、图层 | EXECUTE、SELECT、GROUND 或 L3 |
| Delivery Gate | 输出规范、完整性、溯源 | VALIDATE |

## 9. 运行状态

主图 State 只保存：

```text
active_stage
active_gate
context_ref
artifact_refs
pending_requests
validation_issues
human_review
```

维度报告、GeoJSON、KG Turtle 和候选特征都通过 artifact 引用读取。
