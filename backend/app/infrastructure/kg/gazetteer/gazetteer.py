"""Village-name gazetteer — 村名 → 空间实体（居民点聚类/地块集）解析。

KG 子模块：地名解析是 KG 语义能力，agent 层（Binder/EXPLORE/渲染）只消费。

数据源（全部系统内）：
  1. KG ResidentialCluster（SPARQL：聚类名/质心/sfWithin 地块集）
  2. explicit current L1 bindings supplied by the caller

匹配：精确 → difflib fuzzy(ratio>=0.6) → Flash 判定 + 双确认
  （LLM 判定 ∧ 空间校验：村名特征 vs 聚类地块 dlbm 构成）

当前上下文只消费当前 KG、bundle 和显式阶段 artifact；不自动恢复历史 gazetteer
或 semantic-memory 轮次文件。
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_FUZZY_THRESHOLD = 0.6


@dataclass
class GazetteerEntry:
    """A resolved village name → spatial entity (residential settlement)."""

    name: str
    aliases: List[str] = field(default_factory=list)
    entity_uri: str = ""            # KG ResidentialCluster URI
    bsms: List[str] = field(default_factory=list)
    centroid: Optional[List[float]] = None   # [lon, lat]
    source: str = "kg_cluster"      # kg_cluster | bundle_annotation | gis_name_binding
    confidence: float = 0.0
    description: str = ""


class Gazetteer:
    """In-memory gazetteer with exact → fuzzy resolution."""

    def __init__(self, entries: Optional[List[GazetteerEntry]] = None):
        self.entries: List[GazetteerEntry] = list(entries or [])
        self._by_name: Dict[str, GazetteerEntry] = {
            e.name: e for e in self.entries
        }
        for e in self.entries:
            for alias in e.aliases:
                self._by_name.setdefault(alias, e)

    def resolve(self, name: str, fuzzy: bool = True) -> Optional[GazetteerEntry]:
        if not name:
            return None
        if name in self._by_name:
            return self._by_name[name]
        if fuzzy:
            best, best_ratio = None, 0.0
            for key, entry in self._by_name.items():
                ratio = difflib.SequenceMatcher(None, name, key).ratio()
                if ratio > best_ratio:
                    best, best_ratio = entry, ratio
            if best_ratio >= _FUZZY_THRESHOLD:
                logger.debug("[Gazetteer] fuzzy match %s -> %s (%.2f)", name, best.name, best_ratio)
                return best
        return None

    def upsert(self, entry: GazetteerEntry) -> None:
        existing = self._by_name.get(entry.name)
        if existing is not None:
            # Preserve spatial evidence when a later semantic annotation only
            # contributes a name/description.  Replacing a KG cluster entry
            # with an empty L1 entry silently broke GROUND resolution.
            if not entry.bsms and existing.bsms:
                entry.bsms = list(existing.bsms)
            if entry.centroid is None and existing.centroid is not None:
                entry.centroid = list(existing.centroid)
            if not entry.entity_uri:
                entry.entity_uri = existing.entity_uri
            if not entry.aliases:
                entry.aliases = list(existing.aliases)
            self.entries.remove(existing)
            for key, value in list(self._by_name.items()):
                if value is existing:
                    del self._by_name[key]
        self.entries.append(entry)
        self._by_name[entry.name] = entry
        for alias in entry.aliases:
            self._by_name.setdefault(alias, entry)


def _cluster_entries_from_kg(kg: Any, bundle: Any) -> List[GazetteerEntry]:
    """KG ResidentialCluster（hasCentroid + 空间距离选地块集）。

    builder 的地块 sfWithin 聚类关系未生效（实测只指向 village）— 改用聚类质心
    （GEO:hasCentroid WKT）+ bundle 地块几何距离（400m 阈值）确定聚类内地块。
    """
    from rdflib import RDF
    from app.infrastructure.kg.ontology import GEO, PLN, EntityTypes
    from app.spatial.model.geometry import _compute_centroid

    parcel_pts = {}
    if bundle is not None:
        for f in (bundle.polygons.get("landuse_current") or []):
            bsm = str(f.bsm or "")
            geom = f.geometry
            if bsm and geom:
                c = _compute_centroid({
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature", "properties": {}, "geometry": geom}],
                })
                if c:
                    parcel_pts[bsm] = c

    entries: List[GazetteerEntry] = []
    for cluster in kg.g.subjects(RDF.type, EntityTypes.ResidentialCluster):
        name = ""
        for _, _, o in kg.g.triples((cluster, PLN.name, None)):
            name = str(o)
            break
        centroid = None
        for _, _, geom in kg.g.triples((cluster, GEO.hasCentroid, None)):
            for _, _, o in kg.g.triples((geom, GEO.asWKT, None)):
                # WKT: POINT(lon lat)
                import re as _re

                m = _re.findall(r"[\d.+-]+", str(o))
                if len(m) >= 2:
                    try:
                        centroid = [float(m[0]), float(m[1])]
                    except (TypeError, ValueError):
                        centroid = None
                break
            if centroid is not None:
                break
        bsms = []
        if centroid is not None:
            for bsm, pt in parcel_pts.items():
                dx = pt[0] - centroid[0]
                dy = pt[1] - centroid[1]
                if dx * dx + dy * dy < 0.004 * 0.004:  # ~400m
                    bsms.append(bsm)
        entries.append(GazetteerEntry(
            name=name or f"居民点{len(entries) + 1}",
            entity_uri=str(cluster),
            bsms=bsms,
            centroid=centroid,
            source="kg_cluster",
            confidence=0.9,
        ))
    return entries


def _facility_entries_from_kg(kg: Any) -> List[GazetteerEntry]:
    """Expose named L1 Facility entities as geocoder candidates.

    KG already stores facility name/type and point coordinates.  Previously
    that query path was available to cognition only; PARSE/GROUND could not
    resolve a report facility against the same point entity.
    """
    from rdflib import RDF
    from app.infrastructure.kg.ontology import PLN, EntityTypes

    entries: List[GazetteerEntry] = []
    for facility in kg.g.subjects(RDF.type, EntityTypes.Facility):
        name = str(kg.g.value(facility, PLN.name) or "").strip()
        if not name:
            continue
        lon = kg.g.value(facility, PLN.lon)
        lat = kg.g.value(facility, PLN.lat)
        try:
            centroid = [float(lon), float(lat)] if lon is not None and lat is not None else None
        except (TypeError, ValueError):
            centroid = None
        bsm = str(kg.g.value(facility, PLN.bsm) or "").strip()
        entries.append(GazetteerEntry(
            name=name,
            aliases=[str(kg.g.value(facility, PLN.facility_type) or "").strip()],
            entity_uri=str(facility),
            bsms=[bsm] if bsm else [],
            centroid=centroid,
            source="kg_facility",
            confidence=0.9 if centroid else 0.6,
            description=f"KG L1 现状设施：{name}",
        ))
    return entries


def build_gazetteer(
    kg: Any,
    bundle: Any,
) -> Gazetteer:
    """Build the current-context gazetteer from KG clusters and bundle data.

    Non-fatal: KG query failures degrade to an empty gazetteer.

    Historical files are intentionally not read here. Current L1 bindings are
    attached by context bootstrap from explicit artifact references.
    """
    gazetteer = Gazetteer()
    try:
        for e in _cluster_entries_from_kg(kg, bundle):
            gazetteer.upsert(e)
        for e in _facility_entries_from_kg(kg):
            gazetteer.upsert(e)
    except Exception as e:
        logger.warning("[Gazetteer] cluster build failed: %s", e)
    logger.info("[Gazetteer] built: %d entries", len(gazetteer.entries))
    return gazetteer


def spatial_score(
    village_feature_hints: str,
    cluster_dlbms: List[str],
) -> int:
    """特征词命中计数（确定性裁决用）：hints 中每个特征词被聚类构成支持 +1。"""
    if not village_feature_hints or not cluster_dlbms:
        return 0
    hint_to_prefix = {
        "耕地": "11", "农田": "11", "水田": "11", "稻田": "11", "菜地": "11",
        "林": "13", "山": "13", "坡": "13",
        "园": "12", "果": "12",
        "宅基地": "21", "居住": "21", "建设": "21", "住宅": "21",
        "农房": "21", "民房": "21", "房屋": "21", "村庄": "21", "居民点": "21",
        "水": "31", "河": "31", "塘": "31", "溪": "31",
    }
    score = 0
    for kw, prefix in hint_to_prefix.items():
        if kw in village_feature_hints and any(str(d).startswith(prefix) for d in cluster_dlbms):
            score += 1
    return score


def spatial_check(
    village_feature_hints: str,
    cluster_dlbms: List[str],
) -> bool:
    """Flash 双确认之二：空间校验 — 任一特征词匹配即通过（any 语义）。"""
    return spatial_score(village_feature_hints, cluster_dlbms) > 0


__all__ = [
    "Gazetteer",
    "GazetteerEntry",
    "build_gazetteer",
    "spatial_check",
]
