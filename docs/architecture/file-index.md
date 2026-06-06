# 文件路径索引

本文档提供关键代码路径的完整索引，按模块分类。

> **更新日期**: 2026-05-21
> **版本**: v3.0 (统一架构)

**本节是文件路径的唯一来源**，其他文档应引用此表。

---

## Agent 核心

| 文件 | 职责 |
|------|------|
| `backend/app/agent/graph.py` | StateGraph 定义，4 节点（conversation, execute_tools, analyze_dimension, layer_completion_check） |
| `backend/app/agent/state.py` | AgentState 定义，Annotated merge 函数 |
| `backend/app/agent/routing.py` | after_conversation, after_analysis 路由逻辑 |
| `backend/app/agent/nodes/conversation.py` | conversation_node 中央路由节点 |
| `backend/app/agent/nodes/tools.py` | execute_tools 节点 |
| `backend/app/agent/nodes/analysis.py` | analyze_dimension 维度分析节点 |
| `backend/app/agent/nodes/completion.py` | layer_completion_check 层级完成检测节点 |
| `backend/app/agent/gis_context.py` | SharedGISContext 上下文管理 |
| `backend/app/agent/message_builder.py` | 多模态消息构建（图片+文本） |

---

## 配置层

| 文件 | 职责 |
|------|------|
| `backend/app/config/phases.yaml` | 28 维度唯一来源（YAML） |
| `backend/app/config/loader.py` | YAML → Pydantic 配置加载器 |
| `backend/app/config/dependency.py` | Wave 波次计算、依赖链管理、影响树 |
| `backend/app/config/document_types.py` | 维度标签、地形标签、文档类型标签 |

---

## 核心基础设施

| 文件 | 职责 |
|------|------|
| `backend/app/core/settings.py` | 环境变量、路径配置、密钥 |
| `backend/app/core/llm.py` | LLM 工厂（OpenAI、ZhipuAI、DeepSeek） |
| `backend/app/core/tracing.py` | LangSmith/LangFuse 集成 |
| `backend/app/core/events.py` | SSE 事件类型常量 |

---

## 后端 API

### 路由

| 文件 | 职责 |
|------|------|
| `backend/app/api/routes.py` | 统一路由入口 |
| `backend/app/api/session_routes.py` | 22个API端点（sessions, stream, sync, feedback, checkpoints, resume, reports, step-mode, export, planning-text等） |
| `backend/app/api/schemas.py` | 请求/响应 Pydantic 模型 |

### 服务层

| 文件 | 职责 |
|------|------|
| `backend/app/services/sse.py` | SSEManager，事件推送管理 |
| `backend/app/services/runtime.py` | LangGraph 运行时服务 |
| `backend/app/services/checkpoint.py` | Checkpoint 加载/保存 |
| `backend/app/services/session.py` | 会话管理 |
| `backend/app/services/report_store.py` | 报告存储与版本历史 |
| `backend/app/services/review.py` | 审批服务（approve/reject/rollback） |

---

## 数据库

| 文件 | 职责 |
|------|------|
| `backend/app/database/engine.py` | SQLite 异步引擎、WAL 模式、AsyncSqliteSaver |
| `backend/app/database/models.py` | SQLModel 模型定义（PlanningSession, UISession, DimensionReport, UploadedFile, PlanningTextDocument） |
| `backend/app/database/operations.py` | 异步数据库操作 |

---

## 工具系统

### 注册与管理

| 文件 | 职责 |
|------|------|
| `backend/app/tools/registry.py` | ToolRegistry 工具注册中心、ToolMetadata、参数 Schema |
| `backend/app/tools/constants.py` | 工具常量定义 |
| `backend/app/tools/protocol.py` | 工具协议/基类定义 |
| `backend/app/tools/types.py` | 工具类型系统 |
| `backend/app/tools/tools.py` | 工具实现 |
| `backend/app/tools/web_review_tool.py` | Web 搜索/审查工具 |
| `backend/app/tools/core/gis_tool_wrappers.py` | GIS 工具包装函数 |

### 分析工具

