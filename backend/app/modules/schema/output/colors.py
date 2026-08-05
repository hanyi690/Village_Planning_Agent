"""Zone type colors and rendering attributes — SINGLE SOURCE OF TRUTH.

All GIS color definitions live here. Frontend, backend tools, map renderers,
and API test routes ALL import from this file.

GB/T 21010 + GB/T 50280-98 planning color specifications.
Synchronized with: frontend/src/features/planning/constants/gis.ts
"""

from typing import Dict

# ── Zone type colors (8 functional zones) ──────────────────────────────

ZONE_TYPE_COLORS: Dict[str, Dict[str, str]] = {
    "农业用地": {"fill": "#F5F8DC", "stroke": "#8B7355"},
    "生态绿地": {"fill": "#68B167", "stroke": "#2E8B57"},
    "居住用地": {"fill": "#FFD380", "stroke": "#B8860B"},
    "商业用地": {"fill": "#FF0000", "stroke": "#CC0000"},
    "产业用地": {"fill": "#BB9674", "stroke": "#8B6914"},
    "公共服务用地": {"fill": "#4A90D9", "stroke": "#1E3A5F"},
    "交通用地": {"fill": "#0000FF", "stroke": "#0066CC"},
    "水域": {"fill": "#87CEEB", "stroke": "#4169E1"},
}

DEFAULT_ZONE_COLOR: Dict[str, str] = {"fill": "#CCCCCC", "stroke": "#666666"}

# ── Facility colors ────────────────────────────────────────────────────

FACILITY_STATUS_COLORS: Dict[str, Dict[str, str]] = {
    "现状保留": {"fill": "green", "stroke": "#006400"},
    "规划新建": {"fill": "blue", "stroke": "#00008B"},
    "规划改扩建": {"fill": "orange", "stroke": "#CC8400"},
    "规划迁建": {"fill": "purple", "stroke": "#800080"},
}

FACILITY_TYPE_COLORS: Dict[str, Dict[str, str]] = {
    "村委会":     {"fill": "#8B4513", "stroke": "#654321"},
    "学校":       {"fill": "#4169E1", "stroke": "#2850A0"},
    "卫生站":     {"fill": "#DC143C", "stroke": "#B01030"},
    "文化站":     {"fill": "#9932CC", "stroke": "#7A28A0"},
    "市场":       {"fill": "#FF8C00", "stroke": "#CC7000"},
    "养老服务":    {"fill": "#2F4F4F", "stroke": "#1F3333"},
    "产业服务中心": {"fill": "#B8860B", "stroke": "#8B6508"},
    "停车场":     {"fill": "#696969", "stroke": "#505050"},
    "地质灾害点":  {"fill": "#FF0000", "stroke": "#CC0000"},
}

# ── Planning zone colors (6 planning zones) ────────────────────────────

PLANNING_ZONE_COLORS: Dict[str, str] = {
    "生态保护区": "#2E8B57",
    "生态控制区": "#90EE90",
    "农田保护区": "#FFE4B5",
    "一般农业区": "#98FB98",
    "村庄建设区": "#FF6347",
    "林业发展区": "#3CB371",
}

PRIMARY_ZONE_COLORS: Dict[str, str] = {
    "生态空间": "#2E8B57",
    "农业空间": "#FFE4B5",
    "建设空间": "#FF6347",
}

PLANNING_ZONE_RENDERING: Dict[str, Dict[str, str]] = {
    "生态保护区": {"zone_type": "生态绿地", "fill": "#2E8B57", "stroke": "#1B5E20"},
    "生态控制区": {"zone_type": "生态绿地", "fill": "#90EE90", "stroke": "#5F9EA0"},
    "农田保护区": {"zone_type": "农业用地", "fill": "#FFE4B5", "stroke": "#DAA520"},
    "一般农业区": {"zone_type": "农业用地", "fill": "#98FB98", "stroke": "#66CD66"},
    "村庄建设区": {"zone_type": "居住用地", "fill": "#FF6347", "stroke": "#CC4F39"},
    "林业发展区": {"zone_type": "生态绿地", "fill": "#3CB371", "stroke": "#2E8B57"},
}

# ── Sensitivity level colors ───────────────────────────────────────────

SENSITIVITY_COLORS: Dict[str, Dict[str, str]] = {
    "high":       {"fill": "#FF0000", "stroke": "#CC0000"},
    "medium":     {"fill": "#FFFF00", "stroke": "#CCCC00"},
    "low":        {"fill": "#00FF00", "stroke": "#00CC00"},
    "buffer":     {"fill": "#FFA500", "stroke": "#CC8400"},
    "高敏感区":    {"fill": "#FF0000", "stroke": "#CC0000"},
    "中敏感区":    {"fill": "#FFFF00", "stroke": "#CCCC00"},
    "低敏感区":    {"fill": "#00FF00", "stroke": "#00CC00"},
    "缓冲区":     {"fill": "#FFA500", "stroke": "#CC8400"},
}

# ── Infrastructure colors (road / water) ───────────────────────────────

INFRA_COLORS: Dict[str, Dict[str, str]] = {
    "县道": {"fill": "#555555", "stroke": "#333333"},
    "乡道": {"fill": "#808080", "stroke": "#606060"},
    "村道": {"fill": "#A0A0A0", "stroke": "#808080"},
    "道路": {"fill": "#666666", "stroke": "#444444"},
    "河流": {"fill": "#00BFFF", "stroke": "#0099CC"},
    "水系": {"fill": "#00BFFF", "stroke": "#0099CC"},
}

# ── Isochrone colors by travel time (minutes) ──────────────────────────

ISOCHRONE_COLORS: Dict[int, str] = {5: "#00FF00", 10: "#FFFF00", 15: "#FFA500"}

# ── Space control zone colors ──────────────────────────────────────────

SPACE_CONTROL_COLORS: Dict[str, Dict[str, str]] = {
    "510": {"fill": "#FFE0B2", "stroke": "#FFB74D", "name": "允许建设区"},
    "520": {"fill": "#C8E6C9", "stroke": "#81C784", "name": "限制建设区"},
    "530": {"fill": "#FFF9C4", "stroke": "#FFF176", "name": "有条件建设区"},
    "540": {"fill": "#FFCDD2", "stroke": "#E57373", "name": "禁止建设区"},
}

# ── Helpers ────────────────────────────────────────────────────────────


def get_zone_color(zone_type: str) -> Dict[str, str]:
    """Get fill/stroke color for a zone type."""
    return ZONE_TYPE_COLORS.get(zone_type, DEFAULT_ZONE_COLOR)


def get_facility_color(facility_type: str) -> Dict[str, str]:
    """Get fill/stroke color for a facility type."""
    return FACILITY_TYPE_COLORS.get(facility_type, DEFAULT_ZONE_COLOR)


def get_infra_color(infra_key: str) -> Dict[str, str]:
    """Get fill/stroke color for infrastructure (road/water type)."""
    return INFRA_COLORS.get(infra_key, INFRA_COLORS.get("道路", DEFAULT_ZONE_COLOR))


__all__ = [
    "ZONE_TYPE_COLORS",
    "DEFAULT_ZONE_COLOR",
    "FACILITY_STATUS_COLORS",
    "FACILITY_TYPE_COLORS",
    "PLANNING_ZONE_COLORS",
    "PRIMARY_ZONE_COLORS",
    "PLANNING_ZONE_RENDERING",
    "SENSITIVITY_COLORS",
    "INFRA_COLORS",
    "ISOCHRONE_COLORS",
    "SPACE_CONTROL_COLORS",
    "get_zone_color",
    "get_facility_color",
    "get_infra_color",
]
