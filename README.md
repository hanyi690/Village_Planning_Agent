# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统：**一条闭环管线** = 文本规划（L1/L2/L3 28 维度）+ 空间布局（PARSE + EXECUTE），全程 KG 语义桥接 + RAG 知识检索。

## 核心特性

- **6 节点主图**：`conversation` → `analyze_dimension` / `execute_tools` / `explore` / `gis_agent` → `layer_completion_check`
- **三层递进规划**：现状分析(L1, 12 维) → 规划思路(L2, 4 维) → 详细规划(L3, 12 维)
- **五层模块架构**：`Schema ← Data ← SpatialOps ← KG ← Agent`（单向依赖）
- **RAG 知识检索**：Small-to-Big + 层级感知，法规条文与技术指标智能注入
- **SSE 单通道**：所有数据通过 SSE 推送，Checkpoint 为唯一数据源（SSOT）
- **级联修复**：驳回后自动计算影响树，按依赖链波次重分析
- **GIS 空间布局**：PARSE ReAct（意图解析）+ LAYOUT 混合管线（骨架 + ReAct + Evaluator Gate）

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Village Planning Agent                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌────────────┐    ┌───────────────┐    ┌────────────────────────┐  │
│  │ Frontend   │───▶│  FastAPI API  │───▶│  LangGraph 主图 (6节点) │  │
│  │ Next.js 14 │SSE │  /api/sessions│    │  backend/app/agent/    │  │
│  │ + MapLibre │    │  /* (7端点)   │    │  graph.py              │  │
│  └────────────┘    └───────────────┘    └───────────┬────────────┘  │
│       │                                            │               │
│       │                            ┌────────────────┼───────────┐   │
│       │                            ▼                ▼           ▼   │
│       │                      ┌─────────┐  ┌──────────────┐ ┌──────┐ │
│       │                      │ analyze │  │  gis_agent   │ │ RAG  │ │
│       │                      │dimension│  │ PARSE+LAYOUT │ │Chroma│ │
│       │                      └────┬────┘  └──────┬───────┘ └──────┘ │
│       │                           │              │                  │
│       │                           ▼              ▼                  │
│       │                   ┌──────────────────────────────┐          │
│       │                   │  五层模块 (app/modules/)      │          │
│       │                   │  schema ← data ← spatial_ops │          │
│       │                   │         ← kg ← (rag)         │          │
│       │                   └──────────────────────────────┘          │
│       │                                                             │
│       └────────────────── SSE 单通道 ◄─────────────────────────────│
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 6 节点主图

```
START → conversation ──► analyze_dimension ──► layer_completion_check
              │                ▲                      │
              ├─► execute_tools─┘                      │
              ├─► gis_agent ──────────────────────────┘
              └─► END (闲聊/问答)

layer_completion_check (phase=completed, 非 step_mode)
              └─► explore ──► gis_agent ──► END
```

详见 [docs/architecture/agent-graph.md](docs/architecture/agent-graph.md)

### 三层规划流程

```
Layer 1 (现状分析)  ──▶  Layer 2 (规划思路)  ──▶  Layer 3 (详细规划)
12 维度并行              4 维度波次执行          12 维度波次执行
(Map-Reduce)             (Wave 1-4)             (Wave 1-2)
```

## 快速开始

### 环境要求

- Python 3.13+
- Node.js 18+（推荐 20+）
- LLM API Key（DashScope / DeepSeek / OpenAI / 智谱AI）

### 安装

```bash
# 后端
pip install -r requirements.txt

# 前端
cd frontend && npm install
```

### 配置

复制 `.env.example` 为 `.env` 并填写：

```env
# LLM 配置（默认 qwen-plus 系列，阿里云 DashScope）
LLM_PROVIDER=openai                       # openai | deepseek | zhipuai
OPENAI_API_KEY=your_dashscope_api_key
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus                       # qwen-plus | qwen3.5-plus | deepseek-chat | gpt-4o
MAX_TOKENS=65536

# Embedding（推荐阿里云 DashScope，内存占用低）
EMBEDDING_PROVIDER=aliyun
DASHSCOPE_API_KEY=your_dashscope_api_key
ALIYUN_EMBEDDING_MODEL=text-embedding-v4

# 多模态（可选）
MULTIMODAL_ENABLED=true
MULTIMODAL_MODEL=qwen3.5-plus
```

> 支持 DeepSeek / OpenAI / 智谱AI 切换，均为 OpenAI 兼容接口。

### 启动

```bash
# 后端（端口 8000）
python backend/main.py

# 前端（端口 3000）
cd frontend && npm run dev
```

访问 http://localhost:3000

### Docker 部署

```bash
cp .env.example .env  # 填写 API Key
docker-compose up -d  # 后端 8003 / 前端 3003
```

### 构建知识库

```bash
# 知识库状态
python -m app.modules.rag.cli status

# 重新导入文档
python -m app.modules.rag.cli reload <file_path>

# 删除文档
python -m app.modules.rag.cli delete <source_name>

# 验证一致性
python -m app.modules.rag.cli verify <source_name>
```

支持的文档格式：`.md`, `.txt`, `.pdf`, `.pptx`, `.ppt`, `.docx`, `.doc`

**源文档目录**：`data/policies/`

## 项目结构

```
Village_Planning_Agent/
├── backend/
│   ├── main.py                         # 应用入口（lifespan + 中间件）
│   └── app/
│       ├── main.py                     # FastAPI app 定义
│       ├── api/                        # API 路由层
│       │   ├── routes.py               # 统一路由器
│       │   ├── session_routes.py       # 7 核心端点
│       │   ├── gis_test_routes.py      # GIS 测试（开发）
│       │   └── schemas.py              # 请求/响应模型
│       ├── agent/                      # LangGraph Agent 核心
│       │   ├── graph.py                # create_unified_planning_graph (6节点)
│       │   ├── routing.py              # after_conversation + after_analysis
│       │   ├── state.py                # AgentState, PlanningPhase
│       │   ├── conversation/node.py    # 中央路由节点
│       │   ├── tools/execute_node.py   # 工具执行节点
│       │   ├── analysis/               # 维度分析（RAG + KG + DataPipeline）
│       │   ├── explore/                # EXPLORE 认知引擎（桥接 + 概要索引）
│       │   ├── completion/node.py      # 层级完成检测 + interrupt
│       │   └── gis/                    # GIS Agent (PARSE + LAYOUT)
│       ├── modules/                    # 五层业务模块
│       │   ├── schema/                 # ① 类型契约层（零依赖）
│       │   ├── data/                   # ② 数据获取层
│       │   ├── spatial_ops/            # ③ 空间分析层
│       │   ├── kg/                     # ④ 知识图谱层
│       │   ├── rag/                    # RAG 知识检索
│       │   ├── planning_text/          # 规划文本生成
│       │   └── prompts/                # Prompt 模板
│       ├── services/                   # 服务层
│       │   ├── runtime.py              # PlanningRuntimeService 单例
│       │   ├── sse/                    # SSE 管理器
│       │   ├── checkpoint.py           # 检查点服务
│       │   └── report_store.py         # 报告存储
│       ├── tools/                      # 工具系统（access/gis/intent）
│       ├── database/                   # 数据持久层（SQLModel）
│       ├── core/                       # 核心基础设施（llm, settings）
│       └── config/                     # 配置层（YAML 驱动）
├── frontend/
│   └── src/
│       ├── app/                        # Next.js App Router
│       └── features/
│           ├── planning/               # 规划功能模块
│           │   ├── store/planningStore.ts   # Zustand 核心状态
│           │   ├── hooks/              # SSE 连接 + 流式渲染
│           │   ├── api/                # API 客户端
│           │   └── components/         # React 组件
│           └── gis-test/               # GIS 测试模块
├── data/
│   ├── policies/                       # RAG 源文档
│   └── gis/                            # GIS 数据
├── docs/                               # 文档（见 docs/README.md）
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

## API 端点

### 核心 API（`/api/sessions/*`）

| # | 方法 | 路径 | 说明 |
|---|------|------|------|
| 1 | POST | `/api/sessions` | 创建会话（支持文件上传） |
| 2 | GET | `/api/sessions/{id}/stream` | SSE 事件流（单通道） |
| 3 | GET | `/api/sessions/{id}/sync` | 断线重连（`?from_seq=N`） |
| 4 | POST | `/api/sessions/{id}/feedback` | 反馈（approve / reject 触发级联修订） |
| 5 | GET | `/api/sessions/{id}/checkpoints` | 检查点列表 |
| 6 | POST | `/api/sessions/{id}/resume/{checkpoint_id}` | 从检查点恢复 |
| 7 | GET | `/api/sessions/{id}/reports/{dim_key}` | 维度报告全文 |

> 旧版 `/api/planning/*` 已**废弃并移除**。

详见 [docs/architecture/backend-api.md](docs/architecture/backend-api.md)

## SSE 流式事件

| 事件类型 | 说明 |
|---------|------|
| `connected` | SSE 连接建立 |
| `layer_started` | 层级开始执行 |
| `dimension_start` | 维度开始分析 |
| `dimension_delta` | 维度内容增量（Token 级） |
| `dimension_complete` | 维度分析完成 |
| `layer_completed` | 层级完成 |
| `tool_call` | 工具开始执行 |
| `tool_progress` | 工具执行进度 |
| `tool_result` | 工具执行结果 |
| `gis_layer_update` | GIS 图层更新 |
| `checkpoint_saved` | 检查点已保存 |
| `pause` | 步进暂停 |
| `resumed` | 恢复执行 |
| `cascade_impact` | 级联影响（修复触发） |
| `cascade_complete` | 级联修复完成 |
| `heartbeat` | 心跳（15 秒无事件） |

## 三层规划维度

### Layer 1: 现状分析（12 维度并行）

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

### Layer 2: 规划思路（4 维度波次执行）

| Wave | 维度键 | 维度名称 | 依赖 |
|------|--------|----------|------|
| 1 | `resource_endowment` | 资源禀赋分析 | 6 个 Layer 1 维度 |
| 2 | `planning_positioning` | 规划定位分析 | `resource_endowment` |
| 3 | `development_goals` | 发展目标分析 | `resource_endowment`, `planning_positioning` |
| 4 | `planning_strategies` | 规划策略分析 | 前 3 个 Layer 2 维度 |

### Layer 3: 详细规划（12 维度波次执行）

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

## 文档

完整的文档体系导航见 [docs/README.md](docs/README.md)。

| 想了解... | 请阅读 |
|----------|--------|
| 系统设计理念 | [docs/design/00_SYSTEM_DESIGN.md](docs/design/00_SYSTEM_DESIGN.md) |
| 主图怎么跑 | [docs/architecture/agent-graph.md](docs/architecture/agent-graph.md) |
| API 端点 | [docs/architecture/backend-api.md](docs/architecture/backend-api.md) |
| 前端架构 | [docs/architecture/frontend.md](docs/architecture/frontend.md) |
| RAG 检索 | [docs/architecture/rag-system.md](docs/architecture/rag-system.md) |
| 闭环管线设计 | [docs/design/04_PLANNING_PIPELINE.md](docs/design/04_PLANNING_PIPELINE.md) |
| 术语表 | [docs/reference/terminology.md](docs/reference/terminology.md) |

## 许可证

MIT License
