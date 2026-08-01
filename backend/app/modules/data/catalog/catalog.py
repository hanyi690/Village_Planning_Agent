"""Data catalog - unified entry point for all data sources.

Loads YAML configuration, initializes drivers via DriverRegistry, and
provides query methods for spatial data retrieval.

Usage:
    from app.modules.data import DataCatalog

    catalog = DataCatalog()
    result = catalog.get_source("jintian_current_landuse").fetch()

Phase 1: skeleton with config loading and source initialization.
Connection instantiation (Phase 2) and concrete drivers (Phase 3) are
wired in later phases. Until then, sources whose driver is not yet
registered are skipped with a warning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.modules.schema.types.canonical import BBox, VillageBundle, VillageMetadata
from app.utils.logger import get_logger

from ..contracts import DataResult, DataSourceMetadata
from ..sources import DataSourceDriver, DriverRegistry
from .config import CatalogConfig

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent / "sources.yaml"


def _merge_geojson_into_bundle(
    bundle: Any,
    layer_key: str,
    geojson: Dict[str, Any],
) -> int:
    """Merge a user-uploaded GeoJSON FeatureCollection into a VillageBundle.

    Features are routed into the bundle's point/line/polygon groups by geometry
    type and stored under ``upload_{layer_key}``. Original properties are kept
    as ``_raw`` on each feature so nothing is lost on snapshot.
    """
    from app.modules.schema.types.base import LineFeature, PointFeature, PolygonFeature

    features = geojson.get("features", [])
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


def _extract_coords(geometry: Dict[str, Any], out: List[Tuple[float, float]]) -> None:
    """Recursively extract (lon, lat) coordinate pairs from a GeoJSON geometry."""
    geom_type = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if geom_type == "Point":
        if len(coords) >= 2:
            out.append((coords[0], coords[1]))
    elif geom_type in ("LineString", "MultiPoint"):
        for c in coords:
            if len(c) >= 2:
                out.append((c[0], c[1]))
    elif geom_type in ("Polygon", "MultiLineString"):
        for ring in coords:
            for c in ring:
                if len(c) >= 2:
                    out.append((c[0], c[1]))
    elif geom_type == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                for c in ring:
                    if len(c) >= 2:
                        out.append((c[0], c[1]))


class DataCatalog:
    """Data catalog - manages all configured data sources.

    Lifecycle:
        1. Load YAML configuration (sources + connections)
        2. Register connections (Phase 2)
        3. Instantiate drivers via DriverRegistry
        4. Query sources by name or layer_type
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._connections: Dict[str, Dict[str, Any]] = {}
        self._sources_cfg: Dict[str, Dict[str, Any]] = {}
        self._sources: Dict[str, DataSourceDriver] = {}
        self._load_config()
        self._init_connections()
        self._init_sources()

    # ── configuration loading ──

    def _load_config(self) -> None:
        if not self.config_path.exists():
            logger.warning(
                "[DataCatalog] Config not found: %s. Using empty catalog.",
                self.config_path,
            )
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        try:
            catalog = CatalogConfig(**raw)
            self._connections = catalog.connections
            self._sources_cfg = catalog.sources
            logger.info(
                "[DataCatalog] Loaded %d sources, %d connections from %s",
                len(self._sources_cfg),
                len(self._connections),
                self.config_path,
            )
        except Exception as e:
            logger.error("[DataCatalog] Config validation failed: %s", e)
            raise

    # ── connection initialization (Phase 2 stub) ──

    def _init_connections(self) -> None:
        """Instantiate and register connections from YAML declarations."""
        from ..connections import ConnectionRegistry
        from ..connections.amap import AmapConnection
        from ..connections.gd_tianditu import GDTiandituConnection
        from ..connections.osm import OSMConnection
        from ..connections.tianditu import TiandituConnection

        _classes = {
            "tianditu": TiandituConnection,
            "amap": AmapConnection,
            "gd_tianditu": GDTiandituConnection,
            "osm": OSMConnection,
        }

        for name, cfg in self._connections.items():
            conn_cls = _classes.get(cfg.type)
            if conn_cls is None:
                logger.warning(
                    "[DataCatalog] Unknown connection type '%s' for '%s'. Skipping.",
                    cfg.type,
                    name,
                )
                continue
            try:
                conn = conn_cls()
                ConnectionRegistry.register(conn)
            except Exception as e:
                logger.error(
                    "[DataCatalog] Failed to init connection '%s': %s",
                    name,
                    e,
                )

    # ── source initialization ──

    def _init_sources(self) -> None:
        from app.core.settings import PROJECT_ROOT

        for name, cfg in self._sources_cfg.items():
            driver_name = cfg.get("driver", "")
            if not DriverRegistry.has_driver(driver_name):
                logger.warning(
                    "[DataCatalog] Driver '%s' not registered for source '%s'. "
                    "Skipping (will be available after Phase 3 migration).",
                    driver_name,
                    name,
                )
                continue

            try:
                driver_cls = DriverRegistry.get(driver_name)
                resolved_cfg = self._resolve_paths(cfg, PROJECT_ROOT)
                self._sources[name] = driver_cls(resolved_cfg)
                logger.info(
                    "[DataCatalog] Initialized source: %s (driver=%s)",
                    name,
                    driver_name,
                )
            except Exception as e:
                logger.error(
                    "[DataCatalog] Failed to init source '%s': %s",
                    name,
                    e,
                )

    @staticmethod
    def _resolve_paths(cfg: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
        """Resolve relative paths in config against project root."""
        resolved = dict(cfg)
        for key in ("path", "cache_dir", "local_path"):
            if key in resolved:
                p = Path(resolved[key])
                if not p.is_absolute():
                    resolved[key] = str(project_root / p)
        return resolved

    # ── query API ──

    def get_source(self, name: str) -> DataSourceDriver:
        """Get a data source by name.

        Raises:
            KeyError: if source name is not found.
        """
        if name not in self._sources:
            available = list(self._sources.keys())
            raise KeyError(f"Unknown source: {name}. Available: {available}")
        return self._sources[name]

    def list_sources(self) -> List[str]:
        """Return all initialized source names."""
        return list(self._sources.keys())

    def find_source_by_layer_type(self, layer_type: str) -> Optional[DataSourceDriver]:
        """Find the first source supporting a given layer_type."""
        sources = self.find_sources_by_layer_type(layer_type)
        return sources[0] if sources else None

    def find_sources_by_layer_type(self, layer_type: str) -> List[DataSourceDriver]:
        """Find all sources supporting a given layer_type, in YAML config order."""
        matched: List[DataSourceDriver] = []
        for name, source in self._sources.items():
            cfg = self._sources_cfg.get(name, {})
            if cfg.get("layer_type") == layer_type:
                matched.append(source)
                continue
            for layer in cfg.get("layers", []):
                if layer.get("layer_type") == layer_type:
                    matched.append(source)
                    break
        return matched

    def query_by_bbox(
        self,
        bbox: BBox,
        layer_types: List[str],
    ) -> Dict[str, DataResult]:
        """Query multiple layer types by bounding box.

        For each layer_type, tries all configured sources in YAML config order
        until one succeeds (implements priority/source-fallback).
        If all sources for a layer_type fail, returns the last failure.

        Returns:
            Dict mapping layer_type to DataResult.
        """
        results: Dict[str, DataResult] = {}
        for lt in layer_types:
            sources = self.find_sources_by_layer_type(lt)
            if not sources:
                results[lt] = DataResult.fail(
                    error=f"No source configured for layer_type: {lt}"
                )
                continue
            last_error = ""
            for source in sources:
                try:
                    result = source.fetch(bbox=bbox, layer_type=lt)
                    if result.success:
                        results[lt] = result
                        break
                    last_error = result.error or "unknown error"
                except Exception as e:
                    logger.warning(
                        "[DataCatalog] Source failed for %s: %s", lt, e
                    )
                    last_error = str(e)
            else:
                # All sources failed
                results[lt] = DataResult.fail(
                    error=f"All sources failed for {lt}: {last_error}"
                )
        return results

    # gis_type_ref -> (ingest port, ingest arg) mapping for typed bundle loading.
    # Derived from GIS_LAYER_REGISTRY (T6). Kept as backward compat property.
    @classmethod
    @property
    def _TYPED_LAYER_MAP(cls):
        """Backward compat -- derived from GIS_LAYER_REGISTRY."""
        from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY
        return {
            lt: (e.ingest.adapter, e.ingest.feature_type) if e.ingest else None
            for lt, e in GIS_LAYER_REGISTRY.items()
        }

    def load_village_bundle(
        self,
        village_name: str,
        layer_types: Optional[List[str]] = None,
    ):
        """Load village data bundle — morphology-first, no bbox required.

        Flow:
          1. Load boundary first (file_vector ignores bbox)
          2. Derive bbox from boundary geometry
          3. Fallback: geocode village_name if no boundary
          4. Load all layers (file_vector ignores bbox, api_vector uses it)
          5. Return typed VillageBundle with morphology groups populated

        Args:
            village_name: village name for metadata and geocode fallback.
            layer_types: specific layer types to load. If None, loads all
                configured sources whose layer_type is in ``GIS_LAYER_REGISTRY``.

        Returns:
            ``VillageBundle`` with points/lines/polygons/rasters morphology groups.
        """
        from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY

        if layer_types is None:
            layer_types = list(GIS_LAYER_REGISTRY.keys())

        # Step 1: Load boundary first (no bbox needed for file_vector)
        bbox = None
        bundle = VillageBundle(village_name=village_name)

        boundary_result = self._load_boundary(village_name)
        if boundary_result and boundary_result.success:
            # Step 2: Derive bbox from boundary geometry
            bbox = self._derive_bbox_from_boundary(boundary_result.data)
            # Assign boundary: ingest as AdminArea via result_to_features
            from ..ingest import result_to_features
            admin_features, _ = result_to_features(boundary_result, "admin_area")
            if admin_features:
                for a in admin_features:
                    bundle.add(a)

        # Step 2b: Fallback — geocode if no boundary
        if bbox is None:
            bbox = self._geocode_village(village_name)

        # Step 3: Load all layers via query_by_bbox (file_vector ignores bbox)
        results = self.query_by_bbox(bbox, layer_types) if bbox else {}

        # Step 4: Build typed bundle from results
        for lt, result in results.items():
            if not result.success:
                logger.warning("[DataCatalog] Skipping %s: %s", lt, result.error)
                continue
            if lt == "boundary":
                # Already loaded in Step 1
                continue
            if result.data_type == "url":
                # API source fell back to a WMS imagery URL (visualization only,
                # no vector data). There is nothing to ingest -- skip instead of
                # letting the adapter crash on a non-FeatureCollection payload.
                logger.warning(
                    "[DataCatalog] Skipping %s: WMS URL only (no vector data)",
                    lt,
                )
                continue
            entry = GIS_LAYER_REGISTRY.get(lt)
            if entry is None or entry.ingest is None:
                logger.debug(
                    "[DataCatalog] Layer '%s' has no ingest spec -- skipping "
                    "(inference pipeline not yet active)", lt,
                )
                continue

            adapter_name = entry.ingest.adapter
            from ..adapters import ADAPTERS
            adapter = ADAPTERS.get(adapter_name)
            if adapter is None:
                logger.warning(
                    "[DataCatalog] No adapter registered for '%s' (layer '%s')",
                    adapter_name, lt,
                )
                continue
            adapter_result = adapter.load(result.data, entry)
            if adapter_result.warnings:
                bundle.metadata.crs_warnings.extend(adapter_result.warnings[:5])
            for feat in adapter_result.features:
                bundle.add(feat)

        # Step 4b: Fallback — derive water bodies from DLBM=31xx parcels
        # when external water sources (upload / Tianditu API) are unavailable.
        if not bundle.polygons.get("water_bodies") and bundle.polygons.get("landuse_current"):
            from app.modules.schema.types.spatial_types import WaterFeature
            generated = 0
            for p in bundle.polygons.get("landuse_current"):
                dlbm = p.dlbm or ""
                if dlbm.startswith("31"):
                    wf = WaterFeature(
                        geometry=p.geometry,
                        bsm=p.bsm,
                        ysdm=p.ysdm,
                        layer_type="water",
                        water_type={
                            "3101": "河流",
                            "3102": "湖泊",
                            "3103": "水库",
                            "3104": "坑塘",
                            "3105": "沟渠",
                        }.get(dlbm[:4], "坑塘"),
                        water_name=p.name or "",
                    )
                    bundle.add(wf)
                    generated += 1
            if generated:
                logger.info(
                    "[DataCatalog] Derived %d water bodies from DLBM=31xx parcels",
                    generated,
                )

        bundle.metadata.provider_sources = list(results.keys())
        if bbox:
            bundle.metadata.bbox_wgs84 = bbox

        logger.info(
            "[DataCatalog] load_village_bundle('%s'): %d parcels, %d roads, %d annotations",
            village_name,
            bundle.parcel_count,
            len(bundle.lines.get("roads_current")) + len(bundle.lines.get("roads_planned")),
            len(bundle.points.get("annotations_current")) + len(bundle.points.get("annotations_planned")),
        )
        return bundle

    async def load_village_bundle_async(
        self,
        village_name: str,
        session_id: Optional[str] = None,
        layer_types: Optional[List[str]] = None,
    ):
        """Session-level build entry for a VillageBundle.

        Loads the spatial data via the synchronous ``load_village_bundle``
        (unchanged, reuse), then — when ``session_id`` is given — populates the
        session context onto the same bundle instance:
          * ``metadata``: session_id / planning_period / admin hierarchy
          * ``documents.planning_texts``: village_data text, task description,
            constraints, uploaded file parsed text, project planning docs
          * ``layer_reports``: full L1/L2/L3 report contents from the DB

        Returns a session-scoped ``VillageBundle``.
        """
        bundle = self.load_village_bundle(village_name, layer_types=layer_types)
        if session_id:
            await self._populate_session_context(bundle, session_id)
        return bundle

    async def _populate_session_context(
        self,
        bundle: VillageBundle,
        session_id: str,
    ) -> None:
        """Fill session-level context onto a VillageBundle (async DB reads)."""
        from datetime import datetime

        from app.database.operations import (
            get_planning_session_async,
            get_session_reports_async,
            get_uploaded_files_by_session_async,
        )

        session = await get_planning_session_async(session_id)
        if session:
            bundle.metadata.session_id = session_id
            bundle.metadata.planning_period = session.get("planning_period", "")
            bundle.metadata.province = session.get("province", "")
            bundle.metadata.city = session.get("city", "")
            bundle.metadata.county = session.get("county", "")
            bundle.metadata.township = session.get("township", "")

            texts = [
                {"source": "village_data", "name": "村庄基础数据", "content": session.get("village_data") or ""},
                {"source": "task_description", "name": "任务描述", "content": session.get("task_description") or ""},
                {"source": "constraints", "name": "约束条件", "content": session.get("constraints") or ""},
            ]
            bundle.documents.planning_texts = [
                t for t in texts if t["content"].strip()
            ]

        try:
            uploaded = await get_uploaded_files_by_session_async(session_id)
        except Exception as e:
            logger.warning("[DataCatalog] Uploaded files load failed for %s: %s", session_id, e)
            uploaded = []
        for f in uploaded:
            text = f.get("parsed_text") or ""
            if not text.strip():
                continue
            bundle.documents.planning_texts.append({
                "source": "upload",
                "category": f.get("file_category", ""),
                "name": f.get("original_filename") or f.get("filename", ""),
                "content": text,
            })

        # Merge uploaded GIS data (spatial) into the bundle groups so the
        # snapshot carries user uploads as features, not just parsed text.
        try:
            uploaded_gis = await get_uploaded_files_by_session_async(
                session_id, file_category="gis_data",
            )
        except Exception as e:
            logger.warning("[DataCatalog] Uploaded GIS load failed for %s: %s", session_id, e)
            uploaded_gis = []
        for item in uploaded_gis:
            geojson = item.get("gis_data") or {}
            if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
                continue
            dtype = item.get("gis_data_type") or "upload"
            _merge_geojson_into_bundle(bundle, dtype, geojson)

        try:
            from app.modules.data.documents.loader import list_available_documents, load_planning_text
            from pathlib import Path
            for doc in list_available_documents(bundle.village_name):
                path = doc.get("path", "")
                if not path:
                    continue
                try:
                    content = Path(path).read_text(encoding="utf-8")
                except Exception:
                    continue
                bundle.documents.planning_texts.append({
                    "source": "project_doc",
                    "type": doc.get("type", "unknown"),
                    "name": doc.get("name", ""),
                    "content": content,
                })
        except Exception as e:
            logger.debug("[DataCatalog] Project docs load skipped: %s", e)

        bundle.layer_reports = await get_session_reports_async(session_id)
        bundle.metadata.bundle_version = "1.0"
        bundle.metadata.built_at = datetime.now().isoformat()

    # ── Boundary-first helpers ──

    def _load_boundary(self, village_name: str) -> Optional[DataResult]:
        """Load boundary layer first (no bbox needed for file_vector)."""
        source = self.find_source_by_layer_type("boundary")
        if source is None:
            logger.debug("[DataCatalog] No boundary source configured")
            return None
        try:
            return source.fetch()  # file_vector ignores bbox
        except Exception as e:
            logger.warning("[DataCatalog] Boundary load failed: %s", e)
            return None

    @staticmethod
    def _derive_bbox_from_boundary(geojson: Dict[str, Any]) -> Optional[BBox]:
        """Derive BBox from boundary GeoJSON geometry.

        Extracts all coordinates from the boundary features and computes
        the axis-aligned bounding box. Returns None if no valid coordinates.
        """
        if not isinstance(geojson, dict):
            return None
        features = geojson.get("features", [])
        if not features:
            return None

        all_coords: List[Tuple[float, float]] = []
        for f in features:
            geom = f.get("geometry", {})
            _extract_coords(geom, all_coords)

        if not all_coords:
            return None

        lons = [c[0] for c in all_coords]
        lats = [c[1] for c in all_coords]
        bbox = BBox(west=min(lons), south=min(lats), east=max(lons), north=max(lats))
        if bbox.is_valid():
            return bbox
        return None

    def _geocode_village(self, village_name: str) -> Optional[BBox]:
        """Fallback: geocode village name to bbox (when no boundary data).

        Tries Tianditu geocode first, then POI search in the county region.
        Returns a 5km buffer bbox around the located point, or None.
        """
        from ..connections import ConnectionRegistry

        conn = ConnectionRegistry.get("tianditu")
        if conn is None:
            logger.debug("[DataCatalog] No tianditu connection for geocode fallback")
            return None

        # Step 1: Direct geocode
        result = conn.geocode(village_name)
        if result.success and result.lon != 0:
            center = (result.lon, result.lat)
            logger.info("[DataCatalog] geocode: %s -> (%.4f, %.4f)", village_name, *center)
            return self._center_to_bbox(center, 5.0)

        # Step 2: POI search in county region
        from app.utils.location_parser import parse_location_hierarchy
        try:
            hierarchy = parse_location_hierarchy(village_name)
            county = hierarchy.get("county", "")
            if county:
                poi_result = conn.search_poi_in_region(village_name, county)
                if poi_result.success and poi_result.pois:
                    first = poi_result.pois[0]
                    center = (first.get("lon", 0), first.get("lat", 0))
                    if center[0] != 0:
                        logger.info(
                            "[DataCatalog] POI: %s -> (%.4f, %.4f)",
                            village_name, *center,
                        )
                        return self._center_to_bbox(center, 5.0)
        except Exception as e:
            logger.warning("[DataCatalog] POI fallback failed: %s", e)

        logger.warning("[DataCatalog] Could not locate %s via geocode", village_name)
        return None

    @staticmethod
    def _center_to_bbox(
        center: Tuple[float, float], buffer_km: float
    ) -> BBox:
        """Convert a center point + buffer distance to a BBox."""
        buffer_deg = buffer_km / 111.0
        return BBox(
            west=center[0] - buffer_deg,
            south=center[1] - buffer_deg,
            east=center[0] + buffer_deg,
            north=center[1] + buffer_deg,
        )

    __all__ = ["DataCatalog"]
