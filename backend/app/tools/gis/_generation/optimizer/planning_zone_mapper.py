"""规划分区名 ↔ zone_type 双向映射。

解决 GIS 系统中的命名不匹配问题：
- ConstraintDrivenAllocator 内部使用 7 类 zone_type（居住用地/农业用地/生态绿地 等）
- LayoutValidator 期望 6 个规划分区名

双层分区体系（三区三线）：
  一级3区：生态空间 / 农业空间 / 建设空间（全域覆盖不重叠）
  二级6类：生态保护区 / 生态控制区 / 农田保护区 / 一般农业区 / 村庄建设区 / 林业发展区

映射关系：
  生态保护区     ← 生态绿地（林地+水域）+ 水域
  生态控制区     ← 生态绿地（草地）
  农田保护区     ← 农业用地（DLBM ∈ BASIC_FARMLAND_DLBMS）
  一般农业区     ← 农业用地（非基本农田 DLBM）
  村庄建设区     ← 居住用地 + 产业用地 + 公共服务用地 + 交通用地 + 商业用地
  林业发展区     ← 生态绿地（商品林/生态林 1340/1350）
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.modules.gis.schema import (
    BASIC_FARMLAND_CODES,
    GENERAL_AGRICULTURE_CODES,
    CONSTRUCTION_ZONE_TYPES as _CONSTRUCTION_ZONE_TYPES,
    DLBM_TO_PLANNING_ZONE,
    PLANNING_ZONE_RENDERING,
    FORESTRY_CODES,
    GRASSLAND_CODES,
    FOREST_CODES,
    WATER_CODES,
    PLANNING_ZONE_TO_PRIMARY_ZONE,
    PLANNING_ZONE_NAMES,
    PRIMARY_ZONE_NAMES,
    get_primary_zone_for_planning_zone,
)

# 基本农田 DLBM（仅耕地 01 类，同步自 schema.BASIC_FARMLAND_CODES）
# 永久基本农田划定应基于 YJJBNTTB 图层，非 DLBM 简单映射
BASIC_FARMLAND_DLBMS = BASIC_FARMLAND_CODES

# 一般农业区 DLBM（园地 + 设施农用地 + 其他，同步自 schema.GENERAL_AGRICULTURE_CODES）
GENERAL_AGRICULTURE_DLBMS = GENERAL_AGRICULTURE_CODES

# 6 个规划分区 → 7 类 zone_type 的目标映射
PLANNING_ZONE_TO_ZONE_TYPES: Dict[str, List[str]] = {
    "生态保护区": ["生态绿地", "水域"],
    "生态控制区": ["生态绿地"],
    "农田保护区": ["农业用地"],
    "一般农业区": ["农业用地"],
    "村庄建设区": ["居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"],
    "林业发展区": ["生态绿地"],
}

# 反向映射：7 类 zone_type → 6 个规划分区（默认映射，基本农田需 DLBM 细分）
ZONE_TYPE_TO_PLANNING_ZONE: Dict[str, str] = {
    "居住用地": "村庄建设区",
    "产业用地": "村庄建设区",
    "公共服务用地": "村庄建设区",
    "交通用地": "村庄建设区",
    "商业用地": "村庄建设区",
    "生态绿地": "生态保护区",
    "水域": "生态保护区",
    # 农业用地需按 DLBM 细分（见 map_zone_type_to_planning_zone）
}

# zone_type → 一级三区映射
ZONE_TYPE_TO_PRIMARY_ZONE: Dict[str, str] = {
    "居住用地": "建设空间",
    "产业用地": "建设空间",
    "公共服务用地": "建设空间",
    "交通用地": "建设空间",
    "商业用地": "建设空间",
    "生态绿地": "生态空间",
    "水域": "生态空间",
    "农业用地": "农业空间",
}

# DLBM → 规划分区偏好（从 zone_schema DLBM_TO_PLANNING_ZONE 反转派生）
PLANNING_ZONE_DLBM_PREFERENCE: Dict[str, List[str]] = defaultdict(list)
for _dlbm, _zone in DLBM_TO_PLANNING_ZONE.items():
    PLANNING_ZONE_DLBM_PREFERENCE[_zone].append(_dlbm)
PLANNING_ZONE_DLBM_PREFERENCE = dict(PLANNING_ZONE_DLBM_PREFERENCE)


def map_planning_zone_targets_to_zone_types(
    planning_targets: Dict[str, float],
    landuse_geojson: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """将 6 个规划分区目标转为 7 类 zone_type 目标。

    农业用地目标 = 农田保护区 + 一般农业区（合并）
    村庄建设区目标 = 5 类建设用地的任一个（取最大）
    生态保护区目标 = 生态绿地（林+水）+ 水域
    生态控制区目标 = 生态绿地（草地部分）
    林业发展区目标 = 生态绿地（商品林/生态林部分）
    """
    zone_type_targets: Dict[str, float] = {}
    agri_total = 0.0
    eco_total = 0.0
    construction_total = 0.0
    eco_control_total = 0.0
    forestry_total = 0.0

    for pz, area in planning_targets.items():
        if pz == "农田保护区":
            agri_total += area
        elif pz == "一般农业区":
            agri_total += area
        elif pz == "村庄建设区":
            construction_total += area
        elif pz == "生态保护区":
            eco_total += area
        elif pz == "生态控制区":
            eco_control_total += area
        elif pz == "林业发展区":
            forestry_total += area

    if agri_total > 0:
        zone_type_targets["农业用地"] = agri_total
    if construction_total > 0:
        # Compute construction sub-type ratios from current land use if available
        ratios = _compute_construction_ratios(landuse_geojson) if landuse_geojson else {}
        zone_type_targets["居住用地"] = construction_total * ratios.get("居住用地", 0.6)
        zone_type_targets["产业用地"] = construction_total * ratios.get("产业用地", 0.15)
        zone_type_targets["公共服务用地"] = construction_total * ratios.get("公共服务用地", 0.15)
        zone_type_targets["交通用地"] = construction_total * ratios.get("交通用地", 0.08)
        zone_type_targets["商业用地"] = construction_total * ratios.get("商业用地", 0.02)
    if eco_total > 0:
        eco_ratios = _compute_ecological_ratios(landuse_geojson) if landuse_geojson else {}
        zone_type_targets["生态绿地"] = eco_total * eco_ratios.get("生态绿地", 0.9)
        zone_type_targets["水域"] = eco_total * eco_ratios.get("水域", 0.1)
    if eco_control_total > 0:
        zone_type_targets["生态绿地"] = zone_type_targets.get("生态绿地", 0.0) + eco_control_total
    if forestry_total > 0:
        zone_type_targets["生态绿地"] = zone_type_targets.get("生态绿地", 0.0) + forestry_total

    return zone_type_targets


def _compute_ecological_ratios(
    landuse_geojson: Dict[str, Any],
) -> Dict[str, float]:
    """Compute ecological split ratios from current land-use data.

    Measures actual 生态绿地 vs 水域 area from parcels, falling back
    to the default 0.9 / 0.1 split if data is unavailable.
    """
    from app.modules.gis.schema import ZONE_TYPE_TO_DLBMS
    green_dlbms = set(ZONE_TYPE_TO_DLBMS.get("生态绿地", []))
    water_dlbms = set(ZONE_TYPE_TO_DLBMS.get("水域", []))
    eco_dlbms = green_dlbms | water_dlbms

    green_area = 0.0
    water_area = 0.0
    for ft in landuse_geojson.get("features", []):
        dlbm = str(ft.get("properties", {}).get("DLBM", "")).strip()
        if dlbm not in eco_dlbms:
            continue
        area = ft.get("properties", {}).get("area_ha", 0.0)
        if area <= 0:
            continue
        if dlbm in green_dlbms:
            green_area += area
        elif dlbm in water_dlbms:
            water_area += area

    total = green_area + water_area
    if total > 0:
        return {"生态绿地": green_area / total, "水域": water_area / total}
    return {"生态绿地": 0.9, "水域": 0.1}


def _compute_construction_ratios(landuse_geojson: Dict[str, Any]) -> Dict[str, float]:
    """Compute construction sub-type ratios from current land use statistics."""
    from collections import defaultdict
    from app.modules.gis.schema import DLBM_TO_ZONE_TYPE

    zone_areas: Dict[str, float] = defaultdict(float)
    for feat in landuse_geojson.get("features", []):
        props = feat.get("properties", {})
        dlbm = str(props.get("DLBM", "")).strip()
        zone_type = DLBM_TO_ZONE_TYPE.get(dlbm, "")
        if zone_type in _CONSTRUCTION_ZONE_TYPES:
            area = (props.get("DLMJ", 0) or props.get("SHAPE_Area", 0) or 0) / 10000
            zone_areas[zone_type] += area

    total = sum(zone_areas.values())
    if total <= 0:
        return {}

    return {zt: area / total for zt, area in zone_areas.items()}


def map_zone_type_to_planning_zone(
    zone_type: str,
    dlbm: str = "",
) -> str:
    """将 allocator 输出的 zone_type 映射为 6 个规划分区名。

    细分逻辑：
    - 农业用地：DLBM ∈ BASIC_FARMLAND_DLBMS → 农田保护区；其他 → 一般农业区
    - 生态绿地：DLBM ∈ GRASSLAND_CODES → 生态控制区；
                DLBM ∈ FORESTRY_CODES → 林业发展区；
                其他 → 生态保护区
    - 水域 → 生态保护区
    """
    if zone_type == "农业用地":
        if dlbm in BASIC_FARMLAND_DLBMS:
            return "农田保护区"
        return "一般农业区"
    if zone_type == "生态绿地":
        if dlbm in GRASSLAND_CODES:
            return "生态控制区"
        if dlbm in FORESTRY_CODES:
            return "林业发展区"
        return "生态保护区"
    return ZONE_TYPE_TO_PLANNING_ZONE.get(zone_type, "一般农业区")


def remap_assigned_zones(
    features: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """将 features 中 assigned_zone 从 7 类 zone_type 重映射为 6 个规划分区名。

    Args:
        features: allocator 输出的 feature 列表，每个 feature 有
                  properties.assigned_zone (7 类) 和 properties.DLBM

    Returns:
        修改后的 features（in-place 修改并返回）
    """
    for ft in features:
        props = ft.setdefault("properties", {})
        assigned = props.get("assigned_zone", "")
        dlbm = str(props.get("DLBM", "")).strip()
        if not assigned:
            continue
        # 已是 6 个规划分区名则跳过
        if assigned in PLANNING_ZONE_TO_ZONE_TYPES:
            continue
        # 映射为 6 个规划分区名
        props["assigned_zone"] = map_zone_type_to_planning_zone(assigned, dlbm)
        # 保留原 zone_type 作为参考
        props.setdefault("zone_type_original", assigned)
    return features


__all__ = [
    "BASIC_FARMLAND_DLBMS",
    "GENERAL_AGRICULTURE_DLBMS",
    "PLANNING_ZONE_TO_ZONE_TYPES",
    "ZONE_TYPE_TO_PLANNING_ZONE",
    "ZONE_TYPE_TO_PRIMARY_ZONE",
    "PLANNING_ZONE_DLBM_PREFERENCE",
    "PLANNING_ZONE_NAMES",
    "PRIMARY_ZONE_NAMES",
    "PLANNING_ZONE_TO_PRIMARY_ZONE",
    "map_planning_zone_targets_to_zone_types",
    "map_zone_type_to_planning_zone",
    "remap_assigned_zones",
]
