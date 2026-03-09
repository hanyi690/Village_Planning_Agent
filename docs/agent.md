# 智能体架构文档

> LangGraph 核心引擎 - 三层递进式规划系统 + RAG 知识检索

## 版本信息

- **版本**: 2.1.0
- **架构**: hierarchical-langgraph

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                   src/agent.py (接口层)                             │
│  run_village_planning() / run_analysis_only() / run_concept_only()  │
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
    session_id: str                # 会话ID（用于流式输出事件）

    # 流程控制
    current_layer: int             # 当前层级 (1/2/3/4，4表示完成)
    layer_1_completed: bool
    layer_2_completed: bool
    layer_3_completed: bool

    # 人工审核
    need_human_review: bool
    human_feedback: str
    need_revision: bool
    revision_target_dimensions: List[str]

    # 各层成果
    analysis_reports: Dict[str, str]  # Layer 1: 各维度现状分析报告
    concept_reports: Dict[str, str]   # Layer 2: 各维度规划思路报告
    detail_reports: Dict[str, str]    # Layer 3: 各维度详细规划报告
    final_output: str

    # RAG 知识缓存
    knowledge_cache: Dict[str, str]

    # 元数据 - 持久化到 Checkpoint，用于去重和版本化同步
    metadata: Dict[str, Any]  # {published_layers, version, last_signal_timestamp, event_id_counter}

    # 步进模式
    step_mode: bool
    step_level: str                # 步骤级别（layer/dimension/skill）
    pause_after_step: bool
    previous_layer: int            # 刚完成的层级编号

    # 路由控制
    quit_requested: bool           # 用户请求退出
    trigger_rollback: bool         # 触发回退
    rollback_target: str           # 回退目标checkpoint ID

    # 修订历史
    revision_history: List[Dict[str, Any]]
    last_revised_dimensions: List[str]

    # 黑板模式数据共享
    blackboard: Dict[str, Any]

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]
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

**执行模式**: 波次路由 + 项目影子缓存优化

```
Wave 1: 11维度并行 (industry, spatial_structure, ...)
    │
    ├── 完成后调用 extract_projects_batch() 提取项目信息
    │   └── 存入 project_shadow_cache
    │
    ▼
Wave 2: project_bank (依赖 Wave 1 全部完成)
    │
    ├── 从 project_shadow_cache 读取项目信息
    ├── 格式化为 filtered_detail（~5000字符）
    └── 替代完整报告（~50000字符，节省约90% token）
```

**项目影子缓存优化**:
- Wave 1 完成时，从各维度报告中提取建设项目信息
- 使用正则 + LLM 混合提取，确保准确性
- project_bank 维度使用影子缓存替代完整报告
- 显著减少 LLM 输入 token 量

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

### Layer 1 维度列表

location, socio_economic, villager_wishes, superior_planning, natural_environment, land_use, traffic, public_services, infrastructure, ecological_green, architecture, historical_culture

### Layer 2 维度列表

resource_endowment, planning_positioning, development_goals, planning_strategies

### Layer 3 维度列表

