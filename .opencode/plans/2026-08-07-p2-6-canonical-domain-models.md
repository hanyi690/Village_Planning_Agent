# P2-6: Canonical Domain Models (per ADR)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before touching code, write one-page ADRs (Architecture Decision Records) for each domain concept that currently has multiple representations. Only after ADRs are reviewed, implement the canonical model and remove runtime-path adapters.

**Architecture:** Each ADR answers: What does this model represent? Which module owns it? Who generates, who consumes? Required fields and units? Is it a domain fact, computation intermediate, or render view? Where is the single migration boundary for old data?

**Tech Stack:** Python, Pydantic, pytest

## Global Constraints

- Backend tests from `backend/` directory
- 4-space indent, double quotes
- LF line endings
- Commit only when explicitly asked, at task boundaries
- **Do NOT decide canonical models during code execution** - ADRs must be written and reviewed first

---

## Adapter Bridges Requiring ADRs

| Concept | Current Representations | ADR Needed |
|---|---|---|
| Planning intent | `_build_legacy_intent` dict, `SpatialPlanningIntent` typed | ADR-001 |
| Candidate site/parcel | `CandidateSite`, `CandidateParcel`, bridge in `select/adapter.py` | ADR-002 |
| Layout configuration | `layout_configs` (list of dicts), `PlannedState` fields | ADR-003 |
| Revision impact tree | `get_impact_tree_compat`, typed `RevisionImpactTree` | ADR-004 |
| Legacy artifact migration | `migrate_legacy_artifacts` in runtime nodes | ADR-005 |

---

### Task 1: Write ADR-001 through ADR-005

**Files:**
- Create: `docs/adr/001-canonical-planning-intent.md`
- Create: `docs/adr/002-canonical-candidate-model.md`
- Create: `docs/adr/003-layout-config-vs-planned-state.md`
- Create: `docs/adr/004-revision-impact-tree.md`
- Create: `docs/adr/005-legacy-artifact-migration-boundary.md`

- [ ] **Step 1: Write each ADR**

Each ADR follows this template:

```markdown
# ADR-00X: [Title]

## Status
Proposed

## Context
[What problem does this solve? What are the current multiple representations?]

## Decision
[What is the canonical model? Who owns it? Who generates/consumes?]

## Required Fields
[Field name, type, unit, required/optional]

## Classification
[Domain fact | Computation intermediate | Render view]

## Migration Boundary
[Where is the single entry point for old data conversion?]

## Consequences
[What breaks? What becomes easier?]
```

For ADR-001 (Planning Intent):
- Read `backend/app/modules/schema/contracts/parse_contracts.py` for `SpatialPlanningIntent`
- Read the `_build_legacy_intent` function (search for it)
- Read `backend/app/agent/select/adapter.py` for the bridge
- Decide: `SpatialPlanningIntent` is canonical; `_build_legacy_intent` is removed; old dict format only at checkpoint-import boundary

For ADR-002 (Candidate model):
- Read `backend/app/agent/select/adapter.py` (39 lines)
- Read `CandidateSite` and `CandidateParcel` definitions
- Decide which is canonical, who owns it, who generates, who consumes

For ADR-003 (Layout config):
- Read `backend/app/agent/validate/checks.py:269` where `layout_configs` is read as fact
- Read `PlannedState` definition
- Decide: `PlannedState` is the sole fact source; `layout_configs` is a render hint

For ADR-004 (Revision impact tree):
- Search for `get_impact_tree_compat`
- Decide: typed `RevisionImpactTree` is canonical

For ADR-005 (Legacy migration):
- Search for `migrate_legacy_artifacts` call sites
- Decide: only called at checkpoint-import boundary, never in runtime nodes

- [ ] **Step 2: Commit ADRs**

```bash
git add docs/adr/
git commit -m "docs: add ADRs for canonical domain models"
```

---

### Task 2: Implement ADR-001 - remove _build_legacy_intent

