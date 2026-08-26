"""L1 spatial observations require the typed dual-output contract."""

import json

import pytest
from pydantic import ValidationError

from app.domain.assessment.observation_draft import (
    L1DemandFact,
    L1ObservationPassOutput,
    L1ScopedMetricFact,
    L1SpatialEntityFact,
    L1SpatialLocator,
    L1ReportOutput,
    build_l1_observation_output_model,
    l1_observation_output_model_for_dimension,
)


def test_l1_observe_and_report_outputs_are_separate_contracts() -> None:
    response_model = build_l1_observation_output_model(("spatial_entity",))
    output = response_model.model_validate(
        {
            "observations": [
                {
                    "fact_type": "spatial_entity",
                    "status": "confirmed",
                    "entity_type": "道路",
                    "name": "村道",
                    "locator": {
                        "place_names": ["金田村北部"],
                        "relation": "通往村委会",
                    },
                }
            ]
        }
    )

    assert output.observations[0].name == "村道"
    report = L1ReportOutput(report_body="交通现状分析正文。")
    assert report.report_body == "交通现状分析正文。"


def test_l1_empty_report_body_is_not_a_valid_typed_result() -> None:
    with pytest.raises(ValidationError):
        L1ReportOutput(report_body="")


def test_l1_observation_attribute_scalars_are_normalized_to_strings() -> None:
    output = build_l1_observation_output_model(("scoped_metric",)).model_validate(
        {
            "observations": [
                {
                    "fact_type": "scoped_metric",
                    "status": "confirmed",
                    "metric": "上位规划数据目录",
                    "scope": "全村",
                    "attributes": {
                        "record_count": 25,
                        "coverage_ratio": 0.8,
                    },
                }
            ]
        }
    )

    assert output.observations[0].attributes == {
        "record_count": "25",
        "coverage_ratio": "0.8",
    }


def test_l1_dimension_output_model_uses_dimension_specific_union_schema() -> None:
    response_model = l1_observation_output_model_for_dimension("location")

    assert response_model is not L1ObservationPassOutput
    assert issubclass(response_model, L1ObservationPassOutput)
    schema = response_model.model_json_schema()
    assert schema["properties"]["allowed_fact_types"]["default"] == [
        "spatial_entity",
        "spatial_relation",
        "scoped_metric",
        "document_observation",
    ]

    output = response_model.model_validate(
        {
            "observations": [
                {
                    "fact_type": "demand",
                    "demand_type": "养老服务",
                    "scope": "全村",
                    "spatial_requirement": "none",
                }
            ]
        }
    )

    assert output.observations == []
    assert output.allowed_fact_types == (
        "spatial_entity",
        "spatial_relation",
        "scoped_metric",
        "document_observation",
    )
    assert len(output.quarantined_observations) == 1
    assert any(
        item.startswith("l1_observation_record_invalid:0:")
        for item in output.diagnostics
    )


def test_l1_observation_output_recovers_stringified_container_and_quarantines_bad_record() -> None:
    output = l1_observation_output_model_for_dimension("public_services").model_validate(
        {
            "observations": json.dumps(
                [
                    {
                        "fact_type": "spatial_entity",
                        "status": "confirmed",
                        "entity_type": "道路",
                        "name": "村道",
                        "locator": {
                            "place_names": ["金田村"],
                            "relation": "贯穿村庄",
                        },
                        "source_quote": "现状村道贯穿村庄",
                    },
                    {
                        "fact_type": "demand",
                        "demand_type": "养老服务",
                        "scope": "全村",
                        "spatial_requirement": "none",
                        "status": "uncertain",
                    },
                    {"fact_type": "document_observation", "scope": "全村"},
                ],
                ensure_ascii=False,
            )
        }
    )

    assert len(output.observations) == 2
    assert isinstance(output.observations[0], L1SpatialEntityFact)
    assert output.observations[0].name == "村道"
    assert isinstance(output.observations[1], L1DemandFact)
    assert len(output.provisional_fact_records) == 1
    assert output.provisional_fact_records[0].fact_type == "demand"
    assert len(output.quarantined_observations) == 1
    assert output.quarantined_observations[0].ordinal == 2
    assert any(
        item.startswith("l1_observation_record_invalid:2:")
        for item in output.diagnostics
    )


def test_l1_observation_output_marks_non_confirmed_records_as_provisional() -> None:
    response_model = build_l1_observation_output_model(
        ("scoped_metric", "constraint"),
    )

    output = response_model.model_validate(
        {
            "observations": [
                {
                    "fact_type": "scoped_metric",
                    "metric": "常住人口",
                    "scope": "全村",
                    "status": "uncertain",
                    "source_quote": "无法核验",
                }
            ]
        }
    )

    assert len(output.observations) == 1
    assert output.observations[0].fact_type == "scoped_metric"
    assert len(output.provisional_fact_records) == 1
    assert output.provisional_fact_records[0].fact_type == "scoped_metric"
    assert output.quarantined_observations == []


def test_unconfigured_global_l1_output_model_fails_closed() -> None:
    output = L1ObservationPassOutput.model_validate(
        {
            "observations": [
                {
                    "fact_type": "spatial_entity",
                    "entity_type": "道路",
                    "name": "村道",
                    "locator": {},
                }
            ]
        }
    )

    assert output.allowed_fact_types == ()
    assert output.observations == []
    assert len(output.quarantined_observations) == 1
    assert output.quarantined_observations[0].error_paths == ["<model>"]


@pytest.mark.asyncio
async def test_l1_loop_quarantines_dimension_disallowed_fact_type(
    monkeypatch,
) -> None:
    from app.domain.assessment import l1_extraction_loop
    from app.domain.assessment.source_index import build_l1_source_index

    index = build_l1_source_index({"village_data": "村民提出养老服务需求。"})
    segment = index.source_segments[0]

    async def fake_runner(response_model, _messages, **_kwargs):
        if isinstance(response_model, type) and issubclass(
            response_model, L1ObservationPassOutput
        ):
            return response_model.model_validate(
                {
                    "observations": [
                        {
                            "fact_type": "demand",
                            "demand_type": "养老服务",
                            "scope": "全村",
                            "spatial_requirement": "none",
                            "source_segment_ids": [segment.segment_id],
                            "source_quote": "村民提出养老服务需求。",
                        }
                    ]
                }
        )
        return L1ReportOutput(report_body="村民提出养老服务需求。")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    result = await l1_extraction_loop.run_l1_dimension_loop(
        dimension_key="location",
        prompt="地点现状",
        source_index=index,
        runner_kwargs={"max_retries": 0},
    )

    assert result.observations == []
    assert result.cursor is not None
    assert result.cursor.status == "complete"
    assert any(
        item.startswith("l1_observation_record_invalid:0:")
        for item in result.diagnostics
    )
