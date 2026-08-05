# Wave I Implementation Plan: EXECUTE Subgraph

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Land Design Worker that consumes `SiteSelectionDecision + LandDesignBrief` and produces project polygon outlines (项目轮廓) + a unified `ParcelChangeSet`; make Zone/Facility workers decision-driven (deterministic parcel reclassification, no MIP/current-state); delete the 8 EXECUTE-chain advisory_crosswalks violations atomically; add an EXECUTE review package with before/after comparison.

**Architecture:** Reuse the existing pure-Shapely `parcel_ops.py` (`reclassify_parcel`/`merge_parcels`/`split_parcel_by_geometry`/`create_parcel`/`apply_operations` — all with `derived_from_bsms` lineage, no advisory_crosswalks) as the foundation. The new `app/agent/execute/land_design_worker.py` orchestrates parcel changes for projects/zones/facilities, producing a unified `ParcelChangeSet` (contract already defined in `parcel_change_contracts.py` with `area_conservation_verified`/`geometry_validity_verified`). A `planned_state_builder.py` converts `ParcelChangeSet -> PlannedState` (replacing the raw-GeoJSON `_layout_configs_to_planned_state` path). Rewrite `_execute_project_node` (polygon footprint instead of Point), `_execute_layout_node` (deterministic zone reclassify instead of 2x MIP solve), `_execute_facility_node` (decision-driven instead of KG POI lookup). Then atomically delete the 8 `LEGACY_GATED_FILES` (mip_allocator/mip_solver/planning_zone_mapper/zone_generator/land_use_zone_generator/space_control_generator/zone_type_deriver/generate.py) and update the violation budget 11->3. Add EXECUTE review package + guardrails. Main-graph wiring deferred to Wave M.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, no LangGraph (module-level functions, mirroring prior waves).

## Global Constraints
- LF line endings, 4-space indent, double quotes, no trailing whitespace
- Tests run from `backend/` (i.e. `python -m pytest tests/unit/execute/ -v`)
- Do NOT commit pre-existing uncommitted files under `docs/` (docs/design/, docs/architecture/, docs/weekly-reports/)
- Additive contracts: do NOT delete existing fields in `parcel_change_contracts.py`, `planned_state_contracts.py`, `selection_contracts.py`
- `app/agent/execute/` + `app/tools/gis/_generation/` must have ZERO `advisory_crosswalks` imports by end of Wave I (guardrail)
- Reuse `parcel_ops.py` — do NOT rewrite its core functions (reclassify/merge/split/create)
- No PuLP/MIP in the new execute path; zone assignment is deterministic reclassify by `zone_target.candidate_bsms`
- Facility placement is decision-driven from `facility_target.anchor_point`/`location_hint` — NO KG existing-POI lookup, NO `FACILITY_DLBM_MAP`
- Keep `_execute_axis_node` + `_execute_road_node` unchanged (not in Wave I scope)
- Main-graph wiring deferred to Wave M (deliver module only)
- Keep backward-compat fallbacks where a caller may not have SELECT output (log warning), but the legacy first-candidate loop in `_execute_project_node` IS removed in Task 3
- Branch: `refactor/phase1-planning-context` (continuing after Wave H)

---

### Task 1: Land Design Worker core module

**Files:**
- Create: `backend/app/agent/execute/land_design_worker.py`
- Modify: `backend/app/agent/execute/__init__.py` (export `design_all`, `build_parcel_change_set`)
- Create: `backend/tests/unit/execute/test_land_design_worker.py`

**Interfaces:**
- Consumes: `SiteSelectionDecision`, `LandDesignBrief`, `SpatialPlanningIntent` (project_targets/zone_targets/facilities), `ParcelChange`/`ParcelChangeSet` (parcel_change_contracts.py), `parcel_ops.py` functions, bundle parcels (`.bsm`/`.geometry`/`.dlbm`/`.area_sqm`)
- Produces:
  - `design_project_parcel(project, brief, selected_bsm, parcel_by_bsm) -> ParcelChange` — decide operation from `brief.footprint_conditions`/`setback_requirements`/`area_tolerance_pct`: single parcel -> reclassify; multi-parcel -> merge; needs split -> split. Uses `parcel_ops`.
  - `design_zone_parcel(zone_target, parcel_by_bsm) -> list[ParcelChange]` — for each `zone_target.candidate_bsms`, `reclassify_parcel` to the zone's planning_land_use.
  - `design_facility_parcel(facility_target, parcel_by_bsm, brief) -> ParcelChange` — generate facility footprint from `anchor_point`/`location_hint` (buffer or `create_parcel`).
  - `build_parcel_change_set(changes: list[ParcelChange], *, area_conservation_verified=False, geometry_validity_verified=False) -> ParcelChangeSet` — aggregate + set verification flags.
  - `design_all(intent, site_selection, briefs, parcel_by_bsm) -> ParcelChangeSet` — orchestrator over project_targets + zone_targets + facilities.
