# 09 模块实施规格：缓存外源证据到可渲染规划成果

> Status: TARGET / IMPLEMENTATION SPEC
>
> Authority: 本文件把 `07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md` 的跨阶段原则落实到当前仓库的 Data、外源缓存、Cognition/KG、Evidence、GROUND、SELECT、EXECUTE 和 DELIVER 模块。`00` 仍是业务主链总览，`05_MIGRATION.md` 仍是实际完成状态账本。

## 1. 目标与现实约束

本阶段的实际目标不是重新采集地图服务，也不是把地图 POI 直接画到规划图上，而是使用已有缓存支持一条可复现的规划链：

```text
本地 GIS / 文档 / 已有地图缓存
        ↓
Data Source Catalog + ExternalObservationSnapshot
        ↓
动态字段/图层理解 + 实体支持聚类
        ↓
Evidence 双平面 + Session KG
        ↓
GROUND 选择本地 WorldEntity/SpatialRepresentation
        ↓
SELECT 接收可计算 resource_ref
        ↓
EXECUTE 在本地 Geometry 上生成 planned changeset
        ↓
DELIVER 输出 GeoJSON/PNG/HTML，全部带 lineage
```

外源缓存不具备本地项目边界、完整路网或法定规划几何的权威性。它们只能提供名称、别名、行政范围、坐标锚点、道路/水体观察、候选类型和 provenance。

## 2. 当前实现到目标产出的差距

| 模块 | 当前实现（代码事实） | 目标产出差距 | 本规格的落点 |
|---|---|---|---|
| Data | `SessionDataSnapshot`、`SpatialFeature` 和 `VillageBundle` 仍以 Bundle/单一 geometry 为主；`DataCatalog.load_village_bundle()` 可能进入旧 ExternalAnchorPipeline | 任意字段、多 Geometry 和外源缓存没有统一只读观察模型 | `external_observation_contracts.py` + `external_observation_cache.py`；缓存不写回 Bundle |
| 外源 provider | AMap/天地图/腾讯采集脚本已有 raw、normalized、manifest、状态和 cache key | 生产 Evidence 不能读取这些缓存，只能选择在线文本 provider | cached-map retriever；缺缓存不在线回退 |
| Cognition | source semantic classifier 可识别部分 source label；KG builder 仍由 Bundle 固定专题驱动 | provider observation、别名、同坐标实体支持没有独立 assertion | cluster + `ExternalEntitySupport`，实体 ID 不使用 BSM |
| KG | `EntityIdPolicy` 和 `SpatialKGEntity` 对 BSM/单 geometry 有历史约束 | 外源观察无法成为可撤销的实体支持事实 | adapter 只写 observation support predicates，不宣称最终实体类型 |
| Evidence | `EvidenceGraph`/`PlaceEvidenceIndex` 仍混合候选召回、空间绑定和部分实体合并 | 地图数据若作为文本会丢 coordinate contract、operation、scope 和 raw ref | `EvidenceFact.fact_type=external_map_observation`，独立字段 JSON |
| GROUND | 已有闭集候选和 LLM bounded selection，但仍可见 Bundle/KG/EvidenceGraph 历史入口 | 外源候选可能被误当执行 Geometry；道路/地点表示粒度不足 | Ground 只接 entity/representation；外源只作为 evidence/support |
| SELECT | solver 以 parcel/BSM 和部分 feature_id 为资源键 | 无法统一消费道路、设施、点、多面表示 | `resource_ref` + `representation_ref`，parcel adapter 才接受 BSM |
| EXECUTE | 规划工人和 materializer 已能产出 planned state，但不同 worker 的 lineage 不完全一致 | 规划结果需可渲染、可追溯、可回放 | geometry lineage validator + DeliverySpatialSnapshot |
| DELIVER | renderer 读取 DeliverySpatialSnapshot/render_layers，已禁止示意线冒充成果 | 若 planned layer 缺 geometry 或 lineage，状态需要明确诊断 | render contract fail-closed，仍允许 baseline-only diagnostic |

## 3. 外源缓存对象和坐标契约

### 3.1 ExternalObservation

每条观察保留：

```text
observation_id
provider / stage / operation
status / attempted / retry_count
observed_name / aliases / observed_type
scope_bucket / admin_match
location_native / location_wgs84 / coordinate_contract
geometry / geometry_semantics
raw_response_ref / request_key / source_record_ref
cluster_id / metadata
```

