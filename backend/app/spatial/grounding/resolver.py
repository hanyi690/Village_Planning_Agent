"""SpatialResolver - single entry point for spatial reference resolution.

Consolidates the three competing spatial-semantics implementations into one
place, all reading from a ``PlanningContext``:

    resolve_text      EXPLORE / GROUND free-text description -> candidates
    resolve_spec      PARSE closed-set SpatialReferenceSpec -> candidates
    resolve_anchors   intent location hints -> candidate BSMs / anchors
    bind              deterministic bundle binding (BSM-first)

    Every method takes its facts from ``PlanningContext`` (workspace / gazetteer /
KG / constraint index / evidence index) instead of each caller building its own
gazetteer/KG/center fallback. Callers that only have a village name + anchors
can use the module-level ``resolve_intent_anchors`` helper.

Dependency rule: this module must not import ``app.agent``
or ``app.api``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

# ── Location-token helpers (moved from parse/agent.py to keep GROUND
#    inside grounding; parse/agent.py now delegates to this module). ──

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


def _resolve_gazetteer_entry(token: str, gazetteer: Any):
    """token → gazetteer entry (BSMs + centroid), with village-suffix probes."""
    if gazetteer is None:
        return None
    for candidate in (token, f"{token}村", f"{token}自然村", f"{token}组"):
        entry = gazetteer.resolve(candidate, fuzzy=False)
        if entry is not None and (getattr(entry, "bsms", None) or []):
            return entry
    entry = gazetteer.resolve(token, fuzzy=True)
    if entry is not None and (getattr(entry, "bsms", None) or []):
        return entry
    return None


_DIRECTION_WORDS = ("东北", "东南", "西北", "西南", "北", "南", "东", "西")


def _direction_from_connects(token: str) -> Optional[str]:
    """村北 -> north; 东北 -> northeast; empty when no direction word."""
    text = (token or "").strip()
    if not text:
        return None
    for word in ("东北", "东南", "西北", "西南"):
        if word in text:
            return word
    for word in ("北", "南", "东", "西"):
        if word in text:
            return word
    return None


def _first_village_center(kg_anchors: List[Dict[str, Any]]) -> Optional[tuple]:
    """First non-zero village anchor as the bundle centre for direction math."""
    for anchor in kg_anchors or []:
        lon = anchor.get("lon")
        lat = anchor.get("lat")
        if lon and lat and not (float(lon) == 0.0 and float(lat) == 0.0):
            return (float(lon), float(lat))
    return None


def _village_cluster_for(
    token: str,
    gazetteer: Any,
    village_cluster_map: Optional[Dict[str, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Gazetteer entry first; bundle cluster fallback for a natural village."""
    entry = _resolve_gazetteer_entry(token, gazetteer)
    if entry is not None:
        return {
            "centroid": list(getattr(entry, "centroid", None) or ())
            if getattr(entry, "centroid", None)
            else None,
            "bsms": list(getattr(entry, "bsms", None) or []),
            "source": "gazetteer",
            "confidence": float(getattr(entry, "confidence", 0.0) or 0.0),
        }
    if not village_cluster_map:
        return None
    for key in (token, f"{token}村", f"{token}自然村"):
        if key in village_cluster_map:
            item = village_cluster_map[key]
            return {
                "centroid": list(item.get("centroid") or ()),
                "bsms": list(item.get("bsms") or []),
                "source": "village_cluster",
                "confidence": float(item.get("confidence", 0.4) or 0.4),
            }
    return None


_VILLAGE_ALL_MARKER = "__VILLAGE_ALL__"


_MENTION_SEPARATORS = ("、", "，", ",", "；", ";", "及", "和", "与")


_MENTION_SEPARATORS = ("、", "，", ",", "；", ";", "及", "和", "与")


def _split_mentions(label: str) -> list[str]:
    """Split a combined location cell into discrete mentions."""
    parts = []
    for raw in re.split(r"[、，,；;及和与]+", label or ""):
        part = (raw or "").strip()
        if part:
            parts.append(part)
    return parts


