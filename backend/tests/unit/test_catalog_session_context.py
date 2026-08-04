"""Tests for DataCatalog._populate_session_context (DB ops mocked)."""

import pytest


def _new_catalog():
    from app.modules.data.catalog.catalog import DataCatalog

    return DataCatalog.__new__(DataCatalog)


@pytest.mark.asyncio
async def test_populate_session_context(monkeypatch):
    from app.modules.schema.types.canonical import VillageBundle

    bundle = VillageBundle(village_name="金田村")
    catalog = _new_catalog()

    async def fake_get_session(session_id):
        return {
            "session_id": session_id,
            "planning_period": "2022-2035年",
            "province": "广东省",
            "city": "肇庆市",
            "county": "广宁县",
            "township": "排沙镇",
            "village_data": "人口 500 人，面积 3.2 平方公里",
            "task_description": "编制村庄规划",
            "constraints": "不占用基本农田",
            "constraints_other": "忽略字段",
        }

    async def fake_get_uploaded(session_id):
        return [
            {
                "original_filename": "村情调研.md",
                "file_category": "village_data",
                "parsed_text": "地形以丘陵为主",
            },
            {"original_filename": "empty.txt", "parsed_text": "   "},
        ]

    async def fake_get_reports(session_id):
        return {
            1: {"location": {"report_id": "r-1", "content": "## 区位", "summary": "{}", "version": 1, "generated_at": ""}}
        }

    monkeypatch.setattr("app.database.operations.get_planning_session_async", fake_get_session)
    monkeypatch.setattr(
        "app.database.operations.get_uploaded_files_by_session_async", fake_get_uploaded
    )
    monkeypatch.setattr("app.database.operations.get_session_reports_async", fake_get_reports)
    monkeypatch.setattr(
        "app.modules.data.documents.loader.list_available_documents",
        lambda *a, **k: [],
    )

    await catalog._populate_session_context(bundle, "sess-001")

    assert bundle.metadata.session_id == "sess-001"
    assert bundle.metadata.planning_period == "2022-2035年"
    assert bundle.metadata.province == "广东省"
    assert bundle.metadata.city == "肇庆市"
    assert bundle.metadata.county == "广宁县"
    assert bundle.metadata.township == "排沙镇"
    assert bundle.metadata.bundle_version == "1.0"
    assert bundle.metadata.built_at

    sources = [t["source"] for t in bundle.documents.planning_texts]
    assert sources == ["village_data", "task_description", "constraints", "upload"]
    contents = {t["source"]: t["content"] for t in bundle.documents.planning_texts}
    assert contents["village_data"] == "人口 500 人，面积 3.2 平方公里"
    assert contents["upload"] == "地形以丘陵为主"

    assert bundle.layer_reports[1]["location"]["report_id"] == "r-1"


@pytest.mark.asyncio
async def test_populate_session_context_no_session(monkeypatch):
    from app.modules.schema.types.canonical import VillageBundle

    bundle = VillageBundle(village_name="金田村")
    catalog = _new_catalog()

    async def fake_get_session(session_id):
        return None

    async def fake_get_uploaded(session_id):
        return []

    async def fake_get_reports(session_id):
        return {}

    monkeypatch.setattr("app.database.operations.get_planning_session_async", fake_get_session)
    monkeypatch.setattr(
        "app.database.operations.get_uploaded_files_by_session_async", fake_get_uploaded
    )
    monkeypatch.setattr("app.database.operations.get_session_reports_async", fake_get_reports)
    monkeypatch.setattr(
        "app.modules.data.documents.loader.list_available_documents",
        lambda *a, **k: [],
    )

    await catalog._populate_session_context(bundle, "sess-missing")

    assert bundle.metadata.session_id == ""
    assert bundle.documents.planning_texts == []
    assert bundle.layer_reports == {}


@pytest.mark.asyncio
async def test_populate_session_context_merges_uploaded_gis(monkeypatch):
    from app.modules.schema.types.canonical import VillageBundle

    bundle = VillageBundle(village_name="金田村")
    catalog = _new_catalog()

    async def fake_get_session(session_id):
        return {"session_id": session_id, "village_name": "金田村"}

    async def fake_get_uploaded(session_id, file_category=None):
        if file_category == "gis_data":
            return [
                {
                    "gis_data_type": "upload_roads",
                    "gis_data": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {"name": "村道"}},
                            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.5, 0.5]}, "properties": {"BSM": "u1"}},
                            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}, "properties": {}},
                        ],
                    },
                }
            ]
        return []

    async def fake_get_reports(session_id):
        return {}

    monkeypatch.setattr("app.database.operations.get_planning_session_async", fake_get_session)
    monkeypatch.setattr(
        "app.database.operations.get_uploaded_files_by_session_async", fake_get_uploaded
    )
    monkeypatch.setattr("app.database.operations.get_session_reports_async", fake_get_reports)
    monkeypatch.setattr(
        "app.modules.data.documents.loader.list_available_documents",
        lambda *a, **k: [],
    )

    await catalog._populate_session_context(bundle, "sess-001")

    lines = bundle.lines.get("upload_upload_roads")
    points = bundle.points.get("upload_upload_roads")
    polygons = bundle.polygons.get("upload_upload_roads")
    assert len(lines) == 1
    assert len(points) == 1
    assert len(polygons) == 1

    assert points[0].bsm == "u1"
    assert lines[0]._raw["name"] == "村道"
    assert lines[0].layer_type == "upload_upload_roads"


