"""Test schema boundary contracts left after the V4 audit."""

import pytest


def test_sse_not_in_new_schema():
    with pytest.raises(ImportError, match="cannot import name"):
        from app.modules.schema import GISAnalysisData  # noqa: F401


def test_old_path_removed():
    """The deleted gis.schema shim must not be importable."""
    with pytest.raises(ModuleNotFoundError):
        import app.modules.gis.schema  # noqa: F401


def test_metrics_function_works():
    from app.modules.schema.utils.metrics import compute_land_use_metrics

    result = compute_land_use_metrics({"landuse_current_geojson": {"features": []}})
    assert result["total_area_ha"] == 0.0
    assert "construction_area_ha" in result
