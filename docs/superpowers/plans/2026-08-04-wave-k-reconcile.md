# Wave K Implementation Plan: RECONCILE Subgraph

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent RECONCILE subgraph (`app/agent/reconcile/`) that produces a typed `ReconciliationReport` with a coverage matrix tracing the full chain `PlanningIntervention -> SpatialReferenceSpec -> CandidateSite -> SiteSelectionDecision -> ParcelChangeSet -> PlannedState`, plus a list of cross-artifact inconsistencies (文本↔成果对账 per 07_VALIDATION_FEEDBACK.md §5). Absorb the partial `_build_l3_l4_consistency_report` from execute_agent.py. Add a 4-way reconcile gate.

**Architecture:** Enrich the skeletal Wave A contracts (`ReconciliationReport`/`CoverageMatrix`/`ReconciliationInconsistency` in `reconciliation_contracts.py`): add a typed `CoverageMatrixRow` (aligned with the existing `TraceabilityEntry` in delivery_manifest_contracts.py), upgrade `CoverageMatrix.rows: list[dict]` -> `list[CoverageMatrixRow]`, add `responsible_stage` to `ReconciliationInconsistency`. The `app/agent/reconcile/` subgraph mirrors the Wave J structure: `checks.py` (6 chain-coverage checks + quantitative drift), `aggregate.py` (reconcile_aggregate building CoverageMatrix + inconsistencies), `gate.py` (4-way PASS/RETRY_L3/RETRY_EXECUTE/HUMAN), `review.py` (8-section review package). Because the upstream chain has weak/broken linkage fields (spec has no intervention_id, ParcelChange has no project_ref, PlannedParcel.source_spec is empty on the primary path), reconcile_aggregate reconstructs the chain via BSM as the end-to-end thread + `ProjectTarget.project_id` (== intervention_id, set by compile_node) + positional alignment + best-effort matching, reporting positional misalignment as inconsistencies. `_build_l3_l4_consistency_report` (execute_agent.py:867) is absorbed into reconcile_aggregate as an L3-targets->PlannedState coverage check and deleted from execute_agent. `land_balance.py` (L1 vs L4 area closure) is referenced, not absorbed. Main-graph wiring deferred to Wave M.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, no LangGraph (module-level functions, mirroring prior waves).

