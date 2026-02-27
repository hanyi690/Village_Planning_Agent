# 智能体架构文档

> LangGraph 核心引擎 - 三层递进式规划系统

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                   src/agent.py (接口层)                      │
│  run_village_planning() / run_analysis_only()               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│            orchestration/main_graph.py (主图编排)            │
│  VillagePlanningState → StateGraph → 层级调度               │
└─────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Layer 1    │    │   Layer 2    │    │   Layer 3    │
│ 现状分析子图  │───▶│ 规划思路子图  │───▶│ 详细规划子图  │
│ (12维度并行) │    │ (4维度串行)   │    │ (12维度)     │
└──────────────┘    └──────────────┘    └──────────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     planners/ (规划器层)                     │
│  UnifiedPlannerBase → GenericPlanner                        │
│  Python Code-First，支持 28 个维度                           │
└─────────────────────────────────────────────────────────────┘
```

## 主图编排

### 状态定义

```python
class VillagePlanningState(TypedDict):
    # 输入
    project_name: str
    village_data: str
    task_description: str
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
    
    # 输出
    analysis_reports: Dict[str, str]   # Layer 1
    concept_reports: Dict[str, str]    # Layer 2
    detail_reports: Dict[str, str]     # Layer 3
    final_output: str
```

### 图结构

```
START
  │
  ▼
┌─────────────────┐
│ layer1_analysis │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│  tool_bridge    │────▶│  layer2_concept │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│     pause       │     │  layer3_detail  │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
        END              ┌─────────────────┐
                         │ generate_final  │
                         └────────┬────────┘
                                  │
                                  ▼
                                 END
```

### 图构建

```python
def create_village_planning_graph(checkpointer=None):
    builder = StateGraph(VillagePlanningState)
    
    # 节点
    builder.add_node("layer1_analysis", execute_layer1_analysis)
    builder.add_node("layer2_concept", execute_layer2_concept)
    builder.add_node("layer3_detail", execute_layer3_detail)
    builder.add_node("tool_bridge", tool_bridge_node)
    builder.add_node("pause", pause_node)
    
    # 条件边
    builder.add_conditional_edges(START, route_initial)
    builder.add_conditional_edges("layer1_analysis", route_after_layer1)
    builder.add_conditional_edges("tool_bridge", route_after_tool_bridge)
    
    return builder.compile(checkpointer=checkpointer)
```

## 三层子图

### Layer 1: 现状分析 (12维度并行)

**文件**: `subgraphs/analysis_subgraph.py`

**维度**: 
- location (区位分析)
- socio_economic (社会经济)
- natural_environment (自然环境)
- land_use (土地利用)
- traffic (道路交通)
- public_services (公共服务)
- infrastructure (基础设施)
- ecological_green (生态绿地)
- architecture (建筑)
- historical_culture (历史文化)
- villager_wishes (村民意愿)
- superior_planning (上位规划)

**执行模式**: Map-Reduce 并行 (Send 机制)

```python
def map_dimensions(state: AnalysisState) -> List[Send]:
    return [
        Send("analyze_dimension", {"dimension_key": key, "raw_data": state["raw_data"]})
        for key in state["subjects"]
    ]

builder.add_conditional_edges("initialize", map_dimensions)
```

### Layer 2: 规划思路 (4维度串行)

**文件**: `subgraphs/concept_subgraph.py`

**维度**:
- resource_endowment (资源禀赋)
- planning_positioning (规划定位)
- development_goals (发展目标)
- planning_strategies (规划策略)

**执行模式**: 4波次串行 (依赖驱动)

| 维度 | 依赖 |
|------|------|
| resource_endowment | 无 (Wave 1) |
| planning_positioning | resource_endowment (Wave 2) |
| development_goals | 前2个 (Wave 3) |
| planning_strategies | 前3个 (Wave 4) |

### Layer 3: 详细规划 (12维度)

**文件**: `subgraphs/detailed_plan_subgraph.py`

**维度**:
- industry (产业规划)
- spatial_structure (空间结构)
- land_use_planning (土地利用)
- settlement_planning (居民点)
- traffic_planning (道路交通)
- public_service (公共服务)
- infrastructure_planning (基础设施)
- ecological (生态绿地)
- disaster_prevention (防灾减灾)
- heritage (历史文保)
- landscape (村庄风貌)
- project_bank (项目库)

**执行模式**: 2波次 (前11个并行，project_bank 依赖前11个)

## 路由决策

### Layer 1 完成后

```python
def route_after_layer1(state):
    if not state["layer_1_completed"]:
        return "end"
    if state.get("step_mode"):
        return "tool_bridge"  # 准备暂停
    return "layer2_concept"
