"""
GIS Test API - GIS 工具测试端点

提供独立测试接口，供前端 test-gis 页面调用。
使用金田村真实数据替代硬编码矩形。
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.tools.core import (
    VillagePlanningScheme,
    PlanningZone,
    FacilityPoint,
    DevelopmentAxis,
    generate_spatial_layout_from_json,
)
from src.tools.core.planning_schema import LocationBias, AdjacencyRule
from src.tools.core.boundary_fallback import generate_proxy_boundary_with_fallback
from src.config.boundary_fallback import BoundaryFallbackConfig

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================
# Test Data Constants
# ============================================

# Test center coordinates for Jintian Village (WGS84)
JINTIAN_TEST_CENTER = (116.044146, 24.818629)

# Cached test data
_TEST_DATA_CACHE: Optional[tuple] = None


# ============================================
# Request/Response Models
# ============================================

class SpatialLayoutTestRequest(BaseModel):
    """空间布局测试请求"""
    village_name: Optional[str] = Field(default="金田村委会", max_length=50)
    planning_scheme: Optional[dict] = Field(default=None, description="自定义规划方案")
    use_real_data: bool = Field(default=True, description="使用真实金田村数据")


class SpatialLayoutTestResponse(BaseModel):
    """空间布局测试响应"""
    success: bool
    geojson: Optional[dict] = None
    zones_geojson: Optional[dict] = None
    facilities_geojson: Optional[dict] = None
    axes_geojson: Optional[dict] = None
    statistics: Optional[dict] = None
    center: Optional[list] = None
    data_source: Optional[str] = None
    error: Optional[str] = None


class BoundaryFallbackTestRequest(BaseModel):
    """边界兜底测试请求"""
    village_name: Optional[str] = Field(default="金田村委会", max_length=50)
    skip_user_upload: bool = Field(default=True, description="跳过用户上传策略")
    force_bbox: bool = Field(default=False, description="强制使用 bbox_buffer")


class BoundaryFallbackTestResponse(BaseModel):
    """边界兜底测试响应"""
    success: bool
    geojson: Optional[dict] = None
    strategy_used: Optional[str] = None
    fallback_history: Optional[list] = None
    warnings: Optional[list] = None
    stats: Optional[dict] = None
    error: Optional[str] = None


class IsochroneTestRequest(BaseModel):
    """等时圈测试请求"""
    center: List[float] = Field(default=[116.044146, 24.818629], description="中心坐标 [lon, lat]")
    time_minutes: List[int] = Field(default=[5, 10, 15], description="等时圈时间范围")
    travel_mode: str = Field(default="walk", description="出行方式: walk/drive")


class IsochroneTestResponse(BaseModel):
    """等时圈测试响应"""
    success: bool
    geojson: Optional[dict] = None
    center: Optional[list] = None
    travel_mode: Optional[str] = None
    error: Optional[str] = None


class AccessibilityTestRequest(BaseModel):
    """可达性测试请求"""
    origin: Optional[List[float]] = Field(default=None, description="起点坐标")
    destinations: Optional[List[List[float]]] = Field(default=None, description="目的地坐标列表")
    analysis_type: str = Field(default="service_coverage", description="分析类型")


class AccessibilityTestResponse(BaseModel):
    """可达性测试响应"""
    success: bool
    coverage_rate: Optional[float] = None
    reachable_count: Optional[int] = None
    geojson: Optional[dict] = None
    summary: Optional[dict] = None
    error: Optional[str] = None


class POISearchTestRequest(BaseModel):
    """POI搜索测试请求"""
    keyword: str = Field(default="学校", description="搜索关键词")
    region: Optional[str] = Field(default="金田村", description="搜索区域")
    center: Optional[List[float]] = Field(default=None, description="中心坐标")
    radius: Optional[int] = Field(default=3000, description="搜索半径")


class POISearchTestResponse(BaseModel):
    """POI搜索测试响应"""
    success: bool
    pois: Optional[List[dict]] = None
    total_count: Optional[int] = None
    geojson: Optional[dict] = None
    source: Optional[str] = None
    error: Optional[str] = None


class GISCoverageTestRequest(BaseModel):
    """GIS覆盖率测试请求"""
    location: str = Field(default="金田村", description="位置名称")
    buffer_km: float = Field(default=5.0, description="缓冲区半径")


class GISCoverageTestResponse(BaseModel):
    """GIS覆盖率测试响应"""
    success: bool
    location: Optional[str] = None
    coverage_rate: Optional[float] = None
    layers_available: Optional[dict] = None
    feature_counts: Optional[dict] = None
    layers: Optional[List[dict]] = None
    data_sources: Optional[dict] = None
    error: Optional[str] = None


class EcologicalTestRequest(BaseModel):
    """生态敏感性测试请求"""
    study_area: Optional[dict] = Field(default=None, description="研究区域 GeoJSON")
    use_jintian_data: bool = Field(default=True, description="使用金田村真实数据")


class EcologicalTestResponse(BaseModel):
    """生态敏感性测试响应"""
    success: bool
    study_area_km2: Optional[float] = None
    sensitive_area_km2: Optional[float] = None
    sensitivity_class: Optional[str] = None
    sensitivity_zones: Optional[List[dict]] = None
    recommendations: Optional[List[str]] = None
    geojson: Optional[dict] = None
    error: Optional[str] = None


class FacilityTestRequest(BaseModel):
    """设施验证测试请求"""
    facility_type: str = Field(default="公共服务设施", description="设施类型")
    location: List[float] = Field(default=[116.044146, 24.818629], description="设施坐标")


class FacilityTestResponse(BaseModel):
    """设施验证测试响应"""
    success: bool
    overall_score: Optional[float] = None
    suitability_level: Optional[str] = None
    recommendations: Optional[List[str]] = None
    error: Optional[str] = None


class VectorizerTestRequest(BaseModel):
    """规划矢量化测试请求"""
    zones: Optional[List[dict]] = Field(default=None, description="规划分区")
    facilities: Optional[List[dict]] = Field(default=None, description="规划设施")
    use_report_data: bool = Field(default=True, description="使用报告数据")


class VectorizerTestResponse(BaseModel):
    """规划矢量化测试响应"""
    success: bool
    zones_geojson: Optional[dict] = None
    facilities_geojson: Optional[dict] = None
    error: Optional[str] = None


# 新增工具测试请求/响应模型

class LanduseChangeTestRequest(BaseModel):
    """用地变化分析测试请求"""
    use_jintian_data: bool = Field(default=True, description="使用金田村真实数据")
    change_threshold: float = Field(default=0.1, description="变化识别阈值")


class LanduseChangeTestResponse(BaseModel):
    """用地变化分析测试响应"""
    success: bool
    change_statistics: Optional[dict] = None
    total_current_area_km2: Optional[float] = None
    total_planned_area_km2: Optional[float] = None
    total_area_change_km2: Optional[float] = None
    increase_types: Optional[List[str]] = None
    decrease_types: Optional[List[str]] = None
    error: Optional[str] = None


class ConstraintValidatorTestRequest(BaseModel):
    """约束验证测试请求"""
    use_jintian_data: bool = Field(default=True, description="使用金田村真实数据")
    strict_mode: bool = Field(default=False, description="严格模式")


class ConstraintValidatorTestResponse(BaseModel):
    """约束验证测试响应"""
    success: bool
    compliance_score: Optional[float] = None
    passed_checks: Optional[int] = None
    total_checks: Optional[int] = None
    conflicts: Optional[List[dict]] = None
    is_valid: Optional[bool] = None
    recommendations: Optional[List[str]] = None
    error: Optional[str] = None


class HazardBufferTestRequest(BaseModel):
    """灾害缓冲区测试请求"""
    use_jintian_data: bool = Field(default=True, description="使用金田村真实数据")
    buffer_meters: int = Field(default=200, description="缓冲距离（米）")


class HazardBufferTestResponse(BaseModel):
    """灾害缓冲区测试响应"""
    success: bool
    buffer_zones: Optional[dict] = None
    affected_area_km2: Optional[float] = None
    hazard_count: Optional[int] = None
    hazard_summary: Optional[dict] = None
    error: Optional[str] = None


# ============================================
# Test Data Helper
# ============================================

def _get_test_data(use_real_data: bool = True) -> tuple:
    """Get cached test data."""
    global _TEST_DATA_CACHE
    if _TEST_DATA_CACHE is None:
        if use_real_data:
            _TEST_DATA_CACHE = _get_jintian_test_data()
        else:
            _TEST_DATA_CACHE = _create_test_data()
    return _TEST_DATA_CACHE


def _get_jintian_test_data() -> tuple:
    """使用金田村真实数据替代硬编码矩形"""
    try:
        from backend.services.jintian_test_data_service import JintianTestDataService

        boundary = JintianTestDataService.get_boundary()
        roads = JintianTestDataService.get_road_network(planned=True)
        scheme = JintianTestDataService.get_planning_scheme_from_report()

        logger.info("[gis_test] 使用金田村真实数据: boundary_features=%d, road_features=%d",
                    len(boundary.get("features", [])),
                    len(roads.get("features", [])))

        return boundary, roads, scheme
    except Exception as e:
        logger.warning(f"[gis_test] 金田数据加载失败，使用默认数据: {e}")
        return _create_test_data()


def _create_test_data() -> tuple:
    """创建默认测试数据（用于 fallback）"""
    center_lon, center_lat = JINTIAN_TEST_CENTER
    offset = 0.02

    boundary = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "测试村庄边界"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [center_lon - offset, center_lat - offset],
                    [center_lon + offset, center_lat - offset],
                    [center_lon + offset, center_lat + offset],
                    [center_lon - offset, center_lat + offset],
                    [center_lon - offset, center_lat - offset],
                ]]
            }
        }]
    }

    roads = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "东西主干道", "road_type": "primary"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[center_lon - 0.025, center_lat], [center_lon + 0.025, center_lat]]
                }
            },
            {
                "type": "Feature",
                "properties": {"name": "南北次要道路", "road_type": "secondary"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[center_lon, center_lat - 0.025], [center_lon, center_lat + 0.025]]
                }
            }
        ]
    }

    scheme = VillagePlanningScheme(
        zones=[
            PlanningZone(zone_id="Z01", land_use="residential", area_ratio=0.35,
                         location_bias=LocationBias(direction="center"), density="medium"),
            PlanningZone(zone_id="Z02", land_use="public_service", area_ratio=0.15,
                         location_bias=LocationBias(direction="center"), density="high"),
            PlanningZone(zone_id="Z03", land_use="agricultural", area_ratio=0.30,
                         location_bias=LocationBias(direction="south"), density="low"),
            PlanningZone(zone_id="Z04", land_use="ecological", area_ratio=0.15,
                         location_bias=LocationBias(direction="edge"), density="low"),
            PlanningZone(zone_id="Z05", land_use="industrial", area_ratio=0.05,
                         location_bias=LocationBias(direction="west"), density="low"),
        ],
        facilities=[
            FacilityPoint(facility_id="F01", facility_type="村委会", status="existing",
                          location_hint="村庄中心位置", service_radius=500, priority="high"),
            FacilityPoint(facility_id="F02", facility_type="文化活动站", status="new",
                          location_hint="靠近村委会", service_radius=300, priority="medium"),
        ],
        axes=[
            DevelopmentAxis(axis_id="A01", axis_type="primary", direction="east-west",
                            description="主要发展轴"),
        ],
        rationale="默认规划布局",
        development_axes=["沿东西向主干道发展"],
        total_area_km2=2.0
    )

    return boundary, roads, scheme


# ============================================
# Test Endpoints
# ============================================

@router.post("/test/spatial-layout", response_model=SpatialLayoutTestResponse)
async def test_spatial_layout(request: SpatialLayoutTestRequest):
    """独立测试空间布局生成（使用真实金田村数据）"""
    logger.info(f"[gis_test] 空间布局测试: village={request.village_name}, use_real={request.use_real_data}")

    try:
        boundary, roads, default_scheme = _get_test_data(use_real_data=request.use_real_data)

        scheme = default_scheme
        data_source = "jintian_real" if request.use_real_data else "default_mock"

        if request.planning_scheme:
            try:
                scheme = VillagePlanningScheme(**request.planning_scheme)
                logger.info(f"[gis_test] 使用自定义方案: zones={len(scheme.zones)}")
            except Exception as e:
                logger.warning(f"[gis_test] 方案解析失败: {e}")

        result = generate_spatial_layout_from_json(
            village_boundary=boundary,
            road_network=roads,
            planning_scheme=scheme,
            fallback_grid=True,
            merge_threshold=0.01
        )

        if result.get("success"):
            data = result.get("data", {})
            return SpatialLayoutTestResponse(
                success=True,
                geojson=data.get("geojson"),
                zones_geojson=data.get("zones_geojson"),
                facilities_geojson=data.get("facilities_geojson"),
                axes_geojson=data.get("axes_geojson"),
                statistics=data.get("statistics"),
                center=data.get("center"),
                data_source=data_source,
            )
        else:
            return SpatialLayoutTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        logger.error(f"[gis_test] 异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/boundary-fallback", response_model=BoundaryFallbackTestResponse)
async def test_boundary_fallback(request: BoundaryFallbackTestRequest):
    """测试边界兜底机制"""
    logger.info(f"[gis_test] 边界兜底测试: village={request.village_name}")

    try:
        config = BoundaryFallbackConfig()
        if request.force_bbox:
            config = BoundaryFallbackConfig(strategy_priority=["bbox_buffer"])

        result = generate_proxy_boundary_with_fallback(
            center=JINTIAN_TEST_CENTER,
            village_name=request.village_name or "金田村委会",
            gis_data={"road": _get_test_data()[1], "water": None, "residential": None},
            config=config,
            skip_user_upload=request.skip_user_upload,
        )

        if result.get("success"):
            return BoundaryFallbackTestResponse(
                success=True,
                geojson=result.get("geojson"),
                strategy_used=result.get("strategy_used"),
                fallback_history=result.get("fallback_history"),
                warnings=result.get("warnings"),
                stats=result.get("stats"),
            )
        else:
            return BoundaryFallbackTestResponse(
                success=False,
                error=result.get("error"),
                fallback_history=result.get("fallback_history"),
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/isochrone", response_model=IsochroneTestResponse)
async def test_isochrone(request: IsochroneTestRequest):
    """测试等时圈分析"""
    logger.info(f"[gis_test] 等时圈测试: center={request.center}, times={request.time_minutes}")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_isochrone_analysis

        context = {
            "center": request.center,
            "time_minutes": request.time_minutes,
            "travel_mode": request.travel_mode,
        }

        import json
        result_str = wrap_isochrone_analysis(context)
        result = json.loads(result_str)

        if result.get("success"):
            return IsochroneTestResponse(
                success=True,
                geojson=result.get("geojson"),
                center=result.get("center"),
                travel_mode=result.get("travel_mode"),
            )
        else:
            return IsochroneTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/accessibility", response_model=AccessibilityTestResponse)
async def test_accessibility(request: AccessibilityTestRequest):
    """测试可达性分析"""
    logger.info(f"[gis_test] 可达性测试: type={request.analysis_type}")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_accessibility_analysis
        import json

        # Use Jintian center if origin not provided
        origin = request.origin or list(JINTIAN_TEST_CENTER)

        # Generate sample destinations around center
        destinations = request.destinations or [
            [116.044146 + 0.01, 24.818629],
            [116.044146 - 0.01, 24.818629 + 0.01],
            [116.044146 + 0.02, 24.818629 - 0.01],
        ]

        context = {
            "origin": origin,
            "destinations": destinations,
            "center": origin,
            "analysis_type": request.analysis_type,
        }

        result_str = wrap_accessibility_analysis(context)
        result = json.loads(result_str)

        if result.get("success"):
            return AccessibilityTestResponse(
                success=True,
                coverage_rate=result.get("coverage_rate"),
                reachable_count=result.get("reachable_count"),
                geojson=result.get("geojson"),
                summary=result.get("summary"),
            )
        else:
            return AccessibilityTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/poi-search", response_model=POISearchTestResponse)
async def test_poi_search(request: POISearchTestRequest):
    """测试 POI 搜索"""
    logger.info(f"[gis_test] POI搜索测试: keyword={request.keyword}")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_poi_search
        import json

        context = {
            "keyword": request.keyword,
            "region": request.region,
            "center": request.center or list(JINTIAN_TEST_CENTER),
            "radius": request.radius,
        }

        result_str = wrap_poi_search(context)
        result = json.loads(result_str)

        if result.get("success"):
            return POISearchTestResponse(
                success=True,
                pois=result.get("pois"),
                total_count=result.get("total_count"),
                geojson=result.get("geojson"),
                source=result.get("source"),
            )
        else:
            return POISearchTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/gis-coverage", response_model=GISCoverageTestResponse)
async def test_gis_coverage(request: GISCoverageTestRequest):
    """测试 GIS 数据覆盖率计算"""
    logger.info(f"[gis_test] GIS覆盖率测试: location={request.location}")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_gis_coverage_calculator
        import json

        context = {
            "location": request.location,
            "buffer_km": request.buffer_km,
        }

        result_str = wrap_gis_coverage_calculator(context)
        result = json.loads(result_str)

        if result.get("success"):
            return GISCoverageTestResponse(
                success=True,
                location=result.get("location"),
                coverage_rate=result.get("coverage_rate"),
                layers_available=result.get("layers_available"),
                feature_counts=result.get("feature_counts"),
                layers=result.get("layers"),
                data_sources=result.get("data_sources"),
            )
        else:
            return GISCoverageTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/ecological", response_model=EcologicalTestResponse)
async def test_ecological(request: EcologicalTestRequest):
    """测试生态敏感性分析"""
    logger.info(f"[gis_test] 生态敏感性测试: use_jintian={request.use_jintian_data}")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_ecological_sensitivity
        import json

        study_area = request.study_area
        if request.use_jintian_data and not study_area:
            from backend.services.jintian_test_data_service import JintianTestDataService
            study_area = JintianTestDataService.get_boundary()

        context = {
            "study_area": study_area,
        }

        result_str = wrap_ecological_sensitivity(context)
        result = json.loads(result_str)

        if result.get("success"):
            return EcologicalTestResponse(
                success=True,
                study_area_km2=result.get("study_area_km2"),
                sensitive_area_km2=result.get("sensitive_area_km2"),
                sensitivity_class=result.get("sensitivity_class"),
                sensitivity_zones=result.get("sensitivity_zones"),
                recommendations=result.get("recommendations"),
            )
        else:
            return EcologicalTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/facility", response_model=FacilityTestResponse)
async def test_facility(request: FacilityTestRequest):
    """测试设施位置验证"""
    logger.info(f"[gis_test] 设施验证测试: type={request.facility_type}")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_facility_validator
        import json

        context = {
            "facility_type": request.facility_type,
            "location": request.location,
        }

        result_str = wrap_facility_validator(context)
        result = json.loads(result_str)

        if result.get("success"):
            return FacilityTestResponse(
                success=True,
                overall_score=result.get("overall_score"),
                suitability_level=result.get("suitability_level"),
                recommendations=result.get("recommendations"),
            )
        else:
            return FacilityTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/vectorizer", response_model=VectorizerTestResponse)
async def test_vectorizer(request: VectorizerTestRequest):
    """测试规划矢量化"""
    logger.info(f"[gis_test] 矢量化测试: use_report={request.use_report_data}")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_planning_vectorizer
        import json

        zones = request.zones
        facilities = request.facilities

        if request.use_report_data:
            from backend.services.jintian_test_data_service import JintianTestDataService
            report_zones = JintianTestDataService.get_planning_zones_from_report()
            report_facilities = JintianTestDataService.get_facilities_from_report()

            zones = zones or report_zones
            facilities = facilities or report_facilities

        context = {
            "zones": zones,
            "facilities": facilities,
            "village_center": list(JINTIAN_TEST_CENTER),
        }

        result_str = wrap_planning_vectorizer(context)
        result = json.loads(result_str)

        if result.get("success"):
            return VectorizerTestResponse(
                success=True,
                zones_geojson=result.get("zones"),
                facilities_geojson=result.get("facilities"),
            )
        else:
            return VectorizerTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 新增工具测试端点

@router.post("/test/landuse-change", response_model=LanduseChangeTestResponse)
async def test_landuse_change(request: LanduseChangeTestRequest):
    """测试用地变化分析"""
    logger.info(f"[gis_test] 用地变化分析测试: use_jintian={request.use_jintian_data}")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_landuse_change_analysis
        from backend.services.jintian_test_data_service import JintianTestDataService
        import json

        current_landuse = None
        planned_landuse = None

        if request.use_jintian_data:
            current_landuse = JintianTestDataService.get_data_by_type("landuse_current")
            planned_landuse = JintianTestDataService.get_data_by_type("landuse_planned")

        if not current_landuse or not planned_landuse:
            return LanduseChangeTestResponse(
                success=False,
                error="未找到用地数据，请确保使用金田村测试数据"
            )

        context = {
            "current_landuse": current_landuse,
            "planned_landuse": planned_landuse,
            "change_threshold": request.change_threshold,
        }

        result_str = wrap_landuse_change_analysis(context)
        result = json.loads(result_str)

        if result.get("success"):
            return LanduseChangeTestResponse(
                success=True,
                change_statistics=result.get("change_statistics"),
                total_current_area_km2=result.get("total_current_area_km2"),
                total_planned_area_km2=result.get("total_planned_area_km2"),
                total_area_change_km2=result.get("total_area_change_km2"),
                increase_types=result.get("increase_types"),
                decrease_types=result.get("decrease_types"),
            )
        else:
            return LanduseChangeTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/constraint-validator", response_model=ConstraintValidatorTestResponse)
async def test_constraint_validator(request: ConstraintValidatorTestRequest):
    """测试约束验证"""
    logger.info(f"[gis_test] 约束验证测试: use_jintian={request.use_jintian_data}")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_constraint_validator
        from backend.services.jintian_test_data_service import JintianTestDataService
        import json

        planning_zones = None
        protection_zones = {}
        construction_zone = None

        if request.use_jintian_data:
            planning_zones = JintianTestDataService.get_data_by_type("landuse_planned")
            protection_zones = {
                "farmland_protection": JintianTestDataService.get_data_by_type("farmland_protection"),
                "ecological_protection": JintianTestDataService.get_data_by_type("ecological_protection"),
                "historical_protection": JintianTestDataService.get_data_by_type("historical_protection"),
            }
            construction_zone = JintianTestDataService.get_data_by_type("construction_zone")

        if not planning_zones:
            return ConstraintValidatorTestResponse(
                success=False,
                error="未找到规划数据，请确保使用金田村测试数据"
            )

        context = {
            "planning_zones": planning_zones,
            "protection_zones": protection_zones,
            "construction_zone": construction_zone,
            "strict_mode": request.strict_mode,
        }

        result_str = wrap_constraint_validator(context)
        result = json.loads(result_str)

        if result.get("success"):
            return ConstraintValidatorTestResponse(
                success=True,
                compliance_score=result.get("compliance_score"),
                passed_checks=result.get("passed_checks"),
                total_checks=result.get("total_checks"),
                conflicts=result.get("conflicts"),
                is_valid=result.get("is_valid"),
                recommendations=result.get("recommendations"),
            )
        else:
            return ConstraintValidatorTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/hazard-buffer", response_model=HazardBufferTestResponse)
async def test_hazard_buffer(request: HazardBufferTestRequest):
    """测试灾害缓冲区生成"""
    logger.info(f"[gis_test] 灾害缓冲区测试: buffer={request.buffer_meters}m")

    try:
        from src.tools.core.gis_tool_wrappers import wrap_hazard_buffer_generator
        from backend.services.jintian_test_data_service import JintianTestDataService
        import json

        hazard_points = None

        if request.use_jintian_data:
            hazard_points = JintianTestDataService.get_data_by_type("geological_hazard_points")

        if not hazard_points:
            return HazardBufferTestResponse(
                success=False,
                error="未找到地质灾害点数据，请确保使用金田村测试数据"
            )

        context = {
            "hazard_points": hazard_points,
            "buffer_meters": request.buffer_meters,
            "dissolve": True,
        }

        result_str = wrap_hazard_buffer_generator(context)
        result = json.loads(result_str)

        if result.get("success"):
            return HazardBufferTestResponse(
                success=True,
                buffer_zones=result.get("buffer_zones"),
                affected_area_km2=result.get("affected_area_km2"),
                hazard_count=result.get("hazard_count"),
                hazard_summary=result.get("hazard_summary"),
            )
        else:
            return HazardBufferTestResponse(success=False, error=result.get("error"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]