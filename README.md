# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 和 LangChain 的村庄规划智能系统，采用**三层子图架构**和**波次动态路由**实现专业的村庄规划辅助。

## ✨ 核心特性

- **🏗️ 三层子图架构**：现状分析 → 规划思路 → 详细规划
- **⚡ 波次动态路由**：Wave 1 (9个维度并行) + Wave 2 (依赖等待)，智能调度
- **🎯 智能状态筛选**：每个维度只接收其依赖的3-4个现状维度，节省60-90% Token
- **📁 多文件输入**：支持一次性加载多个数据文件，自动合并处理
- **🚀 高性能并行**：10个维度并行分析，效率提升 7.5 倍
- **🎨 专业规划**：涵盖产业、交通、公服、设施、生态、防灾、文保、风貌、项目库等10个维度
- **🔧 简化配置**：标准 ZhipuAI SDK，开箱即用
- **📊 完整输出**：生成专业的村庄规划报告
- **🆕 交互模式**：支持Checkpoint持久化、人工审查、逐步执行、回退修复 ✨

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

**方式4：逐步执行模式** ✨ 新增

在每个Layer完成后暂停，等待用户交互：

```bash
python -m src.run_agent --mode step \
    --project "某某村" \
    --data data/example_data.txt \
    --step-level layer
```

可用暂停级别：
- `layer`：在每层完成后暂停（默认）
- `dimension`：在每个维度完成后暂停
- `skill`：在每个skill完成后暂停

**方式5：从Checkpoint恢复** ✨ 新增

从指定的checkpoint恢复执行：

```bash
python -m src.run_agent --mode resume \
    --project "某某村" \
    --resume-from checkpoint_001_layer1_completed
```

**方式6：列出所有Checkpoint** ✨ 新增

查看项目的所有checkpoint：

```bash
python -m src.run_agent --mode list-checkpoints --project "某某村"
```

---

## 🆕 交互模式详解

### 核心功能

1. **Checkpoint持久化**
   - 每个Layer完成后自动保存checkpoint
   - 支持从任意checkpoint恢复执行
   - 自动管理checkpoint索引和元数据

2. **人工审查机制**
   - 在关键节点暂停并展示报告
   - 支持Approve/Reject/View/Rollback操作
   - 输入详细的反馈意见

3. **逐步执行模式**
   - 在每层完成后暂停等待确认
   - 交互式命令：next/status/checkpoints/rollback/help
   - 查看当前执行进度和状态

4. **回退机制**
   - 回退到任意checkpoint
   - 自动清理回退点之后的生成文件
   - 安全的确认机制

5. **智能修复**
   - 基于反馈自动识别需要修复的维度
   - 混合模式：系统识别 + 用户确认
   - 调用相应skill执行修复

### 交互式命令

在逐步执行模式下可用：

| 命令 | 说明 |
|------|------|
| `next` / `continue` | 继续执行下一步 |
| `status` | 查看当前状态和进度 |
| `checkpoints` | 列出所有checkpoint |
| `rollback <id>` | 回退到指定checkpoint |
| `review` | 审查当前报告 |
| `help` | 显示帮助信息 |
| `quit` | 退出程序 |

### 人工审查选项

| 选项 | 说明 |
|------|------|
| `[A]pprove` | 通过审查，继续执行 |
| `[R]eject` | 驳回，需要修复 |
| `[V]iew` | 查看完整内容 |
| `[L]Rollback` | 回退到之前的checkpoint |
| `[Q]uit` | 退出程序 |

### 完整工作流示例

```bash
# 1. 启动逐步执行模式
python -m src.run_agent --mode step --project "某某村" --data village_data.txt

# 2. Layer 1完成后暂停
>>> status          # 查看详细状态
>>> review          # 审查现状分析报告
>>> next            # 继续执行Layer 2

# 3. Layer 2完成后
>>> review          # 审查规划思路
>>> next            # 继续执行Layer 3

# 4. 如需回退
>>> rollback checkpoint_001_layer1_completed
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
           │    ├── 优化：每个维度只处理相关数据
           │    └── 生成综合现状报告 + 维度报告字典
           │
           ├─── [Layer 2: 规划思路子图]
           │    ├── 4个维度并行分析
           │    ├── 优化：状态筛选（每个维度只接收3-4个现状维度）
           │    └── 生成规划思路报告 + 维度报告字典
           │
           └─── [Layer 3: 详细规划子图] ✨ 新增波次路由
                ├── Wave 1: 9个维度完全并行
                │    ├── 智能状态筛选（每个维度只接收依赖的3-4个现状维度）
                │    └── Token优化：节省60-90%
                │
                └── Wave 2: project_bank
                     ├── 等待Wave 1的9个维度完成
                     ├── 整合所有前序规划结果
                     └── 生成建设项目库
```

