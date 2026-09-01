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
from app.infrastructure.evidence_runtime.index.evidence_scorer import (
    score_candidate,
    total,
)
from app.workflow.validation.l1_fact_catalog import (
    build_l1_fact_catalog,
    is_canonical_l1_fact_id,
)
from app.infrastructure.logging import get_logger
from app.contracts.ground.spatial_reference_contracts import normalize_spatial_role

logger = get_logger(__name__)

_RESOLVED_THRESHOLD = 0.8
_AMBIGUOUS_GAP = 0.15
_SCOPE_ROLES = frozenset({
    "scope",
    "village",
    "natural_village",
    "administrative_village",
    "settlement",
    "place",
    "area",
    "行政村",
    "自然村",
    "村庄",
    "聚落",
    "地点",
    "区域",
})
_DYNAMIC_SCOPE_SOURCES = frozenset({
    "amap",
    "amap_map",
    "bundle_annotation",
    "external_anchors",
    "tencent",
    "tencent_map",
    "tianditu",
    "uploaded_annotation",
})

# A role supplied by the caller is a retrieval boundary, not merely a score
# bonus.  Without this filter a village mention such as ``园寨村`` also
# recalls every hazard point whose label starts with ``园寨``; the competing
# source geometries then incorrectly turn an already resolved village scope
# into ``ambiguous``.  Unknown-role queries intentionally keep all roles so
# EvidenceGraph can return the cross-layer evidence set to its LLM selector.
_ROLE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "scope": _SCOPE_ROLES,
    "village": _SCOPE_ROLES,
    "natural_village": _SCOPE_ROLES,
    "administrative_village": _SCOPE_ROLES,
    "settlement": _SCOPE_ROLES,
    "place": _SCOPE_ROLES,
    "area": _SCOPE_ROLES,
    "facility": frozenset({"facility", "landmark"}),
    "landmark": frozenset({"landmark", "facility"}),
    "road": frozenset({"road", "axis"}),
    "axis": frozenset({"road", "axis"}),
    "water": frozenset({"water"}),
    "hazard": frozenset({"hazard"}),
    "parcel": frozenset({"parcel"}),
    "zone": frozenset({"zone", "parcel"}),
}


def _role_compatible(entry: PlaceEvidenceEntry, role: str) -> bool:
    expected = str(role or "unknown").strip().lower()
    if not expected or expected == "unknown":
        return True
    allowed = _ROLE_COMPATIBILITY.get(expected, frozenset({expected}))
    actual = str(getattr(entry, "role", "") or "").strip().lower()
    return actual in allowed


def _is_scope_role(value: Any) -> bool:
    return str(value or "").strip().casefold() in _SCOPE_ROLES


def _source_feature_identity(feature: Any, source_layer: str = "") -> str:
    raw = getattr(feature, "_raw", None)
    properties = getattr(feature, "properties", None)
    for source in (raw, properties):
        if isinstance(source, dict) and str(source.get("source_feature_id") or "").strip():
            return str(source["source_feature_id"]).strip()
    source_id = str(getattr(feature, "source_feature_id", "") or "").strip()
    if source_id:
        return source_id
    bsm = str(getattr(feature, "bsm", "") or "").strip()
    return f"bundle:{source_layer}:{bsm}" if source_layer and bsm else ""


def _scope_mentions_for_fact(fact: Any) -> list[Any]:
    """Read only the typed L1 scope objects at the retrieval boundary."""

    raw = getattr(fact, "scopes", None)
    if raw in (None, "", []):
        raw = getattr(fact, "scope_mentions", None)
    if raw in (None, "", []):
        raw = [
            {"name": value, "role": "natural_village"}
            for value in (getattr(fact, "village_scopes", None) or [])
        ]
        raw.extend(
            {"name": value, "role": "place"}
            for value in (getattr(fact, "place_scopes", None) or [])
        )
    if isinstance(raw, str):
        return []
    return list(raw or [])


def _scope_value(scope: Any, field: str, default: str = "") -> str:
    if isinstance(scope, dict):
        return str(scope.get(field, default) or "").strip()
    return str(getattr(scope, field, default) or "").strip()


def _fact_scope_names(fact: Any) -> list[str]:
    return list(dict.fromkeys(
        _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
        for scope in _scope_mentions_for_fact(fact)
        if _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
    ))


def _is_dynamic_gazetteer_scope(entry: Any) -> bool:
    """Allow only source-backed uploaded/external scope anchors.

    KG clusters, persisted gazetteer rows, and L1 enrichment rows are legacy
    scope materializations.  They must not re-enter retrieval as a natural
    village identity; the typed L1 mention is the semantic source of truth.
    """

    source = str(getattr(entry, "source", "") or "").strip().casefold()
    entity_uri = str(getattr(entry, "entity_uri", "") or "").strip().casefold()
    return (
        source in _DYNAMIC_SCOPE_SOURCES
        or entity_uri.startswith("pln:external_")
        or "external_natural_village" in entity_uri
    )


