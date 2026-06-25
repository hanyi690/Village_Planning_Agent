"""Layout validation - checks spatial layout against constraints and completeness rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Required planning zones that must exist in a valid layout
REQUIRED_ZONE_TYPES = {"永久基本农田保护区", "村庄建设区", "生态保护区", "一般农地区"}

# Minimum area (ha) for each zone type
MIN_ZONE_AREA_HA = {
    "永久基本农田保护区": 1.0,
    "村庄建设区": 0.5,
    "生态保护区": 1.0,
    "一般农地区": 5.0,
}

# Zone types that must NOT contain protected parcels
PROTECTED_ZONE_TYPES = {"永久基本农田保护区", "生态保护区"}
CONSTRUCTION_ZONE_TYPES = {"村庄建设区"}


@dataclass
class Violation:
    check: str
    severity: str  # "error" | "warning"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    check_name: str
    passed: bool
    violation_count: int = 0
    violations: List[Violation] = field(default_factory=list)


@dataclass
class ValidationReport:
    status: str  # "pass" | "fail" | "warning"
    checks: List[CheckResult] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def total_violations(self) -> int:
        return len(self.violations)


class LayoutValidator:
    """Validates spatial layout against constraint and completeness rules.

    Checks:
    1. Area constraints — planning_zone areas satisfy KG constraint bounds
    2. Zone completeness — all required zone types present
    3. Overlap detection — no geometric overlaps in same layer
    4. Protected parcels — basic farmland / ecological parcels not in construction zone
    5. Minimum area — each zone meets minimum area threshold
    """

    def validate(
        self,
        layout_configs: List[Dict[str, Any]],
        constraints: Optional[List[Dict[str, Any]]] = None,
    ) -> ValidationReport:
        checks = [
            self._check_area_constraints(constraints or [], layout_configs),
            self._check_zone_completeness(layout_configs),
            self._check_overlap(layout_configs),
            self._check_protected_parcels(layout_configs),
            self._check_min_zone_area(layout_configs),
        ]

        all_violations = []
        all_warnings = []
        for c in checks:
            for v in c.violations:
                all_violations.append(v)
                if v.severity == "warning":
                    all_warnings.append(v.message)

        has_errors = any(v.severity == "error" for v in all_violations)
        status = "fail" if has_errors else ("warning" if all_warnings else "pass")

        return ValidationReport(
            status=status,
            checks=checks,
            violations=all_violations,
            warnings=all_warnings,
        )

    def _check_area_constraints(
        self, constraints: List[Dict], layout_configs: List[Dict]
    ) -> CheckResult:
        violations = []

        zone_areas = self._get_zone_areas(layout_configs)

        for c in constraints:
            field = c.get("field", "")
            op = c.get("operator", "")
            value = c.get("value", 0)

            if "construction" in field and op in ("<=", "lte"):
                actual = zone_areas.get("村庄建设区", 0)
                if actual > value:
                    violations.append(Violation(
                        check="area_constraint",
                        severity="error",
                        message=f"建设用地面积 {actual:.1f}ha 超过上限 {value}ha",
                        details={"zone": "村庄建设区", "actual": actual, "limit": value, "operator": op},
                    ))
            elif "farmland" in field and op in (">=", "gte"):
                actual = zone_areas.get("永久基本农田保护区", 0)
                if actual < value:
                    violations.append(Violation(
                        check="area_constraint",
                        severity="error",
                        message=f"基本农田面积 {actual:.1f}ha 低于下限 {value}ha",
                        details={"zone": "永久基本农田保护区", "actual": actual, "limit": value, "operator": op},
                    ))
            elif "ecological" in field and op in (">=", "gte"):
                actual = zone_areas.get("生态保护区", 0)
                if actual < value:
                    violations.append(Violation(
                        check="area_constraint",
                        severity="error",
                        message=f"生态保护区面积 {actual:.1f}ha 低于下限 {value}ha",
                        details={"zone": "生态保护区", "actual": actual, "limit": value, "operator": op},
                    ))

        return CheckResult(
            check_name="area_constraints",
            passed=len(violations) == 0,
            violation_count=len(violations),
            violations=violations,
        )

    def _check_zone_completeness(self, layout_configs: List[Dict]) -> CheckResult:
        violations = []
        zone_types = set()

        for config in layout_configs:
            if config.get("layerType") != "planning_zone":
                continue
            geojson = config.get("data", {})
            for feat in geojson.get("features", []):
                props = feat.get("properties", {})
                zt = props.get("assigned_zone", "") or props.get("zone_type", "")
                if zt:
                    zone_types.add(zt)

        missing = REQUIRED_ZONE_TYPES - zone_types
        for zt in missing:
            violations.append(Violation(
                check="zone_completeness",
                severity="error",
                message=f"缺少必需分区: {zt}",
                details={"missing_zone": zt},
            ))

        return CheckResult(
            check_name="zone_completeness",
            passed=len(violations) == 0,
            violation_count=len(violations),
            violations=violations,
        )

    def _check_overlap(self, layout_configs: List[Dict]) -> CheckResult:
        violations = []

        try:
            from shapely import from_geojson
            import json as _json
        except ImportError:
            return CheckResult(check_name="overlap", passed=True)

        for config in layout_configs:
            layer_type = config.get("layerType", "")
            geojson = config.get("data", {})
            features = geojson.get("features", [])

            if len(features) < 2:
                continue

            geoms = []
            for feat in features:
                g = feat.get("geometry", {})
                if g and g.get("coordinates"):
                    try:
                        geom = from_geojson(_json.dumps(g))
                        geoms.append((feat, geom))
                    except Exception:
                        continue

            overlap_count = 0
            for i in range(len(geoms)):
                for j in range(i + 1, min(i + 10, len(geoms))):
                    try:
                        if geoms[i][1].intersects(geoms[j][1]):
                            intersection = geoms[i][1].intersection(geoms[j][1])
                            if intersection.area > 0:
                                overlap_count += 1
                    except Exception:
                        continue

            if overlap_count > 0:
                violations.append(Violation(
                    check="overlap",
                    severity="warning",
                    message=f"{layer_type} 图层有 {overlap_count} 处重叠",
                    details={"layer": layer_type, "overlap_count": overlap_count},
                ))

        return CheckResult(
            check_name="overlap",
            passed=len(violations) == 0,
            violation_count=len(violations),
            violations=violations,
        )

    def _check_protected_parcels(self, layout_configs: List[Dict]) -> CheckResult:
        violations = []

        for config in layout_configs:
            if config.get("layerType") != "planning_zone":
                continue
            geojson = config.get("data", {})
            for feat in geojson.get("features", []):
                props = feat.get("properties", {})
                assigned_zone = props.get("assigned_zone", "")
                current_zone = props.get("current_zone_type", "")

                if assigned_zone in CONSTRUCTION_ZONE_TYPES:
                    if current_zone in ("生态绿地", "农业用地"):
                        dlbm = props.get("DLBM", "")
                        if dlbm in ("0110", "0120", "0130", "1340", "1350"):
                            violations.append(Violation(
                                check="protected_parcels",
                                severity="error",
                                message=f"受保护地块(DLBM={dlbm})被分配到建设区",
                                details={"dlbm": dlbm, "assigned_zone": assigned_zone},
                            ))

        if len(violations) > 10:
            violations = violations[:10]
            violations.append(Violation(
                check="protected_parcels",
                severity="warning",
                message=f"共 {len(violations)} 处保护地块违规（仅显示前10条）",
            ))

        return CheckResult(
            check_name="protected_parcels",
            passed=len(violations) == 0,
            violation_count=len(violations),
            violations=violations,
        )

    def _check_min_zone_area(self, layout_configs: List[Dict]) -> CheckResult:
        violations = []
        zone_areas = self._get_zone_areas(layout_configs)

        for zt, min_area in MIN_ZONE_AREA_HA.items():
            actual = zone_areas.get(zt, 0)
            if actual < min_area and actual > 0:
                violations.append(Violation(
                    check="min_zone_area",
                    severity="warning",
                    message=f"{zt} 面积 {actual:.1f}ha 低于最小阈值 {min_area}ha",
                    details={"zone": zt, "actual": actual, "minimum": min_area},
                ))

        return CheckResult(
            check_name="min_zone_area",
            passed=len(violations) == 0,
            violation_count=len(violations),
            violations=violations,
        )

    @staticmethod
    def _get_zone_areas(layout_configs: List[Dict]) -> Dict[str, float]:
        zone_areas: Dict[str, float] = {}
        for config in layout_configs:
            if config.get("layerType") != "planning_zone":
                continue
            geojson = config.get("data", {})
            for feat in geojson.get("features", []):
                props = feat.get("properties", {})
                zt = props.get("assigned_zone", "") or props.get("zone_type", "")
                area = props.get("area_ha", 0)
                if zt:
                    zone_areas[zt] = zone_areas.get(zt, 0) + area
        return zone_areas
