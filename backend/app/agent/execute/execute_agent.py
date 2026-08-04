"""EXECUTE Agent - spatial execution subgraph.

Migrated from agent/gis/execute/agent.py per docs/architecture/agent-graph.md §5.

Consumes PARSE intent + KG context, produces spatial layout results.
Peer to PARSE Agent (parse/), invoked by the top-level GIS pipeline.

Sub-tasks (sequential skeleton, parallel fan-out reserved for Phase 2):
  layout/   - zone allocation (MIP) + function zone + planning zone layers
  facility/ - facility point placement
  axis/     - development axis + space control zone + land use zone layers
  road/     - planned road network (Stage 0-6 + local deterministic fallback)

Worker-Evaluator loop:
  route -> layout -> facility -> axis -> road -> validate
  validate --pass--> END | --retry--> layout (max 3 rounds)

P1 wiring: nodes call the underlying generation helpers directly
(generate._generate_*, LayoutValidator.validate)
rather than the @tool wrappers, bypassing InjectedState. This couples execute/
to tools/gis private helpers; P2 should promote them to a public generation API.
"""

from __future__ import annotations

import json
from functools import wraps
from typing import Any, Awaitable, Callable, Literal

from langgraph.graph import StateGraph, END, START

from app.agent.execute.execute_state import ExecuteAgentState
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _checkpoint_safe(value: Any) -> Any:
    """Convert NumPy scalar containers to checkpoint-serializable primitives."""
    module_name = type(value).__module__
    if module_name == "numpy" or module_name.startswith("numpy."):
        if hasattr(value, "item"):
            return _checkpoint_safe(value.item())
        if hasattr(value, "tolist"):
            return _checkpoint_safe(value.tolist())
    if isinstance(value, dict):
        return {key: _checkpoint_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_checkpoint_safe(item) for item in value]
    return value


def _checkpoint_safe_node(
    node: Callable[[ExecuteAgentState], Awaitable[dict]],
) -> Callable[[ExecuteAgentState], Awaitable[dict]]:
    @wraps(node)
    async def wrapped(state: ExecuteAgentState) -> dict:
        return _checkpoint_safe(await node(state))

    return wrapped


def _execution_error(
    state: ExecuteAgentState,
    stage: str,
    code: str,
    message: str,
) -> dict:
    issue = {"stage": stage, "code": code, "message": message}
    existing = list(state.execution_errors or [])
    if not any(
        item.get("stage") == stage and item.get("code") == code
        for item in existing
    ):
        existing.append(issue)
    return {"execution_errors": existing}


# ── Node implementations ─────────────────────────────────────────────


async def _route_tasks_node(state: ExecuteAgentState) -> dict:
    """Determine which execution sub-tasks to run based on intent.

    Layout is the core allocation task. Facility, axis, and road tasks are
    routed only when the typed or legacy intent declares corresponding targets.
    """
    import os

    tasks = ["layout"]
    defer_road = os.getenv("GIS_DEFER_ROAD", "").strip().lower() in {"1", "true", "yes"}
    intent = state.intent
    if intent is not None:
        if isinstance(intent, dict):
            projects = intent.get("project_targets")
            facilities = intent.get("facilities")
            development_axes = intent.get("development_axes")
            road_targets = intent.get("road_targets")
        else:
            projects = getattr(intent, "project_targets", None)
            facilities = getattr(intent, "facilities", None)
            development_axes = getattr(intent, "development_axes", None)
            road_targets = getattr(intent, "road_targets", None)
        if projects:
            tasks.append("project")
        if facilities:
            tasks.append("facility")
        if development_axes:
            tasks.append("axis")
        if road_targets and not defer_road:
            tasks.append("road")
        elif road_targets and defer_road:
            logger.warning("[EXECUTE] road task deferred by GIS_DEFER_ROAD")
    logger.info("[EXECUTE] tasks routed: %s", tasks)
    result = {"tasks_to_run": tasks}
    session_id = getattr(state, "session_id", "")
    if session_id and intent is not None:
        try:
            from rdflib import RDF
            from app.modules.kg.manager import get_kg_manager
            from app.modules.kg.ontology import EntityTypes

            kg = get_kg_manager().get_session_kg(session_id)
            if kg is None:
                return _execution_error(
                    state,
                    "route",
                    "missing_session_kg",
                    "Session KG is required before EXECUTE.",
                ) | result
            expected = {
                EntityTypes.ProjectTarget: len(getattr(intent, "project_targets", None) or []),
                EntityTypes.ZoneTarget: len(getattr(intent, "zone_targets", None) or []),
                EntityTypes.FacilityTarget: len(getattr(intent, "facilities", None) or []),
                EntityTypes.AxisTarget: len(getattr(intent, "development_axes", None) or []),
                EntityTypes.RoadTarget: len(getattr(intent, "road_targets", None) or []),
            }
            mismatches = []
            for entity_type, expected_count in expected.items():
                actual_count = len(set(kg.g.subjects(RDF.type, entity_type)))
                if actual_count != expected_count:
                    mismatches.append(
                        f"{entity_type.split('/')[-1]} state={expected_count} kg={actual_count}"
                    )
            if mismatches:
                return _execution_error(
                    state,
                    "route",
                    "kg_l3_intent_mismatch",
                    "L3 intent mismatch: " + "; ".join(mismatches),
                ) | result
        except Exception as e:
            return _execution_error(
                state,
                "route",
                "kg_l3_validation_failed",
                str(e),
            ) | result
    return result


