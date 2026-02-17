# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统，提供 Web 应用和 CLI 工具两种使用方式。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0+-green.svg)](https://github.com/langchain-ai/langgraph)

---

## 核心特性

- **三层规划架构**: 现状分析 → 规划思路 → 详细规划，逐层递进
- **并行维度执行**: 每层多个维度并行处理（12+4+12），高效执行
- **实时流式输出**: SSE 维度级流式推送，Token 实时显示
- **状态持久化**: AsyncSqliteSaver 自动保存状态，支持断点恢复
- **人工审查支持**: 步进模式下每层完成可暂停审查
- **状态驱动 UI**: 后端状态为单一真实源，前端条件渲染

---

## 快速开始

### 环境要求

- Python 3.9+
- Node.js 18+
- LLM API Key (ZhipuAI / OpenAI / DeepSeek)

### 安装

```bash
# 克隆项目
git clone https://github.com/yourusername/village-planning-agent.git
cd village-planning-agent

# 创建 .env 文件
cp .env.example .env
# 编辑 .env 填入 API Key

# 安装依赖
pip install -r backend/requirements.txt
cd frontend && npm install
```

### 启动

```bash
# 启动后端
python backend/main.py

# 启动前端（新终端）
cd frontend && npm run dev
```

访问 http://localhost:3000

---

## 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                      前端 (Next.js 14)                        │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  UnifiedPlanningContext (状态管理)                      │  │
│  │  ├── TaskController (REST 轮询 / 2秒)                   │  │
│  │  └── SSE 连接 (维度流式文本)                            │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                           │ REST + SSE
┌──────────────────────────────────────────────────────────────┐
│                     后端 (FastAPI)                            │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  planning.py (API 路由)                                 │  │
│  │  ├── POST /api/planning/start                          │  │
│  │  ├── GET /api/planning/status/{id}                     │  │
│  │  ├── GET /api/planning/stream/{id}                     │  │
│  │  └── POST /api/planning/review/{id}                    │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────────────────────────────────────────┐
│                   核心引擎 (LangGraph)                        │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  main_graph.py (主图编排)                               │  │
│  │  ├── Layer 1: 现状分析子图 (12 维度并行)                │  │
│  │  ├── Layer 2: 规划思路子图 (4 维度并行)                 │  │
│  │  └── Layer 3: 详细规划子图 (12 维度并行)                │  │
│  └────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  AsyncSqliteSaver (状态持久化)                          │  │
│  │  └── checkpoints 表 (自动管理所有状态)                  │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 数据流

### REST 状态同步 (每 2 秒)

```
前端 TaskController.pollStatus()
  ↓
GET /api/planning/status/{session_id}
  ↓
从 AsyncSqliteSaver 读取完整状态
  ↓
返回 SessionStatusResponse
  ├── pause_after_step (是否暂停)
  ├── layer_X_completed (层级完成)
  ├── previous_layer (刚完成的层级)
  └── pending_review_layer (待审查层级)
  ↓
syncBackendState() 更新 Context
  ↓
UI 条件渲染 ReviewPanel
```

### SSE 流式文本

```
后端 graph.astream() 执行
  ↓
维度内容生成 → dimension_delta 事件
  ↓
前端 onDimensionDelta 回调
  ↓
实时更新维度内容显示
```

### 暂停/恢复流程

```
步进模式 + 层级完成
  ↓
route_after_pause() 返回 "end"
  ↓
前端检测 pause_after_step=true
  ↓
显示 ReviewPanel (条件渲染)
  ↓
用户批准 → POST /api/planning/review?action=approve
  ↓
清除暂停标志 → 恢复执行
```

---

## 项目结构

```
Village_Planning_Agent/
├── backend/                      # FastAPI 后端
│   ├── main.py                   # 应用入口
│   ├── api/
│   │   ├── planning.py           # 规划 API (核心)
│   │   ├── sessions.py           # 会话管理
│   │   ├── data.py               # 数据访问
│   │   └── files.py              # 文件上传
│   ├── database/
│   │   ├── models.py             # 数据模型 (精简版)
│   │   ├── operations_async.py   # 异步操作
│   │   └── engine.py             # 数据库引擎
│   └── utils/                    # 工具函数
├── frontend/                     # Next.js 14 前端
│   └── src/
│       ├── app/                  # App Router
│       ├── contexts/
│       │   └── UnifiedPlanningContext.tsx  # 全局状态
│       ├── controllers/
│       │   └── TaskController.tsx          # 状态同步
│       ├── components/
│       │   └── chat/
│       │       ├── ChatPanel.tsx           # 主界面
│       │       └── ReviewPanel.tsx         # 审查面板
│       └── hooks/               # 自定义 Hooks
├── src/                         # 核心规划引擎
│   ├── orchestration/
│   │   └── main_graph.py        # LangGraph 主图
│   ├── subgraphs/               # 三层子图
│   │   ├── analysis_subgraph.py # 现状分析
│   │   ├── concept_subgraph.py  # 规划思路
│   │   └── detailed_plan_subgraph.py  # 详细规划
│   ├── nodes/                   # 图节点
│   └── core/                    # 核心配置
└── data/                        # 数据目录
    └── village_planning.db      # SQLite 数据库
```

---

## 三层规划维度

### Layer 1: 现状分析 (12 维度)

| 维度 | 说明 |
|------|------|
| location | 区位与对外交通分析 |
| socio_economic | 社会经济分析 |
| villager_wishes | 村民意愿分析 |
| superior_planning | 上位规划分析 |
| natural_environment | 自然环境与资源分析 |
| land_use | 村庄用地分析 |
| traffic | 道路与交通分析 |
| public_services | 公共服务设施分析 |
| infrastructure | 基础设施分析 |
| ecological_green | 生态绿地分析 |
| architecture | 建筑分析 |
| historical_culture | 历史文化分析 |

### Layer 2: 规划思路 (4 维度)

| 维度 | 说明 |
|------|------|
| resource_endowment | 资源禀赋分析 |
| planning_positioning | 规划定位分析 |
| development_goals | 发展目标分析 |
| planning_strategies | 规划策略分析 |

### Layer 3: 详细规划 (12 维度)

产业规划、空间结构、土地利用、聚落体系、综合交通、公共服务设施、基础设施、生态保护、防灾减灾、历史文化遗产、村庄风貌、建设项目库。

---

## 配置说明

### 环境变量

```env
# LLM 配置 (任选其一)
ZHIPUAI_API_KEY=your_zhipuai_key
OPENAI_API_KEY=your_openai_key
OPENAI_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_TOKENS=65536

# 数据库
USE_ASYNC_DATABASE=true
```

---

## 文档

- **[智能体架构](docs/agent.md)** - LangGraph 三层规划系统详解
- **[后端实现](docs/backend.md)** - FastAPI API 端点与数据流
- **[前端实现](docs/frontend.md)** - Next.js 状态管理与组件架构

---

## 许可证

MIT License
