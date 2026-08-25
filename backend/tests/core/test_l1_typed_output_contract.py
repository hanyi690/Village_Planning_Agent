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
)


def test_l1_observe_and_report_outputs_are_separate_contracts() -> None:
    output = L1ObservationPassOutput(
        observations=[
            L1SpatialEntityFact(
                fact_type="spatial_entity",
                entity_type="道路",
                name="村道",
                locator=L1SpatialLocator(
                    place_names=["金田村北部"],
                    relation="通往村委会",
                ),
            )
        ],
    )

    assert output.observations[0].name == "村道"
    report = L1ReportOutput(report_body="交通现状分析正文。")
    assert report.report_body == "交通现状分析正文。"


def test_l1_empty_report_body_is_not_a_valid_typed_result() -> None:
    with pytest.raises(ValidationError):
        L1ReportOutput(report_body="")


def test_l1_observation_attribute_scalars_are_normalized_to_strings() -> None:
    output = L1ObservationPassOutput.model_validate(
        {
            "observations": [
                {
                    "fact_type": "scoped_metric",
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


def test_l1_observation_output_recovers_stringified_container_and_skips_bad_record() -> None:
    output = L1ObservationPassOutput.model_validate(
        {
            "observations": json.dumps(
                [
                    {
                        "fact_type": "spatial_entity",
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
                    },
                ],
                ensure_ascii=False,
            )
        }
    )

    assert len(output.observations) == 1
    assert isinstance(output.observations[0], L1SpatialEntityFact)
    assert output.observations[0].name == "村道"
    assert any(
        item.startswith("l1_observation_record_invalid:1:")
        for item in output.diagnostics
    )


@pytest.mark.asyncio
async def test_l1_loop_accepts_global_union_fact_with_soft_dimension_mismatch(
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

    assert isinstance(result.observations[0], L1DemandFact)
    assert result.cursor is not None
    assert result.cursor.status == "complete"
    assert any(
        item.startswith("l1_dimension_fact_type_mismatch:location:demand")
        for item in result.diagnostics
    )
