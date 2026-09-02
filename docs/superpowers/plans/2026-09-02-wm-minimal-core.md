# WM Minimal Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a deterministic DATA-backed WM v0 with immutable CAS snapshots and a capability-scoped `CurrentWorldQueryPort` for Evidence and L1-GROUND.

**Architecture:** Keep one physical RDF/CAS snapshot for now, but expose only the current source/world projection through a dedicated read port. The v0 projection contains source records, world entities, entity parts, and DATA-owned spatial representations; intent, planned, assertion, merge/split, and automatic fusion remain outside the v0 query surface. Context Runtime injects the current port explicitly, and downstream current-view consumers cannot fall back to the generic whole-graph port.

**Tech Stack:** Python 3, Pydantic contracts, RDFLib named graphs, TriG serialization, filesystem-backed CAS, pytest.

## Global Constraints

- `DATA → WM v0 → Evidence / L1-GROUND` is the only required vertical slice.
- `CurrentWorldQueryPort` is mandatory for current-view consumers; callers must not self-filter planned data.
- Snapshot reload must preserve `snapshot_ref`, digest, and bounded query results deterministically.
- Do not add complex merge/split, automatic entity fusion, or complex ontology in this phase.
- Remove obvious legacy adapters, duplicate bootstrap work, and redundant current-view compatibility paths when no active caller needs them.

---

### Task 1: Lock the current-view contract

**Files:**
- Modify: `backend/app/contracts/ports/world_model.py`
- Modify: `backend/app/contracts/ports/planning_ports.py`
- Modify: `backend/app/contracts/cognition/ports.py`
- Test: `tests/test_world_model_v0.py`

**Interfaces:**
- Produce `CurrentWorldQueryPort` with bounded methods `find_source_records`, `find_entities`, and `representations_for`.
- Inject it as `PlanningPorts.current_world`.
- Keep write/legacy interfaces separate so Evidence and L1-GROUND never receive a generic whole-graph reader.

- [x] Add the typed protocol and test that the runtime port exposes only current-view methods and no planned/intent graph handle.
- [x] Make the test assert source/entity/representation result shapes include the WM snapshot ref/digest.
- [x] Run the focused contract and adapter tests.

### Task 2: Implement the bounded current-world adapter

**Files:**
- Create: `backend/app/infrastructure/kg/adapters/current_world_adapter.py`
- Modify: `backend/app/infrastructure/cognition_runtime/world_model_store.py`
- Test: `tests/test_world_model_v0.py`

**Interfaces:**
- `CurrentWorldQueryAdapter(store)` reads only `SOURCE_GRAPH` for source records and only `WORLD_GRAPH` for entity/part/representation rows.
- `find_source_records(*, source_record_ref="", source_feature_ref="", dataset_ref="", limit=50)` returns stable sorted bounded dictionaries.
- `find_entities(*, identity="", entity_ref="", source_feature_ref="", name="", entity_type="", limit=50)` returns stable sorted entity/part rows.
- `representations_for(entity_ref, *, limit=50)` returns stable sorted representation lineage rows.

- [x] Write failing adapter tests for source/entity/representation isolation and deterministic ordering.
- [x] Implement explicit named-graph traversal without `Dataset(default_union=True)` as a query boundary.
- [x] Attach `snapshot_ref` and `snapshot_digest` to every returned row and expose the adapter from the store.
- [x] Run the focused tests.

### Task 3: Wire the DATA → WM v0 bootstrap and remove duplicate current bootstrap

**Files:**
- Modify: `backend/app/infrastructure/context_runtime/manager.py`
- Modify: `backend/app/infrastructure/context_runtime/runtime.py`
- Remove: `backend/app/infrastructure/cognition_runtime/catalog_world_model.py` when no production caller remains
- Test: `tests/test_world_model_v0.py`

**Interfaces:**
- Context Runtime performs one DATA-backed WM store construction and injects `store.current_world` as `PlanningPorts.current_world`.
- Existing intent/planned commit behavior remains isolated from the v0 current query port.

- [x] Add an integration test that builds a context from an admitted DATA catalog and verifies the current port is present.
- [x] Remove the duplicated `get_world_model_store` call and stale generic current-port fallback.
- [x] Delete the unused direct-DATA legacy world-model adapter after confirming no imports remain.
- [x] Run context and WM focused tests.

### Task 4: Migrate Evidence and L1-GROUND current reads

**Files:**
- Modify: `backend/app/infrastructure/evidence_runtime/v2_catalog.py`
- Modify: `backend/app/modules/ground/reference_resolution.py`
- Modify: `backend/app/modules/evidence/application.py` only where current-view injection/writer fallback is touched
- Test: `tests/test_world_model_v0.py`
- Test: existing Evidence and Ground focused tests discovered during implementation

**Interfaces:**
- Evidence catalog retrieval and GROUND reference resolution require `context.ports.current_world`.
- No fallback from these paths to `context.ports.world_model`, `context.kg`, or a raw RDF graph is allowed in v2-only mode.
- Evidence does not write semantic decisions as part of the v0 current query path.

- [x] Add a regression test using a store containing planned triples and assert Evidence/GROUND current queries cannot see them.
- [x] Switch the v2 read helpers to `current_world` and fail clearly if it is missing.
- [x] Remove only the obsolete current-view compatibility branch, leaving deferred write features untouched.
- [x] Run focused Evidence/GROUND tests.

### Task 5: Reload/CAS deterministic exit gate and cleanup

**Files:**
- Modify: `backend/app/contracts/cognition/source.py` if a typed `SourceRecord` contract is required by the query result.
- Modify: `backend/app/contracts/cognition/snapshot.py` only if v0 snapshot metadata needs an explicit current-view field.
- Test: `tests/test_world_model_v0.py`
- Modify: relevant documentation only if the implementation contract differs from current docs.

**Interfaces:**
- Exit gate: build DATA snapshot → bootstrap WM v0 → obtain `snapshot_ref/digest` → reload from CAS → query source/entity/representation → compare exact normalized results.

- [x] Test a fresh store and a second store reloaded from the same CAS pointer.
- [x] Assert identical snapshot ref, digest, source record, entity, part, and representation rows.
- [x] Run the full relevant regression set and `git diff --check`.
- [x] Search for remaining active Evidence/GROUND generic current-port usage and remove only obvious redundant paths.
