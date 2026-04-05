# 系统架构文档 (Architecture Overview)

> 最后更新: 2026-04-05
>
> 本文档详细描述前端、后端、Agent 三层的文件结构和依赖关系。

---

## 一、系统分层架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              前端层 (Frontend Layer)                             │
│  技术栈: Next.js 14 + React 18 + Zustand + Immer + TailwindCSS                  │
│  入口: frontend/src/app/page.tsx                                                │
│  状态: Zustand Store (planningStore.ts) + 粒度选择器                             │
│  通信: SSE 事件流 (批量处理) + REST API                                          │
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
│  服务: planning_service, sse_manager, checkpoint_service, session_service       │
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
├── stores/                       # ⭐ Zustand 状态管理 (新架构)
│   ├── index.ts                  # 导出入口
│   ├── planningStore.ts          # 单一状态源 (Immer middleware)
│   └── planning-context.tsx      # Provider 包装层
│
├── hooks/                        # ⭐ Hooks 目录重构
│   ├── index.ts                  # 总导出入口
│   ├── planning/                 # 规划相关 hooks
│   │   ├── index.ts
│   │   ├── usePlanningHandlers.ts    # 规划操作 (start, approve, reject)
│   │   ├── usePlanningSelectors.ts   # 粒度选择器 (性能优化)
│   │   ├── useReviewActions.ts       # 审查操作封装
│   │   ├── useMessagePersistence.ts  # 消息自动持久化
│   │   ├── useSSEConnection.ts       # SSE 连接 (批量 + 重连)
│   │   └── useSessionRestore.ts      # 会话恢复
│   ├── ui/                       # UI 相关 hooks
│   │   ├── index.ts
│   │   └── useStreamingText.ts       # 流式文本动画
│   └── utils/                    # 工具 hooks
│   │   ├── index.ts
│   │   ├── useStreamingRender.ts     # 批处理渲染 (RAF)
│   │   └── useThrottleCallback.ts    # 防抖节流
│
├── components/                   # UI 组件
│   ├── layout/                   # 布局组件
│   │   ├── UnifiedLayout.tsx         # 主布局容器
│   │   ├── UnifiedContentSwitcher.tsx # 视图切换
│   │   ├── Header.tsx                # 顶部导航栏
│   │   ├── HistoryPanel.tsx          # 历史记录侧边栏
│   │   └── KnowledgePanel.tsx        # 知识库面板
│   │
│   ├── chat/                     # 聊天组件
│   │   ├── ChatPanel.tsx             # 主聊天容器
│   │   ├── MessageList.tsx           # 消息列表渲染
│   │   ├── MessageBubble.tsx         # 消息气泡
│   │   ├── MessageContent.tsx        # 消息内容分发器
│   │   ├── StreamingText.tsx         # 流式文本
│   │   ├── ThinkingIndicator.tsx     # 思考指示器
│   │   ├── ProgressPanel.tsx         # 维度执行进度
│   │   ├── ReviewPanel.tsx           # 审查操作面板
│   │   ├── ToolStatusPanel.tsx       # 工具执行状态
│   │   ├── DimensionReportStreaming.tsx # 流式维度报告
│   │   ├── LayerReportMessage.tsx    # 层级报告消息
│   │   ├── DimensionSelector.tsx     # 维度选择器
│   │   ├── CheckpointMarker.tsx      # 检查点标记
│   │   └── FileViewerSidebar.tsx     # 文件查看侧边栏
│   │
│   ├── layer/                    # 图层组件
│   │   └── LayerSidebar.tsx          # 层级导航侧边栏
│   │
│   ├── report/                   # 报告组件
│   │   └── KnowledgeReference.tsx    # 知识引用展示
│   │
│   └── ui/                       # 基础 UI 组件
│       ├── Card.tsx                  # 卡片组件
│       └── SegmentedControl.tsx      # 分段控制器
│
├── lib/                          # 工具库
│   ├── api/                          # API 客户端
│   │   ├── index.ts                  # 统一导出
│   │   ├── planning-api.ts           # 规划 API + SSE
│   │   ├── data-api.ts               # 数据访问 API
│   │   └── types.ts                  # API 类型定义
│   │
│   ├── utils/                        # 工具函数
│   │   ├── index.ts                  # 统一导出
│   │   └── message-helpers.ts        # 消息创建工具
│   │
│   ├── logger.ts                     # 日志工具
│   └── constants.ts                  # 应用常量
│
├── types/                        # ⭐ TypeScript 类型重构
│   ├── index.ts                      # 统一导出
│   └── message/                      # 消息类型模块
│       ├── index.ts                  # Message 联合类型
│       ├── message-types.ts          # 具体消息类型 (8种)
│       ├── message-guards.ts         # 类型守卫函数
│       └── message-helpers.ts        # 消息辅助函数
│
└── config/                       # 配置
    ├── dimensions.ts                 # 维度配置 (28维度)
    └── planning.ts                   # 规划默认参数
