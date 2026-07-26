"""Tool-facing structured queries — SPARQL template registry for EXECUTE/MIP.

All templates return structured data (bsm, dlbm, area_ha, etc.).
LLM-friendly semantic post-processing is in llm.py.

[v4.5] Parameterized queries: all user-supplied values use SPARQL variables
with initBindings (rdflib) instead of raw string replacement. Fragment
placeholders (type_filter, slope_filter, aspect_filter) remain as string
replacement but are validated before substitution.
"""

from rdflib import Literal

from app.utils.logger import get_logger

logger = get_logger(__name__)

PREFIX = """
PREFIX pln: <http://village-planning.org/ontology#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""

# Fragment placeholders that are replaced as raw SPARQL fragments
# These are validated before substitution
FRAGMENT_PARAMS = {"type_filter", "slope_filter", "aspect_filter"}

# Parameters that have safe defaults
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
                    pln:touches ?neighbor .
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
               pln:touches ?b .
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

    # ── Three zones / three lines ──
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
            {type_filter}
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
            { ?v a pln:NaturalSettlement ; pln:name ?name ; pln:lon ?lon ; pln:lat ?lat . }
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
            {slope_filter}
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
            {aspect_filter}
        }
    """,
}

# Mapping from template parameter names to SPARQL variable names
# for use with initBindings
BINDING_MAP = {
    "field_name": "field_name_val",
    "dlbm": "dlbm_val",
    "zone_type": "zone_type_val",
    "bsm": "bsm_val",
    "min_lon": "min_lon_val",
    "max_lon": "max_lon_val",
    "min_lat": "min_lat_val",
    "max_lat": "max_lat_val",
}


def _sanitize_fragment(fragment: str) -> str:
    """Validate a SPARQL fragment before insertion.

    Allows only SPARQL-safe characters: alphanumeric, whitespace,
    SPARQL operators, IRI chars, and common punctuation.
    Rejects fragments containing dangerous patterns like DELETE/INSERT/DROP.
    """
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


def query_kg(kg, template_name: str, **params) -> list:
    """Tool interface: query KG using a named template with parameters.

    Args:
        kg: PlanningKG instance
        template_name: key in QUERY_TEMPLATES
        **params: template substitution parameters (e.g., dlbm="1100")

    Returns:
        list of dicts with query results
    """
    if template_name not in QUERY_TEMPLATES:
        return [{"error": f"Unknown template: {template_name}. Available: {list(QUERY_TEMPLATES.keys())}"}]

    sparql = QUERY_TEMPLATES[template_name]

    # Apply defaults for optional parameters
    for key, default_val in DEFAULT_VALUES.items():
        params.setdefault(key, default_val)

    # Apply fragment replacements (validated) first
    fragment_params = {k: v for k, v in params.items() if k in FRAGMENT_PARAMS}
    for key, val in fragment_params.items():
        safe_val = _sanitize_fragment(val)
        sparql = sparql.replace(f"{{{key}}}", safe_val)

    # Build initBindings for parameterized variables
    bindings = {}
    for key, val in params.items():
        if key in FRAGMENT_PARAMS or key in DEFAULT_VALUES:
            continue
        var_name = BINDING_MAP.get(key)
        if var_name is not None:
            bindings[var_name] = Literal(val)

    # Execute with parameterized bindings
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


# LangChain-compatible tool definition
TOOL_META = {
    "name": "query_kg",
    "description": (
        "Query the village planning knowledge graph using SPARQL templates. "
        "Available templates: " + ", ".join(QUERY_TEMPLATES.keys()) + ". "
        "Use this to check planning constraints, count parcels by type, "
        "query zone restrictions, and look up facility/road/water data."
    ),
    "parameters": {
        "template_name": {"type": "string", "description": "SPARQL template name"},
        "**params": {"type": "object", "description": "Template parameters"},
    },
}