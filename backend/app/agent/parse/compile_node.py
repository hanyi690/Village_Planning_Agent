"""Top-level PARSE compile node - deterministic extraction from PlanningProgram.

Wave F COMPILE mode core. Consumes L3 PlanningProgram (typed aggregate) and
produces IntentCompilationResult + SpatialReferenceSpec[] + diagnostics.
No LLM calls. Does NOT import the bridge-layer parse agent (bridge isolation).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.modules.parsing.compiler.spec_mapper import (
    map_intervention_to_spec,
    map_interventions_to_specs,
)
from app.modules.schema.contracts.l3_contracts import PlanningIntervention, PlanningProgram
from app.modules.schema.contracts.parse_contracts import (
    FacilityTarget,
    ProjectTarget,
    RoadTarget,
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.modules.schema.contracts.parse_result_contracts import (
    CompilationStatus,
    IntentCompilationResult,
    ParseDiagnostic,
    ParseMode,
    ParseTrace,
    ProjectRequirement,
)
from app.modules.schema.contracts.provenance import Provenance, SemanticMetadata
from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec
from app.modules.schema.contracts.target_binding_contracts import (
    TargetBinding,
    TargetBindingTable,
)


def _spatial_hint(intervention: PlanningIntervention) -> str:
    req = intervention.spatial_requirements
    if isinstance(req, dict):
        return str(req.get("location", ""))
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
        elif category in ("restoration", "protection", "zone"):
            intent.zone_targets.append(_to_zone_target(intervention))
        else:
            intent.project_targets.append(_to_project_target(intervention, index))
    return intent


def _build_project_requirements(
    program: PlanningProgram,
) -> list[ProjectRequirement]:
    requirements: list[ProjectRequirement] = []
    for intervention in program.interventions:
        if intervention.category != "project":
            continue
        requirements.append(
            ProjectRequirement(
                project_ref=intervention.intervention_id,
                area_range=intervention.area_range_ha,
                functions=list(intervention.functions),
                spatial_requirements=dict(intervention.spatial_requirements),
                constraints=list(intervention.constraints),
            )
        )
    return requirements


def _build_diagnostics(
    program: PlanningProgram,
    spec_diags: list[ParseDiagnostic],
) -> list[ParseDiagnostic]:
    diagnostics = list(spec_diags)
    if not program.interventions:
        diagnostics.append(
            ParseDiagnostic(
                diagnostic_id="parse-empty-program",
                severity="warning",
                code="EMPTY_PROGRAM",
                message="PlanningProgram has no interventions",
                field_path="interventions",
            )
        )
    return diagnostics


def _build_target_binding_table(
    program: PlanningProgram,
    specs: list[SpatialReferenceSpec],
) -> TargetBindingTable:
    """Build the authoritative target_id <-> intervention_id <-> spec_id table.

    Links each intervention to its spec by semantic key (spec.target_id ==
    intervention.target_id), never by position. Interventions without a spatial
    spec (non_spatial / skipped by the mapper) still yield a binding with an
    empty spec_id so the target remains traceable end-to-end.
    """
    spec_by_target = {spec.target_id: spec for spec in specs if spec.target_id}
    bindings: list[TargetBinding] = []
    for intervention in program.interventions:
        spec = spec_by_target.get(intervention.target_id)
        bindings.append(
            TargetBinding(
                target_id=intervention.target_id,
                intervention_id=intervention.intervention_id,
                spec_id=spec.spec_id if spec else "",
                project_ref=intervention.intervention_id,
                target_type=intervention.category,
                expected_output_kind=intervention.expected_output_kind,
            )
        )
    return TargetBindingTable(bindings=tuple(bindings))


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
    project_requirements = _build_project_requirements(program)
    specs, spec_diags = map_interventions_to_specs(program.interventions)
    target_binding_table = _build_target_binding_table(program, specs)
    diagnostics = _build_diagnostics(program, spec_diags)

    now = datetime.now(timezone.utc).isoformat()
    trace = ParseTrace(
        mode=ParseMode.COMPILE,
        steps=[
            {
                "step": "deterministic_extract",
                "interventions": len(program.interventions),
                "specs": len(specs),
            },
            {
                "step": "build_intent",
                "project_targets": len(intent.project_targets),
                "facilities": len(intent.facilities),
                "road_targets": len(intent.road_targets),
                "zone_targets": len(intent.zone_targets),
            },
            {
                "step": "build_requirements",
                "project_requirements": len(project_requirements),
            },
        ],
        started_at=now,
        finished_at=now,
    )

    provenance = Provenance(
        source="parse",
        run_id=run_id,
        module="parse",
        trace=[f"compile:{run_id}"],
        natural_language_description=(
            "Deterministic compile of PlanningProgram "
            f"{program.artifact_id or program_ref} into SpatialPlanningIntent"
        ),
    )

    result = IntentCompilationResult(
        program_ref=program_ref or program.artifact_id,
        base_revision_ref="",
        typed_intent=intent,
        project_requirements=project_requirements,
        spatial_reference_specs=specs,
        constraint_set=None,
        diagnostics=diagnostics,
        patches=[],
        target_binding_table=target_binding_table,
        compilation_status=CompilationStatus.DRAFT,
        confidence=0.0,
        provenance=provenance,
        intent=intent,
        compilation_errors=[],
        trace=trace,
    )
    return result, specs, diagnostics
