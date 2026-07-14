"""Backend render test — verify GIS pipeline produces valid render output."""

import json
import os
import tempfile
import pytest
from pathlib import Path


def _load_jintian_geojson(rel_path: str) -> dict:
    from app.core.settings import JINTIAN_GIS_DIR
    path = Path(JINTIAN_GIS_DIR) / rel_path
    if not path.exists():
        pytest.skip(f"Jintian data not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestRenderPipeline:
    """Verify render_map tool produces valid GISLayerConfig output."""

    def test_render_produces_layers(self):
        from app.tools.gis.render import render_map

        gis_data = {
            "boundary_geojson": _load_jintian_geojson("current/boundary.geojson"),
            "landuse_current_geojson": _load_jintian_geojson("current/landuse.geojson"),
        }

        cmd = render_map.func(
            layout_configs=[],
            gis_data=gis_data,
            tool_call_id="test-render-1",
        )
        messages = cmd.update.get("messages", [])
        result = json.loads(messages[0].content)
        assert result["success"] is True
        layers = result["data"]["layers"]
        assert len(layers) >= 2, f"Expected >=2 layers, got {len(layers)}"

    def test_render_layers_have_required_properties(self):
        from app.tools.gis.render import render_map

        gis_data = {
            "boundary_geojson": _load_jintian_geojson("current/boundary.geojson"),
            "landuse_current_geojson": _load_jintian_geojson("current/landuse.geojson"),
        }

        cmd = render_map.func(
            layout_configs=[],
            gis_data=gis_data,
            tool_call_id="test-render-2",
        )
        messages = cmd.update.get("messages", [])
        result = json.loads(messages[0].content)
        for layer in result["data"]["layers"]:
            assert "layerType" in layer, f"Layer missing layerType"
            assert layer.get("geojson", {}).get("type") == "FeatureCollection", \
                f"Layer {layer.get('layerType')}: not a FeatureCollection"


class TestExportAfterRender:
    """Verify that rendered layers can be exported."""

    def test_render_then_export_produces_valid_output(self):
        import shutil
        from app.tools.gis.export import export_gdb

        landuse = _load_jintian_geojson("current/landuse.geojson")
        gis_data = {
            "boundary_geojson": _load_jintian_geojson("current/boundary.geojson"),
            "landuse_current_geojson": landuse,
            "road_geojson": _load_jintian_geojson("current/road.geojson"),
            "farmland_protection_geojson": _load_jintian_geojson("planned/farmland_protection.geojson"),
            "ecological_protection_geojson": _load_jintian_geojson("planned/ecological_protection.geojson"),
            "construction_zone_geojson": _load_jintian_geojson("planned/construction_zone.geojson"),
        }

        tmpdir = tempfile.mkdtemp(prefix="gis_pipeline_test_")
        try:
            export_cmd = export_gdb.func(
                layout_configs=[],
                allocated_geojson=landuse,
                gis_data=gis_data,
                village_name="金田村",
                output_dir=tmpdir,
                tool_call_id="test-pipeline-2",
            )

            for path in [
                "current/boundary.geojson",
                "current/landuse.geojson",
                "current/road.geojson",
                "planned/landuse.geojson",
                "tables/land_balance.json",
            ]:
                assert os.path.exists(os.path.join(tmpdir, path)), f"Missing: {path}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
