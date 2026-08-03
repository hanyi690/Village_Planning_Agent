"""Layer 3: PARSE intent (SpatialPlanningIntent -> RDF subgraph + SemanticMemoryStore).

All functions are module-level and assigned to PlanningKG in base.py.

Intent virtual entities (ZoneTarget, FacilityTarget, AxisTarget, RoadTarget)
enter KG with rough geometry and spatial anchoring triples for spatial
grounding. Entity/relation annotations stored in self.memory.

Lifecycle: build_intent_layer creates L3 entities, clear_intent_layer removes them.
"""
from typing import Any

from rdflib import Literal, RDF
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, EntityIdPolicy
from ..memory import EntityAnnotation

logger = get_logger(__name__)

# L3 entity types for clear_intent_layer
_L3_TYPES = {
    EntityTypes.ZoneTarget, EntityTypes.FacilityTarget,
    EntityTypes.AxisTarget, EntityTypes.RoadTarget, EntityTypes.ProjectTarget,
}


def _serialize_bbox(bbox) -> str:
    """Serialize bbox tuple to comma-separated string for RDF literal."""
    if bbox is None:
        return ""
    try:
        return ",".join(str(round(v, 6)) for v in bbox)
    except (TypeError, ValueError):
        return ""


def _source_refs(target, intent) -> list[str]:
    return [
        value
        for value in (
            getattr(target, "source_report_key", ""),
            getattr(target, "source_instruction_id", ""),
            getattr(getattr(target, "semantic", None), "raw_text", ""),
            intent.raw_text,
        )
        if value
    ]


