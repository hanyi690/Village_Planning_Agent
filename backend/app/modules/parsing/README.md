# Parsing 模块 - 确定性 + LLM 文本提取工具层

> **定位**: 规划文本/表格/报告的结构化提取工具集，被 PARSE Agent 与 `report_store` 消费
> **依赖方向**: `parsing -> schema.contracts`；被 `agent/gis/parse` + `services/report_store` 消费
> **非独立架构层**: 属 Agent 层的工具基础设施，不持有空间数据，不依赖 Data/KG 层
> **空间计算禁令**: 本模块不做任何空间计算（BBox / 距离 / 面积 / 过滤），所有空间计算由 `spatial_ops/` 完成

---

## 一、模块定位

parsing 是"文本 -> 结构化"的**工具层**，不含 Agent 编排逻辑。它提供三类提取能力：

| 能力类 | 技术 | 文件 | LLM 依赖 |
|---|---|---|---|
| **确定性解析** | markdown 表格 / 关键词分节 / regex 约束 | `markdown_parser` / `section_classifier` / `regulation_extractor` | zero LLM |
| **LLM 结构化提取** | Instructor + Pydantic schemas | `structured_output` / `summary_generator` | LLM |
| **地名/语义辅助** | 词典匹配 / 语义枚举 | `gazetteer` / `semantics` / `metric_anchors` / `table_schema_inference` | zero LLM |

**与 PARSE Agent 的关系**：PARSE Agent（`agent/gis/parse`）在 `explore_*`/`extract_*` 节点调用 parsing 的工具完成文本提取；parsing 产出 Pydantic 中间 schemas（`ZoneOutput`/`IntentOutput` 等），由 PARSE `format_*` 节点转为 `schema/contracts/parse_contracts.py` 的最终契约（`SpatialPlanningIntent`/`SpatialOperation`/`SpatialConstraint`）。

**与 spatial_ops 的边界**：parsing 负责"文本 -> 结构化"，spatial_ops 负责"结构化 -> 空间锚定"。parsing 不做任何几何运算、BBox 计算、地块过滤--这些全部由 `spatial_ops.grounding` 完成。

---

## 二、完整数据流（KG 返回语义上下文后）

```
用户输入规划文本
    │
    ▼
┌──────────────────────────────────────────────────────────────────────┐
│ parsing 模块（文本提取）                                              │
│  markdown_parser     → 分节 + 表格数据                                │
│  section_classifier  → 文档分类                                       │
│  regulation_extractor → 约束规则                                      │
│  table_schema_inference → 结构化表格                                  │
│  gazetteer           → 地名 -> 编码                                   │
└──────────────────────┬───────────────────────────────────────────────┘
                       │ 中间 schemas
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PARSE Agent explore_* 阶段                                            │
│                                                                      │
│  LLM 有两个信息来源：                                                  │
│  1. parsing 工具产出的文本中间格式（"15%商业用地"）                    │
│  2. KG 查询返回的语义上下文（"刘村北侧有8个宅基地地块，靠近乡道"）     │
│                                                                      │
│  LLM 将两者融合：                                                      │
│  "村北新增15%商业用地" + "刘村北侧有3个宅基地地块，靠近乡道"            │
│  → 决定选择 P001/P002/P003 作为候选                                   │
│                                                                      │
│  产出：自然语言草稿 + code_mappings + place_mappings                  │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PARSE Agent format_* 阶段                                             │
│                                                                      │
│  LLM 将草稿格式化为 Pydantic：                                        │
│  ZoneTarget(land_use="商业", area_ratio=0.15,                        │
│             spatial_hint="村北", description="村北新增15%商业用地")   │
│                                                                      │
│  后处理（auto-fill）：                                                 │
│  _auto_fill_facility_anchor → 匹配 place_mappings 填充 candidate_bsms │
│  _auto_fill_axis_anchor    → 匹配 place_mappings 填充 start/end_anchor│
│  _auto_fill_road_anchor    → 匹配 place_mappings 填充 start/end_anchor│
│                                                                      │
│  产出：SpatialPlanningIntent（含空间锚定 + 语义锚点）                  │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ spatial_ops.grounding（精确空间计算）                                  │
│                                                                      │
│  "村北" → resolve_directional_bbox → query_parcels_in_bbox           │
│    → 填充精确的 candidate_bsms, bbox, proximity_weights              │
│                                                                      │
│  产出：空间锚定完成后的 SpatialPlanningIntent                          │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ EXECUTE                                                              │
│  layout: ZoneTarget → MIP                                            │
│  facility: FacilityTarget → FacilityPlacer                           │
│  axis: AxisTarget → AxisBuilder                                      │
│  road: RoadTarget → (待实现)                                          │
└──────────────────────────────────────────────────────────────────────┘
```

