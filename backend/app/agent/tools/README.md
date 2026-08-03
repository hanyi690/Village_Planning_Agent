# agent/tools 子包（工具执行节点）

> 并行执行非路由工具调用，SSE 推送进度/结果。
> **Updated: 2026-08-02**

---

## 一、定位

主图 `execute_tools` 节点。过滤出路由类工具（`advance_planning_intent` / `gis_analysis`，它们由 `routing.after_conversation` 定向分发），然后并行调用其余注册的 `BaseTool`。

---

## 二、目录结构

```
tools/
├── __init__.py       # 导出 execute_tools_node
└── execute_node.py   # ★ 110 行：_invoke_single + execute_tools_node
```

---

## 三、实现

- **`_normalize_name`**：把 LLM 旧 Prompt 可能输出的 PascalCase 别名（`AdvancePlanningIntent` / `GISAnalysis`）映射回注册的 snake_case。
- **`_ROUTING_NAMES`**：意图类工具集合（执行节点跳过）。
- **`_invoke_single`**：
  1. `ToolRegistry.get_tool_info` → SSE `tool_started`（display_name / description / estimated_time）；
  2. `TOOL_REGISTRY[tool_name].ainvoke({**args, "state": state})`；
  3. 成功 → SSE `tool_status: success` + `ToolMessage`；失败 → SSE `tool_status: error` + `ToolMessage("工具执行失败: ...")`。
- **`execute_tools_node`**：取最后一条消息的 tool_calls，过滤常规工具 → `asyncio.gather` 并行调用 → 返回 `{messages: [ToolMessage...]}`。

---

## 四、输入输出契约

```
输入:  state（messages 最后一条带 tool_calls）
输出:  {messages: [ToolMessage]}（每个常规工具调用一条）
```

---

## 五、相关文档

- `../README.md` — 主图与编排
- `../routing.py` — after_conversation（意图类工具的路由）
- `app/tools/` — 工具定义 / TOOL_REGISTRY / ToolRegistry
- `app/utils/sse_publisher.py` — SSE 推送
