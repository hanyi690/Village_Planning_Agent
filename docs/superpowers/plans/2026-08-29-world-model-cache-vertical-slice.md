# Cached External Evidence and World-Model Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不发起新的地图请求的前提下，把已有高德、天地图和腾讯缓存接入 Data→Evidence→Cognition→GROUND，并保持 SELECT/EXECUTE 只消费本地 Data 层的可渲染几何。

**Architecture:** 新增只读 `ExternalObservationSnapshot` 和坐标归一化缓存读取器；PlanningContext 携带快照，Evidence 通过独立 cached-map retriever 检索结构化观察，KG 通过 adapter 可选投影实体支持。外源点/线/面永远不注入本地 Bundle，也不直接成为规划输出几何；GROUND 只用其作为闭集候选的辅助证据，最终绑定本地 representation。

**Tech Stack:** Python 3.11、Pydantic v2、Shapely、RDFLib、pytest、现有 CAS/PlanningContext/Evidence/DELIVER renderer。

## Global Constraints

- 不发起新的高德、天地图或腾讯请求；只读取 `output/map_validation` 缓存和本地 GIS。
- AMap GCJ-02 只转换一次；天地图按 WGS84-compatible；腾讯统一保存 `[lon, lat]`。
- `SourceFeatureRecord`、`ExternalObservation`、`WorldEntity`、`SpatialRepresentation` 和 planning artifact 身份分离。
- 外源观察不得覆盖、伪造或替代 `boundary.geojson`、本地道路、地块或规划输出 Geometry。
- Evidence 不能把外源地图观察当普通文本；必须保存 provider、stage、operation、状态、坐标契约和 raw response ref。
- LLM 只能在已召回候选中排序或 abstain；不能生成坐标、Geometry、entity ID 或 BSM。
- 任何缓存缺失只形成可审计的 unavailable/missing 状态，不触发隐式在线回退。

---

### Task 1: 建立外源观察契约与缓存读取器

**Files:**
- Create: `backend/app/contracts/evidence/external_observation_contracts.py`
- Create: `backend/app/data/catalog/external_observation_cache.py`
- Test: `tests/test_external_observation_cache.py`

**Interfaces:**
- Produces `ExternalObservation`, `ExternalObservationSnapshot`, `load_cached_external_observation_snapshot()`, `cluster_external_observations()`。
- Consumes provider-specific `normalized_all.jsonl` and optional `manifest.json`; never imports provider HTTP clients.

- [ ] **Step 1: 写失败测试**

测试必须覆盖：三家 provider 的坐标归一化；缺坐标记录保留但不进入空间 cluster；同一 WGS84 位置在 30 米内形成一个 cluster；名称和别名保留；无 manifest 的 AMap interrupted run 可读取；缓存目录不存在时返回空快照而不是发请求。

- [ ] **Step 2: 实现契约**

`ExternalObservation` 至少包含 `observation_id`、`provider`、`stage`、`operation`、`status`、`scope_bucket`、`observed_name`、`aliases`、`location_wgs84`、`location_native`、`coordinate_contract`、`geometry`、`raw_response_ref`、`source_record_ref`、`metadata`。`ExternalObservationSnapshot` 包含 `snapshot_id`、`project_name`、`observations`、`provider_attempts`、`digest`、`complete`。

- [ ] **Step 3: 实现读取和聚类**

