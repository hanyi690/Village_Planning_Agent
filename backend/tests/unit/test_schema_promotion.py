"""Test that schema layer promotion is correct and old path is removed.

Verification:
1. New import path works: from app.modules.schema import BBox, ...
2. Old import path (gis.schema) is removed — raises ModuleNotFoundError
3. SSE types are NOT in new schema package
4. Dicts/ subpackage works from new location
5. All schema sub-modules are importable from new location
6. No reverse dependencies in schema (schema does not import from tools/agent/kg)
7. Lookup functions produce correct results from new location
8. spatial_ops module works as new home for spatial_context
"""

import pytest


# ── New import path works ────────────────────────────────────────────


def test_new_import_canonical():
    from app.modules.schema.types.canonical import BBox, CRS, VillageBundle
    assert BBox is not None
    assert CRS.WGS84 == "EPSG:4326"


def test_new_import_contracts():
    from app.modules.schema.contracts.layout_contracts import ZoneIntent, AllocationResult
    assert ZoneIntent is not None


def test_new_import_spatial_types():
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel, FarmlandProtection
    assert CurrentLandUseParcel is not None
    assert FarmlandProtection is not None


def test_new_import_code_sets():
    from app.modules.schema.encodings.code_sets import get_zone_type_for_dlbm, dlbm_to_planning_zone
    assert get_zone_type_for_dlbm is not None
    assert dlbm_to_planning_zone is not None


def test_new_import_dicts():
    from app.modules.schema.encodings.dicts import get_center
    center = get_center()
    assert center is not None


def test_new_barrel_import():
    from app.modules.schema import BBox, ZoneIntent, get_zone_type_for_dlbm
    assert BBox is not None
    assert ZoneIntent is not None
    assert get_zone_type_for_dlbm is not None


def test_new_resolve_zone_type():
    from app.modules.schema import resolve_zone_type_for_dlbm
    assert resolve_zone_type_for_dlbm("0101") == "农业用地"


# ── SSE types excluded from new schema ───────────────────────────────


def test_sse_not_in_new_schema():
    with pytest.raises(ImportError, match="cannot import name"):
        from app.modules.schema import GISAnalysisData  # noqa: F401


# ── Old import path removed ──────────────────────────────────────────


def test_old_path_removed():
    """gis.schema shim directory deleted — import should fail."""
    with pytest.raises(ModuleNotFoundError):
        import app.modules.gis.schema  # noqa: F401


# ── Dicts YAML loading from new location ─────────────────────────────


def test_dicts_yaml_loaded():
    from app.modules.schema.encodings.dicts import get_center
    center = get_center()
    appendix5 = center.encoding("appendix5")
    assert appendix5 is not None


# ── No reverse dependencies ─────────────────────────────────────────


def test_no_reverse_deps_in_schema():
    """Static check: no file in app/modules/schema/ imports from app.tools, app.agent, or app.modules.kg."""
    import os
    import re
    schema_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "schema"
    )
    schema_dir = os.path.normpath(schema_dir)

    # Match actual import statements only (not docstring references)
    import_pattern = re.compile(r'^\s*from app\.(tools|agent|modules\.kg)')
    violations = []

    for root, dirs, files in os.walk(schema_dir):
        # Skip __pycache__
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if import_pattern.match(line):
                        violations.append(f"{fpath}:{lineno}: {line.strip()}")

    assert violations == [], f"Schema reverse dependencies found:\n" + "\n".join(violations)


# ── Lookup functions produce correct results ─────────────────────────


def test_lookup_functions_work():
    from app.modules.schema import (
        get_zone_type_for_dlbm,
        dlbm_to_planning_zone,
        resolve_zone_type_for_dlbm,
    )
    assert get_zone_type_for_dlbm("0101") == "农业用地"
    assert dlbm_to_planning_zone("0101") == "一般农业区"
    assert resolve_zone_type_for_dlbm("0101") == "农业用地"


def test_metrics_function_works():
    from app.modules.schema.utils.metrics import compute_land_use_metrics
    result = compute_land_use_metrics({"landuse_current_geojson": {"features": []}})
    assert result["total_area_ha"] == 0.0
    assert "construction_area_ha" in result


def test_parse_contracts_importable():
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, ZoneTarget
    intent = SpatialPlanningIntent(village_name="test")
    assert intent.village_name == "test"


# ── spatial_ops module works ─────────────────────────────────────────


def test_spatial_ops_import():
    from app.modules.spatial_ops import compute_spatial_context
    assert compute_spatial_context is not None


def test_spatial_ops_submodules():
    from app.modules.spatial_ops.geometry import _compute_centroid, _compute_total_area
    from app.modules.spatial_ops.relations import _compute_spatial_relations, _compute_zone_adjacency
    assert _compute_centroid is not None
    assert _compute_spatial_relations is not None


def test_spatial_ops_no_reverse_deps():
    """Static check: spatial_ops does not import from tools/agent/kg."""
    import os
    import re
    ops_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "spatial_ops"
    )
    ops_dir = os.path.normpath(ops_dir)

    import_pattern = re.compile(r'^\s*from app\.(tools|agent|modules\.kg)')
    violations = []

    for root, dirs, files in os.walk(ops_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if import_pattern.match(line):
                        violations.append(f"{fpath}:{lineno}: {line.strip()}")

    assert violations == [], f"SpatialOps reverse dependencies found:\n" + "\n".join(violations)
