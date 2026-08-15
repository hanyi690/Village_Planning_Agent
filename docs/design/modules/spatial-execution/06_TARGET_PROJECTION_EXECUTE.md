# TARGET_PROJECTION、GROUND、SELECT 与 EXECUTE

> 状态：`TARGET DESIGN`。第 6 节的旧实现表只用于迁移追溯；当前路径和完成度以
> [`10_IMPLEMENTATION_STATUS.md`](../../10_IMPLEMENTATION_STATUS.md) 与 `docs/architecture/` 为准。

## 1. 四个阶段的边界

```text
shared compiler core
    L1 report + evidence → L1DimensionFragment

TARGET_PROJECTION (deterministic domain boundary)
    PlanningProgram + evidence → IntentCompilationResult + SpatialReferenceSpec

GROUND
    SpatialReferenceSpec + PlaceEvidenceIndex + context → GroundingResult

SELECT
    GroundingResult + requirements → SiteSelectionDecision

EXECUTE
    SiteSelectionDecision + ExecutionPlan → Worker results → ExecutionResult
    ExecutionResult → ParcelChangeSet / PlannedState（精确子产物引用）
```

## 2. TARGET_PROJECTION

Target projection 是已组装规划程序的类型化空间投影，不是空间查询 Agent，也不是自然语言解析器。
共享 compiler core 只服务 L1/L2 报告片段；正式 target projection 只有一个确定性入口：

| Profile | 调用位置 | 输入 | 输出 |
|---|---|---|---|
| `L1_OBSERVATION` | L1 worker 完成报告后 | `content`、独立 `instruction`、证据引用、legacy summary | `L1DimensionFragment` |
| `TARGET_PROJECTION` | L3 Program Gate 之后 | `PlanningProgram`、证据引用 | `IntentCompilationResult + SpatialReferenceSpec` |

L1 调用 compiler core 不表示工作流进入 target projection。target projection 仍是 L3 后、GROUND 前的独立确定性边界。

`L1_OBSERVATION` 负责：

- 从报告中编译事实、约束、问题、机会、分类引用和证据缺口。
- 将每个字段追溯到 `source_report_ref`、来源段落和 evidence reference。
- 保留报告正文（report_body）和 observations 结构化 JSON（`instruction` 列），不重写现有 L1 报告。
- 输出可独立审查的 `L1DimensionFragment`。

`TARGET_PROJECTION` 负责：

- 从 `PlanningProgram` 编译 Zone、Facility、Road、Axis、Project。
- 将自然语言空间关系编译为 `SpatialReferenceSpec`。
- 关联 `EvidenceItem` 和来源段落。
- 校验必填字段、枚举和目标之间的引用。

target projection 遵循以下策略：

1. 确定性抽取和 schema 校验优先。
2. 不调用 LLM，不从报告正文重新解释规划事实。
3. 缺字段或空间证据不足直接进入 GROUND/VALIDATE gate，由 HUMAN 处理。
4. 投影结果写入不可变 `target_projection` artifact，并以 parent digest 绑定 `PlanningProgram`。

实现约束：claim 的 `location_hints` 在 claim adapter 进入 `PlanningIntervention.spatial_requirements.location`
后，才由 mapper 编译为 `place_name` 闭集引用；不把位置文本丢失为旧的单值字段，也不在此阶段生成坐标。
SELECT 必须透传每个 target 的 `expected_output_kind`（尤其是 `point`），EXECUTE 才能把已选项目送入
定位点 worker，而不是错误地按 parcel footprint 处理。

对于 L1 输入，legacy `DimensionReport.summary` 仅为最低优先级兼容材料。字段冲突优先级为：
明确证据与 provenance → 报告正文 → `instruction` 中可验证的结构信息 → legacy summary。

它不负责：

- 查询 KG 候选。
- 读取完整几何。
- 选择地块。
- 生成坐标。

## 3. GROUND 子图

内部节点：

```text
normalize_spec
  → resolve_reference
  → query_semantic_relations
  → refine_geometry
  → assemble_grounding_evidence
  → grounding_gate
```

