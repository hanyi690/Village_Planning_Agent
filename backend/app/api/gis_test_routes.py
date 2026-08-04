"""GIS Dev API — 8 endpoints for development/testing.

Production should disable this router. Each endpoint wraps GIS services
for the frontend test-gis page.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Dev data helpers (replace legacy gis.data.loader; remove when routes are rewritten) ──
from app.modules.data.catalog.catalog import DataCatalog
from app.modules.data.documents.loader import load_planning_text


def load_all(village_name: str = "金田村委会") -> Dict[str, Any]:
    """Dev helper: load village GIS data as raw dict."""
    bundle = DataCatalog().load_village_bundle(village_name)
    return bundle.to_geojson_dict()


def load_planned() -> Dict[str, Any]:
    """Dev helper: load planned layers as raw dict."""
    return load_all("金田村委会")


class PlanningTextLoader:
    """Dev compat for legacy PlanningTextLoader."""

    @staticmethod
    def load_village_planning_markdown(village_name: str) -> str:
        return load_planning_text(village_name) or ""


def _get_village_params(gis_data: Dict[str, Any]) -> Dict[str, str]:
    """Inline replacement for the deprecated get_village_params helper."""
    from app.tools.gis._analytics.metrics_calculator import GISMetricsCalculator

    metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
    total_area = str(round(metrics["total_area_ha"], 2))
    zone_areas = metrics.get("zone_areas", {})
    sorted_zones = sorted(zone_areas.items(), key=lambda x: -x[1])
    top_zones = [z for z, _ in sorted_zones[:3]]
    zone_names = {
        "农业用地": "农业用地", "生态绿地": "林地", "居住用地": "居民点",
        "水域": "水域", "交通用地": "交通", "产业用地": "产业",
        "公共服务用地": "公服", "商业用地": "商业",
    }
    descriptions = [zone_names.get(z, z) for z in top_zones]
    land_use_description = (
        descriptions[0] + "为主，含" + "、".join(descriptions[1:]) if descriptions else "未知"
    )
    return {
        "total_area": total_area,
        "land_use_description": land_use_description,
        "village_name": "金田村委会",
    }


def _get_data_summary(gis_data: Dict[str, Any]) -> Dict[str, Any]:
    """Inline replacement for the deprecated get_data_summary helper."""
    summary: Dict[str, Any] = {}
    for key, geojson in gis_data.items():
        if not isinstance(geojson, dict) or "features" not in geojson:
            continue
        feats = geojson.get("features", [])
        geom_types: Dict[str, int] = {}
        for f in feats:
            gt = f.get("geometry", {}).get("type", "None")
            geom_types[gt] = geom_types.get(gt, 0) + 1
        summary[key] = {"feature_count": len(feats), "geometry_types": geom_types}
    return summary


def _report_content_text(parsed: Dict[str, Any]) -> str:
    """Extract planning text from a dimension report record."""
    content = parsed.get("content", "")
    if content:
        return str(content)
    summary = parsed.get("summary", {}) or {}
    return str(summary.get("text_summary", "") or "")


async def _resolve_intent_via_parse(village_name: str, planning_text: str = "") -> Any:
    """Resolve a spatial intent via the PARSE Agent (deterministic rule-based).

    Returns a SpatialPlanningIntent (app.modules.schema.contracts.parse_contracts).
    """
    from app.agent.select.parse_agent import parse_async

    text = planning_text or ""
    if not text:
        text = load_planning_text(village_name) or ""
    result = await parse_async(planning_text=text, village_name=village_name)
    return result.intent


router = APIRouter(prefix="/api/dev/gis", tags=["GIS Dev"])

# ── Color injection (shared by /analysis and /zones) ──────────────

from app.modules.schema.encodings.code_sets import get_zone_type_for_dlbm
from app.modules.schema import (
    get_zone_color, ZONE_TYPE_COLORS,
    PLANNING_ZONE_COLORS, DEFAULT_ZONE_COLOR,
)
from app.modules.schema.output.colors import (
    SENSITIVITY_COLORS, FACILITY_TYPE_COLORS, INFRA_COLORS,
    ISOCHRONE_COLORS, get_facility_color, get_infra_color,
)


def inject_feature_colors(geojson: Dict[str, Any], layer_type: str) -> Dict[str, Any]:
    """Inject per-feature color/stroke properties based on DLBM/zone_type/sensitivity_level."""
    if not geojson or "features" not in geojson:
        return geojson
    for feat in geojson["features"]:
        props = feat.get("properties", {})
        if layer_type == "function_zone":
            dlbm = props.get("DLBM", "")
            zone_type = props.get("zone_type", "") or get_zone_type_for_dlbm(dlbm)
            color = get_zone_color(zone_type)
            props.setdefault("fill", color.get("fill", DEFAULT_ZONE_COLOR.get("fill", "#AAAAAA")))
            props.setdefault("stroke", color.get("stroke", "#333333"))
        elif layer_type == "planning_zone":
            zone_name = props.get("zone_type", "")
            color = PLANNING_ZONE_COLORS.get(zone_name, DEFAULT_ZONE_COLOR)
            props.setdefault("fill", color.get("fill", "#AAAAAA"))
            props.setdefault("stroke", color.get("stroke", "#333333"))
        elif layer_type == "sensitivity":
            level = props.get("sensitivity_level", "")
            color = SENSITIVITY_COLORS.get(level, {})
            props.setdefault("fill", color.get("fill", "#AAAAAA"))
        elif layer_type == "facility":
            ftype = props.get("facility_type", "")
            color = get_facility_color(ftype)
            props.setdefault("fill", color.get("fill", "#FF6B6B"))
    return geojson


def _sanitize_floats(obj: Any) -> Any:
    """Replace NaN/Inf with None for JSON serialization."""
    import math
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


# ════════════════════════════════════════════════════════════════
# Request Models (5 models, down from 12)
# ════════════════════════════════════════════════════════════════

class DataRequest(BaseModel):
    """Data acquisition — unified center/bbox/coverage."""
    location: str = "金田村委会"
    buffer_km: float = 5.0
    include: List[str] = Field(default_factory=lambda: ["center", "bbox", "coverage", "data"])

class AnalysisRequest(BaseModel):
    """Spatial analysis — isochrone/accessibility/poi."""
    analysis_type: str = "isochrone"  # isochrone | accessibility | poi
    center: List[float] = Field(default=[116.044146, 24.818629])
    time_minutes: List[int] = Field(default=[5, 10, 15])
    travel_mode: str = "walk"
    keyword: str = "学校"
    radius: int = 2000
    page_size: int = 20

class ValidateRequest(BaseModel):
    """Validation — layout/facility/ecological/constraint/hazard."""
    validation_type: str = "layout"  # layout | facility | ecological | constraint | hazard
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)
    facility_type: str = "公共服务设施"
    location: List[float] = Field(default=[116.044146, 24.818629])
    constraints: Optional[List[Dict[str, Any]]] = None
    buffer_meters: float = 200.0
    use_jintian_data: bool = False

class LayoutRequest(BaseModel):
    """Layout generation — spatial-layout/pipeline/landuse-change."""
    village_name: str = "金田村委会"
    run_path: str = "gen"  # gen | plan | both
    intent: Optional[Dict[str, Any]] = None
    compare_to_planned: bool = False
    include_validation: bool = False
    include_landuse_change: bool = False
    use_llm: bool = False
    planning_text: Optional[str] = None
    export: bool = True
    render: bool = True
    output_dir: Optional[str] = None

class IntentRequest(BaseModel):
    """Intent parsing — text → UnifiedSpatialIntent."""
    village_name: str = "金田村委会"
    planning_text: Optional[str] = None
    use_db_reports: bool = False
    use_jintian_reports: bool = False
    custom_text: Optional[str] = None


# ════════════════════════════════════════════════════════════════
# 1. GET /status
# ════════════════════════════════════════════════════════════════

@router.get("/status", summary="Check GIS service availability")
async def gis_status():
    """Check which GIS services and dependencies are available."""
    from app.core.settings import TIANDITU_API_KEY, AMAP_API_KEY
    status = {
        "tianditu": bool(TIANDITU_API_KEY),
        "amap": bool(AMAP_API_KEY),
        "spatial": False,
    }
    try:
        import shapely
        status["spatial"] = True
    except ImportError:
        pass
    try:
        import osmnx
        status["osmnx"] = True
    except ImportError:
        status["osmnx"] = False
    return status


# ════════════════════════════════════════════════════════════════
# 2. POST /data
# ════════════════════════════════════════════════════════════════

@router.post("/data", summary="Fetch GIS data with center/bbox/coverage")
async def gis_data(request: DataRequest):
    """Unified data endpoint — fetch, center, bbox, coverage in one call."""
    t0 = time.time()
    result: Dict[str, Any] = {"success": True}
    try:
        gis_data = load_all(request.location)
        result["data_summary"] = _get_data_summary(gis_data)

        if "data" in request.include:
            result["gis_data"] = {k: v for k, v in gis_data.items() if k.endswith("_geojson")}

        if "center" in request.include or "bbox" in request.include:
            params = _get_village_params(gis_data)
            if "center" in request.include:
                result["center"] = params.get("center")
            if "bbox" in request.include:
                result["bbox"] = params.get("bbox")

        if "coverage" in request.include:
            from app.tools.gis._analytics.coverage import calculate_coverage
            result["coverage"] = calculate_coverage(gis_data)

        result["timing_ms"] = round((time.time() - t0) * 1000)
        return _sanitize_floats(result)
    except Exception as e:
        logger.error(f"[GIS] /data failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ════════════════════════════════════════════════════════════════
# 3. POST /analysis
# ════════════════════════════════════════════════════════════════

@router.post("/analysis", summary="Spatial analysis (isochrone/accessibility/poi)")
async def gis_analysis(request: AnalysisRequest):
    """Unified analysis endpoint — isochrone, accessibility, or POI search."""
    t0 = time.time()
    try:
        if request.analysis_type == "isochrone":
            from app.tools.gis._analytics.isochrone import generate_isochrones
            result = generate_isochrones(
                center=request.center,
                time_minutes=request.time_minutes,
                travel_mode=request.travel_mode,
            )
            return _sanitize_floats({"success": True, "isochrones": result, "timing_ms": round((time.time() - t0) * 1000)})

        elif request.analysis_type == "accessibility":
            from app.tools.gis._analytics.accessibility import analyze_accessibility
            result = analyze_accessibility(center=request.center)
            return _sanitize_floats({"success": True, "accessibility": result, "timing_ms": round((time.time() - t0) * 1000)})

        elif request.analysis_type == "poi":
            from app.modules.data.providers.poi import POIProvider
            result = POIProvider.search_poi_nearby(
                keyword=request.keyword,
                center=tuple(request.center),
                radius=request.radius,
                page_size=request.page_size,
            )
            return {"success": result.get("success", True), "pois": result.get("pois", []), "timing_ms": round((time.time() - t0) * 1000)}

        else:
            return {"success": False, "error": f"Unknown analysis_type: {request.analysis_type}"}
    except Exception as e:
        logger.error(f"[GIS] /analysis failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ════════════════════════════════════════════════════════════════
# 4. POST /validate
# ════════════════════════════════════════════════════════════════

@router.post("/validate", summary="Validation (layout/facility/ecological/constraint/hazard)")
async def gis_validate(request: ValidateRequest):
    """Unified validation endpoint."""
    t0 = time.time()
    try:
        if request.validation_type == "layout":
            return await _validate_layout(request, t0)
        elif request.validation_type == "facility":
            return await _validate_facility(request, t0)
        elif request.validation_type == "ecological":
            return await _validate_ecological(request, t0)
        elif request.validation_type == "constraint":
            return await _validate_constraint(request, t0)
        elif request.validation_type == "hazard":
            return await _validate_hazard(request, t0)
        else:
            return {"success": False, "error": f"Unknown validation_type: {request.validation_type}"}
    except Exception as e:
        logger.error(f"[GIS] /validate failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


async def _validate_layout(request: ValidateRequest, t0: float) -> Dict[str, Any]:
    from app.tools.gis._validation.layout_validator import LayoutValidator

    layout_configs = request.layout_configs

    # Mode 2: generate from jintian data then validate
    if request.use_jintian_data and not layout_configs:
        from app.tools.gis._generation.pipeline import run_layout_pipeline

        gis_data = load_all()
        intent = await _resolve_intent_via_parse("金田村委会")

        pipeline_result = await asyncio.to_thread(
            run_layout_pipeline, intent, gis_data, run_export=False, run_render=False,
        )
        layout_configs = pipeline_result.get("layers", [])

    if not layout_configs:
        return {"success": False, "error": "No layout_configs provided", "timing_ms": round((time.time() - t0) * 1000)}

    validator = LayoutValidator()
    report = await asyncio.to_thread(validator.validate, layout_configs, request.constraints)

    checks_detail = [
        {
            "name": c.check_name,
            "passed": c.passed,
            "violation_count": c.violation_count,
            "violations": [{"check": v.check, "severity": v.severity, "message": v.message} for v in c.violations],
        }
        for c in report.checks
    ]

    return _sanitize_floats({
        "success": True,
        "validation": report.to_dict(),
        "checks": checks_detail,
        "timing_ms": round((time.time() - t0) * 1000),
    })


async def _validate_facility(request: ValidateRequest, t0: float) -> Dict[str, Any]:
    from app.tools.gis._validation.facility_validator import validate_facility_location
    result = validate_facility_location(
        facility_type=request.facility_type,
        location=request.location,
    )
    return _sanitize_floats({"success": True, "validation": result, "timing_ms": round((time.time() - t0) * 1000)})


async def _validate_ecological(request: ValidateRequest, t0: float) -> Dict[str, Any]:
    from app.tools.gis._validation.facility_validator import assess_ecological_sensitivity
    result = assess_ecological_sensitivity(request.location)
    return _sanitize_floats({"success": True, "sensitivity": result, "timing_ms": round((time.time() - t0) * 1000)})


async def _validate_constraint(request: ValidateRequest, t0: float) -> Dict[str, Any]:
    from app.tools.gis._analytics.metrics_calculator import GISMetricsCalculator
    from app.tools.gis._conflict.detector import ConflictDetector

    gis_data = load_all()
    summaries = GISMetricsCalculator.compute_summaries(gis_data)
    conflict_report = ConflictDetector().detect_all(summaries)
    return _sanitize_floats({
        "success": True,
        "conflicts": {
            "metric_conflicts": len(conflict_report.metric_conflicts) if hasattr(conflict_report, "metric_conflicts") else 0,
            "constraint_violations": len(conflict_report.constraint_violations) if hasattr(conflict_report, "constraint_violations") else 0,
        },
        "timing_ms": round((time.time() - t0) * 1000),
    })


async def _validate_hazard(request: ValidateRequest, t0: float) -> Dict[str, Any]:
    from app.tools.gis._validation.facility_validator import SPATIAL_AVAILABLE

    gis_data = load_all()
    hazard_geojson = gis_data.get("hazard_geojson")
    if not hazard_geojson:
        return {"success": False, "error": "No hazard data available", "timing_ms": round((time.time() - t0) * 1000)}

    buffer_geojson = None
    if SPATIAL_AVAILABLE:
        from shapely.geometry import shape
        from shapely.ops import unary_union
        import numpy as np

        buffered = []
        for feat in hazard_geojson.get("features", []):
            try:
                geom = shape(feat.get("geometry", {}))
                if not geom.is_empty:
                    buffered.append(geom.buffer(request.buffer_meters / 111320))
            except Exception:
                continue
        if buffered:
            union = unary_union(buffered)
            from shapely.geometry.mapping import mapping
            buffer_geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(union), "properties": {"buffer_m": request.buffer_meters}}]}

    return _sanitize_floats({
        "success": True,
        "hazard_count": len(hazard_geojson.get("features", [])),
        "buffer_geojson": buffer_geojson,
        "timing_ms": round((time.time() - t0) * 1000),
    })


# ════════════════════════════════════════════════════════════════
# 5. POST /layout
# ════════════════════════════════════════════════════════════════

@router.post("/layout", summary="Generate spatial layout (full pipeline)")
async def gis_layout(request: LayoutRequest):
    """Run the spatial layout pipeline — gen/plan/both paths with optional comparison."""
    t0 = time.time()
    try:
        from app.tools.gis._generation.pipeline import run_layout_pipeline, build_three_way_comparison

        gis_data = load_all(request.village_name)
        planned_data = load_planned() if request.compare_to_planned else {}

        gen_result: Dict[str, Any] = {}
        plan_result: Dict[str, Any] = {}

        # Resolve intent and run pipeline for each path
        for path_name in (["gen", "plan"] if request.run_path == "both" else [request.run_path]):
            try:
                if request.use_llm or path_name == "gen":
                    intent = await _resolve_intent_via_parse(
                        request.village_name, planning_text=request.planning_text or "",
                    )
                else:
                    intent = await _resolve_intent_via_parse(request.village_name)
            except Exception as e:
                logger.warning(f"[{path_name}] Intent resolution failed: {e}")
                from app.agent.select.parse_agent import parse_async as _empty_parse
                intent = (await _empty_parse(planning_text="", village_name=request.village_name)).intent

            pipeline_result = await asyncio.to_thread(
                run_layout_pipeline,
                intent, gis_data, request.village_name,
                run_export=request.export,
                run_render=request.render,
                output_dir=request.output_dir,
            )
            pipeline_result["parse_source"] = "parse_agent"
            pipeline_result["intent"] = intent.model_dump() if hasattr(intent, "model_dump") else intent

            if path_name == "gen":
                gen_result = pipeline_result
            else:
                plan_result = pipeline_result

        # Three-way comparison
        comparison = None
        if request.compare_to_planned:
            comparison = build_three_way_comparison(
                gen_layers=gen_result.get("layers"),
                plan_layers=plan_result.get("layers"),
                planned_data=planned_data,
                gis_data=gis_data,
            )

        # Optional: landuse change
        landuse_change = None
        if request.include_landuse_change:
            current = gis_data.get("landuse_current_geojson")
            planned = gis_data.get("landuse_planned_geojson")
            if current and planned:
                current = inject_feature_colors(current, "function_zone")
                planned = inject_feature_colors(planned, "planning_zone")
                current_dlbm = {f.get("properties", {}).get("DLBM") for f in current.get("features", []) if f.get("properties", {}).get("DLBM")}
                planned_dlbm = {f.get("properties", {}).get("DLBM") for f in planned.get("features", []) if f.get("properties", {}).get("DLBM")}
                landuse_change = {
                    "current_parcels": len(current.get("features", [])),
                    "planned_parcels": len(planned.get("features", [])),
                    "added_dlbm": list(planned_dlbm - current_dlbm),
                    "removed_dlbm": list(current_dlbm - planned_dlbm),
                }

        # Optional: validation
        validation = None
        if request.include_validation:
            from app.tools.gis._validation.layout_validator import LayoutValidator
            layers = gen_result.get("layers") or plan_result.get("layers") or []
            if layers:
                validator = LayoutValidator()
                report = await asyncio.to_thread(validator.validate, layers)
                validation = report.to_dict()

        # Build response
        response: Dict[str, Any] = {"success": True, "timing_ms": round((time.time() - t0) * 1000)}
        if gen_result:
            response["gen"] = gen_result
        if plan_result:
            response["plan"] = plan_result
        if comparison:
            response["comparison"] = comparison
        if landuse_change:
            response["landuse_change"] = landuse_change
        if validation:
            response["validation"] = validation

        return _sanitize_floats(response)
    except Exception as e:
        logger.error(f"[GIS] /layout failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ════════════════════════════════════════════════════════════════
# 6. POST /intent
# ════════════════════════════════════════════════════════════════

@router.post("/intent", summary="Parse planning text to spatial intent")
async def gis_intent(request: IntentRequest):
    """Parse planning text → UnifiedSpatialIntent."""
    t0 = time.time()
    try:
        # Option 1: DB reports
        if request.use_db_reports:
            from app.services.report_store import ReportStore
            from app.database.engine import get_async_session
            from sqlalchemy import text

            store = ReportStore()
            async with get_async_session() as db:
                result = await db.execute(text("""
                    SELECT session_id FROM dimension_reports
                    WHERE layer=3 GROUP BY session_id
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
                    "summary": {"metrics": parsed.get("metrics", {}), "key_points": parsed.get("key_points", []), "text_summary": parsed.get("text_summary", "")},
                    "content": parsed.get("text_summary", ""),
                }

            reports_text = "\n\n".join(
                f"[{dk}]\n{_report_content_text(p)}"
                for dk, p in reports.items()
            )
            parse_result = await _resolve_intent_via_parse(
                request.village_name, planning_text=reports_text,
            )
            intent_json = parse_result.model_dump()
            return _sanitize_floats({"success": True, "intent": intent_json, "source": "db_l3", "timing_ms": round((time.time() - t0) * 1000)})

        # Option 2/3: Text-based
        planning_text = request.planning_text or request.custom_text
        if not planning_text and request.use_jintian_reports:
            planning_text = PlanningTextLoader.load_village_planning_markdown(request.village_name)

        if not planning_text:
            return {"success": False, "error": "No planning text provided", "timing_ms": round((time.time() - t0) * 1000)}

        parse_result = await _resolve_intent_via_parse(
            request.village_name, planning_text=planning_text,
        )
        intent = parse_result.model_dump()
        return _sanitize_floats({"success": True, "intent": intent, "source": "parse_agent", "timing_ms": round((time.time() - t0) * 1000)})

    except Exception as e:
        logger.error(f"[GIS] /intent failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ════════════════════════════════════════════════════════════════
# 7. POST /zones
# ════════════════════════════════════════════════════════════════

class ZonesRequest(BaseModel):
    zone_type: str = "land_use"  # land_use | space_control
    village_name: str = "金田村委会"

@router.post("/zones", summary="Generate zones (land-use V/N/E or space-control)")
async def gis_zones(request: ZonesRequest):
    """Generate V/N/E land-use zones or space-control zones."""
    t0 = time.time()
    try:
        gis_data = load_all(request.village_name)

        if not gis_data or not gis_data.get("boundary_geojson"):
            return {"success": False, "error": "GIS data not loaded", "timing_ms": round((time.time() - t0) * 1000)}

        if request.zone_type == "land_use":
            from app.tools.gis._generation.land_use_zone_generator import LandUseZoneGenerator, VNE_CATEGORIES
            generator = LandUseZoneGenerator()
            geojson = generator.generate(
                boundary=gis_data.get("boundary_geojson"),
                current_landuse=gis_data.get("landuse_current_geojson"),
                planned_landuse=gis_data.get("landuse_planned_geojson"),
            )
            return _sanitize_floats({
                "success": True,
                "zone_type": "land_use",
                "categories": VNE_CATEGORIES,
                "geojson": geojson,
                "feature_count": len(geojson.get("features", [])) if geojson else 0,
                "timing_ms": round((time.time() - t0) * 1000),
            })

        elif request.zone_type == "space_control":
            from app.tools.gis._generation.space_control_generator import SpaceControlZoneGenerator, SPACE_CONTROL_ZONES
            from app.modules.schema.output.colors import SPACE_CONTROL_COLORS

            generator = SpaceControlZoneGenerator()
            geojson = generator.generate(
                boundary=gis_data.get("boundary_geojson"),
                farmland_protection=gis_data.get("farmland_protection_geojson"),
                ecological_protection=gis_data.get("ecological_protection_geojson"),
                current_landuse=gis_data.get("landuse_current_geojson"),
            )
            definitions = {code: {"name": info["name"], "description": info["description"], "color": SPACE_CONTROL_COLORS.get(code, {})} for code, info in SPACE_CONTROL_ZONES.items()}
            return _sanitize_floats({
                "success": True,
                "zone_type": "space_control",
                "definitions": definitions,
                "geojson": geojson,
                "feature_count": len(geojson.get("features", [])) if geojson else 0,
                "timing_ms": round((time.time() - t0) * 1000),
            })

        else:
            return {"success": False, "error": f"Unknown zone_type: {request.zone_type}"}
    except Exception as e:
        logger.error(f"[GIS] /zones failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "timing_ms": round((time.time() - t0) * 1000)}


# ════════════════════════════════════════════════════════════════
# 8. GET /files/{path}
# ════════════════════════════════════════════════════════════════

@router.get("/files", summary="List available GIS data files")
async def list_files():
    """List GeoJSON files in jintian_boundary directory."""
    from app.core.settings import JINTIAN_GIS_DIR
    data_dir = JINTIAN_GIS_DIR
    if not data_dir.exists():
        return {"files": [], "count": 0}
    files = sorted(f.name for f in data_dir.glob("*.geojson"))
    return {"files": files, "count": len(files)}


@router.get("/files/{filepath:path}", summary="Get GIS data file")
async def get_file(filepath: str):
    """Return a specific GeoJSON file from jintian data directory."""
    from app.core.settings import JINTIAN_GIS_DIR
    full_path = JINTIAN_GIS_DIR / filepath
    if not full_path.exists():
        return {"error": f"File not found: {filepath}"}
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
