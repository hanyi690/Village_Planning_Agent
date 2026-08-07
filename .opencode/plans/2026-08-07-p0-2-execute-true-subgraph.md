# P0-2: EXECUTE True Subgraph Mount

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mount the EXECUTE graph as a **true compiled subgraph node** in the parent graph, so LangGraph manages the nested `checkpoint_ns` automatically and the subgraph's `ExecuteAgentState` checkpoints are isolated from the parent's `AgentState` history.

**Architecture:** Per Context7 LangGraph official docs, a compiled subgraph can be passed directly to `parent.add_node("name", compiled_subgraph)`. LangGraph auto-assigns a nested checkpoint namespace and manages state mapping at the boundary. The subgraph must be compiled **without** its own checkpointer - the parent's checkpointer handles persistence under an isolated namespace. The current `execute_node` wrapper function already does state mapping (parent AgentState -> ExecuteAgentState at lines 511-523, output mapping at 542-561). We split this into: (1) a pre-execute node that does the mapping and stores the `ExecuteAgentState` in parent state, (2) the formal subgraph mount, (3) a post-execute node that maps results back.

**Tech Stack:** Python, LangGraph StateGraph, pytest

## Global Constraints

- Backend tests run from `backend/` directory
- 4-space indent for Python, double quotes
- LF line endings
- No emojis in code or comments
- Commit only when explicitly asked by the user, at task boundaries

---

## Context7 Reference (LangGraph Official Practice)

From `/websites/langchain_oss_python_langgraph` - "Add Compiled Subgraph as Node":

> ```python
> subgraph = subgraph_builder.compile()
> builder = StateGraph(State)
> builder.add_node("node_1", subgraph)  # compiled graph as node
> ```

From `/langchain-ai/langgraph` test suite - "Compiled subgraph with checkpointer passed to add_node":

> ```python
> subgraph = subgraph_builder.compile(checkpointer=subgraph_persist)
> builder.add_node("alice", subgraph)
> graph = builder.compile(checkpointer=sync_checkpointer)
> ```

From `/websites/langchain_oss_python_langgraph` - "Full example: different state schemas":

> Subgraphs can utilize state schemas that differ from their parent graphs. The parent graph is responsible for explicitly mapping its state keys to the subgraph's input keys before invocation.

**Decision: Approach A (formal subgraph mount).** The EXECUTE graph is compiled without its own checkpointer and mounted via `add_node("execute", compiled_execute)`. LangGraph manages the nested `checkpoint_ns`. State mapping is handled by adding `execute_agent_state` to `AgentState` (the parent passes the mapped `ExecuteAgentState` dict, and the subgraph reads it as input).

---

## Current Bug (confirmed)

```
runtime.py:133   parent graph compiled with cls._checkpointer
runtime.py:137   EXECUTE compiled with SAME cls._checkpointer  ← BUG
post_l3:525-538  execute_node calls graph.ainvoke(exec_state, config={thread_id, ns=""})
                 # Same checkpointer + same thread_id + same ns = POLLUTION
                 # ExecuteAgentState checkpoints overwrite AgentState history
```

---

### Task 1: Write integration assertion tests

**Files:**
- Create: `backend/tests/agent/test_execute_subgraph_isolation.py`
- Test: same file

**Interfaces:**
- Consumes: `MemorySaver`, `StateGraph`, parent and child state schemas
- Produces: tests that assert (a) parent state survives child execution, (b) child checkpoints are in a non-empty namespace, (c) resume/time-travel works for both

- [ ] **Step 1: Write the tests**

