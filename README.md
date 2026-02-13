# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 和 LangChain 的智能村庄规划系统，提供 **Web 应用** 和 **CLI 工具** 两种使用方式，采用异步数据库架构实现专业的村庄规划辅助。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-green.svg)](https://github.com/langchain-ai/langgraph)

---

## 核心特性

### Web 应用
- **现代化界面**: 基于 Next.js 14 + Tailwind CSS 的响应式 Web 界面
- **维度级流式响应**: 实时 Token → 前端显示 < 100ms 延迟
- **SSE/REST 解耦架构**: REST 提供可靠状态（每 2 秒轮询），SSE 仅负责流式文本推送
- **异步数据库**: 默认启用异步模式，支持并发数据库操作
- **智能文件上传**: 支持多种编码自动检测（UTF-8/GBK/GB2312）和多格式解析（.txt/.md/.docx/.pdf）
- **交互式审查**: 支持人工审查、通过/驳回、回退修复
- **历史会话**: 支持查看和加载历史会话记录
- **检查点导航**: 时间轴可视化，支持检查点对比和回退

### 规划引擎
- **三层架构**: 现状分析 → 规划思路 → 详细规划
- **并行执行**: 12+4+12 个维度并行处理，高效执行
- **智能恢复**: 检查点持久化，支持从任意阶段恢复
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

# 数据库模式: "true" for async (推荐), "false" for sync (回退)
USE_ASYNC_DATABASE=true

# 向量数据库配置
VECTOR_STORE_DIR=data/vectordb
VECTORDB_PERSIST=true

# LangSmith 追踪 (可选)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_PROJECT=village-planning-agent
```

**3. 安装后端依赖**
```bash
pip install -r requirements.txt
```

**4. 安装前端依赖**
```bash
cd frontend
npm install
```

### 启动应用

**启动后端**:
```bash
cd backend
python main.py
```
后端运行在 http://127.0.0.1:8000

**启动前端** (新终端):
```bash
cd frontend
npm run dev
```
前端运行在 http://localhost:3000

**访问应用**: 打开浏览器访问 http://localhost:3000

---

## 数据流架构

### 前端数据流

```
用户操作
  ↓
UnifiedPlanningContext.startPlanning()
  ↓
POST /api/planning/start
  ↓
TaskController (REST轮询每2秒) + useTaskSSE (SSE流式)
  ↓
├─ REST: /api/planning/status (状态、层级完成)
├─ SSE: /api/planning/stream (dimension_delta, dimension_complete)
└─ UI更新 (useStreamingRender批处理渲染)
```

### 后端数据流

```
FastAPI
  ↓
├─ 异步数据库 (SQLite + aiosqlite)
├─ StreamingQueueManager (维度级批处理)
├─ AsyncStoragePipeline (异步存储)
└─ SSE (维度级事件)
  ↓
前端 (REST + SSE)
```

### SSE/REST 解耦架构

**REST 职责**：
- 每 2 秒轮询获取可靠状态
- 数据库作为单一真实源
- 层级完成、暂停、审查状态

**SSE 职责**：
- 维度级流式文本推送（打字机效果）
- `dimension_delta` - 维度增量 token
- `dimension_complete` - 维度完成
- `layer_progress` - 层级进度

---

## 技术优势

### 1. 异步数据库架构
- 默认启用异步模式（`USE_ASYNC_DATABASE=true`）
- 支持 SQLite 异步操作（aiosqlite）
- 同步回退机制，确保兼容性
- 更好的并发性能

### 2. SSE/REST 解耦
- REST 提供可靠状态: 每 2 秒轮询获取状态变化
- SSE 仅用于流式文本: 只发送维度级事件
- 无需复杂去重: 消除 SSE 事件丢失或重复的风险
- 数据库作为单一真实源: 所有状态由数据库统一管理

### 3. 并行执行优化
- 使用并行处理多个维度
- 智能状态筛选：只传递相关维度数据
- 大幅减少 LLM token 消耗（可节省 40-60%）

### 4. 批处理渲染
- 使用 `requestAnimationFrame` 批量更新 DOM
- 防抖内容刷新（100ms）
- 减少 > 80% 的 DOM 更新，提升性能

### 5. 异步存储管道
- 维度完成时立即写入缓存（非阻塞）
- 层级完成时批量写入数据库
- 文件写入使用后台任务，不阻塞流式传输

---

## 项目结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI 后端
│   ├── main.py                # 应用入口
│   ├── api/                   # API 路由
│   ├── database/              # 数据库模块
│   │   ├── manager.py        # 数据库管理器（异步/同步模式）
│   │   ├── operations_async.py # 异步数据库操作
│   │   └── async_wrapper.py # 异步包装器（带回退）
│   ├── services/              # 业务逻辑层
│   ├── schemas.py             # Pydantic 数据模型
│   └── requirements.txt        # Python 依赖
├── frontend/                  # Next.js 14 前端
│   ├── src/
│   │   ├── app/              # Next.js App Router
│   │   ├── components/       # React 组件
│   │   ├── controllers/     # 状态控制器 (TaskController)
│   │   ├── contexts/        # React Context (UnifiedPlanningContext)
│   │   ├── hooks/          # 自定义 Hooks
│   │   └── lib/            # 工具库
│   └── package.json         # Node.js 依赖
├── src/                        # 核心规划引擎
│   ├── orchestration/         # 编排层
│   ├── subgraphs/            # 三层子图
│   ├── planners/             # 规划器层
│   └── utils/                # 核心工具类
├── data/                       # 数据目录
├── docs/                       # 详细文档
└── README.md                  # 项目说明
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
# 数据库模式 (默认: true)
USE_ASYNC_DATABASE=true
```

- `true`: 异步模式（推荐，支持并发）
- `false`: 同步模式（回退选项）

---

## 文档

详细实现文档请查看项目根目录和 `/docs` 目录：

### 核心文档
- **[核心智能体文档](docs/agent.md)** - LangGraph 架构、三层规划系统、统一规划器
- **[前端实现文档](docs/frontend.md)** - Next.js 14 技术栈、类型系统、SSE/REST 解耦
- **[后端实现文档](docs/backend.md)** - FastAPI 架构、API 端点、异步数据库状态管理
- **[前端组件架构](FRONTEND_COMPONENT_ARCHITECTURE.md)** - Next.js 应用架构、组件设计、状态管理、数据流
- **[前端视觉指南](FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范、色彩系统、组件样式

---

## 常见问题

### Q: 规划任务无法启动？
A: 检查以下项：
- 确认 LLM API Key 有效
- 检查后端服务是否启动 (http://127.0.0.1:8000/health)
- 查看后端日志确认数据库初始化成功
- 确认 `USE_ASYNC_DATABASE=true` （推荐）

### Q: 数据库错误？
A:
- 确认 SQLite 数据库文件权限正确
- 检查 `USE_ASYNC_DATABASE` 配置
- 如果异步模式失败，可设置为 `false` 使用同步模式

### Q: 前端无法连接后端？
A:
- 检查 `NEXT_PUBLIC_API_URL` 配置
- 确认后端服务已启动
- 查看浏览器控制台和后端日志

---

## 许可证

MIT License

Copyright (c) 2024 村庄规划智能体项目

---

## 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph) - 强大的状态图框架
- [LangChain](https://github.com/langchain-ai/langchain) - LLM 应用开发框架
- [Next.js](https://nextjs.org/) - React 框架
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化 Python Web 框架
