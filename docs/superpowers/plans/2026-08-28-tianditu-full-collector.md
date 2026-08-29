# Tianditu Full Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current Tianditu validation loops with a resumable, auditable collector that exhausts the documented administrative, category, bbox, polygon, place-name, reverse-geocode, route, and discoverable WFS capabilities within documented provider limits.

**Architecture:** Keep the collector as a project-level data acquisition tool, separate from production KG/Evidence/GROUND. Use a provider-specific planner to generate deterministic request jobs, a transport/cache layer to persist every raw response and retryable failure, and a reducer to produce normalized records, scope buckets, coverage checks, and candidate packages. Administrative and polygon constraints are applied by the provider where documented and again locally in WGS84; no provider response is treated as a basemap-label dump.

**Tech Stack:** Python 3, `requests`, `shapely`, existing project boundary/L1 loaders, JSON/JSONL cache artifacts, `pytest` with mocked transport.

## Global Constraints

- Use the official Tianditu V2 search contract: query types 12, 13, 14, 1, 2, 7, and 10; do not invent undocumented wildcard parameters.
- Use Tianditu's own administrative name/9-digit GB code for `specify`; never substitute AMap/Tencent codes without an explicit mapping record.
- Use WGS84-compatible lon/lat for Tianditu search, geocoder, route, and local spatial checks; do not apply GCJ-02 conversion.
- Enforce documented limits: search `count` 1–300, provider total overflow over 500, and polygon input no more than 20 points per request.
- Preserve all raw responses and all attempts; `success_empty`, `partial`, `failed`, and `unsupported` must remain distinct.
- Retry transient transport/HTTP/provider failures with bounded backoff; do not retry a confirmed empty response or a deterministic parameter/permission failure indefinitely.
- Reuse existing successful Tianditu cache entries by canonical request key; the new collector must not consume quota for requests whose valid raw cache is already present unless `--refresh` is explicit.
- Keep old validation output untouched; write the new collector under `output/map_validation/tianditu_full/` until compatibility is verified.
- Never scrape private tile/vector endpoints or infer text from raster/vector tile internals; only use documented APIs and explicitly discovered public WFS layers.

---

### Task 1: Define the new collector contract and request planner

**Files:**
- Create: `scripts/collect_tianditu_full.py`
- Test: `tests/test_collect_tianditu_full.py`

**Interfaces:**
- `TiandituRequestJob`: immutable job metadata containing stage, operation, URL, sanitized params, scope level, category, spatial partition, and coordinate contract.
- `build_admin_jobs(context, config) -> list[TiandituRequestJob]`
- `build_l1_jobs(context, names, config) -> list[TiandituRequestJob]`
- `polygon_chunks(geometry, max_vertices=20) -> list[str]`
- `request_key(url, params) -> str`

- [ ] **Step 1: Write failing tests for deterministic request planning.**

  Cover: `queryType=13` always includes `specify` and `mapBound`; administrative jobs include village/town/county/city scope jobs; category jobs are generated for every configured category; polygon chunks close the ring and contain at most 20 points; L1 jobs include project-local and Meizhou-only fallback scopes.

- [ ] **Step 2: Run the focused tests and confirm they fail because the new module does not exist.**

  Run: `python -m pytest tests/test_collect_tianditu_full.py -q`

- [ ] **Step 3: Implement the immutable job model and pure planner functions.**

  Build provider methods in this order: administrative code/boundary discovery, statistics (`queryType=14`), administrative category search (`queryType=13`), project/expanded polygon category search (`queryType=10`), local bbox/place-name search (`queryType=7`, `queryType=1`, `queryType=2`), reverse-geocode probe jobs, route probes, and WFS discovery/feature jobs. Use category shards rather than a fake empty keyword.

- [ ] **Step 4: Run the focused tests and refactor only pure planning code while they remain green.**

  Run: `python -m pytest tests/test_collect_tianditu_full.py -q`

---

### Task 2: Implement bounded transport, cache reuse, and failure semantics

**Files:**
- Modify: `scripts/collect_tianditu_full.py`
- Test: `tests/test_collect_tianditu_full.py`

**Interfaces:**
- `TiandituTransport.request(job) -> RequestResult`
- `classify_tianditu_response(http_status, payload, error) -> StatusResult`
- `retry_delay(attempt, error_class) -> float`
- `CacheStore.load(request_key)`, `CacheStore.write_raw(...)`, `CacheStore.write_pointer(...)`

- [ ] **Step 1: Write failing tests for cache hits, empty responses, transient retries, deterministic failures, and malformed JSON/XML.**

  Assert that a cache hit performs no network call; a successful zero-record response becomes `success_empty`; HTTP 5xx and connection timeout retry; HTTP 400/401/403 and provider parameter codes become `failed` with `retryable=false`; every attempt is persisted; and a non-JSON WFS ServiceException is retained as raw text/XML rather than silently converted to empty data.

- [ ] **Step 2: Run the focused tests and confirm the transport tests fail.**

  Run: `python -m pytest tests/test_collect_tianditu_full.py -q`

