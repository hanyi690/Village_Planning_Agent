# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 和 LangChain 的村庄规划智能系统，采用**分层架构**和**交互式工作流**实现专业的村庄规划辅助。

**当前版本：v4.0.0 - 分层架构重构** ✨

## ✨ 核心特性

- **🏗️ 清晰分层架构**：工具层 → 编排层 → CLI层
- **🔧 统一工具模式**：所有工具遵循统一的设计模式
- **📋 交互式工作流**：Checkpoint持久化、人工审查、逐步执行、回退修复
- **🎯 专业规划**：涵盖产业、交通、公服、设施、生态、防灾、文保、风貌、项目库等10个维度
- **⚡ 高性能并行**：10个维度并行分析，智能调度，效率提升
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

# ... 其他维度（交通、设施、生态、建筑、文化等）
```

### 4. 运行

**方式1：完整规划流程**

```bash
python -m src.cli.main --mode full \
    --project "项目名称" \
    --data data/village_data.txt \
    --output output.txt
```

**方式2：仅现状分析**

```bash
python -m src.cli.main --mode analysis \
    --project "项目名称" \
    --data data/village_data.txt \
    --output analysis.txt
```

**方式3：仅规划思路**

```bash
python -m src.cli.main --mode concept \
    --project "项目名称" \
    --data data/village_data.txt \
    --output concept.txt
```

---

## 🆕 交互模式使用指南

### 核心功能

#### 1. Checkpoint持久化

系统在每个Layer完成后自动保存检查点，包含：
- 执行状态（当前阶段、完成情况）
- 已生成的报告（现状分析、规划思路、详细规划）
- 维度报告字典（10个维度的详细分析）
- 时间戳和描述信息

**检查点存储位置**：`checkpoints/<项目名称>/`

#### 2. 人工审查机制

在关键节点暂停并展示报告，支持以下操作：

| 操作 | 说明 |
|------|------|
| `[A]pprove` | 通过审查，继续执行下一阶段 |
| `[R]eject` | 驳回报告，进入修复流程 |
| `[V]iew` | 查看完整报告内容 |
| `[L]Rollback` | 回退到之前的检查点 |
| `[Q]uit` | 退出程序 |

**驳回后流程**：
1. 系统提示输入反馈意见
2. 自动识别需要修复的维度
3. 调用对应Skill重新生成该维度内容
4. 整合修复结果到总报告中

#### 3. 逐步执行模式

在每个Layer完成后暂停，进入交互式命令行界面：

```bash
python -m src.cli.main --mode step \
    --project "项目名称" \
    --data data/village_data.txt \
    --step-level layer
```

**可用暂停级别**：
- `layer`：在每层完成后暂停（默认）
- `dimension`：在每个维度完成后暂停
- `skill`：在每个skill完成后暂停

#### 4. 交互式命令

在逐步执行模式下可使用以下命令：

| 命令 | 简写 | 说明 |
|------|------|------|
| `next` | `n`, `continue` | 继续执行下一步 |
| `status` | `st` | 查看当前状态和进度 |
| `checkpoints` | `cp` | 列出所有检查点 |
| `rollback <id>` | `rb` | 回退到指定检查点 |
| `review` | `rv` | 审查当前报告 |
| `help` | `h`, `?` | 显示帮助信息 |
| `quit` | `q`, `exit` | 退出程序 |

#### 5. 回退机制

回退到任意检查点并清理后续生成的内容：

```bash
# 在交互式界面中
>>> checkpoints
Available checkpoints:
  [0] checkpoint_000_layer1_completed - 2025-01-21 10:30:15
  [1] checkpoint_001_layer2_completed - 2025-01-21 10:45:22
  [2] checkpoint_002_layer3_completed - 2025-01-21 11:20:08

>>> rollback checkpoint_001_layer2_completed
⚠️  警告：此操作将：
    • 回退到 checkpoint_001_layer2_completed
    • 清理之后生成的 1 个文件
    • 当前状态将丢失

