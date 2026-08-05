# Wave M1 Implementation Plan: Post-L3 Subgraph Chain Wiring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy `gis_agent_node` internals (which call `build_layout_pipeline()`, a 1165-line monolith collapsing PARSE+KG+EXECUTE+EXPORT+RENDER) with a new post-L3 chain that wires the Wave B-L subgraphs in sequence: PARSE -> GROUND -> SELECT -> EXECUTE -> VALIDATE -> RECONCILE -> DELIVER. Fix the `kg->data` reverse dependency (1 lazy import in `kg/service.py:46`) by adding a `BundleAssemblyPort`. Fix the 2 pre-existing `catalog_session_context` test failures. Add `"DELIVER"`/`"RECONCILE"`/`"VALIDATE"` to `StepReport.VALID_STAGES`. Keep the conversation router, L1/L2/L3 dimension workers, and `analyze_dimension` legacy worker unchanged (M2 scope). Conservative State trimming: add new fields, deprecate old.

**Architecture:** The new `gis_agent_node` becomes a thin orchestrator that: (1) builds `PlanningContext` via the existing factory, (2) invokes the new `build_post_l3_chain()` sub-graph, (3) writes results to State. The post-L3 chain is a `StateGraph(PostL3ChainState)` with 7 nodes: `parse` -> `ground` -> `select` -> `execute` -> `validate` -> `reconcile` -> `deliver` -> END. Each node wraps the corresponding `*_aggregate` function, pulling inputs from `PostL3ChainState` (which carries typed artifact references, not raw dicts). The EXECUTE node reuses the existing `build_execute_agent_graph()` sub-graph (unchanged). The VALIDATE node replaces the execute-internal `_validate_node` with a call to `validate_aggregate`. RECONCILE and DELIVER are new nodes after EXECUTE. The `kg->data` fix: add `BundleAssemblyPort` Protocol to `ports/`, implement in data layer, inject via `PlanningPorts`, consume in `kg/service.py` (replace lazy import). Delete `layout_pipeline.py` (1165 lines) and `parse_agent.py` (826 lines) after migrating the 2 helpers they still need (`_extract_instruction_tables` -> `app/modules/parsing/tables.py`, `_build_trace_layer` -> `app/modules/spatial_ops/map_layers.py`). Update `gis_test_routes.py` to use the new PARSE API. Main graph topology (`bootstrap/graph.py`) stays 6-node; only `gis_agent_node` internals change.

**Tech Stack:** Python 3.11, Pydantic v2, LangGraph, pytest. Tests run from `backend/`.

