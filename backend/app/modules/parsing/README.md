# Parsing 模块 — 确定性 + LLM 文本提取工具层

> **定位**: 规划文本/表格/报告的结构化提取工具集，被 PARSE Agent 与 `report_store` 消费
> **依赖**: `parsing → schema.contracts`；被 `agent/gis/parse` + `services/report_store` 消费
> **非独立架构层**: 属 Agent 层的工具基础设施，不持有空间数据，不依赖 Data/KG 层
> **Updated: 2026-07-26**

***

## 一、模块定位

parsing 是"文本 -> 结构化"的**工具层**，不含 Agent 编排逻辑。它提供三类提取能力：

| 能力类 | 技术 | 文件 | LLM 依赖 |
|-------|------|------|---------|
| **确定性解析** | markdown 表格 / 关键词分节 / regex 约束 | `markdown_parser` / `section_classifier` / `regulation_extractor` | zero LLM |
| **LLM 结构化提取** | Instructor + Pydantic schemas | `structured_output` | LLM |
| **地名/语义辅助** | 词典匹配 / 语义枚举 | `gazetteer` / `semantics` / `table_schema_inference` | zero LLM |

**与 PARSE Agent 的关系**：PARSE Agent（`agent/gis/parse`）在 `explore_*` 节点调用 parsing 的工具完成文本提取，在 `format_*` 节点转为 `schema/contracts/parse_contracts.py` 的最终契约（`SpatialPlanningIntent` / `SpatialOperation` / `SpatialConstraint`）。

**空间计算禁令**: 本模块不做任何空间计算（BBox / 距离 / 面积 / 过滤），所有空间计算由 `spatial_ops/` 完成。

***

## 二、完整数据流（LLM + KG 协同粗定位 → spatial_ops 精确计算 → KG L3 存储）

