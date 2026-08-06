"""SpatialResolver - single entry point for spatial reference resolution.

Consolidates the three competing spatial-semantics implementations into one
place, all reading from a ``PlanningContext``:

    resolve_text      EXPLORE / GROUND free-text description -> candidates
    resolve_spec      PARSE closed-set SpatialReferenceSpec -> candidates
    resolve_anchors   intent location hints -> candidate BSMs / anchors
    bind              deterministic bundle binding (BSM-first)

Every method takes its facts from ``PlanningContext`` (bundle / gazetteer /
KG / constraint index / kg_query_fn) instead of each caller building its own
gazetteer/KG/center fallback. Callers that only have a village name + anchors
can use the module-level ``resolve_intent_anchors`` helper.

Dependency rule: this module must not import ``app.agent``, ``app.services``
or ``app.api``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Location-token helpers (moved from parse/agent.py to keep GROUND
#    inside spatial_ops; parse/agent.py now delegates to this module). ──

_LOCATION_SEP_RE = re.compile(r"[、，,；;/\s]+|至|和|与")
_LOCATION_STRIP = ("自然村", "村", "组", "段", "沿", "线", "附近", "周边", "区域", "一带")


def _extract_location_tokens(location: str) -> List[str]:
    """位置文本 → 候选 token：'肩丰、田坑' / '肩丰至炉池段' / '园寨自然村'。"""
    tokens = []
    for part in _LOCATION_SEP_RE.split(location or ""):
        part = part.strip()
        for suffix in _LOCATION_STRIP:
            part = part.rstrip(suffix)
        part = part.strip()
        if part and not any(ch.isdigit() for ch in part):
            tokens.append(part)
    return list(dict.fromkeys(tokens))


def _resolve_gazetteer_bsms(token: str, gazetteer: Any) -> List[str]:
    """token → gazetteer 解析 → BSM 列表（精确 → 村后缀 → fuzzy）。"""
    if gazetteer is None:
        return []
    for candidate in (token, f"{token}村", f"{token}自然村", f"{token}组"):
        entry = gazetteer.resolve(candidate, fuzzy=False)
        if entry is not None and entry.bsms:
            return list(entry.bsms)
    entry = gazetteer.resolve(token, fuzzy=True)
    if entry is not None and entry.bsms:
        return list(entry.bsms)
    return []


class SpatialResolver:
    """One resolver bound to one ``PlanningContext``."""

    def __init__(self, context: Any):
        from app.modules.context.planning_context import PlanningContext

        if not isinstance(context, PlanningContext):
            raise TypeError("SpatialResolver requires a PlanningContext")
        self.context = context

    @property
    def bundle(self):
        return self.context.bundle

    @property
    def gazetteer(self):
        return self.context.gazetteer

    @property
    def kg(self):
        return self.context.kg

    @property
    def constraint_index(self):
        return self.context.constraint_index

    @property
    def kg_query_fn(self):
        return self.context.kg_query_fn

    # ── 1. Free-text description (EXPLORE / GROUND) ────────────────

    def resolve_text(self, desc: str) -> "ResolvedSpatialDescription":
        """Resolve a natural-language spatial description to candidate BSMs.

        Delegates to ``grounding.resolve_spatial_description`` with all
        context-injected dependencies (gazetteer / KG / constraint index).
        """
        from .grounding import resolve_spatial_description

        if not desc or self.bundle is None:
            from .grounding import ResolvedSpatialDescription

            return ResolvedSpatialDescription(
                evidence_text=desc,
                unresolved_reason="empty desc or bundle",
            )
        return resolve_spatial_description(
            desc,
            self.bundle,
            kg=self.kg,
            gazetteer=self.gazetteer,
            constraint_index=self.constraint_index,
            kg_query_fn=self.kg_query_fn,
        )

    # ── 2. Closed-set spec (PARSE -> GROUND boundary) ──────────────

    def resolve_spec(self, spec: Any) -> "ResolvedSpatialRef":
        """Resolve a closed-set SpatialReferenceSpec to candidate BSMs.

        Runs KG-side candidate resolution, then filters to bundle parcels and
        applies a directional bbox refinement when the spec carries a direction
        (replacing the village-center bbox fallback used by EXPLORE grounding).
        """
        from app.modules.schema.contracts.spatial_reference_contracts import (
            CandidateSet,
            ResolvedSpatialRef,
        )

        provenance: Dict[str, Any] = {"path": "kg:resolve_candidates"}
        candidates: CandidateSet = CandidateSet()
        port = getattr(self.context.ports, "spatial_query", None)
        try:
            if port is not None:
                run_id = getattr(self.context, "session_id", "") or ""
                result = port.resolve_candidates(run_id, spec)
                if result is not None:
                    candidates = result
            elif self.kg_query_fn is not None:
                result = self.kg_query_fn("resolve_candidates", spec=spec)
                if isinstance(result, dict) and "bsms" in result:
                    candidates = CandidateSet(
                        bsms=[str(b) for b in (result.get("bsms") or [])],
                        ref_bsms=[str(b) for b in (result.get("ref_bsms") or [])],
                    )
                elif isinstance(result, list):
                    bsms = [
                        str(r.get("bsm"))
                        for r in result
                        if isinstance(r, dict) and r.get("bsm")
                    ]
                    candidates = CandidateSet(bsms=bsms)
        except Exception as e:
            logger.warning("[SpatialResolver] resolve_candidates failed: %s", e)
            provenance["error"] = str(e)

        bsms = list(dict.fromkeys([*candidates.bsms, *candidates.ref_bsms]))
        final_bsms = self._filter_to_bundle(bsms)
        provenance["kg_count"] = len(bsms)
        provenance["bundle_count"] = len(final_bsms)

        bbox = None
        direction = getattr(spec, "direction", None)
        if direction:
            try:
                bbox = self._directional_bbox(direction)
                if bbox:
                    provenance["path"] += "+geometry:directional_bbox"
            except Exception as e:
                logger.warning("[SpatialResolver] directional bbox failed: %s", e)

        if not final_bsms and not bbox:
            return ResolvedSpatialRef(
                final_bsms=[],
                bbox=None,
                confidence=0.0,
                provenance={"...": provenance},
            )

        confidence = 0.7 if final_bsms else 0.3
        if not final_bsms and bbox:
            # Directional bbox with no KG match: fall back to geometry query.
            from .grounding import query_parcels_in_bbox

            parcels = self.context.bundle_parcels()
            final_bsms = query_parcels_in_bbox(parcels, bbox)
            provenance["path"] += "+geometry:bbox"
            confidence = 0.8

        return ResolvedSpatialRef(
            final_bsms=final_bsms,
            bbox=bbox,
            confidence=confidence,
            provenance=provenance,
        )

    def _filter_to_bundle(self, bsms: List[str]) -> List[str]:
        """Keep only BSM values that correspond to real bundle parcels."""
        if not bsms:
            return []
        by_bsm: Dict[str, bool] = {}
        for p in self.context.bundle_parcels():
            bsm = str(p.bsm or "").strip()
            if bsm:
                by_bsm[bsm] = True
        return [b for b in bsms if b in by_bsm]

    def _directional_bbox(self, direction: str) -> Optional[tuple]:
        """Directional bbox around the bundle's village center."""
        from .grounding import (
            _village_center,
            resolve_directional_bbox,
        )

        parcels = self.context.bundle_parcels()
        center = _village_center(parcels) if parcels else None
        if center is None:
            return None
        return resolve_directional_bbox(center, direction)

    # ── 3. Intent anchors (PARSE location hints) ───────────────────

    def resolve_anchors(self, intent: Any) -> int:
        """Fill intent target candidate_bsms / anchors from gazetteer + KG anchors."""
        return resolve_intent_anchors(
            intent,
            gazetteer=self.gazetteer,
            village_anchors=self.context.village_anchors,
            village_name=self.context.village_name,
        )

    # ── 4. Deterministic bundle binding (BSM-first) ────────────────

    def bind(self, instructions: Any) -> Dict[str, Any]:
        """Bind instruction candidates to immutable bundle geometry.

        Delegates to ``bundle_binder`` with a gazetteer injected from the
        context so the binder never hardcodes a village name.
        """
        from .bundle_binder import DeterministicBundleBinder

        binder = DeterministicBundleBinder(self.bundle)
        return binder.bind(instructions, gazetteer=self.gazetteer)


