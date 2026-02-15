# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 的智能村庄规划系统，提供 Web 应用和 CLI 工具两种使用方式，采用 AsyncSqliteSaver 实现状态持久化。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python13.com/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0.8-green.svg)](https://github.com/langchain-ai/langgraph)

---

## 核心特性

### Web 应用
- **现代化界面**: 基于 Next.js 14 + Tailwind CSS 的响应式 Web 界面
- **维度级流式响应**: 实时 Token → 前端显示 < 100ms 延迟
- **状态持久化**: AsyncSqliteSaver 自动保存状态到 SQLite，支持会话恢复
- **智能文件上传**: 支持多种编码自动检测（UTF-8/GBK/GB2312）和多格式解析（.txt/.md/.docx/.pdf）
- **交互式审查**: 支持人工审查、通过/驳回、回退修复
- **历史会话**: 支持查看和加载历史会话记录
- **检查点导航**: 时间轴可视化，支持检查点对比和回退

### 规划引擎
- **三层架构**: 现状分析 → 规划思路 → 详细规划
- **并行执行**: 12+4+12 个维度并行处理，高效执行
- **智能恢复**: 检查点自动持久化，支持从任意阶段恢复
- **状态筛选优化**: 智能过滤相关维度，节省 40-60% LLM token
- **统一规划器**: 基于统一基类的通用规划器架构

---

## 快速开始

### 环境要求
- Python 3.9+
- Node.js 18+
- LLM API Key (ZhipuAI / OpenAI / DeepSeek)

### 安装

**1. 克隆项目**
```bash
git clone https://github.com/yourusername/village-planning-agent.git
cd village-planning-agent
```

**2. 配置环境变量**
创建 `.env` 文件：
```env
# LLM 配置 (任选其一)
ZHIPUAI_API_KEY=your_zhipuai_api_key_here
OPENAI_API_KEY=your_openai_api_key_here

# LLM 模型
LLM_MODEL=deepseek-chat
MAX_TOKENS=65536

OPENAI_API_BASE=https://api.deepseek.com/v1

# 数据库模式
USE_ASYNC_DATABASE=true

# 向量数据库配置
VECTOR_STORE_DIR=data/vectordb
VECTORDB_PERSIST=true

# LangSmith 追踪 (可选)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_PROJECT=village-planning-agent
```

**3. 安装依赖**
```bash
pip install -r requirements.txt
cd frontend
npm install
```

### 启动应用

**启动后端**:
```bash
python backend/main.py
```

**启动前端** (新终端):
```bash
npm run dev
```

**访问应用**: http://localhost:3000

---

## 数据流架构

### 核心设计理念

**后端状态为单一真实源 (Single Source of Truth)**
- Controller 只负责数据搬运,不做任何业务逻辑判断
- 幂等性: 无论轮询多少次,只要后端状态不变,前端渲染结果不变

### 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端 (Next.js)                      │
│  ┌──────────────────────────────────────────────────┐     │
│  │         UnifiedPlanningContext                 │     │
│  │  ┌──────────────┐  ┌──────────────┐             │     │
│  │  │ TaskController│  │  ReviewPanel │             │     │
│  │  │ (REST 轮询)   │  │ (条件渲染)   │             │     │
│  │  └──────────────┘  └──────────────┘             │     │
│  └──────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
                        ↓ REST 轮询 (每2秒) + SSE 流式
┌─────────────────────────────────────────────────────────────┐
│                       后端 (FastAPI)                       │
│  ┌──────────────────────────────────────────────────┐     │
│  │   LangGraph 主图 (三层规划系统)                 │     │
│  │   ↓ AsyncSqliteSaver (状态持久化)              │     │
│  │   ↓ checkpoints 表 (自动管理)                   │     │
│  │   - layer_X_completed                           │     │
│  │   - analysis_dimension_reports                 │     │
│  │   - concept_dimension_reports                  │     │
│  │   - detailed_dimension_reports                 │     │
│  │   - pause_after_step                            │     │
│  └──────────────────────────────────────────────────┘     │
│  ┌──────────────────────────────────────────────────┐     │
│  │   planning_sessions 表 (业务元数据)             │     │
│  │   - session_id, project_name                  │     │
│  │   - status, created_at                        │     │
│  └──────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 数据流详解

