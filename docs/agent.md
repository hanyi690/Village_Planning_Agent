# 核心智能体实现文档

> **村庄规划智能体** - LangGraph 分层规划引擎
>
> **最后更新**: 2025年 | **版本**: 2.0

## 目录

- [LangGraph 架构](#langgraph-架构)
- [三层规划系统](#三层规划系统)
- [节点架构](#节点架构)
- [维度映射](#维度映射)
- [工具和适配器](#工具和适配器)
- [LLM 集成](#llm-集成)

---

## LangGraph 架构

### 主图编排

**位置**: `src/orchestration/main_graph.py`

#### 核心概念

**状态图 (StateGraph)**:

```python
class VillagePlanningState(TypedDict):
    # 输入
    project_name: str
    village_data: str
    task_description: str
    constraints: str

    # 流程控制
    current_layer: int
    layer_1_completed: bool
    layer_2_completed: bool
    layer_3_completed: bool

    # 人工审核
    need_human_review: bool
    human_feedback: str
    need_revision: bool

    # 各层成果
    analysis_report: str
    planning_concept: str
    detailed_plan: str
    final_output: str

    # 输出管理
    output_manager: OutputManager

    # 检查点
    checkpoint_enabled: bool
    last_checkpoint_id: str
    checkpoint_manager: Any

    # 逐步执行模式
    step_mode: bool
    step_level: str
    pause_after_step: bool

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]

    # 黑板模式数据共享
    blackboard: Dict[str, Any]
```

**代码位置**: `main_graph.py:53-113`

---

#### 主图结构

```
┌─────────┐
│  START  │
└────┬────┘
     │
     ▼
┌─────────┐
│  Pause  │ ◄─────┐ (暂停管理节点)
└────┬────┘       │
     │            │
     ▼            │
┌─────────────────┴────────┐
│  Route after_pause       │ (根据 current_layer 路由)
└───┬─────────┬─────────┬──┘
    │         │         │
    ▼         ▼         ▼
┌────────┐ ┌────────┐ ┌────────┐
│Layer 1 │ │Layer 2 │ │Layer 3 │
└───┬────┘ └───┬────┘ └───┬────┘
    │           │           │
    └───────────┴───────────┘
                │
                ▼
         ┌─────────────┐
         │Tool Bridge  │ (工具桥接节点)
         └──────┬──────┘
                │
                ▼
         ┌─────────────┐
         │  Pause      │
         └─────────────┘
```

**代码位置**: `main_graph.py:789-886`

---

#### 执行流程

**1. 初始化**:

```python
initial_state = {
    "project_name": project_name,
    "village_data": village_data,
    "current_layer": 1,
    "layer_1_completed": False,
    "layer_2_completed": False,
    "layer_3_completed": False,
    "step_mode": step_mode,
    "pause_after_step": step_mode,
    # ...
}
```

**2. 执行主图**:

```python
graph = create_village_planning_graph()
final_state = graph.invoke(initial_state)
```

**代码位置**: `main_graph.py:892-1107`

---

### 路由决策

#### `route_after_pause`

**功能**: 根据 `current_layer` 决定执行哪个 layer

**代码**: `main_graph.py:653-671`

```python
def route_after_pause(state: VillagePlanningState):
    """pause节点后的路由"""
    current_layer = state.get("current_layer", 1)

    if current_layer == 1:
        return "layer1_analysis"
    elif current_layer == 2:
        return "layer2_concept"
    elif current_layer == 3:
        return "layer3_detail"
    else:
        return "layer1_analysis"
```

---

#### `route_after_layer1`

**功能**: Layer 1 完成后的路由决策

**逻辑**:

- 如果失败 → 结束
- 如果需要暂停/审查 → 工具桥接
- 否则 → Layer 2

**代码**: `main_graph.py:674-690`

---

#### `route_after_tool_bridge`

**功能**: 工具桥接后的路由决策

**逻辑**:

- 检查退出标志 → 结束
- 检查回退标志 → 结束
- 检查修复标志 → 继续对应 layer
- 根据 current_layer 和 step_mode 决定下一步

**代码**: `main_graph.py:722-782`

---

## 三层规划系统

### Layer 1: 现状分析子图

**位置**: `src/subgraphs/analysis_subgraph.py`

#### 12 个并行维度

**维度列表**:

1. 区位与对外交通分析 (`location`)
2. 社会经济分析 (`socio_economic`)
3. 村民意愿与诉求分析 (`villager_wishes`)
4. 上位规划与政策导向分析 (`superior_planning`)
5. 自然环境与生态本底分析 (`natural_environment`)
6. 土地利用与合规性分析 (`land_use`)
7. 道路交通与街巷空间分析 (`traffic`)
8. 公共服务设施承载力分析 (`public_services`)
9. 基础设施现状分析 (`infrastructure`)
10. 生态绿地与开敞空间分析 (`ecological_green`)
11. 聚落形态与建筑风貌分析 (`architecture`)
12. 历史文化与乡愁保护分析 (`historical_culture`)

**代码位置**: `src/core/dimension_mapping.py:12-25`

---

#### 子图结构（重构版：无汇总节点）

```python
builder = StateGraph(AnalysisState)

# 添加初始化节点
builder.add_node("initialize", initialize_analysis)

# 添加单个维度分析节点（并行执行）
builder.add_node("analyze_dimension", analyze_dimension)

# 构建执行流程
builder.add_edge(START, "initialize")

# 路由到各维度（并行）
builder.add_conditional_edges("initialize", map_dimensions)

# 所有维度完成后直接结束
builder.add_edge("analyze_dimension", END)
```

**关键变化**：
- ✅ **删除了 `reduce_analyses` 节点**
- ✅ **删除了 `generate_final_report` 节点**
- ✅ **analyze_dimension 返回结果到 `analyses` 列表**
- ✅ **并行执行后直接到 END**
- ✅ **从 `analyses` 列表提取维度报告，使用英文键名**

**重要修复**: LangGraph 的 Send 机制为每个并行任务创建隔离状态，字典无法自动合并。解决方案是使用 `analyses` 列表（通过 `operator.add` 正确累积），然后在包装函数中转换为使用英文键名的字典。

**代码位置**: `analysis_subgraph.py:345-360`

```python
# 从 analyses 列表中提取维度报告并转换为字典（使用英文键名）
analyses = result.get("analyses", [])
dimension_reports = {}
for analysis in analyses:
    dimension_key = analysis.get("dimension_key")  # 英文键名
    analysis_result = analysis.get("analysis_result")
    if dimension_key and analysis_result:
        dimension_reports[dimension_key] = analysis_result

return {
    "analysis_dimension_reports": dimension_reports,  # 使用完整字段名
    "success": True
}
```

---

#### 维度规划器

**位置**: `src/planners/analysis_planners.py`

**基类**:

```python
class BaseAnalysisPlanner:
    """现状分析规划器基类"""

    def __init__(self, dimension_name: str, dimension_key: str):
        self.dimension_name = dimension_name
        self.dimension_key = dimension_key
        self.llm = create_llm()

    def analyze(self, raw_data: str) -> str:
        """执行分析"""
        prompt = self._build_prompt(raw_data)
        return self.llm.invoke(prompt).content
```

**12 个具体规划器**:

- `LocationAnalysisPlanner` - 区位分析
- `SocioEconomicAnalysisPlanner` - 社会经济分析
- `VillagerWishesAnalysisPlanner` - 村民意愿分析
- ... (共 12 个)

**代码位置**: `analysis_planners.py:30-400`

---

### Layer 2: 规划思路子图

**位置**: `src/subgraphs/concept_subgraph.py`

#### 4 个并行维度

**维度列表**:

1. 资源禀赋分析 (`resource_endowment`)
2. 规划定位分析 (`planning_positioning`)
3. 发展目标分析 (`development_goals`)
4. 规划策略分析 (`planning_strategies`)

**代码位置**: `src/core/dimension_mapping.py:150-155`

---

#### 子图结构（重构版：无汇总节点）

```python
builder = StateGraph(ConceptState)

# 添加初始化节点
builder.add_node("initialize", initialize_concept_analysis)

# 添加单个概念维度分析节点（并行执行）
builder.add_node("analyze_concept_dimension", analyze_concept_dimension)

# 构建执行流程
builder.add_edge(START, "initialize")

# 路由到各维度（并行）
builder.add_conditional_edges("initialize", map_concept_dimensions)

# 所有维度完成后直接结束
builder.add_edge("analyze_concept_dimension", END)
```

**关键变化**：
- ✅ **删除了 `reduce_concept_analyses` 节点**
- ✅ **删除了 `generate_final_concept` 节点**
- ✅ **analyze_concept_dimension 返回结果到 `concept_analyses` 列表**
- ✅ **并行执行后直接到 END**
- ✅ **从 `concept_analyses` 列表提取维度报告，使用英文键名**

**代码位置**: `concept_subgraph.py:409-424`

---

#### 概念规划器

**位置**: `src/planners/concept_planners.py`

**基类**:

```python
class BaseConceptPlanner:
    """规划思路规划器基类"""

    def __init__(self, dimension_name: str, dimension_key: str):
        self.dimension_name = dimension_name
        self.dimension_key = dimension_key
        self.llm = create_llm()

    def generate_concept(
        self,
        analysis_report: str,
        dimension_reports: Dict[str, str]
    ) -> str:
        """生成规划思路"""
        prompt = self._build_prompt(
            analysis_report,
            dimension_reports
        )
        return self.llm.invoke(prompt).content
```

**4 个具体规划器**:

- `ResourceEndowmentPlanner` - 资源禀赋
- `PlanningPositioningPlanner` - 规划定位
- `DevelopmentGoalsPlanner` - 发展目标
- `PlanningStrategiesPlanner` - 规划策略

**代码位置**: `concept_planners.py:30-200`

---

### Layer 3: 详细规划子图

**位置**: `src/subgraphs/detailed_plan_subgraph.py`

#### 12 个维度 + 分波执行

**维度列表**:

1. 产业规划 (`industry`)
2. 空间结构规划 (`spatial_structure`)
3. 土地利用规划 (`land_use_planning`)
4. 聚落体系规划 (`settlement_planning`)
5. 综合交通规划 (`traffic`)
6. 公共服务设施规划 (`public_service`)
7. 基础设施规划 (`infrastructure`)
8. 生态保护与修复 (`ecological`)
9. 防灾减灾规划 (`disaster_prevention`)
10. 历史文化遗产保护 (`heritage`)
11. 村庄风貌引导 (`landscape`)
12. 建设项目库 (`project_bank`)

**代码位置**: `src/core/dimension_mapping.py:200-220`

---

#### 分波执行（重构版：无汇总节点）

**Wave 1**: 前 11 个维度并行执行

**Wave 2**: `project_bank` 单独执行（依赖其他维度）

**代码**: `detailed_plan_subgraph.py:243-293`

```python
# Wave 1: 并行执行前 11 个维度
wave1_dims = [
    "industry", "spatial_structure", "land_use_planning",
    "settlement_planning", "traffic", "public_service",
    "infrastructure", "ecological", "disaster_prevention",
    "heritage", "landscape"
]

# 路由函数：根据波次决定执行哪些维度
def route_by_dependency_wave(state):
    current_wave = state.get("current_wave", 1)

    if current_wave == 1:
        # Wave 1: 11个维度并行
        return create_parallel_tasks(wave1_dims)
    elif current_wave == 2:
        # Wave 2: project_bank
        return create_parallel_tasks(["project_bank"])
    else:
        # 所有维度完成，直接结束
        return "end"

# 所有维度完成后直接到END（删除了generate_final_detailed_plan节点）
builder.add_node("end", lambda s: {"detailed_dimension_reports": extract_reports(s)})
builder.add_edge("end", END)
```

**关键变化**：
- ✅ **删除了 `generate_final_detailed_plan` 节点**
- ✅ **添加了 `end` 节点提取维度报告**
- ✅ **所有维度完成后直接到 END**

---

#### 详细规划规划器

**位置**: `src/planners/detailed_planners.py`

**基类**:

```python
class BaseDetailedPlanner:
    """详细规划规划器基类"""

    def __init__(self, dimension_name: str, dimension_key: str):
        self.dimension_name = dimension_name
        self.dimension_key = dimension_key
        self.llm = create_llm()

    def generate_detailed_plan(
        self,
        project_name: str,
        analysis_report: str,
        planning_concept: str,
        dimension_reports: Dict[str, str],
        concept_dimension_reports: Dict[str, str]
    ) -> str:
        """生成详细规划"""
        prompt = self._build_prompt(
            project_name,
            analysis_report,
            planning_concept,
            dimension_reports,
            concept_dimension_reports
        )
        return self.llm.invoke(prompt).content
```

**12 个具体规划器**:

- `IndustryPlanner` - 产业规划
- `SpatialStructurePlanner` - 空间结构规划
- `LandUsePlanningPlanner` - 土地利用规划
- ... (共 12 个)

**代码位置**: `detailed_planners.py:30-600`

---

## 节点架构

### 节点基类

**位置**: `src/nodes/base_node.py`

```python
class BaseNode:
    """节点基类"""

    def __init__(self, node_name: str):
        self.node_name = node_name
        self.logger = get_logger(f"Node-{node_name}")

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """节点执行入口"""
        raise NotImplementedError
```

---

### Layer 节点

**位置**: `src/nodes/layer_nodes.py`

#### Layer1AnalysisNode

**功能**: Layer 1 分析节点

```python
class Layer1AnalysisNode(BaseNode):
    """Layer 1 分析节点"""

    def __call__(self, state: VillagePlanningState) -> Dict[str, Any]:
        """调用现状分析子图"""
        result = call_analysis_subgraph(
            raw_data=state["village_data"],
            project_name=state["project_name"]
        )

        # 子图返回: {"analysis_dimension_reports": {...}, "success": True}
        dimension_reports = result.get("analysis_dimension_reports", {})

        # 生成综合报告（拼接各维度报告）
        combined_report = self._generate_combined_report(
            state["project_name"],
            dimension_reports,
            "现状分析"
        )

        return {
            "analysis_report": combined_report,
            "analysis_dimension_reports": dimension_reports,  # 使用完整字段名
            "layer_1_completed": result["success"],
            "current_layer": 2
        }
```

**重要说明**:
- 子图返回 `analysis_dimension_reports`（使用英文键名）
- 节点生成综合报告 `analysis_report`（拼接各维度）
- 维度报告键名示例: `{"location": "...", "socio_economic": "...", ...}`

**代码位置**: `layer_nodes.py:324-364`

---

#### Layer2ConceptNode

**功能**: Layer 2 规划思路节点

**代码位置**: `layer_nodes.py:52-90`

---

#### Layer3DetailNode

**功能**: Layer 3 详细规划节点

**代码位置**: `layer_nodes.py:92-140`

---

### 工具节点

**位置**: `src/nodes/tool_nodes.py`

#### ToolBridgeNode

**功能**: 工具桥接节点

**职责**:

- 处理人工审查 (`need_human_review`)
- 处理暂停交互 (`pause_after_step`)
- 处理修复 (`need_revision`)

**代码**: `tool_nodes.py:20-100`

```python
class ToolBridgeNode(BaseNode):
    """工具桥接节点"""

    def __call__(self, state: VillagePlanningState) -> Dict[str, Any]:
        """统一工具调用入口"""

        # 优先级：人工审查 > 暂停 > 修复
        if state.get("need_human_review", False):
            return self._prepare_human_review(state)
        elif state.get("pause_after_step", False):
            return self._prepare_pause(state)
        elif state.get("need_revision", False):
            return self._run_revision(state)
        else:
            return state
```

---

#### PauseManagerNode

**功能**: 暂停管理节点

**职责**:

- Step 模式下设置暂停状态
- 为下一层执行准备暂停状态

**代码**: `tool_nodes.py:102-130`

```python
class PauseManagerNode(BaseNode):
    """暂停管理节点"""

    def __call__(self, state: VillagePlanningState) -> Dict[str, Any]:
        """管理暂停状态"""
        if state.get("step_mode", False):
            return {"pause_after_step": True}
        return {}
```

---

## 维度映射

### 英文键名与中文名称映射

**重要说明**: 系统统一使用**英文键名**存储维度报告，在显示时映射为**中文名称**。

#### Layer 1: 现状分析维度映射

**位置**: `src/core/dimension_mapping.py`

```python
ANALYSIS_DIMENSION_NAMES = {
    "location": "区位分析",
    "socio_economic": "社会经济分析",
    "villager_wishes": "村民意愿与诉求分析",
    "superior_planning": "上位规划与政策导向分析",
    "natural_environment": "自然环境分析",
    "land_use": "土地利用分析",
    "traffic": "道路交通分析",
    "public_services": "公共服务设施分析",
    "infrastructure": "基础设施分析",
    "ecological_green": "生态绿地分析",
    "architecture": "建筑分析",
    "historical_cultural": "历史文化分析"
}
```

**数据结构**:
```python
# 内部存储（英文键名）
analysis_dimension_reports = {
    "location": "区位分析内容...",
    "socio_economic": "社会经济分析内容...",
    ...
}

# 显示时使用映射
for key, content in analysis_dimension_reports.items():
    display_name = ANALYSIS_DIMENSION_NAMES[key]  # "区位分析"
    print(f"## {display_name}\n\n{content}")
```

---

#### Layer 2: 规划思路维度映射

```python
CONCEPT_DIMENSION_NAMES = {
    "resource_endowment": "资源禀赋分析",
    "planning_positioning": "规划定位分析",
    "development_goals": "发展目标分析",
    "planning_strategies": "规划策略分析"
}
```

---

#### Layer 3: 详细规划维度映射

```python
DETAILED_DIMENSION_NAMES = {
    "industry": "产业规划",
    "spatial_structure": "空间结构规划",
    "land_use_planning": "土地利用规划",
    "settlement_planning": "聚落体系规划",
    "traffic": "综合交通规划",
    "public_service": "公共服务设施规划",
    "infrastructure": "基础设施规划",
    "ecological": "生态保护与修复",
    "disaster_prevention": "防灾减灾规划",
    "heritage": "历史文化遗产保护",
    "landscape": "村庄风貌引导",
    "project_bank": "建设项目库"
}
```

---

### 为什么使用英文键名？

1. **代码一致性**: 英文键名避免了中文编码问题
2. **API 友好**: JSON 格式更规范
3. **类型安全**: 避免键名拼写错误
4. **国际化**: 便于未来支持多语言

---

### 依赖关系配置

**位置**: `src/core/dimension_mapping.py`

#### FULL_DEPENDENCY_CHAIN

**定义**: 详细规划维度的完整依赖链

**数据结构**:

```python
FULL_DEPENDENCY_CHAIN = {
    "industry": {
        "layer1_analyses": ["socio_economic", "land_use"],
        "layer2_concepts": ["resource_endowment", "development_goals"],
        "wave": 1,
        "depends_on_detailed": []
    },
    "spatial_structure": {
        "layer1_analyses": [
            "land_use", "superior_planning",
            "socio_economic", "natural_environment"
        ],
        "layer2_concepts": ["planning_positioning", "planning_strategies"],
        "wave": 1,
        "depends_on_detailed": []
    },
    # ... (其他维度)
}
```

**代码位置**: `dimension_mapping.py:38-200`

---

#### STATE_FILTER_MAP

**定义**: 状态筛选映射（优化 LLM 调用）

**功能**: 为每个规划维度指定需要的状态字段

**代码位置**: `dimension_mapping.py:250-400`

```python
STATE_FILTER_MAP = {
    "industry": {
        "layer1": ["socio_economic", "land_use"],
        "layer2": ["resource_endowment", "development_goals"]
    },
    "spatial_structure": {
        "layer1": ["land_use", "superior_planning", "socio_economic"],
        "layer2": ["planning_positioning", "planning_strategies"]
    },
    # ... (其他维度)
}
```

---

### 状态筛选优化

**位置**: `src/utils/state_filter.py`

**功能**: 根据依赖关系过滤状态，减少 LLM 上下文

**优势**:
- 🎯 **精准传递**：每个维度只接收其依赖的相关维度数据
- 💰 **降低成本**：大幅减少 LLM token 消耗（可节省 40-60%）
- ⚡ **提升速度**：减少上下文传输和处理时间
- 🎨 **提高质量**：专注相关信息，减少干扰

**代码**: `state_filter.py:20-80`

```python
def filter_state_for_dimension(
    state: Dict[str, Any],
    dimension_key: str
) -> Dict[str, Any]:
    """为特定维度筛选状态"""

    # 获取依赖配置
    config = FULL_DEPENDENCY_CHAIN.get(dimension_key, {})
    layer1_keys = config.get("layer1_analyses", [])
    layer2_keys = config.get("layer2_concepts", [])

    # 筛选维度报告（使用完整字段名，键名为英文）
    filtered_dimension_reports = {
        k: v for k, v in state.get("analysis_dimension_reports", {}).items()
        if k in layer1_keys
    }

    filtered_concept_reports = {
        k: v for k, v in state.get("concept_dimension_reports", {}).items()
        if k in layer2_keys
    }

    return {
        "analysis_dimension_reports": filtered_dimension_reports,
        "concept_dimension_reports": filtered_concept_reports,
        # ... 其他字段
    }
```

**示例对比**:

**不使用状态筛选**（传递所有维度）:
```
产业规划接收:
- 12个现状分析维度（约 36,000 tokens）
- 4个规划思路维度（约 12,000 tokens）
- 总计: ~48,000 tokens
```

**使用状态筛选**（只传递相关维度）:
```
产业规划接收:
- 2个相关现状分析维度（社会经济、土地利用）（约 6,000 tokens）
- 2个相关规划思路维度（资源禀赋、发展目标）（约 6,000 tokens）
- 总计: ~12,000 tokens（节省 75%）
```

---

## 工具和适配器

### CheckpointTool

**位置**: `src/tools/checkpoint_tool.py`

**功能**: 检查点管理

#### 保存检查点

```python
def save(
    self,
    state: Dict[str, Any],
    layer: int,
    description: str
) -> Dict[str, Any]:
    """保存检查点"""
    checkpoint_id = f"checkpoint_{self.checkpoint_count:03d}_layer{layer}_completed"

    checkpoint_data = {
        "checkpoint_id": checkpoint_id,
        "timestamp": datetime.now().isoformat(),
        "layer": layer,
        "description": description,
        "metadata": {
            "project_name": self.project_name,
            "layer": layer,
            "description": description
        },
        "state": self._serialize_state(state)
    }

    # 保存到文件
    checkpoint_file = self.checkpoint_dir / f"{checkpoint_id}.json"
    with open(checkpoint_file, 'w', encoding='utf-8') as f:
        json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)

    self.checkpoint_count += 1
    self.checkpoints.append(checkpoint_data)

    return {"success": True, "checkpoint_id": checkpoint_id}
```

**代码位置**: `checkpoint_tool.py:50-100`

---

#### 加载检查点

```python
def load(self, checkpoint_id: str) -> Dict[str, Any]:
    """加载检查点"""
    checkpoint_file = self.checkpoint_dir / f"{checkpoint_id}.json"

    if not checkpoint_file.exists():
        return {"success": False, "error": "检查点不存在"}

    with open(checkpoint_file, 'r', encoding='utf-8') as f:
        checkpoint_data = json.load(f)

    state = self._deserialize_state(checkpoint_data["state"])

    return {
        "success": True,
        "state": state,
        "checkpoint_data": checkpoint_data
    }
```

**代码位置**: `checkpoint_tool.py:102-140`

---

### RevisionTool

**位置**: `src/tools/revision_tool.py`

**功能**: 修复工具

#### 解析反馈

```python
def parse_feedback(self, feedback: str) -> Dict[str, Any]:
    """解析反馈，识别需要修复的维度"""
    # 使用 LLM 解析反馈
    prompt = f"""
    分析以下反馈，识别需要修复的维度：

    反馈内容：{feedback}

    可选维度：
    - industry (产业规划)
    - traffic (交通规划)
    - public_service (公共服务规划)
    - ...

    返回 JSON 格式：
    {{
        "dimensions": ["industry", "traffic"],
        "reason": "原因说明"
    }}
    """

    response = self.llm.invoke(prompt)
    return json.loads(response.content)
```

**代码位置**: `revision_tool.py:50-100`

---

#### 执行修复

```python
def revise_multiple(
    self,
    dimensions: List[str],
    state: Dict[str, Any],
    feedback: str
) -> Dict[str, Any]:
    """批量修复多个维度"""
    revised_results = {}

    for dimension in dimensions:
        result = self.revise_single(dimension, state, feedback)
        revised_results[dimension] = result

    return {
        "success": True,
        "revised_results": revised_results
    }
```

**代码位置**: `revision_tool.py:150-220`

---

### WebReviewTool

**位置**: `src/tools/web_review_tool.py`

**功能**: Web 审查工具，支持人工审查交互

#### 等待审查

```python
def wait_for_review(self, state: Dict[str, Any]) -> Dict[str, Any]:
    """等待人工审查"""
    checkpoint_id = state.get("last_checkpoint_id", "")

    review_data = {
        "checkpoint_id": checkpoint_id,
        "layer": state.get("current_layer", 1),
        "project_name": state.get("project_name", ""),
        "status": "waiting_for_review",
        "message": f"Layer {state.get('current_layer')} 已完成，等待审查"
    }

    return {
        "success": True,
        "need_human_review": True,
        "review_data": review_data
    }
```

**代码位置**: `web_review_tool.py:50-100`

---

### 专业适配器

**位置**: `src/tools/adapters/`

#### GISAnalysisAdapter

**功能**: GIS 空间分析

**支持的分析类型**:

- `land_use_analysis` - 土地利用分析
- `soil_analysis` - 土壤分析
- `hydrology_analysis` - 水文分析

**代码位置**: `adapters/gis_adapter.py:20-100`

```python
class GISAnalysisAdapter(BaseAdapter):
    """GIS 空间分析适配器"""

    def execute(self, analysis_type: str, **kwargs) -> AdapterResult:
        """执行 GIS 分析"""
        try:
            if analysis_type == "land_use_analysis":
                return self._analyze_land_use(**kwargs)
            elif analysis_type == "soil_analysis":
                return self._analyze_soil(**kwargs)
            else:
                return AdapterResult(
                    success=False,
                    error=f"不支持的分析类型: {analysis_type}"
                )
        except Exception as e:
            return AdapterResult(success=False, error=str(e))
```

---

#### NetworkAnalysisAdapter

**功能**: 网络分析

**支持的分析类型**:

- `connectivity_metrics` - 连通度指标
- `accessibility_analysis` - 可达性分析
- `centrality_analysis` - 中心性分析

**代码位置**: `adapters/network_adapter.py:20-120`

---

#### PopulationPredictionAdapter

**功能**: 人口预测

**支持的分析类型**:

- `population_forecast` - 人口预测
- `age_structure_analysis` - 年龄结构分析
- `labor_force_analysis` - 劳动力分析

**代码位置**: `adapters/population_adapter.py:20-80`

---

### 适配器配置

**默认配置**: `src/core/dimension_mapping.py:450-500`

```python
DEFAULT_ADAPTER_CONFIG = {
    "gis": {
        "enabled": False,
        "data_path": "data/gis/",
        "analyses": {
            "land_use": {
                "enabled": False,
                "required": False
            }
        }
    },
    "network": {
        "enabled": False,
        "data_path": "data/network/",
        "analyses": {
            "connectivity": {
                "enabled": False,
                "required": False
            }
        }
    },
    "population": {
        "enabled": False,
        "analyses": {
            "forecast": {
                "enabled": False,
                "required": False
            }
        }
    }
}
```

---

## LLM 集成

### LLM 工厂

**位置**: `src/core/llm_factory.py`

**功能**: 统一 LLM 创建接口

#### 支持的提供商

1. **ZhipuAI (智谱)**

   - 模型: `glm-4-flash`, `glm-4`, `glm-4-plus`
   - 自动检测: 模型名包含 `glm-`
2. **OpenAI**

   - 模型: `gpt-4o-mini`, `gpt-4o`, `gpt-4-turbo`
   - 自动检测: 模型名包含 `gpt-`
3. **DeepSeek**

   - 模型: `deepseek-chat`, `deepseek-coder`
   - 自动检测: 模型名包含 `deepseek-`

---

#### 创建 LLM

**代码**: `llm_factory.py:20-80`

```python
def create_llm(
    model: str = None,
    temperature: float = 0.7,
    max_tokens: int = None,
    streaming: bool = False
) -> BaseLLM:
    """创建 LLM 实例"""

    model = model or LLM_MODEL
    max_tokens = max_tokens or MAX_TOKENS

    # 自动检测提供商
    if model.startswith("glm-"):
        return _create_zhipuai_llm(model, temperature, max_tokens, streaming)
    elif model.startswith("gpt-"):
        return _create_openai_llm(model, temperature, max_tokens, streaming)
    elif model.startswith("deepseek-"):
        return _create_deepseek_llm(model, temperature, max_tokens, streaming)
    else:
        raise ValueError(f"不支持的模型: {model}")
```

---

#### ZhipuAI LLM

**代码**: `llm_factory.py:82-110`

```python
def _create_zhipuai_llm(
    model: str,
    temperature: float,
    max_tokens: int,
    streaming: bool
) -> BaseLLM:
    """创建 ZhipuAI LLM"""
    from langchain_community.chat_models import ChatZhipuAI

    api_key = os.getenv("ZHIPUAI_API_KEY")
    if not api_key:
        raise ValueError("未配置 ZHIPUAI_API_KEY")

    return ChatZhipuAI(
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming
    )
```

---

#### OpenAI LLM

**代码**: `llm_factory.py:112-140`

```python
def _create_openai_llm(
    model: str,
    temperature: float,
    max_tokens: int,
    streaming: bool
) -> BaseLLM:
    """创建 OpenAI LLM"""
    from langchain_openai import ChatOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("未配置 OPENAI_API_KEY")

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming
    )
```

---

### LangSmith 追踪

**位置**: `src/core/langsmith_integration.py`

**功能**: LangSmith 追踪和监控

#### 初始化

**代码**: `langsmith_integration.py:20-60`

```python
def get_langsmith_manager() -> LangSmithManager:
    """获取 LangSmith 管理器单例"""
    if _manager is None:
        return LangSmithManager()
    return _manager


class LangSmithManager:
    """LangSmith 追踪管理器"""

    def __init__(self):
        self.enabled = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
        self.api_key = os.getenv("LANGCHAIN_API_KEY", "")
        self.project = os.getenv("LANGCHAIN_PROJECT", "village-planning-agent")

        if self.enabled and self.api_key:
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = self.api_key
            os.environ["LANGCHAIN_PROJECT"] = self.project
```

---

#### 创建运行元数据

**代码**: `langsmith_integration.py:80-120`

```python
def create_run_metadata(
    self,
    project_name: str,
    extra_info: Dict[str, Any] = None
) -> Dict[str, Any]:
    """创建运行元数据"""
    metadata = {
        "project_name": project_name,
        "timestamp": datetime.now().isoformat(),
        "run_id": str(uuid.uuid4()),
    }

    if extra_info:
        metadata.update(extra_info)

    return metadata
```

---

### 流式输出

**位置**: `src/core/streaming.py`

**功能**: 流式执行图并输出事件

**Checkpointer 集成** ⭐ NEW:
```python
async def stream_graph_execution(
    graph: StateGraph,
    initial_state: Dict[str, Any],
    session_id: str,
    enable_streaming: bool = False,
    checkpointer=None,  # NEW: Accept checkpointer
    thread_id: str = None  # NEW: Accept thread_id for resume
) -> StreamingResponse:
    """
    Stream main graph execution events via SSE

    ⭐ NEW: 支持从 checkpointer 恢复执行
    """
    # Configure for resume if thread_id provided
    config = {}
    if thread_id and checkpointer:
        config = {"configurable": {"thread_id": thread_id}}

        # ⭐ FIX: 只传 config，不传 thread_id
        saved_state = await checkpointer.aget(config)
        if saved_state:
            # 从 checkpointer 恢复，不使用 initial_state
            stream_iterator = graph.astream(None, config, stream_mode="values")
        else:
            # 新执行，使用 initial_state
            stream_iterator = graph.astream(initial_state, config, stream_mode="values")
    else:
        # 没有 checkpointer，直接使用 initial_state
        config = {"configurable": {"thread_id": session_id}}
        stream_iterator = graph.astream(initial_state, config, stream_mode="values")
```

**流状态管理** ⭐ NEW:
```python
# 暂停时设置流状态
if event.get("pause_after_step"):
    try:
        from backend.api.planning import _stream_states
        _stream_states[session_id] = "paused"
    except ImportError:
        logger.warning("[Streaming] Could not import _stream_states")

    yield _format_sse_event("pause", {...})
    yield _format_sse_event("stream_paused", {...})  # ⭐ NEW: 通知前端关闭连接
    break  # ⭐ 退出流循环

# 完成时设置流状态
if not initial_state.get("pause_after_step"):
    try:
        from backend.api.planning import _stream_states
        _stream_states[session_id] = "completed"
    except ImportError:
        logger.warning("[Streaming] Could not import _stream_states")

    yield _format_sse_event("completed", {...})
```

**代码**: `streaming.py:41-338`

```python
async def stream_graph_execution(
    graph: StateGraph,
    initial_state: Dict[str, Any],
    callback: Callable[[Dict[str, Any]], None]
) -> Dict[str, Any]:
    """流式执行图"""

    async for event in graph.astream(initial_state):
        # 调用回调函数
        if callback:
            callback(event)

        # 发送 SSE 事件
        yield f"data: {json.dumps(event)}\n\n"

    # 返回最终状态
    final_state = event
    yield f"event: done\ndata: {json.dumps(final_state)}\n\n"
```

---

## 数据流

### 状态传递

**主图 → 子图**:

```python
# 主图调用子图
result = call_analysis_subgraph(
    raw_data=state["village_data"],
    project_name=state["project_name"]
)

# 子图返回结果（英文键名）
# {"analysis_dimension_reports": {"location": "...", "socio_economic": "...", ...}, "success": True}

# 主图更新状态
dimension_reports = result.get("analysis_dimension_reports", {})
combined_report = generate_combined_report(dimension_reports)

return {
    "analysis_report": combined_report,  # 综合报告
    "analysis_dimension_reports": dimension_reports,  # 维度报告（英文键名）
    "layer_1_completed": True,
    "current_layer": 2
}
```

**维度报告键名示例**（Layer 1）:
```python
{
    "location": "区位分析内容...",
    "socio_economic": "社会经济分析内容...",
    "villager_wishes": "村民意愿分析内容...",
    "superior_planning": "上位规划分析内容...",
    "natural_environment": "自然环境分析内容...",
    "land_use": "土地利用分析内容...",
    "traffic": "道路交通分析内容...",
    "public_services": "公共服务分析内容...",
    "infrastructure": "基础设施分析内容...",
    "ecological_green": "生态绿地分析内容...",
    "architecture": "建筑分析内容...",
    "historical_cultural": "历史文化分析内容..."
}
```

---

### 黑板模式

**位置**: `src/utils/blackboard_manager.py`

**功能**: 共享数据和洞察

**代码**: `blackboard_manager.py:20-80`

```python
def get_blackboard() -> Dict[str, Any]:
    """获取黑板实例"""
    return {
        "raw_data_references": {},
        "tool_results": {},
        "shared_insights": []
    }


def add_insight(blackboard: Dict[str, Any], insight: Dict[str, Any]):
    """添加洞察到黑板"""
    blackboard["shared_insights"].append(insight)


def get_insights(blackboard: Dict[str, Any], category: str = None):
    """从黑板获取洞察"""
    insights = blackboard["shared_insights"]

    if category:
        return [i for i in insights if i.get("category") == category]

    return insights
```

---

## 最佳实践

### 1. 节点设计

- **单一职责**: 每个节点只负责一个功能
- **幂等性**: 节点应该是幂等的（重复执行结果相同）
- **错误处理**: 捕获异常并返回错误信息

### 2. 状态管理

- **不可变性**: 不要直接修改输入状态，返回新的状态字典
- **选择性更新**: 只更新需要改变的字段
- **类型安全**: 使用 TypedDict 定义状态结构

### 3. LLM 调用优化

- **状态筛选**: 使用 `STATE_FILTER_MAP` 减少上下文
- **提示工程**: 使用结构化提示模板
- **温度控制**: 分析任务使用低温度 (0.3-0.5)，生成任务使用中温度 (0.7-0.9)

### 4. 检查点管理

- **定期保存**: 在关键节点保存检查点
- **增量保存**: 只保存变化的状态
- **版本控制**: 使用计数器命名检查点

---

## 测试

### 单元测试

**示例**:

```python
def test_layer1_node():
    """测试 Layer 1 节点"""
    node = Layer1AnalysisNode()
    state = {
        "project_name": "测试村",
        "village_data": "测试数据...",
        "current_layer": 1
    }

    result = node(state)

    assert result["layer_1_completed"] == True
    assert "analysis_report" in result
    assert result["current_layer"] == 2
```

---

### 集成测试

**示例**:

```python
def test_main_graph():
    """测试主图"""
    graph = create_village_planning_graph()
    initial_state = {
        "project_name": "测试村",
        "village_data": "测试数据...",
        "current_layer": 1,
        "step_mode": False
    }

    final_state = graph.invoke(initial_state)

    assert final_state["layer_1_completed"] == True
    assert final_state["layer_2_completed"] == True
    assert final_state["layer_3_completed"] == True
    assert "final_output" in final_state
```

---

## 常见问题

**Q: 如何添加新的分析维度？**
A:

1. 在 `dimension_mapping.py` 中添加维度定义
2. 在 `analysis_planners.py` 中创建对应规划器
3. 在 `analysis_subgraph.py` 中添加节点

**Q: 如何修改依赖关系？**
A: 修改 `FULL_DEPENDENCY_CHAIN` 配置

**Q: 如何启用适配器？**
A: 在请求中设置 `enable_adapters=True` 并提供 `adapter_config`

---

## 最新改进 (2024-2025年) ⭐

### 0. Pause 事件去重机制 (2025-02-09) ⭐⭐⭐ NEW

**问题修复**: 修复审查面板重复显示和批准失败问题

**核心改动**: 后端添加 pause 事件去重，防止 stream iterator 产生重复事件

#### 后端函数调用关系

```
_execute_graph_in_background()  [backend/api/planning.py:200]
  │
  ├─> 初始化
  │   ├─> sent_pause_events = _sessions[session_id].setdefault("sent_pause_events", set())  [Line 266]
  │   ├─> logger.info(f"已发送的pause事件: {sent_pause_events}")  [Line 267]
  │   └─> 迭代 stream 事件
  │
  ├─> 检测 pause_after_step  [Line 324]
  │   ├─> current_layer = event.get("current_layer", 1)
  │   ├─> pause_event_key = f"pause_layer_{current_layer}"
  │   ├─> if pause_event_key not in sent_pause_events:  [Line 331] ⭐ 去重检查
  │   │   ├─> pause_event = {type: "pause", current_layer, checkpoint_id, reason, timestamp}
  │   │   ├─> events_list.append(pause_event)  [Line 339]
  │   │   ├─> sent_pause_events.add(pause_event_key)  [Line 342] ⭐ 标记已发送
  │   │   ├─> stream_paused_event = {type: "stream_paused", ...}
  │   │   ├─> events_list.append(stream_paused_event)  [Line 349]
  │   │   ├─> _stream_states[session_id] = "paused"  [Line 350]
  │   │   ├─> logger.info(f"✓ pause事件已添加到队列 (Layer {current_layer})")
  │   │   └─> return
  │   └─> else:
  │       ├─> logger.info(f"⚠️ 跳过重复的pause事件 (Layer {current_layer})")
  │       └─> return  [Line 362]
  │
  └─> 格式化并发送 SSE 事件
      └─> yield format_sse("pause", pause_event_data)
```

#### 批准流程清理

```
review_action()  [backend/api/planning.py:670]
  │
  ├─> 检查 action == "approve"  [Line 711]
  │   │
  │   ├─> 详细状态日志  [Lines 714-718]
  │   │   ├─> logger.info(f"  - review_id: {review_id}")
  │   │   ├─> logger.info(f"  - pause_after_step: {is_pause_mode}")
  │   │   ├─> logger.info(f"  - waiting_for_review: {is_review_mode}")
  │   │   └─> logger.info(f"  - current_layer: {initial_state.get('current_layer', 1)}")
  │   │
  │   ├─> 重置流状态
  │   │   └─> _stream_states[session_id] = "active"  [Line 721]
  │   │
  │   ├─> 清除暂停标志
  │   │   ├─> initial_state["waiting_for_review"] = False  [Line 728]
  │   │   ├─> initial_state["pause_after_step"] = False  [Line 729]
  │   │   ├─> initial_state["human_feedback"] = ""
  │   │   ├─> initial_state["__interrupt__"] = False
  │   │   └─> session["status"] = TaskStatus.running
  │   │
  │   ├─> 清除 pause 事件追踪  [Lines 735-737] ⭐
  │   │   └─> if "sent_pause_events" in _sessions[session_id]:
  │   │       └─> logger.info(f"清除pause事件追踪: {_sessions[session_id]['sent_pause_events']}")
  │   │
  │   └─> 恢复执行
  │       └─> return await _resume_graph_execution(session_id, initial_state)  [Line 748]
  │           ├─> checkpointer = _session_checkpointer[session_id]  [Line 437]
  │           ├─> _stream_states[session_id] = "active"  [Line 440]
  │           └─> asyncio.create_task(_execute_graph_in_background(...))  [Line 446]
```

#### 依赖关系

```python
# 后端内部依赖链
backend/api/planning.py
  ├─> src/orchestration/main_graph.py
  │   ├─> create_village_planning_graph()  # 创建主图
  │   ├─> VillagePlanningState  # 状态定义
  │   ├─> route_after_pause()  # 路由函数
  │   └─> layer_nodes.py  # Layer 节点
  │
  ├─> src/utils/output_manager.py
  │   └─> create_output_manager()  # 输出管理器
  │
  ├─> backend/services/rate_limiter.py
  │   └─> rate_limiter.is_allowed()  # 限流检查
  │
  ├─> backend/utils/logging.py
  │   └─> get_logger(__name__)  # 日志器
  │
  └─> 全局状态管理
      ├─> _sessions: Dict[str, Dict]  # 会话存储
      ├─> _active_executions: Dict[str, bool]  # 执行追踪
      ├─> _session_checkpointer: Dict[str, Any]  # 检查点存储
      └─> _stream_states: Dict[str, str]  # 流状态追踪
```

#### 与前端的关系

```
前端 ←→ 后端 通信流程

┌─────────────────────────────────────────────────────┐
│                    前端                          │
│  frontend/src/components/chat/ChatPanel.tsx         │
│  frontend/src/hooks/useTaskSSE.ts                   │
└─────────────────────────────────────────────────────┘
                    │
                    │ SSE
                    ↓
┌─────────────────────────────────────────────────────┐
│                    后端                          │
│  backend/api/planning.py                            │
│  ├─> _execute_graph_in_background()                 │
│  │   ├─> sent_pause_events (去重追踪)              │
│  │   └─> 检测 pause_after_step                      │
│  └─> review_action()                                │
│      └─> 清除 sent_pause_events                      │
└─────────────────────────────────────────────────────┘
                    │
                    ↓
┌─────────────────────────────────────────────────────┐
│                   Agent                          │
│  src/orchestration/main_graph.py                    │
│  src/nodes/layer_nodes.py                           │
│  src/planners/ (各类规划器)                          │
└─────────────────────────────────────────────────────┘
```

**关键改进**:
- ✅ 后端 pause 事件去重机制（与 layer_completed 事件去重一致）
- ✅ 批准时详细状态日志
- ✅ 清除 pause 事件追踪，为下一 layer 准备
- ✅ 防止 stream iterator 产生重复 pause 事件

**修复效果**:
- ✅ 每个 Layer 只发送一次 pause 事件
- ✅ 前端只会收到一次 pause 事件
- ✅ 批准后状态清理完整
- ✅ 顺畅的执行流程

---

### 1. 子图架构重构

**重要变更**: 删除汇总节点，简化子图执行流程

**改进前**:
```
initialize → 并行维度 → reduce_analyses → generate_final_report → END
```

**改进后**:
```
initialize → 并行维度 → END
```

**优势**:
- ✅ 更快的执行速度（减少不必要的汇总步骤）
- ✅ 更细粒度的控制（直接操作维度报告）
- ✅ 更灵活的组合（前端可按需组合维度内容）

### 2. RAG 系统集成

**新增**: 检索增强生成（RAG）支持

**功能**:
- 向量数据库存储村庄规划知识
- 语义相似度检索
- 上下文增强生成

**使用场景**:
- 历史规划方案参考
- 最佳实践推荐
- 政策法规查询

**集成方式**:
```python
from src.rag.vector_store import VectorStore

vector_store = VectorStore()
relevant_docs = vector_store.search(query, top_k=3)
context = "\n".join([doc.content for doc in relevant_docs])
```

### 3. 并行执行优化

**修复**: LangGraph Send 机制状态合并问题

**问题**: 并行任务创建隔离状态，字典无法自动合并

**解决方案**:
- 使用 `analyses` 列表（通过 `operator.add` 累积）
- 在包装函数中转换为英文键名字典
- 确保所有维度报告正确返回

**实现代码**:
```python
# 从 analyses 列表中提取维度报告
analyses = result.get("analyses", [])
dimension_reports = {}
for analysis in analyses:
    dimension_key = analysis.get("dimension_key")  # 英文键名
    analysis_result = analysis.get("analysis_result")
    if dimension_key and analysis_result:
        dimension_reports[dimension_key] = analysis_result

return {
    "analysis_dimension_reports": dimension_reports,
    "success": True
}
```

### 4. 状态筛选优化

**新增**: `STATE_FILTER_MAP` 配置

**功能**: 为每个规划维度指定需要的状态字段

**优势**:
- 🎯 **精准传递**：只传递相关维度数据
- 💰 **降低成本**：大幅减少 LLM token 消耗（可节省 40-60%）
- ⚡ **提升速度**：减少上下文传输和处理时间
- 🎨 **提高质量**：专注相关信息，减少干扰

**使用示例**:
```python
def filter_state_for_dimension(
    state: Dict[str, Any],
    dimension_key: str
) -> Dict[str, Any]:
    config = FULL_DEPENDENCY_CHAIN.get(dimension_key, {})
    layer1_keys = config.get("layer1_analyses", [])
    layer2_keys = config.get("layer2_concepts", [])

    # 筛选维度报告（使用英文键名）
    filtered_dimension_reports = {
        k: v for k, v in state.get("analysis_dimension_reports", {}).items()
        if k in layer1_keys
    }

    return {
        "analysis_dimension_reports": filtered_dimension_reports,
        # ...
    }
```

---

## 参考资源

- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [LangChain 文档](https://python.langchain.com/)
- [ZhipuAI 文档](https://open.bigmodel.cn/dev/api)
- [OpenAI 文档](https://platform.openai.com/docs)
- [项目 RAG 系统文档](../docs/RAG系统使用指南.md)
