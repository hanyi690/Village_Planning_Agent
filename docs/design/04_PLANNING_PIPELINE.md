# L1/L2/L3 与空间决策闭环

## 1. 总体结构

```text
BOOTSTRAP
  → L1 OBSERVE
  → L1 Evidence Gate
  → L2 STRATEGIZE
  → L2 Consistency Gate
  → L3 PLAN / IntentCompiler
  → L3 Intent Gate
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
  → parallel analysis workers
  → EvidenceBundle merge
  → fact / constraint / problem extraction
  → cross-dimension consistency check
  → L1Snapshot
```

`L1Snapshot` 至少包含：

- `facts`
- `constraints`
- `problems`
- `opportunities`
- `evidence_gaps`
- `dimension_provenance`

缺少关键事实时，Gate 生成 `ExplorationRequest`，由 EXPLORE 返回 `EvidenceBundle` 后只重跑受影响维度。

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

输入：`L1Snapshot + L2Strategy + EvidenceBundle`。

内部流程：

```text
L3 dimension workers
  → target / constraint draft
  → cross-dimension merge
  → IntentCompiler
  → SpatialReferenceSpec validation
  → IntentGraph write
  → L3 Intent Gate
```

L3 的权威输出是 `L3PlanningIntent`，Markdown 只是渲染结果。

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

输出 `PlacementDecision`，必须包含选择理由、淘汰理由和证据。

## 7. EXECUTE

按目标类型分派 Worker：

- Zone：MIP / zoning allocator
- Facility：facility placer
- Road：唯一正式 road planner
- Axis：axis builder
- Project：project placement worker

Worker 只消费 `PlacementDecision` 和 `ExecutionPlan`。不可在 Worker 内重新解析文本或偷偷选另一个候选。

## 8. 分层门控

| Gate | 检查 | 失败去向 |
|---|---|---|
| L1 Evidence Gate | 事实、来源、维度完整性 | EXPLORE 或 L1 |
| L2 Consistency Gate | 策略与事实、约束一致 | L1、EXPLORE 或 L2 |
| L3 Intent Gate | Target、约束和空间引用完整 | EXPLORE、L3 或人工 |
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
