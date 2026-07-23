# PARSE + KG：专业规划范式对齐差距分析

> **Status: [DIAGNOSTIC]** | **Type: Gap Analysis** | **Version: v2** | **Updated: 2026-07-22**
> **Scope**: PARSE Agent Schema + KG Builder + 现有Schema全景 — 对照专业教材/规范发现的系统性差距
> **References**: BIBLIOGRAPHY.md §A2-3, §A5, §B1, §B5-7, §B10
> **Source Documents**:
> - 《村庄规划用地分类指南》(住建部, 2014) — 3大类10中类15小类 V/N/E 分类体系
> - 《广东省村庄规划编制基本技术指南（试行）》(广东省自然资源厅, 2019) — 附表1/2/附录3/附录5/表2-6
> - 《实用性村庄规划编制手册》——李巍等 (369页) — §2.6 GIS实验操作, §3-4 规划定位与空间布局
> - 《乡村规划原理》——李京生 — 空间结构理论, 规划体系演进
> **Schema Baseline** (本章 §A-I 记录):
> - `parse/state.py` (398行) — ParseAgentState + 全部 output schema
> - `contracts.py` (293行) — SpatialContext + UnifiedSpatialIntent
> - `spatial_types.py` (731行) — 5组25+ dataclass
> - `canonical.py` (169行) — GISDataBundle
> - `dicts/` — 6套编码 YAML + 5份规则 YAML
> - `kg/ontology.py` (107行) — 16实体+11关系
> - `kg/builder.py` (1286行) — PlanningKG

---

## 现有 Schema 全景 (Baseline)

> 本章记录系统中已存在的全部 Schema 定义，作为差距分析的基线。

### A. PARSE Schema 层 (`backend/app/agent/gis/parse/state.py`)

#### A1. Section 分类

```python
class SectionInfo(BaseModel):
    section_id: str = ""
    title: str = ""
    section_type: Literal[
        "preamble", "target", "regulation", "project_table",
        "land_use_table", "indicator_table", "heritage_table",
        "facility_table", "ecological_table", "spatial_layout",
        "protection", "infrastructure", "governance",
    ] = "preamble"
    content: str = ""
    has_table: bool = False

class SectionClassificationResult(BaseModel):
    sections: List[SectionInfo]
    document_type: Literal["village_plan", "special_plan", "implementation", "unknown"] = "unknown"
```

#### A2. 空间操作 (SpatialOperation) — 逐条执行指令

```python
class SpatialAnchor(BaseModel):
    reference: str = ""                        # 锚点名称
    offset: Optional[str] = None               # 偏移描述
    secondary_ref: Optional[str] = None
    secondary_offset: Optional[str] = None
    candidate_parcels: List[str] = []          # 候选地块 BSM 列表
    confidence: float = 0.0
    resolution_status: Literal["anchored", "partial", "unresolved"] = "unresolved"

class ComplianceCheck(BaseModel):
    in_construction_boundary: bool = True
    not_farmland: bool = True
    not_ecological_redline: bool = True
    within_village_boundary: bool = True

class SpatialOperation(BaseModel):
    action: Literal["create", "split", "merge", "modify", "reclassify"]
    spatial_anchor: Optional[SpatialAnchor] = None
    location_desc: Optional[str] = None        # 自由文本回退
    target_parcels: List[str] = []             # BSM 列表
    source_text: str = ""
    confidence: float = 1.0
    confidence_level: Literal["high", "medium", "low"] = "high"
    needs_confirmation: bool = True
    # create 参数
    project_name: Optional[str] = None
    area_sqm: Optional[float] = None
    land_use_name: Optional[str] = None
    land_use_code: Optional[str] = None        # GHYTBM 附录5编码
    # split/merge 参数
    source_bsm: Optional[str] = None
    split_ratio: Optional[float] = None
    source_bsms: Optional[List[str]] = None
    # modify/reclassify 参数
    field_changes: Optional[Dict[str, Any]] = None
    new_qmdlbm: Optional[str] = None           # 期末地类编码
    affected_layers: List[str] = []
    compliance: Optional[ComplianceCheck] = None
    article_ref: str = ""
    natural_village: str = ""
```

#### A3. 空间约束 (SpatialConstraint) — 可计算规则

```python
class SpatialRule(BaseModel):
    operation: Literal["no_overlap", "buffer_exclusion", "contained_by",
                        "adjacent_to", "distance_within"] = "no_overlap"
    subject: str = ""
    object: str = ""
    distance_m: Optional[float] = None

class SpatialConstraint(BaseModel):
    type: Literal["area_constraint", "spatial_constraint",
                  "building_constraint", "use_constraint",
                  "boundary_constraint"] = "spatial_constraint"
    source_text: str = ""
    article_ref: str = ""
    priority: Literal["mandatory", "recommended", "aspirational"] = "mandatory"
    # 面积约束
    land_use: Optional[str] = None
    target_area_ha: Optional[float] = None
    operator: Optional[Literal["<=", ">=", "=="]] = None
    # 空间约束
    zone_type: Optional[str] = None
    spatial_rule: Optional[SpatialRule] = None
    # 建筑约束
    max_area_sqm: Optional[float] = None
    max_height_m: Optional[float] = None
    max_floors: Optional[int] = None
    setback_m: Optional[float] = None
```

#### A4. 空间规划意图 (SpatialPlanningIntent) — LLM 结构化输出