### 🌟 波次动态路由（Layer 3 详细规划）

**Wave 1 - 独立并行（9个维度）**：
1. 产业规划 - 依赖: 社会经济, 土地利用
2. 村庄总体规划 - 依赖: 土地利用, 区位, 自然环境
3. 道路交通规划 - 依赖: 区位, 交通
4. 公服设施规划 - 依赖: 公共服务, 社会经济
5. 基础设施规划 - 依赖: 基础设施, 土地利用
6. 生态绿地规划 - 依赖: 自然环境, 生态绿地
7. 防震减灾规划 - 依赖: 基础设施, 自然环境
8. 历史文保规划 - 依赖: 历史文化
9. 村庄风貌指引 - 依赖: 建筑

**Wave 2 - 依赖等待（1个维度）**：
10. 建设项目库 - 依赖: Wave 1的全部9个维度规划结果

### 📊 Token 优化效果

| 详细规划维度 | 原始Token | 优化后Token | 节省率 |
|-------------|-----------|-------------|--------|
| 产业规划 | 200,000 | 15,000 | 92.5% |
| 村庄总体规划 | 200,000 | 20,000 | 90.0% |
| 道路交通规划 | 200,000 | 12,000 | 94.0% |
| ... | ... | ... | ... |
| 项目建设库 | 272,000 | 88,000 | 67.6% |
| **平均** | **~210,000** | **~25,000** | **~88%** |

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
│   │   ├── detailed_plan_subgraph.py # 详细规划子图（支持波次路由）✨
│   │   ├── analysis_prompts.py        # 分析维度 Prompt
│   │   ├── concept_prompts.py         # 概念维度 Prompt
│   │   └── detailed_plan_prompts.py   # 详细规划维度 Prompt
│   │
│   ├── core/                   # 核心模块
│   │   ├── dimension_mapping.py      # 维度依赖映射（含波次配置）✨
│   │   ├── dimension_skill.py        # Skills封装（含修复支持）✨
│   │   ├── config.py                 # 配置
│   │   ├── llm_factory.py            # LLM 工厂
│   │   └── prompts.py                # 通用 Prompt
│   │
│   ├── checkpoint/             # ✨ Checkpoint模块（新增）
│   │   ├── checkpoint_manager.py     # Checkpoint管理核心
│   │   └── json_storage.py           # JSON存储实现
│   │
│   ├── interactive/            # ✨ 交互式UI模块（新增）
│   │   ├── review_ui.py              # 人工审查界面
│   │   └── cli.py                    # 交互式命令行界面
│   │
│   ├── revision/               # ✨ 修复模块（新增）
│   │   └── revision_manager.py       # 修复管理器
│   │
│   ├── utils/                  # 工具函数
│   │   ├── state_filter.py           # 状态筛选工具（含v2增强版）✨
│   │   ├── output_manager.py         # 输出管理器
│   │   └── logger.py                 # 日志工具
│   │
│   ├── main_graph.py           # 主图（三层流程协调 + 交互模式）✨
│   ├── agent.py                # 入口（兼容层）
│   ├── run_agent.py            # CLI 入口（新增模式）✨
│   ├── tools/                  # 工具模块
│   └── knowledge/              # 知识库模块
│
├── tests/                     # 测试模块 ✨ 新增
│   └── test_dynamic_routing.py      # 动态路由功能测试（19个测试）
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
├── data/
│   ├── example_data.txt        # 示例村庄数据
│   └── vectordb/               # 向量数据库
│
├── INTERACTIVE_MODE.md         # ✨ 交互模式使用指南（新增）
├── .env.example                # 环境变量示例
├── requirements.txt            # 依赖
└── README.md                   # 本文件
```

---

## 📖 使用指南

### 多文件输入支持 ✨ 新增

支持通过逗号分隔多个数据文件，系统会自动合并内容：

```bash
# 单个文件（原有用法，完全兼容）
python -m src.run_agent --mode full \
    --project "某某村" \
    --data village_data.txt

# 多个文件（逗号分隔）
python -m src.run_agent --mode full \
    --project "幸福村" \
    --data population.txt,infrastructure.pdf,economy.docx \
    --output planning.txt

# 现状分析 - 多文件
python -m src.run_agent --mode analysis \
    --project "前进村" \
    --data baseline.txt,supplement.pdf \
    --output analysis.txt
```

**支持的文件格式**：`txt`, `pdf`, `docx`, `md`, `pptx`, `xlsx` 等

**数据合并格式**：
```
# 文件: population.txt

