# 规划思路子图使用指南

## 概述

规划思路子图是村庄规划系统的第二层核心组件，基于现状分析报告，生成系统的规划思路。

## 4个规划维度

### 1. 资源禀赋分析
- **自然资源**：土地、水、生物、景观资源
- **人文资源**：历史、文化、民俗、人才资源
- **经济资源**：产业、品牌、市场资源
- **区位与交通**：地理优势、交通条件

### 2. 规划定位分析
- **区域定位**：在区域发展格局中的角色
- **功能定位**：主导功能、特色功能、辅助功能
- **产业定位**：主导产业、配套产业、新兴产业
- **形象定位**：村庄形象口号、品牌标识、目标客群
- **发展层次定位**：近期、中期、远期定位

### 3. 发展目标分析
- **总体目标**：愿景、使命、核心价值观
- **分阶段目标**：
  - 近期（1-3年）：起步阶段
  - 中期（3-5年）：成长阶段
  - 远期（5-10年）：成熟阶段
- **指标体系**：经济、社会、生态、文化指标

### 4. 规划策略分析
- **空间布局策略**：功能分区、用地结构优化、村庄肌理
- **产业发展策略**：主导产业提升、产业融合、新业态培育
- **生态保护策略**：生态红线、环境整治、绿色发展
- **文化传承策略**：遗产保护、文化活态传承、文化创新
- **基础设施策略**：交通完善、设施配套、智慧乡村
- **社会治理策略**：组织建设、人才引进、资金保障、机制创新

## 快速开始

### Python API

```python
from src.subgraphs.concept_subgraph import call_concept_subgraph

result = call_concept_subgraph(
    project_name="某某村",
    analysis_report=analysis_report_text,
    task_description="制定乡村振兴规划思路",
    constraints="生态优先，绿色发展"
)

print(result['concept_report'])
```

### 命令行测试

```bash
# 完整测试
python -m src.test_concept_subgraph

# 单独测试
python -m src.test_concept_subgraph --test direct
python -m src.test_concept_subgraph --test wrapper
python -m src.test_concept_subgraph --test stream
```

## 架构特点

### 并行执行

使用 LangGraph 的 **Send 机制**实现4个维度同时分析：

```
[START]
   ↓
[初始化] → 设置4个规划维度
   ↓
[Map分发] → 创建4个并行任务
   ↓
[4个并行分析]
   ├─ 资源禀赋
   ├─ 规划定位
   ├─ 发展目标
   └─ 规划策略
   ↓
[Reduce汇总] → 整合4个结果
   ↓
[生成最终报告]
   ↓
[END]
```

### 状态管理

- 使用强类型 `TypedDict` 定义状态
- 使用 `operator.add` 累加并行分析结果
- 支持消息历史记录

### 错误处理

- 单个维度失败不影响其他维度
- 自动降级到简化模式
- 详细的错误日志

## 输出格式

### 最终报告结构

```markdown
# 村庄规划思路报告

## 一、资源禀赋分析
...

## 二、规划定位
...

## 三、发展目标
...

### 3.1 近期目标（1-3年）
...

### 3.2 中期目标（3-5年）
...

### 3.3 远期目标（5-10年）
...

## 四、规划策略
...

### 4.1 空间布局策略
...

### 4.2 产业发展策略
...
```

## 与主图集成

### 在主图中使用

```python
from src.subgraphs.concept_subgraph import call_concept_subgraph

def execute_layer2_concept(state):
    result = call_concept_subgraph(
        project_name=state["project_name"],
        analysis_report=state["analysis_report"],
        task_description=state["task_description"],
        constraints=state["constraints"]
    )
    return {"planning_concept": result["concept_report"]}
```

### 数据流转

```
主图 Layer 1（现状分析）
    ↓ analysis_report
主图 Layer 2（规划思路）
    ├─ 调用规划思路子图
    ├─ 并行分析4个维度
    └─ 生成 planning_concept
    ↓ planning_concept
主图 Layer 3（详细规划）
```

## 性能指标

| 指标 | 数值 |
|------|------|
| 并行维度数 | 4个 |
| 加速比 | 约 3-4x（相比串行） |
| 平均耗时 | 约30-40秒（使用GPT-4o-mini） |

## 扩展指南

### 添加新的规划维度

1. 在 `concept_prompts.py` 中添加新维度的 Prompt
2. 在 `concept_subgraph.py` 的 `initialize_concept_analysis` 中添加到维度列表
3. 更新 `list_concept_dimensions()` 函数

### 自定义 Prompt

编辑 `src/subgraphs/concept_prompts.py` 中的 Prompt 模板以适应具体需求。

## 故障排除

### 问题1: LLM 调用失败
**检查**：
- `OPENAI_API_KEY` 是否正确
- 网络连接是否正常
- 模型名称是否正确

### 问题2: 输出质量不佳
**优化**：
- 提供更详细的现状分析报告
- 明确具体的规划任务和约束
- 调整 Prompt 模板（在 `concept_prompts.py` 中）

### 问题3: 执行时间过长
**优化**：
- 使用更快的模型（如 `gpt-4o-mini`）
- 减少 `analysis_report` 的长度
- 降低 `MAX_TOKENS` 配置

## 相关文件

- `src/subgraphs/concept_subgraph.py` - 子图实现
- `src/subgraphs/concept_prompts.py` - Prompt 模板
- `src/subgraphs/analysis_subgraph.py` - 现状分析子图
- `src/main_graph.py` - 主图集成
- `src/test_concept_subgraph.py` - 测试脚本

---

**基于最新的 LangGraph 和 LangChain 实现** ✨
