# 模块实现映射 (Module Implementation Mapping)

> 五大设计层 → 实际代码路径映射。每个模块给出位置、职责、关键文件、依赖、实现状态。
> 所有事实均从代码验证。当前分支：`feature/flash-llm-explore-agent` (HEAD `f29cbe94`)。

---

## 架构分层

```
Schema ← Data ← SpatialOps ← KG ← Agent
                                  └── RAG (横向支撑)
```

依赖方向自下而上，反向依赖禁止。Schema 层零依赖（不 import Data/KG/Agent/Tools）。

---

## 模块 1：Schema（类型契约层）

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/schema/` |
| **职责** | 定义空间要素类型（四形态：矢量/栅格/表格/文档）、编码体系（13+ 套）、跨层契约、汇交输出规范。系统底座，零依赖。 |
| **依赖** | 仅标准库 + `pydantic` + `yaml`；禁止 import Data/KG/Agent/Tools/geopandas/shapely |
| **实现状态** | ✅ v4.8.1 落地完成，所有设计类型已实现 |

### 关键文件

| 子包 | 文件 | 说明 |
|---|---|---|
| `types/` | `base.py` | `SpatialFeature` (Pydantic v2 BaseModel) → `PointFeature`/`LineFeature`/`PolygonFeature` |
| | `spatial_types.py` | Group A–F 矢量语义子类（含阶段抽象 Base* + 实体/表达分离） |
| | `raster_types.py` | `RasterDataset` + DEMInput/DOMInput/SlopeRaster/AspectRaster/SuitabilityRaster |
| | `table_types.py` | `TableDataset` + 7 子类（输入型 PopulationTable/IndustryTable + 输出型 ControlRuleTable 等） |
| | `document_types.py` | `Document` + PlanningText/L3Report |
| | `canonical.py` | `VillageBundle`（形态优先容器）、`ProjectDataView`、LayerGroup 系列 |
| | `layer_registry.py` | `GIS_LAYER_REGISTRY`（YAML-driven，40+ layer_type） |
| | `gis_layer_registry.yaml` | 图层注册表单一真相源 |
| `encodings/` | `code_sets.py` | 编码派生字典 + lookup 函数（v3.0） |
| | `classification.py` | 编码分类逻辑 |
| | `dicts/loader.py` | `DictionaryCenter` 加载器 |
| | `dicts/encodings/` | 13 套编码 YAML：gbt21010/tugui/appendix5/ghflbm/ydyhfldm/vne + three_categories/zone_types_*/planning_zones/primary_zones |
| | `dicts/mappings/` | 14 套编码间映射 YAML（gbt21010_to_*、planning_zones_to_* 等） |
| | `dicts/vocabularies/` `dicts/rules/` `dicts/references/` | 受控词表、规则、参考数据 |
| `contracts/` | `parse_contracts.py` | PARSE 输出契约（`SpatialPlanningIntent`/`ZoneTarget`/`FacilityTarget`/`AxisTarget`/`RoadTarget`） |
| | `execution_contracts.py` | EXECUTE 输入契约（`SpatialOperation`/`SpatialConstraint`/`MIPModel`/`ExecutionPlan`） |
| | `validation_contracts.py` | 验证闭环契约（`ValidationCheckItem`） |
| | `layout_contracts.py` | LAYOUT 工具契约 |
| | `context_contracts.py` | 空间认知契约（`ContextBlock` + 7 子类型，v4.3） |
| | `constraint_contracts.py` `custom_zone_contracts.py` `delivery_contracts.py` `semantic_fields.py` `spatial_ref_contracts.py` | 约束/自定义分区/交付/语义字段/空间引用契约 |
| `output/` | `gdb.py` | `GDB_LAYER_REGISTRY`、GDB 12 层字段定义、命名规范 |
| | `colors.py` | 8 套调色板 |
| | `tables.py` | 表格汇交导出（4 函数） |
| `utils/` | `metrics.py` | 用地指标计算 |
| `provenance/` | | 数据溯源 |

### 编码体系（13 套）

现状层 6 套：`GB/T21010`、`TUGUI`、`APPENDIX5`、`GHFLBM`、`YDYHFL`、`VNE`
分区层 7 套（v3.0 新增）：`three_categories`、`zone_types_appendix5`、`zone_types_gbt50137`、`zone_types_town`、`zone_types_village`、`planning_zones`、`primary_zones`

---

## 模块 2：Data（数据获取与管理层）

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/data/` |
| **职责** | 所有空间数据（矢量/栅格/瓦片）和文档进入系统的唯一边界。Catalog + Source + Connection 三层抽象，四形态分桶 ingest。 |
| **依赖** | → `schema`；被 `spatial_ops`/`kg`/`agent` 消费 |
| **实现状态** | ✅ [PRODUCTION] v4.9；矢量/栅格/文档完整，表格 ingest 未打通 |

