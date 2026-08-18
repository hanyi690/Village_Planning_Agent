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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


class _CandidateChoice(BaseModel):
    """Closed-set grounding choice; the provider never returns free text."""

    candidate_index: int = Field(ge=0)

# ── Location-token helpers (moved from parse/agent.py to keep GROUND
#    inside grounding; parse/agent.py now delegates to this module). ──

_LOCATION_SEP_RE = re.compile(r"[、，,；;/\s]+|至|和|与")
_LOCATION_STRIP = ("自然村", "村", "组", "段", "沿", "线", "附近", "周边", "区域", "一带")


def _bbox_radius_m(bbox) -> float:
    """Approximate the half-diagonal radius of a (lon0,lat0,lon1,lat1) bbox."""
    try:
        lon0, lat0, lon1, lat1 = (float(value) for value in bbox[:4])
    except (TypeError, ValueError, IndexError):
        return 0.0
    mid_lat = (lat0 + lat1) / 2.0
    from app.spatial.model.crs_engine import meters_to_degrees_lat, meters_to_degrees_lon

    dlon = abs(lon1 - lon0)
    dlat = abs(lat1 - lat0)
    if dlon == 0 and dlat == 0:
        return 0.0
    x_m = dlon / meters_to_degrees_lon(1.0, mid_lat) if dlon else 0.0
    y_m = dlat / meters_to_degrees_lat(1.0) if dlat else 0.0
    return round(((x_m ** 2 + y_m ** 2) ** 0.5) / 2.0, 1)


