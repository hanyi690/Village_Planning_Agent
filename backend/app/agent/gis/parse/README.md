# PARSE Agent 子包

> 规划文本 -> 空间意图。消费 L3 报告 + ContextBlock 列表，产出类型化 `SpatialPlanningIntent` / `SpatialOperation` / `SpatialConstraint`。

---

## 一、定位

PARSE 是 GIS Agent 的 **PLAN 阶段执行核**，与 `execute/`（DELIVER 阶段）平级。它把自然语言规划报告转化为下游可执行的空间意图，核心解决"文本 -> 结构化空间目标"的语义鸿沟。

### PARSE = LLM as Formalizer + Spatial Grounder

PARSE 不是"信息提取器"，而是**从自然语言到形式化约束的编译器**（ACL 2025 综述 *LLMs as Planning Formalizers* 范式）。它的产出不是"待解释的柔性意图"，而是"可直接使用的约束包"。

| 阶段 | 学术对应 | PARSE 实现 |
|---|---|---|
| `explore_*` (Think) | Constraint Decomposition | LLM 自由推理 + 调用 KG 工具查询空间上下文 |
| `format_*` (Format) | Formal Encoding | LLM 将草稿格式化为严格 Pydantic 输出 |
| post-format | Spatial Grounding | 调用 `spatial_ops.grounding` 填充空间锚定 |

**关键特征**：
- **空间感知**：通过 `ContextBlock` 列表注入空间关系与锚点，不直接接触原始 GeoJSON 几何
- **Think-Then-Format**：探索阶段自由推理 + 工具调用，格式化阶段强制 Pydantic 输出
- **Schema 强制**：输出为严格 Pydantic 模型，保证 PARSE -> EXECUTE 交接可靠
- **空间锚定义**务：每个空间描述必须解析为 `candidate_bsms` + `bbox`，而非文本标签

---

## 二、图架构（agent.py:1405）

```
START
  -> classify_sections                       # 文档分节分类
      │  (route_by_section, Send fan-out)
      ├──-> explore_projects -> format_projects ──-> validate_and_merge
      ├──-> explore_targets  -> format_targets  ──-> validate_and_merge
      ├──-> extract_regulations ─────────────────-> validate_and_merge
      └── extract_tables ────────────────────────-> validate_and_merge
                                                    │  (should_retry)
                                                    ├── retry -> classify_sections
                                                    └── end  -> END
```

### Think-Then-Format 模式

| 阶段 | thinking | json_schema | tools | 职责 |
|------|----------|-------------|-------|------|
| `explore_*` | ON | OFF | ON | LLM 自由推理 + 调用 lookup_code/resolve_place/query_village_kg，产出自然语言草稿 + 编码/地名映射 |
| `format_*` | OFF | ON | OFF | LLM 将草稿格式化为严格 Pydantic 输出（ guaranteed compatible） |

### 节点说明

| 节点 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `classify_sections` | planning_text | `section_map` + `parse_strategy` | 文档分节，决定解析策略（full/incremental/section_only） |
| `explore_projects` | 项目章节 | `draft_operations` + `code_mappings_projects` | ReAct 探索项目类内容 |
| `format_projects` | 探索草稿 | `raw_operations`（增量） | 格式化为 `SpatialOperation` |
| `explore_targets` | 目标章节 | `draft_targets` + `code/place_mappings_targets` | ReAct 探索用地目标 |
| `format_targets` | 探索草稿 | `raw_targets`（`SpatialPlanningIntent`） | 格式化分区/设施/轴线目标 |
| `extract_regulations` | 规制章节 | `raw_constraints` | regex(70%) + LLM(30%) 混合提取约束 |
| `extract_tables` | 表格章节 | `raw_tables` | schema 推断提取指标/分区/设施表 |
| `validate_and_merge` | 全部 raw_* | `operation_sequence` / `constraint_set` / `planning_intent` | 汇聚 + 校验 + 重试决策 |

---

## 三、工具

PARSE Agent 在 `explore_*` 阶段可用三个工具（`agent.py`）：

| 工具 | 用途 |
|------|------|
| `lookup_code` | 查询用地名称 -> GHYTBM 编码（附录5规划用途编码） |
| `resolve_place` | 查询地名 -> GIS 空间锚点（NaturalVillageAnchor / FacilityAnchor） |
| `query_village_kg` | 查询 KG 空间上下文（村锚点 / 设施 / 道路 / 保护地块 / 三区三线 / VNE 汇总） |

