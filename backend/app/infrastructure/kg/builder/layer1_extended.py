"""Layer 1 extended: additional geometry group builders (protection, buildings, terrain, boundaries, etc)."""
from typing import Any, Dict, List

from rdflib import Literal, RDF, URIRef
from rdflib.namespace import XSD

from .registry import kg_builder, BuildContext
from ..ontology import (
    PLN, PLN_NS, GEO, EntityTypes, Relations, EntityIdPolicy, SemanticPredicates,
    GEOMETRY_POLYGON, GEOMETRY_LINE, GEOMETRY_POINT, GEOMETRY_RASTER,
)
from .enrichment import derive_semantic_label, derive_legal_constraint
from .geo_helpers import add_centroid, add_bbox, add_geo_feature_type

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Predicate shortcuts
gis_type_ref = SemanticPredicates.gis_type_ref
geometry_kind = SemanticPredicates.geometry_kind
semantic_group = SemanticPredicates.semantic_group
has_semantic_label = SemanticPredicates.has_semantic_label
legal_constraint = SemanticPredicates.legal_constraint
allowed_operations = SemanticPredicates.allowed_operations


def add_protection_polygons(kg, polygons_layer) -> None:
    count = 0

    protection_groups = [
        ("farmland_protection", "永久基本农田", "farmland_protection", "forbid_construction"),
        ("ecological_redline", "生态保护红线", "ecological_protection", "forbid_construction"),
        ("historical_protection", "历史文化保护线", "historical_protection", "forbid_construction"),
        ("cultivated_land_target", "耕地保护目标", "cultivated_land_target", "restrict_construction"),
        ("urban_dev_boundary", "城镇开发边界", "urban_dev_boundary", "restrict_construction"),
        ("village_dev_boundary", "村庄建设边界", "village_dev_boundary", "allow_construction"),
        ("nature_reserves", "自然保护区", "nature_reserve", "forbid_construction"),
    ]

    for attr_name, label, ltype, constraint in protection_groups:
        for item in polygons_layer.get(attr_name) or []:
            bsm = str(item.bsm).strip()
            ysdm = str(item.ysdm).strip()
            if bsm:
                uri = EntityIdPolicy.uri(attr_name, bsm)
            else:
                uri = EntityIdPolicy.fallback_uri(attr_name, ysdm, count)
            EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
            kg.g.add((uri, RDF.type, EntityTypes.Zone))
            kg.g.add((uri, PLN.name, Literal(f"{label}_{bsm or count}")))
            kg.g.add((uri, Relations.sfWithin, PLN.village))
            kg.g.add((uri, gis_type_ref, Literal(ltype)))
            kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
            kg.g.add((uri, semantic_group, Literal("protection")))
            kg.g.add((uri, has_semantic_label, Literal(label)))
            kg.g.add((uri, legal_constraint, Literal(constraint)))
            kg.g.add((uri, allowed_operations, Literal("verify_only")))
            add_geo_feature_type(kg.g, uri)
            count += 1

    if count:
        logger.info("Added %d protection polygons", count)


@kg_builder("current_building", entity_type="Facility", layer=1, order=50)
def add_buildings(kg, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    count = 0
    for i, b in enumerate(features):
        bsm = str(b.bsm).strip()
        ysdm = str(b.ysdm).strip()
        name = f"建筑_{bsm or i}"
        if bsm:
            uri = EntityIdPolicy.uri("building", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("building", ysdm, i)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.Facility))
        kg.g.add((uri, PLN.name, Literal(name)))
        kg.g.add((uri, PLN.facility_type, Literal("建筑")))
        geom = b.geometry or {}
        coords = geom.get("coordinates", [0, 0]) if isinstance(geom, dict) else [0, 0]
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            add_centroid(kg.g, uri, coords[0], coords[1])
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("current_building")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        kg.g.add((uri, semantic_group, Literal("building")))
        kg.g.add((uri, has_semantic_label, Literal(name)))
        add_geo_feature_type(kg.g, uri)
        count += 1
    if count:
        logger.info("Added %d buildings", count)
    return {"count": count, "entity_type": "Building"}


def add_terrain_entities(kg, lines_layer, points_layer) -> None:
    count = 0
    for i, c in enumerate(lines_layer.get("contour_lines") if hasattr(lines_layer, "get") else []):
        bsm = str(c.bsm).strip()
        ysdm = str(c.ysdm).strip()
        elev = c.elevation or ""
        if bsm:
            uri = EntityIdPolicy.uri("contour", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("contour", ysdm, i)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.Road))
        kg.g.add((uri, PLN.name, Literal(f"等高线_{elev or bsm or i}")))
        if elev:
            kg.g.add((uri, PLN.elevation, Literal(str(elev))))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("contour_line")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_LINE)))
        kg.g.add((uri, semantic_group, Literal("terrain")))
        kg.g.add((uri, has_semantic_label, Literal(f"等高线{elev}m")))
        count += 1

    for i, ep in enumerate(points_layer.get("elevation_points") or []):
        bsm = str(ep.bsm).strip()
        ysdm = str(ep.ysdm).strip()
        elev = ep.elevation or getattr(ep, "height", "") or ""
        geom = ep.geometry or {}
        coords = geom.get("coordinates", [0, 0]) if isinstance(geom, dict) else [0, 0]
        if bsm:
            uri = EntityIdPolicy.uri("elevpt", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("elevpt", ysdm, i)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.Facility))
        kg.g.add((uri, PLN.name, Literal(f"高程点_{elev or i}")))
        if elev:
            kg.g.add((uri, PLN.elevation, Literal(str(elev))))
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            add_centroid(kg.g, uri, coords[0], coords[1])
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("elevation_point")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        kg.g.add((uri, semantic_group, Literal("terrain")))
        kg.g.add((uri, has_semantic_label, Literal(f"高程{elev}m")))
        add_geo_feature_type(kg.g, uri)
        count += 1

    if count:
        logger.info("Added %d terrain entities (contours + elevation points)", count)


