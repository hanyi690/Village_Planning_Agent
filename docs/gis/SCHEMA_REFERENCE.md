# GIS Schema 子包 — 数据定义、编码体系与输出规范

> **单一真相源 (Single Source of Truth)**：所有 GIS 数据模型、编码映射、GDB 输出规范统一定义于此包。
> 其他模块（fetcher、tool、generator）仅消费 schema 定义，不自行定义编码或字段结构。

## 规范依据

Schema 包的设计严格遵循以下技术规范：

| 规范文件                                   | 适用范围                        | Schema 对应                                                             |
| ------------------------------------------ | ------------------------------- | ----------------------------------------------------------------------- |
| 《广东省村庄规划编制基本技术指南（试行）》 | 规划分区、用地分类、规划目标    | `ghytbm.yaml`, `planning_targets.yaml`, `land_use_structure.yaml` |
| GB/T 21010-2017《土地利用现状分类》        | 现状地类编码 (DLBM)             | `dlbm.yaml`                                                           |
| 自然资发〔2023〕234号《用地用海分类》      | 用地用海分类代码 (YDYHFLDM)     | `ydyhfldm.yaml`                                                       |
| 《村庄规划用地分类》(住建部)               | V/N/E 村庄规划用地分类          | `vne.yaml`                                                            |
| 广东省县级土地利用总体规划数据库标准       | 规划分类编码 (GHFLBM)、GDB 图层 | `ghflbm.yaml`, `gdb_layers.yaml`                                    |
| 自然资源部《双评价指南》2019               | 动态分区决策规则                | `planning_zone_rules.yaml`, `dynamic_zoning.py`                     |
| DB22/T 3407-2022                           | 要素代码分类                    | `element_codes.yaml`                                                  |

---

## 包结构

```
schema/
├── __init__.py              # 统一导出 + 编码符号派生
├── canonical.py             # 规范数据模型 (BBox, GeoFeature, GISDataBundle)
├── intent.py                # 空间意图模型 (ZoneIntent, UnifiedSpatialIntent)
├── pipeline.py              # 管线输出模型 (ConflictReport, ExportResult)
├── output_profile.py        # 省级输出配置 (OutputProfile, LayerSpec)
├── encoding_registry.py     # 编码注册表 (EncodingRegistry)
├── classification.py        # 地类分类包装 (LandUseClass, ClassificationSchema)
├── dynamic_zoning.py        # 动态分区引擎 (DynamicZoningEngine)
├── gdb.py                   # GDB 图层注册表 + 字段填充
├── colors.py                # 颜色定义 (GB/T 21010 + GB/T 50280-98)
├── events.py                # SSE 事件契约 (camelCase 自动转换)
└── dicts/                   # YAML 字典中心 (单一真相源)
    ├── __init__.py           # 导出 get_center, CodeDictionary, DictionaryCenter
    ├── loader.py             # DictionaryCenter 加载器
    ├── candidate_engine.py   # 跨体系候选提案引擎
    ├── dlbm.yaml             # 三调地类编码 (GB/T 21010)
    ├── ghytbm.yaml           # 规划用途编码 (广东省指南附录5)
    ├── ghflbm.yaml           # 规划分类编码 (广东省数据库标准)
    ├── ydyhfldm.yaml         # 用地用海分类 (自然资发〔2023〕234号)
    ├── vne.yaml              # V/N/E 村庄规划用地分类 (住建部)
    ├── sddlbm_to_ydyhfldm.yaml # 三调→用地用海 候选提案表
    ├── element_codes.yaml    # 要素代码分类 (DB22/T 3407)
    ├── three_line_types.yaml # 三线管控图层定义
    ├── planning_zone_rules.yaml # ★ 动态分区规则引擎（唯一决策入口，DLBM仅为输入之一）
    ├── gdb_layers.yaml       # GDB 图层定义
    ├── field_defaults.yaml   # GDB 字段默认值规则
    ├── planning_targets.yaml # 规划目标指标表
    └── land_use_structure.yaml # 土地利用结构调整表
```

---

## 三大正交编码体系

Schema 包的核心设计是**三套正交编码体系**的共存与互转，每套体系服务于不同的规范要求：