```python
class SpatialPreference(BaseModel):
    direction: Optional[str] = None
    reference: Optional[str] = None

class AdjacencyRules(BaseModel):
    prefer: List[str] = []
    avoid: List[str] = []

class ZoneTarget(BaseModel):
    land_use: str = ""                         # 自由字符串
    area_ratio: float = 0.0
    dlbm: Optional[str] = None
    spatial_preference: Optional[SpatialPreference] = None
    adjacency_rules: Optional[AdjacencyRules] = None
    density: Literal["high", "medium", "low"] = "medium"

class FacilityTarget(BaseModel):
    type: str = ""
    status: Literal["existing_preserve", "planned_new",
                    "planned_expand", "planned_relocate"] = "existing_preserve"
    location_hint: str = ""
    service_radius: Optional[int] = None
    anchor_village: Optional[str] = None

class AxisTarget(BaseModel):
    direction: str = ""
    reference_feature: str = ""
    connects: List[str] = []

class SpatialPlanningIntent(BaseModel):
    village_name: str = ""
    planning_period: str = ""
    zone_targets: List[ZoneTarget] = []
    facilities: List[FacilityTarget] = []
    development_axes: List[AxisTarget] = []
    total_area_ha: Optional[float] = None
    construction_area_ha: Optional[float] = None
    farmland_area_ha: Optional[float] = None
    ecological_area_ha: Optional[float] = None
    population: Optional[int] = None
```

#### A5. ParseAgentState — PARSE 子图内部状态

```python
class ParseAgentState(BaseModel):
    planning_text: str = ""
    village_name: str = ""
    spatial_context: SpatialContext = Field(default_factory=SpatialContext)
    section_map: List[SectionInfo] = []
    parse_strategy: Literal["full", "incremental", "section_only"] = "full"
    # 提取中间结果
    raw_operations: List[SpatialOperation] = []
    raw_constraints: List[SpatialConstraint] = []
    raw_targets: SpatialPlanningIntent = Field(default_factory=SpatialPlanningIntent)
    raw_tables: Dict[str, Any] = {}
    # 验证
    validation_errors: List[str] = []
    parse_round: int = 0
    is_valid: bool = False
    # 最终输出
    operation_sequence: List[SpatialOperation] = []
    constraint_set: List[SpatialConstraint] = []
    planning_intent: SpatialPlanningIntent = Field(default_factory=SpatialPlanningIntent)
    # 中间产物（Think-Then-Format 模式）
    draft_operations: str = ""
    draft_targets: str = ""
    # 编码/地名映射（并行fan-out）
    code_mappings_projects: Dict[str, str] = {}
    place_mappings_projects: Dict[str, dict] = {}
    code_mappings_targets: Dict[str, str] = {}
    place_mappings_targets: Dict[str, dict] = {}
    # LLM trace（并行安全）
    messages: List[Any] = []
    llm_trace_projects: List[Dict[str, Any]] = []
    llm_trace_targets: List[Dict[str, Any]] = []
```

---

### B. GIS Schema 合约层 (`backend/app/modules/gis/schema/contracts.py`)

#### B1. SpatialContext — GIS→Agent 空间上下文

```python
class LanduseEntry(BaseModel):
    dlbm: str = ""
    name: str = ""
    count: int = 0
    area_ha: float = 0.0
    zone_type: str = ""
    planning_zone: str = ""

class NaturalVillageAnchor(BaseModel):
    name: str = ""
    center: Tuple[float, float] = (0.0, 0.0)
    parcel_ids: List[str] = []
    dominant_landuse: str = ""
    adjacent_to: List[str] = []

class SpatialRelation(BaseModel):
    subject: str = ""
    relation: Literal["east_of", "west_of", "north_of", "south_of",
                       "adjacent_to", "contains", "contained_by",
                       "near", "along", "between"] = "adjacent_to"
    object: str = ""
    confidence: float = 1.0
    source: Literal["geometry_computed", "alias_lookup", "llm_inferred"] = "geometry_computed"

class ConstraintSummary(BaseModel):
    zone_type: str = ""
    rule: str = ""
    area_ha: Optional[float] = None
    geometry_type: Optional[str] = None
    overlaps_with: List[str] = []

class SpatialContext(BaseModel):
    parcel_count: int = 0
    total_area_ha: float = 0.0
    construction_boundary_ha: float = 0.0
    landuse_distribution: List[LanduseEntry] = []
    village_center: Optional[Tuple[float, float]] = None
    natural_villages: List[NaturalVillageAnchor] = []
    spatial_relations: List[SpatialRelation] = []
    constraint_summary: List[ConstraintSummary] = []
    zone_adjacency: Dict[str, List[str]] = {}
```

#### B2. UnifiedSpatialIntent — LAYOUT 的单一意图模型

```python
class Direction(str, Enum):
    CENTER="center", NORTH="north", SOUTH="south", EAST="east", WEST="west",
    NORTHEAST="northeast", NORTHWEST="northwest",
    SOUTHEAST="southeast", SOUTHWEST="southwest",
    PERIPHERY="periphery", EAST_WEST="east-west", NORTH_SOUTH="north-south"

class Density(str, Enum):
    HIGH="high", MEDIUM="medium", LOW="low"

class ZoneIntent(BaseModel):
    zone_id: str = ""
    land_use: str = ""                         # 自由字符串
    dlbm: str = ""
    dlbm_aliases: List[str] = []
    area_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    direction: Direction = Direction.CENTER
    reference_feature: str = ""
    adjacent_to: List[str] = []
    avoid_adjacent_to: List[str] = []
    density: Density = Density.MEDIUM
    preserve_existing: bool = True

class FacilityIntent(BaseModel):
    facility_id: str = ""
    facility_type: str = ""
    target_zone: str = ""
    location_hint: str = ""
    status: str = "existing"

class AxisIntent(BaseModel):
    axis_id: str = ""
    axis_type: str = ""
    direction: Direction = Direction.CENTER
    connects: List[str] = []
    label: str = ""

class ConstraintIntent(BaseModel):
    constraint_id: str = ""
    constraint_type: str = ""
    geometry_ref: str = ""
    strict: bool = True

class UnifiedSpatialIntent(BaseModel):
    zones: List[ZoneIntent] = []
    facilities: List[FacilityIntent] = []
    axes: List[AxisIntent] = []
    constraints: List[ConstraintIntent] = []
    metadata: Dict[str, Any] = {}
```

---

### C. 空间要素类型层 (`backend/app/modules/gis/schema/spatial_types.py`)

