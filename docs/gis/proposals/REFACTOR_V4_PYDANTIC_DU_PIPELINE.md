# GIS 数据管道重构实施方案 v4
## -- 全面 Pydantic v2 + Discriminated Union + 编码谱系 + 声明式管道

> 状态: 提案（当前方向，已确认 2026-07-29）
> 日期: 2026-07-28
> 分支: `refactor/v4-pydantic-du-pipeline`
> 输入: v3 编码中心提案、context7/exa 范式研究、当前代码现状调查、agent 架构深度调查
> 权威顺序: 实现时以模块 README 为准。本文档与模块 README 冲突时，以模块 README 为准（归档重组 2026-07-29 统一权威链）。

---

## 0. 与 v3 的关系:保留骨架,深化四处

v3 的骨架(编码谱系考证、统一 1:N 映射、adapter 策略模式、DLQ + immutable)方向正确,予以保留。但有四个实质性决策需要修正:

| # | v3 的立场 | v4 的修正 | 理由 |
|---|-----------|-----------|------|
| 1 | §5.5:Pydantic DU 列为"v3.1 独立评估",本期用 layer_type tag + registry 路由模拟 DU | **全面迁移 Pydantic v2 + DU,一次性切断 dataclass** | layer_type 空转是 dataclass 无验证约束的症状;手工模拟 DU 等于重造 Pydantic 已内建的能力;中文字段别名映射 Pydantic `Field(alias=...)` 原生解决 |
| 2 | §2.4:条件表达式用字符串 DSL + 自定义求值器 | **Pydantic `Condition` 模型树** | 字符串 DSL 需要自定义解析器;模型树可被 LLM `with_structured_output` 直接生成,安全、可测试、可序列化 |
| 3 | §6.1:builder 用 YAML 字符串引用函数名(`kg.builder: _add_water_bodies`) | **YAML 声明 `entity_type` + Python `@kg_builder` 装饰器绑定** | YAML 字符串引用有反射味道,IDE 不可追踪,函数名重构时 YAML 不自动更新 |
| 4 | §3:L2 LLM 消歧在 ingest 阶段调用 LLM | **L2 规则生成预留给 analysis 阶段,规则执行在 tool agent 阶段;本次只搭接口不实现 LLM 调用** | LLM 选择应在 analysis 实现(用户确认);ingest 阶段应保持确定性;analysis LLM 生成 NL/结构化规则 -> flash LLM(tool agent)执行 |

一个核心决策:**不双写、不兼容期**。dataclass 一次性切换为 Pydantic;GeoSPARQL 谓词一次性替换,不留旧谓词。

---

## 1. Pydantic v2 + Discriminated Union 迁移

### 1.1 为什么全面迁移而非 v3 的"延后"

1. **`layer_type` 字段已存在但空转**是症状不是根因--根因是 dataclass 无解析期验证,ingest 没有强制赋值的约束机制。v3 §5.4 是在 dataclass 体系上手工模拟 DU。
2. **`base.py:56-68` 文档说 L1 中间层"构造时 fail-fast"但实际没有**--`PolygonFeature` 不验证 geometry type,`CurrentLandUseParcel` 不验证 dlbm 格式。Pydantic `field_validator` 免费提供。
3. **`layer1.py` 的 `getattr(p, "dlbm", "")` 模式**(出现 60+ 次)是因为 dataclass 无类型保证。Pydantic 模型让字段类型在 KG builder 中可见,IDE 补全 + 静态分析可用。
4. **中文字段别名映射**(`_LANDUSE_ALIASES`、`from_geojson_feature` 里的 `props.get("BSM","")`)--Pydantic `Field(alias="BSM")` + `model_config = ConfigDict(populate_by_name=True)` 原生解决,不需要 v3 §5.1 的 `field_mapping` YAML 块。
5. **回归风险可控**:有 golden bundle 快照(Phase 0)兜底,且 DU 的 discriminator 直接复用 `layer_type` 字段值,语义不变。

### 1.2 模型迁移规范

#### 基类迁移

```python
# schema/types/base.py -- 迁移后
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Any, Dict, Literal
from typing_extensions import Annotated

class SpatialFeature(BaseModel):
    """所有空间要素的统一基类。"""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    geometry: Dict[str, Any]               # GeoJSON geometry (必选)
    bsm: str = Field(default="", alias="BSM")          # 标识码
    ysdm: str = Field(default="", alias="YSDM")        # 要素代码 (10位)
    layer_type: str = ""                   # DU discriminator,ingest 强制赋值

    @field_validator("geometry")
    @classmethod
    def _validate_geometry_present(cls, v):
        if not v or "type" not in v:
            raise ValueError("geometry must be a valid GeoJSON geometry dict")
        return v

    @property
    def geometry_type(self) -> str:
        return self.geometry.get("type", "Unknown")


class PointFeature(SpatialFeature):
    @field_validator("geometry")
    @classmethod
    def _validate_point_geom(cls, v):
        if v.get("type") not in ("Point", "MultiPoint"):
            raise ValueError(f"PointFeature requires Point/MultiPoint, got {v.get('type')}")
        return v

class LineFeature(SpatialFeature):
    @field_validator("geometry")
    @classmethod
    def _validate_line_geom(cls, v):
        if v.get("type") not in ("LineString", "MultiLineString"):
            raise ValueError(f"LineFeature requires LineString/MultiLineString, got {v.get('type')}")
        return v

class PolygonFeature(SpatialFeature):
    @field_validator("geometry")
    @classmethod
    def _validate_polygon_geom(cls, v):
        if v.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"PolygonFeature requires Polygon/MultiPolygon, got {v.get('type')}")
        return v
```

