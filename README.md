# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 和 LangChain 的智能村庄规划系统，提供 **Web 应用** 和 **CLI 工具** 两种使用方式，采用三层分层架构实现专业的村庄规划辅助。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-green.svg)](https://github.com/langchain-ai/langgraph)

---

## ✨ 核心特性

### 🌐 Web 应用

- **现代化界面**: 基于 Next.js 14 + Bootstrap 5.3 的响应式 Web 界面
- **实时进度**: SSE 流式传输，实时查看规划进度
- **智能文件上传**: 支持多种编码自动检测（UTF-8/GBK/GB2312）和多格式解析（.txt/.md/.docx/.pdf）
- **文件管理**: 支持多文件上传、会话历史、检查点管理
- **交互式审查**: 支持人工审查、通过/驳回、回退修复
- **历史会话**: 支持查看和加载历史会话记录
- **检查点导航**: 时间轴可视化，支持检查点对比和回退

### 🏗️ 规划引擎

- **分层架构**: 三层子图（现状分析 → 规划思路 → 详细规划）
- **并行分析**: 12+4+12 个维度并行处理，高效执行
- **智能恢复**: 检查点持久化，支持从任意阶段恢复
- **专业工具**: GIS 分析、网络分析、人口预测等专业适配器

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
# 安装核心依赖
pip install -r requirements.txt

# 如果使用 backend/requirements.txt，确保安装了文件解析库
cd backend
pip install -r requirements.txt
cd ..
```

**4. 安装前端依赖**

```bash
cd frontend
npm install
cd ..
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
  - **文本文件** (.txt, .md)：自动检测编码（UTF-8/GBK/GB2312）
  - **Word文档** (.docx)：提取所有段落文本
  - **PDF文档** (.pdf)：提取所有页面文本
  - 显示解析后的编码类型和内容长度供确认
- 选择需要分析的维度（可选）
- 点击"开始规划"

**2. 查看进度**

- 实时查看规划进度
- 查看各层完成状态
- 浏览中间结果

**3. 审查和修改**

- 在关键节点进行人工审查
- 批准继续或驳回修改
- 回退到任意检查点

**4. 查看报告**

- 查看最终规划报告
- 浏览各维度详细分析
- 下载报告文件

### 文件上传支持

系统支持以下文件格式：

| 格式 | 说明 | 解析方式 |
|------|------|---------|
| **.txt** | 纯文本文件 | 自动检测编码（UTF-8/GBK/GB2312） |
| **.md** | Markdown 文件 | 自动检测编码（UTF-8/GBK/GB2312） |
| **.docx** | Word 文档 | 提取所有段落文本，保留换行 |
| **.pdf** | PDF 文档 | 提取所有页面文本，保留分页 |

**文件大小限制**：最大 10MB

**推荐做法**：
- 文本文件推荐使用 UTF-8 编码
- Word 和 PDF 文件会自动提取文本内容
- 确保文件内容不是扫描图片（需要包含可提取的文本层）

---

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

**交互模式（逐步执行）**:

```bash
python -m src.cli.main \
    --mode step \
    --project "示例村庄" \
    --data data/village_data.txt \
    --step-level layer
```

**从检查点恢复**:

```bash
python -m src.cli.main \
    --mode resume \
    --project "示例村庄" \
    --resume-from checkpoint_001_layer2_completed
```

---

## 📋 规划流程

### 三层规划架构

**架构特点**：
- ✅ **简化流程**：每层直接并行分析维度，无需汇总节点，提高执行效率
- ✅ **细粒度存储**：检查点只保存维度报告，便于灵活组合和快速加载
- ✅ **统一命名**：`analysis_dimension_reports`, `concept_dimension_reports`, `detailed_dimension_reports`（英文键名）
- ✅ **智能状态筛选**：根据依赖关系自动筛选相关维度，优化 LLM 上下文
- ✅ **中心化状态管理**：前端使用 ViewMode 计算属性统一管理视图状态
- ✅ **Smart Container 模式**：UnifiedContentSwitcher 自动响应状态变化切换视图

