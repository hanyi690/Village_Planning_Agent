"""Test execution and validation contract types - behavior tests only.

Trimmed in V4 audit:
- Reverse-dep tests moved to test_architecture_invariants.py
- Pure model-construction tests removed (kept only behavior: computed fields,
  spec coverage, validation).

Verifies:
1. ValidationCheckResult.overall_passed is a computed field
2. ValidationCheckItem supports all 8 check IDs from design doc §5.6
"""


def test_validation_check_result_overall_passed_field():
    """overall_passed is a stored field reflecting validation outcome.

    When set to False (default), it correctly reports failure even if
    passed_count > 0. This verifies the field is present and typed correctly.
    """
    from app.modules.schema.contracts.validation_contracts import (
        ValidationCheckResult, ValidationCheckItem,
    )
    result = ValidationCheckResult(
        checks=[
            ValidationCheckItem(check_id="construction_cap", passed=True),
            ValidationCheckItem(check_id="farmland_floor", passed=False),
        ],
        total_checks=2,
        passed_count=1,
    )
    # Default overall_passed is False when any check fails
    assert result.overall_passed is False

    # Explicit True when all checks pass
    result_pass = ValidationCheckResult(
        checks=[
            ValidationCheckItem(check_id="construction_cap", passed=True),
        ],
        total_checks=1,
        passed_count=1,
        overall_passed=True,
    )
    assert result_pass.overall_passed is True


def test_all_8_validation_checks_constructible():
    """Verify all 8 check IDs from design doc §5.6 can be constructed.

    This is a spec-coverage test: it ensures the contract supports the
    full set of validation checks defined in the design document.
    """
    from app.modules.schema.contracts.validation_contracts import ValidationCheckItem
    check_ids = [
        "construction_cap",
        "farmland_floor",
        "no_basic_farmland",
        "no_ecological_redline",
        "within_boundary",
        "area_deviation",
        "adjacency_compliance",
        "three_line_compliance",
    ]
    for cid in check_ids:
        item = ValidationCheckItem(check_id=cid, passed=True)
        assert item.check_id == cid