工具执行通过 `_get_current_parse_kg()`（`agent.py:139`）从 `KGManager.get_any_kg()` 获取 KG 实例。

---

## 四、状态与输出（state.py）

### ParseAgentState

内部状态，独立于 LAYOUT Pipeline：

| 字段组 | 字段 | 说明 |
|--------|------|------|
| 输入 | `planning_text`, `village_name`, `context_blocks` | 文本 + ContextBlock 空间上下文 |
| 分类 | `section_map`, `parse_strategy` | 分节结果 + 策略 |
| 中间 | `raw_operations`, `raw_constraints`, `raw_targets`, `raw_tables` | 类型化中间结果 |
| 校验 | `validation_errors`, `parse_round`, `is_valid` | 校验状态 |
| 输出 | `operation_sequence`, `constraint_set`, `planning_intent` | 最终产出 |
| 草稿 | `draft_operations`, `draft_targets` | Phase A 探索产出 |
| 映射 | `code_mappings_*`, `place_mappings_*` | 编码/地名映射（projects/targets 分键避免并发冲突） |

### 核心输出模型

- **`SpatialPlanningIntent`**（`parse_contracts.py`）：分区目标 `zone_targets` + 设施 `facilities` + 轴线 `development_axes` + 道路 `road_targets` + 面积约束 + 指标表 + 三区三线
- **`SpatialOperation`**（`state.py:116`）：原子空间操作（create/split/merge/modify/reclassify），带 `SpatialAnchor` 双阶段定位
- **`SpatialConstraint`**：空间约束规则
- **`SpatialAnchor`**（`state.py:79`）：PARSE 预解析 + LAYOUT 确认的双阶段定位

### 面向各子任务的输出

| 子任务 | PARSE 产出字段 | 消费方 |
|---|---|---|
| **layout** | `zone_targets[i].land_use/area_ratio/density/adjacency_rules/vne_code` | `_intent_to_targets()` -> MIP |
| **facility** | `facilities[i].type/status/direction/location_hint/anchor_village/candidate_bsms/anchor_point` | `FacilityPlacer.place()` |
| **axis** | `development_axes[i].direction/axis_type/label/connects/start_anchor/end_anchor` | `AxisBuilder.build()` |
| **road** | `road_targets[i].road_level/width_m/connects/start_anchor/end_anchor` | （待实现 road generator） |
| **operations** | `operation_sequence[i].action/target_parcels/spatial_anchor.candidate_parcels` | `_apply_operations()` |

---

## 五、空间接地（Spatial Grounding）

PARSE 不直接读 GeoJSON，而是通过 `ContextBlock` 列表（`app/modules/spatial_ops/context.py:compute_context_blocks(bundle)`）获取模块化空间上下文卡片。v4.3 起替换单体 `SpatialContext`，每个 `ContextBlock` 编码一个空间认知维度：

- `VILLAGE_META`：村庄基础统计（地块数、总面积、建设边界面积、村中心坐标）
- `LANDUSE_DIST`：地类分布（按 dlbm 分组统计，含地块数和面积）
- `RESIDENTIAL_CLUSTERS`：居民点锚点（聚类自居住地块 + 注记命名合并）
- `FACILITIES`：设施精确锚点（来自 typed 设施/注记要素）
- `SPATIAL_RELATIONS`：村组间语义关系（east_of / adjacent_to / contains / near）
- `CONSTRAINTS`：保护边界摘要（永久基本农田 / 生态红线 / 历史文化等）
- `ZONE_ADJACENCY`：分区邻接矩阵
- `TERRAIN`：地形剖面（P2 预留，无 DEM 数据时返回 None）

### 空间锚定义务（v5.0 设计目标）

PARSE 作为 Formalizer，其"形式化"必须包括**空间形式化**。仅输出 `ZoneTarget(spatial_preference="村北")` 是不够的--EXECUTE 无法从"村北"字符串推导空间决策。

**所有空间计算由 `spatial_ops.grounding` 完成**，PARSE Agent 只调用，不内联计算：

| 用户描述 | PARSE 调用 spatial_ops | 产出的空间锚定 |
|---|---|---|
| "村北" | `resolve_directional_bbox(center, "北")` -> `query_parcels_in_bbox` | `candidate_bsms + bbox` |
| "靠近刘村" | `query_parcels_near_entity(center, 500)` | `candidate_bsms + proximity_weights` |
| "避开基本农田" | `query_excluded_parcels(blocks, "farmland_protection")` | `excluded_bsms` |
| "沿河" | `query_parcels_near_entity(river_center, 200)` | `candidate_bsms` |

