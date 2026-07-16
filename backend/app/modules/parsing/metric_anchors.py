"""Metric anchors — deterministic extraction of precise values from GIS data.

GIS GeoJSON computation is the primary extraction path (zero LLM, deterministic).
Regex-based text extraction has been removed — Instructor handles text extraction.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MetricAnchors:
    """Precise metric values extracted deterministically from reports.

    Each value has a source field for auditability.
    """

    total_area_ha: Optional[float] = None
    total_area_source: str = ""

    construction_area_ha: Optional[float] = None
    construction_source: str = ""

    farmland_area_ha: Optional[float] = None
    farmland_source: str = ""

    ecological_area_ha: Optional[float] = None
    ecological_source: str = ""

    permanent_farmland_ha: Optional[float] = None
    permanent_farmland_source: str = ""

    new_construction_ha: Optional[float] = None
    new_construction_source: str = ""

    forest_coverage_pct: Optional[float] = None
    forest_coverage_source: str = ""

    forest_land_ha: Optional[float] = None
    forest_land_source: str = ""

    # Computed planning zone targets (4-zone 土地用途分区, set after extraction)
    zone_ratios: Dict[str, float] = field(default_factory=dict)

    @property
    def confidence(self) -> float:
        """Confidence score based on how many key anchors were found."""
        key_fields = [
            self.total_area_ha,
            self.construction_area_ha,
            self.farmland_area_ha,
            self.ecological_area_ha,
        ]
        found = sum(1 for v in key_fields if v is not None)
        return found / len(key_fields)

    @property
    def confidence_label(self) -> str:
        """Confidence as qualitative label for ParseTrace."""
        score = self.confidence
        if score >= 0.75:
            return "high"
        elif score >= 0.5:
            return "medium"
        return "low"

    def to_anchor_dict(self) -> Dict[str, Any]:
        """Convert to dict suitable for prompt injection."""
        result = {}
        mapping = {
            "总面积": (self.total_area_ha, self.total_area_source),
            "建设用地": (self.construction_area_ha, self.construction_source),
            "耕地保有量": (self.farmland_area_ha, self.farmland_source),
            "生态红线": (self.ecological_area_ha, self.ecological_source),
            "永久基本农田": (self.permanent_farmland_ha, self.permanent_farmland_source),
            "新增建设用地": (self.new_construction_ha, self.new_construction_source),
            "森林覆盖率": (self.forest_coverage_pct, self.forest_coverage_source),
            "林地保有量": (self.forest_land_ha, self.forest_land_source),
        }
        for key, (value, source) in mapping.items():
            if value is not None:
                result[key] = {"value": value, "unit": "ha" if "率" not in key else "%", "source": source}
        # Include 土地用途分区 targets (from DLBM re-mapping, not direct area)
        if self.zone_ratios:
            for zone, ratio in self.zone_ratios.items():
                result[f"{zone}比例"] = {"value": f"{ratio:.4f}", "source": "规划分区目标"}
                if self.total_area_ha:
                    result[f"{zone}面积"] = {
                        "value": round(ratio * self.total_area_ha, 1),
                        "unit": "ha",
                        "source": "DLBM重分类",
                    }
        return result


# ---- Merged constraint patterns from kg/builder.py ----
# metric_key -> (constraint_id, target_field, operator)

CONSTRAINT_PATTERNS: List[Dict[str, str]] = [
    {"metric_key": "建设用地规模_公顷", "constraint_id": "construction_cap", "field": "construction_area_ha"},
    {"metric_key": "耕地保有量_公顷", "constraint_id": "farmland_min", "field": "farmland_area_ha"},
    {"metric_key": "永久基本农田_公顷", "constraint_id": "permanent_farmland_min", "field": "permanent_farmland_ha"},
    {"metric_key": "生态保护红线面积", "constraint_id": "ecological_redline_min", "field": "ecological_area_ha"},
    {"metric_key": "森林覆盖率_百分比", "constraint_id": "forest_coverage_min", "field": "forest_coverage_pct"},
    {"metric_key": "新增建设用地_公顷", "constraint_id": "construction_expansion", "field": "new_construction_ha"},
    {"metric_key": "林地保有量_公顷", "constraint_id": "forest_land_min", "field": "forest_land_ha"},
]

# metric_key -> anchor field name on MetricAnchors
_METRIC_KEY_TO_FIELD: Dict[str, str] = {
    "建设用地规模_公顷": "construction_area_ha",
    "耕地保有量_公顷": "farmland_area_ha",
    "永久基本农田_公顷": "permanent_farmland_ha",
    "生态保护红线面积": "ecological_area_ha",
    "森林覆盖率_百分比": "forest_coverage_pct",
    "新增建设用地_公顷": "new_construction_ha",
    "林地保有量_公顷": "forest_land_ha",
    "总用地面积_公顷": "total_area_ha",
}

# anchor field -> source field name on MetricAnchors
_FIELD_TO_SOURCE: Dict[str, str] = {
    "total_area_ha": "total_area_source",
    "construction_area_ha": "construction_source",
    "farmland_area_ha": "farmland_source",
    "permanent_farmland_ha": "permanent_farmland_source",
    "ecological_area_ha": "ecological_source",
    "new_construction_ha": "new_construction_source",
    "forest_coverage_pct": "forest_coverage_source",
    "forest_land_ha": "forest_land_source",
}

# Also support the schema-qualified field names from summary module
_SCHEMA_FIELD_TO_ANCHOR: Dict[str, str] = {
    "current_construction_ha": "construction_area_ha",
    "planned_construction_ha": "construction_area_ha",
    "current_farmland_ha": "farmland_area_ha",
    "planned_farmland_ha": "farmland_area_ha",
    "min_ecological_redline_ha": "ecological_area_ha",
    "planned_ecological_ha": "ecological_area_ha",
    "ecological_area_ha": "ecological_area_ha",
    "min_farmland_protection_ha": "permanent_farmland_ha",
    "max_construction_ha": "construction_area_ha",
    "total_area_ha": "total_area_ha",
    "forest_coverage_rate": "forest_coverage_pct",
}

# Legacy field names that LLM may output, mapped to semantics-qualified names.
# Used by _normalize_metric_keys() for LLM output normalization.
# Dimension-specific overrides take priority over _SCHEMA_FIELD_TO_ANCHOR.
_LEGACY_FIELD_MAP: Dict[str, Dict[str, str]] = {
    "land_use": {
        "construction_area_ha": "current_construction_ha",
        "farmland_area_ha": "current_farmland_ha",
        "farmland_ha": "current_farmland_ha",
        "construction_ha": "current_construction_ha",
    },
    "settlement_planning": {
        "construction_area_ha": "current_construction_ha",
        "planned_construction_area_ha": "planned_construction_ha",
        "target_population": "planned_population",
    },
    "land_use_planning": {
        "construction_area_ha": "current_construction_ha",
        "planned_construction_area_ha": "planned_construction_ha",
    },
    "ecological_green": {
        "ecological_redline_ha": "min_ecological_redline_ha",
    },
    "ecological": {
        "ecological_redline_ha": "min_ecological_redline_ha",
    },
    "superior_planning": {
        "ecological_redline_ha": "min_ecological_redline_ha",
        "farmland_protection_ha": "min_farmland_protection_ha",
        "construction_ha": "max_construction_ha",
    },
}


def extract_metric_anchors(
    reports: Dict[str, Dict[str, Any]],
    gis_data: Optional[Dict[str, Any]] = None,
) -> MetricAnchors:
    """Extract precise metric values from reports and GIS data.

    Three-tier extraction (highest priority first):
    1. GIS GeoJSON direct computation (most accurate — spatial measurement)
    2. Direct read from reports.metrics (schema-qualified field names)
    4. Default values (none — caller should handle missing)

    Args:
        reports: Dict of dimension_key -> {content, summary: {metrics, text_summary, ...}}
        gis_data: Optional GIS data dict with keys:
            - boundary_geojson: Village boundary (MJ field for total area)
            - landuse_current_geojson: Landuse parcels (DLMJ+DLBM for area by type)
            - ecological_protection_geojson: Ecological redline (MJ field)
            - construction_zone_geojson: Construction zone (MJ field)
            - hazard_points_geojson: Hazard points (feature count)

    Returns:
        MetricAnchors with extracted values and source tracking.
    """
    anchors = MetricAnchors()

    # Pass 0: GIS GeoJSON direct computation (highest priority)
    if gis_data:
        _extract_from_gis(anchors, gis_data)

    # Pass 1: Direct metrics read (most reliable text source)
    _extract_from_metrics(anchors, reports)

    # Pass 2: Regex from content (fill gaps)

    # Compute zone ratios if we have the data
    _compute_zone_ratios(anchors, gis_data)

    logger.info(
        "[metric_anchors] Extracted: total=%.1f, construction=%.1f, farmland=%.1f, eco=%.1f, confidence=%.2f",
        anchors.total_area_ha or 0,
        anchors.construction_area_ha or 0,
        anchors.farmland_area_ha or 0,
        anchors.ecological_area_ha or 0,
        anchors.confidence,
    )

    return anchors


def extract_gis_anchors(
    dimension_key: str,
    content: str = "",
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract metric anchors from GIS GeoJSON only (Layer 0).

    Returns a flat dict of metric_key -> value. Only computes values
    from GeoJSON properties — no regex, no LLM.

    Args:
        dimension_key: Dimension key, e.g. "land_use_planning".
        content: Report text (unused, kept for API compat).
        gis_data: Optional GIS data dict. If None, returns empty dict.

    Returns:
        Dict of metric_key -> extracted value.
    """
    if not gis_data:
        return {}

    anchors = MetricAnchors()
    _extract_from_gis(anchors, gis_data)
    _compute_zone_ratios(anchors, gis_data)

    result: Dict[str, Any] = {}
    if anchors.total_area_ha is not None:
        result["total_area_ha"] = anchors.total_area_ha
    if anchors.construction_area_ha is not None:
        result["construction_area_ha"] = anchors.construction_area_ha
    if anchors.farmland_area_ha is not None:
        result["farmland_area_ha"] = anchors.farmland_area_ha
    if anchors.ecological_area_ha is not None:
        result["ecological_area_ha"] = anchors.ecological_area_ha
    if anchors.permanent_farmland_ha is not None:
        result["permanent_farmland_ha"] = anchors.permanent_farmland_ha
    if anchors.new_construction_ha is not None:
        result["new_construction_ha"] = anchors.new_construction_ha
    if anchors.forest_coverage_pct is not None:
        result["forest_coverage_pct"] = anchors.forest_coverage_pct
    if anchors.forest_land_ha is not None:
        result["forest_land_ha"] = anchors.forest_land_ha
    for zone, ratio in anchors.zone_ratios.items():
        result[f"zone_ratio_{zone}"] = ratio
        if anchors.total_area_ha:
            result[f"zone_area_{zone}"] = round(ratio * anchors.total_area_ha, 1)

    logger.info(
        "[metric_anchors] GIS anchors for %s: %d metrics extracted",
        dimension_key, len(result),
    )
    return result


