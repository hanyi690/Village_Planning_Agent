# Post-L3 Chain Repair Plan (P0 Critical Path)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore end-to-end runnability of the unified planning graph's post-L3 chain (PARSE -> GROUND -> SELECT -> EXECUTE -> VALIDATE -> RECONCILE -> DELIVER) by eliminating state-loss, missing-input, fail-open, dual-graph, and false-completion defects, then collapse to a single post-L3 implementation.

**Architecture:** The main graph `create_unified_planning_graph` (graph.py) is the single source of truth. Its post-L3 nodes (post_l3_main_nodes.py) operate directly on `AgentState`. The standalone `post_l3_chain` (post_l3_chain.py / post_l3_nodes.py / post_l3_state.py) is strictly more complete in logic but is a second graph that breaks HITL resume. This plan ports the standalone's missing logic (ExecutionPlan, evidence retrieval, typed refs, fail-closed) into the main-graph nodes, unifies HITL onto the main graph, then deletes the standalone.

**Tech Stack:** Python 3.11, LangGraph 1.2.8, Pydantic V2, pytest, FastAPI, React/TypeScript frontend.

## Diagnostic Basis (verified against current code)

Each P0 below is confirmed by direct file inspection during planning:

- **P0-1 State schema drops outputs.** `AgentState` (state.py:200-260) declares `execution_plan`, `parcel_changeset`, `validation_report` but NOT `planned_state`, `execution_errors`, `parcel_changeset_ref`, `planned_state_ref`, `grounding_result_ref`, `site_selection_ref`. `execute_node` (post_l3_main_nodes.py:364-371) returns all of them -> LangGraph 1.2.8 filters undeclared keys -> VALIDATE/RECONCILE read `None`.
- **P0-2 No ExecutionPlan in main graph.** `select_node` (post_l3_main_nodes.py:275-301) lacks `build_execution_plan()`; standalone (post_l3_nodes.py:300) has it. EXECUTE consumes `execution_plan` from state (post_l3_main_nodes.py:321) -> always `None`.
- **P0-3 VALIDATE fail-open.** `validate_aggregate` (validate/aggregate.py:60-61) substitutes empty `SimpleNamespace` when `planned_state is None` instead of emitting a blocking check. Also, `validate_node` (post_l3_main_nodes.py:390) passes the whole `IntentCompilationResult`; `check_accessibility`/`check_contract_completeness` may treat project targets as empty.
- **P0-4 RECONCILE missing inputs.** `reconcile_node` (post_l3_main_nodes.py:426) uses `state.get("planning_program")` directly instead of the existing `_load_planning_program(state)` helper (post_l3_main_nodes.py:201-220) that falls back to `l3_program_ref` artifact store. `build_coverage_matrix` (reconcile/aggregate.py:63-70) uses positional index `i` for intervention->spec and spec->candidate pairing.
- **P0-6 Two-graph HITL.** Main graph (graph.py:146,182-208) registers `human_review_node` that calls `interrupt()` writing `human_review_items`. But `resume_post_l3_chain` (post_l3_resume.py:116-135) rebuilds the **standalone** `build_post_l3_chain` and resumes it with `Command(resume=...)` - a different compiled graph, same `thread_id`. API reads `post_l3_pending_review`; main graph writes `human_review_items` -> empty review list.
- **P0-7 Premature completed.** `state_to_ui_status` (state.py:386-387) checks `phase == "completed"` BEFORE `is_interrupted`, so an interrupted post-L3 chain still reports `completed` to the UI and SSE.
- **P0-8 Layer naming drift (partial).** `export_package.py:77` maps `ecological_redline` -> `ecological_redline_geojson`; `map_layers.py:88` uses `ecological_protection_geojson`. `deliver/checks.py` now routes via `GDB_LAYER_REGISTRY` (`_statutory_source_for`), so correctness depends on the registry being the single naming authority.

## Global Constraints

