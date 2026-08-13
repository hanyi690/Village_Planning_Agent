from app.contracts.domain.l3_contracts import (
    PlanningIntervention,
    PlanningProgram,
    RoadPlanningParameters,
)
from app.domain.program.target_projection.aggregate import project_program
from app.domain.program.target_projection.compile import compile_program_deterministic


def _intervention(
    target_id: str,
    *,
    category: str,
    output: str,
    role: str | None = None,
) -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id=target_id,
        target_id=target_id,
        name=target_id,
        category=category,
        execution_mode="spatial",
        expected_output_kind=output,
        materialization_role=role,
    )


def test_projection_never_reinterprets_road_length_as_width() -> None:
    road = _intervention("road-1", category="road", output="line")
    road.scale = "16 km"
    road.problem_addressed = "道路升级16公里"

    result, _, diagnostics = compile_program_deterministic(
        PlanningProgram(interventions=[road])
    )

    assert result.typed_intent.road_targets[0].width_m == 0
    assert any(item.code == "ROAD_SEMANTICS_UNRESOLVED" for item in diagnostics)


def test_projection_consumes_typed_road_dimensions_and_action() -> None:
    road = _intervention("road-1", category="road", output="line")
    road.road_parameters = RoadPlanningParameters(
        action="upgrade",
        road_level="三级公路",
        length_m=8000,
        roadbed_width_m=7.5,
        pavement_width_m=6,
        connects=["Y122乡道"],
    )

    result, _, diagnostics = compile_program_deterministic(
        PlanningProgram(interventions=[road])
    )
    projected = result.typed_intent.road_targets[0]

    assert projected.length_m == 8000
    assert projected.width_m == 6
    assert projected.roadbed_width_m == 7.5
    assert projected.action == "upgrade"
    assert projected.road_planning_kind == "existing_road_intervention"
    assert projected.connects == ["Y122乡道"]
    assert not [item for item in diagnostics if item.severity == "error"]


def test_protection_and_restoration_are_overlays_not_land_use_assignments() -> None:
    protection = _intervention(
        "protect-1",
        category="protection",
        output="polygon",
        role="protection_overlay",
    )
    restoration = _intervention(
        "restore-1",
        category="restoration",
        output="polygon",
        role="restoration_overlay",
    )
    land_use = _intervention(
        "zone-1",
        category="zone",
        output="polygon",
        role="land_use_assignment",
    )

    result, _, _ = compile_program_deterministic(
        PlanningProgram(interventions=[protection, restoration, land_use])
    )

    assert [item.target_id for item in result.typed_intent.zone_targets] == ["zone-1"]
    assert [item.target_id for item in result.typed_intent.project_targets] == [
        "protect-1",
        "restore-1",
    ]
    assert result.typed_intent.project_targets[0].materialization_role == "protection_overlay"
    assert result.typed_intent.project_targets[1].materialization_role == "restoration_overlay"


def test_projection_gate_fails_closed_on_unresolved_l3_semantics() -> None:
    road = _intervention("road-1", category="road", output="line")

    result, _, gate = project_program(PlanningProgram(interventions=[road]))

    assert any(item.severity == "error" for item in result.diagnostics)
    assert gate.passed is False
    assert gate.feedback_route == "L3"
