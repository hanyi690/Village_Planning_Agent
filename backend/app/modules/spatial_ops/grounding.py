"""空间接地模块 — PARSE Agent spatial grounding.

职责 B: 将自然语言空间描述 (如"村北""靠近刘村") 接地为具体的空间锚定:
  方向描述 → BBox → 候选地块 BSM → 排除约束重叠地块 → 邻近度加权

API 设计: spatial_ops/README.md §4.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── 数据类 ──


@dataclass
class ZoneSpatialAnchor:
    """ZoneTarget 空间接地结果 — ground_zone_spatial_preference 的返回值.

    Fields:
        candidate_bsms: BBox + direction 过滤后的候选地块 BSM 列表
        candidate_bbox: 方向描述解析出的 BBox (min_lon, min_lat, max_lon, max_lat)
        excluded_bsms: 与约束多边形 (基本农田/生态红线等) 重叠的排除 BSM
        proximity_weights: 各候选地块到参考点的邻近度 (0.0-1.0, 越高越近)
    """
    candidate_bsms: List[str] = field(default_factory=list)
    candidate_bbox: Optional[Tuple[float, float, float, float]] = None
    excluded_bsms: List[str] = field(default_factory=list)
    proximity_weights: Dict[str, float] = field(default_factory=dict)


# ── 方向接地 ──


def resolve_directional_bbox(
    center: Tuple[float, float],
    direction: str,
    radius_m: float = 1000,
) -> Optional[Tuple[float, float, float, float]]:
    """将方向描述解析为 BBox (min_lon, min_lat, max_lon, max_lat).

    支持 8 个方位: 北/南/东/西/东北/东南/西北/西南 (支持中英文).
    BBox 从 center 向指定方向偏移 radius_m，近端以 center 为界.

    Args:
        center: 参考点坐标 (lon, lat)
        direction: 方向描述 ("北", "south", "东北", "northwest", 等)
        radius_m: 搜索半径（米）

    Returns:
        (min_lon, min_lat, max_lon, max_lat) 或 None (无法识别方向时)
    """
    from app.utils.crs_engine import meters_to_degrees_lon, meters_to_degrees_lat

    lon, lat = center
    direction = direction.strip().lower()

    # 方向归一化: 中文 -> 英文
    dir_map = {
        "北": "north", "南": "south", "东": "east", "西": "west",
        "东北": "northeast", "东南": "southeast", "西北": "northwest", "西南": "southwest",
        "n": "north", "s": "south", "e": "east", "w": "west",
        "ne": "northeast", "se": "southeast", "nw": "northwest", "sw": "southwest",
    }
    direction = dir_map.get(direction, direction)

    deg_lon = meters_to_degrees_lon(radius_m, lat)
    deg_lat = meters_to_degrees_lat(radius_m)

    if direction in ("north",):
        return (lon - deg_lon, lat, lon + deg_lon, lat + deg_lat)
    elif direction in ("south",):
        return (lon - deg_lon, lat - deg_lat, lon + deg_lon, lat)
    elif direction in ("east",):
        return (lon, lat - deg_lat, lon + deg_lon, lat + deg_lat)
    elif direction in ("west",):
        return (lon - deg_lon, lat - deg_lat, lon, lat + deg_lat)
    elif direction in ("northeast",):
        return (lon, lat, lon + deg_lon, lat + deg_lat)
    elif direction in ("southeast",):
        return (lon, lat - deg_lat, lon + deg_lon, lat)
    elif direction in ("northwest",):
        return (lon - deg_lon, lat, lon, lat + deg_lat)
    elif direction in ("southwest",):
        return (lon - deg_lon, lat - deg_lat, lon, lat)

    logger.warning("resolve_directional_bbox: unknown direction '%s'", direction)
    return None


# ── 地块过滤 ──


def _parcel_centroid(parcel) -> Optional[Tuple[float, float]]:
    """Extract centroid from parcel geometry (GeoJSON)."""
    from app.modules.spatial_ops.geometry import _compute_centroid
    try:
        return _compute_centroid(parcel.geometry)
    except Exception:
        return None


def query_parcels_in_bbox(
    parcels: list,
    bbox: Tuple[float, float, float, float],
) -> List[str]:
    """返回质心在 BBox 内的地块 BSM 列表.

    Args:
        parcels: List[CurrentLandUseParcel] 或任何有 .bsm + .geometry 的地块
        bbox: (min_lon, min_lat, max_lon, max_lat)

    Returns:
        质心在 BBox 内的地块 BSM 列表
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    results = []
    for p in parcels:
        centroid = _parcel_centroid(p)
        if centroid is None:
            continue
        clon, clat = centroid
        if min_lon <= clon <= max_lon and min_lat <= clat <= max_lat:
            if p.bsm:
                results.append(p.bsm)
    return results