#### Discriminated Union 定义

```python
# schema/types/spatial_types.py -- 迁移后

class CurrentLandUseParcel(BaseLandUseParcel):
    """现状地类图斑 -- layer_type 固定为 landuse_current。"""
    layer_type: Literal["landuse_current"] = "landuse_current"
    sddlbm: str = Field(default="", alias="SDDLBM")
    sddlbm_system: str = ""

class PlannedLandUseParcel(BaseLandUseParcel):
    """规划地类图斑 -- layer_type 固定为 landuse_planned。"""
    layer_type: Literal["landuse_planned"] = "landuse_planned"
    qmdlbm: str = Field(default="", alias="QMDLBM")
    # ...

class WaterFeature(PolygonFeature):
    layer_type: Literal["water"] = "water"
    water_type: str = ""

# ... 30+ 子类,每个都声明 layer_type: Literal["<gis_type_ref>"] = "<gis_type_ref>"

# ── Discriminated Union ──
GisFeature = Annotated[
    Union[
        CurrentLandUseParcel,
        PlannedLandUseParcel,
        WaterFeature,
        CurrentRoad,
        PlannedRoad,
        # ... 全部 30+ 子类
    ],
    Field(discriminator="layer_type"),
]
```

#### ingest 出口:DU 自动路由

```python
# 迁移后:不再需要 isinstance 链
from pydantic import TypeAdapter

_feature_adapter = TypeAdapter(GisFeature)

def result_to_features(result: DataResult, entry: GisLayerTypeEntry) -> tuple[list[GisFeature], list[str]]:
    geojson = _geojson_from_result(result)
    if geojson is None:
        return [], [result.error or "no geojson data"]

    features: list[GisFeature] = []
    warnings: list[str] = []
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        # 注入 layer_type(du discriminator)
        props["layer_type"] = entry.gis_type_ref
        feat["properties"] = props
        try:
            typed = _feature_adapter.validate_python(feat)  # DU 自动路由
            features.append(typed)
        except ValidationError as e:
            warnings.append(f"Feature BSM={props.get('BSM','?')}: {e}")
            # DLQ: 不中断,继续处理
    return features, warnings
```

#### 迁移统计

| 现有文件 | dataclass 数 | 迁移动作 |
|---------|------------|---------|
| `base.py` | 5 (SpatialFeature/Point/Line/Polygon/RasterDataset) | -> BaseModel + field_validator |
| `spatial_types.py` | 30+ (AdminArea/BaseLandUseParcel/CurrentLandUseParcel/...) | -> BaseModel + `layer_type: Literal[...]` + Field(alias=中文字段) |
| `raster_types.py` | 5 (DEMInput/DOMInput/SlopeRaster/...) | -> BaseModel |
| `table_types.py` | 5+ (PopulationTable/...) | -> BaseModel |
| `document_types.py` | 2+ | -> BaseModel |
| `canonical.py` | 6 LayerGroup + VillageBundle + VillageMetadata | -> BaseModel + `_layers: dict` 动态化(§4) |

### 1.3 `_raw` 字段处理

现状 `_raw: Dict` 用于调试。Pydantic 中用 `extra="allow"` + `model_dump()` 替代--所有未声明字段自动保留在模型中,`model_dump()` 可完整序列化。删除 `_raw` 字段,下游 `getattr(p, "_raw", {})` 改为 `p.model_dump()` 或 `p.model_extra`。

### 1.4 `from_geojson_feature` classmethod 处理

现状 30+ 子类有各自的 `from_geojson_feature`。Pydantic 迁移后,**大部分删除**--`model_validate(geojson_dict)` 直接完成解析。仅保留有特殊逻辑的(如 `CurrentFacility.from_annotation_feature` 做设施类型推断)。

---

## 2. 统一编码元模型

### 2.1 编码体系字典:统一 schema

(采纳 v3 §2.1,无修改)

```yaml
# dicts/encodings/<system>.yaml
version: "2023"
standard: "国土空间调查、规划、用途管制用地用海分类指南"
system: ydyhfldm
authority: "自然资源部"
role: planned               # current | planned | admin | reference
code_format: "4位数字"
levels: 3
classes:
  - code: "0703"
    name: "农村宅基地"
    parent: "07"
    cross_refs:
      gbt21010: ["0702"]
      vne: ["V11"]
```

迁移:appendix5 的 `zone_type/vne/ydyhfldm` 字段、ghflbm 的 `ghytbms` 列表、tugui 的 `planning_zone/primary_zone/categories` 全部迁入 `cross_refs`;`loader.py` 的 DictionaryCenter 增加 schema 版本探测,旧字段读取走兼容 shim(一次性,标记 deprecated)。

### 2.2 映射字典:原生 1:N 统一 schema