状态必须区分：

```text
success_nonempty
success_empty
missing
failed
not_attempted
```

`failed` 代表已调用但权限、配额、HTTP 或传输失败；`missing` 代表能力不可用或成功但无数据；两者都不能解释为实体不存在。

### 3.2 一次坐标归一化

| Provider | 保留原始坐标 | 本地计算坐标 | 规则 |
|---|---|---|---|
| AMap | GCJ-02 `[lon,lat]` | WGS84 `[lon,lat]` | 仅在缓存读取时转换一次；保存转换方法和原值 |
| 天地图 | 官方 lon/lat | WGS84-compatible | 不套用 GCJ-02 偏移 |
| 腾讯 | 原始 `lat/lng` 顺序 | WGS84 `[lon,lat]` | 只调整轴顺序，不把纬度/经度写反 |

所有本地空间判断、同坐标聚类和 GROUND 辅助检索都只使用 `location_wgs84`。原始坐标只用于审计和重放。

## 4. 同坐标实体支持与 GIS Feature 区分

外源观察不能直接成为 WorldEntity。采用三层结构：

```text
ExternalObservation
    ↓ spatial cluster（例如 30 m）
ExternalEntitySupport
    ↓ Cognition accepted assertion
WorldEntity / EntityPart
    ↓ representation selection
Local SpatialRepresentation
```

同一空间范围内的多个 provider 观察进入同一个 support cluster，但每一条观察和名称别名都保留。cluster 不等于自动实体合并：类型冲突、时间冲突、行政冲突和道路编号冲突必须进入 `ambiguous`。

道路要求：

- 外源道路 POI、逆地理道路名和本地连续线段只能形成支持证据。
- 道路整体、道路段、道路中心线、道路红线和路网边分别建模。
- 三个连续本地线段可以组成一个 `RoadEntity` 和三个 `RoadSegment`，同时生成一个 derived MultiLine representation。
- 外源 route polyline 不得直接作为规划道路 Geometry。

地点要求：

- 点状定位、管理边界面、建成区面和服务范围面可以是同一 `PlaceEntity` 的不同 representation。
- 同名异地地点不能因为名称相同自动合并。
- 同坐标但名称不同的观察只合并为 support cluster，交给 Cognition 产生 accepted/ambiguous assertion。

## 5. Evidence 检索契约

业务查询只描述：

```text
concept / role / name or alias / scope / representation purpose / spatial relation
```

不描述：

```text
roads_current / facilities_current / bundle / kg / BSM
```

Evidence 返回两个互补平面：

1. World plane：实体、部件、表示、关系和 capability。
2. Source plane：外源观察、原始字段、provider response、状态和 provenance。

地图缓存 Evidence 的事实形态：

```json
{
  "fact_type": "external_map_observation",
  "evidence_role": "location_binding",
  "source_kind": "external_map_cache",
  "spatial_refs": ["external-observation:..."],
  "fields": {
    "provider": "amap",
    "operation": "reverse_geocode",
    "location_wgs84": "[116.04,24.82]",
    "coordinate_contract": "GCJ-02→WGS84 once",
    "scope_bucket": "project_local",
    "raw_response_ref": "output/map_validation/..."
  }
}
```

它可以支持名称、别名、类型、范围和候选排序，但不能单独支持“这就是完整道路/水体边界”。

## 6. GROUND 到 SELECT/EXECUTE 的资源协议

GROUND 输出必须提供：

```text
entity_ref
representation_ref
source_snapshot_ref
source_feature_ids
geometry_ref
geometry_kind
purpose
relation_refs
evidence_refs
```

SELECT 接受 `resource_ref` 和 `representation_ref`。`resource_ref` 指向可计算、可加载、带 CRS 和 digest 的本地空间资源；只有 parcel solver adapter 可以把 BSM 作为兼容字段。外源 observation ref 只能出现在 `evidence_refs`/`source_refs`，不能进入 solver geometry 输入。

EXECUTE 产生 planned entity、planned representation 和 changeset。所有规划线、面和点都必须：

1. 来源于当前 Data Geometry 或已批准的空间运算；
2. 明确 CRS 和 WGS84 输出转换；
3. 带 `world_model_digest`、`source_snapshot_ref`、`representation_ref` 和 approval lineage；
4. 能被 `DeliverySpatialSnapshot` 重新加载。

## 7. 交付渲染契约

