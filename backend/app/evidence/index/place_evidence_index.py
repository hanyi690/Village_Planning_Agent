"""PlaceEvidenceIndex - deterministic, versioned evidence index (design §3.2).

Built once from a ``PlanningContext``: gazetteer entries, L1 typed location
facts, bundle POI annotations and (optionally) KG entity names. Resolution
(source candidate generation §4.1) is deterministic and scored over the eight
dimensions; ``candidate_bsms`` returns the source BSM set for the resolver.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.contracts.ports.place_resolution_contracts import (
    PlaceEvidenceEntry,
    PlaceResolutionCandidate,
    PlaceResolutionResult,
)
from app.evidence.index.evidence_scorer import (
    score_candidate,
    total,
)
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_RESOLVED_THRESHOLD = 0.8
_AMBIGUOUS_GAP = 0.15


class PlaceEvidenceIndex:
    """A versioned snapshot of place evidence derived from a context."""

    def __init__(self, context: Any, version: tuple = (0, 0)):
        self.context = context
        self.version = version
        self.entries: List[PlaceEvidenceEntry] = []
        self._by_canonical: Dict[str, PlaceEvidenceEntry] = {}
        self._by_alias: Dict[str, PlaceEvidenceEntry] = {}

    @classmethod
    def build(cls, context: Any) -> "PlaceEvidenceIndex":
        """Construct the index from a ``PlanningContext``."""
        version = (
            int(getattr(context, "version", 0) or 0),
            int(getattr(context, "kg_version", 0) or 0),
        )
        index = cls(context=context, version=version)

        if getattr(context, "gazetteer", None) is not None:
            for e in getattr(context.gazetteer, "entries", []) or []:
                index._register_from_gazetteer(e)

        # KG entity names carry authoritative BSM/geometry.  Register them
        # before L1 facts so a fact with a matching name merges onto the entity
        # (entity-level binding) instead of a whole-DLMC class fallback.
        kg = getattr(context, "kg", None)
        if kg is not None:
            index._register_kg_names(kg)

        try:
            parcels = list(context.current_parcels() or [])
        except Exception:
            workspace = getattr(context, "workspace", None)
            parcels = list(
                (getattr(workspace, "polygons", {}) or {}).get("landuse_current") or []
            )
        from app.spatial.grounding.grounding import build_parcel_centroid_cache

        centroid_cache = build_parcel_centroid_cache(parcels)
        for fact in getattr(context, "location_facts", []) or []:
            index._register_from_l1_fact(fact, parcels, centroid_cache)

        workspace = getattr(context, "workspace", None)
        if workspace is not None:
            pois = (workspace.points.get("annotations_current") or []) if getattr(workspace, "points", None) else []
            index._register_poi(pois, parcels, centroid_cache)

        return index

    # ── Registration ─────────────────────────────────────────────────

    def _register_from_gazetteer(self, entry: Any) -> None:
        name = getattr(entry, "name", "") or ""
        if not name:
            return
        bsms = [str(b) for b in (getattr(entry, "bsms", None) or [])]
        entity_uri = getattr(entry, "entity_uri", "") or name
        centroid = getattr(entry, "centroid", None)
        geometry_ref = None
        if centroid:
            geometry_ref = f"POINT({centroid[0]} {centroid[1]})" if len(centroid) >= 2 else None
        aliases = [str(a) for a in (getattr(entry, "aliases", None) or []) if a]
        role, entity_types = self._gazetteer_role(entry)
        self._add_entry(
            PlaceEvidenceEntry(
                canonical_name=name,
                aliases=aliases,
                entity_refs=[entity_uri],
                entity_types=entity_types,
                role=role,
                source_bsms=bsms,
                geometry_ref=geometry_ref,
                provenance=["gazetteer"],
                confidence=float(getattr(entry, "confidence", 0.0) or 0.0),
            )
        )

    @staticmethod
    def _gazetteer_role(entry: Any) -> tuple[str, list[str]]:
        """Dispatch a gazetteer entry's role from its source and anchor URI kind."""
        source = str(getattr(entry, "source", "") or "")
        if source == "kg_facility":
            return "facility", ["facility"]
        if source == "l1_instruction":
            uri = str(getattr(entry, "entity_uri", "") or "")
            for kind in ("facility", "project", "zone", "landmark"):
                if f"anchor_{kind}_" in uri:
                    return kind, [kind]
            return "village", ["village"]
        return "village", ["village"]

    def _register_from_l1_fact(
        self,
        fact: Any,
        parcels: Optional[List[Any]] = None,
        centroid_cache: Optional[Dict[str, Any]] = None,
    ) -> None:
        norm = getattr(fact, "normalized_name", "") or ""
        mention = getattr(fact, "normalized_name", "") or getattr(fact, "mention", "") or ""
        name = norm or mention
        if not name:
            return
        role = getattr(fact, "role", "unknown") or "unknown"
        aliases = [str(a) for a in (getattr(fact, "aliases", None) or []) if a]
        if name not in aliases:
            aliases.append(name)
        entry = PlaceEvidenceEntry(
            canonical_name=name,
            aliases=aliases,
            entity_refs=[f"l1_fact:{name}"],
            entity_types=[role],
            role=role,
            source_bsms=[],
            geometry_ref=None,
            provenance=["l1_fact"],
            confidence=float(getattr(fact, "confidence", 0.0) or 0.0),
        )
        self._add_entry(entry)
        self._bind_l1_fact_bsms(fact, entry, parcels, centroid_cache)

    # L1 fact geometry binding (design §3.2: entity-level, never class-level)

    def _bind_l1_fact_bsms(
        self,
        fact: Any,
        entry: "PlaceEvidenceEntry",
        parcels: Optional[List[Any]] = None,
        centroid_cache: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Bind an L1 typed fact to a specific entity, never a whole-DLMC class.

        Entity-level binding happens in ``build``: KG entity names are registered
        before L1 facts, so a fact with a matching name merges onto the entity's
        authoritative BSM/geometry.  This method only keeps the specific
        facility-point near-entity fallback for facilities that have a real point
        but no named KG entity yet.  Unmatched facts stay with empty source_bsms
        (typed unresolved), never a class-level parcel pool.
        """
        if entry.source_bsms:
            return
        role = str(getattr(fact, "role", "") or "")
        if role != "facility":
            return
        workspace = getattr(self.context, "workspace", None)
        if workspace is None:
            return
        if parcels is None:
            try:
                parcels = list(workspace.current_parcels() or [])
            except Exception:
                return
        if not parcels:
            return
        points: List[Any] = []
        try:
            points = list((workspace.points.get("facilities_current") or []) or [])
        except Exception:
            points = []
        from app.spatial.grounding.grounding import query_parcels_near_entity

        hit: List[str] = []
        for pt in points:
            geom = getattr(pt, "geometry", None) or {}
            text = str(getattr(pt, "facility_name", "") or "")
            if not text:
                continue
            if text in entry.canonical_name or entry.canonical_name[0] == text:
                coords = geom.get("coordinates") if isinstance(geom, dict) else None
                if coords and len(coords) >= 2:
                    hit.extend(query_parcels_near_entity(
                        parcels,
                        (float(coords[0]), float(coords[1])),
                        max_distance_m=500,
                        centroid_cache=centroid_cache,
                    ))
        bsms = [b for b in dict.fromkeys(hit) if b]
        if bsms:
            entry.source_bsms = list(dict.fromkeys([*entry.source_bsms, *bsms]))
            entry.confidence = max(entry.confidence, 0.5)
            if not entry.geometry_ref:
                entry.geometry_ref = "bundled:facility"

    @staticmethod
    def normalize_mention(mention: str) -> str:
        """Strip spatial-desc suffixes so '金田河两岸' -> '金田河'."""
        token = (mention or "").strip()
        for suffix in ("沿线", "两岸", "附近", "周边", "一带", "区域", "范围内", "域"):
            if token.endswith(suffix):
                token = token[: -len(suffix)].strip()
                break
        return token

    def _register_poi(
        self,
        pois: List[Any],
        parcels: Optional[List[Any]] = None,
        centroid_cache: Optional[Dict[str, Any]] = None,
    ) -> None:
        for p in pois:
            text = getattr(p, "text", "") or ""
            if not text:
                continue
            category = getattr(p, "category", "") or ""
            geom = getattr(p, "geometry", None) or {}  # getattr intentional: heterogeneous feature objects
            geometry_ref = None
            if isinstance(geom, dict):
                coords = geom.get("coordinates")
                if coords and len(coords) >= 2:
                    geometry_ref = f"POINT({coords[0]} {coords[1]})"
            role = "facility" if category == "现状设施点" else "landmark"
            source_bsms = self._poi_source_bsms(geom, parcels, centroid_cache)
            self._add_entry(
                PlaceEvidenceEntry(
                    canonical_name=text,
                    aliases=[],
                    entity_refs=[f"poi:{text}"],
                    entity_types=[role],
                    role=role,
                    source_bsms=source_bsms,
                    geometry_ref=geometry_ref,
                    provenance=["poi"],
                    confidence=0.5,
                )
            )

    def _poi_source_bsms(
        self,
        geometry: Any,
        parcels: Optional[List[Any]] = None,
        centroid_cache: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Bind an uploaded point to nearby real parcels, without fabrication."""
        if not isinstance(geometry, dict):
            return []
        coords = geometry.get("coordinates")
        if not coords or len(coords) < 2:
            return []
        try:
            from app.spatial.grounding.grounding import query_parcels_near_entity

            if parcels is None:
                parcels = list(self.context.current_parcels() or [])
            return query_parcels_near_entity(
                parcels,
                (float(coords[0]), float(coords[1])),
                max_distance_m=500,
                centroid_cache=centroid_cache,
            )
        except Exception:
            return []

    #: KG entity types that can carry a locatable name -> (role, entity_types)
    _KG_NAMEABLE_TYPES = {
        "facility": ("facility", ("facility",)),
        "water_body": ("water", ("water_body", "water")),
        "road": ("road", ("road",)),
        "administrative_village": ("village", ("village", "administrative_village")),
        "residential_cluster": ("village", ("village", "residential_cluster")),
        "place_ref": ("landmark", ("place_ref", "landmark")),
        "zone": ("zone", ("zone",)),
    }

    def _register_kg_names(self, kg: Any) -> None:
        graph = getattr(kg, "g", None) or getattr(kg, "graph", None)
        if graph is None:
            graph = kg
        if graph is None or not hasattr(graph, "triples"):
            logger.warning(
                "[PlaceEvidenceIndex] cannot resolve KG RDF graph; "
                "KG entity names will not be indexed"
            )
            return
        try:
            from rdflib import RDF

            from app.infrastructure.kg.ontology import PLN, GeoPredicates

            for s, _, o in graph.triples((None, RDF.type, None)):
                type_fragment = str(o).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                role_key = re.sub(r"(?<!^)(?=[A-Z])", "_", type_fragment).lower()
                mapping = self._KG_NAMEABLE_TYPES.get(role_key)
                if mapping is None:
                    continue
                name = self._first_label(graph, s)
                if not name:
                    continue
                role, entity_types = mapping
                bsm = str(graph.value(s, PLN.bsm) or "").strip()
                lon = graph.value(s, PLN.lon)
                lat = graph.value(s, PLN.lat)
                geometry_ref = None
                centroid = None
                if lon is not None and lat is not None:
                    try:
                        centroid = (float(lon), float(lat))
                        geometry_ref = (
                            f"POINT({centroid[0]} {centroid[1]})"
                        )
                    except (TypeError, ValueError):
                        centroid = None
                        geometry_ref = None
                if geometry_ref is None:
                    geometry_ref = self._kg_wkt_ref(graph, s)
                aliases: List[str] = []
                try:
                    ft = graph.value(s, PLN.facility_type)
                    if ft:
                        ft_text = str(ft).strip()
                        if ft_text and ft_text != name:
                            aliases.append(ft_text)
                except Exception:
                    pass
                relation_refs = self._kg_relation_refs(graph, s)
                confidence = 0.7 if bsm else (0.6 if centroid else 0.4)
                entry = PlaceEvidenceEntry(
                    canonical_name=name,
                    aliases=list(dict.fromkeys(aliases)),
                    entity_refs=[str(s)],
                    entity_types=list(entity_types),
                    role=role,
                    source_bsms=[bsm] if bsm else [],
                    geometry_ref=geometry_ref,
                    provenance=["kg"],
                    confidence=confidence,
                    relation_refs=relation_refs,
                )
                # A named KG facility with coordinates but no BSM is bound to
                # real bundle parcels through the same near-entity query used
                # for uploaded POIs (geometry still comes from the bundle).
                if (
                    not entry.source_bsms
                    and centroid is not None
                    and getattr(self.context, "workspace", None) is not None
                ):
                    try:
                        parcels = list(self.context.current_parcels() or [])
                        if parcels:
                            from app.spatial.grounding.grounding import (
                                build_parcel_centroid_cache,
                                query_parcels_near_entity,
                            )

                            cache = build_parcel_centroid_cache(parcels)
                            near = query_parcels_near_entity(
                                parcels,
                                centroid,
                                max_distance_m=500,
                                centroid_cache=cache,
                            )
                            if near:
                                entry.source_bsms = list(dict.fromkeys(near))
                                entry.confidence = max(entry.confidence, 0.6)
                    except Exception as exc:
                        logger.debug(
                            "[PlaceEvidenceIndex] KG facility bsm bind failed %s: %s",
                            name,
                            exc,
                        )
                self._add_entry(entry)
        except Exception:
            return

    @staticmethod
    def _kg_wkt_ref(graph: Any, subject: Any) -> Optional[str]:
        """Read a GeoSPARQL WKT geometry from a KG entity, if present."""
        try:
            from app.infrastructure.kg.ontology import GeoPredicates

            geometry_node = graph.value(subject, GeoPredicates.hasGeometry)
            if geometry_node is not None:
                wkt = graph.value(geometry_node, GeoPredicates.asWKT)
                if wkt:
                    return f"kg_wkt:{str(wkt)[:200]}"
        except Exception:
            pass
        return None

    @staticmethod
    def _kg_relation_refs(graph: Any, subject: Any) -> List[str]:
        """Collect typed relation objects so topology can inform scoring."""
        try:
            from app.infrastructure.kg.ontology import PLN, GeoPredicates, Relations

            spatial_predicates = Relations.spatial()
            relation_refs: List[str] = []
            for predicate, obj in graph.predicate_objects(subject):
                pred = str(predicate)
                if pred in {str(p) for p in spatial_predicates} or pred.startswith(str(PLN)):
                    if not str(obj).startswith("http"):
                        continue
                    relation_refs.append(f"{pred}|{obj}")
            return list(dict.fromkeys(relation_refs))[:40]
        except Exception:
            return []

    @staticmethod
    def _first_label(graph: Any, subject: Any) -> Optional[str]:
        for predicate, obj in graph.predicate_objects(subject):
            if predicate.endswith("label") or predicate.endswith("name"):
                txt = str(obj).strip()
                if txt and not txt.startswith("http"):
                    return txt
        for _, obj in graph.predicate_objects(subject):
            if hasattr(obj, "language") and obj.language is not None:
                txt = str(obj).strip()
                if txt:
                    return txt
        return None

    def _add_entry(self, entry: PlaceEvidenceEntry) -> None:
        key = _normalize(entry.canonical_name)
        existing = self._by_canonical.get(key)
        if existing is not None:
            existing.aliases = list(dict.fromkeys([*existing.aliases, *entry.aliases]))
            existing.entity_refs = list(dict.fromkeys([*existing.entity_refs, *entry.entity_refs]))
            existing.entity_types = list(dict.fromkeys([*existing.entity_types, *entry.entity_types]))
            existing.source_bsms = list(dict.fromkeys([*existing.source_bsms, *entry.source_bsms]))
            existing.provenance = list(dict.fromkeys([*existing.provenance, *entry.provenance]))
            existing.relation_refs = list(
                dict.fromkeys([*existing.relation_refs, *entry.relation_refs])
            )
            if not existing.geometry_ref and entry.geometry_ref:
                existing.geometry_ref = entry.geometry_ref
            existing.confidence = max(existing.confidence, entry.confidence)
            entry = existing
        else:
            self.entries.append(entry)
            self._by_canonical[key] = entry
        for alias in entry.aliases:
            self._by_alias.setdefault(_normalize(alias), entry)

    # ── Resolution ───────────────────────────────────────────────────

    def resolve_mention(
        self, mention: str, role: str = "unknown", hints: str = ""
    ) -> PlaceResolutionResult:
        """Resolve a mention to candidates, classify, and trace the lookup."""
        trace: List[Dict[str, Any]] = []
        norm = _normalize(mention)
        trace.append({"step": "normalize", "input": mention, "normalized": norm})

        candidates: List[PlaceResolutionCandidate] = []
        seen: Dict[str, PlaceEvidenceEntry] = {}

        exact = self._by_canonical.get(norm) or self._by_alias.get(norm)
        if exact is not None:
            seen[exact.canonical_name] = exact
            trace.append({"step": "exact", "matched": exact.canonical_name})

        # Role-aware suffix tolerance (e.g. village-suffix normalization).
        alt = self.normalize_mention(mention)
        if alt and alt != mention:
            alt_norm = _normalize(alt)
            alt_entry = self._by_canonical.get(alt_norm) or self._by_alias.get(alt_norm)
            if alt_entry is not None and alt_entry.canonical_name not in seen:
                seen[alt_entry.canonical_name] = alt_entry
                trace.append({"step": "suffix_exact", "matched": alt_entry.canonical_name})

        for key, entry in self._by_canonical.items():
            if entry.canonical_name in seen:
                continue
            if norm and norm in key:
                seen[entry.canonical_name] = entry
                trace.append({"step": "substring", "matched": entry.canonical_name})
            elif norm and key and key in norm:
                # Forward substring: a long mention such as
                # '金田河沿线农业发展区' contains the entity '金田河'.
                seen[entry.canonical_name] = entry
                trace.append({"step": "mention_contains_entity", "matched": entry.canonical_name})

        for key, entry in self._by_alias.items():
            if entry.canonical_name in seen:
                continue
            if norm and norm in key:
                seen[entry.canonical_name] = entry
                trace.append({"step": "alias_substring", "matched": entry.canonical_name})
            elif norm and key and key in norm:
                seen[entry.canonical_name] = entry
                trace.append({"step": "alias_contains_entity", "matched": entry.canonical_name})

        for entry in seen.values():
            evidence = score_candidate(mention, entry, role=role, hints=hints, context=self.context)
            score = total(evidence)
            candidates.append(
                PlaceResolutionCandidate(
                    entity_ref=""
                    if not entry.entity_refs
                    else entry.entity_refs[0],
                    entity_type=entry.entity_types[0] if entry.entity_types else entry.role,
                    canonical_name=entry.canonical_name,
                    aliases=list(entry.aliases),
                    geometry_ref=entry.geometry_ref,
                    source_bsms=list(entry.source_bsms),
                    score=round(score, 4),
                    evidence_refs=list(entry.provenance),
                    relation_refs=list(entry.relation_refs),
                    evidence=evidence,
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        trace.append({"step": "score", "candidate_count": len(candidates)})

        status: str
        selected_entity_ref: Optional[str] = None
        unresolved_reason: Optional[str] = None

        if not candidates:
            status = "unresolved"
            unresolved_reason = "no candidate matched the mention"
        else:
            top = candidates[0]
            if top.score >= _RESOLVED_THRESHOLD:
                status = "resolved"
                selected_entity_ref = top.entity_ref
            elif len(candidates) > 1 and (candidates[0].score - candidates[1].score) <= _AMBIGUOUS_GAP:
                status = "ambiguous"
                unresolved_reason = "multiple close candidates or weak evidence"
            else:
                status = "ambiguous"
                unresolved_reason = "only weak evidence; manual review required"

        return PlaceResolutionResult(
            mention=mention,
            normalized_name=norm,
            status=status,
            selected_entity_ref=selected_entity_ref,
            candidates=candidates,
            evidence_refs=[c.entity_ref for c in candidates],
            query_trace=trace,
            unresolved_reason=unresolved_reason,
            context_version=".".join(str(v) for v in self.version),
            context_fingerprint=f"{self.context.session_id}@{self.version[0]}:kg{self.version[1]}",
        )

    def candidate_bsms(self, mention: str) -> List[str]:
        """Source BSM set of the resolved candidate (used by the resolver)."""
        result = self.resolve_mention(mention)
        if result.status != "resolved" or not result.candidates:
            return []
        return list(result.candidates[0].source_bsms)


def _normalize(name: str) -> str:
    if not name:
        return ""
    cleaned = name.strip().lower()
    for suffix in ("自然村", "村"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            break
    return cleaned


__all__ = ["PlaceEvidenceIndex"]