```yaml
# dicts/mappings/sddlbm_to_ydyhfldm.yaml
version: "1.0"
source_system: sddlbm
target_system: ydyhfldm
basis: "用地用海分类指南附录F(官方对应)"
mappings:
  - source: "05H1"
    default: "0900"
    decision: context                # auto | context | manual
    targets:
      - code: "0900"
        when: null                   # 恒真 -> 缺省
        confidence: exact
      - code: "0901"
        when:                         # Pydantic Condition 模型树(§2.3)
          kind: func
          func: poi_match
          args: [["商业", "店铺", "超市", "商场"]]
        evidence_hint: [poi]
        confidence: conditional
```

要点:
- `targets[]` 原生列表,**运行时绝不压平**;`default` 单独标注;
- `when` 是 **Pydantic `Condition` 模型树**(§2.3),不是字符串;
- `evidence_hint` 声明该候选依赖哪条官方消歧通道;
- `basis` 必填--每个映射必须能回溯到标准出处。

### 2.3 Condition 模型树(替代 v3 字符串 DSL)

```python
# dicts/expr_eval.py -- 迁移后
from pydantic import BaseModel
from typing import Any, Literal

class Condition(BaseModel):
    """可序列化、可被 LLM with_structured_output 直接生成的条件树。

    替代 v3 §2.4 的字符串 DSL。求值器是递归的 model 字段访问,无 eval。
    """
    kind: Literal["func", "comparison", "and", "or", "null"]
    # kind=func
    func: str | None = None           # poi_match | field_equals | within_zone | imagery_indicator | area_gt
    args: list[Any] = []
    # kind=comparison
    field: str | None = None
    op: Literal["==", "!=", "in", "starts_with", "ends_with", "gt", "lt"] | None = None
    value: Any = None
    # kind=and|or
    children: list["Condition"] = []

    def evaluate(self, ctx: "MappingContext") -> bool:
        match self.kind:
            case "null":
                return True
            case "and":
                return all(c.evaluate(ctx) for c in self.children)
            case "or":
                return any(c.evaluate(ctx) for c in self.children)
            case "comparison":
                actual = ctx.get(self.field)
                match self.op:
                    case "==": return actual == self.value
                    case "!=": return actual != self.value
                    case "in": return actual in self.value
                    case "starts_with": return str(actual).startswith(self.value)
                    case "gt": return float(actual) > float(self.value)
                    case "lt": return float(actual) < float(self.value)
                    case _: return False
            case "func":
                return _BUILTIN_FUNCS[self.func](ctx, *self.args)
            case _:
                return False


# 内建函数注册表
_BUILTIN_FUNCS = {
    "poi_match": _func_poi_match,           # POI 通道
    "field_equals": _func_field_equals,     # 图斑属性
    "within_zone": _func_within_zone,       # 空间通道(KG/spatial_ops)
    "imagery_indicator": _func_imagery,     # 影像通道
    "area_gt": _func_area_gt,               # 面积阈值
}
```

**为什么模型树优于字符串 DSL**:
1. LLM `with_structured_output(Condition)` 可直接生成,无需字符串解析;
2. Pydantic 验证保证结构合法,无注入风险;
3. 可递归求值,无 eval;
4. `model_dump_json()` 确定性序列化,可 hash、可缓存;
5. `planning_zone_rules.yaml` 的 condition 同步迁到该模型树。

### 2.4 迁移清单(含 bug 修复)

(采纳 v3 §2.3,无修改)

| 现有文件 | 迁移动作 |
|---|---|
| `references/dlbm_to_ghytbm.yaml` | 转统一 schema;**修复 0602 重复键**:拆为两条 target,when 分别挂 `field_equals("QSXZ","10")` 与 imagery/补充调查,decision: context |
| `references/sddlbm_to_ydyhfldm.yaml` | 转统一 schema;`needs_human_decision: true` -> `decision: manual`;alternatives.when 自由文本 -> Condition 模型树(人工翻译一次,约 20 条) |
| `rules/ghflbm_to_tdytfqdm.yaml` | 转统一 schema,decision: auto;**修正键名拼写 tdyfqdm->tdytfqdm** |
| `loader.py` `_PROPOSAL_FILES` 硬编码 | 删除;改为扫描 `dicts/mappings/` 目录,按 `source_system/target_system` 自注册 |
| `code_sets.py` 各压平 dict | 保留只读兼容视图(标记 deprecated),新代码一律走 `MappingRegistry.resolve()` |
| `planning_zone_rules.yaml` condition 字符串 | 迁到 Condition 模型树 |

---

## 3. 消歧决策梯:L2 接口预留(不实现 LLM 调用)

### 3.1 四级阶梯(确定性递减,成本递增)

```
L0 auto      targets 仅 1 个(或 when=null 恒真)        -> 直接映射,零成本
L1 context·确定性通道  when Condition 可求值且唯一命中   -> 规则引擎决定,零 LLM
         (官方方法一/二/三的机器化:POI / 地形图字段 / 影像指标 / within_zone)
L2 context·LLM 辅助   多候选幸存 or 证据不足           -> LLM 在候选闭集内选择+留证据
         (★ 规则生成预留给 analysis 阶段,规则执行在 tool agent 阶段)
L3 manual    decision:manual,或 LLM confidence 低于阈值 -> 人工队列(DLQ 第三类)
```

### 3.2 L2 的定位调整(与 v3 的关键差异)

v3 把 L2 LLM 消歧放在**数据管道 ingest 阶段**。v4 修正:

