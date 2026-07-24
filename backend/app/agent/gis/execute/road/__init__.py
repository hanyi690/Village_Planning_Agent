"""Road sub-task - planned road network generation.

Consumes: intent, existing road network (from KG), allocated_geojson
Produces: planned road layer in layout_configs

Status: placeholder. PlannedRoad schema is defined in
app/modules/gis/schema/spatial_types.py but no road generator exists yet.
P2 will implement the generator and wire it into execute/agent._execute_road_node.
"""
