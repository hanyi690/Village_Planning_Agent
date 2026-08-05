"""VALIDATE hardening: missing constraint index, area-conservation audit, traceability."""

from app.agent.validate.aggregate import validate_aggregate
from app.agent.validate.checks import (
    check_area_conservation,
    check_hard_constraints,
    check_traceability,
    check_topology,
)
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent
from app.modules.schema.contracts.planned_state_contracts import PlannedParcel, PlannedState

UNIT_SQUARE = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
HALF_SQUARE = [[0.0, 0.0], [0.0, 1.0], [0.5, 1.0], [0.5, 0.0], [0.0, 0.0]]
EQUAL_SQUARE = [[2.0, 2.0], [2.0, 3.0], [3.0, 3.0], [3.0, 2.0], [2.0, 2.0]]


def _wkt(coords):
    ring = ", ".join(f"{x} {y}" for x, y in coords)
    return f"POLYGON (({ring}))"


def _make_change(bsm, action="modify", before_wkt="", after_wkt="", derived=None, project_ref=None):
    return ParcelChange(
        bsm=bsm,
        action=action,
        derived_from_bsms=list(derived or []),
        before_geometry_wkt=before_wkt,
        after_geometry_wkt=after_wkt,
        project_ref=project_ref,
    )


def _make_changeset(changes=None):
    return ParcelChangeSet(changes=list(changes or []))


def _polygon_feature(coords, name=""):
    return {
        "type": "Feature",
        "properties": {"name": name},
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


def _make_layout(layer_type, features):
    return [
        {
            "layerType": layer_type,
            "data": {"type": "FeatureCollection", "features": list(features)},
        }
    ]


def test_hard_constraints_missing_index_fails():
    checks = check_hard_constraints(None, None)
    assert checks[0].passed is False
    assert checks[0].check_id == "hard_constraints"
    assert checks[0].responsible_stage == "SELECT"


def test_area_conservation_drift_detected():
    before = _wkt(UNIT_SQUARE)
    after = _wkt(HALF_SQUARE)
    changeset = _make_changeset(
        changes=[_make_change("P002", action="split", before_wkt=before, after_wkt=after, derived=["P001"])]
    )
    checks = check_area_conservation(changeset)
    assert checks[0].passed is False
    assert "drift" in checks[0].actual_value

    conserving = _make_changeset(
        changes=[_make_change("P003", action="split", before_wkt=before, after_wkt=_wkt(EQUAL_SQUARE), derived=["P001"])]
    )
    assert check_area_conservation(conserving)[0].passed is True


def test_area_conservation_create_ignored():
    changeset = _make_changeset(
        changes=[_make_change("P004", action="create", after_wkt=_wkt(UNIT_SQUARE))]
    )
    assert check_area_conservation(changeset)[0].passed is True


def test_topology_detects_project_layer():
    project = _make_layout("project", [_polygon_feature(UNIT_SQUARE, "PROJ1")])
    project_gaps = next(c for c in check_topology(project) if c.check_id == "topology_gaps")
    assert project_gaps.passed is True

    road = [
        {
            "layerType": "road",
            "data": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "RD1"},
                        "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
                    }
                ],
            },
        }
    ]
    road_gaps = next(c for c in check_topology(road) if c.check_id == "topology_gaps")
    assert road_gaps.passed is True


def test_traceability_missing_project_fails():
    intent = SpatialPlanningIntent(project_targets=[ProjectTarget(project_id="p1", name="P1")])
    changeset = _make_changeset(changes=[_make_change("P002", project_ref="p2")])
    checks = check_traceability(changeset, intent)
    assert checks[0].passed is False
    assert "p1" in checks[0].actual_value
    assert checks[0].affected_parcels == ["p1"]

    matching = _make_changeset(changes=[_make_change("P002", project_ref="p1")])
    assert check_traceability(matching, intent)[0].passed is True

    no_ref = _make_changeset(changes=[_make_change("P002")])
    assert check_traceability(no_ref, intent)[0].passed is False


def test_validate_aggregate_includes_traceability():
    state = PlannedState(parcels=[PlannedParcel(bsm="P001", geometry=_wkt(UNIT_SQUARE))])
    changeset = _make_changeset(changes=[_make_change("P001", project_ref="p1")])
    intent = SpatialPlanningIntent(project_targets=[ProjectTarget(project_id="p1", name="P1")])
    layouts = _make_layout("parcel", [_polygon_feature(UNIT_SQUARE, "Z1")])
    report = validate_aggregate(state, changeset, layouts, intent, None)
    trace = next(c for c in report.checks if c.check_id == "traceability")
    assert trace.passed is True
    assert trace.responsible_stage == "EXECUTE"
