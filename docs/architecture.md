# 系统架构文档 (Architecture Overview)

> 最后更新: 2026-04-04
>
> 本文档详细描述前端、后端、Agent 三层的文件结构和依赖关系。

---

## 一、系统分层架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              前端层 (Frontend Layer)                             │
│  技术栈: Next.js 14 + React 18 + TypeScript + TailwindCSS + Framer Motion       │
│  入口: frontend/src/app/page.tsx                                                │
│  状态: UnifiedPlanningContext (聚合 6 个细粒度 Context)                          │
│  通信: SSE 事件流 + REST API                                                     │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                           HTTP/SSE (端口 8000)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              后端层 (Backend Layer)                              │
│  技术栈: FastAPI + SQLModel + SQLite (WAL) + asyncio                            │
│  入口: backend/main.py                                                          │
│  API: /api/planning/*, /api/data/*, /api/files/*, /api/knowledge/*             │
│  SSE: asyncio.Queue 多订阅者事件推送                                             │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                          Python 函数调用
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Agent 层 (Agent Layer)                              │
│  技术栈: LangGraph + LangChain + RAG (ChromaDB)                                 │
│  入口: src/orchestration/main_graph.py                                          │
│  模式: StateGraph + 子图 + 规划器 + 工具系统                                     │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                      SQLite Checkpoint + ChromaDB 向量库
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              存储层 (Storage Layer)                              │
│  数据库: data/village_planning.db (SQLite WAL)                                  │
│  向量库: knowledge_base/chroma_db/                                               │
│  源文档: data/policies/                                                          │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、前端架构详解

### 2.1 目录结构与职责

```
frontend/src/
├── app/                          # Next.js App Router
│   ├── page.tsx                  # 主页面入口 (唯一页面)
│   ├── layout.tsx                # 根布局 (字体、全局样式)
│   └── globals.css               # 全局 CSS (Tailwind 基础样式)
│
├── components/                   # UI 组件
│   ├── layout/                   # 布局组件
│   │   ├── UnifiedLayout.tsx         # 主布局容器 (Header + Content)
│   │   ├── UnifiedContentSwitcher.tsx # 视图切换 (表单/会话)
│   │   ├── Header.tsx                # 顶部导航栏
│   │   ├── HistoryPanel.tsx          # 历史记录侧边栏
│   │   └── KnowledgePanel.tsx        # 知识库面板
│   │
│   ├── chat/                     # 聊天组件 (核心交互区)
│   │   ├── ChatPanel.tsx             # 主聊天容器 (状态聚合)
│   │   ├── MessageList.tsx           # 消息列表渲染
│   │   ├── MessageBubble.tsx         # 消息气泡 (用户/助手样式)
│   │   ├── MessageContent.tsx        # 消息内容分发器
│   │   ├── ChatInputArea.tsx         # 输入框 + 操作按钮
│   │   ├── ChatStatusHeader.tsx      # 状态头部 (进度/暂停)
│   │   ├── ProgressPanel.tsx         # 维度执行进度
│   │   ├── ReviewPanel.tsx           # 审查操作面板
│   │   ├── ToolStatusPanel.tsx       # 工具执行状态
│   │   ├── DimensionReportStreaming.tsx # 流式维度报告
│   │   ├── LayerReportMessage.tsx    # 层级报告消息
│   │   └── hooks/                    # 组件级 Hooks
│   │       ├── useChatInput.ts
│   │       ├── useFileUpload.ts
│   │       └── usePlanningHandlers.ts
│   │
│   ├── layer/                    # 图层组件
│   │   └── LayerSidebar.tsx          # 层级导航侧边栏
│   │
│   ├── report/                   # 报告组件
│   │   └── KnowledgeReference.tsx    # 知识引用展示
│   │
│   └── ui/                       # 基础 UI 组件
│       └── SegmentedControl.tsx      # 分段控制器
│
├── contexts/                     # React Context 状态管理
│   ├── UnifiedPlanningContext.tsx    # 聚合 Context (向后兼容)
│   ├── ConversationContext.tsx       # 对话状态 (messages, taskId)
│   ├── ProgressContext.tsx           # 执行进度 (dimensions, phase)
│   ├── PlanningStateContext.tsx      # 规划状态 (layer, paused)
│   ├── ReportContext.tsx             # 报告状态 (layerReports)
│   ├── HistoryContext.tsx            # 历史记录 (villages, sessions)
│   └── ViewerContext.tsx             # 文档查看器
│
├── controllers/                  # 控制器
│   └── TaskController.tsx            # SSE 连接管理 + 状态同步
│
├── hooks/                        # 全局 Hooks
│   ├── useStreamingRender.ts         # 批量流式渲染
│   ├── useStreamingText.ts           # 打字机效果
│   ├── useToolStatus.ts              # 工具状态管理
│   └── useThrottleCallback.ts        # 节流回调
│
├── lib/                          # 工具库
│   ├── api/                          # API 客户端
│   │   ├── index.ts                      # 统一导出
│   │   ├── client.ts                     # 基础 HTTP 客户端
│   │   ├── types.ts                      # API 类型定义
│   │   ├── planning-api.ts               # 规划 API + SSE
│   │   ├── data-api.ts                   # 数据访问 API
│   │   └── knowledge-api.ts              # 知识库 + 文件上传
│   │
│   ├── utils/                        # 工具函数
│   │   ├── cn.ts                         # 类名合并 (clsx + tailwind-merge)
│   │   ├── message-helpers.ts            # 消息创建工具
│   │   ├── button-styles.ts              # 按钮样式
│   │   └── report-parser.ts              # 报告解析
│   │
│   └── constants.ts                  # 应用常量
│
├── types/                        # TypeScript 类型
│   ├── index.ts                      # 统一导出
│   ├── message.ts                    # 基础消息类型
│   ├── message-types.ts              # 具体消息类型 (8种)
│   ├── message-guards.ts             # 类型守卫函数
│   └── message-helpers.ts            # 消息辅助函数
│
└── config/                       # 配置
    ├── dimensions.ts                 # 维度配置 (名称/图标/层级映射)
    └── planning.ts                   # 规划默认参数
```

### 2.2 前端核心依赖关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                          入口层 (Entry)                             │
├─────────────────────────────────────────────────────────────────────┤
│  page.tsx                                                           │
│      │                                                              │
│      ├── imports → UnifiedPlanningProvider (contexts/)              │
│      │                                                              │
│      └── renders → UnifiedLayout                                    │
│                        │                                            │
│                        └── renders → UnifiedContentSwitcher         │
│                                          │                          │
│                                          ├──→ VillageInputForm      │
│                                          └──→ ChatPanel             │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Context 状态层                                │
├─────────────────────────────────────────────────────────────────────┤
│  UnifiedPlanningContext (聚合层)                                    │
│      │                                                              │
│      ├── useConversationContext() → messages, taskId, status       │
│      ├── useProgressContext()     → dimensionProgress, phase       │
│      ├── usePlanningStateContext()→ currentLayer, isPaused         │
│      ├── useReportContext()       → layerReports                   │
│      ├── useHistoryContext()      → villages, sessions             │
│      └── useViewerContext()       → viewingFile                    │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Controller 控制层                             │
├─────────────────────────────────────────────────────────────────────┤
│  TaskController                                                     │
│      │                                                              │
│      ├── SSE 连接 → planningApi.createStream()                      │
│      │       │                                                      │
│      │       └── 事件分发:                                          │
│      │           ├── onDimensionDelta → useStreamingRender          │
│      │           ├── onLayerCompleted → fetch reports               │
│      │           ├── onToolCall → useToolStatus                     │
│      │           └── onPause → setIsPaused                          │
│      │                                                              │
│      └── REST API → planningApi.getStatus() (断线重连同步)          │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.3 SSE 事件处理流程

```
后端 SSE 事件                          前端处理函数                     状态更新
─────────────────────────────────────────────────────────────────────────────
connected           →    onConnected()           →    setTaskId()
layer_started       →    onLayerStarted()        →    setCurrentLayer()
dimension_delta     →    onDimensionDelta()      →    useStreamingRender.addToken()
                                                              │
                                                              └─→ requestAnimationFrame
                                                                          │
                                                                          └─→ 批量更新
dimension_complete  →    onDimensionComplete()   →    更新 Message 状态
layer_completed     →    onLayerCompleted()       →    REST 获取完整报告
tool_call           →    handleToolCall()         →    useToolStatus
tool_progress       →    handleToolProgress()     →    useToolStatus
tool_result         →    handleToolResult()       →    useToolStatus
pause               →    onPause()                →    setIsPaused(true)
completed           →    onCompleted()            →    setStatus('completed')
error               →    onError()                →    setError()
```

---

## 三、后端架构详解

### 3.1 目录结构与职责

```
backend/
├── main.py                       # FastAPI 应用入口
│                                 # - CORS 配置
│                                 # - 生命周期管理 (启动/关闭)
│                                 # - 路由注册
│                                 # - 全局异常处理
│
├── api/                          # API 路由层
│   ├── planning.py               # 规划任务 API (核心)
│   │                             # - POST /start: 启动规划
│   │                             # - GET /stream/{id}: SSE 流
│   │                             # - POST /review/{id}: 审查操作
│   │                             # - SSE 事件发布函数
│   │
│   ├── data.py                   # 数据访问 API
│   │                             # - GET /villages: 村庄列表
│   │                             # - GET /villages/{name}/layers/{layer}
│   │
│   ├── files.py                  # 文件上传 API
│   │                             # - POST /upload: 解析 Word/PDF
│   │
│   ├── knowledge.py              # 知识库管理 API
│   │                             # - 文档 CRUD
│   │                             # - 同步操作
│   │
│   ├── tool_manager.py           # 工具管理器单例
│   └── validate_config.py        # 启动配置验证
│
├── database/                     # 数据库层
│   ├── engine.py                 # 异步引擎 (SQLite + WAL)
│   ├── models.py                 # SQLModel 数据模型
│   │                             # - PlanningSession
│   │                             # - UISession, UIMessage
│   │                             # - DimensionRevision
│   │
│   └── operations_async.py       # 异步 CRUD 操作
│
├── services/                     # 服务层
│   └── rate_limiter.py           # 限流器 (滑动窗口)
│
├── utils/                        # 工具函数
│   ├── progress_helper.py        # 进度计算
│   └── logging.py                # 日志工具
│
└── schemas.py                    # Pydantic 请求/响应模型
```

### 3.2 后端核心依赖关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                          main.py (入口)                             │
├─────────────────────────────────────────────────────────────────────┤
│  应用初始化                                                          │
│      │                                                              │
│      ├── include_router → /api/planning/*                          │
│      ├── include_router → /api/data/*                              │
│      ├── include_router → /api/files/*                             │
│      └── include_router → /api/knowledge/*                         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       api/planning.py (核心)                        │
├─────────────────────────────────────────────────────────────────────┤
│  POST /start                                                        │
│      │                                                              │
│      ├── rate_limiter.check()                                       │
│      ├── db_ops.create_session()                                    │
│      └── _execute_graph_in_background()                             │
│              │                                                      │
│              └── create_village_planning_graph()                    │
│                          │                                          │
│                          └── graph.astream()                        │
│                                      │                              │
│                                      └── SSE 事件发布               │
│                                              │                      │
│                                              └── append_*_event()  │
│                                                                      │
│  GET /stream/{session_id}                                           │
│      │                                                              │
│      └── subscribe_session() → asyncio.Queue                        │
│              │                                                      │
│              └── StreamingResponse (text/event-stream)              │
│                                                                      │
│  POST /review/{session_id}                                          │
│      │                                                              │
│      └── graph.update_state() (LangGraph Checkpoint)               │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       database/operations_async.py                  │
├─────────────────────────────────────────────────────────────────────┤
│  会话管理                                                            │
│      ├── create_session() → INSERT planning_sessions               │
│      ├── get_session() → SELECT ... WHERE session_id               │
│      └── update_session_status()                                   │
│                                                                      │
│  UI 消息                                                             │
│      ├── create_ui_message()                                        │
│      └── get_ui_messages()                                          │
│                                                                      │
│  维度修订                                                            │
│      ├── create_dimension_revision()                                │
│      └── get_revisions()                                            │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 SSE 事件发布机制

```python
# backend/api/planning.py

# 全局订阅管理
_subscribers: Dict[str, List[asyncio.Queue]] = {}
_events_cache: Dict[str, deque] = {}  # 阅后即焚缓存

def append_dimension_delta_event(session_id, layer, dimension_key, delta, accumulated):
    """发布维度增量事件"""
    event = {
        "type": "dimension_delta",
        "event_id": str(uuid4()),
        "session_id": session_id,
        "layer": layer,
        "dimension_key": dimension_key,
        "delta": delta,
        "accumulated": accumulated,
        "timestamp": datetime.now().isoformat()
    }
    _append_session_event(session_id, event)
    _publish_event_sync(session_id, event)

async def subscribe_session(session_id: str):
    """SSE 订阅"""
    queue = asyncio.Queue()
    _subscribers.setdefault(session_id, []).append(queue)
    try:
        while True:
            event = await queue.get()
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
    finally:
        _subscribers[session_id].remove(queue)
```

---

## 四、Agent 架构详解

### 4.1 目录结构与职责

```
src/
├── agent.py                      # 对外接口 (run_village_planning)
│
├── orchestration/                # 编排层 (LangGraph 主图)
│   ├── main_graph.py             # 主图定义
│   │                             # - VillagePlanningState (TypedDict)
│   │                             # - 节点函数: execute_layer1/2/3_analysis
│   │                             # - SSE辅助: _send_dimension_event, _create_token_callback
│   │                             # - create_village_planning_graph()
│   │
│   ├── state.py                  # 统一状态定义
│   │                             # - PlanningPhase (枚举)
│   │                             # - LAYER_DIMENSIONS, WAVE_DIMENSIONS
│   │                             # - get_layer_dimensions(), get_wave_dimensions()
│   │
│   ├── routing.py                # 路由逻辑 (Send API)
│   │                             # - route_by_phase()
│   │                             # - collect_layer_results()
│   │
│   └── nodes/                    # 节点实现
│       └── dimension_node.py     # 统一维度分析节点
│                                 # - analyze_dimension_node()
│                                 # - create_dimension_state()
│                                 # - DIMENSION_NAMES
│
├── nodes/                        # 节点层
│   ├── base_node.py              # BaseNode, AsyncBaseNode 基类
│   ├── layer_nodes.py            # Layer1AnalysisNode, Layer2ConceptNode...
│   └── tool_nodes.py             # ToolBridgeNode, RevisionNode
│
├── planners/                     # 规划器
│   ├── unified_base_planner.py   # 基类 (LLM 调用 + RAG + 流式)
│   └── generic_planner.py        # 28 维度统一规划器
│                                 # - _execute_tool_hook()
│                                 # - execute()
│
├── tools/                        # 工具系统
│   ├── registry.py               # ToolRegistry (装饰器注册)
│   │                             # - ToolMetadata (用于 bind_tools)
│   │                             # - execute_tool() / execute_tool_structured()
│   │
│   ├── adapters/                 # 适配器层
│   │   ├── __init__.py           # AdapterFactory
│   │   ├── base_adapter.py       # BaseAdapter, AdapterResult
│   │   │                         # ToolExecutionResult, ToolStage
│   │   ├── tool_wrapper.py       # 工具函数包装器
│   │   ├── analysis/             # 分析类适配器
│   │   │   ├── accessibility_adapter.py
│   │   │   └── ...
│   │   └── data_fetch/           # 数据获取适配器
│   │       ├── gis_fetch_adapter.py
│   │       └── ...
│   │
│   └── builtin/                  # 内置工具
│       └── __init__.py           # knowledge_search, web_search
│
├── config/                       # 配置
│   └── dimension_metadata.py     # 28 维度元数据 (权威来源)
│                                 # - DIMENSIONS_METADATA
│                                 # - get_dimension_config(), get_dimension_layer()
│                                 # - get_full_dependency_chain(), get_impact_tree()
│
├── core/                         # 核心模块
│   ├── config.py                 # LLM 模型配置
│   └── llm_factory.py            # LLM 实例工厂 (OpenAI/ZhipuAI)
│
└── rag/                          # RAG 知识检索
    ├── core/                     # RAG 核心
    │   ├── kb_manager.py         # 知识库管理
    │   ├── tools.py              # knowledge_search_tool
    │   └── retriever.py          # 检索器
    │
    └── scripts/                  # 管理脚本
        ├── build_kb_auto.py      # 构建知识库
        └── kb_cli.py             # CLI 工具
```

### 4.2 Agent 核心依赖关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                    orchestration/main_graph.py                      │
├─────────────────────────────────────────────────────────────────────┤
│  create_village_planning_graph()                                    │
│      │                                                              │
│      ├── StateGraph(VillagePlanningState)                          │
│      │                                                              │
│      ├── 节点注册                                                    │
│      │   ├── init_pause → _init_pause_node                         │
│      │   ├── layer1_analysis → execute_layer1_analysis             │
│      │   ├── layer2_concept → execute_layer2_concept               │
│      │   ├── layer3_detail → execute_layer3_detail                 │
│      │   ├── tool_bridge → ToolBridgeNode                          │
│      │   └── generate_final → _generate_final_node                 │
│      │                                                              │
│      ├── 条件路由                                                    │
│      │   ├── route_after_pause                                     │
│      │   ├── route_after_layer1                                    │
│      │   ├── route_after_layer2                                    │
│      │   └── route_after_layer3                                    │
│      │                                                              │
│      └── compile(checkpointer=AsyncSqliteSaver)                    │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  orchestration/nodes/dimension_node.py              │
├─────────────────────────────────────────────────────────────────────┤
│  analyze_dimension_node(state, on_token)                           │
│      │                                                              │
│      ├── 获取维度配置 (从 dimension_metadata.py)                    │
│      │                                                              │
│      ├── 构建 Prompt (_build_dimension_prompt)                     │
│      │                                                              │
│      ├── 调用 LLM (流式/非流式)                                     │
│      │   ├── on_token 回调 → SSE dimension_delta 事件              │
│      │   └── _stream_llm() 或 llm.ainvoke()                        │
│      │                                                              │
│      └── 返回结果 {dimension_key, result, success}                  │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     orchestration/routing.py                        │
├─────────────────────────────────────────────────────────────────────┤
│  route_by_phase(state) → List[Send]                                │
│      │                                                              │
│      ├── Phase=LAYER1 → 12 维度并行 Send                           │
│      │                                                              │
│      ├── Phase=LAYER2 → 波次路由 (Wave 1-4)                        │
│      │                                                              │
│      ├── Phase=LAYER3 → 波次路由 (Wave 1-4)                        │
│      │                                                              │
│      └── Phase=COMPLETED → END                                     │
│                                                                      │
│  collect_layer_results(state)                                       │
│      │                                                              │
│      └── 检查 completed_dimensions，推进 phase                      │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     config/dimension_metadata.py                    │
├─────────────────────────────────────────────────────────────────────┤
│  DIMENSIONS_METADATA: 28 维度完整配置                               │
│      │                                                              │
│      ├── Layer 1 (12): location, socio_economic, villager_wishes...│
│      ├── Layer 2 (4): resource_endowment, planning_positioning...  │
│      └── Layer 3 (12): industry, spatial_structure, project_bank...│
│                                                                      │
│  关键函数:                                                           │
│      ├── get_dimension_config(key) → 维度配置                       │
│      ├── get_dimension_layer(key) → 层级                           │
│      ├── get_full_dependency_chain() → 依赖链 + Wave 计算           │
│      └── get_impact_tree(key) → 影响树 (Revision 级联更新)         │
└─────────────────────────────────────────────────────────────────────┘
│      │       └── AnalyzeDimensionNode                              │
│      │               │                                              │
│      │               └── GenericPlanner.execute()                  │
│      │                                                              │
│      └── Reduce: ReduceAnalysesNode                                │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       planners/generic_planner.py                   │
├─────────────────────────────────────────────────────────────────────┤
│  GenericPlanner.execute(state)                                      │
│      │                                                              │
│      ├── 获取维度配置: get_dimension_config(dimension_key)         │
│      │                                                              │
│      ├── RAG 知识注入: knowledge_preload (可选)                    │
│      │                                                              │
│      ├── 工具执行: _execute_tool_hook() (可选)                     │
│      │       │                                                      │
│      │       └── ToolRegistry.execute_tool()                       │
│      │                                                              │
│      ├── LLM 调用: llm.astream()                                   │
│      │       │                                                      │
│      │       └── 流式回调 → append_dimension_delta_event()         │
│      │                                                              │
│      └── 返回结果                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.3 LangGraph 图结构

#### 主图 (main_graph.py)

```
                                    START
                                      │
                                      ▼
                               ┌─────────────┐
                               │ init_pause  │
                               └─────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
            [need_revision]    [continue]        [pause_after_step]
                    │                 │                 │
                    ▼                 │                 ▼
            ┌─────────────┐           │          ┌─────────────┐
            │tool_bridge  │           │          │  END        │
            └─────────────┘           │          (等待审查)
                    │                 │
                    ▼                 ▼
        ┌───────────────────────────────────────────────┐
        │                                               │
        ▼                                               ▼
┌─────────────────┐                           ┌─────────────────┐
│ layer1_analysis │                           │    END          │
│ (12维并行)      │                           │  (规划完成)     │
└─────────────────┘                           └─────────────────┘
        │
        ├──[layer1_completed]──► layer2_concept
        │                              │
        │                              ├──[layer2_completed]──► layer3_detail
        │                              │                              │
        │                              │                              ├──[layer3_completed]──► generate_final
        │                              │                              │                              │
        │                              │                              │                              └──► END
        │                              │                              │
        │                              │                              └──[need_revision]──► tool_bridge
        │                              │
        │                              └──[need_revision]──► tool_bridge
        │
        └──[need_revision]──► tool_bridge
```

#### 对话图 (conversation_graph.py)

```
START
  │
  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         conversation                                │
│  (conversation_node)                                                │
│      │                                                              │
│      ├── LLM: _get_llm_with_tools() (bind_tools)                   │
│      │                                                              │
│      └── System Prompt: _build_system_prompt()                     │
└─────────────────────────────────────────────────────────────────────┘
  │
  ├──[intent_router]──► tool_execution (有 tool_calls)
  │       │
  │       └── ToolRegistry.execute_tool() → ToolMessage
  │               │
  │               └──► conversation (循环)
  │
  ├──[intent_router]──► planning_step (CONTINUE_PLANNING)
  │       │
  │       └── _handle_layer*_phase()
  │               │
  │               └──► conversation (循环)
  │
  ├──[intent_router]──► answer_question (ASK_QUESTION)
  │       │
  │       └──► conversation (循环)
  │
  └──[intent_router]──► END (规划完成)
```

### 4.4 工具系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                       tools/registry.py                             │
├─────────────────────────────────────────────────────────────────────┤
│  ToolRegistry (类方法)                                              │
│      │                                                              │
│      ├── @register_with_metadata(metadata)                         │
│      │       └── 注册工具 + 元数据                                  │
│      │                                                              │
│      ├── to_langchain_tools() → [StructuredTool, ...]              │
│      │       └── 用于 LLM bind_tools                               │
│      │                                                              │
│      ├── execute_tool(name, context) → str                         │
│      │       └── 传统模式 (返回字符串)                              │
│      │                                                              │
│      └── execute_tool_structured(name, context) → ToolExecutionResult│
│              └── 对话模式 (返回结构化结果)                          │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       tools/adapters/                               │
├─────────────────────────────────────────────────────────────────────┤
│  AdapterFactory                                                     │
│      │                                                              │
│      ├── register_adapter_class(name, AdapterClass)                │
│      │                                                              │
│      └── create_adapter(name, config) → BaseAdapter                │
│                                                                      │
│  BaseAdapter (抽象基类)                                             │
│      │                                                              │
│      ├── is_available: bool                                        │
│      ├── status: AdapterStatus                                     │
│      │                                                              │
│      └── run(**kwargs) → AdapterResult                             │
│              ├── success: bool                                     │
│              ├── data: Dict                                        │
│              ├── error: Optional[str]                              │
│              └── metadata: Dict                                    │
│                                                                      │
│  ToolExecutionResult (对话模式)                                     │
│      │                                                              │
│      ├── tool_name: str                                            │
│      ├── status: "pending" | "running" | "success" | "error"       │
│      ├── stages: List[ToolStage]                                   │
│      ├── data: Dict                                                │
│      ├── display_hints: DisplayHints                               │
│      └── summary: str                                               │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       具体 Adapter 实现                             │
├─────────────────────────────────────────────────────────────────────┤
│  analysis/                          data_fetch/                     │
│  ├── accessibility_adapter.py       ├── gis_fetch_adapter.py        │
│  ├── gis_analysis_adapter.py        ├── poi_adapter.py             │
│  ├── network_adapter.py             ├── wfs_adapter.py             │
│  └── population_adapter.py          └── routing_adapter.py         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 五、跨层数据流

### 5.1 完整请求流程

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 用户操作: 点击"开始规划"                                                          │
└──────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 前端 (ChatInputArea.tsx)                                                         │
│     │                                                                            │
│     └── onClick → planningApi.startPlanning({village_name, step_mode})          │
└──────────────────────────────────────────────────────────────────────────────────┘
        │
        │ HTTP POST /api/planning/start
        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 后端 (planning.py)                                                               │
│     │                                                                            │
│     ├── rate_limiter.check(project_name)                                         │
│     ├── db_ops.create_session(session_id, project_name)                          │
│     ├── checkpointer = get_checkpointer()                                        │
│     ├── graph = create_village_planning_graph(checkpointer)                      │
│     │                                                                            │
│     └── asyncio.create_task(_execute_graph_in_background())                      │
│              │                                                                   │
│              └── async for event in graph.astream(initial_state):               │
│                      │                                                           │
│                      └── publish_event_to_subscribers(event)                     │
└──────────────────────────────────────────────────────────────────────────────────┘
        │
        │ SSE Event: layer_started
        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 前端 (TaskController.tsx)                                                        │
│     │                                                                            │
│     └── onLayerStarted({layer: 1}) → setCurrentLayer(1)                         │
└──────────────────────────────────────────────────────────────────────────────────┘
        │
        │ Agent 执行: AnalyzeDimensionNode
        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Agent (generic_planner.py)                                                       │
│     │                                                                            │
│     ├── llm.astream(prompt)                                                      │
│     │       │                                                                    │
│     │       └── for token in stream:                                            │
│     │               │                                                            │
│     │               └── append_dimension_delta_event(delta)                     │
│     │                                                                            │
│     └── return result                                                            │
└──────────────────────────────────────────────────────────────────────────────────┘
        │
        │ SSE Event: dimension_delta (每 200ms)
        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 前端 (TaskController.tsx → useStreamingRender)                                   │
│     │                                                                            │
│     └── onDimensionDelta({dimension_key, delta})                                │
│              │                                                                   │
│              └── addToken(dimension_key, delta)                                  │
│                      │                                                           │
│                      └── requestAnimationFrame → flushPending()                  │
│                              │                                                   │
│                              └── 批量更新 dimensionContents                      │
└──────────────────────────────────────────────────────────────────────────────────┘
        │
        │ Agent 完成: Layer 1 所有维度
        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Agent (main_graph.py)                                                            │
│     │                                                                            │
│     └── route_after_layer1 → layer2_concept 或 tool_bridge (revision)           │
└──────────────────────────────────────────────────────────────────────────────────┘
        │
        │ SSE Event: layer_completed (step_mode=True)
        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 前端 (TaskController.tsx)                                                        │
│     │                                                                            │
│     └── onLayerCompleted({layer: 1, pause_after_step: true})                    │
│              │                                                                   │
│              └── setIsPaused(true)                                               │
│                      │                                                           │
│                      └── ReviewPanel 显示                                        │
└──────────────────────────────────────────────────────────────────────────────────┘
        │
        │ 用户操作: 点击"通过审查"
        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 前端 (ReviewPanel.tsx)                                                           │
│     │                                                                            │
│     └── onClick → planningApi.approveReview(session_id)                         │
└──────────────────────────────────────────────────────────────────────────────────┘
        │
        │ HTTP POST /api/planning/review/{session_id}
        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 后端 (planning.py)                                                               │
│     │                                                                            │
│     ├── graph.update_state(config, {"approved": True})                          │
│     │                                                                            │
│     └── asyncio.create_task(_execute_graph_in_background())                      │
│              │                                                                   │
│              └── 继续执行 Layer 2                                                │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 状态同步机制

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              状态来源                                             │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  LangGraph Checkpointer (单一真实源)                                             │
│      │                                                                           │
│      ├── current_layer                                                          │
│      ├── layer_1/2/3_completed                                                  │
│      ├── analysis_reports / concept_reports / detail_reports                    │
│      ├── metadata (version, published_layers)                                   │
│      └── pause_after_step                                                       │
│                                                                                  │
│  SQLite planning_sessions (业务元数据)                                           │
│      │                                                                           │
│      ├── status: "running" | "paused" | "completed" | "error"                   │
│      ├── execution_error                                                        │
│      ├── is_executing                                                           │
│      └── stream_state                                                           │
│                                                                                  │
│  前端 Context (派生状态)                                                         │
│      │                                                                           │
│      ├── status (from REST) → isPaused, isCompleted                             │
│      ├── currentLayer (from SSE/REST)                                           │
│      ├── dimensionProgress (from SSE)                                           │
│      └── layerReports (from REST)                                               │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘

同步规则:
1. SSE 事件推送增量更新 (dimension_delta, tool_call)
2. REST 轮询获取完整状态 (每 2s 或断线重连)
3. Checkpoint 是状态的唯一权威来源
4. 前端状态完全由后端同步派生，无独立业务状态
```

---

## 六、关键文件索引

### 6.1 前端关键文件

| 文件 | 职责 | 依赖 |
|------|------|------|
| `app/page.tsx` | 页面入口 | UnifiedPlanningProvider, UnifiedLayout |
| `contexts/UnifiedPlanningContext.tsx` | 聚合 Context | 6 个细粒度 Context |
| `controllers/TaskController.tsx` | SSE 管理 | planningApi, Context setters |
| `components/chat/ChatPanel.tsx` | 主聊天容器 | MessageList, ProgressPanel, ReviewPanel |
| `hooks/useStreamingRender.ts` | 批量渲染 | requestAnimationFrame |
| `lib/api/planning-api.ts` | 规划 API | fetch, EventSource |

### 6.2 后端关键文件

| 文件 | 职责 | 依赖 |
|------|------|------|
| `main.py` | 应用入口 | all routers, database |
| `api/planning.py` | 规划 API | main_graph, db_ops, rate_limiter |
| `database/operations_async.py` | 数据操作 | SQLModel, engine |
| `services/rate_limiter.py` | 限流 | 滑动窗口算法 |

### 6.3 Agent 关键文件

| 文件 | 职责 | 依赖 |
|------|------|------|
| `orchestration/main_graph.py` | 主图编排 | subgraphs, nodes, LangGraph |
| `subgraphs/analysis_subgraph.py` | Layer 1 子图 | GenericPlanner, Send |
| `planners/generic_planner.py` | 统一规划器 | UnifiedPlannerBase, ToolRegistry |
| `tools/registry.py` | 工具注册 | ToolMetadata, adapters |
| `config/dimension_metadata.py` | 维度配置 | DIMENSIONS_METADATA |

---

## 七、扩展指南

### 7.1 添加新维度

1. 在 `src/config/dimension_metadata.py` 添加维度元数据
2. 在 `src/subgraphs/*_prompts.py` 添加提示模板
3. 更新 `frontend/src/config/dimensions.ts`

### 7.2 添加新工具

1. 在 `src/tools/adapters/` 创建 Adapter
2. 在 `src/tools/registry.py` 注册元数据
3. 更新 `TOOL_PARAMETER_SCHEMAS` 和 `TOOL_METADATA_DEFINITIONS`

### 7.3 添加新 SSE 事件

1. 后端: 在 `backend/api/planning.py` 添加 `append_*_event()`
2. 前端: 在 `frontend/src/lib/api/types.ts` 添加事件类型
3. 前端: 在 `TaskController.tsx` 添加处理回调