```
用户输入规划文本
    │
    ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ parsing 模块（文本提取）                                                        │
│  markdown_parser     → 分节 + 表格数据                                          │
│  section_classifier  → 文档分类                                                 │
│  regulation_extractor → 约束规则                                                │
│  table_schema_inference → 指标/分区/设施表                                      │
│  gazetteer           → 地名 -> 编码                                             │
└───────────────────────┬───────────────────────────────────────────────────────┘
                        │ 中间 schemas（ZoneOutput / FacilityOutput 等）
                        ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ PARSE Agent: explore_* 阶段 (LLM + 工具调用 + KG 语义查询)                       │
│                                                                                │
│  LLM 有三个信息来源：                                                             │
│  1. parsing 工具产出的文本中间格式（"15%商业用地，位于村北"）                      │
│  2. KG 查询：query_village_kg(template, params) → 地块/设施/道路的详细实体数据    │
│     ┌─ get_village_parcels → BSM/DLBM/面积/分区/坐标                             │
│     ├─ get_parcel_neighbors → 邻接关系（触碰/靠近/路网连通）                      │
│     ├─ get_facility_locations → 现有设施坐标+类型                                │
│     ├─ get_road_network → 现有路网                                               │
│     ├─ get_village_anchors → 自然村锚点坐标                                      │
│     ├─ count_by_zone_type → 三区分布                                            │
│     └─ get_designated_zones → 分区对照                                           │
│  3. resolve_place 工具 → 地名 -> {center, parcel_ids, confidence}               │
│                                                                                │
│  LLM 将三者融合做**语义粗定位**：                                                  │
│  "村北新增15%商业用地" + KG返回的"刘村北侧有P001(宅基地0.15ha)、P002(耕地1.2ha)"    │
│  → LLM 推理: "P001是宅基地，靠近乡道，面积0.15ha，适合转为商业用地"                │
│  → 输出: 自然语言草稿，包含具体的 BSM 决策                                        │
│                                                                                │
│  同时，LLM 产出 code_mappings + place_mappings（地名→坐标的映射表）              │
└───────────────────────┬───────────────────────────────────────────────────────┘
                        │ draft_targets / draft_operations
                        ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ PARSE Agent: format_* 阶段（LLM 结构化 + 确定性填充 + spatial_ops 精确计算）      │
│                                                                                │
│  Step 1: LLM 将自然语言草稿转为 Pydantic 契约                                    │
│   ZoneTarget(land_use="商业", area_ratio=0.15,                                │
│              spatial_hint="村北", candidate_bsms=["P001","P003"],              │
│              planning_zone="村庄建设区")                                        │
│                                                                                │
│  Step 2: 确定性后处理（_inject_deterministic_fields）                            │
│   → 从 code_mappings 填充 dlbm / vne_code                                       │
│                                                                                │
│  Step 3: 语义锚定匹配（_auto_fill_*_anchor）                                    │
│   → 从 place_mappings 匹配地名 → 填充 candidate_bsms / anchor_point             │
│   → ZoneTarget / FacilityTarget / AxisTarget / RoadTarget 均受益               │
│                                                                                │
│  Step 4: 空间精确计算（_ground_zone_targets）                                    │
│   → spatial_ops.grounding.ground_zone_spatial_preference(                      │
│        preference_desc="村北", LLM_selected_bsms=["P001","P003"])               │
│   → 返回 ZoneSpatialAnchor(candidate_bsms, candidate_bbox,                     │
│                             excluded_bsms, proximity_weights)                   │
│                                                                                │
│  产出：完全空间锚定的 SpatialPlanningIntent                                      │
└───────────────────────┬───────────────────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ KG Layer 3 写入（build_intent_layer）                                           │
│                                                                                │
│  将 SpatialPlanningIntent 存入 RDF 图:                                          │
│  pln:zone_target_0 rdf:type pln:ZoneTarget                                     │
│    pln:candidate_bsm  pln:parcel_P001                                          │
│    pln:candidate_bbox  "116.04,24.83,116.06,24.85"                            │
│    pln:excluded_bsm    pln:parcel_P099                                         │
│    pln:spatial_hint    "村北"                                                  │
│    pln:land_use_code   "2121"                                                 │
│                                                                                │
│  同时存入 SemanticMemoryStore（自然语言描述，供下游 LLM 查询）                     │
└───────────────────────┬───────────────────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ EXECUTE 阶段（消费 KG L3 粗定位 + spatial_ops.bridge 精确操作）                  │
│                                                                                │
│  layout:  ZoneTarget → spatial_ops.bridge(SpatialIndex) → parcel_ops → MIP    │
│  facility: FacilityTarget → spatial_ops.bridge → FacilityPlacer               │
│  axis:    AxisTarget → spatial_ops.bridge → AxisBuilder                       │
│  road:    RoadTarget → spatial_ops.bridge → road_planner                      │
│                                                                                │
│  EXECUTE 通过 SpatialIndex 查询:                                               │
│    idx.get_parcel_geometry("P001") → GeoJSON（找回精确几何）                    │
│    idx.parcels_intersecting(planned_geom) → overlap 分析                       │
│    idx.parcels_within_distance("P001", 200) → 邻近地块                          │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 各层职责

| 层 | 输入 | 产出 | 示例 |
|---|------|------|------|
| **parsing** | 原始文本 | 中间 schemas（文本结构化） | `"村北新增15%商业用地"` |
| **KG L1+L2** | VillageBundle | RDF 实体 + 空间关系三元组 | `pln:parcel_P001 pln:touches pln:parcel_P002` |
| **PARSE explore_*** | 文本结构化 + KG 语义上下文 | 草稿 + 映射（LLM 语义粗定位） | `"选择刘村北侧 P001(0.15ha) 转为商业用地"` |
| **PARSE format_*** | 草稿 | Pydantic 最终契约（含 LLM 选定的 BSM） | `ZoneTarget(candidate_bsms=["P001"])` |
| **spatial_ops** | LLM 粗定位 + bundle | 精确空间锚定（最终版） | `ZoneSpatialAnchor(bbox, excluded, weights)` |
| **KG L3** | 空间锚定后的契约 | RDF 三元组 + 语义注释 | `pln:ZoneTarget + pln:candidate_bsm` |
| **EXECUTE** | KG L3 + SpatialIndex | 规划方案 | MIP 布局 / 设施放置 / 道路生成 |

***

## 三、PARSE 与 KG 语义上下文的协作（核心设计）

### 3.1 粗定位：LLM + KG + spatial_ops 三方接力

```
文本: "村北新增15%商业用地"
    │
    ▼