DELIVER 只读取 `DeliverySpatialSnapshot` 和 `render_layers`，不回查 Bundle、KG 或 provider。每个渲染 Feature 必须有：

```text
valid GeoJSON geometry
layer_type / layer_name
source_snapshot_ref or world_model_digest
representation_ref or resource_ref
status / operation
```

如果规划层没有实际 Geometry，渲染器必须输出 `diagnostic_only` 或缺失原因，不画示意线冒充成果。baseline-only 地图可以渲染，但交付状态必须不是 `complete`。

## 8. 运行模式和缓存策略

```text
cache-only（本阶段默认）
  ↓
shadow（V1/V2 对比）
  ↓
prefer_v2（V2 权威，显式兼容回退）
  ↓
v2_only（不构建/读取 Bundle provider fallback）
```

本阶段强制 cache-only：

- 读取已有 manifest/raw/normalized 文件；
- 不调用 provider connection、HTTP client 或在线 external search；
- cache key 包含 provider、stage、operation、归一化参数和 snapshot digest；
- 读取结果进入 session context 后，Evidence cache key 包含 external snapshot digest；
- 缺失或失败状态进入诊断，不自动重试。

## 9. 验收矩阵

| 场景 | 必须通过的事实 |
|---|---|
| 未知 layer/field | 原始属性保留；schema unresolved 不阻止 source snapshot |
| 三 provider 缓存 | 不产生 HTTP；状态、raw ref、坐标契约可追溯 |
| 同坐标多 provider | observation 全保留；cluster 相同；名称进入 aliases/support |
| 三段道路 | segment refs 保留；整体/部件表示可区分；Ground 选择本地表示 |
| 点+多面地点 | 同一 entity 可有多 representation；purpose 改变选择 |
| LLM 不可用 | source/evidence 可建立；候选保持 ambiguous/unresolved |
| SELECT | 只接收本地 resource/representation；外源 ref 只能是证据 |
| EXECUTE | planned geometry 有 digest/CRS/approval lineage |
| DELIVER | planned road/zone/facility 能渲染；缺失时 fail-closed diagnostic |

## 10. 实施入口

第一批代码任务和测试顺序见 [缓存外源证据与世界模型垂直切片实施计划](../superpowers/plans/2026-08-29-world-model-cache-vertical-slice.md)。完成每个任务后更新 `05_MIGRATION.md` 的实际状态，不将本规格或实施计划当成已完成证据。

## 11. 实体粒度、无名地块与阶段 I/O（实现必须遵守）

### 11.1 KG 的基本单位不是名称，而是可识别的 WorldEntity

KG 实体的最小单位按“可独立谈论、可建立关系、可选择至少一个空间表示”确定，而不是按 provider 的一条记录或 Bundle 的一个 feature 确定。推荐的标识层次为：

```text
WorldEntity（稳定语义对象）
  ├─ EntityPart（可独立约束/统计/编辑的部件）
  └─ SpatialRepresentation（点/线/面/多面/范围；可随数据版本变化）
```

没有名字的地块仍然是合法实体：`entity_ref` 由数据集、图层语义指纹、稳定 feature identity 和版本组合生成，不依赖空名称、临时序号或 BSM；`label` 可以为空，未知字段进入 `claims`/`unmapped_attributes`，而不是丢弃。只有语义证据充分时才提升为 `Parcel`、`Road`、`WaterBody` 等类型，否则保留 `WorldEntity + geometry_kind + semantic_hypotheses`，状态为 `unresolved`。

大地块按业务可操作性处理：共享用途/权属/约束并作为一个操作对象时保持一个 `EntityPart`；用途、权属、约束或规划操作在面内变化时拆成多个部件，并用 `part_of` 连接到同一 `WorldEntity`；仅为渲染、索引或拓扑切片的几何不提升为新语义实体，而是保留 `derived_from`。线性对象采用“整体—连续段—几何表示”三层，多个道路线段可属于一个 `RoadEntity`，同时每个段仍可单独参与邻接、缓冲和施工操作。

### 11.2 各阶段严格的输入/输出边界

