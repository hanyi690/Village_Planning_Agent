# Background Execution Architecture Design Plan

> **Status**: 🔄 **Partially Implemented**
>
> **Implementation Notes**:
> - Background execution using `asyncio.create_task` is implemented in `backend/api/planning.py`
> - The full `BackgroundTaskManager` class with event queue is NOT implemented
> - Current implementation uses direct event writing to session storage instead
> - This document is retained for reference but may not reflect current architecture
>
> **Last Reviewed**: 2026-02-10

## Executive Summary

Design and implement a robust background execution system that starts planning immediately when `start_planning` is called, while maintaining SSE streaming for progress updates and supporting disconnection/reconnection scenarios.

## Current Architecture Analysis

### Flow Today
```
Frontend                        Backend
  |                               |
  |-- POST /api/planning/start -->|  Create session, return session_id
  |                               |  (NO execution starts)
  |                               |
  |-- GET /api/planning/stream -->|  NOW graph execution starts
  |<-- SSE events ----------------|  stream_graph_execution() called
```

### Problems Identified
1. **No execution until SSE connects**: If frontend never connects, nothing happens
2. **User expectation mismatch**: Users expect planning to start immediately on button click
3. **Race conditions**: Timing issues between session creation and SSE connection
4. **Lost connections**: If SSE drops, execution state is lost
5. **Tight coupling**: SSE endpoint tightly coupled with execution logic

### Existing Infrastructure
- `_sessions`: Dict storing session state
- `_active_executions`: Dict preventing duplicate executions
- `_stream_states`: Dict tracking stream state (active/paused/completed)
- `_session_checkpointer`: Dict storing LangGraph checkpointers
- `stream_graph_execution()`: SSE streaming in `src/core/streaming.py`
- `rate_limiter`: Prevents duplicate project executions

## Architecture Decision: Hybrid Background Task + Event Queue

### Chosen Approach: asyncio.create_task with In-Memory Event Queue

**Rationale:**
- ✅ Minimal architectural changes
- ✅ Native async/await support (FastAPI is async)
- ✅ No external dependencies (Redis, Celery)
- ✅ Thread-safe with asyncio primitives
- ✅ Preserves existing SSE streaming logic
- ✅ Supports disconnection/reconnection scenarios
- ✅ Compatible with pause/resume workflows

**Why Not Other Approaches:**

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| FastAPI BackgroundTasks | Simple, built-in | Tied to request lifecycle, dies when request completes | ❌ Not suitable for long-running tasks |
| Celery + Redis | Production-grade, scalable | Heavy infrastructure, deployment complexity | ❌ Overkill for current scale |
| asyncio.create_task only | Native, simple | No event history for reconnections | ⚠️ Needs event queue enhancement |
| **Hybrid (Chosen)** | Best of both worlds | Requires queue management | ✅ **Recommended** |

## Detailed Architecture Design

### Core Components

#### 1. Background Task Manager (`backend/services/background_task_manager.py`)

```python
class BackgroundTaskManager:
    """
    Manages background execution of planning tasks
    - Starts execution immediately
    - Stores events in queue for SSE consumption
    - Handles disconnection/reconnection
    """
    
    def __init__(self):
        # Event storage: session_id -> list of events
        self._event_queues: Dict[str, asyncio.Queue] = {}
        
        # Task tracking: session_id -> asyncio.Task
        self._running_tasks: Dict[str, asyncio.Task] = {}
        
        # Completion tracking
        self._task_status: Dict[str, str] = {}  # pending/running/completed/failed
        
    async def start_execution(
        self, 
        session_id: str, 
        initial_state: Dict[str, Any],
        checkpointer
    ) -> None:
        """Start graph execution in background"""
        # Create event queue for this session
        self._event_queues[session_id] = asyncio.Queue(maxsize=1000)
        
        # Create background task
        task = asyncio.create_task(
            self._execute_graph(session_id, initial_state, checkpointer)
        )
        self._running_tasks[session_id] = task
        
    async def _execute_graph(self, session_id, initial_state, checkpointer):
        """Execute graph and push events to queue"""
        # Wrap existing stream_graph_execution logic
        # Capture SSE events and push to queue
        
    async def get_event_stream(self, session_id):
        """Generator for SSE to consume events"""
        # Yield events from queue
        # Handle reconnection scenarios
        
    def get_task_status(self, session_id) -> str:
        """Query current task status"""
```