## Global Constraints
- LF line endings, 4-space indent, double quotes, no trailing whitespace
- Tests run from `backend/` (i.e. `python -m pytest tests/unit/ -q`)
- Do NOT commit pre-existing uncommitted files under `docs/`
- Additive contracts: do NOT delete existing fields
- `app/agent/deliver/` and all subgraph dirs must remain zero `advisory_crosswalks` imports
- Keep conversation router (`conversation_router/`) and L1/L2/L3 workers (`l1_observe/analysis_node.py`, `l2_strategize/worker.py`, `l3_plan/worker.py`) UNCHANGED (M2 scope)
- Keep `bootstrap/graph.py` 6-node topology UNCHANGED (only `gis_agent_node` internals change)
- Conservative State: add new fields to `AgentState`, deprecate (don't delete) legacy `gis_*` fields
- Reference `spatial_ops/land_balance.check_delivery_gate` - do NOT absorb
- Reference `spatial_ops/export_package.export_gdb_package` - do NOT modify
- Branch: `refactor/phase1-planning-context` (continuing after Wave L)

---

### Task 1: BundleAssemblyPort + kg->data fix

**Files:**
- Create: `backend/app/modules/ports/bundle_assembly.py`
- Modify: `backend/app/modules/ports/planning_ports.py` (add `bundle_assembly` field)
- Modify: `backend/app/modules/kg/service.py` (replace lazy import with port injection)
- Create: `backend/app/modules/data/bundle_assembly_adapter.py` (port implementation)
- Modify: `backend/app/services/context/planning_context.py` (wire adapter into PlanningPorts)
- Create: `backend/tests/unit/ports/test_bundle_assembly_port.py`

**Interfaces:**
- `BundleAssemblyPort(Protocol)`: `merge_geojson_into_bundle(bundle, layer_key, geojson) -> int`
- `DataBundleAssemblyAdapter`: wraps `catalog._merge_geojson_into_bundle`
- `PlanningPorts.bundle_assembly: BundleAssemblyPort | None = None`
- `kg/service.py:build_kg()` accepts `ports: PlanningPorts | None = None`; if `bundle is None`, uses `ports.bundle_assembly` instead of lazy import

- [ ] **Step 1: Write failing test** - `test_bundle_assembly_port_protocol`, `test_kg_service_uses_port_not_data_import` (AST-verify `service.py` has no `from app.modules.data` import)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** port + adapter + inject into PlanningPorts + update service.py
- [ ] **Step 4: Run test to verify it passes** + `test_architecture_invariants.py` patterns0 now PASSES
- [ ] **Step 5: Commit**: `feat(wave-m1): BundleAssemblyPort eliminates kg->data reverse dependency`

---

### Task 2: Fix catalog_session_context failures

**Files:**
- Modify: `backend/app/modules/data/catalog/catalog.py` (fix `upload_roads` layer type)
- Modify: `backend/tests/unit/test_catalog_session_context.py` (fix stale `fake_populate` signature)

**Interfaces:**
- Fix 1: `_merge_geojson_into_bundle` or `_infer_layer_key_from_upload` should recognize `upload_roads` -> route to `current_road` (add alias)
- Fix 2: `test_load_village_bundle_async_calls_sync_and_populate` - update `fake_populate(bundle, session_id)` to accept `uploaded_gis=None` kwarg

- [ ] **Step 1: Write/fix test** - update `fake_populate` signature; verify `upload_roads` routes correctly
- [ ] **Step 2: Run test to verify current state**
- [ ] **Step 3: Implement** alias fix + test fix
- [ ] **Step 4: Run test to verify it passes** + all 6 catalog tests pass
- [ ] **Step 5: Commit**: `fix(wave-m1): catalog_session_context upload_roads alias + stale test stub`

---

### Task 3: PostL3ChainState contract

**Files:**
- Create: `backend/app/agent/bootstrap/post_l3_state.py`
- Create: `backend/tests/unit/bootstrap/test_post_l3_state.py`

**Interfaces:**
- `PostL3ChainState(BaseModel)`:
  - Identity: `session_id: str`, `village_name: str`, `run_id: str`
  - Context: `context: Any` (PlanningContext, not serialized), `context_version: str`
  - L3 input: `planning_program: Any` (PlanningProgram), `l3_program_ref: dict | None`
  - PARSE output: `intent: Any`, `specs: list[Any]`, `parse_gate: Any | None`
  - GROUND output: `grounding_result: Any`, `ground_gate: Any | None`
  - SELECT output: `site_selection: Any`, `land_design_briefs: list[Any]`, `select_gate: Any | None`
  - EXECUTE output: `planned_state: Any`, `parcel_changeset: Any`, `layout_configs: list[dict]`, `allocated_geojson: dict`, `execution_errors: list[dict]`
  - VALIDATE output: `validation_report: Any`, `validate_gate: Any | None`
  - RECONCILE output: `reconciliation_report: Any`, `reconcile_gate: Any | None`
  - DELIVER output: `delivery_manifest: Any`, `deliver_gate: Any | None`, `export_result: dict | None`
  - Upstream gates: `upstream_gates: list[Any]` (accumulated for DELIVER)
  - Messages: `messages: list[Any]`

- [ ] **Step 1: Write failing test** - construct PostL3ChainState with all fields, verify defaults
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** state contract
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-m1): PostL3ChainState contract for post-L3 chain`

---

### Task 4: Post-L3 chain nodes (PARSE + GROUND + SELECT)

**Files:**
- Create: `backend/app/agent/bootstrap/post_l3_nodes.py` (parse_node, ground_node, select_node)
- Create: `backend/tests/unit/bootstrap/test_post_l3_nodes_parse_ground_select.py`

**Interfaces:**
- `async def parse_node(state: PostL3ChainState) -> dict` - calls `compile_program(program, ...)` from `app.agent.parse`; writes `intent`, `specs`, `parse_gate`
- `async def ground_node(state: PostL3ChainState) -> dict` - calls `ground_aggregate(specs, context)`; writes `grounding_result`, `ground_gate`
- `async def select_node(state: PostL3ChainState) -> dict` - calls `select_aggregate(grounding_result, intent, context)`; writes `site_selection`, `land_design_briefs`, `select_gate`

- [ ] **Step 1: Write failing test** - each node with mock inputs produces correct outputs
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** 3 node functions
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-m1): post-L3 chain nodes (parse/ground/select)`

