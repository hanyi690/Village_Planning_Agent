"""Real-session readable stage assertions.

Uses the real DataCatalog session bundle path (uploads → bundle → KG prebuild)
then writes representative step reports and renders the readable Markdown.
"""
import pytest

pytest.importorskip("fastapi")

from tests.fixtures.db import make_session_with_uploads  # noqa: E402

_FULL_UPLOADS = [
    {"file_category": "gis_data", "filename": "landuse.geojson", "file_type": "geojson",
     "gis_data_type": "landuse_current",
     "gis_data": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "properties": {"BSM": "P0000000000000000001", "DLBM": "1100", "area_sqm": 10000},
          "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]}},
    {"file_category": "gis_data", "filename": "road.geojson", "file_type": "geojson",
     "gis_data_type": "road",
     "gis_data": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "properties": {"name": "村道", "BSM": "R1"},
          "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}]}},
    {"file_category": "gis_data", "filename": "boundary.geojson", "file_type": "geojson",
     "gis_data_type": "boundary",
     "gis_data": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "properties": {"name": "村界"},
          "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]}},
]


@pytest.mark.asyncio
async def test_real_session_stages_readable(sqlite_db, pipeline_reset):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = await make_session_with_uploads("sess-real", "金田村", uploads=_FULL_UPLOADS)

        from app.services.session_kg import ensure_session_kg

        snap = await ensure_session_kg(sid, village_name="金田村")
        assert snap is not None and snap.get("triple_count", 0) > 0

        from app.services.step_report import save_step_report

        await save_step_report(sid, "KG_PREBUILD", step_name="kg_prebuild",
                               outputs={"triple_count": snap["triple_count"]},
                               diagnostics={"sfTouches": 3})
        await save_step_report(sid, "EXPLORE", step_name="explore_bridge",
                               outputs={"instructions": 2},
                               diagnostics={"total": 3, "resolved": 2, "unresolved": 1})
        await save_step_report(sid, "EXECUTE", step_name="execute_layout",
                               outputs={"layers": 6},
                               diagnostics={"validation_passed": True})

        from app.services.stage_report import build_stage_report_markdown

        md = await build_stage_report_markdown(sid)
        assert "## KG_PREBUILD / kg_prebuild" in md
        assert "## EXPLORE / explore_bridge" in md
        assert "## EXECUTE / execute_layout" in md
        assert "resolved" in md
        print("\n===== READABLE STAGE REPORT =====")
        print(md)
        print("=================================")
    finally:
        await teardown()
