# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 和 LangChain 的智能村庄规划系统，提供 **Web 应用** 和 **CLI 工具** 两种使用方式，采用分层架构实现专业的村庄规划辅助。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-green.svg)](https://github.com/langchain-ai/langgraph)

## ✨ 核心特性

### 🌐 Web 应用
- **现代化界面**：基于 Next.js + Bootstrap 的响应式 Web 界面
- **实时进度**：SSE 流式传输，实时查看规划进度
- **文件管理**：支持多文件上传、会话历史、检查点管理
- **交互式审查**：支持人工审查、通过/驳回、回退修复

### 🏗️ 规划引擎
- **分层架构**：三层子图（现状分析 → 规划思路 → 详细规划）
- **并行分析**：12+4+10 个维度并行处理，高效执行
- **智能恢复**：检查点持久化，支持从任意阶段恢复
- **专业工具**：GIS 分析、网络分析、人口预测等专业适配器

### 🖥️ CLI 工具
- **命令行接口**：支持完整规划和单层执行
- **批处理**：适合批量处理多个规划任务
- **灵活集成**：易于集成到其他系统中

---

## 🚀 快速开始

### Web 应用（推荐）

**启动后端**：

```bash
cd backend
pip install -r requirements.txt
python main.py
# 后端运行在 http://localhost:8080
```

**启动前端**：

```bash
cd frontend
npm install
npm run dev
# 前端运行在 http://localhost:3000
```

**配置环境变量**：

创建 `.env` 文件：

```env
# API 配置
ZHIPUAI_API_KEY=your_zhipuai_api_key_here
OPENAI_API_KEY=your_openai_api_key_here

# LLM 配置
LLM_MODEL=glm-4-flash
MAX_TOKENS=65536
```

### CLI 工具

**完整规划流程**：

```bash
pip install -r requirements.txt

python -m src.cli.main --mode full \
    --project "项目名称" \
    --data data/village_data.txt \
    --output output.txt
```

**单层执行**：

```bash
# 仅现状分析
python -m src.cli.main --mode analysis --project "项目名称" --data data/village_data.txt

# 仅规划思路
python -m src.cli.main --mode concept --project "项目名称" --data data/village_data.txt

# 交互模式（逐步执行）
python -m src.cli.main --mode step --project "项目名称" --data data/village_data.txt
```

**从检查点恢复**：

```bash
python -m src.cli.main --mode resume \
    --project "项目名称" \
    --resume-from checkpoint_001_layer2_completed
```

---

## 📋 规划流程

### 三层规划架构

```
村庄数据输入
    ↓
┌─────────────────────────────────┐
│  Layer 1: 现状分析 (12维度并行)  │
│  - 区位交通、社会经济、村民意愿   │
│  - 自然环境、土地利用、基础设施   │
│  - 公共服务、历史文化、风貌等     │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│  Layer 2: 规划思路 (4维度并行)   │
│  - 资源禀赋分析                  │
│  - 规划定位分析                  │
│  - 发展目标分析                  │
│  - 规划策略分析                  │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│  Layer 3: 详细规划 (10维度)      │
│  Wave 1: 产业、交通、公服等9个   │
│  Wave 2: 建设项目库汇总          │
└─────────────────────────────────┘
    ↓
最终规划方案
```

### 专业工具适配器

| 适配器 | 功能 |
|--------|------|
| GIS 适配器 | 土地利用、土壤、水文空间分析 |
| 网络适配器 | 路网连通度、可达性、中心性分析 |
| 人口适配器 | 人口预测、结构分析、劳动力分析 |

---

## 📖 API 文档

### Web API

**规划相关 API** (`/api/planning`)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/start` | 启动新的规划任务 |
| GET | `/stream/{id}` | SSE 流式获取任务状态 |
| POST | `/resume` | 从检查点恢复执行 |
| POST | `/review/{id}` | 审查操作（通过/驳回/回退） |
| GET | `/checkpoints/{project}` | 列出所有检查点 |
| DELETE | `/sessions/{id}` | 删除会话 |

**村庄相关 API** (`/api/villages`)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/` | 获取所有村庄列表 |
| GET | `/{name}` | 获取村庄详情 |
| GET | `/{name}/layers/{layer}` | 获取层级内容 |
| GET | `/{name}/final-report` | 获取最终报告 |