人口数据内容...

================================================================================

# 文件: infrastructure.pdf

基础设施内容...

================================================================================

# 文件: economy.docx

经济数据内容...
```

**错误处理**：
- 所有文件成功 → 正常执行
- 部分文件失败 → 继续执行成功文件，警告失败文件
- 所有文件失败 → 退出并显示详细错误

**日志输出示例**：
```
[INFO] 检测到多个文件输入 (3 个文件)
[INFO] 成功加载 3 个文件:
[INFO]   ✓ population.txt (1000 字符)
[INFO]   ✓ infrastructure.pdf (2000 字符)
[INFO]   ✓ economy.docx (1500 字符)
```

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

**仅详细规划（推荐：带维度报告优化）**

```python
from src.subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph

result = call_detailed_plan_subgraph(
    project_name="某某村",
    analysis_report="现状分析报告...",
    planning_concept="规划思路报告...",
    # ✨ 新增：传递维度报告以启用波次动态路由和状态筛选优化
    dimension_reports={
        "location": "区位分析内容...",
        "socio_economic": "社会经济分析内容...",
        # ... 其他8个维度
    },
    concept_dimension_reports={
        "resource_endowment": "资源禀赋分析...",
        "planning_positioning": "规划定位分析...",
        # ... 其他2个维度
    },
    task_description="制定村庄详细规划",
    constraints="生态优先，绿色发展"
)

print(result['detailed_plan_report'])

# ✨ Token优化统计
token_stats = result.get('token_usage_stats', {})
for dim, stats in token_stats.items():
    print(f"{dim}: 节省 {stats['reduction_percent']}% Token")
```

### 简化测试

```bash
# 分析子图测试（生成完整现状分析报告）
python -m test.simple_test_analysis

# 规划思路子图测试（生成完整规划思路报告 + 状态优化）
python -m test.simple_test_concept

# 详细规划子图测试（生成完整详细规划报告 + 波次动态路由）
python -m test.simple_test_detailed_plan
```

### 单元测试

```bash
# 运行动态路由功能测试（19个测试）
python -m pytest tests/test_dynamic_routing.py -v
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

## 📊 性能表现

基于 ZhipuAI GLM-4-Flash 的测试数据：

### 执行时间

| 任务 | 维度数 | 执行时间 | 说明 |
|------|--------|----------|------|
| 现状分析 | 10个 | ~50秒 | 并行执行 |
| 规划思路 | 4个 | ~50秒 | 并行执行 + 状态筛选 |
| 详细规划 | 10个 | ~2分钟 | ✨ 波次路由 + 智能状态筛选 |
| **完整流程** | - | **~3分钟** | 三层串联 + Token优化 |

**加速效果**：
- 现状分析：7.5倍加速（vs 串行）
- 详细规划：5倍加速（Wave 1 并行 + Wave 2）
- 整体流程：3.4倍加速（vs 串行）

### Token 优化（新增）

| 层级 | 优化技术 | Token节省 |
|------|----------|----------|
| Layer 2（规划思路） | 状态筛选（每个维度3-4个现状） | ~60% |
| Layer 3（详细规划） | 状态筛选（每个维度3-4个现状+思路） | ~88% |
| Wave 1（9个维度并行） | 独立执行 | - |
| Wave 2（project_bank） | 等待依赖 | - |

**关键优化**：
- 每个规划维度只接收其依赖的3-4个现状维度，而非全部10个
- Token使用平均减少 60-90%
- 成本降低约 85%

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
  - ✨ 波次动态路由（Wave-based routing）
  - ✨ 依赖感知调度（Dependency-aware scheduling）
  - ✨ 智能状态筛选（Smart state filtering）

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

## 🔄 更新日志

### v3.0.0 - 交互模式（2025-01）✨ 最新

**重大更新**：实现完整的交互模式，支持Checkpoint持久化、人工审查、逐步执行、回退修复。

#### ✨ 新增功能

1. **Checkpoint持久化**
   - 每个Layer完成后自动保存checkpoint
   - 支持从任意checkpoint恢复执行
   - JSON格式存储，自动管理索引
   - 状态序列化/反序列化

2. **人工审查机制**
   - ReviewUI：完整的审查界面
   - Approve/Reject/View/Rollback操作
   - 用户反馈收集和处理
   - 集成checkpoint列表

3. **逐步执行模式**
   - InteractiveCLI：交互式命令行界面
   - 在每层完成后暂停
   - 命令：next/status/checkpoints/rollback/review/help/quit
   - 可配置暂停级别（layer/dimension/skill）