---

### Task 5: Post-L3 chain nodes (EXECUTE + VALIDATE + RECONCILE + DELIVER)

**Files:**
- Modify: `backend/app/agent/bootstrap/post_l3_nodes.py` (add execute_node, validate_node, reconcile_node, deliver_node)
- Create: `backend/tests/unit/bootstrap/test_post_l3_nodes_execute_validate_reconcile_deliver.py`

**Interfaces:**
- `async def execute_node(state: PostL3ChainState) -> dict` - builds `ExecuteAgentState` from chain state + context, invokes `build_execute_agent_graph()`, extracts `planned_state` (via `changeset_to_planned_state`), `parcel_changeset`, `layout_configs`
- `async def validate_node(state: PostL3ChainState) -> dict` - calls `validate_aggregate(planned_state, changeset, layout_configs, intent, context.constraint_index, run_id)`; writes `validation_report`, `validate_gate`
- `async def reconcile_node(state: PostL3ChainState) -> dict` - calls `reconcile_aggregate(program, specs, grounding_result, site_selection, changeset, planned_state, intent, run_id)`; writes `reconciliation_report`, `reconcile_gate`
- `async def deliver_node(state: PostL3ChainState) -> dict` - calls `export_gdb_package(...)` for export_result, calls `deliver_aggregate(planned_state, validation_report, reconciliation_report, upstream_gates, export_result, current_parcels, run_id)`; writes `delivery_manifest`, `deliver_gate`, `export_result`. Optionally calls `render_map_preview` + `render_interactive_map` for render artifacts.

- [ ] **Step 1: Write failing test** - each node with mock inputs
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** 4 node functions
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-m1): post-L3 chain nodes (execute/validate/reconcile/deliver)`

---

### Task 6: build_post_l3_chain() graph factory

**Files:**
- Create: `backend/app/agent/bootstrap/post_l3_chain.py` (`build_post_l3_chain`)
- Create: `backend/tests/unit/bootstrap/test_post_l3_chain.py`

**Interfaces:**
- `def build_post_l3_chain() -> compiled StateGraph(PostL3ChainState)`
- Topology: `START -> parse -> ground -> select -> execute -> validate -> reconcile -> deliver -> END`
- Gate-driven conditional edges (simplified for M1 - gates log route but don't loop back yet):
  - parse_gate HUMAN -> END (log)
  - ground_gate HUMAN -> END (log)
  - select_gate HUMAN -> END (log)
  - validate_gate HUMAN -> END (log)
  - reconcile_gate HUMAN -> END (log)
  - deliver_gate RETRY_VALIDATE -> END (log, no loop in M1)
  - deliver_gate HUMAN -> END (log)
- All PASS routes continue linearly

- [ ] **Step 1: Write failing test** - chain compiles, linear pass produces DeliveryManifest
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** graph factory
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-m1): build_post_l3_chain graph factory`

