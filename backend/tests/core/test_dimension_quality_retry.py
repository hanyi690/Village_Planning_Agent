"""Observation quality retry loop (design: validation step + single-dimension
retry with corrective feedback).

Covers: quality validation, dimension_failures routing to HUMAN, resume
dispatch carrying corrective feedback, and L3 program_rework single-dimension
retry.
"""
from __future__ import annotations


def test_validation_accepts_good_observations():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations([
        {"name": "祠堂", "location": "社前村", "relation": "位于社前村"},
        {"name": "园寨", "location": "园寨", "relation": ""},
    ])
    assert report["ok"] is True
    assert report["defect_ratio"] == 0.0


def test_validation_flags_missing_spatial_anchor():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations([
        {"name": "某设施", "location": "", "relation": ""},
        {"name": "另一条", "location": "园寨", "relation": ""},
    ])
    assert report["ok"] is False
    assert report["no_place"] == 1
    assert "空间锚点" in report["feedback"]


def test_validation_flags_missing_name():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations([
        {"name": "", "location": "社前村", "relation": ""},
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
                "feedback": "请补全空间锚点",
            }
        ],
    }
    command = provider_resume_dispatch_node(state)
    assert command.update == {"provider_resume_dimensions": []}
    assert len(command.goto) == 1
    payload = command.goto[0].arg
    assert payload["dimension_key"] == "location"
    assert payload["quality_feedback"] == "请补全空间锚点"


def test_l3_program_rework_approve_retries_only_failed_dimensions():
    """L3 program_rework approval must resolve to a single-dimension retry
    (provider_resume_dimensions), never to the unroutable stage 'l3'."""
    import asyncio

    from app.workflow.root_graph import apply_human_review_decision

    state = {
        "session_id": "s-rework",
        "paused_stage": "l3",
        "human_review_decisions": {"action": "approve", "feedback": "ok"},
        "human_review_items": [
            {
                "request_type": "program_rework",
                "context": {
                    "dimension_key": "industry",
                    "message": "ERROR[unsupported_area_unit] IND-008: area_range unit not supported",
                },
            },
            {
                "request_type": "program_rework",
                "context": {"dimension_key": "settlement_planning", "message": "ERROR[invalid_intervention_action] JT-002"},
            },
            {"request_type": "other", "context": {}},
        ],
        "provider_failures": [],
        "dimension_failures": [],
        "fatal_error": None,
        "dimension_retry_counts": {},
        "phase": "layer3",
        "retry_counts": {},
    }
    result = asyncio.run(apply_human_review_decision(state))
    assert result["autonomous_decision"] == "retry_invalid_l3_dimensions"
    assert result["provider_resume_dimensions"] == ["industry", "settlement_planning"]
    assert "IND-008" in result["quality_feedback"]
    assert "JT-002" in result["quality_feedback"]


def test_l3_program_rework_route_goes_to_provider_resume_dispatch():
    from app.workflow.root_graph import route_after_human_review

    state = {
        "paused_stage": "l3",
        "human_review_decisions": {"action": "retry"},
        "provider_resume_dimensions": ["industry"],
    }
    assert route_after_human_review(state) == "provider_resume_dispatch"


def test_unit_normalization_handles_mojibake_and_aliases():
    from app.domain.program.unit_normalization import normalize_action, normalize_unit

    assert normalize_unit("平方米") == "m2"
    assert normalize_unit("平米") == "m2"
    assert normalize_unit("KM") == "km"
    assert normalize_unit("m²") == "m2"
    assert normalize_unit(" 亩 ") == "mu"
    assert normalize_unit("公顷") == "ha"
    assert normalize_unit("hm²") == "ha"
    assert normalize_unit("hm2") == "ha"
    assert normalize_action("新建") == "new"
    assert normalize_action("升级") == "upgrade"
    assert normalize_action("改扩建") == "expand"
    assert normalize_action("修缮") == "repair"
    assert normalize_action("UPGRADE") == "upgrade"
