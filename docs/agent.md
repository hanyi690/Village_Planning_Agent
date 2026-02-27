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
│ (12维度并行) │    │ (4维度波次)   │    │ (12维度波次) │
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

## 执行流程

```
START
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ init_pause (初始化暂停状态)                                  │
│ - 检查 step_mode 和 previous_layer                           │
│ - 如果 need_revision=True，清除暂停标志                      │
└─────────────────────────────────────────────────────────────┘
  │
  ▼ (route_after_pause)
  │
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: 现状分析 (12个维度完全并行)                          │
│                                                             │
│ [initialize] -> [analyze_dimension x 12] -> [reduce]        │
│                                                             │
│ 维度: location, socio_economic, natural_environment,        │
│       land_use, traffic, public_services, infrastructure,   │
│       ecological_green, architecture, historical_culture,   │
│       villager_wishes, superior_planning                    │
│                                                             │
│ 输出: analysis_reports: Dict[str, str]                       │
└─────────────────────────────────────────────────────────────┘
  │
  ▼ (route_after_layer1)
  │
┌─────────────────────────────────────────────────────────────┐
│ tool_bridge (可选)                                           │
│ - step_mode 暂停                                             │
│ - need_human_review 人工审核                                 │
│ - need_revision 修复                                         │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: 规划思路 (4个维度，波次路由)                          │
│                                                             │
│ Wave 1: resource_endowment (无同层依赖)                      │
│ Wave 2: planning_positioning (依赖 resource_endowment)      │
│ Wave 3: development_goals (依赖前两个)                       │
│ Wave 4: planning_strategies (依赖前三个)                     │
│                                                             │
│ 输出: concept_reports: Dict[str, str]                        │
└─────────────────────────────────────────────────────────────┘
  │
  ▼ (route_after_layer2)
  │
┌─────────────────────────────────────────────────────────────┐
│ tool_bridge (可选)                                           │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: 详细规划 (12个维度，波次路由)                         │
│                                                             │
│ Wave 1: 9个维度并行执行                                      │
│   industry, master_plan, traffic, public_service,           │
│   infrastructure, ecological, disaster_prevention,          │
│   heritage, landscape                                       │
│                                                             │
│ Wave 2: project_bank (依赖Wave 1全部完成)                    │
│                                                             │
│ 输出: detail_reports: Dict[str, str]                         │
└─────────────────────────────────────────────────────────────┘
  │
  ▼ (route_after_layer3)
  │
┌─────────────────────────────────────────────────────────────┐
│ tool_bridge (可选)                                           │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ generate_final_output                                       │
│ - 整合三层报告                                               │
│ - 生成最终规划文档                                           │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
END
```

## 状态定义

```python
class VillagePlanningState(TypedDict):
    # 输入数据
    project_name: str              # 项目/村庄名称
    village_data: str              # 村庄基础数据
    task_description: str          # 规划任务描述
    constraints: str               # 约束条件

    # 流程控制
    current_layer: int             # 当前执行层级 (1/2/3)
    layer_1_completed: bool        # 现状分析完成
    layer_2_completed: bool        # 规划思路完成
    layer_3_completed: bool        # 详细规划完成

    # 人工审核
    need_human_review: bool        # 是否需要人工审核
    human_feedback: str            # 人工反馈
    need_revision: bool            # 是否需要修复
    revision_target_dimensions: List[str]  # 修复维度列表

    # 各层成果
    analysis_reports: Dict[str, str]  # Layer 1: 现状分析报告
    concept_reports: Dict[str, str]   # Layer 2: 规划思路报告
    detail_reports: Dict[str, str]    # Layer 3: 详细规划报告
    final_output: str              # 最终成果

    # 逐步执行模式
    step_mode: bool                # 是否启用逐步执行模式
    pause_after_step: bool         # 是否在当前步骤后暂停
    previous_layer: int            # 刚完成的层级编号

    # 路由控制
    quit_requested: bool           # 用户请求退出
    trigger_rollback: bool         # 触发回退
    rollback_target: str           # 回退目标checkpoint ID

    # 数据共享
    blackboard: Dict[str, Any]

    # 修订历史
    revision_history: List[Dict[str, Any]]
    last_revised_dimensions: List[str]
```

## 主图编排

### 图结构

