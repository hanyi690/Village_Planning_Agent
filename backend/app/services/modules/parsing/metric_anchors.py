"""Metric anchors — deterministic extraction of precise values from reports.

Merges three previously separate extraction systems:
1. kg/builder.py CONSTRAINT_PATTERNS (7 metric_key -> constraint_id mappings)
2. summary/generator.py DIMENSION_EXTRACTION_RULES (Chinese regex per dimension)
3. summary/generator.py _extract_metrics_regex (generic numeric regex)

Priority: metrics field direct read > Chinese regex from text > hardcoded defaults.
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

    # Computed zone ratios (set after extraction)
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
        if self.zone_ratios:
            for zone, ratio in self.zone_ratios.items():
                result[f"{zone}比例"] = {"value": f"{ratio:.4f}", "source": "计算值"}
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


def normalize_metric_keys(
    metrics: Dict[str, Any],
    dimension_key: str,
) -> Dict[str, Any]:
    """Rename legacy field names to semantics-qualified names.

    Priority: _LEGACY_FIELD_MAP (dimension-specific) > _SCHEMA_FIELD_TO_ANCHOR > keep as-is.
    """
    dim_map = _LEGACY_FIELD_MAP.get(dimension_key, {})
    result = {}
    for k, v in metrics.items():
        if k in dim_map:
            result[dim_map[k]] = v
        elif k in _SCHEMA_FIELD_TO_ANCHOR:
            result[_SCHEMA_FIELD_TO_ANCHOR[k]] = v
        else:
            result[k] = v
    return result

# ---- Merged regex extraction from summary/generator.py ----

# _CS = clause separator chars — prevent .*? from crossing clause boundaries
# Includes 与/和/及 (conjunctions) that often separate different metrics in same sentence
_CS = r"[^，。；、与和及\n]"

DIMENSION_EXTRACTION_RULES: Dict[str, Dict[str, List[str]]] = {
    "land_use_planning": {
        "建设用地规模_公顷": [
            rf"建设用地{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
            rf"建设规模{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
            rf"村庄建设用地{_CS}*?(\d+\.?\d*)",
        ],
        "耕地保有量_公顷": [
            rf"(\d+\.?\d*)\s*(?:公顷|ha){_CS}*?耕地保有量",
            rf"耕地保有量{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
            rf"耕地保护{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "永久基本农田_公顷": [
            rf"(\d+\.?\d*)\s*(?:公顷|ha){_CS}*?永久基本农田",
            rf"永久基本农田{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
            rf"基本农田{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "生态保护红线面积": [
            rf"(\d+\.?\d*)\s*(?:公顷|ha){_CS}*?生态保护红线",
            rf"生态保护红线{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)?",
            rf"生态红线{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "新增建设用地_公顷": [
            rf"新增建设{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "总用地面积_公顷": [
            rf"总用地面积{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
            rf"总面积{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
            r"\| 合计 \| (\d+\.?\d*)",  # markdown table: | 合计 | 2352.89 |
            r"\| 总计 \| (\d+\.?\d*)",  # markdown table: | 总计 | xxx |
        ],
    },
    "ecological": {
        "生态保护红线面积": [
            rf"(\d+\.?\d*)\s*(?:公顷|ha){_CS}*?生态保护红线",
            rf"生态保护红线{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)?",
            rf"生态红线{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "林地保有量_公顷": [
            rf"(\d+\.?\d*)\s*(?:公顷|ha){_CS}*?林地保有量",
            rf"林地保有量{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "森林覆盖率_百分比": [
            rf"森林覆盖率{_CS}*?(\d+\.?\d*)\s*%",
        ],
    },
    "settlement_planning": {
        "建设用地规模_公顷": [
            rf"建设用地{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "规划期末人口": [
            rf"规划期末{_CS}*?人口{_CS}*?(\d+)",
            rf"规划人口{_CS}*?(\d+)",
            rf"常住人口{_CS}*?(\d+)\s*人",
        ],
        "人均建设用地": [
            rf"人均建设用地{_CS}*?(\d+\.?\d*)\s*m",
        ],
    },
    "superior_planning": {
        "生态保护红线面积": [
            rf"(\d+\.?\d*)\s*(?:公顷|ha){_CS}*?生态保护红线",
            rf"生态保护红线{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)?",
        ],
        "耕地保有量_公顷": [
            rf"(\d+\.?\d*)\s*(?:公顷|ha){_CS}*?耕地保有量",
            rf"耕地保有量{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
            rf"基本农田{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
        ],
        "建设用地规模_公顷": [
            rf"建设用地{_CS}*?(\d+\.?\d*)\s*(?:公顷|ha)",
            rf"城镇开发边界{_CS}*?(\d+\.?\d*)",
        ],
    },
    "disaster_prevention": {
        "地质灾害隐患点_处": [
            rf"地质灾害隐患{_CS}*?(\d+)\s*处",
            rf"隐患点{_CS}*?(\d+)\s*处",
            rf"(\d+)\s*处{_CS}*?地质灾害隐患",
        ],
    },
}


def extract_metric_anchors(
    reports: Dict[str, Dict[str, Any]],
    gis_data: Optional[Dict[str, Any]] = None,
) -> MetricAnchors:
    """Extract precise metric values from reports and GIS data.

    Four-tier extraction (highest priority first):
    1. GIS GeoJSON direct computation (most accurate — spatial measurement)
    2. Direct read from reports.metrics (schema-qualified field names)
    3. Chinese regex from report content (DIMENSION_EXTRACTION_RULES)
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
    _extract_from_regex(anchors, reports)

    # Compute zone ratios if we have the data
    _compute_zone_ratios(anchors)

    logger.info(
        "[metric_anchors] Extracted: total=%.1f, construction=%.1f, farmland=%.1f, eco=%.1f, confidence=%.2f",
        anchors.total_area_ha or 0,
        anchors.construction_area_ha or 0,
        anchors.farmland_area_ha or 0,
        anchors.ecological_area_ha or 0,
        anchors.confidence,
    )

    return anchors


