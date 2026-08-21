"""L1 spatial observations require the typed dual-output contract."""

import pytest
from pydantic import ValidationError

from app.domain.assessment.observation_draft import (
    L1DimensionOutput,
    L1ObservationDraft,
)


def test_l1_typed_output_keeps_report_and_spatial_observations_separate() -> None:
    output = L1DimensionOutput(
        report_body="交通现状分析正文。",
        observations=[
            L1ObservationDraft(
                entity_type="道路",
                name="村道",
                location="金田村北部",
                relation="通往村委会",
            )
        ],
    )

    assert output.report_body == "交通现状分析正文。"
    assert output.observations[0].name == "村道"


def test_l1_empty_report_body_is_not_a_valid_typed_result() -> None:
    with pytest.raises(ValidationError):
        L1DimensionOutput(report_body="", observations=[])

