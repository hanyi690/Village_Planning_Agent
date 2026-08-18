"""Unit tests for the A5 segment routing helpers (app/workflow/segments.py)."""

from __future__ import annotations

from langgraph.graph import END
from langgraph.types import Command, Send

from app.workflow.segments import (
    _COGNITIVE_INTERNAL,
    _SPATIAL_INTERNAL,
    _make_router,
    _map_route_result,
    _remap_command,
)


def _cmd(goto, graph=None, update=None):
    return Command(graph=graph, goto=goto, update=update)


def test_map_route_internal_target_stays_in_segment() -> None:
    command = _map_route_result(
        "ground",
        source_segment="spatial_chain",
        internal_nodes=_SPATIAL_INTERNAL,
        cross_map={},
    )
    assert command.graph is None
    assert command.goto == "ground"


def test_map_route_cross_target_emits_parent_jump_with_entry_hint() -> None:
    command = _map_route_result(
        "validate",
        source_segment="hitl",
        internal_nodes=frozenset(),
        cross_map={"validate": ("spatial_chain", "validate")},
    )
    assert command.graph == Command.PARENT
    assert command.goto == "spatial_chain"
    assert command.update == {"subgraph_entry": "validate"}


def test_map_route_cross_target_without_hint_clears_entry() -> None:
    command = _map_route_result(
        "target_projection",
        source_segment="cognitive",
        internal_nodes=_COGNITIVE_INTERNAL,
        cross_map={"target_projection": ("spatial_chain", None)},
    )
    assert command.graph == Command.PARENT
    assert command.goto == "spatial_chain"
    assert command.update == {"subgraph_entry": None}


def test_map_route_end_ends_parent() -> None:
    command = _map_route_result(
        END,
        source_segment="cognitive",
        internal_nodes=_COGNITIVE_INTERNAL,
        cross_map={},
    )
    assert command.graph == Command.PARENT
    assert command.goto == END


def test_map_route_diagnostic_sentinel() -> None:
    command = _map_route_result(
        "end_diagnostic",
        source_segment="spatial_chain",
        internal_nodes=_SPATIAL_INTERNAL,
        cross_map={},
    )
    assert command.graph == Command.PARENT
    assert command.goto == "end_diagnostic"


def test_map_route_send_list_from_intent_parks_payloads() -> None:
    sends = [Send("l1_worker", {"dimension_key": "a"}), Send("l2_worker", {"dimension_key": "b"})]
    command = _map_route_result(
        sends,
        source_segment="intent_loop",
        internal_nodes=frozenset(),
        cross_map={},
    )
    assert command.graph == Command.PARENT
    assert command.goto == "cognitive"
    assert command.update == {"pending_dispatches": [{"dimension_key": "a"}, {"dimension_key": "b"}]}


def test_map_route_send_list_from_cognitive_stays_internal() -> None:
    sends = [Send("l1_worker", {"dimension_key": "a"})]
    command = _map_route_result(
        sends,
        source_segment="cognitive",
        internal_nodes=_COGNITIVE_INTERNAL,
        cross_map={},
    )
    assert command.graph is None
    assert command.goto == sends


def test_map_route_unknown_target_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        _map_route_result(
            "mystery_node",
            source_segment="cognitive",
            internal_nodes=_COGNITIVE_INTERNAL,
            cross_map={},
        )


def test_make_router_rejects_under_dispatch_audit(monkeypatch) -> None:
    from app.workflow.dispatch import DispatchDiagnostic, DispatchDiagnosticCode
    from app.workflow.routing import RouteAuthorization
    from app.workflow.terminal import TerminalStatus

    monkeypatch.setattr(
        "app.workflow.routing.authorize_route_result",
        lambda _state, _source, _result: RouteAuthorization(
            accepted=False,
            diagnostic=DispatchDiagnostic(
                code=DispatchDiagnosticCode.UNAUTHORIZED_STAGE,
                message="probe",
            ),
        ),
    )
    router = _make_router(
        "ground",
        lambda _state: "select",
        source_segment="spatial_chain",
        internal_nodes=_SPATIAL_INTERNAL,
        cross_map={},
    )
    command = router({})
    assert command.graph == Command.PARENT
    assert command.goto == "end_diagnostic"
    assert command.update["delivery_status"] == TerminalStatus.DIAGNOSTIC_ONLY.value


def test_make_router_preserves_child_artifact_refs_on_parent_terminal(monkeypatch) -> None:
    from app.workflow.routing import RouteAuthorization

    monkeypatch.setattr(
        "app.workflow.routing.authorize_route_result",
        lambda _state, _source, _result: RouteAuthorization(accepted=True),
    )
    refs = {"delivery_manifest": {"descriptor_digest": "manifest-ref"}}
    router = _make_router(
        "deliver",
        lambda _state: END,
        source_segment="spatial_chain",
        internal_nodes=_SPATIAL_INTERNAL,
        cross_map={},
    )

    command = router({"artifact_refs": refs})

    assert command.graph == Command.PARENT
    assert command.goto == END
    assert command.update == {"artifact_refs": refs}


def test_remap_command_cross_targets() -> None:
    internal = _COGNITIVE_INTERNAL
    # internal target unchanged
    assert _remap_command(_cmd("advance_phase"), internal).goto == "advance_phase"
    assert _remap_command(_cmd("advance_phase"), internal).graph is None
    # cross to spatial chain carries the phase update
    cross = _remap_command(Command(update={"phase": "post_l3"}, goto="target_projection"), internal)
    assert cross.graph == Command.PARENT
    assert cross.goto == "spatial_chain"
    assert cross.update == {"phase": "post_l3", "subgraph_entry": None}
    # END exits the parent
    end = _remap_command(_cmd(END), internal)
    assert end.graph == Command.PARENT
    assert end.goto == END
    # terminal diagnostic exits to the parent diagnostic node
    diag = _remap_command(_cmd("end_diagnostic"), internal)
    assert diag.graph == Command.PARENT
    assert diag.goto == "end_diagnostic"
    # Send fan-out stays internal
    sends = _remap_command(_cmd([Send("l1_worker", {})]), internal)
    assert sends.graph is None