- **Line endings:** LF for Python/TS/TSX; CRLF only for .bat/.cmd.
- **Indentation:** 4 spaces (Python), 2 spaces (TS/TSX).
- **Quotes:** double (Python), single (frontend).
- **No comments added to code unless explicitly requested by a task step.**
- **No `git commit` unless a task step explicitly says to commit.**
- **Edit safety:** per AGENTS.md, `Edit`/`edit` `oldString` must be 1-2 unique non-Chinese lines; avoid line-trailing comments with emoji; fall back to `sed -i <line>c\` by line number if matching fails.
- **Tests:** backend uses pytest; frontend uses Jest. Run the relevant suite after each task.
- **LangGraph 1.2.8:** undeclared state keys are filtered; `Command(resume=...)` resumes the SAME compiled graph+thread; `Command(resume=..., update=...)` is not the official resume pattern - use `update` via the state-update interface first when needed.
- **Backwards compat:** `gis_agent_entry.gis_agent_node` must keep working until Task 7 deletes the standalone; do not break its callers mid-plan.

---

## File Structure (what changes)

| File | Role | Change |
|---|---|---|
| `backend/app/agent/plan_state/state.py` | `AgentState` schema + `state_to_ui_status` | Add 6 missing post-L3 fields; fix completion/interrupt precedence |
| `backend/app/agent/bootstrap/post_l3_main_nodes.py` | Main-graph post-L3 nodes | Port ExecutionPlan build, evidence retrieval, typed refs, RECONCILE program load, fail-closed VALIDATE |
| `backend/app/agent/validate/aggregate.py` | VALIDATE aggregate | Fail-closed on missing planned_state |
| `backend/app/agent/reconcile/aggregate.py` | RECONCILE coverage matrix | ID-based joins (deferred: schema-level ID work tracked but positional fallback retained behind a flag in this plan's scope) |
| `backend/app/agent/bootstrap/graph.py` | Main graph builder + main `human_review_node` | Already correct; Task 7 removes any stale standalone references |
| `backend/app/services/post_l3_resume.py` | HITL resume API | Rewrite to resume the **main** graph via `Command(resume=...)`; unify key to `human_review_items` |
| `backend/app/services/runtime.py` | Runtime + SSE | Stop sending `completed` while post-L3 unfinished; gate completion on `deliver_gate=PASS` |
| `backend/app/agent/bootstrap/post_l3_chain.py` | Standalone chain builder | **Delete** in Task 7 |
| `backend/app/agent/bootstrap/post_l3_nodes.py` | Standalone chain node impls | **Delete** in Task 7 (after logic ported) |
| `backend/app/agent/bootstrap/post_l3_state.py` | Standalone chain state | **Delete** in Task 7 |
| `backend/app/agent/bootstrap/gis_agent_entry.py` | L3->post-L3 entry | Update to not invoke standalone chain; main graph already drives post-L3 nodes |
| `backend/tests/agent/test_post_l3_main_nodes.py` | New unit tests for main-graph nodes | Create |
| `backend/tests/agent/test_unified_graph_replay.py` | New integration test for main-graph post-L3 replay | Create |
| `backend/app/modules/spatial_ops/output/export_package.py` | Export layer naming | Verify against `GDB_LAYER_REGISTRY` (out of P0 critical path; tracked in Task 8 notes) |

---

## Task Ordering Rationale

Tasks 1-4 make the chain **run** (state flows, ExecutionPlan exists, RECONCILE has inputs, VALIDATE blocks on missing). Task 5 makes retries **meaningful** (feedback consumed, no same-input loop). Task 6 stops **lying** to the UI about completion. Task 7 collapses to **one** graph + one resume API. Task 8 is the integration test that proves it. Each task ends with a green test cycle and is independently reviewable.

---

## Task 1: Add missing post-L3 state channels to AgentState

**Files:**
- Modify: `backend/app/agent/plan_state/state.py` (AgentState class, ~line 240-260; `create_initial_state`, ~line 339-355)
- Test: `backend/tests/agent/test_state_schema.py` (new)

**Interfaces:**
- Consumes: none
- Produces: `AgentState` now declares `planned_state`, `execution_errors`, `grounding_result_ref`, `site_selection_ref`, `parcel_changeset_ref`, `planned_state_ref` (all `Optional[Any]` / `Dict[str, Any]` default). `create_initial_state` seeds them. Later tasks write/read these keys.

- [ ] **Step 1: Write failing test**

```python
# backend/tests/agent/test_state_schema.py
from app.agent.plan_state.state import AgentState, create_initial_state

REQUIRED_POST_L3_KEYS = (
    "planned_state", "execution_errors",
    "grounding_result_ref", "site_selection_ref",
    "parcel_changeset_ref", "planned_state_ref",
)

def test_agent_state_declares_post_l3_output_keys():
    hints = AgentState.__annotations__
    for key in REQUIRED_POST_L3_KEYS:
        assert key in hints, f"AgentState missing post-L3 channel: {key}"

def test_create_initial_state_seeds_post_l3_outputs():
    s = create_initial_state("s1", "v1", "data")
    for key in REQUIRED_POST_L3_KEYS:
        assert key in s, f"create_initial_state missing seed for: {key}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/agent/test_state_schema.py -v`
