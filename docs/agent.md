# 智能体架构文档

> **相关文档**: [系统架构总览](architecture.md) | [前端实现](frontend.md) | [工具系统](tool-system.md)
>
> LangGraph Router Agent 架构 - Send API 并行执行 + Checkpoint 完整记录

## 版本信息

- **版本**: 3.0.0
- **架构**: Router Agent (Send API)
- **更新**: 单一图、单一 State，消灭子图嵌套

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                   conversation_node (中央路由/大脑)                  │
│  LLM bind_tools → 意图识别 → 路由决策                                │
└─────────────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   闲聊/问答   │    │   工具调用    │    │   推进规划    │
│   → END      │    │ execute_tools │    │ route_by_phase│
└──────────────┘    └──────────────┘    └──────────────┘
                                              │
                              ┌───────────────┼───────────────┐
                              ▼               ▼               ▼
                        ┌─────────┐     ┌─────────┐     ┌─────────┐
                        │Send[N]  │     │ revision│     │knowledge│
                        │维度并行  │     │ 修订节点│     │preload  │
                        └─────────┘     └─────────┘     └─────────┘
                              │
                              ▼
                      analyze_dimension
                              │
                              ▼
                      collect_results
                              │
                              ▼
                      check_completion
                              │
                   ┌──────────┴──────────┐
                   ▼                      ▼
             advance_phase           conversation
                   │                      │
                   └──────────────────────┘
```

## Phase 和 Layer 对应关系

| Phase | 含义 | `_phase_to_layer()` 返回值 | 执行动作 |
|-------|------|---------------------------|---------|
| `init` | 初始状态，未开始 | `0` | 推进到 `layer1` |
| `layer1` | 正在执行 Layer 1 | `1` | 执行 Layer 1 维度 |
| `layer2` | 正在执行 Layer 2 | `2` | 执行 Layer 2 维度 |
| `layer3` | 正在执行 Layer 3 | `3` | 执行 Layer 3 维度 |
| `completed` | 规划完成 | `None` | 结束 |

### 状态流设计

```
INIT (phase="init", layer=0)
  → route_by_phase 返回 "advance_phase"
  → phase 推进到 "layer1"

Layer 1 执行 (phase="layer1", layer=1)
  → 执行维度分析
  → 完成后设置 pause_after_step=True, phase 保持 "layer1"

暂停状态 (pause_after_step=True)
  → check_phase_completion 返回 "pause"
  → 图结束等待审查

恢复执行 (用户批准)
  → approve 推进 phase 到 "layer2"
  → route_by_phase 发送 layer_started
  → 开始 Layer 2 维度分析
```

## 执行流程

```
[用户输入]
    │
    ▼
conversation_node (LLM: bind_tools)
    │ intent_router
    ├─► [闲聊/问答] END
    ├─► [工具调用] execute_tools → END
    └─► [AdvancePlanningIntent] route_by_phase
                                    │
                             [知识预加载] (首次)
                                    │
                             ┌──────┴──────┐
                             ▼             ▼
                    [Send N 维度]      [revision]
                    (并行执行)         (修订模式)
                             │
                             ▼
                    analyze_dimension ×N
                    │
                    ├─► Layer 1: 12维度并行
                    ├─► Layer 2: 4波次顺序
                    └─► Layer 3: 2波次顺序
                             │
                             ▼
                    collect_results
                             │
                             ▼
                    emit_sse_events
                             │
                             ▼
                    check_phase_completion
                             │
                   ┌─────────┴─────────┐
                   ▼                   ▼
             [阶段完成]           [暂停审查]
             advance_phase        pause_after_step
                   │                   │
                   └───────────────────┘
                           │
                           ▼
                     conversation_node
```

## Router Agent 架构特性

### 1. 单一 State 消灭双写

```python
class UnifiedPlanningState(TypedDict):
    """统一规划状态 - Router Agent 架构核心"""

    # 核心驱动
    messages: Annotated[List[BaseMessage], add_messages]

    # 业务参数
    session_id: str
    project_name: str
    config: PlanningConfig

    # 执行进度
    phase: str                          # init(0)/layer1(1)/layer2(2)/layer3(3)/completed
    current_wave: int                   # 当前波次
    reports: Dict[str, Dict[str, str]]  # {layer1: {dim: report}}
    completed_dimensions: Dict[str, List[str]]  # {layer1: [dim1, dim2]}

    # Send API 自动合并
    dimension_results: Annotated[List[Dict], operator.add]
    sse_events: Annotated[List[Dict], operator.add]

    # 交互控制
    pending_review: bool
    need_revision: bool
    revision_target_dimensions: List[str]
    review_feedback: str

    # Step Mode 控制
    step_mode: bool              # 是否启用分步执行
    pause_after_step: bool       # 层级完成后暂停标志
    previous_layer: int          # 刚完成的层级编号

    # 元数据
    metadata: Dict[str, Any]