```

### 2.2 Zustand 状态管理架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Provider Layer                              │
├─────────────────────────────────────────────────────────────────────┤
│  PlanningProvider (planning-context.tsx)                            │
│      │                                                              │
│      ├── usePlanningStore() → Zustand 状态                          │
│      ├── useSSEConnection() → SSE 连接管理                          │
│      ├── useMessagePersistence() → 消息自动保存                      │
│      └── useSessionRestore() → 会话恢复                              │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Zustand Store                               │
├─────────────────────────────────────────────────────────────────────┤
│  planningStore.ts (Immer middleware)                                │
│      │                                                              │
│      ├── State: taskId, status, messages, reports, progress...      │
│      │                                                              │
│      ├── Actions:                                                   │
│      │   ├── setTaskId(), setStatus(), addMessage()                 │
│      │   ├── handleSSEEvent() → SSE 事件处理器                       │
│      │   ├── syncBackendState() → REST 状态同步                      │
│      │   └──────────────────────────────────────────────            │
│      │                                                              │
│      └── Selectors (粒度选择器):                                     │
│          ├── useMessages() → Message[]                              │
│          ├── useStatus() → Status                                   │
│          ├── useIsPaused() → boolean                                │
│          ├── useDimensionProgressAll() → Record<string, Progress>   │
│          └──────────────────────────────────────────────            │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.3 SSE 事件处理流程 (批量优化)

```
后端 SSE 事件                          前端处理函数                     状态更新
─────────────────────────────────────────────────────────────────────────────
connected           →    onConnected()           →    setTaskId()
layer_started       →    onLayerStarted()        →    setCurrentLayer()
dimension_delta     →    批量队列 (50ms 窗口)     →    合并后 handleSSEEvent()
dimension_complete  →    onDimensionComplete()   →    updateDimensionProgress()
layer_completed     →    onLayerCompleted()      →    setCompletedLayer()
tool_call           →    onToolCall()            →    addToolStatus()
tool_progress       →    onToolProgress()        →    updateToolStatus()
tool_result         →    onToolResult()          →    finalizeToolStatus()
pause               →    onPause()               →    setIsPaused(true)
stream_paused       →    onStreamPaused()        →    关闭 SSE 连接
error               →    onError()               →    重连 (指数退避)
```

### 2.4 粒度选择器使用示例

```typescript
// ❌ Bad - 整个状态订阅，任何变化都会重渲染
const store = usePlanningStore();
const messages = store.messages;

// ✅ Good - 粒度选择器，只在 messages 变化时重渲染
const messages = useMessages();

