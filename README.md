# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统，三层递进式规划架构。

## 核心特性

- **三层递进规划**: 现状分析(L1) → 规划思路(L2) → 详细规划(L3)
- **28维度并行执行**: 12+4+12 维度，Map-Reduce 并行处理
- **SSE 流式推送**: 维度级增量文本，实时显示
- **状态持久化**: AsyncSqliteSaver 自动保存，支持断点恢复
- **人工审查**: 步进模式支持层级暂停审查
- **后端状态驱动**: 单一真实源，前端条件渲染

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户界面 (Next.js 14)                        │
│  UnifiedPlanningContext ───── TaskController                        │
│       │                              │                               │
│       │  syncBackendState()          │  REST轮询(2s) + SSE           │
│       ▼                              ▼                               │
│  条件渲染: ReviewPanel / LayerReportCard                             │
└─────────────────────────────────────────────────────────────────────┘
                               │ HTTP/SSE
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         后端服务 (FastAPI)                           │
│  API Routes:                                                        │
│    POST /api/planning/start    启动规划                              │
│    GET  /api/planning/status   状态查询                              │
│    GET  /api/planning/stream   SSE流式                              │
│    POST /api/planning/review   审查操作                              │
│    GET  /api/data/villages     数据访问                              │
└─────────────────────────────────────────────────────────────────────┘
                               │ Python调用
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent核心 (LangGraph)                         │
│  主图: START → Layer1 → Layer2 → Layer3 → END                       │
│  子图: analysis_subgraph / concept_subgraph / detailed_plan_subgraph │
│  LLM: 智谱 GLM-4-Flash                                              │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          存储层 (SQLite)                             │
│  planning_sessions: 业务元数据                                       │
│  checkpoints: LangGraph状态快照 (AsyncSqliteSaver)                   │
└─────────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 环境要求

- Python 3.9+
- Node.js 18+
- LLM API Key (ZhipuAI)

### 安装

```bash
git clone https://github.com/yourusername/village-planning-agent.git
cd village-planning-agent

# 后端
pip install -r backend/requirements.txt

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

## 数据流

### 核心原则：后端状态为单一真实源

```
后端状态                              前端派生状态
─────────────────────────────────────────────────────
status: 'paused'           →        isPaused: true
previous_layer: 1          →        pendingReviewLayer: 1
layer_1_completed: true    →        completedLayers[1]: true
execution_complete: true   →        停止轮询
```

### REST 状态同步 (每2秒)

```
TaskController.fetchStatus()
    │
    ▼
GET /api/planning/status/{id}
    │
    ▼ 返回完整状态
{
  status: "paused",
  previous_layer: 1,
  layer_1_completed: true,
  ...
}
    │
    ▼
syncBackendState() → 更新 UnifiedPlanningContext
    │
    ▼
UI 条件渲染 ReviewPanel
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

## 项目结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI 后端
│   ├── main.py                 # 应用入口
│   ├── schemas.py              # Pydantic模型
│   ├── api/
│   │   ├── planning.py         # 规划API
│   │   ├── data.py             # 数据访问API
│   │   └── tool_manager.py     # 工具管理器
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
│   ├── lib/
│   │   └── api.ts              # API客户端
│   └── types/
│       └── message.ts          # 类型定义
├── src/                        # 核心引擎
│   ├── agent.py                # 对外接口
│   ├── orchestration/
│   │   └── main_graph.py       # LangGraph主图
│   ├── subgraphs/              # 三层子图
│   │   ├── analysis_subgraph.py
│   │   ├── concept_subgraph.py
│   │   └── detailed_plan_subgraph.py
│   ├── nodes/
│   │   └── layer_nodes.py      # Layer节点
│   ├── planners/
│   │   ├── unified_base_planner.py
│   │   └── generic_planner.py  # 通用规划器
│   └── config/
│       └── dimension_metadata.py  # 维度配置
└── data/
    └── village_planning.db     # SQLite数据库
```

## 三层规划维度

### Layer 1: 现状分析 (12维度并行)

区位分析、社会经济、自然环境、土地利用、道路交通、公共服务、基础设施、生态绿地、建筑、历史文化、村民意愿、上位规划

### Layer 2: 规划思路 (4维度串行)

资源禀赋 → 规划定定位 → 发展目标 → 规划策略

### Layer 3: 详细规划 (12维度)

产业规划、空间结构、土地利用、居民点、道路交通、公共服务、基础设施、生态绿地、防灾减灾、历史文保、村庄风貌、项目库

## API端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/planning/start` | POST | 启动规划任务 |
| `/api/planning/status/{id}` | GET | 查询任务状态 |
| `/api/planning/stream/{id}` | GET | SSE流式事件 |
| `/api/planning/review/{id}` | POST | 审查操作 |
| `/api/data/villages` | GET | 列出所有村庄 |
| `/api/data/villages/{name}/layers/{layer}` | GET | 获取层级内容 |

## 文档

- **[智能体架构](docs/agent.md)** - LangGraph 主图与子图
- **[后端实现](docs/backend.md)** - FastAPI API 与数据流
- **[前端实现](docs/frontend.md)** - Next.js 状态管理

## 许可证

MIT License