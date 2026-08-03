# GIS Agent 包

> 村庄规划空间布局的 Agent 编排层。
> `parse/`（规划文本 → 空间意图）与 `execute/`（空间意图 → 空间成果）平级，顶层流水线（`layout_pipeline.py`）编排二者及 KG / 导出 / 渲染。

---

## 一、包定位

本包是村庄规划系统的 **PLAN / DELIVER 执行核**，对应 v6.0 北极星三段（ANALYZE / PLAN / DELIVER）中的后两段：

- **PARSE Agent**（`parse/`）：消费 L3 规划报告文本 + ContextBlock 列表，产出类型化空间意图（`SpatialPlanningIntent` / `SpatialOperation` / `SpatialConstraint`）
- **EXECUTE Agent**（`execute/`）：消费空间意图 + KG 上下文，产出空间布局成果（分配用地 / 设施 / 轴线 / 道路）
- **顶层流水线**（`layout_pipeline.py`）：编排 fetch → build_kg → parse → write_kg_l3 → detect_conflicts → execute → export → render 的确定骨架

两个子包通过 **LangGraph state 注入** 通信，不直接互相调用。KG 模块（`app/modules/kg/`）是二者之间的语义桥接层。

---

## 二、目录结构

```
backend/app/agent/gis/
├── __init__.py          # 包导出
├── README.md            # 本文档
├── agent.py             # Agent 构建器（parse/legacy + run_gis_pipeline）
├── state.py             # GISPipelineInput / State / Output + legacy TypedDict 别名
├── prompts.py           # PARSE / LAYOUT 系统 prompt（legacy，新图不依赖）
├── layout_pipeline.py   # 顶层流水线 StateGraph（9 节点）
├── format_bound_intent.py   # Explore/Binder 产物 → 规划 intent（严格无工具，v4/P6）
├── spatial_entity_binder.py # Explore 候选 → bundle 不可变几何的确定性绑定
├── vocab_extractor.py       # L3 报告 → session 功能区词汇表（确定性）
├── vocab/               # 词汇表规则 DSL（TypingRule ↔ expr_eval.Condition）
│   ├── rules.py         #   rule_to_condition 统一求值
│   └── context.py       #   求值上下文（含 bundle 属性解析）
├── parse/               # PARSE Agent 子包（规划文本 → 空间意图）
│   ├── README.md
│   ├── agent.py         # parse() / parse_async() 规则解析管线
│   └── state.py         # ParseAgentState + SpatialPlanningIntent 等
└── execute/             # EXECUTE Agent 子包（空间意图 → 空间成果）
    ├── README.md
    ├── agent.py         # build_execute_agent_graph()（7 节点 Worker-Evaluator）
    ├── state.py         # ExecuteAgentState
    ├── layout/          # 用地布局子任务（占位，逻辑内联在 execute/agent.py）
    ├── facility/        # 设施布局子任务（占位，逻辑内联）
    ├── axis/            # 发展轴线子任务（占位，逻辑内联）
    └── road/            # 道路规划子任务（含 generator.py 的 Stage 0-6 生成器）
```

---

## 三、顶层流水线（layout_pipeline.py）

`build_layout_pipeline()` 构建统一 StateGraph，采用 **纯确定骨架 + execute 子图 Worker-Evaluator**（9 节点）：

```
START
  → fetch_gis_data    # DataCatalog 按 village 加载 bundle（schema 驱动单一路径）
  → build_kg          # KGManager Layer1 缓存 + Layer2 语义 + Layer3 易失；预计算邻接/约束/保护区
  → parse_intent      # PARSE Agent：规划文本 → intent（v4 外部 intent 优先，不做二次解析）
  → write_kg_l3       # intent 实体（ZoneTarget/FacilityTarget 等）写入 KG Layer3
  → detect_conflicts  # 跨维度冲突检测
  → execute           # EXECUTE 子图：route_tasks → 各生成器 → validate（内部最多 3 轮重试）
  → export_gdb        # 12 层 GeoPackage + 用地平衡表
  → render_map        # MapLibre 前端图层
  → END
```

- **状态**：`GISPipelineState`（Pydantic BaseModel），`input_schema=GISPipelineInput`，`output_schema=GISPipelineOutput`
- **入口**：`run_gis_pipeline(session_id, village_name, planning_text, l3_reports)`（`agent.py:96`）
- **接入点**：`app/agent/graph.py` 的 `gis_agent_node` 调用 `build_layout_pipeline()`
- **PARSE 位置**：fetch + build_kg 之后执行，可查询实时 KG 做空间锚定（gazetteer 解析 → `candidate_bsms`）
- **v4 外部 intent 门控**：`parse_intent` 节点若检测到已有带结构化内容的 intent（zone/custom_zone/facilities 任一非空），直接保留外部 intent 跳过内部重解析（`layout_pipeline.py:205-223`）

