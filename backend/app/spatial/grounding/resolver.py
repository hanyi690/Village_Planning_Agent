"""SpatialResolver - single entry point for spatial reference resolution.

Consolidates the three competing spatial-semantics implementations into one
place, all reading from a ``PlanningContext``:

    resolve_text      EXPLORE / GROUND free-text description -> candidates
    resolve_spec      PARSE closed-set SpatialReferenceSpec -> candidates
    resolve_anchors   intent location hints -> candidate BSMs / anchors
    bind              deterministic bundle binding (BSM-first)

    Every method takes its facts from ``PlanningContext`` (workspace / gazetteer /
KG / constraint index / EvidenceGraph) instead of each caller building its own
gazetteer/KG/center fallback. Callers that only have a village name + anchors
can use the module-level ``resolve_intent_anchors`` helper.

Dependency rule: this module must not import ``app.agent``
or ``app.api``.
"""

from __future__ import annotations

import os
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

_LOCATION_SEPARATORS = frozenset("、，,；;/ \t\r\n至和与")
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

    ``CandidateSet.ref_geometries`` carries exact point/line evidence.  It
    must never be confused with a bbox or a geometry invented from parcel
    centroids, so malformed/empty/unsupported values are dropped before they
    reach GROUND.
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


def _authoritative_geometry_refs(values: Any) -> list[Any]:
    """Normalize source-backed geometry records without synthesizing geometry.

    Adapters return independent ``GeometryRef`` records; each record is
    validated separately and retained with its source lineage. Invalid
    records are discarded rather than repaired or merged.
    """
    from app.contracts.spatial.spatial_reference_contracts import GeometryRef

    raw_values = list(values or [])
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
    for part in _split_by_separators(location, _LOCATION_SEPARATORS):
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


def _split_by_separators(value: str, separators: frozenset[str]) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for char in str(value or ""):
        if char in separators:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _split_mentions(label: str) -> list[str]:
    """Split a combined location cell into discrete mentions."""
    return _split_by_separators(label, frozenset(_MENTION_SEPARATORS))


