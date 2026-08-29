# Cognitive World Model Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前以 VillageBundle、固定 layer key、BSM 和单一 geometry 为中心的 Data→KG→Evidence→GROUND 链路，迁移为通用 Source Catalog→Cognition→Session World Model→Entity/Representation Query→GROUND 链路，并保持规划主链可增量运行和可回退。

**Architecture:** 迁移采用 strangler + shadow read。先建立独立 V2 contracts、Source Catalog 和 World Model store，通过 `BundleSourceAdapter` 导入现有数据；随后让新检索和 Ground 在 V1 旁路 shadow 运行并比较结果；最后按模块切换读写权威，Bundle 退为兼容输入/输出。任何阶段都不对现有 Source Record 做破坏性变更。

**Tech Stack:** Python 3.11、Pydantic v2、GeoJSON/GeoPandas、Shapely、PyProj、RDFLib、SQLAlchemy/PostGIS adapter、FastAPI、LangGraph、pytest、现有 structured LLM runtime。

## Global Constraints

- 所有文件使用 LF；Python 使用 4 空格和双引号；删除 trailing whitespace。
- 编辑现有文件前重新读取目标范围；使用短且唯一的代码锚点，不用大段中文注释作为匹配文本。
- `SourceFeatureRecord`、`WorldEntity`、`SpatialRepresentation` 和 workflow artifact 身份必须分离。
- 核心 V2 contracts 禁止出现 `bundle_feature_bsm`、`geometry_authority='bundle'` 或固定 layer key。
- LLM 只能选择已给 candidate ref 或 abstain；不能生成 source/entity/representation ID、坐标、WKT 或 geometry。
- Data 不得导入 KG、Evidence Runtime 或 GROUND；业务模块不得导入 KGManager、裸 RDF graph 或 retriever 实现。
- 每个迁移任务必须保留 source/world snapshot digest、provenance 和可重放测试。
- 每个任务必须通过自身单元测试、相关 acceptance probe、`python -m compileall -q app` 和 `git diff --check` 后再提交。
- 不使用历史 session 作为业务输入；集成验证创建新的 current session 或使用任务内构造的最小 source snapshot。

---

## 1. 迁移模式与发布门

### 1.1 运行模式

在 `backend/app/core/settings.py` 增加三个显式配置：

```python
COGNITION_WORLD_MODEL_MODE = "off"       # off | shadow | prefer_v2 | v2_only
COGNITION_SHADOW_DIFF_ENABLED = True
BUNDLE_COMPAT_MATERIALIZATION_ENABLED = True
```

语义：

| 模式 | 权威读 | V2 写 | 允许回退 |
|---|---|---|---|
| `off` | V1 Bundle/KG/Evidence/Ground | 否 | 不适用 |
| `shadow` | V1 | 是，并生成 diff artifact | 是 |
| `prefer_v2` | V2；缺 capability 时显式返回 unresolved | 是 | 只允许配置列出的 V1 adapter，不允许静默回退 |
| `v2_only` | V2 | 是 | 否 |

禁止使用“V2 查询为空就自动查 Bundle”的隐式回退。回退必须形成 `CompatibilityFallbackFinding`，记录 query、原因、world-model digest 和 V1 source refs。

### 1.2 迁移阶段

```text
M0 characterization and dependency gates
M1 cognition contracts
M2 lossless source catalog
M3 world model store and transactions
M4 schema understanding
M5 entity resolution and multi-representation assembly
M6 session cognition bootstrap
M7 world/evidence query runtime
M8 GROUND V2
M9 L2/SELECT resource migration
M10 intent/planned graph and delivery
M11 V2-only and compatibility retirement
```

每个阶段结束时更新 `docs/design/05_MIGRATION.md` 的状态；本文件只描述实施顺序，不记录某次运行是否已经通过。

## 2. 目标文件结构

```text
backend/app/
├── contracts/cognition/
│   ├── __init__.py
│   ├── source.py
│   ├── concept.py
│   ├── entity.py
│   ├── representation.py
│   ├── assertion.py
│   ├── query.py
│   ├── changeset.py
│   ├── snapshot.py
│   └── ports.py
├── modules/cognition/
│   ├── __init__.py
│   ├── application.py
│   ├── schema_understanding.py
│   ├── entity_resolution.py
│   ├── representation_assembly.py
│   ├── topology_assembly.py
│   ├── validation.py
│   └── projections.py
├── data/source_catalog/
│   ├── __init__.py
│   ├── readers.py
│   ├── profiler.py
│   ├── attribute_store.py
│   ├── geometry_store.py
│   ├── repository.py
│   └── bundle_adapter.py
├── infrastructure/cognition_runtime/
│   ├── __init__.py
│   ├── transaction.py
│   ├── rdflib_store.py
│   ├── postgis_store.py
│   ├── repository.py
│   ├── schema_matcher.py
│   ├── entity_matcher.py
│   └── indexes/
│       ├── entity_name.py
│       ├── entity_property.py
│       ├── source_attribute.py
│       ├── representation.py
│       ├── topology.py
│       └── provenance.py
├── modules/ground/
│   ├── request_compiler.py
│   ├── entity_grounder.py
│   ├── representation_selector.py
│   ├── relation_grounder.py
│   ├── constraint_evaluator.py
│   ├── candidate_domain_assembler.py
│   └── recovery.py
└── data/compatibility/
    ├── legacy_evidence_adapter.py
    └── bundle_materializer.py

backend/tests/
├── architecture/
├── cognition/
├── data/
├── evidence/
├── ground/
└── e2e/
```

现有 `infrastructure/kg/` 在迁移期作为 `WorldModelStore` 的 RDFLib/PostGIS implementation source，不立即删除；其公开调用逐步收口到 cognition ports。

---

### Task 1: 恢复测试入口并冻结当前依赖/行为基线

