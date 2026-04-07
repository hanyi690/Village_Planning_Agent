# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统，采用 Router Agent 架构 + 三层递进式规划 + RAG 知识检索增强。

## 核心特性

- **Router Agent 架构**: 单一 StateGraph + 中央路由节点，消灭双写问题
- **三层递进规划**: 现状分析(L1) → 规划思路(L2) → 详细规划(L3)
- **28维度智能执行**: 12+4+12 维度，Map-Reduce 并行 + Wave 波次调度
- **专业 Prompt 模板**: 28个维度各有定制化专业模板
- **RAG 知识检索**: 关键维度预加载知识，法规条文和技术指标智能注入
- **SSE 流式推送**: Token 级增量文本实时显示，批量处理优化
- **状态持久化**: LangGraph Checkpoint 作为 SSOT，支持断点恢复
- **人工审查**: 步进模式支持层级暂停审查
- **维度修复**: 支持驳回后级联修复相关维度（影响树计算）

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          Village_Planning_Agent 架构                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────────────────┐ │
│  │  Frontend   │────▶│   FastAPI API    │────▶│    Router Agent (LangGraph)  │ │
│  │  (React +   │     │   (backend/)     │     │      (src/orchestration/)    │ │
│  │   Zustand)  │     │                  │     │                              │ │
│  └─────────────┘     └──────────────────┘     └──────────────────────────────┘ │
│         │                    │                          │                       │
│         │ SSE Stream         │                          ▼                       │
│         │                    │                ┌──────────────────────────────┐ │
│         │                    ▼                │  conversation_node (中央路由) │ │
│         │          ┌─────────────────┐        │          ↓                   │ │
│         │          │   Database      │        │  intent_router (意图识别)    │ │
│         │          │ (SQLite + WAL)  │        │          ↓                   │ │
│         │          └─────────────────┘        │  Send API (并行分发)         │ │
│         │                                   └──────────────────────────────┘ │
│         │                                              │                       │
│         │                              ┌───────────────┼───────────────┐       │
│         │                              ▼               ▼               ▼       │
│         │                    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│         │                    │ Tool System │  │  Dimension  │  │     RAG     │ │
│         │                    │ (registry)  │  │   Nodes     │  │  (ChromaDB) │ │
│         │                    └─────────────┘  └─────────────┘  └─────────────┘ │
│         │                                                                   │
│         └───────────────────────────────────────────────────────────────────▶ │
│                              SSE Stream Events                                 │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Router Agent 架构流程

```
[用户输入]
    │
    ▼
conversation_node (LLM: bind_tools)
    │ intent_router
    ├─► [闲聊/问答] END
    ├─► [工具调用] execute_tools_node
    └─► [推进规划] route_by_phase
                          │
                   [Send N 维度]
                          │
                          ▼
                  analyze_dimension
                          │
                   emit_sse_events
                          │
                          ▼
                  collect_results
                          │
                  check_completion
                          │
               ┌──────────┴──────────┐
               ▼                      ▼
         advance_phase           END (pause)
```

### 三层规划流程

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Layer 1 (现状分析) ──▶ Layer 2 (规划思路) ──▶ Layer 3 (详细规划)               │
│                                                                                 │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────────────────────────┐│
│  │ 12 维度并行   │    │ 4 维度波次执行│    │ 12 维度波次执行                   ││
│  │ (Map-Reduce)  │    │ (Wave 1-4)    │    │ (Wave 1-2)                        ││
│  └───────────────┘    └───────────────┘    └───────────────────────────────────┘│
│                                                                                 │
│  维度依赖链: Layer1 ──▶ Layer2 ──▶ Layer3 (跨层依赖)                           │
│              同层维度 ──▶ 同层维度 (同层依赖，Wave 控制)                        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 核心数据流

### 状态管理架构

**单一真实源 (SSOT)**: LangGraph Checkpoint 是状态的唯一权威来源

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          状态同步架构                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   LangGraph Checkpoint (SSOT)                                          │
│          │                                                              │
│          ▼                                                              │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │  UnifiedPlanningState                                            │  │
│   │  - phase: "layer1" | "layer2" | "layer3" | "completed"          │  │
│   │  - reports: {layer1: {}, layer2: {}, layer3: {}}                │  │
│   │  - completed_dimensions: {layer1: [], layer2: [], layer3: []}   │  │
│   │  - pause_after_step: boolean                                     │  │
│   │  - previous_layer: number                                        │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│          │                                                              │
│          │ SSE Events + REST Status                                    │
│          ▼                                                              │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │  Frontend Zustand Store                                          │  │
│   │  - currentLayer: derived from phase                              │  │
│   │  - completedLayers: derived from reports                         │  │
│   │  - isPaused: derived from pause_after_step                       │  │
│   │  - pendingReviewLayer: derived from previous_layer               │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### SSE 流式事件

