# Wave J Implementation Plan: VALIDATE Subgraph

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent VALIDATE subgraph (`app/agent/validate/`) that produces a typed `ValidationReport` with 8 validation check categories and per-violation responsibility-stage attribution, plus a 5-way responsibility router (PASS/RETRY_EXECUTE/RETRY_SELECT/RETRY_GROUND/RETRY_L3/HUMAN). Rewrite `_validate_node` to consume it (removing the EXECUTE-internal `LayoutValidator` and the 3-round silent fallthrough). Fix the stale `test_execute_custom_zoning` test. Delete the final 3 advisory_crosswalks violations (budget 3 -> 0), fulfilling the global "活动规划链对跨体系映射符号扫描为零" condition.

**Architecture:** Reuse the Wave A typed contracts (`ValidationReport`/`ValidationCheck`/`ValidationIssue` with `responsible_stage: Literal["L3","PARSE","GROUND","SELECT","EXECUTE"]` in `validation_report_contracts.py`) — currently UNUSED in production. The 9 legacy `LayoutValidator` checks move into `app/agent/validate/checks.py` as deterministic functions emitting `ValidationCheck` directly (with stage attribution); the missing check categories (topology, continuity, accessibility, contract completeness, true classification-missing) are implemented fresh. `validate_aggregate` orchestrates the 8 checks into a `ValidationReport` with `issues_by_stage`. `evaluate_validate_gate` maps error-severity issue concentration to a 5-way route (mirroring `select_graph/gate.py`), wiring only RETRY_EXECUTE into the current EXECUTE graph (L3/GROUND/SELECT edges are Wave M TODO). The legacy `LayoutValidator` is deleted after migration; `compare_layouts.py` + `dynamic_zoning.py` (dev/analytics-only, unreachable from active chain) are deleted; `VIOLATION_BUDGET` goes 3 -> 0. Main-graph wiring deferred to Wave M.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, no LangGraph (module-level functions, mirroring prior waves).

## Global Constraints
- LF line endings, 4-space indent, double quotes, no trailing whitespace
- Tests run from `backend/` (i.e. `python -m pytest tests/unit/validate/ -v`)
- Do NOT commit pre-existing uncommitted files under `docs/` (docs/design/, docs/architecture/, docs/weekly-reports/)
- Additive contracts: do NOT delete existing fields in `validation_report_contracts.py`, `workflow_contracts.py`, `planned_state_contracts.py`, `parcel_change_contracts.py`
- `app/agent/validate/` must have ZERO `advisory_crosswalks` imports (guardrail)
- All 8 check categories implemented deterministically, no LLM, no MIP, no kg imports in `app/agent/validate/`
- Accessibility uses haversine service-radius coverage (no external API / Tianditu)
- Reuse `ConstraintIndex` (bridge.py) for hard constraints, `shapely STRtree` for topology/overlap, `land_balance.py` for area closure
- Fix `test_execute_custom_zoning.py:58` (`custom_functional_zone` -> `custom_planning_zone`) — removes 1 pre-existing failure (4 -> 3)
- `_route_after_validate` drops the 3-round silent `pass` fallthrough; failed validation routes to `human` (terminal) or `retry`
- Main-graph wiring deferred to Wave M (deliver module only)
- Branch: `refactor/phase1-planning-context` (continuing after Wave I)

---

### Task 1: VALIDATE checks (8 categories + responsibility stage)

**Files:**
- Create: `backend/app/agent/validate/checks.py` (8 deterministic check functions)
- Create: `backend/tests/unit/validate/__init__.py`, `backend/tests/unit/validate/test_checks.py`

