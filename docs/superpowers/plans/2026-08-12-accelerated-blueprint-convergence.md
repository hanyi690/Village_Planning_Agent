# Accelerated Backend Blueprint Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task with a fresh implementer and a task-scoped review after each task.

**Goal:** Close the three highest-value migration gaps that currently prevent a real, inspectable backend result: custom zoning must produce parcel changes when an explicit classification decision exists, the road planner must be a replaceable typed worker adapter, and delivery map layers must expose stable metadata through `/api/v1`.

**Architecture:** Preserve the blueprint dependency direction and existing artifact owners. Add narrow adapters/materializers at the existing EXECUTE and Application boundaries; do not move business logic into `WorkflowState`, renderers, API routes, or the old EXECUTE graph assembler. The first task creates legal `ParcelChange` objects only from already-selected parcels and an explicit resolved `ClassificationDecision`; the second normalizes staged road output into the existing `WorkerResult` input shape; the third projects persisted `RenderLayers` metadata without recomputing spatial facts.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, Shapely, GeoJSON, pytest, existing CAS/artifact and `DeliverySpatialSnapshot` contracts.

## Global Constraints

- Dependency direction remains `API / SSE -> Application -> Workflow -> Domain -> Data / Spatial / Evidence ports <- Infrastructure adapters`.
- One business fact has one owner; downstream code reads immutable artifact refs.
- Workflow only orchestrates, routes, pauses, resumes, and persists refs; it does not implement planning algorithms.
- LLM output may provide claims or suggestions only; it must not directly create spatial facts, classifications, locations, `ParcelChange`, or execution tasks.
- `EXECUTE` may use only explicit, resolved classification decisions; it must not infer a legal code from a name, `dlbm`, vocabulary category, crosswalk, or first candidate.
- `DELIVER` outputs must come from one `DeliverySpatialSnapshot`; map layers, reports, HTML, PNG, GeoJSON, and manifest must not read separate planning truth.
- Missing or invalid classification, unavailable road inputs, unresolved geometry, and empty solver results remain typed `HUMAN`, `partial`, or `unresolved`; they must not become default success.
- Preserve existing user changes in `docs/` and `.codex/`; do not reset, checkout, or overwrite unrelated work.
- Use LF, two-space TypeScript indentation, four-space Python indentation, and single quotes in frontend code.

---

### Task 1: Materialize explicitly classified custom zones into `ParcelChangeSet`

**Files:**
- Modify: `backend/app/modules/schema/contracts/custom_zone_contracts.py`
- Create: `backend/app/modules/spatial_ops/zoning/custom_zone_changeset.py`
- Modify: `backend/app/agent/execute/plan_builder.py`
- Modify: `backend/app/workflow/stages/execute.py`
- Modify: `backend/app/agent/execute/nodes/zone_worker.py`
- Create: `backend/tests/core/test_custom_zone_changeset.py`

**Interfaces:**
- Consumes: `CustomZoneTarget`, `CustomZoningGenerator.generate_with_validation()`, `ClassificationDecision`, `parcel_by_bsm`, and existing `design_zone_parcel`/`ParcelChange` contracts.
- Produces: `materialize_custom_zone_changes(target, parcels, three_lines=None) -> CustomZoneMaterializationResult`, where the result contains `changes: list[ParcelChange]`, `unresolved_items: list[dict[str, object]]`, `diagnostics: list[dict[str, object]]`, and `audit: object | None`.
- Existing worker boundary: `_TASK_SPECS` must make `custom_zone_targets` dispatchable as the existing layout/zone task, the EXECUTE stage must pass the typed protection-line input into `ExecuteAgentState`, and `_zone_worker(state)` adds the returned changes and diagnostics to its existing `WorkerResult`; it must not change `execute_agent.py`, merge logic, or artifact persistence.

- [ ] **Step 1: Write failing contract tests for the legal boundary**

Create tests that construct a vocabulary with one category, two typed parcel geometries, and a `CustomZoneTarget` with explicit target BSMs. Cover these exact cases:

```python
def test_resolved_custom_zone_creates_reclassify_changes():
    result = materialize_custom_zone_changes(target_with_resolved_decision(), parcels)
    assert [change.bsm for change in result.changes] == ['P001', 'P002']
    assert all(change.action == 'reclassify' for change in result.changes)
    assert {change.after_classification.code for change in result.changes} == {'1207'}

def test_custom_category_never_becomes_legal_code_without_decision():
    result = materialize_custom_zone_changes(target_without_decision(), parcels)
    assert result.changes == []
    assert any(item['code'] == 'classification_unresolved' for item in result.unresolved_items)

def test_custom_zone_uses_generator_selection_and_preserves_audit():
    result = materialize_custom_zone_changes(target_with_resolved_decision_and_rules(), parcels)
    assert {change.bsm for change in result.changes} == {'P001'}
    assert result.audit is not None

def test_invalid_resolved_code_is_fail_closed():
    result = materialize_custom_zone_changes(target_with_invalid_decision(), parcels)
    assert result.changes == []
    assert any(item['code'] in {'classification_invalid', 'classification_unresolved'} for item in result.unresolved_items)
```

