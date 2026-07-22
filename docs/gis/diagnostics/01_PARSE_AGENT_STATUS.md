# PARSE Agent：当前状态与问题诊断

> **Status: [DIAGNOSTIC]** | **Type: Implementation Status Report** | **Version: v11** | **Updated: 2026-07-22**
> **Scope**: PARSE Agent当前状态 — draft质量已修复(v11)，编码校验待微调
> **References**: BIBLIOGRAPHY.md §F6-7
> **Related**: 01_DESIGN_GOALS.md §3.2, design-log/01_DECISION_LOG.md §Decision-002, proposals/01_PARSE_SPATIAL_ENHANCEMENT.md

## 1. PARSE Agent 在 Trinity 架构中的位置

```
Layer 1: PLANNING KG（RDF 知识图谱）
        规划报告文本 + GIS 地块属性 → RDF 三元组
        18 SPARQL 模板 → LLM 动态查询空间关系/约束/设施分布
              ↓
Layer 2: AGENTIC PIPELINE
         PARSE Agent: classify → route → explore → format → validate
         LAYOUT Pipeline: build_kg → conflicts → execute → validate → export
              ↓
Layer 3: SPATIAL GENERATOR（MIP + CA 程序化几何生成）
```

PARSE Agent 是 Layer 2 的入口：**规划文本 → 结构化空间操作 + 约束 + 规划意图**。

## 2. 数据流水线（当前实现）

```
GeoJSON files (5 个)
  ├─ landuse.geojson (660 parcels)       → CurrentLandUseParcel (Schema typing)
  ├─ road.geojson (131 roads)            → CurrentRoad (Schema typing)
  ├─ annotation.geojson (34 points)       → CurrentAnnotation (Schema typing)
  ├─ boundary.geojson (1 boundary)       → AdminArea (Schema typing)
  └─ admin_boundary_line.geojson (561 lines) → (未使用)
       ↓
compute_spatial_context(gis_data)
  → SpatialContext:
    - landuse_distribution (16 DLBM types × zone_type)
    - natural_villages (15 VillageGroup anchors)
    - spatial_relations (225 parcel-level relations)
    - zone_adjacency (7 zones)
    - constraint_summary (0 — protection zone data is empty)
       ↓
PlanningKG.build_from_reports(reports={}, landuse=x, gis=x)
  → 10,149 RDF triples:
    - 660 Parcel entities + DLBM/zone_type/area
    - ~5,000 adjacency edges (spatial join within 10m)
    - 4 Constraint entities (from GIS metrics)
    - 7 Zone entities + restrictions
    - 34 Facility entities (from annotation → CurrentAnnotation → Facility)
    - 4 Village entities (from annotation 村名)
    - 131 Road entities (from road → CurrentRoad → Road)
       ↓
PARSE Agent tools:
  - lookup_code(name)        → DictionaryCenter YAML (GHYTBM + zone_type + VNE)
  - resolve_place(name)      → Gazetteer (天地图 geocode + Haversine ≤5km)
  - query_village_kg(name)   → KG SPARQL (count_by_zone_type, etc.)
```

## 3. PARSE Agent Graph 拓扑（v10）

```
START → classify_sections → route_by_section (conditional fan-out)
         ↓
  [explore_projects → format_projects]
  [explore_targets → format_targets]
  [extract_regulations]
  [extract_tables]
         ↓
  validate_and_merge → should_retry? → END or retry
```

**8 个节点，4 个 LLM 调用路径**：

| 节点 | Phase | thinking | json_schema | tools | 产出 |
|------|-------|----------|-------------|-------|------|
| classify_sections | — | ON(1000) | ON | OFF | section_map (10 sections) |
| explore_projects | A | ON(2000) | OFF | ON(3 tools) | draft_operations + code_mappings |
| format_projects | B | OFF | ON | OFF | raw_operations (List[SpatialOperation]) |
| explore_targets | A | ON(2000) | OFF | ON(3 tools) | draft_targets + code_mappings |
| format_targets | B | OFF | ON | OFF | raw_targets (SpatialPlanningIntent) |
| extract_regulations | — | ON(1000) | ON | OFF | raw_constraints |
| extract_tables | — | — | — | — | raw_tables (确定性，0 LLM) |
| validate_and_merge | — | OFF | ON | OFF | 最终输出 |

