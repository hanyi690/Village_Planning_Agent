# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 和 LangChain 的村庄规划智能系统，采用**分层架构**和**交互式工作流**实现专业的村庄规划辅助。

**当前版本：v4.2.0**

## ✨ 核心特性

- **🏗️ 分层图架构**：主图协调三层子图（现状分析、规划思路、详细规划）
- **📋 交互式工作流**：Checkpoint持久化、人工审查、逐步执行、回退修复
- **⚡ 高性能并行**：12+4+10个维度并行分析，智能状态筛选降低Token消耗
- **📊 LangSmith追踪**：完整的LLM调用链追踪，支持性能分析和调试
- **🔄 灵活恢复**：支持从任意检查点恢复执行
- **📁 多文件输入**：支持一次性加载多个数据文件，自动合并处理

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境

创建 `.env` 文件：

```env
# API 配置
ZHIPUAI_API_KEY=your_zhipuai_api_key_here
OPENAI_API_KEY=your_openai_api_key_here

# LLM 配置
LLM_MODEL=glm-4-flash
MAX_TOKENS=65536

# 向量数据库配置
VECTOR_STORE_DIR=data/vectordb
VECTORDB_PERSIST=true

# LangSmith 追踪配置
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_api_key_here
LANGCHAIN_PROJECT=village-planning-agent
```

### 3. 准备数据

创建村庄数据文件（建议使用结构化格式）：

```markdown
# 村庄基础数据

## 基本信息
- 村庄名称：[您的村庄名称]
- 人口：[人口数量]
- 面积：[面积数据]
- 主要产业：[主要产业]

## 人口与经济
- 户籍人口：[数据]
- 常住人口：[数据]
- 人均收入：[数据]
- 主要产业：[产业详情]

## 自然环境
- 地形：[地形描述]
- 森林覆盖率：[数据]
- 年降水量：[数据]
```

### 4. 运行

**完整规划流程**：

```bash
python -m src.cli.main --mode full \
    --project "项目名称" \
    --data data/village_data.txt \
    --output output.txt
```

**仅现状分析**：

```bash
python -m src.cli.main --mode analysis \
    --project "项目名称" \
    --data data/village_data.txt \
    --output analysis.txt
```

**仅规划思路**：

```bash
python -m src.cli.main --mode concept \
    --project "项目名称" \
    --data data/village_data.txt \
    --output concept.txt
```

---

## 🏗️ 图结构架构

### 主图结构

主图是整个系统的协调层，管理三层规划流程的执行顺序和状态传递。