**Files:**
- Create: `requirements-dev.txt`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/architecture/test_cognition_dependency_rules.py`
- Create: `backend/tests/architecture/legacy_dependency_allowlist.txt`
- Create: `backend/tests/data/test_current_source_loss_characterization.py`
- Modify: `.github/workflows/gis-engine-ci.yml`

**Interfaces:**
- Consumes: 当前 Python package tree。
- Produces: `pytest` 测试入口、可逐项减少的 legacy dependency allowlist、当前属性丢失/单几何限制的 characterization evidence。

- [ ] **Step 1: 建立开发依赖文件**

写入：

```text
-r requirements.txt
pytest>=8.3,<9
pytest-asyncio>=0.24,<1
pytest-cov>=6,<7
```

- [ ] **Step 2: 写 dependency rule 测试**

测试使用 `ast` 枚举 import，禁止新增以下依赖：

```python
FORBIDDEN = {
    "app.data": ("app.infrastructure.kg", "app.infrastructure.evidence_runtime"),
    "app.modules.ground": ("app.infrastructure.kg", "app.infrastructure.evidence_runtime"),
    "app.spatial": ("app.infrastructure.evidence_runtime",),
    "app.modules.execute": ("app.infrastructure.kg",),
}
```

现存违规以 `module|imported_module` 一行一个写入 allowlist；测试断言 `observed - allowlist == set()`。后续任务每删除一个违规就同步删除对应 allowlist 行，因此新违规不能进入主干。

- [ ] **Step 3: 写当前数据损失 characterization 测试**

构造包含 `任意指标_X9` 和第二几何属性的 GeoJSON，断言当前 `_compact_source_properties()` 不保留该标量，并断言 `SpatialFeature` 只声明 `geometry`。该测试名称必须含 `legacy_characterization`，只记录迁移起点，不被 V2 实现复用。

- [ ] **Step 4: 运行基线测试**

Run:

```bash
cd backend
python -m pytest tests/architecture tests/data/test_current_source_loss_characterization.py -v
```

Expected: PASS；输出列出 allowlist 中的既有违规，但没有未登记违规。

- [ ] **Step 5: 修正 CI 路径**

CI backend job 依次运行：

```bash
python -m pytest tests/architecture tests/cognition tests/data tests/evidence tests/ground -v
python -m pytest tests/e2e -v -m "e2e and not slow"
```

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt backend/tests .github/workflows/gis-engine-ci.yml
git commit -m "test: establish cognition migration baseline"
```

---

### Task 2: 建立 Source、Entity、Representation 和 Snapshot 核心契约

**Files:**
- Create: `backend/app/contracts/cognition/__init__.py`
- Create: `backend/app/contracts/cognition/source.py`
- Create: `backend/app/contracts/cognition/concept.py`
- Create: `backend/app/contracts/cognition/entity.py`
- Create: `backend/app/contracts/cognition/representation.py`
- Create: `backend/app/contracts/cognition/assertion.py`
- Create: `backend/app/contracts/cognition/snapshot.py`
- Test: `backend/tests/cognition/test_core_contracts.py`

**Interfaces:**
- Consumes: `app.contracts.base.StrictContractModel`、`ContractMeta`。
- Produces: `SourceFeatureRecord`、`WorldEntity`、`SpatialRepresentation`、`SemanticAssertion`、`SessionWorldModelSnapshot`。

- [ ] **Step 1: 写身份分离失败测试**

测试创建两个 source record、一个 entity、三个 representation，并断言：

```python
assert left.source_record_ref != right.source_record_ref
assert entity.entity_ref not in {left.source_record_ref, right.source_record_ref}
assert {item.entity_ref for item in representations} == {entity.entity_ref}
assert {item.role for item in representations} == {
    "locator", "physical_extent", "administrative_extent"
}
```

再用 `model_validate` 传入 `bundle_feature_bsm`，期望 `ValidationError`。

- [ ] **Step 2: 实现 source contracts**

核心字段固定为：

```python
class SourceFieldProfile(StrictContractModel):
    name: str
    physical_type: str
    nullable: bool = True
    unique_ratio: float = 0.0
    null_ratio: float = 0.0
    samples: tuple[str, ...] = ()

class SourceGeometryFieldProfile(StrictContractModel):
    name: str
    geometry_kinds: tuple[str, ...]
    crs_refs: tuple[str, ...] = ()

class SourceFeatureRecord(StrictContractModel):
    source_record_ref: str
    collection_ref: str
    source_feature_id: str
    attributes_ref: str
    geometry_refs: tuple[str, ...] = ()
    content_digest: str
```

- [ ] **Step 3: 实现 entity 和 representation contracts**

```python
class WorldEntity(StrictContractModel):
    entity_ref: str
    concept_refs: tuple[str, ...]
    canonical_name: str = ""
    aliases: tuple[str, ...] = ()
    lifecycle_state: Literal["observed", "planned", "superseded"] = "observed"

class SpatialRepresentation(StrictContractModel):
    representation_ref: str
    entity_ref: str
    geometry_ref: str
    role: str
    geometry_kind: str
    crs: str
    authority: str
    valid_time: str = ""
    source_record_refs: tuple[str, ...] = ()
    derived_from_refs: tuple[str, ...] = ()
    status: Literal["proposed", "accepted", "rejected", "superseded"]
```

- [ ] **Step 4: 实现 assertion 和 snapshot contracts**

Assertion 必须保存 subject/predicate/object-or-value、source refs、decision ref、status 和 confidence。Snapshot 必须保存 source catalog、semantic mapping、entity resolution、parent world model 和 changeset digests。

- [ ] **Step 5: 运行契约测试**

Run: `cd backend && python -m pytest tests/cognition/test_core_contracts.py -v`

Expected: PASS；未知 Bundle 字段被 `extra='forbid'` 拒绝。

- [ ] **Step 6: Commit**

```bash
git add backend/app/contracts/cognition backend/tests/cognition/test_core_contracts.py
git commit -m "feat: add cognition world model contracts"
```

---

### Task 3: 建立查询、变更集和端口契约

**Files:**
- Create: `backend/app/contracts/cognition/query.py`
- Create: `backend/app/contracts/cognition/changeset.py`
- Create: `backend/app/contracts/cognition/ports.py`
- Modify: `backend/app/contracts/ports/planning_ports.py`
- Test: `backend/tests/cognition/test_query_and_port_contracts.py`

**Interfaces:**
- Consumes: Task 2 contracts。
- Produces: `EntityQuery`、`RepresentationRequirement`、`WorldModelChangeSet`、`WorldModelQueryPort`、`WorldModelCommitPort`、`SourceCatalogPort`、`GeometryStorePort`。

- [ ] **Step 1: 写 query contract 测试**

测试以下查询可序列化并具有稳定 fingerprint：

```python
query = EntityQuery(
    query_text="连接金田村委会的现状道路",
    required_capabilities=("network_edge",),
    names=("金田村委会",),
    relation_filters=(
        RelationFilter(predicate="connectedTo", object_ref="entity://place/jintian"),
    ),
    limit=20,
)
```

测试 `RepresentationRequirement(purpose="network-routing", roles=("network_centerline",), geometry_kinds=("LineString", "MultiLineString"))` 不包含 source layer。

- [ ] **Step 2: 实现 query contracts**

提供 `SpatialFilter`、`RelationFilter`、`EntityQuery`、`RepresentationRequirement`、`EntityCandidate`、`EntityQueryResult`、`RepresentationQueryResult` 和 `SourceTraceResult`。所有 tuple 在 validator 中去重排序，fingerprint 使用 canonical JSON SHA-256。

- [ ] **Step 3: 实现 changeset contracts**

```python
class WorldModelChangeSet(StrictContractModel):
    changeset_id: str
    session_id: str
    parent_world_model_digest: str
    source_catalog_digest: str
    assertions: tuple[SemanticAssertion, ...] = ()
    entities: tuple[WorldEntity, ...] = ()
    representations: tuple[SpatialRepresentation, ...] = ()
    relations: tuple[WorldRelation, ...] = ()
    target_graph: Literal["assertion", "world", "intent", "planned"]
    fingerprint: str = ""
```

