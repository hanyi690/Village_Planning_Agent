# 术语表

本文档提供系统术语定义，确保概念一致性。

> **更新日期**: 2026-07-29（扩展 SSE 事件类型）
> **版本**: v4.0 (LangGraph 1.2 interrupt/resume)

## 目录

- [会话与状态](#会话与状态)
- [层级与维度](#层级与维度)
- [SSE事件类型](#sse事件类型)
- [Agent架构](#agent架构)
- [前端状态](#前端状态)
- [工具系统](#工具系统)

---

## 会话与状态

| 术语 | 英文 | 定义 | 相关文档 |
|------|------|------|----------|
| Session | Session | 一次完整的规划会话，由唯一 session_id 标识 | [04-backend-api](./04-backend-api.md) |
| Checkpoint | Checkpoint | LangGraph 的状态快照，用于持久化和恢复 | [02-agent-core](./02-agent-core.md) |
| Phase | Phase | 规划阶段：init、layer1、layer2、layer3、completed | [02-agent-core](./02-agent-core.md) |
| SSOT | Single Source of Truth | Checkpoint 作为状态的唯一真实来源 | [01-system-overview](./01-system-overview.md) |

---

## 层级与维度

| 术语 | 英文 | 定义 | 相关文档 |
|------|------|------|----------|
| Layer | Layer | 规划层级：Layer 1(现状)、Layer 2(思路)、Layer 3(详细) | [03-layer-dimension](./03-layer-dimension.md) |
| Dimension | Dimension | 分析维度，每层级包含多个维度 | [03-layer-dimension](./03-layer-dimension.md) |
| Wave | Wave | 执行波次，同层依赖按Wave顺序执行 | [03-layer-dimension](./03-layer-dimension.md) |
| Report | Report | 维度分析结果，存储在 reports 状态 | [02-agent-core](./02-agent-core.md) |

---

## SSE事件类型

**本节是SSE事件类型的唯一来源**，其他文档应引用此表。

### 规划进度事件

| 事件类型 | 说明 | 数据字段 |
|----------|------|----------|
| `layer_started` | 层级开始执行 | `{layer, total_dimensions}` |
| `layer_completed` | 层级执行完成 | `{layer, reports}` |
| `dimension_start` | 维度开始分析 | `{dimension_key, layer, wave}` |
| `dimension_delta` | 维度内容增量(流式) | `{dimension_key, delta, seq}` |
| `dimension_complete` | 维度分析完成 | `{dimension_key, report, wave}` |

### 工具执行事件

| 事件类型 | 说明 | 数据字段 |
|----------|------|----------|
| `tool_call` | 工具开始执行 | `{tool_name, call_id, args}` |
| `tool_progress` | 工具执行进度 | `{call_id, progress, message}` |
| `tool_result` | 工具执行结果 | `{call_id, result, success}` |

### 状态变更事件

| 事件类型 | 说明 | 数据字段 |
|----------|------|----------|
| `phase_changed` | 阶段变更 | `{phase, previous_phase}` |
| `status_update` | 状态更新 | `{status, message}` |
| `checkpoint_saved` | 检查点保存 | `{checkpoint_id, thread_id}` |

### 用户交互事件

| 事件类型 | 说明 | 数据字段 |
|----------|------|----------|
| `user_message` | 用户消息 | `{content, role}` |
| `assistant_message` | 助手消息 | `{content, role}` |
| `review_required` | 需要审查 | `{layer, pending_action}` |
| `review_result` | 审查结果 | `{action, layer}` |

### 扩展事件类型（来自前端 SSE 实现）

| 事件类型 | 说明 | 数据字段 |
|----------|------|----------|
| `dimension_delta` | 维度内容增量（流式） | `{dimension_key, delta, seq}` |
| `dimension_revised` | 维度修订完成 | `{dimension_key}` |
| `dimension_reset` | 维度重置开始 | `{dimension_key}` |
| `dimension_reset_complete` | 维度重置完成 | `{dimension_key}` |
| `dimension_error` | 维度分析错误 | `{dimension_key, error}` |
| `thinking_start` | 思考开始 | `{}` |
| `thinking` | 思考中 | `{content}` |
| `thinking_end` | 思考结束 | `{}` |
| `stream_paused` | 流暂停 | `{}` |
| `review_request` | 审查请求 | `{layer}` |
| `rag_query` | RAG 查询 | `{query}` |
| `rag_result` | RAG 结果 | `{results}` |
| `rag_config_updated` | RAG 配置更新 | `{config}` |
| `cascade_impact` | 级联影响 | `{dimensions}` |
| `cascade_complete` | 级联完成 | `{}` |
| `execution_resumed` | 执行恢复 | `{}` |
| `revision_completed` | 修订完成 | `{}` |
| `layer_paused` | 层级暂停 | `{layer}` |
| `gis_result` | GIS 结果 | `{result}` |
| `gis_layer_update` | GIS 图层更新 | `{layers}` |
| `text_chunk` | 文本块 | `{content}` |
| `content_delta` | 内容增量 | `{content}` |
| `ai_response_delta` | AI 响应增量 | `{content}` |
| `ai_response_complete` | AI 响应完成 | `{}` |

> **注意**：扩展事件类型以 `frontend/src/features/planning/types/events.ts` 的实际定义为准，此处仅作速查。

---

## Agent架构

| 术语 | 英文 | 定义 | 相关文档 |
|------|------|------|----------|
| Router Agent | Router Agent | 中央路由模式，conversation_node作为路由中心 | [02-agent-core](./02-agent-core.md) |
| StateGraph | StateGraph | LangGraph状态图，定义节点和边 | [02-agent-core](./02-agent-core.md) |
| Send API | Send API | LangGraph并行分发机制 | [02-agent-core](./02-agent-core.md) |
| Intent Router | Intent Router | 意图路由，根据LLM响应决定下一步 | [02-agent-core](./02-agent-core.md) |
| interrupt() | interrupt | LangGraph 官方 human-in-the-loop 暂停机制 | [02-agent-core](./02-agent-core.md) |
| Command(resume) | Command(resume) | LangGraph 恢复 interrupt 的官方 API | [02-agent-core](./02-agent-core.md) |

---

## 前端状态

| 术语 | 英文 | 定义 | 相关文档 |
|------|------|------|----------|
| Zustand | Zustand | React状态管理库，配合Immer实现不可变更新 | [05-frontend-state](./05-frontend-state.md) |
| PlanningState | PlanningState | 前端状态接口，包含所有规划相关状态 | [05-frontend-state](./05-frontend-state.md) |
| interruptInfo | Interrupt Info | interrupt 暂停信息对象（替代 pause_after_step/execution_paused） | [05-frontend-state](./05-frontend-state.md) |
| deriveUIState | Derive UI State | 从核心状态派生UI状态的函数 | [05-frontend-state](./05-frontend-state.md) |
| Signal-Fetch | Signal-Fetch | SSE发信号、REST API获取完整数据的模式 | [05-frontend-state](./05-frontend-state.md) |

---

## 工具系统

| 术语 | 英文 | 定义 | 相关文档 |
|------|------|------|----------|
| ToolRegistry | Tool Registry | 工具注册中心，管理工具函数和元数据 | [06-tool-system](./06-tool-system.md) |
| ToolMetadata | Tool Metadata | 工具元数据：名称、描述、参数Schema | [06-tool-system](./06-tool-system.md) |
| RAG | Retrieval-Augmented Generation | 检索增强生成，知识检索工具的核心技术 | [08-rag-system](./08-rag-system.md) |

---

## 命名约定

### 代码命名

| 类型 | 命名约定 | 示例 |
|------|----------|------|
| 维度键 | snake_case | `socio_economic`, `land_use_planning` |
| 工具名称 | snake_case | `knowledge_search`, `accessibility_analysis` |
| SSE事件类型 | snake_case | `dimension_start`, `layer_completed` |
| 状态字段 | snake_case | `previous_layer`, `step_mode`, `interrupt_info` |
| 函数名 | snake_case | `analyze_dimension`, `collect_layer_results` |
| 类名 | PascalCase | `ToolRegistry`, `SSEManager` |
| 接口名 | PascalCase | `PlanningState`, `ToolMetadata` |

### 文件命名

| 类型 | 命名约定 | 示例 |
|------|----------|------|
| Python模块 | snake_case | `dimension_metadata.py`, `sse_publisher.py` |
| TS组件 | PascalCase | `PlanningProvider.tsx` |
| TS Hook | camelCase + use前缀 | `useSSEConnection.ts` |
| 文档 | kebab-case | `layer-dimension-dataflow.md` |

---

## API端点速查

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/sessions` | POST | 创建会话 |
| `/api/sessions/{id}/stream` | GET | SSE 事件流 |
| `/api/sessions/{id}/sync` | GET | 断线重连同步 |
| `/api/sessions/{id}/feedback` | POST | 反馈/审批 |
| `/api/sessions/{id}/checkpoints` | GET | 检查点列表 |
| `/api/sessions/{id}/resume/{cp}` | POST | 恢复执行 |
| `/api/sessions/{id}/reports/{dim}` | GET | 报告全文 |

---

## 相关文档

- [01-system-overview](./01-system-overview.md) - 系统总览
- [02-agent-core](./02-agent-core.md) - Agent核心
- [03-layer-dimension](./03-layer-dimension.md) - 维度配置
- [04-backend-api](./04-backend-api.md) - 后端API
- [file-index](./file-index.md) - 文件路径索引