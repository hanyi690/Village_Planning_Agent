# DATA Performance Acceleration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the real Jintian DATA → WM → Evidence cold-start latency while preserving one canonical catalog, immutable geometry, and CPU fallback correctness.

**Architecture:** Normalize the incoming `DataResourceCatalog` exactly once before constructing `SpatialWorkspace`; reuse the resulting catalog and manifest through context bootstrap instead of re-running current-world admission. Keep WM projection/CAS and Evidence on their existing contracts, then add an optional accelerator port only for post-normalization batch spatial or raster arithmetic. CUDA is never an admission, CRS, topology-repair, identity, or persistence authority.

**Tech Stack:** Python 3.12, Pydantic, Shapely/GEOS, pyproj, RDFLib, SQLite/CAS, pytest, optional CuPy/cuDF/cuSpatial.

## Global Constraints

- DATA remains generic and must not infer semantics from filenames or arbitrary source fields.
- `current_world_snapshot()` is the single CPU canonicalization boundary for a context build.
- `Shapely/GEOS make_valid` and surface-family topology audit remain the authoritative geometry path.
- Source, normalized, representation, capability, catalog, boundary, WM, and Evidence digests must remain stable for identical input.
- GPU dependencies are optional; an environment without CUDA must produce the same consumable WM/Evidence result.
- GPU failure or invariant mismatch falls back to CPU without changing admission, coverage, identity, or Evidence sufficiency.
- Every optimization needs a real Jintian regression test and a before/after timing record.

## Task 1: Establish the duplicate-normalization regression

**Files:**
- Modify: `tests/test_jintian_data_e2e_acceptance.py`
- Test: `tests/test_jintian_data_e2e_acceptance.py::test_real_jintian_complete_p0_catalog_is_consumable_by_wm_and_evidence`

**Interfaces:**
- Consumes: the existing complete Jintian P0 catalog fixture and `build_planning_context()`.
- Produces: a regression assertion that the context receives the same catalog digest and feature count as the caller.

- [x] **Step 1: Record the current baseline**

Run:

```text
python -m pytest tests/test_jintian_data_e2e_acceptance.py -q --durations=20
```

Observed baseline: complete P0 test 85.82 s; context log 54.5 s; WM initialization 9.9 s.

- [x] **Step 2: Use the existing digest/feature assertions as the failing-protection test**

The complete acceptance already asserts the catalog feature count, dependency digest, WM creation,
Evidence retrieval, and invalidation. Keep these assertions in place while changing only the
canonicalization ownership in Task 2.

- [x] **Step 3: Run the focused test before implementation**

Run:

```text
python -m pytest tests/test_jintian_data_e2e_acceptance.py::test_real_jintian_complete_p0_catalog_is_consumable_by_wm_and_evidence -q
```

Expected: PASS at the current baseline and provide the comparison point for Task 2.

## Task 2: Canonicalize the catalog once during context bootstrap

**Files:**
- Modify: `backend/app/infrastructure/context_runtime/manager.py:558-640`
- Modify: `backend/app/spatial/model/workspace.py:21-36`
- Test: `tests/test_jintian_data_e2e_acceptance.py`

**Interfaces:**
- Consumes: a `DataResourceCatalog` or raw generic catalog passed to `build_planning_context()`.
- Produces: one admitted `DataResourceCatalog` reused by `SessionDataSnapshot`, `SpatialWorkspace`, WM,
  and Evidence.

- [x] **Step 1: Move the current-world conversion before workspace construction**

After raw input conversion in `build_planning_context()`, call:

```python
data_resource_catalog = DataResourceCatalog(
    current_world_snapshot(data_catalog.snapshot)
)
assert_current_world_catalog(data_resource_catalog.snapshot)
```

Then construct `SessionDataSnapshot` and `SpatialWorkspace` from this object.

- [x] **Step 2: Remove the second current-world conversion**

Delete the later `current_world_snapshot(data_resource_catalog.snapshot)` construction in the same
function. Preserve dependency digest assignment and all error handling around the one conversion.

- [x] **Step 3: Make `SpatialWorkspace` reuse an already-admitted catalog**

When `SpatialWorkspace` receives a `DataResourceCatalog`, retain it directly after validating its
current-world policy. Do not make another new `DataResourceCatalog` wrapper or repeat admission
verdict calculation. Raw non-catalog inputs remain rejected by the existing normalized-input contract.

- [x] **Step 4: Run focused functional tests**

Run:

```text
python -m pytest tests/test_jintian_data_e2e_acceptance.py -q --durations=10
python -m pytest tests/test_data_admission_mvp.py tests/test_jintian_topology_policy.py -q
```

Expected: all tests pass; the complete context build is materially faster; catalog and geometry
digests are unchanged.

- [x] **Step 5: Avoid redundant Pydantic copies during multi-catalog merge**

Representations and capabilities are reused when their qualified ref, resource ref, and content
digest do not change; `model_copy()` is used only when merge rebinding actually changes a field.
This keeps merged snapshot lineage intact while reducing repeated validation work for large
capability indexes.

## Task 3: Add explicit performance observability

**Files:**
- Modify: `backend/app/infrastructure/context_runtime/manager.py`
- Modify: `backend/app/infrastructure/cognition_runtime/world_model_store.py`
- Modify: `docs/design/DATA_PRODUCTION_RUNBOOK.md`
- Test: `tests/test_jintian_data_e2e_acceptance.py`

**Interfaces:**
- Consumes: existing `perf_counter()` timing points.
- Produces: stable stage timings for canonicalization, manifest creation, WM projection, CAS persistence,
  and Evidence retrieval without changing source digests.

- [x] **Step 1: Add bounded stage timing fields to debug/info logs**

