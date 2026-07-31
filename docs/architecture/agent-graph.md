# Agent 主图（Agent Graph）

> 回答"主图怎么跑"。
> 设计理由见 [design/04_PLANNING_PIPELINE.md](../design/04_PLANNING_PIPELINE.md) 与 [design/05_EXPLORE_BRIDGE.md](../design/05_EXPLORE_BRIDGE.md)。

## 1. 当前实现：5 节点主图

`create_unified_planning_graph()`（`backend/app/agent/graph.py:159`）构建 `StateGraph(AgentState)`，注册 5 个节点：

```
                         START
                           │
                           ▼
                   ┌───────────────┐
                   │ conversation  │  中央路由（大脑）
                   │ node.py:74    │  bind_tools: advance_planning_intent
                   └───────┬───────┘  + gis_analysis + analytics tools
                           │ after_conversation (routing.py:27)
          ┌────────────────┼────────────────┬──────────────┐
          ▼                ▼                ▼              ▼
   ┌─────────────┐  ┌──────────────┐  ┌────────────┐    END
   │execute_tools│  │analyze_      │  │ gis_agent  │  (闲聊/问答)
   │execute_     │  │dimension     │  │ graph.py:52│
   │node.py:79   │  │analysis/     │  │ PARSE+LAYOUT
   └──────┬──────┘  │node.py       │  │ 混合管线
          │         └──────┬───────┘  └─────┬──────┘
          │                │                │
          └────────────────┤                │
                  ▼        │                │
          ┌──────────────┐ │                │
          │conversation  │◄┘                │
          └──────────────┘                  │
                            ▼               │
                   ┌──────────────────┐     │
                   │layer_completion_ │     │
                   │check             │     │
                   │completion/       │     │
                   │node.py:20        │     │
                   └────────┬─────────┘     │
                            │ after_analysis (routing.py:129)
                            │ Wave 调度 + 跨层提前分发
                            ▼
                  ┌─────────────────┐
                  │ analyze_dimension│ (下一波 Send)
                  │ 或 conversation  │
                  │ 或 END           │
                  └─────────────────┘
                                         │
                                         ▼
                                   conversation ◄┘
```

### 节点表

| 节点 | 实现文件 | 职责 | 状态 |
|------|----------|------|------|
| `conversation` | `agent/conversation/node.py:74` | 中央路由。`bind_tools([advance_planning_intent, gis_analysis] + analytics)`，LLM 决策后经 `after_conversation` 路由 | `[IMPLEMENTED]` |
| `execute_tools` | `agent/tools/execute_node.py:79` | `[过渡性]` 仅处理非路由 tool_calls（`knowledge_search`、`web_search`、`population_prediction`）。路由类工具被过滤 | `[DEPRECATED?]` |
| `analyze_dimension` | `agent/analysis/node.py` | RAG 检索 + KG 查询（**仅 L1**，`node.py:667` 阻断 L2/L3）+ `DataPipeline` 工具执行 + LLM 流式生成 | `[IMPLEMENTED]` |
| `layer_completion_check` | `agent/completion/node.py:20` | 层级完成检测。`step_mode` 走 `interrupt()` 暂停审批；连续模式自动推进下一层 | `[IMPLEMENTED]` |
| `gis_agent` | `agent/graph.py:52` | PARSE ReAct + LAYOUT 混合管线。当前**仅自取 L3 报告**（`graph.py:207`），存在**双重 parse 问题**（`graph.py:97` + `layout_pipeline.py:123`） | `[IMPLEMENTED]` 有缺陷 |

### 边定义

```python
# graph.py:173-181
builder.add_edge(START, "conversation")
builder.add_conditional_edges("conversation", after_conversation,
    {"execute_tools", "analyze_dimension", "gis_agent", END})
builder.add_edge("execute_tools", "conversation")
builder.add_edge("gis_agent", "conversation")
builder.add_edge("analyze_dimension", "layer_completion_check")
builder.add_conditional_edges("layer_completion_check", after_analysis,
    {"analyze_dimension", "conversation", END})
```

## 2. 路由逻辑

### `after_conversation`（`routing.py:27`）