确认回退? [y/N]: y
✓ 已回退到 checkpoint_001_layer2_completed
```

#### 6. 从Checkpoint恢复

```bash
python -m src.cli.main --mode resume \
    --project "项目名称" \
    --resume-from checkpoint_001_layer2_completed
```

#### 7. 列出所有Checkpoint

```bash
python -m src.cli.main --mode list-checkpoints --project "项目名称"
```

### 完整工作流示例

```bash
# 步骤1：启动逐步执行模式
python -m src.cli.main --mode step \
    --project "示例村庄" \
    --data village_data.txt

# 步骤2：Layer 1（现状分析）完成后暂停
================================================================
当前状态：Layer 1 已完成
下一阶段：Layer 2（规划思路）
================================================================

>>> status              # 查看详细状态
当前项目: 示例村庄
当前阶段: Layer 1 完成
检查点: checkpoint_000_layer1_completed
报告已生成: analysis_report.txt

>>> review              # 审查现状分析报告
选择操作:
[A]pprove  [R]eject  [V]iew  [L]Rollback  [Q]uit
> A

>>> next                # 继续执行Layer 2

# 步骤3：Layer 2（规划思路）完成后
>>> review              # 审查规划思路
选择操作:
[A]pprove  [R]eject  [V]iew  [L]Rollback  [Q]uit
> R
请输入反馈意见: > 规划定位不够清晰，需要更具体的发展目标

# 系统自动识别需要修复的维度并重新生成

>>> next                # 继续执行Layer 3

# 步骤4：如需回退
>>> rollback checkpoint_000_layer1_completed
```

---

## 🏗️ 分层架构

### 架构层次

```
┌─────────────────────────────────────────┐
│            CLI 层 (cli/)                │  ← 命令行界面
│  - 参数解析、命令执行、用户交互           │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│        编排层 (orchestration/)          │  ← 业务逻辑
│  - 状态管理、流程协调、工具调用           │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│         工具层 (tools/)                 │  ← 可复用工具
│  - Checkpoint / Interactive / Revision  │
└─────────────────────────────────────────┘
```

### 三层规划流程

```
主图 (Main Graph)
    │
    ├─→ [Layer 1: 现状分析子图]
    │    ├─ 10个维度并行分析
    │    └─ 生成现状分析报告
    │
    ├─→ [Layer 2: 规划思路子图]
    │    ├─ 4个维度并行分析
    │    └─ 生成规划思路报告
    │
    └─→ [Layer 3: 详细规划子图]
         ├─ Wave 1: 9个维度并行
         └─ Wave 2: 项目库（依赖前9个）
```

### 路由决策流程图

系统在 `tool_bridge` 后根据当前状态自动路由到下一层：

```
                    route_after_tool_bridge()
                                │
                                ▼
                    ┌───────────────────────┐
                    │  检查 need_revision?   │
                    └───────────┬───────────┘
                                │
                ┌───────────────┴───────────────┐
                │ YES                           │ NO
                ▼                               ▼
        ┌───────────────┐           ┌───────────────────────┐
        │  修复模式路由   │           │    正常执行路由        │
        │ current_layer  │           │   current_layer 检查  │
        └───────┬───────┘           └───────────┬───────────┘
                │                               │
    ┌───────────┼───────────┐       ┌───────────┼───────────┐
    │           │           │       │           │           │
    ▼           ▼           ▼       ▼           ▼           ▼
  layer=1     layer=2     layer=3  layer=1     layer=2     layer=3
    │           │           │       │           │           │
    ▼           ▼           ▼       ▼           ▼           ▼
 "layer2"    "layer3"     "end"   "layer2"    "layer2"    "layer3"
 (修复后)    (修复后)    (结束)  (执行L2)   ✓(执行L2)   (执行L3)
                                           (固定修复)


【正常执行模式 - 详细路由逻辑】

current_layer == 1:
    └─→ 返回 "layer2"  [执行 layer2_concept 节点]

current_layer == 2:
    ├─ layer_1_completed == True?
    │   ├─ YES → 返回 "layer2"  [执行 layer2_concept 节点] ✓
    │   └─ NO  → 返回 "end"     [警告并结束]
    │