```
┌─────────────────────────────────────────────────────────────────┐
│                         主图 (Main Graph)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │  START  │───▶│   pause      │───▶│ route_after_pause    │   │
│  └─────────┘    │  Manager     │    └──────────────────────┘   │
│                 └──────────────┘              │                 │
│                          │                   ▼                 │
│                          │         ┌─────────────────┐          │
│                          │         │ current_layer=1  │──▶ layer1_analysis
│                          │         │ current_layer=2  │──▶ layer2_concept
│                          │         │ current_layer=3  │──▶ layer3_detail
│                          │         └─────────────────┘          │
│                          │                   │                 │
│                          │                   ▼                 │
│                          │         ┌──────────────────────┐    │
│                          │         │  Layer Nodes         │    │
│                          │         │  - layer1_analysis   │    │
│                          │         │  - layer2_concept    │    │
│                          │         │  - layer3_detail     │    │
│                          │         └──────────────────────┘    │
│                          │                   │                 │
│                          │                   ▼                 │
│                          │         ┌──────────────────────┐    │
│                          │         │ route_after_layer*   │    │
│                          │         └──────────────────────┘    │
│                          │                   │                 │
│                          │                   ▼                 │
│                          │         ┌──────────────────────┐    │
│                          └────────▶│   tool_bridge        │    │
│                                    └──────────────────────┘    │
│                                           │                     │
│                                           ▼                     │
│                                    ┌──────────────┐             │
│                                    │ route_after  │             │
│                                    │ _tool_bridge │             │
│                                    └──────────────┘             │
│                                           │                     │
│                                           ▼                     │
│                                    ┌──────────────┐             │
│                                    │ generate_    │             │
│                                    │ final_output │──▶ END     │
│                                    └──────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

**主图节点列表**：

| 节点 | 功能 | 路由函数 |
|------|------|----------|
| `pause` | 暂停管理节点，在step模式下设置暂停状态 | `route_after_pause` |
| `layer1_analysis` | 执行现状分析子图（12维度并行） | `route_after_layer1` |
| `layer2_concept` | 执行规划思路子图（4维度并行） | `route_after_layer2` |
| `layer3_detail` | 执行详细规划子图（10维度分波次） | `route_after_layer3` |
| `tool_bridge` | 工具桥接节点，统一处理人工审查/暂停/修复 | `route_after_tool_bridge` |
| `generate_final` | 生成最终综合规划成果 | - |

**关键路由函数**：
- `route_after_pause(state)` → 根据当前层决定执行哪个layer节点
- `route_after_layer1(state)` → Layer 1完成后：进入tool_bridge暂停 或 进入layer2
- `route_after_layer2(state)` → Layer 2完成后：进入tool_bridge暂停 或 进入layer3
- `route_after_layer3(state)` → Layer 3完成后：进入final或END
- `route_after_tool_bridge(state)` → 工具桥接后：回pause/layer2/layer3/END

### 现状分析子图

12个维度并行分析，使用 Map-Reduce 模式。

```
┌─────────────────────────────────────────────────────────────────┐
│                   现状分析子图 (Layer 1)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  START ─▶ initialize ─▶ map_dimensions ─▶ [并行分发12个维度]     │
│                                          │                      │
│                                          ▼                      │
│  ┌────────────────────────────────────────────────────────┐    │
│  │                    12个并行分析节点                     │    │
│  ├────────────────────────────────────────────────────────┤    │
│  │                                                          │    │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐           │    │
│  │  │区位分析│ │社会经济│ │村民意愿│ │上位规划│  ... 8个   │    │
│  │  └────────┘ └────────┘ └────────┘ └────────┘           │    │
│  │       │          │          │          │               │    │
│  │       └──────────┴──────────┴──────────┘               │    │
│  │                      │                                 │    │
│  └──────────────────────┼─────────────────────────────────┘    │
│                         │                                       │
│                         ▼                                       │
│                  reduce_analyses (汇总)                         │
│                         │                                       │
│                         ▼                                       │
│               generate_report (生成综合报告)                    │
│                         │                                       │
│                         ▼                                       │
│                        END                                      │
└─────────────────────────────────────────────────────────────────┘
```

**现状分析12个维度**：

1. 区位与对外交通分析 (`location`)
2. 社会经济分析 (`socio_economic`)
3. 村民意愿与诉求分析 (`villager_wishes`)
4. 上位规划与政策导向分析 (`superior_planning`)
5. 自然环境与生态本底分析 (`natural_environment`)
6. 土地利用与合规性分析 (`land_use`)
7. 道路交通与街巷空间分析 (`traffic`)
8. 公共服务设施承载力分析 (`public_services`)
9. 基础设施现状分析 (`infrastructure`)
10. 生态绿地与开敞空间分析 (`ecological_green`)
11. 聚落形态与建筑风貌分析 (`architecture`)
12. 历史文化与乡愁保护分析 (`historical_culture`)

### 规划思路子图

4个维度并行分析，基于现状分析生成规划思路。

```
┌─────────────────────────────────────────────────────────────────┐
│                   规划思路子图 (Layer 2)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  输入：analysis_report + dimension_reports (来自Layer 1)        │
│                                                                  │
│  START ─▶ initialize ─▶ map_concept_dimensions ─▶ [并行分发4个]  │
│                                             │                    │
│                                             ▼                    │
│  ┌────────────────────────────────────────────────────────┐    │
│  │                    4个并行分析节点                      │    │
│  ├────────────────────────────────────────────────────────┤    │
│  │                                                          │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐        │    │
│  │  │资源禀赋分析│  │规划定位分析│  │发展目标分析│  ...    │    │
│  │  └────────────┘  └────────────┘  └────────────┘        │    │
│  │       │                │                │               │    │
│  │       └────────────────┴────────────────┘               │    │
│  │                      │                                  │    │
│  └──────────────────────┼──────────────────────────────────┘    │
│                         │                                       │
│                         ▼                                       │
│                reduce_analyses (汇总)                           │
│                         │                                       │
│                         ▼                                       │
│            generate_final_concept (生成规划思路报告)            │
│                         │                                       │
│                         ▼                                       │
│                        END                                      │
└─────────────────────────────────────────────────────────────────┘
```

**规划思路4个维度**：

1. 资源禀赋分析 (`resource_endowment`)
2. 规划定位分析 (`planning_positioning`)
3. 发展目标分析 (`development_goals`)
4. 规划策略分析 (`planning_strategies`)

### 详细规划子图

10个维度分波次执行，使用依赖链动态调度。

```
┌─────────────────────────────────────────────────────────────────┐
│                  详细规划子图 (Layer 3)                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  输入：analysis_report + concept_report (来自Layer 1+2)        │
│                                                                  │
│  START ─▶ initialize (设置current_wave=1)                       │
│           │                                                     │
│           ▼                                                     │
│  route_by_dependency_wave ──┬──▶ [Wave 1: 9个维度并行]          │
│           │                  │                                  │
│           │                  ▼                                  │
│           │         ┌────────────────┐                         │
│           │         │ Wave 1 完成   │                         │
│           │         └────────────────┘                         │
│           │                  │                                  │
│           │                  ▼                                  │
│           │         advance_wave (current_wave=2)               │
│           │                  │                                  │
│           │                  ▼                                  │
│           │         route_by_dependency_wave                    │
│           │                  │                                  │
│           │                  └──▶ [Wave 2: project_bank]        │
│           │                                                     │
│           └──▶ generate_final (汇总所有10个维度)                │
│                         │                                       │
│                         ▼                                       │
│                        END                                      │
└─────────────────────────────────────────────────────────────────┘
```

**详细规划10个维度**：

| Wave | 维度 | 依赖关系 |
|------|------|----------|
| **Wave 1** (并行) | 产业规划 (`industry`) | L1: socio_economic, land_use<br>L2: resource_endowment, development_goals |
| | 村庄总体规划 (`master_plan`) | L1: land_use, superior_planning, socio_economic, natural_environment<br>L2: planning_positioning, planning_strategies |
| | 道路交通规划 (`traffic`) | L1: location, traffic, villager_wishes, superior_planning<br>L2: planning_strategies |
| | 公服设施规划 (`public_service`) | L1: public_services, socio_economic, villager_wishes<br>L2: development_goals |
| | 基础设施规划 (`infrastructure`) | L1: infrastructure, land_use, villager_wishes<br>L2: development_goals |
| | 生态绿地规划 (`ecological`) | L1: natural_environment, ecological_green<br>L2: resource_endowment, planning_strategies |
| | 防震减灾规划 (`disaster_prevention`) | L1: infrastructure, natural_environment<br>L2: planning_strategies |
| | 历史文保规划 (`heritage`) | L1: historical_culture<br>L2: planning_positioning |
| | 村庄风貌指引 (`landscape`) | L1: architecture<br>L2: planning_positioning, resource_endowment |
| **Wave 2** (串行) | 建设项目库 (`project_bank`) | **依赖Wave 1的全部9个维度**<>L1: land_use, socio_economic, location, villager_wishes, superior_planning<br>L2: ALL (全部4个思路维度)<>L3: 前面9个详细规划维度 |

### 三层数据流

```
village_data (输入)
    │
    ▼
