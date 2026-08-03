# EXECUTE Agent 子包

> 空间执行层：消费 PARSE intent + KG 上下文，产出空间布局结果（分区、设施、轴线、道路），Worker-Evaluator 重试循环 + L4 写回 KG。
> **Updated: 2026-08-02**

---

## 一、定位

EXECUTE 是 GIS Agent 的 **DELIVER 阶段执行核**，与 `parse/`（PLAN 阶段）平级，由顶层 `layout_pipeline.py` 在 PARSE 完成后调用。它把 PARSE 产出的 `SpatialPlanningIntent` + 上层的 KG 上下文，转化为可导出的空间图层（GeoJSON FeatureCollection），并校验合规性后写回 KG（L4 规划实体）。

> ✅ **状态：P1 已全部接通**。早期文档称"P0 skeleton / 节点为 pass-through placeholder / 未接入顶层管线"，**已过时**——当前 7 节点全部调用真实生成器（MIP 分配器、FacilityPlacer、轴线生成器、道路 Stage 0-6 生成器、LayoutValidator），并经 `write_l4` 写回 KG。P1 实现直接调用 `tools/gis` 私有生成器（`_generate_*` / `MIPZoneAllocator` / `LayoutValidator`），绕过 `@tool` 包装与 `InjectedState`；**P2 目标**是将其提升为公开生成 API 再迁移。

---

## 二、目录结构

```
execute/
├── __init__.py            # 导出 ExecuteAgentState / build_execute_agent_graph
├── agent.py               # ★ 图构建 + 7 个节点实现（633 行）
├── state.py               # ExecuteAgentState（Pydantic，字段镜像 GISPipelineState）
├── road/
│   ├── __init__.py        # 导出 execute_road_planning_from_agent_state
│   └── generator.py       # 道路 Stage 0-6 生成器（远程/门控 + 本地 plan_roads 回退）
├── layout/                # 分区分配（MIP）+ 功能区 + 规划区层（逻辑内联于 _execute_layout_node）
├── facility/              # 设施点布设（逻辑内联于 _execute_facility_node）
└── axis/                  # 发展轴 + 空间管制区 + 用地分区层（逻辑内联于 _execute_axis_node）
```

> `layout/ facility/ axis/` 三个子目录目前仅含 `__init__.py`（占位），**实际逻辑直接写在 `agent.py` 的节点函数内**。

---

## 三、公开 API

```python
from app.agent.gis.execute import ExecuteAgentState, build_execute_agent_graph

graph = build_execute_agent_graph()          # 编译好的 StateGraph
result = await graph.ainvoke(ExecuteAgentState(**state_subset))
```

**状态边界**：`ExecuteAgentState` 字段刻意镜像 `GISPipelineState`（`gis_data` / `gis_bundle` / `intent` / `operation_sequence` / `constraint_set` / `facility_anchors` / `kg_*` 只读视图），顶层管线用 `ExecuteAgentState(**pipeline_state_subset)` 构造子状态，并在子图边界做状态映射。

---

## 四、图结构（7 节点 + 1 条件边）

```
START → route_tasks → execute_layout → execute_facility → execute_axis → execute_road → validate
                                                                            │
        validate ──pass──→ write_l4 → END                    (retry) ──→ execute_layout
             （Worker-Evaluator 重试，max 3 轮）
```

### 节点明细

| 节点 | 实现 | 职责 |
|---|---|---|
| `route_tasks` | `_route_tasks_node` | 依据 typed/legacy intent 决定子任务：`layout` 为核心任务；`facility`/`axis`/`road` 仅当 intent 带对应 target |
| `execute_layout` | `_execute_layout_node` | ★ 核心：`_apply_operations` → 用地 **MIPZoneAllocator.solve** → **CustomZoningGenerator** 候选筛选（词汇表/规则/三线）→ 第二次 MIP 解决自定义分区候选冲突 → `custom_planning_zone` 主分区层 |
| `execute_facility` | `_execute_facility_node` | `_generate_facilities`（查 KG 既有设施坐标 → FacilityPlacer 布设新设施），追加 facility 层 |
| `execute_axis` | `_execute_axis_node` | `_generate_axes` + `_generate_space_control_zone`（三线传入）+ `_generate_land_use_zone`，最多追加 3 层 |
| `execute_road` | `_execute_road_node` | 优先 **`road/generator.py::execute_road_planning_from_agent_state`**（Stage 0-6 门控生成）；失败降级 `modules/spatial_ops/road_planner.plan_roads`（upgrade/create/preserve） |
| `validate` | `_validate_node` | `LayoutValidator.validate`（protected parcels / VNE 详情），产出 `constraint_adjustments` 供重试（adjustments 反馈回 `execute_layout` 修正分配目标） |
| `write_l4` | `_write_l4_node` | 把规划实体（PlannedParcel / PlannedZone / PlannedFacility / PlannedAxis / PlannedRoad）写入 session KG（`EntityAnnotation`，`l4_provenance` 维度，`derived_from="execute_computed"`），成功后 `bump_version` |

