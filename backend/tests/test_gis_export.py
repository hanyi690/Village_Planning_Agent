"""Tests for 12-layer GDB export and land balance table."""

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


def _export_and_load(village_name: str = "金田村") -> tuple[str, list[str]]:
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

    tmpdir = tempfile.mkdtemp(prefix="gis_export_test_")
    cmd = export_gdb.func(
        gis_data=gis_data,
        allocated_geojson=landuse,
        layout_configs=[],
        village_name=village_name,
        output_dir=tmpdir,
        tool_call_id="test-export-1",
    )
    messages = cmd.update.get("messages", [])
    result = json.loads(messages[0].content)
    return tmpdir, result["data"]["exported_files"]


class Test12LayerExport:
    """Verify export produces all standard layers."""

    def test_at_least_8_files_exported(self):
        tmpdir, exported = _export_and_load()
        try:
            assert len(exported) >= 8, f"Expected >=8 files, got {len(exported)}: {exported}"
            required = [
                "current/boundary.geojson",
                "current/landuse.geojson",
                "current/road.geojson",
                "planned/landuse.geojson",
                "planned/farmland_protection.geojson",
                "planned/ecological_protection.geojson",
                "planned/construction_zone.geojson",
                "tables/land_balance.json",
            ]
            for path in required:
                full = os.path.join(tmpdir, path)
                assert os.path.exists(full), f"Missing: {path}"
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_each_layer_has_valid_geojson(self):
        tmpdir, exported = _export_and_load()
        try:
            for rel_path in exported:
                if not rel_path.endswith(".geojson"):
                    continue
                full = os.path.join(tmpdir, rel_path)
                with open(full, encoding="utf-8") as f:
                    data = json.load(f)
                assert data.get("type") == "FeatureCollection", \
                    f"{rel_path}: expected FeatureCollection, got {data.get('type')}"
                assert isinstance(data.get("features"), list), \
                    f"{rel_path}: features not a list"
                assert len(data["features"]) > 0, \
                    f"{rel_path}: expected non-empty features"
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestLandBalance:
    """Verify land balance table output."""

    def test_land_balance_has_required_keys(self):
        tmpdir, exported = _export_and_load()
        try:
            balance_path = os.path.join(tmpdir, "tables/land_balance.json")
            assert os.path.exists(balance_path), "Missing land_balance.json"
            with open(balance_path, encoding="utf-8") as f:
                balance = json.load(f)
            assert "total_area_ha" in balance
            assert "planning_zones" in balance
            assert "function_zones" in balance
            assert balance["total_area_ha"] > 0
            assert len(balance["planning_zones"]) >= 2
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_planning_zones_sum_matches_total(self):
        tmpdir, exported = _export_and_load()
        try:
            balance_path = os.path.join(tmpdir, "tables/land_balance.json")
            with open(balance_path, encoding="utf-8") as f:
                balance = json.load(f)
            zone_sum = sum(balance["planning_zones"].values())
            total = max(balance["total_area_ha"], 0.01)
            assert abs(zone_sum - total) / total < 0.1, \
                f"Zone sum {zone_sum:.1f} should be within 10% of total {total:.1f}"
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestFieldAlignment:
    """Verify exported fields match GDB_LAYER_REGISTRY."""

    def test_landuse_core_fields_present(self):
        from app.services.modules.gis.data.gdb_schema import GDB_LAYER_REGISTRY

        tmpdir, exported = _export_and_load()
        try:
            path = os.path.join(tmpdir, "current/landuse.geojson")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            schema_fields = {f[0] for f in GDB_LAYER_REGISTRY["current_landuse"]["fields"]}
            feature = data["features"][0]
            props = feature.get("properties", {})

            core = {"BSM", "DLBM", "DLMC", "DLMJ"}
            missing = core - set(props.keys())
            assert not missing, f"Missing core fields: {missing}"
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
