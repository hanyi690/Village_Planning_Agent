# Official practice baseline (2026-08-06)

This audit records the framework decisions used to implement the target design. The design contract remains authoritative; documentation is changed only for factual corrections or to record an implementation decision.

| Area | Context7 / official source | Decision |
|---|---|---|
| LangGraph interrupts | [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | The node containing `interrupt()` is replayed from its beginning. Work before the interrupt is therefore pure or idempotent; pause events use a stable event id and are deduplicated. |
| LangGraph checkpoint continuation | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | A session's `thread_id` is the durable cursor. HITL resumes use `Command(resume=...)` on the same compiled graph and same thread; stable checkpoint replay uses the checkpoint's `checkpoint_id` with a normal graph invocation. We never rebuild a second graph or inject a copied full state. |
| LangGraph subgraphs | [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) | The parent graph owns the checkpointer and directly mounted EXECUTE subgraphs receive it. Different state schemas require an explicit adapter. |
| LangGraph retries | [Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api) | `RetryPolicy` is limited to transient infrastructure failures. Business gates remain explicit routed state transitions. |
| FastAPI lifecycle | [Lifespan](https://fastapi.tiangolo.com/advanced/events) | Database, checkpointer and graph resources are initialized and cleaned up in the application lifespan. Core startup failure is fail-fast. |
| FastAPI lifecycle tests | [Testing events](https://fastapi.tiangolo.com/advanced/testing-events) | Lifecycle tests use `with TestClient(app)` so startup and shutdown are both exercised. |
| Pytest configuration | [Pytest configuration](https://github.com/pytest-dev/pytest/blob/9.0.0/doc/en/reference/customize.md) | Core tests are selected with `testpaths`/`addopts`; `faulthandler_timeout` provides thread diagnostics. |
| Test timeout | [pytest-timeout](https://github.com/pytest-dev/pytest-timeout) | Version 2.3.1 and `timeout_method=thread` provide a hard exit and all-thread stack dump on Windows deadlocks. |
| Async startup bounds | [Python asyncio task docs](https://github.com/python/cpython/blob/v3.13.9/Doc/library/asyncio-task.rst) | `asyncio.timeout()` bounds the complete startup group and converts cancellation to a clear timeout failure. |
| Artifact replay checksums | [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | Because replay re-executes nodes, artifact writes use canonical sorted JSON checksums and existing revisions are reused; a changed checksum fails closed. |
| Real session lifecycle | [FastAPI testing events](https://fastapi.tiangolo.com/advanced/testing-events) | The core integration test creates a real multipart session inside `with TestClient(app)`, uses isolated SQLite, then runs the seven stage nodes with deterministic local adapters. |
| Configured LLM connectivity | Repository `.env` + `app.core.llm.create_llm` | Historical DashScope runs reached the configured endpoint, but the current key preflight returns `401 invalid_api_key`; real-session acceptance is therefore not claimed. The post-L3 PARSE COMPILE path remains deterministic by design. |
| MiniMax backup provider | [MiniMax OpenAI API compatibility](https://platform.minimaxi.com/docs/api-reference/text-openai-api), [text generation guide](https://platform.minimaxi.com/docs/guides/text-generation) | Add an explicit `minimax` provider through the existing `ChatOpenAI` factory using `https://api.minimaxi.com/v1`, `MINIMAX_API_KEY`, and `MiniMax-M2.7` by default. MiniMax documents `temperature` as `(0, 1]`, so the adapter clamps deterministic `0` to `0.01`. Provider switching is explicit and bounded; no automatic repeated fallback is introduced. |
| MiniMax structured auxiliary calls | Same OpenAI-compatible API contract | Instructor/summary and optional KG semantic confirmation must use the selected provider rather than a DashScope-only client. KG semantic confirmation is opt-in under MiniMax (`GIS_ENRICH_LLM_CONFIRM=true`); deterministic spatial binding remains the authoritative gate, preventing malformed auxiliary output from blocking the main graph. |
| RDFLib graph concurrency | [RDFLib Graph API](https://rdflib.readthedocs.io/en/stable/apidocs/rdflib.graph/), [RDFLib stores](https://rdflib.readthedocs.io/en/stable/plugins/) | Treat the default in-memory Graph as an isolated mutable object. Serialize construction, cloning, registration and query access; do not rely on CPython's GIL for cache safety. |
| Chroma embedded persistence | [Chroma system constraints](https://cookbook.chromadb.dev/core/system_constraints/), [deployment patterns](https://cookbook.chromadb.dev/running/deployment-patterns/) | Chroma documents same-process thread safety, but warns that a local PersistentClient path is not process-safe for concurrent writers. This service therefore serializes the complete synchronous query path (embedding + native HNSW/SQLite call) and keeps each test's runtime isolated; it does not replace Chroma with a fake store. |
| OpenAI-compatible synchronous client | [OpenAI Python resource management](https://github.com/openai/openai-python/blob/main/README.md) | Shared synchronous clients remain bounded by an application semaphore during L1 streaming. Client lifetime is owned by the runtime and request timeouts remain explicit; concurrency is not used as a substitute for a business retry. |
| Shapely geometry validity | [Shapely validation and make_valid](https://github.com/shapely/shapely/blob/main/docs/manual.md) | Check `is_valid` before GEOS predicates, retain `explain_validity` provenance for source audits, and use `validation.make_valid` at the spatial boundary. Because repair may return `MultiPolygon` or `GeometryCollection`, accept valid multipart output and fail closed for empty/unrecoverable results. |
| L3 timeout checkpoint continuation | [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | A provider stream timeout is recorded with the failed dimension, converted to a persisted HUMAN checkpoint, and an explicit approval clears only that transient fatal marker so the pending L3 worker resumes from the same thread. Completed dimensions are not replayed as a synthetic success. |

## Implementation baseline

- The canonical workflow remains `PARSE → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`.
- State carries a versioned `context_ref` and typed `artifact_refs`; large typed values are loaded from `ArtifactStore` at stage boundaries.
- EXECUTE is a directly mounted compiled subgraph. The deleted wrapper/post-L3 state is not restored.
- HITL is split into prepare, publish, wait and apply nodes. Only the wait node interrupts.
- Stage audit uses the existing `StepReportModel` persistence path; no parallel report database is introduced. Markdown is a projection of those rows and is written both to the API response and `.run-tmp/{session_id}/reports/stage-report.md`.
- A Windows `0xC0000005` reproduced during the first real LLM run while L1 `Send` workers overlapped RAG/native calls. Python `faulthandler` and pytest-timeout correctly produced no Python exception because this was a native process fault. The repair is bounded L1 LLM concurrency plus a process-local critical section around the synchronous vector query path; a later real run crossed the same L1 window without the access violation.
### Shapely/GeoPandas geometry validity (2026-08-08)

- Query: official Shapely `make_valid` and `is_valid` documentation.
- Basis: invalid geometries must be checked with `is_valid`; `make_valid` repairs
  invalid input but can return multipart/geometry-collection results, so callers
  must validate the repaired result before predicates.
- Decision: the spatial bridge validates uploaded parcel, constraint, and query
  geometries before `intersects`/`intersection`; an unrecoverable feature is
  skipped with a bounded diagnostic rather than repeatedly raising a topology
  exception. Original upload checksums remain unchanged in the session audit.
