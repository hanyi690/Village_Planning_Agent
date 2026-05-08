# 系统架构总览

本文档提供 Village Planning Agent 系统的整体架构概览。

> **更新日期**: 2026-05-08
> **版本**: v2.0 (重组后架构)

## 目录

- [系统定位](#系统定位)
- [技术栈概览](#技术栈概览)
- [五层架构](#五层架构)
- [核心设计原则](#核心设计原则)
- [三层规划架构](#三层规划架构)
- [关键文件精选](#关键文件精选)

---

## 系统定位

Village Planning Agent 是一个基于 LangGraph 的智能村庄规划助手系统：

- **核心功能**：村庄规划报告自动生成
- **技术特点**：Agent架构、SSE实时推送、RAG知识库、GIS空间分析
- **应用场景**：村庄现状分析、规划思路生成、详细规划制定

---

## 技术栈概览

| 层级 | 技术 | 版本 |
|------|------|------|
| 前端框架 | Next.js + React | 15.x |
| 状态管理 | Zustand + Immer | 4.x |
| 后端框架 | FastAPI | 0.100+ |
| Agent框架 | LangGraph | 0.2+ |
| LLM | Claude/Qwen | - |
| 向量数据库 | ChromaDB | - |
| 关系数据库 | SQLite (WAL) | - |
| GIS库 | GeoPandas, OSMnx | - |
| 容器化 | Docker Compose | - |

---

## 五层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层 (User Layer)                        │
│  Next.js SPA + Zustand State + SSE Hook                         │
│  文件: frontend/src/                                             │
│  状态: ⏸️ 搁置                                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓ SSE (Server-Sent Events)
┌─────────────────────────────────────────────────────────────────┐
│                        后端层 (Backend Layer)                     │
│  FastAPI + SSEManager + CheckpointService                       │
│  文件: backend/app/api/, backend/app/services/                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓ LangGraph API
┌─────────────────────────────────────────────────────────────────┐
│                        Agent层 (Agent Layer)                      │
│  Router Agent + StateGraph + Send API                           │
│  文件: backend/app/agent/                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓ ToolRegistry
┌─────────────────────────────────────────────────────────────────┐
│                        工具层 (Tool Layer)                        │
│  GIS Tools + RAG Tools + Analysis Tools                         │
│  文件: backend/app/tools/, backend/app/modules/                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        数据层 (Data Layer)                        │
│  SQLite + ChromaDB + File Storage + GIS Data                    │
│  文件: backend/app/database/, data/                              │
└─────────────────────────────────────────────────────────────────┘
```

### 各层职责

| 层级 | 职责 | 关键组件 |
|------|------|----------|
| 用户层 | UI渲染、状态管理、SSE接收 | `planningStore.ts`, `useSSEConnection.ts` |
| 后端层 | API路由、SSE推送、状态持久化 | `SSEManager`, `CheckpointService` |
| Agent层 | 意图路由、维度分析、状态流转 | `conversation_node`, `analyze_dimension` |
| 工具层 | GIS查询、知识检索、数据分析 | `ToolRegistry`, `rag/service.py` |
| 数据层 | 数据存储、向量检索、文件管理 | `models.py`, `vector_store.py` |

---

## 核心设计原则

### 1. SSOT (Single Source of Truth)

Checkpoint 是状态的唯一真实来源：

- 前端状态从 Checkpoint 派生
- Agent 状态存储在 Checkpoint
- 数据恢复从 Checkpoint 加载

```
Checkpoint (LangGraph AsyncSqliteSaver)
    ↓ deriveUIState()
前端 Zustand Store
    ↓
React UI
```

### 2. Router Agent 模式

采用中央路由模式，单一 StateGraph：

```
用户输入 → conversation_node (LLM处理)
                ↓ intent_router
         ├─ 闲聊/问答 → END
         ├─ 工具调用 → execute_tools
         └─ 推进规划 → route_by_phase → Send(N维度)
```

**优势**：
- 单一入口点，逻辑清晰
- 状态流转可控
- 易于调试和监控

### 3. Send API 并行机制

使用 LangGraph Send API 实现维度并行：

```python
# backend/app/agent/graph.py
Send(analyze_dimension, {"dimension_key": key, "wave": wave})
```

- Layer 1：12维度完全并行
- Layer 2/3：按 Wave 分批并行

### 4. Wave 波次机制

同一层级内存在依赖的维度按 Wave 顺序执行：

```
Layer 2:
  Wave 1: resource_endowment (无依赖)
  Wave 2: planning_positioning (依赖Wave1)
  Wave 3: development_goals (依赖Wave1,2)
  Wave 4: planning_strategies (依赖全部)
```

---

## 三层规划架构

### 架构概览

村庄规划采用三层递进式架构：

| 层级 | 名称 | 维度数 | 执行模式 | 目标 |
|------|------|--------|----------|------|
| Layer 1 | 现状分析 | 12 | Map-Reduce并行 | 分析村庄现状 |
| Layer 2 | 规划思路 | 4 | Wave波次执行 | 确定规划方向 |
| Layer 3 | 详细规划 | 12 | Wave波次执行 | 制定具体方案 |

### 数据流向

```
用户输入村庄信息
    ↓
Layer 1 (现状分析)
    ├─ location: 区位分析
    ├─ socio_economic: 社会经济分析
    ├─ ... (共12维度)
    ↓ (全部完成后)
Layer 2 (规划思路)
    ├─ Wave 1: resource_endowment
    ├─ Wave 2: planning_positioning
    ├─ Wave 3: development_goals
    ├─ Wave 4: planning_strategies
    ↓ (全部完成后)
Layer 3 (详细规划)
    ├─ Wave 1-2: 各规划维度
    ↓
规划报告输出
```

---

## 关键文件精选

### Agent 核心

| 文件 | 职责 |
|------|------|
| `backend/app/agent/graph.py` | StateGraph 定义 |
| `backend/app/agent/state.py` | UnifiedPlanningState 定义 |
| `backend/app/agent/routing.py` | intent_router, route_by_phase |
| `backend/app/config/phases.yaml` | 28维度配置（唯一来源） |

### 后端 API

| 文件 | 职责 |
|------|------|
| `backend/app/services/sse.py` | SSE 推送管理 |
| `backend/app/api/routes.py` | 统一路由入口 |
| `backend/app/database/engine.py` | 数据库引擎与Checkpointer |

### 前端核心 [搁置]

| 文件 | 职责 |
|------|------|
| `frontend/src/stores/planningStore.ts` | Zustand 状态管理 |
| `frontend/src/hooks/planning/useSSEConnection.ts` | SSE 连接 Hook |

### 工具与 RAG

| 文件 | 职责 |
|------|------|
| `backend/app/tools/registry.py` | 工具注册中心 |
| `backend/app/modules/rag/service.py` | 知识库检索服务 |
| `backend/app/modules/rag/vector_store.py` | 向量存储 |

完整文件索引见 [file-index.md](./file-index.md)

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - Agent 核心架构详解
- [03-layer-dimension](./03-layer-dimension.md) - 28维度完整配置
- [04-backend-api](./04-backend-api.md) - 后端 API 详解
- [05-frontend-state](./05-frontend-state.md) - 前端状态管理详解 [搁置]
- [terminology](./terminology.md) - 术语定义