def _project_output(state: ExecuteAgentState, features: list, unresolved: list) -> dict:
    """Build the standard planned_project layer output for _execute_project_node."""
    if not features:
        result = _execution_error(
            state,
            "project",
            "project_output_empty",
            "Project targets exist but none could be placed on a constraint-safe candidate parcel.",
        )
        result["unresolved_targets"] = list(state.unresolved_targets or []) + unresolved
        return result
    layers = list(state.layout_configs)
    layers.append({
        "layerType": "planned_project",
        "layerName": "规划项目",
        "data": {"type": "FeatureCollection", "features": features},
    })
    result = {"layout_configs": layers}
    if unresolved:
        result["unresolved_targets"] = list(state.unresolved_targets or []) + unresolved
    return result


def _parcel_from_feature(feature: dict) -> Any:
    """Adapt a landuse GeoJSON feature into the Land Design Worker parcel shape.

    The worker reads .bsm/.geometry/.dlbm/.area_sqm from each parcel entry.
    """
    from types import SimpleNamespace

    props = feature.get("properties") or {}
    return SimpleNamespace(
        bsm=str(props.get("BSM") or props.get("bsm") or ""),
        geometry=feature.get("geometry"),
        dlbm=str(props.get("DLBM") or props.get("dlbm") or ""),
        area_sqm=float(props.get("area_sqm") or props.get("area") or 0),
        area_ha=float(props.get("area_ha") or 0),
    )


def _polygon_footprint(change: Any, source_feature: dict) -> dict:
    """Polygon footprint for a planned_project feature.

    Prefer the change's after geometry (WKT -> GeoJSON); fall back to the
    source parcel geometry when the WKT is empty or invalid.
    """
    from shapely import wkt
    from shapely.geometry import mapping as geometry_mapping

    after_wkt = getattr(change, "after_geometry_wkt", "") or ""
    if after_wkt:
        try:
            geom = wkt.loads(after_wkt)
            if not geom.is_empty:
                return geometry_mapping(geom)
        except Exception:
            pass
    source_geometry = (source_feature or {}).get("geometry")
    return source_geometry or {}


def _project_features_from_selection(
    state: ExecuteAgentState,
    projects: list,
    by_bsm: dict,
    selected: list,
) -> tuple:
    """Primary SELECT path: place projects on the SSD-selected parcels.

    ``selected_combination`` is an ordered BSM list (one per placed project).
    Each selected parcel is run through the Land Design Worker to produce a
    ``ParcelChange`` (accumulated on ``state.parcel_changes``) and a Polygon
    footprint feature for the planned_project layer.
    """
    from app.agent.execute.land_design_worker import design_project_parcel

    projects_by_id = {
        getattr(project, "project_id", ""): project for project in projects
    }
    briefs = list(state.land_design_briefs or [])
    parcel_by_bsm = {
        bsm: _parcel_from_feature(feature) for bsm, feature in by_bsm.items()
    }
    features = []
    for index, bsm in enumerate(selected):
        feature = by_bsm.get(str(bsm))
        if not feature or not feature.get("geometry"):
            continue
        project = None
        brief = briefs[index] if index < len(briefs) else None
        if brief is not None:
            project = projects_by_id.get(getattr(brief, "project_ref", ""))
        worker_brief = brief if project is not None else None
        change = design_project_parcel(project, worker_brief, str(bsm), parcel_by_bsm)
        if change is None:
            continue
        state.parcel_changes.append(change)
        project_id = ""
        if project is not None:
            project_id = getattr(project, "project_id", "")
        elif brief is not None:
            project_id = getattr(brief, "project_ref", "")
        props = {
            "project_id": project_id,
            "project_name": getattr(project, "name", ""),
            "project_category": getattr(project, "category", "other"),
            "action": getattr(project, "action", "new"),
            "scale_text": getattr(project, "scale_text", ""),
            "source_bsm": str(bsm),
            "source_instruction_id": getattr(project, "source_instruction_id", ""),
            "source_report_key": getattr(project, "source_report_key", ""),
            "candidate_bsms": list(getattr(project, "candidate_bsms", None) or []),
            "constraint_check": "passed",
            "geometry_source": "land_design_worker",
            "change_action": change.action,
        }
        if brief is not None:
            props["project_ref"] = getattr(brief, "project_ref", "")
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": _polygon_footprint(change, feature),
        })
    return features, []


async def _execute_project_node(state: ExecuteAgentState) -> dict:
    """Place each L3 project on the SELECT-selected parcel via the Land Design Worker.

    Primary path: consume ``SiteSelectionDecision.selected_combination`` from
    the SELECT subgraph (ordered BSM list), pairing with land design briefs,
    and accumulate ``ParcelChange`` entries into ``state.parcel_changes``. The
    planned_project layer features carry the parcel's Polygon footprint.
    """
    from app.agent.execute.land_design_worker import build_parcel_change_set

    if "project" not in state.tasks_to_run:
        return {}

    projects = list(getattr(state.intent, "project_targets", None) or [])
    landuse = (state.gis_data or {}).get("landuse_current_geojson") or {}
    by_bsm = {
        str((feature.get("properties") or {}).get("BSM")
            or (feature.get("properties") or {}).get("bsm")
            or ""): feature
        for feature in landuse.get("features") or []
    }
    selected = []
    if state.site_selection is not None:
        selected = list(getattr(state.site_selection, "selected_combination", None) or [])
    if not selected:
        logger.warning("[EXECUTE:project] SELECT not wired; project node produces no output")
        return {}

    features, unresolved = _project_features_from_selection(
        state, projects, by_bsm, selected
    )
    if state.parcel_changes:
        state.parcel_changeset = build_parcel_change_set(list(state.parcel_changes))
    return _project_output(state, features, unresolved)


