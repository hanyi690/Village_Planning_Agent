# Spatial Demo Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the spatial-results UI with the backend's real delivery state, expose honest current/reference layers before DELIVER, make artifacts human-readable, and recover stale checkpoint decisions without an unhandled browser error.

**Architecture:** Keep planning, execution, and delivery business logic unchanged. Extend only the stable API transport/projection boundary to return a typed diagnostic map projection when DELIVER artifacts are absent, and make the frontend render current/reference data as explicitly non-deliverable preview content. Treat checkpoint conflicts as recoverable state synchronization rather than fatal UI exceptions.

**Tech Stack:** FastAPI, Pydantic v2, Next.js 14, React 18, TypeScript, MapLibre, Playwright, pytest.

## Global Constraints

- Do not modify backend business implementations outside `backend/app/api`.
- Do not present current/reference layers as completed L3 planning output.
- A missing DELIVER artifact must not surface as a generic 404/500 overlay when the session is still running or paused.
- Artifact details shown in the UI must default to summaries/tables, with raw JSON available only as an explicit inspection action.
- Checkpoint conflict recovery must use the latest backend state and active event id.

### Task 1: Diagnose and stabilize the v1 spatial API

**Files:**
- Modify: `backend/app/api/v1/contracts.py`
- Modify: `backend/app/api/v1/routes/map_layers.py`
- Test: `backend/tests/core/test_api_v1_contracts.py`
- Test: `backend/tests/core/test_map_layers_api.py`

**Interfaces:**
- `GET /api/v1/sessions/{session_id}/map-layers` returns HTTP 200 for an existing session even when DELIVER artifacts are absent.
- The response includes `delivery_status: "diagnostic_only"`, an explicit `preview_mode`, and readable layer metadata when only current/reference layers are available.
- Completed DELIVER snapshots remain authoritative and retain their existing response shape.

- [ ] Add a typed response field for preview/diagnostic provenance.
- [ ] Map invalid internal delivery status values to the public contract instead of allowing response-model validation to become HTTP 500.
- [ ] Add API tests for paused-session and completed-delivery behavior.
- [ ] Run the focused API tests and inspect OpenAPI output.

### Task 2: Make the spatial-results page honest and usable before L3 completion

**Files:**
- Modify: `frontend/src/features/planning/components/PlanningWorkbenchPage.tsx`
- Modify: `frontend/src/features/planning/components/IntermediateArtifactsPanel.tsx`
- Modify: `frontend/src/features/planning/components/DeliveryStatusBanner.tsx`
- Modify: `frontend/src/features/planning/api/types.ts`
- Modify: `frontend/src/features/planning/api/planning-api.ts`
- Test: `frontend/src/__tests__/components/IntermediateArtifactsPanel.test.tsx`

**Interfaces:**
- The map page distinguishes `现状/参考预览` from `L3 规划交付`.
- Empty or diagnostic results render a status card, not `成果加载失败`.
- Artifact rows show stage, status, short summary, and a human-readable detail drawer; raw JSON is opt-in.
- The right side uses tabs or collapsible sections so the map and the active inspection panel receive the available width.

- [ ] Normalize the new API fields in the frontend client.
- [ ] Render a diagnostic preview banner and remove misleading completed-result wording.
- [ ] Replace the always-expanded artifact stack with compact grouped rows and an explicit detail action.
- [ ] Move evidence/relations into a selectable inspection area instead of stacking every panel.
- [ ] Add component tests for diagnostic and completed states.

### Task 3: Recover stale checkpoint decisions

**Files:**
- Modify: `frontend/src/features/planning/api/client.ts`
- Modify: `frontend/src/features/planning/hooks/useApprovalActions.ts`
- Modify: `frontend/src/features/planning/utils/session-hydrate.ts`
- Test: `frontend/src/__tests__/api/planning-api.test.ts`

**Interfaces:**
- A 409 conflict containing `event_id does not match active checkpoint` triggers one state refresh and exposes a readable review message.
- The UI never throws an unhandled Runtime Error for a recoverable checkpoint conflict.

- [ ] Classify conflict responses with a stable error code/status.
- [ ] Refresh session state/review data before retrying or asking the user to review the current checkpoint.
- [ ] Add a regression test for the stale event id path.

### Task 4: Verify the full demonstration path

**Files:**
- Modify: `frontend/e2e/v1-contract.spec.ts` only if the public contract changes.
- Modify: `frontend/e2e/gis-frontend.spec.ts` only if selectors or explicit preview states change.

- [ ] Run backend API and contract tests with the repository's default e2e filter overridden where needed.
- [ ] Run frontend type-check and focused component tests.
- [ ] Use Playwright to verify a paused session shows a non-error preview, a completed session shows authoritative layers, artifacts are readable, and a stale checkpoint conflict is recoverable.
- [ ] Confirm no backend files outside `backend/app/api` changed.
