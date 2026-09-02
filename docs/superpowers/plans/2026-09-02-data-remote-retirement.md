# DATA Remote Admission and Legacy Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 DATA 成为唯一可执行数据入口，完成远程来源声明式准入、provider 多进程写入保护、跨 WM/Evidence/Planning Ground 的依赖失效、旧历史模块物理删除，并用真实 Jintian 数据证明 WM 与 Evidence 消费同一不可变 DATA 产品。

**Architecture:** 本轮保留不可变 CAS 作为唯一 DATA 产品边界。所有远程 API/WFS/MapServer/WMTS/remote raster 只在准入阶段写入声明式 receipt，不在准入阶段抓取；provider run 通过 lease + fencing token 持有写权限，结果以 coverage 完整状态发布。WM、Evidence、Planning Ground 只读取 `DataApplication.load_catalog()` 组合出的 DATA catalog，并通过统一 dependency/subgraph invalidation 计划拒绝旧 digest。

**Tech Stack:** Python 3.11+, Pydantic v2, Shapely, RDFLib, filesystem CAS, SQLite, pytest, PowerShell。

## Global Constraints

- 必须物理删除旧 Bundle、BSM/DLBM 派生、external anchor injection 及其默认兼容入口；不能以 feature flag 保留旧运行路径。
- 不得在 admission 阶段执行远程网络请求；远程来源只接受声明式 contract，实际抓取属于 provider run。
- 未知 CRS、未验证坐标转换、缺少 boundary digest、部分 coverage、过期 lease 或旧 fencing token 一律 fail closed。
- provider cache 默认只能写入 `data/cache/map_observations`；`output/map_validation` 只能作为人工确认过的只读迁移源。
- 原始上传 geometry、normalized geometry 和 provider observation 必须不可变；WM/Evidence 只能产生 projection/query result，不能回写 DATA geometry。
- 所有新写入必须带 source/catalog digest、boundary digest、query geometry digest、CRS contract、coverage 状态和 provenance。
- 生产权限、安全扫描、SLO、灾难恢复必须有可执行验收探针；不能把“声明在文档中”当成运行证据。

---

### Task 1: 建立远程来源声明式 admission contract

**Files:**
- Create: `backend/app/contracts/data/remote_admission_contracts.py`
- Modify: `backend/app/contracts/data/__init__.py`
- Modify: `backend/app/contracts/data/admission_contracts.py`
- Modify: `backend/app/modules/data/admission.py`
- Modify: `backend/app/data/catalog/config.py`
- Modify: `backend/app/data/ingestion/sources/api_vector.py`
- Modify: `backend/app/data/ingestion/sources/wmts_tile.py`
- Modify: `backend/app/data/ingestion/sources/remote_raster.py`
- Test: `tests/test_data_remote_admission.py`

**Interfaces:**
- `RemoteSourceKind = Literal["api_vector", "wfs", "mapserver", "wmts", "remote_raster"]`。
- `RemoteSourceAdmissionRequest(source_id: str, kind: RemoteSourceKind, endpoint: AnyHttpUrl, provider: str, layer: str | None, boundary_ref: str, boundary_digest: str, query_geometry_digest: str, crs_contract: str, capabilities: tuple[str, ...], auth_ref: str | None, limits: RemoteAdmissionLimits)`。
- `RemoteSourceAdmissionReceipt(receipt_id: str, request_digest: str, status: Literal["ADMITTED", "QUARANTINED", "REJECTED"], provider_run_required: bool, boundary_ref: str, boundary_digest: str, query_geometry_digest: str, crs_contract: str, capability_contract: tuple[str, ...], provenance: dict[str, Any])`。
- `DataAdmissionFacade.admit_declared_remote(request, *, state, run_id, branch_id) -> RemoteSourceAdmissionReceipt`。

- [ ] **Step 1: Write the failing contract tests**

  Cover all five kinds, HTTPS-only endpoint validation, host/provider allowlist, required boundary/query/CRS digests, auth ref non-secret rule, explicit capability, and the fact that the call never invokes a network client.

- [ ] **Step 2: Run the focused tests and verify the contract is absent**

  Run: `python -m pytest tests/test_data_remote_admission.py -q`

  Expected: FAIL because the remote contract and facade entry point do not yet exist.

- [ ] **Step 3: Implement the declaration-only contract and facade method**

  Validate endpoint scheme/host/provider, fixed provider kinds, positive request limits, digest syntax, explicit CRS target, and redacted `auth_ref` (`secret`, token, key, password values are rejected). Persist only the receipt or a typed rejection gap. Do not instantiate `ConnectionRegistry`, `requests`, or any source driver.

