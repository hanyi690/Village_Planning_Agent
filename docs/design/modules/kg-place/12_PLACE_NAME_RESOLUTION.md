# 地名解析与 L1/KG 事实融合设计

## 1. 问题定义

当前 `SpatialResolver` 的主要路径是：

```text
SpatialReferenceSpec
  → SpatialQueryPort / kg_query_fn
  → bundle BSM 过滤
  → direction bbox fallback
```

`PlaceNameResolver` / Gazetteer 主要依赖 KG 聚类、外部锚点和模糊匹配；L1 报告中的自然村名、设施地点、道路地点和空间事实尚未以统一的 typed fact index 参与候选排序。短地名的 fuzzy fallback 还可能把多个候选压缩成第一个匹配项。

这会造成三个问题：

1. L1 已经确认的地点事实没有进入 TARGET_PROJECTION → GROUND 的正式证据链。
2. KG 的实体别名、类型、拓扑关系和来源没有参与完整的候选评分。
3. 外部 geocoder 或 village-center/bbox fallback 可能在 session 内已有更好证据时抢占主路径。

## 2. 设计原则

地名解析不是“把文字转成坐标”，而是：

```text
PlaceMention
  → session entity candidates
  → evidence-backed resolution
  → optional geometry refinement
```

解析结果只能说明“这个名称在本 session 中最可能指向哪些实体/空间范围”，不能直接完成项目选址或生成规划分区。

优先级固定为：

```text
明确的 session KG 实体/别名
  > L1 typed location fact
  > KG 类型、拓扑和行政范围一致性
  > Bundle 几何一致性
  > 外部 geocoder
  > 无证据的模糊匹配
```

无证据的短名称模糊匹配不得自动通过，只能产生 `ambiguous` 结果或人工审查请求。

## 3. 统一输入与索引

### 3.1 L1 地点事实

L1 compiler 应在 `L1Snapshot.location_facts` 和 `L1Snapshot.fact_records` 中输出可追溯的地点事实；
不要只把地名留在 `facts: list[str]` 中。

```python
class L1LocationFact(BaseModel):
    mention: str
    normalized_name: str
    role: Literal["village", "facility", "road", "water", "landmark", "area", "unknown"]
    aliases: list[str] = []
    spatial_hint: str = ""
    related_mentions: list[str] = []
    source_report_ref: str
    source_span: str = ""
    evidence_refs: list[str] = []
    confidence: float = 0.0
```

`L1Snapshot.location_facts` 是 L1 地点事实的阶段级集合。它不包含最终 BSM 选择，只包含报告中明确出现的地点语义和来源。

### 3.2 PlaceEvidenceIndex

`PlanningContext` 构建后，为当前 `context_version + kg_version + l1_snapshot_ref` 建立可重放索引：

```text
PlaceEvidenceIndex
├─ canonical_name → KG entity refs
├─ alias → KG entity refs
├─ L1 normalized_name → L1LocationFact refs
├─ entity_type / role index
├─ related entity and topology index
├─ village anchor index
├─ bundle geometry index
└─ provenance / version metadata
```

索引可以由 EXPLORE/Context service 构建，但解析器只通过 `PlaceEvidencePort` 读取，不能直接访问 ReportStore 或 KG 实例。

## 4. 解析流程

### 4.1 候选生成

```text
PlaceMention
  → normalize aliases / suffixes
  → exact session KG lookup
  → L1LocationFact lookup
  → KG relation/type expansion
  → Bundle geometry candidates
  → external geocoder only when session evidence is insufficient
```

候选实体必须带：

```text
entity_ref
entity_type
canonical_name
aliases
geometry_ref
source_bsms
relation_refs
evidence_refs
```

### 4.2 证据评分

评分是可解释的确定性过程，权重由配置管理，不写死在 LLM prompt 中：

```text
exact canonical / alias match       + high
L1LocationFact exact mention        + high
KG entity type matches role         + medium
KG relation/topology matches hint   + medium
within current bundle                + medium
geometry near known L1 anchor       + medium
external geocoder                   + low
fuzzy-only short-name match         + prohibited auto-pass
```

输出三个状态：

```text
resolved    单一候选达到阈值，证据充分
ambiguous   多个候选接近或只有弱证据
unresolved  没有有效候选
```

### 4.3 LLM 的位置

LLM 只允许在 `ambiguous` 状态下对 Top-K 候选做结构化判别：

```text
名称 + L1LocationFact + KG 候选摘要 + 几何/关系证据
  → {candidate_id, match, reason, missing_evidence}
```

LLM 不得创造新的 entity_ref、BSM 或坐标，也不得把地点解析结果直接写入 SiteSelectionDecision。

## 5. 统一输出契约

```python
class PlaceResolutionCandidate(BaseModel):
    entity_ref: str
    entity_type: str
    canonical_name: str
    aliases: list[str] = []
    geometry_ref: str | None = None
    source_bsms: list[str] = []
    score: float
    evidence_refs: list[str] = []
    relation_refs: list[str] = []


class PlaceResolutionResult(ContractMeta):
    mention: str
    normalized_name: str
    status: Literal["resolved", "ambiguous", "unresolved"]
    selected_entity_ref: str | None = None
    candidates: list[PlaceResolutionCandidate] = []
    evidence_refs: list[str] = []
    query_trace: list[dict[str, Any]] = []
    unresolved_reason: str | None = None
```

`SpatialResolver.resolve_spec()` 应消费 `PlaceResolutionResult`，将解析出的 entity/geometry 交给后续空间查询；它不应继续直接修改 intent 内的 `candidate_bsms`。

## 6. 与各阶段的边界

```text
L1        发现并结构化地点事实
EXPLORE   查询 KG、L1LocationFact、Bundle 和历史证据
TARGET_PROJECTION 将 PlanningProgram 中的地点引用编译为 SpatialReferenceSpec
GROUND    调用 PlaceEvidencePort / SpatialResolver，生成候选空间和证据
SELECT    仅在候选空间中选择项目位置
EXECUTE   消费 SiteSelectionDecision + ExecutionPlan，不再解析地名
```

## 7. MVP 落地顺序

### M0：索引和契约

- 增加 `L1LocationFact` 和 `PlaceResolutionResult` 契约。
- 将 L1 报告中已存在的自然村/设施/道路地点提取为 typed facts。
- 在 PlanningContext 中记录 `l1_snapshot_ref`、`kg_version` 和 index version。

### M1：session 内确定性解析

- exact KG name/alias；
- L1 fact match；
- entity type/role 过滤；
- Bundle 几何和 village anchor 校验；
- 禁止短名称 fuzzy 自动通过。

### M2：GROUND 接线

- `SpatialResolver.resolve_spec()` 返回 `PlaceResolutionResult` trace；
- `CandidateSite.target_ref/intervention_id` 必须保留；
- 解析失败进入 GROUND Gate，而不是扩大候选池。

### M3：歧义 LLM 判别

- 仅对 Top-K 候选调用 LLM；
- 结果写入 `compilation_trace`/`query_trace`；
- LLM 失败时保持 `ambiguous`，不能降级为第一个候选。

## 8. 验收标准

固定 fixture 至少覆盖：

1. KG canonical name exact match；
2. L1 fact alias match；
3. 同名地点但不同 entity type；
4. 短名称多候选；
5. KG 与 L1 fact 冲突；
6. 只有外部 geocoder、session 内无证据；
7. 无法解析的地点。

每个 case 都必须验证 status、候选排序、evidence_refs、context/kg/index version，以及 GROUND 对 unresolved/ambiguous 的正确路由。
