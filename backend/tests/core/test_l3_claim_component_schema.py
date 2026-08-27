from __future__ import annotations

import json

from app.domain.program.claim_draft import (
    L3RoughClaimOutput,
    PlanningClaimDraftSet,
    rough_claim_to_planning_claim_draft,
    normalize_claim_draft_set,
)
from app.domain.program.worker import (
    _normalize_claim_components,
    _sanitize_l3_provider_component,
)
from app.infrastructure.llm.planning_claims import _dynamic_claim_output_model


def test_provider_schema_is_the_small_non_executable_wire_shape() -> None:
    schema = L3RoughClaimOutput.model_json_schema()
    item_schema = schema["$defs"]["L3RoughClaimDraft"]
    properties = set(item_schema["properties"])

    assert properties == {
        "claim_family",
        "statement",
        "planning_role",
        "location_hints",
        "constraint_refs",
        "objective_refs",
        "evidence_refs",
        "source_fact_refs",
        "grounding_requirements",
        "uncertainty",
    }
    assert not properties.intersection({
        "claim_id",
        "project_package_ref",
        "facility_parameters",
        "road_parameters",
        "spatial_requirements",
        "relations",
        "geometry",
        "quantity",
    })
    assert len(json.dumps(schema, ensure_ascii=False)) < 2400


def test_provider_envelope_decodes_stringified_lists() -> None:
    output = L3RoughClaimOutput.model_validate({
        "claims": json.dumps([{
            "claim_family": "facility",
            "statement": "完善公共服务方向",
            "source_fact_refs": ["l1:fact:facility"],
            "grounding_requirements": ["candidate_geometry"],
        }], ensure_ascii=False),
    })

    assert output.claims[0].claim_family == "facility"
    assert output.claims[0].source_fact_refs == ["l1:fact:facility"]


def test_provider_envelope_quarantines_non_object_items_and_keeps_peers() -> None:
    output = L3RoughClaimOutput.model_validate({
        "claims": [
            {"claim_family": "objective", "statement": "提升服务"},
            "malformed item",
            {"claim_family": "action", "statement": "改善环境"},
        ],
    })

    assert [claim.statement for claim in output.claims] == ["提升服务", "改善环境"]
    assert any("indexes=1" in item for item in output.diagnostics)


def test_dynamic_provider_model_is_stable_and_ignores_vendor_extra_fields() -> None:
    first = _dynamic_claim_output_model(["l1:fact:first"], [])
    second = _dynamic_claim_output_model(["l1:fact:second"], ["l1:fact:second"])

    assert first is L3RoughClaimOutput
    assert second is first
    output = first.model_validate({
        "claims": [{
            "claim_family": "objective",
            "statement": "提升公共服务可达性",
            "provider_trace": {"ignored": True},
            "facility_parameters": {"must_not_become_domain_input": True},
        }],
    })
    assert not hasattr(output.claims[0], "provider_trace")
    assert not hasattr(output.claims[0], "facility_parameters")


def test_worker_closes_fact_refs_and_grounding_requirements() -> None:
    model = _dynamic_claim_output_model(
        ["l1:fact:facility", "l1:fact:background"],
        ["l1:fact:facility"],
    )
    output = model.model_validate({"claims": [{
        "claim_family": "facility",
        "statement": "完善公共服务方向",
        "source_fact_refs": ["l1:fact:facility", "l1:fact:invented"],
        "grounding_requirements": ["candidate_geometry", "not_configured"],
    }]})

    sanitized, diagnostics = _sanitize_l3_provider_component(
        output.claims[0],
        source_fact_ids=("l1:fact:facility", "l1:fact:background"),
        spatial_source_fact_ids=("l1:fact:facility",),
        allowed_claim_families={"facility"},
        allowed_grounding_requirements={"candidate_geometry"},
    )

    assert sanitized is not None
    assert sanitized["source_fact_refs"] == ["l1:fact:facility"]
    assert sanitized["grounding_requirements"] == ["candidate_geometry"]
    assert any("l3_source_fact_closed_set" in item for item in diagnostics)
    assert any("l3_grounding_requirement_closed_set" in item for item in diagnostics)


def test_unknown_claim_family_is_quarantined_without_rewriting_it() -> None:
    output = L3RoughClaimOutput.model_validate({"claims": [{
        "claim_family": "made_up_family",
        "statement": "不应进入领域主张",
    }]})

    sanitized, diagnostics = _sanitize_l3_provider_component(
        output.claims[0],
        source_fact_ids=(),
        spatial_source_fact_ids=(),
        allowed_claim_families={"objective"},
    )

    assert sanitized is None
    assert any("l3_claim_family_closed_set" in item for item in diagnostics)


def test_component_adapter_generates_stable_id_and_keeps_rough_spatial_claim_pending() -> None:
    component = {
        "claim_family": "facility",
        "statement": "完善公共服务方向",
        "planning_role": "spatial_intervention",
        "source_fact_refs": ["l1:fact:facility"],
        "grounding_requirements": ["candidate_geometry"],
    }

    first = rough_claim_to_planning_claim_draft(component, dimension_key="public_service")
    second = rough_claim_to_planning_claim_draft(component, dimension_key="public_service")

    assert first.claim_id == second.claim_id
    assert first.claim_id.startswith("public_service:intent:")
    assert first.suggested_category == "facility"
    assert first.facility_parameters is None

    _, claim_set = _normalize_claim_components(
        dimension_key="public_service",
        output=L3RoughClaimOutput.model_validate({"claims": [component]}),
        source_fact_ids=("l1:fact:facility",),
        spatial_source_fact_ids=("l1:fact:facility",),
    )
    from app.domain.program.claim_adapter import classify_claims

    _, pending, dispositions, _issues = classify_claims(
        claim_set.claims,
        dimension_key="public_service",
    )
    assert len(pending) == 1
    assert dispositions[0].status == "pending_grounding"


def test_rough_road_claim_is_preserved_without_typed_parameters() -> None:
    component = rough_claim_to_planning_claim_draft(
        {
            "claim_family": "road",
            "statement": "改善村道通行条件",
            "planning_role": "spatial_intervention",
            "source_fact_refs": ["fact:road"],
            "grounding_requirements": ["network_snapshot"],
        },
        dimension_key="traffic",
    )

    claim_set = normalize_claim_draft_set(
        PlanningClaimDraftSet(claims=[component]),
        dimension_key="traffic",
    )

    assert len(claim_set.claims) == 1
    assert claim_set.claims[0].road_parameters is None
