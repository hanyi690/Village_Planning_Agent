# 村庄规划智能体 (Village Planning Agent)

基于 LangGraph 和 LangChain 的村庄规划智能系统，采用**分层架构**和**交互式工作流**实现专业的村庄规划辅助。

**当前版本：v4.1.0 - LangSmith完整集成** ✨

## ✨ 核心特性

- **🏗️ 清晰分层架构**：工具层 → 编排层 → CLI层
- **🔧 统一工具模式**：所有工具遵循统一的设计模式
- **📋 交互式工作流**：Checkpoint持久化、人工审查、逐步执行、回退修复
- **🎯 专业规划**：涵盖产业、交通、公服、设施、生态、防灾、文保、风貌、项目库等10个维度
- **⚡ 高性能并行**：12个维度并行分析，智能调度，效率提升
- **🔄 灵活恢复**：支持从任意检查点恢复执行
- **📁 多文件输入**：支持一次性加载多个数据文件，自动合并处理
- **📊 LangSmith追踪** [NEW]：完整的LLM调用链追踪，支持性能分析和调试

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

# LangSmith 追踪配置 [NEW]
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_api_key_here
LANGCHAIN_PROJECT=village-planning-agent
# LANGCHAIN_ENDPOINT=https://api.smith.langchain.com  # 可选
# LANGCHAIN_CALLBACKS_BACKGROUND=true  # 默认true
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
- 维度报告字典（12个维度的详细分析）
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

## 📊 LangSmith 追踪 [NEW]

### 概述

村庄规划智能体现在完整集成 LangSmith 追踪功能，提供：
- **完整调用链追踪**：从CLI → 主图 → 子图 → 规划器 → LLM的完整调用链
- **性能分析**：每个维度、每层的Token消耗和耗时分析
- **调试支持**：查看每个LLM调用的输入输出、Prompt内容
- **元数据标注**：自动添加项目名称、层级、维度等上下文信息

### 启用 LangSmith

**步骤1：获取 API Key**

