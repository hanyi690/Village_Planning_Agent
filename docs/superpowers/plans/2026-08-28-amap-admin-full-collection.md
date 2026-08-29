# AMap Administrative Full Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the first-stage AMap validation collector so it reuses cached responses, collects the supported administrative, polygon, around, sampling, routing, type-sharded, and POI-detail evidence, and emits coordinate-safe scope-filtered candidates without treating AMap as a basemap-label enumerator.

**Architecture:** Keep the collector as an independent validation tool outside production Data/KG/GROUND. Store every executed request and full raw response in the stage cache, then derive normalized records with GCJ-02/WGS84 coordinates, Meizhou administrative buckets, deterministic quality scores, and Top-K retained candidates. Use the existing local WGS84 boundary only after converting AMap response coordinates back to WGS84; convert the boundary to GCJ-02 only for AMap polygon requests.

**Tech Stack:** Python 3, requests, Shapely, existing `app.spatial.model.coord_transform`, JSON/JSONL artifacts, pytest-style unit tests.

## Global Constraints

- The first stage must use only known administrative scope and derived local GIS geometry; it must not use L1 names.
- The second stage must remain a separate cache and must not be silently rewritten as an administrative baseline.
- Every request with identical endpoint and sanitized parameters must reuse its cached raw response unless `--refresh` is explicitly passed.
- Full raw API responses are retained; only filtered Top-K candidates are supplied to downstream Evidence.
- Hard reject `outside_meizhou`; retain lower-priority `township_local`, `county_local`, and `meizhou_other` records with explicit buckets.
- AMap request coordinates are GCJ-02; local boundary and bundle coordinates are WGS84/CRS84. Preserve both coordinate forms and perform spatial tests in WGS84.
- Do not scrape unpublished vector tiles or claim that public POI APIs enumerate arbitrary basemap labels.
- Do not modify production Data, KG, Evidence, or GROUND behavior in this validation task.

---

### Task 1: Add coordinate and administrative scope primitives

**Files:**
- Modify: `scripts/collect_amap_jintian_validation.py`
- Test: `tests/test_collect_amap_jintian_validation.py`

**Interfaces:**
- Consumes: AMap records, existing WGS84 `boundary.geojson`, district-tree responses.
- Produces: `CoordinatePair`, boundary context with both CRS forms, administrative descendant index, and deterministic `scope_bucket` classification.

- [ ] **Step 1: Write tests for coordinate preservation and scope buckets.**

```python
def test_amap_point_keeps_gcj02_and_normalizes_to_wgs84():
    record = {"location": "116.044146,24.818629"}
    normalized = normalize_amap_location(record)
    assert normalized["location_gcj02"] == [116.044146, 24.818629]
    assert normalized["location_wgs84"] != normalized["location_gcj02"]


def test_scope_bucket_rejects_outside_meizhou_and_keeps_project_extensions():
    scope = make_scope_classifier(project_boundary=box(116.03, 24.80, 116.06, 24.84))
    assert scope.classify({"cityname": "河源市", "location_wgs84": [114.7, 23.7]})["bucket"] == "outside_meizhou"
    assert scope.classify({"cityname": "梅州市", "districtname": "平远县", "townname": "泗水镇", "location_wgs84": [116.07, 24.85]})["bucket"] == "township_local"
    assert scope.classify({"cityname": "梅州市", "districtname": "平远县", "townname": "泗水镇", "location_wgs84": [116.04, 24.82]})["bucket"] == "project_local"
```

- [ ] **Step 2: Run the focused tests and confirm they fail before implementation.**

Run: `python -m pytest tests/test_collect_amap_jintian_validation.py -q`

Expected: FAIL because the coordinate normalizer and scope classifier do not yet exist.

- [ ] **Step 3: Implement coordinate normalization and scope classification.**

Add functions that preserve `location_gcj02`, compute `location_wgs84` through `gcj02_to_wgs84`, and classify records into `project_local`, `township_local`, `county_local`, `meizhou_other`, `outside_meizhou`, or `unknown_scope`. Use city name/code and the administrative descendant tree; use `towncode` or normalized town text for 泗水镇 because town records may inherit county adcodes.

- [ ] **Step 4: Run the focused tests and verify they pass.**

Run: `python -m pytest tests/test_collect_amap_jintian_validation.py -q`

Expected: PASS.

### Task 2: Make the boundary context suitable for Polygon and sampling requests

**Files:**
- Modify: `scripts/collect_amap_jintian_validation.py`
- Test: `tests/test_collect_amap_jintian_validation.py`

