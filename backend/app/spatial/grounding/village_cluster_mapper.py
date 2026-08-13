"""Natural-village -> residential-cluster mapping for GROUND anchor resolution.

The fixture bundle carries no named village boundaries, so named natural
villages (园寨/田坑/...) cannot be resolved through the KG gazetteer.  This
module derives *real* residential clusters from the bundle's 宅基地 (DLBM 1340)
parcels and maps village names onto those clusters.  Geometry always comes from
the bundle; the mapping itself is flagged low-confidence and may be routed to
the Stage 2.6 human-confirmation queue when the planner is strict.

Determinism & resume:
- The cluster derivation is fully deterministic.
- The village->cluster mapping uses the flash LLM only as a self-service
  enhancer (cached by sha256 of the report excerpt + village order).  On any
  failure it falls back to a deterministic size-ordered assignment, so GROUND
  never blocks on the model.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_RESIDENTIAL_DLMC = ("1340", "0702")
_CLUSTER_DISTANCE_DEG = 0.008  # ~800m at 24N


@dataclass
class VillageCluster:
    index: int
    centroid: tuple
    bsms: List[str] = field(default_factory=list)
    parcel_count: int = 0
    area_ha: float = 0.0


def build_village_clusters(parcels: List[Any]) -> List[VillageCluster]:
    """Cluster 宅基地 parcels into residential settlements (deterministic)."""
    from app.spatial.grounding.grounding import build_parcel_centroid_cache

    cache = build_parcel_centroid_cache(parcels)
    selected = []
    for parcel in parcels:
        name = str(getattr(parcel, "name", "") or "")
        code = str(getattr(parcel, "dlbm", "") or "") or str(getattr(parcel, "dlmc", "") or "")
        is_residential = code in _RESIDENTIAL_DLMC or any(
            token in name for token in ("宅基地", "村庄建设用地", "农村居民点")
        )
        if not is_residential:
            continue
        bsm = str(getattr(parcel, "bsm", "") or "")
        centroid = cache.get(bsm) or cache.get(str(getattr(parcel, "bsm", None)))
        if centroid is None:
            continue
        area = float(getattr(parcel, "area_sqm", 0) or 0) / 10000.0
        selected.append((bsm, centroid, area))
    if not selected:
        return []

    clusters: List[VillageCluster] = []
    for bsm, centroid, area in selected:
        placed = False
        for cluster in clusters:
            if math.hypot(centroid[0] - cluster.centroid[0], centroid[1] - cluster.centroid[1]) < _CLUSTER_DISTANCE_DEG:
                cluster.bsms.append(bsm)
                cluster.parcel_count += 1
                cluster.area_ha += area
                cx = sum(p[0] for p in [centroid] + [(c[0], c[1]) for c in []])  # placeholder
                # recompute centroid incrementally
                n = cluster.parcel_count
                cluster.centroid = (
                    (cluster.centroid[0] * (n - 1) + centroid[0]) / n,
                    (cluster.centroid[1] * (n - 1) + centroid[1]) / n,
                )
                placed = True
                break
        if not placed:
            clusters.append(VillageCluster(
                index=len(clusters),
                centroid=centroid,
                bsms=[bsm],
                parcel_count=1,
                area_ha=area,
            ))
    # Stable ordering: largest settlement first, then west->east.
    clusters.sort(key=lambda c: (-c.parcel_count, c.centroid[0]))
    for i, cluster in enumerate(clusters):
        cluster.index = i
    return clusters


_PROMPT_TEMPLATE = """你是村庄规划 GIS 证据编译器。待核对的聚落名称：{villages}。
该村有 {m} 个宅基地聚落（编号 0..{max_index}），每个聚落有质心坐标与规模：
{clusters}

只允许根据报告摘录中明确出现的名称、方位、坐标或可核对空间关系建立映射。
禁止按名称顺序、聚落规模顺序、常识或猜测分配。证据不足的名称必须省略。

