from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.program.claim_draft import (
    L3ClaimOutput,
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
        }]} )


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


def test_dynamic_relation_schema_closes_template_object_kind_and_parameters() -> None:
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

    with pytest.raises(ValidationError):
        model.model_validate({"claims": [{
            "component_kind": "facility",
            "claim_id": "facility-1",
            "statement": "建设公共服务设施",
            "intervention_action": "new",
            "spatial_requirements": {
                "relations": [{
                    "relation_template": "near",
                    "object_ref": "灾害约束",
                    "object_ref_kind": "constraint",
                    "parameters": {
                        "parameter_type": "distance",
                        "max_distance_m": 100,
                        "metric": "euclidean",
                    },
                }],
            },
        }]})


def test_dynamic_schema_rejects_parameter_field_name_as_relation_template() -> None:
    model = _dynamic_claim_output_model(
        ["l1:fact:road"],
        ["l1:fact:road"],
    )

    with pytest.raises(ValidationError):
        model.model_validate({"claims": [{
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


def test_empty_dynamic_fact_set_rejects_nonempty_source_fact_refs() -> None:
    model = _dynamic_claim_output_model([], [])

    with pytest.raises(ValidationError):
        model.model_validate({"claims": [{
            "component_kind": "facility",
            "claim_id": "facility-1",
            "statement": "建设设施",
            "intervention_action": "new",
            "source_fact_refs": ["l1:fact:invented"],
        }]})
