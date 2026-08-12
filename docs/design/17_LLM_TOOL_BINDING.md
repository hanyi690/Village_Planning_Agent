# LLM 调用 Binding Tool 的设计与实现边界

> 本文区分两种状态：
> - `TARGET`：目标设计（蓝图要求的边界，可能尚未实现）
> - `CURRENT`：当前代码实现事实（以 `backend/app/` 为准，含文件引用）
>
> 更新时间：2026-08-12
> 状态：TARGET DESIGN + CURRENT 事实并存
> 当前实现状态台账：[10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md)

## 1. 目的

本文回答一个问题：**当 LLM 需要调用一个绑定（binding）工具时，项目如何实现、当前已实现到哪一步、目标边界是什么。**

工具层的定位在 [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md) 与
[14_BACKEND_MODULE_BLUEPRINT.md](14_BACKEND_MODULE_BLUEPRINT.md) M5/M10 中规定：
**tools 只能是外部能力适配器，不能成为规划算法的第二实现。**

## 2. 设计目标（TARGET）

### 2.1 目标闭环

```text
LLM 决定调用工具
  -> tool_call(name, args) 由 bind_tools 暴露的 schema 约束
  -> 路由（conversation）识别：路由型 / 读型
  -> DispatchPolicy 校验（可选，蓝图 M5）
  -> 执行节点 invoke BaseTool（InjectedState 注入会话上下文）
  -> 统一 make_result / to_tool_message 返回
  -> ToolMessage 回到 LLM 消息流
```

### 2.2 边界规则

- 工具只消费 typed workspace / artifact refs，不读裸 GeoJSON、文件路径或 `latest`。
- 工具不实现规划算法；领域能力必须来自 `domain/`、`spatial/`、`evidence/`。
- 每个工具必须注册到统一 registry（`ToolRegistry`），Agent 通过 scope 绑定。
- 返回必须走 `helpers.py: make_result / to_tool_message` 协议，控制 token 预算。
- 路由型工具（如 `advance_planning_intent`、`gis_analysis`）不进通用执行节点，由路由层直接处理。
- 蓝图 M5 要求：LLM 只能提出 `DispatchProposal`，经 `DispatchPolicy` 校验阶段、工具、父 refs、
  预算、重试与幂等性后，才能成为 `DispatchCommand`（见 `workflow/dispatch.py`）。

### 2.3 目标目录契约（来自蓝图 §2.1）

```text
infrastructure/llm/tools/
├── registry.py        # 唯一注册中心：metadata + executable 双通道
├── helpers.py         # make_result / to_tool_message 统一协议
├── intent_tools.py    # 路由型意图工具
├── access/            # EXPLORE 读路径工具集（scope: "explore"）
└── gis/               # GIS 工具集
```

`workflow/tools/execute_node.py` 是通用工具执行节点；`workflow/conversation/` 负责路由。
`infrastructure/llm/tools/tools.py` 的遗留 `ALL_TOOLS / TOOL_REGISTRY` 不承载新工具。

## 3. 当前实现（CURRENT）

### 3.1 LLM 工厂

`backend/app/core/llm.py`：`create_llm()` 按 provider 构造 LLM。

- MiniMax 走 OpenAI 兼容端点（`_create_minimax_llm`），`base_url = MINIMAX_API_BASE`，
  temperature 夹紧到 `(0.01, 1.0]`，`max_tokens` 上限 8192。
- `LLMProvider.MINIMAX / OPENAI / ZHIPUAI` 由 `LLM_PROVIDER` 环境变量决定。

### 3.2 已绑定工具（CURRENT）

`backend/app/workflow/conversation/node.py:46` `_get_llm_with_tools()`：

```python
llm = create_llm(temperature=0.7, max_tokens=MAX_TOKENS)
bind_list = [advance_planning_intent, gis_analysis]
_llm_with_tools = llm.bind_tools(bind_list)
```

只有两个路由型意图工具被真正 bind 到 LLM：

- `advance_planning_intent`（`intent_tools.py`）→ 推进规划流程
- `gis_analysis`（`intent_tools.py`）→ 触发空间分析

路由在 `workflow/conversation/edges.py` `after_conversation`：

```text
advance_planning_intent -> _dispatch_current（分发维度）
gis_analysis            -> target_projection
其他未知工具            -> execute_tools
```

### 3.3 已注册但未绑定（CURRENT / GAP）

`backend/app/infrastructure/llm/tools/access/` 定义 6 个读路径工具：

