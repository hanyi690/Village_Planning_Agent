# PARSE 空间意图 + EXECUTE 布局生成

> **PARSE 消费 EXPLORE 产出，EXECUTE 多策略执行 + Evaluator Gate + L4 回写。**
> 对应 `00_SYSTEM_DESIGN` 第一部分 Agent 层展开。

---

## 1. 设计目标：PARSE -> EXECUTE 两段式

```
EXPLORE 产出 (ExplorationInstructionCollection + ReportSummaryIndex)
  │
  ▼
PARSE Agent (gis_agent 内)
  │ 消费 ExplorationInstruction + 概要索引
  │ 按维度取 L3 报告原文 (通过 ReportSummaryIndex 导航)
  │ 产出: SpatialPlanningIntent (ZoneTarget/FacilityTarget/AxisTarget/RoadTarget)
  │ 写 L3 intent 实体到 KG
  │
  ▼
EXECUTE Agent (gis_agent 内)
  │ 消费 intent + KG + VillageBundle
  │ 多策略: parcel operations (主) + MIP quota (次) + programmatic (辅)
  │ Evaluator Gate: validate -> fail? -> retry (max 3 rounds)
  │ 产出: 布局成果 (layout_configs) + L4 回写 (PlannedState)
  │
  ▼
export_gdb + render_map
```

**核心约束**：
- PARSE 不直接查 KG（EXPLORE 已前置 KG 交互），只消费 EXPLORE 的候选 BSM
- EXECUTE 是 PARSE 与 L4 之间的执行层，读 KG 约束、写 L4 PlannedState
- Evaluator Gate 保证布局质量，最多重试 3 轮
- L4 回写带 provenance（derived_from/source_spec/decided_by/operation）

---

## 2. PARSE Agent 设计

### 2.1 当前实现：纯正则提取器

`parse/agent.py`（214行）是纯规则解析器，不接收 `session_id`，不查询 KG：

```
parse/agent.py:
  4 个正则模式:
    _ZONE_TARGET_RE  - 分区/用地/面积/比例
    _FACILITY_RE     - 设施/服务中心/卫生室/学校/广场
    _AXIS_RE         - 发展轴/景观轴/生态廊道
    _ROAD_RE         - 道路/公路/村道/乡道 + 宽度

  公共 API:
    parse(planning_text, village_name, planning_period) -> ParseResult
    parse_async(...) -> ParseResult  (asyncio.to_thread 包装)

  ParseResult:
    intent: SpatialPlanningIntent
    operation_sequence: List[Any]
    constraint_set: List[Any]
    validation_errors: List[str]
```

`ParseAgentState` 中以下字段**全部空置**：
- `context_blocks`
- `code_mappings_projects`
- `place_mappings_projects`

### 2.2 目标：消费 ExplorationInstruction

PARSE 修正后消费 EXPLORE 产出，不再独立解析报告：

```
PARSE 修正后:
  1. 从 state 读取 ExplorationInstructionCollection + ReportSummaryIndex
  2. 扫描概要索引，识别空间相关维度 (spatial_relevance == "high")
  3. 按需获取该维度完整 L3 报告原文 (ReportStore.get_latest_report)
  4. 结合 ExplorationInstruction 的候选 BSM + 域分类 + 约束
  5. 产出类型化 ZoneTarget/FacilityTarget/AxisTarget/RoadTarget
  6. 填充 ParseAgentState 的空置字段 (code_mappings/place_mappings/context_blocks)
```

### 2.3 空间接地（SpatialReferenceSpec -> ResolvedSpatialRef）

PARSE 的空间接地分两阶段：

```
阶段1: PARSE 产出 SpatialReferenceSpec (closed-set DSL)
  ↓ instructor + LLM
阶段2: KG resolve_candidates -> CandidateSet (粗筛 BSM)
  ↓ spatial_ops.resolve_spatial_ref
阶段3: ResolvedSpatialRef (精确 BSM + bbox + confidence)
```

**契约已就绪**：
- `spatial_ref_contracts.py` 定义 `SpatialReferenceSpec`（closed-set: 5 type / 5 kind / 8 direction / 6 topo）
- `queries/spatial_ref.py` 实现 `resolve_candidates(kg, spec) -> CandidateSet`
- `parse_queries["resolve_candidates"]` 已注册（status: available）