┌─────────────────────────────────────────┐
│   Layer 1: 现状分析子图 (12维度并行)    │
│   输出: analysis_report                 │
│         dimension_reports (字典)        │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│   Layer 2: 规划思路子图 (4维度并行)    │
│   输入: analysis_report                 │
│         dimension_reports (筛选)        │
│   输出: concept_report                  │
│         concept_dimension_reports       │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│   Layer 3: 详细规划子图 (10维度分波次) │
│   输入: analysis_report + concept_report│
│         维度报告字典 (筛选)             │
│   输出: detailed_plan                   │
└─────────────────────────────────────────┘
    │
    ▼
最终输出: 完整的村庄规划方案
```

---

## 📖 使用指南

### 基本用法

**Python API**：

```python
from src.agent import run_village_planning

result = run_village_planning(
    project_name="项目名称",
    village_data="村庄数据文本...",
    task_description="制定乡村振兴规划",
    constraints="生态优先，绿色发展"
)

# 访问各阶段成果
print(result['analysis_report'])    # 现状分析
print(result['planning_concept'])   # 规划思路
print(result['detailed_plan'])      # 详细规划
```

**多文件输入**：

```bash
# 逗号分隔多个文件，系统自动合并
python -m src.cli.main --mode full \
    --project "示例项目" \
    --data population.txt,infrastructure.pdf,economy.docx \
    --output planning.txt
