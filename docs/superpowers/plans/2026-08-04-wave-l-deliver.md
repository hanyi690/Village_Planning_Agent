# Wave L Implementation Plan: DELIVER Subgraph

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent DELIVER subgraph (`app/agent/deliver/`) that consumes the upstream artifacts (`PlannedState`, `ValidationReport`, `ReconciliationReport`, upstream `GateDecision`s, `export_result`) and produces a typed `DeliveryManifest` with `traceability` populated from the RECONCILE `CoverageMatrix`, `deliverables` mapped from the export package, `pending_human_items` collected from delivery checks + upstream gates, and a `statutory_complete` flag that blocks "完整法定成果" when planning classification is missing (per 08_DELIVERABLES_COMPLIANCE.md §3). Add a 3-way deliver gate.

**Architecture:** Enrich the skeletal Wave A `DeliveryManifest` contract (`delivery_manifest_contracts.py`): add a `statutory_complete: bool` field + `statutory_complete_breakdown: dict[str, bool]` (additive, keep existing fields). The `app/agent/deliver/` subgraph mirrors the Wave J/K structure: `checks.py` (3 deterministic checks returning `list[HumanItem]`: statutory layers complete, traceability complete, classification for statutory), `aggregate.py` (deliver_aggregate populating traceability from CoverageMatrixRow, deliverables from export_result, pending_human_items from checks + upstream gates, delivery_gate via `spatial_ops/land_balance.py:check_delivery_gate`, statutory_complete determination), `gate.py` (3-way PASS/RETRY_VALIDATE/HUMAN), `review.py` (8-section review package). `check_delivery_gate` stays in spatial_ops (reference, don't absorb — mirrors Wave K's treatment of land_balance.py). The `CoverageMatrixRow -> TraceabilityEntry` field mapping is mechanical (vocabulary already aligned per Wave K): `spec_index: int|None -> requirement_id: str`, BSM thread -> selection/change/planned IDs. Upstream `PendingRequest`s with `feedback_route == "HUMAN"` are collected and converted to `HumanItem`s. `statutory_complete` is True iff `delivery_gate.passed` AND no blocking HumanItems AND classification check passed. Main-graph wiring deferred to Wave M.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, no LangGraph (module-level functions, mirroring prior waves).

## Global Constraints
- LF line endings, 4-space indent, double quotes, no trailing whitespace
- Tests run from `backend/` (i.e. `python -m pytest tests/unit/deliver/ -v`)
- Do NOT commit pre-existing uncommitted files under `docs/` (docs/design/, docs/architecture/, docs/weekly-reports/)
- Additive contracts: do NOT delete existing fields in `delivery_manifest_contracts.py` or upstream chain contracts
- `app/agent/deliver/` must have ZERO `advisory_crosswalks` imports (guardrail)
- Reference `spatial_ops/land_balance.py:check_delivery_gate` — do NOT absorb
- Reference `spatial_ops/export_package.py:export_gdb_package` output dict — do NOT modify
- Deliver gate: 3 routes (PASS/RETRY_VALIDATE/HUMAN); RETRY_VALIDATE when dominant blocking issue is classification_missing (fixable), HUMAN for unfixable/tie/upstream
- Main-graph wiring deferred to Wave M (deliver module only; do NOT touch `bootstrap/graph.py` or `layout_pipeline.py`)
- Keep the 3 pre-existing failures unchanged (kg->data, catalog_session_context x2)
- Branch: `refactor/phase1-planning-context` (continuing after Wave K)

---

### Task 1: enrich DeliveryManifest contracts (statutory_complete)

**Files:**
- Modify: `backend/app/modules/schema/contracts/delivery_manifest_contracts.py`
- Modify: `backend/tests/unit/contracts/test_execute_validate_reconcile_deliver.py`

**Interfaces:**
- Consumes: `ContractMeta`, `Provenance` (existing)
- Produces (additive, keep existing classes):
  - Modify `DeliveryManifest`: add `statutory_complete: bool = False`
  - Modify `DeliveryManifest`: add `statutory_complete_breakdown: dict[str, bool] = Field(default_factory=dict)`
- Align with 08_DELIVERABLES_COMPLIANCE.md §3 (blocking issue -> diagnostic bundle, not final output)

- [ ] **Step 1: Write the failing test** — DeliveryManifest defaults statutory_complete=False + breakdown={}; DeliveryManifest(statutory_complete=True, statutory_complete_breakdown={...}) round-trips
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** contract enrichment (additive)
- [ ] **Step 4: Run test to verify it passes** + `test_execute_validate_reconcile_deliver.py` no regression
- [ ] **Step 5: Commit**: `feat(wave-l): enrich DeliveryManifest with statutory_complete field`

---

### Task 2: deliver checks (statutory layers + traceability + classification)

**Files:**
- Create: `backend/app/agent/deliver/checks.py`
- Create: `backend/tests/unit/deliver/__init__.py`, `backend/tests/unit/deliver/test_checks.py`

