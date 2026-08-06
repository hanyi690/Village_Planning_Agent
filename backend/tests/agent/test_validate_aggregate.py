from app.agent.validate.aggregate import validate_aggregate


def test_validate_blocks_on_missing_planned_state():
    report = validate_aggregate(
        planned_state=None,
        changeset=None,
        layout_configs=None,
        intent=None,
        constraint_index=None,
        run_id="r1",
    )
    assert report.overall_passed is False
    codes = [c.check_id for c in report.checks]
    assert any("missing_planned_state" in c for c in codes), (
        "must emit a blocking missing_planned_state check"
    )