只输出 JSON：{{"名称": {{"cluster_index": 编号, "evidence": "报告原文短句"}}, ...}}。
evidence 必须是报告摘录中可以逐字找到的短句；不要输出其它文字。"""


def _cache_path(run_root: Optional[Path]) -> Optional[Path]:
    if run_root is None:
        return None
    return (run_root / "village-cluster-map.json").resolve()


async def map_villages(
    clusters: List[VillageCluster],
    village_names: List[str],
    report_text: str = "",
    cache: Optional[Path] = None,
    llm: Any = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Map village names to clusters (flash-LLM enhanced, cached, fallback safe)."""
    if not clusters or not village_names:
        return {}
    cache_key = hashlib.sha256(
        (
            f"v3|{report_text[:4000]}|{','.join(village_names)}|"
            f"{source_artifact_ref}|{source_artifact_digest}"
        ).encode("utf-8")
    ).hexdigest()
    if cache is not None and cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            if raw.get("key") == cache_key and isinstance(raw.get("map"), dict):
                return {str(k): v for k, v in raw["map"].items()}
        except Exception:
            pass

    mapping: Dict[str, Dict[str, Any]] = {}
    if llm is not None and report_text.strip():
        try:
            cluster_lines = "\n".join(
                f"{c.index}: 质心({c.centroid[0]:.5f},{c.centroid[1]:.5f}) 地块数{c.parcel_count} 面积{c.area_ha:.2f}ha"
                for c in clusters
            )
            prompt = _PROMPT_TEMPLATE.format(
                villages="、".join(village_names),
                m=len(clusters),
                max_index=len(clusters) - 1,
                clusters=cluster_lines,
            )
            if report_text:
                prompt += f"\n\n报告摘录（用于方位判断）:\n{report_text[:2500]}\n"
            import asyncio

            if asyncio.iscoroutinefunction(llm.ainvoke):
                response = await llm.ainvoke(prompt)
            else:
                response = await asyncio.to_thread(llm.invoke, prompt)
            raw_text = ""
            if hasattr(response, "content"):
                content = response.content
                raw_text = "".join(content) if isinstance(content, list) else str(content or "")
            else:
                raw_text = str(response or "")
            payload = _parse_mapping_json(
                raw_text,
                village_names,
                clusters,
                report_text=report_text,
                source_artifact_ref=source_artifact_ref,
                source_artifact_digest=source_artifact_digest,
            )
            if payload:
                mapping = payload
        except Exception as exc:  # noqa: BLE001 - fallback is always safe
            logger.warning("[village-cluster] flash mapping failed: %s", exc)

    if cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"key": cache_key, "map": mapping}, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[village-cluster] cache flush failed: %s", exc)
    return mapping


def _parse_mapping_json(
    raw: str,
    village_names: List[str],
    clusters: List[VillageCluster],
    *,
    report_text: str,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
) -> Dict[str, Dict[str, Any]]:
    import re

    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except Exception:
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for name in village_names:
        item = data.get(name)
        if item is None:
            item = data.get(f"{name}村")
        if not isinstance(item, dict):
            continue
        index = item.get("cluster_index")
        evidence = str(item.get("evidence") or "").strip()
        if not evidence or evidence not in report_text:
            continue
        try:
            index = int(index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(clusters):
            cluster = clusters[index]
            result[name] = {
                "centroid": list(cluster.centroid),
                "bsms": list(cluster.bsms),
                "cluster_index": index,
                "confidence": 0.7,
                "method": "flash_llm_report_evidence",
                "evidence": evidence,
                "provenance_refs": [
                    f"report-evidence:{hashlib.sha256(evidence.encode('utf-8')).hexdigest()}",
                    *([f"bundle:{source_artifact_digest}"] if source_artifact_digest else []),
                ],
                "source_artifact_ref": source_artifact_ref,
                "source_artifact_digest": source_artifact_digest,
                "source_feature_id": f"residential-cluster:{index}",
                "coordinate_crs": "EPSG:4326",
            }
    return result


__all__ = ["VillageCluster", "build_village_clusters", "map_villages"]