#### 1. TaskController 数据流（状态同步）

```
前端: TaskController (每2秒轮询)
  ↓
后端: GET /api/planning/status/{session_id}
  ↓
从 AsyncSqliteSaver 读取完整状态
  ↓
返回: SessionStatusResponse
  - pauseAfterStep (暂停状态)
  - layer_X_completed (层级完成)
  - currentLayer, previousLayer, pendingReviewLayer
  - executionComplete, executionError
  ↓
前端: syncBackendState(statusData)
  ↓
直接更新 Context 状态 (不做任何判断)
  ↓
UI 重新渲染 (条件渲染 ReviewPanel)
```

**关键特性**:
- ✅ **纯数据搬运**: Controller 只负责获取状态和同步,不做任何业务逻辑判断
- ✅ **幂等性**: 无论轮询多少次,只要后端状态不变,前端渲染结果不变

#### 2. SSE 数据流（流式文本）

```
前端: useTaskSSE
  ↓
后端: GET /api/planning/stream/{session_id}
  ↓
维度级批处理
  ↓
SSE 事件推送:
  - dimension_delta: {dimension_key, dimension_name, layer, chunk, accumulated}
  - dimension_complete: {dimension_key, dimension_name, layer, full_content}
  - error: {error}
  ↓
前端: 实时显示流式文本
```

#### 3. AsyncSqliteSaver 状态持久化

```
LangGraph 执行图
  ↓
状态变化 → AsyncSqliteSaver.put()
  ↓
自动序列化 → checkpoints 表
  │
  ├─ checkpoints (主表)
  │  ├─ thread_id
  │  ├─ checkpoint_id
  │  └─ checkpoint (JSON/二进制)
  │
  └─ checkpoints_blobs (二进制数据)
     ├─ checkpoint_id
     └─ blob
```

#### 4. 暂停/恢复流程

```
步进模式 (step_mode=True) + 层级完成 (layer_X_completed=True)
  ↓
PauseManagerNode 检测到暂停条件
  ↓
设置 state["pause_after_step"] = True
  ↓
路由到 END 终止执行
  ↓
前端 REST 轮询检测到 pauseAfterStep=true
  ↓
TaskController.syncBackendState() 更新状态
  ↓
Context.isPaused = true, Context.pendingReviewLayer = 1
  ↓
条件渲染: {isPaused && <ReviewPanel layer={pendingReviewLayer} />}
  ↓
用户批准 → POST /api/planning/review/{id}?action=approve
  ↓
清除 pause 标志 → 恢复执行
  ↓
前端 REST 轮询检测到 pauseAfterStep=false
  ↓
Context.isPaused = false
  ↓
ReviewPanel 自动消失
```

---

## 技术优势

### 1. 极简版 TaskController
- **纯数据搬运**: 只负责获取状态和同步,不做任何业务逻辑判断
- **幂等性**: 无论轮询多少次,只要后端状态不变,前端渲染结果不变
- **代码简洁**: 删除了所有 Ref 和去重逻辑,代码量减少约 60%

### 2. 状态驱动 UI (State Driven)
- **后端状态为单一真实源**: 前端 UI 直接根据后端状态渲染
- **条件渲染**: `{isPaused && <ReviewPanel layer={pendingReviewLayer} />}`
- **无重复渲染**: React 足够聪明,不会重复渲染重型组件

### 3. AsyncSqliteSaver 状态持久化
- **自动管理**: LangGraph 自动保存状态,无需手动维护
- **双重表设计**: checkpoints 表 + checkpoints_blobs 表
- **毫秒级恢复**: 从 checkpoint 毫秒级还原完整状态
- **数据一致性**: AI 状态 = 数据库内容,天然匹配

### 4. SSE/REST 解耦
- **REST**: 可靠状态查询,每 2 秒轮询
- **SSE**: 维度级流式文本,实时推送
- **无去重风险**: 消除事件丢失或重复

### 5. 双表精简设计
- **业务表**: 只存储元数据 (session_id, project_name, status)
- **检查点表**: AsyncSqliteSaver 自动管理完整状态
- **代码简洁**: 删除了 12+ 个手动维护的字段

---

## 项目结构

