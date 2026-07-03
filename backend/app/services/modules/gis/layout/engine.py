"""
Spatial layout engine - orchestrates the full pipeline.

Phase 0:  Conflict detection + resolution
Phase 1:  Zone generation (DLBM reclassification + planning zone allocation)
Phase 2:  KG-driven constraint allocation
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger
from .conflict_detector import ConflictDetector, ConflictReport
from .conflict_resolver import ConflictResolver, ResolutionReport
from .planning_intent import UnifiedSpatialIntent
from .zone_generator import ZoneGenerator
from .map_renderer import MapRenderer
from .facility_placer import FacilityPlacer
from .axis_builder import AxisBuilder
from .zone_schema import PLANNING_ZONE_COLORS, DLBM_TO_ZONE_TYPE, ZONE_TYPE_COLORS, DEFAULT_ZONE_COLOR

logger = get_logger(__name__)


class SpatialLayoutEngine:
    """V2: KG-driven spatial layout engine.

    Phase 0: Reports → KG build → ConflictDetection → ConflictResolution
    Phase 1: KG constraints → ZoneGenerator + ConstraintAllocator → MapRenderer
    """

    def __init__(self) -> None:
        self.conflict_detector = ConflictDetector()
        self.conflict_resolver = ConflictResolver()
        self.zone_generator = ZoneGenerator()
        self.map_renderer = MapRenderer()
        self.facility_placer = FacilityPlacer()
        self.axis_builder = AxisBuilder()
        self.kg = None           # PlanningKG instance (lazy init)
        self._allocator = None   # ConstraintDrivenAllocator (lazy init)
        self._kg_constraints: List[Dict[str, Any]] = []
        self._last_planning_targets: Dict[str, float] = {}
        self._adjacency_graph = None  # AdjacencyGraph (lazy init)

    def build_kg(self, reports: Dict[str, Dict[str, Any]],
                 landuse_geojson: Dict[str, Any]) -> "SpatialLayoutEngine":
        """Build Planning Knowledge Graph from reports + landuse data.

        After calling this, subsequent calls to generate_layout() will use
        KG-driven constraint allocation instead of pure DLBM reclassification.
        """
        from .kg import PlanningKG
        self.kg = PlanningKG(village_name=reports.get("_village", ""))
        self.kg.build_from_reports(reports=reports, landuse_geojson=landuse_geojson)
        self._kg_constraints = self.kg.get_constraints()
        logger.info(
            f"[SpatialLayoutEngine] KG built: {self.kg.get_triple_count()} triples, "
            f"{len(self._kg_constraints)} constraints"
        )
        return self

    def _get_allocator(self):
        """Lazy init constraint allocator."""
        if self._allocator is None:
            from .optimizer import ConstraintDrivenAllocator
            self._allocator = ConstraintDrivenAllocator()
        return self._allocator

    def _get_adjacency_graph(self, landuse_geojson: Dict[str, Any]):
        """Lazy init adjacency graph from landuse data."""
        if self._adjacency_graph is None:
            from .optimizer.adjacency_graph import AdjacencyGraph
            from ..utils.geojson_utils import build_parcel_index
            from .zone_generator import resolve_zone_type_for_dlbm
            parcel_db, _ = build_parcel_index(
                landuse_geojson, zone_type_fn=resolve_zone_type_for_dlbm
            )
            self._adjacency_graph = AdjacencyGraph(parcel_db, max_distance_m=30.0)
        return self._adjacency_graph

    def has_kg(self) -> bool:
        return self.kg is not None or bool(self._kg_constraints)

    def set_kg_constraints(self, constraints: List[Dict[str, Any]]) -> None:
        """Inject pre-built KG constraints without a full PlanningKG instance.

        Allows generate_layout to produce planning_zone layer when
        kg_constraints are available from state but the full KG was not
        built in this process.
        """
        self._kg_constraints = constraints

    def detect_and_resolve(
        self,
        summaries: Dict[str, Dict[str, Any]],
    ) -> Tuple[ConflictReport, ResolutionReport]:
        """Phase 0: Detect and resolve cross-dimension conflicts.

        Args:
            summaries: {dimension_key: {"metrics": {...}, ...}}

        Returns:
            Tuple of (conflict_report, resolution_report)
        """
        conflict_report = self.conflict_detector.detect_all(summaries)
        resolution_report = self.conflict_resolver.resolve(conflict_report)

        logger.info(
            f"[SpatialLayoutEngine] Phase 0 complete: "
            f"{conflict_report.total_count} conflicts detected, "
            f"{len(resolution_report.metric_resolutions)} metric resolutions, "
            f"{len(resolution_report.constraint_resolutions)} constraint resolutions"
        )

        return conflict_report, resolution_report

    def generate_layout(
        self,
        intent: UnifiedSpatialIntent,
        gis_context: Optional[Any] = None,
        boundary_geojson: Optional[Dict[str, Any]] = None,
        landuse_current_geojson: Optional[Dict[str, Any]] = None,
        protection_zones: Optional[Dict[str, Dict[str, Any]]] = None,
        road_geojson: Optional[Dict[str, Any]] = None,
        construction_zone_geojson: Optional[Dict[str, Any]] = None,
        hazard_points_geojson: Optional[Dict[str, Any]] = None,
        session_id: str = "",
    ) -> List[Dict[str, Any]]:
        """Phase 1: Generate multi-layer layout from unified intent.

        Produces up to 6 layer types in one call:
          - boundary (village outline)
          - function_zone (generated zones from ZoneGenerator)
          - sensitivity_zone (protection areas: farmland/ecological/historical)
          - infrastructure (roads + construction zones)
          - facility_point (hazard points)
          - development_axis (spatial structure axes)

        Args:
            intent: Unified spatial intent with zone definitions
            gis_context: Optional SharedGISContext for data access
            boundary_geojson: Village boundary
            landuse_current_geojson: Current land use parcels
            protection_zones: Dict of protection zone GeoJSONs by name
            road_geojson: Road network GeoJSON
            construction_zone_geojson: Construction zone polygons GeoJSON
            hazard_points_geojson: Geological hazard points GeoJSON

        Returns:
            List of GISLayerConfig dicts sorted by rendering priority
        """
        # Get data from gis_context if available
        if gis_context:
            if not boundary_geojson:
                boundary_geojson = gis_context.get_data_by_type("boundary")
            if not landuse_current_geojson:
                landuse_current_geojson = gis_context.get_data_by_type("landuse_current")
            if not protection_zones:
                protection_zones = gis_context.get_protection_zones()

        # Generate function_zone GeoJSON (DLBM reclassification - existing method)
        self._emit_progress(session_id, "generating_function_zone", "生成功能分区图层")
        function_zone_geojson = self.zone_generator.generate(
            intent=intent,
            boundary_geojson=boundary_geojson,
            landuse_current_geojson=landuse_current_geojson,
            protection_zones=protection_zones,
        )

        # Build multi-layer dict
        layers: Dict[str, Dict[str, Any]] = {}

        if function_zone_geojson.get("features"):
            for feat in function_zone_geojson["features"]:
                feat.setdefault("properties", {})["layer_role"] = "reference_current"
            layers["function_zone"] = function_zone_geojson
            # Incremental SSE: push function_zone as soon as generated
            self._emit_layer_update(session_id, "function_zone", function_zone_geojson, boundary_geojson)

        # ---- KG-driven planning zone allocation (NEW) ----
        if self.has_kg() and landuse_current_geojson:
            self._emit_progress(session_id, "generating_planning_zone", "生成规划分区图层")
            planning_zone_geojson = self._generate_planning_zones(
                intent, landuse_current_geojson, protection_zones
            )
            if planning_zone_geojson and planning_zone_geojson.get("features"):
                planning_zone_geojson = self._refine_planning_zones(planning_zone_geojson)
                for feat in planning_zone_geojson["features"]:
                    feat.setdefault("properties", {})["layer_role"] = "authoritative_planning"
                layers["planning_zone"] = planning_zone_geojson
                # Incremental SSE: push planning_zone as soon as generated
                self._emit_layer_update(session_id, "planning_zone", planning_zone_geojson, boundary_geojson)

        # Protection zones → sensitivity_zone layer
        if protection_zones:
            sensitivity_features = []
            for zone_name, geojson in protection_zones.items():
                if not geojson or not geojson.get("features"):
                    continue
                for feat in geojson["features"]:
                    feat = dict(feat)
                    feat.setdefault("properties", {})["protection_type"] = zone_name
                    sensitivity_features.append(feat)
            if sensitivity_features:
                layers["sensitivity_zone"] = {
                    "type": "FeatureCollection",
                    "features": sensitivity_features,
                }
                self._emit_layer_update(session_id, "sensitivity_zone", layers["sensitivity_zone"], boundary_geojson)

        # Roads + construction zone → infrastructure layer
        INFRA_COLORS = {
            "县道": {"fill": "#555555", "stroke": "#333333"},
            "乡道": {"fill": "#808080", "stroke": "#606060"},
            "村道": {"fill": "#A0A0A0", "stroke": "#808080"},
            "道路": {"fill": "#666666", "stroke": "#444444"},
            "河流": {"fill": "#00BFFF", "stroke": "#0099CC"},
            "水系": {"fill": "#00BFFF", "stroke": "#0099CC"},
            "construction_zone": {"fill": "#CC9900", "stroke": "#996600"},
        }
        infra_features = []
        if road_geojson and road_geojson.get("features"):
            for feat in road_geojson["features"]:
                feat = dict(feat)
                props = feat.setdefault("properties", {})
                props["infra_type"] = "road"
                # Inject color based on road type (RN prefix or name)
                rn = str(props.get("RN", "") or "")
                name = str(props.get("name", "") or "")
                road_key = "道路"
                if rn.startswith("X") or "县道" in name:
                    road_key = "县道"
                elif rn.startswith("Y") or "乡道" in name or "村道" in name:
                    road_key = "乡道"
                infra_color = INFRA_COLORS.get(road_key, INFRA_COLORS["道路"])
                props["color"] = infra_color["stroke"]
                props["stroke"] = infra_color["stroke"]
                infra_features.append(feat)
        if construction_zone_geojson and construction_zone_geojson.get("features"):
            for feat in construction_zone_geojson["features"]:
                feat = dict(feat)
                props = feat.setdefault("properties", {})
                props["infra_type"] = "construction_zone"
                infra_color = INFRA_COLORS["construction_zone"]
                props["color"] = infra_color["stroke"]
                props["stroke"] = infra_color["stroke"]
                infra_features.append(feat)
        if infra_features:
            layers["infrastructure"] = {
                "type": "FeatureCollection",
                "features": infra_features,
            }
            self._emit_layer_update(session_id, "infrastructure", layers["infrastructure"], boundary_geojson)

        # Facility points → facility_point layer (via FacilityPlacer)
        self._emit_progress(session_id, "generating_facility_point", "生成设施点图层")
        facilities = getattr(intent, "facilities", [])
        facility_geojson = self.facility_placer.place(
            facilities=facilities,
            landuse_geojson=landuse_current_geojson,
            boundary_geojson=boundary_geojson,
            hazard_points_geojson=hazard_points_geojson,
        )
        if facility_geojson and facility_geojson.get("features"):
            layers["facility_point"] = facility_geojson
            self._emit_layer_update(session_id, "facility_point", facility_geojson, boundary_geojson)

        # Spatial structure → development_axis layer (via AxisBuilder)
        self._emit_progress(session_id, "generating_development_axis", "生成发展轴线图层")
        spatial_structure_geojson = self.axis_builder.build(
            intent, boundary_geojson, landuse_current_geojson
        )
        if spatial_structure_geojson and spatial_structure_geojson.get("features"):
            layers["development_axis"] = spatial_structure_geojson
            self._emit_layer_update(session_id, "development_axis", spatial_structure_geojson, boundary_geojson)

        # Render all layers to GISLayerConfig
        configs = self.map_renderer.render(
            layers=layers,
            boundary_geojson=boundary_geojson,
        )

        layer_summary = ", ".join(c["layerType"] for c in configs)
        logger.info(
            f"[SpatialLayoutEngine] Phase 1 complete: "
            f"{len(configs)} layers ({layer_summary})"
        )

        return configs

    def full_pipeline(
        self,
        summaries: Dict[str, Dict[str, Any]],
        intent: UnifiedSpatialIntent,
        gis_context: Optional[Any] = None,
        boundary_geojson: Optional[Dict[str, Any]] = None,
        landuse_current_geojson: Optional[Dict[str, Any]] = None,
        protection_zones: Optional[Dict[str, Dict[str, Any]]] = None,
        road_geojson: Optional[Dict[str, Any]] = None,
        construction_zone_geojson: Optional[Dict[str, Any]] = None,
        hazard_points_geojson: Optional[Dict[str, Any]] = None,
        reports: Optional[Dict[str, Dict[str, Any]]] = None,
        max_validation_rounds: int = 3,
        session_id: str = "",
    ) -> Tuple[ConflictReport, ResolutionReport, List[Dict[str, Any]]]:
        """Full Phase 0 + Phase 1 pipeline with KG-driven multi-layer output.

        Args:
            summaries: Dimension summaries for conflict detection
            intent: Unified spatial intent
            gis_context: Optional SharedGISContext
            boundary_geojson: Village boundary
            landuse_current_geojson: Current land use parcels
            protection_zones: Dict of protection zone GeoJSONs
            road_geojson: Road network GeoJSON
            construction_zone_geojson: Construction zone GeoJSON
            hazard_points_geojson: Geological hazard points GeoJSON
            reports: Optional L3 dimension reports dict. If provided, builds KG
                     and enables constraint-driven planning zone allocation.
            max_validation_rounds: Max validate→adjust→regenerate cycles (default 3)
            session_id: Optional session ID for SSE progress events

        Returns:
            Tuple of (conflict_report, resolution_report, gis_layer_configs)
        """
        # Auto-build KG if reports provided and not already built
        if reports and not self.has_kg() and landuse_current_geojson:
            self._emit_progress(session_id, "building_kg", "构建规划知识图谱")
            self.build_kg(reports, landuse_current_geojson)

        # Phase 0: Detect and resolve conflicts
        self._emit_progress(session_id, "phase0_conflict_detection", "检测维度间冲突")
        conflict_report, resolution_report = self.detect_and_resolve(summaries)

        # Attach resolution to intent
        intent.conflicts_resolved = resolution_report

        # Phase 1: Generate layout with all layer types
        self._emit_progress(session_id, "phase1_layout_generation", "生成空间布局图层")
        configs = self.generate_layout(
            intent=intent,
            gis_context=gis_context,
            boundary_geojson=boundary_geojson,
            landuse_current_geojson=landuse_current_geojson,
            protection_zones=protection_zones,
            road_geojson=road_geojson,
            construction_zone_geojson=construction_zone_geojson,
            hazard_points_geojson=hazard_points_geojson,
            session_id=session_id,
        )

        # Phase 1.5: Validate and re-optimize loop
        if self._kg_constraints and max_validation_rounds > 0:
            from .validator import LayoutValidator
            validator = LayoutValidator()

            for round_num in range(max_validation_rounds):
                self._emit_progress(
                    session_id, f"validation_round_{round_num + 1}",
                    f"验证第 {round_num + 1} 轮",
                )
                report = validator.validate(configs, self._kg_constraints)
                if report.status == "pass":
                    logger.info("[Engine] Validation passed on round %d", round_num + 1)
                    break

                adjustments = self._violations_to_adjustments(report.violations)
                violation_summary = "; ".join(
                    f"{v.check}: {v.message}" for v in report.violations[:5]
                )
                logger.info(
                    "[Engine] Validation round %d: %d violations (%s), adjustments=%s",
                    round_num + 1, report.total_violations,
                    violation_summary, list(adjustments.keys()),
                )
                if not adjustments:
                    break
                adjusted_targets = self._apply_adjustments(
                    self._last_planning_targets, adjustments,
                    damping=0.2 / (round_num + 1),
                )

                if landuse_current_geojson and self.has_kg():
                    new_planning = self._generate_planning_zones_with_targets(
                        intent, landuse_current_geojson, adjusted_targets,
                    )
                    if new_planning:
                        configs = self._replace_planning_zone_layer(configs, new_planning)

        self._emit_progress(session_id, "complete", "布局生成完成")
        return conflict_report, resolution_report, configs


    def _generate_planning_zones(
        self,
        intent: UnifiedSpatialIntent,
        landuse_geojson: Dict[str, Any],
        protection_zones: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate planning zone GeoJSON using KG-driven constraint allocation.

        Produces a 4-zone planning layer (农田保护区/村庄建设区/生态保护区/一般农业区)
        that DIFFERS from the DLBM-reclassified function_zone layer.

        The zones follow the 土地用途分区 from the land_use_planning report.
        """
        if not self._kg_constraints:
            return None

        # Compute targets from actual landuse DLBM data (no hardcoded defaults)
        targets = self._compute_zone_targets(landuse_geojson, intent)
        self._last_planning_targets = targets

        # Build adjacency graph for spatial constraints
        adj_graph = self._get_adjacency_graph(landuse_geojson)

        allocator = self._get_allocator()
        result = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=targets,
            constraints=self._kg_constraints,
            kg=self.kg,
            protection_zones=protection_zones,
            adjacency_graph=adj_graph,
            adjacency_weight=0.5,
            change_penalty_weight=0.3,
        )

        if not result.get("features"):
            return None

        # Add zone colors for rendering
        for feat in result["features"]:
            zt = feat["properties"].get("assigned_zone", "一般农业区")
            feat["properties"]["color"] = PLANNING_ZONE_COLORS.get(zt, "#CCCCCC")
            feat["properties"]["zone_type"] = zt

        # Count changes vs original
        changed = sum(1 for f in result["features"]
                      if f["properties"].get("changed", False))
        logger.info(
            f"[SpatialLayoutEngine] Planning zones: {len(result['features'])} features, "
            f"{changed} changed ({changed/len(result['features'])*100:.1f}% vs current DLBM)"
        )
        return result

    @staticmethod
    def _compute_zone_targets(
        landuse_geojson: Dict[str, Any],
        intent: UnifiedSpatialIntent,
    ) -> Dict[str, float]:
        """Compute 4-zone area targets from actual DLBM data in landuse GeoJSON.

        No hardcoded defaults — every target is derived from the parcel data.
        Intent metadata can override individual zone targets when provided.
        """
        from .optimizer.mip_allocator import dlbm_to_planning_zone
        from ..utils.geojson_utils import build_parcel_index
        from .zone_generator import resolve_zone_type_for_dlbm
        from collections import defaultdict

        parcel_db, _ = build_parcel_index(
            landuse_geojson, zone_type_fn=resolve_zone_type_for_dlbm
        )

        zone_areas = defaultdict(float)
        for info in parcel_db.values():
            zone_areas[dlbm_to_planning_zone(info["dlbm"])] += info["area_ha"]

        targets = {
            "农田保护区": zone_areas.get("农田保护区", 0.0),
            "村庄建设区": zone_areas.get("村庄建设区", 0.0),
            "生态保护区": zone_areas.get("生态保护区", 0.0),
            "一般农业区": zone_areas.get("一般农业区", 0.0),
        }

        # Intent metadata overrides (only if explicitly provided)
        metadata = getattr(intent, "metadata", {}) or {}
        override_map = {
            "farmland_ha": "农田保护区",
            "construction_ha": "村庄建设区",
            "ecological_ha": "生态保护区",
            "general_agriculture_ha": "一般农业区",
        }
        for meta_key, zone_name in override_map.items():
            if meta_key in metadata:
                targets[zone_name] = float(metadata[meta_key])

        logger.info(
            f"[SpatialLayoutEngine] Zone targets from DLBM: "
            + ", ".join(f"{k}={v:.1f}ha" for k, v in targets.items())
        )
        return targets

    def _violations_to_adjustments(
        self, violations: list,
    ) -> Dict[str, Dict[str, Any]]:
        """Convert ValidationReport violations to target adjustments.

        Handles two violation types:
        - area_constraint: zone area exceeds/falls short of constraint bounds
        - zone_completeness: missing required zones get area incentive boost
        """
        adjustments: Dict[str, Dict[str, Any]] = {}
        for v in violations:
            if v.check == "area_constraint" and v.details:
                zone = v.details.get("zone", "")
                if "超过上限" in v.message:
                    adjustments[zone] = {
                        "action": "reduce",
                        "excess": v.details.get("actual", 0) - v.details.get("limit", 0),
                    }
                elif "低于下限" in v.message:
                    adjustments[zone] = {
                        "action": "increase",
                        "shortfall": v.details.get("limit", 0) - v.details.get("actual", 0),
                    }
            elif v.check == "zone_completeness":
                missing_zone = v.details.get("missing_zone", "")
                if missing_zone and v.severity == "error":
                    # Missing required zone → boost its target area to incentivize creation
                    adjustments[missing_zone] = {
                        "action": "increase",
                        "shortfall": 5.0,
                    }
        return adjustments

    def _apply_adjustments(
        self,
        targets: Dict[str, float],
        adjustments: Dict[str, Dict[str, Any]],
        damping: float = 0.2,
    ) -> Dict[str, float]:
        """Adjust zone area targets based on violations."""
        adjusted = dict(targets)
        for zone, adj in adjustments.items():
            if zone not in adjusted:
                continue
            if adj["action"] == "reduce":
                adjusted[zone] -= adj.get("excess", 0) * damping
            elif adj["action"] == "increase":
                adjusted[zone] += adj.get("shortfall", 0) * damping
        return adjusted

    def _generate_planning_zones_with_targets(
        self,
        intent: UnifiedSpatialIntent,
        landuse_geojson: Dict[str, Any],
        targets: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        """Re-generate planning zones with adjusted targets."""
        adj_graph = self._get_adjacency_graph(landuse_geojson)

        allocator = self._get_allocator()
        result = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=targets,
            constraints=self._kg_constraints,
            kg=self.kg,
            adjacency_graph=adj_graph,
            adjacency_weight=0.5,
            change_penalty_weight=0.3,
        )
        if not result.get("features"):
            return None

        for feat in result["features"]:
            zt = feat["properties"].get("assigned_zone", "一般农业区")
            feat["properties"]["color"] = PLANNING_ZONE_COLORS.get(zt, "#CCCCCC")
            feat["properties"]["zone_type"] = zt

        # Apply CA refinement
        result = self._refine_planning_zones(result)
        return result

    @staticmethod
    def _replace_planning_zone_layer(
        configs: List[Dict[str, Any]],
        new_planning: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Replace planning_zone layer in configs with new data."""
        from .map_renderer import MapRenderer
        new_configs = []
        for c in configs:
            if c.get("layerType") == "planning_zone":
                renderer = MapRenderer()
                rendered = renderer.render(
                    layers={"planning_zone": new_planning},
                    boundary_geojson=None,
                )
                for rc in rendered:
                    if rc.get("layerType") == "planning_zone":
                        new_configs.append(rc)
            else:
                new_configs.append(c)
        return new_configs

    @staticmethod
    def _emit_progress(session_id: str, stage: str, message: str) -> None:
        """Emit GIS layout progress event via SSE (no-op if session_id empty)."""
        if not session_id:
            return
        try:
            from app.utils.sse_publisher import SSEPublisher
            SSEPublisher.send_tool_progress(
                session_id=session_id,
                tool_name="gis_layout_engine",
                stage=stage,
                progress=0.0,
                message=message,
            )
        except Exception as e:
            logger.debug("[Engine] SSE progress emit failed: %s", e)

    @staticmethod
    def _emit_layer_update(
        session_id: str,
        layer_type: str,
        geojson: Dict[str, Any],
        boundary_geojson: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit incremental gis_layer_update SSE event for a single layer.

        Pushes each layer as soon as it's generated instead of waiting for
        all layers to complete. This reduces the per-event payload from
        ~6.5MB (all layers) to ~0.5-1.5MB (single layer), preventing
        main thread blocking on JSON.parse.
        """
        if not session_id:
            return
        try:
            from app.utils.sse_publisher import SSEPublisher
            from .map_renderer import MapRenderer, LAYER_PRIORITY

            renderer = MapRenderer()
            # Render just this one layer
            single_config = renderer.render(
                layers={layer_type: geojson},
                boundary_geojson=boundary_geojson if layer_type == "boundary" else None,
            )

            if single_config:
                SSEPublisher.send_gis_layer_update(
                    session_id=session_id,
                    layer=LAYER_PRIORITY.get(layer_type, 0),
                    dimension_key="spatial_layout",
                    dimension_name="空间布局",
                    layers=single_config,
                )
                logger.debug("[Engine] Emitted layer_update for %s", layer_type)
        except Exception as e:
            logger.debug("[Engine] SSE layer_update emit failed: %s", e)

    def _refine_planning_zones(
        self, geojson: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply CA refinement to planning zone features.

        Closes gaps < 30m between same-type features and simplifies boundaries.
        Falls back to original if area conservation fails (>3% loss).
        """
        try:
            from .optimizer.ca_refiner import ZoneCARefiner
            refiner = ZoneCARefiner(
                merge_distance_m=30.0,
                simplify_tolerance_m=10.0,
                iterations=3,
                min_area_ha=0.04,
            )
            original_area = refiner._total_area_ha(geojson["features"])
            refined = refiner.refine(geojson["features"])
            refined_area = refiner._total_area_ha(refined)

            if abs(original_area - refined_area) / max(original_area, 1) > 0.03:
                logger.warning(
                    "[Engine] CA area loss >3%%, reverting (%.1f -> %.1f ha)",
                    original_area, refined_area,
                )
                return geojson

            logger.info(
                "[Engine] CA refinement: %d features, %.1f -> %.1f ha",
                len(refined), original_area, refined_area,
            )
            return {"type": "FeatureCollection", "features": refined}
        except Exception as e:
            logger.warning("[Engine] CA refinement failed, using original: %s", e)
            return geojson


__all__ = ["SpatialLayoutEngine"]