---

### Task 7: Rewrite gis_agent_node to use post-L3 chain

**Files:**
- Modify: `backend/app/agent/bootstrap/gis_agent_entry.py` (rewrite `gis_agent_node` to invoke `build_post_l3_chain()` instead of `build_layout_pipeline()`)
- Modify: `backend/app/services/step_report.py` (add `DELIVER`, `RECONCILE`, `VALIDATE` to `VALID_STAGES`)
- Create: `backend/tests/unit/bootstrap/test_gis_agent_entry.py`

**Interfaces:**
- `gis_agent_node` new flow: build PlanningContext -> build PostL3ChainState from context + L3 reports -> invoke `build_post_l3_chain().ainvoke(state)` -> extract delivery_manifest + render artifacts -> write to AgentState
- Keep SSE publishing (gis_result event)
- Keep `_gis_error_handler` unchanged
- Migrate `_extract_instruction_tables` usage: use `app.modules.parsing.tables` (or inline)
- Migrate `_build_trace_layer`: move to `spatial_ops/map_layers.py` or inline in deliver node

- [ ] **Step 1: Write failing test** - `gis_agent_node` with mock context produces delivery_manifest on state
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** rewrite + StepReport stages
- [ ] **Step 4: Run test to verify it passes** + existing execute tests no regression
- [ ] **Step 5: Commit**: `feat(wave-m1): rewrite gis_agent_node to use post-L3 chain`

---

### Task 8: Migrate helpers + delete legacy code

**Files:**
- Move: `_extract_instruction_tables` from `parse_agent.py` -> `backend/app/modules/parsing/tables.py` (or shared module)
- Move: `_build_trace_layer` from `layout_pipeline.py` -> `backend/app/modules/spatial_ops/map_layers.py`
- Modify: `backend/app/api/gis_test_routes.py` (update `parse_async` import to new PARSE API or mark as deprecated)
- Modify: `backend/app/agent/explore/agent.py` (update `_extract_instruction_tables` import)
- Modify: `backend/app/agent/execute/vocab_extractor.py` (update import)
- Delete: `backend/app/agent/select/parse_agent.py` (826 lines)
- Delete: `backend/app/agent/execute/layout_pipeline.py` (1165 lines)
- Delete: `backend/app/agent/select/parse_state.py`, `parse_fallback.py`, `prompts.py` (if present)
- Update: `backend/tests/unit/test_gis_output_contract.py` (rewrite or delete tests referencing deleted modules)

**Interfaces:**
- `app.modules.parsing.tables.extract_instruction_tables(text) -> list[dict]` (public API)
- `app.modules.spatial_ops.map_layers.build_trace_layer(gis_data, explore_instructions) -> dict | None` (public API)
- `gis_test_routes._resolve_intent_via_parse` -> use new `compile_program` or mark deprecated

- [ ] **Step 1: Write failing test** - verify migrated helpers work at new locations
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** migration + deletions + import updates
- [ ] **Step 4: Run test to verify it passes** + `test_gis_output_contract.py` updated + full suite
- [ ] **Step 5: Commit**: `refactor(wave-m1): delete legacy parse_agent + layout_pipeline, migrate helpers`

---

### Task 9: AgentState conservative additions

**Files:**
- Modify: `backend/app/agent/plan_state/state.py` (add new fields, deprecate old)
- Create: `backend/tests/unit/test_agent_state_wave_m_fields.py`

