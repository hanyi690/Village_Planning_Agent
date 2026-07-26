# 架构文档导航

本目录包含 Village Planning Agent 系统的完整架构文档。

> **更新日期**: 2026-05-21
> **版本**: v3.0 (统一架构)

## 文档结构

```
docs/architecture/
├── README.md                     # 本文档 - 总览与导航入口
├── 01-system-overview.md         # 系统架构总览
├── 02-agent-core.md              # Agent核心架构
├── 03-layer-dimension.md         # 层级与28维度配置
├── 04-backend-api.md             # 后端API与SSE架构
├── 05-frontend-state.md          # 前端状态管理
├── 06-tool-system.md             # 工具系统架构
├── 08-rag-system.md              # RAG知识库架构
├── 09-database-schema.md         # 数据库Schema
├── 10-deployment-guide.md        # 配置与部署指南
├── 10-frontend-components.md     # 前端组件架构
├── 12-error-handling.md          # 错误处理
├── 13-performance.md             # 性能优化
├── 14-testing.md                 # 测试架构
├── terminology.md                # 术语表
├── file-index.md                 # 文件路径索引
└── gis-system-architecture.md    # GIS系统架构
```

## 核心架构概览

### 目录结构

```
village-planner/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── api/                 # API 路由层
│   │   │   ├── routes.py        # 统一路由
│   │   │   ├── session_routes.py # API端点
│   │   │   └── schemas.py       # 请求/响应模型
│   │   ├── agent/               # LangGraph Agent
│   │   │   ├── graph.py         # StateGraph 定义
│   │   │   ├── state.py         # AgentState 定义
│   │   │   ├── routing.py       # 路由逻辑
│   │   │   └── nodes/           # 节点实现
│   │   ├── config/              # 配置层
│   │   │   ├── phases.yaml      # 28维度配置（唯一来源）
│   │   │   ├── loader.py        # YAML 加载器
│   │   │   └── dependency.py    # 依赖计算
│   │   ├── core/                # 核心基础设施
│   │   │   ├── settings.py      # 配置管理
│   │   │   ├── llm.py           # LLM 工厂
│   │   │   └── events.py        # SSE 事件类型
│   │   ├── database/            # 数据持久层
│   │   │   ├── models.py        # SQLModel 定义
│   │   │   └── operations.py    # 数据库操作
│   │   ├── services/            # 服务层
│   │   │   ├── sse.py           # SSE Manager
│   │   │   ├── runtime.py       # 规划运行时
│   │   │   ├── checkpoint.py    # 检查点服务
│   │   │   └── modules/         # 业务模块
│   │   │       ├── rag/         # RAG 知识检索
│   │   │       ├── gis/         # GIS 空间分析
│   │   │       ├── prompts/     # Prompt 模板
│   │   │       ├── planning_text/ # 规划文本生成
│   │   │       ├── summary/     # 摘要生成
│   │   │       └── data/        # 数据处理
│   │   ├── tools/               # 工具层
│   │   │   ├── registry.py      # 工具注册中心
│   │   │   ├── constants.py     # 工具常量
│   │   │   ├── adapters/        # 外部适配器
│   │   │   ├── core/            # 核心工具
│   │   │   └── analytics/       # 分析工具
│   │   └── utils/               # 工具函数
│   ├── schemas.py               # Pydantic schemas
│   └── village_planning.db      # SQLite 数据库
│
├── frontend/
│   └── src/
│       ├── app/                 # Next.js App Router
│       │   ├── layout.tsx
│       │   └── page.tsx
│       └── features/
│           └── planning/        # 规划功能模块
│               ├── api/         # API 客户端
│               ├── components/  # React 组件
│               ├── config/      # 前端配置
│               ├── constants/   # 常量定义
│               ├── hooks/       # React Hooks
│               ├── store/       # Zustand Store
│               ├── types/       # TypeScript 类型
│               └── utils/       # 工具函数
│
├── data/
│   ├── RAG_doc/                  # 知识库文档与缓存
│   └── database/                 # SQLite 数据库文件
│
├── scripts/                     # 脚本工具
├── docs/                        # 文档
└── tests/                       # 测试
```

## 快速导航

