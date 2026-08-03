"""Layout validation - checks spatial layout against constraints and completeness rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger
from app.modules.schema import PLANNING_ZONE_NAMES

logger = get_logger(__name__)

# Required planning zones that must exist in a valid layout
# 农田保护区 is optional — villages without basic farmland (e.g. 金田村)
# won't have this zone, which is correct per YJJBNTTB designation
REQUIRED_ZONE_TYPES = {"村庄建设区", "生态保护区", "一般农业区"}
OPTIONAL_ZONE_TYPES = {"农田保护区", "生态控制区", "林业发展区"}

# Minimum area (ha) for each zone type
MIN_ZONE_AREA_HA = {
    "农田保护区": 1.0,
    "村庄建设区": 0.5,
    "生态保护区": 1.0,
    "一般农业区": 5.0,
}

# Zone types that must NOT contain protected parcels
PROTECTED_ZONE_TYPES = {"农田保护区", "生态保护区"}
CONSTRUCTION_ZONE_TYPES = {"村庄建设区"}


@dataclass
class Violation:
    check: str
    severity: str  # "error" | "warning"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConstraintAdjustment:
    """Structured adjustment from validation → allocate feedback (Step 3).

    Each violation produces a concrete delta_ha that allocate can apply
    to correct its MIP target map on the next round.
    """
    zone: str       # "村庄建设区"
    action: str     # "reduce_area" | "increase_area" | "reassign_parcels"
    delta_ha: float  # +12.5 (need more) / -8.3 (need less)
    reason: str      # "建设用地面积 128.8ha 超过上限 120.5ha"
    priority: int = 1  # 1=must_fix, 2=should_fix


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
    adjustments: List[ConstraintAdjustment] = field(default_factory=list)  # Step 3

    @property
    def total_violations(self) -> int:
        return len(self.violations)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.status != "fail",
            "strict_pass": self.status == "pass",
            "status": self.status,
            "total_violations": self.total_violations,
            "violations": [
                {"check": v.check, "severity": v.severity, "message": v.message, "details": v.details}
                for v in self.violations[:10]
            ],
            "warnings": self.warnings[:5],
        }


@dataclass
class RetryValidationReport(ValidationReport):
    attempt: int = 0
    retry_suggestion: Optional[Dict[str, Any]] = None
    final_state: str = ""  # "best_effort" | ""

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["attempt"] = self.attempt
        if self.retry_suggestion:
            d["retry_suggestion"] = self.retry_suggestion
        if self.final_state:
            d["final_state"] = self.final_state
        return d


class LayoutValidator:
    """Validates spatial layout against constraint and completeness rules.

    Checks:
    1. Area constraints — planning_zone areas satisfy KG constraint bounds
    2. Zone completeness — all required zone types present
    3. Overlap detection — no geometric overlaps in same layer
    4. Protected parcels — basic farmland / ecological parcels not in construction zone
    5. Minimum area - each zone meets minimum area threshold
    6. GeoJSON RFC 7946 structural validation
    """

    def validate(
        self,
        layout_configs: List[Dict[str, Any]],
        constraints: Optional[List[Dict[str, Any]]] = None,
        adjacency_graph: Any = None,
        protected_parcels_detail: Optional[List[Dict[str, Any]]] = None,
        kg_vne_summary: Optional[List[Dict[str, Any]]] = None,
    ) -> ValidationReport:
        checks = [
            self._check_area_constraints(constraints or [], layout_configs),
            self._check_zone_completeness(layout_configs),
            self._check_overlap(layout_configs),
            self._check_protected_parcels(layout_configs, protected_parcels_detail),
            self._check_min_zone_area(layout_configs),
            self._check_geojson_structural(layout_configs),
            self._check_adjacency_compatibility(layout_configs, adjacency_graph),
            self._check_spatial_compactness(layout_configs),
            self._check_vne_compliance(layout_configs, kg_vne_summary),
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

        # Step 3: Compute structured adjustments from violations
        adjustments = self._compute_adjustments(all_violations, layout_configs)

        return ValidationReport(
            status=status,
            checks=checks,
            violations=all_violations,
            warnings=all_warnings,
            adjustments=adjustments,
        )

    def _check_area_constraints(
        self, constraints: List[Dict], layout_configs: List[Dict]
    ) -> CheckResult:
        violations = []

        zone_areas = self._get_zone_areas(layout_configs)

        for c in constraints:
            field = c.get("field", "")
            op = c.get("operator", c.get("op", ""))
            value = c.get("value", 0)
            try:
                value = float(value)
            except (ValueError, TypeError):
                continue

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
                actual = zone_areas.get("农田保护区", 0)
                if actual < value:
                    violations.append(Violation(
                        check="area_constraint",
                        severity="error",
                        message=f"基本农田面积 {actual:.1f}ha 低于下限 {value}ha",
                        details={"zone": "农田保护区", "actual": actual, "limit": value, "operator": op},
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

        missing_optional = OPTIONAL_ZONE_TYPES - zone_types
        for zt in missing_optional:
            violations.append(Violation(
                check="zone_completeness",
                severity="warning",
                message=f"缺少可选分区: {zt}（村庄无基本农田划定时不产生此分区）",
                details={"missing_zone": zt},
            ))

        return CheckResult(
            check_name="zone_completeness",
            passed=not any(v.severity == "error" for v in violations),
            violation_count=len(violations),
            violations=violations,
        )

    def _check_overlap(self, layout_configs: List[Dict]) -> CheckResult:
        violations = []

        try:
            import shapely.geometry
            from shapely.strtree import STRtree
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
                        geom = shapely.geometry.shape(g)
                        if not geom.is_empty:
                            geoms.append((feat, geom))
                    except Exception:
                        continue

            if len(geoms) < 2:
                continue

            # Build spatial index for efficient overlap detection
            geom_list = [g for _, g in geoms]
            tree = STRtree(geom_list)

            overlap_count = 0
            checked = set()
            for i, (_, geom_i) in enumerate(geoms):
                candidates = tree.query(geom_i)
                for j in candidates:
                    j = int(j)
                    if j <= i:
                        continue
                    pair = (i, j)
                    if pair in checked:
                        continue
                    checked.add(pair)
                    try:
                        if geom_i.intersects(geom_list[j]):
                            intersection = geom_i.intersection(geom_list[j])
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

    def _check_protected_parcels(
        self,
        layout_configs: List[Dict],
        protected_parcels_detail: Optional[List[Dict[str, Any]]] = None,
    ) -> CheckResult:
        """Check protected parcels are not assigned to construction zone.

        Two detection modes:
          1. KG-based (preferred): uses protected_parcels_detail from KG
             which tracks within_zone relations (spatial containment).
          2. DLBM-based (fallback): hardcoded DLBM code check.
        """
        violations = []

        # Build set of protected parcel BSMs from KG detail
        protected_bsms: Dict[str, str] = {}  # bsm → protection_name
        if protected_parcels_detail:
            for pp in protected_parcels_detail:
                bsm = str(pp.get("bsm", "")).strip()
                prot_name = pp.get("protection_name", "")
                if bsm:
                    protected_bsms[bsm] = prot_name

        for config in layout_configs:
            if config.get("layerType") != "planning_zone":
                continue
            geojson = config.get("data", {})
            for feat in geojson.get("features", []):
                props = feat.get("properties", {})
                assigned_zone = props.get("assigned_zone", "")

                if assigned_zone not in CONSTRUCTION_ZONE_TYPES:
                    continue

                # KG-based check: parcel BSM in protected set
                bsm = str(props.get("BSM", "")).strip()
                if bsm and bsm in protected_bsms:
                    prot_name = protected_bsms[bsm]
                    violations.append(Violation(
                        check="protected_parcels",
                        severity="error",
                        message=f"受保护地块(BSM={bsm}, {prot_name})被分配到建设区",
                        details={"bsm": bsm, "protection": prot_name, "assigned_zone": assigned_zone},
                    ))
                    continue

                # Fallback: DLBM-based check
                current_zone = props.get("zone_type", "")
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

    def _check_geojson_structural(self, layout_configs: List[Dict]) -> CheckResult:
        """Validate GeoJSON follows RFC 7946 structure for each layer config."""
        violations = []
        VALID_GEOM_TYPES = {
            "Point", "MultiPoint", "LineString", "MultiLineString",
            "Polygon", "MultiPolygon",
        }

        for layer_idx, config in enumerate(layout_configs):
            geojson = config.get("data", config.get("geojson", {}))
            if not geojson or not isinstance(geojson, dict):
                continue

            # Top-level: must have type: FeatureCollection and features array
            if geojson.get("type") != "FeatureCollection":
                violations.append(Violation(
                    check="geojson_structural", severity="warning",
                    message=f"图层 {layer_idx} GeoJSON type 应为 FeatureCollection",
                    details={"layer": layer_idx, "expected": "FeatureCollection"},
                ))
                continue

            features = geojson.get("features")
            if not isinstance(features, list):
                violations.append(Violation(
                    check="geojson_structural", severity="warning",
                    message=f"图层 {layer_idx} features 应为数组",
                    details={"layer": layer_idx},
                ))
                continue

            # Forbidden: top-level crs member
            if "crs" in geojson:
                violations.append(Violation(
                    check="geojson_structural", severity="warning",
                    message=f"图层 {layer_idx} GeoJSON 不应包含 crs 成员",
                    details={"layer": layer_idx},
                ))

            for fi, feat in enumerate(features):
                if not isinstance(feat, dict):
                    violations.append(Violation(
                        check="geojson_structural", severity="warning",
                        message=f"图层 {layer_idx} feature {fi} 应为对象",
                        details={"layer": layer_idx, "feature": fi},
                    ))
                    continue

                if feat.get("type") != "Feature":
                    violations.append(Violation(
                        check="geojson_structural", severity="warning",
                        message=f"图层 {layer_idx} feature {fi} type 应为 Feature",
                        details={"layer": layer_idx, "feature": fi},
                    ))

                props = feat.get("properties")
                if props is not None and not isinstance(props, dict):
                    violations.append(Violation(
                        check="geojson_structural", severity="warning",
                        message=f"图层 {layer_idx} feature {fi} properties 应为对象或 null",
                        details={"layer": layer_idx, "feature": fi},
                    ))

                geom = feat.get("geometry")
                if geom is None:
                    continue
                if not isinstance(geom, dict):
                    violations.append(Violation(
                        check="geojson_structural", severity="warning",
                        message=f"图层 {layer_idx} feature {fi} geometry 应为对象或 null",
                        details={"layer": layer_idx, "feature": fi},
                    ))
                    continue

                gtype = geom.get("type", "")
                if gtype and gtype not in VALID_GEOM_TYPES:
                    violations.append(Violation(
                        check="geojson_structural", severity="warning",
                        message=f"图层 {layer_idx} feature {fi} 无效 geometry type: {gtype}",
                        details={"layer": layer_idx, "feature": fi, "type": gtype},
                    ))

                # Validate coordinate ranges
                coords = geom.get("coordinates")
                if coords is not None:
                    flat = []
                    self._flatten_coords(coords, flat)
                    for ci, pt in enumerate(flat):
                        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                            continue
                        lon, lat = pt[0], pt[1]
                        if isinstance(lon, (int, float)) and not (-180 <= lon <= 180):
                            violations.append(Violation(
                                check="geojson_structural", severity="warning",
                                message=f"图层 {layer_idx} feature {fi} 经度越界: {lon}",
                                details={"layer": layer_idx, "feature": fi, "lon": lon},
                            ))
                            break
                        if isinstance(lat, (int, float)) and not (-90 <= lat <= 90):
                            violations.append(Violation(
                                check="geojson_structural", severity="warning",
                                message=f"图层 {layer_idx} feature {fi} 纬度越界: {lat}",
                                details={"layer": layer_idx, "feature": fi, "lat": lat},
                            ))
                            break

                # Validate polygon ring closure
                if gtype in ("Polygon", "MultiPolygon") and coords is not None:
                    self._validate_ring_closure(coords, gtype, violations, layer_idx, fi)

        return CheckResult(
            check_name="geojson_structural",
            passed=len(violations) == 0,
            violation_count=len(violations),
            violations=violations,
        )

    @staticmethod
    def _flatten_coords(coords: Any, flat: List) -> None:
        """Recursively flatten coordinate arrays to [lon, lat] pairs."""
        if isinstance(coords, (list, tuple)) and coords:
            if isinstance(coords[0], (list, tuple)):
                for item in coords:
                    LayoutValidator._flatten_coords(item, flat)
            else:
                flat.append(coords)

    @staticmethod
    def _validate_ring_closure(
        coords: Any, geom_type: str,
        violations: List[Violation], layer_idx: int, feat_idx: int,
    ) -> None:
        """Check polygon rings are closed (first == last coordinate)."""
        rings = coords if geom_type == "Polygon" else coords
        if not isinstance(rings, (list, tuple)):
            return
        for ring in rings:
            if geom_type == "MultiPolygon":
                # MultiPolygon: coords = [[ring1, ring2...], [ring1...]]
                if isinstance(ring, (list, tuple)) and ring and isinstance(ring[0], (list, tuple)):
                    for sub_ring in ring:
                        LayoutValidator._check_ring(sub_ring, violations, layer_idx, feat_idx)
                else:
                    LayoutValidator._check_ring(ring, violations, layer_idx, feat_idx)
            else:
                LayoutValidator._check_ring(ring, violations, layer_idx, feat_idx)

    @staticmethod
    def _check_ring(
        ring: Any, violations: List[Violation], layer_idx: int, feat_idx: int,
    ) -> None:
        """Check a single polygon ring for closure."""
        if not isinstance(ring, (list, tuple)) or len(ring) < 4:
            return
        first, last = ring[0], ring[-1]
        if not (isinstance(first, (list, tuple)) and isinstance(last, (list, tuple))):
            return
        if len(first) >= 2 and len(last) >= 2:
            if (abs(first[0] - last[0]) > 1e-10 or abs(first[1] - last[1]) > 1e-10):
                violations.append(Violation(
                    check="geojson_structural", severity="warning",
                    message=f"图层 {layer_idx} feature {feat_idx} 边界环未闭合",
                    details={"layer": layer_idx, "feature": feat_idx},
                ))

    def validate_with_retry(
        self,
        layout_configs: List[Dict[str, Any]],
        constraints: Optional[List[Dict[str, Any]]] = None,
        max_retries: int = 3,
        protected_parcels_detail: Optional[List[Dict[str, Any]]] = None,
        kg_vne_summary: Optional[List[Dict[str, Any]]] = None,
    ) -> RetryValidationReport:
        """Validate layout and generate adjustment suggestions on failure."""
        constraints = constraints or []

        for attempt in range(max_retries):
            report = self.validate(
                layout_configs, constraints,
                protected_parcels_detail=protected_parcels_detail,
                kg_vne_summary=kg_vne_summary,
            )

            if report.status == "pass":
                return RetryValidationReport(
                    status=report.status,
                    checks=report.checks,
                    violations=report.violations,
                    warnings=report.warnings,
                    attempt=attempt + 1,
                )

            suggestion = self._generate_adjustment(report.violations)
            logger.info(
                f"[Validator] Attempt {attempt + 1}/{max_retries} failed "
                f"({report.total_violations} violations)"
            )

            # Last attempt — return with suggestion
            if attempt == max_retries - 1:
                return RetryValidationReport(
                    status=report.status,
                    checks=report.checks,
                    violations=report.violations,
                    warnings=report.warnings,
                    attempt=attempt + 1,
                    retry_suggestion=suggestion,
                    final_state="best_effort",
                )

        # Should not reach here, but safety
        return RetryValidationReport(status="fail", attempt=max_retries)

    def _generate_adjustment(
        self, violations: List[Violation]
    ) -> Dict[str, Any]:
        """Generate target adjustment suggestions from violations."""
        adjustments = []

        for v in violations:
            if v.check == "area_constraint":
                details = v.details
                zone = details.get("zone", "")
                if "超过上限" in v.message:
                    adjustments.append({
                        "action": "reduce_area_ratio",
                        "zone": zone,
                        "reason": f"{zone} 面积超标，建议降低面积比例",
                    })
                elif "低于下限" in v.message:
                    adjustments.append({
                        "action": "increase_area_ratio",
                        "zone": zone,
                        "reason": f"{zone} 面积不足，建议提高面积比例",
                    })
            elif v.check == "zone_completeness":
                missing = v.details.get("missing_zone", "")
                adjustments.append({
                    "action": "add_missing_zone",
                    "zone": missing,
                    "reason": f"缺少必需分区 {missing}，需添加",
                })
            elif v.check == "protected_parcels":
                adjustments.append({
                    "action": "reassign_protected",
                    "zone": "村庄建设区",
                    "reason": "受保护地块被分配到建设区，需重新分配至农业或生态区",
                })

        return {
            "adjustments": adjustments,
            "summary": f"共 {len(adjustments)} 项调整建议",
        }

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

    def _check_adjacency_compatibility(
        self,
        layout_configs: List[Dict],
        adjacency_graph: Any = None,
    ) -> CheckResult:
        """Check adjacency compatibility rate (same-zone neighbors / total edges).

        If adjacency_graph is provided, computes the actual rate from the
        layout's zone assignments. Otherwise, skips this check.
        Threshold: 30% (village-scale planning with area targets often forces
        reassignment of large ecological blocks, creating boundary fragmentation).
        """
        if adjacency_graph is None:
            return CheckResult(check_name="adjacency_compatibility", passed=True)

        # Build assignment map from layout
        assignments: Dict[str, str] = {}
        for config in layout_configs:
            if config.get("layerType") != "planning_zone":
                continue
            geojson = config.get("data", {})
            for feat in geojson.get("features", []):
                props = feat.get("properties", {})
                ck = props.get("composite_key", "")
                zone = props.get("assigned_zone", "")
                if ck and zone:
                    assignments[ck] = zone

        if not assignments:
            return CheckResult(check_name="adjacency_compatibility", passed=True)

        # Compute rate
        same_zone = 0
        total = 0
        adj_dict = getattr(adjacency_graph, "adjacency_dict", {})
        for key_i, neighbors in adj_dict.items():
            zone_i = assignments.get(key_i, "")
            if not zone_i:
                continue
            for key_j in neighbors:
                if key_j <= key_i:
                    continue
                total += 1
                if assignments.get(key_j, "") == zone_i:
                    same_zone += 1

        rate = same_zone / total if total > 0 else 0.0
        violations = []
        if rate < 0.30:
            violations.append(Violation(
                check="adjacency_compatibility",
                severity="warning",
                message=f"邻接同类率 {rate:.1%} 低于建议阈值 30%",
                details={"rate": round(rate, 4), "threshold": 0.30},
            ))

        return CheckResult(
            check_name="adjacency_compatibility",
            passed=len(violations) == 0,
            violation_count=len(violations),
            violations=violations,
        )

    def _check_spatial_compactness(
        self,
        layout_configs: List[Dict],
    ) -> CheckResult:
        """Check spatial compactness index (1 / (1 + CV of zone areas)).

        Measures how evenly parcels are distributed across zones.
        Higher compactness = more even distribution of parcel sizes within zones.
        Threshold: 0.5 (minimum acceptable for village planning).
        """
        from collections import defaultdict

        # Collect parcel areas by zone
        zone_parcel_areas: Dict[str, List[float]] = defaultdict(list)
        for config in layout_configs:
            if config.get("layerType") != "planning_zone":
                continue
            geojson = config.get("data", {})
            for feat in geojson.get("features", []):
                props = feat.get("properties", {})
                zone = props.get("assigned_zone", "") or props.get("zone_type", "")
                area = props.get("area_ha", 0)
                if zone and area > 0:
                    zone_parcel_areas[zone].append(area)

        if not zone_parcel_areas:
            return CheckResult(check_name="spatial_compactness", passed=True)

        # Compute compactness: 1/(1+CV) for each zone, then average
        scores = []
        for areas in zone_parcel_areas.values():
            if len(areas) < 2:
                continue
            mean_a = sum(areas) / len(areas)
            if mean_a <= 0:
                continue
            variance = sum((a - mean_a) ** 2 for a in areas) / len(areas)
            std_a = variance ** 0.5
            cv = std_a / mean_a
            scores.append(1 / (1 + cv))

        if not scores:
            return CheckResult(check_name="spatial_compactness", passed=True)

        compactness = sum(scores) / len(scores)
        violations = []
        if compactness < 0.5:
            violations.append(Violation(
                check="spatial_compactness",
                severity="warning",
                message=f"空间紧凑度 {compactness:.3f} 低于建议阈值 0.5",
                details={"compactness": round(compactness, 4), "threshold": 0.5},
            ))

        return CheckResult(
            check_name="spatial_compactness",
            passed=len(violations) == 0,
            violation_count=len(violations),
            violations=violations,
        )

    def _check_vne_compliance(
        self,
        layout_configs: List[Dict],
        kg_vne_summary: Optional[List[Dict[str, Any]]] = None,
    ) -> CheckResult:
        """Check VNE (国土空间规划用途分类) compliance of zone assignments.

        Validates that the area distribution across planning zones is
        consistent with the VNE classification from KG. Specifically:
          - VNE V* (村庄建设) → 村庄建设区
          - VNE N* (非村庄建设) → 村庄建设区
          - VNE E1* (水域) → 生态保护区
          - VNE E2* (农林) → 一般农业区

        kg_vne_summary: [{vne_code, parcel_count, total_area_ha}] from KG.
        """
        if not kg_vne_summary:
            return CheckResult(check_name="vne_compliance", passed=True)

        from app.modules.schema import VNE_TO_ZONE_TYPE

        # Build VNE → planning_zone mapping (VNE → zone_type → planning_zone)
        vne_to_planning: Dict[str, str] = {}
        for vne_code, zone_type in VNE_TO_ZONE_TYPE.items():
            first = vne_code[0] if vne_code else ""
            if first == "V":
                vne_to_planning[vne_code] = "村庄建设区"
            elif first == "N":
                vne_to_planning[vne_code] = "村庄建设区"
            elif first == "E":
                if "水域" in zone_type:
                    vne_to_planning[vne_code] = "生态保护区"
                elif "农业" in zone_type or "农林" in zone_type:
                    vne_to_planning[vne_code] = "一般农业区"
                else:
                    vne_to_planning[vne_code] = "生态控制区"

        # Collect zone areas from layout
        zone_areas = self._get_zone_areas(layout_configs)
        violations = []

        # Aggregate VNE areas by expected planning zone
        expected_by_zone: Dict[str, float] = {}
        for vne_entry in kg_vne_summary:
            vne_code = str(vne_entry.get("vne_code", "")).strip()
            planning_zone = vne_to_planning.get(vne_code, "")
            if not planning_zone:
                continue
            vne_area = float(vne_entry.get("total_area_ha", 0) or 0)
            expected_by_zone[planning_zone] = expected_by_zone.get(planning_zone, 0) + vne_area

        # Compare aggregated VNE areas against actual planning zone areas
        for zone, expected_ha in expected_by_zone.items():
            actual_ha = zone_areas.get(zone, 0)
            if expected_ha > 0 and actual_ha > 0:
                ratio = actual_ha / expected_ha
                if ratio < 0.5:
                    violations.append(Violation(
                        check="vne_compliance",
                        severity="warning",
                        message=f"VNE分类预期 {zone} {expected_ha:.1f}ha 但实际 {actual_ha:.1f}ha (覆盖率 {ratio:.0%})",
                        details={
                            "zone": zone,
                            "vne_expected_ha": round(expected_ha, 1),
                            "actual_ha": round(actual_ha, 1),
                            "coverage_ratio": round(ratio, 2),
                        },
                    ))

        return CheckResult(
            check_name="vne_compliance",
            passed=len(violations) == 0,
            violation_count=len(violations),
            violations=violations,
        )

    def _compute_adjustments(
        self,
        violations: List[Violation],
        layout_configs: List[Dict[str, Any]],
    ) -> List[ConstraintAdjustment]:
        """Step 3: Convert violations into structured adjustments for allocate.

        Each area_constraint violation produces a delta_ha that allocate
        can apply to its target_map on the next retry round.
        """
        adjustments: List[ConstraintAdjustment] = []
        zone_areas = self._get_zone_areas(layout_configs)

        for v in violations:
            if v.check == "area_constraint":
                details = v.details
                zone = details.get("zone", "")
                actual = details.get("actual", 0)
                limit = details.get("limit", 0)

                if "超过上限" in v.message:
                    delta = limit - actual  # negative: need to reduce
                    adjustments.append(ConstraintAdjustment(
                        zone=zone,
                        action="reduce_area",
                        delta_ha=round(delta, 2),
                        reason=v.message,
                        priority=1,
                    ))
                elif "低于下限" in v.message:
                    delta = limit - actual  # positive: need to increase
                    adjustments.append(ConstraintAdjustment(
                        zone=zone,
                        action="increase_area",
                        delta_ha=round(delta, 2),
                        reason=v.message,
                        priority=1,
                    ))

            elif v.check == "protected_parcels":
                adjustments.append(ConstraintAdjustment(
                    zone="村庄建设区",
                    action="reassign_parcels",
                    delta_ha=-1.0,  # Reduce by ~1ha per violation (heuristic)
                    reason=v.message,
                    priority=1,
                ))

            elif v.check == "zone_completeness":
                missing = v.details.get("missing_zone", "")
                # Estimate needed area for missing zone
                estimated = MIN_ZONE_AREA_HA.get(missing, 5.0)
                adjustments.append(ConstraintAdjustment(
                    zone=missing,
                    action="increase_area",
                    delta_ha=estimated,
                    reason=v.message,
                    priority=2,
                ))

        return adjustments
