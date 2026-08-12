# Stage 1 Application, Workflow and Contract Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the first migration cutover by moving API writes/reads behind application boundaries, enforcing typed workflow dispatch, and freezing the §9.4/§9.5/§9.7 contracts without business logic.

**Architecture:** Keep the existing dirty migration worktree as the baseline. Stream A owns application commands, queries, projections, and UoW; Stream B owns workflow dispatch/routing/terminal; Stream C owns contracts, ports, evidence models, and contract tests. Production callers are switched only after focused tests pass, and old paths are removed only when no imports remain.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, LangGraph, pytest.

## Global Constraints

- Do not reset or discard existing worktree changes.
- Keep each stream's write set disjoint: A `application/` and API call sites, B `workflow/`, C `contracts/ports/` and `evidence/model/`.
- No `Any` in newly frozen public contracts; failures use typed results or explicit exceptions at the application boundary.
- API routes may call application commands/queries only; workflow stages may emit only typed dispatch/completion shapes.
- Run focused contract/architecture tests after each stream and the §9.2 acceptance smoke before claiming cutover.

### Task 1: §9.2 Application boundary

**Files:** `backend/app/application/commands/`, `backend/app/application/queries/`, `backend/app/application/projections/`, `backend/app/application/unit_of_work.py`, and the minimum API call sites needed to stop direct runtime reads/writes.

- [ ] Add or complete typed create/resume/review/session-state use cases and a UoW protocol around existing runtime, event, and artifact ports.
- [ ] Make `/api/v1` routes call commands/queries/projections instead of directly reading runtime/store/SSE internals.
- [ ] Add focused architecture and application tests, then run the create-session and resume tests.
- [ ] Remove only dead duplicate application/service imports proven unused by `rg` and the focused tests.

### Task 2: §9.3 Workflow dispatch boundary

**Files:** `backend/app/workflow/dispatch.py`, `backend/app/workflow/routing.py`, `backend/app/workflow/terminal.py`, root graph call sites, and focused workflow tests.

- [ ] Define typed dispatch proposal, policy decision, command, rejection diagnostic, and terminal result contracts using existing artifact/stage references.
- [ ] Route graph transitions through the policy boundary and reject invalid stage transitions, missing parents, and budget/attempt violations with typed diagnostics.
- [ ] Add tests for valid dispatch, cross-stage rejection, malformed proposal, and terminal routing.

### Task 3: §9.4/§9.5/§9.7 contract freeze

**Files:** `backend/app/contracts/workflow/repair.py`, `backend/app/contracts/ports/`, `backend/app/evidence/model/`, and contract tests.

- [ ] Freeze `RelationEvidence`, external search request/result/port, `ValidationAdjustment`, `IterationRecord`, image/visual evidence models, media/visual ports, and the four planning output contracts.
- [ ] Ensure models are strict Pydantic contracts with schema/digest/provenance/parent references where required and no business logic or provider imports.
- [ ] Add schema, failure-shape, port substitutability, and no-`Any` tests.

### Cutover gates

- [ ] §9.2: real `/api/v1` create-session and resume path passes.
- [ ] §9.3: real dispatch rejects unauthorized stage transitions.
- [ ] `git diff --check` and focused pytest suites pass; report remaining real-provider acceptance as open if credentials/runtime data prevent execution.
