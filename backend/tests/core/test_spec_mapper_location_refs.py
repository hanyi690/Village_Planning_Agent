"""Typed spatial references are the only input to target projection."""
from __future__ import annotations

from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.domain.planning_semantics import (
    RoadPlanningParameters,
    SiteAreaPlanningParameters,
)
from app.data.ingestion.compiler.spec_mapper import map_intervention_to_spec


def _site_area(*, name: str = "site", hints: list[str] | None = None) -> PlanningIntervention:
    requirements = {}
    if hints is not None:
        requirements["location_hints"] = list(hints)
    return PlanningIntervention(
        intervention_id=f"iv-{name}",
        name=name,
        category="site_area",
        execution_mode="spatial",
        expected_output_kind="polygon",
        materialization_role="site_footprint",
        site_area_parameters=SiteAreaPlanningParameters(
            site_type="公共服务设施用地",
            action="new",
            footprint_area_m2=100,
        ),
        spatial_requirements=requirements,
    )


def _road(*, name: str, hints: list[str] | None = None) -> PlanningIntervention:
    requirements = {}
    if hints is not None:
        requirements["location_hints"] = list(hints)
    return PlanningIntervention(
        intervention_id=f"iv-{name}",
        name=name,
        category="road",
        asset_kind="road",
        execution_mode="spatial",
        expected_output_kind="line",
        road_parameters=RoadPlanningParameters(
            action="new",
            road_level="村道",
            length_m=100,
        ),
        spatial_requirements=requirements,
    )


def _label_contains(spec) -> str | None:
    if spec is None:
        return None
    if spec.type == "topological" and spec.reference is not None:
        return (spec.reference.filter or {}).get("label_contains")
    return None


def test_prose_only_scope_is_not_reinterpreted():
    spec = map_intervention_to_spec(_site_area(name="金田村文化活动中心", hints=[]))
    assert spec is not None
    assert spec.unresolved_reason == "missing_location_evidence"


def test_typed_place_hint_is_compiled_as_a_grounding_query():
    spec = map_intervention_to_spec(_site_area(name="河岸公共空间", hints=["石窟河"]))
    assert _label_contains(spec) == "石窟河"


def test_prose_river_name_is_not_extracted():
    spec = map_intervention_to_spec(_site_area(name="沿石窟河两岸农业发展区", hints=[]))
    assert spec is not None
    assert spec.unresolved_reason == "missing_location_evidence"


def test_generic_road_words_are_not_place_names():
    for name in ("村内道路硬化", "机耕路提升"):
        spec = map_intervention_to_spec(_road(name=name, hints=[]))
        assert spec is not None
        assert spec.unresolved_reason == "missing_location_evidence", (name, spec)


def test_typed_village_scope_is_preserved():
    spec = map_intervention_to_spec(_site_area(hints=["全村"]))
    assert spec is not None
    assert spec.type == "topological"
    assert spec.topo == "sfWithin"
    assert spec.reference is not None
    assert spec.reference.kind == "village"


def test_l3_source_fact_refs_survive_target_projection_mapping():
    intervention = _site_area(name="有证据的公共空间", hints=[]).model_copy(update={
        "source_fact_refs": ["l1:fact:current", "l1:fact:second"],
    })

    spec = map_intervention_to_spec(intervention)

    assert spec is not None
    assert spec.l1_fact_refs == ["l1:fact:current", "l1:fact:second"]
