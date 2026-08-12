# Backend Dual-Fact Convergence Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse every dual-fact path in the backend to the blueprint's single-owner architecture: `WorkflowState`-only control, single domain-service producer per stage artifact, `application/`-only transport, single contracts/ home. Delete the old `app.agent/*`, `app/services/*`, `app/modules/*` implementations as each stage is migrated.

**Architecture:** Aggressive cut-over per stage. For each stage: write a domain contract test that fails → move the aggregate/gate logic into `app/domain/<stage>/` → switch the `workflow/stages/<stage>.py` node to call only the domain service → migrate inline `*_gate_decision` to the unified `gate_ref` CAS artifact → delete `app/agent/<stage>/` in the same task. The fixture e2e suite (`tests/e2e`, 12 passing) plus `tests/core` + `tests/contracts` are the per-task regression gate; an architecture test forbidding `import app.agent.*` / `import app.services.*` / `import app.modules.*` from the production path is added once and grown each phase.

**Tech Stack:** Python 3.11, FastAPI, LangGraph, Pydantic v2, pytest, SQLite (artifact store + checkpoint + events), Poetry.

## Global Constraints

- Python 3.11; LF line endings; 4-space indent; single quotes per surrounding file.
- **Forbidden in production path after this plan:** `import app.agent.*`, `import app.services.*` (allow-listed exceptions only, listed in tasks), `import app.modules.*`, `WorkflowProgress` artifact, `LEGACY_GATE_STAGES`, inline `<stage>_gate_decision` channel, `parse_contracts` re-exports, `app.api.v1.routes` (flat module), `app.api.human_review_routes`, `app.api.schemas`.
- **OpenAPI snapshot is NOT authoritative.** `docs/contracts/openapi-v1.json` is stale and may NOT be referenced as correctness. The live `app.openapi()` (from real routes) is the source of truth. Whenever contracts/API change, REGENERATE the snapshot from live routes in the same task and commit it.
- **适时调整 + 干净闭环 (adapt-to-need + clean closure).** Each migration task must inspect the moved object's actual responsibility against the blueprint §2.1 boundary. Where the old shape carries redundant fields, dual naming, or transition hacks, tighten it at the new home (drop redundant fields, rename, merge/split). Every task's commit MUST close the loop: all callers switched to the new home, the old definition deleted in the same task, no facade/compat re-export left behind. If the tightening is too large for one commit to close, split into "move unchanged + close" then "tighten" — but NEVER leave an intermediate dual-track state.
- Per-task gate: `pytest tests/e2e tests/core tests/contracts -o addopts="" -q` MUST stay green before the task's commit step.
- Blueprint §9 forbids long-term facades; each cut-over task MUST delete the corresponding `app/agent/<stage>/` directory in its final commit.
- Real-LLM acceptance (`tests/acceptance/test_real_graph_resume_delivery.py`) is NOT a per-task gate (needs MINIMAX key + 20+ min); run at end of Phase 2 and once at plan end.

## File Structure (target homes, locked here)

### `app/` after this plan (production-only):

```
api/v1/{routes/*, contracts/, dependencies.py, session_create.py}
application/{commands/*, queries/*, projections/*, unit_of_work.py, interrupts.py}
workflow/{root_graph.py, state.py, runtime_adapter.py, stage_adapter.py, routing.py, dispatch.py, terminal.py, stage_audit.py, stages/*}
domain/{assessment, objectives, program/{target_projection/}, demand, suitability, allocation, materialization, validation/{validate.py, reconcile.py}, delivery}
data/{model, ingestion, catalog, snapshots, ports}
spatial/{model, query, grounding, allocation, network, change, validation, delivery}
evidence/{model, retrieval, kg}
contracts/{artifacts, workflow, public/v1, ports}
infrastructure/{persistence, artifacts, events, checkpoints, llm, gis, kg, rag, search, rendering, export}
bootstrap/{composition.py, lifespan.py}
```