- [ ] **Step 3: Implement the transport and cache layer.**

  Store one canonical raw envelope per request key, a pointer cache entry, and append-only attempt/request records. Include API operation, URL, sanitized parameters, coordinate contract, provider status/infocode, HTTP status, response hash, retrieval time, retry count, and failure class. Do not include the API key in a key, log, or raw metadata.

- [ ] **Step 4: Run tests and verify no credentials appear in serialized artifacts.**

  Run: `python -m pytest tests/test_collect_tianditu_full.py -q`

---

### Task 3: Implement administrative and spatial collection with completeness accounting

**Files:**
- Modify: `scripts/collect_tianditu_full.py`
- Test: `tests/test_collect_tianditu_full.py`

**Interfaces:**
- `collect_admin_stage(context, transport, config) -> CollectionSummary`
- `paginate_search(job_factory, transport) -> list[RawReference]`
- `scope_filter(record, context) -> ScopeDecision`
- `normalize_tianditu_record(record, raw_ref, job) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests for category pagination, >500 sharding, local point-in-polygon filtering, and scope buckets.**

  Include a provider count of 501 that forces a spatial/category split, a record just outside the village boundary but inside the township, a record outside Meizhou, and a polygon response that overlaps two chunks and must deduplicate by `hotPointID` plus normalized fallback identity.

- [ ] **Step 2: Implement the administrative stage.**

  Discover and cache Tianditu administrative metadata, run queryType 14 statistics per scope/category, queryType 13 with exact `specify` plus bbox and `show=2`, queryType 10 for each <=20-vertex polygon chunk, and run queryType 1/2/7 as scoped supplements. Paginate only within documented limits; if totals exceed provider limits, split by category, spatial tile, or child administrative scope.

- [ ] **Step 3: Add reverse-geocode, route, and WFS jobs without promoting them to POI records.**

  Reverse-geocode boundary/grid/bundle probe points with the full documented request; retain roads, road intersections, addresses, and administrative fields as observation records. Route results are validation observations. WFS jobs first request GetCapabilities, then DescribeFeatureType for discovered layers, then GetFeature by bbox/available paging. Preserve non-JSON service exceptions as failed responses.

- [ ] **Step 4: Run focused tests and verify the summary distinguishes retrieval, coverage, and scope.**

  Run: `python -m pytest tests/test_collect_tianditu_full.py -q`

---

### Task 4: Implement L1 place-name collection with tiered scope and evidence-safe output

**Files:**
- Modify: `scripts/collect_tianditu_full.py`
- Test: `tests/test_collect_tianditu_full.py`

**Interfaces:**
- `collect_l1_stage(context, transport, config) -> CollectionSummary`
- `load_l1_place_names() -> tuple[list[dict], list[dict]]`
- `write_candidate_package(summary) -> Path`

- [ ] **Step 1: Write failing tests for exact-name scope tiers and outside-project Meizhou retention.**

  Assert that each L1 name is queried project-local first, then only if necessary expanded/township/county/Meizhou-local; no query is allowed to leave the Meizhou scope; a result outside the village boundary but within Meizhou is retained in a separate bucket; and a missing result is not treated as a provider failure.

- [ ] **Step 2: Implement L1 collection using the latest valid L1 snapshot.**

  For each accepted place-like name, queryType 7/1/2 with `specify` and bbox tiers, queryType 10 with polygon chunks, and the Tianditu geocoder with the full structured address. Deduplicate all responses while retaining every request reference. Keep L1-derived candidates separate from administrative baseline records.

- [ ] **Step 3: Generate normalized-all, retained-candidates, rejected-candidates, coverage, and manifest artifacts.**

  The candidate package may be consumed by later Evidence/GROUND work, but it must contain only normalized records with raw request references; GROUND still cannot create geometry from an external result.

- [ ] **Step 4: Run focused tests.**

  Run: `python -m pytest tests/test_collect_tianditu_full.py -q`

---

### Task 5: Add command-line entry points and compatibility checks

**Files:**
- Modify: `scripts/collect_tianditu_full.py`
- Modify: `docs/design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md`
- Test: `tests/test_collect_tianditu_full.py`

**Interfaces:**
- CLI: `python scripts/collect_tianditu_full.py --stage admin|l1|all --refresh --dry-run`
- Output root: `output/map_validation/tianditu_full/01_admin_scope` and `output/map_validation/tianditu_full/02_l1_place_names`

- [ ] **Step 1: Write failing CLI tests for dry-run counts, missing credential behavior, and cache-only rerun.**

- [ ] **Step 2: Implement CLI/configuration.**

  Support `--stage`, `--refresh`, `--dry-run`, `--min-interval`, `--max-retries`, `--output-root`, and an optional explicit Tianditu administrative-code mapping file. Do not call the network in dry-run mode.

- [ ] **Step 3: Update the target design document.**

  Document that Tianditu data collection is a provider-data layer with raw snapshots, coverage accounting, and normalized external candidates; Evidence references these records; GROUND binds only registered candidates and local geometry. State the official API limits and that basemap labels remain outside the public full-enumeration contract.

- [ ] **Step 4: Run the complete relevant test suite and static checks.**

  Run: `python -m pytest tests/test_collect_tianditu_full.py tests/test_three_provider_validation.py tests/test_migrate_amap_validation_cache.py -q`

  Also run: `python -m py_compile scripts/collect_tianditu_full.py`