**Interfaces:**
- Consumes: `CoverageMatrix`/`CoverageMatrixRow` (reconciliation_contracts.py), `ValidationReport`/`ValidationCheck` (validation_report_contracts.py), `HumanItem` (delivery_manifest_contracts.py), `dict | None` (export_result)
- Produces (each returns `list[HumanItem]`; empty = passed):
  1. `check_statutory_layers_complete(export_result)` — export_result None or missing required layer keys -> blocking HumanItem; stage DELIVER
  2. `check_traceability_complete(coverage_matrix)` — rows with status != "covered" -> non-blocking HumanItem (warning)
  3. `check_classification_for_statutory(validation_report)` — classification_missing check failed -> blocking HumanItem (block "完整法定成果")
- Deterministic, no LLM, no advisory_crosswalks, no kg imports

- [ ] **Step 1: Write the failing test** — one case per check (pass + fail variants; None export; partial traceability warning; classification missing blocking)
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** `checks.py`
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-l): deliver checks (statutory layers + traceability + classification)`

---

### Task 3: deliver_aggregate (orchestrator -> DeliveryManifest)

**Files:**
- Create: `backend/app/agent/deliver/aggregate.py` (`deliver_aggregate`, `build_traceability_from_coverage`, `build_deliverables_from_export`, `collect_upstream_human_items`)
- Modify: `backend/app/agent/deliver/__init__.py` (export deliver functions)
- Create: `backend/tests/unit/deliver/test_aggregate.py`

**Interfaces:**
- Consumes: `PlannedState` (planned_state_contracts.py), `ValidationReport` (validation_report_contracts.py), `ReconciliationReport`/`CoverageMatrixRow` (reconciliation_contracts.py), `GateDecision`/`PendingRequest` (workflow_contracts.py), `DeliveryManifest`/`Deliverable`/`TraceabilityEntry`/`HumanItem`/`DeliveryGate` (delivery_manifest_contracts.py), `dict | None` (export_result), `Provenance`
- Produces:
  - `build_traceability_from_coverage(coverage_matrix) -> list[TraceabilityEntry]` — map CoverageMatrixRow fields: intervention_id->intervention_id, spec_index->requirement_id (str), candidate_site_id->candidate_id, selected_bsm->selection_id, change_bsm->change_id, planned_parcel_bsm->planned_ref, deliverable_id=""
  - `build_deliverables_from_export(export_result) -> list[Deliverable]` — map exported_files list to Deliverable entries
  - `collect_upstream_human_items(upstream_gates) -> list[HumanItem]` — convert HUMAN-route PendingRequests to HumanItems
  - `deliver_aggregate(planned_state, validation_report, reconciliation_report, upstream_gates, export_result, *, run_id="") -> DeliveryManifest`
    - Run 3 checks -> check_human_items
    - collect_upstream_human_items -> upstream_human_items
    - `check_delivery_gate(current_parcels, planned_state.parcels, ...)` (from spatial_ops.land_balance) -> delivery_gate
    - merge HumanItems -> pending_human_items
    - statutory_complete = delivery_gate.passed AND no blocking HumanItems AND classification check passed
    - statutory_complete_breakdown = {"delivery_gate": ..., "no_blocking_items": ..., "classification_complete": ...}
    - provenance = Provenance(source="deliver_aggregate", run_id=..., module="app.agent.deliver.aggregate")
- Deterministic

- [ ] **Step 1: Write the failing test** — full pass -> statutory_complete True, traceability populated; classification missing -> blocking HumanItem + statutory_complete False; export_result None -> blocking layers item; upstream HUMAN gate -> HumanItem collected
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** aggregate + helpers
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-l): deliver_aggregate (orchestrator -> DeliveryManifest)`

---

### Task 4: deliver gate (3-way)

**Files:**
- Create: `backend/app/agent/deliver/gate.py` (`evaluate_deliver_gate`, `deliver_gate_route`)
- Modify: `backend/app/agent/deliver/__init__.py` (export gate functions)
- Create: `backend/tests/unit/deliver/test_gate.py`

**Interfaces:**
- Consumes: `DeliveryManifest`, `GateDecision`, `PendingRequest`, `StageId` (workflow_contracts.py)
- Produces: `evaluate_deliver_gate(manifest) -> GateDecision` with routes:
  - `PASS`: statutory_complete is True
  - `RETRY_VALIDATE`: dominant blocking issue is classification_missing (item_id starts "hi-class-") — fixable by re-validation
  - `HUMAN`: export failure (hi-layers-), upstream unresolved (hi-upstream-), tie, or no blocking item but delivery_gate failed
- Mirror `reconcile/gate.py` style (stage="deliver", GateDecision + PendingRequest with context["reason"])
- Precedence: PASS if statutory_complete; else HUMAN on tie/unfixable; else RETRY_VALIDATE on classification

