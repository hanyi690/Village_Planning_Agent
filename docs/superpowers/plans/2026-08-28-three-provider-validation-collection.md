# Three Provider Validation Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect auditable first-stage administrative baselines and second-stage L1-name evidence from AMap, Tianditu, and Tencent using each provider's documented capabilities, shared scope/coordinate rules, durable raw caching, and explicit failure-versus-missing semantics.

**Architecture:** Add a standalone validation collector that uses the repository's existing provider URLs, credential names, coordinate utilities, WFS layers, and L1 snapshot chain without changing production world-model behavior. Each provider/stage has an independent cache and raw-response store; normalized records are classified into administrative scope buckets and downstream candidates. A request is `failed` only when an attempted operation did not complete successfully; a successful empty result or provider capability gap is `missing`, never `failed`.

**Tech Stack:** Python 3, requests, Shapely, pyproj, existing provider coordinate/config conventions, JSON/JSONL artifacts, pytest.

## Global Constraints

- Use only official provider APIs and documented parameters; do not scrape private vector tiles or undocumented endpoints.
- Preserve full raw responses for every attempted request, including terminal errors, while only successful responses are reusable as cache hits by default.
- Retry network timeouts, connection errors, HTTP 429/5xx, and provider transient errors with bounded exponential backoff; do not endlessly retry credential, permission, malformed-parameter, or successful-empty responses.
- Distinguish `failed`, `missing`, and `success_nonempty` in request events and normalized records.
- Administrative hard scope is梅州市 (`441400`/city text); retain lower-priority county/town/project buckets and reject outside-city business candidates.
- AMap request/response points use GCJ-02 and must be converted once to WGS84 for local geometry tests. Tencent requests use its documented lat/lng ordering and explicit `coord_type=wgs84` where supported. Tianditu search/WFS geometry follows its documented lon/lat / CGCS2000-WGS84-compatible contract and must retain CRS metadata.
- Keep AMap, Tianditu, and Tencent caches separate, and keep administrative baseline and L1-name stages separate.

---

### Task 1: Freeze official capability matrix and provider contracts

**Files:**
- Create: `docs/design/three-provider-external-evidence-capability-matrix.md`
- Modify: `backend/app/data/ingestion/providers/tencent/README.md`
- Modify: `backend/app/data/ingestion/providers/tianditu/README.md`

- [ ] **Step 1: Record official API capabilities and parameters.**

Document AMap POI text/around/polygon/detail, inputtips, geocode/regeo, route; Tianditu V2 search query types 1/7/10/12/13/14, geocoder, administrative, route, WFS; Tencent region/nearby/rectangle search, suggestion, geocoder/regeocoder, route, and coordinate ordering.

- [ ] **Step 2: Define provider-specific missing capability states.**

For example, Tianditu's documented V2 search does not imply arbitrary basemap-label enumeration; Tencent's existing provider has no generic polygon POI endpoint in the current WebService surface, so rectangle plus tiled nearby/region searches are the supported substitute. Record this as `capability_missing`, not a failed API request.

### Task 2: Implement shared durable cache and retry state machine

**Files:**
- Create: `scripts/collect_three_provider_validation.py`
- Test: `tests/test_three_provider_validation.py`

**Interfaces:**
- Produces `request_event.status` in `{success_nonempty, success_empty, missing, failed}` and `retry_count`.
- `CacheStore.load()` returns only reusable successful envelopes by default; failed envelopes remain auditable but do not block retry.

- [ ] **Step 1: Test failure/missing distinction.**

```python
def test_successful_empty_is_missing_not_failed():
    event = classify_response(provider="tencent", attempted=True, http_status=200, payload={"status": 0, "data": [], "count": 0})
    assert event["status"] == "missing"
    assert event["failure"] is None


def test_transport_error_is_failed_and_retryable():
    event = classify_response(provider="amap", attempted=True, http_status=None, payload={}, error="Timeout")
    assert event["status"] == "failed"
    assert event["retryable"] is True
```

- [ ] **Step 2: Implement sanitized request keys and response envelopes.**

Exclude API secrets from keys and stored parameters. Store `provider`, `stage`, `operation`, endpoint, sanitized parameters, attempt history, status, error class, raw response reference, and coordinate contract.

- [ ] **Step 3: Implement bounded retry.**

Retry transport errors, timeouts, 429, 500–599, and provider-declared transient codes. Preserve every attempt in `attempts.jsonl`; only the final envelope is the request's canonical raw response. A successful empty response is cached as `success_empty`/`missing` and is not retried.

### Task 3: Implement shared coordinate and scope normalization

**Files:**
- Modify: `scripts/collect_three_provider_validation.py`
- Test: `tests/test_three_provider_validation.py`

- [ ] **Step 1: Test coordinate contracts.**

