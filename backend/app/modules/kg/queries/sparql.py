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

DEPRECATED_TEMPLATES = {
    "get_protected_parcels_detail": "Use get_constraint_coverage() instance method instead",
    "get_three_zones": "Use get_constraint_coverage() instance method instead",
    "get_three_lines": "Use get_constraint_coverage() instance method instead",
    "get_indicators": "PlanningIndicator type removed in v4.6 — no replacement",
}

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

    "get_protected_parcels_detail": PREFIX + """
        SELECT ?bsm ?dlbm ?zone_type ?area_ha ?protection_name ?protection_category
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:dlbm ?dlbm ;
                    pln:current_zone_type ?zone_type ;
                    pln:area_ha ?area_ha ;
                    pln:within_zone ?protection .
            ?protection a pln:ThreeLine ;
                        pln:name ?protection_name .
            OPTIONAL { ?protection pln:source ?protection_category . }
        }
        ORDER BY ?protection_name ?bsm
    """,

    "check_protected_parcels": PREFIX + """
        SELECT (COUNT(?p) as ?count) (SUM(?area) as ?total_area)
        WHERE {
            ?p a pln:Parcel ;
               pln:current_zone_type ?zt ;
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
                    pln:current_zone_type ?zt ;
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
                    pln:current_zone_type ?zone_type .
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
                    pln:current_zone_type ?zone_type .
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
                     pln:current_zone_type ?neighbor_zone_type ;
                     pln:area_ha ?neighbor_area .
        }
    """,

    "get_parcels_near_point": PREFIX + """
        SELECT ?bsm ?dlbm ?zone_type ?area_ha ?lon ?lat
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:dlbm ?dlbm ;
                    pln:current_zone_type ?zone_type ;
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
               pln:current_zone_type ?zone_type ;
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

    # ── Three zones / three lines (DEPRECATED — use get_constraint_coverage) ──
    "get_three_zones": PREFIX + """
        SELECT ?zone_name (COUNT(?p) as ?parcel_count) (SUM(?area) as ?total_area_ha)
        WHERE {
            ?p a pln:Parcel ;
               pln:planning_zone ?zone_name ;
               pln:area_ha ?area .
        }
        GROUP BY ?zone_name
        ORDER BY DESC(?total_area_ha)
    """,

    "get_three_lines": PREFIX + """
        SELECT ?name ?code ?color ?area_target_ha
        WHERE {
            ?line a pln:ThreeLine ;
                  pln:name ?name .
            OPTIONAL { ?line pln:code ?code . }
            OPTIONAL { ?line pln:color ?color . }
            OPTIONAL { ?line pln:area_target_ha ?area_target_ha . }
        }
    """,

    "get_indicators": PREFIX + """
        SELECT ?name ?value ?source
        WHERE {
            ?i a pln:PlanningIndicator ;
               pln:name ?name ;
               pln:value ?value .
            OPTIONAL { ?i pln:source ?source . }
        }
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
        SELECT ?name ?lon ?lat
        WHERE {
            { ?v a pln:Village ; pln:name ?name ; pln:lon ?lon ; pln:lat ?lat . }
            UNION
            { ?v a pln:AdministrativeVillage ; pln:name ?name ; pln:lon ?lon ; pln:lat ?lat . }
            UNION
            { ?v a pln:ResidentialCluster ; pln:name ?name ; pln:lon ?lon ; pln:lat ?lat . }
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

    if template_name in DEPRECATED_TEMPLATES:
        logger.warning("[query_kg] Template '%s' is deprecated: %s",
                       template_name, DEPRECATED_TEMPLATES[template_name])

    sparql = QUERY_TEMPLATES[template_name]

    for key, default_val in DEFAULT_VALUES.items():
        params.setdefault(key, default_val)

    # Backward compat: map old fragment params to new binding keys
    FRAGMENT_TO_BINDING = {
        "type_filter": "facility_type",
        "slope_filter": "slope_class",
        "aspect_filter": "aspect_class",
    }
    for old_key, new_key in FRAGMENT_TO_BINDING.items():
        if old_key in params and new_key not in params:
            logger.warning("[query_kg] Deprecated param '%s' used; migrate to '%s'", old_key, new_key)
            params[new_key] = params[old_key]
            del params[old_key]

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
        "DEPRECATED SPARQL: " + ", ".join(DEPRECATED_TEMPLATES.keys()) + ". "
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


def get_parcels_within_distance_of_entity(self, entity_uri: str, max_distance_m: float) -> List[str]:
    entity = URIRef(entity_uri) if isinstance(entity_uri, str) else entity_uri
    bsms = set()
    for rel in (PLN.nearby, PLN.sfTouches):
        for s, _, _ in self.g.triples((None, rel, entity)):
            for _, _, bsm in self.g.triples((s, PLN.bsm, None)):
                bsms.add(str(bsm))
        for s, _, _ in self.g.triples((entity, rel, None)):
            for _, _, bsm in self.g.triples((s, PLN.bsm, None)):
                bsms.add(str(bsm))
    return list(bsms)


def get_adjacent_parcels_with_length(self, bsm: str) -> List[Tuple[str, float]]:
    results = []
    for s, _, _ in self.g.triples((None, PLN.bsm, Literal(bsm))):
        if (s, RDF.type, EntityTypes.Parcel) not in self.g:
            continue
        for _, _, neighbor in self.g.triples((s, PLN.sfTouches, None)):
            for _, _, nbsm in self.g.triples((neighbor, PLN.bsm, None)):
                length = 0.0
                for _, _, lo in self.g.triples((s, PLN.shared_boundary_length, None)):
                    length = float(lo)
                results.append((str(nbsm), length))
    return results


def get_connected_parcels(self, parcel_uri: str, max_path_length: float = float("inf")) -> List[str]:
    """Return BSMs of parcels connected to parcel_uri via road network (L3)."""
    uri = URIRef(parcel_uri) if isinstance(parcel_uri, str) else parcel_uri
    bsms = set()
    for _, _, neighbor in self.g.triples((uri, PLN.connected_via_road, None)):
        for _, _, bsm in self.g.triples((neighbor, PLN.bsm, None)):
            bsms.add(str(bsm))
    for s, _, _ in self.g.triples((None, PLN.connected_via_road, uri)):
        for _, _, bsm in self.g.triples((s, PLN.bsm, None)):
            bsms.add(str(bsm))
    return list(bsms)


def get_parcels_by_bsm_list(self, bsms: List[str]) -> List[Dict[str, Any]]:
    """Return parcel structural data for a list of BSMs."""
    if not bsms:
        return []
    bsm_filter = " ".join(f'"{b}"' for b in bsms)
    sparql = (
        "PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?dlbm ?area_ha ?zone_type ?vne_code ?planning_zone WHERE {{ "
        f"?p a pln:Parcel ; pln:bsm ?bsm ; pln:dlbm ?dlbm ; "
        f"pln:area_ha ?area_ha ; pln:current_zone_type ?zone_type . "
        f"OPTIONAL {{ ?p pln:vne_code ?vne_code . }} "
        f"OPTIONAL {{ ?p pln:planning_zone ?planning_zone . }} "
        f"FILTER(?bsm IN ({bsm_filter})) }}"
    )
    return self.query(sparql)


def validate_intent(self, intent: Any) -> List[Dict[str, Any]]:
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, FacilityTarget
    if not isinstance(intent, SpatialPlanningIntent):
        return []
    conflicts = []
    for ft in intent.facilities:
        if ft.semantic and ft.semantic.spatial_hint:
            for bsm in self.get_parcels_within_distance_of_entity(ft.semantic.spatial_hint, 500):
                if _is_in_protected_zone(self, bsm):
                    conflicts.append({"description": f"设施 {ft.type} 的候选地块 {bsm} 在保护区内",
                                      "severity": "high", "facility": ft.type, "bsm": bsm})
    return conflicts


def _is_in_protected_zone(self, bsm: str) -> bool:
    """Check if a parcel overlaps any constraint polygon via spatial_ops bridge."""
    if self._constraint_index is None:
        return False
    overlaps = self._constraint_index.parcel_in_constraint(bsm)
    return len(overlaps) > 0


def get_constraint_coverage(self) -> List[Dict[str, Any]]:
    """Get all parcels with constraint polygon overlap info.

    Iterates all parcel BSMs in the KG and checks each against
    the spatial ConstraintIndex.

    Returns:
        List of dicts, each with:
          bsm, dlbm, area_ha, zone_type, planning_zone,
          constraints: List[{constraint_type, overlap_pct, overlap_area_sqm, rule}]
    """
    if self._constraint_index is None:
        logger.debug("get_constraint_coverage: no constraint_index injected")
        return []

    from rdflib import RDF, Namespace
    PLN = Namespace("http://village-planning.org/ontology#")
    all_bsms = list(self.g.subjects(RDF.type, PLN.Parcel))
    if not all_bsms:
        return []

    bsm_cache = {}
    for pu in all_bsms:
        bsm_node = self.g.value(pu, PLN.bsm)
        if bsm_node:
            bsm_cache[str(bsm_node)] = pu

    results = []
    for bsm, pu in bsm_cache.items():
        overlaps = self._constraint_index.parcel_in_constraint(bsm)
        if not overlaps:
            continue
        parcel_info = self.get_parcels_by_bsm_list([bsm])
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