- **L0/L1**(auto + 规则消歧)仍在 ingest 阶段执行--这是确定性的、无 LLM 的;
- **L2 的规则生成**移到 analysis 阶段(analysis LLM 在产出规划文本时生成结构化规则,如"05H1 商服用地的细分,若 POI 显示为超市则归 0901"),这些规则以 `Condition` 模型树形式产出;
- **L2 的规则执行**在 tool agent 阶段(flash LLM 消费 analysis 产出的规则,预填充 bundle);
- **L3**(manual)走 DLQ 不变。

### 3.3 本次范围:L2 接口模型

```python
# dicts/disambiguation.py(新增)
from pydantic import BaseModel, field_validator
from typing import Literal

class Candidate(BaseModel):
    """一个候选目标编码 + 其触发条件。"""
    code: str
    when: Condition | None = None
    surviving_evidence: list[str] = []      # L1 已命中的证据

class DisambiguationContext(BaseModel):
    """消歧上下文 -- 可被 flash LLM + instructor 直接消费。

    设计为 tool agent 阶段 flash LLM 的输入 schema。
    """
    source_system: str
    source_code: str
    parcel_attrs: dict                       # 图斑全属性
    neighbors: list[dict]                    # KG EntityCard 摘要
    poi_hits: list[dict] = []
    zone_membership: list[str] = []
    village_profile: str = ""                # RAG 村庄画像(≤200字)
    candidates: list[Candidate]              # 闭集,LLM 只能从中选

class DisambiguationDecision(BaseModel):
    """消歧决策 -- 闭集选择 + 证据 + provenance。"""
    chosen_code: str
    confidence: Literal["high", "medium", "low"]
    rationale: str                           # ≤100字,引用证据
    evidence: list[str] = []
    decided_by: Literal["rule", "llm", "human", "default"] = "llm"
    model: str = ""                          # 记录 model 版本
    reviewed: bool = False

    @field_validator("chosen_code")
    @classmethod
    def _must_be_in_candidates(cls, v, info):
        """validator 强制:chosen_code 必须在 candidates 闭集内。"""
        # info.context 携带 DisambiguationContext
        ctx = info.context
        if ctx and hasattr(ctx, "candidates"):
            valid = {c.code for c in ctx.candidates}
            if v not in valid:
                raise ValueError(f"chosen_code {v} not in candidate closed set {valid}")
        return v
```

### 3.4 与 candidate_engine 的关系

`CandidateEngine.propose()` 升级为决策梯的统一入口:

```python
def resolve(self, source_system, target_system, source_code, ctx: MappingContext) -> Resolution:
    mapping = self.mappings.get(source_system, target_system, source_code)
    if mapping is None:                       -> Resolution.unmapped()      # 进 DLQ 第一类
    if mapping.decision == "auto":            -> Resolution.auto(default)
    hits = [t for t in mapping.targets if t.when is None or t.when.evaluate(ctx)]
    if len(hits) == 1:                        -> Resolution.rule_based(hit) # L1
    if mapping.decision == "manual":          -> Resolution.manual(alts)    # L3
    # L2:返回 DisambiguationContext,不在此调用 LLM
    return Resolution.needs_llm(DisambiguationContext(..., candidates=hits))
```

**本次不实现 L2 的 LLM 调用**。`Resolution.needs_llm` 的消费者在后续 agent 架构重构中实现(tool agent / flash LLM)。

---

## 4. LayerGroup 动态化

### 4.1 动态 `_layers` + 兼容 property

```python
# canonical.py -- 迁移后
class PolygonLayerGroup(BaseModel):
    """所有 PolygonFeature 子类,动态分桶。"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    _layers: dict[str, list[GisFeature]] = {}

    def add(self, feature: GisFeature) -> None:
        """按 registry 的 bundle_target 自动分桶。"""
        entry = GIS_LAYER_REGISTRY.get(feature.layer_type)
        key = entry.bundle_target_key if entry else "inferred"
        self._layers.setdefault(key, []).append(feature)

    # ── 兼容 property(保留旧接口,行为不变)──
    @property
    def landuse_current(self) -> list[GisFeature]:
        return self._layers.get("landuse_current", [])

    @property
    def water_bodies(self) -> list[GisFeature]:
        return self._layers.get("water_bodies", [])

    # ... 其他旧字段名保留为 property

    @property
    def constraint_polygons(self) -> list[GisFeature]:
        """自动聚合所有 spatial.is_constraint=true 的层。"""
        result = []
        for gis_type, entry in GIS_LAYER_REGISTRY.items():
            if entry.spatial and entry.spatial.is_constraint:
                result.extend(self._layers.get(entry.bundle_target_key, []))
        return result

    @property
    def all_features(self) -> list[GisFeature]:
        return [f for features in self._layers.values() for f in features]
```

### 4.2 VillageBundle

