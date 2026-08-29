# AMap Maximal Public-API Collection Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AMap administrative and L1 collectors maximally complete within documented public API limits while preserving full raw responses, distinguishing failure from empty/capability-missing states, and keeping Data/Evidence/GROUND boundaries intact.

**Architecture:** Use the Jintian-specific collector as the canonical AMap request planner and route the unified three-provider command through it. Each request is identified by provider, stage, endpoint, and sanitized parameters; successful raw responses are reusable, failed requests are retried and remain retryable, and normalized candidate projections never replace the immutable raw response. AMap response coordinates remain GCJ-02 in the source snapshot and are converted exactly once to WGS84 for local spatial checks.

**Tech Stack:** Python 3, requests, Shapely, pytest, existing coordinate conversion utilities, JSON/JSONL cache artifacts.

## Global Constraints

- The administrative stage uses only known administrative input and local boundary/bundle geometry; it must not consume L1 names.
- The L1 stage uses an immutable L1 snapshot and keeps its cache separate from the administrative stage.
- AMap POI 2.0 has a 25-record page limit and a 200-record same-query limit; queries reaching that limit must be split by type or space and marked partial until split coverage is complete.
- Raw API responses, including successful empty responses and provider errors, are always retained under the request cache; normalized and retained candidate files are derived indexes.
- Use `success_nonempty`, `success_empty`, `missing_capability`, `not_attempted`, and `failed` as distinct states.
- Retry transient transport, HTTP, and provider errors with bounded attempts; a cached failed response must not prevent a later retry.
- AMap requests and response points use GCJ-02; local boundary/bundle checks use WGS84; preserve both forms and convert once.
- Polygon and Around results are filtered deterministically by Meizhou administrative scope and local geometry before Evidence receives candidates.
- POI detail requests use at most 10 IDs and the documented `|` separator; routes and reverse-geocode results remain observations, not complete road or water geometries.
- Do not scrape unpublished vector tiles or infer arbitrary basemap-label enumeration from public POI APIs.

---

### Task 1: Unify AMap collection entry points

**Files:**
- Modify: `scripts/collect_three_provider_validation.py:565-590`
- Modify: `scripts/collect_amap_jintian_validation.py:540-680`
- Test: `tests/test_three_provider_validation.py`

**Interfaces:**
- Consumes: the existing unified provider/stage CLI and Jintian AMap collector.
- Produces: one canonical AMap request planner while preserving the existing `--provider amap --stage admin|l1|all` command.

- [ ] **Step 1: Add a test proving the unified AMap route selects the canonical collector.**

```python
def test_unified_amap_route_uses_canonical_collector(monkeypatch, tmp_path):
    called = {}

    class FakeCollector:
        def __init__(self, *args, **kwargs):
            called["created"] = True

        def collect(self, stage):
            called["stage"] = stage
            return tmp_path / "manifest.json"

    monkeypatch.setattr("scripts.collect_amap_jintian_validation.AmapJintianCollector", FakeCollector)
    result = run("amap", "01_admin_scope", False, 0)
    assert called == {"created": True, "stage": "01_admin_scope"}
    assert result == tmp_path / "manifest.json"
```

- [ ] **Step 2: Run the focused test and observe the old path failure.**

Run: `python -m pytest tests/test_three_provider_validation.py::test_unified_amap_route_uses_canonical_collector -q`

Expected: FAIL because the unified runner currently constructs the older `ValidationCollector` path for AMap.

- [ ] **Step 3: Add a canonical collector facade without duplicating provider logic.**

Expose an `AmapJintianCollector` facade in `collect_amap_jintian_validation.py` with `collect(stage)` dispatching to the hardened administrative or L1 stage. Update the unified runner to import this facade only for `provider == "amap"`; leave Tianditu and Tencent routing unchanged.

- [ ] **Step 4: Run the focused test and the existing provider tests.**

Run: `python -m pytest tests/test_three_provider_validation.py -q`

Expected: PASS, with the unified AMap entry point selecting the canonical collector.

### Task 2: Implement retry-safe five-state request envelopes

**Files:**
- Modify: `scripts/collect_amap_jintian_validation.py:563-655`
- Test: `tests/test_collect_amap_jintian_validation.py`

**Interfaces:**
- Consumes: sanitized request key, existing cache pointers, AMap HTTP/JSON responses.
- Produces: retry history, stable cache envelopes, and explicit request status.

