"""EXPLORE verification — compare L3 text targets vs L4 geometry (post-execute)."""
from __future__ import annotations
from typing import Any, Dict, List


def compare_intent_to_layout(intent: Any, layout_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
    differences: List[Dict[str, Any]] = []
    consistent: Dict[str, Any] = {}

    zone_text = {
        z.land_use: float(z.area_ha)
        for z in (getattr(intent, "zone_targets", None) or [])
        if z.land_use and z.area_ha
    }
    zone_actual: Dict[str, float] = {}
    for cfg in layout_configs:
        if (cfg.get("layerType") or cfg.get("layer_type")) != "custom_planning_zone":
            continue
        data = cfg.get("data") or cfg.get("geojson") or {}
        for f in data.get("features", []):
            p = f.get("properties") or {}
            name = p.get("zone_name") or p.get("category_name_zh")
            if name:
                zone_actual[name] = zone_actual.get(name, 0.0) + float(p.get("area_ha", 0) or 0)
    for name, target in zone_text.items():
        actual = zone_actual.get(name, 0.0)
        if actual > 0 and abs(actual - target) / target > 0.1:
            differences.append({"check": "zone_area", "name": name, "target_ha": target, "actual_ha": actual})
    consistent["zone_actual"] = zone_actual

    projects = list(getattr(intent, "project_targets", None) or [])
    placed = 0
    for cfg in layout_configs:
        if (cfg.get("layerType") or cfg.get("layer_type")) in {"planned_project", "project_point"}:
            placed += len(((cfg.get("data") or cfg.get("geojson") or {}).get("features", [])) or [])
    if projects and placed == 0:
        differences.append({"check": "project_placement", "expected": len(projects), "actual": placed})
    consistent["placed_projects"] = placed

    roads = list(getattr(intent, "road_targets", None) or [])
    road_count = 0
    for cfg in layout_configs:
        if (cfg.get("layerType") or cfg.get("layer_type")) in {"planned_road", "planned_road_candidates"}:
            road_count += len(((cfg.get("data") or cfg.get("geojson") or {}).get("features", [])) or [])
    if roads and road_count == 0:
        differences.append({"check": "road_connectivity", "expected": len(roads), "actual": road_count})
    consistent["road_count"] = road_count

    suggestions = [d["name"] for d in differences if d["check"] == "zone_area"]
    return {
        "consistent_items": consistent,
        "differences": differences,
        "revision_suggestions": suggestions,
    }


async def save_explore_verification(session_id: str, intent: Any, layout_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
    from app.modules.evidence.step_report import save_step_report

    result = compare_intent_to_layout(intent, layout_configs)
    try:
        await save_step_report(
            session_id, "EXPLORE",
            step_name="l3_l4_verification",
            outputs={
                "differences": len(result["differences"]),
                "consistent_items": result["consistent_items"],
            },
            diagnostics={
                "differences": result["differences"],
                "revision_suggestions": result["revision_suggestions"],
            },
        )
    except Exception as e:  # noqa: BLE001 — non-fatal
        import logging
        logging.getLogger(__name__).debug("[EXPLORE-verify] step report failed: %s", e)
    return result
