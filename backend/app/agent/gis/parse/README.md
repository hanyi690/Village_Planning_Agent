# PARSE Agent 子包

> 规划文本 -> 空间意图。**基于规则的确定性解析器**（非 ReAct 图）：regex 提取 + 表格提取 + 【INSTRUCTION】段 + gazetteer 空间锚定，产出类型化 `SpatialPlanningIntent`。
> **Updated: 2026-08-02**

---

## 一、定位

PARSE 是 GIS Agent 的 **PLAN 阶段执行核**，与 `execute/`（DELIVER 阶段）平级。它把自然语言规划报告转化为下游可执行的 `SpatialPlanningIntent`（分区/设施/轴线/道路目标）。

> ⚠️ **架构现状**：本子包曾按 **ReAct StateGraph**（`classify_sections → explore_* → format_* → validate_and_merge`）设计并文档化。**该设计已废弃**——当前实现是合并了旧 `parse_v2` 的**单一确定性函数** `parse()`，无 StateGraph、无 explore/format 节点。LLM 增强可在未来通过 `GIS_PARSE_LLM_ENABLED` 门控接入而不改公开 API。

---

## 二、目录结构

```
parse/
├── __init__.py          # 导出 parse / parse_async / ParseResult + schema 类（SpatialPlanningIntent 等）
├── agent.py             # ★ 规则解析器（762 行）：parse() + 提取器 + 空间锚定 + KG 绑定
└── state.py             # ParseAgentState（Pydantic，向后兼容保留）+ SectionInfo 等类型
```

---

## 三、公开 API

```python
from app.agent.gis.parse import parse, parse_async, ParseResult

result = parse(planning_text, village_name="金田村委会", planning_period="2022-2035年")
# -> ParseResult
#      .intent: SpatialPlanningIntent   # zone_targets / facilities / development_axes / road_targets / raw_text
#      .operation_sequence: List[SpatialOperation]  # 恒为 []（当前不产出操作序列）
#      .constraint_set: List[SpatialConstraint]     # 恒为 []（当前不产出约束集）
#      .validation_errors: List[str]

result_async = await parse_async(...)   # asyncio.to_thread 包装
```

**`ParseAgentState`**（`state.py`）保留 ReAct 时代的字段（`section_map` / `raw_operations` / `draft_targets` / `place_mappings_*` 等）仅供向后兼容，**新解析路径不使用它**——`parse()` 是纯函数，无中间状态。类型契约（`SpatialPlanningIntent` / `ZoneTarget` / `FacilityTarget` / `AxisTarget` / `RoadTarget` / `SpatialPreference` / `SemanticMetadata`）统一来自 `app.modules.schema.contracts.parse_contracts`。

---

## 四、解析管线（实际实现）

```
parse(planning_text, ...)
  │
  ├─ 1. regex 提取（agent.py 内联模式）
  │     _ZONE_TARGET_RE    "分区:商业 30%" / "30%用于商业" → List[ZoneTarget]
  │     _FACILITY_RE       "设施/服务中心/卫生室/学校/广场/停车场/公园 …" → List[FacilityTarget]
  │     _AXIS_RE           "发展轴/景观轴/生态廊道/道路轴线 …" → List[AxisTarget]
  │     _ROAD_RE           "道路/公路/村道/乡道 …宽度:8m" → List[RoadTarget]
  │
  ├─ 2. markdown 表格提取（app.modules.parsing.tables，单位级检测）
  │     _extract_zone_tables(text)     → List[ZoneTarget]    （名称列 + 面积/比例列 + ≥60% 名称含"区"）
  │     _extract_project_tables(text)  → List[FacilityTarget]（表头含 项目/工程/设施名称）
  │
  ├─ 3. 【INSTRUCTION】段提取（P8）
  │     _extract_instruction_section: 从 _INSTRUCTION_MARKER 起取结构化段
  │     _extract_instruction_tables: 解析固定列表格（类型闭集：项目/功能分区/分区/设施/轴线/
  │         现状设施/现状项目/现状分区）→ {zones, facilities, axes}
  │     按名称去重合并（INSTRUCTION 优先，位置信息更完整）
  │
  ├─ 4. 表格残片过滤
  │     丢弃类型/位置含 "|" 的设施（regex 会把 markdown 表格行误提取为设施）
  │
  ├─ 5. 组装 SpatialPlanningIntent（raw_text 截断 2000 字符）
  │
  └─ 6. 空间锚定（可选，外部调用）
       resolve_spatial_anchors(intent, village_name)  # 见 §五
```

**方向提取**：`_direction_from_location` 用 `_DIRECTION_RULES` 元组（方位词 → direction 枚举，取首个命中），如"村东北部与西南部" → `northeast`。

**去重合并逻辑**：先 regex+表格提取，再合并 INSTRUCTION 段；已存在的名称（`zone_names` / `facility_names` / `axis_names`）不重复追加。

---

## 五、空间锚定（resolve_spatial_anchors）

```python
resolve_spatial_anchors(intent, village_name="") -> int   # 返回成功解析的实体数
```

