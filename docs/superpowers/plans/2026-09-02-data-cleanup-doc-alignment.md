# DATA Cleanup and Documentation Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove unreferenced DATA legacy implementations and align the executable DATA design with the actual admission, catalog, provider, WM, Evidence, and invalidation paths.

**Architecture:** `DataAdmissionFacade` remains the sole DATA write boundary. DATA source drivers and immutable catalog products remain; unreferenced typed Bundle-era adapters, provider anchor aggregators, and DATA-side fuzzy helpers are deleted. WM and Evidence consume only the normalized catalog or explicitly marked advisory observation cache.

**Tech Stack:** Python 3.12, Pydantic v2, Shapely, GeoPandas, rasterio, filesystem CAS, SQLite, pytest, Markdown.

## Global Constraints

- Do not reintroduce Bundle assembly, BSM/DLBM-derived DATA products, external anchor injection, fixed boundary reads, or cross-protocol provider fallback.
- Do not delete planning-layer public response containers unless all callers and contracts are migrated in the same change.
- All DATA writes go through `DataAdmissionFacade`; catalog and provider products remain immutable and digest-addressed.
- Unknown CRS, invalid geometry, incomplete provider coverage, stale parents, and missing admission receipts fail closed.
- `output/` contains no DATA cache or legacy Bundle input; caches use `data/cache/map_observations` and `data/cache/tiles`.
- Every implementation change must have a focused regression test and an updated current-state design statement.

---

### Task 1: Remove unreferenced DATA legacy modules

**Files:**
- Delete: `backend/app/data/ingestion/ingest.py`
- Delete: `backend/app/data/ingestion/adapters/__init__.py`
- Delete: `backend/app/data/ingestion/adapters/document.py`
- Delete: `backend/app/data/ingestion/adapters/features.py`
- Delete: `backend/app/data/ingestion/adapters/parcels.py`
- Delete: `backend/app/data/ingestion/adapters/raster.py`
- Delete: `backend/app/data/ingestion/adapters/table.py`
- Delete: `backend/app/data/ingestion/providers/poi.py`
- Delete: `backend/app/data/ingestion/providers/amap/anchor_service.py`
- Delete: `backend/app/data/ingestion/providers/tencent/anchor_service.py`
- Delete: `backend/app/data/ingestion/providers/tianditu/anchor_service.py`
- Delete: `backend/app/data/ingestion/gazetteer.py`
- Delete: `backend/app/data/ingestion/encoding_detector.py`
- Delete: `backend/app/data/catalog/admin_code_loader.py`
- Delete: `backend/app/data/model/location_parser.py`
- Modify: `backend/app/data/ingestion/__init__.py`
- Modify: `backend/app/data/README.md`
- Modify: `backend/app/data/ingestion/README.md`
- Modify: `backend/app/data/ingestion/providers/amap/README.md`
- Modify: `backend/app/data/ingestion/providers/tencent/README.md`
- Modify: `backend/app/data/ingestion/providers/tianditu/README.md`
- Test: `tests/test_retired_data_modules.py`

**Interfaces:**
- The only public DATA ingestion entry is `process_uploaded_file()` plus `DataAdmissionFacade`; source drivers remain available through `DriverRegistry`.
- No production module may import the deleted modules or expose their symbols from `app.data.ingestion`.

- [ ] **Step 1: Add absence and import-boundary assertions**

  Extend `tests/test_retired_data_modules.py` with the exact deleted paths and assert that importing `app.data.ingestion`, `app.data.ingestion.sources`, and `app.modules.data.application` succeeds without importing any deleted module.

- [ ] **Step 2: Run the focused boundary tests**

  Run: `python -m pytest tests/test_retired_data_modules.py -q`

  Expected: FAIL only because the deleted paths and old `ingest` exports still exist.

- [ ] **Step 3: Remove obsolete exports and documentation references**

  Remove the `ingest` imports/exports from `backend/app/data/ingestion/__init__.py`; change DATA READMEs to list only active facade, drivers, connections, boundary, catalog, and observation-cache responsibilities.