`SpatialAnchor` 的双阶段定位：
1. **PARSE 预解析**：`location_desc` 匹配 `RESIDENTIAL_CLUSTERS` / `FACILITIES` 块 -> 候选地块 + 置信度
2. **LAYOUT 确认**：`resolve_place` 工具确认或修正锚点

---

## 六、输入输出契约

```
输入: ParseAgentState(planning_text, village_name, context_blocks)
输出: {
  operation_sequence: List[SpatialOperation],   # 空间操作序列
  constraint_set:     List[SpatialConstraint],   # 空间约束集
  planning_intent:    SpatialPlanningIntent,     # 分区/设施/轴线目标
  validation_errors:  List[str],                 # 校验错误
}
```

下游 `layout_pipeline.py:_parse_intent_node` 消费这些输出，注入 `GISPipelineState` 供 EXECUTE 使用。同时 PARSE 通过 `add_intent`/`add_operations`/`add_constraints`/`add_spatial_relations` 将结果写入 `ProjectKG` Layer 3（项目级，见 `modules/kg/README.md` §六），供 EXECUTE 经 `ConstraintCompiler` 读取。

---

## 七、KG 集成（v5.0 设计目标）

### 7.1 流水线顺序修正

当前流水线顺序存在倒置问题：

```
当前（错误）:  parse_intent -> fetch_gis_data -> build_kg -> execute
               ↑ PARSE 在 KG 构建前运行，query_village_kg 获取陈旧 KG

目标（正确）:  fetch_gis_data -> build_kg_l1l2 -> parse_intent -> write_kg_l3 -> execute
               ↑ KG L1+L2 先构建    ↑ PARSE 查询当前 KG    ↑ 写入 L3
```

### 7.2 统一 Intent -- 无需转换器

PARSE 产出 `SpatialPlanningIntent`（Pydantic），KG 直接消费此类型，**不需要转换为 `PlanIntent`（dataclass）**。

**根本原则：类型应该反映语义，而非格式。** Pydantic 和 dataclass 的差异是技术细节，不应该影响领域模型。`SpatialPlanningIntent` 既是 PARSE 的运行时表示，也是 KG 的存储表示。KG 的 `_add_structured_intent` 直接接受 `SpatialPlanningIntent`，将其字段序列化为 RDF 三元组。

| 旧设计（两套 Intent） | 新设计（统一 Intent） |
|---|---|
| `parse_contracts.SpatialPlanningIntent` (Pydantic) + `context_contracts.PlanIntent` (dataclass) | 只有 `parse_contracts.SpatialPlanningIntent` |
| 需要 `intent_converter.py` 做格式转换 | 不需要转换器 |
| 两处字段同步维护 | 一处维护 |
| 文本描述在转换时丢弃 | 文本描述作为一等公民保留 |

`context_contracts.py` 中的 `PlanIntent` / `ZoneTarget` / `FacilityTarget` / `RoadTarget`（SpatialIntentUnit 子类）废弃。`PlanBlock`（L4）和 `ContextBlock`（L1）保留不变。

### 7.3 文本描述作为一等公民

KG 不仅仅是"数值约束存储"，它还必须保留**人类可读的语义锚点**。文本描述不是"噪声"，而是：

1. **溯源证据**：证明规划意图的来源
2. **查询接口**：用户后续修改"把村北的商业改到村南"时，需要知道"村北"对应哪个意图
3. **可视化标签**：地图上显示"商业（村北）"而非"ZoneTarget #3"

PARSE 在 `explore_*` 阶段通过查询 KG 将"村北"转化为 `candidate_bsms`，但**"村北"这个原始文本必须保留在 KG 中**。

### 7.4 空间锚定 + 文本描述存储

KG Layer 3 同时存储空间锚定和文本描述：

| PARSE 产出 | KG 三元组 |
|---|---|
| `candidate_bsms: ["P001", ...]` | `pln:ZoneTarget -> pln:candidate_bsm -> pln:parcel_P001` |
| `candidate_bbox: (x1, y1, x2, y2)` | `pln:ZoneTarget -> pln:candidate_bbox -> "x1,y1,x2,y2"` |
| `excluded_bsms: ["P100", ...]` | `pln:ZoneTarget -> pln:excluded_bsm -> pln:parcel_P100` |
| `spatial_hint: "村北"` | `pln:ZoneTarget -> pln:spatial_hint -> "村北"` |
| `description: "村北新增15%商业用地"` | `pln:ZoneTarget -> pln:description -> "村北新增15%商业用地"` |
| `raw_text: "..."` | `pln:SpatialPlanningIntent -> pln:raw_text -> "..."` |