对话后路由，按优先级：

1. **级联修订** — `need_revision` + `feedback` 存在时，计算影响树（`get_impact_tree_compat`），`Send` 分发 Wave 0 目标维度到 `analyze_dimension`（`is_revision=True`）
2. **推进意图** — 检测 `advance_planning_intent` tool_call → `_dispatch_current` 分发当前层维度
3. **GIS 分析** — 检测 `gis_analysis` tool_call → `gis_agent`
4. **其他工具** — 未知 tool_call → `execute_tools`
5. **普通对话** — 无 tool_call → `END`

### `after_analysis`（`routing.py:129`）

分析后路由，三选一：

1. **级联修订模式** — 依赖检查：遍历 `revision_impact_tree` 中未完成维度，检查同层 + 跨层依赖是否就绪，就绪则 `Send` 分发
2. **正常推进** — Wave 调度：当前层依赖已完成的维度 `Send` 分发；**跨层提前分发**（`routing.py:263-287`）—— 下一层中跨层依赖已就绪的维度可提前启动
3. **完成** — 无就绪维度 → `END`

## 3. 目标：6 节点主图（+explore）

当前为 5 节点开环，目标引入 **EXPLORE 桥接节点**形成闭环：

```
START
  │
  ▼
conversation ──► analyze_dimension (L1/L2/L3)
  │                    │
  │                    ▼
  │             layer_completion_check
  │                    │
  │                    ▼ (phase=completed)
  │             ┌──────────┐
  │             │ explore  │  ← 新增：读 L1+L2+L3 全量报告 + KG 交互
  │             │          │     产出概要索引
  │             └────┬─────┘
  │                  ▼
  │             gis_agent (PARSE + LAYOUT)
  │                  │
  │                  ▼
  │             L3 校核轮 (读 L4 对账)
  │                  │
  └──────────────────┘
```

**EXPLORE 提升为主图顶层节点的原因**（详见 [design/05](../design/05_EXPLORE_BRIDGE.md)）：

- 当前 `gis_agent` 仅取 L3 报告（`graph.py:207`），**L1/L2 空间线索丢失**
- EXPLORE 按需读取 L1+L2+L3 全量报告，产出 `ReportSummaryIndex` 供 PARSE 导航
- KG 交互集中在 EXPLORE，PARSE 不直接查 KG，职责清晰
- 闭环：EXECUTE 产出 L4 → L3 校核轮读 L4 做文本/几何一致性校核

## 4. 已知问题

| 问题 | 位置 | 影响 |
|------|------|------|
| 双重 parse | `graph.py:97` + `layout_pipeline.py:123` | PARSE Agent 被执行两次，浪费 LLM 调用 |
| gis_agent 仅取 L3 | `graph.py:207` | L1/L2 空间线索（三区三线、用地分布、村庄分类）丢失 |
| KG 仅 L1 查询 | `analysis/node.py:667` | L2/L3 维度无 KG 认知补充 |
| execute_tools 过渡性 | `execute_node.py:79` | 仅处理 3 个非路由工具，路由类被过滤后转发 |
| 开环无校核轮 | `design/04` 断点⑥ | L3 文本与 L4 几何无一致性校核 |

## 5. 相关文件

```
backend/app/agent/
├── graph.py                 # create_unified_planning_graph() + gis_agent_node
├── routing.py               # after_conversation + after_analysis
├── state.py                 # AgentState, PlanningPhase
├── conversation/node.py     # conversation_node (中央路由)
├── tools/execute_node.py    # execute_tools_node (非路由工具)
├── analysis/
│   ├── node.py              # analyze_dimension (RAG + KG + DataPipeline + LLM)
│   └── pipeline.py          # DataPipeline (统一工具执行)
├── completion/node.py       # layer_completion_check (interrupt / auto-advance)
└── gis/
    ├── agent.py             # create_parse_agent_graph (PARSE ReAct)
    ├── layout_pipeline.py   # build_layout_pipeline (LAYOUT 混合管线)
    ├── parse/               # PARSE Agent 子图
    └── execute/             # EXECUTE Agent 子图
```
