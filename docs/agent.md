# 智能体架构文档

> LangGraph 核心引擎 - 三层递进式规划系统 + RAG 知识检索

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                   src/agent.py (接口层)                             │
│  run_village_planning() / run_analysis_only()                       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│            orchestration/main_graph.py (主图编排)                    │
│  VillagePlanningState → StateGraph → 层级调度                       │
│  START → init_pause → Layer1 → Layer2 → Layer3 → final → END        │
└─────────────────────────────────────────────────────────────────────┘
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
┌─────────────────────────────────────────────────────────────────────┐
│                     planners/ (规划器层)                             │
│  GenericPlanner - 28个维度统一规划器                                 │
│  工具钩子: population_model, gis_coverage, network_accessibility    │
└─────────────────────────────────────────────────────────────────────┘
```

## 执行流程

```
START
  │
  ▼
init_pause (初始化暂停状态)
  │
  ▼ (route_after_pause)
  │
Layer 1: 现状分析 (12维度并行)
  │ initialize → knowledge_preload → [analyze_dimension ×12] → reduce
  │ 输出: analysis_reports
  │
  ▼ (route_after_layer1)
  │
tool_bridge (可选: step_mode暂停)
  │
  ▼
Layer 2: 规划思路 (4维度波次)
  │ Wave 1: resource_endowment (无依赖)
  │ Wave 2: planning_positioning (依赖 Wave 1)
  │ Wave 3: development_goals (依赖 Wave 1,2)
  │ Wave 4: planning_strategies (依赖 Wave 1,2,3)
  │ 输出: concept_reports
  │
  ▼ (route_after_layer2)
  │
tool_bridge (可选)
  │
  ▼
Layer 3: 详细规划 (12维度波次)
  │ Wave 1: 11维度并行
  │ Wave 2: project_bank (依赖 Wave 1 全部完成)
  │ 输出: detail_reports
  │
  ▼ (route_after_layer3)
  │
generate_final_output
  │
  ▼
END
```

## 状态定义

```python
class VillagePlanningState(TypedDict):
    # 输入数据
    project_name: str              # 项目名称
    village_data: str              # 村庄基础数据
    task_description: str          # 规划任务描述
    constraints: str               # 约束条件

    # 流程控制
    current_layer: int             # 当前层级 (1/2/3)
    layer_1_completed: bool
    layer_2_completed: bool
    layer_3_completed: bool

    # 人工审核
    need_human_review: bool
    human_feedback: str
    need_revision: bool
    revision_target_dimensions: List[str]

    # 各层成果
    analysis_reports: Dict[str, str]  # Layer 1
    concept_reports: Dict[str, str]   # Layer 2
    detail_reports: Dict[str, str]    # Layer 3
    final_output: str

    # RAG 知识缓存
    knowledge_cache: Dict[str, str]

    # 步进模式
    step_mode: bool
    pause_after_step: bool
    previous_layer: int

    # 修订历史
    revision_history: List[Dict[str, Any]]
    last_revised_dimensions: List[str]

    # 黑板模式数据共享
    blackboard: Dict[str, Any]
```

## 主图编排

```python
def create_village_planning_graph(checkpointer=None):
    builder = StateGraph(VillagePlanningState)
    
    # 节点
    builder.add_node("init_pause", init_pause_state)
    builder.add_node("layer1_analysis", Layer1AnalysisNode())
    builder.add_node("layer2_concept", Layer2ConceptNode())
    builder.add_node("layer3_detail", Layer3DetailNode())
    builder.add_node("tool_bridge", ToolBridgeNode())
    builder.add_node("generate_final", generate_final_output)
    
    # 边
    builder.add_edge(START, "init_pause")
    
    # 条件边
    builder.add_conditional_edges("init_pause", route_after_pause)
    builder.add_conditional_edges("layer1_analysis", route_after_layer1)
    builder.add_conditional_edges("layer2_concept", route_after_layer2)
    builder.add_conditional_edges("layer3_detail", route_after_layer3)
    
    return builder.compile(checkpointer=checkpointer)
```

## 子图实现

### Layer 1: 现状分析子图

**执行模式**: Map-Reduce 并行

```
initialize → knowledge_preload_node → [analyze_dimension ×12] → reduce
```

**维度列表**: location, socio_economic, villager_wishes, superior_planning, natural_environment, land_use, traffic, public_services, infrastructure, ecological_green, architecture, historical_culture

### Layer 2: 规划思路子图

**执行模式**: 波次路由 (依赖驱动)

```
Wave 1: resource_endowment
Wave 2: planning_positioning
Wave 3: development_goals
Wave 4: planning_strategies
```

### Layer 3: 详细规划子图

**执行模式**: 波次路由

```
Wave 1: 11维度并行 (industry, spatial_structure, ...)
Wave 2: project_bank (依赖 Wave 1 全部完成)
```

### Revision 子图

**功能**: 处理人工驳回后的并行修复机制

**级联更新**: 修复一个维度时，自动更新所有下游依赖维度

## 规划器层

### GenericPlanner (通用规划器)

```python
class GenericPlanner(UnifiedPlannerBase):
    """支持所有 28 维度的统一规划器"""
    
    def __init__(self, dimension_key: str):
        self.config = get_dimension_config(dimension_key)
        self.dimension_key = dimension_key
    
    def build_prompt(self, state) -> str:
        # 从 knowledge_cache 获取知识上下文
        knowledge = state.get("knowledge_cache", {}).get(self.dimension_key, "")
        # 获取依赖的上层报告
        dependencies = self.config.get("dependencies", {})
        # 构建提示词
        ...
    
    def _execute_tool_hook(self, state) -> str:
        # 执行工具调用
        tool_name = self.config.get("tool")
        if tool_name:
            return ToolRegistry.execute_tool(tool_name, context)
        return ""