parsing: 提取 land_use="商业", area_ratio=0.15, spatial_hint="村北"
    │
    ▼
PARSE explore_*: LLM 查询 KG 获取详细实体信息
    ├─ query_village_kg('get_village_parcels') → 刘村所有地块
    │  P001: 宅基地(2121) 0.15ha, 村北200m, 靠近乡道Y123
    │  P002: 耕地(0110) 1.2ha, 村北350m, 在永久基本农田范围内
    │  P003: 宅基地(2121) 0.12ha, 村北180m, 紧邻村道
    │  P004: 商业用地(2101) 0.08ha, 村中心
    │
    ├─ query_village_kg('get_parcel_neighbors', bsm="P001") →
    │  P001 邻接 P002(触碰), P003(触碰), 靠近道路 Y123
    │
    └─ query_village_kg('get_village_anchors') →
       刘村: (116.052, 24.835), 下刘村: (116.058, 24.845)

LLM 语义推理:
  "P002 在基本农田范围内 → 排除
   P001 和 P003 是宅基地，靠近路 → 可以选择
   P001 靠近乡道 → 优先考虑（交通便利）
   P001 面积 0.15ha 与 15% 用地比例匹配"

LLM 输出草稿:
  "目标: 将刘村北侧 P001 地块(0.15ha) 由宅基地转为商业用地"
    │
    ▼
PARSE format_*: 结构化 + 空间精确计算
  ZoneTarget(
    land_use="商业",
    area_ratio=0.15,
    candidate_bsms=["P001", "P003"],    # LLM 语义选定
    spatial_hint="村北",
  )
  → spatial_ops.grounding.ground_zone_spatial_preference(...)
  → 返回: candidate_bsms=["P001","P003"], bbox=(...), excluded_bsms=["P099"]
    │
    ▼
KG L3: build_intent_layer → 存储最终空间锚定
    │
    ▼
EXECUTE: 读取 KG L3 粗定位 + spatial_ops.bridge 精确几何操作
```

### 3.2 信息源分工

| 信息来源 | 提供的知识 | 对应阶段 | 示例 |
|---------|-----------|---------|------|
| parsing 工具 | 文本中的"是什么" | explore_* 前 | `"15%商业用地"`、"村北"、"新建卫生室" |
| KG L1（查询） | 地块的"在哪里、是什么" | explore_* 中 | `"P001: 宅基地0.15ha, 村北200m"` |
| KG L2（查询） | 空间关系"与什么相邻" | explore_* 中 | `"P001 靠近乡道 Y123"` |
| LLM 推理 | "选哪个"（语义粗定位） | explore_* → format_* | `"选 P001 转为商业"` |
| spatial_ops | "精确定位"（精确几何） | format_* 后 | `bbox=(...), weights={...}` |
| KG L3（存储） | 最终决策的持久化 | format_* → EXECUTE | `pln:candidate_bsm=P001` |
| spatial_ops.bridge | "精确计算"（运行时几何） | EXECUTE 中 | `idx.parcels_intersecting(geom)` |

### 3.3 与 spatial_ops 的分工原则

| 操作 | 谁做 | 为什么 |
|------|------|--------|
| LLM 选择候选地块（BSM 级别） | PARSE LLM | LLM 理解语义：哪些地块"适合"转为商业用地 |
| BBox 计算 + 候选过滤 + 邻近度 | spatial_ops.grounding | 需要几何精度和距离计算 |
| 约束重叠排除 | spatial_ops.grounding | 需要 ConstraintIndex（R-tree） |
| 精确几何操作（intersect/within） | spatial_ops.bridge (SpatialIndex) | EXECUTE 阶段的运行时空间索引 |
| 存储粗定位结果 | KG L3 | 持久化供 EXECUTE 消费 |

**关键区别**：LLM 选定具体的 BSM（语义决策），spatial_ops 验证/精化（几何计算），KG L3 持久化（存储）。

***

## 四、各子任务的提取-语义-计算链路

| 子任务 | parsing 提取（文本） | KG 语义（精细实体信息） | LLM 粗定位 | spatial_ops 精确 | KG L3 |
|-------|-------------------|----------------------|-----------|-----------------|-------|
| **layout** | `land_use="商业"`, `area_ratio=0.15`, `spatial_hint="村北"` | 各村地块列表、地类、面积、坐标 | 选 P001/P003 作为候选 | BBox 验证、排除约束、邻近加权 | 存储 ZoneTarget + anchor |
| **facility** | `type="卫生室"`, `location_hint="村北"` | 现有设施位置、服务半径、覆盖范围 | 选位置点（坐标附近）| 最近邻匹配、覆盖范围计算 | 存储 FacilityTarget + anchor |
| **axis** | `axis_type="primary"`, `direction="north-south"` | 自然村中心点、道路网络 | 选 start/end 锚点（村口/乡道接口）| 轴线生成、缓冲区计算 | 存储 AxisTarget + anchor |
| **road** | `road_level="主干道"`, `width_m=12`, `connects=["村北","村南"]` | 现有道路、地形、水系 | 选路径走向 | 最短路径、连通性分析 | 存储 RoadTarget + anchor |
| **ops** | `action="create"`, `land_use_code="2121"` | 保护地块、三区三线约束 | 确认地块合规性 | 合规检查、面积计算 | 存储 SpatialOperation |

### 粗定位（语义）vs 精确定位（几何）的边界

```
LLM 语义粗定位（PARSE explore_*）:
  从 KG 返回的数百个地块中，LLM 根据语义选择 3-5 个候选：
  "P001 靠近乡道，是宅基地，面积 0.15ha → 适合转为商业用地"
  "P002 在基本农田范围内 → 排除"
  → 输出: candidate_bsms=["P001", "P003"]

