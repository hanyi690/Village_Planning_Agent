# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 和 LangChain 的智能村庄规划系统，提供 **Web 应用** 和 **CLI 工具** 两种使用方式，采用三层分层架构实现专业的村庄规划辅助。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-green.svg)](https://github.com/langchain-ai/langgraph)

---

## ✨ 核心特性

### 🌐 Web 应用
- **现代化界面**: 基于 Next.js 14 + Tailwind CSS 的响应式 Web 界面
- **维度级流式响应**: 实时 Token → 前端显示 < 100ms 延迟
- **智能数据流**: StreamingQueueManager 批处理 → SSE 维度事件 → useStreamingRender Hook → UI
- **异步存储**: 维度完成时立即写入 Redis，层级完成时批量写入 SQLite
- **数据库单一源**: 所有状态由数据库统一管理，消除事件丢失或重复
- **智能文件上传**: 支持多种编码自动检测（UTF-8/GBK/GB2312）和多格式解析（.txt/.md/.docx/.pdf）
- **交互式审查**: 支持人工审查、通过/驳回、回退修复
- **历史会话**: 支持查看和加载历史会话记录
- **检查点导航**: 时间轴可视化，支持检查点对比和回退

### 🏗️ 规划引擎
- **三层架构**: 现状分析 → 规划思路 → 详细规划
- **并行执行**: 12+4+12 个维度并行处理，高效执行
- **智能恢复**: 检查点持久化，支持从任意阶段恢复
- **状态筛选优化**: 智能过滤相关维度，节省 40-60% LLM token
- **统一规划器**: 基于统一基类的通用规划器架构
- **批处理优化**: 维度级 token 批处理（50 tokens 或 100ms）

### 🖥️ CLI 工具
- **命令行接口**: 支持完整规划和单层执行
- **批处理**: 适合批量处理多个规划任务
- **灵活集成**: 易于集成到其他系统中

---

## 🚀 快速开始

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
# OPENAI_API_KEY=your_openai_api_key_here
# LLM 模型
LLM_MODEL=glm-4-flash
MAX_TOKENS=65536

# LangSmith 追踪 (可选)
LANGCHAIN_TRACING_V2=true
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

## 📖 使用指南

### Web 应用

**1. 新建规划**
- 点击"新建规划"按钮
- 输入村庄名称和基础数据
- 上传村庄现状数据文件（支持 .txt, .md, .docx, .pdf）
- 选择需要分析的维度（可选）
- 点击"开始规划"

**2. 查看进度**
- 实时查看规划进度（REST 轮询每 2 秒更新状态）
- 维度级流式文本显示（SSE 推送，< 100ms 延迟）
- 查看各层完成状态
- 浏览中间结果

**3. 审查和修改**
- 在关键节点进行人工审查
- 批准继续执行
- 驳回修改需求
- 回退到任意检查点
- 查看各维度详细分析

**4. 查看报告**
- 查看最终规划报告
- 浏览各维度详细分析
- 支持自定义维度组合显示
- 下载报告文件

### 文件上传支持

系统支持以下文件格式：

| 格式 | 说明 | 解析方式 |
|------|------|-------------------|
| **.txt** | 纯文本文件 | 自动检测编码（UTF-8/GBK/GB2312） |
| **.md** | Markdown 文件 | 自动检测编码（UTF-8/GBK/GB2312） |
| **.docx** | Word 文档 | 提取所有段落文本，保留换行 |
| **.pdf** | PDF 文档 | 提取所有页面文本，保留分页 |

**文件大小限制**：最大 10MB

### CLI 工具

**完整规划流程**:
```bash
python -m src.cli.main \
    --mode full \
    --project "示例村庄" \
    --data data/village_data.txt \
    --output output.txt
```

