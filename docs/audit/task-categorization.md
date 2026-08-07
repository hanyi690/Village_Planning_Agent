# Task Categorization Audit (P3-7)

Categorizes every `asyncio.create_task` in `app/api/session_routes.py` so the
fire-and-forget ones are routed through `TaskSupervisor` (which offers
per-session deduplication and cancellation) instead of bare global tasks.

## Call sites (current line numbers verified in source)

| # | Line | Call | Request-scoped? | Fire-and-forget? | Dedup key |
|---|------|------|-----------------|------------------|-----------|
| 1 | 581 | `resume_from_interrupt(session_id, resume_data={action: approve})` | No | Yes | `session_id` |
| 2 | 608 | `resume_from_interrupt(session_id, resume_data={action: reject, ...}, state_updates=...)` | No | Yes | `session_id` |
| 3 | 658 | `resume_from_interrupt(session_id, resume_data={action: message_injected, ...}, state_updates=...)` | No | Yes | `session_id` |
| 4 | 665 | `resume_from_interrupt(session_id, resume_data={action: message_injected, ...}, state_updates=...)` | No | Yes | `session_id` |
| 5 | 688 | `_trigger_planning_execution(session_id)` | No | Yes | `session_id` |
| 6 | 696 | `_trigger_planning_execution(session_id)` | No | Yes | `session_id` |
| 7 | 768 | `_trigger_planning_execution(session_id, checkpoint_id=..., state_values=...)` | No | Yes | `session_id` |
| 8 | 1074 | `resume_from_interrupt(session_id, resume_data={action: approve})` (step-mode auto-approve) | No | Yes | `session_id` |

## Rationale

- **Request-scoped?** No. Each call launches long-running LangGraph execution
  (resume from interrupt or trigger a new planning execution). The HTTP handler
  must return immediately with a "started"/"accepted" acknowledgement; awaiting
  the coroutine would block the response until the whole graph run finished.

- **Fire-and-forget?** Yes. All 8 should outlive the request. They are graph
  execution side-effects triggered by user feedback / resume / step-mode
  toggles.

- **Cancellable?** Yes, via `TaskSupervisor.cancel(key)` — useful at shutdown
  and when a newer execution supersedes an in-flight one.

- **Deduplication?** Yes. At most one execution per session should run at a
  time. Each call is keyed by `session_id`. `TaskSupervisor.create_task`
  cancels any previously-running task for the same key before starting the new
  one, preventing concurrent overlapping graph runs for the same session.

## Non-changes

- `asyncio.gather` (line 426) is a parallel await, not a fire-and-forget task.
- `asyncio.wait_for` / `asyncio.TimeoutError` / `asyncio.CancelledError`
  (lines 541, 546, 548) are stream-await control flow, not background tasks.

## Routing

Every fire-and-forget call is replaced with:

    supervisor = CompositionRoot.get_task_supervisor()
    supervisor.create_task(session_id, coro)