spatial_ops 精确计算（PARSE format_* → grounding）:
  对 LLM 选择的候选做精确几何验证：
  "候选地块的哪个方向 BBox 最合理？"
  "是否与约束多边形重叠？"
  "到参考点的距离权重是多少？"
  → 输出: ZoneSpatialAnchor(candidate_bsms, bbox, excluded, weights)
```

***

## 五、模块结构

```
backend/app/modules/parsing/
├── __init__.py                  # 公开 API（确定性解析器）
├── schemas.py                   # Pydantic 输出 schemas: ZoneOutput/FacilityOutput/IntentOutput + 28 维度 schemas
├── semantics.py                 # ValueSemantics 枚举 + 跨维度 metric 映射
│
├── markdown_parser.py           # 确定性 markdown 表格解析
├── section_classifier.py        # 关键词分节分类
├── regulation_extractor.py      # Regex 约束/管制规则提取
├── table_schema_inference.py    # 表格 schema 推断
│
├── structured_output.py         # Instructor-based LLM 结构化提取
│
├── gazetteer.py                 # 地名词典（地名 -> 坐标/候选地块）
└── README.md                    # 本文档
```

| 文件 | 核心导出 | 职责 | 消费者 | 状态 |
|------|---------|------|--------|------|
| `schemas.py` | `ZoneOutput`, `FacilityOutput`, `IntentOutput`, `_DIMENSION_SCHEMAS` | 中间 Pydantic 约束模型 | `structured_output` / PARSE `format_*` | ✅ 活跃 |
| `semantics.py` | `SemanticField`, `ValueSemantics` | 指标语义枚举 + 跨维度映射 | `schemas` / `_conflict/detector` / `_conflict/resolver` | ✅ 活跃 |
| `markdown_parser.py` | `parse_markdown_tables`, `split_by_headers`, `detect_table` | markdown 表格 → 结构化行 | PARSE `extract_tables` | ✅ 活跃 |
| `section_classifier.py` | `classify_section`, `SECTION_KEYWORDS` | 文档分节 | PARSE `classify_sections` | ✅ 活跃 |
| `regulation_extractor.py` | `extract_regulations_regex`, `REGULATION_PATTERNS` | regex 提取管制规则（70% 覆盖） | PARSE `extract_regulations` | ✅ 活跃 |
| `table_schema_inference.py` | 表格列 schema 推断 | 指标/分区/设施表列结构识别 | PARSE `extract_tables` | ✅ 活跃 |
| `structured_output.py` | Instructor 提取入口 | LLM → Pydantic schema | PARSE `explore_*` | ✅ 活跃 |
| `gazetteer.py` | 地名 → 坐标/候选地块 | 地名查询 | PARSE `resolve_place` / `tools/gis/parse.py` | ✅ 活跃 |

### 已删除文件

| 文件 | 原因 | 替代 |
|------|------|------|
| `summary_generator.py` | `report_store` 淘汰 | PARSE Agent 直接产出 `SpatialPlanningIntent` |
| `summary_parser.py` | `report_store` 淘汰 | PARSE Agent 直接消费规划文本 |
| `metric_anchors.py` | 仅为废弃的 `summary_generator` 使用 | `spatial_ops.context` 的 ContextBlock |
| `structured_output.py`（旧版）| 重构为 Instructor 统一入口 | `structured_output.py`（新版）|

***

## 六、与上下游模块关系

| 方向 | 模块 | 关系 |
|------|------|------|
| 上游 | `data/documents` | 提供 `PlanningText` / `L3Report` 作为 parsing 输入文本 |
| 下游 | `agent/gis/parse` | PARSE Agent 调用 parsing 工具，融合 KG 语义做粗定位 |
| 下游 | `schema/contracts/parse_contracts` | 接收 parsing 中间 schema 转换后的最终契约 |
| 语义 | `modules/kg` | PARSE 在 `explore_*` 阶段**查询** KG L1+L2 获取详细实体数据；在 `format_*` 后**写入** KG L3 存储粗定位结果 |
| 空间计算 | `modules/spatial_ops` | PARSE 调用 `spatial_ops.grounding` 做精确空间锚定；EXECUTE 调用 `spatial_ops.bridge` 做运行时几何操作 |

### 数据流向示意

```
parsing ──→ PARSE explore_* ──→ KG L1+L2 (查询实体数据)
                │
                │ LLM 语义决策: 选具体 BSM
                ▼
          PARSE format_* ──→ spatial_ops.grounding (精确计算)
                │
                │ spatial_ops 返回 ZoneSpatialAnchor
                ▼
          PARSE post-process ──→ KG L3 (存储粗定位结果)
                │
                ▼
          EXECUTE ──→ spatial_ops.bridge (运行时几何操作)