- [ ] **Step 1: Add tests for transient retry, cached failure retry, and empty-vs-missing classification.**

```python
def test_transient_http_error_is_retried_then_success(monkeypatch, tmp_path):
    responses = [FakeResponse(503, {"status": "0", "infocode": "10001"}), FakeResponse(200, {"status": "1", "pois": []})]
    collector = StageCollector("test", refresh=False, min_interval=0, root=tmp_path, max_retries=2)
    monkeypatch.setattr(collector.session, "get", lambda *args, **kwargs: responses.pop(0))
    data, event = collector.request("poi", "https://example.test", {"keywords": "村"}, "poi")
    assert event["status"] == "success_empty"
    assert event["retry_count"] == 1


def test_cached_failed_request_is_retryable(monkeypatch, tmp_path):
    collector = StageCollector("test", refresh=False, min_interval=0, root=tmp_path, max_retries=1)
    write_failed_cache_envelope(collector, "https://example.test", {"keywords": "村"})
    monkeypatch.setattr(collector.session, "get", lambda *args, **kwargs: FakeResponse(200, {"status": "1", "pois": [{"id": "p1"}]}))
    _, event = collector.request("poi", "https://example.test", {"keywords": "村"}, "poi")
    assert event["cache_hit"] is False
    assert event["status"] == "success_nonempty"


def test_missing_capability_is_not_success_empty():
    assert classify_status(attempted=False, capability_available=False, payload={}) == "missing_capability"
    assert classify_status(attempted=True, capability_available=True, payload={"status": "1", "pois": []}) == "success_empty"
```

- [ ] **Step 2: Run the tests to establish the missing status/retry behavior.**

Run: `python -m pytest tests/test_collect_amap_jintian_validation.py -q`

Expected: FAIL because the current collector performs one request, reuses cached failures, and exposes only a boolean success flag.

- [ ] **Step 3: Implement bounded retries and retry history.**

Add configurable `max_retries=4`, transient HTTP/provider error classification, exponential backoff bounded to eight seconds, and an `attempts` list in the cache envelope. Do not retry known permanent parameter/credential errors. Store each attempt in `attempts.jsonl` and store the final envelope in the raw response file.

- [ ] **Step 4: Implement explicit status classification.**

Classify a valid successful response with records as `success_nonempty`, a valid successful response with a known empty collection as `success_empty`, unsupported/not-applicable planned capability as `missing_capability`, an intentionally skipped request as `not_attempted`, and all attempted unsuccessful requests as `failed`. Preserve `http_status`, provider status, infocode, info, record count, retry count, and error text.

- [ ] **Step 5: Make cache reuse status-aware.**

Reuse successful envelopes without a live request. Never treat a cached `failed` envelope as final; retry it on the next run unless `--refresh` is false and the failure is explicitly marked permanent. Keep `success_empty` reusable and never reinterpret it as entity absence.

- [ ] **Step 6: Run focused tests.**

Run: `python -m pytest tests/test_collect_amap_jintian_validation.py -q`

Expected: PASS with explicit five-state events and retry metadata.

### Task 3: Add fine-grained type and spatial sharding

**Files:**
- Modify: `scripts/collect_amap_jintian_validation.py:70-90, 669-778, 940-1005`
- Test: `tests/test_collect_amap_jintian_validation.py`

**Interfaces:**
- Consumes: local WGS84 boundary, expanded boundary, type-code catalog, AMap Polygon/Around limits.
- Produces: deterministic query plans that split broad categories by type and split saturated areas into spatial cells.

- [ ] **Step 1: Add tests for eight-page cap and saturation planning.**

```python
def test_amap_page_plan_never_exceeds_documented_two_hundred_record_cap():
    assert max_pages_for_page_size(25) == 8


def test_saturated_polygon_is_split_into_child_cells():
    plan = split_saturated_scope(box(116.0, 24.8, 116.1, 24.9), max_records=200)
    assert len(plan) > 1
    assert all(cell.intersects(box(116.0, 24.8, 116.1, 24.9)) for cell in plan)


def test_around_requests_include_strict_city_scope():
    params = around_params("116.04,24.82", 3000, "141200")
    assert params["region"] == "441400"
    assert params["city_limit"] == "true"
```

- [ ] **Step 2: Run the tests and confirm the old broad-plan behavior.**

