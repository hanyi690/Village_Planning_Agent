from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.program.claim_draft import (
    L3ClaimOutput,
    L3ProviderClaimOutput,
    component_to_planning_claim_draft,
)
from app.infrastructure.llm.planning_claims import _dynamic_claim_output_model


def test_l3_provider_schema_is_discriminated_and_componentized() -> None:
    schema = L3ClaimOutput.model_json_schema()
    items = schema["properties"]["claims"]["items"]

    assert items["discriminator"]["propertyName"] == "component_kind"
    assert len(items["oneOf"]) >= 8


def test_facility_component_cannot_expose_linear_parameter_block() -> None:
    with pytest.raises(ValidationError):
        L3ClaimOutput.model_validate({"claims": [{
            "component_kind": "facility",
            "claim_id": "facility-1",
            "statement": "建设服务设施",
            "facility_parameters": {"facility_type": "clinic", "action": "new"},
            "linear_parameters": {"material": "pipe"},
        }]})


def test_legacy_flat_payload_is_rejected_at_the_provider_boundary() -> None:
    with pytest.raises(ValidationError):
        L3ClaimOutput.model_validate({"claims": [{
            "claim_id": "facility-1",
            "statement": "建设服务设施",
            "suggested_category": "facility",
            "suggested_output_kind": "point",
            "facility_parameters": {"facility_type": "clinic"},
        }]})


def test_component_converts_to_the_strict_normalizer_input() -> None:
    output = L3ClaimOutput.model_validate({"claims": [{
        "component_kind": "facility",
        "claim_id": "facility-1",
        "statement": "建设服务设施",
        "intervention_action": "new",
        "facility_parameters": {"facility_type": "clinic", "action": "new"},
    }]})
    draft = component_to_planning_claim_draft(output.claims[0])

    assert draft.suggested_category == "facility"
    assert draft.facility_parameters is not None


def test_linear_component_cannot_select_a_restoration_category() -> None:
    with pytest.raises(ValidationError):
        L3ClaimOutput.model_validate({"claims": [{
            "component_kind": "linear",
            "claim_id": "linear-1",
            "statement": "建设污水管线",
            "suggested_category": "restoration",
            "asset_kind": "sewer",
        }]})


def test_provider_relation_shape_is_structured_and_worker_closes_it() -> None:
    model = _dynamic_claim_output_model(
        ["l1:fact:facility"],
        ["l1:fact:facility"],
    )
    valid = model.model_validate({"claims": [{
        "component_kind": "facility",
        "claim_id": "facility-1",
        "statement": "建设公共服务设施",
        "intervention_action": "new",
        "spatial_requirements": {
            "relations": [{
                "relation_template": "near",
                "object_ref": "现状公共服务点",
                "object_ref_kind": "entity",
                "parameters": {
                    "parameter_type": "distance",
                    "max_distance_m": 100,
                    "metric": "euclidean",
                },
            }],
        },
    }]})

    assert valid.claims[0].spatial_requirements is not None
    assert valid.claims[0].spatial_requirements.relations[0].relation_template == "near"

    invalid = model.model_validate({"claims": [{
        "component_kind": "facility",
        "claim_id": "facility-1",
        "statement": "建设公共服务设施",
        "intervention_action": "new",
        "spatial_requirements": {
            "relations": [{
                "relation_template": "near",
                "object_ref": "target:other",
                "object_ref_kind": "target",
                "parameters": {
                    "parameter_type": "distance",
                    "max_distance_m": 100,
                    "metric": "euclidean",
                },
            }],
        },
    }]})

    from app.domain.program.worker import _sanitize_l3_provider_component

    sanitized, diagnostics = _sanitize_l3_provider_component(
        invalid.claims[0],
        source_fact_ids=("l1:fact:facility",),
        spatial_source_fact_ids=("l1:fact:facility",),
    )
    assert sanitized["spatial_requirements"]["relations"] == []
    assert "candidate_geometry" in sanitized["spatial_requirements"]["grounding_requirements"]
    assert any("l3_relation_closed_set" in item for item in diagnostics)


