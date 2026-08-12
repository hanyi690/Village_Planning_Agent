from types import SimpleNamespace

from app.agent.validate.checks import check_contract_completeness


def test_all_spatial_tasks_deferred_do_not_require_planned_parcels():
    intent = SimpleNamespace(
        project_targets=[SimpleNamespace(requires_spatial=True)],
        zone_targets=[],
    )
    planned_state = SimpleNamespace(parcels=[])
    changeset = SimpleNamespace(
        changes=[],
        area_conservation_verified=False,
        geometry_validity_verified=False,
    )
    execution_plan = SimpleNamespace(worker_tasks=[])

    checks = check_contract_completeness(
        planned_state,
        changeset,
        intent,
        execution_plan=execution_plan,
    )

    assert all(check.passed for check in checks)


def test_missing_spatial_outputs_are_attributed_to_active_targets():
    intent = SimpleNamespace(
        project_targets=[SimpleNamespace(requires_spatial=True, project_id="project-1")],
        zone_targets=[],
    )
    planned_state = SimpleNamespace(parcels=[])
    changeset = SimpleNamespace(
        changes=[],
        area_conservation_verified=False,
        geometry_validity_verified=False,
    )
    execution_plan = SimpleNamespace(worker_tasks=[
        SimpleNamespace(target_id="project-1", expected_output_kind="parcel"),
    ])

    checks = check_contract_completeness(
        planned_state,
        changeset,
        intent,
        execution_plan=execution_plan,
    )

    assert checks[0].affected_target_ids == ["project-1"]
    assert checks[2].affected_target_ids == ["project-1"]
