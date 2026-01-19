# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 和 LangChain 的村庄规划智能系统，采用**三层子图架构**实现专业的村庄规划辅助。

## ✨ 核心特性

- **🏗️ 三层子图架构**：现状分析 → 规划思路 → 详细规划
- **⚡ 并行执行**：10个维度并行分析，效率提升 7.5 倍
- **🎯 专业规划**：涵盖产业、交通、公服、设施、生态、防灾、文保、风貌、项目库等10个维度
- **🔧 简化配置**：标准 ZhipuAI SDK，开箱即用
- **📊 完整输出**：生成专业的村庄规划报告

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

# LLM 配置（使用 ZhipuAI GLM-4-Flash）
LLM_MODEL=glm-4-flash
MAX_TOKENS=65536

# 向量数据库配置
VECTOR_STORE_DIR=data/vectordb
VECTORDB_PERSIST=true
```

### 3. 运行

**方式1：完整规划流程**

```bash
python -m src.run_agent --mode full \
    --project "某某村" \
    --data data/example_data.txt \
    --output output.txt
```

**方式2：仅现状分析**

```bash
python -m src.run_agent --mode analysis \
    --project "某某村" \
    --data data/example_data.txt \
    --output analysis.txt
```

**方式3：仅规划思路**

```bash
python -m src.run_agent --mode concept \
    --project "某某村" \
    --data data/example_data.txt \
    --output concept.txt
```

---

## 🏗️ 三层架构

```
┌─────────────────────────────────────┐
│       主图 (Main Graph)             │
│  协调三层子图 + 管理规划流程         │
└──────────┬──────────────────────────┘
           │
           ├─── [Layer 1: 现状分析子图]
           │    ├── 10个维度并行分析
           │    └── 生成综合现状报告
           │
           ├─── [Layer 2: 规划思路子图]
           │    ├── 4个维度并行分析
           │    └── 生成规划思路报告
           │
           └─── [Layer 3: 详细规划子图]
                ├── 10个专业维度并行规划
                └── 生成详细规划报告
```

### 现状分析子图 - 10个维度

1. 区位分析
2. 社会经济分析
3. 自然环境分析
4. 土地利用分析
5. 道路交通分析
6. 公共服务设施分析
7. 基础设施分析
8. 生态绿地分析
9. 建筑分析
10. 历史文化分析

### 规划思路子图 - 4个维度

1. 资源禀赋分析
2. 规划定位分析
3. 发展目标分析
4. 规划策略分析

### 详细规划子图 - 10个专业维度

1. 产业规划
2. 村庄总体规划
3. 道路交通规划
4. 公服设施规划
5. 基础设施规划
6. 生态绿地规划
7. 防震减灾规划
8. 历史文保规划
9. 村庄风貌指引
10. 建设项目库

---

## 📂 项目结构

```
Village_Planning_Agent/
├── src/
│   ├── subgraphs/              # 子图模块
│   │   ├── analysis_subgraph.py      # 现状分析子图
│   │   ├── concept_subgraph.py       # 规划思路子图
│   │   ├── detailed_plan_subgraph.py # 详细规划子图
│   │   ├── analysis_prompts.py        # 分析维度 Prompt
│   │   ├── concept_prompts.py         # 概念维度 Prompt
│   │   └── detailed_plan_prompts.py   # 详细规划维度 Prompt
│   │
│   ├── main_graph.py           # 主图（三层流程协调）
│   ├── agent.py                # 入口（兼容层）
│   ├── run_agent.py            # CLI 入口
│   ├── config.py               # 配置
│   ├── llm_factory.py          # LLM 工厂
│   ├── tools/                  # 工具模块
│   └── utils/                  # 工具函数
│
├── data/
│   ├── example_data.txt        # 示例村庄数据
│   └── vectordb/               # 向量数据库
│
├── test/
│   ├── test_analysis_subgraph.py       # 子图测试
│   ├── test_concept_subgraph.py        # 子图测试
│   ├── test_detailed_plan_subgraph.py  # 子图测试
│   ├── simple_test_analysis.py         # 简化测试 ⭐
│   ├── simple_test_concept.py          # 简化测试 ⭐
│   ├── simple_test_detailed_plan.py    # 简化测试 ⭐
│   └── README_SIMPLE_TESTS.md          # 简化测试说明
│
├── .env.example                # 环境变量示例
├── requirements.txt            # 依赖
└── README.md                   # 本文件
```

---

## 📖 使用指南

### Python API

**完整规划流程**

```python
from src.agent import run_village_planning