// ✅ Good - 组合选择器
const { taskId, status, isPaused } = usePlanningSelectors();
```

---

## 三、后端架构详解

### 3.1 目录结构与职责

```
backend/
├── main.py                      # FastAPI 入口
│   ├── app = FastAPI()
│   ├── CORS 配置
│   └── Router 注册: planning, data, files, knowledge
│
├── api/                         # API 路由层
│   ├── routes.py                # 路由注册
│   ├── planning.py              # 规划 API (核心)
│   │   ├── POST /start          → 启动规划
│   │   ├── GET  /stream         → SSE 事件流
│   │   ├── GET  /status         → 状态查询
│   │   ├── GET  /layers/{layer} → 层级报告
│   │   ├── POST /review         → 批准/驳回/回滚
│   │   └── DEL  /sessions/{id}  → 删除会话
│   │
│   ├── data.py                  # 数据访问 API
│   │   ├── GET /villages        → 村庄列表
│   │   ├── GET /checkpoints     → 检查点列表
│   │   └── GET /layer-content   → 层级内容
│   │
│   ├── files.py                 # 文件管理 API
│   │   ├── POST /upload         → 上传文件
│   │   └── GET  /files/{id}     → 获取文件
│   │
│   ├── knowledge.py             # 知识库 API
│   │   ├── GET /documents       → 文档列表
│   │   └── POST /documents      → 添加文档
│   │
│   ├── tool_manager.py          # 工具管理 API
│   └── validate_config.py       # 配置验证
│
├── services/                    # 服务层 (业务逻辑)
│   ├── planning_service.py      # 规划执行服务
│   │   ├── run_planning_graph() → 执行 LangGraph
│   │   ├── stream_planning_events() → SSE 事件生成
│   │   └── get_layer_reports() → 获取层级报告
│   │
│   ├── sse_manager.py           # SSE 事件管理
│   │   ├── SSEPublisher         → 事件发布器
│   │   ├── EventQueue           → asyncio.Queue
│   │   └── subscribe()          → 订阅事件流
│   │
│   ├── checkpoint_service.py    # 检查点服务
│   │   ├── get_checkpoints()    → 获取检查点列表
│   │   ├── rollback_checkpoint() → 回滚检查点
│   │   └── get_checkpoint_state() → 获取状态
│   │
│   ├── session_service.py       # 会话管理服务
│   │   ├── create_session()     → 创建会话
│   │   ├── delete_session()     → 删除会话
│   │   └── list_sessions()      → 会话列表
│   │
│   ├── review_service.py        # 审查服务
│   │   ├── approve_review()     → 批准
│   │   └── reject_review()      → 驳回
│   │
│   └── rate_limiter.py          # API 限流
│
├── database/                    # 数据库层
│   ├── operations_async.py      # 异步数据库操作
│   │   ├── save_message()       → 保存消息
│   │   ├── load_messages()      → 加载消息
│   │   ├── save_checkpoint()    → 保存检查点
│   │   └── get_session_state()  → 获取会话状态
│   │
│   ├── models.py                # SQLModel 模型
│   │   ├── Session              → 会话表
│   │   ├── Message              → 消息表
│   │   ├── Checkpoint           → 检查点表
│   │   └── LayerReport          → 层级报告表
│   │
│   └── connection.py            # 数据库连接
│
└── utils/                       # 工具函数
    ├── logger.py                # 日志工具
    └── exceptions.py            # 异常定义
```

### 3.2 后端核心依赖关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                          API 路由层                                  │
├─────────────────────────────────────────────────────────────────────┤
│  planning.py                                                        │
│      │                                                              │
│      ├── POST /start → planning_service.run_planning_graph()        │
│      │                                                              │
│      ├── GET /stream → sse_manager.subscribe()                      │
│      │       │                                                      │
│      │       └── EventSourceResponse (SSE 流)                       │
│      │                                                              │
│      ├── GET /status → checkpoint_service.get_checkpoint_state()    │
│      │                                                              │
│      └── POST /review → review_service.approve/reject()             │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          服务层                                      │
├─────────────────────────────────────────────────────────────────────┤
│  planning_service.py                                                │
│      │                                                              │
│      ├── run_planning_graph()                                       │
│      │       │                                                      │
│      │       └── src/orchestration/main_graph.py                    │
│      │               │                                              │
│      │               └── LangGraph StateGraph.ainvoke()             │
│      │                                                              │
│      └── stream_planning_events()                                   │
│              │                                                      │
│              └── sse_manager.publish_event()                         │
│                      │                                              │
│                      └── asyncio.Queue.put()                        │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Agent 层                                    │
├─────────────────────────────────────────────────────────────────────┤
│  src/orchestration/main_graph.py                                    │
│      │                                                              │
│      ├── create_village_planning_graph()                            │
│      │       │                                                      │
│      │       └── StateGraph(VillagePlanningState)                   │
│      │               │                                              │
│      │               ├── Nodes: init_pause, layer1, layer2, layer3  │
│      │               └── Edges: START → init_pause → ... → END      │
│      │                                                              │
│      └── checkpointer → SQLiteSaver (持久化)                        │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 SSE 事件管理

```python
# sse_manager.py
class SSEPublisher:
    """SSE 事件发布器"""

    def __init__(self):
        self._subscribers: Dict[str, asyncio.Queue] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue:
        """订阅事件流"""
        queue = asyncio.Queue()
        self._subscribers[session_id] = queue
        return queue

    def publish_event(self, session_id: str, event: SSEEvent):
        """发布事件"""
        if session_id in self._subscribers:
            self._subscribers[session_id].put_nowait(event)

    def unsubscribe(self, session_id: str):
        """取消订阅"""
        self._subscribers.pop(session_id, None)