### 关键文件

| 子包 | 文件 | 说明 |
|---|---|---|
| `catalog/` | `catalog.py` | `DataCatalog` — 唯一数据入口，`load_village_bundle()` |
| | `config.py` | Pydantic 配置模型 |
| | `sources.yaml` | 数据源物理配置（单一真相源） |
| `sources/` | `base.py` | `DataSourceDriver` ABC |
| | `registry.py` | `DriverRegistry`（装饰器自动发现） |
| | `file_vector.py` | 本地 GeoJSON/Shapefile |
| | `api_vector.py` | WFS/MapServer REST |
| | `wmts_tile.py` | WMTS 瓦片下载+缓存 |
| | `local_raster.py` | 本地 GeoTIFF |
| | `remote_raster.py` | 远程栅格下载指引 |
| | `document.py` | Markdown/JSON/TXT |
| `connections/` | `base.py` `rate_limiter.py` `tianditu.py` `amap.py` `gd_tianditu.py` `osm.py` | API 连接管理 + 速率限制 |
| `adapters/` | `__init__.py` | `IngestAdapter` Protocol + `ADAPTERS` 注册表 |
| | `parcels.py` | 用地 parcels 编码校验 |
| | `features.py` | 通用矢量要素 |
| | `raster.py` | GeoTIFF → RasterDataset |
| | `table.py` | CSV/Excel → TableDataset |
| | `document.py` | Markdown → Document |
| 根目录 | `ingest.py` | raw GeoJSON → typed schema models |
| | `base_conversion.py` | DLBM → GHYTBM 基数转换（v4.9） |
| | `encoding_detector.py` | 编码检测 |
| | `contracts.py` | `DataResult`/`DataSourceMetadata` |
| `documents/` | `loader.py` | 规划文本/L3 报告加载 |
| `providers/` | `tianditu/` `amap/` `poi.py` | POI/API 搜索子模块 |

### 数据流

```
DataCatalog.load_village_bundle() 
  → DataSourceDriver.fetch() → DataResult 
  → ADAPTERS[adapter].load() → AdapterResult(features, warnings, dlq) 
  → bundle.add(feature) → _bundle_key_for() 查 YAML registry 路由到形态 Group
```

---

## 模块 3：SpatialOps（空间计算唯一层）

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/spatial_ops/` |
| **职责** | 系统中所有空间计算的唯一发生地。BBox/距离/面积/邻接/过滤/约束编译/地块操作/道路规划/用地平衡。 |
| **依赖** | → `schema` + `app.utils`；禁止反向依赖 Agent/KG/Tools/Parsing |
| **实现状态** | ✅ v5.0；七大职责全部实现 |

### 关键文件

| 文件 | 职责 | 消费者 |
|---|---|---|
| `context.py` | 职责 A：`ContextBlock` 计算（8 种空间认知卡片） | KG builder |
| `geometry.py` | 职责 A：几何操作（centroid/area/parcel_relations） | KG builder |
| `relations.py` | 职责 A：空间关系（方向、邻接） | KG builder |
| `grounding.py` | 职责 B：空间接地（PARSE 专用，text → BBox/BSM candidates） | PARSE agent |
| `bridge.py` | 职责 C：空间桥接（`ConstraintIndex` + 跨类型关系，EXECUTE 专用） | EXECUTE agent |
| `constraint_compiler.py` | 职责 D：约束编译（6 源编译 + 冲突仲裁） | MIP solver |
| `parcel_ops.py` | 职责 E：地块几何操作（split/merge/modify/reclassify/create） | EXECUTE agent |
| `road_planner.py` | 职责 F：道路网络规划（RoadTarget → PlannedRoad） | EXECUTE agent |
| `land_balance.py` | 职责 G：用地平衡表（L1 vs L4 对比 + DeliveryGate） | 导出层 |

> **注意**：`ConstraintCompiler`（`constraint_compiler.py`）头部标注为替代旧的 PARSE→MIP 散转换与 KG→state 拍平逻辑，设计来源 `02_EXECUTION_PLAN.md` Module B。该类在架构上被标记为 **[DEPRECATED]**，其功能正被 `bridge.py` 的 `ConstraintIndex` 与跨类型关系机制取代。

---

## 模块 4：KG（知识图谱层）

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/kg/` |
| **职责** | 空间语义引擎。四层结构（L1 现状实体 → L2 空间关系 → L3 意图虚拟实体 → L4 规划成果），RDF + GeoSPARQL 对齐，SemanticMemoryStore 存关系量化属性。 |
| **依赖** | → `schema` + `spatial_ops`（消费计算结果，不自己算几何）；被 `agent`/`tools` 消费 |
| **实现状态** | ✅ v5.0；四层 + 缓存 + 记忆存储完整 |