The tests must also assert that a protection-line-excluded parcel is absent from the changes, that `area_target_ha` uses the generator's final selected BSMs only, and that `before_geometry_wkt`/`after_geometry_wkt` are taken from the selected parcel geometry rather than invented.

- [ ] **Step 2: Run the focused tests and verify they fail for the missing materializer**

Run:

```powershell
python -m pytest backend/tests/core/test_custom_zone_changeset.py -q -o addopts=""
```

Expected: FAIL because the new materializer and explicit custom-zone execution path do not yet exist.

- [ ] **Step 3: Extend `CustomZoneTarget` without creating a second legal-classification model**

Add a stable `target_id: str` field with a deterministic default only at construction boundaries that currently lack one, and add `classification_decision: ClassificationDecision | None = None` using the existing canonical model. Keep `category_code` as custom vocabulary semantics; never treat it as a statutory code. Import the canonical classification type through the existing schema module and keep Pydantic forward references valid for `SpatialPlanningIntent`.

- [ ] **Step 4: Implement the narrow materializer**

Implement `custom_zone_changeset.py` so it:

1. Calls `CustomZoningGenerator(...).generate_with_validation()` to obtain selected zones and provenance audit.
2. Matches each generated zone back to its target by `pln:category_code` and selected `pln:target_bsms`.
3. Requires `target.classification_decision.status == 'resolved'` and validates it through the same registry/helper used by `land_design_worker`; it never maps `category_code`, category name, `dlbm`, or a crosswalk to a legal code.
4. Creates one `ParcelChange(action='reclassify')` per selected BSM, with `source_bsms=[bsm]`, stable `target_id`, source geometry as both before/after geometry unless an existing typed operation supplies another geometry, and the decision's canonical classification as `after_classification`.
5. Returns typed unresolved diagnostics for missing target, invalid decision, missing BSM, invalid geometry, or generator output with no selected parcels.
6. Preserves the generator audit in the result and does not re-add protection-line-excluded parcels.

The production EXECUTE boundary must normalize the existing protection-line input into the generator's subtype mapping. If protection-line input is present but malformed or not available for a custom target, return a target-scoped unresolved diagnostic instead of treating it as an empty constraint set.

- [ ] **Step 5: Make custom-zone targets reachable and switch only the custom-zone branch in `_zone_worker`**

Add `custom_zone_targets` to the existing execution-plan task specification with the same explicit-target and classification gate used for zone work; do not create a second worker type or silently schedule an unresolved target. Then replace the unconditional `custom_zone_deferred` block with a call to the materializer. Append its changes to `zone_changes`, its unresolved items to the worker result, and a diagnostic containing the number of materialized custom-zone changes. Custom targets without resolved decisions must remain unresolved and must not make the worker succeed.

Before empty ordinary-zone MIP allocation, reserve every explicit custom target BSM and every BSM selected by rules/area-driven custom zoning. If a BSM is claimed by both an ordinary zone and a custom target, emit a target-scoped overlap diagnostic and do not emit duplicate changes.

Invalid persisted custom target bindings must become target-scoped unresolved/task failure; never catch-and-continue them out of the result.

- [ ] **Step 6: Run focused, boundary, and delivery regression tests**

Run:

```powershell
python -m pytest backend/tests/core/test_custom_zone_changeset.py backend/tests/core/test_execute_classification_boundary.py backend/tests/core/test_spatial_delivery_io.py -q -o addopts=""
```

Expected: all selected tests pass; existing ordinary-zone behavior remains unchanged; at least one custom-zone fixture reaches a non-empty `ParcelChangeSet` and a planned feature with `change_status='modified'`.

- [ ] **Step 7: Commit the task**

```powershell
git add backend/app/modules/schema/contracts/custom_zone_contracts.py backend/app/modules/spatial_ops/zoning/custom_zone_changeset.py backend/app/agent/execute/plan_builder.py backend/app/workflow/stages/execute.py backend/app/agent/execute/nodes/zone_worker.py backend/tests/core/test_custom_zone_changeset.py
git commit -m "feat: materialize classified custom zones"
```

### Task 2: Make the staged road planner a typed, replaceable worker adapter

**Files:**
- Modify: `backend/app/modules/ports/road_planner.py`
- Create: `backend/app/modules/spatial_ops/road/port_adapter.py`
- Modify: `backend/app/services/context/planning_context.py`
- Modify: `backend/app/workflow/stages/execute.py`
- Modify: `backend/app/agent/execute/nodes/road_worker.py`
- Create: `backend/tests/core/test_road_planner_port_contract.py`