def query_parcels_near_entity(
    parcels: list,
    entity_center: Tuple[float, float],
    max_distance_m: float = 500,
) -> List[str]:
    """返回距实体中心指定距离内的地块 BSM 列表.

    Args:
        parcels: List[CurrentLandUseParcel]
        entity_center: (lon, lat)
        max_distance_m: 最大距离（米）

    Returns:
        距离内的地块 BSM 列表
    """
    from app.utils.geo_utils import haversine_distance

    results = []
    for p in parcels:
        centroid = _parcel_centroid(p)
        if centroid is None:
            continue
        dist = haversine_distance(entity_center, centroid)
        if dist <= max_distance_m:
            if p.bsm:
                results.append(p.bsm)
    return results


def query_excluded_parcels(
    constraint_index: Any,
    parcels: list,
    zone_type: str = "",
) -> List[str]:
    """从 ConstraintIndex 提取约束区内重叠地块 BSM（排除集）.

    对每个地块检查是否与指定类型的约束多边形重叠.
    当 zone_type 为空时，检查所有约束类型.

    Args:
        constraint_index: ConstraintIndex (from spatial_ops.bridge)
        parcels: List[CurrentLandUseParcel]
        zone_type: "farmland_protection" / "ecological_redline" / 空（全部）

    Returns:
        与约束多边形重叠的地块 BSM 列表
    """
    if constraint_index is None:
        return []

    excluded = set()
    for p in parcels:
        if not p.bsm:
            continue
        overlaps = constraint_index.parcel_in_constraint(p.bsm)
        for ov in overlaps:
            if not zone_type or ov.constraint_type == zone_type:
                excluded.add(p.bsm)
                break
    return list(excluded)


# ── 邻近度评分 ──


def compute_proximity_weights(
    parcels: list,
    reference_center: Tuple[float, float],
    max_distance_m: float = 500,
) -> Dict[str, float]:
    """计算地块到参考点的邻近度评分 (0.0-1.0).

    距离越近权重越高，用于 MIP 目标函数.
    weight = max(0, 1 - distance / max_distance_m)

    Args:
        parcels: List[CurrentLandUseParcel]
        reference_center: (lon, lat)
        max_distance_m: 最大距离（米），超过此距离权重的为 0

    Returns:
        {bsm: weight} 字典，0.0-1.0 范围
    """
    from app.utils.geo_utils import haversine_distance

    weights = {}
    for p in parcels:
        if not p.bsm:
            continue
        centroid = _parcel_centroid(p)
        if centroid is None:
            continue
        dist = haversine_distance(reference_center, centroid)
        weight = max(0.0, 1.0 - dist / max_distance_m)
        weights[p.bsm] = round(weight, 4)
    return weights


# ── 面积计算 ──


def compute_target_area(
    area_ratio: float,
    total_area_ha: float,
) -> float:
    """area_ratio * total_area_ha -> target_area_ha."""
    return area_ratio * total_area_ha


# ── 组合接口 ──