### 关键文件

| 子包 | 文件 | 说明 |
|---|---|---|
| 根目录 | `ontology.py` | 本体：`EntityTypes`/`Relations`/`GeoPredicates`/`SemanticPredicates` |
| | `manager.py` | `KGManager` 单例 — 三层缓存（L1 immutable / L2 per-intent / L3 per-allocate）+ 查询缓存版本失效 |
| | `memory.py` | `SemanticMemoryStore` — 关系量化属性（shared_boundary_m/centroid_distance_m 等） |
| | `dlq.py` | Dead Letter Queue |
| `builder/` | `base.py` | `PlanningKG` 数据容器（RDF Graph + memory） |
| | `builder.py` | `KGBuilder` 编排器（`build_from_bundle()`/`build()`） |
| | `registry.py` | `@kg_builder` 装饰器 + `BuilderSpec` + `BuildContext` |
| | `layer1_core.py` | 12 个 L1 builders（parcels/roads/water/facilities...） |
| | `layer1_extended.py` | 6 个 L1 builders（protection/boundaries/terrain...） |
| | `layer1.py` `layer1_control_lines.py` `control_line_mapping.py` | L1 聚合 + 控制线映射 |
| | `layer2.py` | `add_parcel_relations`/`add_cross_type_relations` |
| | `layer3.py` | `build_intent_layer`/`clear_intent_layer`（易失） |
| | `layer4.py` | `apply_planned_state` + `PlannedState` dataclasses（版本化） |
| | `enrichment.py` | `add_gis_layer_groups`/`add_semantic_enrichment` |
| | `geo_helpers.py` | WKT centroid/bbox helpers |
| `queries/` | `sparql.py` | 30+ SPARQL 模板，`query_kg()` |
| | `semantic.py` | LLM 友好语义查询 |
| | `cognition.py` | `get_village_cognition` 三层认知摘要 |
| | `spatial_ref.py` | 空间引用查询 |
| | `contracts.py` | `DualPayload`/`TokenBudget`/`TopKSampler` |

### @kg_builder 注册机制

```python
@kg_builder("landuse_current", entity_type="Parcel", layer=1, order=10)
def _add_parcels(kg, features, *, gtype_ref, entry, ctx): ...
```

`KGBuilder._build_entities()` 按 `layer` → `order` 顺序调用所有注册函数。

---

## 模块 5：RAG（检索增强生成层）

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/rag/` |
| **职责** | 动态知识检索与管理。Small-to-Big 架构（检索 child，返回 parent），层级切片，LLM 生成查询。横向支撑 Agent 层。 |
| **依赖** | → `app.core`（LLM/settings）；被 `agent`/`services` 消费 |
| **实现状态** | ✅ 生产可用 |

### 关键文件

| 文件 | 说明 |
|---|---|
| `service.py` | `RagService` 单例 — LLM 生成查询 + 向量相似检索 + Small-to-Big + 知识库管理 |
| `vector_store.py` | `HierarchyVectorStore` + `AliyunEmbeddings`（层级感知检索） |
| `chunker.py` | 层级切片 |
| `context.py` | 上下文组装 |
| `cli.py` | KB CLI（status/delete/reload/verify） |
| `utils/document_loader.py` | 文档加载 |
| `utils/metadata_extractor.py` | `MetadataExtractor`/`ExtractedMetadata` |

---

## 附加模块

### Parsing（规划文本解析工具层）

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/parsing/` |
| **职责** | 确定性 + LLM 文本提取工具集，被 PARSE Agent 与 `report_store` 消费。非独立架构层，属 Agent 层工具基础设施。 |
| **依赖** | → `schema.contracts`；不依赖 Data/KG 层；不做空间计算 |
| **实现状态** | ✅ 实现完成 |

关键文件：`markdown_parser.py`、`section_classifier.py`、`regulation_extractor.py`、`gazetteer.py`、`semantics.py`、`table_schema_inference.py`、`admin_code_loader.py`、`schemas.py`

