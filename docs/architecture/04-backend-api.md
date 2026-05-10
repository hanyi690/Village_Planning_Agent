# 后端 API 架构

本文档详细说明后端 API 路由结构和 SSE 管理机制。

> **更新日期**: 2026-05-10
> **版本**: v3.4 (报告端点扩展 — 历史版本 + 跨会话查询)

## 目录

- [API 端点一览](#api-端点一览)
- [核心端点详解](#核心端点详解)
- [数据模型](#数据模型)
- [SSE 事件流](#sse-事件流)
- [关键文件路径](#关键文件路径)

---

## API 端点一览

### Session 端点（核心）

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/sessions` | POST | 创建规划会话 |
| `/api/sessions/{id}/stream` | GET | SSE 事件流 |
| `/api/sessions/{id}/sync` | GET | 断线重连同步 |
| `/api/sessions/{id}/status` | GET | 会话状态查询 |
| `/api/sessions/{id}/feedback` | POST | 反馈接口（审批/修订/对话） |
| `/api/sessions/{id}/checkpoints` | GET | 检查点列表 |
| `/api/sessions/{id}/resume/{checkpoint_id}` | POST | 从检查点恢复 |
| `/api/sessions/{id}/reports/{dim_key}` | GET | 维度报告全文（支持 `?version=N` 查历史版本） |
| `/api/sessions/{id}/reports/{dim_key}/versions` | GET | 维度版本历史摘要列表 |
| `/api/sessions/{id}/layer/{layer}/reports` | GET | 层级报告批量获取 |
| `/api/sessions/{id}` | DELETE | 删除会话 |
| `/api/projects/{name}/reports/{dim_key}` | GET | 按项目名跨会话查询报告 |

### 基础端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/health` | GET | 服务健康检查 |

---

## 核心端点详解

### 1. 创建会话

```python
# backend/app/api/session_routes.py
@router.post("/api/sessions", response_model=SessionCreateResponse)
async def create_session(
    background_tasks: BackgroundTasks,
    project_name: str = Form(..., description="项目名称"),
    village_name: str = Form("", description="村庄名称"),
    task_description: str = Form("制定村庄发展规划", description="任务描述"),
    constraints: str = Form("无特殊约束", description="约束条件"),
    step_mode: bool = Form(False, description="分步执行模式"),
    village_data: str = Form("", description="村庄基础数据（文本）"),
    village_data_files: List[UploadFile] = File(None, description="村庄数据文件"),
    task_files: List[UploadFile] = File(None, description="任务描述文件"),
    constraint_files: List[UploadFile] = File(None, description="约束条件文件"),
):
    """创建新规划会话 - 支持 multipart/form-data 文件上传（按来源区分）"""
```

**请求方式**: `multipart/form-data`（不是 JSON）

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `project_name` | str (Form) | 是 | 项目名称 |
| `village_data` | str (Form) | 否 | 村庄基础数据文本（可与文件并存，会合并） |
| `village_name` | str (Form) | 否 | 村庄名称 |
| `task_description` | str (Form) | 否 | 任务描述（默认"制定村庄发展规划"） |
| `constraints` | str (Form) | 否 | 约束条件（默认"无特殊约束"） |
| `step_mode` | bool (Form) | 否 | 分步执行模式 |
| `village_data_files` | File[] | 否 | 村庄数据文件（docx/pdf/txt 等，内容合并到 village_data） |
| `task_files` | File[] | 否 | 任务描述文件（覆盖 task_description 文本） |
| `constraint_files` | File[] | 否 | 约束条件文件（覆盖 constraints 文本） |

**文件处理流程**：

1. 上传文件保存到 `data/uploads/{session_id}/` 目录
2. 文档类文件（docx/pdf/txt/md 等）通过 `MarkItDownLoader` 提取文本：
   - `village_data_files` → 文本追加到 `village_data`
   - `task_files` → 文本覆盖 `task_description`
   - `constraint_files` → 文本覆盖 `constraints`
3. 生成 `UploadedFileMeta` 列表传入初始状态
4. 验证合并后的 `village_data` ≥ 10 字符

**数据验证**：合并后 `village_data` 必须 ≥ 10 字符，否则返回 400

```
    initial_state = PlanningRuntimeService.build_initial_state(
        project_name=project_name,
        village_data=parsed_content,
        village_name=village_name,
        task_description=task_description,
        constraints=constraints,
        session_id=session_id,
        stream_mode=True,
        step_mode=step_mode,
        uploaded_files=uploaded_files if uploaded_files else None,
    )

    background_tasks.add_task(
        PlanningRuntimeService._trigger_planning_execution,
        session_id, initial_state
    )

    return SessionCreateResponse(
        session_id=session_id,
        stream_url=f"/api/sessions/{session_id}/stream",
        status=TaskStatus.running
    )
```

---

### 2. SSE 事件流

```python
@router.get("/api/sessions/{session_id}/stream")
async def stream_events(session_id: str):
    """SSE 事件流端点"""
    async def event_generator():
        queue = await PlanningRuntimeService.subscribe_with_history(session_id)
        try:
            # 发送连接确认
            yield sse_manager.format_sse({
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            })

            # 状态同步已移除 — 前端通过 REST GET /status 获取基准状态
            # 重连时通过 GET /sync?from_seq=N 追补遗漏的增量事件

            # 事件循环
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if event.get("type") in ["completed", "error"]:
                        yield sse_manager.format_sse(event)
                        break
                    yield sse_manager.format_sse(event)
                except asyncio.TimeoutError:
                    yield sse_manager.format_sse({
                        "type": "heartbeat",
                        "timestamp": datetime.now().isoformat()
                    })
        except asyncio.CancelledError:
            pass
        finally:
            await sse_manager.unsubscribe(session_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
```

**SSE 消息格式**：

```
event: {type}
data: {"type": "...", "session_id": "...", ...}

```

---

### 3. 断线重连同步

```python
@router.get("/api/sessions/{session_id}/sync")
async def sync_events(session_id: str, from_seq: int = 0):
    """断线重连同步端点"""
    if not sse_manager.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    events = sse_manager.get_events_from_seq(session_id, from_seq)
    return {
        "events": events,
        "last_seq": sse_manager.get_last_seq(session_id),
        "from_seq": from_seq
    }
```

**重连流程**（串行化，消除竞争）：

1. SSE 断开 → 前端记录 `last_seq`
2. 重连时串行执行：
   - **先** `GET /api/sessions/{id}/status` → 获取基准状态（phase, reports 等）
   - **再** `GET /api/sessions/{id}/sync?from_seq={last_seq}` → 追补遗漏的增量事件
3. SSE 重连 → 继续实时流

> **架构决策**: 重连时 `getStatus` 和 `syncEvents` 必须串行执行，先获取基准状态再追补增量事件。
> 此前并行调用导致 checkpoint 空状态覆盖事件数据，造成 UI 闪烁/内容消失。

---

### 4. 反馈接口（整合端点）

```python
class FeedbackRequest(BaseModel):
    """反馈请求"""
    feedback: Optional[str] = Field(None, description="反馈内容")
    dimensions: Optional[List[str]] = Field(None, description="需修订的维度列表")
    message: Optional[str] = Field(None, description="对话消息")
    approve: bool = Field(False, description="批准当前层级继续")


@router.post("/api/sessions/{session_id}/feedback")
async def submit_feedback(session_id: str, request: FeedbackRequest):
    """提交反馈"""
    state = await PlanningRuntimeService.aget_state_values(session_id)

    # 审批：批准当前层级继续执行
    if request.approve and state.get("pause_after_step", False):
        await PlanningRuntimeService.aupdate_state(session_id, {
            "pause_after_step": False,
            "previous_layer": 0
        })
        asyncio.create_task(
            PlanningRuntimeService._trigger_planning_execution(session_id)
        )
        return {"status": "approved"}

    # 修订：触发指定维度重分析
    if request.feedback and request.dimensions:
        await PlanningRuntimeService.aupdate_state(session_id, {
            "human_feedback": request.feedback,
            "need_revision": True,
            "revision_target_dimensions": request.dimensions,
        })
        asyncio.create_task(
            PlanningRuntimeService._trigger_planning_execution(session_id)
        )
        return {"status": "revision_started", "dimensions": request.dimensions}

    # 对话：追加消息到会话
    if request.message:
        from langchain_core.messages import HumanMessage
        await PlanningRuntimeService.aupdate_state(session_id, {
            "messages": [HumanMessage(content=request.message)]
        })
        asyncio.create_task(
            PlanningRuntimeService._trigger_planning_execution(session_id)
        )
        return {"status": "message_accepted"}

    return {"status": "no_action"}
```

**三种反馈模式**：

| 模式 | 参数组合 | 说明 |
|------|----------|------|
| 审批 | `approve=true` | 批准当前层级，继续执行 |
| 修订 | `feedback + dimensions` | 触发指定维度级联重分析 |
| 对话 | `message` | 追加用户消息到会话 |

---

### 5. 检查点列表

```python
@router.get("/api/sessions/{session_id}/checkpoints")
async def get_checkpoints(session_id: str):
    """获取检查点列表"""
    history = await checkpoint_service.get_checkpoint_history(session_id)
    checkpoints = []
    for entry in history:
        values = entry.get("values", {})
        checkpoints.append({
            "checkpoint_id": entry.get("checkpoint_id", ""),
            "phase": values.get("phase", "init"),
            "layer": values.get("previous_layer", 0),
        })
    return {
        "session_id": session_id,
        "checkpoints": checkpoints,
        "count": len(checkpoints)
    }
```

---

### 6. 从检查点恢复

```python
@router.post("/api/sessions/{session_id}/resume/{checkpoint_id}")
async def resume_from_checkpoint(session_id: str, checkpoint_id: str):
    """从检查点恢复"""
    target_state = None
    async for snapshot in PlanningRuntimeService.aget_state_history(session_id):
        if snapshot.config.get("configurable", {}).get("checkpoint_id", "") == checkpoint_id:
            target_state = snapshot
            break

    if not target_state:
        raise HTTPException(status_code=404, detail=f"Checkpoint not found: {checkpoint_id}")

    layer = target_state.values.get("previous_layer", 1) or 1
    sse_manager.append_event(session_id, {
        "type": "resumed",
        "checkpoint_id": checkpoint_id,
        "layer": layer
    })

    asyncio.create_task(
        PlanningRuntimeService._trigger_planning_execution(session_id)
    )
    return {"status": "resumed", "checkpoint_id": checkpoint_id, "layer": layer}
```

---

### 7. 维度报告全文

```python
@router.get("/api/sessions/{session_id}/reports/{dim_key}")
async def get_dimension_report(session_id: str, dim_key: str, version: Optional[int] = None):
    """获取维度报告全文，支持历史版本查询（?version=N）"""
    # 查历史版本：优先使用 DimensionRevision 表
    if version is not None:
        revisions = await get_dimension_revisions_async(
            session_id=session_id, dimension_key=dim_key, limit=100
        )
        for rev in revisions:
            if rev.get("version") == version:
                return {
                    "session_id": session_id,
                    "dimension_key": dim_key,
                    "layer": rev.get("layer"),
                    "content": rev.get("content"),
                    "version": version,
                    "created_at": rev.get("created_at"),
                }
        raise HTTPException(status_code=404, detail=f"Version {version} not found for dimension: {dim_key}")

    # 默认：从 checkpoint 读取当前内容（保持向后兼容）
    state = await PlanningRuntimeService.aget_state_values(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    reports = state.get("reports", {})
    for layer_key in ["layer1", "layer2", "layer3"]:
        if dim_key in reports.get(layer_key, {}):
            return {
                "session_id": session_id,
                "dimension_key": dim_key,
                "layer": int(layer_key[-1]),
                "content": reports[layer_key][dim_key]
            }

    raise HTTPException(status_code=404, detail=f"Report not found: {dim_key}")
```

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `version` | int (query) | 否 | 历史版本号，不传则返回当前 checkpoint 中的报告 |

**数据源优先级**：
- 不传 `version`：从 LangGraph checkpoint 读取（现有行为）
- 传 `version=N`：从 `DimensionRevision` 数据库表读取指定版本

---

### 8. 维度版本历史列表

```python
@router.get("/api/sessions/{session_id}/reports/{dim_key}/versions")
async def get_dimension_report_versions(session_id: str, dim_key: str):
    """列出指定维度所有历史版本摘要（不含完整内容）"""
    revisions = await get_dimension_revisions_async(
        session_id=session_id, dimension_key=dim_key
    )
    if not revisions:
        raise HTTPException(status_code=404, detail=f"No revisions found for dimension: {dim_key}")

    return {
        "session_id": session_id,
        "dimension_key": dim_key,
        "versions": [
            {
                "version": r["version"],
                "layer": r["layer"],
                "created_at": r["created_at"],
                "reason": r["reason"],
            }
            for r in revisions
        ],
    }
```

**响应格式**（不含完整 content，仅摘要）：

```json
{
  "session_id": "...",
  "dimension_key": "location",
  "versions": [
    {"version": 3, "layer": 1, "created_at": "2026-05-10T...", "reason": "用户反馈修订"},
    {"version": 2, "layer": 1, "created_at": "2026-05-10T...", "reason": "AI 自动优化"},
    {"version": 1, "layer": 1, "created_at": "2026-05-10T...", "reason": "初始生成"}
  ]
}
```

**数据源**：`DimensionRevision` 表 → `get_dimension_revisions_async()` (operations.py:896)

---

### 9. 按项目名跨会话查询报告

```python
@router.get("/api/projects/{project_name}/reports/{dim_key}")
async def get_project_dimension_report(
    project_name: str,
    dim_key: str,
    session_id: Optional[str] = None,
    version: Optional[int] = None,
):
    """通过项目名跨会话查询维度报告，可选指定 session_id 和 version"""
    if version is not None and not session_id:
        raise HTTPException(status_code=400, detail="version parameter requires session_id")

    if session_id:
        # 指定会话 + 可选版本
        if version is not None:
            revisions = await get_dimension_revisions_async(
                session_id=session_id, dimension_key=dim_key, limit=100
            )
            for rev in revisions:
                if rev.get("version") == version:
                    return {
                        "project_name": project_name,
                        "session_id": session_id,
                        "dimension_key": dim_key,
                        "layer": rev.get("layer"),
                        "content": rev.get("content"),
                        "version": version,
                        "created_at": rev.get("created_at"),
                    }
            raise HTTPException(status_code=404, detail=f"Version {version} not found for dimension: {dim_key}")

        # 指定会话 + 当前 checkpoint
        state = await PlanningRuntimeService.aget_state_values(session_id)
        # ... 查找并返回报告 ...

    # 默认：取该项目最新会话的当前 checkpoint 报告
    sessions = await list_planning_sessions_async(project_name=project_name, limit=1)
    if not sessions:
        raise HTTPException(status_code=404, detail=f"No sessions found for project: {project_name}")

    latest_session_id = sessions[0]["session_id"]
    # ... 查找并返回报告 ...
```

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | str (query) | 否 | 指定会话 ID |
| `version` | int (query) | 否 | 历史版本号，需同时传 `session_id` |

**查询优先级**：
1. 传 `session_id` + `version=N` → `DimensionRevision` 表
2. 传 `session_id` 不传 `version` → 该会话 checkpoint
3. 都不传 → 该项目最新会话的 checkpoint

**复用函数**：
- `list_planning_sessions_async(project_name=...)` (operations.py:243)
- `PlanningRuntimeService.aget_state_values()`
- `get_dimension_revisions_async()` (operations.py:896)

**curl 示例**：
```bash
# 按项目名取最新报告
curl "http://localhost:8000/api/projects/金田村/reports/location"

# 指定会话
curl "http://localhost:8000/api/projects/金田村/reports/location?session_id={id}"

# 指定会话 + 历史版本
curl "http://localhost:8000/api/projects/金田村/reports/location?session_id={id}&version=2"
```

---

### 10. 删除会话

```python
@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    from app.services.session import session_service
    result = await session_service.delete_session(session_id)
    return {
        "message": f"Session {session_id} deleted",
        "deleted_checkpoints": result.get("checkpoint", False)
    }
```

---

### 11. 会话状态查询

```python
@router.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """获取会话状态"""
    from app.database.operations import get_planning_session_async
    db_session = await get_planning_session_async(session_id)
    if not db_session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
    state = dict(checkpoint_state.values) if checkpoint_state and checkpoint_state.values else {}
    return state_to_ui_status(state, db_session)
```

---

### 12. 层级报告批量获取

```python
@router.get("/api/sessions/{session_id}/layer/{layer}/reports")
async def get_layer_reports(session_id: str, layer: int):
    """获取层级报告"""
    if layer not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}")
    return await checkpoint_service.get_layer_reports(session_id, layer)
```

---

### 健康检查端点

```python
# backend/app/api/routes.py
@router.get("/api/health", tags=["Health"])
async def unified_health_check():
    """Unified health check endpoint"""
    return {
        "status": "healthy",
        "service": "village-planning-backend",
        "version": "2.0.0",
        "modules": ["session", "data", "files", "knowledge"],
        "architecture": "SSE-single-channel"
    }
```

---

## 数据模型

### 核心请求模型

```python
# backend/app/api/schemas.py

class TaskStatus(str, Enum):
    """任务状态枚举"""
    pending = "pending"
    running = "running"
    paused = "paused"
    reviewing = "reviewing"
    revising = "revising"
    completed = "completed"
    failed = "failed"


class ImageSourceType(str, Enum):
    """图片来源类型"""
    upload = "upload"       # 用户直接上传
    embedded = "embedded"   # 文档内嵌图片


class ImageData(BaseModel):
    """图片数据模型（用于多模态消息）"""
    image_base64: str
    image_format: str           # jpeg, png, gif, webp
    source_type: ImageSourceType
    source_filename: Optional[str]
    width: Optional[int]
    height: Optional[int]
```

### 文件上传模型

```python
# 文件类型标识
UploadedFileType = Literal[
    "document", "geojson", "shapefile", "kml", "gis_file",
    "village_data", "task_description", "constraint",
]


class UploadedFileMeta(BaseModel):
    """上传文件元数据（存入 initial_state）"""
    filename: str               # 原始文件名
    file_type: UploadedFileType # 文件用途分类
    path: str                   # 服务器保存路径
    data_type: Optional[str]    # 数据子类型
    size_bytes: int             # 文件大小（字节）


class FileUploadResponse(BaseModel):
    """文件上传响应"""
    success: bool
    filename: str
    content: str
    size: int
    message: str
```

**文件类型说明**：

| file_type | 对应请求参数 | 用途 |
|-----------|-------------|------|
| `village_data` | `village_data_files` | 村庄基础数据、村情台账、调查报告等 |
| `task_description` | `task_files` | 任务书、设计委托书等 |
| `constraint` | `constraint_files` | 上位规划、政策文件、法规标准等 |
| `document` | (文档解析后) | 通用文档类型 |
| `gis_file` | (间接) | 空间数据文件 |

### 会话创建/状态模型

```python
class StartPlanningRequest(BaseModel):
    """启动规划会话请求 (JSON 模式，保留兼容)"""
    project_name: str
    village_data: str
    village_name: str
    task_description: str
    constraints: str
    enable_review: bool
    stream_mode: bool
    step_mode: bool
    images: Optional[List[ImageData]]


class SessionCreateResponse(BaseModel):
    """创建会话响应"""
    session_id: str
    stream_url: str
    status: str


class SessionStatusResponse(BaseModel):
    """会话状态响应"""
    session_id: str
    status: str
    current_layer: Optional[int]
    previous_layer: Optional[int]
    created_at: Optional[str]
    progress: Optional[float]
    layer_1_completed: bool
    layer_2_completed: bool
    layer_3_completed: bool
    pause_after_step: bool
    execution_complete: bool
    execution_error: Optional[str]
    messages: List[Dict[str, Any]]
    ui_messages: List[Dict[str, Any]]
    revision_history: List[Dict[str, Any]]
    last_checkpoint_id: str
```

---

## SSE 事件流

### SSE Manager 核心结构

```python
# backend/app/services/sse.py
class SSEManager:
    """SSE 事件管理器"""

    def __init__(self):
        self._queues: Dict[str, List[asyncio.Queue]] = {}
        self._events: Dict[str, List[Dict]] = {}
        self._seq: Dict[str, int] = {}

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        """订阅事件队列"""

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue):
        """取消订阅"""

    async def emit(self, session_id: str, event: Dict):
        """发送事件到所有订阅者"""

    def format_sse(self, event: Dict) -> str:
        """格式化为 SSE 消息"""
        event_type = event.get("type", "message")
        data = json.dumps(event)
        return f"event: {event_type}\ndata: {data}\n\n"

    def get_events_from_seq(self, session_id: str, from_seq: int) -> List[Dict]:
        """获取指定序列号之后的事件"""
```

### SSE 事件类型

完整事件类型定义见 [terminology.md#SSE事件类型](./terminology.md#sse事件类型)

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| Session 端点 | `backend/app/api/session_routes.py` |
| 路由聚合 | `backend/app/api/routes.py` |
| 数据模型 | `backend/app/api/schemas.py` |
| Services 入口 (懒加载) | `backend/app/services/__init__.py` |
| GIS 服务 | `backend/app/services/modules/gis/service.py` |
| RAG 服务 | `backend/app/services/modules/rag/service.py` |
| SSE 管理 | `backend/app/services/sse.py` |
| Checkpoint 服务 | `backend/app/services/checkpoint.py` |
| 运行时服务 | `backend/app/services/runtime.py` |

> **注意**: `GisService` 和 `RagService` 通过 `__init__.py` 的 `__getattr__` 懒加载导出。
> 不要直接 import 子模块路径；使用 `from app.services import GisService, RagService`。

完整文件索引：[file-index.md](./file-index.md)

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - Agent 与 API 交互
- [05-frontend-state](./05-frontend-state.md) - 前端 SSE 处理
- [terminology](./terminology.md) - SSE 事件定义

---

## 历史变更

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v3.4 | 2026-05-10 | 报告端点扩展：`?version=N` 历史版本查询 + `/versions` 版本列表 + `/api/projects/{name}/reports/{key}` 跨会话查询 |
| v3.3 | 2026-05-10 | SSE 架构优化：删除 `state_sync` 事件（消除 AIMessage 序列化崩溃）；前端重连串行化 `getStatus` → `syncEvents` |
| v3.2 | 2026-05-09 | `status_files`/`other_files` 表单字段合并为 `village_data_files`，删除 `other` 子目录 |
| v3.1 | 2026-05-09 | Services 模块改为 `__getattr__` 懒加载；删除 `gis_service.py`/`rag_service.py` shim 文件 |
| v3.0 | 2026-05-09 | 路径前缀从 `/api/planning/` 改为 `/api/sessions/`；整合 chat/review 为 feedback；新增 delete/status 端点 |
| v2.0 | 2026-05-08 | 架构重组，统一 Session API |
| v1.0 | 2026-05-07 | 初始版本 |