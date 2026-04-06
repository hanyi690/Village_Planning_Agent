"""
GIS Validation Tools for Planning

Provides facility location validation and ecological sensitivity assessment
for scientific planning verification.

Reference: Planning workflow requires validation of facility siting decisions
and ecological protection zone identification.
"""

from typing import Dict, Any, List, Optional, Tuple, Literal
from ...utils.logger import get_logger

logger = get_logger(__name__)

# Import core analysis modules
try:
    from ..core.accessibility_core import (
        haversine_distance,
        SERVICE_RADIUS_STANDARDS,
        run_accessibility_analysis,
    )
    ACCESSIBILITY_AVAILABLE = True
except ImportError:
    ACCESSIBILITY_AVAILABLE = False
    logger.warning("[gis_validation] accessibility_core not available")

try:
    from ..core.gis_core import run_gis_analysis
    GIS_AVAILABLE = True
except ImportError:
    GIS_AVAILABLE = False
    logger.warning("[gis_validation] gis_core not available")

try:
    from ..core.spatial_analysis import calculate_buffer_zones, geojson_to_geodataframe
    SPATIAL_AVAILABLE = True
except ImportError:
    SPATIAL_AVAILABLE = False
    logger.warning("[gis_validation] spatial_analysis not available")


# Facility siting standards (from planning regulations)
FACILITY_SITING_STANDARDS = {
    "幼儿园": {
        "service_radius": 300,
        "min_population": 500,
        "avoid_zones": ["工业区", "垃圾处理场", "加油站"],
        "preferred_zones": ["居住区", "社区中心"],
    },
    "小学": {
        "service_radius": 500,
        "min_population": 1000,
        "avoid_zones": ["工业区", "交通主干道"],
        "preferred_zones": ["居住区"],
    },
    "中学": {
        "service_radius": 1000,
        "min_population": 3000,
        "avoid_zones": ["工业区"],
        "preferred_zones": ["居住区", "交通便捷区"],
    },
    "医院": {
        "service_radius": 1000,
        "min_population": 5000,
        "avoid_zones": ["工业区", "垃圾处理场"],
        "preferred_zones": ["交通便利区", "人口密集区"],
    },
    "诊所": {
        "service_radius": 500,
        "min_population": 1000,
        "avoid_zones": ["工业区"],
        "preferred_zones": ["居住区"],
    },
    "公园": {
        "service_radius": 500,
        "min_population": 2000,
        "avoid_zones": [],
        "preferred_zones": ["生态敏感区周边", "居住区"],
    },
    "超市": {
        "service_radius": 500,
        "min_population": 1500,
        "avoid_zones": [],
        "preferred_zones": ["居住区", "交通节点"],
    },
    "菜市场": {
        "service_radius": 500,
        "min_population": 2000,
        "avoid_zones": ["学校周边100m"],
        "preferred_zones": ["居住区"],
    },
    "健身设施": {
        "service_radius": 500,
        "min_population": 1000,
        "avoid_zones": [],
        "preferred_zones": ["公园周边", "社区中心"],
    },
    "垃圾收集点": {
        "service_radius": 100,
        "min_population": 200,
        "avoid_zones": ["学校", "医院", "水源地"],
        "preferred_zones": ["交通便利区"],
    },
    "公交站": {
        "service_radius": 300,
        "min_population": 500,
        "avoid_zones": [],
        "preferred_zones": ["居住区入口", "公共设施周边"],
    },
}

# Ecological sensitivity factors
ECOLOGICAL_SENSITIVITY_FACTORS = {
    "water_body": {
        "buffer_distance": 50,
        "weight": 0.3,
        "description": "Water body buffer zone",
    },
    "river": {
        "buffer_distance": 30,
        "weight": 0.25,
        "description": "River buffer zone",
    },
    "wetland": {
        "buffer_distance": 100,
        "weight": 0.35,
        "description": "Wetland protection zone",
    },
    "forest": {
        "buffer_distance": 20,
        "weight": 0.15,
        "description": "Forest edge zone",
    },
    "slope_over_25": {
        "buffer_distance": 0,
        "weight": 0.2,
        "description": "Steep slope area (development prohibited)",
    },
}