### 1. DLBM / GHYTBM — 国标地类编码

| 编码   | 全称         | 标准             | 用途                     |
| ------ | ------------ | ---------------- | ------------------------ |
| DLBM   | 地类编码     | GB/T 21010-2017  | 现状地类标识（三调数据） |
| GHYTBM | 规划用途编码 | 广东省指南附录5  | 规划期末地类标识         |
| GHFLBM | 规划分类编码 | 广东省数据库标准 | 规划分类（更粗粒度）     |

**层级关系**：`GHFLBM → GHYTBM`（一对多），如 `1130(林地规划) → [1340(商品林), 1350(生态林)]`

**DLBM → 规划分区映射**（三级）：

```
DLBM → zone_type (功能分区 L1) → planning_zone (规划分区 L2) → primary_zone (三区 L3)
0101(水田) → 农业用地 → 农田保护区 → 农业空间
2121(宅基地) → 居住用地 → 村庄建设区 → 建设空间
0301(乔木林) → 生态绿地 → 林业发展区 → 农业空间
```

### 2. YDYHFLDM — 用地用海分类代码

| 编码     | 全称             | 标准                  | 用途                 |
| -------- | ---------------- | --------------------- | -------------------- |
| YDYHFLDM | 用地用海分类代码 | 自然资发〔2023〕234号 | 基数转换（跨省交换） |

**与 DLBM 的关系**：DLBM 是三调编码，YDYHFLDM 是新国标编码。大部分一一对应，少数一对多需人工决策。
转换通过 `sddlbm_to_ydyhfldm.yaml` 候选提案表实现。

### 3. V/N/E — 村庄规划用地分类

| 编码 | 全称           | 标准                       | 用途             |
| ---- | -------------- | -------------------------- | ---------------- |
| V    | 村庄建设用地   | 住建部《村庄规划用地分类》 | 村庄内部用地细分 |
| N    | 非村庄建设用地 | 同上                       | 村庄外建设       |
| E    | 非建设用地     | 同上                       | 农业/生态用地    |

**V/N/E → 规划分区映射**：

```
V11(住宅用地) → 居住用地 → 村庄建设区
V2(公共服务) → 公共服务用地 → 村庄建设区
E23(一般农用地) → 农业用地 → 一般农业区/农田保护区
E9(其他非建设用地) → 生态绿地 → 生态保护区/生态控制区
```

### 跨体系转换流程

```
三调 DLBM ──→ GHYTBM (规划用途) ──→ V/N/E (住建部分类)
    │                │                    │
    └──→ YDYHFLDM ──┘                    │
         (基数转换)                        │
              └──────────────────────────→ GHFLBM (规划分类)
```

**关键原则**：一对多转换不自动决定，由 `CandidateEngine` 返回候选提案，Agent 必须人工决策。

---

## 模块详解

### canonical.py — 规范数据模型

所有进入 Agent 管线的数据**必须**规范化为这些 Pydantic 模型。Provider 层负责 CRS 归一化（→WGS84）和类型强制转换。

| 模型              | 用途            | 关键字段                                         |
| ----------------- | --------------- | ------------------------------------------------ |
| `CRS`           | 坐标系枚举      | WGS84, CGCS2000, GCJ02                           |
| `BBox`          | 规范边界框      | west, south, east, north (OSMnx 2.x 顺序)        |
| `GeoFeature`    | 规范地理要素    | geometry (GeoJSON), properties, source_provider  |
| `LandUseParcel` | 地类图斑        | dlbm, area_ha, zone_type, planning_zone          |
| `GISDataBundle` | 完整 GIS 数据集 | boundary, landuse, roads, water_bodies, metadata |
| `GISMetadata`   | 数据溯源元数据  | village_name, bbox_wgs84, provider_sources       |

**CRS 策略**：所有坐标统一 WGS84 (EPSG:4326) 存储，度量运算按需投影 CGCS2000。

**广东省规范对应**：

- CGCS2000 坐标系 → `CRS.CGCS2000`
- 85国家高程基准 → DEM 数据处理
- ≥1:2000 比例尺 → BBox 精度约束

### intent.py — 空间意图模型