```

### 交互模式

**核心功能**：

1. **Checkpoint持久化**：每层完成后自动保存检查点
2. **人工审查**：关键节点暂停，支持通过/驳回/回退
3. **逐步执行**：每层完成后暂停进入交互界面
4. **回退机制**：回退到任意检查点

**常用命令**：

| 命令 | 简写 | 说明 |
|------|------|------|
| `next` | `n` | 继续执行下一步 |
| `status` | `st` | 查看当前状态和进度 |
| `checkpoints` | `cp` | 列出所有检查点 |
| `rollback <id>` | `rb` | 回退到指定检查点 |
| `review` | `rv` | 审查当前报告 |
| `help` | `h` | 显示帮助信息 |
| `quit` | `q` | 退出程序 |

**启动逐步执行模式**：

```bash
python -m src.cli.main --mode step \
    --project "项目名称" \
    --data data/village_data.txt \
    --step-level layer
```

**从Checkpoint恢复**：

```bash
python -m src.cli.main --mode resume \
    --project "项目名称" \
    --resume-from checkpoint_001_layer2_completed
```

---

## 📊 LangSmith 追踪

### 启用追踪

在 `.env` 中配置：

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_xxx...
LANGCHAIN_PROJECT=village-planning-agent
```

### Trace 结构

```
📦 run_village_planning (主图执行)
  ├─ 📁 Layer 1: 现状分析
  │   ├─ 📍 区位分析 → 🤖 LLM Call
  │   ├─ 📍 社会经济 → 🤖 LLM Call
  │   └─ ... (10个其他维度)
  ├─ 📁 Layer 2: 规划思路
  │   ├─ 📍 资源禀赋 → 🤖 LLM Call
  │   └─ ... (3个其他维度)
  └─ 📁 Layer 3: 详细规划
      ├─ 📍 产业规划 → 🤖 LLM Call
      └─ ... (9个其他维度)
```

### 元数据示例

```json
{
  "project_name": "测试村庄",
  "timestamp": "2026-01-30T10:30:00",
  "agent_version": "v4.1.1",
  "dimension": "industry",
  "layer": 3
}
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

**自动检测**：
- `glm-*` → ZhipuAI
- `gpt-*` → OpenAI
- `deepseek-*` → DeepSeek

---

## ❓ 故障排除

### 常见问题

**Q: LangSmith 追踪未生效**
- 检查 `LANGCHAIN_TRACING_V2=true`
- 确认 `LANGCHAIN_API_KEY` 已正确设置

**Q: LLM 调用失败**
- 检查 API Key 是否有效
- 检查网络连接或API额度

**Q: 检查点保存失败**
- 确认 `checkpoints/` 目录存在
- 检查写入权限

**Q: Token 消耗过高**
- 已启用状态筛选优化（默认启用）
- 使用更高效的模型（如 glm-4-flash）

### 错误代码

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `ZHIPUAI_API_KEY not found` | 智谱AI Key 未配置 | 设置 `ZHIPUAI_API_KEY` |
| `ValueError: Unknown dimension` | 维度名称错误 | 检查维度名称拼写 |

---

## 🔄 更新日志

### v4.2.0 - 移除适配器模拟数据
- 移除所有适配器中的模拟数据生成逻辑
- GIS 适配器：移除 `fallback_to_mock` 配置和所有 `_analyze_*_mock` 方法
- 网络适配器：移除 `fallback_to_mock` 配置和所有 `_analyze_*_mock` 方法
- 人口适配器：移除 `fallback_to_simple` 配置和默认值逻辑
- 添加明确的参数验证，缺少必需参数时返回清晰的错误提示
- MockAdapter 保留但添加明确警告，标注为测试专用

### v4.1.1 - Bug修复
- 修复项目库（project_bank）变量名不匹配问题

### v4.0.1 - Pause管理节点解耦
- 添加pause管理节点，完全解耦暂停逻辑与业务逻辑
- 修复Step模式暂停失效问题

### v4.0.0 - 分层架构重构
- 实现清晰的分层架构：工具层 → 编排层 → CLI层
- 统一工具模式
- 修复Step Mode Layer 2跳过问题

### v3.0.0 - 交互模式
- 实现完整的交互模式：Checkpoint持久化、人工审查、逐步执行、回退修复

### v2.0.0 - 波次动态路由
- 引入波次动态路由和智能状态筛选

### v1.0.0 - 初始版本
- 基础功能：三层子图架构、并行执行

---

## 📄 开源协议

MIT License

---

**村庄规划 AI 助手** - 让村庄规划更智能、更高效
