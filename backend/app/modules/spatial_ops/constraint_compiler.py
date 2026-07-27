"""ConstraintCompiler — single entry point for all constraint compilation.

Replaces:
  - PARSE → MIP 散转换 (allocate.py:_spatial_constraint_to_mip)
  - KG → state 拍平 (tools/gis/kg.py queries)
  - 12处 try/except: pass 静默吞错

Design: 02_EXECUTION_PLAN.md Module B
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ..schema.contracts.constraint_contracts import (
    CompilationReport,
    CompiledConstraint,
    ConflictRecord,
    DroppedItem,
)
from ..schema.contracts.parse_contracts import SpatialConstraint
from ..schema.encodings.code_sets import (
    get_planning_zone_from_landuse,
    normalize_landuse,
)

logger = logging.getLogger(__name__)


class ConstraintCompiler:
    """Compile all constraint sources into a single CompilationReport.

    Sources:
      1. PARSE constraints (SpatialConstraint list)
      2. Three-line constraints (from bundle / ConstraintIndex)
      3. VNE constraints (from bundle parcel data)
      4. Protected parcel constraints (from bundle / ConstraintIndex)
      5. Rule YAML constraints (from planning_zone_rules.yaml)
      6. Feedback constraints (from validation loop)

    Every dropped item is recorded with a reason. Silent drops are bugs.
    """

    def __init__(self, bundle: Any = None):
        self.bundle = bundle
        self._stats: Dict[str, int] = {
            "parse_input": 0,
            "three_line_input": 0,
            "vne_input": 0,
            "protected_input": 0,
            "rule_yaml_input": 0,
            "feedback_input": 0,
        }

    def compile(
        self,
        parse_constraints: Optional[List[SpatialConstraint]] = None,
        bundle=None,
        rule_config: Optional[Any] = None,
        feedback_constraints: Optional[List[CompiledConstraint]] = None,
    ) -> CompilationReport:
        """Compile all constraint sources into a single report.

        Args:
            parse_constraints: PARSE 产出的空间约束列表
            bundle: VillageBundle（用于三线/VNE/保护地块计算）
            rule_config: RuleConfig 规则配置
            feedback_constraints: 上一轮校验反馈的约束

        Returns:
            CompilationReport with compiled/dropped/conflicts.
        """
        report = CompilationReport()
        b = bundle or self.bundle

        t0 = time.time()

        # 1. Compile PARSE constraints
        if parse_constraints:
            self._stats["parse_input"] = len(parse_constraints)
            self._compile_parse_constraints(parse_constraints, report)

        # 2. Compile three-line constraints (from bundle / ConstraintIndex)
        if b is not None:
            self._compile_three_line_constraints(b, report)

        # 3. Compile VNE constraints
        if b is not None:
            self._compile_vne_constraints(b, report)

        # 4. Compile protected parcel constraints
        if b is not None:
            self._compile_protected_constraints(b, report)

        # 5. Compile rule YAML constraints
        if rule_config is not None:
            self._stats["rule_yaml_input"] = 1
            self._compile_rule_config(rule_config, report)

        # 6. Compile feedback constraints
        if feedback_constraints:
            self._stats["feedback_input"] = len(feedback_constraints)
            report.compiled.extend(feedback_constraints)

        # 7. Resolve conflicts (same scope+field, keep strictest)
        self._resolve_conflicts(report)

        elapsed = time.time() - t0
        logger.info(
            "ConstraintCompiler: %s (%.2fs)",
            report.summary(), elapsed,
        )
        return report

    def _compile_parse_constraints(
        self,
        constraints: List[SpatialConstraint],
        report: CompilationReport,
    ) -> None:
        """Compile PARSE SpatialConstraint list into CompiledConstraint list."""
        for i, c in enumerate(constraints):
            cc = self._spatial_constraint_to_compiled(c, i)
            if cc is not None:
                report.compiled.append(cc)
            else:
                report.dropped.append(
                    DroppedItem(
                        source_item=f"parse_constraint[{i}]",
                        reason=f"无法编译: type={c.type}, land_use={c.land_use}",
                        source="parse",
                    )
                )

    def _spatial_constraint_to_compiled(
        self,
        c: SpatialConstraint,
        idx: int,
    ) -> Optional[CompiledConstraint]:
        """Convert one SpatialConstraint to CompiledConstraint.

        Returns None if the constraint cannot be compiled (dropped).
        """
        if c.type == "area_constraint":
            if c.land_use is None or c.target_area_ha is None:
                return None
            zone = None
            try:
                if isinstance(c.land_use, str):
                    zone = get_planning_zone_from_landuse(c.land_use)
            except Exception:
                zone = None

            return CompiledConstraint(
                id=f"parse_area_{idx}",
                scope="zone" if zone else "global",
                zone=zone,
                field="area_ha",
                operator=c.operator or ">=",
                value=c.target_area_ha,
                hardness="hard" if c.priority == "mandatory" else "soft",
                weight=5.0 if c.priority != "mandatory" else None,
                source="parse",
                provenance=c.source_text or c.article_ref or f"parse_constraint[{idx}]",
            )

        if c.type == "spatial_constraint":
            # Spatial constraints (no_overlap, buffer_exclusion, etc.)
            # These need geometry-level compilation — kept as reference
            return CompiledConstraint(
                id=f"parse_spatial_{idx}",
                scope="global",
                field="spatial_rule",
                operator="==",
                value=1.0,
                hardness="hard",
                source="parse",
                provenance=c.source_text or f"parse_spatial[{idx}]",
            )

        # Other constraint types: building, use, boundary, protection, etc.
        # Build a generic compiled constraint from available fields
        if c.value is not None:
            return CompiledConstraint(
                id=f"parse_{c.type}_{idx}",
                scope="global",
                field=c.value_unit or "value",
                operator="<=",
                value=c.value,
                hardness="hard" if c.priority == "mandatory" else "soft",
                weight=5.0 if c.priority != "mandatory" else None,
                source="parse",
                provenance=c.source_text or f"parse_{c.type}[{idx}]",
            )

        return None

    def _compile_three_line_constraints(
        self,
        bundle: Any,
        report: CompilationReport,
    ) -> None:
        """Compile three-line constraints from bundle data.

        Three lines are reference layers (not KG entities per v4.7).
        Constraints are derived from ConstraintIndex or bundle polygon data.
        """
        count = 0
        try:
            constraint_polygons = getattr(
                getattr(bundle, "polygons", None), "constraint_polygons", None
            )
            if constraint_polygons is not None:
                count = len(constraint_polygons)
                report.compiled.append(
                    CompiledConstraint(
                        id="three_line_global",
                        scope="global",
                        field="constraint_polygons",
                        operator="==",
                        value=float(count),
                        hardness="hard",
                        source="three_line",
                        provenance=f"bundle.polygons.constraint_polygons: {count} polygons",
                    )
                )
        except Exception as e:
            report.dropped.append(
                DroppedItem(
                    source_item="three_line",
                    reason=f"读取约束面失败: {e}",
                    source="three_line",
                )
            )
        self._stats["three_line_input"] = count

    def _compile_vne_constraints(
        self,
        bundle: Any,
        report: CompilationReport,
    ) -> None:
        """Compile VNE (Village/Non-village/Ecological) capacity constraints."""
        try:
            parcels = getattr(
                getattr(getattr(bundle, "polygons", None), "landuse_current", None),
                "__iter__",
                None,
            )
            if parcels is None:
                report.dropped.append(
                    DroppedItem(
                        source_item="vne",
                        reason="bundle.polygons.landuse_current 不可用",
                        source="vne",
                    )
                )
                return

            vne_counts: Dict[str, int] = {}
            for p in bundle.polygons.landuse_current:
                vne = getattr(p, "vne_code", None) or ""
                major = vne[0] if vne else "E"
                vne_counts[major] = vne_counts.get(major, 0) + 1

            for vne_type, cnt in vne_counts.items():
                report.compiled.append(
                    CompiledConstraint(
                        id=f"vne_{vne_type}_count",
                        scope="global",
                        field="parcel_count",
                        operator=">=",
                        value=float(cnt),
                        hardness="hard",
                        source="vne",
                        provenance=f"VNE {vne_type}: {cnt} parcels",
                    )
                )
            self._stats["vne_input"] = len(vne_counts)
        except Exception as e:
            report.dropped.append(
                DroppedItem(
                    source_item="vne",
                    reason=f"VNE 编译异常: {e}",
                    source="vne",
                )
            )

    def _compile_protected_constraints(
        self,
        bundle: Any,
        report: CompilationReport,
    ) -> None:
        """Compile protected parcel constraints from bundle."""
        try:
            polygons = getattr(bundle, "polygons", None)
            if polygons is None:
                report.dropped.append(
                    DroppedItem(
                        source_item="protected",
                        reason="bundle.polygons 不可用",
                        source="protected",
                    )
                )
                return

            protected_count = 0
            for layer_name in [
                "farmland_protection",
                "ecological_redline",
                "historical_protection",
            ]:
                layer = getattr(polygons, layer_name, None)
                if layer:
                    protected_count += len(layer)

            if protected_count > 0:
                report.compiled.append(
                    CompiledConstraint(
                        id="protected_parcels_global",
                        scope="global",
                        field="protected_count",
                        operator="==",
                        value=float(protected_count),
                        hardness="hard",
                        source="protected",
                        provenance=f"保护地块: {protected_count} 个约束面",
                    )
                )
            self._stats["protected_input"] = protected_count
        except Exception as e:
            report.dropped.append(
                DroppedItem(
                    source_item="protected",
                    reason=f"保护地块编译异常: {e}",
                    source="protected",
                )
            )

    def _compile_rule_config(
        self,
        rule_config: Any,
        report: CompilationReport,
    ) -> None:
        """Compile rule YAML constraints into the report."""
        try:
            if hasattr(rule_config, "to_constraints"):
                constraints = rule_config.to_constraints()
                for cc in constraints:
                    report.compiled.append(cc)
        except Exception as e:
            report.dropped.append(
                DroppedItem(
                    source_item="rule_config",
                    reason=f"规则配置编译失败: {e}",
                    source="rule_yaml",
                )
            )

    def _resolve_conflicts(self, report: CompilationReport) -> None:
        """Resolve conflicts among compiled constraints.

        Conflict rule: same scope+field → keep strictest bound.
        - hard > soft
        - For same hardness: min for <=, max for >=
        """
        key_map: Dict[str, List[CompiledConstraint]] = {}
        for cc in report.compiled:
            key = f"{cc.scope}:{cc.zone or ''}:{cc.field}"
            key_map.setdefault(key, []).append(cc)

        for key, constraints in key_map.items():
            if len(constraints) <= 1:
                continue

            # Sort: hard first, then by strictness
            hard_cons = [c for c in constraints if c.hardness == "hard"]
            soft_cons = [c for c in constraints if c.hardness == "soft"]

            # Hard wins over soft
            surviving = hard_cons if hard_cons else soft_cons
            overridden = soft_cons if hard_cons else []

            # Among same hardness, keep strictest
            if len(surviving) > 1:
                sorted_cons = sorted(
                    surviving,
                    key=lambda c: (
                        c.value if c.operator in ("<=", "==") else -c.value
                    ),
                )
                if surviving[0].operator in ("<=", "=="):
                    surviving = [sorted_cons[0]]
                else:
                    surviving = [sorted_cons[-1]]

                overridden.extend(sorted_cons[1:])

            if overridden:
                report.conflicts.append(
                    ConflictRecord(
                        scope=key,
                        field=surviving[0].field,
                        competing_values=[c.value for c in constraints],
                        competing_sources=list(set(c.source for c in constraints)),
                        resolved_value=surviving[0].value,
                        resolved_operator=surviving[0].operator,
                        overridden_items=[c.id for c in overridden],
                    )
                )
                # Remove overridden from compiled list
                overridden_ids = {c.id for c in overridden}
                report.compiled = [c for c in report.compiled if c.id not in overridden_ids]

    def get_stats(self) -> Dict[str, int]:
        """Return compilation statistics for logging."""
        return dict(self._stats)


__all__ = ["ConstraintCompiler"]