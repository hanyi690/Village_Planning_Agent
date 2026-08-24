"""L1 spatial observations require the typed dual-output contract."""

import pytest
from pydantic import ValidationError

from app.domain.assessment.observation_draft import (
    L1ObservationPassOutput,
    L1ObservationDraft,
    L1ReportOutput,
)


def test_l1_observe_and_report_outputs_are_separate_contracts() -> None:
    output = L1ObservationPassOutput(
        observations=[
            L1ObservationDraft(
                entity_type="道路",
                name="村道",
                location="金田村北部",
                relation="通往村委会",
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
                    "name": "上位规划数据目录",
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
