"""Zone type colors and rendering attributes.

GB/T 21010 + GB/T 50280-98 planning color specifications.
Synchronized with frontend: frontend/src/features/planning/constants/gis.ts
"""

from typing import Dict

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

FACILITY_STATUS_COLORS: Dict[str, Dict[str, str]] = {
    "现状保留": {"fill": "green", "stroke": "#006400"},
    "规划新建": {"fill": "blue", "stroke": "#00008B"},
    "规划改扩建": {"fill": "orange", "stroke": "#CC8400"},
    "规划迁建": {"fill": "purple", "stroke": "#800080"},
}

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


def get_zone_color(zone_type: str) -> Dict[str, str]:
    """Get fill/stroke color for a zone type."""
    return ZONE_TYPE_COLORS.get(zone_type, DEFAULT_ZONE_COLOR)