# ── Module-level anchor resolution (context-free convenience) ──────────
# Owned by the resolver package so ``parse/agent.py`` delegates to it instead
# of reimplementing gazetteer token matching.


def resolve_intent_anchors(
    intent: Any,
    *,
    gazetteer: Any = None,
    village_anchors: Optional[List[Dict[str, Any]]] = None,
    village_name: str = "",
) -> int:
    """Resolve intent location hints into candidate BSMs / coordinate anchors.

    Mirrors the previous ``parse/agent.py:resolve_spatial_anchors`` contract,
    moved into spatial_ops so GROUND owns all gazetteer/KG anchor resolution.
    Only reads gazetteer + KG anchors; never writes. Returns resolved count.
    """
    if gazetteer is None and not village_anchors:
        return 0

    resolved = 0
    kg_anchors: List[Dict[str, Any]] = []
    for anchor in village_anchors or []:
        try:
            lon = float(anchor.get("lon"))
            lat = float(anchor.get("lat"))
        except (TypeError, ValueError, AttributeError):
            continue
        if lon == 0 and lat == 0:
            continue
        kg_anchors.append({"name": str(anchor.get("name") or ""), "lon": lon, "lat": lat})

    for zt in (getattr(intent, "zone_targets", None) or []):
        location = ""
        if getattr(zt, "spatial_preference", None) is not None:
            location = zt.spatial_preference.reference or ""
        if not location and getattr(zt, "semantic", None) is not None:
            location = getattr(zt.semantic, "spatial_hint", "") or ""
        for token in _extract_location_tokens(location):
            bsms = _resolve_gazetteer_bsms(token, gazetteer)
            if bsms and not any(b in (zt.candidate_bsms or []) for b in bsms):
                zt.candidate_bsms.extend(bsms)
                resolved += 1

    for ft in (getattr(intent, "facilities", None) or []):
        location = (getattr(ft, "location_hint", "") or getattr(ft, "anchor_village", "")) or ""
        for token in _extract_location_tokens(location):
            bsms = _resolve_gazetteer_bsms(token, gazetteer)
            if bsms and not any(b in (ft.candidate_bsms or []) for b in bsms):
                ft.candidate_bsms.extend(bsms)
                resolved += 1
        if getattr(ft, "anchor_point", None) is None and kg_anchors:
            matched = next(
                (a for a in kg_anchors if a["name"] and a["name"] in location),
                None,
            )
            if matched:
                ft.anchor_point = (matched["lon"], matched["lat"])
                ft.semantic.reasoning_trace = "KG village anchor matched by location hint"
                resolved += 1

    for ax in (getattr(intent, "development_axes", None) or []):
        location = (getattr(ax, "reference_feature", "")
                    or (getattr(getattr(ax, "semantic", None), "spatial_hint", "") or ""))
        for token in _extract_location_tokens(location):
            bsms = _resolve_gazetteer_bsms(token, gazetteer)
            if bsms and not any(b in (ax.corridor_bsms or []) for b in bsms):
                ax.corridor_bsms.extend(bsms)
                resolved += 1

    for prj in (getattr(intent, "project_targets", None) or []):
        location = (getattr(prj, "location_hint", "")
                    or (getattr(getattr(prj, "semantic", None), "spatial_hint", "") or ""))
        for token in _extract_location_tokens(location):
            bsms = _resolve_gazetteer_bsms(token, gazetteer)
            if bsms and not any(b in (prj.candidate_bsms or []) for b in bsms):
                prj.candidate_bsms.extend(bsms)
                resolved += 1
        if not (prj.candidate_bsms or []) and kg_anchors:
            text = f"{prj.name} {location}"
            matched = next(
                (a for a in kg_anchors if a["name"] and a["name"] in text),
                None,
            )
            if matched:
                prj.semantic.reasoning_trace = "KG village anchor matched by project location hint"
                resolved += 1

    for rt in (getattr(intent, "road_targets", None) or []):
        if not kg_anchors:
            continue
        text = " ".join([
            str(getattr(rt, "road_level", "") or ""),
            str(getattr(rt, "connects", "") or ""),
            str(getattr(getattr(rt, "semantic", None), "natural_language_description", "") or ""),
        ])
        named = [a for a in kg_anchors if a["name"] and a["name"] in text]
        candidates = named if len(named) >= 2 else kg_anchors
        if len(candidates) < 2:
            continue
        if "南北" in text:
            start, end = min(candidates, key=lambda a: a["lat"]), max(candidates, key=lambda a: a["lat"])
        elif "东西" in text:
            start, end = min(candidates, key=lambda a: a["lon"]), max(candidates, key=lambda a: a["lon"])
        else:
            start, end = min(candidates, key=lambda a: (a["lon"], a["lat"])), max(candidates, key=lambda a: (a["lon"], a["lat"]))
        if getattr(rt, "start_anchor", None) is None:
            rt.start_anchor = (start["lon"], start["lat"])
        if getattr(rt, "end_anchor", None) is None:
            rt.end_anchor = (end["lon"], end["lat"])
        if not getattr(rt, "connects", None):
            rt.connects = [start["name"], end["name"]]
        rt.semantic.reasoning_trace = "KG village anchors inferred road endpoints; requires route validation"
        resolved += 1

    if resolved:
        logger.info("[SpatialResolver] anchors resolved: %d entities", resolved)
    return resolved


def resolve_spatial_anchors(
    intent: Any,
    village_name: str = "",
    village_anchors: Optional[List[Dict[str, Any]]] = None,
    gazetteer: Any = None,
) -> int:
    """将 intent 中位置文本解析为具体 BSM 集。

    Thin wrapper around resolve_intent_anchors. The gazetteer should be
    passed by the caller (loaded via PlanningContext). If not provided,
    resolution is skipped (returns 0).
    Migrated from app.agent.select.parse_agent.resolve_spatial_anchors (Wave M2).
    """
    if gazetteer is None and not village_anchors:
        return 0

    return resolve_intent_anchors(
        intent,
        gazetteer=gazetteer,
        village_anchors=village_anchors,
        village_name=village_name,
    )


__all__ = ["SpatialResolver", "resolve_intent_anchors", "resolve_spatial_anchors"]
