"""Regression tests for source-report facts at the L1 -> GROUND boundary."""

from pathlib import Path
from types import SimpleNamespace

from app.data.ingestion.compiler.profiles.l1_observation import compile_l1_observation
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village" / "current_report.md"


def test_l1_location_facts_come_from_observations_not_report_body():
    """L1LocationFact must only come from the observations JSON, not report body.

    The uploaded current_report.md is raw input, not an L1 intermediate
    artifact.  Scanning its prose/HTML tables for village names produced
    un-auditable location_facts with comma-joined name strings (e.g.
    "肩丰、长塘、营仔、田坑、黄竹").  The compiler only extracts
    location_facts from the model's structured observations JSON; an empty
    instruction must yield zero facts.
    """
    content = FIXTURE.read_text(encoding="utf-8")
    fragment = compile_l1_observation(
        dimension_key="socio_economic",
        content=content,
        instruction="",
        report_id="rpt-socio-economic-v1",
    )

    assert fragment.location_facts == []


def test_legacy_markdown_instruction_yields_no_location_facts():
    """A legacy markdown INSTRUCTION table is no longer a location source.

    Since the dual-response migration the structured observations JSON is the
    only location-fact source; a markdown table must yield zero facts rather
    than a silently accepted fallback.
    """
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

    assert fragment.location_facts == []


def test_observations_json_provides_location_facts():
    """Dual-response observations JSON compiles into typed location facts."""
    import json

    instruction = json.dumps([
        {"entity_type": "现状设施", "name": "供水点", "location": "园寨", "description": "5处供水点", "scale": "5处"},
        {"entity_type": "道路", "name": "Y122乡道", "location": "村北", "description": "乡道", "scale": ""},
        {"entity_type": "水系", "name": "金田河", "location": "", "description": "河流", "scale": ""},
    ], ensure_ascii=False)
    fragment = compile_l1_observation(
        dimension_key="infrastructure",
        content="正文内容",
        instruction=instruction,
        report_id="rpt-infra-v1",
    )

    typed = {(fact.normalized_name, fact.role) for fact in fragment.location_facts}
    assert ("供水点", "facility") in typed
    assert ("Y122乡道", "road") in typed
    assert ("金田河", "water") in typed
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