def extract_dimension_anchors(
    dimension_key: str,
    content: str,
    metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """DEPRECATED: Use Instructor-based extraction via generate_structured_summary.

    This function is kept only for backward compatibility. It no longer
    performs regex extraction — returns metrics dict as-is if provided.
    Will be removed in a future version.
    """
    return dict(metrics) if metrics else {}


# DLBM prefixes for land use classification (GB/T 21010-2017)
_DLBM_FARMLAND = {"01", "11"}  # 耕地(01), 水浇地/旱地 subset; 水田(11)
_DLBM_CONSTRUCTION = {"07", "08", "09", "21", "22"}  # 住宅/公共/交通/商服/工矿
_DLBM_ECOLOGICAL = {"03", "31"}  # 林地(03), 生态(31)


def _extract_from_gis(
    anchors: MetricAnchors,
    gis_data: Dict[str, Any],
) -> None:
    """Pass 0: Extract values from GIS GeoJSON (highest priority — spatial measurement)."""
    # Total area from boundary GeoJSON
    boundary = gis_data.get("boundary_geojson")
    if boundary and anchors.total_area_ha is None:
        total = _sum_geojson_field(boundary, "MJ")
        if total and total > 0:
            anchors.total_area_ha = total
            anchors.total_area_source = "gis.boundary.MJ"

    # Area breakdown from landuse_current GeoJSON (DLBM-based classification)
    landuse = gis_data.get("landuse_current_geojson")
    if landuse:
        area_by_prefix = _sum_landuse_by_dlbm_prefix(landuse)

        if anchors.construction_area_ha is None:
            val = sum(area_by_prefix.get(p, 0) for p in _DLBM_CONSTRUCTION)
            if val > 0:
                anchors.construction_area_ha = val
                anchors.construction_source = "gis.landuse_current.DLBM"

        if anchors.farmland_area_ha is None:
            val = sum(area_by_prefix.get(p, 0) for p in _DLBM_FARMLAND)
            if val > 0:
                anchors.farmland_area_ha = val
                anchors.farmland_source = "gis.landuse_current.DLBM"

        if anchors.ecological_area_ha is None:
            val = sum(area_by_prefix.get(p, 0) for p in _DLBM_ECOLOGICAL)
            if val > 0:
                anchors.ecological_area_ha = val
                anchors.ecological_source = "gis.landuse_current.DLBM"

    # Ecological redline from protection zone GeoJSON
    eco_protection = gis_data.get("ecological_protection_geojson")
    if eco_protection and anchors.ecological_area_ha is None:
        val = _sum_geojson_field(eco_protection, "MJ")
        if val and val > 0:
            anchors.ecological_area_ha = val
            anchors.ecological_source = "gis.ecological_protection.MJ"

    # Hazard points count
    hazard = gis_data.get("hazard_points_geojson")
    if hazard:
        count = len(hazard.get("features", []))
        if count > 0:
            # Store in metrics dict (no dedicated anchor field for hazard count)
            logger.info("[metric_anchors] GIS hazard_points count: %d", count)


def _sum_geojson_field(geojson: Dict[str, Any], field: str) -> Optional[float]:
    """Sum a numeric field from GeoJSON feature properties."""
    total = 0.0
    found = False
    for feature in geojson.get("features", []):
        val = feature.get("properties", {}).get(field)
        if val is not None:
            try:
                total += float(val)
                found = True
            except (ValueError, TypeError):
                pass
    return total if found else None


def _sum_landuse_by_dlbm_prefix(landuse_geojson: Dict[str, Any]) -> Dict[str, float]:
    """Sum DLMJ (sqm) by DLBM 2-digit prefix, return as hectares."""
    from collections import defaultdict
    by_prefix: Dict[str, float] = defaultdict(float)
    for feature in landuse_geojson.get("features", []):
        props = feature.get("properties", {})
        dlbm = str(props.get("DLBM", ""))
        dlmj = props.get("DLMJ")
        if dlbm and dlmj is not None:
            try:
                by_prefix[dlbm[:2]] += float(dlmj)
            except (ValueError, TypeError):
                pass
    # Convert sqm to ha
    return {k: v / 10000 for k, v in by_prefix.items()}


def _extract_from_metrics(
    anchors: MetricAnchors,
    reports: Dict[str, Dict[str, Any]],
) -> None:
    """Pass 1: Read values directly from reports.metrics dict."""
    for dim_key, report in reports.items():
        metrics = report.get("summary", {}).get("metrics", {})
        if not metrics:
            continue

        # Try Chinese metric_key names (from CONSTRAINT_PATTERNS)
        for pattern in CONSTRAINT_PATTERNS:
            metric_key = pattern["metric_key"]
            anchor_field = _METRIC_KEY_TO_FIELD[metric_key]

            if getattr(anchors, anchor_field) is not None:
                continue  # Already found

            value = metrics.get(metric_key)
            if value is not None:
                try:
                    float_val = float(value)
                    setattr(anchors, anchor_field, float_val)
                    source_field = _FIELD_TO_SOURCE[anchor_field]
                    setattr(anchors, source_field, f"{dim_key}.metrics.{metric_key}")
                except (ValueError, TypeError):
                    pass

        # Try schema-qualified field names (from summary module)
        for schema_field, anchor_field in _SCHEMA_FIELD_TO_ANCHOR.items():
            if getattr(anchors, anchor_field) is not None:
                continue

            value = metrics.get(schema_field)
            if value is not None:
                try:
                    float_val = float(value)
                    setattr(anchors, anchor_field, float_val)
                    source_field = _FIELD_TO_SOURCE[anchor_field]
                    setattr(anchors, source_field, f"{dim_key}.metrics.{schema_field}")
                except (ValueError, TypeError):
                    pass

        # Special: total_area from land_use_planning or land_use
        if dim_key in ("land_use_planning", "land_use"):
            if anchors.total_area_ha is None and metrics.get("total_area_ha"):
                try:
                    anchors.total_area_ha = float(metrics["total_area_ha"])
                    anchors.total_area_source = f"{dim_key}.metrics.total_area_ha"
                except (ValueError, TypeError):
                    pass


def _compute_zone_ratios(anchors: MetricAnchors, gis_data: Optional[Dict[str, Any]] = None) -> None:
    """Compute 土地用途分区(4区) targets by re-mapping DLBM to planning zones.

    NOTE: This is NOT a direct mapping from DLBM area measurements!
    - 耕地面积(DLBM 01/11) ≠ 农田保护区面积
    - 建设用地面积(DLBM 07/08...) ≠ 村庄建设区面积
    - 生态面积(DLBM 03/31) ≠ 生态保护区面积

    Planning zones are defined by policy (三区三线), not just DLBM.
    We compute targets by re-mapping each parcel via DLBM_TO_PLANNING_ZONE.
    """
    landuse = gis_data.get("landuse_current_geojson") if gis_data else None
    if not landuse or not anchors.total_area_ha or anchors.total_area_ha <= 0:
        # Fallback: use DLBM prefix-based approximation (less accurate)
        total = anchors.total_area_ha
        if total and total > 0:
            if anchors.farmland_area_ha is not None:
                anchors.zone_ratios["农田保护区"] = anchors.farmland_area_ha / total
            if anchors.ecological_area_ha is not None:
                anchors.zone_ratios["生态保护区"] = anchors.ecological_area_ha / total
            if anchors.construction_area_ha is not None:
                anchors.zone_ratios["村庄建设区"] = anchors.construction_area_ha / total
            # Fill 一般农业区 as remainder
            known = sum(anchors.zone_ratios.values())
            if known < 1.0:
                anchors.zone_ratios["一般农业区"] = 1.0 - known
        return

    # Primary: re-map each parcel via DLBM_TO_PLANNING_ZONE for accurate 4-zone areas
    from app.modules.gis.schema import dlbm_to_planning_zone

    zone_areas: Dict[str, float] = {}
    for feature in landuse.get("features", []):
        props = feature.get("properties", {})
        dlbm = str(props.get("DLBM", ""))
        dlmj = props.get("DLMJ")
        if not dlbm or dlmj is None:
            continue
        try:
            area_ha = float(dlmj) / 10000  # DLMJ is in sqm
            zone_name = dlbm_to_planning_zone(dlbm)
            zone_areas[zone_name] = zone_areas.get(zone_name, 0.0) + area_ha
        except (ValueError, TypeError):
            continue

    # Override ecological protection zone with MJ field if available
    eco_protection = gis_data.get("ecological_protection_geojson") if gis_data else None
    if eco_protection and eco_protection.get("features"):
        eco_mj = 0.0
        for feat in eco_protection.get("features", []):
            mj = feat.get("properties", {}).get("MJ")
            if mj is not None:
                try:
                    eco_mj += float(mj)
                except (ValueError, TypeError):
                    pass
        if eco_mj > 0:
            zone_areas["生态保护区"] = eco_mj / 10000

    # Override farmland protection with MJ field if available
    farmland_protection = gis_data.get("farmland_protection_geojson") if gis_data else None
    if farmland_protection and farmland_protection.get("features"):
        fp_mj = 0.0
        for feat in farmland_protection.get("features", []):
            mj = feat.get("properties", {}).get("MJ")
            if mj is not None:
                try:
                    fp_mj += float(mj)
                except (ValueError, TypeError):
                    pass
        if fp_mj > 0:
            zone_areas["农田保护区"] = fp_mj / 10000

    total = anchors.total_area_ha
    anchors.zone_ratios = {}
    for zone_name in ["农田保护区", "生态保护区", "村庄建设区", "一般农业区"]:
        area = zone_areas.get(zone_name, 0.0)
        anchors.zone_ratios[zone_name] = area / total if total > 0 else 0.0

    # Normalize: ensure sum ≈ 1.0
    ratio_sum = sum(anchors.zone_ratios.values())
    if ratio_sum > 0 and abs(ratio_sum - 1.0) > 0.01:
        for zone_name in anchors.zone_ratios:
            anchors.zone_ratios[zone_name] /= ratio_sum

    logger.info(
        "[metric_anchors] Planning zone targets (4区): "
        + ", ".join(f"{k}={v:.2%} ({v * total:.1f}ha)" for k, v in anchors.zone_ratios.items())
    )