current_layer == 3:
    ├─ layer_2_completed == True?
    │   ├─ YES → 返回 "layer3"  [执行 layer3_detail 节点]
    │   └─ NO  → 返回 "end"     [警告并结束]
    │
other:
    └─→ 返回 "end"


【关键理解】
• current_layer = 2  表示"即将执行 Layer 2"，而不是"Layer 2已完成"
• current_layer = 3  表示"即将执行 Layer 3"，而不是"Layer 3已完成"
• layer_1_completed 表示"Layer 1 已完成"的标志
• layer_2_completed 表示"Layer 2 已完成"的标志


【Step模式执行流程】
用户输入"next" → tool_bridge → route_after_tool_bridge

Layer 1 完成后:
    state: {current_layer: 2, layer_1_completed: True}
    路由决策: current_layer==2 → 返回 "layer2" ✓
    结果: 执行 layer2_concept (Layer 2 规划思路)

Layer 2 完成后:
    state: {current_layer: 3, layer_2_completed: True}
    路由决策: current_layer==3 → 返回 "layer3" ✓
    结果: 执行 layer3_detail (Layer 3 详细规划)


【Bug修复说明】
修复前: current_layer==2 时错误返回 "layer3"，导致跳过 Layer 2
修复后: current_layer==2 时正确返回 "layer2"，确保执行 Layer 2
位置: src/orchestration/main_graph.py:772-790
```

### 规划维度

**现状分析（10个维度）**：
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

**规划思路（4个维度）**：
1. 资源禀赋分析
2. 规划定位分析
3. 发展目标分析
4. 规划策略分析

**详细规划（10个维度）**：
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
│   ├── tools/                  # 统一工具层
│   │   ├── file_manager.py    # 文件管理工具
│   │   ├── knowledge_tool.py  # 知识库工具
│   │   ├── map_tool.py        # 地图工具
│   │   ├── checkpoint_tool.py # Checkpoint工具 ✨
│   │   ├── interactive_tool.py # 交互式工具 ✨
│   │   └── revision_tool.py   # 修复工具 ✨
│   │
│   ├── orchestration/          # 编排层
│   │   └── main_graph.py      # 主图（纯业务逻辑）
│   │
│   ├── cli/                    # CLI层
│   │   ├── arg_parsers.py     # 参数解析
│   │   ├── commands.py        # 命令执行
│   │   └── main.py            # 入口
│   │
│   ├── subgraphs/              # 子图模块
│   │   ├── analysis_subgraph.py
│   │   ├── concept_subgraph.py
│   │   └── detailed_plan_subgraph.py
│   │
│   ├── core/                   # 核心组件
│   │   ├── dimension_mapping.py
│   │   ├── dimension_skill.py
│   │   ├── config.py
│   │   └── llm_factory.py
│   │
│   ├── utils/                  # 工具函数
│   ├── knowledge/              # 知识库
│   └── agent.py               # 入口函数
│
├── data/                       # 数据目录
├── checkpoints/                # 检查点存储 ✨
├── output/                     # 输出目录
├── tests/                      # 测试
├── .env.example
├── requirements.txt
└── README.md
```

---

## 📖 使用指南

### 多文件输入支持

支持通过逗号分隔多个数据文件，系统自动合并：

```bash
# 多个文件（逗号分隔）
python -m src.cli.main --mode full \
    --project "示例项目" \
    --data population.txt,infrastructure.pdf,economy.docx \
    --output planning.txt

# 支持的格式：txt, pdf, docx, md, pptx, xlsx
```

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

### Python API

**完整规划流程**：

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
print(result['concept_report'])     # 规划思路
print(result['detailed_plan'])     # 详细规划
```

**仅现状分析**：

```python
from src.agent import run_analysis_only

result = run_analysis_only(
    project_name="项目名称",
    village_data="村庄数据文本..."
)

print(result['analysis_report'])
```

**仅规划思路**：

```python
from src.agent import run_concept_only