定义"什么放在哪里"的声明式意图，由 LLM 通过 `with_structured_output(UnifiedSpatialIntent)` 生成。

| 模型                     | 用途                                                    |
| ------------------------ | ------------------------------------------------------- |
| `ZoneIntent`           | 功能分区意图（用地类型、面积比、方向、邻接约束）        |
| `FacilityIntent`       | 设施点意图（类型、目标分区、位置提示）                  |
| `AxisIntent`           | 发展轴意图（方向、连接关系）                            |
| `ConstraintIntent`     | 空间约束（红线、保护线）                                |
| `UnifiedSpatialIntent` | 完整空间意图（zones + facilities + axes + constraints） |

**广东省规范对应**：

- 规划分区意图 → `ZoneIntent.land_use` 映射到 须匹配 `PLANNING_ZONE_NAMES` 6类
- 建设用地管制 → `ConstraintIntent` 编码 510/520/530/540
- 三线约束 → 生态红线、基本农田、历史文化保护线

### parse_state.py — PARSE 空间感知模型

PARSE Agent 的输入/输出模型定义。模型定义在 schema 层，计算逻辑在 `app/services/modules/gis/spatial_context.py`。

**输入模型**（替代原 GISSummary）：

| 模型                     | 用途                                                             |
| ------------------------ | ---------------------------------------------------------------- |
| `SpatialContext`       | 空间感知 GIS 上下文（统计 + 空间锚点 + 关系图 + 约束概要，~2KB） |
| `NaturalVillageAnchor` | 自然村空间锚点（名称 + 质心 + 图斑ID + 主导地类 + 邻接）         |
| `SpatialRelation`      | 空间关系三元组（subject + relation + object，从几何计算派生）    |
| `ConstraintSummary`    | 约束概要（分区类型 + 规则 + 面积 + 重叠关系）                    |

**输出模型**（增强原 OperationItem / ConstraintItem / PlanningIntent）：

| 模型                  | 用途                                                        |
| --------------------- | ----------------------------------------------------------- |
| `SpatialAnchor`     | 操作空间锚点（参照物 + 方向偏移 + 候选图斑 + 解析状态）     |
| `SpatialRule`       | 可计算空间规则（操作类型 + 主体 + 对象 + 距离）             |
| `ZoneTarget`        | 带空间偏好的分区目标（地类 + 面积比 + 方向偏好 + 邻接规则） |
| `SpatialPreference` | 分区空间偏好（方向 + 参照物）                               |
| `AdjacencyRules`    | 分区邻接规则（prefer + avoid）                              |

**SpatialAnchor 解析状态**：

| 状态           | 含义                   | LAYOUT 处理                 |
| -------------- | ---------------------- | --------------------------- |
| `anchored`   | 已锚定到具体图斑       | 直接使用 candidate_parcels  |
| `partial`    | 锚定到区域但未确定图斑 | resolve_place_name 缩小范围 |
| `unresolved` | 需 LAYOUT 阶段解析     | resolve_place_name 完整解析 |

**SpatialRule 映射**：

| 规划文本                       | SpatialRule                       | Shapely 等价            |
| ------------------------------ | --------------------------------- | ----------------------- |
| "允许建设区内不得安排基本农田" | no_overlap(建设区, 基本农田)      | intersection() == empty |
| "产业用地距居住区≥200m"       | buffer_exclusion(产业, 居住, 200) | distance() > 200        |
| "宅基地必须在建设边界内"       | contained_by(宅基地, 建设边界)    | within()                |

**SpatialContext 计算归属**：

- 模型定义：`schema/parse_state.py`（Pydantic BaseModel）
- 计算逻辑：`app/services/modules/gis/spatial_context.py`（`compute_spatial_context()` 函数）
- 自然村推断：从 GIS 图斑的 DLMC 字段 + 空间聚类动态推断，不依赖静态别名库

### pipeline.py — 管线输出模型

定义各管线阶段工具的结构化输出，用于 `llm.with_structured_output(Model)` 自动解析。

