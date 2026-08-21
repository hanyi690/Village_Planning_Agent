# Spatial Sidebar Chain and KG Convergence Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge the spatial page right sidebar into two truthful modules—`空间链路` and `KG 模块`—so roads are shown only as an execution subtopic and evidence/entity/topology features share one KG boundary.

**Architecture:** Keep the existing backend-backed positioning trace, artifact index, evidence query API, and real GIS counts. Replace the five parallel sidebar tabs with two top-level modules; place artifact details inside a collapsed section of the spatial chain and place entity browsing, evidence querying, and topology mode inside the KG module. Do not invent relationship result counts where the backend only exposes a query mode.

**Tech Stack:** Next.js, React, TypeScript, Tailwind utility classes, existing planning APIs and Zustand state.

## Global Constraints

- Do not change planning workflow or backend business logic.
- Use `positioning-trace` for process state and the artifact index for output state.
- Use the existing evidence query endpoint for KG evidence; do not turn explanatory copy into a fake result.
- Keep the current green visual system, compact cards, and responsive right-panel layout.
- Roads remain available as a named execution subtopic, never as the spatial chain title or primary workflow.

---

### Task 1: Replace parallel spatial tabs with two top-level modules

**Files:**
- Modify: `frontend/src/features/planning/components/PlanningWorkbenchPage.tsx`

**Interfaces:**
- Consumes: `positioningTrace`, `spatialWorkflowSteps`, `spatialArtifactKeys`, real GIS counts, `EvidenceQueryPanel`, and `SPATIAL_RELATIONS`.
- Produces: `SpatialSidebarTab = 'spatial' | 'kg'`, defaulting to `spatial`, with labels `空间链路` and `KG 模块`.

- [x] **Step 1: Rename and simplify the sidebar state**

  Change the union from five parallel tabs to `spatial | kg`, set the initial tab to `spatial`, and render only the two top-level buttons.

- [x] **Step 2: Make the spatial module the single process/output surface**

  Keep the positioning-trace timeline and artifact summary in the spatial module. Move `IntermediateArtifactsPanel` into a collapsed `details` section labelled `查看中间产物详情`, and rename `道路专题结果` to `执行专题结果`. If road projects exist, label them `道路专题` inside that generic execution card; if not, explain that execution output has not reached the backend stage rather than displaying road zeroes.

- [x] **Step 3: Make the KG module own entities, evidence, and topology**

  Move the entity browser, `EvidenceQueryPanel`, and relation-mode explanation into one KG card stack. Keep real GIS counts for entities, make evidence the only query result surface, and label relation chips as `KG 拓扑模式`. Explain that selecting a relation is a map/query mode and that relation conclusions must come from the evidence packet or validation artifacts.

- [x] **Step 4: Align map controls with the new information architecture**

  Rename the map toolbar relation label to `KG 拓扑`, and replace copy that implies a generated relationship result with copy that identifies it as a selected inspection mode.

### Task 2: Verify visual and contract alignment

**Files:**
- Test: existing frontend API tests and build/typecheck commands.
- Verify: `frontend/src/features/planning/components/PlanningWorkbenchPage.tsx` rendered through the local browser.

**Interfaces:**
- Consumes: current running backend `positioning-trace`, artifact index, and evidence APIs.
- Produces: a compact right sidebar whose top-level state is only spatial chain or KG.

- [x] **Step 1: Run typecheck and build**

  Run `npm run type-check` and `npm run build`; expect no new errors.

- [x] **Step 2: Smoke-test the right sidebar in the local browser**

  Open the workbench with a persisted session, confirm the two buttons are visible, confirm `空间链路` shows real recorded/pending stages and artifact summary, confirm `KG 模块` shows entity/evidence/topology sections, and confirm no standalone `道路流程` or `道路连接结果` card remains.

- [x] **Step 3: Check the diff**

  Run `git diff --check` and confirm only the intended right-sidebar and plan files changed in this task.
