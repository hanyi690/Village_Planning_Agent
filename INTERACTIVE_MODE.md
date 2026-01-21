# 村庄规划Agent交互模式使用指南

## 概述

村庄规划Agent现已支持完整的交互模式，允许用户逐步执行、审查、回退和修复规划过程。

## 核心功能

### 1. Checkpoint持久化

系统在每个Layer完成后自动保存checkpoint，支持：
- 状态持久化到JSON文件
- 从任意checkpoint恢复执行
- 自动管理checkpoint索引

**存储位置**：`results/{project_name}/{timestamp}/checkpoints/`

### 2. 人工审查机制

在关键节点暂停，提供完整的审查界面：
- 查看报告摘要和全文
- Approve（通过）/ Reject（驳回）/ View（查看）/ Rollback（回退）
- 输入详细的反馈意见

### 3. 逐步执行模式

在每层完成后暂停，等待用户确认：
- 查看当前执行进度
- 继续执行下一步
- 列出所有checkpoint
- 回退到指定checkpoint
- 审查当前报告

### 4. 回退机制

支持回退到任意checkpoint：
- 自动清理回退点之后的生成文件
- 创建回退记录
- 安全的确认机制

### 5. 修复机制

基于人工反馈智能修复：
- 自动识别需要修复的维度
- 用户确认修复范围（混合模式）
- 调用相应skill执行修复

## 使用方法

### 基本用法

#### 1. 完整规划流程（自动保存checkpoint）

```bash
python -m src.run_agent --mode full --project "某某村" --data village_data.txt
```

执行过程中会自动保存checkpoint。

#### 2. 逐步执行模式

在每个Layer完成后暂停，等待用户交互：

```bash
python -m src.run_agent --mode step --project "某某村" --data village_data.txt
```

可用的暂停级别：
- `--step-level layer`：在每层完成后暂停（默认）
- `--step-level dimension`：在每个维度完成后暂停
- `--step-level skill`：在每个skill完成后暂停

#### 3. 人工审查模式

启用人工审查，在关键节点等待用户确认：

```bash
python -m src.run_agent --mode full --review --project "某某村" --data village_data.txt
```

#### 4. 从checkpoint恢复

从指定的checkpoint恢复执行：

```bash
python -m src.run_agent --mode resume --project "某某村" --resume-from checkpoint_001_layer1_completed
```

#### 5. 列出所有checkpoint

查看项目的所有checkpoint：

```bash
python -m src.run_agent --mode list-checkpoints --project "某某村"
```

或使用：

```bash
python -m src.run_agent --project "某某村" --list-checkpoints
```

## 交互式命令

### 逐步执行模式命令

在逐步执行模式下，可使用以下命令：

| 命令 | 说明 |
|------|------|
| `next` / `continue` / `n` / `c` | 继续执行下一步 |
| `status` / `s` | 查看当前状态和进度 |
| `checkpoints` / `cp` / `list` | 列出所有checkpoint |
| `rollback <id>` / `rb <id>` | 回退到指定checkpoint |
| `review` / `rv` | 审查当前报告 |
| `help` / `h` / `?` | 显示帮助信息 |
| `quit` / `exit` / `q` | 退出程序 |

**示例**：
```
>>> next                    # 继续执行
>>> rollback checkpoint_001  # 回退到checkpoint_001
>>> status                  # 查看状态
>>> help                    # 显示帮助
```

### 人工审查选项

在人工审查界面，可执行以下操作：

| 选项 | 说明 |
|------|------|
| `[A]pprove` | 通过审查，继续执行 |
| `[R]eject` | 驳回，需要修复（会要求输入反馈） |
| `[V]iew` | 查看完整内容（分页显示） |
| `[L]Rollback` | 回退到之前的checkpoint |
| `[Q]uit` | 退出程序 |

## 修复流程

当选择Reject（驳回）并输入反馈后：