- [ ] **Step 4: Make drivers consume the declared contract**

  Add `admission_contract`/`source_id` metadata to API vector, WMTS and remote raster drivers. Drivers must refuse fetch when the declared boundary/query/CRS contract is absent or inconsistent, and must return coverage metadata rather than silently treating a download guide as admitted data.

- [ ] **Step 5: Run focused tests and the existing data suite**

  Run: `python -m pytest tests/test_data_remote_admission.py tests/test_data_admission_mvp.py tests/test_data_admission_p1.py -q`

  Expected: PASS; any existing test that calls a retired compatibility path must be migrated to the new facade rather than re-enabling the path.

---

### Task 2: Provider run lease, fencing, atomic writer, and crash recovery

**Files:**
- Create: `backend/app/contracts/data/provider_run_contracts.py`
- Create: `backend/app/data/catalog/provider_run_lease.py`
- Modify: `backend/app/data/catalog/external_observation_cache.py`
- Modify: `scripts/collect_three_provider_validation.py`
- Modify: `scripts/collect_amap_jintian_validation.py`
- Modify: `scripts/collect_tianditu_full.py`
- Test: `tests/test_provider_run_lease.py`

**Interfaces:**
- `ProviderRunLease(run_ref: str, provider: str, owner_id: str, fencing_token: int, acquired_at: datetime, expires_at: datetime, status: Literal["ACTIVE", "EXPIRED", "RELEASED"])`。
- `ProviderRunLeaseStore.acquire(run_ref, provider, owner_id, *, ttl_seconds, now=None) -> ProviderRunLease`。
- `ProviderRunLeaseStore.renew(lease, *, now=None) -> ProviderRunLease`。
- `ProviderRunLeaseStore.release(lease, *, now=None) -> None`。
- `ProviderRunLeaseStore.assert_writer(lease, *, now=None) -> None`。
- `ProviderObservationWriter.publish(lease, snapshot_payload, *, boundary_digest, query_geometry_digest, crs_contract, coverage) -> Path`。
- `ProviderObservationWriter.recover(run_ref, provider, *, now=None) -> ProviderRunRecovery`。

- [ ] **Step 1: Write concurrency and recovery tests**

  Verify two processes/instances cannot hold the same active lease, a reclaimed lease gets a strictly larger fencing token, stale writers are rejected even when their owner id is reused, publish uses temp-file + fsync + atomic replace, partial files are never indexed as complete, and an expired run is recoverable as `ABANDONED/PARTIAL`.

- [ ] **Step 2: Run the lease tests and verify failure**

  Run: `python -m pytest tests/test_provider_run_lease.py -q`

  Expected: FAIL because no provider lease store/writer exists.

- [ ] **Step 3: Implement the lease store**

  Store one JSON lease record per `run_ref/provider` under `data/cache/map_observations/.leases`. Use an OS-level exclusive lock for read-modify-write, monotonic fencing tokens, UTC expiry, atomic replacement, and no secret values. Expired leases can be reclaimed only after marking the prior run abandoned.

- [ ] **Step 4: Implement the fenced observation writer**

  Write each provider result into a run-specific staging directory. Before every write and final publish, call `assert_writer`; publish a manifest only if all records have checksums and the declared coverage is complete. The manifest must include run id, lease token, boundary/query digests, CRS contract, per-layer counts, failures, and `coverage_status` (`COMPLETE`, `PARTIAL`, `FAILED`, `ABANDONED`).

- [ ] **Step 5: Update all three collectors**

  Acquire one lease per provider run, pass the boundary/query contract into the writer, release only after final manifest publication, and mark the run abandoned on exception. No collector may write directly to a cache path or publish a manifest without the writer.

- [ ] **Step 6: Run focused provider tests and cache tests**

  Run: `python -m pytest tests/test_provider_run_lease.py tests/test_external_observation_cache.py tests/test_three_provider_validation.py tests/test_collect_amap_jintian_validation.py tests/test_collect_tianditu_full.py -q`

  Expected: PASS, with stale/partial manifests rejected by the read-only observation loader.

---

### Task 3: Unified DATA dependency/subgraph invalidation across WM, Evidence, and Planning Ground

**Files:**
- Create: `backend/app/contracts/data/invalidation_contracts.py`
- Create: `backend/app/modules/data/invalidation.py`
- Modify: `backend/app/infrastructure/cognition_runtime/world_model_store.py`
- Modify: `backend/app/modules/evidence/application.py`
- Modify: `backend/app/modules/ground/stage.py`
- Modify: `backend/app/infrastructure/context_runtime/manager.py`
- Modify: `backend/app/infrastructure/evidence_runtime/facade.py`
- Test: `tests/test_data_dependency_invalidation.py`

