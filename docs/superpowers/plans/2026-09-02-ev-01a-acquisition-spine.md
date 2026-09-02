# EV-01A Acquisition Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the Evidence acquisition path with `docs/design/04_EVIDENCE.md` by making requirement policy, immutable query plans, provider attempts, page records, observation lineage, acquisition receipts, and CAS replay form one local-only vertical slice.

**Architecture:** Evidence owns the semantic acquisition plan and immutable audit contracts. DATA and Current World remain read-only acquisition authorities; Evidence does not add a second provider/network writer. The first slice executes only local DATA, Current World, source-span, and frozen-cache reads, then produces typed attempts/observations/receipt data that is embedded in the existing replayable retrieval artifact.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, existing `EvidenceApplication`, `evidence_runtime`, CAS artifact store, pytest.

## Global Constraints

- `docs/design/04_EVIDENCE.md` is the design authority; `docs/design/acceptance/03_evidence_acceptance.md` remains the acceptance boundary.
- Preserve DATA acquisition ownership for endpoint/auth/network/lease/fencing/raw-response persistence; Evidence only creates the plan and consumes local acquisition results.
- New runtime facts must use the unified `ProviderAttemptStatus`; legacy observation statuses may be read only through an explicit adapter and must not be emitted by the new path.
- EV-01A records acquisition coverage and completeness; it must not claim policy-driven semantic sufficiency or create Cognition/World Model write proposals.
- External observations remain locator/advisory evidence and never gain executable geometry authority.
- Existing CAS/write-once behavior and current World Model branch/context isolation must remain deterministic.
- Keep changes minimal, use LF line endings, two-space frontend/four-space Python indentation, and preserve unrelated worktree changes.

---

### Task 1: Establish versioned policy and requirement contracts

**Files:**
- Create: `backend/app/contracts/evidence/policy_contracts.py`
- Modify: `backend/app/contracts/evidence/requirement_contracts.py`
- Modify: `backend/app/contracts/evidence/__init__.py`
- Test: `tests/test_evidence_acquisition_contracts.py`

**Interfaces:**
- Produces `EvidencePolicy`, `EvidencePolicyRegistry`, and deterministic `resolve_policy(policy_ref, policy_version=None)`.
- Extends `EvidenceRequirement` with `requirement_ref`, `requesting_artifact_ref`, `subject_refs`, `purpose`, `valid_time`, `policy_ref`, and `contract_version` while retaining only explicitly necessary compatibility aliases.
- Keeps policy thresholds out of `EvidenceRequirement`; authority, age, independent-source, inference, conflict, absence, completion, and budget rules belong to `EvidencePolicy`.

- [ ] **Step 1: Write failing contract tests** for policy resolution, unknown policy rejection, stable policy digest, and requirement validation requiring `policy_ref` for new EV-01A requirements.
- [ ] **Step 2: Run the focused contract tests** with `python -m pytest tests/test_evidence_acquisition_contracts.py -q`; verify they fail before implementation.
- [ ] **Step 3: Implement the typed policy contracts and deterministic registry** with the initial policies `location_identity_support.v1`, `facility_existence.v1`, `road_identity.v1`, `relation_support.v1`, `source_semantic_support.v1`, `execution_geometry_support.v1`, `legal_extent_support.v1`, and `absence_claim.v1`.
- [ ] **Step 4: Update requirement compilation** so generated requirements receive an explicit policy reference based on kind/evidence role, while preserving policy fields out of arbitrary metadata.
- [ ] **Step 5: Run the focused tests and existing requirement-related tests**; verify serialized output and fingerprints are stable.

### Task 2: Replace the lightweight runtime route plan with an immutable EvidenceQueryPlanV1

**Files:**
- Create: `backend/app/contracts/evidence/query_plan_contracts.py`
- Modify: `backend/app/infrastructure/evidence_runtime/query_planner.py`
- Modify: `backend/app/contracts/evidence/retrieval_contracts.py`
- Modify: `backend/app/infrastructure/evidence_runtime/artifact_store.py`
- Test: `tests/test_evidence_acquisition_contracts.py`

**Interfaces:**
- Produces `EvidenceQueryPlanV1`, `EvidenceProviderRoute`, `EvidencePageStrategy`, `EvidenceRetryPolicy`, `EvidenceTimeoutPolicy`, `EvidenceBudget`, `EvidenceCompletionCondition`, and `plan_fingerprint(plan)`.
- `EvidenceQueryPlanV1` includes `query_plan_ref`, `requirement_refs`, `normalized_query`, `subject_refs`, `scope`, `provider_routes`, page/retry/timeout/budget policies, `dedupe_key`, `completion_condition`, `policy_ref`, `policy_version`, `plan_fingerprint`, and `contract_version`.
- Keeps the old retriever grouping internal as `LegacyRetrieverRoutePlan` only at the adapter boundary; it must not be persisted as the formal plan.

