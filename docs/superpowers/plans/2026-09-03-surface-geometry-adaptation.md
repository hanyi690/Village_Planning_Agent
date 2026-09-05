# Surface Geometry Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real Jintian vector inputs consumable by DATA, WM, and Evidence without pretending that a `Polygon`/`MultiPolygon` type change is lossless.

**Architecture:** Keep the source geometry type and coordinates immutable in the raw representation. Extend DATA's internal spatial capability contract from exact geometry type equality to an explicit homogeneous surface family (`Polygon`/`MultiPolygon`), while preserving `source_geometry_type`, `normalized_geometry_type`, parts, area, and repair provenance. Accept a repaired result only when it is valid, non-empty, in the same homogeneous family, and within the coordinate/range contract; retain a complete valid mixed-dimensional `GeometryCollection` as a read-only normalized representation and keep unresolved CRS fail-closed. Downstream consumers use the normalized geometry and its capability lineage, never the raw payload or a guessed layer name.

**Tech Stack:** Python 3.12, Pydantic v2, Shapely/GEOS, GeoJSON, pytest, existing DATA `DataAdmissionFacade`, WM projection, and Evidence catalog retriever.

## Global Constraints

- GeoJSON geometry types remain the fixed RFC 7946 set; do not introduce a custom GeoJSON type such as `PolygonFamily`.
- `Polygon` and `MultiPolygon` are both 2D surface representations, but the normalized type change must remain explicit and auditable.
- Raw source geometry is immutable and is never overwritten by `make_valid`.
- Unknown filenames and arbitrary business fields cannot prove resource role or geometry semantics.
- CRS is explicit; missing or unsupported CRS remains fail-closed.
- A repair result containing lower-dimensional or mixed-dimensional parts is not silently reduced to a polygon; a complete valid `GeometryCollection` is retained only as a read-only collection representation.
- BoundaryScopeArtifact may only use an admitted normalized Polygon/MultiPolygon representation.
- Existing unrelated WM/L1 working-tree changes must not be overwritten or included in a focused commit.

### Task 1: Define surface-family compatibility and repair audit

**Files:**
- Modify: `backend/app/data/resource_catalog.py:109-205`
- Modify: `backend/app/contracts/data/source_contracts.py:SourceFeature`
- Test: `tests/test_jintian_topology_policy.py`
- Test: `tests/test_data_admission_mvp.py`

**Interfaces:**
- `geometry_kind` remains the source coarse family, while `normalized_geometry_kind` records the actual normalized family; `topology_repair_audit` records exact source and normalized GeoJSON types.
- The topology policy becomes `surface_family_compatible`; Polygon and MultiPolygon are compatible only for homogeneous polygonal spatial operations.
- `make_valid` must preserve both geometries and write a trace when exact type changes; same-family repaired geometry is executable, while a complete valid collection result is read-only and all other non-family results remain unresolved.

- [x] **Step 1: Write failing assertions for the new policy.**

  Assert that Jintian landuse indices 22 and 258, and ecological index 4, retain their raw `MultiPolygon`, expose a valid normalized `Polygon`, and record `source_geometry_type != repaired_geometry_type` plus `review_required=True`. Assert that feature 343 records its parts and area audit. Assert that a Polygon repaired to a mixed-dimensional GeometryCollection remains unresolved.

- [x] **Step 2: Run the focused tests and verify the old strict policy fails them.**

  Run `python -m pytest tests/test_jintian_topology_policy.py tests/test_data_admission_mvp.py -q`.

- [x] **Step 3: Implement family compatibility in the validator.**

  Replace exact `repaired_type != source_type` rejection with a named compatibility predicate that permits only `Polygon`/`MultiPolygon` pairs for the `polygon` family. Keep `source_geometry_type`, `repaired_geometry_type`, parts, areas, delta, method, and review signals in the audit. Add a trace token that explicitly records `surface_family_compatible` and the exact type transition.

- [x] **Step 4: Run focused topology tests.**

  Run `python -m pytest tests/test_jintian_topology_policy.py tests/test_data_admission_mvp.py -q` and confirm the repair audit and normalized views are stable.

- [ ] **Step 5: Commit the isolated geometry contract change.**

  Run `git add backend/app/data/resource_catalog.py backend/app/contracts/data/source_contracts.py tests/test_jintian_topology_policy.py tests/test_data_admission_mvp.py` and `git commit -m "feat(data): support audited surface geometry repairs"` only if the files contain no unrelated changes.

### Task 2: Admit the complete local Jintian P0 input set

**Files:**
- Modify: `backend/app/modules/data/application.py:748-965`
- Modify: `backend/app/data/admission.py:700-890`
- Test: `tests/test_data_admission_mvp.py`

**Interfaces:**
- `DataAdmissionFacade.admit()` returns `ADMITTED` for a resource whose normalized features are all valid and spatially executable, even when a same-family topology repair needs review.
- Feature-level quarantine remains available for genuinely unresolved features; it must not be used for a same-family Polygon/MultiPolygon representation that passed the invariant checks.
- `current_world_snapshot()` and catalog admission indexes continue to use normalized geometry and explicit admission decisions.

- [x] **Step 1: Add the real-input acceptance expectations.**

  Update the Jintian P0 admission test so all ten GeoJSON resources, the DEM descriptor, and the Markdown report are admitted; separately assert that feature 343 carries `review_required` and that raw geometry remains unchanged.

