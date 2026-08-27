"""L1 spatial observations require the typed dual-output contract."""

import json

import pytest
from pydantic import ValidationError

from app.domain.assessment.observation_draft import (
    L1DemandFact,
    L1ObservationPassOutput,
    L1ObservationProviderOutput,
    L1ScopedMetricFact,
    L1SpatialEntityFact,
    L1SpatialLocator,
    L1ReportOutput,
    build_l1_observation_output_model,
    l1_observation_provider_model_for_dimension,
    l1_observation_output_model_for_dimension,
    normalize_l1_observation_provider_output,
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


def test_l1_provider_schema_excludes_internal_recovery_envelope() -> None:
    provider_model = l1_observation_provider_model_for_dimension("socio_economic")
    schema = provider_model.model_json_schema()

    assert set(schema["properties"]) == {"observations", "diagnostics"}
    assert "provisional_fact_records" not in json.dumps(schema, ensure_ascii=False)
    assert "quarantined_observations" not in json.dumps(schema, ensure_ascii=False)
    assert "allowed_fact_types" not in json.dumps(schema, ensure_ascii=False)
    assert "required_fact_types" not in json.dumps(schema, ensure_ascii=False)
    schema_text = json.dumps(schema, ensure_ascii=False)
    assert "oneOf" not in schema_text
    assert "maxItems" not in schema["properties"]["observations"]


def test_l1_provider_schema_identity_is_stable_across_dimension_allowlists() -> None:
    first = l1_observation_provider_model_for_dimension("location")
    second = l1_observation_provider_model_for_dimension("architecture")

    assert first is L1ObservationProviderOutput
    assert second is first


def test_l1_provider_boundary_coerces_null_scalars_and_nested_attributes() -> None:
    provider_model = l1_observation_provider_model_for_dimension("ecological_green")
    provider_output = provider_model.model_validate(
        {
            "observations": [
                {
                    "fact_type": "scoped_metric",
                    "metric": "绿地面积",
                    "scope": "全村",
                        "status": "uncertain",
                        "source_segment_ids": ["l1:test:segment:1"],
                        "source_quote": "绿地面积现状资料",
                        "unit": None,
                    "counting_basis": None,
                    "attributes": {"locations": ["黄竹", "田坑"]},
                }
            ]
        }
    )

    output = normalize_l1_observation_provider_output(
        "ecological_green",
        provider_output,
    )

    observation = output.observations[0]
    assert observation.unit == ""
    assert observation.counting_basis == ""
    assert observation.attributes["locations"] == '["黄竹","田坑"]'
    assert not any(item.startswith("l1_provider_null_coerced:") for item in output.diagnostics)
    assert "l1_provider_attribute_coerced:0:locations" in output.diagnostics


def test_l1_provider_boundary_decodes_stringified_observation_array() -> None:
    provider_model = l1_observation_provider_model_for_dimension("public_services")
    provider_output = provider_model.model_validate(
        {
            "observations": json.dumps(
                [{
                    "fact_type": "spatial_entity",
                    "entity_type": "卫生室",
                    "name": "村卫生室",
                        "status": "confirmed",
                        "source_segment_ids": ["l1:test:segment:1"],
                        "source_quote": "村卫生室",
                        "locator": {"place_names": ["金田村"]},
                }],
                ensure_ascii=False,
            )
        }
    )

    assert len(provider_output.observations) == 1
    assert provider_output.observations[0].fact_type == "spatial_entity"


def test_l1_provider_boundary_keeps_all_source_observations_without_row_quota() -> None:
    rows = [
        {
            "fact_type": "document_observation",
            "subject": f"来源事实-{index}",
            "scope": "全村",
            "status": "verified",
        }
        for index in range(48)
    ]

    provider_output = l1_observation_provider_model_for_dimension("location").model_validate(
        {"observations": rows}
    )
    output = normalize_l1_observation_provider_output("location", provider_output)

    assert len(provider_output.observations) == 48
    assert len(output.observations) == 48
    assert all(item.status == "confirmed" for item in output.observations)
    assert "l1_provider_status_normalized:0:verified->confirmed" in output.diagnostics


def test_l1_provider_boundary_recovers_observation_array_with_diagnostics_tail() -> None:
    rows = [{
        "fact_type": "document_observation",
        "subject": "规划批复",
        "scope": "全村",
    }]
    encoded = json.dumps(rows, ensure_ascii=False) + ', "diagnostics": []}'

    provider_output = l1_observation_provider_model_for_dimension("location").model_validate(
        {"observations": encoded}
    )

    assert len(provider_output.observations) == 1
    assert provider_output.observations[0].subject == "规划批复"


def test_l1_provider_container_repair_keeps_nested_sentence_quotes() -> None:
    from app.domain.assessment.observation_draft import _decode_json_container

    valid = json.dumps(
        [{
            "fact_type": "document_observation",
            "subject": '他说"规划"已经批复',
            "scope": "全村",
        }],
        ensure_ascii=False,
    )
    malformed = valid.replace('\\"规划\\"', '"规划"')

    decoded = _decode_json_container(malformed)

    assert decoded[0]["subject"] == '他说"规划"已经批复'


def test_l1_provider_container_repair_quotes_json_like_keys_and_literals() -> None:
    from app.domain.assessment.observation_draft import _decode_json_container

    decoded = _decode_json_container(
        '[{fact_type: "document_observation", subject: "规划", '
        'scope: "全村", status: None,}]'
    )

    assert decoded == [{
        "fact_type": "document_observation",
        "subject": "规划",
        "scope": "全村",
        "status": None,
    }]


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
            response_model, L1ObservationProviderOutput
        ):
            return response_model.model_construct(
                observations=[
                        {
                            "fact_type": "demand",
                            "demand_type": "养老服务",
                            "scope": "全村",
                            "spatial_requirement": "none",
                            "source_segment_ids": [segment.segment_id],
                            "source_quote": "村民提出养老服务需求。",
                        }
                ],
                diagnostics=[],
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