**Interfaces:**
- Consumes: WGS84/CRS84 `data/gis/jintian/current/boundary.geojson`.
- Produces: simplified WGS84 polygon, GCJ-02 request polygon, expanded polygon, boundary vertices, interior grid, and WGS84 sample points.

- [ ] **Step 1: Test polygon input conversion and WGS84 output checks.**

```python
def test_polygon_request_is_gcj02_but_boundary_checks_are_wgs84():
    context = load_admin_boundary_context()
    assert context["source_crs"] == "CRS84/WGS84"
    assert context["request_crs"] == "GCJ-02"
    assert context["check_crs"] == "WGS84"
    assert context["polygon_strings_gcj02"]
    assert context["sample_points_wgs84"]
```

- [ ] **Step 2: Implement an expanded boundary and deterministic interior sampling grid.**

Keep the true boundary for project-local classification. Create an outward approximate buffer in a meter-based projection for the extended query polygon, then convert its vertices to GCJ-02. Generate boundary vertices and only grid points whose WGS84 points are inside the true boundary or the explicitly named expansion polygon.

- [ ] **Step 3: Run the focused tests.**

Run: `python -m pytest tests/test_collect_amap_jintian_validation.py::test_polygon_request_is_gcj02_but_boundary_checks_are_wgs84 -q`

Expected: PASS.

### Task 3: Expand the first-stage request matrix with cache reuse

**Files:**
- Modify: `scripts/collect_amap_jintian_validation.py`
- Test: `tests/test_collect_amap_jintian_validation.py`

**Interfaces:**
- Consumes: `StageCollector`, admin anchors, boundary context, `PLACE_TYPES`.
- Produces: cached requests for administrative geocoding/tree, local and expanded Polygon, 3km/10km Around, boundary/grid regeo, road/water probe regeo, type-local POI searches, route probes, and post-filter POI detail calls.

- [ ] **Step 1: Test request-key stability and detail batching.**

```python
def test_identical_sanitized_requests_reuse_one_cache_key(tmp_path):
    collector = StageCollector("test", refresh=False, min_interval=0, root=tmp_path)
    assert collector.request_key("https://example.test", {"key": "secret", "a": "1"}) == collector.request_key("https://example.test", {"a": "1"})


def test_detail_batches_at_most_ten_ids():
    assert list(chunk_ids([str(i) for i in range(21)], 10)) == [
        [str(i) for i in range(10)],
        [str(i) for i in range(10, 20)],
        ["20"],
    ]
```

- [ ] **Step 2: Implement full first-stage request categories.**

Use only administrative inputs and local geometry. Add:

```text
structured geocode: 金田村, 泗水镇
district tree: 梅州市, 平远县, 泗水镇, 金田村/村委会 probe
polygon: true boundary and expanded boundary, type-sharded
around: 3km and 10km, type-sharded
regeo: boundary vertices, interior grid, administrative anchors
regeo: sampled local road and water candidates from bundle when available
local type searches: facilities, public/transport, natural/water, services/recreation
routes: limited driving/walking/bicycling/electrobike anchor checks
detail: accepted/top-ranked POI IDs in batches of 10 with children/business/indoor/navi/photos
```

Use v5 as the primary API. Use v3 only for deliberately labeled compatibility comparisons or failed v5 operations, not as an unbounded duplicate of every result page.

- [ ] **Step 3: Ensure every request writes a full raw response and manifest event.**

Keep `cache/<request_key>.json` as a pointer and `responses/<request_key>.json` as the complete response envelope. Add request category, coordinate CRS, pagination/truncation metadata, and cache-hit status to the event.

- [ ] **Step 4: Run collector dry-run with an empty API key fixture.**

Run: `python scripts/collect_amap_jintian_validation.py --stage admin --expand-admin --min-interval 0`

Expected: no network calls when `AMAP_API_KEY` is absent; failed request records are written without exposing a key.

### Task 4: Normalize, filter, score, and separate raw versus business outputs

**Files:**
- Modify: `scripts/collect_amap_jintian_validation.py`
- Test: `tests/test_collect_amap_jintian_validation.py`

**Interfaces:**
- Consumes: normalized API responses and scope classifier.
- Produces: `normalized_all.jsonl`, `retained_candidates.jsonl`, `rejected_candidates.jsonl`, `scope_summary.json`, and Evidence-ready candidate packets.

- [ ] **Step 1: Test deterministic ranking and parent fallback rejection.**

