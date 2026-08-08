"""Regression tests for source-report facts at the L1 -> GROUND boundary."""

from pathlib import Path

from app.modules.parsing.compiler.profiles.l1_observation import compile_l1_observation


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village" / "current_report.md"


def test_source_report_village_list_is_dimension_scoped_and_traceable():
    content = FIXTURE.read_text(encoding="utf-8")
    fragment = compile_l1_observation(
        dimension_key="socio_economic",
        content=content,
        instruction="",
        report_id="rpt-socio-economic-v1",
    )

    names = {fact.normalized_name for fact in fragment.location_facts}
    assert names == {
        "园寨", "田坑", "社前", "分水", "清明", "塘笃",
        "长塘", "炉池", "肩丰", "营仔", "新山", "黄竹",
    }
    assert all(fact.source_report_ref == "rpt-socio-economic-v1" for fact in fragment.location_facts)
    assert all(fact.dimension_key == "socio_economic" for fact in fragment.location_facts)


def test_source_report_html_rows_split_places_without_service_prose():
    content = FIXTURE.read_text(encoding="utf-8")
    fragment = compile_l1_observation(
        dimension_key="infrastructure",
        content=content,
        instruction="",
        report_id="rpt-infrastructure-v1",
    )

    names = {fact.normalized_name for fact in fragment.location_facts}
    assert {"营仔", "社前", "田坑", "塘笃", "黄竹"}.issubset(names)
    assert "服务本村" not in names
    assert "全村" not in names
    assert all(fact.source_span for fact in fragment.location_facts)


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
