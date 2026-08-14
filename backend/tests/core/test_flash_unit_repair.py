"""Flash unit repair: unknown units mapped cheaply to the standard closed set,
avoiding a full dimension re-generation on simple unit typos.
"""
from __future__ import annotations

from app.domain.program.claim_draft import (
    MeasureDraft,
    PlanningClaimDraft,
    PlanningClaimDraftSet,
    ProjectPlanningParametersDraft,
)


def _draft_set(unit="待定", top_unit=None):
    claim = PlanningClaimDraft(
        claim_id="c1",
        suggested_category="project",
        suggested_output_kind="parcel",
        project_parameters=ProjectPlanningParametersDraft(
            footprint_area=MeasureDraft(value=100, unit=unit),
        ),
    )
    if top_unit:
        claim.quantity_unit = top_unit
    return PlanningClaimDraftSet(dimension_key="x", claims=[claim])


def test_collect_unknown_units_finds_unmappable():
    from app.domain.program.flash_unit_repair import collect_unknown_units

    unknown = collect_unknown_units(_draft_set("待定"))
    assert "待定" in unknown
    assert unknown["待定"] == ["c1"]


def test_known_units_are_not_collected():
    from app.domain.program.flash_unit_repair import collect_unknown_units

    assert collect_unknown_units(_draft_set("ha")) == {}
    assert collect_unknown_units(_draft_set("hm")) == {}  # alias maps to ha


def test_apply_mapping_updates_measure_unit():
    from app.domain.program.flash_unit_repair import _apply_mapping

    ds = _draft_set("待定")
    assert _apply_mapping(ds, {"待定": "ha"}) >= 1
    assert ds.claims[0].project_parameters.footprint_area.unit == "ha"


def test_parse_mapping_json():
    from app.domain.program.flash_unit_repair import _parse_mapping

    mapping = _parse_mapping('{"待定": "ha", "XX": "m"}')
    assert mapping == {"待定": "ha", "xx": "m"}


def test_flash_repair_units_applies_mapping(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.infrastructure.llm import factory as llm_factory

    async def _fake_ainvoke(prompt):
        return SimpleNamespace(content='{"\u5f85\u5b9a": "ha"}')

    monkeypatch.setattr(
        llm_factory,
        "create_flash_llm",
        lambda *a, **k: SimpleNamespace(ainvoke=_fake_ainvoke),
    )
    from app.domain.program.flash_unit_repair import flash_repair_units

    ds = _draft_set("待定")
    from app.domain.program.flash_unit_repair import _parse_mapping, _apply_mapping, collect_unknown_units
    llm = llm_factory.create_flash_llm()
    import inspect
    print("DEBUG iscoroutine:", inspect.iscoroutinefunction(llm.ainvoke))
    resp = asyncio.run(llm.ainvoke("x"))
    print("DEBUG content:", resp.content)
    m = _parse_mapping(resp.content)
    print("DEBUG mapping:", m)
    print("DEBUG unknown:", collect_unknown_units(ds))
    print("DEBUG applied:", _apply_mapping(ds, m))
    result = asyncio.run(flash_repair_units(ds, "s-flash"))
    print("DEBUG unit after:", result.claims[0].project_parameters.footprint_area.unit)
    assert result.claims[0].project_parameters.footprint_area.unit == "ha"


def test_flash_repair_noop_when_all_known():
    import asyncio

    from app.domain.program.flash_unit_repair import flash_repair_units

    ds = _draft_set("ha")
    result = asyncio.run(flash_repair_units(ds, "s-flash"))
    assert result.claims[0].project_parameters.footprint_area.unit == "ha"
