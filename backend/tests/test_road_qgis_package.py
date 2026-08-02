from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
from PIL import Image

from app.services.modules.gis.road.qgis_package import build_qgis_demo_package


CRS = {"type": "name", "properties": {"name": "EPSG:4326"}}


def _write(path: Path, features: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {"type": "FeatureCollection", "crs": CRS, "features": features},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _feature(geometry: dict | None, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def test_qgis_package_writes_strict_single_family_map_layers(tmp_path: Path) -> None:
    polygon = {"type": "Polygon", "coordinates": [[[116, 24], [117, 24], [117, 25], [116, 25], [116, 24]]]}
    line = {"type": "LineString", "coordinates": [[116.1, 24.1], [116.9, 24.9]]}
    point = {"type": "Point", "coordinates": [116.5, 24.5]}
    sources = {name: tmp_path / f"{name}.geojson" for name in (
        "boundary", "roads", "demands", "buildings", "constraints", "recommended", "segments", "final"
    )}
    _write(sources["boundary"], [_feature(polygon, {"name": "test"})])
    _write(sources["roads"], [_feature(line, {"edge_id": "E1"})])
    _write(
        sources["demands"],
        [
            _feature(point, {"demand_id": "D1", "network_status": "connected"}),
            _feature(None, {"demand_id": "D2", "network_status": "unresolved"}),
        ],
    )
    _write(sources["buildings"], [_feature(polygon, {"building_id": "B1"})])
    _write(sources["constraints"], [_feature(polygon, {"constraint_id": "C1", "severity": "hard"})])
    _write(sources["recommended"], [_feature(line, {"candidate_id": "CR1", "least_cost_value": 1.0})])
    _write(sources["segments"], [_feature(line, {"segment_id": "S1", "construction_action": "new"})])
    _write(sources["final"], [_feature(line, {"plan_role": "recommended", "construction_action": "new"})])
    dem, slope = tmp_path / "dem.tif", tmp_path / "slope.tif"
    Image.fromarray(np.array([[100.0]], dtype=np.float32), mode="F").save(dem)
    Image.fromarray(np.array([[5.0]], dtype=np.float32), mode="F").save(slope)

    result = build_qgis_demo_package(
        output_dir=tmp_path / "map",
        boundary_path=sources["boundary"],
        road_edges_path=sources["roads"],
        demand_points_path=sources["demands"],
        building_footprints_path=sources["buildings"],
        constraints_path=sources["constraints"],
        recommended_routes_path=sources["recommended"],
        recommended_segments_path=sources["segments"],
        final_plan_path=sources["final"],
        dem_path=dem,
        slope_path=slope,
    )

    assert result["status"] == "ready"
    assert result["layers"]["service_points"]["map_feature_count"] == 1
    assert result["layers"]["recommended_routes"]["default_visible"] is False
    assert result["layers"]["recommended_action_segments"]["default_visible"] is True
    for path in (tmp_path / "map").glob("*.geojson"):
        json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
        frame = gpd.read_file(path)
        assert str(frame.crs) == "EPSG:4326"
        assert not frame.geometry.isna().any()
        assert frame.geometry.is_valid.all()
