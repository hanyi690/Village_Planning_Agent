"""
Spatial Layout Node

Independent node for generating spatial layout GeoJSON from planning text.
Executes after spatial_structure dimension completion.

Reference: GIS Planning Visualization Architecture Refactoring Plan
"""

import json
import re
from typing import Dict, Any, Optional
from ...utils.logger import get_logger
from ...utils.sse_publisher import SSEPublisher
from ...core.llm_factory import create_llm
from ...tools.core.spatial_layout_generator import generate_spatial_layout_from_json
from ...tools.core.planning_schema import VillagePlanningScheme
from ...subgraphs.spatial_layout_prompts import format_parse_prompt

logger = get_logger(__name__)


async def spatial_layout_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Spatial layout generation node.

    Executes after spatial_structure dimension completion:
    1. Extract planning text from state.detailed_plan["spatial_structure"]
    2. Use Flash LLM with JSON mode to parse into VillagePlanningScheme
    3. Call spatial_layout_generator to generate GeoJSON
    4. Send SSE gis_data event to frontend

    Args:
        state: UnifiedPlanningState or dimension state

    Returns:
        Dict with gis_analysis_results update
    """
    logger.info("[spatial_layout_node] Starting spatial layout generation")

    # Step 1: Get spatial_structure dimension output
    detailed_plan = state.get("detailed_plan", {})
    spatial_text = detailed_plan.get("spatial_structure", "")

    if not spatial_text:
        logger.warning("[spatial_layout_node] No spatial_structure content found")
        return {
            "gis_analysis_results": {
                "spatial_layout": {
                    "success": False,
                    "error": "No spatial_structure planning text available"
                }
            }
        }

    # Step 2: Parse planning text using Flash LLM with JSON mode
    try:
        scheme = await _parse_planning_text_to_scheme(
            spatial_text,
            state.get("config", {}),
            state.get("project_name", "")
        )
    except Exception as e:
        logger.error(f"[spatial_layout_node] Text parsing failed: {e}")
        return {
            "gis_analysis_results": {
                "spatial_layout": {
                    "success": False,
                    "error": f"Planning text parsing failed: {str(e)}"
                }
            }
        }

    if scheme is None:
        return {
            "gis_analysis_results": {
                "spatial_layout": {
                    "success": False,
                    "error": "Failed to generate valid planning scheme"
                }
            }
        }

    # Step 3: Get GIS cache data with boundary fallback mechanism
    from ..shared_gis_context import SharedGISContext

    gis_context = SharedGISContext.from_state(state)
    if gis_context is None:
        logger.warning("[spatial_layout_node] Cannot create SharedGISContext, missing village_name")
        return {
            "gis_analysis_results": {
                "spatial_layout": {
                    "success": False,
                    "error": "Missing village configuration"
                }
            }
        }

    # Get boundary using fallback mechanism (user uploaded -> isochrone -> bbox_buffer)
    boundary_geojson = gis_context.get_or_generate_boundary()

    # Get road data from cache or user upload
    road_geojson = gis_context.get_data_by_type("road")

    # Step 4: Generate GeoJSON
    result = generate_spatial_layout_from_json(
        village_boundary=boundary_geojson,
        road_network=road_geojson,
        planning_scheme=scheme,
        fallback_grid=True,
        merge_threshold=0.01
    )

    # Step 5: Send SSE event
    session_id = state.get("session_id", "")
    if result.get("success"):
        data = result.get("data", {})

        # Send gis_data event for frontend map rendering
        SSEPublisher.send_gis_result(
            session_id=session_id,
            dimension_key="spatial_layout",
            dimension_name="空间布局生成",
            summary="规划布局已生成，包含用地分区和公共设施配置",
            layers=data.get("geojson", {}).get("features", []),
            map_options={
                "center": data.get("center", [0, 0])
            },
            analysis_data=data.get("statistics")
        )

        logger.info(f"[spatial_layout_node] Successfully generated {data.get('statistics', {}).get('zone_count', 0)} zones")
    else:
        error_msg = result.get("error", "Unknown error")
        SSEPublisher.send_tool_status(
            session_id=session_id,
            tool_name="spatial_layout_generator",
            status="error",
            error=error_msg
        )
        logger.error(f"[spatial_layout_node] Generation failed: {error_msg}")

    return {
        "gis_analysis_results": {
            "spatial_layout": result
        }
    }


async def _parse_planning_text_to_scheme(
    planning_text: str,
    config: Dict[str, Any],
    village_name: str
) -> Optional[Any]:
    """
    Parse planning text to VillagePlanningScheme using Flash LLM.

    Uses JSON mode for reliable structured output.

    Args:
        planning_text: Spatial structure planning text
        config: Planning configuration
        village_name: Village name

    Returns:
        VillagePlanningScheme instance or None on failure
    """
    # Build prompt
    village_data = config.get("village_data", "")
    total_area = "未知"
    current_land_use = "未知"

    # Try to extract area from village data
    if village_data:
        area_match = re.search(r'面积约?(\d+\.?\d*)(平方公里|km2|公顷|亩)', village_data)
        if area_match:
            value = float(area_match.group(1))
            unit = area_match.group(2)
            if unit == "亩":
                total_area = f"{value / 150:.2f}"  # Convert to km2
            elif unit == "公顷":
                total_area = f"{value / 100:.2f}"  # Convert to km2
            else:
                total_area = f"{value}"

    prompt = format_parse_prompt(
        planning_text=planning_text,
        village_name=village_name,
        total_area=total_area,
        current_land_use=current_land_use
    )

    # Create Flash LLM with JSON mode (use glm-4-flash for fast response)
    flash_llm = create_llm(
        model="glm-4-flash",
        temperature=0.1,  # Low temperature for deterministic output
        max_tokens=2000,
        provider="zhipuai"
    )

    try:
        # Invoke LLM
        response = await flash_llm.ainvoke(prompt)

        # Parse JSON response
        content = response.content
        if isinstance(content, str):
            json_data = json.loads(content)
        else:
            json_data = content

        # Validate with Pydantic
        scheme = VillagePlanningScheme(**json_data)

        # Validate area ratios
        total_ratio = sum(z.area_ratio for z in scheme.zones)
        if abs(total_ratio - 1.0) > 0.05:
            logger.warning(f"[parse_planning_text] Area ratio sum {total_ratio} deviates from 1.0, will adjust during generation")
            # Normalize ratios
            for z in scheme.zones:
                z.area_ratio = z.area_ratio / total_ratio

        logger.info(f"[parse_planning_text] Successfully parsed {len(scheme.zones)} zones, {len(scheme.facilities)} facilities")
        return scheme

    except json.JSONDecodeError as e:
        logger.error(f"[parse_planning_text] JSON decode error: {e}")
        return None
    except Exception as e:
        logger.error(f"[parse_planning_text] Pydantic validation error: {e}")
        return None


def should_trigger_spatial_layout(state: Dict[str, Any]) -> bool:
    """
    Check if spatial_layout_node should be triggered.

    Trigger conditions:
    - spatial_structure dimension has completed
    - detailed_plan contains spatial_structure content

    Args:
        state: Current state

    Returns:
        True if spatial_layout_node should run
    """
    detailed_plan = state.get("detailed_plan", {})
    spatial_text = detailed_plan.get("spatial_structure", "")

    # Check if spatial_structure has content
    if not spatial_text:
        return False

    # Check if spatial_layout has already been generated
    gis_results = state.get("gis_analysis_results", {})
    spatial_layout_result = gis_results.get("spatial_layout", {})

    if spatial_layout_result.get("success"):
        return False  # Already generated

    return True


__all__ = [
    "spatial_layout_node",
    "should_trigger_spatial_layout",
    "_parse_planning_text_to_scheme",
]