**Files:**
- Search and modify all files containing `_build_legacy_intent`
- Test: `backend/tests/architecture/test_no_runtime_adapters.py`

- [ ] **Step 1: Find all usages**

Run: `cd backend && grep -rn "_build_legacy_intent" app/`

- [ ] **Step 2: Replace with typed SpatialPlanningIntent**

Per ADR-001, remove the legacy dict construction. If a caller receives a dict, parse it into `SpatialPlanningIntent` at the boundary.

- [ ] **Step 3: Write architecture test**

```python
def test_no_legacy_intent_in_runtime_path():
    import inspect
    import importlib
    violations = []
    for mod_name in ["app.agent.bootstrap.post_l3_main_nodes", "app.agent.execute.execute_agent"]:
        mod = importlib.import_module(mod_name)
        source = inspect.getsource(mod)
        if "_build_legacy_intent" in source:
            violations.append(mod_name)
    assert not violations
```

- [ ] **Step 4: Run tests and commit**

```bash
cd backend && python -m pytest tests/ -v --tb=short -x
git add backend/
git commit -m "refactor: remove _build_legacy_intent per ADR-001"
```

---

### Task 3: Implement ADR-002 - unify CandidateSite/CandidateParcel

**Files:**
- Modify: `backend/app/agent/select/adapter.py`
- Modify: SELECT and EXECUTE consumers
- Test: architecture test

- [ ] **Step 1: Read adapter.py and both model definitions**

- [ ] **Step 2: Per ADR-002, merge into canonical model**

- [ ] **Step 3: Remove the bridge code in adapter.py**

- [ ] **Step 4: Run tests and commit**

```bash
cd backend && python -m pytest tests/ -v --tb=short -x
git add backend/
git commit -m "refactor: unify candidate model per ADR-002"
```

---

### Task 4: Implement ADR-003 - demote layout_configs to render hint

**Files:**
- Modify: `backend/app/agent/validate/checks.py:269` (stop reading layout_configs as fact)
- Modify: any other business-logic reads of layout_configs
- Test: architecture test

- [ ] **Step 1: Find all business-logic reads of layout_configs**

Run: `cd backend && grep -rn "layout_configs" app/ --include="*.py" | grep -v "render\|export\|_jsonable"`

- [ ] **Step 2: Replace with PlannedState reads per ADR-003**

- [ ] **Step 3: Run tests and commit**

```bash
cd backend && python -m pytest tests/ -v --tb=short -x
git add backend/
git commit -m "refactor: demote layout_configs to render hint per ADR-003"
```

---

### Task 5: Implement ADR-004 and ADR-005

**Files:**
- Modify: files containing `get_impact_tree_compat`
- Modify: files containing `migrate_legacy_artifacts` in runtime nodes
- Test: architecture test

- [ ] **Step 1: Remove get_impact_tree_compat per ADR-004**

- [ ] **Step 2: Restrict migrate_legacy_artifacts to checkpoint-import boundary per ADR-005**

- [ ] **Step 3: Write combined architecture test**

```python
def test_no_runtime_adapters():
    import inspect, importlib
    FORBIDDEN = ["_build_legacy_intent", "get_impact_tree_compat", "migrate_legacy_artifacts"]
    RUNTIME_MODULES = [
        "app.agent.bootstrap.post_l3_main_nodes",
        "app.agent.execute.execute_agent",
        "app.agent.validate.checks",
    ]
    violations = []
    for mod_name in RUNTIME_MODULES:
        mod = importlib.import_module(mod_name)
        source = inspect.getsource(mod)
        for pattern in FORBIDDEN:
            if pattern in source:
                violations.append(f"{mod_name}: {pattern}")
    assert not violations
```

- [ ] **Step 4: Run tests and commit**

```bash
cd backend && python -m pytest tests/ -v --tb=short -x
git add backend/
git commit -m "refactor: remove runtime adapters per ADR-004 and ADR-005"
```