def _function_zone_layer(zone_changes: list) -> dict | None:
    """Build the function_zone layer from reclassified ParcelChange entries."""
    from shapely import wkt
    from shapely.geometry import mapping as geometry_mapping

    features = []
    for change in zone_changes:
        if getattr(change, "action", "") != "reclassify":
            continue
        geometry = {}
        after_wkt = getattr(change, "after_geometry_wkt", "") or ""
        if after_wkt:
            try:
                geom = wkt.loads(after_wkt)
                if not geom.is_empty:
                    geometry = geometry_mapping(geom)
            except Exception:
                geometry = {}
        if not geometry:
            continue
        cls = getattr(change, "after_classification", None)
        bsm = str(getattr(change, "bsm", ""))
        features.append({
            "type": "Feature",
            "properties": {
                "bsm": bsm,
                "planning_land_use": str(getattr(cls, "code", "") or ""),
                "zone_type": str(getattr(cls, "canonical_name", "") or ""),
                "action": getattr(change, "action", ""),
                "source_bsm": bsm,
                "area_ha": round(float(getattr(change, "new_area_ha", 0) or 0), 2),
            },
            "geometry": geometry,
        })
    if not features:
        return None
    return {
        "layerType": "function_zone",
        "layerName": "功能分区",
        "data": {"type": "FeatureCollection", "features": features},
    }


def _allocated_geojson_from_changes(landuse: dict, zone_changes: list) -> dict:
    """landuse features with reclassified parcels tagged with their planning land use."""
    assigned = {}
    for change in zone_changes:
        if getattr(change, "action", "") != "reclassify":
            continue
        cls = getattr(change, "after_classification", None)
        assigned[str(getattr(change, "bsm", ""))] = {
            "planning_land_use": str(getattr(cls, "code", "") or ""),
            "zone_type": str(getattr(cls, "canonical_name", "") or ""),
        }
    features = []
    for feature in landuse.get("features") or []:
        props = dict(feature.get("properties") or {})
        bsm = str(props.get("BSM") or props.get("bsm") or "")
        if bsm in assigned:
            props["planning_land_use"] = assigned[bsm]["planning_land_use"]
            props["zone_type"] = assigned[bsm]["zone_type"]
        new_feature = dict(feature)
        new_feature["properties"] = props
        features.append(new_feature)
    return {"type": "FeatureCollection", "features": features}


def _assign_custom_zone_features(landuse: dict, candidates: dict, pending_zone_name: str) -> dict:
    """Tag every landuse feature with its custom zone (pending for unclaimed parcels)."""
    bsm_to_zone = {}
    for zone_name, bsms in (candidates or {}).items():
        for bsm in bsms:
            bsm_to_zone[str(bsm)] = zone_name
    features = []
    for feature in landuse.get("features") or []:
        props = dict(feature.get("properties") or {})
        bsm = str(props.get("BSM") or props.get("bsm") or "")
        props["assigned_zone"] = bsm_to_zone.get(bsm, pending_zone_name)
        new_feature = dict(feature)
        new_feature["properties"] = props
        features.append(new_feature)
    return {"type": "FeatureCollection", "features": features}


def _build_custom_planning_layer(
    state: ExecuteAgentState,
    landuse: dict,
    custom_targets: list,
) -> dict | None:
    """Build the custom_planning_zone layer via the vocabulary-driven generator (no MIP)."""
    from app.modules.spatial_ops.custom_planning import (
        PENDING_ZONE_NAME,
        build_custom_planning_zone_layer,
        build_custom_zone_allocation_inputs,
    )
    from app.tools.gis._generation.custom_zone_generator import CustomZoningGenerator
    from shapely.geometry import shape

    gis_bundle = getattr(state, "gis_bundle", None)
    parcels = [
        {
            "bsm": str(f.get("properties", {}).get("BSM", "") or f.get("properties", {}).get("bsm", "")),
            "dlbm": str(f.get("properties", {}).get("DLBM", "") or f.get("properties", {}).get("dlbm", "")),
            "area_ha": float(f.get("properties", {}).get("area_sqm", 0) or 0) / 10000.0,
            "geometry": shape(f["geometry"]) if f.get("geometry") else None,
        }
        for f in (landuse.get("features") or [])
    ]
    parcels = [p for p in parcels if p["bsm"] and p["geometry"] is not None]

    try:
        from app.agent.execute.vocab_context import build_parcel_contexts

        ctxs = build_parcel_contexts(parcels, gis_bundle)
        for p in parcels:
            p.update(ctxs.get(str(p["bsm"]), {}))
    except Exception as e:
        logger.warning("[EXECUTE:layout] parcel context build failed: %s", e)

    three_lines = {}
    if gis_bundle is not None:
        for bundle_key, subtype in (
            ("ecological_redline", "ecological_redline"),
            ("farmland_protection", "farmland_redline"),
        ):
            geoms = [
                getattr(f, "geometry", None)
                for f in (gis_bundle.polygons.get(bundle_key) or [])
            ]
            three_lines[subtype] = [{"geometry": shape(g)} for g in geoms if g]
    for gis_key, subtype in (
        ("ecological_protection_geojson", "ecological_redline"),
        ("farmland_protection_geojson", "farmland_redline"),
    ):
        if three_lines.get(subtype):
            continue
        source = (state.gis_data or {}).get(gis_key) or {}
        three_lines[subtype] = [
            {"geometry": shape(feature["geometry"])}
            for feature in source.get("features") or []
            if feature.get("geometry")
        ]

    intent_dict = (
        state.intent.model_dump(exclude_none=True)
        if hasattr(state.intent, "model_dump")
        else dict(state.intent or {})
    )
    if intent_dict.get("custom_zone_targets") and not intent_dict.get("vocabulary_name"):
        intent_dict["vocabulary_name"] = intent_dict["custom_zone_targets"][0].get("vocabulary_name", "")
    if not intent_dict.get("vocabulary_name"):
        logger.warning("[EXECUTE:layout] custom targets present but no vocabulary_name - skipping custom layer")
        return None

    gen = CustomZoningGenerator(parcels, intent_dict, three_lines=three_lines)
    zones, _audit = gen.generate_with_validation()
    if not zones:
        return None
    _targets, candidates, metadata = build_custom_zone_allocation_inputs(landuse, zones)
    custom_allocated = _assign_custom_zone_features(landuse, candidates, PENDING_ZONE_NAME)
    custom_layer = build_custom_planning_zone_layer(custom_allocated, metadata)
    if not custom_layer.get("features"):
        return None
    return {
        "layerType": "custom_planning_zone",
        "layerName": "自定义规划分区",
        "data": custom_layer,
    }