def extract_dimension_anchors(
    dimension_key: str,
    content: str,
    metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract metric anchors for a single dimension.

    Used by summary/generator.py for seed_metrics generation.
    Returns a flat dict of metric_key -> value (no MetricAnchors object).

    Priority: metrics dict direct read > Chinese regex from content.

    Args:
        dimension_key: Dimension key, e.g. "land_use_planning".
        content: Report text content.
        metrics: Optional pre-extracted metrics dict from summary.

    Returns:
        Dict of metric_key -> extracted value.
    """
    result: Dict[str, Any] = {}

    # Pass 1: Direct metrics read (Chinese metric_key names)
    if metrics:
        for pattern in CONSTRAINT_PATTERNS:
            metric_key = pattern["metric_key"]
            value = metrics.get(metric_key)
            if value is not None:
                try:
                    result[metric_key] = float(value)
                except (ValueError, TypeError):
                    pass

        # Also try schema-qualified field names
        for schema_field, anchor_field in _SCHEMA_FIELD_TO_ANCHOR.items():
            value = metrics.get(schema_field)
            if value is not None:
                # Store with anchor field name to avoid duplicates
                if anchor_field not in result:
                    try:
                        result[anchor_field] = float(value)
                    except (ValueError, TypeError):
                        pass

    # Pass 2: Chinese regex from content
    rules = DIMENSION_EXTRACTION_RULES.get(dimension_key, {})
    for metric_key, patterns in rules.items():
        if metric_key in result:
            continue  # Already found via metrics
        for pattern in patterns:
            m = re.search(pattern, content)
            if m:
                try:
                    val = m.group(1)
                    float_val = float(val) if "." in val else int(val)
                    result[metric_key] = float(float_val)
                except (ValueError, TypeError):
                    pass
                break

    # Generic numeric regex (from old _extract_metrics_regex)
    generic_patterns = [
        (r'([\d.]+)\s*公顷', 'area_ha'),
        (r'([\d.]+)\s*亩', 'area_mu'),
        (r'(\d+)\s*人', 'population'),
        (r'(\d+)\s*户', 'households'),
        (r'([\d.]+)\s*%', 'percentage'),
        (r'([\d.]+)\s*万元', 'amount_wan_yuan'),
        (r'([\d.]+)\s*km', 'length_km'),
        (r'([\d.]+)\s*m[²2]', 'area_sqm'),
    ]
    for pat, key in generic_patterns:
        if key in result:
            continue
        m = re.search(pat, content)
        if m:
            val = m.group(1)
            result[key] = float(val) if '.' in val else int(val)

    return result


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


def _extract_from_regex(
    anchors: MetricAnchors,
    reports: Dict[str, Dict[str, Any]],
) -> None:
    """Pass 2: Extract values from report content using Chinese regex."""
    for dim_key, report in reports.items():
        content = report.get("content", "")
        if not content:
            continue

        rules = DIMENSION_EXTRACTION_RULES.get(dim_key, {})
        if not rules:
            continue

        for metric_key, patterns in rules.items():
            anchor_field = _METRIC_KEY_TO_FIELD.get(metric_key)
            if not anchor_field:
                continue
            if getattr(anchors, anchor_field) is not None:
                continue  # Already found via metrics

            for pattern in patterns:
                m = re.search(pattern, content)
                if m:
                    try:
                        val = m.group(1)
                        float_val = float(val) if "." in val else int(val)
                        setattr(anchors, anchor_field, float(float_val))
                        source_field = _FIELD_TO_SOURCE[anchor_field]
                        setattr(anchors, source_field, f"{dim_key}.regex.{metric_key}")
                    except (ValueError, TypeError):
                        pass
                    break


def _compute_zone_ratios(anchors: MetricAnchors) -> None:
    """Compute precise zone area ratios from anchors."""
    if anchors.total_area_ha and anchors.total_area_ha > 0:
        total = anchors.total_area_ha
        if anchors.construction_area_ha is not None:
            anchors.zone_ratios["村庄建设区"] = anchors.construction_area_ha / total
        if anchors.farmland_area_ha is not None:
            anchors.zone_ratios["农田保护区"] = anchors.farmland_area_ha / total
        if anchors.ecological_area_ha is not None:
            anchors.zone_ratios["生态保护区"] = anchors.ecological_area_ha / total
        if anchors.permanent_farmland_ha is not None:
            anchors.zone_ratios["永久基本农田"] = anchors.permanent_farmland_ha / total
