# Agent 核心架构

本文档详细说明 Router Agent 架构、StateGraph 设计和执行流程。

> **更新日期**: 2026-05-21
> **版本**: v3.2 (统一架构)

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

### 简化 4 节点图

Router Agent 采用简化架构，4 个核心节点 + Send API 动态分发：

```
              START
                │
                ▼
         ┌─────────────┐
    ┌───│ conversation │◄──────────────────────┐
    │   └──────┬──────┘                       │
    │          │ after_conversation            │
    │   ┌──────┼──────┬──────────┐            │
    │   ▼      ▼      ▼          ▼            │
    │  exec   Send[N] END       END           │
    │  _tools   │     (闲聊)   (暂停)          │
    │   │       ▼                             │
    │   │  analyze_dimension                  │
    │   │       │                             │
    │   │       │ after_analysis              │
    │   │  ┌────┼────┬──────────┐            │
    │   │  ▼    ▼    ▼          ▼            │
    │   │ Send END  conversation  END        │
    │   │ (继续)(完成) (等待审批) (完成)       │
    │   └────┼────────────────────┘            │
    └────────┘                                │
```

**4 节点一览**：

| 节点 | 职责 | 类型 |
|------|------|------|
| `conversation` | 中央路由，LLM 意图识别 | 普通节点 |
| `execute_tools` | 执行 GIS 等工具调用 | 普通节点 |
| `analyze_dimension` | 维度分析（Send API 动态分发） | Send 目标节点 |
| `layer_completion_check` | 层级完成检查与暂停控制 | 普通节点 |

### 设计原则

1. **单一路由入口**: `conversation` 节点处理所有用户输入
2. **Send API 并行**: 维度分析通过 `Send("analyze_dimension", ...)` 动态分发
3. **路由纯函数**: `after_conversation` / `after_analysis` 是纯路由函数
4. **依赖驱动**: 同层依赖检查决定分发顺序

---

## StateGraph 定义

### 图构建

```python
# backend/app/agent/graph.py
def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图（4节点）"""
    builder = StateGraph(AgentState)

    # 4 个节点
    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("analyze_dimension", analyze_dimension_node)
    builder.add_node("layer_completion_check", layer_completion_check)

    # 边定义
    builder.add_edge(START, "conversation")
    builder.add_conditional_edges("conversation", after_conversation, {
        "execute_tools": "execute_tools",
        "analyze_dimension": "analyze_dimension",
        END: END
    })
    builder.add_edge("execute_tools", "conversation")
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
   - tool_calls(GIS) → execute_tools → 回到 conversation
   - AdvancePlanningIntent → Send[N] → analyze_dimension × N
   - 级联修订(feedback) → Send[N] → analyze_dimension × N
   - 普通对话/无操作 → END
3. analyze_dimension 完成后 → layer_completion_check
4. after_analysis 决定:
   - 层级未完成 → Send[N] → 继续 analyze_dimension
   - 层级完成 + execution_paused → END (等待审批)
   - 层级完成 + 无暂停 → 推进下一层 → Send[N]
   - 全部完成 → END
```

---

## 状态定义

### AgentState

```python
# backend/app/agent/state.py
class AgentState(TypedDict, total=False):
    """核心状态 - 精简版"""
    # 消息流
    messages: Annotated[List[BaseMessage], add_messages]

    # 会话标识
    session_id: str
    project_name: str

    # 执行进度
    phase: str                    # 当前阶段 (init/layer1/layer2/layer3)
    current_wave: int             # 当前波次
    completed_dimensions: Annotated[Dict[str, List[str]], _merge_dict_of_lists]

    # 配置与交互
    config: Dict[str, Any]        # {village_data, task_description, constraints, ...}
    feedback: Optional[str]       # 级联修订反馈

    # Send API 注入
    dimension_key: Optional[str]  # 当前维度标识（Send API 动态注入）

    # 执行控制
    step_mode: bool               # 分步执行模式
    execution_paused: bool        # 执行暂停标志
    pause_after_step: bool        # 层级完成后暂停
    previous_layer: int           # 前一个完成的层级

    # 级联修订
    need_revision: bool
    revision_target_dimensions: List[str]
    human_feedback: str
    is_revision: bool
    revision_impact_tree: Optional[Dict[int, List[str]]]
    revision_completed_dims: Annotated[Dict[int, List[str]], _merge_dict_of_lists]

    # 性能优化
    pending_reports: Annotated[List[Dict], _merge_lists]  # 批量写入缓冲
    layer_char_counts: Annotated[Dict[int, int], _merge_layer_char_counts]
```

