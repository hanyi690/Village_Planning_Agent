# EXECUTE Agent 子包

> 空间意图 → 空间成果。消费 PARSE 产出的 `SpatialPlanningIntent` + KG 上下文，产出分配用地 / 设施 / 轴线 / 道路等空间布局层。

---

## 一、定位

EXECUTE 是 GIS Agent 的 **DELIVER 阶段执行核**，与 `parse/`（PLAN 阶段）平级。它把类型化空间意图转化为可导出的空间图层，核心解决"意图 → 空间实体"的落地鸿沟。

**与 PARSE 的关系**：通过 LangGraph state 注入通信，不直接调用。PARSE 产出写入 `GISPipelineState`，EXECUTE 从中读取。

**与 LAYOUT 的关系**：LAYOUT 是 EXECUTE 内的一个子任务（用地布局），与 facility / axis / road 平级。当前 `layout_pipeline.py` 的 `allocate_and_generate` 节点把所有生成逻辑压在一个 ReAct 子图里，EXECUTE 子包的目标是将其拆分为独立子任务。

---

## 二、图架构（agent.py）

```
START
  → route_tasks        # 根据 intent 决定执行哪些子任务
  → execute_layout     # 用地分配 + 功能分区生成
  → execute_facility   # 设施点布局
  → execute_axis       # 发展轴线生成
  → execute_road       # 规划道路网络（placeholder）
  → validate           # Evaluator 闸门
      ├─ pass  → END
      └─ retry → execute_layout（最多 3 轮）
```

- **状态**：`ExecuteAgentState`（Pydantic BaseModel）
- **Worker-Evaluator 模式**：`validate` 节点为闸门，失败时带 violations 反馈回到 `execute_layout` 重试
- **顺序骨架**：子任务有依赖（设施需分区、轴线需用地），暂为顺序执行；P2 可改为 Send 并行 fan-out

### 节点说明

| 节点 | 职责 | 消费 | 产出 | 状态 |
|------|------|------|------|------|
| `route_tasks` | 决定子任务集 | `intent` | `tasks_to_run` | ✅ 已实现 |
| `execute_layout` | 用地分配 + 功能分区 | `intent.zone_targets`, `kg_constraints`, `kg_adjacency_map` | `allocated_geojson`, 功能分区层 | ⚠️ placeholder |
| `execute_facility` | 设施点布局 | `intent.facilities`, `facility_anchors`, `allocated_geojson` | 设施层 | ⚠️ placeholder |
| `execute_axis` | 发展轴线 | `intent.development_axes`, `allocated_geojson` | 轴线层 | ⚠️ placeholder |
| `execute_road` | 规划道路网络 | `intent`, 现状道路(KG), `allocated_geojson` | 道路层 | ⚠️ placeholder（无生成器） |
| `validate` | 校验布局结果 | `allocated_geojson`, `layout_configs`, `kg_constraints` | `validation_result`, `validation_round` | ⚠️ placeholder |

---

## 三、子任务目录

| 子目录 | 职责 | 包装的工具（P1） |
|--------|------|-----------------|
| `layout/` | 用地分配 + 功能分区生成 | `tools/gis/allocate.allocate_zones` + `_generation/zone_generator` |
| `facility/` | 公共服务设施点布局 | `tools/gis/_generation/facility_placer` |
| `axis/` | 发展轴线生成 | `tools/gis/_generation/axis_builder` |
| `road/` | 规划道路网络 | 无（`PlannedRoad` schema 已定义，生成器待实现） |

---

## 四、状态（state.py）

### ExecuteAgentState

`GISPipelineState` 的执行层子集，聚焦空间成果生产：

| 字段组 | 字段 | 说明 |
|--------|------|------|
| 身份 | `session_id`, `village_name` | 会话/村庄标识 |
| 上游输入 | `gis_data`, `intent`, `operation_sequence`, `constraint_set` | 来自 PARSE + 数据层 |
| KG 上下文 | `kg_turtle`, `kg_constraints`, `kg_adjacency_map`, `kg_session_ref`, `kg_three_lines` | 来自 KGManager（只读视图） |
| 执行产出 | `allocated_geojson`, `allocation_summary`, `layout_configs` | 分配结果 + 图层列表 |
| 校验 | `validation_result`, `validation_round` | Worker-Evaluator 状态 |
| 路由 | `tasks_to_run` | 子任务集 |
| 消息 | `messages` | LangGraph 累积消息 |

字段类型刻意镜像 `GISPipelineState`，便于顶层流水线通过子集构造 `ExecuteAgentState(**pipeline_state_subset)`。

---

## 五、当前状态（P0 骨架）

- ✅ 图编译通过：6 节点 + 条件边
- ✅ 端到端可运行：smoke test 通过（空 intent 正确跳过 facility/axis，validate 1 轮通过）
- ⚠️ **节点为 placeholder**：`execute_*` / `validate` 均为 pass-through，未调用真实工具
- ⚠️ **未接入生产**：`layout_pipeline.py` 仍跑内联的 `_allocate_generate_react_node` + `_validate_layout_node`

---

## 六、迁移路线

### P0：骨架（已完成）

搭建 `execute/` 子包目录 + 可编译 StateGraph + placeholder 节点。不破坏现有生产管线。

### P1：接入生产（待执行）

1. `execute_layout` 节点接入 `allocate_zones` + `_generate_function_zones`
2. `execute_facility` / `execute_axis` 节点接入 `facility_placer` / `axis_builder`
3. `validate` 节点接入 `validate_layout`
4. `layout_pipeline.py` 的 `_allocate_generate_react_node` + `_validate_layout_node` 替换为调用 `build_execute_agent_graph()`
5. 消除 `tools/gis/_generation/pipeline.py` 命令式 `run_layout_pipeline()` 与 StateGraph 版的重复

### P2：子任务分解 + 道路生成器（待规划）

1. 拆 `generate_layout` 工具为子任务专用生成器（layout/facility/axis 各自独立）
2. 实现 `PlannedRoad` 生成器，落地 `execute_road` 节点
3. `layout_pipeline.py` 改名 `pipeline.py`（名不副实，实为顶层编排器）
4. 子任务改 Send 并行 fan-out（无依赖时）

---

## 七、接入点

生产接入在 `app/agent/graph.py` 的 `gis_agent_node`：

```python
# 当前（P0）：
from .gis.layout_pipeline import build_layout_pipeline
pipeline = build_layout_pipeline()

# 目标（P1）：
from .gis.execute import build_execute_agent_graph
execute = build_execute_agent_graph()  # 替换 allocate_and_generate + validate
```

---

## 八、相关文档

- `../README.md` — GIS Agent 包总览
- `../parse/README.md` — PARSE Agent（上游生产者）
- `app/modules/kg/README.md` — KG 桥接层（提供约束/邻接查询）
- `docs/gis/proposals/03_TOOL_FIRST_ARCHITECTURE.md` §4 — EXECUTE_OPS Agent 预留依据