**单层执行**:
```bash
# 仅现状分析
python -m src.cli.main --mode analysis --project "示例村庄" --data data/village_data.txt

# 仅规划思路
python -m src.cli.main --mode concept --project "示例村庄" --data data/village_data.txt

# 仅详细规划
python -m src.cli.main --mode detailed --project "示例村庄" --data data/village_data.txt
```

---

## 🏗️ 系统架构

### 核心架构特点
- ✅ **简化流程**：每层直接并行分析维度，无汇总节点
- ✅ **细粒度存储**：检查点只保存维度报告，便于灵活组合
- ✅ **统一命名**：`analysis_dimension_reports`, `concept_dimension_reports`, `detailed_dimension_reports`（英文键名）
- ✅ **智能状态筛选**：根据依赖关系自动筛选相关维度
- ✅ **SSE/REST 解耦**：REST 提供可靠状态，SSE 仅负责流式文本效果
- ✅ **线程安全**：全局状态使用 Lock 保护
- ✅ **会话清理**：自动清理 24 小时后的过期会话
- ✅ **API 重试**：指数退避重试机制（最大 3 次）

### 规划流程图

```
村庄数据输入
    ↓
┌───────────────────────────────────────────┐
│ Layer 1: 现状分析 (12维度并行)                   │
│ analyze_dimension (并行) → END                   │
│ - 区位分析、社会经济、村民意愿、上位规划              │
│ - 自然环境、土地利用、道路交通、公共服务          │
│ - 基础设施、生态绿地、建筑、历史文化              │
│ 输出: analysis_dimension_reports (字典)           │
└───────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────┐
│ Layer 2: 规划思路 (4维度并行)                    │
│ analyze_concept_dimension (并行) → END           │
│ - 资源禀赋分析                                   │
│ - 规划定位分析                                   │
│ - 发展目标分析                                   │
│ - 规划策略分析                                   │
│ 输出: concept_dimension_reports (字典)           │
└───────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ Layer 3: 详细规划 (12维度，分波次执行)            │
│ detailed_plan_dimension (并行) → Wave 1→ END       │
│ - Wave 1: 产业、空间、土地等11个维度 (并行)        │
│ Wave 2: 设施项目库 (依赖 Wave 1 结果)              │
│ Wave 3: 其余维度详细规划                          │
│ 输出: detailed_dimension_reports (字典)          │
└───────────────────────────────────────────────────┘
    ↓
最终规划方案 (前端可灵活组合显示各维度内容)
```

### 数据流与状态管理