def test_l3_provider_schema_identity_does_not_change_with_runtime_catalog() -> None:
    first = _dynamic_claim_output_model(["l1:fact:first"], ["l1:fact:first"])
    second = _dynamic_claim_output_model(
        ["l1:fact:second", "l1:fact:third"], ["l1:fact:third"]
    )

    assert first is L3ProviderClaimOutput
    assert second is first




def test_l3_provider_envelope_decodes_stringified_claims_before_domain_projection() -> None:
    output = L3ProviderClaimOutput.model_validate({
        "claims": '[{"component_kind":"facility","claim_id":"f-1",'
        '"statement":"建设设施","intervention_action":"new"}]'
    })

    assert len(output.claims) == 1
    assert output.claims[0].component_kind == "facility"


def test_worker_rejects_parameter_field_name_as_relation_template() -> None:
    model = _dynamic_claim_output_model(
        ["l1:fact:road"],
        ["l1:fact:road"],
    )

    output = model.model_validate({"claims": [{
        "component_kind": "road",
        "claim_id": "road-1",
        "statement": "建设道路",
        "intervention_action": "new",
        "spatial_requirements": {
            "relations": [{
                "relation_template": "connects",
                "object_ref": "村北",
                "object_ref_kind": "place_hint",
            }],
        },
    }]})
    from app.domain.program.worker import _sanitize_l3_provider_component

    sanitized, diagnostics = _sanitize_l3_provider_component(
        output.claims[0],
        source_fact_ids=("l1:fact:road",),
        spatial_source_fact_ids=("l1:fact:road",),
    )
    assert sanitized["spatial_requirements"]["relations"] == []
    assert any("l3_relation_closed_set" in item for item in diagnostics)


def test_empty_dynamic_fact_set_is_closed_after_provider_parse() -> None:
    model = _dynamic_claim_output_model([], [])

    output = model.model_validate({"claims": [{
        "component_kind": "facility",
        "claim_id": "facility-1",
        "statement": "建设设施",
        "intervention_action": "new",
        "source_fact_refs": ["l1:fact:invented"],
    }]})
    from app.domain.program.worker import _sanitize_l3_provider_component

    sanitized, diagnostics = _sanitize_l3_provider_component(
        output.claims[0],
        source_fact_ids=(),
        spatial_source_fact_ids=(),
    )
    assert sanitized["source_fact_refs"] == []
    assert any("l3_source_fact_closed_set" in item for item in diagnostics)


def test_dynamic_provider_wire_accepts_non_spatial_semantic_alias() -> None:
    model = _dynamic_claim_output_model([], [])
    output = model.model_validate({"claims": [{
        "component_kind": "constraint",
        "claim_id": "constraint-1",
        "planning_role": "constraint",
        "statement": "建设活动需要避让生态保护范围",
        "intervention_action": "repair",
        "spatial_requirements": {
            "grounding_requirements": ["candidate_geometry"],
        },
    }]})

    assert output.claims[0].component_kind == "constraint"
    from app.domain.program.worker import _sanitize_l3_provider_component

    sanitized, diagnostics = _sanitize_l3_provider_component(
        output.claims[0],
        source_fact_ids=(),
        spatial_source_fact_ids=(),
    )
    assert sanitized is not None
    assert sanitized["component_kind"] == "non_spatial_action"
    assert sanitized["spatial_requirements"] is None
    assert any("l3_spatial_requirement_boundary" in item for item in diagnostics)


def test_dynamic_provider_wire_serializes_after_boundary_projection_without_warnings() -> None:
    import warnings

    model = _dynamic_claim_output_model([], [])
    output = model.model_validate({"claims": [{
        "component_kind": "facility",
        "claim_id": "facility-1",
        "statement": "建设公共服务设施",
        "intervention_action": "new",
        "facility_parameters": {"facility_type": "clinic", "action": "new"},
        "spatial_requirements": {"grounding_requirements": ["candidate_geometry"]},
    }]})

    from app.domain.program.worker import _normalize_claim_components

    _normalize_claim_components(
        dimension_key="public_service",
        output=output,
        source_fact_ids=(),
        spatial_source_fact_ids=(),
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        output.model_dump_json()
    assert not any("PydanticSerializationUnexpectedValue" in str(item.message) for item in captured)
