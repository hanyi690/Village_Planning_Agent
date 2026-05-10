# Agent 核心架构

本文档详细说明 Router Agent 架构、StateGraph 设计和执行流程。

> **更新日期**: 2026-05-09
> **版本**: v3.0 (简化 3 节点架构)

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

### 简化 3 节点图

Router Agent 采用简化架构，仅 3 个核心节点 + Send API 动态分发：

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

**3 节点一览**：

| 节点 | 职责 | 类型 |
|------|------|------|
| `conversation` | 中央路由，LLM 意图识别 | 普通节点 |
| `execute_tools` | 执行 GIS 等工具调用 | 普通节点 |
| `analyze_dimension` | 维度分析（Send API 动态分发） | Send 目标节点 |

### 设计原则

1. **单一路由入口**: `conversation` 节点处理所有用户输入
2. **Send API 并行**: 维度分析通过 `Send("analyze_dimension", ...)` 动态分发，实现并行执行
3. **路由纯函数**: `after_conversation` / `after_analysis` 是纯路由函数，不含业务逻辑

---

## StateGraph 定义

### 图构建

```python
# backend/app/agent/graph.py
def create_unified_planning_graph(checkpointer=None) -> StateGraph:
    """创建统一规划图（3节点）"""
    builder = StateGraph(dict)

    # 3 个节点
    builder.add_node("conversation", conversation_node)
    builder.add_node("execute_tools", execute_tools_node)
    builder.add_node("analyze_dimension", analyze_dimension_node)

    # 边定义
    builder.add_edge(START, "conversation")
    builder.add_conditional_edges("conversation", after_conversation, {
        "execute_tools": "execute_tools",
        "analyze_dimension": "analyze_dimension",
        END: END
    })
    builder.add_edge("execute_tools", "conversation")
    builder.add_conditional_edges("analyze_dimension", after_analysis, {
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
3. analyze_dimension 完成后 → after_analysis 决定:
   - 层级未完成 → Send[N] → 继续 analyze_dimension
   - 层级完成 + pause_after_layer → conversation (等待审批)
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
    completed_dimensions: Dict[str, List[str]]  # {"layer1": [...], "layer2": [...]}
    reports: Dict[str, Dict[str, str]]         # {"layer1": {dim_key: content}}

    # 配置与交互
    config: Dict[str, Any]        # {village_data, task_description, constraints, ...}
    feedback: Optional[str]       # 级联修订反馈

    # Send API 注入
    dimension_key: Optional[str]  # 当前维度标识（Send API 动态注入）

    # 辅助字段
    image_ids: List[str]
    step_mode: bool
    metadata: Dict[str, Any]
    dimension_results: Annotated[List[Dict], operator.add]  # Send API 自动合并
```

### 与旧版(v2.0)的关键差异

| 字段 | v2.0 | v3.0 | 说明 |
|------|------|------|------|
| `sse_events` | `Annotated[List, operator.add]` | 移除 | SSE 直接在节点内发送，不通过状态传递 |
| `human_feedback` | str | 移除 | 合并为 `feedback` |
| `need_revision` | bool | 移除 | 通过 feedback 非空判断 |
| `revision_target_dimensions` | List[str] | 移除 | 通过影响树自动计算 |
| `pause_after_step` | bool | 保留 | 前端暂停标志 |
| `report_versions` | 无 | Dict | 新增，存储版本历史 |
| `summaries` | 无 | Dict | 新增，维度摘要 |

### 阶段枚举

```python
class PlanningPhase(Enum):
    INIT = "init"
    LAYER1 = "layer1"
    LAYER2 = "layer2"
    LAYER3 = "layer3"
    COMPLETED = "completed"
```

### 维度配置常量

```python
# 层级 → 维度列表
LAYER_DIMENSIONS: Dict[int, List[str]] = {
    1: _get_layer_dimensions(1),  # 12 维度
    2: _get_layer_dimensions(2),  # 4 维度
    3: _get_layer_dimensions(3),  # 12 维度
}

# 层内波次分组
WAVE_DIMENSIONS: Dict[int, Dict[int, List[str]]] = {
    1: {1: [...]},  # Layer1 全部 Wave 1
    2: {1: [...], 2: [...], 3: [...], 4: [...]},  # Layer2 4个波次
    3: {1: [...], 2: [...]},  # Layer3 2个波次
}
```