- [ ] **Step 4: 实现 ports 并注入 PlanningPorts**

`PlanningPorts` 新增可选字段：

```python
source_catalog: SourceCatalogPort | None = None
world_model_query: WorldModelQueryPort | None = None
world_model_commit: WorldModelCommitPort | None = None
geometry_store: GeometryStorePort | None = None
representation_selection: RepresentationSelectionPort | None = None
```

- [ ] **Step 5: 运行测试**

Run: `cd backend && python -m pytest tests/cognition/test_query_and_port_contracts.py -v`

Expected: PASS；两次构造等价 query 得到相同 fingerprint。

- [ ] **Step 6: Commit**

```bash
git add backend/app/contracts/cognition backend/app/contracts/ports/planning_ports.py backend/tests/cognition
git commit -m "feat: define world model query and commit ports"
```

---

### Task 4: 实现无损 Source Catalog 与 Bundle 输入适配

**Files:**
- Create: `backend/app/data/source_catalog/__init__.py`
- Create: `backend/app/data/source_catalog/readers.py`
- Create: `backend/app/data/source_catalog/profiler.py`
- Create: `backend/app/data/source_catalog/attribute_store.py`
- Create: `backend/app/data/source_catalog/geometry_store.py`
- Create: `backend/app/data/source_catalog/repository.py`
- Create: `backend/app/data/source_catalog/bundle_adapter.py`
- Modify: `backend/app/data/model/snapshot.py`
- Modify: `backend/app/data/snapshots/snapshot_service.py`
- Test: `backend/tests/data/test_source_catalog.py`
- Test: `backend/tests/data/test_bundle_source_adapter.py`

**Interfaces:**
- Consumes: `SourceCatalogPort` 和 Task 2 source contracts。
- Produces: `SourceCatalogSnapshot`、完整 raw attributes、零到多个 geometry refs、V1 Bundle→V2 source adapter。

- [ ] **Step 1: 写任意字段和多几何测试**

输入记录包含：

```python
record = {
    "id": "road-17",
    "道路俗名": "东环村道",
    "任意指标_X9": 12.5,
    "中心线": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]},
    "控制范围": {"type": "Polygon", "coordinates": [[[0, -1], [1, -1], [1, 1], [0, -1]]]},
}
```

断言属性 store 可原样取回两个业务字段，SourceFeatureRecord 有两个不同 geometry refs，profile 包含两个 geometry field。

- [ ] **Step 2: 实现 attribute/geometry store**

先提供 session-scoped in-memory + CAS JSON implementation。`put()` 以 canonical digest 生成 ref；`get()` 找不到 ref 时抛 `LookupError`，不返回空字典或空 geometry。

- [ ] **Step 3: 实现 profiler 和 reader protocol**

`SourceReader` 提供 `list_collections()`、`profile_collection()`、`iter_records()`。GeoJSON adapter 不要求固定 property；geometry 之外的每个 key 都进入 attribute store。对明确配置的多个 geometry fields 分别写 geometry store。

- [ ] **Step 4: 实现 BundleSourceAdapter**

遍历 Bundle 的所有动态 group keys，而不是固定列表；每个 V1 feature 建立 source record。BSM 写入 raw attribute 和 `SourceIdentifier(kind="legacy_bsm")`，不转成 entity ID。

- [ ] **Step 5: 为 SessionDataSnapshot 增加通用入口**

新增：

```python
@classmethod
def from_source_catalog(
    cls,
    catalog: SourceCatalogSnapshot,
    *,
    session_id: str,
) -> "SessionDataSnapshot": ...
```

`from_bundle()` 保留为调用 BundleSourceAdapter 的兼容入口；新入口的 digest 覆盖所有 Collection、field profile、attribute digest 和 geometry digest。

- [ ] **Step 6: 运行数据测试**

Run: `cd backend && python -m pytest tests/data/test_source_catalog.py tests/data/test_bundle_source_adapter.py -v`

Expected: PASS；随机字段未丢失；未知 Collection 保留原 collection ref；没有默认 polygons 分组。

- [ ] **Step 7: Commit**

```bash
git add backend/app/data/source_catalog backend/app/data/model/snapshot.py backend/app/data/snapshots/snapshot_service.py backend/tests/data
git commit -m "feat: add lossless dynamic source catalog"
```

---

### Task 5: 实现 World Model store、图分区和原子提交

**Files:**
- Create: `backend/app/infrastructure/cognition_runtime/__init__.py`
- Create: `backend/app/infrastructure/cognition_runtime/transaction.py`
- Create: `backend/app/infrastructure/cognition_runtime/rdflib_store.py`
- Create: `backend/app/infrastructure/cognition_runtime/repository.py`
- Modify: `backend/app/infrastructure/kg/manager.py`
- Modify: `backend/app/infrastructure/kg/spatial_store.py`
- Test: `backend/tests/cognition/test_world_model_transaction.py`
- Test: `backend/tests/cognition/test_multi_representation_store.py`

**Interfaces:**
- Consumes: `WorldModelChangeSet`、query/commit ports、geometry refs。
- Produces: 原子 `commit()`、source/assertion/world/intent/planned graph、entity→many representations query。

- [ ] **Step 1: 写 transaction 原子性测试**

提交一个合法 changeset 后记录 digest；再提交含未知 representation entity_ref 的 changeset，期望 `WorldModelCommitError`，并断言 store 的 version 和 digest 未变化。

- [ ] **Step 2: 写多表示查询测试**

一个 PlaceEntity 关联 locator Point、physical extent Polygon 和 administrative extent MultiPolygon；`get_representations(entity_ref, requirement)` 分别返回匹配 role，不依赖插入顺序。

- [ ] **Step 3: 实现 RDF named graph mapping**

使用固定 graph refs：

```python
SOURCE_GRAPH = URIRef("urn:planning:graph:source")
ASSERTION_GRAPH = URIRef("urn:planning:graph:assertion")
WORLD_GRAPH = URIRef("urn:planning:graph:world")
INTENT_GRAPH = URIRef("urn:planning:graph:intent")
PLANNED_GRAPH = URIRef("urn:planning:graph:planned")
```

Entity 与 Representation 是独立 node；`hasRepresentation` 关联二者；geometry literal/storage ref 只属于 Representation。

- [ ] **Step 4: 实现 commit validation**

提交前验证 parent digest、source digest、所有 foreign refs、assertion candidate membership、representation geometry ref 和 graph target；在临时 Dataset 完成写入并计算 digest，成功后一次替换 session snapshot。

- [ ] **Step 5: 改造 spatial store projection**

保留 `SpatialKGEntity` 兼容类，新增 `SpatialRepresentationRow`；PostGIS/RDF index 按 representation 单独索引，不再把单一 `geometry_wkt` 当 Entity 属性。