def validate_facility_location(
    facility_type: str,
    location: Tuple[float, float],
    analysis_params: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    """
    Validate facility location suitability

    Comprehensive validation including:
    - Service radius coverage analysis
    - Population accessibility analysis
    - Siting constraint verification
    - Overall suitability scoring

    Args:
        facility_type: Type of facility (e.g., "幼儿园", "医院")
        location: Facility location coordinates (lon, lat)
        analysis_params: Analysis parameters
            - population_points: List of population distribution points
            - existing_facilities: List of existing facilities of same type
            - land_use_data: Current land use GeoJSON
            - water_features: Water body GeoJSON for constraint check
        **kwargs: Additional parameters

    Returns:
        Dict with validation results and recommendations
    """
    try:
        # Get facility standards
        standards = FACILITY_SITING_STANDARDS.get(facility_type, {
            "service_radius": 500,
            "min_population": 1000,
            "avoid_zones": [],
            "preferred_zones": [],
        })

        service_radius = standards.get("service_radius", 500)
        min_population = standards.get("min_population", 1000)
        avoid_zones = standards.get("avoid_zones", [])
        preferred_zones = standards.get("preferred_zones", [])

        # Initialize validation results
        validation_results = {
            "facility_type": facility_type,
            "location": location,
            "standards_applied": standards,
            "checks": {},
            "scores": {},
            "recommendations": [],
        }

        # 1. Service radius coverage analysis
        population_points = analysis_params.get("population_points", [])
        coverage_result = _analyze_coverage(
            location, population_points, service_radius
        )
        validation_results["checks"]["coverage"] = coverage_result

        # Coverage score (0-100)
        coverage_rate = coverage_result.get("coverage_rate", 0)
        validation_results["scores"]["coverage"] = min(100, coverage_rate * 100)

        # 2. Population adequacy check
        total_population = coverage_result.get("covered_population", 0)
        population_adequate = total_population >= min_population
        validation_results["checks"]["population_adequacy"] = {
            "served_population": total_population,
            "required_population": min_population,
            "adequate": population_adequate,
            "gap": min_population - total_population if not population_adequate else 0,
        }

        # Population score (0-100)
        if population_adequate:
            validation_results["scores"]["population"] = 100
        else:
            pop_ratio = total_population / min_population
            validation_results["scores"]["population"] = min(100, pop_ratio * 100)

        # 3. Existing facility proximity check
        existing_facilities = analysis_params.get("existing_facilities", [])
        proximity_result = _check_facility_proximity(
            location, existing_facilities, facility_type, service_radius
        )
        validation_results["checks"]["facility_proximity"] = proximity_result

        # Proximity score (0-100, lower if too close to existing)
        min_dist = proximity_result.get("min_distance_m")
        if min_dist is not None and min_dist < service_radius * 0.5:
            validation_results["scores"]["proximity"] = 50  # Penalty for too close
        else:
            validation_results["scores"]["proximity"] = 100

        # 4. Constraint zone check (water bodies, industrial areas, etc.)
        water_features = analysis_params.get("water_features")
        if water_features and SPATIAL_AVAILABLE:
            constraint_result = _check_constraint_zones(
                location, water_features, avoid_zones
            )
            validation_results["checks"]["constraints"] = constraint_result

            # Constraint score (0 if in forbidden zone)
            if constraint_result.get("in_forbidden_zone"):
                validation_results["scores"]["constraints"] = 0
            else:
                validation_results["scores"]["constraints"] = 100

        # 5. Calculate overall score
        scores = validation_results["scores"]
        weights = {"coverage": 0.3, "population": 0.25, "proximity": 0.2, "constraints": 0.25}

        overall_score = sum(
            scores.get(k, 50) * weights.get(k, 0.25)
            for k in weights
        ) / sum(weights.values())

        validation_results["overall_score"] = round(overall_score, 1)
        validation_results["suitability_level"] = _get_suitability_level(overall_score)

        # 6. Generate recommendations
        recommendations = _generate_facility_recommendations(validation_results)
        validation_results["recommendations"] = recommendations

        return {
            "success": True,
            "data": validation_results,
        }

    except Exception as e:
        logger.error(f"[gis_validation] Facility validation failed: {e}")
        return {"success": False, "error": f"Facility validation failed: {str(e)}"}


def _analyze_coverage(
    location: Tuple[float, float],
    population_points: List[Dict[str, Any]],
    service_radius: float
) -> Dict[str, Any]:
    """Analyze population coverage within service radius"""
    covered_population = 0
    total_population = 0
    covered_points = []
    uncovered_points = []

    for point in population_points:
        coords = point.get("coordinates", [0, 0])
        pop = point.get("population", 1)
        total_population += pop

        distance = haversine_distance(location, (coords[0], coords[1]))

        if distance <= service_radius:
            covered_population += pop
            covered_points.append({
                "coordinates": coords,
                "population": pop,
                "distance_m": round(distance, 1),
            })
        else:
            uncovered_points.append({
                "coordinates": coords,
                "population": pop,
                "distance_m": round(distance, 1),
            })

    coverage_rate = covered_population / total_population if total_population > 0 else 0

    return {
        "coverage_rate": round(coverage_rate, 4),
        "covered_population": covered_population,
        "total_population": total_population,
        "service_radius_m": service_radius,
        "covered_points_count": len(covered_points),
        "uncovered_points_count": len(uncovered_points),
    }


def _check_facility_proximity(
    location: Tuple[float, float],
    existing_facilities: List[Dict[str, Any]],
    facility_type: str,
    service_radius: float
) -> Dict[str, Any]:
    """Check proximity to existing facilities of same type"""
    same_type_facilities = [
        f for f in existing_facilities
        if f.get("type") == facility_type
    ]

    distances = []
    nearest = None
    min_distance = float("inf")

    for facility in same_type_facilities:
        coords = facility.get("coordinates", [0, 0])
        distance = haversine_distance(location, (coords[0], coords[1]))
        distances.append(distance)

        if distance < min_distance:
            min_distance = distance
            nearest = facility

    return {
        "existing_count": len(same_type_facilities),
        "min_distance_m": round(min_distance, 1) if min_distance != float("inf") else None,
        "nearest_facility": nearest,
        "distances_m": [round(d, 1) for d in distances[:5]],
        "optimal_distance_m": service_radius,  # Ideal separation
    }


def _check_constraint_zones(
    location: Tuple[float, float],
    water_features: Dict[str, Any],
    avoid_zones: List[str]
) -> Dict[str, Any]:
    """Check if location is within constraint zones"""
    if not SPATIAL_AVAILABLE:
        return {"checked": False, "reason": "Spatial analysis unavailable"}

    # Create point geometry
    point_geojson = {"type": "Point", "coordinates": list(location)}

    # Check water body proximity
    water_gdf = geojson_to_geodataframe(water_features)
    if water_gdf is None:
        return {"checked": False, "reason": "Invalid water features"}

    distances = water_gdf.geometry.apply(
        lambda geom: haversine_distance(
            location,
            (geom.centroid.x, geom.centroid.y)
        )
    )

    min_water_distance = distances.min() if len(distances) > 0 else float("inf")

    # Check if within standard buffer
    in_water_buffer = min_water_distance < 50  # Standard water protection buffer

    return {
        "checked": True,
        "min_water_distance_m": round(min_water_distance, 1),
        "in_water_buffer": in_water_buffer,
        "in_forbidden_zone": in_water_buffer,  # Water buffer is forbidden for most facilities
        "avoid_zones_checked": avoid_zones,
    }


def _get_suitability_level(score: float) -> str:
    """Convert score to suitability level"""
    if score >= 80:
        return "Excellent"
    elif score >= 60:
        return "Good"
    elif score >= 40:
        return "Moderate"
    elif score >= 20:
        return "Poor"
    else:
        return "Unsuitable"


def _generate_facility_recommendations(results: Dict[str, Any]) -> List[str]:
    """Generate recommendations based on validation results"""
    recommendations = []
    scores = results.get("scores", {})
    checks = results.get("checks", {})

    # Coverage recommendations
    if scores.get("coverage", 0) < 60:
        coverage_rate = checks.get("coverage", {}).get("coverage_rate", 0)
        recommendations.append(
            f"Coverage rate ({coverage_rate:.1%}) is low. "
            "Consider alternative locations closer to population centers."
        )

    # Population recommendations
    if scores.get("population", 0) < 100:
        pop_check = checks.get("population_adequacy", {})
        gap = pop_check.get("gap", 0)
        if gap > 0:
            recommendations.append(
                f"Served population ({pop_check.get('served_population', 0)}) "
                f"is below required ({pop_check.get('required_population', 0)}). "
                f"Gap: {gap} people."
            )

    # Proximity recommendations
    if scores.get("proximity", 0) < 70:
        proximity = checks.get("facility_proximity", {})
        min_dist = proximity.get("min_distance_m", 0)
        recommendations.append(
            f"Location too close ({min_dist}m) to existing facility. "
            "Consider spacing facilities for better coverage distribution."
        )

    # Constraint recommendations
    if scores.get("constraints", 0) == 0:
        recommendations.append(
            "Location is within a forbidden zone (e.g., water buffer). "
            "This location is NOT suitable for this facility type."
        )

    if not recommendations:
        recommendations.append(
            f"Location scored {results.get('overall_score', 0)}/100 "
            f"({results.get('suitability_level', 'Unknown')}). "
            "No major concerns identified."
        )

    return recommendations


def assess_ecological_sensitivity(
    study_area: Dict[str, Any],
    water_features: Optional[Dict[str, Any]] = None,
    slope_data: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Assess ecological sensitivity for planning

    Identifies sensitive areas based on:
    - Water body buffer zones
    - Slope gradients
    - Wetland/forest proximity
    - Composite sensitivity mapping

    Args:
        study_area: Study area boundary (GeoJSON Polygon)
        water_features: Water features layer (GeoJSON)
        slope_data: Slope gradient data (optional)
        **kwargs: Additional parameters
            - sensitivity_levels: List of sensitivity levels to calculate

    Returns:
        Dict with sensitivity assessment and zone classification
    """
    try:
        if not SPATIAL_AVAILABLE:
            return {
                "success": False,
                "error": "Ecological assessment requires spatial_analysis module"
            }

        # Convert study area
        study_gdf = geojson_to_geodataframe(study_area)
        if study_gdf is None:
            return {"success": False, "error": "Invalid study area GeoJSON"}

        sensitivity_zones = []
        total_sensitive_area = 0

        # 1. Water body buffer analysis
        if water_features:
            water_gdf = geojson_to_geodataframe(water_features)
            if water_gdf is not None:
                for factor_name, factor_config in ECOLOGICAL_SENSITIVITY_FACTORS.items():
                    if factor_name in ["water_body", "river", "wetland"]:
                        buffer_distance = factor_config.get("buffer_distance", 50)
                        weight = factor_config.get("weight", 0.2)

                        # Create buffer zones
                        buffer_result = calculate_buffer_zones(
                            water_features,
                            buffer_distance,
                            dissolve=True
                        )

                        if buffer_result.get("success"):
                            buffer_geojson = buffer_result["data"]["geojson"]
                            buffer_area = buffer_result["data"]["total_area_km2"]

                            sensitivity_zones.append({
                                "zone_type": factor_name,
                                "buffer_distance_m": buffer_distance,
                                "area_km2": buffer_area,
                                "sensitivity_weight": weight,
                                "description": factor_config.get("description", ""),
                                "geojson": buffer_geojson,
                            })
                            total_sensitive_area += buffer_area * weight

        # 2. Slope analysis (if data provided)
        if slope_data:
            slope_gdf = geojson_to_geodataframe(slope_data)
            if slope_gdf is not None:
                # Identify steep slopes (>25 degrees)
                steep_slope_factor = ECOLOGICAL_SENSITIVITY_FACTORS.get("slope_over_25", {})
                # This would require actual slope calculation - placeholder
                sensitivity_zones.append({
                    "zone_type": "steep_slope",
                    "description": "Areas with slope > 25 degrees",
                    "sensitivity_weight": steep_slope_factor.get("weight", 0.2),
                    "note": "Requires detailed slope data for precise calculation",
                })

        # 3. Calculate composite sensitivity
        study_area_km2 = 0
        try:
            projected = study_gdf.to_crs(epsg=3857)
            study_area_km2 = projected.geometry.area.sum() / 1_000_000
        except Exception:
            pass

        sensitivity_ratio = total_sensitive_area / study_area_km2 if study_area_km2 > 0 else 0

        # 4. Generate sensitivity classification
        sensitivity_class = _classify_sensitivity(sensitivity_ratio)

        # 5. Generate protection recommendations
        recommendations = _generate_ecological_recommendations(
            sensitivity_zones, sensitivity_class, sensitivity_ratio
        )

        return {
            "success": True,
            "data": {
                "study_area_km2": round(study_area_km2, 2),
                "sensitive_area_km2": round(total_sensitive_area, 2),
                "sensitivity_ratio": round(sensitivity_ratio, 4),
                "sensitivity_class": sensitivity_class,
                "sensitivity_zones": sensitivity_zones,
                "recommendations": recommendations,
                "metadata": {
                    "water_features_provided": water_features is not None,
                    "slope_data_provided": slope_data is not None,
                }
            }
        }

    except Exception as e:
        logger.error(f"[gis_validation] Ecological assessment failed: {e}")
        return {"success": False, "error": f"Ecological assessment failed: {str(e)}"}


def _classify_sensitivity(ratio: float) -> str:
    """Classify overall sensitivity level"""
    if ratio >= 0.3:
        return "Highly Sensitive"
    elif ratio >= 0.15:
        return "Moderately Sensitive"
    elif ratio >= 0.05:
        return "Low Sensitivity"
    else:
        return "Minimal Sensitivity"


def _generate_ecological_recommendations(
    zones: List[Dict[str, Any]],
    sensitivity_class: str,
    ratio: float
) -> List[str]:
    """Generate protection recommendations"""
    recommendations = []

    # Overall recommendation
    if sensitivity_class == "Highly Sensitive":
        recommendations.append(
            "Study area has high ecological sensitivity. "
            "Limit development to low-impact activities. "
            "Establish comprehensive protection zones."
        )
    elif sensitivity_class == "Moderately Sensitive":
        recommendations.append(
            "Study area requires careful planning. "
            "Avoid development in identified sensitive zones. "
            "Implement mitigation measures for buffer areas."
        )
    else:
        recommendations.append(
            "Study area has acceptable sensitivity level. "
            "Standard planning constraints apply."
        )

    # Zone-specific recommendations
    for zone in zones:
        zone_type = zone.get("zone_type", "")
        buffer_dist = zone.get("buffer_distance_m", 0)

        if zone_type in ["water_body", "river", "wetland"]:
            recommendations.append(
                f"Establish {buffer_dist}m protection buffer for {zone_type}. "
                "Prohibit construction and pollution sources within buffer."
            )

    return recommendations


def format_validation_result(result: Dict[str, Any]) -> str:
    """Format validation result to string"""
    if not result.get("success"):
        return f"Validation failed: {result.get('error', 'Unknown error')}"

    data = result.get("data", {})
    lines = ["GIS Validation Result:"]

    if "facility_type" in data:
        lines.append(f"- Facility: {data['facility_type']}")
        lines.append(f"- Overall score: {data.get('overall_score', 0)}/100")
        lines.append(f"- Suitability: {data.get('suitability_level', 'Unknown')}")

        scores = data.get("scores", {})
        lines.append("- Component scores:")
        for k, v in scores.items():
            lines.append(f"  * {k}: {v}")

        recommendations = data.get("recommendations", [])
        if recommendations:
            lines.append("- Recommendations:")
            for rec in recommendations[:3]:
                lines.append(f"  * {rec}")

    if "sensitivity_class" in data:
        lines.append(f"- Sensitivity class: {data['sensitivity_class']}")
        lines.append(f"- Sensitive area: {data.get('sensitive_area_km2', 0)} km2")
        lines.append(f"- Study area: {data.get('study_area_km2', 0)} km2")

    return "\n".join(lines)


__all__ = [
    "validate_facility_location",
    "assess_ecological_sensitivity",
    "format_validation_result",
    "FACILITY_SITING_STANDARDS",
    "ECOLOGICAL_SENSITIVITY_FACTORS",
]