读取每个 provider/stage 下最新的非零 normalized run；优先有 manifest 的完整 run，其次允许中断 run。过滤 `meizhou_other` 和 `outside_meizhou`，但在 snapshot metadata 中保留计数。按 observation_id 去重，不覆盖 raw record。用 Haversine 距离建立空间 cluster，cluster ID 由排序后的 observation IDs 的 digest 生成；不同名称但同一坐标保留为 aliases/candidate evidence，不直接删除观察。

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/test_external_observation_cache.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts/evidence/external_observation_contracts.py backend/app/data/catalog/external_observation_cache.py tests/test_external_observation_cache.py
git commit -m "feat: add cached external observation snapshot"
```

---

### Task 2: 将缓存快照接入 PlanningContext

**Files:**
- Modify: `backend/app/infrastructure/context_runtime/runtime.py`
- Modify: `backend/app/infrastructure/context_runtime/manager.py`
- Test: `tests/test_context_external_observations.py`

**Interfaces:**
- `PlanningContext.external_observation_snapshot: ExternalObservationSnapshot | None`。
- `build_planning_context()` 在 Data snapshot 建立后只调用缓存读取器；在线 provider registry 继续只负责显式文本外部搜索。

- [ ] **Step 1: 写失败测试**

给临时缓存根目录写入一条天地图和一条 AMap normalized record，构造最小 bundle context，断言 context 携带 snapshot、digest 出现在 `snapshot_meta()`，而 monkeypatch 在线 provider 的 HTTP 方法不会被调用。

- [ ] **Step 2: 实现 context 字段和 capability**

在 dataclass 增加 `external_observation_snapshot`；`_record_capabilities()` 增加 `external_observations`；`snapshot_meta()` 和 `_content_inputs` 增加 snapshot digest、provider 列表和 observation count。

- [ ] **Step 3: 接入 manager**

从 `output/map_validation` 读取快照；路径通过 `EXTERNAL_MAP_CACHE_ROOT` 可配置，默认项目根下 `output/map_validation`。读取异常只记录 diagnostics，不阻断本地规划 context。

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/test_context_external_observations.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/context_runtime/runtime.py backend/app/infrastructure/context_runtime/manager.py tests/test_context_external_observations.py
git commit -m "feat: expose cached map observations in planning context"
```

---

### Task 3: 建立 cached-map Evidence 检索平面

**Files:**
- Create: `backend/app/infrastructure/evidence_runtime/retrievers/cached_map_retriever.py`
- Modify: `backend/app/infrastructure/evidence_runtime/facade.py`
- Modify: `backend/app/infrastructure/evidence_runtime/retriever_router.py`
- Test: `tests/test_cached_map_retriever.py`

**Interfaces:**
- `retrieve_from_cached_map(context, query, entity_scope, limit=32) -> tuple[list[EvidenceFact], list[EvidenceSource], dict]`。
- Facts 使用 `fact_type="external_map_observation"`、`source_kind="external_map_cache"`、`evidence_role="location_binding"`，空间事实只引用 `observation_id` 和 raw refs。

- [ ] **Step 1: 写失败测试**

验证：名称查询可以召回 AMap/天地图观察；道路/水体/设施 scope 会过滤角色；同一地点多 provider 观察都返回但不重复相同 observation；缓存为空返回明确 trace；返回 fact 不包含 BSM 或伪造 geometry。

- [ ] **Step 2: 实现匹配和 Evidence 投影**

匹配 `observed_name`、aliases、metadata 中的 address/name；查询为空且 scope 是 spatial 时只返回 `project_local` 的 bounded observations。`EvidenceFact.fields` 保存 JSON 编码的 provider、stage、operation、coordinate_contract、scope_bucket、location_wgs84、geometry_semantics、cluster_id；`spatial_refs` 只放 observation refs。

- [ ] **Step 3: 接入 Evidence facade**

在 cached context hydration 后调用 cached-map retriever；将版本号和 snapshot digest 加入 Evidence cache key；在 retrieval_status 中记录 `cached_map_observations`。该分支绝不调用在线 provider。

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/test_cached_map_retriever.py tests -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/evidence_runtime/retrievers/cached_map_retriever.py backend/app/infrastructure/evidence_runtime/facade.py backend/app/infrastructure/evidence_runtime/retriever_router.py tests/test_cached_map_retriever.py
git commit -m "feat: retrieve cached map observations as structured evidence"
```

---

### Task 4: 将外源观察投影为可撤销的 KG 实体支持

**Files:**
- Create: `backend/app/infrastructure/kg/adapters/external_observation_adapter.py`
- Modify: `backend/app/infrastructure/kg/ontology.py`
- Test: `tests/test_external_observation_kg_adapter.py`

**Interfaces:**
- `ExternalEntitySupport`：`entity_ref`、`cluster_id`、`observation_refs`、`aliases`、`roles`、`centroid_wgs84`。
- `project_external_observations(graph, snapshot) -> list[ExternalEntitySupport]`。

- [ ] **Step 1: 写失败测试**

验证同一坐标范围内的多 provider 观察投影到同一个 external support entity；不同坐标或明确冲突的 scope 不合并；RDF 中保存每个 observation ref、provider、原始坐标和 WGS84 坐标；撤销一个 observation 后可以由剩余 assertion 重建。

- [ ] **Step 2: 扩展 ontology predicates**

增加 `externalObservation`、`externalProvider`、`observedName`、`locationWGS84`、`observationCluster` 等 predicate；不得把 `ExternalObservation` 声明成 `Parcel`、`Road` 或 `WorldEntity` 的最终实例。

- [ ] **Step 3: 实现 projection**

复用 Task 1 的 cluster；entity ref 使用 `external-support:{cluster_id}`，不使用 BSM。Geometry 仅作为 observation support 的 WKT/坐标 literal，不能覆盖本地 geometry。adapter 不参与 Data 读取，也不反向调用 DataCatalog。

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/test_external_observation_kg_adapter.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/kg/adapters/external_observation_adapter.py backend/app/infrastructure/kg/ontology.py tests/test_external_observation_kg_adapter.py
git commit -m "feat: project cached observations into auditable kg support"
```