result = run_concept_only(
    project_name="项目名称",
    analysis_report="现状分析报告..."
)

print(result['concept_report'])
```

**快速分析**：

```python
from src.agent import quick_analysis

report = quick_analysis("村庄数据文本...")
print(report)
```

---

## ⚙️ 配置说明

### LLM 配置

**1. ZhipuAI（推荐）**：
```env
ZHIPUAI_API_KEY=your_key
LLM_MODEL=glm-4-flash
```

**2. OpenAI**：
```env
OPENAI_API_KEY=your_key
LLM_MODEL=gpt-4o-mini
```

**3. DeepSeek**：
```env
DEEPSEEK_API_KEY=your_key
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-reasoner
```

### 自动检测

系统根据 `LLM_MODEL` 自动选择提供商：
- `glm-*` → ZhipuAI
- `gpt-*` → OpenAI
- `deepseek-*` → DeepSeek

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

### v4.0.0 - 分层架构重构（最新）

**重大重构**：实现清晰的分层架构，统一工具模式。

#### Bug Fixes

**Step Mode Layer 2 Skip Fix**：
- 修复了在step模式下Layer 2被跳过的问题
- 修正了`route_after_tool_bridge`函数中的路由逻辑
- 当`current_layer=2`时现在正确返回`"layer2"`而不是`"layer3"`
- 确保了Layer 1 → Layer 2 → Layer 3的正确执行顺序

#### 架构改进

**新增模块**：
- `src/tools/checkpoint_tool.py` - Checkpoint工具（遵循tool pattern）
- `src/tools/interactive_tool.py` - 交互式工具（合并ReviewUI和CLI）
- `src/tools/revision_tool.py` - 修复工具
- `src/orchestration/` - 编排层（纯业务逻辑）
- `src/cli/` - 统一CLI层

**移除模块**：
- `src/checkpoint/` → 重构为 `src/tools/checkpoint_tool.py`
- `src/interactive/` → 重构为 `src/tools/interactive_tool.py`
- `src/revision/` → 重构为 `src/tools/revision_tool.py`
- `src/main_graph.py` → 移至 `src/orchestration/main_graph.py`

#### 设计原则

**统一工具模式**：
```python
class ToolName:
    def method(self, ...) -> Dict[str, Any]:
        return {
            "success": bool,
            "content": Any,
            "metadata": Dict,
            "error": str
        }
```

**清晰分层**：
- 工具层：可复用的工具组件
- 编排层：纯业务逻辑，无UI代码
- CLI层：用户界面和参数处理

#### API变更

**Checkpoint工具**：
```python
from src.tools import CheckpointTool

tool = CheckpointTool("项目名称")
result = tool.save(state, layer, description)
checkpoint_id = result["checkpoint_id"]
```

**交互式工具**：
```python
from src.tools import InteractiveTool

tool = InteractiveTool()
result = tool.review_content(content, title, allow_rollback, checkpoints)
action = result["action"]  # "approve", "reject", "rollback", "quit"
```

**修复工具**：
```python
from src.tools import RevisionTool

tool = RevisionTool("项目名称")
result = tool.revise_dimension(dimension, state, feedback)
revised_content = result["content"]
```

### v3.0.0 - 交互模式

实现完整的交互模式，支持Checkpoint持久化、人工审查、逐步执行、回退修复。

### v2.0.0 - 波次动态路由

引入波次动态路由和智能状态筛选，大幅降低Token使用。

### v1.0.0 - 初始版本

基础功能：三层子图架构、并行执行、10个专业维度规划。

---

## 🚀 技术栈

- **LLM**: ZhipuAI GLM-4-Flash, OpenAI GPT-4o-mini, DeepSeek-Reasoner
- **框架**: LangGraph, LangChain
- **特性**:
  - 并行执行（Send机制）
  - 子图嵌套（模块化）
  - 强类型状态（TypedDict）
  - Checkpoint持久化
  - 交互式工作流

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

---

## 📄 开源协议

MIT License

---

**村庄规划 AI 助手** - 让村庄规划更智能、更高效 ✨
