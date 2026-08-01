"""Tests for VillageBundle <-> dict serialization (full snapshot roundtrip)."""


def _polygon(coords=None):
    return {
        "type": "Polygon",
        "coordinates": coords or [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    }


def _build_sample_bundle():
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import (
        CurrentFacility,
        CurrentLandUseParcel,
        CurrentRoad,
        WaterFeature,
    )

    bundle = VillageBundle(village_name="金田村")
    bundle.metadata.session_id = "sess-001"
    bundle.metadata.planning_period = "2022-2035年"
    bundle.metadata.province = "广东省"

    parcel = CurrentLandUseParcel(
        geometry=_polygon(),
        bsm="001",
        dlbm="0101",
        area_sqm=12000.0,
        zone_type="agriculture",
    )
    road = CurrentRoad(
        geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        bsm="002",
        road_level="县道",
        road_width=6.5,
    )
    facility = CurrentFacility(
        geometry={"type": "Point", "coordinates": [0.5, 0.5]},
        bsm="003",
        facility_type="学校",
        facility_name="金田小学",
        category="public_service",
    )
    water = WaterFeature(
        geometry=_polygon(),
        bsm="004",
        water_type="坑塘",
        water_name="大塘",
    )

    # Write layer groups directly to preserve stored BSM values.
    bundle.points._layers["facilities_current"] = [facility]
    bundle.lines._layers["roads_current"] = [road]
    bundle.polygons._layers["landuse_current"] = [parcel]
    bundle.polygons._layers["water_bodies"] = [water]

    bundle.documents.planning_texts = [
        {"source": "village_data", "name": "村庄基础数据", "content": "人口 500 人"},
        {"source": "upload", "category": "village_data", "name": "input.md", "content": "上传内容"},
    ]

    bundle.layer_reports = {
        1: {
            "location": {
                "report_id": "r-1",
                "content": "## 区位分析\n...",
                "summary": "{}",
                "version": 1,
                "generated_at": "2026-07-31T10:00:00",
            }
        },
        3: {
            "project_bank": {
                "report_id": "r-9",
                "content": "## 项目库\n...",
                "summary": "{}",
                "version": 1,
                "generated_at": "2026-07-31T12:00:00",
            }
        },
    }
    return bundle


def test_to_from_bundle_dict_roundtrip():
    from app.modules.schema.types.canonical import from_bundle_dict, to_bundle_dict

    bundle = _build_sample_bundle()
    data = to_bundle_dict(bundle)
    restored = from_bundle_dict(data)

    assert restored.village_name == "金田村"
    assert restored.metadata.session_id == "sess-001"
    assert restored.metadata.planning_period == "2022-2035年"
    assert restored.metadata.province == "广东省"

    assert len(restored.polygons.get("landuse_current")) == 1
    assert len(restored.polygons.get("water_bodies")) == 1
    assert len(restored.lines.get("roads_current")) == 1
    assert len(restored.points.get("facilities_current")) == 1

    # BSM preserved exactly (no re-assignment on restore)
    assert restored.polygons.get("landuse_current")[0].bsm == "001"
    assert restored.lines.get("roads_current")[0].bsm == "002"
    assert restored.points.get("facilities_current")[0].bsm == "003"

    # Feature attributes roundtrip
    parcel = restored.polygons.get("landuse_current")[0]
    assert parcel.dlbm == "0101"
    assert parcel.zone_type == "agriculture"
    assert parcel.layer_type == "landuse_current"
    road = restored.lines.get("roads_current")[0]
    assert road.road_width == 6.5
    facility = restored.points.get("facilities_current")[0]
    assert facility.facility_name == "金田小学"
    water = restored.polygons.get("water_bodies")[0]
    assert water.water_type == "坑塘"

    # Documents + reports roundtrip
    assert restored.documents.planning_texts == bundle.documents.planning_texts
    assert restored.layer_reports == bundle.layer_reports
    assert restored.layer_reports[3]["project_bank"]["content"] == "## 项目库\n..."


def test_to_bundle_dict_is_json_serializable():
    import json

    from app.modules.schema.types.canonical import to_bundle_dict

    bundle = _build_sample_bundle()
    data = to_bundle_dict(bundle)
    # Should not raise
    json.dumps(data, ensure_ascii=False)


def test_empty_bundle_roundtrip():
    from app.modules.schema.types.canonical import VillageBundle, from_bundle_dict, to_bundle_dict

    bundle = VillageBundle(village_name="empty")
    restored = from_bundle_dict(to_bundle_dict(bundle))
    assert restored.village_name == "empty"
    assert restored.parcel_count == 0
    assert restored.documents.planning_texts == []
    assert restored.layer_reports == {}