```

## 维度配置

### 维度数量

| 层级 | 数量 | 执行模式 |
|------|------|---------|
| Layer 1 | 12 | 并行 |
| Layer 2 | 4 | 波次 (Wave 1→4) |
| Layer 3 | 12 | 波次 (Wave 1→2) |

### RAG 启用的维度

**Layer 1**: 全部12个维度启用

**Layer 3 关键维度**: land_use_planning, infrastructure_planning, ecological, disaster_prevention, heritage

### 依赖配置示例

```python
# Layer 2 依赖 Layer 1
"planning_positioning": {
    "dependencies": {
        "layer1_analyses": ["location", "socio_economic", "superior_planning"],
        "layer2_concepts": ["resource_endowment"]
    }
}

# Layer 3 依赖 Layer 1, 2 和同层维度
"project_bank": {
    "dependencies": {
        "layer3_plans": ["industry", "spatial_structure", ...]  # 所有其他维度
    }
}
```

## 工具系统

### 工具注册

```python
# src/tools/registry.py
@ToolRegistry.register("population_model_v1")
def calculate_population(context: Dict[str, Any]) -> str:
    # 人口预测模型
    ...

# 调用
ToolRegistry.execute_tool("population_model_v1", context)
```

### 内置工具

| 工具 | 功能 |
|------|------|
| `population_model_v1` | 人口预测模型 |
| `gis_coverage_calculator` | GIS 覆盖率计算 |
| `network_accessibility` | 网络可达性分析 |
| `knowledge_search` | RAG 知识检索 |

### 维度工具映射

```python
# dimension_metadata.py
"socio_economic": {"tool": "population_model_v1"}
"land_use": {"tool": "gis_coverage_calculator"}
"traffic": {"tool": "network_accessibility"}
```

## RAG 知识检索

### 集成方式

```
子图执行:
┌─────────┐    ┌──────────────────┐    ┌─────────────┐
│initialize│───▶│knowledge_preload │───▶│ 分析节点    │
└─────────┘    │    _node         │    └─────────────┘
               └──────────────────┘           │
                      │                       ▼
                      ▼              从 knowledge_cache
               预加载关键维度知识            读取知识
```

### 模块结构

```
src/rag/
├── config.py                 # 配置
├── build.py                  # 知识库构建入口
├── core/
│   ├── tools.py              # knowledge_search_tool
│   ├── cache.py              # Embedding 模型缓存
│   └── loaders.py            # 文档加载器
└── scripts/
    └── build_kb_auto.py      # 构建脚本
```

## 节点基类

### BaseNode (同步节点基类)

```python
class BaseNode(ABC):
    """同步节点基类"""
    
    @abstractmethod
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行节点逻辑（子类必须实现）"""
        pass
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """同步调用接口，用于LangGraph"""
        ...
```

### AsyncBaseNode (异步节点基类)

```python
class AsyncBaseNode(BaseNode):
    """异步节点基类
    
    用于需要异步执行的节点（如调用异步子图）。
    LangGraph 会自动检测并正确处理异步节点。
    """
    
    @abstractmethod
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """异步执行节点逻辑（子类必须实现）"""
        pass
    
    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """异步调用接口，用于LangGraph"""
        ...
```

**异步节点应用**:
- `BaseLayerNode` - Layer 层节点（调用异步子图）
- `ReduceDimensionReportsNode` - 汇总报告节点
- `RevisionNode` - 修复工具节点

**子图调用异步化**: 所有 `call_*_subgraph` 函数均为异步函数，使用 `await subgraph.ainvoke()` 调用。

## 目录结构

```
src/
├── agent.py                    # 对外接口
├── core/
│   ├── config.py               # 全局配置
│   ├── llm_factory.py          # LLM工厂
│   ├── state_builder.py        # 状态构建器
│   └── streaming.py            # 流式输出
├── config/
│   └── dimension_metadata.py   # 维度元数据
├── orchestration/
│   └── main_graph.py           # 主图编排
├── subgraphs/
│   ├── analysis_subgraph.py    # Layer 1 子图
│   ├── concept_subgraph.py     # Layer 2 子图
│   ├── detailed_plan_subgraph.py # Layer 3 子图
│   └── revision_subgraph.py    # Revision 子图
├── nodes/
│   ├── base_node.py            # 节点基类 (BaseNode, AsyncBaseNode)
│   ├── layer_nodes.py          # Layer 节点 (异步)
│   ├── subgraph_nodes.py       # 子图节点
│   └── tool_nodes.py           # 工具节点 (含异步 RevisionNode)
├── planners/
│   ├── unified_base_planner.py # 规划器基类
│   └── generic_planner.py      # 通用规划器
├── tools/
│   ├── registry.py             # 工具注册表
│   └── adapters/               # 适配器
└── rag/
    └── core/tools.py           # RAG 检索工具
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `src/agent.py` | 对外接口 |
| `src/orchestration/main_graph.py` | 主图编排 |
| `src/subgraphs/analysis_subgraph.py` | Layer 1 子图 |
| `src/subgraphs/concept_subgraph.py` | Layer 2 子图 |
| `src/subgraphs/detailed_plan_subgraph.py` | Layer 3 子图 |
| `src/planners/generic_planner.py` | 通用规划器 |
| `src/config/dimension_metadata.py` | 维度配置 |
| `src/tools/registry.py` | 工具注册表 |
| `src/rag/core/tools.py` | RAG 检索工具 |