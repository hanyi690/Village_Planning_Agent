from app.contracts.domain.l1_contracts import L1Fact
from app.data.ingestion.compiler.profiles.l1_observation import compile_l1_observation


def test_l1_compiles_typed_metric_demand_and_constraint_without_parsing_report_body() -> None:
    instruction = {
        "observations": [
            {
                "fact_type": "scoped_metric",
                "semantic_type": "population",
                "metric": "常住人口",
                "scope": "全村",
                "description": "常住人口为 1260 人",
                "value": 1260,
                "unit": "人",
                "counting_basis": "2023年统计",
                "source_refs": ["input:village_data:segment:1"],
                "source_quote": "常住人口为1260人",
            },
            {
                "fact_type": "demand",
                "semantic_type": "public_service_gap",
                "demand_type": "养老服务需求",
                "scope": "社前村",
                "locator": {"place_names": ["社前村"]},
                "description": "社前村存在养老服务需求",
                "source_refs": ["input:village_data:segment:2"],
                "source_quote": "社前村存在养老服务需求",
            },
            {
                "fact_type": "constraint",
                "constraint_type": "河道缓冲带",
                "applies_to_scope": "全村",
                "description": "河道两侧需避让",
                "source_refs": ["input:village_data:segment:3"],
                "source_quote": "河道两侧需避让",
            },
        ]
    }
    snapshot = compile_l1_observation(
        dimension_key="socio_economic",
        content="这段正文不提供机器事实。",
        instruction=__import__("json").dumps(instruction, ensure_ascii=False),
        report_id="report-socio",
    )

    assert len(snapshot.fact_records) == 3
    metric = next(item for item in snapshot.fact_records if item.semantic_type == "population")
    assert isinstance(metric, L1Fact)
    assert metric.fact_kind == "document_observation"
    assert metric.value == 1260
    assert metric.unit == "人"
    demand = next(item for item in snapshot.fact_records if item.semantic_type == "public_service_gap")
    assert demand.fact_kind == "spatial_observation"
    assert "社前村" in demand.statement
    assert "河道两侧需避让" in snapshot.constraints
    location_names = {item.normalized_name for item in snapshot.location_facts}
    assert "养老服务需求" not in location_names
    assert "社前村" in location_names
    assert "常住人口" not in location_names
    assert "河道缓冲带" not in location_names


def test_unconfirmed_observation_does_not_enter_authoritative_facts() -> None:
    snapshot = compile_l1_observation(
        dimension_key="traffic",
        content="道路现状报告正文仍可阅读。",
        instruction=(
            '{"observations":[{"fact_type":"spatial_entity",'
            '"entity_type":"道路","name":"疑似道路","locator":{},"status":"uncertain",'
            '"source_quote":"无法核验"}]}'
        ),
        report_id="report-traffic",
    )

    assert snapshot.fact_records == []
    assert snapshot.location_facts == []


def test_village_wide_demand_without_locator_stays_non_spatial_and_is_preserved() -> None:
    snapshot = compile_l1_observation(
        dimension_key="villager_wishes",
        content="村民诉求报告正文。",
        instruction=(
            '{"observations":[{"fact_type":"demand",'
            '"demand_type":"tourism","scope":"全村","value":"发展旅游业",'
            '"attributes":{"benefit_object":"全体村民"},'
            '"source_segment_ids":["l1:segment:1"],'
            '"source_quote":"村民希望发展旅游业"}]}'
        ),
        report_id="report-wishes",
    )

    assert len(snapshot.fact_records) == 1
    demand = snapshot.fact_records[0]
    assert demand.fact_kind == "document_observation"
    assert demand.semantic_type == "tourism"
    assert demand.value == "发展旅游业"
    assert snapshot.location_facts == []
