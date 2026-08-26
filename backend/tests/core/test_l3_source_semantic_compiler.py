import pytest
from pydantic import ValidationError

from app.domain.program.assembler import assemble_planning_program
from app.domain.program.claim_adapter import interventions_from_claims
from app.domain.program.claim_draft import (
    PlanningClaimDraft,
    PlanningClaimDraftSet,
    claim_set_semantic_errors,
    normalize_claim_draft_set,
)


def test_road_dimensions_are_extracted_at_claim_source_and_normalized_to_metres() -> None:
    draft = PlanningClaimDraft(
        claim_id="TR002",
        statement="Y122乡道路基宽7.5米、路面宽6米，全长8公里。",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        location_hints=["Y122乡道村内段"],
        road_parameters={
            "action": "upgrade",
            "road_level": "三级公路",
            "length": {"value": 8, "unit": "km"},
            "roadbed_width": {"value": 7.5, "unit": "m"},
            "pavement_width": {"value": 6, "unit": "m"},
            "alignment_refs": ["Y122乡道"],
            "connects": [],
        },
    )

    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[draft]),
        dimension_key="traffic_planning",
    )
    road = claim_set.claims[0].road_parameters

    assert road is not None
    assert road.length_m == 8000
    assert road.roadbed_width_m == 7.5
    assert road.pavement_width_m == 6
    assert road.alignment_refs == ["Y122乡道"]
    assert claim_set_semantic_errors(claim_set) == []


def test_source_compiler_rejects_kilometres_used_as_road_width() -> None:
    draft = PlanningClaimDraft(
        claim_id="TR002",
        statement="全长8公里，路面宽6米。",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        location_hints=["Y122乡道"],
        road_parameters={
            "action": "upgrade",
            "length": {"value": 8, "unit": "km"},
            "pavement_width": {"value": 8, "unit": "km"},
            "alignment_refs": ["Y122乡道"],
        },
    )

    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[draft]),
        dimension_key="traffic_planning",
    )

    assert claim_set.claims == []
    assert any("invalid_road_parameters" in item for item in claim_set.diagnostics)
    assert any("claim_contract_invalid" in item for item in claim_set.diagnostics)
    assert any("claim_contract_invalid" in item for item in claim_set_semantic_errors(claim_set))


def test_utility_pipe_diameter_is_not_treated_as_pavement_width() -> None:
    draft = PlanningClaimDraft(
        claim_id="INF-PIPE-1",
        statement="更新供水管道，主管管径DN100，总长度6公里。",
        suggested_category="road",
        suggested_output_kind="line",
        location_hints=["12个自然村"],
        asset_kind="water_supply",
        linear_parameters={
            "action": "upgrade",
            "length": {"value": 6, "unit": "km"},
            "diameter": {"value": 100, "unit": "mm"},
        },
    )

    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[draft]),
        dimension_key="project_bank",
    )

    linear = claim_set.claims[0].linear_parameters
    assert linear is not None
    assert linear.length_m == 6000
    assert linear.diameter_mm == 100
    assert claim_set.claims[0].road_parameters is None
    assert claim_set_semantic_errors(claim_set) == []


def test_utility_detection_survives_repair_normalizing_road_level() -> None:
    draft = PlanningClaimDraft(
        claim_id="INF-PIPE-2",
        statement="新建污水管道管径DN300，总长度8公里。",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="sewer",
        linear_parameters={
            "action": "new",
            "length": {"value": 8, "unit": "km"},
            "diameter": {"value": 300, "unit": "mm"},
        },
    )

    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[draft]),
        dimension_key="project_bank",
    )

    assert claim_set.claims[0].linear_parameters is not None
    assert claim_set.claims[0].linear_parameters.diameter_mm == 300
    assert claim_set.claims[0].road_parameters is None
    assert claim_set_semantic_errors(claim_set) == []


def test_drainage_channel_dimensions_are_not_treated_as_road_width() -> None:
    draft = PlanningClaimDraft(
        claim_id="DM-DRAIN-1",
        statement="沿滑坡点布设截排水沟，沟底宽度0.6米、深度0.5米，总长3500米。",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="drainage_channel",
        linear_parameters={
            "action": "new",
            "length": {"value": 3500, "unit": "m"},
        },
    )

    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[draft]),
        dimension_key="disaster_prevention",
    )

    assert claim_set.claims[0].linear_parameters is not None
    assert claim_set.claims[0].linear_parameters.length_m == 3500
    assert claim_set.claims[0].road_parameters is None
    assert claim_set_semantic_errors(claim_set) == []


