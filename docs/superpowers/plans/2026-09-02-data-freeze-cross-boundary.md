# DATA Freeze and Cross-Boundary Contract Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze DATA at its current P0 boundary by making provider acquisition and DATA change publication explicit, while documenting the remaining WM/Evidence/GROUND contracts without implementing those modules prematurely.

**Architecture:** DATA owns admission, normalized products, BoundaryScope, remote acquisition execution, lease/fencing, immutable observation storage, and publication of a DATA-only `DataChangeSet`. Evidence owns semantic requirements and `EvidenceQueryPlan`; a future unified Dependency Runtime owns cross-module stale propagation. WM, Evidence, L1-GROUND, and Cognition design documents will be aligned to these boundaries and marked target/partial where code is not being added.

**Tech Stack:** Python 3.12+, Pydantic v2, Shapely, pytest, Markdown design contracts, CAS/SQLite-backed artifact metadata.

## Global Constraints

- DATA must remain the only writer of DATA products and must not directly mutate WM, Evidence, or Ground runtime caches.
- `ProviderAcquisitionPlan` and `EvidenceQueryPlan` are distinct contracts with different owners.
- DATA publishes immutable `DataChangeSet`; cross-module invalidation is a Dependency Runtime responsibility documented as target behavior.
- No old `ProviderQueryPlan`, `DataInvalidationPlan`, typed ingest, Bundle, or output-cache compatibility shim may remain in the active DATA API.
- WM/Evidence/L1-GROUND/Cognition changes from the supplied review are documentation-only in this plan.
- Existing user changes must be preserved; verification uses focused tests followed by the full suite and static acceptance scanner.

---

### Task 1: Rename DATA provider query contract to acquisition contract

**Files:**
- Delete: `backend/app/contracts/data/provider_query_contracts.py`
- Create: `backend/app/contracts/data/provider_acquisition_contracts.py`
- Modify: `backend/app/contracts/data/__init__.py`
- Modify: `scripts/collect_amap_jintian_validation.py`
- Modify: `scripts/collect_three_provider_validation.py`
- Modify: `scripts/collect_tianditu_full.py`
- Modify: `tests/test_collect_amap_jintian_validation.py`
- Modify: `tests/test_jintian_data_e2e_acceptance.py`

**Interfaces:**
- Produces `ProviderAcquisitionPlan` and `build_provider_acquisition_plan()`.
- The plan contains only DATA acquisition inputs: boundary/query digests, normalized/provider CRS, geometry, bounds, expansion, and coverage policy.
- Evidence keeps its independent `EvidenceQueryPlan` in `backend/app/infrastructure/evidence_runtime/query_planner.py`.

- [ ] **Step 1: Write the failing contract-boundary test**

Add assertions that the DATA package exports `ProviderAcquisitionPlan`, does not export `ProviderQueryPlan`, and that provider collection context uses `provider_acquisition_plans`.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest tests/test_data_p1_p2_docs.py tests/test_jintian_data_e2e_acceptance.py -q`

Expected: FAIL because the current DATA contract and collector context still use `ProviderQueryPlan`/`provider_query_plans`.

- [ ] **Step 3: Implement the explicit DATA acquisition contract**

Rename the model/function/module and update public exports, provider collector manifests, query-plan filenames, and tests. Do not add a compatibility alias.

- [ ] **Step 4: Run focused provider and Jintian tests**

Run: `python -m pytest tests/test_collect_amap_jintian_validation.py tests/test_jintian_data_e2e_acceptance.py tests/test_data_remote_admission.py -q`

Expected: PASS with no import of the retired query contract.

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts/data backend/app/data scripts tests
git commit -m "refactor: separate provider acquisition from evidence query planning"
```

### Task 2: Make DATA invalidation publish-only

**Files:**
- Modify: `backend/app/contracts/data/invalidation_contracts.py`
- Modify: `backend/app/contracts/data/__init__.py`
- Modify: `backend/app/modules/data/invalidation.py`
- Modify: `backend/app/modules/data/application.py`
- Modify: `backend/app/infrastructure/context_runtime/manager.py`
- Modify: `tests/test_data_dependency_invalidation.py`
- Create: `tests/test_data_change_set_boundary.py`

**Interfaces:**
- Produces `DataChangeSet` containing previous/current DATA graph digests, changed DATA node refs, conservative flag, and reason codes.
- `build_data_dependency_graph()` contains only DATA nodes (`catalog`, `source`, `normalized`, `representation`, `capability`); it does not contain `wm`, `evidence`, or `ground` nodes.
- `plan_data_change_set(previous, current)` returns `DataChangeSet`.
- Removes `apply_data_dependency_invalidation()` and `DataInvalidationPlan`; DATA no longer imports or calls WM/Evidence runtime invalidation functions.