```

### 2. Send API 并行执行

```python
def route_by_phase(state: Dict[str, Any]) -> Union[List[Send], str]:
    """根据当前 phase 路由到对应的维度分析"""

    phase = state.get("phase", "init")

    # 暂停状态优先检测
    if state.get("pause_after_step"):
        return END

    # 知识预加载检测
    if not knowledge_cache:
        return "knowledge_preload"

    # 需要修订
    if state.get("need_revision"):
        return "revision"

    # 已完成
    if phase == "completed":
        return END

    # 返回 Send 列表并行执行
    pending = get_pending_dimensions(state)
    return [Send("analyze_dimension", create_dimension_state(d, state))
            for d in pending]
```

### 3. 意图路由 (Intent Router)

```python
def intent_router(state: Dict[str, Any]) -> str:
    """根据最后一条消息决定下一步"""

    last_msg = messages[-1]

    # 检查工具调用
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tool_call in last_msg.tool_calls:
            if tool_call.get("name") == "AdvancePlanningIntent":
                return "route_planning"  # 推进规划
        return "execute_tools"  # 其他工具

    # 检查修订需求
    if state.get("need_revision"):
        return "route_planning"

    # 普通对话，结束本轮
    return END
```

## 节点定义

### conversation_node (中央路由)

```python
async def conversation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    中央路由节点 - LLM 作为大脑

    功能：
    1. 识别用户意图（闲聊/问答/工具调用/推进规划）
    2. 绑定工具：AdvancePlanningIntent, 其他工具
    3. 生成回复
    """
    llm = create_llm()
    llm_with_tools = llm.bind_tools([AdvancePlanningIntent, ...])

    response = await llm_with_tools.ainvoke(state["messages"])

    return {"messages": [response]}
```

### analyze_dimension (维度分析)

```python
async def analyze_dimension_for_send(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    维度分析节点 - Send API 调用

    特性：
    1. 从 knowledge_cache 读取预加载知识
    2. 使用专业 Prompt 模板
    3. 流式输出 SSE 事件
    """
    dimension_key = state["dimension_key"]
    knowledge = state["config"]["knowledge_cache"].get(dimension_key, "")

    # 构建 Prompt
    prompt = build_dimension_prompt(dimension_key, state, knowledge)

    # 流式生成
    async for chunk in llm.astream(prompt):
        yield {"sse_events": [{
            "type": "dimension_delta",
            "dimension_key": dimension_key,
            "delta": chunk
        }]}

    # 返回结果
    return {
        "dimension_results": [{dimension_key: full_content}],
        "completed_dimensions": {layer: [dimension_key]}
    }
