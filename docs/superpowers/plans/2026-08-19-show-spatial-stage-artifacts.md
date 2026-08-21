# Spatial Stage Artifact Visibility Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the process record and the actual artifact registration independently for every spatial-chain stage, with human-readable artifact names when spatial outputs exist.

**Architecture:** Keep all artifact keys from the backend index for stage matching, derive a separate spatial-only set for spatial output totals, and enrich each `SpatialWorkflowStep` with its expected and registered artifact keys. The sidebar will never count L1/L2-only artifacts as spatial output and will distinguish “stage recorded” from “spatial artifact registered.”

**Tech Stack:** React, TypeScript, existing `positioning-trace` and artifact-index APIs.

## Global Constraints

- Do not change backend workflow behavior or fabricate spatial artifacts.
- Use only keys returned by `GET /api/v1/sessions/{id}/artifacts` as registered outputs.
- Preserve compact right-sidebar layout and human-readable labels.

---

### Task 1: Bind stages to real artifact keys

**Files:**
- Modify: `frontend/src/features/planning/components/PlanningWorkbenchPage.tsx`

- [x] **Step 1: Separate all artifact keys from spatial-only artifact keys**
- [x] **Step 2: Add expected artifact keys to each spatial workflow stage**
- [x] **Step 3: Render process status and artifact status independently**
- [x] **Step 4: Show registered artifact labels under the matching stage**

### Task 2: Verify spatial visibility

**Files:**
- Test: existing frontend type/build checks.
- Verify: local browser spatial-chain sidebar.

- [x] **Step 1: Run typecheck and build**
- [x] **Step 2: Confirm current session shows L3/L2 artifacts separately from spatial artifacts**
- [x] **Step 3: Confirm a future registered spatial artifact appears under its stage without changing stage copy**

### Task 3: Expose human-readable planning intent text

**Files:**
- Modify: `frontend/src/features/planning/components/PlanningWorkbenchPage.tsx`

- [x] **Step 1: Read layer-3 reports restored from the durable event stream**
- [x] **Step 2: Prefer `report_body` and avoid rendering claims JSON as正文**
- [x] **Step 3: Convert claims-only responses into a labeled readable judgment list**
- [x] **Step 4: Render compact, expandable intent text under the L3 spatial stage**
