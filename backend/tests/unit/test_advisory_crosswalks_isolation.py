"""Isolation tests for the advisory_crosswalks refactor.

Verifies that cross-system land-use mappings moved OUT of code_sets into
app.modules.schema.advisory_crosswalks, and that same-system code→name sets
stayed in code_sets.
"""

from app.modules.schema.advisory_crosswalks import (
    DLBM_TO_PLANNING_ZONE,
    ZONE_TYPE_TO_DLBMS,
    dlbm_to_planning_zone,
    get_zone_type_for_dlbm,
    DLBM_TO_ZONE_TYPE,
    DLBM_TO_PRIMARY_ZONE,
)


def test_advisory_crosswalks_exports_symbols():
    assert "0101" in DLBM_TO_PLANNING_ZONE
    assert callable(dlbm_to_planning_zone)
    assert callable(get_zone_type_for_dlbm)


def test_code_sets_no_longer_exports_crosswalks():
    import app.modules.schema.encodings.code_sets as cs
    # Planning-zone derivation stays out of code_sets (advisory-only).
    assert not hasattr(cs, "DLBM_TO_PLANNING_ZONE")
    assert not hasattr(cs, "dlbm_to_planning_zone")
    # Wave A.1 Task 8: the CURRENT functional classification of a DLBM code
    # (DLBM→zone_type) is same-system and now lives in code_sets.
    assert hasattr(cs, "get_zone_type_for_dlbm")


def test_code_sets_keeps_same_system_mappings():
    from app.modules.schema.encodings.code_sets import DLBM_TO_DLMC, GHYTBM_TO_GHYTMC
    assert "0101" in DLBM_TO_DLMC
    assert "2121" in GHYTBM_TO_GHYTMC
