from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.domain.planning_semantics import FacilityPlanningParameters
from app.data.ingestion.compiler.spec_mapper import map_intervention_to_spec
from app.data.ingestion.ingest import ingest_feature


def _feature(label: str, index: int) -> dict:
    return {
        "type": "Feature",
        "properties": {"注记": label, "分类": "现状设施点"},
        "geometry": {"type": "Point", "coordinates": [116.0 + index / 1000, 24.8]},
    }


def _features() -> list[object]:
    payload = {
        "type": "FeatureCollection",
        "features": [
            *[_feature("站", index) for index in range(3)],
            *[_feature("祠", index + 3) for index in range(13)],
        ],
    }
    features, warnings = ingest_feature(
        payload,
        "current_facility",
        source_uri="file:///data/jintian/annotation.geojson",
    )
    assert warnings == []
    return features


def test_station_retrofit_promotes_all_three_source_points():
    intervention = PlanningIntervention(
        intervention_id="public_service:claim:pub_fac_011",
        name="升级改造公交站亭",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="upgrade",
        problem_addressed="升级改造公交站亭3处，完善候车设施",
        spatial_requirements={
            "source_feature_ids": [
                (getattr(feature, "_raw", {}) or {}).get("source_feature_id")
                for feature in _features()[:3]
            ]
        },
        facility_parameters=FacilityPlanningParameters(
            facility_type="公交站亭",
            action="expand",
            capacity=3,
            capacity_unit="处",
        ),
    )
    spec = map_intervention_to_spec(
        intervention,
        source_features={"facility": _features()},
    )
    assert spec is not None
    assert spec.type == "directional"
    assert len(spec.reference.filter["source_feature_ids"]) == 3


def test_shrine_group_requires_declared_thirteen_count():
    intervention = PlanningIntervention(
        intervention_id="heritage:claim:HC-003",
        name="祠堂功能拓展",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="preserve",
        spatial_requirements={
            "source_feature_ids": [
                (getattr(feature, "_raw", {}) or {}).get("source_feature_id")
                for feature in _features()[3:]
            ]
        },
        facility_parameters=FacilityPlanningParameters(
            facility_type="文化活动中心",
            action="preserve",
        ),
    )
    spec = map_intervention_to_spec(
        intervention,
        source_features={"facility": _features()},
    )
    assert spec is not None
    assert spec.type == "directional"
    assert len(spec.reference.filter["source_feature_ids"]) == 13


def test_source_group_count_mismatch_remains_candidate_only():
    intervention = PlanningIntervention(
        intervention_id="public_service:claim:pub_fac_011",
        name="升级改造公交站亭",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="new",
        problem_addressed="升级改造公交站亭2处，完善候车设施",
        spatial_requirements={
            "source_feature_ids": [
                (getattr(feature, "_raw", {}) or {}).get("source_feature_id")
                for feature in _features()[:2]
            ]
        },
        facility_parameters=FacilityPlanningParameters(
            facility_type="公交站亭",
            action="new",
            capacity=2,
            capacity_unit="处",
        ),
    )
    spec = map_intervention_to_spec(
        intervention,
        source_features={"facility": _features()},
    )
    assert spec is not None
    assert spec.type != "directional"
