# agent/conversation_router 子包（中央路由）

> 上游主图的**大脑**：对话节点 + 路由边。把用户消息路由到工具执行 / 维度分析层 / GIS 入口 / END。
> 两文件：`node.py`（conversation_node）+ `edges.py`（after_conversation / after_analysis）。

---

## 职责边界

**做**：`node.conversation_node` 把 `advance_planning_intent` / `gis_analysis` 及分析工具（`population_prediction` / `knowledge_search` / `web_search`）绑定到 LLM，让模型选择"推进意图 / 调工具 / 直接回复"；已知意图 tool_call 直接旁路 LLM（`_trigger_planning_execution` 注入时）。`edges.after_conversation` 处理后路由：级联修订（有 `need_revision` + feedback 时计算影响树并分发 Wave 0）> 推进意图检测（`advance_planning_intent` → `layer_router`；`gis_analysis` → `gis_agent`）> 未知工具 → `execute_tools` > 普通对话 → `END`。`edges.after_analysis` 处理分析后路由：修订分支（依赖检查分发 / 完成则 END）/ 普通分支（同层依赖就绪 + 跨层提前分发 `cross_ready`，`step_mode` 除外）/ 无就绪 → END。

**不做**：不执行任何工具（那是 `tools/execute_node`）；不运行维度分析（那是 `l1_observe` 等 worker）；不实现阶段推进状态机（那是 `bootstrap/phase_machine` / `advance_phase`）。

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 路由函数 | `app/agent/conversation_router/edges.py` | `after_conversation` / `after_analysis`（返回 `str | list[Send]`） |
| 对话节点 | `app/agent/conversation_router/node.py` | `conversation_node`（输入 `AgentState.messages`；输出 `{messages: [AIMessage]}`） |
| 状态 | `app/agent/plan_state/state.py` | `AgentState` |
| 阶段 | `app/agent/bootstrap/phase_machine.py` | `PlanningPhase`、`get_layer_dimensions`、`_phase_to_layer` |
| 意图工具 | `app/tools/intent_tools.py` | `advance_planning_intent` / `gis_analysis` |
| 配置 | `app/config/dependency.py` | `compute_impact_tree` / `get_next_revision_wave` |

## 依赖方向

**可导入**：`app/agent/bootstrap/phase_machine`、`app/agent/plan_state`（只经 `AgentState` 交互）、`app/config`、`app/tools/intent_tools`、`app/tools/tools`（`get_tools_for_llm`）、`langchain_core` / `langgraph`。

**禁止导入**：`app/agent/l1_observe` / `l2_strategize` / `l3_plan` 及各 post-L3 stage 的实现（路由只返回目标节点名，不触碰算法）。

## 禁止行为

- 不得在 `edges.py` 里做 I/O / 调用 LLM（纯路由函数）。
- 不得绕过 `step_mode` 做跨层提前分发（`cross_ready` 必须被 `step_mode` 排除）。
- 不得把路由目标写死（必须读取 `phase` / 工具名动态判定）。
- 已知意图 tool_call 不得重复走 LLM（必须旁路，避免二次判定）。

---

## 相关文档

- `../README.md` — 主图节点表 + 路由（§三）
- `../tools/README.md` — `execute_tools`（`after_conversation` 分发的工具目标）
- `../bootstrap/README.md` — `layer_router` / `advance_phase`（路由下游）
- `app/tools/intent_tools.py` — 意图类工具
