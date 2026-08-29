from app.workflow.delivery.geometry_lineage import (
    validate_executable_resource_ref,
    validate_render_feature,
)


def test_external_observation_can_support_but_not_execute():
    result = validate_executable_resource_ref(
        "external-observation:o-1",
        evidence_refs=["external-observation:o-1"],
    )
    assert result["status"] == "rejected"
    assert result["code"] == "external_observation_not_executable"


def test_local_resource_is_executable_with_separate_evidence():
    result = validate_executable_resource_ref(
        "dataset:landuse/feature-1",
        evidence_refs=["external-observation:o-1"],
    )
    assert result["status"] == "accepted"


def test_planned_render_feature_reports_missing_lineage():
    result = validate_render_feature(
        {"geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {}},
        planned=True,
    )
    assert result == {"status": "diagnostic_only", "code": "missing_geometry_lineage"}