**API 文档**：启动后端后访问 `http://localhost:8080/docs`

---

## 📂 项目结构

```
Village_Planning_Agent/
├── backend/                    # FastAPI 后端
│   ├── main.py                # 应用入口
│   ├── api/                   # API 路由
│   │   ├── orchestration.py  # 规划编排 API
│   │   ├── villages.py        # 村庄管理 API
│   │   ├── sessions.py        # 会话管理 API
│   │   └── files.py           # 文件上传 API
│   └── services/              # 业务逻辑
│
├── frontend/                   # Next.js 前端
│   ├── src/
│   │   ├── app/               # 页面（App Router）
│   │   │   ├── page.tsx       # 首页
│   │   │   ├── planning/      # 规划页面
│   │   │   └── history/       # 历史记录
│   │   └── components/        # React 组件
│   └── package.json
│
├── src/                        # 规划引擎核心
│   ├── orchestration/          # 编排层
│   │   └── main_graph.py      # 主图
│   ├── subgraphs/              # 子图
│   │   ├── analysis_subgraph.py
│   │   ├── concept_subgraph.py
│   │   └── detailed_plan_subgraph.py
│   ├── nodes/                  # 节点封装
│   ├── planners/               # 规划器
│   ├── tools/                  # 工具层
│   │   └── adapters/          # 专业适配器
│   └── core/                   # 核心组件
│
└── results/                    # 规划结果存储
```

---

## 📂 项目结构

```
Village_Planning_Agent/
├── src/
│   ├── cli/                    # CLI命令行界面
│   │   └── main.py             # 主入口
│   ├── orchestration/          # 编排层
│   │   └── main_graph.py       # 主图
│   ├── subgraphs/              # 子图模块
│   │   ├── analysis_subgraph.py    # 现状分析子图
│   │   ├── concept_subgraph.py     # 规划思路子图
│   │   └── detailed_plan_subgraph.py  # 详细规划子图
│   ├── core/                   # 核心组件
│   │   ├── dimension_mapping.py     # 维度依赖映射
│   │   └── llm_factory.py          # LLM工厂
│   ├── nodes/                  # 节点封装层 (v4.0.0新增)
│   │   ├── base_node.py          # 节点基类
│   │   ├── layer_nodes.py        # Layer节点: Layer1/2/3
│   │   ├── tool_nodes.py         # 工具节点: ToolBridge, PauseManager
│   │   └── final_nodes.py        # 最终输出节点
│   ├── planners/               # 规划器封装层
│   │   ├── base_planner.py       # 规划器基类
│   │   ├── analysis_planners.py  # 12个现状分析规划器
│   │   ├── concept_planners.py   # 4个规划思路规划器
│   │   └── detailed_planners.py  # 10个详细规划规划器
│   ├── tools/                  # 工具层
│   │   ├── adapters/            # 专业工具适配器
│   │   │   ├── base_adapter.py      # 适配器基类
│   │   │   ├── gis_adapter.py       # GIS空间分析适配器
│   │   │   ├── network_adapter.py   # 网络分析适配器
│   │   │   └── population_adapter.py # 人口预测适配器
│   │   ├── checkpoint_tool.py      # 检查点工具
│   │   ├── interactive_tool.py     # 交互工具
│   │   └── revision_tool.py        # 修复工具
│   └── utils/                  # 工具函数
├── data/                       # 数据目录
├── checkpoints/                # 检查点存储
├── output/                     # 输出目录
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🔧 专业工具适配器

系统提供专业工具适配器用于高级分析功能。适配器隔离了外部专业计算库的复杂性。

### 适配器列表

| 适配器 | 功能 | 外部依赖 |
|--------|------|----------|
| `GISAnalysisAdapter` | 土地利用、土壤、水文分析 | geopandas |
| `NetworkAnalysisAdapter` | 路网连通度、可达性、中心性分析 | networkx |
| `PopulationPredictionAdapter` | 人口预测、结构分析、劳动力分析 | 无（内置算法） |

### 使用适配器

适配器需要真实数据才能工作，不再提供模拟数据模式。

**GIS 适配器示例**：

```python
from src.tools.adapters.gis_adapter import GISAnalysisAdapter