```

***

## 七、设计原则

1. **确定性优先**：能 regex/markdown 解析的不用 LLM
2. **LLM 兜底**：复杂语义用 Instructor 结构化
3. **LLM 粗定位 + spatial_ops 精确定位**：LLM 做语义决策（选哪些 BSM），spatial_ops 做几何计算（BBox/距离/过滤/加权）
4. **KG 数据驱动 LLM 推理**：LLM 的语义粗定位基于 KG 返回的详细实体信息（不是 text hint 模糊匹配）
5. **KG L3 存储最终决策**：粗定位结果持久化供 EXECUTE 消费
6. **中间 schema 与最终契约分离**：parsing schemas 面向 LLM 提取，parse_contracts 面向下游消费
7. **零空间计算**：parsing 不做任何几何运算，所有空间计算由 `spatial_ops/` 完成
8. **零空间数据**：parsing 不持有 GeoJSON/几何
9. **工具无状态**：所有函数纯输入纯输出，状态由 PARSE Agent state 管理

***

## 八、相关文档

- `docs/gis/00_SYSTEM_DESIGN.md` — 系统总体设计（四层架构）
- `backend/app/agent/gis/parse/README.md` — PARSE Agent（parsing 的主要消费者）
- `backend/app/modules/kg/README.md` — KG 模块（L1+L2 查询源 / L3 粗定位存储）
- `backend/app/modules/spatial_ops/README.md` — 空间计算唯一层（grounding + bridge）
- `backend/app/modules/schema/contracts/parse_contracts.py` — 最终契约类型
- `backend/app/modules/kg/builder/layer3.py` — L3 粗定位写入实现
