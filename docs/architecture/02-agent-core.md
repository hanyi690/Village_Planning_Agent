# Agent核心架构

本文档详细说明 Router Agent 架构、StateGraph 设计和执行流程。

> **更新日期**: 2026-05-08
> **版本**: v2.0 (重组后架构)

## 目录

- [Router Agent架构](#router-agent架构)
- [StateGraph节点定义](#stategraph节点定义)
- [统一状态定义](#统一状态定义)
- [关键节点详解](#关键节点详解)
- [检查点机制](#检查点机制)

---

## Router Agent架构

### 中央路由模式

Router Agent 采用中央路由模式，使用单一 StateGraph 和单一状态定义：

```
[用户输入]
    │
    ▼
conversation_node (LLM: bind_tools)
    │ intent_router
    ├─► [闲聊/问答] END
    ├─► [工具调用] execute_tools
    └─► [推进规划] route_by_phase
                          │
                   [Send N 维度]
                          │
                          ▼
                  analyze_dimension
                          │
                          ▼
                  collect_results
                          │
               ┌──────────┴──────────┐
               ▼                      ▼
         advance_phase           conversation
```

### conversation_node

中央路由节点是 Router Agent 的核心：

```python
# backend/app/agent/nodes/conversation.py
async def conversation_node(state: UnifiedPlanningState) -> Dict[str, Any]:
    """
    中央路由节点（大脑）

    使用 LLM bind_tools 实现意图识别:
    - 普通对话：直接回复
    - 工具调用：返回 tool_calls
    - 推进规划：返回 AdvancePlanningIntent
    """
    messages = list(state.get("messages", []))
    phase = state.get("phase", PlanningPhase.INIT.value)

    # 构建系统提示
    system_prompt = _build_system_prompt(phase, project_name, config, reports)

    # 获取 LLM 并绑定工具
    llm = create_llm(model=LLM_MODEL, temperature=0.7)
    llm_with_tools = llm.bind_tools([ADVANCE_PLANNING_TOOL])

    # 调用 LLM
    response = await llm_with_tools.ainvoke([SystemMessage(content=system_prompt)] + messages)

    return {"messages": [response]}
```

### intent_router

根据最后一条消息决定下一步：

| 返回值 | 条件 | 下一步 |
|--------|------|--------|
| `"execute_tools"` | 存在工具调用（非AdvancePlanningIntent） | execute_tools节点 |
| `"route_planning"` | AdvancePlanningIntent 或 need_revision | 规划流程 |
| `END` | 普通对话 | 结束本轮 |

---

## StateGraph节点定义

### 节点一览表

| 节点名称 | 职责 | 入口条件 |
|----------|------|----------|
| `conversation` | 中央路由，LLM意图识别 | START入口 |
| `execute_tools` | 执行工具调用 | 工具调用意图 |
| `knowledge_preload` | 知识并行预加载 | 知识缓存为空 |
| `analyze_dimension` | 维度分析（Send分发） | 有待执行维度 |
| `emit_events` | 批量发送SSE事件 | 维度分析完成 |
| `collect_results` | 收集维度结果 | 维度执行完成 |
| `advance_phase` | 推进到下一阶段 | 层级完成 |

### 条件边路由

```python
# 入口：对话节点
builder.add_edge(START, "conversation")

# 意图路由
builder.add_conditional_edges("conversation", route_intent, {
    "execute_tools": "execute_tools",
    "route_planning": "route_planning",
    END: END
})

# 规划路由（Send API动态分发）
builder.add_conditional_edges("route_planning", route_planning, {
    "knowledge_preload": "knowledge_preload",
    "analyze_dimension": "analyze_dimension",
    "collect_results": "collect_results",
    "advance_phase": "advance_phase",
    END: END
})

# 维度分析 -> 发送事件 -> 收集结果
builder.add_edge("analyze_dimension", "emit_events")
builder.add_edge("emit_events", "collect_results")

# 收集结果 -> 检查完成
builder.add_conditional_edges("collect_results", check_completion, {
    "continue": "route_planning",
    "advance": "advance_phase",
    "complete": END,
    "pause": END
})
```

---

## 统一状态定义

### UnifiedPlanningState核心字段

```python
# backend/app/agent/state.py
class UnifiedPlanningState(TypedDict):
    # 核心驱动
    messages: Annotated[List[BaseMessage], add_messages]

    # 业务参数
    session_id: str
    project_name: str
    config: PlanningConfig

    # 执行进度
    phase: str                    # 当前阶段
    current_wave: int             # 当前波次
    reports: Dict                 # 维度报告
    completed_dimensions: Dict    # 已完成维度

    # Send API自动合并
    dimension_results: Annotated[List[Dict], operator.add]
    sse_events: Annotated[List[Dict], operator.add]

    # Step Mode
    step_mode: bool
    pause_after_step: bool
    previous_layer: int
```

### 自动合并机制

关键字段使用 `Annotated` + `operator.add` 实现自动合并：

```python
dimension_results: Annotated[List[Dict], operator.add]  # 多维度结果自动合并
sse_events: Annotated[List[Dict], operator.add]         # SSE事件自动合并
```

### 阶段枚举

```python
class PlanningPhase(Enum):
    INIT = "init"
    LAYER1 = "layer1"
    LAYER2 = "layer2"
    LAYER3 = "layer3"
    COMPLETED = "completed"
```

---

## 关键节点详解

### route_by_phase

规划路由节点，使用 Send API 实现维度并行分发：

```python
def route_by_phase(state: Dict[str, Any]) -> Union[List[Send], str]:
    """
    根据当前phase路由到维度分析

    Send API实现:
    - 返回 List[Send]：并行执行多个维度
    - 返回 str：跳转到指定节点或END
    """
    phase = state.get("phase")
    current_wave = state.get("current_wave", 1)
    layer = _phase_to_layer(phase)

    # INIT阶段推进到layer1
    if layer == 0:
        return "advance_phase"

    # 知识预加载检测
    if not knowledge_cache:
        return "knowledge_preload"

    # 层级路由（详见03-layer-dimension.md）
    # ...
```

详见维度路由机制：[03-layer-dimension.md#Wave波次机制](./03-layer-dimension.md#wave波次机制)

### analyze_dimension

维度分析节点，执行单个维度的规划分析：

```python
async def analyze_dimension(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    维度分析节点

    流程:
    1. 获取维度配置和工具绑定
    2. 构建Prompt（从缓存读取知识）
    3. 执行LLM调用
    4. 发送dimension_delta SSE事件
    5. 返回dimension_results和sse_events
    """
    dimension_key = state.get("dimension_key")

    # 流式执行
    result = await execute_dimension_analysis(state, streaming=True)

    return {
        "dimension_results": [{dimension_key: result}],
        "sse_events": [dimension_complete_event],
        "completed_dimensions": {layer: [dimension_key]}
    }
```

### collect_results

结果收集节点，检查层级完成状态：

```python
def check_completion(state: Dict[str, Any]) -> str:
    """
    检查完成状态并决定下一步

    Returns:
        "continue": 波次/维度推进后继续执行
        "advance": 推进到下一阶段
        "complete": 规划完成
        "pause": 暂停等待审查
    """
    phase = state.get("phase")
    completed = state.get("completed_dimensions")

    # 检查当前层是否全部完成
    if is_layer_complete(phase, completed):
        if is_last_layer(phase):
            return "complete"
        return "advance"

    # 检查是否需要暂停
    if state.get("pause_after_step"):
        return "pause"

    return "continue"
```

---

## 检查点机制

### Checkpoint持久化

LangGraph Checkpointer 自动持久化状态：

```python
# backend/app/database/engine.py
async def get_global_checkpointer():
    """
    获取全局 AsyncSqliteSaver 实例（单例模式）

    使用单例模式避免重复连接创建和setup()调用
    """
    conn = await aiosqlite.connect(get_db_path(), check_same_thread=False)
    await conn.execute("PRAGMA journal_mode=WAL")
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    return checkpointer
```

### 双模式Stream

```python
async for event in graph.astream(state, stream_mode=["values", "checkpoints"]):
    # values: 状态变化事件
    # checkpoints: 持久化事件
```

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 主图定义 | `backend/app/agent/graph.py` |
| 状态定义 | `backend/app/agent/state.py` |
| 意图路由 | `backend/app/agent/routing.py` |
| 对话节点 | `backend/app/agent/nodes/conversation.py` |
| 工具节点 | `backend/app/agent/nodes/tools.py` |
| 分析节点 | `backend/app/agent/nodes/analysis.py` |
| 维度配置 | `backend/app/config/phases.yaml` |

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [03-layer-dimension](./03-layer-dimension.md) - 28维度配置、Wave机制
- [04-backend-api](./04-backend-api.md) - API与Agent交互
- [06-tool-system](./06-tool-system.md) - Tool-Dimension绑定
- [terminology](./terminology.md) - Agent术语定义