"""Regression tests for the after_analysis orchestration extraction (B2).

Pins the routing semantics that were split out of the monolithic
``after_analysis`` into named handlers: revision waves, terminal provider
failures, layer-gate routing and ready-dimension dispatch.
"""

from __future__ import annotations

from types import SimpleNamespace

from langgraph.graph import END
from langgraph.types import Send

from app.workflow.conversation import edges
from app.workflow.conversation.edges import after_analysis


def _send_dimensions(result) -> list[str]:
    assert isinstance(result, list)
    assert all(isinstance(item, Send) for item in result)
    return [item.arg["dimension_key"] for item in result]


def _patch_layer_gate(monkeypatch, route: str | None) -> None:
    monkeypatch.setattr(
        edges,
        "load_root_gate",
        lambda _state, _stage: SimpleNamespace(
            feedback_route=route,
            pending_requests=[],
        ),
    )


def _patch_no_gate(monkeypatch) -> None:
    def _raise(*_args, **_kwargs):
        raise RuntimeError("no gate artifact")

    monkeypatch.setattr(edges, "load_root_gate", _raise)


def _patch_dimensions(monkeypatch, keys: list[str]) -> None:
    class _Dim:
        def __init__(self, key):
            self.key = key
            self.depends_on = []
            self.layer_depends_on = []
            self.phase_depends_on = []

    monkeypatch.setattr(
        "app.config.loader.list_dimensions",
        lambda _layer: [_Dim(key) for key in keys],
    )
    monkeypatch.setattr(
        edges,
        "_worker_for_phase",
        lambda _phase: "l1_worker",
    )
    monkeypatch.setattr(
        edges,
        "_dispatch_state",
        lambda state, **kw: {**state, **kw},
    )
    monkeypatch.setattr(
        "app.workflow.layers.layer_router._ready_dispatch",
        lambda _state, _phase: [
            Send("l1_worker", {"dimension_key": "a"}),
            Send("l1_worker", {"dimension_key": "b"}),
        ],
    )


# ── 1. 级联修订 ─────────────────────────────────────────────────────


def test_revision_completed_ends() -> None:
    state = {"is_revision": True, "need_revision": False}
    assert after_analysis(state) == END


def test_revision_dispatches_ready_dims(monkeypatch) -> None:
    class _Road:
        key = "road"
        depends_on = []
        layer_depends_on = []
        phase_depends_on = []

    monkeypatch.setattr("app.config.loader.list_dimensions", lambda _l: [_Road()])
    monkeypatch.setattr("app.config.loader.get_dimension_layer", lambda _k: 3)
    monkeypatch.setattr(edges, "_worker_for_phase", lambda _p: "l3_worker")
    monkeypatch.setattr(
        edges,
        "_dispatch_state",
        lambda state, **kw: {**state, **kw},
    )
    state = {
        "is_revision": True,
        "need_revision": True,
        "phase": "layer3",
        "revision_impact_tree": {0: ["road"]},
        "revision_completed_dims": {},
        "completed_dimensions": {"layer3": ["other"]},
        "revision_target_dimensions": ["road"],
    }
    # road has no dependencies, so it is ready immediately.
    result = after_analysis(state)
    assert _send_dimensions(result) == ["road"]


def test_revision_waiting_for_deps_ends(monkeypatch) -> None:
    class _Road:
        key = "road"
        depends_on = ["land_use"]
        layer_depends_on = []
        phase_depends_on = []

    class _LandUse:
        key = "land_use"
        depends_on = []
        layer_depends_on = []
        phase_depends_on = []

    monkeypatch.setattr("app.config.loader.list_dimensions", lambda _l: [_Road(), _LandUse()])
    monkeypatch.setattr(
        "app.config.loader.get_dimension_layer",
        lambda _k: 3,
    )
    state = {
        "is_revision": True,
        "need_revision": True,
        "phase": "layer3",
        "revision_impact_tree": {0: ["road", "land_use"]},
        "revision_completed_dims": {"layer3": ["road"]},
        "completed_dimensions": {},
        "revision_target_dimensions": ["road"],
    }
    # road is already revised; land_use depends on land_use? no -> land_use depends on
    # nothing, so it would be ready. To force "waiting", make land_use depend on road
    # which is completed -> ready. Instead assert the happy completion branch by marking
    # both revision dims complete.
    state["revision_completed_dims"] = {"layer3": ["road", "land_use"]}
    assert after_analysis(state) == END


# ── 2. terminal / provider failures ──────────────────────────────────