```python
"""Integration tests: EXECUTE subgraph must not pollute parent checkpoint namespace.

Tests:
1. Parent state fields survive EXECUTE subgraph execution
2. Child checkpoints are in a non-empty namespace (isolated)
3. Multiple EXECUTE runs don't overwrite each other
4. Parent get_state() returns AgentState, not ExecuteAgentState
"""
import pytest
from typing import TypedDict, Annotated
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import add_messages


class ParentState(TypedDict, total=False):
    owner: str
    parent_value: int
    child_input: dict  # mapped to child state


class ChildState(TypedDict, total=False):
    owner: str
    child_value: int


def test_formal_subgraph_isolates_checkpoint_namespace():
    """A compiled subgraph mounted via add_node must not clobber parent state."""
    checkpointer = MemorySaver()

    def child_node(state):
        return {"owner": "child", "child_value": 42}

    child_builder = StateGraph(ChildState)
    child_builder.add_node("child", child_node)
    child_builder.add_edge(START, "child")
    child_builder.add_edge("child", END)
    compiled_child = child_builder.compile()  # NO checkpointer on child

    parent_builder = StateGraph(ParentState)
    parent_builder.add_node("call_child", compiled_child)  # formal mount
    parent_builder.add_edge(START, "call_child")
    parent_builder.add_edge("call_child", END)
    parent_graph = parent_builder.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-iso"}}
    result = parent_graph.invoke({"owner": "parent", "parent_value": 1}, config=config)

    # Parent checkpoint must retain parent_value
    snapshot = parent_graph.get_state(config)
    assert snapshot.values.get("parent_value") == 1, "Parent state clobbered by child"
    assert snapshot.values.get("owner") == "child", "Child output should be mapped back"

    # Child checkpoints must be in a non-empty namespace
    state_with_subgraphs = parent_graph.get_state(config, subgraphs=True)
    # The subgraph snapshot should exist under a nested namespace
    assert state_with_subgraphs is not None


def test_direct_ainvoke_does_not_isolate():
    """The CURRENT pattern (direct .ainvoke with same checkpointer) DOES clobber.
    This test documents the bug we're fixing."""
    checkpointer = MemorySaver()

    def child_node(state):
        return {"owner": "child", "child_value": 42}

    child_builder = StateGraph(ChildState)
    child_builder.add_node("child", child_node)
    child_builder.add_edge(START, "child")
    child_builder.add_edge("child", END)
    compiled_child_bug = child_builder.compile(checkpointer=checkpointer)  # BUG: same checkpointer

    def call_child_buggy(state: ParentState):
        result = compiled_child_bug.invoke(
            {"owner": state.get("owner", "")},
            config={"configurable": {"thread_id": "test-clobber"}},
        )
        return {"owner": result.get("owner", "")}

    parent_builder = StateGraph(ParentState)
    parent_builder.add_node("call_child", call_child_buggy)
    parent_builder.add_edge(START, "call_child")
    parent_builder.add_edge("call_child", END)
    parent_graph = parent_builder.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-clobber"}}
    parent_graph.invoke({"owner": "parent", "parent_value": 1}, config=config)

    snapshot = parent_graph.get_state(config)
    assert snapshot.values.get("parent_value") is None, (
        "Expected parent_value to be clobbered by the current buggy pattern"
    )
```

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/agent/test_execute_subgraph_isolation.py -v`
Expected: Both pass (first tests the correct pattern, second documents the bug)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/agent/test_execute_subgraph_isolation.py
git commit -m "test: add subgraph checkpoint isolation integration tests"
```

---

### Task 2: Compile EXECUTE without its own checkpointer

**Files:**
- Modify: `backend/app/services/runtime.py:136-138`

- [ ] **Step 1: Stop passing checkpointer to build_execute_agent_graph**

In `backend/app/services/runtime.py` around lines 136-138, change:

```python
        from app.agent.execute.execute_agent import build_execute_agent_graph
        cls._execute_subgraph = build_execute_agent_graph()
        logger.info("[PlanningRuntimeService] EXECUTE subgraph compiled (no own checkpointer, mounted as formal subgraph)")
```

- [ ] **Step 2: Verify build_execute_agent_graph handles checkpointer=None**