- Deterministic, no LLM, no advisory_crosswalks, no MIP, no kg imports.

- [ ] **Step 1: Write the failing test** — each design function 1-2 cases + `build_parcel_change_set` aggregation + lineage (`derived_from_bsms`) + verification flags
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** `land_design_worker.py` + `__init__.py` export
- [ ] **Step 4: Run test to verify it passes** + existing parcel_ops tests no regression
- [ ] **Step 5: Commit**: `feat(wave-i): Land Design Worker (project/zone/facility parcel changes)`

---

### Task 2: PlannedState builder from ParcelChangeSet

**Files:**
- Create: `backend/app/agent/execute/planned_state_builder.py`
- Modify: `backend/app/agent/execute/__init__.py` (export `changeset_to_planned_state`)
- Create: `backend/tests/unit/execute/test_planned_state_builder.py`

**Interfaces:**
- Consumes: `ParcelChangeSet`, `SpatialPlanningIntent` (road_targets/development_axes/facilities), `PlannedState`/`PlannedParcel`/`PlannedFacility`/`PlannedRoad`/`PlannedAxis` (planned_state_contracts.py)
- Produces: `changeset_to_planned_state(changeset, intent) -> PlannedState` — map `ParcelChange.action` -> `PlannedParcel.operation`; propagate `derived_from_bsms`/`before_classification`/`after_classification`; generate `PlannedFacility[]` from facility changes, `PlannedRoad[]` from `intent.road_targets`, `PlannedAxis[]` from `intent.development_axes`.
- Deterministic, no kg imports.

- [ ] **Step 1: Write the failing test** — changeset with reclassify/split/merge changes -> PlannedState with correct operations + lineage; facility/road/axis mapping
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** `planned_state_builder.py`
- [ ] **Step 4: Run test to verify it passes** + contract tests no regression
- [ ] **Step 5: Commit**: `feat(wave-i): PlannedState builder from ParcelChangeSet`

---

### Task 3: rewrite _execute_project_node (Land Design Worker + polygon footprint)

**Files:**
- Modify: `backend/app/agent/execute/execute_agent.py` (`_execute_project_node` + helper `_project_features_from_selection`)
- Modify: `backend/app/agent/execute/execute_state.py` (add `parcel_changeset: Optional[Any] = None` field)
- Create: `backend/tests/unit/execute/test_project_node_land_design.py`

**Interfaces:**
- Consumes: `state.site_selection.selected_combination`, `state.land_design_briefs`, `state.intent.project_targets`, `parcel_by_bsm` from `gis_data["landuse_current_geojson"]`, `land_design_worker.design_project_parcel`
- Rewrite: delete the legacy first-candidate fallback loop (Wave H kept it); primary path uses `design_project_parcel` per selected BSM -> builds `planned_project` layer with **Polygon** geometry (project outline, from the parcel geometry) instead of Point; appends `ParcelChange[]` to `state.parcel_changeset` (or a new field `parcel_changes: list` on state — decide and document)
- Keep unresolved_targets handling for unplaced projects
- Add `ExecuteAgentState.parcel_changeset: Optional[Any] = None` (ParcelChangeSet accumulated across project/layout/facility nodes)

- [ ] **Step 1: Write the failing test** — SSD + briefs -> planned_project layer with Polygon geometry + ParcelChange added; legacy loop gone (assert no `candidate_bsms` iteration / no `for bsm in project.candidate_bsms`)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** node rewrite + state field
- [ ] **Step 4: Run test to verify it passes** + existing `test_project_node_consumes_ssd.py` updated if needed + no regression
- [ ] **Step 5: Commit**: `feat(wave-i): rewrite _execute_project_node (Land Design Worker + polygon footprint)`

---

### Task 4: rewrite _execute_layout_node (deterministic zone reclassify, no MIP)

**Files:**
- Modify: `backend/app/agent/execute/execute_agent.py` (`_execute_layout_node`)
- Create: `backend/tests/unit/execute/test_layout_node_deterministic.py`

**Interfaces:**
- Consumes: `state.intent.zone_targets` (with candidate_bsms/planning_zone/area_ha), `state.intent.custom_zone_targets`, `parcel_by_bsm`, `land_design_worker.design_zone_parcel`
- Rewrite: delete both `MIPZoneAllocator().solve()` calls + `landuse_current_geojson` optimization input; iterate `zone_target.candidate_bsms` -> `reclassify_parcel` to the zone's planning_land_use; produce `function_zone`/`custom_planning_zone` layers + `ParcelChange[]`; keep `CustomZoningGenerator` only if no advisory_crosswalks dependency (check — if it imports crosswalks, replace with deterministic reclassify)
- Remove the `allocation_summary` mode="mip" reporting (use mode="deterministic")
- Do NOT touch `_execute_facility_node` here (Task 5)

