# agent/conversation 子包（中央路由节点）

> 主图的"大脑"：LLM 绑定工具解析用户意图，决定推进规划 / GIS 分析 / 调用工具 / 直接回复。
> **Updated: 2026-08-02**

---

## 一、定位

主图 `conversation` 节点。把 `advance_planning_intent` / `gis_analysis` 两个路由工具 + 分析工具（人口预测/知识检索/网络搜索）绑定到 LLM，让模型自主选择推进意图或实际工具调用。

---

## 二、目录结构

```
conversation/
├── __init__.py    # 导出 conversation_node
└── node.py        # ★ 111 行：SYSTEM_TEMPLATE + _get_llm_with_tools + conversation_node
```

---

## 三、实现

- **`SYSTEM_TEMPLATE`**：系统提示（当前阶段/任务/约束 + 可用工具 + 响应规则：用户说"继续规划/下一步"→ `advance_planning_intent`；请求 GIS → `gis_analysis`）。
- **`_get_llm_with_tools`**：模块级缓存的 `LLM.bind_tools([advance_planning_intent, gis_analysis] + get_tools_for_llm())`（`create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)`）。
- **`_build_prompt`**：`ChatPromptTemplate.from_messages([system, MessagesPlaceholder("messages")])`，partial 填充项目/阶段/任务/约束。
- **`conversation_node`**：
  1. 若最后一条消息已携带已知意图 tool_call（`advance_planning_intent` / `gis_analysis` / `GISAnalysis`）→ **旁路 LLM 直接路由**（由 `_trigger_planning_execution` 注入）；
  2. 否则 `prompt | llm_with_tools` 调用；
  3. 返回单个 `AIMessage`（可能带 tool_calls）。

下游 `routing.after_conversation` 依据返回消息的 tool_calls 决定去向。

---

## 四、输入输出契约

```
输入:  state（messages / phase / config）
输出:  {messages: [AIMessage]}（content 或 tool_calls）
```

---

## 五、相关文档

- `../README.md` — 主图与编排
- `../routing.py` — after_conversation 路由
- `app/tools/intent_tools.py` — advance_planning_intent / gis_analysis 定义
- `app/core/llm.py` — LLM 工厂