- [ ] **Step 6: 运行存储测试**

Run: `cd backend && python -m pytest tests/cognition/test_world_model_transaction.py tests/cognition/test_multi_representation_store.py -v`

Expected: PASS；失败 changeset 无部分写；三种表示均可回查。

- [ ] **Step 7: Commit**

```bash
git add backend/app/infrastructure/cognition_runtime backend/app/infrastructure/kg/manager.py backend/app/infrastructure/kg/spatial_store.py backend/tests/cognition
git commit -m "feat: add transactional multi-representation world model"
```

---

### Task 6: 实现动态 Schema understanding 与可审计 LLM 决策

**Files:**
- Create: `backend/app/modules/cognition/__init__.py`
- Create: `backend/app/modules/cognition/schema_understanding.py`
- Create: `backend/app/modules/cognition/validation.py`
- Create: `backend/app/infrastructure/cognition_runtime/schema_matcher.py`
- Create: `backend/app/contracts/cognition/decision.py`
- Test: `backend/tests/cognition/test_schema_understanding.py`
- Test: `backend/tests/cognition/test_schema_llm_membership.py`

**Interfaces:**
- Consumes: `SourceCollectionProfile`、ontology concept/property candidate index、现有 structured LLM runtime。
- Produces: `SourceSemanticMappingSnapshot`，状态为 accepted/ambiguous/unresolved/rejected。

- [ ] **Step 1: 写 deterministic known-profile 测试**

字段 `DLBM` 在 value/encoding validator 证实属于受支持编码时可以生成 accepted mapping；同名字段值域完全不兼容时不得仅凭字段名接受。

- [ ] **Step 2: 写 LLM closed-set 测试**

fake provider 返回不存在的 `candidate_property_ref`，verifier 必须把 decision 记为 rejected，且 accepted mapping 为空。provider 返回 `None` 时状态为 unresolved，不抛成系统失败。

- [ ] **Step 3: 实现 candidate retrieval**

按 field name/description、physical type、value samples、geometry profile 和 known registry 召回最多 12 个 property candidates；Collection role 最多 8 个 concept candidates。候选排序稳定并保存 candidate digest。

- [ ] **Step 4: 实现 structured LLM transaction**

输出 schema：

```python
class SchemaMappingProposal(StrictContractModel):
    collection_ref: str
    field_name: str
    candidate_property_ref: str | None
    candidate_concept_ref: str | None
    representation_role_ref: str | None
    confidence: float
```

逐项验证 collection、field 和 candidate membership；禁止自由文本 property ID。

- [ ] **Step 5: 实现 snapshot persistence**

保存 source/profile/candidate/input/raw-output digest、prompt version、model id、validator findings 和 decisions；相同输入可重放得到相同 normalized decision fingerprint。

- [ ] **Step 6: 运行测试**

Run: `cd backend && python -m pytest tests/cognition/test_schema_understanding.py tests/cognition/test_schema_llm_membership.py -v`

Expected: PASS；未知字段可 unresolved；raw attribute 仍可查询。

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/cognition backend/app/infrastructure/cognition_runtime/schema_matcher.py backend/app/contracts/cognition/decision.py backend/tests/cognition
git commit -m "feat: add audited dynamic schema understanding"
```

---

### Task 7: 实现实体解析、道路部件和多表示装配

**Files:**
- Create: `backend/app/modules/cognition/entity_resolution.py`
- Create: `backend/app/modules/cognition/representation_assembly.py`
- Create: `backend/app/modules/cognition/topology_assembly.py`
- Create: `backend/app/infrastructure/cognition_runtime/entity_matcher.py`
- Test: `backend/tests/cognition/test_entity_resolution.py`
- Test: `backend/tests/cognition/test_road_part_assembly.py`
- Test: `backend/tests/cognition/test_place_multi_representation.py`

**Interfaces:**
- Consumes: source records、semantic mappings、existing world entities、geometry/topology operations。
- Produces: `EntityResolutionSnapshot` 与待提交的 entities/representations/relations/assertions。

- [ ] **Step 1: 写身份解析矩阵测试**

覆盖：同权威 ID 合并候选、同名异地不合并、近邻但道路编号冲突不合并、信息不足 ambiguous、撤销 accepted assertion 后 cluster 可重建。

- [ ] **Step 2: 写道路分段测试**

三个端点连续、名称与道路编号兼容的 LineString 记录应产生一个 RoadEntity、三个 RoadSegment entity、三条 `partOf` 和一个 derived MultiLine representation。把中间线段道路编号改为另一编号后，它必须进入不同 cluster 或 ambiguous。

- [ ] **Step 3: 写地点多表示测试**

不同 Collection 中同一权威地点 ID 的 Point、Polygon 和 MultiPolygon 记录应产生一个 PlaceEntity 与三个 representation；source record 数量保持三个，不发生源记录融合。

- [ ] **Step 4: 实现 blocking**

按 authoritative identifier、admin-scoped code、concept-compatible name、bbox distance、topology 和 valid time 形成 candidate groups。每组保存 blocking reasons，组大小超过配置上限时按空间 tile 分片而不是截断后自动选择。

- [ ] **Step 5: 实现 LLM group matching 与图一致性**

LLM 只引用 source_record_ref/existing entity_ref，输出 same_entity/part_of/different/ambiguous/abstain。确定性阶段检查一对多冲突、concept disjointness、时间冲突、道路拓扑和权威 ID 冲突。

- [ ] **Step 6: 实现 representation/topology assembly**

源 geometry 生成 source-backed representation；聚合 geometry 生成 derived representation 并保存 members、method、tolerance 和 CRS。Entity ID 只由 `IdentityService` 在 accepted cluster commit 时生成。

- [ ] **Step 7: 运行测试**

Run: `cd backend && python -m pytest tests/cognition/test_entity_resolution.py tests/cognition/test_road_part_assembly.py tests/cognition/test_place_multi_representation.py -v`

Expected: PASS；道路和地点场景满足设计中的实体/表示数量。

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/cognition backend/app/infrastructure/cognition_runtime/entity_matcher.py backend/tests/cognition
git commit -m "feat: resolve entities and assemble spatial representations"
```

---

### Task 8: 建立 Session cognition bootstrap 并解除全局 Bundle/landuse gate

**Files:**
- Create: `backend/app/modules/cognition/application.py`
- Create: `backend/app/modules/cognition/projections.py`
- Modify: `backend/app/infrastructure/context_runtime/runtime.py`
- Modify: `backend/app/infrastructure/context_runtime/manager.py`
- Modify: `backend/app/workflow/layers/context_bootstrap.py`
- Modify: `backend/app/bootstrap/composition.py`
- Modify: `backend/app/core/settings.py`
- Modify: `.env.example`
- Test: `backend/tests/cognition/test_cognition_bootstrap.py`
- Test: `backend/tests/cognition/test_capability_gate.py`