契约：

```python
class GroundedCandidate(BaseModel):
    bsm: str
    source_entities: list[str]
    geometry_ref: str | None
    metrics: dict[str, float] = {}
    constraints: list[str] = []
    evidence_ids: list[str] = []


class GroundingResult(BaseModel):
    target_id: str
    candidates: list[GroundedCandidate]
    status: Literal['resolved', 'ambiguous', 'unresolved']
    confidence: float
    query_trace: list[dict]
    unresolved_reason: str | None = None
```

## 4. SELECT 子图

SELECT 采用“规则先行、模型辅助、规则复核”：

1. 移除禁止建设、灾害、基本农田和不满足最小面积的候选。
2. 计算规模、适宜性、聚落距离、道路可达性和服务覆盖。
3. 对 Top-K 候选执行可选 Selection Agent 排序。
4. 进行目标间冲突消解和资源分配。
5. 产生 `SiteSelectionDecision`。

Selection Agent 的输入是规范化候选特征，输出只能是候选排序、理由和不确定性，不能直接输出新 BSM 或新坐标。

```python
class SiteSelectionDecision(ContractMeta):
    selected_combination: list[str]
    full_ranking: list[RankedCandidate]
    eliminated: list[EliminatedCandidate]
    decision_factors: dict
    review_status: str
    provenance: Provenance | None
```

## 5. EXECUTE 子图（目标与当前边界）

EXECUTE 只接受 `SiteSelectionDecision` 和 `ExecutionPlan`。按目标类型分派单一正式 Worker：

| Worker | 输入 | 输出 |
|---|---|---|
| Zone Worker | 分区目标、分配指标 | function/land-use layers |
| Facility Worker | 设施位置决定、容量 | planned facility layer |
| Road Worker | 道路目标、道路网络和约束 | planned road layer |
| Axis Worker | 轴线目标和锚点 | planned axis layer |
| Project Worker | 项目选址决定 | planned project layer |

Worker 不得重新执行 target projection，也不得将第一个可用候选当作最终选址。

上述是目标输入边界。当前实现已经把规划程序、目标投影和交付快照收敛到 typed artifact，但 EXECUTE 的完整 worker contract、统一 `ExecutionResult` 和真实链路仍是 `PARTIAL`；具体事实以 `10_IMPLEMENTATION_STATUS.md` 为准。迁移期的旧 `ExecuteAgentState`、集中式执行节点和 reports-derived 输入不得继续扩展。

目标重构应形成：

```text
prepare_inputs → land_design / allocation → geometry_materialize
  → road_axis_layout → planned_state_builder → execution_review → write_l4
```

其中 Zone Worker 应由 MIP/约束求解器处理规划分区，不得把现状地类代码直接映射为规划分区；Road Worker 应
以 staged road planner 为正式路径，任何不可用情况都必须显式返回 degraded/unresolved。EXECUTE 内部的
`execution_review` 只做执行完整性和 Worker 间冲突检查，最终规则、拓扑、面积和连通性校验仍由外层 VALIDATE 负责。

## 6. 旧实现的迁移对应

| 旧实现 | 目标职责 |
|---|---|
| `agent/select/parse_agent.py` | 已删除；L1/L2 共享 compiler 位于 `app/modules/parsing/compiler/`，target projection 位于 `app/domain/program/target_projection/` |
| `modules/spatial_ops/grounding.py` | Grounding domain service |
| `modules/spatial_ops/bundle_binder.py` | 删除；改为 context-aware reference resolution |
| `agent/gis/execute/agent.py` | 已迁移；当前实现集中在 `app/domain/materialization/execute_agent.py` |
| `tools/gis/_generation/*` | 已删除；正式链路由 `agent/execute` 与 `modules/spatial_ops` 提供 |
| `services/modules/gis/road/*` 与 `spatial_ops/road_planner.py` | 历史重复实现；staged planner 是唯一正式 Road Worker，旧入口已删除或待清理以 `10_IMPLEMENTATION_STATUS.md` 为准 |