| 模型                 | 用途                                  |
| -------------------- | ------------------------------------- |
| `ConflictItem`     | 单个冲突（metric/constraint/spatial） |
| `ConflictReport`   | 冲突检测输出                          |
| `ViolationItem`    | 单个验证违规                          |
| `ValidationReport` | 布局验证输出（Worker-Evaluator 模式） |
| `AllocationResult` | MIP/贪心分配结果                      |
| `ExportResult`     | GDB 导出结果（14层 + 土地平衡表）     |

### output_profile.py — 省级输出配置

封装省份数据交换标准的差异，使生成核心无需修改即可适配新省份。

**广东省配置** (`OutputProfile.guangdong()`)：

| 属性                 | 值                                  | 规范依据             |
| -------------------- | ----------------------------------- | -------------------- |
| CRS                  | EPSG:4527 (CGCS2000 3° GK zone 39) | 广东省指南           |
| DB格式               | GDB                                 | 广东省数据库技术规范 |
| 用地分类标准         | VNE (住建部)                        | 广东省指南           |
| 现状编码             | DLBM (三调)                         | GB/T 21010           |
| 建设用地上限         | 21.66 ha                            | 金田村实测           |
| 耕地保有量下限       | 98.54 ha                            | 金田村实测           |
| 生态红线面积下限     | 365.28 ha                           | 金田村实测           |
| 有条件建设区占比上限 | 20%                                 | 广东省指南           |

**14 层输出架构**（5 现状 + 9 规划）：

| #  | 图层 ID               | GDB Key               | 几何            | 必选 | 规范对应                         |
| -- | --------------------- | --------------------- | --------------- | ---- | -------------------------------- |
| 01 | boundary              | admin_area            | MultiPolygon    | ✅   | GHCFW 行政区划                   |
| 02 | admin_boundary_line   | admin_boundary_line   | MultiLineString | ✅   | 行政区划界线                     |
| 03 | current_landuse       | current_landuse       | MultiPolygon    | ✅   | 现状地类图斑                     |
| 04 | current_road          | current_road          | MultiLineString | ✅   | 现状道路                         |
| 05 | current_annotation    | current_annotation    | Point           | ✅   | 现状注记                         |
| 06 | planned_landuse       | planned_landuse       | MultiPolygon    | ✅   | **QMDLTB 期末地类图斑**    |
| 07 | farmland_protection   | farmland_protection   | MultiPolygon    | ✅   | 永久基本农田                     |
| 08 | ecological_protection | ecological_redline    | MultiPolygon    | ✅   | 生态保护红线                     |
| 09 | historical_protection | historical_protection | MultiPolygon    | ❌   | 历史文化保护线                   |
| 10 | space_control_zone    | space_control_zone    | MultiPolygon    | ✅   | **JSYDGZQ 建设用地管制区** |
| 11 | land_use_zone         | land_use_zone         | MultiPolygon    | ✅   | **TDYT 土地用途分区**      |
| 12 | geological_hazard     | hazard_points         | Point           | ❌   | 地质灾害点                       |
| 13 | planned_road          | planned_road          | MultiLineString | ✅   | 规划道路                         |
| 14 | planned_annotation    | planned_annotation    | Point           | ✅   | 规划注记                         |

**广东省规范要求的 4 个必出图层**：GHCFW(01)、QMDLTB(06)、TDYT(11)、JSYDGZQ(10)

### encoding_registry.py — 编码注册表

从 DictionaryCenter 自动派生的编码查找表，懒加载单例。

```python
reg = get_encoding_registry()
zone = reg.dlbm_to_zone["0101"]       # "农业用地"
planning = reg.dlbm_to_planning["0101"]  # "农田保护区"
```

**核心映射**：

- `dlbm_to_zone`: DLBM → 功能分区 (8类)
- `dlbm_to_planning`: DLBM → 规划分区 (6类)
- `dlbm_to_primary`: DLBM → 三区 (3类)
- `dlbm_to_name`: DLBM → 中文名称
- `dlbm_to_category_sets`: DLBM → 类别标签集

> **⚠️ 重要**：`dlbm_to_zone`、`dlbm_to_planning`、`dlbm_to_primary` 等映射仅表示基于现状地类的统计倾向，**不反映空间管控结果**。获取真实规划分区请使用 `DynamicZoningEngine` 的 `resolve_zone()` 方法，该方法会叠加三区三线、建设边界等空间约束。直接使用 `dlbm_to_planning` 等同于跳过规则引擎，仅在无空间数据时作为低置信度兜底。