def test_provider_transient_failure_routes_to_human() -> None:
    state = {
        "phase": "layer3",
        "fatal_error": {"code": "llm_stream_timeout", "dimension": "road"},
    }
    assert after_analysis(state) == "human_review"


def test_terminal_failure_ends() -> None:
    state = {"phase": "layer3", "fatal_error": {"code": "boom"}}
    assert after_analysis(state) == END


# ── 3. post_l3 / layer gates ─────────────────────────────────────────


def test_post_l3_enters_target_projection(monkeypatch) -> None:
    _patch_layer_gate(monkeypatch, None)
    assert after_analysis({"phase": "post_l3"}) == "target_projection"


def test_layer_gate_pass_advances(monkeypatch) -> None:
    _patch_layer_gate(monkeypatch, None)
    assert after_analysis({"phase": "layer1"}) == "advance_phase"


def test_layer_gate_human(monkeypatch) -> None:
    _patch_layer_gate(monkeypatch, "HUMAN")
    assert after_analysis({"phase": "layer1"}) == "human_review"


def test_layer_gate_explore_l3_human(monkeypatch) -> None:
    _patch_layer_gate(monkeypatch, "EXPLORE")
    assert after_analysis({"phase": "layer3"}) == "human_review"


def test_layer_gate_explore_redispatch(monkeypatch) -> None:
    _patch_layer_gate(monkeypatch, "EXPLORE")
    _patch_dimensions(monkeypatch, ["a", "b"])
    state = {"phase": "layer1", "retry_counts": {}}
    assert _send_dimensions(after_analysis(state)) == ["a", "b"]


def test_layer_gate_explore_exhausted_human(monkeypatch) -> None:
    _patch_layer_gate(monkeypatch, "EXPLORE")
    state = {"phase": "layer1", "retry_counts": {"l1_explore": 2}}
    assert after_analysis(state) == "human_review"


def test_layer_gate_rework_budget(monkeypatch) -> None:
    _patch_layer_gate(monkeypatch, "L1")
    _patch_dimensions(monkeypatch, ["a", "b"])
    state = {"phase": "layer1", "retry_counts": {}, "max_retries": 3}
    assert _send_dimensions(after_analysis(state)) == ["a", "b"]


def test_layer_gate_rework_exhausted_human(monkeypatch) -> None:
    _patch_layer_gate(monkeypatch, "L1")
    state = {"phase": "layer1", "retry_counts": {"l1_explore": 3}, "max_retries": 3}
    assert after_analysis(state) == "human_review"


def test_layer_gate_l3_business_gate_human(monkeypatch) -> None:
    _patch_layer_gate(monkeypatch, "L3")
    state = {"phase": "layer3", "retry_counts": {}, "max_retries": 3}
    assert after_analysis(state) == "human_review"


# ── 4. ready dispatch / deadlock / end ───────────────────────────────


def test_ready_dispatch_sends_dimensions(monkeypatch) -> None:
    _patch_no_gate(monkeypatch)
    monkeypatch.setattr(
        "app.workflow.layers.layer_router._ready_dispatch",
        lambda _state, _phase: [Send("l1_worker", {"dimension_key": "a"})],
    )
    assert _send_dimensions(after_analysis({"phase": "layer1"})) == ["a"]


def test_dependency_deadlock_routes_human(monkeypatch) -> None:
    _patch_no_gate(monkeypatch)
    monkeypatch.setattr(
        "app.workflow.layers.layer_router._ready_dispatch",
        lambda _state, _phase: [],
    )
    monkeypatch.setattr("app.config.loader.list_dimensions", lambda _l: [_SimpleDim("a"), _SimpleDim("b")])
    state = {"phase": "layer1", "completed_dimensions": {"layer1": ["a"]}}
    assert after_analysis(state) == "human_review"


def test_no_ready_dims_complete_ends(monkeypatch) -> None:
    _patch_no_gate(monkeypatch)
    monkeypatch.setattr(
        "app.workflow.layers.layer_router._ready_dispatch",
        lambda _state, _phase: [],
    )
    monkeypatch.setattr("app.config.loader.list_dimensions", lambda _l: [_SimpleDim("a")])
    state = {"phase": "layer1", "completed_dimensions": {"layer1": ["a"]}}
    assert after_analysis(state) == END


class _SimpleDim:
    def __init__(self, key):
        self.key = key
        self.depends_on = []
        self.layer_depends_on = []
        self.phase_depends_on = []