**Interfaces:**
- `DataDependencyNode(node_ref: str, node_kind: Literal["source", "normalized", "representation", "capability", "catalog", "wm", "evidence", "ground"], digest: str, depends_on: tuple[str, ...])`。
- `DataDependencyGraph(catalog_digest: str, nodes: tuple[DataDependencyNode, ...], graph_digest: str)`。
- `DataInvalidationPlan(previous_graph_digest: str, current_graph_digest: str, changed_nodes: tuple[str, ...], stale_nodes: tuple[str, ...], affected_subgraphs: tuple[str, ...], conservative: bool, reason_codes: tuple[str, ...])`。
- `plan_data_dependency_invalidation(previous, current) -> DataInvalidationPlan`。
- `apply_data_dependency_invalidation(state, plan) -> dict[str, Any]`。

- [ ] **Step 1: Write focused graph-diff tests**

  Verify a single normalized feature change invalidates only its representation/capability and downstream WM/Evidence/GROUND nodes that name it; a catalog-level or missing dependency graph invalidates all three downstream subgraphs conservatively; unchanged digests preserve unrelated nodes; the resulting plan is deterministic.

- [ ] **Step 2: Run the invalidation tests and verify failure**

  Run: `python -m pytest tests/test_data_dependency_invalidation.py -q`

  Expected: FAIL because the shared graph and planner do not exist.

- [ ] **Step 3: Implement the immutable dependency graph and planner**

  Build nodes from the four DATA product refs plus explicit consumer refs. Compare by digest and transitive closure. If a consumer has no dependency metadata, set `conservative=True` and invalidate its whole subgraph; never infer precision from filenames or session ids.

- [ ] **Step 4: Bind WM, Evidence, and Ground outputs to the plan**

  Add `data_dependency_graph_digest`/`data_invalidation_plan_digest` to their output metadata and reject retrieval or grounding when the current DATA graph marks their upstream node stale. Invalidation must clear query caches and planning context, but must not mutate source geometry or delete immutable CAS blobs.

- [ ] **Step 5: Run focused consumer tests**

  Run: `python -m pytest tests/test_data_dependency_invalidation.py tests/test_jintian_data_e2e_acceptance.py tests/test_geometry_lineage.py -q`

  Expected: PASS; stale parent, replay and unrelated-node behavior are explicit in assertions.

---

### Task 4: Physically delete retired Bundle/history implementation

**Files:**
- Delete: `backend/app/application/sessions/session_bundle.py`
- Delete: `backend/app/data/catalog/external_anchors.py`
- Delete: `backend/app/infrastructure/evidence_runtime/retrievers/bundle_retriever.py`
- Delete: `backend/app/infrastructure/storage/bundle_store.py`
- Modify: `backend/app/application/sessions/session_service.py`
- Modify: `backend/app/infrastructure/kg/session_kg.py`
- Modify: `backend/app/infrastructure/kg/manager.py`
- Modify: `backend/app/infrastructure/llm/tools/access/shared.py`
- Modify: `backend/app/infrastructure/evidence_runtime/evidence_graph.py`
- Modify: `backend/app/infrastructure/evidence_runtime/index/place_evidence_index.py`
- Modify: `backend/app/spatial/query/context.py`
- Modify: `backend/app/spatial/query/bridge.py`
- Modify: `backend/app/spatial/grounding/grounding.py`
- Modify: `backend/app/spatial/grounding/resolver.py`
- Modify: `backend/app/data/catalog/catalog.py`
- Test: `tests/test_retired_data_modules.py`

**Interfaces:**
- All production callers use `DataApplication.load_catalog(state)` and typed DATA refs; no caller may import `VillageBundle`, `BundleStore`, `external_anchors`, `bundle_retriever`, `load_village_bundle*`, or `resolve_bundle`.

- [ ] **Step 1: Add absence/import-boundary tests before deletion**

  Search production modules for forbidden imports and add tests that import the active DATA/WM/Evidence/GROUND paths while asserting the retired module files are absent after the migration.

- [ ] **Step 2: Migrate remaining callers**

  Replace old spatial/evidence access with catalog adapter queries returning immutable `source_feature_ref`, `representation_ref`, and `geometry_ref`. Replace old coordinate helper use with one strict CRS normalizer that rejects unknown and BD09/GCJ02 values unless a declared conversion contract exists.

- [ ] **Step 3: Run import-boundary tests and full existing tests**

  Run: `python -m pytest tests/test_retired_data_modules.py tests/test_data_products_p1.py tests/test_data_admission_mvp.py -q`

  Expected: FAIL only until every caller has moved; do not add compatibility shims.

