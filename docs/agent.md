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
│  revision_history: 修订历史记录                              │
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

## LLM 模型配置

### 当前配置 (DeepSeek V3)

```bash
# .env
LLM_MODEL=deepseek-chat
OPENAI_API_BASE=https://api.deepseek.com/v1
MAX_TOKENS=65536
```

### LLM Factory 架构

**文件**: `src/core/llm_factory.py`

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM Factory                              │
│                    create_llm()                             │
└─────────────────────────────────────────────────────────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                              ▼
    ┌──────────────────┐           ┌──────────────────┐
    │   OpenAI 兼容    │           │    ZhipuAI SDK   │
    │  ChatOpenAI      │           │  ChatZhipuAI     │
    │                  │           │                  │
    │  • DeepSeek      │           │  • glm-4-flash   │
    │  • OpenAI        │           │  • glm-4-plus    │
    │  • 其他兼容接口   │           │                  │
    └──────────────────┘           └──────────────────┘
```

### 提供商自动检测

```python
# src/core/llm_factory.py
def detect_provider(model_name: str) -> LLMProvider:
    if model_name.startswith("glm-"):
        return LLMProvider.ZHIPUAI
    elif model_name.startswith("gpt-") or model_name.startswith("deepseek-"):
        return LLMProvider.OPENAI
    return LLMProvider.OPENAI
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
    revision_target_dimensions: List[str]  # 用户选择的修复维度

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

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]
```

## 主图编排

**文件**: `src/orchestration/main_graph.py`

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
    builder.add_conditional_edges("tool_bridge", route_after_tool_bridge)
    
    return builder.compile(checkpointer=checkpointer)
```

### 路由函数

```python
def route_after_pause(state) -> Literal["tool_bridge", "layer1", "layer2", "layer3", "final"]:
    # 优先检查修复标志
    if state.get("need_revision"):
        return "tool_bridge"
    
    # 根据current_layer路由
    current_layer = state.get("current_layer", 1)
    if current_layer == 1: return "layer1_analysis"
    if current_layer == 2: return "layer2_concept"
    if current_layer == 3: return "layer3_detail"
    if current_layer == 4: return "generate_final"

def route_after_layer1(state) -> Literal["tool_bridge", "layer2", "end"]:
    if not state["layer_1_completed"]:
        return "end"
    if state.get("step_mode") and state.get("previous_layer") > 0:
        return "tool_bridge"
    return "layer2"
```

## 子图实现

### Layer 1: 现状分析子图

**文件**: `src/subgraphs/analysis_subgraph.py`

**执行模式**: Map-Reduce 并行

```
initialize → knowledge_preload_node → [analyze_dimension x12] → reduce
```

**维度列表**: location, socio_economic, villager_wishes, superior_planning, natural_environment, land_use, traffic, public_services, infrastructure, ecological_green, architecture, historical_culture

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
Wave 1: 11维度并行 (industry, spatial_structure, ...)
Wave 2: project_bank (依赖 Wave 1 全部完成)
```

### Revision 子图

**文件**: `src/subgraphs/revision_subgraph.py`

**功能**: 处理人工驳回后的并行修复机制

**级联更新**: 修复一个维度时，自动更新所有下游依赖维度

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

### 完整维度元数据

```python
DIMENSIONS_METADATA: Dict[str, Dict[str, Any]] = {
    # Layer 1: 现状分析 (12个)
    "location": {
        "key": "location",
        "name": "区位与对外交通分析",
        "layer": 1,
        "dependencies": [],
        "rag_enabled": True,
        "prompt_key": "location_analysis"
    },
    # ... 其他 Layer 1 维度
    
    # Layer 2: 规划思路 (4个)
    "resource_endowment": {
        "key": "resource_endowment",
        "name": "资源禀赋分析",
        "layer": 2,
        "dependencies": {
            "layer1_analyses": ["natural_environment", "land_use", ...]
        },
        "rag_enabled": False,
    },
    # ... 其他 Layer 2 维度
    
    # Layer 3: 详细规划 (12个)
    "land_use_planning": {
        "key": "land_use_planning",
        "name": "土地利用规划",
        "layer": 3,
        "dependencies": {
            "layer1_analyses": ["land_use", "natural_environment"],
            "layer2_concepts": ["planning_positioning", "planning_strategies"]
        },
        "rag_enabled": True,  # 关键维度
    },
    # ... 其他 Layer 3 维度
}
```

### 辅助函数

```python
def get_dimension_config(dimension_key: str) -> Optional[Dict]
def list_dimensions(layer: Optional[int] = None) -> List[Dict]
def get_layer_dimensions(layer: int) -> List[str]
def get_dimension_layer(dimension_key: str) -> Optional[int]