共 5 组(Groups A-E)，25+ 个 dataclass，覆盖村庄规划全要素。**此层数据齐全但 PARSE/KG 未引用。**

#### Group A: 行政区划 (2 类型)

| 类型 | 几何 | 关键字段 |
|------|------|----------|
| `AdminArea` | Polygon | djzqdm(12位区划代码), djzqmc, mj(椭球面积) |
| `AdminBoundaryLine` | Line | djzqdm, boundary_type(670500=村界) |

#### Group B: 地类图斑 (3 类型)

| 类型 | 编码体系 | 关键字段 |
|------|----------|----------|
| `BaseLandUseParcel` | 因层而异 | dlbm, dlbm_system, name, area_sqm, zone_type, planning_zone, primary_zone |
| `CurrentLandUseParcel` | appendix5 | sddlbm (三调编码) |
| `PlannedLandUseParcel` | tugui + appendix5 + ghflbm | ghytbm, ghflbm, qmdlbm(期末), qmghflbm, ghytmc |

`primary_zone` 字段标注三区归属（生态空间/农业空间/建设空间）。

#### Group C: 现状要素 (5 类型)

| 类型 | 几何 | 关键字段 |
|------|------|----------|
| `CurrentBuilding` | Polygon | building_type, floors, area_sqm, structure |
| `CurrentRoad` | Line | shape_length, road_level(村道/乡道/县道), road_width |
| `CurrentFacility` | Point/Polygon | facility_type, facility_name, scale, service_radius, category |
| `CurrentAnnotation` | Point | text(注记文本), category(现状设施点/村名) |
| (PlaceNameAnnotation) | — | 已删除，由 CurrentAnnotation(category="村名") 覆盖 |

#### Group D: 规划要素 (13 类型) — 最完整的专业层

| 类型 | 规范来源 | 关键字段 |
|------|----------|----------|
| `ControlLine` (基类) | 广东省技术指南 | mj, protection_level |
| `FarmlandProtection` | 三区三线成果 | xzqhdm, xzqhmc, jbnt_mj |
| `EcologicalRedline` | 三区三线成果 | district, city, zone, object_id |
| `CultivatedLandTarget` | 三条控制线 | target_level |
| `UrbanDevBoundary` | 三条控制线 | dev_type(集中建设/弹性发展/特殊用途) |
| `VillageDevBoundary` | 目标年规划 | boundary_type(刚性/弹性) |
| `HazardControlLine` | 安全控制线 | hazard_type(崩塌/滑坡/泥石流), risk_level(高/中/低) |
| `FloodControlLine` | 安全控制线 | flood_frequency, control_elevation |
| `HistoricalProtection` | 历史文化保护 | buff_dist, protection_scope, protection_level |
| `**ConstructionCtrlZone**` ★ | **广东省技术指南 表6** | tdkjgzfqdm(01-06), mj, gzfqmc |
| `**LandUseZone**` ★ | **广东省技术指南 表5** | tdyfqdm(4位乡规分类), ytfqmc |
| `**PlanningScope**` ★ | **广东省技术指南 表3** | xzqhdm, mj(GHCFW规划村范围) |
| `ConditionalConstructionZone` | 有条件建设区 | lx("有条件建设区"), ≤现建×20%约束 |
| `GeologicalHazardPoint` | 地质灾害点 | name, longitude, latitude, hazard_type, scale |
| `PlannedRoad` | 规划道路 | shape_length, ln_type, road_level |
| `PlannedAnnotation` | 规划注记 | text, category(规划设施点) |

★ 标记为核心必选图层（广东省技术指南表2：GHCFW/QMDLTB/TDYT/JSYDGZQ 4个汇交图层）

`ConstructionCtrlZone` 定义了关键常量：
```python
ALLOWED_CONSTRUCTION = "01"     # 允许建设区
RESTRICTED = "02"               # 限制建设区
CONDITIONAL = "03"              # 有条件建设区
PROHIBITED = "04"               # 禁止建设区
BASIC_FARMLAND_ZONE = "05"      # 永久基本农田保护区
ECOLOGICAL_REDLINE_ZONE = "06"  # 生态保护红线区
```

`SPACE_CONTROL_ZONE_TYPES` = `{"01": "允许建设区", ..., "06": "生态保护红线区"}`

#### Group E: 基础地理信息 (3 类型, 标为"🔴 未实现")

| 类型 | 用途 | 状态 |
|------|------|------|
| `ContourLine` | 等高线 (1:2000 DLG) | 🔴 未实现 |
| `ElevationPoint` | 高程点 (1985国家高程基准) | 🔴 未实现 |
| `WaterFeature` | 水系要素 (线/面) | 🔴 未实现 |

---

### D. 规范数据容器层 (`backend/app/modules/gis/schema/canonical.py`)

```python
class GISDataBundle(BaseModel):
    """村庄全部GIS数据 — pipeline 中的单一通行对象"""
    boundary: Optional[GeoFeature] = None      # 村界
    landuse: List[Any] = []                    # List[BaseLandUseParcel]
    roads: List[GeoFeature] = []
    water_bodies: List[GeoFeature] = []
    annotations: List[GeoFeature] = []
    dem: Optional[Any] = None                  # 🔴 字段已预留, 未填充
    metadata: GISMetadata
    standard_version: str = ""
```

---

### E. YAML 规则数据层 (`backend/app/modules/gis/schema/dicts/`)

#### E1. 编码系统 (`dicts/encodings/`) — 6 套

| 文件 | 编码体系 | 用途 | 条目数 |
|------|----------|------|--------|
| `gbt21010.yaml` | GB/T 21010-2017 | 土地利用现状分类 (DLBM) | 73个二级类 |
| `tugui.yaml` | 广东省土规数据库标准 | 期末地类编码 (QMDLBM) | — |
| `appendix5.yaml` | 广东省技术指南 附录5 | 规划用途编码 (GHYTBM) | — |
| `ghflbm.yaml` | 规划分类编码 | 规划分类 (比appendix5粗) | — |
| `ydyhfldm.yaml` | 用地用海分类代码 | 三级分类 (24/113/140) | — |
| `vne.yaml` | V/N/E 用地分类 | 村庄规划用地分类 | — |

