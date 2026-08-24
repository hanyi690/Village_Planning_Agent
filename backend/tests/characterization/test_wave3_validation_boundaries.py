from __future__ import annotations

from app.contracts.planning.scenario import PlanningScenario, ScenarioFeature
from app.contracts.spatial.planned_state_contracts import (
    PlannedFacility,
    PlannedState,
    PlannedZone,
    PlannedZoneOverlay,
)
from app.domain.validation.relation_validation import validate_final_scenario
from app.domain.validation.checks import check_quantitative_drift
from app.domain.materialization.nodes.merge_and_materialize import _enrich_planned_state


def _feature(feature_id: str, target_id: str, candidate_id: str, geometry_kind: str, wkt: str) -> ScenarioFeature:
    return ScenarioFeature(
        feature_id=feature_id,
        scenario_id="scenario:boundary",
        target_id=target_id,
        candidate_id=candidate_id,
        geometry_kind=geometry_kind,
        geometry_wkt=wkt,
        crs="EPSG:3857",
        generation_operation="test",
        source_refs=[f"source:{candidate_id}"],
        relation_ids=[f"selection:{target_id}:{candidate_id}"],
    )


def test_baseline_overlay_does_not_inherit_planned_state_scenario() -> None:
    scenario = PlanningScenario(
        scenario_id="scenario:boundary",
        baseline_ref="baseline:test",
        problem_fingerprint="problem:test",
        feature_intents=[_feature("feature:selected", "target:selected", "candidate:selected", "polygon", "POLYGON ((0 0, 2 0, 2 2, 0 0))")],
    )
    state = PlannedState(
        scenario_id="scenario:boundary",
        parcels=[
            {
                "feature_id": "feature:selected",
                "candidate_id": "candidate:selected",
                "target_ref": "target:selected",
                "scenario_id": "scenario:boundary",
                "geometry": "POLYGON ((0 0, 2 0, 2 2, 0 0))",
            }
        ],
        overlays=[
            PlannedZoneOverlay(
                overlay_id="baseline:overlay",
                materialization_role="protection_overlay",
                target_ref="baseline:overlay",
                geometry="POLYGON ((10 10, 11 10, 11 11, 10 10))",
                scenario_id="",
            )
        ],
    )
    report = validate_final_scenario(scenario, state, type("Problem", (), {"constraint_factors": [], "fingerprint": "problem:test"})())
    assert not any(item.code == "orphan_final_feature" and item.target_id == "baseline:overlay" for item in report.findings)


def test_point_only_facility_does_not_require_unrelated_polygon() -> None:
    scenario = PlanningScenario(
        scenario_id="scenario:boundary",
        baseline_ref="baseline:test",
        problem_fingerprint="problem:test",
        feature_intents=[_feature("feature:facility", "target:facility", "candidate:facility", "point", "POINT (100 100)")],
    )
    state = PlannedState(
        scenario_id="scenario:boundary",
        zones=[PlannedZone(zone_id="zone:other", target_ref="target:other", geometry="POLYGON ((0 0, 2 0, 2 2, 0 0))")],
        facilities=[PlannedFacility(feature_id="feature:facility", candidate_id="candidate:facility", derived_from_target="target:facility", scenario_id="scenario:boundary", geometry="POINT (100 100)", relation_ids=["selection:target:facility:candidate:facility"], source_refs=["source:facility"])],
    )
    report = validate_final_scenario(scenario, state, type("Problem", (), {"constraint_factors": [], "fingerprint": "problem:test"})())
    assert not any(item.code == "cross_layer_orphan_point" for item in report.findings)


def test_enrich_keeps_selected_overlay_and_drops_constraint_inventory() -> None:
    selected = PlannedZoneOverlay(
        overlay_id="target:selected",
        materialization_role="functional_overlay",
        target_ref="target:selected",
        candidate_id="candidate:selected",
        feature_id="feature:selected",
        geometry="POLYGON ((0 0, 2 0, 2 2, 0 0))",
    )
    layout = [
        {
            "layerType": "functional_overlay",
            "data": {
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                        "properties": {"target_id": "target:selected", "materialization_role": "functional_overlay"},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]},
                        "properties": {"target_id": "target:baseline", "materialization_role": "functional_overlay"},
                    },
                ]
            },
        }
    ]
    enriched, diagnostics = _enrich_planned_state(PlannedState(overlays=[selected]), layout)
    assert diagnostics == []
    assert [item.target_ref for item in enriched.overlays] == ["target:selected"]
    assert enriched.overlays[0].candidate_id == "candidate:selected"


def test_quantitative_drift_ignores_zero_area_overlay_placeholders() -> None:
    intervention = type("Intervention", (), {"area_range_ha": [950.0, 950.0]})()
    zero_area_parcel = type("Parcel", (), {"area_ha": 0.0})()
    program = type("Program", (), {"interventions": [intervention]})()
    state = type("State", (), {"parcels": [zero_area_parcel]})()
    assert check_quantitative_drift(program, state) == []


def test_quantitative_drift_excludes_preserved_split_remainder() -> None:
    intervention = type("Intervention", (), {"area_range_ha": [0.022, 0.022]})()
    footprint_a = type("Parcel", (), {"area_ha": 0.010, "operation": "create"})()
    footprint_b = type("Parcel", (), {"area_ha": 0.012, "operation": "create"})()
    remainder = type("Parcel", (), {"area_ha": 0.054, "operation": "preserve"})()
    program = type("Program", (), {"interventions": [intervention]})()
    state = type("State", (), {"parcels": [footprint_a, footprint_b, remainder]})()
    assert check_quantitative_drift(program, state) == []


def test_quantitative_drift_ignores_deferred_area_claims_outside_materialized_batch() -> None:
    selected = type(
        "Intervention",
        (),
        {
            "intervention_id": "target:selected",
            "target_id": "target:selected",
            "project_package_ref": "pkg:selected",
            "area_range_ha": [0.022, 0.022],
        },
    )()
    deferred = type(
        "Intervention",
        (),
        {
            "intervention_id": "target:deferred",
            "target_id": "target:deferred",
            "project_package_ref": "pkg:deferred",
            "area_range_ha": [35.0, 35.0],
        },
    )()
    footprint_a = type("Parcel", (), {"area_ha": 0.010, "operation": "create", "project_ref": "target:selected"})()
    footprint_b = type("Parcel", (), {"area_ha": 0.012, "operation": "create", "project_ref": "target:selected"})()
    remainder = type("Parcel", (), {"area_ha": 0.054, "operation": "preserve", "project_ref": "parcel-resource:source"})()
    program = type("Program", (), {"interventions": [selected, deferred]})()
    state = type("State", (), {"parcels": [footprint_a, footprint_b, remainder]})()
    assert check_quantitative_drift(program, state) == []