**Interfaces:**
- Consumes: `ValidationCheck` (validation_report_contracts.py), `PlannedState`/`PlannedParcel` (planned_state_contracts.py), `ParcelChangeSet` (parcel_change_contracts.py), `SpatialPlanningIntent`, `ConstraintIndex` (bridge.py), shapely STRtree
- Produces (each returns `list[ValidationCheck]`, with `responsible_stage` + `fix_suggestion` + `affected_parcels`):
  1. `check_hard_constraints(planned_state, constraint_index) -> list[ValidationCheck]` — planned parcels whose geometry intersects prohibited constraints; stage SELECT or EXECUTE
  2. `check_area_conservation(changeset) -> list[ValidationCheck]` — sum(split parts) == original, sum(merged) == sum(sources); uses `changeset.area_conservation_verified` + per-change before/after area; stage EXECUTE
  3. `check_topology(layout_configs) -> list[ValidationCheck]` — STRtree adjacency + gap detection (non-empty geometry, valid topology); stage EXECUTE
  4. `check_overlap(layout_configs) -> list[ValidationCheck]` — STRtree intersecting pairs with intersection.area > 0; stage EXECUTE
  5. `check_continuity(layout_configs) -> list[ValidationCheck]` — MultiPolygon component count per zone (>1 component = fragmented); stage EXECUTE
  6. `check_accessibility(planned_state, intent) -> list[ValidationCheck]` — haversine service-radius coverage for facility anchors; stage SELECT
  7. `check_contract_completeness(planned_state, changeset, intent) -> list[ValidationCheck]` — PlannedState.parcels non-empty when projects/zones exist, ParcelChangeSet verification flags, non-empty bsm/geometry; stage EXECUTE or L3
  8. `check_classification_missing(planned_state) -> list[ValidationCheck]` — `planning_land_use` empty on non-preserve planned parcels; stage L3 or EXECUTE
- Deterministic, no LLM, no advisory_crosswalks, no kg imports

- [ ] **Step 1: Write the failing test** — one case per check function (valid input -> passed check; invalid input -> failed check with responsible_stage set)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** `checks.py`
- [ ] **Step 4: Run test to verify it passes** + no regression
- [ ] **Step 5: Commit**: `feat(wave-j): VALIDATE checks (8 categories + responsibility stage)`

---

### Task 2: validate_aggregate (orchestrator -> ValidationReport)

**Files:**
- Create: `backend/app/agent/validate/aggregate.py` (`validate_aggregate`)
- Create: `backend/app/agent/validate/__init__.py` (export `validate_aggregate`)
- Create: `backend/tests/unit/validate/test_aggregate.py`

**Interfaces:**
- Consumes: 8 check functions, `ValidationReport`/`ValidationCheck`/`ValidationIssue` (validation_report_contracts.py), `StageIssue` base
- Produces: `validate_aggregate(planned_state, changeset, layout_configs, intent, constraint_index) -> ValidationReport`
  - Run all 8 checks, flatten to `checks: list[ValidationCheck]`
  - `overall_passed = all(check.passed) and no error-severity issue`
  - `issues_by_stage: dict[str, list[ValidationIssue]]` — group issues by `responsible_stage`
  - `adjustments` — from constraint adjustments (if any)
  - `provenance` — Provenance(source="validate_aggregate", run_id=..., module="app.agent.validate.aggregate")
- Deterministic

- [ ] **Step 1: Write the failing test** — valid inputs -> ValidationReport with overall_passed True; an invalid check -> overall_passed False + issue in the right stage bucket
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** `aggregate.py` + `__init__.py`
- [ ] **Step 4: Run test to verify it passes** + contract tests no regression
- [ ] **Step 5: Commit**: `feat(wave-j): validate_aggregate (orchestrator -> ValidationReport)`

---

### Task 3: validate gate (5-way responsibility router)

**Files:**
- Create: `backend/app/agent/validate/gate.py` (`evaluate_validate_gate`, `validate_gate_route`)
- Modify: `backend/app/agent/validate/__init__.py` (export gate functions)
- Create: `backend/tests/unit/validate/test_gate.py`

**Interfaces:**
- Consumes: `ValidationReport`, `GateDecision`, `PendingRequest`, `StageId` (workflow_contracts.py)
- Produces: `evaluate_validate_gate(report: ValidationReport) -> GateDecision` with routes:
  - `PASS`: `report.overall_passed` True and no error-severity issues
  - `RETRY_EXECUTE`: most error issues attributed to EXECUTE
  - `RETRY_SELECT`: most error issues attributed to SELECT
  - `RETRY_GROUND`: most error issues attributed to GROUND
  - `RETRY_L3`: most error issues attributed to L3
  - `HUMAN`: low confidence / unresolved ambiguity / mixed-stage errors
- `validate_gate_route(report) -> str` helper
- Mirror `select_graph/gate.py` style (stage="validate", GateDecision + PendingRequest with context["reason"])
- Precedence: PASS if no errors; else HUMAN if tie/mixed; else the dominant stage