**Interfaces:**
- Add: `delivery_manifest: Optional[Any] = None` (typed DeliveryManifest from DELIVER)
- Add: `reconciliation_report_ref: Optional[Any] = None` (typed ReconciliationReport)
- Add: `validation_report_ref: Optional[Any] = None` (typed ValidationReport)
- Add: `pending_requests: Annotated[List[Dict], _replace_or_merge_lists]` (accumulated gate pending requests)
- Add: `context_version: str = ""` (PlanningContext version stamp)
- Deprecate (comment, don't delete): `gis_layout_configs`, `gis_export_result`, `gis_render_result`, `gis_render_artifact`, `gis_validation_result`, `gis_execution_errors`, `gis_conflict_result` -> add `# DEPRECATED Wave M1: use delivery_manifest`

- [ ] **Step 1: Write failing test** - new fields default correctly; old fields still accessible
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** state additions
- [ ] **Step 4: Run test to verify it passes** + plan_state tests no regression
- [ ] **Step 5: Commit**: `feat(wave-m1): conservative AgentState additions (delivery_manifest, pending_requests, context_version)`

---

### Task 10: Guardrails + full verification

**Files:**
- Create: `backend/tests/unit/bootstrap/test_no_advisory_crosswalks.py` (guardrail for `app/agent/bootstrap/`)
- Modify: `backend/tests/unit/test_no_advisory_crosswalk_imports.py` (add `app/agent/bootstrap` to forbidden_dirs if needed)

**Interfaces:**
- AST scan: `app/agent/bootstrap/*.py` must NOT import `advisory_crosswalks`
- sys.modules snapshot: importing `app.agent.bootstrap` must not load advisory_crosswalks
- Verify: `test_architecture_invariants.py` ALL 8 pass (kg->data fixed)
- Verify: `test_catalog_session_context.py` ALL 6 pass (both fixes applied)
- Verify: full suite 1218+ pass, 0 pre-existing failures remain

- [ ] **Step 1: Write guardrail test** (mirror execute pattern)
- [ ] **Step 2: Run test to verify it runs** (should be green - no violations)
- [ ] **Step 3: Implement** guardrail
- [ ] **Step 4: Run full suite** - verify 0 pre-existing failures + zero new regressions
- [ ] **Step 5: Commit**: `test(wave-m1): guardrails + full verification (0 pre-existing failures)`

---

### Task 11: Docs sync (uncommitted)

**Files:**
- Modify: `docs/design/10_IMPLEMENTATION_STATUS.md` (add Wave M1 row; update Delivery Gate, PlannedState, import boundary rows)
- Modify: `docs/weekly-reports/2026-08-04-wave-roadmap.md` (add Wave M1 delivery note)

- [ ] **Step 1: Update `10_IMPLEMENTATION_STATUS.md`** - M1 row + status updates
- [ ] **Step 2: Update `2026-08-04-wave-roadmap.md`** - Wave M1 delivery summary
- [ ] **Step 3: Verify git status** - docs changes remain uncommitted
- [ ] **No commit** (docs rule)

---

## Verification
- Post-L3 chain: all new tests pass
- Full suite: 1218+ pass, **0 pre-existing failures** (kg->data fixed, catalog tests fixed)
- Guardrails: `app/agent/bootstrap/` zero advisory_crosswalks imports
- `test_architecture_invariants.py`: ALL 8 pass (including patterns0 kg->data)
- Legacy deleted: `parse_agent.py` (826 lines) + `layout_pipeline.py` (1165 lines) = ~2000 lines removed
- Main graph topology unchanged (6 nodes); only `gis_agent_node` internals replaced
- Conversation router + L1/L2/L3 workers unchanged (M2 scope)

## Out of scope (deferred to M2)
- Wiring `l1_aggregate` / `l2_aggregate` / `l3_aggregate` as post-layer-completion nodes
- Replacing legacy `analyze_dimension` with layer-specific workers
- Gate-driven retry loops (M1 logs HUMAN routes but doesn't loop back)
- Deleting legacy `gis_*` AgentState fields (conservative: deprecated, not deleted)
- Replacing `explore_node` with GROUND subgraph (EXPLORE stays as L3->bridge)
- `Graphify 依赖图` review package artifact (post-M1 verification)
- Consolidating revision cascade fields into `human_review` substructure
