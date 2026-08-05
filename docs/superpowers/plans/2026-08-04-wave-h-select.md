# Wave H Implementation Plan: SELECT Subgraph

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent SELECT subgraph (`app/agent/select_graph/`) that consumes GROUND's `GroundingResult` plus the L3 `SpatialPlanningIntent` and produces a typed `SiteSelectionDecision` with `LandDesignBrief[]`, following "硬约束过滤 + 多因子评分 + 冲突分配". Rewrite `_execute_project_node` to consume `SiteSelectionDecision` and delete the "first available candidate" logic.

**Architecture:** Reuse the existing but un-wired pure-function module `app/modules/spatial_ops/selection.py` (`apply_hard_filters` / `apply_scale_filter` / `score_candidates` / `rank_candidates` / `select_parcel` -> `PlacementDecision`) rather than rewriting it. Wave H adds: a min-area hard filter + `_PROHIBITED_CONSTRAINTS` consolidation (Task 1); a `GroundingResult -> CandidateParcel` adapter (Task 2); a `select_aggregate` orchestrator that maps each `ProjectTarget` to a `SelectionTarget`, runs `select_parcel`, applies priority-sequential conflict allocation, and assembles `SiteSelectionDecision + LandDesignBrief` (Task 3); a gate (Task 4); a review package with map preview (Task 5); guardrails (Task 6); and the `_execute_project_node` rewrite (Task 7). Main-graph wiring deferred to Wave M. Scoring keeps the existing 3 factors (proximity/construction/area_fit) with 道路可达性 + 服务覆盖 as zero-weight stubs in `score_breakdown`. New subgraph lives in `app/agent/select_graph/` (NOT the legacy `app/agent/select/` which is the PARSE legacy dir).

**Tech Stack:** Python 3.11, Pydantic v2, pytest, no LangGraph (module-level functions, mirroring L1/L2/L3/PARSE/GROUND).

## Global Constraints
- LF line endings, 4-space indent, double quotes, no trailing whitespace
- Tests run from `backend/` (i.e. `python -m pytest tests/unit/select_graph/ -v`)
- Do NOT commit pre-existing uncommitted files under `docs/` (docs/design/, docs/architecture/, docs/weekly-reports/)
- Additive contracts: do NOT delete existing fields in `selection_contracts.py` (`SiteSelectionDecision`/`RankedCandidate`/`EliminatedCandidate`/`LandDesignBrief`) or `grounding_contracts.py` (`GroundingResult`/`CandidateSite`)
- `app/agent/select_graph/` must NOT import `app.modules.kg` or `app.agent.select` (legacy PARSE dir) (guardrail)
- Reuse `spatial_ops/selection.py` — do not rewrite its core functions; only add `min_area_ha` param + consolidate the `_PROHIBITED_CONSTRAINTS` constant
- Scoring: keep 3 factors (proximity 0.5 + construction 0.3 + area_fit 0.2); 道路可达性/服务覆盖 as zero-weight stubs in score_breakdown (0.0, deterministic, no external API/KG)
- Conflict allocation: priority-sequential — process targets by `target_id` order, first picker wins, later targets skip occupied parcels (eliminated reason `allocated_to_higher_priority`)
- Main-graph wiring deferred to Wave M (deliver module only)
- Do NOT touch legacy `app/agent/select/parse_agent.py` or `_execute_facility_node` (Wave I scope)
- Branch: `refactor/phase1-planning-context` (continuing after Wave G)

---

### Task 1: min-area hard filter + consolidate _PROHIBITED_CONSTRAINTS

**Files:**
- Modify: `backend/app/modules/spatial_ops/selection.py` (add `min_area_ha: float = 0.0` param to `apply_hard_filters`; keep `_PROHIBITED_CONSTRAINTS` as the single source of truth)
- Modify: `backend/app/agent/execute/execute_agent.py` (replace duplicate `_PROHIBITED_CONSTRAINTS` sets at ~lines 192-199 and ~571-578 with import from `app.modules.spatial_ops.selection`)
- Create: `backend/tests/unit/spatial_ops/test_selection_min_area.py`