```python
class VillageBundle(BaseModel):
    """Single village data container -- morphology-first。"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    village_name: str
    points: PointLayerGroup = Field(default_factory=PointLayerGroup)
    lines: LineLayerGroup = Field(default_factory=LineLayerGroup)
    polygons: PolygonLayerGroup = Field(default_factory=PolygonLayerGroup)
    rasters: RasterLayerGroup = Field(default_factory=RasterLayerGroup)
    tables: TableLayerGroup = Field(default_factory=TableLayerGroup)
    documents: DocumentGroup = Field(default_factory=DocumentGroup)
    metadata: VillageMetadata = Field(default_factory=VillageMetadata)
    standard_version: str = "4.4"

    def add(self, feature: GisFeature) -> None:
        """按 geometry_kind 路由到对应 LayerGroup,再由 LayerGroup.add 分桶。"""
        kind = GIS_LAYER_REGISTRY.get(feature.layer_type)
        if kind and kind.geometry_kind == "point":
            self.points.add(feature)
        elif kind and kind.geometry_kind == "line":
            self.lines.add(feature)
        elif kind and kind.geometry_kind == "polygon":
            self.polygons.add(feature)
        # ... raster/table/document

    # ── 兼容 property ──
    @property
    def boundary(self) -> Any:
        if self.polygons.admin_areas:
            return self.polygons.admin_areas[0]
        if self.polygons.planning_scope:
            return self.polygons.planning_scope[0]
        return None

    # ... 其他旧 property 保留
```

### 4.3 `to_geojson_dict` / `all_features` 等

遍历 `_layers`,不再枚举字段。`is_complete()`、`parcel_count`、`total_area_ha`、`get_parcels_by_dlbm`、`get_parcels_by_zone` 等便利方法保留,改为从 `_layers` 取数据。

---

## 5. 图层注册表扩展

### 5.1 registry 元模型(在 v3 §5.1 基础上删除 field_mapping)

```yaml
# schema/types/gis_layer_registry.yaml -- v4
layer_types:
  water:
    i18n: {zh: 水系, en: water}
    geometry_kind: polygon
    group: natural
    ingest:
      adapter: features               # §5.2
      feature_type: water
    encodings:
      dlbm_field: dlbm
      systems: [gbt21010]
      mappings: [{from: gbt21010, to: appendix5, on: dlbm}]
    spatial:
      is_constraint: false
      participates: [water_overlap]
    bundle_target: {group: polygons, key: water_bodies}
    kg:
      entity_type: WaterBody
      uri_policy: "L1:{type}_{bsm}"
    validation:
      required_fields: [dlbm]
      geometry: {must_be_valid: true, dlq_on_error: true}
```

**与 v3 的差异**:删除 `ingest.field_mapping` 块--Pydantic `Field(alias=...)` 在模型上直接声明,不需要在 YAML 重复。

`GisLayerTypeEntry` Pydantic 模型同步扩展(嵌套模型:IngestSpec/EncodingsSpec/SpatialSpec/BundleTarget/KgSpec/ValidationSpec)。

### 5.2 adapter 策略模式

(采纳 v3 §5.2,简化签名)

```python
# data/adapters/__init__.py -- 新增
from typing import Protocol

class IngestAdapter(Protocol):
    def load(self, data: dict, entry: GisLayerTypeEntry, ctx: IngestContext) -> AdapterResult:
        """data: fetch 后的内存对象(不落临时文件);返回 features+warnings+dlq"""
        ...

# 6 个标准 adapter:
# parcels   -- 地类图斑类(现状/规划),走编码验证链
# features  -- 一般点/线/面要素,DU 自动路由
# wfs_layers -- api_vector 多层服务
# raster    -- DEM/DOM/slope
# table     -- 属性表
# document  -- 文本类

ADAPTERS: dict[str, IngestAdapter] = {
    "parcels": ParcelsAdapter(),
    "features": FeaturesAdapter(),
    "wfs_layers": WfsLayersAdapter(),
    "raster": RasterAdapter(),
    "table": TableAdapter(),
    "document": DocumentAdapter(),
}

def register_adapter(name: str, adapter: IngestAdapter) -> None:
    """注册 custom adapter(特殊层唯一需要写 Python 的情形)。"""
    ADAPTERS[name] = adapter
```

### 5.3 类型路由:DU 替代 isinstance 链

(替代 v3 §5.4)

```python
# 迁移后:_assign_to_bundle 删除,改为:

# catalog.py
def _route_to_bundle(bundle: VillageBundle, features: list[GisFeature]) -> None:
    """DU 已完成类型路由,这里只需按 bundle_target 分桶。"""
    for feat in features:
        bundle.add(feat)  # VillageBundle.add -> LayerGroup.add -> _layers[key].append
```

`_TYPE_BINDINGS`(layer_registry.py L80-135)从手写改为从 YAML 派生:

```python
def build_registry_from_yaml(yaml_path: str | None = None) -> None:
    # ... 读取 YAML ...
    for gis_type_ref, meta in gis_layer_types.items():
        # 从 YAML 直接派生所有绑定
        register_gis_layer_type(
            gis_type_ref,
            model_class_name=_infer_model_class(gis_type_ref),  # 从 layer_type Literal 反查
            geometry_kind=meta.get("geometry_kind", ""),
            ingest_port=meta.get("ingest", {}).get("adapter"),
            ingest_arg=meta.get("ingest", {}).get("feature_type", ""),
            bundle_target_key=meta.get("bundle_target", {}).get("key", ""),
            # ...
        )
```

### 5.4 消除 tempfile

`ingest.py` L647/L675 两处 `NamedTemporaryFile` 删除。adapter 签名已按内存 dict 设计:

```python
# 迁移前(ingest.py:647):
tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False)
json.dump(geojson, tmp)
tmp.close()
return ingest_landuse(tmp.name, ...)  # 写临时文件再读回来

# 迁移后:
return _ingest_landuse_from_dict(geojson, layer_type=layer_type)  # 直接解析 dict
```

---

## 6. KG 构建自动化与 GeoSPARQL 对齐

