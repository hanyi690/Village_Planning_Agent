# 数据和状态流转架构文档

## 概述

本文档详细描述 Village Planning Agent 系统从数据生成到前端展示的完整流程，包括状态变化、存储时机、事件发送机制和架构设计。

**核心设计原则**: **SSOT (Single Source of Truth)** - 以 LangGraph Checkpoint 为唯一真实源。

---

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              前端 (Next.js)                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ ChatPanel   │───>│TaskController│───>│ SSE Client  │───>│ Context     │  │
│  │ (UI组件)    │    │ (状态管理)   │    │ (EventSource)│    │ (全局状态)  │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                │            │               │
│                                                │            ▼               │
│                                                │    localVersion 比较      │
└────────────────────────────────────────────────│────────────────────────────┘
         │                    │                  │
         │ REST API           │ REST API        │ SSE
         ▼                    ▼                  │
┌─────────────────────────────────────────────────────────────────────────────┐
│                              后端 (FastAPI)                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ Planning API│───>│ Event Queue │───>│ SSE Stream  │    │ Status API  │  │
│  │ /start      │    │ (asyncio.Q) │    │ /stream     │    │ /status     │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│         │                                    ▲                │             │
│         ▼                                    │                ▼             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ LangGraph   │───>│ Background  │───>│ Publish     │    │ version     │  │
│  │ Execution   │    │ Task        │    │ to Queue    │    │ 字段返回    │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      存储层 (SSOT: Checkpoint 为核心)                         │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │              LangGraph Checkpoint (唯一真实源)                         │  │
│  │  ├── VillagePlanningState (完整状态)                                  │  │
│  │  ├── metadata: { published_layers, version, last_signal_timestamp }  │  │
│  │  └── layer_X_completed, analysis_reports, concept_reports...         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │ SQLite DB   │    │ SSE 内存队列│    │ 文件系统    │                      │
│  │ (业务元数据)│    │ (阅后即焚)  │    │ (报告文件)  │                      │
│  │ is_executing│    │ deque(5000) │    │ Markdown    │                      │
│  │ stream_state│    │             │    │             │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心架构优化 (2026-03-09)

### 2.1 SSOT 架构设计

**设计原则**: 以 LangGraph Checkpoint 为唯一真实源 (Single Source of Truth)

| 优化项 | 旧架构 | 新架构 |
|--------|--------|--------|
| **去重状态** | 内存 `sent_layer_events` set | Checkpoint `metadata.published_layers` |
| **执行状态** | 内存 `_active_executions` dict | 数据库 `is_executing` 字段 |
| **流状态** | 内存 `_stream_states` dict | 数据库 `stream_state` 字段 |
| **历史事件** | 仅依赖内存 `_sessions` | Checkpoint 重建 + 内存缓存 |

### 2.2 State Metadata 结构

```python
# VillagePlanningState 中的 metadata 字段
metadata: Dict[str, Any] = {
    "published_layers": [1, 2],           # 已发送 layer_completed 信号的层级
    "version": 102,                        # 状态版本号，用于前端同步
    "last_signal_timestamp": "2025-...",  # 最后信号时间戳
}
```

### 2.3 数据库字段扩展

```sql
-- planning_sessions 表新增字段
ALTER TABLE planning_sessions ADD COLUMN is_executing BOOLEAN DEFAULT FALSE;
ALTER TABLE planning_sessions ADD COLUMN stream_state TEXT DEFAULT 'active';
```

---

## 3. 数据生成阶段

### 3.1 LangGraph 执行流程

**入口点**: `backend/api/planning.py` - `_execute_graph_in_background()`

```python
async def _execute_graph_in_background(session_id, graph, initial_state, checkpointer):
    config = {"configurable": {"thread_id": session_id}}
    
    # ✅ 持久化去重：从 Checkpoint metadata 读取已发送的层级信号
    checkpoint_state = await graph.aget_state(config)
    metadata = checkpoint_state.values.get("metadata", {})
    published_layers = set(metadata.get("published_layers", []))
    
    stream_iterator = graph.astream(clean_state, config, stream_mode="values")
    
    async for event in stream_iterator:
        # 检测层级完成，使用 published_layers 去重
        for layer_num in [1, 2, 3]:
            if event.get(f"layer_{layer_num}_completed") and layer_num not in published_layers:
                # 发送事件
                await _append_session_event_async(session_id, event_data)
                
                # ✅ 持久化更新 metadata
                published_layers.add(layer_num)
                await graph.aupdate_state(config, {
                    "metadata": {
                        "published_layers": list(published_layers),
                        "version": metadata.get("version", 0) + 1,
                    }
                })
```

