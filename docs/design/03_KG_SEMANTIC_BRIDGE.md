# KG 语义与空间桥接

## 1. KG 的定位

KG 是事实、关系、意图和成果的语义索引，不是所有空间计算的替代品，也不是工作流状态容器。

空间查询由两个能力组合：

```text
KG semantic query (entity / relation / constraint)
        +
Spatial query service (geometry / index / distance / topology)
        → GroundingResult or ValidationEvidence
```

## 2. 四类数据边界

为避免与规划 L1/L2/L3 混淆，KG 层不再使用 L1/L2/L3/L4 命名。

| KG 数据集 | 内容 | 写入者 | 读取者 |
|---|---|---|---|
| `BaseFacts` | 现状地块、道路、水体、设施、行政实体、编码、来源 | Data/KG Builder | L1、Explore、Ground、Validate |
| `DerivedRelations` | `sfTouches`、`sfWithin`、`sfIntersects`、邻近、道路连通、约束覆盖 | SpatialOps/KG Builder | L1、L2、Ground、Select、Validate |
| `IntentGraph` | L3 的 Zone/Facility/Road/Project 和空间引用关系 | IntentCompiler | Ground、Select、Execute、Reconcile |
| `PlannedState` | PlannedZone、PlannedFacility、PlannedRoad、PlannedProject | Execute | Validate、Reconcile、Delivery |

地名解析不直接把 KG 查询结果当作最终候选。KG 的实体、别名、关系和来源应与 L1 产出的
`L1LocationFact`、VillageBundle 几何共同组成 `PlaceEvidenceIndex`，由 GROUND 的
`PlaceEvidencePort` 消费。详细流程见 [12_PLACE_NAME_RESOLUTION.md](12_PLACE_NAME_RESOLUTION.md)。

## 3. KG 接口

```python
class SemanticQueryPort(Protocol):
    def find_entities(self, ref: RefObject) -> list[EntityRef]: ...
    def query_relations(self, relation: str, subject: EntityRef) -> list[EntityRef]: ...
    def get_constraints(self, scope: EntityRef) -> list[ConstraintFact]: ...
    def get_cognition(self, scope: str, purpose: str) -> CognitionSummary: ...


class SpatialQueryPort(Protocol):
    def refine(self, entities: list[EntityRef], spec: SpatialReferenceSpec) -> CandidateSet: ...
    def measure(self, candidates: list[str], features: list[str]) -> list[CandidateMetric]: ...
```

`resolve_spatial_description()` 不再同时承担自然语言分类、Gazetteer 加载、KG 回调注入和几何兜底；这些职责由 IntentCompiler、SemanticQueryPort 和 SpatialQueryPort 分开完成。

## 4. 各规划阶段的 KG 角色

| 规划阶段 | KG 用法 |
|---|---|
| L1 | 通过 EXPLORE 请求现状事实、约束覆盖和空间认知摘要 |
| L2 | 通过 EXPLORE 请求空间格局、设施覆盖、交通可达性和发展条件证据 |
| L3 | 通过 EXPLORE 请求项目、设施、道路和空间关系相关证据 |
| L2 | 验证策略是否违反现状结构和管制关系 |
| L3 | 将规划文本编译为 IntentGraph，并保留证据来源 |
| GROUND | 将 `SpatialReferenceSpec` 解析为实体和候选集 |
| SELECT | 读取候选特征、关系和约束，生成评分输入 |
| EXECUTE | 读取 `SiteSelectionDecision`，写入 PlannedState |
| RECONCILE | 对账 IntentGraph 与 PlannedState |

## 5. 写入规则

- BaseFacts 只能由数据摄取或明确的事实修订写入。
- DerivedRelations 由可重建的空间计算生成，不由 LLM 直接写入。
- IntentGraph 只能由 IntentCompiler 提交 revision。
- PlannedState 只能由 Execute 提交，并携带 `derived_from`。
- 所有 KG 写入都必须带 session、version 和 provenance。
- L1/L2/L3 不直接持有 KG 实例；KG 查询由 EXPLORE 通过 `SemanticQueryPort` 统一执行。
- `SpatialCognitionEvidence` 是供维度分析消费的证据视图，不是候选地块或选址决定。

## 6. 失败语义

KG 查询失败不等于“没有实体”。接口必须区分：

- `not_found`：查询成功但没有结果。
- `stale_snapshot`：快照与 Context 不一致。
- `query_error`：查询执行失败。
- `ambiguous`：多个实体均匹配。
- `insufficient_geometry`：语义实体存在但缺少可计算几何。

这些状态由 Gate 决定是进入 EXPLORE、回到 L3、请求人工确认还是停止交付。