def build_intent_layer(kg, intent: Any) -> None:
    """Build L3 intent virtual entities from SpatialPlanningIntent.

    ZoneTarget, FacilityTarget, AxisTarget, RoadTarget enter KG with
    spatial anchoring triples (candidate_bsm, excluded_bsm, candidate_bbox,
    spatial_hint, description). Semantic annotations in SemanticMemoryStore.
    """
    from app.modules.schema.contracts.parse_contracts import (
        SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget, RoadTarget,
        ProjectTarget,
    )
    if not isinstance(intent, SpatialPlanningIntent):
        logger.warning("build_intent_layer requires SpatialPlanningIntent, got %s", type(intent).__name__)
        return

    zc = fc = ac = rc = pc = 0

    # ── Project targets (parents of facility/road/zone execution targets) ──
    project_uris = {}
    for project in intent.project_targets:
        p_uri = EntityIdPolicy.uri("project_target", project.project_id)
        project_uris[project.project_id] = p_uri
        kg.g.add((p_uri, RDF.type, EntityTypes.ProjectTarget))
        kg.g.add((p_uri, PLN.target_id, Literal(project.project_id)))
        kg.g.add((p_uri, PLN.name, Literal(project.name)))
        kg.g.add((p_uri, PLN.project_category, Literal(project.category)))
        kg.g.add((p_uri, PLN.operation, Literal(project.action)))
        if project.location_hint:
            kg.g.add((p_uri, PLN.location_hint, Literal(project.location_hint)))
        if project.scale_text:
            kg.g.add((p_uri, PLN.scale_text, Literal(project.scale_text)))
        if project.area_ha is not None:
            kg.g.add((p_uri, PLN.target_area_ha, Literal(project.area_ha, datatype=XSD.double)))
        if project.source_instruction_id:
            kg.g.add((p_uri, PLN.source_instruction_id, Literal(project.source_instruction_id)))
        if project.source_report_key:
            kg.g.add((p_uri, PLN.source_report_key, Literal(project.source_report_key)))
        for bsm in project.candidate_bsms:
            kg.g.add((p_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        for bsm in project.excluded_bsms:
            kg.g.add((p_uri, PLN.excluded_bsm, PLN[f"parcel_{bsm}"]))
        kg.g.add((PLN.village, PLN.has_project, p_uri))
        kg.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(p_uri),
            entity_type="ProjectTarget",
            description=f"规划项目: {project.name} ({project.category})",
            source_text_refs=[
                value for value in (
                    project.source_report_key,
                    project.semantic.raw_text,
                ) if value
            ],
            intent_refs=[project.source_instruction_id] if project.source_instruction_id else [],
        ))
        pc += 1

    # ── Zone targets ──
    for zt in intent.zone_targets:
        target_id = zt.zone_id or zt.land_use or f"idx{zc}"
        z_uri = EntityIdPolicy.uri("zone_target", target_id)
        kg.g.add((z_uri, RDF.type, EntityTypes.ZoneTarget))
        kg.g.add((z_uri, PLN.target_id, Literal(target_id)))
        kg.g.add((z_uri, PLN.land_use_code, Literal(zt.land_use)))
        if zt.area_ha is not None:
            kg.g.add((z_uri, PLN.target_area_ha, Literal(zt.area_ha, datatype=XSD.double)))
        if zt.area_ratio > 0:
            kg.g.add((z_uri, PLN.target_area_ratio, Literal(zt.area_ratio, datatype=XSD.double)))
        if zt.planning_zone:
            kg.g.add((z_uri, PLN.planning_zone, Literal(zt.planning_zone)))
        if zt.dlbm:
            kg.g.add((z_uri, PLN.dlbm, Literal(zt.dlbm)))
        if zt.vne_code:
            kg.g.add((z_uri, PLN.vne_code, Literal(zt.vne_code)))
        kg.g.add((z_uri, PLN.density, Literal(zt.density)))
        kg.g.add((PLN.village, PLN.has_zone, z_uri))
        if zt.source_instruction_id:
            kg.g.add((z_uri, PLN.source_instruction_id, Literal(zt.source_instruction_id)))
        if zt.source_report_key:
            kg.g.add((z_uri, PLN.source_report_key, Literal(zt.source_report_key)))
        # Spatial anchoring triples
        for bsm in zt.candidate_bsms:
            kg.g.add((z_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        for bsm in zt.excluded_bsms:
            kg.g.add((z_uri, PLN.excluded_bsm, PLN[f"parcel_{bsm}"]))
        bbox_str = _serialize_bbox(zt.candidate_bbox)
        if bbox_str:
            kg.g.add((z_uri, PLN.candidate_bbox, Literal(bbox_str)))
        hint = zt.semantic.spatial_hint
        if hint:
            kg.g.add((z_uri, PLN.spatial_hint, Literal(hint)))
        desc = zt.semantic.natural_language_description
        if desc:
            kg.g.add((z_uri, PLN.description, Literal(desc)))
        # Semantic memory annotation
        if zt.area_ha is not None:
            mem_desc = f"规划目标: 将 {zt.area_ha:.2f} 公顷土地用于 {zt.land_use}"
        else:
            mem_desc = f"规划目标: 将 {zt.area_ratio*100:.0f}% 的土地用于 {zt.land_use}"
        if zt.dlbm:
            mem_desc += f" (地类编码: {zt.dlbm})"
        kg.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(z_uri),
            entity_type="ZoneTarget",
            description=mem_desc,
            source_text_refs=_source_refs(zt, intent),
            intent_refs=[zt.source_instruction_id] if zt.source_instruction_id else [],
        ))
        zc += 1

    # ── Facility targets ──
    for ft in intent.facilities:
        target_id = ft.source_instruction_id or ft.type or f"idx{fc}"
        f_uri = EntityIdPolicy.uri("facility_target", target_id)
        kg.g.add((f_uri, RDF.type, EntityTypes.FacilityTarget))
        kg.g.add((f_uri, PLN.target_id, Literal(target_id)))
        kg.g.add((f_uri, PLN.facility_type, Literal(ft.type)))
        kg.g.add((f_uri, PLN.status, Literal(ft.status)))
        if ft.location_hint:
            kg.g.add((f_uri, PLN.location_hint, Literal(ft.location_hint)))
        if ft.service_radius:
            kg.g.add((f_uri, PLN.service_radius, Literal(ft.service_radius, datatype=XSD.integer)))
        if ft.direction:
            kg.g.add((f_uri, PLN.direction, Literal(ft.direction)))
        # Spatial anchoring triples
        for bsm in ft.candidate_bsms:
            kg.g.add((f_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        if ft.anchor_point:
            kg.g.add((f_uri, PLN.anchor_point, Literal(f"{ft.anchor_point[0]},{ft.anchor_point[1]}")))
        hint = ft.semantic.spatial_hint
        if hint:
            kg.g.add((f_uri, PLN.spatial_hint, Literal(hint)))
        kg.g.add((PLN.village, PLN.has_facility, f_uri))
        if ft.source_project_id in project_uris:
            kg.g.add((project_uris[ft.source_project_id], PLN.has_facility, f_uri))
        if ft.source_instruction_id:
            kg.g.add((f_uri, PLN.source_instruction_id, Literal(ft.source_instruction_id)))
        if ft.source_report_key:
            kg.g.add((f_uri, PLN.source_report_key, Literal(ft.source_report_key)))
        # Semantic memory annotation
        svc = f"服务半径{ft.service_radius}m" if ft.service_radius else ""
        loc = f"位于{ft.location_hint}" if ft.location_hint else ""
        kg.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(f_uri),
            entity_type="FacilityTarget",
            description=f"规划设施: {ft.type} ({ft.status}) {svc} {loc}".strip(),
            source_text_refs=_source_refs(ft, intent),
            intent_refs=[ft.source_instruction_id] if ft.source_instruction_id else [],
        ))
        fc += 1

    # ── Development axes ──
    for ax in intent.development_axes:
        target_id = ax.source_instruction_id or ax.reference_feature or f"idx{ac}"
        a_uri = EntityIdPolicy.uri("axis_target", target_id)
        kg.g.add((a_uri, RDF.type, EntityTypes.AxisTarget))
        kg.g.add((a_uri, PLN.target_id, Literal(target_id)))
        if ax.reference_feature:
            kg.g.add((a_uri, PLN.reference_feature, Literal(ax.reference_feature)))
        if ax.direction:
            kg.g.add((a_uri, PLN.direction, Literal(ax.direction)))
        if ax.axis_type:
            kg.g.add((a_uri, PLN.axis_type, Literal(ax.axis_type)))
        if ax.label:
            kg.g.add((a_uri, PLN.label, Literal(ax.label)))
        # Spatial anchoring triples
        if ax.start_anchor:
            kg.g.add((a_uri, PLN.anchor_point, Literal(f"{ax.start_anchor[0]},{ax.start_anchor[1]}")))
        if ax.end_anchor:
            kg.g.add((a_uri, PLN.end_point, Literal(f"{ax.end_anchor[0]},{ax.end_anchor[1]}")))
        for bsm in ax.corridor_bsms:
            kg.g.add((a_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        kg.g.add((PLN.village, PLN.has_axis, a_uri))
        if ax.source_project_id in project_uris:
            kg.g.add((project_uris[ax.source_project_id], PLN.has_axis, a_uri))
        if ax.source_instruction_id:
            kg.g.add((a_uri, PLN.source_instruction_id, Literal(ax.source_instruction_id)))
        if ax.source_report_key:
            kg.g.add((a_uri, PLN.source_report_key, Literal(ax.source_report_key)))
        # Semantic memory annotation
        kg.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(a_uri),
            entity_type="AxisTarget",
            description=f"发展轴线: 沿{ax.reference_feature}方向",
            source_text_refs=_source_refs(ax, intent),
            intent_refs=[ax.source_instruction_id] if ax.source_instruction_id else [],
        ))
        ac += 1

    # ── Road targets (NEW — fills road sub-task gap) ──
    for rt in intent.road_targets:
        target_id = rt.source_instruction_id or rt.source_project_id or rt.road_level or f"idx{rc}"
        r_uri = EntityIdPolicy.uri("road_target", target_id)
        kg.g.add((r_uri, RDF.type, EntityTypes.RoadTarget))
        kg.g.add((r_uri, PLN.target_id, Literal(target_id)))
        if rt.road_level:
            kg.g.add((r_uri, PLN.road_level, Literal(rt.road_level)))
        if rt.width_m > 0:
            kg.g.add((r_uri, PLN.width_m, Literal(rt.width_m, datatype=XSD.double)))
        for conn in rt.connects:
            kg.g.add((r_uri, PLN.connects, Literal(conn)))
        # Spatial anchoring triples
        if rt.start_anchor:
            kg.g.add((r_uri, PLN.anchor_point, Literal(f"{rt.start_anchor[0]},{rt.start_anchor[1]}")))
        if rt.end_anchor:
            kg.g.add((r_uri, PLN.end_point, Literal(f"{rt.end_anchor[0]},{rt.end_anchor[1]}")))
        for bsm in rt.path_bsms:
            kg.g.add((r_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        hint = rt.semantic.spatial_hint
        if hint:
            kg.g.add((r_uri, PLN.spatial_hint, Literal(hint)))
        kg.g.add((PLN.village, PLN.has_road, r_uri))
        if rt.source_project_id in project_uris:
            kg.g.add((project_uris[rt.source_project_id], PLN.has_road, r_uri))
        if rt.source_instruction_id:
            kg.g.add((r_uri, PLN.source_instruction_id, Literal(rt.source_instruction_id)))
        if rt.source_report_key:
            kg.g.add((r_uri, PLN.source_report_key, Literal(rt.source_report_key)))
        # Semantic memory annotation
        kg.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(r_uri),
            entity_type="RoadTarget",
            description=f"规划道路: {rt.road_level} 宽{rt.width_m}m",
            source_text_refs=_source_refs(rt, intent),
            intent_refs=[rt.source_instruction_id] if rt.source_instruction_id else [],
        ))
        rc += 1

    # Raw planning text on village entity
    if intent.raw_text:
        kg.g.add((PLN.village, PLN.raw_planning_text, Literal(intent.raw_text)))

    logger.info(
        "build_intent_layer: %d projects, %d zones, %d facilities, %d axes, %d roads",
        pc, zc, fc, ac, rc,
    )


def clear_intent_layer(kg) -> None:
    """Remove all L3 intent virtual entities from the RDF graph.

    Called at end of planning session to clean up volatile L3 triples.
    """
    count = 0
    for t in _L3_TYPES:
        for s in list(kg.g.subjects(RDF.type, t)):
            for p, o in kg.g.predicate_objects(s):
                kg.g.remove((s, p, o))
                count += 1
    if count:
        logger.info("clear_intent_layer: removed %d L3 triples", count)