### 6.1 builder 注册:YAML + 装饰器结合

YAML 声明 `kg.entity_type`;Python `@kg_builder` 装饰器绑定 builder 函数到 `gis_type_ref`:

```python
# kg/builder/registry.py -- 新增
from typing import Callable

_KG_BUILDERS: dict[str, Callable] = {}

def kg_builder(gis_type_ref: str, *, entity_type: str | None = None):
    """注册 KG builder 函数到 gis_type_ref。

    YAML 声明 kg.entity_type(如 WaterBody);
    装饰器绑定 builder 函数到 gis_type_ref(如 "water")。
    """
    def decorator(fn: Callable) -> Callable:
        _KG_BUILDERS[gis_type_ref] = fn
        if entity_type:
            fn._kg_entity_type = entity_type
        return fn
    return decorator

def get_builder(gis_type_ref: str) -> Callable | None:
    return _KG_BUILDERS.get(gis_type_ref)
```

```python
# kg/builder/layer1.py -- 迁移后
from .registry import kg_builder

@kg_builder("water", entity_type="WaterBody")
def _add_water_bodies(self, features: list, *, gis_type_ref: str, entry: GisLayerTypeEntry, ctx: BuildContext) -> BuildReport:
    ...

@kg_builder("landuse_current", entity_type="Parcel")
def _add_parcels(self, features: list, *, gis_type_ref: str, entry: GisLayerTypeEntry, ctx: BuildContext) -> BuildReport:
    ...
```

### 6.2 builder 循环(替代 base.py 20+ 显式调用)

```python
# base.py::build_from_bundle() -- 迁移后
def build_from_bundle(self, bundle, parcel_relations=None, intent=None,
                      planned_state=None, constraint_index=None, ...):
    self.g = Graph()
    self.g.bind("pln", PLN)
    self.g.bind("geo", GEO)
    self._parcel_count = 0
    self._constraint_index = constraint_index

    ctx = BuildContext(village_name=bundle.village_name, ...)

    # Village entity
    self._add_village_entity(bundle.village_name)
    self._add_village_meta_from_bundle(bundle)

    # ── 遍历 registry,自动调度 builder ──
    from .registry import get_builder, _KG_BUILDERS
    for gis_type_ref, builder_fn in _KG_BUILDERS.items():
        entry = GIS_LAYER_REGISTRY.get(gis_type_ref)
        if not entry:
            continue
        features = _get_bundle_features(bundle, entry)
        if not features:
            continue
        report = builder_fn(self, features, gis_type_ref=gis_type_ref, entry=entry, ctx=ctx)
        ctx.merge(report)

    # 空间关系(自动计算)
    self._add_all_spatial_relations(bundle, parcel_relations)

    # 语义层(自动推导)
    self._auto_semantic_enrichment()

    # Layer 3/4(optional)
    if intent is not None:
        self.build_intent_layer(intent)
    if planned_state is not None:
        self._apply_planned_state(planned_state)

    return self
```

### 6.3 统一 builder 签名

```python
def builder_fn(self, features: list[GisFeature], *,
               gis_type_ref: str,
               entry: GisLayerTypeEntry,
               ctx: BuildContext) -> BuildReport:
    """
    features:    该 gis_type_ref 的全部要素(从 bundle 按 bundle_target 取出)
    gis_type_ref: 图层类型引用(如 "water")
    entry:       registry 条目(含 kg.entity_type, spatial, encodings 等元数据)
    ctx:         构建上下文(village entity, bbox, provenance, constraint_index)
    """
    ...
```

现有 `_add_parcels/add_roads/_add_water_bodies/...` 逐一改装(签名统一化,逻辑不动)。

### 6.4 GeoSPARQL 谓词:一次性替换,不双写

| 现有谓词 | 处置 | 理由 |
|---------|------|------|
| `Relations.touches` | **直接替换** -> `geo:sfTouches` | GeoSPARQL 标准 |
| `Relations.intersects` | **直接替换** -> `geo:sfIntersects` | GeoSPARQL 标准 |
| `Relations.contains` | **直接替换** -> `geo:sfContains` | GeoSPARQL 标准 |
| `Relations.located_in` | **直接替换** -> `geo:sfWithin` | GeoSPARQL 标准 |
| `Relations.nearby` | 保留 `pln:nearby` | 无标准对应,文档化为扩展 |
| `Relations.connected_via_road` | 保留 `pln:connected_via_road` | 无标准对应 |
| `Relations.derived_from` | 保留 `pln:derived_from` | provenance 语义 |
| `Relations.serves` | 保留 `pln:serves` | 纯语义关系 |

**不双写**意味着 KG 里不存冗余三元组,查询不需要 OR 两个谓词。

**影响面**:`ontology.py` 谓词定义 + `layer1.py` 关系构建代码 + `queries/sparql.py` 模板 + `queries/semantic.py`/`cognition.py` 一次性更新。

**geometry 同时落 WKT literal**(`geo:hasGeometry` / `geo:asWKT`),让 GeoSPARQL 拓扑函数可直接查询:

```python
# layer1.py -- 新增 WKT 落库
from shapely.geometry import shape
from shapely import wkt

def _add_wkt_geometry(self, uri, geometry_dict):
    geom = shape(geometry_dict)
    wkt_literal = Literal(geom.wkt, datatype=GEO.wktLiteral)
    self.g.add((uri, GEO.hasGeometry, geom_node))
    self.g.add((geom_node, GEO.asWKT, wkt_literal))
```