### 3.2 子图节点数据生成

**文件**: `src/nodes/subgraph_nodes.py`

与之前相同，但状态更新自动持久化到 Checkpoint。

### 3.3 数据生成时机

| 事件类型 | 触发时机 | 数据内容 |
|---------|---------|---------|
| `layer_started` | 层级开始执行 | layer, layer_name |
| `dimension_delta` | 每个 token 生成时（频率控制） | delta, accumulated |
| `dimension_complete` | 维度分析完成 | full_content |
| `layer_completed` | 层级所有维度完成 | has_data, dimension_count, **version** |
| `pause` | 步进模式暂停 | checkpoint_id, current_layer |
| `stream_paused` | SSE 流暂停信号 | reason |

---

## 4. 后端处理阶段

### 4.1 事件队列管理

**文件**: `backend/api/planning.py`

```python
# 全局订阅管理
_session_subscribers: Dict[str, set] = {}  # session_id -> set of asyncio.Queue

async def subscribe_session(session_id: str) -> asyncio.Queue:
    queue = asyncio.Queue(maxsize=200)
    _session_subscribers[session_id].add(queue)
    
    # ✅ 同步历史事件到新订阅者
    for event in _sessions[session_id]["events"]:
        queue.put_nowait(event)
    
    # ✅ 新增：如果内存中没有历史事件，从 Checkpoint 重建
    if historical_count == 0 or not layer_completed_found:
        rebuilt_events = await _rebuild_events_from_checkpoint(session_id)
        for event in rebuilt_events:
            queue.put_nowait(event)
    
    return queue
```

### 4.2 Checkpoint 事件重建

```python
async def _rebuild_events_from_checkpoint(session_id: str) -> List[Dict]:
    """从 Checkpoint 重建关键事件（服务重启后恢复）"""
    events = []
    
    checkpoint_state = await graph.aget_state(config)
    state = checkpoint_state.values
    
    # 重建 layer_completed 事件
    for layer_num in [1, 2, 3]:
        if state.get(f"layer_{layer_num}_completed"):
            events.append({
                "type": "layer_completed",
                "layer": layer_num,
                "_rebuild": True,  # 标记为重建事件
                ...
            })
    
    # 重建 pause 事件
    if state.get("pause_after_step"):
        events.append({"type": "pause", ...})
    
    return events
```

### 4.3 Signal-Fetch Pattern

**设计原则**: SSE 只发送轻量信号，不传输大型数据

```python
# layer_completed 事件（轻量信号 + 版本号）
event_data = {
    "type": "layer_completed",
    "layer": layer_num,
    "has_data": len(dimension_reports) > 0,
    "dimension_count": len(dimension_reports),
    "total_chars": total_dimension_content,
    "version": updated_metadata["version"],  # ✅ 新增：版本号
    # 不包含 report_content 和 dimension_reports
}
```

### 4.4 执行状态管理（数据库）

```python
# 替代内存中的 _active_executions 和 _stream_states

async def _is_execution_active(session_id: str) -> bool:
    """从数据库读取执行状态"""
    from backend.database.operations_async import is_execution_active_async
    return await is_execution_active_async(session_id)

async def _set_execution_active(session_id: str, active: bool):
    """写入数据库"""
    from backend.database.operations_async import set_execution_active_async
    await set_execution_active_async(session_id, active)

async def _get_stream_state(session_id: str) -> str:
    """从数据库读取流状态"""
    from backend.database.operations_async import get_stream_state_async
    return await get_stream_state_async(session_id)

async def _set_stream_state(session_id: str, state: str):
    """写入数据库"""
    from backend.database.operations_async import set_stream_state_async
    await set_stream_state_async(session_id, state)
```

---

## 5. 存储时机和方法

### 5.1 存储层次 (SSOT)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        存储层次 (优先级从高到低)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. LangGraph Checkpoint (Primary - SSOT)                                   │
│     ├── 完整状态快照、支持回滚                                               │
│     ├── metadata.published_layers (去重状态)                                │
│     ├── metadata.version (版本号)                                           │
│     └── 由 AsyncSqliteSaver 自动管理                                        │
│                                                                              │
│  2. SQLite planning_sessions (Business Metadata)                            │
│     ├── status, created_at, execution_error                                 │
│     ├── is_executing (替代内存 _active_executions)                          │
│     ├── stream_state (替代内存 _stream_states)                              │
│     └── 业务元数据，不存储状态字段                                           │
│                                                                              │
│  3. _sessions 内存 (SSE Event Queue Only)                                   │
│     ├── events: deque(maxlen=5000) - 阅后即焚                               │
│     └── 仅用于 SSE 事件缓存，不存储业务状态                                  │
│                                                                              │
│  4. 文件系统 (results/{project}/{session}/)                                 │
│     ├── 最终报告输出                                                         │
│     └── Markdown/HTML 格式                                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 存储时机详解