| 阶段 | 消费什么 | 产出什么 | 明确禁止 |
|---|---|---|---|
| Data | 任意文件、字段、图层和 CRS | `SourceDataset`、`SourceFeature`、geometry + 原始属性 + digest | 要求字段必须叫 `BSM`/`roads_current` |
| Cognition/KG | Data 语义摘要、Evidence 断言、外源 observation support | `WorldEntity`、`EntityPart`、`SpatialRepresentation`、关系、语义候选 | provider POI 直接成为规划实体/几何权威 |
| Evidence | KG 世界平面 + source observation 平面 + 文档/L1/L2 事实 | 可追溯 `EvidenceFact`/`EvidenceSource`、候选和冲突 | 返回无 provenance 的裸名称/坐标 |
| L1 | Data/Evidence 观察事实 | 带来源 typed observations、名称/属性/范围线索 | 生成最终规划几何 |
| L2 | 已确认/待确认实体、约束和空间关系 | 方案规则、服务半径、布局候选、约束解释 | 直接写最终图层 |
| L3 | L2 规则 + 可计算 representations | `Intent`/`Target`、候选集合和评分 | 接受 external observation 作为 geometry ref |
| GROUND | Evidence 候选 + KG 实体/表示 + Data 能力 | `entity_ref + representation_ref + evidence_refs + ambiguity` | 只返回名称/BSM或把 observation 当 geometry |
| SELECT | GROUND 的本地 `resource_ref`/`representation_ref`、约束和操作目的 | 可执行选择集、空间操作参数、拒绝原因 | 依赖固定图层名；从外源文本猜 geometry |
| EXECUTE | SELECT 资源引用、CRS、操作类型和 approved lineage | planned entity/representation、changeset、digest、审计事件 | 重新搜索 provider；凭空制造线面 |
| DELIVER | `DeliverySpatialSnapshot` 中的 planned/baseline representations | GeoJSON/PNG/HTML 和诊断 | 回查 KG/Bundle/provider 或画示意几何 |

### 11.3 多源 GIS 合并的可执行算法

多源合并不是把三个 provider 的 feature 做 union，而是：规范化（记录 CRS、轴顺序、有效性、时间和 `source_feature_ref`，内部计算统一 WGS84）；候选关联（按距离/IoU、别名、类型兼容性、行政范围和时间生成 links，阈值与算法版本进入 provenance）；实体支持聚合（形成 support cluster，保留每条 observation，对冲突产生 `ambiguous` assertion）；本地表示选择（只有 Data 中有 CRS、digest 和可加载 geometry 的 representation 才能进入 GROUND/SELECT）。

同一坐标（容差内）只意味着“同一空间支持簇”，不自动意味着同一实体；名称、类型、行政范围和时间一致时，Cognition 才能关联到已有 `WorldEntity`。名称相同但空间分离必须保持不同候选。

### 11.4 SELECT/EXECUTE 的核心答案

SELECT 和 EXECUTE 不只依赖 KG，也不直接操作 KG 的几何。KG 负责“这是什么、与谁相关、可做什么”的语义和关系；Data representation 负责“实际在哪里、什么 CRS、如何加载”。二者通过 `representation_ref -> resource_ref -> source_snapshot/digest` 连接：

```text
KG entity/intent + Evidence support + local representation capability
        ↓ SELECT
ExecutableResourceRef (dataset, feature, geometry, CRS, digest, operation)
        ↓ EXECUTE
PlannedRepresentation + ChangeSet + lineage
        ↓ DELIVER
renderable planning layer
```

只有 KG 实体而没有可加载的本地 representation 时，SELECT 返回 `unresolved_geometry`；只有外源坐标而没有 Data geometry 时，EXECUTE 必须拒绝，而不是把外源点转换成规划面/线。

## 12. LLM 输入/输出协议：表格优先、分页、引用化

### 12.1 强制规则

所有进入 LLM 的结构化事实必须先转换成有固定列的表格。表格可以是 Markdown、CSV-like 文本或严格的二维 JSON rows，但不能把整个 `L1Snapshot`、KG 图或 Bundle 作为嵌套 JSON 一次性塞入 prompt。

实现入口为 `backend/app/infrastructure/llm/table_protocol.py`；它统一执行列数、行数、字符数和输出嵌套深度校验，业务维度不得自行绕过该入口。

强制限制：