**REST/SSE 职责分离**：
```
┌─────────────────────────────────────────────────────┐
│                      前端 (Next.js)                │
│  ┌──────────────────────────────────────────────┐   │
│  │  TaskController (状态管理层)             │   │
│  │  ┌────────────────────────────────────────┐   │   │
│  │  │ REST 轮询 (每 2 秒)           │   │   │
│  │  │ ├─ layer_1_completed                   │   │   │
│  │  │ ├─ layer_2_completed                   │   │   │
│  │  │ ├─ layer_3_completed                   │   │   │
│  │  │ ├─ pause_after_step                    │   │   │
│  │  │ ├─ waiting_for_review                 │   │   │
│  │  │ ├─ execution_complete                  │   │   │
│  │  │ └──────────────────────────────────────┘ │   │
│  │  ┌────────────────────────────────────────┐   │   │
│  │  │ 单一真实源: SQLite 数据库      │   │   │
│  │  │ - tasks 表存储所有状态             │   │   │
│  │  │ - 状态更新立即写入数据库          │   │   │
│  │  └──────────────────────────────────────┘ │   │
│  └────────────────────────────────────────────┘   │   │
│  ┌──────────────────────────────────────────────┐   │
│  │ SSE 流式推送 (仅文本效果)           │   │
│  │  ├─ text_delta (打字机效果)             │   │   │
│  │  └─ error (错误信息)                  │   │   │
│  └──────────────────────────────────────────────┘ │   │
│  ┌──────────────────────────────────────────────┐   │
│  │ TaskController 回调 (稳定引用)         │   │
│  │  ├─ onLayerCompleted                   │   │
│  │  ├─ onPause                          │   │
│  │  ├─ onComplete                        │   │
│  │  ├─ onError                           │   │
│  │  └─ onTextDelta                      │   │
│  └──────────────────────────────────────────────┘ │   │
│                                                 │
│  触发器: useEffect (依赖 taskId + callbacks)    │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                      后端 (FastAPI)                │
│  ┌──────────────────────────────────────────────┐   │
│  │              核心智能体 (LangGraph)       │   │
│  │  ┌────────────────────────────────────────┐   │   │
│  │  │ 三层规划主图                     │   │   │
│  │  │ - 并行维度分析                   │   │   │
│  │  │ - 智能状态筛选                   │   │   │
│  │  │ - 检查点管理                      │   │   │
│  │  └──────────────────────────────────────┘ │   │   │
│  ┌────────────────────────────────────────────┐   │   │
│  │      StreamingQueueManager (NEW)         │   │   │
│  │  - 维度级 token 批处理               │   │   │
│  │  - 批处理: 50 tokens 或 100ms       │   │   │
│  │  - 线程安全 (Lock 保护)              │   │   │
│  │  └──────────────────────────────────────┘ │   │   │
│  ┌────────────────────────────────────────────┐   │   │
│  │      AsyncStoragePipeline (NEW)         │   │   │
│  │  - 维度完成 → Redis (立即)         │   │   │
│  │  - 层级完成 → SQLite (批量)        │   │   │
│  │  - 文件写入 (后台任务)               │   │   │
│  │  └──────────────────────────────────────┘ │   │   │
│  ┌────────────────────────────────────────────┐   │   │
│  │        SSE 事件发射器 (扩展)         │   │   │
│  │  ├─ dimension_delta (维度增量)       │   │   │
│  │  ├─ dimension_complete (维度完成)       │   │   │
│  │  ├─ layer_progress (层级进度)          │   │   │
│  │  └─ 原有事件类型                     │   │   │
│  └──────────────────────────────────────────────┘ │   │
│                                                 │
┌─────────────────────────────────────────────────────┘
                          │
                          ▼
```

**状态更新流程**：
1. 层级完成时
   LangGraph → 数据库更新 (layer_X_completed = True)
                    ↓
   REST 轮询检测到状态变化
                    ↓
   前端触发 onLayerCompleted 回调

2. 流式文本推送
   LangGraph 生成 token
                    ↓
   StreamingQueueManager 批处理 (50 tokens 或 100ms)
                    ↓
   SSE 发送 dimension_delta 事件
                    ↓
   前端 useStreamingRender Hook 批处理渲染 (RAF + 防抖)
                    ↓
   UI 更新 (目标 < 100ms 延迟)

3. 异步存储 (不阻塞流式传输)
   维度完成时
   StreamingQueueManager.complete_dimension()
                    ↓
   AsyncStoragePipeline.store_dimension() → Redis (非阻塞)

   层级完成时
   所有维度完成
                    ↓
   AsyncStoragePipeline.commit_layer()
                    ↓
   SQLite 批量写入 + 文件后台任务