### 各层职责

| 层 | 输入 | 产出 | 示例 |
|---|---|---|---|
| **parsing** | 原始文本 | 中间 schemas（文本结构化） | `"村北新增15%商业用地"` |
| **PARSE explore\*** | 文本结构化 + KG 语义上下文 | 草稿 + 映射（语义融合） | `"选择刘村北侧 P001/P002"` |
| **PARSE format\*** | 草稿 | Pydantic 最终契约（含语义锚点） | `ZoneTarget(land_use="商业", area_ratio=0.15, spatial_hint="村北")` |
| **PARSE auto-fill** | Pydantic + place_mappings | 填充空间锚定（初版） | `candidate_bsms=["P001","P002"]` |
| **spatial_ops** | 空间锚定初版 + bundle | 精确空间锚定（终版） | `candidate_bbox=(...), proximity_weights={...}` |
| **KG** | 最终契约 | RDF 三元组存储 | `pln:ZoneTarget, pln:candidate_bsm` |

---

## 三、parsing 与 KG 语义上下文的协作

KG 返回语义上下文后，parsing 工具本身**不变**，但 PARSE 的 `explore_*` prompt 可以利用 KG 语义数据做更精确的推理。

### 当前 prompt（已有的）

```
query_village_kg('get_village_anchors') → 刘村: (116.052, 24.835)
query_village_kg('get_parcels_near_point', ...) → 候选地块列表
query_village_kg('get_protected_parcels_detail') → 保护地块
```

### KG 返回语义后（假设）

```
query_village_kg('get_village_anchors') → 刘村: (116.052, 24.835), 下刘村: (116.058, 24.845)
query_village_kg('get_parcels_near_point', ...) →
  P001: 宅基地(2121) 0.15ha, 位于刘村北侧200m, 靠近乡道Y123
  P002: 耕地(0110) 1.2ha, 位于刘村北侧350m, 在永久基本农田范围内
  P003: 宅基地(2121) 0.12ha, 位于刘村北侧180m, 紧邻村道
```

LLM 可以据此做推理：
- P002 在基本农田范围内 → 排除
- P001 和 P003 是宅基地，靠近路 → 可以选择
- P001 靠近乡道 → 优先考虑（交通便利）

### parsing 工具与 KG 语义的分工

| 信息来源 | 提供的知识 | 示例 |
|---|---|---|
| parsing 工具 | 文本中的"是什么" | "15%商业用地"、"村北"、"新建卫生室" |
| KG 语义 | 空间中的"在哪里" | "刘村北侧200m"、"靠近乡道"、"基本农田范围内" |
| spatial_ops | 精确的"怎么算" | BBox 计算、距离计算、地块过滤 |

**parsing 提取"是什么"，KG 提供"在哪里"，spatial_ops 计算"怎么算"。** 三者缺一不可。

---

## 四、各子任务的提取-语义-计算链路

| 子任务 | parsing 提取（文本） | KG 语义（空间上下文） | spatial_ops 计算（精确） |
|---|---|---|---|
| **layout** | `land_use="商业"`, `area_ratio=0.15` | 各村用地分布、约束边界 | BBox 候选、排除保护区、MIP 目标 |
| **facility** | `type="卫生室"`, `direction="north"` | 现有设施位置、服务半径 | 最近邻匹配、覆盖范围计算 |
| **axis** | `axis_type="primary"`, `direction="north-south"` | 自然村中心点、道路网络 | 轴线生成、缓冲区计算 |
| **road** | `road_level="主干道"`, `width_m=12`, `connects=["村北","村南"]` | 现有道路、地形 | 最短路径、连通性分析 |
| **ops** | `action="create"`, `land_use_code="2121"` | 保护地块、三区三线 | 合规检查、面积计算 |

---

## 五、模块结构

