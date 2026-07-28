"""Tests for the extended GIS layer registry."""


def test_ingest_spec_nested_model():
    from app.modules.schema.types.layer_registry import (
        GisLayerTypeEntry,
        IngestSpec,
        Bundletarget,
    )

    spec = IngestSpec(adapter="features", feature_type="water")
    entry = GisLayerTypeEntry(
        gis_type_ref="water",
        geometry_kind="polygon",
        ingest=spec,
        bundle_target=Bundletarget(group="polygons", key="water_bodies"),
    )
    assert entry.ingest.adapter == "features"
    assert entry.bundle_target.key == "water_bodies"
    assert entry.model_dump()["gis_type_ref"] == "water"


def test_registry_built_from_yaml_only():
    from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY

    entry = GIS_LAYER_REGISTRY.get("landuse_current")
    assert entry is not None
    assert entry.ingest is not None
    assert entry.ingest.adapter == "parcels"
    assert entry.bundle_target is not None
    assert entry.bundle_target.key == "landuse_current"
    assert entry.spatial is not None
    assert not entry.spatial.is_constraint


def test_no_type_bindings_remain():
    import app.modules.schema.types.layer_registry as reg

    assert not hasattr(reg, "_TYPE_BINDINGS")


def test_no_build_from_bindings_only():
    import app.modules.schema.types.layer_registry as reg

    assert not hasattr(reg, "_build_from_bindings_only")