- `bundle_overview`、`spatial_context`、`spatial_features`
- `layer_reports`、`knowledge_graph`、`rag_search`

这些工具通过 `access/__init__.py:_register()` 注册到 `ToolRegistry`，`for_agent("explore")`
可返回 `ACCESS_TOOLS`。**但全仓库没有任何节点调用 `llm.bind_tools(ToolRegistry.for_agent("explore"))`**，
即这些工具是"死注册"，不会被任何 LLM 实际绑定调用。

### 3.4 通用执行节点的接线缺口（CURRENT / GAP）

`backend/app/workflow/tools/execute_node.py` 的 `execute_tools_node()`：

- 用 `ToolRegistry.get_tool_info()` 取 SSE 展示元数据（可用）。
- 用 `tools.py: TOOL_REGISTRY`（一个遗留空 dict）取可执行对象 → `base_tool is None` → 抛"工具未注册"。

也就是说：**真正承载 executable 的是 `ToolRegistry` 类的 `_tools` dict，但 execute_node 读的是
`tools.py` 里的空 `TOOL_REGISTRY`**，导致通用执行路径当前无法执行任何 access 工具。
这是迁移遗留（`tools.py` 的 analytics 工具被删除后保留了空壳接口）。

### 3.5 L3 结构化输出（另一条"调用"路径）

`backend/app/infrastructure/llm/planning_claims.py`：`PlanningClaimGenerator` 使用
`with_structured_output(PlanningClaimDraftSet, method="function_calling")`。

MiniMax M2.x 不暴露 `json_schema` response format，故用 function_calling 拿结构化 claims；
这条路径不经工具列表，也不走 execute_tools。

### 3.6 现状小结

| 能力 | 状态 | 说明 |
|---|---|---|
| 意图工具 bind | CURRENT | conversation 节点绑定 2 个路由工具，路由到 dispatch/target_projection |
| access 工具注册 | CURRENT | `ToolRegistry` 可返回 `ACCESS_TOOLS`，元数据可用 |
| access 工具绑定 | GAP | 无节点调用 `bind_tools(for_agent("explore"))` |
| 通用 execute_tools | GAP | execute_node 读取遗留空 `TOOL_REGISTRY`，无法执行注册工具 |
| L3 结构化输出 | CURRENT | `with_structured_output(method="function_calling")` |
| DispatchPolicy 门控工具调用 | GAP | DispatchPolicy 校验 stage 跳转，尚未对 LLM 工具调用闭环 |

## 4. 实现"LLM 调用 binding tool"的落地步骤

要新增一个 LLM 可调用的绑定工具，需要补齐/建立以下闭环（按顺序）：

1. **定义**：在 `intent_tools.py` 或新 `tools/*.py` 写 `@tool(args_schema=PydanticModel)`；
   Pydantic schema 决定 LLM 能传什么参数。
2. **注册**：`ToolRegistry.register(name, tool=tool, ...)`；若走通用执行路径，还需把工具放
   进 execute_node 真正读取的注册表（修复它读 `ToolRegistry.get_tool()`，或填充
   `tools.py` 的 `TOOL_REGISTRY`）。
3. **绑定**：把工具加入 `conversation_node._get_llm_with_tools()` 的 `bind_list`；
   或为某 agent scope 单独建链 `llm.bind_tools(ToolRegistry.for_agent("explore"))`。
4. **路由**：在 `after_conversation` 识别工具名：路由型 → 指定阶段；读型 → `"execute_tools"`。
5. **执行与返回**：`execute_tools_node` 用 `base_tool.ainvoke({**args, "state": state})`
   （InjectedState 注入会话上下文），用 `make_result / to_tool_message` 包 `ToolMessage`，
   保持 `_ROUTING_NAMES` 排除路由工具。
6. **（可选）DispatchPolicy**：蓝图 M5 要求 LLM 只能提 `DispatchProposal`，经
   `DispatchPolicy.authorize()` 校验阶段/父 refs/预算后才成为 `DispatchCommand`。

## 5. 参考

- [14_BACKEND_MODULE_BLUEPRINT.md](14_BACKEND_MODULE_BLUEPRINT.md) — M5 Workflow / M10 Infrastructure
- [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md) — 工具层边界
- [10_IMPLEMENTATION_STATUS.md](10_IMPLEMENTATION_STATUS.md) — 实现状态台账
- [tools 层 README](../../backend/app/infrastructure/llm/tools/README.md) — 当前工具层职责说明