```
backend/app/modules/parsing/
├── __init__.py                  # 公开 API（确定性解析器）
├── schemas.py                   # Pydantic 输出 schemas: ZoneOutput/FacilityOutput/IntentOutput + 28 维度 schemas
├── semantics.py                 # ValueSemantics 枚举 + 跨维度 metric 映射
│
├── markdown_parser.py           # 确定性 markdown 表格解析（split_by_headers/detect_table/parse_markdown_tables）
├── section_classifier.py        # 关键词分节分类（classify_section + SECTION_KEYWORDS）
├── regulation_extractor.py      # Regex 约束/管制规则提取（extract_regulations_regex + REGULATION_PATTERNS）
├── table_schema_inference.py    # 表格 schema 推断（指标/分区/设施表列结构识别）
│
├── structured_output.py         # Instructor-based LLM 结构化提取（max_retries=3）
├── summary_generator.py         # ⚠️ [DEPRECATED] Instructor-based 摘要生成（report_store 兼容）
├── summary_parser.py            # ⚠️ [DEPRECATED] 摘要文本解析（report_store 兼容）
│
├── metric_anchors.py            # ⚠️ [DEPRECATED] 确定性 metric 提取（仅 summary_generator 使用）
└── gazetteer.py                 # 地名词典（地名 -> 坐标/候选地块，对接 schema 编码体系）
```

| 文件 | 核心导出 | 职责 | 消费者 | 状态 |
|---|---|---|---|---|
| `schemas.py` | `ZoneOutput`, `FacilityOutput`, `IntentOutput`, `_DIMENSION_SCHEMAS` | LLM 输出的 Pydantic 约束模型 | `structured_output` / PARSE `format_*` | ✅ 活跃 |
| `semantics.py` | `SemanticField`, `ValueSemantics` | 指标语义枚举 + 跨维度映射 | `schemas` / `_conflict/detector` / `_conflict/resolver` | ✅ 活跃 |
| `markdown_parser.py` | `parse_markdown_tables`, `split_by_headers`, `detect_table` | markdown 表格 -> 结构化行 | PARSE `extract_tables` | ✅ 活跃 |
| `section_classifier.py` | `classify_section`, `SECTION_KEYWORDS` | 文档分节（项目/目标/规制/表格） | PARSE `classify_sections` | ✅ 活跃 |
| `regulation_extractor.py` | `extract_regulations_regex`, `REGULATION_PATTERNS` | regex 提取管制规则（70% 覆盖） | PARSE `extract_regulations` | ✅ 活跃 |
| `table_schema_inference.py` | 表格列 schema 推断 | 指标/分区/设施表列结构识别 | PARSE `extract_tables` | ✅ 活跃 |
| `structured_output.py` | Instructor 提取入口 | LLM -> Pydantic schema（max_retries=3） | PARSE `explore_*` | ✅ 活跃 |
| `gazetteer.py` | 地名 -> 坐标/候选地块 | 地名查询，对接 `schema` 编码体系 | PARSE `resolve_place` / `tools/gis/parse.py` | ✅ 活跃 |
| `summary_generator.py` | 摘要生成 | L3 报告摘要 | `services/report_store` | ⚠️ 废弃 |
| `summary_parser.py` | 摘要解析 | 摘要文本解析 | `services/report_store` | ⚠️ 废弃 |
| `metric_anchors.py` | 确定性 metric 提取 | 从 GIS 数据提取指标锚点 | `summary_generator` | ⚠️ 废弃（传递性） |

---

## 六、废弃工具

以下工具仅被 `report_store`（规划文本组装模块，正在淘汰）使用，标记为废弃：

| 文件 | 废弃原因 | 替代方案 |
|---|---|---|
| `summary_generator.py` | 仅 `report_store` 使用，规划文本组装模块淘汰 | PARSE Agent 直接产出 `SpatialPlanningIntent` |
| `summary_parser.py` | 仅 `report_store` 使用 | PARSE Agent 直接消费规划文本 |
| `metric_anchors.py` | 仅 `summary_generator` 使用（传递性废弃） | `spatial_ops.context` 的 ContextBlock 已包含 metric 信息 |
| `schemas.py` 中部分维度 schema | 仅 `summary_generator` 使用 | `parse_contracts.py` 的最终契约类型 |

**废弃策略**：不直接删除（`report_store` 仍被 session/checkpoint/analysis 等模块引用），添加 `DeprecationWarning` + 文档标记，待 `report_store` 完全淘汰后统一清理。

---

## 七、与 schema 设计对接

### 7.1 中间 schema vs 最终契约（分离原则）

parsing 的 `schemas.py` 产出**中间 Pydantic 模型**（`ZoneOutput`/`FacilityOutput`/`IntentOutput`），这些**不是** `schema/contracts/parse_contracts.py` 的最终契约。转换链：

