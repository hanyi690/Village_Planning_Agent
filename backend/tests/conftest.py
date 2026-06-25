"""pytest 配置 — 注册 fixtures 供 tests/ 下所有测试使用。"""

from tests.fixtures.gis_e2e import (
    landuse_geojson,
    boundary_geojson,
    protection_zones,
    road_geojson,
    construction_zone_geojson,
    hazard_points_geojson,
    l3_reports_for_kg,
    gis_data,
    real_intent,
)

__all__ = [
    "landuse_geojson",
    "boundary_geojson",
    "protection_zones",
    "road_geojson",
    "construction_zone_geojson",
    "hazard_points_geojson",
    "l3_reports_for_kg",
    "gis_data",
    "real_intent",
]
