"""Observation quality retry loop (design: validation step + single-dimension
retry with corrective feedback).

Covers: quality validation, dimension_failures routing to HUMAN, and the
resume dispatch carrying corrective feedback to the retried worker.
"""
from __future__ import annotations


def test_validation_accepts_good_observations():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations([
        {"name": "??", "location": "???", "relation": "?????"},
        {"name": "??", "location": "??", "relation": ""},
    ])
    assert report["ok"] is True
    assert report["defect_ratio"] == 0.0


def test_validation_flags_missing_spatial_anchor():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations([
        {"name": "???", "location": "", "relation": ""},
        {"name": "???", "location": "??", "relation": ""},
    ])
    assert report["ok"] is False
    assert report["no_place"] == 1
    assert "????" in report["feedback"]


def test_validation_flags_missing_name():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations([
        {"name": "", "location": "???", "relation": ""},
    ])
    assert report["ok"] is False
    assert report["missing_name"] == 1


def test_dimension_failures_route_to_human_review():
    from app.workflow.conversation.edges import after_analysis

    state = {
        "phase": "layer1",
        "is_revision": False,
        "dimension_failures": [{
            "stage": "L1",
            "dimension": "location",
            "code": "dimension_quality_failed",
            "message": "quality defect",
        }],
    }
    assert after_analysis(state) == "human_review"


def test_provider_failure_dimensions_collects_quality_failures():
    from app.workflow.root_graph import _provider_failure_dimensions

    state = {
        "dimension_failures": [
            {"dimension": "location", "code": "dimension_quality_failed"},
        ]
    }
    assert _provider_failure_dimensions(state, []) == ["location"]


def test_provider_resume_dispatch_carries_feedback():
    from langgraph.types import Send

    from app.workflow.layers.layer_router import provider_resume_dispatch_node

    state = {
        "phase": "layer1",
        "provider_resume_dimensions": ["location"],
        "dimension_failures": [
            {
                "dimension": "location",
                "code": "dimension_quality_failed",
                "feedback": "???????",
            }
        ],
    }
    command = provider_resume_dispatch_node(state)
    assert command.update == {"provider_resume_dimensions": []}
    assert len(command.goto) == 1
    payload = command.goto[0].arg
    assert payload["dimension_key"] == "location"
    assert payload["quality_feedback"] == "???????"