```python
def create_village_planning_graph(checkpointer=None):
    builder = StateGraph(VillagePlanningState)
    
    # 节点
    builder.add_node("init_pause", init_pause_node)
    builder.add_node("layer1_analysis", Layer1AnalysisNode())
    builder.add_node("layer2_concept", Layer2ConceptNode())
    builder.add_node("layer3_detail", Layer3DetailNode())
    builder.add_node("tool_bridge", ToolBridgeNode())
    builder.add_node("generate_final", generate_final_output)
    
    # 条件边
    builder.add_conditional_edges(START, route_initial)
    builder.add_conditional_edges("layer1_analysis", route_after_layer1)
    builder.add_conditional_edges("layer2_concept", route_after_layer2)
    builder.add_conditional_edges("layer3_detail", route_after_layer3)
    builder.add_conditional_edges("tool_bridge", route_after_tool_bridge)
    
    return builder.compile(checkpointer=checkpointer)
```

### 路由决策

```python
def route_after_layer1(state):
    if not state["layer_1_completed"]:
        return "end"
    if state.get("step_mode"):
        return "tool_bridge"  # 准备暂停
    return "layer2_concept"

def route_after_tool_bridge(state):
    previous = state.get("previous_layer", 1)
    if state["step_mode"] and previous == 1:
        return "pause"  # 等待审查
    if previous == 1:
        return "layer2_concept"
    if previous == 2:
        return "layer3_detail"
    return "generate_final"
```

## 子图实现

### Layer 1: 现状分析子图

**文件**: `subgraphs/analysis_subgraph.py`

**执行模式**: Map-Reduce 并行 (Send 机制)

```python
def map_dimensions(state: AnalysisState) -> List[Send]:
    return [
        Send("analyze_dimension", {"dimension_key": key})
        for key in state["subjects"]
    ]

builder.add_conditional_edges("initialize", map_dimensions)
builder.add_node("analyze_dimension", AnalyzeDimensionNode())
builder.add_node("reduce", ReduceAnalysesNode())
```

### Layer 2: 规划思路子图

**文件**: `subgraphs/concept_subgraph.py`

**执行模式**: 波次路由 (依赖驱动)

```python
def route_by_dependency_wave(state):
    completed = state.get("completed_dimensions", set())
    for wave in wave_order:
        ready = [d for d in wave if d not in completed]
        if ready:
            return Send("analyze_dimension", {"dimension_key": ready[0]})
    return "reduce"
```

### Layer 3: 详细规划子图

**文件**: `subgraphs/detailed_plan_subgraph.py`

**执行模式**: 波次路由

```python
WAVE_1 = ["industry", "master_plan", "traffic", "public_service", 
          "infrastructure", "ecological", "disaster_prevention", 
          "heritage", "landscape"]
WAVE_2 = ["project_bank"]  # 依赖 Wave 1 全部完成
```

## 规划器层

### UnifiedPlannerBase (基类)

**文件**: `planners/unified_base_planner.py`

```python
class UnifiedPlannerBase(ABC):
    @abstractmethod
    def validate_state(self, state) -> tuple[bool, str]: ...
    @abstractmethod
    def build_prompt(self, state) -> str: ...
    @abstractmethod
    def get_layer(self) -> int: ...
    
    def execute(self, state, model, temperature) -> Dict[str, Any]:
        # 标准执行流程
        prompt = self.build_prompt(state)
        response = self._call_llm(prompt, model, temperature)
        return self._parse_response(response)
```

### GenericPlanner (通用规划器)

**文件**: `planners/generic_planner.py`

```python
class GenericPlanner(UnifiedPlannerBase):
    """支持所有 28 维度的统一规划器"""
    
    def __init__(self, dimension_key: str):
        self.config = get_dimension_config(dimension_key)
        self.dimension_key = dimension_key
    
    def build_prompt(self, state) -> str:
        layer = self.get_layer()
        if layer == 1:
            return self._build_layer1_prompt(state)
        elif layer == 2:
            return self._build_layer2_prompt(state)
        else:
            return self._build_layer3_prompt(state)
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
    "socio_economic": {
        "name": "社会经济",
        "layer": 1,
        "dependencies": [],
    },
    # ... 其他 Layer 1 维度
    
    # Layer 2 维度
    "resource_endowment": {
        "name": "资源禀赋",
        "layer": 2,
        "dependencies": ["natural_environment", "land_use", "socio_economic"],
    },
    "planning_positioning": {
        "name": "规划定位",
        "layer": 2,
        "dependencies": ["location", "socio_economic", "resource_endowment"],
    },
    # ... 其他 Layer 2 维度
    
    # Layer 3 维度
    "industry": {
        "name": "产业规划",
        "layer": 3,
        "dependencies": ["socio_economic", "resource_endowment", "planning_positioning"],
    },
    # ... 其他 Layer 3 维度
}
```

