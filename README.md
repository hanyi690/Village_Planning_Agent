# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统，三层递进式规划架构 + RAG 知识检索增强。

## 核心特性

- **三层递进规划**: 现状分析(L1) → 规划思路(L2) → 详细规划(L3)
- **28维度智能执行**: 12+4+12 维度，Map-Reduce 并行 + 波次路由
- **专业 Prompt 模板**: 28个维度各有定制化专业模板，包含输出格式规范和分析要点
- **RAG 知识检索**: 关键维度预加载知识，法规条文和技术指标智能注入
- **SSE 流式推送**: Token 级增量文本实时显示
- **状态持久化**: LangGraph Checkpointer 自动保存，支持断点恢复
- **人工审查**: 步进模式支持层级暂停审查
- **维度修复**: 支持驳回后级联修复相关维度

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          Village_Planning_Agent 架构                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────────────────┐ │
│  │  Frontend   │────▶│   FastAPI API    │────▶│    LangGraph Orchestration   │ │
│  │  (React)    │     │   (backend/)     │     │      (src/orchestration/)    │ │
│  └─────────────┘     └──────────────────┘     └──────────────────────────────┘ │
│         │                    │                          │                       │
│         │ SSE/REST            │                          ▼                       │
│         │                    │                ┌──────────────────────────────┐ │
│         │                    ▼                │      Node Layer              │ │
│         │          ┌─────────────────┐        │      (src/nodes/)            │ │
│         │          │   Database      │        └──────────────────────────────┘ │
│         │          │ (SQLite + WAL)  │                      │                 │
│         │          └─────────────────┘                      │                 │
│         │                                   ┌───────────────┼───────────┐      │
│         │                                   ▼               ▼           ▼      │
│         │                         ┌─────────────────┐ ┌──────────┐ ┌────────┐ │
│         │                         │   Tool System   │ │   LLM    │ │   RAG  │ │
│         │                         │ (src/tools/)    │ │ Factory  │ │(src/rag│ │
│         │                         └─────────────────┘ └──────────┘ └────────┘ │
│         │                                                                   │
│         └───────────────────────────────────────────────────────────────────▶ │
│                              SSE Stream Events                                 │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

三层规划流程:
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Layer 1 (现状分析) ──▶ Layer 2 (规划思路) ──▶ Layer 3 (详细规划)               │
│                                                                                 │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────────────────────────┐│
│  │ 12 维度并行   │    │ 4 维度波次执行│    │ 12 维度波次执行                   ││
│  │ (单波次)      │    │ (Wave 1-4)    │    │ (Wave 1-4)                        ││
│  └───────────────┘    └───────────────┘    └───────────────────────────────────┘│
│                                                                                 │
│  维度依赖链: Layer1 ──▶ Layer2 ──▶ Layer3 (跨层依赖)                           │
│              同层维度 ──▶ 同层维度 (同层依赖，Wave 控制)                        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 核心数据流

### 状态管理原则

**单一真实源**: LangGraph Checkpointer 是状态的唯一权威来源

```
前端状态完全由后端同步派生，无独立业务状态：

后端状态                          前端派生状态
──────────────────────────────────────────────────
status: 'paused'         →       isPaused: true
previous_layer: 1        →       pendingReviewLayer: 1
layer_X_completed: true  →       completedLayers[X]: true
execution_complete: true →       停止轮询
```

### 规划执行流程

```
HTTP POST /api/planning/start
    │
    ├─→ 限流检查 (rate_limiter)
    ├─→ 创建 PlanningSession 记录
    ├─→ 获取 Checkpointer 单例
    ├─→ 创建图实例 (create_village_planning_graph)
    └─→ 后台异步执行 (_execute_graph_in_background)
            │
            ▼
        Layer 1: 12维度并行执行
            │ analysis_reports 输出
            ▼
        Layer 2: 4维度波次执行 (Wave1→Wave4)
            │ concept_reports 输出
            ▼
        Layer 3: 12维度波次执行
            │ detail_reports 输出
            ▼
        generate_final_output
            │ final_output
            ▼
        SSE: completed 事件
```

### SSE 流式事件

| 事件类型               | 说明                     |
| ---------------------- | ------------------------ |
| `layer_started`      | 层级开始                 |
| `content_delta`      | 文本增量                 |
| `dimension_delta`    | 维度内容增量（Token级）  |
| `dimension_complete` | 维度完成                 |
| `dimension_revised`  | 维度修复完成             |
| `layer_completed`    | 层级完成                 |
| `pause`              | 步进暂停                 |
| `error`              | 错误信息                 |

### REST 状态同步

前端每2秒轮询 `/api/planning/status/{id}` 获取完整状态：
- 初始加载时恢复状态
- SSE 断线后重新同步
- 获取消息历史和修订历史

## 三层规划维度

### Layer 1: 现状分析 (12维度并行)

区位与对外交通、社会经济、村民意愿与诉求、上位规划与政策导向、自然环境、土地利用、道路交通、公共服务设施、基础设施、生态绿地、建筑、历史文化与乡愁保护

### Layer 2: 规划思路 (4维度波次执行)

资源禀赋(Wave1) → 规划定位(Wave2) → 发展目标(Wave3) → 规划策略(Wave4)

### Layer 3: 详细规划 (12维度波次执行)

产业规划、空间结构规划、土地利用规划★、居民点规划、道路交通规划、公共服务设施规划、基础设施规划★、生态绿地规划★、防震减灾规划★、历史文保规划★、村庄风貌指引、项目库

> ★ 标记为启用 RAG 知识检索的关键维度

## 快速开始

### 环境要求

- Python 3.13+
- Node.js 18+ (推荐 20+)
- LLM API Key (DeepSeek 或 智谱AI 或 OpenAI)

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
# LLM 配置 (DeepSeek)
OPENAI_API_KEY=your_deepseek_api_key
OPENAI_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MAX_TOKENS=65536

# Embedding 模型
EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
HF_ENDPOINT=https://hf-mirror.com  # HuggingFace 镜像（可选）
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

支持的文档格式：`.md`, `.txt`, `.pdf`, `.pptx`, `.ppt`, `.docx`, `.doc`

**源文档目录**: `data/policies/`

## 项目结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI 后端
│   ├── main.py                 # 应用入口
│   ├── schemas.py              # Pydantic 数据模型
│   ├── api/                    # API 路由
│   │   ├── planning.py         # 规划任务API (核心: /start, /stream, /review)
│   │   ├── data.py             # 村庄数据API
│   │   ├── files.py            # 文件上传API
│   │   ├── knowledge.py        # 知识库API
│   │   ├── routes.py           # 路由聚合
│   │   └── tool_manager.py     # 工具管理API
│   ├── database/               # 数据模型 (SQLModel)
│   │   ├── models.py           # PlanningSession, SessionEvent
│   │   └── operations_async.py # 异步CRUD操作
│   ├── services/               # 服务层
│   │   ├── planning_service.py # 规划执行服务
│   │   ├── checkpoint_service.py # 检查点服务
│   │   ├── session_service.py  # 会话管理服务
│   │   ├── review_service.py   # 审查服务
│   │   ├── sse_manager.py      # SSE 事件管理
│   │   └── rate_limiter.py     # 限流器
│   └── utils/                  # 工具函数
├── frontend/src/               # Next.js 14 前端
│   ├── app/                    # 页面路由 (App Router)
│   ├── providers/              # Context Provider
│   ├── controllers/            # TaskController (任务控制)
│   ├── components/             # UI组件
│   │   ├── chat/               # 聊天组件 (ChatPanel, ToolStatusPanel)
│   │   └── planning/           # 规划组件 (ReviewPanel, DimensionCard)
│   ├── hooks/                  # 自定义Hooks
│   ├── lib/                    # API客户端
│   └── types/                  # 类型定义
├── src/                        # Agent核心引擎
│   ├── agent.py                # 对外接口 (run_village_planning)
│   ├── orchestration/          # 主图编排
│   │   ├── main_graph.py       # 主图定义 (StateGraph构建)
│   │   ├── state.py            # 状态定义 (PlanningState, PlanningPhase)
│   │   ├── routing.py          # 路由逻辑 (Send API)
│   │   └── nodes/              # 节点实现
│   │       ├── dimension_node.py # 统一维度分析节点
│   │       └── revision_node.py  # 维度修复节点
│   ├── subgraphs/              # Prompt 模板系统
│   │   ├── analysis_prompts.py # Layer 1: 12维度现状分析模板
│   │   ├── concept_prompts.py  # Layer 2: 4维度规划思路模板
│   │   └── detailed_plan_prompts.py # Layer 3: 12维度详细规划模板
│   ├── config/                 # 维度配置
│   │   └── dimension_metadata.py # 维度元数据权威来源 (28维度)
│   ├── core/                   # 核心模块
│   │   ├── config.py           # 全局配置 (LLM, API Keys)
│   │   └── llm_factory.py      # LLM工厂 (OpenAI/ZhipuAI双提供商)
│   ├── rag/                    # RAG 知识检索
│   │   ├── core/               # RAG核心引擎
│   │   └── scripts/            # 知识库构建脚本
│   └── tools/                  # 工具函数
│       ├── registry.py         # 工具注册中心
│       ├── tools.py            # 工具定义
│       ├── builtin/            # 内置工具
│       └── core/               # 核心工具实现 (GIS, 人口预测)
├── knowledge_base/             # 知识库存储 (ChromaDB)
├── data/                       # 数据文件
│   ├── policies/               # 政策文档 (RAG源)
│   └── output/                 # 规划输出
├── docs/                       # 架构文档
└── tests/                      # 测试文件
```

## API 端点

### 规划 API (`/api/planning/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/start` | POST | 启动规划任务 |
| `/status/{id}` | GET | 查询任务状态 (REST轮询) |
| `/stream/{id}` | GET | SSE流式事件 |
| `/review/{id}` | POST | 审查操作 (approve/reject/rollback) |
| `/sessions/{id}` | DELETE | 删除会话 |

### 数据 API (`/api/data/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/villages` | GET | 列出所有村庄 |
| `/villages/{name}/layers/{layer}` | GET | 获取层级内容 |
| `/villages/{name}/checkpoints` | GET | 获取检查点列表 |

### 文件 API (`/api/files/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/upload` | POST | 上传并解析文件 |

### 知识库 API (`/api/knowledge/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/stats` | GET | 知识库统计 |
| `/documents` | GET/POST | 文档列表/上传 |
| `/sync` | POST | 同步文档 |

## 文档

### 核心架构文档

- **[系统架构总览](docs/architecture.md)** - 前端/后端/Agent 三层完整架构、文件依赖关系、数据流向
- **[智能体架构](docs/agent.md)** - LangGraph 主图、子图、规划器、RAG 知识检索详细实现
- **[前端实现](docs/frontend.md)** - Next.js 14 组件层次、Context 状态管理、SSE 事件处理
- **[后端实现](docs/backend_architecture_analysis.md)** - FastAPI API 与数据流分析
- **[数据和状态流转](docs/data-flow-architecture.md)** - SSE 事件、REST 轮询、Checkpoint 版本化同步
- **[工具系统](docs/tool-system.md)** - 工具注册、Adapter 适配器、bind_tools 动态调用

### 快速导航

| 想了解... | 请阅读 |
|----------|--------|
| 整体架构和文件关系 | [系统架构总览](docs/architecture.md) |
| LangGraph 图结构和节点 | [智能体架构](docs/agent.md) |
| 前端组件和状态管理 | [前端实现](docs/frontend.md) |
| SSE 事件和状态同步 | [数据和状态流转](docs/data-flow-architecture.md) |
| 工具注册和执行流程 | [工具系统](docs/tool-system.md) |
| API 端点定义 | 见下方 API 端点章节 |

### 其他文档

- **[研究课题实现](docs/research-progress.md)** - Hierarchical LangGraph 架构研究
- **[服务管理](docs/startup-guide.md)** - 服务启动与管理指南
- **[演示文档](docs/village_planning_presentation.md)** - 村庄规划系统演示（Marp 格式）

### RAG 知识库

RAG 系统已实现以下优化（详见 [智能体架构](docs/agent.md#rag-知识检索 v2.0---支持元数据过滤)）：

- **元数据注入**: 维度标签、地形类型、文档类型自动识别
- **差异化切片**: 政策/案例/标准/指南不同类型文档采用不同切片策略
- **元数据过滤检索**: 支持按维度、地形、文档类型精准过滤

## 维度依赖与波次执行

系统通过波次调度处理维度间的依赖关系。详细配置见 [智能体架构](docs/agent.md#维度配置)。

- **Layer 1**: 12 维度并行执行（无依赖）
- **Layer 2**: 4 维度波次执行（Wave 1→4，逐级依赖）
- **Layer 3**: 12 维度波次执行（Wave 1 并行，Wave 2 依赖 Wave 1）

级联修复：当维度被驳回修复时，自动更新所有下游依赖维度。

## 许可证

MIT License