### Deleted dirs (across phases):
- `app/agent/` (Phase 2, stage-by-stage)
- `app/services/` (Phase 4)
- `app/modules/` (Phase 5)
- `app/core/` (split into `infrastructure/llm/` + `contracts/`)
- `app/database/` → `infrastructure/persistence/`
- `app/utils/` (split into `infrastructure/` + `spatial/`)
- `app/config/` → `bootstrap/`
- `app/api/{routes.py, human_review_routes.py, schemas.py}` (Phase 6)
- `app/tools/` → `infrastructure/{gis,rendering,rag}/` (folded in Phase 5)

---

## Phase 0 — Rebuild contract baseline

### Task 0.1: Regenerate OpenAPI snapshot from live routes (new baseline)

**Files:**
- Modify: `docs/contracts/openapi-v1.json` (regenerated; `sse-events-v1.schema.json` verified too)
- Test: `backend/tests/core/test_api_contract_snapshots.py`

**Interfaces:** Produces: `docs/contracts/openapi-v1.json` equals `app.openapi()`; both snapshot tests PASS.

- [ ] **Step 1:** Run `python -m pytest tests/core/test_api_contract_snapshots.py -o addopts="" -q` and capture the current diff to understand what changed in the live schema.
- [ ] **Step 2:** Regenerate the snapshot from live routes. The canonical way: build the same FastAPI app the test builds and dump `app.openapi()` to `docs/contracts/openapi-v1.json` (preserve key order/formatting of the JSON file as-is, e.g. via `json.dump(indent=2)` matching existing file style).
- [ ] **Step 3:** Verify `sse-events-v1.schema.json` still equals `TypeAdapter(PublicEvent).json_schema()`; regenerate if needed.
- [ ] **Step 4:** Run `python -m pytest tests/core/test_api_contract_snapshots.py -o addopts="" -q` → PASS.
- [ ] **Step 5:** Commit `chore: rebuild openapi snapshot baseline from live routes`.

**Baseline gate established:** `pytest tests/e2e tests/core tests/contracts -o addopts="" -q` green (expect 197 passed).

---

## Phase 1 — `workflow_progress` retirement (MIG-003 partial close)

> **ORDERING (REVISED):** Phase 1 runs AFTER Phase 2. `pack_workflow_patch` → `_persist_progress` is load-bearing for checkpoint resume: `services/runtime.py` (`aupdate_state`/`resume_from_interrupt`/`_execute_planning`) and the legacy stage nodes read stage-local keys (`current_stage`, `next_stage`, `paused_stage`, `deferral_summary`, `retry_counts`, etc.) out of the `WorkflowProgress.stage_payload` hydrated by `materialize_workflow_state`. Those keys are NOT reducer-projected into the compact `WorkflowState`. Deleting the carrier before the stages stop using it breaks resume — exactly the MIG-003 precondition "先拆成 typed stage artifacts，carrier 才能退役".

### Task 1.1: Forbid `WorkflowProgress` in production

**Files:**
- Create: `backend/tests/contracts/test_no_workflow_progress.py`
- Test: the new file

**Interfaces:** Produces: a contract test asserting no production module imports `WorkflowProgress` or `workflow_progress_contracts`.

- [ ] **Step 1:** Write failing test scanning `app/**/*.py` (excluding `tests/`) for `import`/`from` lines matching `WorkflowProgress` or `workflow_progress_contracts`.
- [ ] **Step 2:** Run → FAIL (imported by `runtime_adapter.py:90-102`).
- [ ] **Step 3:** Commit `test: forbid workflow_progress in production`.

### Task 1.2: Remove the legacy carrier from runtime_adapter

**Files:**
- Modify: `backend/app/workflow/runtime_adapter.py` (`materialize_workflow_state` `:76-114` drops the `artifact_refs["workflow_progress"]` hydration branch `:90-102`; delete `_persist_progress` `:117-149`; `pack_workflow_patch` `:188-195` no longer persists progress)
- Modify: `backend/app/infrastructure/artifacts/runtime.py` (drop `workflow_progress` from known artifact names, `:31`)
- Modify: `backend/app/tests/core/test_workflow_progress_contract.py` → repurpose to absence
- Test: `backend/tests/contracts/test_no_workflow_progress.py` (from 1.1)

**Interfaces:** Produces: `materialize_workflow_state` only reads `state["runtime"]` (Send payload) and top-level control keys; no `workflow_progress` artifact ever persisted.