Run: `python -m pytest tests/test_collect_amap_jintian_validation.py -q`

Expected: FAIL for the new sharding and strict Around parameter assertions.

- [ ] **Step 3: Replace four broad type shards with a type-plan generator.**

Represent each query as a named type shard. Start with each top-level AMap type code separately; when a response reaches 200 records, expand that type using the checked-in detailed type-code catalog. Preserve the exact type string in the request plan and manifest.

- [ ] **Step 4: Add spatial cell splitting for saturated Polygon and Around tasks.**

For Polygon tasks, split the local and expanded WGS84 envelopes into deterministic overlapping cells, convert each cell to GCJ-02 for AMap, query each cell, and use local WGS84 filtering for final scope. For Around tasks, use a deterministic grid of centers covering the project/expanded extent rather than relying on one administrative center. Stop splitting only when the response count is below 200 or the finest configured type/space unit has been reached; mark the latter `partial_provider_cap`.

- [ ] **Step 5: Add strict city parameters and local scope classification.**

Use `region=441400&city_limit=true` on text and Around queries, and on Polygon queries where supported. Keep `outside_meizhou` records in raw/normalized-all output, but exclude them from retained candidates. Preserve `meizhou_other` records as explicit same-city exclusion evidence.

- [ ] **Step 6: Run plan-only validation.**

Run: `python scripts/collect_amap_jintian_validation.py --stage admin --expand-admin --min-interval 0 --plan-only`

Expected: the plan lists type and spatial shards, reports expected request counts and cache keys, and performs no network request.

### Task 4: Preserve complete Data-layer fields and repair coordinate/detail contracts

**Files:**
- Modify: `backend/app/data/ingestion/providers/amap/provider.py:447-486`
- Modify: `backend/app/data/catalog/external_anchors.py:453-490`
- Modify: `scripts/collect_amap_jintian_validation.py:780-813`
- Test: `tests/test_collect_amap_jintian_validation.py`
- Test: `tests/test_amap_provider.py`

**Interfaces:**
- Consumes: full AMap POI, detail, and reverse-geocode responses.
- Produces: raw-compatible Data records preserving optional fields, one-time coordinate normalization, and valid detail requests.

- [ ] **Step 1: Add tests for reverse-geocode field preservation and detail ID syntax.**

```python
def test_reverse_geocode_normalization_keeps_all_documented_collections():
    normalized = normalize_regeo_payload({"regeocode": {"roads": [{"name": "Y122"}], "roadinters": [{"first_name": "Y122"}], "pois": [{"id": "p1"}], "aois": [{"name": "金田村"}], "addressComponent": {}}})
    assert normalized["roads"][0]["name"] == "Y122"
    assert normalized["roadinters"][0]["first_name"] == "Y122"
    assert normalized["pois"][0]["id"] == "p1"
    assert normalized["aois"][0]["name"] == "金田村"


def test_detail_request_uses_pipe_separated_batches_of_ten():
    batches = detail_request_batches([str(i) for i in range(11)])
    assert batches[0]["id"] == "0|1|2|3|4|5|6|7|8|9"
    assert batches[1]["id"] == "10"
```

- [ ] **Step 2: Implement full reverse-geocode parsing in the production Data provider.**

Request `extensions=all`, `roadlevel=0`, and the configured radius. Return the existing address fields plus `roads`, `roadinters`, `pois`, `aois`, `neighborhood`, `building`, and the raw provider payload reference. Keep the public result backward-compatible by adding fields rather than removing existing keys.

- [ ] **Step 3: Fix the production POI coordinate contract.**

When `_parse_pois()` has already derived WGS84 from AMap GCJ-02, mark the external feature coordinate as WGS84 and preserve the original `lon_gcj02`/`lat_gcj02` in provenance. Ensure Stage 2 does not perform a second GCJ-02 conversion.

- [ ] **Step 4: Fix POI detail batching.**

Use batches of at most ten IDs and join IDs with `|`. Keep detail requests behind cache and scope/quality filtering. Record `detail_coverage` as `top_k` or `all_scoped_ids` rather than implying universal POI detail coverage.

- [ ] **Step 5: Run provider and collector tests.**

Run: `python -m pytest tests/test_amap_provider.py tests/test_collect_amap_jintian_validation.py -q`

