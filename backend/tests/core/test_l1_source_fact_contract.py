"""Regression tests for source-report facts at the L1 -> GROUND boundary."""

from pathlib import Path
from types import SimpleNamespace

from app.modules.parsing.compiler.profiles.l1_observation import compile_l1_observation
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village" / "current_report.md"


def test_l1_location_facts_come_from_instruction_not_report_body():
    """L1LocationFact must only come from the INSTRUCTION table, not report body.

    The uploaded current_report.md is raw input, not an L1 intermediate
    artifact.  Scanning its prose/HTML tables for village names produced
    un-auditable location_facts with comma-joined name strings (e.g.
    "肩丰、长塘、营仔、田坑、黄竹").  The compiler now only extracts
    location_facts from the model's structured INSTRUCTION table.
    """
    content = FIXTURE.read_text(encoding="utf-8")
    fragment = compile_l1_observation(
        dimension_key="socio_economic",
        content=content,
        instruction="",
        report_id="rpt-socio-economic-v1",
    )

    for fact in fragment.location_facts:
        assert "、" not in fact.normalized_name
        assert fact.normalized_name != "全村"
        assert fact.normalized_name != ""


def test_instruction_table_provides_location_facts():
    """When the model emits an INSTRUCTION table, its rows become location_facts."""
    instruction = (
        "【INSTRUCTION】\n"
        "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
        "| :--- | :--- | :--- | :--- | :--- |\n"
        "| 现状设施 | 供水点 | 园寨 | 5处供水点 | 5处 |\n"
        "| 现状设施 | 变压器 | 营仔 | 配电设施 | 1处 |\n"
    )
    fragment = compile_l1_observation(
        dimension_key="infrastructure",
        content="正文内容",
        instruction=instruction,
        report_id="rpt-infrastructure-v1",
    )

    names = {fact.normalized_name for fact in fragment.location_facts}
    assert "园寨" in names
    assert "营仔" in names
    assert "服务本村" not in names
    assert "全村" not in names
    assert all(fact.source_span for fact in fragment.location_facts)
    assert all(fact.source_report_ref == "rpt-infrastructure-v1" for fact in fragment.location_facts)

    typed = {(fact.normalized_name, fact.role) for fact in fragment.location_facts}
    assert ("供水点", "facility") in typed
    assert ("园寨", "village") in typed


def test_model_reasoning_and_protocol_chatter_are_not_l1_facts():
    fragment = compile_l1_observation(
        dimension_key="traffic",
        content=(
            "# 道路交通\n"
            "<think>internal reasoning</think>\n"
            "用户要求我作为道路交通分析专家。\n"
            "村内道路较窄，大部分不足 8 米。"
        ),
        instruction="",
        report_id="rpt-traffic-v1",
    )

    assert all("<think>" not in fact for fact in fragment.facts)
    assert all("用户要求我" not in fact for fact in fragment.facts)
    assert any("道路较窄" in fact for fact in fragment.facts)


def test_typed_facility_fact_reaches_evidence_index_and_real_parcel():
    parcel = SimpleNamespace(
        bsm="bsm-1",
        geometry={"type": "Point", "coordinates": [113.0, 23.0]},
    )
    bundle = SimpleNamespace(
        points={"annotations_current": [SimpleNamespace(
            text="供水点", category="现状设施点",
            geometry={"type": "Point", "coordinates": [113.0, 23.0]},
        )]},
        polygons={"landuse_current": [parcel]},
    )
    context = SimpleNamespace(
        session_id="s1", version=1, kg_version=1, gazetteer=None,
        kg=None, workspace=bundle,
        location_facts=[SimpleNamespace(
            normalized_name="供水点", mention="供水点", role="facility",
            aliases=[], confidence=0.95,
        )],
    )
    context.current_parcels = lambda: [parcel]
    index = PlaceEvidenceIndex.build(context)
    result = index.resolve_mention("供水点", role="facility")
    assert result.status == "resolved"
    assert result.candidates[0].source_bsms == ["bsm-1"]
    assert "poi" in result.candidates[0].evidence_refs