- [ ] **Step 1:** Delete the hydration branch in `materialize_workflow_state`.
- [ ] **Step 2:** Delete `_persist_progress` and the progress-writing block in `pack_workflow_patch`.
- [ ] **Step 3:** Remove `workflow_progress` from known artifact names.
- [ ] **Step 4:** Repurpose `test_workflow_progress_contract.py` (or delete if covered by 1.1).
- [ ] **Step 5:** Fix any legacy `state.get("stage_payload", {})` reads in production nodes to read `WorkflowState` reducer keys directly (audit first).
- [ ] **Step 6:** Run full gate; fix breakages; commit `refactor(workflow): retire workflow_progress legacy carrier`.

---

## Phase 2 — Aggressive per-stage cut-over: `app.agent.<stage>` → `app.domain.<stage>` (+ inline gate → `gate_ref`)

### Reusable per-stage template (each task follows this)

For stage `S`:

- [ ] **Step 1 — Write failing architecture test** `backend/tests/contracts/test_no_agent_import_stage_S.py`:
```python
import pathlib, re
def test_stage_S_production_modules_have_no_app_agent_dependency():
    root = pathlib.Path("app")
    banned = re.compile(r"from app\.agent\.S\b|import app\.agent\.S\b")
    offenders = [
        p for p in root.rglob("*.py")
        if "tests" not in str(p) and banned.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"stage S still imports app.agent.S: {offenders}"
```
- [ ] **Step 2 — Run architecture test, expect FAIL.**
- [ ] **Step 3 — Move aggregate + gate into `app/domain/S/`.** Keep public function names identical.
- [ ] **Step 4 — Migrate inline gate to `gate_ref` CAS artifact** via `persist_gate_decision(state, stage="S", decision=...)` (helper at `workflow/stages/support.py:240`); drop raw `<S>_gate_decision` writes.
- [ ] **Step 5 — Update `workflow/stages/S.py` to import only from `app.domain.S`.**
- [ ] **Step 6 — Update `root_graph.py` gate mutation** (delete the `LEGACY_GATE_STAGES` branch once last user).
- [ ] **Step 7 — Delete `app/agent/S/` directory entirely.**
- [ ] **Step 8 — Run architecture test, expect PASS.**
- [ ] **Step 9 — Run full gate; do NOT revert Step 7.**
- [ ] **Step 10 — Commit:** `refactor(stage=S): migrate to domain and delete app.agent.S`.

**适时调整 rule applies in Step 3/4:** while moving, drop redundant fields, unify naming, and consolidate duplicate logic; keep the task's single commit fully closed (all callers switched, old def deleted).

### Task 2.1: RECONCILE
Create `app/domain/validation/reconcile.py` + `reconcile_gate.py`; modify `stages/reconcile.py`; delete `app/agent/reconcile/`. Run template 1→10.

### Task 2.2: DELIVER
Create `app/domain/delivery/{__init__.py, aggregate_service.py, snapshot_builder.py, renderer_ref.py, gate_service.py}`; move `app/agent/deliver/{aggregate,snapshot_builder,renderer,gate}.py`; move `delivery_exporter.py` → `infrastructure/export/`; modify `stages/deliver.py`; delete `app/agent/deliver/`. Run template 1→10. NOTE: keep `app/services/run_paths.py` import in renderer for now (Phase 4 fixes).

### Task 2.3: VALIDATE
Create `app/domain/validation/validate.py` + `validate_gate.py`; move `app/agent/validate/{aggregate,gate,checks,review}.py`; modify `stages/validate.py`; delete `app/agent/validate/`. `adjustment_executor.py` stays (autorepair production wiring is OUT of scope). Run template 1→10.

### Task 2.4: GROUND
Create `app/domain/ground/{__init__.py, aggregate_service.py, gate_service.py}`; move `app/agent/ground/{aggregate,gate,format_bound_intent}.py`; modify `stages/ground.py`; delete `app/agent/ground/`. Run template 1→10.

