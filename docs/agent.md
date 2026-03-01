# 智能体架构文档

> LangGraph 核心引擎 - 三层递进式规划系统 + RAG 知识检索

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
│  knowledge_cache: RAG 知识预加载缓存                         │
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
init_pause (初始化暂停状态)
  │
  ▼ (route_after_pause)
  │
Layer 1: 现状分析 (12维度并行)
  │ initialize → knowledge_preload → [analyze_dimension x12] → reduce
  │ 输出: analysis_reports
  │
  ▼ (route_after_layer1)
  │
tool_bridge (可选: step_mode暂停)
  │
  ▼
Layer 2: 规划思路 (4维度波次)
  │ Wave 1: resource_endowment
  │ Wave 2: planning_positioning
  │ Wave 3: development_goals
  │ Wave 4: planning_strategies
  │ 输出: concept_reports
  │
  ▼ (route_after_layer2)
  │
tool_bridge (可选)
  │
  ▼
Layer 3: 详细规划 (12维度波次)
  │ Wave 1: 9维度并行
  │ Wave 2: project_bank
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

**文件**: `src/orchestration/main_graph.py`

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
```

## 主图编排

**文件**: `src/orchestration/main_graph.py`

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
    
    return builder.compile(checkpointer=checkpointer)
```

## 子图实现

### Layer 1: 现状分析子图

**文件**: `src/subgraphs/analysis_subgraph.py`

**执行模式**: Map-Reduce 并行

```
initialize → knowledge_preload_node → [analyze_dimension x12] → reduce
```

```python
def map_dimensions(state) -> List[Send]:
    return [Send("analyze_dimension", {"dimension_key": key})
            for key in state["subjects"]]
```

### Layer 2: 规划思路子图

**文件**: `src/subgraphs/concept_subgraph.py`

**执行模式**: 波次路由 (依赖驱动)

```
Wave 1: resource_endowment (无依赖)
Wave 2: planning_positioning (依赖 Wave 1)
Wave 3: development_goals (依赖 Wave 1,2)
Wave 4: planning_strategies (依赖 Wave 1,2,3)
```

### Layer 3: 详细规划子图

**文件**: `src/subgraphs/detailed_plan_subgraph.py`

**执行模式**: 波次路由

```
Wave 1: 9维度并行 (industry, master_plan, traffic, ...)
Wave 2: project_bank (依赖 Wave 1 全部完成)
```

### Revision 子图

**文件**: `src/subgraphs/revision_subgraph.py`

**功能**: 处理人工驳回后的并行修复机制

## 规划器层

### UnifiedPlannerBase (基类)

**文件**: `src/planners/unified_base_planner.py`

```python
class UnifiedPlannerBase(ABC):
    @abstractmethod
    def validate_state(self, state) -> tuple[bool, str]: ...
    @abstractmethod
    def build_prompt(self, state) -> str: ...
    @abstractmethod
    def get_layer(self) -> int: ...
    
    def execute(self, state, model, temperature) -> Dict[str, Any]:
        prompt = self.build_prompt(state)
        response = self._call_llm(prompt, model, temperature)
        return self._parse_response(response)
```

### GenericPlanner (通用规划器)

**文件**: `src/planners/generic_planner.py`

```python
class GenericPlanner(UnifiedPlannerBase):
    """支持所有 28 维度的统一规划器"""
    
    def __init__(self, dimension_key: str):
        self.config = get_dimension_config(dimension_key)
        self.dimension_key = dimension_key
    
    def build_prompt(self, state) -> str:
        # 从 knowledge_cache 获取知识上下文
        knowledge = state.get("knowledge_cache", {}).get(self.dimension_key, "")
        ...
```

## 维度配置

**文件**: `src/config/dimension_metadata.py`

```python
DIMENSION_CONFIG = {
    # Layer 1 (12维度)
    "location": {"name": "区位分析", "layer": 1, "dependencies": []},
    "socio_economic": {"name": "社会经济", "layer": 1},
    "land_use": {"name": "土地利用", "layer": 1, "rag_enabled": True},
    # ...
    
    # Layer 2 (4维度)
    "resource_endowment": {"name": "资源禀赋", "layer": 2},
    "planning_positioning": {"name": "规划定位", "layer": 2},
    # ...
    
    # Layer 3 (12维度)
    "industry": {"name": "产业规划", "layer": 3},
    "land_use_planning": {"name": "土地利用规划", "layer": 3, "rag_enabled": True},
    # ...
}
```

## RAG 知识检索

### 模块结构

```
src/rag/
├── config.py                 # 配置：DATA_DIR, 向量库路径
├── core/
│   ├── tools.py              # 检索工具：knowledge_search_tool
│   ├── cache.py              # 查询缓存
│   └── context_manager.py    # 上下文管理
├── utils/
│   └── loaders.py            # 文档加载器
├── service/                  # 可选独立服务
└── scripts/
    └── build_kb_auto.py      # 知识库构建脚本
```

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

### 关键维度

- **Layer 1**: land_use, infrastructure, ecological_green, historical_culture
- **Layer 3**: land_use_planning, infrastructure_planning, ecological, disaster_prevention, heritage

## 数据流

```
前端 raw_data (村庄现状)
      │
      ▼
backend/api/planning.py
      │ 构建 initial_state
      ▼
orchestration/main_graph.py
      │ StateGraph.astream()
      ▼
┌─────────────────────────────────────┐
│ Layer 1 子图                         │
│   raw_data → 各维度分析              │
│   knowledge_cache → Prompt 注入      │
│   → analysis_reports                │
└─────────────────────────────────────┘
      │
      ▼
Layer 2 → Layer 3 → final_output
      │
      ▼
SSE 事件推送 → 前端显示
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `src/agent.py` | 对外接口 |
| `src/orchestration/main_graph.py` | 主图编排 |
| `src/subgraphs/analysis_subgraph.py` | Layer 1 子图 |
| `src/subgraphs/concept_subgraph.py` | Layer 2 子图 |
| `src/subgraphs/detailed_plan_subgraph.py` | Layer 3 子图 |
| `src/subgraphs/revision_subgraph.py` | Revision 子图 |
| `src/nodes/layer_nodes.py` | Layer 节点封装 |
| `src/nodes/subgraph_nodes.py` | 子图节点 |
| `src/planners/unified_base_planner.py` | 规划器基类 |
| `src/planners/generic_planner.py` | 通用规划器 |
| `src/config/dimension_metadata.py` | 维度配置 |
| `src/core/llm_factory.py` | LLM 工厂 |
| `src/rag/core/tools.py` | RAG 检索工具 |
| `src/rag/utils/loaders.py` | 文档加载器 |
| `src/tools/knowledge_tool.py` | 知识检索工具接口 |
