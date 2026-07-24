# Data / Schema / KG / PARSE 优化可执行任务清单

> **Based on**: `EXA_FINDINGS.md` Part 2 + 代码审计 2026-07-24
> **原则**: P0 = 接线/去重/补 shim（不新增抽象）；P1 = 契约 + 类型；P2 = 互通 + 扩展
> **关键事实**: `tools/gis/kg.py:22` 已做一次性 KG 提取(拍平成 flat dict)；`mip_solver.py:82` `ConstraintDrivenAllocator.solve` 已收 `constraints/adjacency_map/kg`。ConstraintCompiler 是**formalize 现有 ad-hoc 拍平**，非从零建。

---

## 执行顺序与关键路径

```
P0-A Data 接线:  T1 → T3 → T4
                  T1 → T2
                  T5 → T6
P0-B KG 契约:    T7 → T8 → T9
P1-A 编译器:     T11 ──┐
                  T12 ──┤→ T10 → T13  (T13 是集成大节点)
P1-B Schema:     T14, T15 → T16
P1-C PARSE:      T17 ; T13 → T18
P2:              T19(T6), T20, T21(T20), T22(T7,T14), T23(T5)
```

**关键路径**: T1→T7→T10→T13（Data 接线 → KG 类型化 → 编译器 → pipeline 集成）。T13 完成后 KG 才真正成为 PARSE/EXECUTE 间的语义桥接。

---

## P0-A Data 层接线（让类型化路径上生产）

### T1 `gis_context.py` 切换到 `DataCatalog.load_village_bundle` [M]
- **文件**: `backend/app/agent/gis_context.py`
- **现状**: `:95` `from app.modules.data.fetcher import get_fetcher`；`SharedGISContext._user_uploaded_data` 存 raw GeoJSON
- **改动**:
  - 加 `from app.modules.data.catalog.catalog import DataCatalog` + `from app.modules.schema.types.canonical import BBox`
  - 新方法 `get_typed_bundle(self) -> GISDataBundle`：`DataCatalog().load_village_bundle(self.village_name, BBox(*self.bbox))`
  - 保留 `get_data_by_type`（raw dict）标 `# DEPRECATED`，过渡期兼容
  - center 定位逻辑暂保留 fetcher（4-tier 策略），仅图层加载切 DataCatalog
- **验收**: `get_typed_bundle()` 返回 `GISDataBundle`，`parcel_count>0`，不调 `get_fetcher` 取图层
- **依赖**: 无
- **风险**: fetcher 的 center 定位是另一职责，本期不迁移，避免范围爆炸

### T2 `session_routes.py` 切换到 DataCatalog [M]
- **文件**: `backend/app/api/session_routes.py`
- **现状**: `:1305` `from app.modules.data.fetcher import GISDataFetcher`
- **改动**: 图层加载改 `DataCatalog.load_village_bundle`；center 定位保留 `GISDataFetcher` 或迁 `connections/`
- **验收**: `grep -rn "load_village_bundle\|GISDataFetcher" session_routes.py` 图层取数走 DataCatalog
- **依赖**: T1

### T3 `compute_spatial_context` 收类型化 bundle [M]
- **文件**: `backend/app/modules/spatial_ops/context.py:38`、`backend/app/agent/gis/layout_pipeline.py:75`、`backend/app/tools/gis/parse.py:493`
- **现状**: `compute_spatial_context(gis_data: Dict[str, Any])`
- **改动**:
  - 新签名 `compute_spatial_context(bundle: GISDataBundle) -> SpatialContext`，内部从 `bundle.landuse/roads/annotations` 读
  - 加 `compute_spatial_context_from_dict(gis_data)` 标 `# DEPRECATED` 兼容旧调用
  - `layout_pipeline.py:75` 与 `tools/gis/parse.py:493` 改传 bundle
- **验收**: pipeline 用 bundle 调用；`SpatialContext.natural_villages/landuse_entries` 字段填充正确
- **依赖**: T1

### T4 删 `load_village_data` raw dict 路径 [S]
- **文件**: `backend/app/modules/data/catalog/catalog.py:218`
- **现状**: `load_village_data` 返回 raw dict（`:250` `gis_data[f"{lt}_geojson"]=result.data`）
- **改动**: 删 `load_village_data`，统一到 `load_village_bundle`（typed）
- **验收**: `grep -rn "load_village_data" backend/app/` 无调用
- **依赖**: T1, T2

