# EV-01C Frozen External Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admit frozen external-provider observations into the typed Evidence acquisition chain while preserving cache-read completeness, origin-provider completeness, provenance, and the no-execution-geometry boundary.

**Architecture:** The existing `ExternalObservationSnapshot` remains the frozen-cache source artifact. A runtime adapter will convert one cache read into a `frozen_cache` acquisition attempt and typed `EXTERNAL_OBSERVATION` records, while retaining the historical provider attempt and status as origin provenance. The Evidence application will validate and aggregate the runtime result; it will not promote historical provider state to the current route attempt or produce absence conclusions.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, pytest, existing content-addressed Evidence artifact store.

## Global Constraints

- Do not enter Sufficiency, absence reasoning, Gap scheduling, Cognition proposal/commit, WM write, or online provider acquisition.
- `cache_read_completeness` and `origin_provider_completeness` are separate facts.
- A frozen-cache read has `attempt_kind="frozen_cache"`, `provider="frozen_cache"`, no current `PageRecord`, and never becomes an external-provider attempt.
- Historical provider status is preserved as provenance; it is never guessed or upgraded.
- External coordinates remain advisory locator evidence and never become local DATA resource/representation geometry without DATA admission.
- Preserve replay identity and physical audit lineage as separate fields.
- Use `apply_patch` for edits, LF line endings, and 4-space Python indentation.

---

### Task 1: Freeze EV-01B regression boundaries

**Files:**
- Modify: `tests/test_evidence_acquisition_contracts.py`
- Modify: `backend/app/modules/evidence/application.py`
- Modify: `backend/app/infrastructure/evidence_runtime/artifact_store.py`

**Interfaces:**
- `EvidenceApplication._acquisition_audit()` raises `ArtifactReplayError` when runtime did not provide a typed snapshot/receipt.
- `retrieval_fingerprint()` uses business digests and plan fingerprint, while persisted `EvidenceRetrievalAuthority` keeps physical refs for audit.

- [ ] **Step 1: Add a failing test for missing runtime terminal attempts.**

```python
def test_application_fails_closed_without_runtime_acquisition_audit():
    with pytest.raises(ArtifactReplayError):
        _acquisition_audit(
            ExplorationResult(evidence_bundle=EvidenceBundle(request="roads")),
            query_plan=plan,
            context=Context(),
        )
```

- [ ] **Step 2: Run the focused test and verify it fails for the old fallback.**

Run: `python -m pytest tests/test_evidence_acquisition_contracts.py::test_application_fails_closed_without_runtime_acquisition_audit -q`

Expected: FAIL until the Application fallback is removed or fail-closed validation is present.

- [ ] **Step 3: Add a planned-only WM replay test.**

Use one authority with `world_model_snapshot_ref="S0"` and digest `C0`, copy it with `S1` and digest `C0`, and assert the Evidence retrieval fingerprint is unchanged; then change digest to `C1` and assert it changes.

- [ ] **Step 4: Run the EV-01B regression file.**

Run: `python -m pytest tests/test_evidence_acquisition_contracts.py -q`

Expected: PASS, including no-page local acquisition and fail-closed Application behavior.

---

### Task 2: Add the frozen external observation contract

**Files:**
- Modify: `backend/app/contracts/evidence/provider_attempt.py`
- Modify: `backend/app/contracts/evidence/acquisition_contracts.py`
- Modify: `backend/app/contracts/evidence/__init__.py`
- Test: `tests/test_evidence_frozen_external_cache.py`

**Interfaces:**
- `EvidenceObservationRecord` gains origin-provider and cache lineage fields: `origin_provider`, `origin_record_ref`, `origin_attempt_ref`, `origin_status`, `origin_query_fingerprint`, `cache_snapshot_ref`, `cache_digest`, `locator_crs`.
- `EvidenceAcquisitionReceipt` exposes `cache_read_complete` and `origin_completeness` at route-result granularity without changing the meaning of `complete`.

- [ ] **Step 1: Write failing contract tests for complete and incomplete origins.**

```python
def test_frozen_cache_success_preserves_quota_origin_as_incomplete():
    result = admit_frozen_external_cache(snapshot_with_origin("QUOTA_EXHAUSTED"))
    attempt = result.attempt
    observation = result.observations[0]
    assert attempt.attempt_kind == "frozen_cache"
    assert attempt.provider == "frozen_cache"
    assert attempt.status == "SUCCESS_NONEMPTY"
    assert attempt.page_record_refs == ()
    assert observation.origin_provider == "amap"
    assert observation.origin_status == "QUOTA_EXHAUSTED"
    assert result.receipt.cache_read_complete is True
    assert result.receipt.origin_completeness == "incomplete"
```

- [ ] **Step 2: Run the contract test and verify missing fields fail.**

Run: `python -m pytest tests/test_evidence_frozen_external_cache.py -q`

Expected: FAIL because the origin/cache fields and adapter do not yet exist.

- [ ] **Step 3: Implement the minimal typed fields and validators.**

Keep `ExternalObservation` as the source artifact shape, add only the typed Evidence lineage fields needed to distinguish the current frozen-cache attempt from the historical provider attempt, and reject local execution geometry refs on external observations.

- [ ] **Step 4: Run the focused contract tests.**

Run: `python -m pytest tests/test_evidence_frozen_external_cache.py -q`

Expected: PASS for complete origin, quota/partial origin, empty cache, and no-geometry cases.

---

### Task 3: Implement the frozen-cache runtime adapter

