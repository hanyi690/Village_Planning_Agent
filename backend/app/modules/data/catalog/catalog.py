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

    Features are validated through the registry adapter for ``layer_key`` and
    routed to its canonical bundle target (for example ``landuse_current``).
    """
    features = geojson.get("features", [])
    if not features:
        return 0

    aliases = {
        "road": "current_road",
        "residential": "current_building",
    }
    gis_type_ref = aliases.get(layer_key, layer_key)

    from app.modules.data.adapters import ADAPTERS
    from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY

    entry = GIS_LAYER_REGISTRY.get(gis_type_ref)
    if entry is None or entry.ingest is None:
        logger.warning("[DataCatalog] Unknown uploaded GIS layer type: %s", layer_key)
        return 0
    adapter = ADAPTERS.get(entry.ingest.adapter)
    if adapter is None:
        logger.warning(
            "[DataCatalog] No adapter '%s' for uploaded layer %s",
            entry.ingest.adapter,
            gis_type_ref,
        )
        return 0

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
        # village_name → admin_meta (province/city/county/town/adcode) 预设
        # 用于同步路径下让 pipeline 拿到正确的 region 限定
        self._admin_meta_overrides: Dict[str, Dict[str, str]] = {}
        self._load_config()
        self._init_connections()
        self._init_sources()

    def set_admin_meta(
        self,
        village_name: str,
        province: str = "",
        city: str = "",
        county: str = "",
        township: str = "",
        adcode_12: str = "",
    ) -> None:
        """预设 village 的行政元数据 (同步路径使用).

        调用示例:
            catalog.set_admin_meta("金田", county="平远县", township="泗水镇",
                                   adcode_12="441426110000")

        若不预设, _auto_fill_admin_meta 会通过本地 12 位 adcode CSV 自动查询.
        """
        self._admin_meta_overrides[village_name] = {
            "province": province,
            "city": city,
            "county": county,
            "township": township,
            "adcode_12": adcode_12,
        }
        logger.debug("[DataCatalog] set admin meta for '%s': %s",
                      village_name, self._admin_meta_overrides[village_name])

    def get_admin_meta(self, village_name: str) -> Dict[str, str]:
        """获取 village 的预设 admin meta (无则返回空 dict)."""
        return self._admin_meta_overrides.get(village_name, {})

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
        bundle = VillageBundle(
            village_name=village_name,
            metadata=VillageMetadata(village_name=village_name),
        )

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

        # Step 5: External Anchor Enrichment (v9.8 pipeline)
        #   - 自动从 AdminCodeService 填充 12 位 adcode + 行政层级 (同步路径)
        #   - 5 阶段: collect → normalize (gcj02/bd09→wgs84) → cross-source dedup → local dedup → inject
        #   - 注入策略: 直接注入现有 sub-key (annotations_current 等), 不引入 _external
        #   - 通过 _raw["anchor_source"] 字段记录来源
        try:
            self._auto_fill_admin_meta(bundle, village_name)
            from .external_anchors import ExternalAnchorPipeline
            from app.modules.spatial_ops.geometry import village_boundary_geometry

            cfg = {
                "province": bundle.metadata.province or "",
                "city": bundle.metadata.city or "",
                "county": bundle.metadata.county or "",
                "town": bundle.metadata.township or "",
                "village": village_name,
                "adcode": bundle.metadata.adcode_12 or "",
                "natural_village_names": self._load_village_anchors(village_name),
            }
            # 取 village admin boundary (用于 strict point-in-polygon filter)
            boundary = village_boundary_geometry(bundle)
            pipeline = ExternalAnchorPipeline()
            injected = pipeline.run(bundle, bbox, cfg,
                                     village_boundary=boundary)
            if injected:
                logger.info(
                    "[DataCatalog] external anchors injected: %s (boundary=%s)",
                    sum(injected.values()), boundary is not None,
                )
        except Exception as e:
            logger.warning(
                "[DataCatalog] external anchor pipeline failed: %s", e,
            )

        logger.info(
            "[DataCatalog] load_village_bundle('%s'): %d parcels, %d roads, %d annotations",
            village_name,
            bundle.parcel_count,
            len(bundle.lines.get("roads_current")) + len(bundle.lines.get("roads_planned")),
            len(bundle.points.get("annotations_current")) + len(bundle.points.get("annotations_planned")),
        )
        return bundle

    def _load_village_yaml_meta(self, village_name: str) -> Dict[str, str]:
        """从 data/gis/{village}/villages.yaml 读取村庄行政区划（现状事实）。

        优先于 CSV 重名猜测：金田村在 villages.yaml 明确为
        "广东省 梅州市 平远县 泗水镇"，避免误判为安徽同名村导致多源
        enrichment 用错 region 搜索。
        """
        try:
            from pathlib import Path
            import yaml

            cfg_path = Path("data/gis") / str(village_name).strip() / "villages.yaml"
            if not cfg_path.exists():
                cfg_path = Path("data/gis/jintian/villages.yaml")
            if not cfg_path.exists():
                return {}
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            v = data.get("village", {}) or {}
            if not isinstance(v, dict):
                return {}
            out = {}
            for k in ("province", "city", "county", "township", "code"):
                val = str(v.get(k) or "").strip()
                if val:
                    out[k] = val
            return out
        except Exception as e:  # noqa: BLE001 — 配置缺失非致命
            logger.debug("[DataCatalog] village yaml meta failed: %s", e)
            return {}

    def _load_village_anchors(self, village_name: str) -> List[str]:
        """从 data/gis/{village}/villages.yaml 加载自然村名 + 村名组合设施锚点。

        Data 层配置（现状行政事实，非规划决策），用于多源 anchor enrichment
        的自然村搜索关键词。文件缺失时回退到空列表（不阻断管线）。
        """
        try:
            from pathlib import Path
            import yaml

            cfg_path = Path("data/gis") / str(village_name).strip() / "villages.yaml"
            if not cfg_path.exists():
                # 兜底：按村庄名猜测（如"金田村委会" → jintian）
                cfg_path = Path("data/gis/jintian/villages.yaml")
                if not cfg_path.exists():
                    return []
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            names = [str(n).strip() for n in (data.get("natural_villages", []) or []) if str(n).strip()]
            anchors = []
            for a in (data.get("village_anchors", []) or []):
                n = str(a.get("name", "") or "").strip()
                if n:
                    anchors.append(n)
            for lm in (data.get("landmarks", []) or []):
                n = str(lm.get("name", "") or "").strip()
                if n:
                    anchors.append(n)
            combined = names + anchors
            # 去重保序
            seen = set()
            result = []
            for n in combined:
                if n not in seen:
                    seen.add(n)
                    result.append(n)
            return result
        except Exception as e:  # noqa: BLE001 — 配置缺失非致命
            logger.warning("[DataCatalog] village anchors load failed for %s: %s", village_name, e)
            return []

    def _auto_fill_admin_meta(
        self,
        bundle: VillageBundle,
        village_name: str,
    ) -> None:
        """通过 AdminCodeService 自动填充 bundle.metadata.

        同步路径下 metadata.province/city/county 为空 — 用本地 12 位 adcode
        CSV 查询填上. 优先 12 位 township code 用于外部 API.

        处理重名:
          "金田" 在多个省都有同名地点. 策略:
          0. 若调用方预设了 admin_meta_overrides, 优先用 override 的 county/town
          1. 若已知 county, 强制按 county 过滤
          2. 否则警告 + 取第一个 (但记录风险)
        """
        # 已有完整 5 级则跳过
        if (bundle.metadata.province and bundle.metadata.county
                and bundle.metadata.adcode_12):
            return

        # 0a. 优先用 data/gis/{village}/villages.yaml 的行政区划（现状事实，防重名误判）
        try:
            yaml_meta = self._load_village_yaml_meta(village_name)
            if yaml_meta:
                if not bundle.metadata.province and yaml_meta.get("province"):
                    bundle.metadata.province = yaml_meta["province"]
                if not bundle.metadata.city and yaml_meta.get("city"):
                    bundle.metadata.city = yaml_meta["city"]
                if not bundle.metadata.county and yaml_meta.get("county"):
                    bundle.metadata.county = yaml_meta["county"]
                if not bundle.metadata.township and yaml_meta.get("township"):
                    bundle.metadata.township = yaml_meta["township"]
                if not bundle.metadata.adcode_12 and yaml_meta.get("code"):
                    bundle.metadata.adcode_12 = yaml_meta["code"]
                # YAML 提供完整行政区划则直接返回（跳过 CSV 重名猜测）
                if (bundle.metadata.province and bundle.metadata.county
                        and bundle.metadata.adcode_12):
                    return
        except Exception as e:
            logger.debug("[DataCatalog] villages.yaml admin meta failed: %s", e)

        # 0. 优先用预设 override (测试时通常会预设)
        override = self._admin_meta_overrides.get(village_name, {})
        if override:
            if not bundle.metadata.province and override.get("province"):
                bundle.metadata.province = override["province"]
            if not bundle.metadata.city and override.get("city"):
                bundle.metadata.city = override["city"]
            if not bundle.metadata.county and override.get("county"):
                bundle.metadata.county = override["county"]
            if not bundle.metadata.township and override.get("township"):
                bundle.metadata.township = override["township"]
            if not bundle.metadata.adcode_12 and override.get("adcode_12"):
                bundle.metadata.adcode_12 = override["adcode_12"]
            # 预设充分则提前返回
            if (bundle.metadata.county and bundle.metadata.adcode_12):
                return

        try:
            from app.modules.parsing.admin_code_loader import (
                get_admin_code_service,
            )
            svc = get_admin_code_service()

            known_county = bundle.metadata.county or ""
            known_province = bundle.metadata.province or ""

            # 1. 找 village (5 级), 在多个同名中选 county/province 匹配的
            village_code = ""
            search_results = svc.search(village_name, level=5, limit=50)

            if search_results:
                candidates = []
                for v in search_results:
                    chain = svc.get_parent_chain_with_names(v.code)
                    county_name = next(
                        (n for c, n, l in chain if l == 3), ""
                    )
                    province_name = next(
                        (n for c, n, l in chain if l == 1), ""
                    )
                    candidates.append({
                        "code": v.code, "name": v.name,
                        "county": county_name, "province": province_name,
                    })

                # 优先级匹配: known_county > known_province > 默认第一个
                matched = []
                if known_county:
                    matched = [c for c in candidates if c["county"] == known_county]
                elif known_province:
                    matched = [c for c in candidates if c["province"] == known_province]
                else:
                    # 都未知 — 取 name 完全匹配的第一个
                    name_matches = [c for c in candidates if c["name"] == village_name]
                    if name_matches:
                        matched = name_matches

                if matched:
                    # 选 name 完全匹配的优先, 否则第一个
                    for c in matched:
                        if c["name"] == village_name:
                            village_code = c["code"]
                            break
                    if not village_code:
                        village_code = matched[0]["code"]
                elif candidates:
                    # 兜底: 取第一个但警告
                    village_code = candidates[0]["code"]
                    logger.warning(
                        "[DataCatalog] '%s' has %d ambiguous matches, "
                        "using first: %s (county=%s, province=%s). "
                        "Set bundle.metadata.county to disambiguate.",
                        village_name, len(candidates),
                        candidates[0]["code"], candidates[0]["county"],
                        candidates[0]["province"],
                    )

            if not village_code:
                logger.debug("[DataCatalog] no adcode found for village '%s'", village_name)
                return

            # 2. 用 village_code 拿 5 级 parent chain
            chain = svc.get_parent_chain_with_names(village_code)
            for code, name, level in chain:
                if level == 1:
                    if not bundle.metadata.province:
                        bundle.metadata.province = name
                elif level == 2:
                    if not bundle.metadata.city:
                        bundle.metadata.city = name
                elif level == 3:
                    if not bundle.metadata.county:
                        bundle.metadata.county = name
                elif level == 4:
                    if not bundle.metadata.township:
                        bundle.metadata.township = name
                elif level == 5:
                    pass

            # 3. 12 位 township code (优先) 或 village code
            if not bundle.metadata.adcode_12:
                town_code = ""
                county_code = ""
                for code, name, level in chain:
                    if level == 4:
                        town_code = code
                    elif level == 3:
                        county_code = code
                if len(town_code) == 12:
                    bundle.metadata.adcode_12 = town_code
                elif len(village_code) == 12:
                    bundle.metadata.adcode_12 = village_code
                elif len(county_code) == 12:
                    bundle.metadata.adcode_12 = county_code
        except Exception as e:
            logger.debug("[DataCatalog] auto fill admin meta failed: %s", e)

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
        uploaded_gis = []
        if session_id:
            try:
                from app.database.operations import get_uploaded_files_by_session_async

                uploaded = await get_uploaded_files_by_session_async(session_id)
                uploaded_gis = [
                    item for item in uploaded
                    if isinstance(item.get("gis_data"), dict)
                ]
            except Exception as e:
                logger.warning(
                    "[DataCatalog] Uploaded GIS probe failed for %s: %s",
                    session_id,
                    e,
                )

        has_session_gis = any(
            isinstance(item.get("gis_data"), dict)
            and item["gis_data"].get("type") == "FeatureCollection"
            and item["gis_data"].get("features")
            for item in uploaded_gis
        )
        demo_village = str(village_name or "").strip().lower() in {
            "金田",
            "金田村",
            "jintian",
        }
        if has_session_gis or (session_id and not demo_village):
            bundle = VillageBundle(
                village_name=village_name,
                metadata=VillageMetadata(village_name=village_name),
            )
            if has_session_gis:
                logger.info(
                    "[DataCatalog] Using session GIS uploads only for %s; "
                    "configured demo sources are excluded",
                    session_id,
                )
            else:
                logger.warning(
                    "[DataCatalog] No session GIS uploads for %s; returning an "
                    "empty bundle instead of loading demo-village sources",
                    session_id,
                )
        else:
            bundle = self.load_village_bundle(village_name, layer_types=layer_types)
        if session_id:
            await self._populate_session_context(
                bundle,
                session_id,
                uploaded_gis=uploaded_gis,
            )
        return bundle

    async def _populate_session_context(
        self,
        bundle: VillageBundle,
        session_id: str,
        uploaded_gis: Optional[List[Dict[str, Any]]] = None,
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
        if uploaded_gis is None:
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