**Interfaces:**
- Consumes: `PlanningPorts.road_planner`, existing `_road_worker(state)` expectations, staged `RoadPlanningConfig`/`run_stage4_road_planning`, and GeoJSON result paths.
- Produces: `RoadPlanResult` with `layers: list[dict[str, object]]`, `unresolved_items: list[dict[str, object]]`, and `diagnostics: list[dict[str, object]]`; `StagedRoadPlannerAdapter.is_available() -> bool` and `plan(state) -> RoadPlanResult`.
- The adapter must be injected into `PlanningPorts`, passed from the planning context into `ExecuteAgentState`, and be the only formal road-planning call from `_road_worker`; it must never expose `RoadPlanningResult` path internals to the port consumer.

- [ ] **Step 1: Write failing port tests**

Cover unavailable inputs, formal planned-road output with target provenance, blocked/empty Stage 4 output, and multiple road targets. The multiple-target test must prove that a layer without matching `target_id` is unresolved rather than claimed by every target.

```python
def test_unavailable_adapter_returns_typed_unresolved_without_running_stage4():
    adapter = StagedRoadPlannerAdapter(state=state_without_roads())
    assert adapter.is_available() is False
    result = adapter.plan(state_without_roads())
    assert result.layers == []
    assert result.unresolved_items[0]['code'] == 'road_unresolved'

def test_formal_planned_road_layer_keeps_target_provenance(monkeypatch):
    monkeypatch.setattr(..., 'run_stage4_road_planning', fake_stage4_result)
    result = StagedRoadPlannerAdapter(...).plan(state_with_two_targets())
    assert result.layers[0]['layerType'] == 'planned_road'
    assert result.layers[0]['data']['features'][0]['properties']['target_id'] == 'road-1'
```

- [ ] **Step 2: Run the focused tests and verify the adapter is missing**

```powershell
python -m pytest backend/tests/core/test_road_planner_port_contract.py -q -o addopts=""
```

Expected: FAIL because `RoadPlanResult` and `StagedRoadPlannerAdapter` are not defined.

- [ ] **Step 3: Define the narrow port result and adapter**

Use Pydantic or frozen dataclasses consistent with nearby port contracts. `StagedRoadPlannerAdapter` must validate that inputs are available before invoking Stage 4, normalize path-backed GeoJSON into `planned_road` layers, strip CRS metadata only at the existing worker boundary, preserve `target_id`/`source_project_id` provenance, and turn blocked requests, missing files, empty formal layers, and exceptions into `road_unresolved` diagnostics. Candidate/evaluation-only layers must not be reported as formal success.

- [ ] **Step 4: Inject the adapter through the real EXECUTE path**

Construct `StagedRoadPlannerAdapter` in the existing planning-context factory when the snapshot has the required road inputs, assign it to `PlanningPorts.road_planner`, and pass `context.ports` into `ExecuteAgentState` at the existing EXECUTE stage boundary. Add a test that a real `ExecuteAgentState` receives the adapter instead of `None` for a fixture with roads.

- [ ] **Step 5: Make the worker port-only for formal road output**

Remove the direct `road_generator` production branch from `_road_worker` or move it entirely behind the adapter; the worker must report an unresolved `WorkerResult` when no injected port is available. Candidate/evaluation layers are diagnostics only and can never make a target succeed. Do not edit `execute_agent.py`, `merge.py`, or the root workflow graph.

- [ ] **Step 5: Run road and execution boundary regressions**

```powershell
python -m pytest backend/tests/core/test_road_planner_port_contract.py backend/tests/core/test_execute_classification_boundary.py backend/tests/core/test_execution_result_architecture.py -q -o addopts=""
```

Expected: all selected tests pass, a two-target fake result cannot silently mark both targets as succeeded, and the real EXECUTE state receives the typed adapter.

- [ ] **Step 6: Commit the task**

```powershell
git add backend/app/modules/ports/road_planner.py backend/app/modules/spatial_ops/road/port_adapter.py backend/app/services/context/planning_context.py backend/app/workflow/stages/execute.py backend/app/agent/execute/nodes/road_worker.py backend/tests/core/test_road_planner_port_contract.py
git commit -m "feat: type staged road planner port"
```

### Task 3: Expose stable delivery map-layer metadata and refresh the API contract snapshot

**Files:**
- Modify: `backend/app/application/projections/models.py`
- Modify: `backend/app/application/projections/delivery.py`
- Create: `backend/tests/core/test_delivery_projection_contract.py`
- Modify: `docs/contracts/openapi-v1.json`

