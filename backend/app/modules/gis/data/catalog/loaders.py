"""Backward-compatible loaders — delegate to DataCatalog.

Provides drop-in replacements for legacy load_all(), load_current(),
load_planned() that use the new DataCatalog infrastructure.

Migration path:
  OLD: from app.modules.gis.data.loader import load_all
  NEW: from app.modules.gis.data.catalog.loaders import load_all

Both work identically. The new version uses DataCatalog internally.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.settings import JINTIAN_GIS_DIR
from app.modules.gis.schema.canonical import BBox
from app.utils.logger import get_logger

from ..loader import _load_geojson, _CURRENT_FILE_MAP, _PLANNED_FILE_MAP
from .catalog import DataCatalog

logger = get_logger(__name__)


# ── Legacy file-based loading (kept for direct file access) ──


def load_current() -> Dict[str, Any]:
    """Load all current status layers.

    Delegates to legacy loader for direct file access.
    """
    from ..loader import load_current as _legacy_load_current

    return _legacy_load_current()


def load_planned() -> Dict[str, Any]:
    """Load all planned (ground truth) layers.

    Delegates to legacy loader for direct file access.
    """
    from ..loader import load_planned as _legacy_load_planned

    return _legacy_load_planned()


def load_all() -> Dict[str, Any]:
    """Load both current and planned data into a single gis_data dict.

    Primary entry point for pipeline testing.
    Uses DataCatalog when available, falls back to legacy loader.
    """
    try:
        catalog = DataCatalog()
        # Check if catalog has the expected sources
        expected = set(_CURRENT_FILE_MAP.values()) | set(_PLANNED_FILE_MAP.values())
        available = set()
        for name in catalog.list_sources():
            src = catalog.get_source(name)
            meta = src.get_metadata()
            # Build key from layer_type or name
            key = getattr(src, "layer_type", "") or meta.name
            if key:
                available.add(key + "_geojson")

        # If catalog covers all expected sources, use it
        if expected <= available:
            logger.info("[CatalogLoaders] Using DataCatalog for load_all()")
            return _load_all_from_catalog(catalog)
    except Exception as e:
        logger.debug("[CatalogLoaders] DataCatalog not available: %s", e)

    # Fallback to legacy loader
    from ..loader import load_all as _legacy_load_all

    return _legacy_load_all()


def _load_all_from_catalog(catalog: DataCatalog) -> Dict[str, Any]:
    """Load all data via DataCatalog.

    Maps source names to gis_data keys using layer_type.
    """
    gis_data: Dict[str, Any] = {}

    for name in catalog.list_sources():
        try:
            src = catalog.get_source(name)
            result = src.fetch()
            if result.success and result.data_type == "geojson":
                # Build gis_data key from layer_type
                layer_type = getattr(src, "layer_type", "")
                if layer_type:
                    key = f"{layer_type}_geojson"
                else:
                    key = f"{name}_geojson"
                gis_data[key] = result.data
        except Exception as e:
            logger.warning("[CatalogLoaders] Failed to load %s: %s", name, e)

    return gis_data


# ── New DataCatalog-based loaders ──


def load_village_data(
    village_name: str = "金田村委会",
    bbox: Optional[BBox] = None,
) -> Dict[str, Any]:
    """Load all village data via DataCatalog.

    Args:
        village_name: Village name for metadata.
        bbox: Optional bounding box for spatial queries.

    Returns:
        gis_data dict with all available layers.
    """
    catalog = DataCatalog()

    if bbox is None:
        # Try to derive bbox from boundary layer
        try:
            boundary_src = catalog.get_source("jintian_boundary")
            result = boundary_src.fetch()
            if result.success and result.data_type == "geojson":
                features = result.data.get("features", [])
                if features:
                    coords = features[0].get("geometry", {}).get("coordinates", [])
                    if coords:
                        # Extract bbox from polygon coordinates
                        flat = _flatten_coords(coords)
                        lons = [c[0] for c in flat]
                        lats = [c[1] for c in flat]
                        bbox = BBox(
                            west=min(lons),
                            south=min(lats),
                            east=max(lons),
                            north=max(lats),
                        )
        except Exception as e:
            logger.warning("[CatalogLoaders] Could not derive bbox: %s", e)

    if bbox:
        return catalog.load_village_data(village_name, bbox)

    # No bbox — load all local files
    return _load_all_from_catalog(catalog)


def load_village_data_with_types(
    village_name: str = "金田村委会",
    bbox: Optional[BBox] = None,
    layer_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Load specific layer types for a village.

    Args:
        village_name: Village name.
        bbox: Bounding box.
        layer_types: Specific layer types to load. If None, loads all.

    Returns:
        gis_data dict.
    """
    catalog = DataCatalog()

    if bbox is None:
        # Default bbox for Jintian
        bbox = BBox(west=115.5, south=24.0, east=116.5, north=25.0)

    if layer_types is None:
        return catalog.load_village_data(village_name, bbox)

    results = catalog.query_by_bbox(bbox, layer_types)
    gis_data: Dict[str, Any] = {}
    for lt, result in results.items():
        if result.success and result.data_type == "geojson":
            gis_data[f"{lt}_geojson"] = result.data
    return gis_data


