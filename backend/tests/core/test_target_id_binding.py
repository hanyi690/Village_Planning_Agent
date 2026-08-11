"""Core tests for the target_id binding chain (断点 #8).

Verifies:
  1. SpatialReferenceSpec.project_ref is set to the intervention_id after
     mapping (breakpoint A fix).
  2. compile_program_deterministic emits a TargetBindingTable that links every
     intervention to its binding by semantic key (target_id), not position.
"""
from __future__ import annotations

import pytest

from app.agent.parse.compile_node import compile_program_deterministic
from app.modules.parsing.compiler.spec_mapper import map_intervention_to_spec
from app.modules.schema.contracts.l3_contracts import (
    PlanningIntervention,
    PlanningProgram,
)
from app.modules.schema.contracts.target_binding_contracts import TargetBindingTable

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def test_project_ref_is_set_to_intervention_id():
    intervention = PlanningIntervention(
        intervention_id="intervention-1",
        name="建设村民活动中心",
        category="project",
        execution_mode="spatial",
        target_id="target-1",
    )

    spec = map_intervention_to_spec(intervention)

    assert spec is not None
    assert spec.project_ref == intervention.intervention_id
    assert spec.target_id == intervention.target_id
    assert spec.spec_id == f"spatial-ref:{intervention.target_id}"


def test_project_ref_is_set_for_missing_location_evidence():
    intervention = PlanningIntervention(
        intervention_id="intervention-2",
        name="新建产业园区",
        category="project",
    )

    spec = map_intervention_to_spec(intervention)

    assert spec is not None
    assert spec.unresolved_reason == "missing_location_evidence"
    assert spec.project_ref == intervention.intervention_id


def test_target_binding_table_generated():
    program = PlanningProgram(
        interventions=[
            PlanningIntervention(
                intervention_id="interv-a",
                name="建设村民活动中心",
                category="facility",
                target_id="target-a",
            ),
            PlanningIntervention(
                intervention_id="interv-b",
                name="硬化道路",
                category="road",
                target_id="target-b",
            ),
            PlanningIntervention(
                intervention_id="interv-c",
                name="建立保洁巡查制度",
                category="project",
                execution_mode="non_spatial",
                expected_output_kind="action",
                target_id="target-c",
            ),
        ]
    )

    result, _, _ = compile_program_deterministic(program)

    table = result.target_binding_table
    assert isinstance(table, TargetBindingTable)
    assert len(table.bindings) == 3

    binding_a = table.binding_for_target("target-a")
    assert binding_a is not None
    assert binding_a.intervention_id == "interv-a"
    assert binding_a.project_ref == "interv-a"
    assert binding_a.spec_id == "spatial-ref:target-a"
    assert binding_a.target_type == "facility"

    binding_b = table.binding_for_target("target-b")
    assert binding_b is not None
    assert binding_b.intervention_id == "interv-b"
    assert binding_b.project_ref == "interv-b"
    assert binding_b.spec_id == "spatial-ref:target-b"

    binding_c = table.binding_for_target("target-c")
    assert binding_c is not None
    assert binding_c.intervention_id == "interv-c"
    assert binding_c.project_ref == "interv-c"
    assert binding_c.spec_id == ""
    assert binding_c.expected_output_kind == "action"


def test_target_binding_table_links_spec_by_target_id_not_position():
    program = PlanningProgram(
        interventions=[
            PlanningIntervention(
                intervention_id="interv-x",
                name="非空间制度",
                category="project",
                execution_mode="non_spatial",
                expected_output_kind="action",
                target_id="target-x",
            ),
            PlanningIntervention(
                intervention_id="interv-y",
                name="建设服务站",
                category="facility",
                target_id="target-y",
            ),
        ]
    )

    result, specs, _ = compile_program_deterministic(program)

    binding_x = result.target_binding_table.binding_for_target("target-x")
    binding_y = result.target_binding_table.binding_for_target("target-y")

    assert binding_x.spec_id == ""
    assert binding_y.spec_id == "spatial-ref:target-y"
    assert [spec.target_id for spec in specs] == ["target-y"]


def test_target_binding_table_is_immutable():
    from pydantic import ValidationError

    table = TargetBindingTable()

    with pytest.raises(Exception):
        table.bindings = ()