- [ ] **Step 1: Write the failing test** — one case per route + tie/mixed -> HUMAN
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** gate
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-j): validate gate (5-way responsibility router)`

---

### Task 4: validate review package

**Files:**
- Create: `backend/app/agent/validate/review.py` (`build_validate_review_package`)
- Modify: `backend/app/agent/validate/__init__.py` (export review function)
- Create: `backend/tests/unit/validate/test_review.py`

**Interfaces:**
- Consumes: `ValidationReport`, `GateDecision`
- Produces: `build_validate_review_package(report: ValidationReport, gate: GateDecision) -> dict` with 8 sections (Chinese headers, JSON-serializable, mirror ground/select/execute review):
  1. 检查摘要 (8 category passed/failed counts)
  2. 按阶段归因 (issues_by_stage summary)
  3. 违规清单 (ValidationIssue list)
  4. 面积守恒详情
  5. 拓扑/重叠/连续性结果
  6. 可达性覆盖
  7. Gate 决定 + 路由 (route + rationale)
  8. 来源追溯 (provenance via model_dump(mode="json"))

- [ ] **Step 1: Write the failing test** — 8 sections present, JSON-serializable
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** review
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-j): validate review package`

---

### Task 5: rewrite _validate_node to consume VALIDATE subgraph

**Files:**
- Modify: `backend/app/agent/execute/execute_agent.py` (`_validate_node`)
- Modify: `backend/app/agent/execute/execute_state.py` (add `validation_report: Optional[Any] = None`)
- Create: `backend/tests/unit/validate/test_validate_node.py`

**Interfaces:**
- Consumes: `state.layout_configs`, `state.parcel_changeset`, `state.planned_state` (if available), `state.intent`, `state.kg_protected_parcels_detail`, `app.agent.validate.aggregate.validate_aggregate`
- Rewrite `_validate_node`:
  - Delete the `LayoutValidator` import/call (from `app.tools.gis._validation.layout_validator`)
  - Build inputs: `planned_state = <from parcel_changeset via planned_state_builder, or None>`, `changeset = state.parcel_changeset`, `constraint_index = build_constraint_index(state.gis_bundle)`
  - Call `validate_aggregate(planned_state, changeset, state.layout_configs, state.intent, constraint_index)` -> `ValidationReport`
  - Store `state.validation_report = report`
  - Map to `validation_result` dict for backward compat: `passed`->`overall_passed`, `status`->derive ("pass"/"warning"/"fail"), `violations`->flatten issues `[{check, message}]`, keep `custom_planning`/`l3_l4_consistency` if still produced (may be simplified)
  - Keep `partial_usable` handling
  - Narrow the broad `except Exception` (remove the generic catch or restrict per known error codes)
- Keep `_build_l3_l4_consistency_report` (may be called as one input source or deferred to Wave K)

- [ ] **Step 1: Write the failing test** — _validate_node returns validation_result with passed from ValidationReport; state.validation_report populated; no LayoutValidator import (AST check)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** node rewrite + state field
- [ ] **Step 4: Run test to verify it passes** + existing execute tests no regression
- [ ] **Step 5: Commit**: `feat(wave-j): rewrite _validate_node to consume VALIDATE subgraph`

---

### Task 6: fix stale test + update route edges (no silent fallthrough)

**Files:**
- Modify: `backend/tests/unit/test_execute_custom_zoning.py` (`custom_functional_zone` -> `custom_planning_zone` at line 58)
- Modify: `backend/app/agent/execute/execute_agent.py` (`_route_after_validate`)
- Modify: `backend/tests/unit/validate/test_validate_node.py` (extend for routing)

**Interfaces:**
- Fix `test_execute_custom_zoning.py:58` — expects `"custom_planning_zone"` (matches production + `test_layout_node_deterministic.py:147`); removes 1 pre-existing failure (4 -> 3)
- Rewrite `_route_after_validate` to return `Literal["pass", "retry", "human"]`:
  - `pass` if `validation_result.passed`
  - `human` if validation failed AND `state.validation_round >= 3` (terminal, NO silent pass fallthrough)
  - `retry` otherwise
- Update graph conditional edges: `{"retry": "execute_layout", "pass": "write_l4", "human": END}` (check END wiring)

- [ ] **Step 1: Write the failing test** — route returns "human" after 3 failed rounds (not silent pass); stale test fixed
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** test fix + route rewrite + edge update
- [ ] **Step 4: Run test to verify it passes** + full suite (expect 3 pre-existing failures only: kg->data, catalog x2)
- [ ] **Step 5: Commit**: `fix(wave-j): fix stale test + update route edges (no silent fallthrough)`

---

### Task 7: atomic delete 3 remaining crosswalk files + budget 3 -> 0

