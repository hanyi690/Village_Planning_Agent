"""Location evidence must survive the claim-to-grounding boundary."""

import pytest
from pydantic import ValidationError

from app.contracts.program import PlanningClaim
from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.domain.planning_semantics import (
    FacilityPlanningParameters,
    SiteAreaPlanningParameters,
)
from app.domain.program.assembler import assemble_planning_program
from app.domain.program.claim_adapter import interventions_from_claims
from app.domain.program.target_projection.compile import compile_program_deterministic
from app.workflow.stages.target_projection import _spatial_spec_village_names


def test_claim_location_hints_become_a_closed_set_spatial_reference():
    claim = PlanningClaim(
        claim_id="facility-1",
        dimension_key="public_service",
        statement="Add a small service facility.",
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility-1",
        suggested_category="facility",
        suggested_output_kind="point",
        location_hints=["园寨", "黄竹"],
        evidence_refs=["fact:facility-1"],
        facility_parameters=FacilityPlanningParameters(
            facility_type="service facility",
            action="new",
        ),
    )
    intervention = interventions_from_claims([claim], dimension_key="public_service")[0]
    program = assemble_planning_program([intervention], [], claims=[claim])
    compilation, specs, diagnostics = compile_program_deterministic(program)

    assert compilation.typed_intent.facilities[0].location_hint == "园寨、黄竹"
    assert len(specs) == 1
    assert specs[0].op == "or"
    assert [child.reference.kind for child in specs[0].children] == [
        "place_name",
        "place_name",
    ]
    assert [
        child.reference.filter["label_contains"] for child in specs[0].children
    ] == ["园寨", "黄竹"]
    assert not diagnostics


def test_typed_facility_hint_keeps_place_and_facility_semantics_conjunctive():
    claim = PlanningClaim(
        claim_id="facility-place-1",
        dimension_key="public_service",
        statement="社前村祠堂维护。",
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility-place-1",
        suggested_category="facility",
        suggested_output_kind="point",
        location_hints=["社前村", "祠堂"],
        evidence_refs=["fact:facility-place-1"],
        facility_parameters=FacilityPlanningParameters(
            facility_type="祠堂",
            action="preserve",
        ),
    )
    intervention = interventions_from_claims([claim], dimension_key="public_service")[0]
    program = assemble_planning_program([intervention], [], claims=[claim])
    compilation, specs, diagnostics = compile_program_deterministic(program)

    assert compilation.typed_intent.facilities[0].location_hint == "社前村、祠堂"
    assert len(specs) == 1
    assert specs[0].op == "and"
    assert specs[0].children[0].reference.filter == {"label_contains": "社前村"}
    assert specs[0].children[1].reference.filter == {"label_contains": "祠堂"}
    assert not diagnostics


def test_projection_source_support_check_ignores_facility_labels():
    claim = PlanningClaim(
        claim_id="facility-place-2",
        dimension_key="public_service",
        statement="社前村祠堂维护。",
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility-place-2",
        suggested_category="facility",
        suggested_output_kind="point",
        location_hints=["社前村", "祠堂"],
        evidence_refs=["fact:facility-place-2"],
        facility_parameters=FacilityPlanningParameters(
            facility_type="祠堂",
            action="preserve",
        ),
    )
    intervention = interventions_from_claims([claim], dimension_key="public_service")[0]
    program = assemble_planning_program([intervention], [], claims=[claim])
    compilation, specs, _ = compile_program_deterministic(program)

    assert _spatial_spec_village_names(specs[0]) == ["社前村"]


def test_facility_point_and_site_area_footprint_are_separate_targets() -> None:
    facility = PlanningIntervention(
        intervention_id="facility-1",
        name="综合服务中心设施节点",
        target_id="facility-1",
        planning_role="spatial_intervention",
        project_package_ref="pkg-facility-1",
        admission_reason="typed_spatial_claim_ready",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        asset_kind="facility",
        facility_parameters=FacilityPlanningParameters(
            facility_type="综合服务中心",
            action="new",
        ),
        claim_refs=["claim-facility-1"],
        evidence_refs=["fact-facility-1"],
    )
    site_area = PlanningIntervention(
        intervention_id="site-area-1",
        name="村民活动场地用地范围",
        target_id="site-area-1",
        category="site_area",
        execution_mode="spatial",
        expected_output_kind="polygon",
        planning_role="spatial_intervention",
        project_package_ref="pkg-site-area-1",
        admission_reason="typed_spatial_claim_ready",
        materialization_role="site_footprint",
        site_area_parameters=SiteAreaPlanningParameters(
            site_type="活动场地",
            footprint_area_m2=1200,
        ),
        claim_refs=["claim-site-area-1"],
        evidence_refs=["fact-site-area-1"],
    )

    claims = [
        PlanningClaim(
            claim_id="claim-facility-1",
            statement=facility.name,
            suggested_category="facility",
            suggested_output_kind="point",
            asset_kind="facility",
            planning_role="spatial_intervention",
            project_package_ref="pkg-facility-1",
            location_hints=["社前村"],
            evidence_refs=["fact-facility-1"],
            facility_parameters=facility.facility_parameters,
        ),
        PlanningClaim(
            claim_id="claim-site-area-1",
            statement=site_area.name,
            suggested_category="site_area",
            suggested_output_kind="polygon",
            planning_role="spatial_intervention",
            project_package_ref="pkg-site-area-1",
            materialization_role="site_footprint",
            location_hints=["社前村"],
            evidence_refs=["fact-site-area-1"],
            site_area_parameters=site_area.site_area_parameters,
        ),
    ]
    program = assemble_planning_program([facility, site_area], [], claims=claims)
    compilation, _, diagnostics = compile_program_deterministic(program)

    assert [item.target_id for item in compilation.typed_intent.facilities] == [
        "facility-1"
    ]
    assert [item.target_id for item in compilation.typed_intent.site_area_targets] == [
        "site-area-1"
    ]
    assert compilation.typed_intent.facilities[0].expected_output_kind == "point"
    assert compilation.typed_intent.site_area_targets[0].expected_output_kind == "polygon"
    assert not [item for item in diagnostics if item.code == "SITE_AREA_MATERIALIZATION_UNRESOLVED"]

    with pytest.raises(ValidationError):
        PlanningIntervention(
            intervention_id="site-area-point-1",
            name="错误的用地范围点位",
            category="site_area",
            execution_mode="spatial",
            expected_output_kind="point",
        )
