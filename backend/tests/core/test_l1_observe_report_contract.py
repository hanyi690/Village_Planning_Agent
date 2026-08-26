"""L1 produces typed facts once, then synthesizes a report from those facts."""

import pytest
from pydantic import ValidationError

from app.contracts.domain.l1_contracts import (
    L1DimensionPassState,
    L1SourceIndex,
)
from app.domain.assessment.source_index import build_l1_source_index
from app.domain.assessment.observation_draft import (
    L1DemandFact,
    L1ObservationPassOutput,
    L1ReportOutput,
    QuarantinedObservation,
    build_l1_observation_output_model,
)
from app.domain.assessment.observation_quality import validate_observations


def test_l1_models_do_not_expose_register_or_coverage_fields() -> None:
    assert set(L1ObservationPassOutput.model_fields) == {
        "observations",
        "provisional_fact_records",
        "diagnostics",
        "quarantined_observations",
        "allowed_fact_types",
        "required_fact_types",
    }
    assert "current_assets" not in L1SourceIndex.model_fields
    assert "demands" not in L1SourceIndex.model_fields
    assert "pending_row_ids" not in L1DimensionPassState.model_fields
    assert "confirmed_row_ids" not in L1DimensionPassState.model_fields

    with pytest.raises(ValidationError):
        L1ObservationPassOutput.model_validate(
            {"observations": [], "register_rows": [], "coverage": []}
        )


def test_source_index_is_transport_only() -> None:
    index = build_l1_source_index(
        {"village_data": "现有村道一条，村民反映雨季通行困难。"}
    )

    assert index.source_segments
    dumped = index.model_dump(mode="json")
    assert "current_assets" not in dumped
    assert "demands" not in dumped


def test_l1_fact_type_is_selected_by_the_union_and_old_shape_is_rejected() -> None:
    response_model = build_l1_observation_output_model(
        ("demand", "document_observation"),
    )

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
    assert isinstance(output.observations[0], L1DemandFact)
    assert output.quarantined_observations == []

    recovered = response_model.model_validate(
        {
            "observations": [
                {
                    "entity_type": "现状设施",
                    "name": "祠堂",
                    "location": "社前村",
                }
            ]
        }
    )
    assert recovered.observations == []
    assert len(recovered.quarantined_observations) == 1
    assert isinstance(recovered.quarantined_observations[0], QuarantinedObservation)
    assert recovered.quarantined_observations[0].ordinal == 0
    assert "fact_type" in recovered.quarantined_observations[0].error_paths
    assert any(
        item.startswith("l1_observation_record_invalid:0:")
        for item in recovered.diagnostics
    )

    malformed_metric = build_l1_observation_output_model(
        ("scoped_metric",),
    ).model_validate(
        {
            "observations": [
                {
                    "fact_type": "scoped_metric",
                    "metric": "常住人口",
                    "scope": "全村",
                    "locator": {"place_names": ["社前村"]},
                }
            ]
        }
    )
    assert malformed_metric.observations == []
    assert len(malformed_metric.quarantined_observations) == 1
    assert malformed_metric.quarantined_observations[0].ordinal == 0
    assert "locator" in malformed_metric.quarantined_observations[0].error_paths
    assert any(
        item.startswith("l1_observation_record_invalid:0:")
        for item in malformed_metric.diagnostics
    )


@pytest.mark.asyncio
async def test_l1_loop_calls_only_observe_and_report(monkeypatch) -> None:
    from app.domain.assessment import l1_extraction_loop

    index = build_l1_source_index(
        {"village_data": "现有村道一条，村民反映雨季通行困难。"}
    )
    segment = index.source_segments[0]
    calls: list[type] = []
    messages_seen: list[list[dict]] = []

    async def fake_runner(response_model, messages, **_kwargs):
        calls.append(response_model)
        messages_seen.append(messages)
        if isinstance(response_model, type) and issubclass(
            response_model, L1ObservationPassOutput
        ):
            return response_model.model_validate(
                {
                    "observations": [
                        {
                            "fact_type": "spatial_entity",
                            "entity_type": "road",
                            "name": "村道",
                            "locator": {},
                            "description": "现有村道一条",
                            "source_segment_ids": [segment.segment_id],
                            "source_quote": "现有村道一条",
                        }
                    ]
                }
            )
        return L1ReportOutput(report_body="现状村道一条，雨季通行存在困难。")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    result = await l1_extraction_loop.run_l1_dimension_loop(
        dimension_key="traffic",
        prompt="交通现状",
        source_index=index,
        runner_kwargs={"max_retries": 0},
    )

    assert issubclass(calls[0], L1ObservationPassOutput)
    assert calls[1] is L1ReportOutput
    assert result.cursor is not None
    assert result.cursor.status == "complete"
    assert result.observations[0].source_refs == [segment.source_ref]
    observe_prompt = str(messages_seen[0])
    assert "不得另造资产台账、需求台账、coverage" in observe_prompt
    assert "同一语义族内的不同子类" in observe_prompt
    assert "attributes.metric" in observe_prompt
    assert "attributes.metric 或 semantic_type 本身" in observe_prompt
    assert "forest_area:commercial_forest" in observe_prompt


@pytest.mark.asyncio
async def test_completed_resume_does_not_repeat_model_calls(monkeypatch) -> None:
    from app.domain.assessment import l1_extraction_loop

    index = build_l1_source_index({"village_data": "现状资料"})

    async def fail_runner(*_args, **_kwargs):
        raise AssertionError("completed resume must not call provider")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fail_runner,
    )
    cursor = L1DimensionPassState(
        dimension_key="traffic",
        source_digest=index.source_digest,
        pass_name="complete",
        calls_used=2,
        status="complete",
    )
    result = await l1_extraction_loop.run_l1_dimension_loop(
        dimension_key="traffic",
        prompt="不会再次发送",
        source_index=index,
        previous_cursor=cursor,
        resume_payload={
            "report_body": "已完成正文。",
            "observations": [],
            "cursor": cursor.model_dump(mode="json"),
        },
    )

    assert result.report_body == "已完成正文。"
    assert result.cursor is not None
    assert result.cursor.status == "complete"


def test_observation_quality_treats_dimension_type_mismatch_as_soft_diagnostic() -> None:
    report = validate_observations(
        [
            {
                "fact_type": "demand",
                "demand_type": "养老服务",
                "scope": "全村",
                "spatial_requirement": "none",
                "semantic_type": "public_service_gap",
                "description": "全村存在养老服务需求",
            }
        ],
        dimension_key="location",
    )

    assert report["ok"] is True
    assert report["invalid_fact_type"] == 0
    assert report["dimension_mismatch"] == 1


def test_observation_quality_counts_distinct_defective_rows_across_buckets() -> None:
    report = validate_observations(
        [
            {
                "fact_type": "spatial_relation",
                "subject_ref": "金田河",
                "predicate": "",
                "object_ref": "石窟河",
                "semantic_type": "water_relation",
            },
            {
                "fact_type": "document_observation",
                "subject": "",
                "scope": "全村",
            },
        ],
        dimension_key="traffic",
        max_defect_ratio=0.75,
    )

    assert report["invalid_relation"] == 1
    assert report["invalid_semantics"] == 1
    assert report["defect_ratio"] == 1.0
    assert report["ok"] is False