---

## 路由逻辑

### after_conversation - 对话后路由

```python
# backend/app/agent/routing.py
def after_conversation(state: Dict[str, Any]) -> Union[str, List[Send]]:
    """
    对话后路由 - 新架构核心

    3 种路由分支:
    1. 级联修订: feedback 存在 → 计算影响树 → Send[N] 维度
    2. 推进规划: AdvancePlanningIntent → 分发当前层级维度
    3. 工具调用: GISAnalysis → execute_tools
    4. 普通对话: END
    """
    # 1. 级联修订
    if state.get("feedback"):
        target_dim = _infer_dim_from_feedback(state)
        impacted = get_impact_tree_compat(target_dim)
        all_dims = [target_dim] + [d for wave_dims in impacted.values() for d in wave_dims]
        return [Send("analyze_dimension", {...}) for dim in all_dims]

    # 2-3. 工具调用检测
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            if name == "AdvancePlanningIntent":
                return _dispatch_current(state)  # → Send[N]
            if name == "GISAnalysis":
                return "execute_tools"

    # 4. 默认结束
    return END
```

### after_analysis - 分析后路由

```python
def after_analysis(state: Dict[str, Any]) -> Union[str, List[Send]]:
    """
    分析后路由 - 波次推进逻辑

    4 种结果:
    1. completed → END
    2. 层级完成 + pause_after_layer → conversation (等待审批)
    3. 层级完成 → 推进 phase → Send[N] 下一层维度
    4. 未完成 → Send[N] 继续当前层维度
    """
    if phase == "completed":
        return END

    completed = state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    total_dims = get_layer_dimensions(layer)

    if set(completed) == set(total_dims):
        # 层级完成
        if state.get("pause_after_step"):
            return "conversation"  # 等待用户审批
        # 推进到下一层
        return [Send("analyze_dimension", {...}) for d in pending_next_layer]

    # 继续当前层
    pending = [d for d in total_dims if d not in completed]
    return [Send("analyze_dimension", {...}) for d in pending]
```

### 与旧版(v2.0)路由对比

| 路由函数 | v2.0 | v3.0 |
|----------|------|------|
| 意图路由 | `intent_router()` → execute_tools / route_planning / END | 合并到 `after_conversation()` |
| 阶段推进 | `route_by_phase()` → knowledge_preload / analyze_dimension / advance_phase | 合并到 `_dispatch_current()` |
| 完成检查 | `check_completion()` → continue / advance / complete / pause | 合并到 `after_analysis()` |

---

## 关键节点详解

### conversation_node

中央路由节点，是 Agent 的"大脑"：

```python
# backend/app/agent/nodes/conversation.py
async def conversation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """中央路由节点 - 解析用户意图并决定下一步"""
    # 构建系统提示（包含当前阶段、项目信息）
    system_prompt = _build_system_prompt(phase, project_name, config)

    # LLM 绑定工具: AdvancePlanningIntent + GISAnalysis
    llm = create_llm(model=LLM_MODEL, temperature=0.7)
    llm_with_tools = llm.bind_tools([ADVANCE_PLANNING_TOOL, GIS_ANALYSIS_TOOL])

    response = await llm_with_tools.ainvoke([SystemMessage(...)] + messages)
    return {"messages": [response]}
```

**绑定的工具**：

| 工具 | 功能 | 路由结果 |
|------|------|----------|
| `AdvancePlanningIntent` | 推进规划流程 | `after_conversation` → Send[N] 维度 |
| `GISAnalysis` | GIS 可视化分析 | `after_conversation` → `execute_tools` |
| (无工具调用) | 普通对话 | `after_conversation` → END |

### analyze_dimension

维度分析节点，通过 Send API 并行分发执行：