# 依赖链
def get_full_dependency_chain() -> Dict[str, Dict]
def get_execution_wave(dimension_key: str) -> int
def get_dimensions_by_wave(wave: int, layer: Optional[int]) -> List[str]

# 级联修复
def get_downstream_dependencies(dimension_key: str) -> List[str]
def get_impact_tree(dimension_key: str) -> Dict[int, List[str]]
def get_revision_wave_dimensions(targets: List[str], completed: List[str]) -> Dict[int, List[str]]
```

### RAG 启用的维度

**Layer 1**: location, socio_economic, villager_wishes, superior_planning, natural_environment, land_use, traffic, public_services, infrastructure, ecological_green, architecture, historical_culture (全部启用)

**Layer 3**: land_use_planning, infrastructure_planning, ecological, disaster_prevention, heritage (关键维度)

## RAG 知识检索

### 模块结构

```
src/rag/
├── config.py                 # 配置：DATA_DIR, 向量库路径
├── build.py                  # 知识库构建入口
├── core/
│   ├── tools.py              # 检索工具：knowledge_search_tool
│   ├── cache.py              # Embedding 模型缓存
│   ├── context_manager.py    # 上下文管理
│   └── summarization.py      # 文档摘要生成
├── utils/
│   └── loaders.py            # 文档加载器 (PDF, DOCX, DOC, PPTX等)
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

## 目录结构

```
src/
├── __init__.py
├── agent.py                    # 对外接口
├── core/
│   ├── config.py               # 全局配置
│   ├── llm_factory.py          # LLM工厂
│   ├── prompts.py              # Prompt模板
│   ├── state_builder.py        # 状态构建器
│   ├── streaming.py            # 流式输出
│   └── langsmith_integration.py # LangSmith集成
├── config/
│   └── dimension_metadata.py   # 维度元数据
├── orchestration/
│   └── main_graph.py           # 主图编排
├── subgraphs/
│   ├── analysis_subgraph.py    # Layer 1 子图
│   ├── analysis_prompts.py
│   ├── concept_subgraph.py     # Layer 2 子图
│   ├── concept_prompts.py
│   ├── detailed_plan_subgraph.py # Layer 3 子图
│   ├── detailed_plan_prompts.py
│   └── revision_subgraph.py    # Revision 子图
├── nodes/
│   ├── base_node.py            # 节点基类
│   ├── layer_nodes.py          # Layer 节点
│   ├── subgraph_nodes.py       # 子图节点
│   └── tool_nodes.py           # 工具节点
├── planners/
│   ├── unified_base_planner.py # 规划器基类
│   └── generic_planner.py      # 通用规划器
├── tools/
│   ├── registry.py             # 工具注册表
│   ├── knowledge_tool.py       # 知识检索工具
│   ├── planner_tool.py         # 规划工具
│   ├── revision_tool.py        # 修复工具
│   ├── file_manager.py         # 文件管理
│   ├── web_review_tool.py      # Web审查工具
│   └── adapters/               # 适配器
├── rag/
│   ├── config.py
│   ├── build.py
│   ├── core/
│   ├── utils/
│   └── scripts/
└── utils/
    ├── logger.py
    ├── output_manager.py
    ├── report_utils.py
    ├── blackboard_manager.py
    └── paths.py
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `src/agent.py` | 对外接口 |
| `src/core/config.py` | 全局配置 (LLM, API Keys) |
| `src/core/llm_factory.py` | LLM 工厂 |
| `src/orchestration/main_graph.py` | 主图编排 |
| `src/subgraphs/analysis_subgraph.py` | Layer 1 子图 |
| `src/subgraphs/concept_subgraph.py` | Layer 2 子图 |
| `src/subgraphs/detailed_plan_subgraph.py` | Layer 3 子图 |
| `src/subgraphs/revision_subgraph.py` | Revision 子图 |
| `src/nodes/layer_nodes.py` | Layer 节点封装 |
| `src/nodes/tool_nodes.py` | 工具节点 |
| `src/planners/generic_planner.py` | 通用规划器 |
| `src/config/dimension_metadata.py` | 维度配置 |
| `src/rag/core/tools.py` | RAG 检索工具 |
| `src/tools/revision_tool.py` | 维度修复工具 |