1. 系统自动识别需要修复的维度（基于关键词匹配）
2. 显示识别结果并要求用户确认
3. 用户可以：
   - 确认识别结果
   - 手动修改选择
   - 取消修复
4. 逐个维度调用skill执行修复
5. 修复完成后继续执行

**识别的关键词**：

| 维度 | 关键词 |
|------|--------|
| 产业规划 | 产业、经济、农业、工业、旅游、收入、gdp |
| 总体规划 | 总体规划、空间布局、用地、村庄布局 |
| 道路交通 | 交通、道路、运输、出行、路网、停车 |
| 公服设施 | 公共服务、教育、医疗、卫生、养老、文化、体育 |
| 基础设施 | 基础设施、水电、给排水、电力、通信、管网 |
| 生态绿地 | 生态、环境、绿地、绿化、环保、污染 |
| 防震减灾 | 防灾、减灾、安全、消防、防洪、地震 |
| 历史文保 | 历史、文化、文物、保护、古迹、传统 |
| 村庄风貌 | 风貌、建筑、风格、外观、色彩、高度 |
| 建设项目库 | 项目、建设、工程、投资、实施、计划 |

## Checkpoint管理

### Checkpoint文件格式

Checkpoint文件保存为JSON格式，包含：

```json
{
  "checkpoint_id": "checkpoint_001_layer1_completed",
  "timestamp": "2024-01-01T12:00:00",
  "metadata": {
    "layer": 1,
    "description": "Layer 1 现状分析完成",
    "project_name": "测试村"
  },
  "state": {
    "project_name": "测试村",
    "current_layer": 2,
    "layer_1_completed": true,
    "analysis_report": "...",
    "messages": [...]
  }
}
```

### Checkpoint命名规则

- 格式：`checkpoint_XXX_layerY_completed.json`
- XXX：层级编号（001-003）
- Y：层级编号（1-3）

示例：
- `checkpoint_001_layer1_completed.json` - Layer 1完成
- `checkpoint_002_layer2_completed.json` - Layer 2完成
- `checkpoint_003_layer3_completed.json` - Layer 3完成

## 完整工作流示例

### 场景1：逐步审查规划

```bash
# 1. 启动逐步执行模式
python -m src.run_agent --mode step --project "某某村" --data village_data.txt

# 2. Layer 1完成后，系统暂停并显示：
#    - 执行进度
#    - 当前状态
#    - 可用命令

>>> status          # 查看详细状态
>>> review          # 审查现状分析报告
>>> next            # 继续执行Layer 2

# 3. Layer 2完成后，继续
>>> review          # 审查规划思路
>>> next            # 继续执行Layer 3

# 4. Layer 3完成后，继续
>>> review          # 审查详细规划
>>> next            # 生成最终报告
```

### 场景2：人工审查并修复

```bash
# 1. 启动人工审查模式
python -m src.run_agent --mode full --review --project "某某村" --data village_data.txt

# 2. 在审查界面选择：
#    [R]eject - 驳回

# 3. 输入反馈：
#    产业规划部分需要加强乡村旅游发展，
#    道路交通规划不够详细

# 4. 系统识别维度：
#    识别到需要修复的维度:
#      1. 产业规划
#      2. 道路交通规划
#    确认这些维度? (Y/N/M): Y

# 5. 系统执行修复，然后继续
```

### 场景3：回退和恢复

```bash
# 1. 列出所有checkpoint
python -m src.run_agent --mode list-checkpoints --project "某某村"

# 输出：
#   1. Layer 1: 现状分析完成
#      ID: checkpoint_001_layer1_completed
#   2. Layer 2: 规划思路完成
#      ID: checkpoint_002_layer2_completed
#   3. Layer 3: 详细规划完成
#      ID: checkpoint_003_layer3_completed

# 2. 回退到Layer 2
>>> rollback checkpoint_002_layer2_completed

# 3. 或者从checkpoint恢复执行
python -m src.run_agent --mode resume --project "某某村" \
    --resume-from checkpoint_002_layer2_completed
```