def ground_zone_spatial_preference(
    preference_desc: str,
    place_mappings: Dict[str, dict],
    constraint_index: Any,
    bundle: Any,
    preselected_bsms: Optional[List[str]] = None,
) -> "ZoneSpatialAnchor":
    """组合调用：将 ZoneTarget 的空间偏好描述接地为完整空间锚定.

    这是 PARSE Agent 在 format_targets 后调用的唯一入口.
    内部组合 resolve_directional_bbox + query_parcels_in_bbox +
    query_excluded_parcels + compute_proximity_weights.

    当 preselected_bsms 非空时，跳过 BBox 候选搜索，直接使用 LLM 选定的 BSM
    做排除 + 邻近加权（LLM 语义粗定位 -> spatial_ops 验证/精化）.

    preference_desc 格式: "村北靠近刘村" (方向 + 地名)
    从 place_mappings 中查找地名对应的 center.
    方向关键词从描述中提取: 北/南/东/西/东北/东南/西北/西南.

    Args:
        preference_desc: 空间偏好描述 (如 "村北靠近刘村")
        place_mappings: resolve_place 工具结果，{place_name: {center, parcel_ids, ...}}
        constraint_index: ConstraintIndex 用于排除约束重叠
        bundle: VillageBundle (提供 bundle.polygons.landuse_current)
        preselected_bsms: LLM 语义选定的 BSM 列表（非空时跳过 BBox 搜索）

    Returns:
        ZoneSpatialAnchor 包含完整空间锚定
    """
    from app.utils.geo_utils import haversine_distance

    parcels = bundle.polygons.get("landuse_current") if bundle else []

    if not preference_desc or not parcels:
        return ZoneSpatialAnchor()

    # 1. 从描述中提取方向和地名
    dir_keywords = {
        "北": "north", "南": "south", "东": "east", "西": "west",
        "东北": "northeast", "东南": "southeast", "西北": "northwest", "西南": "southwest",
    }
    direction = ""
    for kw, eng in dir_keywords.items():
        if kw in preference_desc:
            direction = eng
            break

    # 2. 从 place_mappings 中查找地名
    ref_center = None
    ref_name = ""
    for place_name, info in place_mappings.items():
        if place_name in preference_desc:
            center = info.get("center", [0, 0])
            if center and any(center):
                ref_center = (float(center[0]), float(center[1]))
                ref_name = place_name
                break

    # 3. 如果没有地名匹配，用村庄整体中心
    if ref_center is None and parcels:
        try:
            from app.modules.spatial_ops.geometry import _compute_centroid
            all_geoms = [p.geometry for p in parcels if hasattr(p, "geometry")]
            if all_geoms:
                from app.utils.geo_utils import safe_unary_union
                from shapely.geometry import shape
                union_geom = safe_unary_union([shape(g) for g in all_geoms])
                ref_center = (union_geom.centroid.x, union_geom.centroid.y)
        except Exception:
            pass

    if ref_center is None:
        return ZoneSpatialAnchor()

    # 4. 解析 BBox（仅用于可视化，不作为候选过滤依据了）
    bbox = None
    if direction:
        bbox = resolve_directional_bbox(ref_center, direction)

    # 5. 查询候选地块：LLM 语义选定 vs 几何搜索
    if preselected_bsms:
        candidate_bsms = [b for b in preselected_bsms if b]
    elif bbox:
        candidate_bsms = query_parcels_in_bbox(parcels, bbox)
    elif ref_name:
        candidate_bsms = query_parcels_near_entity(parcels, ref_center, max_distance_m=500)
    else:
        candidate_bsms = [p.bsm for p in parcels if p.bsm]

    # 6. 排除约束重叠（对所有候选都做，即使是 LLM 选定的）
    excluded_bsms = query_excluded_parcels(constraint_index, parcels)
    candidate_bsms = [b for b in candidate_bsms if b not in excluded_bsms]

    # 7. 邻近度加权
    proximity_weights = compute_proximity_weights(
        [p for p in parcels if p.bsm in candidate_bsms],
        ref_center,
    )

    logger.info(
        "ground_zone_spatial_preference: direction=%s, ref=%s, llm_selected=%s, candidates=%d, excluded=%d",
        direction or "(none)", ref_name or "(none)",
        bool(preselected_bsms), len(candidate_bsms), len(excluded_bsms),
    )

    return ZoneSpatialAnchor(
        candidate_bsms=candidate_bsms,
        candidate_bbox=bbox,
        excluded_bsms=excluded_bsms,
        proximity_weights=proximity_weights,
    )


# ── Facility 空间接地 ──


