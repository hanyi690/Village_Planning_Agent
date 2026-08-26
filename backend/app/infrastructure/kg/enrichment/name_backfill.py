"""LLM-assisted name backfill for nameless KG entities.

KG spatial entities built from the GIS bundle often carry placeholder names
(Road ``道路_xxx``, WaterBody ``水体_xxx``/``溪流_xxx``, Facility single-char
labels, ResidentialCluster ``居民点N``).  L1/L3 reports extract real names
(``Y122乡道`` / ``金田河`` / ``祠堂``).  This module matches each real name to a
nameless KG entity of the same type and location — using KG topology and the
current facility points — and writes the name back.

Boundary: the LLM only resolves ambiguity between a small set of candidates.
BSMs, coordinates and geometry always come from the bundle/KG, never from the
model.  A mention that cannot be matched stays unresolved; no class-level or
whole-village parcel pool is ever substituted.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from rdflib import RDF, Literal, URIRef

from app.infrastructure.kg.ontology import PLN, EntityTypes
from app.infrastructure.logging import get_logger
from app.contracts.spatial.spatial_reference_contracts import (
    CandidateSelectionProposal,
    SpatialCandidateDecision,
    candidate_set_digest,
    spatial_candidate_descriptor,
    spatial_candidate_input_digest,
    stable_spatial_candidate_id,
    validate_spatial_candidate_proposal,
)

logger = get_logger(__name__)


class NameMention(BaseModel):
    """One real place name extracted from an L1/L3 report."""

    name: str
    role: str = "unknown"  # water / road / facility / village / landmark
    location: str = ""     # 位置列原始文本（自然村名 / 方位描述 / 空）
    source_dimension: str = ""


class BackfillResult(BaseModel):
    applied: int = 0
    unresolved: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)


_ROLE_TO_ENTITY_TYPE = {
    "water": EntityTypes.WaterBody,
    "road": EntityTypes.Road,
    "facility": EntityTypes.Facility,
    "village": EntityTypes.ResidentialCluster,
}

_GENERIC_NAME_MARKERS = {
    "road": ("道路", "road", "村道", "乡道", "县道"),
    "water": ("水体", "溪流", "水塘", "坑塘", "水域", "河流", "湖泊"),
    "facility": ("设施", "建筑", "facility", "unknown"),
    "village": ("居民点", "settlement", "cluster"),
}


def is_generic_name(name: str, role: str) -> bool:
    """True when a KG entity name is a placeholder rather than a real name."""
    name = (name or "").strip()
    if not name:
        return True
    if role == "facility" and len(name) <= 1:
        return True
    markers = _GENERIC_NAME_MARKERS.get(role, ())
    return any(marker in name for marker in markers)


def _entity_name(kg: Any, subject: Any) -> str:
    return str(kg.g.value(subject, PLN.name) or "").strip()


def _entity_bsm(kg: Any, subject: Any) -> str:
    return str(kg.g.value(subject, PLN.bsm) or "").strip()


def _entity_centroid(kg: Any, subject: Any) -> Optional[tuple[float, float]]:
    try:
        from app.infrastructure.kg.ontology import GeoPredicates
        from app.spatial.grounding.coordinate_identity import point_xy

        for geometry in kg.g.objects(subject, GeoPredicates.hasCentroid):
            wkt = kg.g.value(geometry, GeoPredicates.asWKT)
            point = point_xy(str(wkt or ""))
            if point is not None:
                return point
    except Exception:
        pass
    lon = kg.g.value(subject, PLN.lon)
    lat = kg.g.value(subject, PLN.lat)
    try:
        return (float(lon), float(lat)) if lon is not None and lat is not None else None
    except (TypeError, ValueError):
        return None


def nameless_entities(kg: Any, role: str) -> List[Dict[str, Any]]:
    """Return KG entities of ``role`` that still carry a placeholder name."""
    entity_type = _ROLE_TO_ENTITY_TYPE.get(role)
    if entity_type is None:
        return []
    out: List[Dict[str, Any]] = []
    for subject in kg.g.subjects(RDF.type, entity_type):
        name = _entity_name(kg, subject)
        if not is_generic_name(name, role):
            continue
        out.append({
            "entity_uri": str(subject),
            "candidate_id": stable_spatial_candidate_id(
                {"entity_uri": str(subject)}, namespace="kg"
            ),
            "role": role,
            "current_name": name,
            "bsm": _entity_bsm(kg, subject),
            "centroid": _entity_centroid(kg, subject),
        })
    return out


def _village_bsms(gazetteer: Any, location: str) -> set:
    if not location or gazetteer is None:
        return set()
    entry = gazetteer.resolve(location, fuzzy=False) or gazetteer.resolve(location, fuzzy=True)
    if entry is None:
        return set()
    return {str(b) for b in (entry.bsms or []) if b}


def _village_centroid(gazetteer: Any, location: str) -> Optional[tuple[float, float]]:
    if not location or gazetteer is None:
        return None
    entry = gazetteer.resolve(location, fuzzy=False) or gazetteer.resolve(location, fuzzy=True)
    if entry is None or not entry.centroid:
        return None
    return (float(entry.centroid[0]), float(entry.centroid[1]))


def _haversine_m(a, b) -> float:
    import math

    if a is None or b is None:
        return float("inf")
    lon1, lat1 = a
    lon2, lat2 = b
    radius = 6371000.0
    dlon = math.radians(lon2 - lon1)
    dlat = math.radians(lat2 - lat1)
    s = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(s))


def build_candidates(
    kg: Any,
    gazetteer: Any,
    mention: NameMention,
    *,
    max_centroid_distance_m: float = 1200.0,
) -> List[Dict[str, Any]]:
    """Narrow nameless entities to the mention's type and location.

    Deterministic only.  Returns a scored candidate list ordered by spatial
    evidence strength; an empty list means no nameless entity of the right type
    is near the mention's location (fail-closed, never a whole-village pool).
    """
    entities = nameless_entities(kg, mention.role)
    if not entities:
        return []
    village_bsms = _village_bsms(gazetteer, mention.location)
    village_centroid = _village_centroid(gazetteer, mention.location)

    candidates: List[Dict[str, Any]] = []
    for entity in entities:
        evidence: List[str] = []
        bsm = entity["bsm"]
        centroid = entity["centroid"]
        if bsm and village_bsms and bsm in village_bsms:
            evidence.append("entity_bsm_in_village")
        if village_centroid is not None and centroid is not None:
            distance = _haversine_m(village_centroid, centroid)
            if distance <= max_centroid_distance_m:
                evidence.append("entity_centroid_near_village")
            entity["centroid_distance_m"] = round(distance, 1)
        if not evidence:
            continue
        entity["evidence"] = evidence
        candidates.append(entity)
    candidates.sort(
        key=lambda c: (
            "entity_bsm_in_village" not in c["evidence"],
            c.get("centroid_distance_m", float("inf")),
        )
    )
    return candidates


def _write_name(kg: Any, entity_uri: str, name: str) -> None:
    kg.g.set((URIRef(entity_uri), PLN.name, Literal(name)))


async def _llm_confirm(
    llm: Any,
    mention: NameMention,
    candidates: List[Dict[str, Any]],
    *,
    budget: Optional[Dict[str, Any]] = None,
) -> Optional[SpatialCandidateDecision]:
    """Ask the flash model to pick a candidate for an ambiguous mention.

    Returns the validated selection decision or None when the provider is
    unavailable.
    """
    if llm is None:
        logger.info(
            "[name-backfill] no LLM supplied; leaving ambiguous name unresolved: %s",
            mention.name,
        )
        return None
    from app.spatial.grounding.call_budget import (
        reserve_ground_llm_call,
        run_ground_llm_call,
    )

    call_timeout = reserve_ground_llm_call(budget)
    if call_timeout is None:
        logger.info(
            "[name-backfill] grounding LLM budget exhausted; keeping mention unresolved: %s",
            mention.name,
        )
        return None
    descriptors = [
        spatial_candidate_descriptor(candidate, kind="kg_name_backfill")
        for candidate in candidates
    ]
    decision_id = f"kg-name-backfill:{mention.role}:{mention.name}:{mention.location}"
    query_text = f"{mention.name}\n{mention.role}\n{mention.location}"
    input_digest = spatial_candidate_input_digest(
        decision_id=decision_id,
        query_text=query_text,
        candidates=descriptors,
    )
    lines = "\n".join(
        f"candidate_id={descriptor.candidate_id} 类型={candidate['role']} "
        f"现名={candidate['current_name']!r} BSM={candidate['bsm'] or '无'} "
        f"质心={candidate['centroid'] or '无'}"
        for candidate, descriptor in zip(candidates, descriptors)
    )
    prompt = (
        f"地名「{mention.name}」（类型 {mention.role}）提到位于「{mention.location or '未知'}」。"
        "下列是本次输入动态生成的候选 KG 实体。"
        "status 只能为 selected/abstain/ambiguous；selected 时填写稳定 candidate_id；"
        f"input_digest={input_digest}；"
        f"不要输出序号、候选名称或新 ID。\n{lines}"
    )
    try:
        from app.infrastructure.llm.structured import run_structured_output

        async def _invoke():
            return await run_structured_output(
                CandidateSelectionProposal,
                [{"role": "user", "content": prompt}],
                llm=llm,
                max_retries=1,
                timeout=call_timeout,
            )

        response = await run_ground_llm_call(budget, call_timeout, _invoke)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[name-backfill] LLM confirm failed: %s", exc)
        return None
    try:
        decision = validate_spatial_candidate_proposal(
            decision_id=decision_id,
            query_text=query_text,
            candidates=descriptors,
            proposal=response,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[name-backfill] typed candidate choice rejected: %s", exc)
        return None
    return decision


async def backfill_kg_names(
    kg: Any,
    gazetteer: Any,
    mentions: List[NameMention],
    *,
    llm: Any = None,
    cache_path: Optional[Path] = None,
    budget: Optional[Dict[str, Any]] = None,
) -> BackfillResult:
    """Match real names to nameless KG entities and write them back.

    Deterministic single-candidate matches are applied without an LLM call.
    Ambiguous matches (multiple candidates) go through a flash confirmation.
    Unmatched mentions remain unresolved (never a class-level fallback).
    """
    cache: Dict[str, Any] = {}
    if cache_path is not None and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[name-backfill] cache load failed: %s", exc)

    result = BackfillResult()
    pending: List[
        tuple[
            NameMention,
            List[Dict[str, Any]],
            str,
            str,
            str,
            str,
        ]
    ] = []
    for mention in mentions:
        key = hashlib.sha256(
            json.dumps(
                {
                    "name": mention.name,
                    "role": mention.role,
                    "location": mention.location,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        candidates = build_candidates(kg, gazetteer, mention)
        descriptors = [
            spatial_candidate_descriptor(candidate, kind="kg_name_backfill")
            for candidate in candidates
        ]
        decision_id = f"kg-name-backfill:{mention.role}:{mention.name}:{mention.location}"
        query_text = f"{mention.name}\n{mention.role}\n{mention.location}"
        input_digest = spatial_candidate_input_digest(
            decision_id=decision_id,
            query_text=query_text,
            candidates=descriptors,
        )
        set_digest = candidate_set_digest(descriptors)
        chosen: Optional[Dict[str, Any]] = None
        if len(candidates) == 1:
            chosen = next(iter(candidates))
        elif len(candidates) > 1:
            cache_entry = cache.get(key)
            if (
                isinstance(cache_entry, dict)
                and cache_entry.get("candidate_set_digest") == set_digest
                and cache_entry.get("input_digest") == input_digest
            ):
                chosen = next(
                    (
                        c
                        for c in candidates
                        if c["candidate_id"] == cache_entry.get("candidate_id")
                    ),
                    None,
                )
            if chosen is None:
                pending.append(
                    (mention, candidates, key, input_digest, set_digest, decision_id)
                )
        if chosen is None:
            if len(candidates) <= 1:
                result.unresolved.append(mention.name)
                continue
            result.pending.append(mention.name)
            continue
        _write_name(kg, chosen["entity_uri"], mention.name)
        cache[key] = {
            "candidate_id": chosen["candidate_id"],
            "candidate_set_digest": set_digest,
            "input_digest": input_digest,
        }
        result.applied += 1
        result.decisions.append({
            "name": mention.name,
            "role": mention.role,
            "entity_uri": chosen["entity_uri"],
            "candidate_id": chosen["candidate_id"],
            "source_dimension": mention.source_dimension,
            "evidence": chosen.get("evidence", []),
            "candidate_set_digest": set_digest,
            "input_digest": input_digest,
        })

    if pending:
        decisions = await asyncio.gather(*(
            _llm_confirm(llm, mention, candidates, budget=budget)
            for mention, candidates, _, _, _, _ in pending
        ))
        # Commit in mention order.  Calls may run concurrently, but KG writes
        # and cache updates stay deterministic and avoid shared-graph races.
        for (
            (mention, candidates, key, input_digest, set_digest, _decision_id),
            decision,
        ) in zip(pending, decisions):
            selected_id = (
                decision.selected_candidate_id
                if decision is not None and decision.status == "selected"
                else None
            )
            chosen = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate["candidate_id"] == selected_id
                ),
                None,
            )
            if chosen is None:
                if mention.name not in result.pending:
                    result.pending.append(mention.name)
                continue
            _write_name(kg, chosen["entity_uri"], mention.name)
            cache[key] = {
                "candidate_id": chosen["candidate_id"],
                "candidate_set_digest": set_digest,
                "input_digest": input_digest,
            }
            result.applied += 1
            result.decisions.append({
                "name": mention.name,
                "role": mention.role,
                "entity_uri": chosen["entity_uri"],
                "candidate_id": chosen["candidate_id"],
                "source_dimension": mention.source_dimension,
                "evidence": chosen.get("evidence", []),
                "candidate_set_digest": set_digest,
                "input_digest": input_digest,
            })

    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
            tmp.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            tmp.replace(cache_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[name-backfill] cache flush failed: %s", exc)

    logger.info(
        "[name-backfill] applied=%d unresolved=%d pending=%d",
        result.applied,
        len(result.unresolved),
        len(result.pending),
    )
    return result


def backfill_kg_names_sync(
    kg: Any,
    gazetteer: Any,
    mentions: List[NameMention],
) -> BackfillResult:
    """Deterministic, synchronous single-candidate name backfill (no LLM).

    Suitable for the context factory, which builds the EvidenceGraph
    synchronously.  Only unique candidates are written; ambiguous mentions are
    left unresolved for the async LLM-confirmation path.
    """
    result = BackfillResult()
    for mention in mentions:
        candidates = build_candidates(kg, gazetteer, mention)
        if len(candidates) != 1:
            if len(candidates) > 1:
                result.pending.append(mention.name)
            else:
                result.unresolved.append(mention.name)
            continue
        chosen = next(iter(candidates))
        descriptors = [
            spatial_candidate_descriptor(candidate, kind="kg_name_backfill")
            for candidate in candidates
        ]
        input_digest = spatial_candidate_input_digest(
            decision_id=f"kg-name-backfill:{mention.role}:{mention.name}:{mention.location}",
            query_text=f"{mention.name}\n{mention.role}\n{mention.location}",
            candidates=descriptors,
        )
        _write_name(kg, chosen["entity_uri"], mention.name)
        result.applied += 1
        result.decisions.append({
            "name": mention.name,
            "role": mention.role,
            "entity_uri": chosen["entity_uri"],
            "candidate_id": chosen["candidate_id"],
            "source_dimension": mention.source_dimension,
            "evidence": chosen.get("evidence", []),
            "candidate_set_digest": candidate_set_digest(descriptors),
            "input_digest": input_digest,
        })
    if result.applied or result.unresolved or result.pending:
        logger.info(
            "[name-backfill] sync applied=%d unresolved=%d pending=%d",
            result.applied,
            len(result.unresolved),
            len(result.pending),
        )
    return result


__all__ = [
    "BackfillResult",
    "NameMention",
    "backfill_kg_names",
    "backfill_kg_names_sync",
    "build_candidates",
    "is_generic_name",
    "nameless_entities",
]