### T5 `gis/schema` 兼容 shim [S]
- **文件**: `backend/app/modules/gis/schema/__init__.py`（新建，目录当前为空）
- **现状**: `schema/README.md` 称旧路径可用，实际 `ls gis/schema/` 为空
- **改动**: re-export `app.modules.schema`，发 `DeprecationWarning`
- **验收**: `from app.modules.gis.schema import GISDataBundle` 仍可用且发 warning
- **依赖**: 无

### T6 合并两个 feature_type 注册表 [S]
- **文件**: `catalog/catalog.py:263`(`_TYPED_LAYER_MAP`)、`ingest.py:420`(`_FEATURE_TYPE_REGISTRY`)
- **改动**: schema 层建 `LAYER_TYPE_REGISTRY`（`layer_type -> (model_class, ingest_port, default_path)`），catalog/ingest 都引用
- **验收**: 单一注册表，两处不再各自维护映射
- **依赖**: T5

---

## P0-B KG 类型化摄入契约

### T7 KG 类型化摄入 API [L]
- **文件**: `backend/app/modules/kg/builder.py`
- **现状**: `_build_static(landuse_geojson, gis_data)`(`:278`)、`add_protection_zones(gis_data:Dict)`(`:1778`)、`add_control_lines`(`:1862`)、`add_planning_elements`(`:1934`)、`add_natural_features`(`:2011`) 全收 raw dict
- **改动**:
  - 新 `build_from_bundle(self, bundle: GISDataBundle) -> PlanningKG`（替代 `_build_static` 的 raw geojson 入口）
  - 新 `add_parcels(parcels: List[CurrentLandUseParcel])`、`add_protection_zones(zones: List[FarmlandProtection|EcologicalRedline])` 等，签名收类型化 `List`
  - 旧 `add_*(gis_data:Dict)` 改为过渡桥（内部转类型化再调新 API），标 `# DEPRECATED`
- **验收**: 新 API 签名拒绝 dict；从 bundle 构建的 KG 三元组数与旧路径一致
- **依赖**: T1
- **对标**: OntoZoning TBox/ABox（EXA_FINDINGS §2.3）

### T8 删 `KGInputParcels.from_geojson` + KG data import [S]
- **文件**: `backend/app/modules/kg/builder.py`
- **现状**: `KGInputParcels.from_geojson()`(`:175`)、`:187` `from app.modules.data import ingest_current_landuse`
- **改动**: 删 `from_geojson`；删 data import；KG 只收 `List[CurrentLandUseParcel]`
- **验收**: `grep -n "from_geojson\|modules.data" builder.py` 无命中
- **依赖**: T7

### T9 KGManager 缓存 key 改 hash 类型化字段 [S]
- **文件**: `backend/app/modules/kg/manager.py:53`
- **现状**: `compute_layer1_cache_key` hash raw GeoJSON features（`BSM:DLBM:SHAPE_Area`）
- **改动**: 新 `compute_layer1_cache_key(village_name, parcels: List[CurrentLandUseParcel])`，hash `(bsm, dlbm, dlbm_system, area_sqm)`
- **验收**: 相同类型化 parcels 命中缓存；raw geojson 不再进 KGManager
- **依赖**: T7, T8

---

## P1-A ConstraintCompiler

### T10 新建 `kg/constraint_compiler.py` [L]
- **文件**: `backend/app/modules/kg/constraint_compiler.py`（新建）
- **对标**: RLP / Graph-Grounded / Scimitar（EXA_FINDINGS §2.4）
- **现状**: `tools/gis/kg.py:22` `build_knowledge_graph` ad-hoc 拍平 KG -> flat dict（`kg_constraints/adjacency_map/zone_restrictions/protected_parcels`，`:159-167`）
- **改动**: 新 `ConstraintCompiler.compile(intent, parcels, kg) -> MIPModel`:
  - Step1 硬约束（对标 Ontology-to-tools T-Box hard locks）: `kg.get_protected_parcels()` -> 变量锁定；`kg.get_three_lines()` -> 空间边界
  - Step2 软约束（annotation-derived soft goals）: `intent.zone_targets` -> 目标；`intent.adjacency_rules` -> 邻接偏好
  - Step3 ground 成 `MIPModel(variables, hard_constraints, soft_goals, cost_matrix)`（grounding 函数必须有限，对标 RLP answer-set）
  - 约束模板库对标 Ofoghi MILP ontology（bound/balancing/set covering/logic）+ MICE 线性化 lemma