**Interfaces:**
- Consumes: SourceCatalog、schema mapping、entity resolution、WorldModelCommitPort。
- Produces: `SessionWorldModelSnapshot`、精简 `PlanningContext` refs、`CapabilitySnapshot`。

- [ ] **Step 1: 写无 Bundle bootstrap 测试**

只注册一个未知名称的道路 GeoJSON Collection，不创建 VillageBundle、不提供 BSM；执行 bootstrap 后断言 world-model snapshot 存在、source record 数正确、`network_edge` capability 根据 accepted cognition 决定，且没有 `landuse_current` 全局错误。

- [ ] **Step 2: 实现 CognitionApplication.bootstrap**

```python
async def bootstrap(
    self,
    session_id: str,
    source_snapshot_ref: str,
    *,
    previous_world_model_ref: str = "",
) -> SessionWorldModelSnapshot: ...
```

按 source→schema→entity→representation→commit 顺序执行；每一步返回 artifact ref 和 digest。普通 unresolved mapping 不阻断 source/world snapshot 提交。

- [ ] **Step 3: 实现 CapabilitySnapshot**

能力从 accepted concepts、representation roles、可用 spatial operations 和 solver requirements 计算。`parcel_assignment` 需要 candidate_site extent + resource identity；`network_path` 需要 connected network representations。

- [ ] **Step 4: 精简 PlanningContext**

新增 source/world snapshot refs、digests 和 capability snapshot；V2 模式下 ports 是权威。`workspace`、`kg`、`evidence_graph` 只留 compatibility property，并在 `v2_only` 访问时抛 `LegacyContextAccessError`。

- [ ] **Step 5: 修改 workflow bootstrap**

`context_bootstrap_node` 先冻结 SourceCatalog，再调用 CognitionApplication；只有 source snapshot/commit/digest 错误或当前阶段 required capability 缺失时失败。Bundle build 只在 `off/shadow` 或 compat materialization 开启时运行。

- [ ] **Step 6: 运行测试**

Run: `cd backend && python -m pytest tests/cognition/test_cognition_bootstrap.py tests/cognition/test_capability_gate.py -v`