- [ ] **Step 4: Physically delete the retired modules**

  Use `apply_patch` delete operations only after `rg` reports no production imports. Remove legacy catalog assembly methods and dead Bundle branches from `session_kg.py`; do not leave a feature flag or environment-variable fallback.

- [ ] **Step 5: Run compile/import and test verification**

  Run: `python -m compileall -q backend/app scripts tests; python -m pytest tests -q; git diff --check`

  Expected: active tests pass, no retired module imports remain, and immutable DATA catalog is the only source path.

---

### Task 5: Production permission, security, SLO, disaster recovery, and real WM/Evidence acceptance

**Files:**
- Create: `backend/app/contracts/data/production_acceptance_contracts.py`
- Create: `scripts/acceptance/data_production_acceptance.py`
- Modify: `docs/design/acceptance/00_common.md`
- Modify: `docs/design/acceptance/01_data_acceptance.md`
- Modify: `docs/design/acceptance/02_world_model_acceptance.md`
- Modify: `docs/design/acceptance/03_evidence_acceptance.md`
- Modify: `docs/design/acceptance/09_planning_ground_acceptance.md`
- Modify: `docs/design/DATA_EXECUTABLE_DESIGN.md`
- Modify: `docs/design/05_MIGRATION.md`
- Test: `tests/test_data_production_acceptance.py`
- Test: `tests/test_jintian_data_e2e_acceptance.py`

**Interfaces:**
- `ProductionAcceptancePolicy(allowed_roots: tuple[str, ...], allowed_hosts: tuple[str, ...], max_upload_bytes: int, max_provider_runtime_seconds: int, max_evidence_latency_ms: int, max_wm_latency_ms: int, rto_seconds: int, rpo_seconds: int)`。
- `run_data_production_acceptance(policy, *, repo_root, state) -> ProductionAcceptanceReport`。
- `ProductionAcceptanceReport(permission_checks, security_checks, slo_checks, recovery_checks, wm_consumption, evidence_consumption, passed, gaps)`。

- [ ] **Step 1: Write the real Jintian acceptance test**

  Use the supplied `data/gis/jintian/current` boundary/layers, DEM, MinerU report and local three-provider cache. Execute upload/admission, normalized products, boundary scope, provider query plan/cache snapshot, context bootstrap, WM projection, Evidence retrieval, and Ground dependency validation. Assert all consumer digests equal the DATA catalog digest, returned evidence carries source/representation lineage, and no input GeoJSON bytes or geometry objects change.

- [ ] **Step 2: Write production acceptance tests**

  Assert path allowlists reject workspace/output writes, remote admission rejects non-allowlisted hosts and embedded secrets, manifests reject incomplete coverage, CAS recovery restores from a copied immutable root, RTO/RPO values are measured and reported, and a dependency scan reports no forbidden legacy imports.

- [ ] **Step 3: Implement the acceptance policy and executable probe**

  Keep policy declarative and environment-driven without printing secrets. Check permissions using temporary roots, run a static security scan (`rg` forbidden imports/secrets plus Python compile/import checks), measure bounded local bootstrap/retrieval timings, and simulate disaster recovery by copying CAS/cache manifests into a clean temp root then replaying descriptors.

- [ ] **Step 4: Update acceptance documentation**

  Separate `runtime-verified`, `documented`, `inferred`, and `open` evidence. Document the exact commands, input paths, expected coverage statuses, RTO/RPO/SLO thresholds, permission model, and recovery runbook. State that remote providers require a subsequent provider run after declaration-only admission.

- [ ] **Step 5: Run final verification**

  Run: `python -m pytest tests -q; python -m compileall -q backend/app scripts tests; python scripts/acceptance/data_production_acceptance.py; git diff --check`

  Expected: active project tests and local acceptance pass. Historical tests under `docs/references` may remain externally blocked by missing optional dependencies and must be reported separately rather than weakening the DATA boundary.

---

## Self-review coverage

- Remote API vector/WFS/MapServer/WMTS/remote raster declaration-only admission: Task 1.
- Multi-process provider writer, lease/fencing, crash recovery: Task 2.
- Boundary/query/CRS/coverage provenance: Tasks 1, 2, and 5.
- Cross WM/Evidence/Planning Ground dependency/subgraph invalidation: Task 3.
- Physical deletion of old Bundle/history paths and no compatibility switch: Task 4.
- Permission, security scan, SLO, disaster recovery: Task 5.
- Real Jintian chain and correct WM/Evidence consumption: Task 5.

No feature flag, fallback import, or “try old path on error” step is permitted by this plan.