def _normalize_spec_mention(label: str) -> str:
    """Normalize PARSE label_contains into a resolver-friendly mention.

    - '12个自然村' / '9个自然村' / '全村域' /
      '全村' -> whole-village marker
    - '石窟河沿线' / '金田河两岸' -> base entity token
    - pure count/unit text (e.g. '40处') -> empty (no location evidence)
    """
    token = (label or "").strip()
    if not token:
        return ""
    if token in {"全村域", "全村", "村域"} or re.fullmatch(
        r"(?:全村)?\d+个自然村", token
    ):
        return _VILLAGE_ALL_MARKER
    for suffix in (
        "沿线", "两岸", "附近", "周边",
        "一带", "区域", "范围内", "流域", "域",
    ):
        if token.endswith(suffix):
            token = token[: -len(suffix)].strip()
            break
    if not token:
        return ""
    if any(ch.isdigit() for ch in token) and not any(
        ch.isalpha()
        for ch in token.replace("个", "").replace("处", "").replace("座", "")
        .replace("米", "").replace("亩", "")
    ):
        return ""
    return token


def _keyword_dlmc_bsms(context: Any, mention: str) -> list[str]:
    """Fallback: long mentions containing transport/water/forest keywords bind
    the corresponding DLMC parcel groups even when no typed fact matches."""
    try:
        parcels = list(context.current_parcels() or [])
    except Exception:
        return []
    if not parcels:
        return []
    targets = []
    if any(k in mention for k in ("村道", "乡道", "道路", "交通")):
        targets.extend(["村内交通用地", "对外交通用地"])
    if "河" in mention or "水域" in mention:
        targets.append("水域")
    if any(k in mention for k in ("林", "山", "生态", "绿")):
        targets.extend(["生态林", "商品林"])
    if not targets:
        return []
    bsms = [
        str(p.bsm)
        for p in parcels
        if str(getattr(p, "name", "") or "") in targets and str(getattr(p, "bsm", "") or "")
    ]
    return list(dict.fromkeys(bsms))