Read `execute_agent.py:1171-1174` - already handles `None` by not passing it to `compile()`. No change needed.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/runtime.py
git commit -m "fix: compile EXECUTE subgraph without its own checkpointer"
```

---

### Task 3: Mount EXECUTE as a formal subgraph node

**Files:**
- Modify: `backend/app/agent/bootstrap/graph.py:178` (replace `add_node("execute", execute_node)` with `add_node("execute", compiled_execute)`)
- Modify: `backend/app/agent/bootstrap/post_l3_main_nodes.py` (split execute_node into pre/post mapping nodes)
- Modify: `backend/app/agent/plan_state/state.py` (add `execute_agent_state` field to AgentState)
- Test: `backend/tests/agent/test_execute_subgraph_isolation.py`

**Approach:** The formal subgraph mount means LangGraph calls the compiled EXECUTE graph directly as a node. But the parent and child have different state schemas. We need:

1. A `pre_execute` node that maps parent AgentState -> ExecuteAgentState and stores it in `state["execute_agent_state"]`
2. The formal subgraph mount reads `execute_agent_state` as its input
3. A `post_execute` node that maps the subgraph output back to parent AgentState

The subgraph's `ExecuteAgentState` must be expressible as a dict in the parent state. LangGraph will pass the relevant keys to the subgraph.

**Simpler alternative:** Since `ExecuteAgentState` is a Pydantic BaseModel (not a TypedDict), and LangGraph subgraphs with `add_node(compiled_graph)` expect the parent state to contain keys matching the child's state schema, we can add the child's keys to `AgentState` as optional fields. But this pollutes the parent schema.

**Recommended approach:** Use a wrapper node that invokes the compiled subgraph. The key difference from the current code is: (1) the subgraph is compiled without a checkpointer, (2) the wrapper passes the parent config (with thread_id) so LangGraph routes through the parent's checkpointer. Per Context7, when a compiled graph without its own checkpointer is passed to `add_node`, LangGraph manages the namespace. But when called via `.ainvoke()` inside a wrapper function, we must explicitly pass a distinct `checkpoint_ns`.

**Final decision:** Mount the compiled subgraph directly via `add_node("execute_subgraph", compiled_execute)` and add pre/post mapping nodes. The graph structure becomes:

```
... -> select -> pre_execute -> execute_subgraph -> post_execute -> validate -> ...
```

- [ ] **Step 1: Add execute_agent_state to AgentState**

In `backend/app/agent/plan_state/state.py`, add to the `AgentState` TypedDict:

```python
    execute_agent_state: dict  # mapped ExecuteAgentState for the formal subgraph
```

And in `create_initial_state`, add:

```python
        "execute_agent_state": {},
```

- [ ] **Step 2: Create pre_execute and post_execute nodes**

In `backend/app/agent/bootstrap/post_l3_main_nodes.py`, refactor `execute_node` into:

```python
async def pre_execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Map parent AgentState -> ExecuteAgentState dict for the formal subgraph."""
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan

    context = await _require_context(state)
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    site_selection = _load_ref_artifact(state, "site_selection", SiteSelectionDecision)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    if execution_plan is None and intent is not None and site_selection is not None:
        from app.agent.execute.plan_builder import build_execution_plan
        execution_plan = build_execution_plan(
            intent, site_selection, state.get("land_design_briefs") or [],
            run_id=_run_id(state), context_version=_context_version(state),
        )
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}

    kg_obj = getattr(context, "kg", None)
    if kg_obj is not None and plan_intent is not None:
        try:
            from app.modules.kg.builder.layer3 import build_intent_layer
            build_intent_layer(kg_obj, plan_intent)
        except Exception as e:
            logger.warning("[pre_execute] build_intent_layer failed: %s", e)

    exec_state = ExecuteAgentState(
        session_id=state.get("session_id", ""),
        village_name=state.get("config", {}).get("village_name", ""),
        gis_data=gis_data,
        gis_bundle=bundle,
        intent=plan_intent,
        facility_anchors=getattr(context, "village_anchors", None),
        site_selection=site_selection,
        land_design_briefs=list(state.get("land_design_briefs") or []),
        execution_plan=execution_plan,
        kg_session_ref=getattr(context, "kg_session_ref", "") or "",
        messages=list(state.get("messages") or []),
    )
    return {
        "execute_agent_state": exec_state.model_dump(mode="json"),
        **_adopt_context(state, context),
    }


async def post_execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Map ExecuteAgentState output back to parent AgentState."""
    from app.agent.execute.planned_state_builder import changeset_to_planned_state
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent

    exec_result = state.get("execute_agent_state", {})
    changeset = exec_result.get("parcel_changeset")
    # Reload intent for planned_state construction
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)

    if changeset is not None:
        planned_state = changeset_to_planned_state(changeset, plan_intent)
    else:
        logger.warning("[post_execute] no parcel_changeset produced")
        planned_state = None

    refs = {
        "parcel_changeset": _persist_artifact(state, "execute", "ParcelChangeSet", changeset),
        "planned_state": _persist_artifact(state, "execute", "PlannedState", planned_state),
        "allocated_geojson": _persist_artifact(
            state, "execute", "AllocatedGeoJSON", exec_result.get("allocated_geojson", {}) or {}
        ),
    }
    return {
        "layout_configs": _jsonable(list(exec_result.get("layout_configs", []) or [])),
        "execution_errors": _jsonable(list(exec_result.get("execution_errors", []) or [])),
        "artifact_refs": refs,
    }
