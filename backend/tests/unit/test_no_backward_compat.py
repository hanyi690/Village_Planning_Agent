"""Tests asserting no backward-compat patterns remain after v4 audit."""


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