def ground_facility_spatial_preference(
    location_hint: str,
    direction: str,
    place_mappings: Dict[str, dict],
    bundle: Any,
) -> "ZoneSpatialAnchor":
    """将 FacilityTarget 的位置描述接地为空间锚定.

    Args:
        location_hint: 位置描述 (如 "村北", "村委会旁")
        direction: 方向 (如 "north", "south")
        place_mappings: resolve_place 工具结果
        bundle: VillageBundle

    Returns:
        ZoneSpatialAnchor 含候选地块和 BBox
    """
    parcels = bundle.polygons.get("landuse_current") if bundle else []
    if not location_hint or not parcels:
        return ZoneSpatialAnchor()

    # 用 place_mappings 匹配地名
    ref_center = None
    for place_name, info in place_mappings.items():
        if place_name in location_hint:
            center = info.get("center", [0, 0])
            if center and any(center):
                ref_center = (float(center[0]), float(center[1]))
                break

    if ref_center is None:
        try:
            from app.modules.spatial_ops.geometry import _compute_centroid
            all_geoms = [p.geometry for p in parcels if hasattr(p, "geometry")]
            if all_geoms:
                from app.utils.geo_utils import safe_unary_union
                from shapely.geometry import shape
                union_geom = safe_unary_union([shape(g) for g in all_geoms])
                ref_center = (union_geom.centroid.x, union_geom.centroid.y)
        except Exception:
            pass

    if ref_center is None:
        return ZoneSpatialAnchor()

    bbox = None
    if direction:
        bbox = resolve_directional_bbox(ref_center, direction)

    candidate_bsms = []
    if bbox:
        candidate_bsms = query_parcels_in_bbox(parcels, bbox)
    else:
        candidate_bsms = query_parcels_near_entity(parcels, ref_center, max_distance_m=300)
    if not candidate_bsms:
        candidate_bsms = [p.bsm for p in parcels if p.bsm]

    logger.info(
        "ground_facility_spatial_preference: hint=%s, direction=%s, candidates=%d",
        location_hint, direction or "(none)", len(candidate_bsms),
    )

    return ZoneSpatialAnchor(
        candidate_bsms=candidate_bsms,
        candidate_bbox=bbox,
    )


# ── Axis / Road 空间接地 ──


def ground_linear_spatial_preference(
    start_anchor: Optional[Tuple[float, float]],
    end_anchor: Optional[Tuple[float, float]],
    place_mappings: Dict[str, dict],
    bundle: Any,
    connects_hints: Optional[List[str]] = None,
) -> "ZoneSpatialAnchor":
    """将 AxisTarget/RoadTarget 的线状锚点接地为路径候选 BSM.

    从 start_anchor / end_anchor 或 connects 地名推断路径走廊内的地块.

    Args:
        start_anchor: 起点坐标 (lon, lat) 或 None
        end_anchor: 终点坐标 (lon, lat) 或 None
        place_mappings: resolve_place 工具结果
        bundle: VillageBundle
        connects_hints: 连接地名列表 (如 ["村北", "村南"])

    Returns:
        ZoneSpatialAnchor 含 corridor_bsms（线状路径的候选地块）
    """
    parcels = bundle.polygons.get("landuse_current") if bundle else []
    if not parcels:
        return ZoneSpatialAnchor()

    # 尝试从 connects_hints 找地名锚点
    ref_centers = []
    if connects_hints:
        for hint in connects_hints:
            for place_name, info in place_mappings.items():
                if place_name in hint or hint in place_name:
                    center = info.get("center", [0, 0])
                    if center and any(center):
                        ref_centers.append((float(center[0]), float(center[1])))
                    break

    # 用已有坐标
    if start_anchor:
        ref_centers.insert(0, start_anchor)
    if end_anchor:
        ref_centers.append(end_anchor)

    if not ref_centers:
        try:
            from app.modules.spatial_ops.geometry import _compute_centroid
            all_geoms = [p.geometry for p in parcels if hasattr(p, "geometry")]
            if all_geoms:
                from app.utils.geo_utils import safe_unary_union
                from shapely.geometry import shape
                union_geom = safe_unary_union([shape(g) for g in all_geoms])
                ref_centers = [(union_geom.centroid.x, union_geom.centroid.y)]
        except Exception:
            pass

    if not ref_centers:
        return ZoneSpatialAnchor()

    candidate_set: Set[str] = set()
    for center in ref_centers:
        bsms = query_parcels_near_entity(parcels, center, max_distance_m=400)
        candidate_set.update(bsms)

    if not candidate_set:
        candidate_set = {p.bsm for p in parcels if p.bsm}

    logger.info(
        "ground_linear_spatial_preference: anchors=%d, candidates=%d",
        len(ref_centers), len(candidate_set),
    )

    return ZoneSpatialAnchor(candidate_bsms=list(candidate_set))


__all__ = [
    "ZoneSpatialAnchor",
    "resolve_directional_bbox",
    "query_parcels_in_bbox",
    "query_parcels_near_entity",
    "query_excluded_parcels",
    "compute_proximity_weights",
    "compute_target_area",
    "ground_zone_spatial_preference",
    "ground_facility_spatial_preference",
    "ground_linear_spatial_preference",
]