| 事件类型 | 说明 | 文档参考 |
|---------|------|----------|
| `connected` | SSE 连接建立 | [前端状态](docs/architecture/frontend-state-dataflow.md) |
| `layer_started` | 层级开始执行 | [后端API](docs/architecture/backend-api-dataflow.md) |
| `dimension_start` | 维度开始分析 | [Agent核心](docs/architecture/agent-core-implementation.md) |
| `dimension_delta` | 维度内容增量 (Token级) | [前端状态](docs/architecture/frontend-state-dataflow.md) |
| `dimension_complete` | 维度分析完成 | [维度数据流](docs/architecture/layer-dimension-dataflow.md) |
| `layer_completed` | 层级执行完成 | [后端API](docs/architecture/backend-api-dataflow.md) |
| `tool_call` | 工具开始执行 | [工具系统](docs/architecture/tool-system-implementation.md) |
| `tool_progress` | 工具执行进度 | [工具系统](docs/architecture/tool-system-implementation.md) |
| `tool_result` | 工具执行结果 | [工具系统](docs/architecture/tool-system-implementation.md) |
| `checkpoint_saved` | 检查点已保存 | [Agent核心](docs/architecture/agent-core-implementation.md) |
| `pause` | 步进暂停 | [Agent核心](docs/architecture/agent-core-implementation.md) |
| `resumed` | 恢复执行 | [Agent核心](docs/architecture/agent-core-implementation.md) |

## 三层规划维度

### Layer 1: 现状分析 (12维度并行)

| 维度键 | 维度名称 | 工具绑定 |
|--------|----------|----------|
| `location` | 区位与对外交通分析 | - |
| `socio_economic` | 社会经济分析 | `population_model_v1` |
| `villager_wishes` | 村民意愿与诉求分析 | - |
| `superior_planning` | 上位规划与政策导向分析 | - |
| `natural_environment` | 自然环境分析 | `wfs_data_fetch` |
| `land_use` | 土地利用分析 | `gis_coverage_calculator` |
| `traffic` | 道路交通分析 | `accessibility_analysis` |
| `public_services` | 公共服务设施分析 | `poi_search` |
| `infrastructure` | 基础设施分析 | - |
| `ecological_green` | 生态绿地分析 | - |
| `architecture` | 建筑分析 | - |
| `historical_culture` | 历史文化与乡愁保护分析 | - |

### Layer 2: 规划思路 (4维度波次执行)

| Wave | 维度键 | 维度名称 | 依赖 |
|------|--------|----------|------|
| 1 | `resource_endowment` | 资源禀赋分析 | 6个 Layer 1 维度 |
| 2 | `planning_positioning` | 规划定位分析 | `resource_endowment` |
| 3 | `development_goals` | 发展目标分析 | `resource_endowment`, `planning_positioning` |
| 4 | `planning_strategies` | 规划策略分析 | 前3个 Layer 2 维度 |

### Layer 3: 详细规划 (12维度波次执行)

| 维度键 | 维度名称 | RAG |
|--------|----------|-----|
| `industry` | 产业规划 | - |
| `spatial_structure` | 空间结构规划 | - |
| `land_use_planning` | 土地利用规划 | ✓ |
| `settlement_planning` | 居民点规划 | - |
| `traffic_planning` | 道路交通规划 | - |
| `public_service` | 公共服务设施规划 | - |
| `infrastructure_planning` | 基础设施规划 | ✓ |
| `ecological` | 生态绿地规划 | ✓ |
| `disaster_prevention` | 防震减灾规划 | ✓ |
| `heritage` | 历史文保规划 | ✓ |
| `landscape` | 村庄风貌指引 | - |
| `project_bank` | 建设项目库 | - |

> RAG 标记的维度启用知识检索增强，涉及法规条文和技术标准

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
│   ├── api/planning/           # API 路由
│   │   ├── startup.py          # 启动与清理
│   │   ├── stream.py           # SSE 流端点
│   │   ├── chat.py             # 对话 API
│   │   ├── review.py           # 审查 API
│   │   └── session.py          # 会话管理
│   ├── services/               # 服务层
│   │   ├── sse_manager.py      # SSE 事件管理 (核心)
│   │   ├── checkpoint_service.py # 检查点服务
│   │   └── planning_runtime.py # 规划运行时
│   ├── database/               # 数据模型 (SQLModel)
│   └── constants/              # 常量定义
│       └── sse_events.py       # SSE 事件类型
├── frontend/src/               # React 前端
│   ├── stores/                 # Zustand 状态管理
│   │   └── planningStore.ts    # 核心状态定义
│   ├── hooks/planning/         # 规划相关 Hooks
│   │   └── useSSEConnection.ts # SSE 连接管理
│   ├── lib/api/                # API 客户端
│   ├── types/message/          # 消息类型定义
│   └── components/             # UI 组件
├── src/                        # Agent 核心引擎
│   ├── orchestration/          # 主图编排 (Router Agent)
│   │   ├── main_graph.py       # StateGraph 构建
│   │   ├── state.py            # UnifiedPlanningState
│   │   ├── routing.py          # 路由逻辑 (intent_router, route_by_phase)
│   │   └── nodes/              # 节点实现
│   │       ├── dimension_node.py # 维度分析节点
│   │       └── revision_node.py  # 修订节点
│   ├── config/                 # 配置
│   │   └── dimension_metadata.py # 维度元数据 (权威来源)
│   ├── core/                   # 核心模块
│   │   ├── config.py           # 全局配置
│   │   └── llm_factory.py      # LLM 工厂
│   ├── rag/                    # RAG 知识检索
│   ├── tools/                  # 工具系统
│   │   ├── registry.py         # ToolRegistry (核心)
│   │   └── builtin/            # 内置工具实现
│   └── utils/                  # 工具函数
│       └── sse_publisher.py    # SSE 事件发布器
├── docs/architecture/          # 架构文档 (技术实现)
│   ├── frontend-state-dataflow.md
│   ├── backend-api-dataflow.md
│   ├── agent-core-implementation.md
│   ├── layer-dimension-dataflow.md
│   ├── tool-system-implementation.md
│   └── terminology-and-references.md
├── knowledge_base/             # 知识库存储 (ChromaDB)
└── data/                       # 数据文件
    ├── policies/               # 政策文档 (RAG源)
    └── output/                 # 规划输出
