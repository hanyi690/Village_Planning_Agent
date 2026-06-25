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

from rdflib import Graph, Namespace, Literal, RDF, URIRef, BNode
from rdflib.namespace import XSD

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Namespaces
PLN = Namespace("http://village-planning.org/ontology#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")

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
    "永久基本农田保护区": {"color": "#FFE4B5", "restrictions": ["禁止非农化", "禁止非粮化"]},
    "村庄建设区": {"color": "#FF6347", "restrictions": ["建设用地规模上限30.5ha"]},
    "生态保护区": {"color": "#2E8B57", "restrictions": ["禁止工业开发", "禁止城镇化"]},
    "一般农地区": {"color": "#98FB98", "restrictions": ["限制大规模非农建设"]},
}


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
    ) -> "PlanningKG":
        """一键构建完整知识图谱。

        Args:
            reports: {dimension_key: {summary: {...}, content: "..."}}
            landuse_geojson: 现状用地图斑 GeoJSON (660 parcels)
            boundary_geojson: 村界 GeoJSON

        Returns:
            self (for chaining)
        """
        self.g = Graph()
        self.g.bind("pln", PLN)
        self._parcel_count = 0
        self._constraint_count = 0

        # 1. Add village entity
        village = PLN.village
        self.g.add((village, RDF.type, PLN.Village))
        self.g.add((village, PLN.name, Literal(self.village_name or "unknown")))

        # 2. Add parcels from GeoJSON
        if landuse_geojson:
            self._add_parcels(landuse_geojson)

        # 3. Add constraints from reports
        self._add_constraints(reports)

        # 4. Add indicators from reports
        self._add_indicators(reports)

        # 5. Add zones from report content
        self._add_zones(reports)

        # 6. Build spatial adjacency
        if landuse_geojson:
            self._add_spatial_relations(landuse_geojson)

        logger.info(
            f"[PlanningKG] Built KG: {self._parcel_count} parcels, "
            f"{self._constraint_count} constraints, "
            f"{len(self.g)} total triples"
        )
        return self

    def _add_parcels(self, geojson: Dict[str, Any]):
        """Add all parcels as PLN:Parcel entities."""
        features = geojson.get("features", [])
        from ..colors import get_zone_type_for_dlbm
        from ..zone_generator import resolve_zone_type_for_dlbm

        for ft in features:
            props = ft.get("properties", {})
            bsm = str(props.get("BSM", ""))
            dlbm = str(props.get("DLBM", "")).strip()
            dlmc = str(props.get("DLMC", "")).strip()
            area = props.get("DLMJ", 0) or props.get("SHAPE_Area", 0)

            if not bsm:
                continue

            parcel = PLN[f"parcel_{bsm}"]
            self.g.add((parcel, RDF.type, PLN.Parcel))
            self.g.add((parcel, PLN.bsm, Literal(bsm)))
            self.g.add((parcel, PLN.dlbm, Literal(dlbm)))
            self.g.add((parcel, PLN.dlmc, Literal(dlmc)))
            self.g.add((parcel, PLN.area_sqm, Literal(area, datatype=XSD.double)))
            self.g.add((parcel, PLN.area_ha, Literal(area / 10000, datatype=XSD.double)))

            # Current zone type (DLBM classification)
            zone_type = resolve_zone_type_for_dlbm(dlbm)
            self.g.add((parcel, PLN.current_zone_type, Literal(zone_type)))

            self._parcel_count += 1

    def _add_constraints(self, reports: Dict[str, Dict[str, Any]]):
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

        # Also parse spatial structure constraints from content
        for dk, report in reports.items():
            content = report.get("content", "")
            if "生态保护红线" in content and "362.02" in content:
                c = PLN.ecological_redline_protection
                self.g.add((c, RDF.type, PLN.Constraint))
                self.g.add((c, PLN.field, Literal("ecological_redline_ha")))
                self.g.add((c, PLN.operator, Literal(">=")))
                self.g.add((c, PLN.value, Literal(362.02, datatype=XSD.double)))
                self.g.add((c, PLN.prohibits, Literal("industrial_development")))
                self.g.add((c, PLN.prohibits, Literal("urbanization")))
                self.g.add((c, PLN.source, Literal(dk)))
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

    def _add_zones(self, reports: Dict[str, Dict[str, Any]]):
        """Add planning zone definitions from report content."""
        for name, props in ZONE_TYPE_PATTERNS.items():
            zone = PLN[f"zone_{name}"]
            self.g.add((zone, RDF.type, PLN.Zone))
            self.g.add((zone, PLN.name, Literal(name)))
            self.g.add((zone, PLN.color, Literal(props["color"])))
            for restriction in props["restrictions"]:
                self.g.add((zone, PLN.restriction, Literal(restriction)))
            self.g.add((PLN.village, PLN.has_zone, zone))

        # Add spatial structure zones from report
        for dk, report in reports.items():
            content = report.get("content", "")
            if "生态农业发展区" in content:
                zone = PLN.zone_eco_agriculture
                self.g.add((zone, RDF.type, PLN.Zone))
                self.g.add((zone, PLN.name, Literal("生态农业发展区")))
                self.g.add((zone, PLN.area_target_ha, Literal(1960.70, datatype=XSD.double)))
            if "生态保育屏障区" in content:
                zone = PLN.zone_eco_barrier
                self.g.add((zone, RDF.type, PLN.Zone))
                self.g.add((zone, PLN.name, Literal("生态保育屏障区")))
                self.g.add((zone, PLN.area_target_ha, Literal(362.02, datatype=XSD.double)))
            if "宜居生活建设区" in content:
                zone = PLN.zone_livable
                self.g.add((zone, RDF.type, PLN.Zone))
                self.g.add((zone, PLN.name, Literal("宜居生活建设区")))
                self.g.add((zone, PLN.area_target_ha, Literal(30.50, datatype=XSD.double)))

    def _add_spatial_relations(self, geojson: Dict[str, Any]):
        """Build parcel adjacency graph from GeoDataFrame spatial joins."""
        try:
            from ...utils.geojson_utils import geojson_to_geodataframe
            gdf = geojson_to_geodataframe(geojson)
            if gdf is None or len(gdf) < 2:
                return

            gdf_proj = gdf.to_crs("EPSG:3857")
            # Spatial join: find parcels within 10m of each other
            gdf_proj["geometry_buffered"] = gdf_proj.geometry.buffer(10)
            joined = gdf_proj.sjoin(
                gdf_proj.set_geometry("geometry_buffered"),
                how="inner",
                predicate="intersects",
            )

            # Add adjacent_to relations for touching parcels
            edge_count = 0
            for _, row in joined.iterrows():
                bsm_a = str(row.get("BSM_left", ""))
                bsm_b = str(row.get("BSM_right", ""))
                if bsm_a and bsm_b and bsm_a != bsm_b:
                    parcel_a = PLN[f"parcel_{bsm_a}"]
                    parcel_b = PLN[f"parcel_{bsm_b}"]
                    self.g.add((parcel_a, PLN.adjacent_to, parcel_b))
                    edge_count += 1
                    if edge_count >= 5000:  # Limit for performance
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
