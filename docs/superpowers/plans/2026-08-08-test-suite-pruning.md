# Test Suite Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Remove duplicated backend tests while preserving one authoritative guardrail for each behavior and keeping expensive session tests available as explicit integration tests.

**Architecture:** Keep `tests/core` as a small default smoke suite. Keep focused unit tests under `tests/unit`, and move real session verification to `tests/integration`. Replace repeated stage-specific import guardrails with the central import-graph guardrail.

**Tech Stack:** Python 3.13, pytest, pytest-asyncio, pytest-timeout.

## Global Constraints

- Delete only tests with an existing equivalent assertion or move them without changing coverage intent.
- Do not delete production code or fixtures.
- Default `pytest` must not build the full LangGraph/LLM path.
- Integration tests remain runnable by an explicit marker or path.
- Use `python -m pytest` in documented/CI commands so the backend package path is deterministic.

---

### Task 1: Centralize crosswalk import guardrails

**Files:**
- Modify: `backend/tests/unit/test_no_advisory_crosswalk_imports.py`
- Delete: `backend/tests/unit/bootstrap/test_no_advisory_crosswalks.py`
- Delete: `backend/tests/unit/execute/test_no_advisory_crosswalks.py`
- Delete: `backend/tests/unit/deliver/test_no_advisory_crosswalks.py`
- Delete: `backend/tests/unit/validate/test_no_crosswalk_imports.py`
- Delete: `backend/tests/unit/reconcile/test_no_crosswalk_imports.py`
- Delete: `backend/tests/unit/parse/test_no_crosswalk_imports.py`

**Interfaces:** The central guardrail will scan all active `app/agent` stages and GIS generation modules for direct and transitive crosswalk imports. No test imports the deleted specialized files.

- [ ] **Step 1: Extend the central forbidden-stage list**

Add `parse`, `reconcile`, `deliver`, `bootstrap`, and `app/tools/gis/_generation` to the central direct-import scan. Keep the existing transitive import-graph checks and `map_code` checks.

- [ ] **Step 2: Delete only the specialized copies**

Remove the six specialized files listed above. They repeat `test_matcher_detects_crosswalk_imports`, zero-budget assertions, and per-package import snapshots already represented by the central scanner.

- [ ] **Step 3: Run the consolidated guardrail**

Run `python -m pytest tests/unit/test_no_advisory_crosswalk_imports.py -q` from `backend/`.

### Task 2: Reduce the default core suite

**Files:**
- Delete: `backend/tests/core/test_hitl_replay.py`
- Delete: `backend/tests/core/test_offline_vertical_chain.py`
- Delete: `backend/tests/core/test_graph_durability.py`
- Move: `backend/tests/core/test_real_session_backend.py` to `backend/tests/integration/test_real_session_backend.py`
- Modify: `backend/tests/core/test_architecture_contract.py`

**Interfaces:** `tests/core` retains architecture and startup smoke coverage. HITL replay, offline chain, checkpoint durability, and real session coverage are supplied by the agent/unit/integration suites.

- [ ] **Step 1: Remove the duplicate core modules**

Delete the three core files whose behaviors are covered by existing agent/unit tests.

- [ ] **Step 2: Move the real session test to integration**

Preserve the test body and change only its path. Update the architecture contract to check `tests/integration/test_real_session_backend.py`.

- [ ] **Step 3: Verify the core collection is small**

Run `python -m pytest tests/core --collect-only -q` and confirm only the architecture/startup smoke tests remain.

### Task 3: Make integration opt-in and verify the reduced suite

**Files:**
- Modify: `backend/pytest.ini`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/integration/test_real_session_backend.py`
- Modify: `.github/workflows/gis-engine-ci.yml`

- [ ] **Step 1: Register integration and slow markers**

Set the default marker expression to exclude `integration` and `slow`, register both markers, and mark every test collected below `tests/integration` as `integration` from the root conftest.

- [ ] **Step 2: Mark the moved real session test**

Add a module-level `pytestmark = pytest.mark.integration` to keep it explicit even when invoked by filename.

- [ ] **Step 3: Fix CI invocation**

Use `python -m pytest` for core and real-LLM commands. Keep the real-LLM test as an explicit CI job rather than part of the default loop.

- [ ] **Step 4: Run verification**

Run:

```text
python -m pytest -q
python -m pytest tests/unit/test_no_advisory_crosswalk_imports.py -q
python -m pytest tests/unit/test_planning_chain_e2e.py -q
python -m pytest tests/integration/test_real_session_backend.py --collect-only -q
```

Expected: the default run is fast and does not import the full graph path; central guardrails and the retained deterministic chain pass; the real session test is collected only when explicitly selected.

