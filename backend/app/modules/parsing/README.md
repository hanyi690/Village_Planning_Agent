# Parsing 模块 — 确定性 + LLM 文本提取工具层

> **定位**: 规划文本/表格/报告的结构化提取工具集，被 PARSE Agent、`report_store`、KG enrichment 与 `data/catalog` 消费
> **依赖**: `parsing → schema.contracts`；`app.core.settings`；`app.utils.logger`；`app.modules.data.providers.tianditu`（gazetteer 惰性导入）；`app.modules.schema.encodings.code_sets`（table_schema_inference）
> **空间计算禁令**: 本模块不做任何空间计算（BBox / 距离 / 面积 / 过滤），所有空间计算由 `spatial_ops/` 完成
> **Updated: 2026-08-03**

---

## 一、模块定位

parsing 是"文本 -> 结构化"的**工具层**，不含 Agent 编排逻辑。它提供四类提取能力：

| 能力类 | 技术 | 文件 | LLM 依赖 |
|-------|------|------|---------|
| **结构化摘要** | 类型化 JSON 摘要生成/解析 | `summary_generator` / `summary_parser` | zero LLM（规则式） |
| **表格语义提取** | 列语义推断 + schema 映射 | `tables` / `table_schema_inference` | zero LLM |
| **地名/语义辅助** | 天地图地理编码 / 词典匹配 / 语义枚举 | `gazetteer` / `semantics` | zero LLM |
| **管理数据** | 2024 全国 5 级行政区划加载 | `admin_code_loader` | zero LLM |
| **输出 schema** | Pydantic 类型化输出模型 | `schemas` | - |

**与 PARSE Agent 的关系**：PARSE Agent（`agent/gis/parse/agent.py`）直接调用 `tables._extract_zone_tables` / `_extract_project_tables` 等确定性提取器，产出 `schema/contracts/parse_contracts.py` 的最终契约（`SpatialPlanningIntent` / `SpatialOperation` / `SpatialConstraint`）。

**与 ReportStore 的关系**：`report_store` 通过 `summary_generator.generate_structured_summary` 生成维度报告的 JSON 摘要，通过 `summary_parser.parse_summary` 反解析供 L2/L3 依赖加载与规划文本生成使用。

---

## 二、模块结构（实际文件树）

```
backend/app/modules/parsing/
├── __init__.py                  # 公开 API（无再导出，仅模块说明）
├── schemas.py                   # Pydantic 输出 schemas: ZoneOutput/FacilityOutput/AxisOutput/
│                                #   IntentOutput + BaseDimensionSummary + 28 维度 schemas
├── semantics.py                 # ValueSemantics 枚举 + SemanticField + 跨维度 MetricConcept 映射
├── tables.py                    # 单元级列语义表格提取（零领域关键词白名单）
├── table_schema_inference.py    # 表格 schema 推断 + 行→指标/分区/设施映射
├── admin_code_loader.py         # 2024 全国 5 级行政区划数据加载（AdminCodeService 单例）
├── gazetteer.py                 # 地名词典（天地图地理编码 + fuzzy 匹配，两级回退）
├── summary_generator.py         # generate_structured_summary — 规则式 JSON 摘要
├── summary_parser.py            # parse_summary — JSON-aware 摘要反解析
└── README.md                    # 本文档
```

> ⚠️ 修正历史遗留错误：`structured_output.py`（Instructor 提取入口）**不存在**于本目录，属已废弃设计；`markdown_parser.py` / `section_classifier.py` / `regulation_extractor.py` 已于 2026-08-03 随死代码清理移除（无任何消费者，`detect_table`/`classify_section`/regex 约束提取已被 `tables.py` + PARSE Agent 取代）；`summary_generator.py` / `summary_parser.py` **仍然存在且活跃**（被 `report_store` 使用）。

---

## 三、核心文件与 API

### 3.1 schemas.py — 类型化输出模型

