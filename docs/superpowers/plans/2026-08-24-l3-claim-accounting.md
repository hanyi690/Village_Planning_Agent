# L3 Claim Accounting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve valid but ungrounded L3 spatial intent as auditable pending claims while retaining strict intervention admission.

**Architecture:** Add an L3 `ClaimDisposition` contract and persist classifier output on `PlanningProgram`. Keep `interventions_from_claims()` unchanged for strict callers; use a new classifier from fragment assembly so pending-only readiness gaps become warning-level accounting records.

**Tech Stack:** Python 3, Pydantic v2, pytest.

## Global Constraints

- Preserve unrelated dirty-worktree changes.
- Do not change GROUND or SELECT.
- Do not add regex parsing, coordinates, BSMs, WKT, candidate geometry, or a compatibility alias.
- Preserve strict `interventions_from_claims()` behavior.

---

### Task 1: Add claim-accounting contracts and classification

**Files:**
- Modify: `backend/app/contracts/domain/l3_contracts.py`
- Modify: `backend/app/domain/program/claim_adapter.py`
- Test: `backend/tests/contracts/test_l3_executable_target_admission.py`

**Interfaces:**
- Produces: `ClaimDisposition`, `classify_claims(claims, *, dimension_key)` returning admitted interventions, pending claims, dispositions, and issues.

- [ ] **Step 1: Write focused classifier expectations**

```python
result = classify_claims([claim])
assert result.pending_claims == [claim]
assert result.dispositions[0].status == 'pending_grounding'
```

- [ ] **Step 2: Run the focused admission tests**

Run: `pytest backend/tests/contracts/test_l3_executable_target_admission.py -q`

- [ ] **Step 3: Implement typed dispositions and strict readiness partitioning**

```python
if readiness_gaps and set(readiness_gaps) <= pending_gap_names:
    pending_claims.append(claim)
    dispositions.append(ClaimDisposition(status='pending_grounding', ...))
```

- [ ] **Step 4: Run focused tests**

Run: `pytest backend/tests/contracts/test_l3_executable_target_admission.py -q`

### Task 2: Persist classifier output during program assembly

**Files:**
- Modify: `backend/app/domain/program/aggregate.py`
- Test: `backend/tests/contracts/test_l3_executable_target_admission.py`

**Interfaces:**
- Consumes: `classify_claims()` output.
- Produces: `PlanningProgram.pending_grounding_claims` and `PlanningProgram.claim_dispositions`.

- [ ] **Step 1: Write assembly assertions**

```python
assert program.pending_grounding_claims == [claim]
assert program.claim_dispositions[0].claim_id == claim.claim_id
```

- [ ] **Step 2: Replace aggregate-only strict admission with classifier use**

```python
classification = classify_claims(claims, dimension_key=frag.dimension_key)
interventions.extend(classification.interventions)
pending_claims.extend(classification.pending_claims)
```

- [ ] **Step 3: Run claim and aggregate tests**

Run: `pytest backend/tests/contracts/test_l3_executable_target_admission.py backend/tests/core/test_l3_planning_output_contract.py -q`
