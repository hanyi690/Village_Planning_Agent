# Backend official-practice audit (2026-08-10)

> This audit separates official target practice from repository facts. A `符合` row means the implementation was verified by reading code and/or running a test; a `部分符合` row means the basic pattern exists but an important production boundary is incomplete. It does not claim a complete end-to-end planning run.

## Evidence baseline

The design decisions below were compared against current official documentation through Context7 and Exa:

- FastAPI: [lifespan](https://fastapi.tiangolo.com/advanced/events), [dependencies with `yield`](https://fastapi.tiangolo.com/advanced/advanced-dependencies/), [streaming responses](https://fastapi.tiangolo.com/advanced/stream-data), and [testing lifespan](https://fastapi.tiangolo.com/advanced/testing-events).
- SQLAlchemy: [asyncio ORM/session](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) and the rule that one `AsyncSession` is not shared across concurrent tasks.
- LangGraph: [persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), and [event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming).

The selected target is: application-owned lifespan; one compiled persisted graph per runtime; stable `thread_id`; `Command(resume=...)` on the same graph; idempotent work around interrupts; one async database session per task; explicit write transaction boundaries; and SSE as a projection of persisted events rather than a source of truth.

## Findings

| Area | Status | Code evidence | Target / next action |
|---|---|---|---|
| FastAPI lifespan | 符合 | `backend/app/main.py:162` uses `@asynccontextmanager`; core startup is bounded and shutdown cancels tracked tasks and closes resources. | Keep all process resources in the lifespan. Add a lifecycle test around the real app when test isolation is available. |
| Readiness vs liveness | 符合 | `/health` is a liveness response in `main.py`; `/api/health` checks `app.state.readiness` in `backend/app/api/routes.py`. | Keep Docker readiness on `/api/health`; keep `/health` dependency-free. |
| SSE streaming | 部分符合 | `backend/app/api/route_modules/session_sse.py:18` uses `StreamingResponse`, heartbeat timeout, `CancelledError`, and `finally` unsubscribe. | Add typed event envelopes and a documented `seq`/replay contract. Do not hold database sessions over the network stream. |
| FastAPI dependency scope | 部分符合 | API routes call service-level `get_async_session()` contexts instead of injecting a DB session with `Depends`. | The service-level context is safe for current short CRUD operations; the ideal API boundary should expose an `Annotated[AsyncSession, Depends(...)]` dependency for request-scoped handlers where the session is actually needed. |
| Async SQLAlchemy engine ownership | 符合 | `backend/app/database/engine.py` now creates one process-local engine and resets the factory on disposal. Regression test: `backend/tests/core/test_backend_lifecycle_contract.py`. | App lifespan remains the owner; do not add per-request engines or ref-counted global sessions. |
| Async SQLAlchemy session ownership | 符合 | Every database operation opens its own context; `AsyncSessionLocal` is not shared between concurrent operations. The context rolls back on exceptions and no longer hides `commit()`. | Keep explicit `commit()` in write operations and use `async_sessionmaker.begin()` for future atomic multi-write services. |
| LangGraph persistence | 部分符合 | `backend/app/services/runtime.py:128-135` initializes one checkpointer and compiles the root and EXECUTE graphs once; `get_thread_config()` uses session `thread_id`. | EXECUTE currently invokes a separately compiled graph from a parent node with namespace `execute`; ideal state is a directly mounted subgraph with one parent-owned persistence boundary. |
| LangGraph HITL | 符合 | `backend/app/agent/bootstrap/graph.py:600-616` and `backend/app/agent/plan_state/completion_node.py:248-282` are the two intentional business interrupt points; both use `HumanInterrupt`, while `runtime.py:231-264` resumes with `Command(resume=...)` on the same thread. | Preserve the prepare/publish/wait/apply split, normalize legacy fields only at boundaries, and keep pre-interrupt work pure/idempotent. |
| LangGraph replay side effects | 部分符合 | HITL preparation/publish is designed to be idempotent, but L1/L2/L3 enrichment contains untracked `asyncio.create_task()` calls. | Route all background enrichment through the runtime task supervisor and make artifact writes idempotent before production replay is claimed. |
| Background task lifetime | 部分符合 | API launch paths use `PlanningRuntimeService`/task supervisor in several places, while worker enrichment still creates detached tasks. | No detached task may outlive a session/runtime; use stable task keys and cancel/await them in lifespan shutdown. |
| Response contracts | 部分符合 | Many routes use Pydantic response models, but several history/GIS routes return raw dictionaries and one planning-text route exposes exception text in a 500 detail. | Define stable response envelopes and hide provider/internal exception details in production responses. |
| CORS | 部分符合 | `main.py` uses explicit origins and credentials rather than wildcard origins. | Normalize whitespace, reject empty production origins, and keep credentials disabled unless browser auth requires them. |
| Health dependency graph | 未验证 | Static code confirms the two endpoints and readiness map; no isolated app lifespan smoke test was run in this pass. | Add a test using `with TestClient(app)` that verifies startup, readiness, and cleanup. |

## Immediate corrections made in this pass

1. Removed reference-counted engine lifetime and reset `AsyncSessionLocal` during disposal.
2. Removed the implicit commit from `get_async_session()`; writes already have explicit commits in the current CRUD layer.
3. Added regression tests for engine recreation, rollback, and the absence of hidden commits.
4. Added missing module READMEs for route modules, EXECUTE nodes/legacy helpers, encoding dictionaries, spatial evidence, and the main frontend features.
5. Corrected the target/current documentation boundary so an independently invoked EXECUTE graph is not described as a directly mounted parent subgraph.
6. Unified step-mode and post-L3 HUMAN payloads under `HumanInterrupt`; pending checkpoint payloads now feed the same backend UI projection and frontend store contract.
7. Added `ResumePlan` and pure checkpoint policy classification so `next`, pending interrupts, artifact checksums, and terminal states are no longer collapsed into one resume decision.

## Remaining P0/P1 work

- P0: prove one deterministic local end-to-end run from session input through `DeliveryManifest`; real provider connectivity is not a substitute for this test.
- P1: mount EXECUTE as a true subgraph or define an explicit, tested parent/child artifact boundary with one durable session cursor.
- P1: track all background tasks through the runtime supervisor and verify shutdown has no pending tasks.
- P1: freeze typed response envelopes for status, events, reports, artifacts, and errors.
- P1: remove unsafe candidate-pool fallback in SELECT and fail closed when GROUND cannot prove a target-specific spatial reference.
- P1: use `ResumePlan` parent-version checks to calculate the earliest invalid artifact and make SELECT→EXECUTE→DELIVER recovery deterministic.

## Verification performed

```text
pytest -o addopts="" --basetemp=backend/.pytest-lifecycle-tmp -q backend/tests/core/test_backend_lifecycle_contract.py
3 passed
pytest -o addopts="" --basetemp=backend/.pytest-human-interrupt-tmp -q backend/tests/core/test_human_interrupt_contract.py
5 passed
pytest -o addopts="" --basetemp=backend/.pytest-resume-final -q \
  backend/tests/core/test_resume_plan_contract.py \
  backend/tests/core/test_checkpoint_classification.py \
  backend/tests/core/test_human_interrupt_contract.py \
  backend/tests/core/test_backend_lifecycle_contract.py
13 passed
pytest -o addopts="" -x -q backend/tests/e2e/test_unified_graph_replay_e2e.py
26 passed
npm.cmd run type-check  # frontend/
passed
```

The Context7/Exa comparison also confirms the remaining boundary: LangGraph's
`thread_id`/`checkpoint_id` identify persisted graph position, while artifact
dependency invalidation is application policy. The project must not describe a
checkpoint cursor as a complete business resume plan. Official references:
[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
[LangGraph subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs),
and [LangGraph time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel).

The default project test configuration was not treated as proof of the complete product loop: it selects E2E tests and external-provider paths can require credentials or native GIS services.