Expected: PASS, with preserved reverse-geocode fields, one-time coordinate conversion, and documented detail syntax.

### Task 5: Produce complete raw/normalized/retained coverage accounting

**Files:**
- Modify: `scripts/collect_amap_jintian_validation.py:640-665, 1030-1170`
- Modify: `docs/design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md:817-1072`
- Test: `tests/test_collect_amap_jintian_validation.py`

**Interfaces:**
- Consumes: request envelopes, normalized records, scope classifier, L1 provenance.
- Produces: auditable coverage status and design-aligned Data/Evidence artifacts.

- [ ] **Step 1: Add tests for manifest coverage accounting.**

```python
def test_manifest_distinguishes_empty_missing_failed_and_partial_queries():
    manifest = build_manifest([
        {"status": "success_nonempty"},
        {"status": "success_empty"},
        {"status": "missing_capability"},
        {"status": "not_attempted"},
        {"status": "failed"},
    ])
    assert manifest["status_counts"] == {
        "success_nonempty": 1,
        "success_empty": 1,
        "missing_capability": 1,
        "not_attempted": 1,
        "failed": 1,
    }
```

- [ ] **Step 2: Write `normalized_all.jsonl` from every successful response.**

Retain out-of-scope records with `scope_bucket` and `scope_reasons`; do not silently delete them. Preserve raw response references, endpoint, sanitized parameters, query-plan digest, coordinate contract, and geometry semantics.

- [ ] **Step 3: Write Evidence-ready retained and rejected projections.**

Use deterministic scope blocking and quality scoring before writing `retained_candidates.jsonl`. Keep `rejected_candidates.jsonl` with explicit rejection reasons such as `outside_meizhou`, `same_city_wrong_county`, `parent_only_match`, `generic_name`, `duplicate_poi_id`, or `provider_cap_unresolved`.

- [ ] **Step 4: Add coverage fields to manifests.**

Record `status_counts`, `truncated_queries`, `partial_queries`, `type_shard_count`, `spatial_shard_count`, `raw_response_count`, `normalized_record_count`, `retained_candidate_count`, `rejected_record_count`, `detail_request_count`, `detail_coverage`, and `coordinate_contract`.

- [ ] **Step 5: Align design terminology with the implementation.**

Update the target design so `success_empty`, `missing_capability`, and `not_attempted` remain distinct in sections 19, 20, and 21.6. State that “maximal public-API collection” means complete coverage under documented provider limits, not basemap-label enumeration or unrestricted POI completeness.

- [ ] **Step 6: Run all relevant tests.**

Run: `python -m pytest tests/test_collect_amap_jintian_validation.py tests/test_three_provider_validation.py tests/test_amap_provider.py -q`

Expected: PASS.

### Task 6: Reuse existing cache and validate the completed plan without unnecessary quota use

**Files:**
- Modify: generated artifacts under `output/amap_validation/` and `output/map_validation/amap/` only.

- [ ] **Step 1: Build a cache-gap report before live collection.**

Run the canonical planner with `--plan-only` and compare sanitized request keys with existing AMap caches. Mark identical successful and successful-empty requests reusable; mark failed requests retryable; list only new type/spatial/detail requests as gaps.

- [ ] **Step 2: Run the administrative stage with cache reuse.**

Run: `python scripts/collect_amap_jintian_validation.py --stage admin --expand-admin --min-interval 0.35`

Expected: existing successful responses are not requested again; missing plan keys are executed; transient failures receive bounded retries; no L1 names appear in the administrative request log.

- [ ] **Step 3: Run the L1 stage with cache reuse.**

Run: `python scripts/collect_amap_jintian_validation.py --stage l1 --min-interval 0.35`

Expected: the L1 snapshot digest and name provenance are recorded; only new name/type/space/detail gaps are requested.

- [ ] **Step 4: Verify final artifacts and coordinate safety.**

Check that every executed request has a raw response reference, every failed request has attempt history, every successful empty request is not labeled missing, every retained candidate has a scope bucket, every AMap point has both GCJ-02 and WGS84 forms, and no production path applies GCJ-02 to an already converted coordinate.

- [ ] **Step 5: Report provider-limit gaps explicitly.**

Summarize queries that remain `partial_provider_cap`, `partial_requires_spatial_sharding`, `missing_capability`, or `not_attempted`. Do not call the run complete when any required plan shard remains unresolved.

