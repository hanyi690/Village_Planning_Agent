"""Bundle assembly logic for the data catalog.

Responsible for merging user-uploaded GeoJSON FeatureCollections into a
VillageBundle. Registered layer types route through the adapter registry;
unregistered upload types fall back to the legacy geometry-based merge so
nothing is silently dropped.
"""

from __future__ import annotations

from typing import Any, Dict

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _merge_geojson_into_bundle(
    bundle: Any,
    layer_key: str,
    geojson: Dict[str, Any],
) -> int:
    """Merge a user-uploaded GeoJSON FeatureCollection into a VillageBundle.

    Registered layer types are validated through the registry adapter and
    routed to their canonical bundle target (for example ``landuse_current``).
    Unregistered upload types (e.g. ``upload_roads``) fall back to the legacy
    geometry-based merge, stored under ``upload_{layer_key}`` so nothing is
    silently dropped.
    """
    features = geojson.get("features", [])
    if not features:
        return 0

    aliases = {
        "road": "current_road",
        "residential": "current_building",
        "annotation": "current_annotation",
        "construction_zone": "conditional_construction_zone",
        "geological_hazard_points": "geological_hazard_point",
    }
    gis_type_ref = aliases.get(layer_key, layer_key)

    from app.data.ingestion.adapters import ADAPTERS
    from app.data.model.layer_registry import GIS_LAYER_REGISTRY

    entry = GIS_LAYER_REGISTRY.get(gis_type_ref)
    if entry is not None and entry.ingest is not None:
        adapter = ADAPTERS.get(entry.ingest.adapter)
        if adapter is not None:
            result = adapter.load(geojson, entry)
            for feature in result.features:
                bundle.add(feature)
            merged = len(result.features)
            if result.warnings:
                bundle.metadata.crs_warnings.extend(result.warnings[:5])
            if merged:
                source_name = f"upload:{gis_type_ref}"
                if source_name not in bundle.metadata.provider_sources:
                    bundle.metadata.provider_sources.append(source_name)
                logger.info(
                    "[DataCatalog] Merged %d uploaded features into bundle (type=%s)",
                    merged, gis_type_ref,
                )
            return merged

    # Fallback: unregistered upload type — store under upload_{layer_key}.
    return _merge_geojson_upload_fallback(bundle, layer_key, geojson)


def _merge_geojson_upload_fallback(
    bundle: Any,
    layer_key: str,
    geojson: Dict[str, Any],
) -> int:
    """Legacy geometry-based merge for unregistered upload types.

    Routes features into the bundle point/line/polygon groups by geometry
    type and stores them under ``upload_{layer_key}`` (layer_type
    ``upload_{layer_key}``), preserving original properties as ``_raw``.
    """
    from app.data.model.base import LineFeature, PointFeature, PolygonFeature

    features = geojson.get("features", []) or []
    if not features:
        return 0

    target_key = f"upload_{layer_key}"
    merged = 0
    for f in features:
        geometry = f.get("geometry") or {}
        props = f.get("properties") or {}
        geom_type = geometry.get("type", "")
        bsm = props.get("BSM") or props.get("bsm") or ""
        try:
            if geom_type in ("Point", "MultiPoint"):
                feat = PointFeature(geometry=geometry, bsm=bsm, layer_type=target_key, _raw=props)
                bundle.points._layers.setdefault(target_key, []).append(feat)
            elif geom_type in ("LineString", "MultiLineString"):
                feat = LineFeature(geometry=geometry, bsm=bsm, layer_type=target_key, _raw=props)
                bundle.lines._layers.setdefault(target_key, []).append(feat)
            else:
                feat = PolygonFeature(geometry=geometry, bsm=bsm, layer_type=target_key, _raw=props)
                bundle.polygons._layers.setdefault(target_key, []).append(feat)
        except Exception as e:
            logger.debug("[DataCatalog] Skipping uploaded feature in %s: %s", target_key, e)
            continue
        merged += 1

    if merged:
        logger.info(
            "[DataCatalog] Merged %d uploaded features into bundle (key=%s)",
            merged, target_key,
        )
    return merged


__all__ = [
    "_merge_geojson_into_bundle",
    "_merge_geojson_upload_fallback",
]