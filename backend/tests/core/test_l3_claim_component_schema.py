from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.program.claim_draft import (
    L3ClaimOutput,
    component_to_planning_claim_draft,
)


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
