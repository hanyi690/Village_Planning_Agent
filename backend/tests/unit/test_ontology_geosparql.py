"""Tests for GeoSPARQL alignment in ontology.py."""
from app.modules.kg.ontology import (
    PLN, GEO, EntityTypes, Relations, SemanticPredicates, GeoPredicates,
)


class TestGeoPredicates:
    def test_has_centroid_exists(self):
        assert GeoPredicates.hasCentroid == GEO.hasCentroid

    def test_has_bounding_box_exists(self):
        assert GeoPredicates.hasBoundingBox == GEO.hasBoundingBox

    def test_as_wkt_exists(self):
        assert GeoPredicates.asWKT == GEO.asWKT

    def test_wkt_literal_exists(self):
        assert GeoPredicates.wktLiteral == GEO.wktLiteral


class TestEntityTypesGrouping:
    def test_l1_static_returns_set(self):
        result = EntityTypes.l1_static()
        assert isinstance(result, set)
        assert EntityTypes.Parcel in result
        assert EntityTypes.AdministrativeVillage in result
        assert EntityTypes.GisLayerSet in result
        assert EntityTypes.ZoneTarget not in result
        assert EntityTypes.PlannedParcel not in result

    def test_geo_feature_types_returns_list(self):
        result = EntityTypes.geo_feature_types()
        assert EntityTypes.Parcel in result
        assert EntityTypes.Road in result
        assert EntityTypes.GisLayerSet not in result
        assert EntityTypes.RasterDataset not in result

    def test_geo_subclass_decls(self):
        decls = EntityTypes.geo_subclass_decls()
        assert isinstance(decls, list)
        assert (EntityTypes.Parcel, GEO.Feature) in decls
        assert (EntityTypes.Road, GEO.Feature) in decls


class TestRelationsGrouping:
    def test_spatial_returns_set(self):
        result = Relations.spatial()
        assert isinstance(result, set)
        assert Relations.sfTouches in result
        assert Relations.nearby in result
        assert Relations.derived_from not in result


class TestSemanticPredicatesGrouping:
    def test_cognition_predicates_returns_set(self):
        result = SemanticPredicates.cognition_predicates()
        assert isinstance(result, set)
        assert SemanticPredicates.gis_type_ref in result
        assert SemanticPredicates.geometry_kind in result
        assert SemanticPredicates.contains_entity in result
        assert SemanticPredicates.taxonomic_parent in result