**Interfaces:**
- Produces: `apply_hard_filters(candidates, *, constraint_index=None, hazards=None, occupied=None, min_area_ha=0.0) -> (survivors, rejected)`. When `min_area_ha > 0` and `cand.area_ha < min_area_ha` -> reject reason `"below_min_area"` (append to detail; not a constraint block).
- Consumes: existing `_PROHIBITED_CONSTRAINTS` set (6 types: farmland_protection/ecological_redline/historical_protection/cultivated_land_target/hazard_control_line/flood_control_line)

- [ ] **Step 1: Write the failing test** — min-area filter rejects a small parcel; execute_agent no longer has a literal duplicate set (assert via import identity or AST that the sets are gone)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** — add param to `apply_hard_filters`; replace duplicate sets in execute_agent with `from app.modules.spatial_ops.selection import _PROHIBITED_CONSTRAINTS` (import at function level to match existing style)
- [ ] **Step 4: Run test to verify it passes** + existing `test_parcel_selection.py` and execute tests no regression
- [ ] **Step 5: Commit**: `feat(wave-h): add min-area hard filter + consolidate _PROHIBITED_CONSTRAINTS`

---

### Task 2: GroundingResult -> CandidateParcel adapter

**Files:**
- Create: `backend/app/agent/select_graph/__init__.py` (export adapter + later tasks' functions)
- Create: `backend/app/agent/select_graph/adapter.py` (`grounding_to_candidate_parcels`, `candidate_site_to_parcels`)
- Create: `backend/tests/unit/select_graph/__init__.py`, `backend/tests/unit/select_graph/conftest.py`, `backend/tests/unit/select_graph/test_adapter.py`

**Interfaces:**
- Consumes: `GroundingResult`, `CandidateSite` (grounding_contracts.py), `CandidateParcel` (selection.py), bundle parcels (`.polygons.get("landuse_current")` -> parcels with `.bsm`/`.geometry`/`.dlbm`/`.area_sqm`)
- Produces: `grounding_to_candidate_parcels(result: GroundingResult, bundle) -> list[CandidateParcel]`. Each `CandidateSite.source_parcels` (list of BSM strings) -> one `CandidateParcel` per BSM found in bundle. `area_ha = parcel.area_sqm / 10000.0`. `dlmc` mapped from `dlbm` via `from app.modules.schema import DLBM_TO_DLMC`. `distance_m`/`cluster` left default (filled by scoring layer later).
- Deterministic, no kg imports, no shapely dependency needed (uses bundle geometry dict directly)

- [ ] **Step 1: Write the failing test** — empty result -> empty list; 1 CandidateSite with 2 source_parcels -> 2 CandidateParcel with correct bsm/geometry/area_ha/dlmc; unknown BSM skipped
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** adapter
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-h): GroundingResult->CandidateParcel adapter`

---

### Task 3: select_aggregate orchestrator

**Files:**
- Create: `backend/app/agent/select_graph/aggregate.py` (`select_aggregate`, `build_site_selection_decision`, `build_land_design_brief`)
- Modify: `backend/app/agent/select_graph/__init__.py` (export `select_aggregate`)
- Create: `backend/tests/unit/select_graph/test_aggregate.py`

**Interfaces:**
- Consumes: `GroundingResult`, `SpatialPlanningIntent` (project_targets), `PlanningContext` (bundle + constraint_index), `CandidateParcel`, `SelectionTarget`, `select_parcel`, `PlacementDecision`, `Rejection` (selection.py), `SiteSelectionDecision`, `RankedCandidate`, `EliminatedCandidate`, `LandDesignBrief` (selection_contracts.py), `Provenance`
- Produces: `select_aggregate(result: GroundingResult, intent, context: PlanningContext) -> tuple[SiteSelectionDecision, list[LandDesignBrief]]`
- Flow:
  1. `parcels = grounding_to_candidate_parcels(result, context.bundle)`
  2. For each `intent.project_targets` -> `SelectionTarget(target_id=project.project_id, name=project.name, category="project", scale_text=project.scale_text)`
  3. Run `select_parcel` per target with `constraint_index=context.constraint_index`, `occupied=occupied_points` (accumulate from already-placed decisions — priority-sequential conflict allocation), `cluster_centroid` from context if available
  4. Assemble `SiteSelectionDecision`: `selected_combination` = ordered placed BSM list; `full_ranking` = ranked candidates across all decisions (candidate_id = bsm, rank, score, score_breakdown with 5 keys incl. 0.0 stubs for road_access/service_coverage); `eliminated` = rejected + occupied-skipped (elimination_reason `hard_filter`/`below_min_area`/`allocated_to_higher_priority`, eliminated_by_constraint from Rejection detail); `decision_factors` = dict of per-target best-score; `review_status = "auto"`; `provenance` = Provenance(source="select_aggregate", run_id=session_id, ...)
  5. Build `LandDesignBrief` per selected project (deterministic from ProjectTarget): `project_ref=project_id`, `footprint_conditions` from category+scale_text, `access_requirements` from road_targets adjacency, `setback_requirements` from constraint overlap labels, `area_tolerance_pct=5.0` default
- Deterministic, no LLM

- [ ] **Step 1: Write the failing test** — empty GroundingResult + empty intent -> empty SSD with 0 candidates; 1 project 1 candidate -> 1 selected_combination entry + 1 LandDesignBrief; conflict: 2 projects 1 parcel -> 1 selected 1 eliminated(allocated_to_higher_priority)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** aggregate + brief builder
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-h): select_aggregate (orchestrator -> SiteSelectionDecision + LandDesignBrief)`