def _authoritative_geometry_wkt(value: Any) -> str:
    """Accept only a valid source geometry returned by a spatial adapter.

    ``CandidateSet.ref_geometry_wkt`` is the escape hatch for exact point/line
    evidence.  It must never be confused with a bbox or a geometry invented
    from parcel centroids, so malformed/empty/unsupported values are dropped
    before they reach GROUND.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        from shapely import wkt as shapely_wkt

        geometry = shapely_wkt.loads(text)
    except Exception:
        return ""
    if geometry.is_empty or not geometry.is_valid:
        return ""
    if geometry.geom_type not in {
        "Point", "MultiPoint", "LineString", "MultiLineString",
        "Polygon", "MultiPolygon",
    }:
        return ""
    return geometry.wkt


def _authoritative_geometry_refs(values: Any, singular: Any = None) -> list[Any]:
    """Normalize source-backed geometry records without synthesizing geometry.

    Spatial adapters may still return the legacy singular WKT.  New adapters
    can return independent ``GeometryRef`` records; each record is validated
    separately and retained with its source lineage.  Invalid records are
    discarded rather than repaired or merged.
    """
    from app.contracts.spatial.spatial_reference_contracts import GeometryRef

    raw_values = list(values or [])
    if not raw_values and singular:
        raw_values = [singular]
    refs: list[GeometryRef] = []
    for raw in raw_values:
        if isinstance(raw, GeometryRef):
            data = raw.model_dump()
        elif isinstance(raw, dict):
            data = dict(raw)
        else:
            data = {"wkt": str(raw or "")}
        wkt = _authoritative_geometry_wkt(data.get("wkt"))
        if not wkt:
            continue
        data["wkt"] = wkt
        try:
            refs.append(GeometryRef.model_validate(data))
        except Exception:
            # Keep the boundary fail-closed when an adapter sends malformed
            # metadata, even if its WKT itself parses.
            continue
    return refs


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
            "entity_ref": str(getattr(entry, "entity_uri", "") or ""),
            "provenance_refs": [f"gazetteer:{getattr(entry, 'source', 'unknown')}"],
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
                "entity_ref": str(item.get("entity_ref") or ""),
                "provenance_refs": list(item.get("provenance_refs") or []),
                "source_artifact_ref": str(item.get("source_artifact_ref") or ""),
                "source_feature_id": str(item.get("source_feature_id") or ""),
                "coordinate_crs": str(item.get("coordinate_crs") or "EPSG:4326"),
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
    if (
        token in {"全村域", "全村", "村域"}
        or token.startswith("全村")
        or re.fullmatch(r"(?:全村)?\d+个自然村", token)
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


class SpatialResolver:
    """One resolver bound to one ``PlanningContext``."""

    def __init__(self, context: Any):
        if not (
            hasattr(context, "workspace")
            and hasattr(context, "kg")
        ):
            raise TypeError("SpatialResolver requires a PlanningContext")
        self.context = context
        from app.spatial.grounding.call_budget import new_ground_llm_budget

        self._ground_llm_budget = new_ground_llm_budget()

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
            min_child = min(
                children,
                key=lambda child: child.confidence,
                default=None,
            )
            return ResolvedSpatialRef(
                final_bsms=sorted(final),
                bbox=bboxes[0] if len(bboxes) == 1 else None,
                confidence=min((child.confidence for child in children), default=0.0),
                uncertainty_radius_m=(
                    getattr(min_child, "uncertainty_radius_m", 0.0) or 0.0
                    if min_child is not None
                    else 0.0
                ),
                uncertainty_reason=(
                    str(getattr(min_child, "uncertainty_reason", "") or "")
                    if min_child is not None
                    else ""
                ),
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
            raw_label = (
                str(getattr(reference, "name", "") or "")
                or str((getattr(reference, "filter", None) or {}).get("label_contains") or "")
            )
            cluster = self._resolve_village_cluster(raw_label)
            if cluster is not None:
                cluster_bsms, village_token = cluster
                return ResolvedSpatialRef(
                    final_bsms=cluster_bsms,
                    bbox=None,
                    confidence=0.35,
                    uncertainty_radius_m=250.0,
                    uncertainty_reason="village_coarse",
                    provenance={
                        "path": "village_cluster:gazetteer",
                        "village": village_token,
                        "bsm_count": len(cluster_bsms),
                    },
                )
            return ResolvedSpatialRef(
                final_bsms=[],
                confidence=0.0,
                uncertainty_radius_m=0.0,
                uncertainty_reason="unresolved",
                provenance={
                    "path": "unresolved:village_reference",
                    "reason": "village boundary cannot become a parcel candidate pool",
                },
            )
        try:
            if self.evidence_index is not None:
                mention = self._spec_mention(spec)
                if mention == _VILLAGE_ALL_MARKER:
                    raw_label = (
                        str(getattr(reference, "name", "") or "")
                        or str((getattr(reference, "filter", None) or {}).get("label_contains") or "")
                    )
                    cluster = self._resolve_village_cluster(raw_label)
                    if cluster is not None:
                        cluster_bsms, village_token = cluster
                        return ResolvedSpatialRef(
                            final_bsms=cluster_bsms,
                            bbox=None,
                            confidence=0.35,
                            uncertainty_radius_m=250.0,
                            uncertainty_reason="village_coarse",
                            provenance={
                                "path": "village_cluster:gazetteer",
                                "village": village_token,
                                "bsm_count": len(cluster_bsms),
                            },
                        )
                    return ResolvedSpatialRef(
                        final_bsms=[],
                        confidence=0.0,
                        uncertainty_radius_m=0.0,
                        uncertainty_reason="unresolved",
                        provenance={
                            "path": "unresolved:village_all",
                            "reason": "whole-village text is not target-bound parcel evidence",
                        },
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
                            # A whole-village part inside a combined mention is
                            # not itself parcel evidence; keep the other parts.
                            continue
                        if not part_mention:
                            continue
                        evidence_bsms.extend(
                            self.evidence_index.candidate_bsms(part_mention)
                        )
                    if evidence_bsms:
                        candidates = CandidateSet(
                            bsms=list(dict.fromkeys(evidence_bsms))
                        )
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
        reference_geometries = _authoritative_geometry_refs(
            getattr(candidates, "ref_geometries", None),
            getattr(candidates, "ref_geometry_wkt", None),
        )
        reference_geometry_wkt = (
            reference_geometries[0].wkt
            if len(reference_geometries) == 1
            else None
        )
        if reference_geometries:
            provenance["path"] += "+authoritative_geometry"
            provenance["source_geometry_count"] = len(reference_geometries)
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

        if final_bsms and not bbox and not reference_geometries:
            # 设计 §4.3：证据索引判 ambiguous（多候选接近/弱证据）的引用即使
            # 已有候选 BSMs，也进入有界 LLM 判别，避免直接取 top 造成误绑。
            try:
                ambiguous = self._llm_resolve_ambiguous(
                    spec,
                    self._spec_mention(spec),
                    mention_enhancements,
                )
                if ambiguous is not None:
                    return ambiguous
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SpatialResolver] ambiguous llm resolution failed: %s", exc)

        if not final_bsms and not bbox and not reference_geometries:
            # 不允许留下不可解析的引用（目标 §"不能留又不能解析"）：在证据索引
            # 候选内做有界 LLM best-effort 判别；几何/BSM 仍来自 bundle。失败
            # 才保持 unresolved（绝不伪造几何）。
            fallback = self._llm_reason_fallback(
                spec,
                self._spec_mention(spec),
                mention_enhancements,
            )
            if fallback is not None:
                return fallback
            # 最后一步：会话村地块簇粗兜底。只有模糊村/区域提示的目标不应被
            # 直接丢弃：把会话村聚落地块集合作为有界候选池（带不确定性），由
            # 适宜性/LLM 去判别。几何/BSM 仍只来自 bundle gazetteer。
            cluster = self._resolve_village_cluster("")
            if cluster is not None:
                cluster_bsms, village_token = cluster
                return ResolvedSpatialRef(
                    final_bsms=cluster_bsms,
                    bbox=None,
                    confidence=0.3,
                    uncertainty_radius_m=250.0,
                    uncertainty_reason="village_coarse_fallback",
                    provenance={
                        "path": "village_cluster:gazetteer:coarse_fallback",
                        "village": village_token,
                        "bsm_count": len(cluster_bsms),
                        "prior": provenance,
                    },
                )
            return ResolvedSpatialRef(
                final_bsms=[],
                bbox=None,
                confidence=0.0,
                uncertainty_radius_m=0.0,
                uncertainty_reason="unresolved",
                provenance={"...": provenance},
            )

        confidence = 0.9 if reference_geometries else (0.7 if final_bsms else 0.3)
        if not final_bsms and bbox:
            # Directional bbox with no KG match: fall back to geometry query.
            from .grounding import query_parcels_in_bbox

            parcels = self.context.current_parcels()
            final_bsms = query_parcels_in_bbox(parcels, bbox)
            provenance["path"] += "+geometry:bbox"
            confidence = 0.8

        uncertainty_reason = ""
        uncertainty_radius_m = 0.0
        if not final_bsms:
            uncertainty_reason = "unresolved"
        else:
            path = str(provenance.get("path", "") or "")
            if "+geometry:bbox" in path or "+gazetteer:village" in path or "+flash_mention" in path:
                uncertainty_reason = "coarse_reference"
                uncertainty_radius_m = _bbox_radius_m(bbox) if bbox else 250.0

        return ResolvedSpatialRef(
            final_bsms=final_bsms,
            bbox=bbox,
            reference_geometry_wkt=reference_geometry_wkt or None,
            reference_geometries=reference_geometries,
            confidence=confidence,
            uncertainty_radius_m=uncertainty_radius_m,
            uncertainty_reason=uncertainty_reason,
            provenance=provenance,
        )

    def _llm_reason_fallback(
        self,
        spec: Any,
        mention: str,
        mention_enhancements: Optional[Dict[str, List[str]]] = None,
        extra_candidates: Optional[List[Any]] = None,
    ) -> Optional["ResolvedSpatialRef"]:
        """有界 LLM best-effort（设计 §4.3）：在 Recall 候选内判别，不新增 BSM/几何。

        LLM 只在证据索引召回的候选内选最优；候选行携带几何与 KG 拓扑关系，
        让判别具备拓扑上下文（对齐 arXiv 2505.17136：LLM 拓扑推理需要几何/
        place-type 上下文）。失败或没有可用候选返回 None，保持 unresolved——
        绝不降级为第一个候选，也绝不伪造几何/BSM。
        """
        ordered = extra_candidates or self._collect_llm_candidates(
            spec, mention, mention_enhancements
        )
        if not ordered:
            return None
        picked = self._llm_pick_candidate(mention, self._spec_hints(spec), ordered)
        if picked is None:
            # 设计 §4.3：失败/超时保持 ambiguous，不得降级为第一个候选。
            return None
        bsms = self._filter_to_bundle(list(getattr(picked, "source_bsms", None) or []))
        if not bsms:
            return None
        from app.contracts.spatial.spatial_reference_contracts import ResolvedSpatialRef

        return ResolvedSpatialRef(
            final_bsms=bsms,
            bbox=None,
            confidence=0.35,
            uncertainty_radius_m=250.0,
            uncertainty_reason="llm_best_effort",
            provenance={
                "path": "evidence:candidates+llm_best_effort",
                "mention": mention,
                "picked": str(getattr(picked, "canonical_name", "") or ""),
                "candidate_count": len(ordered),
            },
        )

    def _collect_llm_candidates(
        self,
        spec: Any,
        mention: str,
        mention_enhancements: Optional[Dict[str, List[str]]] = None,
    ) -> List[Any]:
        """Deduped Top-8 evidence-index candidates for LLM discrimination."""
        candidates: List[Any] = []
        if self.evidence_index is None:
            return []
        sub_mentions = [mention]
        for sub in (mention_enhancements or {}).get(getattr(spec, "target_id", ""), []) or []:
            sub_mentions.append(_normalize_spec_mention(str(sub)))
        hints = self._spec_hints(spec)
        for sub in sub_mentions:
            if not sub:
                continue
            try:
                result = self.evidence_index.resolve_mention(sub, hints=hints)
                candidates.extend(result.candidates)
            except Exception:  # noqa: BLE001
                continue
        by_ref: Dict[str, Any] = {}
        for c in candidates:
            key = str(c.entity_ref or c.canonical_name or "")
            if not key:
                continue
            if key not in by_ref or c.score > by_ref[key].score:
                by_ref[key] = c
        return sorted(by_ref.values(), key=lambda c: -c.score)[:8]

    def _spec_hints(self, spec: Any) -> str:
        """提取 spec 的位置/关系提示文本，作为 LLM 判别的拓扑上下文。"""
        parts: List[str] = []
        ref = getattr(spec, "reference", None)
        if ref is not None:
            filt = getattr(ref, "filter", None) or {}
            for key in ("label_contains", "name", "near", "relation"):
                value = filt.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        direction = getattr(spec, "direction", None)
        if direction:
            parts.append(str(direction))
        topo = getattr(spec, "topo", None)
        if topo:
            parts.append(str(topo))
        semantic = getattr(spec, "semantic", None)
        raw = ""
        try:
            raw = getattr(semantic, "raw_text", "") or ""
        except Exception:  # noqa: BLE001
            raw = ""
        if isinstance(raw, str) and raw.strip():
            parts.append(raw.strip()[:160])
        return "、".join(part for part in dict.fromkeys(parts) if part)

    def _llm_pick_candidate(
        self,
        mention: str,
        hints: str,
        ordered: List[Any],
    ) -> Optional[Any]:
        """有界判别：LLM 在候选内选编号；失败/超时返回 None（保持 ambiguous）。"""
        import os

        if str(os.getenv("DISABLE_GROUND_LLM", "")).strip().lower() in {
            "1", "true", "yes", "on",
        } or str(os.getenv("DISABLE_GROUND_REPORT_LLM", "")).strip().lower() in {
            "1", "true", "yes", "on",
        }:
            return None
        from app.spatial.grounding.call_budget import (
            ground_llm_sync_semaphore,
            reserve_ground_llm_call,
        )

        call_timeout = reserve_ground_llm_call(self._ground_llm_budget)
        if call_timeout is None:
            logger.info(
                "[SpatialResolver] grounding LLM budget exhausted; keeping deterministic resolution for %s",
                mention,
            )
            return None
        try:
            from app.infrastructure.llm.factory import create_flash_llm

            llm = create_flash_llm(max_tokens=200, temperature=0.1)
            lines = chr(10).join(
                self._candidate_line(i, c) for i, c in enumerate(ordered, 1)
            )
            hint_clause = f"《{hints}》" if hints else ""
            prompt = (
                f"空间引用「{mention}」{hint_clause}。"
                "以下是从 KG/索引召回的候选实体（含几何与拓扑关系），"
                "请选择与引用最匹配的一个，只输出编号；都不合适输出 0：\n" + lines
            )

            # The production adapter exposes structured output, while v1
            # test/dry-run adapters may only expose ``invoke``.  Keep the
            # closed candidate-index contract in both paths; the fallback
            # parses an index only and never accepts a new BSM or geometry.
            structured_factory = getattr(llm, "with_structured_output", None)
            structured = (
                structured_factory(_CandidateChoice, method="function_calling")
                if callable(structured_factory)
                else None
            )

            # This resolver is intentionally synchronous for compatibility
            # with the spatial aggregate API.  Bound the provider call in a
            # short-lived worker and keep the shared grounding gate around it;
            # the async L1 fan-out is implemented in ground_l1_anchors.
            executor = ThreadPoolExecutor(max_workers=1)
            sync_gate = ground_llm_sync_semaphore(self._ground_llm_budget)

            def _invoke_with_bounded_queue():
                # The sync resolver is called by compatibility paths, so the
                # semaphore wait must happen in the timed worker too.  Waiting
                # in the caller thread used to serialize ambiguous references
                # indefinitely before the provider timeout even started.
                acquired = sync_gate.acquire(timeout=max(0.001, call_timeout))
                if not acquired:
                    raise TimeoutError("grounding LLM semaphore queue timeout")
                try:
                    if structured is not None:
                        return structured.invoke(prompt)
                    invoke = getattr(llm, "invoke", None)
                    if not callable(invoke):
                        raise TypeError("grounding LLM adapter has no invoke method")
                    return invoke(prompt)
                finally:
                    sync_gate.release()

            try:
                response = executor.submit(_invoke_with_bounded_queue).result(
                    timeout=call_timeout
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            choice = response
            if not isinstance(choice, _CandidateChoice):
                content = getattr(choice, "content", choice)
                if isinstance(content, (list, tuple)):
                    content = "".join(str(item) for item in content)
                if isinstance(content, dict):
                    choice = _CandidateChoice.model_validate(content)
                else:
                    match = re.search(r"(?<!\d)(\d+)(?!\d)", str(content or ""))
                    if match:
                        choice = _CandidateChoice(candidate_index=int(match.group(1)))
            if choice is None:
                # Provider adapters may return an empty response when the
                # optional grounding model is unavailable.  Keep the
                # deterministic evidence result ambiguous instead of turning
                # a normal provider miss into a schema-validation warning.
                return None
            if not isinstance(choice, _CandidateChoice):
                choice = _CandidateChoice.model_validate(choice)
            index = choice.candidate_index - 1
            if 0 <= index < len(ordered):
                return ordered[index]
        except FutureTimeoutError:
            logger.warning(
                "[SpatialResolver] llm pick timed out after %.1fs: %s",
                call_timeout,
                mention,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SpatialResolver] llm pick failed: %s", exc)
        return None

    def _candidate_line(self, index: int, c: Any) -> str:
        """一行候选：名称/类型/BSM/几何/拓扑关系/得分。"""
        rels: List[str] = []
        for ref in list(getattr(c, "relation_refs", None) or [])[:5]:
            text = str(ref)
            rels.append(text.rsplit("#", 1)[-1].rsplit("/", 1)[-1])
        geometry = str(getattr(c, "geometry_ref", "") or "")[:160]
        return (
            f"{index}. {c.canonical_name} 类型={c.entity_type} "
            f"BSM={','.join(c.source_bsms[:4]) or '无'} "
            f"几何={geometry or '无'} 拓扑={','.join(rels) or '无'} 得分={c.score:.2f}"
        )

    def _llm_resolve_ambiguous(
        self,
        spec: Any,
        mention: str,
        mention_enhancements: Optional[Dict[str, List[str]]] = None,
    ) -> Optional["ResolvedSpatialRef"]:
        """歧义引用有界判别（设计 §4.3）：证据索引判 ambiguous 时在候选内选。

        成功返回 LLM 判别的落位；失败保持原确定性结果（已有 BSMs 不丢）。
        """
        if self.evidence_index is None or not mention:
            return None
        try:
            result = self.evidence_index.resolve_mention(
                mention, hints=self._spec_hints(spec)
            )
        except Exception:  # noqa: BLE001
            return None
        if str(getattr(result, "status", "") or "") != "ambiguous":
            return None
        candidates = list(getattr(result, "candidates", None) or [])
        if not candidates:
            return None
        picked = self._llm_pick_candidate(
            mention, self._spec_hints(spec), candidates
        )
        if picked is None:
            return None
        bsms = self._filter_to_bundle(list(getattr(picked, "source_bsms", None) or []))
        if not bsms:
            return None
        from app.contracts.spatial.spatial_reference_contracts import ResolvedSpatialRef

        return ResolvedSpatialRef(
            final_bsms=bsms,
            bbox=None,
            confidence=0.5,
            uncertainty_radius_m=250.0,
            uncertainty_reason="llm_ambiguous_resolution",
            provenance={
                "path": "evidence:candidates+llm_ambiguous",
                "mention": mention,
                "picked": str(getattr(picked, "canonical_name", "") or ""),
                "candidate_count": len(candidates),
            },
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


    def _resolve_village_cluster(self, label: str):
        """Village-level reference -> village parcel cluster via the gazetteer.

        Design 4.3 / spatial reasoning: a target located only by its village
        (kind==village, whole-village mention, or sfWithin the session village)
        must not be dropped.  Resolve the named village to its parcel cluster
        from the uploaded-bundle gazetteer as a coarse candidate pool; the
        geometry/BSM are always real bundle parcels, never fabricated.  Falls
        back to the session village when the spec carries no label.
        """
        if self.gazetteer is None:
            return None

        def _candidates_for(token: str):
            if not token:
                return None
            bsms = _resolve_gazetteer_bsms(token, self.gazetteer)
            if not bsms:
                return None
            final = self._filter_to_bundle(bsms)
            if not final:
                return None
            return final, token

        token = str(label or "").strip()
        for suffix in ("\u81ea\u7136\u6751", "\u6751", "\u7ec4"):
            token = token.rstrip(suffix)
        result = _candidates_for(token)
        if result is not None:
            return result
        # The label is often a whole-village phrase (e.g. "全村40处隐患点")
        # that the gazetteer cannot name-match.  Fall back to the session
        # village parcel cluster so the target still gets a bounded pool.
        village = str(getattr(self.context, "village_name", "") or "").strip()
        for suffix in ("\u81ea\u7136\u6751", "\u6751", "\u7ec4"):
            village = village.rstrip(suffix)
        return _candidates_for(village)

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
        snapshot = getattr(getattr(self.context, "workspace", None), "snapshot", None)
        return resolve_intent_anchors(
            intent,
            gazetteer=self.gazetteer,
            village_anchors=self.context.village_anchors,
            village_name=self.context.village_name,
            village_cluster_map=village_cluster_map,
            bundle_snapshot_ref=(
                f"bundle-snapshot:{snapshot.snapshot_id}" if snapshot else ""
            ),
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
    bundle_snapshot_ref: str = "",
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

    for rt in [
        *(getattr(intent, "road_targets", None) or []),
        *(getattr(intent, "linear_targets", None) or []),
    ]:
        location = (
            getattr(rt, "location_hint", "")
            or (getattr(getattr(rt, "semantic", None), "spatial_hint", "") or "")
        )
        connects = list(getattr(rt, "connects", None) or [])
        text = " ".join([str(location or ""), " ".join(connects)])
        anchors: List[tuple] = []
        endpoint_hits: List[Dict[str, Any] | None] = []
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
                endpoint_hits.append(hit)
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
                endpoint_hits.append(hit)
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
                    endpoint_hits.append(None)
        if anchors and getattr(rt, "start_anchor", None) is None:
            rt.start_anchor = anchors[0]
            resolved += 1
        if len(anchors) > 1 and getattr(rt, "end_anchor", None) is None:
            rt.end_anchor = anchors[1]
            resolved += 1
        if len(anchors) >= 2:
            from app.contracts.domain.road_planning import RoadEndpointEvidence

            for role, field_name, coordinate, hit in (
                ("start", "start_endpoint", anchors[0], endpoint_hits[0]),
                ("end", "end_endpoint", anchors[1], endpoint_hits[1]),
            ):
                if getattr(rt, field_name, None) is not None or hit is None:
                    continue
                bsms = list(hit.get("bsms") or [])
                source_ref = str(hit.get("source_artifact_ref") or bundle_snapshot_ref)
                feature_id = str(hit.get("source_feature_id") or (bsms[0] if bsms else ""))
                evidence_refs = list(hit.get("provenance_refs") or [])
                evidence_refs.extend(f"bundle-parcel:{bsm}" for bsm in bsms)
                entity_ref = str(hit.get("entity_ref") or "")
                if not source_ref or not (feature_id or entity_ref) or not evidence_refs:
                    continue
                setattr(
                    rt,
                    field_name,
                    RoadEndpointEvidence(
                        role=role,
                        resolution_status="resolved",
                        entity_ref=entity_ref or None,
                        coordinate=coordinate,
                        coordinate_crs=str(hit.get("coordinate_crs") or "EPSG:4326"),
                        source_artifact_ref=source_ref,
                        source_feature_id=feature_id,
                        evidence_refs=list(dict.fromkeys(evidence_refs)),
                    ),
                )
                resolved += 1

    for prj in (getattr(intent, "site_area_targets", None) or []):
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

    for rt in [
        *(getattr(intent, "road_targets", None) or []),
        *(getattr(intent, "linear_targets", None) or []),
    ]:
        if not kg_anchors:
            continue
        text = " ".join([
            str(getattr(rt, "road_level", "") or ""),
            str(getattr(rt, "connects", "") or ""),
            str(getattr(getattr(rt, "semantic", None), "natural_language_description", "") or ""),
        ])
        candidates = [a for a in kg_anchors if a["name"] and a["name"] in text]
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
