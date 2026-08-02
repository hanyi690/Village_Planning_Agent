"""Road sub-task - planning-node preparation and gated route generation.

Consumes PARSE RoadTarget objects, KG/Data context, and current GIS layers.
Produces road planning entities/nodes and, when confirmed enough, planned road
candidate layers in layout_configs.
"""

from .generator import execute_road_planning_from_agent_state

__all__ = ["execute_road_planning_from_agent_state"]