result = run_village_planning(
    project_name="某某村",
    village_data="村庄数据文本...",
    task_description="制定乡村振兴规划",
    constraints="生态优先，绿色发展"
)

# 访问各阶段成果
print(result['analysis_report'])    # 现状分析
print(result['concept_report'])     # 规划思路
print(result['detailed_plan'])     # 详细规划
```

**仅现状分析**

```python
from src.subgraphs.analysis_subgraph import call_analysis_subgraph

result = call_analysis_subgraph(
    project_name="某某村",
    raw_data="村庄数据文本..."
)

print(result['analysis_report'])
```

**仅规划思路**

```python
from src.subgraphs.concept_subgraph import call_concept_subgraph

result = call_concept_subgraph(
    project_name="某某村",
    analysis_report="现状分析报告..."
)

print(result['concept_report'])
```

**仅详细规划**

```python
from src.subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph

result = call_detailed_plan_subgraph(
    project_name="某某村",
    analysis_report="现状分析报告...",
    planning_concept="规划思路报告...",
    task_description="制定村庄详细规划",
    constraints="生态优先，绿色发展"
)

print(result['detailed_plan_report'])
```

### 简化测试

```bash
# 分析子图测试（生成完整现状分析报告）
python -m test.simple_test_analysis

# 规划思路子图测试（生成完整规划思路报告）
python - m test.simple_test_concept

# 详细规划子图测试（生成完整详细规划报告）
python -m test.simple_test_detailed_plan
```

详见：[test/README_SIMPLE_TESTS.md](test/README_SIMPLE_TESTS.md)

---

## ⚙️ 配置说明

### LLM 配置

支持两种 LLM 提供商：

**1. ZhipuAI（推荐）**
```env
ZHIPUAI_API_KEY=your_key
LLM_MODEL=glm-4-flash
```

**2. OpenAI / DeepSeek**
```env
OPENAI_API_KEY=your_key
LLM_MODEL=gpt-4o-mini
# 或
DEEPSEEK_API_KEY=your_key
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-reasoner
```

### 自动检测

系统会根据 `LLM_MODEL` 自动选择正确的提供商：
- `glm-*` → ZhipuAI
- `gpt-*` → OpenAI
- `deepseek-*` → OpenAI (DeepSeek)

---

## 🎯 数据格式

推荐使用结构化的村庄数据：

```markdown
# 某某村基础数据

## 基本信息
- 村庄名称：某某村
- 人口：1200人
- 面积：5.2平方公里
- 主要产业：农业、旅游业

## 人口与经济
- 户籍人口：1200人
- 常住人口：980人
- 农民人均纯收入：18000元/年
- 主要产业：水稻种植、茶叶种植、乡村旅游

## 自然环境
- 地形：丘陵地貌
- 森林覆盖率：68%
- 年降水量：1600mm

# ... 其他维度
```

**格式要求**：
- 支持自由文本（推荐结构化格式）
- 建议包含所有10个维度的信息
- 可为 Markdown、纯文本等格式

---

## 🚀 技术栈

- **LLM**:
  - ZhipuAI GLM-4-Flash（推荐）
  - OpenAI GPT-4o-mini
  - DeepSeek-Reasoner
- **框架**: LangGraph, LangChain
- **特性**:
  - Send 机制（并行执行）
  - 子图嵌套（模块化）
  - 强类型状态（TypedDict）
  - 状态累加器（operator.add）

---

## 📊 性能表现

基于 ZhipuAI GLM-4-Flash 的测试数据：

| 任务 | 维度数 | 执行时间 | 说明 |
|------|--------|----------|------|
| 现状分析 | 10个 | ~50秒 | 并行执行 |
| 规划思路 | 4个 | ~50秒 | 并行执行 |
| 详细规划 | 10个 | ~2分钟 | 并行执行 |
| **完整流程** | - | **~3分钟** | 三层串联 |

**加速效果**：
- 现状分析：7.5倍加速（vs 串行）
- 整体流程：3.4倍加速（vs 串行）

---

## 🔧 自定义

### 修改 Prompt

编辑对应子图的 Prompt 文件：

- `src/subgraphs/analysis_prompts.py` - 现状分析维度
- `src/subgraphs/concept_prompts.py` - 规划思路维度
- `src/subgraphs/detailed_plan_prompts.py` - 详细规划维度

### 添加新维度

1. 在对应的 Prompt 文件中添加维度定义
2. 在子图的维度列表中注册
3. 添加对应的 Prompt 模板

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

---

## 📄 开源协议

MIT License

---

**村庄规划 AI 助手** - 让村庄规划更智能、更高效 ✨

基于 LangGraph 和 LangChain 实现
