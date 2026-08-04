"""EXECUTE review package tests - build_execute_review_package + build_before_after_geojson."""

import json

from app.agent.execute.review import (
    build_before_after_geojson,
    build_execute_review_package,
)
from app.modules.schema.contracts.classification_ref import ClassificationRef
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.planned_state_contracts import (
    PlannedAxis,
    PlannedFacility,
    PlannedParcel,
    PlannedRoad,
    PlannedState,
)
from app.modules.schema.contracts.provenance import Provenance

_SECTION_KEYS = {
    "操作日志",
    "面积守恒",
    "地块谱系",
    "前后对比图",
    "PlannedState 摘要",
    "设施/道路/轴线清单",
    "未解析目标",
    "来源追溯",
}

_WKT = "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))"


def make_change(action, bsm, derived, before_code, after_code, wkt):
    return ParcelChange(
        bsm=bsm,
        action=action,
        derived_from_bsms=derived,
        before_classification=ClassificationRef(
            code=before_code,
            canonical_name=before_code,
            system="GB/T 21010",
            source="derived",
        ),
        after_classification=ClassificationRef(
            code=after_code,
            canonical_name=after_code,
            system="GB/T 21010",
            source="derived",
        ),
        before_geometry_wkt=wkt,
        after_geometry_wkt=wkt,
    )


def make_changeset():
    return ParcelChangeSet(
        changes=[
            make_change("reclassify", "P001", ["P001"], "0101", "0701", _WKT),
            make_change("reclassify", "P002", ["P002"], "0101", "0701", _WKT),
            make_change("merge", "P003", ["P001", "P002"], "", "0701", _WKT),
        ],
        area_conservation_verified=True,
        geometry_validity_verified=True,
        provenance=Provenance(source="land_design_worker", run_id="r1", module="x"),
    )


def make_planned_state():
    return PlannedState(
        version="v1",
        parcels=[
            PlannedParcel(bsm="P001", planning_land_use="0701", operation="reclassify")
        ],
        facilities=[
            PlannedFacility(name="school", facility_type="school", lon=0.01, lat=0.01)
        ],
        roads=[PlannedRoad(name="r1", road_level="village_road")],
        axes=[PlannedAxis(name="a1", reference_feature="路", direction="南北")],
        source="parcel_change_set",
    )


def _parcel_by_bsm():
    return {
        "P001": {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
            }
        }
    }


def _package(changeset=None, planned_state=None):
    return build_execute_review_package(
        changeset or make_changeset(),
        planned_state or make_planned_state(),
    )


def test_sections_present():
    assert set(_package().keys()) == _SECTION_KEYS


def test_operation_log():
    log = _package()["操作日志"]

    assert log["total"] == 3
    assert log["by_action"]["reclassify"] == 2
    assert log["by_action"]["merge"] == 1


def test_area_conservation():
    area = _package()["面积守恒"]

    assert area["area_conservation_verified"] is True
    assert area["geometry_validity_verified"] is True
    assert area["changes"] == 3


def test_parcel_lineage():
    lineage = _package()["地块谱系"]

    assert len(lineage) == 3
    first = lineage[0]
    assert first["bsm"] == "P001"
    assert first["action"] == "reclassify"
    assert first["derived_from_bsms"] == ["P001"]
    assert first["before_classification_code"] == "0101"
    assert first["after_classification_code"] == "0701"


def test_before_after_geojson():
    fc = build_before_after_geojson(make_changeset(), _parcel_by_bsm())

    assert fc["type"] == "FeatureCollection"
    assert fc["properties"]["note"] == "EXECUTE before/after parcel comparison"
    assert len(fc["features"]) >= 1
    feature = fc["features"][0]
    assert feature["type"] == "Feature"
    assert feature["properties"]["bsm"] == "P001"
    assert feature["properties"]["action"] == "reclassify"
    assert feature["properties"]["after_geometry_wkt"] == _WKT
    assert feature["properties"]["derived_from_bsms"] == ["P001"]
    assert feature["geometry"] is not None
    assert feature["geometry"]["type"] == "Polygon"


def test_before_after_geojson_geometry_fallback():
    changeset = ParcelChangeSet(
        changes=[make_change("reclassify", "P001", ["P001"], "0101", "0701", "")],
        area_conservation_verified=True,
        geometry_validity_verified=True,
    )

    fc = build_before_after_geojson(changeset, _parcel_by_bsm())

    assert len(fc["features"]) == 1
    assert fc["features"][0]["geometry"]["type"] == "Polygon"


def test_before_after_geojson_skips_missing_geometry():
    changeset = ParcelChangeSet(
        changes=[make_change("reclassify", "P999", ["P999"], "0101", "0701", "")],
        area_conservation_verified=True,
        geometry_validity_verified=True,
    )

    fc = build_before_after_geojson(changeset, {})

    assert fc["features"] == []


def test_planned_state_summary():
    summary = _package()["PlannedState 摘要"]

    assert summary["parcels"] == 1
    assert summary["zones"] == 0
    assert summary["facilities"] == 1
    assert summary["roads"] == 1
    assert summary["axes"] == 1
    assert summary["version"] == "v1"
    assert summary["source"] == "parcel_change_set"


def test_facility_road_axis_listing():
    listing = _package()["设施/道路/轴线清单"]

    assert listing["facilities"][0]["name"] == "school"
    assert listing["facilities"][0]["facility_type"] == "school"
    assert listing["facilities"][0]["lon"] == 0.01
    assert listing["facilities"][0]["lat"] == 0.01
    assert listing["roads"][0]["road_level"] == "village_road"
    assert listing["axes"][0]["direction"] == "南北"


def test_unresolved_section():
    unresolved = _package()["未解析目标"]

    assert unresolved["count"] == 0
    assert unresolved["note"]


def test_provenance():
    provenance = _package()["来源追溯"]

    assert provenance["source"] == "land_design_worker"
    assert provenance["run_id"] == "r1"


def test_provenance_empty():
    changeset = make_changeset()
    changeset.provenance = None

    assert _package(changeset=changeset)["来源追溯"] == {}


def test_json_serializable():
    json.dumps(_package())