async def _execute_layout_node(state: ExecuteAgentState) -> dict:
    """Layout sub-task: deterministic zone reclassification (no MIP).

    Reclassifies each zone target's candidate parcels to the zone's planning
    land use via the Land Design Worker, building function_zone /
    custom_planning_zone layers and accumulating ParcelChange entries on state.
    """
    from app.agent.execute.land_design_worker import (
        build_parcel_change_set,
        design_zone_parcel,
    )

    if state.tasks_to_run and "layout" not in state.tasks_to_run:
        return {}

    gis_data = state.gis_data or {}
    gis_bundle = getattr(state, "gis_bundle", None)
    if gis_bundle is not None and hasattr(gis_bundle, "polygons") and (
        gis_bundle.polygons.get("landuse_current")
        or gis_bundle.polygons.get("landuse_planned")
    ):
        landuse = gis_bundle.to_geojson_dict().get("landuse_current_geojson")
    else:
        landuse = gis_data.get("landuse_current_geojson")
    if not landuse or not landuse.get("features"):
        logger.warning("[EXECUTE:layout] no landuse data - skipping")
        return _execution_error(
            state,
            "layout",
            "missing_landuse",
            "Current land-use polygons are required for layout execution.",
        )

    zone_targets = getattr(state.intent, "zone_targets", None)
    if zone_targets is None and isinstance(state.intent, dict):
        zone_targets = state.intent.get("zone_targets")
    zone_targets = list(zone_targets or [])

    custom_targets = getattr(state.intent, "custom_zone_targets", None)
    if custom_targets is None and isinstance(state.intent, dict):
        custom_targets = state.intent.get("custom_zone_targets")
    custom_targets = list(custom_targets or [])

    if not zone_targets and not custom_targets:
        message = "No explicit planning zone targets were derived from the reports."
        logger.error("[EXECUTE:layout] %s", message)
        return _execution_error(
            state,
            "layout",
            "missing_zone_targets",
            message,
        )

    parcel_by_bsm = {
        str((feature.get("properties") or {}).get("BSM")
            or (feature.get("properties") or {}).get("bsm") or ""): _parcel_from_feature(feature)
        for feature in (landuse.get("features") or [])
    }

    zone_changes = []
    for zone_target in zone_targets:
        if not getattr(zone_target, "candidate_bsms", None):
            continue
        zone_changes.extend(design_zone_parcel(zone_target, parcel_by_bsm))
    state.parcel_changes.extend(zone_changes)
    if state.parcel_changes:
        state.parcel_changeset = build_parcel_change_set(list(state.parcel_changes))

    layers = []
    func_layer = _function_zone_layer(zone_changes)
    if func_layer:
        layers.append(func_layer)

    summary = {
        "mode": "deterministic",
        "allocated_count": len(zone_changes),
        "zone_target_count": len(zone_targets),
    }

    allocated_geojson = _allocated_geojson_from_changes(landuse, zone_changes)

    if custom_targets:
        try:
            custom_layer = _build_custom_planning_layer(state, landuse, custom_targets)
            if custom_layer:
                layers.append(custom_layer)
                summary["custom_zone_count"] = len(
                    (custom_layer.get("data") or {}).get("features") or []
                )
        except Exception as e:
            logger.error("[EXECUTE:layout] custom zoning failed: %s", e, exc_info=True)

    logger.info(
        "[EXECUTE:layout] reclassified %d parcels, %d layers",
        len(zone_changes), len(layers),
    )

    return {
        "allocated_geojson": allocated_geojson,
        "allocation_summary": summary,
        "layout_configs": layers,
        "constraint_adjustments": [],
    }