- [ ] **Step 1: Add failing tests** for immutable plan serialization, deterministic digest, route ordering, policy binding, and fingerprint changes when page or budget semantics change.
- [ ] **Step 2: Implement the V1 plan contracts** with closed deterministic defaults for local DATA, Current World, source span, frozen cache, and optional external adapter routes.
- [ ] **Step 3: Make `build_query_plan()` return the formal plan** and keep the legacy retriever conversion private to runtime routing.
- [ ] **Step 4: Add the plan fingerprint and plan ref to retrieval fingerprint input** without changing unrelated artifact key semantics.
- [ ] **Step 5: Run focused plan tests and the existing retrieval artifact tests.**

### Task 3: Add ProviderAttempt and ProviderPageRecord lineage

**Files:**
- Create: `backend/app/contracts/evidence/acquisition_contracts.py`
- Modify: `backend/app/contracts/evidence/provider_attempt.py`
- Modify: `backend/app/contracts/evidence/external_observation_contracts.py`
- Modify: `backend/app/contracts/evidence/retrieval_artifact_contracts.py`
- Modify: `backend/app/contracts/evidence/__init__.py`
- Test: `tests/test_evidence_acquisition_contracts.py`

**Interfaces:**
- Produces `ProviderPageRecord`, `EvidenceAcquisitionReceipt`, and `EvidenceObservationSnapshot` lineage fields.
- Extends `ProviderAttempt` with `query_plan_ref`, `query_ref`, `reason_code`, `page_record_refs`, `item_count`, `raw_response_refs`, `next_retry_hint`, and `acquisition_digest`.
- New statuses must be represented by `ProviderAttemptStatus`; `ExternalObservationStatus` is limited to external observation records.
- `EvidenceAcquisitionReceipt` records query plan ref/fingerprint, attempt refs, page refs, observation snapshot ref/digest, completion state, and deterministic digest.

- [ ] **Step 1: Write failing tests** covering every terminal attempt state, lineage closure, page serialization, completion reasons, and the invariant that incomplete pages cannot produce a complete acquisition receipt.
- [ ] **Step 2: Implement strict Pydantic validation** for page/attempt parent refs, cursor progression, terminal status, item counts, and allowed termination reasons.
- [ ] **Step 3: Update observation snapshots and retrieval artifacts** to carry acquisition receipt refs and preserve external geometry authority restrictions.
- [ ] **Step 4: Add explicit legacy read adapters** and remove any new-path construction of broad `failed`/`missing` facts.
- [ ] **Step 5: Run focused contract tests and existing external observation/cache tests.**

### Task 4: Implement the local acquisition adapter without adding provider ownership

**Files:**
- Create: `backend/app/infrastructure/evidence_runtime/acquisition_executor.py`
- Modify: `backend/app/infrastructure/evidence_runtime/facade.py`
- Modify: `backend/app/infrastructure/evidence_runtime/v2_catalog.py`
- Modify: `backend/app/modules/evidence/application.py`
- Test: `tests/test_evidence_local_acquisition.py`

**Interfaces:**
- Produces `AcquisitionRouteResult` containing typed attempts, page records, observation snapshot, acquisition receipt, and existing bounded facts/sources.
- Consumes `EvidenceQueryPlanV1`, `EvidenceRetrievalAuthority`, current DATA catalog, Current World read view, source spans, and frozen external cache.
- Does not call online providers, own endpoint/auth/network/lease logic, or decide semantic sufficiency.

- [ ] **Step 1: Write failing Jintian/local tests** for DATA success, Current World success, source-span lineage, optional external `NOT_ATTEMPTED`, and read-only geometry behavior.
- [ ] **Step 2: Implement local route execution** by wrapping existing DATA catalog, Current World, local text/source-span, and cache-only reads; emit one attempt per planned route even when a route is not attempted.
- [ ] **Step 3: Emit page records and acquisition coverage** with `provider_exhausted` or explicit declared local bound, marking incomplete local results `PARTIAL`.
- [ ] **Step 4: Attach receipt/snapshot lineage to `ExplorationResult`, `EvidencePacket`, and `EvidenceRetrievalArtifact` without changing sufficiency semantics.**
- [ ] **Step 5: Run the focused local slice plus `tests/test_jintian_data_e2e_acceptance.py` and relevant cache/geometry tests.**

### Task 5: Remove obsolete compatibility paths and redundant plan/attempt construction

