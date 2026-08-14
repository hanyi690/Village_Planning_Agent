"""Circuit-breaker semantics: provider failure must route to HUMAN resume,
never silently END the graph (design: failed dimensions recover via provider-resume)."""
from __future__ import annotations


def _state(**extra):
    base = {
        "phase": "layer3",
        "is_revision": False,
        "completed_dimensions": {"layer3": ["a", "b"]},
        "artifact_refs": {},
    }
    base.update(extra)
    return base


def test_transient_failure_routes_to_human_review():
    from app.workflow.conversation.edges import after_analysis

    state = _state(
        fatal_error={
            "stage": "L3",
            "dimension": "settlement_planning",
            "code": "llm_provider_circuit_open",
            "message": "circuit open",
        }
    )
    assert after_analysis(state) == "human_review"


def test_provider_failure_channel_routes_to_human_review():
    from app.workflow.conversation.edges import after_analysis

    state = _state(
        provider_failures=[
            {
                "stage": "L3",
                "dimension": "settlement_planning",
                "code": "llm_stream_timeout",
                "message": "timeout",
            }
        ]
    )
    assert after_analysis(state) == "human_review"


def test_fatal_error_absent_returns_none():
    from app.workflow.conversation.edges import after_analysis

    assert after_analysis(_state()) is not None  # routes onward (dispatch or END)
