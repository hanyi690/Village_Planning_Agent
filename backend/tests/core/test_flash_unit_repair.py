from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.domain.program.claim_draft import (
    FacilityPlanningParametersDraft,
    MeasureDraft,
    PlanningClaimDraft,
    PlanningClaimDraftSet,
    RoadPlanningParametersDraft,
    SiteAreaPlanningParametersDraft,
)


def _build_draft_set() -> PlanningClaimDraftSet:
    return PlanningClaimDraftSet(
        dimension_key="x",
        claims=[
            PlanningClaimDraft(
                claim_id="area-1",
                suggested_category="site_area",
                suggested_output_kind="parcel",
                site_area_parameters=SiteAreaPlanningParametersDraft(
                    footprint_area=MeasureDraft(value=100, unit="hm"),
                ),
            ),
            PlanningClaimDraft(
                claim_id="len-1",
                suggested_category="road",
                suggested_output_kind="line",
                road_parameters=RoadPlanningParametersDraft(
                    length=MeasureDraft(value=10, unit="ha"),
                ),
            ),
            PlanningClaimDraft(
                claim_id="facility-1",
                suggested_category="facility",
                suggested_output_kind="point",
                facility_parameters=FacilityPlanningParametersDraft(
                    service_radius=MeasureDraft(value=500, unit="待定"),
                ),
            ),
            PlanningClaimDraft(
                claim_id="site-2",
                suggested_category="site_area",
                suggested_output_kind="parcel",
                site_area_parameters=SiteAreaPlanningParametersDraft(
                    footprint_area=MeasureDraft(value=80, unit="待定"),
                ),
            ),
            PlanningClaimDraft(
                claim_id="site-count",
                suggested_category="site_area",
                suggested_output_kind="parcel",
                site_area_parameters=SiteAreaPlanningParametersDraft(
                    capacity=MeasureDraft(value=20, unit="待定"),
                ),
            ),
        ],
    )


def test_collect_unknown_units_only_returns_unrecognized_fields():
    from app.domain.program.flash_unit_repair import collect_unknown_units

    unknown = collect_unknown_units(_build_draft_set())
    assert unknown == {"待定": ["facility-1", "site-2", "site-count"]}


def test_deterministic_alias_resolution_keeps_legacy_aliases():
    from app.domain.program.flash_unit_repair import apply_unit_resolution_batch, resolve_units_deterministically

    draft_set = _build_draft_set()
    batch, unresolved = resolve_units_deterministically(draft_set)

    assert any(
        item.claim_id == "area-1"
        and item.field_path == "site_area_parameters.footprint_area.unit"
        and item.quantity_kind == "area"
        and item.normalized_unit == "ha"
        and item.status == "resolved"
        for item in batch.resolutions
    )
    assert any(
        item.claim_id == "len-1"
        and item.field_path == "road_parameters.length.unit"
        and item.status == "abstain"
        for item in batch.resolutions
    )
    assert {item.claim_id for item in unresolved} == {"facility-1", "site-2", "site-count"}

    assert apply_unit_resolution_batch(draft_set, batch) == 1
    assert draft_set.claims[0].site_area_parameters.footprint_area.unit == "ha"
    assert draft_set.claims[1].road_parameters.length.unit == "ha"


def test_apply_unit_resolution_batch_ignores_invalid_path():
    from app.domain.program.flash_unit_repair import UnitResolution, UnitResolutionBatch, apply_unit_resolution_batch

    draft_set = _build_draft_set()
    batch = UnitResolutionBatch(
        resolutions=[
            UnitResolution(
                claim_id="site-2",
                field_path="site_area_parameters.missing.unit",
                raw_unit="待定",
                quantity_kind="area",
                normalized_unit="ha",
                status="resolved",
            )
        ]
    )

    assert apply_unit_resolution_batch(draft_set, batch) == 0
    assert draft_set.claims[3].site_area_parameters.footprint_area.unit == "待定"


