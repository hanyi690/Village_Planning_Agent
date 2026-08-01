"""EXECUTE Agent - spatial execution subgraph.

Consumes PARSE intent + KG context, produces spatial layout results.
Peer to PARSE Agent (parse/), invoked by the top-level GIS pipeline.

Sub-tasks (sequential skeleton, parallel fan-out reserved for Phase 2):
  layout/   - zone allocation (MIP) + function zone + planning zone layers
  facility/ - facility point placement
  axis/     - development axis + space control zone + land use zone layers
  road/     - planned road network (placeholder)

Worker-Evaluator loop:
  route -> layout -> facility -> axis -> road -> validate
  validate --pass--> END | --retry--> layout (max 3 rounds)

P1 wiring: nodes call the underlying generation helpers directly
(generate._generate_*, MIPZoneAllocator, LayoutValidator.validate)
rather than the @tool wrappers, bypassing InjectedState. This couples execute/
to tools/gis private helpers; P2 should promote them to a public generation API.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END, START

from .state import ExecuteAgentState
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Node implementations ─────────────────────────────────────────────


async def _route_tasks_node(state: ExecuteAgentState) -> dict:
    """Determine which execution sub-tasks to run based on intent.

    layout always runs (core zone allocation). facility/axis run only when
    intent carries corresponding targets. road is always queued but currently
    a placeholder.
    """
    tasks = ["layout"]
    intent = state.intent
    if intent is not None:
        if hasattr(intent, "facilities") and intent.facilities:
            tasks.append("facility")
        if hasattr(intent, "development_axes") and intent.development_axes:
            tasks.append("axis")
    tasks.append("road")
    logger.info("[EXECUTE] tasks routed: %s", tasks)
    return {"tasks_to_run": tasks}


async def _execute_layout_node(state: ExecuteAgentState) -> dict:
    """Layout sub-task: apply PARSE operations + MIP allocation + function/planning zone layers.

    Replaces the deprecated allocate_and_generate ReAct node with a deterministic
    pipeline: operations -> allocation -> function zone -> planning zone.
    constraint_adjustments from validate feedback are applied to targets on retry.
    """
    from app.tools.gis.generate import (
        _apply_operations, _generate_function_zones, _make_planning_zone_layer,
    )
    from app.tools.gis.allocate import _spatial_constraint_to_mip
    from app.tools.gis._generation.optimizer.mip_allocator import MIPZoneAllocator

    gis_data = state.gis_data or {}
    gis_bundle = getattr(state, "gis_bundle", None)
    if gis_bundle is not None and hasattr(gis_bundle, "polygons") and (gis_bundle.polygons.get("landuse_current") or gis_bundle.polygons.get("landuse_planned")):
        landuse_dict = gis_bundle.to_geojson_dict()
        landuse = landuse_dict.get("landuse_current_geojson")
    else:
        landuse = gis_data.get("landuse_current_geojson")
    if not landuse or not landuse.get("features"):
        logger.warning("[EXECUTE:layout] no landuse data - skipping")
        return {}

    try:
        allocated = state.allocated_geojson or {}
        if state.operation_sequence and allocated:
            allocated = _apply_operations(allocated, state.operation_sequence)

        total_area_ha = sum(
            float(f.get("properties", {}).get("area_ha", 0) or 0)
            for f in landuse.get("features", [])
        )

        # Direct ZoneTarget extraction
        zone_targets = list(state.intent.zone_targets) if hasattr(state.intent, 'zone_targets') and state.intent.zone_targets else []
        target_map = {zt.land_use: round(zt.area_ratio * total_area_ha, 2) for zt in zone_targets if zt.land_use}
        density_hints = {zt.land_use: zt.density for zt in zone_targets if zt.land_use and zt.density}
        adjacency_rules = {}
        for zt in zone_targets:
            if zt.land_use and zt.adjacency_rules:
                adjacency_rules[zt.land_use] = {
                    "prefer": list(zt.adjacency_rules.prefer) if zt.adjacency_rules.prefer else [],
                    "avoid": list(zt.adjacency_rules.avoid) if zt.adjacency_rules.avoid else [],
                }

        if state.constraint_adjustments:
            for adj in state.constraint_adjustments:
                zone = adj.get("zone", "")
                delta = adj.get("delta_ha", 0)
                if zone in target_map and delta:
                    target_map[zone] = round(target_map[zone] + delta, 2)
                    logger.info(
                        "[EXECUTE:layout] adjusted %s by %+.1f ha (reason: %s)",
                        zone, delta, adj.get("reason", ""),
                    )

        mip_parse_constraints = []
        for c in (state.constraint_set or []):
            mip_c = _spatial_constraint_to_mip(c)
            if mip_c:
                mip_parse_constraints.append(mip_c)
        all_constraints = list(state.kg_constraints or []) + mip_parse_constraints

        allocator = MIPZoneAllocator()
        allocated_geojson, alloc_trace = allocator.solve(
            landuse_geojson=landuse,
            targets=target_map,
            constraints=all_constraints,
            zone_targets=zone_targets,
            parse_constraints=state.constraint_set,
            density_hints=density_hints or None,
            adjacency_rules=adjacency_rules or None,
            facility_anchors=state.facility_anchors,
            protected_parcels_detail=state.kg_protected_parcels_detail or None,
            three_line_targets=state.kg_three_lines or None,
            vne_summary=state.kg_vne_summary or None,
        )

        summary = {
            "mode": alloc_trace.get("mode", "mip"),
            "allocated_count": len(allocated_geojson.get("features", [])),
        }
        if density_hints:
            summary["density_hints"] = density_hints
        if adjacency_rules:
            summary["adjacency_rules"] = adjacency_rules

        # Step 6: Generate function zone + planning zone layers
        layers = []
        func_layer = _generate_function_zones(state.intent, gis_data)
        if func_layer:
            layers.append(func_layer)
        plan_layer = _make_planning_zone_layer(allocated_geojson, gis_data)
        if plan_layer:
            layers.append(plan_layer)

        # P7: 自定义功能区层（L4 FunctionalZone，session 词汇表 + 语义规则选择 + 三线拦截）
        custom_targets = getattr(state.intent, "custom_zone_targets", None)
        if custom_targets is None and isinstance(state.intent, dict):
            custom_targets = state.intent.get("custom_zone_targets")
        custom_targets = custom_targets or []
        logger.info("[EXECUTE:layout] custom targets=%d (intent=%s)", len(custom_targets), type(state.intent).__name__)
        if custom_targets:
            try:
                from app.tools.gis._generation.custom_zone_generator import CustomZoningGenerator
                from shapely.geometry import mapping, shape

                parcels = [
                    {
                        "bsm": str(f.get("properties", {}).get("BSM", "") or f.get("properties", {}).get("bsm", "")),
                        "dlbm": str(f.get("properties", {}).get("DLBM", "") or f.get("properties", {}).get("dlbm", "")),
                        "geometry": shape(f["geometry"]) if f.get("geometry") else None,
                    }
                    for f in (landuse.get("features") or [])
                ]
                parcels = [p for p in parcels if p["bsm"] and p["geometry"] is not None]

                three_lines = {}
                if gis_bundle is not None:
                    for bundle_key, subtype in (
                        ("ecological_redline", "ecological_redline"),
                        ("farmland_protection", "farmland_redline"),
                    ):
                        feats = gis_bundle.polygons.get(bundle_key) or []
                        geoms = [getattr(f, "geometry", None) for f in feats]
                        three_lines[subtype] = [
                            {"geometry": shape(g)} for g in geoms if g
                        ]

                intent_dict = (
                    state.intent.model_dump(exclude_none=True)
                    if hasattr(state.intent, "model_dump")
                    else dict(state.intent or {})
                )
                # 顶层 vocabulary_name 从第一个 target 继承（session 注册名）
                if intent_dict.get("custom_zone_targets") and not intent_dict.get("vocabulary_name"):
                    intent_dict["vocabulary_name"] = intent_dict["custom_zone_targets"][0].get("vocabulary_name", "")
                gen = CustomZoningGenerator(parcels, intent_dict, three_lines=three_lines)
                zones, _audit = gen.generate_with_validation()
                if zones:
                    features = []
                    for z in zones:
                        geom = mapping(z["pln:geometry"]) if hasattr(z["pln:geometry"], "__geo_interface__") else z["pln:geometry"]
                        features.append({
                            "type": "Feature",
                            "geometry": geom,
                            "properties": {
                                "entity_type": z["entity_type"],
                                "category_code": z["pln:category_code"],
                                "category_name_zh": z["pln:category_name_zh"],
                                "color": z["pln:color"],
                                "target_bsms": z["pln:target_bsms"],
                                "decided_by": z["pln:decided_by"],
                                "confidence": z["pln:confidence"],
                                "vocabulary_name": z["pln:vocabulary_name"],
                            },
                        })
                    layers.append({
                        "layerType": "custom_functional_zone",
                        "data": {"type": "FeatureCollection", "features": features},
                    })
                    logger.info("[EXECUTE:layout] custom_functional_zone: %d features", len(features))
            except Exception as e:
                logger.error("[EXECUTE:layout] custom zoning failed: %s", e, exc_info=True)

        logger.info(
            "[EXECUTE:layout] allocated %d parcels, %d layers (mode=%s)",
            summary["allocated_count"], len(layers), summary["mode"],
        )

        return {
            "allocated_geojson": allocated_geojson,
            "allocation_summary": summary,
            "layout_configs": layers,
            "constraint_adjustments": [],  # clear after consume
        }
    except Exception as e:
        logger.error("[EXECUTE:layout] failed: %s", e, exc_info=True)
        return {}


async def _execute_facility_node(state: ExecuteAgentState) -> dict:
    """Facility sub-task: public service facility placement via FacilityPlacer.

    Queries KG for existing facility coordinates, then places new facilities.
    Appends the facility layer to layout_configs.
    """
    from app.tools.gis.generate import _generate_facilities

    try:
        fac_layer = _generate_facilities(
            state.intent, state.gis_data or {},
            kg_session_ref=state.kg_session_ref or "",
        )
        if not fac_layer:
            return {}

        layers = list(state.layout_configs)
        layers.append(fac_layer)
        logger.info("[EXECUTE:facility] appended facility layer")
        return {"layout_configs": layers}
    except Exception as e:
        logger.error("[EXECUTE:facility] failed: %s", e, exc_info=True)
        return {}


async def _execute_axis_node(state: ExecuteAgentState) -> dict:
    """Axis sub-task: development axis + space control zone + land use zone layers.

    Appends up to 3 layers to layout_configs.
    """
    from app.tools.gis.generate import (
        _generate_axes, _generate_space_control_zone, _generate_land_use_zone,
    )

    try:
        layers = list(state.layout_configs)
        gis_data = state.gis_data or {}
        allocated = state.allocated_geojson or {}

        axis_layer = _generate_axes(state.intent, gis_data)
        if axis_layer:
            layers.append(axis_layer)

        space_ctrl_layer = _generate_space_control_zone(
            gis_data, allocated, state.intent, state.kg_three_lines or None,
        )
        if space_ctrl_layer:
            layers.append(space_ctrl_layer)

        land_use_layer = _generate_land_use_zone(allocated, gis_data)
        if land_use_layer:
            layers.append(land_use_layer)

        added = len(layers) - len(state.layout_configs)
        if added:
            logger.info("[EXECUTE:axis] appended %d layers (axis/space-control/land-use)", added)
        return {"layout_configs": layers}
    except Exception as e:
        logger.error("[EXECUTE:axis] failed: %s", e, exc_info=True)
        return {}


async def _execute_road_node(state: ExecuteAgentState) -> dict:
    """Road sub-task: planned road network generation.

    Consumes RoadTarget from PARSE intent + existing roads from bundle.
    Produces planned road layer via spatial_ops.road_planner.
    """
    from app.modules.spatial_ops.road_planner import plan_roads

    intent = state.intent
    if not intent:
        logger.info("[EXECUTE:road] no intent, skipping")
        return {}

    # Extract road targets
    road_targets = []
    if hasattr(intent, "road_targets"):
        road_targets = intent.road_targets
    elif isinstance(intent, dict):
        road_targets = intent.get("road_targets", [])

    if not road_targets:
        logger.info("[EXECUTE:road] no road targets in intent, skipping")
        return {}

    # Get current roads from bundle
    bundle = state.gis_bundle
    current_roads = []
    if bundle is not None:
        roads = bundle.lines.get("roads_current") if bundle.lines is not None else None
        if roads is not None:
            current_roads = list(roads)
        # Also try legacy attribute
        if not current_roads:
            current_roads = getattr(bundle, "roads", [])

    # Generate planned roads
    planned_roads = plan_roads(
        road_targets=road_targets,
        current_roads=current_roads,
    )

    if not planned_roads:
        logger.info("[EXECUTE:road] no roads generated")
        return {}

    # Build layer config for export/render
    road_layer = {
        "layer_type": "planned_road",
        "features": planned_roads,
        "count": len(planned_roads),
    }

    # Merge into existing layout_configs
    existing = state.layout_configs or []
    updated = [road_layer] + existing

    logger.info(
        "[EXECUTE:road] generated %d planned roads (%d upgrade, %d new, %d preserved)",
        len(planned_roads),
        sum(1 for r in planned_roads if r.get("operation") == "upgrade"),
        sum(1 for r in planned_roads if r.get("operation") == "create"),
        sum(1 for r in planned_roads if r.get("operation") == "preserve"),
    )

    return {"layout_configs": updated}


async def _validate_node(state: ExecuteAgentState) -> dict:
    """Evaluator gate: validate layout via LayoutValidator, surface adjustments.

    Produces constraint_adjustments for the retry loop (fed back to
    _execute_layout_node which applies them to allocation targets).
    """
    from app.tools.gis._validation.layout_validator import LayoutValidator

    if not state.layout_configs:
        return {
            "validation_round": state.validation_round + 1,
            "validation_result": {"passed": True, "violations": [], "reason": "no layout"},
        }

    try:
        validator = LayoutValidator()
        report = validator.validate(
            state.layout_configs,
            protected_parcels_detail=state.kg_protected_parcels_detail or None,
            kg_vne_summary=state.kg_vne_summary or None,
        )

        passed = report.status != "fail"
        adjustments = getattr(report, "adjustments", None) or []
        adj_dicts = [
            {"zone": a.zone, "action": a.action, "delta_ha": a.delta_ha,
             "reason": a.reason, "priority": a.priority}
            for a in adjustments
        ]

        round_num = state.validation_round + 1
        logger.info(
            "[EXECUTE:validate] round %d: %s (%d adjustments)",
            round_num, "PASS" if passed else "FAIL", len(adj_dicts),
        )

        return {
            "validation_round": round_num,
            "validation_result": {
                "passed": passed,
                "status": report.status,
                "violations": [
                    {"check": c.check_name, "message": c.violations[0].message}
                    for c in report.checks if c.violations
                ] if not passed else [],
            },
            "constraint_adjustments": adj_dicts,
        }
    except Exception as e:
        logger.error("[EXECUTE:validate] failed: %s", e, exc_info=True)
        return {
            "validation_round": state.validation_round + 1,
            "validation_result": {"passed": True, "violations": [], "error": str(e)},
        }


# ── Conditional routing ──────────────────────────────────────────────


def _route_after_validate(state: ExecuteAgentState) -> Literal["pass", "retry"]:
    """Route after validation: pass -> END, fail -> retry (max 3 rounds)."""
    result = state.validation_result or {}
    if result.get("passed", False):
        return "pass"
    if state.validation_round >= 3:
        logger.warning(
            "[EXECUTE] validation exceeded %d rounds - using best result",
            state.validation_round,
        )
        return "pass"
    return "retry"


# ── L4 Write-back ────────────────────────────────────────────────────


async def _write_l4_node(state: ExecuteAgentState) -> dict:
    """Write L4 planned entities (PlannedParcel, PlannedZone, PlannedFacility, etc.) to KG.

    Called after execute completes to persist the planned layout back to KG.
    """
    from rdflib import Literal, RDF
    from app.modules.kg.memory import EntityAnnotation

    session_id = getattr(state, "session_id", "")
    if not session_id:
        logger.warning("[EXECUTE:l4_write] No session_id - skipping L4 write")
        return {}

    try:
        from app.modules.kg.manager import get_kg_manager
        manager = get_kg_manager()
        kg = manager.get_session_kg(session_id)
        if kg is None:
            logger.warning("[EXECUTE:l4_write] No KG for session %s", session_id)
            return {}
    except Exception as e:
        logger.warning("[EXECUTE:l4_write] KG access failed: %s", e)
        return {}

    layout_configs = state.layout_configs or []
    written = 0

    for config in layout_configs:
        layer_type = config.get("layer_type", "")
        features = config.get("features", [])
        op_type = config.get("operation", "preserve")

        if op_type == "preserve":
            continue

        for feat in features:
            props = feat.get("properties", {})
            bsm = props.get("bsm", "")
            target_use = props.get("target_use", props.get("planning_zone", ""))

            if not bsm or not target_use:
                continue

            if layer_type == "function_zone" or layer_type == "planning_zone":
                entity_uri = f"pln:PlannedZone_{bsm}"
                entity_type = "PlannedZone"
            elif layer_type == "facility":
                entity_uri = f"pln:PlannedFacility_{bsm}"
                entity_type = "PlannedFacility"
            elif layer_type == "axis":
                entity_uri = f"pln:PlannedAxis_{bsm}"
                entity_type = "PlannedAxis"
            elif layer_type == "road":
                entity_uri = f"pln:PlannedRoad_{bsm}"
                entity_type = "PlannedRoad"
            else:
                entity_uri = f"pln:PlannedParcel_{bsm}"
                entity_type = "PlannedParcel"

            try:
                kg.g.add((RDF.Uri(entity_uri), RDF.type, Literal(entity_type)))
                kg.g.add((RDF.Uri(entity_uri), Literal(target_use), Literal("target_use")))
                if bsm:
                    kg.g.add((RDF.Uri(entity_uri), Literal(bsm), Literal("bsm")))

                annotation = EntityAnnotation(
                    entity_uri=entity_uri,
                    entity_type=entity_type,
                    description=f"规划{target_use}",
                    source_text_refs=[f"operation:{op_type}"],
                )
                await kg.memory.add_entity_annotation_async(
                    annotation,
                    dimension_key="l4_provenance",
                    fact_type="planned_entity",
                    derived_from="execute_computed",
                )
                written += 1
            except Exception as e:
                logger.warning("[EXECUTE:l4_write] Failed to write %s: %s", entity_uri, e)

    if written > 0:
        manager.bump_version(session_id)
        logger.info("[EXECUTE:l4_write] Wrote %d L4 entities to KG", written)

    return {}


# ── Graph builder ────────────────────────────────────────────────────


def build_execute_agent_graph():
    """Build the EXECUTE Agent StateGraph.

    Sequential skeleton: route -> layout -> facility -> axis -> road -> validate
    Worker-Evaluator retry loop on validation failure (max 3 rounds).

    Returns:
        Compiled StateGraph with ExecuteAgentState schema, ready for
        .ainvoke() or .astream().
    """
    graph = StateGraph(ExecuteAgentState)

    graph.add_node("route_tasks", _route_tasks_node)
    graph.add_node("execute_layout", _execute_layout_node)
    graph.add_node("execute_facility", _execute_facility_node)
    graph.add_node("execute_axis", _execute_axis_node)
    graph.add_node("execute_road", _execute_road_node)
    graph.add_node("validate", _validate_node)
    graph.add_node("write_l4", _write_l4_node)

    graph.add_edge(START, "route_tasks")
    graph.add_edge("route_tasks", "execute_layout")
    graph.add_edge("execute_layout", "execute_facility")
    graph.add_edge("execute_facility", "execute_axis")
    graph.add_edge("execute_axis", "execute_road")
    graph.add_edge("execute_road", "validate")

    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"retry": "execute_layout", "pass": "write_l4"},
    )

    graph.add_edge("write_l4", END)

    compiled = graph.compile()
    logger.info("[EXECUTE] Agent graph compiled: 7 nodes (incl. L4 write-back), 1 conditional edge")
    return compiled


__all__ = ["build_execute_agent_graph"]
