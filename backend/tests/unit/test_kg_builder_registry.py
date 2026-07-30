"""Tests for kg/builder/registry.py - @kg_builder, BuildContext, _get_bundle_features."""
from dataclasses import dataclass
from unittest.mock import MagicMock

from app.modules.kg.builder.registry import (
    kg_builder, get_builder, BuilderSpec, BuildContext,
    _KG_BUILDERS, _ordered_builders, _get_bundle_features,
)


class TestKGBuilderRegistry:
    def setup_method(self):
        self._saved = dict(_KG_BUILDERS)
        _KG_BUILDERS.clear()

    def teardown_method(self):
        _KG_BUILDERS.clear()
        _KG_BUILDERS.update(self._saved)

    def test_decorator_registers_function(self):
        @kg_builder("test_type", entity_type="TestEntity")
        def my_builder(kg, features, *, gis_type_ref, entry, ctx):
            pass

        assert "test_type" in _KG_BUILDERS
        spec = _KG_BUILDERS["test_type"]
        assert spec.fn is my_builder
        assert spec.entity_type == "TestEntity"
        retrieved = get_builder("test_type")
        assert retrieved is my_builder

    def test_get_builder_returns_none_for_unknown(self):
        assert get_builder("nonexistent") is None

    def test_decorator_entity_type_defaults_to_none(self):
        @kg_builder("bare_type")
        def bare_builder(kg, features, *, gis_type_ref, entry, ctx):
            pass

        assert "bare_type" in _KG_BUILDERS
        spec = _KG_BUILDERS["bare_type"]
        assert spec.entity_type is None
        assert not hasattr(bare_builder, "_kg_entity_type")


class TestBuilderSpecOrdering:
    def setup_method(self):
        self._saved = dict(_KG_BUILDERS)
        _KG_BUILDERS.clear()

    def teardown_method(self):
        _KG_BUILDERS.clear()
        _KG_BUILDERS.update(self._saved)

    def test_order_param_respected(self):
        @kg_builder("z_type", layer=1, order=20)
        def fn_z(kg, features, *, gis_type_ref, entry, ctx):
            pass

        @kg_builder("a_type", layer=1, order=10)
        def fn_a(kg, features, *, gis_type_ref, entry, ctx):
            pass

        ordered = _ordered_builders()
        assert ordered[0].gis_type_ref == "a_type"
        assert ordered[1].gis_type_ref == "z_type"

    def test_layer_sorts_before_order(self):
        @kg_builder("l2_type", layer=2, order=0)
        def fn_l2(kg, features, *, gis_type_ref, entry, ctx):
            pass

        @kg_builder("l1_type", layer=1, order=99)
        def fn_l1(kg, features, *, gis_type_ref, entry, ctx):
            pass

        ordered = _ordered_builders()
        assert ordered[0].gis_type_ref == "l1_type"
        assert ordered[1].gis_type_ref == "l2_type"

    def test_builder_spec_has_all_fields(self):
        @kg_builder("test_type", entity_type="TestEntity", layer=1, order=5)
        def fn(kg, features, *, gis_type_ref, entry, ctx):
            pass

        spec = _KG_BUILDERS["test_type"]
        assert spec.gis_type_ref == "test_type"
        assert spec.fn is fn
        assert spec.entity_type == "TestEntity"
        assert spec.layer == 1
        assert spec.order == 5

    def test_defaults_layer1_order0(self):
        @kg_builder("bare_type")
        def fn(kg, features, *, gis_type_ref, entry, ctx):
            pass

        spec = _KG_BUILDERS["bare_type"]
        assert spec.layer == 1
        assert spec.order == 0


class TestBuildContext:
    def test_build_context_defaults(self):
        ctx = BuildContext(village_name="test")
        assert ctx.village_name == "test"
        assert ctx.bbox is None
        assert ctx.constraint_index is None
        assert ctx.provenance == {}

    def test_build_context_with_all_fields(self):
        ctx = BuildContext(
            village_name="test",
            bbox=(113.0, 23.0, 114.0, 24.0),
            constraint_index="mock_idx",
            provenance={"mappings_version": "1.0"},
        )
        assert ctx.bbox == (113.0, 23.0, 114.0, 24.0)
        assert ctx.constraint_index == "mock_idx"
        assert ctx.provenance["mappings_version"] == "1.0"


class TestGetBundleFeatures:
    def test_get_bundle_features_returns_list(self):
        @dataclass
        class BundleTarget:
            group: str
            key: str

        @dataclass
        class GisLayerTypeEntry:
            bundle_target: BundleTarget

        entry = GisLayerTypeEntry(bundle_target=BundleTarget("polygons", "water_bodies"))

        bundle = MagicMock()
        bundle.polygons = {"water_bodies": [1, 2, 3]}

        result = _get_bundle_features(bundle, entry)
        assert result == [1, 2, 3]

    def test_get_bundle_features_returns_empty_for_missing(self):
        @dataclass
        class BundleTarget:
            group: str
            key: str

        @dataclass
        class GisLayerTypeEntry:
            bundle_target: BundleTarget

        entry = GisLayerTypeEntry(bundle_target=BundleTarget("polygons", "missing_key"))

        bundle = MagicMock()
        bundle.polygons = {}

        result = _get_bundle_features(bundle, entry)
        assert result == []