### Task 2.5: EXECUTE (heaviest — swap `_execute_subgraph`)
Create `app/domain/materialization/orchestrator.py` (`run_worker_graph(state, execution_plan_ref) -> ExecutionResult`) replacing `PlanningRuntimeService._execute_subgraph`; move `app/agent/execute/{execute_state,plan_builder,planned_state_builder,road_generator}.py` + `nodes/*` into `domain/materialization/` (consolidate with existing worker_contract workers); modify `stages/execute.py`; delete `app/agent/execute/`. Run template 1→10.

### Task 2.6: SELECT
Create `app/domain/allocation/select_service.py` (move `app.agent.select.aggregate.select_aggregate`) + `select_gate.py`; move `app.agent.execute.plan_builder` usage → `domain/materialization/plan_builder.py`; modify `stages/select.py`; delete `app/agent/select/`. Run template 1→10.

### Task 2.7: L3 / PROGRAM
Create `app/domain/program/aggregate_service.py` + `gate_service.py` (move `app.agent/l3_plan/{aggregate,gate}.py`, delegating to existing `assembler`/`classification`); delete `app/agent/l3_plan/`. Wire via `workflow/stages/l3.py` in Task 2.10.

### Task 2.8: L2 / OBJECTIVES
Create `app/domain/objectives/{__init__.py, aggregate_service.py, worker_service.py, gate_service.py}` (move `app/agent/l2_strategize/{worker,aggregate,gate}.py`); delete `app/agent/l2_strategize/`.

### Task 2.9: L1 / ASSESS
Create `app/domain/assessment/{__init__.py, dimension_worker.py, aggregate_service.py, gate_service.py, markdown_reader.py}` (move `app/agent/l1_observe/{analysis_node,aggregate,gate}.py` + `app/modules/parsing/compiler/core.compile_dimension_report`); delete `app/agent/l1_observe/`.

### Task 2.10: Wire L1/L2/L3 stage modules into root_graph
Create `app/workflow/stages/l1.py`, `l2.py`, `l3.py` thin adapters; modify `root_graph.py:7-17,616-618` to register `audited_stage("L1"/"L2"/"L3")` nodes; absorb `app/agent/bootstrap/{layer_router,phase_machine,context_bootstrap,layer_aggregate_node}.py` responsibilities into `workflow/`; delete `app/agent/bootstrap/`. Add `test_no_app_agent_import_in_root_graph.py`.

### Task 2.11: Remove `LEGACY_GATE_STAGES`
Modify `state.py` (delete frozenset + `load_root_gate` legacy branch), `root_graph.py` (delete `_gate_mutation_patch` legacy branch + `l1/l2/l3_gate_decision` reads/writes in HUMAN handlers). Add `test_only_gate_ref_in_state.py`.

### Task 2.12: Real-LLM acceptance sanity run
Inject MINIMAX key; run `tests/acceptance/test_real_graph_resume_delivery.py` with watchdog+log (NOT inline `Select-Object -Last`). Pipeline must reach DELIVER without raising. Record in `docs/audits/round-3/real-acceptance-post-cutover.md`.

---

## Phase 3 — Single artifact producer (root_graph HUMAN handlers)

### Task 3.1: Route HUMAN-review revisions through domain services
Modify `root_graph.py` `store_artifact(...)` calls on domain artifacts (`:548,1433,1543,1562,1569,1798,1848,1862`) to call domain services: `domain.program.assembler.assemble_planning_program` (revision), new `domain.delivery.deferral_ledger.apply_deferrals`, new `domain.allocation.revise_site_selection`, new `domain.materialization.revise_execution_plan`, new `domain.delivery.diagnostic_manifest.build_end_diagnostic_manifest`. Add `test_root_graph_writes_no_domain_typed_artifact.py`.

---

## Phase 4 — Collapse `app/services/*` into `application/` + `infrastructure/`