---

## 八、类型契约变更计划（v5.0）

### 8.1 统一 Intent -- 废弃 PlanIntent

`context_contracts.py` 中的 L3 类型废弃，统一使用 `parse_contracts.py` 的 Pydantic 类型：

| context_contracts（废弃） | parse_contracts（统一） | 说明 |
|---|---|---|
| `PlanIntent` | `SpatialPlanningIntent` | KG 直接消费 Pydantic 类型 |
| `ZoneTarget` (SpatialIntentUnit) | `ZoneTarget` (BaseModel) | 统一为 Pydantic |
| `FacilityTarget` (SpatialIntentUnit) | `FacilityTarget` (BaseModel) | 统一为 Pydantic |
| `RoadTarget` (SpatialIntentUnit) | `AxisTarget` (BaseModel) | 统一为 Pydantic |
| `PlanningConstraint` | `SpatialConstraint` (BaseModel) | 统一为 Pydantic |
| `SpatialIntentUnit` | 废弃 | 不再需要 dataclass 层级 |

**保留不变**的 context_contracts 类型：`PlanBlock` / `ParcelChange` / `FacilityChange` / `RoadChange` / `SettlementChange`（L4 增量变更集）、`ContextBlock` / `SpatialCognitiveUnit` / 各 Anchor（L1 现状实体）。

### 8.2 已实现：SpatialPlanningIntent 增强（parse_contracts.py）

每个有空间维度的类型包含**三层字段**：形式化约束 + 空间锚定 + 语义锚点。

**`FacilityTarget` 新增字段**（`direction` 驱动 FacilityPlacer 的 `_place_new` 方向决策）：

```python
class FacilityTarget(BaseModel):
    type: str = ""
    status: Literal["existing_preserve", "planned_new", ...] = "existing_preserve"
    location_hint: str = ""
    service_radius: Optional[int] = None
    anchor_village: Optional[str] = None
    # === 空间锚定 ===
    direction: str = "center"         # "north"/"south"/"east"/"west"/...
    candidate_bsms: List[str] = Field(default_factory=list)
    anchor_point: Optional[Tuple[float, float]] = None  # 精确坐标 (lon, lat)
    # Semantic anchors
    semantic: SemanticMetadata = Field(default_factory=SemanticMetadata)
```

**`AxisTarget` 新增字段**（`axis_type`/`label` 驱动 AxisBuilder 的轴线类型判断）：

```python
class AxisTarget(BaseModel):
    direction: str = ""
    reference_feature: str = ""
    connects: List[str] = Field(default_factory=list)
    # === 轴线类型 ===
    axis_type: str = "primary"        # "primary" / "secondary" / "spatial_control"
    label: str = ""                   # "南北发展轴"
    # === 空间锚定 ===
    start_anchor: Optional[Tuple[float, float]] = None
    end_anchor: Optional[Tuple[float, float]] = None
    corridor_bsms: List[str] = Field(default_factory=list)
    # Semantic anchors
    semantic: SemanticMetadata = Field(default_factory=SemanticMetadata)
```

**新增 `RoadTarget`**（road 子任务不再为空）：

```python
class RoadTarget(BaseModel):
    road_level: str = ""               # "主干道"/"次干道"/"支路"/"村道"
    width_m: float = 0.0
    connects: List[str] = Field(default_factory=list)  # ["村北", "村南"]
    # === 空间锚定 ===
    start_anchor: Optional[Tuple[float, float]] = None
    end_anchor: Optional[Tuple[float, float]] = None
    path_bsms: List[str] = Field(default_factory=list)
    semantic: SemanticMetadata = Field(default_factory=SemanticMetadata)
```

**`SpatialPlanningIntent` 新增 `road_targets`**：

```python
class SpatialPlanningIntent(BaseModel):
    zone_targets: List[ZoneTarget] = Field(default_factory=list)
    facilities: List[FacilityTarget] = Field(default_factory=list)
    development_axes: List[AxisTarget] = Field(default_factory=list)
    road_targets: List[RoadTarget] = Field(default_factory=list)  # NEW
    # ... 面积约束 / 指标表 / 三区三线 ...
    # Semantic anchors
    raw_text: str = ""
    reasoning_trace: str = ""
```

### 8.3 post-format 确定性锚定（agent.py 已实现）

