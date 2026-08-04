"""Shared fixtures for PARSE compile node unit tests."""
from __future__ import annotations

import pytest

from app.modules.schema.contracts.l3_contracts import (
    PlanningIntervention,
    PlanningProgram,
)


@pytest.fixture
def planning_program() -> PlanningProgram:
    """L3 PlanningProgram with project + facility + road interventions."""
    return PlanningProgram(
        artifact_id="l3-xxx-v1",
        context_version="cv1",
        interventions=[
            PlanningIntervention(
                intervention_id="iv-1",
                name="金田村供水设施改造",
                category="project",
                scale="5ha",
                area_range_ha=(3.0, 5.0),
                functions=["供水", "净化"],
                spatial_requirements={"location": "村北", "dlbm_in": ["0301"]},
                constraints=["不占基本农田"],
            ),
            PlanningIntervention(
                intervention_id="iv-2",
                name="文化活动广场",
                category="facility",
                scale="0.5ha",
                area_range_ha=(0.2, 0.8),
                functions=["文体活动"],
                spatial_requirements={"location": "村中心"},
                constraints=[],
            ),
            PlanningIntervention(
                intervention_id="iv-3",
                name="村主干道硬化",
                category="road",
                scale="2km",
                spatial_requirements={"adjacent_to": "村委会"},
                constraints=[],
            ),
        ],
    )


@pytest.fixture
def empty_program() -> PlanningProgram:
    """L3 PlanningProgram with no interventions."""
    return PlanningProgram(artifact_id="l3-empty-v1", context_version="cv1")
