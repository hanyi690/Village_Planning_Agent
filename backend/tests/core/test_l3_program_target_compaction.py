from app.contracts.domain.l3_contracts import (
    InterventionDependency,
    L3ProgramFragment,
    PlanningProgram,
    ProgramIssue,
)
from app.contracts.domain.planning_semantics import (
    FacilityPlanningParameters,
    PolygonPlanningParameters,
    LinearAssetPlanningParameters,
    RoadPlanningParameters,
)
from app.contracts.program import PlanningClaim, PlanningRelationRequirement, PlanningSpatialRequirements
from app.domain.program.aggregate import merge_program_fragments
from app.contracts.domain.l3_contracts import PlanningIntervention
from app.domain.program.gate import evaluate_l3_gate
from app.domain.program.target_projection.compile import compile_program_deterministic
from app.domain.program.claim_adapter import (
    canonical_package_intervention_id,
    interventions_from_claims,
)


def _claim(claim_id, dimension, package, evidence):
    return PlanningClaim(
        claim_id=claim_id,
        dimension_key=dimension,
        statement=f"{dimension} 维护文化设施",
        suggested_category="facility",
        suggested_output_kind="point",
        asset_kind="facility",
        planning_role="spatial_intervention",
        project_package_ref=package,
        location_hints=["社前村"],
        evidence_refs=[evidence],
        constraint_refs=[f"constraint:{claim_id}"],
        objective_refs=[f"objective:{claim_id}"],
        facility_parameters=FacilityPlanningParameters(
            facility_type="文化设施",
            action="preserve",
        ),
    )


def test_cross_dimension_package_members_compact_deterministically():
    first = L3ProgramFragment(
        dimension_key="public_service",
        claims=[_claim("a", "public_service", "pkg-cultural", "fact-a")],
    )
    second = L3ProgramFragment(
        dimension_key="culture",
        claims=[_claim("b", "culture", "pkg-cultural", "fact-b")],
    )
    program = merge_program_fragments([second, first], run_id="run-1")
    assert len(program.interventions) == 1
    intervention = program.interventions[0]
    assert intervention.project_package_ref == "pkg-cultural"
    assert intervention.claim_refs == ["a", "b"]
    assert intervention.evidence_refs == ["fact-a", "fact-b"]
    assert intervention.objective_refs == ["objective:a", "objective:b"]
    assert intervention.constraints == ["constraint:a", "constraint:b"]


def test_compaction_rewrites_package_relation_endpoints_and_merges_members():
    first = _claim("a", "public_service", "pkg-cultural", "fact-a").model_copy(
        update={
            "spatial_requirements": PlanningSpatialRequirements(
                relations=[
                    PlanningRelationRequirement(
                        relation_id="co-locate-cultural",
                        relation_template="co_locate",
                        subject_ref="pkg-cultural",
                        object_ref="b",
                        object_ref_kind="entity",
                        parameters={"max_distance_m": 100},
                    )
                ]
            )
        }
    )
    second = _claim("b", "culture", "pkg-cultural", "fact-b")

    program = merge_program_fragments(
        [
            L3ProgramFragment(dimension_key="culture", claims=[second]),
            L3ProgramFragment(dimension_key="public_service", claims=[first]),
        ],
        run_id="run-relation-compaction",
    )

    assert len(program.interventions) == 1
    target_id = program.interventions[0].target_id
    relations = program.interventions[0].spatial_requirements["relations"]
    assert len(relations) == 1
    assert relations[0]["subject_ref"] == target_id
    assert relations[0]["object_ref"] == target_id
    assert relations[0]["object_ref_kind"] == "target"


def test_duplicate_claim_id_is_accounted_once_and_marked_merged():
    claim = _claim("same", "public_service", "pkg-cultural", "fact-a")
    duplicate = claim.model_copy(update={"dimension_key": "culture"})
    program = merge_program_fragments(
        [
            L3ProgramFragment(dimension_key="public_service", claims=[claim]),
            L3ProgramFragment(dimension_key="culture", claims=[duplicate]),
        ],
        run_id="run-duplicate",
    )

    assert [item.claim_id for item in program.claims] == ["same"]
    assert len(program.claim_dispositions) == 1
    assert program.claim_dispositions[0].status == "merged_duplicate"
    assert any(issue.code == "duplicate_claim_id" for issue in program.program_issues)
    assert "duplicate_claim:same:culture" in program.omissions


