from app.contracts.domain.l3_contracts import (
    PlanningIntervention,
    PlanningProgram,
    RoadPlanningParameters,
)
from app.contracts.domain.planning_semantics import PolygonPlanningParameters
from app.contracts.program import PlanningClaim
from app.domain.program.target_projection.aggregate import project_program
from app.domain.program.target_projection.compile import compile_program_deterministic
from app.contracts.workflow.parse_result_contracts import (
    CompilationStatus,
    IntentCompilationResult,
    ParseDiagnostic,
)
from app.contracts.workflow.parse_contracts import SiteAreaTarget, SpatialPlanningIntent
from app.domain.program.target_projection.gate import evaluate_target_projection_gate


def _intervention(
    target_id: str,
    *,
    category: str,
    output: str,
    role: str | None = None,
) -> PlanningIntervention:
    polygon_parameters = (
        PolygonPlanningParameters(materialization_role=role or "functional_overlay")
        if category in {"protection", "restoration", "zone"}
        else None
    )
    return PlanningIntervention(
        intervention_id=target_id,
        target_id=target_id,
        name=target_id,
        planning_role="spatial_intervention",
        project_package_ref=f"pkg-{target_id}",
        admission_reason="typed_spatial_claim_ready",
        category=category,
        asset_kind="road" if category == "road" else "none",
        execution_mode="spatial",
        expected_output_kind=output,
        claim_refs=[f"claim-{target_id}"],
        evidence_refs=[f"fact-{target_id}"],
        materialization_role=role,
        road_parameters=RoadPlanningParameters() if category == "road" else None,
        polygon_parameters=polygon_parameters,
    )


def _claim_for(intervention: PlanningIntervention) -> PlanningClaim:
    return PlanningClaim(
        claim_id=intervention.claim_refs[0],
        statement=intervention.name,
        suggested_category=intervention.category,
        suggested_output_kind=intervention.expected_output_kind,
        asset_kind=intervention.asset_kind,
        planning_role="spatial_intervention",
        project_package_ref=intervention.project_package_ref,
        materialization_role=intervention.materialization_role,
        location_hints=["社前村"],
        evidence_refs=list(intervention.evidence_refs),
        road_parameters=intervention.road_parameters,
        linear_parameters=intervention.linear_parameters,
        facility_parameters=intervention.facility_parameters,
        polygon_parameters=intervention.polygon_parameters,
    )


def _program(*interventions: PlanningIntervention) -> PlanningProgram:
    return PlanningProgram(
        interventions=list(interventions),
        claims=[_claim_for(item) for item in interventions],
    )


def test_projection_never_reinterprets_road_length_as_width() -> None:
    road = _intervention("road-1", category="road", output="line")
    road.scale = "16 km"
    road.problem_addressed = "道路升级16公里"

    result, _, diagnostics = compile_program_deterministic(
        _program(road)
    )

    assert result.typed_intent.road_targets == []
    assert any(item.code == "INTERVENTION_ADMISSION_RECOMPUTE_FAILED" for item in diagnostics)


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
        _program(road)
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
        _program(protection, restoration, land_use)
    )

    assert [item.target_id for item in result.typed_intent.zone_targets] == ["zone-1"]
    assert [item.target_id for item in result.typed_intent.project_targets] == [
        "protect-1",
        "restore-1",
    ]
    assert result.typed_intent.project_targets[0].materialization_role == "protection_overlay"
    assert result.typed_intent.project_targets[1].materialization_role == "restoration_overlay"


def test_projection_gate_defers_unresolved_semantics() -> None:
    """Admission failures stop before GROUND at the HUMAN boundary."""
    road = _intervention("road-1", category="road", output="line")

    result, _, gate = project_program(_program(road))

    # Missing typed readiness is fail-closed at TARGET_PROJECTION.
    assert result.typed_intent.road_targets == []
    assert any(item.severity == "error" for item in result.diagnostics)
    assert gate.feedback_route == "HUMAN"
    assert gate.route_reason == "target_projection_admission_error"


def test_projection_needs_review_routes_human_before_grounding() -> None:
    result = IntentCompilationResult(
        typed_intent=SpatialPlanningIntent(
            site_area_targets=[
                SiteAreaTarget(target_id="site-1", site_area_id="site-1", name="滨河修复")
            ]
        ),
        compilation_status=CompilationStatus.NEEDS_REVIEW,
        diagnostics=[
            ParseDiagnostic(
                severity="warning",
                code="UNSUPPORTED_SPATIAL_REFERENCE",
                message="GROUND must resolve the semantic label",
            )
        ],
    )

    gate = evaluate_target_projection_gate(result)

    assert gate.passed is False
    assert gate.feedback_route == "HUMAN"
    assert gate.route_reason == "target_projection_needs_review"


def test_projection_warning_only_remains_non_blocking_when_explicitly_draft() -> None:
    result = IntentCompilationResult(
        typed_intent=SpatialPlanningIntent(
            site_area_targets=[
                SiteAreaTarget(target_id="site-1", site_area_id="site-1", name="滨河修复")
            ]
        ),
        compilation_status=CompilationStatus.DRAFT,
        diagnostics=[
            ParseDiagnostic(
                severity="warning",
                code="UNSUPPORTED_SPATIAL_REFERENCE",
                message="GROUND may resolve the semantic label",
            )
        ],
    )

    gate = evaluate_target_projection_gate(result)

    assert gate.passed is True
    assert gate.feedback_route is None


def test_projection_admission_error_routes_human_before_grounding() -> None:
    result = IntentCompilationResult(
        typed_intent=SpatialPlanningIntent(
            site_area_targets=[
                SiteAreaTarget(target_id="site-1", site_area_id="site-1", name="滨河修复")
            ]
        ),
        diagnostics=[
            ParseDiagnostic(
                severity="error",
                code="INTERVENTION_ADMISSION_RECOMPUTE_FAILED",
                message="admission lineage no longer matches the claim",
            )
        ],
    )

    gate = evaluate_target_projection_gate(result)

    assert gate.passed is False
    assert gate.feedback_route == "HUMAN"
    assert gate.route_reason == "target_projection_admission_error"


def test_projection_non_admission_error_keeps_l3_rework_route() -> None:
    result = IntentCompilationResult(
        typed_intent=SpatialPlanningIntent(
            site_area_targets=[
                SiteAreaTarget(target_id="site-1", site_area_id="site-1", name="滨河修复")
            ]
        ),
        diagnostics=[
            ParseDiagnostic(
                severity="error",
                code="SOURCE_SEMANTIC_SNAPSHOT_MISMATCH",
                message="source semantic snapshot is stale",
            )
        ],
    )

    gate = evaluate_target_projection_gate(result)

    assert gate.passed is False
    assert gate.feedback_route == "L3"
    assert gate.route_reason == "target_projection_semantic_error"
