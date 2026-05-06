"""
Jintian Test Data Service - 金田村测试数据加载服务

提供金田村真实 GIS 数据的加载和缓存功能。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from src.tools.core import VillagePlanningScheme, PlanningZone, FacilityPoint, DevelopmentAxis
from src.tools.core.planning_schema import LocationBias, AdjacencyRule

logger = logging.getLogger(__name__)

# Data directory path
JINTIAN_DATA_DIR = Path(__file__).parent.parent.parent / "docs" / "gis" / "jintian_boundary"


class JintianTestDataService:
    """金田村测试数据服务"""

    _cache: Dict[str, Any] = {}

    @classmethod
    def _load_geojson(cls, filename: str) -> Dict:
        """Load GeoJSON file with caching."""
        cache_key = f"geojson:{filename}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        filepath = JINTIAN_DATA_DIR / filename
        if not filepath.exists():
            logger.warning(f"[JintianService] File not found: {filename}")
            return {}

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        cls._cache[cache_key] = data
        return data

    @classmethod
    def _load_metadata(cls) -> Dict:
        """Load metadata.json with caching."""
        cache_key = "metadata"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        filepath = JINTIAN_DATA_DIR / "metadata.json"
        if not filepath.exists():
            return {}

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        cls._cache[cache_key] = data
        return data

    @classmethod
    def get_boundary(cls) -> Dict:
        """获取金田村规划边界 GeoJSON"""
        return cls._load_geojson("boundary.geojson")

    @classmethod
    def get_boundary_current(cls) -> Dict:
        """获取金田村现状边界 GeoJSON"""
        return cls._load_geojson("boundary_current.geojson")

    @classmethod
    def get_road_network(cls, planned: bool = True) -> Dict:
        """获取道路网络 GeoJSON

        Args:
            planned: True for planned roads, False for current roads
        """
        filename = "road_planned.geojson" if planned else "road_current.geojson"
        return cls._load_geojson(filename)

    @classmethod
    def get_landuse(cls, planned: bool = True) -> Dict:
        """获取用地 GeoJSON"""
        filename = "landuse_planned.geojson" if planned else "landuse_current.geojson"
        return cls._load_geojson(filename)

    @classmethod
    def get_hazard_points(cls) -> Dict:
        """获取地质灾害点 GeoJSON"""
        return cls._load_geojson("geological_hazard_points.geojson")

    @classmethod
    def get_protection_zones(cls) -> Dict:
        """获取保护红线 GeoJSON（合并农田、生态、历史保护）"""
        farmland = cls._load_geojson("farmland_protection.geojson")
        ecological = cls._load_geojson("ecological_protection.geojson")
        historical = cls._load_geojson("historical_protection.geojson")

        # Merge all protection zones
        merged_features = []
        for geojson in [farmland, ecological, historical]:
            for feature in geojson.get("features", []):
                merged_features.append(feature)

        return {
            "type": "FeatureCollection",
            "features": merged_features,
        }

    @classmethod
    def get_construction_zone(cls) -> Dict:
        """获取建设用地 GeoJSON"""
        return cls._load_geojson("construction_zone.geojson")

    @classmethod
    def get_center(cls) -> Tuple[float, float]:
        """获取金田村中心坐标 (lon, lat)"""
        metadata = cls._load_metadata()
        # From metadata or calculated from boundary
        village_info = metadata.get("village", {})
        # Default center from previous analysis
        return (116.044146, 24.818629)

    @classmethod
    def get_area_km2(cls) -> float:
        """获取金田村面积 (km²)"""
        metadata = cls._load_metadata()
        return metadata.get("village", {}).get("area_km2", 23.53)

    @classmethod
    def get_village_name(cls) -> str:
        """获取金田村名称"""
        metadata = cls._load_metadata()
        return metadata.get("village", {}).get("name", "金田村委会")

    @classmethod
    def get_facilities_from_report(cls) -> List[Dict]:
        """从 Layer3 报告提取规划设施"""
        cache_key = "facilities"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        # Predefined facilities based on Layer3 report
        facilities = [
            {
                "facility_id": "F01",
                "facility_type": "村委会",
                "status": "existing",
                "location_hint": "园寨村中心位置",
                "service_radius": 500,
                "priority": "high",
            },
            {
                "facility_id": "F02",
                "facility_type": "林下灵芝扩种示范基地",
                "status": "new",
                "location_hint": "园寨村后山商业林区",
                "scale": "100亩",
                "priority": "high",
            },
            {
                "facility_id": "F03",
                "facility_type": "古檀文化公园",
                "status": "upgrade",
                "location_hint": "园寨村古檀树周边",
                "scale": "5000㎡",
                "priority": "high",
            },
            {
                "facility_id": "F04",
                "facility_type": "农产品初加工与冷链中心",
                "status": "new",
                "location_hint": "园寨村村委会旁闲置用地",
                "scale": "500㎡",
                "priority": "medium",
            },
            {
                "facility_id": "F05",
                "facility_type": "船灯舞非遗传承体验馆",
                "status": "new",
                "location_hint": "园寨村废弃小学旧址",
                "scale": "300㎡",
                "priority": "medium",
            },
            {
                "facility_id": "F06",
                "facility_type": "金田驿道康养步道",
                "status": "new",
                "location_hint": "南粤古驿道遗存沿线",
                "scale": "3公里",
                "priority": "medium",
            },
            {
                "facility_id": "F07",
                "facility_type": "闲置农房民宿集群",
                "status": "new",
                "location_hint": "社前、园寨自然村闲置房屋",
                "scale": "15栋",
                "priority": "low",
            },
            {
                "facility_id": "F08",
                "facility_type": "村级电商物流服务站",
                "status": "new",
                "location_hint": "村主干道旁 Y122 乡道沿线",
                "scale": "200㎡",
                "priority": "high",
            },
            {
                "facility_id": "F09",
                "facility_type": "生态蜂林养殖区",
                "status": "new",
                "location_hint": "远离居住区的深层林地",
                "scale": "500箱",
                "priority": "low",
            },
        ]

        cls._cache[cache_key] = facilities
        return facilities

    @classmethod
    def get_planning_scheme_from_report(cls) -> VillagePlanningScheme:
        """从 Layer3 报告提取规划方案"""
        cache_key = "planning_scheme"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        # Create planning scheme based on "一心一带三区"
        scheme = VillagePlanningScheme(
            zones=[
                PlanningZone(
                    zone_id="Z01",
                    land_use="public_service",
                    area_ratio=0.05,
                    location_bias=LocationBias(direction="center"),
                    density="high",
                    description="综合服务中心",
                ),
                PlanningZone(
                    zone_id="Z02",
                    land_use="tourism",
                    area_ratio=0.10,
                    location_bias=LocationBias(direction="axis"),
                    density="medium",
                    description="南粤古驿道文旅发展带",
                ),
                PlanningZone(
                    zone_id="Z03",
                    land_use="agricultural",
                    area_ratio=0.30,
                    location_bias=LocationBias(direction="north"),
                    adjacency=AdjacencyRule(avoid_adjacent_to=["construction"]),
                    density="low",
                    description="林下经济示范区",
                ),
                PlanningZone(
                    zone_id="Z04",
                    land_use="agricultural",
                    area_ratio=0.20,
                    location_bias=LocationBias(direction="south"),
                    adjacency=AdjacencyRule(adjacent_to=["residential"]),
                    density="medium",
                    description="特色农业种植区",
                ),
                PlanningZone(
                    zone_id="Z05",
                    land_use="ecological",
                    area_ratio=0.35,
                    location_bias=LocationBias(direction="edge"),
                    adjacency=AdjacencyRule(avoid_adjacent_to=["industrial", "construction"]),
                    density="low",
                    description="生态康养保护区",
                ),
            ],
            facilities=[
                FacilityPoint(
                    facility_id="F01",
                    facility_type="村委会",
                    status="existing",
                    location_hint="园寨村中心位置",
                    service_radius=500,
                    priority="high",
                ),
                FacilityPoint(
                    facility_id="F02",
                    facility_type="林下灵芝示范基地",
                    status="new",
                    location_hint="园寨村后山商业林区",
                    service_radius=1000,
                    priority="high",
                ),
                FacilityPoint(
                    facility_id="F03",
                    facility_type="古檀文化公园",
                    status="upgrade",
                    location_hint="园寨村古檀树周边",
                    service_radius=300,
                    priority="high",
                ),
                FacilityPoint(
                    facility_id="F04",
                    facility_type="农产品加工中心",
                    status="new",
                    location_hint="村委会旁闲置用地",
                    service_radius=200,
                    priority="medium",
                ),
                FacilityPoint(
                    facility_id="F05",
                    facility_type="船灯舞体验馆",
                    status="new",
                    location_hint="废弃小学旧址",
                    service_radius=400,
                    priority="medium",
                ),
            ],
            axes=[
                DevelopmentAxis(
                    axis_id="A01",
                    axis_type="primary",
                    direction="east-west",
                    description="Y122 乡道发展主轴",
                ),
                DevelopmentAxis(
                    axis_id="A02",
                    axis_type="secondary",
                    direction="north-south",
                    description="金田河生态景观带",
                ),
            ],
            rationale="基于'一心一带三区'空间结构的规划布局",
            development_axes=["沿Y122乡道东西向发展", "沿金田河生态保护"],
            total_area_km2=23.53,
        )

        cls._cache[cache_key] = scheme
        return scheme

    @classmethod
    def get_planning_zones_from_report(cls) -> List[Dict]:
        """从 Layer3 报告提取规划分区（用于矢量化测试）"""
        cache_key = "zones"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        zones = [
            {
                "zone_id": "Z01",
                "land_use": "public_service",
                "area_ratio": 0.05,
                "location_bias": {"direction": "center"},
                "density": "high",
                "description": "综合服务中心",
            },
            {
                "zone_id": "Z02",
                "land_use": "tourism",
                "area_ratio": 0.10,
                "location_bias": {"direction": "axis"},
                "density": "medium",
                "description": "南粤古驿道文旅发展带",
            },
            {
                "zone_id": "Z03",
                "land_use": "agricultural",
                "area_ratio": 0.30,
                "location_bias": {"direction": "north"},
                "density": "low",
                "description": "林下经济示范区",
            },
            {
                "zone_id": "Z04",
                "land_use": "agricultural",
                "area_ratio": 0.20,
                "location_bias": {"direction": "south"},
                "density": "medium",
                "description": "特色农业种植区",
            },
            {
                "zone_id": "Z05",
                "land_use": "ecological",
                "area_ratio": 0.35,
                "location_bias": {"direction": "edge"},
                "density": "low",
                "description": "生态康养保护区",
            },
        ]

        cls._cache[cache_key] = zones
        return zones

    @classmethod
    def clear_cache(cls):
        """Clear all cached data."""
        cls._cache.clear()
        logger.info("[JintianService] Cache cleared")


__all__ = ["JintianTestDataService"]