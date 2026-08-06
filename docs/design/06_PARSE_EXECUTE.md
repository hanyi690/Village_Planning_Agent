# PARSE、GROUND、SELECT 与 EXECUTE

## 1. 四个阶段的边界

```text
shared compiler core
    L1 report + evidence → L1DimensionFragment

PARSE / IntentCompiler (top-level)
    PlanningProgram + evidence → IntentCompilationResult + SpatialReferenceSpec

GROUND
    SpatialReferenceSpec + PlaceEvidenceIndex + context → GroundingResult

SELECT
    GroundingResult + requirements → SiteSelectionDecision

EXECUTE
    SiteSelectionDecision + ExecutionPlan → Worker results → ParcelChangeSet → PlannedState
```

## 2. PARSE / IntentCompiler

IntentCompiler 是共享的类型化编译能力，不是空间查询 Agent。共享 core 提供两个明确 profile：

| Profile | 调用位置 | 输入 | 输出 |
|---|---|---|---|
| `L1_OBSERVATION` | L1 worker 完成报告后 | `content`、独立 `instruction`、证据引用、legacy summary | `L1DimensionFragment` |
| `L3_PLANNING` | L3 Program Gate 之后的顶层 PARSE | `PlanningProgram`、证据引用 | `IntentCompilationResult + SpatialReferenceSpec` |

L1 调用 compiler core 不表示工作流进入顶层 PARSE。顶层 PARSE 仍是 L3 后、GROUND 前的独立阶段。

`L1_OBSERVATION` 负责：

- 从报告中编译事实、约束、问题、机会、分类引用和证据缺口。
- 将每个字段追溯到 `source_report_ref`、来源段落和 evidence reference。
- 保留报告正文和 `【INSTRUCTION】`，不重写现有 L1 报告。
- 输出可独立审查的 `L1DimensionFragment`。

`L3_PLANNING` 负责：

- 从 `PlanningProgram` 编译 Zone、Facility、Road、Axis、Project。
- 将自然语言空间关系编译为 `SpatialReferenceSpec`。
- 关联 `EvidenceItem` 和来源段落。
- 校验必填字段、枚举和目标之间的引用。

两个 profile 共享以下编译策略：

1. 确定性抽取和 schema 校验优先。
2. 只有歧义、缺字段或低置信度时才调用 LLM。
3. LLM 只能返回结构化 `CompilationPatch`，不能直接覆盖 artifact。
4. patch 经确定性合并后重新校验并写入 `compilation_trace`。
5. REPAIR 用于局部纠错；REVISE 用于结构性修订或产生新 revision。

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

Worker 不得重新调用 PARSE，也不得将第一个可用候选当作最终选址。

上述是目标输入边界。当前代码的 `post_l3_nodes.execute_node` 仍向 `ExecuteAgentState` 注入 intent、bundle、
selection 和 reports-derived 数据，尚未只接受 `SiteSelectionDecision + ExecutionPlan`。当前内部节点仍是
`route_tasks → execute_layout → execute_project → execute_facility → execute_axis → execute_road → validate → write_l4`。

目标重构应形成：

```text
prepare_inputs → land_design / allocation → geometry_materialize
  → road_axis_layout → planned_state_builder → execution_review → write_l4
```

其中 Zone Worker 应由 MIP/约束求解器处理规划分区，不得把现状地类代码直接映射为规划分区；Road Worker 应
以 staged road planner 为正式路径，简化 planner 只能显式标记为 degraded fallback。EXECUTE 内部的
`execution_review` 只做执行完整性和 Worker 间冲突检查，最终规则、拓扑、面积和连通性校验仍由外层 VALIDATE 负责。

## 6. 旧实现的迁移对应

| 旧实现 | 目标职责 |
|---|---|
| `agent/select/parse_agent.py` | 已删除；共享 compiler 位于 `app/agent/parse/` 与 `app/modules/parsing/compiler/` |
| `modules/spatial_ops/grounding.py` | Grounding domain service |
| `modules/spatial_ops/bundle_binder.py` | 删除；改为 context-aware reference resolution |
| `agent/gis/execute/agent.py` | 已迁移；当前实现仍集中在 `app/agent/execute/execute_agent.py` |
| `tools/gis/_generation/*` | 部分仍被 custom zoning / GIS 适配器使用，尚未全部收敛 |
| `services/modules/gis/road/*` 与 `spatial_ops/road_planner.py` | 当前并存；目标是以 staged planner 为唯一正式 Road Worker |