#### E2. 规划规则 (`dicts/rules/`) — 5 份, PARSE/KG 未引用

| 文件 | 内容 | 版本 | 关键数据 |
|------|------|------|----------|
| `planning_targets.yaml` | 附表1 规划目标表 | 2026_GD_V1 | 7指标(code I01-I07, name, unit, attribute约束性/预期性) |
| `land_use_structure.yaml` | 附表2 土地利用结构表 | 2026_GD_V1 | 19子类(code, name, parent, ghytbm) |
| `planning_zone_rules.yaml` | 规划分区决策规则 | 2026_GD_V1 | 4个管制区(510-540), `planning_zone_to_primary_zone`映射, 16条决策规则 |
| `three_line_types.yaml` | 三线管控图层定义 | 2026_GD_V1 | 3条控制线(颜色/线型/GDB key), 建设区+注记类 |
| `gdb_layers.yaml` | GDB图层规则 | — | — |
| `field_defaults.yaml` | 字段默认值 | — | — |

#### E3. 编码分类引擎 (`dicts/` 基础设施)

| 文件 | 用途 |
|------|------|
| `loader.py` | `DictionaryCenter` — 所有YAML的加载/查询中心 (`get_center()`) |
| `candidate_engine.py` | 编码候选推荐引擎 |
| `__init__.py` | 模块导出 |
| `references/` | 编码系统间转换映射 (如 sddlbm→ydyhfldm) |

---

### F. KG 知识图谱层 (`backend/app/modules/kg/`)

#### F1. Ontology (`ontology.py`) — 当前 16 实体 + 11 关系

```python
PLN = Namespace("http://village-planning.org/ontology#")

class EntityTypes:
    Parcel, Zone, Constraint, Indicator,       # Phase 0
    Project, Village, Regulation, LandUsePlan,  # Phase 1
    Facility, Axis, Road, WaterBody, BuildingGroup,
    LandConservationPlan, ReforestationPlan, GridRegulation  # Phase 2

class Relations:
    adjacent_to, within_zone, constrained_by,   # Phase 0
    designated_as, protects, located_in,        # Phase 1
    achieves, conflicts_with, derived_from,
    serves, connects
```

#### F2. KG Builder (`builder.py`) — 硬编码模式

```python
# 仅4个粗分区 (vs 标准15小类)
ZONE_TYPE_PATTERNS = {
    "农田保护区": {"color": "#FFE4B5", "restrictions": ["禁止非农化", "禁止非粮化"]},
    "村庄建设区": {"color": "#FF6347", "restrictions": ["建设用地规模受控"]},
    "生态保护区": {"color": "#2E8B57", "restrictions": ["禁止工业开发", "禁止城镇化"]},
    "一般农业区": {"color": "#98FB98", "restrictions": ["限制大规模非农建设"]},
}

# 仅7条约束 (vs 标准16条决策规则)
CONSTRAINT_PATTERNS = [
    {"metric_key": "建设用地规模_公顷", "constraint_id": "construction_cap", ...},
    {"metric_key": "耕地保有量_公顷", "constraint_id": "farmland_min", ...},
    {"metric_key": "永久基本农田_公顷", "constraint_id": "permanent_farmland_min", ...},
    {"metric_key": "生态保护红线面积", "constraint_id": "ecological_redline_min", ...},
    {"metric_key": "森林覆盖率_百分比", "constraint_id": "forest_coverage_min", ...},
    {"metric_key": "新增建设用地_公顷", "constraint_id": "construction_expansion", ...},
    {"metric_key": "林地保有量_公顷", "constraint_id": "forest_land_min", ...},
]

# 额外5条语义约束
SEMANTIC_CONSTRAINT_MAP = {
    "max_construction_ha": {...},
    "min_farmland_protection_ha": {...},
    "min_ecological_redline_ha": {...},
    "planned_construction_ha": {...},
    "planned_farmland_ha": {...},
}

# 仅3条管制规则 (vs 标准6大类)
REGULATION_TYPES = {
    "永久基本农田保护": {"protects": "农田保护区", "field": "farmland_area_ha"},
    "生态保护红线": {"protects": "生态保护区", "field": "ecological_redline_ha"},
    "村庄建设边界": {"protects": "村庄建设区", "field": "construction_area_ha"},
}

# _add_indicators() — 直接dump metric key-value, 无结构化字段
# _add_zones_from_intent() — Dict .get() 访问, 非typed
# build_from_intent(intent: Dict[str, Any]) — 参数为Dict
```

---

### G. Schema 转换链 (当前数据流)

```
规划文本 → PARSE Agent (parse/state.py)
              ↓
         SpatialPlanningIntent  →  SpatialOperation[]
            (A4)                     (A2)
         SpatialConstraint[]        ParseAgentState
            (A3)                     (A5)
              ↓
         layout_pipeline._parse_intent_node()
              ↓ intent = planning_intent (typed)
              ↓
    ┌─────────┼─────────┐
    ↓         ↓         ↓
  KG       allocate   generate
builder   .py          .py
(build_    _intent_    _intent_
from_      to_         from_
intent)    targets()   typed()
  ↓           ↓           ↓
Dict        Dict        Unified
.get()      .get()      Spatial
路径       分支         Intent
                         ↓
                    ZoneGenerator
                    FacilityPlacer
                    AxisBuilder
```

**问题**：`build_from_intent` 和 `_intent_to_targets` 仍用 `Dict.get()` 模式；`_intent_from_typed` 用 `hasattr` 双重路径（typed + dict fallback）。

---

### H. 现有 GIS 分析模块

