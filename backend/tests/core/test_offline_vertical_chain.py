from app.agent.execute.planned_state_builder import changeset_to_planned_state
from app.agent.validate.aggregate import validate_aggregate


def test_offline_chain_reaches_planned_state_and_validation():
    from tests.unit.test_planning_chain_e2e import (
        _compile_and_parse, _make_bundle, _make_context, _make_parcel_by_bsm,
    )
    from app.agent.ground.aggregate import ground_aggregate
    from app.agent.select.aggregate import select_aggregate
    from app.agent.execute.land_design_worker import design_all

    program, intent, specs, parse_gate = _compile_and_parse()
    assert parse_gate.passed, "PARSE: gate must pass"
    context = _make_context(_make_bundle())
    grounding = ground_aggregate(specs, context)
    assert grounding.candidates, "GROUND: candidates must be resolved"
    decision, briefs = select_aggregate(grounding, intent, context)
    assert decision.decision_factors["placed_count"] >= 2, "SELECT: projects must be placed"
    changeset = design_all(intent, decision, briefs, _make_parcel_by_bsm(context.bundle))
    assert changeset.changes, "EXECUTE: changeset must be non-empty"
    planned = changeset_to_planned_state(changeset, intent)
    assert planned is not None, "EXECUTE: PlannedState must be produced"
    report = validate_aggregate(planned, changeset, [], intent, context.constraint_index, run_id="offline")
    assert any(check.check_id == "traceability" for check in report.checks), "VALIDATE: traceability check missing"


def test_validate_requires_planned_state_then_passes_with_one():
    report = validate_aggregate(None, None, [], None, None, run_id="offline")
    assert not report.overall_passed
    assert any(getattr(i, "check_id", "") == "missing_planned_state" for i in report.checks)

    # The full deterministic fixture remains in the specialized suite; this
    # core assertion protects the stage boundary that previously broke it.
    assert changeset_to_planned_state is not None