### classification.py — 地类分类包装

`LandUseClass` 数据类和 `ClassificationSchema` 不可变快照，提供导出方法：

- `to_dlbm_zone_type()`: DLBM → 功能分区字典（默认倾向，非最终分区）
- `to_dlbm_planning_zone()`: DLBM → 规划分区字典（默认倾向，非最终分区；获取真实分区请用 `DynamicZoningEngine.resolve_zone()`）
- `to_code_sets()`: 类别编码集合（BASIC_FARMLAND, ECOLOGICAL 等）
- `to_prompt_table()`: LLM 提示注入用 Markdown 表格

### planning_zone_rules.yaml — 动态分区规则引擎配置

**动态分区的唯一决策入口**。所有规划分区计算必须经过此规则引擎，DLBM 仅为输入之一。

**规则结构**：

```yaml
# planning_zone_rules.yaml — 动态分区规则引擎
# 规则按优先级从高到低执行，首条匹配即返回
# 未匹配任何规则时使用 DLBM 的 default_planning_zone（低置信度兜底）

rules:
  - id: eco_redline
    priority: 1
    condition:
      spatial_overlap: ecological_redline   # 图斑与生态红线重叠
      current_zone_type: [建设用地, 居住用地, 产业用地]  # 且当前为建设类
    result:
      planning_zone: 生态保护区
      confidence: high
      source: 三区三线

  - id: farmland_protection
    priority: 2
    condition:
      spatial_overlap: permanent_farmland   # 图斑与永久基本农田重叠
    result:
      planning_zone: 农田保护区
      confidence: high
      source: 永久基本农田保护

  - id: geo_hazard_buffer
    priority: 3
    condition:
      within_buffer:
        layer: geological_hazard_points
        distance_m: 500
      current_zone_type: [建设用地, 居住用地]
    result:
      planning_zone: 生态控制区
      confidence: medium
      source: 双评价指南

  - id: construction_boundary
    priority: 4
    condition:
      spatial_overlap: village_construction_boundary  # 图斑在村庄建设边界内
      current_zone_type: [居住用地, 公共服务用地, 产业用地, 商业用地, 交通用地]
    result:
      planning_zone: 村庄建设区
      confidence: high
      source: 村庄建设边界

  # 更多规则可按省份/地区扩展...

# 兜底策略：无规则匹配时
fallback:
  use: dlbm_default_planning_zone  # 使用 DLBM 的 default_planning_zone 属性
  confidence: low
  needs_decision: true              # 标记需人工确认
  message: "无空间约束规则匹配，使用地类默认倾向，请规划师复核"
```

**设计原则**：

1. **规则可配置**：新增/修改分区规则只需编辑 YAML，无需改代码
2. **优先级显式**：规则按 priority 字段排序，首条匹配即返回，避免歧义
3. **置信度标注**：每条规则输出 confidence（high/medium/low），低置信度结果必须人工确认
4. **来源可追溯**：每条规则携带 source 字段，指向规范依据
5. **省份可扩展**：不同省份可覆盖此文件（如广东省增加林业发展区规则），通过 OutputProfile 机制加载

**参考**：Municipal GIS Compliance Framework 的"versioned rule catalog"模式——规则本身是数据，不是代码，规则变更只需数据更新 + 重新评估，无需代码部署。

### dynamic_zoning.py — 动态分区引擎

基于 `planning_zone_rules.yaml` 规则 + 三线/建设边界空间约束的动态分区计算。**分区不来自地类，而来自规则**。

**决策规则**（按优先级从高到低）：

| 优先级 | 条件                      | 结果          | 规范依据         |
| ------ | ------------------------- | ------------- | ---------------- |
| 1      | 生态红线重叠 + 建设区     | → 生态保护区 | 三区三线         |
| 2      | 基本农田重叠              | → 农田保护区 | 永久基本农田保护 |
| 3      | 地质灾害500m缓冲 + 建设区 | → 生态控制区 | 双评价指南       |
| 4      | 无规则匹配时的兜底        | 使用 DLBM 的 `default_planning_zone`，置信度=low | GB/T 21010 |

