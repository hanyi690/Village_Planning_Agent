# 智能体架构文档

> 村庄规划智能体 - LangGraph 核心引擎详解

## 目录

- [架构概述](#架构概述)
- [主图编排](#主图编排)
- [三层规划系统](#三层规划系统)
- [状态定义](#状态定义)
- [路由决策](#路由决策)
- [暂停恢复机制](#暂停恢复机制)

---

## 架构概述

### 技术栈

- **LangGraph 1.0+**: 状态图编排框架
- **LangChain**: LLM 应用开发框架
- **AsyncSqliteSaver**: SQLite 状态持久化
- **Pydantic V2**: 数据验证

### 设计原则

1. **分层架构**: 三层递进式规划（现状分析 → 规划思路 → 详细规划）
2. **并行执行**: 每层内多个维度使用 `Send` 机制并行处理
3. **状态持久化**: AsyncSqliteSaver 自动保存状态到 SQLite
4. **检查点机制**: 每层完成后自动保存，支持中断恢复

### 目录结构

```
src/
├── orchestration/
│   └── main_graph.py            # 主图编排
├── subgraphs/
│   ├── analysis_subgraph.py     # Layer 1: 现状分析子图
│   ├── concept_subgraph.py      # Layer 2: 规划思路子图
│   └── detailed_plan_subgraph.py # Layer 3: 详细规划子图
├── nodes/
│   ├── base_node.py             # 节点基类
│   ├── subgraph_nodes.py        # 子图节点
│   └── tool_nodes.py            # 工具节点
├── core/
│   ├── config.py                # 配置
│   ├── dimension_config.py      # 维度配置
│   └── llm_factory.py           # LLM 工厂
└── utils/
    ├── state_filter.py          # 状态筛选
    └── output_manager.py        # 输出管理
```

---

## 主图编排

### 状态定义

```python
# src/orchestration/main_graph.py
class VillagePlanningState(TypedDict):
    # 输入
    project_name: str
    village_data: str
    task_description: str
    constraints: str
    
    # 会话管理
    session_id: str
    
    # 流程控制
    current_layer: int             # 当前层级 (1/2/3)
    previous_layer: int            # 刚完成的层级
    layer_1_completed: bool
    layer_2_completed: bool
    layer_3_completed: bool
    
    # 步进模式
    step_mode: bool
    pause_after_step: bool
    pending_review_layer: int      # 待审查层级 (0=无)
    
    # 层级输出
    analysis_report: str
    analysis_dimension_reports: Dict[str, str]
    planning_concept: str
    concept_dimension_reports: Dict[str, str]
    detailed_plan: str
    detailed_dimension_reports: Dict[str, str]
    
    # 输出路径
    output_path: str
    
    # 错误处理
    execution_error: str
    layer_1_failed_dimensions: List[str]
```

### 图结构

```
START
  ↓
[route_initial]
  ├──→ layer1_analysis
  └──→ END (错误)
  ↓
[execute_layer1_analysis]
  ↓
[route_after_layer1]
  ├──→ tool_bridge (步进模式)
  ├──→ layer2_concept (正常流程)
  └──→ END (失败)
  ↓
[tool_bridge_node]
  ↓
[route_after_tool_bridge]
  ├──→ pause (步进模式暂停)
  └──→ layer2_concept
  ↓
[pause_node]
  ↓
[route_after_pause]
  ├──→ END (暂停等待审查)
  └──→ layer1/2/3 (恢复执行)
  ↓
... Layer 2, Layer 3 类似 ...
  ↓
[generate_final_output]
  ↓
END
```

### 图构建代码

```python
def create_village_planning_graph(checkpointer=None):
    builder = StateGraph(VillagePlanningState)
    
    # 添加节点
    builder.add_node("layer1_analysis", execute_layer1_analysis)
    builder.add_node("layer2_concept", execute_layer2_concept)
    builder.add_node("layer3_detail", execute_layer3_detail)
    builder.add_node("tool_bridge", tool_bridge_node)
    builder.add_node("pause", pause_node)
    builder.add_node("final", generate_final_output)
    
    # 条件边
    builder.add_conditional_edges(START, route_initial)
    builder.add_conditional_edges("layer1_analysis", route_after_layer1)
    builder.add_conditional_edges("tool_bridge", route_after_tool_bridge)
    builder.add_conditional_edges("pause", route_after_pause)
    # ... 更多边
    
    return builder.compile(checkpointer=checkpointer)
```

---

## 三层规划系统

### Layer 1: 现状分析

**文件**: `src/subgraphs/analysis_subgraph.py`

**维度** (12 个并行):

| 键名 | 维度 |
|------|------|
| location | 区位与对外交通分析 |
| socio_economic | 社会经济分析 |
| villager_wishes | 村民意愿分析 |
| superior_planning | 上位规划分析 |
| natural_environment | 自然环境与资源分析 |
| land_use | 村庄用地分析 |
| traffic | 道路与交通分析 |
| public_services | 公共服务设施分析 |
| infrastructure | 基础设施分析 |
| ecological_green | 生态绿地分析 |
| architecture | 建筑分析 |
| historical_culture | 历史文化分析 |

**子图结构**:

```
START → initialize → knowledge_preload → [Send] → analyze_dimension (×12) → END
```

**并行执行**:

```python
def map_dimensions(state: AnalysisState) -> List[Send]:
    sends = []
    for dimension_key in state["subjects"]:
        sends.append(Send("analyze_dimension", {
            "dimension_key": dimension_key,
            "raw_data": state["raw_data"],
        }))
    return sends

builder.add_conditional_edges("knowledge_preload", map_dimensions)
```

**输出**:
- `analysis_report`: 综合报告 (用于显示)
- `analysis_dimension_reports`: 各维度独立报告字典

### Layer 2: 规划思路

**文件**: `src/subgraphs/concept_subgraph.py`

**维度** (4 个并行):

| 键名 | 维度 |
|------|------|
| resource_endowment | 资源禀赋分析 |
| planning_positioning | 规划定位分析 |
| development_goals | 发展目标分析 |
| planning_strategies | 规划策略分析 |

**依赖**: 需要Layer 1 的 `analysis_report` 和 `analysis_dimension_reports`

**输出**:
- `planning_concept`: 综合报告
- `concept_dimension_reports`: 各维度独立报告字典

### Layer 3: 详细规划

**文件**: `src/subgraphs/detailed_plan_subgraph.py`

**维度** (12 个并行):

| 键名 | 维度 |
|------|------|
| industry | 产业规划 |
| spatial_structure | 空间结构规划 |
| land_use_planning | 土地利用规划 |
| settlement_planning | 聚落体系规划 |
| traffic | 综合交通规划 |
| public_service | 公共服务设施规划 |
| infrastructure | 基础设施规划 |
| ecological | 生态保护与修复规划 |
| disaster_prevention | 防灾减灾规划 |
| heritage | 历史文化遗产保护 |
| landscape | 村庄风貌引导 |
| project_bank | 建设项目库 |

**分波执行**:
- Wave 1: 前 11 个维度并行
- Wave 2: `project_bank` (依赖 Wave 1 结果)

**依赖**: 需要Layer 1 和 Layer 2 的所有输出

---

## 状态定义

### 子图状态

```python
# analysis_subgraph.py
class AnalysisState(TypedDict):
    raw_data: str
    project_name: str
    subjects: List[str]  # 待分析维度列表
    analyses: Annotated[List[Dict], operator.add]  # 并行结果累加
    analysis_dimension_reports: Annotated[Dict[str, str], merge_dicts]
    knowledge_map: Dict[str, List[dict]]  # RAG 知识映射
    rag_enabled: bool
```

### 状态合并函数

```python
def merge_dicts(left: Dict[str, str], right: Dict[str, str]) -> Dict[str, str]:
    """合并两个字典（用于并行节点结果合并）"""
    result = {**left, **right}
    return result
```

---

## 路由决策

### 初始路由

```python
def route_initial(state: VillagePlanningState) -> Literal["layer1_analysis", "end"]:
    if not state.get("village_data"):
        return "end"
    return "layer1_analysis"
```

### Layer 1 完成后路由

```python
def route_after_layer1(state: VillagePlanningState):
    if not state["layer_1_completed"]:
        return "end"
    
    # 步进模式 → 进入 tool_bridge 准备暂停
    if state.get("step_mode"):
        return "tool_bridge"
    
    # 正常流程 → 直接进入 Layer 2
    return "layer2_concept"
```

### 工具桥接后路由

```python
def route_after_tool_bridge(state: VillagePlanningState):
    # 使用 previous_layer 判断刚完成哪一层
    previous_layer = state.get("previous_layer", 1)
    step_mode = state.get("step_mode", False)
    
    # Layer 1 完成，步进模式 → 暂停
    if previous_layer == 1 and state["layer_1_completed"] and step_mode:
        return "pause"
    
    # Layer 1 完成，非步进模式 → Layer 2
    if previous_layer == 1 and state["layer_1_completed"]:
        return "layer2_concept"
    
    # ... 类似处理 Layer 2, Layer 3
```

### 暂停后路由

```python
def route_after_pause(state: VillagePlanningState):
    step_mode = state.get("step_mode", False)
    pending_review_layer = state.get("pending_review_layer", 0)
    
    # 有待审查层级 → 终止执行等待审查
    if step_mode and pending_review_layer > 0:
        return "end"
    
    # 否则继续执行当前层级
    current_layer = state.get("current_layer", 1)
    if current_layer == 1:
        return "layer1_analysis"
    elif current_layer == 2:
        return "layer2_concept"
    else:
        return "layer3_detail"
```

---

## 暂停恢复机制

### 暂停触发

1. **设置状态**: 层级完成时设置 `pause_after_step=True` 和 `pending_review_layer=N`

```python
# execute_layer1_analysis() 返回
return {
    "analysis_report": combined_report,
    "analysis_dimension_reports": dimension_reports,
    "layer_1_completed": True,
    "current_layer": 2,
    "previous_layer": 1,          # 刚完成的层级
    "pending_review_layer": 1,    # 待审查层级
    "pause_after_step": True,     # 触发暂停
}
```

2. **路由决策**: `route_after_tool_bridge` 返回 `"pause"`

3. **暂停节点**: 设置最终暂停状态

```python
def pause_node(state: VillagePlanningState):
    return {
        "pause_after_step": True,
        "messages": [AIMessage(content="Layer X 已完成，暂停中")]
    }
```

4. **最终路由**: `route_after_pause` 返回 `"end"`

### 恢复执行

后端收到批准请求后：

```python
# backend/api/planning.py
async def handle_review(session_id: str, action: str):
    state = _sessions[session_id]["initial_state"]
    
    if action == "approve":
        # 清除暂停标志
        state["pause_after_step"] = False
        state["pending_review_layer"] = 0
        
        # 清空已发送暂停事件
        _sessions[session_id]["sent_pause_events"].clear()
        
        # 恢复执行
        await _resume_graph_execution(session_id, state)
```

---

## 层级执行节点

### Layer 1 执行

```python
def execute_layer1_analysis(state: VillagePlanningState) -> Dict[str, Any]:
    # 调用现状分析子图
    result = call_analysis_subgraph(
        raw_data=state["village_data"],
        project_name=state["project_name"]
    )
    
    if result["success"]:
        # 生成综合报告
        combined_report = _generate_simple_combined_report(
            state["project_name"],
            result["analysis_dimension_reports"],
            "现状分析",
            layer_number=1
        )
        
        return {
            "analysis_report": combined_report,
            "analysis_dimension_reports": result["analysis_dimension_reports"],
            "layer_1_completed": True,
            "current_layer": 2,
            "previous_layer": 1,
            "pending_review_layer": 1,
        }
    
    return {
        "analysis_report": "分析失败",
        "layer_1_completed": False,
    }
```

### 错误处理

```python
def execute_layer1_analysis(state: VillagePlanningState):
    try:
        result = call_analysis_subgraph(...)
        
        # 检测致命错误（连接失败）
        if "Connection error" in result.get("error", ""):
            return {
                "execution_error": "LLM服务连接失败",
                "quit_requested": True,  # 终止整个流程
            }
        
        # 检查失败维度数量
        failed_dims = result.get("failed_dimensions", [])
        if len(failed_dims) > 6:  # 超过一半失败
            return {
                "execution_error": f"{len(failed_dims)}个维度失败",
                "quit_requested": True,
            }
        
        # 部分失败，继续执行
        ...
    except Exception as e:
        return {"execution_error": str(e)}
```

---

## 状态持久化

### Checkpointer 集成

```python
# 创建图时传入 checkpointer
graph = create_village_planning_graph(checkpointer=checkpointer)

# 执行时使用 thread_id
config = {"configurable": {"thread_id": session_id}}
async for event in graph.astream(initial_state, config):
    # 状态自动保存到 checkpoints 表
```

### 状态读取

```python
# 获取当前状态
checkpoint_state = await graph.aget_state(config)
state_values = checkpoint_state.values

# 获取历史状态
history = [s async for s in graph.aget_state_history(config)]
```

### 状态更新

```python
# 从特定检查点恢复
await graph.aupdate_state(config, new_values, checkpoint_id)
```
