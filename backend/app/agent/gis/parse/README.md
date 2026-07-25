# PARSE Agent 子包

> 规划文本 → 空间意图。消费 L3 报告 + SpatialContext，产出类型化 `SpatialPlanningIntent` / `SpatialOperation` / `SpatialConstraint`。

---

## 一、定位

PARSE 是 GIS Agent 的 **PLAN 阶段执行核**，与 `execute/`（DELIVER 阶段）平级。它把自然语言规划报告转化为下游可执行的空间意图，核心解决"文本 → 结构化空间目标"的语义鸿沟。

**关键特征**：
- **空间感知**：通过 `SpatialContext` 注入空间关系与锚点，不直接接触原始 GeoJSON 几何
- **Think-Then-Format**：探索阶段自由推理 + 工具调用，格式化阶段强制 Pydantic 输出
- **Schema 强制**：输出为严格 Pydantic 模型，保证 PARSE → EXECUTE 交接可靠

---

## 二、图架构（agent.py:1405）

```
START
  → classify_sections                       # 文档分节分类
      │  (route_by_section, Send fan-out)
      ├──→ explore_projects → format_projects ──→ validate_and_merge
      ├──→ explore_targets  → format_targets  ──→ validate_and_merge
      ├──→ extract_regulations ─────────────────→ validate_and_merge
      └──→ extract_tables ───────────────────────→ validate_and_merge
                                                    │  (should_retry)
                                                    ├── retry → classify_sections
                                                    └── end  → END
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
| `lookup_code` | 查询用地名称 → GHYTBM 编码（附录5规划用途编码） |
| `resolve_place` | 查询地名 → GIS 空间锚点（NaturalVillageAnchor / FacilityAnchor） |
| `query_village_kg` | 查询 KG 空间上下文（村锚点 / 设施 / 道路 / 保护地块 / 三区三线 / VNE 汇总） |

工具执行通过 `_get_current_parse_kg()`（`agent.py:139`）从 `KGManager.get_any_kg()` 获取 KG 实例。

---

## 四、状态与输出（state.py）

### ParseAgentState

内部状态，独立于 LAYOUT Pipeline：

| 字段组 | 字段 | 说明 |
|--------|------|------|
| 输入 | `planning_text`, `village_name`, `spatial_context` | 文本 + 空间上下文 |
| 分类 | `section_map`, `parse_strategy` | 分节结果 + 策略 |
| 中间 | `raw_operations`, `raw_constraints`, `raw_targets`, `raw_tables` | 类型化中间结果 |
| 校验 | `validation_errors`, `parse_round`, `is_valid` | 校验状态 |
| 输出 | `operation_sequence`, `constraint_set`, `planning_intent` | 最终产出 |
| 草稿 | `draft_operations`, `draft_targets` | Phase A 探索产出 |
| 映射 | `code_mappings_*`, `place_mappings_*` | 编码/地名映射（projects/targets 分键避免并发冲突） |

### 核心输出模型

- **`SpatialPlanningIntent`**（`state.py:367`）：分区目标 `zone_targets` + 设施 `facilities` + 轴线 `development_axes` + 面积约束 + 指标表 + 三区三线
- **`SpatialOperation`**（`state.py:116`）：原子空间操作（create/split/merge/modify/reclassify），带 `SpatialAnchor` 双阶段定位
- **`SpatialConstraint`**：空间约束规则
- **`SpatialAnchor`**（`state.py:79`）：PARSE 预解析 + LAYOUT 确认的双阶段定位

---

## 五、空间接地（Spatial Grounding）

PARSE 不直接读 GeoJSON，而是通过 `SpatialContext`（`app/modules/spatial_ops/context.py:compute_spatial_context()`）获取压缩空间上下文（~2KB）。v4.1 起 `compute_spatial_context` 收 `ProjectDataView`（多村 `VillageBundle`），产出项目级空间上下文：

- `natural_villages`：自然村锚点（聚类自居住地块 + 地名别名匹配）
- `facility_anchors`：设施精确锚点（来自 annotation.geojson）
- `spatial_relations`：村组间语义关系（east_of / adjacent_to / contains / near）
- `constraint_summary`：保护边界摘要

`SpatialAnchor` 的双阶段定位：
1. **PARSE 预解析**：`location_desc` 匹配 `SpatialContext.natural_villages` → 候选地块 + 置信度
2. **LAYOUT 确认**：`resolve_place` 工具确认或修正锚点

---

## 六、输入输出契约

```
输入: ParseAgentState(planning_text, village_name, spatial_context)
输出: {
  operation_sequence: List[SpatialOperation],   # 空间操作序列
  constraint_set:     List[SpatialConstraint],   # 空间约束集
  planning_intent:    SpatialPlanningIntent,     # 分区/设施/轴线目标
  validation_errors:  List[str],                 # 校验错误
}
```

下游 `layout_pipeline.py:_parse_intent_node` 消费这些输出，注入 `GISPipelineState` 供 EXECUTE 使用。同时 PARSE 通过 `add_intent`/`add_operations`/`add_constraints`/`add_spatial_relations` 将结果写入 `ProjectKG` Layer 3（项目级，见 `modules/kg/README.md` §六），供 EXECUTE 经 `ConstraintCompiler` 读取。

---

## 七、相关文档

- `../README.md` — GIS Agent 包总览
- `../execute/README.md` — EXECUTE Agent（下游消费者）
- `app/modules/spatial_ops/context.py` - SpatialContext 计算（收 `ProjectDataView`, v4.1）
- `app/modules/parsing/README.md` - parsing 工具层（PARSE 调用提取工具）
- `app/modules/kg/README.md` - ProjectKG 桥接层（PARSE 写入 Layer 3）
- `app/modules/schema/contracts/parse_contracts.py` - 最终契约类型
- `docs/gis/00_SYSTEM_DESIGN.md` §四 - PARSE 理解层设计
- `docs/gis/diagnostics/01_PARSE_AGENT_STATUS.md` — PARSE Agent 状态诊断
- `docs/gis/proposals/01_PARSE_SPATIAL_ENHANCEMENT.md` — 空间增强提案