- [ ] **Step 1: Write the failing test** — zone_targets with candidate_bsms -> function_zone layer + ParcelChange[] with reclassify actions; no MIP import/call (assert via monkeypatch that MIPZoneAllocator is not invoked, or AST that `mip_allocator` not imported)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** layout node rewrite
- [ ] **Step 4: Run test to verify it passes** + `test_execute_custom_zoning` STILL pre-existing-fails the same way (do not change its behavior) + no regression
- [ ] **Step 5: Commit**: `feat(wave-i): rewrite _execute_layout_node (deterministic zone reclassify, no MIP)`

---

### Task 5: rewrite _execute_facility_node (decision-driven, no KG POI)

**Files:**
- Modify: `backend/app/agent/execute/execute_agent.py` (`_execute_facility_node`)
- Create: `backend/tests/unit/execute/test_facility_node_decision_driven.py`

**Interfaces:**
- Consumes: `state.intent.facilities`, `state.intent.project_targets`, `land_design_worker.design_facility_parcel`, parcel_by_bsm
- Rewrite: delete `_generate_facilities`/`FacilityPlacer`/KG existing-POI lookup path; iterate `intent.facilities`, build facility footprint from `anchor_point`/`location_hint` via `design_facility_parcel`; produce `facility_point` layer (Polygon geometry) + `ParcelChange[]`
- Do NOT delete `_execute_facility_node` entirely — keep error handling (`facility_output_empty` etc.)

- [ ] **Step 1: Write the failing test** — facilities with anchor_point -> facility layer with Polygon geometry + ParcelChange; no KG POI lookup (assert via monkeypatch that kg session not queried)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** facility node rewrite
- [ ] **Step 4: Run test to verify it passes** + no regression
- [ ] **Step 5: Commit**: `feat(wave-i): rewrite _execute_facility_node (decision-driven, no KG POI)`

---

### Task 6: _write_l4_node consumes ParcelChangeSet

**Files:**
- Modify: `backend/app/agent/execute/execute_agent.py` (`_write_l4_node` + `_layout_configs_to_planned_state`)
- Create: `backend/tests/unit/execute/test_write_l4_from_changeset.py`

**Interfaces:**
- Consumes: `state.parcel_changeset`, `planned_state_builder.changeset_to_planned_state`, `apply_planned_state` (kg layer4)
- Rewrite: `_write_l4_node` uses `changeset_to_planned_state(state.parcel_changeset, state.intent)` when changeset present; keeps old `_layout_configs_to_planned_state` as fallback when changeset is None; calls `apply_planned_state` + `manager.bump_version` as before
- Set `area_conservation_verified`/`geometry_validity_verified` on the changeset before write (from Task 1 builder or verify here)

- [ ] **Step 1: Write the failing test** — changeset -> PlannedState written via apply_planned_state (mock kg); fallback path when changeset None
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** write_l4 rewrite
- [ ] **Step 4: Run test to verify it passes** + existing L4 tests no regression
- [ ] **Step 5: Commit**: `feat(wave-i): _write_l4_node consumes ParcelChangeSet`

---

### Task 7: atomic delete 8 LEGACY_GATED_FILES + update violation budget

**Files:**
- Delete: `backend/app/tools/gis/_generation/optimizer/mip_allocator.py`, `optimizer/mip_solver.py`, `optimizer/planning_zone_mapper.py`, `_generation/zone_generator.py`, `_generation/land_use_zone_generator.py`, `_generation/space_control_generator.py`, `_generation/zone_type_deriver.py`, `backend/app/tools/gis/generate.py`
- Modify: `backend/tests/unit/test_no_advisory_crosswalk_imports.py` (remove the 8 from `VIOLATION_BUDGET` 11->3 and from `LEGACY_GATED_FILES` entirely)
- Modify: `backend/app/tools/gis/__init__.py` + any importers of `generate.py`/deleted modules (search & fix)
- Modify: `backend/app/tools/gis/_generation/optimizer/__init__.py` if it re-exports deleted modules
- Create: (verification only) run full suite

**Interfaces:**
- After delete: `VIOLATION_BUDGET` = 3 entries (dynamic_zoning.py, compare_layouts.py, layout_validator.py); `LEGACY_GATED_FILES` = [] (empty)
- All callers migrated in Tasks 3-6 must no longer import the deleted modules

