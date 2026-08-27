# Test Suite Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce historical test-file sprawl while preserving current behavior coverage and making pytest discovery predictable.

**Architecture:** Keep a small set of canonical contract, unit, integration, acceptance, and characterization suites. Merge stage-specific closure tests into behavior-oriented files, consolidate overlapping grounding/evidence boundaries, and document expiry metadata for characterization tests.

**Tech Stack:** Python 3.12, pytest, pytest-asyncio, existing backend test helpers.

## Global Constraints

- Preserve existing user changes and do not reset unrelated files.
- Do not delete a test unless its assertions are migrated or demonstrably obsolete.
- Default pytest discovery must exclude `docs/references` and generated/vendor material.
- Characterization tests must state owner/purpose and a concrete removal condition.

### Task 1: Fix pytest discovery and markers

**Files:**
- Modify: `pytest.ini`
- Modify: `backend/pytest.ini`
- Modify: `conftest.py`
- Modify: `backend/conftest.py`

- [ ] Define explicit test paths and exclude external reference trees.
- [ ] Move shared plugin/bootstrap ownership to the repository top-level.
- [ ] Add markers for unit, characterization, integration, acceptance, contracts, and e2e.
- [ ] Verify collection from the repository root.

### Task 2: Merge remaining closure-stage tests

**Files:**
- Modify: `backend/tests/contracts/test_planning_domain_boundaries.py`
- Modify: `backend/tests/core/test_l2_contracts.py`
- Modify: `backend/tests/core/test_l3_claim_contract_closure.py`
- Delete: obsolete stage-only closure files after assertion migration.

- [ ] Compare stage files against current contract tests and retain unique assertions.
- [ ] Move unique P3/replay assertions only when an equivalent canonical target exists.
- [ ] Delete only files with no remaining unique behavior.
- [ ] Run the affected contract and core tests.

### Task 3: Consolidate grounding/evidence boundaries

**Files:**
- Modify: `backend/tests/core/test_evidence_graph_boundary.py`
- Modify: `backend/tests/core/test_grounding_fail_closed.py`
- Modify: `backend/tests/core/test_unified_grounding_core.py`
- Modify: `backend/tests/core/test_unified_rag_adapter.py`
- Delete: duplicate boundary-only files after migration.

- [ ] Group assertions by evidence graph, retrieval adapter, grounding resolution, and fail-closed policy.
- [ ] Remove duplicate fixtures and repeated “missing evidence” scenarios.
- [ ] Run the consolidated grounding/evidence subset.

### Task 4: Add characterization lifecycle registry

**Files:**
- Create: `backend/tests/characterization/README.md`
- Modify: each retained `backend/tests/characterization/test_*.py` with a lifecycle marker where needed.

- [ ] Record purpose, owner role, and removal condition for each retained characterization file.
- [ ] Mark files with a target review date or explicit migration gate.
- [ ] Keep characterization tests out of the default fast regression marker.

### Task 5: Verify the converged suite

**Files:**
- Modify: `docs/README.md` only if test commands are documented there.

- [ ] Run collection with the repository default command.
- [ ] Run fast contracts/unit tests.
- [ ] Run integration/acceptance tests separately.
- [ ] Report remaining known failures separately from cleanup changes.
