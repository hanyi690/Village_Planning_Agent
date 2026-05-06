"""
Constraint Validator Tool

验证规划方案是否符合保护约束。

功能：
- 检查规划方案与农田保护区的冲突
- 检查规划方案与生态保护区的冲突
- 检查规划方案与历史文化保护区的冲突
- 检查规划方案是否在建设区范围内
- 计算合规评分

输入：
- planning_zones: 规划方案 GeoJSON
- farmland_protection: 农田保护区 GeoJSON
- ecological_protection: 生态保护区 GeoJSON
- historical_protection: 历史保护区 GeoJSON
- construction_zone: 建设区 GeoJSON

输出：
- compliance_score: 合规评分 (0-1)
- conflicts: 冲突区域列表
- warnings: 预警信息
- validated_zones: 合规分区 GeoJSON
"""

from typing import Dict, Any, List, Optional, Tuple
from ...utils.logger import get_logger

logger = get_logger(__name__)

# Check geopandas availability
try:
    import geopandas as gpd
    from shapely.geometry import shape
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[constraint_validator] geopandas/shapely not available")


# 保护约束类型定义
PROTECTION_TYPES = {
    "farmland": {
        "name": "农田保护区",
        "severity": "high",
        "description": "永久基本农田，不得改变用途",
        "color": "#FFD700",
    },
    "ecological": {
        "name": "生态保护区",
        "severity": "medium",
        "description": "生态红线区，限制开发",
        "color": "#228B22",
    },
    "historical": {
        "name": "历史文化保护区",
        "severity": "medium",
        "description": "文物保护单位，需保护",
        "color": "#8B4513",
    },
    "water_source": {
        "name": "水源保护区",
        "severity": "high",
        "description": "饮用水水源保护区",
        "color": "#1E90FF",
    },
    "geological_hazard": {
        "name": "地质灾害区",
        "severity": "high",
        "description": "地质灾害危险区",
        "color": "#FF4500",
    },
}


