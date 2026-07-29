"""Tests for kg/builder/registry.py — @kg_builder, BuildContext, _get_bundle_features."""
import pytest
from rdflib import URIRef


class TestKGBuilderRegistry:
    def _save_and_clear_builders(self):
        from app.modules.kg.builder.registry import _KG_BUILDERS
        saved = dict(_KG_BUILDERS)
        _KG_BUILDERS.clear()
        return saved

    def _restore_builders(self, saved):
        from app.modules.kg.builder.registry import _KG_BUILDERS
        _KG_BUILDERS.clear()
        _KG_BUILDERS.update(saved)

    def test_decorator_registers_function(self):
        from app.modules.kg.builder.registry import kg_builder, _KG_BUILDERS, get_builder
        saved = self._save_and_clear_builders()
        try:
            @kg_builder("test_type", entity_type="TestEntity")
            def my_builder(self, features, *, gis_type_ref, entry, ctx):
                return {"count": len(features)}
            assert "test_type" in _KG_BUILDERS
            assert get_builder("test_type") is my_builder
            assert getattr(my_builder, "_kg_entity_type", None) == "TestEntity"
        finally:
            self._restore_builders(saved)

    def test_get_builder_returns_none_for_unknown(self):
        from app.modules.kg.builder.registry import get_builder
        assert get_builder("nonexistent") is None

    def test_decorator_entity_type_defaults_to_none(self):
        from app.modules.kg.builder.registry import kg_builder, _KG_BUILDERS
        saved = self._save_and_clear_builders()
        try:
            @kg_builder("bare_type")
            def bare_builder(self, features, *, gis_type_ref, entry, ctx):
                return {"count": len(features)}
            assert "bare_type" in _KG_BUILDERS
            assert not hasattr(bare_builder, "_kg_entity_type")
        finally:
            self._restore_builders(saved)


class TestBuildContext:
    def test_build_context_defaults(self):
        from app.modules.kg.builder.registry import BuildContext
        ctx = BuildContext(village_name="test")
        assert ctx.village_name == "test"
        assert ctx.bbox is None
        assert ctx.constraint_index is None
        assert ctx.provenance == {}

    def test_build_context_with_all_fields(self):
        from app.modules.kg.builder.registry import BuildContext
        ctx = BuildContext(
            village_name="金田",
            bbox=(113.0, 23.0, 114.0, 24.0),
            constraint_index="mock_idx",
            provenance={"mappings_version": "1.0"},
        )
        assert ctx.bbox == (113.0, 23.0, 114.0, 24.0)
        assert ctx.constraint_index == "mock_idx"
        assert ctx.provenance["mappings_version"] == "1.0"


class TestGetBundleFeatures:
    def test_get_bundle_features_returns_list(self):
        from app.modules.kg.builder.registry import _get_bundle_features
        from app.modules.schema.types.layer_registry import GisLayerTypeEntry, Bundletarget, IngestSpec
        mock_entry = GisLayerTypeEntry(
            gis_type_ref="water",
            geometry_kind="polygon",
            description="test",
            ingest=IngestSpec(adapter="features", feature_type="water"),
            bundle_target=Bundletarget(group="polygons", key="water_bodies"),
        )
        class MockBundle:
            pass
        bundle = MockBundle()
        bundle.polygons = type("Polygons", (), {"water_bodies": [1, 2, 3]})()
        result = _get_bundle_features(bundle, mock_entry)
        assert result == [1, 2, 3]

    def test_get_bundle_features_returns_empty_for_missing(self):
        from app.modules.kg.builder.registry import _get_bundle_features
        from app.modules.schema.types.layer_registry import GisLayerTypeEntry, Bundletarget, IngestSpec
        mock_entry = GisLayerTypeEntry(
            gis_type_ref="nonexistent",
            geometry_kind="polygon",
            description="test",
            ingest=IngestSpec(adapter="features", feature_type="x"),
            bundle_target=Bundletarget(group="polygons", key="no_such_key"),
        )
        class MockBundle:
            polygons = {}
        result = _get_bundle_features(MockBundle(), mock_entry)
        assert result == []