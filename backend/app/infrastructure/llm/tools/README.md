# infrastructure/llm/tools 工具适配

> 本 README 以 `backend/app/infrastructure/llm/tools/` 实际代码为准（核验日期 2026-08-15）。
> 旧文档中的 `modules/*`、`tools/gis/*`（顶层）路径已不存在；工具已收敛到本包。

## 定位

LLM 可调用工具的外部能力适配器：把领域能力封装为 LangChain/LangGraph 工具，供
conversation 节点 `bind_tools` 与 `workflow/tools/execute_node.py` 执行。工具只做外部
能力适配，不实现规划算法。

## 文件职责

| 文件/目录 | 职责 |
|---|---|
| `registry.py` | `ToolRegistry` + `ToolMetadata`：工具注册、元数据与查找（`get_tool_info`/`get_tool`） |
| `tools.py` | `get_tools_for_llm`：返回可绑定工具列表 |
| `helpers.py` | `make_result` / `to_tool_message`：统一工具返回协议 |
| `intent_tools.py` | 规划意图工具（`advance_planning_intent`、`gis_analysis`）与路由名 |
| `access/` | 会话统一读路径工具：`bundle`/`knowledge`/`rag`/`reports`/`shared` |

## 与 execute_node 的关系

`workflow/tools/execute_node.py` 通过 `ToolRegistry.get_tool_info/get_tool` 解析工具名并
执行；`_ROUTING_NAMES` 中的 `advance_planning_intent`/`gis_analysis` 由路由节点处理，
其余工具在此执行并回写 ToolMessage。

## 边界规则

- 工具内不重写 `domain/`/`spatial/` 已有算法（几何、冲突检测、分类等）。
- 工具返回必须走 `make_result` + token 预算，不给 LLM 裸大数据。
- 不反向 import 上层作为业务依赖。