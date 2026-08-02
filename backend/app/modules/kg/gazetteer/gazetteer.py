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
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_GAZETTEER_DIR = Path(__file__).resolve().parents[5] / "data" / "gazetteer"

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "aliases": self.aliases,
            "entity_uri": self.entity_uri,
            "bsms": self.bsms,
            "centroid": self.centroid,
            "source": self.source,
            "confidence": self.confidence,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GazetteerEntry":
        return cls(**{k: data.get(k, v) for k, v in {
            "name": "", "aliases": [], "entity_uri": "", "bsms": [],
            "centroid": None, "source": "kg_cluster", "confidence": 0.0,
            "description": "",
        }.items()})


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
            self.entries.remove(existing)
        self.entries.append(entry)
        self._by_name[entry.name] = entry
        for alias in entry.aliases:
            self._by_name.setdefault(alias, entry)

    def to_dict(self) -> Dict[str, Any]:
        return {"entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Gazetteer":
        return cls([GazetteerEntry.from_dict(e) for e in data.get("entries", [])])


def gazetteer_path(village: str) -> Path:
    _GAZETTEER_DIR.mkdir(parents=True, exist_ok=True)
    return _GAZETTEER_DIR / f"{village}.json"


def save_gazetteer(gazetteer: Gazetteer, village: str) -> Path:
    path = gazetteer_path(village)
    path.write_text(json.dumps(gazetteer.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_gazetteer(village: str) -> Gazetteer:
    path = gazetteer_path(village)
    if not path.exists():
        return Gazetteer()
    try:
        return Gazetteer.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as e:
        logger.warning("[Gazetteer] load failed: %s", e)
        return Gazetteer()


def _cluster_entries_from_kg(kg: Any, bundle: Any) -> List[GazetteerEntry]:
    """KG ResidentialCluster（hasCentroid + 空间距离选地块集）。

    builder 的地块 sfWithin 聚类关系未生效（实测只指向 village）— 改用聚类质心
    （GEO:hasCentroid WKT）+ bundle 地块几何距离（400m 阈值）确定聚类内地块。
    """
    from rdflib import RDF
    from app.modules.kg.ontology import GEO, PLN, EntityTypes
    from app.modules.spatial_ops.geometry import _compute_centroid

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


def _annotation_entries_from_memory(memory: Any, bundle: Any) -> List[GazetteerEntry]:
    """SemanticMemoryStore 注解（L1 回流产物：村名→BSM）→ 条目候选。"""
    from app.modules.spatial_ops.geometry import _compute_centroid

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
        if "村" in desc or "自然村" in desc:
            name = desc.split("（")[0].strip()
            if not name:
                continue
            bsms = []
            for ref in (ann.source_text_refs or []):
                pass
            centroid = None
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
    except Exception as e:
        logger.warning("[Gazetteer] cluster build failed: %s", e)
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
    "load_gazetteer",
    "save_gazetteer",
    "confirm_with_llm",
    "spatial_check",
]
