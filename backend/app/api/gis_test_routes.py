"""
GIS Dev Test Routes - 开发环境专用的 GIS 端到端测试 API

仅用于开发和测试，生产环境应禁用。
每个端点包装现有 GIS 服务为 REST API，供前端 test-gis 页面调用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev/gis", tags=["GIS Dev"])


# ============================================
# GeoJSON color injection (per-feature DLBM/zone_type → color)
# ============================================

from app.services.modules.gis.layout.zone_schema import (
    get_zone_color, get_zone_type_for_dlbm, ZONE_TYPE_COLORS, DEFAULT_ZONE_COLOR,
    PLANNING_ZONE_COLORS,
)

# Sensitivity level color mapping
SENSITIVITY_COLORS = {
    "high": {"fill": "#FF0000", "stroke": "#CC0000"},
    "medium": {"fill": "#FFFF00", "stroke": "#CCCC00"},
    "low": {"fill": "#00FF00", "stroke": "#00CC00"},
    "buffer": {"fill": "#FFA500", "stroke": "#CC8400"},
    "高敏感区": {"fill": "#FF0000", "stroke": "#CC0000"},
    "中敏感区": {"fill": "#FFFF00", "stroke": "#CCCC00"},
    "低敏感区": {"fill": "#00FF00", "stroke": "#00CC00"},
    "缓冲区": {"fill": "#FFA500", "stroke": "#CC8400"},
}

# Facility type color mapping (per facility_type, not status)
FACILITY_TYPE_COLORS = {
    "村委会": {"fill": "#8B4513", "stroke": "#654321"},
    "学校": {"fill": "#4169E1", "stroke": "#2850A0"},
    "卫生站": {"fill": "#DC143C", "stroke": "#B01030"},
    "文化站": {"fill": "#9932CC", "stroke": "#7A28A0"},
    "市场": {"fill": "#FF8C00", "stroke": "#CC7000"},
    "养老服务": {"fill": "#2F4F4F", "stroke": "#1F3333"},
    "产业服务中心": {"fill": "#B8860B", "stroke": "#8B6508"},
    "停车场": {"fill": "#696969", "stroke": "#505050"},
    "地质灾害点": {"fill": "#FF0000", "stroke": "#CC0000"},
}

# Infrastructure color by road/water type
INFRA_COLORS = {
    "县道": {"fill": "#555555", "stroke": "#333333"},
    "乡道": {"fill": "#808080", "stroke": "#606060"},
    "村道": {"fill": "#A0A0A0", "stroke": "#808080"},
    "道路": {"fill": "#666666", "stroke": "#444444"},
    "河流": {"fill": "#00BFFF", "stroke": "#0099CC"},
    "水系": {"fill": "#00BFFF", "stroke": "#0099CC"},
}


def inject_feature_colors(geojson: Dict[str, Any], layer_type: str) -> Dict[str, Any]:
    """Inject per-feature color/stroke properties based on DLBM/zone_type/sensitivity_level.

    This ensures each feature has a color matching national standards (GB/T 21010-2017)
    so the frontend can render them with data-driven styling.
    """
    if not geojson or not geojson.get("features"):
        return geojson

    features = []
    for feat in geojson["features"]:
        feat = dict(feat)
        props = dict(feat.get("properties", {}))

        # Skip if already has color
        if props.get("color"):
            feat["properties"] = props
            features.append(feat)
            continue

        if layer_type == "function_zone":
            dlbm = str(props.get("DLBM", "")).strip()
            zone_type = str(props.get("zone_type", "")).strip()
            # Try zone_type first, then derive from DLBM
            if not zone_type and dlbm:
                zone_type = get_zone_type_for_dlbm(dlbm)
            if not zone_type:
                zone_type = "农业用地"  # default for landuse
            color_info = get_zone_color(zone_type)
            props["zone_type"] = zone_type
            props["color"] = color_info["fill"]
            props["stroke"] = color_info["stroke"]

        elif layer_type == "planning_zone":
            zone_type = str(props.get("zone_type", "") or props.get("assigned_zone", "")).strip()
            if not zone_type:
                zone_type = "一般农业区"
            pcolor = PLANNING_ZONE_COLORS.get(zone_type)
            if pcolor:
                props["color"] = pcolor
                props["stroke"] = pcolor
            else:
                props["color"] = DEFAULT_ZONE_COLOR["fill"]
                props["stroke"] = DEFAULT_ZONE_COLOR["stroke"]

        elif layer_type == "sensitivity_zone":
            level = str(props.get("sensitivity_level", "") or props.get("protection_type", "")).strip()
            level_lower = level.lower() if level else ""
            color_info = SENSITIVITY_COLORS.get(level) or SENSITIVITY_COLORS.get(level_lower)
            if not color_info:
                color_info = SENSITIVITY_COLORS.get("中敏感区", DEFAULT_ZONE_COLOR)
            props["color"] = color_info["fill"]
            props["stroke"] = color_info["stroke"]

        elif layer_type == "facility_point":
            fac_type = str(props.get("facility_type", "")).strip()
            color_info = FACILITY_TYPE_COLORS.get(fac_type)
            if not color_info:
                # Fallback by status
                status = str(props.get("status", "规划新建")).strip()
                from app.services.modules.gis.layout.zone_schema import FACILITY_STATUS_COLORS
                color_info = FACILITY_STATUS_COLORS.get(status, {"fill": "blue", "stroke": "#00008B"})
            props["color"] = color_info["fill"]
            props["stroke"] = color_info["stroke"]

        elif layer_type == "infrastructure":
            infra_type = str(props.get("infrastructure_type", "")).strip()
            rn = str(props.get("RN", "")).strip()
            name = str(props.get("name", "")).strip()
            road_key = "道路"
            if infra_type in ("河流", "水系"):
                road_key = "河流"
            elif rn.startswith("X") or "县道" in name:
                road_key = "县道"
            elif rn.startswith("Y") or "乡道" in name or "村道" in name:
                road_key = "乡道"
            color_info = INFRA_COLORS.get(road_key, INFRA_COLORS["道路"])
            props["color"] = color_info["stroke"]
            props["stroke"] = color_info["stroke"]

        feat["properties"] = props
        features.append(feat)

    return {"type": "FeatureCollection", "features": features}

# ============================================
# Pydantic Request Models
# ============================================

class LocationRequest(BaseModel):
    location: str = "金田村委会"
    buffer_km: float = 5.0
    max_features: int = 100

class CenterRequest(BaseModel):
    location: str = "金田村委会"
    buffer_km: float = 5.0

class BBoxRequest(BaseModel):
    location: str = "金田村委会"
    buffer_km: float = 5.0

class IsochroneRequest(BaseModel):
    center: List[float] = Field(default=[116.044146, 24.818629])
    time_minutes: List[int] = Field(default=[5, 10, 15])
    travel_mode: str = "walk"

class AccessibilityRequest(BaseModel):
    analysis_type: str = "service_coverage"
    origin: Optional[List[float]] = None
    center: Optional[List[float]] = None

class POISearchRequest(BaseModel):
    keyword: str = "学校"
    center: List[float] = Field(default=[116.044146, 24.818629])
    radius: int = 2000
    page_size: int = 20

class CoverageRequest(BaseModel):
    location: str = "金田村"
    buffer_km: float = 5.0
    max_features: int = 100

class FacilityValidationRequest(BaseModel):
    facility_type: str = "公共服务设施"
    location: List[float] = Field(default=[116.044146, 24.818629])

class EcologicalRequest(BaseModel):
    use_jintian_data: bool = True

class SpatialLayoutRequest(BaseModel):
    village_name: str = "金田村委会"
    intent: Optional[Dict[str, Any]] = None

class LanduseChangeRequest(BaseModel):
    location: str = "金田村"
    buffer_km: float = 5.0
    change_threshold: float = 0.1

class ConstraintValidatorRequest(BaseModel):
    location: str = "金田村"
    strict_mode: bool = False

class HazardBufferRequest(BaseModel):
    location: str = "金田村"
    buffer_meters: float = 200.0

class LayoutValidateRequest(BaseModel):
    """Request model for layout validation endpoint."""
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)
    constraints: Optional[List[Dict[str, Any]]] = None
    use_jintian_data: bool = False

# ============================================
# Helpers
# ============================================

def _jintian_data_dir() -> Path:
    """Return path to data/gis/jintian/."""
    from app.core.settings import JINTIAN_GIS_DIR
    return JINTIAN_GIS_DIR


def _load_jintian_geojson(filename: str) -> Optional[Dict[str, Any]]:
    """Load a GeoJSON file from jintian_boundary directory."""
    data_dir = _jintian_data_dir()
    filepath = data_dir / filename
    if not filepath.exists():
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load {filename}: {e}")
        return None


# ============================================
# Status Endpoint
# ============================================

@router.get("/status", summary="Check GIS service availability")
async def gis_status():
    """Check which GIS services and dependencies are available."""
    from app.core.settings import TIANDITU_API_KEY, AMAP_API_KEY

    services = {
        "tianditu_api_key": bool(TIANDITU_API_KEY),
        "amap_api_key": bool(AMAP_API_KEY),
    }

    # Check optional dependencies
    try:
        import osmnx  # noqa: F401
        services["osmnx"] = True
    except ImportError:
        services["osmnx"] = False

    try:
        import geopandas  # noqa: F401
        services["geopandas"] = True
    except ImportError:
        services["geopandas"] = False

    try:
        import rdflib  # noqa: F401
        services["rdflib"] = True
    except ImportError:
        services["rdflib"] = False

    # Check jintian data availability
    jintian_dir = _jintian_data_dir()
    services["jintian_data"] = jintian_dir.is_dir()

    return {
        "status": "ok",
        "services": services,
        "jintian_files": len(list(jintian_dir.glob("*.geojson"))) if jintian_dir.is_dir() else 0,
    }


# ============================================
# Data Fetch Endpoints
# ============================================

@router.post("/data-fetch", summary="Fetch all GIS data for a location")
async def data_fetch(request: LocationRequest):
    """Fetch all GIS data (water, road, residential, boundary) for a location."""
    t0 = time.time()
    try:
        from app.services.modules.gis.fetcher import get_fetcher
        fetcher = get_fetcher()
        result = await asyncio.to_thread(
            fetcher.fetch_all_gis_data,
            request.location, request.buffer_km, request.max_features
        )
        return {"success": True, "data": result, "timing_ms": round((time.time() - t0) * 1000)}
    except Exception as e:
        logger.error(f"[GIS Test] data-fetch failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/center", summary="Locate village center")
async def locate_center(request: CenterRequest):
    """Locate village center using 4-tier fallback strategy."""
    t0 = time.time()
    try:
        from app.services.modules.gis.fetcher import get_fetcher
        fetcher = get_fetcher()
        center, metadata = await asyncio.to_thread(
            fetcher.get_village_center, request.location, request.buffer_km
        )
        # Fallback to jintian boundary center if geocoding fails
        if center is None:
            boundary = _load_jintian_geojson("current/boundary.geojson")
            if boundary:
                try:
                    from shapely.geometry import shape
                    geom = shape(boundary["features"][0]["geometry"])
                    c = geom.centroid
                    center = (c.x, c.y)
                    metadata["fallback"] = "jintian_boundary_centroid"
                except Exception:
                    center = (116.044146, 24.818629)
                    metadata["fallback"] = "hardcoded_default"
        return {
            "success": center is not None,
            "center": list(center) if center else None,
            "metadata": metadata,
            "timing_ms": round((time.time() - t0) * 1000),
        }
    except Exception as e:
        logger.error(f"[GIS Test] center failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/bbox", summary="Get boundary bbox")
async def get_bbox(request: BBoxRequest):
    """Get boundary and expanded bbox for a location."""
    t0 = time.time()
    try:
        from app.services.modules.gis.fetcher import get_fetcher
        fetcher = get_fetcher()
        result = await asyncio.to_thread(
            fetcher.get_boundary_bbox, request.location, request.buffer_km
        )
        return {"success": True, "data": result, "timing_ms": round((time.time() - t0) * 1000)}
    except Exception as e:
        logger.error(f"[GIS Test] bbox failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ============================================
# Analysis Endpoints
# ============================================

@router.post("/isochrone", summary="Generate isochrones")
async def test_isochrone(request: IsochroneRequest):
    """Generate time-based accessibility isochrones."""
    t0 = time.time()
    try:
        import math
        center = request.center
        travel_mode = request.travel_mode
        speeds = {"walk": 5.0, "drive": 40.0, "bike": 15.0}
        speed_kmh = speeds.get(travel_mode, 5.0)

        isochrones = []
        for minutes in request.time_minutes:
            radius_km = speed_kmh * minutes / 60.0
            radius_deg = radius_km / 111.32
            # Generate circle polygon
            n_points = 64
            coords = []
            for i in range(n_points + 1):
                angle = 2 * math.pi * i / n_points
                lat = center[1] + radius_deg * math.cos(angle)
                lon = center[0] + radius_deg * math.sin(angle) / math.cos(math.radians(center[1]))
                coords.append([lon, lat])
            isochrones.append({
                "time_minutes": minutes,
                "radius_km": round(radius_km, 2),
                "geojson": {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": {"time_minutes": minutes, "travel_mode": travel_mode, "radius_km": round(radius_km, 2)},
                },
            })

        # Build combined GeoJSON FeatureCollection
        features = [iso["geojson"] for iso in isochrones]

        # Inject per-isochrone colors (5min=green, 10min=yellow, 15min=orange)
        ISOCHRONE_COLORS = {5: "#00FF00", 10: "#FFFF00", 15: "#FFA500"}
        for feat in features:
            props = feat.setdefault("properties", {})
            mins = props.get("time_minutes", 10)
            props["color"] = ISOCHRONE_COLORS.get(mins, "#FFA500")
            props["stroke"] = props["color"]

        geojson = {"type": "FeatureCollection", "features": features}

        return {"success": True, "geojson": geojson, "isochrones": isochrones, "timing_ms": round((time.time() - t0) * 1000)}
    except Exception as e:
        logger.error(f"[GIS Test] isochrone failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/accessibility", summary="Analyze accessibility")
async def test_accessibility(request: AccessibilityRequest):
    """Run accessibility analysis (driving, walking, service coverage)."""
    t0 = time.time()
    try:
        from app.services.modules.gis.accessibility import run_accessibility_analysis
        origin = tuple(request.origin) if request.origin else None
        center = tuple(request.center) if request.center else (116.044146, 24.818629)
        result = await asyncio.to_thread(
            run_accessibility_analysis,
            request.analysis_type, origin, None, center
        )
        return {"success": True, **result, "timing_ms": round((time.time() - t0) * 1000)}
    except Exception as e:
        logger.error(f"[GIS Test] accessibility failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/poi-search", summary="Search nearby POI")
async def test_poi_search(request: POISearchRequest):
    """Search POI near a center point using Amap (primary) or Tianditu."""
    t0 = time.time()
    try:
        from app.services.modules.gis.providers.poi import POIProvider
        center_tuple = tuple(request.center)
        result = await asyncio.to_thread(
            POIProvider.search_poi_nearby,
            request.keyword, center_tuple, request.radius, request.page_size
        )
        # POIProvider.search_poi_nearby returns a dict, not an object
        return {
            "success": result.get("success", False),
            "pois": result.get("pois"),
            "geojson": result.get("geojson"),
            "total_count": result.get("total_count", 0),
            "source": result.get("source"),
            "error": result.get("error"),
            "timing_ms": round((time.time() - t0) * 1000),
        }
    except Exception as e:
        logger.error(f"[GIS Test] poi-search failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/coverage", summary="Calculate GIS coverage")
async def test_coverage(request: CoverageRequest):
    """Calculate GIS data coverage rate for a location."""
    t0 = time.time()
    try:
        from app.services.modules.gis.coverage import calculate_gis_coverage
        result = await asyncio.to_thread(
            calculate_gis_coverage, request.location, request.buffer_km
        )
        return {"success": True, **result, "timing_ms": round((time.time() - t0) * 1000)}
    except Exception as e:
        logger.error(f"[GIS Test] coverage failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ============================================
# Validation Endpoints
# ============================================

@router.post("/facility-validation", summary="Validate facility siting")
async def test_facility_validation(request: FacilityValidationRequest):
    """Validate facility location against planning standards."""
    t0 = time.time()
    try:
        from app.services.modules.gis.validators import validate_facility_location
        location_tuple = tuple(request.location)
        analysis_params = {
            "population_points": [],
            "existing_facilities": [],
            "land_use_data": _load_jintian_geojson("current/landuse.geojson"),
            "protection_zones": {
                "farmland_protection": _load_jintian_geojson("farmland_protection.geojson"),
                "ecological_redline": _load_jintian_geojson("ecological_protection.geojson"),
            },
            "hazard_zones": _load_jintian_geojson("geological_hazard_points.geojson"),
        }
        result = await asyncio.to_thread(
            validate_facility_location, request.facility_type, location_tuple, analysis_params
        )
        return {"success": True, **result, "timing_ms": round((time.time() - t0) * 1000)}
    except Exception as e:
        logger.error(f"[GIS Test] facility-validation failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/ecological", summary="Assess ecological sensitivity")
async def test_ecological(request: EcologicalRequest):
    """Assess ecological sensitivity using jintian data."""
    t0 = time.time()
    try:
        if request.use_jintian_data:
            study_area = _load_jintian_geojson("current/boundary.geojson")
            water = _load_jintian_geojson("wfs_hyda.geojson") or _load_jintian_geojson("current/landuse.geojson")
            if not study_area:
                return {"success": False, "error": "jintian boundary data not found", "timing_ms": round((time.time() - t0) * 1000)}

            # Try full assessment first
            try:
                from app.services.modules.gis.validators import assess_ecological_sensitivity, SPATIAL_AVAILABLE
                if not SPATIAL_AVAILABLE:
                    raise ImportError("spatial_analysis module not available")
                result = await asyncio.to_thread(assess_ecological_sensitivity, study_area, water)
                if not result.get("success", True):
                    raise RuntimeError(result.get("error", "unknown error"))
                return {"success": True, **result, "timing_ms": round((time.time() - t0) * 1000)}
            except (ImportError, ModuleNotFoundError, RuntimeError) as e:
                logger.warning(f"[GIS Test] ecological full assessment unavailable: {e}")

            # Fallback: simple area-based assessment from jintian data
            ecological = _load_jintian_geojson("ecological_protection.geojson")
            farmland = _load_jintian_geojson("farmland_protection.geojson")
            eco_area = sum(
                f.get("properties", {}).get("MJ", 0) or 0
                for f in ecological.get("features", []) if ecological
            ) if ecological else 0
            farm_area = sum(
                f.get("properties", {}).get("MJ", 0) or 0
                for f in farmland.get("features", []) if farmland
            ) if farmland else 0
            total_study = sum(
                f.get("properties", {}).get("MJ", 0) or 0
                for f in study_area.get("features", [])
            )
            eco_ratio = eco_area / total_study if total_study > 0 else 0
            sensitivity_class = "high" if eco_ratio > 0.3 else "medium" if eco_ratio > 0.1 else "low"

            return {
                "success": True,
                "study_area_km2": round(total_study / 100, 2),
                "ecological_area_km2": round(eco_area / 100, 2),
                "farmland_area_km2": round(farm_area / 100, 2),
                "sensitivity_class": sensitivity_class,
                "ecological_ratio": round(eco_ratio, 3),
                "source": "jintian_fallback",
                "geojson": inject_feature_colors(ecological, "sensitivity_zone"),
                "timing_ms": round((time.time() - t0) * 1000),
            }
        else:
            return {"success": True, "note": "Non-jintian ecological assessment requires study_area input", "timing_ms": round((time.time() - t0) * 1000)}
    except Exception as e:
        logger.error(f"[GIS Test] ecological failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ============================================
# Planning Endpoints
# ============================================

@router.post("/spatial-layout", summary="Generate spatial layout")
async def test_spatial_layout(request: SpatialLayoutRequest):
    """Run the full spatial layout pipeline for a village."""
    t0 = time.time()
    try:
        from app.services.modules.gis.layout.engine import SpatialLayoutEngine

        # Load jintian data for the pipeline
        boundary = _load_jintian_geojson("current/boundary.geojson")
        landuse = _load_jintian_geojson("current/landuse.geojson")
        road = _load_jintian_geojson("current/road.geojson")
        farmland = _load_jintian_geojson("farmland_protection.geojson")
        ecological = _load_jintian_geojson("ecological_protection.geojson")
        historical = _load_jintian_geojson("historical_protection.geojson")
        construction = _load_jintian_geojson("construction_zone.geojson")
        hazard = _load_jintian_geojson("geological_hazard_points.geojson")

        if not boundary:
            return {"success": False, "error": "jintian boundary data not found", "timing_ms": round((time.time() - t0) * 1000)}

        protection_zones = {}
        if farmland:
            protection_zones["farmland_protection"] = farmland
        if ecological:
            protection_zones["ecological_protection"] = ecological
        if historical:
            protection_zones["historical_protection"] = historical

        engine = SpatialLayoutEngine()
        from app.services.modules.gis.layout.planning_intent import UnifiedSpatialIntent
        intent = UnifiedSpatialIntent()
        summaries = {
            "land_use": {"construction_area_ha": 30.5, "new_construction_ha": 0.33},
            "population": {"total": 2800},
        }

        # Load L3 reports to trigger KG build + CA refinement + validation loop
        project_root = Path(__file__).resolve().parents[3]
        l3_report_path = project_root / "output" / "experiments" / "rag" / "g1" / "iter0" / "layer3_reports.json"
        reports_for_kg = None
        if l3_report_path.exists():
            try:
                import re
                with open(l3_report_path, encoding="utf-8") as f:
                    raw_reports = json.load(f).get("reports", {})

                def _extract_metrics(content: str) -> dict:
                    metrics = {}
                    patterns = [
                        (r'建设用地.*?([\d.]+)\s*公顷', '建设用地规模_公顷'),
                        (r'耕地.*?([\d.]+)\s*公顷', '耕地保有量_公顷'),
                        (r'生态保护红线.*?([\d.]+)\s*公顷', '生态保护红线面积'),
                        (r'永久基本农田.*?([\d.]+)\s*公顷', '永久基本农田_公顷'),
                        (r'森林覆盖率.*?([\d.]+)\s*%', '森林覆盖率_百分比'),
                        (r'林地.*?([\d.]+)\s*公顷', '林地保有量_公顷'),
                    ]
                    for pat, key in patterns:
                        m = re.search(pat, content)
                        if m:
                            metrics[key] = float(m.group(1))
                    return metrics

                reports_for_kg = {
                    dk: {
                        "summary": {"metrics": _extract_metrics(content)},
                        "content": content,
                    }
                    for dk, content in raw_reports.items()
                    if isinstance(content, str)
                }
            except Exception as e_load:
                logger.warning(f"[GIS Test] L3 reports load failed: {e_load}")

        conflict_report, resolution_report, layout_configs, pipeline_trace = await asyncio.to_thread(
            engine.full_pipeline,
            summaries=summaries,
            intent=intent,
            boundary_geojson=boundary,
            landuse_current_geojson=landuse,
            protection_zones=protection_zones if protection_zones else None,
            road_geojson=road,
            construction_zone_geojson=construction,
            hazard_points_geojson=hazard,
            reports=reports_for_kg,
            max_validation_rounds=2,
        )

        # Convert layout_configs to serializable format
        configs_data = []
        for cfg in layout_configs:
            cfg_dict = {k: v for k, v in cfg.items() if k != "geojson" or v is not None}
            if "geojson" in cfg and cfg["geojson"] is not None:
                cfg_dict["geojson"] = cfg["geojson"]
            configs_data.append(cfg_dict)

        return {
            "success": True,
            "layout_configs": configs_data,
            "conflicts": {
                "metric_conflicts": len(conflict_report.metric_conflicts) if hasattr(conflict_report, "metric_conflicts") else 0,
                "constraint_violations": len(conflict_report.constraint_violations) if hasattr(conflict_report, "constraint_violations") else 0,
            },
            "kg_built": engine.has_kg(),
            "pipeline_trace": pipeline_trace.model_dump() if hasattr(pipeline_trace, "model_dump") else pipeline_trace,
            "timing_ms": round((time.time() - t0) * 1000),
        }
    except Exception as e:
        logger.error(f"[GIS Test] spatial-layout failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/landuse-change", summary="Analyze landuse change")
async def test_landuse_change(request: LanduseChangeRequest):
    """Compare current vs planned landuse from jintian data."""
    t0 = time.time()
    try:
        current = _load_jintian_geojson("current/landuse.geojson")
        planned = _load_jintian_geojson("planned/landuse.geojson")

        if not current or not planned:
            return {"success": False, "error": "jintian landuse data not found", "timing_ms": round((time.time() - t0) * 1000)}

        # Inject per-feature colors based on DLBM → zone_type mapping
        current = inject_feature_colors(current, "function_zone")
        planned = inject_feature_colors(planned, "planning_zone")

        current_features = len(current.get("features", []))
        planned_features = len(planned.get("features", []))

        # Basic statistics
        current_dlbm = set()
        planned_dlbm = set()
        for f in current.get("features", []):
            props = f.get("properties", {})
            if "DLBM" in props:
                current_dlbm.add(props["DLBM"])
        for f in planned.get("features", []):
            props = f.get("properties", {})
            if "DLBM" in props:
                planned_dlbm.add(props["DLBM"])

        return {
            "success": True,
            "current_parcels": current_features,
            "planned_parcels": planned_features,
            "current_dlbm_types": len(current_dlbm),
            "planned_dlbm_types": len(planned_dlbm),
            "added_dlbm": list(planned_dlbm - current_dlbm),
            "removed_dlbm": list(current_dlbm - planned_dlbm),
            "geojson": {
                "current": current,
                "planned": planned,
            },
            "timing_ms": round((time.time() - t0) * 1000),
        }
    except Exception as e:
        logger.error(f"[GIS Test] landuse-change failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/constraint-validator", summary="Validate planning constraints")
async def test_constraint_validator(request: ConstraintValidatorRequest):
    """Run conflict detection on jintian data summaries."""
    t0 = time.time()
    try:
        from app.services.modules.gis.layout.conflict_detector import ConflictDetector

        # Use jintian-based summaries
        summaries = {
            "land_use": {
                "construction_area_ha": 30.5,
                "new_construction_ha": 0.33,
                "farmland_area_ha": 120.0,
                "ecological_area_ha": 80.0,
            },
            "population": {"total": 2800, "density": 700},
            "natural_environment": {"forest_coverage": 0.65},
        }

        detector = ConflictDetector()
        report = await asyncio.to_thread(detector.detect_all, summaries)

        return {
            "success": True,
            "metric_conflicts": len(report.metric_conflicts) if hasattr(report, "metric_conflicts") else 0,
            "constraint_violations": len(report.constraint_violations) if hasattr(report, "constraint_violations") else 0,
            "spatial_conflicts": len(report.spatial_conflicts) if hasattr(report, "spatial_conflicts") else 0,
            "is_valid": len(report.constraint_violations) == 0 if hasattr(report, "constraint_violations") else True,
            "timing_ms": round((time.time() - t0) * 1000),
        }
    except Exception as e:
        logger.error(f"[GIS Test] constraint-validator failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/hazard-buffer", summary="Generate hazard buffer zones")
async def test_hazard_buffer(request: HazardBufferRequest):
    """Generate geological hazard buffer zones from jintian data."""
    t0 = time.time()
    try:
        hazard_data = _load_jintian_geojson("geological_hazard_points.geojson")

        if not hazard_data:
            return {"success": False, "error": "jintian hazard data not found", "timing_ms": round((time.time() - t0) * 1000)}

        features = hazard_data.get("features", [])
        hazard_count = len(features)

        # Try geopandas buffer in projected CRS for accuracy
        try:
            import geopandas as gpd
            from shapely.geometry import shape
            from app.services.modules.gis.utils.crs_engine import project_to_metric, project_to_wgs84

            buffered_features = []
            for f in features:
                geom = shape(f.get("geometry", {}))
                # Buffer in projected CRS (CGCS2000 Gauss-Kruger) for meter-accurate results
                gdf = gpd.GeoSeries([geom], crs="EPSG:4326")
                lon = geom.centroid.x
                gdf_m = gdf.to_crs(
                    f"EPSG:{4526 + int(round((lon + 1.5) / 3.0))}"
                )
                buf_m = gdf_m.buffer(request.buffer_meters).iloc[0]
                buf = gpd.GeoSeries([buf_m], crs=gdf_m.crs).to_crs("EPSG:4326").iloc[0]
                buffered_features.append({
                    "type": "Feature",
                    "properties": {**f.get("properties", {}), "buffer_m": request.buffer_meters},
                    "geometry": buf.__geo_interface__,
                })

            geojson = {"type": "FeatureCollection", "features": buffered_features}
        except ImportError:
            geojson = hazard_data  # fallback: return points without buffer

        return {
            "success": True,
            "hazard_count": hazard_count,
            "buffer_meters": request.buffer_meters,
            "geojson": geojson,
            "timing_ms": round((time.time() - t0) * 1000),
        }
    except Exception as e:
        logger.error(f"[GIS Test] hazard-buffer failed: {e}")
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ============================================
# Layout Validation Endpoint
# ============================================

@router.post("/layout-validate", summary="Validate spatial layout configs")
async def validate_layout(request: LayoutValidateRequest):
    """Validate layout configs using LayoutValidator (8 checks).

    Two modes:
    1. Pass layout_configs directly (from spatial-layout or parse-text response)
    2. Set use_jintian_data=True to generate + validate from jintian data
    """
    t0 = time.time()
    try:
        from app.services.modules.gis.layout.validator import LayoutValidator

        layout_configs = request.layout_configs

        # Mode 2: generate layout from jintian data then validate
        if request.use_jintian_data and not layout_configs:
            from app.services.modules.gis.layout.engine import SpatialLayoutEngine
            from app.services.modules.gis.layout.planning_intent import UnifiedSpatialIntent

            boundary = _load_jintian_geojson("current/boundary.geojson")
            landuse = _load_jintian_geojson("current/landuse.geojson")
            if not boundary:
                return {"success": False, "error": "jintian boundary data not found", "timing_ms": round((time.time() - t0) * 1000)}

            engine = SpatialLayoutEngine()
            intent = UnifiedSpatialIntent()
            summaries = {
                "land_use": {"construction_area_ha": 30.5, "new_construction_ha": 0.33},
                "population": {"total": 2800},
            }
            _, _, layout_configs = engine.full_pipeline(
                summaries=summaries,
                intent=intent,
                boundary_geojson=boundary,
                landuse_current_geojson=landuse,
            )

        if not layout_configs:
            return {"success": False, "error": "No layout_configs provided and jintian generation failed", "timing_ms": round((time.time() - t0) * 1000)}

        validator = LayoutValidator()
        report = await asyncio.to_thread(
            validator.validate, layout_configs, request.constraints
        )

        # Build check-level details for frontend
        checks_detail = []
        for c in report.checks:
            checks_detail.append({
                "name": c.check_name,
                "passed": c.passed,
                "violation_count": c.violation_count,
                "violations": [
                    {"check": v.check, "severity": v.severity, "message": v.message}
                    for v in c.violations
                ],
            })

        # Zone area summary
        zone_areas = LayoutValidator._get_zone_areas(layout_configs)

        return {
            "success": True,
            "validation": report.to_dict(),
            "checks": checks_detail,
            "zone_areas": zone_areas,
            "timing_ms": round((time.time() - t0) * 1000),
        }
    except Exception as e:
        logger.error(f"[GIS Test] layout-validate failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ============================================
# Parse Planning Text → Intent
# ============================================

class ParseTextRequest(BaseModel):
    village_name: str = "金田村"
    planning_text: str = ""
    use_jintian_reports: bool = False
    use_db_reports: bool = True


@router.post("/parse-text", summary="Parse planning text to spatial intent")
async def parse_planning_text(request: ParseTextRequest):
    """从规划文本解析出 UnifiedSpatialIntent，并生成图层对比。

    优先级：use_db_reports > planning_text > use_jintian_reports
    - use_db_reports=True: 从数据库加载最新 L3 报告
    - planning_text 非空: 使用提供的文本
    - use_jintian_reports=True: 使用内置示例文本
    """
    t0 = time.time()

    # --- Option 1: Load from DB ---
    if request.use_db_reports:
        try:
            from app.services.report_store import ReportStore
            from app.database.engine import get_async_session
            from sqlalchemy import text

            store = ReportStore()

            # Get latest session_id with L3 reports via SQLAlchemy session
            async with get_async_session() as db:
                result = await db.execute(text("""
                    SELECT session_id FROM dimension_reports
                    WHERE layer=3
                    GROUP BY session_id
                    ORDER BY MAX(generated_at) DESC LIMIT 1
                """))
                row = result.fetchone()

            if not row:
                return {"success": False, "error": "No L3 reports in DB", "timing_ms": round((time.time() - t0) * 1000)}

            session_id = row[0]
            summaries = await store.get_layer_summaries(session_id, 3)

            if not summaries:
                return {"success": False, "error": f"No L3 summaries for session {session_id[:16]}...", "timing_ms": round((time.time() - t0) * 1000)}

            reports = {}
            for dk, parsed in summaries.items():
                reports[dk] = {
                    "summary": {
                        "metrics": parsed.get("metrics", {}),
                        "key_points": parsed.get("key_points", []),
                        "text_summary": parsed.get("text_summary", ""),
                    },
                    "content": parsed.get("text_summary", ""),
                }

            dim_list = list(reports.keys())
            logger.info(f"[parse-text] Loaded {len(reports)} dims from DB session {session_id[:16]}...: {dim_list}")

            from app.tools.gis.layout_tools import _aparse_reports_to_intent
            result = await _aparse_reports_to_intent(reports=reports, village_name=request.village_name)

            if not result.get("success"):
                return {"success": False, "error": result.get("error", "Unknown"), "timing_ms": round((time.time() - t0) * 1000)}

            intent_json = result["data"]["intent_json"]
            parse_trace = result["data"].get("parse_trace")

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"[GIS Test] parse-text DB load failed: {e}\n{tb}")
            return {"success": False, "error": f"DB load failed: {e}", "traceback": tb[:500], "timing_ms": round((time.time() - t0) * 1000)}

    else:
        # --- Option 2/3: Text-based ---
        planning_text = request.planning_text
        if not planning_text and request.use_jintian_reports:
            planning_text = _get_jintian_planning_text()

        if not planning_text:
            return {"success": False, "error": "No planning text provided", "timing_ms": round((time.time() - t0) * 1000)}

        from app.agent.gis.prompts import format_parse_prompt
        from app.core.settings import LLM_MODEL

        prompt_text = format_parse_prompt(
            planning_text=planning_text,
            village_name=request.village_name,
            total_area="2352.56",
            current_land_use="农业用地为主，含居民点、林地、水域",
        )

        parse_trace = None
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=LLM_MODEL, temperature=0, request_timeout=120)
            response = await llm.ainvoke(prompt_text)
            response_text = response.content
            from app.services.modules.gis.layout.trace import ParseTrace
            parse_trace = ParseTrace(
                source="jintian_reports" if request.use_jintian_reports else "planning_text",
                llm_model=LLM_MODEL,
                llm_prompt=prompt_text,
                llm_response=response_text,
            ).model_dump()
        except Exception as e:
            logger.error(f"[GIS Test] parse-text LLM failed: {e}")
            return {"success": False, "error": f"LLM failed: {e}", "timing_ms": round((time.time() - t0) * 1000)}

        import re as _re
        json_match = _re.search(r'```json\s*(.*?)\s*```', response_text, _re.DOTALL)
        if not json_match:
            json_match = _re.search(r'(\{[\s\S]*\})', response_text)

        if not json_match:
            return {
                "success": False,
                "error": "No JSON found in LLM response",
                "raw_response": response_text[:500],
                "timing_ms": round((time.time() - t0) * 1000),
            }

        try:
            intent_json = json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"JSON parse error: {e}",
                "timing_ms": round((time.time() - t0) * 1000),
            }

        zones = intent_json.get("zones", [])
        if zones:
            total_ratio = sum(z.get("area_ratio", 0) for z in zones)
            if abs(total_ratio - 1.0) > 0.05:
                for z in zones:
                    z["area_ratio"] = round(z.get("area_ratio", 0) / total_ratio, 4)
                new_sum = sum(z["area_ratio"] for z in zones)
                if abs(new_sum - 1.0) > 0.001 and zones:
                    zones[0]["area_ratio"] = round(zones[0].get("area_ratio", 0) + (1.0 - new_sum), 4)

    # --- Common: Generate layout from intent_json ---
    try:
        from app.tools.gis.layout_tools import _dict_to_intent
        from app.services.modules.gis.layout.engine import SpatialLayoutEngine

        intent = _dict_to_intent(intent_json)
        engine = SpatialLayoutEngine()

        boundary = _load_jintian_geojson("current/boundary.geojson")
        landuse = _load_jintian_geojson("current/landuse.geojson")

        configs = engine.generate_layout(
            intent=intent,
            boundary_geojson=boundary,
            landuse_current_geojson=landuse,
        )

        from app.services.modules.gis.layout.planning_intent import UnifiedSpatialIntent as USI
        default_intent = USI()
        default_configs = engine.generate_layout(
            intent=default_intent,
            boundary_geojson=boundary,
            landuse_current_geojson=landuse,
        )

        zone_summary = ", ".join(f"{z.land_use}({z.area_ratio:.1%})" for z in intent.zones)

        return {
            "success": True,
            "intent": {
                "zone_count": len(intent.zones),
                "facility_count": len(intent.facilities),
                "axis_count": len(intent.axes),
                "zones": zone_summary,
            },
            "parsed_layout": {
                "layer_count": len(configs),
                "layer_types": [c.get("layerType") for c in configs],
            },
            "default_layout": {
                "layer_count": len(default_configs),
                "layer_types": [c.get("layerType") for c in default_configs],
            },
            "intent_json": intent_json,
            "parse_trace": parse_trace,
            "timing_ms": round((time.time() - t0) * 1000),
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"[GIS Test] parse-text layout generation failed: {e}\n{tb}")
        return {
            "success": False,
            "error": f"Layout generation failed: {e}",
            "traceback": tb[:1000],
            "intent_json": intent_json if 'intent_json' in dir() else None,
            "timing_ms": round((time.time() - t0) * 1000),
        }


def _get_jintian_planning_text() -> str:
    """Return a built-in planning text sample for Jintian village."""
    return """## 金田村规划概况