**Files:**
- Delete: `backend/app/tools/gis/_validation/layout_validator.py`, `backend/app/tools/gis/_rendering/compare_layouts.py`, `backend/app/tools/gis/_analytics/dynamic_zoning.py`
- Modify: `backend/app/tools/gis/_analytics/__init__.py` (remove dynamic_zoning re-export)
- Modify: `backend/app/tools/gis/_rendering/__init__.py` (if it re-exports compare_layouts)
- Modify: `backend/app/tools/gis/_generation/pipeline.py` (`build_three_way_comparison` if it imports compare_layouts — graceful degrade)
- Modify: `backend/app/api/gis_test_routes.py` (any compare_layouts/dynamic_zoning references — graceful degrade or remove route)
- Modify: `backend/tests/unit/test_no_advisory_crosswalk_imports.py` (`VIOLATION_BUDGET` -> `{}`, `LEGACY_GATED_FILES` -> `[]`)
- Modify: `backend/tests/unit/execute/test_no_advisory_crosswalks.py` (`_EXPECTED_BUDGET_FILES` -> `()`, budget assertion -> 0)

**Interfaces:**
- After delete: `VIOLATION_BUDGET == {}` (zero violations — global acceptance condition met); `LEGACY_GATED_FILES == []`
- All callers migrated in Tasks 1-5 must no longer import the deleted modules

- [ ] **Step 1: Grep for importers of the 3 deleted modules** (layout_validator, compare_layouts, dynamic_zoning) across `backend/` — fix any non-migrated callers
- [ ] **Step 2: Delete the 3 files** (git rm) + remove re-exports
- [ ] **Step 3: Update** violation budget tests
- [ ] **Step 4: Run full suite** — confirm only 3 pre-existing failures (kg->data, catalog x2); confirm `test_no_advisory_crosswalk_imports.py` + `test_no_advisory_crosswalks.py` pass with budget 0
- [ ] **Step 5: Commit**: `chore(wave-j): atomic delete 3 remaining crosswalk files + budget 3->0`

---

### Task 8: guardrails

**Files:**
- Create: `backend/tests/unit/validate/test_no_crosswalk_imports.py`

**Interfaces:**
- AST scan: `app/agent/validate/*.py` must NOT import `advisory_crosswalks`
- Regression: 3 deleted files no longer exist (`os.path.exists` False)
- `VIOLATION_BUDGET == 0` (import the real budget and assert)
- sys.modules snapshot: importing `app.agent.validate` must not load `advisory_crosswalks`
- Mirror `tests/unit/execute/test_no_advisory_crosswalks.py` pattern (BOM-tolerant utf-8-sig)

- [ ] **Step 1: Write the failing test** (verify matcher catches planted import)
- [ ] **Step 2: Run test to verify it runs** (should be green — violations cleared in Task 7)
- [ ] **Step 3: Implement** guardrail tests
- [ ] **Step 4: Run test to verify it passes** + full suite (expect ~1066+ new pass, 3 pre-existing failures)
- [ ] **Step 5: Commit**: `test(wave-j): guardrails (no crosswalks in validate + budget zero)`

---

### Task 9: docs sync (uncommitted)

**Files:**
- Modify: `docs/design/10_IMPLEMENTATION_STATUS.md` (Validation Router PARTIAL -> CURRENT; import boundary budget 0; execute_custom_zoning note)
- Modify: `docs/weekly-reports/2026-08-04-wave-roadmap.md` (add Wave J delivery note)

- [ ] **Step 1: Update `10_IMPLEMENTATION_STATUS.md`** Validation Router + import boundary rows
- [ ] **Step 2: Update `2026-08-04-wave-roadmap.md`** with Wave J delivery summary
- [ ] **Step 3: Verify git status** — docs changes remain uncommitted; no `docs/` staging
- [ ] **No commit** (docs rule)

---

## Verification
- VALIDATE suite: all new tests pass
- Full suite: existing 1066 + new pass, only 3 pre-existing failures remain (kg->data, catalog_session_context x2 — execute_custom_zoning FIXED in Task 6), zero new regressions
- advisory_crosswalks violation budget: 3 -> 0 (global "活动规划链对跨体系映射符号扫描为零" condition met)
- Guardrails: `app/agent/validate/` zero advisory_crosswalks imports; 3 files deleted

## Out of scope (deferred)
- Main-graph wiring (`bootstrap/graph.py`) + L3/GROUND/SELECT validation feedback edges -> Wave M
- RECONCILE (text<->artifact reconciliation) -> Wave K
- Network accessibility (graph path analysis) -> later wave (Wave J uses haversine coverage)
- `_execute_axis_node`/`_execute_road_node` rewrite -> later wave
- `kg->data` reverse dependency -> Wave M