def add_boundaries(kg, polygons_layer, lines_layer) -> None:
    count = 0
    for i, a in enumerate(polygons_layer.get("admin_areas") if hasattr(polygons_layer, "get") else []):
        bsm = str(a.bsm).strip()
        ysdm = str(a.ysdm).strip()
        name = f"行政区_{bsm or i}"
        if bsm:
            uri = EntityIdPolicy.uri("admin", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("admin", ysdm, i)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.AdministrativeVillage))
        kg.g.add((uri, PLN.name, Literal(name)))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("admin_area")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        kg.g.add((uri, semantic_group, Literal("admin")))
        kg.g.add((uri, has_semantic_label, Literal(name)))
        count += 1

    for i, ps in enumerate(polygons_layer.get("planning_scope") if hasattr(polygons_layer, "get") else []):
        bsm = str(ps.bsm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("scope", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("scope", "scope", i)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.Zone))
        kg.g.add((uri, PLN.name, Literal("规划范围")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("planning_scope")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        kg.g.add((uri, semantic_group, Literal("admin")))
        kg.g.add((uri, has_semantic_label, Literal("规划范围")))
        add_geo_feature_type(kg.g, uri)
        kg.g.add((PLN.village, PLN.has_planning_scope, Literal(True)))
        count += 1

    for i, bl in enumerate(lines_layer.get("admin_boundaries") or []):
        bsm = str(bl.bsm).strip()
        ysdm = str(bl.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("adminline", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("adminline", ysdm, i)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.Road))
        kg.g.add((uri, PLN.name, Literal(f"行政界线_{bsm or i}")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("admin_boundary_line")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_LINE)))
        kg.g.add((uri, semantic_group, Literal("admin")))
        kg.g.add((uri, has_semantic_label, Literal("行政界线")))
        count += 1

    if count:
        logger.info("Added %d boundary entities", count)


def add_natural_resource_zones(kg, polygons_layer) -> None:
    count = 0
    nr_groups = [
        ("soil_types", "土壤类型", "soil_type"),
        ("soil_erosions", "土壤侵蚀", "soil_erosion"),
        ("watersheds", "流域", "watershed"),
        ("hydrogeology_zones", "水文地质分区", "hydrogeology_zone"),
    ]
    for attr_name, label, ltype in nr_groups:
        for i, item in enumerate(polygons_layer.get(attr_name) or []):
            bsm = str(item.bsm).strip()
            ysdm = str(item.ysdm).strip()
            if bsm:
                uri = EntityIdPolicy.uri(attr_name, bsm)
            else:
                uri = EntityIdPolicy.fallback_uri(attr_name, ysdm, i)
            EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
            kg.g.add((uri, RDF.type, EntityTypes.Zone))
            kg.g.add((uri, PLN.name, Literal(f"{label}_{bsm or i}")))
            kg.g.add((uri, Relations.sfWithin, PLN.village))
            kg.g.add((uri, gis_type_ref, Literal(ltype)))
            kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
            kg.g.add((uri, semantic_group, Literal("natural_resource")))
            kg.g.add((uri, has_semantic_label, Literal(label)))
            add_geo_feature_type(kg.g, uri)
            count += 1
    if count:
        logger.info("Added %d natural resource zones", count)


@kg_builder("dem", entity_type="RasterDataset", layer=1, order=70)
def add_dem_raster(kg, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    count = 0
    for i, dem in enumerate(features):
        if dem is None:
            continue
        uri = EntityIdPolicy.uri("dem", f"dem_{i}")
        kg.g.add((uri, RDF.type, EntityTypes.RasterDataset))
        kg.g.add((uri, PLN.name, Literal("数字高程模型")))
        kg.g.add((uri, gis_type_ref, Literal("dem")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_RASTER)))
        kg.g.add((uri, semantic_group, Literal("terrain")))
        kg.g.add((uri, has_semantic_label, Literal("DEM数字高程模型")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        path = getattr(dem, "path", "") or ""
        if path:
            kg.g.add((uri, PLN.path, Literal(path)))
        crs = getattr(dem, "crs", "") or ""
        if crs:
            kg.g.add((uri, PLN.crs, Literal(str(crs))))
        res = getattr(dem, "resolution", 0.0)
        if res:
            kg.g.add((uri, PLN.resolution, Literal(float(res), datatype=XSD.double)))
        bounds = getattr(dem, "bounds", None)
        if bounds and isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            add_bbox(kg.g, uri, float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
        w = getattr(dem, "width", 0)
        h = getattr(dem, "height", 0)
        if w:
            kg.g.add((uri, PLN.width, Literal(int(w), datatype=XSD.integer)))
        if h:
            kg.g.add((uri, PLN.height, Literal(int(h), datatype=XSD.integer)))
        count += 1
    if count:
        logger.info("Added %d DEM raster entities", count)
    return {"count": count, "entity_type": "RasterDataset"}