**Files:**
- Modify: `backend/app/modules/evidence/application.py`
- Modify: `backend/app/modules/evidence/ports.py`
- Modify: `backend/app/modules/evidence/dimension_facade.py`
- Modify: `backend/app/infrastructure/evidence_runtime/query_planner.py`
- Modify: `backend/app/infrastructure/evidence_runtime/facade.py`
- Modify: `backend/app/contracts/evidence/provider_attempt.py`
- Test: `tests/test_evidence_legacy_removal.py`

**Interfaces:**
- Keeps only compatibility adapters that are still required by API/workflow boundaries and makes them explicit/read-only.
- Removes duplicate formal `EvidenceQuery`/route-plan definitions and fallback synthesis of a generic local attempt when a typed local acquisition result exists.
- Does not remove an adapter until `rg` confirms there are no active callers and focused regression tests pass.

- [ ] **Step 1: Add tests** asserting the new path emits typed plan/attempt/receipt objects and does not emit broad legacy statuses.
- [ ] **Step 2: Inventory active imports and callers** with `rg` before deleting any compatibility symbol.
- [ ] **Step 3: Remove dead duplicate contracts and redundant fallback construction**, retaining only named adapters needed by API/workflow consumers.
- [ ] **Step 4: Run the full evidence-related test set and inspect the final diff for accidental boundary changes.**

### Task 6: Verify the EV-01A gate and update design/acceptance status

**Files:**
- Modify: `docs/design/acceptance/03_evidence_acceptance.md`
- Modify: `docs/design/04_EVIDENCE.md` only if an implementation fact is now outdated
- Test: all evidence-related tests plus the selected DATA/WM regression suite

**Interfaces:**
- Produces an auditable EV-01A verification report in the final response and test output; no new runtime API beyond the contracts from Tasks 1–4.

- [ ] **Step 1: Run contract, local acquisition, cache, geometry, World Model, and DATA end-to-end tests.**
- [ ] **Step 2: Verify the six EV-01 gates**: requirement policy binding, immutable plan, route attempts, page completeness, observation lineage/geometry boundary, and deterministic replay.
- [ ] **Step 3: Run `git diff --check` and `git status --short`; confirm no unrelated changes.**
- [ ] **Step 4: Update acceptance wording only for gates actually demonstrated by tests; leave Sufficiency, Gap Scheduler, and Cognition gates explicitly partial.**

## Spec coverage and intentional deferrals

This plan implements the pasted EV-01A direction and the acquisition portions of `04_EVIDENCE.md`: typed requirement policy, immutable query plan, unified attempt taxonomy, page completeness, local observation lineage, acquisition receipt, and replay. It intentionally does not implement online provider collection, policy-driven semantic sufficiency, persistent lease-based gap scheduling, Cognition rounds, proposal commit, L1-GROUND write migration, entity merge/split, or distributed scheduling.

## Execution checkpoint — 2026-09-02

Completed in this pass:

- Versioned `EvidencePolicy` registry and requirement identity/purpose/policy fields.
- Immutable `EvidenceQueryPlanV1` with route, page, retry, timeout, budget, completion, and digest fields.
- `RUNNING` provider status plus typed page/observation/receipt contracts.
- Query-plan fingerprint binding to CAS retrieval fingerprints and persisted retrieval artifacts.
- Removal of the unused duplicate `EvidenceQuery` contract and conversion of runtime routing to formal plan routes.
- Materialization of source-backed local facts into `EvidenceObservationSnapshot` records with route/attempt lineage.
- Persistence and replay exposure of the observation snapshot and acquisition receipt from `ExplorationResult`.
- Contract and DATA/WM/cache regression coverage.

Still intentionally open:

- Online provider-native collection and lease/retry execution remain out of EV-01B.
- Durable gap scheduling, policy-driven sufficiency, and Cognition proposal/commit.

## EV-01B execution checkpoint — 2026-09-02

Completed in the acquisition vertical slice:

- Added `AcquisitionRouteExecutor` and `AcquisitionRouteResult` under
  `infrastructure/evidence_runtime`; facade and V2 catalog now emit terminal
  route attempts before Application normalization.
- Added authority-neutral attempt kinds: `local_data`, `current_world`,
  `source_span`, `frozen_cache`, and `external_provider`.
- Added typed observation fields and the minimum DATA/CurrentWorld observation
  kinds: `DATA_SOURCE_RECORD`, `CURRENT_WORLD_ENTITY`, and
  `CURRENT_WORLD_REPRESENTATION`.
- Removed Application-side trace-to-attempt inference. Application now only
  validates runtime lineage before persisting the artifact.
- Enforced that local and frozen-cache acquisition cannot contain PageRecords;
  remote external terminal acquisition may contain a real page record.
- Receipt completion is based on `required_for_acquisition` routes and records
  completed, incomplete, and optional-unattempted route refs.
- CAS retrieval identity now follows business digests and plan fingerprint, so
  a physical WM snapshot handle change with the same current-world digest can
  replay the same artifact.
