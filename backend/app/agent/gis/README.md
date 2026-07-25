# GIS Agent 包

> 村庄规划空间布局的 Agent 编排层。
> `parse/`（规划文本 → 空间意图）与 `execute/`（空间意图 → 空间成果）平级，顶层流水线编排二者及 KG / 导出 / 渲染。

---

## 一、包定位

本包是村庄规划系统的 **PLAN / DELIVER 执行核**，对应 v6.0 北极星三段（ANALYZE / PLAN / DELIVER）中的后两段：

- **PARSE Agent**（`parse/`）：消费 L3 规划报告文本 + ContextBlock 列表，产出类型化空间意图（`SpatialPlanningIntent` / `SpatialOperation` / `SpatialConstraint`）
- **EXECUTE Agent**（`execute/`）：消费空间意图 + KG 上下文，产出空间布局成果（分配用地 / 设施 / 轴线 / 道路）
- **顶层流水线**（`layout_pipeline.py`）：编排 parse → fetch → KG → conflicts → execute → export → render 的确定骨架

两个子包通过 **LangGraph state 注入** 通信，不直接互相调用。KG 模块（`app/modules/kg/`）是二者之间的语义桥接层。

---

## 二、目录结构

```
backend/app/agent/gis/
├── __init__.py          # 包导出
├── README.md            # 本文档
├── agent.py             # Agent 构建器（parse/execute/legacy + run_gis_pipeline）
├── state.py             # GISPipelineState / Input / Output + legacy TypedDict 别名
├── prompts.py           # PARSE / LAYOUT 系统 prompt
├── layout_pipeline.py   # 顶层流水线 StateGraph（9 节点，名不副实待改名 pipeline.py）
├── parse/               # PARSE Agent 子包（规划文本 → 空间意图）
│   ├── README.md
│   ├── agent.py         # build_parse_agent_graph()
│   └── state.py         # ParseAgentState + SpatialPlanningIntent 等
└── execute/             # EXECUTE Agent 子包（空间意图 → 空间成果）
    ├── README.md
    ├── agent.py         # build_execute_agent_graph()
    ├── state.py         # ExecuteAgentState
    ├── layout/          # 用地布局子任务
    ├── facility/        # 设施布局子任务
    ├── axis/            # 发展轴线子任务
    └── road/            # 道路规划子任务（placeholder）
```

---

## 三、顶层流水线（layout_pipeline.py）

`build_layout_pipeline()` 构建统一 StateGraph，采用 **确定骨架 + ReAct 自适应 + Worker-Evaluator 重试**：

```
START
  → parse_intent          # 调用 parse/ 子图
  → fetch_gis_data        # 天地图/OSM/高德数据获取
  → build_kg              # 构建 KG（Layer1 缓存 + Layer2 语义 + Layer3 易失）
  → detect_conflicts      # 跨维度冲突检测
  → allocate_and_generate # ReAct 子图：分配 + 生成多层布局
  → validate_layout       # Evaluator 闸门
      ├─ pass  → export_gdb → render_map → END
      └─ retry → allocate_and_generate（最多 3 轮）
```

- **状态**：`GISPipelineState`（Pydantic BaseModel），`input_schema=GISPipelineInput`，`output_schema=GISPipelineOutput`
- **入口**：`run_gis_pipeline(session_id, village_name, planning_text, l3_reports)`（`agent.py:101`）
- **接入点**：`app/agent/graph.py` 的 `gis_agent_node` 调用 `build_layout_pipeline()`

> ⚠️ **命名债务**：`layout_pipeline.py` 实为整个 GIS 流水线的顶层编排器，不只是 LAYOUT。待 `execute/` 接入后应改名为 `pipeline.py`。参见 `execute/README.md` 的迁移路线。

---

## 四、Agent 构建器（agent.py）

| 函数 | 用途 | 状态 |
|------|------|------|
| `create_parse_agent_graph()` | 转发到 `parse/agent.build_parse_agent_graph()` | ✅ 生产 |
| `build_layout_pipeline()` | 顶层流水线（推荐入口） | ✅ 生产 |
| `run_gis_pipeline(...)` | 异步端到端入口 | ✅ 生产 |
| `create_gis_agent_graph()` | 单 ReAct Agent（13 工具） | ⚠️ 已废弃，向后兼容保留 |
| `create_layout_agent_graph()` | 单 ReAct Agent（11 工具） | ⚠️ 已废弃，仍被 `allocate_and_generate` 节点内部使用 |

---

## 五、状态架构（state.py）

```
GISPipelineInput  ── API 输入（session, village, planning_text, l3_reports）
GISPipelineState  ── 内部全状态（identity / input / intent / KG / allocation / layout / validation / export / render / messages）
GISPipelineOutput ── API 输出（layout_configs, export_result, render_result, validation_passed）
```

legacy TypedDict 别名（`GISAgentState` / `ParseAgentState` / `LayoutAgentState` / `LayoutPipelineState`）仅向后兼容，新代码用 `GISPipelineState`。

---

## 六、迁移路线

当前生产路径：`layout_pipeline.py` 的 `_allocate_generate_react_node` + `_validate_layout_node` 直接跑内联的 ReAct + validate。

目标路径：这两个节点替换为调用 `execute/` 子图，使 LAYOUT 真正成为 execute 层的子任务。

| 阶段 | 内容 | 状态 |
|------|------|------|
| P0 | `execute/` 骨架可编译、可运行（placeholder 节点） | ✅ 完成 |
| P1 | execute 节点接入现有工具；顶层流水线调用 execute 子图 | 待执行 |
| P2 | 拆 `generate_layout` 为子任务专用生成器；实现 road 生成器；`layout_pipeline.py` 改名 | 待规划 |

---

## 七、相关文档

- `parse/README.md` — PARSE Agent 架构
- `execute/README.md` — EXECUTE Agent 架构与迁移路线
- `app/modules/kg/README.md` — KG 桥接层（parse/execute 间的语义中间态）
- `docs/gis/00_PLANNING_SYSTEM_VISION.md` — v6.0 北极星（ANALYZE/PLAN/DELIVER）
- `docs/gis/proposals/03_TOOL_FIRST_ARCHITECTURE.md` — Tool-First 架构（execute 子包预留依据）