**关键变更**：优先级 4 不再是"DLBM 静态映射"，而是低置信度兜底：

1. 规则引擎首先检查图斑是否与永久基本农田、生态红线、村庄建设边界重叠，若重叠则应用规则 1-3
2. 即使无评价数据，也基于已有的三线图层执行规则引擎（三线数据通常是可获得的）
3. 若仍无匹配，则返回 DLBM 的 `default_planning_zone`，且 `confidence = "low"`，Agent 应提示规划师复核
4. 兜底结果标记 `needs_decision=True`，进入人工确认队列

### gdb.py — GDB 图层注册表

GDB 输出的单一真相源，定义图层命名、字段结构和内部映射。

**命名规则**：`{prefix}_{description}_{feature_type_code}_{date}`

- 要素类型代码：PBL(面)、LJJ(线)、DMM(点)
- 示例：`JT_行政区划_PBL_20221212`

**QMDLTB 期末地类图斑字段**（广东省规范 20 必填字段）：

| 字段     | 类型    | 含义             | 来源             |
| -------- | ------- | ---------------- | ---------------- |
| BSM      | str:18  | 标识码           | 18位元素代码     |
| YSDM     | str:10  | 要素代码         | GB/T 标准编码    |
| TBH      | str:8   | 图斑号           | 顺序编号         |
| XZQHDM   | str:12  | 行政区划代码     | 12位行政区划     |
| XZQHMC   | str:100 | 行政区划名称     | 村名             |
| DLBM     | str:4   | 地类编码(现状)   | GB/T 21010       |
| DLMJ     | float64 | 地类面积         | CGCS2000度量     |
| QMDLBM   | str:4   | 期末地类编码     | 规划用途编码     |
| LYYSDM   | str:10  | 来源要素代码     | 现状要素代码     |
| MS       | str:90  | 描述             | 规划说明         |
| GHFLBM   | str:4   | 规划分类编码     | 广东省标准       |
| QMGHFLBM | str:4   | 期末规划分类编码 | = GHFLBM         |
| GHYTBM   | str:4   | 规划用途编码     | 广东省指南附录5  |
| GHYTMC   | str:20  | 规划用途名称     | GHYTBM→名称查找 |
| LSYSXZB1 | str:4   | 落实约束性指标1  | 规划目标         |
| LSZBMJ1  | float64 | 落实指标面积1    | 规划目标         |
| LSYSXZB2 | str:4   | 落实约束性指标2  | 规划目标         |
| LSZBMJ2  | float64 | 落实指标面积2    | 规划目标         |
| LSYSXZB3 | str:4   | 落实约束性指标3  | 规划目标         |
| LSZBMJ3  | float64 | 落实指标面积3    | 规划目标         |

**JSYDGZQ 建设用地管制区编码**：

| 代码 | 名称               | 颜色    | 含义       |
| ---- | ------------------ | ------- | ---------- |
| 510  | 允许建设区 (YXZQ)  | #FFE0B2 | 可建设     |
| 520  | 限制建设区 (XZZQ)  | #C8E6C9 | 限制性建设 |
| 530  | 有条件建设区 (YZQ) | #FFF9C4 | 条件性建设 |
| 540  | 禁止建设区 (KCQ)   | #FFCDD2 | 禁止建设   |

**enrich_gdb_fields()** 字段填充规则（来自 `field_defaults.yaml`）：

1. `copy_from`: 从另一字段复制（如 QMDLBM ← DLBM）
2. `from_param`: 从函数参数填充（如 XZQHDM ← xzqhdm）
3. `lookup + depends_on`: 查找表转换（如 GHYTMC ← lookup(ghytbm_to_ghytmc, GHYTBM)）
4. YSDM 特殊处理：按 gdb_key 查默认值
5. Shape_ 字段：跳过（几何计算）
6. 类型默认值：float→0.0, int→0, str→""

### colors.py — 颜色定义

GB/T 21010 + GB/T 50280-98 规划颜色规范，前后端共享。