**缺口**：
- PARSE agent 不产出 `SpatialReferenceSpec`（纯正则无 LLM）
- `spatial_ops` 无 `resolve_spatial_ref` 函数（阶段3 未实现）

### 2.4 消除双重 parse

当前双重 parse：
1. `graph.py:97` `gis_agent_node` 独立调 `create_parse_agent_graph()`
2. `layout_pipeline.py:123` `_parse_intent_node` 再调 `parse_async()`

EXPLORE 提升后：
- `gis_agent_node` 移除独立 parse 调用
- `layout_pipeline.py` 的 `_parse_intent_node` 统一消费 EXPLORE 产出
- 消除 `graph.py:97` 的 `create_parse_agent_graph`

---

## 3. EXECUTE Agent 设计

### 3.1 子图结构

`execute/agent.py` 构建 7 节点 StateGraph：

```
START -> route_tasks -> execute_layout -> execute_facility
  -> execute_axis -> execute_road -> validate
  -> {pass: write_l4 -> END | retry: execute_layout}
```

| 节点 | 职责 | 实现 |
|------|------|------|
| route_tasks | 按 intent 决定执行哪些子任务 | `_route_tasks_node` - layout 必跑，facility/axis 按 intent 有无，road 必排队 |
| execute_layout | 分区分配 + 功能区/规划分区层 | `_execute_layout_node` - MIP 分配 + `_generate_function_zones` + `_make_planning_zone_layer` |
| execute_facility | 设施点放置 | `_execute_facility_node` - `_generate_facilities` + KG 查现有设施坐标 |
| execute_axis | 发展轴 + 空间管制区 + 用途分区 | `_execute_axis_node` - 3 个 layer 生成 |
| execute_road | 规划路网 | `_execute_road_node` - `plan_roads(road_targets, current_roads)` |
| validate | Evaluator Gate | `_validate_node` - `LayoutValidator.validate` + 产出 constraint_adjustments |
| write_l4 | L4 回写 | `_write_l4_node` - 写 PlannedParcel/PlannedZone/PlannedFacility/PlannedAxis/PlannedRoad |

### 3.2 多策略执行

EXECUTE 的 layout 节点采用三层策略：

| 策略层 | 机制 | 说明 |
|--------|------|------|
| 主策略 | parcel operations | `_apply_operations(allocated, operation_sequence)` - reclassify/modify/split/merge |
| 次策略 | MIP quota check | `MIPZoneAllocator().solve(...)` - 按面积配额约束分配 |
| 辅策略 | programmatic generation | `_generate_function_zones` / `_make_planning_zone_layer` - 程序化生成图层 |

> ConstraintCompiler 已 `[DEPRECATED]`，MIP 直接消费 SPARQL 结果，不经编译中间层。

### 3.3 Evaluator Gate

```
validate (LayoutValidator)
  │
  ├── passed=True ──> write_l4 ──> END
  │
  └── passed=False
        ├── round < 3 ──> retry ──> execute_layout (带 constraint_adjustments)
        └── round >= 3 ──> pass (使用最优结果)
```

`_route_after_validate`（execute/agent.py:357）：
- `passed=True` -> `"pass"` -> write_l4
- `passed=False` + `round >= 3` -> `"pass"`（超限，用最优结果）
- `passed=False` + `round < 3` -> `"retry"` -> execute_layout

重试时 `constraint_adjustments` 反馈到 layout 节点：
```python
# execute/agent.py:102-111
if state.constraint_adjustments:
    for adj in state.constraint_adjustments:
        zone = adj.get("zone", "")
        delta = adj.get("delta_ha", 0)
        if zone in target_map and delta:
            target_map[zone] = round(target_map[zone] + delta, 2)
```

> 注：layout_pipeline.py:333 也有一个 `_route_after_validation`，但属 legacy，execute 子图内部自管重试。

### 3.4 L4 回写（write_kg_l4）

`_write_l4_node`（execute/agent.py:374）将布局成果写回 KG L4：

```
layout_configs 中的每个 feature (非 preserve 操作):
  ├─ function_zone/planning_zone -> PlannedZone_{bsm}
  ├─ facility                   -> PlannedFacility_{bsm}
  ├─ axis                       -> PlannedAxis_{bsm}
  ├─ road                       -> PlannedRoad_{bsm}
  └─ 其他                       -> PlannedParcel_{bsm}
```