## Global Constraints
- LF line endings, 4-space indent, double quotes, no trailing whitespace
- Tests run from `backend/` (i.e. `python -m pytest tests/unit/reconcile/ -v`)
- Do NOT commit pre-existing uncommitted files under `docs/` (docs/design/, docs/architecture/, docs/weekly-reports/)
- Additive contracts: do NOT delete existing fields in `reconciliation_contracts.py`, `delivery_manifest_contracts.py`, or the upstream chain contracts
- `app/agent/reconcile/` must have ZERO `advisory_crosswalks` imports (guardrail)
- Reconstruct the chain in the reconcile layer — do NOT modify upstream contracts (SpatialReferenceSpec `extra:"forbid"` stays; ParcelChange gets no new field)
- Absorb `_build_l3_l4_consistency_report` into `reconcile_aggregate`; delete the dict helper from execute_agent.py; `_validate_node` no longer calls it
- `land_balance.py` stays in spatial_ops (reference, don't absorb)
- Reconcile gate: 4 routes (PASS/RETRY_L3/RETRY_EXECUTE/HUMAN); L3 for text-source gaps, EXECUTE for worker gaps, HUMAN for ties/drift
- Main-graph wiring deferred to Wave M (deliver module only)
- Keep the 3 pre-existing failures unchanged (kg->data, catalog_session_context x2)
- Branch: `refactor/phase1-planning-context` (continuing after Wave J)

---

### Task 1: enrich RECONCILE contracts + CoverageMatrixRow

**Files:**
- Modify: `backend/app/modules/schema/contracts/reconciliation_contracts.py`
- Create: `backend/tests/unit/contracts/test_reconciliation_contracts.py`

**Interfaces:**
- Consumes: `ContractMeta`, `Provenance` (existing)
- Produces (additive, keep existing classes):
  - `CoverageMatrixRow(BaseModel)`: `intervention_id: str = ""`, `spec_index: int | None = None`, `candidate_site_id: str = ""`, `selected_bsm: str = ""`, `change_bsm: str = ""`, `planned_parcel_bsm: str = ""`, `status: Literal["covered","partial","missing"] = "missing"`
  - Modify `CoverageMatrix.rows: list[CoverageMatrixRow]` (upgrade from `list[dict]`; additive)
  - Add `responsible_stage: Literal["L3","PARSE","GROUND","SELECT","EXECUTE"] = "EXECUTE"` to `ReconciliationInconsistency` (additive)
- Align with `TraceabilityEntry` (delivery_manifest_contracts.py) vocabulary

- [ ] **Step 1: Write the failing test** — CoverageMatrixRow constructs with all fields + status Literal; CoverageMatrix accepts list[CoverageMatrixRow]; ReconciliationInconsistency carries responsible_stage
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** contract enrichment
- [ ] **Step 4: Run test to verify it passes** + existing `test_execute_validate_reconcile_deliver.py` no regression
- [ ] **Step 5: Commit**: `feat(wave-k): enrich RECONCILE contracts + CoverageMatrixRow`

---

### Task 2: reconcile checks (chain coverage + quantitative drift)

**Files:**
- Create: `backend/app/agent/reconcile/checks.py`
- Create: `backend/tests/unit/reconcile/__init__.py`, `backend/tests/unit/reconcile/test_checks.py`

**Interfaces:**
- Consumes: `PlanningProgram`/`PlanningIntervention` (l3_contracts.py), `SpatialReferenceSpec` (spatial_reference_contracts.py), `GroundingResult`/`CandidateSite` (grounding_contracts.py), `SiteSelectionDecision` (selection_contracts.py), `ParcelChangeSet`/`ParcelChange` (parcel_change_contracts.py), `PlannedState`/`PlannedParcel` (planned_state_contracts.py), `SpatialPlanningIntent` (parse_contracts.py)
- Produces (each returns `list[ReconciliationInconsistency]`, with `responsible_stage`):
  1. `check_intervention_coverage(program, specs)` — interventions without a compiled spec; stage L3
  2. `check_spec_candidate_coverage(specs, grounding_result)` — specs with no CandidateSite; stage GROUND
  3. `check_candidate_selection_coverage(grounding_result, decision)` — candidate source_parcels not in selected_combination; stage SELECT
  4. `check_selection_change_coverage(decision, changeset)` — selected BSMs with no ParcelChange (bsm/derived_from_bsms match); stage EXECUTE
  5. `check_change_planned_coverage(changeset, planned_state)` — changes with no PlannedParcel; stage EXECUTE
  6. `check_quantitative_drift(program, planned_state)` — planned area vs intervention `area_range_ha` deviation (> tolerance); stage L3
- Deterministic, no LLM, no advisory_crosswalks, no kg imports

- [ ] **Step 1: Write the failing test** — one case per check (full coverage -> no inconsistency; a gap -> inconsistency with correct responsible_stage)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** `checks.py`
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-k): reconcile checks (chain coverage + quantitative drift)`

---

### Task 3: reconcile_aggregate (orchestrator -> ReconciliationReport)

**Files:**
- Create: `backend/app/agent/reconcile/aggregate.py` (`reconcile_aggregate`, `build_coverage_matrix`)
- Create: `backend/app/agent/reconcile/__init__.py` (export `reconcile_aggregate`)
- Create: `backend/tests/unit/reconcile/test_aggregate.py`

**Interfaces:**
- Consumes: 6 check functions + `_build_l3_l4_consistency_report` logic (absorbed), all 6 chain artifacts, `Provenance`
- Produces: `reconcile_aggregate(program, specs, grounding_result, decision, changeset, planned_state, intent, *, run_id="") -> ReconciliationReport`
  - Run all 6 checks + the absorbed L3-targets->PlannedState coverage (project placement, road count, zone area delta)
  - `build_coverage_matrix(...)`: iterate `program.interventions`, for each trace spec -> candidate -> selection -> change -> planned via BSM thread + `ProjectTarget.project_id` + positional alignment; fill `CoverageMatrixRow` with status covered/partial/missing; report positional misalignment as inconsistency
  - `inconsistencies` aggregated with `responsible_stage`
  - `provenance` = Provenance(source="reconcile_aggregate", run_id=..., module="app.agent.reconcile.aggregate")
- Deterministic

- [ ] **Step 1: Write the failing test** — full chain -> CoverageMatrix rows all covered, no inconsistencies; a gap in the chain -> row status missing + inconsistency; positional misalignment detected
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** aggregate + coverage matrix builder
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-k): reconcile_aggregate (orchestrator -> ReconciliationReport)`

---

### Task 4: reconcile gate (4-way)

**Files:**
- Create: `backend/app/agent/reconcile/gate.py` (`evaluate_reconcile_gate`, `reconcile_gate_route`)
- Modify: `backend/app/agent/reconcile/__init__.py` (export gate functions)
- Create: `backend/tests/unit/reconcile/test_gate.py`

**Interfaces:**
- Consumes: `ReconciliationReport`, `GateDecision`, `PendingRequest`, `StageId` (workflow_contracts.py)
- Produces: `evaluate_reconcile_gate(report) -> GateDecision` with routes:
  - `PASS`: no inconsistencies (or all warnings)
  - `RETRY_L3`: most error inconsistencies attributed to L3 (text source)
  - `RETRY_EXECUTE`: most error inconsistencies attributed to EXECUTE (worker gap)
  - `HUMAN`: tie/mixed-stage or quantitative drift
- Mirror `validate/gate.py` style (stage="reconcile", GateDecision + PendingRequest with context["reason"])
- Precedence: PASS if no errors; else HUMAN if tie/mixed; else dominant stage (L3->RETRY_L3, EXECUTE->RETRY_EXECUTE)