```
村庄数据输入
    ↓
┌───────────────────────────────────────────────────┐
│  Layer 1: 现状分析 (12维度并行)                   │
│  analyze_dimension (并行) → END                   │
│  - 区位、社会经济、村民意愿、上位规划              │
│  - 自然环境、土地利用、道路交通、公共服务          │
│  - 基础设施、生态绿地、建筑、历史文化              │
│  输出: analysis_dimension_reports (字典)           │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│  Layer 2: 规划思路 (4维度并行)                    │
│  analyze_concept_dimension (并行) → END           │
│  - 资源禀赋分析                                   │
│  - 规划定位分析                                   │
│  - 发展目标分析                                   │
│  - 规划策略分析                                   │
│  输出: concept_dimension_reports (字典)           │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│  Layer 3: 详细规划 (12维度，分波次执行)            │
│  Wave 1: 产业、空间、土地等11个维度 (并行)        │
│  Wave 2: 建设项目库 (依赖Wave 1结果)              │
│  输出: detailed_dimension_reports (字典)          │
└───────────────────────────────────────────────────┘
    ↓
最终规划方案 (前端可灵活组合显示各维度内容)
```

### 技术优势

**1. 并行执行优化**

**问题**: LangGraph 的 Send 机制为每个并行任务创建隔离状态，字典无法自动合并。

**解决方案**:
- 使用 `analyses` 列表（通过 `operator.add` 正确累积）
- 在包装函数中将列表转换为使用英文键名的字典
- 确保所有维度报告正确返回

**实现代码**（analysis_subgraph.py:345-360）:
```python
# 从 analyses 列表中提取维度报告并转换为字典（使用英文键名）
analyses = result.get("analyses", [])
dimension_reports = {}
for analysis in analyses:
    dimension_key = analysis.get("dimension_key")  # 英文键名
    analysis_result = analysis.get("analysis_result")
    if dimension_key and analysis_result:
        dimension_reports[dimension_key] = analysis_result
```

**2. 状态筛选优化**
- 每个维度只接收其依赖的相关维度数据
- 大幅减少 LLM token 消耗（可节省 40-60%）
- 提高响应速度和分析质量

**3. 并行执行效率**
- 同层维度完全并行，无等待
- Layer 1: 12个维度并行
- Layer 2: 4个维度并行
- Layer 3: Wave 1 并行 11个 + Wave 2 单独执行

**4. 检查点机制**
- 每层完成后自动保存检查点
- 支持从任意层恢复执行
- 精确记录维度级别的结果

### 检查点数据结构

所有层的检查点使用统一的字段命名规范：

**重要说明**: 维度报告使用**英文键名**存储，显示时映射为**中文名称**。