- **验收**: 单元测试--给定 mock intent+parcels+kg 产出有效约束矩阵；8 项验证检查（设计 §5.6）各有对应模板
- **依赖**: T11

### T11 补齐 KG 读 API [M]
- **文件**: `backend/app/modules/kg/builder.py`
- **现状**: 仅 `get_constraints`(`:1366`)、`get_adjacency_map`(`:1382`)
- **改动**: 加 `get_protected_parcels()`/`get_zone_restrictions()`/`get_three_lines()`/`get_intent()`/`get_facility_locations()`/`get_vne_summary()`
  - 注: `tools/gis/kg.py` 已用 `query_kg(kg, "check_protected_parcels"/"get_protected_parcels_detail")` 查询，说明 SPARQL 模板已存在 -- 复用 `kg/query.py` 模板，封装为 `PlanningKG` 方法
- **验收**: 6 方法返回正确数据；ConstraintCompiler 可调用
- **依赖**: 无（可与 T10 并行）

### T12 PARSE 粒度写 API [M]
- **文件**: `backend/app/modules/kg/builder.py`
- **现状**: `build_from_intent`(`:538`)/`_build_semantic`(`:334`) 单体构建
- **改动**: 加 `add_intent(intent)`/`add_operations(ops)`/`add_constraints(cons)`；`build_from_intent` 内部调三者
- **验收**: PARSE 可逐项写 KG；单元测试验证 Layer3 三元组正确
- **依赖**: T7

### T13 `layout_pipeline` 用 ConstraintCompiler 替代 `tools/gis/kg.py` 拍平 [L]
- **文件**: `backend/app/agent/gis/layout_pipeline.py`(`_build_kg_node:140`、`_execute_node:336`)
- **现状**: `_build_kg_node` 调 `tools/gis/kg.build_knowledge_graph` -> 存 flat dict 到 state；`_execute_node`/MIP 从 state 读
- **改动**:
  - `_build_kg_node`: `kg.build_from_bundle(bundle)` + `add_intent/add_operations/add_constraints`；`ConstraintCompiler.compile(intent, parcels, kg) -> MIPModel` 存 state
  - `mip_solver.ConstraintDrivenAllocator.solve`(`:82`) 已收 `constraints/adjacency_map/kg` -- 改为从 `MIPModel` 取这些
  - 保留 `tools/gis/kg.py` 标 `# DEPRECATED`，过渡期不删
- **验收**: `grep` pipeline 不再调 `build_knowledge_graph`；MIP 从 `MIPModel` 取约束；`run_layout_pipeline.py` 回归通过
- **依赖**: T10, T11, T12

---

## P1-B Schema 补类型

### T14 7 个新空间类型 [M]
- **文件**: `backend/app/modules/schema/types/spatial_types.py`
- **改动**: 加 `SoilType/SoilErosion/Watershed/NatureReserve/HydrogeologyZone/PopulationGrid/GDPGrid`（字段见 `01_DATA_ACQUISITION_PLAN §4.1`）
- **验收**: 7 类型可实例化；`from_geojson_feature` 支持
- **依赖**: 无

### T15 `AdminArea` 扩展 [S]
- **文件**: `backend/app/modules/schema/types/spatial_types.py`
- **改动**: 加 `admin_level`(village/town/county/city/province) + `parent_code`
- **验收**: 5 级行政区划可表达
- **依赖**: 无

### T16 ingest registry 同步新类型 [S]
- **文件**: `backend/app/modules/data/ingest.py:420`
- **改动**: 7 新类型 + AdminArea 扩展字段加入 registry
- **验收**: `ingest_feature` 可摄入 7 新类型
- **依赖**: T6, T14, T15

---

## P1-C PARSE 契约归位