Expected: PASS；无地块输入可以形成世界模型，parcel solver capability 明确为 false。

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/cognition backend/app/infrastructure/context_runtime backend/app/workflow/layers/context_bootstrap.py backend/app/bootstrap/composition.py backend/app/core/settings.py .env.example backend/tests/cognition
git commit -m "feat: bootstrap session world model from source catalog"
```

---

### Task 9: 重构实体/来源双平面检索与 Evidence Packet V2

**Files:**
- Create: `backend/app/contracts/evidence/cognition_packet_contracts.py`
- Create: `backend/app/infrastructure/cognition_runtime/indexes/entity_name.py`
- Create: `backend/app/infrastructure/cognition_runtime/indexes/entity_property.py`
- Create: `backend/app/infrastructure/cognition_runtime/indexes/source_attribute.py`
- Create: `backend/app/infrastructure/cognition_runtime/indexes/representation.py`
- Create: `backend/app/infrastructure/cognition_runtime/indexes/topology.py`
- Create: `backend/app/infrastructure/cognition_runtime/indexes/provenance.py`
- Create: `backend/app/infrastructure/evidence_runtime/world_model_retriever.py`
- Modify: `backend/app/modules/evidence/application.py`
- Modify: `backend/app/infrastructure/evidence_runtime/query_planner.py`
- Modify: `backend/app/infrastructure/evidence_runtime/facade.py`
- Create: `backend/app/data/compatibility/legacy_evidence_adapter.py`
- Test: `backend/tests/evidence/test_world_model_retrieval.py`
- Test: `backend/tests/evidence/test_raw_attribute_retrieval.py`
- Test: `backend/tests/evidence/test_provider_independence.py`

**Interfaces:**
- Consumes: WorldModelQueryPort、SourceCatalogPort、现有 text/report/RAG/external providers。
- Produces: `CognitionEvidencePacket`，V1 `FeatureEvidenceRef` 只由 adapter 生成。

- [ ] **Step 1: 写 provider independence 测试**

构造业务 `EvidenceRequirement`，断言编译结果只包含 `WorldModelQuery`/`SourceEvidenceQuery`，序列化内容不含 `bundle`、`kg`、`roads_current`。Infrastructure plan 可以选择内部 providers，但不得回写业务 contract。

- [ ] **Step 2: 写 entity-first retrieval 测试**

同一 PlaceEntity 有三个 source records 和三个 representations；名称查询只返回一个 entity candidate，packet 同时列出三个 source refs 和满足 requirement 的 representation candidates。

- [ ] **Step 3: 写 raw attribute 查询测试**

对未映射字段 `任意指标_X9=12.5` 查询，packet 标记 `raw_property_match`；该结果不能单独满足 `authority='statutory'` requirement。

- [ ] **Step 4: 实现独立索引**

每个索引以 world/source snapshot digest 构建，不修改实体或 assertion。EntityNameIndex 返回 refs；RepresentationIndex 返回表示 metadata；Geometry body 仍由 GeometryStorePort 按需读取。

- [ ] **Step 5: 实现 Evidence Packet V2**

Canonical 字段为 world/source snapshot refs、entity/representation candidates、assertion/source refs、relations、coverage、sufficiency、cursor 和 query trace。删除 V2 中的 BSM/Bundle authority 字段。

- [ ] **Step 6: 接入 EvidenceFacade**

新增：

```python
async def retrieve_cognition(
    self,
    requirement: EvidenceRequirement | Iterable[EvidenceRequirement],
    context: EvidenceContext,
    *,
    entity_query: EntityQuery | None = None,
    representation_requirement: RepresentationRequirement | None = None,
) -> CognitionEvidencePacket: ...
```

V1 `retrieve()` 在 off/shadow 模式保持；legacy adapter 显式记录 compatibility finding。

- [ ] **Step 7: 运行测试**

Run: `cd backend && python -m pytest tests/evidence/test_world_model_retrieval.py tests/evidence/test_raw_attribute_retrieval.py tests/evidence/test_provider_independence.py -v`

Expected: PASS；实体和来源没有被错误折叠；业务 request 无 provider 名称。

- [ ] **Step 8: Commit**

```bash
git add backend/app/contracts/evidence backend/app/infrastructure/cognition_runtime/indexes backend/app/infrastructure/evidence_runtime backend/app/modules/evidence/application.py backend/app/data/compatibility backend/tests/evidence
git commit -m "feat: query evidence through entity and source planes"
```

---

### Task 10: 重写 GROUND 为实体选择、表示选择和候选域装配

**Files:**
- Create: `backend/app/modules/ground/request_compiler.py`
- Create: `backend/app/modules/ground/entity_grounder.py`
- Create: `backend/app/modules/ground/representation_selector.py`
- Create: `backend/app/modules/ground/relation_grounder.py`
- Create: `backend/app/modules/ground/constraint_evaluator.py`
- Create: `backend/app/modules/ground/candidate_domain_assembler.py`
- Create: `backend/app/modules/ground/recovery.py`
- Modify: `backend/app/modules/ground/application.py`
- Modify: `backend/app/modules/ground/ports.py`
- Modify: `backend/app/modules/ground/validation.py`
- Modify: `backend/app/contracts/ground/spatial_reference_contracts.py`
- Modify: `backend/app/contracts/ground/grounded_problem.py`
- Create: `backend/app/spatial/representation_selection.py`
- Test: `backend/tests/ground/test_entity_grounder.py`
- Test: `backend/tests/ground/test_representation_selection.py`
- Test: `backend/tests/ground/test_ground_recovery.py`
- Test: `backend/tests/architecture/test_ground_has_no_runtime_dependencies.py`

**Interfaces:**
- Consumes: EvidenceFacade V2、WorldModelQueryPort、RepresentationSelectionPort、SpatialOperationPort。
- Produces: V2 `GroundedEntityBindingSnapshot`、含 entity/representation/resource refs 的 `GroundedPlanningProblem`。

- [ ] **Step 1: 写表示选择排序测试**

同一地点有 locator Point、accepted legal extent Polygon、proposed service extent Polygon。`purpose='statutory-overlap'` 选择 accepted legal extent；`purpose='map-label'` 选择 locator。插入顺序变化结果不变。

- [ ] **Step 2: 写道路 Ground 测试**

目标要求 `network_path`，候选道路整体有 derived MultiLine 和三个 segment centerline。Ground 返回 RoadEntity 和 network representation refs，不要求 parcel BSM。

- [ ] **Step 3: 写恢复状态测试**

第一轮 entity ambiguous；Cognition commit 新 accepted assertion 并产生新 world-model digest；第二轮只重跑未闭合 subject 并转为 grounded。若 digest 与 candidate set 都不变，恢复循环提前停止。

- [ ] **Step 4: 实现 request compiler 和 entity grounder**

`GroundingRequest` 编译为 EntityQuery + RepresentationRequirement；LLM 只在 EntityQueryResult candidate refs 中选择。Ground 不调用 entity resolution commit，也不合并 source records。

- [ ] **Step 5: 实现 deterministic RepresentationSelectionService**

排序键依次包含 role compatibility、accepted、authority、valid time、geometry kind、CRS、accuracy、topology completeness、derived penalty 和 ref。无满足项返回 typed `missing_representation_capability`。

- [ ] **Step 6: 实现 relation/constraint/candidate assembler**

空间运算通过 representation ref 加载 geometry；输出 binding 必须含 entity_ref、representation_ref、world-model snapshot、source/assertion refs。Parcel adapter 可以附 legacy BSM alias，但 core resource_ref 不得由 BSM 生成。

- [ ] **Step 7: 收缩 application orchestration**

`application.py` 只编排两个入口、artifact load/store 和 bounded recovery；移除直接 EvidenceGraph、BindingStore、ObservationStore 和 PlanningContext.kg/workspace 访问。V1 实现暂时移动到 `data/compatibility` adapter，不在新 application 内混排条件分支。

- [ ] **Step 8: 运行 Ground 测试和依赖测试**

Run:

```bash
cd backend
python -m pytest tests/ground tests/architecture/test_ground_has_no_runtime_dependencies.py -v
python ../scripts/acceptance/ground_current_session_probe.py --help
```

Expected: 单元测试 PASS；Ground package 不导入 KGManager、EvidenceGraph、VillageBundle；probe CLI 可导入。

- [ ] **Step 9: Commit**

```bash
git add backend/app/modules/ground backend/app/contracts/ground backend/app/spatial/representation_selection.py backend/tests/ground backend/tests/architecture
git commit -m "refactor: ground entities and purpose-specific representations"
```

---

### Task 11: 迁移 L2 与 SELECT 到 capability/resource refs

**Files:**
- Modify: `backend/app/modules/l2/suitability_spatial_factors.py`
- Modify: `backend/app/modules/l2/suitability_terrain_adapter.py`
- Modify: `backend/app/modules/l2/suitability.py`
- Modify: `backend/app/modules/select/refined_candidate_catalog.py`
- Modify: `backend/app/modules/select/parcel_assignment_backend.py`
- Modify: `backend/app/modules/select/global_site_select.py`
- Modify: `backend/app/modules/select/global_zone_select.py`
- Modify: `backend/app/contracts/ground/candidate_geometry.py`
- Modify: `backend/app/contracts/ground/grounded_problem.py`
- Test: `backend/tests/cognition/test_l2_capability_queries.py`
- Test: `backend/tests/ground/test_select_resource_refs.py`

**Interfaces:**
- Consumes: Ground V2 candidate domains、WorldModelQueryPort、Representation refs。
- Produces: 不依赖固定 layer/BSM 的 suitability factor inputs 与 SELECT resource ledger。

- [ ] **Step 1: 写 L2 layer-name independence 测试**

使用随机 Collection 名构建 accepted `network_edge`、`service_origin`、`prohibited_overlap` entities；L2 因子必须通过 capability query 找到它们，源码和 query trace 不出现 `roads_current`、`facilities_current`、`hazard_points`。

- [ ] **Step 2: 写 SELECT resource 测试**

候选资源以 `resource_ref` 和 `representation_ref` 唯一标识；两个候选共享同一资源时 capacity ledger 检测冲突。Legacy BSM alias 缺失不能让非 parcel solver 失败。

- [ ] **Step 3: 改造 L2 factor provider**

将固定 workspace layer 读取替换为声明式 factor definitions：concept/capability query + representation purpose + spatial operation。法定约束只接受 accepted legal extent。

- [ ] **Step 4: 改造 Ground candidate/resource contracts**

新增 `resource_ref`、`entity_ref`、`representation_ref`、`source_record_refs`、`assertion_refs` 和 world-model ref；`source_bsms` 标记 deprecated compatibility alias，不参与 fingerprint 的 canonical identity。

- [ ] **Step 5: 改造 SELECT adapters**

通用 solver 使用 resource refs。`parcel_assignment_backend` 单独调用 `ParcelSourceIdentifierAdapter` 获取来源 parcel ID；没有该 alias 时返回 capability finding，而不是让所有 SELECT 路径失败。

- [ ] **Step 6: 运行测试**

Run: `cd backend && python -m pytest tests/cognition/test_l2_capability_queries.py tests/ground/test_select_resource_refs.py -v`

Expected: PASS；道路和设施候选不需要 BSM；parcel solver 对缺 alias fail-closed。

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/l2 backend/app/modules/select backend/app/contracts/ground backend/tests/cognition backend/tests/ground
git commit -m "refactor: consume world capabilities and resource references"
```

---

### Task 12: 迁移 TARGET_PROJECTION、EXECUTE 和 planned graph 提交