```

---

## 四、Agent 架构详解

参见 [agent.md](agent.md) 获取完整 Agent 架构文档。

### 4.1 核心模块

```
src/
├── agent.py                    # 对外接口
│   ├── run_village_planning()  → 完整规划
│   ├── run_analysis_only()     → 仅 Layer 1
│   └── run_concept_only()      → 仅 Layer 1 + 2
│
├── orchestration/              # 编排层
│   ├── main_graph.py           # 主图编排
│   ├── state.py                # 状态定义
│   ├── routing.py              # 路由逻辑
│   └── nodes/
│       ├── dimension_node.py   # 统一维度分析节点
│       └── revision_node.py    # 维度修复节点
│
├── subgraphs/                  # 子图模块
│   ├── analysis_prompts.py     # Layer 1 提示词 (12维度)
│   ├── concept_prompts.py      # Layer 2 提示词 (4维度)
│   └── detailed_plan_prompts.py # Layer 3 提示词 (12维度)
│
├── planners/                   # 规划器层
│   ├── generic_planner.py      # 通用规划器 (28维度)
│   └── unified_base_planner.py # 规划器基类
│
├── tools/                      # 工具系统
│   ├── registry.py             # 工具注册表
│   ├── tools.py                # 工具定义
│   └── project_extractor.py    # 项目提取工具
│
├── rag/                        # RAG 知识检索
│   ├── core/tools.py           # knowledge_search_tool
│   └── metadata/               # 元数据模块
│
└── core/                       # 核心配置
    ├── config.py               # 全局配置
    └── llm_factory.py          # LLM 工厂
```

---

## 五、数据流转

参见 [data-flow-architecture.md](data-flow-architecture.md) 获取完整数据流转文档。

### 5.1 状态同步机制

```
┌─────────────────────────────────────────────────────────────────────┐
│                      后端 LangGraph Checkpoint                       │
│  (SQLiteSaver 持久化)                                               │
│      │                                                              │
│      ├── status: 'paused'                                           │
│      ├── previous_layer: 1                                          │
│      ├── layer_1_completed: true                                    │
│      ├── version: 102                                               │
│      └──────────────────────────────────────────────                │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      前端 Zustand Store                              │
│  (Immer middleware)                                                 │
│      │                                                              │
│      ├── isPaused: true (派生自 status)                             │
│      ├── pendingReviewLayer: 1 (派生自 previous_layer)              │
│      ├── completedLayers: {1: true, 2: false, 3: false}             │
│      └──────────────────────────────────────────────                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 六、关键文件索引

### 前端关键文件

| 文件 | 功能 |
|------|------|
| `stores/planningStore.ts` | Zustand Store (单一状态源) |
| `stores/planning-context.tsx` | Provider 包装层 |
| `hooks/planning/usePlanningSelectors.ts` | 粒度选择器 |
| `hooks/planning/useSSEConnection.ts` | SSE 连接管理 |
| `hooks/planning/useMessagePersistence.ts` | 消息持久化 |
| `hooks/planning/useSessionRestore.ts` | 会话恢复 |
| `lib/api/planning-api.ts` | Planning API |
| `config/dimensions.ts` | 28维度配置 |
| `types/message/index.ts` | Message 联合类型 |
| `components/chat/ChatPanel.tsx` | 主聊天容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/chat/ToolStatusPanel.tsx` | 工具状态 |

### 后端关键文件

| 文件 | 功能 |
|------|------|
| `backend/api/planning.py` | 规划 API 路由 |
| `backend/services/planning_service.py` | 规划执行服务 |
| `backend/services/sse_manager.py` | SSE 事件管理 |
| `backend/services/checkpoint_service.py` | 检查点服务 |
| `backend/services/session_service.py` | 会话管理 |
| `backend/database/operations_async.py` | 异步数据库操作 |

### Agent 关键文件

| 文件 | 功能 |
|------|------|
| `src/orchestration/main_graph.py` | 主图编排 |
| `src/orchestration/state.py` | 状态定义 |
| `src/orchestration/nodes/dimension_node.py` | 维度分析节点 |
| `src/subgraphs/analysis_prompts.py` | Layer 1 提示词 |
| `src/subgraphs/detailed_plan_prompts.py` | Layer 3 提示词 |
| `src/planners/generic_planner.py` | 通用规划器 |
| `src/config/dimension_metadata.py` | 28维度元数据 |

---

## 七、架构演进历史

| 版本 | 日期 | 变化 |
|------|------|------|
| v3.1 | 2026-04-05 | Agent Phase 和 Layer 关系修正：init 返回 0，新增 advance_phase/pause 路由 |
| v3.0 | 2026-04-05 | 前端状态管理从 Context 迁移到 Zustand + Immer |
| v2.2 | 2026-03-xx | Hooks 目录重构: planning/ui/utils 子目录 |
| v2.1 | 2026-03-xx | Types 目录重构: message 子模块 |
| v2.0 | 2026-02-xx | SSE 批量处理优化 (50ms 窗口) |