1. 每张表只表达一个主题，列数默认不超过 12；
2. 每页默认不超过 32 行、6200 字符，L2/L3 可提高行数但仍需分页；
3. 一行只代表一个事实、一个实体、一个约束、一个 gap 或一个目标，不在单元格内嵌套数组对象；
4. 长文本只保留摘要和 `source_ref`，完整内容通过 artifact/source ref 回查；
5. 关系使用 `from_ref`、`relation`、`to_ref` 三列，不嵌套 adjacency/tree 对象；
6. 多值字段使用稳定分隔符或独立子表，禁止无限增长的 `list[dict]` 单元格；
7. LLM 一次调用最多产出一个 bounded page 的 rows，超过数量必须返回 `continuation_required`，由程序继续分页调用；
8. 任何 LLM 输出都先落成扁平行，再由程序按 ref 组装快照、图谱和规划程序；LLM 不直接产出完整嵌套的 `WorldModel`/`ExecutionPlan`。

### 12.2 四类 LLM 表

| 表 | 用途 | 最小列 |
|---|---|---|
| `source_observation_rows` | L1 从文档/GIS/缓存抽取观察 | `row_ref, dimension, subject_text, predicate, value, unit, source_ref, source_span, status` |
| `dependency_fact_rows` | 下游维度消费上游产物 | `fact_ref, producer_dimension, fact_type, subject_ref, value, confidence, source_refs` |
| `constraint_gap_rows` | L2/L3 判断缺口和补证据动作 | `gap_ref, consumer_dimension, requirement, current_status, retrieval_capability, priority` |
| `target_rows` | L3 形成目标和空间需求 | `target_ref, claim_family, subject_ref, operation, representation_purpose, required_capabilities, evidence_refs` |

KG、Evidence、Data 的详细对象都通过引用列进入这些表，而不是展开成一棵大 JSON 树。程序负责根据引用加载下一页或执行确定性空间查询。

### 12.3 输出大小和质量门

结构化解析器必须拒绝：

- 顶层不是 rows/list 的对象；
- 单次超过当前 page row limit；
- 出现未声明的嵌套对象或深度超过 2；
- 缺少 `row_ref`、`source_ref` 或对应阶段所需的主键；
- 输出了 `geometry` 坐标数组但没有 `representation_ref` 和 `source_snapshot_ref`；
- 以自然语言段落代替 required columns。

拒绝后由程序执行 bounded retry，只要求模型返回缺失/违规的行，不重发整个上下文。

## 13. L1/L2/L3 的重新定位与依赖树传递

### 13.1 维度不是孤立报告，而是依赖树中的生产者/消费者

`phases.yaml` 中的 28 个 dimension 是规划领域视角，不是 28 个互相独立的文本报告。每个维度都必须声明：

```text
producer_layer
input_product_types
output_product_types
upstream_dimensions
downstream_dimensions
gap_types_it_can_resolve
spatial_capabilities_required
```

同一规划领域在不同层的含义不同：

- L1 的 `traffic` 生产道路/端点/网络的观察事实；
- L2 的 `traffic` 消费这些观察，生产道路问题、连通性规则、优先级和约束；
- L3 的 `traffic` 消费规则和本地 representations，生产道路目标、候选操作和施工参数。

它们可以共享 `dimension_key=traffic`，但不能共享同一个 fact schema 或同一个 report string。

### 13.2 L1：观察事实生产层

L1 只回答“输入中观察到什么”：

```text
source_observation_rows
  → L1Fact rows
  → LocationMention / EvidenceGap rows
```

L1 必须区分：

- `document_observation`：文档明确写出的事实；
- `gis_observation`：Data geometry/属性明确存在的事实；
- `spatial_observation`：来源支持的空间关系；
- `derived_metric`：程序依据已知数据计算的指标；
- `pending`：尚未核实的观察。

L1 不负责“命名实体”。L1 只产生可追溯的 `subject_text`/`mention_ref`，必要时提出 `place_binding` gap。KG 的 `entity_ref` 由后续认知和 GROUND 产生。

### 13.3 L2：跨维度综合和规则生产层

L2 不只是“规划思路作文”，而是依赖树上的综合节点。它消费多个 L1 维度的 `dependency_fact_rows`，生产：

```text
resource_endowment_rows
planning_positioning_rows
development_goal_rows
constraint_rule_rows
service_requirement_rows
priority_rows
```

每一行都必须包含：

```text
producer_dimension
input_fact_refs
claim_ref
rule_or_metric
applicability_scope
confidence
unresolved_gap_refs
```

L2 的结果仍然不生成最终几何，只生成“需要什么空间能力”和“怎样评价候选”的规则。

### 13.4 L3：目标、项目和空间需求生产层

