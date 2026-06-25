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
