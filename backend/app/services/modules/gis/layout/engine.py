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
from .colors import PLANNING_ZONE_COLORS

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

    def has_kg(self) -> bool:
        return self.kg is not None

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
        function_zone_geojson = self.zone_generator.generate(
            intent=intent,
            boundary_geojson=boundary_geojson,
            landuse_current_geojson=landuse_current_geojson,
            protection_zones=protection_zones,
        )

        # Build multi-layer dict
        layers: Dict[str, Dict[str, Any]] = {}

        if function_zone_geojson.get("features"):
            layers["function_zone"] = function_zone_geojson

        # ---- KG-driven planning zone allocation (NEW) ----
        if self.has_kg() and landuse_current_geojson:
            planning_zone_geojson = self._generate_planning_zones(
                intent, landuse_current_geojson
            )
            if planning_zone_geojson and planning_zone_geojson.get("features"):
                layers["planning_zone"] = planning_zone_geojson

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

        # Roads + construction zone → infrastructure layer
        infra_features = []
        if road_geojson and road_geojson.get("features"):
            for feat in road_geojson["features"]:
                feat = dict(feat)
                feat.setdefault("properties", {})["infra_type"] = "road"
                infra_features.append(feat)
        if construction_zone_geojson and construction_zone_geojson.get("features"):
            for feat in construction_zone_geojson["features"]:
                feat = dict(feat)
                feat.setdefault("properties", {})["infra_type"] = "construction_zone"
                infra_features.append(feat)
        if infra_features:
            layers["infrastructure"] = {
                "type": "FeatureCollection",
                "features": infra_features,
            }

        # Facility points → facility_point layer (via FacilityPlacer)
        facilities = getattr(intent, "facilities", [])
        facility_geojson = self.facility_placer.place(
            facilities=facilities,
            landuse_geojson=landuse_current_geojson,
            boundary_geojson=boundary_geojson,
            hazard_points_geojson=hazard_points_geojson,
        )
        if facility_geojson and facility_geojson.get("features"):
            layers["facility_point"] = facility_geojson

        # Spatial structure → development_axis layer (via AxisBuilder)
        spatial_structure_geojson = self.axis_builder.build(
            intent, boundary_geojson, landuse_current_geojson
        )
        if spatial_structure_geojson and spatial_structure_geojson.get("features"):
            layers["development_axis"] = spatial_structure_geojson

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

        Returns:
            Tuple of (conflict_report, resolution_report, gis_layer_configs)
        """
        # Auto-build KG if reports provided and not already built
        if reports and not self.has_kg() and landuse_current_geojson:
            self.build_kg(reports, landuse_current_geojson)

        # Phase 0: Detect and resolve conflicts
        conflict_report, resolution_report = self.detect_and_resolve(summaries)

        # Attach resolution to intent
        intent.conflicts_resolved = resolution_report

        # Phase 1: Generate layout with all layer types
        configs = self.generate_layout(
            intent=intent,
            gis_context=gis_context,
            boundary_geojson=boundary_geojson,
            landuse_current_geojson=landuse_current_geojson,
            protection_zones=protection_zones,
            road_geojson=road_geojson,
            construction_zone_geojson=construction_zone_geojson,
            hazard_points_geojson=hazard_points_geojson,
        )

        return conflict_report, resolution_report, configs


    def _generate_planning_zones(
        self,
        intent: UnifiedSpatialIntent,
        landuse_geojson: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Generate planning zone GeoJSON using KG-driven constraint allocation.

        Produces a 4-zone planning layer (永久基本农田/村庄建设区/生态保护区/一般农地区)
        that DIFFERS from the DLBM-reclassified function_zone layer.

        The zones follow the 土地用途分区 from the land_use_planning report.
        """
        if not self._kg_constraints:
            return None

        # 4-zone targets from planning report (overridden by intent metadata if set)
        metadata = getattr(intent, "metadata", {}) or {}
        total_area = metadata.get("total_area_ha", 2352.56)
        targets = {
            "永久基本农田保护区": metadata.get("farmland_ha", 78.83),
            "村庄建设区": metadata.get("construction_ha", 30.50),
            "生态保护区": metadata.get("ecological_ha", 362.02),
            "一般农地区": metadata.get("general_agriculture_ha", 1881.54),
        }

        allocator = self._get_allocator()
        result = allocator.solve(
            landuse_geojson=landuse_geojson,
            targets=targets,
            constraints=self._kg_constraints,
            kg=self.kg,
        )

        if not result.get("features"):
            return None

        # Add zone colors for rendering
        for feat in result["features"]:
            zt = feat["properties"].get("assigned_zone", "一般农地区")
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


__all__ = ["SpatialLayoutEngine"]