Record only elapsed milliseconds and counts; do not log raw geometry, attributes, credentials, or full
provider responses.

- [ ] **Step 2: Add a timing acceptance threshold for local regression**

Use a generous machine-dependent threshold for correctness CI and store the observed benchmark in the
runbook; do not make a hard real-time assertion that would fail on slower CI hosts.

- [x] **Step 3: Verify timing instrumentation does not affect digest output**

Run the complete Jintian acceptance and compare the catalog digest, boundary digest, WM digest, and
Evidence source references before and after the instrumentation.

- [x] **Step 4: Reduce deterministic WM TriG serialization overhead**

The WM CAS representation now uses a bounded direct TriG writer: named graphs are grouped, full N3
terms are sorted, and literal lexical forms are retained. This removes RDFLib's subject-ordering
bookkeeping while keeping RDFLib TriG parsing on restore. WM v0 reload and the complete Jintian
acceptance verify graph/digest and consumer compatibility.

- [x] **Step 5: Avoid repeated deterministic provider capability failures**

The AMap acceptance harness records the first non-retryable capability rejection for an operation and
skips later requests of that operation within the same run. Skips remain auditable
`missing_capability` rows and do not affect formal DATA admission or provider coverage semantics.

- [x] **Step 6: Remove remaining hot-path duplication without changing authority**

CAS publication now reuses the JSON-safe payload for canonical bytes and semantic digest; the WM
road retry index is lazy; and source-catalog line identity uses precomputed semantic tokens plus an
endpoint candidate grid before the original exact distance check. These changes preserve all DATA,
WM and Evidence identities and keep CPU behavior authoritative.

The WM serializer uses length-prefixed digest rows instead of per-quad JSON encoding, while CAS
publication reuses one JSON-safe payload for canonical bytes and semantic digest calculation. The WM digest algorithm is explicitly
versioned as `sha256-sorted-rdflib-n3-quads-v2-length-prefixed`; old snapshots are rebuilt rather than
silently mixed with the new digest contract. Focused Jintian observation improved from about 17.5 s
to 15.9 s on the same Windows workspace; this is a diagnostic observation, not a CI timing gate.

Repeated WM construction for an identical immutable catalog now uses a two-entry process-local LRU
projection cache keyed by catalog digest, schema-mapping fingerprint, and split/single graph mode.
The cache stores only RDF source/world triples and replays them into the caller's graphs; it never
stores raw geometry or becomes a DATA/Evidence authority. A dedicated WM v0 test compares both graph
triple sets between a full projection and a cache replay.

## Task 4: Benchmark the optional CUDA boundary

**Files:**
- Create: `backend/app/data/acceleration/__init__.py`
- Create: `backend/app/data/acceleration/ports.py`
- Create: `backend/app/data/acceleration/cpu.py`
- Create: `backend/app/data/acceleration/cuda.py`
- Modify: `docs/design/DATA_EXECUTABLE_DESIGN.md`
- Modify: `docs/design/DATA_PRODUCTION_RUNBOOK.md`
- Test: `tests/test_data_acceleration.py`

**Interfaces:**
- Consumes: admitted, normalized CPU geometry or numeric raster batches with explicit CRS.
- Produces: optional batch predicate/distance/raster results plus an execution trace. It never produces
  a `DataAdmissionReceipt`, geometry identity, topology repair, or authoritative catalog mutation.

- [ ] **Step 1: Define the CPU reference port**

Use a protocol with operations such as:

```python
class SpatialBatchAccelerator(Protocol):
    def point_in_polygon(self, points: Sequence[tuple[float, float]], polygons: Sequence[Any]) -> BatchResult: ...
    def point_to_linestring_distance(self, points: Sequence[tuple[float, float]], lines: Sequence[Any]) -> BatchResult: ...
```

The CPU implementation uses existing Shapely semantics and returns deterministic host results.

- [ ] **Step 2: Add CUDA capability detection without a mandatory dependency**

The CUDA implementation must import cuSpatial/CuPy lazily. Missing packages, no device, insufficient
memory, unsupported geometry family, or runtime errors return an unavailable result so the caller can
use the CPU reference implementation.

- [ ] **Step 3: Add CPU/GPU equivalence tests**

For normalized WGS84 point/polygon and point/line batches, compare feature-index results and distances
within an explicit tolerance. Ensure source/catalog/geometry digests are identical and no input object
is mutated.

- [ ] **Step 4: Do not wire CUDA into the current Jintian admission path yet**

The current 1,662-feature P0 acceptance must continue to use CPU. Enable CUDA only after a benchmark
shows that host/device transfer and setup are lower than the CPU operation cost for the target batch.

## Task 5: Full verification and documentation alignment

**Files:**
- Modify: `docs/design/DATA_EXECUTABLE_DESIGN.md`
- Modify: `docs/design/DATA_PRODUCTION_RUNBOOK.md`
- Test: `tests/test_jintian_data_e2e_acceptance.py`

**Interfaces:**
- Consumes: the optimized single-canonicalization bootstrap and optional accelerator contract.
- Produces: documented evidence that WM and Evidence consume the same immutable DATA products.

- [x] **Step 1: Run the complete local gate**

```text
python -m pytest tests -q
python -m compileall -q backend scripts tests
python scripts/acceptance/data_production_acceptance.py --root .
git diff --check
```

- [x] **Step 2: Verify the real Jintian chain**

Verify upload/admission, normalized boundary, provider plan, cache/snapshot, context bootstrap, WM,
Evidence, read-only geometry, replay, stale parent, and invalidation using the existing acceptance.

- [x] **Step 3: Record the measured result and current CUDA status**

Document the before/after timing, GPU availability, optional package availability, and the exact
operation threshold that would justify enabling CUDA in a deployment.
