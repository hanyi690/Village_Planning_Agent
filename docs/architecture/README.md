# 架构文档导航

本目录包含 Village Planning Agent 系统的完整架构文档。

> **更新日期**: 2026-05-08
> **版本**: v2.0 (重组后架构)

## 文档结构

```
docs/architecture/
├── README.md                     # 本文档 - 总览与导航入口
├── 01-system-overview.md         # 系统架构总览
├── 02-agent-core.md              # Agent核心架构
├── 03-layer-dimension.md         # 层级与28维度配置
├── 04-backend-api.md             # 后端API与SSE架构
├── 05-frontend-state.md          # 前端状态与组件架构 [搁置]
├── 06-tool-system.md             # 工具系统架构
├── 08-rag-system.md              # RAG知识库架构
├── 09-database-schema.md         # 数据库Schema
├── terminology.md                # 术语表
├── file-index.md                 # 文件路径索引
├── gis-system-architecture.md    # GIS系统架构
└── _archived/                    # 归档旧文档
```

## 架构变更说明 (v2.0)

### 目录结构重组

项目已完成从双顶层目录到统一 `backend/app/` 结构的重组：

| 旧路径 | 新路径 |
|--------|--------|
| `src/orchestration/` | `backend/app/agent/` |
| `src/config/` | `backend/app/config/` |
| `src/core/` | `backend/app/core/` |
| `src/tools/` | `backend/app/tools/` + `backend/app/modules/gis/` |
| `src/services/` | `backend/app/services/` + `backend/app/modules/rag/` |
| `src/utils/` | `backend/app/utils/` |
| `src/prompts/` | `backend/app/modules/prompts/` |
| `backend/services/` | `backend/app/services/` |
| `backend/constants/` | `backend/app/core/` |
| `backend/database/` | `backend/app/database/` |
| `backend/api/` | `backend/app/api/` |
| `knowledge_base/` | `data/knowledge_base/` |

### 新目录结构

```
village-planner/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── api/
│       ├── agent/
│       ├── config/
│       ├── core/
│       ├── database/
│       ├── modules/
│       │   ├── gis/
│       │   ├── rag/
│       │   └── prompts/
│       ├── services/
│       ├── tools/
│       └── utils/
│
├── frontend/                      [已实现]
│
├── data/
│   ├── knowledge_base/
│   ├── database/
│   └── chroma_db/
│
├── tests/
├── scripts/
├── docs/
└── config/
```

## 快速导航

| 文档 | 核心内容 | 状态 |
|------|----------|------|
| [01-system-overview](./01-system-overview.md) | 五层架构、技术栈 | ✅ |
| [02-agent-core](./02-agent-core.md) | Router Agent、StateGraph | ✅ |
| [03-layer-dimension](./03-layer-dimension.md) | 28维度配置 | ✅ |
| [04-backend-api](./04-backend-api.md) | API端点、SSE | ✅ |
| [05-frontend-state](./05-frontend-state.md) | Zustand状态、组件 | ✅ 已实现 |
| [06-tool-system](./06-tool-system.md) | 工具注册 | ✅ |
| [gis-system-architecture](./gis-system-architecture.md) | GIS系统 | ✅ |
| [08-rag-system](./08-rag-system.md) | 知识库 | ✅ |
| [10-frontend-components](./10-frontend-components.md) | 前端组件架构 | ✅ |
| [file-index](./file-index.md) | 文件路径索引 | ✅ |

## 核心概念速查

### 三层规划架构

| 层级 | 名称 | 维度数 | 执行模式 |
|------|------|--------|----------|
| Layer 1 | 现状分析 | 12 | Map-Reduce并行 |
| Layer 2 | 规划思路 | 4 | Wave波次执行 |
| Layer 3 | 详细规划 | 12 | Wave波次执行 |

### 五层技术架构

```
用户层 (React + Zustand)          [已实现]
    ↓ SSE
后端层 (FastAPI + SSEManager)
    ↓ LangGraph
Agent层 (Router Agent + StateGraph)
    ↓ ToolRegistry
工具层 (GIS + RAG + 分析工具)
    ↓
数据层 (SQLite + ChromaDB + 文件)
```

### 关键设计原则

| 原则 | 说明 | 实现位置 |
|------|------|----------|
| SSOT | Checkpoint是状态唯一来源 | LangGraph Checkpointer |
| Router Agent | conversation_node中央路由 | `backend/app/agent/graph.py` |
| Send API | N维度并行分析 | `Send(analyze_dimension)` |
| Wave机制 | 同层依赖按波次执行 | `backend/app/config/phases.yaml` |
| 模块化 | GIS/RAG/Prompts独立模块 | `backend/app/modules/` |

## 相关资源

- [术语表](./terminology.md) - 所有术语定义
- [文件路径索引](./file-index.md) - 关键代码路径
- [CLAUDE.md](../../.claude/CLAUDE.md) - 项目开发规范