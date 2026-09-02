# DATA P1/P2 Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收敛 DATA 的 P1/P2 差距：让已实现的本地文件格式走统一准入边界，发布可独立追踪的 DATA 产品 artifact，补齐 admission 生命周期/恢复契约，并对上传输入施加可审计的大小与记录预算。

**Architecture:** 继续以 `DataAdmissionFacade` 为唯一写边界；本地文件先解析为 generic records，再通过显式 capability matrix、CRS/encoding/role gate 进入 CAS。catalog index 只引用独立的 source、normalized、representation、capability products；旧完整 payload、旧准入 wrapper 和 legacy Bundle 不再作为运行时回退。在线 API/WMTS/remote raster 不在上传准入阶段自动联网，仍由 provider/Evidence 边界负责。

**Tech Stack:** Python 3、Pydantic、Shapely/pyproj、GeoPandas/Fiona、Pandas、FastAPI UploadFile、CAS artifact repository、pytest。

## Global Constraints

- current DATA 只接受 `current_evidence`；planned/reference/control/unclassified 不得进入 current catalog。
- CRS 缺失、未知或无法转换必须 fail closed；不得按 WGS84 猜测。
- 不在 DATA admission 中隐式访问 API、WFS、MapServer、WMTS 或 remote raster。
- 旧 `VillageBundle`、BSM/DLBM 派生、external anchor injection 不属于运行时入口；本轮不保留默认或隐式 fallback。
- 上传大小、文本长度、feature/row 数量必须有硬上限，超过上限形成可持久化的 admission gap。
- 任何规范化或能力变化都只能发布新的 immutable artifact；named ref 使用 CAS，stale parent 不得覆盖 current。
- 所有新代码使用现有项目风格：Python 4 空格、LF、最小补丁范围；不得重置工作区中已有改动。

---

### Task 1: 扩展本地准入 capability matrix

**Files:**
- Modify: `backend/app/data/admission.py`
- Modify: `backend/app/data/ingestion/documents/document_loader.py`
- Modify: `backend/app/data/ingestion/upload.py`
- Modify: `backend/app/modules/data/application.py`
- Test: `tests/test_data_admission_p1.py`

**Interfaces:**
- Consumes: parsed GeoJSON/table/raster upload payloads and explicit filename-derived media declarations.
- Produces: `check_local_admission_boundary(...)` and an async facade path that admits supported local vector formats and tables without invoking legacy Bundle code.

- [ ] **Step 1: Write failing capability-matrix tests**

  Add tests asserting that current-evidence `file_vector` accepts GeoJSON, Shapefile ZIP, GPKG/GDB/KML/GML declarations after parsing to FeatureCollection; `table` accepts CSV/TSV/XLSX with non-spatial CRS; wrong role, unknown CRS, non-UTF8, unsupported media, and remote/API adapters return the exact terminal state expected by the contract.

- [ ] **Step 2: Run the focused tests and verify the matrix is currently incomplete**

  Run `python -m pytest tests/test_data_admission_p1.py -q`. Expected: failures showing the current P0-only check rejects at least one supported local format.

- [ ] **Step 3: Implement the explicit local matrix**

  Add one deterministic checker with media/adapter/CRS/encoding/role inputs and remove the P0-only checker from runtime imports. Make the facade call the new checker. Add table materialization in `_prepare_input` to turn `TableResource.tables[*].rows` into generic non-spatial records, preserving sheet and row lineage.

- [ ] **Step 4: Make upload declarations match the parsed source**

  Extend file classification for `.gdb`; map GeoJSON/vector container/table suffixes to explicit media types and adapters. Do not use `application/octet-stream` for a recognized local format. Preserve source format, layer, CRS and parse diagnostics in policy metadata.

- [ ] **Step 5: Run focused and existing DATA tests**

  Run `python -m pytest tests/test_data_admission_p1.py tests/test_data_admission_mvp.py tests/test_jintian_data_e2e_acceptance.py -q`. Expected: PASS.