def test_facility_axis_and_zone_keep_their_own_typed_semantics() -> None:
    drafts = [
        PlanningClaimDraft(
            claim_id="FAC-1",
            statement="新建卫生站，服务半径300米。",
            suggested_category="facility",
            suggested_output_kind="point",
            location_hints=["村委会东侧"],
            facility_parameters={
                "facility_type": "卫生站",
                "action": "new",
                "service_radius": {"value": 300, "unit": "m"},
                "footprint_area": {"value": 600, "unit": "m2"},
            },
        ),
        PlanningClaimDraft(
            claim_id="AXIS-1",
            statement="形成沿Y122乡道的东西向发展轴。",
            suggested_category="axis",
            suggested_output_kind="line",
            axis_parameters={
                "action": "new",
                "axis_type": "primary",
                "direction": "east-west",
                "reference_features": ["Y122乡道"],
                "corridor_width": {"value": 50, "unit": "m"},
            },
        ),
        PlanningClaimDraft(
            claim_id="ZONE-1",
            statement="配置2至3公顷产业用地。",
            suggested_category="zone",
            suggested_output_kind="polygon",
            polygon_parameters={
                "materialization_role": "land_use_assignment",
                "planning_zone": "村庄建设区",
                "land_use": "产业用地",
                "area_range": {"minimum": 2, "maximum": 3, "unit": "ha"},
            },
        ),
    ]

    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=drafts),
        dimension_key="spatial_structure",
    )

    assert claim_set_semantic_errors(claim_set) == []
    facility, axis, zone = claim_set.claims
    assert facility.facility_parameters.service_radius_m == 300
    assert facility.facility_parameters.footprint_area_m2 == 600
    assert axis.axis_parameters.reference_features == ["Y122乡道"]
    assert axis.axis_parameters.corridor_width_m == 50
    assert zone.materialization_role == "land_use_assignment"
    assert zone.area_range_ha == (2, 3)


def test_missing_protection_and_restoration_roles_are_not_auto_created() -> None:
    drafts = [
        PlanningClaimDraft(
            claim_id="P-1",
            statement="保护古树群。",
            suggested_category="protection",
            suggested_output_kind="polygon",
        ),
        PlanningClaimDraft(
            claim_id="R-1",
            statement="修复河岸生态。",
            suggested_category="restoration",
            suggested_output_kind="polygon",
        ),
    ]

    claim_set = normalize_claim_draft_set(PlanningClaimDraftSet(claims=drafts))

    assert claim_set.claims[0].materialization_role is None
    assert claim_set.claims[1].materialization_role is None
    assert claim_set_semantic_errors(claim_set) == []


def test_typed_semantics_survive_claim_proposal_program_boundaries() -> None:
    draft = PlanningClaimDraft(
        claim_id="TR003",
        statement="村道硬化8公里，路面宽4.5米。",
        planning_role="spatial_intervention",
        project_package_ref="pkg-tr003",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        location_hints=["纵向村道"],
        evidence_refs=["fact:tr003"],
        road_parameters={
            "action": "harden",
            "length": {"value": 8, "unit": "km"},
            "pavement_width": {"value": 4.5, "unit": "m"},
            "alignment_refs": ["纵向村道"],
        },
    )
    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[draft]),
        dimension_key="traffic_planning",
    )
    interventions = interventions_from_claims(
        claim_set.claims,
        dimension_key="traffic_planning",
    )
    program = assemble_planning_program(interventions, [], claims=claim_set.claims)

    intervention = program.interventions[0]
    assert intervention.intervention_action == "harden"
    assert intervention.road_parameters is not None
    assert intervention.road_parameters.length_m == 8000
    assert intervention.road_parameters.pavement_width_m == 4.5


