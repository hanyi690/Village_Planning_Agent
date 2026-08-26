"""报告 → KG 实体注解（多级增强入口，自 parse/agent.py extract_bindings 迁入）。

 L1 级（wave1）：保留 typed location projection，空间绑定由 GROUND 负责。
 L2/L3 级（wave2/3）：只生成 derived report projection，不写回语义实体。
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_BSM_NUM_RE = re.compile(r"(\d{15,25})")


_VILLAGE_ROLES = frozenset({"village", "natural_village", "settlement", "村庄", "自然村"})


def _location_fact_mentions(location_facts: Optional[List[Any]]) -> List[Dict[str, str]]:
    """Convert structured L1 location facts into KG enrichment mentions.

    Village facts keep the existing ``{base}村`` name suffix (the village-binding
    branch).  Non-village typed facts (facility/project/zone/landmark/...) are
    retained with their original name and an explicit ``role`` so downstream
    consumers can distinguish them without treating them as residential clusters.
    """
    mentions: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for fact in location_facts or []:
        role = str(getattr(fact, "role", "") or "").strip().lower()
        normalized = str(getattr(fact, "normalized_name", "") or "").strip()
        if not normalized:
            continue
        dim = str(getattr(fact, "dimension_key", "") or "l1_location_fact")
        hint = str(
            getattr(fact, "spatial_hint", "")
            or getattr(fact, "source_span", "")
            or normalized
        )[:160]
        for token in re.split(r"[、，,;/至和与\\s]+", normalized):
            token = token.strip()
            if not token:
                continue
            if role in _VILLAGE_ROLES:
                base = token.removesuffix("自然村").removesuffix("村").strip()
                if not base or (base, dim) in seen:
                    continue
                seen.add((base, dim))
                mentions.append({
                    "name": f"{base}村",
                    "role": "village",
                    "hints": hint,
                    "dim": dim,
                })
            else:
                if (token, dim) in seen:
                    continue
                seen.add((token, dim))
                mentions.append({
                    "name": token,
                    "role": role,
                    "hints": hint,
                    "dim": dim,
                })
    return mentions


def project_report_entities(reports: Dict[str, str]) -> Dict[str, Any]:
    """Build a display-only report projection with conflict quarantine.

    The extracted table rows are not accepted KG entities.  A name shared by
    incompatible projection types is quarantined, while repeated rows of the
    same type are deterministically coalesced into one projection item.  No
    claim, fact, action, relation, or semantic-memory write is performed.
    """

    from app.data.ingestion.tables import (
        _extract_project_tables,
        _extract_zone_tables,
    )

    candidates: list[dict[str, Any]] = []
    for dimension_key, content in (reports or {}).items():
        for zone in _extract_zone_tables(content or ""):
            name = str(getattr(zone, "land_use", "") or "").strip()
            if name:
                candidates.append({
                    "projection_name": name,
                    "projection_type": "FunctionalZone",
                    "source_dimensions": [str(dimension_key)],
                })
        for project in _extract_project_tables(content or ""):
            name = str(getattr(project, "type", "") or "").strip()
            if name:
                candidates.append({
                    "projection_name": name,
                    "projection_type": "Project",
                    "source_dimensions": [str(dimension_key)],
                })

    grouped: Dict[str, Dict[str, set[str]]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate["projection_name"], {}).setdefault(
            candidate["projection_type"], set()
        ).update(candidate["source_dimensions"])

    projection_items: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for name in sorted(grouped):
        types = grouped[name]
        if len(types) != 1:
            quarantined.append({
                "code": "report_projection_name_conflict",
                "projection_name": name,
                "projection_types": sorted(types),
                "source_dimensions": sorted({dim for dims in types.values() for dim in dims}),
            })
            continue
        projection_type, dimensions = next(iter(types.items()))
        projection_items.append({
            "projection_name": name,
            "projection_type": projection_type,
            "source_dimensions": sorted(dimensions),
            "authority": "derived_projection",
        })

    return {
        "authority": "derived_projection",
        "projection_items": projection_items,
        "quarantined_projections": quarantined,
    }


async def extract_bindings(
    session_id: str,
    wave: int,
    reports: Dict[str, str],
    kg: Any = None,
    bundle: Any = None,
    location_facts: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Return report projections without admitting report-derived semantics."""

    from app.infrastructure.kg import require_session_kg

    kg = kg if kg is not None else require_session_kg(session_id)
    projection = project_report_entities(reports)
    location_mentions = _location_fact_mentions(location_facts)

    # Building the gazetteer is deliberately read-only here.  Spatial
    # candidate selection and semantic writes belong to GROUND, where the
    # current dynamic candidate set and its digest are available.
    if kg is not None:
        from app.infrastructure.kg.gazetteer import build_gazetteer

        build_gazetteer(
            kg,
            bundle,
            memory=None,
            village_name=str(getattr(bundle, "village_name", "") or ""),
        )

    stats = {
        "wave": wave,
        "authority": projection["authority"],
        "village_bound": 0,
        "anchor_entries": 0,
        "gis_village_entries": 0,
        "semantic_entities": 0,
        "projection_items": projection["projection_items"],
        "quarantined_projections": projection["quarantined_projections"],
        "location_mentions": location_mentions,
    }
    logger.info("[Enrich] session=%s report projection=%s", session_id, stats)
    return stats


async def run_wave(session_id: str, wave: int, reports: Dict[str, str], bundle: Any = None,
                   location_facts: Optional[List[Any]] = None) -> Dict[str, Any]:
    return await extract_bindings(
        session_id, wave, reports, bundle=bundle,
        location_facts=location_facts,
    )


__all__ = ["extract_bindings", "project_report_entities", "run_wave"]
