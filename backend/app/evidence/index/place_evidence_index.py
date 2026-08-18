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
        # A name/alias is not an identity key.  Keep all entries so two
        # source entities with the same label can remain independently
        # auditable and can be returned as ambiguous candidates.
        self._by_canonical: Dict[str, List[PlaceEvidenceEntry]] = {}
        self._by_alias: Dict[str, List[PlaceEvidenceEntry]] = {}

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
        # 实体级绑定（设施点/地标点 + 同坐标地块）优先；只有实体级缺失才用村锚点兜底
        if not self._entity_level_bound(entry):
            self._bind_village_anchor_bsms(fact, entry)

    # L1 fact geometry binding (design §3.2: entity-level, never class-level)

    def _entity_level_bound(self, entry: "PlaceEvidenceEntry") -> bool:
        """实体级绑定：真实 POINT 几何（非 village_anchor/bundled 占位）+ 地块。"""
        if not entry.source_bsms:
            return False
        from app.spatial.grounding.coordinate_identity import point_xy

        return point_xy(entry.geometry_ref) is not None

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
        if entry.source_bsms and self._entity_level_bound(entry):
            return
        role = str(getattr(fact, "role", "") or "")
        if role not in ("facility", "landmark"):
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
        # 设施点/地标点可来自 facilities_current 或 annotations_current；
        # 点标签可能是 text/注记/name/label/facility_name（"祠"对应"祠堂"）。
        points: List[Any] = []
        try:
            points = list((workspace.points.get("facilities_current") or []) or [])
        except Exception:
            points = []
        if not points:
            try:
                points = list((workspace.points.get("annotations_current") or []) or [])
            except Exception:
                points = []
        from app.spatial.grounding.coordinate_identity import point_xy
        from app.spatial.grounding.grounding import query_parcels_near_entity
        from app.spatial.grounding.topology import hint_tokens

        # 村 hint（如 社前村）：用于在多个同名/同类设施点里按空间拓扑消歧
        village_bsms: set = set()
        village_centroid = None
        hint_text = str(getattr(fact, "spatial_hint", "") or getattr(fact, "source_span", "") or "")
        gazetteer = getattr(self.context, "gazetteer", None)
        if gazetteer is not None:
            for token in hint_tokens(hint_text):
                entry_g = gazetteer.resolve(token, fuzzy=False) or gazetteer.resolve(token, fuzzy=True)
                if entry_g is None or not (entry_g.bsms or entry_g.centroid):
                    continue
                village_bsms.update(str(b) for b in (entry_g.bsms or []) if b)
                if village_centroid is None and entry_g.centroid:
                    village_centroid = tuple(float(x) for x in entry_g.centroid[:2])
                break

        # 收集所有匹配设施点 → (坐标, 邻近地块, 到村质心距离)
        matches: List[tuple] = []
        for pt in points:
            geom = getattr(pt, "geometry", None) or {}
            text = ""
            for attr in ("text", "name", "label", "facility_name", "注记"):
                value = getattr(pt, attr, "") if hasattr(pt, attr) else ""
                if not value and isinstance(getattr(pt, "properties", None), dict):
                    value = pt.properties.get(attr, "")
                if value:
                    text = str(value).strip()
                    break
            if not text:
                continue
            name = entry.canonical_name or ""
            if not (text in name or (name and name[0] == text) or text == name):
                continue
            coords = geom.get("coordinates") if isinstance(geom, dict) else None
            if not coords or len(coords) < 2:
                continue
            try:
                lon, lat = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                continue
            near = query_parcels_near_entity(
                parcels,
                (lon, lat),
                max_distance_m=500,
                centroid_cache=centroid_cache,
            )
            dist = float("inf")
            if village_centroid is not None:
                dist = ((lon - village_centroid[0]) ** 2 + (lat - village_centroid[1]) ** 2) ** 0.5
            matches.append(((lon, lat), list(near), dist))

        if not matches:
            return
        # 消歧：优先与 hint 村庄地块重叠的点，其次离村质心最近（同坐标=同实体）
        if village_bsms:
            matches.sort(
                key=lambda m: (
                    -len(set(m[1]) & village_bsms),
                    m[2],
                    m[0][0],
                )
            )
        best = matches[0]
        point_geometry = f"POINT({best[0][0]} {best[0][1]})"
        hit = list(best[1])
        if len(matches) > 1:
            overlap = len(set(best[1]) & village_bsms) if village_bsms else 0
            entry.provenance.append(
                f"facility_point_disambiguated:{len(matches)}pts:overlap={overlap}"
            )
        bsms = [b for b in dict.fromkeys(hit) if b]
        if bsms:
            entry.source_bsms = list(dict.fromkeys([*entry.source_bsms, *bsms]))
            entry.confidence = max(entry.confidence, 0.7)
            if point_geometry is not None:
                entry.geometry_ref = point_geometry
            provenance = f"facility_point:{point_geometry}" if point_geometry else "facility_point"
            if provenance not in entry.provenance:
                entry.provenance.append(provenance)

    def _bind_village_anchor_bsms(
        self,
        fact: Any,
        entry: "PlaceEvidenceEntry",
    ) -> None:
        """Bind a non-village L1 fact to a natural village it is reported at.

        The observation ``source_span``/``spatial_hint`` names the village
        (e.g. ``现状设施 | 供水点 | 园寨 | 5处供水点``).  When that village has
        a gazetteer entry with a BSM set (LLM-decided many-to-one cluster
        mapping or GIS name binding), the fact inherits those BSMs.  Village
        names and BSMs both come from report+KG; nothing is fabricated, and a
        fact that is itself a village role is never self-anchored.
        """
        if entry.source_bsms:
            return
        role = str(getattr(fact, "role", "") or "")
        if role == "village":
            return
        gazetteer = getattr(self.context, "gazetteer", None)
        if gazetteer is None:
            return
        span = " ".join(
            str(x)
            for x in (
                getattr(fact, "source_span", "") or "",
                getattr(fact, "spatial_hint", "") or "",
                *[str(a) for a in (getattr(fact, "aliases", None) or [])],
            )
            if x
        )
        if not span:
            return
        # Longest village name first to avoid partial-name over-anchoring.
        candidates = []
        for ge in list(getattr(gazetteer, "entries", []) or []):
            bsms = list(dict.fromkeys(getattr(ge, "bsms", None) or []))
            if not bsms:
                continue
            for vn in [
                str(getattr(ge, "name", "") or ""),
                *[str(a) for a in (getattr(ge, "aliases", None) or [])],
            ]:
                vn = vn.strip()
                if len(vn) >= 2 and vn in span:
                    candidates.append((len(vn), vn, ge))
        if not candidates:
            return
        candidates.sort(key=lambda item: -item[0])
        _, vn, ge = candidates[0]
        entry.source_bsms = list(dict.fromkeys([*entry.source_bsms, *ge.bsms]))
        entry.entity_refs.append(
            str(getattr(ge, "entity_uri", "") or f"gazetteer:{vn}")
        )
        entry.provenance.append(f"village_anchor:{vn}")
        if not entry.geometry_ref:
            entry.geometry_ref = f"village_anchor:{vn}"
        entry.confidence = max(
            entry.confidence,
            float(getattr(ge, "confidence", 0.0) or 0.0),
        )

    @staticmethod
    def normalize_mention(mention: str) -> str:
        """Strip spatial-desc suffixes so '金田河两岸' -> '金田河'."""
        token = (mention or "").strip()
        for suffix in ("沿线", "两岸", "附近", "周边", "一带", "区域", "范围内", "域"):
            if token.endswith(suffix):
                token = token[: -len(suffix)].strip()
                break
        return token

    @staticmethod
    def _point_xy(geometry_ref: Optional[str]) -> Optional[tuple]:
        """Extract (lon, lat) from a POINT(...) geometry ref.

        Delegates to ``app.spatial.grounding.coordinate_identity`` (ER
        principle: 同一坐标 = 同一实体), format-independent.
        """
        from app.spatial.grounding.coordinate_identity import point_xy

        return point_xy(geometry_ref)

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

            # General entity resolution (GER-LLM / ER pattern): a POI that
            # shares its source point with an already-registered KG entity
            # (same coordinates, same role) is the same real-world place.
            # Merge the POI's near-parcel BSMs and raw label onto that entity
            # instead of creating a duplicate name entry - no label/alias map.
            if geometry_ref:
                poi_xy = self._point_xy(geometry_ref)
                target = None
                if poi_xy is not None:
                    for e in self.entries:
                        if e.role != role:
                            continue
                        e_xy = self._point_xy(e.geometry_ref)
                        if (
                            e_xy is not None
                            and abs(e_xy[0] - poi_xy[0]) < 1e-5
                            and abs(e_xy[1] - poi_xy[1]) < 1e-5
                        ):
                            # Co-location = same real-world place (ER pattern):
                            # merge regardless of whether the target is a KG
                            # entity or another uploaded POI annotation.
                            target = e
                            break
                if target is not None:
                    target.source_bsms = list(
                        dict.fromkeys([*target.source_bsms, *source_bsms])
                    )
                    if text not in target.aliases:
                        target.aliases.append(text)
                    if f"poi:{text}" not in target.entity_refs:
                        target.entity_refs.append(f"poi:{text}")
                    if "poi" not in target.provenance:
                        target.provenance.append("poi")
                    target.confidence = max(target.confidence, 0.5)
                    continue

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

            # The builder stores point centroids under hasCentroid and full
            # geometries under hasGeometry; read both so any KG entity with a
            # locatable centre gets a geometry_ref.
            for predicate in (
                GeoPredicates.hasGeometry,
                GeoPredicates.hasCentroid,
            ):
                geometry_node = graph.value(subject, predicate)
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
        # Same coordinates remain a safe co-location identity signal.  Names
        # alone are not identity when source geometries disagree.
        coord_target = self._coordinate_merge_target(entry)
        if coord_target is not None:
            self._merge_into(coord_target, entry)
            return
        name_target = self._name_merge_target(entry)
        if name_target is not None:
            self._merge_into(name_target, entry)
            return
        key = _normalize(entry.canonical_name)
        existing_entries = self._by_canonical.get(key, [])
        merge_target = self._canonical_merge_target(entry, existing_entries)
        if merge_target is not None:
            self._merge_into(merge_target, entry)
            entry = merge_target
        else:
            self.entries.append(entry)
            self._by_canonical.setdefault(key, []).append(entry)
        for alias in entry.aliases:
            alias_key = _normalize(alias)
            if alias_key:
                aliases = self._by_alias.setdefault(alias_key, [])
                if entry not in aliases:
                    aliases.append(entry)

    @classmethod
    def _canonical_merge_target(
        cls,
        entry: PlaceEvidenceEntry,
        existing_entries: List[PlaceEvidenceEntry],
    ) -> Optional[PlaceEvidenceEntry]:
        """Return a safe same-canonical-name merge target, if one exists."""
        entry_geometry = cls._authoritative_geometry_key(entry)
        existing_geometries = {
            cls._authoritative_geometry_key(existing) for existing in existing_entries
        }
        existing_geometries.discard(None)
        # A geometry-less generic mention must not attach itself to one of
        # several already-known source entities by list order.
        if entry_geometry is None and len(existing_geometries) > 1:
            return None
        if entry_geometry is not None and existing_geometries:
            for existing in existing_entries:
                if cls._authoritative_geometry_key(existing) == entry_geometry:
                    return existing
            return None
        if entry_geometry is not None and existing_entries:
            # Do not let source arrival order decide which geometry inherits
            # an earlier generic/name-only record.
            return None
        for existing in existing_entries:
            left = cls._authoritative_geometry_key(existing)
            if left is None or entry_geometry is None:
                return existing
        return None

    @staticmethod
    def _authoritative_geometry_key(geometry_or_entry: Any) -> Optional[str]:
        """Canonicalize source WKT; coarse anchors are not source geometry."""
        geometry_ref = getattr(geometry_or_entry, "geometry_ref", geometry_or_entry)
        value = str(geometry_ref or "").strip()
        if not value or value.startswith(("village_anchor:", "bundled:")):
            return None
        if value.startswith("kg_wkt:"):
            value = value[len("kg_wkt:") :].strip()
        try:
            from shapely import wkt

            geometry = wkt.loads(value)
            if geometry.is_empty:
                return None
            return geometry.wkb_hex
        except Exception:
            return None

    def _name_merge_target(
        self, entry: PlaceEvidenceEntry
    ) -> Optional[PlaceEvidenceEntry]:
        """同角色 + 规范名/别名重叠 = 同一实体（例如 L1 fact「园寨」与
        gazetteer「园寨村」(别名 园寨) 合并，BSM/几何流入同一条目）。"""
        keys = {
            _normalize(entry.canonical_name),
            *(_normalize(str(a)) for a in entry.aliases if a),
        }
        keys.discard("")
        if not keys:
            return None
        entry_geometry = self._authoritative_geometry_key(entry)
        matching: List[PlaceEvidenceEntry] = []
        for existing in self.entries:
            if existing.role != entry.role:
                continue
            existing_keys = {
                _normalize(existing.canonical_name),
                *(_normalize(str(a)) for a in existing.aliases if a),
            }
            existing_keys.discard("")
            if existing_keys & keys:
                existing_geometry = self._authoritative_geometry_key(existing)
                if (
                    entry_geometry is not None
                    and existing_geometry is not None
                    and entry_geometry != existing_geometry
                ):
                    continue
                matching.append(existing)
        if entry_geometry is None:
            source_geometries = {
                self._authoritative_geometry_key(existing) for existing in matching
            }
            source_geometries.discard(None)
            if len(source_geometries) > 1:
                return None
        else:
            source_geometries = {
                self._authoritative_geometry_key(existing) for existing in matching
            }
            source_geometries.discard(None)
            if not source_geometries and matching:
                return None
            if source_geometries:
                matching = [
                    existing
                    for existing in matching
                    if self._authoritative_geometry_key(existing) == entry_geometry
                ]
                if not matching:
                    return None
        return matching[0] if matching else None

    def _coordinate_merge_target(
        self, entry: PlaceEvidenceEntry
    ) -> Optional[PlaceEvidenceEntry]:
        """同坐标 + 同角色 的既有条目视为同一真实实体（ER 原则）。"""
        if not entry.geometry_ref:
            return None
        try:
            from app.spatial.grounding.coordinate_identity import same_coordinate
        except Exception:  # noqa: BLE001
            return None
        for existing in self.entries:
            if existing.role != entry.role:
                continue
            if existing.geometry_ref and same_coordinate(
                existing.geometry_ref, entry.geometry_ref, tol=1e-5
            ):
                return existing
        return None

    @staticmethod
    def _merge_into(target: PlaceEvidenceEntry, source: PlaceEvidenceEntry) -> None:
        """Merge ``source`` into ``target``, accumulating evidence (ER merge)."""
        target.aliases = list(dict.fromkeys([*target.aliases, *source.aliases]))
        target.entity_refs = list(dict.fromkeys([*target.entity_refs, *source.entity_refs]))
        target.entity_types = list(dict.fromkeys([*target.entity_types, *source.entity_types]))
        target.source_bsms = list(dict.fromkeys([*target.source_bsms, *source.source_bsms]))
        target.provenance = list(dict.fromkeys([*target.provenance, *source.provenance]))
        target.relation_refs = list(
            dict.fromkeys([*target.relation_refs, *source.relation_refs])
        )
        if not target.geometry_ref and source.geometry_ref:
            target.geometry_ref = source.geometry_ref
        try:
            target.confidence = max(
                float(target.confidence or 0.0), float(source.confidence or 0.0)
            )
        except (TypeError, ValueError):
            pass

    # ── Resolution ───────────────────────────────────────────────────

    def resolve_mention(
        self, mention: str, role: str = "unknown", hints: str = ""
    ) -> PlaceResolutionResult:
        """Resolve a mention to candidates, classify, and trace the lookup."""
        trace: List[Dict[str, Any]] = []
        norm = _normalize(mention)
        trace.append({"step": "normalize", "input": mention, "normalized": norm})

        candidates: List[PlaceResolutionCandidate] = []
        seen: Dict[int, PlaceEvidenceEntry] = {}

        exact_entries = [
            *self._by_canonical.get(norm, []),
            *self._by_alias.get(norm, []),
        ]
        for exact in exact_entries:
            if id(exact) not in seen:
                seen[id(exact)] = exact
        if exact_entries:
            trace.append(
                {
                    "step": "exact",
                    "matched": list(dict.fromkeys(e.canonical_name for e in exact_entries)),
                    "candidate_count": len(seen),
                }
            )

        # Role-aware suffix tolerance (e.g. village-suffix normalization).
        alt = self.normalize_mention(mention)
        if alt and alt != mention:
            alt_norm = _normalize(alt)
            alt_entries = [
                *self._by_canonical.get(alt_norm, []),
                *self._by_alias.get(alt_norm, []),
            ]
            added = 0
            for alt_entry in alt_entries:
                if id(alt_entry) not in seen:
                    seen[id(alt_entry)] = alt_entry
                    added += 1
            if added:
                trace.append(
                    {
                        "step": "suffix_exact",
                        "matched": list(dict.fromkeys(e.canonical_name for e in alt_entries)),
                        "candidate_count": added,
                    }
                )

        for key, entries in self._by_canonical.items():
            if norm and norm in key:
                for entry in entries:
                    seen[id(entry)] = entry
                trace.append({"step": "substring", "matched": [e.canonical_name for e in entries]})
            elif norm and key and key in norm:
                # Forward substring: a long mention such as
                # '金田河沿线农业发展区' contains the entity '金田河'.
                for entry in entries:
                    seen[id(entry)] = entry
                trace.append(
                    {
                        "step": "mention_contains_entity",
                        "matched": [e.canonical_name for e in entries],
                    }
                )

        for key, entries in self._by_alias.items():
            if norm and norm in key:
                for entry in entries:
                    seen[id(entry)] = entry
                trace.append({"step": "alias_substring", "matched": [e.canonical_name for e in entries]})
            elif norm and key and key in norm:
                for entry in entries:
                    seen[id(entry)] = entry
                trace.append(
                    {
                        "step": "alias_contains_entity",
                        "matched": [e.canonical_name for e in entries],
                    }
                )

        for entry in seen.values():
            evidence = score_candidate(mention, entry, role=role, hints=hints, context=self.context)
            score = total(evidence)
            candidates.append(
                PlaceResolutionCandidate(
                    entity_ref=_preferred_entity_ref(entry),
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
            source_geometry_keys = {
                self._authoritative_geometry_key(candidate.geometry_ref)
                for candidate in candidates
            }
            source_geometry_keys.discard(None)
            if len(source_geometry_keys) > 1:
                # A generic mention cannot select one of several source
                # geometries.  Explicit source IDs (handled upstream) are
                # required to turn this into an exact feature.
                status = "ambiguous"
                unresolved_reason = "multiple source geometries for the same mention"
            elif top.score >= _RESOLVED_THRESHOLD:
                if _candidate_has_spatial(top):
                    status = "resolved"
                    selected_entity_ref = top.entity_ref
                else:
                    # 名字命中 ≠ 已解析：无 BSM/几何/KG 实体时不能算 resolved
                    status = "ambiguous"
                    unresolved_reason = "name-only match without spatial evidence"
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


def _preferred_entity_ref(entry: PlaceEvidenceEntry) -> str:
    """优先真实 KG 实体 URI（http），其次 POI/gazetteer，最后合成 l1_fact。"""
    refs = [str(r) for r in (getattr(entry, "entity_refs", None) or []) if r]
    if not refs:
        return ""
    for r in refs:
        if r.startswith("http"):
            return r
    for r in refs:
        if r.startswith(("poi:", "gazetteer:")):
            return r
    return refs[0]


def _candidate_has_spatial(candidate: PlaceResolutionCandidate) -> bool:
    """候选是否有空间引用（BSM 集 / 几何 / 真实 KG 实体）。"""
    if candidate.source_bsms:
        return True
    if candidate.geometry_ref:
        return True
    if str(candidate.entity_ref or "").startswith("http"):
        return True
    return False


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
