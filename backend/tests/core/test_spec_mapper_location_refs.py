"""Regression tests for deterministic spatial-reference mapping in spec_mapper.

Guards against:
- one-character false place names from arbitrary Chinese spans
- generic scope words (村内道路/现状机耕路) becoming place names
- river-name extraction (a safe deterministic suffix)

Complex feature extraction (祠堂/小学/广场 ...) is delegated to the GROUND
flash-LLM mention enhancer plus the evidence index substring matcher; the
deterministic mapper must simply not fabricate a place name for those.
"""
from __future__ import annotations

from app.contracts.domain.l3_contracts import PlanningIntervention
from app.data.ingestion.compiler.spec_mapper import map_intervention_to_spec


def _make(
    category: str,
    name: str,
    problem: str,
    location: str = "",
) -> PlanningIntervention:
    kind = {
        "facility": "point",
        "road": "line",
        "axis": "line",
        "restoration": "polygon",
        "protection": "polygon",
        "zone": "polygon",
        "project": "parcel",
    }[category]
    return PlanningIntervention(
        intervention_id=f"iv-{name[:6]}",
        name=name,
        category=category,
        execution_mode="spatial",
        expected_output_kind=kind,
        problem_addressed=problem,
        spatial_requirements={"location": location} if location else {},
    )


def _label_contains(spec) -> str | None:
    if spec is None:
        return None
    if spec.type == "topological" and spec.reference is not None:
        return (spec.reference.filter or {}).get("label_contains")
    return None


def test_single_char_false_mentions_are_not_produced():
    spec = map_intervention_to_spec(
        _make("project", "村庄公共服务设施建设", "主要利益建设，建立新机制促进发展", "")
    )
    assert spec is not None
    assert spec.unresolved_reason == "missing_location_evidence"


def test_river_name_suffix_is_extracted_without_position_word():
    spec = map_intervention_to_spec(
        _make("zone", "沿石窟河两岸农业发展区", "沿石窟河沿岸发展农业", "")
    )
    assert _label_contains(spec) == "石窟河"


def test_generic_road_words_are_not_place_names():
    for name, problem in (
        ("村内道路硬化", "村内道路建设及硬化处理"),
        ("机耕路提升", "现状机耕路改造提升"),
    ):
        spec = map_intervention_to_spec(_make("road", name, problem, ""))
        assert spec is not None
        assert spec.unresolved_reason == "missing_location_evidence", (name, spec)


def test_root_village_in_prose_is_recognized():
    spec = map_intervention_to_spec(
        _make("project", "金田村文化活动中心", "金田村文化活动中心建设", "")
    )
    assert _label_contains(spec) == "金田村"


def test_temple_is_left_to_ground_evidence_index():
    # 祠堂 is a real feature but not in the deterministic suffix table; the
    # mapper must not fabricate a partial name (村内祠 / 祠) for it.
    spec = map_intervention_to_spec(
        _make("restoration", "祠堂修缮", "村内祠堂修缮保护", "")
    )
    assert spec is not None
    assert spec.unresolved_reason == "missing_location_evidence"


def test_water_body_category_is_not_fabricated():
    spec = map_intervention_to_spec(
        _make("protection", "村口水塘治理", "村口水塘清淤治理", "")
    )
    assert spec is not None
    assert spec.unresolved_reason == "missing_location_evidence"