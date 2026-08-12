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
    return SemanticMetadata(
        natural_language_description=intervention.name,
        spatial_hint=_spatial_hint(intervention),
        raw_text=intervention.name,
    )


def _to_project_target(intervention: PlanningIntervention, index: int) -> ProjectTarget:
    return ProjectTarget(
        target_id=intervention.target_id,
        project_id=intervention.intervention_id,
        name=intervention.name,
        category="other",
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        action="new",
        scale_text=intervention.scale,
        area_ha=intervention.area_range_ha[0] if intervention.area_range_ha else None,
        location_hint=_spatial_hint(intervention),
        source_instruction_id=intervention.intervention_id,
        claim_refs=list(intervention.claim_refs),
        classification_decision=intervention.classification_decision,
        source_section="L3_PROGRAM",
        source_row=index,
        semantic=_semantic(intervention),
    )


def _to_facility_target(intervention: PlanningIntervention) -> FacilityTarget:
    return FacilityTarget(
        target_id=intervention.target_id,
        type=intervention.name,
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        status="planned_new",
        location_hint=_spatial_hint(intervention),
        source_project_id=intervention.intervention_id,
        source_instruction_id=intervention.intervention_id,
        claim_refs=list(intervention.claim_refs),
        classification_decision=intervention.classification_decision,
        direction="center",
        semantic=_semantic(intervention),
    )


def _to_road_target(intervention: PlanningIntervention) -> RoadTarget:
    return RoadTarget(
        target_id=intervention.target_id,
        road_level=intervention.name,
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        width_m=0.0,
        connects=[],
        source_project_id=intervention.intervention_id,
        classification_decision=intervention.classification_decision,
        claim_refs=list(intervention.claim_refs),
        semantic=_semantic(intervention),
    )


def _to_axis_target(intervention: PlanningIntervention) -> AxisTarget:
    return AxisTarget(
        target_id=intervention.target_id,
        label=intervention.name,
        execution_mode=intervention.execution_mode,
        expected_output_kind=intervention.expected_output_kind,
        source_project_id=intervention.intervention_id,
        source_instruction_id=intervention.intervention_id,
        classification_decision=intervention.classification_decision,
        claim_refs=list(intervention.claim_refs),
        semantic=_semantic(intervention),
    )


def _to_zone_target(intervention: PlanningIntervention) -> ZoneTarget:
    return ZoneTarget(
        target_id=intervention.target_id,
        land_use=intervention.functions[0] if intervention.functions else intervention.name,
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
        elif category in ("restoration", "protection", "zone"):
            intent.zone_targets.append(_to_zone_target(intervention))
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