### 并行合并函数

状态使用 Annotated 类型配合合并函数，实现 Send API 并行执行后的状态合并：

```python
def _merge_dict_of_lists(a: Dict[str, List], b: Dict[str, List]) -> Dict[str, List]:
    """合并两个 {key: list} 字典，对同 key 的 list 去重拼接"""
    ...

def _merge_lists(a: List, b: List) -> List:
    """合并两个列表"""
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
    3. 工具执行：其他工具 -> execute_tools
    4. 普通对话：END
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
                return "execute_tools"

    return END
```

### after_analysis - 分析后路由

```python
def after_analysis(state: Dict[str, Any]) -> Union[str, List[Send]]:
    """
    分析后路由 - 波次推进逻辑

    处理：
    1. completed -> END
    2. execution_paused -> END（等待审批）
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

    if state.get("execution_paused"):
        return END

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
# backend/app/agent/nodes/conversation.py
async def conversation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """中央路由节点 - 解析用户意图并决定下一步"""
    # 构建系统提示
    system_prompt = f"""你是村庄规划助手，正在进行 {project_name} 的规划工作。

当前阶段：{PHASE_DESCRIPTIONS.get(phase, '未知')}
规划任务：{config.get('task_description', '制定村庄发展规划')}
约束条件：{config.get('constraints', '无特殊约束')}

可用工具：
- AdvancePlanningIntent: 推进规划流程
- GISAnalysis: GIS可视化分析"""

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

层级完成检查节点：

```python
# backend/app/agent/nodes/completion.py
async def layer_completion_check(state: Dict[str, Any]) -> Dict[str, Any]:
    """层级完成检查"""
    layer = _phase_to_layer(phase)
    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    total_dims = get_layer_dimensions(layer)

    if set(completed) == set(total_dims):
        # 层级完成
        if state.get("step_mode"):
            # 分步模式：暂停等待审批
            return {
                "execution_paused": True,
                "pause_after_step": True,
                "previous_layer": layer,
            }
        # 连续模式：推进下一层
        next_phase = get_next_phase(phase)
        return {"phase": next_phase}

    return {}
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
3. graph.invoke(None, {"configurable": {"checkpoint_id": ...}})
```

### 状态投影

`state_to_ui_status()` 函数从 AgentState 投影出前端所需的 UI 状态：

```python
def state_to_ui_status(state: Dict[str, Any], db_session=None) -> Dict[str, Any]:
    """状态转 UI 格式"""
    return {
        "session_id": state.get("session_id"),
        "status": status,
        "phase": phase,
        "current_layer": current_layer,
        "progress": progress,
        "completed_dimensions": state.get("completed_dimensions"),
        "execution_paused": state.get("execution_paused"),
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
| 对话节点 | `backend/app/agent/nodes/conversation.py` |
| 分析节点 | `backend/app/agent/nodes/analysis.py` |
| 完成检查 | `backend/app/agent/nodes/completion.py` |
| 工具节点 | `backend/app/agent/nodes/tools.py` |
| GIS 上下文 | `backend/app/agent/gis_context.py` |
| 消息构建 | `backend/app/agent/message_builder.py` |
| 维度配置 | `backend/app/config/phases.yaml` |
| 依赖配置 | `backend/app/config/dependency.py` |

---

## 相关文档

- [03-layer-dimension](./03-layer-dimension.md) - 28维度配置
- [04-backend-api](./04-backend-api.md) - API 与 Agent 交互
- [06-tool-system](./06-tool-system.md) - Tool-Dimension 绑定
- [terminology](./terminology.md) - Agent 术语定义