industry, spatial_structure, land_use_planning, settlement_planning, traffic_planning, public_service, infrastructure_planning, ecological, disaster_prevention, heritage, landscape, project_bank

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
│   ├── streaming.py            # 流式输出
│   ├── prompts.py              # 提示词模板
│   └── langsmith_integration.py # LangSmith 集成
├── config/
│   └── dimension_metadata.py   # 维度元数据
├── orchestration/
│   └── main_graph.py           # 主图编排
├── subgraphs/
│   ├── analysis_subgraph.py    # Layer 1 子图
│   ├── analysis_prompts.py     # Layer 1 提示词
│   ├── concept_subgraph.py     # Layer 2 子图
│   ├── concept_prompts.py      # Layer 2 提示词
│   ├── detailed_plan_subgraph.py # Layer 3 子图
│   ├── detailed_plan_prompts.py # Layer 3 提示词
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
│   ├── file_manager.py         # 文件管理器
│   ├── knowledge_tool.py       # 知识检索工具接口
│   ├── revision_tool.py        # 修复工具
│   ├── web_review_tool.py      # Web 审查工具
│   ├── project_extractor.py    # 项目提取工具
│   └── adapters/               # 适配器
│       ├── base_adapter.py
│       ├── population_adapter.py
│       ├── gis_adapter.py
│       └── network_adapter.py
├── rag/
│   ├── config.py               # RAG 配置
│   ├── build.py                # 知识库构建入口
│   └── core/
│       ├── tools.py            # RAG 检索工具
│       ├── cache.py            # Embedding 模型缓存
│       └── loaders.py          # 文档加载器
└── utils/
    ├── logger.py               # 日志工具
    ├── output_manager.py       # 输出管理器
    ├── blackboard_manager.py   # 黑板管理器
    ├── report_utils.py         # 报告生成工具
    └── paths.py                # 路径配置
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `src/agent.py` | 对外接口（run_village_planning, run_analysis_only, run_concept_only） |
| `src/orchestration/main_graph.py` | 主图编排（状态定义、路由逻辑、图构建） |
| `src/subgraphs/analysis_subgraph.py` | Layer 1 子图（12维度并行分析） |
| `src/subgraphs/concept_subgraph.py` | Layer 2 子图（4维度波次执行） |
| `src/subgraphs/detailed_plan_subgraph.py` | Layer 3 子图（12维度波次执行） |
| `src/subgraphs/revision_subgraph.py` | Revision 子图（级联修复） |
| `src/planners/generic_planner.py` | 通用规划器（工具调用、Prompt构建） |
| `src/config/dimension_metadata.py` | 维度配置（28个维度的元数据） |
| `src/tools/registry.py` | 工具注册表 |
| `src/tools/project_extractor.py` | 项目提取工具 |
| `src/tools/file_manager.py` | 文件管理器（支持多种格式） |
| `src/rag/core/tools.py` | RAG 检索工具集 |
| `src/nodes/base_node.py` | 节点基类（BaseNode, AsyncBaseNode） |
| `src/nodes/layer_nodes.py` | Layer 节点实现 |
| `src/core/llm_factory.py` | LLM 工厂（支持 DeepSeek/OpenAI/智谱） |

## 项目库影子缓存机制

### 概述

项目库（project_bank）维度依赖所有其他 Layer 3 维度的输出。为避免将完整的 11 份报告（约 50000+ 字符）作为输入，系统实现了影子缓存优化：

```
原始方案: 11 份完整报告 → project_bank LLM（~50000 字符输入）
优化方案: 影子缓存 → project_bank LLM（~5000 字符输入）
节省效果: 约 90% token 减少
```

### 数据流架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Wave 1 Dimensions (并行)                      │
│  industry, spatial_structure, land_use_planning, ...            │
│                           ↓                                      │
│              completed_dimension_reports                         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│              reduce_dimension_plans() 项目提取                   │
│  ┌─────────────────┐    ┌─────────────────┐                     │
│  │ 正则提取        │    │ LLM 提取        │                     │
│  │ PROJECT_PATTERNS│    │ PROJECT_EXTRACTOR│                    │
│  │ SCALE_PATTERNS  │    │ _PROMPT          │                    │
│  └────────┬────────┘    └────────┬────────┘                     │
│           └──────────┬───────────┘                              │
│                      ↓                                           │
│           project_shadow_cache                                   │
│           {dim: [{name, scale, phase, ...}]}                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│              Wave 2: project_bank                                │
│  format_shadow_cache_for_prompt() → filtered_detail             │
│  格式化输出:                                                      │
│  ### 产业规划                                                     │
│  - 特色种植基地（50亩） [近期]                                    │
│  - 农产品加工车间（300㎡） [中期]                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 项目提取模式

**正则提取模式**（`src/tools/project_extractor.py`）:

```python
PROJECT_PATTERNS = [
    r"项目[名称]*[：:]\s*([^\n]+)",           # 项目名称：XXX
    r"建设[（(]?([^）)\n]{2,20})[）)]?",       # 建设XXX
    r"(新建|改造|扩建|修建)([^，,。\n]{2,25})", # 新建/改造XXX
    # ...
]

SCALE_PATTERNS = [
    r"(面积|规模|长度)[：:]\s*(\d+\.?\d*)\s*(㎡|km|m)",
    # ...
]

PHASE_KEYWORDS = {
    "近期": ["近期", "2025", "2026", "一期"],
    "中期": ["中期", "2027", "2028", "二期"],
    "远期": ["远期", "2029", "2030", "三期"],
}
```

**LLM 辅助提取**:
- 当内容包含项目关键词时，调用 LLM 补充提取
- 输出结构化 JSON: `[{name, content, scale, location, phase}]`
- 与正则提取结果合并去重

