"""Tool: parse_planning_text — pipeline entry for the PARSE Agent subgraph.

Split from parse_tools.py during Phase C refactor.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.tools import tool

from app.utils.logger import get_logger
from app.tools.helpers import make_result

logger = get_logger(__name__)




@tool
async def parse_planning_text(
    planning_text: str,
    village_name: str = "",
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse planning text via PARSE Agent subgraph.

    This is the pipeline entry point that runs the full PARSE Agent:
      classify_sections -> route_by_section -> extract_* -> validate_and_merge

    Returns structured output with:
      - operation_sequence: List[SpatialOperation] with spatial anchors
      - constraint_set: List[SpatialConstraint] with spatial rules
      - planning_intent: SpatialPlanningIntent with zone targets and facilities

    Args:
        planning_text: Markdown planning report text
        village_name: Target village name
        gis_data: GIS data bundle for spatial context computation

    Returns:
        Dict with operation_sequence, constraint_set, planning_intent.
    """
    try:
        from app.modules.gis.spatial_context import compute_spatial_context

        # Compute spatial context from GIS data
        spatial_context = compute_spatial_context(gis_data or {})

        # Build KG from GIS data for on-demand spatial queries
        # Uses KGManager Layer 1 cache — avoids rebuilding adjacency for same village
        try:
            from app.modules.kg.manager import get_kg_manager
            manager = get_kg_manager()
            landuse_geojson = (gis_data or {}).get("landuse_current_geojson")
            kg, _cache_hit = manager.get_or_build_layer1(village_name, landuse_geojson, gis_data or {})
            logger.info("[parse_planning_text] KG ready: %d triples", kg.get_triple_count())
        except Exception as kg_err:
            logger.warning("[parse_planning_text] KG build skipped: %s", kg_err)

        # Initialize Gazetteer for place name → VillageGroup matching
        try:
            import app.agent.gis.parse.agent as pa
            from app.modules.parsing.gazetteer import PlaceNameResolver
            gazetteer = PlaceNameResolver(spatial_context.natural_villages)
            pa._gazetteer = gazetteer
            logger.info("[parse_planning_text] Gazetteer initialized with %d villages",
                        len(spatial_context.natural_villages))
        except Exception as gz_err:
            logger.warning("[parse_planning_text] Gazetteer init skipped: %s", gz_err)

        # Build and run PARSE Agent subgraph
        from app.agent.gis.parse.agent import build_parse_agent_graph
        from app.agent.gis.parse.state import ParseAgentState, SpatialPlanningIntent

        graph = build_parse_agent_graph()

        input_state = ParseAgentState(
            planning_text=planning_text,
            village_name=village_name,
            spatial_context=spatial_context,
        )

        result = await graph.ainvoke(input_state.model_dump())

        # Extract outputs
        operation_sequence = result.get("operation_sequence", [])
        constraint_set = result.get("constraint_set", [])
        planning_intent = result.get("planning_intent", SpatialPlanningIntent())
        validation_errors = result.get("validation_errors", [])

        logger.info(
            "[parse_planning_text] Parsed: %d operations, %d constraints, %d errors",
            len(operation_sequence),
            len(constraint_set),
            len(validation_errors),
        )

        return make_result(
            success=True,
            data={
                "operation_sequence": operation_sequence,
                "constraint_set": constraint_set,
                "planning_intent": planning_intent,
                "validation_errors": validation_errors,
                "spatial_context_summary": {
                    "parcel_count": spatial_context.parcel_count,
                    "total_area_ha": spatial_context.total_area_ha,
                    "village_count": len(spatial_context.natural_villages),
                    "relation_count": len(spatial_context.spatial_relations),
                },
            },
        )
    except Exception as e:
        logger.error("[parse_planning_text] Failed: %s", e)
        return make_result(success=False, error=str(e))


__all__ = ["parse_planning_text"]
