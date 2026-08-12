# Tools 层 — 外部能力适配器

> **定位**：外部能力适配器层——把领域能力封装为 **LangChain `@tool`** 供 Agent 调用。`tools` **只能是外部能力适配器，不能成为规划算法的第二实现**（见 `docs/design/00_SYSTEM_DESIGN.md`：*"应用层可以调用领域层；领域层不能反向导入 Agent、Service、API 或 UI。`tools` 只能是外部能力适配器，不能成为规划算法的第二实现"*）。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：
- 把 `modules/` 领域能力包装为工具调用面（`tools/gis/*`、`tools/access/*`）
- 统一工具返回协议（`helpers.py`：`make_result` / `to_tool_message`）
- 工具注册与元数据（`registry.py`：`register()` / `for_agent()` / `ToolMetadata`）
- 通用业务工具（`tools.py`：人口预测 / 知识检索 / 网络搜索；`intent_tools.py`：推进规划意图 / GIS 分析意图）

**不负责**：
- **不实现规划算法**（所有领域算法在 `modules/`：空间计算 → `spatial_ops`，文本提取 → `parsing`，语义 → `kg`）
- 不做业务编排 / 会话生命周期（那是 `services/`）
- 不反向 import Agent 作为业务依赖

---

## 输入/输出契约

**输出协议**（`helpers.py`）：

```python
make_result(success: bool, data=None, error="") -> dict   # {"success", "data"?, "error"?}
to_tool_message(result, tool_call_id) -> ToolMessage
```

**注册入口**（`registry.py`）：`register(tool)` → `for_agent(scope)` 返回可绑定工具列表；`ToolMetadata` 供 SSE 事件 / UI 渲染。

**子目录**：

| 目录 | 职责 |
|---|---|
| `access/` | EXPLORE 会话统一读路径工具（bundle / knowledge / rag / reports / shared）—— 见 `access/README.md` |
| `gis/` | GIS 工具集（conflict / export / extract / kg / lookup / render / validate）+ 内部子目录 —— 见 `gis/README.md` |

---

## 依赖方向

```
tools/ → modules/*（领域能力）、schema/contracts、app.utils
       → langchain_core.tools / langgraph.prebuilt（@tool / InjectedState / InjectedToolCallId）
   ▲ 被 agent 节点绑定调用（bind_tools）
```

- 允许：`modules`（只读消费领域能力）、`schema/contracts`、`app.utils`、LangChain
- 禁止：反向 import `agent` 作为业务依赖；在工具内实现算法

---

## 禁止行为

- 在 tools 内**重写** `modules/` 已有的规划算法（如内联几何计算、内联冲突检测）
- 让工具层成为第二实现并绕过领域模块（导致逻辑分叉、无法统一修复）
- 工具返回非结构化裸数据给 LLM（应经 `make_result` + token 预算）
- 新增工具不注册到 `registry.py`（Agent 无法绑定）

---

## 相关文档

- `access/README.md` — 读路径工具集
- `gis/README.md` — GIS 工具集与内部子目录
- `docs/design/00_SYSTEM_DESIGN.md` — 工具层边界（tools 只能是外部能力适配器）