### Task 2: Publish independent DATA product artifacts

**Files:**
- Create: `backend/app/contracts/data/product_contracts.py`
- Modify: `backend/app/contracts/data/__init__.py`
- Modify: `backend/app/contracts/data/source_contracts.py`
- Modify: `backend/app/infrastructure/artifacts/runtime.py`
- Modify: `backend/app/modules/data/application.py`
- Test: `tests/test_data_products_p1.py`

**Interfaces:**
- Consumes: `DataResourceCatalogSnapshot` produced by the existing normalizer.
- Produces: immutable `SourceSnapshotArtifact`, `NormalizedResourceArtifact`, `RepresentationSnapshotArtifact`, and `CapabilityIndexArtifact`; `DataResourceCatalogIndexSnapshot` carries their refs/digests; loader can compose a catalog from the products.

- [ ] **Step 1: Write failing product and reload tests**

  Assert that a DATA run writes four separate schema-typed artifacts, that the catalog index contains their descriptor digests, that no component embeds raw geometry or raw attributes, and that `DataApplication.load_catalog()` composes the same catalog digest from the component artifacts.

- [ ] **Step 2: Implement frozen component contracts**

  Define flat manifests containing snapshot identity, source/dataset/feature refs and digests, normalized geometry digests, representation/capability rows, policy version, and a self-derived digest. Components contain lineage and hashes only, not raw geometry/attributes.

- [ ] **Step 3: Add component refs to the index and runtime key registry**

  Extend `DataResourceCatalogIndexSnapshot` with component refs/digests and add four named artifact keys. Remove `data_catalog_payload` from the new artifact key registry and from production state publication; the index and four products are the only catalog publication.

- [ ] **Step 4: Persist components before publishing the catalog index**

  Update `DataApplication.run()` and admission replay to store/reload the four products with parent refs in source → normalized → representation → capability → index order. Add the component refs to `DataRunResult`, state patch, receipt parents, and boundary-scope parents.

- [ ] **Step 5: Compose catalog from products and verify parent/digest checks**

  Implement a strict loader that validates every component digest and reconstructs the full catalog only from the four products. Missing component, legacy payload-only state, tampered component, and stale parent all fail closed. Add tests for each case.

### Task 3: Complete lifecycle terminal traces and recovery contract

**Files:**
- Modify: `backend/app/contracts/data/admission_contracts.py`
- Modify: `backend/app/modules/data/application.py`
- Modify: `backend/app/data/ingestion/upload.py`
- Test: `tests/test_data_admission_p1.py`

**Interfaces:**
- Consumes: existing receipt/gap CAS persistence and `DataAdmissionFacade.resume()` entry point.
- Produces: stage-accurate lifecycle tuples for every terminal result and explicit gap-parented recovery attempts.

- [ ] **Step 1: Write lifecycle/recovery tests**

  Cover missing input, unsupported declaration, encoding/CRS rejection, parse failure, geometry failure, policy rejection, successful admission, retry from a retryable gap, rejection of non-retryable gap, and idempotent replay. Assert lifecycle ordering, parent gap refs, and no mutation of the old receipt.

- [ ] **Step 2: Add recovery parent to the request contract**

  Add optional `recovery_gap_ref` and require `resume()` to validate the immutable `DataAdmissionGap` source, attempt and retryability against the new request before admitting.

- [ ] **Step 3: Thread stage traces through facade failures**

  Let `_rejection()` receive an explicit lifecycle prefix. Use `PARSING`, `NORMALIZED`, `REPRESENTATION_BUILT`, and `CAPABILITY_INDEXED` at the corresponding failure boundaries; map normalizer failures to CRS/geometry/invalid terminal states without catching CAS/storage errors as input defects.

- [ ] **Step 4: Persist recovery lineage and update upload metadata**

  Include the recovery gap descriptor in receipt `input_refs` and observed metadata, and persist the complete lifecycle tuple in `UploadedFile` and returned upload metadata.