金田村位于广东省梅州市梅县区，总面积约23.5平方公里。村庄以农业生产为主，
现有耕地约78.83公顷，生态保护面积362.02公顷，建设区约30.50公顷。

## 用地规划

根据上位规划要求，金田村应保持农田保护区78.83公顷，
划定村庄建设区30.50公顷用于居民点建设和公共服务设施。
生态保护区362.02公顷需严格管控，一般农业区1881.54公顷可适度开发。

居住用地主要集中在村庄中心区域，沿主要道路分布。
产业用地规划在村庄东部，远离居民区。
公共服务用地包括村委会、卫生站、学校等，位于村庄中心。
生态绿地主要分布在北部山体和水系周边。
交通用地沿东西向主干道分布，连接周边村庄。
水域包括金田河及山塘水库，需保护水源地。

## 公共服务设施

现状设施：村委会1处，卫生站1所，小学1所。
规划新增：文化活动中心1处，养老服务站1处，停车场2处。
设施布局原则：服务半径不超过500米，优先布局在村庄中心。

## 发展轴线

主要发展轴：沿东西向主干道（省道S223）布局，连接镇区与周边村庄。
次要发展轴：沿南北向村道，连接北部生态区与南部农业区。
空间结构：一心（村委会中心）、一轴（东西主轴）、两区（生态保护区与建设发展区）。"""


# ============================================
# Jintian Static Data Endpoints
# ============================================

@router.get("/jintian/files", summary="List jintian boundary files")
async def list_jintian_files():
    """List available GeoJSON files in jintian_boundary directory."""
    data_dir = _jintian_data_dir()
    if not data_dir.is_dir():
        return {"success": False, "error": "jintian data directory not found", "files": []}

    # Map filenames to layer groups (new path structure: current/xxx.geojson, planned/xxx.geojson)
    GROUP_MAP = {
        "current/boundary": "status", "current/road": "status",
        "current/landuse": "status", "current/annotation": "status",
        "current/admin_boundary_line": "status",
        "planned/boundary": "status",
        "planned/landuse": "planned", "planned/road": "planned",
        "planned/annotation": "planned",
        "planned/farmland_protection": "protection",
        "planned/ecological_protection": "protection",
        "planned/historical_protection": "protection",
        "planned/construction_zone": "planned",
        "planned/geological_hazard_points": "status",
        "project/polygons": "planned", "project/lines": "planned",
        "project/points": "planned", "project/annotation": "planned",
    }

    LAYER_TYPE_MAP = {
        "current/boundary": "boundary", "planned/boundary": "boundary",
        "current/road": "infrastructure", "planned/road": "infrastructure",
        "current/landuse": "function_zone", "planned/landuse": "planning_zone",
        "planned/farmland_protection": "sensitivity_zone",
        "planned/ecological_protection": "sensitivity_zone",
        "planned/historical_protection": "sensitivity_zone",
        "planned/geological_hazard_points": "facility_point",
        "planned/construction_zone": "planning_zone",
    }

    files = []
    for f in sorted(data_dir.rglob("*.geojson")):
        # Use relative path as key (e.g., "current/boundary")
        rel_path = str(f.relative_to(data_dir).with_suffix(""))
        name = rel_path.replace("\\", "/")
        group = GROUP_MAP.get(name, "status")
        layer_type = LAYER_TYPE_MAP.get(name, "function_zone")

        # Quick feature count
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                feature_count = len(data.get("features", []))
        except Exception:
            feature_count = 0

        files.append({
            "filename": str(f.relative_to(data_dir)).replace("\\", "/"),
            "name": name,
            "group": group,
            "layer_type": layer_type,
            "records": feature_count,
        })

    return {"success": True, "files": files}


@router.get("/jintian/data/{filename:path}", summary="Get jintian GeoJSON file")
async def get_jintian_data(filename: str):
    """Return a GeoJSON file from data/gis/jintian/ directory."""
    # Security: only allow .geojson files, no path traversal
    if not filename.endswith(".geojson"):
        return {"success": False, "error": "Only .geojson files allowed"}
    if ".." in filename:
        return {"success": False, "error": "Path traversal not allowed"}

    data = _load_jintian_geojson(filename)
    if data is None:
        return {"success": False, "error": f"File not found: {filename}"}

    return {"success": True, "geojson": data}