```

## API 端点

### 规划 API (`/api/planning/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/start` | POST | 启动规划任务 |
| `/status/{id}` | GET | 查询任务状态 |
| `/stream/{id}` | GET | SSE 流式事件 |
| `/chat/{id}` | POST | 发送对话消息 |
| `/review/{id}` | POST | 审查操作 (approve/reject) |
| `/checkpoint/{id}` | GET | 获取检查点列表 |
| `/message/{id}` | GET/POST | 消息管理 |

### 数据 API (`/api/data/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/villages` | GET | 列出所有村庄 |
| `/villages/{name}/layers/{layer}` | GET | 获取层级内容 |

### 知识库 API (`/api/knowledge/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/stats` | GET | 知识库统计 |
| `/documents` | GET/POST | 文档列表/上传 |

## 架构文档

### 技术实现文档

| 文档 | 说明 |
|------|------|
| [前端状态管理](docs/architecture/frontend-state-dataflow.md) | Zustand + Immer 架构、SSE 批量处理、Signal-Fetch 模式 |
| [后端API与数据流](docs/architecture/backend-api-dataflow.md) | API 路由、SSE 管理器、Checkpoint SSOT、数据持久化 |
| [Agent核心实现](docs/architecture/agent-core-implementation.md) | Router Agent 架构、StateGraph 设计、执行流程 |
| [维度与层级数据流](docs/architecture/layer-dimension-dataflow.md) | 三层架构、依赖链机制、Wave 计算、影响树 |
| [工具系统实现](docs/architecture/tool-system-implementation.md) | ToolRegistry 注册、内置工具、Tool-Dimension 绑定 |
| [术语表与交叉引用](docs/architecture/terminology-and-references.md) | 核心术语定义、文档交叉引用、代码路径索引 |

### 快速导航

| 想了解... | 请阅读 |
|----------|--------|
| 前端如何管理状态 | [前端状态管理](docs/architecture/frontend-state-dataflow.md) |
| SSE 如何工作 | [后端API与数据流](docs/architecture/backend-api-dataflow.md) |
| Agent 执行流程 | [Agent核心实现](docs/architecture/agent-core-implementation.md) |
| 维度依赖关系 | [维度与层级数据流](docs/architecture/layer-dimension-dataflow.md) |
| 工具如何注册执行 | [工具系统实现](docs/architecture/tool-system-implementation.md) |

### 其他文档

- **[服务管理](docs/startup-guide.md)** - 服务启动与管理指南
- **[演示文档](docs/village_planning_presentation.md)** - 村庄规划系统演示（Marp 格式）

## 维度依赖与级联修复

### 依赖链机制

系统通过 Wave 调度处理维度间依赖：

- **Layer 1**: 12 维度并行执行（无内部依赖）
- **Layer 2**: 4 维度按 Wave 执行（Wave 1→4，逐级依赖）
- **Layer 3**: 12 维度按 Wave 执行（大部分 Wave 1 并行，`project_bank` Wave 2）

### 级联修复（影响树）

当维度被驳回修复时，系统自动计算影响树：

```
用户修改: natural_environment
    │
    ▼ (Wave 1)
┌─────────────────────────────────────┐
│ resource_endowment, ecological,     │
│ spatial_structure, land_use_planning│
│ disaster_prevention                 │
└─────────────────────────────────────┘
    │
    ▼ (Wave 2)
┌─────────────────────────────────────┐
│ planning_positioning,               │
│ planning_strategies                 │
└─────────────────────────────────────┘
    │
    ▼ (Wave 3)
┌─────────────────────────────────────┐
│ development_goals, project_bank     │
└─────────────────────────────────────┘
```

详见 [维度与层级数据流](docs/architecture/layer-dimension-dataflow.md#依赖链机制)

## 许可证

MIT License