| 文件 | 职责 |
|------|------|
| `backend/app/tools/analytics/population.py` | 人口预测模型（省级增长率/自回归/综合加权） |
| `backend/app/tools/analytics/knowledge_search.py` | 知识检索工具（knowledge_search, document_overview, chapter_content） |

---

## 服务模块 (services/modules/)

### GIS 模块

| 文件 | 职责 |
|------|------|
| `backend/app/services/modules/gis/service.py` | GisService 业务门面，run_parallel 并行执行 |
| `backend/app/services/modules/gis/fetcher.py` | GISDataFetcher 数据获取协调器 |
| `backend/app/services/modules/gis/coverage.py` | 覆盖率计算 |
| `backend/app/services/modules/gis/accessibility.py` | 可达性分析 |
| `backend/app/services/modules/gis/isochrone.py` | 等时圈分析 |
| `backend/app/services/modules/gis/validators.py` | 数据验证 |
| `backend/app/services/modules/gis/providers/amap/provider.py` | 高德 API 封装（POI、地理编码、路径规划） |
| `backend/app/services/modules/gis/providers/tianditu/provider.py` | 天地图 API 封装 |
| `backend/app/services/modules/gis/providers/tianditu/wfs.py` | 天地图 WFS 服务 |
| `backend/app/services/modules/gis/providers/tianditu/tiles.py` | 天地图瓦片服务 |
| `backend/app/services/modules/gis/providers/tianditu/gd_service.py` | 广东省天地图服务 |
| `backend/app/services/modules/gis/providers/osm/provider.py` | OSM 道路数据获取 |
| `backend/app/services/modules/gis/providers/poi.py` | POI 数据统一接口 |
| `backend/app/services/modules/gis/utils/coord_utils.py` | 坐标转换（GCJ-02 → WGS-84） |

### RAG 模块

| 文件 | 职责 |
|------|------|
| `backend/app/services/modules/rag/service.py` | RagService 检索服务，generate_queries, get_context |
| `backend/app/services/modules/rag/vector_store.py` | HierarchyVectorStore，Small-to-Big 检索，树形索引 |
| `backend/app/services/modules/rag/chunker.py` | HierarchySlicer 层级切片，LLMOutlineCorrector 大纲矫正 |
| `backend/app/services/modules/rag/context.py` | DocumentContextManager 文档上下文管理 |
| `backend/app/services/modules/rag/utils/metadata_extractor.py` | MetadataExtractor 元数据提取 |
| `backend/app/services/modules/rag/utils/document_loader.py` | 文档加载器（MinerU/Docling/MarkItDown） |

### Prompts 模块

| 文件 | 职责 |
|------|------|
| `backend/app/services/modules/prompts/analysis.py` | Layer 1 维度分析提示词 |
| `backend/app/services/modules/prompts/concept.py` | Layer 2 规划思路提示词 |
| `backend/app/services/modules/prompts/detailed.py` | Layer 3 详细规划提示词 |
| `backend/app/services/modules/prompts/spatial.py` | 空间布局提示词 |

### Planning Text 模块

| 文件 | 职责 |
|------|------|
| `backend/app/services/modules/planning_text/generator.py` | 规划文本生成器 |
| `backend/app/services/modules/planning_text/config.py` | 规划文本策略配置 |
| `backend/app/services/modules/planning_text/layer_exporter.py` | 层级导出器 |
| `backend/app/services/modules/planning_text/section_builder.py` | 章节构建器 |
| `backend/app/services/modules/planning_text/content_extractor.py` | 内容提取器 |
| `backend/app/services/modules/planning_text/llm_styler.py` | LLM 润色器 |
| `backend/app/services/modules/planning_text/rag_appender.py` | RAG 内容追加器 |
| `backend/app/services/modules/planning_text/json_exporter.py` | JSON 导出器 |

### Summary 模块

| 文件 | 职责 |
|------|------|
| `backend/app/services/modules/summary/generator.py` | 摘要生成器 |
| `backend/app/services/modules/summary/parser.py` | 摘要解析器 |
| `backend/app/services/modules/summary/schema.py` | 摘要 Schema 定义 |

### Data 模块