```

### 检查点数据结构

所有层的检查点使用统一的字段命名规范：

**重要说明**：维度报告使用**英文键名**存储，显示时映射为**中文名称**。

```json
{
  "checkpoint_id": "checkpoint_001_layer1_completed",
  "state": {
    "analysis_dimension_reports": {
      "location": "区位分析内容...",
      "socio_economic": "社会经济分析内容...",
      "villager_wishes": "村民意愿分析内容...",
      "superior_planning": "上位规划分析内容...",
      "natural_environment": "自然环境分析内容...",
      "land_use": "土地利用分析内容...",
      "traffic": "道路交通分析内容...",
      "public_services": "公共服务分析内容...",
      "infrastructure": "基础设施分析内容...",
      "ecological_green": "生态绿地分析内容...",
      "architecture": "建筑分析内容...",
      "historical_cultural": "历史文化分析内容..."
    },
    "concept_dimension_reports": {
      "resource_endowment": "资源禀赋分析内容...",
      "planning_positioning": "规划定位分析内容...",
      "development_goals": "发展目标分析内容...",
      "planning_strategies": "规划策略分析内容..."
    },
    "detailed_dimension_reports": {
      "industry": "产业规划内容...",
      "spatial_structure": "空间结构规划内容...",
      "land_use_planning": "土地利用规划内容...",
      "settlement_planning": "聚落体系规划内容...",
      "traffic": "综合交通规划内容...",
      "public_service": "公共服务设施规划内容...",
      "infrastructure": "基础设施规划内容...",
      "ecological": "生态保护与修复内容...",
      "disaster_prevention": "防灾减灾规划内容...",
      "heritage": "历史文化遗产保护内容...",
      "landscape": "村庄风貌引导内容...",
      "project_bank": "建设项目库内容..."
    }
  }
}
```

---

## 🎯 技术优势

### 1. SSE/REST 解耦架构 ⭐
- **REST 提供可靠状态**: 每 2 秒轮询获取状态，保证数据一致性
- **SSE 仅用于流式文本**: 只发送 `dimension_delta` 和 `error` 事件
- **无需复杂重试**: 消除 SSE 事件丢失或重复的风险
- **数据库作为单一真实源**: 所有状态由数据库统一管理

### 2. 并行执行优化
- 使用 `analisys` 列表并行处理 12 个维度
- 智能状态筛选：只传递相关维度数据
- 大幅减少 LLM token 消耗（可节省 40-60%）

### 3. 批处理渲染
- 使用 `requestAnimationFrame` 批量更新 DOM
- 防抖内容刷新（100ms）
- 减少 > 80% 的 DOM 更新，提升性能

### 4. 异步存储管道
- 维度完成时立即写入 Redis（非阻塞）
- 层级完成时批量写入 SQLite
- 文件写入使用后台任务，不阻塞流式传输

### 5. 线程安全
- 全局状态使用 `Lock` 保护
- 线程安全的会话访问上下文管理器
- 防止竞态条件和数据损坏

### 6. 会话自动清理
- 后台任务每小时检查一次
- 自动清理 24 小时后的过期会话
- 释放内存和资源

### 7. API 客户端重试
- 指数退避重试（1s, 2s, 4s）
- 最大 3 次重试
- 抖动防止 thundering herd
- 仅对 5xx 和网络错误重试

### 8. 维度级流式响应
- Token 级实时推送：LLM → 前端 < 100ms
- 按维度独立流式传输
- 批处理优化（50 tokens 或 100ms 窗口）
- 支持维度级完成事件

---

## 📂 项目结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI 后端
│   ├── main.py                # 应用入口
│   ├── api/                   # API 路由
│   │   ├── planning.py        # 规划执行 API
│   │   ├── sessions.py         # 会话管理 API
│   │   ├── data.py            # 数据访问 API
│   │   ├── validate_config.py # 配置验证
│   │   ├── tool_manager.py    # 工具管理器
│   │   └── files.py          # 文件上传 API
│   ├── database/              # 数据库模块
│   │   ├── __init__.py       # 数据库初始化
│   │   ├── operations.py     # CRUD 操作
│   │   └── operations_enhanced.py  # 增强操作
│   ├── schemas.py             # Pydantic 数据模型
│   ├── services/              # 业务逻辑层
│   │   ├── rate_limiter.py   # 速率限制
│   │   ├── redis_client.py  # Redis 客户端
│   │   ├── sse_event_stream.py # SSE 事件流
│   │   └── storage_pipeline.py # 异步存储管道 (NEW)
│   ├── requirements.txt        # Python 依赖
│   └── utils/                # 后端工具类
│       ├── logging.py         # 日志配置
│       └── progress_helper.py # 进度计算
├── frontend/                  # Next.js 14 前端
│   ├── public/              # 静态资源
│   ├── src/
│   │   ├── app/           # Next.js App Router
│   │   ├── components/      # React 组件
│   │   │   ├── chat/         # 聊天界面组件
│   │   │   │   ├── ChatPanel.tsx           # 主聊天面板
│   │   │   │   ├── MessageList.tsx        # 消息列表
│   │   │   │   ├── MessageContent.tsx     # 消息内容
│   │   │   │   ├── ActionButtonGroup.tsx # 操作按钮组
│   │   │   │   ├── DimensionSection.tsx  # 维度区块
│   │   │   │   ├── LayerReportCard.tsx      # 层级报告卡片
│   │   │   │   ├── LayerReportMessage.tsx  # 层级报告消息
│   │   │   │   ├── ThinkingIndicator.tsx # 思考指示器
│   │   │   │   ├── StreamingText.tsx        # 流式文本组件
│   │   │   │   ├── CodeBlock.tsx           # 代码块
│   │   │   │   └── index.ts           # 组件导出
│   │   │   ├── layout/        # 布局组件
│   │   │   │   ├── MainLayout.tsx     # 主布局
│   │   │   │   ├── Sidebar.tsx         # 侧边栏
│   │   │   │   └── index.ts         # 导出
│   │   ├── controllers/    # 状态控制器
│   │   │   │   └── TaskController.tsx # 任务状态控制器
│   │   ├── contexts/        # React Context
│   │   │   ├── UnifiedPlanningContext.tsx # 统一规划上下文
│   │   │   └── UnifiedPlanningState.tsx  # 状态定义
│   │   ├── hooks/          # 自定义 Hooks
│   │   │   ├── useStreamingRender.ts  # 批处理渲染 Hook (NEW)
│   │   │   ├── useStreamingText.ts  # 流式文本 Hook
│   │   │   ├── useTaskSSE.ts       # SSE 连接 Hook
│   │   │   └── ...                    # 其他 Hooks
│   │   ├── lib/            # 工具库
│   │   │   ├── api.ts            # API 客户端（含重试机制）
│   │   │   ├── constants.ts      # 常量定义
│   │   │   ├── logger.ts        # 日志工具
│   │   │   ├── utils.ts         # 工具函数
│   │   │   └── types/          # TypeScript 类型
│   │   ├── styles/         # 样式文件
│   │   ├── .env.local       # 前端环境变量
│   │   ├── package.json    # Node.js 依赖
│   │   ├── tsconfig.json   # TypeScript 配置
│   │   └── next.config.js  # Next.js 配置
├── src/                        # 核心规划引擎
│   ├── orchestration/         # 编排层
│   │   ├── main_graph.py      # LangGraph 主图
│   │   └── knowledge_preloader.py # 知识预加载
│   ├── subgraphs/            # 三层子图
│   │   ├── analysis_subgraph.py    # 现状分析
│   │   ├── concept_subgraph.py     # 规划思路
│   │   └── detailed_plan_subgraph.py # 详细规划
│   ├── nodes/                # 节点封装
│   │   ├── layer_nodes.py     # 层级节点
│   │   ├── tool_nodes.py      # 工具节点
│   │   └── ...                # 其他节点
│   ├── planners/             # 规划器层
│   │   ├── generic_planner.py         # 通用规划器
│   │   └── unified_base_planner.py # 统一基类（支持流式队列）
│   ├── tools/                # 工具层
│   │   ├── checkpoint_tool.py    # 检查点工具
│   │   ├── web_review_tool.py    # Web 审查工具
│   │   ├── knowledge_tool.py     # 知识检索工具
│   │   ├── revision_tool.py      # 修订工具
│   │   └── ...                # 其他工具
│   ├── utils/                # 核心工具类
│   │   ├── streaming_queue.py     # 流式队列管理器 (NEW)
│   │   ├── config.py            # 配置管理
│   │   ├── checkpoint_manager.py # 检查点管理器
│   │   ├── output_manager.py     # 输出管理器
│   │   ├── output_manager_registry.py # 输出管理器注册表
│   │   ├── paths.py            # 路径工具
│   │   ├── text_formatter.py    # 文本格式化
│   │   ├── logger.py           # 日志工具
│   │   └── ...                # 其他工具
│   ├── config/                # 配置文件
│   │   ├── default_config.yaml # 默认配置
│   │   └── prompts/            # 提示词模板
│   └── checkpoint/           # 检查点存储
│       └── ...                # 检查点数据
├── data/                       # 数据目录
│   └── results/                # 结果输出
├── docs/                       # 详细文档
│   ├── agent.md               # 核心智能体文档
│   ├── frontend.md            # 前端实现文档
│   ├── backend.md             # 后端实现文档
│   └── ...                    # 其他文档
├── tests/                      # 测试代码
├── .env                        # 环境变量配置
├── requirements.txt            # Python 核心依赖
├── start-services.sh          # 服务启动脚本
├── stop-services.sh           # 服务停止脚本
└── README.md                  # 项目说明
```