#### 会话创建时

```python
# backend/api/planning.py - start_planning()

# 1. 创建数据库会话记录（包含执行状态）
await create_planning_session_async({
    "session_id": session_id,
    "project_name": request.project_name,
    "status": TaskStatus.running,
    "is_executing": True,      # ✅ 新增
    "stream_state": "active",  # ✅ 新增
})

# 2. 初始化 SSE 内存队列（仅用于事件缓存）
_sessions[session_id] = {
    "events": deque(maxlen=5000),  # 仅 SSE 事件
}

# 3. LangGraph State 包含 metadata
initial_state = {
    ...
    "metadata": {
        "published_layers": [],
        "version": 0,
    }
}
```

#### 层级完成时

```python
# layer_completed 事件处理

# 1. 发送 SSE 事件
await _append_session_event_async(session_id, event_data)

# 2. ✅ 持久化更新 Checkpoint metadata
await graph.aupdate_state(config, {
    "metadata": {
        "published_layers": [..., layer_num],
        "version": current_version + 1,
    }
})

# 3. 不再更新内存 sent_layer_events（已废弃）
```

#### 暂停/完成时

```python
# 暂停时
await _set_stream_state(session_id, "paused")
await set_execution_active_async(session_id, False)

# 完成时
await _set_stream_state(session_id, "completed")
await set_execution_active_async(session_id, False)
```

### 5.3 数据库表结构

#### planning_sessions 表

```sql
CREATE TABLE planning_sessions (
    session_id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    
    -- ✅ 新增：执行状态（替代内存状态）
    is_executing BOOLEAN DEFAULT FALSE,
    stream_state TEXT DEFAULT 'active',  -- 'active', 'paused', 'completed'
    
    -- 业务元数据
    execution_error TEXT,
    output_path TEXT,
    completed_at TEXT
);
```

#### VillagePlanningState (Checkpoint)

```python
class VillagePlanningState(TypedDict):
    # 输入
    project_name: str
    village_data: str
    
    # 流程控制
    current_layer: int
    layer_1_completed: bool
    layer_2_completed: bool
    layer_3_completed: bool
    
    # 各层成果
    analysis_reports: Dict[str, str]
    concept_reports: Dict[str, str]
    detail_reports: Dict[str, str]
    
    # ✅ 新增：元数据（持久化到 Checkpoint）
    metadata: Dict[str, Any]  # {published_layers, version, ...}
```

---

## 6. 前端接收阶段

### 6.1 SSE 连接管理

**文件**: `frontend/src/controllers/TaskController.tsx`

```typescript
// SSE 连接建立（仅依赖 taskId）
useEffect(() => {
    if (!taskId) return;
    
    const es = planningApi.createStream(taskId, (event) => {
        switch (event.type) {
            case 'layer_completed':
                // ✅ Signal-Fetch Pattern: 触发 REST API 获取完整数据
                callbacks.onLayerCompleted?.(event.data.layer, '', {});
                break;
            // ... 其他事件
        }
    });
    
    return () => es.close();
}, [taskId]);
```

### 6.2 版本化同步机制

**文件**: `frontend/src/contexts/UnifiedPlanningContext.tsx`

```typescript
// ✅ 新增：本地版本号，用于版本化同步
const localVersionRef = useRef<number>(0);

const syncBackendState = useCallback((backendData: any) => {
    // ✅ 版本化同步：检查版本号，防止乱序导致的 UI 回滚
    const serverVersion = backendData.version ?? 0;
    const localVersion = localVersionRef.current;
    
    if (serverVersion > 0 && serverVersion <= localVersion) {
        console.log(`跳过旧版本数据: serverVersion=${serverVersion}, localVersion=${localVersion}`);
        return;
    }
    
    // 更新本地版本号
    if (serverVersion > 0) {
        localVersionRef.current = serverVersion;
    }
    
    // 继续处理状态更新...
}, []);
```

### 6.3 layer_completed 事件处理

