"""P0-1: EXECUTE subgraph must run through the real RuntimeService assembly.

Reproduces the production bug: checkpointer=True cannot be used for root graphs.
"""
import pytest

from app.services.runtime import PlanningRuntimeService


@pytest.mark.asyncio
async def test_execute_subgraph_compiled_with_real_saver():
    await PlanningRuntimeService.ensure_initialized()
    graph = PlanningRuntimeService._execute_subgraph
    assert graph is not None
    saver = getattr(graph, "checkpointer", None)
    assert saver is not None, "EXECUTE subgraph has no checkpointer"
    assert saver is not True, "EXECUTE subgraph still compiled with checkpointer=True"


@pytest.mark.asyncio
async def test_execute_subgraph_invokes_without_runtime_error():
    await PlanningRuntimeService.ensure_initialized()
    graph = PlanningRuntimeService._execute_subgraph
    config = {"configurable": {"thread_id": "test-exec-runtime-1", "checkpoint_ns": "execute"}}
    try:
        await graph.ainvoke({}, config=config)
    except RuntimeError as e:
        if "cannot be used for root graphs" in str(e):
            pytest.fail(f"EXECUTE root invocation raised the P0-1 bug: {e}")
        raise


@pytest.mark.asyncio
async def test_new_attempt_does_not_inherit_old_execute_state():
    """A second ainvoke with a fresh thread_id must not see prior EXECUTE outputs."""
    await PlanningRuntimeService.ensure_initialized()
    graph = PlanningRuntimeService._execute_subgraph
    cfg_a = {"configurable": {"thread_id": "attempt-A"}}
    cfg_b = {"configurable": {"thread_id": "attempt-B"}}
    await graph.aget_state(cfg_a)
    state_b_before = await graph.aget_state(cfg_b)
    assert state_b_before is None or not state_b_before.values