```json
{
  "checkpoint_id": "checkpoint_001_layer1_completed",
  "state": {
    // Layer 1 - 使用英文键名
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

    // Layer 2 - 使用英文键名
    "concept_dimension_reports": {
      "resource_endowment": "资源禀赋分析内容...",
      "planning_positioning": "规划定位分析内容...",
      "development_goals": "发展目标分析内容...",
      "planning_strategies": "规划策略分析内容..."
    },

    // Layer 3 - 使用英文键名
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

**优势**：
- 🎯 **细粒度控制**：前端可按需显示特定维度
- 🔄 **灵活组合**：支持自定义维度组合展示
- 💾 **高效存储**：避免冗余的综合报告
- 🚀 **快速加载**：只加载需要的维度内容
- 🌐 **国际化友好**：英文键名便于多语言支持

### 专业工具适配器

| 适配器     | 功能                                       | 状态  |
| ---------- | ------------------------------------------ | ----- |
| GIS 适配器 | 土地利用、土壤、水文空间分析               | 可选  |
| 网络适配器 | 路网连通度、可达性、中心性分析              | 可选  |
| 人口适配器 | 人口预测、结构分析、劳动力分析              | 可选  |

**注意**：专业适配器默认未启用，需要配置相关数据后才能使用。系统可在无专业数据的情况下正常运行，LLM 将基于文本数据进行分析。

---

## 📂 项目结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI 后端
│   ├── main.py                # 应用入口
│   ├── api/                   # API 路由
│   │   ├── planning.py        # 规划执行 API
│   │   ├── data.py            # 数据访问 API
│   │   ├── sessions.py        # 会话管理 API
│   │   ├── files.py           # 文件上传 API
│   │   ├── validate_config.py # 配置验证 API
│   │   └── tool_manager.py    # 工具管理器 API
│   ├── services/              # 业务逻辑层
│   │   └── planning_service.py
│   ├── utils/                 # 后端工具类
│   │   ├── error_handler.py
│   │   └── session_helper.py
│   ├── schemas.py             # Pydantic 数据模型
│   └── requirements.txt       # Python 依赖
│
├── frontend/                   # Next.js 14 前端
│   ├── src/
│   │   ├── app/               # Next.js App Router
│   │   │   ├── layout.tsx     # 根布局
│   │   │   ├── page.tsx       # 首页
│   │   │   ├── globals.css    # 全局样式
│   │   │   └── village/       # 村庄规划页面
│   │   │       └── [taskId]/  # 动态路由
│   │   │           ├── loading.tsx # 加载状态
│   │   │           └── page.tsx   # 规划页面
│   │   ├── components/        # React 组件
│   │   │   ├── chat/          # 聊天界面组件 (13个)
│   │   │   │   ├── ChatPanel.tsx
│   │   │   │   ├── MessageList.tsx
│   │   │   │   ├── MessageBubble.tsx
│   │   │   │   ├── LayerReportMessage.tsx
│   │   │   │   ├── LayerReportCard.tsx
│   │   │   │   ├── DimensionSection.tsx
│   │   │   │   ├── ReviewInteractionMessage.tsx
│   │   │   │   ├── CodeBlock.tsx
│   │   │   │   └── ...
│   │   │   ├── review/        # 审查功能组件
│   │   │   ├── report/        # 报告显示组件 (仅文档)
│   │   │   ├── layout/        # 布局组件 (Header, HistoryPanel, UnifiedContentSwitcher ⭐)
│   │   │   ├── ui/            # 通用UI组件 (Card, SegmentedControl)
│   │   │   ├── FileUpload.tsx # 文件上传组件
│   │   │   ├── DimensionSelector.tsx # 维度选择器
│   │   │   ├── VillageInputForm.tsx # 输入表单
│   │   │   └── MarkdownRenderer.tsx # Markdown渲染
│   │   ├── contexts/          # React Context 状态管理
│   │   │   └── UnifiedPlanningContext.tsx # 统一规划上下文
│   │   ├── hooks/             # 自定义 Hooks
│   │   │   ├── useStreaming.ts
│   │   │   ├── useTaskSSE.ts
│   │   │   └── useLazyLoad.tsx
│   │   ├── lib/               # 工具库
│   │   │   ├── api.ts         # API客户端
│   │   │   └── utils.ts       # 工具函数
│   │   ├── config/            # 配置文件
│   │   └── types/             # TypeScript 类型定义
│   ├── .env.local             # 前端环境变量
│   ├── package.json           # Node.js 依赖
│   └── tsconfig.json          # TypeScript 配置
│
├── src/                        # 核心规划引擎
│   ├── orchestration/          # 编排层
│   │   └── main_graph.py      # LangGraph 主图
│   ├── subgraphs/              # 三层子图
│   │   ├── analysis_subgraph.py      # 现状分析子图
│   │   ├── concept_subgraph.py       # 规划思路子图
│   │   ├── detailed_plan_subgraph.py # 详细规划子图
│   │   └── *_prompts.py       # 各层提示词
│   ├── nodes/                  # 节点封装
│   │   ├── subgraph_nodes.py  # 子图调用节点
│   │   └── tool_nodes.py      # 工具调用节点
│   ├── planners/               # 规划器
│   │   ├── analysis_planners.py     # 现状分析规划器
│   │   ├── concept_planners.py      # 规划思路规划器
│   │   ├── detailed_planners.py     # 详细规划规划器
│   │   └── unified_base_planner.py  # 统一基类
│   ├── tools/                  # 工具层
│   │   ├── checkpoint_tool.py       # 检查点管理
│   │   ├── interactive_tool.py      # 交互工具
│   │   ├── web_review_tool.py       # Web审查工具
│   │   └── adapters/               # 专业适配器
│   ├── core/                   # 核心组件
│   │   ├── config.py          # 全局配置
│   │   ├── llm_factory.py     # LLM 工厂
│   │   ├── dimension_mapping.py    # 维度映射
│   │   └── streaming.py       # 流式输出
│   ├── utils/                  # 工具类
│   │   ├── output_manager.py  # 输出管理
│   │   ├── state_filter.py    # 状态筛选
│   │   ├── text_formatter.py  # 文本格式化
│   │   └── paths.py           # 路径管理
│   └── cli/                    # CLI 工具
│       └── main.py            # 命令行入口
│
├── data/                       # 数据目录
│   └── vectordb/              # 向量数据库存储
│
├── results/                    # 结果输出目录
│   └── [村庄名]/              # 各村庄规划结果
│
├── docs/                       # 详细文档
│   ├── agent.md               # 核心智能体文档
│   ├── backend.md             # 后端实现文档
│   ├── frontend.md            # 前端实现文档
│   ├── ARCHITECTURE_REFACTORING.md # 架构重构说明
│   └── QUICK_REFERENCE.md     # 快速参考
│
├── .env                        # 环境变量配置
├── requirements.txt           # Python 核心依赖
├── CHANGELOG.md              # 变更日志
├── SETUP_GUIDE.md            # 安装指南
├── QUICK_START.md            # 快速开始
└── README.md                 # 项目说明
```