```typescript
// ChatPanel.tsx - handleLayerCompleted()
const handleLayerCompleted = async (layer, reportContent, dimensionReports) => {
    // 1. 强制刷新批处理事件
    flushBatch();
    
    // 2. ✅ Signal-Fetch Pattern: 调用 REST API 获取完整数据
    const backendData = await fetchLayerReportsFromBackend(layer);
    
    // 3. 合并数据（优先使用 REST API 返回的数据）
    const finalReports = backendData?.reports || dimensionReports;
    
    // 4. 更新 UI
    updateLayerReport(layer, finalReports);
};
```

---

## 7. 事件类型和处理

### 7.1 事件类型汇总

| 事件类型 | 方向 | 数据内容 | 处理方式 |
|---------|------|---------|---------|
| `connected` | 后端→前端 | session_id | 日志记录 |
| `layer_started` | 后端→前端 | layer, layer_name | 创建空消息、更新 UI |
| `dimension_delta` | 后端→前端 | delta, accumulated | 批量更新内容缓存 |
| `dimension_complete` | 后端→前端 | full_content | 最终化维度内容 |
| `layer_completed` | 后端→前端 | has_data, dimension_count, **version** | 触发 REST API 调用 |
| `pause` | 后端→前端 | checkpoint_id, layer | 显示审查面板 |
| `stream_paused` | 后端→前端 | reason | 关闭 SSE 连接 |
| `completed` | 后端→前端 | success | 显示完成状态 |
| `error` | 后端→前端 | error message | 显示错误信息 |

### 7.2 事件频率控制

```python
# dimension_delta 事件频率控制
DELTA_MIN_INTERVAL_MS = 500  # ✅ 从 200ms 增加到 500ms
DELTA_MIN_TOKENS = 50        # ✅ 从 20 增加到 50 tokens

def append_dimension_delta_event(...):
    current_time = time.time() * 1000
    
    # 检查是否应该发送
    time_elapsed = current_time - last_sent
    should_send = (time_elapsed >= 500) or (token_count >= 50)
    
    if not should_send:
        return False  # 跳过发送
    
    # 发送事件...
```

---

## 8. 恢复和重连机制

### 8.1 后端恢复流程

```python
# _resume_graph_execution()

# 1. 从 Checkpoint 获取完整状态（包含 metadata）
checkpoint_state = await graph.aget_state(config)
full_state = checkpoint_state.values

# 2. ✅ 从 metadata 恢复去重状态
metadata = full_state.get("metadata", {})
published_layers = set(metadata.get("published_layers", []))

# 3. 清除暂停标志
await graph.aupdate_state(config, {
    "pause_after_step": False,
    "previous_layer": 0,
})

# 4. 更新数据库执行状态
await _set_execution_active(session_id, True)
await _set_stream_state(session_id, "active")

# 5. 启动后台执行
asyncio.create_task(_execute_graph_in_background(...))
```

### 8.2 SSE 重连时状态补全

```python
# subscribe_session()

# ✅ 如果内存中没有历史事件，从 Checkpoint 重建
if historical_count == 0 or not layer_completed_found:
    rebuilt_events = await _rebuild_events_from_checkpoint(session_id)
    for event in rebuilt_events:
        queue.put_nowait(event)
```

### 8.3 前端重连机制

```typescript
// TaskController.tsx
// SSE 断线重连时先获取完整状态

const handleSSEError = () => {
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        // ✅ 重连前先获取一次完整状态
        fetchStatus().then(() => {
            sseConnectionRef.current = createSSEConnection();
        });
    }
};
```

---

## 9. 关键设计决策

### 9.1 SSOT 架构

**问题**: 多套状态（内存、数据库、Checkpoint）导致数据不一致

**解决方案**:
1. LangGraph Checkpoint 为唯一真实源
2. 数据库只存储业务元数据（status, is_executing, stream_state）
3. 内存只用于 SSE 事件缓存（阅后即焚）

### 9.2 持久化去重

**问题**: 服务重启后内存 `sent_layer_events` 丢失，导致重复发送事件

**解决方案**:
```python
# 将已发送层级存储到 Checkpoint metadata
await graph.aupdate_state(config, {
    "metadata": {
        "published_layers": [..., layer_num],
    }
})

# 从 Checkpoint 读取去重状态
published_layers = set(metadata.get("published_layers", []))
```

### 9.3 版本化同步

**问题**: SSE 消息乱序导致 UI 回滚到旧状态

**解决方案**:
```typescript
// 前端维护 localVersion，仅当 serverVersion > localVersion 时更新
if (serverVersion > 0 && serverVersion <= localVersion) {
    return; // 跳过旧版本数据
}
localVersionRef.current = serverVersion;
```