Expected: FAIL on `planned_state`, `execution_errors`, `parcel_changeset_ref`, `planned_state_ref` (the four currently undeclared).

- [ ] **Step 3: Add the fields to AgentState**

In `state.py`, inside the `# EXECUTE 输出` block (after `allocated_geojson: Dict[str, Any]` at line 243), add:

```python
    planned_state: Optional[Any]  # PlannedState (typed) - EXECUTE output
    execution_errors: Annotated[List[Dict[str, Any]], _replace_or_merge_lists]  # EXECUTE errors
    parcel_changeset_ref: Optional[Dict[str, Any]]  # ParcelChangeSet artifact ref
    planned_state_ref: Optional[Dict[str, Any]]  # PlannedState artifact ref
```

In the `# GROUND 输出` block (after `ground_gate`), add:

```python
    grounding_result_ref: Optional[Dict[str, Any]]  # GroundingResult artifact ref
```

In the `# SELECT 输出` block (after `select_gate`), add:

```python
    site_selection_ref: Optional[Dict[str, Any]]  # SiteSelectionDecision artifact ref
```

- [ ] **Step 4: Seed them in `create_initial_state`**

In the `# ── Wave M: post-L3 主图独立节点链初始值 ──` block (around line 339), add after `"allocated_geojson": {},`:

```python
        "planned_state": None,
        "execution_errors": [],
        "grounding_result_ref": None,
        "site_selection_ref": None,
        "parcel_changeset_ref": None,
        "planned_state_ref": None,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/agent/test_state_schema.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend suite to catch regressions**

Run: `pytest backend/tests -x -q`
Expected: 1434+ passed (no new failures).

---

## Task 2: Main-graph SELECT builds and persists ExecutionPlan

**Files:**
- Modify: `backend/app/agent/bootstrap/post_l3_main_nodes.py:275-301` (`select_node`)
- Test: `backend/tests/agent/test_post_l3_main_nodes.py` (new)

**Interfaces:**
- Consumes: `state["intent"]` (IntentCompilationResult), `state["grounding_result"]`, PlanningContext
- Produces: `state["execution_plan"]` (ExecutionPlan typed) - consumed by `execute_node` (post_l3_main_nodes.py:321) and the ExecuteAgentState init.

- [ ] **Step 1: Write failing test**

```python
# backend/tests/agent/test_post_l3_main_nodes.py
import pytest
from app.agent.bootstrap import post_l3_main_nodes as M

