# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统，三层递进式规划架构 + RAG 知识检索增强。

## 核心特性

- **三层递进规划**: 现状分析(L1) → 规划思路(L2) → 详细规划(L3)
- **28维度智能执行**: 12+4+12 维度，Map-Reduce 并行 + 波次路由
- **RAG 知识检索**: 关键维度预加载知识，法规条文和技术指标智能注入
- **SSE 流式推送**: 维度级增量文本实时显示
- **状态持久化**: AsyncSqliteSaver 自动保存，支持断点恢复
- **人工审查**: 步进模式支持层级暂停审查

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         前端 (Next.js 14)                            │
│  UnifiedPlanningContext ←─REST轮询(2s)─ TaskController              │
│        ↓                                    SSE流式文本              │
│  条件渲染: ReviewPanel / LayerReportCard                             │
└─────────────────────────────────────────────────────────────────────┘
                               │ HTTP/SSE
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         后端 (FastAPI)                               │
│  /api/planning/*   规划任务管理                                      │
│  /api/data/*       村庄数据查询                                      │
│  /api/files/*      文件上传解析                                      │
│  /api/knowledge/*  知识库管理                                        │
└─────────────────────────────────────────────────────────────────────┘
                               │ Python调用
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent核心 (LangGraph)                         │
│  主图: START → Layer1(并行) → Layer2(波次) → Layer3(波次) → END      │
│  子图: analysis / concept / detailed_plan / revision                 │
│  规划器: GenericPlanner (28维度统一执行)                              │
│  RAG: knowledge_preload_node → knowledge_cache → Prompt注入         │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          存储层 (SQLite)                             │
│  planning_sessions: 业务元数据                                       │
│  checkpoints: LangGraph状态快照 (AsyncSqliteSaver)                   │
│  knowledge_base/chroma_db/: RAG 向量数据库                           │
└─────────────────────────────────────────────────────────────────────┘
```

## 核心数据流

### 请求处理流程

```
前端表单提交 (village_data, task_description, constraints)
       │
       ▼ POST /api/planning/start
backend/api/planning.py:start_planning()
       │ 创建 session_id，写入数据库
       │ 构建 initial_state
       │ asyncio.create_task(_execute_graph_in_background)
       ▼
src/orchestration/main_graph.py
       │ StateGraph.astream(initial_state, config)
       ▼
Layer 1: analysis_subgraph (12维度并行)
       │ knowledge_preload_node → RAG检索
       │ Map-Reduce 并行执行
       ▼
Layer 2: concept_subgraph (4维度波次)
       ▼
Layer 3: detailed_plan_subgraph (12维度波次)
       ▼
状态持久化 → SQLite checkpoints
SSE事件推送 → 前端实时渲染
```

### REST 状态同步 (前端每2秒轮询)

```
后端状态                          前端派生状态
──────────────────────────────────────────────────
status: 'paused'         →       isPaused: true
previous_layer: 1        →       pendingReviewLayer: 1
layer_X_completed: true  →       completedLayers[X]: true
execution_complete: true →       停止轮询
```

### SSE 流式事件

| 事件类型               | 说明         |
| ---------------------- | ------------ |
| `content_delta`      | 文本增量     |
| `dimension_delta`    | 维度内容增量 |
| `dimension_complete` | 维度完成     |
| `error`              | 错误信息     |

## 三层规划维度

### Layer 1: 现状分析 (12维度并行)

区位分析、社会经济、自然环境、**土地利用★**、道路交通、公共服务、**基础设施★**、**生态绿地★**、建筑、**历史文化★**、村民意愿、上位规划

### Layer 2: 规划思路 (4维度波次执行)

资源禀赋 → 规划定位 → 发展目标 → 规划策略

### Layer 3: 详细规划 (12维度波次执行)

产业规划、空间结构、**土地利用规划★**、居民点、道路交通、公共服务、**基础设施规划★**、**生态绿地规划★**、**防灾减灾★**、**历史文保★**、村庄风貌、项目库

> ★ 标记为启用 RAG 知识检索的关键维度

## 快速开始

### 环境要求

- Python 3.13+
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

### Docker 部署

```bash
# 一键部署
./deploy.sh

# 或 Windows
deploy.bat
```

### 构建知识库

```bash
# 首次构建（全量）
python src/rag/scripts/build_kb_auto.py

# 后续管理（增量）
python -m src.rag.scripts.kb_cli list           # 列出文档
python -m src.rag.scripts.kb_cli add <文件路径>  # 添加文档
python -m src.rag.scripts.kb_cli delete <文件名> # 删除文档
python -m src.rag.scripts.kb_cli sync           # 同步源目录
```

支持的文档格式：`.md`, `.txt`, `.pdf`, `.pptx`, `.docx`, `.doc`

**源文档目录**: `data/policies/`

## 项目结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI 后端
│   ├── main.py                 # 应用入口
│   ├── api/                    # API 路由
│   │   ├── planning.py         # 规划任务API
│   │   ├── data.py             # 村庄数据API
│   │   ├── files.py            # 文件上传API
│   │   └── knowledge.py        # 知识库API
│   └── database/               # 数据模型
├── frontend/src/               # Next.js 14 前端
│   ├── app/                    # 页面路由
│   ├── contexts/               # 状态管理
│   ├── controllers/            # 控制器
│   ├── components/             # UI组件
│   └── lib/                    # API客户端
├── src/                        # Agent核心引擎
│   ├── orchestration/          # 主图编排
│   ├── subgraphs/              # 三层子图
│   ├── nodes/                  # 节点实现
│   ├── planners/               # 规划器
│   ├── config/                 # 维度配置
│   ├── rag/                    # RAG 知识检索
│   └── tools/                  # 工具函数
├── knowledge_base/             # 知识库存储
│   └── chroma_db/              # ChromaDB 向量库
├── data/                       # 数据文件
│   ├── village_planning.db     # SQLite数据库
│   └── policies/               # 政策文档源文件
└── docs/                       # 文档
```

## API 端点

### 规划 API (`/api/planning/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/planning/start` | POST | 启动规划任务 |
| `/api/planning/status/{id}` | GET | 查询任务状态 |
| `/api/planning/stream/{id}` | GET | SSE流式事件 |
| `/api/planning/review/{id}` | POST | 审查操作 |
| `/api/planning/sessions/{id}` | DELETE | 删除会话 |

### 数据 API (`/api/data/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/data/villages` | GET | 列出所有村庄 |
| `/api/data/villages/{name}/layers/{layer}` | GET | 获取层级内容 |

### 文件 API (`/api/files/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/files/upload` | POST | 上传并解析文件 |

### 知识库 API (`/api/knowledge/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/knowledge/status` | GET | 知识库状态 |
| `/api/knowledge/documents` | GET | 文档列表 |
| `/api/knowledge/sync` | POST | 同步文档 |

## 文档

- **[智能体架构](docs/agent.md)** - LangGraph 主图、子图、规划器、RAG
- **[后端实现](docs/backend.md)** - FastAPI API 与数据流
- **[前端实现](docs/frontend.md)** - Next.js 状态管理

## RAG 知识检索

### 模块架构

统一的 RAG 模块位于 `src/rag/`：

- **核心工具**: `knowledge_search_tool` - 语义检索
- **文档加载**: `loaders.py` - 支持 PDF, DOCX, PPTX, TXT, MD 等格式
- **向量存储**: ChromaDB，持久化到 `knowledge_base/chroma_db/`

### 检索策略

- **预加载模式**: 子图开始前统一检索，缓存到 `knowledge_cache`
- **关键维度**: 涉及法规条文和技术指标的维度自动注入知识上下文

## 许可证

MIT License