每个 L4 实体带 provenance 谓词（经 `layer4.py:apply_planned_state`）：

| 谓词 | 含义 | 示例 |
|------|------|------|
| `pln:derived_from` | 溯源到 L1 地块 | derived_from Parcel_{bsm} |
| `pln:source_spec` | PARSE spec 来源 | "directional:east_of_village" |
| `pln:decided_by` | 决策者 | "rule" / "llm" / "human" |
| `pln:operation` | 操作类型 | reclassify / merge / split / new / demolish |
| `pln:area_change_ha` | 面积变化（有符号） | -2.5 (减少) / +1.0 (增加) |
| `pln:in_version` | 版本标记 | "current" / "v2" |

---

## 4. layout_pipeline 9 节点流

`layout_pipeline.py` 构建 9 节点 StateGraph：

```
START -> fetch_gis_data -> build_kg -> parse_intent -> write_kg_l3
  -> detect_conflicts -> execute -> export_gdb -> render_map -> END
```

| # | 节点 | 职责 | 实现 |
|---|------|------|------|
| 1 | fetch_gis_data | DataCatalog 加载 VillageBundle | `_fetch_gis_data_node` (layout_pipeline.py:30) |
| 2 | build_kg | 构建 L1+L2 KG + 预计算邻接/约束/保护地块 | `_build_kg_node` (layout_pipeline.py:56) |
| 3 | parse_intent | PARSE 消费报告文本 -> SpatialPlanningIntent | `_parse_intent_node` (layout_pipeline.py:123) |
| 4 | write_kg_l3 | 写 L3 intent 实体到 KG | `_write_kg_l3_node` (layout_pipeline.py:190) |
| 5 | detect_conflicts | 跨维度冲突检测 | `_detect_conflicts_node` (layout_pipeline.py:225) |
| 6 | execute | EXECUTE 子图 + Evaluator Gate + write_kg_l4 | `_execute_node` (layout_pipeline.py:272) |
| 7 | export_gdb | GDB 12 层汇交导出 | `_export_gdb_node` (layout_pipeline.py:243) |
| 8 | render_map | MapLibre 地图渲染 | `_render_map_node` (layout_pipeline.py:256) |

**执行顺序设计**：PARSE 在 `fetch_gis_data` + `build_kg` 之后执行，使其可查询 live KG 做空间接地。L3 intent 实体作为独立节点在 PARSE 完成后写入。

---

## 5. 校验反馈回路

```
                    ┌─────────────────────────────────┐
                    ▼                                 │
execute_layout ──> validate ──(fail, round<3)──> retry (带 adjustments)
                    │
                    ├──(pass)──> write_l4 ──> END
                    │
                    └──(fail, round>=3)──> pass (用最优) ──> write_l4 ──> END
```

**反馈链路**：
1. `validate` 产出 `constraint_adjustments`（zone/delta_ha/reason/priority）
2. `retry` 路由回 `execute_layout`，`constraint_adjustments` 被应用到 `target_map`
3. layout 重新 MIP 分配，产出新的 `allocated_geojson` + `layout_configs`
4. 再次 `validate`，直到 pass 或超 3 轮

**L3 校核轮（设计）**：EXECUTE 完成后，L3 读 L4 PlannedState 做文本/几何一致性校核：
- `land_use_planning`：`get_area_by_type` 算 L4 规划后面积 vs L3 文本表述面积
- `spatial_structure`：读 L4 PlannedZone 的 `derived_from` 链校核结构
- `project_bank`：读 L4 PlannedFacility 的 `operation`/`area` 校核项目表

---

## 6. execute_queries 命名空间

`kg/queries/__init__.py` 定义四命名空间，execute_queries 大部分 reserved/exists_not_wired：