```python
ZoneOutput(zone_id, land_use(enum), dlbm, area_ratio[0,1], direction(enum),
           reference_feature, adjacent_to, avoid_adjacent_to, density)
FacilityOutput(facility_id, facility_type(enum), status(enum), location_hint,
               service_radius[100,2000])
AxisOutput(axis_id, axis_type(enum), direction, reference_feature)
IntentOutput(zones, facilities, axes, rationale, metadata)

BaseDimensionSummary + 28 维度 schemas（12 L1 / 4 L2 / 12 L3）
  # 字段使用 Annotated[Optional[...], SemanticField(...), Field(...)] 元数据
  # 注册表：_DIMENSION_SCHEMAS / ALL_DIMENSION_KEYS / LAYER_DIMENSIONS
get_dimension_schema(dimension_key) -> Type[BaseDimensionSummary]
get_metrics_description(dimension_key) -> Dict[str, str]
```

### 3.2 semantics.py — 跨维度指标语义

```python
class ValueSemantics(str, Enum):
    CURRENT_OBSERVED / PLANNED_TARGET / CONSTRAINT_UPPER / CONSTRAINT_LOWER /
    BASELINE_YEAR / PROJECTED / ALLOCATED

class SemanticField(semantics, unit, data_source, comparable=True)
class MetricConcept(str, Enum):  # 11 概念：CONSTRUCTION_AREA / FARMLAND_AREA / ... / ROAD_LENGTH

CROSS_DIMENSION_METRICS: Dict[MetricConcept, List[FieldRef]]   # 跨维度字段映射
get_comparable_fields(concept, semantics) -> List[FieldRef]
get_constraint_fields(concept) -> List[FieldRef]
infer_semantics_from_field_name(field_name) -> Optional[ValueSemantics]
```

消费者：`tools/gis/_conflict/detector.py` / `resolver.py`（同名不同义指标冲突检测）。

### 3.3 tables.py — 单元级列语义提取

**零领域关键词白名单**：纯结构解析（表头 + `| :--- |` 分隔行），列语义按**单位**判定（`%` → ratio，公顷/ha/亩/㎡ → area，表头含位置关键词且无数值 → location）。

```python
_extract_zone_tables(text) -> List[ZoneTarget]        # 需名称列 + 面积/比例列 + ≥60% 名称含"区"
_extract_project_tables(text) -> List[FacilityTarget] # 表头含 项目/工程/设施名称
```

> ⚠️ 依赖说明：`tables.py` 导入 `app.agent.gis.parse.agent._direction_from_location`——**存在 parsing → agent 的反向依赖边**，与"纯工具层"定位相悖，属已知技术债。

### 3.4 table_schema_inference.py — 表格 schema 推断

```python
class TableSchemaType(Enum): INDICATOR_TABLE / LAND_USE_TABLE / FACILITY_TABLE / UNKNOWN

infer_table_schema(headers) -> TableSchemaType
map_table_to_indicators(rows, headers) -> Optional[PlanningIndicatorTable]      # 附表1
map_table_to_zone_targets(rows, headers) -> Optional[List[ZoneTarget]]          # 附表2
map_table_to_facility_targets(rows, headers) -> Optional[List[FacilityTarget]]
infer_and_map_table(headers, rows) -> Tuple[TableSchemaType, Any]               # 主入口
# _parse_number 处理单位/千分位/万；_resolve_vne 用 GHYTBM_TO_VNE
```

### 3.5 admin_code_loader.py — 行政区划

```python
@dataclass AdminCodeRecord: code, name, level, pcode, category=0

class AdminCodeService:   # 单例（__new__）
    get_by_code / get_by_name / get_children / get_parent_chain /
    get_parent_chain_with_names / search(keyword, level, limit=20) /
    get_provinces/cities/counties/towns/villages / resolve_hierarchy(...) / stats

get_admin_code_service() -> AdminCodeService
# 数据源：data/gis/china_area-2024/area_code_2024.csv.gz（2024 国统局 5 级编码）
```

消费者：`data/catalog/catalog.py`（行政区划代码兜底定位）。

### 3.6 gazetteer.py — 地名解析

```python
PlaceNameResolver(residential_clusters)   # VillageAnchor = (name, lon, lat, parcel_ids)
resolve(place_name) -> dict               # {name, lon, lat, village_name, parcel_ids,
                                          #  confidence, method∈{geocode,fuzzy,unresolved}}
resolve_batch(place_names) -> List[dict]
# Tier 1: 天地图 geocode（前置"广东省梅州市"前缀）→ 最近 VillageGroup（Haversine，阈值 5km）
# Tier 2: fuzzy 子串匹配（包含/短名/前后缀）——零 API 成本
# confidence = max(0.5, 0.9 - dist/50000)
```

