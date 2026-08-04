# PARSE、GROUND、SELECT 与 EXECUTE

## 1. 四个阶段的边界

```text
PARSE / IntentCompiler
    text + evidence → L3PlanningIntent + SpatialReferenceSpec

GROUND
    SpatialReferenceSpec + context → GroundingResult

SELECT
    GroundingResult + requirements → PlacementDecision

EXECUTE
    PlacementDecision → PlannedState / output layers
```

## 2. PARSE / IntentCompiler

PARSE 是类型化编译器，不是空间查询 Agent。它负责：

- 从 L3 文本提取 Zone、Facility、Road、Axis、Project。
- 将自然语言空间关系编译为 `SpatialReferenceSpec`。
- 关联 `EvidenceItem` 和来源段落。
- 校验必填字段、枚举和目标之间的引用。

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
5. 产生 `PlacementDecision`。

Selection Agent 的输入是规范化候选特征，输出只能是候选排序、理由和不确定性，不能直接输出新 BSM 或新坐标。

```python
class PlacementDecision(BaseModel):
    target_id: str
    selected_bsm: str | None
    selected_geometry_ref: str | None
    rejected_candidates: list[dict]
    decision_factors: dict[str, float]
    evidence_ids: list[str]
    status: Literal['selected', 'unresolved', 'requires_review']
```

## 5. EXECUTE 子图

EXECUTE 只接受 `PlacementDecision` 和 `ExecutionPlan`。按目标类型分派单一正式 Worker：

| Worker | 输入 | 输出 |
|---|---|---|
| Zone Worker | 分区目标、分配指标 | function/land-use layers |
| Facility Worker | 设施位置决定、容量 | planned facility layer |
| Road Worker | 道路目标、道路网络和约束 | planned road layer |
| Axis Worker | 轴线目标和锚点 | planned axis layer |
| Project Worker | 项目选址决定 | planned project layer |

Worker 不得重新调用 PARSE，也不得将第一个可用候选当作最终选址。

## 6. 旧实现的迁移对应

| 旧实现 | 目标职责 |
|---|---|
| `agent/gis/parse/agent.py` | IntentCompiler + reference extraction |
| `modules/spatial_ops/grounding.py` | Grounding domain service |
| `modules/spatial_ops/bundle_binder.py` | 删除；改为 context-aware reference resolution |
| `agent/gis/execute/agent.py` | Execute orchestration only |
| `tools/gis/_generation/*` | 迁入对应 Worker |
| `services/modules/gis/road/*` 与 `spatial_ops/road_planner.py` | 合并为一个 Road Worker |
