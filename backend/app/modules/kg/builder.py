"""
PlanningKG — 规划知识图谱构建器

将 L3 报告 + GIS 数据转化为 RDF 知识图谱。
每个地块、约束、指标都是独立的命名实体，可通过 SPARQL 查询。

Usage:
    kg = PlanningKG()
    kg.build_from_reports(reports, landuse_geojson)
    result = kg.query("SELECT ?c WHERE { ?c a pln:Constraint }")
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from app.modules.gis.schema.spatial_types import CurrentLandUseParcel
from app.utils.schema_validator import validate_ingestion_point

from rdflib import Graph, Namespace, Literal, RDF, URIRef, BNode
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from app.utils.crs_engine import project_to_metric, get_metric_crs
from .ontology import PLN, GEO, EntityTypes, Relations, FACILITY_TYPES, REGULATION_TYPES

logger = get_logger(__name__)

# Predefined constraints extracted from L3 report patterns
CONSTRAINT_PATTERNS = [
    {
        "metric_key": "建设用地规模_公顷",
        "constraint_id": "construction_cap",
        "field": "construction_area_ha",
        "operator": "<=",
        "description": "村庄建设用地规模上限",
    },
    {
        "metric_key": "耕地保有量_公顷",
        "constraint_id": "farmland_min",
        "field": "farmland_area_ha",
        "operator": ">=",
        "description": "耕地保有量下限",
    },
    {
        "metric_key": "永久基本农田_公顷",
        "constraint_id": "permanent_farmland_min",
        "field": "permanent_farmland_ha",
        "operator": ">=",
        "description": "永久基本农田保护面积",
    },
    {
        "metric_key": "生态保护红线面积",
        "constraint_id": "ecological_redline_min",
        "field": "ecological_redline_ha",
        "operator": ">=",
        "description": "生态保护红线面积约束",
    },
    {
        "metric_key": "森林覆盖率_百分比",
        "constraint_id": "forest_coverage_min",
        "field": "forest_coverage_pct",
        "operator": ">=",
        "description": "森林覆盖率下限",
    },
    {
        "metric_key": "新增建设用地_公顷",
        "constraint_id": "construction_expansion",
        "field": "new_construction_ha",
        "operator": "=",
        "description": "新增建设用地规模",
    },
    {
        "metric_key": "林地保有量_公顷",
        "constraint_id": "forest_land_min",
        "field": "forest_land_ha",
        "operator": ">=",
        "description": "林地保有量下限",
    },
]

# Metrics that should always be extracted as Indicator entities
INDICATOR_PATTERNS = [
    ("规划期末人口", "population", "人"),
    ("人均建设用地", "per_capita_construction_sqm", "m²/人"),
    ("村集体年收入", "village_income_yuan", "元"),
    ("带动就业", "employment_persons", "人"),
    ("常住人口", "resident_population", "人"),
]

# Zone definitions extracted from land_use_planning report tables
ZONE_TYPE_PATTERNS = {
    "农田保护区": {"color": "#FFE4B5", "restrictions": ["禁止非农化", "禁止非粮化"]},
    "村庄建设区": {"color": "#FF6347", "restrictions": ["建设用地规模受控"]},
    "生态保护区": {"color": "#2E8B57", "restrictions": ["禁止工业开发", "禁止城镇化"]},
    "一般农业区": {"color": "#98FB98", "restrictions": ["限制大规模非农建设"]},
}


@dataclass
class KGInputParcels:
    """Container for typed parcels consumed by KG builder.
    
    This class ensures all parcel data flows through the ingestion layer
    via from_geojson() method, maintaining schema injection enforcement.
    """
    parcels: List[CurrentLandUseParcel] = field(default_factory=list)
    
    @classmethod
    def from_geojson(cls, geojson: Dict[str, Any]) -> "KGInputParcels":
        """Convert GeoJSON to typed parcels (via ingestion layer).
        
        This is the SINGLE ENTRY POINT for parcel data into KG builder.
        All other code must use this wrapper to ensure schema injection.
        
        Args:
            geojson: Standard GeoJSON FeatureCollection
            
        Returns:
            KGInputParcels with validated typed parcels
        """
        from app.modules.gis.schema import ingest_current_landuse
        
        try:
            # Use ingestion layer to enforce proper parsing
            parcels = ingest_current_landuse(geojson)
            logger.debug(f"[KGBuilder] Ingested {len(parcels)} parcels from GeoJSON")
            return cls(parcels=parcels)
        except Exception as e:
            logger.error(f"[KGBuilder] Failed to ingest parcels from GeoJSON: {e}")
            return cls(parcels=[])




# Semantic-qualified key → constraint mapping (parallel to Chinese-key patterns)
SEMANTIC_CONSTRAINT_MAP = {
    "max_construction_ha": {
        "constraint_id": "construction_cap",
        "field": "construction_area_ha",
        "operator": "<=",
        "description": "村庄建设用地规模上限",
    },
    "min_farmland_protection_ha": {
        "constraint_id": "farmland_min",
        "field": "farmland_area_ha",
        "operator": ">=",
        "description": "耕地保有量下限",
    },
    "min_ecological_redline_ha": {
        "constraint_id": "ecological_redline_min",
        "field": "ecological_redline_ha",
        "operator": ">=",
        "description": "生态保护红线面积约束",
    },
    "planned_construction_ha": {
        "constraint_id": "construction_planned",
        "field": "construction_area_ha",
        "operator": "=",
        "description": "规划建设用地面积",
    },
    "planned_farmland_ha": {
        "constraint_id": "farmland_planned",
        "field": "farmland_area_ha",
        "operator": "=",
        "description": "规划耕地面积",
    },
}


class PlanningKG:
    """规划知识图谱: 基于 RDFLib 的轻量级图存储。

    存储:
      - 地块实体 (Parcel): 660 nodes with DLBM/DLMC/area/geometry
      - 约束实体 (Constraint): extracted from report metrics
      - 指标实体 (Indicator): current/planned values
      - 分区实体 (Zone): planning zone definitions
      - 关系: constrained_by, adjacent_to, within_zone
    """

    def __init__(self, village_name: str = ""):
        self.g = Graph()
        self.g.bind("pln", PLN)
        self.g.bind("geo", GEO)
        self.village_name = village_name
        self._parcel_count = 0
        self._constraint_count = 0

    def build_from_reports(
        self,
        reports: Dict[str, Dict[str, Any]],
        landuse_geojson: Optional[Dict[str, Any]] = None,
        boundary_geojson: Optional[Dict[str, Any]] = None,
        gis_data: Optional[Dict[str, Any]] = None,
        parcels: Optional[List[Any]] = None,
    ) -> "PlanningKG":
        """一键构建完整知识图谱。

        Args:
            reports: {dimension_key: {summary: {...}, content: "..."}}
            landuse_geojson: 现状用地图斑 GeoJSON (660 parcels) [legacy, prefer parcels]
            boundary_geojson: 村界 GeoJSON
            gis_data: Full GIS data dict (used to compute zone areas from actual data)
            parcels: Typed CurrentLandUseParcel list from ingest_current_landuse() [preferred]

        When parcels is provided, typed fields are used directly (parcel.dlbm, parcel.bsm, etc.)
        instead of raw dict props.get() access. This is the schema-injection path.
        When landuse_geojson is provided without parcels, the legacy raw dict path is used.

        Returns:
            self (for chaining)
        """
        self.g = Graph()
        self.g.bind("pln", PLN)
        self._parcel_count = 0
        self._constraint_count = 0

        # Compute zone areas from GIS data (replaces hardcoded values)
        zone_areas = self._compute_zone_areas_from_gis(gis_data)

        # 1. Add village entity
        village = PLN.village
        self.g.add((village, RDF.type, PLN.Village))
        self.g.add((village, PLN.name, Literal(self.village_name or "unknown")))

        # 2. Add parcels — prefer typed parcels over raw GeoJSON
        if parcels:
            self._add_parcels_typed(parcels)
        elif landuse_geojson:
            self._add_parcels(landuse_geojson)

        # 3. Add constraints from reports
        self._add_constraints(reports, zone_areas)

        # 4. Add indicators from reports
        self._add_indicators(reports)

        # 5. Add zones from report content
        self._add_zones(reports, zone_areas)

        # 6. Build spatial adjacency
        if landuse_geojson:
            self._add_spatial_relations(landuse_geojson)

        # 7. Add Project entities (from report content)
        self._add_projects(reports)

        # 8. Add Regulation entities (from constraints)
        self._add_regulations()

        # 9. Add designated_as relations (parcel → planning zone)
        if landuse_geojson:
            self._add_designated_as_relations(landuse_geojson)

        # 10. Add spatial infrastructure (facilities, roads, water bodies)
        if landuse_geojson:
            self._add_spatial_infrastructure(landuse_geojson)

        # 11. GIS-measured constraints (most accurate)
        if gis_data:
            self._add_gis_constraint_triples(gis_data)

        logger.info(
            f"[PlanningKG] Built KG: {self._parcel_count} parcels, "
            f"{self._constraint_count} constraints, "
            f"{len(self.g)} total triples"
        )
        return self

    # Intent → constraint_type mapping
    _INTENT_CONSTRAINT_MAP = {
        "farmland_protection": {
            "field": "farmland_area_ha",
            "operator": ">=",
            "description": "永久基本农田保护面积",
        },
        "ecological_redline": {
            "field": "ecological_redline_ha",
            "operator": ">=",
            "description": "生态保护红线面积约束",
        },
        "historical": {
            "field": "heritage_protection",
            "operator": ">=",
            "description": "历史文化遗产保护约束",
        },
        "hazard": {
            "field": "geological_hazard_zone",
            "operator": "exclude",
            "description": "地质灾害避让约束",
        },
    }

    def build_from_intent(
        self,
        intent: Dict[str, Any],
        landuse_geojson: Optional[Dict[str, Any]] = None,
        boundary_geojson: Optional[Dict[str, Any]] = None,
        gis_data: Optional[Dict[str, Any]] = None,
    ) -> "PlanningKG":
        """Build KG from PARSE Agent's structured intent (instead of raw reports).

        Skips all regex/text parsing — zones, facilities, axes, constraints
        come directly from UnifiedSpatialIntent. GIS data (parcels, adjacency,
        infrastructure) still built from gis_data.

        Args:
            intent: UnifiedSpatialIntent as dict (from parse_planning_text output)
            landuse_geojson: Current landuse parcels GeoJSON
            boundary_geojson: Village boundary GeoJSON
            gis_data: Full GIS data dict

        Returns:
            self (for chaining)
        """
        self.g = Graph()
        self.g.bind("pln", PLN)
        self._parcel_count = 0
        self._constraint_count = 0

        zone_areas = self._compute_zone_areas_from_gis(gis_data)

        # 1. Village entity
        village = PLN.village
        self.g.add((village, RDF.type, PLN.Village))
        self.g.add((village, PLN.name, Literal(self.village_name or "unknown")))

        # 2. Parcels from GIS (unchanged)
        if landuse_geojson:
            self._add_parcels(landuse_geojson)

        # 3. Zones from intent
        self._add_zones_from_intent(intent, zone_areas)

        # 4. Constraints from intent
        self._add_constraints_from_intent(intent, zone_areas)

        # 5. Facilities from intent
        self._add_facilities_from_intent(intent)

        # 6. Axes from intent
        self._add_axes_from_intent(intent)

        # 7. Spatial adjacency (GIS, unchanged)
        if landuse_geojson:
            self._add_spatial_relations(landuse_geojson)

        # 8. Regulations (from constraints already added)
        self._add_regulations()

        # 9. Designated relations (GIS, unchanged)
        if landuse_geojson:
            self._add_designated_as_relations(landuse_geojson)

        # 10. Infrastructure (GIS, unchanged)
        if landuse_geojson:
            self._add_spatial_infrastructure(landuse_geojson)

        # 11. GIS-measured constraints (most accurate)
        if gis_data:
            self._add_gis_constraint_triples(gis_data)

        logger.info(
            f"[PlanningKG] Built KG from intent: {self._parcel_count} parcels, "
            f"{self._constraint_count} constraints, "
            f"{len(self.g)} total triples"
        )
        return self

    def _add_zones_from_intent(
        self,
        intent: Dict[str, Any],
        zone_areas: Optional[Dict[str, float]] = None,
    ):
        """Add zone entities from intent.zones."""
        zones = intent.get("zones", [])
        if not zones:
            # Fallback: add standard zones from ZONE_TYPE_PATTERNS
            for name, props in ZONE_TYPE_PATTERNS.items():
                zone = PLN[f"zone_{name}"]
                self.g.add((zone, RDF.type, PLN.Zone))
                self.g.add((zone, PLN.name, Literal(name)))
                self.g.add((zone, PLN.color, Literal(props["color"])))
                for restriction in props["restrictions"]:
                    self.g.add((zone, PLN.restriction, Literal(restriction)))
                self.g.add((PLN.village, PLN.has_zone, zone))
            return

        for z in zones:
            zone_id = z.get("zone_id", z.get("land_use", "unknown"))
            zone = PLN[f"zone_{zone_id}"]
            self.g.add((zone, RDF.type, PLN.Zone))
            self.g.add((zone, PLN.name, Literal(z.get("land_use", zone_id))))

            # Area: area_ratio × total GIS area > zone_areas > omit
            area_ha = None
            area_ratio = z.get("area_ratio")
            if area_ratio and zone_areas:
                total_area = sum(zone_areas.values())
                if total_area > 0:
                    area_ha = round(area_ratio * total_area, 2)
            if area_ha is None and zone_areas:
                land_use = z.get("land_use", "")
                area_ha = zone_areas.get(land_use)
            if area_ha is not None:
                self.g.add((zone, PLN.area_target_ha, Literal(area_ha, datatype=XSD.double)))

            # Color from ZONE_TYPE_PATTERNS if matching
            land_use = z.get("land_use", "")
            pattern = ZONE_TYPE_PATTERNS.get(land_use)
            if pattern:
                self.g.add((zone, PLN.color, Literal(pattern["color"])))
                for restriction in pattern["restrictions"]:
                    self.g.add((zone, PLN.restriction, Literal(restriction)))

            # Direction as placement hint
            direction = z.get("direction", "")
            if direction:
                self.g.add((zone, PLN.direction, Literal(direction)))

            # Density
            density = z.get("density", "")
            if density:
                self.g.add((zone, PLN.density, Literal(density)))

            self.g.add((PLN.village, PLN.has_zone, zone))

    def _add_constraints_from_intent(
        self,
        intent: Dict[str, Any],
        zone_areas: Optional[Dict[str, float]] = None,
    ):
        """Add constraint entities from intent.constraints."""
        constraints = intent.get("constraints", [])
        for c in constraints:
            ctype = c.get("constraint_type", "")
            mapping = self._INTENT_CONSTRAINT_MAP.get(ctype)
            if not mapping:
                continue

            cid = c.get("constraint_id", f"intent_{ctype}")
            strict = c.get("strict", True)
            self._add_constraint_triple(
                cid=cid,
                field=mapping["field"],
                operator=mapping["operator"],
                value=0.0,  # Actual value from GIS data below
                description=mapping["description"],
                source=f"intent:{ctype}",
            )

            # Add strictness as extra triple
            constraint_uri = PLN[cid]
            self.g.add((constraint_uri, PLN.strict, Literal(strict, datatype=XSD.boolean)))

            # geometry_ref → link to GIS layer
            geo_ref = c.get("geometry_ref", "")
            if geo_ref:
                self.g.add((constraint_uri, PLN.geometry_ref, Literal(geo_ref)))

        # Add ecological redline from GIS zone_areas
        eco_area = zone_areas.get("生态绿地") if zone_areas else None
        if eco_area is not None:
            c = PLN.ecological_redline_protection
            self.g.add((c, RDF.type, PLN.Constraint))
            self.g.add((c, PLN.constraint_id, Literal("ecological_redline_protection")))
            self.g.add((c, PLN.field, Literal("ecological_redline_ha")))
            self.g.add((c, PLN.operator, Literal(">=")))
            self.g.add((c, PLN.value, Literal(eco_area, datatype=XSD.double)))
            self.g.add((c, PLN.prohibits, Literal("industrial_development")))
            self.g.add((c, PLN.prohibits, Literal("urbanization")))
            self.g.add((c, PLN.source, Literal("gis_data")))
            self._constraint_count += 1

    def _add_facilities_from_intent(self, intent: Dict[str, Any]):
        """Add facility entities from intent.facilities."""
        facilities = intent.get("facilities", [])
        for f in facilities:
            fid = f.get("facility_id", f.get("facility_type", "unknown"))
            facility = PLN[f"facility_{fid}"]
            self.g.add((facility, RDF.type, PLN.Facility))
            self.g.add((facility, PLN.name, Literal(f.get("facility_type", fid))))

            target_zone = f.get("target_zone", "")
            if target_zone:
                zone_uri = PLN[f"zone_{target_zone}"]
                self.g.add((facility, PLN.serves, zone_uri))

            location_hint = f.get("location_hint", "")
            if location_hint:
                self.g.add((facility, PLN.location_hint, Literal(location_hint)))

            status = f.get("status", "")
            if status:
                self.g.add((facility, PLN.status, Literal(status)))

            self.g.add((PLN.village, PLN.has_facility, facility))

    def _add_axes_from_intent(self, intent: Dict[str, Any]):
        """Add axis entities from intent.axes."""
        axes = intent.get("axes", [])
        for a in axes:
            aid = a.get("axis_id", "unknown")
            axis = PLN[f"axis_{aid}"]
            self.g.add((axis, RDF.type, PLN.Axis))
            self.g.add((axis, PLN.name, Literal(a.get("label", aid))))
            self.g.add((axis, PLN.axis_type, Literal(a.get("axis_type", "primary"))))

            direction = a.get("direction", "")
            if direction:
                self.g.add((axis, PLN.direction, Literal(direction)))

            # Connect to zones/facilities
            for connected_id in a.get("connects", []):
                target = PLN[f"zone_{connected_id}"]
                self.g.add((axis, PLN.connects, target))

            self.g.add((PLN.village, PLN.has_axis, axis))

    def _add_gis_constraint_triples(self, gis_data: Dict[str, Any]):
        """Add GIS-measured constraints as RDF triples (most accurate source).

        Uses GISMetricsCalculator to compute real area constraints from
        landuse GeoJSON and adds them as both village-level triples and
        Constraint entities.
        """
        try:
            from app.tools.gis._analytics.metrics_calculator import GISMetricsCalculator
            metrics = GISMetricsCalculator.compute_land_use_metrics(gis_data)
        except Exception as e:
            logger.warning(f"[PlanningKG] GIS constraint computation failed: {e}")
            return

        village_uri = PLN.village

        # Village-level metric triples
        self.g.add((village_uri, PLN.constructionCap_ha,
                     Literal(metrics["construction_area_ha"], datatype=XSD.double)))
        self.g.add((village_uri, PLN.farmlandMin_ha,
                     Literal(metrics["farmland_area_ha"], datatype=XSD.double)))
        self.g.add((village_uri, PLN.ecologicalMin_ha,
                     Literal(metrics["ecological_area_ha"], datatype=XSD.double)))
        self.g.add((village_uri, PLN.forestCoverage_pct,
                     Literal(metrics["forest_coverage"], datatype=XSD.double)))
        self.g.add((village_uri, PLN.totalArea_ha,
                     Literal(metrics["total_area_ha"], datatype=XSD.double)))

        # Constraint entities (for query/retrieval by downstream tools)
        gis_constraints = [
            ("gis_construction_cap", "construction_cap", "construction_area_ha",
             "<=", metrics["construction_area_ha"], "GIS实测建设用地规模上限"),
            ("gis_farmland_min", "farmland_min", "farmland_area_ha",
             ">=", metrics["farmland_area_ha"], "GIS实测耕地保有量下限"),
            ("gis_ecological_min", "ecological_redline", "ecological_area_ha",
             ">=", metrics["ecological_area_ha"], "GIS实测生态保护红线下限"),
        ]
        for cid, ctype, field, op, value, desc in gis_constraints:
            self._add_constraint_triple(cid, field, op, value, desc, "gis_measured")

        logger.info(
            f"[PlanningKG] Added {len(gis_constraints)} GIS-measured constraints: "
            f"construction<={metrics['construction_area_ha']}ha, "
            f"farmland>={metrics['farmland_area_ha']}ha, "
            f"ecological>={metrics['ecological_area_ha']}ha"
        )

    def _compute_zone_areas_from_gis(
        self, gis_data: Optional[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Compute zone areas from GIS landuse data, replacing hardcoded values.

        Loads landuse_current GeoJSON, projects to metric CRS, dissolves by
        zone_type, and computes area in hectares.

        Returns:
            {zone_type: area_ha} e.g. {"农业用地": 1960.7, "生态绿地": 362.0}
        """
        if not gis_data:
            return {}

        landuse_geojson = gis_data.get("landuse_current_geojson")
        if not landuse_geojson or not landuse_geojson.get("features"):
            return {}

        try:
            from app.utils.geojson_utils import geojson_to_geodataframe
            from app.modules.gis.schema import get_zone_type_for_dlbm

            gdf = geojson_to_geodataframe(landuse_geojson)
            if gdf is None or len(gdf) == 0:
                return {}

            # Add zone_type column from DLBM
            gdf["zone_type"] = gdf["DLBM"].apply(
                lambda d: get_zone_type_for_dlbm(str(d).strip())
            )

            # Project to metric CRS for accurate area calculation
            gdf_proj = project_to_metric(gdf)

            # Fix invalid geometries before dissolve to prevent TopologyException
            gdf_proj["geometry"] = gdf_proj.geometry.apply(
                lambda g: g.buffer(0) if g is not None and not g.is_valid else g
            )
            gdf_proj = gdf_proj[~gdf_proj.is_empty]

            # Dissolve by zone_type and compute area
            dissolved = gdf_proj.dissolve(by="zone_type", aggfunc="sum")
            dissolved["area_ha"] = dissolved.geometry.area / 10000.0

            zone_areas = {}
            for zone_type, row in dissolved.iterrows():
                zone_areas[str(zone_type)] = round(float(row["area_ha"]), 2)

            logger.info(
                f"[PlanningKG] Computed zone areas from GIS: {zone_areas}"
            )
            return zone_areas

        except Exception as e:
            logger.warning(f"[PlanningKG] Zone area computation failed: {e}")
            return {}

    def _add_parcels(self, geojson: Dict[str, Any]):
        """Add all parcels as PLN:Parcel entities.

        Uses composite key f"{BSM}_{DLBM}_{SHAPE_Area}" as entity name because
        BSM is NOT unique — 80 BSMs have 2 different DLBM codes, and 38 BSM+DLBM
        pairs have multiple features with different geometries/areas.
        Three-level key ensures all 660 parcels are preserved.
        """
        features = geojson.get("features", [])
        from app.modules.gis.schema import get_zone_type_for_dlbm
        from app.tools.gis._generation.zone_generator import resolve_zone_type_for_dlbm

        duplicate_bsms = set()
        seen_bsms = set()
        for ft in features:
            props = ft.get("properties", {})
            bsm = str(props.get("BSM", "")).strip()
            dlbm = str(props.get("DLBM", "")).strip()
            dlmc = str(props.get("DLMC", "")).strip()
            area = props.get("DLMJ", 0) or props.get("SHAPE_Area", 0)

            if not bsm:
                continue

            shape_area = props.get("SHAPE_Area", 0) or 0
            composite_key = f"{bsm}_{dlbm}_{int(shape_area)}"
            if bsm in seen_bsms:
                duplicate_bsms.add(bsm)
            seen_bsms.add(bsm)

            parcel = PLN[f"parcel_{composite_key}"]
            self.g.add((parcel, RDF.type, PLN.Parcel))
            self.g.add((parcel, PLN.bsm, Literal(bsm)))
            self.g.add((parcel, PLN.dlbm, Literal(dlbm)))
            self.g.add((parcel, PLN.dlmc, Literal(dlmc)))
            self.g.add((parcel, PLN.area_sqm, Literal(area, datatype=XSD.double)))
            self.g.add((parcel, PLN.area_ha, Literal(area / 10000, datatype=XSD.double)))

            # Current zone type (DLBM classification)
            zone_type = resolve_zone_type_for_dlbm(dlbm)
            self.g.add((parcel, PLN.current_zone_type, Literal(zone_type)))

            # Parcel located_in Village
            self.g.add((parcel, Relations.located_in, PLN.village))

            self._parcel_count += 1

        if duplicate_bsms:
            logger.info(
                f"[PlanningKG] Found {len(duplicate_bsms)} BSMs with multiple DLBM codes"
            )

    def _add_parcels_typed(self, parcels: List[Any]) -> None:
        """Add parcels from typed CurrentLandUseParcel instances (schema-injection path).

        Uses typed model fields (parcel.dlbm, parcel.bsm, parcel.area_sqm, etc.)
        instead of raw dict props.get() access. This is the preferred path per
        01_DESIGN_GOALS.md §6 — all GIS data enters through ingestion layer.

        Args:
            parcels: List of typed parcel objects from ingest_current_landuse()
                     (CurrentLandUseParcel or BaseLandUseParcel instances)
        """
        from app.tools.gis._generation.zone_generator import resolve_zone_type_for_dlbm

        duplicate_bsms = set()
        seen_bsms = set()

        for parcel in parcels:
            bsm = str(parcel.bsm).strip()
            dlbm = str(parcel.dlbm).strip()
            dlmc = str(parcel.name).strip()
            area = float(parcel.area_sqm) if parcel.area_sqm else 0.0

            if not bsm:
                continue

            shape_area = float(parcel.area_sqm) if parcel.area_sqm else 0.0
            composite_key = f"{bsm}_{dlbm}_{int(shape_area)}"
            if bsm in seen_bsms:
                duplicate_bsms.add(bsm)
            seen_bsms.add(bsm)

            parcel_uri = PLN[f"parcel_{composite_key}"]
            self.g.add((parcel_uri, RDF.type, PLN.Parcel))
            self.g.add((parcel_uri, PLN.bsm, Literal(bsm)))
            self.g.add((parcel_uri, PLN.dlbm, Literal(dlbm)))
            self.g.add((parcel_uri, PLN.dlmc, Literal(dlmc)))
            self.g.add((parcel_uri, PLN.area_sqm, Literal(area, datatype=XSD.double)))
            self.g.add((parcel_uri, PLN.area_ha, Literal(area / 10000, datatype=XSD.double)))

            # Current zone type (DLBM classification)
            zone_type = resolve_zone_type_for_dlbm(dlbm)
            self.g.add((parcel_uri, PLN.current_zone_type, Literal(zone_type)))

            # Parcel located_in Village
            self.g.add((parcel_uri, Relations.located_in, PLN.village))

            self._parcel_count += 1

        if duplicate_bsms:
            logger.info(
                f"[PlanningKG] Found {len(duplicate_bsms)} BSMs with multiple DLBM codes (typed)"
            )

    def _add_constraints(
        self,
        reports: Dict[str, Dict[str, Any]],
        zone_areas: Optional[Dict[str, float]] = None,
    ):
        """Extract constraints from report summaries using patterns.

        Matches both Chinese metric keys (e.g. 建设用地规模_公顷) and
        semantic-qualified keys (e.g. max_construction_ha).
        """
        for dk, report in reports.items():
            metrics = report.get("summary", {}).get("metrics", {})
            if not metrics:
                continue

            # Chinese metric key matching (original)
            for pattern in CONSTRAINT_PATTERNS:
                metric_key = pattern["metric_key"]
                if metric_key in metrics:
                    value = metrics[metric_key]
                    if value is None:
                        continue

                    cid = f"{pattern['constraint_id']}_{dk}"
                    self._add_constraint_triple(cid, pattern["field"],
                                                pattern["operator"], float(value),
                                                pattern["description"], dk)

            # Semantic-qualified key matching (new)
            for sem_key, mapping in SEMANTIC_CONSTRAINT_MAP.items():
                if sem_key in metrics:
                    value = metrics[sem_key]
                    if value is None:
                        continue
                    cid = f"{mapping['constraint_id']}_{dk}"
                    self._add_constraint_triple(cid, mapping["field"],
                                                mapping["operator"], float(value),
                                                mapping["description"], dk)

        # Add ecological redline constraint from GIS data or report metrics
        eco_area = None
        if zone_areas:
            eco_area = zone_areas.get("生态绿地")
        if eco_area is None:
            # Fallback: try report metrics
            for dk, report in reports.items():
                metrics = report.get("summary", {}).get("metrics", {})
                for key in ("生态保护红线面积", "min_ecological_redline_ha"):
                    if key in metrics and metrics[key] is not None:
                        eco_area = float(metrics[key])
                        break
                if eco_area is not None:
                    break
        if eco_area is not None:
            c = PLN.ecological_redline_protection
            self.g.add((c, RDF.type, PLN.Constraint))
            self.g.add((c, PLN.constraint_id, Literal("ecological_redline_protection")))
            self.g.add((c, PLN.field, Literal("ecological_redline_ha")))
            self.g.add((c, PLN.operator, Literal(">=")))
            self.g.add((c, PLN.value, Literal(eco_area, datatype=XSD.double)))
            self.g.add((c, PLN.prohibits, Literal("industrial_development")))
            self.g.add((c, PLN.prohibits, Literal("urbanization")))
            self.g.add((c, PLN.source, Literal("gis_data")))
            self._constraint_count += 1

    def _add_constraint_triple(
        self, cid: str, field: str, operator: str,
        value: float, description: str, source: str,
    ) -> None:
        """Add a single constraint as RDF triples."""
        constraint = PLN[cid]
        self.g.add((constraint, RDF.type, PLN.Constraint))
        self.g.add((constraint, PLN.constraint_id, Literal(cid)))
        self.g.add((constraint, PLN.field, Literal(field)))
        self.g.add((constraint, PLN.operator, Literal(operator)))
        self.g.add((constraint, PLN.value, Literal(value, datatype=XSD.double)))
        self.g.add((constraint, PLN.description, Literal(description)))
        self.g.add((constraint, PLN.source, Literal(source)))
        self.g.add((PLN.village, PLN.has_constraint, constraint))
        self._constraint_count += 1

    def _add_indicators(self, reports: Dict[str, Dict[str, Any]]):
        """Add planning indicators as PLN:Indicator entities."""
        for dk, report in reports.items():
            metrics = report.get("summary", {}).get("metrics", {})
            for key, val in metrics.items():
                if val is None:
                    continue
                if not isinstance(val, (int, float)):
                    continue

                indicator = PLN[f"indicator_{dk}_{key}"]
                self.g.add((indicator, RDF.type, PLN.Indicator))
                self.g.add((indicator, PLN.name, Literal(key)))
                self.g.add((indicator, PLN.value, Literal(float(val), datatype=XSD.double)))
                self.g.add((indicator, PLN.source, Literal(dk)))
                self.g.add((PLN.village, PLN.has_indicator, indicator))

    def _add_zones(
        self,
        reports: Dict[str, Dict[str, Any]],
        zone_areas: Optional[Dict[str, float]] = None,
    ):
        """Add planning zone definitions from report content.

        Zone area targets are computed from GIS data when available,
        falling back to report metrics, then omitting if neither exists.
        """
        for name, props in ZONE_TYPE_PATTERNS.items():
            zone = PLN[f"zone_{name}"]
            self.g.add((zone, RDF.type, PLN.Zone))
            self.g.add((zone, PLN.name, Literal(name)))
            self.g.add((zone, PLN.color, Literal(props["color"])))
            for restriction in props["restrictions"]:
                self.g.add((zone, PLN.restriction, Literal(restriction)))
            self.g.add((PLN.village, PLN.has_zone, zone))

        # Add spatial structure zones with computed areas
        # GIS data zones: create zone entities from zone_areas regardless of report keywords
        # zone_type names must match zone_schema.ZONE_TYPE_COLORS keys
        GIS_ZONE_MAP = [
            ("农业用地", "zone_gis_farmland"),
            ("生态绿地", "zone_gis_ecological"),
            ("居住用地", "zone_gis_residential"),
            ("产业用地", "zone_gis_construction"),
        ]
        if zone_areas:
            for zone_type, zone_uri_name in GIS_ZONE_MAP:
                if zone_type not in zone_areas:
                    continue
                zone = PLN[zone_uri_name]
                self.g.add((zone, RDF.type, PLN.Zone))
                self.g.add((zone, PLN.name, Literal(zone_type)))
                self.g.add((zone, PLN.area_target_ha, Literal(zone_areas[zone_type], datatype=XSD.double)))
                self.g.add((PLN.village, PLN.has_zone, zone))

        # Report-content zones: create from keyword matches in report text
        for dk, report in reports.items():
            content = report.get("content", "")
            metrics = report.get("summary", {}).get("metrics", {})

            for zone_name, zone_uri_name, zone_type in [
                ("生态农业发展区", "zone_eco_agriculture", "农业用地"),
                ("生态保育屏障区", "zone_eco_barrier", "生态绿地"),
                ("宜居生活建设区", "zone_livable", "居住用地"),
            ]:
                if zone_name not in content:
                    continue

                zone = PLN[zone_uri_name]
                self.g.add((zone, RDF.type, PLN.Zone))
                self.g.add((zone, PLN.name, Literal(zone_name)))

                # Area: GIS data > report metrics > omit
                area_ha = None
                if zone_areas and zone_type in zone_areas:
                    area_ha = zone_areas[zone_type]
                if area_ha is None:
                    for metric_key, metric_val in metrics.items():
                        if zone_type in metric_key and metric_val is not None:
                            try:
                                area_ha = float(metric_val)
                                break
                            except (ValueError, TypeError):
                                continue
                if area_ha is not None:
                    self.g.add((zone, PLN.area_target_ha, Literal(area_ha, datatype=XSD.double)))

    def _add_spatial_relations(self, geojson: Dict[str, Any]):
        """Build parcel adjacency graph from GeoDataFrame spatial joins."""
        try:
            from app.utils.geojson_utils import geojson_to_geodataframe
            gdf = geojson_to_geodataframe(geojson)
            if gdf is None or len(gdf) < 2:
                return

            gdf_proj = project_to_metric(gdf)
            # Spatial join: find parcels within 10m of each other
            gdf_proj["geometry_buffered"] = gdf_proj.geometry.buffer(10)
            joined = gdf_proj.sjoin(
                gdf_proj.set_geometry("geometry_buffered"),
                how="inner",
                predicate="intersects",
            )

            # Add adjacent_to relations for touching parcels
            edge_count = 0
            seen_edges = set()
            for _, row in joined.iterrows():
                bsm_a = str(row.get("BSM_left", "")).strip()
                bsm_b = str(row.get("BSM_right", "")).strip()
                dlbm_a = str(row.get("DLBM_left", "")).strip()
                dlbm_b = str(row.get("DLBM_right", "")).strip()
                if not (bsm_a and bsm_b and dlbm_a and dlbm_b):
                    continue
                ck_a = f"{bsm_a}_{dlbm_a}_{int(row.get('SHAPE_Area_left', 0) or 0)}"
                ck_b = f"{bsm_b}_{dlbm_b}_{int(row.get('SHAPE_Area_right', 0) or 0)}"
                if ck_a == ck_b:
                    continue
                edge_key = tuple(sorted([ck_a, ck_b]))
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                parcel_a = PLN[f"parcel_{ck_a}"]
                parcel_b = PLN[f"parcel_{ck_b}"]
                if (parcel_a, RDF.type, PLN.Parcel) in self.g and \
                   (parcel_b, RDF.type, PLN.Parcel) in self.g:
                    self.g.add((parcel_a, PLN.adjacent_to, parcel_b))
                    edge_count += 1
                if edge_count >= 5000:
                    break

            logger.info(f"[PlanningKG] Added {edge_count} adjacency edges")
        except Exception as e:
            logger.warning(f"[PlanningKG] Spatial relations failed: {e}")

    def query(self, sparql: str) -> List[Dict[str, Any]]:
        """Execute SPARQL query and return results as list of dicts."""
        try:
            results = self.g.query(sparql)
            # Convert results to list of dicts
            rows = []
            for row in results:
                if hasattr(row, 'asdict'):
                    row_dict = {}
                    for k, v in row.asdict().items():
                        row_dict[str(k)] = str(v) if v is not None else None
                    rows.append(row_dict)
                elif isinstance(row, (tuple, list)):
                    row_dict = {}
                    if hasattr(results, 'vars'):
                        for i, var in enumerate(results.vars):
                            if i < len(row):
                                row_dict[str(var)] = str(row[i]) if row[i] is not None else None
                    rows.append(row_dict)
            return rows
        except Exception as e:
            logger.error(f"[PlanningKG] SPARQL query failed: {e}")
            return []

    def get_constraints(self) -> List[Dict[str, Any]]:
        """Get all constraints as a list of dicts."""
        query_str = """
            PREFIX pln: <http://village-planning.org/ontology#>
            SELECT ?id ?field ?op ?value ?source
            WHERE {
                ?c a pln:Constraint ;
                   pln:constraint_id ?id ;
                   pln:field ?field ;
                   pln:operator ?op ;
                   pln:value ?value ;
                   pln:source ?source .
            }
        """
        return self.query(query_str)

    def get_adjacency_map(self) -> Dict[str, set]:
        """Get parcel adjacency map from KG triples.

        SPARQL-queries pln:adjacent_to triples and returns a dict mapping
        each parcel composite key to the set of adjacent parcel composite keys.

        Returns:
            {composite_key: {adjacent_composite_key, ...}}
        """
        adj_map: Dict[str, set] = {}
        for s, _, o in self.g.triples((None, PLN.adjacent_to, None)):
            # Extract composite key from URI: pln:parcel_BSM_DLBM_Area
            key_s = str(s)
            key_o = str(o)
            prefix = str(PLN) + "parcel_"
            if key_s.startswith(prefix) and key_o.startswith(prefix):
                ck_s = key_s[len(prefix):]
                ck_o = key_o[len(prefix):]
                adj_map.setdefault(ck_s, set()).add(ck_o)
                adj_map.setdefault(ck_o, set()).add(ck_s)
        logger.info(f"[PlanningKG] Adjacency map: {len(adj_map)} parcels with neighbors")
        return adj_map

    def get_parcel_count(self) -> int:
        return self._parcel_count

    def get_triple_count(self) -> int:
        return len(self.g)

    def serialize(self, filepath: str, format: str = "turtle"):
        """Save KG to file (for debugging/export)."""
        self.g.serialize(destination=filepath, format=format)
        logger.info(f"[PlanningKG] Saved to {filepath} ({format})")

    def to_turtle(self) -> str:
        """Serialize KG to Turtle string for state persistence."""
        return self.g.serialize(format="turtle")

    @classmethod
    def from_turtle(cls, turtle_str: str, village_name: str = "") -> "PlanningKG":
        """Reconstruct KG from Turtle string."""
        kg = cls(village_name=village_name)
        kg.g.parse(data=turtle_str, format="turtle")
        kg._parcel_count = len(list(kg.g.subjects(RDF.type, PLN.Parcel)))
        kg._constraint_count = len(list(kg.g.subjects(RDF.type, PLN.Constraint)))
        return kg

    # ============================================
    # Phase 1: New entity and relation builders
    # ============================================

    def _add_projects(self, reports: Dict[str, Dict[str, Any]]):
        """Add Project entities from report content.

        Extracts project references from L3 report text using keyword patterns,
        creates Project entities with achieves relations to indicators.
        """
        import re
        project_patterns = [
            (r"实施(.{2,20}项目)", "项目"),
            (r"推进(.{2,20}工程)", "工程"),
            (r"建设(.{2,20}项目)", "建设项目"),
            (r"规划(.{2,15}设施)", "设施规划"),
        ]
        seen_projects = set()
        for dk, report in reports.items():
            content = report.get("content", "")
            if not content:
                continue
            for pattern, suffix in project_patterns:
                for match in re.finditer(pattern, content):
                    name = match.group(1).strip()
                    if len(name) < 4 or name in seen_projects:
                        continue
                    seen_projects.add(name)
                    uri_name = f"project_{len(seen_projects)}"
                    project = PLN[uri_name]
                    self.g.add((project, RDF.type, EntityTypes.Project))
                    self.g.add((project, PLN.name, Literal(name)))
                    self.g.add((project, PLN.source, Literal(dk)))
                    # Link project to village
                    self.g.add((PLN.village, Relations.achieves, project))
        if seen_projects:
            logger.info(f"[PlanningKG] Added {len(seen_projects)} projects")

    def _add_regulations(self):
        """Add Regulation entities from existing constraints.

        Converts high-level constraints into Regulation entities with
        protects relations to the zones they safeguard.
        """
        for reg_name, reg_info in REGULATION_TYPES.items():
            reg = PLN[f"regulation_{reg_name}"]
            self.g.add((reg, RDF.type, EntityTypes.Regulation))
            self.g.add((reg, PLN.name, Literal(reg_name)))

            # Find the zone this regulation protects
            protected_zone_name = reg_info["protects"]
            zone_uri = PLN[f"zone_{protected_zone_name}"]
            if (zone_uri, RDF.type, PLN.Zone) in self.g:
                self.g.add((reg, Relations.protects, zone_uri))

            # Link to relevant constraint via field
            field = reg_info["field"]
            for s in self.g.subjects(PLN.field, Literal(field)):
                if (s, RDF.type, PLN.Constraint) in self.g:
                    self.g.add((reg, Relations.constrained_by, s))

        logger.info(f"[PlanningKG] Added {len(REGULATION_TYPES)} regulations")

    def _add_designated_as_relations(self, landuse_geojson: Dict[str, Any]):
        """Add designated_as relations: parcel → planning zone.

        Uses the MIP allocator's DLBM → planning zone mapping to
        establish the designated_as relationship between each parcel
        and its native planning zone.
        """
        from app.tools.gis._generation.optimizer.mip_allocator import dlbm_to_planning_zone

        count = 0
        for ft in landuse_geojson.get("features", []):
            props = ft.get("properties", {})
            bsm = str(props.get("BSM", "")).strip()
            dlbm = str(props.get("DLBM", "")).strip()
            if not bsm:
                continue
            shape_area = int(props.get("SHAPE_Area", 0) or 0)
            composite_key = f"{bsm}_{dlbm}_{shape_area}"
            parcel = PLN[f"parcel_{composite_key}"]
            if (parcel, RDF.type, PLN.Parcel) not in self.g:
                continue
            zone_name = dlbm_to_planning_zone(dlbm)
            zone = PLN[f"zone_{zone_name}"]
            if (zone, RDF.type, PLN.Zone) in self.g:
                self.g.add((parcel, Relations.designated_as, zone))
                count += 1
        if count > 0:
            logger.info(f"[PlanningKG] Added {count} designated_as relations")

    def _add_spatial_infrastructure(self, landuse_geojson: Dict[str, Any]):
        """Add Facility, Road, WaterBody entities from land use data.

        Classifies parcels by DLBM into infrastructure types and creates
        corresponding entities with serves/connects relations.
        """
        road_dlbms = {"1000", "1001", "1002", "1003", "1004", "1005", "1006", "1040", "2126", "2200"}
        water_dlbms = {"1101", "1102", "1103", "1104", "1105", "1106", "1109", "1110", "1140", "1180", "3100"}
        facility_dlbms = {"0800", "0801", "0802", "0803", "0806", "0810", "0900", "2122", "2125"}

        roads = []
        water_bodies = []
        facilities = []

        for ft in landuse_geojson.get("features", []):
            props = ft.get("properties", {})
            dlbm = str(props.get("DLBM", "")).strip()
            bsm = str(props.get("BSM", "")).strip()
            if not bsm:
                continue
            if dlbm in road_dlbms:
                roads.append((bsm, dlbm, props))
            elif dlbm in water_dlbms:
                water_bodies.append((bsm, dlbm, props))
            elif dlbm in facility_dlbms:
                facilities.append((bsm, dlbm, props))

        # Add Road entities with connects relations
        for i, (bsm, dlbm, props) in enumerate(roads):
            road = PLN[f"road_{bsm}"]
            self.g.add((road, RDF.type, EntityTypes.Road))
            self.g.add((road, PLN.name, Literal(f"道路_{bsm}")))
            self.g.add((road, PLN.dlbm, Literal(dlbm)))
            self.g.add((PLN.village, Relations.connects, road))
            # Road connects to village
            self.g.add((road, Relations.located_in, PLN.village))

        # Add WaterBody entities
        for i, (bsm, dlbm, props) in enumerate(water_bodies):
            water = PLN[f"water_{bsm}"]
            self.g.add((water, RDF.type, EntityTypes.WaterBody))
            self.g.add((water, PLN.name, Literal(f"水域_{bsm}")))
            self.g.add((water, PLN.dlbm, Literal(dlbm)))
            self.g.add((water, Relations.located_in, PLN.village))

        # Add Facility entities with serves relations
        for i, (bsm, dlbm, props) in enumerate(facilities):
            facility = PLN[f"facility_{bsm}"]
            self.g.add((facility, RDF.type, EntityTypes.Facility))
            self.g.add((facility, PLN.name, Literal(f"设施_{bsm}")))
            self.g.add((facility, PLN.dlbm, Literal(dlbm)))
            self.g.add((facility, Relations.located_in, PLN.village))
            # Determine who the facility serves based on DLBM
            if dlbm in ("0801", "0802"):
                self.g.add((facility, Relations.serves, Literal("教育服务")))
            elif dlbm == "0803":
                self.g.add((facility, Relations.serves, Literal("医疗服务")))
            else:
                self.g.add((facility, Relations.serves, Literal("公共服务")))

        total = len(roads) + len(water_bodies) + len(facilities)
        if total > 0:
            logger.info(
                f"[PlanningKG] Added infrastructure: {len(roads)} roads, "
                f"{len(water_bodies)} water bodies, {len(facilities)} facilities"
            )

    def add_annotations(self, annotations: list) -> "PlanningKG":
        """Add Facility + Village entities from typed CurrentAnnotation models.

        annotation.geojson 包含两类要素:
          - 现状设施点: 篮/电/污/祠/站/广/卫/健/停/水/小
          - 村名: 八社村/上举村/符坑村/文贵村

        设施点 → PLN.Facility 实体
        村名 → PLN.Village 实体 (补充 spatial_context 的 natural_villages)
        """
        from app.modules.gis.schema.spatial_types import CurrentFacility

        facility_count = 0
        village_count = 0

        for ann in annotations:
            cat = getattr(ann, "category", "")
            if cat == "村名":
                # Village name anchor
                text = getattr(ann, "text", "")
                if text and hasattr(ann, "geometry"):
                    coords = ann.geometry.get("coordinates", [0, 0])
                    village = PLN[f"village_ann_{text}"]
                    self.g.add((village, RDF.type, PLN.Village))
                    self.g.add((village, PLN.name, Literal(text)))
                    self.g.add((village, PLN.lon, Literal(coords[0], datatype=XSD.double)))
                    self.g.add((village, PLN.lat, Literal(coords[1], datatype=XSD.double)))
                    self.g.add((village, Relations.located_in, PLN.village))
                    village_count += 1
            elif cat == "现状设施点":
                facility = CurrentFacility.from_annotation_feature(
                    {"properties": ann._raw, "geometry": ann.geometry}
                ) if hasattr(ann, "_raw") else None
                if facility is None:
                    continue
                fname = facility.facility_name or "unknown"
                ftype = facility.facility_type or "公共服务"
                uri_name = f"facility_ann_{fname}_{facility_count}"
                fac_uri = PLN[uri_name]
                self.g.add((fac_uri, RDF.type, PLN.Facility))
                self.g.add((fac_uri, PLN.name, Literal(fname)))
                self.g.add((fac_uri, PLN.facility_type, Literal(ftype)))
                if hasattr(facility, "geometry"):
                    coords = facility.geometry.get("coordinates", [0, 0])
                    self.g.add((fac_uri, PLN.lon, Literal(coords[0], datatype=XSD.double)))
                    self.g.add((fac_uri, PLN.lat, Literal(coords[1], datatype=XSD.double)))
                category = getattr(facility, "category", "") or "public_service"
                self.g.add((fac_uri, Relations.serves, Literal(category)))
                self.g.add((fac_uri, Relations.located_in, PLN.village))
                self.g.add((PLN.village, PLN.has_facility, fac_uri))
                facility_count += 1

        if facility_count or village_count:
            logger.info(
                f"[PlanningKG] Added annotations: {facility_count} facilities, "
                f"{village_count} villages"
            )
        return self

    def add_roads(self, roads: list) -> "PlanningKG":
        """Add Road entities from typed CurrentRoad models."""
        count = 0
        for road in roads:
            bsm = getattr(road, "bsm", "")
            if not bsm:
                bsm = f"road_{count}"
            uri_name = f"road_{bsm}"
            road_uri = PLN[uri_name]
            self.g.add((road_uri, RDF.type, PLN.Road))
            self.g.add((road_uri, PLN.name, Literal(f"道路_{bsm}")))
            shape_length = getattr(road, "shape_length", 0.0) or 0.0
            if shape_length:
                self.g.add((road_uri, PLN.length, Literal(shape_length, datatype=XSD.double)))
            road_level = getattr(road, "road_level", "") or "村道"
            self.g.add((road_uri, PLN.road_level, Literal(road_level)))
            self.g.add((road_uri, Relations.located_in, PLN.village))
            self.g.add((PLN.village, Relations.connects, road_uri))
            count += 1

        if count:
            logger.info(f"[PlanningKG] Added {count} roads")
        return self

    def print_summary(self):
        """Print KG statistics."""
        constraints = self.get_constraints()
        print(f"\n=== Planning KG Summary ===")
        print(f"  Parcels: {self._parcel_count}")
        print(f"  Constraints: {len(constraints)}")
        print(f"  Total triples: {len(self.g)}")
        print(f"\n  Constraints:")
        for c in constraints:
            print(f"    {c.get('id','?')}: {c.get('field','?')} {c.get('op','?')} {c.get('value','?')} (from: {c.get('source','?')})")