---

### Task 4: select gate

**Files:**
- Create: `backend/app/agent/select_graph/gate.py` (`evaluate_select_gate`, `select_gate_route`)
- Modify: `backend/app/agent/select_graph/__init__.py` (export gate functions)
- Create: `backend/tests/unit/select_graph/test_gate.py`

**Interfaces:**
- Consumes: `SiteSelectionDecision`, `GateDecision`, `PendingRequest`, `StageId` (workflow_contracts.py)
- Produces: `evaluate_select_gate(decision: SiteSelectionDecision, *, target_count: int, confidence_threshold: float = 0.4) -> GateDecision` with routes:
  - `PASS`: `selected_combination` non-empty and covers all targets (`len(selected_combination) >= target_count` or no targets expected unresolved)
  - `RETRY_GROUND`: some targets have no candidate (eliminated with `allocated_to_higher_priority`/`hard_filter`/`below_min_area`) -> PendingRequest reason `selection_no_candidate`
  - `HUMAN`: top candidate score < confidence_threshold (low confidence) -> human review
- Precedence: RETRY_GROUND wins if any target unplaced; else HUMAN if low confidence; else PASS
- Mirror `agent/ground/gate.py` style (stage="select", artifact_id="gate-select-<id>", PendingRequest uses request_type + context["reason"])

- [ ] **Step 1: Write the failing test** — one case per route + precedence (unplaced wins over low-confidence)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** gate
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-h): select gate (PASS/RETRY_GROUND/HUMAN)`

---

### Task 5: select review package + map preview

**Files:**
- Create: `backend/app/agent/select_graph/review.py` (`build_select_review_package`, `build_preview_geojson`)
- Modify: `backend/app/agent/select_graph/__init__.py` (export review functions)
- Create: `backend/tests/unit/select_graph/test_review.py`

**Interfaces:**
- Consumes: `SiteSelectionDecision`, `list[LandDesignBrief]`, `GateDecision`, `GroundingResult`
- Produces: `build_select_review_package(decision, briefs, gate, result) -> dict` with 8 sections (Chinese headers, JSON-serializable, mirror `ground/review.py` style):
  1. 输入候选摘要 (CandidateSite count + source_parcels total)
  2. 完整排名 (RankedCandidate list)
  3. 淘汰理由 (EliminatedCandidate list)
  4. 最终组合 (selected_combination + LandDesignBrief summary)
  5. 决策因子 (decision_factors / score_breakdown)
  6. Gate 决定 + 原理 (feedback_route or PASS + rationale)
  7. 来源追溯 (provenance serialized via model_dump(mode="json"))
  8. 地图预览 (FeatureCollection of selected parcels with project_id/source_bsm properties)
- `build_preview_geojson(decision, bundle_parcels_by_bsm) -> dict` — FeatureCollection, one Feature per selected BSM with geometry from bundle, properties `{project_id, source_bsm, site_id, score}`

- [ ] **Step 1: Write the failing test** — 8 sections present, JSON-serializable (json.dumps), preview is FeatureCollection with features
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** review + preview
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-h): select review package + map preview`

---

### Task 6: guardrails