def validate_planning_constraints(
    planning_zones: Dict[str, Any],
    protection_zones: Optional[Dict[str, Dict[str, Any]]] = None,
    construction_zone: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    验证规划方案是否符合保护约束。

    Args:
        planning_zones: 规划方案 GeoJSON FeatureCollection
        protection_zones: 保护区域字典 {
            "farmland": GeoJSON,
            "ecological": GeoJSON,
            "historical": GeoJSON,
        }
        construction_zone: 建设区 GeoJSON FeatureCollection
        **kwargs: 其他参数
            - strict_mode: 严格模式（任何冲突即不合规）
            - buffer_distance: 冲突检测缓冲距离（米）
            - output_validated: 是否输出合规分区

    Returns:
        Dict with:
        - success: bool
        - data: 验证结果
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "constraint_validator requires geopandas. Install: pip install geopandas shapely"
        }

    if not planning_zones.get("features"):
        return {
            "success": False,
            "error": "planning_zones must contain features"
        }

    try:
        from .spatial_analysis import (
            run_spatial_overlay,
            run_spatial_query,
            geojson_to_geodataframe,
            geodataframe_to_geojson,
            calculate_buffer_zones,
        )

        # 转换规划方案为 GeoDataFrame
        gdf_planning = geojson_to_geodataframe(planning_zones)
        if gdf_planning is None:
            return {"success": False, "error": "Failed to convert planning_zones"}

        strict_mode = kwargs.get("strict_mode", False)
        buffer_distance = kwargs.get("buffer_distance", 0)
        output_validated = kwargs.get("output_validated", True)

        conflicts = []
        warnings = []
        passed_checks = 0
        total_checks = 0

        # 检查各保护区域
        if protection_zones is None:
            protection_zones = {}

        for zone_type, protection_geojson in protection_zones.items():
            if not protection_geojson or not protection_geojson.get("features"):
                continue

            total_checks += 1
            zone_info = PROTECTION_TYPES.get(zone_type, {"name": zone_type, "severity": "medium"})

            # 应用缓冲距离（如果设置）
            if buffer_distance > 0:
                buffer_result = calculate_buffer_zones(
                    layer=protection_geojson,
                    buffer_distance=buffer_distance,
                    dissolve=True,
                )
                if buffer_result.get("success"):
                    check_layer = buffer_result.get("data", {}).get("geojson")
                else:
                    check_layer = protection_geojson
            else:
                check_layer = protection_geojson

            # 检查交集
            intersect_result = run_spatial_overlay(
                operation="intersect",
                layer_a=planning_zones,
                layer_b=check_layer,
            )

            if intersect_result.get("success"):
                intersect_data = intersect_result.get("data", {})
                intersect_count = intersect_data.get("feature_count", 0)
                intersect_area_km2 = intersect_data.get("total_area_km2", 0)

                if intersect_count > 0:
                    # 存在冲突
                    conflict = {
                        "zone_type": zone_type,
                        "zone_name": zone_info.get("name", zone_type),
                        "severity": zone_info.get("severity", "medium"),
                        "conflict_count": intersect_count,
                        "conflict_area_km2": round(intersect_area_km2, 4),
                        "description": zone_info.get("description", ""),
                        "recommendation": _get_conflict_recommendation(zone_type, intersect_area_km2),
                        "conflict_geojson": intersect_data.get("geojson"),
                    }
                    conflicts.append(conflict)

                    if strict_mode:
                        return {
                            "success": True,
                            "data": {
                                "compliance_score": 0,
                                "is_valid": False,
                                "strict_mode_failure": True,
                                "conflicts": conflicts,
                                "warnings": ["严格模式下，任何保护区域冲突均为不合规"],
                            }
                        }
                else:
                    passed_checks += 1

        # 检查建设区边界
        if construction_zone and construction_zone.get("features"):
            total_checks += 1

            # 检查规划方案是否全部在建设区内
            within_result = run_spatial_query(
                query_type="within",
                geometry={"type": "Polygon", "coordinates": [[0, 0]]},  # 占位，实际使用 clip
                target_layer=construction_zone,
            )

            # 使用 clip 检查超出建设区的部分
            clip_result = run_spatial_overlay(
                operation="clip",
                layer_a=planning_zones,
                layer_b=construction_zone,
            )

            if clip_result.get("success"):
                clip_count = clip_result.get("data", {}).get("feature_count", 0)
                original_count = len(planning_zones.get("features", []))

                if clip_count < original_count:
                    # 有规划地块超出建设区
                    out_of_boundary_count = original_count - clip_count
                    conflict = {
                        "zone_type": "construction_boundary",
                        "zone_name": "建设区边界",
                        "severity": "low",
                        "conflict_count": out_of_boundary_count,
                        "description": f"{out_of_boundary_count} 个规划地块超出建设区边界",
                        "recommendation": "调整规划边界，使其在建设区范围内",
                    }
                    conflicts.append(conflict)
                    warnings.append(f"{out_of_boundary_count} 个地块超出建设区")
                else:
                    passed_checks += 1

        # 计算合规评分
        compliance_score = passed_checks / max(total_checks, 1)

        # 生成合规分区（可选）
        validated_zones = None
        if output_validated:
            validated_zones = _generate_validated_zones(
                planning_zones,
                conflicts,
                compliance_score,
            )

        return {
            "success": True,
            "data": {
                "compliance_score": round(compliance_score, 2),
                "is_valid": len(conflicts) == 0,
                "passed_checks": passed_checks,
                "total_checks": total_checks,
                "conflicts": conflicts,
                "warnings": warnings,
                "validated_zones": validated_zones,
                "severity_summary": _summarize_severity(conflicts),
                "recommendations": _generate_overall_recommendations(conflicts, compliance_score),
            }
        }

    except Exception as e:
        logger.error(f"[constraint_validator] Validation failed: {e}")
        return {"success": False, "error": f"Constraint validation failed: {str(e)}"}


def _get_conflict_recommendation(zone_type: str, conflict_area_km2: float) -> str:
    """根据冲突类型生成建议"""
    if zone_type == "farmland":
        return f"农田保护区冲突面积 {conflict_area_km2} km²，需避开永久基本农田"
    elif zone_type == "ecological":
        return f"生态红线区冲突面积 {conflict_area_km2} km²，建议减少开发强度"
    elif zone_type == "historical":
        return f"历史保护区冲突面积 {conflict_area_km2} km²，需征求文物部门意见"
    elif zone_type == "water_source":
        return f"水源保护区冲突面积 {conflict_area_km2} km²，禁止新建设活动"
    elif zone_type == "geological_hazard":
        return f"地质灾害区冲突面积 {conflict_area_km2} km²，需进行地质灾害评估"
    else:
        return f"保护区冲突面积 {conflict_area_km2} km²"