- [ ] **Step 1: Write the failing test** — one case per route + tie -> HUMAN
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** gate
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-k): reconcile gate (4-way: PASS/RETRY_L3/RETRY_EXECUTE/HUMAN)`

---

### Task 5: reconcile review package

**Files:**
- Create: `backend/app/agent/reconcile/review.py` (`build_reconcile_review_package`)
- Modify: `backend/app/agent/reconcile/__init__.py` (export review function)
- Create: `backend/tests/unit/reconcile/test_review.py`

**Interfaces:**
- Consumes: `ReconciliationReport`, `GateDecision`
- Produces: `build_reconcile_review_package(report, gate) -> dict` with 8 sections (Chinese headers, JSON-serializable):
  1. 覆盖矩阵摘要 (row count + status distribution)
  2. 链覆盖详情 (per-link covered/missing counts)
  3. 不一致清单 (ReconciliationInconsistency list)
  4. 面积偏差详情
  5. 按阶段归因 (responsible_stage grouping)
  6. 向后谱系 (PlannedState -> change -> selection -> candidate -> spec -> intervention trace)
  7. Gate 决定 + 路由
  8. 来源追溯 (provenance via model_dump(mode="json"))

- [ ] **Step 1: Write the failing test** — 8 sections present, JSON-serializable
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** review
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-k): reconcile review package`

---

### Task 6: absorb _build_l3_l4_consistency_report

**Files:**
- Modify: `backend/app/agent/execute/execute_agent.py` (delete `_build_l3_l4_consistency_report`; `_validate_node` stops calling it)
- Modify: `backend/app/agent/execute/execute_state.py` (add `reconciliation_report: Optional[Any] = None`)
- Create: `backend/tests/unit/reconcile/test_absorb_l3_l4.py`

**Interfaces:**
- `_build_l3_l4_consistency_report` (execute_agent.py:867-956) deleted; its logic (expected_projects/roads/zones vs placed_projects/road_count/zone_area) absorbed into `reconcile_aggregate` (Task 3)
- `_validate_node` no longer calls it; `validation_result["l3_l4_consistency"]` set from `state.reconciliation_report` if present else omitted/None
- `ExecuteAgentState.reconciliation_report: Optional[Any] = None` (RECONCILE subgraph output; wired in Wave M)
- Verify no remaining reference to `_build_l3_l4_consistency_report` in execute_agent.py

- [ ] **Step 1: Write the failing test** — reconcile_aggregate covers project/road/zone consistency (from a fixture); execute_agent.py has no `_build_l3_l4_consistency_report` definition/reference (AST check)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** delete + state field + _validate_node update
- [ ] **Step 4: Run test to verify it passes** + execute tests no regression + full suite (3 pre-existing failures only)
- [ ] **Step 5: Commit**: `refactor(wave-k): absorb _build_l3_l4_consistency_report into reconcile`

---

### Task 7: guardrails

**Files:**
- Create: `backend/tests/unit/reconcile/test_no_crosswalk_imports.py`

**Interfaces:**
- AST scan: `app/agent/reconcile/*.py` must NOT import `advisory_crosswalks`
- sys.modules snapshot: importing `app.agent.reconcile` must not load advisory_crosswalks
- Mirror `tests/unit/validate/test_no_crosswalk_imports.py` pattern (BOM-tolerant utf-8-sig)

- [ ] **Step 1: Write the failing test** (verify matcher catches planted import)
- [ ] **Step 2: Run test to verify it runs** (should be green — no violations)
- [ ] **Step 3: Implement** guardrail tests
- [ ] **Step 4: Run test to verify it passes** + full suite (1122+ new pass, 3 pre-existing failures)
- [ ] **Step 5: Commit**: `test(wave-k): guardrails (no crosswalks in reconcile)`

---

### Task 8: docs sync (uncommitted)

**Files:**
- Modify: `docs/design/10_IMPLEMENTATION_STATUS.md` (add RECONCILE row CURRENT; PlannedState row update)
- Modify: `docs/weekly-reports/2026-08-04-wave-roadmap.md` (add Wave K delivery note)

- [ ] **Step 1: Update `10_IMPLEMENTATION_STATUS.md`** add RECONCILE row + update PlannedState row
- [ ] **Step 2: Update `2026-08-04-wave-roadmap.md`** with Wave K delivery summary
- [ ] **Step 3: Verify git status** — docs changes remain uncommitted; no `docs/` staging
- [ ] **No commit** (docs rule)

---

## Verification
- RECONCILE suite: all new tests pass
- Full suite: existing 1122 + new pass, only 3 pre-existing failures remain (kg->data, catalog_session_context x2), zero new regressions
- Guardrails: `app/agent/reconcile/` zero advisory_crosswalks imports

## Out of scope (deferred)
- Main-graph wiring (`bootstrap/graph.py`) + reconcile_graph node/edges -> Wave M
- Contract enrichment (add intervention_id to SpatialReferenceSpec, project_ref to ParcelChange) -> later wave (Wave K reconstructs the chain instead)
- DeliveryManifest.traceability population -> Wave L
- Network accessibility -> later wave
- `kg->data` reverse dependency -> Wave M
