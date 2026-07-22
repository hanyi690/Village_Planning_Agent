"""build_kg / query_kg tools — RDF knowledge graph construction and SPARQL query."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger
from app.tools.helpers import make_result, to_tool_message

logger = get_logger(__name__)

_kg_instance: Any = None


@tool
def build_knowledge_graph(
    reports: Annotated[Dict[str, Dict[str, Any]], InjectedState("reports")],
    gis_data: Annotated[Dict[str, Optional[Dict[str, Any]]], InjectedState("gis_data")],
    village_name: Annotated[str, InjectedState("village_name")],
    intent: Annotated[Optional[Dict[str, Any]], InjectedState("intent")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Build knowledge graph from planning intent + land use data. Call once.

    Data auto-injected from state — no arguments needed.
    """
    global _kg_instance

    from app.modules.kg import PlanningKG

    landuse_geojson = gis_data.get("landuse_current_geojson") if gis_data else None

    kg = PlanningKG(village_name=village_name)
    if intent:
        kg.build_from_intent(intent=intent, landuse_geojson=landuse_geojson, gis_data=gis_data)
    else:
        kg.build_from_reports(reports=reports, landuse_geojson=landuse_geojson, gis_data=gis_data)

    _kg_instance = kg
    turtle = kg.to_turtle()
    constraints = kg.get_constraints()

    return Command(update={
        "kg_turtle": turtle,
        "kg_constraints": constraints,
        "messages": [to_tool_message(make_result(True, data={
            "triple_count": kg.get_triple_count(),
            "constraint_count": len(constraints),
        }), tool_call_id)],
    })


@tool
def query_knowledge_graph(
    template_name: str,
    gis_data: Annotated[Optional[Dict[str, Any]], InjectedState("gis_data")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    **params,
) -> Command:
    """Query the knowledge graph using a SPARQL template.

    Available templates: get_constraint_by_field, get_zones_by_type,
    get_parcels_in_zone, get_area_summary.

    Args:
        template_name: Query template to use.
        **params: Template-specific parameters (e.g. field_name, zone_type).
    """
    global _kg_instance

    if _kg_instance is None:
        return Command(update={
            "messages": [to_tool_message(make_result(False, error="KG not built — call build_knowledge_graph first"), tool_call_id)],
        })

    from app.modules.kg.query import query_kg
    query_result = query_kg(_kg_instance, template_name, **params)
    result = make_result(True, data={"template": template_name, "params": params, "results": query_result})
    return Command(update={
        "messages": [to_tool_message(result, tool_call_id)],
    })