- [ ] **Step 1: Grep for importers of deleted modules** (generate, mip_allocator, mip_solver, planning_zone_mapper, zone_generator, land_use_zone_generator, space_control_generator, zone_type_deriver) across `backend/` — fix any non-migrated callers
- [ ] **Step 2: Delete the 8 files** (git rm)
- [ ] **Step 3: Update** `test_no_advisory_crosswalk_imports.py` budget + LEGACY_GATED_FILES
- [ ] **Step 4: Run full suite** — confirm only 4 pre-existing failures; confirm `test_no_advisory_crosswalk_imports.py` still passes (budget now 3)
- [ ] **Step 5: Commit**: `chore(wave-i): atomic delete 8 LEGACY_GATED_FILES + update violation budget`

---

### Task 8: EXECUTE review package + before/after comparison

**Files:**
- Create: `backend/app/agent/execute/review.py` (`build_execute_review_package`, `build_before_after_geojson`)
- Modify: `backend/app/agent/execute/__init__.py` (export review functions)
- Create: `backend/tests/unit/execute/test_execute_review.py`

**Interfaces:**
- Consumes: `ParcelChangeSet`, `PlannedState`, `GateDecision` or validation result, context
- Produces: `build_execute_review_package(changeset, planned_state, ...) -> dict` with 8 sections (Chinese headers, JSON-serializable, mirror ground/select review style): 操作日志 (action counts), 面积守恒, 地块谱系 (derived_from_bsms tree), 前后对比图 (FeatureCollection of before/after pairs), PlannedState 摘要, 设施/道路/轴线清单, 未解析目标, provenance
- `build_before_after_geojson(changeset, parcel_by_bsm) -> dict` — FeatureCollection with paired before/after features

- [ ] **Step 1: Write the failing test** — 8 sections present, JSON-serializable, before/after GeoJSON valid
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** review + before_after
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-i): EXECUTE review package + before/after comparison`

---

### Task 9: guardrails

**Files:**
- Create: `backend/tests/unit/execute/test_no_advisory_crosswalks.py`
- Modify: (none required; independent AST scan in new file)

**Interfaces:**
- AST scan: `app/agent/execute/*.py` + `app/tools/gis/_generation/*.py` (and `optimizer/` subdir) must NOT import `app.modules.schema.advisory_crosswalks`
- Regression: the 8 deleted files no longer exist (`os.path.exists` is False)
- Regression: `VIOLATION_BUDGET` == 3 (import the test's budget and assert)
- sys.modules snapshot: importing `app.agent.execute` must not load `advisory_crosswalks`
- Mirror `tests/unit/ground/test_no_kg_imports.py` / `tests/unit/select_graph/test_no_kg_imports.py` pattern (BOM-tolerant utf-8-sig)

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it runs** (should be green — violations already cleared in Task 7; verify matcher catches planted import)
- [ ] **Step 3: Implement** guardrail tests
- [ ] **Step 4: Run test to verify it passes** + full suite (1018+ new pass, 4 pre-existing failures)
- [ ] **Step 5: Commit**: `test(wave-i): guardrails (no advisory_crosswalks in execute chain)`

---

### Task 10: docs sync (uncommitted)

**Files:**
- Modify: `docs/design/10_IMPLEMENTATION_STATUS.md` (EXECUTE Worker 子图 PARTIAL -> CURRENT; PlannedState row update)
- Modify: `docs/weekly-reports/2026-08-04-wave-roadmap.md` (add Wave I delivery note)

- [ ] **Step 1: Update `10_IMPLEMENTATION_STATUS.md`** EXECUTE + PlannedState rows
- [ ] **Step 2: Update `2026-08-04-wave-roadmap.md`** with Wave I delivery summary
- [ ] **Step 3: Verify git status** — docs changes remain uncommitted; no `docs/` staging
- [ ] **No commit** (docs rule)

---

## Verification
- EXECUTE suite: all new tests pass
- Full suite: existing 1018 + new pass, only 4 pre-existing failures remain (kg->data, catalog_session_context x2, execute_custom_zoning), zero new regressions
- advisory_crosswalks violation budget: 11 -> 3 (8 EXECUTE-chain violations cleared)
- Guardrails: `app/agent/execute/` + `app/tools/gis/_generation/` zero advisory_crosswalks imports; 8 files deleted

## Out of scope (deferred)
- Main-graph wiring (`bootstrap/graph.py`) -> Wave M
- `_execute_axis_node`/`_execute_road_node` rewrite -> later wave (no advisory_crosswalks deps)
- 3 remaining advisory_crosswalks violations (dynamic_zoning.py, compare_layouts.py, layout_validator.py) -> later wave
- Legacy `app/agent/select/` (PARSE legacy dir) atomic deletion -> Wave M
- `kg->data` reverse dependency -> Wave M