- [ ] **Step 4: Physically delete the unreferenced files**

  Delete only the exact files listed in this task after `rg` confirms no production imports. Do not replace them with compatibility shims.

- [ ] **Step 5: Run import and focused verification**

  Run: `python -m pytest tests/test_retired_data_modules.py tests/test_data_remote_admission.py tests/test_jintian_data_e2e_acceptance.py -q`

  Expected: PASS and no deleted file exists.

---

### Task 2: Make current DATA documentation authoritative and implementation-aligned

**Files:**
- Rewrite: `docs/design/DATA_EXECUTABLE_DESIGN.md`
- Modify: `docs/design/DATA_PRODUCTION_RUNBOOK.md`
- Modify: `docs/design/05_MIGRATION.md`
- Modify: `docs/design/DOCUMENTATION_AUTHORITY.md`
- Modify: `backend/app/data/README.md`
- Modify: `backend/app/data/catalog/README.md`
- Modify: `backend/app/infrastructure/evidence_runtime/retrievers/README.md`
- Modify: `backend/app/infrastructure/kg/README.md`
- Test: `tests/test_data_p1_p2_docs.py`

**Interfaces:**
- Documentation must describe the current path as code, not the retired target path.
- It must distinguish `runtime-verified`, `documented`, `inferred`, and `open` claims.
- It must explicitly document local current inputs, DEM/report, map cache roots, remote declaration-only admission, topology policy, WM/Evidence consumption, invalidation, recovery, and production gates.

- [ ] **Step 1: Locate contradictory claims**

  Search the design docs for statements that say upload uses synchronous admission, that WM/Evidence are out of scope, that old output caches remain migration sources, or that the catalog contains resource bodies.

- [ ] **Step 2: Replace the design with a current-state document**

  Document the active contracts and exact module paths, a flow diagram, product/ref table, lifecycle and failure states, strict topology audit including Jintian feature 343, remote driver protocol closure, provider writer fencing, dependency invalidation, consumer rules, deletion boundary, and verification evidence.

- [ ] **Step 3: Align runbook and authority index**

  Ensure the runbook commands and migration document point to `data/cache/*`, the immutable CAS products, and the real `v2_only` WM/Evidence path. Mark live provider coverage and deployment ACL/DR exercise as open release gates rather than completed local facts.

- [ ] **Step 4: Add documentation consistency tests**

  Assert that current docs contain the active facade/retriever/cache terms and do not claim the old synchronous upload path or old output cache as a valid source.

- [ ] **Step 5: Run documentation tests**

  Run: `python -m pytest tests/test_data_p1_p2_docs.py -q`

  Expected: PASS.

---

### Task 3: Final DATA verification and physical-retirement audit

**Files:**
- Modify: `backend/app/contracts/data/production_acceptance_contracts.py`
- Modify: `backend/app/modules/data/production_acceptance.py`
- Modify: `tests/test_data_production_acceptance.py`
- Modify: `tests/test_retired_data_modules.py`

**Interfaces:**
- Static acceptance must fail when deleted DATA paths, output cache paths, old Bundle input directories, or deleted-module imports return.
- Dynamic local acceptance remains `python -m pytest tests -q`; no remote network call is required for this local gate.

- [ ] **Step 1: Expand retired-path policy**

  Include every physically deleted DATA module and the output cache/bundle patterns in the policy and scanner.

- [ ] **Step 2: Run the complete verification suite**

  Run: `python -m pytest tests -q; python -m compileall -q backend/app scripts tests; python scripts/acceptance/data_production_acceptance.py --root .; git diff --check`.

- [ ] **Step 3: Record the evidence boundary**

  Report exact test counts, static scan counts, physical deletion results, retained cache roots, warnings, and release-environment open gates.

---

## Self-review coverage

- Legacy DATA implementation removal: Task 1.
- Accurate and detailed DATA design documentation: Task 2.
- Production static gate and final verification: Task 3.
- WM/Evidence consumer guarantees remain protected by existing Jintian E2E and dependency invalidation tests.

No compatibility shim, fallback import, fixed-boundary read, or old output cache source is permitted by this plan.
