"""Test that schema layer promotion is correct and old path is removed.

Trimmed in V4 audit: reverse-dep tests moved to test_architecture_invariants.py,
lookup tests moved to test_encoding_consistency.py.
Kept: import-failure assertions + positive import-path verification.
"""

import pytest


# ── New import path works ────────────────────────────────────────────


def test_new_import_canonical():
    from app.modules.schema.types.canonical import BBox, CRS, VillageBundle
    assert BBox is not None
    assert CRS.WGS84 == "EPSG:4326"


def test_new_import_contracts():
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    assert SiteSelectionDecision is not None


def test_new_import_spatial_types():
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel, FarmlandProtection
    assert CurrentLandUseParcel is not None
    assert FarmlandProtection is not None


def test_new_import_code_sets():
    from app.modules.schema.advisory_crosswalks import get_zone_type_for_dlbm, dlbm_to_planning_zone
    assert get_zone_type_for_dlbm is not None
    assert dlbm_to_planning_zone is not None


def test_new_import_dicts():
    from app.modules.schema.encodings.dicts import get_center
    center = get_center()
    assert center is not None


def test_new_barrel_import():
    from app.modules.schema import BBox
    from app.modules.schema.advisory_crosswalks import get_zone_type_for_dlbm
    assert BBox is not None
    assert get_zone_type_for_dlbm is not None


# ── SSE types excluded from new schema ───────────────────────────────


def test_sse_not_in_new_schema():
    with pytest.raises(ImportError, match="cannot import name"):
        from app.modules.schema import GISAnalysisData  # noqa: F401


# ── Old import path removed ──────────────────────────────────────────


def test_old_path_removed():
    """gis.schema shim directory deleted - import should fail."""
    with pytest.raises(ModuleNotFoundError):
        import app.modules.gis.schema  # noqa: F401


# ── Dicts YAML loading from new location ─────────────────────────────


def test_dicts_yaml_loaded():
    from app.modules.schema.encodings.dicts import get_center
    center = get_center()
    appendix5 = center.encoding("appendix5")
    assert appendix5 is not None


def test_metrics_function_works():
    from app.modules.schema.utils.metrics import compute_land_use_metrics
    result = compute_land_use_metrics({"landuse_current_geojson": {"features": []}})
    assert result["total_area_ha"] == 0.0
    assert "construction_area_ha" in result


# ── spatial_ops module works ─────────────────────────────────────────


def test_spatial_ops_import():
    from app.modules.spatial_ops import compute_spatial_context
    assert compute_spatial_context is not None


def test_spatial_ops_submodules():
    from app.modules.spatial_ops.geometry import _compute_centroid, _compute_total_area
    from app.modules.spatial_ops.geometry.relations import _compute_spatial_relations, _compute_zone_adjacency
    assert _compute_centroid is not None
    assert _compute_spatial_relations is not None