### P3-4 词汇表接线（`_attach_custom_zone_targets`）

`parse_intent` 节点末尾把 INSTRUCTION / 表格提取的实体名接到 L3 分区表词汇表（`layout_pipeline.py:27-78`）：

```
L3 报告功能分区表 ──vocab_extractor（确定性）──> session Vocabulary（register_vocabulary）
intent 的 facility/zone_target 实体名 ──format_bound_intent._match_category_code──> category_code
  └──> 生成 CustomZoneTarget（decided_by="rule", confidence=0.7, target_bsms 继承 gazetteer 候选）
       → CustomZoningGenerator 按类别规则选地 → 产出 L4 FunctionalZone
```

### 命名债务

`layout_pipeline.py` 实为整个 GIS 流水线的顶层编排器，不只是 LAYOUT；待 `execute/` 完全收口后可考虑改名为 `pipeline.py`（低优先级）。

---

## 四、Agent 构建器（agent.py）

| 函数 | 用途 | 状态 |
|------|------|------|
| `run_gis_pipeline(...)` | 异步端到端入口（推荐） | ✅ 生产 |
| `create_parse_agent_graph()` | 转发到 `parse/agent.parse_async`（返回函数而非 LangGraph） | ✅ 生产 |
| `build_layout_pipeline()` | 顶层流水线 StateGraph | ✅ 生产 |
| `create_gis_agent_graph()` | 单 ReAct Agent（13 工具） | ⚠️ 已废弃，向后兼容保留 |
| `create_layout_agent_graph()` | 单 ReAct Agent（11 工具） | ⚠️ 已废弃，不再被流水线引用 |

> 旧流水线中的 `_allocate_generate_react_node`（ReAct 子图）与 `_validate_layout_node`（Evaluator 闸门）**已删除**，由 `_execute_node`（`layout_pipeline.py:385`）整体替换——执行与重试逻辑全部收进 `execute/` 子图。

---

## 五、状态架构（state.py）

```
GISPipelineInput  ── API 输入（session, village, planning_text, l3_reports, intent）
GISPipelineState  ── 内部全状态（identity / input / intent / KG / allocation / layout / validation / export / render / messages）
GISPipelineOutput ── API 输出（layout_configs, export_result, render_result, validation_passed, validation_round）
```

- KG 侧预计算查询结果（`kg_three_zones` / `kg_three_lines` / `kg_protected_parcels_detail` / `kg_vne_summary` 等）在 `build_kg` 节点一次性算好，下游节点零 SPARQL 消费
- legacy TypedDict 别名（`GISAgentState` / `ParseAgentState` / `LayoutAgentState` / `LayoutPipelineState`）仅向后兼容，新代码一律用 `GISPipelineState`

---

## 六、周边能力（v4 / P6 / P8）

| 模块 | 职责 | 说明 |
|------|------|------|
| `spatial_entity_binder.py` | Explore 候选 → bundle 几何绑定 | 确定性 BSM 优先；`DeterministicBundleBinder` 只读不 mutate bundle，拒绝歧义候选 |
| `format_bound_intent.py` | Binder 产物 → 规划 intent | 严格无工具；project 域 → `CustomZoneTarget`；zone/landuse 目标从 evidence 提取 `area_ratio`（如 "生态保护区 15.39%"） |
| `vocab_extractor.py` | L3 报告 → session 词汇表 | LLM 只产类别定义（名称/颜色/地类线索/依据），不产几何不产 BSM；确定性 fallback + `_DLBM_HINTS` |
| `vocab/rules.py` | 词汇表规则 DSL | `TypingRule → expr_eval.Condition` 统一求值，消除 generator 双实现 |

---

## 七、相关文档

- `parse/README.md` — PARSE Agent 架构（规则解析管线）
- `execute/README.md` — EXECUTE Agent 架构（7 节点图 + 迁移路线 P1 已完成）
- `app/modules/kg/README.md` — KG 桥接层（parse/execute 间的语义中间态）
- `docs/gis/00_PLANNING_SYSTEM_VISION.md` — v6.0 北极星（ANALYZE/PLAN/DELIVER）
- `docs/gis/proposals/03_TOOL_FIRST_ARCHITECTURE.md` — Tool-First 架构（execute 子包预留依据）