1. 访问 [LangSmith](https://smith.langchain.com/)
2. 注册并创建账号
3. 在设置中创建 API Key

**步骤2：配置环境变量**

在 `.env` 文件中添加：

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_xxx...
LANGCHAIN_PROJECT=village-planning-agent
```

**步骤3：运行规划**

配置后，所有LLM调用将自动追踪：

```bash
python -m src.cli.main --mode full \
    --project "测试村庄" \
    --data village_data.txt
```

### 查看 Trace

1. 访问 [LangSmith Dashboard](https://smith.langchain.com/)
2. 选择项目 `village-planning-agent`
3. 查看最近的运行记录

### Trace 结构

每个完整的规划流程包含以下层级：

```
📦 run_village_planning (主图执行)
  ├─ 📁 Layer 1: 现状分析
  │   ├─ 📍 区位分析
  │   │   └─ 🤖 LLM Call (glm-4-flash)
  │   ├─ 📍 社会经济分析
  │   │   └─ 🤖 LLM Call (glm-4-flash)
  │   ├─ 📍 ... (8个其他维度)
  │   └─ 📝 综合报告生成
  │       └─ 🤖 LLM Call (glm-4-flash)
  ├─ 📁 Layer 2: 规划思路
  │   ├─ 📍 资源禀赋
  │   │   └─ 🤖 LLM Call (glm-4-flash)
  │   ├─ 📍 规划定位
  │   │   └─ 🤖 LLM Call (glm-4-flash)
  │   ├─ 📍 发展目标
  │   │   └─ 🤖 LLM Call (glm-4-flash)
  │   ├─ 📍 规划策略
  │   │   └─ 🤖 LLM Call (glm-4-flash)
  │   └─ 📝 综合思路生成
  │       └─ 🤖 LLM Call (glm-4-flash)
  └─ 📁 Layer 3: 详细规划
      ├─ 📍 产业规划
      │   └─ 🤖 LLM Call (glm-4-flash)
      ├─ 📍 ... (9个其他维度)
      └─ 📍 项目库
          └─ 🤖 LLM Call (glm-4-flash)
```

### 元数据信息

每个 Trace 包含以下元数据：

```json
{
  "project_name": "测试村庄",
  "timestamp": "2026-01-30T10:30:00",
  "agent_version": "v4.1.0",
  "dimension": "industry",
  "layer": 3,
  "layer_name": "detailed"
}
```

### 使用 Trace 进行调试

**场景1：查看特定维度的 Prompt**

1. 在 LangSmith Dashboard 中找到对应的 LLM Call
2. 点击 "Inputs" 查看 Prompt 内容
3. 分析 Prompt 是否符合预期

**场景2：分析 Token 消耗**

1. 在 Dashboard 中选择项目
2. 使用过滤器按 `dimension` 分组
3. 查看每个维度的总 Token 消耗

**场景3：对比不同版本的输出**

1. 在 `metadata` 中添加 `agent_version` 字段
2. 使用过滤器对比不同版本的 Trace
3. 分析输出质量差异

### 禁用 LangSmith

如果不需要追踪，只需设置：

```env
LANGCHAIN_TRACING_V2=false
```

系统将正常运行，不会记录 Trace。

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
    │    ├─ 12个维度并行分析
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
用户输入"next" → tool_bridge → route_after_tool_bridge → pause → route_after_pause

Layer 1 完成后:
    state: {current_layer: 2, layer_1_completed: True, step_mode: True}
    路由决策: current_layer==2 → 返回 "pause" → pause_manager_node设置pause_after_step=True → 返回 "layer2" ✓
    结果: 执行 layer2_concept (Layer 2 规划思路)

Layer 2 完成后:
    state: {current_layer: 3, layer_2_completed: True, step_mode: True}
    路由决策: current_layer==3 → 返回 "pause" → pause_manager_node设置pause_after_step=True → 返回 "layer3" ✓
    结果: 执行 layer3_detail (Layer 3 详细规划)


【Pause管理节点 - 解耦设计】
新增pause_manager_node()统一管理暂停状态，完全解耦暂停逻辑与业务逻辑：

暂停流程:
    START → pause (设置pause_after_step=True)
         → route_after_pause → layer1_analysis
         → route_after_layer1 → tool_bridge (暂停交互)
         → route_after_tool_bridge → pause (重置pause_after_step=True)
         → route_after_pause → layer2_concept
         → route_after_layer2 → tool_bridge (暂停交互) ✓
         → route_after_tool_bridge → pause (重置pause_after_step=True)
         → route_after_pause → layer3_detail
         → ...

优势:
    - 完全解耦：Layer执行函数不关心暂停逻辑
    - 集中管理：所有暂停场景在一个地方管理
    - 易于扩展：轻松支持人工审核、调试模式等新暂停场景
    - 符合LangGraph理念：使用节点和边管理状态转换


【Bug修复说明】
1. 修复Layer 2跳过问题 (v4.0.0)
   修复前: current_layer==2 时错误返回 "layer3"，导致跳过 Layer 2
   修复后: current_layer==2 时正确返回 "layer2"，确保执行 Layer 2
   位置: src/orchestration/main_graph.py:772-790

2. 修复Step模式暂停失效问题 (v4.0.1)
   修复前: 用户输入next后pause_after_step被设置为False，导致Layer 2及后续不暂停
   修复后: 新增pause管理节点，每次tool_bridge后重置pause_after_step=True
   位置: src/orchestration/main_graph.py:691, 719, 788, 855
```

### 规划维度

**现状分析（12个维度）**：
1. 区位分析
2. 社会经济分析
3. 村民意愿与诉求分析
4. 上位规划与政策导向分析
5. 自然环境分析
6. 土地利用分析
7. 道路交通分析
8. 公共服务设施分析
9. 基础设施分析
10. 生态绿地分析
11. 建筑分析
12. 历史文化分析

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

### 三层维度依赖关系图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           村庄数据输入 (village_data)                       │
│                     人口、经济、交通、设施、生态、建筑、文化...               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Layer 1: 现状分析 (12个维度并行)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐         │
│  │ 区位分析│ │社会经济│ │村民意愿│ │上位规划│ │自然环境│ │土地利用│  ...   │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘         │
│                                                                             │
│  输出: analysis_report + dimension_reports (12个维度的详细分析)              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Layer 2: 规划思路 (4个维度并行)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                          依赖: Layer 1 的分析报告                           │
│                                                                             │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐        │
│  │ 资源禀赋分析│ → │ 规划定位分析│ → │ 发展目标分析│ → │ 规划策略分析│        │
│  └────────────┘   └────────────┘   └────────────┘   └────────────┘        │
│         │                 │                 │                 │             │
│         └─────────────────┴─────────────────┴─────────────────┘             │
│                                     │                                       │
│  输出: concept_report (基于现状分析的规划思路)                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              Layer 3: 详细规划 (Wave 1 + Wave 2 分波次执行)                │
├─────────────────────────────────────────────────────────────────────────────┤
│                          依赖: Layer 1 + Layer 2 的输出                     │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Wave 1: 9个维度并行执行                          │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                     │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐           │   │
│  │  │ 产业规划│ │ 总体规划│ │ 道路规划│ │ 公服规划│ │ 设施规划│  ...    │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘           │   │
│  │       │          │          │          │          │                 │   │
│  │       └──────────┴──────────┴──────────┴──────────┘                 │   │
│  │                      │                                               │   │
│  └──────────────────────┼───────────────────────────────────────────────┘   │
│                         │                                                   │
│                         ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Wave 2: 建设项目库 (串行)                         │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                     │   │
│  │                    依赖: Wave 1 的所有9个维度输出                     │   │
│  │                                                                     │   │
│  │  ┌──────────────────────────────────────────────────────┐          │   │
│  │  │          建设项目库 (Project Library)                 │          │   │
│  │  │  基于前9个维度的规划成果，整合生成具体建设项目清单     │          │   │
│  │  └──────────────────────────────────────────────────────┘          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  输出: detailed_plan (包含所有10个维度的详细规划)                            │
└─────────────────────────────────────────────────────────────────────────────┘


【数据流详解】

                village_data (输入)
                      │
                      ▼
    ┌─────────────────────────────────┐
    │   Layer 1: 现状分析子图          │
    │   ├─ 区位分析 → dimension_reports["区位分析"]
    │   ├─ 社会经济 → dimension_reports["社会经济"]
    │   ├─ 村民意愿 → dimension_reports["村民意愿"]
    │   ├─ 上位规划 → dimension_reports["上位规划"]
    │   ├─ 自然环境 → dimension_reports["自然环境"]
    │   ├─ 土地利用 → dimension_reports["土地利用"]
    │   ├─ 道路交通 → dimension_reports["道路交通"]
    │   ├─ 公服设施 → dimension_reports["公服设施"]
    │   ├─ 基础设施 → dimension_reports["基础设施"]
    │   ├─ 生态绿地 → dimension_reports["生态绿地"]
    │   ├─ 建筑分析 → dimension_reports["建筑分析"]
    │   └─ 历史文化 → dimension_reports["历史文化"]
    │
    │   → 输出: analysis_report (汇总12个维度)
    └─────────────────────────────────┘
                      │
                      ▼
    ┌─────────────────────────────────┐
    │   Layer 2: 规划思路子图          │
    │   输入: analysis_report         │
    │
    │   ├─ 资源禀赋分析 (基于现状)
    │   ├─ 规划定位分析 (基于现状)
    │   ├─ 发展目标分析 (基于现状+定位)
    │   └─ 规划策略分析 (基于现状+定位+目标)
    │
    │   → 输出: concept_report
    └─────────────────────────────────┘
                      │
                      ▼
    ┌─────────────────────────────────┐
    │   Layer 3: 详细规划子图          │
    │   输入: analysis_report + concept_report
    │
    │   ┌─ Wave 1 (并行) ─────────────┐
    │   │  ├─ 产业规划       (依赖 L1+L2)
    │   │  ├─ 村庄总体规划   (依赖 L1+L2)
    │   │  ├─ 道路交通规划   (依赖 L1+L2)
    │   │  ├─ 公服设施规划   (依赖 L1+L2)
    │   │  ├─ 基础设施规划   (依赖 L1+L2)
    │   │  ├─ 生态绿地规划   (依赖 L1+L2)
    │   │  ├─ 防震减灾规划   (依赖 L1+L2)
    │   │  ├─ 历史文保规划   (依赖 L1+L2)
    │   │  └─ 村庄风貌指引   (依赖 L1+L2)
    │   └──────────────────────────────┘
    │              │
    │              ▼
    │   ┌─ Wave 2 (串行) ─────────────┐
    │   │  └─ 建设项目库 (依赖 Wave 1 的所有输出)
    │   │     - 需要前9个维度的规划成果
    │   │     - 整合生成具体项目清单
    │   └──────────────────────────────┘
    │
    │   → 输出: detailed_plan (包含所有10个维度)
    └─────────────────────────────────┘


【关键依赖关系】

1. Layer 2 依赖 Layer 1
   - 规划思路需要基于现状分析结果
   - 传入参数: analysis_report

2. Layer 3 依赖 Layer 1 + Layer 2
   - 详细规划需要现状分析 + 规划思路
   - 传入参数: analysis_report + concept_report

3. Layer 3 内部: Wave 2 依赖 Wave 1
   - 建设项目库需要前9个维度的规划成果
   - 确保项目库与其他规划内容一致


【执行顺序总结】

输入数据
    ↓
Layer 1 (12个维度并行) → 现状分析报告
    ↓
Layer 2 (4个维度并行) → 规划思路报告
    ↓
Layer 3
    ├─ Wave 1 (9个维度并行) → 9个专项规划
    └─ Wave 2 (建设项目库) → 项目清单
    ↓
最终输出: 完整的村庄规划方案
```

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

### v4.0.1 - Pause管理节点解耦

**新功能**：添加pause管理节点，完全解耦暂停逻辑与业务逻辑。

#### 新增功能

**Pause管理节点**：
- 新增 `pause_manager_node()` 函数统一管理暂停状态
- 新增 `route_after_pause()` 函数处理pause节点后的路由
- 在step模式下自动重置 `pause_after_step=True`
- 支持未来扩展其他暂停场景（人工审核、调试模式等）

#### Bug Fixes

**Step模式暂停失效修复**：
- 修复了在step模式下Layer 2完成后不暂停的问题
- 当用户输入`next`后，pause_after_step会被pause管理节点重置为True
- 确保每一层完成后都能正确暂停等待用户输入
- 完全解耦：Layer执行函数不再需要关心暂停逻辑

#### 技术改进

**架构优化**：
- 修改 `START` 边：从直接进入layer1改为先进入pause节点
- 修改 `route_after_tool_bridge`：在step模式下路由到pause节点
- 集中管理暂停逻辑，便于维护和扩展
- 符合LangGraph设计理念：使用节点和边管理状态转换

### v4.0.0 - 分层架构重构

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

基础功能：三层子图架构、并行执行、12个现状分析维度、10个详细规划维度。

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

## 🛠️ 开发指南

### 环境搭建

**1. 克隆项目**

```bash
git clone <repository-url>
cd Village_Planning_Agent
```

**2. 创建虚拟环境**

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

**3. 安装依赖**

```bash
pip install -r requirements.txt
```

**4. 配置环境变量**

复制 `.env.example` 到 `.env` 并填写配置：

```bash
cp .env.example .env
```

### 项目结构

```
Village_Planning_Agent/
├── src/
│   ├── cli/                    # CLI命令行界面
│   │   └── main.py             # 主入口
│   ├── core/                   # 核心模块
│   │   ├── config.py           # 配置管理
│   │   ├── llm_factory.py      # LLM工厂（支持LangSmith）
│   │   ├── langsmith_integration.py  # LangSmith集成 [NEW]
│   │   ├── dimension_mapping.py # 维度依赖映射
│   │   └── state_builder.py    # 状态构建器
│   ├── orchestration/          # 编排层
│   │   └── main_graph.py       # 主图（支持LangSmith）
│   ├── subgraphs/              # 子图
│   │   ├── analysis_subgraph.py    # 现状分析子图
│   │   ├── concept_subgraph.py     # 规划思路子图
│   │   └── detailed_plan_subgraph.py  # 详细规划子图
│   ├── planners/               # 规划器
│   │   ├── base_planner.py     # 基类（支持LangSmith）
│   │   ├── analysis_planners.py    # 现状分析规划器
│   │   ├── concept_planners.py     # 规划思路规划器
│   │   └── detailed_planners.py    # 详细规划规划器
│   ├── nodes/                  # 节点
│   │   ├── layer_nodes.py      # 层节点
│   │   └── tool_nodes.py       # 工具节点
│   ├── tools/                  # 工具层
│   │   ├── checkpoint_tool.py  # 检查点工具
│   │   ├── interactive_tool.py # 交互工具
│   │   ├── revision_tool.py    # 修复工具
│   │   └── file_manager.py     # 文件管理工具
│   └── utils/                  # 工具函数
│       ├── logger.py           # 日志工具
│       ├── state_filter.py     # 状态筛选
│       └── output_manager.py   # 输出管理
├── tests/                      # 测试
│   └── test_langsmith_integration.py  # LangSmith集成测试 [NEW]
├── checkpoints/                # 检查点存储（自动创建）
├── output/                     # 输出文件（自动创建）
├── data/                       # 数据文件
├── requirements.txt            # Python依赖
├── .env.example               # 环境变量示例
└── README.md                  # 项目文档
```

### 运行测试

**运行所有测试**：

```bash
pytest tests/
```

**运行特定测试**：

```bash
pytest tests/test_langsmith_integration.py -v
```

**查看测试覆盖率**：

```bash
pytest tests/ --cov=src --cov-report=html
```

### 调试技巧

**1. 启用详细日志**

在 `.env` 中设置：

```env
LOG_LEVEL=DEBUG
```

**2. 使用 LangSmith 追踪**

LangSmith 可以帮助可视化整个执行流程：

- 在 Dashboard 中查看完整调用链
- 分析每个节点的输入输出
- 定位性能瓶颈

**3. 单步执行模式**

```bash
python -m src.cli.main --mode step --project "测试" --data test.txt
```

### 添加新功能

**1. 添加新的规划维度**

1. 在 `dimension_mapping.py` 中定义依赖关系
2. 在对应的 `*_planners.py` 中创建规划器类
3. 在 `*_prompts.py` 中添加 Prompt 模板
4. 更新子图的维度列表

**2. 集成 LangSmith 追踪**

```python
from src.core.langsmith_integration import get_langsmith_manager

langsmith = get_langsmith_manager()
if langsmith.is_enabled():
    metadata = langsmith.create_run_metadata(
        project_name="项目名",
        dimension="维度名",
        layer=1
    )
    llm = create_llm(metadata=metadata)
```

---

## ❓ 故障排除

### 常见问题

**Q: LangSmith 追踪未生效**

**A:** 检查以下几点：
1. 确认 `LANGCHAIN_TRACING_V2=true`
2. 确认 `LANGCHAIN_API_KEY` 已正确设置
3. 查看日志中是否有 `[LLM Factory] LangSmith tracing enabled`
4. 访问 LangSmith Dashboard 确认项目名称正确

**Q: LLM 调用失败**

**A:** 可能原因：
1. API Key 未设置或无效 → 检查 `.env` 文件
2. 网络问题 → 检查网络连接
3. API 额度耗尽 → 检查账户余额
4. 超时 → 增加 `MAX_TOKENS` 或使用更快的模型

**Q: 检查点保存失败**

**A:** 检查：
1. `checkpoints/` 目录是否存在
2. 是否有写入权限
3. 磁盘空间是否充足

**Q: 维度依赖关系错误**

**A:** 检查：
1. `dimension_mapping.py` 中的依赖定义
2. 确保 `depends_on_detailed` 中的维度确实存在

**Q: Token 消耗过高**

**A:** 优化方案：
1. 启用状态筛选（已默认启用）
2. 使用更高效的模型（如 glm-4-flash）
3. 减少 Prompt 长度
4. 在 LangSmith 中分析各维度 Token 消耗，优化高频维度

### 错误代码

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `ZHIPUAI_API_KEY not found` | 智谱AI Key 未配置 | 设置 `ZHIPUAI_API_KEY` |
| `OPENAI_API_KEY not found` | OpenAI Key 未配置 | 设置 `OPENAI_API_KEY` |
| `ValueError: Unknown dimension` | 维度名称错误 | 检查维度名称拼写 |
| `ConnectionError` | 网络连接失败 | 检查网络或代理设置 |
| `TimeoutError` | 请求超时 | 增加超时时间或检查网络 |

### 获取帮助

1. **查看日志**：`logs/` 目录下的日志文件
2. **启用 Debug 模式**：设置 `LOG_LEVEL=DEBUG`
3. **查看 LangSmith Trace**：分析完整的调用链
4. **提交 Issue**：[GitHub Issues](https://github.com/your-repo/issues)

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

---

## 📄 开源协议

MIT License

---

**村庄规划 AI 助手** - 让村庄规划更智能、更高效 ✨