async def _execute_facility_node(state: ExecuteAgentState) -> dict:
    """Facility sub-task: decision-driven facility footprint placement.

    Builds a Polygon footprint for each FacilityTarget anchor via the Land
    Design Worker and accumulates ParcelChange entries onto state. No KG POI
    lookup, no FacilityPlacer, no constraint-index filtering.
    """
    if "facility" not in state.tasks_to_run:
        return {}

    try:
        from shapely import wkt
        from shapely.geometry import mapping as geometry_mapping

        from app.agent.execute.land_design_worker import (
            build_parcel_change_set,
            design_facility_parcel,
        )

        facilities = list(getattr(state.intent, "facilities", None) or [])
        if not facilities:
            return _execution_error(
                state,
                "facility",
                "facility_output_empty",
                "No facility targets in intent.",
            )

        features = []
        for facility in facilities:
            change = design_facility_parcel(facility, None, None)
            if change is None:
                logger.warning(
                    "[EXECUTE:facility] skipped %s (no anchor_point)",
                    getattr(facility, "type", ""),
                )
                continue
            state.parcel_changes.append(change)
            geometry = {}
            after_wkt = getattr(change, "after_geometry_wkt", "") or ""
            if after_wkt:
                try:
                    geom = wkt.loads(after_wkt)
                    if not geom.is_empty:
                        geometry = geometry_mapping(geom)
                except Exception:
                    geometry = {}
            features.append({
                "type": "Feature",
                "properties": {
                    "facility_id": change.bsm,
                    "facility_type": getattr(facility, "type", ""),
                    "status": "planned_new",
                    "source_bsm": change.bsm,
                    "change_action": change.action,
                },
                "geometry": geometry,
            })

        if state.parcel_changes:
            state.parcel_changeset = build_parcel_change_set(list(state.parcel_changes))

        if not features:
            return _execution_error(
                state,
                "facility",
                "facility_output_empty",
                "Facility targets exist but no facility layer was produced.",
            )

        layers = list(state.layout_configs)
        layers.append({
            "layerType": "facility_point",
            "layerName": "公共服务设施",
            "data": {"type": "FeatureCollection", "features": features},
        })
        logger.info("[EXECUTE:facility] appended facility layer (%d features)", len(features))
        return {"layout_configs": layers}
    except Exception as e:
        logger.error("[EXECUTE:facility] failed: %s", e, exc_info=True)
        return _execution_error(state, "facility", "facility_failed", str(e))


async def _execute_axis_node(state: ExecuteAgentState) -> dict:
    """Axis sub-task: development axis + space control zone + land use zone layers.

    Appends up to 3 layers to layout_configs.
    """
    from app.tools.gis.generate import (
        _generate_axes, _generate_space_control_zone, _generate_land_use_zone,
    )

    if "axis" not in state.tasks_to_run:
        return {}

    try:
        layers = list(state.layout_configs)
        gis_data = state.gis_data or {}
        allocated = state.allocated_geojson or {}

        axis_layer = _generate_axes(state.intent, gis_data)
        if axis_layer:
            layers.append(axis_layer)
        else:
            return _execution_error(
                state,
                "axis",
                "axis_output_empty",
                "Axis targets exist but no development-axis layer was produced.",
            )

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
        return _execution_error(state, "axis", "axis_failed", str(e))


async def _execute_road_node(state: ExecuteAgentState) -> dict:
    """Road sub-task: planned road network generation.

    Primary path: remote Stage 0-6 generator (confirmation gates 2.6/3/4,
    ported from origin/agent/kg-schema-gis-handoff-20260730). Falls back to
    the lightweight local plan_roads when the staged generator cannot produce
    a layer. If declared road targets still produce no geometry, execution
    records an error and formal output is blocked by validation.
    """
    if "road" not in state.tasks_to_run:
        return {}

    intent = state.intent
    road_targets = list(getattr(intent, "road_targets", None) or [])
    if isinstance(intent, dict):
        road_targets = list(intent.get("road_targets") or [])

    diagnostic_layers: List[Dict[str, Any]] = []
    try:
        from app.agent.execute.road_generator import (
            execute_road_planning_from_agent_state,
        )

        result = execute_road_planning_from_agent_state(state)
        layers = result.get("layout_layers") or []
        diagnostic_layers = list(layers)
        if layers:
            formal_road_layers = [
                layer
                for layer in layers
                if (layer.get("layerType") or layer.get("layer_type"))
                in {"planned_road", "planned_road_candidates"}
                and ((layer.get("data") or {}).get("features") or layer.get("features"))
            ]
            existing = state.layout_configs or []
            logger.info(
                "[EXECUTE:road] stage generator: ran=%s targets=%d layers=%d",
                result.get("ran"), result.get("road_target_count", 0), len(layers),
            )
            if formal_road_layers:
                for layer in formal_road_layers:
                    data = layer.get("data")
                    if isinstance(data, dict):
                        data.pop("crs", None)
                    layer.pop("crs", None)
                return {"layout_configs": layers + existing}
            logger.info(
                "[EXECUTE:road] stage generator produced diagnostics without formal geometry; "
                "continuing to deterministic anchor planner"
            )
        if result.get("ran"):
            logger.info(
                "[EXECUTE:road] stage generator ran but no layers: %s",
                result.get("reason"),
            )
        logger.info("[EXECUTE:road] stage generator skipped: %s", result.get("reason"))
    except Exception as e:
        logger.warning(
            "[EXECUTE:road] stage generator failed, falling back to local plan_roads: %s", e
        )

    from app.modules.spatial_ops.road_planner import plan_roads

    try:
        if not intent:
            logger.info("[EXECUTE:road] no intent, skipping")
            return {}

        # Extract road targets
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
    except Exception as e:
        logger.warning("[EXECUTE:road] failed: %s", e)
        return _execution_error(state, "road", "road_failed", str(e))

    if not planned_roads:
        logger.info("[EXECUTE:road] no roads generated")
        return _execution_error(
            state,
            "road",
            "road_output_empty",
            "Road targets exist but no planned road was produced.",
        )

    for road in planned_roads:
        geometry = road.get("geometry")
        if isinstance(geometry, str):
            try:
                road["geometry"] = json.loads(geometry)
            except json.JSONDecodeError:
                road["geometry"] = None

    # Build layer config for export/render
    road_layer = {
        "layer_type": "planned_road",
        "features": planned_roads,
        "count": len(planned_roads),
    }

    # Merge into existing layout_configs
    existing = state.layout_configs or []
    updated = [road_layer] + diagnostic_layers + existing

    logger.info(
        "[EXECUTE:road] generated %d planned roads (%d upgrade, %d new, %d preserved)",
        len(planned_roads),
        sum(1 for r in planned_roads if r.get("operation") == "upgrade"),
        sum(1 for r in planned_roads if r.get("operation") == "create"),
        sum(1 for r in planned_roads if r.get("operation") == "preserve"),
    )

    return {"layout_configs": updated}