def test_rejected_claims_are_quarantined_without_local_repair() -> None:
    rejected = PlanningClaimDraft(
        claim_id="ROAD-BAD",
        statement="道路升级。",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
    )
    claim_set = normalize_claim_draft_set(PlanningClaimDraftSet(claims=[rejected]))

    assert claim_set.claims == []
    assert any("claim_contract_invalid" in item for item in claim_set.diagnostics)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("suggested_category", "land_use_zone"),
        ("suggested_output_kind", "road_segment"),
        ("intervention_action", "renovate"),
        ("implementation_phase", "immediate"),
    ],
)
def test_provider_draft_rejects_open_ended_control_vocabulary(
    field: str,
    value: str,
) -> None:
    payload = {
        "claim_id": "STRICT-1",
        "statement": "结构化边界测试",
        field: value,
    }

    with pytest.raises(ValidationError):
        PlanningClaimDraft.model_validate(payload)


def test_square_metre_unicode_unit_is_normalized_at_source_compile() -> None:
    draft = PlanningClaimDraft(
        claim_id="ZONE-M2",
        statement="配置建设用地一万平方米。",
        suggested_category="zone",
        suggested_output_kind="polygon",
        polygon_parameters={
            "materialization_role": "land_use_assignment",
            "planning_zone": "村庄建设区",
            "land_use": "建设用地",
            "area_range": {"minimum": 10000, "maximum": 10000, "unit": "m²"},
        },
    )

    claim_set = normalize_claim_draft_set(PlanningClaimDraftSet(claims=[draft]))

    assert claim_set.claims[0].area_range_ha == (1.0, 1.0)
    assert claim_set_semantic_errors(claim_set) == []


def test_functional_overlay_is_not_compiled_as_land_use_area_assignment() -> None:
    draft = PlanningClaimDraft(
        claim_id="FUNC-1",
        statement="形成一心一带三区产业空间结构。",
        suggested_category="zone",
        suggested_output_kind="polygon",
        polygon_parameters={
            "materialization_role": "functional_overlay",
            "planning_zone": "产业功能结构",
            "land_use": "",
            "area_range": {"minimum": 1, "maximum": 2352.89, "unit": "ha"},
        },
    )

    claim_set = normalize_claim_draft_set(PlanningClaimDraftSet(claims=[draft]))

    assert claim_set.claims[0].materialization_role == "functional_overlay"
    assert claim_set.claims[0].area_range_ha is None
    assert claim_set_semantic_errors(claim_set) == []
    assert any(
        "functional_overlay_area_non_authoritative" in item
        for item in claim_set.diagnostics
    )


@pytest.mark.parametrize(
    ("category", "output", "asset_kind"),
    [
        ("facility", "point", "water_supply"),
        ("site_area", "polygon", "power"),
        ("protection", "polygon", "drainage_channel"),
    ],
)
def test_mismatched_asset_kind_is_quarantined_before_program_assembly(
    category: str,
    output: str,
    asset_kind: str,
) -> None:
    draft = PlanningClaimDraft(
        claim_id="BAD-ASSET-MIX",
        statement="不兼容资产语义",
        planning_role="spatial_intervention",
        suggested_category=category,
        suggested_output_kind=output,
        asset_kind=asset_kind,
        facility_parameters=(
            {"facility_type": "供水设施", "action": "new"}
            if category == "facility"
            else None
        ),
        site_area_parameters=(
            {"site_type": "变压器改造", "action": "new"}
            if category == "site_area"
            else None
        ),
        polygon_parameters=(
            {"materialization_role": "protection_overlay"}
            if category == "protection"
            else None
        ),
    )

    claim_set = normalize_claim_draft_set(PlanningClaimDraftSet(claims=[draft]))

    assert claim_set.claims == []
    assert any("draft_contract_invalid" in item for item in claim_set.diagnostics)


def test_site_area_point_without_typed_footprint_is_quarantined() -> None:
    draft = PlanningClaimDraft(
        claim_id="PROJECT-POINT-1",
        statement="新建综合服务中心，位置在村北入口。",
        suggested_category="site_area",
        suggested_output_kind="point",
        site_area_parameters={"site_type": "综合服务中心", "action": "new"},
    )

    claim_set = normalize_claim_draft_set(PlanningClaimDraftSet(claims=[draft]))

    assert claim_set.claims == []
    assert any("invalid_site_area_output" in item for item in claim_set.diagnostics)
