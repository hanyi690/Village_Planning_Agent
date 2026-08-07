# Phase 0: Documentation & Graphify Baseline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a pre-refactoring baseline by (1) configuring Graphify to ignore noise (images, test recordings, caches, generated artifacts), (2) generating domain-scoped baseline graphs, and (3) updating module capability/boundary documentation. This baseline is used after Phase 4 to measure improvement in dependency edges, community cohesion, and god-node reduction.

**Architecture:** Graphify runs twice: now (baseline) and after all refactoring (comparison). The baseline captures the current state of the codebase so that post-refactoring changes are measurable. Module docs are updated to reflect actual (not aspirational) boundaries.

**Tech Stack:** Graphify, Python

## Global Constraints

- This is a read-only/analysis phase - no business code changes
- LF line endings
- No emojis in code or comments
- Do not commit unless explicitly asked

---

### Task 1: Create .graphifyignore

**Files:**
- Create: `.graphifyignore`

- [ ] **Step 1: Create the ignore file**

```
# Node modules
**/node_modules/**

# Python caches
**/__pycache__/**
**/.pytest_cache/**
**/*.pyc

# Test artifacts
**/playwright-report/**
**/test-results/**
**/.pytest-tmp*/
**/*.webm
**/*.mp4

# Images
**/*.png
**/*.jpg
**/*.jpeg
**/*.gif
**/*.svg
**/*.ico
**/*.bmp

# Build outputs
**/dist/**
**/build/**
**/.cache/**

# Graphify output (don't recurse into own output)
**/graphify-out/**

# Temp/runtime
**/.run-tmp*/
**/tmp/
```

- [ ] **Step 2: Commit**

```bash
git add .graphifyignore
git commit -m "chore: add Graphify ignore rules for images, caches, test artifacts"
```

---

### Task 2: Generate domain-scoped baseline graphs

**Files:**
- Generate: `graphify-out/baseline/agent/`
- Generate: `graphify-out/baseline/data-kg/`
- Generate: `graphify-out/baseline/spatial-ops/`
- Generate: `graphify-out/baseline/frontend/`

- [ ] **Step 1: Run Graphify per domain**

Run Graphify separately for each domain, outputting to `graphify-out/baseline/`:
- `backend/app/agent/` -> `graphify-out/baseline/agent/`
- `backend/app/modules/data/` + `backend/app/modules/kg/` -> `graphify-out/baseline/data-kg/`
- `backend/app/modules/spatial_ops/` -> `graphify-out/baseline/spatial-ops/`
- `frontend/src/` -> `graphify-out/baseline/frontend/`

- [ ] **Step 2: Record baseline metrics**

For each domain graph, record:
- Total node count
- Edge count
- Number of communities detected
- Number of unnamed/low-cohesion communities
- Largest node degree (god-node candidate)
- Any circular dependencies detected

Save these as `graphify-out/baseline/metrics.md` for post-refactoring comparison.

- [ ] **Step 3: Commit**

```bash
git add graphify-out/baseline/
git commit -m "chore: generate domain-scoped Graphify baseline graphs"
```

---

### Task 3: Update module capability/boundary documentation

**Files:**
- Modify: `docs/architecture/` (update existing module docs to reflect ACTUAL boundaries, not aspirational)
- Modify: `backend/app/agent/README.md` (correct the HITL claim at line 33)

- [ ] **Step 1: Audit existing module docs**

Read all files in `docs/architecture/` and `backend/app/agent/README.md`. Identify where docs claim capabilities that don't match reality (e.g., `frontend.md:128` claims `human_review_paused` is consumed by frontend - it isn't; `agent/README.md:33` acknowledges the gap).

- [ ] **Step 2: Correct docs to reflect actual state**

Update each doc to describe what IS true now, with a "Known Gaps" section listing what's planned. Don't describe aspirational state as current.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/ backend/app/agent/README.md
git commit -m "docs: correct module boundary docs to reflect actual state with known gaps"
```

---

## Baseline Metrics Checklist (for post-Phase 4 comparison)

After this phase, the following must be recorded in `graphify-out/baseline/metrics.md`:

- [ ] Agent domain: node count, edge count, communities, god-nodes, cycles
- [ ] Data+KG domain: same metrics
- [ ] Spatial ops domain: same metrics
- [ ] Frontend domain: same metrics
- [ ] Cross-domain import edges count (modules->services, services->api violations)

These metrics are the comparison baseline for Phase 4 Task 7.