#### 2. Modified Planning API (`backend/api/planning.py`)

**Changes to `/api/planning/start`:**
```python
@router.post("/api/planning/start")
async def start_planning(request: StartPlanningRequest):
    # 1. Create session (existing logic)
    session_id = _generate_session_id()
    initial_state = _build_initial_state(request, session_id)
    _sessions[session_id] = {...}
    
    # 2. NEW: Start background execution immediately
    from backend.services.background_task_manager import background_task_manager
    
    checkpointer = MemorySaver()
    _session_checkpointer[session_id] = checkpointer
    
    await background_task_manager.start_execution(
        session_id, 
        initial_state, 
        checkpointer
    )
    
    # 3. Return immediately
    return {
        "task_id": session_id,
        "status": TaskStatus.running,
        "message": "Planning started",
        "stream_url": f"/api/planning/stream/{session_id}"
    }
```

**Changes to `/api/planning/stream`:**
```python
@router.get("/api/planning/stream/{session_id}")
async def stream_planning(session_id: str):
    """
    SSE stream that consumes events from background task
    Handles:
    - Live streaming of active tasks
    - Replay of completed events for reconnections
    - Polling for not-yet-started tasks
    """
    from backend.services.background_task_manager import background_task_manager
    
    # Stream events from background task manager
    return await background_task_manager.get_event_stream(session_id)
```

#### 3. Event Queue Implementation

**Key Features:**
- **Bounded Queue**: Max 1000 events per session (prevent memory overflow)
- **TTL**: Events expire after 1 hour
- **Priority Events**: `layer_completed`, `pause`, `error` marked as critical
- **Replay Support**: On reconnection, replay missed events since last checkpoint

### State Management

#### Session Lifecycle States

```
pending    → Session created, background task starting
running    → Graph execution active
paused     → Waiting for user approval (step mode/review)
completed  → All layers finished successfully
failed     → Execution error
```

#### Stream Connection States

```
disconnected  → No SSE connection
connected     → SSE active, streaming live events
reconnecting  → Client reconnecting, replaying missed events
```

#### Data Structures

```python
# Enhanced session storage
_sessions[session_id] = {
    "session_id": str,
    "project_name": str,
    "status": TaskStatus,
    "created_at": datetime,
    "request": dict,
    "current_layer": int,
    "initial_state": dict,
    # NEW fields
    "background_task_started": bool,
    "last_event_sequence": int,  # For reconnection replay
    "checkpoint_events": List[dict],  # Critical events for replay
}

# Background task manager storage
_event_queues[session_id] = asyncio.Queue  # Live events
_task_status[session_id] = str  # Current task status
_running_tasks[session_id] = asyncio.Task  # Task handle
_event_history[session_id] = List[dict]  # Replay buffer (last 100 events)
```

## Implementation Plan

### Phase 1: Core Infrastructure (Priority: HIGH)

#### Step 1.1: Create BackgroundTaskManager
**File**: `backend/services/background_task_manager.py` (NEW)

**Structure**:
```python
import asyncio
import logging
from typing import Dict, Any, Optional, AsyncIterator
from datetime import datetime, timedelta
from langgraph.graph import StateGraph

logger = logging.getLogger(__name__)

class BackgroundTaskManager:
    """Singleton for managing background task execution"""
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        
        # Event storage
        self._event_queues: Dict[str, asyncio.Queue] = {}
        self._event_history: Dict[str, list] = {}  # Replay buffer
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._task_status: Dict[str, str] = {}
        self._task_results: Dict[str, Dict[str, Any]] = {}
        
        # Configuration
        self._max_queue_size = 1000
        self._history_max_size = 100  # Keep last 100 events for replay
        self._event_ttl_seconds = 3600  # 1 hour
        
        logger.info("[BackgroundTaskManager] Initialized")
```

**Key Methods**:
- `async def start_execution(session_id, initial_state, checkpointer)`
- `async def _execute_graph_and_capture_events(...)`
- `async def get_event_stream(session_id, last_sequence=None) → AsyncIterator`
- `def get_task_status(session_id) → str`
- `async def cancel_task(session_id)`
- `async def cleanup_session(session_id)`