| 模块 | 文件 | 状态 |
|------|------|------|
| `accessibility.py` | 交通可达性 | ✅ 存在, 无 Pydantic Schema |
| `coverage.py` | 服务范围覆盖 | ✅ 存在, 无 Pydantic Schema |
| `isochrone.py` | 等时圈分析 | ✅ 存在, 无 Pydantic Schema |
| `metrics_calculator.py` | 用地指标计算 | ✅ 存在, KG Builder 调用 |
| `dynamic_zoning.py` | 动态分区 | ✅ 存在 |
| `validation/` | 设施/布局验证 | ✅ 存在 |
| `terrain.py` | DEM地形分析 | ❌ 不存在 |
| `suitability.py` | 用地适宜性评价 | ❌ 不存在 |
| `carrying_capacity.py` | 承载力评价 | ❌ 不存在 |

---

### I. 专业知识体系 ↔ Schema 对照总表

| 专业标准 | 标准条款 | 对应 Schema | 对齐状态 |
|----------|----------|-------------|----------|
| 三区三线 | 生态/农业/建设空间 + 三条控制线 | `BaseLandUseParcel.primary_zone` | ⚠️ 字段存在但 PARSE/KG 未系统性使用 |
| 建设用地管制区(510-540) | 广东省技术指南 表6 | `ConstructionCtrlZone` (spatial_types) | ✅ dataclass 定义齐全，PARSE 未引用 |
| 土地用途分区 | 广东省技术指南 表5 | `LandUseZone` (spatial_types) | ✅ dataclass 定义齐全，PARSE 未引用 |
| 附表1 规划目标表 | 7指标×3列 | `planning_targets.yaml` | ✅ YAML 定义齐全，PARSE 未引用 |
| 附表2 土地利用结构表 | 19子类×4列 | `land_use_structure.yaml` | ✅ YAML 定义齐全，PARSE 未引用 |
| 附录3 管制规则 | 6大类 | 无 | ❌ 缺失 |
| 附录5 用地分类表 | GHYTBM 编码 | `appendix5.yaml` | ✅ YAML + DictionaryCenter |
| V/N/E 分类 | 3大类10中类15小类 | `vne.yaml` | ✅ YAML 存在，PARSE 未使用 |
| GB/T 21010 三调分类 | 73个二级类 | `gbt21010.yaml` | ✅ YAML + DictionaryCenter |
| 双评价 | 生态/农业/城镇适宜性 | 无 | ❌ 缺失 |
| 数据库要素图层 | 广东省技术指南 表2 | `GDB_LAYER_REGISTRY` (gdb.py) | ✅ 12层定义 |
| 村庄规划数据库汇交 | 附件1/2 | `gdb.py` | ✅ 字段/命名规范 |
| GIS 地形分析 | 高程/坡度/坡向/起伏度 | `analysis/terrain.py` | ❌ 不存在 |

---

## 总览

| 差距编号 | 类别 | 严重度 | 简述 |
|----------|------|--------|------|
| G1 | PARSE | **Critical** | 用地分类体系缺失 — 无 V/N/E 3大类10中类15小类层级 |
| G2 | PARSE | **Critical** | "一图一表一规则"输出结构缺失 |
| G3 | PARSE | **High** | 规划目标表(附表1)未建模 — 7指标×3列结构缺失 |
| G4 | PARSE | **High** | 土地利用结构调整表(附表2)未建模 — 19子类×4列结构缺失 |
| G5 | PARSE | **Critical** | 管制规则(附录3)未建模 — 当前仅5个通用约束类型 |
| G6 | PARSE | **High** | 三区三线空间结构缺失 |
| G7 | PARSE | **Medium** | Section 分类不匹配 — 缺5种专业section类型 |
| G8 | PARSE | **Medium** | 双评价(GIS分析基础)缺失 |
| K1 | KG | **Critical** | V/N/E 精细分类三元组缺失 — 仅硬编码4个粗分区 |
| K2 | KG | **Critical** | 管制规则 RDF 实体缺失 — 仅3条规则 |
| K3 | KG | **High** | 规划指标表三元组缺失 — 指标无基期/目标/变化量结构 |
| K4 | KG | **High** | Ontology 缺失核心概念 — 缺6实体+4关系 |
| K5 | KG | **Medium** | `build_from_intent` 仍用 Dict 路径 |
| K6 | KG | **Medium** | 硬编码模式未替换为 YAML 规则 |

---

## PARSE Agent 差距详情

### G1. 用地分类体系缺失 (Critical)

**对照规范**：《村庄规划用地分类指南》表2.2.2

标准定义 3大类(V/N/E)、10中类、15小类的完整层级：

```
V 村庄建设用地
  V1 村民住宅用地
    V11 住宅用地
    V12 混合式住宅用地
  V2 村庄公共服务用地
    V21 村庄公共服务设施用地
    V22 村庄公共场地
  V3 村庄产业用地
    V31 村庄商业服务业设施用地
    V32 村庄生产仓储用地
  V4 村庄基础设施用地
    V41 村庄道路用地
    V42 村庄交通设施用地
    V43 村庄公用设施用地
  V9 村庄其他建设用地
N 非村庄建设用地
  N1 对外交通设施用地
  N2 国有建设用地
E 非建设用地
  E1 水域
    E11 自然水域
    E12 水库
    E13 坑塘沟渠
  E2 农林用地
    E21 设施农用地
    E22 农用道路
    E23 其他农林用地
  E9 其他非建设用地
```

**当前实现**：`parse/state.py` `ZoneTarget`

```python
class ZoneTarget(BaseModel):
    land_use: str = ""          # 自由字符串, 无枚举约束
    area_ratio: float = 0.0
    dlbm: Optional[str] = None  # 仅有附录5编码引用
    density: Literal["high", "medium", "low"] = "medium"
```

**差距**：
- 无 V/N/E 大类概念
- 无 10 中类 / 15 小类层级
- `land_use` 是自由字符串 — 可以是任意值，无法保证与标准对齐
- 缺少 `parent_category`、`vne_code`、`sub_class` 等层级字段