### 影子缓存格式化

```python
def format_shadow_cache_for_prompt(shadow_cache) -> str:
    """
    将影子缓存格式化为 Prompt 输入
    
    输出格式:
    ### 产业规划
    - 特色种植基地（50亩） [近期]
    - 农产品加工车间（300㎡） [中期]
    
    ### 道路交通规划
    - 主干道硬化（2km） [近期]
    """
```

### 状态传递链

```
1. Wave 1 完成 → reduce_dimension_plans()
   └─ extract_projects_batch() → project_shadow_cache

2. Wave 2 路由 → create_parallel_tasks_with_state_filtering()
   └─ format_shadow_cache_for_prompt() → filtered_detail

3. GenericPlanner._prepare_prompt_params()
   └─ state.get("filtered_detail") → params["dimension_plans"]

4. _build_layer3_prompt()
   └─ get_dimension_prompt("project_bank", dimension_plans=...)
```

## 流式输出系统

### 架构概览

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   LLM API    │───▶│  Planner     │───▶│  Backend     │───▶│   Frontend   │
│ (DeepSeek)   │    │  (Generic)   │    │  (FastAPI)   │    │  (React)     │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
       │                   │                   │                   │
       │ streaming=True    │ on_token_callback │ SSE Events        │ EventSource
       ▼                   ▼                   ▼                   ▼
   llm.stream()     StreamingCallback   dimension_delta     useStreamingRender
```

### Token 回调机制

**StreamingCallback 类**（`src/planners/unified_base_planner.py`）:

```python
class StreamingCallback(BaseCallbackHandler):
    """流式回调处理器"""
    
    def __init__(self, on_token_callback: Callable[[str, str], None] | None = None):
        self.on_token_callback = on_token_callback
        self.accumulated_content = ""
    
    def on_llm_new_token(self, token: str, **kwargs) -> None:
        """每次生成新 token 时调用"""
        self.accumulated_content += token
        if self.on_token_callback:
            self.on_token_callback(token, self.accumulated_content)
```

**回调函数签名**:
```python
def on_token_callback(token: str, accumulated: str) -> None:
    """
    Args:
        token: 当前生成的 token（增量）
        accumulated: 累积的完整内容
    """
```

### 频率控制

后端对 SSE 事件进行频率控制，避免事件过多：

```python
# 频率控制参数
DELTA_MIN_INTERVAL_MS = 500  # 最小发送间隔（毫秒）
DELTA_MIN_TOKENS = 50        # 最小 token 数量

# 发送条件：满足其一即可
should_send = (time_elapsed >= 500) or (token_count >= 50)
```

### 子图节点集成

**维度分析节点中的 Token 回调**（`src/nodes/subgraph_nodes.py`）:

```python
def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
    session_id = state.get("session_id", "")
    
    # 创建 Token 回调函数
    def on_token_callback(token: str, accumulated: str):
        if session_id:
            from backend.api.planning import append_dimension_delta_event
            append_dimension_delta_event(
                session_id=session_id,
                layer=1,
                dimension_key=dimension_key,
                dimension_name=dimension_name,
                delta=token,
                accumulated=accumulated
            )
    
    # 执行规划器（启用流式）
    planner_result = planner.execute(
        planner_state,
        streaming=True,
        on_token_callback=on_token_callback
    )
    
    # 发送维度完成事件
    if session_id:
        flush_dimension_delta(...)  # 强制刷新剩余 token
        append_dimension_complete_event(...)
```

### SSE 事件类型

| 事件类型 | 数据内容 | 触发时机 |
|---------|---------|---------|
| `dimension_delta` | `{layer, dimension_key, delta, accumulated}` | 频率控制后发送 |
| `dimension_complete` | `{layer, dimension_key, full_content}` | 维度分析完成 |
| `layer_completed` | `{layer, has_data, version}` | 层级完成（Signal-Fetch 模式） |

### 前端批处理

前端使用 `useStreamingRender` Hook 进行批处理，减少 DOM 更新：

```typescript
// 配置参数
const { batchSize = 10, batchWindow = 50, debounceMs = 100 } = options;

// 使用 requestAnimationFrame 批量更新
const scheduleBatch = () => {
  requestAnimationFrame(() => {
    flushBatchInternal();  // 防抖后执行回调
  });
};
```