- 加载 `app.modules.kg.gazetteer.load_gazetteer(village_name)`（`data/gazetteer/{village}.json`，只读不落盘）
- 对每个空间实体的位置文本提取 token（`_extract_location_tokens`：按 `、，,；;/ 至 和 与` 切分，去 自然村/村/组/段/沿/线/附近/周边/区域/一带 后缀）
- token → `_resolve_gazetteer_bsms`（精确 → 村后缀 → fuzzy，`Gazetteer.resolve(fuzzy=)`）
- 填充：
  - `ZoneTarget.candidate_bsms`（MIP canvas / ZoneGenerator 空间过滤）
  - `FacilityTarget.candidate_bsms`（FacilityPlacer 候选池）
  - `AxisTarget.corridor_bsms`（AxisBuilder 走廊）
- 无匹配保留原文 `spatial_hint` 供语义使用

> **旧设计对照**：`spatial_ops.grounding.ground_zone_spatial_preference` 仍存在且导出（见 `modules/spatial_ops/README.md` §六），但**当前 PARSE 路径不调用它**——空间锚定走 `kg.gazetteer`。grounding 保留为独立可用的空间接地库。

---

## 六、KG 绑定（extract_bindings — 已废弃转发器）

```python
async def extract_bindings(session_id, wave, reports, llm=None, kg=None, bundle=None) -> Dict
```

**已废弃**：多层级 KG 富化已迁至 `app.modules.kg.enrichment`，此函数仅作转发器（PARSE 保持 intent-only）。

模块内保留的内部工具（`agent.py`，供 enrichment 复用）：
- `_extract_bindings_deterministic(reports)` — 规则回退：`XX村` 提及 + 120 字符内 BSM
- `_extract_bindings_llm(llm, reports, candidate_bsms)` — Flash LLM JSON 约束提取
- `_validate_binding(binding, kg, bundle)` — **KG 写入闸门**：confidence≥0.6 + BSM 在 KG + 村内/村外规则
  - 有注记点（村名分类）：必须通过村界包含（村外毗邻行政村 → 拒绝）+ 点在候选地块内
  - 无注记点（村内自然村）：地块中心点必须在村界内
- `_extract_entity_semantics(reports)` — P4：功能分区/项目实体语义提取（纯注解，无空间绑定）
- `_queue_review(session_id, wave, skipped)` — 跳过项写入 `{memory_dir}/_review/{session_id}_wave_{wave}.json`

---

## 七、输入输出契约

```
输入:  planning_text (str) + village_name + planning_period
输出:  ParseResult
         .intent: SpatialPlanningIntent
             zone_targets:    List[ZoneTarget]       # land_use / area_ratio / spatial_preference / semantic
             facilities:      List[FacilityTarget]   # type / status / location_hint / anchor_village / semantic
             development_axes: List[AxisTarget]      # label / reference_feature / direction / semantic
             road_targets:    List[RoadTarget]       # road_level / width_m / semantic
             raw_text: str                           # 截断 2000 字符
         .operation_sequence: List[SpatialOperation]  # []（当前不产出）
         .constraint_set:     List[SpatialConstraint] # []（当前不产出）
```

下游 `layout_pipeline.py:_parse_intent_node` 消费 `intent`，注入 `GISPipelineState` 供 EXECUTE 使用。EXECUTE 经 `format_bound_intent.py` / `vocab_extractor.py` 把 `ZoneTarget/FacilityTarget/AxisTarget` 转换为各子任务的内部意图类型。

---

## 八、与 parsing 模块的分工

| 提取能力 | 实现位置 |
|---|---|
| regex 目标/设施/轴线/道路 | `agent.py` 内联（`_ZONE_TARGET_RE` 等） |
| 单元级表格提取（zone/project 表） | `app.modules.parsing.tables` |
| 【INSTRUCTION】固定列表格 | `agent.py::_extract_instruction_tables`（内部用 `parsing.tables._iter_tables`） |
| 行政区划 / 地名地理编码 | `app.modules.parsing.admin_code_loader` / `gazetteer` |

---

## 九、测试

无 `parse/` 独立测试，覆盖：
- `tests/unit/test_parse_table_extraction.py` — `parse()` 端到端表格提取（zone ratios / facility locations / dedup merge）
- `tests/unit/test_parse_instruction.py` — 【INSTRUCTION】表格解析
- `tests/unit/test_parse_agent.py` — 含 `_compute_centroid` 等内部工具
- 集成：`test_parse_agent_llm.py`（用 `jintian_planning_text` fixture 走完整管线）、`test_kg_jintian_e2e.py`

---

## 十、相关文档

- `../README.md` — GIS Agent 包总览
- `../execute/README.md` — EXECUTE Agent（下游消费者）
- `app/modules/parsing/README.md` — parsing 工具层（PARSE 调用提取工具）
- `app/modules/kg/README.md` — KG 模块（gazetteer / enrichment）
- `app/modules/schema/contracts/parse_contracts.py` — 最终契约类型