**已有可用数据**：
- `dicts/encodings/vne.yaml` — VNE 编码字典
- `dicts/rules/land_use_structure.yaml` — 附表2 的 19 个用地分类 (含 code/name/parent/ghytbm)
- `spatial_types.py` `LandUseZone` — 土地用途分区 dataclass (含 tdyfqdm 编码)

---

### G2. "一图一表一规则"输出结构缺失 (Critical)

**对照规范**：《广东省技术指南》第四章"规划成果"

> 村庄规划基本成果应包括"一图一表一规则"，分别为村庄规划总图、近期建设项目表和村庄规划管制规则。

要求：
- 村庄规划总图：5条控制线 + 用地布局 + 附表1 + 附表2
- 近期建设项目表(附录2)：11列 (项目类型/名称/空间位置/用地面积/建筑面积/资金规模/筹措方式/责任主体/协作部门/建设方式/备注)
- 村庄规划管制规则(附录3)：6大类

**当前实现**：`SpatialPlanningIntent` 仅输出

```python
class SpatialPlanningIntent(BaseModel):
    village_name: str = ""
    planning_period: str = ""
    zone_targets: List[ZoneTarget]       # → 对应"图"的部分内容
    facilities: List[FacilityTarget]     # → 对应"近期项目"的一部分
    development_axes: List[AxisTarget]   # → 自定义概念, 不在标准中
    total_area_ha: Optional[float]
    construction_area_ha: Optional[float]
    farmland_area_ha: Optional[float]
    ecological_area_ha: Optional[float]
    population: Optional[int]
```

**差距**：
- 缺少 `PlanningMap` (规划总图) 结构化输出
- 缺少 `RecentProjectTable` (近期建设项目表) — 11 列结构
- 缺少 `ControlRuleSet` (管制规则) — 6 大类
- `AxisTarget` 是自定义概念，标准中用 "村庄建设边界"+"产业空间布局" 替代

---

### G3. 规划目标表(附表1)未建模 (High)

**对照规范**：《广东省技术指南》附表1

7 个指标 × 3 列时间维度：

| 指标 | 属性 | 
|------|------|
| 耕地保有量 | 约束性 |
| 基本农田保护面积 | 约束性 |
| 村庄建设用地规模 | 约束性 |
| 公共服务设施用地规模 | 预期性 |
| 基础设施用地规模 | 预期性 |
| 户均宅基地 | 预期性 |
| 人均村庄建设用地 | 预期性 |

每项有：基期年值 / 目标年值 / 变化量

**当前实现**：散落在 `SpatialPlanningIntent` 的裸字段

```python
construction_area_ha: Optional[float]  # 仅一个时间点
farmland_area_ha: Optional[float]      # 仅有现状值
ecological_area_ha: Optional[float]    # 无指标属性标记
population: Optional[int]              # 无户均/人均计算
```

**差距**：
- 未区分"约束性"vs"预期性"
- 缺少基期年/目标年/变化量的时间维度
- 缺 4 个指标：公共服务设施/基础设施/户均宅基地/人均村庄建设用地
- 指标数据无结构化来源标记 (上位传导 vs 本级规划)

**已有可用数据**：`dicts/rules/planning_targets.yaml` 已完整定义 7 个指标(code/name/unit/attribute/field)

---

### G4. 土地利用结构调整表(附表2)未建模 (High)

**对照规范**：《广东省技术指南》附表2

19 个子类别，每类有：基期年面积/比重 + 目标年面积/比重 + 规划期内增减

三大类结构：农业用地(6) + 建设用地(12) + 生态用地(3)

**当前实现**：无。`SpatialPlanningIntent` 仅有 3 个总面积字段

**差距**：
- 完全缺失 19 子类 × 4 列(面积/比重 × 现状/规划) 的结构
- 无法生成土地平衡表
- 无法追踪各地类的增减变化

**已有可用数据**：`dicts/rules/land_use_structure.yaml` 已完整定义 19 个分类(code/name/parent/ghytbm)

---

### G5. 管制规则(附录3)未建模 (Critical)

**对照规范**：《广东省技术指南》附录3

6 大类管制规则，每类含具体约束条款模板：

1. **生态保护**：保护红线范围+禁止建设活动+保护生态用地名录
2. **耕地和永久基本农田保护**：基本农田面积+集中分布区+占用审批程序+设施农用地管理规定
3. **历史文化传承与保护**：文物保护单位名录+历史文化保护线范围+修缮审批要求
4. **建设空间管制**：
   - 产业发展空间：经营性建设用地密度/高度/容积率/绿地率
   - 农村住房：宅基地面积上限/建筑层数/高度/风貌要求
   - 基础设施和公共服务设施：退线距离/设施用地保护
5. **村庄安全和防灾减灾**：避开自然灾害区/消防通道要求/应急庇护场所
6. **其他管制规则**：各村实际情况制定

**当前实现**：`SpatialConstraint`

```python
class SpatialConstraint(BaseModel):
    type: Literal[
        "area_constraint",
        "spatial_constraint",
        "building_constraint",
        "use_constraint",
        "boundary_constraint",
    ] = "spatial_constraint"
```

**差距**：
- 5 个通用类型 (area/spatial/building/use/boundary) 不匹配 6 大管制类别
- 缺少管管制规则的标准模板结构 (分类→条款列表→空间关联→量化限值)
- `building_constraint` 仅含 max_area_sqm/max_height_m/max_floors/setback_m，缺少容积率/绿地率/建筑密度/风貌要求

---

### G6. 三区三线空间结构缺失 (High)

**对照规范**：《中共中央 国务院关于建立国土空间规划体系并监督实施的若干意见》

> "三区"：生态空间、农业空间、城镇空间
> "三线"：生态保护红线、永久基本农田、城镇开发边界

**当前实现**：无。`SpatialPlanningIntent` 无三区三线概念

**差距**：
- 缺 `ThreeZones` (生态/农业/建设空间面积)
- 缺 `ThreeLines` (三条控制线面积+空间范围)
- 现有 `SpatialContext` 的 `zone_adjacency` 仅有 7 个自定义 zone，无三区映射