# ── Typed ingestion loaders (new capability) ──


def load_typed_annotations() -> Tuple[List[Any], List[str]]:
    """Load annotations as typed CurrentAnnotation models.

    Returns:
        (annotations_list, warnings_list)
    """
    from app.modules.gis.schema import ingest_feature

    ann_path = JINTIAN_GIS_DIR / "current" / "annotation.geojson"
    if not ann_path.exists():
        return [], [f"Annotation file not found: {ann_path}"]

    return ingest_feature(str(ann_path), "current_annotation")


def load_typed_roads() -> Tuple[List[Any], List[str]]:
    """Load roads as typed CurrentRoad models.

    Returns:
        (roads_list, warnings_list)
    """
    from app.modules.gis.schema import ingest_feature

    road_path = JINTIAN_GIS_DIR / "current" / "road.geojson"
    if not road_path.exists():
        return [], [f"Road file not found: {road_path}"]

    return ingest_feature(str(road_path), "current_road")


# ── Pipeline-ready combined loader (replaces script duplicates) ──


def load_gis_data_full() -> Tuple[Dict[str, Any], List[Any], List[Any]]:
    """Load all GIS data + typed annotations + typed roads.

    This is the drop-in replacement for the duplicate load_gis_data()
    functions in run_parse_pipeline.py, run_layout_pipeline.py, etc.

    Returns:
        (gis_data, annotations, roads) where:
        - gis_data: dict of GeoJSON FeatureCollections
        - annotations: typed CurrentAnnotation models
        - roads: typed CurrentRoad models
    """
    # 1. Load all GeoJSON layers
    gis_data = load_all()

    # 2. Parse annotations as typed models
    annotations, ann_warnings = load_typed_annotations()
    if ann_warnings:
        logger.debug("[load_gis_data_full] Annotation warnings: %d", len(ann_warnings))

    # 3. Parse roads as typed models
    roads, road_warnings = load_typed_roads()
    if road_warnings:
        logger.debug("[load_gis_data_full] Road warnings: %d", len(road_warnings))

    # 4. Inject typed annotation data into gis_data dict
    if annotations:
        ann_features = []
        for ann in annotations:
            feat = {"type": "Feature", "properties": {}, "geometry": getattr(ann, "geometry", {})}
            for attr in ("text", "category", "name", "注记", "分类"):
                val = getattr(ann, attr, None)
                if val:
                    feat["properties"][attr] = val
            ann_features.append(feat)
        gis_data["annotation_geojson"] = {
            "type": "FeatureCollection",
            "features": ann_features,
        }

    logger.info(
        "[load_gis_data_full] %d layers, %d annotations, %d roads",
        len(gis_data),
        len(annotations),
        len(roads),
    )

    return gis_data, annotations, roads


# ── Helpers ──


def _flatten_coords(coords: Any) -> List[List[float]]:
    """Flatten nested coordinate lists."""
    result: List[List[float]] = []
    if isinstance(coords, list) and len(coords) == 2 and isinstance(coords[0], (int, float)):
        return [coords]
    for item in coords:
        result.extend(_flatten_coords(item))
    return result


__all__ = [
    # Legacy compatible
    "load_all",
    "load_current",
    "load_planned",
    # New catalog-based
    "load_village_data",
    "load_village_data_with_types",
    # Typed ingestion
    "load_typed_annotations",
    "load_typed_roads",
    # Pipeline-ready
    "load_gis_data_full",
]