L3 消费 L2 规则、L1 来源事实和 KG/Data 的 capability rows，生产扁平的：

```text
target_rows
candidate_request_rows
spatial_requirement_rows
program_rows
```

L3 可以声明：

- 目标对象；
- 目标操作；
- 面积/服务半径/连通性要求；
- 需要的 representation purpose；
- 需要哪些本地能力；
- 哪些 evidence gap 必须先解决。

L3 不创建 geometry，不直接写 planned layer。

### 13.5 依赖树传递什么

维度之间传递的是带 ref 的产品行，而不是完整上一维度报告：

```text
L1 fact rows
  ↓ fact_ref / source_ref
L2 rule and requirement rows
  ↓ claim_ref / requirement_ref
L3 target and spatial requirement rows
  ↓ target_ref / candidate_request_ref
GROUND candidate rows
  ↓ representation_ref / evidence_refs
SELECT executable resource rows
  ↓ operation + approved lineage
EXECUTE planned changeset rows
```

这样可以只重算受影响的下游节点，而不是因为一个 L1 事实变化就把所有维度的嵌套报告重新塞给 LLM。

## 14. Fact、Evidence 和 Gap 的命名、定位和关系

### 14.1 命名空间

名称必须可由程序确定、可读、可去重：

```text
l1.fact.<dimension>.<fact_kind>.<hash>
evidence.source.<source_kind>.<hash>
evidence.observation.<provider>.<stage>.<hash>
evidence.gap.<consumer_dimension>.<requirement>.<hash>
l2.claim.<dimension>.<claim_family>.<hash>
l3.target.<dimension>.<claim_family>.<hash>
ground.binding.<target_or_mention>.<hash>
select.resource.<operation>.<hash>
execute.change.<target>.<hash>
```

### 14.2 L1 Fact 与 Evidence 的区别

`L1Fact` 是一个经过 L1 语义抽取、拥有 `fact_id` 的规划观察产品；`EvidenceFact` 是统一 Evidence Runtime 对多个来源事实的检索投影。二者不能互相冒充：

```text
L1Fact.fact_id
  ├── source_refs → EvidenceSource.reference
  └── evidence_refs → EvidenceFact / external observation
```

Evidence 的定位是“这个主张可以由哪些来源支持”，不是重新命名 L1 Fact。统一检索返回时，必须保留：

```text
producer_kind
producer_dimension
fact_ref
source_ref
source_span / source_record_ref
spatial_refs
status
```

### 14.3 Evidence Gap 是可立即补充的工作项

Evidence Gap 不能只是报告末尾的一句“资料不足”。它必须是可调度的行：

```text
gap_ref
consumer_dimension
requirement
subject_ref / subject_text
missing_fields
allowed_sources
retrieval_capability
priority
status
```

状态建议：

```text
open → ready_for_retrieval → retrieving → resolved
                              ↘ not_available
                              ↘ requires_human_confirmation
```

只有 `ready_for_retrieval` 且存在允许的缓存/本地能力时，Evidence Runtime 才应立即补充；否则进入 `not_available` 或人工确认队列。缺少证据不得通过 LLM 猜测填平。

Evidence 补充完成后只更新 gap 对应的 source/fact rows，并沿依赖树标记受影响维度，不重新生成无关维度的全部内容。

## 15. 当前维度设计的修正方向

现有 `phases.yaml` 已经有 `depends_on`、`layer_depends_on`、`phase_depends_on`，但大多数维度仍共享过宽的 `l1_fact_types`、`l3_claim_families` 和统一空间边界。迁移时必须增加或推导以下字段：

```yaml
products:
  l1_outputs: [source_observation, location_mention, evidence_gap]
  l2_inputs: [fact_ref, evidence_ref]
  l2_outputs: [constraint_rule, service_requirement]
  l3_inputs: [claim_ref, requirement_ref, capability_ref]
  l3_outputs: [target, spatial_requirement, candidate_request]
llm_contract:
  input_tables: [source_observation_rows, dependency_fact_rows]
  output_table: target_rows
  max_rows_per_call: 24
  max_columns: 12
gap_policy:
  immediate_retrieval: true
  allowed_sources: [local_data, cache, kg]
```

旧字段可在兼容期由程序推导，但不得再用一个宽泛的 fact/claim 列表代表全部层级职责。每个维度的目标是“生产下一层可以消费的最小产品”，不是生成一篇自包含长报告。