**Files:**
- Create: `backend/app/infrastructure/evidence_runtime/frozen_cache_adapter.py`
- Modify: `backend/app/infrastructure/evidence_runtime/acquisition_executor.py`
- Modify: `backend/app/infrastructure/evidence_runtime/v2_catalog.py`
- Modify: `backend/app/infrastructure/evidence_runtime/facade.py`
- Modify: `backend/app/modules/evidence/application.py`

**Interfaces:**
- `read_frozen_external_cache(context, query_plan, route, query, entity_scope, limit) -> AcquisitionRouteResult`.
- The adapter reads only `ExternalObservationSnapshot`, calls `retrieve_from_cached_map`, and builds `frozen_cache` attempt lineage.
- Historical provider attempts are copied as origin metadata only; current receipt status describes cache read execution.

- [ ] **Step 1: Add failing integration tests for cache-read/origin separation.**

Cover:

```text
origin SUCCESS_NONEMPTY + provider_exhausted
cache SUCCESS_NONEMPTY
→ current cache read complete, origin complete

origin QUOTA_EXHAUSTED / PARTIAL
cache SUCCESS_NONEMPTY
→ current cache read complete, origin incomplete

origin SUCCESS_EMPTY + provider_exhausted
cache SUCCESS_EMPTY
→ current cache read complete, no absence conclusion
```

- [ ] **Step 2: Implement the adapter as a read-only runtime boundary.**

Use `attempt_kind="frozen_cache"`, `provider="frozen_cache"`, `provider_name=""`, `page_record_refs=()`, and `reason_code="frozen_cache_read_complete"` for a successful bounded cache read. Preserve the source snapshot id/digest and map each returned external fact to `EXTERNAL_OBSERVATION`.

- [ ] **Step 3: Attach the adapter result to V2 and facade results.**

The route result must be present before Application commit. No Application code may synthesize an external attempt from `query_trace`, and no external cache read may be labeled as an AMap/Tianditu/Tencent current attempt.

- [ ] **Step 4: Run the focused integration tests.**

Run: `python -m pytest tests/test_evidence_frozen_external_cache.py tests/test_evidence_acquisition_contracts.py tests/test_external_observation_cache.py tests/test_external_observation_adapter.py -q`

Expected: PASS with no current PageRecord for frozen cache and preserved origin incompleteness.

---

### Task 4: Verify replay, reload, and geometry boundaries

**Files:**
- Modify: `backend/app/infrastructure/evidence_runtime/artifact_store.py` only if reload fields are incomplete.
- Modify: `backend/app/contracts/evidence/retrieval_artifact_contracts.py` only if typed frozen-cache lineage is not persisted.
- Test: `tests/test_evidence_frozen_external_cache.py`
- Test: `tests/test_jintian_data_e2e_acceptance.py`

**Interfaces:**
- Retrieval CAS reload preserves `EvidenceObservationSnapshot.digest`, `EvidenceAcquisitionReceipt.digest`, attempt refs, origin refs, cache snapshot ref/digest, and physical authority lineage.

- [ ] **Step 1: Add replay/reload tests.**

Assert same `D0/C0/P1/Q0` replays the same artifact, changing only the physical cache root does not change semantic identity, changing cache digest creates a new artifact, and reloaded snapshot/receipt digests are stable.

- [ ] **Step 2: Add the geometry boundary assertion.**

For cached coordinates, assert `geometry_authority` is `none` or `locator_only`, and assert no external observation exposes a local DATA `resource_ref` or execution `representation_ref`.

- [ ] **Step 3: Run the complete acquisition P0 regression set.**

Run: `python -m pytest tests/test_evidence_acquisition_contracts.py tests/test_evidence_frozen_external_cache.py tests/test_external_observation_cache.py tests/test_external_observation_adapter.py tests/test_jintian_data_e2e_acceptance.py tests/test_world_model_v0.py -q`

Expected: PASS; no Sufficiency or absence conclusion test is added in this plan.

- [ ] **Step 4: Run hygiene checks and update the plan checkpoint.**

Run: `git diff --check` and `python -m compileall -q backend/app/contracts/evidence backend/app/infrastructure/evidence_runtime backend/app/modules/evidence`.

Record that EV-01C freezes Evidence Acquisition P0 at local DATA + CurrentWorld + source spans + frozen external cache + deterministic replay. Online provider acquisition remains P1/P2.

## Execution checkpoint — 2026-09-02

Implemented:

- `EvidenceObservationRecord` now preserves origin provider, origin attempt/status/query fingerprint, cache snapshot/digest, and locator CRS.
- `EvidenceAcquisitionReceipt` now separates current `cache_read_complete` from `origin_completeness`.
- Added `frozen_cache_adapter.py` and wired it into V2 catalog and the general facade cached-map path.
- Frozen cache reads use `attempt_kind="frozen_cache"`, `provider="frozen_cache"`, no current PageRecord, and advisory-only geometry semantics.
- Explicit external source-family requirements produce a required cache route; context-only external routes remain optional.
- Added complete-origin, quota-origin, empty-cache, no-geometry, and lineage regression coverage.

Verification:

- `tests/test_evidence_frozen_external_cache.py` plus acquisition/cache/WM/Jintian regression: 30 passed.
- Latest focused EV-01B/EV-01C contract run after typed-cache cleanup: 14 passed.
- `git diff --check` and targeted `compileall` passed.

Deferred by design:

- Online provider acquisition and historical cache pagination reconstruction.
- Sufficiency, absence conclusion, Gap scheduler, Cognition transaction, and WM write.
