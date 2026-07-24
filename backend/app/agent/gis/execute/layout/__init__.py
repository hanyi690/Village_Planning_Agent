"""Layout sub-task - zone allocation + function zone generation.

Consumes: intent.zone_targets, kg_constraints, kg_adjacency_map
Produces: allocated_geojson, function zone layer in layout_configs

Wraps (P1): tools/gis/allocate.allocate_zones
            tools/gis/_generation/zone_generator
"""
