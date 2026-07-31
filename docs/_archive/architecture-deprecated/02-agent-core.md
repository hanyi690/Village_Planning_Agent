> [!WARNING] **DEPRECATED — 历史参考**
> 模块路径、版本号已过时。当前 Agent 架构以 [README.md](../README.md) 为准。
> 保留技术决策和 StateGraph 设计演进历史。

# Agent 核心架构

本文档详细说明 Router Agent 架构、StateGraph 设计和执行流程。

> **更新日期**: 2026-07-08
> **版本**: v4.0 (LangGraph 1.2 interrupt/resume)

## 目录

- [架构概览](#架构概览)
- [StateGraph 定义](#stategraph-定义)
- [状态定义](#状态定义)
- [路由逻辑](#路由逻辑)
- [关键节点详解](#关键节点详解)
- [检查点机制](#检查点机制)
- [关键文件路径](#关键文件路径)

---

## 架构概览

### 5 节点图

Router Agent 采用 5 个核心节点 + Send API 动态分发 + interrupt() 审批：

```
              START
                │
                ▼
         ┌─────────────┐◄──────────────────┐┌──────────────┐
    ┌───│ conversation │◄──────────────────││  gis_agent   │
    │   └──────┬──────┘                    │└──────┬───────┘
    │          │ after_conversation         │       │
    │   ┌──────┼──────┬──────────┐         │       │
    │   ▼      ▼      ▼          ▼         │       │
    │  exec   Send[N] END       gis_agent  │       │
    │  _tools   │     (闲聊)               │       │
    │   │       ▼                          │       │
    │   │  analyze_dimension               │       │
    │   │       │                          │       │
    │   │       ▼                          │       │
    │   │  layer_completion_check          │       │
    │   │       │ after_analysis           │       │
    │   │  ┌────┼────┬──────────┐          │       │
    │   │  ▼    ▼    ▼          ▼          │       │
    │   │ Send END  conversation  END      │       │
    │   │ (继续)(完成)(审批恢复) (完成)      │       │
    │   └────┼─────────────────────────────┘       │
    └────────┘                                     │
              interrupt() → Command(resume=...) ───┘
```

**5 节点一览**：

| 节点 | 职责 | 类型 |
|------|------|------|
| `conversation` | 中央路由，LLM 意图识别 | 普通节点 |
| `execute_tools` | 执行工具调用 | 普通节点 |
| `analyze_dimension` | 维度分析（Send API 动态分发） | Send 目标节点 |
| `layer_completion_check` | 层级完成检查 + interrupt() 审批 | 普通节点 |
| `gis_agent` | GIS 空间布局 ReAct Agent | 普通节点 (error_handler) |

### 设计原则

1. **单一路由入口**: `conversation` 节点处理所有用户输入
2. **Send API 并行**: 维度分析通过 `Send("analyze_dimension", ...)` 动态分发
3. **interrupt 审批**: `layer_completion_check` 使用 `interrupt()` 实现官方 human-in-the-loop
4. **路由纯函数**: `after_conversation` / `after_analysis` 是纯路由函数（无 Runtime 参数）
5. **依赖驱动**: 同层依赖检查决定分发顺序

---

## StateGraph 定义

### 图构建

```python
# backend/app/agent/graph.py
def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图（5节点）"""
    builder = StateGraph(AgentState)

    # 5 个节点
    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("analyze_dimension", analyze_dimension_node)
    builder.add_node("layer_completion_check", layer_completion_check)
    builder.add_node("gis_agent", gis_agent_node, error_handler=_gis_error_handler)

    # 边定义
    builder.add_edge(START, "conversation")
    builder.add_conditional_edges("conversation", after_conversation, {
        "execute_tools": "execute_tools",
        "analyze_dimension": "analyze_dimension",
        "gis_agent": "gis_agent",
        END: END
    })
    builder.add_edge("execute_tools", "conversation")
    builder.add_edge("gis_agent", "conversation")
    builder.add_edge("analyze_dimension", "layer_completion_check")
    builder.add_conditional_edges("layer_completion_check", after_analysis, {
        "analyze_dimension": "analyze_dimension",
        "conversation": "conversation",
        END: END
    })

    return builder.compile(checkpointer=checkpointer)
```

### 执行流程

```
1. START → conversation (LLM 处理用户输入)
2. after_conversation 决定下一步:
   - tool_calls(GIS) → gis_agent → conversation
   - tool_calls(其他) → execute_tools → conversation
   - AdvancePlanningIntent → Send[N] → analyze_dimension × N
   - 级联修订(feedback) → Send[N] → analyze_dimension × N
   - 普通对话/无操作 → END
3. analyze_dimension 完成后 → layer_completion_check
4. after_analysis 决定:
   - 层级未完成 → Send[N] → 继续 analyze_dimension
   - 层级完成 + step_mode → interrupt() → END (等待审批)
   - 层级完成 + 自动 → 推进下一层 → Send[N]
   - 全部完成 → END
5. 审批恢复: Command(resume={"action": "approve/reject"}) → 重新执行 layer_completion_check
```

---

## 状态定义

### AgentState

```python
# backend/app/agent/state.py
class AgentState(TypedDict, total=False):
    """核心状态"""
    # 消息流
    messages: Annotated[List[BaseMessage], add_messages]

    # 会话标识
    session_id: str
    project_name: str

    # 执行进度
    phase: str                    # 当前阶段 (init/layer1/layer2/layer3/completed)
    current_wave: int             # 当前波次
    completed_dimensions: Annotated[Dict[str, List[str]], _merge_dict_of_lists]

    # 配置与交互
    config: Annotated[Dict[str, Any], _merge_config]
    feedback: Optional[str]       # 级联修订反馈

    # Send API 注入
    dimension_key: Optional[str]  # 当前维度标识（Send API 动态注入）
    image_ids: List[str]          # 图片引用
    metadata: Dict[str, Any]      # 元数据

    # 执行控制
    step_mode: bool               # 分步执行模式（interrupt 审批）
    previous_layer: int           # 前一个完成的层级

    # 级联修订
    need_revision: bool
    revision_target_dimensions: List[str]
    human_feedback: str
    is_revision: Annotated[bool, _merge_is_revision]
    revision_impact_tree: Annotated[Optional[Dict[int, List[str]]], _preserve_impact_tree]
    revision_completed_dims: Annotated[Dict[int, List[str]], _merge_revision_completed]
    revision_feedback: Optional[str]
    last_revised_dimensions: List[str]

    # 性能优化
    pending_reports: Annotated[List[Dict], _replace_or_merge_lists]  # 批量写入缓冲
    layer_char_counts: Annotated[Dict[int, int], _merge_layer_char_counts]

    # GIS
    gis_layout_configs: Annotated[List[Dict], _replace_or_merge_lists]  # GIS 图层配置
    user_uploaded_data: Annotated[Dict[str, Dict], _merge_dict_of_dicts]  # 用户上传 GIS 数据

    # P0 数据流闭环
    _landuse_metrics: Annotated[Dict[str, float], _merge_dict_of_dicts]  # L1 现状用地指标
    intent_targets: Annotated[Dict[str, float], _merge_dict_of_dicts]    # L2 规划目标面积
```

### 并行合并函数

状态使用 Annotated 类型配合合并函数，实现 Send API 并行执行后的状态合并：

```python
def _merge_dict_of_lists(a: Dict[str, List], b: Dict[str, List]) -> Dict[str, List]:
    """合并两个 {key: list} 字典，对同 key 的 list 去重拼接"""
    # O(n) dedup via dict.fromkeys, preserves order
    ...

def _replace_or_merge_lists(a: List, b: List) -> List:
    """b=[] 时清空缓冲，否则合并（用于 pending_reports, gis_layout_configs）"""
    if b == []:
        return []
    return a + b
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

## 路由逻辑

### after_conversation - 对话后路由

```python
# backend/app/agent/routing.py
def after_conversation(state: Dict[str, Any]) -> Union[str, List[Send]]:
    """
    对话后路由 - 新架构核心

    处理：
    1. 级联修订：feedback 存在时计算影响树
    2. 推进意图：AdvancePlanningIntent -> 分发维度
    3. GIS 分析：GISAnalysis -> gis_agent
    4. 工具执行：其他工具 -> execute_tools
    5. 普通对话：END
    """
    # 1. 级联修订
    feedback = state.get("feedback") or state.get("human_feedback")
    need_revision = state.get("need_revision", False)

    if need_revision and feedback:
        target_dims = state.get("revision_target_dimensions", [])
        # 计算影响树
        downstream_tree = get_impact_tree_compat(target_dim)
        # 仅分发 Wave 0（目标维度）
        return [Send("analyze_dimension", {...}) for d in wave0_dims]

    # 2. 推进意图检测
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            if name == "AdvancePlanningIntent":
                return _dispatch_current(state)
            if name == "GISAnalysis":
                return "gis_agent"

    return END
```

### after_analysis - 分析后路由

```python
def after_analysis(state: Dict[str, Any]) -> Union[str, List[Send]]:
    """
    分析后路由 - 波次推进逻辑

    处理：
    1. completed -> END
    2. interrupt 暂停 -> END（等待审批，由 LangGraph 自动处理）
    3. 待处理维度 -> Send 分发（检查同层依赖）
    """
    # 级联修订：使用依赖检查逻辑
    if is_revision:
        # 检查哪些维度的依赖已完成
        ready_dims = _check_revision_dependencies(state)
        if ready_dims:
            return [Send("analyze_dimension", {...}) for d in ready_dims]
        return END

    # 正常执行流程
    if phase == "completed":
        return END

    # step_mode 下 interrupt() 已在 layer_completion_check 中处理
    # 恢复后由 Command(resume=...) 触发，无需在路由中检查暂停标志

    # 检查同层依赖，只分发依赖已完成的 dimensions
    ready_dims = _get_ready_dimensions(state)
    if ready_dims:
        return [Send("analyze_dimension", {...}) for d in ready_dims]

    return END
```

---

## 关键节点详解

### conversation_node

中央路由节点，是 Agent 的"大脑"：

```python
# backend/app/agent/conversation/node.py
async def conversation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """中央路由节点 - 解析用户意图并决定下一步"""
    # 优化：如果最后一条消息已有已知 intent tool_call，跳过 LLM
    last_msg = messages[-1] if messages else None
    if last_msg and hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
        known = {"advance_planning_intent", "gis_analysis", "GISAnalysis"}
        for tc in last_msg.tool_calls:
            if tc.get("name") in known:
                return {}  # 直接路由，不调用 LLM

    # LLM 绑定工具
    llm_with_tools = llm.bind_tools([ADVANCE_PLANNING_TOOL, GIS_ANALYSIS_TOOL])
    response = await llm_with_tools.ainvoke(full_messages)

    return {"messages": [response]}
```

### analyze_dimension

维度分析节点，通过 Send API 并行分发执行：

```python
# backend/app/agent/nodes/analysis.py
async def analyze_dimension(state: Dict[str, Any]) -> Dict[str, Any]:
    """维度分析节点 - 直接执行"""
    # 1. 获取维度配置（从 phases.yaml）
    dim_config = get_dimension_config(dimension_key)

    # 2. 并行执行 GIS 工具
    gis_results = await execute_gis_tools(dim_config.tools)

    # 3. RAG 知识检索
    knowledge = await rag_service.search(dim_config.rag_query)

    # 4. 组装 Prompt（含前序依赖报告）
    prompt = build_analysis_prompt(state, dim_config, gis_results, knowledge)

    # 5. 流式 LLM + SSE 实时推送
    SSEPublisher.send_dimension_start(session_id, dimension_key)
    content = await stream_llm(prompt)
    SSEPublisher.send_dimension_complete(session_id, dimension_key, content)

    # 6. 保存版本到 ReportStore
    await report_store.save_report(session_id, dimension_key, content)

    # 7. 更新 completed_dimensions
    return {
        "completed_dimensions": {layer_key: [dimension_key]},
        "pending_reports": [{...}],
    }
```

### layer_completion_check

层级完成检查节点，使用 interrupt() 实现官方 human-in-the-loop：

```python
# backend/app/agent/completion/node.py
async def layer_completion_check(state: Dict[str, Any]) -> Dict[str, Any]:
    """层级完成检查 + interrupt 审批

    Key: interrupt() 恢复时整个节点从头重新执行，
    所以 SSE 事件必须在 interrupt 之后触发，避免重复。
    """
    layer = _phase_to_layer(phase)
    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    total_dims = get_layer_dimensions(layer)

    if set(completed) != set(total_dims):
        return {}  # 层级未完成，no-op

    step_mode = state.get("step_mode", False)

    if step_mode:
        # CRITICAL: interrupt() BEFORE any SSE side effects
        resume_data = interrupt({
            "layer": layer,
            "phase": phase,
            "layer_name": get_layer_name(layer),
            "reason": "step_mode_awaiting_review",
        })
        action = resume_data.get("action", "approve")

        if action == "approve":
            # 只在 approve 后发送 SSE 事件（避免重复）
            SSEPublisher.send_layer_complete(session_id, layer, ...)
            next_phase = get_next_phase(phase)
            return {"phase": next_phase, "previous_layer": layer}
        elif action == "reject":
            SSEPublisher.send_layer_complete(session_id, layer, ...)
            return {"need_revision": True, "is_revision": True, ...}

    # 连续模式：自动推进
    next_phase = get_next_phase(phase)
    SSEPublisher.send_layer_complete(session_id, layer, ...)
    return {"phase": next_phase, "previous_layer": layer}
```

### gis_agent

GIS 空间布局 ReAct Agent，带 error_handler 容错：

```python
# backend/app/agent/graph.py
def _gis_error_handler(state: Dict[str, Any], error: Exception) -> Command:
    """GIS Agent 错误处理 — 返回错误消息到 conversation"""
    logger.error("[gis_agent] Node failed: %s", error)
    return Command(
        update={"messages": [AIMessage(content=f"GIS 分析出错: {error}")]},
        goto="conversation",
    )

builder.add_node("gis_agent", gis_agent_node, error_handler=_gis_error_handler)
```

---

## 检查点机制

### Checkpoint 持久化

LangGraph Checkpointer 在每个节点执行后自动保存状态快照：

```python
# backend/app/database/engine.py
async def get_global_checkpointer():
    """获取全局 AsyncSqliteSaver 实例"""
    conn = await aiosqlite.connect(get_db_path())
    await conn.execute("PRAGMA journal_mode=WAL")
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    return checkpointer
```

### 检查点恢复流程

```
1. GET /api/sessions/{id}/checkpoints → 获取检查点列表
2. POST /api/sessions/{id}/resume/{checkpoint_id} → 恢复执行
3. aupdate_state(as_node="__start__") + astream(None, config)
```

### interrupt/resume 模式

LangGraph 官方 human-in-the-loop 机制：

```python
# 暂停：在 layer_completion_check 中调用
resume_data = interrupt({"layer": layer, "reason": "step_mode_awaiting_review"})

# 恢复：通过 PlanningRuntimeService.resume_from_interrupt()
await PlanningRuntimeService.resume_from_interrupt(
    session_id,
    resume_data={"action": "approve"},  # 或 "reject"
)
# 内部使用 Command(resume=resume_data) 作为 astream 输入
```

### 状态投影

`state_to_ui_status()` 函数从 AgentState + checkpoint 中断状态投影出前端所需的 UI 状态：

```python
def state_to_ui_status(state: Dict[str, Any], db_session=None, *, is_interrupted: bool = False) -> Dict[str, Any]:
    """状态转 UI 格式"""
    # is_interrupted 从 checkpoint_state.next 检测
    # next 包含 "layer_completion_check" → 表示 interrupt 暂停
    return {
        "session_id": state.get("session_id"),
        "status": status,  # paused when is_interrupted
        "phase": phase,
        "current_layer": current_layer,
        "progress": progress,
        "completed_dimensions": state.get("completed_dimensions"),
        "interrupt_info": interrupt_info,  # 替代 execution_paused/pause_after_step
        "step_mode": state.get("step_mode"),
    }
```

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 主图定义 | `backend/app/agent/graph.py` |
| 状态定义 | `backend/app/agent/state.py` |
| 路由逻辑 | `backend/app/agent/routing.py` |
| 对话节点 | `backend/app/agent/conversation/node.py` |
| 分析节点 | `backend/app/agent/analysis/node.py` |
| 完成检查 | `backend/app/agent/completion/node.py` |
| 工具节点 | `backend/app/agent/tools.py` |
| GIS 上下文 | `backend/app/agent/gis_context.py` |
| GIS Agent | `backend/app/agent/gis/` |
| 消息构建 | `backend/app/agent/message_builder.py` |
| 维度配置 | `backend/app/config/phases.yaml` |
| 依赖配置 | `backend/app/config/dependency.py` |

---

## 相关文档

- [03-layer-dimension](./03-layer-dimension.md) - 28维度配置
- [04-backend-api](./04-backend-api.md) - API 与 Agent 交互
- [06-tool-system](./06-tool-system.md) - Tool-Dimension 绑定
- [terminology](./terminology.md) - Agent 术语定义