| 颜色集               | 用途         | 条目数    |
| -------------------- | ------------ | --------- |
| ZONE_TYPE_COLORS     | 8 功能分区   | 8         |
| PLANNING_ZONE_COLORS | 6 规划分区   | 6         |
| PRIMARY_ZONE_COLORS  | 3 三区       | 3         |
| SPACE_CONTROL_COLORS | 4 管制区     | 4         |
| FACILITY_TYPE_COLORS | 9 设施类型   | 9         |
| SENSITIVITY_COLORS   | 4 敏感度等级 | 4+4(中英) |
| INFRA_COLORS         | 6 基础设施   | 6         |

### events.py — SSE 事件契约

Pydantic v2 模型，`alias_generator=to_camel` 自动将 Python snake_case 转为 JavaScript camelCase。

| 模型                | SSE 事件         | 前端对应              |
| ------------------- | ---------------- | --------------------- |
| GisResultEvent      | gis_result       | GisResultMessage      |
| GisLayerUpdateEvent | gis_layer_update | GisLayerUpdateMessage |
| GISLayerConfig      | layers[] 元素    | GISLayerConfig        |
| GISAnalysisData     | analysisData     | GisResultCard         |

---

## DictionaryCenter — YAML 字典中心

### 设计原则

1. **无映射概念，只有候选提案**：一对多转换不自动决定
2. **所有编码体系外化为 YAML 数据**：修改编码只改 YAML，不改 Python
3. **向后兼容**：现有 API 签名保留
4. **版本标记**：每个字典记录标准版本号

### 字典清单

| YAML 文件                | 编码体系          | 标准                  | 条目数  | 类型           |
| ------------------------ | ----------------- | --------------------- | ------- | -------------- |
| dlbm.yaml                | DLBM 三调地类     | GB/T 21010-2017       | ~30     | CodeDictionary |
| ghytbm.yaml              | GHYTBM 规划用途   | 广东省指南附录5       | ~25     | CodeDictionary |
| ghflbm.yaml              | GHFLBM 规划分类   | 广东省数据库标准      | ~15     | CodeDictionary |
| ydyhfldm.yaml            | YDYHFLDM 用地用海 | 自然资发〔2023〕234号 | ~30     | CodeDictionary |
| vne.yaml                 | V/N/E 村庄用地    | 住建部                | ~20     | CodeDictionary |
| sddlbm_to_ydyhfldm.yaml  | 三调→用地用海    | 跨体系                | ~30     | ProposalTable  |
| element_codes.yaml       | 要素代码          | DB22/T 3407           | 7前缀   | CodeDictionary |
| three_line_types.yaml    | 三线管控          | 三区三线              | 3+1层   | CodeDictionary |
| planning_zone_rules.yaml | 分区决策规则      | 双评价指南            | 3规则   | CodeDictionary |
| gdb_layers.yaml          | GDB 图层          | 广东省数据库标准      | 14层    | CodeDictionary |
| field_defaults.yaml      | 字段默认值        | 广东省标准            | ~30规则 | CodeDictionary |
| planning_targets.yaml    | 规划目标指标      | 广东省指南附表1       | 7指标   | CodeDictionary |
| land_use_structure.yaml  | 土地利用结构      | 广东省指南附表2       | ~20类   | CodeDictionary |

### CodeDictionary API

```python
center = get_center()
dlbm = center.get("dlbm")

# 单条查找
entry = dlbm.lookup("0101")  # {"code": "0101", "name": "水田", ...}

# 字典转换
dlbm_to_name = dlbm.to_dict("code", "name")  # {"0101": "水田", ...}

# 过滤集合
farmland_codes = dlbm.to_set("code", filter_tag="BASIC_FARMLAND")  # {"0101", "0102", "0103"}

# LLM 提示表
table = dlbm.to_prompt_table()  # Markdown 表格

# LandUseClass 列表
classes = dlbm.to_land_use_classes()
```

### ProposalTable API

```python
center = get_center()
table = center.get_proposal("sddlbm_to_ydyhfldm")

# 候选提案
entry = table.propose("2122")  # {"source": "2122", "candidate": "2122", "conversion_type": "一一对应"}

# 批量字典
mapping = table.to_dict()  # {"2122": ("2122", "一一对应"), ...}
```

### CandidateEngine — 跨体系候选提案

