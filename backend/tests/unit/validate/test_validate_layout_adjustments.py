"""validate_layout tool: ConstraintAdjustment -> legacy {zone, action, delta_ha} mapping (Wave N Task N5).

Gap B: report.adjustments now carries ConstraintAdjustment objects; the tool's
legacy {zone, action, delta_ha, reason, priority} consumers must normalize them
without assuming attribute access to non-existent zone/action/delta_ha fields.
"""

from app.modules.schema.contracts.validation_report_contracts import ConstraintAdjustment
from app.tools.gis.validate import _adjustment_to_legacy


def test_adjustment_to_legacy_from_constraint_adjustment():
    adj = ConstraintAdjustment(
        constraint_id="area_conservation",
        adjustment_type="relax",
        original_value="5.0",
        adjusted_value="4.0",
        reason="fix split drift",
        source_check="area_conservation",
    )
    legacy = _adjustment_to_legacy(adj)
    assert legacy["zone"] == "area_conservation"
    assert legacy["action"] == "relax"
    assert legacy["delta_ha"] == -1.0
    assert legacy["reason"] == "fix split drift"
    assert legacy["priority"] == "normal"


def test_adjustment_to_legacy_from_dict():
    legacy = _adjustment_to_legacy(
        {"zone": "生态保护区", "action": "relax", "delta_ha": 2.0, "reason": "r"}
    )
    assert legacy["zone"] == "生态保护区"
    assert legacy["delta_ha"] == 2.0
    assert legacy["priority"] == "normal"


def test_adjustment_to_legacy_non_numeric_delta_zero():
    adj = ConstraintAdjustment(
        constraint_id="classification_missing",
        adjustment_type="relax",
        original_value="non-preserve parcels carry a planning_land_use",
        adjusted_value="P001",
        reason="classify",
        source_check="classification_missing",
    )
    legacy = _adjustment_to_legacy(adj)
    assert legacy["delta_ha"] == 0.0
