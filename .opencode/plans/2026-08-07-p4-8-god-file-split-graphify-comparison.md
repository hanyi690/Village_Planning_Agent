# P4-8: God File Split by Dependency Edges + Graphify Comparison

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 4 God files by responsibility (not by technical layer), then regenerate Graphify and compare against Phase 0 baseline. Success is measured by reduced cross-module import edges, eliminated circular dependencies, and single fact ownership - NOT by line count alone.

**Architecture:** Files that change together stay together. Each split produces focused files. After splitting, Graphify is regenerated and compared to `graphify-out/baseline/` to verify improvement.

**Tech Stack:** Python, TypeScript, Graphify

## Global Constraints

- Backend tests from `backend/`, frontend from `frontend/`
- 2-space TS, 4-space Python
- LF line endings
- Commit only when explicitly asked, at task boundaries
- **Success metric**: reduced import edges and cycles, NOT line count

---

### Task 1: Split session_routes.py (1314 lines)

**Files:**
- Modify: `backend/app/api/session_routes.py` (reduce to router aggregation)
- Create: `backend/app/api/routes/session_crud.py`
- Create: `backend/app/api/routes/session_sse.py`
- Create: `backend/app/api/routes/session_hitl.py`
- Create: `backend/app/api/routes/session_gis.py`
- Create: `backend/app/api/routes/session_checkpoints.py`
- Create: `backend/app/api/routes/session_history.py`

- [ ] **Step 1: Map route handlers to responsibility groups**

Read `session_routes.py` and categorize each `@router` handler.

- [ ] **Step 2: Extract each group**

Each file gets its own `router = APIRouter()`. Shared deps go in a common module.

- [ ] **Step 3: Reduce session_routes.py to aggregation**

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/api/ -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/
git commit -m "refactor: split session_routes.py by responsibility"
```

---

### Task 2: Split planningStore.ts (1971 lines)

**Files:**
- Create: `frontend/src/features/planning/store/handlers/sseHandlers.ts`
- Create: `frontend/src/features/planning/store/handlers/derivedState.ts`
- Create: `frontend/src/features/planning/store/handlers/historyActions.ts`
- Create: `frontend/src/features/planning/store/handlers/gisActions.ts`
- Modify: `frontend/src/features/planning/store/planningStore.ts`

- [ ] **Step 1: Extract SSE handler + derived state + grouped actions**

- [ ] **Step 2: Run tests**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/planning/store/
git commit -m "refactor: split planningStore.ts by responsibility"
```

---

### Task 3: Split execute_agent.py (1192 lines)

**Files:**
- Create: `backend/app/agent/execute/nodes/` (one file per node function)
- Create: `backend/app/agent/execute/legacy/layer_helpers.py`
- Modify: `backend/app/agent/execute/execute_agent.py` (reduce to graph builder)

- [ ] **Step 1: Extract 11 node functions into focused modules**

- [ ] **Step 2: Move legacy helpers**

- [ ] **Step 3: Run tests**

Run: `cd backend && python -m pytest tests/agent/ tests/core/ -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add backend/app/agent/execute/
git commit -m "refactor: split execute_agent.py by responsibility"
```

---

### Task 4: Split DataCatalog (1008 lines)

**Files:**
- Create: `backend/app/modules/data/catalog/assembly.py`
- Create: `backend/app/modules/data/catalog/inference.py`
- Create: `backend/app/modules/data/catalog/geometry_fallback.py`
- Modify: `backend/app/modules/data/catalog/catalog.py`

- [ ] **Step 1: Extract assembly, inference, geometry fallback**

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/modules/data/ -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add backend/app/modules/data/catalog/
git commit -m "refactor: split DataCatalog by responsibility"
```

---

### Task 5: Regenerate Graphify and compare to baseline

**Files:**
- Generate: `graphify-out/post-refactor/agent/`
- Generate: `graphify-out/post-refactor/data-kg/`
- Generate: `graphify-out/post-refactor/spatial-ops/`
- Generate: `graphify-out/post-refactor/frontend/`
- Create: `graphify-out/comparison.md`

- [ ] **Step 1: Run Graphify per domain (same as Phase 0)**

- [ ] **Step 2: Compare to baseline**

For each domain, compare:
- Node count (should be similar or slightly higher - more files)
- Edge count (should DECREASE - fewer cross-module imports)
- Circular dependencies (should be eliminated)
- God-node max degree (should decrease)
- Community cohesion (should improve - fewer unnamed communities)

- [ ] **Step 3: Write comparison report**

Create `graphify-out/comparison.md` with before/after metrics.

- [ ] **Step 4: Commit**

```bash
git add graphify-out/
git commit -m "chore: post-refactor Graphify comparison vs baseline"
```

---

### Task 6: Full regression

- [ ] **Step 1: Backend tests**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 2: Frontend tests**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run build`
Expected: All pass

- [ ] **Step 3: Verify improvement metrics**

Confirm the comparison report shows:
- Cross-domain import edges reduced
- No new circular dependencies
- God-node degrees reduced
- Community cohesion improved