### Planning Text（规划文本生成）

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/planning_text/` |
| **职责** | 规划说明文本生成与导出 |
| **实现状态** | ✅ 实现 |

关键文件：`generator.py`、`content_extractor.py`、`section_builder.py`、`llm_styler.py`、`rag_appender.py`、`json_exporter.py`、`layer_exporter.py`、`docx_styles.py`、`config.py`

### Prompts/L1（L1 维度提示词）

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/prompts/l1/` |
| **职责** | 12 个 L1 分析维度的提示词模板 |
| **实现状态** | ⚠️ 新增未跟踪目录（`git status` 显示 `??`，尚未纳入版本控制） |

12 维度（`_config.py` 定义）：`location`/`socio_economic`/`villager_wishes`/`superior_planning`/`natural_environment`/`land_use`/`traffic`/`public_services`/`infrastructure`/`ecological_green`/`architecture`/`historical_culture`

---

## Agent/GIS 子模块

GIS Agent 位于 `backend/app/agent/gis/`，包含三个子模块，对应规划的三阶段（PLAN → DELIVER → 探索）。

### parse/ — PARSE Agent

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/agent/gis/parse/` |
| **职责** | 规划文本 → 类型化空间意图（`SpatialPlanningIntent`）。消费 parsing 模块工具，产出写入 `GISPipelineState`。 |
| **关键文件** | `agent.py`（`parse()`/`parse_async()` → `ParseResult`）、`state.py` |
| **依赖** | → `schema.contracts`、`parsing`、`spatial_ops.grounding`；不直接调用 KG |
| **实现状态** | ⚠️ **[IMPLEMENTED but DEGRADED]** — 纯 regex 实现，不查询 KG。已合并旧的 ReAct StateGraph 和 parse_v2 为单一确定性实现（`agent.py` 头部确认）。LLM 增强可通过 `GIS_PARSE_LLM_ENABLED` 开关后续加入，不改公开 API。 |

### execute/ — EXECUTE Agent

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/agent/gis/execute/` |
| **职责** | 空间意图 → 空间成果。消费 PARSE 产出的 intent + KG 上下文，产出分配用地/设施/轴线/道路等空间布局层。 |
| **关键文件** | `agent.py`（`build_execute_agent_graph()`，7 节点 StateGraph）、`state.py`（`ExecuteAgentState`）、`layout/`、`facility/`、`axis/`、`road/`、`README.md` |
| **依赖** | → `schema`、`kg`（KGManager）、`spatial_ops`（road_planner/ConstraintCompiler）；与 PARSE 通过 LangGraph state 通信 |
| **实现状态** | ✅ **[IMPLEMENTED]** — LAYOUT hybrid pipeline（MIP + 生成）+ `write_kg_l4` 节点（L4 写回 KG）。图架构：`route_tasks → execute_layout → execute_facility → execute_axis → execute_road → validate →(pass)→ write_l4 → END`，validate 失败重试最多 3 轮。`_write_l4_node` 写入 PlannedParcel/PlannedZone/PlannedFacility/PlannedRoad/PlannedAxis 并 `bump_version()`。 |

### explore/ — EXPLORE Agent

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/agent/gis/explore/`（当前工作树中目录为空） |
| **职责** | 独立探索代理，产出证据和候选实体引用，不产出最终规划几何。确定性 baseline + 可选 Flash 模型精炼。 |
| **关键文件** | 源码位于 `25e24847` commit（`explore/agent.py`、`explore/contracts.py`、`explore/__init__.py`），含 `ExplorationInstruction`/`ExplorationInstructionCollection` 契约 |
| **依赖** | → `app.utils`；独立有界，下游 Binder 边界 |
| **实现状态** | 🔲 **[PLANNED]** — 源码存在于 `25e24847` commit（分支 `feature/flash-llm-explore-agent`），当前 HEAD 已移除。工作树仅残留 `.pyc` 陈旧产物（已清理），目录为空。 |

---

## 模块依赖矩阵

```
Schema      ← (零依赖，底座)
Data        ← Schema
SpatialOps  ← Schema + app.utils
KG          ← Schema + SpatialOps
RAG         ← app.core (LLM/settings)
Parsing     ← Schema.contracts
Agent/gis   ← Schema + KG + SpatialOps + Parsing + RAG
```

| 模块 | Schema | Data | SpatialOps | KG | RAG | Parsing |
|---|---|---|---|---|---|---|
| Schema | — | ✗ | ✗ | ✗ | ✗ | ✗ |
| Data | ✅ | — | ✗ | ✗ | ✗ | ✗ |
| SpatialOps | ✅ | ✗ | — | ✗ | ✗ | ✗ |
| KG | ✅ | ✗ | ✅ | — | ✗ | ✗ |
| RAG | ✗ | ✗ | ✗ | ✗ | — | ✗ |
| Agent/gis | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
