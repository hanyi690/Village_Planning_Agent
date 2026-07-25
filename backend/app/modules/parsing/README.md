# Parsing 模块 - 确定性 + LLM 文本提取工具层

> **定位**: 规划文本/表格/报告的结构化提取工具集，被 PARSE Agent 与 `report_store` 消费
> **依赖方向**: `parsing -> schema.contracts`；被 `agent/gis/parse` + `services/report_store` 消费
> **非独立架构层**: 属 Agent 层的工具基础设施，不持有空间数据，不依赖 Data/KG 层

---

## 一、模块定位

parsing 是"文本 -> 结构化"的**工具层**，不含 Agent 编排逻辑。它提供三类提取能力：

| 能力类 | 技术 | 文件 | LLM 依赖 |
|---|---|---|---|
| **确定性解析** | markdown 表格 / 关键词分节 / regex 约束 | `markdown_parser` / `section_classifier` / `regulation_extractor` | zero LLM |
| **LLM 结构化提取** | Instructor + Pydantic schemas | `structured_output` / `summary_generator` | LLM |
| **地名/语义辅助** | 词典匹配 / 语义枚举 | `gazetteer` / `semantics` / `metric_anchors` / `table_schema_inference` | zero LLM |

**与 PARSE Agent 的关系**：PARSE Agent（`agent/gis/parse`）在 `explore_*`/`extract_*` 节点调用 parsing 的工具完成文本提取；parsing 产出 Pydantic 中间 schemas（`ZoneOutput`/`IntentOutput` 等），由 PARSE `format_*` 节点转为 `schema/contracts/parse_contracts.py` 的最终契约（`SpatialPlanningIntent`/`SpatialOperation`/`SpatialConstraint`）。

---

## 二、在四层架构中的位置

```
┌──────────────────────────────────────────────────────────┐
│  Agent Layer (理解 + 执行)                                │
│  ┌──────────────┐  ┌──────────────┐                      │
│  │ PARSE Agent  │  │ EXECUTE Agent│                      │
│  │ (agent/gis/  │  │ (agent/gis/  │                      │
│  │  parse)      │  │  execute)    │                      │
│  └──────┬───────┘  └──────────────┘                      │
│         │ calls tools                                     │
│  ┌──────▼──────────────────────────────────────────┐     │
│  │  parsing 模块 (本模块) -- Agent 工具基础设施      │     │
│  │  确定性解析 + LLM 结构化 + 地名/语义辅助          │     │
│  └──────┬──────────────────────────────────────────┘     │
│         │ produces intermediate Pydantic schemas          │
├─────────┼────────────────────────────────────────────────┤
│         ▼                                                │
│  Schema Layer (contracts/parse_contracts)                │
│  SpatialPlanningIntent / SpatialOperation / SpatialConstraint │
└──────────────────────────────────────────────────────────┘
```

parsing 产出的 `ZoneOutput`/`FacilityOutput`/`IntentOutput` 是**中间格式**，不直接流入下游；PARSE Agent 的 `format_*` 节点将其转换为 `schema/contracts/parse_contracts.py` 的最终契约类型后，才写入 `ProjectKG` 的 Layer 3（易失层）供 EXECUTE 读取。

**对应 ANALYZE/PLAN/DELIVER 闭环**：parsing 服务于 PLAN 阶段的文本理解环节，是 PARSE Agent 的"手"（Agent 是"脑"，parsing 是"手"）。

---

