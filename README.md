# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统，三层递进式规划架构 + RAG 知识检索增强。

## 核心特性

- **三层递进规划**: 现状分析(L1) → 规划思路(L2) → 详细规划(L3)
- **28维度智能执行**: 12+4+12 维度，Map-Reduce 并行 + 波次路由
- **RAG 知识检索**: 关键维度预加载知识，法规条文和技术指标智能注入
- **SSE 流式推送**: Token 级增量文本实时显示
- **状态持久化**: LangGraph Checkpointer 自动保存，支持断点恢复
- **人工审查**: 步进模式支持层级暂停审查
- **维度修复**: 支持驳回后级联修复相关维度

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         前端 (Next.js 14)                            │
│  UnifiedPlanningContext ←─REST轮询(2s)─ TaskController              │
│        ↓                                    SSE流式文本              │
│  条件渲染: ReviewPanel / LayerReportMessage                         │
└─────────────────────────────────────────────────────────────────────┘
                               │ HTTP/SSE
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         后端 (FastAPI)                               │
│  /api/planning/*   规划任务管理    /api/data/*   村庄数据查询        │
│  /api/files/*      文件上传解析    /api/knowledge/*  知识库管理      │
│  AsyncSqliteSaver (Checkpointer单例) → 状态持久化                   │
└─────────────────────────────────────────────────────────────────────┘
                               │ Python调用
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent核心 (LangGraph)                         │
│  主图: START → init_pause → Layer1(并行) → Layer2(波次) →           │
│        Layer3(波次) → tool_bridge → generate_final → END            │
│  子图: analysis / concept / detailed_plan / revision                 │
│  规划器: GenericPlanner (28维度统一执行)                              │
│  RAG: knowledge_preload_node → knowledge_cache → Prompt注入         │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          存储层 (SQLite)                             │
│  planning_sessions: 业务元数据    ui_sessions/messages: UI状态       │
│  checkpoints: LangGraph状态快照 (单一真实源)                         │
│  knowledge_base/chroma_db/: RAG 向量数据库                           │
└─────────────────────────────────────────────────────────────────────┘
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
│   ├── api/                    # API 路由
│   │   ├── planning.py         # 规划任务API
│   │   ├── data.py             # 村庄数据API
│   │   ├── files.py            # 文件上传API
│   │   └── knowledge.py        # 知识库API
│   ├── database/               # 数据模型
│   ├── services/               # 服务层 (限流器)
│   └── utils/                  # 工具函数
├── frontend/src/               # Next.js 14 前端
│   ├── app/                    # 页面路由
│   ├── contexts/               # 状态管理
│   ├── controllers/            # TaskController
│   ├── components/             # UI组件
│   ├── hooks/                  # 自定义Hooks
│   ├── lib/                    # API客户端
│   ├── config/                 # 配置文件
│   └── types/                  # 类型定义
├── src/                        # Agent核心引擎
│   ├── agent.py                # 对外接口
│   ├── orchestration/          # 主图编排
│   ├── subgraphs/              # 三层子图
│   ├── nodes/                  # 节点实现
│   ├── planners/               # 规划器
│   ├── config/                 # 维度配置
│   ├── core/                   # 核心模块
│   ├── rag/                    # RAG 知识检索
│   └── tools/                  # 工具函数
├── knowledge_base/             # 知识库存储
├── data/                       # 数据文件
├── docs/                       # 文档
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

- **[智能体架构](docs/agent.md)** - LangGraph 主图、子图、规划器、RAG
- **[后端实现](docs/backend.md)** - FastAPI API 与数据流
- **[前端实现](docs/frontend.md)** - Next.js 状态管理

## 维度依赖与波次执行

### 依赖链

维度之间存在依赖关系，通过 `dimension_metadata.py` 配置：

```python
# Layer 2 依赖 Layer 1
"planning_positioning": {
    "dependencies": {
        "layer1_analyses": ["location", "socio_economic", "superior_planning"],
        "layer2_concepts": ["resource_endowment"]
    }
}

# Layer 3 依赖 Layer 1, 2 和同层维度
"project_bank": {
    "dependencies": {
        "layer3_plans": ["industry", "spatial_structure", ...]  # 所有其他维度
    }
}
```

### 波次调度

- **Wave 1**: 无依赖的维度，可并行执行
- **Wave N**: 依赖 Wave 1..N-1 的维度

### 级联修复

当维度被修复时，自动更新所有下游依赖维度：

```
修复 natural_environment
  → Wave 1: resource_endowment, ecological, spatial_structure, ...
  → Wave 2: planning_positioning, planning_strategies
  → Wave 3: development_goals, project_bank
```

## 许可证

MIT License