---

## 🔧 配置说明

### LLM 配置

**ZhipuAI (推荐)**:

```env
ZHIPUAI_API_KEY=your_key
LLM_MODEL=glm-4-flash
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

---

## 📚 文档

详细实现文档请查看项目根目录和 `/docs` 目录：

### 核心文档
- **[前端架构文档](FRONTEND_COMPONENT_ARCHITECTURE.md)** - Next.js 应用架构、组件设计、状态管理
- **[前端视觉指南](FRONTEND_VISUAL_GUIDE.md)** - UI/UX 设计规范、色彩系统、组件样式
- **[前端实现文档](docs/前端.md)** - 前端技术栈、类型系统、SSE集成、API客户端 ⭐ NEW
- **[后端实现文档](docs/后端.md)** - FastAPI 架构、API端点、服务层设计 ⭐ NEW
- **[核心智能体文档](docs/agent.md)** - LangGraph 架构、三层规划系统、节点设计、SSE流管理

### 快速参考
- **[快速开始](QUICK_START.md)** - 5分钟快速上手指南
- **[安装指南](SETUP_GUIDE.md)** - 详细安装步骤说明
- **[变更日志](CHANGELOG.md)** - 项目变更历史和版本规划
- **[架构重构说明](docs/ARCHITECTURE_REFACTORING.md)** - 架构演进历史
- **[快速参考](docs/QUICK_REFERENCE.md)** - 常用命令、配置、API快速查询

### 修复文档
- **[SSE循环修复](SSE_LOOP_FIX_COMPLETE.md)** - SSE连接循环问题完整修复方案
- **[SSE循环修复快速参考](SSE_LOOP_FIX_QUICK_REFERENCE.md)** - SSE修复快速参考指南

**最新更新 (2025-02-09)** ⭐⭐⭐:
- ✅ **Pause 事件去重机制**：修复审查面板重复显示问题
  - 后端：添加 `sent_pause_events` Set 追踪，每个 Layer 只发送一次 pause 事件
  - 前端：添加 `processedPauseEventsRef` 追踪，二次去重防护
  - 批准后正确清理追踪状态，允许下一 layer 的 pause 事件被处理
  - 任务完成时清除所有追踪，确保新任务从干净状态开始
- ✅ **批准失败修复**：修复 "No pending review or pause" 错误
  - 批准时详细状态日志，便于调试
  - 清除 pause_after_step 标志和 pause 事件追踪
  - 确保 approve 后状态一致，顺利进入下一 layer
- ✅ **函数调用关系文档**：详细的前后端函数调用链和数据流向图
  - 完整的 pause 事件处理流程（从检测到显示审查面板）
  - 批准流程（从前端点击到后端执行再到新 SSE 连接）
  - 文件间依赖关系（前端组件、后端模块、Agent 引擎）

**修复效果**:
- 修复前：Layer 1 → 2-3个审查面板 → 批准失败 "No pending review or pause"
- 修复后：Layer 1 → 1个审查面板 → 批准立即成功 → 顺畅进入 Layer 2

**详细文档**：
- [前端修复说明](docs/前端.md#最新修复-2025-02-09--⭐⭐⭐-new)
- [后端修复说明](docs/后端.md#1-pause-事件去重机制-2025-02--⭐⭐⭐-new)
- [Agent 修复说明](docs/agent.md#0-pause-事件去重机制-2025-02-09--⭐⭐⭐-new)
- [组件架构更新](FRONTEND_COMPONENT_ARCHITECTURE.md#pause-事件去重机制-2025-02-09--⭐⭐⭐-new)
- [视觉设计更新](FRONTEND_VISUAL_GUIDE.md#pause-事件去重与状态清理-2025-02-09--⭐⭐⭐-new)

**最新更新 (2024)**:
- ✅ **前端架构简化**：重构类型系统，拆分为5个专注文件，优化代码组织
- ✅ **类型系统重构**：message.ts 拆分为 message-types.ts、message-guards.ts、message-helpers.ts
- ✅ **代码清理**：删除未使用文件（features.ts、report/index.ts、backup文件），减少~250行
- ✅ **Hook 简化**：useTaskSSE 接口统一，事件映射简化，减少复杂度
- ✅ **API 层优化**：删除重复方法，修复导出，统一错误处理
- ✅ **新增常量文件**：创建 constants.ts，提取共享层映射和配置
- ✅ **组件精简**：ChatPanel.tsx 从1033行减少到~640行
- ✅ **SSE 循环修复**：修复 Layer 1 完成后 SSE 连接无限循环问题
- ✅ **流状态管理**：添加 stream_states 跟踪，防止 EventSource 无限重连
- ✅ **暂停流程优化**：发送 stream_paused 事件，前端主动关闭连接
- ✅ **批准后重连**：批准后创建新的 SSE 连接，正确执行后续层级
- ✅ **UI状态管理**：引入 ViewMode 计算属性和 UnifiedContentSwitcher 组件
- ✅ **前端组件清理**：删除12个未使用组件，减少约1000-1500行代码
- ✅ **历史会话管理**：支持查看和加载历史村庄会话
- ✅ **报告同步优化**：实时同步层级报告到聊天流
- ✅ **检查点功能完善**：支持检查点查看、对比和回退
- ✅ **统一英文键名**：使用英文键名存储维度报告（如 `location`, `socio_economic`）
- ✅ **RAG系统集成**：集成检索增强生成，提升规划质量
- ✅ **日志系统完善**：实现统一的日志管理和追踪
- ✅ **限流保护**：添加API限流机制，防止滥用

---

## ❓ 常见问题

**Q: 上传的文件显示乱码怎么办？**

A: 系统已支持自动编码检测（UTF-8/GBK/GB2312），如果仍有问题：
- 确认文件内容确实是文本格式（非图片或扫描件）
- 对于 .txt 和 .md 文件，尝试用记事本另存为 UTF-8 编码
- 对于 .docx 和 .pdf 文件，确保包含可提取的文本（非扫描件）
- 查看浏览器控制台和后端日志中的解析信息

**Q: 支持哪些文件格式？**

A: 系统支持以下格式：
- **文本文件**: .txt, .md（自动编码检测）
- **Word文档**: .docx（提取段落文本）
- **PDF文档**: .pdf（提取页面文本）

**Q: Word 或 PDF 文件上传后内容为空？**

A: 可能的原因：
- 文件是扫描件（图片格式），不包含可提取的文本
- 文件受密码保护
- 文件格式损坏。建议：转换为 .txt 格式后再上传

**Q: LangSmith 追踪未生效**

- 检查 `LANGCHAIN_TRACING_V2=true` 和 API Key 配置

**Q: LLM 调用失败**

- 检查 API Key 是否有效
- 检查网络连接和 API 额度

**Q: 前端无法连接后端**

- 检查 `NEXT_PUBLIC_API_URL` 配置
- 确认后端服务已启动（`http://127.0.0.1:8000/health`）

**Q: Token 消耗过高**

- 使用更高效的模型（如 `glm-4-flash`）
- 系统已启用状态筛选优化

**Q: 规划结果提示"数据未提供"**

- 检查上传的文件内容是否正确解码（查看编码信息）
- 确认文件内容长度足够（至少10个字符）
- 查看浏览器控制台的调试日志

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

**贡献指南**:

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

---

## 📄 许可证

MIT License

---

## 🙏 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph) - 强大的状态图框架
- [LangChain](https://github.com/langchain-ai/langchain) - LLM 应用开发框架
- [Next.js](https://nextjs.org/) - React 框架
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化 Python Web 框架

---

**村庄规划 AI 助手** - 让村庄规划更智能、更高效