def _generate_validated_zones(
    planning_zones: Dict[str, Any],
    conflicts: List[Dict],
    compliance_score: float,
) -> Optional[Dict[str, Any]]:
    """生成合规分区 GeoJSON，标注冲突区域"""
    try:
        features = planning_zones.get("features", [])
        validated_features = []

        conflict_zones = {c["zone_type"] for c in conflicts}

        for feature in features:
            props = feature.get("properties", {}).copy()
            props["compliance_score"] = compliance_score
            props["has_conflict"] = False

            # 标记冲突状态
            validated_features.append({
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": props,
            })

        # 添加冲突区域标记
        for conflict in conflicts:
            if conflict.get("conflict_geojson"):
                conflict_geojson = conflict.get("conflict_geojson")
                for f in conflict_geojson.get("features", []):
                    props = f.get("properties", {}).copy()
                    props["is_conflict"] = True
                    props["conflict_type"] = conflict.get("zone_type")
                    props["severity"] = conflict.get("severity")
                    validated_features.append({
                        "type": "Feature",
                        "geometry": f.get("geometry"),
                        "properties": props,
                    })

        return {
            "type": "FeatureCollection",
            "features": validated_features,
            "properties": {
                "compliance_score": compliance_score,
                "layerType": "function_zone",
                "layerName": "合规分区验证",
            }
        }

    except Exception as e:
        logger.warning(f"[constraint_validator] Validated zones generation failed: {e}")
        return None


def _summarize_severity(conflicts: List[Dict]) -> Dict[str, int]:
    """汇总冲突严重程度"""
    summary = {"high": 0, "medium": 0, "low": 0}
    for conflict in conflicts:
        severity = conflict.get("severity", "medium")
        summary[severity] = summary.get(severity, 0) + 1
    return summary


def _generate_overall_recommendations(
    conflicts: List[Dict],
    compliance_score: float,
) -> List[str]:
    """生成整体建议"""
    recommendations = []

    if compliance_score >= 0.9:
        recommendations.append("规划方案整体合规，建议进一步优化细节")
    elif compliance_score >= 0.7:
        recommendations.append("规划方案存在部分冲突，建议调整冲突区域")
    elif compliance_score >= 0.5:
        recommendations.append("规划方案合规性较低，需重新评估保护约束")
    else:
        recommendations.append("规划方案合规性严重不足，建议重新规划")

    # 针对性建议
    high_severity = [c for c in conflicts if c.get("severity") == "high"]
    if high_severity:
        recommendations.append(f"存在 {len(high_severity)} 个高严重度冲突，优先解决")

    farmland_conflicts = [c for c in conflicts if c.get("zone_type") == "farmland"]
    if farmland_conflicts:
        recommendations.append("农田保护区冲突必须解决，不可占用永久基本农田")

    return recommendations


def check_single_constraint(
    planning_zone: Dict[str, Any],
    protection_zone: Dict[str, Any],
    zone_type: str,
) -> Dict[str, Any]:
    """
    检查单个规划地块与单个保护区的冲突。

    Args:
        planning_zone: 单个规划地块 GeoJSON Feature
        protection_zone: 保护区域 GeoJSON FeatureCollection
        zone_type: 保护区域类型

    Returns:
        Dict with conflict status
    """
    from .spatial_analysis import run_spatial_query

    try:
        geometry = planning_zone.get("geometry", {})
        if not geometry:
            return {"success": False, "error": "Missing geometry in planning_zone"}

        result = run_spatial_query(
            query_type="intersects",
            geometry=geometry,
            target_layer=protection_zone,
        )

        if result.get("success"):
            match_count = result.get("data", {}).get("match_count", 0)
            return {
                "success": True,
                "data": {
                    "has_conflict": match_count > 0,
                    "zone_type": zone_type,
                    "intersect_count": match_count,
                }
            }

        return {"success": False, "error": result.get("error")}

    except Exception as e:
        return {"success": False, "error": str(e)}


__all__ = [
    "validate_planning_constraints",
    "check_single_constraint",
    "PROTECTION_TYPES",
]