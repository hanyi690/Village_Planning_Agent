"""PlaceEvidenceIndex - deterministic, versioned evidence index (design §3.2).

Built once from a ``PlanningContext``: gazetteer entries, L1 typed location
facts, bundle POI annotations and (optionally) KG entity names. Resolution
(source candidate generation §4.1) is deterministic and scored over the eight
dimensions; ``candidate_bsms`` returns the source BSM set for the resolver.
"""
from __future__ import annotations

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

        for fact in getattr(context, "location_facts", []) or []:
            index._register_from_l1_fact(fact)

        workspace = getattr(context, "workspace", None)
        if workspace is not None:
            pois = (workspace.points.get("annotations_current") or []) if getattr(workspace, "points", None) else []
            index._register_poi(pois)

        kg = getattr(context, "kg", None)
        if kg is not None:
            index._register_kg_names(kg)

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

    def _register_from_l1_fact(self, fact: Any) -> None:
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
        self._bind_l1_fact_bsms(fact, entry)

    # ?? L1 fact geometry binding (design ?3.2: role-aware) ????????????

    _WATER_DLMC = frozenset({"水域", "河流水面", "湖泊水面", "坑塘水面", "沟渠"})
    _ROAD_DLMC = frozenset({"村内交通用地", "对外交通用地", "公路用地", "农村道路"})
    _FACILITY_DLMC = frozenset({"公共服务设施用地", "公共管理与公共服务用地", "科教文卫用地"})

    def _bind_l1_fact_bsms(self, fact: Any, entry: "PlaceEvidenceEntry") -> None:
        """Bind an L1 typed fact (water/road/area/facility) to real parcels.

        The L1 compiler extracts names but no geometry; this step reconnects
        the name to bundle parcels through role-specific matches (DLMC groups,
        facility points, water/road parcels) so GROUND can consume facilities,
        roads, water bodies and areas - not just natural villages.
        """
        if entry.source_bsms:
            return
        role = str(getattr(fact, "role", "") or "")
        workspace = getattr(self.context, "workspace", None)
        if workspace is None:
            return
        try:
            parcels = list(workspace.current_parcels() or [])
        except Exception:
            return
        if not parcels:
            return

        def _parcel_name(p: Any) -> str:
            return str(getattr(p, "name", "") or "")

        bsms: List[str] = []
        try:
            if role == "water":
                bsms = [str(p.bsm) for p in parcels if _parcel_name(p) in self._WATER_DLMC]
            elif role == "road":
                bsms = [str(p.bsm) for p in parcels if _parcel_name(p) in self._ROAD_DLMC]
            elif role == "area":
                target = str(getattr(fact, "normalized_name", "") or "")
                bsms = [
                    str(p.bsm) for p in parcels
                    if target and target in _parcel_name(p)
                ]
            elif role == "facility":
                bsms = [str(p.bsm) for p in parcels if _parcel_name(p) in self._FACILITY_DLMC]
                # Prefer exact facility points (annotation single-char labels).
                points = []
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
                                parcels, (float(coords[0]), float(coords[1])), max_distance_m=500,
                            ))
                if hit:
                    bsms = list(dict.fromkeys(hit))
        except Exception as exc:
            logger.debug("[PlaceEvidenceIndex] L1 fact bind failed %s: %s", entry.canonical_name, exc)
        bsms = [b for b in dict.fromkeys(bsms) if b]
        if bsms:
            entry.source_bsms = list(dict.fromkeys([*entry.source_bsms, *bsms]))
            entry.confidence = max(entry.confidence, 0.5)
            if not entry.geometry_ref:
                entry.geometry_ref = f"bundled:{role}"

    @staticmethod
    def normalize_mention(mention: str) -> str:
        """Strip spatial-desc suffixes so '金田河两岸' -> '金田河'."""
        token = (mention or "").strip()
        for suffix in ("沿线", "两岸", "附近", "周边", "一带", "区域", "范围内", "域"):
            if token.endswith(suffix):
                token = token[: -len(suffix)].strip()
                break
        return token

    def _register_poi(self, pois: List[Any]) -> None:
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
            source_bsms = self._poi_source_bsms(geom)
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

    def _poi_source_bsms(self, geometry: Any) -> List[str]:
        """Bind an uploaded point to nearby real parcels, without fabrication."""
        if not isinstance(geometry, dict):
            return []
        coords = geometry.get("coordinates")
        if not coords or len(coords) < 2:
            return []
        try:
            from app.spatial.grounding.grounding import query_parcels_near_entity

            return query_parcels_near_entity(
                self.context.current_parcels(),
                (float(coords[0]), float(coords[1])),
                max_distance_m=500,
            )
        except Exception:
            return []

    def _register_kg_names(self, kg: Any) -> None:
        graph = getattr(kg, "graph", None)
        if graph is None:
            return
        try:
            from rdflib import RDF, URIRef

            for s, _, o in graph.triples((None, RDF.type, None)):
                if str(o).endswith("residential_cluster"):
                    name = self._first_label(graph, s)
                    if name:
                        self._add_entry(
                            PlaceEvidenceEntry(
                                canonical_name=name,
                                aliases=[],
                                entity_refs=[str(s)],
                                entity_types=["village"],
                                role="village",
                                source_bsms=[],
                                geometry_ref=None,
                                provenance=["kg"],
                                confidence=0.4,
                            )
                        )
        except Exception:
            return

    @staticmethod
    def _first_label(graph: Any, subject: Any) -> Optional[str]:
        for _, predicate, obj in graph.predicate_objects(subject):
            if predicate.endswith("label") or predicate.endswith("name"):
                txt = str(obj).strip()
                if txt and not txt.startswith("http"):
                    return txt
        for _, _, obj in graph.predicate_objects(subject):
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

        # Role-aware suffix tolerance: '?????' -> '???', '?????' -> '???'.
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
