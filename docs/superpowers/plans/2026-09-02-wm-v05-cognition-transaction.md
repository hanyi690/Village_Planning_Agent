# WM v0.5 Cognition Transaction Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old proposal-directly-accepted World Model write path with a deterministic Cognition transaction kernel that consumes proposal artifacts and decision artifacts, validates a current-world parent, rebuilds the affected projection, publishes an immutable CAS child, and returns a typed receipt.

**Architecture:** Keep the existing DATA-backed RDF/CAS store and immutable `SessionWorldModelSnapshot`. Introduce explicit v0.5 contracts for `AssertionProposal`, `AssertionDecisionArtifact`, `AssertionCommitRequest`, and `WorldModelCommitReceipt`. Cognition owns deterministic proposal validation and decision creation; the store only validates the request and applies the transaction. Current-world projection writes are limited to accepted decisions, while ambiguous/rejected assertion history remains auditable. The first commit group is one subject, which is deterministic and prevents unrelated proposals from blocking one another.

**Tech Stack:** Python 3, Pydantic v2 contracts, RDFLib named graphs, existing World Model CAS persistence, pytest.

## Global Constraints

- `Evidence`, `L1-GROUND`, `L1`, providers, and LLM-facing code may construct proposals but must not receive or call a current-world mutation primitive.
- A proposal without exactly one matching decision artifact cannot be committed; an `ACCEPT` decision must never be inferred from proposal status or an empty `decision_ref`.
- Only `ACCEPT` decisions may change the current WORLD projection. `AMBIGUOUS` and `REJECT` are recorded as assertion history without projection.
- A superseded accepted assertion must be marked superseded and its old current projection removed before the new projection is validated and published.
- Parent validation uses `expected_parent_snapshot` plus `expected_current_world_digest`; planned/intent changes must not authorize or invalidate this transaction.
- Invalid requests and stale parents leave all graphs, version, digest, and CAS state unchanged.
- Do not add merge/split automation, complex ontology, automatic fusion, or a new physical store in this phase.
- Remove the active old `commit_proposal_batch` contract and implementation rather than retaining a misleading compatibility facade.

## Task 1: Define the v0.5 transaction contracts

- [x] Replace the legacy proposal-only contracts in `backend/app/contracts/cognition/proposals.py` with the five explicit v0.5 value objects and their strict validation rules.
- [x] Export the new contracts from `backend/app/contracts/cognition/__init__.py`.
- [x] Update `backend/app/contracts/ports/world_model.py` so the commit port exposes the Cognition transaction operation with typed request, proposals, and decisions, while retaining only unrelated intent/planned/L1 port methods.
- [x] Add contract tests covering deterministic proposal fingerprints, one-to-one proposal/decision refs, parent consistency, decision enum values, and rejection of empty authority/source/evidence data where required.

## Task 2: Add deterministic Cognition validation

- [x] Add a small Cognition validation service under `backend/app/modules/cognition/` that accepts proposal value objects and emits one `AssertionDecisionArtifact` per proposal.
- [x] Make the validator deterministic and policy-driven: valid source/evidence-backed proposals with the current parent are accepted; explicitly unsupported/ambiguous proposal kinds are ambiguous; malformed, foreign, or parent-mismatched proposals are rejected.
- [x] Ensure the validator records `validator_ref`, `policy_ref`, `policy_version`, `reason_code`, and the same `parent_current_world_digest` on every decision.
- [x] Add tests proving the validator is the sole place that turns proposals into decisions and that no proposal field can directly authorize a current-world write.

## Task 3: Implement the atomic store transaction

- [x] Replace `WorldModelKGStore.commit_proposal_batch` in `backend/app/infrastructure/cognition_runtime/world_model_store.py` with `commit_assertion_transaction`.
- [x] Validate request parent snapshot, current-world digest, proposal/decision closure, fingerprints, source/evidence refs, entity ownership, and one-subject commit-group granularity before mutating any graph.
- [x] Persist proposal and decision audit nodes in the assertion graph, append semantic assertion history for all decisions, and project only accepted assertions into WORLD.
- [x] Rebuild projections for every superseded accepted assertion and verify that no superseded triple remains visible in WORLD.
- [x] Preserve the existing graph rollback and CAS publication path, produce an immutable child snapshot even when a valid group records only ambiguous/rejected decisions, and return `WorldModelCommitReceipt` with parent/child, accepted/ambiguous/rejected refs, affected refs, and old/new current digests.
- [x] Add focused store tests for Gate A (missing decision leaves world unchanged), Gate B (supersede removes old projection), Gate C (only Cognition commit operation can write accepted current assertions), stale CAS parent, replay/no-op, and unrelated-subject atomicity.

## Task 4: Route the real Cognition application through v0.5

- [x] Update `backend/app/modules/cognition/application.py` to load the reloadable current snapshot, build an `AssertionCommitRequest`, invoke deterministic Cognition validation, and call the new commit port operation.
- [x] Keep Evidence input at the artifact boundary: accept `EvidenceRetrievalArtifact`/receipt references as evidence refs and do not import provider or retrieval implementation internals into WM.
- [x] Store and reload the committed `SessionWorldModelSnapshot` and `WorldModelCommitReceipt` through the existing artifact state update path.
- [x] Remove old `WorldModelProposalBatch`/`WorldModelCommitResult` imports and call sites after migration; verify no active consumer depends on proposal-directly-accepted semantics.
- [x] Add an application integration test for DATA snapshot → WM v0 → reload → proposal/decision transaction → query entity/source/representation and receipt.

## Task 5: Verify and commit the implementation

- [x] Run targeted cognition, World Model, Evidence, L1-GROUND, and contract tests.
- [x] Run the full backend test suite or record any pre-existing collection/runtime failures separately from regressions introduced here.
- [x] Inspect the final diff for redundant compatibility code, generic full-graph access in the new Cognition write path, and accidental planned/intent coupling.
- [x] Commit the completed implementation on `codex/wm-minimal-core` with a message describing the v0.5 Cognition transaction kernel.

## Expected exit gate

`DATA snapshot → WM v0 → reload → query entity/source/representation` remains deterministic, and a real Evidence-backed Cognition transaction additionally satisfies:

`proposal → decision → request → projection rebuild → immutable CAS child → receipt`.