```
parsing.schemas.ZoneOutput  --PARSE format_targets-->  parse_contracts.ZoneTarget
parsing.schemas.FacilityOutput  --PARSE format_targets-->  parse_contracts.FacilityTarget
parsing.schemas.IntentOutput  --PARSE format_targets-->  parse_contracts.SpatialPlanningIntent
```

**为什么分离**：parsing schemas 面向 LLM 提取（字段名/枚举/约束便于 LLM 理解），parse_contracts 面向下游消费（含 `SpatialAnchor` 双阶段定位、`adjacency_rules` 等 EXECUTE 需要的字段）。两者职责不同，不强行统一。

### 7.2 与 schema 编码体系对齐

- `gazetteer.py` 的地名查询对接 `schema.encodings` 的 6 套编码（gbt21010/tugui/appendix5/ghflbm/ydyhfldm/vne），地名 -> 候选地块时用编码体系校验
- `regulation_extractor.py` 提取的管制规则，其"允许用途/禁止用途"字段对齐 `schema/contracts/parse_contracts.SpatialConstraint` 与 `schema/types/table_types.ControlRuleTable`（v4.3 S11 补二元组）

### 7.3 与 TableDataset（v4.3）对接

parsing 的 `table_schema_inference.py` + `markdown_parser.py` 提取的表格（指标表/分区表/设施表），经 PARSE `extract_tables` 节点产出后，最终流入 `schema/types/table_types.py` 的类型化表格（`PlanningIndicatorTable`/`LandUseStructureTable`/`FacilityInventory`），存入 `ProjectDataView.tables`。

---

## 八、设计原则

1. **确定性优先**：能 regex/markdown 解析的不用 LLM（`regulation_extractor` 70% 覆盖、`markdown_parser` 零 LLM）
2. **LLM 兜底**：复杂语义用 Instructor 结构化（`structured_output` max_retries=3）
3. **中间 schema 与最终契约分离**：parsing schemas 面向 LLM 提取，parse_contracts 面向下游消费
4. **零空间数据依赖**：parsing 不持有 GeoJSON/几何，`metric_anchors` 从 GIS 提取但只产出数值锚点
5. **零空间计算**：parsing 不做 BBox/距离/面积/过滤等几何运算，所有空间计算由 `spatial_ops/` 完成
6. **工具无状态**：所有函数纯输入纯输出，状态由 PARSE Agent state 管理
7. **parsing 提取"是什么"，KG 提供"在哪里"，spatial_ops 计算"怎么算"**：三者分工明确，不跨界

---

## 九、与上下游模块关系

| 方向 | 模块 | 关系 |
|---|---|---|
| 上游 | `data/documents` | 提供 `PlanningText`/`L3Report`（`Document` 子类）作为 parsing 输入文本 |
| 下游 | `agent/gis/parse` | PARSE Agent 调用 parsing 工具，产出经 format_* 转 parse_contracts |
| 下游 | `schema/contracts/parse_contracts` | 接收 parsing 中间 schema 转换后的最终契约 |
| 旁路 | `services/report_store` | `summary_generator`/`summary_parser` 为 report_store 提供摘要兼容（⚠️ 废弃） |
| 旁路 | `tools/gis/_conflict` | `semantics.py` 的 `ValueSemantics`/`MetricConcept` 被冲突检测器消费 |
| 语义 | `modules/kg` | parsing 不直接写 KG；PARSE 在 `explore_*` 阶段查询 KG 获取语义上下文，在 `format_*` 后写入 KG L3 |
| 空间计算 | `modules/spatial_ops` | parsing 不做空间计算；PARSE 调用 `spatial_ops.grounding` 做精确空间锚定 |

---

## 十、相关文档

- `docs/gis/00_SYSTEM_DESIGN.md` §四 - PARSE 理解层（parsing 作为 PARSE 的工具基础）
- `backend/app/agent/gis/parse/README.md` - PARSE Agent（parsing 的主要消费者）
- `backend/app/modules/spatial_ops/README.md` - 空间计算唯一层（grounding 实现）
- `backend/app/modules/schema/contracts/parse_contracts.py` - 最终契约类型
- `backend/app/modules/schema/types/table_types.py` - TableDataset（v4.3 表格对接）
- `docs/gis/diagnostics/01_PARSE_AGENT_STATUS.md` - PARSE Agent 状态诊断