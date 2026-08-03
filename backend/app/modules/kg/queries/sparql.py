"""SPARQL query layer for PlanningKG - templates + instance methods.

Combines:
  - SPARQL template registry (QUERY_TEMPLATES) + parameterized execution (query_kg)
  - Instance methods mixed into PlanningKG via QueryMixin (need self._constraint_index etc.)

Both are consumed by PARSE / EXECUTE / Tools indiscriminately.
"""
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Literal, RDF, URIRef

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations

logger = get_logger(__name__)


# ============================================================
# SPARQL template registry
# ============================================================

PREFIX = """
PREFIX pln: <http://village-planning.org/ontology#>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""

FRAGMENT_PARAMS: set = set()  # All templates migrated to initBindings

DEFAULT_VALUES = {
    "min_lon": "-180",
    "max_lon": "180",
    "min_lat": "-90",
    "max_lat": "90",
}

QUERY_TEMPLATES = {
    # ── Protection zones ──
    "get_zone_restrictions": PREFIX + """
        SELECT ?zone ?name ?restriction
        WHERE {
            ?zone a pln:Zone ;
                  pln:name ?name ;
                  pln:restriction ?restriction .
        }
    """,

    "check_protected_parcels": PREFIX + """
        SELECT (COUNT(?p) as ?count) (SUM(?area) as ?total_area)
        WHERE {
            ?p a pln:Parcel ;
               pln:zone_type ?zt ;
               pln:area_ha ?area .
            FILTER(?zt IN ("农业用地", "生态绿地"))
        }
    """,

    # ── Parcel queries ──
    "get_parcels_by_dlbm": PREFIX + """
        SELECT ?parcel ?bsm ?dlbm ?dlmc ?area
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:dlbm ?dlbm ;
                    pln:area_ha ?area .
            FILTER(?dlbm = ?dlbm_val)
        }
    """,

    "get_parcels_by_zone_type": PREFIX + """
        SELECT ?parcel ?bsm ?area
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:zone_type ?zt ;
                    pln:area_ha ?area .
            FILTER(?zt = ?zone_type_val)
        }
    """,

    "get_village_parcels": PREFIX + """
        SELECT ?parcel ?bsm ?dlbm ?dlmc ?zone_type ?area_ha ?lon ?lat ?vne_code ?planning_zone
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:dlbm ?dlbm ;
                    pln:area_ha ?area_ha ;
                    pln:zone_type ?zone_type .
            OPTIONAL { ?parcel pln:dlmc ?dlmc . }
            OPTIONAL { ?parcel pln:lon ?lon . }
            OPTIONAL { ?parcel pln:lat ?lat . }
            OPTIONAL { ?parcel pln:vne_code ?vne_code . }
            OPTIONAL { ?parcel pln:planning_zone ?planning_zone . }
        }
        ORDER BY ?bsm
    """,

    "get_parcel_detail": PREFIX + """
        SELECT ?bsm ?dlbm ?dlmc ?zone_type ?area_ha ?lon ?lat ?vne_code ?planning_zone
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm_val ;
                    pln:dlbm ?dlbm ;
                    pln:area_ha ?area_ha ;
                    pln:zone_type ?zone_type .
            OPTIONAL { ?parcel pln:dlmc ?dlmc . }
            OPTIONAL { ?parcel pln:lon ?lon . }
            OPTIONAL { ?parcel pln:lat ?lat . }
            OPTIONAL { ?parcel pln:vne_code ?vne_code . }
            OPTIONAL { ?parcel pln:planning_zone ?planning_zone . }
        }
    """,

    "get_parcel_neighbors": PREFIX + """
        SELECT ?neighbor_bsm ?neighbor_dlbm ?neighbor_zone_type ?neighbor_area
        WHERE {
            ?parcel pln:bsm ?bsm_val ;
                    geo:sfTouches ?neighbor .
            ?neighbor pln:bsm ?neighbor_bsm ;
                     pln:dlbm ?neighbor_dlbm ;
                     pln:zone_type ?neighbor_zone_type ;
                     pln:area_ha ?neighbor_area .
        }
    """,

    "get_parcels_near_point": PREFIX + """
        SELECT ?bsm ?dlbm ?zone_type ?area_ha ?lon ?lat
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:dlbm ?dlbm ;
                    pln:zone_type ?zone_type ;
                    pln:area_ha ?area_ha ;
                    pln:lon ?lon ;
                    pln:lat ?lat .
            FILTER(
                ?lon >= ?min_lon_val && ?lon <= ?max_lon_val &&
                ?lat >= ?min_lat_val && ?lat <= ?max_lat_val
            )
        }
    """,

    "get_designated_zones": PREFIX + """
        SELECT ?parcel ?bsm ?zone_name
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:designated_as ?zone .
            ?zone pln:name ?zone_name .
        }
    """,

    "get_adjacent_parcels": PREFIX + """
        SELECT ?a_bsm ?b_bsm
        WHERE {
            ?a pln:bsm ?a_bsm ;
               geo:sfTouches ?b .
            ?b pln:bsm ?b_bsm .
        }
        LIMIT 100
    """,

    # ── Aggregation queries ──
    "count_by_zone_type": PREFIX + """
        SELECT ?zone_type (COUNT(?p) as ?count) (SUM(?area) as ?total_area)
        WHERE {
            ?p a pln:Parcel ;
               pln:zone_type ?zone_type ;
               pln:area_ha ?area .
        }
        GROUP BY ?zone_type
        ORDER BY DESC(?total_area)
    """,

    "count_by_vne": PREFIX + """
        SELECT ?vne_code (COUNT(?p) as ?parcel_count) (SUM(?area) as ?total_area_ha)
        WHERE {
            ?p a pln:Parcel ;
               pln:vne_code ?vne_code ;
               pln:area_ha ?area .
        }
        GROUP BY ?vne_code
        ORDER BY DESC(?total_area_ha)
    """,

    "count_by_planning_zone": PREFIX + """
        SELECT ?planning_zone (COUNT(?p) as ?parcel_count) (SUM(?area) as ?total_area_ha)
        WHERE {
            ?p a pln:Parcel ;
               pln:planning_zone ?planning_zone ;
               pln:area_ha ?area .
        }
        GROUP BY ?planning_zone
        ORDER BY DESC(?total_area_ha)
    """,

    "count_entity_types": PREFIX + """
        SELECT ?type (COUNT(?entity) as ?count)
        WHERE {
            ?entity a ?type .
        }
        GROUP BY ?type
        ORDER BY DESC(?count)
    """,

    # ── Facilities & infrastructure ──
    "get_facility_locations": PREFIX + """
        SELECT ?facility ?name ?type ?lon ?lat ?serves
        WHERE {
            ?facility a pln:Facility ;
                      pln:name ?name .
            OPTIONAL { ?facility pln:facility_type ?type . }
            OPTIONAL { ?facility pln:lon ?lon . }
            OPTIONAL { ?facility pln:lat ?lat . }
            OPTIONAL { ?facility pln:serves ?serves . }
        }
    """,

    "get_facilities_by_type": PREFIX + """
        SELECT ?facility ?name ?type ?lon ?lat ?serves
        WHERE {
            ?facility a pln:Facility ;
                      pln:name ?name .
            OPTIONAL { ?facility pln:facility_type ?type . }
            OPTIONAL { ?facility pln:lon ?lon . }
            OPTIONAL { ?facility pln:lat ?lat . }
            OPTIONAL { ?facility pln:serves ?serves . }
            FILTER(?type = ?facility_type_val)
        }
    """,

    "get_facility_serve_areas": PREFIX + """
        SELECT ?facility ?name ?serves
        WHERE {
            ?facility a pln:Facility ;
                      pln:name ?name ;
                      pln:serves ?serves .
        }
    """,

    "get_road_network": PREFIX + """
        SELECT ?road ?name ?dlbm ?road_level ?length
        WHERE {
            ?road a pln:Road ;
                  pln:name ?name .
            OPTIONAL { ?road pln:dlbm ?dlbm . }
            OPTIONAL { ?road pln:road_level ?road_level . }
            OPTIONAL { ?road pln:length ?length . }
        }
    """,

    "get_water_bodies": PREFIX + """
        SELECT ?water ?name ?dlbm ?area_ha
        WHERE {
            ?water a pln:WaterBody ;
                   pln:name ?name .
            OPTIONAL { ?water pln:dlbm ?dlbm . }
            OPTIONAL { ?water pln:area_target_ha ?area_ha . }
        }
    """,

    "get_village_anchors": PREFIX + """
        SELECT ?name ?wkt ?kind
        WHERE {
            {
                ?v a pln:Village ; pln:name ?name ; geo:hasCentroid ?cg .
                ?cg geo:asWKT ?wkt . BIND("village" AS ?kind)
            }
            UNION
            {
                ?v a pln:AdministrativeVillage ; pln:name ?name ; geo:hasCentroid ?cg .
                ?cg geo:asWKT ?wkt . BIND("admin_village" AS ?kind)
            }
            UNION
            {
                ?v a pln:ResidentialCluster ; pln:name ?name ; geo:hasCentroid ?cg .
                ?cg geo:asWKT ?wkt . BIND("cluster" AS ?kind)
            }
        }
    """,

    # ── P1: KG 拓扑查询模板（grounding 空间描述解析用）──
    # 基于已验证的 parcel-parcel sfTouches / parcel-road sfIntersects /
    # parcel-water sfTouches 关系（P0 接线后已构建）。

    "get_parcels_touching_bsm": PREFIX + """
        SELECT DISTINCT ?bsm ?dlbm ?zone_type
        WHERE {
            ?neighbor a pln:Parcel ;
                      pln:bsm ?bsm ;
                      geo:sfTouches ?parcel .
            ?parcel pln:bsm ?bsm_val .
            OPTIONAL { ?neighbor pln:dlbm ?dlbm . }
            OPTIONAL { ?neighbor pln:zone_type ?zone_type . }
        }
    """,

    "get_parcels_intersecting_road": PREFIX + """
        SELECT DISTINCT ?bsm ?dlbm ?zone_type ?road_name
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    geo:sfIntersects ?road .
            ?road a pln:Road .
            OPTIONAL { ?parcel pln:dlbm ?dlbm . }
            OPTIONAL { ?parcel pln:zone_type ?zone_type . }
            OPTIONAL { ?road pln:name ?road_name . }
        }
    """,

    "get_parcels_touching_water": PREFIX + """
        SELECT DISTINCT ?bsm ?dlbm ?zone_type ?water_name
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    geo:sfTouches ?water .
            ?water a pln:WaterBody .
            OPTIONAL { ?parcel pln:dlbm ?dlbm . }
            OPTIONAL { ?parcel pln:zone_type ?zone_type . }
            OPTIONAL { ?water pln:name ?water_name . }
        }
    """,

    "get_parcels_touching_constraint": PREFIX + """
        SELECT DISTINCT ?bsm ?dlbm ?zone_type ?constraint_name ?constraint_type
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    geo:sfTouches ?constraint .
            ?constraint a ?constraint_type .
            OPTIONAL { ?parcel pln:dlbm ?dlbm . }
            OPTIONAL { ?parcel pln:zone_type ?zone_type . }
            OPTIONAL { ?constraint pln:name ?constraint_name . }
            FILTER(?constraint_type != pln:Parcel)
        }
    """,

    # ── Terrain ──
    "get_terrain_profile": PREFIX + """
        SELECT ?property ?value
        WHERE {
            pln:village ?prop ?value .
            FILTER(
                STRSTARTS(STR(?prop), STR(pln:slope_)) ||
                STRSTARTS(STR(?prop), STR(pln:suitability_))
            )
        }
    """,

    "get_parcels_by_slope": PREFIX + """
        SELECT ?bsm ?dlbm ?slope_class ?area_ha
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:dlbm ?dlbm ;
                    pln:area_ha ?area_ha ;
                    pln:slope_class ?slope_class .
            FILTER(?slope_class = ?slope_class_val)
        }
    """,

    "get_parcels_by_aspect": PREFIX + """
        SELECT ?bsm ?dlbm ?aspect_class ?area_ha
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:dlbm ?dlbm ;
                    pln:area_ha ?area_ha ;
                    pln:aspect_class ?aspect_class .
            FILTER(?aspect_class = ?aspect_class_val)
        }
    """,
}

BINDING_MAP = {
    "field_name": "field_name_val",
    "dlbm": "dlbm_val",
    "zone_type": "zone_type_val",
    "bsm": "bsm_val",
    "min_lon": "min_lon_val",
    "max_lon": "max_lon_val",
    "min_lat": "min_lat_val",
    "max_lat": "max_lat_val",
    "facility_type": "facility_type_val",
    "slope_class": "slope_class_val",
    "aspect_class": "aspect_class_val",
    "bsm": "bsm_val",
    "cluster_name": "cluster_name_val",
    "road_name": "road_name_val",
    "water_name": "water_name_val",
    "constraint_type": "constraint_type_val",
}


def _sanitize_fragment(fragment: str) -> str:
    """Validate a SPARQL fragment before insertion."""
    blocked = {"DELETE", "INSERT", "DROP", "CLEAR", "LOAD", "CREATE", "UPDATE"}
    fragment_stripped = fragment.strip()
    if not fragment_stripped:
        return ""
    upper = fragment_stripped.upper()
    for keyword in blocked:
        if keyword in upper:
            logger.warning("[query_kg] Blocked dangerous fragment containing %s", keyword)
            return ""
    return fragment_stripped


# ── Semantic query dispatch ──
# Maps template_name -> (semantic_module_function, description)
# When query_kg receives one of these names, it calls the semantic function
# instead of executing SPARQL. Returns human-readable text descriptions.

SEMANTIC_QUERIES: Dict[str, tuple] = {}


def _register_semantic_queries():
    """Lazy-register semantic query dispatch entries.
    
    Called once on first query_kg call to avoid circular imports.
    """
    if SEMANTIC_QUERIES:
        return
    from .semantic import (
        get_parcels_semantic_list,
        get_parcel_detail_semantic,
        get_parcel_neighbors_semantic,
        get_facilities_semantic_list,
        get_road_network_semantic,
        get_designated_zones_semantic,
    )
    SEMANTIC_QUERIES.update({
        "get_village_parcels": (get_parcels_semantic_list, "All parcels with human-readable descriptions"),
        "get_parcel_detail": (get_parcel_detail_semantic, "Single parcel detail with relations as text"),
        "get_parcel_neighbors": (get_parcel_neighbors_semantic, "Neighbors of a parcel with semantic descriptions"),
        "get_facility_locations": (get_facilities_semantic_list, "All facilities as human-readable descriptions"),
        "get_road_network": (get_road_network_semantic, "All roads as human-readable descriptions"),
        "get_designated_zones": (get_designated_zones_semantic, "Designated/constraint zones with human-readable descriptions"),
    })


def query_kg(kg, template_name: str, **params) -> list:
    """Tool interface: query KG using a named template or semantic query.

    Args:
        kg: PlanningKG instance
        template_name: key in QUERY_TEMPLATES or SEMANTIC_QUERIES
        **params: template substitution parameters (e.g., bsm="P001")

    Returns:
        list of dicts with query results (includes "description" key for semantic queries)
    """
    # ── Semantic query dispatch (returns human-readable text) ──
    _register_semantic_queries()
    if template_name in SEMANTIC_QUERIES:
        fn, _ = SEMANTIC_QUERIES[template_name]
        try:
            result = fn(kg, **params)
            logger.info("[query_kg] Semantic query '%s' returned %d items", template_name, len(result) if isinstance(result, list) else 0)
            return result if isinstance(result, list) else [{"error": "unexpected return type", "template": template_name}]
        except Exception as e:
            logger.error("[query_kg] Semantic query '%s' failed: %s", template_name, e)
            return [{"error": f"Semantic query failed: {e}", "template": template_name}]

    # ── SPARQL template dispatch ──
    if template_name not in QUERY_TEMPLATES:
        return [{"error": f"Unknown template: {template_name}. Available: {list(QUERY_TEMPLATES.keys()) + list(SEMANTIC_QUERIES.keys())}"}]

    sparql = QUERY_TEMPLATES[template_name]

    for key, default_val in DEFAULT_VALUES.items():
        params.setdefault(key, default_val)

    bindings = {}
    for key, val in params.items():
        if key in DEFAULT_VALUES:
            continue
        var_name = BINDING_MAP.get(key)
        if var_name is not None:
            bindings[var_name] = Literal(val)

    try:
        results = kg.g.query(sparql, initBindings=bindings if bindings else None)
        rows = []
        for row in results:
            if hasattr(row, 'asdict'):
                rows.append({str(k): str(v) if v is not None else None for k, v in row.asdict().items()})
            elif isinstance(row, (tuple, list)):
                rd = {}
                if hasattr(results, 'vars'):
                    for i, var in enumerate(results.vars):
                        if i < len(row):
                            rd[str(var)] = str(row[i]) if row[i] is not None else None
                rows.append(rd)
        return rows
    except Exception as e:
        logger.error("SPARQL query failed: %s", e)
        return []


TOOL_META = {
    "name": "query_kg",
    "description": (
        "Query the village planning knowledge graph using named templates. "
        "Returns SEMANTIC (human-readable) descriptions for: "
        + ", ".join(SEMANTIC_QUERIES.keys()) + ". "
        "Returns raw SPARQL results for: "
        + ", ".join(QUERY_TEMPLATES.keys()) + ". "
        "SEMANTIC queries return a 'description' field with human-readable text. "
        "PREFER semantic queries when the LLM needs to reason about parcels, "
        "facilities, roads, or designated zones."
    ),
    "parameters": {
        "template_name": {"type": "string",
            "description": f"Template name. Semantic: {list(SEMANTIC_QUERIES.keys())}. SPARQL: {list(QUERY_TEMPLATES.keys())}"},
        "**params": {"type": "object", "description": "Template parameters (e.g. bsm='P001')"},
    },
}


# ============================================================
# Instance methods (mixed into PlanningKG via QueryMixin)
# ============================================================

def query(self, sparql: str) -> List[Dict[str, Any]]:
    try:
        results = self.g.query(sparql)
        rows = []
        for row in results:
            if hasattr(row, 'asdict'):
                rows.append({str(k): str(v) if v is not None else None for k, v in row.asdict().items()})
            elif isinstance(row, (tuple, list)):
                rd = {}
                if hasattr(results, 'vars'):
                    for i, var in enumerate(results.vars):
                        if i < len(row):
                            rd[str(var)] = str(row[i]) if row[i] is not None else None
                rows.append(rd)
        return rows
    except Exception as e:
        logger.error("SPARQL query failed: %s", e)
        return []


def get_adjacency_map(self) -> Dict[str, set]:
    """Adjacency map: BSM -> set of neighbor BSMs."""
    adj: Dict[str, set] = {}
    for s, _, o in self.g.triples((None, PLN.sfTouches, None)):
        bsm_s = None
        bsm_o = None
        for _, _, lit in self.g.triples((s, PLN.bsm, None)):
            bsm_s = str(lit)
        for _, _, lit in self.g.triples((o, PLN.bsm, None)):
            bsm_o = str(lit)
        if bsm_s and bsm_o:
            adj.setdefault(bsm_s, set()).add(bsm_o)
            adj.setdefault(bsm_o, set()).add(bsm_s)
    return adj


def get_parcel_count(self) -> int:
    return self._parcel_count


def get_triple_count(self) -> int:
    return len(self.g)


def serialize(self, filepath: str, fmt: str = "turtle"):
    self.g.serialize(destination=filepath, format=fmt)
    logger.info("Saved to %s (%s)", filepath, fmt)


def to_turtle(self) -> str:
    return self.g.serialize(format="turtle")


def from_turtle(cls, turtle_str: str, village_name: str = "") -> "PlanningKG":
    kg = cls(village_name=village_name)
    kg.g.parse(data=turtle_str, format="turtle")
    kg._parcel_count = len(list(kg.g.subjects(RDF.type, EntityTypes.Parcel)))
    return kg


def get_parcels_within_distance_of_entity(kg, entity_uri: str, max_distance_m: float) -> List[str]:
    entity = URIRef(entity_uri) if isinstance(entity_uri, str) else entity_uri
    bsms = set()
    for rel in (PLN.nearby, PLN.sfTouches):
        for s, _, _ in kg.g.triples((None, rel, entity)):
            for _, _, bsm in kg.g.triples((s, PLN.bsm, None)):
                bsms.add(str(bsm))
        for s, _, _ in kg.g.triples((entity, rel, None)):
            for _, _, bsm in kg.g.triples((s, PLN.bsm, None)):
                bsms.add(str(bsm))
    return list(bsms)


def get_adjacent_parcels_with_length(kg, bsm: str) -> List[Tuple[str, float]]:
    results = []
    for s, _, _ in kg.g.triples((None, PLN.bsm, Literal(bsm))):
        if (s, RDF.type, EntityTypes.Parcel) not in kg.g:
            continue
        for _, _, neighbor in kg.g.triples((s, PLN.sfTouches, None)):
            for _, _, nbsm in kg.g.triples((neighbor, PLN.bsm, None)):
                length = 0.0
                for _, _, lo in kg.g.triples((s, PLN.shared_boundary_length, None)):
                    length = float(lo)
                results.append((str(nbsm), length))
    return results


def get_connected_parcels(kg, parcel_uri: str, max_path_length: float = float("inf")) -> List[str]:
    """Return BSMs of parcels connected to parcel_uri via road network (L3)."""
    uri = URIRef(parcel_uri) if isinstance(parcel_uri, str) else parcel_uri
    bsms = set()
    for _, _, neighbor in kg.g.triples((uri, PLN.connected_via_road, None)):
        for _, _, bsm in kg.g.triples((neighbor, PLN.bsm, None)):
            bsms.add(str(bsm))
    for s, _, _ in kg.g.triples((None, PLN.connected_via_road, uri)):
        for _, _, bsm in kg.g.triples((s, PLN.bsm, None)):
            bsms.add(str(bsm))
    return list(bsms)


def get_parcels_by_bsm_list(kg, bsms: List[str]) -> List[Dict[str, Any]]:
    """Return parcel structural data for a list of BSMs."""
    if not bsms:
        return []
    bsm_filter = " ".join(f'"{b}"' for b in bsms)
    sparql = (
        "PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?dlbm ?area_ha ?zone_type ?vne_code ?planning_zone WHERE {{ "
        f"?p a pln:Parcel ; pln:bsm ?bsm ; pln:dlbm ?dlbm ; "
        f"pln:area_ha ?area_ha ; pln:zone_type ?zone_type . "
        f"OPTIONAL {{ ?p pln:vne_code ?vne_code . }} "
        f"OPTIONAL {{ ?p pln:planning_zone ?planning_zone . }} "
        f"FILTER(?bsm IN ({bsm_filter})) }}"
    )
    return kg.query(sparql)


def validate_intent(kg, intent: Any) -> List[Dict[str, Any]]:
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, FacilityTarget
    if not isinstance(intent, SpatialPlanningIntent):
        return []
    conflicts = []
    for ft in intent.facilities:
        if ft.semantic and ft.semantic.spatial_hint:
            for bsm in get_parcels_within_distance_of_entity(kg, ft.semantic.spatial_hint, 500):
                if _is_in_protected_zone(kg, bsm):
                    conflicts.append({"description": f"设施 {ft.type} 的候选地块 {bsm} 在保护区内",
                                      "severity": "high", "facility": ft.type, "bsm": bsm})
    return conflicts


def _is_in_protected_zone(kg, bsm: str) -> bool:
    """Check if a parcel overlaps any constraint polygon via spatial_ops bridge."""
    if kg._constraint_index is None:
        return False
    overlaps = kg._constraint_index.parcel_in_constraint(bsm)
    return len(overlaps) > 0


def get_constraint_coverage(kg) -> List[Dict[str, Any]]:
    """Get all parcels with constraint polygon overlap info.

    Iterates all parcel BSMs in the KG and checks each against
    the spatial ConstraintIndex.

    Returns:
        List of dicts, each with:
          bsm, dlbm, area_ha, zone_type, planning_zone,
          constraints: List[{constraint_type, overlap_pct, overlap_area_sqm, rule}]
    """
    if kg._constraint_index is None:
        logger.debug("get_constraint_coverage: no constraint_index injected")
        return []

    from rdflib import RDF, Namespace
    PLN = Namespace("http://village-planning.org/ontology#")
    all_bsms = list(kg.g.subjects(RDF.type, PLN.Parcel))
    if not all_bsms:
        return []

    bsm_cache = {}
    for pu in all_bsms:
        bsm_node = kg.g.value(pu, PLN.bsm)
        if bsm_node:
            bsm_cache[str(bsm_node)] = pu

    results = []
    for bsm, pu in bsm_cache.items():
        overlaps = kg._constraint_index.parcel_in_constraint(bsm)
        if not overlaps:
            continue
        parcel_info = get_parcels_by_bsm_list(kg, [bsm])
        info = parcel_info[0] if parcel_info else {}
        results.append({
            "bsm": bsm,
            "dlbm": info.get("dlbm", ""),
            "area_ha": info.get("area_ha", 0),
            "zone_type": info.get("zone_type", ""),
            "planning_zone": info.get("planning_zone", ""),
            "constraints": [
                {
                    "constraint_type": ov.constraint_type,
                    "overlap_pct": ov.overlap_pct,
                    "overlap_area_sqm": ov.overlap_area_sqm,
                    "rule": ov.rule,
                }
                for ov in overlaps
            ],
        })
    return results

# Populate SEMANTIC_QUERIES at import time
_register_semantic_queries()


# ============================================================
# L4 query functions (effective state: L1 + L4 merge)
# ============================================================


def get_effective_land_use(kg, bsm: str, version: str = "current"):
    """Get effective land use: L4 if changed, else L1 fallback."""
    l4 = kg.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?lu WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm "{bsm}" ; '
        f'pln:planning_land_use ?lu ; pln:in_version "{version}" . }}')
    if l4:
        return l4[0].get("lu")
    l1 = kg.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?dlbm WHERE {{ '
        f'?p a pln:Parcel ; pln:bsm "{bsm}" ; pln:dlbm ?dlbm . }}')
    return l1[0].get("dlbm") if l1 else None


def get_effective_area_ha(kg, bsm: str, version: str = "current"):
    """Get effective area: L4 if changed, else L1 fallback."""
    l4 = kg.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?area WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm "{bsm}" ; '
        f'pln:planned_area_ha ?area ; pln:in_version "{version}" . }}')
    if l4:
        try:
            return float(l4[0].get("area", 0))
        except (ValueError, TypeError):
            return None
    l1 = kg.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?area WHERE {{ '
        f'?p a pln:Parcel ; pln:bsm "{bsm}" ; pln:area_ha ?area . }}')
    if l1:
        try:
            return float(l1[0].get("area", 0))
        except (ValueError, TypeError):
            return None
    return None


def get_plan_changes(kg, version: str = "current"):
    """Get all planning changes (delta) for a version."""
    return kg.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?p ?bsm ?lu ?area WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm ?bsm ; '
        f'pln:in_version "{version}" . '
        f'OPTIONAL {{ ?p pln:planning_land_use ?lu . }} '
        f'OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}')


def get_planned_parcels_in_zone(kg, zone_type: str, version: str = "current"):
    return kg.query(
        f"PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?land_use ?area WHERE {{ "
        f"?p a pln:PlannedParcel ; pln:bsm ?bsm ; pln:planning_land_use ?land_use ; "
        f'pln:planning_zone_type "{zone_type}" ; pln:in_version "{version}" . '
        f"OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}"
    )


def check_constraint_violations(kg, version: str = "current"):
    """Check planned parcels against constraint polygons via spatial_ops bridge."""
    violations = []
    if kg._constraint_index is None:
        return violations

    for pp in kg.query(f"PREFIX pln: <http://village-planning.org/ontology#> "
                       f"SELECT ?p ?bsm ?land_use WHERE {{ "
                       f"?p a pln:PlannedParcel ; pln:bsm ?bsm ; "
                       f"pln:planning_land_use ?land_use ; pln:in_version \"{version}\" . }}"):
        bsm = pp.get("bsm", "")
        overlaps = kg._constraint_index.parcel_in_constraint(bsm)
        for ov in overlaps:
            violations.append({
                "bsm": bsm,
                "planned_land_use": pp.get("land_use", ""),
                "protected_zone": ov.constraint_type,
                "rule": ov.rule,
                "overlap_area_sqm": ov.overlap_area_sqm,
                "overlap_pct": ov.overlap_pct,
                "version": version,
            })
    return violations


def compare_versions(kg, version_a: str, version_b: str):
    """Compare two plan versions - returns changes between them."""
    a_map = {p["bsm"]: p for p in kg.query(
        f"PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?land_use ?area WHERE {{ "
        f"?p a pln:PlannedParcel ; pln:in_version \"{version_a}\" ; "
        f"pln:bsm ?bsm . "
        f"OPTIONAL {{ ?p pln:planning_land_use ?land_use . }} "
        f"OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}") if p.get("bsm")}
    b_map = {p["bsm"]: p for p in kg.query(
        f"PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?land_use ?area WHERE {{ "
        f"?p a pln:PlannedParcel ; pln:in_version \"{version_b}\" ; "
        f"pln:bsm ?bsm . "
        f"OPTIONAL {{ ?p pln:planning_land_use ?land_use . }} "
        f"OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}") if p.get("bsm")}
    changed = []
    for bsm, bp in b_map.items():
        if bsm in a_map:
            ap = a_map[bsm]
            if ap.get("land_use", "") != bp.get("land_use", ""):
                changed.append({"bsm": bsm, "from": ap.get("land_use", ""),
                                "to": bp.get("land_use", "")})
        else:
            changed.append({"bsm": bsm, "from": None, "to": bp.get("land_use", "")})
    a_keys = set(a_map.keys())
    b_keys = set(b_map.keys())
    return {"version_a": version_a, "version_b": version_b,
            "changed_parcels": changed,
            "added_parcels": list(b_keys - a_keys),
            "removed_parcels": list(a_keys - b_keys),
            "total_changes": len(changed) + len(b_keys - a_keys) + len(a_keys - b_keys)}
