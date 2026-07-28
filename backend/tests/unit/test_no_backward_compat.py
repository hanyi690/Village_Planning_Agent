"""Tests asserting no backward-compat patterns remain after v4 audit."""

import pytest


def test_spatial_types_no_hardcoded_zone_dicts():
    """SPACE_CONTROL_ZONE_TYPES/COLORS must not exist in spatial_types.py
    (they're YAML-derived in code_sets.py per v4 §2.4)."""
    from app.modules.schema.types import spatial_types
    assert not hasattr(spatial_types, "SPACE_CONTROL_ZONE_TYPES")
    assert not hasattr(spatial_types, "SPACE_CONTROL_ZONE_COLORS")


def test_classification_no_legacy_getattr():
    """Module-level __getattr__ for legacy uppercase names must be gone."""
    import importlib
    mod = importlib.import_module("app.modules.schema.encodings.classification")
    # __getattr__ on a module is only set explicitly; if it's gone, the module
    # won't have it as a regular attribute
    assert not hasattr(mod, "__getattr__"), \
        "classification.py should not have module-level __getattr__"


def test_ontology_no_deprecated_relation_aliases():
    """Deprecated relation aliases (touches, located_in, etc.) must be gone.
    Only active set: sfTouches, sfWithin, sfIntersects, sfContains, nearby,
    connected_via_road, derived_from, serves, connects."""
    from app.modules.kg.ontology import Relations
    deprecated = ["touches", "located_in", "intersects", "contains",
                  "within_zone", "designated_as", "delineates"]
    for name in deprecated:
        assert not hasattr(Relations, name), f"Relations.{name} should be removed"
    # connects is active (used in layer1.py) - keep it
    assert hasattr(Relations, "connects")


def test_ontology_no_three_zone_line_compat():
    """ThreeZone/ThreeLine compat attrs must be gone (moved to ConstraintIndex)."""
    from app.modules.kg.ontology import EntityTypes
    assert not hasattr(EntityTypes, "ThreeZone")
    assert not hasattr(EntityTypes, "ThreeLine")


def test_no_add_structured_intent_shim():
    """_add_structured_intent legacy shim must be gone; use build_intent_layer."""
    from app.modules.kg.builder.mixins import Layer3Mixin
    assert not hasattr(Layer3Mixin, "_add_structured_intent")


def test_sparql_no_deprecated_templates():
    """DEPRECATED_TEMPLATES and FRAGMENT_TO_BINDING shim must be gone."""
    from app.modules.kg.queries import sparql
    assert not hasattr(sparql, "DEPRECATED_TEMPLATES")
    assert not hasattr(sparql, "FRAGMENT_TO_BINDING")
    # Deprecated template names should not be in QUERY_TEMPLATES
    deprecated_names = {"get_protected_parcels_detail", "get_three_zones",
                        "get_three_lines", "get_indicators"}
    actual_names = set(sparql.QUERY_TEMPLATES.keys())
    assert deprecated_names.isdisjoint(actual_names), \
        f"Deprecated templates still present: {deprecated_names & actual_names}"


def test_no_getattr_defensive_patterns_on_typed_models():
    """No getattr(p, 'dlbm', '') / getattr(p, 'bsm', '') etc. on typed parcels.
    These fields are real Pydantic fields - direct access is safe.
    Exception: fields that don't exist on the model (e.g. shape_length) may keep getattr."""
    import re
    from pathlib import Path

    # Fields that ARE on typed models - getattr is unnecessary
    typed_fields = "dlbm|bsm|area_sqm|zone_type|geometry|sddlbm|ysdm|dlbm_system|planning_zone|primary_zone|mapping_provenance|layer_type"
    pattern = re.compile(rf'getattr\([a-z_]+,\s*["\'](?:{typed_fields})["\']')

    backend = Path(__file__).parent.parent.parent / "app" / "modules"
    offenders = []
    for py_file in backend.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if "# getattr intentional" in line:
                continue
            if pattern.search(line):
                offenders.append(f"{py_file}:{lineno}: {line.strip()}")

    if offenders:
        pytest.fail(
            f"Found {len(offenders)} defensive getattr on typed fields:\n"
            + "\n".join(offenders)
        )


def test_manager_no_legacy_geojson_path():
    """compute_layer1_cache_key must not accept dict (GeoJSON) input.
    get_or_build_layer1 must not have landuse_geojson/gis_data params."""
    import inspect
    from app.modules.kg.manager import compute_layer1_cache_key, KGManager

    # Must reject dict input
    try:
        compute_layer1_cache_key("test", {"features": []})
        assert False, "Should reject dict input"
    except (TypeError, ValueError):
        pass

    sig = inspect.signature(KGManager.get_or_build_layer1)
    assert "landuse_geojson" not in sig.parameters, \
        f"landuse_geojson param must be removed: {sig.parameters.keys()}"
    assert "gis_data" not in sig.parameters, \
        f"gis_data param must be removed: {sig.parameters.keys()}"

    sig2 = inspect.signature(KGManager.get_or_build_kg)
    assert "landuse_geojson" not in sig2.parameters
    assert "gis_data" not in sig2.parameters
    assert "reports" not in sig2.parameters


def test_code_sets_no_compat_aliases():
    """Backward-compat alias exports must be gone from code_sets.py."""
    from app.modules.schema.encodings import code_sets
    assert not hasattr(code_sets, "FORESTRY_CODES"), "FORESTRY_CODES alias must be removed"
    assert not hasattr(code_sets, "CONSTRUCTION_ZONE_TYPES"), "CONSTRUCTION_ZONE_TYPES alias must be removed"
    assert not hasattr(code_sets, "SPACE_CONTROL_ZONE_TYPES"), "SPACE_CONTROL_ZONE_TYPES alias must be removed"
