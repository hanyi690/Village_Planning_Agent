# 系统架构总览

本文档提供 Village Planning Agent 系统的整体架构概览。

> **更新日期**: 2026-05-21
> **版本**: v3.2 (统一架构)

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
│  文件: frontend/src/features/planning/                           │
│  状态: ✅ 已实现                                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓ SSE (Server-Sent Events)
┌─────────────────────────────────────────────────────────────────┐
│                        后端层 (Backend Layer)                     │
│  FastAPI + SSEManager + PlanningRuntimeService                  │
│  文件: backend/app/api/, backend/app/services/                   │
│  端点: 7个核心API                                                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓ LangGraph API
┌─────────────────────────────────────────────────────────────────┐
│                        Agent层 (Agent Layer)                      │
│  Router Agent + StateGraph + Send API                           │
│  文件: backend/app/agent/                                        │
│  节点: conversation → execute_tools → analyze_dimension          │
└─────────────────────────────────────────────────────────────────┘
                              ↓ ToolRegistry
┌─────────────────────────────────────────────────────────────────┐
│                        工具层 (Tool Layer)                        │
│  GIS Tools + RAG Tools + Analysis Tools                         │
│  文件: backend/app/tools/, backend/app/services/modules/         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        数据层 (Data Layer)                        │
│  SQLite + ChromaDB + File Storage + GIS Data                    │
│  文件: backend/app/database/, data/                              │
│  模型: PlanningSession, DimensionReport                          │
└─────────────────────────────────────────────────────────────────┘
```

### 各层职责

| 层级 | 职责 | 关键组件 |
|------|------|----------|
| 用户层 | UI渲染、状态管理、SSE接收 | `planningStore.ts`, `useSSE.ts` |
| 后端层 | API路由、SSE推送、状态持久化 | `SSEManager`, `PlanningRuntimeService` |
| Agent层 | 意图路由、维度分析、状态流转 | `conversation_node`, `analyze_dimension` |
| 工具层 | GIS查询、知识检索、数据分析 | `ToolRegistry`, `modules/rag/` |
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
    ↓ state_to_ui_status()
前端 Zustand Store
    ↓
React UI
```

### 2. Router Agent 模式

采用中央路由模式，单一 StateGraph：

```
用户输入 → conversation_node (LLM处理)
                ↓ after_conversation
         ├─ 闲聊/问答 → END
         ├─ 工具调用 → execute_tools
         └─ 推进规划 → Send(N维度)
```

**优势**：
- 单一入口点，逻辑清晰
- 状态流转可控
- 易于调试和监控

### 3. Send API 并行机制

使用 LangGraph Send API 实现维度并行：

```python
# backend/app/agent/routing.py
[Send("analyze_dimension", {"dimension_key": key}) for key in pending_dims]
```

- Layer 1：12维度完全并行
- Layer 2/3：按依赖关系分批并行

### 4. 依赖驱动执行

同一层级内存在依赖的维度按依赖关系顺序执行：

```
Layer 2:
  Wave 0: resource_endowment (无同层依赖)
  Wave 1: planning_positioning (依赖 resource_endowment)
  Wave 2: development_goals (依赖 resource_endowment, planning_positioning)
  Wave 3: planning_strategies (依赖全部)
```

---

## 三层规划架构

### 架构概览

村庄规划采用三层递进式架构：

| 层级 | 名称 | 维度数 | 执行模式 | 目标 |
|------|------|--------|----------|------|
| Layer 1 | 现状分析 | 12 | 并行（Send API） | 分析村庄现状 |
| Layer 2 | 规划思路 | 4 | 依赖驱动 | 确定规划方向 |
| Layer 3 | 详细规划 | 12 | 依赖驱动 | 制定具体方案 |

### 数据流向

```
用户输入村庄信息
    ↓
Layer 1 (现状分析)
    ├─ location: 区位分析
    ├─ socio_economic: 社会经济分析
    ├─ ... (共12维度并行)
    ↓ (全部完成后)
Layer 2 (规划思路)
    ├─ resource_endowment → planning_positioning → development_goals → planning_strategies
    ↓ (全部完成后)
Layer 3 (详细规划)
    ├─ 各规划维度（依赖Layer2）
    ↓
规划报告输出
```

---

## 关键文件精选

### Agent 核心

| 文件 | 职责 |
|------|------|
| `backend/app/agent/graph.py` | StateGraph 定义（3节点） |
| `backend/app/agent/state.py` | AgentState 定义 |
| `backend/app/agent/routing.py` | after_conversation, after_analysis |
| `backend/app/config/phases.yaml` | 28维度配置（唯一来源） |

### 后端 API

| 文件 | 职责 |
|------|------|
| `backend/app/api/session_routes.py` | 7个核心 Session 端点 |
| `backend/app/api/routes.py` | 路由聚合 + 健康检查 |
| `backend/app/services/sse.py` | SSE 推送管理 |
| `backend/app/services/runtime.py` | 规划运行时服务 |
| `backend/app/database/models.py` | SQLModel 数据模型 |

### 前端核心

| 文件 | 职责 |
|------|------|
| `frontend/src/features/planning/store/planningStore.ts` | Zustand 状态管理 |
| `frontend/src/features/planning/hooks/useSSE.ts` | SSE 连接 Hook |
| `frontend/src/features/planning/api/planning-api.ts` | API 客户端 |

### 工具与模块

| 文件 | 职责 |
|------|------|
| `backend/app/tools/registry.py` | 工具注册中心 |
| `backend/app/services/modules/rag/service.py` | 知识库检索服务 |
| `backend/app/services/modules/gis/service.py` | GIS 空间分析服务 |
| `backend/app/services/modules/prompts/` | Prompt 模板模块 |

完整文件索引见 [file-index.md](./file-index.md)

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - Agent 核心架构详解
- [03-layer-dimension](./03-layer-dimension.md) - 28维度完整配置
- [04-backend-api](./04-backend-api.md) - 后端 API 详解
- [05-frontend-state](./05-frontend-state.md) - 前端状态管理详解
- [terminology](./terminology.md) - 术语定义