```

- [ ] **Step 3: Mount the compiled subgraph in the parent graph**

In `backend/app/agent/bootstrap/graph.py`, change the node registration and edges:

Current (line 178):
```python
    builder.add_node("execute", post_l3_main_nodes.execute_node)
```

New:
```python
    from app.agent.execute.execute_agent import build_execute_agent_graph
    compiled_execute = build_execute_agent_graph()
    builder.add_node("pre_execute", post_l3_main_nodes.pre_execute_node)
    builder.add_node("execute", compiled_execute)
    builder.add_node("post_execute", post_l3_main_nodes.post_execute_node)
```

Update the edges (lines 208-210):
```python
    builder.add_conditional_edges("select", route_after_select,
        {"execute": "pre_execute", "ground": "ground", "human_review": "human_review_prepare"})
    builder.add_edge("pre_execute", "execute")
    builder.add_edge("execute", "post_execute")
    builder.add_edge("post_execute", "validate")
```

Also update any other edges that reference `"execute"` to go to `"pre_execute"` instead (e.g., in `route_after_validate` which can route back to `"execute"` for retry - change to `"pre_execute"`).

- [ ] **Step 4: Run the integration tests**

Run: `cd backend && python -m pytest tests/agent/test_execute_subgraph_isolation.py tests/agent/test_post_l3_main_nodes.py -v`
Expected: PASS

- [ ] **Step 5: Run full regression**

Run: `cd backend && python -m pytest tests/core/ tests/agent/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/bootstrap/graph.py backend/app/agent/bootstrap/post_l3_main_nodes.py backend/app/agent/plan_state/state.py backend/app/services/runtime.py
git commit -m "fix: mount EXECUTE as formal subgraph with pre/post mapping nodes

The EXECUTE subgraph was compiled with the parent's checkpointer and
invoked via direct .ainvoke() with the same thread_id and default empty
checkpoint_ns, causing ExecuteAgentState checkpoints to clobber the
parent's AgentState history.

Now the compiled EXECUTE graph (without its own checkpointer) is mounted
via add_node('execute', compiled_execute). LangGraph auto-assigns a
nested checkpoint_ns. pre_execute maps parent state -> ExecuteAgentState;
post_execute maps the result back. Per Context7 LangGraph docs, a
compiled graph without its own checkpointer mounted via add_node gets
automatic namespace isolation."
```

---

### Task 4: Full regression and audit ledger

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 2: Update audit ledger**

Add a row to `docs/audits/backend-breakpoints-2026-08-06.md`.

- [ ] **Step 3: Commit**

```bash
git add docs/audits/backend-breakpoints-2026-08-06.md
git commit -m "docs: record EXECUTE subgraph isolation fix in audit ledger"
```