### 重试与退出
- `_route_after_validate`：`passed` → `write_l4`；`validation_round >= 3` → 结束重试，但失败结果不会写入 L4。
- 缺现状地类、缺分区目标或声明了 facility/axis/road target 却未生成对应成果时，写入 `execution_errors` 并由 validator 阻断正式成果。

---

## 五、布局节点细节（execute_layout）

1. **数据准备**：从 `gis_bundle`（优先）或 `gis_data` 取 `landuse_current_geojson`；无数据则记录执行错误并阻断正式输出。
2. **操作应用**：若上游带 `operation_sequence` 且已有 `allocated_geojson`，先 `_apply_operations`。
3. **目标解析**：`intent.zone_targets` → `target_map`（绝对 `area_ha` 优先，否则 `area_ratio × 总面积`）+ `density_hints` + `adjacency_rules`；无明确目标不再复制现状分布兜底。
4. **重试修正**：`constraint_adjustments`（zone + delta_ha + reason）叠加进 `target_map`。
5. **约束合并**：`state.kg_constraints` + `_spatial_constraint_to_mip(constraint_set)`。
6. **B1 候选画布**：`custom_zone_targets[].target_bsms`（binder/gazetteer 产出）注入 `zone_targets.candidate_bsms`，限定 MIP 分配池（空间定位生效）。
7. **MIP 求解**：`MIPZoneAllocator().solve(...)`，trace 含 `mode`（mip/intent-only）。
8. **图层生成**：`function_zone` 仅作隐藏分析层；不再输出 `planning_zone` 为规划主成果。
9. **P7 自定义主分区**：`CustomZoningGenerator(parcels, intent_dict, three_lines)` 生成候选地块；第二次 `MIPZoneAllocator` 以每区候选 BSM 作为硬边界，解决跨区冲突；`custom_planning.py` 合并地块、补足显式“待确认分区”，输出唯一 `custom_planning_zone` 主分区层。

---

## 六、道路子任务（road/generator.py）

`execute_road_planning_from_agent_state(state) -> Dict`（`{ran, reason, road_target_count, layout_layers, stage_*_report, ...}`）：

- **Stage 2 准备**：`_road_targets_to_stage2` 把 `RoadTarget` → demand points / road projects / road constraints（写 `stage2_from_parse/`）。
- **Stage 1**：`build_road_network`（当前路网 → nodes/edges）。
- **Stage 2.6**：`build_planning_nodes_with_kg_retry_adapter` → KG retry adapter → `build_planning_nodes`（规划节点构建 + 质量闸门 + 人工确认模板 + 迭代记录）。
- **Stage 3**：`bind_road_spatial_requirements` → `planning_gate`（`automatic_route_generation_allowed`）。
- **Stage 4**：门控通过且 `landuse_path` 存在 → `run_stage4_road_planning`（自动路径生成 → `planned_road_candidates`）。
- 产物图层：`road_spatial_candidates`（隐藏）、`road_planning_entities`（隐藏）、`road_planning_nodes`（可见）、`planned_road_candidates`（隐藏）。
- 失败/门控未开 → 返回 `ran=False`，由 `_execute_road_node` 降级到 `road_planner.plan_roads`。

---

## 七、输入输出契约

```
输入:  ExecuteAgentState
         gis_data / gis_bundle   # GIS 数据容器（landuse_current 等）
         intent                  # SpatialPlanningIntent（typed）或 dict（legacy）
         operation_sequence / constraint_set
         facility_anchors
         kg_* 只读视图（turtle / constraints / adjacency_map / three_lines / protected_parcels_detail / vne_summary / session_ref）

输出:  layout_configs: List[Dict]     # 各层 {layer_type/layerType, data 或 features, ...}
         function_zone（分析）/ custom_planning_zone（唯一主分区）
         facility / axis / space_control_zone / land_use_zone
         planned_road（road 层）+ road_planning_nodes 等
       allocated_geojson: FeatureCollection  # MIP 分配结果
       allocation_summary: {mode, allocated_count, density_hints?, adjacency_rules?}
       validation_result: {passed, status, violations[]}
       constraint_adjustments: List[{zone, action, delta_ha, reason, priority}]
       → write_l4 把规划实体写回 session KG（版本号自增）
```

顶层 `layout_pipeline.py` 消费 `layout_configs`，与 KG / `gis_bundle` 打包为最终响应（`parse` + `execute` 两阶段产物）。

---

## 八、相关文档

- `../README.md` — GIS Agent 包总览
- `../parse/README.md` — PARSE Agent（上游 intent 生产者）
- `app/tools/gis/` — 被直接调用的生成器（`generate` / `allocate` / `_generation` / `_validation`）
- `app/modules/spatial_ops/README.md` — `road_planner.plan_roads` 降级路径
- `app/modules/kg/README.md` — KG（gazetteer / memory L4 写回）