- [ ] **Step 1: Write the failing test** — one case per route + tie -> HUMAN
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** gate
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-l): deliver gate (3-way: PASS/RETRY_VALIDATE/HUMAN)`

---

### Task 5: deliver review package

**Files:**
- Create: `backend/app/agent/deliver/review.py` (`build_deliver_review_package`)
- Modify: `backend/app/agent/deliver/__init__.py` (export review function)
- Create: `backend/tests/unit/deliver/test_review.py`

**Interfaces:**
- Consumes: `DeliveryManifest`, `GateDecision`
- Produces: `build_deliver_review_package(manifest, gate) -> dict` with 8 sections (Chinese headers, JSON-serializable):
  1. 交付清单 (deliverables list)
  2. 溯源谱系 (TraceabilityEntry list mapped from CoverageMatrixRow)
  3. 出口门槛 (DeliveryGate check results: land_balance_closed, three_line_violations, protected_intrusions, changed_parcels_pct, zones_complete, passed, failures)
  4. 未决人工项 (HumanItem list)
  5. 规划分类缺失 (classification_missing check outcome)
  6. 法定成果完整性 (statutory_complete + breakdown)
  7. Gate 决定 + 路由
  8. 来源追溯 (provenance via model_dump(mode="json"))
- Mirror `reconcile/review.py` structure (_build_gate_decision, _build_provenance copy-verbatim)

- [ ] **Step 1: Write the failing test** — 8 sections present, JSON-serializable
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** review
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-l): deliver review package`

---

### Task 6: state field integration

**Files:**
- Modify: `backend/app/agent/execute/execute_state.py`

**Interfaces:**
- Modify `ExecuteAgentState`: add `delivery_manifest: Optional[Any] = None  # DeliveryManifest - DELIVER output (Wave M wires)` (mirrors `reconciliation_report` field)

- [ ] **Step 1: Write the failing test** — ExecuteAgentState defaults delivery_manifest=None; round-trips
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** state field
- [ ] **Step 4: Run test to verify it passes** + execute tests no regression
- [ ] **Step 5: Commit**: `feat(wave-l): add delivery_manifest field to ExecuteAgentState`

---

### Task 7: guardrails

**Files:**
- Create: `backend/tests/unit/deliver/test_no_advisory_crosswalks.py`

**Interfaces:**
- AST scan: `app/agent/deliver/*.py` must NOT import `advisory_crosswalks`
- sys.modules snapshot: importing `app.agent.deliver` must not load advisory_crosswalks
- Mirror `tests/unit/execute/test_no_advisory_crosswalks.py` pattern (BOM-tolerant utf-8-sig)

- [ ] **Step 1: Write the failing test** (verify matcher catches planted import)
- [ ] **Step 2: Run test to verify it runs** (should be green — no violations)
- [ ] **Step 3: Implement** guardrail tests
- [ ] **Step 4: Run test to verify it passes** + full suite (1179+ new pass, 3 pre-existing failures)
- [ ] **Step 5: Commit**: `test(wave-l): guardrails (no crosswalks in deliver)`

---

### Task 8: docs sync (uncommitted)

**Files:**
- Modify: `docs/design/10_IMPLEMENTATION_STATUS.md` (add DELIVER row CURRENT; update Delivery Gate row; remove "DeliveryManifest traceability 填充属 Wave L" from PlannedState row)
- Modify: `docs/weekly-reports/2026-08-04-wave-roadmap.md` (add Wave L delivery note)

- [ ] **Step 1: Update `10_IMPLEMENTATION_STATUS.md`** add DELIVER row + update Delivery Gate + PlannedState rows
- [ ] **Step 2: Update `2026-08-04-wave-roadmap.md`** with Wave L delivery summary
- [ ] **Step 3: Verify git status** — docs changes remain uncommitted; no `docs/` staging
- [ ] **No commit** (docs rule)

---

## Verification
- DELIVER suite: all new tests pass
- Full suite: existing 1179 + new pass, only 3 pre-existing failures remain (kg->data, catalog_session_context x2), zero new regressions
- Guardrails: `app/agent/deliver/` zero advisory_crosswalks imports
- `DeliveryManifest.statutory_complete` blocks "完整法定成果" when planning classification missing
- `TraceabilityEntry` populated from `CoverageMatrixRow` (Wave K -> Wave L bridge)
- `pending_human_items` collected from deliver checks + upstream HUMAN gates
- Main graph untouched (`bootstrap/graph.py`, `layout_pipeline.py` unmodified)

## Out of scope (deferred)
- Main-graph wiring (`bootstrap/graph.py`) + deliver node/edges -> Wave M
- Replacing `_export_gdb_node`/`_render_map_node` with deliver subgraph -> Wave M
- Adding "DELIVER" stage to `step_report.py` VALID_STAGES -> Wave M
- `kg->data` reverse dependency -> Wave M
- Replacing legacy `human_review_queue.json` mechanism -> Wave M
- Planning-text `legal_basis` integration (planning_text/content_extractor.py) -> later wave
- Building Deliverables from PlannedState + render config (一图一表一规则) -> later wave (Wave L maps from export_result)