```python
engine = get_candidate_engine()
proposal = engine.propose("sddlbm", "ydyhfldm", "2122")

if proposal.needs_human_decision:
    # 返回候选列表给规划师，禁止自动选择
    return proposal.alternatives
else:
    return proposal.suggested_code
```

**置信度等级**：

- `exact`: 一一对应，可自动使用
- `conditional`: 有上下文条件，需验证
- `ambiguous`: 一对多，必须人工决策

---

## 依赖流向

```
┌─────────────────────────────────────────────────────────────┐
│  SCHEMA PACKAGE (单一真相源)                                  │
│  canonical.py, intent.py, pipeline.py, encoding_registry.py │
│  classification.py, dynamic_zoning.py, gdb.py, colors.py    │
│  output_profile.py, events.py, dicts/                       │
└─────────────────────────────────────────────────────────────┘
                              ↓ CONSUMED BY ↓
┌─────────────────────────────────────────────────────────────┐
│  DATA LAYER (fetchers, providers)                            │
│  GISDataFetcher, GISDataOrchestrator                        │
└─────────────────────────────────────────────────────────────┘
                              ↓ CONSUMED BY ↓
┌─────────────────────────────────────────────────────────────┐
│  TOOLS LAYER (parsing, generation, export, rendering)       │
│  export.py ← GDB_LAYER_REGISTRY, GDB_DTYPE_TO_PYTHON       │
└─────────────────────────────────────────────────────────────┘
                              ↓ CONSUMED BY ↓
┌─────────────────────────────────────────────────────────────┐
│  GENERATION LAYER                                            │
│  land_use_zone_generator.py ← ClassificationSchema, VNE    │
│  space_control_generator.py ← SPACE_CONTROL_COLORS          │
└─────────────────────────────────────────────────────────────┘
```

**核心原则**：Schema 包不依赖任何上层模块，所有依赖方向为 Schema → 下层。

---

## 广东省规范关键映射

### 规划分区体系

广东省指南定义的 6 规划分区 → 3 三区映射：

```
生态保护区 ──┐
             ├──→ 生态空间
生态控制区 ──┘

农田保护区 ──┐
             ├──→ 农业空间
一般农业区 ──┤
             │
林业发展区 ──┘

村庄建设区 ────→ 建设空间
```

### 行政区划代码

12位代码结构（广东省指南要求）：

```
44 14 26 108 004
│  │  │  │   └── 村级 (3位)
│  │  │  └──── 乡镇级 (3位)
│  │  └─────── 县级 (2位)
│  └────────── 地市级 (2位)
└──────────── 省级 (2位)
```

### 规划目标指标

| 代码 | 指标名               | 属性   | 字段                        |
| ---- | -------------------- | ------ | --------------------------- |
| I01  | 耕地保有量           | 约束性 | farmland_area_ha            |
| I02  | 基本农田保护面积     | 约束性 | basic_farmland_area_ha      |
| I03  | 村庄建设用地规模     | 约束性 | construction_area_ha        |
| I04  | 公共服务设施用地规模 | 预期性 | public_service_area_ha      |
| I05  | 基础设施用地规模     | 预期性 | infrastructure_area_ha      |
| I06  | 户均宅基地           | 预期性 | homestead_per_household_sqm |
| I07  | 人均村庄建设用地     | 预期性 | construction_per_capita_sqm |

### 土地利用结构调整

三大类 × 二级地类，现状与规划对比：

| 大类     | 二级地类                                 | GHYTBM          |
| -------- | ---------------------------------------- | --------------- |
| 农业用地 | 耕地、园地、商品林、草地、其他农用地     | 1100-1510       |
| 建设用地 | 宅基地、公共服务、基础设施、经营性、交通 | 2100-2320       |
| 生态用地 | 水域、自然保留地、生态林                 | 3100-3200, 1350 |

---

## 扩展新省份

添加新省份只需：

1. 在 `dicts/` 添加省份特定的 YAML 字典（如有编码差异）
2. 在 `output_profile.py` 添加 `OutputProfile.<province>()` 类方法
3. 在 `get_output_profile()` 添加省份路由

生成核心、编码注册表、动态分区引擎无需修改。
