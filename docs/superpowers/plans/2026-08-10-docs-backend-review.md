# Documentation and Backend Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository documentation describe the real module boundaries and define an ideal, implementation-first closed-loop architecture without normalizing current gaps.

**Architecture:** Keep the existing basic flow—Next.js UI → FastAPI application → LangGraph workflow → typed domain contracts → spatial/KG/data modules—but make the target state authoritative and place current code facts beside it. Use one application lifespan, one compiled persisted graph per runtime, one session per async database task, and typed artifact references at workflow boundaries.

**Tech Stack:** Python 3.11, FastAPI 0.128.x, Pydantic 2, SQLAlchemy 2 async, SQLModel, LangGraph 1.x, Next.js 14, React 18, TypeScript, GeoPandas, Shapely, RDFLib, Chroma.

## Global Constraints

- Preserve the existing five-layer domain framework and canonical workflow names.
- Do not claim a capability is complete unless the repository contains an executable path and verification evidence.
- Target design is ideal-state first; current implementation differences must be explicit migration records.
- Do not overwrite or revert unrelated user changes already present in the working tree.
- Documentation updates use LF line endings, two-space indentation for structured examples, and concise module ownership statements.
- Official practice references must use Context7/Exa results for FastAPI, SQLAlchemy, and LangGraph decisions.

---

### Task 1: Reconcile the architecture baseline

**Files:**
- Modify: `docs/design/00_SYSTEM_DESIGN.md`
- Modify: `docs/design/01_LAYERED_ARCHITECTURE.md`
- Modify: `docs/architecture/agent-graph.md`
- Modify: `docs/design/10_IMPLEMENTATION_STATUS.md`
- Create: `docs/audits/backend-official-practice-2026-08-10.md`

**Interfaces:**
- Consumes: `backend/app/main.py`, `backend/app/database/engine.py`, `backend/app/agent/bootstrap/graph.py`, current module READMEs, Context7 and Exa official documentation.
- Produces: A target-state design, an observed-vs-target status table, and a backend practice evidence ledger.

- [ ] **Step 1: Record the official baseline**

  Include links to FastAPI lifespan/dependency/streaming/testing docs, SQLAlchemy async session docs, and LangGraph persistence/interrupt/streaming docs. Record the decision that these are target-state constraints rather than retroactive claims about current code.

- [ ] **Step 2: Update the target design**

  Keep `PARSE → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`, but define the ideal lifecycle, persistence, artifact, retry, and SSE contracts. Explicitly separate target state from migration state.

- [ ] **Step 3: Update implementation status**

  Correct node counts, route ownership, actual artifact/ref behavior, and the known context/version and legacy-path gaps from code evidence.

- [ ] **Step 4: Add the backend practice audit**

  Review FastAPI lifecycle, streaming, dependency scope, async SQLAlchemy session ownership, LangGraph checkpointer/HITL usage, background task ownership, response validation, and health/readiness semantics. Classify each as `符合`, `部分符合`, `偏离`, or `未验证`, with file evidence and a remediation priority.

### Task 2: Complete missing module documentation

**Files:**
- Create: `backend/app/api/route_modules/README.md`
- Create: `backend/app/agent/execute/nodes/README.md`
- Create: `backend/app/agent/execute/legacy/README.md`
- Create: `backend/app/modules/schema/encodings/dicts/README.md`
- Create: `backend/app/modules/schema/encodings/dicts/vocabularies/README.md`
- Create: `backend/app/modules/spatial_ops/evidence/README.md`
- Create: `frontend/README.md`
- Create: `frontend/src/app/README.md`
- Create: `frontend/src/features/planning/README.md`
- Create: `frontend/src/features/gis-test/README.md`

**Interfaces:**
- Consumes: Actual files and imports in each directory, existing frontend API/types/store code, and `docs/architecture/*`.
- Produces: README files with purpose, public entrypoints, inputs/outputs, dependency boundaries, runtime status, and verification commands.

- [ ] **Step 1: Document API route modules**

  Describe the six route modules, their mounted paths, service dependencies, and the rule that routes validate/translate requests but do not own planning algorithms.

- [ ] **Step 2: Document EXECUTE nodes and legacy area**

  Describe worker orchestration and mark legacy helpers explicitly as compatibility-only with deletion criteria.

- [ ] **Step 3: Document encoding dictionaries and spatial evidence**

  Describe deterministic loading/validation and evidence scoring/place indexing without presenting them as candidate selection.

- [ ] **Step 4: Document the frontend modules**

  Describe Next.js entrypoints, planning feature state/SSE/API flow, GIS test page scope, environment variables, and current E2E/type-check commands.

### Task 3: Fix clear backend lifecycle/session deviations

**Files:**
- Modify: `backend/app/database/engine.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/route_modules/session_sse.py`
- Test: `backend/tests/core/test_backend_lifecycle_contract.py`

**Interfaces:**
- Consumes: Existing database exports and runtime initialization/shutdown calls.
- Produces: A single app-owned async engine/session factory lifecycle, explicit transaction ownership, stable SSE disconnect/cleanup behavior, and regression tests.

- [ ] **Step 1: Add failing lifecycle/session tests**

  Assert that engine disposal resets the session factory, repeated lifecycle setup does not retain a disposed engine, and a session rollback occurs on an exception without an implicit commit being hidden in the context manager.

- [ ] **Step 2: Implement the minimal lifecycle correction**

  Remove reference-counted engine lifetime, reset `AsyncSessionLocal` during disposal, use one engine/session factory per application runtime, and keep commit/rollback at explicit CRUD transaction boundaries.

- [ ] **Step 3: Preserve streaming semantics**

  Keep SSE subscription inside the generator lifetime, handle cancellation, and document that database sessions are not held across the network stream.

- [ ] **Step 4: Run focused tests**

  Run `pytest -q backend/tests/core/test_backend_lifecycle_contract.py` and the existing database/session tests that do not require external LLM credentials.

### Task 4: Verify documentation and backend behavior

**Files:**
- Modify: `docs/README.md` if navigation needs the new audit/plan links.
- Test: Existing backend unit/core tests and frontend type-check.

**Interfaces:**
- Consumes: All modified README/design/audit files and the lifecycle/session changes.
- Produces: A documented verification matrix and a final list of unresolved gaps.

- [ ] **Step 1: Run documentation consistency checks**

  Check that every Python package directory with source files has a README, all referenced paths exist, and design documents do not claim deleted/legacy modules are canonical.

- [ ] **Step 2: Run backend checks**

  Run syntax compilation, focused lifecycle tests, relevant core contract tests, and the default pytest command where dependencies allow. Do not run real external-provider calls.

- [ ] **Step 3: Run frontend checks**

  Run `npm run type-check` and `npm run lint` from `frontend` if the installed toolchain supports them.

- [ ] **Step 4: Update status evidence**

  Record exact commands and results in the audit document, distinguishing runtime-verified results from static inference.
