# Cognition Round Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Introduce an explicit workflow-owned CognitionRound carrier so Evidence retrieval and proposal batches use a validated round/epoch/parent-snapshot contract.

**Architecture:** Workflow/Cognition creates an immutable `CognitionRound` from the pinned World Model parent and the exact requirement set. Evidence receives that contract through `EvidenceContext`, validates it, persists it in retrieval authority, and copies its identity into `EvidenceProposalBatch`; WM remains the only assertion writer.

**Tech Stack:** Python 3, Pydantic contracts, LangGraph workflow state, content-addressed artifacts, pytest.

## Global Constraints

- Follow `docs/design/04_EVIDENCE.md`: every round binds round, `wm_epoch`, parent snapshot digest, requirement set digest, and proposal fingerprint.
- Workflow/Cognition owns round creation; Evidence must reject retrieval without an explicit round and must not synthesize one from retrieval ids or snapshot fields.
- The round parent is immutable for the retrieval; a changed WM parent requires a new round.
- Evidence produces proposals only; WM continues to validate and commit assertions through its Cognition commit port.
- Existing DATA admission, Evidence sufficiency, artifact CAS, and WM transaction behavior must remain working.

---

### Task 1: Add the immutable round contract and workflow carrier

**Files:**
- Create: `backend/app/contracts/cognition_round.py`
- Modify: `backend/app/contracts/cognition/__init__.py`
- Modify: `backend/app/workflow/state.py`
- Create: `backend/app/workflow/cognition_context.py`
- Modify: `backend/app/infrastructure/context_runtime/runtime.py`
- Modify: `backend/app/infrastructure/context_runtime/manager.py` only if the
  context factory needs to publish the carrier

**Interfaces:**
- Produces: `CognitionRound`, `open_cognition_round(...)`.
- Consumes: pinned WorkflowState/PlanningContext World Model snapshot identity and typed EvidenceRequirement values.

- [x] **Step 1: Add failing contract tests**
- [x] **Step 2: Implement strict round identity and deterministic factory**
- [x] **Step 3: Carry the round through WorkflowState and PlanningContext**
- [x] **Step 4: Run contract tests**

### Task 2: Bind Evidence retrieval and ProposalBatch to the explicit round

**Files:**
- Modify: `backend/app/contracts/evidence/retrieval_contracts.py`
- Modify: `backend/app/contracts/evidence/proposal_contracts.py`
- Modify: `backend/app/infrastructure/evidence_runtime/artifact_store.py`
- Modify: `backend/app/modules/evidence/application.py`
- Modify: `backend/app/modules/evidence/coverage.py`
- Modify: `backend/app/modules/evidence/proposals.py`

**Interfaces:**
- Consumes: `EvidenceContext.cognition_round`.
- Produces: retrieval authority and ProposalBatch with matching round/epoch/parent/requirement lineage and frozen proposal fingerprint.

- [x] **Step 1: Make retrieval authority carry `CognitionRound`**
- [x] **Step 2: Require the explicit round in EvidenceContext and validate the requirement digest**
- [x] **Step 3: Build and persist proposals from the round contract**
- [x] **Step 4: Run Evidence contract and persistence tests**

### Task 3: Pass rounds from workflow and Cognition callers

**Files:**
- Modify: `backend/app/modules/ground/application.py`
- Modify: `backend/app/modules/ground/stage.py`
- Modify: `backend/app/modules/l1/aggregation.py`
- Modify: `backend/app/infrastructure/evidence_runtime/dimension_runtime.py`
- Modify: `backend/app/workflow/layers/context_bootstrap.py`
- Modify: relevant tests constructing EvidenceContext or EvidenceRetrievalAuthority.

**Interfaces:**
- Consumes: workflow state/context and requirement batches.
- Produces: every production DATA-backed Evidence retrieval call has an explicit workflow-created `CognitionRound`.

- [x] **Step 1: Create a round immediately before each Evidence retrieval batch**
- [x] **Step 2: Pass the round into EvidenceContext**
- [x] **Step 3: Reject missing or mismatched parent identity**
- [x] **Step 4: Run workflow, GROUND, L1, and Evidence tests**

### Task 4: Preserve WM transaction boundary and verify end to end

**Files:**
- Modify: `backend/app/contracts/cognition/proposals.py` only if commit request needs round lineage.
- Modify: `backend/app/modules/cognition/application.py` only if round validation is required at the Cognition boundary.
- Create or modify: focused round/proposal boundary tests.

- [x] **Step 1: Verify Proposal conversion carries the round-bound parent and fingerprint**
- [x] **Step 2: Verify WM commit remains the only writer**
- [x] **Step 3: Run compile/import, focused tests, and the full test suite**
- [x] **Step 4: Review and commit**

## Self-review

- The explicit round is created outside Evidence and is persisted in Evidence retrieval authority.
- Proposal batches carry the same round identity and cannot mix parent snapshots or requirement sets.
- Absence and Sufficiency semantics are unchanged; only round lineage is strengthened.
- No EvidenceGraph or historical compatibility surface is reintroduced.