def test_conflicting_duplicate_claim_id_is_not_silently_dropped():
    first = _claim("same", "public_service", "pkg-cultural", "fact-a")
    second = _claim("same", "culture", "pkg-other", "fact-b")
    program = merge_program_fragments(
        [
            L3ProgramFragment(dimension_key="public_service", claims=[first]),
            L3ProgramFragment(dimension_key="culture", claims=[second]),
        ],
        run_id="run-conflict-duplicate",
    )

    assert len(program.claim_dispositions) == 1
    assert program.claim_dispositions[0].status == "merged_duplicate"
    assert any(
        issue.code == "conflicting_duplicate_claim_id"
        and issue.severity == "error"
        for issue in program.program_issues
    )


def test_incompatible_package_members_are_split_with_issue():
    point = _claim("point", "public_service", "pkg-mixed", "fact-point")
    polygon = PlanningClaim(
        claim_id="polygon",
        dimension_key="ecology",
        statement="生态功能区",
        suggested_category="zone",
        suggested_output_kind="polygon",
        asset_kind="land_use",
        planning_role="spatial_intervention",
        project_package_ref="pkg-mixed",
        location_hints=["社前村"],
        evidence_refs=["fact-polygon"],
        materialization_role="functional_overlay",
        polygon_parameters=PolygonPlanningParameters(
            materialization_role="functional_overlay",
        ),
    )
    # Both members are executable, but incompatible geometry must stay split.
    program = merge_program_fragments(
        [
            L3ProgramFragment(dimension_key="public_service", claims=[point]),
            L3ProgramFragment(dimension_key="ecology", claims=[polygon]),
        ],
        run_id="run-1",
    )
    assert len(program.interventions) == 2
    assert any(issue.code == "package_requires_split" for issue in program.program_issues)


def test_claim_only_program_has_distinct_zero_spatial_gate_route():
    claim = _claim("observation", "ecology", "pkg-observation", "fact-observation").model_copy(
        update={"planning_role": "indicator"}
    )
    decision = evaluate_l3_gate(PlanningProgram(claims=[claim]))
    assert decision.feedback_route == "HUMAN"
    assert decision.route_reason == "zero_spatial_interventions"


def test_unresolved_admission_issue_routes_back_to_l3():
    claim = _claim("incomplete", "ecology", "pkg-incomplete", "fact-incomplete")
    program = PlanningProgram(
        claims=[claim],
        program_issues=[
            ProgramIssue(
                dimension_key="ecology",
                claim_id="incomplete",
                severity="error",
                code="claim_admission_incomplete",
                reason="typed parameter block is missing",
            )
        ],
    )
    decision = evaluate_l3_gate(program)
    assert decision.feedback_route == "L3"
    assert decision.pending_requests[0].context["claim_id"] == "incomplete"


def test_diagnostic_only_admission_issue_does_not_block_admitted_subset():
    claim = _claim("valid", "public_service", "pkg-valid", "fact-valid")
    program = PlanningProgram(
        claims=[claim],
        interventions=interventions_from_claims([claim]),
        program_issues=[
            ProgramIssue(
                dimension_key="public_service",
                claim_id="incomplete",
                severity="error",
                code="claim_admission_incomplete",
                reason="evidence/source-fact lineage is missing",
            )
        ],
    )
    decision = evaluate_l3_gate(program)
    assert decision.passed is True


def test_variant_matrix_keeps_linear_asset_ids_distinct_and_order_independent():
    road = PlanningClaim(
        claim_id="road",
        dimension_key="traffic",
        statement="道路硬化",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        planning_role="spatial_intervention",
        project_package_ref="pkg-linear",
        location_hints=["主路"],
        evidence_refs=["fact-road"],
        road_parameters=RoadPlanningParameters(action="harden", length_m=100),
    )
    water = PlanningClaim(
        claim_id="water",
        dimension_key="water",
        statement="供水管线",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="water_supply",
        planning_role="spatial_intervention",
        project_package_ref="pkg-linear",
        location_hints=["主路"],
        evidence_refs=["fact-water"],
        linear_parameters=LinearAssetPlanningParameters(
            action="new",
            length_m=100,
        ),
    )
    first = merge_program_fragments(
        [
            L3ProgramFragment(dimension_key="traffic", claims=[road]),
            L3ProgramFragment(dimension_key="water", claims=[water]),
        ],
        run_id="run-1",
    )
    second = merge_program_fragments(
        [
            L3ProgramFragment(dimension_key="water", claims=[water]),
            L3ProgramFragment(dimension_key="traffic", claims=[road]),
        ],
        run_id="run-1",
    )
    first_ids = sorted(item.intervention_id for item in first.interventions)
    second_ids = sorted(item.intervention_id for item in second.interventions)
    assert first_ids == second_ids
    assert len(first_ids) == 2
    assert len(set(first_ids)) == 2
    assert any(issue.code == "package_requires_split" for issue in first.program_issues)
    split = next(issue for issue in first.program_issues if issue.code == "package_requires_split")
    assert split.claim_ids == ["road", "water"]


