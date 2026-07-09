"""SPARQL query templates and Tool interface for PlanningKG."""

PREFIX = """
PREFIX pln: <http://village-planning.org/ontology#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""

QUERY_TEMPLATES = {
    "get_constraints": PREFIX + """
        SELECT ?id ?field ?op ?value ?source
        WHERE {
            ?c a pln:Constraint ;
               pln:constraint_id ?id ;
               pln:field ?field ;
               pln:operator ?op ;
               pln:value ?value .
            OPTIONAL { ?c pln:source ?source . }
        }
    """,

    "get_constraint_by_field": PREFIX + """
        SELECT ?id ?field ?op ?value
        WHERE {
            ?c a pln:Constraint ;
               pln:constraint_id ?id ;
               pln:field ?field ;
               pln:operator ?op ;
               pln:value ?value .
            FILTER(CONTAINS(?field, "{field_name}"))
        }
    """,

    "get_parcels_by_dlbm": PREFIX + """
        SELECT ?parcel ?bsm ?dlbm ?dlmc ?area
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:dlbm ?dlbm ;
                    pln:area_ha ?area .
            FILTER(?dlbm = "{dlbm}")
        }
    """,

    "get_parcels_by_zone_type": PREFIX + """
        SELECT ?parcel ?bsm ?area
        WHERE {
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:current_zone_type ?zt ;
                    pln:area_ha ?area .
            FILTER(?zt = "{zone_type}")
        }
    """,

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

    "get_zone_restrictions": PREFIX + """
        SELECT ?zone ?name ?restriction
        WHERE {
            ?zone a pln:Zone ;
                  pln:name ?name ;
                  pln:restriction ?restriction .
        }
    """,

    "get_indicators": PREFIX + """
        SELECT ?name ?value ?source
        WHERE {
            ?i a pln:Indicator ;
               pln:name ?name ;
               pln:value ?value .
            OPTIONAL { ?i pln:source ?source . }
        }
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

    "get_adjacent_parcels": PREFIX + """
        SELECT ?a_bsm ?b_bsm
        WHERE {
            ?a pln:bsm ?a_bsm ;
               pln:adjacent_to ?b .
            ?b pln:bsm ?b_bsm .
        }
        LIMIT 100
    """,

    # --- Phase 1: New query templates ---

    "get_all_projects": PREFIX + """
        SELECT ?project ?name ?source
        WHERE {
            ?project a pln:Project ;
                     pln:name ?name .
            OPTIONAL { ?project pln:source ?source . }
        }
    """,

    "get_project_indicators": PREFIX + """
        SELECT ?project ?project_name ?indicator ?ind_name ?value
        WHERE {
            ?village pln:achieves ?project .
            ?project a pln:Project ;
                     pln:name ?project_name .
            ?indicator a pln:Indicator ;
                       pln:name ?ind_name ;
                       pln:value ?value ;
                       pln:source ?source .
            FILTER(CONTAINS(STR(?source), STR(?project_name)))
        }
    """,

    "get_regulation_impacts": PREFIX + """
        SELECT ?reg ?reg_name ?zone ?zone_name ?constraint ?field ?op ?value
        WHERE {
            ?reg a pln:Regulation ;
                 pln:name ?reg_name .
            OPTIONAL {
                ?reg pln:protects ?zone .
                ?zone pln:name ?zone_name .
            }
            OPTIONAL {
                ?reg pln:constrained_by ?constraint .
                ?constraint pln:field ?field ;
                            pln:operator ?op ;
                            pln:value ?value .
            }
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
        SELECT ?road ?name ?dlbm
        WHERE {
            ?road a pln:Road ;
                  pln:name ?name .
            OPTIONAL { ?road pln:dlbm ?dlbm . }
        }
    """,

    "get_water_bodies": PREFIX + """
        SELECT ?water ?name ?dlbm
        WHERE {
            ?water a pln:WaterBody ;
                   pln:name ?name .
            OPTIONAL { ?water pln:dlbm ?dlbm . }
        }
    """,

    "get_parcels_by_facility": PREFIX + """
        SELECT ?facility ?facility_name ?parcel ?bsm ?area
        WHERE {
            ?facility a pln:Facility ;
                      pln:name ?facility_name ;
                      pln:located_in ?village .
            ?parcel a pln:Parcel ;
                    pln:bsm ?bsm ;
                    pln:area_ha ?area ;
                    pln:located_in ?village .
        }
        LIMIT 50
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

    "count_entity_types": PREFIX + """
        SELECT ?type (COUNT(?entity) as ?count)
        WHERE {
            ?entity a ?type .
        }
        GROUP BY ?type
        ORDER BY DESC(?count)
    """,
}


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
    for key, val in params.items():
        sparql = sparql.replace(f"{{{key}}}", str(val))

    return kg.query(sparql)


# LangChain-compatible tool definition
TOOL_META = {
    "name": "query_kg",
    "description": (
        "Query the village planning knowledge graph using SPARQL templates. "
        "Available templates: " + ", ".join(QUERY_TEMPLATES.keys()) + ". "
        "Use this to check planning constraints (construction caps, farmland minimums, "
        "ecological redlines), count parcels by type, query zone restrictions, and "
        "look up indicator values. "
        "Example: query_kg('get_constraint_by_field', field_name='construction') "
        "to find all construction-related constraints."
    ),
    "parameters": {
        "template_name": {"type": "string", "description": "SPARQL template name"},
        "**params": {"type": "object", "description": "Template parameters (dlbm, zone_type, field_name, etc.)"},
    },
}
