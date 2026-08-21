# Frontend L1/L2/L3 and GIS Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize the newest remote frontend implementation into the current branch, make L1/L2/L3 dimension results and GIS render layers display even when their payloads are empty, and make planning-text APIs return empty values temporarily.

**Architecture:** Use `origin/integrate/blueprint-with-handoff-fix` as the remote frontend reference, applying only its `frontend/` changes. Keep the current backend `/api/v1` contract untouched. The frontend will continue to obtain dimension progress/reports from the planning store and authoritative GIS layers from `/api/v1/sessions/{id}/map-layers` plus delivery artifacts; planning text will be a no-op empty projection until its backend contract is restored.

**Tech Stack:** Next.js 14, React 18, TypeScript, Zustand, MapLibre, Jest, Playwright, FastAPI `/api/v1` frontend contract.

## Global Constraints

- Modify only files under `frontend/` plus this implementation plan; do not edit, stage, or commit `backend/` files.
- Preserve the user's existing uncommitted backend and documentation changes.
- Do not call the removed `/api/sessions/{id}/planning-text` endpoints.
- `getPlanningText()` returns `null`, `getPlanningTextVersions()` returns an empty list, and `generatePlanningText()` returns an empty successful response.
- Empty L1/L2/L3 reports and empty GIS layer collections must render without throwing.
- The local backend SSE contract is authoritative: dimension/GIS source events arrive as public `progress` events with the source event name in `data.type`; `resync_required` remains a control payload.

### Task 1: Synchronize the remote frontend delta

**Files:**
- Modify: the frontend files changed by `origin/integrate/blueprint-with-handoff-fix` relative to `HEAD`, limited to `frontend/`.
- Do not modify: `backend/**`.

**Interfaces:**
- Consumes: current branch `HEAD` and remote reference `origin/integrate/blueprint-with-handoff-fix`.
- Produces: current-branch frontend files matching the remote developer implementation for the selected delta.

- [x] **Step 1: Verify the source branch and frontend-only file list**

```powershell
git diff --name-status HEAD origin/integrate/blueprint-with-handoff-fix -- frontend
```

Expected: only `frontend/` paths are selected for synchronization.

- [x] **Step 2: Apply the remote frontend delta without touching backend**

```powershell
git diff --binary HEAD origin/integrate/blueprint-with-handoff-fix -- frontend | git apply
```

Expected: only the working-tree frontend files are updated; the index remains untouched.

- [x] **Step 3: Verify the staged path boundary**

```powershell
git diff --name-only | Where-Object { $_ -notlike 'frontend/*' }
```

Expected: only pre-existing non-frontend paths may appear; this task must not add a new backend path.

### Task 2: Make planning text an empty, non-error projection

**Files:**
- Modify: `frontend/src/features/planning/api/planning-api.ts` around the planning-text methods.
- Test: `frontend/src/__tests__/api/planning-api.test.ts`.

**Interfaces:**
- Consumes: existing `PlanningTextDocument`, `PlanningTextVersionList`, and `GeneratePlanningTextResponse` types.
- Produces: no-network empty responses that keep `PlanningTextViewer` mounted without error logs.

- [x] **Step 1: Add tests for empty planning-text behavior**

```typescript
it('returns an empty planning text projection without network access', async () => {
  await expect(planningApi.getPlanningText('session-1')).resolves.toBeNull();
  await expect(planningApi.getPlanningTextVersions('session-1')).resolves.toEqual({
    session_id: 'session-1',
    versions: [],
  });
  expect(fetch).not.toHaveBeenCalled();
});
```

- [x] **Step 2: Implement the empty responses**

```typescript
async getPlanningText(): Promise<PlanningTextDocument | null> {
  return null;
}

async getPlanningTextVersions(sessionId: string): Promise<PlanningTextVersionList> {
  return { session_id: sessionId, versions: [] };
}
```

For `generatePlanningText`, return a typed response with an empty `markdown_content`, zero article count, and a successful empty status instead of throwing or fetching a removed endpoint.

- [x] **Step 3: Run the focused API tests**

```powershell
npm test -- --runInBand src/__tests__/api/planning-api.test.ts
```

Expected: PASS, with no planning-text network request.

### Task 3: Verify L1/L2/L3 and GIS empty-state rendering

**Files:**
- Modify only if required: `frontend/src/features/planning/store/planningStore.ts`, `frontend/src/features/planning/hooks/useSSE.ts`, `frontend/src/features/planning/hooks/useDelivery.ts`, `frontend/src/features/planning/components/PlanningWorkbenchPage.tsx`, `frontend/src/features/planning/components/layout/ReportViewer.tsx`, and GIS components already included in the remote frontend delta.
- Test: existing planning store, GIS normalization, API, and E2E contract tests.

**Interfaces:**
- Consumes: `/api/v1/sessions/{id}/events`, `/api/v1/sessions/{id}/state`, `/api/v1/sessions/{id}/delivery`, `/api/v1/sessions/{id}/map-layers`, and `/api/v1/sessions/{id}/artifacts/{key}`.
- Produces: stable UI projections for `layer1`, `layer2`, `layer3`, and an empty-but-valid GIS layer collection.

- [x] **Step 1: Confirm the store initializes all three dimensions and empty GIS layers**

```powershell
rg -n "layer1|layer2|layer3|mapLayers|applyMapLayers|normalizeV1MapLayers" frontend/src/features/planning
```

Expected: all three dimensions have explicit state paths and empty arrays/maps are accepted.

- [x] **Step 2: Run type checking**

```powershell
npm run type-check
```

Expected: PASS.

- [x] **Step 3: Run focused unit tests**

```powershell
npm test -- --runInBand src/__tests__/api/client.test.ts src/__tests__/utils/gis-normalize.test.ts src/__tests__/store/planningStore.delivery.test.ts
```

Expected: PASS.

- [x] **Step 4: Run the frontend contract smoke test when the backend is available**

```powershell
npm run test:e2e -- e2e/v1-contract.spec.ts
```

Expected: the test reaches the `/api/v1` endpoints; the backend was not running in this session, so this E2E step remains an environment follow-up and no backend code was changed.

- [x] **Step 5: Verify the local backend SSE projection**

The frontend registers the local public event names (`progress`, `human_review`, `completed`, `failed`, and `resync_required`). It unwraps dimension/GIS source events from `progress.data.type` and preserves the local `resync_required` control payload for REST recovery.

### Task 4: Final boundary and working-tree verification

**Files:**
- No additional source files.

- [x] **Step 1: Confirm backend files are unchanged by this task**

```powershell
git diff --name-only HEAD -- backend
git diff --cached --name-only | Where-Object { $_ -like 'backend/*' }
```

Expected: no backend paths introduced by this task.

- [x] **Step 2: Review frontend diff and report existing unrelated changes**

```powershell
git status --short
git diff --stat -- frontend
```

Expected: only frontend implementation changes from this task plus the user's pre-existing modifications are reported.