**Interfaces:**
- Consumes: persisted `DeliverySpatialSnapshot` and `RenderLayers` artifacts through `delivery_projections.map_layers()`.
- Produces: public map-layer views with stable `layer_id`, `layer_type`, `layer_name`, `feature_count`, `geojson`, `style`, `legend`, `default_visible`, and the source snapshot checksum already owned by the delivery artifact.
- The route remains `GET /api/v1/sessions/{session_id}/map-layers`; no route may read runtime, renderer, report store, or raw GIS.

- [ ] **Step 1: Write failing projection tests**

Use a fake persisted `RenderLayers` artifact containing `current_landuse`, `complete_planned_landuse`, `planned_project_point`, `facility_point`, and `planned_road`. Assert every output layer has a unique non-empty `layer_id`; styles, legend metadata, visibility, feature counts, and point properties (`project_ref`, `target_id`, `name`, `provenance`) survive projection; and the collection points at the same snapshot checksum as delivery.

Also add a regression assertion that the current OpenAPI snapshot differs before regeneration, because the current baseline fails `test_openapi_v1_snapshot_is_current`.

- [ ] **Step 2: Run the focused projection tests and confirm the missing fields**

```powershell
python -m pytest backend/tests/core/test_delivery_projection_contract.py backend/tests/core/test_api_contract_snapshots.py -q -o addopts=""
```

Expected: projection tests fail on missing metadata, and the existing OpenAPI snapshot test fails with the current route/schema mismatch.

- [ ] **Step 3: Extend the public projection models**

Add strict fields to the existing public DTOs with backward-compatible optional defaults only where an internal layer genuinely lacks metadata. `layer_id` must be stable and unique within one collection; derive it from the canonical internal `layerType`/`layer_type`, not from array position alone. Preserve GeoJSON properties as-is rather than creating a duplicated feature index. Keep snapshot checksum semantics explicit and unchanged.

- [ ] **Step 4: Project metadata without recomputing spatial facts**

Update `_layer_view()` and `map_layers()` to read existing style/color/default visibility/legend/provenance fields from the persisted artifact. If a layer has no legend field, expose an empty legend or the canonical layer metadata already present in that artifact; do not recreate classification colors or query `PlannedState`. Keep missing-artifact behavior fail-closed with the existing 404 projection errors.

- [ ] **Step 5: Regenerate the checked-in OpenAPI snapshot from the current router**

Use the repository's existing snapshot generation command or a one-shot Python command that imports `router`, calls `FastAPI(...).openapi()`, and writes `docs/contracts/openapi-v1.json` with stable sorted JSON formatting. Do not manually delete paths or change route behavior to satisfy the snapshot. Verify that the snapshot test passes.

- [ ] **Step 6: Run projection, render, and API regression tests**

```powershell
python -m pytest backend/tests/core/test_delivery_projection_contract.py backend/tests/core/test_api_contract_snapshots.py backend/tests/core/test_complete_delivery_outputs.py backend/tests/core/test_delivery_render_quality.py -q -o addopts=""
```

Expected: all selected tests pass; persisted map layers expose road/project/facility metadata; renderer tests still prove two-panel PNG generation and delivery quality; no API route reads internal runtime state.

- [ ] **Step 7: Commit the task**

```powershell
git add backend/app/application/projections/models.py backend/app/application/projections/delivery.py backend/tests/core/test_delivery_projection_contract.py docs/contracts/openapi-v1.json
git commit -m "feat: expose stable delivery layer metadata"
```

### Whole-slice verification and gap review

- [ ] Run the full non-E2E regression without the repository's default marker filter:

```powershell
python -m pytest backend/tests/contracts backend/tests/core backend/tests/e2e -q -o addopts="" --maxfail=1
```

- [ ] Run the focused delivery rendering verification against a fresh temporary output directory and inspect actual files:

```powershell
python -m pytest backend/tests/core/test_delivery_render_quality.py backend/tests/core/test_spatial_delivery_io.py -q -o addopts=""
```

Record counts for `ParcelChangeSet`, `complete_planned_landuse`, `planned_road`, `function_zone`, `planned_project_point`, and `facility_point`; read the generated GeoJSON and HTML; render/read the two-panel PNG. A zero-change result remains `partial`, not success.

- [ ] Re-run the targeted code-only graphify updates for `backend/app/domain`, `backend/app/workflow`, `backend/app/modules/spatial_ops`, `backend/app/application`, and `backend/app/api`; retain the generated graphs as audit artifacts.

- [ ] Update `docs/design/10_IMPLEMENTATION_STATUS.md` and `docs/audits/backend-migration-issue-register-2026-08-12.md` only with evidence from commands or a new real run. Do not close the real MiniMax acceptance gap unless a new checkpoint reopen/resume produces non-zero legal parcel changes and the output files are read.