## 4. v10 Pipeline 实测结果（金田村，2026-07-22）

```
[GIS] Parsed 34 annotations (typed)
[GIS] Parsed 131 roads (typed)
[KG] Built: 10149 triples + annotations/roads
[Gazetteer] Initialized with 15 villages

classify_sections: 10 sections (4s)
extract_tables: 101 rows (0s, 0 LLM)

explore_projects: single-batch (~4500 chars)
  round 1: comprehensive tool calls
  round 2: refinement calls
  → draft = 2185 chars (+16x vs v10), 30+ codes 🎉

explore_targets: single-batch (~4500 chars)
  round 1: comprehensive tool calls
  round 2: refinement calls
  → draft = 2605 chars (+24x vs v10), 8 codes 🎉

format_projects: OK json_schema → 30 operations 🎉
format_targets: OK json_schema → 8 zones + facilities + axes

validate_and_merge: OK json_schema → is_valid=False, 37 errors (编码校验格式问题，非逻辑错误)

总耗时: 显著改善 (single-batch 消除碎片 + draft质量飞跃)
```

### ✅ 已解决

- **"length limit" 完全消除**：format_projects + format_targets 的 S1 json_schema 均通过
- **KG 构建成功**：10,149 triples（vs v8 的 "KG Build skipped"）
- **Schema 层隔离**：annotation.geojson → CurrentAnnotation → KG Facility/Village 实体
- **详细日志**：section 级进度 + draft preview + codes/places 计数
- **🆕 draft 质量飞跃 (v11)**：explore_projects 138→2185 chars (+16x), explore_targets 109→2605 chars (+24x)
- **🆕 operations 数量突破 (v11)**：format_projects 2→30 operations 🎉

### ⚠️ 待微调

- **编码校验格式问题**：37 errors 主要来自 GHYTBM 格式不匹配（如 "GHYTBM=2200" vs "2200"），`lookup_code` 返回格式与 `validate` 字典 key 格式不同步，需在 format prompt 中加格式约束
- **area_ratio 语义**：zone_targets area_ratio 总和 100% 但为现状面积分解，不是规划目标值

## 5. 根因诊断：thinking 模式 + ReAct 循环 → draft 碎片

### 5.1 DashScope thinking 模式的 token 消耗机制

```
_get_llm(enable_thinking=True, thinking_budget=2000, max_tokens=8192)
```

- `max_tokens=8192` = thinking tokens + output tokens 的总上限
- `thinking_budget=2000` = 软上限（模型可能消耗更多）
- 当 LLM 输出 tool_calls 时，`response.content` 可能是 `""` 或 reasoning 碎片
- 2 轮 ReAct 后，thinking tokens 已消耗 3000-5000，只剩 3000-5000 给 output

### 5.2 v10 per-section batching 的碎片效应

v10 将 4 个 section 逐个处理：
- section 1: traffic_planning (541 chars) → LLM 调工具 → draft = 0 chars（只有 tool_calls）
- section 2: public_service (526 chars) → LLM 调工具 → draft = 80 chars（碎片）
- section 3: infrastructure_planning (1018 chars) → ...
- section 4: disaster_prevention (954 chars) → ...

每个 section 太小，LLM 没有"大局观"去写摘要，只产生碎片。

### 5.3 v9 / v10 / v11 三代对比

