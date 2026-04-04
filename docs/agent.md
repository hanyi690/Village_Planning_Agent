# 智能体架构文档

> **相关文档**: [系统架构总览](architecture.md) | [前端实现](frontend.md) | [工具系统](tool-system.md)
>
> LangGraph 核心引擎 - 三层递进式规划系统 + RAG 知识检索

## 版本信息

- **版本**: 2.2.0
- **架构**: hierarchical-langgraph
- **更新**: Prompt 模板系统集成，28维度专业模板

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

## Prompt 模板系统

### 概述

系统为 28 个维度各配备了专业的 Prompt 模板，包含详细的输出格式规范、分析要点和禁忌事项。

### 模板文件结构

```
src/subgraphs/
├── analysis_prompts.py        # Layer 1: 12维度现状分析模板
│   └── get_dimension_prompt(dimension_key, raw_data, ...)
├── concept_prompts.py         # Layer 2: 4维度规划思路模板
│   └── get_dimension_prompt(dimension_key, analysis_report, ...)
└── detailed_plan_prompts.py   # Layer 3: 12维度详细规划模板
    └── get_dimension_prompt(dimension_key, project_name, ...)
```

### 模板调用链

```
dimension_node.py
    │
    ├── Layer 1 → analysis_prompts.get_dimension_prompt()
    │     └── 输入: raw_data, task_description, constraints
    │
    ├── Layer 2 → concept_prompts.get_dimension_prompt()
    │     └── 输入: analysis_report (Layer1摘要), superior_planning_context
    │
    └── Layer 3 → detailed_plan_prompts.get_dimension_prompt()
          └── 输入: analysis_report, planning_concept, dimension_plans
```

### Layer 1 模板示例

**区位分析 (location)** 专业格式要求：

```
输出格式要求（严格遵循）：
1. 层级展开格式：必须按照从大到小的层级展开（省→市→县→镇→村）
2. 每层独立段落：每个层级的描述独立成段
3. 冒号分隔：使用"[地点]在[上级区域]的位置：描述内容"的格式
4. 自然段落叙述：不要使用编号列表（1. 2. 3.），使用自然段落

输出格式示例：
[市]在[省]的位置：[市]是[省][区域位置]，位于[省][方位]。
[县]在[市]的位置：[县]是[市][行政关系]，位于[市][方位]。
...
```

### Layer 2 模板示例

**资源禀赋 (resource_endowment)** 专业格式要求：

```
输出格式要求（严格遵循）：
1. 简洁条目式：使用"[资源类型]：[具体资源]"的格式
2. 每行一个资源类别：每个资源类别必须独占一行
3. 唯一性资源识别（重点）：
   - 全镇唯一：识别在全镇范围内独有的稀缺资源
   - 全县唯一：识别在县级范围内独有的独特资源

输出格式示例：
民俗资源：黄粄、船灯舞、仙人粄
自然资源：古檀林、山溪、杉木林
唯一性标签：【全镇唯一】1200年古檀木、【全县唯一】船灯舞非遗
```

### Layer 3 模板示例

**产业规划 (industry)** 专业格式要求：

```
规划要点：
1. 产业定位与资源匹配
2. 三链逻辑构建：
   - 强链——强化现有环节
   - 补链——补充缺失环节
   - 拓链——延伸产业链条
3. 产业体系构建（一二三产融合）
4. 产业项目细化（项目名称/建设内容/规模/选址）
5. 空间布局
6. 实施保障

输出要求：
- 使用表格呈现产业项目清单
- 三链逻辑完整，上下游衔接紧密
```

### 模板集成机制

**`dimension_node.py` 的 `_build_dimension_prompt()` 函数**：