- [x] **Step 2: Run the real-input acceptance test and capture the current failures.**

  Run `python -m pytest tests/test_data_admission_mvp.py::test_real_jintian_p0_inputs_are_admissible_through_facade -q`.

- [x] **Step 3: Change only the resource-level gate needed by the new normalized representation.**

  Ensure the gate evaluates `normalized_geometry is None` rather than exact source type, and that family-compatible repaired geometries produce normal capabilities. Preserve a non-blocking repair review signal in the feature audit and catalog diagnostics. Do not relax CRS, bounds, empty geometry, or mixed-dimension checks.

- [x] **Step 4: Run the full local Jintian DATA acceptance.**

  Run `python -m pytest tests/test_data_admission_mvp.py::test_real_jintian_p0_inputs_are_admissible_through_facade tests/test_jintian_data_e2e_acceptance.py -q`.

- [ ] **Step 5: Commit the Jintian admission change.**

  Run `git add backend/app/modules/data/application.py backend/app/data/admission.py tests/test_data_admission_mvp.py` and `git commit -m "test(data): admit real jintian p0 resources"` only after reviewing the staged diff.

### Task 3: Verify WM and Evidence consume normalized DATA products

**Files:**
- Modify: `tests/test_jintian_data_e2e_acceptance.py`
- Modify: `backend/app/infrastructure/evidence_runtime/retrievers/data_catalog_retriever.py` only if a failing contract test proves it is necessary
- Modify: WM projection module only if a failing contract test proves it is necessary
- Test: `tests/test_jintian_data_e2e_acceptance.py`

**Interfaces:**
- WM receives admitted normalized catalog products and dependency digests.
- Evidence receives `data:` source references and never reads raw local files or mutates catalog geometry.
- A family-compatible type transition is visible in lineage/audit but does not change the source feature identity.

- [x] **Step 1: Add consumer assertions for repaired Jintian features.**

  Build the admitted landuse/ecological catalogs, bootstrap WM, retrieve from the DATA catalog through Evidence, and assert that repaired features have normalized polygon geometry, stable `source_feature_ref`, `geometry_authority=data_resource_catalog`, and non-empty dependency graph digest.

- [x] **Step 2: Run the consumer test before any consumer change.**

  Run `python -m pytest tests/test_jintian_data_e2e_acceptance.py -q`.

- [x] **Step 3: Make the smallest consumer correction only if required.**

  Route consumers through the existing normalized representation/capability refs. Do not add filename-based or business-field-based geometry conversion in WM/Evidence.

- [x] **Step 4: Run the consumer and full test suites.**

  Run `python -m pytest tests/test_jintian_data_e2e_acceptance.py tests/test_jintian_topology_policy.py -q`, then `python -m pytest tests -q`.

- [ ] **Step 5: Commit the consumer verification change if any code changed.**

  Use `git diff --check`, review the focused staged diff, and commit with `test(data): verify repaired geometry consumption`.

### Task 4: Align executable design and acceptance evidence

**Files:**
- Modify: `docs/design/DATA_EXECUTABLE_DESIGN.md:topology policy and Jintian acceptance`
- Modify: `docs/design/DATA_PRODUCTION_RUNBOOK.md:geometry repair and provider preconditions`
- Modify: `docs/design/05_MIGRATION.md:surface-family migration boundary`
- Test: `tests/test_p1_p2_docs.py` if the repository contains this document regression suite

**Interfaces:**
- Design documents state one authoritative topology policy and do not claim strict type if the implementation accepts same-family type transitions.
- The acceptance command reports local input admission separately from provider-cache coverage.

- [x] **Step 1: Document the Polygon/MultiPolygon distinction and policy.**

  State that Polygon is one surface with one exterior ring and optional holes, while MultiPolygon is a homogeneous collection of Polygons. State that same-family adaptation is not a claim of exact type preservation.

- [x] **Step 2: Document fail-closed cases.**

  Record that incomplete/lower-dimensional collapse, invalid bounds, unresolved CRS, and ambiguous topology remain quarantined or blocked; a complete valid GeometryCollection can be consumed by WM/Evidence only through its read-only collection representation, while polygon execution still requires an explicit polygon-family normalized view.

- [x] **Step 3: Record official sources.**

  Link RFC 7946, OGC Simple Feature Access, Shapely `make_valid`, and GDAL geometry validity/make-valid documentation. Mark conclusions about the repository's specific features as runtime evidence, not external facts.

- [x] **Step 4: Run documentation and production checks.**

  Run `python -m pytest tests/test_p1_p2_docs.py -q` when present, `git diff --check`, and `python scripts/acceptance/data_production_acceptance.py --root .`.

- [ ] **Step 5: Commit the documentation update.**

  Run `git add docs/design/DATA_EXECUTABLE_DESIGN.md docs/design/DATA_PRODUCTION_RUNBOOK.md docs/design/05_MIGRATION.md tests/test_p1_p2_docs.py` for existing files only, review, and commit `docs: define surface geometry adaptation contract`.

## Self-Review Checklist

- [x] No code path relies on a filename or arbitrary field to decide that a geometry is a boundary or current fact.
- [x] No custom GeoJSON geometry type was introduced.
- [x] Every type transition is visible in a repair audit and transform trace.
- [x] Every normalized geometry consumed by WM/Evidence has explicit CRS and capability lineage.
- [x] Real Jintian local resources and provider cache coverage are reported separately.
- [x] Existing unrelated WM/L1 changes remain outside focused commits.