def _build_l3_l4_consistency_report(state: ExecuteAgentState) -> dict:
    """Compare structured L3 targets with generated L4-ready geometries."""
    intent = state.intent
    expected_projects = {
        target.project_id
        for target in (getattr(intent, "project_targets", None) or [])
    }
    expected_roads = list(getattr(intent, "road_targets", None) or [])
    expected_zones = list(getattr(intent, "zone_targets", None) or [])
    placed_projects = set()
    planned_road_count = 0
    zone_area_by_name = {}

    for config in state.layout_configs or []:
        layer_type = config.get("layerType") or config.get("layer_type") or ""
        data = config.get("data") or config.get("geojson") or {}
        features = data.get("features") if isinstance(data, dict) else None
        features = features or config.get("features") or []
        if layer_type == "planned_project":
            placed_projects.update(
                str((feature.get("properties") or {}).get("project_id") or "")
                for feature in features
            )
        if layer_type in {"planned_road", "road", "road_network"}:
            planned_road_count += sum(
                1 for feature in features
                if (feature.get("geometry") or {}).get("type")
                in {"LineString", "MultiLineString"}
            )
        if layer_type in {
            "custom_planning_zone",
            "planning_zone",
            "function_zone",
            "land_use_zone",
        }:
            for feature in features:
                props = feature.get("properties") or {}
                name = str(
                    props.get("target_use")
                    or props.get("planning_zone")
                    or props.get("zone_type")
                    or props.get("land_use")
                    or ""
                )
                zone_area_by_name[name] = zone_area_by_name.get(name, 0.0) + float(
                    props.get("area_ha") or props.get("allocated_area_ha") or 0
                )

    placed_projects.discard("")
    missing_projects = sorted(expected_projects - placed_projects)
    differences = []
    suggestions = []
    if missing_projects:
        differences.append({
            "check": "project_placement",
            "expected": len(expected_projects),
            "actual": len(placed_projects),
            "missing_ids": missing_projects,
        })
        suggestions.append("重新绑定缺失项目的独立候选 BSM，并检查限制区冲突。")
    if expected_roads and planned_road_count < len(expected_roads):
        differences.append({
            "check": "road_connectivity",
            "expected": len(expected_roads),
            "actual": planned_road_count,
        })
        suggestions.append("补齐道路目标端点，使用项目点和现状道路节点重新寻路。")

    area_checks = []
    for target in expected_zones:
        if target.area_ha is None:
            continue
        actual = zone_area_by_name.get(target.land_use, 0.0)
        delta = round(actual - float(target.area_ha), 4)
        area_checks.append({
            "target": target.land_use,
            "expected_ha": float(target.area_ha),
            "actual_ha": actual,
            "delta_ha": delta,
        })
    return {
        "passed": not differences,
        "consistent_items": {
            "placed_project_ids": sorted(expected_projects & placed_projects),
            "zone_area_checks": area_checks,
            "planned_road_count": planned_road_count,
        },
        "differences": differences,
        "revision_suggestions": suggestions,
    }