- [ ] **Step 1: Write the failing boundary test**

Test that a changed DATA feature creates a `DataChangeSet` containing the changed DATA ref, that no consumer node is present in the graph, and that the DATA module has no downstream cache mutation function.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest tests/test_data_dependency_invalidation.py tests/test_data_change_set_boundary.py -q`

Expected: FAIL because the current graph contains consumer nodes and `apply_data_dependency_invalidation()` directly calls WM/Evidence runtime functions.

- [ ] **Step 3: Implement `DataChangeSet` and remove downstream mutation**

Change the DATA contract and implementation. Update application/context callers to use only the DATA graph digest. Leave cross-module invalidation ownership as a documented future Dependency Runtime contract.

- [ ] **Step 4: Run focused DATA tests**

Run: `python -m pytest tests/test_data_dependency_invalidation.py tests/test_data_change_set_boundary.py tests/test_data_products_p1.py -q`

Expected: PASS; no WM/Evidence cache functions are called by DATA.

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts/data backend/app/modules/data backend/app/infrastructure/context_runtime/manager.py tests
git commit -m "refactor: publish data changes without downstream invalidation"
```

### Task 3: Align DATA and cross-module design documents

**Files:**
- Modify: `docs/design/DATA_EXECUTABLE_DESIGN.md`
- Modify: `docs/design/DATA_PRODUCTION_RUNBOOK.md`
- Modify: `docs/design/04_EVIDENCE.md`
- Modify: `docs/design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md`
- Modify: `docs/design/L1_GROUND_EXECUTABLE_DESIGN.md`
- Modify: `docs/design/PLANNING_GROUND_EXECUTABLE_DESIGN.md`
- Modify: `docs/design/05_MIGRATION.md`
- Modify: `tests/test_data_p1_p2_docs.py`

**Interfaces:**
- DATA docs name `ProviderAcquisitionPlan`/`RemoteAcquisitionExecutionPlan` and `DataChangeSet`.
- Evidence docs define `EvidencePolicyRegistry`, `EvidenceRequirement → EvidenceQueryPlan → AcquisitionRequest`, and a round/epoch/fixpoint protocol as target design.
- WM docs define source-local/provisional identity versus canonical identity and `CurrentWorldQueryPort` as the first typed port.
- L1-GROUND docs remove `WorldModelCommitRequest` from public output, end at `ProposalBatch`, and define Cognition commit plus binding revalidation as separate contexts.
- Planning Ground docs identify Dependency Runtime as the sole cross-module invalidation owner.

- [ ] **Step 1: Add documentation regression assertions**

Assert the DATA docs use acquisition/change-set terms and the WM/Evidence/GROUND docs contain the reviewed contract decisions while preserving `TARGET/PARTIAL` status for unimplemented code.

- [ ] **Step 2: Run the documentation test to verify it fails**

Run: `python -m pytest tests/test_data_p1_p2_docs.py -q`

Expected: FAIL until the old provider/invalidation wording and missing cross-module decisions are corrected.

- [ ] **Step 3: Update the documents**

Make the ownership, lifecycle, transaction, identity, policy, round, and invalidation decisions explicit. Do not claim WM/Evidence/GROUND code is implemented.

- [ ] **Step 4: Run documentation and acceptance tests**

Run: `python -m pytest tests/test_data_p1_p2_docs.py tests/test_data_production_acceptance.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/design tests/test_data_p1_p2_docs.py
git commit -m "docs: freeze data boundary and record cognition contracts"
```

### Task 4: Final verification and DATA freeze report

**Files:**
- Verify: all changed DATA contracts, application modules, provider scripts, tests, and design documents.

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests -q`

Expected: all tests pass; existing third-party deprecation warnings may remain separately reported.

- [ ] **Step 2: Run static checks**

Run: `git diff --check` and `python scripts/acceptance/data_production_acceptance.py --root .`

Expected: no whitespace errors, permission violations, secret findings, legacy paths, or retired DATA imports.

- [ ] **Step 3: Verify retired names**

Run: `rg -n --glob '*.py' 'ProviderQueryPlan|build_provider_query_plan|DataInvalidationPlan|apply_data_dependency_invalidation|provider_query_plans' backend/app scripts tests`

Expected: no active implementation references; any intentional historical mention must be limited to migration documentation and tests that assert retirement.

- [ ] **Step 4: Update the plan status**

Record that DATA is frozen at P0/current-local scope and that online provider coverage, ACL, disaster recovery, and SLO/RPO/RTO remain production backlog rather than WM/Evidence blockers.