**Files:**
- Modify: `backend/app/modules/target_projection/requirement_compilation.py`
- Modify: `backend/app/modules/target_projection/stage.py`
- Modify: `backend/app/modules/target_projection/ports.py`
- Modify: `backend/app/modules/execute/stage.py`
- Modify: `backend/app/modules/execute/ports.py`
- Modify: `backend/app/modules/execute/workers/write_l4.py`
- Modify: `backend/app/modules/execute/workers/route_prepare.py`
- Modify: `backend/app/modules/execute/road_generator.py`
- Create: `backend/app/modules/execute/world_changeset_builder.py`
- Test: `backend/tests/cognition/test_intent_graph_commit.py`
- Test: `backend/tests/cognition/test_planned_graph_commit.py`
- Test: `backend/tests/architecture/test_business_modules_do_not_import_kg.py`

**Interfaces:**
- Consumes: WorldModelCommitPort、Ground V2、ApprovedExecutionInput。
- Produces: intent/planned `WorldModelChangeSet` 和对应 snapshot refs。

- [ ] **Step 1: 写 intent commit 测试**

TARGET_PROJECTION 编译 planning target 为 intent entity + EntityQuery + RepresentationRequirement；提交到 intent graph。测试 monkeypatch KG builder 为抛错，流程仍通过 port 成功，证明没有直接调用 `build_intent_layer`。

- [ ] **Step 2: 写 planned graph 原子性测试**

EXECUTE 产生计划道路 entity、segment parts、centerline representations 和 relations。任何 worker 输出缺 approval/ground lineage 时整个 planned changeset 拒绝，不增加 world-model version。

- [ ] **Step 3: 改造 TARGET_PROJECTION**

删除 `EvidenceFacade.install_intent_layer()` 使用；stage 只构建和提交 intent changeset。复杂空间要求进入 representation purpose，不包含固定图层或 BSM。

- [ ] **Step 4: 改造 EXECUTE workers**

worker 返回 typed planned entity/representation/relation fragment；`world_changeset_builder` 聚合、查重和验证。只有 stage 在 approval validation 后调用一次 commit port。

- [ ] **Step 5: 删除业务模块 KG imports**

移除 execute 对 `require_session_kg`、`KGManager`、`builder.layer3/layer4`、`EntityTypes/PLN` 的直接导入；route preparation 通过 WorldModelQueryPort 获取已 Ground 路网表示。

- [ ] **Step 6: 运行测试**

Run: `cd backend && python -m pytest tests/cognition/test_intent_graph_commit.py tests/cognition/test_planned_graph_commit.py tests/architecture/test_business_modules_do_not_import_kg.py -v`