async def _validate_node(state: ExecuteAgentState) -> dict:
    """Evaluator gate: validate layout via LayoutValidator, surface adjustments.

    Produces constraint_adjustments for the retry loop (fed back to
    _execute_layout_node which applies them to allocation targets).
    """
    from app.tools.gis._validation.layout_validator import LayoutValidator

    custom_layer_present = any(
        (config.get("layerType") or config.get("layer_type")) == "custom_planning_zone"
        and ((config.get("data") or config.get("geojson") or {}).get("features") or config.get("features"))
        for config in (state.layout_configs or [])
    )
    deferred_codes = {
        "road_output_empty", "road_failed", "planned_roads_unresolved", "road_deferred",
        "project_output_empty", "planned_facilities_unresolved",
    }
    if custom_layer_present and state.execution_errors:
        codes = {item.get("code") for item in state.execution_errors}
        if codes and codes.issubset(deferred_codes):
            return {
                "validation_round": state.validation_round + 1,
                "validation_result": {
                    "passed": True,
                    "status": "warning",
                    "partial_usable": True,
                    "violations": [
                        {"check": item.get("code"), "message": item.get("message")}
                        for item in state.execution_errors
                    ],
                    "reason": "custom_zone_ready_road_deferred",
                },
                "execution_errors": list(state.execution_errors or []),
            }

    if state.execution_errors:
        return {
            "validation_round": state.validation_round + 1,
            "validation_result": {
                "passed": False,
                "status": "fail",
                "violations": [
                    {
                        "check": issue.get("code", "execution_error"),
                        "message": issue.get("message", "Execution failed"),
                    }
                    for issue in state.execution_errors
                ],
                "reason": "execution_errors",
            },
        }

    if not state.layout_configs:
        return {
            "validation_round": state.validation_round + 1,
            "validation_result": {
                "passed": False,
                "status": "fail",
                "violations": [{"check": "layout_presence", "message": "No layout layers were produced"}],
                "reason": "no_layout",
            },
        }

    try:
        from app.modules.spatial_ops.custom_planning import validate_custom_planning_zone_layer

        validator = LayoutValidator()
        validator_configs = state.layout_configs
        if custom_layer_present:
            validator_configs = [
                config for config in state.layout_configs
                if (config.get("layerType") or config.get("layer_type"))
                not in {"function_zone", "land_use_zone"}
            ]
        # 道路诊断层（候选/实体/节点）是 EXECUTE 中间产物，不作为正式规划道路校验，
        # 只保留正式 planned_road / planned_road_candidates 参与校验。
        validator_configs = [
            config for config in validator_configs
            if (config.get("layerType") or config.get("layer_type"))
            not in {"road_spatial_candidates", "road_planning_entities", "road_planning_nodes"}
        ]
        report = validator.validate(
            validator_configs,
            protected_parcels_detail=state.kg_protected_parcels_detail or None,
            kg_vne_summary=state.kg_vne_summary or None,
        )

        custom_geojson = next(
            (
                config.get("data") or config.get("geojson")
                for config in state.layout_configs
                if (config.get("layerType") or config.get("layer_type")) == "custom_planning_zone"
            ),
            None,
        )
        custom_validation = (
            validate_custom_planning_zone_layer(custom_geojson)
            if custom_geojson else None
        )
        custom_violations = []
        if custom_validation and not custom_validation["passed"]:
            custom_violations.append({
                "check": "custom_planning_zone_overlap",
                "message": "Custom planning zones overlap after global allocation.",
            })
        validator_violations = [
            {"check": c.check_name, "message": c.violations[0].message}
            for c in report.checks if c.violations
        ]
        consistency = _build_l3_l4_consistency_report(state)
        try:
            from app.agent.explore.verification import save_explore_verification

            verification = await save_explore_verification(
                state.session_id, state.intent, state.layout_configs or []
            )
            consistency["l3_l4_verification"] = verification
        except Exception as e:
            logger.debug("[EXECUTE:validate] explore verification failed: %s", e)
        passed = report.status != "fail" and (
            custom_validation is None or custom_validation["passed"]
        ) and consistency["passed"]
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
                "status": report.status if passed else "fail",
                "violations": validator_violations + custom_violations,
                "custom_planning": custom_validation,
                "l3_l4_consistency": consistency,
            },
            "constraint_adjustments": adj_dicts,
        }
    except Exception as e:
        logger.error("[EXECUTE:validate] failed: %s", e, exc_info=True)
        return {
            "validation_round": state.validation_round + 1,
            "validation_result": {
                "passed": False,
                "status": "error",
                "violations": [{"check": "validator_runtime", "message": str(e)}],
                "error": str(e),
            },
        }


# ── Conditional routing ──────────────────────────────────────────────


def _route_after_validate(state: ExecuteAgentState) -> Literal["pass", "retry"]:
    """Route after validation: pass -> END, fail -> retry (max 3 rounds)."""
    result = state.validation_result or {}
    if result.get("passed", False):
        return "pass"
    if state.validation_round >= 3:
        logger.warning(
            "[EXECUTE] validation exceeded %d rounds - returning failed terminal result",
            state.validation_round,
        )
        return "pass"
    return "retry"


# ── L4 Write-back ────────────────────────────────────────────────────