#### Step 1.2: Modify Planning API Start Endpoint
**File**: `backend/api/planning.py` (MODIFY lines 283-364)

**Changes**:
```python
@router.post("/api/planning/start")
async def start_planning(request: StartPlanningRequest):
    # ... existing validation and session creation ...
    
    # AFTER creating initial_state and checkpointer:
    
    # NEW: Start background execution immediately
    from backend.services.background_task_manager import background_task_manager
    
    try:
        await background_task_manager.start_execution(
            session_id=session_id,
            initial_state=initial_state,
            checkpointer=checkpointer
        )
        logger.info(f"[Planning API] Background execution started for {session_id}")
    except Exception as e:
        logger.error(f"[Planning API] Failed to start background task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start execution: {str(e)}")
    
    # Update session to reflect background task started
    _sessions[session_id]["background_task_started"] = True
    _sessions[session_id]["status"] = TaskStatus.running
    
    # Return immediately (execution already running in background)
    return {
        "task_id": session_id,
        "status": TaskStatus.running,
        "message": "Planning started in background",
        "stream_url": f"/api/planning/stream/{session_id}",
        "execution_started": True  # NEW flag
    }
```

#### Step 1.3: Modify Planning API Stream Endpoint
**File**: `backend/api/planning.py` (MODIFY lines 367-469)

**Changes**:
```python
@router.get("/api/planning/stream/{session_id}")
async def stream_planning(session_id: str):
    """
    SSE stream consuming events from background task
    
    Supports:
    - Live streaming of active tasks
    - Replay of missed events (reconnection)
    - Status polling for pending tasks
    """
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        from backend.services.background_task_manager import background_task_manager
        
        # Check if background task supports reconnection
        last_sequence = _sessions[session_id].get("last_event_sequence", 0)
        
        # Return streaming response from background task manager
        return await background_task_manager.get_sse_stream(
            session_id=session_id,
            last_sequence=last_sequence
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Planning API] Stream error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Stream error: {str(e)}")
```

### Phase 2-7: Detailed Implementation

[Continues with detailed implementation steps for all phases as shown in the full plan...]

## Summary

### Key Benefits

1. **Immediate Execution**: Planning starts right away, no waiting for SSE
2. **Robust Reconnection**: Clients can disconnect and reconnect without losing progress
3. **Better UX**: Faster API response, background progress continues
4. **Scalability**: Event queue pattern supports future horizontal scaling
5. **Backwards Compatible**: Frontend works without changes

### Files to Modify

**New Files**:
- `backend/services/background_task_manager.py` (~300 lines)
- `tests/test_background_task_manager.py` (~400 lines)
- `tests/test_background_execution_integration.py` (~300 lines)
- `docs/background_execution_architecture.md` (~200 lines)
- `docs/background_execution_developer_guide.md` (~150 lines)

**Modified Files**:
- `backend/api/planning.py` (modify `start_planning` and `stream_planning`, ~50 lines changed)
- `frontend/src/hooks/useTaskSSE.ts` (optional reconnection support, ~30 lines)
- `frontend/src/lib/api.ts` (optional sequence parameter, ~10 lines)

### Estimated Effort

- Phase 1 (Core Infrastructure): 2-3 days
- Phase 2 (Event Capture): 2 days
- Phase 3 (Reconnection): 1-2 days
- Phase 4 (Pause/Resume): 1 day
- Phase 5 (Cleanup): 1 day
- Phase 6 (Testing): 2-3 days
- Phase 7 (Frontend): 1 day

**Total**: 10-13 days development + 3 days testing = **2 weeks**

### Risk Mitigation

1. **Feature Flag**: Disable background execution if issues arise
2. **Rollback Plan**: Revert to old behavior via environment variable
3. **Gradual Rollout**: Test in dev → staging → production
4. **Monitoring**: Track metrics closely after deployment
5. **Load Testing**: Verify performance under 100 concurrent sessions

### Success Criteria

- ✅ `/api/planning/start` responds in < 100ms
- ✅ Background execution starts within 50ms
- ✅ SSE receives events from background task
- ✅ Disconnection doesn't stop execution
- ✅ Reconnection replays missed events
- ✅ Pause/resume works correctly
- ✅ Rate limiter still prevents duplicates
- ✅ Memory usage < 200MB for 100 sessions
- ✅ Zero breaking changes to frontend