> **STORAGE DESIGN (REVISED per LangGraph official + exa practice):** Do NOT mechanically move `runtime.py`/`report_store.py`/`context/planning_context.py` into `infrastructure/`. Official LangGraph persistence model splits THREE layers:
> 1. **Checkpointer** = authoritative per-superstep state log (WAL analog). State schema rule: only routing fields + LLM-reasoning artifacts; large objects referenced by ID; single checkpoint >50KB → external store. Our `runtime` channel (promoted in Phase 1) is a MIGRATION vehicle, not the end-state — post-Phase-2 it should shrink as more keys become artifact refs/reducer channels.
> 2. **Application append-only store** = the UI/audit source of truth (never read by LLM, never from checkpointer). `report_store.py` (DimensionReport append-only table) IS this correct layer → `infrastructure/reports/`.
> 3. **Long-term memory** = cross-session `BaseStore` namespaces (future; not built here).
> Dependency direction: `workflow`/`domain` must NOT depend on `application` or on `services/runtime.py`. Current violation: `workflow/stages/execute.py:158,209,211,212` reads `PlanningRuntimeService._execute_subgraph` (private attr). FIX: EXECUTE subgraph is owned by `app/domain/materialization/execute_agent.py`; `execute.py` builds/calls it directly; delete `_execute_subgraph` from `PlanningRuntimeService`.

- **4.0** Delete `PlanningRuntimeService._execute_subgraph` + `_execute_agent` wiring in `services/runtime.py`; `workflow/stages/execute.py` builds the subgraph from `app/domain/materialization.execute_agent` directly (fixes workflow→application reverse dependency, official design).
- **4.1** Real `bootstrap/composition.py` (move `services/composition.py`; update importers; delete shim).
- **4.2** PlanningRuntime port split: create `application/ports/planning_runtime.py` protocol; move `services/runtime.py` → `infrastructure/runtime/planning_runtime_service.py`; wire `api/v1/dependencies.py` `get_planning_runtime` into routes that need it (`state.py`, `human_review.py`) — closes the dead `RuntimeDependency` gap.
- **4.3** `services/checkpoint*.py` → `infrastructure/checkpoints/`; `database/` → `infrastructure/persistence/`.
- **4.4** `services/run_paths.py` → `workflow/`; `artifact_fingerprint.py` → `infrastructure/artifacts/fingerprint.py`; `report_store.py` → `infrastructure/reports/`; `session*.py` → `application/sessions/`; `bundle_store.py` → `infrastructure/artifacts/`; `review_package.py` → `application/projections/`; `task_supervisor.py` → `infrastructure/tasks/`.
- **4.5** Eliminate dual resume planner: `application/commands/resume_checkpoint.py` is the owner; absorb `services/resume_service.py` helpers; delete `resume_service.py`.
- **4.6** Delete empty `app/services/`.

Each task: failing test `test_no_<old>_in_production` → move → fix imports → full gate → commit.

---

## Phase 5 — Fold `app/modules/*`, `app/tools/*`, `app/core/*`, `app/utils/*`, `app/config/*`

- **5.1** `modules/schema/contracts/` → `contracts/{artifacts,workflow,public/v1,ports}/` in batches of ~5, one commit each; forbid wildcard re-export in `contracts/__init__.py`.
- **5.2** `modules/ports/*` → `contracts/ports/` (interfaces) + `infrastructure/` (impl/adapters). Per port: `context_provider`, `gazetteer`, `planning_ports`, `road_planner`, `semantic_query`, `spatial_query`, `zone_allocator`, `bundle_assembly`.
- **5.3** `modules/spatial_ops/*` (57 files) → `spatial/*` (geometry, parcel_ops, index, conflict, grounding, allocation, road/network), `infrastructure/export/` (io/, output/), `spatial/allocation/zoning/` (zoning/). Batch by subdir.
- **5.4** `modules/kg/*` → `evidence/kg/` + `infrastructure/kg/` (builders to evidence, provider adapters to infra). Batch by subdir (`adapters`, `builder`, `enrichment`, `gazetteer`, `queries`).
- **5.5** `modules/rag/*` → `infrastructure/rag/`.
- **5.6** `modules/data/*` → `data/ingestion/` + `data/catalog/` + `infrastructure/` (provider adapters amap/baidu/tencent/tianditu → infra).
- **5.7** `modules/parsing/*` final removal: `tables.py` (`【INSTRUCTION】` extractor) moves to `evidence/retrieval/` if still needed after `agent/explore` move; delete rest of `modules/parsing/`.
- **5.8** `agent/explore/*` → `evidence/retrieval/` (per retriever batch).
- **5.9** `tools/` → `infrastructure/{gis,rendering,rag}/`; `tools/{helpers,intent_tools,registry,tools}.py` → `infrastructure/llm/tools/`.
- **5.10** `core/` → `infrastructure/llm/` + `contracts/` + `bootstrap/`; `utils/` → `infrastructure/events/` + `spatial/` + `infrastructure/logging.py`; `config/` → `bootstrap/`.
- **5.11** Delete `app/modules/`.

