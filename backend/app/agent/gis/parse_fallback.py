"""PARSE-as-fallback: merge missing intent categories without disturbing anchors."""
from __future__ import annotations


def merge_fallback_targets(external, parsed) -> int:
    added = 0
    ext_zones = {z.land_use for z in external.zone_targets if z.land_use}
    for zt in parsed.zone_targets:
        if zt.land_use and zt.land_use not in ext_zones:
            external.zone_targets.append(zt)
            ext_zones.add(zt.land_use)
            added += 1
    ext_fac = {f.type for f in external.facilities if f.type}
    for ft in parsed.facilities:
        if ft.type and ft.type not in ext_fac:
            external.facilities.append(ft)
            ext_fac.add(ft.type)
            added += 1
    ext_road = {r.road_level for r in external.road_targets if r.road_level}
    for rt in parsed.road_targets:
        if rt.road_level and rt.road_level not in ext_road:
            external.road_targets.append(rt)
            ext_road.add(rt.road_level)
    return added