4. **回退机制**
   - 回退到任意checkpoint
   - 自动清理回退点之后的文件
   - Dry-run模式预览
   - 安全确认机制

5. **智能修复**
   - RevisionManager：修复流程管理
   - 基于关键词识别需要修复的维度
   - 混合模式：系统识别 + 用户确认
   - Skill的execute_with_feedback方法

6. **新增命令行模式**
   - `--mode step`：逐步执行模式
   - `--mode resume`：从checkpoint恢复
   - `--mode list-checkpoints`：列出所有checkpoint
   - `--step-level`：配置暂停级别
   - `--resume-from`：指定checkpoint ID

#### 🔧 模块扩展

**新增模块**：
- `src/checkpoint/` - Checkpoint管理
- `src/interactive/` - 交互式UI
- `src/revision/` - 修复管理器

**修改模块**：
- `src/main_graph.py` - 添加pause_node、revision_node，更新状态定义
- `src/core/dimension_skill.py` - 添加execute_with_feedback方法
- `src/agent.py` - 添加step_mode和step_level参数
- `src/run_agent.py` - 新增3种运行模式

#### 📝 文档更新

- 新增：`INTERACTIVE_MODE.md`（交互模式完整指南）
- 更新：`README.md`（交互模式文档）

#### 🎯 使用示例

```bash
# 逐步执行
python -m src.run_agent --mode step --project "村" --data data.txt

# 从checkpoint恢复
python -m src.run_agent --mode resume --project "村" --resume-from cp_001

# 列出checkpoint
python -m src.run_agent --mode list-checkpoints --project "村"
```

---

### v2.1.0 - 多文件输入支持（2025-01）

**新增功能**：

1. **多文件输入支持**
   - 支持通过逗号分隔多个数据文件
   - 自动合并多个文件内容
   - 100% 向后兼容现有单文件用法
   - 清晰的日志输出显示加载状态

2. **增强的错误处理**
   - 部分文件失败时继续执行
   - 详细的错误提示
   - 文件加载统计信息

3. **支持的格式**
   - `txt`, `pdf`, `docx`, `md`, `pptx`, `xlsx` 等多种格式
   - 混合格式支持（如：`file1.txt,file2.pdf,file3.docx`）

#### 使用示例

```bash
# 单文件（原有用法）
python -m src.run_agent --mode full --project "村" --data file.txt

# 多文件
python -m src.run_agent --mode full --project "村" --data pop.txt,infr.pdf
```

---

### v2.0.0 - 波次动态路由优化（2025-01）

**重大更新**：引入波次动态路由和智能状态筛选，大幅降低Token使用和执行成本。

#### ✨ 新增功能

1. **波次动态路由**
   - Wave 1: 9个独立维度完全并行执行
   - Wave 2: project_bank等待依赖完成后执行
   - 基于LangGraph的Send对象实现多波次调度

2. **智能状态筛选**
   - 每个维度只接收其依赖的3-4个现状维度
   - Token使用减少60-90%
   - 支持完整依赖链追踪

3. **依赖关系映射**
   - 精确的三层依赖关系定义（现状→思路→详细规划）
   - 支持依赖可视化（Mermaid图）
   - 波次执行摘要

4. **Skills封装（可选）**
   - 维度规划Skill基类
   - 10个具体Skill实现
   - Skill工厂模式

5. **增强的状态筛选**
   - `filter_state_for_detailed_dimension_v2()`
   - 依赖链追踪
   - Token统计和可视化

#### 🔧 优化改进

- 更新`analysis_prompts.py`：
  - `location`维度新增上位规划约束分析
  - `socio_economic`维度新增村民意愿分析

- 更新`detailed_plan_subgraph.py`：
  - 支持波次路由
  - 状态字段扩展
  - Token统计

#### 📝 文档更新

- 新增：`tests/test_dynamic_routing.py`（19个测试）
- 更新：`README.md`（波次路由文档）
- 更新：三个简化测试文件

#### ⚡ 性能提升

- Token使用：平均减少 **88%**
- 执行时间：缩短 **40-50%**
- 成本降低：约 **85%**

#### 🧪 测试覆盖

- 19个单元测试全部通过
- 覆盖依赖映射、状态筛选、波次路由、集成测试

---

### v1.0.0 - 初始版本

**基础功能**：
- 三层子图架构（现状分析 → 规划思路 → 详细规划）
- 并行执行支持
- 10个专业维度规划
- 简化配置和完整输出

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

---

## 📄 开源协议

MIT License

---

**村庄规划 AI 助手** - 让村庄规划更智能、更高效 ✨

基于 LangGraph 和 LangChain 实现
