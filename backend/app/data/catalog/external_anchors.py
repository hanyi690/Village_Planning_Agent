"""External Anchor Enrichment Pipeline — 4 阶段 (collect → normalize → dedup → inject)

Pipeline:
  Stage 1: COLLECT — 5 个 source 拉取 → ExternalFeature 列表 (保留 coord_system 标记)
  Stage 2: NORMALIZE — 统一转 WGS84 (gcj02→wgs84, bd09→wgs84)
  Stage 3: CROSS-SOURCE DEDUP — 同 (name_norm, lon_3, lat_3, category) 优先级胜出
  Stage 4: LOCAL DEDUP — 与 bundle 现有 feature 冲突则丢弃
  Stage 5: ROUTE + INJECT — 按 category → 注入现有 sub-key (annotations_current 等)

设计原则:
  - 不引入 _external sub-key, 直接注入现有 sub-key
  - 注入后 bundle 干净统一, 无跨源/本地重复
  - 通过 _raw["anchor_source"] 记录来源, 下游消费者无感知

Source priority (高 → 低, dedup 胜出):
  tianditu_wfs > baidu_v3 > tencent_map > amap_poi > osm
  本轮 OSM 0 数据, 跳过; 天地图 WFS 几何权威性最高
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.spatial.model.coord_transform import gcj02_to_wgs84
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


class FeatureCategory(str, Enum):
    """External feature 的概念类别 — 用于 dedup key + 路由."""
    VILLAGE_COMMITTEE = "village_committee"   # 行政村村委会 office POI
    NATURAL_VILLAGE = "natural_village"        # 自然村本村坐标
    FACILITY = "facility"                       # 学校/医院/公交
    ROAD_NAMED = "road_named"                   # 道路交叉口名 POI
    ROAD_LINE = "road_line"                     # 公路几何 LineString
    WATER_NAMED = "water_named"                 # 水库/河流 POI
    WATER_LINE = "water_line"                   # 水系线
    WATER_POLYGON = "water_polygon"             # 水系面
    ADMIN_AREA = "admin_area"                   # 行政区划边界


@dataclass
class ExternalFeature:
    """统一的外部 feature 表示."""
    name: str                       # 原始名 "金田村委会"
    name_norm: str                  # 归一化 "金田" (去除组织后缀)
    lon: float                      # WGS84 经度 (Stage 2 后)
    lat: float                      # WGS84 纬度
    coord_system: str               # "wgs84" | "gcj02" | "bd09"
    category: FeatureCategory
    source: str                     # "amap_poi" | "baidu_v3" | "tencent_map" | "tianditu_wfs" | "osm"
    raw: Dict[str, Any]             # 原始 API 数据
    geometry: Optional[Dict[str, Any]] = None  # 非 Point features
    provenance: Dict[str, Any] = field(default_factory=dict)

    # 原始坐标 (转换前), 用于追溯
    orig_lon: float = 0.0
    orig_lat: float = 0.0
    orig_coord_system: str = ""


# ==================== Source Priority ====================

SOURCE_PRIORITY: Dict[str, int] = {
    "tianditu_wfs": 1,    # 国家级矢量, 几何权威
    "baidu_v3": 2,       # address 字段防误连强
    "tencent_map": 3,    # POI 覆盖广, 自然村本村命中 5/12
    "amap_poi": 4,       # typecode 精细
    "osm": 5,            # 兜底 (本轮金田 0 数据)
}

# ==================== Category → 现有 sub-key 路由 ====================

CATEGORY_ROUTING: Dict[FeatureCategory, Tuple[str, str, str]] = {
    # category → (group, sub_key, layer_type)
    FeatureCategory.VILLAGE_COMMITTEE: ("points", "annotations_current", "external_village_committee"),
    FeatureCategory.NATURAL_VILLAGE: ("points", "annotations_current", "external_natural_village"),
    FeatureCategory.FACILITY: ("points", "annotations_current", "external_facility"),
    FeatureCategory.ROAD_NAMED: ("points", "annotations_current", "external_road_label"),
    FeatureCategory.ROAD_LINE: ("lines", "roads_current", "external_road_line"),
    FeatureCategory.WATER_NAMED: ("points", "annotations_current", "external_water_label"),
    FeatureCategory.WATER_LINE: ("lines", "roads_current", "external_water_line"),
    FeatureCategory.WATER_POLYGON: ("polygons", "water_bodies", "external_water_polygon"),
    FeatureCategory.ADMIN_AREA: ("polygons", "admin_areas", "external_admin_area"),
}


# ==================== Name Normalize ====================

_NAME_SUFFIXES: Tuple[str, ...] = (
    "村民委员会", "村委会", "社区居委会", "社区委员会",
    "居民委员会", "自然村", "行政村",
)


def normalize_name(name: str) -> str:
    """归一化名称: 去前缀/后缀空白与常见组织后缀."""
    if not name:
        return ""
    s = name.strip()
    for suf in _NAME_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
            break
    return s.strip()


# ==================== Coord Normalize ====================

def normalize_to_wgs84(lon: float, lat: float, coord_system: str) -> Tuple[float, float, str]:
    """统一转 WGS84.

    Args:
        lon, lat: 源坐标
        coord_system: "wgs84" | "gcj02" | "bd09"

    Returns:
        (wgs84_lon, wgs84_lat, "wgs84")

    Notes:
        - AMap/Tencent 默认 GCJ02, 需转换
        - 百度 coord_type=1 已直出 WGS84, 不需再转换
        - 天地图 ≈ WGS84 (CGCS2000), 不需转换
        - OSM 直出 WGS84, 不需转换
    """
    if coord_system == "wgs84":
        return lon, lat, "wgs84"
    elif coord_system == "gcj02":
        wlon, wlat = gcj02_to_wgs84(lon, lat)
        return wlon, wlat, "wgs84"
    elif coord_system == "bd09":
        # 百度 API 设置 coord_type=1 应直出 WGS84,
        # 但实测有 1000m+ 偏差 (百度 geocoding 的 "中心点" 误差), 此处不二次转换.
        # 如果未来确认百度真返 BD09, 需要补 bd09 → gcj02 → wgs84 链路.
        return lon, lat, "wgs84"
    else:
        # 默认按 wgs84 处理
        logger.warning("[Pipeline] unknown coord_system: %s, treating as WGS84", coord_system)
        return lon, lat, "wgs84"


# ==================== Local Key Extraction ====================

def _geom_centroid(geom: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """粗略计算 bbox 中心点 (用于 dedup centroid)."""
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])
    if not coords:
        return None
    flat: List[Tuple[float, float]] = []

    def _walk(c):
        if isinstance(c, (int, float)):
            return
        if isinstance(c, list):
            if c and isinstance(c[0], (int, float)):
                flat.append((c[0], c[1]))
            else:
                for sub in c:
                    _walk(sub)

    _walk(coords)
    if not flat:
        return None
    return (sum(c[0] for c in flat) / len(flat),
            sum(c[1] for c in flat) / len(flat))


def _local_feature_keys(bundle: Any) -> set:
    """收集 bundle 中所有非 _external sub-key 的 (name_norm, lon_3, lat_3, category) 集合."""
    keys = set()
    for group_name in ("points", "lines", "polygons"):
        group = getattr(bundle, group_name, None)
        if not group:
            continue
        layers = getattr(group, "_layers", {})
        for sub_key, feats in layers.items():
            if sub_key.endswith("_external"):
                continue
            for f in feats:
                geom = f.geometry if hasattr(f, "geometry") else {}
                centroid = _geom_centroid(geom) if isinstance(geom, dict) else None
                if centroid is None:
                    continue
                name = normalize_name(
                    getattr(f, "text", "") or
                    getattr(f, "facility_name", "") or
                    getattr(f, "water_name", "") or
                    getattr(f, "road_name", "") or
                    ""
                )
                lon_3 = round(centroid[0] * 1000)
                lat_3 = round(centroid[1] * 1000)
                # 本地 key 不分类别 (任何类别都参与 dedup)
                keys.add((name, lon_3, lat_3))
    return keys


def _feature_to_dedup_key(feat: ExternalFeature) -> Tuple[str, int, int, str]:
    """生成 dedup key: (name_norm, lon_3, lat_3, category)."""
    return (
        feat.name_norm,
        round(feat.lon * 1000),
        round(feat.lat * 1000),
        feat.category.value,
    )


# ==================== Pipeline ====================

class ExternalAnchorPipeline:
    """4-5 阶段外源锚点处理流水线."""

    def __init__(self):
        self._lock = threading.Lock()

    def run(self, bundle: Any, bbox: Optional[Any] = None,
            cfg: Optional[Dict[str, Any]] = None,
            village_boundary: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
        """主入口: 4-5 阶段流水线.

        Args:
            bundle: VillageBundle
            bbox: BBox (west, south, east, north) 或 BBox instance
            cfg: {"province", "city", "county", "town", "village"} 用于 region 查询
            village_boundary: GeoJSON Polygon, 用于严格 boundary filter

        Returns:
            {sub_key: count} 注入统计
        """
        cfg = cfg or {}
        bbox_tuple = None
        if bbox is not None:
            if hasattr(bbox, "west"):
                bbox_tuple = (bbox.west, bbox.south, bbox.east, bbox.north)
            elif isinstance(bbox, (tuple, list)):
                bbox_tuple = tuple(bbox)
        if bbox_tuple is None:
            logger.warning("[Pipeline] no bbox, skip enrichment")
            return {}

        # Stage 1: COLLECT
        raw_features = self._stage1_collect(bbox_tuple, cfg)

        if not raw_features:
            return {}

        # Stage 2: NORMALIZE COORDS (统一 WGS84)
        normalized = []
        for f in raw_features:
            try:
                wlon, wlat, _ = normalize_to_wgs84(f.lon, f.lat, f.coord_system)
                f.orig_lon = f.lon
                f.orig_lat = f.lat
                f.orig_coord_system = f.coord_system
                f.lon = wlon
                f.lat = wlat
                f.coord_system = "wgs84"
                normalized.append(f)
            except Exception as e:
                logger.debug("[Pipeline] coord normalize failed for %s: %s", f.name, e)

        # Stage 3: CROSS-SOURCE DEDUP
        deduped = self._stage3_cross_source_dedup(normalized)

        # Stage 4: LOCAL-AWARE DEDUP + boundary filter
        local_keys = _local_feature_keys(bundle)
        final = self._stage4_local_dedup(deduped, local_keys, village_boundary)

        # Stage 5: ROUTE + INJECT
        injected = self._stage5_inject(bundle, final)

        logger.info(
            "[Pipeline] raw=%d → normalized=%d → deduped=%d → local_dedup=%d → injected=%d",
            len(raw_features), len(normalized), len(deduped), len(final),
            sum(injected.values()),
        )
        return injected

    # ----- Stage 1 -----

    def _stage1_collect(self, bbox: Tuple[float, float, float, float],
                        cfg: Dict[str, Any]) -> List[ExternalFeature]:
        """收集所有 source 的 features."""
        features: List[ExternalFeature] = []
        natural_village_names = list(cfg.get("natural_village_names", []) or [])

        # 1a. 天地图 WFS (HYDA/HYDL/LRDL)
        try:
            features.extend(self._from_tianditu_wfs(bbox))
        except Exception as e:
            logger.warning("[Pipeline] Tianditu WFS failed: %s", e)

        # 1b. 百度 v3 region — 优先中文名 (AK 额度有限)
        try:
            county = cfg.get("county", "")
            city = cfg.get("city", "")
            baidu_region = f"{city}{county}" if county else ""
            if baidu_region:
                features.extend(self._from_baidu(baidu_region, natural_village_names))
        except Exception as e:
            logger.warning("[Pipeline] Baidu failed: %s", e)

        # 1c. 腾讯 v1 region — 优先中文名 (12 位 adcode 不被 API 接受)
        try:
            county = cfg.get("county", "")
            city = cfg.get("city", "")
            tencent_region = f"{city}{county}" if county else ""
            if not tencent_region:
                # fallback 用 6 位县级 adcode (腾讯 API 接受)
                adcode_12 = cfg.get("adcode", "")
                if len(adcode_12) >= 6:
                    tencent_region = adcode_12[:6]
            if tencent_region:
                features.extend(self._from_tencent(tencent_region, natural_village_names))
        except Exception as e:
            logger.warning("[Pipeline] Tencent failed: %s", e)

        # 1d. AMap POI (P5a 行政村 + P4 设施 + 道路名 + 水库)
        try:
            features.extend(self._from_amap(bbox, natural_village_names))
        except Exception as e:
            logger.warning("[Pipeline] AMap failed: %s", e)

        # 1e. OSM (本轮 0 数据, 暂跳过)
        # try:
        #     features.extend(self._from_osm(bbox))
        # except Exception as e:
        #     logger.warning("[Pipeline] OSM failed: %s", e)

        return features

    def _from_tianditu_wfs(self, bbox) -> List[ExternalFeature]:
        """天地图 WFS → ExternalFeature (CGCS2000 ≈ WGS84)."""
        from app.data.ingestion.providers.tianditu.wfs import WfsService
        from app.core.settings import TIANDITU_API_KEY, TIANDITU_WFS_ANCHOR_ENABLED

        if not (TIANDITU_WFS_ANCHOR_ENABLED and TIANDITU_API_KEY):
            return []

        wfs = WfsService(api_key=TIANDITU_API_KEY)
        layer_to_cat = [
            ("TDTService:HYDA", FeatureCategory.WATER_POLYGON),
            ("TDTService:HYDL", FeatureCategory.WATER_LINE),
            ("TDTService:LRDL", FeatureCategory.ROAD_LINE),
        ]
        feats = []
        for layer_name, cat in layer_to_cat:
            try:
                r = wfs.get_wfs_data(layer_name, bbox, max_features=500)
            except Exception as e:
                logger.debug("[Pipeline] WFS %s error: %s", layer_name, e)
                continue
            if not r.success:
                continue
            geojson = r.data.get("geojson", {})
            for f in geojson.get("features", []):
                geom = f.get("geometry")
                if not geom:
                    continue
                props = f.get("properties", {})
                centroid = _geom_centroid(geom)
                if not centroid:
                    continue
                name = props.get("NAME", "") or props.get("name", "")
                feats.append(ExternalFeature(
                    name=name, name_norm=normalize_name(name),
                    lon=centroid[0], lat=centroid[1],
                    coord_system="wgs84",
                    category=cat, source="tianditu_wfs",
                    raw=f, geometry=geom,
                    provenance={"OBJECTID": props.get("OBJECTID", "")},
                ))
        return feats

    def _from_baidu(self, region: str,
                    natural_village_names: List[str] = None) -> List[ExternalFeature]:
        """百度 v3 region query=村 → ExternalFeature (BD09)."""
        from app.data.ingestion.providers.baidu.provider import BaiduProvider
        from app.core.settings import BAIDU_API_KEY, BAIDU_EXTERNAL_ANCHOR_ENABLED

        if not (BAIDU_EXTERNAL_ANCHOR_ENABLED and BAIDU_API_KEY):
            return []

        baidu = BaiduProvider()
        feats: List[ExternalFeature] = []

        # A. 行政村 (query="村")
        r = baidu.search_region(
            query="村", region=region, region_limit=True, page_size=20,
        )
        if r.success:
            results = r.data.get("results", [])
            pois = BaiduProvider._parse_pois(results)
            for p in pois:
                name = p.get("name", "")
                feats.append(ExternalFeature(
                    name=name, name_norm=normalize_name(name),
                    lon=p.get("lon", 0), lat=p.get("lat", 0),
                    coord_system="bd09",
                    category=FeatureCategory.VILLAGE_COMMITTEE,
                    source="baidu_v3", raw=p,
                    provenance={
                        "address": p.get("address", ""),
                        "province": p.get("province", ""),
                        "city": p.get("city", ""),
                        "area": p.get("area", ""),
                    },
                ))

        # B. 自然村 (12 个名字 × region search)
        if natural_village_names:
            for vname in natural_village_names:
                kw = str(vname).strip()
                if not kw:
                    continue
                try:
                    rn = baidu.search_region(
                        query=kw, region=region, region_limit=True, page_size=5,
                    )
                except Exception as e:
                    logger.debug("[Pipeline] Baidu natural_village search '%s' failed: %s", kw, e)
                    continue
                if not rn.success:
                    continue
                results = rn.data.get("results", [])
                pois = BaiduProvider._parse_pois(results)
                for p in pois:
                    name = p.get("name", "")
                    if not name or not (kw in name or name in kw):
                        continue
                    feats.append(ExternalFeature(
                        name=name, name_norm=normalize_name(name),
                        lon=p.get("lon", 0), lat=p.get("lat", 0),
                        coord_system="bd09",
                        category=FeatureCategory.NATURAL_VILLAGE,
                        source="baidu_v3", raw=p,
                        provenance={
                            "keyword": kw, "address": p.get("address", ""),
                            "city": p.get("city", ""), "area": p.get("area", ""),
                        },
                    ))

        return feats

    def _from_tencent(self, region: str,
                      natural_village_names: List[str]) -> List[ExternalFeature]:
        """腾讯 v1 search region → ExternalFeature (GCJ02).

        Args:
            region: 优先 12 位 township adcode, 否则 city+county 中文名
        """
        from app.data.ingestion.providers.tencent.provider import TencentMapProvider
        from app.core.settings import TECENT_MAP_API_KEY, TECENT_MAP_EXTERNAL_ANCHOR_ENABLED

        if not (TECENT_MAP_EXTERNAL_ANCHOR_ENABLED and TECENT_MAP_API_KEY):
            return []

        tencent = TencentMapProvider()
        feats = []

        # A. 行政村 (region 搜 "村")
        r = tencent.search_region(keyword="村", region=region, page_size=20)
        if r.success:
            for p in r.data.get("pois", []):
                name = p.get("name", "")
                feats.append(ExternalFeature(
                    name=name, name_norm=normalize_name(name),
                    lon=p.get("lon", 0), lat=p.get("lat", 0),
                    coord_system="gcj02",
                    category=FeatureCategory.VILLAGE_COMMITTEE,
                    source="tencent_map", raw=p,
                    provenance={
                        "address": p.get("address", ""),
                        "district": p.get("district", ""),
                        "adcode": p.get("adcode", ""),
                    },
                ))

        # B. 自然村 (12 个名字 × region search, 5km 内入 natural_village)
        # 关键词 = 自然村名 + 村名组合设施锚点（提高命中率，如"园寨村委会"）
        if natural_village_names:
            for vname in natural_village_names:
                kw = str(vname).strip()
                if not kw:
                    continue
                try:
                    rv = tencent.search_region(
                        keyword=kw, region=region, page_size=5, coord_type="wgs84",
                    )
                except Exception as e:
                    logger.debug("[Pipeline] Tencent natural_village search '%s' failed: %s", kw, e)
                    continue
                if not rv.success:
                    continue
                for p in rv.data.get("pois", []) or []:
                    name = p.get("name", "")
                    # 名称相关性过滤：命中关键词或关键词命中 POI 名
                    if not name or not (kw in name or name in kw):
                        continue
                    feats.append(ExternalFeature(
                        name=name, name_norm=normalize_name(name),
                        lon=p.get("lon", 0), lat=p.get("lat", 0),
                        coord_system="wgs84",
                        category=FeatureCategory.NATURAL_VILLAGE,
                        source="tencent_map", raw=p,
                        provenance={
                            "keyword": kw,
                            "address": p.get("address", ""),
                            "district": p.get("district", ""),
                            "adcode": p.get("adcode", ""),
                        },
                    ))

        return feats

    def _from_amap(self, bbox, natural_village_names: List[str] = None) -> List[ExternalFeature]:
        """AMap POI → ExternalFeature (GCJ02)."""
        from app.data.ingestion.providers.amap.provider import AmapProvider
        from app.core.settings import AMAP_API_KEY, AMAP_EXTERNAL_ANCHOR_ENABLED

        if not (AMAP_EXTERNAL_ANCHOR_ENABLED and AMAP_API_KEY):
            return []

        amap = AmapProvider()
        # 计算半径
        center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        radius_m = max(int(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * 111000 / 2), 5000)

        typecode_to_cat = [
            ("141200", FeatureCategory.FACILITY),       # 学校
            ("090100", FeatureCategory.FACILITY),       # 医院
            ("150700", FeatureCategory.FACILITY),       # 公交
            ("130106", FeatureCategory.VILLAGE_COMMITTEE),  # 村委会
        ]

        # A. 设施 + 行政村 (typecode)
        typecodes = "|".join(tc for tc, _ in typecode_to_cat)
        r = amap.search_poi_by_types(typecodes, center, radius_m, page_size=25)
        feats = []
        if r.success:
            for p in r.data.get("pois", []):
                tc = p.get("typecode", "")
                cat = next((c for t, c in typecode_to_cat if t in tc),
                           FeatureCategory.FACILITY)
                name = p.get("name", "")
                feats.append(ExternalFeature(
                    name=name, name_norm=normalize_name(name),
                    lon=p.get("lon", 0), lat=p.get("lat", 0),
                    coord_system="gcj02",
                    category=cat, source="amap_poi", raw=p,
                    provenance={
                        "address": p.get("address", ""),
                        "typecode": tc,
                    },
                ))

        # B. 行政村 (P5a "村" keyword)
        r2 = amap.search_poi_nearby("村", center, radius_m, page_size=25)
        if r2.success:
            existing_norms = {f.name_norm for f in feats}
            for p in r2.data.get("pois", []):
                name = p.get("name", "")
                norm = normalize_name(name)
                if norm in existing_norms:
                    continue
                existing_norms.add(norm)
                feats.append(ExternalFeature(
                    name=name, name_norm=norm,
                    lon=p.get("lon", 0), lat=p.get("lat", 0),
                    coord_system="gcj02",
                    category=FeatureCategory.VILLAGE_COMMITTEE,
                    source="amap_poi", raw=p,
                    provenance={"address": p.get("address", "")},
                ))

        # C. 道路交叉口名 (typecode 190000)
        try:
            r3 = amap.search_poi_by_types("190000", center, radius_m, page_size=25)
            if r3.success:
                for p in r3.data.get("pois", []):
                    name = p.get("name", "")
                    if not name:
                        continue
                    feats.append(ExternalFeature(
                        name=name, name_norm=normalize_name(name),
                        lon=p.get("lon", 0), lat=p.get("lat", 0),
                        coord_system="gcj02",
                        category=FeatureCategory.ROAD_NAMED,
                        source="amap_poi", raw=p,
                    ))
        except Exception:
            pass

        # D. 水库 (keyword)
        try:
            r4 = amap.search_poi_nearby("水库", center, radius_m, page_size=10)
            if r4.success:
                for p in r4.data.get("pois", []):
                    name = p.get("name", "")
                    if not name:
                        continue
                    feats.append(ExternalFeature(
                        name=name, name_norm=normalize_name(name),
                        lon=p.get("lon", 0), lat=p.get("lat", 0),
                        coord_system="gcj02",
                        category=FeatureCategory.WATER_NAMED,
                        source="amap_poi", raw=p,
                    ))
        except Exception:
            pass

        # E. 自然村 (12 个名字 × nearby search)
        if natural_village_names:
            for vname in natural_village_names:
                kw = str(vname).strip()
                if not kw:
                    continue
                try:
                    rn = amap.search_poi_nearby(kw, center, radius_m, page_size=5)
                except Exception as e:
                    logger.debug("[Pipeline] AMap natural_village search '%s' failed: %s", kw, e)
                    continue
                if not rn.success:
                    continue
                for p in rn.data.get("pois", []) or []:
                    name = p.get("name", "")
                    if not name or not (kw in name or name in kw):
                        continue
                    feats.append(ExternalFeature(
                        name=name, name_norm=normalize_name(name),
                        lon=p.get("lon", 0), lat=p.get("lat", 0),
                        coord_system="gcj02",
                        category=FeatureCategory.NATURAL_VILLAGE,
                        source="amap_poi", raw=p,
                        provenance={"keyword": kw, "address": p.get("address", "")},
                    ))

        return feats

    # ----- Stage 3 -----

    def _stage3_cross_source_dedup(
        self, features: List[ExternalFeature]
    ) -> List[ExternalFeature]:
        """同 (name_norm, lon_3, lat_3, category) 跨源去重, 高优先级胜出."""
        # 按 source 优先级排序 (高优先级在前)
        sorted_feats = sorted(
            features,
            key=lambda f: SOURCE_PRIORITY.get(f.source, 99),
        )
        seen = set()
        kept = []
        for f in sorted_feats:
            key = _feature_to_dedup_key(f)
            if key in seen:
                continue
            seen.add(key)
            kept.append(f)
        return kept

    # ----- Stage 4 -----

    def _stage4_local_dedup(
        self, features: List[ExternalFeature], local_keys: set,
        village_boundary: Optional[Dict[str, Any]] = None,
    ) -> List[ExternalFeature]:
        """与本地 feature 冲突的丢弃 (本地优先) + 严格 boundary filter.

        Args:
            village_boundary: GeoJSON Polygon of village admin area.
                所有类别都严格过滤 (point-in-polygon) — 用户决策 v9.12.
        """
        kept = []
        for f in features:
            # 1. local dedup
            key = (f.name_norm, round(f.lon * 1000), round(f.lat * 1000))
            if key in local_keys:
                continue
            # 2. boundary filter (严格 — 所有类别)
            if village_boundary is not None:
                from app.spatial.model.geometry import point_in_polygon
                if not point_in_polygon((f.lon, f.lat), village_boundary):
                    continue
            kept.append(f)
        return kept

    # ----- Stage 5 -----

    def _stage5_inject(
        self, bundle: Any, features: List[ExternalFeature]
    ) -> Dict[str, int]:
        """按 category → 现有 sub-key 注入."""
        from app.data.model.base import (
            LineFeature, PointFeature, PolygonFeature,
        )

        counts: Dict[str, int] = {}
        for feat in features:
            route = CATEGORY_ROUTING.get(feat.category)
            if not route:
                continue
            group_name, sub_key, layer_type = route
            geom = feat.geometry or {
                "type": "Point", "coordinates": [feat.lon, feat.lat],
            }
            try:
                if group_name == "points":
                    f = PointFeature(
                        geometry=geom, bsm="",
                        layer_type=layer_type,
                        category=feat.category.value,
                        _raw={
                            **feat.raw,
                            "anchor_source": feat.source,
                            "coord_system": "wgs84",
                            "category": feat.category.value,
                            "name_norm": feat.name_norm,
                        },
                    )
                    group = getattr(bundle, group_name)
                    group._layers.setdefault(sub_key, []).append(f)
                elif group_name == "lines":
                    f = LineFeature(
                        geometry=geom, bsm="",
                        layer_type=layer_type,
                        _raw={
                            **feat.raw,
                            "anchor_source": feat.source,
                            "coord_system": "wgs84",
                            "category": feat.category.value,
                            "name_norm": feat.name_norm,
                        },
                    )
                    group = getattr(bundle, group_name)
                    group._layers.setdefault(sub_key, []).append(f)
                elif group_name == "polygons":
                    f = PolygonFeature(
                        geometry=geom, bsm="",
                        layer_type=layer_type,
                        _raw={
                            **feat.raw,
                            "anchor_source": feat.source,
                            "coord_system": "wgs84",
                            "category": feat.category.value,
                            "name_norm": feat.name_norm,
                        },
                    )
                    group = getattr(bundle, group_name)
                    group._layers.setdefault(sub_key, []).append(f)
                counts[sub_key] = counts.get(sub_key, 0) + 1
            except Exception as e:
                logger.debug("[Pipeline] inject %s failed: %s", feat.name, e)
        return counts


__all__ = [
    "FeatureCategory",
    "ExternalFeature",
    "SOURCE_PRIORITY",
    "CATEGORY_ROUTING",
    "normalize_name",
    "normalize_to_wgs84",
    "ExternalAnchorPipeline",
]