# 创建适配器
adapter = GISAnalysisAdapter()

# 执行土地利用分析（需要真实数据）
result = adapter.execute(
    analysis_type="land_use_analysis",
    geo_data_path="path/to/land_use.shp"
)

if result.success:
    print(result.data)
else:
    print(f"错误: {result.error}")
```

**网络适配器示例**：

```python
from src.tools.adapters.network_adapter import NetworkAnalysisAdapter

adapter = NetworkAnalysisAdapter()

result = adapter.execute(
    analysis_type="connectivity_metrics",
    network_data={
        "nodes": [{"id": "A"}, {"id": "B"}],
        "edges": [{"source": "A", "target": "B", "weight": 1.0}]
    }
)
```

**人口适配器示例**：

```python
from src.tools.adapters.population_adapter import PopulationPredictionAdapter

adapter = PopulationPredictionAdapter()

result = adapter.execute(
    analysis_type="population_forecast",
    baseline_population=1000,
    baseline_year=2024,
    forecast_years=10,
    growth_rate=0.5
)
```

### 重要说明

1. **需要真实数据**：适配器不再提供模拟数据，必须提供真实数据文件或参数
2. **依赖安装**：使用适配器前需要安装相应的依赖库
   - GIS 适配器：`pip install geopandas`
   - 网络适配器：`pip install networkx`
3. **清晰错误提示**：缺少依赖或数据时，适配器会返回明确的错误信息
4. **MockAdapter 仅用于测试**：`MockAdapter` 类保留但明确标注为测试专用

---

## ⚙️ 配置说明

### LLM 配置

**ZhipuAI（推荐）**：
```env
ZHIPUAI_API_KEY=your_key
LLM_MODEL=glm-4-flash
```

**OpenAI**：
```env
OPENAI_API_KEY=your_key
LLM_MODEL=gpt-4o-mini
```

**自动检测**：`glm-*` → ZhipuAI, `gpt-*` → OpenAI, `deepseek-*` → DeepSeek

### 前端配置

创建 `frontend/.env.local`：
```env
NEXT_PUBLIC_API_URL=http://localhost:8080
```

---

## ❓ 常见问题

**Q: LangSmith 追踪未生效**
- 检查 `LANGCHAIN_TRACING_V2=true` 和 API Key 配置

**Q: LLM 调用失败**
- 检查 API Key 是否有效，检查网络连接和 API 额度

**Q: 前端无法连接后端**
- 检查 `NEXT_PUBLIC_API_URL` 配置
- 确认后端服务已启动（`http://localhost:8080/health`）

**Q: Token 消耗过高**
- 使用更高效的模型（如 `glm-4-flash`）
- 系统已启用状态筛选优化

---

## 🔄 更新日志

### v5.0.0 - Web 应用架构（当前）
- ✅ 完整的 Web 应用系统（Next.js + FastAPI）
- ✅ SSE 实时流式传输
- ✅ 交互式审查和检查点管理
- ✅ 简化的架构设计（移除重复状态管理）
- ✅ 会话历史和文件管理

### v4.2.0 - 适配器优化
- 移除适配器模拟数据，要求真实输入
- 增强参数验证和错误提示

### v4.0.0 - 分层架构重构
- 实现工具层 → 编排层 → CLI 层
- 统一工具模式

### v3.0.0 - 交互模式
- Checkpoint 持久化、人工审查、逐步执行、回退修复

### v2.0.0 - 波次动态路由
- 引入依赖链动态调度和智能状态筛选

---

## 📄 许可证

MIT License

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**村庄规划 AI 助手** - 让村庄规划更智能、更高效
