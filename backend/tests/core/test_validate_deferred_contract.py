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