---

## 🔧 配置说明

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

**自动检测**: `glm-*` → ZhipuAI, `gpt-*` → OpenAI, `deepseek-*` → DeepSeek

### 前端配置

创建 `frontend/.env.local`:
```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

### LangSmith 追踪 (可选)

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_key
LANGCHAIN_PROJECT=village-planning-agent
```

---

## 📚 文档

详细实现文档请查看项目根目录和 `/docs` 目录：

### 核心文档
- **[核心智能体文档](docs/agent.md)** - LangGraph 架构、三层规划系统、统一规划器
- **[前端实现文档](docs/frontend.md)** - Next.js 14 技术栈、类型系统、SSE/REST 解耦
- **[后端实现文档](docs/backend.md)** - FastAPI 架构、API 端点、数据库状态管理、流式队列、异步存储
- **[前端组件架构](FRONTEND_COMPONENT_ARCHITECTURE.md)** - Next.js 应用架构、组件设计、状态管理、数据流
- **[前端视觉指南](FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范、色彩系统、组件样式

---

## ❓ 常见问题

### Q: 上传的文件显示乱码怎么办？
A: 系统已支持自动编码检测（UTF-8/GBK/GB2312），如果仍有问题：
- 确认文件内容确实是文本格式（非图片或扫描件）
- 对于 .txt 和 .md 文件，尝试用记事本另存为 UTF-8 编码
- 查看浏览器控制台和后端日志中的解析信息

### Q: LangSmith 追踪未生效？
A:
- 检查 `LANGCHAIN_TRACING_V2=true` 和 API Key 配置
- 查看网络连接和 API 额度
- 访问 https://smith.langchain.com 查看追踪数据

### Q: LLM 调用失败？
A:
- 检查 API Key 是否有效
- 检查网络连接和 API 额度
- 查看后端日志 (`logs/backend.log`)

### Q: 前端无法连接后端？
A:
- 检查 `NEXT_PUBLIC_API_URL` 配置
- 确认后端服务已启动 (`http://127.0.0.1:8000/health`)
- 查看后端日志 (`tail -f logs/backend.log`)

---

## 🤝 贡献

**村庄规划 AI 助手** - 让村庄规划更智能、更高效

---

## 📄 许可证

MIT License

Copyright (c) 2024 村庄规划智能体项目

---

## 🙏 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph) - 强大的状态图框架
- [LangChain](https://github.com/langchain-ai/langchain) - LLM 应用开发框架
- [Next.js](https://nextjs.org/) - React 框架
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化 Python Web 框架