**已有可用数据**：
- `dicts/rules/three_line_types.yaml` — 三线图层定义 (含颜色/线型/GDB key)
- `dicts/rules/planning_zone_rules.yaml` — 规划分区到三区的映射 (`planning_zone_to_primary_zone`)

---

### G7. Section 分类不匹配 (Medium)

**对照规范**：《广东省技术指南》第三章"规划内容" — 7大规划内容：

1. 村庄发展目标
2. 生态保护修复
3. 耕地和永久基本农田保护
4. 历史文化传承与保护
5. 产业和建设空间安排
6. 村庄安全和防灾减灾
7. 近期建设行动

**当前实现**：`SectionInfo.section_type` 13 种

```python
Literal["preamble", "target", "regulation", "project_table",
        "land_use_table", "indicator_table", "heritage_table",
        "facility_table", "ecological_table", "spatial_layout",
        "protection", "infrastructure", "governance"]
```

**差距**：
- 缺少 `ecological_restoration` (生态保护修复)
- 缺少 `farmland_protection` (耕地和永久基本农田保护)
- 缺少 `disaster_prevention` (村庄安全和防灾减灾)
- 缺少 `recent_projects` (近期建设行动)
- 缺少 `development_targets` (村庄发展目标 — 与 `target` 区分，含指标体系)
- `ecological_table` 存在但不精确 → 应为 `ecological_restoration`

---

### G8. 双评价(GIS分析基础)缺失 (Medium)

**对照规范**：《实用性村庄规划编制手册》§2.5 调查内容分析, §4.8 GIS实验操作

"双评价"是划定三区三线的科学基础：
- **生态保护重要性评价**：生态系统服务功能重要性 + 生态敏感性
- **农业生产适宜性评价**：土地资源 + 水资源 + 气候 + 环境 + 灾害
- **城镇建设适宜性评价**：高程 + 坡度 + 坡向 + 地质灾害 + 交通可达性 + 基本农田

手册 §2.6 详细描述了 GIS 实验操作流程：
- 实验一：数据库建立与出图设置
- 实验三：地形分析 (高程分析/坡度分析/坡向分析/起伏度分析)
- §4.8：双评价成果空间落位 → 三区三线衔接

**当前实现**：无。`SpatialContext` 无评价结果字段

**已有可用数据**：
- `spatial_types.py` `ContourLine`, `ElevationPoint` — 地形要素 dataclass (Group E, 标记为"🔴 未实现")
- `canonical.py` `GISDataBundle.dem: Optional[Any]` — DEM 字段已预留但未填充
- `analysis/terrain.py` — 不存在 (需新建)

---

## KG Builder 差距详情

### K1. V/N/E 精细分类三元组缺失 (Critical)

**当前实现**：`builder.py` `ZONE_TYPE_PATTERNS` 仅 4 个粗分区

```python
ZONE_TYPE_PATTERNS = {
    "农田保护区": {"color": "#FFE4B5", "restrictions": [...]},
    "村庄建设区": {"color": "#FF6347", "restrictions": [...]},
    "生态保护区": {"color": "#2E8B57", "restrictions": [...]},
    "一般农业区": {"color": "#98FB98", "restrictions": [...]},
}
```

**差距**：
- 4 个粗分区 vs 标准 15 小类
- 无 V/N/E 大类层级关系
- `restrictions` 是自由文本而非结构化管制规则
- 未使用 `land_use_structure.yaml` 中的 19 分类定义

**已有可用数据**：`dicts/rules/land_use_structure.yaml` — 19 子类(code/name/parent/ghytbm)

---

### K2. 管制规则 RDF 实体缺失 (Critical)

**当前实现**：`_add_regulations()` 仅创建 3 条规则

```python
REGULATION_TYPES = {
    "永久基本农田保护": {"protects": "农田保护区", "field": "farmland_area_ha"},
    "生态保护红线": {"protects": "生态保护区", "field": "ecological_redline_ha"},
    "村庄建设边界": {"protects": "村庄建设区", "field": "construction_area_ha"},
}
```

**差距**：
- 仅 3 条规则 vs 标准 6 大类管制规则 (缺：历史文化/建设空间管制/安全防灾/其他)
- 规则仅含 `protects` + `field`，缺少管制条款文本、量化限值、审批程序等
- 无 `controls_use` 关系连接管制规则→地块

---

### K3. 规划指标表三元组缺失 (High)

**当前实现**：`_add_indicators()` 直接 dump 所有 report metric key-values

```python
for key, val in metrics.items():
    if val is None: continue
    indicator = PLN[f"indicator_{dk}_{key}"]
    self.g.add((indicator, PLN.name, Literal(key)))
    self.g.add((indicator, PLN.value, Literal(float(val))))
```

**差距**：
- 无结构化字段 (code I01-I07, attribute 约束性/预期性, unit 公顷/平方米)
- 无时间维度 (基期年 vs 目标年 vs 变化量)
- 来源仅记录 dimension key 而非 "上位规划传导" vs "本级规划确定"

**已有可用数据**：`dicts/rules/planning_targets.yaml` — 7 指标完整定义

---

### K4. Ontology 缺失核心概念 (High)

**当前实现**：`ontology.py` 16 实体 + 11 关系

**缺失实体** (对照专业教材)：

| 缺失实体 | 来源 | 说明 |
|----------|------|------|
| `ControlRule` | 广东省技术指南 附录3 | 6 大类管制规则 |
| `LandUseCategory` | 村庄规划用地分类指南 表2.2.2 | V/N/E 15 小类 |
| `PlanningIndicator` | 广东省技术指南 附表1 | 7 指标×3 时间维度 |
| `ThreeZone` | 三区三线政策 | 生态/农业/建设空间 |
| `ThreeLine` | 三区三线政策 | 三条控制线 |
| `UpperPlan` | 广东省技术指南 三(一) | 上位规划传导 |

**缺失关系**：