@pytest.mark.asyncio
async def test_populate_session_context_reinfers_dirty_gis_type(monkeypatch):
    """Placeholder gis_data_type (upload/auto/unknown) re-inferred from filename.

    A legacy upload row stored with a placeholder type must still land its
    features in the canonical bundle group, otherwise the KG prebuild silently
    produces an empty graph (660 parcels dropped).
    """
    from app.modules.schema.types.canonical import VillageBundle

    bundle = VillageBundle(village_name="金田村")
    catalog = _new_catalog()

    async def fake_get_session(session_id):
        return {"session_id": session_id, "village_name": "金田村"}

    async def fake_get_uploaded(session_id, file_category=None):
        if file_category == "gis_data":
            return [
                {
                    "original_filename": "landuse.geojson",
                    "gis_data_type": "upload",
                    "gis_data": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}, "properties": {"BSM": "P1", "DLBM": "1100"}},
                        ],
                    },
                }
            ]
        return []

    async def fake_get_reports(session_id):
        return {}

    monkeypatch.setattr("app.database.operations.get_planning_session_async", fake_get_session)
    monkeypatch.setattr(
        "app.database.operations.get_uploaded_files_by_session_async", fake_get_uploaded
    )
    monkeypatch.setattr("app.database.operations.get_session_reports_async", fake_get_reports)
    monkeypatch.setattr(
        "app.modules.data.documents.loader.list_available_documents",
        lambda *a, **k: [],
    )

    await catalog._populate_session_context(bundle, "sess-001")

    polygons = bundle.polygons.get("landuse_current")
    assert len(polygons) == 1
    assert "upload:landuse_current" in bundle.metadata.provider_sources
    assert polygons[0].dlbm == "1100"


@pytest.mark.asyncio
async def test_load_village_bundle_async_calls_sync_and_populate(monkeypatch):
    from app.modules.schema.types.canonical import VillageBundle

    catalog = _new_catalog()

    calls = {"sync": 0}

    def fake_sync_load(village_name, layer_types=None):
        calls["sync"] += 1
        return VillageBundle(village_name=village_name)

    async def fake_populate(bundle, session_id):
        bundle.metadata.session_id = session_id

    monkeypatch.setattr(catalog, "load_village_bundle", fake_sync_load)
    monkeypatch.setattr(catalog, "_populate_session_context", fake_populate)

    bundle = await catalog.load_village_bundle_async("金田村", session_id="sess-001")

    assert calls["sync"] == 1
    assert bundle.village_name == "金田村"
    assert bundle.metadata.session_id == "sess-001"

    bundle2 = await catalog.load_village_bundle_async("金田村")
    assert calls["sync"] == 2
    assert bundle2.metadata.session_id == ""


@pytest.mark.asyncio
async def test_load_village_bundle_skips_wms_url_results(monkeypatch):
    """WMS-URL-only results (no vector data) must be skipped, not crash.

    api_vector falls back to a visualization-only WMS URL when no vector data
    is available (e.g. missing GD_TIANDITU_TOKEN). Such a result used to reach
    the adapter and raise a ValueError on a non-FeatureCollection payload.
    """
    from app.modules.data.contracts import DataResult

    catalog = _new_catalog()
    monkeypatch.setattr(catalog, "_load_boundary", lambda village_name: None)
    monkeypatch.setattr(catalog, "_geocode_village", lambda village_name: (0.0, 0.0, 1.0, 1.0))

    road_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.1, 0.1], [0.2, 0.2]]},
                "properties": {"name": "村道", "BSM": "R1"},
            }
        ],
    }

    def fake_query_by_bbox(bbox, layer_types):
        return {
            "urban_dev_boundary": DataResult.ok(
                data={"wms_url": "http://example.test/wms"},
                data_type="url",
            ),
            "current_road": DataResult.ok(data=road_geojson, data_type="geojson"),
        }

    monkeypatch.setattr(catalog, "query_by_bbox", fake_query_by_bbox)

    bundle = catalog.load_village_bundle("金田村")

    assert bundle.parcel_count == 0
    roads = bundle.lines.get("roads_current") or []
    assert len(roads) == 1
    assert roads[0].layer_type == "current_road"