def _layout_configs_to_planned_state(state: ExecuteAgentState):
    """Normalize generated layers into the authoritative L4 contract."""
    from shapely.geometry import shape
    from app.modules.schema.contracts.planned_state_contracts import (
        PlannedAxis,
        PlannedFacility,
        PlannedParcel,
        PlannedRoad,
        PlannedState,
        PlannedZone,
    )
    from app.modules.kg.ontology import EntityIdPolicy

    intent = state.intent
    zone_targets = {
        target.land_use: str(
            EntityIdPolicy.uri(
                "zone_target",
                target.zone_id or target.land_use,
            )
        )
        for target in (getattr(intent, "zone_targets", None) or [])
        if target.land_use
    }
    facility_targets = {
        target.source_instruction_id or target.type: str(
            EntityIdPolicy.uri(
                "facility_target",
                target.source_instruction_id or target.type,
            )
        )
        for target in (getattr(intent, "facilities", None) or [])
        if target.type
    }
    road_targets = {
        target.source_instruction_id or target.source_project_id or target.road_level: str(
            EntityIdPolicy.uri(
                "road_target",
                target.source_instruction_id
                or target.source_project_id
                or target.road_level,
            )
        )
        for target in (getattr(intent, "road_targets", None) or [])
    }
    axis_targets = {
        target.source_instruction_id or target.reference_feature: str(
            EntityIdPolicy.uri(
                "axis_target",
                target.source_instruction_id or target.reference_feature,
            )
        )
        for target in (getattr(intent, "development_axes", None) or [])
    }
    planned = PlannedState(
        version=f"session-{state.session_id or 'current'}",
        source="execute_layout_configs",
    )

    for config in state.layout_configs or []:
        layer_type = config.get("layerType") or config.get("layer_type") or ""
        data = config.get("data") or config.get("geojson") or {}
        features = data.get("features") if isinstance(data, dict) else None
        features = features or config.get("features") or []
        for index, feature in enumerate(features, start=1):
            props = feature.get("properties") or {}
            geometry = feature.get("geometry")
            geometry_type = (geometry or {}).get("type", "")
            wkt = shape(geometry).wkt if geometry else ""
            bsm = str(
                props.get("BSM")
                or props.get("bsm")
                or props.get("source_bsm")
                or ""
            )
            target_use = str(
                props.get("target_use")
                or props.get("planning_zone")
                or props.get("zone_type")
                or props.get("land_use")
                or ""
            )

            if geometry_type in {"Polygon", "MultiPolygon"} and layer_type in {
                "custom_planning_zone",
                "planning_zone",
                "function_zone",
                "land_use_zone",
            }:
                area_ha = float(props.get("area_ha") or props.get("allocated_area_ha") or 0)
                target_uri = zone_targets.get(target_use, "")
                if bsm:
                    planned.parcels.append(PlannedParcel(
                        bsm=bsm,
                        planning_land_use=target_use,
                        zone_type=target_use,
                        area_ha=area_ha,
                        geometry=wkt,
                        derived_from_bsms=[bsm],
                        derived_from_zone_target=target_uri,
                        source_spec=str(props.get("source_instruction_id") or ""),
                        decided_by="rule",
                        operation=str(props.get("operation") or "reclassify"),
                    ))
                else:
                    planned.zones.append(PlannedZone(
                        zone_type=target_use or layer_type,
                        area_ha=area_ha,
                        name=str(props.get("name") or target_use),
                        geometry=wkt,
                        derived_from_zone_target=target_uri,
                    ))
                continue

            if geometry_type == "Point" and layer_type in {
                "facility_point",
                "planned_project",
                "project_point",
            }:
                coordinates = geometry.get("coordinates") or [0, 0]
                source_key = str(
                    props.get("source_instruction_id")
                    or props.get("facility_type")
                    or ""
                )
                target_uri = facility_targets.get(source_key, "")
                if layer_type in {"planned_project", "project_point"}:
                    project_id = str(props.get("project_id") or "")
                    target_uri = str(EntityIdPolicy.uri("project_target", project_id)) if project_id else ""
                planned.facilities.append(PlannedFacility(
                    name=str(props.get("name") or props.get("facility_type") or props.get("project_name") or f"point-{index}"),
                    facility_type=str(props.get("facility_type") or props.get("project_category") or "project"),
                    lon=float(coordinates[0]),
                    lat=float(coordinates[1]),
                    service_radius=int(props.get("service_radius") or 0),
                    derived_from_target=target_uri,
                ))
                continue

            if geometry_type in {"LineString", "MultiLineString"}:
                source_key = str(
                    props.get("source_instruction_id")
                    or props.get("source_project_id")
                    or props.get("project_id")
                    or ""
                )
                if layer_type in {"planned_road", "road", "road_network"}:
                    planned.roads.append(PlannedRoad(
                        name=str(props.get("name") or props.get("road_name") or f"road-{index}"),
                        road_level=str(props.get("road_level") or props.get("road_class") or ""),
                        width_m=float(props.get("width_m") or props.get("recommended_width_m") or 0),
                        derived_from_target=road_targets.get(source_key, ""),
                    ))
                elif layer_type in {"axis", "development_axis", "infrastructure"}:
                    planned.axes.append(PlannedAxis(
                        name=str(props.get("name") or props.get("label") or f"axis-{index}"),
                        reference_feature=str(props.get("reference_feature") or ""),
                        direction=str(props.get("direction") or ""),
                        derived_from_target=axis_targets.get(source_key, ""),
                    ))
    return planned


async def _write_l4_node(state: ExecuteAgentState) -> dict:
    """Write L4 planned entities (PlannedParcel, PlannedZone, PlannedFacility, etc.) to KG.

    Called after execute completes to persist the planned layout back to KG.
    """
    if (state.validation_result or {}).get("partial_usable"):
        logger.warning("[EXECUTE:l4_write] Skipped for partial result; road stage is deferred")
        return {}
    if not (state.validation_result or {}).get("passed", False):
        logger.error("[EXECUTE:l4_write] Skipped because validation did not pass")
        return {}

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

    from app.modules.kg.builder.layer4 import apply_planned_state
    from app.agent.execute.planned_state_builder import changeset_to_planned_state

    if getattr(state, "parcel_changeset", None) is not None:
        planned_state = changeset_to_planned_state(state.parcel_changeset, state.intent)
        logger.info(
            "[EXECUTE:l4_write] building PlannedState from ParcelChangeSet (%d changes)",
            len(state.parcel_changeset.changes),
        )
    else:
        logger.warning("[EXECUTE:l4_write] no parcel_changeset; falling back to layout_configs path")
        planned_state = _layout_configs_to_planned_state(state)
    written = sum(
        len(items)
        for items in (
            planned_state.parcels,
            planned_state.zones,
            planned_state.facilities,
            planned_state.roads,
            planned_state.axes,
        )
    )
    if written:
        apply_planned_state(kg, planned_state)
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

    graph.add_node("route_tasks", _checkpoint_safe_node(_route_tasks_node))
    graph.add_node("execute_layout", _checkpoint_safe_node(_execute_layout_node))
    graph.add_node("execute_project", _checkpoint_safe_node(_execute_project_node))
    graph.add_node("execute_facility", _checkpoint_safe_node(_execute_facility_node))
    graph.add_node("execute_axis", _checkpoint_safe_node(_execute_axis_node))
    graph.add_node("execute_road", _checkpoint_safe_node(_execute_road_node))
    graph.add_node("validate", _checkpoint_safe_node(_validate_node))
    graph.add_node("write_l4", _checkpoint_safe_node(_write_l4_node))

    graph.add_edge(START, "route_tasks")
    graph.add_edge("route_tasks", "execute_layout")
    graph.add_edge("execute_layout", "execute_project")
    graph.add_edge("execute_project", "execute_facility")
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
    logger.info("[EXECUTE] Agent graph compiled: 8 nodes (incl. L4 write-back), 1 conditional edge")
    return compiled


__all__ = ["build_execute_agent_graph"]