消费者：`tools/gis/parse.py`（`resolve_place` 工具）。

### 3.7 summary_generator.py / summary_parser.py

```python
# 规则式（无 LLM）：用维度 Pydantic schema 构建类型化摘要
async generate_structured_summary(dimension_key, layer, content) -> str   # JSON string

# JSON-aware 反解析，总附加 dimension_key/layer 标签
parse_summary(summary, dimension_key="", layer=1) -> Dict[str, Any]
```

消费者：`agent/analysis/node.py::_generate_summary`、`services/report_store.py`。

---

## 四、依赖

- **内部**: `app.core.settings`（`GIS_DATA_DIR`）；`app.utils.logger`；`app.modules.schema.contracts.parse_contracts`（SpatialPreference/ZoneTarget/FacilityTarget/PlanningIndicatorTable/SpatialConstraint）；`app.modules.schema.contracts.semantic_fields`（SemanticMetadata）；`app.modules.data.providers.tianditu`（TiandituProvider，惰性）；`app.modules.schema.encodings.code_sets`（GHYTBM_TO_VNE）；`app.agent.gis.parse.agent`（`_direction_from_location`，**反向依赖，技术债**）
- **外部**: `pydantic>=2.12`；stdlib（re/csv/gzip/json/math/pathlib/dataclasses/enum/typing）
- **零空间计算依赖**：不导入 geopandas/shapely（设计使然）

---

## 五、测试覆盖

无独立 `test_parsing/` 目录，直接覆盖：
- `tests/unit/test_parse_table_extraction.py` — `agent.gis.parse.parse()` 端到端表格提取（zone ratios / facility locations / dedup merge）
- `tests/unit/test_parse_instruction.py` — 【INSTRUCTION】表格解析
- `tests/unit/test_vocab_extractor.py` — 经 vocab_extractor 使用 `_extract_zone_tables`
- `tests/unit/test_report_store.py` — 摘要生成/解析链路
- 集成：`test_parse_agent_llm.py`、`test_kg_jintian_e2e.py`（经 agent 间接覆盖）

---

## 六、与上下游模块关系

| 方向 | 模块 | 关系 |
|------|------|------|
| 上游 | `schema/contracts/parse_contracts` | 提供最终契约类型（ZoneTarget/FacilityTarget 等） |
| 下游 | `agent/gis/parse` | PARSE 规则解析器调用 `tables._extract_*` 等 |
| 下游 | `services/report_store` | 经 `summary_generator` / `summary_parser` 生成/解析维度摘要 |
| 下游 | `agent/gis/vocab_extractor` | 使用 `_extract_zone_tables` |
| 下游 | `modules/kg/enrichment/bindings` | 使用 `_extract_project_tables` / `_extract_zone_tables` |
| 下游 | `data/catalog/catalog` | 使用 `get_admin_code_service` |
| 语义 | `tools/gis/_conflict` | 使用 `semantics.MetricConcept` / `ValueSemantics` |

---

## 七、设计原则

1. **确定性优先**：能 regex/markdown 解析的不用 LLM
2. **LLM 兜底**：分节打分 <2 或 regex 未匹配的实质性行才路由给 LLM
3. **零空间计算**：parsing 不做任何几何运算，所有空间计算由 `spatial_ops/` 完成
4. **零空间数据**：parsing 不持有 GeoJSON/几何
5. **工具无状态**：所有函数纯输入纯输出，状态由 PARSE Agent state 管理
6. **单元级语义**：表格列语义按单位推断（`%`/公顷），不依赖领域关键词白名单

---

## 八、相关文档

- `backend/app/agent/gis/parse/README.md` — PARSE Agent（parsing 的主要消费者）
- `backend/app/modules/kg/README.md` — KG 模块（enrichment 消费 parsing 表格提取）
- `backend/app/modules/schema/contracts/parse_contracts.py` — 最终契约类型