| 文档 | 核心内容 | 关键文件 |
|------|----------|----------|
| [01-system-overview](./01-system-overview.md) | 五层架构、技术栈 | `main.py`, `layout.tsx` |
| [02-agent-core](./02-agent-core.md) | StateGraph、节点、路由 | `agent/graph.py`, `routing.py` |
| [03-layer-dimension](./03-layer-dimension.md) | 28维度、依赖配置 | `config/phases.yaml` |
| [04-backend-api](./04-backend-api.md) | API端点、SSE | `api/session_routes.py` |
| [05-frontend-state](./05-frontend-state.md) | Zustand、组件 | `store/planningStore.ts` |
| [06-tool-system](./06-tool-system.md) | 工具注册、执行 | `tools/registry.py` |
| [08-rag-system](./08-rag-system.md) | 知识检索 | `services/modules/rag/` |
| [09-database-schema](./09-database-schema.md) | 数据模型 | `database/models.py` |
| [10-deployment-guide](./10-deployment-guide.md) | 配置部署 | `.env`, `docker-compose.yml` |
| [10-frontend-components](./10-frontend-components.md) | 前端组件 | `components/` |
| [12-error-handling](./12-error-handling.md) | 错误处理 | - |
| [13-performance](./13-performance.md) | 性能优化 | - |
| [14-testing](./14-testing.md) | 测试架构 | - |

## 核心概念速查

### 三层规划架构

| 层级 | 名称 | 维度数 | 执行模式 |
|------|------|--------|----------|
| Layer 1 | 现状分析 | 12 | 并行（Send API） |
| Layer 2 | 规划思路 | 4 | 波次（依赖驱动） |
| Layer 3 | 详细规划 | 12 | 波次（依赖驱动） |

### 五层技术架构

```
┌─────────────────────────────────────────────────────┐
│  用户层 (React + Zustand + Next.js)                  │
│    ↓ SSE EventSource                                 │
├─────────────────────────────────────────────────────┤
│  后端层 (FastAPI + SSEManager)                       │
│    ↓ 22个API端点                                     │
├─────────────────────────────────────────────────────┤
│  Agent层 (LangGraph StateGraph)                      │
│    ↓ conversation → execute_tools → analyze_dimension → layer_completion_check │
├─────────────────────────────────────────────────────┤
│  工具层 (ToolRegistry + Adapters)                    │
│    ↓ GIS / RAG / Analysis                            │
├─────────────────────────────────────────────────────┤
│  数据层 (SQLite + ChromaDB + 文件)                   │
└─────────────────────────────────────────────────────┘
```

### 核心API端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/sessions` | POST | 创建会话 |
| `/api/sessions/{id}/stream` | GET | SSE事件流 |
| `/api/sessions/{id}/sync` | GET | 断线重连 |
| `/api/sessions/{id}/feedback` | POST | 反馈/审批 |
| `/api/sessions/{id}/checkpoints` | GET | 检查点列表 |
| `/api/sessions/{id}/resume/{cp}` | POST | 恢复执行 |
| `/api/sessions/{id}/reports/{dim}` | GET | 报告全文 |
| `/api/sessions/{id}/step-mode` | PATCH | 切换步进模式 |
| `/api/sessions/{id}/planning-text` | POST/GET | 生成/获取规划文本 |
| `/api/sessions/{id}/planning-text/versions` | GET | 版本列表 |
| `/api/sessions/{id}/export` | POST | 导出文档 |

> 完整端点列表见 [04-backend-api.md](./04-backend-api.md)

### 关键设计原则

| 原则 | 说明 | 实现位置 |
|------|------|----------|
| SSOT | Checkpoint是状态唯一来源 | LangGraph AsyncSqliteSaver |
| 配置驱动 | 维度配置从YAML加载 | `config/phases.yaml` |
| Send API | N维度并行分析 | `routing.py` |
| 依赖驱动 | 同层依赖按波次执行 | `config/dependency.py` |
| SSE单通道 | 所有数据通过SSE推送 | `services/sse.py` |

## 相关资源

- [术语表](./terminology.md) - 所有术语定义
- [文件路径索引](./file-index.md) - 关键代码路径
- [项目开发规范](../../.claude.md) - 项目开发规范
