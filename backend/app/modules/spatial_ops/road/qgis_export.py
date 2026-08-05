"""Create a small, strict, QGIS-facing map package from road-demo outputs."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

import geopandas as gpd
from shapely import make_valid


MAP_CRS = "EPSG:4326"


def _safe_property(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _safe_property(value.item())
    if isinstance(value, (list, tuple, dict, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _strict_json(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _geometry_family(geometry_type: str) -> str:
    if "Point" in geometry_type:
        return "point"
    if "LineString" in geometry_type:
        return "line"
    if "Polygon" in geometry_type:
        return "polygon"
    return "other"


def _clean_layer(
    source: Path,
    target: Path,
    *,
    family: str,
    fields: Sequence[str],
) -> Dict[str, Any]:
    frame = gpd.read_file(source)
    if frame.crs is None:
        raise ValueError(f"Map source has no CRS: {source}")
    source_count = len(frame)
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    if len(frame):
        frame["geometry"] = frame.geometry.map(
            lambda geometry: make_valid(geometry) if not geometry.is_valid else geometry
        )
        frame = frame.loc[
            frame.geometry.map(lambda geometry: _geometry_family(geometry.geom_type) == family)
        ].copy()
    frame = frame.to_crs(MAP_CRS)
    selected = [field for field in fields if field in frame.columns]
    frame = frame[selected + ["geometry"]].copy()
    for column in selected:
        frame[column] = frame[column].map(_safe_property)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(target, driver="GeoJSON")
    _strict_json(target)
    verified = gpd.read_file(target)
    invalid_count = int((~verified.geometry.is_valid).sum()) if len(verified) else 0
    if invalid_count:
        raise ValueError(f"QGIS layer contains invalid geometry: {target}")
    return {
        "path": str(target),
        "source_path": str(source),
        "source_feature_count": source_count,
        "map_feature_count": len(verified),
        "dropped_empty_or_wrong_geometry_count": source_count - len(verified),
        "geometry_family": family,
        "crs": str(verified.crs),
        "invalid_geometry_count": invalid_count,
    }


def _find_gdal_executable(name: str) -> Optional[Path]:
    discovered = shutil.which(name)
    if discovered:
        return Path(discovered)
    candidates = (
        Path("D:/QGIS/bin") / name,
        Path("C:/OSGeo4W/bin") / name,
        Path("D:/OSGeo4W/bin") / name,
    )
    return next((candidate for candidate in candidates if candidate.exists()), None)


def _copy_raster(source: Path, target: Path, role: str, crs: str) -> Dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    gdal_translate = _find_gdal_executable("gdal_translate.exe")
    writer = "source_copy"
    if gdal_translate is not None:
        subprocess.run(
            [
                str(gdal_translate),
                "-of",
                "GTiff",
                "-ot",
                "Float32",
                "-a_srs",
                crs,
                "-a_nodata",
                "-9999",
                "-co",
                "COMPRESS=DEFLATE",
                "-co",
                "TILED=YES",
                "-co",
                "BIGTIFF=NO",
                str(source),
                str(target),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        writer = "QGIS_GDAL_GTiff"
    else:
        shutil.copy2(source, target)
    return {
        "path": str(target),
        "source_path": str(source),
        "map_role": role,
        "crs": crs,
        "raster_writer": writer,
    }


def build_qgis_demo_package(
    *,
    output_dir: Path,
    boundary_path: Path,
    road_edges_path: Path,
    demand_points_path: Path,
    building_footprints_path: Path,
    constraints_path: Path,
    recommended_routes_path: Path,
    recommended_segments_path: Path,
    final_plan_path: Path,
    dem_path: Path,
    slope_path: Path,
) -> Dict[str, Any]:
    """Write only true map layers, separated by geometry type and role."""

    output_dir.mkdir(parents=True, exist_ok=True)
    layers: Dict[str, Dict[str, Any]] = {}
    specifications = (
        (
            "village_boundary",
            boundary_path,
            output_dir / "01_village_boundary.geojson",
            "polygon",
            ("name", "村名", "XZQMC", "DLMC"),
            "村域边界",
            "existing_project_data",
            True,
        ),
        (
            "current_roads",
            road_edges_path,
            output_dir / "02_current_roads.geojson",
            "line",
            ("edge_id", "from_node", "to_node", "length_m", "component_id"),
            "现状道路",
            "existing_project_data",
            True,
        ),
        (
            "service_points",
            demand_points_path,
            output_dir / "03_demo_service_points.geojson",
            "point",
            (
                "demand_id",
                "name",
                "demand_type",
                "priority",
                "network_status",
                "distance_to_road_m",
                "population_served",
                "location_status",
                "data_mode",
            ),
            "道路需要服务的居民点、设施点和项目点",
            "demo_proxy",
            True,
        ),
        (
            "demo_buildings",
            building_footprints_path,
            output_dir / "04_demo_buildings.geojson",
            "polygon",
            (
                "building_id",
                "data_mode",
                "is_real_building",
                "source_landuse_code",
                "source_landuse_name",
            ),
            "用于测试绕避能力的合成建筑障碍",
            "demo_proxy",
            True,
        ),
        (
            "planning_constraints",
            constraints_path,
            output_dir / "05_planning_constraints.geojson",
            "polygon",
            (
                "constraint_id",
                "constraint_type",
                "target_layer",
                "severity",
                "buffer_m",
                "description",
            ),
            "硬约束与地灾等软约束",
            "mixed_project_constraints",
            False,
        ),
        (
            "recommended_routes",
            recommended_routes_path,
            output_dir / "06_recommended_routes.geojson",
            "line",
            (
                "candidate_id",
                "request_id",
                "source_type",
                "strategy",
                "screening_status",
                "total_score",
                "rank_within_request",
                "access_point_count",
                "new_length_m",
                "reuse_existing_length_m",
                "widen_length_m",
                "harden_length_m",
                "net_new_footprint_m2",
                "maximum_grade_percent",
                "minimum_curve_radius_m",
                "hard_violation_count",
            ),
            "阶段5最终推荐的完整路线",
            "calculated_demo_result",
            False,
        ),
        (
            "recommended_action_segments",
            recommended_segments_path,
            output_dir / "07_recommended_action_segments.geojson",
            "line",
            (
                "segment_id",
                "candidate_id",
                "request_id",
                "construction_action",
                "length_m",
                "net_new_footprint_m2",
                "planned_width_m",
                "access_point_count",
            ),
            "按新建、复用、拓宽、硬化拆分的最终路线",
            "calculated_demo_result",
            True,
        ),
        (
            "final_plan",
            final_plan_path,
            output_dir / "08_final_plan_with_existing_roads.geojson",
            "line",
            (
                "plan_role",
                "construction_action",
                "edge_id",
                "segment_id",
                "candidate_id",
                "request_id",
                "length_m",
                "net_new_footprint_m2",
            ),
            "现状道路与最终推荐方案合并预览",
            "calculated_demo_result",
            True,
        ),
    )
    for key, source, target, family, fields, role, data_role, default_visible in specifications:
        result = _clean_layer(source, target, family=family, fields=fields)
        result.update(
            {
                "map_role": role,
                "data_role": data_role,
                "default_visible": default_visible,
            }
        )
        layers[key] = result

    layers["dem"] = _copy_raster(
        dem_path,
        output_dir / "09_dem_elevation_wgs84.tif",
        "真实公开SRTM高程，用于Demo地形计算",
        MAP_CRS,
    )
    layers["dem"].update({"data_role": "real_public_terrain", "default_visible": False})
    layers["slope"] = _copy_raster(
        slope_path,
        output_dir / "10_slope_degrees_wgs84.tif",
        "由SRTM高程计算的坡度",
        MAP_CRS,
    )
    layers["slope"].update({"data_role": "derived_public_terrain", "default_visible": False})

    manifest = {
        "status": "ready",
        "purpose": "Only files listed under layers are intended to be loaded as QGIS map layers.",
        "satellite_basemap_crs": MAP_CRS,
        "vector_layer_crs": MAP_CRS,
        "raster_layer_crs": MAP_CRS,
        "qgis_on_the_fly_reprojection_required_for_rasters": False,
        "not_map_files": [
            "*.json reports",
            "*.csv tables",
            "*.npz routing grids",
            "candidate_evaluations.json",
            "candidate_score_details.json",
        ],
        "layers": layers,
    }
    manifest_path = output_dir / "map_layers_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    readme = output_dir / "00_QGIS_MAP_FILES.md"
    readme.write_text(
        """# QGIS地图文件

这个文件夹只放应当加载到QGIS地图画布中的文件。

推荐打开：`01`、`03`、`04`、`07`、`08`。其中 `08` 是最直观的最终道路图。

- `01_village_boundary.geojson`：村域边界；
- `02_current_roads.geojson`：现状道路；
- `03_demo_service_points.geojson`：Demo居民点、设施点和项目点；
- `04_demo_buildings.geojson`：合成建筑障碍，不是真实房屋；
- `05_planning_constraints.geojson`：硬约束与地灾等软约束，默认可关闭避免遮挡卫星图；
- `06_recommended_routes.geojson`：每项需求的完整推荐路线；
- `07_recommended_action_segments.geojson`：按建设动作拆分的推荐路线；
- `08_final_plan_with_existing_roads.geojson`：现状道路与推荐方案合并图；
- `09_dem_elevation_wgs84.tif`：高程；
- `10_slope_degrees_wgs84.tif`：坡度。

GeoJSON和两个TIF均为EPSG:4326，可直接叠加卫星底图。JSON报告、CSV表和NPZ计算网格不是地图图层。
""",
        encoding="utf-8",
    )
    manifest["manifest_path"] = str(manifest_path)
    manifest["readme_path"] = str(readme)
    return manifest