## 编程接口

### 使用CheckpointManager

```python
from src.checkpoint import CheckpointManager

# 创建manager
manager = CheckpointManager(project_name="某某村")

# 保存checkpoint
checkpoint_id = manager.save_checkpoint(
    state=current_state,
    layer=1,
    description="Layer 1完成"
)

# 列出checkpoint
checkpoints = manager.list_checkpoints()

# 加载checkpoint
state = manager.load_checkpoint(checkpoint_id)

# 回退到checkpoint
restored_state = manager.rollback_to_checkpoint(
    checkpoint_id=checkpoint_id,
    current_output_dir=output_path
)
```

### 使用ReviewUI

```python
from src.interactive import ReviewUI

ui = ReviewUI()
result = ui.review_content(
    content=report_content,
    title="现状分析报告",
    allow_rollback=True,
    available_checkpoints=checkpoints
)

# 处理结果
if result["action"] == "approve":
    print("审查通过")
elif result["action"] == "reject":
    feedback = result["feedback"]
    print(f"反馈: {feedback}")
```

### 使用RevisionManager

```python
from src.revision import RevisionManager

manager = RevisionManager()

# 解析反馈
dimensions = manager.parse_feedback("产业规划不够详细")

# 确认维度
dimensions = manager.confirm_dimensions(dimensions)

# 修复维度
revised_results = manager.revise_multiple_dimensions(
    dimensions=dimensions,
    state=current_state,
    feedback="产业规划不够详细"
)
```

## 注意事项

1. **向后兼容**：新功能不影响现有的full/analysis/quick模式
2. **错误处理**：checkpoint保存失败不会中断主流程
3. **文件清理**：回退时会自动清理之后的生成文件（需用户确认）
4. **性能考虑**：checkpoint保存是异步的，不会显著影响执行速度
5. **终端支持**：Windows用户可能需要安装colorama以支持颜色显示

## 常见问题

### Q: Checkpoint存储在哪里？

A: 默认存储在 `results/{project_name}/{timestamp}/checkpoints/` 目录下。

### Q: 如何禁用checkpoint？

A: 在 `run_village_planning()` 函数中设置 `checkpoint_enabled=False`。

### Q: 修复失败怎么办？

A: 系统会保留原始结果，不会覆盖。可以重新执行修复或回退。

### Q: 如何查看详细的修复历史？

A: 使用 `RevisionManager.get_revision_history()` 方法。

### Q: 支持哪些暂停级别？

A:
- `layer`：每层完成后暂停（默认）
- `dimension`：每个维度完成后暂停
- `skill`：每个skill完成后暂停

### Q: 可以在修复后继续修复吗？

A: 可以。系统会记录修复次数，在prompt中提供历史信息。

## 技术架构

```
src/
├── checkpoint/              # Checkpoint模块
│   ├── __init__.py
│   ├── checkpoint_manager.py    # 核心管理逻辑
│   └── json_storage.py          # JSON存储实现
│
├── interactive/             # 交互式UI模块
│   ├── __init__.py
│   ├── review_ui.py             # 人工审查界面
│   └── cli.py                    # 交互式命令行界面
│
├── revision/                # 修复模块
│   ├── __init__.py
│   └── revision_manager.py      # 修复管理器
│
├── core/                    # 核心模块
│   └── dimension_skill.py       # Skill基类（含execute_with_feedback）
│
├── main_graph.py            # 主图（含新增节点）
├── agent.py                 # 对外接口（已扩展）
└── run_agent.py             # 命令行入口（新增模式）
```

## 更新日志

### v1.0.0 (当前版本)

- ✅ 实现Checkpoint持久化机制
- ✅ 实现人工审查界面
- ✅ 实现逐步执行模式
- ✅ 实现回退机制
- ✅ 实现修复机制
- ✅ 扩展命令行参数支持新功能
- ✅ 更新核心状态定义
- ✅ 集成所有组件到主图
