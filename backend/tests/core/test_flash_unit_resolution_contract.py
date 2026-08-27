from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_unit_resolution_contract_forbids_extra_fields():
    from app.domain.program.flash_unit_repair import UnitResolution

    with pytest.raises(ValidationError):
        UnitResolution.model_validate(
            {
                "claim_id": "c1",
                "field_path": "site_area_parameters.footprint_area.unit",
                "raw_unit": "待定",
                "quantity_kind": "area",
                "normalized_unit": "ha",
                "status": "resolved",
                "extra": "boom",
            }
        )


def test_unit_resolution_batch_contract_forbids_extra_fields():
    from app.domain.program.flash_unit_repair import UnitResolutionBatch

    with pytest.raises(ValidationError):
        UnitResolutionBatch.model_validate(
            {
                "resolutions": [],
                "extra": True,
            }
        )


def test_unit_resolution_batch_parses_typed_payload():
    from app.domain.program.flash_unit_repair import UnitResolutionBatch

    batch = UnitResolutionBatch.model_validate(
        {
            "resolutions": [
                {
                    "claim_id": "c1",
                    "field_path": "facility_parameters.service_radius.unit",
                    "raw_unit": "待定",
                    "quantity_kind": "length",
                    "normalized_unit": "m",
                    "status": "resolved",
                },
                {
                    "claim_id": "c2",
                    "field_path": "road_parameters.length.unit",
                    "raw_unit": "ha",
                    "quantity_kind": "length",
                    "normalized_unit": "",
                    "status": "abstain",
                },
            ]
        }
    )

    assert [item.claim_id for item in batch.resolutions] == ["c1", "c2"]
    assert batch.resolutions[1].status == "abstain"


def test_legacy_mapping_json_is_rejected():
    from app.domain.program.flash_unit_repair import UnitResolutionBatch

    with pytest.raises(ValidationError):
        UnitResolutionBatch.model_validate_json('{"待定":"ha"}')


def test_bare_resolution_list_is_rejected():
    from app.domain.program.flash_unit_repair import UnitResolutionBatch

    with pytest.raises(ValidationError):
        UnitResolutionBatch.model_validate_json(
            '[{"claim_id":"c1","field_path":"site_area_parameters.footprint_area.unit","raw_unit":"待定","quantity_kind":"area","normalized_unit":"ha","status":"resolved"}]'
        )