### 9.4 SSE 重连状态补全

**问题**: 服务重启后内存事件丢失

**解决方案**:
```python
# 从 Checkpoint 重建关键事件
rebuilt_events = await _rebuild_events_from_checkpoint(session_id)
```

---

## 10. 调试日志追踪

### 10.1 后端日志点

| 位置 | 日志内容 | 级别 |
|------|---------|------|
| `subscribe_session` | 订阅者数量、历史事件数量、是否从 Checkpoint 重建 | INFO |
| `_rebuild_events_from_checkpoint` | 重建事件数量、类型 | INFO |
| `_execute_graph_in_background` | published_layers、version 更新 | INFO |
| `_set_execution_active` | 执行状态变更 | INFO |
| `_set_stream_state` | 流状态变更 | INFO |

### 10.2 前端日志点

| 位置 | 日志内容 | 级别 |
|------|---------|------|
| `syncBackendState` | 版本号比较、状态更新 | LOG |
| `handleLayerCompleted` | REST API 调用、数据合并 | LOG |
| `fetchLayerReportsFromBackend` | API 调用耗时、响应数据 | LOG |

---

## 11. 问题排查指南

### 11.1 Layer 1 报告不显示

**检查点**:
1. SSE 连接是否在 `stream_paused` 后断开？
2. `layer_completed` 事件是否发送到订阅者？
3. 前端 REST API 调用是否成功？
4. ✅ Checkpoint metadata.published_layers 是否正确？

**日志追踪**:
```
后端: [Planning] [{id}] ✅ 已更新 metadata: published_layers=[1], version=1
后端: [SSE Publish] Session {id}: ✅ layer_completed 已发送到 1 个订阅者
前端: [TaskController] ✅ layer_completed signal: Layer 1, version=1
前端: [UnifiedPlanningContext] 更新版本号: 0 -> 1
```

### 11.2 SSE 重连后事件丢失

**检查点**:
1. `_rebuild_events_from_checkpoint` 是否被调用？
2. Checkpoint 中是否有完整状态？
3. 内存事件队列是否正确初始化？

**日志追踪**:
```
后端: [SSE Subscribe] Session {id}: 尝试从 Checkpoint 重建事件
后端: [Checkpoint Rebuild] Session {id}: 重建 layer_completed 事件 Layer 1
后端: [Checkpoint Rebuild] Session {id}: 共重建 2 个事件
```

### 11.3 版本同步问题

**检查点**:
1. 后端 `/status` API 是否返回 version 字段？
2. 前端 `localVersionRef` 是否正确更新？
3. SSE 事件是否包含 version？

**日志追踪**:
```
前端: [UnifiedPlanningContext] 跳过旧版本数据: serverVersion=1, localVersion=2
前端: [UnifiedPlanningContext] 更新版本号: 2 -> 3
```

---

## 12. 性能优化

### 12.1 事件批处理

- `dimension_delta` 使用频率控制（500ms/50 tokens）
- 前端使用 `requestAnimationFrame` 批量更新 DOM

### 12.2 数据传输优化

- 使用 Signal-Fetch Pattern 避免大型数据通过 SSE 传输
- REST API 响应使用 gzip 压缩

### 12.3 内存管理

- 事件队列使用 `deque(maxlen=5000)` 自动清理
- 定期清理过期会话（TTL: 24h）
- ✅ 移除 `_active_executions` 和 `_stream_states` 内存占用

---

## 附录：关键代码位置

| 功能 | 文件路径 | 描述 |
|------|---------|------|
| State 定义 | `src/orchestration/main_graph.py` | VillagePlanningState + metadata |
| 后台执行 | `backend/api/planning.py` | `_execute_graph_in_background` |
| 持久化去重 | `backend/api/planning.py` | published_layers 检查和更新 |
| Checkpoint 重建 | `backend/api/planning.py` | `_rebuild_events_from_checkpoint` |
| SSE 订阅 | `backend/api/planning.py` | `subscribe_session` |
| 执行状态管理 | `backend/database/operations_async.py` | `is_execution_active_async` 等 |
| Status API | `backend/api/planning.py` | `get_session_status` (含 version) |
| 版本化同步 | `frontend/src/contexts/UnifiedPlanningContext.tsx` | `syncBackendState` |
| TaskController | `frontend/src/controllers/TaskController.tsx` | SSE 连接管理 |
| ChatPanel | `frontend/src/components/chat/ChatPanel.tsx` | 事件处理 |