"""Location evidence must survive the claim-to-grounding boundary."""

from app.contracts.program import PlanningClaim
from app.contracts.domain.planning_semantics import FacilityPlanningParameters
from app.domain.program.assembler import assemble_planning_program
from app.domain.program.claim_adapter import proposals_from_claims
from app.domain.program.target_projection.compile import compile_program_deterministic


def test_claim_location_hints_become_a_closed_set_spatial_reference():
    claim = PlanningClaim(
        claim_id="facility-1",
        dimension_key="public_service",
        statement="Add a small service facility.",
        suggested_category="facility",
        suggested_output_kind="point",
        location_hints=["园寨", "黄竹"],
        facility_parameters=FacilityPlanningParameters(
            facility_type="service facility",
            action="new",
        ),
    )
    proposal = proposals_from_claims([claim], dimension_key="public_service")[0]
    program = assemble_planning_program([proposal], [], claims=[claim])
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