```python
# backend/app/agent/nodes/analysis.py
async def analyze_dimension(state: Dict[str, Any]) -> Dict[str, Any]:
    """维度分析节点 - 直接执行（8步流程）"""
    # 1. 获取维度配置（从 phases.yaml）
    # 2. 并行执行 GIS 工具
    # 3. RAG 知识检索
    # 4. 组装 Prompt（含前序依赖报告）
    # 5. 流式 LLM + SSE 实时推送 (dimension_start/delta/complete)
    # 6. 保存版本到 ReportStore
    # 7. 更新 completed_dimensions
    # 8. 返回状态更新
```

**SSE 事件序列**：

```
dimension_start → dimension_delta × N → dimension_complete (含 gis_data)
```

**依赖注入**：

```python
# 根据层级注入前序报告
if layer == 1:
    # 无依赖，直接使用 village_data
    pass
elif layer == 2:
    # 注入 Layer 1 完整报告
    deps = "\n".join([f"【{k}】{v[:800]}" for k, v in reports["layer1"].items()])
elif layer == 3:
    # 注入 Layer 1 + Layer 2 报告
    deps = layer1_summary + layer2_summary
```

### execute_tools_node

执行非规划类工具（GIS 等）：

```python
# backend/app/agent/nodes/tools.py
async def execute_tools_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """工具执行节点 - 处理非推进类的工具调用"""
    # 过滤掉 AdvancePlanningIntent（由路由处理）
    regular_calls = [tc for tc in tool_calls if tc["name"] != "AdvancePlanningIntent"]

    for tc in regular_calls:
        SSEPublisher.send_tool_call(...)      # 通知前端开始
        result = ToolRegistry.execute_tool(...) # 执行工具
        SSEPublisher.send_tool_result(...)    # 通知前端结果

    return {"messages": tool_results}  # ToolMessage 列表
```

**执行后回到 `conversation` 节点**，让 LLM 处理工具结果。

---

## 检查点机制

### Checkpoint 持久化

LangGraph Checkpointer 在每个节点执行后自动保存状态快照：

```python
# backend/app/database/engine.py
async def get_global_checkpointer():
    """获取全局 AsyncSqliteSaver 实例（单例模式）"""
    conn = await aiosqlite.connect(get_db_path(), check_same_thread=False)
    await conn.execute("PRAGMA journal_mode=WAL")
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    return checkpointer
```

### 检查点恢复流程

```
1. 前端调用 GET /api/sessions/{id}/checkpoints → 获取检查点列表
2. 前端调用 POST /api/sessions/{id}/resume/{checkpoint_id} → 恢复执行
3. 后端查找目标 snapshot → 解析 layer → 通过 graph.ainvoke(None, config) 继续
```

### 状态投影

`state_to_ui_status()` 函数从 AgentState 投影出前端所需的 UI 状态：

```python
def state_to_ui_status(state: Dict[str, Any], db_session=None) -> Dict[str, Any]:
    """状态转 UI 格式"""
    return {
        "phase": phase,
        "current_wave": state.get("current_wave", 1),
        "reports": state.get("reports", {}),
        "current_layer": _phase_to_layer(phase),
        "progress": progress,
        "completed_dimensions": state.get("completed_dimensions", {}),
        "pause_after_step": state.get("pause_after_step", False),
        "step_mode": state.get("step_mode", False),
        "previous_layer": state.get("previous_layer", 0),
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
| 工具节点 | `backend/app/agent/nodes/tools.py` |
| 分析节点 | `backend/app/agent/nodes/analysis.py` |
| GIS 上下文 | `backend/app/agent/gis_context.py` |
| 消息构建 | `backend/app/agent/message_builder.py` |
| 维度配置 | `backend/app/config/phases.yaml` |
| 依赖配置 | `backend/app/config/dependency.py` |

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [03-layer-dimension](./03-layer-dimension.md) - 28维度配置、Wave 机制
- [04-backend-api](./04-backend-api.md) - API 与 Agent 交互
- [06-tool-system](./06-tool-system.md) - Tool-Dimension 绑定
- [terminology](./terminology.md) - Agent 术语定义

---

## 历史变更

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v3.0 | 2026-05-09 | 简化为 3 节点图；合并 advance_phase/collect_results/emit_events 到路由和分析节点；after_conversation/after_analysis 替代旧路由函数 |
| v2.0 | 2026-05-08 | 架构重组，统一 StateGraph |
| v1.0 | 2026-05-07 | 初始版本 |