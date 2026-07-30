"""Tests for GeoSPARQL WKT helper functions."""
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from app.modules.kg.ontology import GEO, GeoPredicates
from app.modules.kg.builder.geo_helpers import (
    add_centroid, add_bbox, format_wkt_point, format_wkt_bbox,
    parse_wkt_point, parse_wkt_bbox, add_geo_feature_type,
)


class TestFormatWktPoint:
    def test_basic(self):
        result = format_wkt_point(113.5, 23.2)
        assert result == "POINT(113.5 23.2)"

    def test_negative_coords(self):
        result = format_wkt_point(-113.5, -23.2)
        assert result == "POINT(-113.5 -23.2)"

    def test_rounds_to_6_decimals(self):
        result = format_wkt_point(113.123456789, 23.0)
        assert "113.123457" in result


class TestFormatWktBbox:
    def test_basic(self):
        result = format_wkt_bbox(113.0, 23.0, 114.0, 24.0)
        assert result.startswith("POLYGON((")
        assert "113.0 23.0" in result
        assert "114.0 24.0" in result


class TestParseWktPoint:
    def test_basic(self):
        lon, lat = parse_wkt_point("POINT(113.5 23.2)")
        assert lon == 113.5
        assert lat == 23.2

    def test_negative(self):
        lon, lat = parse_wkt_point("POINT(-113.5 -23.2)")
        assert lon == -113.5
        assert lat == -23.2

    def test_invalid_returns_none(self):
        assert parse_wkt_point("invalid") is None

    def test_empty_returns_none(self):
        assert parse_wkt_point("") is None


class TestParseWktBbox:
    def test_basic(self):
        result = parse_wkt_bbox("POLYGON((113.0 23.0, 114.0 23.0, 114.0 24.0, 113.0 24.0, 113.0 23.0))")
        assert result is not None
        assert result[0] == 113.0
        assert result[1] == 23.0
        assert result[2] == 114.0
        assert result[3] == 24.0

    def test_invalid_returns_none(self):
        assert parse_wkt_bbox("invalid") is None


class TestAddCentroid:
    def test_adds_blank_node_geometry(self):
        g = Graph()
        uri = URIRef("http://example.com/parcel1")
        add_centroid(g, uri, 113.5, 23.2)
        centroids = list(g.triples((uri, GeoPredicates.hasCentroid, None)))
        assert len(centroids) == 1
        geom_node = centroids[0][2]
        wkt_triples = list(g.triples((geom_node, GeoPredicates.asWKT, None)))
        assert len(wkt_triples) == 1
        assert "113.5" in str(wkt_triples[0][2])


class TestAddBbox:
    def test_adds_blank_node_geometry(self):
        g = Graph()
        uri = URIRef("http://example.com/village")
        add_bbox(g, uri, 113.0, 23.0, 114.0, 24.0)
        bboxes = list(g.triples((uri, GeoPredicates.hasBoundingBox, None)))
        assert len(bboxes) == 1
        geom_node = bboxes[0][2]
        wkt_triples = list(g.triples((geom_node, GeoPredicates.asWKT, None)))
        assert len(wkt_triples) == 1
        assert "POLYGON" in str(wkt_triples[0][2])


class TestAddGeoFeatureType:
    def test_adds_feature_type(self):
        g = Graph()
        uri = URIRef("http://example.com/parcel1")
        add_geo_feature_type(g, uri)
        types = list(g.objects(uri, RDF.type))
        assert GEO.Feature in types