| 指标 | v9 (全量+thinking+json) | v10 (per-section) | v11 (单批次+Think-Then-Format) |
|------|------------------------|-------------------|-------------------------------|
| sections_text 长度 | 8000 chars (全部) | 500-1700 chars (单 section) | ~4500 chars (合并) |
| draft_operations | 5724 chars | 138 chars | 2185 chars (+16x) 🎉 |
| draft_targets | 4153 chars | 109 chars | 2605 chars (+24x) 🎉 |
| format_projects | 0 ops (S1 fail) | 2 ops (S1 OK) | 30 ops 🎉 |
| format_targets | 7 zones (S1 fail) | 9 zones (S1 OK) | 8 zones (S1 OK) |
| "length limit" 错误 | ❌ 有 | ✅ 0 | ✅ 0 |
| 总耗时 | 582s | 296s | 显著改善 |

**结论**: v11 综合了 v9 的全量视野 + v10 的 Think-Then-Format 稳定性，实现了 draft 质量和操作数量的飞跃。

## 6. v11 成果（✅ 已实现）

### 6.1 核心修复：恢复单批次处理

```python
# 替换 per-section 循环 — 合并所有 section 的 text
sections_text = "\n\n---\n\n".join(
    s.content[:1500] for s in sections[:5]
)  # 总计 ~4500 chars — 全貌但不超限
```

### 6.2 ReAct 后显式注入 "写摘要" 指令

```python
# After ReAct loop — force LLM to produce summary
messages.append(HumanMessage(content=(
    "STOP. Do NOT call more tools.\n"
    "基于以上所有工具查询结果，写出完整的项目清单。每个项目一行。\n"
    "格式: [action] name | code=GHYTBM | area=Xsqm | location=... | source=\"...\"\n"
    "使用工具返回的编码，不要自己编造。"
)))
summary_response = await llm.ainvoke(messages)
draft = summary_response.content  # NOT a tool_call — will have content
```

### 6.3 降低 thinking_budget

```python
thinking_budget = 800  # (was 2000) — extraction doesn't need deep reasoning
```

## 7. 架构限制（长期）

### 7.1 空间锚定断裂（diagnostics/02_RELIABILITY_ASSESSMENT.md §三）

parse 产出的操作引用自然语言地名（园寨/社前/田坑），GIS 数据只有 VillageGroup_1-15。即使 parse 成功，LAYOUT 也不知道 "园寨" 在哪里。

**已部分解决**：Gazetteer (天地图 + Haversine) 可以将 "园寨" → VillageGroup 匹配。**未联动**：Gazetteer 结果未自动注入到 SpatialAnchor.candidate_parcels。

### 7.2 KG 未充分利用（diagnostics/02_RELIABILITY_ASSESSMENT.md §六）

18 个 SPARQL 模板中，explore 节点主要用 `count_by_zone_type` + `get_designated_zones`。其余 16 个（邻接、约束、设施服务范围、道路网络）在设计上应由 LAYOUT Pipeline 使用，尚未实现。

### 7.3 编码体系复杂度

6 套编码体系（GB/T 21010、土规、appendix5、ghflbm、ydyhfldm、VNE）独立定义但互相引用。`lookup_code` 当前只查 appendix5→GHYTBM 映射。规划层需要土规→appendix5 的反向映射，字典尚不完整。

## 8. 近期目标 vs 中期目标

| 周期 | 目标 | 状态 |
|------|------|------|
| 近期 (v11) | draft > 1000 chars, operations > 10 | ✅ v11 已实现 (draft 2185/2605, ops 30) |
| 近期 (v11) | format 阶段无 "length limit" | ✅ v10 已修复 |
| 近期 (v11) | KG 构建成功 + 工具返回有效数据 | ✅ v10 已修复 |
| 近期 (v11.1) | 编码校验格式统一 (GHYTBM format fix) | 🔧 待微调 |
| 中期 | SpatialAnchor 自动填充 (Gazetteer→KG→candidate_parcels) | ❌ 未实现 |
| 中期 | 编码校验 100% 确定性 Python lookup | ⚠️ 部分 (validate 有 check，format 格式不同步) |
| 长期 | EXECUTE_OPERATIONS ReAct 子图 | ❌ 未实现 |
| 长期 | DEM 分析 (坡度/坡向/建设适宜性) | ❌ 未实现 |