| 查询 | 状态 | 说明 |
|------|------|------|
| get_candidate_parcels_for_layout | `reserved` | L3 ZoneTarget 候选 vs L1 地块（重试用） |
| check_conflicts | `exists_not_wired` | 规划地块与约束面冲突检查 |
| get_constraint_coverage | `exists_not_wired` | 约束覆盖（替代旧 get_protected_parcels_detail） |
| verify_constraints | `reserved` | 单地块约束检查 |
| get_l4_state | `exists_not_wired` | 读 L4 规划成果状态 |
| get_effective_land_use | `exists_not_wired` | L4->L1 回退读取有效地类 |
| get_effective_area_ha | `exists_not_wired` | L4->L1 回退读取有效面积 |
| get_planned_parcels_in_zone | `exists_not_wired` | 按分区查询规划地块 |
| get_l4_derived_from_l1 | `exists_not_wired` | L4->L1 溯源审计 |
| apply_planned_state | `exists_not_wired` | 持久化 L4（当前未接入 execute） |
| compare_versions | `exists_not_wired` | 版本差异对比 |
| validate_intent | `exists_not_wired` | L3 vs L1 设施冲突检测 |
| get_facility_locations | `wired` | 设施位置（execute 唯一直接查询） |
| get_road_network | `exists_not_wired` | 道路网络查询 |
| get_village_anchors | `exists_not_wired` | 村庄锚点查询 |

> 仅 `get_facility_locations` 实际接入 execute 子图。其余查询函数已实现但未接入。

---

## 7. 实现状态总览

| 组件 | 状态 | 证据 |
|------|------|------|
| **PARSE Agent** | | |
| 纯正则提取器（4模式） | `[IMPLEMENTED]` | parse/agent.py:55-78 |
| parse_async 公共 API | `[IMPLEMENTED]` | parse/agent.py:201 |
| 消费 ExplorationInstruction | `[PLANNED]` | 待修正，当前只取 reports 文本 |
| 消除双重 parse | `[PLANNED]` | graph.py:97 待移除 |
| ParseAgentState 空置字段填充 | `[PLANNED]` | context_blocks/code_mappings/place_mappings |
| **PARSE 空间接地** | | |
| SpatialReferenceSpec 契约 | `[IMPLEMENTED]` | spatial_ref_contracts.py |
| resolve_candidates (KG 侧) | `[IMPLEMENTED]` | queries/spatial_ref.py |
| parse_queries["resolve_candidates"] 注册 | `[IMPLEMENTED]` | queries/__init__.py:116 |
| PARSE 产出 SpatialReferenceSpec | `[PARTIAL]` | 纯正则无 LLM，不产出 spec |
| spatial_ops.resolve_spatial_ref | `[PLANNED]` | 阶段3 未实现 |
| **EXECUTE Agent** | | |
| 7节点子图 | `[IMPLEMENTED]` | execute/agent.py:465 |
| 多策略执行（parcel ops + MIP + programmatic） | `[IMPLEMENTED]` | execute/agent.py:56-166 |
| Evaluator Gate（max 3 retry） | `[IMPLEMENTED]` | execute/agent.py:357 |
| constraint_adjustments 反馈 | `[IMPLEMENTED]` | execute/agent.py:102-111 |
| write_l4 节点 | `[IMPLEMENTED]` | execute/agent.py:374 |
| L4 provenance 谓词 | `[IMPLEMENTED]` | layer4.py:232 apply_planned_state |
| execute_queries 接入 | `[PARTIAL]` | 仅 get_facility_locations wired |
| ConstraintCompiler | `[DEPRECATED]` | 代码已清理，MIP 直接消费 SPARQL |
| **layout_pipeline** | | |
| 9节点 StateGraph | `[IMPLEMENTED]` | layout_pipeline.py:349 |
| fetch_gis_data | `[IMPLEMENTED]` | layout_pipeline.py:30 |
| build_kg | `[IMPLEMENTED]` | layout_pipeline.py:56 |
| parse_intent | `[PARTIAL]` | layout_pipeline.py:123（纯正则，不查 KG） |
| write_kg_l3 | `[IMPLEMENTED]` | layout_pipeline.py:190 |
| detect_conflicts | `[IMPLEMENTED]` | layout_pipeline.py:225 |
| execute | `[IMPLEMENTED]` | layout_pipeline.py:272 |
| export_gdb | `[IMPLEMENTED]` | layout_pipeline.py:243 |
| render_map | `[IMPLEMENTED]` | layout_pipeline.py:256 |
| **校核回路** | | |
| Evaluator Gate 重试回路 | `[IMPLEMENTED]` | execute/agent.py:492 |
| L3 校核轮（读 L4 对账） | `[PLANNED]` | I5 改造 |