def _is_village_count_token(token: str) -> bool:
    value = str(token or "")
    if value.startswith("全村"):
        value = value[2:]
    suffix = "个自然村"
    return value.endswith(suffix) and value[: -len(suffix)].isdigit()


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
        or _is_village_count_token(token)
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

    def __init__(
        self,
        context: Any,
        *,
        ground_llm_budget: Optional[Dict[str, Any]] = None,
        budget_scope: str = "ground",
    ):
        if not (
            hasattr(context, "workspace")
            and hasattr(context, "kg")
        ):
            raise TypeError("SpatialResolver requires a PlanningContext")
        self.context = context
        if ground_llm_budget is None:
            from app.spatial.grounding.call_budget import get_ground_llm_budget

            ground_llm_budget = get_ground_llm_budget(
                context,
                scope_key=f"{budget_scope}:{getattr(context, 'session_id', '')}",
            )
        self._ground_llm_budget = ground_llm_budget

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
    def evidence_graph(self):
        return self.context.evidence_graph

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
            evidence_graph=self.evidence_graph,
        )

    # ── 2. Closed-set spec (PARSE -> GROUND boundary) ──────────────

    def resolve_spec(
        self,
        spec: Any,
        mention_enhancements: Optional[Dict[str, List[str]]] = None,
        evidence_packet: Any = None,
    ) -> "ResolvedSpatialRef":
        """Resolve a closed-set SpatialReferenceSpec to candidate BSMs.

        Runs KG-side candidate resolution, then filters to bundle parcels and
        applies a directional bbox refinement when the spec carries a direction
        (replacing the village-center bbox fallback used by EXPLORE grounding).

        ``mention_enhancements`` maps ``target_id -> [mention, ...]`` and is
        produced by the GROUND flash-LLM mention enhancer.  When the primary
        mention cannot bind any BSM, each enhanced mention is resolved through
        the same EvidenceGraph and the BSMs are merged - the LLM only supplies
        text, never BSMs/coordinates.

        ``evidence_packet`` is an optional canonical retrieval result for this
        target.  Its opaque feature refs are resolved back through the current
        bundle before they enter the normal ``CandidateSet`` boundary.  This
        keeps packet-driven GROUND and direct EvidenceGraph resolution on one
        fail-closed path.
        """
        from app.contracts.spatial.spatial_reference_contracts import (
            CandidateSet,
            ResolvedSpatialRef,
        )

        if getattr(spec, "type", "") == "composed":
            packet_lineage = {
                "feature_bsms": [],
                "source_feature_ids": [],
                "entity_refs": [],
                "relation_refs": [],
                "l1_fact_refs": [],
                "l1_snapshot_ref": "",
                "bundle_snapshot_digest": "",
            }
            packet_candidates, packet_selection, packet_meta = (
                self._selected_candidate_set_from_evidence_packet(
                    spec,
                    evidence_packet,
                    packet_lineage,
                )
            )
            if packet_selection == "selection_unresolved":
                return self._unresolved_evidence_packet_ref(
                    packet_meta,
                    path=f"composed:{getattr(spec, 'op', None) or 'and'}+evidence_packet",
                )
            if packet_candidates is not None:
                resolved_packet = self._resolved_from_candidate_set(
                    spec,
                    packet_candidates,
                    packet_lineage,
                    path=f"composed:{getattr(spec, 'op', None) or 'and'}+evidence_packet",
                )
                resolved_packet.provenance.update(packet_meta)
                return resolved_packet
            children = [
                self.resolve_spec(child)
                for child in (getattr(spec, "children", None) or [])
            ]
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
            def merged_list(attribute: str) -> list[str]:
                values: list[str] = []
                for child in children:
                    raw_values = getattr(child, attribute, None)
                    if isinstance(raw_values, (list, tuple, set)):
                        values.extend(str(value) for value in raw_values)
                    elif raw_values:
                        values.append(str(raw_values))
                return list(dict.fromkeys(value for value in values if value.strip()))

            reference_geometries = [
                geometry
                for child in children
                for geometry in (getattr(child, "reference_geometries", None) or [])
            ]
            l1_snapshot_refs = merged_list("l1_snapshot_ref")
            bundle_snapshot_digests = merged_list("bundle_snapshot_digest")
            provenance = {
                "path": f"composed:{op}",
                "child_count": len(children),
                "child_candidate_counts": [len(child.final_bsms) for child in children],
                "feature_bsms": merged_list("feature_bsms"),
                "source_feature_ids": merged_list("source_feature_ids"),
                "entity_refs": merged_list("entity_refs"),
                "relation_refs": merged_list("relation_refs"),
                "l1_fact_refs": merged_list("l1_fact_refs"),
            }
            if l1_snapshot_refs:
                provenance["l1_snapshot_ref"] = l1_snapshot_refs
            if bundle_snapshot_digests:
                provenance["bundle_snapshot_digest"] = bundle_snapshot_digests
            return ResolvedSpatialRef(
                final_bsms=sorted(final),
                bbox=bboxes[0] if len(bboxes) == 1 else None,
                reference_geometry_wkt=(
                    reference_geometries[0].wkt
                    if len(reference_geometries) == 1
                    else None
                ),
                reference_geometries=reference_geometries,
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
                spatial_domain_kind=(
                    "exact_feature"
                    if reference_geometries
                    else (
                        "parcel_extent"
                        if len(final) == 1
                        else ("parcel_set" if final else "unknown")
                    )
                ),
                feature_bsms=merged_list("feature_bsms"),
                source_feature_ids=merged_list("source_feature_ids"),
                entity_refs=merged_list("entity_refs"),
                relation_refs=merged_list("relation_refs"),
                l1_fact_refs=merged_list("l1_fact_refs"),
                l1_snapshot_ref=(l1_snapshot_refs[0] if len(l1_snapshot_refs) == 1 else ""),
                bundle_snapshot_digest=(
                    bundle_snapshot_digests[0]
                    if len(bundle_snapshot_digests) == 1
                    else ""
                ),
                provenance=provenance,
            )

        provenance: Dict[str, Any] = {"path": "evidence:candidates"}
        for attribute in (
            "source_binding_ref",
            "source_collection_key",
            "source_snapshot_ref",
            "source_feature_digest",
        ):
            value = str(getattr(spec, attribute, "") or "").strip()
            if value:
                provenance[attribute] = value
        candidates: CandidateSet = CandidateSet()
        evidence_lineage = {
            "feature_bsms": [],
            "source_feature_ids": [],
            "entity_refs": [],
            "relation_refs": [],
            "l1_fact_refs": [],
            "l1_snapshot_ref": "",
            "bundle_snapshot_digest": "",
        }
        evidence_lineage["l1_fact_refs"].extend(
            str(fact_ref)
            for fact_ref in (getattr(spec, "l1_fact_refs", None) or [])
            if str(fact_ref).strip()
        )
        reference = getattr(spec, "reference", None)
        if getattr(reference, "kind", "") == "bsm":
            return self._resolve_direct_bsm_reference(spec, reference)
        if getattr(reference, "kind", "") == "village":
            raw_label = (
                str(getattr(reference, "name", "") or "")
                or str((getattr(reference, "filter", None) or {}).get("label_contains") or "")
            )
            cluster = self._resolve_village_cluster(
                raw_label,
                allow_session_fallback=not bool(raw_label.strip()),
            )
            if cluster is not None:
                cluster_bsms, village_token = cluster
                return ResolvedSpatialRef(
                    final_bsms=cluster_bsms,
                    bbox=None,
                    spatial_domain_kind="village_scope",
                    confidence=0.35,
                    uncertainty_radius_m=250.0,
                    uncertainty_reason="village_coarse",
                    provenance={
                        "path": "village_cluster:gazetteer",
                        "village": village_token,
                        "bsm_count": len(cluster_bsms),
                    },
                )
            evidence_scope = self._village_scope_from_evidence_packet(
                spec,
                evidence_packet,
            )
            if evidence_scope is not None:
                return evidence_scope
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

        packet_candidates, packet_selection, packet_meta = (
            self._selected_candidate_set_from_evidence_packet(
                spec,
                evidence_packet,
                evidence_lineage,
            )
        )
        if packet_selection == "selection_unresolved":
            return self._unresolved_evidence_packet_ref(
                packet_meta,
                path="evidence:candidates+evidence_packet",
            )
        if packet_candidates is not None:
            candidates = packet_candidates
            provenance["path"] += "+evidence_packet"
            provenance.update(packet_meta)
        # A topological SpatialReferenceSpec describes the target domain as
        # the KG relation result of its reference anchor (for example, parcel
        # candidates intersecting a named road).  Resolve that relation before
        # treating the reference label as an ordinary feature mention; the
        # latter only returns the anchor and its broad bundle associations.
        if packet_candidates is None and getattr(spec, "type", "") == "topological":
            kg_candidates = self._resolve_kg_spatial_spec(spec, evidence_lineage)
            if kg_candidates is not None:
                candidates = kg_candidates
                provenance["path"] += "+kg_topology"
        try:
            if (
                packet_candidates is None
                and not candidates.bsms
                and not candidates.ref_bsms
                and self.evidence_graph is not None
            ):
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
                            spatial_domain_kind="village_scope",
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
                    # each part resolved against EvidenceGraph; BSMs are
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
                        # A named natural village may exist only in report
                        # evidence and not as a standalone KG entity.  The
                        # GROUND stage may have produced an evidence-constrained
                        # mapping from that name to Bundle-derived residential
                        # clusters.  Consume the mapping as parcel references,
                        # never as geometry; Bundle remains the only geometry
                        # authority below in ``_filter_to_bundle``.
                        cluster_map = getattr(
                            self.context, "village_cluster_map", None
                        ) or {}
                        cluster = _village_cluster_for(
                            part_mention,
                            self.gazetteer,
                            cluster_map,
                        )
                        if cluster is not None:
                            cluster_bsms = [
                                str(value).strip()
                                for value in (cluster.get("bsms") or [])
                                if str(value).strip()
                            ]
                            if cluster_bsms:
                                evidence_bsms.extend(cluster_bsms)
                                provenance.setdefault(
                                    "village_cluster_evidence", []
                                ).append(
                                    {
                                        "mention": part_mention,
                                        "source": cluster.get("source", "village_cluster"),
                                        "entity_ref": str(
                                            cluster.get("entity_ref") or ""
                                        ),
                                        "confidence": float(
                                            cluster.get("confidence", 0.0) or 0.0
                                        ),
                                        "provenance_refs": list(
                                            cluster.get("provenance_refs") or []
                                        ),
                                    }
                                )
                        evidence_bsms.extend(
                            self.evidence_graph.candidate_bsms(
                                part_mention,
                                include_ambiguous=True,
                                max_candidates=64,
                                hints=self._spec_hints(spec),
                            )
                        )
                        try:
                            place_result = self.evidence_graph.resolve_mention(
                                part_mention,
                                hints=str(
                                    getattr(spec, "spatial_hint", "")
                                    or getattr(spec, "unresolved_reason", "")
                                    or ""
                                ),
                            )
                            for place_candidate in place_result.candidates:
                                if place_candidate.feature_bsm:
                                    evidence_lineage["feature_bsms"].append(
                                        place_candidate.feature_bsm
                                    )
                                if place_candidate.source_feature_id:
                                    evidence_lineage["source_feature_ids"].append(
                                        place_candidate.source_feature_id
                                    )
                                evidence_lineage["entity_refs"].append(
                                    place_candidate.entity_ref
                                )
                                evidence_lineage["relation_refs"].extend(
                                    place_candidate.relation_refs
                                )
                                evidence_lineage["l1_fact_refs"].extend(
                                    place_candidate.l1_fact_refs
                                )
                                evidence_lineage["l1_snapshot_ref"] = (
                                    evidence_lineage["l1_snapshot_ref"]
                                    or place_candidate.l1_snapshot_ref
                                )
                                evidence_lineage["bundle_snapshot_digest"] = (
                                    evidence_lineage["bundle_snapshot_digest"]
                                    or place_candidate.bundle_snapshot_digest
                                )
                        except Exception as exc:
                            logger.debug(
                                "[SpatialResolver] evidence lineage lookup skipped: %s",
                                exc,
                            )
                    if evidence_bsms:
                        candidates = CandidateSet(
                            bsms=list(dict.fromkeys(evidence_bsms))
                        )
                # GROUND flash-LLM mention enhancement: when the primary
                # mention cannot bind, try each enhanced sub-mention through
                # the same EvidenceGraph.  The LLM only supplied text.
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
                            self.evidence_graph.candidate_bsms(
                                sub_mention,
                                include_ambiguous=True,
                                max_candidates=64,
                                hints=self._spec_hints(spec),
                            )
                            if self.evidence_graph is not None
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
        )
        evidence_lineage["source_feature_ids"].extend(
            str(getattr(reference, "source_feature_id", "") or "")
            for reference in reference_geometries
            if str(getattr(reference, "source_feature_id", "") or "").strip()
        )
        evidence_lineage["feature_bsms"].extend(
            str(feature_bsm)
            for reference in reference_geometries
            for feature_bsm in (getattr(reference, "feature_bsms", None) or [])
            if str(feature_bsm).strip()
        )
        evidence_lineage["l1_fact_refs"].extend(
            str(fact_ref)
            for reference in reference_geometries
            for fact_ref in (getattr(reference, "l1_fact_refs", None) or [])
            if str(fact_ref).strip()
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
        for key, values in evidence_lineage.items():
            if isinstance(values, list):
                provenance[key] = list(dict.fromkeys(str(item) for item in values if str(item)))
            elif values:
                provenance[key] = str(values)

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

        evidence_feature_count = len(
            set(str(item) for item in evidence_lineage["feature_bsms"] if str(item))
        )
        if (
            final_bsms
            and not bbox
            and not reference_geometries
            and evidence_feature_count == 1
        ):
            # 设计 §4.3：EvidenceGraph 判 ambiguous（多候选接近/弱证据）的引用即使
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
            # 不允许留下不可解析的引用（目标 §"不能留又不能解析"）：在 EvidenceGraph
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
                    spatial_domain_kind="village_scope",
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

        if not bbox and final_bsms and not reference_geometries:
            bbox = self._parcel_bbox(final_bsms)
            if bbox:
                provenance["path"] += "+geometry:parcel_extent_bbox"

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
            if (
                "+geometry:bbox" in path
                or "+geometry:directional_bbox" in path
                or "+geometry:parcel_extent_bbox" in path
                or "+gazetteer:village" in path
                or "+flash_mention" in path
            ):
                uncertainty_reason = "coarse_reference"
                uncertainty_radius_m = _bbox_radius_m(bbox) if bbox else 250.0

        path = str(provenance.get("path", "") or "")
        if reference_geometries:
            geometry_types = {
                str(getattr(ref, "feature_kind", "") or "")
                for ref in reference_geometries
            }
            spatial_domain_kind = (
                "corridor"
                if any("line" in value for value in geometry_types)
                else "exact_feature"
            )
        elif "+geometry:directional_bbox" in path or "+geometry:bbox" in path:
            spatial_domain_kind = "bbox"
        elif "village_cluster" in path or "+gazetteer:village" in path:
            spatial_domain_kind = "village_scope"
        elif final_bsms:
            spatial_domain_kind = "parcel_extent" if len(final_bsms) == 1 else "parcel_set"
        else:
            spatial_domain_kind = "unknown"

        return ResolvedSpatialRef(
            final_bsms=final_bsms,
            bbox=bbox,
            reference_geometry_wkt=reference_geometry_wkt or None,
            reference_geometries=reference_geometries,
            spatial_domain_kind=spatial_domain_kind,
            confidence=confidence,
            uncertainty_radius_m=uncertainty_radius_m,
            uncertainty_reason=uncertainty_reason,
            source_binding_ref=str(provenance.get("source_binding_ref", "") or ""),
            source_collection_key=str(provenance.get("source_collection_key", "") or ""),
            source_snapshot_ref=str(provenance.get("source_snapshot_ref", "") or ""),
            source_feature_digest=str(provenance.get("source_feature_digest", "") or ""),
            feature_bsms=list(dict.fromkeys(
                str(item) for item in evidence_lineage["feature_bsms"] if str(item).strip()
            )),
            source_feature_ids=list(dict.fromkeys(
                str(item)
                for item in evidence_lineage["source_feature_ids"]
                if str(item).strip()
            )),
            entity_refs=list(dict.fromkeys(
                str(item) for item in evidence_lineage["entity_refs"] if str(item).strip()
            )),
            relation_refs=list(dict.fromkeys(
                str(item)
                for item in evidence_lineage["relation_refs"]
                if str(item).strip()
            )),
            l1_fact_refs=list(dict.fromkeys(
                str(item) for item in evidence_lineage["l1_fact_refs"] if str(item).strip()
            )),
            l1_snapshot_ref=str(evidence_lineage["l1_snapshot_ref"] or ""),
            bundle_snapshot_digest=str(
                evidence_lineage["bundle_snapshot_digest"] or ""
            ),
            provenance=provenance,
        )

    def _resolve_direct_bsm_reference(
        self,
        spec: Any,
        reference: Any,
    ) -> "ResolvedSpatialRef":
        """Resolve an explicit parcel BSM without semantic-name lookup.

        BSM is an identity hint, not geometry. Geometry records are collected
        independently from the session bundle. A duplicated BSM is returned
        as separate exact-feature alternatives and marked ambiguous; callers
        must not silently union records from different source geometries.
        """
        from app.contracts.spatial.spatial_reference_contracts import (
            GeometryRef,
            ResolvedSpatialRef,
        )

        filters = getattr(reference, "filter", None) or {}
        bsm = str(filters.get("bsm") or filters.get("label_contains") or "").strip()
        if not bsm:
            return ResolvedSpatialRef(
                final_bsms=[],
                confidence=0.0,
                uncertainty_reason="bsm_reference_missing",
                provenance={"path": "unresolved:bsm_reference_missing"},
            )
        refs: list[GeometryRef] = []
        try:
            parcels = list(self.context.current_parcels() or [])
        except Exception:
            parcels = []
        from shapely.geometry import shape
        import hashlib

        for parcel in parcels:
            parcel_bsm = str(
                getattr(parcel, "bsm", "")
                or (parcel.get("bsm", "") if isinstance(parcel, dict) else "")
            ).strip()
            if parcel_bsm != bsm:
                continue
            raw_geometry = (
                parcel.get("geometry")
                if isinstance(parcel, dict)
                else getattr(parcel, "geometry", None)
            )
            try:
                geometry = shape(raw_geometry) if isinstance(raw_geometry, dict) else raw_geometry
                if geometry is None or geometry.is_empty or not geometry.is_valid:
                    continue
                wkt = geometry.wkt
            except Exception:
                continue
            digest = hashlib.sha256(wkt.encode("utf-8")).hexdigest()[:16]
            source_ref = f"bundle:parcel:{bsm}:geometry:{digest}"
            refs.append(
                GeometryRef(
                    wkt=wkt,
                    crs="EPSG:4326",
                    source_feature_id=source_ref,
                    source_ref=source_ref,
                    source_refs=[source_ref],
                    feature_bsms=[bsm],
                    source_bsms=[bsm],
                    feature_kind="parcel_polygon",
                )
            )
        if not refs:
            return ResolvedSpatialRef(
                final_bsms=[],
                confidence=0.0,
                uncertainty_reason="bsm_not_found_in_bundle",
                provenance={"path": "unresolved:bsm_not_found", "bsm": bsm},
            )
        duplicate = len(refs) > 1
        return ResolvedSpatialRef(
            final_bsms=[bsm],
            reference_geometry_wkt=refs[0].wkt if len(refs) == 1 else None,
            reference_geometries=refs,
            spatial_domain_kind="exact_feature",
            confidence=0.9 if not duplicate else 0.0,
            uncertainty_reason="duplicate_bsm_geometry_identity" if duplicate else "",
            feature_bsms=[bsm],
            source_feature_ids=[ref.source_feature_id for ref in refs],
            provenance={
                "path": "bundle:explicit_bsm",
                "bsm": bsm,
                "geometry_count": len(refs),
                "identity_status": "ambiguous" if duplicate else "unique",
            },
        )

    def _selected_candidate_set_from_evidence_packet(
        self,
        spec: Any,
        packet: Any,
        evidence_lineage: Dict[str, Any],
    ) -> tuple[Any, str, Dict[str, Any]]:
        """Select a packet identity before any geometry enters GROUND.

        EvidenceGraph is a recall boundary: a packet may intentionally retain
        several same-name facilities or hazard points.  Those records are
        alternatives unless TARGET_PROJECTION supplied an explicit multi-ID
        source collection.  A typed LLM choice is therefore required for an
        ambiguous packet; failure remains unresolved and cannot fall through
        to a village-wide or first-candidate fallback.
        """

        from app.contracts.spatial.spatial_reference_contracts import CandidateSet

        refs = list(getattr(packet, "candidate_refs", None) or [])
        if not refs:
            return None, "absent", {}
        unique_refs: list[Any] = []
        seen: set[str] = set()
        for ref in refs:
            identity = getattr(ref, "identity", None)
            key = str(
                getattr(identity, "bundle_feature_bsm", "")
                or getattr(identity, "source_feature_id", "")
                or getattr(ref, "geometry_ref", "")
                or "|".join(getattr(ref, "entity_refs", None) or [])
            ).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique_refs.append(ref)
        if not unique_refs:
            return None, "absent", {}

        packet_status = str(
            getattr(packet, "ambiguity_status", "unresolved") or "unresolved"
        )
        candidate_feature_bsms = [
            str(
                getattr(getattr(ref, "identity", None), "bundle_feature_bsm", "")
                or ""
            ).strip()
            for ref in unique_refs
            if str(
                getattr(getattr(ref, "identity", None), "bundle_feature_bsm", "")
                or ""
            ).strip()
        ]
        meta: Dict[str, Any] = {
            "packet_candidate_count": len(unique_refs),
            "packet_candidate_total": int(
                getattr(packet, "candidate_total", 0) or 0
            ),
            "packet_candidate_offset": int(
                getattr(packet, "candidate_offset", 0) or 0
            ),
            "packet_ambiguity_status": packet_status,
            "packet_candidate_feature_bsms": candidate_feature_bsms,
        }

        candidate_end = int(getattr(packet, "candidate_offset", 0) or 0) + len(unique_refs)
        packet_incomplete = bool(
            getattr(packet, "candidates_truncated", False)
            or getattr(packet, "next_candidate_offset", None) is not None
            or (
                int(getattr(packet, "candidate_total", 0) or 0) > 0
                and candidate_end < int(getattr(packet, "candidate_total", 0) or 0)
            )
        )
        if packet_incomplete:
            meta.update({
                "packet_selection_status": "selection_unresolved",
                "packet_selection_reason": "candidate_pagination_incomplete",
                "packet_next_candidate_offset": getattr(
                    packet, "next_candidate_offset", None
                ),
            })
            return CandidateSet(), "selection_unresolved", meta

        if self._spec_declares_required_source_collection(spec):
            selected_refs = unique_refs
            selection = "explicit_all_members"
        elif len(unique_refs) == 1:
            # Packet ambiguity also reflects non-spatial evidence gaps and
            # can remain ``multiple`` even after EvidenceGraph has narrowed
            # the authoritative Bundle identity to one feature.  With no
            # spatial alternative there is nothing for the LLM to choose;
            # retain the broader packet status in provenance and bind the
            # sole Bundle candidate deterministically.
            selected_refs = unique_refs
            selection = "single_packet_candidate"
        else:
            picked = self._llm_pick_candidate(
                str(getattr(packet, "request", "") or self._spec_mention(spec)),
                self._evidence_packet_selection_hints(spec, packet),
                unique_refs,
            )
            if picked is None:
                llm_enabled = str(
                    os.getenv("GROUND_LLM_ENABLED", "false")
                ).strip().lower() in {"1", "true", "yes", "on"}
                llm_disabled = (
                    not llm_enabled
                    or str(os.getenv("DISABLE_GROUND_LLM", "")).strip().lower()
                    in {"1", "true", "yes", "on"}
                    or str(os.getenv("DISABLE_LLM", "")).strip().lower()
                    in {"1", "true", "yes", "on"}
                )
                meta.update({
                    "packet_selection_status": "selection_unresolved",
                    "packet_selection_reason": (
                        "ground_llm_disabled"
                        if llm_disabled
                        else "closed_set_llm_failed_or_rejected"
                    ),
                })
                return CandidateSet(), "selection_unresolved", meta
            selected_refs = [picked]
            selection = "closed_set_llm_selected"

        selected_packet = packet.model_copy(
            update={
                "candidate_refs": selected_refs,
                "ambiguity_status": "resolved",
            }
        ) if hasattr(packet, "model_copy") else packet
        if selected_packet is packet and len(selected_refs) != len(refs):
            from copy import copy

            selected_packet = copy(packet)
            selected_packet.candidate_refs = selected_refs
            selected_packet.ambiguity_status = "resolved"
        candidates = self._candidate_set_from_evidence_packet(
            selected_packet,
            evidence_lineage,
        )
        if candidates is None:
            return None, "unusable", meta
        selected_feature_bsms = [
            str(
                getattr(getattr(ref, "identity", None), "bundle_feature_bsm", "")
                or ""
            ).strip()
            for ref in selected_refs
            if str(
                getattr(getattr(ref, "identity", None), "bundle_feature_bsm", "")
                or ""
            ).strip()
        ]
        meta.update({
            "packet_selection_status": selection,
            "selected_feature_bsms": selected_feature_bsms,
        })
        return candidates, selection, meta

    @staticmethod
    def _spec_declares_required_source_collection(spec: Any) -> bool:
        collection_key = str(
            getattr(spec, "source_collection_key", "") or ""
        ).strip()
        reference = getattr(spec, "reference", None)
        filters = getattr(reference, "filter", None) or {}
        source_feature_ids = {
            str(value).strip()
            for value in (
                filters.get("source_feature_ids")
                or filters.get("exact_feature_ids")
                or []
            )
            if str(value).strip()
        }
        if collection_key and len(source_feature_ids) > 1:
            return True
        return any(
            SpatialResolver._spec_declares_required_source_collection(child)
            for child in (getattr(spec, "children", None) or [])
        )

    def _evidence_packet_selection_hints(self, spec: Any, packet: Any) -> str:
        """Render bounded semantic/topology context for closed-set selection."""

        parts: list[str] = []
        spec_hints = self._spec_hints(spec)
        if spec_hints:
            parts.append(f"空间要求：{spec_hints}")
        for span in list(getattr(packet, "source_spans", None) or [])[:8]:
            text = str(span or "").strip()
            if text:
                parts.append(f"来源文段：{text[:240]}")
        for relation in list(getattr(packet, "relation_evidence", None) or [])[:8]:
            subject = getattr(getattr(relation, "subject", None), "identity", None)
            object_ = getattr(getattr(relation, "object", None), "identity", None)
            subject_name = str(
                getattr(subject, "canonical_name", "")
                or getattr(subject, "bundle_feature_bsm", "")
                or ""
            )
            object_name = str(
                getattr(object_, "canonical_name", "")
                or getattr(object_, "bundle_feature_bsm", "")
                or ""
            )
            predicate = str(getattr(relation, "predicate", "") or "")
            metric = getattr(relation, "metric_value", None)
            unit = str(getattr(relation, "metric_unit", "") or "")
            metric_text = f" {metric}{unit}" if metric is not None else ""
            parts.append(
                f"拓扑关系：{subject_name} {predicate} {object_name}{metric_text}"
            )
        l1_scope_refs = [
            str(value).strip()
            for value in (getattr(packet, "l1_scope_refs", None) or [])[:8]
            if str(value).strip()
        ]
        if l1_scope_refs:
            parts.append("L1空间范围：" + "、".join(l1_scope_refs))
        external_refs = [
            str(value).strip()
            for value in (getattr(packet, "external_refs", None) or [])[:4]
            if str(value).strip()
        ]
        if external_refs:
            parts.append("外源参考：" + "、".join(external_refs))
        return "\n".join(parts)[:2400]

    @staticmethod
    def _unresolved_evidence_packet_ref(
        packet_meta: Dict[str, Any],
        *,
        path: str,
    ) -> "ResolvedSpatialRef":
        from app.contracts.spatial.spatial_reference_contracts import (
            ResolvedSpatialRef,
        )

        return ResolvedSpatialRef(
            final_bsms=[],
            bbox=None,
            spatial_domain_kind="unknown",
            confidence=0.0,
            uncertainty_radius_m=0.0,
            uncertainty_reason="evidence_packet_selection_unresolved",
            provenance={"path": path, **packet_meta},
        )

    def _evidence_anchor_coordinate(
        self,
        ref: Any,
    ) -> Optional[tuple[float, float]]:
        """Read one anchor point from its authoritative Bundle feature."""

        identity = getattr(ref, "identity", None)
        feature_bsm = str(
            getattr(identity, "bundle_feature_bsm", "") or ""
        ).strip()
        workspace = getattr(self.context, "workspace", None)
        if not feature_bsm or workspace is None:
            return None
        found = workspace.find_feature_by_bsm(feature_bsm)
        if not found:
            return None
        feature = found[2]
        raw_geometry = getattr(feature, "geometry", None)
        try:
            from shapely.geometry import shape

            geometry = (
                shape(raw_geometry)
                if isinstance(raw_geometry, dict)
                else raw_geometry
            )
            if geometry is None or geometry.is_empty:
                return None
            point = geometry if geometry.geom_type == "Point" else geometry.representative_point()
            return float(point.x), float(point.y)
        except Exception as exc:
            logger.debug(
                "[SpatialResolver] anchor coordinate unavailable for %s: %s",
                feature_bsm,
                exc,
            )
            return None

    def _cluster_evidence_anchor_refs(
        self,
        refs: List[Any],
        *,
        max_distance_m: float = 500.0,
    ) -> List[List[Any]]:
        """Build deterministic spatial components from Bundle-backed anchors.

        Two anchors belong to the same component when their Bundle-derived
        parcel neighborhoods overlap or their authoritative representative
        points are within the bounded natural-village distance.  Text labels
        never create an edge.  Missing geometry therefore remains a separate
        candidate instead of being silently merged by name.
        """

        if not refs:
            return []
        coordinates = [self._evidence_anchor_coordinate(ref) for ref in refs]
        parcel_sets = [
            {
                str(value).strip()
                for value in (getattr(ref, "related_parcel_bsms", None) or [])
                if str(value).strip()
            }
            for ref in refs
        ]
        parent = list(range(len(refs)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        from app.spatial.model.geo_utils import haversine_distance

        for left in range(len(refs)):
            for right in range(left + 1, len(refs)):
                parcel_overlap = bool(parcel_sets[left].intersection(parcel_sets[right]))
                close = False
                if coordinates[left] is not None and coordinates[right] is not None:
                    close = haversine_distance(
                        coordinates[left],
                        coordinates[right],
                    ) <= max_distance_m
                if parcel_overlap or close:
                    union(left, right)

        grouped: Dict[int, List[Any]] = {}
        for index, ref in enumerate(refs):
            grouped.setdefault(find(index), []).append(ref)

        def cluster_key(cluster: List[Any]) -> tuple[str, ...]:
            return tuple(sorted(
                str(
                    getattr(
                        getattr(ref, "identity", None),
                        "bundle_feature_bsm",
                        "",
                    )
                    or ""
                )
                for ref in cluster
            ))

        return sorted(grouped.values(), key=cluster_key)

    def _evidence_anchor_cluster_line(
        self,
        index: int,
        cluster: List[Any],
    ) -> str:
        names: list[str] = []
        roles: list[str] = []
        aliases: list[str] = []
        source_layers: list[str] = []
        feature_bsms: list[str] = []
        parcel_bsms: list[str] = []
        l1_fact_refs: list[str] = []
        relation_refs: list[str] = []
        semantic_scores: list[float] = []
        spatial_scores: list[float] = []
        retrieval_scores: list[float] = []
        coordinates: list[tuple[float, float]] = []
        for ref in cluster:
            identity = getattr(ref, "identity", None)
            names.append(str(getattr(identity, "canonical_name", "") or ""))
            roles.append(str(getattr(identity, "role", "") or ""))
            aliases.extend(getattr(identity, "aliases", None) or [])
            source_layers.append(
                str(getattr(identity, "source_layer", "") or "")
            )
            feature_bsms.append(
                str(getattr(identity, "bundle_feature_bsm", "") or "")
            )
            parcel_bsms.extend(getattr(ref, "related_parcel_bsms", None) or [])
            l1_fact_refs.extend(getattr(ref, "l1_fact_refs", None) or [])
            relation_refs.extend(getattr(ref, "relation_refs", None) or [])
            semantic_scores.append(float(
                getattr(ref, "semantic_match_score", 0.0) or 0.0
            ))
            spatial_scores.append(float(
                getattr(ref, "spatial_support_score", 0.0) or 0.0
            ))
            retrieval_scores.append(float(
                getattr(ref, "retrieval_score", 0.0) or 0.0
            ))
            coordinate = self._evidence_anchor_coordinate(ref)
            if coordinate is not None:
                coordinates.append(coordinate)
        centroid = "unknown"
        if coordinates:
            centroid = (
                f"({sum(value[0] for value in coordinates) / len(coordinates):.6f},"
                f"{sum(value[1] for value in coordinates) / len(coordinates):.6f})"
            )
        return (
            f"{index}. names={'、'.join(dict.fromkeys(value for value in names if value)) or 'unknown'}; "
            f"roles={','.join(dict.fromkeys(value for value in roles if value)) or 'unknown'}; "
            f"aliases={'、'.join(list(dict.fromkeys(str(value) for value in aliases if str(value)))[:8]) or 'none'}; "
            f"source_layers={','.join(dict.fromkeys(value for value in source_layers if value)) or 'unknown'}; "
            f"anchor_BSMs={','.join(dict.fromkeys(value for value in feature_bsms if value))}; "
            f"related_parcels={','.join(list(dict.fromkeys(str(value) for value in parcel_bsms if str(value)))[:12])}; "
            f"L1_facts={','.join(list(dict.fromkeys(str(value) for value in l1_fact_refs if str(value)))[:8]) or 'none'}; "
            f"KG_topology={','.join(list(dict.fromkeys(str(value) for value in relation_refs if str(value)))[:8]) or 'none'}; "
            f"scores=semantic:{max(semantic_scores, default=0.0):.3f},"
            f"spatial:{max(spatial_scores, default=0.0):.3f},"
            f"retrieval:{max(retrieval_scores, default=0.0):.3f}; "
            f"anchor_count={len(cluster)}; centroid={centroid}"
        )

    def _village_scope_from_evidence_packet(
        self,
        spec: Any,
        packet: Any,
    ) -> Optional["ResolvedSpatialRef"]:
        """Infer a coarse natural-village scope from spatial evidence anchors.

        A hazard/facility point whose typed address mentions a natural village
        can locate that village even when no standalone village polygon exists.
        Only the point's Bundle-related parcels become scope seeds; the point
        is retained as provenance and is never promoted to a village geometry.
        """

        refs = list(getattr(packet, "candidate_refs", None) or [])
        if not refs:
            return None
        reference = getattr(spec, "reference", None)
        filters = getattr(reference, "filter", None) or {}
        label = str(filters.get("label_contains") or "").strip()

        # Prefer point/feature anchors over parcel rows when both appear in a
        # broad packet.  Parcels remain attached through the typed topology
        # refs; they are not independent semantic observations of the name.
        semantic_anchor_refs: list[Any] = []
        for ref in refs[:8]:
            identity = getattr(ref, "identity", None)
            role = str(getattr(identity, "role", "") or "").casefold()
            entity_type = str(
                getattr(identity, "entity_type", "") or ""
            ).casefold()
            source_layer = str(
                getattr(identity, "source_layer", "") or ""
            ).casefold()
            if role in {"parcel", "zone"} or entity_type in {"parcel", "zone"}:
                continue
            if source_layer in {"landuse_current", "parcels", "zones"}:
                continue
            semantic_anchor_refs.append(ref)
        anchor_refs = semantic_anchor_refs or refs[:8]
        anchor_clusters = self._cluster_evidence_anchor_refs(anchor_refs)
        cluster_lines = [
            self._evidence_anchor_cluster_line(index, cluster)
            for index, cluster in enumerate(anchor_clusters, 1)
        ]
        selected_cluster_index = 0
        cluster_selection = "single_spatial_cluster"
        if len(anchor_clusters) > 1:
            selected = self._llm_pick_index(
                str(getattr(packet, "request", "") or label),
                self._evidence_packet_selection_hints(spec, packet),
                cluster_lines,
                candidate_kind="空间证据簇",
            )
            if selected is None:
                from app.contracts.spatial.spatial_reference_contracts import (
                    ResolvedSpatialRef,
                )

                return ResolvedSpatialRef(
                    final_bsms=[],
                    bbox=None,
                    spatial_domain_kind="unknown",
                    confidence=0.0,
                    uncertainty_radius_m=0.0,
                    uncertainty_reason="evidence_anchor_clusters_unresolved",
                    provenance={
                        "path": "evidence_packet:anchor_cluster_selection_unresolved",
                        "scope_label": label,
                        "anchor_cluster_count": len(anchor_clusters),
                        "anchor_cluster_candidates": cluster_lines,
                        "cluster_selection_reason": (
                            "ground_llm_disabled"
                            if self._ground_llm_disabled()
                            else "closed_set_llm_failed_or_rejected"
                        ),
                        "not_exact_village_boundary": True,
                    },
                )
            selected_cluster_index = selected
            cluster_selection = "closed_set_llm_selected_cluster"
        refs = anchor_clusters[selected_cluster_index]
        parcel_bsms: list[str] = []
        feature_bsms: list[str] = []
        source_feature_ids: list[str] = []
        entity_refs: list[str] = []
        relation_refs: list[str] = []
        l1_fact_refs: list[str] = []
        anchor_roles: list[str] = []
        for ref in refs[:8]:
            identity = getattr(ref, "identity", None)
            role = str(getattr(identity, "role", "") or "").casefold()
            entity_type = str(
                getattr(identity, "entity_type", "") or ""
            ).casefold()
            source_layer = str(
                getattr(identity, "source_layer", "") or ""
            ).casefold()
            feature_bsm = str(
                getattr(identity, "bundle_feature_bsm", "") or ""
            ).strip()
            if role in {"parcel", "zone"} or entity_type in {"parcel", "zone"}:
                parcel_bsms.append(feature_bsm)
            elif source_layer in {"landuse_current", "parcels", "zones"}:
                parcel_bsms.append(feature_bsm)
            parcel_bsms.extend(
                str(value).strip()
                for value in (getattr(ref, "related_parcel_bsms", None) or [])
                if str(value).strip()
            )
            if feature_bsm:
                feature_bsms.append(feature_bsm)
            source_feature_id = str(
                getattr(identity, "source_feature_id", "") or ""
            ).strip()
            if source_feature_id:
                source_feature_ids.append(source_feature_id)
            entity_refs.extend(getattr(ref, "entity_refs", None) or [])
            relation_refs.extend(getattr(ref, "relation_refs", None) or [])
            l1_fact_refs.extend(getattr(ref, "l1_fact_refs", None) or [])
            if role or entity_type:
                anchor_roles.append(role or entity_type)
        final_bsms = self._filter_to_bundle(list(dict.fromkeys(parcel_bsms)))
        if not final_bsms:
            return None

        from app.contracts.spatial.spatial_reference_contracts import (
            ResolvedSpatialRef,
        )

        return ResolvedSpatialRef(
            final_bsms=final_bsms,
            bbox=self._parcel_bbox(final_bsms),
            spatial_domain_kind="village_scope",
            confidence=0.45,
            uncertainty_radius_m=250.0,
            uncertainty_reason="evidence_derived_village_scope",
            feature_bsms=list(dict.fromkeys(feature_bsms)),
            source_feature_ids=list(dict.fromkeys(source_feature_ids)),
            entity_refs=list(dict.fromkeys(str(value) for value in entity_refs if str(value))),
            relation_refs=list(dict.fromkeys(str(value) for value in relation_refs if str(value))),
            l1_fact_refs=list(dict.fromkeys(str(value) for value in l1_fact_refs if str(value))),
            l1_snapshot_ref=str(getattr(packet, "l1_snapshot_ref", "") or ""),
            bundle_snapshot_digest=str(
                getattr(packet, "bundle_snapshot_digest", "") or ""
            ),
            provenance={
                "path": "evidence_packet:anchor_to_village_scope",
                "scope_label": label,
                "scope_seed_parcel_bsms": final_bsms,
                "anchor_feature_bsms": list(dict.fromkeys(feature_bsms)),
                "anchor_roles": list(dict.fromkeys(anchor_roles)),
                "anchor_cluster_count": len(anchor_clusters),
                "selected_anchor_cluster_index": selected_cluster_index + 1,
                "anchor_cluster_selection": cluster_selection,
                "scope_semantics": "inferred_from_spatial_evidence",
                "not_exact_village_boundary": True,
            },
        )

    def _candidate_set_from_evidence_packet(
        self,
        packet: Any,
        evidence_lineage: Dict[str, Any],
    ) -> Any:
        """Convert verified packet refs into a resolver CandidateSet.

        The packet contains no WKT.  ``geometry_refs_from_evidence_packet``
        performs the only bundle-authoritative geometry read; missing or
        malformed refs simply make this adapter return ``None`` so the normal
        EvidenceGraph path can continue.
        """
        if packet is None or not getattr(packet, "candidate_refs", None):
            return None
        from app.contracts.spatial.spatial_reference_contracts import CandidateSet
        from app.evidence.retrieval.evidence_graph import (
            geometry_refs_from_evidence_packet,
        )

        references = geometry_refs_from_evidence_packet(self.context, packet)
        if not references:
            return None
        bsms: list[str] = []
        for candidate in list(getattr(packet, "candidate_refs", None) or []):
            identity = getattr(candidate, "identity", None)
            feature_bsm = str(
                getattr(identity, "bundle_feature_bsm", "") or ""
            ).strip()
            if feature_bsm:
                evidence_lineage["feature_bsms"].append(feature_bsm)
                entity_type = str(getattr(identity, "entity_type", "") or "").casefold()
                role = str(getattr(identity, "role", "") or "").casefold()
                source_layer = str(getattr(identity, "source_layer", "") or "").casefold()
                if entity_type in {"parcel", "zone"} or role in {"parcel", "zone"}:
                    bsms.append(feature_bsm)
                elif source_layer in {"landuse_current", "parcels", "zones"}:
                    bsms.append(feature_bsm)
            evidence_lineage["source_feature_ids"].extend(
                [str(getattr(identity, "source_feature_id", "") or "")]
            )
            evidence_lineage["entity_refs"].extend(
                [str(value) for value in (getattr(candidate, "entity_refs", None) or [])]
            )
            evidence_lineage["relation_refs"].extend(
                [str(value) for value in (getattr(candidate, "relation_refs", None) or [])]
            )
            evidence_lineage["l1_fact_refs"].extend(
                [str(value) for value in (getattr(candidate, "l1_fact_refs", None) or [])]
            )
            evidence_lineage["l1_snapshot_ref"] = (
                evidence_lineage["l1_snapshot_ref"]
                or str(getattr(candidate, "l1_snapshot_ref", "") or "")
                or str(getattr(packet, "l1_snapshot_ref", "") or "")
            )
            evidence_lineage["bundle_snapshot_digest"] = (
                evidence_lineage["bundle_snapshot_digest"]
                or str(getattr(identity, "bundle_snapshot_digest", "") or "")
                or str(getattr(packet, "bundle_snapshot_digest", "") or "")
            )
            bsms.extend(
                str(value)
                for value in (getattr(candidate, "related_parcel_bsms", None) or [])
                if str(value).strip()
            )
        return CandidateSet(
            bsms=list(dict.fromkeys(bsms)),
            ref_geometries=references,
        )

    def _resolved_from_candidate_set(
        self,
        spec: Any,
        candidates: Any,
        evidence_lineage: Dict[str, Any],
        *,
        path: str,
    ) -> "ResolvedSpatialRef":
        """Build a resolved reference from a canonical candidate set.

        This is used for a packet that already represents the complete
        composed spatial query.  Re-running each child against the ordinary
        mention index would discard the packet's exact geometry and relation
        lineage, especially when a child is only meaningful in the parent's
        topology context.
        """
        from app.contracts.spatial.spatial_reference_contracts import (
            ResolvedSpatialRef,
        )

        bsms = list(
            dict.fromkeys(
                [
                    str(value).strip()
                    for value in [
                        *(getattr(candidates, "bsms", None) or []),
                        *(getattr(candidates, "ref_bsms", None) or []),
                    ]
                    if str(value).strip()
                ]
            )
        )
        final_bsms = self._filter_to_bundle(bsms)
        references = _authoritative_geometry_refs(
            getattr(candidates, "ref_geometries", None),
        )
        geometry_types = {
            str(getattr(ref, "feature_kind", "") or "").casefold()
            for ref in references
        }
        if references:
            spatial_domain_kind = (
                "corridor"
                if any("line" in value for value in geometry_types)
                else "exact_feature"
            )
        elif len(final_bsms) == 1:
            spatial_domain_kind = "parcel_extent"
        elif final_bsms:
            spatial_domain_kind = "parcel_set"
        else:
            spatial_domain_kind = "unknown"
        provenance = {
            "path": path,
            "kg_count": len(bsms),
            "bundle_count": len(final_bsms),
        }
        for attribute in (
            "source_binding_ref",
            "source_collection_key",
            "source_snapshot_ref",
            "source_feature_digest",
        ):
            value = str(getattr(spec, attribute, "") or "").strip()
            if value:
                provenance[attribute] = value
        for key, values in evidence_lineage.items():
            if isinstance(values, list):
                provenance[key] = list(
                    dict.fromkeys(str(item) for item in values if str(item))
                )
            elif values:
                provenance[key] = str(values)
        return ResolvedSpatialRef(
            final_bsms=final_bsms,
            reference_geometry_wkt=(
                references[0].wkt if len(references) == 1 else None
            ),
            reference_geometries=references,
            spatial_domain_kind=spatial_domain_kind,
            confidence=0.9 if references else (0.7 if final_bsms else 0.0),
            source_binding_ref=str(provenance.get("source_binding_ref", "") or ""),
            source_collection_key=str(provenance.get("source_collection_key", "") or ""),
            source_snapshot_ref=str(provenance.get("source_snapshot_ref", "") or ""),
            source_feature_digest=str(provenance.get("source_feature_digest", "") or ""),
            provenance=provenance,
        )

    def _resolve_kg_spatial_spec(
        self,
        spec: Any,
        evidence_lineage: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Resolve a topological spec through the session KG adapter.

        The adapter is the shared KG topology boundary for RDFLib and
        PostGIS-backed stores.  Returning an empty ``CandidateSet`` is still
        meaningful: the caller may continue with EvidenceGraph fallback, but
        it must never turn the anchor itself into an execution target.
        """
        from app.contracts.spatial.spatial_reference_contracts import CandidateSet

        ports = getattr(self.context, "ports", None)
        port = getattr(ports, "spatial_query", None) if ports is not None else None
        if port is None or not callable(getattr(port, "resolve_candidates", None)):
            return None
        try:
            result = port.resolve_candidates(
                str(getattr(self.context, "session_id", "") or ""),
                spec,
            )
            result = result if isinstance(result, CandidateSet) else CandidateSet()
            if evidence_lineage is not None:
                self._append_kg_topology_lineage(spec, result, evidence_lineage)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.debug("[SpatialResolver] KG topology query failed: %s", exc)
            return CandidateSet()

    def _append_kg_topology_lineage(
        self,
        spec: Any,
        candidates: Any,
        evidence_lineage: Dict[str, Any],
    ) -> None:
        """Attach KG relation, L1 and snapshot refs to a topology resolution."""
        kg = self.kg
        if kg is None:
            return
        finder = getattr(kg, "find_entities", None)
        relation_finder = getattr(kg, "find_relations", None)
        if not callable(finder) or not callable(relation_finder):
            return
        reference = getattr(spec, "reference", None)
        filters = getattr(reference, "filter", None) or {}
        label = str(filters.get("label_contains") or "").strip()
        anchor_refs: set[str] = set()
        if label:
            try:
                anchor_refs.update(
                    str(getattr(entity, "entity_ref", "") or "").strip()
                    for entity in finder(name=label, limit=50) or []
                    if str(getattr(entity, "entity_ref", "") or "").strip()
                )
            except Exception:
                pass
        if getattr(reference, "kind", "") == "village":
            village_name = str(getattr(self.context, "village_name", "") or "").strip()
            for token in (village_name, f"{village_name}村"):
                if not token:
                    continue
                try:
                    anchor_refs.update(
                        str(getattr(entity, "entity_ref", "") or "").strip()
                        for entity in finder(name=token, limit=20) or []
                        if str(getattr(entity, "entity_ref", "") or "").strip()
                    )
                except Exception:
                    continue

        target_refs: set[str] = set()
        target_bsms = [
            str(value).strip()
            for value in [
                *(getattr(candidates, "bsms", None) or []),
                *(getattr(candidates, "ref_bsms", None) or []),
            ]
            if str(value).strip()
        ]
        for value in target_bsms:
            try:
                entities = (
                    finder(feature_bsm=value, limit=20)
                    if value.isdigit()
                    else finder(entity_ref=value, limit=20)
                ) or []
            except Exception:
                entities = []
            target_refs.update(
                str(getattr(entity, "entity_ref", "") or "").strip()
                for entity in entities
                if str(getattr(entity, "entity_ref", "") or "").strip()
            )
        evidence_lineage["entity_refs"].extend([*anchor_refs, *target_refs])

        predicate_name = str(getattr(spec, "topo", "") or "")
        relation_ids: set[str] = set()
        if anchor_refs:
            for anchor_ref in anchor_refs:
                try:
                    relations = [
                        *list(relation_finder(subject_ref=anchor_ref, limit=48) or []),
                        *list(relation_finder(object_ref=anchor_ref, limit=48) or []),
                    ]
                except Exception:
                    relations = []
                for relation in relations:
                    predicate = str(getattr(relation, "predicate", "") or "")
                    local_name = predicate.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                    if local_name != predicate_name:
                        continue
                    subject_ref = str(getattr(relation, "subject_ref", "") or "")
                    object_ref = str(getattr(relation, "object_ref", "") or "")
                    if target_refs and not ({subject_ref, object_ref} & target_refs):
                        continue
                    relation_id = str(getattr(relation, "relation_id", "") or "")
                    if relation_id:
                        relation_ids.add(relation_id)
        evidence_lineage["relation_refs"].extend(sorted(relation_ids))

        for fact in list(getattr(self.context, "location_facts", None) or []):
            values = {
                str(getattr(fact, "normalized_name", "") or "").strip(),
                str(getattr(fact, "mention", "") or "").strip(),
                str(getattr(fact, "spatial_hint", "") or "").strip(),
            }
            if label and not any(label in value for value in values if value):
                continue
            evidence_lineage["l1_fact_refs"].extend(
                str(value).strip()
                for value in [
                    getattr(fact, "source_report_ref", ""),
                    *(getattr(fact, "evidence_refs", None) or []),
                ]
                if str(value).strip()
            )
        evidence_lineage["l1_snapshot_ref"] = (
            evidence_lineage["l1_snapshot_ref"]
            or str(getattr(self.context, "l1_snapshot_ref", "") or "")
        )
        evidence_lineage["bundle_snapshot_digest"] = (
            evidence_lineage["bundle_snapshot_digest"]
            or str(
                getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                or ""
            )
        )

    def _llm_reason_fallback(
        self,
        spec: Any,
        mention: str,
        mention_enhancements: Optional[Dict[str, List[str]]] = None,
        extra_candidates: Optional[List[Any]] = None,
    ) -> Optional["ResolvedSpatialRef"]:
        """有界 LLM best-effort（设计 §4.3）：在 Recall 候选内判别，不新增 BSM/几何。

        LLM 只在 EvidenceGraph 召回的候选内选最优；候选行携带几何与 KG 拓扑关系，
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
            spatial_domain_kind=(
                "exact_feature"
                if getattr(picked, "feature_bsm", None)
                else ("parcel_extent" if len(bsms) == 1 else "parcel_set")
            ),
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
        """Return every deduped EvidenceGraph candidate for LLM discrimination.

        EvidenceGraph already owns the bounded recall/page limit.  A second
        hidden ``[:8]`` here would discard valid address/topology candidates
        before the semantic selector sees them.
        """
        candidates: List[Any] = []
        if self.evidence_graph is None:
            return []
        sub_mentions = [mention]
        for sub in (mention_enhancements or {}).get(getattr(spec, "target_id", ""), []) or []:
            sub_mentions.append(_normalize_spec_mention(str(sub)))
        hints = self._spec_hints(spec)
        for sub in sub_mentions:
            if not sub:
                continue
            try:
                result = self.evidence_graph.resolve_mention(sub, hints=hints)
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
        return sorted(by_ref.values(), key=lambda c: -c.score)

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
        lines = [
            self._candidate_line(index, candidate)
            for index, candidate in enumerate(ordered, 1)
        ]
        index = self._llm_pick_index(
            mention,
            hints,
            lines,
            candidate_kind="候选实体",
        )
        if index is None:
            return None
        return ordered[index]

    @staticmethod
    def _ground_llm_disabled() -> bool:
        enabled = str(os.getenv("GROUND_LLM_ENABLED", "false")).strip().lower() in {
            "1", "true", "yes", "on",
        }
        disabled = any(
            str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}
            for name in (
                "DISABLE_LLM",
                "DISABLE_GROUND_LLM",
                "DISABLE_GROUND_REPORT_LLM",
            )
        )
        return not enabled or disabled

    def _llm_pick_index(
        self,
        mention: str,
        hints: str,
        candidate_lines: List[str],
        *,
        candidate_kind: str,
    ) -> Optional[int]:
        """Select one zero-based index from a closed, Bundle-backed set."""

        if not candidate_lines or self._ground_llm_disabled():
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

            llm = create_flash_llm(max_tokens=800, temperature=0.1)
            lines = chr(10).join(candidate_lines)
            hint_clause = f"《{hints}》" if hints else ""
            prompt = (
                f"空间引用「{mention}」{hint_clause}。"
                f"以下是从 EvidenceGraph 召回并由 Bundle/KG 拓扑组织的{candidate_kind}，"
                "请选择与引用最匹配的一个，只输出编号；都不合适输出 0：\n" + lines
            )

            structured_factory = getattr(llm, "with_structured_output", None)
            if not callable(structured_factory):
                raise TypeError(
                    "grounding LLM must expose typed with_structured_output"
                )
            structured = structured_factory(
                _CandidateChoice,
                method="function_calling",
            )

            # This resolver is intentionally synchronous at the spatial
            # aggregate boundary. Bound the typed provider call in a
            # short-lived worker and keep the shared grounding gate around it;
            # the async L1 fan-out is implemented in ground_l1_anchors.
            executor = ThreadPoolExecutor(max_workers=1)
            sync_gate = ground_llm_sync_semaphore(self._ground_llm_budget)

            def _invoke_with_bounded_queue():
                # The semaphore wait must happen in the timed worker too.
                # Waiting in the caller thread would serialize ambiguous
                # references before the provider timeout even starts.
                acquired = sync_gate.acquire(timeout=max(0.001, call_timeout))
                if not acquired:
                    raise TimeoutError("grounding LLM semaphore queue timeout")
                try:
                    return structured.invoke(prompt)
                finally:
                    sync_gate.release()

            try:
                response = executor.submit(_invoke_with_bounded_queue).result(
                    timeout=call_timeout
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            choice = response
            if choice is None:
                return None
            if not isinstance(choice, _CandidateChoice):
                choice = _CandidateChoice.model_validate(choice)
            index = choice.candidate_index - 1
            if 0 <= index < len(candidate_lines):
                return index
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
        """Render identity, address aliases, provenance and topology clues."""
        identity = getattr(c, "identity", None)
        rels: List[str] = []
        for ref in list(getattr(c, "relation_refs", None) or [])[:5]:
            text = str(ref)
            rels.append(text.rsplit("#", 1)[-1].rsplit("/", 1)[-1])
        aliases = list(
            dict.fromkeys(
                str(value).strip()
                for value in (
                    getattr(c, "aliases", None)
                    or getattr(identity, "aliases", None)
                    or []
                )
                if str(value).strip()
            )
        )[:6]
        feature_bsm = str(
            getattr(c, "feature_bsm", "")
            or getattr(identity, "bundle_feature_bsm", "")
            or getattr(c, "source_bsm", "")
            or getattr(identity, "source_bsm", "")
            or (
                getattr(c, "source_bsms", [])[0]
                if len(getattr(c, "source_bsms", []) or []) == 1
                else ""
            )
            or ""
        ).strip()
        geometry = f"bundle://feature/{feature_bsm}" if feature_bsm else ""
        source_bsms = list(
            dict.fromkeys(
                str(value).strip()
                for value in (
                    getattr(c, "source_bsms", None)
                    or (
                        [getattr(identity, "source_bsm", "")]
                        if getattr(identity, "source_bsm", "")
                        else []
                    )
                )
                if str(value).strip()
            )
        )[:8]
        related_parcels = list(
            dict.fromkeys(
                str(value).strip()
                for value in (getattr(c, "related_parcel_bsms", None) or [])
                if str(value).strip()
            )
        )[:8]
        l1_refs = list(
            dict.fromkeys(
                str(value).strip()
                for value in (getattr(c, "l1_fact_refs", None) or [])
                if str(value).strip()
            )
        )[:5]
        evidence_refs = list(
            dict.fromkeys(
                str(value).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                for value in (
                    getattr(c, "evidence_refs", None)
                    or getattr(c, "provenance_refs", None)
                    or []
                )
                if str(value).strip()
            )
        )[:5]
        selection_evidence = {
            str(key): float(value)
            for key, value in dict(
                getattr(c, "evidence", None)
                or getattr(c, "selection_evidence", None)
                or {}
            ).items()
            if float(value or 0.0) > 0.0
        }
        canonical_name = str(
            getattr(c, "canonical_name", "")
            or getattr(identity, "canonical_name", "")
            or ""
        )
        entity_type = str(
            getattr(c, "entity_type", "")
            or getattr(identity, "entity_type", "")
            or ""
        )
        role = str(
            getattr(c, "role", "")
            or getattr(identity, "role", "")
            or "unknown"
        )
        source_layer = str(
            getattr(c, "source_layer", "")
            or getattr(identity, "source_layer", "")
            or "未知"
        )
        score = float(
            getattr(c, "score", 0.0)
            or getattr(c, "confidence", 0.0)
            or 0.0
        )
        return (
            f"{index}. {canonical_name or '未命名实体'} 类型={entity_type or 'unknown'} "
            f"别名={'、'.join(aliases) or '无'} 角色={role} "
            f"来源层={source_layer} feature_BSM={feature_bsm or '无'} "
            f"来源BSM={','.join(source_bsms) or '无'} "
            f"关联地块={','.join(related_parcels) or '无'} 几何={geometry or '无'} "
            f"拓扑={','.join(rels) or '无'} L1事实={','.join(l1_refs) or '无'} "
            f"来源证据={','.join(evidence_refs) or '无'} "
            f"选择证据={selection_evidence or '无'} 得分={score:.2f}"
        )

    def _llm_resolve_ambiguous(
        self,
        spec: Any,
        mention: str,
        mention_enhancements: Optional[Dict[str, List[str]]] = None,
    ) -> Optional["ResolvedSpatialRef"]:
        """歧义引用有界判别（设计 §4.3）：EvidenceGraph 判 ambiguous 时在候选内选。

        成功返回 LLM 判别的落位；失败保持原确定性结果（已有 BSMs 不丢）。
        """
        if self.evidence_graph is None or not mention:
            return None
        try:
            result = self.evidence_graph.resolve_mention(
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
        from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
        from app.evidence.retrieval.evidence_graph import (
            feature_ref_from_candidate,
            geometry_refs_from_evidence_packet,
        )

        picked_ref = feature_ref_from_candidate(
            picked,
            bundle_digest=str(
                getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                or ""
            ),
        )
        picked_packet = EvidencePacket(
            request=mention,
            candidate_refs=[picked_ref],
        )
        reference_geometries = geometry_refs_from_evidence_packet(
            self.context,
            picked_packet,
            max_refs=1,
        )
        if not bsms and not reference_geometries:
            return None
        from app.contracts.spatial.spatial_reference_contracts import ResolvedSpatialRef

        feature_bsm = str(getattr(picked, "feature_bsm", "") or "").strip()
        source_feature_id = str(
            getattr(picked, "source_feature_id", "") or ""
        ).strip()
        source_bsms = list(
            dict.fromkeys(
                str(value).strip()
                for value in (getattr(picked, "source_bsms", None) or [])
                if str(value).strip()
            )
        )
        relation_refs = list(
            dict.fromkeys(
                str(value).strip()
                for value in (getattr(picked, "relation_refs", None) or [])
                if str(value).strip()
            )
        )
        l1_fact_refs = list(
            dict.fromkeys(
                str(value).strip()
                for value in (getattr(picked, "l1_fact_refs", None) or [])
                if str(value).strip()
            )
        )

        return ResolvedSpatialRef(
            final_bsms=bsms,
            reference_geometry_wkt=(
                reference_geometries[0].wkt
                if len(reference_geometries) == 1
                else None
            ),
            reference_geometries=reference_geometries,
            bbox=None,
            spatial_domain_kind=(
                "exact_feature"
                if reference_geometries or feature_bsm
                else ("parcel_extent" if len(bsms) == 1 else "parcel_set")
            ),
            confidence=0.5,
            uncertainty_radius_m=250.0,
            uncertainty_reason="llm_ambiguous_resolution",
            provenance={
                "path": "evidence:candidates+llm_ambiguous",
                "mention": mention,
                "picked": str(getattr(picked, "canonical_name", "") or ""),
                "candidate_count": len(candidates),
                "selected_feature_bsm": feature_bsm,
                "source_feature_id": source_feature_id,
                "source_bsms": source_bsms,
                "relation_refs": relation_refs,
                "l1_fact_refs": l1_fact_refs,
                "reference_geometry_count": len(reference_geometries),
            },
            feature_bsms=[feature_bsm] if feature_bsm else [],
            source_feature_ids=[source_feature_id] if source_feature_id else [],
            entity_refs=list(getattr(picked, "entity_refs", None) or [])
            or ([str(getattr(picked, "entity_ref", ""))] if getattr(picked, "entity_ref", "") else []),
            relation_refs=relation_refs,
            l1_fact_refs=l1_fact_refs,
            l1_snapshot_ref=str(getattr(picked, "l1_snapshot_ref", "") or ""),
            bundle_snapshot_digest=str(
                getattr(picked, "bundle_snapshot_digest", "")
                or getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                or ""
            ),
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

    def _parcel_bbox(self, bsms: List[str]) -> Optional[tuple[float, float, float, float]]:
        """Derive a bounded extent from authoritative bundle parcel geometry."""
        wanted = {str(bsm) for bsm in bsms if str(bsm).strip()}
        if not wanted:
            return None
        bounds: list[tuple[float, float, float, float]] = []
        try:
            from shapely.geometry import shape

            for parcel in self.context.current_parcels():
                bsm = str(getattr(parcel, "bsm", "") or "").strip()
                if bsm not in wanted:
                    continue
                raw = getattr(parcel, "geometry", None)
                geometry = shape(raw) if isinstance(raw, dict) else raw
                if geometry is None or geometry.is_empty or not geometry.is_valid:
                    continue
                bounds.append(tuple(float(value) for value in geometry.bounds))
        except Exception:
            return None
        if not bounds:
            return None
        return (
            min(item[0] for item in bounds),
            min(item[1] for item in bounds),
            max(item[2] for item in bounds),
            max(item[3] for item in bounds),
        )


    def _resolve_village_cluster(
        self,
        label: str,
        *,
        allow_session_fallback: bool = True,
    ):
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
        if not allow_session_fallback:
            return None
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
