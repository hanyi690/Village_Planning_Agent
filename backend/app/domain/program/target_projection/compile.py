"""Deterministic target projection from PlanningProgram.

Wave F COMPILE mode core. Consumes L3 PlanningProgram (typed aggregate) and
produces IntentCompilationResult + SpatialReferenceSpec[] + diagnostics.
No LLM calls and no natural-language re-interpretation.
"""
from __future__ import annotations

from app.data.ingestion.compiler.spec_mapper import (
    map_intervention_to_spec,
    map_interventions_to_specs,
)
from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram
from app.contracts.workflow.parse_contracts import (
    FacilityTarget,
    AxisTarget,
    LinearAssetTarget,
    SiteAreaTarget,
    RoadTarget,
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.contracts.workflow.parse_result_contracts import (
    ClaimDispositionAudit,
    CompilationStatus,
    IntentCompilationResult,
    ParseDiagnostic,
)
from app.contracts.artifacts.provenance import Provenance, SemanticMetadata
from app.contracts.evidence.identity_contracts import EvidenceObservation, GroundedEntityBinding
from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec
from app.domain.program.claim_adapter import admission_reasons_for_intervention
from app.domain.program.target_projection.intent_graph_compiler import compile_intent_graph_v2
from app.domain.program.target_projection.planning_task_graph_compiler import (
    compile_planning_task_graph,
    intent_graph_with_pending_claims,
    pending_claim_grounding_specs,
)


def _spatial_hint(intervention: PlanningIntervention) -> str:
    req = intervention.spatial_requirements
    if isinstance(req, dict):
        location = req.get("location")
        if isinstance(location, str) and location.strip():
            return location.strip()
        hints = req.get("location_hints")
        if isinstance(hints, list):
            return "、".join(str(item).strip() for item in hints if str(item).strip())
    return ""


def _semantic(intervention: PlanningIntervention) -> SemanticMetadata:
    # Keep the full prose in raw_text so GROUND/road Stage 2.6 can mine
    # location clues (problem_addressed often carries 村名/河名/全域) that
    # are absent from the structured location cell.
    raw_parts = [
        intervention.name,
        str(intervention.problem_addressed or ""),
        str(intervention.scale or ""),
        *[str(fn) for fn in (intervention.functions or [])],
    ]
    raw_text = " ".join(part for part in raw_parts if part and str(part).strip())
    return SemanticMetadata(
        natural_language_description=intervention.name,
        spatial_hint=_spatial_hint(intervention),
        raw_text=raw_text,
    )


def _project_action(intervention: PlanningIntervention) -> str:
    action = intervention.intervention_action
    if action == "widen":
        return "upgrade"
    if action == "harden":
        return "repair"
    return action


def _to_site_area_target(intervention: PlanningIntervention, index: int) -> SiteAreaTarget:
    role = intervention.materialization_role
    project_role = role if role != "land_use_assignment" else None
    parameters = intervention.site_area_parameters
    area_ha = intervention.area_range_ha[0] if intervention.area_range_ha else None
    if area_ha is None and parameters is not None and parameters.footprint_area_m2:
        area_ha = parameters.footprint_area_m2 / 10000.0
    return SiteAreaTarget(
        target_id=intervention.target_id,
        site_area_id=intervention.intervention_id,
        name=intervention.name,
        category=intervention.category,
        materialization_role=(
            "site_footprint" if project_role == "site_footprint" else project_role
        ),
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        action=_project_action(intervention),
        scale_text=intervention.scale,
        area_ha=area_ha,
        capacity=parameters.capacity if parameters is not None else None,
        capacity_unit=parameters.capacity_unit if parameters is not None else "",
        footprint_area_m2=(
            parameters.footprint_area_m2 if parameters is not None else None
        ),
        location_hint=_spatial_hint(intervention),
        source_instruction_id=intervention.intervention_id,
        claim_refs=list(intervention.claim_refs),
        classification_decision=intervention.classification_decision,
        source_section="L3_PROGRAM",
        source_row=index,
        semantic=_semantic(intervention),
    )


def _to_facility_target(intervention: PlanningIntervention) -> FacilityTarget:
    parameters = intervention.facility_parameters
    action = parameters.action if parameters is not None else "new"
    status_by_action = {
        "preserve": "existing_preserve",
        "new": "planned_new",
        "expand": "planned_expand",
        "relocate": "planned_relocate",
        "repair": "existing_preserve",
    }
    return FacilityTarget(
        target_id=intervention.target_id,
        type=(parameters.facility_type if parameters is not None else "") or intervention.name,
        action=action,
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        status=status_by_action[action],
        location_hint=_spatial_hint(intervention),
        source_project_id=intervention.intervention_id,
        source_instruction_id=intervention.intervention_id,
        claim_refs=list(intervention.claim_refs),
        classification_decision=intervention.classification_decision,
        direction="center",
        service_radius=(
            round(parameters.service_radius_m)
            if parameters is not None and parameters.service_radius_m is not None
            else None
        ),
        capacity=parameters.capacity if parameters is not None else None,
        capacity_unit=parameters.capacity_unit if parameters is not None else "",
        footprint_area_m2=(
            parameters.footprint_area_m2 if parameters is not None else None
        ),
        semantic=_semantic(intervention),
    )


def _road_level(intervention: PlanningIntervention) -> str:
    parameters = intervention.road_parameters
    return parameters.road_level if parameters is not None else ""


def _road_width_m(intervention: PlanningIntervention) -> float:
    parameters = intervention.road_parameters
    if parameters is None:
        return 0.0
    return float(parameters.pavement_width_m or parameters.roadbed_width_m or 0.0)


def _road_connects(intervention: PlanningIntervention) -> list[str]:
    """Project L3-owned endpoint semantics without reinterpreting prose."""
    parameters = intervention.road_parameters
    if parameters is not None:
        return list(parameters.connects)
    linear = intervention.linear_parameters
    return list(linear.connects) if linear is not None else []


def _to_road_target(intervention: PlanningIntervention) -> RoadTarget:
    connects = _road_connects(intervention)
    parameters = intervention.road_parameters
    linear = intervention.linear_parameters
    requirements = intervention.spatial_requirements or {}
    raw_source_ids = next(
        (
            requirements.get(key)
            for key in (
                "source_feature_ids",
                "existing_road_feature_ids",
                "road_feature_ids",
            )
            if key in requirements
        ),
        None,
    )
    raw_segment_ids = requirements.get("existing_road_segment_ids")
    existing_road_feature_ids = (
        list(dict.fromkeys(
            str(item).strip()
            for item in raw_source_ids
            if str(item).strip()
        ))
        if isinstance(raw_source_ids, (list, tuple, set))
        else []
    )
    existing_road_segment_ids = (
        list(dict.fromkeys(
            str(item).strip()
            for item in raw_segment_ids
            if str(item).strip()
        ))
        if isinstance(raw_segment_ids, (list, tuple, set))
        else []
    )
    return RoadTarget(
        target_id=intervention.target_id,
        asset_kind=intervention.asset_kind,
        road_level=_road_level(intervention),
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        width_m=_road_width_m(intervention) if intervention.asset_kind == "road" else 0.0,
        action=(
            parameters.action if parameters is not None
            else (linear.action if linear is not None else "new")
        ),
        road_planning_kind=(
            "new_corridor"
            if parameters is None or parameters.action == "new"
            else "existing_road_intervention"
        ),
        length_m=(
            parameters.length_m if parameters is not None
            else (linear.length_m if linear is not None else None)
        ),
        roadbed_width_m=parameters.roadbed_width_m if parameters is not None else None,
        pavement_width_m=parameters.pavement_width_m if parameters is not None else None,
        connects=connects,
        alignment_refs=(
            list(parameters.alignment_refs) if parameters is not None
            else (list(linear.alignment_refs) if linear is not None else [])
        ),
        existing_road_feature_ids=existing_road_feature_ids,
        existing_road_segment_ids=existing_road_segment_ids,
        linear_diameter_mm=linear.diameter_mm if linear is not None else None,
        linear_material=linear.material if linear is not None else "",
        source_project_id=intervention.intervention_id,
        classification_decision=intervention.classification_decision,
        claim_refs=list(intervention.claim_refs),
        semantic=_semantic(intervention),
    )


def _to_linear_target(intervention: PlanningIntervention) -> LinearAssetTarget:
    parameters = intervention.linear_parameters
    return LinearAssetTarget(
        target_id=intervention.target_id,
        asset_kind=intervention.asset_kind,
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        action=parameters.action if parameters is not None else "new",
        length_m=parameters.length_m if parameters is not None else None,
        diameter_mm=parameters.diameter_mm if parameters is not None else None,
        material=parameters.material if parameters is not None else "",
        connects=list(parameters.connects) if parameters is not None else [],
        alignment_refs=list(parameters.alignment_refs) if parameters is not None else [],
        source_project_id=intervention.intervention_id,
        source_instruction_id=intervention.intervention_id,
        claim_refs=list(intervention.claim_refs),
        classification_decision=intervention.classification_decision,
        semantic=_semantic(intervention),
    )


def _to_axis_target(intervention: PlanningIntervention) -> AxisTarget:
    parameters = intervention.axis_parameters
    requirements = intervention.spatial_requirements or {}
    raw_source_ids = next(
        (
            requirements.get(key)
            for key in (
                "source_feature_ids",
                "existing_road_feature_ids",
                "road_feature_ids",
            )
            if key in requirements
        ),
        None,
    )
    source_feature_ids = (
        list(dict.fromkeys(
            str(item).strip()
            for item in raw_source_ids
            if str(item).strip()
        ))
        if isinstance(raw_source_ids, (list, tuple, set))
        else []
    )
    return AxisTarget(
        target_id=intervention.target_id,
        label=intervention.name,
        action=parameters.action if parameters is not None else "new",
        reference_feature=(
            "、".join(parameters.reference_features) if parameters is not None else ""
        ),
        connects=list(parameters.connects) if parameters is not None else [],
        direction=parameters.direction if parameters is not None else "",
        axis_type=parameters.axis_type if parameters is not None else "primary",
        corridor_width_m=(
            parameters.corridor_width_m if parameters is not None else None
        ),
        source_feature_ids=source_feature_ids,
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        source_project_id=intervention.intervention_id,
        source_instruction_id=intervention.intervention_id,
        classification_decision=intervention.classification_decision,
        claim_refs=list(intervention.claim_refs),
        semantic=_semantic(intervention),
    )


def _to_zone_target(intervention: PlanningIntervention) -> ZoneTarget:
    parameters = intervention.polygon_parameters
    return ZoneTarget(
        target_id=intervention.target_id,
        land_use=(
            parameters.land_use
            if parameters is not None and parameters.land_use
            else (intervention.functions[0] if intervention.functions else intervention.name)
        ),
        planning_zone=(
            parameters.planning_zone if parameters is not None else None
        ),
        materialization_role="land_use_assignment",
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        area_ha=intervention.area_range_ha[0] if intervention.area_range_ha else None,
        zone_id=intervention.intervention_id,
        source_instruction_id=intervention.intervention_id,
        classification_decision=intervention.classification_decision,
        claim_refs=list(intervention.claim_refs),
        semantic=_semantic(intervention),
    )


def _build_intent(program: PlanningProgram) -> SpatialPlanningIntent:
    intent = SpatialPlanningIntent(village_name="", planning_period="", raw_text="")
    for index, intervention in enumerate(program.interventions):
        category = intervention.category
        if category == "site_area":
            intent.site_area_targets.append(_to_site_area_target(intervention, index))
        elif category == "facility":
            intent.facilities.append(_to_facility_target(intervention))
        elif category == "road":
            if intervention.asset_kind == "road":
                intent.road_targets.append(_to_road_target(intervention))
            else:
                intent.linear_targets.append(_to_linear_target(intervention))
        elif category == "axis":
            intent.development_axes.append(_to_axis_target(intervention))
        elif category in ("restoration", "protection"):
            intent.site_area_targets.append(_to_site_area_target(intervention, index))
        elif category == "zone":
            if intervention.materialization_role == "land_use_assignment":
                intent.zone_targets.append(_to_zone_target(intervention))
            else:
                intent.site_area_targets.append(_to_site_area_target(intervention, index))
        else:
            intent.site_area_targets.append(_to_site_area_target(intervention, index))
    return intent


def _build_diagnostics(
    program: PlanningProgram,
    spec_diags: list[ParseDiagnostic],
) -> list[ParseDiagnostic]:
    diagnostics = list(spec_diags)
    if not program.interventions:
        diagnostics.append(
            ParseDiagnostic(
                diagnostic_id="target-projection-empty-program",
                severity="warning",
                code="EMPTY_PROGRAM",
                message="PlanningProgram has no interventions",
                field_path="interventions",
            )
        )
    for intervention in program.interventions:
        if intervention.planning_role != "spatial_intervention":
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"admission-role-{intervention.target_id}",
                    severity="error",
                    code="INTERVENTION_NOT_ADMITTED",
                    message="TARGET_PROJECTION requires an admitted spatial_intervention role",
                    field_path="planning_role",
                    target_id=intervention.target_id,
                )
            )
        if not intervention.project_package_ref or not intervention.admission_reason:
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"admission-lineage-{intervention.target_id}",
                    severity="error",
                    code="INTERVENTION_ADMISSION_LINEAGE_MISSING",
                    message="TARGET_PROJECTION requires package and admission lineage",
                    field_path="project_package_ref",
                    target_id=intervention.target_id,
                )
            )
        if (
            intervention.admission_reason == "typed_spatial_claim_ready"
            and not (
                intervention.claim_refs
                and (
                    intervention.evidence_refs
                    or intervention.source_fact_refs
                    or intervention.source_refs
                )
            )
        ):
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"admission-evidence-{intervention.target_id}",
                    severity="error",
                    code="INTERVENTION_EVIDENCE_LINEAGE_MISSING",
                    message="admitted intervention must retain claim and evidence/source lineage",
                    field_path="claim_refs",
                    target_id=intervention.target_id,
                )
            )
        if (
            intervention.category == "road"
            and intervention.asset_kind == "road"
            and (
                intervention.road_parameters is None
                or (
                    intervention.road_parameters.length_m is None
                    and intervention.road_parameters.roadbed_width_m is None
                    and intervention.road_parameters.pavement_width_m is None
                )
            )
        ):
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"road-semantics-{intervention.target_id}",
                    severity="warning",
                    code="ROAD_SEMANTICS_UNRESOLVED",
                    message="Road length/width/action semantics were not resolved in L3",
                    field_path="road_parameters",
                    target_id=intervention.target_id,
                )
            )
        if intervention.category == "facility" and intervention.facility_parameters is None:
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"facility-semantics-{intervention.target_id}",
                    severity="warning",
                    code="FACILITY_SEMANTICS_UNRESOLVED",
                    message="Facility type/action/scale semantics were not resolved in L3",
                    field_path="facility_parameters",
                    target_id=intervention.target_id,
                )
            )
        if intervention.category == "axis" and intervention.axis_parameters is None:
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"axis-semantics-{intervention.target_id}",
                    severity="warning",
                    code="AXIS_SEMANTICS_UNRESOLVED",
                    message="Axis direction/reference semantics were not resolved in L3",
                    field_path="axis_parameters",
                    target_id=intervention.target_id,
                )
            )
        if intervention.category == "zone" and intervention.materialization_role is None:
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"zone-role-{intervention.target_id}",
                    severity="warning",
                    code="ZONE_MATERIALIZATION_UNRESOLVED",
                    message="Zone versus overlay materialization was not resolved in L3",
                    field_path="materialization_role",
                    target_id=intervention.target_id,
                )
            )
        if (
            intervention.category == "site_area"
            and intervention.expected_output_kind in {"parcel", "polygon"}
            and intervention.materialization_role != "site_footprint"
        ):
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"site-area-role-{intervention.target_id}",
                    severity="warning",
                    code="SITE_AREA_MATERIALIZATION_UNRESOLVED",
                    message="Site-area footprint semantics were not resolved in L3",
                    field_path="materialization_role",
                    target_id=intervention.target_id,
                )
            )
    return diagnostics


