"""build_kg / query_kg tools — RDF knowledge graph construction and SPARQL query.

Merges:
  - layout/kg/builder.py  (PlanningKG)
  - layout/kg/query.py    (SPARQL templates)
  - layout/kg/ontology.py (entity/relation types)
  - tools/gis/layout_tools.py (build_knowledge_graph, query_knowledge_graph)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Ontology ──────────────────────────────────────────────────

class EntityTypes:
    VILLAGE = "pln:Village"
    ZONE = "pln:Zone"
    PARCEL = "pln:Parcel"
    FACILITY = "pln:Facility"
    ROAD = "pln:Road"
    CONSTRAINT = "pln:Constraint"


class Relations:
    HAS_ZONE = "pln:hasZone"
    HAS_PARCEL = "pln:hasParcel"
    HAS_FACILITY = "pln:hasFacility"
    ADJACENT_TO = "pln:adjacentTo"
    CONSTRAINS = "pln:constrains"


# ── KG Builder ────────────────────────────────────────────────

class PlanningKG:
    """RDF-based planning knowledge graph for spatial reasoning."""

    def __init__(self, village_name: str = ""):
        self.village_name = village_name
        self._triples: List[tuple] = []
        self._constraints: List[Dict[str, Any]] = []

    def build_from_reports(
        self,
        reports: Dict[str, Dict[str, Any]],
        landuse_geojson: Optional[Dict] = None,
        gis_data: Optional[Dict] = None,
    ) -> None:
        """Build KG from planning dimension reports."""
        self._add_village_triple()

        if landuse_geojson:
            self._add_landuse_triples(landuse_geojson)

        for dim_key, dim_data in reports.items():
            self._add_dimension_triples(dim_key, dim_data)

    def build_from_intent(
        self,
        intent: Dict[str, Any],
        landuse_geojson: Optional[Dict] = None,
        gis_data: Optional[Dict] = None,
    ) -> None:
        """Build KG from parsed intent (preferred path)."""
        self._add_village_triple()

        if landuse_geojson:
            self._add_landuse_triples(landuse_geojson)

        for zone in intent.get("zones", []):
            self._add_zone_triple(zone)

        for constraint in intent.get("constraints", []):
            self._add_constraint_triple(constraint)

    # ── triple builders ──

    def _add_village_triple(self) -> None:
        self._triples.append((
            f"pln:{self.village_name or 'village'}",
            "rdf:type",
            EntityTypes.VILLAGE,
        ))

    def _add_landuse_triples(self, geojson: Dict) -> None:
        features = geojson.get("features", [])
        for feat in features:
            props = feat.get("properties", {})
            dlbm = props.get("DLBM", "")
            area = props.get("DLMJ", props.get("area", 0))
            from app.services.modules.gis.zone_schema import get_zone_type_for_dlbm, dlbm_to_planning_zone
            zt = get_zone_type_for_dlbm(dlbm)
            pz = dlbm_to_planning_zone(dlbm)
            parcel_id = props.get("BSM", str(hash(str(props))))
            self._triples.extend([
                (f"pln:{parcel_id}", "rdf:type", EntityTypes.PARCEL),
                (f"pln:{parcel_id}", "pln:dlbm", dlbm),
                (f"pln:{parcel_id}", "pln:zoneType", zt),
                (f"pln:{parcel_id}", "pln:planningZone", pz),
                (f"pln:{parcel_id}", "pln:area", float(area or 0)),
            ])

    def _add_zone_triple(self, zone: Dict) -> None:
        zid = zone.get("zone_id", "")
        lu = zone.get("land_use", "")
        ratio = zone.get("area_ratio", 0)
        self._triples.extend([
            (f"pln:zone/{zid}", "rdf:type", EntityTypes.ZONE),
            (f"pln:zone/{zid}", "pln:landUse", lu),
            (f"pln:zone/{zid}", "pln:areaRatio", float(ratio)),
        ])

    def _add_constraint_triple(self, constraint: Dict) -> None:
        cid = constraint.get("constraint_id", "")
        ctype = constraint.get("constraint_type", "")
        self._constraints.append({"id": cid, "type": ctype, **constraint})

    def _add_dimension_triples(self, dim_key: str, dim_data: Dict) -> None:
        metrics = dim_data.get("metrics", {})
        for field, value in metrics.items():
            if isinstance(value, (int, float)):
                self._triples.append((
                    f"pln:dim/{dim_key}",
                    f"pln:{field}",
                    float(value),
                ))

    def to_turtle(self) -> str:
        """Serialize KG to Turtle format."""
        lines = ["@prefix pln: <http://planning.org/> .", "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .", ""]
        for s, p, o in self._triples:
            o_str = f'"{o}"' if isinstance(o, str) else str(o)
            p_str = f"<{p}>" if ":" not in str(p) else p
            lines.append(f"<{s}> {p_str} {o_str} .")
        return "\n".join(lines)

    def get_constraints(self) -> List[Dict[str, Any]]:
        return self._constraints

    @property
    def triple_count(self) -> int:
        return len(self._triples)


# ── SPARQL Queries ────────────────────────────────────────────

QUERY_TEMPLATES = {
    "get_constraint_by_field": """
        SELECT ?field ?value WHERE {{
            ?constraint pln:{field_name} ?value .
        }}
    """,
    "get_zones_by_type": """
        SELECT ?zone WHERE {{
            ?zone pln:landUse "{zone_type}" .
        }}
    """,
    "get_parcels_in_zone": """
        SELECT ?parcel WHERE {{
            ?parcel pln:zoneType "{zone_type}" .
        }}
    """,
    "get_area_summary": """
        SELECT ?zone_type (SUM(?area) as ?total)
        WHERE {{
            ?parcel pln:zoneType ?zone_type .
            ?parcel pln:area ?area .
        }} GROUP BY ?zone_type
    """,
}


def query_kg_triples(kg: PlanningKG, template_name: str, **kwargs) -> Dict[str, Any]:
    """Execute a SPARQL-like query against the KG's triple store."""
    template = QUERY_TEMPLATES.get(template_name, "")
    if not template:
        return {"success": False, "error": f"Unknown template: {template_name}"}

    result_triples = []
    for s, p, o in kg._triples:
        result_triples.append({"subject": str(s), "predicate": str(p), "object": str(o)})

    return {
        "success": True,
        "data": {
            "template": template_name,
            "params": kwargs,
            "triples": result_triples[:100],
            "total_triples": len(result_triples),
        },
    }


# ── Helpers ───────────────────────────────────────────────────

def _make_result(success: bool, data: Any = None, error: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": success}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    return payload


def _to_tool_message(result: Dict[str, Any], tool_call_id: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False, default=str),
        tool_call_id=tool_call_id,
    )


# ── Tools ─────────────────────────────────────────────────────

_kg_instance: Optional[PlanningKG] = None


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

    from app.services.modules.gis.kg import PlanningKG as OriginalKG
    landuse_geojson = gis_data.get("landuse_current_geojson") if gis_data else None

    kg = OriginalKG(village_name=village_name)
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
        "messages": [_to_tool_message(_make_result(True, data={
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
            "messages": [_to_tool_message(_make_result(False, error="KG 未构建 — 请先调用 build_knowledge_graph"), tool_call_id)],
        })

    from app.services.modules.gis.kg.query import query_kg
    query_result = query_kg(_kg_instance, template_name, **params)
    result = _make_result(True, data={"template": template_name, "params": params, "results": query_result})
    return Command(update={
        "messages": [_to_tool_message(result, tool_call_id)],
    })
