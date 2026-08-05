"""Generate isolated, deterministic proxy locations for pipeline demonstrations.

Proxy locations are derived only from current residential land, current
facilities, and the village boundary.  They are never represented as verified
real-world place-name locations and must not be used for planning conclusions.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import geopandas as gpd
import networkx as nx
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import LineString, Point, mapping
from shapely.ops import transform as transform_geometry, unary_union


DATA_MODE = "demo_proxy"

# This trace is deliberately isolated to the Jintian *demonstration* scenario.
# It was digitised from the satellite-road corridor reviewed in the QGIS demo
# (2026-07-29).  The supplied current-road vector stops at its southern end,
# which made Stage 4 propose rebuilding a visible existing access road.  It is
# not survey-grade data and must never be injected into the production bundle.
DEMO_IMAGERY_REVIEWED_CURRENT_ROADS: Tuple[Dict[str, Any], ...] = (
    {
        "road_id": "DEMO-IMG-ROAD-001",
        "geometry": LineString(
            [
                (116.06241220646139, 24.828837840241853),
                (116.06232855438506, 24.82912530086573),
                (116.06218831662993, 24.829489075694937),
                (116.06193327380343, 24.829774826606112),
                (116.06176270038677, 24.829888442918616),
                (116.06154948318246, 24.83005886700202),
            ]
        ),
        "properties": {
            "road_status": "current_imagery_reviewed_demo_only",
            "geometry_source": "satellite_imagery_manual_trace",
            "source_evidence": "QGIS demo imagery review 2026-07-29",
            "requires_human_confirmation": True,
            "is_demo_proxy": True,
        },
    },
)


def _read(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_demo_imagery_reviewed_road_baseline(
    *,
    current_road_path: Path,
    output_path: Path,
) -> Dict[str, Any]:
    """Create a non-destructive, traceable current-road baseline for the demo.

    The original road bundle is read-only.  A separately written derived layer
    appends only the documented imagery-reviewed access traces above, so that
    a visible existing road is not falsely reported as ``new`` in a demo map.
    Production Stage 1 must continue to use its surveyed/current-road input.
    """

    source = gpd.read_file(current_road_path)
    if source.crs is None:
        raise ValueError(f"Demo road baseline source has no CRS: {current_road_path}")
    # Normalise these audit fields on the *derived* frame.  Without this,
    # mixed null/bool columns are serialised by Fiona as strings and QGIS/users
    # cannot reliably filter the traces that still need field confirmation.
    audit_defaults = {
        "road_id": None,
        "road_status": "current_bundle",
        "geometry_source": "current_road_bundle",
        "source_evidence": str(current_road_path),
        "requires_human_confirmation": False,
        "is_demo_proxy": False,
    }
    for field, default in audit_defaults.items():
        if field not in source.columns:
            source[field] = default
        else:
            source[field] = source[field].fillna(default)
    source["requires_human_confirmation"] = source["requires_human_confirmation"].astype(bool)
    source["is_demo_proxy"] = source["is_demo_proxy"].astype(bool)
    source_records = source.to_dict("records")
    additions: List[Dict[str, Any]] = []
    for item in DEMO_IMAGERY_REVIEWED_CURRENT_ROADS:
        additions.append(
            {
                **item["properties"],
                "road_id": item["road_id"],
                "geometry": item["geometry"],
            }
        )
    baseline = gpd.GeoDataFrame(
        [*source_records, *additions],
        geometry="geometry",
        crs=source.crs,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    baseline.to_file(output_path, driver="GeoJSON")
    manifest_path = output_path.with_name("imagery_reviewed_road_baseline_manifest.json")
    _write(
        manifest_path,
        {
            "data_mode": DATA_MODE,
            "status": "demo_only",
            "original_bundle_modified": False,
            "source_path": str(current_road_path),
            "derived_baseline_path": str(output_path),
            "source_feature_count": len(source),
            "imagery_reviewed_trace_count": len(additions),
            "output_feature_count": len(baseline),
            "trace_ids": [item["road_id"] for item in DEMO_IMAGERY_REVIEWED_CURRENT_ROADS],
            "warning": (
                "The appended traces are satellite-imagery review aids for the "
                "demo only. Field survey or authoritative road data is required "
                "before production use."
            ),
        },
    )
    return {
        "path": output_path,
        "manifest_path": manifest_path,
        "source_feature_count": len(source),
        "imagery_reviewed_trace_count": len(additions),
        "output_feature_count": len(baseline),
    }


def _transform(geometry: Any, transformer: Transformer | None) -> Any:
    return geometry if transformer is None else transform_geometry(transformer.transform, geometry)


def _normalise(value: Any) -> str:
    return "".join(character for character in str(value or "").strip().lower() if character not in " -_、，,（）()")


def _stable_number(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16)


def _residential_anchors(
    landuse_path: Path,
    boundary_path: Path,
    count: int,
    metric_crs: str,
    display_crs: str,
    cluster_distance_m: float,
) -> List[Dict[str, Any]]:
    landuse = gpd.read_file(landuse_path).to_crs(metric_crs)
    boundary = gpd.read_file(boundary_path).to_crs(metric_crs)
    if "DLMC" not in landuse.columns:
        raise ValueError("demo proxy generation requires the current landuse DLMC field")
    residential = landuse.loc[landuse["DLMC"].astype(str).str.contains("宅基地", regex=False, na=False)].copy()
    residential = residential[residential.geometry.notna() & ~residential.geometry.is_empty]
    residential["geometry"] = residential.geometry.map(
        lambda geometry: make_valid(geometry) if not geometry.is_valid else geometry
    )
    if len(residential) < count:
        raise ValueError(f"not enough residential parcels for {count} demo anchors")
    points = list(residential.geometry.representative_point())
    graph = nx.Graph()
    graph.add_nodes_from(range(len(points)))
    for left in range(len(points)):
        for right in range(left + 1, len(points)):
            if points[left].distance(points[right]) <= cluster_distance_m:
                graph.add_edge(left, right)
    clusters: List[Dict[str, Any]] = []
    for members in nx.connected_components(graph):
        geometries = [residential.iloc[index].geometry for index in sorted(members)]
        combined = unary_union(geometries)
        clusters.append(
            {
                "point": combined.representative_point(),
                "residential_area_m2": float(sum(geometry.area for geometry in geometries)),
                "parcel_count": len(geometries),
            }
        )
    clusters.sort(key=lambda item: (-item["residential_area_m2"], item["point"].x, item["point"].y))
    if len(clusters) < count:
        selected_points = [item["point"] for item in clusters]
        extras = sorted(
            (
                {"point": row.geometry.representative_point(), "residential_area_m2": float(row.geometry.area), "parcel_count": 1}
                for _, row in residential.iterrows()
                if all(row.geometry.representative_point().distance(point) > cluster_distance_m / 2 for point in selected_points)
            ),
            key=lambda item: (-item["residential_area_m2"], item["point"].x, item["point"].y),
        )
        clusters.extend(extras[: count - len(clusters)])
    village = unary_union(list(boundary.geometry))
    to_display = None if metric_crs.upper() == display_crs.upper() else Transformer.from_crs(metric_crs, display_crs, always_xy=True)
    output = []
    for index, item in enumerate(clusters[:count], 1):
        point = item["point"]
        if not village.covers(point):
            point = village.representative_point()
        output.append(
            {
                "anchor_id": f"PX{index:03d}",
                "metric_point": point,
                "display_geometry": mapping(_transform(point, to_display)),
                "residential_area_m2": item["residential_area_m2"],
                "parcel_count": item["parcel_count"],
                "population_proxy": max(20, min(1000, round(item["residential_area_m2"] / 50.0))),
            }
        )
    return output


def _offset_point(base: Point, object_id: str, boundary: Any) -> Point:
    seed = _stable_number(object_id)
    angle = math.radians(seed % 360)
    radius = 30.0 + float((seed // 360) % 71)
    candidate = Point(base.x + math.cos(angle) * radius, base.y + math.sin(angle) * radius)
    return candidate if boundary.covers(candidate) else base


def generate_demo_proxy_inputs(
    *,
    stage2_dir: Path,
    stage2_5_tasks_path: Path,
    landuse_path: Path,
    boundary_path: Path,
    output_dir: Path,
    metric_crs: str = "EPSG:4527",
    display_crs: str = "EPSG:4326",
    cluster_distance_m: float = 200.0,
    point_sources: Sequence[Path] = (),
) -> Dict[str, Any]:
    """Create Stage-3-compatible proxy inputs in a clearly isolated directory."""

    demands = _read(stage2_dir / "demand_points.geojson")
    projects = _read(stage2_dir / "road_projects.json")
    constraints = _read(stage2_dir / "road_constraints.json")
    tasks = _read(stage2_5_tasks_path)
    place_tasks = [task for task in tasks.get("tasks", []) if task.get("task_type") == "place"]
    place_tasks.sort(key=lambda item: item["task_id"])
    anchors = _residential_anchors(
        landuse_path,
        boundary_path,
        len(place_tasks),
        metric_crs,
        display_crs,
        cluster_distance_m,
    )
    anchor_by_place = {
        _normalise(task["place_name"]): anchor for task, anchor in zip(place_tasks, anchors)
    }
    boundary = unary_union(list(gpd.read_file(boundary_path).to_crs(metric_crs).geometry))
    to_display = None if metric_crs.upper() == display_crs.upper() else Transformer.from_crs(metric_crs, display_crs, always_xy=True)
    facility_proxy_points: List[Point] = []
    for source in point_sources:
        if not source.exists():
            continue
        frame = gpd.read_file(source).to_crs(metric_crs)
        facility_proxy_points.extend(
            geometry
            for geometry in frame.geometry
            if geometry is not None and not geometry.is_empty and geometry.geom_type == "Point" and boundary.covers(geometry)
        )
    facility_proxy_points.sort(key=lambda point: (point.x, point.y))

    demand_payload = copy.deepcopy(demands)
    demand_payload["data_mode"] = DATA_MODE
    demand_payload["demo_warning"] = "Synthetic proxy locations; not verified real-world place-name coordinates."
    demand_geometry_by_id: Dict[str, Dict[str, Any]] = {}
    demo_healthcare_assigned = False
    ordered_demand_features = sorted(
        demand_payload.get("features", []),
        key=lambda feature: str((feature.get("properties") or {}).get("demand_id") or ""),
    )
    for feature in ordered_demand_features:
        props = feature.get("properties") or {}
        if props.get("demand_type") == "public_service" and not demo_healthcare_assigned:
            props["demo_original_demand_type"] = "public_service"
            props["demand_type"] = "healthcare"
            props["demo_scenario_adjustment"] = (
                "one public-service demand is treated as a demo clinic so healthcare accessibility can be tested"
            )
            demo_healthcare_assigned = True
        anchor = anchor_by_place.get(_normalise(props.get("place_name")))
        if anchor is None:
            # A demo must remain fully spatially executable.  Real planning
            # leaves this unresolved, while the isolated proxy mode assigns a
            # deterministic residential anchor and labels the substitution.
            anchor = anchors[_stable_number(str(props.get("demand_id") or "")) % len(anchors)]
            props["demo_scenario_adjustment"] = (
                "unmatched text place assigned to a deterministic residential proxy anchor"
            )
        point = anchor["metric_point"]
        proxy_method = "current_residential_land_cluster"
        if props.get("demand_type") != "settlement":
            if props.get("demo_scenario_adjustment"):
                proxy_method = "demo_clinic_at_residential_service_center"
            elif facility_proxy_points:
                point = facility_proxy_points[_stable_number(str(props.get("demand_id") or "")) % len(facility_proxy_points)]
                proxy_method = "existing_annotation_or_public_poi_proxy"
            else:
                point = _offset_point(point, str(props.get("demand_id") or ""), boundary)
        feature["geometry"] = mapping(_transform(point, to_display))
        props.update(
            {
                "location_status": "proxy_demo",
                "location_confidence": 0.0,
                "location_reason": (
                    "deterministic proxy selected from current facility annotations or public POIs"
                    if proxy_method == "existing_annotation_or_public_poi_proxy"
                    else (
                        "demo clinic placed at a residential service centre"
                        if proxy_method == "demo_clinic_at_residential_service_center"
                        else "deterministic proxy derived from current residential land"
                    )
                ),
                "requires_human_confirmation": True,
                "is_demo_proxy": True,
                "proxy_anchor_id": anchor["anchor_id"],
                "proxy_method": proxy_method,
            }
        )
        if props.get("demand_type") == "settlement":
            props["population_served"] = anchor["population_proxy"]
            props["population_is_proxy"] = True
        demand_geometry_by_id[str(props.get("demand_id") or "")] = feature["geometry"]

    project_payload = copy.deepcopy(projects)
    project_payload["data_mode"] = DATA_MODE
    project_payload["demo_warning"] = demand_payload["demo_warning"]
    anchor_items = list(anchors)
    for project in project_payload.get("projects", []):
        project_id = str(project.get("project_id") or "")
        endpoint_geometries: Dict[str, Dict[str, Any] | None] = {}
        for side in ("start", "end"):
            geometry = None
            demand_id = project.get(f"{side}_demand_id")
            if demand_id:
                geometry = demand_geometry_by_id.get(str(demand_id))
            if geometry is None:
                anchor = anchor_by_place.get(_normalise(project.get(f"{side}_place")))
                if anchor:
                    geometry = anchor["display_geometry"]
            endpoint_geometries[side] = geometry
        mentioned: List[Dict[str, Any]] = []
        for place, anchor in anchor_by_place.items():
            if any(place and place in _normalise(value) for value in project.get("service_places", [])):
                mentioned.append(anchor)
        mentioned = list({item["anchor_id"]: item for item in mentioned}.values())
        mentioned.sort(key=lambda item: item["anchor_id"])
        if endpoint_geometries["start"] is None and mentioned:
            endpoint_geometries["start"] = mentioned[0]["display_geometry"]
        if endpoint_geometries["end"] is None and len(mentioned) > 1:
            endpoint_geometries["end"] = mentioned[-1]["display_geometry"]
        for side in ("start", "end"):
            if endpoint_geometries[side] is None:
                index = _stable_number(f"{project_id}:{side}") % len(anchor_items)
                if side == "end" and endpoint_geometries["start"] == anchor_items[index]["display_geometry"]:
                    index = (index + 1) % len(anchor_items)
                endpoint_geometries[side] = anchor_items[index]["display_geometry"]
            project[f"{side}_geometry"] = endpoint_geometries[side]
            project[f"{side}_location_status"] = "proxy_demo"
        project.update(
            {
                "planning_status": "demo_proxy_ready",
                "requires_human_confirmation": True,
                "is_demo_proxy": True,
                "proxy_method": "current_residential_land_cluster",
            }
        )

    constraint_payload = copy.deepcopy(constraints)
    constraint_payload["data_mode"] = DATA_MODE
    for constraint in constraint_payload.get("constraints", []):
        if constraint.get("target_layer") == "geological_hazard_points" and constraint.get("buffer_m") is None:
            constraint["buffer_m"] = 100.0
            constraint["parameter_confirmation"] = {
                "status": "demo_proxy",
                "basis": "demonstration-only screening distance; not an approved technical parameter",
            }
        if constraint.get("target_layer") == "ancient_trees" and not constraint.get("geometry"):
            anchor = anchors[_stable_number(str(constraint.get("constraint_id") or "ancient_trees")) % len(anchors)]
            constraint["geometry"] = anchor["display_geometry"]
            constraint["geometry_crs"] = display_crs
            constraint["buffer_m"] = 30.0
            constraint["parameter_confirmation"] = {
                "status": "demo_proxy",
                "basis": "synthetic 30m ancient-tree protection buffer for software demonstration only",
            }

    confirmed_features = []
    for task, anchor in zip(place_tasks, anchors):
        confirmed_features.append(
            {
                "type": "Feature",
                "id": task["task_id"],
                "geometry": anchor["display_geometry"],
                "properties": {
                    "task_id": task["task_id"],
                    "name": task["place_name"],
                    "confirmation_status": "demo_proxy_not_confirmed",
                    "source_method": "current_residential_land_cluster",
                    "is_demo_proxy": True,
                    "residential_area_m2": round(anchor["residential_area_m2"], 3),
                    "parcel_count": anchor["parcel_count"],
                },
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write(output_dir / "demand_points.geojson", demand_payload)
    _write(output_dir / "road_projects.json", project_payload)
    _write(output_dir / "road_constraints.json", constraint_payload)
    _write(
        output_dir / "confirmed_locations.geojson",
        {
            "type": "FeatureCollection",
            "name": "demo_proxy_locations",
            "data_mode": DATA_MODE,
            "crs": {"type": "name", "properties": {"name": display_crs}},
            "features": confirmed_features,
        },
    )
    report = {
        "data_mode": DATA_MODE,
        "status": "demo_only",
        "proxy_place_count": len(anchors),
        "located_demand_count": sum(feature.get("geometry") is not None for feature in demand_payload.get("features", [])),
        "proxy_project_count": len(project_payload.get("projects", [])),
        "cluster_distance_m": cluster_distance_m,
        "facility_proxy_source_point_count": len(facility_proxy_points),
        "demo_healthcare_facility_count": int(demo_healthcare_assigned),
        "source_layers": [str(landuse_path), str(boundary_path), *[str(path) for path in point_sources]],
        "planned_road_read": False,
        "warning": "These coordinates are synthetic proxies for software demonstration and must never be cited as verified Jintian Village locations.",
    }
    _write(output_dir / "demo_proxy_report.json", report)
    _write(
        output_dir / "DEMO_ONLY_DO_NOT_USE_FOR_PLANNING.json",
        {"data_mode": DATA_MODE, "allowed_use": "pipeline demonstration and software testing only", "prohibited_use": "planning conclusion, construction, approval, or evaluation against real place names"},
    )
    return report


__all__ = [
    "build_demo_imagery_reviewed_road_baseline",
    "generate_demo_proxy_inputs",
]