---

### Task 5: 加强 GROUND/SELECT/EXECUTE 的资源边界与渲染验收

**Files:**
- Modify: `backend/app/modules/ground/application.py`
- Modify: `backend/app/spatial/grounding/resolver.py`
- Modify: `backend/app/contracts/select/scenario.py`
- Modify: `backend/app/contracts/execute/execution_plan_contracts.py`
- Modify: `backend/app/workflow/delivery/render_layers.py`
- Create: `tests/test_planning_geometry_lineage.py`

**Interfaces:**
- Ground binding 必须同时携带 `entity_ref`、`representation_ref`、`source_feature_ids`、`source_snapshot_ref`、`geometry_ref`。
- SELECT candidate 必须引用 `resource_ref`/`representation_ref`，不能把外源 observation ref 当可执行 Geometry。
- EXECUTE/DELIVER 只能从本地 Data geometry store 或现有 authoritative workspace 生成 GeoJSON。

- [ ] **Step 1: 写失败测试**

构造一个外源 POI 与本地道路候选同坐标的场景，断言 Ground 只返回本地 representation；构造一个 SELECT scenario，若 resource 只有外源 observation ref 则 fail-closed；构造一个有效 planned road 和 zone，断言 render layer 每个 feature 都有几何和 lineage。

- [ ] **Step 2: 实现边界校验**

在 Ground/SELECT contract validator 中拒绝 `external-observation:` 作为执行 geometry；接受它作为 evidence/source ref。render layer builder 对 missing geometry、非 WGS84、缺少 source snapshot/representation lineage 的 planned feature 产生诊断并不渲染伪造线。

- [ ] **Step 3: 运行现有链路探针**

```bash
python -m pytest tests/test_planning_geometry_lineage.py tests -q
python scripts/acceptance/business_stage_boundary_probe.py
python -m compileall -q backend/app
```

- [ ] **Step 4: 使用现有缓存做离线 smoke**

运行缓存读取、L1/L2/L3/target projection/GROUND/SELECT 的 current-session probes；任何失败都必须输出 artifact ref、snapshot digest 和失败阶段，不能自动刷新 provider。

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/ground backend/app/spatial/grounding backend/app/contracts/select backend/app/contracts/execute backend/app/workflow/delivery/render_layers.py tests/test_planning_geometry_lineage.py
git commit -m "test: enforce local geometry lineage through delivery"
```

---

## Verification and Handoff

最终验收必须同时满足：

1. `python -m pytest tests -q` 通过。
2. 缓存读取测试证明没有 HTTP 调用，且 AMap/天地图/腾讯状态保持可审计。
3. `business_stage_boundary_probe.py` 通过，业务 requirement 不出现 provider/layer/BSM。
4. Ground/SELECT/EXECUTE 的输出能重载 artifact，并能生成含 planned road、zone、facility 或 diagnostic 的 delivery render layers。
5. 外源观察只作为 Evidence/Cognition 支持；最终规划 Geometry 仍来自 Data 层的本地 representation。
6. `git diff --check` 和 `python -m compileall -q backend/app` 通过。

完成后更新 `docs/design/05_MIGRATION.md` 的实际状态；本计划只记录实施顺序，不伪造运行完成度。
