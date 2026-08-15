# LLM 工具绑定设计

> 模块：`backend/app/infrastructure/llm/`（factory / instructor_client / planning_claims / tools）
> 设计 vs 实现差异：[27_IMPLEMENTATION_VS_DESIGN.md](../../27_IMPLEMENTATION_VS_DESIGN.md) §5

| 文档 | 内容 | 状态 |
|---|---|---|
| [17_LLM_TOOL_BINDING.md](17_LLM_TOOL_BINDING.md) | LLM 调用 Binding Tool 的设计与实现边界 | TARGET + CURRENT |

当前事实：conversation 只 bind `advance_planning_intent` / `gis_analysis` 两个路由工具；
access 读型工具已注册（`ToolRegistry`）但未绑定；`execute_node` 走 `ToolRegistry.get_tool`。