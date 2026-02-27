# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统，三层递进式规划架构。

## 核心特性

- **三层递进规划**: 现状分析(L1) → 规划思路(L2) → 详细规划(L3)
- **28维度智能执行**: 12+4+12 维度，Map-Reduce 并行 + 波次路由
- **SSE 流式推送**: 维度级增量文本实时显示
- **状态持久化**: AsyncSqliteSaver 自动保存，支持断点恢复
- **人工审查**: 步进模式支持层级暂停审查
- **后端状态驱动**: 单一真实源，前端条件渲染

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         前端 (Next.js 14)                            │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ UnifiedPlanningContext  ←──syncBackendState()──  TaskController │   │
│  │        ↓                              ↓            REST轮询(2s) │   │
│  │ 条件渲染: ReviewPanel / LayerReportCard      SSE流式文本       │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                               │ HTTP/SSE
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         后端 (FastAPI)                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ /api/planning/start   启动规划                               │   │
│  │ /api/planning/status  状态查询 (REST轮询)                    │   │
│  │ /api/planning/stream  SSE流式事件                            │   │
│  │ /api/planning/review  审查操作 (approve/reject/rollback)     │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                               │ Python调用
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent核心 (LangGraph)                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 主图: START → Layer1(并行) → Layer2(波次) → Layer3(波次) → END│   │
│  │ 子图: analysis_subgraph / concept_subgraph / detailed_plan   │   │
│  │ 规划器: GenericPlanner (28维度统一执行)                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          存储层 (SQLite)                             │
│  planning_sessions: 业务元数据                                       │
│  checkpoints: LangGraph状态快照 (AsyncSqliteSaver)                   │
└─────────────────────────────────────────────────────────────────────┘
```

## 核心数据流

### 后端状态为单一真实源

```
后端状态                          前端派生状态
──────────────────────────────────────────────────
status: 'paused'         →       isPaused: true
previous_layer: 1        →       pendingReviewLayer: 1
layer_X_completed: true  →       completedLayers[X]: true
execution_complete: true →       停止轮询
```

### REST 状态同步 (每2秒)

```
TaskController.fetchStatus()
       │
       ▼ GET /api/planning/status/{id}
       │
       ▼ 返回完整状态
syncBackendState() → 更新 UnifiedPlanningContext
       │
       ▼
UI 条件渲染 ReviewPanel / LayerReportCard
```

### SSE 流式事件

```
graph.astream() 执行
       │
       ▼ dimension_delta 事件
{ type: "dimension_delta", layer: 1, dimension: "location", delta: "..." }
       │
       ▼ 实时更新维度内容显示
```

## 三层规划维度

### Layer 1: 现状分析 (12维度并行)
区位分析、社会经济、自然环境、土地利用、道路交通、公共服务、基础设施、生态绿地、建筑、历史文化、村民意愿、上位规划

### Layer 2: 规划思路 (4维度波次执行)
资源禀赋 → 规划定位 → 发展目标 → 规划策略

### Layer 3: 详细规划 (12维度波次执行)
产业规划、空间结构、土地利用、居民点、道路交通、公共服务、基础设施、生态绿地、防灾减灾、历史文保、村庄风貌、项目库

## 快速开始

### 环境要求
- Python 3.9+
- Node.js 18+
- LLM API Key (智谱AI 或 OpenAI)

### 安装

```bash
# 后端
pip install -r requirements.txt

# 前端
cd frontend && npm install
```

### 配置

```env
# .env
ZHIPUAI_API_KEY=your_key
LLM_MODEL=glm-4-flash
```

### 启动

```bash
# 后端 (端口 8000)
python backend/main.py

# 前端 (端口 3000)
cd frontend && npm run dev
```

访问 http://localhost:3000

## 项目结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI 后端
│   ├── main.py                 # 应用入口
│   ├── schemas.py              # Pydantic模型
│   ├── api/
│   │   ├── planning.py         # 规划API核心
│   │   ├── data.py             # 数据访问API
│   │   └── files.py            # 文件上传API
│   ├── database/
│   │   ├── models.py           # SQLModel模型
│   │   └── operations_async.py # 异步CRUD
│   └── services/
│       └── rate_limiter.py     # 限流器
├── frontend/src/               # Next.js 14 前端
│   ├── contexts/
│   │   └── UnifiedPlanningContext.tsx  # 全局状态
│   ├── controllers/
│   │   └── TaskController.tsx          # REST轮询+SSE
│   ├── components/
│   │   ├── chat/               # 聊天组件
│   │   ├── layout/             # 布局组件
│   │   └── ui/                 # UI组件
│   ├── lib/api.ts              # API客户端
│   └── types/                  # 类型定义
├── src/                        # Agent核心引擎
│   ├── agent.py                # 对外接口
│   ├── orchestration/
│   │   └── main_graph.py       # LangGraph主图
│   ├── subgraphs/              # 三层子图
│   ├── nodes/                  # 节点实现
│   ├── planners/               # 规划器
│   └── config/
│       └── dimension_metadata.py  # 维度配置
└── data/
    └── village_planning.db     # SQLite数据库
```

## API端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/planning/start` | POST | 启动规划任务 |
| `/api/planning/status/{id}` | GET | 查询任务状态 |
| `/api/planning/stream/{id}` | GET | SSE流式事件 |
| `/api/planning/review/{id}` | POST | 审查操作 (approve/reject/rollback) |
| `/api/data/villages` | GET | 列出所有村庄 |
| `/api/data/villages/{name}/layers/{layer}` | GET | 获取层级内容 |
| `/api/files/upload` | POST | 上传文件 |

## 文档

- **[智能体架构](docs/agent.md)** - LangGraph 主图、子图、规划器
- **[后端实现](docs/backend.md)** - FastAPI API 与数据流
- **[前端实现](docs/frontend.md)** - Next.js 状态管理
- **[前端组件架构](FRONTEND_COMPONENT_ARCHITECTURE.md)** - 组件结构与数据流
- **[前端视觉指南](FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范

## 许可证

MIT License
