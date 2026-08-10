# Target-bound SELECT and plan-driven EXECUTE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SELECT produce authoritative target assignments and make EXECUTE run only the bound worker tasks, including typed action outcomes.

**Architecture:** SELECT records one `TargetAssignment` per stable target ID, with selected spatial data and a target snapshot. The plan builder turns those records into self-contained `WorkerTask`s; EXECUTE rebuilds its worker inputs from those task bindings rather than the stale PARSE intent.

**Tech Stack:** Python, Pydantic v2, LangGraph, pytest.

## Global Constraints

- New root artifacts use `schema_version="2.0"`.
- Stable target IDs are authoritative; names and list positions are never join keys.
- EXECUTE routes exclusively from `ExecutionPlan.worker_tasks`.
- Explicit ledger deferrals are omitted from dispatch; unresolved references remain auditable.
- Non-spatial targets produce typed action results without `ParcelChange` records.

---

### Task 1: Bind SELECT assignments and build dispatchable tasks

**Files:**
- Modify: `backend/app/modules/schema/contracts/selection_contracts.py`
- Modify: `backend/app/modules/schema/contracts/execution_plan_contracts.py`
- Modify: `backend/app/agent/select/aggregate.py`
- Modify: `backend/app/agent/execute/plan_builder.py`
- Test: `backend/tests/e2e/test_target_bound_execute_e2e.py`

- [x] **Step 1: Write a failing regression test**

```python
assert task.target_id == "facility-2"
assert task.assignment.anchor_point == (116.0, 24.0)
```

- [x] **Step 2: Run the focused test and capture RED**

Run: `pytest tests/e2e/test_target_bound_execute_e2e.py -q`

- [x] **Step 3: Add target assignments, self-contained worker bindings, action/axis worker types, and ledger filtering**

```python
WorkerTask(target_id=target_id, assignment=assignment, expected_output_kind=assignment.expected_output_kind)
```

- [x] **Step 4: Run the focused test and capture GREEN**

Run: `pytest tests/e2e/test_target_bound_execute_e2e.py -q`

### Task 2: Execute only task bindings and persist per-task outcomes

**Files:**
- Modify: `backend/app/agent/execute/nodes/worker_common.py`
- Modify: `backend/app/agent/execute/nodes/route_prepare.py`
- Modify: `backend/app/agent/execute/nodes/project_worker.py`
- Modify: `backend/app/agent/execute/nodes/facility_worker.py`
- Modify: `backend/app/agent/execute/nodes/axis_worker.py`
- Modify: `backend/app/agent/execute/nodes/road_worker.py`
- Modify: `backend/app/agent/execute/nodes/zone_worker.py`
- Modify: `backend/app/agent/execute/execute_agent.py`
- Modify: `backend/app/agent/bootstrap/post_l3_main_nodes.py`
- Test: `backend/tests/e2e/test_target_bound_execute_e2e.py`

- [x] **Step 1: Extend the failing test so a plan-bound facility anchor succeeds while the supplied intent has no anchor**

```python
result = _facility_worker(ExecuteAgentState(intent=stale_intent, execution_plan=plan))
assert result.layers[0]["data"]["features"][0]["geometry"]["type"] == "Point"
```

- [x] **Step 2: Materialize worker inputs exclusively from plan tasks, add action execution, and record task statuses/diagnostics**

```python
bound_intent = _execution_intent_from_plan(state)
```

- [x] **Step 3: Run focused regressions, then the backend suite once**

Run: `pytest tests/e2e/test_target_bound_execute_e2e.py tests/e2e/test_target_contracts_e2e.py -q`

Run: `pytest -q`

- [x] **Step 4: Commit the implementation and write the task report**

```bash
git add backend docs/superpowers/plans
git commit -m "feat: bind execute workers to target assignments"
```