```python
def _build_dimension_prompt(dimension_key, dimension_name, village_data,
                            task_description, constraints, reports) -> str:
    """构建维度分析 prompt - 使用专业模板"""
    layer = get_dimension_layer(dimension_key) or 3

    # Layer 1: 使用 analysis_prompts 模板
    if layer == 1:
        from ...subgraphs.analysis_prompts import get_dimension_prompt
        return get_dimension_prompt(
            dimension_key=dimension_key,
            raw_data=village_data,
            task_description=task_description,
            constraints=constraints
        )

    # Layer 2: 使用 concept_prompts 模板
    elif layer == 2:
        from ...subgraphs.concept_prompts import get_dimension_prompt
        layer1_reports = reports.get("layer1", {})
        analysis_summary = _format_layer1_summary(layer1_reports)
        return get_dimension_prompt(
            dimension_key=dimension_key,
            analysis_report=analysis_summary,
            superior_planning_context=_get_superior_planning_context(reports)
        )

    # Layer 3: 使用 detailed_plan_prompts 模板
    elif layer == 3:
        from ...subgraphs.detailed_plan_prompts import get_dimension_prompt
        # ... 构建 Layer 1 和 Layer 2 报告摘要
        return get_dimension_prompt(
            dimension_key=dimension_key,
            project_name=project_name,
            analysis_report=analysis_summary,
            planning_concept=concept_summary,
            dimension_plans=dimension_plans
        )
```

### 辅助函数

| 函数 | 功能 |
|------|------|
| `_format_layer1_summary()` | 格式化 Layer 1 报告摘要（截取前 500 字符） |
| `_format_layer2_summary()` | 格式化 Layer 2 报告摘要 |
| `_get_superior_planning_context()` | 获取上位规划上下文（从 Layer 1 的 superior_planning 维度） |
| `_get_dimension_plans()` | 获取前序详细规划内容（project_bank 维度专用） |
| `_build_fallback_prompt()` | 备用简化 prompt（仅用于未知维度） |

### 维度键名映射

维度键名在 `dimension_metadata.py` 和模板文件中完全匹配，无需额外映射：

| 层级 | 维度键名 | 模板变量 |
|------|---------|---------|
| Layer 1 | `location`, `socio_economic`, ... | `ANALYSIS_DIMENSIONS[key]` |
| Layer 2 | `resource_endowment`, `planning_positioning`, ... | `*_PROMPT` 常量 |
| Layer 3 | `industry`, `spatial_structure`, ... | `get_dimension_prompt()` 的 `dimension_map` |

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

## RAG 知识检索（v2.0 - 支持元数据过滤）

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

### 核心创新点（2026-03 新增）

**Phase 1: 元数据注入模块** ✅
- `DimensionTagger` - 15 个分析维度自动识别
- `TerrainTagger` - 5 种地形类型识别
- `DocumentTypeTagger` - 5 种文档类型识别
- `MetadataInjector` - 批量注入元数据到切片

**Phase 2: 差异化切片策略** ✅
- `PolicySlicer` - 按"第 X 条"分割（政策文档）
- `CaseSlicer` - 按项目阶段分割（案例文档）
- `StandardSlicer` - 按章节编号分割（标准规范）
- `GuideSlicer` - 按知识点/标题分割（指南手册）

**Phase 3: 元数据过滤检索** ✅
- `_build_metadata_filter` - 复合过滤条件构建
- `search_knowledge` - 支持维度/地形/文档类型过滤
- `check_technical_indicators` - 技术指标精准检索

**Phase 4: 集成到入库流程** ✅
- `src/rag/build.py` - 差异化切片 + 元数据注入
- `src/rag/core/kb_manager.py` - 增量添加文档时注入

### 模块结构