### 6.5 编码决策 provenance 入 KG

新增扩展谓词:
- `pln:decided_by {rule|llm|human|default}`
- `pln:decision_confidence`
- `pln:decision_evidence`
- `pln:mapping_basis`(映射的标准出处,§2.2 的 basis)

这让"编码可回溯到教材和规范"从文档层落实到**图斑级数据层**。

---

## 7. 质量与幂等(DLQ + immutable)

### 7.1 DLQ 三类分流

- **dlq/geometry**:几何无效(`must_be_valid` 失败)
- **dlq/mapping**:映射缺失(unmapped)
- **dlq/review**:待人工(manual/low-confidence)

每类带原始 feature + 原因 + 来源 layer_type;管道不中断。

### 7.2 消除 tempfile

ingest.py L647/L675 两处 `NamedTemporaryFile` 改为直接解析内存 dict(adapter 签名已按此设计)。

### 7.3 hash-keyed artifacts

`raw_gis_data`/`typed_features`/`village_bundle`/`spatial_relations`/`kg_graph` 五层 asset 各以 `hash(model_dump_json() + registry_version + mappings_version)` 为键持久化;同键跳过,实现 immutable/idempotent。

SDA 的调度用轻量 Python 编排表达(不引入 Dagster 依赖,asset 边界与声明式依赖保留,引擎后置)。

---

## 8. 为后续 Agent 架构预留接口

用户明确:agent 架构重构(ParseAgent 拆分、explore 子 agent、flash LLM 预填充 bundle)不在本次范围,但管道设计要"考量和利用"这些方向。具体预留点:

| 预留点 | 设计 | 后续消费方 |
|--------|------|-----------|
| `DisambiguationContext` Pydantic 模型 | 闭集 candidates + validator,可被 flash LLM + instructor 直接消费 | tool agent / flash LLM |
| `Condition` 模型树 | 可被 LLM `with_structured_output(Condition)` 直接生成 | analysis LLM(规则生成) |
| `VillageBundle.add(feature)` 方法 | tool agent 可增量预填充而不需要知道内部结构 | tool agent / flash LLM |
| `ContextBlock` 已是 Pydantic | 可直接作为 explore 子 agent 的输入 schema | explore 子 agent |
| `Resolution.needs_llm(ctx)` | L1 规则消歧后的 L2 入口,返回 `DisambiguationContext` | tool agent 中的 flash LLM |
| `@kg_builder` 装饰器 | 后续新增图层类型只需写一个 builder 函数 + YAML 条目 | 任何 KG 扩展 |

---

## 9. 分阶段实施计划

**分支**:`refactor/v4-pydantic-du-pipeline`(从当前 main fork)

| Phase | 内容 | 主要文件 | 验收标准 | 风险 |
|-------|------|---------|---------|------|
| **0** | 基线冻结:金田村 golden bundle + golden KG 快照 | `tests/integration/` | 基线可重复 | 无 |
| **1** | Pydantic v2 模型迁移:base.py + spatial_types.py 30+ dataclass -> BaseModel + DU;中文字段 `Field(alias=...)`;`field_validator` 强制 geometry type;删除 `_raw` 用 `extra="allow"`;删除大部分 `from_geojson_feature` | `schema/types/` | 全测试通过;DU `_feature_adapter.validate_python(dict)` 正确路由 30+ 子类 | **高**:核心类型,全链路依赖 |
| **2** | 统一编码元模型:encodings 统一 schema + mappings 统一 1:N + 修 0602 键覆盖 + `Condition` 模型树替代字符串 DSL + planning_zone_rules condition 迁移 + `_GHYTBM_TO_PLANNING_ZONE` 出硬编码 | `encodings/dicts/`, `expr_eval.py`(新), `rules/*.yaml` | 0602 两候选可达;旧 lookup 函数输出不变(兼容视图);全部 Condition 可求值 | 中 |
| **3** | Registry 元模型扩展 + DU 路由替代 isinstance 链 + `_assign_to_bundle` 删除 + `_TYPE_BINDINGS` 改 YAML 派生 + `bundle.add()` 方法 | `layer_registry.py`, `catalog.py`, `gis_layer_registry.yaml` | golden bundle 快照对齐;新增测试层只改 YAML 入 bundle | 高 |
| **4** | LayerGroup 动态化 `_layers: dict` + 兼容 property + `constraint_polygons` 查 registry | `canonical.py` | 旧 property 行为不变;golden bundle 对齐 | 中 |
| **5** | 6 adapter 策略 + 消除 tempfile + `field_mapping` 用 alias 替代(删除 v3 的 YAML 块) | `data/adapters/`(新), `ingest.py` | 新增一个测试层只改 YAML 即入 bundle;tempfile 消除 | 中 |
| **6** | `@kg_builder` 装饰器 + builder 循环 + 签名统一 + GeoSPARQL 一次性替换(不双写)+ WKT literal + provenance 谓词 | `kg/builder/`, `ontology.py`, `queries/` | golden KG:4 标准谓词替换完成 + 4 pln 扩展保留 + 三角数不膨胀(仅谓词 URI 变化) | 中 |
| **7** | L2 接口预留:`DisambiguationContext`/`DisambiguationDecision` 模型 + DLQ 三类 + `Resolution.needs_llm()` + provenance 入 KG(不实现 LLM 调用) | `encodings/disambiguation.py`(新), `data/adapters/`(DLQ) | 模型可序列化;DLQ 通道通;`Resolution.needs_llm` 返回正确 `DisambiguationContext` | 低 |

