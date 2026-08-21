# Persistent Session History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the history sidebar load persisted planning sessions after frontend or backend restarts instead of only showing sessions created in the current browser memory.

**Architecture:** Add a read-only stable v1 history endpoint backed by the existing `planning_sessions` table and database query functions. Add a typed frontend API method that maps the response into the existing `VillageInfo` and `VillageSession` store shape; keep local deleted-session filtering and current in-memory insertion for immediate feedback.

**Tech Stack:** FastAPI, Pydantic v2, SQLModel async database operations, Next.js, TypeScript, Zustand, Vitest.

## Global Constraints

- Backend changes are limited to API transport and read-only history exposure; do not change planning workflow or session execution behavior.
- The history endpoint must not expose `village_data`, task text, constraints, uploaded content, or other large/private session inputs.
- The frontend must continue filtering locally deleted session IDs.
- Empty, malformed, or unavailable history responses must produce a visible loading error rather than silently pretending the backend returned no sessions.
- Existing current-session immediate insertion must remain so a newly started session appears without waiting for a refresh.

---

### Task 1: Add a read-only persisted history contract and endpoint

**Files:**
- Modify: `backend/app/api/v1/contracts.py`
- Create: `backend/app/api/v1/routes/history.py`
- Modify: `backend/app/api/v1/routes/__init__.py`
- Test: `backend/tests/core/test_session_history_api.py`

**Interfaces:**
- Consumes: `list_projects_async()` and `list_planning_sessions_async()` from `backend/app/database/operations.py`.
- Produces: `GET /api/v1/projects`, returning `{ "projects": [{ "name", "display_name", "session_count", "sessions": [...] }] }`.
- Each session returns only `session_id`, `timestamp`, `checkpoint_count`, and `has_final_report`.

- [x] **Step 1: Write the failing API contract tests**

  Add tests that call the route with a mocked async project/session query and assert that the response contains project/session metadata but not `village_data`, `task_description`, or `constraints`. Add an empty database case that returns `{"projects": []}`.

- [x] **Step 2: Run the focused tests and verify they fail**

  Run:

  ```powershell
  python -m pytest backend/tests/core/test_session_history_api.py -q
  ```

  Expected: FAIL because the history response models and route do not exist.

- [x] **Step 3: Add strict Pydantic v2 response models**

  Add `HistorySession`, `HistoryProject`, and `HistoryProjectList` to `contracts.py` using the existing `PublicModel` base and strict typed fields. Use `timestamp` from `created_at`, map `completed_at is not None` to `has_final_report`, and keep `checkpoint_count` at `0` until a dedicated checkpoint-count query is introduced.

- [x] **Step 4: Implement the async route**

  Create a `/api/v1` router with `GET /projects`. Query `list_projects_async()` for project order/counts and `list_planning_sessions_async(limit=100)` once for sessions. Group sessions by `project_name`, sort each group by timestamp descending, and return only the public metadata contract. Include the router from `routes/__init__.py`.

- [x] **Step 5: Run the focused tests and verify they pass**

  Run:

  ```powershell
  python -m pytest backend/tests/core/test_session_history_api.py -q
  ```

  Expected: PASS.

### Task 2: Load persisted history into the frontend store

**Files:**
- Modify: `frontend/src/features/planning/api/types.ts`
- Modify: `frontend/src/features/planning/api/index.ts`
- Modify: `frontend/src/features/planning/api/planning-api.ts`
- Modify: `frontend/src/features/planning/store/planning-context.tsx`
- Test: `frontend/src/__tests__/api/planning-api.test.ts`

**Interfaces:**
- Consumes: `GET /api/v1/projects` from Task 1.
- Produces: `planningApi.listProjects()` returning typed `VillageInfo[]`, and `loadVillagesHistory()` calling it before setting the store.

- [x] **Step 1: Write the failing frontend API test**

  Mock `fetch`, call `planningApi.listProjects()`, and assert that the method requests `/api/v1/projects` and returns the typed `projects` array. Add a mapping assertion for `created_at` to `timestamp` and `completed_at` to `has_final_report`.

- [x] **Step 2: Run the focused frontend test and verify it fails**

  Run:

  ```powershell
  npm test -- --run frontend/src/__tests__/api/planning-api.test.ts
  ```

  Expected: FAIL because the method and response types are not present.

- [x] **Step 3: Add the response types and API method**

  Define backend response types in `types.ts`, export them from `api/index.ts`, and add:

  ```typescript
  async listProjects(): Promise<VillageInfo[]> {
    const response = await apiRequest<{ projects: PersistedHistoryProject[] }>('/api/v1/projects');
    return response.projects;
  }
  ```

  Keep the returned shape aligned with the existing store instead of adding a second history model in Zustand.

- [x] **Step 4: Replace the no-op history loader**

  In `loadVillagesHistory`, call `planningApi.listProjects()`, pass the result through `state.setVillages(...)` so `deletedSessionIds` are applied, and set `historyError` on failure using the existing error helper. Always clear `historyLoading` in `finally`.

- [x] **Step 5: Run typecheck and the focused test**

  Run:

  ```powershell
  npm test -- --run frontend/src/__tests__/api/planning-api.test.ts
  npm run type-check
  ```

  Expected: PASS with no new type errors.

### Task 3: Verify restart persistence and user-visible behavior

**Files:**
- Modify: `frontend/src/features/planning/components/PlanningWorkbenchPage.tsx` only if the existing error/empty state needs copy adjustment.
- Test: `backend/tests/core/test_session_history_api.py`
- Test: `frontend/src/__tests__/api/planning-api.test.ts`

**Interfaces:**
- Consumes: the stable history endpoint and the frontend `loadVillagesHistory()` path.
- Produces: a restart-safe history sidebar and a diagnostic error when the endpoint is unavailable.

- [x] **Step 1: Verify the live backend endpoint**

  Run:

  ```powershell
  Invoke-RestMethod http://127.0.0.1:8000/api/v1/projects
  ```

  Expected: the response includes the existing persisted sessions, including the current `b6a88263-a6ec-4669-a6d0-a878c243a18f` session when it has not been locally deleted.

- [x] **Step 2: Run backend and frontend regression checks**

  Run:

  ```powershell
  python -m pytest backend/tests/core/test_session_history_api.py -q
  npm test -- --run frontend/src/__tests__/api/planning-api.test.ts
  npm run type-check
  npm run build
  git diff --check
  ```

- [x] **Step 3: Perform the browser smoke check**

  Refresh the workbench, confirm the history list is populated, start or open a session, restart only the frontend, refresh again, and confirm the same session remains listed. Confirm a backend-unavailable response shows `历史记录加载失败` instead of `暂无历史会话`.