### T17 `SpatialContext` 迁 `parse_contracts` [S]
- **文件**: `schema/contracts/parse_contracts.py`、`schema/contracts/layout_contracts.py`、`agent/gis/parse/state.py:28`
- **现状**: `SpatialContext/NaturalVillageAnchor/LanduseEntry/SpatialRelation/ConstraintSummary` 在 `layout_contracts`(legacy)；`parse/state.py:28` import 之
- **改动**: 迁到 `parse_contracts.py`；`layout_contracts` 仅留 layout 工具遗留类型；`parse/state.py` 改 import 路径
- **验收**: PARSE 从 `parse_contracts` import `SpatialContext`；`layout_contracts` 不再被 PARSE 依赖
- **依赖**: 无

### T18 PARSE state 注入 KG（替代全局抓）[M]
- **文件**: `backend/app/agent/gis/parse/agent.py`
- **现状**: `_get_current_parse_kg`(`:139`)/`get_any_kg` 全局抓 KG
- **改动**: `ParseAgentState` 加 `kg` 字段；`layout_pipeline._parse_intent_node` 注入 kg；工具调用从 state 取
- **验收**: PARSE 不再调 `get_any_kg`；KG 从 state 注入
- **依赖**: T12, T13

---

## P2 互通与扩展

### T19 GeoPackage driver [M]
- **文件**: `backend/app/modules/data/sources/geopackage.py`（新建）
- **改动**: 新 `DataSourceDriver` 子类，Catalog 自动检测 `.gpkg`（对标设计 §2.2）
- **验收**: `sources.yaml` 配 `.gpkg` 可加载多图层
- **依赖**: T6

### T20 `Source.capabilities()` + `DataResult` 显式字段 [M]
- **文件**: `sources/base.py`、`contracts.py`
- **改动**: ABC 加 `capabilities() -> set[Capability]`（`supports_crs/supports_bbox_query/supports_encoding`）；`DataResult` 加 `spatial_extent: Optional[BBox]`、`crs: str`、`bands: Optional[list]` 一级字段
- **对标**: QGIS `QgsDataProvider.capabilities` / ODC `ParsedItem`
- **验收**: 各 driver 实现 `capabilities`；`DataResult` 字段显式
- **依赖**: 无

### T21 YAML Jinja2 模板 + `to_stac()` [M]
- **文件**: `catalog/catalog.py`、`catalog/config.py`
- **改动**: `sources.yaml` 支持 Jinja2 参数化路径；`DataCatalog.to_stac()` 序列化器
- **对标**: Intake / STAC
- **验收**: `path: "tiles/{z}/{x}/{y}.tif"` 可解析；`to_stac()` 产出 STAC item
- **依赖**: T20

### T22 KG 入库扩展（保护/规划/自然要素）[L]
- **文件**: `backend/app/modules/kg/builder.py`
- **改动**: `add_protection_zones/add_control_lines/add_natural_features` 类型化实现 + 实际数据接入（对标 `01_DATA_ACQUISITION_PLAN` Phase 1）
- **验收**: KG 入库率 4/29 -> 15+/29
- **依赖**: T7, T14

### T23 文档路径同步 [S]
- **文件**: `data/README.md`、`data/ingest.py` docstring
- **改动**: 修 `gis.schema` -> `modules.schema` 路径引用
- **验收**: `grep -rn "gis.schema" backend/app/modules/data/` 无残留（除 shim）
- **依赖**: T5

---

## 验收回归（每个 P0/P1 任务完成后跑）

```bash
# 1. 数据层回归
python backend/scripts/run_layout_pipeline.py   # 13 layers, 34 annotations, 131 roads

# 2. 单元测试
python -m pytest backend/scripts/test_data_drivers.py   # 8 tests
python -m pytest backend/scripts/test_gis_unit.py

# 3. KG 三元组数对比（类型化路径应与旧路径一致）
#    在 _build_kg_node 加日志对比 kg.get_triple_count()
```

## 建议批次

| 批次 | 任务 | 目标 | 预估 |
|---|---|---|---|
| 批次 1 | T5, T6, T23 | 去重 + shim + 文档（低风险，独立） | 0.5 天 |
| 批次 2 | T1, T2, T3, T4 | Data 接线上生产 | 2 天 |
| 批次 3 | T7, T8, T9 | KG 类型化契约 | 2 天 |
| 批次 4 | T11, T12, T10, T13 | ConstraintCompiler + pipeline 集成（关键路径终点） | 3 天 |
| 批次 5 | T14, T15, T16, T17, T18 | Schema 类型 + PARSE 归位 | 2 天 |
| 批次 6 | T19, T20, T21, T22 | 互通与扩展 | 3 天 |