```

### knowledge_preload_node (知识预加载)

```python
async def knowledge_preload_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    知识预加载节点 - 批量 RAG 检索

    流程：
    1. 确定当前层级的维度列表
    2. 批量检索相关知识
    3. 缓存到 knowledge_cache
    """
    layer = _phase_to_layer(state["phase"])
    dimensions = get_layer_dimensions(layer)

    knowledge_cache = {}
    for dim_key in dimensions:
        result = await search_knowledge(dim_name + task_description)
        knowledge_cache[dim_key] = result

    return {"config": {"knowledge_cache": knowledge_cache}}
```

## 维度执行模式

### Layer 1: 现状分析 (12维度并行)

```
route_by_phase
    │
    └─► [Send ×12] → analyze_dimension ×12 (并行)
                           │
                           ▼
                    collect_results
                           │
                           ▼
                    check_completion → advance_phase (Layer 2)
```

### Layer 2: 规划思路 (4波次顺序)

```
Wave 1: resource_endowment (无依赖)
    │
    ▼
Wave 2: planning_positioning (依赖 Wave 1)
    │
    ▼
Wave 3: development_goals (依赖 Wave 1, 2)
    │
    ▼
Wave 4: planning_strategies (依赖 Wave 1, 2, 3)
```

### Layer 3: 详细规划 (2波次顺序)

```
Wave 1: 11维度并行 (industry, spatial_structure, ...)
    │
    └─► project_shadow_cache (项目提取)
    │
    ▼
Wave 2: project_bank (依赖 Wave 1 全部完成)
    │
    └─► 使用 shadow_cache 替代完整报告 (~90% token 节省)
```

## 目录结构

```
src/
├── agent.py                    # 对外接口 (废弃，使用 LangGraph 直接调用)
├── core/
│   ├── config.py               # 全局配置
│   ├── llm_factory.py          # LLM工厂
│   └── langsmith_integration.py # LangSmith 集成
├── config/
│   └── dimension_metadata.py   # 维度元数据 (28维度权威来源)
├── orchestration/
│   ├── main_graph.py           # 主图编排 (Router Agent)
│   ├── state.py                # UnifiedPlanningState 定义
│   ├── routing.py              # intent_router + route_by_phase
│   └── nodes/
│       ├── dimension_node.py   # analyze_dimension + knowledge_preload
│       └── revision_node.py    # 维度修复节点
├── subgraphs/                  # ⚠️ 已废弃，保留 Prompt 模板
│   ├── analysis_prompts.py     # Layer 1 提示词 (12维度)
│   ├── concept_prompts.py      # Layer 2 提示词 (4维度)
│   └── detailed_plan_prompts.py # Layer 3 提示词 (12维度)
├── tools/
│   ├── registry.py             # 工具注册表
│   ├── tools.py                # 工具定义
│   └── project_extractor.py    # 项目提取工具
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
| `src/orchestration/main_graph.py` | Router Agent 主图编排 |
| `src/orchestration/state.py` | UnifiedPlanningState 定义 |
| `src/orchestration/routing.py` | 意图路由 + 规划路由 |
| `src/orchestration/nodes/dimension_node.py` | 维度分析节点 + 知识预加载 |
| `src/orchestration/nodes/revision_node.py` | 维度修复节点 |
| `src/subgraphs/analysis_prompts.py` | Layer 1 提示词模板 |
| `src/subgraphs/concept_prompts.py` | Layer 2 提示词模板 |
| `src/subgraphs/detailed_plan_prompts.py` | Layer 3 提示词模板 |
| `src/config/dimension_metadata.py` | 28维度配置 |
| `src/tools/registry.py` | 工具注册表 |
| `src/rag/core/tools.py` | RAG 检索工具 |

## 维度配置

### 维度数量

| 层级 | 数量 | 执行模式 |
|------|------|---------|
| Layer 1 | 12 | 并行 (Send API) |
| Layer 2 | 4 | 波次顺序 |
| Layer 3 | 12 | 波次顺序 |

### Layer 1 维度列表

`location, socio_economic, villager_wishes, superior_planning, natural_environment, land_use, traffic, public_services, infrastructure, ecological_green, architecture, historical_culture`

### Layer 2 维度列表

`resource_endowment, planning_positioning, development_goals, planning_strategies`

### Layer 3 维度列表

`industry, spatial_structure, land_use_planning, settlement_planning, traffic_planning, public_service, infrastructure_planning, ecological, disaster_prevention, heritage, landscape, project_bank`

## 工具系统

### AdvancePlanningIntent 工具

```python
ADVANCE_PLANNING_TOOL = {
    "type": "function",
    "function": {
        "name": "AdvancePlanningIntent",
        "description": "用户希望推进规划流程时调用",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["start", "approve", "reject", "rollback"]}
            }
        }
    }
}
```

### 工具注册

```python
@ToolRegistry.register("population_model_v1")
def calculate_population(context: Dict[str, Any]) -> str:
    # 人口预测模型
    ...
```

## RAG 知识检索

### 预加载模式

```python
# knowledge_preload_node 在层级开始前批量检索
knowledge_cache = {}
for dim_key in dimensions:
    result = await search_knowledge(dim_name + task_description)
    knowledge_cache[dim_key] = result

# 后续维度节点从缓存读取
knowledge = state["config"]["knowledge_cache"].get(dimension_key)
```

### 元数据过滤

```python
result = check_technical_indicators.invoke({
    "query": "道路宽度标准",
    "dimension": "traffic",
    "terrain": "mountain",
    "doc_type": "standard"
})
```

## 流式输出系统

### SSE 事件类型

| 事件类型 | 数据内容 | 触发时机 |
|---------|---------|---------|
| `connected` | `{session_id}` | SSE 连接建立 |
| `layer_started` | `{layer, name}` | 层级开始 |
| `dimension_delta` | `{dimension_key, delta}` | 维度流式内容 |
| `dimension_complete` | `{dimension_key, full_content}` | 维度完成 |
| `layer_completed` | `{layer, version}` | 层级完成 |
| `pause` | `{layer}` | 暂停审查 |
| `error` | `{message}` | 错误 |

### Send API 自动合并

```python
# dimension_results 和 sse_events 使用 operator.add 自动合并
dimension_results: Annotated[List[Dict], operator.add]
sse_events: Annotated[List[Dict], operator.add]

# 每次 Send 返回的结果自动追加到列表
return {
    "dimension_results": [{dimension_key: content}],
    "sse_events": [event1, event2]
}
```

---

## 项目库影子缓存机制

### 概述

项目库（project_bank）维度依赖所有其他 Layer 3 维度的输出。为避免将完整的 11 份报告作为输入，系统实现了影子缓存优化：

```
原始方案: 11 份完整报告 → project_bank LLM（~50000 字符输入）
优化方案: 影子缓存 → project_bank LLM（~5000 字符输入）
节省效果: 约 90% token 减少
```

### 数据流

```
Wave 1 Dimensions (并行)
    ↓
completed_dimension_reports
    ↓
reduce_dimension_plans() → 项目提取
    ↓
project_shadow_cache: {dim: [{name, scale, phase}]}
    ↓
Wave 2: project_bank
    ↓
format_shadow_cache_for_prompt() → filtered_detail
```

---

## 架构演进历史

| 版本 | 日期 | 变化 |
|------|------|------|
| v3.1 | 2026-04-05 | Phase 和 Layer 关系修正：init 返回 0，新增 advance_phase/pause 路由 |
| v3.0 | 2026-04-05 | Router Agent 架构，Send API 并行执行 |
| v2.2 | 2026-03-xx | Prompt 模板系统集成 |
| v2.0 | 2026-02-xx | 子图架构 (已废弃) |