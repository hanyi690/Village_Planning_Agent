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
        {
            "fact_type": "spatial_entity",
            "entity_type": "设施",
            "name": "祠堂",
            "locator": {"place_names": ["社前村"], "relation": "位于社前村"},
        },
        {
            "fact_type": "spatial_entity",
            "entity_type": "地物",
            "name": "园寨",
            "locator": {"place_names": ["园寨"]},
        },
    ])
    assert report["ok"] is True
    assert report["defect_ratio"] == 0.0


def test_validation_reports_missing_spatial_anchor_without_rejecting_scope_facts():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations([
        {
            "fact_type": "scoped_metric",
            "semantic_type": "population",
            "metric": "常住人口",
            "scope": "全村",
            "value": 500,
        },
        {
            "fact_type": "demand",
            "demand_type": "tourism",
            "scope": "全村",
            "value": "发展旅游业",
        },
    ])
    assert report["ok"] is True
    assert report["no_place"] == 2
    assert report["defect_ratio"] == 0.0


def test_validation_rejects_semantically_empty_observation():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations([{"fact_type": "spatial_entity"}])
    assert report["ok"] is False
    assert report["invalid_fact_type"] == 1
    assert report["invalid_semantics"] == 1


def test_validation_rejects_empty_relation_observation():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations([{
        "fact_type": "spatial_relation",
        "subject_ref": "金田河",
        "predicate": "",
        "object_ref": "",
    }])
    assert report["ok"] is False
    assert report["invalid_relation"] == 1


def test_validation_enforces_the_dimension_fact_vocabulary():
    from app.domain.assessment.observation_quality import validate_observations

    report = validate_observations(
        [{
            "fact_type": "demand",
            "demand_type": "养老服务",
            "scope": "全村",
        }],
        dimension_key="location",
    )

    assert report["ok"] is False
    assert report["invalid_fact_type"] == 1


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


def test_quality_deadlock_retry_dispatches_failed_dimension_with_feedback():
    import asyncio

    from app.workflow.root_graph import apply_human_review_decision

    state = {
        "session_id": "s-quality-deadlock",
        "paused_stage": "layer1",
        "phase": "layer1",
        "human_review_items": [{
            "request_type": "dependency_deadlock_review",
            "context": {"missing_dimensions": ["ecological_green"]},
        }],
        "human_review_decisions": {
            "action": "retry",
            "dimensions": ["ecological_green"],
        },
        "dimension_failures": [{
            "stage": "L1",
            "dimension": "ecological_green",
            "code": "dimension_quality_failed",
            "feedback": "请为每条观察补充空间锚点",
        }],
        "provider_failures": [],
        "fatal_error": None,
        "dimension_retry_counts": {},
        "retry_counts": {},
    }
    result = asyncio.run(apply_human_review_decision(state))
    assert result["provider_resume_dimensions"] == ["ecological_green"]
    assert result["quality_feedback"] == "请为每条观察补充空间锚点"
    assert result["dimension_failures"] == []
    assert result["paused_stage"] is None


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
    assert normalize_unit("hm") == "ha"
    assert normalize_unit("HM") == "ha"
    assert normalize_action("新建") == "new"
    assert normalize_action("升级") == "upgrade"
    assert normalize_action("改扩建") == "expand"
    assert normalize_action("修缮") == "repair"
    assert normalize_action("UPGRADE") == "upgrade"