Expected: PASS；modules/target_projection 和 modules/execute 无 infrastructure.kg import。

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/target_projection backend/app/modules/execute backend/tests/cognition backend/tests/architecture
git commit -m "refactor: commit intent and planned state through world model ports"
```

---

### Task 13: 交付物化、shadow diff 和兼容退场

**Files:**
- Create: `backend/app/data/compatibility/bundle_materializer.py`
- Create: `backend/app/contracts/cognition/shadow_diff.py`
- Create: `backend/app/infrastructure/cognition_runtime/shadow_compare.py`
- Modify: `backend/app/workflow/delivery/delivery_snapshot_builder.py`
- Modify: `backend/app/workflow/delivery/render_layers.py`
- Modify: `backend/app/infrastructure/context_runtime/manager.py`
- Modify: `backend/app/application/sessions/session_bundle.py`
- Test: `backend/tests/cognition/test_shadow_diff.py`
- Test: `backend/tests/data/test_bundle_materializer.py`

**Interfaces:**
- Consumes: World-model snapshots、V1/V2 query/Ground results。
- Produces: `CognitionShadowDiff` artifact、可追溯 legacy Bundle/GeoJSON 输出、V2-only runtime。

- [ ] **Step 1: 写 shadow diff 测试**

比较维度固定为 entity candidates、selected entity、selected representation、source lineage、ambiguity、constraint result。V1 BSM 与 V2 entity_ref 不直接比较字符串，而通过 compatibility source identifier mapping 对齐。

- [ ] **Step 2: 写 Bundle materialization 测试**

从 world model 的 accepted/planned representations 输出 legacy GeoJSON keys；每个输出 feature properties 包含 `entity_ref`、`representation_ref`、`world_model_digest` 和 source refs。没有 BSM 时 materializer 生成 output-local ID，并明确 `id_scope='delivery'`。

- [ ] **Step 3: 接入 shadow 模式**

shadow 运行 V1 和 V2 query/Ground，只提交 V1 业务结果，同时持久化 diff。V2 provider failure 不改变 V1；diff artifact 必须记录 failure 而不是缺席。

- [ ] **Step 4: 接入 prefer_v2/v2_only**

prefer_v2 以 V2 为权威，对缺 capability 返回 typed unresolved；只有显式 compatibility allowlist 能执行 V1 adapter。v2_only 不构建 Bundle、不创建 EvidenceGraph、不调用 `ensure_session_kg(build_from_bundle)`。

- [ ] **Step 5: 迁移 delivery**

Delivery 从 representation registry 查询 current/planned outputs，按 materializer profile 渲染。固定 `landuse_current_geojson` 仅属于 legacy profile。

- [ ] **Step 6: 运行测试**

Run: `cd backend && python -m pytest tests/cognition/test_shadow_diff.py tests/data/test_bundle_materializer.py -v`

Expected: PASS；legacy 输出可追溯；v2_only path 不访问 Bundle cache。

- [ ] **Step 7: Commit**

```bash
git add backend/app/data/compatibility backend/app/contracts/cognition backend/app/infrastructure/cognition_runtime backend/app/workflow/delivery backend/app/infrastructure/context_runtime/manager.py backend/app/application/sessions/session_bundle.py backend/tests
git commit -m "feat: materialize compatibility outputs from world model"
```

---

### Task 14: 建立端到端泛用性验收并移除 legacy allowlist

**Files:**
- Create: `backend/tests/e2e/test_dynamic_gis_world_model.py`
- Create: `backend/tests/e2e/test_road_segments_and_place_representations.py`
- Create: `backend/tests/e2e/test_ground_world_model_only.py`
- Modify: `scripts/acceptance/business_stage_boundary_probe.py`
- Modify: `scripts/acceptance/ground_current_session_probe.py`
- Modify: `docs/design/05_MIGRATION.md`
- Modify: `docs/architecture/CURRENT_RUNTIME.md`
- Modify: `backend/tests/architecture/legacy_dependency_allowlist.txt`

**Interfaces:**
- Consumes: 完整 V2 vertical slice。
- Produces: V2-only release evidence、清空的关键依赖 allowlist、更新后的 current/migration authority。

- [ ] **Step 1: 写动态 Schema E2E**

测试随机 layer/field 名、任意 scalar 属性、混合 Point/Line/Polygon Collection 和两个 geometry fields。断言 source record 全保留、semantic unresolved 不丢数据、accepted mapping 可被 entity query 使用。

- [ ] **Step 2: 写道路/地点 E2E**

同一输入同时包含：三段道路组成一条路；一个地点在不同 Collection 中有定位点和两个面；一个同名异地地点。断言实体、部件、表示、ambiguity 和 source lineage 数量准确。

- [ ] **Step 3: 写 World-Model-only Ground E2E**

设置 `COGNITION_WORLD_MODEL_MODE=v2_only`，monkeypatch Bundle/KG V1 entrypoints 为抛错，运行 L1 location binding 和 planning target grounding。输出必须包含 entity/representation/world refs，并能构造 SELECT diagnostic 或 scenario input。

- [ ] **Step 4: 更新 acceptance probes**

将 `business_stage_boundary_probe.py` 中“所有 requirement 必须含 bundle source family”的断言替换为：业务 requirement 无 provider 名称、packet 含 world/source snapshot、Ground binding 含 entity/representation refs。`ground_current_session_probe.py` 增加 world-model reload 和 lineage 验证。

- [ ] **Step 5: 清空关键 allowlist**

删除 Data→KG/Evidence、Ground→KG/EvidenceGraph、Spatial→EvidenceGraph、Execute→KGManager 的 allowlist 行。剩余兼容 import 必须只位于 `data/compatibility` 或 bootstrap composition。

- [ ] **Step 6: 运行完整验证**

Run:

```bash
cd backend
python -m pytest tests/architecture tests/cognition tests/data tests/evidence tests/ground -v
python -m pytest tests/e2e/test_dynamic_gis_world_model.py tests/e2e/test_road_segments_and_place_representations.py tests/e2e/test_ground_world_model_only.py -v
python -m compileall -q app
cd ..
python scripts/acceptance/business_stage_boundary_probe.py
git diff --check
```

Expected: 全部 PASS；V2-only 测试不访问 Bundle/KG V1；dependency allowlist 不含四类关键违规。

- [ ] **Step 7: 更新权威状态文档**

`05_MIGRATION.md` 只记录每个 M 阶段的 CURRENT/PARTIAL/GAP 状态和 fresh-run evidence；`CURRENT_RUNTIME.md` 只写实际启用的模式、入口和验证过的结果，不把目标描述成现状。

- [ ] **Step 8: Commit**

```bash
git add backend/tests scripts/acceptance docs/design/05_MIGRATION.md docs/architecture/CURRENT_RUNTIME.md
git commit -m "test: verify dynamic GIS cognition and world-model grounding"
```

---

## 3. 模块切换与退出条件

| 模块 | Shadow 进入条件 | Prefer V2 条件 | V1 退出条件 |
|---|---|---|---|
| Source Data | Bundle adapter 能生成完整 SourceCatalog | 原生 reader 与 adapter digest 可比较 | 生产输入不再要求 Bundle build |
| KG/World Model | transaction、多表示、source trace 测试通过 | fresh session world snapshot 可重载 | 无业务模块调用 KGBuilder/KGManager |
| Retrieval | Entity/source 双平面 packet 可持久化 | 召回、cursor、coverage、raw field 测试通过 | 业务 request 不含 Bundle/KG provider |
| GROUND | V1/V2 diff 可生成 | road/place/parcel 三类目标通过 | Ground/Spatial 无 EvidenceGraph/Bundle/KG import |
| L2/SELECT | capability/resource adapter 测试通过 | 非 parcel 与 parcel solver 都 fail-closed | 固定 layer 和 BSM 不再是通用输入 |
| EXECUTE | planned changeset shadow commit 通过 | approval-bound atomic commit 通过 | worker 无直接 KG write |
| Delivery | Bundle materializer golden comparison 通过 | representation registry 为权威 | Bundle 只作为明确选择的输出 profile |

## 4. 回滚策略

1. `shadow` 阶段回滚只需关闭 V2 shadow；V1 权威未改变。
2. `prefer_v2` 回滚到 `shadow`，保留 V2 artifacts 供审计；不把 V2 entity refs 写回 V1 BSM。
3. world-model commit 以 immutable snapshot 为单位，回滚是把 session current pointer 指回 parent snapshot，不删除 source/assertion history。
4. entity resolution 回滚通过 supersede assertion 并重建 world projection，不修改 Source Record。
5. planned graph 回滚只撤销未发布 changeset pointer；已交付产物保存其 world-model digest，不被悄悄替换。

## 5. 自审检查表

- [ ] 每个设计不变量至少对应一个测试任务。
- [ ] Source、Entity、Representation、Artifact 四种 ref 没有互相代用。
- [ ] 多 geometry field、道路部件、地点多表示均有独立测试。
- [ ] Schema matching 与 Entity resolution 使用不同 contract 和 LLM transaction。
- [ ] Evidence 与 Ground 不再通过增加 layer alias 获得泛用性。
- [ ] Ground 新实现没有复制 PlaceEvidenceIndex 的实体合并职责。
- [ ] prefer_v2 不存在静默 V1 fallback。
- [ ] `v2_only` 能在 monkeypatch V1 入口失败的情况下完成核心验收。
- [ ] 迁移顺序允许每个任务独立 review、测试和回滚。
- [ ] `05_MIGRATION.md` 仍是状态 authority，本文件不伪造完成状态。

## 6. 新增迁移闸门：维度产品与 LLM 表格协议

以下闸门优先于 L1/L2/L3 worker 的继续扩展：

1. **Dimension Product Contract**：为 28 个维度补齐 `l1_outputs`、`l2_inputs`、`l2_outputs`、`l3_inputs`、`l3_outputs`、`gap_types` 和 `spatial_capabilities`；未声明产品的维度不得进入生产派发。
2. **Tabular Prompt Gate**：所有 LLM 输入必须来自有列定义的 bounded table；禁止把完整 `L1Snapshot`、KG 或 Bundle 嵌套展开到一次 prompt。默认每页 32 行、12 列、6200 字符。
3. **Flat Output Gate**：LLM 每次只返回当前页的 rows 和 `continuation_required`；复杂对象由程序按 refs 组装，深度超过 2 或未声明列直接拒绝。
4. **Fact/Evidence Namespace Gate**：L1 fact、Evidence source、Evidence observation、L2 claim、L3 target、GROUND binding、SELECT resource 和 EXECUTE change 使用不同命名空间，不能复用一个 `fact_id` 代表多个层次。
5. **Immediate Gap Gate**：Evidence Gap 必须含 `consumer_dimension`、`requirement`、`allowed_sources`、`retrieval_capability` 和 `priority`。只有 `ready_for_retrieval` 且存在本地数据/缓存/KG 能力时才立即补充；其他 gap 必须进入可见队列。
6. **Dependency Product Replay**：修改一个上游 fact 时，只沿 dependency tree 重新计算受影响的产品 rows；测试必须证明无关维度不会重新生成完整嵌套上下文。

这些闸门的详细契约和表格字段见 `09_MODULE_IMPLEMENTATION_SPEC.md` 第 12—15 节。