| 文件 | 职责 |
|------|------|
| `backend/app/services/modules/data/pipeline.py` | 数据处理管道 |
| `backend/app/services/modules/data/formatters.py` | 数据格式化器 |

---

## 前端

### Feature Module 结构

| 目录 | 职责 |
|------|------|
| `frontend/src/features/planning/api/` | API 客户端和类型定义 |
| `frontend/src/features/planning/components/` | React 组件 |
| `frontend/src/features/planning/config/` | 前端配置 |
| `frontend/src/features/planning/constants/` | 常量定义 |
| `frontend/src/features/planning/hooks/` | React Hooks |
| `frontend/src/features/planning/store/` | Zustand Store |
| `frontend/src/features/planning/types/` | TypeScript 类型 |
| `frontend/src/features/planning/utils/` | 工具函数 |

### 状态管理

| 文件 | 职责 |
|------|------|
| `frontend/src/features/planning/store/planningStore.ts` | Zustand 状态管理，PlanningState |
| `frontend/src/features/planning/store/planning-context.tsx` | React Context 包装 |

### Hooks

| 文件 | 职责 |
|------|------|
| `frontend/src/features/planning/hooks/useSSE.ts` | SSE 连接和事件处理 |
| `frontend/src/features/planning/hooks/useSelectors.ts` | 状态选择器 |
| `frontend/src/features/planning/hooks/useHandlers.ts` | 事件处理器 |
| `frontend/src/features/planning/hooks/useStreaming.ts` | 流式渲染 |
| `frontend/src/features/planning/hooks/useSessionRestore.ts` | 会话恢复 |
| `frontend/src/features/planning/hooks/useApprovalActions.ts` | 审批操作 |

### 类型定义

| 文件 | 职责 |
|------|------|
| `frontend/src/features/planning/types/events.ts` | SSE 事件类型 |
| `frontend/src/features/planning/types/messages.ts` | 消息类型 |
| `frontend/src/features/planning/types/base.ts` | 基础类型 |
| `frontend/src/features/planning/types/guards.ts` | 类型守卫 |

### 组件

| 文件 | 职责 |
|------|------|
| `frontend/src/features/planning/components/Dashboard.tsx` | 主布局容器 |
| `frontend/src/features/planning/components/layout/AppHeader.tsx` | 顶部导航 |
| `frontend/src/features/planning/components/layout/LayerNav.tsx` | 左侧维度导航 |
| `frontend/src/features/planning/components/layout/FocusArea.tsx` | 中央工作区 |
| `frontend/src/features/planning/components/layout/ReportViewer.tsx` | 报告查看器 |
| `frontend/src/features/planning/components/layout/ProcessPanel.tsx` | 右侧处理面板 |
| `frontend/src/features/planning/components/chat/MessageList.tsx` | 消息列表 |
| `frontend/src/features/planning/components/chat/StreamingText.tsx` | 流式文本渲染 |
| `frontend/src/features/planning/components/chat/KnowledgeSliceCard.tsx` | 知识切片卡片 |
| `frontend/src/features/planning/components/gis/MapView.tsx` | 地图渲染 |
| `frontend/src/features/planning/components/settings/SettingsPanel.tsx` | 设置面板 |
| `frontend/src/features/planning/components/PlanningTextViewer.tsx` | 规划文本查看器 |
| `frontend/src/features/planning/components/ExportDialog.tsx` | 导出对话框 |

---

## 数据目录

| 目录 | 内容 |
|------|------|
| `data/RAG_doc/` | 知识库原始文件 |
| `data/RAG_doc/_cache/chroma_db_new/` | ChromaDB 向量存储 |
| `data/RAG_doc/_cache/outline_index/` | 层级索引缓存 |
| `data/database/` | SQLite 数据库文件 |

---

## 相关文档

- [01-system-overview](./01-system-overview.md) - 系统总览
- [02-agent-core](./02-agent-core.md) - Agent 核心架构
- [06-tool-system](./06-tool-system.md) - 工具系统
- [08-rag-system](./08-rag-system.md) - RAG 系统
- [gis-system-architecture](./gis-system-architecture.md) - GIS 系统架构
- [terminology](./terminology.md) - 术语定义
