# DATA → KG/Cognition → EVIDENCE Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the current DATA → KG/Cognition → EVIDENCE implementation against acceptance cards 00–03 without contacting any external map provider.

**Architecture:** Keep DATA as the only owner of loadable resources and CRS normalization, project its frozen catalog into a versioned KG-backed World Model, then let Evidence consume exactly matching DATA/KG artifacts plus read-only provider caches. Preserve source-feature, entity, part, representation, fact, and artifact identities as separate namespaces and fail closed whenever CRS, lineage, CAS parent, or local geometry is unavailable.

**Tech Stack:** Python 3.11, Pydantic v2, Shapely, PyProj, RDFLib, the existing content-addressed artifact repository, pytest, and PowerShell one-shot probes.

## Global Constraints

- Do not call AMap, Tianditu, Tencent, or any new external map API; use existing cache files only.
- Do not create test files; use existing tests and one-shot command probes.
- Preserve unrelated uncommitted work in the shared working tree.
- Use LF and four-space Python indentation.
- Keep source feature, WorldEntity, EntityPart, SpatialRepresentation, EvidenceFact, and CAS artifact identities distinct.
- Never grant an executable spatial capability without a loadable resource, explicit CRS, digest, source snapshot, and operation-specific parameter schema.

---

### Task 1: Close generic DATA resources and lineage

**Files:**
- Modify: `backend/app/data/resource_catalog.py`
- Modify: `backend/app/data/catalog/session_resource_catalog.py`
- Modify: `backend/app/data/ingestion/upload.py`

**Interfaces:**
- Consumes: arbitrary records, GeoJSON, multi-geometry rows, ZIP/GPKG multi-layer upload envelopes.
- Produces: stable dataset/feature/representation/resource/capability refs with per-layer and per-CRS lineage.

- [ ] Preserve a stable logical source-record ref while exposing every geometry field as an independently loadable representation.
- [ ] Keep ZIP/GPKG layer and source record identifiers in refs and raw provenance so equal FIDs in different layers do not collide.
- [ ] Leave geometry representations unresolved when CRS is missing or cannot be transformed to WGS84.
- [ ] Publish `union`, `split`, `merge`, `snap`, `topology_repair`, and `network_connection` only for compatible geometry kinds, with explicit required parameter schemas and approval gates.
- [ ] Probe mixed geometry, mixed CRS, unknown fields, and `capabilities_for()` without adding a test file.

### Task 2: Close World Model identity and CAS versioning

**Files:**
- Modify: `backend/app/infrastructure/kg/adapters/source_catalog_adapter.py`
- Modify: `backend/app/infrastructure/cognition_runtime/world_model_store.py`
- Modify: `backend/app/modules/evidence/application.py`

**Interfaces:**
- Consumes: one frozen `DataResourceCatalogSnapshot` and an optional current World Model snapshot digest.
- Produces: distinct source/entity/part/representation nodes and an immutable CAS snapshot protected by the descriptor observed by the writer.

- [ ] Verify source records remain immutable provenance nodes and never become entity or part IDs.
- [ ] Reject stale World Model writes by comparing the named ref with the writer's previously observed descriptor, not a descriptor re-read immediately before CAS.
- [ ] Roll back graph/version/descriptor state on CAS conflict.
- [ ] Reload the session/data-scoped store from CAS when Evidence expects a newer matching graph digest than the process-local store.
- [ ] Probe stale-writer rejection and cross-instance reload with a temporary CAS root.

### Task 3: Close cache evidence facts and immediate gaps

**Files:**
- Modify: `backend/app/contracts/evidence/evidence_contracts.py`
- Modify: `backend/app/data/catalog/external_observation_cache.py`
- Modify: `backend/app/infrastructure/evidence_runtime/gap_scheduler.py`
- Modify: `backend/app/modules/evidence/application.py`

**Interfaces:**
- Consumes: DATA/KG artifact refs, Evidence requirements, and local provider run manifests/normalized rows.
- Produces: stable `EvidenceFact.fact_id`, provider-run five-state audit rows, and scheduled gap rows with immediate/deferred recovery semantics.

- [ ] Derive `EvidenceFact.fact_id` from canonical semantic content so construction order and process restarts do not change it.
- [ ] Preserve every provider/stage run state; when Tencent has no normalized rows, emit no observations and never classify it as a successful empty fact.
- [ ] Normalize scheduler aliases such as `local_data`, `cache`, and `world_model` to their actual local capabilities.
- [ ] Execute ready local DATA/KG/cache retrieval immediately; keep unavailable and human-required gaps visible with recovery pointers.
- [ ] Probe provider status counts, stable fact IDs, immediate scheduling, and advisory-only cached-map results.

### Task 4: Verify and report

**Files:**
- Verify only; do not add test files.

**Interfaces:**
- Consumes: the completed DATA/KG/Evidence slice.
- Produces: command evidence and an explicit remaining-gap ledger.

- [ ] Run `python -m compileall -q backend/app`.
- [ ] Run existing relevant pytest modules under `tests/`.
- [ ] Run one-shot vertical probes for DATA reload, World Model CAS/reload, provider cache states, Evidence fact IDs, and scheduler behavior.
- [ ] Run `git diff --check` on changed files and report the exact file list, results, and any acceptance items still not satisfied.