**依赖关系**:0->1->2->3->4->5->6->7。其中 2 可与 1 并行(不同文件域),但合并顺序保持 2->3。3 依赖 1(DU 模型)。

---

## 10. 回应三个核心问题

**Q1 怎么规范地自动处理各异 GIS 数据?**

Pydantic v2 Discriminated Union + geopandas `read_file()` 自动格式检测 + adapter 策略模式(6 标准 + custom 扩展)。DU 的 `layer_type` discriminator 在解析期自动路由到正确子类,`field_validator` 在构造时强制 geometry type,`Field(alias=...)` 原生处理中文字段名。新层 = 1 条 YAML(选 adapter + bundle_target + kg 映射),90% 场景零 Python。

**Q2 怎么规范地管理(添加一种数据太复杂)?**

两级单一入口:**图层**走 `gis_layer_registry.yaml`(元模型全集),**编码与映射**走 `dicts/`(encodings 统一 schema + mappings 统一 1:N schema + 目录自注册)。runtime 不再压平映射、不再散落硬编码。`_assign_to_bundle` 的 33 分支 isinstance 链删除,`_TYPE_BINDINGS` 手写表改为从 YAML 派生。添加新层从 7-8 文件 ~200 行缩减为 1 个 YAML 5-10 行。

**Q3 没有充分利用数据内在性质?**

三层利用:
- **geometry_kind** -> Pydantic `field_validator` 在构造时强制,DU discriminator 自动决定 morphology 分组(point/line/polygon),不需要人工指定或 isinstance 判断;
- **DLBM 编码体系** -> `Condition` 模型树 + 规则引擎统一推导分类层次/用途分区/法律约束,不再散布 `if dlbm.startswith("31")` 式特判;
- **group 语义分组** -> `constraint_polygons` 等聚合 property 自动查 registry 中 `spatial.is_constraint=true` 的所有层,新增约束层自动纳入聚合。

---

## 附录:范式来源与对齐

| 范式 | 来源 | 对齐点 |
|------|------|--------|
| Pydantic Discriminated Unions | context7: pydantic (`discriminator='el_type'`) | §1.2 GisFeature DU |
| geopandas read_file() 自动格式检测 | context7: geopandas | §5.2 adapter 复用 |
| Software-Defined Assets | context7: dagster (declarative automation) | §7.3 hash-keyed assets |
| GeoSPARQL 标准拓扑关系 | context7: ogc-geosparql (sfTouches/ehContains/RCC8) | §6.4 谓词一次性替换 |
| Schema Layer / Data Layer 分离 | KnowWhereGraph paper | §1 模型迁移 + §6 KG 构建 |
| 编码谱系考证(法定枚举闭集) | v3 §1 + scene#2 研究 | §2 统一编码元模型 |
| 1:N 原生映射 + 不压平 | v3 §2.2 | §2.2 mappings 统一 schema |
| 消歧决策梯(L0-L3) | v3 §3 | §3(调整 L2 触发点) |
| adapter 策略模式 | v3 §5.2 | §5.2(简化签名) |
| DLQ 三类分流 | v3 §7 + geospatial ETL guides | §7.1 |
| immutable + idempotent | geospatial ETL guides | §7.3 |

---

## 附录:现状事实(代码调查摘要)

- `catalog.py` L312-439 `load_village_bundle()`、L538-626 `_assign_to_bundle` 33 个 isinstance 分支、L404 `dlbm.startswith("31")` 水域兜底;
- `layer_registry.py` L80-135 `_TYPE_BINDINGS` 手写表;
- `canonical.py` 23+8+5 硬编码 LayerGroup 字段,无 _layers;
- `ingest.py` L452 `_init_feature_registry`、L647/L675 tempfile;验证收集制(strict=False 默认);
- 6 体系字典 schema 各异;3 映射 3 种 schema 且运行时压平;0602 键被覆盖;`_PROPOSAL_FILES` 硬编码;
- `candidate_engine.py` 已有 ClassificationProposal(exact/conditional/ambiguous),**未被 PARSE 调用**;
- `ontology.py` GEO 命名空间零使用;Relations 8 active + 4 兼容;
- `builder/base.py` 硬编码顺序调用 mixin;`layer1.py` 1369 行建 10 类实体;
- `instructor_client.py` 提供 `get_instructor_client()`/`get_flash_model()`,**零外部调用者(死代码)**;
- ParseAgent(`parse/agent.py` 1860 行)承担 10+ 职责:section 分类、project 提取、target 提取、regulation 提取、table 提取、validation+merge、确定性后修正、几何 grounding、KG 查询、schema 约束 prompt 组装;
- 分析 agent(`agent/analysis/node.py`)与 GIS agent(`agent/gis/`)是两个独立 LangGraph 图,仅通过 DB 报告通信;
- `compute_context_blocks(bundle)` 产出 8 种 ContextBlock(Pydantic),注入 PARSE state + module globals;
- 规划文本由 `PlanningTextGenerator.generate()` 产出,flash LLM(`create_flash_llm`)填充 S-GENERATE 文章。