- [ ] **Step 5: Run lifecycle/recovery and full DATA tests**

  Run `python -m pytest tests/test_data_admission_p1.py tests/test_data_admission_mvp.py tests/test_jintian_data_e2e_acceptance.py -q`. Expected: PASS.

### Task 4: Enforce bounded upload/input budgets

**Files:**
- Modify: `backend/app/core/settings.py`
- Modify: `backend/app/data/ingestion/upload.py`
- Modify: `backend/app/modules/data/application.py`
- Modify: `backend/app/data/resource_catalog.py`
- Test: `tests/test_data_input_limits_p2.py`

**Interfaces:**
- Consumes: environment-configured DATA budgets and current upload/facade inputs.
- Produces: deterministic `INVALID`/`POLICY_REJECTED` gaps for oversized byte, text, feature, row, and coordinate inputs; no unbounded parse/materialize path.

- [ ] **Step 1: Write failing budget tests**

  Test byte limit before full parse, Markdown character limit, GeoJSON feature limit, table row limit, and a normal input at the boundary. Assert the result is quarantined with a stable reason code and does not publish catalog refs.

- [ ] **Step 2: Add bounded settings and pure budget helpers**

  Add positive integer settings with safe defaults and helpers that read limits once per operation. Keep test overrides possible through environment variables without changing defaults at import time in tests.

- [ ] **Step 3: Enforce byte/text budgets in upload ingress**

  Read at most `max_upload_bytes + 1`; reject before decoder/LLM invocation when exceeded. Enforce Markdown parsed text length before temporal admission and persist observed limits.

- [ ] **Step 4: Enforce feature/row budgets in facade materialization and normalization**

  Check FeatureCollection and TableResource counts before expansion; keep a second check after materialization so direct facade calls cannot bypass upload limits. Return immutable gap/receipt rather than raising for user data over budget.

- [ ] **Step 5: Run focused tests, compile, and diff checks**

  Run `python -m pytest tests/test_data_input_limits_p2.py tests/test_data_admission_p1.py tests/test_data_admission_mvp.py -q`, `python -m compileall -q backend/app scripts tests`, and `git diff --check`.

### Task 5: Update DATA design and acceptance evidence

**Files:**
- Modify: `docs/design/DATA_EXECUTABLE_DESIGN.md`
- Modify: `docs/design/05_MIGRATION.md`
- Modify: `docs/design/acceptance/01_data_acceptance.md`
- Modify: `backend/app/data/README.md`
- Modify: `backend/app/data/ingestion/README.md`
- Test: `tests/test_data_p1_p2_docs.py`

**Interfaces:**
- Consumes: implemented contracts, actual artifact keys, terminal/recovery behavior, and focused test results.
- Produces: documentation that distinguishes P1/P2 runtime-verified behavior from remaining non-P0 driver and legacy migration gaps.

- [ ] **Step 1: Write documentation consistency tests**

  Assert docs name the four component products, the canonical local admission matrix, bounded budgets, recovery parent, and `data/cache/map_observations`; assert old Bundle is explicitly migration-only.

- [ ] **Step 2: Update canonical design and migration ledger**

  Replace “catalog payload is canonical” language with component-product publication and document the payload compatibility rule. Mark completed P1/P2 exits with exact code/test references and leave remote drivers/physical legacy deletion as open gaps.

- [ ] **Step 3: Update acceptance and runtime READMEs**

  Add local vector/table admission cases, component artifact reload/tamper cases, terminal lifecycle/recovery matrix, and input-budget cases.

- [ ] **Step 4: Run documentation and complete verification**

  Run `python -m pytest tests/test_data_p1_p2_docs.py tests/test_data_admission_p1.py tests/test_data_products_p1.py tests/test_data_input_limits_p2.py tests/test_jintian_data_e2e_acceptance.py -q`, then the repository DATA suite `python -m pytest tests -q` and `git diff --check`.