`format_targets_node` 后，LLM 产出 Pydantic 类型后执行三个确定性锚定函数：

```python
# agent.py -- 在 format_targets_node 中，LLM 输出后调用
result.facilities = _auto_fill_facility_anchor(
    result.facilities, dict(state.place_mappings_targets))
result.development_axes = _auto_fill_axis_anchor(
    result.development_axes, dict(state.place_mappings_targets))
result.road_targets = _auto_fill_road_anchor(
    result.road_targets, dict(state.place_mappings_targets))
```

各函数从 `resolve_place` 工具结果（`place_mappings`）中匹配地名，填充 `candidate_bsms`/`anchor_point`/`start_anchor`/`end_anchor`。**零 LLM 调用，零空间计算**（空间计算由 `spatial_ops.grounding` 后续完成）。

### 8.4 桥接器更新（generate.py 已实现）

`_intent_from_typed()` 将新字段传递到 `FacilityIntent`/`AxisIntent`：

```python
# 设施方向
facilities.append(FacilityIntent(
    ..., direction=ft.direction if hasattr(ft, 'direction') else "center"))
# 轴线类型+标签
axes.append(AxisIntent(
    ..., axis_type=at.axis_type if hasattr(at, 'axis_type') else "primary",
    label=at.label if hasattr(at, 'label') else ""))
```

### 8.5 KG `_add_structured_intent` 直接消费 Pydantic

```python
# KG layer3.py -- 直接接受 SpatialPlanningIntent，无需转换
def _add_structured_intent(self, intent: SpatialPlanningIntent) -> None:
    for zt in intent.zone_targets:
        z_uri = PLN[f"zone_target_{zt.land_use}"]
        self.g.add((z_uri, RDF.type, EntityTypes.ZoneTarget))
        # 形式化约束
        self.g.add((z_uri, PLN.land_use, Literal(zt.land_use)))
        self.g.add((z_uri, PLN.target_area_ha, Literal(zt.target_area_ha)))
        # 空间锚定
        for bsm in zt.candidate_bsms:
            self.g.add((z_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        # 语义锚点（文本描述）
        if zt.spatial_hint:
            self.g.add((z_uri, PLN.spatial_hint, Literal(zt.spatial_hint)))
        if zt.description:
            self.g.add((z_uri, PLN.description, Literal(zt.description)))
    # raw_text
    if intent.raw_text:
        self.g.add((PLN.village, PLN.raw_planning_text, Literal(intent.raw_text)))
```

**没有转换器，没有中间类型，没有格式映射。** Pydantic 模型的字段直接序列化为 RDF 三元组。

---

## 九、实施计划

| 阶段 | 任务 | 状态 |
|---|---|---|
| 1 | `spatial_ops/grounding.py` 创建 + API 实现 | TODO（别人负责） |
| 2 | `parse_contracts.py` 增加空间锚定 + 语义锚点字段 | ✅ 已完成 |
| 3 | 废弃 `context_contracts.py` 中 L3 类型（PlanIntent 等） | TODO（别人负责） |
| 4 | KG `layer3.py` 改为直接消费 `SpatialPlanningIntent` | TODO（别人负责） |
| 5 | PARSE Agent `format_targets` 后调用 `spatial_ops.grounding` | 部分完成（auto-fill 已实现，grounding 待接） |
| 6 | 流水线重排：fetch -> build_kg -> parse -> write_kg_l3 -> execute | TODO |
| 7 | 修复 PARSE Agent `state.spatial_context` bug | TODO |
| 8 | 修复 `tools/gis/kg.py` 死方法调用 | TODO |
| 9 | 测试：grounding 正确性 + KG 直存验证 + 现有回归 | TODO |

---

## 十、相关文档

- `../README.md` - GIS Agent 包总览
- `../execute/README.md` - EXECUTE Agent（下游消费者）
- `app/modules/spatial_ops/README.md` - 空间计算唯一层（grounding 实现）
- `app/modules/parsing/README.md` - parsing 工具层（PARSE 调用提取工具）
- `app/modules/kg/README.md` - ProjectKG 桥接层（PARSE 写入 Layer 3）
- `app/modules/schema/contracts/parse_contracts.py` - 最终契约类型
- `docs/gis/00_SYSTEM_DESIGN.md` §四 - PARSE 理解层设计
- `docs/gis/diagnostics/01_PARSE_AGENT_STATUS.md` - PARSE Agent 状态诊断
- `docs/gis/proposals/01_PARSE_SPATIAL_ENHANCEMENT.md` - 空间增强提案
