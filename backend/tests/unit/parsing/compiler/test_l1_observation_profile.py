"""Tests for the L1 Observation profile - report -> L1DimensionFragment."""
from __future__ import annotations

from app.modules.parsing.compiler.profiles.l1_observation import compile_l1_observation
from app.modules.schema.contracts.parsing_contracts import CompilationProfile


def test_land_use_fragment_has_classification_refs(land_use_report):
    frag = compile_l1_observation(**land_use_report, run_id="r1")
    assert frag.dimension_key == "land_use"
    # 现状分类仅为事实（ClassificationRef）
    assert len(frag.classification_refs) == 2
    assert {r.canonical_name for r in frag.classification_refs} == {"水田", "村庄建设用地"}
    assert all(r.source == "ingested" for r in frag.classification_refs)
    assert all(r.system == "gbt21010" for r in frag.classification_refs)


def test_land_use_control_lines_become_constraints(land_use_report):
    frag = compile_l1_observation(**land_use_report, run_id="r1")
    assert any("基本农田" in c for c in frag.constraints)
    assert any("生态保护红线" in c for c in frag.constraints)


def test_land_use_instruction_becomes_spatial_facts(land_use_report):
    frag = compile_l1_observation(**land_use_report, run_id="r1")
    assert any("文化礼堂" in f for f in frag.spatial_facts)


def test_l1_location_facts_use_instruction_rows_not_prose():
    frag = compile_l1_observation(
        dimension_key="location",
        content="# 区位\n正文提到金田村，但不应直接成为地点事实。",
        instruction=(
            "【INSTRUCTION】\n"
            "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 现状项目 | 村庄公共服务 | 金田村 | 服务设施集中 | 1处 |\n"
        ),
        report_id="rpt-location",
        summary="",
    )
    assert len(frag.location_facts) == 1
    assert frag.location_facts[0].normalized_name == "金田村"
    assert frag.location_facts[0].source_report_ref == "rpt-location"


def test_socio_economic_missing_data_becomes_evidence_gap(socio_economic_report):
    frag = compile_l1_observation(**socio_economic_report, run_id="r1")
    assert len(frag.evidence_gaps) == 1
    gap = frag.evidence_gaps[0]
    assert gap.dimension == "socio_economic"
    assert "常住人口" in gap.description
    assert gap.gap_id.startswith("socio_economic-")


def test_classification_refs_never_derive_planning_zone(land_use_report):
    """Roadmap constraint: 禁止从现状 DLBM 自动推出规划用途/规划分区."""
    frag = compile_l1_observation(**land_use_report, run_id="r1")
    assert all(r.system != "planning_zones" for r in frag.classification_refs)
    dumped = frag.model_dump(mode="json")
    flat = str(dumped)
    assert "planning_zones" not in flat
    assert "zone_type" not in flat


def test_classification_refs_missing_code_emits_gap_not_fabricated_ref():
    """Roadmap: 未明确规划分类的未调整地块使用 preserve，不自动伪造规划编码."""
    report = {
        "dimension_key": "land_use",
        "content": (
            "# 现状用地\n"
            "## 用地结构\n"
            "| 地类 | 面积(公顷) | 占比(%) |\n"
            "| --- | --- | --- |\n"
            "| 未分类用地 | 5.0 | 1.9 |\n"
        ),
        "instruction": "",
        "summary": "",
        "report_id": "rpt-landuse-v2",
    }
    frag = compile_l1_observation(**report, run_id="r1")
    assert all(r.canonical_name != "未分类用地" for r in frag.classification_refs)


def test_fragment_trace_records_profile_and_steps():
    frag = compile_l1_observation(
        dimension_key="land_use", content="# 现状用地", instruction="",
        summary="", report_id="rpt-x", run_id="r1",
    )
    assert frag.trace is not None
    assert frag.trace.profile == CompilationProfile.L1_OBSERVATION
    assert frag.trace.steps
