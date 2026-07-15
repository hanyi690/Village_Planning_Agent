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

from app.services.modules.gis.zone_schema import (
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
                from app.services.modules.gis.zone_schema import FACILITY_STATUS_COLORS
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
        from app.services.modules.gis.data.fetcher import get_fetcher
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
        from app.services.modules.gis.data.fetcher import get_fetcher
        fetcher = get_fetcher()
        center, metadata = await asyncio.to_thread(
            fetcher.get_village_center, request.location, request.buffer_km
        )
        # Fallback to jintian boundary center if geocoding fails
        if center is None:
            from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
            boundary = _load_all_gis().get("boundary_geojson")
            if boundary:
                try:
                    from shapely.geometry import shape
                    geom = shape(boundary["features"][0]["geometry"])
                    c = geom.centroid
                    center = (c.x, c.y)
                    metadata["fallback"] = "jintian_boundary_centroid"
                except Exception as e:
                    metadata["fallback"] = "boundary_centroid_failed"
                    metadata["fallback_error"] = str(e)
            else:
                metadata["fallback"] = "no_boundary_data"
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
        from app.services.modules.gis.data.fetcher import get_fetcher
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
        from app.services.modules.gis.analysis.accessibility import run_accessibility_analysis
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
        from app.services.modules.gis.analysis.coverage import calculate_gis_coverage
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
        from app.services.modules.gis.validation.facility_validator import validate_facility_location
        from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
        location_tuple = tuple(request.location)
        gis_data = _load_all_gis()
        analysis_params = {
            "population_points": [],
            "existing_facilities": [],
            "land_use_data": gis_data.get("landuse_current_geojson"),
            "protection_zones": {
                "farmland_protection": gis_data.get("farmland_protection_geojson"),
                "ecological_redline": gis_data.get("ecological_protection_geojson"),
            },
            "hazard_zones": gis_data.get("geological_hazard_geojson"),
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
            from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
            gis_data = _load_all_gis()
            study_area = gis_data.get("boundary_geojson")
            water = gis_data.get("landuse_current_geojson")
            if not study_area:
                return {"success": False, "error": "jintian boundary data not found", "timing_ms": round((time.time() - t0) * 1000)}

            # Try full assessment first
            try:
                from app.services.modules.gis.validation.facility_validator import assess_ecological_sensitivity, SPATIAL_AVAILABLE
                if not SPATIAL_AVAILABLE:
                    raise ImportError("spatial_analysis module not available")
                result = await asyncio.to_thread(assess_ecological_sensitivity, study_area, water)
                if not result.get("success", True):
                    raise RuntimeError(result.get("error", "unknown error"))
                return {"success": True, **result, "timing_ms": round((time.time() - t0) * 1000)}
            except (ImportError, ModuleNotFoundError, RuntimeError) as e:
                logger.warning(f"[GIS Test] ecological full assessment unavailable: {e}")

            # Fallback: simple area-based assessment from jintian data
            ecological = gis_data.get("ecological_protection_geojson")
            farmland = gis_data.get("farmland_protection_geojson")
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
        from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
        from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator
        from app.services.modules.gis.kg import PlanningKG
        from app.services.modules.gis.conflict.detector import ConflictDetector
        from app.services.modules.gis.conflict.resolver import ConflictResolver
        from app.services.modules.gis.optimizer.mip_allocator import MIPZoneAllocator
        from app.services.modules.gis.layout.zone_generator import ZoneGenerator
        from app.services.modules.gis.layout.facility_placer import FacilityPlacer
        from app.services.modules.gis.layout.axis_builder import AxisBuilder
        from app.services.modules.gis.layout.map_renderer import MapRenderer

        gis_data = _load_all_gis()
        boundary = gis_data.get("boundary_geojson")
        landuse = gis_data.get("landuse_current_geojson")

        if not boundary:
            return {"success": False, "error": "jintian boundary data not found", "timing_ms": round((time.time() - t0) * 1000)}

        summaries = GISMetricsCalculator.compute_summaries(gis_data)

        # Resolve intent via gen path (planning markdown → LLM → intent)
        from app.services.modules.gis.layout.intent_cache import resolve_gen_intent_cached
        from app.tools.gis.parse import _dict_to_intent
        intent_dict = resolve_gen_intent_cached("金田村委会", gis_data)
        intent = _dict_to_intent(intent_dict)

        # 1. KG
        kg = PlanningKG(village_name="金田村委会")
        kg.build_from_reports(reports={}, landuse_geojson=landuse, gis_data=gis_data)
        kg_constraints = kg.get_constraints()

        # 2. Conflict
        conflict_report = ConflictDetector().detect_all(summaries)
        if conflict_report.has_conflicts:
            resolution_report = ConflictResolver().resolve(conflict_report)
        else:
            resolution_report = None

        # 3. Allocate (MIP)
        metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
        total_area_ha = metrics["total_area_ha"]
        targets = {}
        for z in intent_dict.get("zones", []):
            lu, ratio = z.get("land_use", ""), z.get("area_ratio", 0)
            if lu and ratio:
                targets[lu] = ratio * total_area_ha
        allocated_geojson = None
        if targets and landuse:
            try:
                allocator = MIPZoneAllocator()
                allocated_geojson, _mip_trace = allocator.solve(
                    landuse_geojson=landuse, targets=targets,
                    constraints=kg_constraints or None, kg=kg,
                )
            except Exception:
                pass

        # 4-5. Generate
        effective_landuse = allocated_geojson or landuse
        all_layers = {}
        zg = ZoneGenerator()
        func_zones = zg.generate(intent, effective_landuse, boundary, gis_data)
        if func_zones:
            all_layers["function_zone"] = func_zones
        fp = FacilityPlacer()
        facilities = fp.place(
            facilities=intent.facilities if hasattr(intent, "facilities") else [],
            landuse_geojson=effective_landuse, boundary_geojson=boundary,
        )
        if facilities and facilities.get("features"):
            all_layers["facility_point"] = facilities
        ab = AxisBuilder()
        axes = ab.build(intent, boundary, effective_landuse)
        if axes and axes.get("features"):
            all_layers["development_axis"] = axes
        mr = MapRenderer()
        layout_configs = await asyncio.to_thread(mr.render, all_layers, boundary)

        # Convert layout_configs to serializable format
        configs_data = []
        for cfg in layout_configs:
            cfg_dict = {k: v for k, v in cfg.items() if k != "geojson" or v is not None}
            if "geojson" in cfg and cfg["geojson"] is not None:
                cfg_dict["geojson"] = cfg["geojson"]
            configs_data.append(cfg_dict)

        return _sanitize_floats({
            "success": True,
            "layout_configs": configs_data,
            "conflicts": {
                "metric_conflicts": len(conflict_report.metric_conflicts) if conflict_report and hasattr(conflict_report, "metric_conflicts") else 0,
                "constraint_violations": len(conflict_report.constraint_violations) if conflict_report and hasattr(conflict_report, "constraint_violations") else 0,
            },
            "kg_built": kg is not None,
            "timing_ms": round((time.time() - t0) * 1000),
        })
    except Exception as e:
        logger.error(f"[GIS Test] spatial-layout failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


@router.post("/landuse-change", summary="Analyze landuse change")
async def test_landuse_change(request: LanduseChangeRequest):
    """Compare current vs planned landuse from jintian data."""
    t0 = time.time()
    try:
        from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
        gis_data = _load_all_gis()
        current = gis_data.get("landuse_current_geojson")
        planned = gis_data.get("landuse_planned_geojson")

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
        from app.services.modules.gis.conflict.detector import ConflictDetector
        from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
        from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator

        _gis_data_for_metrics = _load_all_gis()
        summaries = GISMetricsCalculator.compute_summaries(_gis_data_for_metrics)

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
        from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
        gis_data = _load_all_gis()
        hazard_data = gis_data.get("geological_hazard_geojson")

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
        from app.services.modules.gis.validation.layout_validator import LayoutValidator

        layout_configs = request.layout_configs

        # Mode 2: generate layout from jintian data then validate
        if request.use_jintian_data and not layout_configs:
            from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
            from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator
            from app.services.modules.gis.kg import PlanningKG
            from app.services.modules.gis.conflict.detector import ConflictDetector
            from app.services.modules.gis.conflict.resolver import ConflictResolver
            from app.services.modules.gis.optimizer.mip_allocator import MIPZoneAllocator
            from app.services.modules.gis.layout.zone_generator import ZoneGenerator
            from app.services.modules.gis.layout.facility_placer import FacilityPlacer
            from app.services.modules.gis.layout.axis_builder import AxisBuilder
            from app.services.modules.gis.layout.map_renderer import MapRenderer

            gis_data = _load_all_gis()
            boundary = gis_data.get("boundary_geojson")
            landuse = gis_data.get("landuse_current_geojson")
            if not boundary:
                return {"success": False, "error": "jintian boundary data not found", "timing_ms": round((time.time() - t0) * 1000)}

            # Resolve intent via gen path
            from app.services.modules.gis.layout.intent_cache import resolve_gen_intent_cached
            from app.tools.gis.parse import _dict_to_intent
            intent_dict = resolve_gen_intent_cached("金田村委会", gis_data)
            intent = _dict_to_intent(intent_dict)

            # 1. KG
            kg = PlanningKG(village_name="金田村委会")
            kg.build_from_reports(reports={}, landuse_geojson=landuse, gis_data=gis_data)
            kg_constraints = kg.get_constraints()

            # 2. Conflict
            summaries = GISMetricsCalculator.compute_summaries(gis_data)
            conflict_report = ConflictDetector().detect_all(summaries)
            if conflict_report.has_conflicts:
                ConflictResolver().resolve(conflict_report)

            # 3. Allocate (MIP)
            metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
            total_area_ha = metrics["total_area_ha"]
            targets = {}
            for z in intent_dict.get("zones", []):
                lu, ratio = z.get("land_use", ""), z.get("area_ratio", 0)
                if lu and ratio:
                    targets[lu] = ratio * total_area_ha
            allocated_geojson = None
            if targets and landuse:
                try:
                    allocator = MIPZoneAllocator()
                    allocated_geojson, _ = allocator.solve(
                        landuse_geojson=landuse, targets=targets,
                        constraints=kg_constraints or None, kg=kg,
                    )
                except Exception:
                    pass

            # 4-5. Generate
            effective_landuse = allocated_geojson or landuse
            all_layers = {}
            zg = ZoneGenerator()
            func_zones = zg.generate(intent, effective_landuse, boundary, gis_data)
            if func_zones:
                all_layers["function_zone"] = func_zones
            fp = FacilityPlacer()
            facilities = fp.place(
                facilities=intent.facilities if hasattr(intent, "facilities") else [],
                landuse_geojson=effective_landuse, boundary_geojson=boundary,
            )
            if facilities and facilities.get("features"):
                all_layers["facility_point"] = facilities
            ab = AxisBuilder()
            axes = ab.build(intent, boundary, effective_landuse)
            if axes and axes.get("features"):
                all_layers["development_axis"] = axes
            mr = MapRenderer()
            layout_configs = await asyncio.to_thread(mr.render, all_layers, boundary)

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

        return _sanitize_floats({
            "success": True,
            "validation": report.to_dict(),
            "checks": checks_detail,
            "zone_areas": zone_areas,
            "timing_ms": round((time.time() - t0) * 1000),
        })
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

            from app.tools.gis.parse import _parse_reports_to_intent
            from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
            _gis_data_for_parse = _load_all_gis()
            result = _parse_reports_to_intent(reports=reports, village_name=request.village_name, gis_data=_gis_data_for_parse)

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
        from app.services.modules.gis.layout.data_loader import get_village_params, load_all as _load_all_gis

        _gis_data_for_params = _load_all_gis()
        _params = get_village_params(_gis_data_for_params)

        prompt_text = format_parse_prompt(
            planning_text=planning_text,
            village_name=request.village_name,
            total_area=_params["total_area"],
            current_land_use=_params["land_use_description"],
        )

        parse_trace = None
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=LLM_MODEL, temperature=0, request_timeout=120)
            response = await llm.ainvoke(prompt_text)
            response_text = response.content
            from app.services.modules.gis.trace import ParseTrace
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
        from app.services.modules.gis.layout.data_loader import load_all as _load_all_gis
        from app.services.modules.gis.layout.zone_generator import ZoneGenerator
        from app.services.modules.gis.layout.facility_placer import FacilityPlacer
        from app.services.modules.gis.layout.axis_builder import AxisBuilder
        from app.services.modules.gis.layout.map_renderer import MapRenderer
        from app.tools.gis.parse import _dict_to_intent

        gis_data = _load_all_gis()
        boundary = gis_data.get("boundary_geojson")
        landuse = gis_data.get("landuse_current_geojson")

        def _generate(intent_data):
            intent_obj = _dict_to_intent(intent_data) if intent_data else None
            all_layers = {}
            if intent_obj:
                zg = ZoneGenerator()
                func_zones = zg.generate(intent_obj, landuse, boundary, gis_data)
                if func_zones:
                    all_layers["function_zone"] = func_zones
                fp = FacilityPlacer()
                facilities = fp.place(
                    facilities=intent_obj.facilities if hasattr(intent_obj, "facilities") else [],
                    landuse_geojson=landuse, boundary_geojson=boundary,
                )
                if facilities and facilities.get("features"):
                    all_layers["facility_point"] = facilities
                ab = AxisBuilder()
                axes = ab.build(intent_obj, boundary, landuse)
                if axes and axes.get("features"):
                    all_layers["development_axis"] = axes
            mr = MapRenderer()
            return mr.render(all_layers, boundary)

        configs = _generate(intent_json)
        default_configs = _generate(None)

        zones = intent_json.get("zones", [])
        zone_summary = ", ".join(f"{z.get('land_use','?')}({z.get('area_ratio',0):.1%})" for z in zones)

        return {
            "success": True,
            "intent": {
                "zone_count": len(zones),
                "facility_count": len(intent_json.get("facilities", [])),
                "axis_count": len(intent_json.get("axes", [])),
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
    """Return planning text from actual markdown file."""
    from app.services.modules.gis.layout.planning_text_loader import PlanningTextLoader
    return PlanningTextLoader.load_village_planning_markdown("金田村")


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


# ============================================
# Jin Tian Pipeline Test Endpoint
# ============================================
#
# 三路对比架构：
#   规划 markdown (人工规划文本) ──→ gen intent ──→ KG→CONFLICT→ALLOCATE→GENERATE ──→ gen layers
#   L3 reports (系统L3报告)        ──→ plan intent ──→ KG→CONFLICT→ALLOCATE→GENERATE ──→ plan layers
#   planned/ (人工绘制GIS图纸)      ───────────────────────────────────────────────────→ ground truth
#
# 对比矩阵：
#   gen layers  vs planned/  =  「AI 解读人工规划文本」 vs 「人工绘制图纸」  — 测试 AI 能否准确理解规划文本
#   plan layers vs planned/  =  「AI 基于 L3 报告生成」 vs 「人工绘制图纸」  — 测试 AI 能否匹配人工经验
#   gen layers  vs plan layers = 「人工文本路径」        vs 「L3 报告路径」    — 测试两条路径一致性
# ============================================

def _sanitize_floats(obj: Any) -> Any:
    """递归替换 inf/nan 为 None，确保 JSON 兼容。

    MIP 求解器和 AxisBuilder 可能在几何坐标中产生 inf，
    FastAPI 的 JSONResponse 无法序列化这些值。
    Shapely 输出的 GeoJSON 坐标可能使用 tuple，需一并处理。
    """
    import math
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_floats(v) for v in obj]
    return obj


class JinTianPipelineRequest(BaseModel):
    """Jin Tian pipeline 请求参数。

    默认运行双路径（gen + plan）并执行三路对比。
    可切换为单路径或跳过对比以加快测试。
    """
    # 路径控制：gen = 人工规划 markdown, plan = L3 reports, both = 双路径对比
    run_path: str = "both"       # "gen" | "plan" | "both"
    # 是否使用实时 LLM 解析（否则走缓存）
    use_llm: bool = False
    # 是否与 planned/ 人工绘制图纸对比
    compare_to_planned: bool = True
    # 实时 LLM 解析时使用的规划文本（use_llm=True 时生效）
    planning_text: str = ""


@router.post("/jintian/pipeline", summary="双路径 pipeline：gen(人工文本) / plan(L3报告) + 三路对比")
async def jintian_pipeline(request: JinTianPipelineRequest):
    """完整的 GIS 布局管线 — 支持双路径并行 + 三路对比。

    流程（每条路径独立执行）：
      1. 解析 intent（gen: 人工规划 markdown → LLM, plan: L3 reports → LLM）
      2. 构建 KG（注入 GIS 实测约束: 建设用地上限、耕地保有量下限等）
      3. 冲突检测 & 消解（跨维度指标冲突 + 约束违规）
      4. MIP 分配（PuLP 线性规划，引入 KG 约束 + 邻接奖励）
      5. 生成图层（function_zone + planning_zone + facility_point + axis）

    三路对比（compare_to_planned=True 时）：
      - gen layers vs planned/  : 人工规划文本 → AI 生成 vs 人工绘制
      - plan layers vs planned/ : L3 报告 → AI 生成 vs 人工绘制
      - gen layers vs plan layers : 两条 AI 路径一致性评估
    """
    t0 = time.time()
    try:
        from app.services.modules.gis.layout.data_loader import (
            load_all, load_current, load_planned,
            get_village_params, get_data_summary,
        )
        from app.services.modules.gis.layout.intent_cache import (
            resolve_gen_intent_cached, resolve_plan_intent_cached,
        )
        from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator

        # ── 加载数据（所有路径共用）───────────────────────────────
        gis_data = load_all()
        current_data = load_current()
        planned_data = load_planned() if request.compare_to_planned else {}
        data_summary = get_data_summary(gis_data)

        # 执行状态容器
        gen_result: Dict[str, Any] = {}
        plan_result: Dict[str, Any] = {}

        # ============================================================
        # 路径 A: gen — 人工规划 markdown → LLM → intent → layers
        #   数据源: data/gis/jintian/planning_text/金田村委会.md
        #   含义: AI 解读人类规划师书写的规划文档，生成 GIS 图层
        # ============================================================
        if request.run_path in ("gen", "both"):
            gen_result = await _run_pipeline_path(
                request=request,
                path_name="gen",
                intent_resolver=lambda: resolve_gen_intent_cached("金田村委会", gis_data),
                gis_data=gis_data,
                planned_data=planned_data,
                village_name="金田村委会",
            )

        # ============================================================
        # 路径 B: plan — L3 reports → LLM → intent → layers
        #   数据源: output/experiments/rag/g1/iter0/layer3_reports.json
        #   含义: AI 基于 Agent pipeline 产出的 L3 报告生成 GIS 图层
        # ============================================================
        if request.run_path in ("plan", "both"):
            plan_result = await _run_pipeline_path(
                request=request,
                path_name="plan",
                intent_resolver=lambda: resolve_plan_intent_cached("金田村委会", gis_data),
                gis_data=gis_data,
                planned_data=planned_data,
                village_name="金田村委会",
            )

        # ============================================================
        # 三路对比
        #   gen vs planned/ : 「AI 解读人工规划文本」 vs 「人工绘制图纸」
        #   plan vs planned/ : 「AI 基于 L3 报告」 vs 「人工绘制图纸」
        #   gen vs plan     : 「人工文本路径」 vs 「L3 报告路径」
        # ============================================================
        comparison = None
        if request.compare_to_planned:
            comparison = _build_three_way_comparison(
                gen_result=gen_result.get("layers"),
                plan_result=plan_result.get("layers"),
                planned_data=planned_data,
                gis_data=gis_data,
            )

        # ── 汇总 ───────────────────────────────────────────────────
        elapsed = round((time.time() - t0) * 1000)
        response: Dict[str, Any] = {
            "success": True,
            "data_summary": data_summary,
            "timing_ms": elapsed,
        }

        # 附加 gen 路径结果
        if gen_result:
            response["gen"] = {
                "parse_source": gen_result.get("parse_source"),
                "intent_zones": len(gen_result.get("intent", {}).get("zones", [])),
                "layers": gen_result.get("layer_summary"),
                "kg": gen_result.get("kg"),
                "conflict": gen_result.get("conflict"),
                "allocation": gen_result.get("allocation"),
                "layout_configs": gen_result.get("layers"),
            }

        # 附加 plan 路径结果
        if plan_result:
            response["plan"] = {
                "parse_source": plan_result.get("parse_source"),
                "intent_zones": len(plan_result.get("intent", {}).get("zones", [])),
                "layers": plan_result.get("layer_summary"),
                "kg": plan_result.get("kg"),
                "conflict": plan_result.get("conflict"),
                "allocation": plan_result.get("allocation"),
                "layout_configs": plan_result.get("layers"),
            }

        # 附加三路对比结果（sanitize inf/nan → None 以确保 JSON 兼容）
        if comparison:
            response["comparison"] = comparison

        return _sanitize_floats(response)

    except Exception as e:
        logger.error(f"[GIS Test] jintian-pipeline failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


async def _run_pipeline_path(
    request: "JinTianPipelineRequest",
    path_name: str,
    intent_resolver: Any,
    gis_data: Dict[str, Any],
    planned_data: Dict[str, Any],
    village_name: str,
) -> Dict[str, Any]:
    """执行单条 pipeline 路径：PARSE → KG → CONFLICT → ALLOCATE → GENERATE。

    Args:
        path_name: "gen" (人工规划文本) 或 "plan" (L3系统报告)
        intent_resolver: 返回 intent dict 的可调用对象（加密钥缓存命中/LLM 解析）
        gis_data: load_all() 产出的全部 GIS 数据
        planned_data: load_planned() 产出的 planned/ 数据
        village_name: 村名
    """
    from app.services.modules.gis.layout.metrics_calculator import GISMetricsCalculator

    result: Dict[str, Any] = {}

    # ── Step 1: 解析 intent ───────────────────────────────────────
    # gen 路径: 加载 data/gis/jintian/planning_text/金田村委会.md → LLM 解析
    # plan 路径: 加载 output/.../layer3_reports.json → LLM 解析
    # 均注入 GIS 实测约束（建设用地上限/耕地保有量下限/生态红线）到 prompt
    try:
        intent = intent_resolver()
        parse_source = intent.get("metadata", {}).get("source", f"{path_name}_cached")
        result["parse_source"] = parse_source
        result["intent"] = intent
    except Exception as e:
        logger.warning(f"[{path_name}] Intent resolution failed: {e}")
        result["parse_source"] = "failed"
        result["intent"] = {"zones": [], "facilities": [], "axes": [], "constraints": []}

    # 如果用户提供了自定义规划文本且开启 use_llm，用实时 LLM 覆盖缓存
    if request.use_llm and request.planning_text:
        try:
            from app.tools.gis.parse import parse_text_via_llm
            llm_intent = parse_text_via_llm(
                text=request.planning_text,
                village_name=village_name,
                gis_data=gis_data,
            )
            if llm_intent.get("zones"):
                result["intent"] = llm_intent
                result["parse_source"] = f"{path_name}_llm_live"
        except Exception as e:
            logger.warning(f"[{path_name}] Live LLM parsing failed: {e}")

    intent = result["intent"]

    # ── Step 2: 构建 KG（注入 GIS 实测约束）───────────────────────
    # GIS 实测约束作为最高优先级数据源注入 RDF 三元组：
    #   (pln:金田村委会, pln:constructionCap_ha, 21.66)  — 建设用地面积上限
    #   (pln:金田村委会, pln:farmlandMin_ha, 98.54)       — 耕地保有量下限
    #   (pln:金田村委会, pln:ecologicalMin_ha, 2232.66)   — 生态保护红线面积下限
    kg_info = None
    kg_constraints: List[Dict[str, Any]] = []
    kg = None
    try:
        from app.services.modules.gis.kg import PlanningKG
        landuse_geojson = gis_data.get("landuse_current_geojson")
        kg = PlanningKG(village_name=village_name)
        kg.build_from_intent(
            intent=intent,
            landuse_geojson=landuse_geojson,
            gis_data=gis_data,
        )
        kg_constraints = kg.get_constraints()
        kg_info = {
            "triple_count": kg.get_triple_count(),
            "constraint_count": len(kg_constraints),
        }
    except Exception as e:
        kg_info = {"error": str(e)}
    result["kg"] = kg_info

    # ── Step 3: 冲突检测 & 消解 ───────────────────────────────────
    # 检测三类冲突：
    #   (a) 指标冲突 — 多维度对同一概念给出不同数值（e.g., 建设用地在 dim_a=30ha, dim_b=25ha）
    #   (b) 约束违规 — 规划值超出 GIS 实测约束（e.g., 规划建设用地 50ha > 实测上限 21.66ha）
    #   (c) 空间冲突 — 不同维度对空间结构定义不一致
    conflict_info = None
    try:
        from app.services.modules.gis.conflict.detector import ConflictDetector
        from app.services.modules.gis.conflict.resolver import ConflictResolver
        summaries = GISMetricsCalculator.compute_summaries(gis_data)
        conflict_report = ConflictDetector().detect_all(summaries)
        resolution_report = ConflictResolver().resolve(conflict_report)
        conflict_info = {
            "metric_conflicts": len(conflict_report.metric_conflicts) if hasattr(conflict_report, 'metric_conflicts') else 0,
            "constraint_violations": len(conflict_report.constraint_violations) if hasattr(conflict_report, 'constraint_violations') else 0,
            "resolved_values": resolution_report.resolved_values if hasattr(resolution_report, 'resolved_values') else {},
        }
    except Exception as e:
        conflict_info = {"error": str(e)}
    result["conflict"] = conflict_info

    # ── Step 4: MIP 分配 ──────────────────────────────────────────
    # 将 intent 中的 area_ratio 目标转换为实际公顷数 → PuLP 线性规划求解
    # MIP 目标函数: 最小化 (面积偏差 + DLBM 变更惩罚 + 邻接奖励)
    # 硬约束: 受保护地类（基本农田/水域/生态林）不可划入建设区
    allocated_geojson = None
    try:
        from app.services.modules.gis.optimizer.mip_allocator import MIPZoneAllocator
        metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
        total_area_ha = metrics["total_area_ha"]

        # 将 area_ratio (0.0-1.0) 转换为实际公顷目标
        targets = {}
        for z in intent.get("zones", []):
            lu = z.get("land_use", "")
            ratio = z.get("area_ratio", 0)
            if lu and ratio:
                targets[lu] = ratio * total_area_ha

        if targets and landuse_geojson:
            allocator = MIPZoneAllocator()
            allocated_geojson, mip_trace = allocator.solve(
                landuse_geojson=landuse_geojson,
                targets=targets,
                constraints=kg_constraints if kg_constraints else None,
                kg=kg,
            )
            result["allocation"] = {
                "mode": mip_trace.get("mode", "unknown"),
                "changed_pct": mip_trace.get("changed_pct", 0),
                "solver_status": mip_trace.get("solver_status", "unknown"),
            }
        else:
            result["allocation"] = {"mode": "skipped", "reason": "no targets or landuse data"}
    except Exception as e:
        logger.warning(f"[{path_name}] Allocation failed: {e}")
        result["allocation"] = {"mode": "failed", "error": str(e)}

    # ── Step 5: 生成图层 ──────────────────────────────────────────
    # 4 层 GIS 图层：
    #   function_zone  — 功能分区（ZoneGenerator: DLBM→6类合并→面积约束→CA 精化）
    #   planning_zone  — 规划分区（DLBM→4类：农田保护区/村庄建设区/生态保护区/一般农业区）
    #   facility_point — 设施布点（FacilityPlacer: 4策略布点）
    #   infrastructure — 发展轴线（AxisBuilder: 一核一带三区）
    from app.tools.gis.generate import (
        _generate_function_zones,
        _make_planning_zone_layer,
        _generate_facilities,
        _generate_axes,
    )

    layers: List[Dict[str, Any]] = []
    fz = _generate_function_zones(intent, gis_data)
    if fz:
        layers.append(fz)
    # 使用分配后的 GeoJSON（如果有），否则使用原始 landuse
    pz = _make_planning_zone_layer(allocated_geojson, gis_data)
    if pz:
        layers.append(pz)
    fp = _generate_facilities(intent, gis_data)
    if fp:
        layers.append(fp)
    ax = _generate_axes(intent, gis_data)
    if ax:
        layers.append(ax)

    result["layers"] = layers
    result["layer_summary"] = [
        {
            "layerType": lyr.get("layerType"),
            "feature_count": len(lyr.get("data", {}).get("features", [])),
        }
        for lyr in layers
    ]

    return result


def _build_three_way_comparison(
    gen_result: Optional[List[Dict[str, Any]]],
    plan_result: Optional[List[Dict[str, Any]]],
    planned_data: Dict[str, Any],
    gis_data: Dict[str, Any],
) -> Dict[str, Any]:
    """构建三路对比报告。

    对比维度:
      1. gen vs planned/ : 「AI 解读人工规划文本」vs「人工绘制图纸」
         — 测试 AI 能否准确理解人类规划师的规划文档
      2. plan vs planned/ : 「AI 基于 L3 报告生成」vs「人工绘制图纸」
         — 测试 Agent pipeline L3 报告产出能否匹配人工经验
      3. gen vs plan      : 「人工文本路径」vs「L3 报告路径」
         — 测试两条 AI 路径输出的一致性（同一套规划理念，不同输入源）

    返回值结构:
      {
        "gen_vs_planned": {ComparisonReport.to_dict()},
        "plan_vs_planned": {ComparisonReport.to_dict()},
        "gen_vs_plan": {ComparisonReport.to_dict()},
      }
    """
    from app.services.modules.gis.layout.compare_layouts import compare

    # 提取保护区域（用于对比中的合规检查）
    protection = {}
    for key, name in [
        ("farmland_protection_geojson", "farmland"),
        ("ecological_protection_geojson", "ecological"),
        ("historical_protection_geojson", "historical"),
    ]:
        val = gis_data.get(key)
        if val and val.get("features"):
            protection[name] = val

    comparison: Dict[str, Any] = {}

    # ── 对比 1: gen layers vs planned/ ──
    # 「AI 解读人工规划文本」vs「人类绘制的规划图纸」
    if gen_result and planned_data:
        report = compare(gen_result, planned_data, protection if protection else None)
        comparison["gen_vs_planned"] = report.to_dict()

    # ── 对比 2: plan layers vs planned/ ──
    # 「AI 基于 L3 报告生成」vs「人类绘制的规划图纸」
    if plan_result and planned_data:
        report = compare(plan_result, planned_data, protection if protection else None)
        comparison["plan_vs_planned"] = report.to_dict()

    # ── 对比 3: gen layers vs plan layers ──
    # 两条 AI 路径一致性 — 将 plan layers 作为"模拟 planned/"对比
    # 如果 gen 路径产出的图层与 plan 路径高一致，说明两条路径都可靠
    if gen_result and plan_result:
        # 构造 plan layers 为"伪 planned"数据
        plan_landuse = None
        for lyr in plan_result:
            if lyr.get("layerType") == "planning_zone":
                plan_landuse = lyr.get("data")
                break
        if plan_landuse:
            fake_planned = {"landuse_planned_geojson": plan_landuse}
            report = compare(gen_result, fake_planned, protection if protection else None)
            comparison["gen_vs_plan"] = report.to_dict()

    return comparison
