"""Village-name gazetteer — 村名 → 空间实体（居民点聚类/地块集）解析。

KG 子模块：地名解析是 KG 语义能力，agent 层（Binder/EXPLORE/渲染）只消费。

数据源（全部系统内）：
  1. KG ResidentialCluster（SPARQL：聚类名/质心/sfWithin 地块集）
  2. bundle 村名注记（point-in-boundary 过滤村外行政村）
  3. SemanticMemoryStore 注解（L1 语义回流产物：村名→BSM）

匹配：精确 → difflib fuzzy(ratio>=0.6) → Flash 判定 + 双确认
  （LLM 判定 ∧ 空间校验：村名特征 vs 聚类地块 dlbm 构成）

持久化：data/gazetteer/{village}.json（主文件）
         + 轮次增量写入 memory 轮次文件（round/diff/supersede 机制一致）
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
    source: str = "kg_cluster"      # kg_cluster | bundle_annotation | l1_enrichment | llm_confirmed
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


def _external_anchors_from_bundle(bundle: Any) -> List[GazetteerEntry]:
    """从 bundle 多源 API 注入的自然村注记构建权威坐标条目。

    消费 DataCatalog Step 5 注入的 ``annotations_current`` 中
    ``layer_type == "external_natural_village"`` 的注记（source: tencent/amap/tianditu），
    作为自然村名的权威坐标（gazetteer 金标准），解决"多村名绑同 cluster"。
    """
    if bundle is None:
        return []
    # Uploaded annotation points are authoritative GIS evidence, but the
    # grounding contract requires a BSM-backed entry.  Bind each point to the
    # actual landuse parcel that contains/touches it; this is a deterministic
    # geometric relation, never a name-based or nearest-parcel guess.
    landuse = list((getattr(bundle, "polygons", None) or {}).get("landuse_current") or [])
    from shapely.geometry import Point, shape

    def bsms_at(coords: Any) -> List[str]:
        try:
            point = Point(float(coords[0]), float(coords[1]))
        except (TypeError, ValueError, IndexError):
            return []
        matched: List[str] = []
        for parcel in landuse:
            try:
                geom = shape(getattr(parcel, "geometry", None) or {})
                if not geom.is_empty and (geom.contains(point) or geom.touches(point)):
                    bsm = str(getattr(parcel, "bsm", "") or "").strip()
                    if bsm:
                        matched.append(bsm)
            except Exception:
                continue
        return matched

    entries: List[GazetteerEntry] = []
    for f in (bundle.points.get("annotations_current") or []):
        layer_type = str(getattr(f, "layer_type", "") or "")
        raw = getattr(f, "_raw", {}) or {}
        if (not isinstance(raw, dict) or not raw) and hasattr(f, "model_dump"):
            try:
                raw = f.model_dump(by_alias=True)
            except Exception:
                raw = {}
        # Accept both the external-provider contract and ordinary uploaded
        # annotation.geojson (分类=村名, 注记=...).  The latter is source GIS
        # evidence, not a generated label, so it must participate in lookup.
        is_named_annotation = str(raw.get("分类", raw.get("category", "")) or "").strip() in {"村名", "自然村"}
        if layer_type != "external_natural_village" and not is_named_annotation:
            continue
        name_norm = str(
            raw.get("name_norm") or raw.get("注记") or raw.get("text") or ""
        ).strip()
        anchor_source = str(raw.get("anchor_source", "uploaded_annotation") or "").strip()
        if not name_norm:
            continue
        geom = f.geometry or {}
        coords = geom.get("coordinates") or []
        if len(coords) != 2:
            continue
        entries.append(GazetteerEntry(
            name=name_norm,
            aliases=[],
            entity_uri=f"pln:external_{anchor_source}_{name_norm}",
            bsms=bsms_at(coords),
            centroid=[float(coords[0]), float(coords[1])],
            source=anchor_source or "external_anchors",
            confidence=0.9,
            description=f"{name_norm}（多源 API {anchor_source} 坐标）",
        ))
    return entries


def _annotation_entries_from_memory(memory: Any, bundle: Any) -> List[GazetteerEntry]:
    """SemanticMemoryStore 注解（L1 回流产物：村名→BSM）→ 条目候选。"""
    from app.spatial.model.geometry import _compute_centroid

    entries: List[GazetteerEntry] = []
    parcels_by_bsm = {}
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
                    parcels_by_bsm[bsm] = c
    for uri, ann in (memory.entity_annotations or {}).items():
        desc = ann.description or ""
        if "村" in desc or "自然村" in desc or ann.entity_type == "LocationAnchor":
            name = desc.split("（")[0].strip()
            if not name:
                continue
            bsms = [
                str(ref)
                for ref in (ann.intent_refs or [])
                if str(ref).isdigit()
            ]
            centroid = None
            points = [parcels_by_bsm[b] for b in bsms if b in parcels_by_bsm]
            if points:
                centroid = [
                    sum(point[0] for point in points) / len(points),
                    sum(point[1] for point in points) / len(points),
                ]
            entries.append(GazetteerEntry(
                name=name[:20],
                entity_uri=uri,
                bsms=bsms,
                centroid=centroid,
                source="l1_enrichment",
                confidence=float(ann.confidence or 0.5),
                description=desc,
            ))
    return entries


def build_gazetteer(kg: Any, bundle: Any, memory: Any = None) -> Gazetteer:
    """Build the village gazetteer from KG clusters + L1 enrichment memory.

    Non-fatal: KG query failures degrade to an empty gazetteer.
    """
    gazetteer = Gazetteer()
    try:
        for e in _cluster_entries_from_kg(kg, bundle):
            gazetteer.upsert(e)
        for e in _facility_entries_from_kg(kg):
            gazetteer.upsert(e)
    except Exception as e:
        logger.warning("[Gazetteer] cluster build failed: %s", e)
    # 多源 API 自然村权威坐标（进入 bundle 前 enrichment 注入）— 金标准村名条目
    try:
        for e in _external_anchors_from_bundle(bundle):
            gazetteer.upsert(e)
    except Exception as e:
        logger.warning("[Gazetteer] external anchors build failed: %s", e)
    if memory is not None:
        try:
            for e in _annotation_entries_from_memory(memory, bundle):
                # 同 entity_uri 聚类已有 bsms/centroid → 继承（修复 l1_enrichment
                # 注解条目 bsms 恒空导致同名/同 URI 条目覆盖聚类地块集的问题）
                twin = next(
                    (x for x in gazetteer.entries
                     if x.entity_uri and x.entity_uri == e.entity_uri and x.bsms),
                    None,
                )
                if twin is not None and not e.bsms:
                    e = GazetteerEntry(
                        name=e.name,
                        aliases=e.aliases,
                        entity_uri=e.entity_uri,
                        bsms=list(twin.bsms),
                        centroid=twin.centroid or e.centroid,
                        source=e.source,
                        confidence=e.confidence,
                        description=e.description,
                    )
                gazetteer.upsert(e)
        except Exception as e:
            logger.warning("[Gazetteer] memory build failed: %s", e)
    logger.info("[Gazetteer] built: %d entries", len(gazetteer.entries))
    return gazetteer


async def confirm_with_llm(
    llm: Any,
    village_name: str,
    cluster_name: str,
    cluster_desc: str,
) -> bool:
    """Flash 双确认之一：LLM 判定村名与居民点聚类是否一致（有界：只返回判定）。"""
    prompt = (
        "你是村庄地名匹配助手。判断下列村名是否与该居民点的空间描述一致。\n"
        f"村名：{village_name}\n"
        f"居民点：{cluster_name}\n"
        f"空间描述：{cluster_desc}\n"
        "只输出 JSON：{\"match\": true} 或 {\"match\": false}\n"
    )
    try:
        resp = await llm.ainvoke(prompt)
        content = getattr(resp, "content", "") or ""
        import re

        m = re.search(r"\"match\"\s*:\s*(true|false)", content)
        if m:
            return m.group(1) == "true"
    except Exception as e:
        logger.warning("[Gazetteer] LLM confirm failed: %s", e)
    return False


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
    "confirm_with_llm",
    "spatial_check",
    "_external_anchors_from_bundle",
]