**Files:**
- Create: `backend/tests/unit/select_graph/test_no_kg_imports.py`
- Modify: (none required; independent AST scan in new file)

**Interfaces:**
- AST scan: `app/agent/select_graph/*.py` must not import `app.modules.kg` or `app.agent.select`
- sys.modules snapshot: importing `app.agent.select_graph` must not load new kg submodules
- Regression: `spatial_ops/selection.py` has no `app.agent` imports (it's a pure module)
- Mirror `tests/unit/ground/test_no_kg_imports.py` pattern (BOM-tolerant utf-8-sig reading)

- [ ] **Step 1: Write the failing test** (verify matcher catches planted imports)
- [ ] **Step 2: Run test to verify it runs**
- [ ] **Step 3: Implement** guardrail tests
- [ ] **Step 4: Run test to verify it passes** + full suite (967+ new pass, only 4 pre-existing failures)
- [ ] **Step 5: Commit**: `test(wave-h): guardrails (no kg/legacy-select imports)`

---

### Task 7: ExecuteAgentState.site_selection + rewrite _execute_project_node

**Files:**
- Modify: `backend/app/agent/execute/execute_state.py` (add `site_selection: Optional[Any] = None`, `land_design_briefs: List[Any] = Field(default_factory=list)`)
- Modify: `backend/app/agent/execute/execute_agent.py` (`_execute_project_node` lines ~162-286 rewrite)
- Create: `backend/tests/unit/execute/test_project_node_consumes_ssd.py`

**Interfaces:**
- Consumes: `state.site_selection` (`SiteSelectionDecision`), `state.land_design_briefs`, existing `by_bsm` from `gis_data["landuse_current_geojson"]`
- Rewrite `_execute_project_node`:
  - If `state.site_selection` is present with non-empty `selected_combination`: iterate `selected_combination` BSM values, look up in `by_bsm`, build `planned_project` Features (Point geometry from representative_point, properties incl. project_id/source_bsm/constraint_check="passed"), and pair with `land_design_briefs` by index
  - If `state.site_selection` is None (backward compat): keep the OLD inline first-candidate loop but log a warning that SELECT is not wired (Wave M will remove)
  - Keep unresolved_targets handling for unplaced projects
- Do NOT touch `_execute_facility_node`

- [ ] **Step 1: Write the failing test** — SSD present -> planned_project layer built from selected_combination (verify no candidate_bsms iteration, correct source_bsm); SSD absent -> legacy fallback still works with warning
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** state fields + node rewrite
- [ ] **Step 4: Run test to verify it passes** + existing execute tests no regression (esp. `test_execute_custom_zoning` remains pre-existing-fail only)
- [ ] **Step 5: Commit**: `feat(wave-h): rewrite _execute_project_node to consume SiteSelectionDecision`

---

### Task 8: docs sync (uncommitted)

**Files:**
- Modify: `docs/design/10_IMPLEMENTATION_STATUS.md` (SELECT row `TARGET` -> `CURRENT`; add note select_graph + _execute_project_node rewrite)
- Modify: `docs/weekly-reports/2026-08-04-wave-roadmap.md` (add Wave H delivery note under 波次交付说明)

- [ ] **Step 1: Update `10_IMPLEMENTATION_STATUS.md`** SELECT row
- [ ] **Step 2: Update `2026-08-04-wave-roadmap.md`** with Wave H delivery summary
- [ ] **Step 3: Verify git status** — docs changes remain uncommitted; no `docs/` staging
- [ ] **No commit** (docs rule)

---

## Verification
- SELECT suite: all new tests pass
- Full suite: existing 967 + new pass, only 4 pre-existing failures remain (kg->data, catalog_session_context x2, execute_custom_zoning), zero new regressions
- Guardrails: `agent/select_graph/` no kg/legacy-select imports; `spatial_ops/selection.py` pure

## Out of scope (deferred)
- Main-graph wiring (`bootstrap/graph.py`) -> Wave M
- 道路可达性/服务覆盖 full scoring factors -> later wave (stubs in score_breakdown)
- `_execute_facility_node` rewrite + Land Design Worker + ParcelChangeSet -> Wave I
- Legacy `app/agent/select/` (PARSE legacy dir) atomic deletion -> Wave M
- MIP allocator (mip_allocator.py) -> Wave I deletion
