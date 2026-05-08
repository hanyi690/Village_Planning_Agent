# 文件路径索引

本文档提供关键代码路径的完整索引，按模块分类。

> **更新日期**: 2026-05-08
> **版本**: v2.0 (重组后架构)

**本节是文件路径的唯一来源**，其他文档应引用此表。

---

## Agent核心

| 文件 | 职责 |
|------|------|
| `backend/app/agent/graph.py` | StateGraph定义，节点和边 |
| `backend/app/agent/state.py` | UnifiedPlanningState定义 |
| `backend/app/agent/routing.py` | intent_router, route_by_phase |
| `backend/app/agent/message_builder.py` | 消息构建器 |
| `backend/app/agent/nodes/conversation.py` | conversation_node中央路由节点 |
| `backend/app/agent/nodes/tools.py` | execute_tools节点 |
| `backend/app/agent/nodes/analysis.py` | analyze_dimension维度分析节点 |

---

## 配置层

| 文件 | 职责 |
|------|------|
| `backend/app/config/phases.yaml` | 28维度唯一来源（YAML） |
| `backend/app/config/loader.py` | YAML → Pydantic配置加载器 |
| `backend/app/config/dependency.py` | Wave波次计算、依赖链管理 |
| `backend/app/config/document_types.py` | 维度标签、地形标签、文档类型标签 |

---

## 核心基础设施

| 文件 | 职责 |
|------|------|
| `backend/app/core/settings.py` | 环境变量、路径配置、密钥 |
| `backend/app/core/llm.py` | LLM工厂（OpenAI、ZhipuAI、DeepSeek） |
| `backend/app/core/tracing.py` | LangSmith/LangFuse集成 |
| `backend/app/core/events.py` | SSE事件类型常量 |

---

## 后端API

### 路由

| 文件 | 職责 |
|------|------|
| `backend/app/api/routes.py` | 统一路由入口（7个精简端点） |

### 服务层

| 文件 | 职责 |
|------|------|
| `backend/app/services/sse.py` | SSEManager，事件推送管理 |
| `backend/app/services/runtime.py` | LangGraph运行时服务 |
| `backend/app/services/checkpoint.py` | Checkpoint加载/保存 |
| `backend/app/services/session.py` | 会话管理 |
| `backend/app/services/report_store.py` | 报告存储与版本历史 |

---

## 数据库

| 文件 | 职责 |
|------|------|
| `backend/app/database/engine.py` | SQLite异步引擎、WAL模式、Checkpointer |
| `backend/app/database/models.py` | SQLAlchemy/SQLModel模型定义 |
| `backend/app/database/operations.py` | 异步数据库操作 |

---

## 工具系统

### 注册与管理

| 文件 | 职责 |
|------|------|
| `backend/app/tools/protocol.py` | ToolResult、Tool协议定义 |
| `backend/app/tools/registry.py` | ToolRegistry工具注册中心 |
| `backend/app/tools/adapters/langchain.py` | Tool → LangChain适配器 |

### 分析工具

| 文件 | 职责 |
|------|------|
| `backend/app/tools/analytics/population.py` | 人口预测模型 |
| `backend/app/tools/analytics/knowledge_search.py` | 知识检索工具 |

---

## 领域模块 (modules/)

### GIS模块

| 文件 | 职责 |
|------|------|
| `backend/app/modules/gis/service.py` | GIS业务门面 |
| `backend/app/modules/gis/fetcher.py` | GIS数据获取协调器 |
| `backend/app/modules/gis/fallback.py` | 边界兜底数据 |
| `backend/app/modules/gis/coverage.py` | 覆盖率计算 |
| `backend/app/modules/gis/isochrone.py` | 等时圈分析 |
| `backend/app/modules/gis/providers/amap/` | 高德API封装 |
| `backend/app/modules/gis/providers/tianditu/` | 天地图WFS |
| `backend/app/modules/gis/providers/osm/` | OSM道路数据 |

### RAG模块

| 文件 | 职责 |
|------|------|
| `backend/app/modules/rag/service.py` | RAG检索服务 |
| `backend/app/modules/rag/vector_store.py` | ChromaDB向量存储 |
| `backend/app/modules/rag/knowledge_manager.py` | 文档管理 |
| `backend/app/modules/rag/context.py` | 上下文管理 |

### Prompts模块

| 文件 | 职责 |
|------|------|
| `backend/app/modules/prompts/analysis.py` | Layer1维度分析提示词 |
| `backend/app/modules/prompts/concept.py` | Layer2规划思路提示词 |
| `backend/app/modules/prompts/detailed.py` | Layer3详细规划提示词 |
| `backend/app/modules/prompts/spatial.py` | 空间布局提示词 |

---

## 前端 [搁置]

### 状态管理

| 文件 | 职责 |
|------|------|
| `frontend/src/stores/planningStore.ts` | Zustand状态管理，PlanningState |
| `frontend/src/stores/uiStore.ts` | UI状态(侧边栏、模态框) |

### Hooks

| 文件 | 职责 |
|------|------|
| `frontend/src/hooks/planning/useSSEConnection.ts` | SSE连接和事件处理 |
| `frontend/src/hooks/planning/usePlanningAPI.ts` | API调用封装 |
| `frontend/src/hooks/planning/useDimensionProgress.ts` | 维度进度追踪 |

### 类型定义

| 文件 | 职责 |
|------|------|
| `frontend/src/types/message/message-types.ts` | 消息类型定义 |
| `frontend/src/types/planning/planning-types.ts` | 规划状态类型 |
| `frontend/src/types/sse/sse-events.ts` | SSE事件类型 |

### 组件

| 文件 | 职责 |
|------|------|
| `frontend/src/components/planning/PlanningProvider.tsx` | 规划上下文Provider |
| `frontend/src/components/chat/ChatPanel.tsx` | 对话面板 |
| `frontend/src/components/planning/LayerProgress.tsx` | 层级进度显示 |
| `frontend/src/components/planning/DimensionCard.tsx` | 维度卡片 |

---

## Utils工具

| 文件 | 职责 |
|------|------|
| `backend/app/utils/logger.py` | 日志工具 |
| `backend/app/utils/text_splitter.py` | 文档切片 |
| `backend/app/utils/semantic_tagger.py` | 语义标签 |
| `backend/app/utils/context_manager.py` | 上下文收集 |

---

## 数据目录

| 目录 | 内容 |
|------|------|
| `data/knowledge_base/` | 知识库原始文件 |
| `data/database/` | SQLite数据库文件 |
| `data/chroma_db/` | ChromaDB向量存储 |

---

## 相关文档

- [01-system-overview](./01-system-overview.md) - 系统总览
- [02-agent-core](./02-agent-core.md) - Agent核心架构
- [06-tool-system](./06-tool-system.md) - 工具系统
- [08-rag-system](./08-rag-system.md) - RAG系统
- [terminology](./terminology.md) - 术语定义