```python
def test_project_candidate_ranks_above_same_name_meizhou_candidate():
    ranked = rank_candidates([
        {"scope_bucket": "meizhou_other", "name_match": "exact", "type_match": True},
        {"scope_bucket": "project_local", "name_match": "exact", "type_match": True},
    ])
    assert ranked[0]["scope_bucket"] == "project_local"


def test_parent_village_fallback_is_not_direct_name_hit():
    candidate = classify_candidate({"name": "金田村", "query_name": "金田河", "level": "村庄"})
    assert "parent_fallback" in candidate["quality_flags"]
    assert candidate["retained"] is False
```

- [ ] **Step 2: Implement record normalization and scope buckets.**

For POI, tip, and geocode records extract all available names, address components, adcodes, city/district/town text, type codes, IDs, business/navigation/indoor/photos/children fields, raw response references, and both coordinate forms. Do not discard an out-of-scope record from the raw or normalized-all stores.

- [ ] **Step 3: Implement quality scoring and Top-K retention.**

Use hard rejection only for `outside_meizhou`; retain lower scopes with explicit reasons. Rank by project scope, administrative match, exact/normalized name match, L1 role/type compatibility when available, local geometry proximity, and parent-fallback/generic-term penalties. Keep separate Top-K limits for project, township/county, and same-name Meizhou exclusion candidates.

- [ ] **Step 4: Add stage output files and manifest counts.**

The manifest must distinguish:

```text
request_events
unique_cached_responses
raw_response_count
normalized_record_count
retained_candidate_count
rejected_record_count
scope_bucket_counts
truncated_queries
detail_requests
coordinate_contract
```

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest tests/test_collect_amap_jintian_validation.py -q`

Expected: PASS.

### Task 5: Update the target design document with the external-evidence contract

**Files:**
- Modify: `docs/design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md`

**Interfaces:**
- Consumes: implemented collector artifacts and coordinate/scope contracts.
- Produces: documented boundary between Source Data, Evidence, Cognition, and GROUND.

- [ ] **Step 1: Document the two-stage cache contract.**

State that administrative baseline and L1-name probing are independent source-evidence collections; raw responses are immutable audit inputs and filtered candidate packets are derived projections.

- [ ] **Step 2: Document the administrative scope buckets and cascade.**

Specify small-to-large retrieval (`project → township → county → city`) and deterministic hard filtering before Evidence LLM selection.

- [ ] **Step 3: Document the coordinate contract.**

Specify WGS84/CRS84 for local GIS, GCJ-02 for AMap requests/responses, WGS84 for local point-in-polygon and geometry matching, and preservation of both coordinate forms.

- [ ] **Step 4: Document the GROUND closed-set rule.**

External API results may become Evidence source records and candidate references, but GROUND can only select existing WorldEntity/SpatialRepresentation candidates. Any change to world cognition requires a new world-model snapshot before GROUND reruns.

### Task 6: Run cached administrative collection and verify artifacts

**Files:**
- Modify: generated files under `output/amap_validation/01_admin_scope/` only.

- [ ] **Step 1: Run with cache reuse and no refresh.**

Run: `python scripts/collect_amap_jintian_validation.py --stage admin --expand-admin --min-interval 0.35`

Expected: identical requests reuse prior responses; only missing request keys call AMap.

- [ ] **Step 2: Verify no API key appears in event, cache, or raw response files.**

Run: `rg -n "key=|AMAP_API_KEY|[A-Za-z0-9]{32}" output/amap_validation/01_admin_scope`

Expected: no credential value is present.

- [ ] **Step 3: Verify raw, normalized, retained, rejected, and manifest counts.**

Check that every successful request has a raw response reference, every normalized candidate has a coordinate CRS status, every retained candidate has a scope bucket, and every rejected candidate has a reason.

- [ ] **Step 4: Verify the first stage did not consume L1 names.**

Check manifest `input_policy.l1_names_used == false` and ensure the request log contains no L1-derived names.

### Task 7: Regression-check the second-stage cache without requerying

**Files:**
- Modify: generated files under `output/amap_validation/02_l1_place_names/` only if deriving new local projections from existing responses.

- [ ] **Step 1: Confirm the existing L1 raw responses remain readable.**

Use the existing `20260828T085421Z` manifest and request log; do not pass `--refresh`.

- [ ] **Step 2: Derive administrative buckets locally from existing L1 responses.**

Do not reissue identical calls. Produce a separate derived-filter artifact for the L1 stage, preserving the prior run and its raw responses.

- [ ] **Step 3: Report remaining API gaps instead of silently rerunning.**

Only missing Polygon/type/detail requests should be eligible for later explicit supplementation.