```
Village_Planning_Agent/
├── backend/                      # FastAPI 后端
│   ├── main.py                    # 应用入口
│   ├── api/
│   │   └── planning.py            # 规划 API (REST + SSE)
│   ├── database/
│   │   ├── models.py               # 数据库模型（精简版）
│   │   └── operations_async.py     # 异步数据库操作
│   └── requirements.txt            # Python 依赖
├── frontend/                     # Next.js 14 前端
│   └── src/
│       ├── app/                    # Next.js App Router
│       ├── contexts/               # React Context
│       │   └── UnifiedPlanningContext.tsx
│       ├── controllers/            # 状态控制器
│       │   └── TaskController.tsx  # 极简版 TaskController
│       ├── components/chat/        # 聊天组件
│       │   ├── ChatPanel.tsx      # 主聊天界面
│       │   ├── ReviewPanel.tsx    # 审查面板
│       │   └── MessageList.tsx    # 消息列表
│       └── hooks/                  # 自定义 Hooks
│           └── useStreamingRender.ts  # 流式渲染
├── src/                          # 核心规划引擎
│   ├── orchestration/              # 编排层
│   │   └── main_graph.py          # LangGraph 主图
│   ├── subgraphs/                 # 三层子图
│   ├── planners/                   # 规划器层
│   ├── nodes/                      # 节点层
│   └── utils/                      # 核心工具类
└── data/                          # 数据目录
    └── village_planning.db        # SQLite 数据库
```

---

## 配置说明

### LLM 配置

**ZhipuAI (推荐)**:
```env
ZHIPUAI_API_KEY=your_key
LLM_MODEL=glm-4-flash
MAX_TOKENS=65536
```

**OpenAI**:
```env
OPENAI_API_KEY=your_key
LLM_MODEL=gpt-4o-mini
```

**DeepSeek**:
```env
OPENAI_API_KEY=your_deepseek_key
OPENAI_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 数据库配置

```env
# 数据库模式
USE_ASYNC_DATABASE=true
```

---

## 文档

详细实现文档：

- **[智能体架构](docs/agent.md)** - LangGraph 架构、三层规划系统、状态持久化
- **[后端实现](docs/backend.md)** - FastAPI 架构、API 端点、AsyncSqliteSaver 集成
- **[前端实现](docs/frontend.md)** - Next.js 技术栈、极简版 TaskController、状态驱动 UI
- **[前端组件架构](FRONTEND_COMPONENT_ARCHITECTURE.md)** - 组件设计、状态管理、数据流
- **[前端视觉指南](FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范、组件样式

---

## 常见问题

### Q: 状态为什么没有持久化？
A: 确认以下项：
- 已安装 `langgraph-checkpoint-sqlite` 包
- `main_graph.py` 使用 `get_sqlite_checkpointer()`
- 检查 `data/village_planning.db` 权限正确

### Q: 如何查看 checkpoint 数据？
A: 使用 SQLite 客户端：
```sql
SELECT * FROM checkpoints WHERE thread_id = 'your_session_id';
SELECT * FROM checkpoints_blobs WHERE checkpoint_id = 'your_checkpoint_id';
```

### Q: 如何恢复会话？
A: 使用相同的 `thread_id` 重新创建图：
```python
checkpointer = get_sqlite_checkpointer()
graph = create_village_planning_graph(checkpointer=checkpointer)
config = {"configurable": {"thread_id": "your_session_id"}}
state = await graph.get_state(config)  # 自动从 checkpoint 恢复
```

### Q: 前端为什么没有显示审查面板？
A: 确认以下项：
- 后端日志显示 `pause_after_step=true`
- 前端日志显示 `isPaused=true`
- 检查 `ChatPanel.tsx` 中的条件渲染逻辑: `{isPaused && pendingReviewLayer && <ReviewPanel ... />}`

---

## 许可证

MIT License

Copyright (c) 2024 村庄规划智能体项目

---

## 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph) - 强大的状态图框架
- [LangChain](https://github.com/langchain-ai/langchain) - LLM 应用开发框架
- [Next.js](https://nextjs.org/) - React 框架
- [AsyncSqliteSaver](https://github.com/langchain-ai/langgraph-checkpoint-sqlite) - SQLite 持久化