## 三、模块结构

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
├── summary_generator.py         # Instructor-based 摘要生成（report_store 兼容）
├── summary_parser.py            # 摘要文本解析（report_store 兼容）
│
├── metric_anchors.py            # 确定性 metric 提取（从 GIS，zero LLM）
└── gazetteer.py                 # 地名词典（地名 -> 坐标/候选地块，对接 schema 编码体系）
```

| 文件 | 核心导出 | 职责 | 消费者 |
|---|---|---|---|
| `schemas.py` | `ZoneOutput`, `FacilityOutput`, `IntentOutput`, `_DIMENSION_SCHEMAS` | LLM 输出的 Pydantic 约束模型 | `structured_output` / PARSE `format_*` |
| `semantics.py` | `SemanticField`, `ValueSemantics` | 指标语义枚举 + 跨维度映射 | `schemas` / `metric_anchors` |
| `markdown_parser.py` | `parse_markdown_tables`, `split_by_headers`, `detect_table` | markdown 表格 -> 结构化行 | PARSE `extract_tables` |
| `section_classifier.py` | `classify_section`, `SECTION_KEYWORDS` | 文档分节（项目/目标/规制/表格） | PARSE `classify_sections` |
| `regulation_extractor.py` | `extract_regulations_regex`, `REGULATION_PATTERNS` | regex 提取管制规则（70% 覆盖） | PARSE `extract_regulations` |
| `table_schema_inference.py` | 表格列 schema 推断 | 指标/分区/设施表列结构识别 | PARSE `extract_tables` |
| `structured_output.py` | Instructor 提取入口 | LLM -> Pydantic schema（max_retries=3） | PARSE `explore_*` |
| `metric_anchors.py` | 确定性 metric 提取 | 从 GIS 数据提取指标锚点（zero LLM） | PARSE / `report_store` |
| `gazetteer.py` | 地名 -> 坐标/候选地块 | 地名查询，对接 `schema` 编码体系 | PARSE `resolve_place` |
| `summary_generator.py` / `summary_parser.py` | 摘要生成/解析 | L3 报告摘要（`report_store` 兼容） | `services/report_store` |

---

## 四、与 schema 设计对接

### 4.1 中间 schema vs 最终契约（分离原则）

parsing 的 `schemas.py` 产出**中间 Pydantic 模型**（`ZoneOutput`/`FacilityOutput`/`IntentOutput`），这些**不是** `schema/contracts/parse_contracts.py` 的最终契约。转换链：

```
parsing.schemas.ZoneOutput  --PARSE format_targets-->  parse_contracts.ZoneTarget
parsing.schemas.FacilityOutput  --PARSE format_targets-->  parse_contracts.FacilityTarget
parsing.schemas.IntentOutput  --PARSE format_targets-->  parse_contracts.SpatialPlanningIntent
```

**为什么分离**：parsing schemas 面向 LLM 提取（字段名/枚举/约束便于 LLM 理解），parse_contracts 面向下游消费（含 `SpatialAnchor` 双阶段定位、`adjacency_rules` 等 EXECUTE 需要的字段）。两者职责不同，不强行统一。

### 4.2 与 schema 编码体系对齐

- `gazetteer.py` 的地名查询对接 `schema.encodings` 的 6 套编码（gbt21010/tugui/appendix5/ghflbm/ydyhfldm/vne），地名 -> 候选地块时用编码体系校验
- `regulation_extractor.py` 提取的管制规则，其"允许用途/禁止用途"字段对齐 `schema/contracts/parse_contracts.SpatialConstraint` 与 `schema/types/table_types.ControlRuleTable`（v4.3 S11 补二元组）

### 4.3 与 TableDataset（v4.3）对接

parsing 的 `table_schema_inference.py` + `markdown_parser.py` 提取的表格（指标表/分区表/设施表），经 PARSE `extract_tables` 节点产出后，最终流入 `schema/types/table_types.py` 的类型化表格（`PlanningIndicatorTable`/`LandUseStructureTable`/`FacilityInventory`），存入 `ProjectDataView.tables`。

---

## 五、设计原则

1. **确定性优先**：能 regex/markdown 解析的不用 LLM（`regulation_extractor` 70% 覆盖、`markdown_parser` 零 LLM）
2. **LLM 兜底**：复杂语义用 Instructor 结构化（`structured_output` max_retries=3）
3. **中间 schema 与最终契约分离**：parsing schemas 面向 LLM 提取，parse_contracts 面向下游消费
4. **零空间数据依赖**：parsing 不持有 GeoJSON/几何，`metric_anchors` 从 GIS 提取但只产出数值锚点
5. **工具无状态**：所有函数纯输入纯输出，状态由 PARSE Agent state 管理

---

## 六、与上下游模块关系

| 方向 | 模块 | 关系 |
|---|---|---|
| 上游 | `data/documents` | 提供 `PlanningText`/`L3Report`（`Document` 子类，v4.1）作为 parsing 输入文本 |
| 下游 | `agent/gis/parse` | PARSE Agent 调用 parsing 工具，产出经 format_* 转 parse_contracts |
| 下游 | `schema/contracts/parse_contracts` | 接收 parsing 中间 schema 转换后的最终契约 |
| 旁路 | `services/report_store` | `summary_generator`/`summary_parser` 为 report_store 提供摘要兼容 |
| KG | `modules/kg` | parsing 不直接写 KG；PARSE 将转换后的契约写入 `ProjectKG` Layer 3 |

---

## 七、相关文档

- `docs/gis/00_SYSTEM_DESIGN.md` §四 - PARSE 理解层（parsing 作为 PARSE 的工具基础）
- `backend/app/agent/gis/parse/README.md` - PARSE Agent（parsing 的主要消费者）
- `backend/app/modules/schema/contracts/parse_contracts.py` - 最终契约类型
- `backend/app/modules/schema/types/table_types.py` - TableDataset（v4.3 表格对接）
- `docs/gis/diagnostics/01_PARSE_AGENT_STATUS.md` - PARSE Agent 状态诊断
