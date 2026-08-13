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
    ProjectTarget,
    RoadTarget,
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.contracts.workflow.parse_result_contracts import (
    CompilationStatus,
    IntentCompilationResult,
    ParseDiagnostic,
)
from app.contracts.artifacts.provenance import Provenance, SemanticMetadata
from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec


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


def _to_project_target(intervention: PlanningIntervention, index: int) -> ProjectTarget:
    role = intervention.materialization_role
    project_role = role if role != "land_use_assignment" else None
    parameters = intervention.project_parameters
    area_ha = intervention.area_range_ha[0] if intervention.area_range_ha else None
    if area_ha is None and parameters is not None and parameters.footprint_area_m2:
        area_ha = parameters.footprint_area_m2 / 10000.0
    return ProjectTarget(
        target_id=intervention.target_id,
        project_id=intervention.intervention_id,
        name=intervention.name,
        category=intervention.category,
        materialization_role=project_role,
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
    return list(parameters.connects) if parameters is not None else []


def _to_road_target(intervention: PlanningIntervention) -> RoadTarget:
    connects = _road_connects(intervention)
    parameters = intervention.road_parameters
    return RoadTarget(
        target_id=intervention.target_id,
        road_level=_road_level(intervention),
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        width_m=_road_width_m(intervention),
        action=parameters.action if parameters is not None else "new",
        road_planning_kind=(
            "new_corridor"
            if parameters is None or parameters.action == "new"
            else "existing_road_intervention"
        ),
        length_m=parameters.length_m if parameters is not None else None,
        roadbed_width_m=parameters.roadbed_width_m if parameters is not None else None,
        pavement_width_m=parameters.pavement_width_m if parameters is not None else None,
        connects=connects,
        alignment_refs=(
            list(parameters.alignment_refs) if parameters is not None else []
        ),
        source_project_id=intervention.intervention_id,
        classification_decision=intervention.classification_decision,
        claim_refs=list(intervention.claim_refs),
        semantic=_semantic(intervention),
    )


def _to_axis_target(intervention: PlanningIntervention) -> AxisTarget:
    parameters = intervention.axis_parameters
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
        if category == "project":
            intent.project_targets.append(_to_project_target(intervention, index))
        elif category == "facility":
            intent.facilities.append(_to_facility_target(intervention))
        elif category == "road":
            intent.road_targets.append(_to_road_target(intervention))
        elif category == "axis":
            intent.development_axes.append(_to_axis_target(intervention))
        elif category in ("restoration", "protection"):
            intent.project_targets.append(_to_project_target(intervention, index))
        elif category == "zone":
            if intervention.materialization_role == "land_use_assignment":
                intent.zone_targets.append(_to_zone_target(intervention))
            else:
                intent.project_targets.append(_to_project_target(intervention, index))
        else:
            intent.project_targets.append(_to_project_target(intervention, index))
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
        if intervention.category == "road" and intervention.road_parameters is None:
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"road-semantics-{intervention.target_id}",
                    severity="error",
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
                    severity="error",
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
                    severity="error",
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
                    severity="error",
                    code="ZONE_MATERIALIZATION_UNRESOLVED",
                    message="Zone versus overlay materialization was not resolved in L3",
                    field_path="materialization_role",
                    target_id=intervention.target_id,
                )
            )
        if (
            intervention.category == "project"
            and intervention.expected_output_kind in {"parcel", "polygon"}
            and intervention.materialization_role != "project_footprint"
        ):
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"project-role-{intervention.target_id}",
                    severity="error",
                    code="PROJECT_MATERIALIZATION_UNRESOLVED",
                    message="Spatial project footprint semantics were not resolved in L3",
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
) -> tuple[IntentCompilationResult, list, list[ParseDiagnostic]]:
    """Deterministically extract a compile result from an L3 PlanningProgram.

    No LLM calls. Returns (IntentCompilationResult, SpatialReferenceSpec[], diagnostics).
    """
    intent = _build_intent(program)
    specs, spec_diags = map_interventions_to_specs(program.interventions)
    diagnostics = _build_diagnostics(program, spec_diags)

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
        typed_intent=intent,
        spatial_reference_specs=specs,
        diagnostics=diagnostics,
        compilation_status=CompilationStatus.DRAFT,
        provenance=provenance,
    )
    return result, specs, diagnostics