@pytest.mark.asyncio
async def test_select_node_writes_execution_plan(monkeypatch):
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.grounding_contracts import GroundingResult

    plan_intent = SpatialPlanningIntent(project_targets=[object()])
    intent = IntentCompilationResult(typed_intent=plan_intent, raw_intent={})

    async def fake_ctx(s):
        return None
    monkeypatch.setattr(M, "_resolve_context", fake_ctx)
    monkeypatch.setattr(M, "_persist_artifact", lambda *a, **k: None)

    from app.agent.select import aggregate as sel_agg
    monkeypatch.setattr(sel_agg, "select_aggregate",
        lambda g, i, c: (object(), []))
    from app.agent.select import gate as sel_gate
    monkeypatch.setattr(sel_gate, "evaluate_select_gate",
        lambda d, target_count: object())

    state = {"intent": intent, "grounding_result": GroundingResult(candidates=[]),
             "upstream_gates": [], "retry_counts": {}}
    out = await M.select_node(state)
    assert "execution_plan" in out, "select_node must write execution_plan"
    assert out["execution_plan"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/agent/test_post_l3_main_nodes.py::test_select_node_writes_execution_plan -v`
Expected: FAIL - `execution_plan` key absent from return dict.

- [ ] **Step 3: Port `build_execution_plan` into main-graph `select_node`**

In `post_l3_main_nodes.py`, add to the top-level imports (or inline in the function following the file's existing lazy-import convention):

```python
from app.agent.execute.plan_builder import build_execution_plan
```

In `select_node`, after `gate = evaluate_select_gate(...)` and before `ref = _persist_artifact(...)`, add:

```python
    execution_plan = build_execution_plan(
        intent,
        decision,
        briefs,
        run_id=_run_id(state),
        context_version=_context_version(state),
    )
```

In the return dict of `select_node`, add the key:

```python
        "execution_plan": _dump(execution_plan),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/agent/test_post_l3_main_nodes.py::test_select_node_writes_execution_plan -v`
Expected: PASS

- [ ] **Step 5: Run backend suite**

Run: `pytest backend/tests -x -q`
Expected: no regressions.

---

## Task 3: RECONCILE loads PlanningProgram from ref (fail-closed on missing)

**Files:**
- Modify: `backend/app/agent/bootstrap/post_l3_main_nodes.py:426` (`reconcile_node`)
- Test: `backend/tests/agent/test_post_l3_main_nodes.py` (extend)

**Interfaces:**
- Consumes: `state["l3_program_ref"]` (artifact ref) - already written by `gis_agent_entry`.
- Produces: RECONCILE report now receives a non-None `PlanningProgram` when the ref is valid; gate blocks (RETRY_L3) when program is truly absent.

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_reconcile_node_loads_program_from_ref(monkeypatch):
    calls = {}
    def fake_reconcile(program, specs, grounding, decision, changeset,
                       planned_state, intent, run_id=""):
        calls["program"] = program
        return object()
    monkeypatch.setattr(M, "_resolve_context", lambda s: None_async(s))
    from app.agent.reconcile import aggregate as ragg
    monkeypatch.setattr(ragg, "reconcile_aggregate", fake_reconcile)
    from app.agent.reconcile import gate as rgate
    monkeypatch.setattr(rgate, "evaluate_reconcile_gate", lambda r: object())

    state = {"planning_program": None, "l3_program_ref": {"artifact_id": "x"},
             "specs": [], "grounding_result": None, "site_selection": None,
             "parcel_changeset": None, "planned_state": None, "intent": None,
             "upstream_gates": [], "retry_counts": {}, "session_id": "s1"}

    async def fake_load(s):
        return object()
    monkeypatch.setattr(M, "_load_planning_program", fake_load)

    await M.reconcile_node(state)
    assert calls["program"] is not None, "reconcile must use _load_planning_program"
```

(Use a small `lambda s: None` async helper named `None_async` defined at module top of the test file if needed.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/agent/test_post_l3_main_nodes.py::test_reconcile_node_loads_program_from_ref -v`
Expected: FAIL - reconcile_node uses `state.get("planning_program")` directly, so `program` is None and the patched `_load_planning_program` is never called.

- [ ] **Step 3: Replace direct get with helper**

In `reconcile_node` (post_l3_main_nodes.py:426), change:

```python
    program = _to_typed(state.get("planning_program"), PlanningProgram)
```

to:

```python
    program = _load_planning_program(state)
```

- [ ] **Step 4: Add fail-closed gate when program is None**

After the `program = _load_planning_program(state)` line, add:

```python
    if program is None:
        from app.agent.reconcile.gate import evaluate_reconcile_gate
        from app.modules.schema.contracts.reconciliation_contracts import ReconciliationReport
        report = ReconciliationReport(
            inconsistencies=[], coverage_matrix=None, overall_passed=False,
            provenance=None, fatal_error="missing_planning_program",
        )
        gate = evaluate_reconcile_gate(report)
        return {
            "reconciliation_report": _dump(report),
            "reconcile_gate": _dump(gate),
            "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        }
```

(Adjust field names to match the actual `ReconciliationReport` schema; verify with `read` of `reconciliation_contracts.py` before implementing.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/agent/test_post_l3_main_nodes.py -v`
Expected: PASS

- [ ] **Step 6: Run backend suite**

Run: `pytest backend/tests -x -q`

---

## Task 4: VALIDATE fail-closed on missing planned_state + unpack typed intent

**Files:**
- Modify: `backend/app/agent/validate/aggregate.py:51-72` (`validate_aggregate`)
- Modify: `backend/app/agent/bootstrap/post_l3_main_nodes.py:377-407` (`validate_node`)
- Test: `backend/tests/agent/test_validate_aggregate.py` (extend or create)

**Interfaces:**
- Consumes: `state["planned_state"]` (now flows through after Task 1)
- Produces: VALIDATE gate blocks (non-PASS) when planned_state is None instead of passing on empty data.

- [ ] **Step 1: Write failing test**

```python
# backend/tests/agent/test_validate_aggregate.py
from app.agent.validate.aggregate import validate_aggregate

def test_validate_blocks_on_missing_planned_state():
    report = validate_aggregate(
        planned_state=None, changeset=None, layout_configs=None,
        intent=None, constraint_index=None, run_id="r1",
    )
    assert report.overall_passed is False
    codes = [c.check_id for c in report.checks]
    assert any("missing_planned_state" in c for c in codes), \
        "must emit a blocking missing_planned_state check"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/agent/test_validate_aggregate.py::test_validate_blocks_on_missing_planned_state -v`
Expected: FAIL - current code substitutes empty SimpleNamespace and may report `overall_passed=True`.

- [ ] **Step 3: Replace empty-state fallback with a blocking check**

In `validate/aggregate.py`, replace lines 60-61:

```python
    if planned_state is None:
        planned_state = SimpleNamespace(parcels=[], facilities=[])
```

with:

```python
    if planned_state is None:
        from app.modules.schema.contracts.validation_report_contracts import ValidationCheck
        missing_check = ValidationCheck(
            check_id="missing_planned_state",
            check_name="planned_state presence",
            passed=False,
            severity="error",
            responsible_stage="execute",
            expected_value="non-null PlannedState",
            actual_value="None",
            fix_suggestion="EXECUTE produced no planned_state; retry EXECUTE",
        )
        return ValidationReport(
            checks=[missing_check],
            overall_passed=False,
            issues_by_stage={"execute": [_check_to_issue(missing_check)]},
            adjustments=[],
            provenance=Provenance(
                source="validate_aggregate", run_id=run_id,
                module="app.agent.validate.aggregate",
                natural_language_description="blocked: planned_state is None",
            ),
        )
```

(Verify exact `ValidationCheck` field names by reading `validation_report_contracts.py` first.)

- [ ] **Step 4: Unpack typed intent in validate_node**

In `post_l3_main_nodes.py:390`, `validate_node` currently passes the whole `IntentCompilationResult`. Inspect `check_accessibility` and `check_contract_completeness` signatures. If they expect `SpatialPlanningIntent`, change:

```python
    intent = _to_typed(state.get("intent"), IntentCompilationResult)
```

to also derive the typed intent and pass it:

```python
    intent = _to_typed(state.get("intent"), IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
```

and pass `plan_intent` to `validate_aggregate` where the checks expect the typed intent. Confirm against the actual check signatures first (read `validate/checks.py`).

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/agent/test_validate_aggregate.py -v`
Expected: PASS

- [ ] **Step 6: Run backend suite**

Run: `pytest backend/tests -x -q`

---

## Task 5: Make retries consume feedback (GROUND evidence retrieval + execute input rebuild)

**Files:**
- Modify: `backend/app/agent/bootstrap/post_l3_main_nodes.py:251-269` (`ground_node`)
- Modify: `backend/app/agent/bootstrap/post_l3_main_nodes.py:307-371` (`execute_node`) - rebuild ExecutionPlan/site_selection on retry
- Test: `backend/tests/agent/test_post_l3_main_nodes.py` (extend)

**Interfaces:**
- Consumes: `state["error_feedback"]["ground"]`, `state["ground_gate"].pending_requests` (evidence_requests)
- Produces: GROUND retry calls `retrieve_evidence()`; EXECUTE retry re-derives inputs instead of replaying identical state.

- [ ] **Step 1: Write failing test for GROUND evidence retrieval on EXPLORE retry**

```python
@pytest.mark.asyncio
async def test_ground_node_calls_retrieve_evidence_on_explore_retry(monkeypatch):
    from app.agent.ground.aggregate import retrieve_evidence
    called = {"evidence": False}
    async def fake_retrieve(ctx, reqs):
        called["evidence"] = True
        return []
    monkeypatch.setattr(M, "_resolve_context", fake_ctx)
    monkeypatch.setattr(retrieve_evidence, "__wrapped__", fake_retrieve)
    state = {"ground_gate": {"feedback_route": "EXPLORE",
              "evidence_requests": [{"type": "road_access"}]},
             "specs": [], "upstream_gates": [], "retry_counts": {}}
    await M.ground_node(state)
    assert called["evidence"] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/agent/test_post_l3_main_nodes.py::test_ground_node_calls_retrieve_evidence_on_explore_retry -v`
Expected: FAIL - main-graph `ground_node` never calls `retrieve_evidence`.

- [ ] **Step 3: Port evidence retrieval from standalone**

In `ground_node` (post_l3_main_nodes.py:251-269), before `result = ground_aggregate(specs, context)`, add (mirroring post_l3_nodes.py:233-244):

```python
    from app.agent.ground.aggregate import retrieve_evidence
    prior_gate = state.get("ground_gate")
    if _gate_route(prior_gate) == "EXPLORE":
        requests = getattr(prior_gate, "evidence_requests", None)
        if requests is None and isinstance(prior_gate, dict):
            requests = prior_gate.get("evidence_requests")
        try:
            await retrieve_evidence(context, requests or None)
        except Exception as e:
            logger.warning("[post_l3:main:ground] retrieve_evidence failed: %s", e)
```

- [ ] **Step 4: Make EXECUTE retry rebuild inputs**

In `execute_node`, when `state.get("error_feedback", {}).get("execute")` is set OR `state.get("execution_plan")` is None, re-derive:

```python
    if execution_plan is None and intent is not None and site_selection is not None:
        from app.agent.execute.plan_builder import build_execution_plan
        execution_plan = build_execution_plan(
            intent, site_selection, state.get("land_design_briefs") or [],
            run_id=_run_id(state), context_version=_context_version(state),
        )
```

(Note: with Task 2 in place, `execution_plan` should rarely be None on first pass; this is a defensive rebuild for the retry path.)

- [ ] **Step 5: Run tests**

Run: `pytest backend/tests/agent/test_post_l3_main_nodes.py -v`

- [ ] **Step 6: Run backend suite**

Run: `pytest backend/tests -x -q`

---

## Task 6: Stop premature "completed" - gate UI/SSE on deliver_gate=PASS

**Files:**
- Modify: `backend/app/agent/plan_state/state.py:385-393` (`state_to_ui_status`)
- Modify: `backend/app/services/runtime.py:817` (completed SSE)
- Test: `backend/tests/agent/test_state_to_ui_status.py` (new or extend), `backend/tests/services/test_runtime_sse.py` (extend)

**Interfaces:**
- Consumes: `state["deliver_gate"]`, `state["is_interrupted"]` / interrupt flag
- Produces: UI status `running`/`paused` until `deliver_gate.feedback_route == "PASS"`.

- [ ] **Step 1: Write failing test**

```python
# backend/tests/agent/test_state_to_ui_status.py
from app.agent.plan_state.state import state_to_ui_status

def test_interrupted_post_l3_not_reported_completed():
    state = {"phase": "completed", "deliver_gate": None, "metadata": {}}
    out = state_to_ui_status(state, is_interrupted=True)
    assert out["status"] != "completed", \
        "interrupted post-L3 must not report completed even if phase=completed"
    assert out["status"] == "paused"

def test_completed_only_when_deliver_gate_pass():
    state = {"phase": "completed", "metadata": {}}
    assert state_to_ui_status(state)["status"] != "completed"
    state["deliver_gate"] = {"feedback_route": "PASS"}
    assert state_to_ui_status(state)["status"] == "completed"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/agent/test_state_to_ui_status.py -v`
Expected: FAIL - current precedence checks `phase=="completed"` first.

- [ ] **Step 3: Fix precedence in state_to_ui_status**

In `state.py:385-393`, reorder so interrupt and deliver_gate are checked before phase. Replace the block:

```python
    if phase == "completed":
        status = "completed"
    elif is_interrupted:
        status = "paused"
    elif phase == "init":
        status = "pending"
    else:
        status = "running"
```

with:

```python
    deliver_gate = state.get("deliver_gate")
    deliver_pass = False
    if deliver_gate is not None:
        route = getattr(deliver_gate, "feedback_route", None)
        if route is None and isinstance(deliver_gate, dict):
            route = deliver_gate.get("feedback_route")
        deliver_pass = route == "PASS"

    if is_interrupted:
        status = "paused"
    elif phase == "completed" and deliver_pass:
        status = "completed"
    elif phase == "completed":
        status = "running"
    elif phase == "init":
        status = "pending"
    else:
        status = "running"
```

- [ ] **Step 4: Fix runtime SSE**

In `runtime.py:817` (the completed SSE emit), guard on `deliver_gate=PASS` the same way. Read the surrounding function first to confirm the variable name holding the state.

- [ ] **Step 5: Run tests**

Run: `pytest backend/tests/agent/test_state_to_ui_status.py backend/tests/services -v`

- [ ] **Step 6: Run backend suite**

Run: `pytest backend/tests -x -q`

---

## Task 7: Unify HITL onto the main graph; delete standalone post-L3 chain

**Files:**
- Modify: `backend/app/services/post_l3_resume.py` (rewrite `resume_post_l3_chain`)
- Modify: `backend/app/agent/bootstrap/gis_agent_entry.py` (stop invoking standalone)
- Delete: `backend/app/agent/bootstrap/post_l3_chain.py`
- Delete: `backend/app/agent/bootstrap/post_l3_nodes.py`
- Delete: `backend/app/agent/bootstrap/post_l3_state.py`
- Test: `backend/tests/services/test_post_l3_resume.py` (new), `backend/tests/agent/test_unified_graph_replay.py` (new - see Task 8)

**Interfaces:**
- Consumes: the compiled main graph (built by `create_unified_planning_graph`) + the same global checkpointer + `thread_id = session_id`.
- Produces: single resume entrypoint. API GET reads `human_review_items`; POST resolves via `Command(resume=decisions)` against the **main** graph.

- [ ] **Step 1: Write failing test for main-graph resume**

```python
# backend/tests/services/test_post_l3_resume.py
import pytest
from app.services import post_l3_resume

@pytest.mark.asyncio
async def test_resume_targets_main_graph(monkeypatch):
    resumed = {}
    class FakeCompiled:
        async def ainvoke(self, cmd, config):
            resumed["config"] = config
            resumed["cmd"] = cmd
            return {"human_review_decisions": cmd}
    monkeypatch.setattr(post_l3_resume, "_build_main_graph", lambda cp: FakeCompiled())
    await post_l3_resume.resume_post_l3_chain("s1", {"action": "approve"})
    assert resumed["config"]["configurable"]["thread_id"] == "s1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/services/test_post_l3_resume.py -v`
Expected: FAIL - current impl builds `build_post_l3_chain`.

- [ ] **Step 3: Rewrite `resume_post_l3_chain` to resume the main graph**

In `post_l3_resume.py`, replace the body that builds `build_post_l3_chain` with:

```python
from langgraph.types import Command
from app.agent.bootstrap.graph import create_unified_planning_graph
from app.modules.checkpoint import get_global_checkpointer

def _build_main_graph(checkpointer):
    return create_unified_planning_graph(checkpointer=checkpointer)

async def resume_post_l3_chain(session_id: str, decisions: Dict[str, Any]) -> Dict[str, Any]:
    checkpointer = get_global_checkpointer()
    graph = _build_main_graph(checkpointer)
    config = {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}
    result = await graph.ainvoke(Command(resume=decisions), config=config)
    return result
```

Remove the `post_l3_pending_review` write-back (line 163) - the main graph already persists `human_review_items` + `human_review_decisions`.

- [ ] **Step 4: Update the GET API to read `human_review_items`**

Find the GET endpoint (likely in `backend/app/api/human_review.py` or a router) and change its source key from `post_l3_pending_review` to `human_review_items`. Confirm by grepping for `post_l3_pending_review` first.

- [ ] **Step 5: Update `gis_agent_entry` to not invoke the standalone chain**

Read `gis_agent_entry.py` fully. If it calls `build_post_l3_chain().ainvoke(...)`, remove that block - the main graph already drives `parse`->...->`deliver` via its edges after `advance_phase` routes to `parse` (graph.py:146-176). Keep only the L3 program compile + `planning_program`/`l3_program_ref` write into state.

- [ ] **Step 6: Delete the standalone chain files**

```bash
git rm backend/app/agent/bootstrap/post_l3_chain.py
git rm backend/app/agent/bootstrap/post_l3_nodes.py
git rm backend/app/agent/bootstrap/post_l3_state.py
```

Then grep for any remaining imports of `post_l3_chain`, `post_l3_nodes`, `PostL3ChainState` and remove/replace them.

- [ ] **Step 7: Run targeted tests**

Run: `pytest backend/tests/services/test_post_l3_resume.py backend/tests/agent -v`

- [ ] **Step 8: Run full backend suite**

Run: `pytest backend/tests -x -q`
Expected: all green; if a test imported a deleted module, update it to use the main-graph equivalents.

---

## Task 8: Main-graph post-L3 replay integration test

**Files:**
- Create: `backend/tests/agent/test_unified_graph_replay.py`
- Reference: `backend/tests/conftest.py` (fixtures)

**Interfaces:**
- Consumes: `create_unified_planning_graph`, an in-memory checkpointer, a stub PlanningContext.
- Produces: a CI-gated test proving PARSE->...->DELIVER runs without dropping state, and HITL interrupt+resume round-trips on the SAME graph.

- [ ] **Step 1: Write the end-to-end replay test**

```python
# backend/tests/agent/test_unified_graph_replay.py
import pytest
from langgraph.checkpoint.memory import MemorySaver
from app.agent.bootstrap.graph import create_unified_planning_graph
from app.agent.plan_state.state import create_initial_state

@pytest.mark.asyncio
async def test_post_l3_chain_runs_end_to_end(monkeypatch):
    cp = MemorySaver()
    graph = create_unified_planning_graph(checkpointer=cp)
    state = create_initial_state("s1", "v1", "data")
    state["phase"] = "completed"
    state["planning_program"] = <stub PlanningProgram>
    result = await graph.ainvoke(state, config={"configurable": {"thread_id": "s1"}})
    assert result.get("planned_state") is not None
    assert result.get("execution_plan") is not None
    gate = result.get("deliver_gate")
    route = getattr(gate, "feedback_route", None) or (gate or {}).get("feedback_route")
    assert route in {"PASS", "HUMAN"}

@pytest.mark.asyncio
async def test_hitl_interrupt_and_resume_same_graph(monkeypatch):
    # Force a HUMAN route, assert interrupt, then Command(resume=...) on the SAME graph
    ...
```

(Fill the stubs by reading existing fixtures in `backend/tests/conftest.py` and the deterministic aggregate signatures. This is the largest test to write; budget extra time.)

- [ ] **Step 2: Run to verify it passes**

Run: `pytest backend/tests/agent/test_unified_graph_replay.py -v`
Expected: PASS. If it fails, the failure pinpoints remaining state-flow gaps - iterate on Tasks 1-5 until green.

- [ ] **Step 3: Add to CI**

If a CI workflow exists (`.github/workflows/*.yml`), ensure this test file is included in the backend test step. If no CI, note it as a required local gate in `AGENTS.md`.

- [ ] **Step 4: Run full backend suite**

Run: `pytest backend/tests -x -q`

---

## Notes / Deferred (out of P0 critical path, tracked for follow-up)

- **Deliver layer naming (P0-8 partial):** `export_package.py:77` vs `map_layers.py:88` `ecological_protection_geojson`. The deliver check now routes via `GDB_LAYER_REGISTRY`, so a follow-up task should audit `GDB_LAYER_REGISTRY` to ensure `ecological_redline` and `planned_landuse` resolve to sources that `export_gdb_package` actually writes. Add a unit test asserting `check_statutory_layers_complete` passes against a real export fixture.
- **ID-based coverage joins (P0-4 part 2):** `reconcile/aggregate.py:63-70` positional pairing. This requires schema changes to `SpatialReferenceSpec` (add `intervention_id`) and `CandidateSite` (add `spec_ref`). Scope this as a separate plan after the critical path is stable.
- **Bootstrap circular import + lazy load (P1):** `plan_state -> bootstrap -> graph -> plan_state`. Address last, after the chain runs.
- **Frontend HITL wiring:** `getHumanReview`/`resolveHumanReview` API client functions exist but no component calls them. After Task 7 makes the API return real items, add a React component in a follow-up.
- **Frontend Jest failure:** `createSystemMessage` (`frontend/src/features/planning/utils/message-helpers.ts:41`) comment claims it sets `_pendingStorage` but doesn't - may persist transient system messages. Fix in a frontend follow-up.

## Self-Review

1. **Spec coverage:** Each of the 8 P0 defects maps to a task: P0-1->T1, P0-2->T2, P0-3->T4, P0-4->T3 (+deferred ID-join), P0-5->T5, P0-6->T7, P0-7->T6, P0-8->deferred note. ✓
2. **Placeholder scan:** Code blocks are concrete; where a field/signature must be confirmed against the schema (e.g., `ValidationCheck`, `ReconciliationReport`), the step explicitly says to read the contract file first. No "TODO"/"TBD". ✓
3. **Type consistency:** `execution_plan`, `planned_state`, `parcel_changeset_ref`, `planned_state_ref`, `grounding_result_ref`, `site_selection_ref` are used consistently across T1 (declaration), T2 (write), T3/T4 (read). `_load_planning_program` referenced in T3 matches the helper defined at post_l3_main_nodes.py:201. ✓

---

## Execution Status (2026-08-06)

All 8 tasks completed in this session. Backend regression: 187 targeted tests green
(tests/agent, tests/services, tests/unit/bootstrap, tests/unit/reconcile, tests/unit/validate, tests/unit/parse),
full app tree imports (445 modules), compileall clean.

- [x] T1 Add missing post-L3 state channels to AgentState
- [x] T2 Main-graph SELECT builds ExecutionPlan
- [x] T3 RECONCILE loads PlanningProgram from ref (fail-closed)
- [x] T4 VALIDATE fail-closed on missing planned_state + typed intent
- [x] T5 Retries consume feedback (GROUND evidence + EXECUTE rebuild)
- [x] T6 Gate UI/SSE completion on deliver_gate=PASS
- [x] T7 Unify HITL onto main graph; delete standalone post-L3 chain
- [x] T8 Main-graph post-L3 replay integration test

### Extra bug found & fixed during T8
`_collect_human_items` (post_l3_main_nodes.py:599) read `getattr(gate, "pending_requests", None)`
which returns None for the dict-serialized gates the main graph stores (nodes use `_dump(gate)`),
so HUMAN gates never surfaced items -> `human_review` never interrupted (empty review list).
Fixed to fall back to `gate.get("pending_requests")` for dicts. Covered by
`test_collect_human_items_from_dict_gate` and the `test_hitl_interrupt_and_resume_same_graph`
integration test.