| 缺失关系 | 说明 | 示例 |
|----------|------|------|
| `delineates` | 控制线划定 | `ThreeLine → delineates → Parcel` |
| `controls_use` | 用途管制 | `ControlRule → controls_use → LandUseCategory` |
| `conducted_from` | 上位传导 | `PlanningIndicator → conducted_from → UpperPlan` |
| `evaluated_as` | 双评价结果 | `Parcel → evaluated_as → SuitabilityClass` |

---

### K5. `build_from_intent` 仍用 Dict 路径 (Medium)

**当前实现**：`build_from_intent(intent: Dict[str, Any], ...)`

```python
def build_from_intent(self, intent: Dict[str, Any], ...):
    zones = intent.get("zones", [])
    for z in zones:
        zone_id = z.get("zone_id", z.get("land_use", "unknown"))
```

**差距**：typed `SpatialPlanningIntent` 已在 `parse/state.py` 中定义，但 `build_from_intent` 仍接收 `Dict[str, Any]` 并用 `.get()` 访问

---

### K6. 硬编码模式未替换为 YAML 规则 (Medium)

**当前**：`CONSTRAINT_PATTERNS` (7 条) + `ZONE_TYPE_PATTERNS` (4 条) + `SEMANTIC_CONSTRAINT_MAP` (5 条) 全部硬编码

**已有 YAML**：
- `planning_targets.yaml` — 7 指标
- `planning_zone_rules.yaml` — 16 决策规则 + planning_zone_to_primary_zone 映射
- `land_use_structure.yaml` — 19 用地分类
- `three_line_types.yaml` — 三线定义

**差距**：从未从 YAML 加载，更新规则需改代码

---

## 修复优先级建议

### Phase A: 数据结构对齐 (先修 Schema，不改流程)

| 优先级 | 差距 | 文件 | 工作量 |
|--------|------|------|--------|
| P0 | G1 VNE分类 | `parse/state.py` | 新增 VNE 枚举 + ZoneTarget 增强 |
| P0 | G5 管制规则 | `parse/state.py` | 新增 ControlRule 模型 |
| P0 | G3 规划指标表 | `parse/state.py` | 引用 planning_targets.yaml |
| P1 | G4 用地结构表 | `parse/state.py` | 引用 land_use_structure.yaml |
| P1 | G6 三区三线 | `parse/state.py` | 新增 ThreeZonesThreeLines |
| P1 | G7 Section分类 | `parse/state.py` | 扩展 Literal 类型 |
| P2 | G2 输出结构 | `parse/state.py` | 新增 PlanningOutput 包装 |
| P2 | G8 双评价 | `contracts.py` | 新增 DualEvaluation 可选字段 |

### Phase B: KG 对齐

| 优先级 | 差距 | 文件 | 工作量 |
|--------|------|------|--------|
| P0 | K1 VNE分类三元组 | `kg/builder.py` | YAML加载替换 ZONE_TYPE_PATTERNS |
| P0 | K4 Ontology扩展 | `kg/ontology.py` | 新增 6 实体 + 4 关系 |
| P1 | K2 管制规则实体 | `kg/builder.py` | _add_regulations → 6类 |
| P1 | K3 指标实体 | `kg/builder.py` | _add_indicators 结构化 |
| P2 | K5 typed输入 | `kg/builder.py` | build_from_intent Dict→Typed |
| P2 | K6 YAML加载 | `kg/builder.py` | 替换所有硬编码模式 |

### Phase C: 下游对齐

| 优先级 | 差距 | 文件 | 工作量 |
|--------|------|------|--------|
| P1 | Dict桥接清除 | `generate.py`, `allocate.py` | 删除 isinstance(dict) 分支 |
| P1 | 管线对齐 | `layout_pipeline.py` | 删除 intent_json |
| P2 | Reporter对齐 | `parse_reporter.py` | hasattr → typed |

---

## 参考来源

### 专业教材/规范 (RAG)
- 《村庄规划用地分类指南》(住建部, 2014) — `data/RAG_doc/_doc_md/04_技术规范/01_国家层面/01 《村庄规划用地分类指南》_minerU_parsed.md`
- 《广东省村庄规划编制基本技术指南（试行）》(2019) — `data/RAG_doc/_doc_md/04_技术规范/02_地方层面/01_广东省/01 《广东省村庄规划编制基本技术指南（试行）》_minerU_parsed.md`
- 《实用性村庄规划编制手册》李巍等 — `data/RAG_doc/_doc_md/01_专业教材/05 《实用性村庄规划编制手册》——李巍等_minerU_parsed.md`
- 《乡村规划原理》李京生 — `data/RAG_doc/_doc_md/01_专业教材/02 《乡村规划原理 》——李京生_minerU_parsed.md`

### 现有 Schema 源文件 (代码)
- `backend/app/agent/gis/parse/state.py` — PARSE Agent 全部 Schema 定义
- `backend/app/modules/gis/schema/contracts.py` — SpatialContext + UnifiedSpatialIntent
- `backend/app/modules/gis/schema/spatial_types.py` — 5组25+空间要素 dataclass
- `backend/app/modules/gis/schema/canonical.py` — GISDataBundle
- `backend/app/modules/gis/schema/gdb.py` — GDB 12层图层注册表
- `backend/app/modules/gis/schema/classification.py` — DictionaryCenter 驱动的 LandUseClass
- `backend/app/modules/gis/schema/dicts/loader.py` — YAML 加载中心
- `backend/app/modules/gis/schema/dicts/encodings/*.yaml` — 6套编码系统
- `backend/app/modules/gis/schema/dicts/rules/*.yaml` — 5份规划规则
- `backend/app/modules/kg/ontology.py` — 16实体+11关系
- `backend/app/modules/kg/builder.py` — PlanningKG 构建器
- `backend/app/tools/gis/generate.py` — 空间生成器 (_intent_from_typed bridge)
- `backend/app/tools/gis/allocate.py` — MIP 分配器 (_intent_to_targets bridge)