```
src/rag/
├── config.py                 # 配置（Embedding、向量库）
├── build.py                  # 知识库构建入口（已集成差异化切片）
├── metadata/                 # 元数据模块（新增）
│   ├── __init__.py
│   ├── tagging_rules.py      # 标注规则配置（24 维度关键词映射）
│   └── injector.py           # 元数据注入器
├── slicing/                  # 切片策略模块（新增）
│   ├── __init__.py
│   └── strategies.py         # 差异化切片策略
├── core/
│   ├── tools.py              # knowledge_search_tool（支持 metadata 过滤）
│   ├── cache.py              # Embedding 模型缓存
│   ├── loaders.py            # 文档加载器
│   ├── kb_manager.py         # 知识库管理（已集成元数据注入）
│   └── summarization.py      # 文档摘要生成
└── scripts/
    └── build_kb_auto.py      # 构建脚本
```

### 元数据字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| dimension_tags | List[str] | 适用的分析维度列表 |
| terrain | str | 地形类型：mountain/plain/hill/coastal/riverside/all |
| document_type | str | 文档类型：policy/standard/case/guide/report |
| source | str | 来源文件路径 |
| category | str | 知识类别：policies/cases/standards/domain/local |
| chunk_index | int | 切片在文档中的索引 |
| total_chunks | int | 文档总切片数 |
| regions | List[str] | 涉及的地区列表 |

### 使用示例

```python
from src.rag.core.tools import check_technical_indicators

# 山区道路交通规范检索（支持多维度过滤）
result = check_technical_indicators.invoke({
    "query": "道路宽度标准",
    "dimension": "traffic",
    "terrain": "mountain",
    "doc_type": "standard"
})
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
│   └── langsmith_integration.py # LangSmith 集成
├── config/
│   └── dimension_metadata.py   # 维度元数据 (28维度权威来源)
├── orchestration/
│   ├── main_graph.py           # 主图编排
│   ├── state.py                # 状态定义
│   ├── routing.py              # 路由逻辑
│   └── nodes/
│       ├── dimension_node.py   # 统一维度分析节点
│       └── revision_node.py    # 维度修复节点
├── subgraphs/
│   ├── analysis_prompts.py     # Layer 1 提示词 (12维度)
│   ├── concept_prompts.py      # Layer 2 提示词 (4维度)
│   └── detailed_plan_prompts.py # Layer 3 提示词 (12维度)
├── tools/
│   ├── registry.py             # 工具注册表
│   ├── tools.py                # 工具定义
│   └── core/                   # 核心工具实现
├── rag/
│   ├── config.py               # RAG 配置
│   ├── build.py                # 知识库构建入口
│   └── core/
│       ├── tools.py            # RAG 检索工具
│       └── kb_manager.py       # 知识库管理
└── utils/
    ├── logger.py               # 日志工具
    └── sse_publisher.py        # SSE 事件发布器
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `src/agent.py` | 对外接口（run_village_planning, run_analysis_only, run_concept_only） |
| `src/orchestration/main_graph.py` | 主图编排（状态定义、路由逻辑、图构建） |
| `src/orchestration/nodes/dimension_node.py` | 统一维度分析节点（Prompt 模板集成） |
| `src/orchestration/nodes/revision_node.py` | 维度修复节点 |
| `src/subgraphs/analysis_prompts.py` | Layer 1 提示词模板（12维度，含专业格式要求） |
| `src/subgraphs/concept_prompts.py` | Layer 2 提示词模板（4维度，含唯一性资源识别） |
| `src/subgraphs/detailed_plan_prompts.py` | Layer 3 提示词模板（12维度，含三链逻辑等） |
| `src/planners/generic_planner.py` | 通用规划器（工具调用、Prompt构建） |
| `src/config/dimension_metadata.py` | 维度配置（28个维度的元数据） |
| `src/tools/registry.py` | 工具注册表 |
| `src/tools/tools.py` | 工具定义 |
| `src/tools/project_extractor.py` | 项目提取工具 |
| `src/rag/core/tools.py` | RAG 检索工具集 |
| `src/core/llm_factory.py` | LLM 工厂（支持 DeepSeek/OpenAI/智谱） |
| `backend/services/planning_service.py` | 规划执行服务 |
| `backend/services/sse_manager.py` | SSE 事件管理 |

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