def test_zone_materialization_variants_keep_distinct_ids():
    claims = []
    for claim_id, role in (("land", "land_use_assignment"), ("overlay", "functional_overlay")):
        claims.append(
            PlanningClaim(
                claim_id=claim_id,
                dimension_key="land_use",
                statement=claim_id,
                suggested_category="zone",
                suggested_output_kind="polygon",
                asset_kind="land_use",
                planning_role="spatial_intervention",
                project_package_ref="pkg-zone",
                materialization_role=role,
                location_hints=["社前村"],
                evidence_refs=[f"fact-{claim_id}"],
                polygon_parameters=PolygonPlanningParameters(
                    materialization_role=role,
                ),
            )
        )
    program = merge_program_fragments(
        [L3ProgramFragment(dimension_key="land_use", claims=claims)],
        run_id="run-1",
    )
    assert len(program.interventions) == 2
    assert len({item.intervention_id for item in program.interventions}) == 2


def test_direct_fragment_interventions_are_diagnostic_only():
    direct = PlanningIntervention(
        intervention_id="legacy-direct",
        name="legacy",
        execution_mode="spatial",
        expected_output_kind="point",
        category="facility",
    )
    program = merge_program_fragments(
        [L3ProgramFragment(dimension_key="public_service", interventions=[direct])],
        run_id="run-1",
    )
    assert program.interventions == []
    assert any(issue.code == "direct_intervention_not_admitted" for issue in program.program_issues)


def test_direct_intervention_does_not_suppress_valid_claim_admission():
    direct = PlanningIntervention(
        intervention_id="legacy-direct-mixed",
        name="legacy",
        execution_mode="spatial",
        expected_output_kind="point",
        category="facility",
    )
    claim = _claim("valid", "public_service", "pkg-valid", "fact-valid")
    program = merge_program_fragments(
        [
            L3ProgramFragment(
                dimension_key="public_service",
                interventions=[direct],
                claims=[claim],
            )
        ],
        run_id="run-1",
    )
    assert len(program.interventions) == 1
    assert program.interventions[0].claim_refs == ["valid"]
    assert any(issue.code == "direct_intervention_not_admitted" for issue in program.program_issues)


def test_direct_program_interventions_cannot_reach_target_projection():
    direct = PlanningIntervention(
        intervention_id="legacy-direct-projection",
        name="legacy",
        execution_mode="spatial",
        expected_output_kind="point",
        category="facility",
    )
    result, _, diagnostics = compile_program_deterministic(
        PlanningProgram(interventions=[direct])
    )
    assert result.typed_intent.facilities == []
    assert any(item.code == "INTERVENTION_NOT_ADMITTED" for item in diagnostics)


def test_dependency_endpoints_remap_after_compatible_package_compaction():
    first_claim = _claim("a", "public_service", "pkg-dependency", "fact-a")
    second_claim = _claim("b", "culture", "pkg-dependency", "fact-b")
    first = L3ProgramFragment(
        dimension_key="public_service",
        claims=[first_claim],
        dependencies=[
            InterventionDependency(
                from_intervention_id="culture:claim:b",
                to_intervention_id="public_service:claim:a",
                dependency_type="supports",
            )
        ],
    )
    second = L3ProgramFragment(dimension_key="culture", claims=[second_claim])
    forward = merge_program_fragments([first, second], run_id="run-1")
    reverse = merge_program_fragments([second, first], run_id="run-1")
    expected = canonical_package_intervention_id(
        "pkg-dependency",
        "facility",
        "point",
        "facility",
        "",
    )
    assert [(item.from_intervention_id, item.to_intervention_id) for item in forward.dependencies] == [
        (expected, expected)
    ]
    assert [item.model_dump() for item in forward.dependencies] == [
        item.model_dump() for item in reverse.dependencies
    ]