def test_apply_unit_resolution_batch_abstains_on_wrong_kind():
    from app.domain.program.flash_unit_repair import UnitResolution, UnitResolutionBatch, apply_unit_resolution_batch

    draft_set = _build_draft_set()
    batch = UnitResolutionBatch(
        resolutions=[
            UnitResolution(
                claim_id="facility-1",
                field_path="facility_parameters.service_radius.unit",
                raw_unit="待定",
                quantity_kind="area",
                normalized_unit="ha",
                status="resolved",
            )
        ]
    )

    assert apply_unit_resolution_batch(draft_set, batch) == 0
    assert draft_set.claims[2].facility_parameters.service_radius.unit == "待定"


def test_apply_unit_resolution_batch_respects_abstain_status():
    from app.domain.program.flash_unit_repair import UnitResolution, UnitResolutionBatch, apply_unit_resolution_batch

    draft_set = _build_draft_set()
    batch = UnitResolutionBatch(
        resolutions=[
            UnitResolution(
                claim_id="site-2",
                field_path="site_area_parameters.footprint_area.unit",
                raw_unit="待定",
                quantity_kind="area",
                normalized_unit="ha",
                status="abstain",
            )
        ]
    )

    assert apply_unit_resolution_batch(draft_set, batch) == 0
    assert draft_set.claims[3].site_area_parameters.footprint_area.unit == "待定"


def test_apply_unit_resolution_batch_rolls_back_failed_reverification():
    from app.domain.program.flash_unit_repair import UnitResolution, UnitResolutionBatch, apply_unit_resolution_batch

    draft_set = _build_draft_set()
    batch = UnitResolutionBatch(
        resolutions=[
            UnitResolution(
                claim_id="site-2",
                field_path="site_area_parameters.footprint_area.unit",
                raw_unit="待定",
                quantity_kind="area",
                normalized_unit="unknown-unit",
                status="resolved",
            )
        ]
    )

    assert apply_unit_resolution_batch(draft_set, batch) == 0
    assert draft_set.claims[3].site_area_parameters.footprint_area.unit == "待定"


def test_flash_repair_units_is_field_scoped_per_quantity_kind(monkeypatch):
    from app.domain.program.flash_unit_repair import flash_repair_units
    from app.infrastructure.llm import factory as llm_factory

    prompts: list[str] = []

    async def _fake_ainvoke(prompt: str):
        prompts.append(prompt)
        return SimpleNamespace(
            content=(
                '{"resolutions":['
                '{"claim_id":"site-2","field_path":"site_area_parameters.footprint_area.unit","raw_unit":"待定","quantity_kind":"area","normalized_unit":"ha","status":"resolved"},'
                '{"claim_id":"site-count","field_path":"site_area_parameters.capacity.unit","raw_unit":"待定","quantity_kind":"count","normalized_unit":"个","status":"resolved"},'
                '{"claim_id":"len-1","field_path":"road_parameters.length.unit","raw_unit":"ha","quantity_kind":"length","normalized_unit":"m","status":"resolved"}'
                "]}"
            )
        )

    monkeypatch.setattr(
        llm_factory,
        "create_flash_llm",
        lambda *args, **kwargs: SimpleNamespace(ainvoke=_fake_ainvoke),
    )

    result = asyncio.run(flash_repair_units(_build_draft_set(), "s-flash"))

    assert "facility-1" in prompts[0]
    assert "site-2" in prompts[0]
    assert "site-count" in prompts[0]
    assert "len-1" not in prompts[0]
    assert result.claims[0].site_area_parameters.footprint_area.unit == "ha"
    assert result.claims[1].road_parameters.length.unit == "ha"
    assert result.claims[2].facility_parameters.service_radius.unit == "待定"
    assert result.claims[3].site_area_parameters.footprint_area.unit == "ha"
    assert result.claims[4].site_area_parameters.capacity.unit == "个"
