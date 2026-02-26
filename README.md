# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统，三层递进式规划架构。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0+-green.svg)](https://github.com/langchain-ai/langgraph)

---

## 核心特性

- **三层递进规划**: 现状分析(L1) → 规划思路(L2) → 详细规划(L3)
- **维度并行执行**: 12+4+10 维度，Map-Reduce 并行处理
- **SSE 流式推送**: 维度级增量文本，实时显示
- **状态持久化**: AsyncSqliteSaver 自动保存，支持断点恢复
- **人工审查**: 步进模式支持层级暂停审查
- **后端状态驱动**: 单一真实源，前端条件渲染

---

## 快速开始

### 环境要求

- Python 3.9+
- Node.js 18+
- LLM API Key (ZhipuAI / OpenAI / DeepSeek)

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
# 或
OPENAI_API_KEY=your_key
LLM_MODEL=deepseek-chat
```

### 启动

```bash
# 后端 (端口 8000)
python backend/main.py

# 前端 (端口 3000)
cd frontend && npm run dev
```

访问 http://localhost:3000

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js 14)                    │
│                                                             │
│  UnifiedPlanningContext ───── TaskController                │
│       │                           │                         │
│       │  syncBackendState()       │  REST轮询(2s) + SSE     │
│       ▼                           ▼                         │
│  条件渲染: ReviewPanel / LayerReport                        │
└─────────────────────────────────────────────────────────────┘
                            │
                     REST + SSE
                            │
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI)                        │
│                                                             │
│  API Routes:                                                │
│    POST /api/planning/start    启动规划                     │
│    GET  /api/planning/status   状态查询 (核心)              │
│    GET  /api/planning/stream   SSE流式                      │
│    POST /api/planning/review   审查操作                     │
│                                                             │
│  ToolManager (Singleton)                                    │
│  RateLimiter: 5s/3次请求, 10s冷却期                         │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                   Core Engine (LangGraph)                   │
│                                                             │
│  main_graph.py:                                             │
│    START → Layer1 → Layer2 → Layer3 → END                  │
│                                                             │
│  Subgraphs:                                                 │
│    ├── analysis_subgraph   (12维度并行)                     │
│    ├── concept_subgraph    (4维度串行)                      │
│    └── detailed_plan_subgraph (10维度)                      │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                   Storage Layer                             │
│                                                             │
│  SQLite (village_planning.db):                              │
│    ├── planning_sessions  业务元数据                        │
│    └── checkpoints  LangGraph状态快照 (AsyncSqliteSaver)    │
└─────────────────────────────────────────────────────────────┘
```

---

## 数据流

### 核心原则：后端状态为单一真实源

```
┌──────────────────────────────────────────────────────────┐
│                    Backend State                          │
│  (AsyncSqliteSaver + _sessions 内存)                      │
│                                                          │
│  status: 'running' | 'paused' | 'completed' | 'failed'  │
│  pause_after_step: boolean                               │
│  previous_layer: number (待审查层级)                      │
│  layer_X_completed: boolean                              │
│  execution_complete: boolean                             │
└──────────────────────────────────────────────────────────┘
                          │
              GET /api/planning/status (每2秒)
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│                    Frontend Context                       │
│  TaskController.fetchStatus()                            │
│       │                                                  │
│       ▼                                                  │
│  setState(taskState)                                     │
│       │                                                  │
│       ▼                                                  │
│  syncBackendState() → 更新 UnifiedPlanningContext        │
│       │                                                  │
│       ▼                                                  │
│  条件渲染: {isPaused && <ReviewPanel />}                 │
└──────────────────────────────────────────────────────────┘
```

### REST 状态同步

```
TaskController (每2秒轮询)
    │
    ▼
GET /api/planning/status/{id}
    │
    ▼ 返回完整状态
{
  status: "paused",
  pause_after_step: true,
  previous_layer: 1,         // 待审查层级
  layer_1_completed: true,
  layer_2_completed: false,
  layer_3_completed: false,
  execution_complete: false
}
    │
    ▼
syncBackendState()
    │
    ▼
isPaused = (status === 'paused')
pendingReviewLayer = previous_layer
completedLayers = {1: layer_1_completed, ...}
    │
    ▼
UI 条件渲染 ReviewPanel
```

### SSE 流式文本

```
graph.astream() 执行
    │
    ▼ dimension_delta 事件
{
  type: "dimension_delta",
  layer: 1,
  dimension_key: "location",
  delta: "金田村位于...",
  accumulated: "金田村位于泗水镇..."
}
    │
    ▼ onDimensionDelta 回调
实时更新维度内容显示
```

### 审查操作流程

```
用户点击"批准"
    │
    ▼
POST /api/planning/review?action=approve
    │
    ▼
后端: 清除暂停标志
    - pause_after_step = false
    - previous_layer = 0
    - 启动后台任务继续执行
    │
    ▼
REST轮询检测: status = 'running'
    │
    ▼
syncBackendState(): isPaused = false
    │
    ▼
ReviewPanel 消失 (条件渲染)
```

---

## 项目结构

```
Village_Planning_Agent/
├── backend/                 # FastAPI 后端
│   ├── main.py              # 应用入口
│   ├── api/
│   │   ├── planning.py      # 核心 API
│   │   ├── data.py          # 数据访问
│   │   └── tool_manager.py  # 工具管理器
│   ├── database/
│   │   ├── models.py        # 数据模型
│   │   └── operations_async.py
│   └── services/
│       └── rate_limiter.py
├── frontend/src/            # Next.js 14 前端
│   ├── contexts/
│   │   └── UnifiedPlanningContext.tsx  # 全局状态
│   ├── controllers/
│   │   └── TaskController.tsx          # REST轮询+SSE
│   ├── components/
│   │   ├── chat/            # 聊天组件
│   │   └── layout/          # 布局组件
│   └── lib/api.ts           # API 客户端
├── src/                     # 核心引擎
│   ├── orchestration/
│   │   └── main_graph.py    # LangGraph 主图
│   ├── subgraphs/           # 三层子图
│   ├── nodes/               # 图节点
│   ├── planners/            # 规划器
│   └── tools/               # 工具层
└── data/                    # 数据目录
    └── village_planning.db
```

---

## 三层规划维度

### Layer 1: 现状分析 (12维度并行)

区位分析、社会经济、自然环境、土地利用、道路交通、公共服务、基础设施、生态绿地、建筑、历史文化、村民意愿、上位规划

### Layer 2: 规划思路 (4维度串行)

资源禀赋 → 规划定定位 → 发展目标 → 规划策略

### Layer 3: 详细规划 (10维度)

产业规划、总体规划、交通规划、公共服务、基础设施、生态保护、防灾减灾、遗产保护、村庄风貌、项目库

---

## 文档

- **[智能体架构](docs/agent.md)** - LangGraph 主图与子图
- **[后端实现](docs/backend.md)** - FastAPI API 与数据流
- **[前端实现](docs/frontend.md)** - Next.js 状态管理

---

## 许可证

MIT License