## 节点继承体系

```
BaseNode (基类)
├── BaseLayerNode (Layer节点基类)
│   ├── Layer1AnalysisNode (现状分析节点)
│   ├── Layer2ConceptNode (规划思路节点)
│   └── Layer3DetailNode (详细规划节点)
│
├── ToolBridgeNode (工具桥接节点)
│   └── RevisionNode (修复节点)
│
└── SubgraphNodes (子图节点)
    ├── InitializeAnalysisNode
    ├── AnalyzeDimensionNode
    ├── ReduceAnalysesNode
    ├── InitializeConceptNode
    └── ...
```

## 节点调用链

```
1. Layer 1 执行流程:
   main_graph.Layer1AnalysisNode
       -> analysis_subgraph.InitializeAnalysisNode
       -> [analysis_subgraph.AnalyzeDimensionNode x 12] (并行)
       -> analysis_subgraph.ReduceAnalysesNode
       -> GenericPlanner.execute()

2. Layer 2 执行流程:
   main_graph.Layer2ConceptNode
       -> concept_subgraph.InitializeConceptNode
       -> [route_by_dependency_wave] (波次路由)
       -> concept_subgraph.AnalyzeConceptDimensionNode
       -> concept_subgraph.ReduceConceptsNode
       -> GenericPlanner.execute()

3. Layer 3 执行流程:
   main_graph.Layer3DetailNode
       -> detailed_plan_subgraph.InitializeDetailedPlanningNode
       -> [route_by_dependency_wave] (波次路由)
       -> detailed_plan_subgraph.GenerateDimensionPlanNode
       -> detailed_plan_subgraph.ReduceDimensionReportsNode
       -> GenericPlanner.execute()

4. 修复执行流程:
   main_graph.ToolBridgeNode
       -> RevisionNode.execute()
       -> revision_subgraph (并行修复多个维度)
       -> GenericPlanner.execute_with_feedback()
```

## LLM 配置

**文件**: `core/llm_factory.py`

```python
def create_llm(model_name: str = None, temperature: float = 0.7):
    """统一LLM创建入口"""
    provider = detect_provider(model_name or LLM_MODEL)
    
    if provider == "zhipuai":
        return ChatZhipuAI(model=model_name, temperature=temperature)
    elif provider == "openai":
        return ChatOpenAI(model=model_name, temperature=temperature)
```

**支持提供商**: OpenAI, 智谱AI (GLM)

## 工具集

| 工具 | 文件 | 功能 |
|------|------|------|
| VillageDataManager | tools/file_manager.py | 文件加载/解析 |
| KnowledgeTool | tools/knowledge_tool.py | RAG知识检索 |
| RevisionTool | tools/revision_tool.py | 规划修复 |
| ToolRegistry | tools/registry.py | 工具注册中心 |

## 关键文件索引

| 文件 | 功能 |
|------|------|
| `src/agent.py` | 对外接口 |
| `src/orchestration/main_graph.py` | 主图编排 |
| `src/subgraphs/analysis_subgraph.py` | Layer 1 子图 |
| `src/subgraphs/concept_subgraph.py` | Layer 2 子图 |
| `src/subgraphs/detailed_plan_subgraph.py` | Layer 3 子图 |
| `src/subgraphs/revision_subgraph.py` | 修复子图 |
| `src/nodes/layer_nodes.py` | Layer 节点封装 |
| `src/nodes/tool_nodes.py` | 工具节点 |
| `src/nodes/subgraph_nodes.py` | 子图节点 |
| `src/planners/unified_base_planner.py` | 规划器基类 |
| `src/planners/generic_planner.py` | 通用规划器 |
| `src/config/dimension_metadata.py` | 维度配置 |
| `src/core/llm_factory.py` | LLM 工厂 |
| `src/core/state_builder.py` | 状态构建器 |
| `src/core/config.py` | 核心配置 |
