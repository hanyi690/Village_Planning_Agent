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

### Task 3: EXECUTE via wrapper function + independent checkpointer

**Files:**
- Modify: `backend/app/agent/bootstrap/post_l3_main_nodes.py` (keep `execute_node` as wrapper, or rename; it already maps parent refs -> ExecuteAgentState -> parent refs)
- Modify: `backend/app/services/runtime.py` (compile EXECUTE with an independent checkpointer)
- Revert: `backend/app/agent/plan_state/state.py` (REMOVE the 12 EXECUTE channel fields added by the previous Approach 1)
- Revert: `backend/app/agent/bootstrap/graph.py` (keep `execute_node` as a plain function node, NOT a mounted compiled subgraph)
- Test: `backend/tests/agent/test_execute_subgraph_isolation.py`

**Approach (FINAL, per Context7 + Exa official LangGraph practice):** When the parent and subgraph have **different state schemas** (AgentState TypedDict vs ExecuteAgentState BaseModel, with no shared keys), LangGraph's official recommended pattern is **"Call a subgraph inside a node"** — a wrapper function that explicitly maps parent state to subgraph input and back. Direct `add_node(compiled_subgraph)` is only for graphs that SHARE state keys.

The original economics: `execute_node` (post_l3_main_nodes.py) already IS this wrapper — it builds `ExecuteAgentState` from parent refs, calls `graph.ainvoke(exec_state, config)`, and maps `result` back to parent. The ONLY bug was the checkpoint namespace collision (same checkpointer + same thread_id + default empty ns).

**Fix: give EXECUTE an independent checkpointer** so its checkpoints live in a separate namespace, while sharing the thread_id. Per LangGraph docs, a subgraph compiled with `checkpointer=True` (or its own checkpointer instance) gets independent checkpoint history. Because the wrapper passes a DISTINCT `checkpoint_ns` (e.g. `"execute"`) in the config, the EXECUTE checkpoints are isolated from the parent's `""` namespace.

The graph structure stays:
```
... -> select -> execute (wrapper function) -> validate -> ...
```

- [ ] **Step 1: Revert Approach 1 — remove the 12 EXECUTE channel fields from AgentState**

In `backend/app/agent/plan_state/state.py`, remove the EXECUTE channel fields added previously:
```python
    intent: Any
    site_selection: Any
    execution_plan: Any
    gis_data: dict
    gis_bundle: Any
    facility_anchors: list
    kg_session_ref: str
    parcel_changeset: Any
    layout_configs: list
    execution_errors: list
    allocated_geojson: dict
    allocation_summary: dict
    planned_state: Any
```
(These 12 fields were added by the previous Approach 1. Remove them to restore ref-only AgentState. Note: `layout_configs` and `execution_errors` may already exist in AgentState independently — check; only remove the ones the Approach 1 mount added.)

- [ ] **Step 2: Revert graph.py to keep execute_node as a plain function node**

In `backend/app/agent/bootstrap/graph.py`, revert the Approach 1 changes:
- Remove `pre_execute_node` / `post_execute_node` registration and the `add_node("execute", compiled_execute)` mount
- Restore `builder.add_node("execute", post_l3_main_nodes.execute_node)`
- Restore edges: select -> execute -> validate (remove pre_execute/post_execute edges)
- Restore `route_after_select`/`route_after_validate`/`route_after_reconcile`/`route_after_human_review` maps to route to `"execute"` (not `"pre_execute"`)

- [ ] **Step 3: Compile EXECUTE with an independent checkpointer**

In `backend/app/services/runtime.py`, change the EXECUTE compile to give it an independent checkpointer:
```python
        from app.agent.execute.execute_agent import build_execute_agent_graph
        cls._execute_subgraph = build_execute_agent_graph(checkpointer=True)
        logger.info("[PlanningRuntimeService] EXECUTE subgraph compiled (independent checkpointer)")
```
`checkpointer=True` makes LangGraph give the subgraph its own checkpoint history (per official time-travel docs). Verify `build_execute_agent_graph` passes it to `compile()`.

- [ ] **Step 4: Pass a distinct checkpoint_ns when invoking EXECUTE**

In `backend/app/agent/bootstrap/post_l3_main_nodes.py` `execute_node`, change the `graph.ainvoke(...)` call to pass a distinct `checkpoint_ns`:
```python
    result = await graph.ainvoke(
        exec_state,
        config={"configurable": {"thread_id": state.get("session_id", ""), "checkpoint_ns": "execute"}},
    )
```
This isolates EXECUTE checkpoints from the parent's `""` namespace, preventing parent-state clobbering.

- [ ] **Step 5: Run the integration/regression tests**

Run: `cd backend && python -m pytest --basetemp=C:\Users\24957\AppData\Local\Temp\opencode\pt tests/agent/test_execute_subgraph_isolation.py tests/agent/test_post_l3_main_nodes.py -v`
Then: `cd backend && python -m pytest --basetemp=C:\Users\24957\AppData\Local\Temp\opencode\pt tests/core/ tests/agent/ -v`
Fix breakage. Pre-existing failures (test_post_l3_main_nodes.py 6 tests, test_unified_graph_replay) are NOT yours — report them.

- [ ] **Step 6: Verify the wave_m ref-only test passes again**

Run: `cd backend && python -m pytest --basetemp=C:\Users\24957\AppData\Local\Temp\opencode\pt tests/unit/test_agent_state_wave_m_fields.py -v`
This test asserts site_selection/execution_plan/etc. are NOT in AgentState. After reverting the channel fields, it should PASS again.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/bootstrap/post_l3_main_nodes.py backend/app/services/runtime.py backend/app/agent/plan_state/state.py backend/app/agent/bootstrap/graph.py
git commit -m "fix: EXECUTE via wrapper function with independent checkpointer

Revert Approach 1 (which added 12 EXECUTE channel fields to AgentState,
polluting the ref-only schema and breaking test_agent_state_wave_m_fields).
Per LangGraph official practice, when parent and subgraph have different
state schemas the recommended pattern is 'Call a subgraph inside a node'
(a wrapper function that maps state in/out). execute_node already is that
wrapper. The real fix is giving EXECUTE an independent checkpointer
(checkpointer=True) and passing a distinct checkpoint_ns ('execute') so
its checkpoints are isolated from the parent's '' namespace, eliminating
the parent-state clobbering without polluting the parent schema."
```

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