def compile_program_deterministic(
    program: PlanningProgram,
    *,
    run_id: str = "",
    context_version: str = "",
    program_ref: str = "",
    observations: list[EvidenceObservation] | None = None,
    bindings: list[GroundedEntityBinding] | None = None,
    source_features: dict[str, list[object]] | None = None,
    source_semantic_decisions: dict[str, object] | None = None,
) -> tuple[IntentCompilationResult, list, list[ParseDiagnostic]]:
    """Deterministically extract a compile result from an L3 PlanningProgram.

    No LLM calls. Returns (IntentCompilationResult, SpatialReferenceSpec[], diagnostics).
    """
    admission_failures = {
        intervention.intervention_id: admission_reasons_for_intervention(
            intervention,
            list(program.claims),
        )
        for intervention in program.interventions
    }
    admitted_program = program.model_copy(
        deep=True,
        update={
            "interventions": [
                intervention
                for intervention in program.interventions
                if not admission_failures[intervention.intervention_id]
            ]
        },
    )
    intent = _build_intent(admitted_program)
    intent_graph = compile_intent_graph_v2(
        admitted_program,
        observations=observations,
        bindings=bindings,
    )
    pending_claims = list(program.pending_grounding_claims)
    intent_graph = intent_graph_with_pending_claims(intent_graph, pending_claims)
    planning_task_graph = compile_planning_task_graph(
        intent_graph,
        pending_claims=pending_claims,
    )
    pending_specs = pending_claim_grounding_specs(pending_claims)
    specs, spec_diags = map_interventions_to_specs(
        admitted_program.interventions,
        observations=observations or (),
        bindings=bindings or (),
        source_features=source_features or {},
        source_semantic_decisions=source_semantic_decisions or {},
    )
    diagnostics = _build_diagnostics(program, spec_diags)
    diagnostics.extend(
        ParseDiagnostic(
            diagnostic_id=f"admission-recompute-{intervention_id}",
            severity="error",
            code="INTERVENTION_ADMISSION_RECOMPUTE_FAILED",
            message="; ".join(reasons),
            field_path="interventions",
            target_id=intervention_id,
        )
        for intervention_id, reasons in admission_failures.items()
        if reasons
    )
    diagnostics.extend(
        ParseDiagnostic(
            diagnostic_id=f"intent-graph-{index}",
            severity="error" if item.startswith((
                "relation_subject_type_mismatch",
                "relation_object_type_mismatch",
                "relation_unknown_subject",
                "relation_unknown_object",
                "relation_parameters_invalid",
                "relation_parameters_missing",
                "relation_parameter_type_mismatch",
                "relation_deferred",
                "relation_missing_object",
                "unsupported_relation_template",
            )) else "warning",
            code=item.split(":", 1)[0],
            message=item,
        )
        for index, item in enumerate(intent_graph.diagnostics)
    )

    provenance = Provenance(
        source="target_projection",
        run_id=run_id,
        module="target_projection",
        trace=[f"compile:{run_id}"],
        natural_language_description=(
            "Deterministic projection of PlanningProgram "
            f"{program.artifact_id or program_ref} into typed spatial targets"
        ),
    )

    result = IntentCompilationResult(
        program_ref=program_ref or program.artifact_id,
        claims=list(program.claims),
        pending_grounding_claims=list(program.pending_grounding_claims),
        claim_dispositions=[
            ClaimDispositionAudit(
                claim_id=item.claim_id,
                dimension_key=item.dimension_key,
                status=item.status,
                reason=item.reason,
                missing_requirements=list(item.missing_requirements),
            )
            for item in program.claim_dispositions
        ],
        typed_intent=intent,
        spatial_reference_specs=specs,
        diagnostics=diagnostics,
        compilation_status=CompilationStatus.DRAFT,
        provenance=provenance,
        intent_graph=intent_graph,
        planning_task_graph=planning_task_graph,
        pending_grounding_specs=pending_specs,
    )
    from app.evidence.retrieval.requirements import (
        requirements_from_l3,
        requirements_from_target_projection,
    )

    target_requirements = requirements_from_target_projection(result)
    pending_requirements = tuple(
        item
        for item in requirements_from_l3(program)
        if bool(item.metadata.get("pending_grounding"))
    )
    result.evidence_requirements = list({
        item.requirement_id: item
        for item in (*target_requirements, *pending_requirements)
    }.values())
    return result, specs, diagnostics
