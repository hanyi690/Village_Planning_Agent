"""A6: multi-schema isolation on the unified planning graph.

The factory wires ``input_schema=WorkflowState`` (full checkpoint state) and
``output_schema=WorkflowOutput`` (application control projection).  Checkpoint
values keep the full internal state; only direct ``invoke`` callers see the
projected output.
"""

from __future__ import annotations

from app.workflow.root_graph import create_unified_planning_graph
from app.workflow.state import WorkflowOutput, WorkflowState


def _keys(properties: dict) -> set[str]:
    return set(properties or {})


def test_planning_graph_input_schema_is_full_checkpoint_state() -> None:
    graph = create_unified_planning_graph()
    input_keys = _keys(graph.get_input_jsonschema().get("properties", {}))
    assert input_keys == set(WorkflowState.__annotations__)


def test_planning_graph_output_schema_is_control_projection() -> None:
    graph = create_unified_planning_graph()
    output_keys = _keys(graph.get_output_jsonschema().get("properties", {}))
    assert output_keys == set(WorkflowOutput.__annotations__)
    # The output projection is strictly smaller than the internal state: it
    # must never leak worker results, messages or the runtime channel.
    assert output_keys < set(WorkflowState.__annotations__)
    for leaked in ("messages", "runtime", "completed_dimensions", "fatal_error"):
        assert leaked not in output_keys


def test_workflow_output_matches_projection_shape() -> None:
    assert set(WorkflowOutput.__annotations__) == {
        "run_id",
        "session_id",
        "branch_id",
        "phase",
        "active_stage",
        "status",
        "delivery_status",
        "context_ref",
        "context_fingerprint",
        "artifact_refs",
        "gate_ref",
        "retry",
        "interrupt_ref",
        "terminal_ref",
        "validation_feedback",
    }