def _context_l1_items(context: Any) -> list[Any]:
    """Combine canonical L1 mentions and typed records without duplicates."""

    collections = [
        getattr(context, "location_mentions", None)
        or getattr(context, "location_facts", None)
        or [],
        getattr(context, "l1_fact_records", None) or [],
    ]
    result: list[Any] = []
    seen_objects: set[int] = set()
    seen_fact_ids: set[str] = set()
    for collection in collections:
        for item in collection:
            object_id = id(item)
            fact_id = str(getattr(item, "fact_id", "") or "").strip()
            if object_id in seen_objects or (fact_id and fact_id in seen_fact_ids):
                continue
            seen_objects.add(object_id)
            if fact_id:
                seen_fact_ids.add(fact_id)
            result.append(item)
    return result


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
        self._name_ngrams: Dict[str, set[tuple[str, str]]] = {}
        self._short_name_keys: set[tuple[str, str]] = set()
        self._identity_index: Dict[
            tuple[str, str], PlaceEvidenceEntry
        ] = {}
        self._coordinate_index: Dict[
            tuple[str, int, int], List[tuple[float, float, PlaceEvidenceEntry]]
        ] = {}
        self._coordinate_cache: Dict[
            str, tuple[float, float] | None
        ] = {}
        self.semantic_scopes: list[Any] = []
        self.source_semantic_decisions: dict[str, Any] = {}
        # ``None`` means that the injected context does not expose an L1
        # snapshot (some narrow adapters intentionally do not).  Once a
        # snapshot is present, only its canonical IDs may cross the evidence
        # graph boundary; a canonical-looking ID from a semantic overlay is
        # not evidence merely because it has the right prefix.
        self._allowed_l1_fact_ids: frozenset[str] | None = None
        # Shapes are parsed lazily only for spatial joins.  This avoids
        # rebuilding a Shapely object for every POI while keeping the cache
        # session-scoped and reclaimable with the index.
        self._parcel_geometry_cache: Dict[str, Any] = {}
        self._parcel_spatial_index: Any = None
        # Build-time ER key only; coordinates are never exposed in entries.
        self._point_identity_index: Dict[tuple[str, float, float], PlaceEvidenceEntry] = {}

    @classmethod
    def build(
        cls,
        context: Any,
        semantic_decisions: dict[str, Any] | None = None,
    ) -> "PlaceEvidenceIndex":
        """Construct the index from a ``PlanningContext``."""
        version = (
            int(getattr(context, "version", 0) or 0),
            int(getattr(context, "kg_version", 0) or 0),
        )
        index = cls(context=context, version=version)
        if hasattr(context, "l1_fact_records"):
            index._allowed_l1_fact_ids = frozenset(
                build_l1_fact_catalog(
                    getattr(context, "l1_fact_records", None) or []
                ).usable_allowed_fact_ids
            )
        index.source_semantic_decisions = dict(
            semantic_decisions
            or getattr(context, "source_semantic_decisions", None)
            or {}
        )

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
            try:
                parcels = list(workspace.current_parcels() or [])
            except Exception:
                parcels = list(
                    (getattr(workspace, "polygons", {}) or {}).get("landuse_current") or []
                )
        from app.spatial.grounding.grounding import (
            build_parcel_centroid_cache,
            build_parcel_spatial_index,
        )

        centroid_cache = build_parcel_centroid_cache(parcels)
        index._parcel_spatial_index = build_parcel_spatial_index(parcels)
        l1_items = _context_l1_items(context)
        semantic_scope_items = list(
            getattr(context, "l1_fact_records", None) or []
        ) or l1_items
        for fact in l1_items:
            index._register_l1_scope_mentions(fact)
            index._register_from_l1_fact(
                fact, parcels, centroid_cache, index._parcel_spatial_index
            )
        try:
            from app.infrastructure.evidence_runtime.l1_scope import build_l1_semantic_scopes

            index.semantic_scopes = build_l1_semantic_scopes(
                semantic_scope_items,
                session_id=str(getattr(context, "session_id", "") or ""),
                l1_snapshot_ref=str(getattr(context, "l1_snapshot_ref", "") or ""),
            )
        except Exception as exc:
            logger.debug("[PlaceEvidenceIndex] L1 scope build skipped: %s", exc)

        workspace = getattr(context, "workspace", None)
        if workspace is not None:
            points = getattr(workspace, "points", None)
            if points is not None:
                for layer_name in (
                    "annotations_current",
                    "facilities_current",
                    "hazard_points",
                    "geological_hazard_points",
                    "geological_hazard_point",
                ):
                    index._register_poi(
                        points.get(layer_name) or [],
                        parcels,
                        centroid_cache,
                        source_layer=layer_name,
                        spatial_index=index._parcel_spatial_index,
                    )
            index._register_named_bundle_features(
                workspace,
                parcels=parcels,
                spatial_index=index._parcel_spatial_index,
            )
        index._register_data_catalog_features()

        return index

    def _filter_l1_fact_refs(self, values: Any) -> list[str]:
        """Keep only current-snapshot L1 identities for candidate lineage."""

        refs = list(dict.fromkeys(
            str(value).strip()
            for value in (values or [])
            if is_canonical_l1_fact_id(value)
        ))
        if self._allowed_l1_fact_ids is None:
            return refs
        return [value for value in refs if value in self._allowed_l1_fact_ids]

    # ── Registration ─────────────────────────────────────────────────

    def _register_data_catalog_features(self) -> None:
        """Index generic DATA features for name/alias recall.

        The catalog entry is deliberately an evidence candidate, not a
        business entity classification.  Geometry stays behind ``resource_ref``
        and is loaded later by GROUND; unknown roles remain ``unknown``.
        """

        catalog = getattr(self.context, "data_resource_catalog", None)
        snapshot = getattr(catalog, "snapshot", None)
        if snapshot is None:
            return
        from app.data.admission import assert_current_world_catalog

        assert_current_world_catalog(snapshot)
        for feature in list(getattr(snapshot, "features", ()) or ())[:10000]:
            attrs = getattr(feature, "raw_attributes", {}) or {}
            labels = [
                str(value).strip()
                for key, value in attrs.items()
                if str(key).casefold() in {
                    "name", "label", "title", "alias", "road_name", "facility_name",
                    "water_name", "text",
                }
                and str(value).strip()
            ]
            canonical = labels[0] if labels else str(feature.layer_ref or feature.source_feature_ref).strip()
            if not canonical:
                continue
            role = str(
                attrs.get("role")
                or attrs.get("entity_role")
                or attrs.get("entity_type")
                or "unknown"
            ).strip().casefold() or "unknown"
            resource_ref = f"resource:{feature.dataset_ref}:{feature.source_feature_ref}"
            self._add_entry(
                PlaceEvidenceEntry(
                    canonical_name=canonical,
                    aliases=list(dict.fromkeys(labels[1:])),
                    entity_refs=[],
                    entity_types=[role] if role != "unknown" else [],
                    role=role,
                    source_feature_id=str(feature.source_feature_ref),
                    source_layer=str(feature.layer_ref or ""),
                    geometry_ref=resource_ref,
                    provenance=[
                        f"data:{feature.dataset_ref}",
                        f"data_snapshot:{getattr(snapshot, 'snapshot_id', '')}",
                    ],
                    confidence=0.65 if labels else 0.45,
                    bundle_snapshot_digest=str(getattr(snapshot, "digest", "") or ""),
                )
            )

    def _register_named_bundle_features(
        self,
        workspace: Any,
        *,
        parcels: Optional[List[Any]] = None,
        spatial_index: Any = None,
    ) -> None:
        """Index bounded named line/polygon features from the bundle.

        Facilities were historically registered from point layers only.  A
        road or water query therefore depended on a matching KG entity even
        when the authoritative bundle feature was already present.  Register
        non-parcel features here: indexing every land-use polygon would waste
        memory and would turn unlabeled parcels into semantic candidates.
        Unnamed roads/water features are retained with their role as a weak
        bounded scope label, so an explicit ``道路``/``水体`` query can return
        ambiguous bundle identities instead of dropping real geometries.
        """
        layer_specs = (
            ("lines", ("roads_current", "current_road", "transport"), "road"),
            ("polygons", ("water_current", "water", "water_bodies"), "water"),
        )
        for container_name, layer_names, role in layer_specs:
            container = getattr(workspace, container_name, None)
            if container is None or not hasattr(container, "get"):
                continue
            for layer_name in layer_names:
                for feature in list(container.get(layer_name) or []):
                    raw_label = ""
                    for attr in (
                        "text", "name", "label", "road_name", "water_name",
                        "facility_name", "category",
                    ):
                        value = getattr(feature, attr, "")
                        if not value and isinstance(getattr(feature, "properties", None), dict):
                            value = feature.properties.get(attr, "")
                        if str(value or "").strip():
                            raw_label = str(value).strip()
                            break
                    bsm = str(getattr(feature, "bsm", "") or "").strip()
                    if not bsm:
                        continue
                    geometry_ref = f"bundle://feature/{bsm}"
                    raw = getattr(feature, "_raw", {}) or {}
                    source_feature_id = _source_feature_identity(feature, role)
                    semantic_label, semantic_aliases, semantic_fact_refs = (
                        self._source_semantic_overlay(source_feature_id, raw_label)
                    )
                    canonical_name = semantic_label or raw_label or role
                    related_parcel_bsms = self._feature_related_parcel_bsms(
                        feature,
                        parcels=parcels,
                        spatial_index=spatial_index,
                    )
                    self._add_entry(
                        PlaceEvidenceEntry(
                            canonical_name=canonical_name,
                            aliases=semantic_aliases,
                            entity_refs=[f"bundle:{role}:{bsm}"],
                            entity_types=[role],
                            role=role,
                            feature_bsm=bsm,
                            source_feature_id=source_feature_id,
                            source_layer=layer_name,
                            source_bsm=bsm,
                            source_bsms=[bsm],
                            related_parcel_bsms=related_parcel_bsms,
                            geometry_ref=geometry_ref,
                            provenance=[
                                f"bundle:{layer_name}",
                                *(
                                    ["source_semantic:accepted"]
                                    if semantic_label
                                    else []
                                ),
                            ],
                            l1_fact_refs=semantic_fact_refs,
                            l1_snapshot_ref=str(
                                getattr(self.context, "l1_snapshot_ref", "") or ""
                            ),
                            confidence=(
                                0.95
                                if semantic_label
                                else 0.8
                                if raw_label
                                else 0.6
                            ),
                            bundle_snapshot_digest=str(
                                getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                                or ""
                            ),
                        )
                    )

    def _source_semantic_overlay(
        self,
        source_feature_id: str,
        raw_label: str,
    ) -> tuple[str, list[str], list[str]]:
        """Return an accepted snapshot-local semantic overlay only.

        Raw labels remain aliases and never become a verified semantic type.
        An unresolved/ambiguous decision contributes nothing to identity.
        """
        decision = self.source_semantic_decisions.get(source_feature_id)
        if decision is None:
            return "", ([raw_label] if raw_label else []), []
        status = (
            str(getattr(decision, "status", "") or "").strip()
            if not isinstance(decision, dict)
            else str(decision.get("status", "") or "").strip()
        )
        if status != "accepted":
            return "", ([raw_label] if raw_label else []), []
        semantic_label = (
            str(getattr(decision, "semantic_type", "") or "").strip()
            if not isinstance(decision, dict)
            else str(decision.get("semantic_type", "") or "").strip()
        )
        if not semantic_label:
            return "", ([raw_label] if raw_label else []), []
        fact_refs = (
            list(getattr(decision, "supporting_fact_refs", []) or [])
            if not isinstance(decision, dict)
            else list(decision.get("supporting_fact_refs", []) or [])
        )
        aliases = [raw_label] if raw_label and raw_label != semantic_label else []
        return semantic_label, list(dict.fromkeys(aliases)), self._filter_l1_fact_refs(
            fact_refs
        )

    @staticmethod
    def _feature_related_parcel_bsms(
        feature: Any,
        *,
        parcels: Optional[List[Any]],
        spatial_index: Any,
    ) -> List[str]:
        """Project a named bundle feature to intersecting parcel BSM refs.

        This is a build-time topology join.  The evidence entry receives only
        parcel identities, while authoritative feature and parcel geometry
        remain in the bundle for GROUND and later execution stages.
        """
        if not parcels or spatial_index is None:
            return []
        raw_geometry = getattr(feature, "geometry", None)
        if raw_geometry is None and isinstance(getattr(feature, "properties", None), dict):
            raw_geometry = feature.properties.get("geometry")
        try:
            from shapely.geometry import shape

            geometry = shape(raw_geometry) if isinstance(raw_geometry, dict) else raw_geometry
            if geometry is None or geometry.is_empty:
                return []
            query_geometry = getattr(spatial_index, "query_geometry", None)
            if not callable(query_geometry):
                return []
            return list(dict.fromkeys(str(value) for value in query_geometry(geometry) if str(value).strip()))
        except Exception:
            return []

    def query_parcel_bsms_in_bbox(
        self,
        bbox: tuple[float, float, float, float],
    ) -> List[str]:
        """Return bundle parcel BSMs intersecting a coarse query bbox."""
        spatial_index = self._parcel_spatial_index
        if spatial_index is None or not hasattr(spatial_index, "query_bbox"):
            return []
        try:
            return list(
                dict.fromkeys(
                    str(value)
                    for value in spatial_index.query_bbox(bbox)
                    if str(value).strip()
                )
            )
        except Exception:
            return []

    def _register_from_gazetteer(self, entry: Any) -> None:
        name = getattr(entry, "name", "") or ""
        if not name:
            return
        bsms = [str(b) for b in (getattr(entry, "bsms", None) or [])]
        entity_uri = getattr(entry, "entity_uri", "") or name
        centroid = getattr(entry, "centroid", None)
        geometry_ref = None
        aliases = [str(a) for a in (getattr(entry, "aliases", None) or []) if a]
        role, entity_types = self._gazetteer_role(entry)
        if role in _SCOPE_ROLES and not _is_dynamic_gazetteer_scope(entry):
            return
        self._add_entry(
            PlaceEvidenceEntry(
                canonical_name=name,
                aliases=aliases,
                entity_refs=[entity_uri],
                entity_types=entity_types,
                role=role,
                source_bsms=bsms,
                geometry_ref=geometry_ref,
                provenance=[
                    "gazetteer",
                    f"gazetteer_source:{str(getattr(entry, 'source', '') or 'unknown').strip()}",
                ],
                confidence=float(getattr(entry, "confidence", 0.0) or 0.0),
            )
        )

    @staticmethod
    def _gazetteer_role(entry: Any) -> tuple[str, list[str]]:
        """Dispatch a gazetteer entry's role from its source and anchor URI kind."""
        source = str(getattr(entry, "source", "") or "")
        entity_uri = str(getattr(entry, "entity_uri", "") or "")
        for prefix, role in (
            ("pln:water_body:", "water"),
            ("pln:road:", "road"),
            ("pln:facility:", "facility"),
            ("pln:landmark:", "landmark"),
            ("pln:area:", "zone"),
        ):
            if entity_uri.startswith(prefix):
                return role, [role]
        if source == "kg_facility":
            return "facility", ["facility"]
        if source == "water_cluster_map":
            return "water", ["water"]
        if source in _DYNAMIC_SCOPE_SOURCES or entity_uri.startswith("pln:external_"):
            return "scope", ["scope"]
        if source == "l1_instruction":
            uri = str(getattr(entry, "entity_uri", "") or "")
            for kind in ("facility", "project", "zone", "landmark"):
                if f"anchor_{kind}_" in uri:
                    return kind, [kind]
            return "scope", ["scope"]
        return "scope", ["scope"]

    def _register_l1_scope_mentions(self, fact: Any) -> None:
        """Index typed scope names as semantic evidence without geometry."""

        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        source_refs = [
            str(value).strip()
            for value in (getattr(fact, "source_refs", None) or [])
            if str(value).strip()
        ]
        l1_fact_refs = self._filter_l1_fact_refs([fact_id, *source_refs])
        l1_snapshot_ref = str(getattr(self.context, "l1_snapshot_ref", "") or "")
        bundle_digest = str(
            getattr(getattr(self.context, "data_snapshot", None), "digest", "")
            or ""
        )
        for scope in _scope_mentions_for_fact(fact):
            name = _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
            if not name:
                continue
            role = normalize_spatial_role(_scope_value(scope, "role", "unknown"))
            if role in {"", "unknown", "target"}:
                role = "scope"
            aliases = [
                _scope_value(scope, "name"),
                *(
                    [str(value).strip() for value in getattr(scope, "aliases", []) if str(value).strip()]
                    if not isinstance(scope, dict)
                    else [str(value).strip() for value in (scope.get("aliases") or []) if str(value).strip()]
                ),
            ]
            aliases = list(dict.fromkeys(value for value in aliases if value))
            scope_refs = [
                *(
                    [str(value).strip() for value in getattr(scope, "source_refs", []) if str(value).strip()]
                    if not isinstance(scope, dict)
                    else [str(value).strip() for value in (scope.get("source_refs") or []) if str(value).strip()]
                ),
                *(
                    [str(value).strip() for value in getattr(scope, "source_segment_ids", []) if str(value).strip()]
                    if not isinstance(scope, dict)
                    else [str(value).strip() for value in (scope.get("source_segment_ids") or []) if str(value).strip()]
                ),
            ]
            relation = _scope_value(scope, "relation_to_target", "located_in") or "located_in"
            provenance = [
                "l1_scope",
                f"l1_scope_relation:{relation}",
                *(f"l1_scope_source:{value}" for value in scope_refs),
            ]
            self._add_entry(
                PlaceEvidenceEntry(
                    canonical_name=name,
                    aliases=aliases,
                    entity_types=[role],
                    role=role,
                    provenance=list(dict.fromkeys(provenance)),
                    l1_fact_refs=l1_fact_refs,
                    l1_snapshot_ref=l1_snapshot_ref,
                    bundle_snapshot_digest=bundle_digest,
                    confidence=float(_scope_value(scope, "confidence") or 0.0),
                )
            )

    def scope_bsms_for_names(self, names: list[str] | tuple[str, ...]) -> set[str]:
        """Return BSMs from explicit L1/external scope evidence only."""

        keys = {
            _normalize(value)
            for value in names
            if _normalize(value)
        }
        if not keys:
            return set()
        bsms: set[str] = set()
        for entry in self.entries:
            if not any(
                _normalize(value) in keys
                for value in (
                    getattr(entry, "canonical_name", ""),
                    *(getattr(entry, "aliases", None) or []),
                )
            ):
                continue
            provenance = {str(value) for value in (getattr(entry, "provenance", None) or [])}
            if "l1_scope" not in provenance and not any(
                value.startswith("gazetteer_source:")
                and value.split(":", 1)[1] in _DYNAMIC_SCOPE_SOURCES
                for value in provenance
            ):
                continue
            bsms.update(
                str(value).strip()
                for value in (getattr(entry, "source_bsms", None) or [])
                if str(value).strip()
            )
        return bsms

    def _register_from_l1_fact(
        self,
        fact: Any,
        parcels: Optional[List[Any]] = None,
        centroid_cache: Optional[Dict[str, Any]] = None,
        spatial_index: Any = None,
    ) -> None:
        attributes = getattr(fact, "attributes", None) or {}
        if not isinstance(attributes, dict):
            attributes = {}
        norm = str(
            getattr(fact, "normalized_name", "")
            or attributes.get("normalized_name", "")
            or ""
        ).strip()
        mention = str(
            norm
            or getattr(fact, "mention", "")
            or attributes.get("mention", "")
            or getattr(fact, "subject_scope", "")
            or ""
        ).strip()
        name = norm or mention
        if not name:
            return
        role = normalize_spatial_role(str(
            getattr(fact, "role", "")
            or attributes.get("role", "")
            or getattr(fact, "semantic_type", "")
            or "unknown"
        ).strip())
        if role not in {
            "facility",
            "landmark",
            "road",
            "water",
            "parcel",
            "zone",
            "village",
            "natural_village",
            "administrative_village",
            "scope",
            "settlement",
            "place",
            "area",
            "行政村",
            "自然村",
            "村庄",
            "聚落",
            "地点",
            "区域",
            "unknown",
        } and not any(
            str(attributes.get(key, "") or "").strip()
            for key in ("location", "spatial_hint", "village", "settlement")
        ):
            return
        aliases = [str(a) for a in (getattr(fact, "aliases", None) or []) if a]
        aliases.extend(
            str(attributes.get(key, "")).strip()
            for key in ("name", "display_name")
            if str(attributes.get(key, "") or "").strip()
        )
        if name not in aliases:
            aliases.append(name)
        source_refs = [
            str(value).strip()
            for value in (getattr(fact, "source_refs", None) or [])
            if str(value).strip()
        ]
        source_refs.extend(
            str(getattr(fact, attribute, "") or "").strip()
            for attribute in ("source_report_ref", "source_snapshot_ref")
            if str(getattr(fact, attribute, "") or "").strip()
        )
        source_refs = list(dict.fromkeys(source_refs))
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        l1_fact_refs = self._filter_l1_fact_refs([*source_refs, fact_id])
        entry = PlaceEvidenceEntry(
            canonical_name=name,
            aliases=aliases,
            entity_refs=[],
            entity_types=[role],
            role=role,
            source_bsms=[],
            geometry_ref=None,
            provenance=["l1_fact"],
            l1_fact_refs=list(dict.fromkeys(l1_fact_refs)),
            l1_snapshot_ref=str(getattr(self.context, "l1_snapshot_ref", "") or ""),
            bundle_snapshot_digest=str(
                getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                or ""
            ),
            confidence=float(getattr(fact, "confidence", 0.0) or 0.0),
        )
        if self._register_l1_source_features(
            fact, entry, parcels, spatial_index
        ):
            return
        self._bind_l1_fact_bsms(
            fact, entry, parcels, centroid_cache, spatial_index
        )
        # Register only after all deterministic L1 bindings are complete so
        # the normal same-coordinate/entity merge can see the final geometry.
        self._add_entry(entry)

    def _register_l1_source_features(
        self,
        fact: Any,
        entry: "PlaceEvidenceEntry",
        parcels: Optional[List[Any]],
        spatial_index: Any,
    ) -> bool:
        """Join typed L1 source IDs to Bundle/KG identities before name recall.

        ``L1Fact.source_feature_ids`` is an exact provenance binding.  It may
        identify points, lines, polygons, or a bounded collection of source
        features.  The index stores only BSM/ref identity and nearby parcel
        IDs; authoritative geometry remains in the Bundle.  If an explicit ID
        cannot be found, retain an unresolved L1 entry and do not fall back to
        name/coordinate matching, because that could bind the fact to a
        different real-world feature.
        """
        source_ids = list(dict.fromkeys(
            str(value).strip()
            for value in (getattr(fact, "source_feature_ids", None) or [])
            if str(value).strip()
        ))
        if not source_ids:
            return False

        workspace = getattr(self.context, "workspace", None)
        matches: list[tuple[str, str, str, list[str]]] = []
        if workspace is not None:
            from app.data.model.layer_registry import get_planned_output_bundle_keys

            planned_output_layers = get_planned_output_bundle_keys()
            for group_name in ("points", "lines", "polygons"):
                group = getattr(workspace, group_name, None)
                if group is None or not callable(getattr(group, "get", None)):
                    continue
                layer_names = (
                    list(group.keys())
                    if callable(getattr(group, "keys", None))
                    else {
                        "points": (
                            "annotations_current",
                            "facilities_current",
                            "hazard_points",
                            "geological_hazard_points",
                        ),
                        "lines": (
                            "roads_current",
                            "current_road",
                            "roads_planned",
                            "planned_road",
                        ),
                        "polygons": (
                            "landuse_current",
                            "water_bodies",
                            "water_current",
                            "planning_scope",
                        ),
                    }[group_name]
                )
                for layer_name in layer_names:
                    if str(layer_name) in planned_output_layers:
                        continue
                    for feature in list(group.get(layer_name) or []):
                        raw = getattr(feature, "_raw", {}) or {}
                        raw_id = str(
                            raw.get("source_feature_id")
                            if isinstance(raw, dict)
                            else ""
                        ).strip()
                        if not raw_id or raw_id not in source_ids:
                            continue
                        feature_bsm = str(getattr(feature, "bsm", "") or "").strip()
                        if not feature_bsm:
                            continue
                        related = self._feature_related_parcel_bsms(
                            feature,
                            parcels=parcels,
                            spatial_index=spatial_index,
                        )
                        matches.append((raw_id, str(layer_name), feature_bsm, related))

        kg = getattr(self.context, "kg", None)
        bundle_feature_finder = getattr(workspace, "find_feature_by_bsm", None)
        if kg is not None and callable(getattr(kg, "find_entities", None)):
            for source_id in source_ids:
                try:
                    entities = kg.find_entities(
                        source_feature_id=source_id,
                        limit=50,
                    ) or []
                except Exception:
                    entities = []
                for entity in entities:
                    feature_bsm = str(getattr(entity, "feature_bsm", "") or "").strip()
                    if not feature_bsm or not callable(bundle_feature_finder):
                        continue
                    try:
                        bundle_match = bundle_feature_finder(feature_bsm)
                    except Exception:
                        bundle_match = None
                    if not bundle_match or len(bundle_match) < 3:
                        continue
                    source_layer = str(bundle_match[0] or "").strip()
                    bundle_feature = bundle_match[2]
                    bundle_raw = getattr(bundle_feature, "_raw", {}) or {}
                    bundle_source_id = str(
                        bundle_raw.get("source_feature_id")
                        if isinstance(bundle_raw, dict)
                        else ""
                    ).strip()
                    if bundle_source_id != source_id:
                        continue
                    related = self._feature_related_parcel_bsms(
                        bundle_feature,
                        parcels=parcels,
                        spatial_index=spatial_index,
                    )
                    matches.append((
                        source_id,
                        source_layer or str(getattr(entity, "source_layer", "") or "kg"),
                        feature_bsm,
                        related,
                    ))

        unique_matches: list[tuple[str, str, str, list[str]]] = []
        seen_matches: set[tuple[str, str]] = set()
        for match in matches:
            key = (match[0], match[2])
            if key in seen_matches:
                continue
            seen_matches.add(key)
            unique_matches.append(match)

        matched_ids = {item[0] for item in unique_matches}
        unresolved_ids = [source_id for source_id in source_ids if source_id not in matched_ids]
        if not unique_matches:
            entry.provenance.extend(
                f"l1_source_feature_unresolved:{source_id}"
                for source_id in source_ids
            )
            self._add_entry(entry)
            return True

        for source_id, source_layer, feature_bsm, related_parcels in unique_matches:
            bound = entry.model_copy(deep=True)
            bound.entity_refs = list(dict.fromkeys([
                *bound.entity_refs,
                f"l1_source_feature:{source_id}",
            ]))
            bound.feature_bsm = feature_bsm
            bound.source_bsm = feature_bsm
            bound.source_layer = source_layer or None
            bound.source_bsms = list(dict.fromkeys(related_parcels))
            bound.related_parcel_bsms = list(dict.fromkeys(related_parcels))
            bound.geometry_ref = f"bundle://feature/{feature_bsm}"
            bound.provenance.append(f"l1_source_feature:{source_id}")
            bound.provenance.extend(
                f"l1_source_feature_unresolved:{item}"
                for item in unresolved_ids
            )
            self._add_entry(bound)
        return True

    # L1 fact geometry binding (design §3.2: entity-level, never class-level)

    def _entity_level_bound(self, entry: "PlaceEvidenceEntry") -> bool:
        """实体级绑定：bundle feature identity + nearby parcel evidence."""
        return bool(
            entry.source_bsms
            and (
                str(entry.feature_bsm or "").strip()
                or str(entry.source_bsm or "").strip()
            )
        )

    def _bind_l1_fact_bsms(
        self,
        fact: Any,
        entry: "PlaceEvidenceEntry",
        parcels: Optional[List[Any]] = None,
        centroid_cache: Optional[Dict[str, Any]] = None,
        spatial_index: Any = None,
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
        attributes = getattr(fact, "attributes", None) or {}
        if not isinstance(attributes, dict):
            attributes = {}
        role = str(
            getattr(fact, "role", "")
            or attributes.get("role", "")
            or getattr(fact, "semantic_type", "")
            or ""
        ).strip()
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
        # 设施点/地标点可来自 facilities_current 或 annotations_current。
        points: List[tuple[Any, str]] = []
        for layer_name in ("facilities_current", "annotations_current"):
            try:
                points.extend(
                    (point, layer_name)
                    for point in list((workspace.points.get(layer_name) or []) or [])
                )
            except Exception:
                continue
        from app.spatial.grounding.grounding import query_parcels_near_entity

        scope_names = _fact_scope_names(fact)
        scope_bsms = self.scope_bsms_for_names(scope_names)

        # 收集所有匹配设施点 → (坐标, 邻近地块, feature_bsm, layer)
        matches: List[tuple] = []
        for pt, point_source_layer in points:
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
            raw = getattr(pt, "_raw", {}) or {}
            source_feature_id = _source_feature_identity(pt, "facility")
            decision = self.source_semantic_decisions.get(source_feature_id)
            decision_status = (
                getattr(decision, "status", "")
                if decision is not None and not isinstance(decision, dict)
                else str((decision or {}).get("status", ""))
            )
            decision_type = (
                getattr(decision, "semantic_type", "")
                if decision is not None and not isinstance(decision, dict)
                else str((decision or {}).get("semantic_type", ""))
            )
            exact_raw_match = text == name
            accepted_semantic_match = (
                decision_status == "accepted" and decision_type == name
            )
            if not (exact_raw_match or accepted_semantic_match):
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
                geometry_cache=self._parcel_geometry_cache,
                spatial_index=spatial_index,
            )
            point_bsm = str(getattr(pt, "bsm", "") or "").strip() or None
            matches.append(((lon, lat), list(near), point_bsm, point_source_layer))

        if not matches:
            return
        # 多个同名点只有在显式 scope BSM 能唯一筛出一个时才绑定。
        if len(matches) > 1:
            if not scope_bsms:
                return
            matches.sort(key=lambda m: (-len(set(m[1]) & scope_bsms), m[0][0], m[0][1]))
            best_overlap = len(set(matches[0][1]) & scope_bsms)
            next_overlap = len(set(matches[1][1]) & scope_bsms)
            if best_overlap <= 0 or best_overlap == next_overlap:
                return
        best = matches[0]
        hit = list(best[1])
        if len(matches) > 1:
            overlap = len(set(best[1]) & scope_bsms)
            entry.provenance.append(
                f"facility_point_disambiguated:{len(matches)}pts:overlap={overlap}"
            )
        point_bsm = best[2]
        point_source_layer = best[3]
        if point_bsm:
            entry.feature_bsm = point_bsm
            entry.source_bsm = point_bsm
            entry.source_layer = point_source_layer or None
        bsms = [b for b in dict.fromkeys(hit) if b]
        if point_bsm:
            entry.geometry_ref = f"bundle://feature/{point_bsm}"
        provenance = "facility_point:bundle" if point_bsm else "facility_point:unbound"
        if provenance not in entry.provenance:
            entry.provenance.append(provenance)
        if bsms:
            entry.source_bsms = list(dict.fromkeys([*entry.source_bsms, *bsms]))
            entry.related_parcel_bsms = list(
                dict.fromkeys([*entry.related_parcel_bsms, *bsms])
            )
            entry.confidence = max(entry.confidence, 0.7)

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
        return
        role = str(getattr(fact, "role", "") or "")
        if role == "village":
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
        explicit_village = ""
        try:
            from app.spatial.grounding.topology import hint_tokens

            explicit_village = next(
                (
                    token
                    for token in hint_tokens(
                        str(getattr(fact, "spatial_hint", "") or "")
                    )
                    if token and "村" in token
                ),
                "",
            )
        except Exception:
            explicit_village = ""
        gazetteer = getattr(self.context, "gazetteer", None)
        if gazetteer is None:
            # An explicit L1 spatial hint is a semantic scope even when the
            # gazetteer is unavailable.  It does not create anchor geometry
            # or BSMs; it only lets a later exact bundle/KG candidate inherit
            # the village scope.
            context_village = str(
                getattr(self.context, "village_name", "") or ""
            ).strip()
            scope = explicit_village or (
                context_village if context_village and context_village in span else ""
            )
            if scope:
                entry.provenance.append(f"village_anchor:{scope}")
                entry.confidence = max(entry.confidence, 0.6)
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
            context_village = str(
                getattr(self.context, "village_name", "") or ""
            ).strip()
            scope = explicit_village or (
                context_village if context_village and context_village in span else ""
            )
            if scope:
                entry.provenance.append(f"village_anchor:{scope}")
                entry.confidence = max(entry.confidence, 0.6)
            return
        if explicit_village:
            explicit_key = _normalize(explicit_village)
            explicit_candidates = [
                item
                for item in candidates
                if _normalize(item[1]) == explicit_key
            ]
            if explicit_candidates:
                candidates = explicit_candidates
        entity_keys = {
            str(getattr(item[2], "entity_uri", "") or "")
            or f"{item[1]}|{','.join(str(value) for value in getattr(item[2], 'bsms', []) or [])}"
            for item in candidates
        }
        if len(entity_keys) > 1:
            names = list(dict.fromkeys(item[1] for item in candidates))
            entry.provenance.append(
                "village_anchor_ambiguous:" + ",".join(names[:8])
            )
            entry.confidence = max(entry.confidence, 0.3)
            return
        candidates.sort(key=lambda item: -item[0])
        _, vn, ge = candidates[0]
        entry.anchor_bsms = list(dict.fromkeys([*entry.anchor_bsms, *ge.bsms]))
        if self._entity_level_bound(entry):
            # Keep the legacy extent field scoped to the named village for an
            # L1 facility mention, while the exact point's nearby parcels stay
            # auditable in ``related_parcel_bsms`` and its own identity stays
            # in ``feature_bsm``.
            entry.source_bsms = list(dict.fromkeys(ge.bsms))
        else:
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

    def _register_poi(
        self,
        pois: List[Any],
        parcels: Optional[List[Any]] = None,
        centroid_cache: Optional[Dict[str, Any]] = None,
        source_layer: str = "annotations_current",
        spatial_index: Any = None,
    ) -> None:
        for p in pois:
            raw = getattr(p, "_raw", {}) or {}
            properties = getattr(p, "properties", {}) or {}
            if not isinstance(raw, dict):
                raw = {}
            if not isinstance(properties, dict):
                properties = {}
            name_keys = (
                "text", "name", "label", "facility_name", "注记", "名称",
                "地质灾害点名称",
            )
            attribute_values: list[str] = []
            for attr in (
                *name_keys,
                "address", "地址", "location", "位置", "village", "村",
                "村名", "natural_village", "自然村", "settlement", "组",
                "类型", "hazard_type", "大小", "scale",
            ):
                value = getattr(p, attr, "") if hasattr(p, attr) else ""
                value = value or properties.get(attr) or raw.get(attr) or ""
                if isinstance(value, (list, tuple, set)):
                    values = [str(item).strip() for item in value if str(item).strip()]
                else:
                    values = [
                        line.strip()
                        for line in str(value or "").replace("\r\n", "\n").split("\n")
                        if line.strip()
                    ]
                attribute_values.extend(values)
            text = ""
            for attr in name_keys:
                for value in (
                    getattr(p, attr, "") if hasattr(p, attr) else "",
                    properties.get(attr),
                    raw.get(attr),
                ):
                    for line in str(value or "").replace("\r\n", "\n").split("\n"):
                        clean_line = line.strip()
                        if clean_line:
                            text = clean_line
                            break
                    if text:
                        break
                if text:
                    break
            if not text:
                continue
            source_aliases = list(dict.fromkeys(attribute_values))
            category = getattr(p, "category", "") or ""
            geom = getattr(p, "geometry", None) or {}  # getattr intentional: heterogeneous feature objects
            feature_bsm = str(getattr(p, "bsm", "") or "").strip() or None
            raw = getattr(p, "_raw", {}) or {}
            source_feature_id = _source_feature_identity(p, "facility")
            semantic_label, semantic_aliases, semantic_fact_refs = (
                self._source_semantic_overlay(source_feature_id, text)
            )
            canonical_name = semantic_label or text
            annotation_kind = str(
                raw.get("分类") or raw.get("category") or category or ""
            ).strip()
            layer_type = str(
                getattr(p, "layer_type", "") or raw.get("layer_type") or ""
            ).strip()
            is_scope_annotation = (
                annotation_kind in {"村名", "自然村"}
                or layer_type == "external_natural_village"
            )
            geometry_ref = f"bundle://feature/{feature_bsm}" if feature_bsm else None
            role = (
                "hazard"
                if source_layer in {
                    "hazard_points",
                    "geological_hazard_points",
                    "geological_hazard_point",
                }
                else "facility"
                if source_layer == "facilities_current" or category == "现状设施点"
                else "landmark"
            )
            source_bsms = self._poi_source_bsms(
                geom,
                parcels,
                centroid_cache,
                self._parcel_geometry_cache,
                spatial_index,
            )

            if is_scope_annotation:
                self._add_entry(
                    PlaceEvidenceEntry(
                        canonical_name=canonical_name,
                        aliases=list(dict.fromkeys([*source_aliases, *semantic_aliases])),
                        entity_refs=[f"scope:{source_feature_id or canonical_name}"],
                        entity_types=["scope"],
                        role="scope",
                        related_parcel_bsms=list(source_bsms),
                        source_bsms=list(source_bsms),
                        provenance=[
                            "external_scope",
                            f"bundle:{source_layer}",
                            *( ["source_semantic:accepted"] if semantic_label else [] ),
                        ],
                        l1_fact_refs=semantic_fact_refs,
                        l1_snapshot_ref=str(
                            getattr(self.context, "l1_snapshot_ref", "") or ""
                        ),
                        bundle_snapshot_digest=str(
                            getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                            or ""
                        ),
                        confidence=0.9 if semantic_label or source_feature_id else 0.8,
                    )
                )
                continue

            # General entity resolution: a POI with the same bundle feature
            # identity as an existing entity is the same real-world place.
            # Geometry remains owned by the bundle and is never cached here.
            point_key = self._point_identity_key(role, geom)
            target = self._point_identity_index.get(point_key) if point_key else None
            target = target or next(
                (
                    entry
                    for entry in self.entries
                    if feature_bsm
                    and entry.role == role
                    and str(entry.feature_bsm or "").strip() == feature_bsm
                ),
                None,
            )
            if target is not None:
                target.source_bsms = list(
                    dict.fromkeys([*target.source_bsms, *source_bsms])
                )
                target.feature_bsm = target.feature_bsm or feature_bsm
                target.related_parcel_bsms = list(
                    dict.fromkeys([*target.related_parcel_bsms, *source_bsms])
                )
                for alias in source_aliases:
                    if alias and alias != target.canonical_name and alias not in target.aliases:
                        target.aliases.append(alias)
                for alias in semantic_aliases:
                    if alias and alias != target.canonical_name and alias not in target.aliases:
                        target.aliases.append(alias)
                target.l1_fact_refs = list(
                    dict.fromkeys([*target.l1_fact_refs, *semantic_fact_refs])
                )
                if semantic_label and "source_semantic:accepted" not in target.provenance:
                    target.provenance.append("source_semantic:accepted")
                if f"poi:{text}" not in target.entity_refs:
                    target.entity_refs.append(f"poi:{text}")
                if "poi" not in target.provenance:
                    target.provenance.append("poi")
                target.confidence = max(target.confidence, 0.5)
                if point_key:
                    self._point_identity_index[point_key] = target
                continue

            entry = PlaceEvidenceEntry(
                canonical_name=canonical_name,
                aliases=list(dict.fromkeys([*source_aliases, *semantic_aliases])),
                entity_refs=[f"poi:{canonical_name}"],
                entity_types=[role],
                role=role,
                feature_bsm=feature_bsm,
                source_feature_id=source_feature_id or None,
                source_layer=source_layer,
                source_bsm=feature_bsm,
                related_parcel_bsms=list(source_bsms),
                source_bsms=source_bsms,
                geometry_ref=geometry_ref,
                provenance=[
                    "poi",
                    *( ["source_semantic:accepted"] if semantic_label else [] ),
                ],
                l1_fact_refs=semantic_fact_refs,
                confidence=0.95 if semantic_label else 0.5,
            )
            self._add_entry(entry)
            if point_key:
                self._point_identity_index[point_key] = entry

    @staticmethod
    def _point_identity_key(
        role: str,
        geometry: Any,
    ) -> tuple[str, float, float] | None:
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            return None
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            return None
        try:
            return (str(role), round(float(coordinates[0]), 7), round(float(coordinates[1]), 7))
        except (TypeError, ValueError):
            return None

    def _poi_source_bsms(
        self,
        geometry: Any,
        parcels: Optional[List[Any]] = None,
        centroid_cache: Optional[Dict[str, Any]] = None,
        geometry_cache: Optional[Dict[str, Any]] = None,
        spatial_index: Any = None,
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
                geometry_cache=geometry_cache,
                spatial_index=spatial_index,
            )
        except Exception:
            return []

    #: KG entity types that can carry a locatable name -> (role, entity_types)
    _KG_NAMEABLE_TYPES = {
        "facility": ("facility", ("facility",)),
        "water_body": ("water", ("water_body", "water")),
        "road": ("road", ("road",)),
        "administrative_village": ("village", ("village", "administrative_village")),
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

            from app.infrastructure.kg.ontology import PLN, GeoPredicates, SemanticPredicates

            for s, _, o in graph.triples((None, RDF.type, None)):
                type_fragment = str(o).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                role_key = "".join(
                    ("_" if index and char.isupper() else "") + char.lower()
                    for index, char in enumerate(type_fragment)
                )
                mapping = self._KG_NAMEABLE_TYPES.get(role_key)
                if mapping is None:
                    continue
                raw_name = self._first_label(graph, s)
                role, entity_types = mapping
                source_feature_id = str(graph.value(s, PLN.source_feature_id) or "").strip()
                decision = self.source_semantic_decisions.get(source_feature_id)
                decision_status = (
                    getattr(decision, "status", "")
                    if decision is not None and not isinstance(decision, dict)
                    else str((decision or {}).get("status", ""))
                )
                decision_type = (
                    getattr(decision, "semantic_type", "")
                    if decision is not None and not isinstance(decision, dict)
                    else str((decision or {}).get("semantic_type", ""))
                )
                bsm = str(graph.value(s, PLN.bsm) or "").strip()
                if not raw_name and not bsm and not source_feature_id:
                    # A nameless, geometry-less KG node has no bounded
                    # identity that the evidence boundary can safely expose.
                    continue
                name = (
                    decision_type.strip()
                    if decision_status == "accepted" and decision_type.strip()
                    else raw_name or role
                )
                centroid = None
                try:
                    lon = graph.value(s, PLN.lon)
                    lat = graph.value(s, PLN.lat)
                    if lon is not None and lat is not None:
                        centroid = (float(lon), float(lat))
                except (TypeError, ValueError):
                    centroid = None
                geometry_ref = (
                    f"bundle://feature/{bsm}"
                    if bsm
                    else None
                )
                aliases: List[str] = []
                if raw_name != name:
                    aliases.append(raw_name)
                try:
                    ft = graph.value(s, PLN.facility_type)
                    if ft:
                        ft_text = str(ft).strip()
                        if ft_text and ft_text != name:
                            aliases.append(ft_text)
                except Exception:
                    pass
                relation_refs = self._kg_relation_refs(graph, s)
                source_feature_id = str(graph.value(s, PLN.source_feature_id) or "").strip() or None
                source_layer = str(graph.value(s, SemanticPredicates.gis_type_ref) or "").strip() or None
                if role == "road" and source_layer in {
                    "admin_boundary_line",
                    "contour_line",
                }:
                    # Boundary and contour lines are real KG spatial entities,
                    # but they are not transport-road evidence. This is an
                    # integrity diagnostic for legacy or externally supplied
                    # KG data, not a semantic fallback.
                    logger.warning(
                        "[PlaceEvidenceIndex] rejected invalid Road typing: "
                        "entity=%s source_layer=%s; rebuild the KG with the "
                        "AdministrativeBoundary/ContourLine types",
                        s,
                        source_layer,
                    )
                    continue
                confidence = 0.7 if bsm else (0.6 if centroid else 0.4)
                entry = PlaceEvidenceEntry(
                    canonical_name=name,
                    aliases=list(dict.fromkeys(aliases)),
                    entity_refs=[str(s)],
                    entity_types=list(entity_types),
                    role=role,
                    feature_bsm=bsm or None,
                    source_feature_id=source_feature_id,
                    source_layer=source_layer,
                    source_bsm=bsm or None,
                    source_bsms=[bsm] if bsm else [],
                    geometry_ref=geometry_ref,
                    provenance=["kg"],
                    confidence=confidence,
                    relation_refs=relation_refs,
                    # L1 support is merged from the typed L1 entry below;
                    # this KG projection only carries the source-semantic
                    # decision marker and keeps topology/entity refs.
                    l1_fact_refs=[],
                    l1_snapshot_ref=str(
                        getattr(self.context, "l1_snapshot_ref", "") or ""
                    ),
                )
                if decision_status == "accepted" and decision_type.strip():
                    entry.provenance.append("source_semantic:accepted")
                if source_feature_id and not entry.feature_bsm:
                    workspace = getattr(self.context, "workspace", None)
                    for group_name in ("points", "lines", "polygons"):
                        group = getattr(workspace, group_name, None) if workspace is not None else None
                        if group is None or not hasattr(group, "keys"):
                            continue
                        found = False
                        for layer_name in group.keys():
                            for feature in group.get(layer_name) or []:
                                raw = getattr(feature, "_raw", {}) or {}
                                raw_id = str(
                                    raw.get("source_feature_id")
                                    or getattr(feature, "source_feature_id", "")
                                    or ""
                                ).strip()
                                if raw_id != source_feature_id:
                                    continue
                                feature_bsm = str(getattr(feature, "bsm", "") or "").strip()
                                if feature_bsm:
                                    entry.feature_bsm = feature_bsm
                                    entry.source_bsm = feature_bsm
                                entry.source_layer = str(layer_name)
                                found = True
                                break
                            if found:
                                break
                        if found:
                            break
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
                                geometry_cache=self._parcel_geometry_cache,
                                spatial_index=self._parcel_spatial_index,
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
        except Exception as exc:
            logger.warning(
                "[PlaceEvidenceIndex] KG entity indexing failed: %s",
                exc,
                exc_info=True,
            )

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
        def _index(indexed: PlaceEvidenceEntry) -> None:
            key = _normalize(indexed.canonical_name)
            if key:
                entries = self._by_canonical.setdefault(key, [])
                if indexed not in entries:
                    entries.append(indexed)
                self._index_name_key("canonical", key)
            for alias in indexed.aliases:
                alias_key = _normalize(alias)
                if alias_key:
                    aliases = self._by_alias.setdefault(alias_key, [])
                    if indexed not in aliases:
                        aliases.append(indexed)
                    self._index_name_key("alias", alias_key)
            identity = self._source_identity_key(indexed)
            if identity:
                self._identity_index[(indexed.role, identity)] = indexed
            self._index_coordinate(indexed)

        # A shared feature BSM/source_feature_id is the strongest identity
        # signal.  Semantic overlays are allowed to rename an entity, so this
        # check must happen before name-based merging.
        identity_target = self._identity_merge_target(entry)
        if identity_target is not None:
            self._merge_into(identity_target, entry)
            _index(identity_target)
            return

        # Same coordinates remain a safe co-location identity signal.  Names
        # alone are not identity when source geometries disagree.
        coord_target = self._coordinate_merge_target(entry)
        if coord_target is not None:
            self._merge_into(coord_target, entry)
            _index(coord_target)
            return
        name_target = self._name_merge_target(entry)
        if name_target is not None:
            self._merge_into(name_target, entry)
            _index(name_target)
            return
        key = _normalize(entry.canonical_name)
        existing_entries = self._by_canonical.get(key, [])
        merge_target = self._canonical_merge_target(entry, existing_entries)
        if merge_target is not None:
            self._merge_into(merge_target, entry)
            _index(merge_target)
        else:
            self.entries.append(entry)
            _index(entry)

    def _index_name_key(self, kind: str, key: str) -> None:
        """Index name keys for bounded substring candidate recall."""
        value = str(key or "").strip()
        if not value:
            return
        marker = (str(kind), value)
        if len(value) < 2:
            self._short_name_keys.add(marker)
            return
        for index in range(len(value) - 1):
            self._name_ngrams.setdefault(value[index:index + 2], set()).add(marker)

    def _substring_name_keys(self, mention: str) -> set[tuple[str, str]]:
        """Return only canonical/alias keys that can contain the mention."""
        value = str(mention or "").strip()
        if len(value) < 2:
            return {
                ("canonical", key) for key in self._by_canonical
            } | {
                ("alias", key) for key in self._by_alias
            }
        keys: set[tuple[str, str]] = set(self._short_name_keys)
        for index in range(len(value) - 1):
            keys.update(self._name_ngrams.get(value[index:index + 2], set()))
        return keys

    def _identity_merge_target(
        self, entry: PlaceEvidenceEntry
    ) -> Optional[PlaceEvidenceEntry]:
        identity = self._source_identity_key(entry)
        if not identity:
            return None
        return self._identity_index.get((entry.role, identity))

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
        entry_identity = cls._source_identity_key(entry)
        existing_identities = {
            identity
            for existing in existing_entries
            if (identity := cls._source_identity_key(existing))
        }
        if entry_identity and existing_identities:
            for existing in existing_entries:
                if cls._source_identity_key(existing) == entry_identity:
                    return existing
            return None
        if not entry_identity and len(existing_identities) > 1:
            return None
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
        # Geometry is intentionally opaque at the EvidenceGraph boundary.
        # Keep bundle refs as distinct authoritative geometry identities for
        # ambiguity checks; only WKT is parsed here when an older KG entry
        # still carries source geometry internally.
        if value.startswith("bundle://"):
            return value
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

    @staticmethod
    def _source_identity_key(entry: "PlaceEvidenceEntry") -> Optional[str]:
        """Return an identity key without retaining source geometry in the index."""
        for value in (
            getattr(entry, "feature_bsm", ""),
            getattr(entry, "source_bsm", ""),
            getattr(entry, "source_feature_id", ""),
        ):
            normalized = str(value or "").strip()
            if normalized:
                return normalized
        return None

    def _name_merge_target(
        self, entry: PlaceEvidenceEntry
    ) -> Optional[PlaceEvidenceEntry]:
        """Merge only when the source explicitly shares a name or alias."""
        keys = {
            _normalize(entry.canonical_name),
            *(_normalize(str(a)) for a in entry.aliases if a),
        }
        keys.discard("")
        if not keys:
            return None
        entry_geometry = self._authoritative_geometry_key(entry)
        candidate_entries: List[PlaceEvidenceEntry] = []
        seen_candidates: set[int] = set()
        for key in keys:
            for existing in (
                *self._by_canonical.get(key, ()),
                *self._by_alias.get(key, ()),
            ):
                marker = id(existing)
                if marker not in seen_candidates:
                    seen_candidates.add(marker)
                    candidate_entries.append(existing)
        matching: List[PlaceEvidenceEntry] = []
        for existing in candidate_entries:
            if existing.role != entry.role:
                continue
            existing_keys = {
                _normalize(existing.canonical_name),
                *(_normalize(str(a)) for a in existing.aliases if a),
            }
            existing_keys.discard("")
            if existing_keys & keys:
                entry_identity = self._source_identity_key(entry)
                existing_identity = self._source_identity_key(existing)
                if (
                    entry_identity
                    and existing_identity
                    and entry_identity != existing_identity
                ):
                    continue
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

    def _coordinate_xy(
        self,
        entry: PlaceEvidenceEntry,
    ) -> tuple[float, float] | None:
        reference = str(entry.geometry_ref or "").strip()
        if not reference:
            return None
        if reference in self._coordinate_cache:
            return self._coordinate_cache[reference]
        coordinate: tuple[float, float] | None = None
        if reference.startswith("resource:"):
            catalog = getattr(self.context, "data_resource_catalog", None)
            if catalog is not None:
                try:
                    payload = catalog.resolve_geometry(resource_ref=reference)
                    if payload:
                        from shapely.geometry import shape

                        geometry = shape(payload)
                        if not geometry.is_empty and geometry.is_valid:
                            point = geometry.representative_point()
                            coordinate = (float(point.x), float(point.y))
                except Exception:
                    coordinate = None
        else:
            try:
                from app.spatial.grounding.coordinate_identity import point_xy

                coordinate = point_xy(reference)
            except Exception:
                coordinate = None
        self._coordinate_cache[reference] = coordinate
        return coordinate

    @staticmethod
    def _coordinate_cell(
        coordinate: tuple[float, float],
        *,
        tolerance: float = 1e-5,
    ) -> tuple[int, int]:
        from math import floor

        return (
            floor(coordinate[0] / tolerance),
            floor(coordinate[1] / tolerance),
        )

    def _index_coordinate(self, entry: PlaceEvidenceEntry) -> None:
        coordinate = self._coordinate_xy(entry)
        if coordinate is None:
            return
        cell_x, cell_y = self._coordinate_cell(coordinate)
        bucket = self._coordinate_index.setdefault(
            (entry.role, cell_x, cell_y),
            [],
        )
        if all(existing is not entry for _x, _y, existing in bucket):
            bucket.append((coordinate[0], coordinate[1], entry))

    def _coordinate_merge_target(
        self, entry: PlaceEvidenceEntry
    ) -> Optional[PlaceEvidenceEntry]:
        """同坐标 + 同角色 的既有条目视为同一真实实体（ER 原则）。"""
        coordinate = self._coordinate_xy(entry)
        if coordinate is None:
            return None
        tolerance = 1e-5
        cell_x, cell_y = self._coordinate_cell(
            coordinate,
            tolerance=tolerance,
        )
        for delta_x in (-1, 0, 1):
            for delta_y in (-1, 0, 1):
                for x, y, existing in self._coordinate_index.get(
                    (entry.role, cell_x + delta_x, cell_y + delta_y),
                    (),
                ):
                    if (
                        abs(x - coordinate[0]) < tolerance
                        and abs(y - coordinate[1]) < tolerance
                    ):
                        return existing
        return None

    @staticmethod
    def _merge_into(target: PlaceEvidenceEntry, source: PlaceEvidenceEntry) -> None:
        """Merge ``source`` into ``target``, accumulating evidence (ER merge)."""
        target.aliases = list(dict.fromkeys([*target.aliases, *source.aliases]))
        source_name = str(source.canonical_name or "").strip()
        target_name = str(target.canonical_name or "").strip()
        if source_name and source_name != target_name:
            target.aliases = list(dict.fromkeys([*target.aliases, source_name]))
        if not target_name and source_name:
            target.canonical_name = source_name
        target.entity_refs = list(dict.fromkeys([*target.entity_refs, *source.entity_refs]))
        target.entity_types = list(dict.fromkeys([*target.entity_types, *source.entity_types]))
        target.feature_bsm = target.feature_bsm or source.feature_bsm
        target.source_feature_id = target.source_feature_id or source.source_feature_id
        target.source_layer = target.source_layer or source.source_layer
        target.source_bsm = target.source_bsm or source.source_bsm
        target.anchor_bsms = list(
            dict.fromkeys([*target.anchor_bsms, *source.anchor_bsms])
        )
        target.related_parcel_bsms = list(
            dict.fromkeys([*target.related_parcel_bsms, *source.related_parcel_bsms])
        )
        target.source_bsms = list(
            dict.fromkeys([*target.source_bsms, *source.source_bsms])
        )
        target.provenance = list(dict.fromkeys([*target.provenance, *source.provenance]))
        target.relation_refs = list(
            dict.fromkeys([*target.relation_refs, *source.relation_refs])
        )
        target.l1_fact_refs = list(
            dict.fromkeys([*target.l1_fact_refs, *source.l1_fact_refs])
        )
        target.l1_snapshot_ref = target.l1_snapshot_ref or source.l1_snapshot_ref
        target.bundle_snapshot_digest = (
            target.bundle_snapshot_digest or source.bundle_snapshot_digest
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

        for kind, key in sorted(self._substring_name_keys(norm)):
            entries = (
                self._by_canonical.get(key, [])
                if kind == "canonical"
                else self._by_alias.get(key, [])
            )
            if norm and norm in key:
                for entry in entries:
                    seen[id(entry)] = entry
                trace.append({
                    "step": "substring" if kind == "canonical" else "alias_substring",
                    "matched": [e.canonical_name for e in entries],
                })
            elif norm and key and key in norm:
                # Forward substring: a long mention such as
                # '金田河沿线农业发展区' contains the entity '金田河'.
                for entry in entries:
                    seen[id(entry)] = entry
                trace.append(
                    {
                        "step": (
                            "mention_contains_entity"
                            if kind == "canonical"
                            else "alias_contains_entity"
                        ),
                        "matched": [e.canonical_name for e in entries],
                    }
                )

        for entry in seen.values():
            evidence = score_candidate(mention, entry, role=role, hints=hints, context=self.context)
            score = total(evidence)
            context_snapshot = str(
                getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                or getattr(entry, "bundle_snapshot_digest", "")
                or ""
            )
            candidates.append(
                PlaceResolutionCandidate(
                    entity_ref=_preferred_entity_ref(entry),
                    entity_type=entry.entity_types[0] if entry.entity_types else entry.role,
                    role=entry.role,
                    canonical_name=entry.canonical_name,
                    aliases=list(entry.aliases),
                    geometry_ref=entry.geometry_ref,
                    feature_bsm=entry.feature_bsm,
                    source_feature_id=entry.source_feature_id,
                    source_layer=entry.source_layer,
                    source_bsm=entry.source_bsm,
                    anchor_bsms=list(entry.anchor_bsms),
                    related_parcel_bsms=list(entry.related_parcel_bsms),
                    source_bsms=list(entry.source_bsms),
                    score=round(score, 4),
                    evidence_refs=list(entry.provenance),
                    relation_refs=list(entry.relation_refs),
                    l1_fact_refs=list(entry.l1_fact_refs),
                    l1_snapshot_ref=str(
                        entry.l1_snapshot_ref
                        or getattr(self.context, "l1_snapshot_ref", "")
                        or ""
                    ),
                    bundle_snapshot_digest=context_snapshot,
                    evidence=evidence,
                )
            )

        # A single report observation with an explicit village anchor is a
        # semantic scope, not merely another score.  Use it to narrow global
        # same-name bundle points; if several anchored observations survive,
        # retain them as an explicit ambiguity set.
        anchored = [
            candidate
            for candidate in candidates
            if "l1_fact" in candidate.evidence_refs
            and any(
                str(ref).startswith("village_anchor:")
                for ref in candidate.evidence_refs
            )
        ]
        if anchored:
            anchored_spatial = [
                candidate for candidate in anchored if _candidate_has_spatial(candidate)
            ]
            if anchored_spatial:
                candidates = anchored
            else:
                # Keep same-name spatial candidates only as a bounded join
                # input.  They are not auto-selected here; the explicit
                # village-scoped resolver below must validate the join.
                companion_spatial = [
                    candidate
                    for candidate in candidates
                    if candidate not in anchored and _candidate_has_spatial(candidate)
                ]
                candidates = [*anchored, *companion_spatial]
            trace.append({
                "step": "l1_scope_narrow",
                "candidate_count": len(anchored),
                "companion_spatial_count": max(0, len(candidates) - len(anchored)),
            })

        if str(role or "unknown").strip().lower() != "unknown":
            before_role_filter = len(candidates)
            candidates = [
                candidate
                for candidate in candidates
                if _role_compatible(candidate, role)
            ]
            trace.append({
                "step": "role_filter",
                "role": str(role),
                "before": before_role_filter,
                "after": len(candidates),
            })

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

    def semantic_label_probes(
        self,
        mention: str,
        *,
        roles: set[str] | frozenset[str] | tuple[str, ...] = (),
        max_probes: int = 12,
    ) -> list[tuple[str, str]]:
        """Return bounded source-backed partial-name probes.

        A user query often contains a meaningful place prefix rather than a
        complete source label: ``炉池自然村在哪里`` must expose ``炉池`` so
        the indexed hazard labels ``炉池赖木生`` and friends can be inspected.
        The n-gram index is the only recall mechanism here.  It returns
        probes that are present in canonical names/aliases already registered
        from KG, L1 and the Bundle; it never manufactures a name or a spatial
        identity from query text.
        """
        normalized = _normalize(mention)
        if len(normalized) < 2:
            return []
        allowed_roles = {
            str(value).strip()
            for value in roles
            if str(value).strip()
        }
        ranked: dict[tuple[str, str], tuple[int, int]] = {}
        seen_entries: dict[int, tuple[str, str, int]] = {}
        for offset in range(len(normalized) - 1):
            ngram = normalized[offset:offset + 2]
            if not ngram.strip():
                continue
            for kind, key in self._name_ngrams.get(ngram, set()):
                entries = (
                    self._by_canonical.get(key, [])
                    if kind == "canonical"
                    else self._by_alias.get(key, [])
                )
                for entry in entries:
                    role = str(getattr(entry, "role", "") or "").strip()
                    if allowed_roles and role not in allowed_roles:
                        continue
                    overlap, probe = _longest_indexed_overlap(normalized, key)
                    if overlap < 2 or not probe:
                        continue
                    entry_key = id(entry)
                    previous = seen_entries.get(entry_key)
                    current = (probe, role, overlap)
                    if previous is None or current[2] > previous[2]:
                        seen_entries[entry_key] = current

        for probe, role, overlap in seen_entries.values():
            key = (probe, role)
            previous = ranked.get(key)
            rank = (overlap, sum(1 for item in seen_entries.values() if item[0] == probe and item[1] == role))
            if previous is None or rank > previous:
                ranked[key] = rank
        ordered = sorted(
            ranked,
            key=lambda item: (-ranked[item][0], -ranked[item][1], item[1], item[0]),
        )
        return ordered[: max(1, int(max_probes or 1))]

    def query_role_candidates(
        self,
        role: str,
        *,
        max_candidates: int = 64,
    ) -> PlaceResolutionResult:
        """Return a bounded source-backed candidate domain for one role.

        This is the deliberate no-name path for L1 facts such as a named
        road or river whose current GIS layer has no matching label.  It
        returns only entries already carrying source geometry/identity and
        never promotes one member of the domain to an exact match.
        """

        normalized_role = str(role or "unknown").strip().casefold()
        eligible = [
            entry
            for entry in self.entries
            if _role_compatible(entry, normalized_role)
            and (
                str(getattr(entry, "feature_bsm", "") or "").strip()
                or str(getattr(entry, "source_bsm", "") or "").strip()
                or str(getattr(entry, "geometry_ref", "") or "").strip()
            )
        ]
        names = list(dict.fromkeys(
            str(getattr(entry, "canonical_name", "") or "").strip()
            for entry in eligible
            if str(getattr(entry, "canonical_name", "") or "").strip()
        ))
        all_candidates: list[PlaceResolutionCandidate] = []
        seen: set[tuple[str, str, str]] = set()
        for name in names:
            result = self.resolve_mention(name, role=normalized_role)
            for candidate in result.candidates:
                key = (
                    str(getattr(candidate, "entity_ref", "") or ""),
                    str(getattr(candidate, "feature_bsm", "") or ""),
                    str(getattr(candidate, "geometry_ref", "") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                all_candidates.append(candidate)
        all_candidates.sort(
            key=lambda item: (
                str(getattr(item, "source_layer", "") or ""),
                str(getattr(item, "source_bsm", "") or getattr(item, "feature_bsm", "") or ""),
                str(getattr(item, "entity_ref", "") or ""),
            )
        )
        requested_limit = max(1, int(max_candidates or 1))
        bounded = all_candidates[:requested_limit]
        trace = [{
            "step": "role_candidate_recall",
            "role": normalized_role,
            "candidate_total": len(all_candidates),
            "candidate_returned": len(bounded),
            "candidate_limit": requested_limit,
            "candidates_truncated": len(all_candidates) > len(bounded),
            "selection_required": len(all_candidates) != 1,
        }]
        if not bounded:
            status = "unresolved"
            selected = None
            reason = "no source-backed candidate for role"
        elif len(all_candidates) == 1:
            status = "resolved"
            selected = bounded[0].entity_ref
            reason = None
        else:
            status = "ambiguous"
            selected = None
            reason = "role candidate domain requires spatial or semantic selection"
        return PlaceResolutionResult(
            mention=normalized_role,
            normalized_name=normalized_role,
            status=status,
            selected_entity_ref=selected,
            candidates=bounded,
            evidence_refs=[candidate.entity_ref for candidate in bounded],
            query_trace=trace,
            unresolved_reason=reason,
            context_version=".".join(str(v) for v in self.version),
        )

    def query_facility_bsms(
        self,
        village_name: str,
        label: str,
        *,
        role: str = "facility",
        hints: str = "",
    ) -> PlaceResolutionResult:
        """Resolve ``village + facility`` without flattening feature identity.

        The returned candidates expose ``feature_bsm`` for the actual point
        and ``related_parcel_bsms``/``anchor_bsms`` for its spatial context.
        A village-scoped query never falls back to a global same-name point;
        it returns ``unresolved`` when no candidate carries the requested
        village evidence and ``ambiguous`` when multiple source geometries
        remain.
        """
        result = self.resolve_mention(
            label,
            role=role,
            hints=" ".join(value for value in (village_name, hints) if value),
        )
        village_names = _scope_name_tokens(self.context, village_name)
        village_keys = {_normalize(value) for value in village_names if _normalize(value)}
        scoped = [
            candidate
            for candidate in result.candidates
            if any(
                self._candidate_matches_village_scope(candidate, name)
                for name in village_names
            )
        ]
        if not scoped:
            label_key = _normalize(label)
            typed_scope_refs: set[str] = set()
            typed_scope_match = False
            for fact in _context_l1_items(self.context):
                fact_label = _normalize(
                    str(
                        getattr(fact, "normalized_name", "")
                        or getattr(fact, "mention", "")
                        or ""
                    )
                )
                if not fact_label or not (
                    fact_label == label_key
                    or fact_label in label_key
                    or label_key in fact_label
                ):
                    continue
                if set(_normalize(name) for name in _fact_scope_names(fact)) & village_keys:
                    typed_scope_match = True
                    typed_scope_refs.update(
                        str(value).strip()
                        for value in (
                            *(getattr(fact, "source_refs", None) or []),
                            getattr(fact, "fact_id", ""),
                        )
                        if str(value).strip()
                    )
            if typed_scope_refs or typed_scope_match:
                typed_semantic_candidates = [
                    candidate
                    for candidate in result.candidates
                    if not (
                        str(candidate.feature_bsm or "").strip()
                        or str(candidate.source_bsm or "").strip()
                        or str(candidate.geometry_ref or "").strip()
                    )
                    and typed_scope_refs.intersection(
                        set(str(value).strip() for value in candidate.l1_fact_refs)
                    )
                ]
                spatial_candidates = [
                    candidate
                    for candidate in result.candidates
                    if (
                        str(candidate.feature_bsm or "").strip()
                        or str(candidate.source_bsm or "").strip()
                        or str(candidate.geometry_ref or "").strip()
                    )
                ]
                if (
                    (typed_semantic_candidates or typed_scope_match)
                    and len(spatial_candidates) == 1
                ):
                    scoped = spatial_candidates
        # L1 may carry the village scope while the actual bundle point is a
        # separate same-name entry (we intentionally do not merge a
        # geometry-less semantic entry into a source geometry).  Join the
        # semantic scope onto the unique spatial candidates without changing
        # their feature identity.
        semantic_scope_candidates = [
            candidate
            for candidate in scoped
            if not (
                str(candidate.feature_bsm or "").strip()
                or str(candidate.source_bsm or "").strip()
                or str(candidate.geometry_ref or "").strip()
            )
        ]
        spatial_candidates = [
            candidate
            for candidate in result.candidates
            if (
                str(candidate.feature_bsm or "").strip()
                or str(candidate.source_bsm or "").strip()
                or str(candidate.geometry_ref or "").strip()
            )
        ]
        if semantic_scope_candidates and spatial_candidates:
            scope_refs = list(
                dict.fromkeys(
                    ref
                    for candidate in semantic_scope_candidates
                    for ref in candidate.evidence_refs
                )
            )
            l1_fact_refs = list(
                dict.fromkeys(
                    ref
                    for candidate in semantic_scope_candidates
                    for ref in candidate.l1_fact_refs
                )
            )
            scoped = [
                candidate.model_copy(
                    update={
                        "evidence_refs": list(
                            dict.fromkeys(
                                [*candidate.evidence_refs, *scope_refs]
                            )
                        ),
                        "l1_fact_refs": list(
                            dict.fromkeys(
                                [*candidate.l1_fact_refs, *l1_fact_refs]
                            )
                        ),
                        "l1_snapshot_ref": (
                            candidate.l1_snapshot_ref
                            or semantic_scope_candidates[0].l1_snapshot_ref
                        ),
                        "bundle_snapshot_digest": (
                            candidate.bundle_snapshot_digest
                            or semantic_scope_candidates[0].bundle_snapshot_digest
                        ),
                    }
                )
                for candidate in spatial_candidates
            ]
        trace = [*result.query_trace, {
            "step": "village_scope",
            "village": village_name,
            "candidate_count": len(scoped),
        }]
        matching_scopes = [
            scope.scope_id
            for scope in self.semantic_scopes
            if any(
                _normalize(
                    getattr(mention, "normalized_name", "")
                    or getattr(mention, "name", "")
                ) in village_keys
                for mention in getattr(scope, "scope_mentions", [])
            )
        ]
        trace.append({"step": "l1_semantic_scopes", "scope_refs": matching_scopes})
        if not scoped:
            return result.model_copy(update={
                "status": "unresolved",
                "selected_entity_ref": None,
                "candidates": result.candidates,
                "query_trace": trace,
                "unresolved_reason": "no candidate carries the requested village scope",
            })
        if len(scoped) == 1:
            selected = scoped[0]
            status = "resolved" if _candidate_has_spatial(selected) else "ambiguous"
            selected_ref = selected.entity_ref if status == "resolved" else None
            reason = None if status == "resolved" else "scoped candidate has no spatial evidence"
        else:
            status = "ambiguous"
            selected_ref = None
            reason = "multiple facility features remain in the village scope"
        return result.model_copy(update={
            "status": status,
            "selected_entity_ref": selected_ref,
            "candidates": scoped,
            "evidence_refs": [candidate.entity_ref for candidate in scoped],
            "query_trace": trace,
            "unresolved_reason": reason,
        })

    def _candidate_matches_village_scope(
        self,
        candidate: PlaceResolutionCandidate,
        village_name: str,
    ) -> bool:
        """Verify an exact feature against an explicit report-backed scope."""
        village_names = _scope_name_tokens(self.context, village_name)
        if not village_names:
            return False
        village_bsms = self.scope_bsms_for_names(village_names)
        candidate_bsms = {
            str(value).strip()
            for value in (
                *list(getattr(candidate, "related_parcel_bsms", None) or []),
            )
            if str(value).strip()
        }
        if village_bsms and candidate_bsms.intersection(village_bsms):
            return True

        candidate_l1_refs = {
            str(value).strip()
            for value in (getattr(candidate, "l1_fact_refs", None) or [])
            if str(value).strip()
        }
        if candidate_l1_refs:
            village_keys = {_normalize(value) for value in village_names}
            for fact in _context_l1_items(self.context):
                fact_refs = {
                    str(value).strip()
                    for value in (
                        getattr(fact, "fact_id", ""),
                        *(getattr(fact, "source_refs", None) or []),
                    )
                    if str(value).strip()
                }
                if not candidate_l1_refs.intersection(fact_refs):
                    continue
                if village_keys.intersection(
                    {_normalize(value) for value in _fact_scope_names(fact)}
                ):
                    return True

        kg = getattr(self.context, "kg", None)
        if kg is None or not hasattr(kg, "find_entities") or not hasattr(kg, "find_relations"):
            return False
        village_entities = []
        for village in village_names:
            try:
                village_entities.extend(kg.find_entities(name=village, limit=12) or [])
            except Exception:
                continue
        village_refs = {
            str(getattr(entity, "entity_ref", "") or "")
            for entity in village_entities
            if str(getattr(entity, "entity_ref", "") or "").strip()
            and "residentialcluster" not in str(getattr(entity, "entity_ref", "") or "").casefold()
            and "residential_cluster" not in str(getattr(entity, "entity_ref", "") or "").casefold()
        }
        if not village_refs:
            return False
        candidate_ref = str(getattr(candidate, "entity_ref", "") or "").strip()
        if not candidate_ref:
            return False
        try:
            relations = [
                *list(kg.find_relations(subject_ref=candidate_ref, limit=40) or []),
                *list(kg.find_relations(object_ref=candidate_ref, limit=40) or []),
            ]
        except Exception:
            return False
        return any(
            str(getattr(relation, "subject_ref", "") or "") in village_refs
            or str(getattr(relation, "object_ref", "") or "") in village_refs
            for relation in relations
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


def _longest_indexed_overlap(query: str, indexed_key: str) -> tuple[int, str]:
    """Find the longest contiguous query fragment already in an index key."""
    value = str(query or "")
    key = str(indexed_key or "")
    if len(value) < 2 or len(key) < 2:
        return 0, ""
    best_length = 0
    best_probe = ""
    for query_start in range(len(value)):
        for key_start in range(len(key)):
            length = 0
            while (
                query_start + length < len(value)
                and key_start + length < len(key)
                and value[query_start + length] == key[key_start + length]
            ):
                length += 1
            if length > best_length:
                best_length = length
                best_probe = value[query_start:query_start + length]
    return best_length, best_probe


def _normalize(name: str) -> str:
    if not name:
        return ""
    return name.strip().lower()


def _scope_name_tokens(context: Any, text: str) -> List[str]:
    """Extract explicit L1/external scope names without suffix synthesis."""
    raw = str(text or "").strip()
    if not raw:
        return []
    folded = raw.casefold()
    names: List[str] = []
    for fact in _context_l1_items(context):
        for scope in _scope_mentions_for_fact(fact):
            role = _scope_value(scope, "role").casefold()
            name = _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
            aliases = [
                _scope_value(scope, "name"),
                *(
                    [str(value) for value in getattr(scope, "aliases", [])]
                    if not isinstance(scope, dict)
                    else [str(value) for value in (scope.get("aliases") or [])]
                ),
            ]
            if (
                _is_scope_role(role)
                and name
                and any(value.strip().casefold() in folded for value in aliases + [name] if value.strip())
            ):
                names.append(name)
    gazetteer = getattr(context, "gazetteer", None)
    for entry in getattr(gazetteer, "entries", []) or []:
        if not _is_dynamic_gazetteer_scope(entry):
            continue
        canonical = str(getattr(entry, "name", "") or "").strip()
        values = [canonical, *(str(value) for value in (getattr(entry, "aliases", None) or []))]
        if any(value and value.casefold() in folded for value in values):
            if canonical:
                names.append(canonical)
    if names:
        return list(dict.fromkeys(names))
    for delimiter in ("、", "，", ",", "；", ";", "和", "与", "及"):
        raw = raw.replace(delimiter, "|")
    return [
        PlaceEvidenceIndex.normalize_mention(part.strip())
        for part in raw.split("|")
        if PlaceEvidenceIndex.normalize_mention(part.strip())
    ]


__all__ = ["PlaceEvidenceIndex"]