Each task: architecture test forbidding the module import → move in batches → fix imports → full gate → commit.

---

## Phase 6 — Dead-route and dead-file cleanup

- **6.1** Delete shadowed `app/api/v1/routes.py` (flat; package `routes/` wins). Verify `python -c "import app.api.v1; print(app.api.v1.router)"` before and after.
- **6.2** Delete orphaned `app/api/human_review_routes.py`; relocate `ResolveRequest`/`resolve_human_review` symbols into `app/api/v1/routes/human_review.py` or `application/commands/submit_human_review.py`; add `test_no_legacy_human_review_routes.py`.
- **6.3** Move `TaskStatus` out of `app/api/schemas.py` into its consumer or `application/projections/models.py`; delete `app/api/schemas.py`. Keep `api/v1/dependencies.py` (now wired by 4.2).

---

## Phase 7 — `ReportStore` / `summary` authoritativeness

- **7.1** L1 dimension-dependency reads typed `L1Snapshot` artifact (via `artifact_refs["l1_snapshot"]`), not `store.get_layer_summaries(session_id, 1)`. Test `test_l1_dependency_from_artifact.py`.
- **7.2** PlanningContext loads typed artifacts instead of `layer_summaries` (`planning_context.py:257-275`). Test `test_planning_context_from_artifacts.py`.
- **7.3** RAG index uses typed artifacts, not summary (`rag/service.py:269-276`). Test `test_rag_from_artifacts.py`.
- **7.4** Mark `DimensionReport.summary` UI-only: projection in `application/projections/`; add `contracts/public/v1/summary_projection.py`; test `test_no_summary_as_authoritative_input.py`.

---

## Phase 8 — `parse_contracts` retirement

- **8.1** Create `app/contracts/artifacts/intent.py` with `SpatialPlanningIntent`, `ProjectTarget`, `FacilityTarget`, `ZoneTarget`, `RoadTarget`, `AxisTarget`.
- **8.2** Repoint emitters (`stages/select.py`, `stages/execute.py`, `stages/validate.py`, `domain/program/target_projection/compile.py`, `execution_plan_contracts.py` cycle) to `app.contracts.artifacts.intent`; remove `PARSE` from `reconciliation_contracts.py:36` responsible_stage list; delete `parse_contracts.py`. Test `test_no_parse_contracts_import_in_production.py`.

---

## Phase 9 — Final architecture assertions + acceptance

- **9.1** Aggregate all forbidden-import tests into `tests/contracts/test_blueprint_architecture.py`: no `app.agent.*`, `app.services.*`, `app.modules.*`; no `WorkflowProgress`; no `LEGACY_GATE_STAGES`/inline gates; no `parse_contracts`; no summary reads outside projections; `root_graph.py` writes no domain artifacts.
- **9.2** Final real-LLM acceptance run (MINIMAX key injected, watchdog+log). Record in `docs/audits/round-3/convergence-complete.md`.

---

## Out of scope (per user's "Dual-fact cleanup only" choice, recorded for handoff)

- MIG-001 ClassificationDecision → ParcelChange (the "real run produces no ParcelChange" product gap).
- Frontend TypeScript type-check fix (P0 frontend).
- BoundedAdjustmentExecutor production wiring (autorepair loop).
- Multimodal production chain (ImageArtifact → ImageEvidence → VisualReview).
- Cross-process outbox / publisher (MIG-004).
- PlanningContext de-duplication / version binding.

## References

- Blueprint: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`
- Status ledger: `docs/design/10_IMPLEMENTATION_STATUS.md`
- Issue register: `docs/audits/backend-migration-issue-register-2026-08-12.md`
