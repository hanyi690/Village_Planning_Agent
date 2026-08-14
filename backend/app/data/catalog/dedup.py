"""External Anchor Enrichment — 去重与注入服务

本地数据优先, 外部 API 作为补充 (填充本地未覆盖区域):
  Priority 0: 本地 annotation_current/planned (现有 bundle)
  Priority 1: 本地 landuse parcels with BSM
  Priority 2: 天地图 WFS (HYDA/HYDL/LRDL, 国家级矢量, 含名字)
  Priority 3: AMap POI (P5a 村委会 + P4 设施 + 道路名 + 水库名)

去重维度: (name_norm, lat_3, lon_3, type_key) → unique
  lat_3 / lon_3 = round(coord, 3) → ~100m 容差
  name_norm = 去后缀 (村委会/自然村/村)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ==================== Source Priority ====================
# 数字越小优先级越高; 同 key 时数字小者胜出
SOURCE_PRIORITY: Dict[str, int] = {
    "local_annotation": 0,    # 本地 GIS 注记 (现有)
    "local_parcel": 1,        # 本地地块 (BSM 关联)
    "tianditu_wfs": 2,        # 天地图 WFS 矢量
    "amap_poi": 3,            # 高德 POI
    "tencent_map": 6,         # 腾讯地图
}

# 名字归一化去除的后缀
_NAME_SUFFIXES: Tuple[str, ...] = (
    "村民委员会",
    "村委会",
    "社区居委会",
    "社区委员会",
    "居民委员会",
    "自然村",
    "行政村",
    "村",
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


def coord_key(lon: float, lat: float, precision: int = 3) -> Tuple[int, int]:
    """坐标近似 → 整数 key (默认 ~100m 容差)."""
    return (round(lon * (10 ** precision)), round(lat * (10 ** precision)))


def feature_type_key(feat: Any) -> str:
    """生成 feature 的类型键 (避免名称相同但类型不同的合并)."""
    if hasattr(feat, "layer_type"):
        return str(feat.layer_type)
    if isinstance(feat, dict):
        return str(feat.get("layer_type", "unknown"))
    return "unknown"


def feature_name(feat: Any) -> str:
    """提取 feature 的显示名 (兼容不同字段)."""
    if isinstance(feat, dict):
        for attr in ("text", "facility_name", "water_name", "road_name",
                     "village_name", "name"):
            v = feat.get(attr)
            if v:
                return str(v)
        return ""
    for attr in ("text", "facility_name", "water_name", "road_name",
                 "village_name", "name"):
        v = getattr(feat, attr, None)
        if v:
            return str(v)
    return ""


def feature_coords(feat: Any) -> Optional[Tuple[float, float]]:
    """提取 (lon, lat), 兼容 geometry 字段或 None."""
    if isinstance(feat, dict):
        geom = feat.get("geometry", {})
    else:
        geom = feat.geometry or {}
    if not isinstance(geom, dict):
        return None
    coords = geom.get("coordinates") or []
    if len(coords) >= 2:
        try:
            return (float(coords[0]), float(coords[1]))
        except (TypeError, ValueError):
            return None
    return None


def feature_source(feat: Any) -> str:
    """提取 source 字段."""
    if isinstance(feat, dict):
        return str(feat.get("anchor_source", "")
                   or feat.get("provenance", {}).get("source", ""))
    return str(getattr(feat, "anchor_source", "") or "")


# ==================== Dedup ====================

def dedup_features(features: List[Any],
                   precision: int = 3,
                   prefer_source_priority: bool = True
                   ) -> List[Any]:
    """按 (name_norm + coord_~100m + type) 去重.

    Args:
        features: 输入 features (混合 source)
        precision: 坐标精度 (3=~100m, 4=~10m)
        prefer_source_priority: True 则优先级源胜出

    Returns:
        去重后的 features (按 source 优先级排序)
    """
    if not features:
        return []

    # 按 source 优先级排序 (小者在前)
    if prefer_source_priority:
        sorted_features = sorted(
            features,
            key=lambda f: SOURCE_PRIORITY.get(feature_source(f), 99),
        )
    else:
        sorted_features = list(features)

    seen: set = set()
    kept: List[Any] = []

    for f in sorted_features:
        coords = feature_coords(f)
        if coords is None:
            # 无坐标的 feature (Polygon/LineString) 暂跳过几何去重
            # 后续可由 dedup_geometries 处理
            continue

        name = normalize_name(feature_name(f))
        ck = coord_key(coords[0], coords[1], precision)
        tk = feature_type_key(f)
        key = (name, ck[0], ck[1], tk)

        if key in seen:
            continue
        seen.add(key)
        kept.append(f)

    return kept


# ==================== Geometry Dedup (for Polygon/LineString) ====================

def _geom_centroid(geom: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """粗略计算 bbox 中心点."""
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

    avg_lon = sum(c[0] for c in flat) / len(flat)
    avg_lat = sum(c[1] for c in flat) / len(flat)
    return (avg_lon, avg_lat)


def dedup_geometries(features: List[Any],
                     tolerance_deg: float = 0.0001) -> List[Any]:
    """对几何近似 (Polygon/LineString) 按 bbox 中心距离去重."""
    if not features:
        return []

    kept: List[Any] = []
    seen_centroids: List[Tuple[float, float]] = []

    for f in features:
        if isinstance(f, dict):
            geom = f.get("geometry", {})
        else:
            geom = f.geometry or {}
        if not isinstance(geom, dict):
            kept.append(f)
            continue

        centroid = _geom_centroid(geom)
        if centroid is None:
            kept.append(f)
            continue

        is_dup = False
        for sc in seen_centroids:
            if (abs(centroid[0] - sc[0]) < tolerance_deg and
                    abs(centroid[1] - sc[1]) < tolerance_deg):
                is_dup = True
                break
        if not is_dup:
            seen_centroids.append(centroid)
            kept.append(f)

    return kept


# ==================== Internal vs External Classifier ====================

def classify_internal(feat: Any,
                      village_name: str,
                      expected_township: Optional[str] = None,
                      expected_county: Optional[str] = None,
                      expected_city: Optional[str] = None,
                      expected_province: Optional[str] = None,
                      ) -> Optional[bool]:
    """根据 feat 的 provenance 字段判内外 (本村 vs 外村).

    返回:
        True = 本村 (internal)
        False = 外村 (external)
        None = 无法判断 (字段不全)

    规则:
        - 本地 source: 默认 internal
        - 外部 source: 校验 township/county/city/village_name 字段
        - 任何不匹配的视为外村
    """
    src = feature_source(feat)

    # 本地数据永远 internal
    if src.startswith("local"):
        return True

    # 提取归属字段
    if isinstance(feat, dict):
        prov = feat.get("provenance", {})
        addr = feat.get("address", "") or prov.get("address", "")
        township = (prov.get("township") or
                    feat.get("township") or "")
        county = (prov.get("county") or
                  feat.get("county") or
                  prov.get("area") or
                  feat.get("area") or "")
        city = (prov.get("city") or feat.get("city") or "")
        province = (prov.get("province") or feat.get("province") or "")
        name = feat.get("name", "") or feature_name(feat)
    else:
        prov = getattr(feat, "provenance", None) or {}
        addr = prov.get("address", "") or ""
        township = prov.get("township", "")
        county = (prov.get("county") or prov.get("area") or "")
        city = prov.get("city", "")
        province = prov.get("province", "")
        name = feature_name(feat)

    haystack_parts = [addr, township, county, city, province]
    haystack = " ".join(str(p) for p in haystack_parts if p)

    # 优先 township 一致
    if expected_township and expected_township in haystack:
        return True
    # 退而求其次: county 一致 + name 包含本村名
    if expected_county and expected_county in haystack:
        if village_name and village_name in name:
            return True
    if expected_county and expected_county in haystack:
        return True

    # 完全无匹配 → 外村
    if haystack:
        return False

    return None


# ==================== Simple in-memory cache ====================

class SimpleCache:
    """进程内缓存 (key → (ts, value))."""
    def __init__(self, ttl_s: float = 3600.0):
        self._cache: Dict[Tuple, Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.ttl_s = ttl_s

    def get(self, key: Tuple) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts, val = entry
            if time.time() - ts > self.ttl_s:
                del self._cache[key]
                return None
            return val

    def set(self, key: Tuple, value: Any) -> None:
        with self._lock:
            self._cache[key] = (time.time(), value)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


__all__ = [
    "SOURCE_PRIORITY",
    "normalize_name",
    "coord_key",
    "feature_type_key",
    "feature_name",
    "feature_coords",
    "feature_source",
    "dedup_features",
    "dedup_geometries",
    "classify_internal",
    "SimpleCache",
]