```python
def test_amap_is_converted_once_for_local_spatial_checks():
    row = normalize_point("amap", {"location": "116.044146,24.818629"})
    assert row["location_crs"] == "GCJ-02"
    assert row["location_wgs84"] != row["location_gcj02"]


def test_tencent_lat_lng_is_normalized_to_lon_lat():
    row = normalize_point("tencent", {"location": {"lat": 24.818629, "lng": 116.044146}})
    assert row["location_wgs84"] == [116.044146, 24.818629]
```

- [ ] **Step 2: Implement provider-specific extraction.**

Preserve raw coordinates and CRS. Normalize Tencent's `{lat,lng}` and `coord_type=wgs84`; normalize Tianditu `lonlat` and WFS GeoJSON with explicit CRS metadata; normalize AMap GCJ-02 and convert to WGS84 once.

- [ ] **Step 3: Implement six scope buckets.**

Use city/county/town fields and codes plus the local WGS84 boundary: `project_local`, `township_local`, `county_local`, `meizhou_other`, `outside_meizhou`, `unknown_scope`. Outside-Meizhou records remain in raw/normalized audit output but never enter local candidates.

### Task 4: Implement provider-specific first-stage administrative collection

**Files:**
- Modify: `scripts/collect_three_provider_validation.py`

- [ ] **Step 1: Collect AMap administrative baseline.**

Reuse the existing AMap cache and collect geocode, district tree, project/expanded Polygon, 3km/10km Around shards, boundary/interior/road/water regeo probes, limited routes, and Top-K POI detail.

- [ ] **Step 2: Collect Tianditu administrative baseline.**

Use V2 administrative search and V2 search query types 12, 1, 7, 10, 13, and 14 with `specify` and `mapBound`/polygon where documented. Use geocoder/reverse geocoder, administrative boundaries, WFS `HYDA`, `HYDL`, `LRDL`, `RESA`, and `RESP` within the project and expanded BBox. Record WFS `MAXFEATURES` and truncation explicitly.

- [ ] **Step 3: Collect Tencent administrative baseline.**

Use region search for梅州市/平远县/泗水镇, rectangle searches over tiled local/expanded BBoxes, nearby searches over 1km tiles because the documented nearby radius is limited, suggestion queries, geocoder/regeocoder probes, and limited driving/walking/bicycling routes. Use `coord_type=wgs84` where supported and retain Tencent's `lat,lng` request convention.

- [ ] **Step 4: Add official capability records.**

For each provider operation not supported by its public API, write a `missing` capability record with `attempted=false`, documentation reference, and `reason=unsupported_public_operation`; do not manufacture an HTTP failure.

### Task 5: Implement second-stage L1 collection for all three providers

**Files:**
- Modify: `scripts/collect_three_provider_validation.py`

- [ ] **Step 1: Load the latest immutable L1 snapshot.**

Record the L1 ref, descriptor digest, blob digest, 35 mention count, place-like name list, excluded concepts, and source provenance.

- [ ] **Step 2: Use small-to-large query cascades.**

For each name, query project-local structured forms first, then township/county, then Meizhou. Use provider-specific type filters and local geometry before broad generic text searches. Do not let a broad nonempty result prevent a stricter local query.

- [ ] **Step 3: Normalize and classify every result.**

Retain full raw responses and normalized-all records. Mark successful empty results as `missing`, provider capability gaps as `missing`, and only transport/provider execution failures as `failed`.

- [ ] **Step 4: Emit Evidence-ready Top-K packets.**

Supply only scope-filtered candidates plus provenance, rejected summaries, truncation, coordinate contract, and failure/missing status. Evidence may rank/abstain; it may not override hard city scope or invent geometry.

### Task 6: Add output validation and no-repeat tests

**Files:**
- Test: `tests/test_three_provider_validation.py`
- Modify: `docs/design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md`

- [ ] **Step 1: Test output separation.**

Assert that each provider/stage has independent `cache`, `raw_responses`, `attempts`, `normalized_all`, `retained_candidates`, and `rejected_candidates` directories.

- [ ] **Step 2: Test retries do not duplicate successful calls.**

Assert that successful cached requests are not repeated, while failed transport requests are retried on a subsequent run without `--refresh`.

- [ ] **Step 3: Update the target design.**

Document the three-provider source-evidence contract, capability-missing semantics, failure semantics, coordinate rules, and the Evidence/GROUND closed-candidate boundary.

### Task 7: Run both stages with cache reuse and report gaps

**Files:**
- Create: `output/map_validation/<provider>/<stage>/...`

- [ ] **Step 1: Run administrative baseline for AMap, Tianditu, and Tencent.**

Use cache reuse and bounded retry. Do not use `--refresh` unless a prior failed response needs an explicit retry.

- [ ] **Step 2: Run L1-name collection for all three providers.**

Use the same L1 snapshot and separate provider/stage outputs.

- [ ] **Step 3: Verify every request is classified.**

No attempted request may be absent from the event log; every failure has retry history and every missing result has a missing reason.

- [ ] **Step 4: Summarize successful coverage, missing capabilities, failed requests, truncation, and remaining manual basemap-label gaps.**

