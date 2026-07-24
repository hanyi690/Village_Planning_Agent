"""Test script for multi-source GIS data drivers.

Validates all driver implementations with the catalog configuration.
Run: cd backend && python scripts/test_data_drivers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.modules.gis.data.catalog import DataCatalog
from app.modules.gis.data.drivers import (
    DriverRegistry,
    FileVectorDriver,
    TiandituVectorDriver,
    TiandituTileDriver,
    LocalRasterDriver,
    RemoteRasterDriver,
)
from app.modules.gis.schema.canonical import BBox


def test_registry():
    """Test driver registry."""
    print("=" * 60)
    print("TEST: DriverRegistry")
    print("=" * 60)

    drivers = DriverRegistry.list_drivers()
    expected = {
        "file_vector",
        "tianditu_vector",
        "tianditu_tile",
        "local_raster",
        "remote_raster",
    }
    actual = set(drivers.keys())

    print(f"Registered drivers: {sorted(actual)}")
    assert expected <= actual, f"Missing: {expected - actual}"
    print("PASS: All expected drivers registered")
    print()


def test_file_vector_driver():
    """Test FileVectorDriver with existing and missing files."""
    print("=" * 60)
    print("TEST: FileVectorDriver")
    print("=" * 60)

    # Missing file
    driver = FileVectorDriver({
        "path": "nonexistent.geojson",
        "format": "geojson",
        "layer_type": "test",
    })
    result = driver.fetch()
    assert not result.success
    assert "not found" in result.error.lower()
    print("PASS: Missing file handled correctly")

    # Existing file (from catalog)
    catalog = DataCatalog()
    if "jintian_current_landuse" in catalog.list_sources():
        src = catalog.get_source("jintian_current_landuse")
        result = src.fetch()
        assert result.success
        assert result.data_type == "geojson"
        features = result.data.get("features", [])
        print(f"PASS: Loaded {len(features)} features from landuse.geojson")
    else:
        print("SKIP: jintian_current_landuse not in catalog")

    print()


def test_tianditu_vector_driver():
    """Test TiandituVectorDriver metadata."""
    print("=" * 60)
    print("TEST: TiandituVectorDriver")
    print("=" * 60)

    driver = TiandituVectorDriver({
        "service_id": "SQSXWPSJ",
        "protocol": "mapserver_rest",
        "layers": [
            {"id": 0, "name": "test", "layer_type": "farmland_protection"},
        ],
        "crs": "EPSG:4490",
    })

    meta = driver.get_metadata()
    assert meta.name == "SQSXWPSJ"
    assert meta.driver == "tianditu_vector"
    print(f"PASS: Metadata correct — name={meta.name}, driver={meta.driver}")

    layer_types = driver.list_layer_types()
    assert "farmland_protection" in layer_types
    print(f"PASS: Layer types: {layer_types}")

    assert driver.supports_bbox_query
    print("PASS: Supports bbox query")
    print()


def test_tianditu_tile_driver():
    """Test TiandituTileDriver tile math."""
    print("=" * 60)
    print("TEST: TiandituTileDriver")
    print("=" * 60)

    driver = TiandituTileDriver({
        "layer": "img_c",
        "projection": "c",
        "zoom_range": [1, 18],
        "cache_dir": "data/cache/tiles/test",
        "layer_type": "dom",
    })

    # Test bbox to tiles
    bbox = BBox(west=115.5, south=24.0, east=115.6, north=24.1)
    tiles = driver._bbox_to_tiles(bbox, zoom=10)
    assert len(tiles) > 0
    print(f"PASS: BBox → {len(tiles)} tiles at z=10")

    # Verify tile coordinates are valid
    for x, y, z in tiles:
        assert 0 <= x < 2 ** z
        assert 0 <= y < 2 ** z
    print("PASS: All tile coordinates valid")

    meta = driver.get_metadata()
    assert meta.driver == "tianditu_tile"
    print(f"PASS: Metadata — name={meta.name}, driver={meta.driver}")

    print()


def test_local_raster_driver():
    """Test LocalRasterDriver with missing file."""
    print("=" * 60)
    print("TEST: LocalRasterDriver")
    print("=" * 60)

    driver = LocalRasterDriver({
        "path": "nonexistent.tif",
        "format": "GeoTIFF",
        "layer_type": "dem",
    })

    result = driver.fetch()
    assert not result.success
    assert "not found" in result.error.lower()
    print("PASS: Missing file handled correctly")

    meta = driver.get_metadata()
    assert meta.driver == "local_raster"
    print(f"PASS: Metadata — name={meta.name}, driver={meta.driver}")

    print()


def test_remote_raster_driver():
    """Test RemoteRasterDriver download guide."""
    print("=" * 60)
    print("TEST: RemoteRasterDriver")
    print("=" * 60)

    driver = RemoteRasterDriver({
        "provider": "alos_aw3d30",
        "resolution": "12.5m",
        "format": "GeoTIFF",
        "layer_type": "dem",
        "download_guide": {
            "url": "https://example.com",
            "steps": ["step1", "step2"],
        },
        "local_path": "nonexistent.tif",
    })

    result = driver.fetch()
    assert not result.success
    assert result.data_type == "download_guide"
    guide = result.data.get("download_guide", {})
    assert "steps" in guide
    print(f"PASS: Download guide returned — {len(guide['steps'])} steps")

    meta = driver.get_metadata()
    assert meta.driver == "remote_raster"
    assert meta.resolution == 12.5
    print(f"PASS: Metadata — provider={meta.name}, resolution={meta.resolution}m")

    print()


def test_catalog():
    """Test DataCatalog with full configuration."""
    print("=" * 60)
    print("TEST: DataCatalog")
    print("=" * 60)

    catalog = DataCatalog()
    sources = catalog.list_sources()
    print(f"Total sources: {len(sources)}")

    # Categorize
    by_driver = {}
    for name in sources:
        # We can't easily get driver name from instance, but we can check types
        src = catalog.get_source(name)
        driver_type = src.driver_type
        by_driver.setdefault(driver_type, []).append(name)

    for dtype, names in sorted(by_driver.items()):
        print(f"  {dtype}: {len(names)} sources")

    # Test query
    bbox = BBox(west=115.5, south=24.0, east=115.6, north=24.1)
    results = catalog.query_by_bbox(bbox, ["landuse_current", "farmland_protection"])
    for lt, result in results.items():
        status = "OK" if result.success else "FAIL"
        print(f"  Query {lt}: {status}")

    print("PASS: Catalog query complete")
    print()


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("GIS Multi-Source Data Driver Tests")
    print("=" * 60 + "\n")

    tests = [
        test_registry,
        test_file_vector_driver,
        test_tianditu_vector_driver,
        test_tianditu_tile_driver,
        test_local_raster_driver,
        test_remote_raster_driver,
        test_catalog,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"FAIL: {test.__name__}: {e}")
            print()

    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
