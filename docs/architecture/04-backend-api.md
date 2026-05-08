# 后端API与SSE架构

本文档详细说明后端API路由结构和SSE管理机制。

## 目录

- [API端点一览](#api端点一览)
- [核心端点详解](#核心端点详解)
- [SSEManager类设计](#ssemanager类设计)
- [服务层架构](#服务层架构)

---

## API端点一览

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/planning/start` | POST | 启动规划会话 |
| `/api/planning/stream/{session_id}` | GET | SSE事件流 |
| `/api/planning/stream/{session_id}/sync` | GET | SSE重连同步 |
| `/api/planning/status/{session_id}` | GET | 状态查询 |
| `/api/planning/chat/{session_id}` | POST | 对话交互 |
| `/api/planning/review/{session_id}` | POST | 审查操作 |
| `/api/planning/checkpoint/{session_id}` | GET | 检查点列表 |
| `/api/planning/message/{session_id}` | GET/POST | 消息管理 |
| `/api/planning/resume` | POST | 从checkpoint恢复 |
| `/api/planning/sessions/{id}/layer/{layer}/reports` | GET | 层级报告 |
| `/api/planning/sessions/{id}/dimensions/run` | POST | 手动触发维度 |
| `/api/planning/sessions/{id}/dimensions/{key}` | GET | 维度内容 |

---

## 核心端点详解

### 启动规划会话

```python
# backend/api/planning/startup.py
@router.post("/api/planning/start")
async def start_planning(request: StartPlanningRequest):
    """启动新规划会话"""
    session_id = str(uuid.uuid4())

    # 初始化状态
    initial_state = create_initial_state(
        session_id=session_id,
        project_name=request.village_name,
        village_data=request.village_data
    )

    # 存储到数据库
    await create_planning_session(session_id, initial_state)

    # 启动异步执行
    asyncio.create_task(run_planning_async(session_id))

    return {"session_id": session_id}
```

### SSE流端点

```python
# backend/api/planning/stream.py
@router.get("/api/planning/stream/{session_id}")
async def stream_planning(session_id: str):
    """SSE事件流端点"""
    async def event_generator():
        queue = await sse_manager.subscribe(session_id)

        # 发送connected事件
        yield format_sse({"type": "connected", "session_id": session_id})

        while True:
            event = await asyncio.wait_for(queue.get(), timeout=30.0)

            if event.get("type") in ["completed", "error"]:
                yield format_sse(event)
                break

            yield format_sse(event)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### SSE重连同步

```python
@router.get("/api/planning/stream/{session_id}/sync")
async def sync_events(session_id: str, from_seq: int = 0):
    """获取错过的事件"""
    events = sse_manager.get_events_from_seq(session_id, from_seq)
    return {"events": events, "last_seq": sse_manager.get_last_seq(session_id)}
```

**重连流程**：
1. SSE断开 -> 前端记录lastProcessedSeq
2. 重连 -> 调用sync端点获取错过事件
3. 合并事件 -> 继续正常处理

---

## SSEManager类设计

### 核心结构

```python
# backend/services/sse_manager.py
class SSEManager:
    """SSE事件管理器"""

    def __init__(self):
        self._queues: Dict[str, List[asyncio.Queue]] = {}
        self._events: Dict[str, List[Dict]] = {}
        self._seq: Dict[str, int] = {}

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        """订阅事件队列"""
        if session_id not in self._queues:
            self._queues[session_id] = []
        queue = asyncio.Queue()
        self._queues[session_id].append(queue)
        return queue

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue):
        """取消订阅"""
        if session_id in self._queues:
            self._queues[session_id].remove(queue)

    async def emit(self, session_id: str, event: Dict):
        """发送事件到所有订阅者"""
        if session_id not in self._queues:
            return

        # 记录事件序列
        seq = self._seq.get(session_id, 0) + 1
        event["seq"] = seq
        self._seq[session_id] = seq
        self._events[session_id].append(event)

        # 分发到所有队列
        for queue in self._queues[session_id]:
            await queue.put(event)

    def format_sse(self, event: Dict) -> str:
        """格式化为SSE消息"""
        event_type = event.get("type", "message")
        data = json.dumps(event)
        return f"event: {event_type}\ndata: {data}\n\n"
```

### 事件存储

```python
def get_events_from_seq(self, session_id: str, from_seq: int) -> List[Dict]:
    """获取指定序列号之后的事件"""
    events = self._events.get(session_id, [])
    return [e for e in events if e.get("seq", 0) > from_seq]
```

---

## 服务层架构

### CheckpointService

```python
# backend/services/checkpoint_service.py
class CheckpointService:
    """Checkpoint持久化服务"""

    async def save_checkpoint(self, session_id: str, state: Dict):
        """保存检查点"""
        checkpoint_id = generate_checkpoint_id()
        await save_to_db(session_id, checkpoint_id, state)
        return checkpoint_id

    async def load_checkpoint(self, session_id: str) -> Dict:
        """加载最新检查点"""
        return await load_latest_from_db(session_id)

    async def rebuild_session_from_db(self, session_id: str):
        """从数据库重建会话"""
        state = await self.load_checkpoint(session_id)
        # 重建SSE队列和状态
```

### PlanningRuntimeService

```python
# backend/services/planning_runtime_service.py
class PlanningRuntimeService:
    """规划执行服务"""

    async def run_planning_async(self, session_id: str):
        """异步执行规划"""
        graph = create_unified_planning_graph(checkpointer)

        async for event in graph.astream(state, stream_mode=["values", "checkpoints"]):
            # 发送SSE事件
            await sse_manager.emit(session_id, event)
```

---

## SSE事件类型

SSE事件类型定义见 [terminology.md#SSE事件类型](./terminology.md#sse事件类型)

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| SSE管理 | `backend/services/sse_manager.py` |
| 启动路由 | `backend/api/planning/startup.py` |
| SSE流路由 | `backend/api/planning/stream.py` |
| Checkpoint服务 | `backend/services/checkpoint_service.py` |
| 运行时服务 | `backend/services/planning_runtime_service.py` |

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - Agent与API交互
- [05-frontend-state](./05-frontend-state.md) - 前端SSE处理
- [terminology](./terminology.md) - SSE事件定义