class SpatialResolver:
    """One resolver bound to one ``PlanningContext``."""

    def __init__(self, context: Any):
        if not (
            hasattr(context, "workspace")
            and hasattr(context, "kg")
        ):
            raise TypeError("SpatialResolver requires a PlanningContext")
        self.context = context

    @property
    def workspace(self):
        return self.context.workspace

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
    def evidence_index(self):
        return self.context.evidence_index

    # ── 1. Free-text description (EXPLORE / GROUND) ────────────────

    def resolve_text(self, desc: str) -> "ResolvedSpatialDescription":
        """Resolve a natural-language spatial description to candidate BSMs.

        Delegates to ``grounding.resolve_spatial_description`` with all
        context-injected dependencies (gazetteer / KG / constraint index).
        """
        from .grounding import resolve_spatial_description

        if not desc or self.workspace is None:
            from .grounding import ResolvedSpatialDescription

            return ResolvedSpatialDescription(
                evidence_text=desc,
                unresolved_reason="empty desc or bundle",
            )
        return resolve_spatial_description(
            desc,
            self.workspace,
            kg=self.kg,
            gazetteer=self.gazetteer,
            constraint_index=self.constraint_index,
            evidence_index=self.evidence_index,
        )

    # ── 2. Closed-set spec (PARSE -> GROUND boundary) ──────────────

    def resolve_spec(
        self,
        spec: Any,
        mention_enhancements: Optional[Dict[str, List[str]]] = None,
    ) -> "ResolvedSpatialRef":
        """Resolve a closed-set SpatialReferenceSpec to candidate BSMs.

        Runs KG-side candidate resolution, then filters to bundle parcels and
        applies a directional bbox refinement when the spec carries a direction
        (replacing the village-center bbox fallback used by EXPLORE grounding).

        ``mention_enhancements`` maps ``target_id -> [mention, ...]`` and is
        produced by the GROUND flash-LLM mention enhancer.  When the primary
        mention cannot bind any BSM, each enhanced mention is resolved through
        the same evidence index and the BSMs are merged - the LLM only supplies
        text, never BSMs/coordinates.
        """
        from app.contracts.spatial.spatial_reference_contracts import (
            CandidateSet,
            ResolvedSpatialRef,
        )

        if getattr(spec, "type", "") == "composed":
            children = [self.resolve_spec(child) for child in (getattr(spec, "children", None) or [])]
            child_sets = [set(child.final_bsms) for child in children]
            op = getattr(spec, "op", None) or "and"
            if not child_sets:
                final = set()
            elif op == "or":
                final = set().union(*child_sets)
            elif op == "not":
                all_bsms = {
                    str(parcel.bsm)
                    for parcel in self.context.current_parcels()
                    if str(getattr(parcel, "bsm", "") or "")
                }
                final = all_bsms - set().union(*child_sets)
            else:
                final = set.intersection(*child_sets)
            bboxes = [child.bbox for child in children if child.bbox]
            return ResolvedSpatialRef(
                final_bsms=sorted(final),
                bbox=bboxes[0] if len(bboxes) == 1 else None,
                confidence=min((child.confidence for child in children), default=0.0),
                provenance={
                    "path": f"composed:{op}",
                    "child_count": len(children),
                    "child_candidate_counts": [len(child.final_bsms) for child in children],
                },
            )

        provenance: Dict[str, Any] = {"path": "evidence:candidates"}
        candidates: CandidateSet = CandidateSet()
        reference = getattr(spec, "reference", None)
        if getattr(reference, "kind", "") == "village":
            village_bsms = [
                str(parcel.bsm)
                for parcel in self.context.current_parcels()
                if str(getattr(parcel, "bsm", "") or "")
            ]
            return ResolvedSpatialRef(
                final_bsms=list(dict.fromkeys(village_bsms)),
                confidence=1.0 if village_bsms else 0.0,
                provenance={"path": "bundle:village_boundary"},
            )
        try:
            if self.evidence_index is not None:
                mention = self._spec_mention(spec)
                if mention == _VILLAGE_ALL_MARKER:
                    all_bsms = [
                        str(parcel.bsm)
                        for parcel in self.context.current_parcels()
                        if str(getattr(parcel, "bsm", "") or "")
                    ]
                    return ResolvedSpatialRef(
                        final_bsms=list(dict.fromkeys(all_bsms)),
                        confidence=1.0 if all_bsms else 0.0,
                        provenance={"path": "bundle:village_all"},
                    )
                if mention:
                    # Combined cells (e.g. 'Y122+X038') are split and
                    # each part resolved against the evidence index; BSMs are
                    # merged so partial matches still bind the spec.
                    evidence_bsms: list[str] = []
                    parts = _split_mentions(mention)
                    for part in parts:
                        part_mention = _normalize_spec_mention(part)
                        if part_mention == _VILLAGE_ALL_MARKER:
                            all_bsms = [
                                str(parcel.bsm)
                                for parcel in self.context.current_parcels()
                                if str(getattr(parcel, "bsm", "") or "")
                            ]
                            return ResolvedSpatialRef(
                                final_bsms=list(dict.fromkeys(all_bsms)),
                                confidence=1.0 if all_bsms else 0.0,
                                provenance={"path": "bundle:village_all"},
                            )
                        if not part_mention:
                            continue
                        evidence_bsms.extend(
                            self.evidence_index.candidate_bsms(part_mention)
                        )
                    if evidence_bsms:
                        candidates = CandidateSet(
                            bsms=list(dict.fromkeys(evidence_bsms))
                        )
                    elif mention:
                        keyword_bsms = _keyword_dlmc_bsms(self.context, mention)
                        if keyword_bsms:
                            candidates = CandidateSet(bsms=keyword_bsms)
                # GROUND flash-LLM mention enhancement: when the primary
                # mention cannot bind, try each enhanced sub-mention through
                # the same evidence index.  The LLM only supplied text.
                if (
                    not candidates.bsms
                    and not candidates.ref_bsms
                    and mention_enhancements
                ):
                    enhanced = (
                        mention_enhancements.get(getattr(spec, "target_id", ""))
                        or []
                    )
                    enhanced_bsms: list[str] = []
                    for sub in enhanced:
                        sub_mention = _normalize_spec_mention(str(sub))
                        if not sub_mention:
                            continue
                        enhanced_bsms.extend(
                            self.evidence_index.candidate_bsms(sub_mention)
                            if self.evidence_index is not None
                            else []
                        )
                    if enhanced_bsms:
                        candidates = CandidateSet(
                            bsms=list(dict.fromkeys(enhanced_bsms))
                        )
                        provenance["path"] += "+flash_mention"
                        provenance["enhanced_mentions"] = list(enhanced)
            if not candidates.bsms and not candidates.ref_bsms:
                port = getattr(self.context.ports, "spatial_query", None)
                if port is not None:
                    run_id = getattr(self.context, "session_id", "") or ""
                    result = port.resolve_candidates(run_id, spec)
                    if result is not None:
                        candidates = result
        except Exception as e:
            logger.warning("[SpatialResolver] resolve_candidates failed: %s", e)
            provenance["error"] = str(e)

        bsms = list(dict.fromkeys([*candidates.bsms, *candidates.ref_bsms]))
        final_bsms = self._filter_to_bundle(bsms)
        provenance["kg_count"] = len(bsms)
        provenance["bundle_count"] = len(final_bsms)

        # KG relation materialization does not always contain a nearby edge
        # from a named natural village to its parcels. When PARSE gives an
        # explicit village label, use the session gazetteer as the same
        # coarse-reference fallback; this still resolves only existing BSMs
        # from the uploaded bundle and never fabricates geometry.
        if not final_bsms and self.gazetteer is not None:
            try:
                filt = getattr(spec.reference, "filter", None) or {}
                label = str(filt.get("label_contains") or "")
                token = label
                for suffix in ("自然村", "村", "组"):
                    token = token.rstrip(suffix)
                location_facts = list(getattr(self.context, "location_facts", []) or [])
                fact_match = next(
                    (
                        fact
                        for fact in location_facts
                        if str(getattr(fact, "normalized_name", "")) in {label, f"{token}村"}
                    ),
                    None,
                )
                if fact_match is not None:
                    provenance["path"] += "+l1_location_fact"
                gazetteer_bsms = _resolve_gazetteer_bsms(token, self.gazetteer)
                final_bsms = self._filter_to_bundle(gazetteer_bsms)
                if final_bsms:
                    provenance["path"] += "+gazetteer:village"
                    provenance["gazetteer_count"] = len(final_bsms)
            except Exception as exc:
                logger.debug("[SpatialResolver] gazetteer fallback failed: %s", exc)

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

            parcels = self.context.current_parcels()
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
        for p in self.context.current_parcels():
            bsm = str(p.bsm or "").strip()
            if bsm:
                by_bsm[bsm] = True
        return [b for b in bsms if b in by_bsm]

    def _spec_mention(self, spec: Any) -> str:
        ref = getattr(spec, "reference", None)
        if ref is None:
            return ""
        filt = getattr(ref, "filter", None) or {}
        label = str(filt.get("label_contains") or "")
        if label:
            return _normalize_spec_mention(label)
        name = str(getattr(ref, "name", "") or "")
        return _normalize_spec_mention(name) if name else ""

    def _directional_bbox(self, direction: str) -> Optional[tuple]:
        """Directional bbox around the bundle's village center."""
        from .grounding import (
            _village_center,
            resolve_directional_bbox,
        )

        parcels = self.context.current_parcels()
        center = _village_center(parcels) if parcels else None
        if center is None:
            return None
        return resolve_directional_bbox(center, direction)

    # ── 3. Intent anchors (PARSE location hints) ───────────────────

    def resolve_anchors(
        self,
        intent: Any,
        village_cluster_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> int:
        """Fill intent target candidate_bsms / anchors from gazetteer + KG anchors."""
        return resolve_intent_anchors(
            intent,
            gazetteer=self.gazetteer,
            village_anchors=self.context.village_anchors,
            village_name=self.context.village_name,
            village_cluster_map=village_cluster_map,
        )

    # ── 4. Deterministic bundle binding (BSM-first) ────────────────

    def bind(self, instructions: Any) -> Dict[str, Any]:
        """Bind instruction candidates to immutable bundle geometry.

        Delegates to ``bundle_binder`` with a gazetteer injected from the
        context so the binder never hardcodes a village name.
        """
        from .bundle_binder import DeterministicBundleBinder

        binder = DeterministicBundleBinder(self.workspace)
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
    village_cluster_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> int:
    """Resolve intent location hints into candidate BSMs / coordinate anchors.

    Mirrors the previous ``parse/agent.py:resolve_spatial_anchors`` contract,
    moved into grounding so GROUND owns all gazetteer/KG anchor resolution.
    Only reads gazetteer + KG anchors; never writes. Returns resolved count.
    ``village_cluster_map`` maps a natural-village name to a bundle-derived
    residential cluster {centroid, bsms, confidence}; it is a deterministic
    fallback when the gazetteer lacks a named village entry.
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
            hit = _village_cluster_for(token, gazetteer, village_cluster_map)
            bsms = (hit.get("bsms") if hit else None) or []
            if bsms and not any(b in (zt.candidate_bsms or []) for b in bsms):
                zt.candidate_bsms.extend(bsms)
                resolved += 1

    for ft in (getattr(intent, "facilities", None) or []):
        location = (getattr(ft, "location_hint", "") or getattr(ft, "anchor_village", "")) or ""
        for token in _extract_location_tokens(location):
            hit = _village_cluster_for(token, gazetteer, village_cluster_map)
            bsms = (hit.get("bsms") if hit else None) or []
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

    for rt in (getattr(intent, "road_targets", None) or []):
        location = (
            getattr(rt, "location_hint", "")
            or (getattr(getattr(rt, "semantic", None), "spatial_hint", "") or "")
        )
        connects = list(getattr(rt, "connects", None) or [])
        text = " ".join([str(location or ""), " ".join(connects)])
        anchors: List[tuple] = []
        seen_tokens: set = set()
        for token in _extract_location_tokens(text):
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            if _direction_from_connects(token) is not None:
                continue
            hit = _village_cluster_for(token, gazetteer, village_cluster_map)
            if hit is None:
                continue
            bsms = list(hit.get("bsms") or [])
            for b in bsms:
                if str(b) not in (rt.candidate_bsms or []):
                    rt.candidate_bsms.append(str(b))
                    resolved += 1
            centroid = hit.get("centroid")
            if centroid and len(anchors) < 2:
                anchors.append((float(centroid[0]), float(centroid[1])))
        # Raw connect values may be numbered roads (122乡道) or natural
        # villages that token stripping removed; try them verbatim too.
        for conn in connects:
            key = str(conn or "").strip()
            if not key or key in seen_tokens:
                continue
            seen_tokens.add(key)
            hit = _village_cluster_for(key, gazetteer, village_cluster_map)
            if hit is None:
                continue
            for b in (hit.get("bsms") or []):
                if str(b) not in (rt.candidate_bsms or []):
                    rt.candidate_bsms.append(str(b))
                    resolved += 1
            centroid = hit.get("centroid")
            if centroid and len(anchors) < 2:
                anchors.append((float(centroid[0]), float(centroid[1])))
        center = _first_village_center(kg_anchors)
        if center is not None:
            for conn in connects:
                direction = _direction_from_connects(str(conn))
                if not direction:
                    continue
                from .grounding import resolve_directional_bbox

                bbox = resolve_directional_bbox(center, direction, radius_m=800)
                if bbox:
                    lon0, lat0, lon1, lat1 = bbox
                    anchors.append(((lon0 + lon1) / 2.0, (lat0 + lat1) / 2.0))
        if anchors and getattr(rt, "start_anchor", None) is None:
            rt.start_anchor = anchors[0]
            resolved += 1
        if len(anchors) > 1 and getattr(rt, "end_anchor", None) is None:
            rt.end_anchor = anchors[1]
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
    Migrated from the legacy select parse agent's resolve_spatial_anchors (Wave M2).
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