```

### 工具桥接后

```python
def route_after_tool_bridge(state):
    previous = state.get("previous_layer", 1)
    if state["layer_1_completed"] and state["step_mode"] and previous == 1:
        return "pause"
    if state["layer_1_completed"] and previous == 1:
        return "layer2_concept"
    # 类似处理 Layer 2, 3
```

### 暂停后

```python
def route_after_pause(state):
    if state["step_mode"] and state["pending_review_layer"] > 0:
        return "end"  # 等待审查
    current = state.get("current_layer", 1)
    return f"layer{current}_..."  # 继续执行
```

## 规划器层

### UnifiedPlannerBase

**文件**: `planners/unified_base_planner.py`

```python
class UnifiedPlannerBase(ABC):
    @abstractmethod
    def validate_state(self, state) -> tuple[bool, str]: ...
    @abstractmethod
    def build_prompt(self, state) -> str: ...
    @abstractmethod
    def get_layer(self) -> int: ...
    
    def execute(self, state, model, temperature) -> Dict[str, Any]: ...
```

### GenericPlanner

**文件**: `planners/generic_planner.py`

```python
class GenericPlanner(UnifiedPlannerBase):
    """Python Code-First，支持所有 28 维度"""
    
    def __init__(self, dimension_key: str):
        config = get_dimension_config(dimension_key)
        ...
    
    def build_prompt(self, state) -> str:
        # Layer 1: 替换 {raw_data}
        # Layer 2: 替换 {filtered_analysis}, {task_description}
        # Layer 3: 使用函数式 prompt
```

## 数据流

```
run_village_planning()
      │
      ▼
create_village_planning_graph()
      │
      ▼
┌──────────────────────────────────────────┐
│           Main Graph 执行                 │
│                                          │
│  START → layer1_analysis                 │
│           │                              │
│           ├─▶ analysis_subgraph          │
│           │     ├─▶ Send (并行)          │
│           │     │     └─▶ GenericPlanner │
│           │     │           └─▶ LLM      │
│           │     └─▶ reduce               │
│           │                              │
│           ▼                              │
│  route_after_layer1()                    │
│           │                              │
│           ▼                              │
│  layer2_concept (类似)                    │
│           │                              │
│           ▼                              │
│  layer3_detail (类似)                     │
│           │                              │
│           ▼                              │
│  generate_final_output()                 │
│           │                              │
│           ▼                              │
│  END                                     │
└──────────────────────────────────────────┘
```

## 维度配置

**文件**: `config/dimension_metadata.py`

```python
DIMENSION_CONFIG = {
    # Layer 1 维度
    "location": {
        "name": "区位分析",
        "layer": 1,
        "dependencies": [],
    },
    # ... 其他维度
    
    # Layer 2 维度
    "resource_endowment": {
        "name": "资源禀赋",
        "layer": 2,
        "dependencies": ["location", "socio_economic", ...],
    },
    # ...
    
    # Layer 3 维度
    "industry": {
        "name": "产业规划",
        "layer": 3,
        "dependencies": ["resource_endowment", "planning_positioning", ...],
    },
    # ...
}
```

## LLM 配置

**文件**: `core/config.py`

```python
LLM_MODEL = "glm-4-flash"
LLM_PROVIDER = "zhipuai"
MAX_TOKENS = 1500
```

## 设计模式

1. **LangGraph 状态机**: StateGraph + TypedDict + 条件边
2. **Map-Reduce 并行**: Send 机制 + operator.add
3. **工厂模式**: GenericPlannerFactory
4. **模板方法**: UnifiedPlannerBase 定义流程，子类实现细节

## 关键文件索引

| 文件 | 功能 |
|------|------|
| `src/agent.py` | 对外接口 |
| `src/orchestration/main_graph.py` | 主图编排 |
| `src/subgraphs/analysis_subgraph.py` | Layer 1 子图 |
| `src/subgraphs/concept_subgraph.py` | Layer 2 子图 |
| `src/subgraphs/detailed_plan_subgraph.py` | Layer 3 子图 |
| `src/nodes/layer_nodes.py` | Layer 节点封装 |
| `src/planners/unified_base_planner.py` | 规划器基类 |
| `src/planners/generic_planner.py` | 通用规划器 |
| `src/config/dimension_metadata.py` | 维度配置 |
| `src/core/config.py` | 核心配置 |
| `src/core/llm_factory.py` | LLM 工厂 |